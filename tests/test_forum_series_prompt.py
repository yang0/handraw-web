"""Issue #158: forum series prompt follows its exact public image without leaks."""
import json
import tempfile
import unittest
from pathlib import Path

from backend.server import init_database
from backend.services import register_user
from backend.generation_works import project_generation_to_works, generation_image_assets


class ForumSeriesPromptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = init_database(Path(self.folder.name) / "series.db")
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
                    "系列图", "graphic-text", prompt,
                    "" if masked else prompt, masked,
                    json.dumps([f"/generated/prompt_{index}.webp"]),
                    f"2026-11-11T00:0{index}:00Z", "prompt_batch", index, 3,
                ),
            )
            ids = project_generation_to_works(self.conn, f"prompt_slot_{index}")
        work = self.conn.execute("SELECT * FROM works WHERE id=?", (ids[0],)).fetchone()
        urls = [f"/generated/prompt_{i}.webp" for i in range(3)]
        assets = generation_image_assets(self.conn, work, urls)
        self.assertEqual([a["url"] for a in assets], urls)
        self.assertEqual(assets[0]["prompt"], "图一：蓝色海岸")
        self.assertEqual(assets[1].get("prompt", ""), "")
        self.assertEqual(assets[2]["prompt"], "图三：金色街道")

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
        ids = project_generation_to_works(self.conn, "group_images")
        work = self.conn.execute("SELECT * FROM works WHERE id=?", (ids[0],)).fetchone()
        assets = generation_image_assets(self.conn, work, [
            "/generated/multi_a.webp", "/generated/multi_b.webp"])
        self.assertTrue(all(asset.get("prompt", "") == "" for asset in assets))


if __name__ == "__main__":
    unittest.main()
