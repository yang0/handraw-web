"""Ranking parity: the SQL expression and the Python helper must agree.

``backend/ranking.py`` is the only place popularity is defined, but the same
formula also has to run in the browser.  This test pins the contract from the
Python side so a change to one implementation cannot silently drift.
"""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.db import Database
from backend.ranking import (
    asset_popular_score,
    normalize_sort,
    sort_works,
    topic_popular_score,
    work_popular_score,
    work_popular_sql,
)


def _row(**kw):
    return kw


class RankingFormulaTests(unittest.TestCase):
    def test_work_formula_weights(self):
        row = _row(likes=1, cheers=2, favorites=3, forks=4)
        # 1 + 2 + 2*3 + 1*4 = 13.  Forks weigh 1, not 3: the counter is farmable
        # through free generation quota.
        self.assertEqual(work_popular_score(row), 13)

    def test_work_formula_handles_missing_and_none(self):
        self.assertEqual(work_popular_score(_row()), 0)
        self.assertEqual(work_popular_score(_row(likes=None, cheers=None)), 0)

    def test_topic_formula_counts_published_replies(self):
        topic = _row(likes=1, favorites=2, replies=[{}, {}])
        # 2 replies + 1 + 2*2 = 7
        self.assertEqual(topic_popular_score(topic), 7)

    def test_topic_formula_uses_reply_count_when_list_absent(self):
        self.assertEqual(topic_popular_score(_row(likes=0, favorites=0, replyCount=3)), 3)

    def test_asset_formula_uses_usage(self):
        self.assertEqual(asset_popular_score(_row(usageCount=5)), 5)
        self.assertEqual(asset_popular_score(_row(usage_count=2)), 2)
        self.assertEqual(asset_popular_score(_row()), 0)

    def test_legacy_sort_values_collapse_to_popular(self):
        for legacy in ("favorites", "cheers", "hot", "recommended", "POPULAR"):
            self.assertEqual(normalize_sort(legacy), "popular", legacy)
        self.assertEqual(normalize_sort("newest"), "newest")
        self.assertEqual(normalize_sort(""), "newest")
        self.assertEqual(normalize_sort(None), "newest")
        self.assertEqual(normalize_sort("active"), "newest", "active is topic-only")
        self.assertEqual(normalize_sort("active", allow_active=True), "active")


class RankingParityTests(unittest.TestCase):
    def test_sql_expression_matches_python_helper(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "rank.db")
            db.migrate()
            conn = db.get_conn()
            try:
                self._insert_fixtures(conn)
                expr = work_popular_sql("w")
                sql_rows = conn.execute(
                    f"SELECT id, {expr} AS score FROM works w ORDER BY score DESC, id ASC"
                ).fetchall()
                py_rows = sort_works(conn.execute("SELECT * FROM works").fetchall(), "popular")

                self.assertEqual(
                    [(r["id"], int(r["score"])) for r in sql_rows],
                    [(r["id"], work_popular_score(r)) for r in py_rows],
                    "SQL and Python popularity must produce identical ordering and scores",
                )
            finally:
                conn.close()
                db.close()

    @staticmethod
    def _insert_fixtures(conn: sqlite3.Connection) -> None:
        fixtures = [
            ("w1", 1, 2, 3, 4),
            ("w2", 0, 0, 0, 0),
            ("w3", 10, 0, 0, 0),
            ("w4", 0, 0, 0, 5),
            ("w5", 2, 2, 0, 1),
        ]
        now = "2026-01-01T00:00:00Z"
        for wid, likes, cheers, favs, forks in fixtures:
            conn.execute(
                """INSERT INTO works (id, author_username, author_name, title, images_json, styles_json,
                   layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes, status,
                   featured, is_new_release, pioneer_rewarded, cheers, likes, favorites, forks,
                   published_at_ms, created_label, created_at, updated_at)
                   VALUES (?, 'u', 'U', ?, '[]', '[]', '', 'C-15', 'T-01', '3:4', 'graphic-text', 'mood', 0,
                           'p', '', 'published', 0, 0, 0, ?, ?, ?, ?, 1000, '', ?, ?)""",
                (wid, wid, cheers, likes, favs, forks, now, now),
            )
        conn.commit()

    def test_newest_ordering_is_recency_then_id(self):
        rows = [
            _row(id="b", published_at_ms=200),
            _row(id="a", published_at_ms=200),
            _row(id="c", published_at_ms=100),
        ]
        self.assertEqual([r["id"] for r in sort_works(rows, "newest")], ["a", "b", "c"])

    def test_popular_ties_break_by_recency(self):
        rows = [
            _row(id="old", published_at_ms=100, likes=5),
            _row(id="new", published_at_ms=200, likes=5),
        ]
        self.assertEqual([r["id"] for r in sort_works(rows, "popular")], ["new", "old"])


if __name__ == "__main__":
    unittest.main()
