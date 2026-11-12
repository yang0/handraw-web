"""Native schema bootstrap rollback and index upgrade guarantees."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from ops.bootstrap_postgres_v3 import bootstrap
from tests.postgres_support import isolated_pg_dsn, open_isolated_postgres


class PostgresSchemaUpgradeTests(unittest.TestCase):
    def test_index_upgrade_preserves_keys_oids_and_is_idempotent(self):
        db = open_isolated_postgres(self)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT c.oid,c.relname,pg_get_indexdef(c.oid) AS definition "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='i' AND c.relname LIKE 'uq_%'").fetchall()
        self.assertEqual(len(rows), 23)
        for i, row in enumerate(rows):
            conn._db.execute(sql.SQL("ALTER INDEX public.{} RENAME TO {}").format(
                sql.Identifier(row["relname"]), sql.Identifier(f"retired_unique_{i}")))
        migration = (Path(__file__).resolve().parents[1] / "backend" /
                     "postgres_117_unique_index_names.sql").read_text(encoding="utf-8")
        conn.execute(migration)
        conn.execute(migration)
        for row in rows:
            result = conn.execute("SELECT oid,pg_get_indexdef(oid) AS definition "
                                  "FROM pg_class WHERE oid=?", (row["oid"],)).fetchone()
            self.assertEqual(result["definition"], row["definition"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=117").fetchone()[0], 1)

    def test_bootstrap_failure_rolls_back_schema_and_can_retry(self):
        dsn = self.enterContext(isolated_pg_dsn(initialize=False))
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        invalid = root / "invalid.sql"
        invalid.write_text("CREATE TABLE public.partial_fixture (id bigint); SELECT missing_column;", encoding="utf-8")
        with patch.dict("os.environ", {"HANDRAW_ALLOW_PG_BOOTSTRAP": "YES"}):
            with patch("ops.bootstrap_postgres_v3.MIGRATIONS", (invalid,)):
                with self.assertRaises(psycopg.errors.UndefinedColumn):
                    bootstrap(dsn=dsn, apply=True)
            with psycopg.connect(dsn) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0], 0)
            self.assertTrue(bootstrap(dsn=dsn, apply=True)["created"])
