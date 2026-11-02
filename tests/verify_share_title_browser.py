"""Browser verification for Task #4 (Issue #5): Share title uses real generation subject.

Verifies:
1. Seeds a generation history entry with theme '雨夜书店' and workspace tabTitle '图文模式'.
2. Opens Studio History stage and clicks '✨ 晒图' on that history entry.
3. Automatically transitions to Forum compose page.
4. Asserts #compose-title-input value is exactly '雨夜书店' and NOT '图文模式' or '图文模式 · 成图 #1'.
5. User edits title to '雨夜书店·读者手记', reopens compose view, and asserts manual edit is preserved.
6. Saves verification screenshot to C:/tmp/share_title_verified.png.
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

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.services import register_user

PORT = 3128
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_PATH = Path("C:/tmp/share_title_verified.png")
SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)


def run_verification():
    print(f"Starting test server on port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_share_title.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    img_cfg = root / "image-service.json"
    img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": f"http://127.0.0.1:{PORT}"}))

    os.environ["HANDRAW_DB_PATH"] = str(db_path)
    os.environ["HANDRAW_UPLOADS_DIR"] = str(uploads_dir)
    os.environ["HANDRAW_GENERATED_DIR"] = str(generated_dir)
    os.environ["HANDRAW_IMAGE_CONFIG"] = str(img_cfg)
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{PORT}"
    os.environ["HANDRAW_DEMO_MODE"] = "1"

    db = init_database(db_path)
    user, token = register_user(db, "creator_rain", "Secret1234!", display_name="雨夜创作者")
    print(f"Registered user: {user['username']}")

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"  # type: ignore[attr-defined]
    httpd.db = db  # type: ignore[attr-defined]
    httpd.allow_demo_routes = True  # type: ignore[attr-defined]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"Server started on {BASE_URL}")

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

            # 1. Open Studio page
            print("1. Opening /studio/...")
            page.goto(f"{BASE_URL}/studio/", wait_until="networkidle")

            # 2. Inject seeded history entry with subject '雨夜书店' and tabTitle '图文模式'
            print("2. Injecting generation history entry: subject='雨夜书店', tabTitle='图文模式'...")
            page.evaluate("""() => {
                const testEntry = {
                    id: "hist_rainy_bookstore_test",
                    tabTitle: "图文模式",
                    subject: "雨夜书店",
                    createdAt: "2026-11-03 03:00:00",
                    timeShort: "03:00",
                    mode: "graphic-text",
                    modeLabel: "图文创作 · 1 张",
                    kind: "single",
                    recipeSummary: "画风 #FA-003 · 3:4",
                    prompt: "雨夜书店暖黄色灯光下的安静读者",
                    items: [
                        {
                            id: "it_rain_01",
                            title: "成图 #1",
                            subject: "雨夜书店",
                            ratio: "3:4",
                            prompt: "雨夜书店暖黄色灯光下的安静读者",
                            imageUrl: "/images/poster-demo-autumn-equinox.webp"
                        }
                    ]
                };

                const S = window.HANDRAW_STUDIO || {};
                let cur = (S.getHistory && S.getHistory()) || [];
                cur.unshift(testEntry);
                if (S.setHistory) {
                    S.setHistory(cur);
                }
            }""")

            # 3. Open history stage
            print("3. Navigating to Studio History stage...")
            page.evaluate("() => { if (window.HANDRAW_STUDIO && window.HANDRAW_STUDIO.openHistoryStage) window.HANDRAW_STUDIO.openHistoryStage(); }")
            page.wait_for_selector(".ic-hist-entry-card[data-hist-id='hist_rainy_bookstore_test']", timeout=10000)

            # Check title in history card
            card_title = page.locator(".ic-hist-entry-card[data-hist-id='hist_rainy_bookstore_test'] .ic-hist-entry-head strong").inner_text()
            print(f"History card displayed title: '{card_title}'")
            assert "雨夜书店" in card_title, f"History card title should display '雨夜书店', got: {card_title}"

            # 4. Click '✨ 晒图' on this history entry
            print("4. Clicking '✨ 晒图' on history entry...")
            share_btn = page.locator("button[data-hist-share='hist_rainy_bookstore_test']")
            share_btn.click()

            # Wait for forum compose page to load
            page.wait_for_selector("#compose-title-input", timeout=10000)
            print("Forum compose page loaded.")

            # 5. Assert #compose-title-input value
            title_val = page.locator("#compose-title-input").input_value()
            print(f"Actual compose draft title: '{title_val}'")
            assert title_val == "雨夜书店", f"Expected title '雨夜书店', but got '{title_val}'"
            assert "图文模式" not in title_val, "Title must NOT contain workspace mode '图文模式'"
            assert "成图" not in title_val, "Title must NOT contain synthetic '成图'"

            # 6. Test manual title edit retention
            print("5. Testing manual title edit retention...")
            page.locator("#compose-title-input").fill("雨夜书店·读者手记")
            page.wait_for_timeout(300)

            # Navigate back to list, then reopen compose
            page.locator("#compose-back-btn").click()
            page.wait_for_selector(".hw-forum-topics-list, #forum-app-root", timeout=8000)
            print("Navigated back to forum.")

            # Reopen compose
            page.goto(f"{BASE_URL}/forum/?view=compose", wait_until="networkidle")
            page.wait_for_selector("#compose-title-input", timeout=8000)
            reopened_title = page.locator("#compose-title-input").input_value()
            print(f"Reopened draft title: '{reopened_title}'")
            assert reopened_title == "雨夜书店·读者手记", f"Manual title must be preserved, got '{reopened_title}'"

            # 7. Take verification screenshot
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            print(f"Screenshot saved to {SCREENSHOT_PATH} ({SCREENSHOT_PATH.stat().st_size} bytes)")

            browser.close()
            print("All browser verifications passed!")
    finally:
        httpd.shutdown()
        server_thread.join(timeout=3)
        db.close()
        temp_dir.cleanup()


if __name__ == "__main__":
    run_verification()
