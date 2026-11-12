"""
Tests for Issue #14: Do not refund cloud generation on unknown gateway timeout / status.

Verifies:
1. `_gateway_failure_is_definite` classification for all specified exception types.
2. Synchronous generation (`POST /api/studio/generate`):
   - Timeout (TimeoutError / socket.timeout / URLError): no refund, quota/credits intact,
     record remains queued, response is 200 with confirming=True, task_id equals client_task_id.
   - ConnectionRefusedError / socket.gaierror: refund immediately, 502 with refunded=True.
   - HTTP 4xx (except 408): refund immediately, 502 with refunded=True.
   - HTTP 5xx: no refund, 200 with confirming=True.
   - HTTP 408: no refund, 200 with confirming=True.
   - Unconfigured gateway (RuntimeError): refund immediately, 502 with refunded=True.
   - Request without requestId: generated client_task_id is recorded in DB before call,
     retrievable via /api/studio/tasks.
3. GenerationReconciler:
   - Gateway returns empty items and created_at > 30 mins: refunds once with "网关未收到任务，已退还".
     Running twice does not double-refund.
   - Gateway returns empty items and created_at < 30 mins: does not refund.
   - Gateway query raises exception: does not refund.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.server import (
    HandrawRequestHandler,
    GenerationReconciler,
    GatewayNotConfigured,
    _gateway_failure_is_definite,
    _parse_created_at_dt,
    create_channel_server,
)
from backend.services import (
    complete_cloud_generation,
    get_user_studio_task,
    get_wallet_quota_state,
    local_today_str,
    record_cloud_generation_task_id,
    refund_failed_cloud_generation,
    register_user,
)

ORIGIN = "http://handraw.test"


class GatewayFailureClassificationTests(unittest.TestCase):
    """Unit tests for _gateway_failure_is_definite exception classification."""

    def test_unconfigured_gateway_error_is_definite(self):
        exc = GatewayNotConfigured("未检测到本地生图网关配置 image-service.json")
        self.assertTrue(_gateway_failure_is_definite(exc))

    def test_plain_runtime_error_is_unknown(self):
        exc = RuntimeError("something went wrong on server")
        self.assertFalse(_gateway_failure_is_definite(exc))

    def test_connection_refused_is_definite(self):
        exc = urllib.error.URLError(ConnectionRefusedError(10061, "Connect call failed"))
        self.assertTrue(_gateway_failure_is_definite(exc))

        raw_exc = ConnectionRefusedError(10061, "Connect call failed")
        self.assertTrue(_gateway_failure_is_definite(raw_exc))

    def test_dns_resolution_failure_is_definite(self):
        exc = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        self.assertTrue(_gateway_failure_is_definite(exc))

        raw_exc = socket.gaierror(11001, "getaddrinfo failed")
        self.assertTrue(_gateway_failure_is_definite(raw_exc))

    def test_http_4xx_except_408_is_definite(self):
        for code in (400, 401, 403, 404, 422, 429):
            exc = urllib.error.HTTPError("http://gw/api", code, "Client Error", {}, None)
            self.assertTrue(_gateway_failure_is_definite(exc), f"HTTP {code} should be definite")

    def test_http_408_is_unknown(self):
        exc = urllib.error.HTTPError("http://gw/api", 408, "Request Timeout", {}, None)
        self.assertFalse(_gateway_failure_is_definite(exc))

    def test_timeouts_are_unknown(self):
        self.assertFalse(_gateway_failure_is_definite(TimeoutError("Operation timed out")))
        self.assertFalse(_gateway_failure_is_definite(socket.timeout("timed out")))
        self.assertFalse(_gateway_failure_is_definite(urllib.error.URLError(socket.timeout("timed out"))))
        self.assertFalse(_gateway_failure_is_definite(urllib.error.URLError(TimeoutError("timed out"))))

    def test_connection_reset_and_remote_disconnected_are_unknown(self):
        self.assertFalse(_gateway_failure_is_definite(ConnectionResetError("Connection reset by peer")))
        self.assertFalse(_gateway_failure_is_definite(http.client.RemoteDisconnected("Remote end closed")))

    def test_http_5xx_are_unknown(self):
        for code in (500, 502, 503, 504):
            exc = urllib.error.HTTPError("http://gw/api", code, "Server Error", {}, None)
            self.assertFalse(_gateway_failure_is_definite(exc), f"HTTP {code} should be unknown")

    def test_json_and_decoding_errors_are_unknown(self):
        self.assertFalse(_gateway_failure_is_definite(json.JSONDecodeError("Expecting value", "", 0)))
        self.assertFalse(_gateway_failure_is_definite(ValueError("Malformed payload")))
        self.assertFalse(_gateway_failure_is_definite(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")))

    def test_generic_and_unlisted_exceptions_are_unknown(self):
        self.assertFalse(_gateway_failure_is_definite(Exception("Something went wrong")))
        self.assertFalse(_gateway_failure_is_definite(IOError("Disk or pipe issue")))


class ParseCreatedAtTests(unittest.TestCase):
    """Unit tests for _parse_created_at_dt helper."""

    def test_iso_utc_parsing(self):
        dt = _parse_created_at_dt("2026-11-03T12:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 12)

    def test_space_separated_datetime_parsing(self):
        dt = _parse_created_at_dt("2026-11-03 12:00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 12)

    def test_invalid_and_empty_returns_none(self):
        self.assertIsNone(_parse_created_at_dt(None))
        self.assertIsNone(_parse_created_at_dt(""))
        self.assertIsNone(_parse_created_at_dt("invalid-date"))


class RecordCloudGenerationTaskIdTests(unittest.TestCase):
    """Unit tests for record_cloud_generation_task_id service function."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "record_user", "password-123")
        self.uid = self.user["id"]

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_records_task_id_on_queued_generation(self):
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (id, user_id, username, task_id, status, created_at)
                VALUES ('gen_rec_1', ?, 'record_user', '', 'queued', '2026-11-03 12:00:00')
                """,
                (self.uid,),
            )
        record_cloud_generation_task_id(self.db, "gen_rec_1", "task_client_999")
        row = self.db.get_conn().execute("SELECT task_id FROM studio_generations WHERE id = 'gen_rec_1'").fetchone()
        self.assertEqual(row["task_id"], "task_client_999")

    def test_does_not_overwrite_refunded_or_success_generation(self):
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (id, user_id, username, task_id, status, created_at)
                VALUES ('gen_rec_ref', ?, 'record_user', 'original_id', 'refunded', '2026-11-03 12:00:00'),
                       ('gen_rec_succ', ?, 'record_user', 'original_id', 'success', '2026-11-03 12:00:00')
                """,
                (self.uid, self.uid),
            )
        record_cloud_generation_task_id(self.db, "gen_rec_ref", "new_id")
        record_cloud_generation_task_id(self.db, "gen_rec_succ", "new_id")

        row_ref = self.db.get_conn().execute("SELECT task_id FROM studio_generations WHERE id = 'gen_rec_ref'").fetchone()
        row_succ = self.db.get_conn().execute("SELECT task_id FROM studio_generations WHERE id = 'gen_rec_succ'").fetchone()
        self.assertEqual(row_ref["task_id"], "original_id")
        self.assertEqual(row_succ["task_id"], "original_id")



class StudioGenerateTimeoutRefundHTTPTests(unittest.TestCase):
    """Integration HTTP tests for POST /api/studio/generate timeout & error behavior."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        cls.db_path = root / "test_timeout_refund.db"
        cls.img_cfg = root / "image-service.json"
        cls.img_cfg.write_text(json.dumps({"key": "mock-test-key", "base_url": "http://127.0.0.1:9999"}))

        cls.env = patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_ALLOWED_ORIGINS": ORIGIN,
                "HANDRAW_IMAGE_CONFIG": str(cls.img_cfg),
            },
        )
        cls.env.start()
        cls.db = open_isolated_postgres(cls, seed=True)
        cls.user, _ = register_user(cls.db, "gen_tester", "Password123!")

        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.cookie = cls._login("gen_tester", "Password123!")

    def setUp(self):
        conn = self.db.get_conn()
        today = local_today_str()
        conn.execute("UPDATE studio_generations SET status = 'success' WHERE user_id = ?", (self.user["id"],))
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20, free_quota_date = ? WHERE user_id = ?", (today, self.user["id"]))
        conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.db.close_thread_conn()
        cls.db.close()
        cls.env.stop()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    @classmethod
    def _login(cls, username: str, password: str) -> str:
        data = json.dumps({"username": username, "password": password}).encode("utf-8")
        req = urllib.request.Request(
            f"{cls.base}/api/auth/login",
            data=data,
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            raw_cookie = resp.headers.get("Set-Cookie", "")
            return raw_cookie.split(";")[0]

    def _post_generate(self, payload: dict) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/api/studio/generate",
            data=data,
            headers={"Content-Type": "application/json", "Origin": ORIGIN, "Cookie": self.cookie},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_timeout_does_not_refund_and_returns_confirming(self):
        """Timeout -> do NOT refund, quota/credits remain spent, status is queued, confirming is True."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        # Ensure fresh quota for this user
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20 WHERE user_id = ?", (uid,))
        conn.commit()

        req_id = f"req_timeout_{int(time.time() * 1000)}"
        with patch("backend.server.gateway_request", side_effect=TimeoutError("gateway timed out")):
            status, res = self._post_generate({
                "prompt": "超时生图测试",
                "style1": "FA-001",
                "requestId": req_id,
            })

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("confirming"))
        self.assertEqual(res.get("status"), "queued")
        self.assertEqual(res.get("taskId"), req_id)

        # Check database: record is queued, NOT refunded, and task_id was saved
        row = conn.execute("SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ?", (uid, req_id)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["task_id"], req_id)

        # Check quota is reserved (not refunded back to 0 used)
        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 1)
        self.assertEqual(wallet["balance"], 20)

    def test_connection_refused_refunds_immediately(self):
        """Connection refused -> refund immediately, 502 with refunded: true."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20 WHERE user_id = ?", (uid,))
        conn.commit()

        req_id = f"req_refused_{int(time.time() * 1000)}"
        refused_exc = urllib.error.URLError(ConnectionRefusedError(10061, "Connect refused"))
        with patch("backend.server.gateway_request", side_effect=refused_exc):
            status, res = self._post_generate({
                "prompt": "连接被拒生图测试",
                "style1": "FA-001",
                "requestId": req_id,
            })

        self.assertEqual(status, 502)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("refunded"))

        row = conn.execute("SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ?", (uid, req_id)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "refunded")
        self.assertIn("生图网关连接失败", row["error_msg"])

        # Check quota was refunded
        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)

    def test_http_400_refunds_immediately(self):
        """HTTP 400 -> gateway explicit rejection, refund immediately, 502 with refunded: true."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20 WHERE user_id = ?", (uid,))
        conn.commit()

        req_id = f"req_400_{int(time.time() * 1000)}"

        class FakeHTTP400(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://gw/api", 400, "Bad Request", {}, None)
            def read(self):
                return b'{"error":"invalid prompt"}'

        with patch("backend.server.gateway_request", side_effect=FakeHTTP400()):
            status, res = self._post_generate({
                "prompt": "HTTP 400 生图测试",
                "style1": "FA-001",
                "requestId": req_id,
            })

        self.assertEqual(status, 502)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("refunded"))
        self.assertIn("HTTP 400", res.get("error", ""))

        row = conn.execute("SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ?", (uid, req_id)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "refunded")

        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)

    def test_http_500_does_not_refund(self):
        """HTTP 500 -> unknown state, do NOT refund, returns 200 with confirming: true."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20 WHERE user_id = ?", (uid,))
        conn.commit()

        req_id = f"req_500_{int(time.time() * 1000)}"

        class FakeHTTP500(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://gw/api", 500, "Internal Server Error", {}, None)
            def read(self):
                return b'{"error":"internal crash"}'

        with patch("backend.server.gateway_request", side_effect=FakeHTTP500()):
            status, res = self._post_generate({
                "prompt": "HTTP 500 生图测试",
                "style1": "FA-001",
                "requestId": req_id,
            })

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("confirming"))
        self.assertEqual(res.get("status"), "queued")

        row = conn.execute("SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ?", (uid, req_id)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "queued")

        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 1)

    def test_unconfigured_gateway_refunds_immediately(self):
        """Unconfigured gateway (GatewayNotConfigured before network) -> refund immediately, 502 with refunded: true."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20 WHERE user_id = ?", (uid,))
        conn.commit()

        req_id = f"req_unconfigured_{int(time.time() * 1000)}"
        cfg_err = GatewayNotConfigured("未检测到本地生图网关配置 image-service.json")
        with patch("backend.server.gateway_request", side_effect=cfg_err):
            status, res = self._post_generate({
                "prompt": "未配置网关测试",
                "style1": "FA-001",
                "requestId": req_id,
            })

        self.assertEqual(status, 502)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("refunded"))

        row = conn.execute("SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ?", (uid, req_id)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "refunded")

        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)

    def test_pre_submission_failure_without_request_id_refunds_immediately_and_unblocks_next_run(self):
        """Failure before gateway submit (e.g. OSError in ref image) refunds immediately and leaves user unblocked."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        today = local_today_str()
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20, free_quota_date = ? WHERE user_id = ?", (today, uid))
        conn.commit()

        with patch("backend.server.resolve_local_ref_image", side_effect=OSError("Disk read failure")):
            status, res = self._post_generate({
                "prompt": "预提交失败测试",
                "customRefImg": "/uploads/nonexistent.png",
            })

        self.assertEqual(status, 502)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("refunded"))

        # Quota should be restored
        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)
        self.assertEqual(wallet["balance"], 20)

        # Subsequent generation must NOT be blocked by 429 generation_in_progress
        with patch("backend.server.gateway_request", return_value={"id": "next_ok", "status": "queued"}):
            next_status, next_res = self._post_generate({
                "prompt": "后续正常生图",
            })
        self.assertEqual(next_status, 200)
        self.assertTrue(next_res.get("ok"))

    def test_pre_submission_record_task_id_failure_refunds_immediately(self):
        """Failure in record_cloud_generation_task_id (SerializationFailure) refunds immediately."""
        from psycopg.errors import SerializationFailure
        conn = self.db.get_conn()
        uid = self.user["id"]
        today = local_today_str()
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20, free_quota_date = ? WHERE user_id = ?", (today, uid))
        conn.commit()

        with patch("backend.server.record_cloud_generation_task_id", side_effect=SerializationFailure("serialization conflict")):
            status, res = self._post_generate({
                "prompt": "记录task_id失败测试",
                "requestId": "req_db_locked_1",
            })

        self.assertEqual(status, 502)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("refunded"))

        wallet = conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)

    def test_gateway_plain_runtime_error_does_not_refund_but_gateway_not_configured_refunds(self):
        """Plain RuntimeError during gateway call -> confirming (no refund). GatewayNotConfigured -> refunds."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        today = local_today_str()
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20, free_quota_date = ? WHERE user_id = ?", (today, uid))
        conn.commit()

        # Plain RuntimeError -> not refunded, confirming: true
        with patch("backend.server.gateway_request", side_effect=RuntimeError("something unexpected on gateway")):
            status1, res1 = self._post_generate({
                "prompt": "普通RuntimeError测试",
                "requestId": "req_plain_runtime_1",
            })
        self.assertEqual(status1, 200)
        self.assertTrue(res1.get("confirming"))
        wallet = conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 1)

        # Clear active generation so we can run next test
        conn.execute("UPDATE studio_generations SET status = 'success' WHERE user_id = ?", (uid,))
        conn.execute("UPDATE wallets SET free_quota_used = 0 WHERE user_id = ?", (uid,))
        conn.commit()

        # GatewayNotConfigured -> refunded: true, 502
        with patch("backend.server.gateway_request", side_effect=GatewayNotConfigured("未配置网关")):
            status2, res2 = self._post_generate({
                "prompt": "未配置网关异常测试",
                "requestId": "req_cfg_err_1",
            })
        self.assertEqual(status2, 502)
        self.assertTrue(res2.get("refunded"))
        wallet2 = conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(wallet2["free_quota_used"], 0)

    def test_tasks_polling_returns_refunded_record_without_calling_gateway(self):
        """When a generation is already refunded by reconciler, /api/studio/tasks returns status: refunded without calling gateway."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        tid = f"task_reconciled_refund_{int(time.time() * 1000)}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (id, user_id, username, task_id, request_id, engine, status, error_msg, created_at)
                VALUES (?, ?, 'gen_tester', ?, 'req_ref_poll', 'live', 'refunded', '网关未收到任务，已退还', '2026-11-03 10:00:00')
                """,
                (f"gen_{tid}", uid, tid),
            )

        poll_req = urllib.request.Request(
            f"{self.base}/api/studio/tasks?id={tid}",
            headers={"Origin": ORIGIN, "Cookie": self.cookie},
        )
        with patch("backend.server.gateway_request") as mock_gw:
            with urllib.request.urlopen(poll_req) as resp:
                data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data.get("status"), "refunded")
        mock_gw.assert_not_called()

    def test_no_request_id_timeout_preserves_queryable_task_id(self):
        """When request has no requestId, client_task_id is saved before call and queryable on timeout."""
        conn = self.db.get_conn()
        uid = self.user["id"]
        conn.execute("UPDATE wallets SET free_quota_used = 0, balance = 20 WHERE user_id = ?", (uid,))
        conn.commit()

        with patch("backend.server.gateway_request", side_effect=TimeoutError("timeout without rid")):
            status, res = self._post_generate({
                "prompt": "无requestId生图测试",
                "style1": "FA-001",
            })

        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("confirming"))
        assigned_task_id = res.get("taskId")
        self.assertTrue(bool(assigned_task_id))

        # Check DB row has this exact task_id
        row = conn.execute(
            "SELECT * FROM studio_generations WHERE user_id = ? AND task_id = ?",
            (uid, assigned_task_id),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["task_id"], assigned_task_id)

        # Check get_user_studio_task directly resolves it by task_id
        db_task = get_user_studio_task(self.db, self.user, task_id=assigned_task_id)
        self.assertIsNotNone(db_task)
        self.assertEqual(db_task.get("taskId"), assigned_task_id)
        self.assertEqual(db_task.get("status"), "queued")

        # Check /api/studio/tasks polling endpoint can query this task by id
        poll_req = urllib.request.Request(
            f"{self.base}/api/studio/tasks?id={assigned_task_id}",
            headers={"Origin": ORIGIN, "Cookie": self.cookie},
        )
        with patch("backend.server.gateway_request", return_value={"items": [{"id": assigned_task_id, "status": "queued"}]}):
            with urllib.request.urlopen(poll_req) as poll_resp:
                poll_data = json.loads(poll_resp.read().decode("utf-8"))
                self.assertEqual(poll_data.get("status"), "queued")


class ReconcilerUnreceivedTaskRefundTests(unittest.TestCase):
    """Tests for GenerationReconciler handling unreceived tasks (> 30 mins, < 30 mins, exceptions)."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "reconcile_user", "password-123")
        self.uid = self.user["id"]

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_reconciler_refunds_unreceived_task_older_than_30_minutes_once(self):
        """Gateway returns empty items & task created > 30 mins ago -> refund once, running twice does not duplicate."""
        conn = self.db.get_conn()
        today = local_today_str()
        # Seed user wallet: 1 free quota used today
        conn.execute("UPDATE wallets SET free_quota_used = 1, balance = 10, free_quota_date = ? WHERE user_id = ?", (today, self.uid))

        created_old = (datetime.now(timezone.utc) - timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, task_id, request_id, engine, status, cost_type, credits_spent, created_at
                ) VALUES (?, ?, ?, ?, ?, 'live', 'queued', 'free_quota', 0, ?)
                """,
                ("gen_old_35m", self.uid, "reconcile_user", "task_old_35m", "req_old_35m", created_old),
            )
            tx.execute(
                """
                INSERT INTO studio_quota_reservations (
                    generation_id, user_id, reservation_date, units, status, created_at
                ) VALUES ('gen_old_35m', ?, ?, 1, 'reserved', ?)
                """,
                (self.uid, today, created_old),
            )

        reconciler = GenerationReconciler(self.db)
        # Pass 1: gateway returns empty items -> should refund
        with patch("backend.server.gateway_request", return_value={"items": []}):
            handled_first = reconciler.reconcile_once()

        self.assertEqual(handled_first, 1)

        row = conn.execute("SELECT status, error_msg FROM studio_generations WHERE id = 'gen_old_35m'").fetchone()
        self.assertEqual(row["status"], "refunded")
        self.assertEqual(row["error_msg"], "网关未收到任务，已退还")

        # Quota should be released back to 0 used
        wallet = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (self.uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)

        # Pass 2: running again must be idempotent and not process or refund again
        with patch("backend.server.gateway_request", return_value={"items": []}):
            handled_second = reconciler.reconcile_once()

        self.assertEqual(handled_second, 0)
        wallet2 = conn.execute("SELECT free_quota_used, balance FROM wallets WHERE user_id = ?", (self.uid,)).fetchone()
        self.assertEqual(wallet2["free_quota_used"], 0)

    def test_reconciler_does_not_refund_task_under_30_minutes(self):
        """Gateway returns empty items & task created < 30 mins ago -> keep queued, do NOT refund."""
        conn = self.db.get_conn()
        conn.execute("UPDATE wallets SET free_quota_used = 1, balance = 10 WHERE user_id = ?", (self.uid,))

        created_recent = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, task_id, request_id, engine, status, cost_type, credits_spent, created_at
                ) VALUES (?, ?, ?, ?, ?, 'live', 'queued', 'free_quota', 0, ?)
                """,
                ("gen_recent_15m", self.uid, "reconcile_user", "task_recent_15m", "req_recent_15m", created_recent),
            )

        reconciler = GenerationReconciler(self.db)
        with patch("backend.server.gateway_request", return_value={"items": []}):
            handled = reconciler.reconcile_once()

        self.assertEqual(handled, 0)
        row = conn.execute("SELECT status FROM studio_generations WHERE id = 'gen_recent_15m'").fetchone()
        self.assertEqual(row["status"], "queued")
        wallet = conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (self.uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 1)

    def test_reconciler_does_not_refund_on_gateway_query_exception(self):
        """Gateway query throws exception (timeout or 5xx) -> keep queued, do NOT refund."""
        conn = self.db.get_conn()
        conn.execute("UPDATE wallets SET free_quota_used = 1, balance = 10 WHERE user_id = ?", (self.uid,))

        created_old = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, task_id, request_id, engine, status, cost_type, credits_spent, created_at
                ) VALUES (?, ?, ?, ?, ?, 'live', 'queued', 'free_quota', 0, ?)
                """,
                ("gen_query_err", self.uid, "reconcile_user", "task_query_err", "req_query_err", created_old),
            )

        reconciler = GenerationReconciler(self.db)
        with patch("backend.server.gateway_request", side_effect=TimeoutError("gateway polling timed out")):
            handled = reconciler.reconcile_once()

        self.assertEqual(handled, 0)
        row = conn.execute("SELECT status FROM studio_generations WHERE id = 'gen_query_err'").fetchone()
        self.assertEqual(row["status"], "queued")
        wallet = conn.execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (self.uid,)).fetchone()
        self.assertEqual(wallet["free_quota_used"], 1)


if __name__ == "__main__":
    unittest.main()
