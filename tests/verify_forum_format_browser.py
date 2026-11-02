"""Playwright browser verification for dropping forum format filter (图文/纯文).

Verifies on port 3097:
1. Desktop 1440x900:
   - Forum header no longer has [data-fformat] segmented control.
   - Sorting buttons ([data-fsort]) and board navigation buttons (.forum-cat-btn) exist and are visible.
   - Layout is intact (no broken wrapper or misplaced controls).
   - Opening legacy link with ?format=visual or ?format=text loads cleanly without error and without filtering.
   - Screenshot saved to C:/tmp/forum_header_desktop_1440.png.
2. Mobile 390x844:
   - Header is clean, no [data-fformat] control.
   - Layout does not collapse.
   - Screenshot saved to C:/tmp/forum_header_mobile_390.png.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from backend.server import HandrawRequestHandler, init_database
from http.server import ThreadingHTTPServer

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"=== Starting verification server on port {PORT} ===")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "forum_format_verify.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    env_patch = {
        "HANDRAW_DB_PATH": str(db_path),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DEMO_MODE": "1",
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT}",
        "HANDRAW_ENABLE_RECHARGE": "0",
    }
    old_env = {}
    for k, v in env_patch.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    db = None
    httpd = None
    try:
        db = init_database(db_path)

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.channel_role = "main"  # type: ignore[attr-defined]
        httpd.db = db  # type: ignore[attr-defined]
        httpd.allow_demo_routes = True  # type: ignore[attr-defined]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"Server started at {BASE_URL}")

        with sync_playwright() as p:
            launch_args = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            }
            if os.path.exists(CHROME_PATH):
                launch_args["executable_path"] = CHROME_PATH

            browser = p.chromium.launch(**launch_args)

            # --- Test 1: Desktop 1440x900 ---
            print("\n[Desktop 1440] Verifying forum header without format filter...")
            page_desktop = browser.new_page(viewport={"width": 1440, "height": 900})
            
            console_errors = []
            page_desktop.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            page_desktop.goto(f"{BASE_URL}/forum/")
            page_desktop.wait_for_selector(".forum-topic-card", timeout=10000)

            # 1. Assert [data-fformat] does not exist
            fformat_count = page_desktop.locator("[data-fformat]").count()
            print(f"  [data-fformat] elements found: {fformat_count}")
            assert fformat_count == 0, f"Expected 0 [data-fformat] elements, found {fformat_count}"

            # 2. Assert sort buttons exist and are visible
            sort_buttons = page_desktop.locator("[data-fsort]")
            sort_count = sort_buttons.count()
            print(f"  [data-fsort] buttons found: {sort_count}")
            assert sort_count >= 5, f"Expected at least 5 sort buttons, found {sort_count}"
            assert page_desktop.locator('[data-fsort="hot"]').is_visible(), "Hot sort button should be visible"
            assert page_desktop.locator('[data-fsort="newest"]').is_visible(), "Newest sort button should be visible"

            # 3. Assert board navigation buttons exist and are visible
            cat_buttons = page_desktop.locator(".forum-cat-btn")
            cat_count = cat_buttons.count()
            print(f"  Category navigation buttons found: {cat_count}")
            assert cat_count >= 4, f"Expected category navigation buttons, found {cat_count}"

            # 4. Assert search input is visible
            search_input = page_desktop.locator("#forum-search-input")
            assert search_input.is_visible(), "Search input should be visible"

            # 5. Check cards count on default view
            cards_default = page_desktop.locator(".forum-topic-card").count()
            print(f"  Default topic cards count: {cards_default}")
            assert cards_default > 0, "Expected seed topic cards to be rendered"

            # Screenshot desktop
            desktop_shot = SCREENSHOT_DIR / "forum_header_desktop_1440.png"
            page_desktop.screenshot(path=str(desktop_shot), full_page=False)
            print(f"  Saved desktop screenshot to {desktop_shot}")

            # 6. Test legacy link with ?format=visual
            print("\n[Legacy URL Check] Testing ?format=visual...")
            page_desktop.goto(f"{BASE_URL}/forum/?format=visual")
            page_desktop.wait_for_selector(".forum-topic-card", timeout=10000)
            
            cards_with_legacy = page_desktop.locator(".forum-topic-card").count()
            print(f"  Cards with ?format=visual: {cards_with_legacy}")
            assert cards_with_legacy == cards_default, (
                f"Expected same card count ({cards_default}) with ?format=visual, got {cards_with_legacy}"
            )
            assert page_desktop.locator("[data-fformat]").count() == 0

            # 7. Test legacy link with ?format=text
            print("[Legacy URL Check] Testing ?format=text...")
            page_desktop.goto(f"{BASE_URL}/forum/?format=text")
            page_desktop.wait_for_selector(".forum-topic-card", timeout=10000)
            cards_with_text = page_desktop.locator(".forum-topic-card").count()
            print(f"  Cards with ?format=text: {cards_with_text}")
            assert cards_with_text == cards_default, (
                f"Expected same card count ({cards_default}) with ?format=text, got {cards_with_text}"
            )

            # Filter console errors to ignore favicon or network 404s
            fatal_errors = [e for e in console_errors if "favicon" not in e and "404" not in e]
            assert len(fatal_errors) == 0, f"Unexpected console errors: {fatal_errors}"
            print("  Legacy URL handling verified with zero errors and no filtering!")

            # --- Test 2: Mobile 390x844 ---
            print("\n[Mobile 390] Verifying forum header on mobile viewport...")
            page_mobile = browser.new_page(
                viewport={"width": 390, "height": 844},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
            )
            page_mobile.goto(f"{BASE_URL}/forum/")
            page_mobile.wait_for_selector(".forum-topic-card", timeout=10000)

            # Assert [data-fformat] does not exist
            assert page_mobile.locator("[data-fformat]").count() == 0
            assert page_mobile.locator('[data-fsort="hot"]').is_visible()
            assert page_mobile.locator("#forum-search-input").is_visible()
            assert page_mobile.locator(".forum-topic-card").count() > 0

            mobile_shot = SCREENSHOT_DIR / "forum_header_mobile_390.png"
            page_mobile.screenshot(path=str(mobile_shot), full_page=False)
            print(f"  Saved mobile screenshot to {mobile_shot}")

            browser.close()

        print("\n=== ALL BROWSER VERIFICATIONS PASSED SUCCESSFULLY! ===")

    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if db:
            try:
                db.close()
            except Exception:
                pass
        for k in env_patch:
            if old_env[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_env[k]
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
