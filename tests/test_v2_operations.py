"""Native PostgreSQL archive and recovery tests."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.security import verify_password
from ops.postgres_backup import PostgresArchiveError
from ops.v2_manage import (
    BackupIntegrityError, OperationsError, SafetyError, Workspace, backup_workspace,
    bootstrap_admin, health_status, restore_workspace, verify_backup,
)
from tests.postgres_support import isolated_pg_dsn


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        raw = json.dumps({"ok": True, "version": "2.0.0", "db": True, "secret": "must-not-leak"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        return


class HealthTests(unittest.TestCase):
    def test_health_reader_returns_only_safe_fields(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = health_status(f"http://127.0.0.1:{server.server_port}/api/health")
            finally:
                server.shutdown()
                thread.join(timeout=2)
        self.assertEqual(result, {"ok": True, "status": 200, "version": "2.0.0", "db": True})


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class PostgresRecoveryTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.dsn = self.enterContext(isolated_pg_dsn())
        self.conn = self.enterContext(psycopg.connect(self.dsn, autocommit=True))
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="handraw-pg-ops-")))
        self.root = self.temp / "workspace"
        self.workspace = Workspace.resolve(
            self.root, self.dsn, self.root / "private" / "uploads", self.root / "private" / "generated",
        )
        self.workspace.uploads.mkdir(parents=True)
        self.workspace.generated.mkdir()
        (self.workspace.uploads / "source.txt").write_text("upload-before", encoding="utf-8")
        (self.workspace.generated / "generated.txt").write_text("generated-before", encoding="utf-8")
        self.conn.execute("CREATE TABLE public.records (id integer PRIMARY KEY, value text NOT NULL)")
        self.conn.execute("INSERT INTO public.records VALUES (1, 'before')")

    def test_online_backup_then_offline_source_restore(self):
        import psycopg

        archive_dir = self.temp / "backup"
        restored_dir = self.temp / "recovery"
        with psycopg.connect(self.dsn) as writer:
            writer.execute("UPDATE public.records SET value='uncommitted' WHERE id=1")
            saved = backup_workspace(self.workspace, archive_dir)
            writer.rollback()

        self.assertEqual(saved["database"]["format"], "postgresql-custom")
        manifest = (archive_dir / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn(self.dsn, manifest)
        self.assertNotIn(str(self.workspace.uploads), manifest)
        self.assertEqual(verify_backup(archive_dir, self.workspace), saved)

        self.conn.execute("UPDATE public.records SET value='after' WHERE id=1")
        (self.workspace.uploads / "extra.txt").write_text("source-only", encoding="utf-8")
        restore_dsn = self.enterContext(isolated_pg_dsn(initialize=False))
        dry_run = restore_workspace(
            self.workspace, archive_dir, restore_database_url=restore_dsn, restore_dir=restored_dir, dry_run=True,
        )
        self.assertTrue(dry_run["dryRun"])
        self.assertFalse(restored_dir.exists())

        real_connect = psycopg.connect
        connections = []
        def connect_to_destination_only(dsn, **kwargs):
            self.assertEqual(dsn, restore_dsn)
            connections.append(dsn)
            return real_connect(dsn, **kwargs)

        with patch.object(psycopg, "connect", side_effect=connect_to_destination_only):
            restored = restore_workspace(
                self.workspace, archive_dir, restore_database_url=restore_dsn, restore_dir=restored_dir,
            )
        self.assertTrue(connections)
        self.assertTrue(restored["restored"])
        with psycopg.connect(restore_dsn) as recovered:
            self.assertEqual(recovered.execute("SELECT value FROM public.records WHERE id=1").fetchone()[0], "before")
            self.assertEqual(recovered.execute(
                "SELECT count(*) FROM public.schema_migrations WHERE version IN (100,110)"
            ).fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT value FROM public.records WHERE id=1").fetchone()[0], "after")
        self.assertTrue((self.workspace.uploads / "extra.txt").exists())
        self.assertFalse((restored_dir / "uploads" / "extra.txt").exists())
        self.assertEqual((restored_dir / "uploads" / "source.txt").read_text(encoding="utf-8"), "upload-before")
        self.assertEqual((restored_dir / "demo_generated" / "generated.txt").read_text(encoding="utf-8"), "generated-before")

    def test_manifest_and_file_corruption_rejected(self):
        archive_dir = self.temp / "backup"
        backup_workspace(self.workspace, archive_dir)
        archive = archive_dir / "database.dump"
        original = archive.read_bytes()
        archive.write_bytes(original + b"corrupt")
        with self.assertRaisesRegex(BackupIntegrityError, "归档 checksum"):
            verify_backup(archive_dir, self.workspace)
        archive.write_bytes(original)
        (archive_dir / "generated" / "generated.txt").write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(BackupIntegrityError, "generated.*checksum"):
            verify_backup(archive_dir, self.workspace)

    def test_restore_refuses_existing_targets_and_foreign_workspace(self):
        archive_dir = self.temp / "backup"
        backup_workspace(self.workspace, archive_dir)
        with self.assertRaises(SafetyError):
            backup_workspace(self.workspace, archive_dir)
        other_workspace = Workspace.resolve(self.temp / "other", self.dsn)
        with self.assertRaisesRegex(SafetyError, "备份来源"):
            verify_backup(archive_dir, other_workspace)
        restore_dir = self.temp / "recovery"
        with self.assertRaisesRegex(SafetyError, "独立"):
            restore_workspace(self.workspace, archive_dir, restore_database_url=self.dsn, restore_dir=restore_dir)
        populated = self.enterContext(isolated_pg_dsn())
        with self.assertRaisesRegex(SafetyError, "必须为空"):
            restore_workspace(self.workspace, archive_dir, restore_database_url=populated, restore_dir=restore_dir)
        self.assertFalse(restore_dir.exists())
        restore_dir.mkdir()
        sentinel = restore_dir / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(SafetyError, "全新目录"):
            restore_workspace(self.workspace, archive_dir, restore_database_url=populated, restore_dir=restore_dir)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_failed_pg_restore_rolls_back_and_removes_new_media(self):
        import psycopg

        # A corrupt legacy row can be copied into the archive. Adding the foreign
        # key during restore must fail after the data phase has started.
        with self.conn.transaction():
            self.conn.execute("SET LOCAL session_replication_role = replica")
            self.conn.execute("INSERT INTO public.wallets (user_id, balance, updated_at) VALUES (-1, 0, '')")
        archive_dir = self.temp / "backup"
        backup_workspace(self.workspace, archive_dir)
        restore_dsn = self.enterContext(isolated_pg_dsn(initialize=False))
        restored_dir = self.temp / "recovery"
        with self.assertRaisesRegex(PostgresArchiveError, "pg_restore failed"):
            restore_workspace(
                self.workspace, archive_dir, restore_database_url=restore_dsn, restore_dir=restored_dir,
            )
        self.assertFalse(restored_dir.exists())
        with psycopg.connect(restore_dsn) as target:
            self.assertEqual(target.execute("SELECT to_regclass('public.schema_migrations')").fetchone(), (None,))
            self.assertEqual(target.execute("SELECT to_regclass('public.records')").fetchone(), (None,))
        self.assertEqual(self.conn.execute("SELECT value FROM public.records WHERE id=1").fetchone()[0], "before")

    def test_first_admin_is_created_once_without_demo_data_or_credits(self):
        def create(name):
            try:
                return bootstrap_admin(
                    self.workspace, username=name, display_name=name, email=f"{name}@example.test",
                    password="nondefault-password-1234",
                )
            except OperationsError as exc:
                self.assertIn("已有 active admin", str(exc))
                return None

        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(create, ("owner_one", "owner_two")))
        [created] = [result for result in results if result is not None]
        self.assertNotIn("password", created)
        rows = self.conn.execute("""
            SELECT u.username, u.role, u.password_hash, w.balance FROM public.users AS u
            JOIN public.wallets AS w ON w.user_id=u.id
        """).fetchall()
        [(username, role, stored_hash, balance)] = rows
        self.assertEqual((username, role, balance), (created["username"], "admin", 0))
        self.assertTrue(verify_password("nondefault-password-1234", stored_hash))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM public.ledgers").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
