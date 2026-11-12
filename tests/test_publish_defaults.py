"""
Unit tests for publish defaults, prompt instruction filtering, and recipe snapshot persistence.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.services import (
    filter_display_prompt,
    get_studio_workspace,
    get_user_studio_task,
    prepare_cloud_generation,
    register_user,
)

INSTRUCTION_BLOCK = (
    "【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。"
    "如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，"
    "由你先设计画面隐喻（人类和非人类都行）再出图。文字参与构图，图文一体】"
)


class PublishDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
            },
        )
        self.env.start()
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "testuser", "TestPass123!")

    def tearDown(self) -> None:
        if hasattr(self, "db") and self.db:
            try:
                self.db.close()
            except Exception:
                pass
        self.env.stop()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_filter_display_prompt(self):
        # Empty / None
        self.assertEqual(filter_display_prompt(None), "")
        self.assertEqual(filter_display_prompt(""), "")

        # Pure instruction block
        self.assertEqual(filter_display_prompt(INSTRUCTION_BLOCK), "")

        # Instruction block with comma and period variations
        var_block = (
            "【如果主题直白包含画面元素那就按主题出图,文案由你来升华,但是不要直接描述画面."
            "如果主题比较概念化,那么文案和主题尽量保持一致,如果文案较长由你提炼,"
            "由你先设计画面隐喻(人类和非人类都行)再出图.文字参与构图,图文一体】"
        )
        self.assertEqual(filter_display_prompt(var_block), "")

        # User bracket preserved
        user_prompt = "【微距特写】雨后荷塘，一只青蛙坐在荷叶上"
        self.assertEqual(filter_display_prompt(user_prompt), user_prompt)

        # Mixed prompt
        mixed = f"{INSTRUCTION_BLOCK}\n\n【微距特写】雨后荷塘，一只青蛙坐在荷叶上\n画面清透自然"
        filtered = filter_display_prompt(mixed)
        self.assertNotIn("文案由你来升华", filtered)
        self.assertIn("【微距特写】雨后荷塘，一只青蛙坐在荷叶上", filtered)
        self.assertEqual(filtered, "【微距特写】雨后荷塘，一只青蛙坐在荷叶上\n画面清透自然")

    def test_recipe_snapshot_in_generation_and_workspace(self):
        snapshot = {
            "style1": "FA-002",
            "style1Name": "重彩青绿",
            "style2": "",
            "style2Name": "",
            "layout": "LAY-01",
            "layoutName": "三分构图",
        }
        body = {
            "prompt": "水墨山水画",
            "ratio": "3:4",
            "style": "FA-002",
            "style1": "FA-002",
            "recipeSnapshot": snapshot,
        }
        res = prepare_cloud_generation(self.db, self.user, body)
        self.assertIsNotNone(res)
        gen_id = res.get("genId")
        self.assertTrue(bool(gen_id))

        # Verify task details contain recipeSnapshot
        task_detail = get_user_studio_task(self.db, self.user, task_id=gen_id)
        self.assertIsNotNone(task_detail)
        self.assertEqual(task_detail.get("recipeSnapshot"), snapshot)

        # Verify workspace history returns recipeSnapshot
        ws = get_studio_workspace(self.db, self.user)
        self.assertIsNotNone(ws)
        hist = ws.get("history") or []
        self.assertGreaterEqual(len(hist), 1)
        found = next((e for e in hist if e.get("id") == gen_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found.get("recipeSnapshot"), snapshot)


if __name__ == "__main__":
    unittest.main()
