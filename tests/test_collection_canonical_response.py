# -*- coding: utf-8 -*-
"""Tests for canonical toggle_user_collection response fields (Issue #49)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.services import (
    publish_user_work,
    register_user,
    toggle_user_collection,
    toggle_user_like,
)


class CollectionCanonicalResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "test_social.db")
        self.user, _ = register_user(self.db, "user_tester", "pass123")

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_toggle_user_collection_canonical_fields(self):
        # 1. Test collection on style
        res_style = toggle_user_collection(self.db, self.user, "styles", "FA-001")
        self.assertTrue(res_style["ok"])
        self.assertEqual(res_style["targetType"], "style")
        self.assertEqual(res_style["targetId"], "FA-001")
        self.assertTrue(res_style["collected"])
        self.assertIsInstance(res_style["favorites"], int)
        self.assertGreaterEqual(res_style["favorites"], 1)
        self.assertIn("credits", res_style)
        self.assertIn("rewarded", res_style)

        # Toggle off
        res_style_off = toggle_user_collection(self.db, self.user, "styles", "FA-001")
        self.assertTrue(res_style_off["ok"])
        self.assertFalse(res_style_off["collected"])
        self.assertEqual(res_style_off["favorites"], res_style["favorites"] - 1)

        # 2. Test collection on layout
        res_layout = toggle_user_collection(self.db, self.user, "layouts", "SC-001")
        self.assertTrue(res_layout["ok"])
        self.assertEqual(res_layout["targetType"], "layout")
        self.assertEqual(res_layout["targetId"], "SC-001")
        self.assertTrue(res_layout["collected"])
        self.assertIsInstance(res_layout["favorites"], int)

        # 3. Test collection on work
        pub = publish_user_work(
            self.db,
            self.user,
            {"title": "测试作品", "prompt": "prompt", "images": ["/images/individual/FA/FA-013.webp"], "styles": ["FA-001"]},
        )
        work_id = pub["workId"]
        topic_id = pub["topicId"]

        res_work = toggle_user_collection(self.db, self.user, "works", work_id)
        self.assertTrue(res_work["ok"])
        self.assertEqual(res_work["targetType"], "work")
        self.assertEqual(res_work["targetId"], work_id)
        self.assertTrue(res_work["collected"])
        self.assertEqual(res_work["favorites"], 1)

        # 4. Test collection on topic linked to work (canonicalizes to work)
        # Favouriting work's topic increments work's favorites
        res_work_topic = toggle_user_collection(self.db, self.user, "topics", topic_id)
        self.assertTrue(res_work_topic["ok"])
        self.assertEqual(res_work_topic["targetType"], "work")
        self.assertEqual(res_work_topic["targetId"], work_id)
        self.assertFalse(res_work_topic["collected"])  # toggled off
        self.assertEqual(res_work_topic["favorites"], 0)

        # 5. Parity with toggle_user_like response shape
        res_like_work = toggle_user_like(self.db, self.user, "work", work_id)
        self.assertTrue(res_like_work["ok"])
        self.assertEqual(res_like_work["targetType"], "work")
        self.assertEqual(res_like_work["targetId"], work_id)
        self.assertTrue(res_like_work["liked"])
        self.assertEqual(res_like_work["likes"], 1)
        self.assertIn("credits", res_like_work)
        self.assertIn("rewarded", res_like_work)
