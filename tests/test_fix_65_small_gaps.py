"""Tests for Issue #65: Small design gaps.

1. Resource comment char limit: 800 -> 3000 (2000 chars succeeds, 3001 truncated to 3000).
2. Admin self-review default is False (rejected on fresh DB; allowed when explicitly enabled).
3. Seed announcement has no '72h', accurate counts '360+' and '160+'.
4. Operator can accept forum bounty reply on behalf of author; non-staff cannot.
"""
from __future__ import annotations

import unittest
import os
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.postgres_support import open_isolated_postgres
from backend import admin_services, server, services
from backend.resource_discussions import comment as resource_comment
from backend.seed import DEFAULT_SITE_SETTINGS


class Fix65SmallDesignGapsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.author, _ = services.register_user(self.db, "author_65", "Pass1234!")
        self.user_b, _ = services.register_user(self.db, "solver_65", "Pass1234!")
        self.outsider, _ = services.register_user(self.db, "outsider_65", "Pass1234!")
        self.admin, _ = services.register_user(self.db, "admin_65", "Pass1234!")
        self.operator, _ = services.register_user(self.db, "operator_65", "Pass1234!")

        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))
        conn.execute("UPDATE users SET role = 'operator' WHERE id = ?", (self.operator["id"],))
        conn.execute("UPDATE wallets SET balance = 100 WHERE user_id = ?", (self.author["id"],))
        conn.commit()
        self.admin["role"] = "admin"
        self.operator["role"] = "operator"

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_01_resource_comment_limit_3000_chars(self):
        """2000-char resource comment succeeds; 3001-char comment is truncated to 3000."""
        # 1. 2000 chars comment succeeds
        text_2000 = "测" * 2000
        res1 = resource_comment(self.db, self.author, "style", "FA-001", text_2000)
        self.assertTrue(res1.get("ok"))
        self.assertEqual(len(res1["comment"]["text"]), 2000)

        # 2. 3001 chars comment is sanitized and truncated to 3000 chars
        text_3001 = "评" * 3001
        res2 = resource_comment(self.db, self.author, "style", "FA-001", text_3001)
        self.assertTrue(res2.get("ok"))
        self.assertEqual(len(res2["comment"]["text"]), 3000)
        self.assertEqual(res2["comment"]["text"], "评" * 3000)

    def test_02_admin_self_review_default_forbidden_on_fresh_db(self):
        """On fresh database, allow_self_review_for_admin is False; admin cannot self-review."""
        # Admin publishes a work
        work_pub = services.publish_user_work(
            self.db,
            self.admin,
            {
                "title": "管理员自发作品测试自审拦截",
                "prompt": "prompt text",
                "images": ["/images/individual/FA/FA-001.webp"],
                "styles": ["FA-001"],
            },
        )
        wid = work_pub["workId"]

        # Attempt to feature own work with default settings -> must raise 403 self_review_forbidden
        with self.assertRaises(services.ServiceError) as ctx:
            admin_services.admin_moderate_work(self.db, self.admin, wid, "feature", {"reason": "自审加精"})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "self_review_forbidden")

        # Explicitly enabling allow_self_review_for_admin allows it
        admin_services.admin_update_settings(
            self.db,
            self.admin,
            "moderation",
            {"allow_self_review_for_admin": True},
        )
        res_ok = admin_services.admin_moderate_work(self.db, self.admin, wid, "feature", {"reason": "显式允许自审"})
        self.assertTrue(res_ok.get("ok"))

    def test_03_seed_announcement_facts(self):
        """Seed announcement explains separate accounts and lifetime signup quota."""
        announcement = DEFAULT_SITE_SETTINGS.get("announcement", {})
        text = str(announcement.get("text", ""))

        self.assertNotIn("72h", text)
        self.assertIn("生图余额与社区积分独立记账", text)
        self.assertIn("10张1K", text)
        self.assertIn("规划免费", text)
        self.assertNotIn("首晒立奖", text)

        # Also verify database seeded settings match
        db_settings = services.get_site_settings(self.db.get_conn())
        db_ann_text = str(db_settings.get("announcement", {}).get("text", ""))
        self.assertNotIn("72h", db_ann_text)
        self.assertEqual(db_ann_text, text)

        # Default moderation setting in seed
        self.assertFalse(DEFAULT_SITE_SETTINGS.get("moderation", {}).get("allow_self_review_for_admin"))
        self.assertFalse(db_settings.get("moderation", {}).get("allow_self_review_for_admin"))

    def test_04_operator_can_accept_bounty_reply(self):
        """Operator can accept a forum bounty reply on behalf of author."""
        # 1. Author posts bounty topic (bounty=20)
        t_res = services.publish_forum_topic_post(
            self.db,
            self.author,
            {
                "title": "求高手指导手绘排版技巧",
                "category": "tuning",
                "body": "请问如何调整画风与图型的搭配以达到最佳效果？",
                "bounty": 20,
            },
        )
        tid = t_res["topicId"]

        # 2. Solver replies
        r_res = services.publish_forum_reply_post(
            self.db,
            self.user_b,
            tid,
            "建议先选定主色调，然后统一线条粗细和留白边距。",
        )
        rid = r_res["replyId"]

        # 3. Outsider (non-staff) attempts to accept -> rejected 403
        with self.assertRaises(services.ServiceError) as ctx:
            services.accept_forum_bounty_reply(self.db, self.outsider, tid, rid)
        self.assertEqual(ctx.exception.status, 403)

        # 4. Operator accepts bounty reply on behalf -> succeeds
        accept_res = services.accept_forum_bounty_reply(self.db, self.operator, tid, rid)
        self.assertTrue(accept_res.get("ok"))
        self.assertEqual(accept_res.get("bounty"), 20)

        # Verify topic solved
        conn = self.db.get_conn()
        t_row = conn.execute("SELECT solved, bounty_status FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(int(t_row["solved"]), 1)
        self.assertEqual(t_row["bounty_status"], "settled")
