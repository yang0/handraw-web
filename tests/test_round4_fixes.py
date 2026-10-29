"""Round-4 review fixes: the governance regression and the remaining leaks."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.admin_services import admin_moderate_work, admin_resolve_report
from backend.services import (
    build_boot_payload,
    prepare_cloud_generation,
    publish_user_work,
    register_user,
    set_work_visibility,
    submit_abuse_report,
)

IMG = "/images/individual/FA/FA-013.webp"


class _Base(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "db.sqlite"
        self.db = server.init_database(self.path)
        self.author, _ = register_user(self.db, "g_author", "password-a")
        register_user(self.db, "g_admin", "password-admin")
        self.db.get_conn().execute("UPDATE users SET role = 'admin' WHERE username = 'g_admin'")
        self.db.get_conn().commit()
        self.admin = dict(
            self.db.get_conn().execute("SELECT * FROM users WHERE username = 'g_admin'").fetchone()
        )
        self.work = publish_user_work(
            self.db, self.author, {"title": "治理作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _statuses(self):
        work = self.db.get_conn().execute(
            "SELECT status FROM works WHERE id = ?", (self.work["workId"],)
        ).fetchone()
        topic = self.db.get_conn().execute(
            "SELECT status FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        return (work["status"] if work else None), (topic["status"] if topic else None)


class GovernanceRegressionTests(_Base):
    def test_reports_cannot_downgrade_a_hidden_work(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        self.assertEqual(self._statuses(), ("hidden", "hidden"))

        for _ in range(3):
            submit_abuse_report(
                self.db, self.author, {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"}
            )
        self.assertEqual(
            self._statuses(), ("hidden", "hidden"), "auto-pause must not touch an admin-hidden work"
        )

    def test_dismissing_reports_does_not_resurrect_a_hidden_work(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        submit_abuse_report(
            self.db, self.author, {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"}
        )
        report = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND target_id = ? AND status = 'open' LIMIT 1",
            (self.work["workId"],),
        ).fetchone()
        admin_resolve_report(self.db, self.admin, report["id"], "dismissed", auto_action=False)
        self.assertEqual(self._statuses(), ("hidden", "hidden"), "a dismissed report must not republish")

    def test_rejection_restores_a_report_paused_work(self):
        # A pause caused by the report flow is undone when the reports are
        # dismissed.  The pause must carry source='report' for that to happen.
        with self.db.transaction() as tx:
            set_work_visibility(
                tx, self.work["workId"], "paused", "2026-01-01T00:00:00Z",
                source="report", reason="举报达到阈值", allow_from=("published",),
            )
        self.assertEqual(self._statuses(), ("paused", "paused"))
        submit_abuse_report(
            self.db, self.author, {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"}
        )
        report = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND target_id = ? AND status = 'open' LIMIT 1",
            (self.work["workId"],),
        ).fetchone()
        admin_resolve_report(self.db, self.admin, report["id"], "dismissed", auto_action=False)
        self.assertEqual(self._statuses(), ("published", "published"))

    def test_rejection_does_not_restore_a_moderator_paused_work(self):
        # A human pause outranks the report flow: dismissing reports must leave
        # the moderator's decision intact.
        with self.db.transaction() as tx:
            set_work_visibility(
                tx, self.work["workId"], "paused", "2026-01-01T00:00:00Z",
                source="moderator", reason="管理员暂停", allow_from=("published",),
            )
        submit_abuse_report(
            self.db, self.author, {"targetType": "work", "targetId": self.work["workId"], "reason": "垃圾内容"}
        )
        report = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = 'work' AND target_id = ? AND status = 'open' LIMIT 1",
            (self.work["workId"],),
        ).fetchone()
        admin_resolve_report(self.db, self.admin, report["id"], "dismissed", auto_action=False)
        self.assertEqual(
            self._statuses(), ("paused", "paused"), "a dismissed report must not undo a moderator pause"
        )


class DeleteSyncTests(_Base):
    def test_deleting_a_work_hides_its_thread(self):
        admin_moderate_work(self.db, self.admin, self.work["workId"], "delete")
        work, topic = self._statuses()
        self.assertIsNone(work)
        self.assertEqual(topic, "hidden", "a deleted work must not leave a readable thread")
        mapping = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM curation_resource_topics WHERE target_id = ?", (self.work["workId"],)
        ).fetchone()[0]
        self.assertEqual(mapping, 0)


class ForkTargetValidationTests(_Base):
    def test_unknown_fork_target_is_rejected(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            prepare_cloud_generation(
                self.db, self.author, {"prompt": "x", "forkOf": "does-not-exist", "requestId": "r-1"}
            )
        self.assertEqual(ctx.exception.code, "fork_target_invalid")

    def test_hidden_fork_target_is_rejected(self):
        from backend.services import ServiceError

        admin_moderate_work(self.db, self.admin, self.work["workId"], "hide")
        other, _ = register_user(self.db, "g_other", "password-o")
        with self.assertRaises(ServiceError) as ctx:
            prepare_cloud_generation(
                self.db, other, {"prompt": "x", "forkOf": self.work["workId"], "requestId": "r-2"}
            )
        self.assertEqual(ctx.exception.code, "fork_target_invalid")

    def test_self_fork_drops_lineage_without_failing(self):
        prepared = prepare_cloud_generation(
            self.db, self.author, {"prompt": "自己改一版", "forkOf": self.work["workId"], "requestId": "r-3"}
        )
        self.assertIn("genId", prepared)
        stored = self.db.get_conn().execute(
            "SELECT fork_work_id FROM studio_generations WHERE id = ?", (prepared["genId"],)
        ).fetchone()["fork_work_id"]
        self.assertEqual(stored, "")


class PurgeScriptTests(unittest.TestCase):
    def test_purge_identifies_and_removes_unbacked_fork_rows(self):
        from ops import purge_publish_time_forks as purge

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "purge.db"
            db = server.init_database(path)
            try:
                user, _ = register_user(db, "purge_u", "password-a")
                work = publish_user_work(
                    db, user, {"title": "脏数据作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
                )
                db.get_conn().execute(
                    "INSERT INTO work_forks (work_id, user_id, first_generation_id, created_at) VALUES (?,?,?,?)",
                    (work["workId"], 999, "", "2026-01-01T00:00:00Z"),
                )
                db.get_conn().execute("UPDATE works SET forks = 1 WHERE id = ?", (work["workId"],))
                db.get_conn().commit()
                db.close_thread_conn()
            finally:
                db.get_conn().close()
                db.close()

            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            try:
                todo = purge.plan(conn)
                self.assertEqual(len(todo), 1)
                purge.apply(conn, todo)
                forks = conn.execute("SELECT forks FROM works").fetchone()["forks"]
                self.assertEqual(int(forks), 0, "purge must recompute the cached counter")
            finally:
                conn.close()

    def test_purge_catches_a_borrowed_generation_id(self):
        # A fork row pointing at another user's successful generation is still
        # bogus: the generation must belong to the forker and name this work.
        from ops import purge_publish_time_forks as purge
        from backend.services import complete_cloud_generation, prepare_cloud_generation

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "borrow.db"
            db = server.init_database(path)
            try:
                victim, _ = register_user(db, "purge_victim", "password-v")
                attacker, _ = register_user(db, "purge_attacker", "password-t")
                parent = publish_user_work(
                    db, victim, {"title": "被刷作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
                )
                prepared = prepare_cloud_generation(
                    db, victim, {"prompt": "受害者的生成", "requestId": "victim-gen"}
                )
                complete_cloud_generation(db, prepared["genId"], "tv", ["/generated/v.webp"])
                db.get_conn().execute(
                    "INSERT INTO work_forks (work_id, user_id, first_generation_id, created_at) VALUES (?,?,?,?)",
                    (parent["workId"], attacker["id"], prepared["genId"], "2026-01-01T00:00:00Z"),
                )
                db.get_conn().commit()
                db.close_thread_conn()
            finally:
                db.get_conn().close()
                db.close()

            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            try:
                todo = purge.plan(conn)
                self.assertEqual(len(todo), 1, "a borrowed generation id must be flagged")
                purge.apply(conn, todo)
                self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM work_forks").fetchone()[0]), 0)
            finally:
                conn.close()

    def test_backup_uses_the_sqlite_api_and_contains_data(self):
        from ops import purge_publish_time_forks as purge

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "backupdb.db"
            db = server.init_database(path)
            try:
                user, _ = register_user(db, "purge_bk", "password-a")
                publish_user_work(
                    db, user, {"title": "备份作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
                )
                db.close_thread_conn()
                conn = sqlite3.connect(str(path))
                conn.row_factory = sqlite3.Row
                try:
                    backup_path = purge.backup(conn, path)
                finally:
                    conn.close()
            finally:
                db.get_conn().close()
                db.close()
            check = sqlite3.connect(str(backup_path))
            try:
                rows = int(check.execute("SELECT COUNT(*) FROM works").fetchone()[0])
            finally:
                check.close()
            self.assertEqual(rows, 1, "the backup must include committed rows")


class ReceiptTransparencyTests(_Base):
    def test_receipt_explains_the_honour_upgrade(self):
        # A first work earns base + pioneer, and crossing the threshold also pays
        # an honour upgrade; the receipt must name the badge rather than leaving
        # the balance increase unexplained.
        result = publish_user_work(
            self.db, self.author, {"title": "回执作品", "prompt": "p", "images": [IMG], "styles": ["FA-014"]}
        )
        self.assertIn("pioneer", result)
        self.assertIn("upgradedBadge", result)
        self.assertEqual(result["reward"], 15)
        self.assertGreaterEqual(result["credits"], 15)


class AdminEditPreservesPromptTests(_Base):
    def test_editing_a_title_keeps_the_prompt_verbatim(self):
        padded = "  前后都有空格的提示词  "
        work = publish_user_work(
            self.db, self.author, {"title": "原样", "prompt": padded, "images": [IMG], "styles": ["FA-013"]}
        )
        admin_moderate_work(self.db, self.admin, work["workId"], "edit", {"title": "改过的标题"})
        stored = self.db.get_conn().execute(
            "SELECT prompt, title FROM works WHERE id = ?", (work["workId"],)
        ).fetchone()
        self.assertEqual(stored["prompt"], padded, "editing a title must not trim the prompt")
        self.assertEqual(stored["title"], "改过的标题")

    def test_non_numeric_price_edit_is_a_400(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            admin_moderate_work(self.db, self.admin, self.work["workId"], "edit", {"price": "abc"})
        self.assertEqual(ctx.exception.code, "invalid_price")


class RotationRevokesSessionsTests(unittest.TestCase):
    def test_rotation_drops_live_sessions(self):
        from ops import rotate_starter_credentials as rot

        with TemporaryDirectory() as tmp:
            db = server.init_database(Path(tmp) / "rot2.db")
            try:
                user, _ = register_user(db, "linnan", "handraw-starter-2026")
                db.get_conn().execute(
                    "INSERT INTO sessions (token, user_id, user_agent, ip_addr, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                    ("tok-old", user["id"], "ua", "127.0.0.1", 9999999999, "2026-01-01T00:00:00Z"),
                )
                db.get_conn().commit()
                todo = rot.plan(db)
                rot.apply(db, todo)
                remaining = db.get_conn().execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                self.assertEqual(remaining, 0, "rotating credentials must invalidate live sessions")
            finally:
                db.close_thread_conn()
                db.get_conn().close()
                db.close()


if __name__ == "__main__":
    unittest.main()
