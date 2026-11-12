"""Tests for OpenAI-compatible /v1/images/* gateway protocol and model config (#149)."""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.config import load_image_config, normalize_image_protocol, resolve_gateway_model
from backend.db import local_today_str
from backend.server import (
    GenerationReconciler,
    create_channel_server,
)
from backend.services import prepare_cloud_generation, register_user


ORIGIN = "http://trusted.test"
PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_1X1_BYTES = base64.b64decode(PNG_1X1_B64)
PAID_SECRET = "OPENAI_GATEWAY_BLACKBOX_SECRET_149"


def _parse_multipart(content_type: str, raw_body: bytes) -> tuple[dict[str, str], list[tuple[str, bytes, str]]]:
    """Minimal RFC2046 multipart/form-data parser for verifying test uploads."""
    boundary = ""
    for seg in content_type.split(";"):
        seg = seg.strip()
        if seg.startswith("boundary="):
            boundary = seg.split("=", 1)[1].strip().strip('"')
            break
    sep = f"--{boundary}".encode("utf-8")
    fields: dict[str, str] = {}
    files: list[tuple[str, bytes, str]] = []
    for part in raw_body.split(sep)[1:]:
        if part.startswith(b"--"):
            break
        part = part.lstrip(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue
        hdr_bytes, payload = part.split(b"\r\n\r\n", 1)
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        hdr_text = hdr_bytes.decode("utf-8", errors="replace")
        disp = ""
        ctype = ""
        for line in hdr_text.splitlines():
            low = line.lower()
            if low.startswith("content-disposition:"):
                disp = line
            elif low.startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip()
        name = ""
        filename = ""
        for token in disp.split(";"):
            token = token.strip()
            if token.startswith("name="):
                name = token.split("=", 1)[1].strip('"')
            elif token.startswith("filename="):
                filename = token.split("=", 1)[1].strip('"')
        if filename:
            files.append((name, payload, ctype))
        elif name:
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files


class _MockOpenAIGatewayState:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.mode: str = "ok"
        self.error_status: int = 500
        self.error_body: dict | str = {"error": {"message": f"upstream failure with {PAID_SECRET}"}}
        self.sleep_seconds: float = 0.0
        self.models: list[str] = ["gptfree-pool/gpt-image-2.6", "gpt-image-2"]


def _make_mock_gateway_handler(state: _MockOpenAIGatewayState):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            state.requests.append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization", "")})
            if self.path == "/v1/models":
                body = json.dumps({"object": "list", "data": [{"id": m} for m in state.models]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b""
            ctype = self.headers.get("Content-Type") or ""
            record: dict = {
                "method": "POST",
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
                "content_type": ctype,
            }
            if "multipart/form-data" in ctype:
                fields, files = _parse_multipart(ctype, raw)
                record["fields"] = fields
                record["files"] = files
            else:
                record["json"] = json.loads(raw.decode("utf-8")) if raw else {}
            state.requests.append(record)

            if state.sleep_seconds > 0:
                time.sleep(state.sleep_seconds)

            if state.mode == "http_error":
                payload = (
                    state.error_body.encode("utf-8")
                    if isinstance(state.error_body, str)
                    else json.dumps(state.error_body).encode("utf-8")
                )
                self.send_response(state.error_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if state.mode == "empty":
                out = {"created": 1700000000, "data": []}
            else:
                out = {
                    "created": 1700000000,
                    "data": [{"b64_json": PNG_1X1_B64, "mime_type": "image/png"}],
                }
            body = json.dumps(out).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


class OpenAIImageConfigTests(unittest.TestCase):
    def test_protocol_and_model_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "image-service.json"
            with patch.dict(os.environ, {"HANDRAW_IMAGE_CONFIG": str(cfg_path)}, clear=False):
                # 1. Explicit OpenAI config with model
                cfg_path.write_text(
                    json.dumps(
                        {
                            "url": "http://127.0.0.1:3425/v1",
                            "key": "magpie",
                            "model": "gptfree-pool/gpt-image-2.6",
                            "protocol": "openai",
                        }
                    ),
                    encoding="utf-8",
                )
                loaded = load_image_config()
                self.assertEqual(loaded["protocol"], "openai")
                self.assertEqual(loaded["api_base_url"], "http://127.0.0.1:3425/v1")
                self.assertEqual(loaded["base_url"], "http://127.0.0.1:3425")
                self.assertEqual(loaded["model"], "gptfree-pool/gpt-image-2.6")
                self.assertEqual(
                    resolve_gateway_model({"gateway": {"model": "gpt-image-2"}}, loaded),
                    "gptfree-pool/gpt-image-2.6",
                )

                # 2. Config with 3 fields only (no protocol) auto-detects OpenAI for non-chatgpt2api /v1 + model
                cfg_path.write_text(
                    json.dumps(
                        {
                            "url": "http://127.0.0.1:3425/v1",
                            "key": "magpie",
                            "model": "gptfree-pool/gpt-image-2.6",
                        }
                    ),
                    encoding="utf-8",
                )
                inferred = load_image_config()
                self.assertEqual(inferred["protocol"], "openai")

                # 3. Legacy chatgpt2api URL without model remains image-tasks
                cfg_path.write_text(
                    json.dumps({"url": "https://chatgpt2api.handraw-style.com/v1", "key": "legacy-k"}),
                    encoding="utf-8",
                )
                legacy = load_image_config()
                self.assertEqual(legacy["protocol"], "image-tasks")
                self.assertEqual(resolve_gateway_model({"gateway": {"model": "gpt-image-2"}}, legacy), "gpt-image-2")

                # 4. Explicit protocol overrides URL heuristic
                self.assertEqual(
                    normalize_image_protocol("image-tasks", raw_url="http://127.0.0.1:3425/v1", model="custom/m"),
                    "image-tasks",
                )


class OpenAIImageGatewayHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        cls.img_cfg = root / "image-service.json"

        cls.gw_state = _MockOpenAIGatewayState()
        cls.gw_server = ThreadingHTTPServer(("127.0.0.1", 0), _make_mock_gateway_handler(cls.gw_state))
        cls.gw_thread = threading.Thread(target=cls.gw_server.serve_forever, daemon=True)
        cls.gw_thread.start()
        cls.gw_port = cls.gw_server.server_address[1]

        cls.img_cfg.write_text(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{cls.gw_port}/v1",
                    "key": "magpie",
                    "model": "gptfree-pool/gpt-image-2.6",
                    "protocol": "openai",
                    "timeout": 5,
                }
            ),
            encoding="utf-8",
        )

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

        with cls.db.transaction() as tx:
            tx.execute(
                "INSERT INTO catalog_assets (\n                    code, name, kind, source_type, tier, unlock_cost, image_url,\n                    author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at\n                ) VALUES (\n                    'FX-OAI-PAID', '隐藏画风测试', 'style', 'exclusive', 'S', 0, '/img.webp',\n                    'admin', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z'\n                ) ON CONFLICT DO NOTHING",
                (PAID_SECRET,),
            )

        cls.user, _ = register_user(cls.db, "oai_user", "Password123!")
        cls.admin, _ = register_user(cls.db, "oai_admin", "Password123!")
        with cls.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (cls.admin["id"],))
            tx.execute(
                "INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at) VALUES (?, 'asset', 'FX-OAI-PAID', 0, 'settled', '2026-10-31T00:00:00Z') ON CONFLICT DO NOTHING",
                (cls.user["id"],),
            )

        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.cookie = cls._login("oai_user", "Password123!")
        cls.admin_cookie = cls._login("oai_admin", "Password123!")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.gw_server.shutdown()
        cls.gw_server.server_close()
        cls.gw_thread.join(timeout=5)
        cls.db.close_thread_conn()
        cls.db.close()
        cls.env.stop()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    @classmethod
    def _login(cls, username: str, password: str) -> str:
        req = urllib.request.Request(
            f"{cls.base}/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.headers.get("Set-Cookie", "").split(";")[0]

    def setUp(self) -> None:
        self.gw_state.requests.clear()
        self.gw_state.mode = "ok"
        self.gw_state.sleep_seconds = 0.0
        conn = self.db.get_conn()
        today = local_today_str()
        conn.execute("UPDATE studio_generations SET status = 'success' WHERE user_id = ?", (self.user["id"],))
        conn.execute(
            "UPDATE wallets SET free_quota_used = 0, balance = 20, free_quota_date = ? WHERE user_id = ?",
            (today, self.user["id"]),
        )
        conn.commit()

    def _req(self, method: str, path: str, body: dict | None = None, cookie: str = "") -> tuple[int, dict]:
        headers = {"Origin": ORIGIN}
        if cookie:
            headers["Cookie"] = cookie
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_studio_config_and_admin_overview_surface_configured_model(self) -> None:
        st_cfg, cfg_body = self._req("GET", "/api/studio/config")
        self.assertEqual(st_cfg, 200)
        self.assertTrue(cfg_body["liveImageEnabled"])
        self.assertEqual(cfg_body["model"], "gptfree-pool/gpt-image-2.6")

        st_adm, adm_body = self._req("GET", "/api/admin/gateway?probe=1", cookie=self.admin_cookie)
        self.assertEqual(st_adm, 200)
        self.assertEqual(adm_body["gateway"]["model"], "gptfree-pool/gpt-image-2.6")
        self.assertEqual(adm_body["gateway"]["protocol"], "openai")
        self.assertEqual(adm_body["gateway"]["baseUrl"], f"http://127.0.0.1:{self.gw_port}/v1")
        self.assertTrue(adm_body["probe"]["reachable"])
        self.assertTrue(
            any(r["path"] == "/v1/models" and r["auth"] == "Bearer magpie" for r in self.gw_state.requests),
            f"Expected GET /v1/models probe, got {self.gw_state.requests}",
        )

    def test_text_to_image_calls_v1_images_generations_and_masks_secret(self) -> None:
        st, res = self._req(
            "POST",
            "/api/studio/generate",
            {
                "prompt": "画一只戴围巾的柴犬",
                "style1": "FX-OAI-PAID",
                "ratio": "3:4",
                "requestId": "req-oai-t2i-1",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["images"] and res["images"][0].startswith("/generated/"))
        self.assertTrue(res.get("promptMasked"))
        self.assertEqual(res.get("finalPrompt"), "")
        self.assertNotIn(PAID_SECRET, json.dumps(res, ensure_ascii=False))

        post_reqs = [r for r in self.gw_state.requests if r["method"] == "POST"]
        self.assertEqual(len(post_reqs), 1)
        up = post_reqs[0]
        self.assertEqual(up["path"], "/v1/images/generations")
        self.assertEqual(up["auth"], "Bearer magpie")
        self.assertEqual(up["json"]["model"], "gptfree-pool/gpt-image-2.6")
        self.assertEqual(up["json"]["size"], "1152x1536")
        self.assertEqual(up["json"]["quality"], "auto")
        self.assertIn(PAID_SECRET, up["json"]["prompt"])

        # Cached private image is retrievable by owner
        img_req = urllib.request.Request(f"{self.base}{res['images'][0]}", headers={"Cookie": self.cookie})
        with urllib.request.urlopen(img_req, timeout=5) as img_resp:
            self.assertEqual(img_resp.status, 200)
            self.assertEqual(img_resp.read(), PNG_1X1_BYTES)

        # Polling /api/studio/tasks returns DB-cached success without hitting upstream
        before_poll_count = len(self.gw_state.requests)
        st_poll, poll_res = self._req("GET", "/api/studio/tasks?requestId=req-oai-t2i-1", cookie=self.cookie)
        self.assertEqual(st_poll, 200)
        self.assertEqual(poll_res["status"], "success")
        self.assertEqual(poll_res["images"], res["images"])
        self.assertEqual(len(self.gw_state.requests), before_poll_count)

    def test_ref_image_calls_v1_images_edits_multipart(self) -> None:
        st_up, up_res = self._req(
            "POST",
            "/api/uploads",
            {"dataUrl": f"data:image/png;base64,{PNG_1X1_B64}", "nameZh": "参考草图"},
            cookie=self.cookie,
        )
        self.assertEqual(st_up, 200)
        ref_url = up_res["url"]

        st, res = self._req(
            "POST",
            "/api/studio/generate",
            {
                "prompt": "按草图改成水彩插画",
                "customRefImg": ref_url,
                "ratio": "1:1",
                "requestId": "req-oai-edit-1",
            },
            cookie=self.cookie,
        )
        self.assertEqual(st, 200)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["images"][0].startswith("/generated/"))

        post_reqs = [r for r in self.gw_state.requests if r["method"] == "POST"]
        self.assertEqual(len(post_reqs), 1)
        up = post_reqs[0]
        self.assertEqual(up["path"], "/v1/images/edits")
        self.assertEqual(up["auth"], "Bearer magpie")
        self.assertEqual(up["fields"]["model"], "gptfree-pool/gpt-image-2.6")
        self.assertEqual(up["fields"]["size"], "1024x1024")
        self.assertEqual(len(up["files"]), 1)
        self.assertEqual(up["files"][0][0], "image")
        self.assertEqual(up["files"][0][1], PNG_1X1_BYTES)

    def test_upstream_error_and_empty_data_refund_immediately_and_hide_secret(self) -> None:
        # 1. HTTP 500 with sensitive body -> 502 + refund + sanitized error
        self.gw_state.mode = "http_error"
        self.gw_state.error_status = 500
        with self.assertLogs("backend.server", level="WARNING") as cm:
            st, res = self._req(
                "POST",
                "/api/studio/generate",
                {"prompt": "错误测试", "style1": "FX-OAI-PAID", "requestId": "req-oai-err-500"},
                cookie=self.cookie,
            )
        self.assertEqual(st, 502)
        self.assertTrue(res.get("refunded"))
        self.assertIn("HTTP 500", res["error"])
        self.assertNotIn(PAID_SECRET, json.dumps(res, ensure_ascii=False))
        self.assertNotIn(PAID_SECRET, "\n".join(cm.output))

        wallet = self.db.get_conn().execute(
            "SELECT free_quota_used FROM wallets WHERE user_id = ?", (self.user["id"],)
        ).fetchone()
        self.assertEqual(wallet["free_quota_used"], 0)

        # 2. Subsequent empty data response -> also refunds immediately and leaves user unblocked
        self.gw_state.mode = "empty"
        st_empty, res_empty = self._req(
            "POST",
            "/api/studio/generate",
            {"prompt": "空响应测试", "requestId": "req-oai-empty"},
            cookie=self.cookie,
        )
        self.assertEqual(st_empty, 502)
        self.assertTrue(res_empty.get("refunded"))

        # 3. Recovery succeeds immediately after failure refunds (not blocked by 429)
        self.gw_state.mode = "ok"
        st_ok, res_ok = self._req(
            "POST",
            "/api/studio/generate",
            {"prompt": "恢复正常生图", "requestId": "req-oai-recover"},
            cookie=self.cookie,
        )
        self.assertEqual(st_ok, 200)
        self.assertEqual(res_ok["status"], "success")

    def test_reconciler_handles_orphan_openai_rows_without_polling_image_tasks(self) -> None:
        stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json,
                    engine, cost_type, credits_spent, task_id, status, error_msg, request_id,
                    reservation_date, created_at, fork_work_id, prompt_ready, recipe_id
                ) VALUES (
                    'gen_oai_orphan_1', ?, 'oai_user', '云端生图', '3:4', '云端直出', 'single', '',
                    'orphan prompt', 'orphan prompt', 0, ?, '', '[]',
                    'live', 'free_quota', 0, 'req_oai_orphan_1', 'queued', '', 'req_oai_orphan_1',
                    '2026-10-31', ?, '', 1, ''
                )
                """,
                (self.user["id"], json.dumps({"gatewayProtocol": "openai"}), stale_ts),
            )
            tx.execute(
                """
                INSERT INTO studio_quota_reservations (generation_id, user_id, reservation_date, units, status, created_at)
                VALUES ('gen_oai_orphan_1', ?, '2026-10-31', 1, 'reserved', ?)
                """,
                (self.user["id"], stale_ts),
            )

        reconciler = GenerationReconciler(self.db)
        handled = reconciler.reconcile_once()
        self.assertEqual(handled, 1)
        self.assertEqual(len(self.gw_state.requests), 0, "OpenAI orphan reconciler must not hit /api/image-tasks")
        row = self.db.get_conn().execute(
            "SELECT status, error_msg FROM studio_generations WHERE id = 'gen_oai_orphan_1'"
        ).fetchone()
        self.assertEqual(row["status"], "refunded")

    def test_http_400_logs_traceback_and_surfaces_sanitized_upstream_detail(self) -> None:
        self.gw_state.mode = "http_error"
        self.gw_state.error_status = 400
        self.gw_state.error_body = {
            "error": {
                "message": "unsupported size parameter via https://gw.test/v1?token=qsec99 Bearer up-tok-999 api_key=mysec888",
                "code": "invalid_request",
            }
        }
        with self.assertLogs("backend.server", level="ERROR") as cm:
            st, res = self._req(
                "POST",
                "/api/studio/generate",
                {"prompt": "错误诊断测试", "requestId": "req-oai-err-400"},
                cookie=self.cookie,
            )
        self.assertEqual(st, 502)
        self.assertTrue(res.get("refunded"))
        self.assertIn("HTTP 400", res["error"])
        self.assertIn("unsupported size parameter", res["error"])
        self.assertIn("[redacted]", res["error"])
        for secret in ("qsec99", "up-tok-999", "mysec888"):
            self.assertNotIn(secret, res["error"])
            self.assertNotIn(secret, "\n".join(cm.output))
        log_text = "\n".join(cm.output)
        self.assertIn("endpoint=/v1/images/generations", log_text)
        self.assertIn("model=gptfree-pool/gpt-image-2.6", log_text)
        self.assertIn("size=1152x1536", log_text)
        self.assertIn("refs=0", log_text)
        self.assertIn("duration_ms=", log_text)
        self.assertIn("Traceback", log_text)

        row = self.db.get_conn().execute(
            "SELECT status, error_msg FROM studio_generations WHERE request_id = 'req-oai-err-400'"
        ).fetchone()
        self.assertEqual(row["status"], "refunded")
        self.assertIn("unsupported size parameter", row["error_msg"])

    def test_prepare_cloud_generation_marks_openai_protocol_before_compose(self) -> None:
        reconciler = GenerationReconciler(self.db)
        mid_compose_protocols: list[str] = []

        def fake_compose(*args, **kwargs):
            row = self.db.get_conn().execute(
                "SELECT system_append_json FROM studio_generations WHERE request_id = 'req-oai-early-mark'"
            ).fetchone()
            mid_compose_protocols.append(json.loads(row["system_append_json"]).get("gatewayProtocol", ""))
            reconciler.reconcile_once()
            return "composed clean prompt"

        before_reqs = len(self.gw_state.requests)
        with patch("backend.services._compose_skill_prompt", side_effect=fake_compose):
            prep = prepare_cloud_generation(
                self.db,
                self.user,
                {
                    "prompt": "早期协议标记测试",
                    "style1": "FX-OAI-PAID",
                    "requestId": "req-oai-early-mark",
                    "confirmCost": True,
                },
                gateway_protocol="openai",
            )
        self.assertEqual(mid_compose_protocols, ["openai"])
        self.assertEqual(len(self.gw_state.requests), before_reqs, "Reconciler must skip OpenAI task during prompt compose")
        after_row = self.db.get_conn().execute(
            "SELECT system_append_json FROM studio_generations WHERE id = ?",
            (prep["genId"],),
        ).fetchone()
        self.assertEqual(json.loads(after_row["system_append_json"]).get("gatewayProtocol"), "openai")
        # Clean up inflight row so subsequent tests aren't counted against max_inflight
        from backend.services import refund_failed_cloud_generation
        refund_failed_cloud_generation(self.db, prep["genId"], "cleanup")


if __name__ == "__main__":
    unittest.main()
