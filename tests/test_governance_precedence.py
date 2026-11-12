"""Who may override whom: thread vs work decisions, ranks, and the report flow.

Each case is a regression the reviews found (M3, M4, M7, M8, M9, M11, N1, R2,
R4, V9).  They drive the real HTTP endpoints with real roles, then check
both the stored state and what an anonymous reader can see.  The mutation
matrix in docs/architecture/final-implementation-20261030.md lists which case
fails when each guard is removed.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.legacy_database import init_legacy_database
from backend import server as server_module
from backend.config import SESSION_COOKIE_NAME
from backend.server import create_channel_server
from backend.services import publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"
ORIGIN = "http://trusted.test"


class PrecedenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": ORIGIN})
        cls._env.start()
        cls.temp = TemporaryDirectory()
        cls.db = init_legacy_database(Path(cls.temp.name) / "precedence.db")
        conn = cls.db.get_conn()
        cls.author, _ = register_user(cls.db, "pc_author", "password-a")
        for name, role in (("pc_admin", "admin"), ("pc_oper", "operator"), ("pc_mod", None)):
            register_user(cls.db, name, f"password-{name}")
            if role:
                conn.execute("UPDATE users SET role = ? WHERE username = ?", (role, name))
        mod_id = conn.execute("SELECT id FROM users WHERE username = 'pc_mod'").fetchone()["id"]
        conn.execute(
            "INSERT INTO forum_moderators (user_id, username, category, created_at) VALUES (?, ?, 'all', ?)",
            (mod_id, "pc_mod", "2026-10-30T00:00:00Z"),
        )
        cls.reporters = []
        for i in range(3):
            register_user(cls.db, f"pc_rep{i}", f"password-rep{i}")
            cls.reporters.append((f"pc_rep{i}", f"password-rep{i}"))
        conn.commit()
        cls.db.close_thread_conn()
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.tokens = {}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close_thread_conn()
        cls.db.get_conn().close()
        cls.db.close()
        cls.temp.cleanup()
        cls._env.stop()

    # ------------------------------------------------------------ plumbing
    def _request(self, method, path, body=None, who=None):
        headers = {"Origin": ORIGIN}
        if who:
            headers["Cookie"] = f"{SESSION_COOKIE_NAME}={self._token(who)}"
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, self._decode(resp)
        except urllib.error.HTTPError as err:
            return err.code, self._decode(err)

    @staticmethod
    def _decode(resp):
        raw = resp.read()
        if "json" in resp.headers.get("Content-Type", ""):
            return json.loads(raw)
        return raw.decode("utf-8", "replace")

    def _token(self, who):
        if who not in self.tokens:
            password = {"pc_author": "password-a"}.get(who) or dict(self.reporters).get(who) or f"password-{who}"
            status, payload = self._request("POST", "/api/auth/login", {"account": who, "password": password})
            self.assertEqual(status, 200, payload)
            self.tokens[who] = payload["token"]
        return self.tokens[who]

    def setUp(self):
        self.work = publish_user_work(
            self.db, self.author,
            {"title": f"优先级 {self._testMethodName}", "prompt": "p", "images": [IMG], "styles": ["FA-013"]},
        )
        self.wid, self.tid = self.work["workId"], self.work["topicId"]

    def _state(self):
        conn = self.db.get_conn()
        w = conn.execute("SELECT status FROM works WHERE id = ?", (self.wid,)).fetchone()
        t = conn.execute("SELECT status FROM forum_topics WHERE id = ?", (self.tid,)).fetchone()
        self.db.close_thread_conn()
        return (w["status"] if w else None, t["status"] if t else None)

    def _topic_source(self):
        row = self.db.get_conn().execute(
            "SELECT status_source FROM forum_topics WHERE id = ?", (self.tid,)
        ).fetchone()
        self.db.close_thread_conn()
        return row["status_source"]

    def _thread_public(self):
        """True if an anonymous reader can reach the thread."""
        _, boot = self._request("GET", "/api/boot")
        status, _ = self._request("GET", f"/api/forum/resource-topics/{self.tid}")
        return self.tid in json.dumps(boot, ensure_ascii=False) or status == 200

    def _work(self, who, action):
        return self._request("POST", f"/api/admin/works/{self.wid}/moderate", {"action": action}, who)

    def _admin_topic(self, who, action):
        return self._request("POST", f"/api/admin/topics/{self.tid}/moderate", {"action": action}, who)

    def _forum(self, who, action, **extra):
        return self._request("POST", "/api/forum/moderate", {"topicId": self.tid, "action": action, **extra}, who)

    def _report(self, target_type, target_id, who):
        return self._request("POST", "/api/reports", {"targetType": target_type, "targetId": target_id, "reason": "spam"}, who)

    def _report_by_all(self, target_type, target_id):
        return [self._report(target_type, target_id, name)[1].get("autoPaused") for name, _ in self.reporters]

    def _resolve_first(self, target_type, target_id, resolution, who="pc_admin", **extra):
        row = self.db.get_conn().execute(
            "SELECT id FROM reports WHERE target_type = ? AND target_id = ? AND status = 'open' ORDER BY id LIMIT 1",
            (target_type, target_id),
        ).fetchone()
        self.db.close_thread_conn()
        self.assertIsNotNone(row, "expected an open report")
        return self._request(
            "POST", f"/api/admin/reports/{row['id']}/resolve", {"resolution": resolution, **extra}, who
        )

    # ---------------------------------------------- thread vs work (M8, M3, M4)
    def test_publishing_the_work_keeps_a_thread_hidden_through_the_admin_entry(self):
        # M8: an operator pressing "publish" on a live work used to republish a
        # thread the admin had hidden on its own.
        self.assertEqual(self._admin_topic("pc_admin", "hide")[0], 200)
        status, payload = self._work("pc_oper", "publish")
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._state(), ("published", "hidden"))
        self.assertFalse(self._thread_public())

    def test_publishing_the_work_keeps_a_thread_hidden_through_the_forum_entry(self):
        # M8f: same, with the hide made through /api/forum/moderate.
        self.assertEqual(self._forum("pc_admin", "hide")[0], 200)
        self.assertEqual(self._work("pc_oper", "publish")[0], 200)
        self.assertEqual(self._state(), ("published", "hidden"))

    def test_pausing_and_republishing_the_work_keeps_a_moderator_hidden_thread(self):
        # A3: the mirror used to overwrite the thread on the way down, then
        # republish it on the way up.
        self.assertEqual(self._forum("pc_mod", "hide")[0], 200)
        self.assertEqual(self._work("pc_admin", "pause")[0], 200)
        self.assertEqual(self._state(), ("paused", "hidden"))
        self.assertEqual(self._work("pc_admin", "publish")[0], 200)
        self.assertEqual(self._state(), ("published", "hidden"))
        self.assertEqual(self._topic_source(), "moderator")
        self.assertFalse(self._thread_public())

    def test_a_mirrored_thread_follows_its_work_back(self):
        # The counterpart: a thread that was dark only because of its work
        # comes back when the work does.
        self._work("pc_admin", "hide")
        self.assertEqual(self._state(), ("hidden", "hidden"))
        self.assertEqual(self._topic_source(), "work")
        self._work("pc_admin", "publish")
        self.assertEqual(self._state(), ("published", "published"))
        self.assertTrue(self._thread_public())

    def test_work_report_dismissal_keeps_a_thread_hidden_first(self):
        # M4: thread hidden, then the work is auto-paused and the report dismissed.
        self._forum("pc_mod", "hide")
        self.assertEqual(self._report_by_all("work", self.wid), [False, False, True])
        self.assertEqual(self._state(), ("paused", "hidden"))
        self.assertEqual(self._resolve_first("work", self.wid, "dismissed", who="pc_oper")[0], 200)
        self.assertEqual(self._state(), ("published", "hidden"))
        self.assertFalse(self._thread_public())

    def test_work_report_dismissal_keeps_a_thread_hidden_later(self):
        # M3: the work is auto-paused first, then the thread is hidden.
        self._report_by_all("work", self.wid)
        self.assertEqual(self._admin_topic("pc_mod", "hide")[0], 200)
        self._resolve_first("work", self.wid, "dismissed")
        self.assertEqual(self._state(), ("published", "hidden"))

    # ----------------------------------------------------- ranks (M9, R4)
    def test_operator_cannot_republish_a_work_an_admin_hid(self):
        # M9, product rule "admin wins" (pending founder confirmation).
        self._work("pc_admin", "hide")
        status, payload = self._work("pc_oper", "publish")
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload.get("code"), "decision_locked")
        self.assertEqual(self._state(), ("hidden", "hidden"))
        # The admin still can.
        self.assertEqual(self._work("pc_admin", "publish")[0], 200)
        self.assertEqual(self._state(), ("published", "published"))

    def test_moderator_cannot_republish_a_thread_an_admin_hid(self):
        self._admin_topic("pc_admin", "hide")
        for call in (lambda: self._forum("pc_mod", "publish"), lambda: self._admin_topic("pc_mod", "publish")):
            status, payload = call()
            self.assertEqual(status, 403, payload)
            self.assertEqual(payload.get("code"), "decision_locked")
        self.assertEqual(self._state(), ("published", "hidden"))

    def test_moderator_cannot_republish_a_reply_an_admin_confirmed(self):
        # R4: confirming a report hides the reply with the admin's rank; a
        # board moderator's publish_reply used to undo it.
        status, payload = self._request(
            "POST", f"/api/forum/resources/work/{self.wid}/comments", {"text": "违规评论"}, "pc_rep0"
        )
        self.assertEqual(status, 200, payload)
        reply_id = payload["replyId"]
        self._report("reply", reply_id, "pc_rep1")
        self.assertEqual(self._resolve_first("reply", reply_id, "confirmed", autoAction=True)[0], 200)
        status, payload = self._forum("pc_mod", "publish_reply", replyId=reply_id)
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload.get("code"), "decision_locked")
        row = self.db.get_conn().execute("SELECT status FROM forum_replies WHERE id = ?", (reply_id,)).fetchone()
        self.db.close_thread_conn()
        self.assertEqual(row["status"], "hidden")
        # An admin can still restore it.
        self.assertEqual(self._forum("pc_admin", "publish_reply", replyId=reply_id)[0], 200)

    # ------------------------------------------------ report flow (M7, M11)
    def test_dismissing_a_thread_report_does_not_expose_a_paused_work(self):
        # M7: the thread is paused by its own reports, the work by its own;
        # dismissing the thread's reports must leave it as dark as its work.
        self._report_by_all("topic", self.tid)
        self.assertEqual(self._state(), ("published", "paused"))
        self._report_by_all("work", self.wid)
        self.assertEqual(self._state(), ("paused", "paused"))
        self.assertEqual(self._resolve_first("topic", self.tid, "dismissed")[0], 200)
        self.assertEqual(self._state(), ("paused", "paused"))
        self.assertEqual(self._topic_source(), "work", "the thread now follows its work")
        self.assertFalse(self._thread_public())
        # ...and comes back with the work.
        self._resolve_first("work", self.wid, "dismissed")
        self.assertEqual(self._state(), ("published", "published"))

    def test_work_changes_do_not_lift_a_thread_report_hold(self):
        # The thread is paused by its own open reports.  Hiding and
        # republishing the work must not publish it: only its own dismissal
        # (or confirmation) ends that hold.
        self._report_by_all("topic", self.tid)
        self.assertEqual(self._state(), ("published", "paused"))
        self._work("pc_admin", "hide")
        self._work("pc_admin", "publish")
        self.assertEqual(self._state(), ("published", "paused"))
        self.assertEqual(self._topic_source(), "report")
        self.assertFalse(self._thread_public())

    def test_dismissing_a_thread_report_restores_a_thread_paused_only_by_reports(self):
        # N5 / MU5: a pure report pause is lifted, and the provenance cleared.
        self._report_by_all("topic", self.tid)
        self._resolve_first("topic", self.tid, "dismissed")
        self.assertEqual(self._state(), ("published", "published"))
        self.assertEqual(self._topic_source(), "")
        self.assertTrue(self._thread_public())

    def test_confirming_without_auto_action_survives_a_later_dismissal(self):
        # M11: "confirm" with autoAction=false must still turn the report
        # pause into a human verdict.
        self._report_by_all("work", self.wid)
        self.assertEqual(self._resolve_first("work", self.wid, "confirmed", autoAction=False)[0], 200)
        self.assertEqual(self._state(), ("paused", "paused"))
        self._report("work", self.wid, "pc_rep0")
        self._resolve_first("work", self.wid, "dismissed")
        self.assertEqual(self._state(), ("paused", "paused"))
        self.assertFalse(self._thread_public())

    def test_confirmed_work_report_survives_a_later_dismissal(self):
        # U4 / M-a, over HTTP.
        self._report("work", self.wid, "pc_rep0")
        self._resolve_first("work", self.wid, "confirmed", autoAction=True)
        self.assertEqual(self._state(), ("hidden", "hidden"))
        self._report("work", self.wid, "pc_rep1")
        self._resolve_first("work", self.wid, "dismissed")
        self.assertEqual(self._state(), ("hidden", "hidden"))

    def test_confirming_a_thread_report_by_staff_hides_the_work_too(self):
        # V9 (pending founder confirmation): a work's main thread shows the
        # work, so a staff verdict on it is a verdict on the work.
        self._report("topic", self.tid, "pc_rep0")
        self.assertEqual(self._resolve_first("topic", self.tid, "confirmed", who="pc_oper", autoAction=True)[0], 200)
        self.assertEqual(self._state(), ("hidden", "hidden"))
        self.assertEqual(self._topic_source(), "moderator")

    def test_confirming_a_thread_report_by_a_board_moderator_leaves_the_work(self):
        # Board moderators cannot moderate works, so their verdict stops at
        # the thread.
        self._report("topic", self.tid, "pc_rep0")
        self.assertEqual(self._resolve_first("topic", self.tid, "confirmed", who="pc_mod", autoAction=True)[0], 200)
        self.assertEqual(self._state(), ("published", "hidden"))

    def test_thread_reports_do_not_pause_a_thread_that_mirrors_its_work(self):
        # H4: the thread is dark only because its work is hidden.  Reports on
        # it must not turn that into a report pause, or republishing the work
        # would leave the thread dark until someone handles the reports.
        self._work("pc_admin", "hide")
        self.assertEqual(self._report_by_all("topic", self.tid), [False, False, False])
        self.assertEqual(self._topic_source(), "work")
        self._work("pc_admin", "publish")
        self.assertEqual(self._state(), ("published", "published"))

    def test_thread_reports_do_not_turn_a_moderator_hide_into_a_pause(self):
        # H4: auto-pause only applies to a live thread.
        self._forum("pc_mod", "hide")
        self.assertEqual(self._report_by_all("topic", self.tid), [False, False, False])
        self.assertEqual(self._topic_source(), "moderator")
        self._resolve_first("topic", self.tid, "dismissed")
        self.assertEqual(self._state(), ("published", "hidden"))

    # --------------------------------------------------- deleted (N1, R2, N5)
    def test_confirming_a_report_on_a_deleted_thread_keeps_it_deleted(self):
        # N1d: the report is on the *thread*, filed before the work is deleted.
        self._report("topic", self.tid, "pc_rep0")
        self.assertEqual(self._work("pc_admin", "delete")[0], 200)
        self.assertEqual(self._resolve_first("topic", self.tid, "confirmed", who="pc_oper", autoAction=True)[0], 200)
        self.assertEqual(self._state(), (None, "deleted"))
        status, payload = self._admin_topic("pc_oper", "publish")
        self.assertEqual((status, payload.get("code")), (409, "topic_deleted"))
        self.assertFalse(self._thread_public())

    def test_author_deleted_thread_survives_work_hide_and_publish(self):
        # R2: the work mirror used to overwrite an author's deletion.
        self.assertEqual(self._forum("pc_author", "delete")[0], 200)
        self.assertEqual(self._topic_source(), "author")
        self._work("pc_admin", "hide")
        self._work("pc_admin", "publish")
        self.assertEqual(self._state(), ("published", "deleted"))
        self.assertFalse(self._thread_public())

    def test_author_deleted_thread_survives_work_report_dismissal(self):
        # R2b.
        self._forum("pc_author", "delete")
        self._report_by_all("work", self.wid)
        self._resolve_first("work", self.wid, "dismissed")
        self.assertEqual(self._state(), ("published", "deleted"))

    def test_admin_deleting_a_work_thread_keeps_the_row(self):
        # N5: the admin entry used to remove the row, leaving the mapping
        # pointing at nothing.  The thread is now marked deleted, like the
        # forum entry does, and stays so.
        self.assertEqual(self._admin_topic("pc_admin", "delete")[0], 200)
        self.assertEqual(self._state(), ("published", "deleted"))
        self._work("pc_admin", "hide")
        self._work("pc_admin", "publish")
        self.assertEqual(self._state(), ("published", "deleted"))
        self.assertFalse(self._thread_public())
