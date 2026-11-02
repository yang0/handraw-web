"""Playwright browser verification for Admin Message Broadcasts (Phase B).

Verifies on port 3097:
1. Admin account publishes a broadcast via the 2-step flow:
   fills title + body -> preview first -> confirms "向全部现有用户发送".
2. Normal user account sees topbar badge +1.
3. Normal user opens Messages page -> sees pinned "管理员公告" at top of DM list.
4. Conversation is read-only (no reply textarea or send button).
5. Opening the conversation resets unread badge to 0.
6. Admin withdraws the broadcast.
7. Normal user refreshes and sees "【公告已撤回】" with body hidden.
8. Screenshots saved to C:/tmp/.
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

from playwright.sync_api import sync_playwright

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.services import register_user

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
    print("Setting up temporary environment and database for message broadcast browser verification...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_broadcast_verify.db"
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
        admin, token_admin = register_user(db, "admin_user", "AdminPass123!", display_name="超级管理员")
        with db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (admin["id"],))

        alice, token_alice = register_user(db, "alice_user", "AlicePass123!", display_name="爱丽丝")

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.channel_role = "main"  # type: ignore[attr-defined]
        httpd.db = db  # type: ignore[attr-defined]
        httpd.allow_demo_routes = True  # type: ignore[attr-defined]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"Test server running at {BASE_URL}")

        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            if os.path.exists(CHROME_PATH):
                launch_kwargs["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**launch_kwargs)

            # -------------------------------------------------------------
            # Step 1: Admin sends broadcast (preview first -> second confirmation)
            # -------------------------------------------------------------
            print("Step 1: Admin logs in and publishes a broadcast via 2-step confirmation...")
            ctx_admin = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            ctx_admin.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_admin,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_admin = ctx_admin.new_page()

            page_admin.goto(f"{BASE_URL}/?view=notifications&tab=dm")
            page_admin.wait_for_selector('[data-conv-id="broadcasts"]', timeout=8000)
            page_admin.click('[data-conv-id="broadcasts"]')

            # Click "发布群发公告" button
            page_admin.wait_for_selector("#hw-bc-publish-btn", timeout=5000)
            page_admin.click("#hw-bc-publish-btn")

            # Modal Step 1: Fill title and body
            page_admin.wait_for_selector("#hw-bc-title-input", timeout=5000)
            page_admin.fill("#hw-bc-title-input", "全站基础设施与性能架构升级公告")
            page_admin.fill("#hw-bc-body-input", "各位创作者大家好，系统现已完成性能优化与集群扩容，感谢大家的支持与厚爱！")

            # Click "预览公告 (先预览)"
            page_admin.click("#hw-bc-preview-btn")

            # Modal Step 2: Preview & Secondary Confirmation button
            page_admin.wait_for_selector("#hw-bc-confirm-send-btn", timeout=5000)
            btn_text = page_admin.inner_text("#hw-bc-confirm-send-btn")
            assert "向全部现有用户发送" in btn_text, f"Expected confirmation button, got: {btn_text}"

            # Secondary confirmation click
            page_admin.on("dialog", lambda dialog: dialog.accept())
            page_admin.click("#hw-bc-confirm-send-btn")

            # Wait for broadcast card to appear
            page_admin.wait_for_selector('.hw-bc-card[data-bc-id]', timeout=8000)
            print("  Admin broadcast published successfully.")

            # -------------------------------------------------------------
            # Step 2: Alice opens site -> sees unread badge = 1
            # -------------------------------------------------------------
            print("Step 2: Alice opens site, verifying unread badge in topbar...")
            ctx_alice = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            ctx_alice.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_alice,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_alice = ctx_alice.new_page()
            page_alice.goto(f"{BASE_URL}/?view=discover")

            # Wait for topbar and unread badge
            page_alice.wait_for_selector('a[href*="notifications"] .hw-unread-badge', timeout=8000)
            badge_text = page_alice.inner_text('a[href*="notifications"] .hw-unread-badge')
            print(f"  Alice's topbar badge count: {badge_text}")
            assert badge_text == "1", f"Expected badge count 1, got {badge_text}"

            screenshot_badge = SCREENSHOT_DIR / "bc_01_user_unread_badge_desktop.png"
            page_alice.screenshot(path=str(screenshot_badge))
            print(f"  Saved screenshot: {screenshot_badge}")

            # -------------------------------------------------------------
            # Step 3: Alice opens "管理员公告" -> read-only check & badge resets to 0
            # -------------------------------------------------------------
            print("Step 3: Alice opens '管理员公告', verifying read-only and badge reset...")
            page_alice.click('a[href*="notifications"]')
            page_alice.wait_for_selector("#hw-msg-tab-dm", timeout=5000)
            page_alice.click("#hw-msg-tab-dm")

            # Click pinned broadcast conversation
            page_alice.wait_for_selector('[data-conv-id="broadcasts"]', timeout=5000)
            page_alice.click('[data-conv-id="broadcasts"]')

            # Wait for broadcast card
            page_alice.wait_for_selector('.hw-bc-card[data-bc-id]', timeout=5000)
            bc_content = page_alice.inner_text('.hw-bc-card[data-bc-id]')
            assert "全站基础设施与性能架构升级公告" in bc_content, "Broadcast title not found"
            assert "各位创作者大家好" in bc_content, "Broadcast body not found"

            # Check read-only / non-replyable footer note
            footer_text = page_alice.inner_text('#hw-dm-footer')
            print(f"  Footer notice: {footer_text}")
            assert "不支持回复" in footer_text, f"Expected non-replyable notice, got: {footer_text}"

            # Ensure NO input textarea exists in chat pane
            input_count = page_alice.locator("#hw-dm-input").count()
            self_assert = input_count == 0
            assert self_assert, "Reply input should not exist for admin broadcast!"

            # Wait for mark-as-read call
            time.sleep(1.0)

            # Badge should now be hidden (0 unread)
            badge_display = page_alice.eval_on_selector(
                'a[href*="notifications"] .hw-unread-badge',
                "el => window.getComputedStyle(el).display"
            )
            print(f"  Alice's badge display style after reading: {badge_display}")
            assert badge_display == "none", f"Expected badge to be hidden ('none'), got {badge_display}"

            screenshot_read = SCREENSHOT_DIR / "bc_02_user_read_broadcast_desktop.png"
            page_alice.screenshot(path=str(screenshot_read))
            print(f"  Saved screenshot: {screenshot_read}")

            # -------------------------------------------------------------
            # Step 4: Admin withdraws the broadcast
            # -------------------------------------------------------------
            print("Step 4: Admin withdraws the broadcast...")
            page_admin.click(".btn-bc-withdraw")
            time.sleep(1.0)
            print("  Admin withdrawn broadcast successfully.")

            # -------------------------------------------------------------
            # Step 5: Alice refreshes -> sees "【公告已撤回】", body hidden
            # -------------------------------------------------------------
            print("Step 5: Alice refreshes and sees '公告已撤回'...")
            page_alice.goto(f"{BASE_URL}/?view=notifications&tab=dm")
            page_alice.wait_for_selector('[data-conv-id="broadcasts"]', timeout=8000)
            page_alice.click('[data-conv-id="broadcasts"]')

            page_alice.wait_for_selector('.hw-bc-card.is-withdrawn', timeout=5000)
            card_text = page_alice.inner_text('.hw-bc-card.is-withdrawn')
            print(f"  Card text after withdraw: {card_text}")
            assert "【公告已撤回】" in card_text, "Expected '【公告已撤回】' in card"
            assert "各位创作者大家好" not in card_text, "Body must be hidden after withdrawal!"

            screenshot_withdrawn = SCREENSHOT_DIR / "bc_03_user_sees_withdrawn_broadcast.png"
            page_alice.screenshot(path=str(screenshot_withdrawn))
            print(f"  Saved screenshot: {screenshot_withdrawn}")

            browser.close()

        print("\nALL BROWSER VERIFICATIONS FOR MESSAGE BROADCASTS PASSED SUCCESSFULLY!")

    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if db:
            db.close()
        for k in env_patch:
            if old_env.get(k) is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_env[k]
        temp_dir.cleanup()


if __name__ == "__main__":
    main()
