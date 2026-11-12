"""Optimistic article syncing protects remote edits and atomic batches."""
import tempfile
import unittest
from pathlib import Path
from tests.legacy_database import Database
from backend.services import ServiceError, register_user, sync_user_studio_articles


class ArticleVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "version.db")
        self.db.migrate()
        self.alice, _ = register_user(self.db, "version_alice", "Pass12345!", "version-alice@example.com", "Alice", "invite-a")
        self.bob, _ = register_user(self.db, "version_bob", "Pass12345!", "version-bob@example.com", "Bob", "invite-b")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def current(self, aid):
        return self.db.get_conn().execute(
            "SELECT markdown, updated_at_ms FROM studio_articles WHERE id = ?", (aid,)
        ).fetchone()

    def test_stale_edit_fails_without_overwriting_current_article(self):
        created = sync_user_studio_articles(
            self.db, self.alice, [{"id":"v_a", "markdown":"Version one", "baseUpdatedAtMs":0}]
        )
        v1 = created["versions"]["v_a"]
        changed = sync_user_studio_articles(
            self.db, self.alice, [{"id":"v_a", "markdown":"Version two", "baseUpdatedAtMs":v1}]
        )
        v2 = changed["versions"]["v_a"]
        self.assertGreater(v2, v1)
        with self.assertRaises(ServiceError) as error:
            sync_user_studio_articles(
                self.db, self.alice,
                [{"id":"v_a", "markdown":"Stale write", "baseUpdatedAtMs":v1}]
            )
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(error.exception.code, "article_version_conflict")
        self.assertEqual(self.current("v_a")["markdown"], "Version two")

    def test_noop_workspace_sync_does_not_advance_revision(self):
        initial = sync_user_studio_articles(self.db, self.alice, [
            {"id":"noop", "articleTitle":"No-op", "markdown":"same", "baseUpdatedAtMs":0}
        ])["versions"]["noop"]
        again = sync_user_studio_articles(self.db, self.alice, [
            {"id":"noop", "articleTitle":"No-op", "markdown":"same", "baseUpdatedAtMs":initial}
        ])["versions"]["noop"]
        self.assertEqual(again, initial)
        self.assertEqual(self.current("noop")["markdown"], "same")

    def test_conflict_rolls_back_earlier_batch_writes(self):
        versions = sync_user_studio_articles(
            self.db, self.alice, [
                {"id":"batch_a", "markdown":"A1", "baseUpdatedAtMs":0},
                {"id":"batch_b", "markdown":"B1", "baseUpdatedAtMs":0},
            ]
        )["versions"]
        sync_user_studio_articles(
            self.db, self.alice, [
                {"id":"batch_b", "markdown":"B2", "baseUpdatedAtMs":versions["batch_b"]},
            ]
        )
        with self.assertRaises(ServiceError):
            sync_user_studio_articles(self.db, self.alice, [
                {"id":"batch_a", "markdown":"A stale", "baseUpdatedAtMs":versions["batch_a"]},
                {"id":"batch_b", "markdown":"B stale", "baseUpdatedAtMs":versions["batch_b"]},
            ])
        self.assertEqual(self.current("batch_a")["markdown"], "A1")
        self.assertEqual(self.current("batch_b")["markdown"], "B2")

    def test_conflicting_creation_and_other_user_id_never_overwrite(self):
        sync_user_studio_articles(self.db, self.alice, [
            {"id":"id_taken", "markdown":"Original", "baseUpdatedAtMs":0}
        ])
        with self.assertRaises(ServiceError) as error:
            sync_user_studio_articles(self.db, self.bob, [
                {"id":"id_taken", "markdown":"Attack", "baseUpdatedAtMs":0}
            ])
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.current("id_taken")["markdown"], "Original")

    def test_deleted_draft_rejected_and_legacy_skipped(self):
        sync_user_studio_articles(self.db, self.alice, [
            {"id":"deleted_art", "markdown":"Old", "baseUpdatedAtMs":0}
        ])
        with self.db.transaction() as tx:
            tx.execute("UPDATE studio_articles SET deleted_at = '2026-11-07T00:00:00Z' WHERE id = 'deleted_art'")
        with self.assertRaises(ServiceError) as error:
            sync_user_studio_articles(self.db, self.alice, [
                {"id":"deleted_art", "markdown":"Resurrection", "baseUpdatedAtMs":0}
            ])
        self.assertEqual(error.exception.code, "article_deleted")
        result = sync_user_studio_articles(self.db, self.alice, [
            {"id":"deleted_art", "markdown":"Legacy resurrection"},
        ])
        self.assertNotIn("deleted_art", result["versions"])
        self.assertEqual(self.current("deleted_art")["markdown"], "Old")


if __name__ == "__main__":
    unittest.main()
