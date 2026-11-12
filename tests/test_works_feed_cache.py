"""Frozen popular pagination across independent workers and cache failures."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from backend import feed_sessions
from backend.feed_sessions import PopularSession, PopularSessions
from backend.postgres_db import PostgresDatabase
from backend.redis_cache import redis_cache_client
from backend.works_feed import get_works_feed
from tests.postgres_support import isolated_pg_dsn, open_isolated_postgres


@unittest.skipUnless(
    os.environ.get("HANDRAW_PG_STAGING_URL") and os.environ.get("HANDRAW_REDIS_URL"),
    "Isolated PostgreSQL and Redis URLs not provided",
)
class PopularFeedCacheTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "handraw:feed-test:" + uuid.uuid4().hex
        self.enterContext(patch.dict(os.environ, {
            "HANDRAW_REDIS_PREFIX": self.prefix, "HANDRAW_DEMO_MODE": "0",
        }))
        self.db = open_isolated_postgres(self)
        self.conn = self.db.get_conn()
        self.redis = redis_cache_client(os.environ["HANDRAW_REDIS_URL"])
        self.sessions = PopularSessions(self.db, self.conn)
        self.addCleanup(self.clear_cache)
        self.conn.execute("""
            INSERT INTO works (id, author_username, author_name, title, images_json, prompt,
                               likes, published_at_ms, created_at, updated_at)
            SELECT 'cache-work-' || n, 'writer', 'Writer', 'Test',
                   '["/images/example.webp"]', '', n, n, '', ''
            FROM generate_series(1, 8) AS n
        """)
        self.options = {"sort": "popular", "limit": 2}

    def clear_cache(self):
        keys = list(self.redis.scan_iter(match=self.prefix + ":*"))
        if keys:
            self.redis.delete(*keys)
        with feed_sessions._LOCAL_LOCK:
            feed_sessions._LOCAL_SESSIONS.clear()

    def child_page(self, cursor, **filters):
        source = """
import json, os, sys
from contextlib import closing
from backend.postgres_db import PostgresDatabase
from backend.works_feed import get_works_feed
with closing(PostgresDatabase(os.environ['HANDRAW_DATABASE_URL'])) as db:
    print(json.dumps(get_works_feed(db, json.loads(sys.argv[1]))))
"""
        process = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", source,
             json.dumps({**self.options, "cursor": cursor, **filters})],
            env={**os.environ, "HANDRAW_DATABASE_URL": self.db._dsn},
            capture_output=True, encoding="utf-8", timeout=15, check=True,
        )
        return json.loads(process.stdout)

    def test_workers_share_frozen_order_and_hide_changed_works(self):
        first = get_works_feed(self.db, self.options)
        first_ids = [item["id"] for item in first["items"]]
        self.assertEqual(first_ids, ["cache-work-8", "cache-work-7"])
        self.conn.execute("UPDATE works SET likes = 100000 WHERE id = 'cache-work-1'")
        second = self.child_page(first["nextCursor"])
        second_ids = [item["id"] for item in second["items"]]
        self.assertEqual(second_ids, ["cache-work-6", "cache-work-5"])
        self.conn.execute("UPDATE works SET status = 'hidden' WHERE id = 'cache-work-4'")
        self.conn.execute("DELETE FROM works WHERE id = 'cache-work-3'")
        third = self.child_page(second["nextCursor"])
        self.assertEqual(third["items"], [])
        last = self.child_page(third["nextCursor"])
        self.assertEqual([item["id"] for item in last["items"]], ["cache-work-2", "cache-work-1"])
        self.assertFalse(last["hasMore"])
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

    def test_database_actor_filters_and_demo_mode_are_isolated(self):
        first = get_works_feed(self.db, self.options)
        cursor = first["nextCursor"]
        self.assertTrue(self.child_page(cursor, author="writer")["sessionExpired"])
        other_db = PostgresDatabase(self.enterContext(isolated_pg_dsn()))
        self.addCleanup(other_db.close)
        self.assertTrue(get_works_feed(other_db, {**self.options, "cursor": cursor})["sessionExpired"])
        actor = {"id": 99999, "role": "user", "username": "viewer"}
        self.assertTrue(get_works_feed(
            self.db, {**self.options, "cursor": cursor}, current_user=actor,
        )["sessionExpired"])
        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "1"}):
            self.assertTrue(get_works_feed(self.db, {**self.options, "cursor": cursor})["sessionExpired"])
        self.assertEqual(self.child_page(cursor)["sessionId"], first["sessionId"])

    def test_cache_expiry_corruption_and_capacity(self):
        first = get_works_feed(self.db, self.options)
        payloads, expires = self.sessions.redis_keys
        session_id = first["sessionId"]
        self.redis.zadd(expires, {session_id: 0})
        self.assertTrue(self.child_page(first["nextCursor"])["sessionExpired"])
        replacement = get_works_feed(self.db, self.options)
        self.redis.hset(payloads, replacement["sessionId"], "invalid-json")
        self.assertTrue(self.child_page(replacement["nextCursor"])["sessionExpired"])
        for number in range(feed_sessions._MAX_SESSIONS + 5):
            self.sessions.put(str(number), PopularSession("filter", ("work",)))
        self.assertEqual(self.redis.hlen(payloads), feed_sessions._MAX_SESSIONS)
        self.assertEqual(self.redis.zcard(expires), feed_sessions._MAX_SESSIONS)
        self.assertIsNone(self.sessions.get("0"))
        self.assertLessEqual(self.redis.ttl(payloads), feed_sessions._TTL_SECONDS)
        self.assertGreater(self.redis.ttl(payloads), 0)

    def test_redis_outage_keeps_local_session_and_visibility_checks(self):
        with patch.object(self.redis, "eval", side_effect=ConnectionError("isolated cache outage")):
            first = get_works_feed(self.db, self.options)
            self.conn.execute("UPDATE works SET status = 'hidden' WHERE id = 'cache-work-6'")
            second = get_works_feed(self.db, {**self.options, "cursor": first["nextCursor"]})
            self.assertEqual([item["id"] for item in second["items"]], ["cache-work-5"])
        self.assertTrue(self.child_page(first["nextCursor"])["sessionExpired"])
        self.assertLessEqual(len(feed_sessions._LOCAL_SESSIONS), feed_sessions._MAX_SESSIONS)
