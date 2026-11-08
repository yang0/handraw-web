"""#112 backup/restore safety preflight and real PostgreSQL 17 CI rehearsal.

No production DSN, user records or paid gateway. Three RANDOM, disposable PG
databases only; source untouched. pg_dump/pg_restore executed inside the already
running postgres:17 GitHub Actions service to avoid local client version skew.
"""
from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from ops.pg_release_restore_drill_112 import (
    ALLOW_ENV, preflight, run_drill, settings,
)


class PgReleaseDrillSafetyTests112(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = Path(self.tmp.name) / "private-backup.dump"
        self.src = "postgresql://postgres:pass@127.0.0.1:5432/handraw_drill_source"
        self.dst = "postgresql://postgres:pass@127.0.0.1:5432/handraw_restore_drill_one"
        self.undo = "postgresql://postgres:pass@127.0.0.1:5432/handraw_restore_drill_two"

    def test_default_fails_closed_without_operator_approval(self):
        with patch.dict(os.environ, {ALLOW_ENV:""}):
            with self.assertRaisesRegex(RuntimeError,ALLOW_ENV):
                preflight(self.src,self.dst,self.undo,self.archive)

    def test_source_target_alias_and_system_database_rejected(self):
        with patch.dict(os.environ, {ALLOW_ENV:"YES"}):
            for values in (
                (self.src,self.src,self.undo),
                (self.src,self.dst,self.dst),
                (self.src,"postgresql://postgres:pass@127.0.0.1/postgres",self.undo),
                (self.src,"postgresql://postgres:pass@127.0.0.1/not_a_disposable_db",self.undo),
            ):
                with self.subTest(values=values),self.assertRaises(RuntimeError):
                    preflight(*values,self.archive)

    def test_archive_must_not_exist_or_be_symlink(self):
        with patch.dict(os.environ, {ALLOW_ENV:"YES"}):
            self.archive.write_bytes(b"do not touch")
            with self.assertRaises(RuntimeError):
                preflight(self.src,self.dst,self.undo,self.archive)
            self.assertEqual(self.archive.read_bytes(),b"do not touch")

    def test_libpq_query_override_and_cross_server_refused(self):
        with patch.dict(os.environ, {ALLOW_ENV:"YES"}):
            with self.assertRaises(RuntimeError):
                settings(self.src+"?dbname=postgres")
            wrong_host=self.undo.replace("127.0.0.1","127.0.0.2")
            with self.assertRaises(RuntimeError):
                preflight(self.src,self.dst,wrong_host,self.archive)


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL") and
                     os.environ.get("HANDRAW_PG_DRILL_DOCKER_CONTAINER"),
                     "requires real isolated postgres:17 service and PG client")
class RealPgBackupRestore112(unittest.TestCase):
    def test_pg17_dump_restore_rollback_all_rows_exact(self):
        import psycopg
        from psycopg import sql
        from urllib.parse import urlsplit, urlunsplit
        from backend.postgres_db import PostgresDatabase
        from backend.services import apply_wallet_delta, register_user
        from ops.bootstrap_postgres_v3 import bootstrap

        admin=os.environ["HANDRAW_PG_STAGING_URL"]
        ident=uuid.uuid4().hex[:10]
        source="handraw_qa112_backup_"+ident
        restore="handraw_restore_drill_live_"+ident
        rollback="handraw_restore_drill_undo_"+ident
        names=(source,restore,rollback)

        with psycopg.connect(admin,autocommit=True) as conn:
            for name in names:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            def target_url(name):
                parsed=urlsplit(admin)
                return urlunsplit((parsed.scheme,parsed.netloc,"/"+name,
                                   parsed.query,parsed.fragment))
            source_dsn=target_url(source)
            restore_dsn=target_url(restore)
            rollback_dsn=target_url(rollback)
            with patch.dict(os.environ,{"HANDRAW_ALLOW_PG_BOOTSTRAP":"YES"}):
                report=bootstrap(dsn=source_dsn,apply=True)
            self.assertTrue(report["created"])
            db=PostgresDatabase(source_dsn)
            try:
                db.migrate()
                owner,_=register_user(db,"pg112_backup_owner","StrongPassword#112!")
                uid=int(owner["id"])
                with db.transaction() as tx:
                    # Real paid debit/refund rows must roundtrip with the
                    # original user's password hash and durable wallet value.
                    apply_wallet_delta(
                        tx,uid,-2,"studio_gen","CI charged attempt",
                        event_key="qa112_pg_charge",ref_type="generation",
                        ref_id="gen_pg112",
                    )
                    apply_wallet_delta(
                        tx,uid,2,"studio_refund","CI confirmed refund",
                        event_key="qa112_pg_refund",ref_type="generation",
                        ref_id="gen_pg112",
                    )
            finally:
                db.close()

            with tempfile.TemporaryDirectory(prefix="pg112-backup-") as tmp:
                archive=Path(tmp)/"snapshot.dump"
                with patch.dict(os.environ,{ALLOW_ENV:"YES"}):
                    result=run_drill(
                        source=source_dsn,restore=restore_dsn,
                        rollback=rollback_dsn,archive=archive,
                        container_id=os.environ["HANDRAW_PG_DRILL_DOCKER_CONTAINER"],
                    )
                self.assertTrue(result["ok"])
                self.assertTrue(result["fingerprintsMatched"])
                self.assertTrue(result["sourceUntouched"])
                self.assertTrue(result["backupBasedRollbackVerified"])
                self.assertTrue(result["transactionalRollbackVerified"])
                self.assertGreater(result["archiveBytes"],512)
                self.assertGreaterEqual(result["rowCounts"]["users"],1)
                self.assertGreaterEqual(result["rowCounts"]["ledgers"],2)
                self.assertEqual(archive.stat().st_mode & 0o077,0,
                                 "backup must remain owner-readable only")
                with psycopg.connect(rollback_dsn) as c:
                    rows=c.execute(
                        "SELECT event_key,delta FROM ledgers "
                        "WHERE event_key IN ('qa112_pg_charge','qa112_pg_refund') "
                        "ORDER BY event_key"
                    ).fetchall()
                    self.assertEqual(len(rows),2)
                    self.assertEqual(sum(int(x[1]) for x in rows),0)
                print("ISSUE #112 real PG17 custom dump/restore to TWO "
                      "empty disposable databases, transactional and snapshot "
                      "rollback, every-row hashes, ledger balance PASS")
        finally:
            with psycopg.connect(admin,autocommit=True) as conn:
                for name in reversed(names):
                    conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(name)))


if __name__=="__main__":
    unittest.main()
