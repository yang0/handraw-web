"""PostgreSQL maintenance command integration tests."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ops import export_official_assets, reconcile_social_counters, refresh_content
from tests.postgres_support import isolated_pg_dsn


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class PostgresOperationsTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.dsn = self.enterContext(isolated_pg_dsn())
        self.conn = self.enterContext(psycopg.connect(self.dsn, autocommit=True))
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DATABASE_URL": self.dsn, "HANDRAW_REDIS_URL": ""}))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def seed_social_drift(self):
        self.conn.execute("""
            INSERT INTO users(id, username, display_name, invite_code, password_hash, created_at)
            VALUES (51, 'reader', 'Reader', 'reader-ops', '', ''),
                   (52, 'reader_two', 'Reader two', 'reader-two-ops', '', '')
        """)
        self.conn.execute("""
            INSERT INTO works(id, author_username, author_name, title, prompt, published_at_ms, created_at, updated_at,
                              likes, favorites, cheers, forks)
            VALUES ('same-id', 'author', 'Author', 'Work', '', 1, '', '', 99, 42, 7, 8)
        """)
        self.conn.execute("""
            INSERT INTO forum_topics(id, category, category_label, title, author_username, author_name,
                                     summary, published_at_ms, created_at, updated_at, likes, favorites)
            VALUES ('same-id', 'general', 'General', 'Topic', 'author', 'Author', '', 1, '', '', 19, 9),
                   ('clean', 'general', 'General', 'Clean', 'author', 'Author', '', 1, '', '', 0, 0)
        """)
        self.conn.execute("""
            INSERT INTO interactions(user_id, target_type, target_id, stamp_label, created_at)
            VALUES (51, 'like_work', 'same-id', '', ''), (52, 'like_work', 'same-id', 'ignored', ''),
                   (51, 'like_topic', 'same-id', '', ''), (52, 'like_topic', 'same-id', '', ''),
                   (51, 'work', 'same-id', 'cheer', '')
        """)
        self.conn.execute("""
            INSERT INTO collections(user_id, bucket, target_id, created_at)
            VALUES (51, 'works', 'same-id', '')
        """)
        self.conn.execute("""
            INSERT INTO work_forks(work_id, user_id, first_generation_id, created_at)
            VALUES ('same-id', 51, 'source', '')
        """)

    def read_counts(self):
        work = self.conn.execute("SELECT likes, favorites, cheers, forks FROM works WHERE id='same-id'").fetchone()
        topic = self.conn.execute("SELECT likes, favorites FROM forum_topics WHERE id='same-id'").fetchone()
        return work, topic

    def test_reconcile_read_only_bulk_repair_and_repeat(self):
        import psycopg
        from psycopg import sql

        self.seed_social_drift()
        before = self.read_counts()
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(reconcile_social_counters.main([]), 0)
        self.assertIn("作品计数不一致：1", stdout.getvalue())
        self.assertIn("帖子计数不一致：1", stdout.getvalue())
        self.assertEqual(self.read_counts(), before)

        def inspect_backup(dsn, snapshot, directory):
            self.assertEqual(directory, self.root)
            with psycopg.connect(dsn) as conn:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.execute(sql.SQL("SET TRANSACTION SNAPSHOT {}").format(sql.Literal(snapshot)))
                self.assertEqual(conn.execute("SELECT likes FROM works WHERE id='same-id'").fetchone(), (99,))
            return self.root / "test.dump"

        args = ["--apply", "--backup-dir", str(self.root)]
        with patch.object(reconcile_social_counters, "dump_snapshot", side_effect=inspect_backup) as backup:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(reconcile_social_counters.main(args), 0)
                self.assertEqual(reconcile_social_counters.main(args), 0)
            backup.assert_called_once()
        self.assertEqual(self.read_counts(), ((1, 1, 1, 1), (2, 0)))

    def test_reconcile_rolls_back_after_concurrent_write(self):
        self.seed_social_drift()

        def update_during_backup(*_args):
            with self.conn.transaction():
                self.conn.execute("""
                    INSERT INTO interactions(user_id,target_type,target_id,created_at)
                    VALUES (52, 'like_work', 'same-id', '')
                """)
                self.conn.execute("UPDATE works SET likes=likes+1 WHERE id='same-id'")
            return self.root / "test.dump"

        with patch.object(reconcile_social_counters, "dump_snapshot", side_effect=update_during_backup):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(reconcile_social_counters.main(["--apply", "--backup-dir", str(self.root)]), 1)
        self.assertIn("事务已回滚", error.getvalue())
        self.assertEqual(self.read_counts(), ((100, 42, 7, 8), (19, 9)))

    def test_reconcile_preserves_counters_when_backup_fails(self):
        self.seed_social_drift()
        before = self.read_counts()
        with patch.object(reconcile_social_counters, "dump_snapshot", side_effect=OSError("backup disk unavailable")):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(OSError, "backup disk unavailable"):
                reconcile_social_counters.main(["--apply", "--backup-dir", str(self.root)])
        self.assertEqual(self.read_counts(), before)

    def seed_asset(self, code, cost, source="official"):
        self.conn.execute("""
            INSERT INTO catalog_assets(code, name, kind, source_type, definition, unlock_cost,
                                       image_url, published_at_ms, created_at, updated_at)
            VALUES (%s, %s, 'style', %s, %s, %s, '', 1, '', '')
        """, (code, code, source, f"定义 {code}", cost))

    def write_skill(self, styles):
        skill = self.root / "skill"
        references = skill / "references"
        references.mkdir(parents=True, exist_ok=True)
        (references / "styles.json").write_text(json.dumps(styles, ensure_ascii=False), encoding="utf-8")
        (references / "layouts.json").write_text("[]", encoding="utf-8")
        return skill

    def test_export_blocks_code_collision_and_omits_paid_definition(self):
        self.seed_asset("FE-069", 0)
        self.seed_asset("FE-070", 5)
        self.seed_asset("FE-071", 0, source="community")
        skill = self.write_skill([{"number": "FE-069", "generation_name": "Conflict"}])
        out = self.root / "export"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as missing:
            export_official_assets.main(["--out", str(out)])
        self.assertEqual(missing.exception.code, 2)
        args = ["--skill-root", str(skill), "--out", str(out)]
        with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as collision:
            export_official_assets.main(args)
        self.assertEqual(collision.exception.code, 2)
        self.assertIn("FE-069", error.getvalue())
        self.assertFalse(out.exists())
        self.write_skill([])
        with contextlib.redirect_stdout(io.StringIO()):
            export_official_assets.main(args)
        items = json.loads((out / "styles.json").read_text(encoding="utf-8"))
        self.assertEqual([item["number"] for item in items], ["FE-069", "FE-070"])
        self.assertEqual(items[0]["definition"], "定义 FE-069")
        self.assertNotIn("definition", items[1])

    def test_refresh_requires_approval_and_syncs_only_matching_official_rows(self):
        self.seed_asset("FE-099", 0)
        self.seed_asset("FE-098", 0)
        self.seed_asset("FE-097", 0, source="community")
        skill = self.write_skill([{"number": code} for code in ("FE-001", "FE-099", "FE-097")])
        content = self.root / "content"
        content.mkdir()
        catalog = content / "catalog.json"
        original = '{"resources":[{"id":"FE-001","kind":"style","name":"Preserved"}]}'
        catalog.write_text(original, encoding="utf-8")
        (content / "editorial.json").write_text('{"featured":[{"id":"FE-001"}]}', encoding="utf-8")
        base_args = [str(skill), "--worktree"]
        with patch.object(refresh_content, "CONTENT_DIR", content):
            with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
                refresh_content.main(base_args)
            self.assertIn("FE-099", error.getvalue())
            self.assertEqual(catalog.read_text(encoding="utf-8"), original)
            with contextlib.redirect_stdout(io.StringIO()):
                refresh_content.main([*base_args, "--accept", "FE-097", "--sync-overrides"])
                refresh_content.main([*base_args, "--sync-overrides"])
        resources = json.loads(catalog.read_text(encoding="utf-8"))["resources"]
        self.assertEqual(resources[0]["name"], "Preserved")
        rows = dict(self.conn.execute("SELECT code, source_type FROM catalog_assets").fetchall())
        self.assertEqual(rows, {"FE-097": "community", "FE-098": "official", "FE-099": "official_override"})
