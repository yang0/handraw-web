"""Unit and HTTP integration tests for Admin Message Broadcasts (Phase B).

Verifies:
1. Strict row growth: 1 broadcast adds exactly 1 row to message_broadcasts,
   0 rows to dm_messages, 0 rows to notifications, and 0 rows to message_broadcast_reads
   until a user actually reads it.
2. Only admin can send broadcasts; operator and normal users get 403.
3. Idempotent request_id prevents duplicate submissions.
4. Title (4–80) and body (1–5000) boundaries, HTML tags rejected.
5. Rate limits: 1 per minute, 5 per day.
6. Audience cutoff: accounts registered after broadcast cannot see it; unread is 0.
7. Withdrawal: body is hidden, unread count resets to 0, audit log recorded.
8. Broadcasts are unaffected by blocks.
9. Full HTTP server lifecycle.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tests.legacy_database import Database
from backend.messaging import (
    send_message_broadcast,
    withdraw_message_broadcast,
    list_message_broadcasts,
    mark_message_broadcast_read,
    get_messages_unread_summary,
)
from tests.legacy_database import init_legacy_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user, ServiceError


class MessageBroadcastTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_broadcasts.db"
        self.db = init_legacy_database(self.db_path)

        # Create admin, operator, and standard users
        self.admin, _ = register_user(self.db, "admin_user", "AdminPass123!", display_name="超级管理员")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))
        self.admin["role"] = "admin"

        self.operator, _ = register_user(self.db, "operator_user", "OpPass123!", display_name="运营专员")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'operator' WHERE id = ?", (self.operator["id"],))
        self.operator["role"] = "operator"

        self.u1, _ = register_user(self.db, "user_one", "Pass123!", display_name="用户一")
        self.u2, _ = register_user(self.db, "user_two", "Pass123!", display_name="用户二")
        self.u3, _ = register_user(self.db, "user_three", "Pass123!", display_name="用户三")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_broadcast_row_growth_strictly_one_no_fanout(self):
        """CRITICAL: Assert sending a broadcast inserts exactly 1 row into message_broadcasts,
        0 rows into dm_messages, 0 rows into notifications, and 0 rows into message_broadcast_reads
        until a user reads it."""
        conn = self.db.get_conn()

        bc_before = conn.execute("SELECT COUNT(*) FROM message_broadcasts").fetchone()[0]
        dm_before = conn.execute("SELECT COUNT(*) FROM dm_messages").fetchone()[0]
        notif_before = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        reads_before = conn.execute("SELECT COUNT(*) FROM message_broadcast_reads").fetchone()[0]

        res = send_message_broadcast(
            self.db,
            self.admin,
            {
                "title": "重要全员通知：系统架构全面升级",
                "body": "各位社区创作者大家好，今晚系统将进行无缝架构升级，届时请留意。",
                "requestId": "req_strict_no_fanout_001",
            },
        )
        self.assertTrue(res.get("ok"))
        bc_id = res["broadcast"]["id"]

        bc_after = conn.execute("SELECT COUNT(*) FROM message_broadcasts").fetchone()[0]
        dm_after = conn.execute("SELECT COUNT(*) FROM dm_messages").fetchone()[0]
        notif_after = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        reads_after = conn.execute("SELECT COUNT(*) FROM message_broadcast_reads").fetchone()[0]

        # 1. Exactly 1 row added to message_broadcasts
        self.assertEqual(bc_after, bc_before + 1, "message_broadcasts must increase by exactly 1 row")

        # 2. ZERO rows added to dm_messages (no fan-out!)
        self.assertEqual(dm_after, dm_before, "dm_messages must NOT receive any rows on broadcast")

        # 3. ZERO rows added to notifications (no duplication!)
        self.assertEqual(notif_after, notif_before, "notifications must NOT receive any rows on broadcast")

        # 4. ZERO rows in reads before anyone opens it
        self.assertEqual(reads_after, reads_before, "message_broadcast_reads must NOT have rows before reading")

        # Check unread count for user 1: should be 1
        unread_u1 = get_messages_unread_summary(self.db, self.u1)
        self.assertEqual(unread_u1["broadcasts"], 1)
        self.assertEqual(unread_u1["total"], unread_u1["notifications"] + unread_u1["direct"] + 1)

        # User 1 reads the broadcast
        read_res = mark_message_broadcast_read(self.db, self.u1, bc_id)
        self.assertTrue(read_res.get("ok"))

        reads_after_read = conn.execute("SELECT COUNT(*) FROM message_broadcast_reads").fetchone()[0]
        self.assertEqual(reads_after_read, reads_before + 1, "Only 1 row inserted into message_broadcast_reads on user read")

        # User 1 unread is now 0; User 2 unread is still 1
        unread_u1_after = get_messages_unread_summary(self.db, self.u1)
        self.assertEqual(unread_u1_after["broadcasts"], 0)

        unread_u2 = get_messages_unread_summary(self.db, self.u2)
        self.assertEqual(unread_u2["broadcasts"], 1)

    def test_operator_and_user_cannot_send_broadcast_403(self):
        """Only admin can send; operator and normal user get 403."""
        with self.assertRaises(ServiceError) as ctx_op:
            send_message_broadcast(
                self.db,
                self.operator,
                {"title": "运营尝试发送公告", "body": "正文内容", "requestId": "req_op_test"},
            )
        self.assertEqual(ctx_op.exception.status, 403)
        self.assertEqual(ctx_op.exception.code, "admin_required")

        with self.assertRaises(ServiceError) as ctx_u:
            send_message_broadcast(
                self.db,
                self.u1,
                {"title": "普通用户尝试发送公告", "body": "正文内容", "requestId": "req_u_test"},
            )
        self.assertEqual(ctx_u.exception.status, 403)
        self.assertEqual(ctx_u.exception.code, "admin_required")

    def test_idempotent_request_id(self):
        """Duplicate requestId returns existing broadcast without inserting new rows."""
        conn = self.db.get_conn()
        req_id = "req_idempotent_test_01"

        res1 = send_message_broadcast(
            self.db,
            self.admin,
            {"title": "初次发送的标题", "body": "初次发送的正文", "requestId": req_id},
        )
        self.assertFalse(res1.get("replayed"))
        id1 = res1["broadcast"]["id"]

        count_after1 = conn.execute("SELECT COUNT(*) FROM message_broadcasts").fetchone()[0]

        res2 = send_message_broadcast(
            self.db,
            self.admin,
            {"title": "重发发送的标题（应被忽略）", "body": "重发发送的正文", "requestId": req_id},
        )
        self.assertTrue(res2.get("replayed"))
        self.assertEqual(res2["broadcast"]["id"], id1)
        self.assertEqual(res2["broadcast"]["title"], "初次发送的标题")

        count_after2 = conn.execute("SELECT COUNT(*) FROM message_broadcasts").fetchone()[0]
        self.assertEqual(count_after1, count_after2, "No duplicate row created on replay")

    def test_title_and_body_boundaries(self):
        """Verifies title 4–80, body 1–5000, rejects HTML."""
        # Title < 4
        with self.assertRaises(ServiceError) as ctx:
            send_message_broadcast(self.db, self.admin, {"title": "短", "body": "正文", "requestId": "req_t_short"})
        self.assertEqual(ctx.exception.status, 400)

        # Title > 80
        with self.assertRaises(ServiceError) as ctx:
            send_message_broadcast(self.db, self.admin, {"title": "长" * 81, "body": "正文", "requestId": "req_t_long"})
        self.assertEqual(ctx.exception.status, 400)

        # Body < 1
        with self.assertRaises(ServiceError) as ctx:
            send_message_broadcast(self.db, self.admin, {"title": "合规标题", "body": "   ", "requestId": "req_b_empty"})
        self.assertEqual(ctx.exception.status, 400)

        # Body > 5000
        with self.assertRaises(ServiceError) as ctx:
            send_message_broadcast(self.db, self.admin, {"title": "合规标题", "body": "字" * 5001, "requestId": "req_b_long"})
        self.assertEqual(ctx.exception.status, 400)

        # HTML tags in body
        with self.assertRaises(ServiceError) as ctx:
            send_message_broadcast(self.db, self.admin, {"title": "合规标题", "body": "<script>alert(1)</script>", "requestId": "req_html"})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "html_not_allowed")

    def test_rate_limits_minute_and_day(self):
        """Verifies 1/min, 5/day."""
        # 1st broadcast succeeds
        res1 = send_message_broadcast(
            self.db, self.admin, {"title": "公告第1条", "body": "正文", "requestId": "req_rate_1"}
        )
        self.assertTrue(res1.get("ok"))

        # Immediate 2nd broadcast fails with 429 (1/min limit)
        with self.assertRaises(ServiceError) as ctx_min:
            send_message_broadcast(
                self.db, self.admin, {"title": "公告第2条", "body": "正文", "requestId": "req_rate_2"}
            )
        self.assertEqual(ctx_min.exception.status, 429)
        self.assertEqual(ctx_min.exception.code, "rate_limited_minute")

        # Age the 1st broadcast by 2 minutes in DB to bypass minute limit
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE message_broadcasts SET published_at = datetime('now', '-2 minutes') WHERE id = ?",
                (res1["broadcast"]["id"],),
            )

        # 2nd broadcast now succeeds
        res2 = send_message_broadcast(
            self.db, self.admin, {"title": "公告第2条", "body": "正文", "requestId": "req_rate_2"}
        )
        self.assertTrue(res2.get("ok"))

        # Add 3 more broadcasts (aging each) to reach 5/day
        for i in range(3, 6):
            with self.db.transaction() as tx:
                tx.execute("UPDATE message_broadcasts SET published_at = datetime('now', '-2 minutes')")
            res_i = send_message_broadcast(
                self.db, self.admin, {"title": f"公告第{i}条", "body": "正文", "requestId": f"req_rate_{i}"}
            )
            self.assertTrue(res_i.get("ok"))

        # 6th broadcast fails with 429 (5/day limit)
        with self.db.transaction() as tx:
            tx.execute("UPDATE message_broadcasts SET published_at = datetime('now', '-2 minutes')")
        with self.assertRaises(ServiceError) as ctx_day:
            send_message_broadcast(
                self.db, self.admin, {"title": "公告第6条", "body": "正文", "requestId": "req_rate_6"}
            )
        self.assertEqual(ctx_day.exception.status, 429)
        self.assertEqual(ctx_day.exception.code, "rate_limited_day")

    def test_audience_cutoff_new_users_cannot_see_old_broadcasts(self):
        """Users registered AFTER audience_cutoff do not receive the broadcast."""
        # 1. Admin sends broadcast at T1
        res = send_message_broadcast(
            self.db, self.admin, {"title": "早期社区建设公告", "body": "欢迎第一批种子创作者！", "requestId": "req_early_cohort"}
        )
        bc_id = res["broadcast"]["id"]

        # User 1 (already registered before T1) can see the broadcast
        u1_bcs = list_message_broadcasts(self.db, self.u1, {})["broadcasts"]
        self.assertTrue(any(b["id"] == bc_id for b in u1_bcs))
        self.assertEqual(get_messages_unread_summary(self.db, self.u1)["broadcasts"], 1)

        # 2. New user registers AFTER T1
        late_user, _ = register_user(self.db, "late_comer", "Pass123!", display_name="晚加入者")
        with self.db.transaction() as tx:
            # Explicitly set created_at to 1 hour in the future relative to audience_cutoff
            tx.execute("UPDATE users SET created_at = datetime('now', '+1 hour') WHERE id = ?", (late_user["id"],))

        conn = self.db.get_conn()
        late_row = conn.execute("SELECT * FROM users WHERE id = ?", (late_user["id"],)).fetchone()
        late_user_dict = dict(late_row)

        # Late user does NOT see the broadcast
        late_bcs = list_message_broadcasts(self.db, late_user_dict, {})["broadcasts"]
        self.assertFalse(any(b["id"] == bc_id for b in late_bcs))

        # Late user unread count for broadcasts is 0
        unread_late = get_messages_unread_summary(self.db, late_user_dict)
        self.assertEqual(unread_late["broadcasts"], 0)

    def test_withdraw_broadcast_hides_body_and_zeros_unread(self):
        """Withdrawing a broadcast hides body, zeros unread count, and logs audit."""
        res = send_message_broadcast(
            self.db, self.admin, {"title": "包含笔误的测试公告", "body": "请忽略本条测试内容", "requestId": "req_withdraw_test"}
        )
        bc_id = res["broadcast"]["id"]

        # Before withdraw: user sees body and has 1 unread
        u1_before = list_message_broadcasts(self.db, self.u1, {})["broadcasts"][0]
        self.assertFalse(u1_before["isWithdrawn"])
        self.assertEqual(u1_before["body"], "请忽略本条测试内容")
        self.assertEqual(get_messages_unread_summary(self.db, self.u1)["broadcasts"], 1)

        # Admin withdraws broadcast
        withdraw_res = withdraw_message_broadcast(self.db, self.admin, bc_id)
        self.assertTrue(withdraw_res.get("ok"))

        # After withdraw: user sees isWithdrawn=True, body='', unread count drops to 0
        u1_after = list_message_broadcasts(self.db, self.u1, {})["broadcasts"][0]
        self.assertTrue(u1_after["isWithdrawn"])
        self.assertEqual(u1_after["body"], "")
        self.assertEqual(get_messages_unread_summary(self.db, self.u1)["broadcasts"], 0)

        # Admin still has access to body for audit purposes
        admin_view = list_message_broadcasts(self.db, self.admin, {})["broadcasts"][0]
        self.assertTrue(admin_view["isWithdrawn"])
        self.assertEqual(admin_view["body"], "请忽略本条测试内容")

        # Audit log exists
        conn = self.db.get_conn()
        audit = conn.execute("SELECT * FROM audit_logs WHERE action = 'withdraw_broadcast' AND target_id = ?", (str(bc_id),)).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(audit["actor_username"], "admin_user")

    def test_broadcast_unaffected_by_blocks(self):
        """User blocks admin, but still receives and reads admin broadcasts."""
        from backend.messaging import block_user
        block_user(self.db, self.u1, {"userId": self.admin["id"]})

        res = send_message_broadcast(
            self.db, self.admin, {"title": "全站紧急安全通知", "body": "重要系统安全提醒，请查阅。", "requestId": "req_block_unaffected"}
        )
        bc_id = res["broadcast"]["id"]

        # u1 still receives the broadcast and sees it
        u1_bcs = list_message_broadcasts(self.db, self.u1, {})["broadcasts"]
        self.assertTrue(any(b["id"] == bc_id for b in u1_bcs))
        self.assertEqual(get_messages_unread_summary(self.db, self.u1)["broadcasts"], 1)


class MessageBroadcastHTTPTests(unittest.TestCase):
    """Full HTTP API lifecycle test over ThreadingHTTPServer."""

    @classmethod
    def setUpClass(cls):
        cls.port = 3105
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "http_broadcasts.db"

        cls.env_patch = {
            "HANDRAW_DB_PATH": str(cls.db_path),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{cls.port}",
        }
        cls.old_env = {}
        for k, v in cls.env_patch.items():
            cls.old_env[k] = os.environ.get(k)
            os.environ[k] = v

        cls.db = init_legacy_database(cls.db_path)
        cls.admin, cls.token_admin = register_user(cls.db, "http_admin", "Password123!", display_name="超级管理员")
        with cls.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (cls.admin["id"],))

        cls.user, cls.token_user = register_user(cls.db, "http_user", "Password123!", display_name="普通用户")

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), HandrawRequestHandler)
        cls.httpd.channel_role = "main"  # type: ignore[attr-defined]
        cls.httpd.db = cls.db  # type: ignore[attr-defined]
        cls.httpd.allow_demo_routes = True  # type: ignore[attr-defined]

        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.db.close()
        cls.temp_dir.cleanup()
        for k in cls.env_patch:
            if cls.old_env.get(k) is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = cls.old_env[k]

    def _req(self, method: str, path: str, token: str | None = None, body: dict[str, Any] | None = None):
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Cookie", f"{SESSION_COOKIE_NAME}={token}")

        try:
            with urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_http_broadcast_full_lifecycle(self):
        # 1. Admin sends broadcast via HTTP
        status, data = self._req(
            "POST",
            "/api/admin/message-broadcasts",
            token=self.token_admin,
            body={
                "title": "HTTP 接口群发测试公告",
                "body": "本条公告用于端到端 HTTP 接口全链路测试。",
                "requestId": "http_bc_req_001",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        bc_id = data["broadcast"]["id"]

        # 2. User checks unread counts
        status, unread = self._req("GET", "/api/messages/unread", token=self.token_user)
        self.assertEqual(status, 200)
        self.assertEqual(unread["broadcasts"], 1)

        # 3. User lists broadcasts
        status, bc_list = self._req("GET", "/api/message-broadcasts", token=self.token_user)
        self.assertEqual(status, 200)
        self.assertEqual(len(bc_list["broadcasts"]), 1)
        self.assertEqual(bc_list["broadcasts"][0]["id"], bc_id)
        self.assertFalse(bc_list["broadcasts"][0]["isRead"])

        # 4. User marks broadcast read
        status, read_res = self._req("POST", f"/api/message-broadcasts/{bc_id}/read", token=self.token_user)
        self.assertEqual(status, 200)
        self.assertTrue(read_res.get("ok"))

        # 5. User unread counts now 0
        status, unread_after = self._req("GET", "/api/messages/unread", token=self.token_user)
        self.assertEqual(status, 200)
        self.assertEqual(unread_after["broadcasts"], 0)

        # 6. Admin withdraws broadcast
        status, withdraw_res = self._req("POST", f"/api/admin/message-broadcasts/{bc_id}/withdraw", token=self.token_admin)
        self.assertEqual(status, 200)
        self.assertTrue(withdraw_res.get("ok"))

        # 7. User refreshes broadcast list -> sees isWithdrawn=True, body=""
        status, bc_list_withdrawn = self._req("GET", "/api/message-broadcasts", token=self.token_user)
        self.assertEqual(status, 200)
        self.assertTrue(bc_list_withdrawn["broadcasts"][0]["isWithdrawn"])
        self.assertEqual(bc_list_withdrawn["broadcasts"][0]["body"], "")


if __name__ == "__main__":
    unittest.main()
