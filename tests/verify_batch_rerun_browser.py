"""Browser Playwright verification for Issue #41 on port 3097:
- Round 1 generates 3 images to completion.
- Click start again -> confirmation -> verify old preview is immediately cleared.
- Incremental reveal: only current round images shown, count 0/3 -> 1/3 -> 2/3 -> 3/3.
- Mid-run failure: 1/3 displayed, never falsely reports completion.
- Save screenshots to C:/tmp/
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.sync_api import sync_playwright

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_ROUND1 = SCREENSHOT_DIR / "batch_rerun_clean_round1.png"
SCREENSHOT_ROUND2 = SCREENSHOT_DIR / "batch_rerun_clean_round2.png"
SCREENSHOT_FAILURE = SCREENSHOT_DIR / "batch_rerun_clean_failure.png"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def run_browser_verification():
    print(f"Connecting Playwright to preview server on port {PORT}...")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)

        context = browser.new_context(viewport={"width": 1440, "height": 960})
        page = context.new_page()

        # Handle any confirm/alert dialogs automatically
        page.on("dialog", lambda dialog: (print(f"  [Dialog accepted] {dialog.message}", flush=True), dialog.accept()))

        # Route static JS files directly from current worktree
        def route_batch_js(route):
            p_file = WORKTREE_ROOT / "demo" / "assets" / "studio-batch.js"
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=p_file.read_bytes())

        def route_app_js(route):
            p_file = WORKTREE_ROOT / "demo" / "assets" / "studio-app.js"
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=p_file.read_bytes())

        page.route("**/assets/studio-batch.js*", route_batch_js)
        page.route("**/assets/studio-app.js*", route_app_js)

        # Route /api/studio/config so live generation is enabled
        def route_config(route):
            cfg_data = {
                "liveImageEnabled": True,
                "realImageGeneration": True,
                "demoMode": False,
                "rechargeEnabled": False,
                "trustedOrigins": [f"http://127.0.0.1:{PORT}"],
                "model": "gpt-image-2",
                "dailyFreeQuota": 100,
                "creditPerImage": 0,
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(cfg_data))

        page.route("**/api/studio/config*", route_config)

        state = {
            "round": 1,
            "call_count": 0,
        }

        def route_generate(route):
            call_idx = state["call_count"]
            state["call_count"] += 1
            curr_round = state["round"]
            print(f"  -> Intercepted generate request: round={curr_round}, call={call_idx}", flush=True)

            if curr_round == 1:
                # Round 1: 3 successful calls
                resp_data = {
                    "ok": True,
                    "status": "success",
                    "images": [f"/images/poster-demo-autumn-equinox.webp?r=1&i={call_idx}"],
                    "credits": 100,
                    "freeQuotaRemaining": 90,
                }
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(resp_data)
                )
            elif curr_round == 2:
                # In Round 2, verify incremental state progression in the DOM before fulfilling each call!
                if call_idx == 0:
                    # Before Call 0 finishes: verify old previews and rows were cleared!
                    results_count = page.locator(".batch-results-section").count()
                    thumbs_count = page.locator(".batch-iter-thumb-btn.is-generated").count()
                    busy_text = page.locator(".batch-busy-status").inner_text() if page.locator(".batch-busy-status").count() > 0 else ""
                    print(f"  ✓ [Before Round 2 Call 0] results_section={results_count}, thumbs={thumbs_count}, busy='{busy_text}'", flush=True)
                    assert results_count == 0, f"Old .batch-results-section must be removed before first image returns, got {results_count}"
                    assert thumbs_count == 0, f"Old thumbnails must be cleared before first image returns, got {thumbs_count}"
                    assert "0 / 3" in busy_text or "0/3" in busy_text, f"Status must be 0/3, got '{busy_text}'"
                elif call_idx == 1:
                    # Before Call 1 finishes: exactly 1 thumbnail exists (round 2)
                    thumbs_count = page.locator(".batch-iter-thumb-btn.is-generated").count()
                    busy_text = page.locator(".batch-busy-status").inner_text() if page.locator(".batch-busy-status").count() > 0 else ""
                    print(f"  ✓ [Before Round 2 Call 1] thumbs={thumbs_count}, busy='{busy_text}'", flush=True)
                    assert thumbs_count == 1, f"Expected 1 thumbnail after Call 0, got {thumbs_count}"
                    assert "1 / 3" in busy_text or "1/3" in busy_text, f"Status must be 1/3, got '{busy_text}'"
                elif call_idx == 2:
                    # Before Call 2 finishes: exactly 2 thumbnails exist (round 2)
                    thumbs_count = page.locator(".batch-iter-thumb-btn.is-generated").count()
                    busy_text = page.locator(".batch-busy-status").inner_text() if page.locator(".batch-busy-status").count() > 0 else ""
                    print(f"  ✓ [Before Round 2 Call 2] thumbs={thumbs_count}, busy='{busy_text}'", flush=True)
                    assert thumbs_count == 2, f"Expected 2 thumbnails after Call 1, got {thumbs_count}"
                    assert "2 / 3" in busy_text or "2/3" in busy_text, f"Status must be 2/3, got '{busy_text}'"

                resp_data = {
                    "ok": True,
                    "status": "success",
                    "images": [f"/images/poster-demo-round2-{call_idx}.webp?r=2&i={call_idx}"],
                    "credits": 100,
                    "freeQuotaRemaining": 80,
                }
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(resp_data)
                )
            elif curr_round == 3:
                # Round 3: first call succeeds, second call fails with 429
                if call_idx == 0:
                    resp_data = {
                        "ok": True,
                        "status": "success",
                        "images": ["/images/poster-demo-round3-0.webp?r=3&i=0"],
                        "credits": 100,
                        "freeQuotaRemaining": 70,
                    }
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(resp_data)
                    )
                else:
                    resp_data = {
                        "ok": False,
                        "error": "429 账户点数不足，请充值后重试",
                    }
                    route.fulfill(
                        status=429,
                        content_type="application/json",
                        body=json.dumps(resp_data)
                    )

        page.route("**/api/studio/generate", route_generate)

        # -----------------------------------------------------------
        # Step 1: Open Studio Batch Mode
        # -----------------------------------------------------------
        print("\n>>> Step 1: Visiting Studio Batch Create view...", flush=True)
        page.goto(f"{BASE_URL}/studio/?entry=batch&demo_mode=1", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # Ensure user state is logged in
        page.evaluate("""() => {
            const S = window.HANDRAW_SHARED;
            if (S && S.App && S.App.state) {
                S.App.state.loggedIn = true;
                S.App.state.freeQuotaRemaining = 99;
                S.App.state.credits = 100;
            }
        }""")

        page.wait_for_selector(".batch-table-row", timeout=8000)
        rows = page.locator(".batch-table-row")
        rowCount = rows.count()
        print(f"  ✓ Initial batch table rows: {rowCount}", flush=True)
        assert rowCount >= 3, f"Expected at least 3 rows in batch table, got {rowCount}"

        # -----------------------------------------------------------
        # Step 2: Round 1 Generation (3 images to completion)
        # -----------------------------------------------------------
        print("\n>>> Step 2: Running Round 1 Generation...", flush=True)
        state["round"] = 1
        state["call_count"] = 0

        start_btn = page.locator("#batch-btn-start")
        start_btn.click()

        # Wait for Round 1 to complete
        page.wait_for_selector(".batch-summary-status", timeout=12000)
        summary1 = page.locator(".batch-summary-status").inner_text()
        print(f"  ✓ Round 1 summary: '{summary1}'", flush=True)
        assert "已完成 3 / 3 张" in summary1 or "全部完成" in summary1

        # Check that all 3 rows have generated thumbnails
        generated_thumbs = page.locator(".batch-iter-thumb-btn.is-generated")
        assert generated_thumbs.count() == 3, f"Expected 3 thumbnails in round 1, got {generated_thumbs.count()}"

        # Results section should be present
        results_section = page.locator(".batch-results-section")
        assert results_section.count() == 1, "Results section must exist after round 1"

        page.screenshot(path=str(SCREENSHOT_ROUND1), full_page=True)
        print(f"  ✓ Round 1 screenshot saved to {SCREENSHOT_ROUND1}", flush=True)

        # -----------------------------------------------------------
        # Step 3: Round 2 Rerun (Clean slate verification)
        # -----------------------------------------------------------
        print("\n>>> Step 3: Triggering Round 2 Rerun & Verifying Incremental Reveal (0/3 -> 1/3 -> 2/3 -> 3/3)...", flush=True)
        state["round"] = 2
        state["call_count"] = 0

        # Click start again
        start_btn = page.locator("#batch-btn-start")
        start_btn.click()

        # Wait for Round 2 to complete
        print("  Waiting for Round 2 to finish...", flush=True)
        page.wait_for_selector(".batch-summary-status", timeout=15000)
        summary2 = page.locator(".batch-summary-status").inner_text()
        print(f"  ✓ Round 2 summary: '{summary2}'", flush=True)
        assert "已完成 3 / 3 张" in summary2 or "全部完成" in summary2

        # Verify that all thumbnails and results are round 2, NONE are round 1!
        thumbs = page.locator(".batch-iter-thumb-btn.is-generated")
        assert thumbs.count() == 3, f"Expected 3 thumbnails in round 2, got {thumbs.count()}"
        for idx in range(3):
            src = thumbs.nth(idx).get_attribute("data-zoom-src") or ""
            print(f"  ✓ Row {idx} thumbnail src: {src}", flush=True)
            assert "r=2" in src, f"Row {idx} must be from round 2, got {src}"
            assert "r=1" not in src, f"Row {idx} must NOT contain round 1 image, got {src}"

        page.screenshot(path=str(SCREENSHOT_ROUND2), full_page=True)
        print(f"  ✓ Round 2 screenshot saved to {SCREENSHOT_ROUND2}", flush=True)

        # -----------------------------------------------------------
        # Step 4: Round 3 Mid-run Failure (1/3 succeeds, 1 fails)
        # -----------------------------------------------------------
        print("\n>>> Step 4: Testing Mid-run Failure (1/3, must not report complete)...", flush=True)
        state["round"] = 3
        state["call_count"] = 0

        # Click start again
        start_btn = page.locator("#batch-btn-start")
        start_btn.click()

        # Wait for failure to terminate the batch
        page.wait_for_selector(".batch-summary-status", timeout=10000)
        summary3 = page.locator(".batch-summary-status").inner_text()
        print(f"  ✓ Round 3 (failure) summary: '{summary3}'", flush=True)

        assert "已完成 1 / 3 张" in summary3, f"Summary must report 1/3 completed, got '{summary3}'"
        assert "失败 1 张" in summary3, f"Summary must report 1 failed, got '{summary3}'"
        assert "全部完成" not in summary3, f"Summary must NOT say 全部完成, got '{summary3}'"

        # Check rows: row 0 is done, row 1 is failed, row 2 is waiting
        row0_status = page.locator(".batch-table-row[data-batch-row='0']").get_attribute("class") or ""
        row1_status = page.locator(".batch-table-row[data-batch-row='1']").get_attribute("class") or ""
        row2_status = page.locator(".batch-table-row[data-batch-row='2']").get_attribute("class") or ""
        print(f"  ✓ Row classes: row0='{row0_status}', row1='{row1_status}', row2='{row2_status}'", flush=True)
        assert "is-done" in row0_status, "Row 0 should be done"
        assert "is-failed" in row1_status, "Row 1 should be failed"
        assert "is-waiting" in row2_status, "Row 2 should be waiting"

        page.screenshot(path=str(SCREENSHOT_FAILURE), full_page=True)
        print(f"  ✓ Round 3 failure screenshot saved to {SCREENSHOT_FAILURE}", flush=True)

        print("\n========================================================", flush=True)
        print("ALL BROWSER PLAYWRIGHT VERIFICATION CHECKS PASSED!", flush=True)
        print("========================================================\n", flush=True)
        browser.close()


if __name__ == "__main__":
    run_browser_verification()
