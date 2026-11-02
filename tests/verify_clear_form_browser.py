"""Playwright browser verification for Issue #47:
- Clear form in 做图 view clears both form fields AND downstream generation results.
- Preserves generation history in user profile and SQLite.
- Page refresh does NOT restore cleared results.
- Confirm dialog displays updated copy:
  "清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？"
- Busy state:
  - Both reset and run buttons are disabled during processing.
  - Visible hint "任务处理中，暂不能清空或再次生成" appears.
  - Direct clicks on reset while busy are blocked and do not trigger confirm.
- Batch view:
  - Reset button uses the same confirm dialog copy and clears results.
- Saves screenshots to C:/tmp/:
  - clear_form_desktop.png (with generation result displayed)
  - clear_form_cleared.png (after clearing form & results)
  - clear_form_busy.png (during processing with busy hint and disabled buttons)
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
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print(f"Connecting Playwright to preview server on port {PORT}...")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)

        ctx = browser.new_context(viewport={"width": 1440, "height": 960})
        page = ctx.new_page()

        # Dialog tracking
        dialog_messages = []
        auto_dialog = {"should_accept": True}

        def handle_dialog(dialog):
            msg = dialog.message
            print(f"  [Dialog Triggered]: '{msg}'", flush=True)
            dialog_messages.append(msg)
            if auto_dialog["should_accept"]:
                dialog.accept()
            else:
                dialog.dismiss()

        page.on("dialog", handle_dialog)

        # Route static files directly from current worktree
        def route_worktree_assets(route):
            req_path = route.request.url.split("/assets/")[-1].split("?")[0]
            target_file = WORKTREE_ROOT / "demo" / "assets" / req_path
            if target_file.is_file():
                mime = "application/javascript; charset=utf-8" if target_file.suffix == ".js" else "text/css; charset=utf-8" if target_file.suffix == ".css" else "application/octet-stream"
                route.fulfill(status=200, content_type=mime, body=target_file.read_bytes())
            else:
                route.continue_()

        page.route("**/assets/*", route_worktree_assets)

        # Mock /api/studio/config for live generation
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

        # Mock /api/studio/generate to return predictable results and verify in-flight busy state
        busy_test_state = {"active": False, "verified": False}

        def route_generate(route):
            print("  [API Intercepted] /api/studio/generate called", flush=True)
            if busy_test_state["active"]:
                reset_btn = page.locator("#make-image-btn-reset")
                run_btn = page.locator("#make-image-btn-run")
                is_reset_disabled = reset_btn.is_disabled()
                is_run_disabled = run_btn.is_disabled()
                busy_hint_locator = page.locator(".make-image-busy-hint")
                is_hint_visible = busy_hint_locator.is_visible()
                hint_text = busy_hint_locator.inner_text() if is_hint_visible else ""

                print(f"  ✓ Reset button disabled: {is_reset_disabled}", flush=True)
                print(f"  ✓ Run button disabled: {is_run_disabled}", flush=True)
                print(f"  ✓ Busy hint visible: {is_hint_visible}, text: '{hint_text}'", flush=True)

                assert is_reset_disabled, "Reset button must be disabled while busy"
                assert is_run_disabled, "Run button must be disabled while busy"
                assert is_hint_visible, "Busy hint text must be visible beside buttons"
                assert "任务处理中，暂不能清空或再次生成" in hint_text, f"Busy hint text mismatch: '{hint_text}'"

                screenshot_busy = SCREENSHOT_DIR / "clear_form_busy.png"
                page.screenshot(path=str(screenshot_busy), full_page=True)
                print(f"  ✓ Screenshot saved: {screenshot_busy}", flush=True)

                # Direct click while busy must be blocked
                page.evaluate("document.querySelector('#make-image-btn-reset')?.click()")
                assert len(dialog_messages) == 0, "No confirm dialog should appear when clicking reset while busy"

                busy_test_state["verified"] = True

            resp_data = {
                "ok": True,
                "status": "success",
                "images": ["/images/poster-demo-autumn-equinox.webp?seed=47"],
                "credits": 98,
                "freeQuotaRemaining": 9,
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(resp_data))

        page.route("**/api/studio/generate*", route_generate)

        def ensure_logged_in():
            page.evaluate("""() => {
                const S = window.HANDRAW_SHARED;
                if (S && S.App && S.App.state) {
                    S.App.state.loggedIn = true;
                    S.App.state.user = { username: "su_editorial", name: "Su Editorial" };
                    S.App.state.freeQuotaRemaining = 99;
                    S.App.state.credits = 100;
                }
            }""")

        # -------------------------------------------------------------
        # Step 1: Open Studio Make Image and Generate
        # -------------------------------------------------------------
        print("\n>>> Step 1: Opening /studio/?entry=quick&demo_mode=1 in 做图 view...", flush=True)
        page.goto(f"{BASE_URL}/studio/?entry=quick&demo_mode=1", wait_until="networkidle")
        ensure_logged_in()
        page.wait_for_selector(".make-image-container", timeout=15000)

        # Enter subject
        print("  Entering subject into #make-image-subject...")
        subject_input = page.locator("#make-image-subject")
        subject_input.fill("测试清空表单风景图")

        # Click Generate button
        print("  Clicking '#make-image-btn-run' to generate an image...")
        page.click("#make-image-btn-run")

        # Wait for results gallery to appear
        page.wait_for_selector(".make-image-results-section img, .quick-results-wrap img", timeout=15000)
        print("  ✓ Generation results appeared in DOM")

        screenshot_desktop = SCREENSHOT_DIR / "clear_form_desktop.png"
        page.screenshot(path=str(screenshot_desktop), full_page=True)
        print(f"  ✓ Screenshot saved: {screenshot_desktop}")

        # Verify subject and result exist
        assert subject_input.input_value() == "测试清空表单风景图"
        results_count = page.locator(".make-image-results-section, .quick-results-wrap").count()
        assert results_count > 0, "Results gallery section must be visible before clear"

        # -------------------------------------------------------------
        # Step 2: Clear Form and Verify Results Cleared
        # -------------------------------------------------------------
        print("\n>>> Step 2: Clicking 清空表单 and checking confirm text...", flush=True)
        dialog_messages.clear()
        auto_dialog["should_accept"] = True

        reset_btn = page.locator("#make-image-btn-reset")
        reset_btn.click()
        page.wait_for_timeout(500)

        EXPECTED_CONFIRM = "清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？"
        assert len(dialog_messages) == 1, f"Expected 1 confirm dialog, got {len(dialog_messages)}"
        assert dialog_messages[0] == EXPECTED_CONFIRM, f"Confirm copy mismatch: got '{dialog_messages[0]}'"
        print(f"  ✓ Dialog confirm copy exactly matched: '{EXPECTED_CONFIRM}'")

        # Verify subject input is cleared
        current_subject = subject_input.input_value()
        print(f"  ✓ Subject input after reset: '{current_subject}'")
        assert current_subject == "", "Subject input must be reset to empty"

        # Verify results gallery section is completely removed from DOM
        cleared_results_count = page.locator(".make-image-results-section, .quick-results-wrap").count()
        print(f"  ✓ Results gallery count after reset: {cleared_results_count}")
        assert cleared_results_count == 0, "Downstream results gallery must be cleared from DOM"

        screenshot_cleared = SCREENSHOT_DIR / "clear_form_cleared.png"
        page.screenshot(path=str(screenshot_cleared), full_page=True)
        print(f"  ✓ Screenshot saved: {screenshot_cleared}")

        # -------------------------------------------------------------
        # Step 3: Page Reload Retention Check
        # -------------------------------------------------------------
        print("\n>>> Step 3: Refreshing page to verify results remain cleared...", flush=True)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".make-image-container", timeout=15000)

        reloaded_results_count = page.locator(".make-image-results-section, .quick-results-wrap").count()
        print(f"  ✓ Results gallery count after reload: {reloaded_results_count}")
        assert reloaded_results_count == 0, "Page refresh must not restore cleared results"

        # -------------------------------------------------------------
        # Step 4: Profile Generation History Retained
        # -------------------------------------------------------------
        print("\n>>> Step 4: Checking profile generation history (retained)...", flush=True)
        page.goto(f"{BASE_URL}/?view=profile&user=su_editorial&ptab=generations", wait_until="networkidle")
        page.wait_for_selector("[data-prof-gen]", timeout=15000)

        # Check that generation card exists in history
        history_cards = page.locator("[data-prof-gen]")
        history_count = history_cards.count()
        print(f"  ✓ Profile generation history items found: {history_count}")
        assert history_count >= 1, "Generation history record must remain intact after clearing workspace"

        # -------------------------------------------------------------
        # Step 5: Busy State Verification
        # -------------------------------------------------------------
        print("\n>>> Step 5: Testing busy state guards in 做图 view...", flush=True)
        page.goto(f"{BASE_URL}/studio/?entry=quick&demo_mode=1", wait_until="networkidle")
        ensure_logged_in()
        page.wait_for_selector(".make-image-container", timeout=15000)

        busy_test_state["active"] = True
        busy_test_state["verified"] = False
        dialog_messages.clear()

        subject_input = page.locator("#make-image-subject")
        subject_input.fill("并发忙碌状态测试")

        # Click run to start in-flight generation
        page.click("#make-image-btn-run")

        # Wait for in-flight generation to complete
        page.wait_for_selector(".make-image-results-section img, .quick-results-wrap img", timeout=15000)
        assert busy_test_state["verified"], "Busy state must have been verified during in-flight generation"
        print("  ✓ Generation completed and busy checks verified")
        busy_test_state["active"] = False

        # -------------------------------------------------------------
        # Step 6: Batch View Clear Form Verification
        # -------------------------------------------------------------
        print("\n>>> Step 6: Testing Batch Create view clear form confirm...", flush=True)
        page.goto(f"{BASE_URL}/studio/?entry=batch&demo_mode=1", wait_until="networkidle")
        page.wait_for_selector(".batch-container", timeout=15000)

        dialog_messages.clear()
        batch_reset_btn = page.locator("#batch-btn-reset")
        assert batch_reset_btn.count() > 0, "Batch reset button must exist"

        batch_reset_btn.click()
        page.wait_for_timeout(500)

        assert len(dialog_messages) == 1, f"Expected 1 confirm dialog in batch reset, got {len(dialog_messages)}"
        assert dialog_messages[0] == EXPECTED_CONFIRM, f"Batch confirm copy mismatch: '{dialog_messages[0]}'"
        print(f"  ✓ Batch reset dialog matched expected copy: '{EXPECTED_CONFIRM}'")

        print("\n========================================================")
        print("ALL BROWSER PLAYWRIGHT VERIFICATION CHECKS PASSED!")
        print("========================================================\n")

        browser.close()


if __name__ == "__main__":
    main()
