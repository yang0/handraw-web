"""Historical data maintenance integration against native PostgreSQL."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.resource_discussions import ensure_topic
from backend.services import register_user
from ops import converge_asset_comments, converge_work_comments, ensure_resource_topics, purge_publish_time_forks
from ops.postgres_backup import restore_pg_archive
from tests.postgres_support import isolated_pg_dsn


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class MaintenancePostgresTests(unittest.TestCase):
    def setUp(self):
        from backend.postgres_db import PostgresDatabase

        self.dsn = self.enterContext(isolated_pg_dsn())
        self.db = PostgresDatabase(self.dsn)
        self.addCleanup(self.db.close)
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DATABASE_URL": self.dsn, "HANDRAW_DEMO_MODE": "0"}))
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.conn = self.db.get_conn()

    def make_work(self, work_id="legacy-work", forks=0):
        self.conn.execute("""
            INSERT INTO works(id, author_username, author_name, title, prompt, published_at_ms, created_at, updated_at, forks)
            VALUES (?, 'author', '作者', '作品', '', 1, '', '', ?)
        """, (work_id, forks))

    def make_work_comment(self, status="published"):
        self.conn.execute("""
            INSERT INTO work_comments(id, work_id, author_username, author_name, text, status, created_at)
            VALUES ('wc-pg', 'legacy-work', 'viewer', '读者', '旧作品评论', ?, '2026-11-01')
        """, (status,))

    def make_asset_comment(self, comment_id="ac-pg", code="FA-013"):
        self.conn.execute("""
            INSERT INTO asset_comments(id, asset_code, asset_kind, author_username, author_name, text, created_at)
            VALUES (?, ?, 'style', 'viewer', '读者', '旧资源评论', '2026-11-01')
        """, (comment_id, code))

    def run_command(self, module, *args):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            result = module.main(["--backup-dir", str(self.directory), *args])
        self.assertEqual(result, 0, stdout.getvalue())
        return stdout.getvalue()

    def test_work_cli_reuses_topic_and_preserves_hidden_state(self):
        self.make_work()
        with self.db.transaction() as tx:
            topic_id = ensure_topic(tx, "work", "legacy-work", {"title": "作品"}, initial_origin="legacy")
            tx.execute("DELETE FROM curation_resource_topics WHERE kind='work' AND target_id='legacy-work'")
        self.make_work_comment("hidden")
        self.assertIn("1 条", self.run_command(converge_work_comments))
        self.assertEqual(self.conn.execute("SELECT status FROM work_comments").fetchone()[0], "hidden")

        self.run_command(converge_work_comments, "--apply")
        self.run_command(converge_work_comments, "--apply")
        reply = self.conn.execute("""
            SELECT topic_id, status, status_actor_role FROM forum_replies WHERE legacy_source='work_comments:wc-pg'
        """).fetchone()
        self.assertEqual(tuple(reply.values()), (topic_id, "hidden", "admin"))
        self.assertEqual(self.conn.execute("SELECT origin FROM curation_resource_topics").fetchone()[0], "submission")
        self.assertEqual(len(list(self.directory.glob("work-comments-before-*.dump"))), 1)

    def test_asset_cli_copies_both_sources_without_firing_insert_notification(self):
        self.make_work()
        self.make_work_comment()
        self.make_asset_comment()
        self.conn.execute("CREATE TABLE migration_notification_probe(reply_id text)")
        self.conn.execute("""
            CREATE FUNCTION probe_published_reply() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN INSERT INTO migration_notification_probe VALUES (NEW.id); RETURN NEW; END;
            $$
        """)
        self.conn.execute("""
            CREATE TRIGGER probe_published_reply AFTER INSERT ON forum_replies
            FOR EACH ROW WHEN (NEW.status = 'published') EXECUTE FUNCTION probe_published_reply()
        """)
        self.run_command(converge_asset_comments, "--apply")
        self.run_command(converge_asset_comments, "--apply")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM migration_notification_probe").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("""
            SELECT COUNT(*) FROM forum_replies WHERE status='published' AND legacy_source <> ''
        """).fetchone()[0], 2)
        self.assertEqual(self.conn.execute("""
            SELECT COUNT(*) FROM curation_resource_topics WHERE origin='submission'
        """).fetchone()[0], 2)
        self.assertEqual(len(list(self.directory.glob("asset-comments-before-*.dump"))), 1)

    def test_partial_comment_failure_leaves_mapping_retryable(self):
        self.make_asset_comment("ac-valid")
        self.make_asset_comment("ac-retry")
        with self.db.transaction() as tx:
            ensure_topic(tx, "style", "FA-013", {"name": "画风"}, initial_origin="official")
            pending, unmapped, works, _ = converge_asset_comments.plan(tx)
            bad = [dict(item) for item in pending]
            bad[1]["topicId"] = "missing-topic"
            copied, failures = converge_asset_comments.apply(tx, bad, unmapped, works)
            self.assertEqual((copied, len(failures)), (1, 1))
        self.assertEqual(self.conn.execute("SELECT origin FROM curation_resource_topics").fetchone()[0], "official")
        self.run_command(converge_asset_comments, "--apply")
        self.assertEqual(self.conn.execute("SELECT origin FROM curation_resource_topics").fetchone()[0], "submission")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM forum_replies").fetchone()[0], 2)

    def test_topic_cli_normalizes_only_unambiguous_mappings(self):
        self.make_work()
        with self.db.transaction() as tx:
            for code in ("FA-013", "FB-041"):
                ensure_topic(tx, "style", code, {"name": "画风"})
            tx.execute("UPDATE curation_resource_topics SET target_id='fb-041' WHERE target_id='FB-041'")
            tx.execute("UPDATE curation_resource_topics SET target_id='fa-013' WHERE target_id='FA-013'")
            tx.execute("""
                INSERT INTO curation_resource_topics (kind,target_id,topic_id,origin,created_at)
                SELECT kind,'Fa-013',topic_id,origin,created_at FROM curation_resource_topics WHERE target_id='fa-013'
            """)
        catalog = {code: {"kind": "style", "name": code} for code in ("FA-013", "FB-041", "FD-001")}
        manifest = self.directory / "topics.json"
        with patch.object(ensure_resource_topics, "static_catalog", return_value=catalog):
            output = self.run_command(ensure_resource_topics, "--apply", "--manifest", str(manifest))
            self.assertIn("重复映射", output)
            ids = json.loads(manifest.read_text(encoding="utf-8"))["topic_ids"]
            self.assertEqual(len(ids), 2)
            self.run_command(ensure_resource_topics, "--apply", "--manifest", str(manifest))
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["topic_ids"], [])
        codes = {row["target_id"] for row in self.conn.execute("SELECT target_id FROM curation_resource_topics")}
        self.assertEqual(codes, {"fa-013", "Fa-013", "FB-041", "FD-001", "legacy-work"})
        self.assertIsNone(self.conn.execute("SELECT listed_at_ms FROM forum_topics WHERE work_id='legacy-work'").fetchone()[0])
        self.assertEqual(len(list(self.directory.glob("resource-topics-before-*.dump"))), 1)

    def test_fork_repair_keeps_verified_generation_and_restorable_snapshot(self):
        import psycopg

        self.make_work(forks=3)
        self.make_work("unaffected")
        valid, _ = register_user(self.db, "fixture_fork_author", "FixturePassword192!")
        self.conn.execute("""
            INSERT INTO studio_generations(
                id,user_id,username,tab_title,mode,prompt,items_json,engine,status,created_at,fork_work_id
            ) VALUES ('valid-run',?,'fixture_fork_author','Work','graphic-text','','[]','live','success','','legacy-work')
        """, (valid["id"],))
        self.conn.execute("""
            INSERT INTO work_forks(work_id,user_id,first_generation_id,created_at)
            VALUES ('legacy-work',?,'valid-run','a'), ('legacy-work',991,'valid-run','b'), ('legacy-work',992,'','c')
        """, (valid["id"],))
        unaffected_before = self.conn.execute("SELECT xmin::text FROM works WHERE id='unaffected'").fetchone()[0]
        self.assertIn("2 条", self.run_command(purge_publish_time_forks))
        self.run_command(purge_publish_time_forks, "--apply")
        self.run_command(purge_publish_time_forks, "--apply")
        self.assertEqual(self.conn.execute("SELECT user_id FROM work_forks").fetchone()[0], valid["id"])
        self.assertEqual(self.conn.execute("SELECT forks FROM works WHERE id='legacy-work'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT xmin::text FROM works WHERE id='unaffected'").fetchone()[0], unaffected_before)
        [archive] = self.directory.glob("fork-facts-before-*.dump")
        recovered_dsn = self.enterContext(isolated_pg_dsn(initialize=False))
        restore_pg_archive(recovered_dsn, archive)
        with psycopg.connect(recovered_dsn) as recovered:
            self.assertEqual(recovered.execute("SELECT count(*) FROM work_forks").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
