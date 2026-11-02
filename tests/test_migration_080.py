"""Tests for Stage 1: Migration 080 & 081 (listed_at_ms, work_id uniqueness, deduplication)."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.work_schema import (
    audit_and_deduplicate_work_topics,
    FORUM_TOPICS_LISTED_AT_SQL,
    FORUM_TOPICS_WORK_UNIQUE_SQL,
)


class Migration080Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_m80.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp_dir.cleanup()

    def test_migrate_fresh_db_creates_column_and_indexes(self) -> None:
        # Full migration from scratch
        applied = self.db.migrate()
        self.assertIn("080_forum_topics_listed_at_ms", applied)
        self.assertIn("081_forum_topics_work_unique", applied)

        conn = self.db.get_conn()
        # Verify listed_at_ms column exists
        col_info = conn.execute("PRAGMA table_info(forum_topics)").fetchall()
        col_names = [c["name"] for c in col_info]
        self.assertIn("listed_at_ms", col_names)

        # Verify index idx_forum_topics_work_id exists
        indexes = conn.execute("PRAGMA index_list(forum_topics)").fetchall()
        idx_names = [idx["name"] for idx in indexes]
        self.assertIn("idx_forum_topics_work_id", idx_names)
        self.assertIn("idx_forum_topics_pinned_listed", idx_names)

        # Verify idempotency: second migrate run applies 0 migrations
        second_applied = self.db.migrate()
        self.assertEqual(second_applied, [])

    def test_deduplicate_historical_duplicate_work_topics(self) -> None:
        # Initialize up to migration 79
        conn = self.db.get_conn()
        # Run migrations
        self.db.migrate()

        # Artificially drop the unique index to simulate pre-migration state with duplicate work_id
        conn.execute("DROP INDEX IF EXISTS idx_forum_topics_work_id")

        now_iso = "2026-11-01T12:00:00Z"
        # Create work
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, prompt, images_json, status, published_at_ms, created_at, updated_at)
            VALUES ('work_dup_1', 'alice', 'Alice', 'Work 1', 'prompt', '["/img/1.png"]', 'published', 1000, ?, ?)
            """,
            (now_iso, now_iso),
        )

        # Insert topic 1 (primary: mapped in curation_resource_topics + has 2 replies)
        conn.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, styles_json, layout_code, work_id, status, published_at_ms, created_at, updated_at
            ) VALUES (
                'topic_primary', 'showcase', '🎨 晒作品', 'Topic Primary', 'alice', 'Alice', '',
                '[]', '[]', '', 'work_dup_1', 'published', 1000, '2026-11-01T12:00:00Z', '2026-11-01T12:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
            VALUES ('work', 'work_dup_1', 'topic_primary', 'submission', ?)
            """,
            (now_iso,),
        )
        conn.execute(
            """
            INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, status, created_at)
            VALUES ('rep_1', 'topic_primary', 'bob', 'Bob', 'Great!', 'published', ?),
                   ('rep_2', 'topic_primary', 'charlie', 'Charlie', 'Nice!', 'published', ?)
            """,
            (now_iso, now_iso),
        )

        # Insert topic 2 (duplicate: not mapped, 0 replies, older or newer)
        conn.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, styles_json, layout_code, work_id, status, published_at_ms, created_at, updated_at
            ) VALUES (
                'topic_secondary', 'showcase', '🎨 晒作品', 'Topic Secondary', 'alice', 'Alice', '',
                '[]', '[]', '', 'work_dup_1', 'published', 1000, '2026-11-01T13:00:00Z', '2026-11-01T13:00:00Z'
            )
            """
        )

        # Insert non-work topics with empty work_id
        conn.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, styles_json, layout_code, work_id, status, published_at_ms, created_at, updated_at
            ) VALUES (
                'topic_non_work_1', 'chat', '闲聊', 'Non work 1', 'alice', 'Alice', '',
                '[]', '[]', '', '', 'published', 1000, '2026-11-01T14:00:00Z', '2026-11-01T14:00:00Z'
            ),
            (
                'topic_non_work_2', 'chat', '闲聊', 'Non work 2', 'bob', 'Bob', '',
                '[]', '[]', '', '', 'published', 1000, '2026-11-01T15:00:00Z', '2026-11-01T15:00:00Z'
            )
            """
        )

        # Execute deduplication
        manifest = audit_and_deduplicate_work_topics(conn)

        # Verify audit manifest
        self.assertEqual(len(manifest), 1)
        item = manifest[0]
        self.assertEqual(item["work_id"], "work_dup_1")
        self.assertEqual(item["primary_topic_id"], "topic_primary")
        self.assertEqual(item["primary_reply_count"], 2)
        self.assertEqual(item["unlinked_topic_ids"], ["topic_secondary"])

        # Verify DB state: topic_primary keeps work_dup_1, topic_secondary has work_id=''
        t1 = conn.execute("SELECT work_id FROM forum_topics WHERE id = 'topic_primary'").fetchone()
        t2 = conn.execute("SELECT work_id FROM forum_topics WHERE id = 'topic_secondary'").fetchone()
        self.assertEqual(t1["work_id"], "work_dup_1")
        self.assertEqual(t2["work_id"], "")

        # Verify old data is NOT lost on secondary topic
        t2_full = conn.execute("SELECT * FROM forum_topics WHERE id = 'topic_secondary'").fetchone()
        self.assertEqual(t2_full["title"], "Topic Secondary")
        self.assertEqual(t2_full["author_username"], "alice")

        # Verify audit_logs has record
        log_row = conn.execute(
            "SELECT * FROM audit_logs WHERE action = 'topic.deduplicate_work_id' AND target_id = 'topic_primary'"
        ).fetchone()
        self.assertIsNotNone(log_row)
        log_details = json.loads(log_row["details_json"])
        self.assertEqual(log_details["work_id"], "work_dup_1")
        self.assertEqual(log_details["unlinked_topic_id"], "topic_secondary")

        # Now recreation of unique index succeeds
        conn.executescript(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_forum_topics_work_id ON forum_topics(work_id) WHERE work_id <> '' AND work_id IS NOT NULL;"
        )

        # Multiple empty work_ids are allowed
        nw1 = conn.execute("SELECT work_id FROM forum_topics WHERE id = 'topic_non_work_1'").fetchone()
        nw2 = conn.execute("SELECT work_id FROM forum_topics WHERE id = 'topic_non_work_2'").fetchone()
        self.assertEqual(nw1["work_id"], "")
        self.assertEqual(nw2["work_id"], "")

        # Attempting to insert duplicate work_dup_1 raises IntegrityError
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO forum_topics (
                    id, category, category_label, title, author_username, author_name, summary,
                    images_json, styles_json, layout_code, work_id, status, published_at_ms, created_at, updated_at
                ) VALUES (
                    'topic_conflict', 'showcase', '🎨 晒作品', 'Topic Conflict', 'alice', 'Alice', '',
                    '[]', '[]', '', 'work_dup_1', 'published', 1000, '2026-11-01T16:00:00Z', '2026-11-01T16:00:00Z'
                )
                """
            )

        # Second deduplication run returns empty list (idempotent)
        second_manifest = audit_and_deduplicate_work_topics(conn)
        self.assertEqual(second_manifest, [])

    def test_migrate_on_database_with_preexisting_duplicate_work_topics(self) -> None:
        """Simulate a database migrated up to 079 having duplicate work_id, then running 080+081."""
        conn = self.db.get_conn()
        from backend.migrations import MIGRATIONS, POST_MIGRATION_HOOKS
        now_iso = "2026-11-01T12:00:00Z"

        # Apply migrations 1..79 only
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        for v, name, ddl in MIGRATIONS:
            if v >= 80:
                continue
            conn.executescript(f"BEGIN IMMEDIATE;\n{ddl}\n;\nINSERT INTO schema_migrations VALUES ({v}, '{name}', '{now_iso}');\nCOMMIT;")
            if v in POST_MIGRATION_HOOKS:
                POST_MIGRATION_HOOKS[v](conn)

        # Seed pre-existing duplicate work topics
        conn.execute(
            """
            INSERT INTO works (id, author_username, author_name, title, prompt, images_json, status, published_at_ms, created_at, updated_at)
            VALUES ('work_pre_dup', 'bob', 'Bob', 'Pre Dup Work', 'p', '["/img/p.png"]', 'published', 2000, ?, ?)
            """,
            (now_iso, now_iso),
        )
        conn.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, styles_json, layout_code, work_id, status, published_at_ms, created_at, updated_at
            ) VALUES (
                'topic_pre_1', 'showcase', '🎨 晒作品', 'Topic Pre 1', 'bob', 'Bob', '',
                '[]', '[]', '', 'work_pre_dup', 'published', 2000, '2026-11-01T12:00:00Z', '2026-11-01T12:00:00Z'
            ),
            (
                'topic_pre_2', 'showcase', '🎨 晒作品', 'Topic Pre 2', 'bob', 'Bob', '',
                '[]', '[]', '', 'work_pre_dup', 'published', 2000, '2026-11-01T13:00:00Z', '2026-11-01T13:00:00Z'
            )
            """
        )

        # Run migrate() - this will apply 080 (which deduplicates via hook) and 081 (unique index)
        applied = self.db.migrate()
        self.assertIn("080_forum_topics_listed_at_ms", applied)
        self.assertIn("081_forum_topics_work_unique", applied)

        # Verify duplicate was resolved and unique index is active
        t1 = conn.execute("SELECT work_id FROM forum_topics WHERE id = 'topic_pre_1'").fetchone()
        t2 = conn.execute("SELECT work_id FROM forum_topics WHERE id = 'topic_pre_2'").fetchone()
        self.assertEqual(t1["work_id"], "work_pre_dup")
        self.assertEqual(t2["work_id"], "")


if __name__ == "__main__":
    unittest.main()
