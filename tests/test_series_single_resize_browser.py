"""Playwright E2E tests for series single-image generation and resize healing (#150)."""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Optional browser E2E dependency is absent on Python shard runners.
    sync_playwright = None

from tests.legacy_database import init_legacy_database
from backend.server import create_channel_server
from backend.services import register_user

PNG_1X1_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _GatewayState:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_next_status: int | None = None
        self.fail_next_message: str = "mock upstream gateway 502 failure"


def _make_gateway_handler(state: _GatewayState):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            state.calls.append({"path": self.path, "payload": payload})

            if state.fail_next_status is not None:
                status = state.fail_next_status
                message = state.fail_next_message
                state.fail_next_status = None
                err_body = json.dumps({"error": {"message": message}}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
                return

            body = json.dumps({
                "created": 1731312000,
                "data": [{"b64_json": base64.b64encode(PNG_1X1_BYTES).decode("ascii")}],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


def _launch_chromium(pw):
    executable = os.environ.get("HANDRAW_CHROMIUM")
    if executable:
        return pw.chromium.launch(executable_path=executable, headless=True)
    try:
        return pw.chromium.launch(channel="msedge", headless=True)
    except Exception:
        return pw.chromium.launch(headless=True)


@unittest.skipUnless(sync_playwright is not None, "Playwright is not installed on this runner")
class SeriesSingleResizeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        cls.db_path = root / "series_browser.db"
        cls.img_cfg = root / "image-service.json"

        cls.gw_state = _GatewayState()
        cls.gw_server = ThreadingHTTPServer(("127.0.0.1", 0), _make_gateway_handler(cls.gw_state))
        cls.gw_thread = threading.Thread(target=cls.gw_server.serve_forever, daemon=True)
        cls.gw_thread.start()

        cls.img_cfg.write_text(
            json.dumps({
                "url": f"http://127.0.0.1:{cls.gw_server.server_port}/v1",
                "key": "test-key",
                "model": "gptfree-pool/gpt-image-2.6",
                "protocol": "openai",
                "timeout": 5,
            }),
            encoding="utf-8",
        )
        cls.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(cls.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_IMAGE_CONFIG": str(cls.img_cfg),
            },
        )
        cls.env.start()
        cls.db = init_legacy_database(cls.db_path)
        cls.user, _ = register_user(cls.db, "series_e2e", "Password123!")

        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        os.environ["HANDRAW_ALLOWED_ORIGINS"] = cls.base
        cls.cookie = cls._login("series_e2e", "Password123!")

        # Seed a legacy 3-frame failed generation_runs row in DB, mimicking an older session
        # whose batch_id remains cached in localStorage without activeBatchTotal.
        cls.gw_state.fail_next_status = 502
        cls.gw_state.fail_next_message = "seed legacy 3-frame failed run"
        status, _ = cls._post_generate({
            "prompt": "legacy frame 0",
            "ratio": "3:4",
            "batchId": "batch_legacy_resize_3",
            "batchIndex": 0,
            "batchTotal": 3,
            "requestId": "req_seed_legacy_0",
            "confirmCost": True,
        })
        assert status == 502, f"Expected seeded failed run 502, got {status}"
        cls.gw_state.calls.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.gw_server.shutdown()
        cls.gw_server.server_close()
        cls.gw_thread.join(timeout=5)
        cls.db.close_thread_conn()
        cls.db.close()
        cls.env.stop()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    @classmethod
    def _login(cls, username: str, password: str) -> str:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{cls.base}/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": cls.base},
            method="POST",
        )
        with opener.open(req, timeout=5) as resp:
            return resp.headers.get("Set-Cookie", "").split(";", 1)[0]

    @classmethod
    def _post_generate(cls, payload: dict) -> tuple[int, dict]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{cls.base}/api/studio/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": cls.base, "Cookie": cls.cookie},
            method="POST",
        )
        try:
            with opener.open(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _wallet_snapshot(self) -> dict:
        row = self.db.get_conn().execute(
            "SELECT balance, free_quota_used FROM wallets WHERE user_id = ?",
            (self.user["id"],),
        ).fetchone()
        return dict(row)

    def test_series_single_generation_heals_legacy_batch_preserves_siblings_and_renders_across_viewports(self) -> None:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()
                page_errors: list[str] = []
                gen_events: list[dict] = []

                page.on("pageerror", lambda err: page_errors.append(str(err)))

                def on_response(resp):
                    if "/api/studio/generate" not in resp.url:
                        return
                    try:
                        req_payload = json.loads(resp.request.post_data or "{}")
                    except Exception:
                        req_payload = {}
                    try:
                        resp_body = resp.json()
                    except Exception:
                        resp_body = {}
                    gen_events.append({
                        "status": resp.status,
                        "req": req_payload,
                        "resp": resp_body,
                    })

                page.on("response", on_response)

                # Sign in cleanly through the browser context so session cookies match HTTP origin.
                login_resp = page.request.post(
                    f"{self.base}/api/auth/login",
                    data=json.dumps({"username": "series_e2e", "password": "Password123!"}),
                    headers={"Content-Type": "application/json", "Origin": self.base},
                )
                self.assertEqual(login_resp.status, 200)

                page.goto(f"{self.base}/studio/?entry=batch", wait_until="networkidle")
                page.wait_for_selector("#batch-series-main", timeout=10000)

                # Inject legacy cached Series tab state: 2 frames in UI, stale activeBatchId from a
                # 3-frame DB run WITHOUT activeBatchTotal.
                injected = page.evaluate("""(userId) => {
                    const key = `handraw_open_tabs_v10::user_${userId}`;
                    const raw = localStorage.getItem(key);
                    if (!raw) return { ok: false, reason: "missing_open_tabs", key };
                    const parsed = JSON.parse(raw);
                    const tabs = Array.isArray(parsed.tabs) ? parsed.tabs : [];
                    const tab = tabs.find((t) => t.id === parsed.activeTabId) || tabs[0];
                    if (!tab || !tab.graph || !Array.isArray(tab.graph.nodes)) {
                        return { ok: false, reason: "missing_tab_graph" };
                    }
                    const ctrl = tab.graph.nodes.find((n) => n.type === "output_control");
                    const loop = tab.graph.nodes.find((n) => n.type === "loop");
                    if (!ctrl || !loop) return { ok: false, reason: "missing_ctrl_or_loop" };
                    ctrl.data.activeBatchId = "batch_legacy_resize_3";
                    delete ctrl.data.activeBatchTotal;
                    loop.data.batchLayoutMode = "ai";
                    loop.data.batchCount = 2;
                    loop.data.batchRows = [
                        { theme: "图1森林木屋", layout: "" },
                        { theme: "图2星夜灯塔", layout: "" }
                    ];
                    loop.data.promptListText = "图1森林木屋\\n图2星夜灯塔";
                    tab.batchStart = true;
                    localStorage.setItem(key, JSON.stringify(parsed));
                    return { ok: true, key };
                }""", self.user["id"])
                self.assertTrue(injected.get("ok"), injected)

                page.reload(wait_until="networkidle")
                page.wait_for_selector('[data-generate-series-idx="0"]', timeout=10000)
                self.assertEqual(page.locator("[data-series-select-idx]").count(), 2)
                self.assertEqual(page.locator("#batch-count-input").input_value(), "2")

                # 1) Click single-frame generate on Frame 0: stale legacy batch_id hits 409 once,
                # self-heals with a new batch_id -> 200, and charges only once.
                wallet_before_heal = self._wallet_snapshot()
                gw_calls_before_heal = len(self.gw_state.calls)
                gen_events.clear()

                page.locator('[data-generate-series-idx="0"]').click()
                page.wait_for_selector('[data-series-select-idx="0"].has-result', timeout=10000)

                self.assertEqual([e["status"] for e in gen_events], [409, 200], gen_events)
                self.assertEqual(gen_events[0]["req"].get("batchId"), "batch_legacy_resize_3")
                self.assertEqual(gen_events[0]["req"].get("batchTotal"), 2)
                self.assertEqual(gen_events[0]["resp"].get("code"), "batch_size_mismatch")
                healed_batch_id = gen_events[1]["req"].get("batchId")
                self.assertTrue(healed_batch_id and healed_batch_id != "batch_legacy_resize_3")
                self.assertEqual(gen_events[1]["req"].get("batchTotal"), 2)
                self.assertEqual(len(self.gw_state.calls), gw_calls_before_heal + 1)

                wallet_after_heal = self._wallet_snapshot()
                spent_heal = (
                    (wallet_before_heal["balance"] - wallet_after_heal["balance"])
                    + (wallet_after_heal["free_quota_used"] - wallet_before_heal["free_quota_used"])
                )
                self.assertEqual(spent_heal, 1)

                # Wait until busy state unlocks before adding a 3rd frame.
                page.wait_for_function(
                    "() => { const b = document.querySelector('#batch-btn-add-row'); return b && !b.disabled; }",
                    timeout=10000,
                )

                # 2) Resize series 2 -> 3 via "+", switch to Frame 2, generate Frame 2:
                # must send fresh batchId with batchTotal=3 immediately (no 409) and keep Frame 0 visible.
                gen_events.clear()
                page.locator("#batch-btn-add-row").click()
                self.assertEqual(page.locator("[data-series-select-idx]").count(), 3)
                self.assertEqual(page.locator("#batch-count-input").input_value(), "3")

                page.locator('[data-series-select-idx="2"]').click()
                page.wait_for_selector('[data-generate-series-idx="2"]', timeout=5000)
                if page.locator('[data-series-theme-idx="2"]').count() == 0:
                    page.locator('[data-series-composer-mode="image"]').click()
                theme_input = page.locator('[data-series-theme-idx="2"]')
                theme_input.fill("图3雨后茶馆")

                page.locator('[data-generate-series-idx="2"]').click()
                page.wait_for_selector('[data-series-select-idx="2"].has-result', timeout=10000)

                self.assertEqual([e["status"] for e in gen_events], [200], gen_events)
                frame2_batch_id = gen_events[0]["req"].get("batchId")
                self.assertTrue(frame2_batch_id and frame2_batch_id != healed_batch_id)
                self.assertEqual(gen_events[0]["req"].get("batchTotal"), 3)
                self.assertEqual(page.locator('[data-series-select-idx="0"].has-result').count(), 1)
                self.assertEqual(page.locator('[data-series-select-idx="2"].has-result').count(), 1)

                page.wait_for_function(
                    "() => { const b = document.querySelector('[data-series-select-idx=\"1\"]'); return Boolean(b); }",
                    timeout=10000,
                )

                # 3) Simulate upstream 502 on Frame 1 -> card shows concrete failure text + retry hint.
                self.gw_state.fail_next_status = 502
                self.gw_state.fail_next_message = "mock upstream gateway 502 failure"
                page.locator('[data-series-select-idx="1"]').click()
                page.wait_for_selector('[data-generate-series-idx="1"]', timeout=5000)
                page.locator('[data-generate-series-idx="1"]').click()
                page.wait_for_selector(".batch-series-failed small", timeout=10000)

                failed_text = page.locator(".batch-series-failed small").inner_text()
                self.assertIn("可重试这张图片", failed_text)
                self.assertTrue("502" in failed_text or "失败" in failed_text, failed_text)
                self.assertEqual(page.locator('[data-series-select-idx="0"].has-result').count(), 1)
                self.assertEqual(page.locator('[data-series-select-idx="2"].has-result').count(), 1)

                # 4) Responsive verification across desktop (1440x900), tablet (768x1024), mobile (390x844).
                page.wait_for_function(
                    "() => { const b = document.querySelector('#batch-btn-add-row'); return b && !b.disabled; }",
                    timeout=10000,
                )
                for width, height in [(1440, 900), (768, 1024), (390, 844)]:
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(150)
                    main_card = page.locator("#batch-series-main")
                    thumbs = page.locator("#batch-series-thumbs")
                    retry_btn = page.locator('[data-retry-idx="1"]')
                    self.assertTrue(main_card.is_visible(), f"main card hidden at {width}x{height}")
                    self.assertTrue(thumbs.is_visible(), f"thumbs hidden at {width}x{height}")
                    self.assertTrue(retry_btn.is_visible(), f"retry button hidden at {width}x{height}")
                    box = retry_btn.bounding_box()
                    self.assertIsNotNone(box)
                    self.assertGreater(box["width"], 0)
                    self.assertGreater(box["height"], 0)
                    overflow = page.evaluate(
                        "() => document.documentElement.scrollWidth - window.innerWidth"
                    )
                    self.assertLessEqual(overflow, 2, f"horizontal overflow={overflow} at {width}x{height}")

                # 5) Retry failed Frame 1 on recovery -> succeeds with all 3 series thumbs rendered.
                page.set_viewport_size({"width": 1440, "height": 900})
                gen_events.clear()
                page.locator('[data-retry-idx="1"]').click()
                page.wait_for_selector('[data-series-select-idx="1"].has-result', timeout=10000)
                self.assertEqual([e["status"] for e in gen_events], [200], gen_events)
                self.assertEqual(gen_events[0]["req"].get("batchId"), frame2_batch_id)
                self.assertEqual(gen_events[0]["req"].get("batchTotal"), 3)
                self.assertEqual(page.locator(".batch-series-thumb.has-result").count(), 3)

                self.assertEqual(page_errors, [], f"Unexpected page errors: {page_errors}")
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
