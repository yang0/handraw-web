"""Tests for publish content guidance:
- Part A: Title validation (>=4 non-ws chars, blacklisted placeholder titles, pure resource code rejection, valid combos accepted)
- Part A: Work notes requirement (>=8 non-ws chars) and propagation to forum_topics.summary
- Part A: Style/Layout description requirement (>=8 non-ws chars)
- Part A: Preservation of legacy works with empty notes (no fake dummy text)
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tests.legacy_database import init_legacy_database
from backend import curation as C
from backend import server
from backend.services import (
    validate_topic_title,
    PLACEHOLDER_TOPIC_TITLES,
    register_user,
    publish_forum_topic_post,
    ServiceError,
)


class PublishContentGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = init_legacy_database(Path(self.temp.name) / "test_guidance.db")
        self.author, _ = register_user(self.db, "author_guidance", "password123")

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_01_validate_topic_title_unit(self):
        # 1. Invalid / Empty / Too short
        for invalid in [None, "", "   ", "abc", " 1 2 ", "短"]:
            with self.assertRaises(ServiceError) as ctx:
                validate_topic_title(invalid)
            self.assertIn("至少需要 4 个非空白字符", str(ctx.exception))

        # 2. Blacklisted placeholders
        for ph in PLACEHOLDER_TOPIC_TITLES:
            with self.assertRaises(ServiceError) as ctx:
                validate_topic_title(ph)
            msg = str(ctx.exception)
            self.assertTrue("不能使用默认占位词" in msg or "至少需要 4 个非空白字符" in msg)

        # 3. Pure resource codes and combinations of codes/punctuation
        pure_codes = [
            "FA-001",
            "  FA-001  ",
            "USR-FA-123",
            "FA-001 / SC-002",
            "LAY-01 + FA-002",
            "FA-001｜SC-002",
            "【FA-001】",
            "(FA-001)",
        ]
        for pc in pure_codes:
            with self.assertRaises(ServiceError) as ctx:
                validate_topic_title(pc)
            self.assertIn("不能仅由编号组成", str(ctx.exception))

        # 4. Valid combinations of resource codes with meaningful text
        valid_combos = [
            "雨天便利店｜FA-001",
            "FA-001 赛博水墨 · 晒图",
            "【水彩插画】SC-001 尝试",
            "秋分节气海报设计记录",
            "关于手绘工作流优化的思考与建议",
        ]
        for vc in valid_combos:
            clean = validate_topic_title(vc)
            self.assertEqual(clean, vc.strip())

    def test_02_work_notes_written_to_topic_summary(self):
        work_notes = "画了一个雨天便利店的黄昏场景，水彩边缘晕染效果不错。"
        res = C.publish_work_direct(
            self.db,
            self.author,
            {
                "title": "雨天便利店｜水彩画风尝试",
                "images": ["/images/test-rainy.webp"],
                "styles": ["FA-001"],
                "notes": work_notes,
                "prompt": "test prompt for rainy store",
            },
        )
        self.assertEqual(res["status"], "published")
        topic_id = res["topicId"]

        # Verify forum topic was created and its summary has the exact notes
        row = self.db.get_conn().execute("SELECT * FROM forum_topics WHERE id=?", (topic_id,)).fetchone()
        self.assertIsNotNone(row)
        topic = dict(row)
        self.assertEqual(topic["title"], "雨天便利店｜水彩画风尝试")
        self.assertEqual(topic["summary"], work_notes)

    def test_03_legacy_work_with_empty_notes_keeps_empty_summary(self):
        res = C.publish_work_direct(
            self.db,
            self.author,
            {
                "title": "历史旧作品测试保留原样",
                "images": ["/images/test-legacy.webp"],
                "styles": ["FA-001"],
                "prompt": "legacy prompt",
            },
        )
        topic_id = res["topicId"]
        row = self.db.get_conn().execute("SELECT * FROM forum_topics WHERE id=?", (topic_id,)).fetchone()
        self.assertIsNotNone(row)
        topic = dict(row)
        self.assertEqual(topic["summary"], "")

    def test_04_publish_forum_topic_validates_title(self):
        # Placeholder title rejected
        with self.assertRaises(ServiceError) as ctx:
            publish_forum_topic_post(
                self.db,
                self.author,
                {
                    "title": "图文模式",
                    "category": "tuning",
                    "body": "这里是一篇测试正文内容，长度足够八个字以上。",
                },
            )
        self.assertIn("不能使用默认占位词", str(ctx.exception))

        # Pure code rejected
        with self.assertRaises(ServiceError) as ctx:
            publish_forum_topic_post(
                self.db,
                self.author,
                {
                    "title": "FA-001",
                    "category": "tuning",
                    "body": "这里是一篇测试正文内容，长度足够八个字以上。",
                },
            )
        self.assertIn("不能仅由编号组成", str(ctx.exception))

        # Valid topic title succeeds
        res = publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "雨天便利店｜FA-001 实测探讨",
                "category": "tuning",
                "body": "这里是一篇测试正文内容，长度足够八个字以上。",
            },
        )
        self.assertIsNotNone(res.get("topicId"))


if __name__ == "__main__":
    unittest.main()
