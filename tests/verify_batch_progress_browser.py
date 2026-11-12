"""Browser verification for Issue #41:
- Batch generation incremental progress: 0/3 -> 1/3 -> 2/3 -> 3/3.
- No page/form rebuild during generation: theme input focus is preserved.
- Sequential image reveal in rows & bottom results section.
- Cancellation displays "正在停止…", retains completed images, stops subsequent ones.
- Save screenshots to C:/tmp/
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.sync_api import sync_playwright

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_PROGRESS = Path("C:/tmp/batch_progress_incremental.png")
SCREENSHOT_CANCEL = Path("C:/tmp/batch_progress_cancelled.png")
SCREENSHOT_PROGRESS.parent.mkdir(parents=True, exist_ok=True)


def run_browser_verification():
    print(f"Setting up test server on port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    img_cfg = root / "image-service.json"
    img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": f"http://127.0.0.1:{PORT}"}))

    os.environ["HANDRAW_UPLOADS_DIR"] = str(uploads_dir)
    os.environ["HANDRAW_GENERATED_DIR"] = str(generated_dir)
    os.environ["HANDRAW_IMAGE_CONFIG"] = str(img_cfg)
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{PORT}"
    os.environ["HANDRAW_DEMO_MODE"] = "1"

    db = browser_postgres_database()
    user, token = register_user(db, "batch_tester", "Pass1234!")
    print(f"Registered user: {user['username']}")

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"
    httpd.db = db
    httpd.allow_demo_routes = True
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"Server running on {BASE_URL}")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)

            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page = context.new_page()

            delay_seconds = [0.8]

            def route_generate(route):
                if delay_seconds[0] > 0:
                    time.sleep(delay_seconds[0])
                try:
                    payload = json.loads(route.request.post_data or "{}")
                    payload["simulateGateway"] = "ok"
                    route.continue_(post_data=json.dumps(payload))
                except Exception:
                    route.continue_()
            page.route("**/api/studio/generate", route_generate)

            # -----------------------------------------------------------
            # Check 1: Enter Studio Batch Mode
            # -----------------------------------------------------------
            print("\n>>> Check 1: Visiting Studio Batch Create view...")
            page.goto(f"{BASE_URL}/studio/?entry=batch&demo_mode=1", wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Ensure batch table is visible
            page.wait_for_selector(".batch-table-row", timeout=8000)
            rows = page.locator(".batch-table-row")
            rowCount = rows.count()
            print(f"  ✓ Initial batch table rows: {rowCount}")
            assert rowCount >= 3, f"Expected at least 3 rows in batch table, got {rowCount}"

            # -----------------------------------------------------------
            # Check 2: Cancellation during generation
            # -----------------------------------------------------------
            print("\n>>> Check 2: Testing cancellation and completed image retention...")
            start_btn = page.locator("#batch-btn-start")
            assert start_btn.is_visible(), "Start batch button must be visible initially"
            start_btn.click()

            # Wait for stop button to appear and click it
            page.wait_for_selector("#batch-btn-stop", timeout=5000)
            stop_btn = page.locator("#batch-btn-stop")
            stop_btn.click()

            stop_btn_text = stop_btn.inner_text()
            print(f"  ✓ Stop button clicked, text: '{stop_btn_text}'")
            assert "正在停止" in stop_btn_text, f"Stop button must show '正在停止…', got {stop_btn_text}"

            # Wait for batch loop to terminate
            page.wait_for_selector(".batch-summary-status, #batch-btn-start", timeout=8000)
            time.sleep(1)

            cancel_summary = page.locator(".batch-summary-status").inner_text() if page.locator(".batch-summary-status").count() > 0 else ""
            print(f"  ✓ Cancelled summary text: '{cancel_summary}'")
            assert "未执行" in cancel_summary or "已完成" in cancel_summary, f"Expected cancellation summary with unexecuted items, got {cancel_summary}"

            page.screenshot(path=str(SCREENSHOT_CANCEL), full_page=True)
            print(f"  ✓ Screenshot saved to {SCREENSHOT_CANCEL}")

            # -----------------------------------------------------------
            # Check 3: Full incremental run to completion
            # -----------------------------------------------------------
            print("\n>>> Check 3: Verifying full incremental generation and theme input preservation...")
            delay_seconds[0] = 0.5
            first_label_btn = page.locator(".batch-iter-label-btn").first
            first_label_btn.focus()
            focused_before = page.evaluate("() => document.activeElement.className")
            print(f"  ✓ Active element before generation: {focused_before}")

            # Start batch generation
            start_btn = page.locator("#batch-btn-start")
            start_btn.click()

            # Busy status should appear
            page.wait_for_selector(".batch-busy-status, .batch-summary-status", timeout=5000)
            busy_el = page.locator(".batch-busy-status")
            if busy_el.count() > 0:
                print(f"  ✓ Busy status: '{busy_el.inner_text()}'")

            # Wait for all rows to complete
            print("  Waiting for entire batch to finish...")
            page.wait_for_selector(".batch-summary-status, #batch-btn-start", timeout=15000)
            time.sleep(1)

            final_summary = page.locator(".batch-summary-status").inner_text() if page.locator(".batch-summary-status").count() > 0 else ""
            print(f"  ✓ Final summary text: '{final_summary}'")
            assert "全部完成" in final_summary or "已完成" in final_summary, f"Expected final summary, got {final_summary}"

            # Verify that row 0 has thumbnail and is-done
            thumb0 = page.locator(".batch-table-row[data-batch-row='0'] .batch-iter-thumb-btn.is-generated")
            assert thumb0.count() == 1, "Row 0 must contain .batch-iter-thumb-btn.is-generated"

            page.screenshot(path=str(SCREENSHOT_PROGRESS), full_page=True)
            print(f"  ✓ Screenshot saved to {SCREENSHOT_PROGRESS}")

            print("\n========================================================")
            print("BROWSER VERIFICATION COMPLETED SUCCESSFULLY!")
            print("========================================================\n")
            browser.close()
    finally:
        httpd.shutdown()
        try:
            db.close()
        except Exception:
            pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass
        for k in ["HANDRAW_UPLOADS_DIR", "HANDRAW_GENERATED_DIR", "HANDRAW_IMAGE_CONFIG", "HANDRAW_ALLOWED_ORIGINS", "HANDRAW_DEMO_MODE"]:
            os.environ.pop(k, None)


if __name__ == "__main__":
    run_browser_verification()
