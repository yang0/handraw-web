"""PostgreSQL identity introspection should be shared by pooled connections."""
from __future__ import annotations

import threading
import unittest

from backend.postgres_db import PgConnection


class FakeCursor:
    def __init__(self, owner):
        self.owner = owner
        self.description = None
        self.rowcount = 1
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def execute(self, query, params=()):
        self.owner.executed.append((query, params))
        if "information_schema.columns" in query:
            table = params[0]
            self._rows = [(self.owner.identity_map[table],)] if self.owner.identity_map.get(table) else []
        elif "RETURNING" in query.upper():
            self._rows = [(123,)]
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, identity_map=None):
        self.identity_map = identity_map or {}
        self.executed = []

    def cursor(self):
        return FakeCursor(self)


class PgIdentityMetadataTests(unittest.TestCase):
    def test_two_connections_reuse_identity_introspection(self):
        cache = {}
        lock = threading.RLock()
        raw1 = FakeConnection({"users": "id"})
        raw2 = FakeConnection({"users": "id"})
        first = PgConnection(raw1, identity_cache=cache, identity_lock=lock)
        second = PgConnection(raw2, identity_cache=cache, identity_lock=lock)
        self.assertEqual(first.execute("INSERT INTO users(name) VALUES (?)", ("a",)).lastrowid, 123)
        self.assertEqual(second.execute("INSERT INTO users(name) VALUES (?)", ("b",)).lastrowid, 123)
        probes = [q for raw in (raw1, raw2) for q, _ in raw.executed if "information_schema.columns" in q]
        self.assertEqual(len(probes), 1)
        self.assertEqual(cache["users"], "id")

    def test_non_identity_tables_are_cached_too(self):
        cache = {}
        lock = threading.RLock()
        raw1, raw2 = FakeConnection(), FakeConnection()
        PgConnection(raw1, identity_cache=cache, identity_lock=lock).execute(
            "INSERT INTO audit(event) VALUES (?)", ("a",)
        )
        PgConnection(raw2, identity_cache=cache, identity_lock=lock).execute(
            "INSERT INTO audit(event) VALUES (?)", ("b",)
        )
        self.assertIn("audit", cache)
        self.assertIsNone(cache["audit"])
        self.assertEqual(sum("information_schema.columns" in q
                             for raw in (raw1, raw2) for q, _ in raw.executed), 1)

    def test_explicit_returning_remains_untouched(self):
        raw = FakeConnection({"users": "id"})
        result = PgConnection(raw).execute("INSERT INTO users(name) VALUES (?) RETURNING id", ("a",))
        self.assertIsNone(result.lastrowid)
        inserts = [q for q, _ in raw.executed if q.startswith("INSERT")]
        self.assertEqual(inserts, ["INSERT INTO users(name) VALUES (%s) RETURNING id"])

    def test_separate_default_connections_do_not_share_cache(self):
        raw1, raw2 = FakeConnection({"users": "id"}), FakeConnection({"users": "id"})
        PgConnection(raw1).execute("INSERT INTO users(name) VALUES (?)", ("a",))
        PgConnection(raw2).execute("INSERT INTO users(name) VALUES (?)", ("b",))
        self.assertEqual(sum("information_schema.columns" in q
                             for raw in (raw1, raw2) for q, _ in raw.executed), 2)

    def test_concurrent_first_insert_probes_once(self):
        shared, lock = {}, threading.RLock()
        raws = [FakeConnection({"users": "id"}) for _ in range(8)]
        errors = []
        barrier = threading.Barrier(len(raws))
        def write(raw):
            try:
                barrier.wait()
                result = PgConnection(raw, identity_cache=shared, identity_lock=lock).execute(
                    "INSERT INTO users(name) VALUES (?)", ("x",))
                self.assertEqual(result.lastrowid, 123)
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=write, args=(raw,)) for raw in raws]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum("information_schema.columns" in q
                             for raw in raws for q, _ in raw.executed), 1)


if __name__ == "__main__":
    unittest.main()
