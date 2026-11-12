"""V3 public media grants must follow work/topic moderation state."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.legacy_database import Database
from backend.server import _is_published_media
from backend.services import register_user, set_work_visibility, utc_now_iso


class GeneratedMediaVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "0",
            "HANDRAW_LEGACY_PUBLIC_MEDIA_INFERENCE": "0",
        }))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "media_visibility.db")
        self.db.migrate()
        self.addCleanup(self.db.close)
        self.author, _ = register_user(
            self.db, "media_author", "SecurePassword123!",
        )
        self.url = "/generated/v3-public-media.png"
        self.work_id = "work_public_media"
        now = utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO works(
                    id,author_username,author_name,title,prompt,images_json,
                    status,published_at_ms,created_at,updated_at
                   ) VALUES (?,?,?,'Published','image prompt',?,
                             'published',0,?,?)""",
                (self.work_id,self.author["username"],self.author["username"],
                 f'["{self.url}"]',now,now),
            )
            tx.execute(
                """INSERT INTO media_public_grants(
                    id,media_url,owner_user_id,target_type,target_id,
                    granted_by_user_id,granted_at,revoked_at
                   ) VALUES ('grant_generated',?,?,'work',?,?,?,NULL)""",
                (self.url,self.author["id"],self.work_id,self.author["id"],now),
            )

    def test_moderator_hidden_work_revokes_public_access_without_deleting_grant(self):
        self.assertTrue(_is_published_media(self.db,self.url))
        with self.db.transaction() as tx:
            set_work_visibility(
                tx,self.work_id,"hidden",utc_now_iso(),
                source="moderator",reason="review",actor_role="admin",
            )
        self.assertFalse(_is_published_media(self.db,self.url))
        with self.db.transaction() as tx:
            set_work_visibility(
                tx,self.work_id,"published",utc_now_iso(),
                source="moderator",reason="reviewed",actor_role="admin",
            )
        self.assertTrue(_is_published_media(self.db,self.url))

    def test_deleted_work_cannot_leave_public_file_grant(self):
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM works WHERE id=?",(self.work_id,))
        self.assertFalse(_is_published_media(self.db,self.url))

    def test_unrelated_grant_does_not_expose_hidden_work(self):
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET status='hidden' WHERE id=?",(self.work_id,))
        self.assertFalse(_is_published_media(self.db,self.url))


if __name__ == "__main__":
    unittest.main()
