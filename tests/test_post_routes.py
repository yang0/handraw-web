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
    ServiceError,
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
        cls._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test", "HANDRAW_DEMO_MODE": "1"})
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

        # Publish work with price > 0 must be rejected
        try:
            publish_user_work(
                cls.db,
                cls.author,
                {"title": "收费作品", "prompt": "绝密付费提示词", "images": [IMG], "styles": ["FA-013"], "price": 10},
            )
            raise AssertionError("Setting work price must be rejected with 400")
        except ServiceError as e:
            assert e.status == 400
            assert e.code == "work_price_not_allowed"

        # Publish a free work (formerly paid work in legacy tests)
        pub_paid = publish_user_work(
            cls.db,
            cls.author,
            {"title": "作品2", "prompt": "绝密付费提示词", "images": [IMG], "styles": ["FA-013"], "price": 0},
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

        # 3. Work is free: prompt is immediately visible anonymously and for logged in user; unlock returns 400
        # Anonymous viewer: prompt is visible
        status, data_paid_anon = self._request("GET", f"/api/posts/{self.paid_topic_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data_paid_anon["mount"]["work"]["prompt"], "绝密付费提示词")

        buyer_token = self._login("pr_buyer", "pass-buyer")
        status, data_paid_unlocked = self._request(
            "GET", f"/api/posts/{self.paid_topic_id}", token=buyer_token
        )
        self.assertEqual(status, 200)
        self.assertEqual(data_paid_unlocked["mount"]["work"]["prompt"], "绝密付费提示词")

        # Unlock work by buyer is rejected with 400 without deducting credits
        with self.assertRaises(ServiceError) as cm:
            unlock_paid_item(self.db, self.buyer, "work", self.paid_work_id)
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_not_unlockable")

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

    def test_t_redirect_fallback_to_standalone_asset(self):
        """When style/layout has no mapped topic, /t/{ref} creates topic on-demand and 302s to /forum/?view=topic&id=<TID>."""
        conn = self.db.get_conn()
        saved = [
            dict(r)
            for r in conn.execute(
                "SELECT kind, target_id, topic_id, origin, created_at FROM curation_resource_topics WHERE UPPER(target_id) IN ('FA-001', 'SC-021')"
            ).fetchall()
        ]
        try:
            conn.execute("DELETE FROM curation_resource_topics WHERE UPPER(target_id) IN ('FA-001', 'SC-021')")
            conn.commit()

            # 1. Plain style code creates topic on-demand
            code, loc = self._request_raw_redirect("/t/FA-001")
            self.assertEqual(code, 302)
            self.assertTrue(loc.startswith("/forum/?view=topic&id=topic_"))
            fa_tid = loc.split("id=")[1].split("&")[0]

            # 2. Semantic prefix style- reuses the newly created topic
            code, loc = self._request_raw_redirect("/t/style-FA-001")
            self.assertEqual(code, 302)
            self.assertEqual(loc, f"/forum/?view=topic&id={fa_tid}")

            # 3. Plain layout code creates topic on-demand
            code, loc = self._request_raw_redirect("/t/SC-021")
            self.assertEqual(code, 302)
            self.assertTrue(loc.startswith("/forum/?view=topic&id=topic_"))
            sc_tid = loc.split("id=")[1].split("&")[0]

            # 4. Semantic prefix layout- reuses newly created topic
            code, loc = self._request_raw_redirect("/t/layout-SC-021")
            self.assertEqual(code, 302)
            self.assertEqual(loc, f"/forum/?view=topic&id={sc_tid}")

            # 5. With focus=comment preserved
            code, loc = self._request_raw_redirect("/t/FA-001?focus=comment")
            self.assertEqual(code, 302)
            self.assertEqual(loc, f"/forum/?view=topic&id={fa_tid}&focus=comment")

            # 6. Truly nonexistent resource -> 404
            code, _ = self._request_raw_redirect("/t/nonexistent_ref_999999")
            self.assertEqual(code, 404)
        finally:
            conn.execute("DELETE FROM curation_resource_topics WHERE UPPER(target_id) IN ('FA-001', 'SC-021')")
            for r in saved:
                conn.execute(
                    "INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES (?, ?, ?, ?, ?)",
                    (r["kind"], r["target_id"], r["topic_id"], r["origin"], r["created_at"]),
                )
            conn.commit()

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

        # 3. User with settled unlock record: paid definition is not shown to buyers (only usable online)
        buyer_token = self._login("pr_buyer", "pass-buyer")
        conn.execute(
            "INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at) VALUES (?, 'asset', 'PAID-STYLE-1', 25, 'settled', ?)",
            (self.buyer["id"], now),
        )
        conn.commit()
        status, data_buyer = self._request("GET", f"/api/posts/{topic_id}", token=buyer_token)
        self.assertEqual(status, 200)
        self.assertEqual(data_buyer["mount"]["resource"]["definition"], "")
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

    def test_author_exempt_from_paying_own_paid_work_and_asset(self):
        """Author is exempted from unlock costs when unlocking/using their own paid work or asset."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO catalog_assets (code, kind, name, description, image_url, definition, author_username, author_name, source_type, status, unlock_cost, published_at_ms, created_at, updated_at)
            VALUES ('PAID-STYLE-AUTH', 'style', '作者付费画风', '测试', '/img/paid.webp', 'AUTH_SECRET_STYLE_DEF', 'pr_author', '作者', 'community', 'published', 25, 1000, ?, ?)
            """,
            (now, now),
        )
        conn.commit()

        author_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])

        # 1. Author attempts to unlock work -> rejected with 400 without changing balance
        with self.assertRaises(ServiceError) as cm:
            unlock_paid_item(self.db, self.author, "work", self.paid_work_id)
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.code, "work_not_unlockable")

        # Balance remains unchanged
        author_bal_mid = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])
        self.assertEqual(author_bal_mid, author_bal_before, "Author balance must not change on work unlock request")

        # 2. Author unlocks their own paid style asset (unlock_cost = 25)
        res_asset = unlock_paid_item(self.db, self.author, "asset", "PAID-STYLE-AUTH")
        self.assertTrue(res_asset.get("ok"))
        self.assertTrue(res_asset.get("alreadyUnlocked"), "Author should be recognized as already unlocked for their own style asset")

        # Balance remains unchanged
        author_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.author["id"],)).fetchone()["balance"])
        self.assertEqual(author_bal_after, author_bal_before, "Author must not be charged points for their own paid asset")

        # 3. In Studio generation, author canUse is True without prior purchase
        from backend import resource_registry
        res = resource_registry.resolve(conn, "PAID-STYLE-AUTH", viewer=self.author, purpose="generate")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("canUse"), "Author can use own paid style directly in Studio without unlocking")
        self.assertIsNone((res.get("access") or {}).get("hiddenBy"), "Author access not hiddenBy locked")

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
            # Runtime demo access is captured on the HTTP server instance.
            with patch.object(self.server, "allow_demo_routes", False), patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}):
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
        # topic_201 is a seed demo topic. A live server captures the demo
        # switch at creation, so disable it on that instance for this request.
        with patch.object(self.server, "allow_demo_routes", False), patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}):
            status, _ = self._request("GET", "/api/posts/topic_201")
            self.assertEqual(status, 404)

            code, _ = self._request_raw_redirect("/t/topic_201")
            self.assertEqual(code, 404)

    def test_r1_catalog_assets_and_admin_save_ensure_topic(self):
        """R1: catalog_assets (exclusive & community) mapped by ensure_resource_topics;
        admin_upsert_catalog_asset automatically creates topic mapping in same transaction;
        repeat run of ensure_resource_topics is idempotent."""
        conn = self.db.get_conn()
        now = "2026-10-31T06:00:00Z"

        # 1. Insert published exclusive and community assets
        conn.execute(
            """INSERT OR REPLACE INTO catalog_assets (code, kind, name, status, source_type, author_username, image_url, published_at_ms, created_at, updated_at)
               VALUES ('FX-001', 'style', '独家画风FX', 'published', 'exclusive', 'official', '/fx.png', 1700000000000, ?, ?)""",
            (now, now)
        )
        conn.execute(
            """INSERT OR REPLACE INTO catalog_assets (code, kind, name, status, source_type, author_username, image_url, published_at_ms, created_at, updated_at)
               VALUES ('USR-L02', 'layout', '社区图型L02', 'published', 'community', 'pr_author', '/l02.png', 1700000000000, ?, ?)""",
            (now, now)
        )
        conn.commit()

        # Run ensure_resource_topics --apply
        ensure_resource_topics.main(["--db", str(self.db_path), "--apply"])

        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "1"}):
            # Check by-ref and /t/ for FX-001
            status, data = self._request("GET", "/api/posts/by-ref/style/FX-001")
            self.assertEqual(status, 200, f"Expected 200 for FX-001 by-ref, got {status}: {data}")
            self.assertTrue(data.get("ok"))
            fx_topic_id = data["topicId"]

            code, loc = self._request_raw_redirect("/t/FX-001")
            self.assertEqual(code, 302)
            self.assertEqual(loc, f"/forum/?view=topic&id={fx_topic_id}")

            # Check by-ref and /t/ for USR-L02
            status, data = self._request("GET", "/api/posts/by-ref/layout/USR-L02")
            self.assertEqual(status, 200, f"Expected 200 for USR-L02 by-ref, got {status}: {data}")
            self.assertTrue(data.get("ok"))
            usr_topic_id = data["topicId"]

            code, loc = self._request_raw_redirect("/t/USR-L02")
            self.assertEqual(code, 302)
            self.assertEqual(loc, f"/forum/?view=topic&id={usr_topic_id}")

            # 2. Check admin_upsert_catalog_asset auto-creation in same transaction
            from backend.admin_services import admin_upsert_catalog_asset
            admin_user = dict(conn.execute("SELECT * FROM users WHERE username = 'pr_admin'").fetchone())
            res = admin_upsert_catalog_asset(
                self.db,
                admin_user,
                {
                    "kind": "style",
                    "name": "后台直接发布的独家画风",
                    "status": "published",
                    "sourceType": "exclusive",
                }
            )
            new_code = res["code"]
            # Immediately accessible via by-ref without needing to run ensure_resource_topics
            status, data = self._request("GET", f"/api/posts/by-ref/style/{new_code}")
            self.assertEqual(status, 200, f"admin_upsert_catalog_asset should have ensured topic: {data}")
            self.assertTrue(data.get("ok"))

            # 3. Repeat run idempotency
            count_before = conn.execute("SELECT count(*) as cnt FROM curation_resource_topics").fetchone()["cnt"]
            ensure_resource_topics.main(["--db", str(self.db_path), "--apply"])
            count_after = conn.execute("SELECT count(*) as cnt FROM curation_resource_topics").fetchone()["cnt"]
            self.assertEqual(count_before, count_after, "Repeat run must not create duplicate topics")

    def test_r8_focus_comment_redirect(self):
        """R8: /t/{id}?focus=comment preserves focus query parameter on 302 redirect, and discards unwhitelisted query params."""
        # 1. Whitelisted focus=comment is preserved
        code, loc = self._request_raw_redirect("/t/FB-041?focus=comment")
        self.assertEqual(code, 302)
        self.assertEqual(loc, f"/forum/?view=topic&id={self.fb041_topic_id}&focus=comment")

        # 2. Unwhitelisted parameters are dropped
        code, loc2 = self._request_raw_redirect("/t/FB-041?focus=comment&hack=1&random=param")
        self.assertEqual(code, 302)
        self.assertEqual(loc2, f"/forum/?view=topic&id={self.fb041_topic_id}&focus=comment")

    def test_u1_resource_post_counters_match_boot_and_increment(self):
        """U1/W1: GET /api/posts/{id} returns resource likes and favorites matching boot payload per shared.js rules across demo on/off, with/without seed, case differences, and verifies delta=1 on like."""
        conn = self.db.get_conn()

        def calc_shared_counts(boot_payload: dict, code: str) -> tuple[int, int]:
            clean = (code or "").strip().upper().lstrip("#")
            seed = (boot_payload.get("assetSeedMetrics") or {}).get(clean) or {}
            base_l = int(seed.get("likes") or 0)
            base_f = int(seed.get("favorites") or 0)
            live_l = int((boot_payload.get("assetLiveLikes") or {}).get(clean) or 0)
            live_f = int((boot_payload.get("assetLiveFavorites") or {}).get(clean) or 0)
            return max(0, base_l + live_l), max(0, base_f + live_f)

        fb_tid = self.fb041_topic_id
        sc_row = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'layout' AND target_id = 'SC-021'").fetchone()
        self.assertIsNotNone(sc_row, "SC-021 should have an ensured topic")
        sc_tid = str(sc_row["topic_id"])

        # Setup test data:
        # FB-041: ensure seed exists in asset_social_seeds
        conn.execute("INSERT OR REPLACE INTO asset_social_seeds (asset_code, base_likes, base_favorites) VALUES ('FB-041', 5, 2)")
        # SC-021: ensure NO seed exists in asset_social_seeds
        conn.execute("DELETE FROM asset_social_seeds WHERE asset_code = 'SC-021'")
        # Insert lowercase target_id interaction & collection records for FB-041 (must NOT be counted)
        conn.execute("DELETE FROM interactions WHERE target_id IN ('FB-041', 'fb-041')")
        conn.execute("DELETE FROM collections WHERE target_id IN ('FB-041', 'fb-041')")
        conn.execute(
            "INSERT INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, 'like_style', 'fb-041', '', '2026-01-01T00:00:00Z')",
            (self.author["id"],),
        )
        conn.execute(
            "INSERT INTO collections (user_id, bucket, target_id, created_at) VALUES (?, 'styles', 'fb-041', '2026-01-01T00:00:00Z')",
            (self.author["id"],),
        )
        # Insert uppercase live interaction for FB-041
        conn.execute(
            "INSERT INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, 'like_style', 'FB-041', '', '2026-01-01T00:00:00Z')",
            (self.buyer["id"],),
        )
        conn.commit()

        try:
            for demo_flag in ["1", "0"]:
                with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": demo_flag}):
                    boot = services.build_boot_payload(self.db, None)

                    # 1. FB-041 (seed exists in demo; 1 uppercase live like; lowercase ignored)
                    exp_fb_likes, exp_fb_favs = calc_shared_counts(boot, "FB-041")
                    status_fb, data_fb = self._request("GET", f"/api/posts/{fb_tid}")
                    self.assertEqual(status_fb, 200)
                    mount_fb = data_fb.get("mount", {}).get("resource", {})
                    self.assertEqual(mount_fb.get("likes"), exp_fb_likes)
                    self.assertEqual(mount_fb.get("favorites"), exp_fb_favs)
                    self.assertEqual(data_fb.get("topic", {}).get("likes"), exp_fb_likes)
                    self.assertEqual(data_fb.get("topic", {}).get("favorites"), exp_fb_favs)

                    # 2. SC-021 (no seed; baseline is 0)
                    exp_sc_likes, exp_sc_favs = calc_shared_counts(boot, "SC-021")
                    status_sc, data_sc = self._request("GET", f"/api/posts/{sc_tid}")
                    self.assertEqual(status_sc, 200)
                    mount_sc = data_sc.get("mount", {}).get("resource", {})
                    self.assertEqual(mount_sc.get("likes"), exp_sc_likes)
                    self.assertEqual(mount_sc.get("favorites"), exp_sc_favs)
                    self.assertEqual(data_sc.get("topic", {}).get("likes"), exp_sc_likes)
                    self.assertEqual(data_sc.get("topic", {}).get("favorites"), exp_sc_favs)

            # 3. Verify detail count difference before and after like is exactly 1
            with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "1"}):
                _, before_data = self._request("GET", f"/api/posts/{fb_tid}")
                likes_before = before_data["mount"]["resource"]["likes"]

                u_liker, _ = register_user(self.db, f"u1_liker_{int(time.time() * 1000)}", "PassU1_123!")
                services.toggle_user_like(self.db, u_liker, "style", "FB-041")

                _, after_data = self._request("GET", f"/api/posts/{fb_tid}")
                likes_after = after_data["mount"]["resource"]["likes"]
                self.assertEqual(likes_after - likes_before, 1, "Detail likes count delta must be exactly 1 after liking")

                boot_after = services.build_boot_payload(self.db, None)
                exp_after_likes, _ = calc_shared_counts(boot_after, "FB-041")
                self.assertEqual(likes_after, exp_after_likes, "Detail likes after liking must match boot per shared.js rules")
        finally:
            conn.execute("DELETE FROM interactions WHERE target_id IN ('FB-041', 'fb-041')")
            conn.execute("DELETE FROM collections WHERE target_id IN ('FB-041', 'fb-041')")
            conn.commit()

    def test_official_and_community_asset_tips(self):
        """Test Issue #24: Official resource tipping with designated payee, ledgers distinction, and rejection when payee missing."""
        conn = self.db.get_conn()
        now_ts = int(time.time() * 1000)

        # 1. Create test users: tipper (alice), payee superadmin (admin_payee), community creator (bob)
        u_tipper, _ = register_user(self.db, f"tipper_{now_ts}", "Pass1234!")
        u_payee, _ = register_user(self.db, f"admin_payee_{now_ts}", "Pass1234!")
        u_bob, _ = register_user(self.db, f"bob_creator_{now_ts}", "Pass1234!")

        tipper_uid = int(u_tipper["id"])
        payee_uid = int(u_payee["id"])
        payee_username = u_payee["username"]

        try:
            # Ensure official_tip_payee is EMPTY initially
            conn.execute(
                "INSERT OR REPLACE INTO site_settings (key, value_json, updated_by, updated_at) VALUES ('economy', json_object('official_tip_payee', ''), 'system', '2026-11-01T00:00:00Z')"
            )
            conn.commit()

            # A. Tipping official asset (FA-002) with NO payee configured -> rejects with 400 '官方资源赞赏暂未开放'
            tipper_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tipper_uid,)).fetchone()["balance"])
            with self.assertRaises(services.ServiceError) as cm:
                services.send_encourage_tip(self.db, u_tipper, "asset", "FA-002", amount=2)
            self.assertEqual(cm.exception.status, 400)
            self.assertEqual(cm.exception.code, "official_tips_disabled")
            self.assertIn("官方资源赞赏暂未开放", str(cm.exception))
            # Ensure tipper balance was NOT deducted
            tipper_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tipper_uid,)).fetchone()["balance"])
            self.assertEqual(tipper_bal_before, tipper_bal_after, "Balance must not change when payee is unconfigured")

            # B. Configure non-existent payee username
            conn.execute(
                "INSERT OR REPLACE INTO site_settings (key, value_json, updated_by, updated_at) VALUES ('economy', json_object('official_tip_payee', 'nonexistent_user_999'), 'system', '2026-11-01T00:00:00Z')"
            )
            conn.commit()
            with self.assertRaises(services.ServiceError) as cm:
                services.send_encourage_tip(self.db, u_tipper, "asset", "FA-002", amount=2)
            self.assertEqual(cm.exception.status, 400)
            self.assertEqual(cm.exception.code, "official_tips_disabled")

            # C. Configure inactive payee (status != 'active')
            conn.execute("UPDATE users SET status = 'suspended' WHERE id = ?", (payee_uid,))
            conn.execute(
                "INSERT OR REPLACE INTO site_settings (key, value_json, updated_by, updated_at) VALUES ('economy', json_object('official_tip_payee', ?), 'system', '2026-11-01T00:00:00Z')",
                (payee_username,),
            )
            conn.commit()
            with self.assertRaises(services.ServiceError) as cm:
                services.send_encourage_tip(self.db, u_tipper, "asset", "FA-002", amount=2)
            self.assertEqual(cm.exception.status, 400)
            self.assertEqual(cm.exception.code, "official_tips_disabled")

            # D. Activate payee -> Tipping official asset succeeds!
            conn.execute("UPDATE users SET status = 'active' WHERE id = ?", (payee_uid,))
            conn.commit()
            payee_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (payee_uid,)).fetchone()["balance"])

            tip_res = services.send_encourage_tip(self.db, u_tipper, "asset", "FA-002", amount=2)
            self.assertTrue(tip_res["ok"])
            self.assertEqual(tip_res["credits"], tipper_bal_before - 2)

            # Payee balance increased by 2
            payee_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (payee_uid,)).fetchone()["balance"])
            self.assertEqual(payee_bal_after, payee_bal_before + 2)

            # Check ledger entries: kind is tip_official_out and tip_official_in
            tipper_ledger = conn.execute(
                "SELECT kind, delta, ref_type, ref_id FROM ledgers WHERE user_id = ? AND ref_type = 'asset' AND ref_id = 'FA-002' ORDER BY id DESC LIMIT 1",
                (tipper_uid,),
            ).fetchone()
            self.assertEqual(tipper_ledger["kind"], "tip_official_out")
            self.assertEqual(int(tipper_ledger["delta"]), -2)
            self.assertEqual(tipper_ledger["ref_id"], "FA-002")

            payee_ledger = conn.execute(
                "SELECT kind, delta, ref_type, ref_id FROM ledgers WHERE user_id = ? AND ref_type = 'asset' AND ref_id = 'FA-002' ORDER BY id DESC LIMIT 1",
                (payee_uid,),
            ).fetchone()
            self.assertEqual(payee_ledger["kind"], "tip_official_in")
            self.assertEqual(int(payee_ledger["delta"]), 2)
            self.assertEqual(payee_ledger["ref_id"], "FA-002")

            # Check interactions table: has record with target_id='FA-002'
            inter = conn.execute(
                "SELECT * FROM interactions WHERE user_id = ? AND target_type = 'asset' AND target_id = 'FA-002'",
                (tipper_uid,),
            ).fetchone()
            self.assertIsNotNone(inter)

            # Check /t/FA-002 topic endpoint: res_tips aggregates from ledgers
            _, fa_loc = self._request_raw_redirect("/t/FA-002")
            fa_tid = fa_loc.split("id=")[1].split("&")[0]
            status, detail = self._request("GET", f"/api/posts/{fa_tid}")
            self.assertEqual(status, 200)
            self.assertEqual(detail["mount"]["resource"]["tips"], 2)

            # E. Payee cannot tip their own managed official resource
            with self.assertRaises(services.ServiceError) as cm:
                services.send_encourage_tip(self.db, u_payee, "asset", "FA-002", amount=2)
            self.assertEqual(cm.exception.status, 400)
            self.assertIn("不能赞赏自己管理的官方资源", str(cm.exception))

            # F. Community resource behavior remains unchanged (tip_out -> tip_in)
            conn.execute(
                """INSERT INTO catalog_assets (code, kind, name, status, source_type, author_username, author_name, image_url, published_at_ms, created_at, updated_at)
                   VALUES ('USR-TEST-01', 'style', 'Bob Style', 'published', 'community', ?, 'Bob', '/img.png', 1700000000000, '2026-11-01', '2026-11-01')""",
                (u_bob["username"],)
            )
            conn.commit()

            # Bob cannot tip own resource
            with self.assertRaises(services.ServiceError) as cm:
                services.send_encourage_tip(self.db, u_bob, "asset", "USR-TEST-01", amount=2)
            self.assertEqual(cm.exception.status, 400)
            self.assertIn("不能给自己赞赏积分哦", str(cm.exception))

            # Tipper tips Bob's resource
            bob_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (int(u_bob["id"]),)).fetchone()["balance"])
            c_tip_res = services.send_encourage_tip(self.db, u_tipper, "asset", "USR-TEST-01", amount=2)
            self.assertTrue(c_tip_res["ok"])

            # Bob's balance increased by 2
            bob_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (int(u_bob["id"]),)).fetchone()["balance"])
            self.assertEqual(bob_bal_after, bob_bal_before + 2)

            # Check ledger kind is standard tip_out and tip_in (not tip_official)
            bob_ledger = conn.execute(
                "SELECT kind, delta FROM ledgers WHERE user_id = ? AND ref_type = 'asset' AND ref_id = 'USR-TEST-01' ORDER BY id DESC LIMIT 1",
                (int(u_bob["id"]),),
            ).fetchone()
            self.assertEqual(bob_ledger["kind"], "tip_in")
            self.assertEqual(int(bob_ledger["delta"]), 2)
        finally:
            conn.execute("DELETE FROM site_settings WHERE key = 'economy'")
            conn.execute("DELETE FROM catalog_assets WHERE code = 'USR-TEST-01'")
            conn.execute("DELETE FROM ledgers WHERE ref_id IN ('FA-002', 'USR-TEST-01')")
            conn.execute("DELETE FROM interactions WHERE target_id IN ('FA-002', 'USR-TEST-01')")
            conn.commit()

    def test_layout_topic_detail_definition_chinese_only(self):
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'layout' AND target_id = 'SB-001'"
        ).fetchone()
        self.assertIsNotNone(row, "Topic for SB-001 must exist")
        topic_id = str(row["topic_id"])

        status, payload = self._request("GET", f"/api/posts/{topic_id}")
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        mount = payload.get("mount") or {}
        self.assertEqual(mount.get("kind"), "layout")
        resource = mount.get("resource") or {}
        defn = resource.get("definition") or ""
        self.assertTrue(defn, "Layout SB-001 definition must not be empty")
        self.assertNotIn("<!-- en -->", defn)
        self.assertNotIn("<!--en-->", defn)
        self.assertNotIn("<!-- zh -->", defn)
        self.assertNotIn("<!--zh-->", defn)
        self.assertNotIn("Comic storyboard", defn)
        self.assertIn("漫画分镜", defn)

    def test_forum_paid_reading_flow(self):
        """Test forum paid reading post: price validation, divider validation, isolation, unlocking and royalty."""
        author_token = self._login("pr_author", "pass-author")
        buyer_token = self._login("pr_buyer", "pass-buyer")

        # 1. Price validation errors
        # Negative price
        status, payload = self._request(
            "POST",
            "/api/forum/topics",
            {
                "title": "非法负数价格帖子测试",
                "category": "experience",
                "publishMode": "paid",
                "price": -5,
                "bodyHtml": "<p>免费前序</p><div class=\"hw-paywall-divider\"></div><p>付费内容</p>",
            },
            token=author_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("0–100", payload.get("error", ""))

        # Price > 100
        status, payload = self._request(
            "POST",
            "/api/forum/topics",
            {
                "title": "非法超限价格帖子测试",
                "category": "experience",
                "publishMode": "paid",
                "price": 105,
                "bodyHtml": "<p>免费前序</p><div class=\"hw-paywall-divider\"></div><p>付费内容</p>",
            },
            token=author_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("0–100", payload.get("error", ""))

        # Non-integer price string
        status, payload = self._request(
            "POST",
            "/api/forum/topics",
            {
                "title": "非法非整数价格测试",
                "category": "experience",
                "publishMode": "paid",
                "price": "not_a_number",
                "bodyHtml": "<p>免费前序</p><div class=\"hw-paywall-divider\"></div><p>付费内容</p>",
            },
            token=author_token,
        )
        self.assertEqual(status, 400)

        # 2. Missing paywall divider validation
        status, payload = self._request(
            "POST",
            "/api/forum/topics",
            {
                "title": "缺少分界线的付费帖",
                "category": "experience",
                "publishMode": "paid",
                "price": 15,
                "bodyHtml": "<p>这里全是正文，但是完全没有插入分界线！</p>",
            },
            token=author_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("付费分界线", payload.get("error", ""))

        # 3. Missing paid content after divider validation
        status, payload = self._request(
            "POST",
            "/api/forum/topics",
            {
                "title": "分界线后无内容的付费帖",
                "category": "experience",
                "publishMode": "paid",
                "price": 15,
                "bodyHtml": "<p>前序免费公开内容</p><div class=\"hw-paywall-divider\"><span>分界线</span></div>",
            },
            token=author_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("收费正文", payload.get("error", ""))

        # 4. Valid paid post with custom price 15
        paid_body = (
            "<p>前序公开试读章节与背景介绍</p>"
            "<div class=\"hw-paywall-divider\" data-paywall-price=\"15\">"
            "<div class=\"hw-paywall-divider-pill\"><span class=\"hw-paywall-pill-text\">此处以下为 15✦ 专属核心交付章节</span></div>"
            "</div>"
            "<p>付费解锁后的绝密独家交付正文内容，深入讲解了提示词调优和模型微调秘籍。</p>"
        )
        status, payload = self._request(
            "POST",
            "/api/forum/topics",
            {
                "title": "15✦ 独家手绘风提示词工程进阶指南",
                "category": "experience",
                "publishMode": "paid",
                "price": 15,
                "summary": "<p>前序公开试读章节与背景介绍</p>",
                "bodyHtml": paid_body,
                "lockedBody": paid_body,
            },
            token=author_token,
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload.get("ok"))
        topic = payload.get("topic") or {}
        topic_id = topic.get("id")
        self.assertTrue(topic_id)
        self.assertEqual(topic.get("price"), 15)

        # 5. Anonymous view: cannot see lockedBody or paid content
        status, anon_payload = self._request("GET", f"/api/posts/{topic_id}")
        self.assertEqual(status, 200)
        anon_topic = anon_payload.get("topic") or {}
        self.assertEqual(anon_topic.get("price"), 15)
        self.assertEqual(anon_topic.get("lockedBody"), "")
        self.assertIn("前序公开试读", anon_topic.get("summary", ""))
        self.assertNotIn("绝密独家交付正文内容", anon_topic.get("summary", ""))

        # 6. Author view: author reads for free, full lockedBody visible
        status, author_payload = self._request("GET", f"/api/posts/{topic_id}", token=author_token)
        self.assertEqual(status, 200)
        author_topic = author_payload.get("topic") or {}
        self.assertIn("绝密独家交付正文内容", author_topic.get("lockedBody", ""))

        # 7. Buyer unlocks: balance deduction & author 80% revenue split
        conn = self.db.get_conn()
        buyer_uid = int(self.buyer["id"])
        author_uid = int(self.author["id"])
        buyer_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (buyer_uid,)).fetchone()["balance"])
        author_bal_before = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (author_uid,)).fetchone()["balance"])

        # Buyer views before unlock -> locked
        status, buyer_pre_payload = self._request("GET", f"/api/posts/{topic_id}", token=buyer_token)
        self.assertEqual((buyer_pre_payload.get("topic") or {}).get("lockedBody"), "")

        # Buyer unlocks topic
        status, unlock_res = self._request(
            "POST",
            "/api/unlocks",
            {"targetType": "topic", "targetId": topic_id},
            token=buyer_token,
        )
        self.assertEqual(status, 200, unlock_res)
        self.assertTrue(unlock_res.get("ok"))
        self.assertFalse(unlock_res.get("alreadyUnlocked", False))

        # Check wallet balances: buyer deducted 15, author credited 12 (80% of 15)
        buyer_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (buyer_uid,)).fetchone()["balance"])
        author_bal_after = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (author_uid,)).fetchone()["balance"])
        self.assertEqual(buyer_bal_after, buyer_bal_before - 15)
        self.assertEqual(author_bal_after, author_bal_before + 12)

        # Buyer views after unlock -> unlocked, lockedBody visible
        status, buyer_post_payload = self._request("GET", f"/api/posts/{topic_id}", token=buyer_token)
        buyer_topic = buyer_post_payload.get("topic") or {}
        self.assertIn("绝密独家交付正文内容", buyer_topic.get("lockedBody", ""))

        # 8. Duplicate unlock is idempotent: no double deduction
        status, dup_unlock_res = self._request(
            "POST",
            "/api/unlocks",
            {"targetType": "topic", "targetId": topic_id},
            token=buyer_token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(dup_unlock_res.get("alreadyUnlocked"))
        buyer_bal_dup = int(conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (buyer_uid,)).fetchone()["balance"])
        self.assertEqual(buyer_bal_dup, buyer_bal_after)


if __name__ == "__main__":
    unittest.main()
