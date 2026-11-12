"""Tests for full local debug stack logging, AI/HTTP error summaries, PgConnection.executemany, and backfill error reporting (#151)."""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import ai_client
from backend.observability import (
    configure_logging,
    extract_http_error_summary,
    local_debug_stacks_enabled,
    sanitize_log_text,
)
from backend.postgres_db import PgConnection
from tests.legacy_database import init_legacy_database
from backend.server import HandrawRequestHandler
from backend.services import ServiceError, run_blackbox_backfill


class _TraceProbeHandler(HandrawRequestHandler):
    def _enforce_token_scope(self):
        return

    def _handle_get(self):
        if self.path.startswith("/api/forbidden"):
            raise ServiceError("禁止访问测试", status=403, code="forbidden_test")
        if self.path.startswith("/api/explicit-fail"):
            self._send_json({"ok": False, "error": "explicit fail"}, status=502)
            return
        self._send_json({"ok": True})


class ObservabilityHelpersTests(unittest.TestCase):
    def test_extract_http_error_summary_redacts_secrets_and_html(self) -> None:
        raw_json = json.dumps({
            "error": {
                "message": "bad token Bearer tok_secret_1 via https://gw.local/x?api_key=k999 and sk-abcdefghijklmnop",
                "code": "invalid_request_error",
            }
        }).encode("utf-8")
        summary = extract_http_error_summary(raw_json)
        self.assertIn("bad token Bearer [redacted]", summary)
        self.assertIn("invalid_request_error", summary)
        for sec in ("tok_secret_1", "k999", "sk-abcdefghijklmnop"):
            self.assertNotIn(sec, summary)

        html_summary = extract_http_error_summary(b"<html><body><h1>502 Bad Gateway</h1><p>upstream down</p></body></html>")
        self.assertIn("502 Bad Gateway", html_summary)
        self.assertNotIn("<h1>", html_summary)

        self.assertEqual(sanitize_log_text("a\nb\tc", max_len=20), "a b c")

    def test_local_debug_stacks_enabled_respects_env(self) -> None:
        with patch.dict(os.environ, {"HANDRAW_LOG_STACKS": "1", "HANDRAW_ENV": "production"}, clear=False):
            self.assertTrue(local_debug_stacks_enabled())
        with patch.dict(os.environ, {"HANDRAW_LOG_STACKS": "0", "HANDRAW_ENV": "local"}, clear=False):
            self.assertFalse(local_debug_stacks_enabled())
        with patch.dict(os.environ, {"HANDRAW_ENV": "production"}, clear=False):
            os.environ.pop("HANDRAW_LOG_STACKS", None)
            self.assertFalse(local_debug_stacks_enabled())


class LocalDebugFileStackTraceTests(unittest.TestCase):
    def test_4xx_service_error_and_explicit_api_error_write_stacks_to_file_not_backend_server(self) -> None:
        root = logging.getLogger()
        old_handlers, old_level = list(root.handlers), root.level
        old_sys_hook, old_thread_hook = sys.excepthook, threading.excepthook

        server = ThreadingHTTPServer(("127.0.0.1", 0), _TraceProbeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with tempfile.TemporaryDirectory() as tmp, \
                 patch("backend.observability.get_storage_root", return_value=Path(tmp)), \
                 patch("sys.stderr", new_callable=io.StringIO), \
                 patch.dict(os.environ, {"HANDRAW_LOG_STACKS": "1"}, clear=False):
                configure_logging(port=3991)

                with self.assertLogs("backend.server", level="WARNING") as srv_logs:
                    for path in ("/api/forbidden", "/api/explicit-fail"):
                        req = Request(base + path, method="GET")
                        try:
                            with urlopen(req, timeout=5):
                                pass
                        except HTTPError as err:
                            err.read()

                # Existing backend.server contract remains unchanged (no exc_info on 4xx or explicit 502)
                self.assertEqual(len(srv_logs.records), 2)
                self.assertFalse(srv_logs.records[0].exc_info)
                self.assertFalse(srv_logs.records[1].exc_info)

                for h in root.handlers:
                    if hasattr(h, "flush"):
                        h.flush()
                log_file = Path(tmp) / "logs" / "web-3991.log"
                contents = log_file.read_text(encoding="utf-8")
                self.assertIn("handraw.trace", contents)
                self.assertIn("code=forbidden_test", contents)
                self.assertIn("Traceback (most recent call last)", contents)
                self.assertIn("ServiceError: 禁止访问测试", contents)
                self.assertIn("path=/api/explicit-fail status=502 call_stack", contents)
                for handler in list(root.handlers):
                    if handler not in old_handlers:
                        root.removeHandler(handler)
                        handler.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            for handler in list(root.handlers):
                if handler not in old_handlers:
                    root.removeHandler(handler)
                    handler.close()
            root.setLevel(old_level)
            sys.excepthook, threading.excepthook = old_sys_hook, old_thread_hook


class AIClientErrorLoggingTests(unittest.TestCase):
    def test_ai_client_http_400_logs_redacted_summary_and_trace_stack(self) -> None:
        class _BadGatewayHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                if length:
                    self.rfile.read(length)
                payload = json.dumps({
                    "error": {
                        "message": "model disabled for sk-secretkeyvalue99999",
                        "code": "model_not_available",
                    }
                }).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _BadGatewayHandler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{srv.server_port}/v1", "key": "sk-test", "model": "bad-m"}), \
                 patch.dict(os.environ, {"HANDRAW_LOG_STACKS": "1"}, clear=False), \
                 self.assertLogs("backend.ai_client", level="WARNING") as ai_logs, \
                 self.assertLogs("handraw.trace", level="INFO") as trace_logs:
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
            self.assertEqual(text, "")
            self.assertFalse(meta["ok"])
            self.assertEqual(meta["reason"], "http_400")
            joined = "\n".join(ai_logs.output)
            self.assertIn("AI HTTP error 400", joined)
            self.assertIn("model_not_available", joined)
            self.assertNotIn("sk-secretkeyvalue99999", joined)
            self.assertIn("ai_http_error status=400", "\n".join(trace_logs.output))
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=5)


class PostgresAndBackfillTests(unittest.TestCase):
    def test_pg_connection_executemany_translates_qmarks_and_logs_error_stack(self) -> None:
        mock_cur = MagicMock()
        mock_cur.rowcount = 2
        mock_cur.description = None
        mock_raw = MagicMock()
        mock_raw.cursor.return_value = mock_cur

        pg = PgConnection(mock_raw)
        cur = pg.executemany(
            "UPDATE forum_topics SET recipe_has_secret = ? WHERE id = ? AND COALESCE(recipe_json, '') = ?",
            [(0, "t1", ""), (1, "t2", "{}")],
        )
        self.assertEqual(cur.rowcount, 2)
        mock_cur.executemany.assert_called_once_with(
            "UPDATE forum_topics SET recipe_has_secret = %s WHERE id = %s AND COALESCE(recipe_json, '') = %s",
            [(0, "t1", ""), (1, "t2", "{}")],
        )

        # Empty parameter list must not call underlying driver executemany
        mock_cur.reset_mock()
        empty_cur = pg.executemany("UPDATE works SET prompt_has_secret = ? WHERE id = ?", [])
        mock_cur.executemany.assert_not_called()
        self.assertEqual(empty_cur.rowcount, 2)

        # Failing executemany logs traceback to handraw.trace without parameter leakage
        mock_cur.executemany.side_effect = RuntimeError("pg boom")
        with patch.dict(os.environ, {"HANDRAW_LOG_STACKS": "1"}, clear=False), \
             self.assertLogs("handraw.trace", level="INFO") as trace_logs:
            with self.assertRaises(RuntimeError):
                pg.executemany("UPDATE works SET prompt = ? WHERE id = ?", [("SENSITIVE_PARAM_99", "w1")])
        trace_out = "\n".join(trace_logs.output)
        self.assertIn("pg_executemany_error", trace_out)
        self.assertIn("Traceback", trace_out)
        self.assertNotIn("SENSITIVE_PARAM_99", trace_out)

    def test_run_blackbox_backfill_handles_null_recipe_json_and_logs_scan_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = init_legacy_database(Path(tmp) / "backfill_test.db")
            try:
                with db.transaction() as tx:
                    # Recreate nullable recipe_json as in PostgreSQL schemas to verify NULL equality handling
                    tx.execute("DROP TABLE forum_topics")
                    tx.execute(
                        "CREATE TABLE forum_topics (id TEXT PRIMARY KEY, recipe_json TEXT, recipe_has_secret INTEGER)"
                    )
                    tx.execute(
                        "INSERT INTO forum_topics (id, recipe_json, recipe_has_secret) VALUES (?, NULL, NULL)",
                        ("topic_null_rj_1",),
                    )

                counts = run_blackbox_backfill(db)
                self.assertGreaterEqual(counts["topics"], 1)
                row = db.get_conn().execute(
                    "SELECT recipe_has_secret FROM forum_topics WHERE id = 'topic_null_rj_1'"
                ).fetchone()
                self.assertEqual(row["recipe_has_secret"], 0)
                # Hash was persisted cleanly, so immediate second run does zero topic updates
                counts2 = run_blackbox_backfill(db)
                self.assertEqual(counts2["topics"], 0)

                # Corrupt recipe_json topic logs full traceback instead of silently ignoring exception
                with db.transaction() as tx:
                    tx.execute(
                        "INSERT INTO forum_topics (id, recipe_json, recipe_has_secret) VALUES (?, '{not-valid-json', NULL)",
                        ("topic_bad_rj_1",),
                    )
                with self.assertLogs("backend.services", level="WARNING") as svc_logs:
                    run_blackbox_backfill(db)
                svc_out = "\n".join(svc_logs.output)
                self.assertIn("topic scan failed for id=topic_bad_rj_1", svc_out)
                self.assertIn("JSONDecodeError", svc_out)
                self.assertIn("Traceback", svc_out)
            finally:
                db.close_thread_conn()
                db.close()


if __name__ == "__main__":
    unittest.main()
