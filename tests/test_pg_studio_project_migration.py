"""Existing-PostgreSQL Studio2 migration (101-103) safety regression.

No live database required. Every execution path is asserted to be non-
destructive; SQL failures are handled by the driver's surrounding transaction.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

from ops.migrate_pg_studio_projects import (
    ALLOW_ENV, NAME, PROJECT_TABLES_SQL, STEPS, inspect_state, migrate,
    validate_database_name,
)

V102 = "102_studio_graphpatch_reviews"
V103 = "103_author_private_resource_projection"


class FakeCursor:
    """Tracks which additive objects exist, keyed by to_regclass name."""

    def __init__(self, *, base=True, installed=(), partial=None, wrong_name=None,
                 skill=True):
        self.base = base
        # Object names that already exist in the simulated database.
        self.objects = set()
        if base:
            self.objects |= {"schema_migrations", "users", "generation_runs",
                             "media_assets", "skill_personal_resources",
                             "skill_resource_changes"}
        if skill and base:
            self.objects |= {"skill_personal_resources", "skill_resource_changes"}
        # Object names that already exist in the simulated database.
        self.objects |= set(installed)
        # Force a single object to appear without a migration receipt.
        self.partial = partial
        if partial:
            self.objects.add(partial)
        self.wrong_name = wrong_name
        # Simulated migration receipts: version -> name.
        self.receipts = {100: "100_native_v3"}
        self.skill = skill
        self.commands = []
        self.answer = None

    # -- driver surface ---------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=()):
        sql = str(statement).strip()
        self.commands.append((sql, params))
        if "to_regclass" in sql:
            names = [n for n in self._regclass_names(sql)]
            if "public.users" in names and not self.base:
                self.answer = (None,) * len(names)
                return
            if "public.skill_personal_resources" in names and not self.skill:
                self.answer = (None, None)
                return
            self.answer = tuple(
                "exists" if name.split(".")[-1] in self.objects else None
                for name in names
            )
        elif "SELECT version,name" in sql:
            wanted = list(params[0]) if params else [100]
            self.answer = [(v, self.receipts[v]) for v in wanted if v in self.receipts]
        elif sql.startswith("CREATE TABLE public.studio_projects"):
            self._install({"studio_projects", "studio_project_requests",
                           "pg_idx_studio_projects_owner_updated"}, 101, NAME)
        elif sql.startswith("CREATE TABLE public.studio_graphpatch_reviews"):
            self._install({"studio_graphpatch_reviews",
                           "pg_idx_studio_graphpatch_owner"}, 102, V102)
        elif sql.startswith("CREATE TABLE public.user_resources"):
            self._install({"user_resources", "pg_idx_user_resources_owner"}, 103, V103)
        elif sql.startswith("INSERT INTO public.schema_migrations"):
            # The receipt is only authoritative after its DDL ran.
            version, name = params[0], params[1]
            self.receipts.setdefault(version, name)
        else:
            self.answer = [(1,)]

    def _install(self, objects, version, name):
        self.objects |= objects
        self.receipts.pop(version, None)

    @staticmethod
    def _regclass_names(sql):
        import re
        return re.findall(r"to_regclass\('([^']+)'\)", sql)

    # -- result surface ---------------------------------------------------
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


class ExistingPostgresStudioMigrationTests(unittest.TestCase):
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

    def test_all_steps_are_additive_and_ordered(self):
        versions = [step.version for step in STEPS]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(versions, [101, 102, 103])
        for step in STEPS:
            ddl = step.ddl.upper()
            for banned in ["DROP ", "TRUNCATE ", "DELETE ", "UPDATE ", "ALTER ",
                           "CASCADE"]:
                self.assertNotIn(banned, ddl, msg=f"{step.name}: {banned}")

    def test_103_projects_from_skill_authority_and_is_idempotent(self):
        ddl = [s.ddl for s in STEPS if s.version == 103][0]
        self.assertIn("FROM public.skill_personal_resources", ddl)
        self.assertIn("ON CONFLICT (id) DO NOTHING", ddl)
        # Derived code must follow the documented USR-S / USR-L scheme.
        self.assertIn("'USR-S'", ddl)
        self.assertIn("'USR-L'", ddl)

    def test_system_database_never_allowed(self):
        for name in ("postgres", "template0", "template1", ""):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_database_name("postgresql://localhost/" + name)
        validate_database_name(self.dsn)
        validate_database_name(self.dsn + "?sslmode=require")
        for suffix in ("?dbname=postgres", "?host=other-host",
                       "?service=unexpected", "?options=-c%20search_path%3Devil"):
            with self.subTest(suffix=suffix), self.assertRaises(RuntimeError):
                validate_database_name(self.dsn + suffix)

    def test_dry_run_uses_only_selects_and_transaction_settings(self):
        c = FakeCursor()
        conn = FakeConnection(c)
        with fake_driver(conn), \
                patch.dict(os.environ, {ALLOW_ENV: ""}):
            r = migrate(dsn=self.dsn, apply=False)
        self.assertTrue(r["dryRun"])
        self.assertTrue(r["requiresMigration"])
        self.assertEqual(r["pendingVersions"], [101, 102, 103])
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
        self.assertEqual(result["appliedVersions"], [101, 102, 103])
        self.assertFalse(result["requiresMigration"])
        self.assertEqual(
            {v for v, _ in c.receipts.items() if v != 100}, {101, 102, 103})
        self.assertTrue(any("CREATE TABLE public.studio_projects" in q for q, _ in c.commands))
        self.assertTrue(any("CREATE TABLE public.studio_graphpatch_reviews" in q for q, _ in c.commands))
        self.assertTrue(any("CREATE TABLE public.user_resources" in q for q, _ in c.commands))
        c.commands.clear()
        with fake_driver(FakeConnection(c)), \
                patch.dict(os.environ, {ALLOW_ENV: "YES"}):
            already = migrate(dsn=self.dsn, apply=True)
        self.assertTrue(already["alreadyApplied"])
        self.assertFalse(any("CREATE TABLE" in q for q, _ in c.commands))

    def test_partial_upgrade_only_applies_the_remaining_steps(self):
        c = FakeCursor()
        for objects, version, name in (
            ({"studio_projects", "studio_project_requests",
              "pg_idx_studio_projects_owner_updated"}, 101, NAME),
            ({"studio_graphpatch_reviews",
              "pg_idx_studio_graphpatch_owner"}, 102, V102),
        ):
            c.objects |= objects
            c.receipts[version] = name
        with fake_driver(FakeConnection(c)), \
                patch.dict(os.environ, {ALLOW_ENV: "YES"}):
            result = migrate(dsn=self.dsn, apply=True)
        self.assertEqual(result["appliedVersions"], [103])
        self.assertFalse(any("CREATE TABLE public.studio_projects" in q for q, _ in c.commands))

    def test_missing_baseline_and_partial_or_drifted_upgrade_are_refused(self):
        cases = (
            {"base": False},
            {"partial": "studio_projects"},
            {"partial": "user_resources"},
            {"skill": False},
            {"installed": {"studio_projects"}, "receipts": True},
        )
        for options in cases:
            with self.subTest(options=options):
                if options.pop("receipts", False):
                    c = FakeCursor(**options)
                    c.receipts[101] = "WRONG_NAME"
                else:
                    c = FakeCursor(**options)
                with fake_driver(FakeConnection(c)), \
                        patch.dict(os.environ, {ALLOW_ENV: "YES"}):
                    with self.assertRaises(RuntimeError):
                        migrate(dsn=self.dsn, apply=True)
                self.assertFalse(any("CREATE TABLE" in q for q, _ in c.commands))

    def test_inspect_state_reports_each_step(self):
        c = FakeCursor()
        c.objects |= {"studio_projects", "studio_project_requests",
                      "pg_idx_studio_projects_owner_updated"}
        c.receipts[101] = NAME
        state = inspect_state(c)
        self.assertEqual(state["pendingVersions"], [102, 103])
        self.assertEqual([s["state"] for s in state["steps"]],
                         ["applied", "pending", "pending"])


if __name__ == "__main__":
    unittest.main()
