"""Tests for batch size mismatch handling during series single-image generation (#150)."""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import isolated_pg_dsn
from backend.server import create_channel_server, init_database
from backend.services import register_user

ORIGIN = "http://trusted.test"
PNG_1X1_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _GatewayState:
    def __init__(self) -> None:
        self.calls: list[dict] = []


def _make_gateway_handler(state: _GatewayState):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            state.calls.append({"path": self.path, "payload": payload})
            body = json.dumps({
                "created": 1731312000,
                "data": [{"b64_json": base64.b64encode(PNG_1X1_BYTES).decode("ascii")}],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


class BatchSizeMismatchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("HANDRAW_PG_STAGING_URL"):
            raise unittest.SkipTest("Isolated PostgreSQL staging URL not provided")
        root = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.img_cfg = root / "image-service.json"

        cls.gw_state = _GatewayState()
        cls.gw_server = ThreadingHTTPServer(("127.0.0.1", 0), _make_gateway_handler(cls.gw_state))
        cls.gw_thread = threading.Thread(target=cls.gw_server.serve_forever, daemon=True)
        cls.gw_thread.start()

        cls.img_cfg.write_text(
            json.dumps({
                "url": f"http://127.0.0.1:{cls.gw_server.server_port}/v1",
                "key": "test-key",
                "model": "gptfree-pool/gpt-image-2.6",
                "protocol": "openai",
                "timeout": 5,
            }),
            encoding="utf-8",
        )
        cls.enterClassContext(patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_ALLOWED_ORIGINS": ORIGIN,
                "HANDRAW_IMAGE_CONFIG": str(cls.img_cfg),
            },
        ))
        cls.db = init_database(cls.enterClassContext(isolated_pg_dsn()))
        cls.addClassCleanup(cls.db.close)
        cls.user, _ = register_user(cls.db, "series_user", "Password123!")

        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.cookie = cls._login("series_user", "Password123!")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.import_manager.stop()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.gw_server.shutdown()
        cls.gw_server.server_close()
        cls.gw_thread.join(timeout=5)

    @classmethod
    def _login(cls, username: str, password: str) -> str:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{cls.base}/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
            method="POST",
        )
        with opener.open(req, timeout=5) as resp:
            return resp.headers.get("Set-Cookie", "").split(";", 1)[0]

    def _post_generate(self, payload: dict) -> tuple[int, dict]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{self.base}/api/studio/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": ORIGIN, "Cookie": self.cookie},
            method="POST",
        )
        try:
            with opener.open(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_mismatched_batch_total_returns_409_without_charging_and_new_batch_succeeds(self) -> None:
        batch_id = "batch_series_resize_3"
        st1, body1 = self._post_generate({
            "prompt": "frame 0 in 3-card series",
            "ratio": "3:4",
            "batchId": batch_id,
            "batchIndex": 0,
            "batchTotal": 3,
            "requestId": f"req_{batch_id}_0",
            "confirmCost": True,
        })
        self.assertEqual(st1, 200)
        self.assertTrue(body1.get("ok"))
        calls_before = len(self.gw_state.calls)

        wallet_before = self.db.get_conn().execute(
            "SELECT balance, free_quota_used FROM wallets WHERE user_id = ?",
            (self.user["id"],),
        ).fetchone()

        # Reusing old batch_id after series count changed to 2 must return 409, not 500, and must not charge.
        st_mismatch, body_mismatch = self._post_generate({
            "prompt": "frame 0 in resized 2-card series",
            "ratio": "3:4",
            "batchId": batch_id,
            "batchIndex": 0,
            "batchTotal": 2,
            "requestId": f"req_{batch_id}_resized_0",
            "confirmCost": True,
        })
        self.assertEqual(st_mismatch, 409)
        self.assertFalse(body_mismatch.get("ok"))
        self.assertEqual(body_mismatch.get("code"), "batch_size_mismatch")
        self.assertEqual(len(self.gw_state.calls), calls_before, "Rejected batch mismatch must not call gateway")

        wallet_after = self.db.get_conn().execute(
            "SELECT balance, free_quota_used FROM wallets WHERE user_id = ?",
            (self.user["id"],),
        ).fetchone()
        self.assertEqual(dict(wallet_after), dict(wallet_before), "409 mismatch must roll back quota/credit charges")

        # Same batchId with original expected count=3 on slot 1 still succeeds.
        st_same, body_same = self._post_generate({
            "prompt": "frame 1 in same 3-card series",
            "ratio": "3:4",
            "batchId": batch_id,
            "batchIndex": 1,
            "batchTotal": 3,
            "requestId": f"req_{batch_id}_1",
            "confirmCost": True,
        })
        self.assertEqual(st_same, 200)
        self.assertTrue(body_same.get("ok"))


if __name__ == "__main__":
    unittest.main()
