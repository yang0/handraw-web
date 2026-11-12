"""One account cannot pause content on its own (review item #12).

The auto-pause threshold used to count report rows, so a single account that
reported something three times paused it.  Now each account has at most one
open report per target and the threshold counts distinct reporters.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.legacy_database import init_legacy_database
from backend import server
from backend.services import publish_user_work, register_user, submit_abuse_report

IMG = "/images/individual/FA/FA-013.webp"


class ReportLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = init_legacy_database(Path(self.temp.name) / "limits.db")
        self.author, _ = register_user(self.db, "rl_author", "password-a")
        self.work = publish_user_work(
            self.db, self.author, {"title": "举报上限", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _report(self, user, target_type="work"):
        target = self.work["workId"] if target_type == "work" else self.work["topicId"]
        return submit_abuse_report(self.db, user, {"targetType": target_type, "targetId": target, "reason": "spam"})

    def _status(self):
        conn = self.db.get_conn()
        w = conn.execute("SELECT status FROM works WHERE id = ?", (self.work["workId"],)).fetchone()["status"]
        t = conn.execute("SELECT status FROM forum_topics WHERE id = ?", (self.work["topicId"],)).fetchone()["status"]
        self.db.close_thread_conn()
        return (w, t)

    def _open_rows(self, target_id):
        n = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM reports WHERE target_id = ? AND status = 'open'", (target_id,)
        ).fetchone()[0]
        self.db.close_thread_conn()
        return n

    def test_one_account_cannot_pause_a_work(self):
        reporter, _ = register_user(self.db, "rl_solo", "password-r")
        results = [self._report(reporter) for _ in range(5)]
        self.assertEqual([r["autoPaused"] for r in results], [False] * 5)
        self.assertEqual([r["openReports"] for r in results], [1] * 5)
        self.assertEqual(self._status(), ("published", "published"))
        self.assertEqual(self._open_rows(self.work["workId"]), 1, "repeat reports are not stored")

    def test_one_account_cannot_pause_a_thread(self):
        reporter, _ = register_user(self.db, "rl_solo_t", "password-r")
        for _ in range(4):
            self._report(reporter, "topic")
        self.assertEqual(self._status(), ("published", "published"))

    def test_three_accounts_still_pause_a_work(self):
        flags = []
        for i in range(3):
            reporter, _ = register_user(self.db, f"rl_rep{i}", "password-r")
            flags.append(self._report(reporter)["autoPaused"])
        self.assertEqual(flags, [False, False, True])
        self.assertEqual(self._status(), ("paused", "paused"))

    def test_legacy_duplicate_rows_do_not_reach_the_threshold(self):
        # Rows written before the limit existed: three open reports from one
        # account.  A fourth report from a second account makes two people.
        reporter, _ = register_user(self.db, "rl_legacy", "password-r")
        conn = self.db.get_conn()
        for _ in range(3):
            conn.execute(
                "INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at) "
                "VALUES (?, 'rl_legacy', 'work', ?, 't', 'spam', '', 'open', '2026-01-01T00:00:00Z')",
                (reporter["id"], self.work["workId"]),
            )
        conn.commit()
        self.db.close_thread_conn()
        other, _ = register_user(self.db, "rl_other", "password-r")
        result = self._report(other)
        self.assertEqual(result["openReports"], 2)
        self.assertFalse(result["autoPaused"])
        self.assertEqual(self._status(), ("published", "published"))


if __name__ == "__main__":
    unittest.main()
