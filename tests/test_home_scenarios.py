"""Unit tests for home scenarios: migration, default hooks, selection, rotation, cache, admin APIs, and feed filtering."""
from __future__ import annotations

import io
import json
import os
import time
from typing import Any
import unittest
from unittest import mock

from backend.postgres_db import PgConnection
from backend.home_scenarios import (
    _SCENARIOS_CACHE,
    DEFAULT_SCENARIOS,
    admin_list_home_scenarios,
    admin_pin_scenario_work,
    admin_reorder_home_scenarios,
    admin_reorder_scenario_pins,
    admin_save_home_scenario,
    admin_toggle_home_scenario,
    admin_unpin_scenario_work,
    build_scenario_match_clause,
    get_public_home_scenarios,
    get_scenario_match_clause_by_key,
    invalidate_scenarios_cache,
    seed_default_home_scenarios_hook,
)
from backend.services import ServiceError, set_work_visibility
from backend.works_feed import get_works_feed
from tests.postgres_support import open_isolated_postgres


def _insert_work(
    conn: PgConnection,
    *,
    wid: str,
    title: str = "测试作品",
    author: str = "author_alice",
    status: str = "published",
    prompt: str = "提示词",
    notes: str = "",
    subject: str = "",
    images: list[Any] | None = None,
    styles: list[str] | None = None,
    layout: str = "",
    price: int = 0,
    likes: int = 0,
    cheers: int = 0,
    favorites: int = 0,
    forks: int = 0,
    published_at_ms: int = 1000,
    ratio: str = "3:4",
    prompt_has_secret: int = 0,
) -> None:
    if images is None:
        images = ["/images/test_1.png"]
    images_json = json.dumps(images)
    styles_json = json.dumps(styles or [])
    now_iso = "2026-11-04T10:00:00Z"

    conn.execute(
        """
        INSERT INTO works (
            id, title, author_username, author_name, status, prompt, notes, subject,
            prompt_has_secret, images_json, styles_json, layout_code, price, likes, cheers,
            favorites, forks, published_at_ms, ratio, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wid,
            title,
            author,
            author,
            status,
            prompt,
            notes,
            subject,
            prompt_has_secret,
            images_json,
            styles_json,
            layout,
            price,
            likes,
            cheers,
            favorites,
            forks,
            published_at_ms,
            ratio,
            now_iso,
            now_iso,
        ),
    )


class TestHomeScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(mock.patch.dict(os.environ, {"HANDRAW_REDIS_URL": "", "HANDRAW_DEMO_MODE": "0"}))
        self.db = open_isolated_postgres(self)
        invalidate_scenarios_cache()
        self.addCleanup(invalidate_scenarios_cache)
        self.admin_user = {
            "id": 1,
            "username": "admin_user",
            "name": "Admin",
            "role": "admin",
            "status": "active",
        }
        self.operator_user = {
            "id": 2,
            "username": "operator_user",
            "name": "Operator",
            "role": "operator",
            "status": "active",
        }
        self.reviewer_user = {
            "id": 3,
            "username": "reviewer_user",
            "name": "Reviewer",
            "role": "reviewer",
            "status": "active",
        }
        self.normal_user = {
            "id": 99,
            "username": "regular_bob",
            "name": "Bob",
            "role": "user",
            "status": "active",
        }

    def test_native_schema_and_tables(self) -> None:
        conn = self.db.get_conn()
        tables = [
            r["table_name"]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchall()
        ]
        self.assertIn("home_scenarios", tables)
        self.assertIn("scenario_pinned_works", tables)

        cols = [
            r["column_name"]
            for r in conn.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'home_scenarios'
            """).fetchall()
        ]
        for expected_col in [
            "key",
            "title",
            "subtitle",
            "studio_entry",
            "studio_params_json",
            "match_rules_json",
            "sort_order",
            "is_enabled",
            "created_at",
            "updated_at",
        ]:
            self.assertIn(expected_col, cols)

        # Re-running migrate is idempotent
        applied = self.db.migrate()
        self.assertEqual(applied, [])

    def test_default_scenarios_and_no_overwrite(self) -> None:
        conn = self.db.get_conn()
        rows = conn.execute("SELECT key, title, studio_entry FROM home_scenarios").fetchall()
        keys = {r["key"] for r in rows}
        expected_keys = {
            "xiaohongshu",
            "gzh_inline",
            "article_illus",
            "comic_4panel",
            "ip_character",
            "ecommerce",
            "infographic",
            "poster",
        }
        self.assertEqual(keys, expected_keys)

        # Admin customizes a scenario
        conn.execute(
            "UPDATE home_scenarios SET title = '自定义小红书标题' WHERE key = 'xiaohongshu'"
        )

        # Run post migration hook again
        seed_default_home_scenarios_hook(conn)

        updated_row = conn.execute(
            "SELECT title FROM home_scenarios WHERE key = 'xiaohongshu'"
        ).fetchone()
        self.assertEqual(updated_row["title"], "自定义小红书标题")

    def test_prompt_not_matched_by_keywords(self) -> None:
        """Keywords must only match title/subject/notes, never prompt."""
        conn = self.db.get_conn()
        # Work with keyword "结构" only in prompt
        _insert_work(
            conn,
            wid="w_prompt_only",
            title="普通风景画",
            prompt="这是一段包含结构解析和电商卖点的长提示词",
            notes="无相关说明",
            subject="",
            layout="USR-001",
            status="published",
        )
        # Work with keyword "结构" in notes
        _insert_work(
            conn,
            wid="w_notes_kw",
            title="普通风景画2",
            prompt="正常提示词",
            notes="本作品展示榫卯结构分解",
            subject="",
            layout="USR-001",
            status="published",
        )

        # Ecommerce rules search keywords including "结构"
        ec_rules = next(s["match_rules"] for s in DEFAULT_SCENARIOS if s["key"] == "ecommerce")
        clause, params = build_scenario_match_clause(ec_rules, table_alias="w")

        matched = conn.execute(
            f"SELECT id FROM works w WHERE id IN ('w_prompt_only', 'w_notes_kw') AND ({clause})",
            params,
        ).fetchall()
        matched_ids = [m["id"] for m in matched]

        self.assertNotIn("w_prompt_only", matched_ids)
        self.assertIn("w_notes_kw", matched_ids)

    def test_cross_scenario_deduplication_and_pinned_precedence(self) -> None:
        """A work can appear in at most one scenario across the home page on the same day.

        Pinned works claim slots first; auto-fill in sort_order skips already claimed works.
        """
        conn = self.db.get_conn()
        # Insert a work that matches both xiaohongshu (SC, 3:4) and gzh_inline (SC, 3:4) and article_illus
        _insert_work(
            conn,
            wid="w_cross_1",
            title="跨场景作品1",
            layout="SC-001",
            ratio="3:4",
            status="published",
        )
        _insert_work(
            conn,
            wid="w_cross_2",
            title="跨场景作品2",
            layout="SC-001",
            ratio="3:4",
            status="published",
        )
        _insert_work(
            conn,
            wid="w_xhs_only",
            title="小红书专属",
            layout="SC-001",
            ratio="3:4",
            status="published",
        )

        # 1. Unpinned: w_cross_1 is claimed by the first scenario (xiaohongshu, sort_order 10)
        # and should not appear in subsequent scenarios (gzh_inline, sort_order 20, etc.)
        data1, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        all_ids = []
        for it in data1["items"]:
            for s in it["samples"]:
                all_ids.append(s["id"])
        # Every work appears at most once globally!
        self.assertEqual(len(all_ids), len(set(all_ids)))

        # 2. Pinned precedence: Pin w_cross_1 to gzh_inline (sort_order 20)
        invalidate_scenarios_cache()
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('gzh_inline', 'w_cross_1', 10, '2026-11-04T10:00:00Z')"
        )

        data2, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        xhs = next(it for it in data2["items"] if it["key"] == "xiaohongshu")
        gzh = next(it for it in data2["items"] if it["key"] == "gzh_inline")

        xhs_sample_ids = [s["id"] for s in xhs["samples"]]
        gzh_sample_ids = [s["id"] for s in gzh["samples"]]

        # Because w_cross_1 was pinned in gzh_inline, it is claimed by gzh_inline (pinned)
        # and xiaohongshu must NOT have w_cross_1!
        self.assertIn("w_cross_1", gzh_sample_ids)
        self.assertNotIn("w_cross_1", xhs_sample_ids)

        # Still globally unique across all scenarios
        all_ids2 = [s["id"] for it in data2["items"] for s in it["samples"]]
        self.assertEqual(len(all_ids2), len(set(all_ids2)))

    def test_round_robin_shared_candidates_allocation(self) -> None:
        """When two scenarios share candidates and the first scenario has enough to take all 4,
        round-robin allocation ensures the second scenario still gets at least 1 work,
        with zero duplicates across the page, and deterministic reproducibility."""
        conn = self.db.get_conn()
        # Insert 4 works matching both xiaohongshu (SC, 3:4) and gzh_inline (SC, 3:4)
        for i in range(1, 5):
            _insert_work(
                conn,
                wid=f"w_rr_{i}",
                title=f"共享候选作品{i}",
                layout="SC-001",
                ratio="3:4",
                status="published",
                likes=i * 5,
            )

        # Call with date_key
        data1, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        xhs1 = next(it for it in data1["items"] if it["key"] == "xiaohongshu")
        gzh1 = next(it for it in data1["items"] if it["key"] == "gzh_inline")

        # The second scenario gzh_inline MUST get at least 1 work!
        self.assertGreaterEqual(len(gzh1["samples"]), 1)
        self.assertGreaterEqual(len(xhs1["samples"]), 1)

        # Total works across both scenarios must be 4, and zero duplicates
        xhs_ids = [s["id"] for s in xhs1["samples"]]
        gzh_ids = [s["id"] for s in gzh1["samples"]]
        self.assertTrue(set(xhs_ids).isdisjoint(set(gzh_ids)))

        all_ids1 = [s["id"] for it in data1["items"] for s in it["samples"]]
        self.assertEqual(len(all_ids1), len(set(all_ids1)), "No duplicate works across the entire page")

        # Call again on the same day -> identical results
        invalidate_scenarios_cache()
        data2, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        xhs2 = next(it for it in data2["items"] if it["key"] == "xiaohongshu")
        gzh2 = next(it for it in data2["items"] if it["key"] == "gzh_inline")

        self.assertEqual([s["id"] for s in xhs1["samples"]], [s["id"] for s in xhs2["samples"]])
        self.assertEqual([s["id"] for s in gzh1["samples"]], [s["id"] for s in gzh2["samples"]])

    def test_get_public_home_scenarios_selection_and_visibility(self) -> None:
        conn = self.db.get_conn()
        _insert_work(
            conn,
            wid="w_pub_1",
            title="小红书公开作品",
            layout="SC-001",
            ratio="3:4",
            status="published",
            images=["/img/pub1.png"],
        )
        _insert_work(
            conn,
            wid="w_hidden_1",
            title="小红书隐藏作品",
            layout="SC-001",
            ratio="3:4",
            status="hidden",
            images=["/img/hidden1.png"],
        )
        _insert_work(
            conn,
            wid="w_deleted_1",
            title="小红书删除作品",
            layout="SC-001",
            ratio="3:4",
            status="deleted",
            images=["/img/deleted1.png"],
        )
        _insert_work(
            conn,
            wid="w_empty_img",
            title="无图作品",
            layout="SC-001",
            ratio="3:4",
            status="published",
            images=[],
        )

        # Pin the hidden work and published work to xiaohongshu
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('xiaohongshu', 'w_hidden_1', 1, '2026-11-04T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('xiaohongshu', 'w_pub_1', 2, '2026-11-04T10:00:00Z')"
        )

        data, etag = get_public_home_scenarios(self.db, date_key="2026-11-04")
        self.assertTrue(data["ok"])
        self.assertTrue(etag)

        xhs = next(item for item in data["items"] if item["key"] == "xiaohongshu")
        samples = xhs["samples"]

        sample_ids = [s["id"] for s in samples]
        self.assertIn("w_pub_1", sample_ids)
        self.assertNotIn("w_hidden_1", sample_ids)
        self.assertNotIn("w_deleted_1", sample_ids)
        self.assertNotIn("w_empty_img", sample_ids)

    def test_cache_ttl_and_single_entry(self) -> None:
        conn = self.db.get_conn()
        _insert_work(
            conn,
            wid="w_cache_ttl",
            title="IP作品1",
            layout="IP-001",
            ratio="3:4",
            status="published",
        )

        # Call with date 1
        d1, etag1 = get_public_home_scenarios(self.db, date_key="2026-11-04")
        first_key = next(iter(_SCENARIOS_CACHE))
        self.assertEqual(first_key[1], "2026-11-04")
        self.assertEqual(len(_SCENARIOS_CACHE), 1)

        # Calling with date 2 purges date 1 to prevent memory leak
        d2, etag2 = get_public_home_scenarios(self.db, date_key="2026-11-05")
        self.assertNotIn(first_key, _SCENARIOS_CACHE)
        second_key = next(iter(_SCENARIOS_CACHE))
        self.assertEqual(second_key[1], "2026-11-05")
        self.assertEqual(len(_SCENARIOS_CACHE), 1)

        # Test TTL expiration: manually backdate expiry timestamp
        payload, etag, _ = _SCENARIOS_CACHE[second_key]
        _SCENARIOS_CACHE[second_key] = (payload, etag, time.monotonic() - 10)

        # Modifying work title
        conn.execute("UPDATE works SET title = '新修改的标题' WHERE id = 'w_cache_ttl'")

        # Calling again re-evaluates because TTL expired
        d3, etag3 = get_public_home_scenarios(self.db, date_key="2026-11-05")
        ip_sample = next(
            s for it in d3["items"] if it["key"] == "ip_character" for s in it["samples"] if s["id"] == "w_cache_ttl"
        )
        self.assertEqual(ip_sample["title"], "新修改的标题")

    def test_set_work_visibility_invalidates_cache(self) -> None:
        """Hiding a work via set_work_visibility clears cache so public API immediately excludes it."""
        conn = self.db.get_conn()
        _insert_work(
            conn,
            wid="w_vis_test",
            title="即将被隐藏的作品",
            layout="SB-002",
            status="published",
        )

        d1, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        comic1 = next(it for it in d1["items"] if it["key"] == "comic_4panel")
        self.assertIn("w_vis_test", [s["id"] for s in comic1["samples"]])

        # Hide work via set_work_visibility
        with self.db.transaction() as tx:
            changed = set_work_visibility(
                tx,
                work_id="w_vis_test",
                status="hidden",
                now_iso="2026-11-04T12:00:00Z",
                source="moderator",
                actor_role="admin",
            )
            self.assertTrue(changed)

        # Cache must be invalidated, calling get_public_home_scenarios excludes w_vis_test
        d2, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        comic2 = next(it for it in d2["items"] if it["key"] == "comic_4panel")
        self.assertNotIn("w_vis_test", [s["id"] for s in comic2["samples"]])

    def test_reviewer_permission_denied_on_mutations(self) -> None:
        """Reviewers may only read scenario list; toggle/pin/reorder require operator/admin."""
        # Reviewer can read list
        res = admin_list_home_scenarios(self.db, self.reviewer_user)
        self.assertTrue(res["ok"])

        # Reviewer cannot save
        with self.assertRaises(ServiceError) as ctx:
            admin_save_home_scenario(self.db, self.reviewer_user, {"key": "test", "title": "t", "studioEntry": "quick"})
        self.assertEqual(ctx.exception.status, 403)

        # Reviewer cannot toggle
        with self.assertRaises(ServiceError) as ctx:
            admin_toggle_home_scenario(self.db, self.reviewer_user, "poster", False)
        self.assertEqual(ctx.exception.status, 403)

        # Reviewer cannot reorder
        with self.assertRaises(ServiceError) as ctx:
            admin_reorder_home_scenarios(self.db, self.reviewer_user, [])
        self.assertEqual(ctx.exception.status, 403)

        # Reviewer cannot pin
        with self.assertRaises(ServiceError) as ctx:
            admin_pin_scenario_work(self.db, self.reviewer_user, "poster", "some_work")
        self.assertEqual(ctx.exception.status, 403)

        # Reviewer cannot unpin
        with self.assertRaises(ServiceError) as ctx:
            admin_unpin_scenario_work(self.db, self.reviewer_user, "poster", "some_work")
        self.assertEqual(ctx.exception.status, 403)

        # Reviewer cannot reorder pins
        with self.assertRaises(ServiceError) as ctx:
            admin_reorder_scenario_pins(self.db, self.reviewer_user, "poster", [])
        self.assertEqual(ctx.exception.status, 403)

    def test_works_feed_scenario_filtering(self) -> None:
        conn = self.db.get_conn()
        _insert_work(
            conn,
            wid="w_feed_xhs",
            title="小红书系列爆款",
            layout="SC-001",
            ratio="3:4",
            status="published",
            images=["/img/xhs.png"],
        )
        _insert_work(
            conn,
            wid="w_feed_comic",
            title="生活四格漫画",
            layout="SB-002",
            ratio="1:1",
            status="published",
            images=["/img/sb.png"],
        )
        _insert_work(
            conn,
            wid="w_feed_ig",
            title="知识卡金字塔模型",
            layout="IG-001",
            ratio="3:4",
            status="published",
            images=["/img/ig.png"],
        )

        comic_feed = get_works_feed(self.db, {"scenario": "comic_4panel"})
        comic_ids = [w["id"] for w in comic_feed["items"]]
        self.assertIn("w_feed_comic", comic_ids)
        self.assertNotIn("w_feed_xhs", comic_ids)
        self.assertNotIn("w_feed_ig", comic_ids)

        ig_feed = get_works_feed(self.db, {"scenario": "infographic"})
        ig_ids = [w["id"] for w in ig_feed["items"]]
        self.assertIn("w_feed_ig", ig_ids)
        self.assertNotIn("w_feed_comic", ig_ids)

        none_feed = get_works_feed(self.db, {"scenario": "nonexistent_scenario_123"})
        self.assertEqual(none_feed["items"], [])

    def test_cached_json_etag_304_handler(self) -> None:
        from backend.server import HandrawRequestHandler

        class FakeHandler(HandrawRequestHandler):
            def __init__(self, headers: dict[str, str]):
                self.headers = headers
                self.response_code = 0
                self.response_headers: dict[str, str] = {}
                self.wfile = io.BytesIO()

            def send_response(self, code: int, message: str | None = None) -> None:
                self.response_code = code

            def send_header(self, keyword: str, value: str) -> None:
                self.response_headers[keyword] = value

            def end_headers(self) -> None:
                pass

            def _cors_headers(self) -> None:
                pass

        obj = {"ok": True, "data": 123}
        etag = "testetag123"

        # 1. No If-None-Match -> 200 with ETag header
        h1 = FakeHandler({})
        h1._send_cached_json(obj, etag=etag)
        self.assertEqual(h1.response_code, 200)
        self.assertEqual(h1.response_headers.get("ETag"), '"testetag123"')
        self.assertIn("public, max-age=300", h1.response_headers.get("Cache-Control", ""))

        # 2. Matching If-None-Match -> 304 Not Modified
        h2 = FakeHandler({"If-None-Match": '"testetag123"'})
        h2._send_cached_json(obj, etag=etag)
        self.assertEqual(h2.response_code, 304)
        self.assertEqual(h2.response_headers.get("ETag"), '"testetag123"')
        self.assertEqual(h2.wfile.getvalue(), b"")

        # 3. Mismatched If-None-Match -> 200
        h3 = FakeHandler({"If-None-Match": '"otheretag"'})
        h3._send_cached_json(obj, etag=etag)
        self.assertEqual(h3.response_code, 200)

    def test_seed_scenario_samples_normal_anonymous_accessible(self) -> None:
        """Seed script generates official work with studio_generations and grant; anonymous can access image."""
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, invite_code, role, status, created_at) VALUES (?, ?, ?, 'h', ?, ?, 'active', ?)",
            (1, "yang0", "Yang", "inv_yang0", "admin", "2026-11-04T10:00:00Z"),
        )
        seed_default_home_scenarios_hook(conn)

        img_url = "/generated/seed_sample_comic_4panel_1_0.png"
        with (
            mock.patch("ops.seed_scenario_samples.compose_prompt", return_value={"prompt": "示例提示词"}),
            mock.patch("ops.seed_scenario_samples.generate_and_cache_sample_image", return_value=img_url),
        ):
            from ops.seed_scenario_samples import run_seed_scenario_samples
            res = run_seed_scenario_samples(
                self.db,
                author_username="yang0",
                scenario_filter="comic_4panel",
                max_total_generations=1,
            )

        self.assertTrue(res["ok"])
        self.assertEqual(len(res["executed"]), 1)
        wid = res["executed"][0]["workId"]

        # 1. Work published
        w = conn.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()
        self.assertIsNotNone(w)
        self.assertEqual(w["status"], "published")
        self.assertEqual(w["request_id"], "seed_sample_comic_4panel_1")

        # 2. studio_generations created
        gen = conn.execute("SELECT * FROM studio_generations WHERE request_id = 'seed_sample_comic_4panel_1'").fetchone()
        self.assertIsNotNone(gen)
        self.assertEqual(gen["status"], "success")
        self.assertEqual(gen["user_id"], 1)

        # 3. studio_generation_media created with valid FK
        media = conn.execute("SELECT * FROM studio_generation_media WHERE media_url = ?", (img_url,)).fetchone()
        self.assertIsNotNone(media)
        self.assertEqual(media["generation_id"], gen["id"])
        self.assertEqual(media["user_id"], 1)

        # 4. media_public_grants created and active
        grant = conn.execute(
            "SELECT * FROM media_public_grants WHERE media_url = ? AND target_type = 'work' AND target_id = ? AND revoked_at IS NULL",
            (img_url, wid),
        ).fetchone()
        self.assertIsNotNone(grant)
        self.assertEqual(grant["owner_user_id"], 1)

        # 5. Anonymous access check (same query as backend/server.py:794)
        anon_check = conn.execute(
            "SELECT 1 FROM media_public_grants WHERE media_url = ? AND revoked_at IS NULL LIMIT 1",
            (img_url,),
        ).fetchone()
        self.assertIsNotNone(anon_check)

        # 6. Scenario pin exists
        pin = conn.execute(
            "SELECT * FROM scenario_pinned_works WHERE scenario_key = 'comic_4panel' AND work_id = ?",
            (wid,),
        ).fetchone()
        self.assertIsNotNone(pin)

    def test_seed_scenario_samples_grant_failure_hides_work_and_exits(self) -> None:
        """When authorization/pinning fails, work is automatically marked hidden and script raises RuntimeError."""
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, invite_code, role, status, created_at) VALUES (?, ?, ?, 'h', ?, ?, 'active', ?)",
            (1, "yang0", "Yang", "inv_yang0", "admin", "2026-11-04T10:00:00Z"),
        )
        seed_default_home_scenarios_hook(conn)

        img_url = "/generated/seed_sample_comic_4panel_1_0.png"
        with (
            mock.patch("ops.seed_scenario_samples.compose_prompt", return_value={"prompt": "示例提示词"}),
            mock.patch("ops.seed_scenario_samples.generate_and_cache_sample_image", return_value=img_url),
        ):
            with mock.patch("ops.seed_scenario_samples.grant_studio_media_public", side_effect=ServiceError("模拟授权失败", status=500)):
                from ops.seed_scenario_samples import run_seed_scenario_samples
                with self.assertRaises(RuntimeError) as ctx:
                    run_seed_scenario_samples(
                        self.db,
                        author_username="yang0",
                        scenario_filter="comic_4panel",
                        max_total_generations=1,
                    )
                self.assertIn("场景样图后置处理失败已隐藏作品", str(ctx.exception))

        # Check DB: work exists but status is hidden!
        w = conn.execute("SELECT * FROM works WHERE request_id = 'seed_sample_comic_4panel_1'").fetchone()
        self.assertIsNotNone(w)
        self.assertEqual(w["status"], "hidden", "Failed authorization must mark work as hidden")

        # It must NOT be included in public home scenarios
        invalidate_scenarios_cache()
        data, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        comic = next(it for it in data["items"] if it["key"] == "comic_4panel")
        self.assertNotIn(w["id"], [s["id"] for s in comic["samples"]])

    def test_seed_scenario_samples_repairs_half_finished_work_preserves_status(self) -> None:
        """On rerun, existing half-finished work is supplemented (generations, media, grant, pin) while status is preserved."""
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, invite_code, role, status, created_at) VALUES (?, ?, ?, 'h', ?, ?, 'active', ?)",
            (1, "yang0", "Yang", "inv_yang0", "admin", "2026-11-04T10:00:00Z"),
        )
        seed_default_home_scenarios_hook(conn)

        # Simulate work 48fa481b: published direct, then failed at FK, user hid it
        img_url = "/generated/seed_sample_comic_4panel_1_0.png"
        _insert_work(
            conn,
            wid="48fa481b-9f24-4748-b69a-27c39836d630",
            title="生活漫画四格 · 周末猫咪与我的日常",
            author="yang0",
            status="hidden",  # Existing status is hidden
            images=[img_url],
            layout="SB-002",
            ratio="1:1",
        )
        conn.execute(
            "UPDATE works SET request_id = 'seed_sample_comic_4panel_1' WHERE id = '48fa481b-9f24-4748-b69a-27c39836d630'"
        )

        # Run script with max_total_generations=0 (no new images generated)
        from ops.seed_scenario_samples import run_seed_scenario_samples
        res = run_seed_scenario_samples(
            self.db,
            author_username="yang0",
            scenario_filter="comic_4panel",
            max_total_generations=0,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(len(res["executed"]), 1)
        ex = res["executed"][0]
        self.assertEqual(ex["workId"], "48fa481b-9f24-4748-b69a-27c39836d630")
        self.assertEqual(
            set(ex["repaired"]),
            {"studio_generations", "studio_generation_media", "media_public_grants", "scenario_pinned_works"},
        )

        # Work status must NOT have changed: still hidden!
        w = conn.execute("SELECT status FROM works WHERE id = '48fa481b-9f24-4748-b69a-27c39836d630'").fetchone()
        self.assertEqual(w["status"], "hidden", "Repaired work status must NOT be modified")

        # studio_generations exists
        gen = conn.execute("SELECT * FROM studio_generations WHERE request_id = 'seed_sample_comic_4panel_1'").fetchone()
        self.assertIsNotNone(gen)
        self.assertEqual(gen["status"], "success")

        # studio_generation_media exists
        media = conn.execute("SELECT * FROM studio_generation_media WHERE media_url = ?", (img_url,)).fetchone()
        self.assertIsNotNone(media)
        self.assertEqual(media["generation_id"], gen["id"])

        # media_public_grants exists
        grant = conn.execute(
            "SELECT * FROM media_public_grants WHERE media_url = ? AND target_type = 'work' AND target_id = '48fa481b-9f24-4748-b69a-27c39836d630' AND revoked_at IS NULL",
            (img_url,),
        ).fetchone()
        self.assertIsNotNone(grant)

        # scenario_pinned_works exists
        pin = conn.execute(
            "SELECT * FROM scenario_pinned_works WHERE scenario_key = 'comic_4panel' AND work_id = '48fa481b-9f24-4748-b69a-27c39836d630'",
        ).fetchone()
        self.assertIsNotNone(pin)


if __name__ == "__main__":
    unittest.main()
