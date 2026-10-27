"""Temporary-workspace tests for the v2 operations tool."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.security import verify_password
from ops.v2_manage import (
    BackupIntegrityError,
    OperationsError,
    SafetyError,
    Workspace,
    backup_workspace,
    bootstrap_admin,
    health_status,
    restore_preflight,
    restore_workspace,
    verify_backup,
)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        payload = {"ok": True, "version": "2.0.0", "db": True, "secret": "must-not-leak"}
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args: object) -> None:
        return


class V2OperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="handraw-v2-ops-")
        self.root = Path(self.temp_dir.name) / "workspace"
        self.root.mkdir()
        self.workspace = Workspace.resolve(
            self.root,
            self.root / "private" / "handraw_v2.db",
            self.root / "private" / "uploads",
            self.root / "private" / "generated",
        )
        self.workspace.database.parent.mkdir(parents=True)
        database = Database(self.workspace.database)
        database.migrate()
        database.close()
        connection = sqlite3.connect(self.workspace.database)
        connection.executescript(
            """
            CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO records VALUES (1, 'before');
            """
        )
        connection.commit()
        connection.close()
        self.workspace.uploads.mkdir(parents=True)
        self.workspace.generated.mkdir(parents=True)
        (self.workspace.uploads / "source.txt").write_text("upload-before", encoding="utf-8")
        (self.workspace.generated / "generated.txt").write_text("generated-before", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_online_backup_manifest_and_private_files(self) -> None:
        # An uncommitted writer transaction must not leak into the consistent
        # snapshot obtained through sqlite3.Connection.backup().
        writer = sqlite3.connect(self.workspace.database)
        writer.execute("BEGIN")
        writer.execute("UPDATE records SET value='uncommitted' WHERE id=1")

        backup_dir = Path(self.temp_dir.name) / "backups" / "one"
        summary = backup_workspace(self.workspace, backup_dir)
        self.assertTrue(summary["ok"])
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest_text = json.dumps(manifest, ensure_ascii=False).lower()
        self.assertNotIn("password", manifest_text)
        self.assertNotIn("api_key", manifest_text)
        self.assertNotIn("must-not-leak", manifest_text)
        self.assertEqual((backup_dir / "uploads" / "source.txt").read_text(encoding="utf-8"), "upload-before")
        self.assertEqual((backup_dir / "generated" / "generated.txt").read_text(encoding="utf-8"), "generated-before")
        self.assertTrue(verify_backup(backup_dir, self.workspace)["ok"])

        snapshot = sqlite3.connect(backup_dir / "database.sqlite3")
        self.assertEqual(snapshot.execute("SELECT value FROM records WHERE id=1").fetchone()[0], "before")
        snapshot.close()
        writer.rollback()
        writer.close()

    def test_checksum_corruption_is_rejected_before_restore(self) -> None:
        backup_dir = Path(self.temp_dir.name) / "backups" / "corrupt"
        backup_workspace(self.workspace, backup_dir)
        (backup_dir / "generated" / "generated.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaises(BackupIntegrityError):
            verify_backup(backup_dir, self.workspace)
        with self.assertRaises(BackupIntegrityError):
            restore_preflight(self.workspace, backup_dir)
        self.assertEqual((self.workspace.generated / "generated.txt").read_text(encoding="utf-8"), "generated-before")

    def test_restore_requires_stop_write_and_backups_current_state(self) -> None:
        backup_dir = Path(self.temp_dir.name) / "backups" / "valid"
        backup_workspace(self.workspace, backup_dir)
        connection = sqlite3.connect(self.workspace.database)
        try:
            connection.execute("UPDATE records SET value='after' WHERE id=1")
            connection.commit()
        finally:
            connection.close()
        (self.workspace.uploads / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaises(SafetyError):
            restore_workspace(self.workspace, backup_dir)
        connection = sqlite3.connect(self.workspace.database)
        try:
            self.assertEqual(connection.execute("SELECT value FROM records WHERE id=1").fetchone()[0], "after")
        finally:
            connection.close()

        result = restore_workspace(self.workspace, backup_dir, stop_write=True)
        self.assertTrue(result["restored"])
        self.assertTrue(Path(result["preRestoreBackup"]).is_dir())
        connection = sqlite3.connect(self.workspace.database)
        try:
            self.assertEqual(connection.execute("SELECT value FROM records WHERE id=1").fetchone()[0], "before")
        finally:
            connection.close()
        self.assertEqual((self.workspace.uploads / "source.txt").read_text(encoding="utf-8"), "upload-before")
        self.assertFalse((self.workspace.uploads / "extra.txt").exists())
        self.assertEqual((self.workspace.generated / "generated.txt").read_text(encoding="utf-8"), "generated-before")

    def test_restore_refuses_different_workspace_target(self) -> None:
        backup_dir = Path(self.temp_dir.name) / "backups" / "scope"
        backup_workspace(self.workspace, backup_dir)
        other_root = Path(self.temp_dir.name) / "other"
        other = Workspace.resolve(
            other_root,
            other_root / "private" / "handraw_v2.db",
            other_root / "private" / "uploads",
            other_root / "private" / "generated",
        )
        with self.assertRaises(SafetyError):
            restore_preflight(other, backup_dir)

    def test_restore_refuses_database_schema_downgrade(self) -> None:
        backup_dir = Path(self.temp_dir.name) / "backups" / "schema"
        backup_workspace(self.workspace, backup_dir)
        manifest_path = backup_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["database"]["schemaMigrations"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(SafetyError):
            restore_preflight(self.workspace, backup_dir)

    def test_bootstrap_admin_has_no_default_password_or_demo_seed(self) -> None:
        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}, clear=False):
            result = bootstrap_admin(
                self.workspace,
                username="real_owner",
                display_name="Real Owner",
                email="owner@example.com",
                password="not-a-default-1234",
            )
        self.assertEqual(result["role"], "admin")
        self.assertNotIn("password", result)
        connection = sqlite3.connect(self.workspace.database)
        row = connection.execute("SELECT role, password_hash FROM users WHERE username='real_owner'").fetchone()
        self.assertEqual(row[0], "admin")
        self.assertTrue(verify_password("not-a-default-1234", row[1]))
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM records").fetchone()[0], 1)
        connection.close()
        with self.assertRaises(OperationsError):
            bootstrap_admin(
                self.workspace,
                username="other_owner",
                display_name="Other",
                email="other@example.com",
                password="another-password-1234",
            )

    def test_health_reader_returns_only_safe_fields(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = health_status(f"http://127.0.0.1:{server.server_address[1]}/api/health")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result, {"ok": True, "status": 200, "version": "2.0.0", "db": True})
        self.assertNotIn("secret", result)


if __name__ == "__main__":
    unittest.main()
