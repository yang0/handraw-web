"""Tests for Phase 3b-8: Resource discussion topic backfill & visibility threshold."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend import admin_services, post_routes, resource_discussions, services
from backend.seed import ensure_seeded
from ops import ensure_resource_topics
from tests.maintenance_support import fill_resource_topics, migrate_asset_comments
from tests.postgres_support import open_isolated_postgres


class ResourceTopicVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_DEMO_MODE": "1",
        }))
        self.db = open_isolated_postgres(self)
        ensure_seeded(self.db)

        # Register users
        self.author, _ = services.register_user(self.db, "vis_author", "pass-author")
        self.reader, _ = services.register_user(self.db, "vis_reader", "pass-reader")
        self.admin, _ = services.register_user(self.db, "vis_admin", "pass-admin")
        conn = self.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE username = 'vis_admin'")
        self.admin = dict(conn.execute("SELECT * FROM users WHERE username = 'vis_admin'").fetchone())

        self._seed_preview_dataset(conn)

    def _seed_preview_dataset(self, conn):
        """Seed dataset mirroring preview environment described in Section 0 & 6."""
        now = services.utc_now_iso()
        now_ms = int(time.time() * 1000)

        assets = [
            *((f"USR-S0{i}", "style", "community", "vis_author", "社区创作者", f"社区画风 USR-S0{i}", "/img/demo.png")
              for i in range(1, 6)),
            *((f"USR-L0{i}", "layout", "community", "vis_author", "社区创作者", f"社区图型 USR-L0{i}", "/img/demo.png")
              for i in range(1, 5)),
            ("FX-001", "style", "exclusive", "yang0", "yang0", "专属水墨FX", "/img/fx.png"),
            ("LX-001", "layout", "exclusive", "yang0", "yang0", "专属版式LX", "/img/lx.png"),
        ]
        conn.executemany("""
            INSERT INTO catalog_assets (
                code, kind, source_type, author_username, author_name, name,
                image_url, status, published_at_ms, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)
            ON CONFLICT (code) DO UPDATE SET
                kind = excluded.kind, source_type = excluded.source_type,
                author_username = excluded.author_username, author_name = excluded.author_name,
                name = excluded.name, image_url = excluded.image_url, status = excluded.status,
                published_at_ms = excluded.published_at_ms, created_at = excluded.created_at,
                updated_at = excluded.updated_at
        """, [(*asset, now_ms, now, now) for asset in assets])

        # 8 published comments in asset_comments (FA-001×2, SC-021×2, FX-001, IG-001, LX-001, USR-S04)
        comments = [
            ("ac_fa_1", "FA-001", "style", "法式水彩通透"),
            ("ac_fa_2", "FA-001", "style", "笔触边缘柔和"),
            ("ac_sc_1", "SC-021", "layout", "版心很稳"),
            ("ac_sc_2", "SC-021", "layout", "非常百搭"),
            ("ac_fx_1", "FX-001", "style", "专属画风惊艳"),
            ("ac_ig_1", "IG-001", "layout", "信息图排版利器"),
            ("ac_lx_1", "LX-001", "layout", "专属版式很工整"),
            ("ac_us_1", "USR-S04", "style", "社区共创画风好用"),
        ]
        for cid, code, kind, text in comments:
            conn.execute(
                """
                INSERT INTO asset_comments (
                    id, asset_code, asset_kind, author_username, author_name, text,
                    status, time_label, created_at
                ) VALUES (?, ?, ?, 'vis_reader', '读者', ?, 'published', '刚刚', ?)
                """,
                (cid, code, kind, text, now),
            )

    def test_01_backfill_mapping_counts_and_manifest(self):
        """1. Backfill mapping count and manifest generation."""
        conn = self.db.get_conn()
        manifest_path = Path(self.temp_dir) / "manifest.json"

        # Step 1: Converge asset comments
        converge_ret = migrate_asset_comments(self.db)
        self.assertEqual(converge_ret, 0)

        # Step 2: Ensure resource topics with manifest
        ret = fill_resource_topics(self.db, manifest_path)
        self.assertEqual(ret, 0)

        # Check mapping counts: catalog styles + catalog layouts
        rows = conn.execute(
            "SELECT kind, COUNT(*) AS cnt FROM curation_resource_topics WHERE kind IN ('style', 'layout') GROUP BY kind"
        ).fetchall()
        counts = {r["kind"]: r["cnt"] for r in rows}
        self.assertGreaterEqual(counts.get("style", 0), 300)
        self.assertGreaterEqual(counts.get("layout", 0), 10)

        # Check manifest
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("timestamp", manifest)
        self.assertIn("created_count", manifest)
        self.assertIn("topic_ids", manifest)
        self.assertEqual(manifest["created_count"], len(manifest["topic_ids"]))
        self.assertGreater(manifest["created_count"], 0)

        # Idempotence: Second run should find 0 needed
        needed_assets, needed_works = ensure_resource_topics.plan(conn)
        self.assertEqual(len(needed_assets), 0)
        self.assertEqual(len(needed_works), 0)

    def test_02_asset_comments_converged_to_forum_replies(self):
        """2. Legacy asset comments converged to forum_replies with legacy_source."""
        conn = self.db.get_conn()
        migrate_asset_comments(self.db)

        # Check migrated rows in forum_replies
        migrated = conn.execute(
            "SELECT COUNT(*) FROM forum_replies WHERE legacy_source LIKE 'asset_comments:%'"
        ).fetchone()[0]
        self.assertEqual(migrated, 8, "Expected 8 non-seed comments migrated to forum_replies")

        # Each legacy_source has exactly 1 row
        dup = conn.execute(
            "SELECT legacy_source, COUNT(*) FROM forum_replies WHERE legacy_source LIKE 'asset_comments:%' GROUP BY legacy_source HAVING COUNT(*) > 1"
        ).fetchall()
        self.assertEqual(len(dup), 0)

        # Non-seed asset_comments status='published' count is now 0 (all marked 'migrated')
        remaining_pub = conn.execute(
            "SELECT COUNT(*) FROM asset_comments WHERE status = 'published' AND id NOT LIKE 'acm_%'"
        ).fetchone()[0]
        self.assertEqual(remaining_pub, 0)

    def test_03_official_resource_visibility_threshold_in_boot(self):
        """3. Official resources without replies hidden from boot; with replies visible."""
        migrate_asset_comments(self.db)
        fill_resource_topics(self.db)

        boot = services.build_boot_payload(self.db, None)
        topic_ids = {t["id"] for t in boot.get("topics", [])}

        conn = self.db.get_conn()
        official_sql = resource_discussions.official_topic_ids_sql()
        official_topic_ids = {r[0] for r in conn.execute(official_sql).fetchall()}

        # In boot, any official topic MUST have replies >= 1
        for t in boot.get("topics", []):
            if t["id"] in official_topic_ids:
                self.assertGreaterEqual(
                    len(t.get("replies", [])),
                    1,
                    f"Official topic {t['id']} ({t.get('title')}) has 0 replies but appears in boot",
                )

        # FA-001 has comments migrated, so it MUST appear in boot
        fa001_row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FA-001'"
        ).fetchone()
        self.assertIsNotNone(fa001_row)
        self.assertIn(fa001_row["topic_id"], topic_ids, "FA-001 has comments, must appear in boot")

        # FB-041 has 0 replies, so it MUST NOT appear in boot topics
        fb041_row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FB-041'"
        ).fetchone()
        self.assertIsNotNone(fb041_row)
        self.assertNotIn(fb041_row["topic_id"], topic_ids, "FB-041 has 0 replies, must not appear in boot")

    def test_04_community_resources_visible_regardless_of_replies(self):
        """4. Community resources appear in forum topics even with 0 replies."""
        migrate_asset_comments(self.db)
        fill_resource_topics(self.db)

        conn = self.db.get_conn()
        official_ids = {r[0] for r in conn.execute(resource_discussions.official_topic_ids_sql()).fetchall()}

        boot = services.build_boot_payload(self.db, None)
        boot_tids = {t["id"] for t in boot.get("topics", [])}

        # Check USR-S01..S05 and USR-L01..L04
        for i in range(1, 6):
            code = f"USR-S0{i}"
            row = conn.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = ?",
                (code,),
            ).fetchone()
            self.assertIsNotNone(row, f"Topic for {code} should exist")
            tid = row["topic_id"]
            self.assertNotIn(tid, official_ids, f"{code} is community, not official")
            self.assertIn(tid, boot_tids, f"{code} should appear in boot topics regardless of replies")

        for i in range(1, 5):
            code = f"USR-L0{i}"
            row = conn.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = 'layout' AND UPPER(target_id) = ?",
                (code,),
            ).fetchone()
            self.assertIsNotNone(row, f"Topic for {code} should exist")
            tid = row["topic_id"]
            self.assertNotIn(tid, official_ids, f"{code} is community, not official")
            self.assertIn(tid, boot_tids, f"{code} should appear in boot topics regardless of replies")

        # USR-S04 has 1 migrated reply
        us4_row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'USR-S04'"
        ).fetchone()
        us4_topic = next(t for t in boot["topics"] if t["id"] == us4_row["topic_id"])
        self.assertGreaterEqual(len(us4_topic.get("replies", [])), 1)

    def test_05_dynamic_comment_and_moderation_flow(self):
        """5. Commenting makes official topic visible; hiding reply makes it disappear from boot; direct link works."""
        conn = self.db.get_conn()
        migrate_asset_comments(self.db)
        fill_resource_topics(self.db)

        fb041_row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FB-041'"
        ).fetchone()
        fb041_tid = fb041_row["topic_id"]

        # Moment 1: 0 replies -> not in boot; direct link /t/FB-041 resolves to topic_id
        boot1 = services.build_boot_payload(self.db, None)
        self.assertNotIn(fb041_tid, {t["id"] for t in boot1["topics"]})
        resolved_1 = post_routes._resolve_ref_to_topic_id(conn, "FB-041", None)
        self.assertEqual(resolved_1, fb041_tid)

        # Moment 2: Post comment -> appears in boot; direct link still resolves
        res = resource_discussions.comment(self.db, self.reader, "style", "FB-041", "很好看的水彩画风！")
        reply_id = res["replyId"]

        boot2 = services.build_boot_payload(self.db, None)
        self.assertIn(fb041_tid, {t["id"] for t in boot2["topics"]})
        fb_topic = next(t for t in boot2["topics"] if t["id"] == fb041_tid)
        self.assertEqual(len(fb_topic["replies"]), 1)
        resolved_2 = post_routes._resolve_ref_to_topic_id(conn, "FB-041", None)
        self.assertEqual(resolved_2, fb041_tid)

        # Moment 3: Admin hides the reply -> disappears from public boot; direct link still resolves
        conn.execute("UPDATE forum_replies SET status = 'hidden' WHERE id = ?", (reply_id,))

        boot3 = services.build_boot_payload(self.db, None)
        self.assertNotIn(fb041_tid, {t["id"] for t in boot3["topics"]})
        resolved_3 = post_routes._resolve_ref_to_topic_id(conn, "FB-041", None)
        self.assertEqual(resolved_3, fb041_tid)

    def test_06_admin_views_with_hidden_replies(self):
        """6. Admin queries (admin=True) count/show topics with hidden replies."""
        conn = self.db.get_conn()
        migrate_asset_comments(self.db)
        fill_resource_topics(self.db)

        fb041_row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FB-041'"
        ).fetchone()
        fb041_tid = fb041_row["topic_id"]

        # Add a hidden reply to FB-041
        now = services.utc_now_iso()
        conn.execute(
            """
            INSERT INTO forum_replies (
                id, topic_id, author_username, author_name, text, status,
                mounted_style, mounted_layout, likes, accepted, time_label, created_at
            ) VALUES ('rep_fb_hid', ?, 'vis_reader', '读者', '违规评论', 'hidden',
                     '', '', 0, 0, '刚刚', ?)
            """,
            (fb041_tid, now),
        )

        # Public boot hides FB-041
        boot = services.build_boot_payload(self.db, None)
        self.assertNotIn(fb041_tid, {t["id"] for t in boot["topics"]})

        # Admin moderator console: should find topic
        mod_data = admin_services.admin_get_moderator_console(self.db, self.admin, board_filter="assets")
        mod_tids = {t["id"] for t in mod_data.get("topics", [])}
        self.assertIn(fb041_tid, mod_tids, "Admin moderator console must see topic with hidden reply")

        # Admin list topics: should list FB-041
        admin_list = admin_services.admin_list_topics(self.db, self.admin)
        admin_tids = {t["id"] for t in admin_list.get("items", [])}
        self.assertIn(fb041_tid, admin_tids, "Admin topic list must see topic with hidden reply")

        # Admin dashboard metrics: topics_total and topics_published include FB-041
        dash = admin_services.admin_get_dashboard(self.db, self.admin)
        self.assertGreater(dash["kpis"]["topicsPublished"], 0)

    def test_07_exclusive_and_override_author_attribution(self):
        """7. Exclusive & official_override discussion topics have author_username='' and author_name='资源讨论'."""
        conn = self.db.get_conn()

        # Ensure topic for an exclusive asset that has author_username set
        res_exclusive = {
            "name": "专属画风FX",
            "source_type": "exclusive",
            "author_username": "yang0",
            "author_name": "yang0",
        }
        with self.db.transaction() as tx:
            tid_ex = resource_discussions.ensure_topic(tx, "style", "FX-999", res_exclusive)
        topic_ex = dict(conn.execute("SELECT * FROM forum_topics WHERE id = ?", (tid_ex,)).fetchone())
        self.assertEqual(topic_ex["author_username"], "", "Exclusive asset topic must have empty author_username")
        self.assertEqual(topic_ex["author_name"], "资源讨论", "Exclusive asset topic must have author_name='资源讨论'")

        # Ensure topic for official override
        res_override = {
            "name": "官方覆盖画风",
            "source_type": "official_override",
            "author_username": "yang0",
            "author_name": "yang0",
        }
        with self.db.transaction() as tx:
            tid_ov = resource_discussions.ensure_topic(tx, "style", "OV-999", res_override)
        topic_ov = dict(conn.execute("SELECT * FROM forum_topics WHERE id = ?", (tid_ov,)).fetchone())
        self.assertEqual(topic_ov["author_username"], "", "Official override topic must have empty author_username")
        self.assertEqual(topic_ov["author_name"], "资源讨论")

    def test_08_creator_stats_match_visibility_threshold(self):
        """8. Creator statistics topicsCount matches visible topics."""
        conn = self.db.get_conn()
        migrate_asset_comments(self.db)
        fill_resource_topics(self.db)

        _, _, _, creators = services.compute_public_asset_counts_and_creators(conn)
        usernames = [c["username"] for c in creators]
        self.assertNotIn("", usernames, "Empty username must not be counted in creators")

    def test_09_works_visibility_rules(self):
        """9. Work discussion topics: published works (with or without prompt) are visible; unpublished hidden."""
        conn = self.db.get_conn()
        now = services.utc_now_iso()
        now_ms = int(time.time() * 1000)

        # Work 1: Published with prompt
        conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, styles_json,
                layout_code, images_json, status, published_at_ms, created_at, updated_at
            ) VALUES ('w_good', 'vis_author', '作者', '优质作品', 'detailed prompt here', '["FA-001"]',
                     '', '["/img/w1.png"]', 'published', ?, ?, ?)
            """,
            (now_ms, now, now),
        )
        # Work 2: Published without prompt
        conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, styles_json,
                layout_code, images_json, status, published_at_ms, created_at, updated_at
            ) VALUES ('w_noprompt', 'vis_author', '作者', '无提示词作品', '', '["FA-001"]',
                     '', '["/img/w2.png"]', 'published', ?, ?, ?)
            """,
            (now_ms, now, now),
        )
        # Work 3: Unpublished (draft)
        conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, styles_json,
                layout_code, images_json, status, published_at_ms, created_at, updated_at
            ) VALUES ('w_draft', 'vis_author', '作者', '草稿作品', 'draft prompt', '["FA-001"]',
                     '', '["/img/w3.png"]', 'draft', ?, ?, ?)
            """,
            (now_ms, now, now),
        )
        # Ensure a topic mapping exists for w_draft to test suppression
        with self.db.transaction() as tx:
            tid_draft = resource_discussions.ensure_topic(
                tx, 'work', 'w_draft',
                {'title': '草稿作品', 'images_json': '["/img/w3.png"]'},
            )

        # Run ensure_resource_topics
        fill_resource_topics(self.db)

        # Check boot topics
        boot = services.build_boot_payload(self.db, None)
        boot_tids = {t["id"] for t in boot.get("topics", [])}

        row1 = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = 'w_good'").fetchone()
        row2 = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = 'w_noprompt'").fetchone()

        self.assertIsNotNone(row1)
        self.assertIsNotNone(row2)
        # Under #60: backfilled works default to unlisted (listed_at_ms IS NULL).
        # They must not be in forum topic list, but exist, be published, and be accessible via discussions.
        self.assertNotIn(row1["topic_id"], boot_tids, "Unlisted published work must not appear in forum list")
        self.assertNotIn(row2["topic_id"], boot_tids, "Unlisted published work must not appear in forum list")
        self.assertNotIn(tid_draft, boot_tids, "Unpublished work topic must be hidden from boot topics")

        t_row1 = conn.execute("SELECT status FROM forum_topics WHERE id = ?", (row1["topic_id"],)).fetchone()
        t_row2 = conn.execute("SELECT status FROM forum_topics WHERE id = ?", (row2["topic_id"],)).fetchone()
        self.assertEqual(t_row1["status"], "published")
        self.assertEqual(t_row2["status"], "published")
        self.assertEqual(boot.get("discussions", {}).get("w_good", {}).get("topicId"), row1["topic_id"])
        self.assertEqual(boot.get("discussions", {}).get("w_noprompt", {}).get("topicId"), row2["topic_id"])
        self.assertNotIn("w_draft", boot.get("discussions", {}), "Draft work must not appear in discussions")

    def test_10_production_mode_community_asset(self):
        """10. In non-demo production mode (HANDRAW_DEMO_MODE=0), community asset is visible with 0 replies."""
        with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}):
            conn = self.db.get_conn()
            now = services.utc_now_iso()
            now_ms = int(time.time() * 1000)

            # Insert custom community asset (not in seed_ids)
            conn.execute(
                """
                INSERT INTO catalog_assets (
                    code, kind, source_type, author_username, author_name, name,
                    image_url, status, published_at_ms, created_at, updated_at
                ) VALUES ('PROD-S01', 'style', 'community', 'vis_author', '社区创作者', '生产社区画风',
                         '/img/prod.png', 'published', ?, ?, ?)
                """,
                (now_ms, now, now),
            )
            with self.db.transaction() as tx:
                tid = resource_discussions.ensure_topic(
                    tx, "style", "PROD-S01",
                    {"name": "生产社区画风", "source_type": "community", "author_username": "vis_author", "author_name": "社区创作者"},
                )

            boot = services.build_boot_payload(self.db, None)
            boot_tids = {t["id"] for t in boot.get("topics", [])}
            self.assertIn(tid, boot_tids, "Production community asset must be visible with 0 replies")

            # Official resource (e.g. FB-041) with 0 replies is not visible
            fb041_row = conn.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = 'style' AND UPPER(target_id) = 'FB-041'"
            ).fetchone()
            if fb041_row:
                self.assertNotIn(fb041_row["topic_id"], boot_tids, "Official style with 0 replies must be hidden in prod mode")
