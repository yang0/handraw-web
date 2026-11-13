"""Frozen canvas plans use the normal gateway, billing and reconciliation service."""

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend.canvas_dispatcher import CanvasDispatcher
from backend.canvas_runs import get_canvas_run, retry_canvas_run
from backend.db import local_today_str
from backend.generation_v3 import cancel_unsubmitted_web_slots
from backend.server import execute_studio_generation
from backend.services import register_user, ServiceError
from backend.studio_canvases import save_canvas, preview_canvas, submit_canvas
from tests.postgres_support import open_isolated_postgres
from tests.test_studio_canvases import graph


class CanvasDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "canvas_dispatch", "FixturePass123!")
        self.db.get_conn().execute(
            "UPDATE wallets SET balance=50,free_quota_used=0,free_quota_date=? WHERE user_id=?",
            (local_today_str(), self.user["id"]),
        )
        self.enterContext(
            patch(
                "backend.server.load_image_service_config",
                return_value={
                    "protocol": "openai",
                    "model": "fixture",
                    "api_key": "fixture-only",
                },
            )
        )
        self.enterContext(
            patch(
                "backend.server._cache_gateway_item_image",
                side_effect=lambda item, key: f"/images/{key}.webp",
            )
        )
        self.sent = []

        def gateway(*args, **kwargs):
            self.assertIsNone(getattr(self.db._local, "wrapper", None))
            self.sent.append((args, kwargs))
            return {"data": [{"b64_json": "fixture"}]}

        self.gateway = self.enterContext(
            patch("backend.server.openai_image_gateway_request", side_effect=gateway)
        )
        self.dispatcher = CanvasDispatcher(self.db)

    def submit(self, document=None, key="canvas_batch", **extra):
        save_canvas(
            self.db,
            self.user,
            {"id": "canvas", "graph": document or graph(("prompt", ["A", "B"]))},
        )
        preview = preview_canvas(self.db, self.user, "canvas")
        result = submit_canvas(
            self.db,
            self.user,
            "canvas",
            {"requestId": key, "planHash": preview["planHash"], **extra},
        )
        return result, preview

    def test_background_execution_needs_no_per_item_browser_submission(self):
        result, _ = self.submit(
            graph(("prompt", ["A", "B"]), ("colors", [["red"]]), ("ratio", ["16:9"]))
        )
        for _ in range(2):
            self.assertTrue(self.dispatcher.dispatch_once())
        self.assertFalse(self.dispatcher.dispatch_once())
        run = get_canvas_run(self.db, self.user, result["runId"])["run"]
        self.assertEqual(run["status"], "success")
        self.assertTrue(
            all(
                item["status"] == "success" and len(item["images"]) == 1
                for item in run["items"]
            )
        )
        self.assertEqual(len(self.sent), 2)
        self.assertIn("red", self.sent[0][0][1])
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM works WHERE run_id=?", (run["id"],))
            .fetchone()[0],
            1,
        )
        rows = (
            self.db.get_conn()
            .execute(
                "SELECT position,ordinal FROM generation_items WHERE run_id=? ORDER BY ordinal",
                (run["id"],),
            )
            .fetchall()
        )
        self.assertEqual(
            [(r["position"], r["ordinal"]) for r in rows], [(0, 0), (1, 1)]
        )

    def test_three_modes_reach_the_shared_gateway_with_preserved_facts_and_frozen_resources(
        self,
    ):
        from backend.canvas_prompt import GRAPHIC_TEXT_SUFFIX, PURE_IMAGE_RULE

        resource = {
            "kind": "style",
            "canUse": True,
            "access": {"inject": "definition"},
            "_raw_definition": "所选画风的线条和纸感",
            "unlock_cost": 0,
        }
        subject = "预算350万，6人到20人。"
        with (
            patch("backend.resource_registry.resolve", return_value=resource),
            patch(
                "backend.services._compose_skill_prompt",
                side_effect=AssertionError(
                    "Canvas input must not be rewritten by a text model"
                ),
            ),
        ):
            result, _ = self.submit(
                graph(
                    ("prompt", [subject]),
                    ("style1", ["TEST-001"]),
                    ("colors", [["C-01", "自定义暖灰"]]),
                    ("tones", [["T-01"]]),
                    ("mode", ["image-only", "graphic-text", "poster"]),
                )
            )
            for _ in range(3):
                self.assertTrue(self.dispatcher.dispatch_once())
        rows = (
            self.db.get_conn()
            .execute(
                "SELECT mode,prompt,input_json,prompt_ready FROM studio_generations ORDER BY created_at,id"
            )
            .fetchall()
        )
        self.assertEqual(
            {row["mode"] for row in rows}, {"image-only", "graphic-text", "poster"}
        )
        self.assertEqual(len(self.sent), 3)
        for row in rows:
            mode = row["input_json"]["mode"]
            self.assertEqual(row["mode"], mode)
            self.assertEqual(row["prompt_ready"], 1)
            self.assertIn("主题：" + subject, row["prompt"])
            for value in (
                "所选画风的线条和纸感",
                "克莱因蓝",
                "自定义暖灰",
                "影调",
                "高调",
            ):
                self.assertIn(value, row["prompt"])
            self.assertTrue(
                row["prompt"].endswith(
                    PURE_IMAGE_RULE if mode == "image-only" else GRAPHIC_TEXT_SUFFIX
                )
            )
            self.assertTrue(any(sent[0][1] == row["prompt"] for sent in self.sent))
        self.assertEqual(
            get_canvas_run(self.db, self.user, result["runId"])["run"]["status"],
            "success",
        )

    def test_free_official_resources_are_present_without_text_model_composition(self):
        with patch(
            "backend.services._compose_skill_prompt",
            side_effect=AssertionError("No text rewriting"),
        ):
            result, _ = self.submit(
                graph(
                    ("prompt", ["Public style subject"]),
                    ("style1", ["FA-001"]),
                    ("layout", ["SC-001"]),
                    ("mode", ["poster"]),
                )
            )
            self.assertTrue(self.dispatcher.dispatch_once())
        prompt = self.sent[0][0][1]
        self.assertIn("Gemma Correll", prompt)
        self.assertIn("上文下图", prompt)
        self.assertIn("Public style subject", prompt)
        self.assertNotIn("#FA-001", prompt)
        self.assertEqual(
            get_canvas_run(self.db, self.user, result["runId"])["run"]["status"],
            "success",
        )

    def test_quota_change_cannot_exceed_confirmed_budget_and_retry_is_idempotent(self):
        result, _ = self.submit()
        self.db.get_conn().execute(
            "UPDATE wallets SET free_quota_used=3 WHERE user_id=?", (self.user["id"],)
        )
        self.dispatcher.dispatch_once()
        self.dispatcher.dispatch_once()
        run = get_canvas_run(self.db, self.user, result["runId"])["run"]
        self.assertEqual(run["status"], "failed")
        self.assertTrue(
            all(item["errorCode"] == "canvas_budget_exhausted" for item in run["items"])
        )
        self.assertEqual(len(self.sent), 0)
        body = {
            "requestId": "retry_explicit",
            "maxCredits": run["retryQuote"]["total"],
            "unitPrice": run["retryQuote"]["unitPrice"],
        }
        retry_canvas_run(self.db, self.user, run["id"], body)
        self.dispatcher.dispatch_once()
        self.dispatcher.dispatch_once()
        self.assertTrue(
            retry_canvas_run(self.db, self.user, run["id"], body)["idempotent"]
        )
        self.assertFalse(self.dispatcher.dispatch_once())
        completed = get_canvas_run(self.db, self.user, run["id"])["run"]
        self.assertEqual(completed["status"], "success")
        self.assertEqual(completed["spentCredits"], 4)
        self.assertEqual(len(self.sent), 2)

    def test_resource_instructions_are_frozen_and_never_in_public_plan_responses(self):
        self.db.get_conn().execute(
            """INSERT INTO catalog_assets(code,kind,source_type,name,image_url,secret_blackbox_prompt,published_at_ms,created_label,created_at,updated_at)
               VALUES('TEST-001','style','exclusive','Fixture','/images/fixture.webp','original-private-instructions',0,'','','')""",
        )
        resource = {
            "canUse": True,
            "kind": "style",
            "name": "Fixture",
            "unlock_cost": 0,
            "source_type": "exclusive",
            "access": {"inject": "blackbox"},
            "secret_blackbox_prompt": "original-private-instructions",
        }
        with (
            patch("backend.resource_registry.resolve", return_value=resource),
            patch(
                "backend.services._compose_skill_prompt",
                return_value="Public composition",
            ),
        ):
            result, preview = self.submit(
                graph(("prompt", ["A"]), ("style1", ["TEST-001"]))
            )
            resource["secret_blackbox_prompt"] = "changed-private-instructions"
            self.dispatcher.dispatch_once()
        self.assertIn("original-private-instructions", self.sent[0][0][1])
        self.assertNotIn("changed-private-instructions", self.sent[0][0][1])
        public = json.dumps(
            [result, preview, get_canvas_run(self.db, self.user, result["runId"])]
        )
        self.assertNotIn("private-instructions", public)
        row = (
            self.db.get_conn()
            .execute("SELECT visible_prompt,prompt_masked FROM studio_generations")
            .fetchone()
        )
        self.assertEqual(row["visible_prompt"], "")
        self.assertEqual(row["prompt_masked"], 1)

    def test_cancel_claimed_but_unsubmitted_plan_rejects_late_dispatch_without_charge(
        self,
    ):
        result, _ = self.submit()
        item = self.dispatcher.claim()
        cancel_unsubmitted_web_slots(self.db, self.user, result["batchId"], [0, 1])
        with self.assertRaises(ServiceError):
            execute_studio_generation(
                self.db,
                self.user,
                {
                    "canvasId": "canvas",
                    "creationSource": "canvas",
                    "batchId": result["batchId"],
                    "batchIndex": item["ordinal"],
                    "requestId": item["dispatch_request_id"],
                    "_canvasDispatchToken": item["dispatch_token"],
                },
            )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generations")
            .fetchone()[0],
            0,
        )
        self.assertEqual(
            get_canvas_run(self.db, self.user, result["runId"])["run"]["status"],
            "cancelled",
        )
        self.assertEqual(len(self.sent), 0)

    def test_parallel_dispatch_obeys_user_inflight_limit_without_double_reservations(
        self,
    ):
        result, _ = self.submit()
        entered = threading.Event()
        release = threading.Event()

        def held(*args, **kwargs):
            self.assertIsNone(getattr(self.db._local, "wrapper", None))
            entered.set()
            release.wait(timeout=8)
            return {"data": [{"b64_json": "fixture"}]}

        self.gateway.side_effect = held

        def work():
            try:
                return self.dispatcher.dispatch_once()
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            try:
                self.assertTrue(entered.wait(timeout=5))
                self.assertTrue(self.dispatcher.dispatch_once())
                self.assertEqual(
                    self.db.get_conn()
                    .execute("SELECT COUNT(*) FROM studio_generations")
                    .fetchone()[0],
                    1,
                )
            finally:
                release.set()
            self.assertTrue(future.result(timeout=5))
        self.db.get_conn().execute(
            "UPDATE generation_items SET dispatch_after=now() WHERE run_id=?",
            (result["runId"],),
        )
        self.dispatcher.dispatch_once()
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generations")
            .fetchone()[0],
            2,
        )
        self.assertEqual(
            get_canvas_run(self.db, self.user, result["runId"])["run"]["status"],
            "success",
        )
