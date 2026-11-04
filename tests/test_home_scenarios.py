"""Unit tests for home scenarios: migration, default hooks, selection, rotation, cache, admin APIs, and feed filtering."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
import unittest

from backend.db import Database
from backend.home_scenarios import (
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
from backend.services import ServiceError
from backend.works_feed import get_works_feed


def _insert_work(
    conn: sqlite3.Connection,
    *,
    wid: str,
    title: str = "测试作品",
    author: str = "author_alice",
    status: str = "published",
    prompt: str = "提示词",
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
            id, title, author_username, author_name, status, prompt,
            prompt_has_secret, images_json, styles_json, layout_code, price, likes, cheers,
            favorites, forks, published_at_ms, ratio, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wid,
            title,
            author,
            author,
            status,
            prompt,
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
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_scenarios.db"
        self.db = Database(self.db_path)
        self.db.migrate()
        invalidate_scenarios_cache()
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
        self.normal_user = {
            "id": 99,
            "username": "regular_bob",
            "name": "Bob",
            "role": "user",
            "status": "active",
        }

    def tearDown(self) -> None:
        invalidate_scenarios_cache()
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp_dir.cleanup()

    def test_migration_086_and_tables(self) -> None:
        conn = self.db.get_conn()
        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        self.assertIn("home_scenarios", tables)
        self.assertIn("scenario_pinned_works", tables)

        cols = [
            r["name"]
            for r in conn.execute("PRAGMA table_info(home_scenarios)").fetchall()
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
        conn.commit()

        # Run post migration hook again
        seed_default_home_scenarios_hook(conn)
        conn.commit()

        updated_row = conn.execute(
            "SELECT title FROM home_scenarios WHERE key = 'xiaohongshu'"
        ).fetchone()
        self.assertEqual(updated_row["title"], "自定义小红书标题")

    def test_get_public_home_scenarios_selection_and_visibility(self) -> None:
        conn = self.db.get_conn()
        # Insert 1 published work, 1 hidden work, 1 deleted work, 1 empty image work
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
        conn.commit()

        # Pin the hidden work and published work to xiaohongshu
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('xiaohongshu', 'w_hidden_1', 1, '2026-11-04T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('xiaohongshu', 'w_pub_1', 2, '2026-11-04T10:00:00Z')"
        )
        conn.commit()

        data, etag = get_public_home_scenarios(self.db, date_key="2026-11-04")
        self.assertTrue(data["ok"])
        self.assertTrue(etag)

        xhs = next(item for item in data["items"] if item["key"] == "xiaohongshu")
        samples = xhs["samples"]

        # w_hidden_1 must NOT be in samples even though pinned
        sample_ids = [s["id"] for s in samples]
        self.assertIn("w_pub_1", sample_ids)
        self.assertNotIn("w_hidden_1", sample_ids)
        self.assertNotIn("w_deleted_1", sample_ids)
        self.assertNotIn("w_empty_img", sample_ids)

    def test_pinned_precedence_and_order(self) -> None:
        conn = self.db.get_conn()
        for i in range(1, 6):
            _insert_work(
                conn,
                wid=f"w_pin_test_{i}",
                title=f"电商作品{i}",
                layout="EC-001",
                ratio="1:1",
                status="published",
                images=[f"/img/ec_{i}.png"],
            )
        conn.commit()

        # Pin w_pin_test_4 first, then w_pin_test_2
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('ecommerce', 'w_pin_test_4', 10, '2026-11-04T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_at) VALUES ('ecommerce', 'w_pin_test_2', 20, '2026-11-04T10:00:00Z')"
        )
        conn.commit()

        data, _ = get_public_home_scenarios(self.db, date_key="2026-11-04", max_samples_per_scenario=4)
        ec = next(item for item in data["items"] if item["key"] == "ecommerce")
        samples = ec["samples"]
        self.assertEqual(len(samples), 4)

        # Pinned works first
        self.assertEqual(samples[0]["id"], "w_pin_test_4")
        self.assertTrue(samples[0]["isPinned"])
        self.assertEqual(samples[1]["id"], "w_pin_test_2")
        self.assertTrue(samples[1]["isPinned"])

        # Auto-filled samples are not pinned
        self.assertFalse(samples[2]["isPinned"])
        self.assertFalse(samples[3]["isPinned"])
        # No duplicate works
        self.assertNotIn(samples[2]["id"], ("w_pin_test_4", "w_pin_test_2"))
        self.assertNotIn(samples[3]["id"], ("w_pin_test_4", "w_pin_test_2"))

    def test_deterministic_rotation_stability_and_variation(self) -> None:
        conn = self.db.get_conn()
        for i in range(1, 10):
            _insert_work(
                conn,
                wid=f"w_rot_{i}",
                title=f"海报作品{i}",
                layout="SC-001",
                ratio="3:4",
                status="published",
                likes=i * 2,
                cheers=i,
                images=[f"/img/poster_{i}.png"],
            )
        conn.commit()

        # Same dateKey should produce identical rotation order
        data1, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")
        invalidate_scenarios_cache()
        data1_again, _ = get_public_home_scenarios(self.db, date_key="2026-11-04")

        poster1 = next(item for item in data1["items"] if item["key"] == "poster")
        poster1_again = next(item for item in data1_again["items"] if item["key"] == "poster")
        self.assertEqual(
            [s["id"] for s in poster1["samples"]],
            [s["id"] for s in poster1_again["samples"]],
        )

        # Different dateKey produces valid samples deterministically
        invalidate_scenarios_cache()
        data2, _ = get_public_home_scenarios(self.db, date_key="2026-11-05")
        poster2 = next(item for item in data2["items"] if item["key"] == "poster")
        self.assertEqual(len(poster2["samples"]), 4)

    def test_cache_invalidation_and_etag(self) -> None:
        conn = self.db.get_conn()
        _insert_work(
            conn,
            wid="w_cache_1",
            title="IP作品1",
            layout="IP-001",
            ratio="3:4",
            status="published",
            images=["/img/ip_1.png"],
        )
        conn.commit()

        # Initial call
        data1, etag1 = get_public_home_scenarios(self.db, date_key="2026-11-04")

        # Calling again uses cache
        data1_cached, etag1_cached = get_public_home_scenarios(self.db, date_key="2026-11-04")
        self.assertEqual(etag1, etag1_cached)

        # Admin modifies scenario
        admin_save_home_scenario(
            self.db,
            self.admin_user,
            {
                "key": "ip_character",
                "title": "全新IP设计专区",
                "subtitle": "全新副标题说明",
                "studioEntry": "quick",
            },
        )

        # Next call reflects changes and yields a different etag
        data2, etag2 = get_public_home_scenarios(self.db, date_key="2026-11-04")
        self.assertNotEqual(etag1, etag2)
        ip_item = next(item for item in data2["items"] if item["key"] == "ip_character")
        self.assertEqual(ip_item["title"], "全新IP设计专区")

        # Admin pin/unpin/reorder invalidates cache
        admin_pin_scenario_work(self.db, self.admin_user, "ip_character", "w_cache_1", sort_order=1)
        data3, etag3 = get_public_home_scenarios(self.db, date_key="2026-11-04")
        self.assertNotEqual(etag2, etag3)

        admin_unpin_scenario_work(self.db, self.admin_user, "ip_character", "w_cache_1")
        data4, etag4 = get_public_home_scenarios(self.db, date_key="2026-11-04")
        self.assertNotEqual(etag3, etag4)

    def test_admin_access_control(self) -> None:
        # Non-staff user gets 403
        with self.assertRaises(ServiceError) as ctx:
            admin_list_home_scenarios(self.db, self.normal_user)
        self.assertEqual(ctx.exception.status, 403)

        with self.assertRaises(ServiceError) as ctx:
            admin_save_home_scenario(
                self.db,
                self.normal_user,
                {"key": "test_sc", "title": "测试", "studioEntry": "quick"},
            )
        self.assertEqual(ctx.exception.status, 403)

        # Admin user succeeds
        res_list = admin_list_home_scenarios(self.db, self.admin_user)
        self.assertTrue(res_list["ok"])
        self.assertGreaterEqual(res_list["total"], 8)

        # Operator user can list and toggle
        res_op_list = admin_list_home_scenarios(self.db, self.operator_user)
        self.assertTrue(res_op_list["ok"])

        res_toggle = admin_toggle_home_scenario(
            self.db, self.operator_user, "ecommerce", is_enabled=False
        )
        self.assertTrue(res_toggle["ok"])
        self.assertFalse(res_toggle["isEnabled"])

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
        conn.commit()

        # Query feed with scenario='comic_4panel'
        comic_feed = get_works_feed(self.db, {"scenario": "comic_4panel"})
        comic_ids = [w["id"] for w in comic_feed["items"]]
        self.assertIn("w_feed_comic", comic_ids)
        self.assertNotIn("w_feed_xhs", comic_ids)
        self.assertNotIn("w_feed_ig", comic_ids)

        # Query feed with scenario='infographic'
        ig_feed = get_works_feed(self.db, {"scenario": "infographic"})
        ig_ids = [w["id"] for w in ig_feed["items"]]
        self.assertIn("w_feed_ig", ig_ids)
        self.assertNotIn("w_feed_comic", ig_ids)

        # Query feed with nonexistent scenario
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


if __name__ == "__main__":
    unittest.main()
