"""HTTP tests for post routes (/api/posts/*, /t/*) and read-only invariants (Phase 1a)."""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import resource_discussions, services
from backend import server as server_module
from backend.config import SESSION_COOKIE_NAME
from backend.server import create_channel_server
from backend.services import (
    publish_user_work,
    register_user,
    toggle_user_collection,
    toggle_user_like,
    unlock_paid_item,
)
from ops import ensure_resource_topics

IMG = "/images/individual/FA/FA-013.webp"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not follow redirects; let caller inspect response code and Location header
        return None


class PostRoutesHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"})
        cls._env.start()
        cls.temp = TemporaryDirectory()
        cls.db_path = Path(cls.temp.name) / "post_routes.db"
        cls.db = server_module.init_database(cls.db_path)

        # Register users
        cls.author, _ = register_user(cls.db, "pr_author", "pass-author")
        cls.reader, _ = register_user(cls.db, "pr_reader", "pass-reader")
        cls.buyer, _ = register_user(cls.db, "pr_buyer", "pass-buyer")
        cls.admin, _ = register_user(cls.db, "pr_admin", "pass-admin")

        # Give buyer some credits to unlock paid items
        conn = cls.db.get_conn()
        conn.execute("UPDATE wallets SET balance = 100 WHERE user_id = ?", (cls.buyer["id"],))
        conn.execute("UPDATE users SET role = 'admin' WHERE username = 'pr_admin'")
        conn.commit()

        # Publish a normal free work
        pub_work = publish_user_work(
            cls.db,
            cls.author,
            {"title": "普通作品", "prompt": "公开的提示词", "images": [IMG], "styles": ["FA-013"], "price": 0},
        )
        cls.work_id = pub_work["workId"]
        cls.work_topic_id = pub_work["topicId"]

        # Publish a paid work
        pub_paid = publish_user_work(
            cls.db,
            cls.author,
            {"title": "付费作品", "prompt": "绝密付费提示词", "images": [IMG], "styles": ["FA-013"], "price": 10},
        )
        cls.paid_work_id = pub_paid["workId"]
        cls.paid_topic_id = pub_paid["topicId"]

        # Ensure topics for all catalog styles & layouts
        ensure_resource_topics.main(["--db", str(cls.db_path), "--apply"])

        # Fetch FB-041 topicId
        row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND target_id = 'FB-041'"
        ).fetchone()
        cls.fb041_topic_id = str(row["topic_id"])

        # Create HTTP server
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.tokens: dict[str, str] = {}

        # Opener without redirect following
        cls.no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)

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

    def _login(self, username: str, password: str) -> str:
        if username in self.tokens:
            return self.tokens[username]
        status, payload = self._request(
            "POST", "/api/auth/login", {"account": username, "password": password}
        )
        self.assertEqual(status, 200, payload)
        self.tokens[username] = payload["token"]
        return payload["token"]

    def _request(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        headers = {"Origin": "http://trusted.test"}
        if token:
            headers["Cookie"] = f"{SESSION_COOKIE_NAME}={token}"
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, self._decode(res)
        except urllib.error.HTTPError as err:
            return err.code, self._decode(err)

    def _request_raw_redirect(self, path: str):
        headers = {"Origin": "http://trusted.test"}
        req = urllib.request.Request(self.base + path, headers=headers, method="GET")
        try:
            res = self.no_redirect_opener.open(req, timeout=10)
            return res.status, res.headers.get("Location")
        except urllib.error.HTTPError as err:
            return err.code, err.headers.get("Location")

    @staticmethod
    def _decode(res):
        raw = res.read()
        ctype = res.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(raw)
        return raw.decode("utf-8", "replace")

    def test_by_ref_endpoint(self):
        """GET /api/posts/by-ref/{kind}/{id} normal, case-insensitive, 404, hidden."""
        # 1. Style FB-041
        status, data = self._request("GET", "/api/posts/by-ref/style/FB-041")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["topicId"], self.fb041_topic_id)

        # 2. Case-insensitive fb-041
        status, data_lower = self._request("GET", "/api/posts/by-ref/style/fb-041")
        self.assertEqual(status, 200)
        self.assertEqual(data_lower["topicId"], self.fb041_topic_id)

        # 3. Work ref
        status, data_work = self._request("GET", f"/api/posts/by-ref/work/{self.work_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data_work["topicId"], self.work_topic_id)

        # 4. Unknown resource -> 404
        status, err = self._request("GET", "/api/posts/by-ref/style/NOT_EXIST_CODE")
        self.assertEqual(status, 404)

        # 5. Hidden topic -> 404
        conn = self.db.get_conn()
        conn.execute("UPDATE forum_topics SET status = 'hidden' WHERE id = ?", (self.work_topic_id,))
        conn.commit()
        try:
            status, _ = self._request("GET", f"/api/posts/by-ref/work/{self.work_id}")
            self.assertEqual(status, 404)
        finally:
            conn.execute("UPDATE forum_topics SET status = 'published' WHERE id = ?", (self.work_topic_id,))
            conn.commit()

    def test_post_detail_endpoint(self):
        """GET /api/posts/{topicId} normal, viewer liked/favorited, privacy protection."""
        # 1. Normal work detail without login
        status, data = self._request("GET", f"/api/posts/{self.work_topic_id}")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["topic"]["title"], "普通作品")
        self.assertEqual(data["mount"]["kind"], "work")
        self.assertEqual(data["mount"]["work"]["prompt"], "公开的提示词")
        self.assertFalse(data["viewer"]["liked"])
        self.assertFalse(data["viewer"]["favorited"])

        # 2. Logged-in reader who likes and favorites the work
        reader_token = self._login("pr_reader", "pass-reader")
        toggle_user_like(self.db, self.reader, "work", self.work_id)
        toggle_user_collection(self.db, self.reader, "works", self.work_id)

        status, data_logged = self._request(
            "GET", f"/api/posts/{self.work_topic_id}", token=reader_token
        )
        self.assertEqual(status, 200)
        self.assertTrue(data_logged["viewer"]["liked"])
        self.assertTrue(data_logged["viewer"]["favorited"])

        # 3. Paid work: locked content must not leak
        # Anonymous / unpurchased viewer: prompt is empty
        status, data_paid_anon = self._request("GET", f"/api/posts/{self.paid_topic_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data_paid_anon["mount"]["work"]["prompt"], "", "Paid prompt must not leak")

        buyer_token = self._login("pr_buyer", "pass-buyer")
        status, data_paid_unlocked = self._request(
            "GET", f"/api/posts/{self.paid_topic_id}", token=buyer_token
        )
        self.assertEqual(status, 200)
        self.assertEqual(data_paid_unlocked["mount"]["work"]["prompt"], "", "Unpurchased prompt must not leak")

        # Unlock paid work by buyer
        unlock_paid_item(self.db, self.buyer, "work", self.paid_work_id)
        status, data_purchased = self._request(
            "GET", f"/api/posts/{self.paid_topic_id}", token=buyer_token
        )
        self.assertEqual(status, 200)
        self.assertEqual(data_purchased["mount"]["work"]["prompt"], "绝密付费提示词")

        # 4. Style topic detail
        status, data_style = self._request("GET", f"/api/posts/{self.fb041_topic_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data_style["mount"]["kind"], "style")
        self.assertEqual(data_style["mount"]["resource"]["code"], "FB-041")
        self.assertIn("useUrl", data_style["mount"]["resource"])
        self.assertEqual(data_style["mount"]["resource"]["useUrl"], "/studio/?style=FB-041")

        # 5. Nonexistent topic -> 404
        status, _ = self._request("GET", "/api/posts/topic_not_exist_9999")
        self.assertEqual(status, 404)

    def test_post_replies_pagination(self):
        """GET /api/posts/{topicId}/replies 45 items, limit 20, 3 pages, order, no duplicates."""
        conn = self.db.get_conn()
        topic_id = self.fb041_topic_id

        # Insert 45 published replies with ordered timestamps
        for i in range(45):
            rid = f"rep_page_{i:03d}"
            t_iso = f"2026-02-01T10:{i // 60:02d}:{i % 60:02d}Z"
            conn.execute(
                """
                INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at)
                VALUES (?, ?, 'uni_reader', '读者', ?, '', '', 0, 0, 'published', '刚刚', ?)
                """,
                (rid, topic_id, f"第 {i+1} 条回复内容", t_iso),
            )
        # Also insert a hidden reply which must not appear
        conn.execute(
            """
            INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, mounted_style, mounted_layout, likes, accepted, status, time_label, created_at)
            VALUES ('rep_page_hidden', ?, 'uni_reader', '读者', '隐藏内容', '', '', 0, 0, 'hidden', '刚刚', '2026-02-01T10:00:00Z')
            """,
            (topic_id,),
        )
        conn.commit()

        # Page 1 (limit=20)
        status, p1 = self._request("GET", f"/api/posts/{topic_id}/replies?limit=20")
        self.assertEqual(status, 200)
        self.assertEqual(len(p1["items"]), 20)
        self.assertIsNotNone(p1["nextCursor"])

        # Page 2
        cursor1 = p1["nextCursor"]
        status, p2 = self._request("GET", f"/api/posts/{topic_id}/replies?limit=20&cursor={cursor1}")
        self.assertEqual(status, 200)
        self.assertEqual(len(p2["items"]), 20)
        self.assertIsNotNone(p2["nextCursor"])

        # Page 3
        cursor2 = p2["nextCursor"]
        status, p3 = self._request("GET", f"/api/posts/{topic_id}/replies?limit=20&cursor={cursor2}")
        self.assertEqual(status, 200)
        self.assertEqual(len(p3["items"]), 5)
        self.assertIsNone(p3["nextCursor"])

        # Verify no duplicates and total = 45
        all_ids = [r["id"] for r in p1["items"] + p2["items"] + p3["items"]]
        self.assertEqual(len(all_ids), 45)
        self.assertEqual(len(set(all_ids)), 45, "No duplicate reply items across pages")
        self.assertNotIn("rep_page_hidden", all_ids)

        # Verify sorting is strictly ascending
        all_items = p1["items"] + p2["items"] + p3["items"]
        for idx in range(len(all_items) - 1):
            prev_key = (all_items[idx]["createdAt"], all_items[idx]["id"])
            next_key = (all_items[idx + 1]["createdAt"], all_items[idx + 1]["id"])
            self.assertLess(prev_key, next_key)

    def test_t_redirect_endpoint(self):
        """GET /t/{ref} 302 to /forum/?view=topic&id=<topicId>, case-insensitive, 404."""
        expected_fb_target = f"/forum/?view=topic&id={self.fb041_topic_id}"
        expected_work_target = f"/forum/?view=topic&id={self.work_topic_id}"

        # 1. /t/FB-041
        code, loc = self._request_raw_redirect("/t/FB-041")
        self.assertEqual(code, 302)
        self.assertEqual(loc, expected_fb_target)

        # 2. /t/fb-041 (case-insensitive) -> same destination
        code, loc_lower = self._request_raw_redirect("/t/fb-041")
        self.assertEqual(code, 302)
        self.assertEqual(loc_lower, expected_fb_target)

        # 3. /t/<workId>
        code, loc_work = self._request_raw_redirect(f"/t/{self.work_id}")
        self.assertEqual(code, 302)
        self.assertEqual(loc_work, expected_work_target)

        # 4. /t/<topicId>
        code, loc_topic = self._request_raw_redirect(f"/t/{self.work_topic_id}")
        self.assertEqual(code, 302)
        self.assertEqual(loc_topic, expected_work_target)

        # 5. Nonexistent ref -> 404
        code, _ = self._request_raw_redirect("/t/nonexistent_ref_123456")
        self.assertEqual(code, 404)

    def test_get_endpoints_do_not_write_database(self):
        """7. GET /api/boot and post GET endpoints do not write to database."""
        conn = self.db.get_conn()
        topics_count_before = conn.execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0]
        curation_count_before = conn.execute("SELECT COUNT(*) FROM curation_resource_topics").fetchone()[0]

        # Call GET endpoints
        self._request("GET", "/api/boot")
        self._request("GET", "/api/posts/by-ref/style/FB-041")
        self._request("GET", f"/api/posts/{self.fb041_topic_id}")
        self._request("GET", f"/api/posts/{self.fb041_topic_id}/replies")
        self._request_raw_redirect("/t/FB-041")

        topics_count_after = conn.execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0]
        curation_count_after = conn.execute("SELECT COUNT(*) FROM curation_resource_topics").fetchone()[0]

        self.assertEqual(topics_count_before, topics_count_after, "GET endpoints must never write to forum_topics")
        self.assertEqual(curation_count_before, curation_count_after, "GET endpoints must never write to curation_resource_topics")

    def test_j1_paid_style_definition_protection(self):
        """J1: Paid style definition is hidden from anon/unpaid, visible to unlocked/author/admin."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        conn.execute(
            """
            INSERT INTO catalog_assets (code, kind, name, description, image_url, definition, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('PAID-STYLE-1', 'style', '付费画风', '测试付费画风', '/img/paid.webp', 'SUPER_SECRET_STYLE_DEFINITION', 'pr_author', '作者', 'community', 'published', 25, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.commit()

        # Ensure discussion topic exists
        topic_id = resource_discussions.ensure_topic(
            conn, "style", "PAID-STYLE-1", {"name": "付费画风", "source_type": "community", "author_username": "pr_author"}
        )
        conn.commit()

        # 1. Anonymous request: definition is hidden
        status, data_anon = self._request("GET", f"/api/posts/{topic_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data_anon["mount"]["resource"]["definition"], "", "Anonymous cannot see paid definition")
        self.assertFalse(data_anon["mount"]["resource"]["unlocked"])

        # 2. Ordinary user (pr_reader) who hasn't unlocked: definition is hidden
        reader_token = self._login("pr_reader", "pass-reader")
        status, data_reader = self._request("GET", f"/api/posts/{topic_id}", token=reader_token)
        self.assertEqual(status, 200)
        self.assertEqual(data_reader["mount"]["resource"]["definition"], "", "Unpaid user cannot see paid definition")
        self.assertFalse(data_reader["mount"]["resource"]["unlocked"])

        # 3. User with settled unlock record: definition is visible
        buyer_token = self._login("pr_buyer", "pass-buyer")
        conn.execute(
            "INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at) VALUES (?, 'asset', 'PAID-STYLE-1', 25, 'settled', ?)",
            (self.buyer["id"], now),
        )
        conn.commit()
        status, data_buyer = self._request("GET", f"/api/posts/{topic_id}", token=buyer_token)
        self.assertEqual(status, 200)
        self.assertEqual(data_buyer["mount"]["resource"]["definition"], "SUPER_SECRET_STYLE_DEFINITION")
        self.assertTrue(data_buyer["mount"]["resource"]["unlocked"])

        # 4. Author request: definition is visible
        author_token = self._login("pr_author", "pass-author")
        status, data_author = self._request("GET", f"/api/posts/{topic_id}", token=author_token)
        self.assertEqual(status, 200)
        self.assertEqual(data_author["mount"]["resource"]["definition"], "SUPER_SECRET_STYLE_DEFINITION")
        self.assertTrue(data_author["mount"]["resource"]["unlocked"])

        # 5. Admin request: definition is visible
        admin_token = self._login("pr_admin", "pass-admin")
        status, data_admin = self._request("GET", f"/api/posts/{topic_id}", token=admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(data_admin["mount"]["resource"]["definition"], "SUPER_SECRET_STYLE_DEFINITION")
        self.assertTrue(data_admin["mount"]["resource"]["unlocked"])

    def test_j9_detail_full_topic_payload(self):
        """J9: GET /api/posts/{topicId} returns serialized topic with summary, images, styles."""
        status, data = self._request("GET", f"/api/posts/{self.fb041_topic_id}")
        self.assertEqual(status, 200)
        topic = data["topic"]
        self.assertIn("summary", topic)
        self.assertIn("images", topic)
        self.assertIn("styles", topic)
        self.assertIn("category", topic)
        self.assertEqual(topic["status"], "published")

    def test_j10_style_viewer_liked_and_favorited(self):
        """J10: Style likes and collections correctly reflect in viewer state."""
        reader_token = self._login("pr_reader", "pass-reader")
        toggle_user_like(self.db, self.reader, "style", "FB-041")
        toggle_user_collection(self.db, self.reader, "styles", "FB-041")

        status, data = self._request("GET", f"/api/posts/{self.fb041_topic_id}", token=reader_token)
        self.assertEqual(status, 200)
        self.assertTrue(data["viewer"]["liked"])
        self.assertTrue(data["viewer"]["favorited"])

    def test_j11_cursor_base64_validation(self):
        """J11 & K9: Invalid cursor format, field types, malformed base64, or mismatched topicId returns 400 invalid_cursor."""
        topic_id = self.fb041_topic_id

        # 1. Plain non-base64 or malformed cursor
        status, err1 = self._request("GET", f"/api/posts/{topic_id}/replies?cursor=not-a-valid-cursor!!")
        self.assertEqual(status, 400)
        self.assertEqual(err1.get("error"), "invalid_cursor")

        # 2. Base64 encoded JSON but for a different topicId
        wrong_payload = {"created_at": "2026-01-01T00:00:00Z", "id": "reply_1", "topicId": "other_topic_id"}
        wrong_cursor = base64.urlsafe_b64encode(json.dumps(wrong_payload).encode("utf-8")).decode("ascii")
        status, err2 = self._request("GET", f"/api/posts/{topic_id}/replies?cursor={wrong_cursor}")
        self.assertEqual(status, 400)
        self.assertEqual(err2.get("error"), "invalid_cursor")

        # 3. K9: Invalid field types (created_at is list, id is dict)
        type_err_payload = {"created_at": ["2026-01-01T00:00:00Z"], "id": "reply_1", "topicId": topic_id}
        cur3 = base64.urlsafe_b64encode(json.dumps(type_err_payload).encode("utf-8")).decode("ascii")
        status, err3 = self._request("GET", f"/api/posts/{topic_id}/replies?cursor={cur3}")
        self.assertEqual(status, 400)
        self.assertEqual(err3.get("error"), "invalid_cursor")

        # 4. K9: created_at format not matching ISO timestamp
        bad_date_payload = {"created_at": "not-a-date", "id": "reply_1", "topicId": topic_id}
        cur4 = base64.urlsafe_b64encode(json.dumps(bad_date_payload).encode("utf-8")).decode("ascii")
        status, err4 = self._request("GET", f"/api/posts/{topic_id}/replies?cursor={cur4}")
        self.assertEqual(status, 400)
        self.assertEqual(err4.get("error"), "invalid_cursor")

    def test_k1_work_detail_visibility_and_demo_filtering(self):
        """K1: Work detail endpoint checks resolve_resource; returns 404 on hidden/paused/deleted and demo works."""
        conn = self.db.get_conn()

        # 1. Hidden work
        conn.execute("UPDATE works SET status = 'hidden' WHERE id = ?", (self.work_id,))
        conn.commit()
        try:
            status, _ = self._request("GET", f"/api/posts/{self.work_topic_id}")
            self.assertEqual(status, 404, "Hidden work must 404 on detail")
        finally:
            conn.execute("UPDATE works SET status = 'published' WHERE id = ?", (self.work_id,))
            conn.commit()

        # 2. Paused work
        conn.execute("UPDATE works SET status = 'paused' WHERE id = ?", (self.work_id,))
        conn.commit()
        try:
            status, _ = self._request("GET", f"/api/posts/{self.work_topic_id}")
            self.assertEqual(status, 404, "Paused work must 404 on detail")
        finally:
            conn.execute("UPDATE works SET status = 'published' WHERE id = ?", (self.work_id,))
            conn.commit()

        # 3. Deleted work
        conn.execute("UPDATE works SET status = 'deleted' WHERE id = ?", (self.work_id,))
        conn.commit()
        try:
            status, _ = self._request("GET", f"/api/posts/{self.work_topic_id}")
            self.assertEqual(status, 404, "Deleted work must 404 on detail")
        finally:
            conn.execute("UPDATE works SET status = 'published' WHERE id = ?", (self.work_id,))
            conn.commit()

        # 4. Demo work work_104 in non-demo mode
        demo_t = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = 'work_104'").fetchone()
        if demo_t:
            status, _ = self._request("GET", f"/api/posts/{demo_t['topic_id']}")
            self.assertEqual(status, 404, "Demo work must 404 when demo mode is off")

    def test_k8_work_detail_counters(self):
        """K8: Work topic likes/favorites match works table; mount.work includes likes, favorites, forks."""
        conn = self.db.get_conn()
        conn.execute("UPDATE works SET likes = 8, favorites = 5, forks = 3 WHERE id = ?", (self.work_id,))
        conn.commit()

        status, data = self._request("GET", f"/api/posts/{self.work_topic_id}")
        self.assertEqual(status, 200)

        # Topic level counters
        self.assertEqual(data["topic"]["likes"], 8)
        self.assertEqual(data["topic"]["favorites"], 5)
        self.assertEqual(data["topic"]["workId"], self.work_id)

        # Mount work level counters
        work_mount = data["mount"]["work"]
        self.assertEqual(work_mount["likes"], 8)
        self.assertEqual(work_mount["favorites"], 5)
        self.assertEqual(work_mount["forks"], 3)

    def test_j6_demo_visibility_consistency(self):
        """J6: Demo topic without demo mode returns 404 on both detail endpoint and /t/ redirect."""
        # topic_201 is a seed demo topic
        status, _ = self._request("GET", "/api/posts/topic_201")
        self.assertEqual(status, 404)

        code, _ = self._request_raw_redirect("/t/topic_201")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
