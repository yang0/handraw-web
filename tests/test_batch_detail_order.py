"""V3: batch detail shows ordered media inside ONE canonical public work."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.db import Database
from backend.generation_works import project_generation_to_works
from backend.post_routes import _handle_detail
from backend.services import register_user
from backend.works_feed import get_work_by_id

IMAGES = [
    "/images/individual/FA/FA-013.webp",
    "/images/individual/FA/FA-014.webp",
    "/images/individual/FA/FA-015.webp",
]


class BatchDetailOrderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "batch.db")
        self.db.migrate()
        author, _ = register_user(
            self.db, "batch_order_author", "IsolatedBatchPassword!",
        )
        self.author = author
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations
                   (id,user_id,username,tab_title,mode,prompt,visible_prompt,
                    items_json,engine,status,created_at,visibility)
                VALUES ('order_v3',?,?,?,?,?,?,?,'live','success',?,'public')
                """,
                (
                    author["id"], author["username"], "手绘三张插画",
                    "graphic-text", "春日主题", "春日主题",
                    json.dumps([
                        {"id": "z_first", "imageUrl": IMAGES[0],
                         "recipeSnapshot": {"style1": "FA-011", "layout": "SC-001"}},
                        {"id": "b_second", "imageUrl": IMAGES[1],
                         "recipeSnapshot": {"style1": "FB-022", "layout": "IG-006"}},
                        {"id": "a_third", "imageUrl": IMAGES[2],
                         "recipeSnapshot": {"style1": "FC-033", "layout": "SB-003"}},
                    ]),
                    "2026-11-07T00:00:00Z",
                ),
            )
            ids = project_generation_to_works(tx, "order_v3")
        self.assertEqual(len(ids), 1)
        self.work_id = ids[0]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_ordered_media_on_work_and_post_detail(self):
        work = get_work_by_id(self.db, self.work_id)
        self.assertEqual(work["images"], IMAGES)
        self.assertEqual(
            [(item["styles"], item["layout"]) for item in work["imageAssets"]],
            [
                (["FA-011"], "SC-001"),
                (["FB-022"], "IG-006"),
                (["FC-033"], "SB-003"),
            ],
        )
        self.assertEqual(work["batchTotal"], 1)
        conn = self.db.get_conn()
        topic = conn.execute(
            "SELECT id FROM forum_topics WHERE work_id=?", (self.work_id,),
        ).fetchone()
        self.assertIsNotNone(topic)

        output = []
        handler = SimpleNamespace(
            db=self.db,
            _current_user=lambda required=False: None,
            _send_json=output.append,
        )
        self.assertTrue(_handle_detail(handler, topic["id"]))
        self.assertEqual(output[-1]["mount"]["kind"], "work")
        detail = output[-1]["mount"]["work"]
        self.assertEqual(detail["images"], IMAGES)
        self.assertEqual(
            [(item["url"], item["layout"]) for item in detail["imageAssets"]],
            list(zip(IMAGES, ["SC-001", "IG-006", "SB-003"])),
        )
        self.assertEqual(detail["batchWorks"], [])
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM work_media WHERE work_id=?", (self.work_id,),
        ).fetchone()[0], 3)
        self.assertEqual(json.loads(conn.execute(
            "SELECT images_json FROM forum_topics WHERE id=?", (topic["id"],),
        ).fetchone()[0]), IMAGES)

    def test_replay_keeps_one_work_and_one_cover(self):
        with self.db.transaction() as tx:
            self.assertEqual(
                project_generation_to_works(tx, "order_v3"), [self.work_id],
            )
        conn = self.db.get_conn()
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM works WHERE run_id IS NOT NULL"
        ).fetchone()[0], 1)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM work_media WHERE work_id=?", (self.work_id,),
        ).fetchone()[0], 3)
        self.assertEqual(conn.execute(
            "SELECT cover_media_id FROM works WHERE id=?", (self.work_id,),
        ).fetchone()[0], conn.execute(
            "SELECT media_id FROM work_media WHERE work_id=? ORDER BY position LIMIT 1",
            (self.work_id,),
        ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
