"""Concurrent social mutations against the native PostgreSQL schema."""
from __future__ import annotations

import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import patch

from backend.services import (
    register_user,
    send_encourage_tip,
    toggle_user_cheer,
    toggle_user_collection,
    toggle_user_like,
)
from tests.postgres_support import isolated_pg_dsn


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class PostgresSocialCounterTests(unittest.TestCase):
    def setUp(self):
        from backend.postgres_db import PostgresDatabase

        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.db = PostgresDatabase(self.enterContext(isolated_pg_dsn()))
        self.addCleanup(self.db.close)
        self.author, self.reader, self.second_reader = (
            register_user(self.db, name, "IsolatedSocialPassword!")[0]
            for name in ("social_author", "social_reader", "social_second")
        )
        from backend.services import apply_wallet_delta
        with self.db.transaction() as tx:
            for participant in (self.author,self.reader,self.second_reader):
                apply_wallet_delta(tx,participant["id"],20,"admin_adjust","Fixture endowment for social concurrency")
        self.db.get_conn().execute("""
            INSERT INTO works(id,author_username,author_name,title,prompt,published_at_ms,created_at,updated_at)
            VALUES ('social-work', ?, 'Author', 'Work', '', 1, '', '')
        """, (self.author["username"],))

    def in_parallel(self, operation, accounts):
        db = self.db
        barrier = Barrier(len(accounts))

        class DelayedConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def execute(self, statement, parameters=()):
                cursor = self.connection.execute(statement, parameters)
                if statement.startswith(("SELECT 1 FROM collections WHERE", "SELECT 1 FROM interactions WHERE")):
                    # Widen the interval between observing the fact and writing it.
                    time.sleep(0.08)
                return cursor

        class ConcurrentDatabase:
            def get_conn(self):
                return db.get_conn()

            @contextmanager
            def transaction(self):
                with db.transaction() as connection:
                    barrier.wait(timeout=5)
                    yield DelayedConnection(connection)

        def invoke(account):
            try:
                return operation(ConcurrentDatabase(), account)
            finally:
                db.release_request_connection()

        with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
            return list(executor.map(invoke, accounts))

    def count(self, column):
        return int(self.db.get_conn().execute(
            f"SELECT {column} FROM works WHERE id='social-work'"
        ).fetchone()[0])

    def interactions(self, kind):
        return int(self.db.get_conn().execute(
            "SELECT count(*) FROM interactions WHERE target_id='social-work' AND target_type=?", (kind,),
        ).fetchone()[0])

    def test_duplicate_like_set_and_unset_and_double_toggle(self):
        def like(action):
            return self.in_parallel(
                lambda db, user: toggle_user_like(db, user, "work", "social-work", action),
                (self.reader, self.reader),
            )

        created = like("set")
        self.assertTrue(all(result["liked"] for result in created))
        self.assertEqual(sorted(result["rewarded"] for result in created), [0, 0])
        self.assertEqual((self.count("likes"), self.interactions("like_work")), (1, 1))
        removed = like("unset")
        self.assertTrue(all(not result["liked"] for result in removed))
        self.assertEqual((self.count("likes"), self.interactions("like_work")), (0, 0))
        toggled = like(None)
        self.assertEqual(sorted(result["liked"] for result in toggled), [False, True])
        self.assertEqual((self.count("likes"), self.interactions("like_work")), (0, 0))
        self.assertEqual(self.db.get_conn().execute(
            "SELECT count(*) FROM ledgers WHERE kind='first_cheer' AND user_id=?",
            (self.reader["id"],),
        ).fetchone()[0], 0)

    def test_duplicate_collection_set_and_unset(self):
        for action, expected in (("set", 1), ("unset", 0)):
            result = self.in_parallel(
                lambda db, user: toggle_user_collection(db, user, "works", "social-work", action=action),
                (self.reader, self.reader),
            )
            self.assertTrue(all(item["collected"] == bool(expected) for item in result))
            self.assertEqual(self.count("favorites"), expected)
            self.assertEqual(self.db.get_conn().execute(
                "SELECT count(*) FROM collections WHERE bucket='works' AND target_id='social-work'",
            ).fetchone()[0], expected)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT count(*) FROM ledgers WHERE kind='first_collect' AND user_id=?",
            (self.reader["id"],),
        ).fetchone()[0], 0)

    def test_distinct_users_cheer_and_remove_without_lost_updates(self):
        for expected in (2, 0):
            self.in_parallel(
                lambda db, user: toggle_user_cheer(db, user, "work", "social-work"),
                (self.reader, self.second_reader),
            )
            self.assertEqual((self.count("cheers"), self.interactions("work")), (expected, expected))

    def test_concurrent_tip_retry_keeps_one_attached_like_and_one_heat_increment(self):
        results = self.in_parallel(
            lambda db, user: send_encourage_tip(db, user, "work", "social-work", 2, "pg-social-tip"),
            (self.reader, self.reader),
        )
        self.assertEqual(sum(bool(result.get("duplicate")) for result in results), 1)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT count(*) FROM tip_requests WHERE request_id='pg-social-tip'"
        ).fetchone()[0], 1)
        self.assertEqual((self.count("likes"), self.interactions("like_work")), (1, 1))
        self.assertEqual(self.count("cheers"), 3)

    def test_like_and_tip_from_same_user_keep_one_like(self):
        operations = (
            lambda db: toggle_user_like(db, self.reader, "work", "social-work", "set"),
            lambda db: send_encourage_tip(db, self.reader, "work", "social-work", 2, "pg-like-and-tip"),
        )
        self.in_parallel(lambda db, run: run(db), operations)
        self.assertEqual((self.count("likes"), self.interactions("like_work")), (1, 1))
        self.assertEqual(self.count("cheers"), 3)
