"""Generated work detail metadata contracts: singular style, batch and read-only recovery."""
import json
from tests.postgres_support import open_isolated_postgres
import unittest

from backend.generation_works import (
    extract_generation_styles_and_layout,
    recover_generation_work_assets,
    generation_image_assets,
)


class GenerationWorkAssetDetailTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self, initialize=False)
        self.conn = self.db.get_conn()
        self.conn.execute("""
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


    def test_per_image_metadata_follows_image_url_and_uses_item_override(self):
        self.conn.execute(
            "INSERT INTO generation_runs VALUES(?,?,?,?)",
            ("run_batch_1", 7, "web", "web_batch_1"),
        )
        for index, url, style, layout in [
            (0, "/image-a.webp", "FA-011", "SC-001"),
            (1, "/image-b.webp", "FB-022", "IG-006"),
        ]:
            self.conn.execute(
                "INSERT INTO studio_generations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"web_item_{index}", 7, "success", "web_batch_1", "",
                    index, f"2026-01-0{index+1}",
                    json.dumps([{"imageUrl": url, "recipeSnapshot": {
                        "style1": style, "layout": layout,
                    }}]),
                    json.dumps({"recipeSnapshot": {"style1": "FA-999", "layout": "SC-999"}}),
                    "", "",
                ),
            )
        result = generation_image_assets(
            self.conn, {"run_id": "run_batch_1"},
            ["/image-b.webp", "/image-a.webp"],
        )
        self.assertEqual(
            [(r["url"], r["styles"], r["layout"], r["scope"]) for r in result],
            [
                ("/image-b.webp", ["FB-022"], "IG-006", "image"),
                ("/image-a.webp", ["FA-011"], "SC-001", "image"),
            ],
        )

    def test_missing_image_does_not_inherit_first_image_metadata(self):
        self.conn.execute(
            "INSERT INTO generation_runs VALUES(?,?,?,?)",
            ("run_partial_1", 7, "web", "run_partial_source"),
        )
        self.conn.execute(
            "INSERT INTO studio_generations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "run_partial_source", 7, "success", "", "", 0, "2026-01-01",
                json.dumps([
                    {"imageUrl": "/first.webp", "style1": "FA-011", "layout": "SC-001"},
                    {"imageUrl": "/second.webp"},
                ]),
                "{}", "", "",
            ),
        )
        snapshots = generation_image_assets(
            self.conn, {"run_id": "run_partial_1"},
            ["/first.webp", "/second.webp"],
        )
        self.assertEqual(snapshots[0]["styles"], ["FA-011"])
        self.assertEqual(snapshots[0]["layout"], "SC-001")
        self.assertEqual(snapshots[1], {
            "url": "/second.webp", "styles": [], "layout": "", "scope": "missing",
        })

    def test_skill_and_other_users_runs_do_not_leak_web_metadata(self):
        self.conn.execute(
            "INSERT INTO generation_runs VALUES(?,?,?,?)",
            ("run_non_web", 7, "skill", "shared_1"),
        )
        self.conn.execute(
            "INSERT INTO generation_runs VALUES(?,?,?,?)",
            ("run_other", 7, "web", "shared_2"),
        )
        self.conn.execute(
            "INSERT INTO studio_generations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("shared_2", 99, "success", "", "", 0, "2026-01-01",
             json.dumps([{"imageUrl": "/secret.webp", "style1": "FA-017"}]),
             "{}", "", ""),
        )
        self.assertEqual(generation_image_assets(
            self.conn, {"run_id": "run_non_web"}, ["/secret.webp"],
        ), [])
        self.assertEqual(generation_image_assets(
            self.conn, {"run_id": "run_other"}, ["/secret.webp"],
        ), [])


if __name__ == "__main__":
    unittest.main()
