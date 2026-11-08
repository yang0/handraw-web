"""Existing-PostgreSQL Studio Project migration 101 safety regression.

No live database required. Every execution path is asserted to be non-
destructive; SQL failures are handled by the driver's surrounding transaction.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

from ops.migrate_pg_studio_projects import (
    ALLOW_ENV, NAME, PROJECT_TABLES_SQL, inspect_state, migrate,
    validate_database_name,
)


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def __init__(self, *, base=True, applied=False, partial=False, wrong_name=False):
        self.base = base
        self.applied = applied
        self.partial = partial
        self.wrong_name = wrong_name
        self.commands = []
        self.answer = None
        self.db = None

    def execute(self, statement, params=()):
        sql = str(statement).strip()
        self.commands.append((sql, params))
        if "to_regclass" in sql:
            self.answer = (
                ("schema_migrations", "users", "generation_runs", "media_assets",
                 "studio_projects" if self.applied or self.partial else None,
                 "studio_project_requests" if self.applied else None,
                 "pg_idx_studio_projects_owner_updated" if self.applied else None)
                if self.base else (None,) * 7
            )
        elif "SELECT version,name" in sql:
            self.answer = [(100, "100_native_v3"),
                           *(([(101, "DIFFERENT_NAME" if self.wrong_name else NAME)]
                              if self.applied else []))]
        elif sql.startswith("CREATE TABLE public.studio_projects"):
            self.applied = True
            self.partial = False
        elif sql.startswith("INSERT INTO public.schema_migrations"):
            self.applied = True
        else:
            self.answer = [(1,)]

    def fetchone(self):
        if isinstance(self.answer, tuple):
            return self.answer
        if isinstance(self.answer, list):
            return self.answer[0] if self.answer else None
        return self.answer

    def fetchall(self):
        return self.answer if isinstance(self.answer, list) else [self.answer]


class FakeConnection:
    def __init__(self, cursor):
        self.cur = cursor
        self.commit_count = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        if t is None:
            self.commit_count += 1
        self.closed = True
        return False

    def cursor(self):
        return self.cur


def fake_driver(connection):
    """Unit-test driver without installing a live PostgreSQL dependency."""
    fake = types.ModuleType("psycopg")
    fake.connect = lambda *args, **kwargs: connection
    return patch.dict(sys.modules, {"psycopg": fake})


class ExistingPostgresProjectMigrationTests(unittest.TestCase):
    dsn = "postgresql://localhost/handraw_project_migration_test"

    def test_sql_is_additive_only_with_fks_and_unique_idempotency(self):
        ddl = PROJECT_TABLES_SQL.upper()
        for banned in ["DROP ", "TRUNCATE ", "DELETE ", "UPDATE ", "ALTER ",
                       "REPLACE ", "CASCADE"]:
            self.assertNotIn(banned, ddl)
        self.assertIn("REFERENCES PUBLIC.USERS(ID)", ddl)
        self.assertIn("REFERENCES PUBLIC.STUDIO_PROJECTS(ID)", ddl)
        self.assertIn("PRIMARY KEY (USER_ID, PROJECT_ID, IDEMPOTENCY_KEY)", ddl)
        self.assertIn("UPDATED_AT DESC", ddl)

    def test_system_database_never_allowed(self):
        for name in ("postgres", "template0", "template1", ""):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_database_name("postgresql://localhost/" + name)
        validate_database_name(self.dsn)

    def test_dry_run_uses_only_selects_and_transaction_settings(self):
        c = FakeCursor()
        conn = FakeConnection(c)
        with fake_driver(conn), \
                patch.dict(os.environ, {ALLOW_ENV: ""}):
            r = migrate(dsn=self.dsn, apply=False)
        self.assertTrue(r["dryRun"])
        self.assertTrue(r["requiresMigration"])
        self.assertFalse(r["destructiveOperations"])
        self.assertFalse(any("CREATE TABLE" in q for q, _ in c.commands))
        self.assertTrue(conn.closed)

    def test_apply_refuses_without_explicit_operator_approval(self):
        c = FakeCursor()
        with fake_driver(FakeConnection(c)), \
                patch.dict(os.environ, {ALLOW_ENV: ""}):
            with self.assertRaisesRegex(RuntimeError, ALLOW_ENV):
                migrate(dsn=self.dsn, apply=True)
        self.assertFalse(any("CREATE TABLE" in q for q, _ in c.commands))

    def test_atomic_apply_and_repeat_is_noop(self):
        c = FakeCursor()
        with fake_driver(FakeConnection(c)), \
                patch.dict(os.environ, {ALLOW_ENV: "YES"}):
            result = migrate(dsn=self.dsn, apply=True)
        self.assertTrue(result["applied"])
        self.assertFalse(result["requiresMigration"])
        self.assertTrue(any("CREATE TABLE public.studio_projects" in q for q, _ in c.commands))
        self.assertTrue(any("INSERT INTO public.schema_migrations" in q for q, _ in c.commands))
        c.commands.clear()
        with fake_driver(FakeConnection(c)), \
                patch.dict(os.environ, {ALLOW_ENV: "YES"}):
            already = migrate(dsn=self.dsn, apply=True)
        self.assertTrue(already["alreadyApplied"])
        self.assertFalse(any("CREATE TABLE" in q for q, _ in c.commands))

    def test_missing_baseline_and_partial_or_drifted_upgrade_are_refused(self):
        for options in ({"base":False}, {"partial":True},
                        {"applied":True,"wrong_name":True}):
            with self.subTest(options=options):
                c = FakeCursor(**options)
                with fake_driver(FakeConnection(c)), \
                        patch.dict(os.environ, {ALLOW_ENV: "YES"}):
                    with self.assertRaises(RuntimeError):
                        migrate(dsn=self.dsn, apply=True)
                self.assertFalse(any("CREATE TABLE" in q for q, _ in c.commands))


if __name__ == "__main__":
    unittest.main()
