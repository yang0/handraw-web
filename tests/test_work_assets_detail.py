"""Generated work detail metadata contracts: singular style, batch and read-only recovery."""
import json
import sqlite3
import unittest

from backend.generation_works import (
    extract_generation_styles_and_layout,
    recover_generation_work_assets,
)


class GenerationWorkAssetDetailTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE generation_runs (
                id TEXT PRIMARY KEY, user_id INTEGER, source TEXT, external_run_id TEXT
            );
            CREATE TABLE studio_generations (
                id TEXT PRIMARY KEY, user_id INTEGER, status TEXT, batch_id TEXT,
                deleted_at TEXT, batch_index INTEGER, created_at TEXT,
                items_json TEXT, system_append_json TEXT, recipe_id TEXT, recipe_summary TEXT
            );
        """)

    def tearDown(self):
        self.conn.close()

    def test_singular_quick_and_batch_style_aliases(self):
        row = {
            "recipe_id": "", "recipe_summary": "",
            "system_append_json": json.dumps({"recipeSnapshot": {
                "style1": "FA-003", "style2": {"code": "FB-006"}, "layoutId": "SC-021"
            }})
        }
        styles, layout = extract_generation_styles_and_layout(self.conn, row, {
            "recipeSnapshot": {"styles": ["FC-009"], "layout": "IG-031"}
        })
        self.assertEqual(styles, ["FC-009", "FA-003", "FB-006"])
        self.assertEqual(layout, "IG-031")

    def test_read_only_recovery_on_existing_work(self):
        self.conn.execute(
            "INSERT INTO generation_runs VALUES(?,?,?,?)", ("run_1", 7, "web", "batch_1")
        )
        self.conn.execute(
            "INSERT INTO studio_generations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("gen_1", 7, "success", "batch_1", "", 0, "2026-01-01",
             json.dumps([{"imageUrl":"/original.webp", "recipeSnapshot":{"style1":"FA-018"}}]),
             json.dumps({"recipeSnapshot":{"layout":"IG-006"}}), "", "")
        )
        self.conn.commit()
        styles, layout = recover_generation_work_assets(self.conn, {"run_id":"run_1"})
        self.assertEqual(styles, ["FA-018"])
        self.assertEqual(layout, "IG-006")

    def test_recovery_cannot_use_other_users_generation(self):
        self.conn.execute(
            "INSERT INTO generation_runs VALUES(?,?,?,?)", ("run_2", 7, "web", "run_external")
        )
        self.conn.execute(
            "INSERT INTO studio_generations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("run_external", 99, "success", "", "", 0, "2026-01-01",
             json.dumps([{"imageUrl":"/other.webp"}]),
             json.dumps({"recipeSnapshot":{"style1":"FA-111"}}), "", "")
        )
        self.conn.commit()
        self.assertEqual(recover_generation_work_assets(self.conn, {"run_id":"run_2"}), ([], ""))

    def test_nonweb_work_never_reads_web_generation(self):
        self.conn.execute("INSERT INTO generation_runs VALUES(?,?,?,?)", ("run_skill", 7, "skill", "x"))
        self.conn.commit()
        self.assertEqual(recover_generation_work_assets(self.conn, {"run_id":"run_skill"}), ([], ""))


if __name__ == "__main__":
    unittest.main()
