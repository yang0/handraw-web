"""Workspace query budget on a populated isolated PostgreSQL database."""

import os
import unittest
from unittest.mock import patch

from backend.db import utc_now_iso
from backend.generation_v3 import ensure_run, _upsert_media
from backend.services import (
    register_user,
    get_studio_workspace,
    sync_user_studio_articles,
)
from tests.postgres_support import open_isolated_postgres
from backend.studio_workspace import bootstrap_workspace, page_articles
from backend.services import ServiceError
from backend.studio_paging import page_canvases
from backend.canvas_runs import list_canvas_runs


class StudioWorkspaceQueryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0"}))
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "workspace_budget", "FixturePass123!")
        self.db.get_conn().execute(
            "INSERT INTO studio_recipes(id,user_id,subject,created_at,updated_at) VALUES('recipe',?,'Private subject',?,?)",
            (self.user["id"], utc_now_iso(), utc_now_iso()),
        )
        sync_user_studio_articles(
            self.db,
            self.user,
            [
                {
                    "id": "article",
                    "articleTitle": "Private title",
                    "markdown": "Private body",
                    "cards": [{"id": "cover", "prompt": "drawing"}],
                    "settings": {"coverRatio": "16:9"},
                }
            ],
        )

    def seed_executions(self, start, stop):
        with self.db.transaction() as tx:
            for index in range(start, stop):
                bid = f"batch_{index % 120:03d}"
                ensure_run(
                    tx,
                    user_id=self.user["id"],
                    source="web",
                    external_run_id=bid,
                    expected_count=4,
                )
                tx.execute(
                    """INSERT INTO studio_generations(id,user_id,username,created_at,engine,status,
                       batch_id,batch_index,batch_total,recipe_id,recipe_summary,cost_type,credits_spent,visible_prompt,prompt_masked)
                       VALUES(?,?,?,?,'live','success',?,?,4,'recipe','FA-001','credits',2,'',1)""",
                    (
                        f"execution_{index:03d}",
                        self.user["id"],
                        self.user["username"],
                        utc_now_iso(),
                        bid,
                        index // 120,
                    ),
                )

    def measure(self):
        conn = self.db.get_conn()
        with patch.object(conn, "execute", wraps=conn.execute) as execute:
            result = get_studio_workspace(self.db, self.user)
        return result, execute.call_count

    def test_query_count_stays_bounded_for_four_hundred_executions_and_120_runs(self):
        self.seed_executions(0, 2)
        _, small_count = self.measure()
        self.seed_executions(2, 400)
        workspace, large_count = self.measure()
        self.assertLessEqual(large_count, 15)
        self.assertLessEqual(
            large_count,
            small_count + 1,
            "Query count must not grow per execution or run",
        )
        self.assertEqual(len(workspace["history"]), 40)
        self.assertEqual(workspace["articles"][0]["coverRatio"], "16:9")
        self.assertTrue(all(not entry["prompt"] for entry in workspace["history"]))
        print(
            f"workspace queries: 2 executions={small_count}, 400 executions/120 runs={large_count}"
        )

    def test_release_refuses_an_open_transaction_without_rolling_it_back(self):
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE studio_articles SET article_title='Still committed' WHERE id='article'"
            )
            with self.assertRaises(RuntimeError):
                self.db.release_request_connection()
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT article_title FROM studio_articles WHERE id='article'")
            .fetchone()[0],
            "Still committed",
        )
        self.db.release_request_connection()
        self.assertIsNone(getattr(self.db._local, "wrapper", None))

    def test_history_pages_whole_runs_without_a_recent_execution_window(self):
        self.seed_executions(0, 400)
        conn = self.db.get_conn()
        conn.execute("UPDATE generation_runs SET created_at='2026-01-01T00:00:00Z'")
        # More than the former 400-row execution window in ONE old batch.
        conn.execute(
            """INSERT INTO studio_generations(id,user_id,username,created_at,batch_id,status)
               SELECT 'large_'||n,?,?,'2026-01-02T00:00:00Z','batch_000','success'
               FROM generate_series(1,405) n""",
            (self.user["id"], self.user["username"]),
        )
        cursor = ""
        ids = []
        counts = []
        while True:
            with patch.object(conn, "execute", wraps=conn.execute) as execute:
                page = get_studio_workspace(
                    self.db, self.user, collection="history", history_cursor=cursor
                )
            ids.extend(h["runId"] for h in page["history"])
            counts.append(execute.call_count)
            cursor = page["nextCursor"]
            if not cursor:
                break
        self.assertEqual(len(ids), 120)
        self.assertEqual(len(set(ids)), 120)
        self.assertLessEqual(max(counts), 10)
        other, _ = register_user(self.db, "paging_other", "FixturePass123!")
        self.assertEqual(
            get_studio_workspace(self.db, other, collection="history")["history"], []
        )
        conn.execute(
            "UPDATE studio_generations SET deleted_at='deleted' WHERE batch_id='batch_001'"
        )
        remaining = get_studio_workspace(
            self.db, self.user, collection="history", history_limit=100
        )
        self.assertNotIn("batch_001", [h.get("batchId") for h in remaining["history"]])
        for cursor in ("%%%", "e30", "x" * 769):
            with self.assertRaises(ServiceError):
                get_studio_workspace(
                    self.db, self.user, collection="history", history_cursor=cursor
                )

    def test_canvas_and_run_continuation_ties_ownership_and_unstarted_recovery(self):
        conn = self.db.get_conn()
        conn.execute(
            """INSERT INTO studio_canvases(id,user_id,name,updated_at)
               SELECT 'canvas_'||lpad(n::text,3,'0'),?,'Parameters','2026-01-01T00:00:00Z'
               FROM generate_series(1,105) n""",
            (self.user["id"],),
        )
        ids, cursor = [], ""
        while True:
            page = page_canvases(self.db, self.user, cursor=cursor)
            ids.extend(i["id"] for i in page["items"])
            cursor = page["nextCursor"]
            if not cursor:
                break
        self.assertEqual(len(ids), 105)
        self.assertEqual(len(set(ids)), 105)
        with self.db.transaction() as tx:
            for n in range(45):
                run = ensure_run(
                    tx,
                    user_id=self.user["id"],
                    source="web",
                    external_run_id=f"canvas_batch_{n:03d}",
                    expected_count=1,
                )
                tx.execute(
                    "UPDATE generation_runs SET creation_mode='canvas',canvas_id='canvas_001',created_at='2026-01-01T00:00:00Z' WHERE id=?",
                    (run,),
                )
        ids, cursor = [], ""
        while True:
            page = list_canvas_runs(self.db, self.user, "canvas_001", cursor=cursor)
            ids.extend(i["id"] for i in page["items"])
            cursor = page["nextCursor"]
            if not cursor:
                break
        self.assertEqual(len(ids), 45)
        self.assertEqual(len(set(ids)), 45)
        history = get_studio_workspace(
            self.db, self.user, collection="history", history_limit=100
        )
        self.assertEqual(
            len(history["history"]),
            45,
            "Unstarted canvas batches must be recoverable before their first attempt",
        )
        self.assertTrue(
            all(h["creationSource"] == "canvas" for h in history["history"])
        )
        cursor = list_canvas_runs(self.db, self.user, "canvas_001")["nextCursor"]
        with self.assertRaises(ServiceError):
            list_canvas_runs(self.db, self.user, "canvas_002", cursor=cursor)
        other, _ = register_user(self.db, "canvas_other", "FixturePass123!")
        self.assertEqual(page_canvases(self.db, other)["items"], [])
        self.assertEqual(list_canvas_runs(self.db, other, "canvas_001")["items"], [])

    def test_bootstrap_uses_summaries_and_keyset_pages_without_article_bodies(self):
        self.db.get_conn().execute(
            """INSERT INTO studio_articles(id,user_id,article_title,markdown,created_at_ms,updated_at_ms)
               SELECT 'page_'||lpad(n::text,3,'0'),?,'Current document',repeat('Private body ',10000),1,42
               FROM generate_series(1,121) n""",
            (self.user["id"],),
        )
        conn = self.db.get_conn()
        with patch.object(conn, "execute", wraps=conn.execute) as execute:
            result = bootstrap_workspace(self.db, self.user)
        self.assertLessEqual(execute.call_count, 3)
        self.assertEqual(len(result["articles"]), 50)
        self.assertTrue(result["deferredCollections"])
        self.assertTrue(
            all(
                "markdown" not in item and item["_summary"]
                for item in result["articles"]
            )
        )
        ids = [item["id"] for item in result["articles"]]
        cursor = result["articleCursor"]
        while cursor:
            page = page_articles(self.db, self.user, cursor=cursor)
            ids.extend(item["id"] for item in page["items"])
            cursor = page["nextCursor"]
        self.assertEqual(len(ids), 122)
        self.assertEqual(len(set(ids)), 122)
        with self.assertRaises(ServiceError):
            page_articles(self.db, self.user, cursor="not-json")
        with patch.object(conn, "execute", wraps=conn.execute) as execute:
            uploads = get_studio_workspace(self.db, self.user, collection="uploads")
        self.assertEqual(set(uploads), {"loggedIn", "uploads"})
        self.assertFalse(
            any(
                "studio_articles" in str(call.args[0])
                or "studio_generations" in str(call.args[0])
                for call in execute.call_args_list
            )
        )

    def test_article_summary_counts_current_slots_without_reading_private_body(self):
        url = "/images/summary-cover.webp"
        with self.db.transaction() as tx:
            _upsert_media(tx, owner_id=self.user["id"], url=url)
        sync_user_studio_articles(
            self.db,
            self.user,
            [
                {
                    "id": "progress",
                    "articleTitle": "Actual document",
                    "markdown": "Private body",
                    "cards": [
                        {
                            "id": "cover",
                            "role": "cover",
                            "prompt": "cover",
                            "imageUrl": url,
                        },
                        {"id": "pending", "role": "inline", "prompt": "pending"},
                        {
                            "id": "removed",
                            "role": "inline",
                            "prompt": "removed",
                            "imageUrl": url,
                        },
                    ],
                }
            ],
        )
        self.db.get_conn().execute(
            "UPDATE article_illustrations SET deleted_at=? WHERE article_id='progress' AND local_id='removed'",
            (utc_now_iso(),),
        )
        summary = next(
            item
            for item in page_articles(self.db, self.user)["items"]
            if item["id"] == "progress"
        )
        self.assertEqual(summary["illustrationCount"], 2)
        self.assertEqual(summary["selectedImageCount"], 1)
        self.assertEqual(summary["cards"][0]["imageUrl"], url)
        self.assertNotIn("markdown", summary)
        other, _ = register_user(self.db, "summary_other", "FixturePass123!")
        self.assertEqual(page_articles(self.db, other)["items"], [])
