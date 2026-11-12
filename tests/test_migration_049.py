"""Migration 049 backfill on rows written by older code.

Before 049, a thread mirroring its hidden work carried status_source
'moderator', indistinguishable from a thread a moderator hid; and rows paused
before 047 had no source at all, so a dismissal could never restore them.
"""
from __future__ import annotations
from tests.postgres_support import open_isolated_postgres

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.admin_services import admin_resolve_report
from backend.services import publish_user_work, register_user, submit_abuse_report
from tests.postgres_maintenance import STATUS_ACTOR_BACKFILL_SQL

IMG = "/images/individual/FA/FA-013.webp"


class Migration049BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.author, _ = register_user(self.db, "m49_author", "password-a")
        register_user(self.db, "m49_admin", "password-admin")
        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE username = 'm49_admin'")
        conn.commit()
        self.admin = dict(conn.execute("SELECT * FROM users WHERE username = 'm49_admin'").fetchone())

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _new_work(self, title):
        w = publish_user_work(self.db, self.author, {"title": title, "prompt": "p", "images": [IMG], "styles": ["FA-013"]})
        return w["workId"], w["topicId"]

    def _sql(self, sql, params=()):
        conn = self.db.get_conn()
        conn.execute(sql, params)
        conn.commit()

    def _audit(self, target_type, target_id, action):
        self._sql(
            "INSERT INTO audit_logs (actor_id, actor_username, actor_role, action, target_type, target_id, reason, details_json, created_at) "
            "VALUES (NULL, 'system', 'system', ?, ?, ?, '', '{}', '2026-01-01T00:00:00Z')",
            (action, target_type, target_id),
        )

    def _backfill(self):
        conn = self.db.get_conn()
        conn.execute(STATUS_ACTOR_BACKFILL_SQL)
        conn.commit()

    def _row(self, table, row_id):
        row = self.db.get_conn().execute(
            f"SELECT status, status_source FROM {table} WHERE id = ?", (row_id,)
        ).fetchone()
        return (row["status"], row["status_source"])

    def test_old_mirror_rows_become_work_and_follow_the_work_back(self):
        wid, tid = self._new_work("旧镜像")
        self._sql("UPDATE works SET status='hidden', status_source='moderator', status_reason='管理员隐藏' WHERE id=?", (wid,))
        self._sql("UPDATE forum_topics SET status='hidden', status_source='moderator', status_reason='管理员隐藏' WHERE id=?", (tid,))
        self._backfill()
        self.assertEqual(self._row("forum_topics", tid), ("hidden", "work"))

    def test_a_thread_level_hide_is_not_mistaken_for_a_mirror(self):
        wid, tid = self._new_work("独立隐藏")
        self._sql("UPDATE works SET status='hidden', status_source='moderator', status_reason='管理员隐藏' WHERE id=?", (wid,))
        self._sql("UPDATE forum_topics SET status='hidden', status_source='moderator', status_reason='跑题' WHERE id=?", (tid,))
        self._backfill()
        self.assertEqual(self._row("forum_topics", tid), ("hidden", "moderator"))

    def test_legacy_report_pause_becomes_restorable(self):
        # #21: paused before 047, so no source; the audit log shows only the
        # automatic pause.  After the backfill a dismissal restores it.
        wid, tid = self._new_work("旧暂停")
        self._sql("UPDATE works SET status='paused', status_source='' WHERE id=?", (wid,))
        self._sql("UPDATE forum_topics SET status='paused', status_source='' WHERE id=?", (tid,))
        self._audit("work", wid, "moderation.auto_pause")
        self._backfill()
        self.assertEqual(self._row("works", wid), ("paused", "report"))
        self.assertEqual(self._row("forum_topics", tid), ("paused", "work"))

        reporter, _ = register_user(self.db, "m49_rep", "password-r")
        submit_abuse_report(self.db, reporter, {"targetType": "work", "targetId": wid, "reason": "x"})
        rid = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_id = ? AND status = 'open'", (wid,)
        ).fetchone()["id"]
        self.db.close_thread_conn()
        admin_resolve_report(self.db, self.admin, rid, "dismissed")
        self.assertEqual(self._row("works", wid), ("published", ""))
        self.assertEqual(self._row("forum_topics", tid), ("published", ""))

    def test_a_legacy_pause_with_any_human_action_is_left_alone(self):
        # Old code logged auto_pause even when an admin had already paused the
        # work; any human pause in the log means we cannot tell, so do nothing.
        wid, _ = self._new_work("人工暂停")
        self._sql("UPDATE works SET status='paused', status_source='' WHERE id=?", (wid,))
        self._audit("work", wid, "work.pause")
        self._audit("work", wid, "moderation.auto_pause")
        self._backfill()
        self.assertEqual(self._row("works", wid), ("paused", ""))

    def test_a_paused_row_without_any_auto_pause_is_left_alone(self):
        wid, _ = self._new_work("无记录暂停")
        self._sql("UPDATE works SET status='paused', status_source='' WHERE id=?", (wid,))
        self._backfill()
        self.assertEqual(self._row("works", wid), ("paused", ""))


if __name__ == "__main__":
    unittest.main()
