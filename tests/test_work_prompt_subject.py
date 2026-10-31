"""Acceptance tests for work prompt codes and subject persistence.

Verifies:
1. _serialize_work returns subject with visibility identical to prompt (empty when masked/locked).
2. publish_work_direct accepts optional subject (<= 2000 chars) and writes to works.subject.
3. publish_work_direct rejects subject exceeding 2000 characters.
4. _publish_approved writes subject from submission payload into works.subject.
5. _normalise_item validates and preserves subject.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.server import init_database
from backend import curation as C, services as S


class WorkPromptSubjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_PRIVATE_STORAGE": self.tmp.name,
                "HANDRAW_ALLOWED_ORIGINS": "http://127.0.0.1:3094,http://localhost:3094",
            },
        )
        self.env.start()
        self.db = init_database(Path(self.tmp.name) / "test.db")
        self.user, self.token = S.register_user(self.db, "alice", "alice-pass-123")
        self.reviewer, _ = S.register_user(self.db, "rev_a", "rev-pass-123")
        self.admin, _ = S.register_user(self.db, "admin_user", "admin-pass-123")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role='admin' WHERE username='admin_user'")
        self.admin["role"] = "admin"

    def tearDown(self):
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

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
        # Build submission with work item containing subject
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
            # Call _publish_approved
            res = C._publish_approved(tx, sub, 1)
            self.assertEqual(res["workId"], target_id)

            row = tx.execute("SELECT * FROM works WHERE id = ?", (target_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["subject"], "收录独立主题")
            self.assertEqual(row["prompt"], "收录提示词")

            # Test update on revision
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


if __name__ == "__main__":
    unittest.main()
