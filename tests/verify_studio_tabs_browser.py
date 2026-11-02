"""Playwright browser verification for Issue #58: Remove '文章配图' tab from studio mode bar.

Verifies on port 3103:
1. Studio top bar does NOT directly show '文章配图' button.
2. Clicking '更多 ▾' opens dropdown containing '高级画布' and '文章配图'.
3. Clicking '文章配图' in menu successfully enters article creation stage, and '更多 ▾' is highlighted.
4. Direct deep link /studio/?entry=article directly enters article editor.
5. Mode switching between 做图 / 批量 / 高级画布 highlights normally without console errors.
6. Screenshots saved to C:/tmp/:
   - C:/tmp/studio_01_top_bar_no_article_tab.png
   - C:/tmp/studio_02_more_menu_open.png
   - C:/tmp/studio_03_entered_article_from_menu.png
   - C:/tmp/studio_04_direct_entry_article.png
   - C:/tmp/studio_05_switched_modes.png
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from backend.config import SESSION_COOKIE_NAME
from backend.server import HandrawRequestHandler, init_database
from backend.services import create_session_for_user, register_user

PORT = 3103
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def run_browser_verification():
    print("[1/5] Setting up temporary test environment...")
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{PORT}"
    os.environ["HANDRAW_PRIVATE_STORAGE"] = temp_dir.name
    os.environ["HANDRAW_DEMO_MODE"] = "1"

    db_path = Path(temp_dir.name) / "browser_verify.db"
    db = init_database(db_path)

    # Register user and get session token
    user, session_token = register_user(db, "test_creator", "password123")
    conn = db.get_conn()
    conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user["id"],))
    conn.commit()

    server = None
    try:
        print(f"[2/5] Starting HTTP server on port {PORT}...")
        server = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        server.db = db
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        console_errors = []

        print("[3/5] Launching Playwright browser...")
        with sync_playwright() as p:
            browser_kwargs = {"headless": True}
            if os.path.exists(CHROME_PATH):
                browser_kwargs["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**browser_kwargs)

            context = browser.new_context(viewport={"width": 1440, "height": 900})
            # Set session cookie to avoid hitting auth rate limits
            context.add_cookies([
                {
                    "name": SESSION_COOKIE_NAME,
                    "value": session_token,
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ])

            page = context.new_page()

            def on_console(msg):
                if msg.type == "error":
                    console_errors.append(msg.text)

            def on_page_error(err):
                console_errors.append(str(err))

            page.on("console", on_console)
            page.on("pageerror", on_page_error)

            # ==============================================================
            # Test 1: Studio Top Bar (Desktop 1440x900) - No Article Tab Directly
            # ==============================================================
            print("Testing Studio Top Bar (default '做图' mode)...")
            page.goto(f"{BASE_URL}/studio/", wait_until="networkidle")
            page.wait_for_selector("#studio-mode-quick", timeout=10000)

            # Check top bar buttons directly visible
            btn_quick = page.locator("#studio-mode-quick")
            btn_batch = page.locator("#studio-mode-batch")
            btn_more = page.locator("#studio-mode-more-btn")
            more_menu = page.locator("#studio-mode-more-menu")

            assert btn_quick.is_visible(), "做图 button must be visible"
            assert btn_batch.is_visible(), "批量 button must be visible"
            assert btn_more.is_visible(), "更多 ▾ button must be visible"
            assert not more_menu.is_visible(), "更多 menu must be hidden by default"

            # Assert that #studio-mode-article is NOT a visible direct button outside the menu
            direct_article_btn = page.locator(".qc-mode-switch > #studio-mode-article")
            assert direct_article_btn.count() == 0, "Top bar must not contain #studio-mode-article as a direct child"

            s1 = SCREENSHOT_DIR / "studio_01_top_bar_no_article_tab.png"
            page.screenshot(path=str(s1))
            print(f"Captured {s1}")

            # ==============================================================
            # Test 2: Click '更多 ▾' to open dropdown menu
            # ==============================================================
            print("Testing clicking '更多 ▾'...")
            btn_more.click()
            page.wait_for_timeout(300)

            assert more_menu.is_visible(), "更多 menu must be visible after click"
            item_canvas = page.locator("#studio-mode-canvas")
            item_article = page.locator("#studio-mode-article")

            assert item_canvas.is_visible(), "高级画布 item must be visible in menu"
            assert item_article.is_visible(), "文章配图 item must be visible in menu"

            s2 = SCREENSHOT_DIR / "studio_02_more_menu_open.png"
            page.screenshot(path=str(s2))
            print(f"Captured {s2}")

            # Click '文章配图' in menu
            print("Clicking '文章配图' in menu...")
            item_article.click()
            page.wait_for_timeout(500)

            # In article mode, '更多 ▾' button should have btn-primary / is-active
            more_btn_classes = btn_more.get_attribute("class") or ""
            assert "btn-primary" in more_btn_classes or "is-active" in more_btn_classes, f"更多 button must highlight when in article mode, got: {more_btn_classes}"

            # Current URL should reflect ?entry=article
            assert "entry=article" in page.url, f"URL must contain entry=article, got: {page.url}"

            s3 = SCREENSHOT_DIR / "studio_03_entered_article_from_menu.png"
            page.screenshot(path=str(s3))
            print(f"Captured {s3}")

            # ==============================================================
            # Test 3: Direct Deep Link /studio/?entry=article
            # ==============================================================
            print("Testing direct deep link /studio/?entry=article...")
            page.goto(f"{BASE_URL}/studio/?entry=article", wait_until="networkidle")
            page.wait_for_selector("#studio-mode-more-btn", timeout=10000)
            page.wait_for_timeout(500)

            more_btn_deep = page.locator("#studio-mode-more-btn")
            more_deep_classes = more_btn_deep.get_attribute("class") or ""
            assert "btn-primary" in more_deep_classes, f"更多 button must be highlighted on ?entry=article, got: {more_deep_classes}"

            s4 = SCREENSHOT_DIR / "studio_04_direct_entry_article.png"
            page.screenshot(path=str(s4))
            print(f"Captured {s4}")

            # ==============================================================
            # Test 4: Switching between 做图 / 批量 / 高级画布
            # ==============================================================
            print("Testing switching between modes...")
            # 1. Switch to 做图
            page.locator("#studio-mode-quick").click()
            page.wait_for_timeout(300)
            quick_classes = page.locator("#studio-mode-quick").get_attribute("class") or ""
            assert "btn-primary" in quick_classes, "做图 must be highlighted"

            # 2. Switch to 批量
            page.locator("#studio-mode-batch").click()
            page.wait_for_timeout(300)
            batch_classes = page.locator("#studio-mode-batch").get_attribute("class") or ""
            assert "btn-primary" in batch_classes, "批量 must be highlighted"

            # 3. Switch to 高级画布
            page.locator("#studio-mode-more-btn").click()
            page.wait_for_timeout(200)
            page.locator("#studio-mode-canvas").click()
            page.wait_for_timeout(300)
            canvas_more_classes = page.locator("#studio-mode-more-btn").get_attribute("class") or ""
            assert "btn-primary" in canvas_more_classes, "更多 button must be highlighted for canvas"

            s5 = SCREENSHOT_DIR / "studio_05_switched_modes.png"
            page.screenshot(path=str(s5))
            print(f"Captured {s5}")

            # Verify no console errors
            print(f"Console errors encountered: {console_errors}")
            assert len(console_errors) == 0, f"Found unexpected console errors: {console_errors}"

            browser.close()

    finally:
        print("[4/5] Shutting down ephemeral server...")
        if server:
            server.shutdown()
            server.server_close()
        try:
            db.get_conn().close()
            db.close()
        except Exception:
            pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass

    print("[5/5] Verification completed successfully!")


if __name__ == "__main__":
    run_browser_verification()
