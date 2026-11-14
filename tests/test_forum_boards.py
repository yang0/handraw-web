import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import server as web
from backend import services as S
from backend import forum_boards as B
from backend.features import list_notifications
from backend.post_routes import _is_topic_visible
from tests.postgres_support import open_isolated_postgres


class ForumBoardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {"HANDRAW_PRIVATE_STORAGE": str(self.root), "HANDRAW_DEMO_MODE": "0"},
            )
        )
        self.db = open_isolated_postgres(self)
        self.admin, self.admin_token = S.register_user(
            self.db, "board_admin", "FixturePass123!"
        )
        self.member, self.member_token = S.register_user(
            self.db, "board_member", "FixturePass123!"
        )
        self.outsider, self.outsider_token = S.register_user(
            self.db, "board_outside", "FixturePass123!"
        )
        self.db.get_conn().execute(
            "UPDATE users SET role='admin' WHERE id=?", (self.admin["id"],)
        )
        self.admin.update(role="admin", status="active")
        self.key = B.save_board(
            self.db, self.admin, {"label": "受邀讨论", "visibility": "private"}
        )["key"]
        B.change_members(
            self.db, self.admin, self.key, {"usernames": [self.member["username"]]}
        )
        self.tid = S.publish_forum_topic_post(
            self.db,
            self.member,
            {
                "category": self.key,
                "title": "私密论坛测试标题",
                "body": "仅受邀成员能读的正文",
            },
        )["topicId"]

    def save(self, **changes):
        board = next(
            b
            for b in B.admin_list(self.db, self.admin)["items"]
            if b["key"] == self.key
        )
        return B.save_board(self.db, self.admin, {**board, **changes}, self.key)

    def denied(self, call):
        with self.assertRaises(S.ServiceError) as raised:
            call()
        self.assertEqual(raised.exception.status, 404)

    def test_invitation_hides_links_and_content_from_nonmembers_even_staff(self):
        for viewer in (None, self.outsider, {**self.outsider, "role": "operator"}):
            self.assertNotIn(
                self.key, [b["key"] for b in B.list_boards(self.db.get_conn(), viewer)]
            )
            self.denied(lambda: B.require_topic(self.db.get_conn(), self.tid, viewer))
            row = (
                self.db.get_conn()
                .execute("SELECT * FROM forum_topics WHERE id=?", (self.tid,))
                .fetchone()
            )
            self.assertFalse(_is_topic_visible(self.db.get_conn(), row, viewer))
            boot = S.build_boot_payload(self.db, viewer)
            self.assertNotIn(self.tid, [t["id"] for t in boot["topics"]])
        boot = S.build_boot_payload(self.db, self.member)
        self.assertIn(self.tid, [t["id"] for t in boot["topics"]])
        self.assertIn(self.key, [b["key"] for b in boot["forumBoards"]])
        from backend.forum_resources import related_items

        self.db.get_conn().execute(
            "UPDATE forum_topics SET styles_json='[\"FA-001\"]' WHERE id=?", (self.tid,)
        )
        for viewer, expected in (
            (self.member, True),
            (self.outsider, False),
            (None, False),
        ):
            items = related_items(self.db, viewer, "style", "FA-001", "topics")["items"]
            self.assertEqual(self.tid in [t["id"] for t in items], expected)

    def test_revoke_blocks_all_social_writes_and_notifications_without_destroying_posts(
        self,
    ):
        S.publish_forum_reply_post(self.db, self.member, self.tid, "有权回复")
        self.db.get_conn().execute(
            "INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at) VALUES(?,'reply','私密通知','topic',?,CURRENT_TIMESTAMP::text)",
            (self.member["id"], self.tid),
        )
        self.assertTrue(list_notifications(self.db, self.member)["items"])
        B.change_members(
            self.db,
            self.admin,
            self.key,
            {"action": "revoke", "usernames": [self.member["username"]]},
        )
        for call in (
            lambda: S.publish_forum_reply_post(
                self.db, self.member, self.tid, "越权回复"
            ),
            lambda: S.toggle_user_like(self.db, self.member, "topic", self.tid),
            lambda: S.toggle_user_collection(self.db, self.member, "topics", self.tid),
            lambda: S.unlock_paid_item(self.db, self.member, "topic", self.tid),
            lambda: S.publish_forum_topic_post(
                self.db,
                self.member,
                {"category": self.key, "title": "撤权后不能发布", "body": "不能发布"},
            ),
        ):
            self.denied(call)
        self.assertFalse(list_notifications(self.db, self.member)["items"])
        B.change_members(
            self.db, self.admin, self.key, {"usernames": [self.member["username"]]}
        )
        self.assertTrue(B.can_read_topic(self.db.get_conn(), self.tid, self.member))
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT count(*) FROM forum_topics WHERE id=?", (self.tid,))
            .fetchone()[0],
            1,
        )

    def test_close_reopen_revision_and_private_history_cannot_be_published(self):
        self.save(state="closed")
        self.denied(lambda: B.require_topic(self.db.get_conn(), self.tid, self.member))
        self.assertNotIn(
            self.key, [b["key"] for b in B.list_boards(self.db.get_conn(), self.member)]
        )
        self.save(state="open")
        self.assertTrue(B.can_read_topic(self.db.get_conn(), self.tid, self.member))
        with self.assertRaises(S.ServiceError) as raised:
            self.save(visibility="public")
        self.assertEqual(raised.exception.code, "private_history")
        from backend.admin_services import admin_moderate_topic

        with self.assertRaises(S.ServiceError) as raised:
            admin_moderate_topic(
                self.db, self.admin, self.tid, "edit", {"category": "experience"}
            )
        self.assertEqual(raised.exception.status, 409)
        with self.assertRaises(S.ServiceError) as raised:
            B.save_board(
                self.db, self.admin, {"label": "冲突", "revision": 1}, self.key
            )
        self.assertEqual(raised.exception.status, 409)

    def test_private_images_require_current_membership_even_after_cached_derivative(
        self,
    ):
        from PIL import Image

        uploads = self.root / "uploads"
        uploads.mkdir()
        target = uploads / "secret.jpg"
        Image.new("RGB", (500, 300), "red").save(target)
        self.db.get_conn().execute(
            "INSERT INTO user_uploads(id,user_id,cat,name_zh,image_url,file_path,bytes,created_at,updated_at) VALUES('board-image',?,'other','Secret','/uploads/secret.jpg',?,?,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
            (self.admin["id"], str(target), target.stat().st_size),
        )
        self.db.get_conn().execute(
            "INSERT INTO media_public_grants(id,media_url,owner_user_id,target_type,target_id,granted_by_user_id,granted_at) VALUES('board-grant','/uploads/secret.jpg',?,'topic',?,?,CURRENT_TIMESTAMP::text)",
            (self.admin["id"], self.tid, self.admin["id"]),
        )
        self.assertFalse(web._is_published_media(self.db, "/uploads/secret.jpg"))
        self.assertEqual(
            web._private_media_access(self.db, "/uploads/secret.jpg", self.member),
            (True, "private, no-store"),
        )
        self.assertFalse(
            web._private_media_access(self.db, "/uploads/secret.jpg", self.outsider)[0]
        )
        B.change_members(
            self.db,
            self.admin,
            self.key,
            {"action": "revoke", "usernames": [self.member["username"]]},
        )
        self.assertFalse(
            web._private_media_access(self.db, "/uploads/secret.jpg", self.member)[0]
        )

    def test_parallel_invitations_are_one_membership_and_close_waits_for_accepted_write(
        self,
    ):
        from concurrent.futures import ThreadPoolExecutor

        def invite():
            try:
                B.change_members(
                    self.db,
                    self.admin,
                    self.key,
                    {"usernames": [self.outsider["username"]]},
                )
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: invite(), range(8)))
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT count(*) FROM forum_board_members WHERE board_key=? AND user_id=? AND revoked_at IS NULL",
                (self.key, self.outsider["id"]),
            )
            .fetchone()[0],
            1,
        )
        started = threading.Event()
        done = threading.Event()

        def close():
            try:
                started.set()
                self.save(state="closed")
            finally:
                self.db.close_thread_conn()
                done.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.db.transaction() as tx:
                B.require_topic(tx, self.tid, self.member, write=True)
                future = pool.submit(close)
                self.assertTrue(started.wait(3))
                self.assertFalse(
                    done.wait(0.15),
                    "closure waits for in-flight accepted write transaction",
                )
            future.result(timeout=5)
        self.denied(lambda: B.require_topic(self.db.get_conn(), self.tid, self.member))

    def test_reports_and_legacy_reply_aliases_obey_private_membership(self):
        from backend.admin_services import admin_list_reports, admin_resolve_report

        reply = S.publish_forum_reply_post(
            self.db, self.member, self.tid, "私密回复内容"
        )["replyId"]
        self.db.get_conn().execute(
            "UPDATE forum_replies SET legacy_source='work_comments:legacy-private' WHERE id=?",
            (reply,),
        )
        operator = dict(self.outsider, role="operator", status="active")
        targets = (("reply", reply), ("comment", "legacy-private"), ("topic", self.tid))
        report_ids = []
        for kind, target in targets:
            body = {
                "targetType": kind,
                "targetId": target,
                "reason": "隐私检查",
                "detail": "仅成员可读的举报详情",
            }
            self.denied(lambda: S.submit_abuse_report(self.db, self.outsider, body))
            S.submit_abuse_report(self.db, self.member, body)
            report_id = int(
                self.db.get_conn()
                .execute(
                    "SELECT id FROM reports WHERE target_type=? AND target_id=?",
                    (kind, target),
                )
                .fetchone()[0]
            )
            report_ids.append(report_id)
            self.denied(
                lambda: admin_resolve_report(self.db, operator, report_id, "dismissed")
            )
            self.assertEqual(
                self.db.get_conn()
                .execute("SELECT status FROM reports WHERE id=?", (report_id,))
                .fetchone()[0],
                "open",
            )
        self.assertFalse(admin_list_reports(self.db, operator)["items"])
        B.change_members(
            self.db, self.admin, self.key, {"usernames": [self.outsider["username"]]}
        )
        self.assertEqual(len(admin_list_reports(self.db, operator)["items"]), 3)
        for report_id in report_ids:
            admin_resolve_report(self.db, operator, report_id, "dismissed")

    def test_real_http_admin_and_direct_urls(self):
        server = web.create_channel_server(
            0, "main", self.db, host="127.0.0.1", demo_mode=False
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(path, token=None, body=None):
            conn = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=15
            )
            headers = {"Authorization": "Bearer " + token} if token else {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(
                "POST" if body is not None else "GET",
                path,
                json.dumps(body) if body is not None else None,
                headers,
            )
            response = conn.getresponse()
            status = response.status
            data = json.loads(response.read())
            conn.close()
            return status, data

        self.assertEqual(request("/api/posts/" + self.tid, self.member_token)[0], 200)
        for token in (None, self.outsider_token):
            self.assertEqual(request("/api/posts/" + self.tid, token)[0], 404)
            self.assertEqual(
                request("/api/posts/" + self.tid + "/replies", token)[0], 404
            )
        self.assertEqual(request("/api/admin/forum-boards", self.member_token)[0], 403)
        status, data = request(
            "/api/admin/forum-boards",
            self.admin_token,
            {"label": "HTTP新增论坛", "visibility": "public"},
        )
        self.assertEqual(status, 200)
        self.assertIn(
            data["key"], [r["key"] for r in request("/api/forum/boards")[1]["items"]]
        )


if __name__ == "__main__":
    unittest.main()
