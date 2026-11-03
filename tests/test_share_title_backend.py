"""Unit tests for backend handling of share titles and generation subjects (Issue #5)."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.server import init_database
from backend.runtime_policy import sanitize_plain_text
from backend.services import (
    ServiceError,
    get_public_generation_history,
    record_user_studio_history,
    register_user,
    serialize_public_generation_history,
    validate_topic_title,
)


class TestShareTitleBackend(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp_dir.name) / "test_share_title.db"
        self.test_db = init_database(db_path)

    def tearDown(self):
        self.test_db.close()
        self.tmp_dir.cleanup()

    def test_validate_topic_title_placeholder_disallowed(self):
        """Verify default placeholder words like '图文模式' are disallowed for forum topic titles."""
        with self.assertRaises(ServiceError) as exc_info:
            validate_topic_title("图文模式")
        self.assertEqual(exc_info.exception.code, "title_placeholder_disallowed")

        with self.assertRaises(ServiceError) as exc_info:
            validate_topic_title("当前工作流")
        self.assertEqual(exc_info.exception.code, "title_placeholder_disallowed")

        # Real subject is accepted
        valid_title = validate_topic_title("雨夜书店")
        self.assertEqual(valid_title, "雨夜书店")

    def test_curation_draft_validation_rules(self):
        """Verify curation drafts sanitize plain text and enforce length constraints."""
        # Plain text sanitization strips dangerous tags
        raw = "<script>alert(1)</script>雨夜书店<b>分享</b>"
        cleaned = sanitize_plain_text(raw, max_chars=140).strip()
        self.assertNotIn("script", cleaned)
        self.assertNotIn("<b>", cleaned)
        self.assertIn("雨夜书店分享", cleaned)

        # Over 120 chars length constraint
        long_title = "长标题" * 50
        self.assertGreater(len(long_title), 120)

    def test_record_user_studio_history_persists_subject(self):
        """Verify record_user_studio_history durably persists user subject in studio_generations."""
        user, _ = register_user(self.test_db, "creator_alice", "Password123!", display_name="爱丽丝")

        entry = {
            "id": "gen_rainy_bookstore",
            "tabTitle": "图文模式",
            "subject": "雨夜书店",
            "mode": "graphic-text",
            "modeLabel": "图文创作 · 1 张",
            "kind": "single",
            "recipeSummary": "画风 #FA-003 · 3:4",
            "prompt": "雨夜书店的暖光",
            "items": [
                {
                    "id": "item_1",
                    "title": "成图 #1",
                    "subject": "雨夜书店",
                    "imageUrl": "/uploads/rainy_bookstore.png",
                    "ratio": "3:4",
                }
            ],
        }

        res = record_user_studio_history(self.test_db, user, entry)
        self.assertTrue(res.get("ok"))

        # Check direct SQLite row
        conn = self.test_db.get_conn()
        row = conn.execute("SELECT id, tab_title, subject FROM studio_generations WHERE id = ?", ("gen_rainy_bookstore",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["tab_title"], "图文模式")
        self.assertEqual(row["subject"], "雨夜书店")

        # Retrieve via public generation history
        serialized = serialize_public_generation_history(row, conn)
        self.assertEqual(serialized["topic"], "雨夜书店")
        self.assertEqual(serialized["subject"], "雨夜书店")

    def test_serialize_public_generation_history_extracts_item_subject(self):
        """Verify serialized public history extracts subject from items_json if row.subject is empty."""
        user, _ = register_user(self.test_db, "creator_bob", "Password123!", display_name="鲍勃")

        entry_no_top_subject = {
            "id": "gen_from_items",
            "tabTitle": "图文模式",
            "subject": "",  # missing at top level
            "mode": "graphic-text",
            "modeLabel": "生成 · 1 张",
            "kind": "single",
            "recipeSummary": "",
            "prompt": "深山古寺",
            "items": [
                {
                    "id": "item_1",
                    "title": "成图 #1",
                    "subject": "深山古寺",
                    "imageUrl": "/uploads/temple.png",
                }
            ],
        }

        res = record_user_studio_history(self.test_db, user, entry_no_top_subject)
        self.assertTrue(res.get("ok"))

        conn = self.test_db.get_conn()
        row = conn.execute("SELECT * FROM studio_generations WHERE id = ?", ("gen_from_items",)).fetchone()
        serialized = serialize_public_generation_history(row, conn)
        self.assertEqual(serialized["subject"], "深山古寺")
        self.assertEqual(serialized["topic"], "深山古寺")


if __name__ == "__main__":
    unittest.main()
