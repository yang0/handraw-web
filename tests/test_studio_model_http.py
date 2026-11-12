"""Real HTTP ownership, independent authoring and backend-only canvas dispatch."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.canvas_dispatcher import CanvasDispatcher
from backend.server import HandrawRequestHandler
from backend.services import register_user, bind_runtime_database
from tests.postgres_support import open_isolated_postgres
from tests.test_studio_canvases import graph


class StudioModelHTTPTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "HANDRAW_DEMO_MODE": "0",
                    "HANDRAW_PRIVATE_STORAGE": str(root),
                    "HANDRAW_ALLOWED_ORIGINS": "http://studio.fixture",
                    "HANDRAW_AI_CONFIG": str(root / "absent-ai.json"),
                },
            )
        )
        self.db = open_isolated_postgres(self)
        bind_runtime_database(self.db)
        self.user, token = register_user(self.db, "studio_http", "FixturePass123!")
        self.other, other_token = register_user(
            self.db, "other_http", "FixturePass123!"
        )
        self.cookie = "handraw_sid=" + token
        self.other_cookie = "handraw_sid=" + other_token
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.server.db = self.db
        self.server.channel_role = "main"
        self.server.allow_demo_routes = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.enterContext(
            patch(
                "backend.server.load_image_service_config",
                return_value={"protocol": "openai", "model": "fixture"},
            )
        )
        self.enterContext(
            patch(
                "backend.server.openai_image_gateway_request",
                return_value={"data": [{"b64_json": "fixture"}]},
            )
        )
        self.enterContext(
            patch(
                "backend.server._cache_gateway_item_image",
                side_effect=lambda item, key: f"/images/{key}.webp",
            )
        )

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, body=None, cookie=None):
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": "http://studio.fixture",
                "Cookie": self.cookie if cookie is None else cookie,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def save_article(self, aid):
        return self.request(
            "/api/studio/articles",
            {
                "articles": [
                    {
                        "id": aid,
                        "articleTitle": "Same article",
                        "markdown": "Same body",
                        "baseWriteSeq": 0,
                        "cards": [
                            {
                                "id": "cover",
                                "role": "cover",
                                "prompt": "a drawing",
                                "ratio": "3:4",
                            }
                        ],
                    }
                ]
            },
        )

    def test_continuation_routes_are_bounded_validated_and_owner_scoped(self):
        from backend.generation_v3 import ensure_run

        self.db.get_conn().execute(
            """INSERT INTO studio_canvases(id,user_id,name,updated_at)
               SELECT 'http_canvas_'||lpad(n::text,3,'0'),?,'Parameters','2026-01-01T00:00:00Z'
               FROM generate_series(1,51) n""",
            (self.user["id"],),
        )
        status, first = self.request("/api/studio/canvases")
        self.assertEqual(status, 200)
        self.assertEqual(len(first["items"]), 50)
        status, second = self.request(
            "/api/studio/canvases?cursor=" + first["nextCursor"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(second["items"]), 1)
        self.assertEqual(second["nextCursor"], "")
        self.assertEqual(
            self.request(
                "/api/studio/canvases?cursor=" + first["nextCursor"],
                cookie=self.other_cookie,
            )[1]["items"],
            [],
        )
        with self.db.transaction() as tx:
            for n in range(41):
                rid = ensure_run(
                    tx,
                    user_id=self.user["id"],
                    source="web",
                    external_run_id=f"http_canvas_run_{n}",
                    expected_count=1,
                )
                tx.execute(
                    "UPDATE generation_runs SET creation_mode='canvas',canvas_id='http_canvas_001' WHERE id=?",
                    (rid,),
                )
        status, first = self.request("/api/studio/workspace?collection=history")
        self.assertEqual(status, 200)
        self.assertEqual(len(first["history"]), 40)
        status, second = self.request(
            "/api/studio/workspace?collection=history&cursor=" + first["nextCursor"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(second["history"]), 1)
        status, runs = self.request("/api/studio/canvases/http_canvas_001/runs")
        self.assertEqual(status, 200)
        self.assertEqual(len(runs["items"]), 20)
        self.assertTrue(runs["nextCursor"])
        for path in (
            "/api/studio/canvases",
            "/api/studio/canvases/http_canvas_001/runs",
            "/api/studio/workspace?collection=history",
        ):
            self.assertEqual(
                self.request(path + ("&" if "?" in path else "?") + "cursor=invalid")[
                    0
                ],
                400,
            )

    def test_article_http_uses_saved_defaults_and_ignores_other_history_context(self):
        saved = self.request(
            "/api/studio/articles",
            {
                "articles": [
                    {
                        "id": "defaults",
                        "articleTitle": "Independent",
                        "markdown": "Body",
                        "cards": [
                            {"id": "cover", "role": "cover", "prompt": "watercolor cat"}
                        ],
                        "settings": {
                            "coverRatio": "16:9",
                            "mode": "image-only",
                            "colors": ["C-01"],
                        },
                    }
                ]
            },
        )
        self.assertEqual(saved[0], 200)
        source = {
            "creationSource": "article",
            "articleId": "defaults",
            "cardId": "cover",
        }
        self.assertEqual(
            self.request(
                "/api/studio/generate",
                {**source, "mode": "graphic-text", "requestId": "bad-override"},
            )[0],
            409,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generations")
            .fetchone()[0],
            0,
        )
        with patch(
            "backend.server.openai_image_gateway_request",
            return_value={"data": [{"b64_json": "fixture"}]},
        ) as gateway:
            status, generated = self.request(
                "/api/studio/generate",
                {
                    **source,
                    "historyId": "missing-unrelated-history",
                    "useCh001": True,
                    "customRefImg": "/private/unrelated.webp",
                    "requestId": "saved-defaults",
                },
            )
        self.assertEqual(status, 200, generated)
        prompt = gateway.call_args.args[1]
        self.assertIn("16:9", prompt)
        self.assertIn("image-only", prompt)
        self.assertIn("C-01", prompt)
        self.assertIsNone(gateway.call_args.kwargs["refs"])
        row = (
            self.db.get_conn()
            .execute(
                "SELECT input_json FROM studio_generations WHERE request_id='saved-defaults'"
            )
            .fetchone()
        )
        self.assertEqual(row["input_json"]["mode"], "image-only")
        self.assertEqual(row["input_json"]["ratio"], "16:9")
        self.assertEqual(row["input_json"]["colors"], ["C-01"])

    def test_articles_have_distinct_ids_owner_scoped_slots_and_no_canvas_dependency(
        self,
    ):
        for aid in ("one", "two"):
            self.assertEqual(self.save_article(aid)[0], 200)
        status, article = self.request("/api/studio/articles/one")
        self.assertEqual(status, 200)
        self.assertEqual(article["article"]["markdown"], "Same body")
        self.assertEqual(
            self.request("/api/studio/articles/one", cookie=self.other_cookie)[0], 404
        )
        generated = self.request(
            "/api/studio/generate",
            {
                "creationSource": "article",
                "articleId": "one",
                "cardId": "cover",
                "prompt": "a drawing",
                "promptFromSkill": True,
                "requestId": "article_direct",
            },
        )
        self.assertEqual(generated[0], 200, generated)
        selected = self.request("/api/studio/articles/one")[1]["article"]["cards"][0]
        self.assertTrue(selected["imageUrl"])
        changed = self.request(
            "/api/studio/articles/one/illustrations/cover/selection",
            {
                "baseResultEpoch": selected["resultEpoch"],
                "imageUrl": "/images/chosen.webp",
            },
        )
        self.assertEqual(changed[0], 200, changed)
        self.assertEqual(
            self.request("/api/studio/articles/one")[1]["article"]["cards"][0][
                "imageUrl"
            ],
            "/images/chosen.webp",
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_articles")
            .fetchone()[0],
            2,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_canvases")
            .fetchone()[0],
            0,
        )

    def test_canvas_plan_executes_without_per_item_http_requests_and_refresh_recovers_results(
        self,
    ):
        status, saved = self.request(
            "/api/studio/canvases",
            {"id": "canvas_http", "graph": graph(("prompt", ["A", "B"]))},
        )
        self.assertEqual(status, 200, saved)
        status, preview = self.request("/api/studio/canvases/canvas_http/preview", {})
        self.assertEqual(status, 200, preview)
        command = {
            "requestId": "canvas_http_run",
            "planHash": preview["planHash"],
            "maxCredits": preview["quote"]["total"],
        }
        status, submitted = self.request(
            "/api/studio/canvases/canvas_http/runs", command
        )
        self.assertEqual(status, 200, submitted)
        replay = self.request("/api/studio/canvases/canvas_http/runs", command)
        self.assertEqual(replay[1], submitted)
        rid = submitted["runId"]
        self.assertEqual(
            self.request("/api/studio/canvas-runs/" + rid, cookie=self.other_cookie)[0],
            404,
        )
        status, direct = self.request(
            "/api/studio/generate",
            {
                "canvasId": "canvas_http",
                "creationSource": "canvas",
                "batchId": "canvas_http_run",
                "batchIndex": 0,
                "requestId": "forged",
                "_canvasDispatchToken": "forged",
                "_canvasResourceInputs": {},
            },
        )
        self.assertEqual(status, 409, direct)
        worker = CanvasDispatcher(self.db)
        worker.dispatch_once()
        worker.dispatch_once()
        status, result = self.request("/api/studio/canvas-runs/" + rid)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["run"]["status"], "success")
        self.assertEqual(len(result["run"]["items"]), 2)
        self.assertEqual(
            [item["spec"]["prompt"] for item in result["run"]["items"]], ["A", "B"]
        )
        self.assertTrue(all(item["images"] for item in result["run"]["items"]))
        self.assertEqual(
            len(self.request("/api/studio/canvases/canvas_http/runs")[1]["items"]), 1
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generations")
            .fetchone()[0],
            2,
        )
