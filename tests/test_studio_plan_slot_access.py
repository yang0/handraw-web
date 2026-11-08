"""Studio 2.0 #121: authoritative server checks for PlanSlot media/catalog rights."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_projects import create_project, get_project


class PlanSlotAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "studio121.sqlite3")
        self.db.migrate()
        self.owner, _ = register_user(self.db, "golden_owner", "Pass12345!")
        self.other, _ = register_user(self.db, "golden_other", "Pass12345!")
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO user_uploads
                (id,user_id,cat,name_zh,image_url,created_at,asset_uid)
                VALUES (?,?,?,?,?,?,?)""", (
                    "golden-private-row", self.owner["id"], "scenes",
                    "私有参考图", "/private/golden.webp", "2026-11-08",
                    "golden-owned-media"
                ))
        self.counter = 0

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def create(self, slots, user=None):
        self.counter += 1
        return create_project(self.db, user or self.owner, {
            "projectId": f"golden-plan-{self.counter:04d}",
            "idempotencyKey": f"golden-plan-key-{self.counter:06d}",
            "kind": "series", "title": "Studio#121 黄金分镜",
            "authority": "spec",
            "draft": {
                "creationSpec": {
                    "style": {"id": "FA-001", "type": "style",
                              "source": "official", "version": 1}
                },
                "plan": {
                    "planId": "fixed-6", "revision": 3,
                    "kind": "story-series", "slots": slots
                },
                "activeView": "simple"
            }
        })

    def slot(self, media_id="golden-owned-media", overrides=None):
        return {
            "slotId": "slot-3", "order": 2, "subject": "龙井茶园",
            "lockedFields": ["layout"],
            "overrides": overrides or {
                "layout": {"id": "SC-022", "type": "layout",
                           "source": "official", "version": 1}},
            "referenceMedia": [{"mediaId": media_id, "role": "scene"}]
        }

    def test_private_media_in_plan_slot_requires_same_owner(self):
        done = self.create([self.slot()])
        draft = get_project(self.db, self.owner, done["projectId"])["project"]["draft"]
        self.assertEqual(draft["plan"]["slots"][0]["referenceMedia"][0]["mediaId"],
                         "golden-owned-media")
        with self.assertRaises(ServiceError) as context:
            self.create([self.slot()], user=self.other)
        self.assertEqual(context.exception.code, "project_media_forbidden")
        self.assertEqual(context.exception.status, 403)

    def test_missing_or_deleted_media_block_project_save(self):
        with self.assertRaises(ServiceError) as context:
            self.create([self.slot("missing-media-uid")])
        self.assertEqual(context.exception.code, "project_media_forbidden")
        with self.db.transaction() as tx:
            tx.execute("UPDATE user_uploads SET deleted_at=? WHERE asset_uid=?",
                       ("2026-11-08", "golden-owned-media"))
        with self.assertRaises(ServiceError) as context:
            self.create([self.slot()])
        self.assertEqual(context.exception.code, "project_media_forbidden")

    def test_catalog_type_and_revision_cannot_be_faked_by_slot(self):
        for ref, error_code in [
            ({"id": "FA-001", "type": "layout"}, "resource_not_found"),
            ({"id": "SC-022", "type": "style"}, "resource_type_mismatch"),
            ({"id": "SC-022", "type": "layout", "source": "official", "version": 9999},
             "resource_version_conflict")
        ]:
            with self.subTest(ref=ref), self.assertRaises(ServiceError) as context:
                self.create([self.slot(overrides={"layout": ref})])
            self.assertEqual(context.exception.code, error_code)

    def test_private_catalog_entitlement_must_be_checked_again(self):
        private_ref = {"id": "USR-HIDDEN", "type": "style",
                       "source": "private", "version": 4}
        blocked = {"id": "USR-HIDDEN", "kind": "style", "source": "private",
                   "canUse": False, "access": {"canUse": False},
                   "_raw_row": {"revision": 4}}
        with patch("backend.resource_registry.resolve", return_value=blocked):
            with self.assertRaises(ServiceError) as context:
                self.create([self.slot(overrides={"style": private_ref})])
        self.assertEqual(context.exception.code, "resource_forbidden")
        self.assertEqual(context.exception.status, 403)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
