"""Tests for Stage 4: Backend Work-Topic redirects and canonical multi-image works."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.postgres_support import open_isolated_postgres
from backend.generation_works import project_generation_to_works
from backend.post_routes import _handle_detail, _handle_t_redirect, _resolve_ref_to_topic_id
from backend.services import register_user, utc_now_iso


class Stage4BackendRedirectsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_stage4_be.db"
        self._env = patch.dict(
            os.environ,
            {
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_DEMO_MODE": "1",
            },
        )
        self._env.start()
        self.db = open_isolated_postgres(self)
        self.db.migrate()
        self.conn = self.db.get_conn()

        self.alice, _ = register_user(self.db, "alice4", "pass-alice4")

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.conn.close()
        self.db.close()
        self._env.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_work_t_redirect_and_unlisted_detail(self) -> None:
        """Verify /t/work-{id} and /t/{id} redirect to /forum/?view=topic&id={topic_id}."""
        now_ms = int(time.time() * 1000)
        now_iso = utc_now_iso()

        # Insert a published work
        self.conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, notes, status,
                origin, published_at_ms, images_json, styles_json, created_at, updated_at
            ) VALUES ('w_test_401', 'alice4', 'Alice4', 'Test Work 401', 'prompt 401', 'Notes', 'published',
                      'web', ?, '["/img/401.png"]', '[]', ?, ?)
            """,
            (now_ms, now_iso, now_iso),
        )
        # Create unlisted topic
        self.conn.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, status, work_id, listed_at_ms, published_at_ms, created_label, created_at, updated_at
            ) VALUES ('top_test_401', 'showcase', '🎨 晒作品', 'Test Work 401', 'alice4', 'Alice4', '',
                      '["/img/401.png"]', 'published', 'w_test_401', NULL, ?, '刚刚', ?, ?)
            """,
            (now_ms, now_iso, now_iso),
        )
        self.conn.execute(
            """
            INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
            VALUES ('work', 'w_test_401', 'top_test_401', 'submission', ?)
            """,
            (now_iso,),
        )
        self.conn.commit()

        # 1. Resolve ref
        self.assertEqual(_resolve_ref_to_topic_id(self.conn, "w_test_401"), "top_test_401")
        self.assertEqual(_resolve_ref_to_topic_id(self.conn, "work-w_test_401"), "top_test_401")

        # 2. Redirect handler
        handler = MagicMock()
        handler.db = self.db
        handler._current_user.return_value = None

        _handle_t_redirect(handler, "work-w_test_401", qs={"focus": ["comment"]})
        handler.send_response.assert_called_with(302)
        handler.send_header.assert_any_call("Location", "/forum/?view=topic&id=top_test_401&focus=comment")

    def test_batch_generation_siblings_attached_in_detail(self) -> None:
        """Verify a work from a batch generation includes batchWorks siblings in post detail."""
        now_ms = int(time.time() * 1000)
        now_iso = utc_now_iso()

        # Simulate a 4-image generation projection
        gen_row = {
            "id": "gen_batch_99",
            "user_id": self.alice["id"],
            "username": self.alice["username"],
            "author_name": self.alice.get("display_name") or self.alice["username"],
            "subject": "batch generation subject",
            "mode": "quick",
            "engine": "dall-e-3",
            "aspect_ratio": "1:1",
            "image_count": 4,
            "items_json": json.dumps([
                {"id": "img_1", "imageUrl": "/img/gen1.png"},
                {"id": "img_2", "imageUrl": "/img/gen2.png"},
                {"id": "img_3", "imageUrl": "/img/gen3.png"},
                {"id": "img_4", "imageUrl": "/img/gen4.png"},
            ]),
            "styles_json": "[]",
            "layout_code": "",
            "reference_images_json": "[]",
            "status": "success",
            "visibility": "public",
            "created_at": now_iso,
            "completed_at": now_iso,
        }

        # V3 projects all four images into a single canonical work
        with self.db.transaction():
            work_ids = project_generation_to_works(self.conn, gen_row)
        self.assertEqual(len(work_ids), 1)

        # Check detail for first work's topic
        w1_id = work_ids[0]
        t1_id = self.conn.execute("SELECT id FROM forum_topics WHERE work_id = ?", (w1_id,)).fetchone()["id"]

        handler = MagicMock()
        handler.db = self.db
        handler._current_user.return_value = None

        with patch("backend.post_routes.forum_resources._unlocked", return_value=set()):
            _handle_detail(handler, t1_id)
            self.assertTrue(handler._send_json.called)
            resp = handler._send_json.call_args[0][0]
            self.assertTrue(resp["ok"])
            mount = resp["mount"]
            self.assertEqual(mount["kind"], "work")
            work = mount["work"]
            self.assertEqual(work["batchWorks"], [])
            self.assertEqual(len(work["images"]), 4)


if __name__ == "__main__":
    unittest.main()
