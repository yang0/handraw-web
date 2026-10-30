"""Status provenance: moderation decisions survive the abuse-report flow.

A bare status column cannot tell "an admin hid this" apart from "the report
threshold paused it", so dismissing a report used to republish moderated work.
These cases pin the ``status_source`` rule that fixes it.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.admin_services import admin_moderate_work, admin_resolve_report
from backend.services import publish_user_work, register_user, set_work_visibility, submit_abuse_report

IMG = "/images/individual/FA/FA-013.webp"


class StatusProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "prov.db")
        self.author, _ = register_user(self.db, "prov_author", "password-a")
        register_user(self.db, "prov_admin", "password-admin")
        self.db.get_conn().execute("UPDATE users SET role = 'admin' WHERE username = 'prov_admin'")
        self.db.get_conn().commit()
        self.admin = dict(
            self.db.get_conn().execute("SELECT * FROM users WHERE username = 'prov_admin'").fetchone()
        )
        self.work = publish_user_work(
            self.db, self.author, {"title": "来源作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _state(self):
        row = self.db.get_conn().execute(
            "SELECT status, status_source FROM works WHERE id = ?", (self.work["workId"],)
        ).fetchone()
        self.db.close_thread_conn()
        return (row["status"], row["status_source"]) if row else (None, None)

    def _dismiss_all_open_reports(self):
        reports = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND target_id = ? AND status = 'open'",
            (self.work["workId"],),
        ).fetchall()
        self.db.close_thread_conn()
        for report in reports:
            admin_resolve_report(self.db, self.admin, report["id"], "dismissed", auto_action=False)

    def _report(self, times=1):
        for _ in range(times):
            submit_abuse_report(
                self.db,
                self.author,
                {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"},
            )

    def test_moderator_pause_records_its_source(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "pause")
        self.assertEqual(self._state(), ("paused", "moderator"))

    def test_dismissing_reports_cannot_undo_a_moderator_pause(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "pause")
        self._report()
        self._dismiss_all_open_reports()
        self.assertEqual(self._state(), ("paused", "moderator"), "a human pause outranks the report flow")

    def test_dismissing_reports_cannot_unhide_an_admin_hidden_work(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        self._report(times=3)
        self._dismiss_all_open_reports()
        self.assertEqual(self._state(), ("hidden", "moderator"))

    def test_reports_cannot_downgrade_a_hidden_work(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        self._report(times=3)
        self.assertEqual(self._state(), ("hidden", "moderator"), "auto-pause must not touch a hidden work")

    def test_feature_requires_a_published_work(self):
        from backend.services import ServiceError

        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        with self.assertRaises(ServiceError) as ctx:
            admin_moderate_work(self.db, self.admin, self.work["workId"], "feature")
        self.assertEqual(ctx.exception.code, "feature_requires_published")
        self.assertEqual(self._state(), ("hidden", "moderator"))

    def test_boost_new_requires_a_published_work(self):
        from backend.services import ServiceError

        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        with self.assertRaises(ServiceError) as ctx:
            admin_moderate_work(self.db, self.admin, self.work["workId"], "boost_new")
        self.assertEqual(ctx.exception.code, "boost_requires_published")
        self.assertEqual(self._state(), ("hidden", "moderator"))

    def test_feature_still_works_on_a_published_work(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "feature")
        row = self.db.get_conn().execute(
            "SELECT featured, status FROM works WHERE id = ?", (self.work["workId"],)
        ).fetchone()
        self.db.close_thread_conn()
        self.assertEqual(int(row["featured"]), 1)
        self.assertEqual(row["status"], "published")

    def test_report_paused_work_restores_and_clears_its_source(self):
        with self.db.transaction() as tx:
            set_work_visibility(
                tx, self.work["workId"], "paused", "2026-01-01T00:00:00Z",
                source="report", reason="举报达到阈值", allow_from=("published",),
            )
        self.assertEqual(self._state(), ("paused", "report"))
        self._report()
        self._dismiss_all_open_reports()
        self.assertEqual(self._state(), ("published", ""), "restoring clears the provenance")

    def test_confirmed_report_is_recorded_as_a_moderator_verdict(self):
        # Confirming a report is a human decision: the record must say
        # 'moderator', otherwise a later dismissal republishes the content.
        self._report()
        reports = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND target_id = ? AND status = 'open'",
            (self.work["workId"],),
        ).fetchall()
        self.db.close_thread_conn()
        self.assertTrue(reports)
        admin_resolve_report(self.db, self.admin, reports[0]["id"], "confirmed", auto_action=True)
        self.assertEqual(self._state(), ("hidden", "moderator"))

    def test_moderator_verdict_survives_a_later_dismissal(self):
        self._report()
        reports = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND target_id = ? AND status = 'open'",
            (self.work["workId"],),
        ).fetchall()
        self.db.close_thread_conn()
        admin_resolve_report(self.db, self.admin, reports[0]["id"], "confirmed", auto_action=True)
        self._report()  # someone reports again
        self._dismiss_all_open_reports()
        self.assertEqual(
            self._state(), ("hidden", "moderator"),
            "a dismissed report must not undo a confirmed violation",
        )

    def test_topic_source_guard_blocks_report_flow_from_touching_a_moderator_state(self):
        # M-c: automation must not overwrite a moderator decision on the topic.
        # The guard is silent (a no-op), so assert on the stored state.
        from backend.services import set_topic_visibility

        from backend.admin_services import admin_moderate_topic

        admin_moderate_topic(self.db, self.admin, self.work["topicId"], "hide")
        with self.db.transaction() as tx:
            set_topic_visibility(
                tx, self.work["topicId"], "published", "2026-01-01T00:00:00Z", source="report"
            )
        topic = self.db.get_conn().execute(
            "SELECT status, status_source FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        self.assertEqual(
            (topic["status"], topic["status_source"]), ("hidden", "moderator"),
            "an automated flow must not republish a moderator-hidden thread",
        )

    def test_moderator_can_still_republish_its_own_decision(self):
        from backend.services import set_topic_visibility

        from backend.admin_services import admin_moderate_topic

        admin_moderate_topic(self.db, self.admin, self.work["topicId"], "hide")
        with self.db.transaction() as tx:
            set_topic_visibility(
                tx, self.work["topicId"], "published", "2026-01-01T00:00:00Z", source="moderator"
            )
        topic = self.db.get_conn().execute(
            "SELECT status FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        self.assertEqual(topic["status"], "published", "a moderator may reverse their own hide")

    def test_dismissal_passes_the_report_source(self):
        # M-g: the dismissal must identify itself as the report flow, so the
        # topic-level moderator guard applies.
        from backend.admin_services import admin_moderate_topic

        admin_moderate_topic(self.db, self.admin, self.work["topicId"], "hide")
        self._report()
        self._dismiss_all_open_reports()
        topic = self.db.get_conn().execute(
            "SELECT status, status_source FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        self.assertEqual((topic["status"], topic["status_source"]), ("hidden", "moderator"))


if __name__ == "__main__":
    unittest.main()
