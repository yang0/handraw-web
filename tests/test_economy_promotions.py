"""Only known obsolete promotional defaults are changed during economy upgrades."""

import json
import unittest
from pathlib import Path
from backend.seed import DEFAULT_SITE_SETTINGS
from tests.postgres_support import open_isolated_postgres

OLD = "Handraw 手绘风社区升级版：360+ 画风与 160+ 图型全量打通无限画布，荒地首晒立奖 +15✦！"


class EconomyPromotionTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        self.sql = (
            Path(__file__).resolve().parents[1]
            / "backend/postgres_121_reward_promotions.sql"
        ).read_text(encoding="utf-8")

    def announcement(self, text):
        value = {
            "text": text,
            "enabled": False,
            "badge": "Keep badge",
            "cta_label": "Keep CTA",
        }
        self.db.get_conn().execute(
            "INSERT INTO site_settings(key,value_json,updated_by,updated_at) VALUES('announcement',?,'test',CURRENT_TIMESTAMP::text) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (json.dumps(value),),
        )
        return value

    def test_known_promotion_is_retired_without_overwriting_other_announcement_settings(
        self,
    ):
        self.announcement(OLD)
        with self.db.transaction() as tx:
            tx.execute(self.sql)
            tx.execute(self.sql)
        row = (
            self.db.get_conn()
            .execute("SELECT value_json FROM site_settings WHERE key='announcement'")
            .fetchone()[0]
        )
        value = json.loads(row)
        self.assertEqual(value["text"], DEFAULT_SITE_SETTINGS["announcement"]["text"])
        self.assertFalse(value["enabled"])
        self.assertEqual(value["badge"], "Keep badge")
        self.assertEqual(value["cta_label"], "Keep CTA")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT count(*) FROM schema_migrations WHERE version=121")
            .fetchone()[0],
            1,
        )

    def test_authored_announcement_is_preserved_verbatim(self):
        text = "管理员自定义活动：由管理员审核后手动发放15积分，非自动奖励。"
        before = self.announcement(text)
        with self.db.transaction() as tx:
            tx.execute(self.sql)
        after = json.loads(
            self.db.get_conn()
            .execute("SELECT value_json FROM site_settings WHERE key='announcement'")
            .fetchone()[0]
        )
        self.assertEqual(before, after)
