"""Bounded popular feed snapshots: expiry, eviction, and concurrent access."""
from __future__ import annotations

import threading
import time
import unittest

from backend import works_feed


class PopularFeedSessionCacheTests(unittest.TestCase):
    def setUp(self):
        with works_feed._FEED_SESSION_LOCK:
            works_feed._FEED_POPULAR_SESSIONS.clear()
        self.addCleanup(self._clear)

    def _clear(self):
        with works_feed._FEED_SESSION_LOCK:
            works_feed._FEED_POPULAR_SESSIONS.clear()

    def test_capacity_evicts_oldest_snapshot(self):
        now = time.time()
        cap = works_feed._MAX_POPULAR_SESSIONS
        for n in range(cap + 5):
            works_feed._store_popular_session(str(n), ([str(n)], now, None, ()))
        self.assertEqual(len(works_feed._FEED_POPULAR_SESSIONS), cap)
        self.assertIsNone(works_feed._get_popular_session("0"))
        self.assertIsNotNone(works_feed._get_popular_session(str(cap + 4)))

    def test_replacing_session_refreshes_eviction_order(self):
        now = time.time()
        works_feed._store_popular_session("a", (["old"], now, None, ()))
        works_feed._store_popular_session("b", (["b"], now, None, ()))
        works_feed._store_popular_session("a", (["new"], now, None, ()))
        for n in range(works_feed._MAX_POPULAR_SESSIONS - 1):
            works_feed._store_popular_session(str(n), ([str(n)], now, None, ()))
        self.assertIsNone(works_feed._get_popular_session("b"))
        self.assertEqual(works_feed._get_popular_session("a")[0], ["new"])

    def test_expired_snapshot_is_removed_on_read(self):
        now = time.time()
        expired = now - works_feed._SESSION_TTL_SECONDS - 1
        works_feed._store_popular_session("stale", (["w"], expired, None, ()))
        self.assertIsNone(works_feed._get_popular_session("stale"))
        self.assertNotIn("stale", works_feed._FEED_POPULAR_SESSIONS)

    def test_threaded_reads_and_writes_keep_cache_bounded(self):
        errors = []
        barrier = threading.Barrier(5)
        def worker(i):
            try:
                barrier.wait()
                for n in range(160):
                    key = f"{i}:{n}"
                    works_feed._store_popular_session(key, ([key], time.time(), None, ()))
                    works_feed._get_popular_session(key)
                    works_feed._clean_expired_sessions()
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertLessEqual(len(works_feed._FEED_POPULAR_SESSIONS), works_feed._MAX_POPULAR_SESSIONS)


if __name__ == "__main__":
    unittest.main()
