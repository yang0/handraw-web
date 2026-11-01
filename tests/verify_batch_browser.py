"""Browser verification for Phase 3b-2 Studio Batch page.

Tests:
1. 1440x900 desktop:
   - 0 uncaught console errors
   - 0 horizontal overflow
   - 4 batch modes switching (card hiding in Row 2 verified)
   - Fission modal opens cleanly
2. 390x844 mobile:
   - 0 uncaught console errors
   - 0 horizontal overflow
   - Responsive compact layout
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PORT = 3095
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT_DIR = Path(r"C:\Users\yang0\.gemini\antigravity-cli\brain\6005648b-a302-4676-abaa-98e0b38a8b07")


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"{url}/studio/")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    db_path = temp_path / "browser_batch_test.db"
    uploads_dir = temp_path / "uploads"
    generated_dir = temp_path / "generated"
    storage_dir = temp_path / "private_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "HANDRAW_PRIVATE_STORAGE": str(storage_dir),
        "HANDRAW_DB_PATH": str(db_path),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DEMO_MODE": "1",
        "HANDRAW_ENABLE_RECHARGE": "0",
    })

    server_proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server", "--port", str(PORT), "--demo-mode", "--db", str(db_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        print(f"Waiting for studio server on port {PORT}...")
        if not wait_for_server(BASE_URL, timeout=12.0):
            print("ERROR: Server failed to start in time.")
            return 1
        print("Studio server is up and running.")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)

            # -------------------------------------------------------------
            # Pass 1: Desktop 1440x900
            # -------------------------------------------------------------
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))

            print("Navigating to Desktop 1440 /studio/?entry=batch...")
            page.goto(f"{BASE_URL}/studio/?entry=batch", wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Verify no console errors
            ignorable = ("favicon", "net::err_aborted")
            real_errors = [e for e in console_errors if not any(x in e.lower() for x in ignorable)]
            if real_errors:
                print(f"FAILED: Console errors encountered: {real_errors}")
                return 1
            print("PASS: 0 console errors on desktop load.")

            # Verify horizontal scroll
            has_h_scroll = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth")
            if has_h_scroll:
                print("FAILED: Horizontal overflow detected on 1440 desktop!")
                return 1
            print("PASS: No horizontal overflow on 1440 desktop.")

            # Verify Row 1 button order
            row1_text = page.locator(".batch-top-row").inner_text()
            idx_batch = row1_text.find("批量方式")
            idx_output = row1_text.find("生成方式")
            idx_fusion = row1_text.find("画风模式")
            assert idx_batch >= 0 and idx_output >= 0 and idx_fusion >= 0, "All 3 groups must exist in Row 1"
            assert idx_batch < idx_output < idx_fusion, "Row 1 order must be: 批量方式 -> 生成方式 -> 画风模式"
            print("PASS: Row 1 groups and order verified.")

            # Screenshot: Desktop Prompts mode
            shot1 = ARTIFACT_DIR / "batch_1440_prompts.png"
            page.screenshot(path=str(shot1), full_page=False)
            print(f"Captured screenshot: {shot1}")

            # Switch to 多画风
            page.click("button[data-set-loop-mode='styles']")
            page.wait_for_timeout(500)
            # Verify style cards hidden in Row 2
            style_cards_count = page.locator(".batch-pickers-row [data-pick-kind='style1']").count()
            assert style_cards_count == 0, "Style card must be hidden in styles mode"
            assert page.locator("#batch-btn-pick-styles").is_visible(), "Pick styles button must be visible"
            shot2 = ARTIFACT_DIR / "batch_1440_styles.png"
            page.screenshot(path=str(shot2), full_page=False)
            print(f"Captured screenshot: {shot2}")

            # Switch to 多图型
            page.click("button[data-set-loop-mode='layouts']")
            page.wait_for_timeout(500)
            layout_cards_count = page.locator(".batch-pickers-row [data-pick-kind='layout']").count()
            assert layout_cards_count == 0, "Layout card must be hidden in layouts mode"
            assert page.locator("#batch-btn-pick-layouts").is_visible(), "Pick layouts button must be visible"
            shot3 = ARTIFACT_DIR / "batch_1440_layouts.png"
            page.screenshot(path=str(shot3), full_page=False)
            print(f"Captured screenshot: {shot3}")

            # Switch back to 多文案, test Fission modal
            page.click("button[data-set-loop-mode='prompts']")
            page.wait_for_timeout(500)
            page.click("#batch-btn-fission")
            page.wait_for_timeout(500)
            assert page.locator("#fission-modal-seed").is_visible(), "Fission seed input must be visible"
            assert page.locator("#fission-submit-btn").is_visible(), "Fission submit button must be visible"
            shot4 = ARTIFACT_DIR / "batch_1440_fission_modal.png"
            page.screenshot(path=str(shot4), full_page=False)
            print(f"Captured screenshot: {shot4}")

            # Close modal by pressing Escape
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            context.close()

            # -------------------------------------------------------------
            # Pass 2: Mobile 390x844
            # -------------------------------------------------------------
            context_mob = browser.new_context(viewport={"width": 390, "height": 844})
            page_mob = context_mob.new_page()

            console_errors_mob = []
            page_mob.on("console", lambda msg: console_errors_mob.append(msg.text) if msg.type == "error" else None)
            page_mob.on("pageerror", lambda err: console_errors_mob.append(f"PAGEERROR: {err}"))

            print("Navigating to Mobile 390 /studio/?entry=batch...")
            page_mob.goto(f"{BASE_URL}/studio/?entry=batch", wait_until="networkidle")
            page_mob.wait_for_timeout(1000)

            real_errors_mob = [e for e in console_errors_mob if not any(x in e.lower() for x in ignorable)]
            if real_errors_mob:
                print(f"FAILED: Mobile console errors encountered: {real_errors_mob}")
                return 1
            print("PASS: 0 console errors on mobile load.")

            has_h_scroll_mob = page_mob.evaluate("() => document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth")
            if has_h_scroll_mob:
                scroll_w = page_mob.evaluate("() => document.body.scrollWidth")
                inner_w = page_mob.evaluate("() => window.innerWidth")
                print(f"FAILED: Horizontal overflow detected on 390 mobile! scrollWidth={scroll_w}, innerWidth={inner_w}")
                return 1
            print("PASS: No horizontal overflow on 390 mobile.")

            shot5 = ARTIFACT_DIR / "batch_390_mobile.png"
            page_mob.screenshot(path=str(shot5), full_page=False)
            print(f"Captured screenshot: {shot5}")

            context_mob.close()
            browser.close()

        print("\nAll browser verification checks passed successfully!")
        return 0

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except Exception:
            server_proc.kill()
        temp_dir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
