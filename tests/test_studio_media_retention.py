"""Normalized article/canvas references protect the underlying private object."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import utc_now_iso
from backend.generation_v3 import _upsert_media
from backend.media_gc import drain_media_gc, queue_media_cleanup
from backend.services import register_user, sync_user_studio_articles
from backend.studio_canvases import save_canvas
from backend.user_library import is_media_referenced
from tests.postgres_support import open_isolated_postgres
from tests.test_studio_canvases import graph


class StudioMediaRetentionTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "HANDRAW_PRIVATE_STORAGE": str(root),
                    "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                },
            )
        )
        self.file = root / "uploads" / "retained.webp"
        self.file.parent.mkdir()
        self.file.write_bytes(b"private-fixture")
        self.url = "/uploads/retained.webp"
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "media_retention", "FixturePass123!")

    def collect(self):
        with self.db.transaction() as tx:
            queue_media_cleanup(tx, self.url, delay_seconds=0)
            tx.execute(
                "UPDATE media_gc_jobs SET next_attempt_at=0,claim_until=0 WHERE media_url=?",
                (self.url,),
            )
        return drain_media_gc(self.db, limit=1)

    def test_article_selection_survives_without_legacy_cards_or_upload_rows(self):
        with self.db.transaction() as tx:
            _upsert_media(tx, owner_id=self.user["id"], url=self.url)
        sync_user_studio_articles(
            self.db,
            self.user,
            [
                {
                    "id": "article",
                    "markdown": "body",
                    "cards": [
                        {"id": "cover", "prompt": "drawing", "imageUrl": self.url}
                    ],
                }
            ],
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT cards_json FROM studio_articles")
            .fetchone()[0],
            "[]",
        )
        self.assertTrue(
            is_media_referenced(self.db.get_conn(), self.url, str(self.file))
        )
        self.assertEqual(self.collect()["referenced"], 1)
        self.assertTrue(self.file.is_file())

    def test_canvas_reference_group_protects_file_and_deleted_canvas_releases_it(self):
        save_canvas(
            self.db,
            self.user,
            {
                "id": "canvas",
                "graph": graph(("prompt", ["A"]), ("refImages", [[self.url]])),
            },
        )
        self.assertEqual(self.collect()["referenced"], 1)
        self.assertTrue(self.file.is_file())
        self.db.get_conn().execute(
            "UPDATE studio_canvases SET deleted_at=now() WHERE id='canvas'"
        )
        self.assertEqual(self.collect()["deleted"], 1)
        self.assertFalse(self.file.exists())

    def test_attempt_receipt_protects_secondary_media_without_a_gallery_or_task_media(
        self,
    ):
        with self.db.transaction() as tx:
            mid = _upsert_media(tx, owner_id=self.user["id"], url=self.url)
            tx.execute(
                "INSERT INTO studio_generations(id,user_id,username,status,created_at) VALUES('attempt',?,?,'success',?)",
                (self.user["id"], self.user["username"], utc_now_iso()),
            )
            tx.execute(
                "INSERT INTO generation_attempt_media(attempt_id,media_id,ordinal) VALUES('attempt',?,1)",
                (mid,),
            )
        self.assertEqual(self.collect()["referenced"], 1)
        self.assertTrue(self.file.exists())
