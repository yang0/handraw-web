"""Regression checks for the local 2.0 request/security boundary."""
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.db import utc_now_iso
from backend.runtime_policy import bind_host, recharge_enabled, sanitize_html
from backend.server import (
    GenerationReconciler,
    HandrawRequestHandler,
    _remote_image_url_allowed,
    build_sitemap_xml,
    render_seo_portal_html,
)


class SecurityHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE": "0",
            },
        )
        self.env.start()
        self.db = open_isolated_postgres(self, seed=True)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, headers: dict[str, str] | None = None):
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if method=="POST" and path=="/api/studio/generate" and isinstance(body,dict):
            from tests.economy_support import http_body
            body=http_body(self.db,req_headers,body)
            data=json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def login(self, username: str) -> str:
        status, headers, _ = self.request(
            "POST",
            "/api/auth/login",
            {"account": username, "password": "handraw123"},
            {"Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)
        return headers.get("Set-Cookie", "").split(";", 1)[0]

    def test_default_bind_and_exact_cors(self) -> None:
        self.assertEqual(bind_host("0.0.0.0"), "127.0.0.1")
        with patch.dict(os.environ, {"HANDRAW_ALLOW_PUBLIC_BIND": "1"}):
            self.assertEqual(bind_host("0.0.0.0"), "0.0.0.0")
        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0", "HANDRAW_ENABLE_RECHARGE": "1"}):
            self.assertFalse(recharge_enabled())

        status, headers, _ = self.request("GET", "/api/health", headers={"Origin": "https://evil.test"})
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        status, _, _ = self.request("OPTIONS", "/api/health", headers={"Origin": "https://evil.test"})
        self.assertEqual(status, 403)

    def test_production_ssr_and_sitemap_hide_seed_records(self) -> None:
        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}):
            sitemap = build_sitemap_xml(self.db, "http://trusted.test")
            page = render_seo_portal_html(
                self.db,
                '<main id="main-app-root"></main>',
                "http://trusted.test",
                {"view": ["works"]},
            )
        self.assertNotIn(b"work_126", sitemap)
        self.assertNotIn(b"work_126", page)

    def test_write_origin_and_recharge_boundary(self) -> None:
        status, _, raw = self.request(
            "POST",
            "/api/auth/login",
            {"account": "yang0", "password": "handraw123"},
            {"Origin": "https://evil.test"},
        )
        self.assertEqual(status, 403)
        self.assertIn(b"csrf_untrusted_origin", raw)

        status, _, raw = self.request(
            "POST",
            "/api/wallet/recharge",
            {},
            {"Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 503)
        self.assertIn(b"payment_disabled", raw)

    def test_demo_reset_requires_explicit_mode(self) -> None:
        old = os.environ.pop("HANDRAW_DEMO_MODE", None)
        try:
            self.httpd.allow_demo_routes = False  # type: ignore[attr-defined]
            status, _, raw = self.request("POST", "/api/dev/reset", {}, {"Origin": "http://trusted.test"})
            self.assertEqual(status, 404)
            self.assertIn(b"demo_disabled", raw)
        finally:
            if old is not None:
                os.environ["HANDRAW_DEMO_MODE"] = old

    def test_rich_html_is_safe(self) -> None:
        cleaned = sanitize_html(
            '<p data-card-id="FA-001" data-media-url="/uploads/ref.png" onclick="evil()">ok<script>alert(1)</script>'
            '<a href="javascript:alert(2)" target="_blank">bad</a>'
            '<img src="/images/poster-demo-autumn-equinox.webp" onerror="evil()"></p>'
        )
        self.assertNotIn("script", cleaned.lower())
        self.assertNotIn("onclick", cleaned.lower())
        self.assertNotIn("javascript:", cleaned.lower())
        self.assertIn("poster-demo-autumn-equinox.webp", cleaned)
        self.assertIn('data-card-id="FA-001"', cleaned)
        self.assertIn('data-media-url="/uploads/ref.png"', cleaned)

    def test_gateway_private_destination_requires_explicit_allow(self) -> None:
        with patch.dict(os.environ, {"HANDRAW_IMAGE_GATEWAY_ALLOW_PRIVATE": "0"}):
            self.assertFalse(_remote_image_url_allowed("http://127.0.0.1:8080/result.png", "http://127.0.0.1:8080"))
        with patch.dict(os.environ, {"HANDRAW_IMAGE_GATEWAY_ALLOW_PRIVATE": "1"}):
            self.assertTrue(_remote_image_url_allowed("http://127.0.0.1:8080/result.png", "http://127.0.0.1:8080"))

    def test_upload_is_owner_only_and_private_cached(self) -> None:
        owner_cookie = self.login("su_editorial")
        png_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        status, _, raw = self.request(
            "POST",
            "/api/uploads",
            {"dataUrl": "data:image/png;base64," + png_1x1, "name": "private"},
            {"Origin": "http://trusted.test", "Cookie": owner_cookie},
        )
        self.assertEqual(status, 200, raw)
        upload_url = json.loads(raw)["url"]

        status, headers, data = self.request("GET", upload_url, headers={"Cookie": owner_cookie})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "private, no-store")
        self.assertTrue(data.startswith(b"\x89PNG"))

        status, _, _ = self.request("GET", upload_url)
        self.assertEqual(status, 404)
        other_cookie = self.login("lin_sketch")
        status, _, _ = self.request("GET", upload_url, headers={"Cookie": other_cookie})
        self.assertEqual(status, 404)

    def test_published_media_requires_and_receives_explicit_grant(self) -> None:
        owner_cookie = self.login("su_editorial")
        png_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        status, _, raw = self.request(
            "POST",
            "/api/uploads",
            {"dataUrl": "data:image/png;base64," + png_1x1},
            {"Origin": "http://trusted.test", "Cookie": owner_cookie},
        )
        self.assertEqual(status, 200)
        upload_url = json.loads(raw)["url"]
        status, _, raw = self.request(
            "POST",
            "/api/works",
            {"title": "明确授权的作品", "notes": "明确授权作品的创作说明心得记录", "prompt": "公开测试", "images": [upload_url]},
            {"Origin": "http://trusted.test", "Cookie": owner_cookie},
        )
        self.assertEqual(status, 200, raw)
        status, headers, _ = self.request("GET", upload_url)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "public, max-age=60, must-revalidate")

    def test_task_poll_requires_login_and_owner(self) -> None:
        uid = self.db.get_conn().execute("SELECT id FROM users WHERE username='su_editorial'").fetchone()["id"]
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO studio_generations (id,user_id,username,task_id,status,created_at) VALUES (?,?,?,?,?,?)",
                ("gen-security", uid, "su_editorial", "owned-task", "running", utc_now_iso()),
            )
        self.assertEqual(self.request("GET", "/api/studio/tasks?id=owned-task")[0], 401)
        other_cookie = self.login("lin_sketch")
        self.assertEqual(self.request("GET", "/api/studio/tasks?id=owned-task", headers={"Cookie": other_cookie})[0], 404)

    def test_generation_request_id_replay_does_not_charge_twice(self) -> None:
        cookie = self.login("su_editorial")
        payload = {"prompt": "稳定请求测试", "requestId": "security-stable-request", "simulateGateway": "ok"}
        first_status, _, first_raw = self.request(
            "POST", "/api/studio/generate", payload, {"Origin": "http://trusted.test", "Cookie": cookie}
        )
        self.assertEqual(first_status, 200, first_raw)
        first = json.loads(first_raw)
        second_status, _, second_raw = self.request(
            "POST", "/api/studio/generate", payload, {"Origin": "http://trusted.test", "Cookie": cookie}
        )
        self.assertEqual(second_status, 200, second_raw)
        second = json.loads(second_raw)
        self.assertEqual(second["genId"], first["genId"])
        self.assertTrue(second.get("idempotent"))
        uid = self.db.get_conn().execute("SELECT id FROM users WHERE username='su_editorial'").fetchone()["id"]
        self.assertEqual(
            self.db.get_conn().execute(
                "SELECT COUNT(*) FROM studio_generations WHERE user_id=? AND request_id=?", (uid, payload["requestId"])
            ).fetchone()[0],
            1,
        )

    def test_reconciler_finishes_known_task_but_preserves_unknown_state(self) -> None:
        uid = self.db.get_conn().execute("SELECT id FROM users WHERE username='su_editorial'").fetchone()["id"]
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO studio_generations (id,user_id,username,task_id,request_id,engine,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("gen-reconcile", uid, "su_editorial", "known-task", "stable-reconcile", "live", "queued", utc_now_iso()),
            )
        png_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        with patch(
            "backend.server.gateway_request",
            return_value={"items": [{"id": "known-task", "status": "success", "data": [{"b64_json": png_1x1, "mime_type": "image/png"}]}]},
        ):
            self.assertEqual(GenerationReconciler(self.db).reconcile_once(), 1)
        row = self.db.get_conn().execute("SELECT status,items_json FROM studio_generations WHERE id='gen-reconcile'").fetchone()
        self.assertEqual(row["status"], "success")
        self.assertRegex(row["items_json"], r"/generated/known-task_0-[0-9a-f]+\.png")

        with self.db.transaction() as tx:
            tx.execute("UPDATE studio_generations SET status='queued' WHERE id='gen-reconcile'")
        with patch("backend.server.gateway_request", side_effect=TimeoutError("unknown")):
            self.assertEqual(GenerationReconciler(self.db).reconcile_once(), 0)
        self.assertEqual(
            self.db.get_conn().execute("SELECT status FROM studio_generations WHERE id='gen-reconcile'").fetchone()[0],
            "queued",
        )


if __name__ == "__main__":
    unittest.main()
