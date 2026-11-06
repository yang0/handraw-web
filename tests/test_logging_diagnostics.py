"""Regression tests for multi-level, rotating and privacy-preserving diagnostics."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.logging_config import _SafeFormatter, redact


class LoggingDiagnosticsTests(unittest.TestCase):
    def test_redact_credentials_in_message(self):
        raw = "client_secret=abc123 password:badToken Authorization:Bearer.123 postgresql://alice:secret@localhost/db"
        safe = redact(raw)
        self.assertNotIn("abc123", safe)
        self.assertNotIn("badToken", safe)
        self.assertNotIn("alice:secret@", safe)
        self.assertIn("[REDACTED]", safe)

    def test_traceback_text_is_redacted(self):
        formatter = _SafeFormatter("%(levelname)s %(message)s")
        try:
            raise RuntimeError("access_token=topsecret")
        except RuntimeError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 12, "failure", (), exc_info
        )
        rendered = formatter.format(record)
        self.assertIn("RuntimeError", rendered)
        self.assertNotIn("topsecret", rendered)

    def test_rotating_logs_and_levels(self):
        # Verify config in a fresh process, avoiding changes to pytest's handlers.
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            script = (
                "import logging, os\n"
                "from backend.logging_config import configure_logging\n"
                "configure_logging()\n"
                "log=logging.getLogger('handraw.test')\n"
                "log.debug('debug_marker')\n"
                "log.info('info_marker')\n"
                "log.warning('warn_marker')\n"
                "log.error('error_marker access_token=secretvalue')\n"
                "log.critical('critical_marker')\n"
            )
            env = dict(os.environ, HANDRAW_LOG_DIR=tmp, HANDRAW_LOG_LEVEL="INFO")
            proc = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                                  env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            combined = (Path(tmp) / "handraw.log").read_text(encoding="utf-8")
            errors = (Path(tmp) / "handraw-error.log").read_text(encoding="utf-8")
            self.assertIn("info_marker", combined)
            self.assertIn("warn_marker", combined)
            self.assertIn("error_marker", combined)
            self.assertIn("critical_marker", combined)
            self.assertNotIn("debug_marker", combined)
            self.assertNotIn("info_marker", errors)
            self.assertIn("error_marker", errors)
            self.assertIn("critical_marker", errors)
            self.assertNotIn("secretvalue", combined)
            self.assertNotIn("secretvalue", errors)

    def test_internal_error_generates_reference_not_exception_details(self):
        from backend.server import HandrawRequestHandler
        handler = object.__new__(HandrawRequestHandler)
        handler.command = "GET"
        handler.path = "/api/boot?code=never-log-oauth-code&state=private"
        handler._send_json = Mock()
        with patch("backend.server.logger.exception") as log_exc:
            try:
                raise ValueError("password=do-not-expose")
            except ValueError:
                handler._internal_error()
        kwargs = handler._send_json.call_args.kwargs
        body = handler._send_json.call_args.args[0]
        self.assertEqual(kwargs["status"], 500)
        self.assertEqual(body["code"], "internal_error")
        self.assertEqual(len(body["requestId"]), 12)
        self.assertEqual(kwargs["request_id"], body["requestId"])
        self.assertNotIn("do-not-expose", str(body))
        self.assertNotIn("never-log-oauth-code", str(log_exc.call_args))
        self.assertIn("/api/boot", str(log_exc.call_args))


if __name__ == "__main__":
    unittest.main()
