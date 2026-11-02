"""Tests for Issue #52: Retirement of stamps ("超实用配方", "审美在线").

Covers:
1. Stamp rejection: Submitting cheer with stampLabel returns 400 (stamp_retired).
2. Counter protection: Old client stamp requests do NOT increment counters or create interaction rows.
3. Historical data preservation: Existing interaction rows with stamp_label remain intact.
4. Popularity independence: Works with identical likes, favorites, and forks have identical
   popularity regardless of historical cheers values.
5. Index and Query Planner: idx_works_popular_v3 is used by ORDER BY.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.db import Database
from backend.ranking import (
    WORK_POPULAR_EXPR,
    sort_works,
    work_popular_score,
    work_popular_sql,
)
from backend.server import HandrawRequestHandler, init_database
from backend.services import (
    ServiceError,
    publish_user_work,
    register_user,
    toggle_user_cheer,
)


class RetireStampsBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_stamps.db"
        self.db = init_database(self.db_path)
        self.user_a, self.token_a = register_user(self.db, "alice_stamp", "Pass1234!")
        self.user_b, self.token_b = register_user(self.db, "bob_stamp", "Pass1234!")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_stamp_requests_rejected_with_stamp_retired_code(self) -> None:
        """1. Submitting any stampLabel is rejected with 400 and code 'stamp_retired'."""
        for label in ("超实用配方", "审美在线", "custom_stamp"):
            with self.assertRaises(ServiceError) as ctx:
                toggle_user_cheer(self.db, self.user_a, "asset", "FA-001", stamp_label=label)
            self.assertEqual(ctx.exception.status, 400)
            self.assertEqual(ctx.exception.code, "stamp_retired")
            self.assertIn("印章功能已下线", ctx.exception.message)

    def test_rejected_stamp_does_not_increment_counters_or_rows(self) -> None:
        """2. Rejected stamp requests do not create interaction rows or change cheers."""
        conn = self.db.get_conn()
        initial_interactions = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        initial_cheers = conn.execute("SELECT cheers FROM catalog_assets WHERE code = 'FA-001'").fetchone()
        c_val = initial_cheers["cheers"] if initial_cheers else 0

        with self.assertRaises(ServiceError):
            toggle_user_cheer(self.db, self.user_a, "asset", "FA-001", stamp_label="超实用配方")

        after_interactions = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        after_cheers = conn.execute("SELECT cheers FROM catalog_assets WHERE code = 'FA-001'").fetchone()
        a_val = after_cheers["cheers"] if after_cheers else 0

        self.assertEqual(initial_interactions, after_interactions, "No interactions row should be added")
        self.assertEqual(c_val, a_val, "Cheers counter must not change on rejected stamp")

    def test_historical_stamp_rows_preserved(self) -> None:
        """3. Historical stamp interaction rows are preserved and never deleted or mutated."""
        conn = self.db.get_conn()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO interactions (user_id, target_type, target_id, stamp_label, created_at)
                VALUES (?, 'asset', 'FA-001', '超实用配方', '2026-01-01T00:00:00Z'),
                       (?, 'asset', 'FA-001', '审美在线', '2026-01-01T00:00:00Z')
                """,
                (self.user_a["id"], self.user_b["id"]),
            )

        stamps_count = conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE stamp_label IN ('超实用配方', '审美在线')"
        ).fetchone()[0]
        self.assertEqual(stamps_count, 2, "Historical stamps must be preserved in database")

    def test_popularity_independent_of_cheers(self) -> None:
        """4. Two works with identical likes/favs/forks have identical score despite different cheers."""
        # Work A: cheers=100, likes=10, favorites=5, forks=2 -> Score: 10 + 2*5 + 2 = 22
        # Work B: cheers=0,   likes=10, favorites=5, forks=2 -> Score: 10 + 2*5 + 2 = 22
        work_a = {"likes": 10, "cheers": 100, "favorites": 5, "forks": 2}
        work_b = {"likes": 10, "cheers": 0, "favorites": 5, "forks": 2}

        self.assertEqual(
            work_popular_score(work_a),
            work_popular_score(work_b),
            "Historical cheers must not affect work popularity score",
        )
        self.assertEqual(work_popular_score(work_a), 22)

        # SQL parity test
        conn = self.db.get_conn()
        now = "2026-11-01T00:00:00Z"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, images_json, styles_json,
                   layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status,
                   featured, is_new_release, pioneer_rewarded, cheers, likes, favorites, forks,
                   published_at_ms, created_label, created_at, updated_at)
                VALUES
                   ('work_cheers_high', 'u1', 'U1', 'High Cheers', '[]', '[]', '', '', '', '3:4', 'free', '', 0, '', '', 'published', 0, 0, 0, 999, 10, 5, 2, 1000, '', ?, ?),
                   ('work_cheers_zero', 'u2', 'U2', 'Zero Cheers', '[]', '[]', '', '', '', '3:4', 'free', '', 0, '', '', 'published', 0, 0, 0, 0, 10, 5, 2, 1000, '', ?, ?)
                """,
                (now, now, now, now),
            )

        sql = f"SELECT id, {WORK_POPULAR_EXPR} AS score FROM works WHERE id IN ('work_cheers_high', 'work_cheers_zero')"
        rows = {r["id"]: r["score"] for r in conn.execute(sql).fetchall()}
        self.assertEqual(rows["work_cheers_high"], 22)
        self.assertEqual(rows["work_cheers_zero"], 22)
        self.assertEqual(rows["work_cheers_high"], rows["work_cheers_zero"])

    def test_expression_index_v3_used_by_order_by(self) -> None:
        """5. Query planner uses idx_works_popular_v3."""
        conn = self.db.get_conn()
        plan = conn.execute(
            f"EXPLAIN QUERY PLAN SELECT id FROM works WHERE status = 'published' ORDER BY {WORK_POPULAR_EXPR} DESC, published_at_ms DESC"
        ).fetchall()
        details = " ".join(str(r["detail"]) for r in plan)
        self.assertIn("idx_works_popular_v3", details)


if __name__ == "__main__":
    unittest.main()
