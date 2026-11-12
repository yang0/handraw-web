"""Issue #158: forum series prompt follows its exact public image without leaks."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.postgres_support import open_isolated_postgres
from backend.services import register_user
from backend.generation_works import project_generation_to_works, generation_image_assets


class ForumSeriesPromptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "seriesprompt", "Password123!")
        self.conn = self.db.get_conn()

    def tearDown(self):
        self.db.close()
        self.folder.cleanup()

    def test_different_image_prompts_match_urls_and_respect_masking(self):
        # Out-of-order completions must not reorder their approved prompts.
        for index, prompt, masked in [
            (2, "图三：金色街道", 0),
            (0, "图一：蓝色海岸", 0),
            (1, "图二：敏感内容，必须隐藏", 1),
        ]:
            self.conn.execute(
                """
                INSERT INTO studio_generations (
                  id,user_id,username,tab_title,mode,prompt,visible_prompt,prompt_masked,
                  items_json,status,created_at,visibility,engine,
                  batch_id,batch_index,batch_total
                ) VALUES (?,?,?,?,?,?,?,?,?,'success',?,'public','live',?,?,?)
                """,
                (
                    f"prompt_slot_{index}", self.user["id"], self.user["username"],
                    "系列图", "graphic-text", "模型完整展开提示词（不是主题）",
                    "" if masked else "模型完整展开提示词（不是主题）", masked,
                    json.dumps([{"imageUrl": f"/generated/prompt_{index}.webp", "theme": prompt}]),
                    f"2026-11-11T00:0{index}:00Z", "prompt_batch", index, 3,
                ),
            )
            with self.db.transaction():
                ids = project_generation_to_works(self.conn, f"prompt_slot_{index}")
        work = self.conn.execute("SELECT * FROM works WHERE id=?", (ids[0],)).fetchone()
        urls = [f"/generated/prompt_{i}.webp" for i in range(3)]
        assets = generation_image_assets(self.conn, work, urls)
        self.assertEqual([a["url"] for a in assets], urls)
        self.assertEqual(assets[0]["prompt"], "图一：蓝色海岸")
        self.assertEqual(assets[1].get("prompt", ""), "")
        self.assertEqual(assets[2]["prompt"], "图三：金色街道")

    def test_saved_request_snapshot_theme_overrides_composed_visible_prompt(self):
        self.conn.execute(
            """
            INSERT INTO studio_generations (
              id,user_id,username,tab_title,mode,prompt,visible_prompt,prompt_masked,
              system_append_json,items_json,status,created_at,visibility,engine
            ) VALUES ('theme_snapshot',?,?,?,?,?,?,?,?,?,'success',
                      '2026-11-11T00:00:00Z','public','live')
            """,
            (
                self.user["id"], self.user["username"], "单张主题", "graphic-text",
                "完整模型执行提示词，含画风、图型、系统指令",
                "完整模型执行提示词，含画风、图型、系统指令",
                0,
                json.dumps({"recipeSnapshot": {"theme": "阳光下的小猫"}}),
                json.dumps(["/generated/theme_snapshot.webp"]),
            ),
        )
        with self.db.transaction():
            ids = project_generation_to_works(self.conn, "theme_snapshot")
        work = self.conn.execute("SELECT * FROM works WHERE id=?", (ids[0],)).fetchone()
        assets = generation_image_assets(self.conn, work, ["/generated/theme_snapshot.webp"])
        self.assertEqual(assets[0]["prompt"], "阳光下的小猫")
        self.assertNotIn("完整模型执行提示词", assets[0]["prompt"])

    def test_no_theme_never_falls_back_to_full_visible_prompt(self):
        self.conn.execute(
            """
            INSERT INTO studio_generations (
              id,user_id,username,tab_title,mode,prompt,visible_prompt,prompt_masked,
              items_json,status,created_at,visibility,engine
            ) VALUES ('no_theme',?,?,?,?,?,?,?,'["/generated/no_theme.webp"]',
                      'success','2026-11-11T00:00:00Z','public','live')
            """,
            (
                self.user["id"], self.user["username"], "旧版作品", "graphic-text",
                "旧版展开完整提示词", "旧版展开完整提示词", 0,
            ),
        )
        with self.db.transaction():
            ids = project_generation_to_works(self.conn, "no_theme")
        work = self.conn.execute("SELECT * FROM works WHERE id=?", (ids[0],)).fetchone()
        assets = generation_image_assets(self.conn, work, ["/generated/no_theme.webp"])
        self.assertEqual(assets[0].get("prompt", ""), "")

    def test_multi_output_row_cannot_claim_unique_prompt_for_each_image(self):
        self.conn.execute(
            """
            INSERT INTO studio_generations (
              id,user_id,username,tab_title,mode,prompt,visible_prompt,prompt_masked,
              items_json,status,created_at,visibility,engine
            ) VALUES ('group_images',?,?,?,?,?,?,?,?,'success','2026-11-11T00:00:00Z','public','live')
            """,
            (self.user["id"],self.user["username"],"多张", "graphic-text",
             "整组提示", "整组提示", 0,
             json.dumps(["/generated/multi_a.webp","/generated/multi_b.webp"])),
        )
        with self.db.transaction():
            ids = project_generation_to_works(self.conn, "group_images")
        work = self.conn.execute("SELECT * FROM works WHERE id=?", (ids[0],)).fetchone()
        assets = generation_image_assets(self.conn, work, [
            "/generated/multi_a.webp", "/generated/multi_b.webp"])
        self.assertTrue(all(asset.get("prompt", "") == "" for asset in assets))


if __name__ == "__main__":
    unittest.main()
