"""Acceptance tests for work prompt codes and subject persistence.

Verifies:
1. _serialize_work returns subject with visibility identical to prompt (empty when masked/locked).
2. publish_work_direct accepts optional subject (<= 2000 chars) and writes to works.subject.
3. publish_work_direct rejects subject exceeding 2000 characters.
4. _publish_approved writes subject from submission payload into works.subject.
5. _normalise_item validates and preserves subject (rejecting > 2000 chars with 400).
6. When subject contains resource secret instructions while prompt does not:
   - works.prompt_has_secret is set to 1.
   - Boot, work detail, topic mounts, author edit, and curation views mask subject and prompt.
   - Zero secret leaks across all endpoints.
7. Author edit updates works.prompt_has_secret when subject is edited to contain secrets.
8. run_blackbox_backfill scans subject and marks works.prompt_has_secret = 1.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from backend import admin_services as A, curation as C, services as S
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler, init_database


class WorkPromptSubjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "test.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_PRIVATE_STORAGE": self.tmp.name,
                "HANDRAW_ALLOWED_ORIGINS": "http://127.0.0.1:3094,http://localhost:3094,http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE": "0",
            },
        )
        self.env.start()
        self.db = init_database(self.db_path)
        self.user, token = S.register_user(self.db, "alice", "alice-pass-123")
        self.reviewer, _ = S.register_user(self.db, "rev_a", "rev-pass-123")
        self.admin, token_admin = S.register_user(self.db, "admin_user", "admin-pass-123")
        self.stranger, token_stranger = S.register_user(self.db, "bob_stranger", "bob-pass-123")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role='admin' WHERE username='admin_user'")
        self.admin["role"] = "admin"

        self.cookie_user = f"{SESSION_COOKIE_NAME}={token}"
        self.cookie_stranger = f"{SESSION_COOKIE_NAME}={token_stranger}"
        self.cookie_admin = f"{SESSION_COOKIE_NAME}={token_admin}"

        self.secret = "BLACKBOX_SUBJECT_SECRET_INSTRUCTION_9999"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO catalog_assets (code, name, kind, source_type, tier, unlock_cost, image_url, author_username, status, secret_blackbox_prompt, published_at_ms, created_at, updated_at)
                VALUES ('FX-SECRET-SUBJ', '专属测试画风', 'style', 'exclusive', 'A', 0, '/images/secret.webp', 'alice', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (self.secret,),
            )

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def _req(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Content-Type": "application/json",
            "Origin": "http://trusted.test",
        }
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                return status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as he:
            raw = he.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"error": raw}
            return he.code, parsed

    def _req_text(
        self,
        method: str,
        path: str,
        cookie: str | None = None,
    ) -> tuple[int, str]:
        headers = {
            "Origin": "http://trusted.test",
        }
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(self.base + path, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as he:
            return he.code, he.read().decode("utf-8")

    def test_serialize_work_visibility_matches_prompt(self):
        # 1. Free work with subject
        pub = C.publish_work_direct(
            self.db,
            self.user,
            {
                "title": "公开作品",
                "prompt": "手绘风插画，雨中街角面馆",
                "subject": "雨中街角面馆，热气腾腾的一碗汤面",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FE-012"],
                "layout": "SC-021",
                "price": 0,
            },
        )
        wid = pub["workId"]
        with self.db.transaction() as tx:
            row = tx.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row["subject"], "雨中街角面馆，热气腾腾的一碗汤面")

        # Serialized for anonymous viewer (unlocked because price == 0)
        ser = S._serialize_work(row, {}, set(), None)
        self.assertFalse(ser["promptMasked"])
        self.assertEqual(ser["prompt"], "手绘风插画，雨中街角面馆")
        self.assertEqual(ser["subject"], "雨中街角面馆，热气腾腾的一碗汤面")

        # 2. Paid work (price = 5), serialized for stranger (locked)
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET price = 5 WHERE id = ?", (wid,))
            row = tx.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()

        ser_locked = S._serialize_work(row, {}, set(), None)
        self.assertTrue(ser_locked["promptMasked"])
        self.assertEqual(ser_locked["prompt"], "")
        self.assertEqual(ser_locked["subject"], "", "subject must be empty when work is locked")

        # Unlocked for author
        ser_author = S._serialize_work(row, {}, set(), self.user)
        self.assertFalse(ser_author["promptMasked"])
        self.assertEqual(ser_author["prompt"], "手绘风插画，雨中街角面馆")
        self.assertEqual(ser_author["subject"], "雨中街角面馆，热气腾腾的一碗汤面")

        # Unlocked via unlocked_set
        ser_unlocked = S._serialize_work(row, {}, {wid}, None)
        self.assertFalse(ser_unlocked["promptMasked"])
        self.assertEqual(ser_unlocked["prompt"], "手绘风插画，雨中街角面馆")
        self.assertEqual(ser_unlocked["subject"], "雨中街角面馆，热气腾腾的一碗汤面")

    def test_publish_work_direct_subject_validation_and_persistence(self):
        # Successful publish with subject
        pub = C.publish_work_direct(
            self.db,
            self.user,
            {
                "title": "带主题的作品",
                "prompt": "提示词全文",
                "subject": "独立主题内容",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
            },
        )
        wid = pub["workId"]
        with self.db.transaction() as tx:
            row = tx.execute("SELECT subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row["subject"], "独立主题内容")

        # Publish without subject defaults to empty string
        pub2 = C.publish_work_direct(
            self.db,
            self.user,
            {
                "title": "无主题作品",
                "prompt": "提示词全文2",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
            },
        )
        with self.db.transaction() as tx:
            row2 = tx.execute("SELECT subject FROM works WHERE id = ?", (pub2["workId"],)).fetchone()
            self.assertEqual(row2["subject"], "")

        # Oversized subject (> 2000 chars) raises subject_too_long
        with self.assertRaises(S.ServiceError) as ctx:
            C.publish_work_direct(
                self.db,
                self.user,
                {
                    "title": "超长主题作品",
                    "prompt": "提示词",
                    "subject": "A" * 2001,
                    "images": ["/images/individual/FA/FA-001.webp"],
                },
            )
        self.assertEqual(ctx.exception.code, "subject_too_long")

    def test_publish_approved_writes_subject_to_works(self):
        sub_id = "test-sub-1"
        target_id = "test-work-target-1"
        now_iso = S.utc_now_iso()
        sub = {
            "id": sub_id,
            "kind": "work",
            "owner_username": self.user["username"],
            "owner_user_id": self.user["id"],
            "target_id": target_id,
        }
        payload = {
            "kind": "work",
            "title": "审批收录作品",
            "prompt": "收录提示词",
            "subject": "收录独立主题",
            "images": ["/images/individual/FA/FA-001.webp"],
            "styles": ["FA-001"],
            "layout": "SC-021",
            "price": 0,
        }
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO curation_submissions (
                    id, topic_id, owner_username, owner_user_id, kind, target_id,
                    status, current_revision, request_id, created_at, updated_at
                ) VALUES (?, 'topic_test', ?, ?, 'work', ?, 'pending', 1, 'req-1', ?, ?)
                """,
                (sub_id, self.user["username"], self.user["id"], target_id, now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver-1', ?, 1, ?, ?)
                """,
                (sub_id, C.json.dumps(payload, ensure_ascii=False), now_iso),
            )
            res = C._publish_approved(tx, sub, 1)
            self.assertEqual(res["workId"], target_id)

            row = tx.execute("SELECT * FROM works WHERE id = ?", (target_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["subject"], "收录独立主题")
            self.assertEqual(row["prompt"], "收录提示词")

            # Revision update
            payload2 = dict(payload, title="审批收录作品（更新）", subject="收录独立主题（修订版）")
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver-2', ?, 2, ?, ?)
                """,
                (sub_id, C.json.dumps(payload2, ensure_ascii=False), now_iso),
            )
            C._publish_approved(tx, sub, 2)
            row_updated = tx.execute("SELECT * FROM works WHERE id = ?", (target_id,)).fetchone()
            self.assertEqual(row_updated["title"], "审批收录作品（更新）")
            self.assertEqual(row_updated["subject"], "收录独立主题（修订版）")

    def test_normalise_item_subject_validation(self):
        # 1. Normal length subject preserved
        norm = C._normalise_item("work", {"kind": "work", "title": "测试作品", "prompt": "测试提示词", "subject": "测试主题", "images": ["/images/demo.webp"]})
        self.assertEqual(norm["subject"], "测试主题")

        # 2. Oversized subject rejected with subject_too_long (status 400)
        with self.assertRaises(S.ServiceError) as ctx:
            C._normalise_item("work", {"kind": "work", "title": "测试作品", "prompt": "测试提示词", "subject": "S" * 2001, "images": ["/images/demo.webp"]})
        self.assertEqual(ctx.exception.code, "subject_too_long")
        self.assertEqual(ctx.exception.status, 400)

    def test_subject_contains_secret_marks_and_masks_across_endpoints(self):
        """When subject contains resource secret instructions while prompt does not:
        - works.prompt_has_secret is 1.
        - Boot, work detail, topic mounts, author edit, and curation views mask subject and prompt.
        - Zero secret leaks across all endpoints.
        """
        # Alice publishes a work where prompt has no secret, but subject does
        st_pub, r_pub = self._req(
            "POST",
            "/api/works",
            {
                "title": "作品含秘密主题",
                "prompt": "公开无秘密的普通提示词",
                "subject": f"主题文字中包含 {self.secret} 专属黑盒指令",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FX-SECRET-SUBJ"],
                "price": 0,
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_pub, 200)
        wid = r_pub["workId"]

        # 1. DB verification
        with self.db.transaction() as tx:
            row = tx.execute("SELECT prompt, prompt_has_secret, subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row["prompt_has_secret"], 1, "prompt_has_secret must be 1 when subject contains secret")
            self.assertIn(self.secret, row["subject"], "original secret preserved in works.subject")

        # 2. Boot endpoint: /api/boot
        st_boot, r_boot = self._req("GET", "/api/boot")
        self.assertEqual(st_boot, 200)
        work_boot = next((w for w in r_boot.get("works", []) if w["id"] == wid), None)
        self.assertIsNotNone(work_boot)
        self.assertTrue(work_boot["promptMasked"])
        self.assertEqual(work_boot["prompt"], "")
        self.assertEqual(work_boot["subject"], "")
        st_boot_raw, txt_boot = self._req_text("GET", "/api/boot")
        self.assertNotIn(self.secret, txt_boot)

        # 3. Work resource detail: /api/forum/resources/work/<id>
        st_res, r_res = self._req("GET", f"/api/forum/resources/work/{wid}")
        self.assertEqual(st_res, 200)
        res_work = r_res["resource"]
        self.assertTrue(res_work["promptMasked"])
        self.assertEqual(res_work["prompt"], "")
        self.assertEqual(res_work["subject"], "")
        st_res_raw, txt_res = self._req_text("GET", f"/api/forum/resources/work/{wid}")
        self.assertNotIn(self.secret, txt_res)

        # 4. Work post mount by-ref: /api/posts/by-ref/work/<id>
        st_post, txt_post = self._req_text("GET", f"/api/posts/by-ref/work/{wid}")
        if st_post == 200:
            self.assertNotIn(self.secret, txt_post)

        # 5. Author edit: /api/content/works/<id>/edit
        st_edit, r_edit = self._req("GET", f"/api/content/works/{wid}/edit", cookie=self.cookie_user)
        self.assertEqual(st_edit, 200)
        edit_item = r_edit["item"]
        self.assertTrue(edit_item.get("promptMasked"))
        self.assertEqual(edit_item.get("prompt"), "")
        self.assertEqual(edit_item.get("subject"), "")
        st_edit_raw, txt_edit = self._req_text("GET", f"/api/content/works/{wid}/edit", cookie=self.cookie_user)
        self.assertNotIn(self.secret, txt_edit)

        # 6. Curation submission masking: sanitize_curation_payload_for_client
        curation_payload = {
            "kind": "work",
            "title": "投稿作品含秘密主题",
            "prompt": "安全无秘密提示词",
            "subject": f"主题文字包含 {self.secret}",
        }
        sanitized = C.sanitize_curation_payload_for_client(curation_payload, self.db.get_conn())
        self.assertTrue(sanitized.get("promptMasked"))
        self.assertEqual(sanitized.get("prompt"), "[包含资源专属指令，已隐藏]")
        self.assertEqual(sanitized.get("subject"), "[包含资源专属指令，已隐藏]")
        self.assertNotIn(self.secret, json.dumps(sanitized))

    def test_author_edit_updating_subject_with_secret(self):
        """Author editing subject to add a secret flags prompt_has_secret and masks output."""
        # Publish clean work
        st_pub, r_pub = self._req(
            "POST",
            "/api/works",
            {
                "title": "初始干净作品",
                "prompt": "干净提示词",
                "subject": "干净主题",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_pub, 200)
        wid = r_pub["workId"]
        with self.db.transaction() as tx:
            row = tx.execute("SELECT prompt_has_secret FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row["prompt_has_secret"], 0)

        # Author updates subject to include secret
        st_edit, _ = self._req(
            "POST",
            f"/api/content/works/{wid}/edit",
            {
                "title": "初始干净作品",
                "subject": f"更新后主题含有秘密 {self.secret}",
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_edit, 200)
        with self.db.transaction() as tx:
            row_after = tx.execute("SELECT prompt_has_secret, subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row_after["prompt_has_secret"], 1)

        # Boot & edit endpoints now mask the work
        st_boot, r_boot = self._req("GET", "/api/boot")
        w_boot = next(w for w in r_boot["works"] if w["id"] == wid)
        self.assertTrue(w_boot["promptMasked"])
        self.assertEqual(w_boot["prompt"], "")
        self.assertEqual(w_boot["subject"], "")

    def test_run_blackbox_backfill_detects_secret_in_subject(self):
        """run_blackbox_backfill flags legacy works whose subject contains a secret."""
        legacy_id = "work_legacy_subj_test"
        now_iso = S.utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, prompt, prompt_has_secret, subject, images_json, styles_json, published_at_ms, created_at, updated_at)
                VALUES (?, 'alice', 'Alice', '遗留作品', '安全公开提示词', NULL, ?, '[]', '[]', 1700000000000, ?, ?)
                """,
                (legacy_id, f"遗留主题包含 {self.secret}", now_iso, now_iso),
            )

        # Before backfill: fail-closed read
        row_before = self.db.get_conn().execute("SELECT * FROM works WHERE id = ?", (legacy_id,)).fetchone()
        vis, masked = S.get_work_client_prompt(row_before, is_admin_route=False)
        self.assertEqual(vis, "")
        self.assertTrue(masked)

        # Run backfill
        counts = S.run_blackbox_backfill(self.db, force=True)
        self.assertGreaterEqual(counts["works"], 1)

        row_after = self.db.get_conn().execute("SELECT * FROM works WHERE id = ?", (legacy_id,)).fetchone()
        self.assertEqual(row_after["prompt_has_secret"], 1)
        ser = S._serialize_work(row_after, {}, set(), None)
        self.assertTrue(ser["promptMasked"])
        self.assertEqual(ser["prompt"], "")
        self.assertEqual(ser["subject"], "")

    def test_draft_recipe_from_work_subject_masking(self):
        """GET /api/studio/recipes/from-work/{id} does not leak subject when masked or locked."""
        # 1. Secret in subject -> prompt_has_secret = 1
        st_pub, r_pub = self._req(
            "POST",
            "/api/works",
            {
                "title": "绝密主题作品",
                "prompt": "普通公开提示词",
                "subject": f"主题附带绝密指令 {self.secret} 特征",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FX-SECRET-SUBJ"],
                "price": 0,
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_pub, 200)
        wid_secret = r_pub["workId"]

        # Stranger calls from-work
        st_stranger, r_stranger = self._req(
            "GET",
            f"/api/studio/recipes/from-work/{wid_secret}",
            cookie=self.cookie_stranger,
        )
        self.assertEqual(st_stranger, 200)
        self.assertEqual(r_stranger["draft"]["subjectHint"], "", "subjectHint must be empty when work prompt_has_secret=1")
        _, txt_stranger = self._req_text(
            "GET",
            f"/api/studio/recipes/from-work/{wid_secret}",
            cookie=self.cookie_stranger,
        )
        self.assertNotIn(self.secret, txt_stranger)
        self.assertNotIn(self.secret[:20], txt_stranger)

        # 2. Paid work (locked for stranger)
        st_paid, r_paid = self._req(
            "POST",
            "/api/works",
            {
                "title": "付费作品未解锁",
                "prompt": "付费提示词",
                "subject": "付费作品的主题内容文字",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
                "price": 10,
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_paid, 200)
        wid_paid = r_paid["workId"]

        # Stranger calls from-work -> locked, subjectHint must be empty
        st_stranger_paid, r_stranger_paid = self._req(
            "GET",
            f"/api/studio/recipes/from-work/{wid_paid}",
            cookie=self.cookie_stranger,
        )
        self.assertEqual(st_stranger_paid, 200)
        self.assertEqual(r_stranger_paid["draft"]["subjectHint"], "", "subjectHint must be empty for locked paid work")

        # Author calls from-work -> author unlocked, returns subjectHint
        st_author_paid, r_author_paid = self._req(
            "GET",
            f"/api/studio/recipes/from-work/{wid_paid}",
            cookie=self.cookie_user,
        )
        self.assertEqual(st_author_paid, 200)
        self.assertEqual(r_author_paid["draft"]["subjectHint"], "付费作品的主题内容文字")

        # 4. Stranger unlocks paid work -> returns subjectHint
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO unlocks (user_id, target_type, target_id, cost, status, created_at) VALUES (?, 'work', ?, 10, 'settled', ?)",
                (self.stranger["id"], wid_paid, S.utc_now_iso()),
            )
        st_stranger_unlocked, r_stranger_unlocked = self._req(
            "GET",
            f"/api/studio/recipes/from-work/{wid_paid}",
            cookie=self.cookie_stranger,
        )
        self.assertEqual(st_stranger_unlocked, 200)
        self.assertEqual(r_stranger_unlocked["draft"]["subjectHint"], "付费作品的主题内容文字")

        # 3. Clean free work -> returns subjectHint up to 80 chars
        st_clean, r_clean = self._req(
            "POST",
            "/api/works",
            {
                "title": "正常免费公开作品",
                "prompt": "普通免费公开提示词",
                "subject": "雨中街角面馆，热气腾腾的一碗汤面",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
                "price": 0,
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_clean, 200)
        wid_clean = r_clean["workId"]

        st_stranger_clean, r_stranger_clean = self._req(
            "GET",
            f"/api/studio/recipes/from-work/{wid_clean}",
            cookie=self.cookie_stranger,
        )
        self.assertEqual(st_stranger_clean, 200)
        self.assertEqual(r_stranger_clean["draft"]["subjectHint"], "雨中街角面馆，热气腾腾的一碗汤面")

    def test_curation_submission_author_edit_placeholder_protection(self):
        """Author editing a curation-backed work preserves existing subject if placeholder is passed."""
        sub_id = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        target_id = "test-work-placeholder"
        now_iso = S.utc_now_iso()
        sub = {
            "id": sub_id,
            "kind": "work",
            "owner_username": self.user["username"],
            "owner_user_id": self.user["id"],
            "target_id": target_id,
        }
        payload = {
            "kind": "work",
            "title": "投稿支撑作品",
            "prompt": "收录提示词",
            "subject": "初始绝密主题",
            "images": ["/images/individual/FA/FA-001.webp"],
            "styles": ["FA-001"],
            "price": 0,
        }
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO curation_submissions (
                    id, topic_id, owner_username, owner_user_id, kind, target_id,
                    status, current_revision, request_id, created_at, updated_at
                ) VALUES (?, 'topic_ph', ?, ?, 'work', ?, 'approved', 1, 'req-ph', ?, ?)
                """,
                (sub_id, self.user["username"], self.user["id"], target_id, now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver-ph-1', ?, 1, ?, ?)
                """,
                (sub_id, C.json.dumps(payload, ensure_ascii=False), now_iso),
            )
            C._publish_approved(tx, sub, 1)

        # 1. Author edits with placeholder subject -> original subject preserved
        st1, r1 = self._req(
            "POST",
            f"/api/content/works/{target_id}/edit",
            {
                "title": "修改后的作品标题",
                "subject": "[包含资源专属指令，已隐藏]",
                "prompt": "[包含资源专属指令，已隐藏]",
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st1, 200)
        with self.db.transaction() as tx:
            sub_row = tx.execute("SELECT current_revision FROM curation_submissions WHERE id = ?", (sub_id,)).fetchone()
            rev = sub_row["current_revision"]
            cur_payload = C._current_payload(tx, sub_id, rev)
            self.assertEqual(cur_payload["subject"], "初始绝密主题", "placeholder must not overwrite subject in curation payload")
            self.assertEqual(cur_payload["prompt"], "收录提示词", "placeholder must not overwrite prompt in curation payload")
            # Approving keeps original values in works table
            C._publish_approved(tx, sub, rev)
            work_row = tx.execute("SELECT prompt, subject FROM works WHERE id = ?", (target_id,)).fetchone()
            self.assertEqual(work_row["subject"], "初始绝密主题")
            self.assertEqual(work_row["prompt"], "收录提示词")

        # 2. Direct revise endpoint with placeholder -> also preserved
        st_rev, r_rev = self._req(
            "POST",
            f"/api/curation/submissions/{sub_id}/revise",
            {
                "payload": {
                    "kind": "work",
                    "title": "直接修改版本",
                    "subject": "[包含资源专属指令，已隐藏]",
                    "prompt": "[包含资源专属指令，已隐藏]",
                    "images": ["/images/individual/FA/FA-001.webp"],
                    "styles": ["FA-001"],
                }
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st_rev, 200)
        with self.db.transaction() as tx:
            sub_row_r = tx.execute("SELECT current_revision FROM curation_submissions WHERE id = ?", (sub_id,)).fetchone()
            rev_r = sub_row_r["current_revision"]
            cur_payload_r = C._current_payload(tx, sub_id, rev_r)
            self.assertEqual(cur_payload_r["subject"], "初始绝密主题")
            self.assertEqual(cur_payload_r["prompt"], "收录提示词")

        # 3. Author edits with real text -> subject updated
        st2, r2 = self._req(
            "POST",
            f"/api/content/works/{target_id}/edit",
            {
                "title": "修改后的作品标题2",
                "subject": "作者更新后的真实主题",
            },
            cookie=self.cookie_user,
        )
        self.assertEqual(st2, 200)
        with self.db.transaction() as tx:
            sub_row2 = tx.execute("SELECT current_revision FROM curation_submissions WHERE id = ?", (sub_id,)).fetchone()
            rev2 = sub_row2["current_revision"]
            cur_payload2 = C._current_payload(tx, sub_id, rev2)
            self.assertEqual(cur_payload2["subject"], "作者更新后的真实主题")
            C._publish_approved(tx, sub, rev2)
            work_row2 = tx.execute("SELECT subject FROM works WHERE id = ?", (target_id,)).fetchone()
            self.assertEqual(work_row2["subject"], "作者更新后的真实主题")

    def test_publish_approved_rejects_oversized_subject(self):
        """_publish_approved rejects subject exceeding 2000 chars with subject_too_long."""
        sub_id = "test-sub-oversize"
        target_id = "test-work-oversize"
        now_iso = S.utc_now_iso()
        sub = {
            "id": sub_id,
            "kind": "work",
            "owner_username": self.user["username"],
            "owner_user_id": self.user["id"],
            "target_id": target_id,
        }
        payload = {
            "kind": "work",
            "title": "超长主题作品",
            "prompt": "收录提示词",
            "subject": "X" * 2001,
            "images": ["/images/individual/FA/FA-001.webp"],
            "styles": ["FA-001"],
            "price": 0,
        }
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO curation_submissions (
                    id, topic_id, owner_username, owner_user_id, kind, target_id,
                    status, current_revision, request_id, created_at, updated_at
                ) VALUES (?, 'topic_ov', ?, ?, 'work', ?, 'approved', 1, 'req-ov', ?, ?)
                """,
                (sub_id, self.user["username"], self.user["id"], target_id, now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES ('ver-ov-1', ?, 1, ?, ?)
                """,
                (sub_id, C.json.dumps(payload, ensure_ascii=False), now_iso),
            )
            with self.assertRaises(S.ServiceError) as ctx:
                C._publish_approved(tx, sub, 1)
            self.assertEqual(ctx.exception.code, "subject_too_long")
            self.assertEqual(ctx.exception.status, 400)

    def test_admin_edit_work_rejects_oversized_subject(self):
        """Admin edit rejects subject exceeding 2000 chars with subject_too_long (400)."""
        pub = C.publish_work_direct(
            self.db,
            self.user,
            {
                "title": "管理员编辑测试作品",
                "prompt": "正常提示词",
                "subject": "正常主题",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
                "price": 0,
            },
        )
        wid = pub["workId"]

        # 1. Direct function call raises ServiceError 400 subject_too_long
        with self.assertRaises(S.ServiceError) as ctx:
            A.admin_moderate_work(
                self.db,
                self.admin,
                wid,
                "edit",
                {"subject": "S" * 2001},
            )
        self.assertEqual(ctx.exception.code, "subject_too_long")
        self.assertEqual(ctx.exception.status, 400)

        # 2. HTTP endpoint also returns 400
        st, body = self._req(
            "POST",
            f"/api/works/{wid}/moderate",
            {
                "action": "edit",
                "subject": "S" * 2001,
            },
            cookie=self.cookie_admin,
        )
        self.assertEqual(st, 400)
        self.assertIn("最多2000字", str(body.get("error", "")))

    def test_admin_edit_work_preserves_subject_on_placeholder_or_none(self):
        """Admin edit preserves original subject when placeholder or None is supplied."""
        pub = C.publish_work_direct(
            self.db,
            self.user,
            {
                "title": "占位符测试作品",
                "prompt": "原始提示词",
                "subject": "原始绝密主题",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
                "price": 0,
            },
        )
        wid = pub["workId"]

        # 1. Edit with placeholder subject preserves original subject
        res = A.admin_moderate_work(
            self.db,
            self.admin,
            wid,
            "edit",
            {
                "title": "修改标题保留主题",
                "subject": "[包含资源专属指令，已隐藏]",
            },
        )
        self.assertTrue(res.get("ok"))
        with self.db.transaction() as tx:
            row = tx.execute("SELECT title, subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row["title"], "修改标题保留主题")
            self.assertEqual(row["subject"], "原始绝密主题")

        # 2. Edit with None / omitted subject preserves original subject
        res2 = A.admin_moderate_work(
            self.db,
            self.admin,
            wid,
            "edit",
            {
                "title": "二次修改标题",
                "subject": None,
            },
        )
        self.assertTrue(res2.get("ok"))
        with self.db.transaction() as tx:
            row2 = tx.execute("SELECT title, subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row2["title"], "二次修改标题")
            self.assertEqual(row2["subject"], "原始绝密主题")

        # 3. HTTP endpoint with placeholder also preserves original subject
        st, _ = self._req(
            "POST",
            f"/api/works/{wid}/moderate",
            {
                "action": "edit",
                "title": "HTTP改标题",
                "subject": "[包含资源专属指令，已隐藏]",
            },
            cookie=self.cookie_admin,
        )
        self.assertEqual(st, 200)
        with self.db.transaction() as tx:
            row3 = tx.execute("SELECT title, subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row3["title"], "HTTP改标题")
            self.assertEqual(row3["subject"], "原始绝密主题")

        # 4. Editing with real new subject updates it successfully
        st4, _ = self._req(
            "POST",
            f"/api/works/{wid}/moderate",
            {
                "action": "edit",
                "subject": "管理员更新后的真实主题",
            },
            cookie=self.cookie_admin,
        )
        self.assertEqual(st4, 200)
        with self.db.transaction() as tx:
            row4 = tx.execute("SELECT subject FROM works WHERE id = ?", (wid,)).fetchone()
            self.assertEqual(row4["subject"], "管理员更新后的真实主题")


if __name__ == "__main__":
    unittest.main()
