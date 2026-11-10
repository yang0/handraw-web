"""#112 probe safety. Local loopback HTTP only; no production gateway/remote objects."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ops.audit_object_leak_112 import audit, main, validate_manifest


class Handler(BaseHTTPRequestHandler):
    redirect_target_called = False
    leaked_authorization = ""

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()
            return
        if self.path == "/redirect-target":
            Handler.redirect_target_called = True
            Handler.leaked_authorization = self.headers.get("Authorization", "")
        if self.path == "/private-owner":
            status = 200 if self.headers.get("Cookie") == "session=owner-secret" else 403
        elif self.path == "/private-cross-user":
            status = 403 if self.headers.get("Authorization") == "Bearer other-secret" else 401
        elif self.path == "/public" or self.path == "/redirect-target":
            status = 200
        else:
            status = 403
        self.send_response(status)
        self.send_header("Content-Type", "image/png" if status == 200 else "application/json")
        self.end_headers()
        self.wfile.write(b"SECRET-BYTES-DO-NOT-LOG")

    def log_message(self, fmt, *args):
        return


class ObjectLeakAuditor112(unittest.TestCase):
    def setUp(self):
        Handler.redirect_target_called = False
        Handler.leaked_authorization = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = "127.0.0.1:" + str(self.server.server_port)
        root = "http://" + self.host
        paths = {
            "public_work": "/public", "private_owner": "/private-owner",
            "private_anonymous": "/private-anon", "private_cross_user": "/private-cross-user",
            "hidden_work": "/hidden", "private_bucket_object": "/bucket-private",
            "expired_signed_url": "/expired?X-Amz-Signature=top-secret-signed-query",
            "bucket_listing": "/?list-type=2",
        }
        self.manifest = {
            "schema_version": 1, "environment": "preproduction",
            "release_sha": "f" * 40, "cases": [],
        }
        for key, path in paths.items():
            case = {"id": key, "url": root + path,
                    "expect": "allow" if key in ("public_work", "private_owner") else "deny"}
            if key == "private_owner":
                case.update(auth_env="HANDRAW_AUDIT_OWNER_COOKIE", auth_kind="cookie")
            if key == "private_cross_user":
                case.update(auth_env="HANDRAW_AUDIT_OTHER_TOKEN", auth_kind="bearer")
            if key == "expired_signed_url":
                case["expired_at_utc"] = "2020-01-01T00:00:00Z"
            self.manifest["cases"].append(case)
        self.opts = {"allowed_hosts": {self.host}, "allow_http_test": True}
        self.env = {"HANDRAW_AUDIT_OWNER_COOKIE": "session=owner-secret",
                    "HANDRAW_AUDIT_OTHER_TOKEN": "other-secret"}

    def test_eight_real_http_reads_no_sensitive_output_and_never_go(self):
        with patch.dict(os.environ, self.env):
            result = audit(self.manifest, **self.opts)
        self.assertTrue(result["allProbesPassed"])
        self.assertEqual(result["decision"], "NO-GO")
        self.assertFalse(result["productionVerified"])
        payload = json.dumps(result)
        for sensitive in ("owner-secret", "other-secret", "X-Amz-Signature", self.host,
                          "SECRET-BYTES-DO-NOT-LOG"):
            self.assertNotIn(sensitive, payload)

    def test_cross_user_success_is_rejected(self):
        cases = self.manifest["cases"]
        next(c for c in cases if c["id"] == "private_cross_user")["url"] = (
            "http://" + self.host + "/public")
        with patch.dict(os.environ, self.env):
            result = audit(self.manifest, **self.opts)
        self.assertFalse(result["allProbesPassed"])
        self.assertEqual(next(c for c in result["checks"] if c["id"] == "private_cross_user")["status"], 200)

    def test_redirect_does_not_forward_bearer_or_pass_as_denied(self):
        next(c for c in self.manifest["cases"] if c["id"] == "private_cross_user")["url"] = (
            "http://" + self.host + "/redirect")
        with patch.dict(os.environ, self.env):
            result = audit(self.manifest, **self.opts)
        self.assertFalse(result["allProbesPassed"])
        self.assertFalse(Handler.redirect_target_called)
        self.assertEqual(Handler.leaked_authorization, "")

    def test_validation_rejects_case_weakening_missing_duplicate_insecure_origin(self):
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, allowed_hosts={self.host})
        cases = self.manifest["cases"]
        cases[0]["expect"] = "deny"
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, **self.opts)
        cases[0]["expect"] = "allow"
        cases[0]["id"] = "private_anonymous"
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, **self.opts)

    def test_incomplete_credentials_fail_closed(self):
        with patch.dict(os.environ, self.env, clear=True):
            del os.environ["HANDRAW_AUDIT_OTHER_TOKEN"]
            result = audit(self.manifest, **self.opts)
        self.assertFalse(result["allProbesPassed"])
        self.assertEqual(next(c["error"] for c in result["checks"]
                              if c["id"] == "private_cross_user"),
                         "missing_or_invalid_audit_credential")

    def test_cli_writes_owner_only_report_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td)/"manifest.json"
            report = Path(td)/"report.json"
            manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
            args = ["--manifest", str(manifest), "--report", str(report),
                    "--allowed-host", self.host, "--allow-http-test"]
            with patch.dict(os.environ, self.env):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 2)
            self.assertEqual(report.stat().st_mode & 0o077, 0)
            self.assertNotIn("top-secret-signed-query", report.read_text())


if __name__ == "__main__":
    unittest.main()
