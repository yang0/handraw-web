"""Bounded popular feed snapshots: expiry, eviction, and concurrent access."""
from __future__ import annotations

import threading
import os
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from backend import feed_sessions
from backend.feed_sessions import PopularSession, PopularSessions


class PopularFeedSessionCacheTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_REDIS_URL": ""}))
        self._clear()
        self.addCleanup(self._clear)
        self.sessions = PopularSessions(self, SimpleNamespace(cache_scope="test"))

    def _clear(self):
        with feed_sessions._LOCAL_LOCK:
            feed_sessions._LOCAL_SESSIONS.clear()

    def test_capacity_evicts_oldest_snapshot(self):
        cap = feed_sessions._MAX_SESSIONS
        for n in range(cap + 5):
            self.sessions.put(str(n), PopularSession("filter", (str(n),)))
        self.assertEqual(len(feed_sessions._LOCAL_SESSIONS), cap)
        self.assertIsNone(self.sessions.get("0"))
        self.assertIsNotNone(self.sessions.get(str(cap + 4)))

    def test_replacing_session_refreshes_eviction_order(self):
        self.sessions.put("a", PopularSession("filter", ("old",)))
        self.sessions.put("b", PopularSession("filter", ("b",)))
        self.sessions.put("a", PopularSession("filter", ("new",)))
        for n in range(feed_sessions._MAX_SESSIONS - 1):
            self.sessions.put(str(n), PopularSession("filter", (str(n),)))
        self.assertIsNone(self.sessions.get("b"))
        self.assertEqual(self.sessions.get("a").ordered_ids, ("new",))

    def test_expired_snapshot_is_removed_on_read(self):
        self.sessions.put("stale", PopularSession("filter", ("w",)))
        with feed_sessions._LOCAL_LOCK:
            for key, (_, session) in feed_sessions._LOCAL_SESSIONS.items():
                feed_sessions._LOCAL_SESSIONS[key] = (0, session)
        self.assertIsNone(self.sessions.get("stale"))
        self.assertEqual(feed_sessions._LOCAL_SESSIONS, {})

    def test_threaded_reads_and_writes_keep_cache_bounded(self):
        errors = []
        barrier = threading.Barrier(5)
        def worker(i):
            try:
                barrier.wait()
                for n in range(160):
                    key = f"{i}:{n}"
                    self.sessions.put(key, PopularSession("filter", (key,)))
                    self.sessions.get(key)
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertLessEqual(len(feed_sessions._LOCAL_SESSIONS), feed_sessions._MAX_SESSIONS)


if __name__ == "__main__":
    unittest.main()
