"""Playwright browser verification for Direct Messages (Phase 1A).

Verifies on port 3097:
1. Two accounts (alice_test & bob_test) exchange DMs.
2. Alice sends a DM to Bob.
3. Bob's topbar navigation badge shows unread number.
4. Bob opens the conversation -> badge returns to 0, read cursor advances.
5. Alice opens the conversation -> sees "已读" on her sent message.
6. Mobile viewport (390x844) verification: messages center tabs, conversation view, and badge display cleanly without overflow.
7. Screenshots saved to C:/tmp/.
"""
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
    print("Setting up temporary environment and database for browser verification...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_dm_verify.db"
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
        alice, token_alice = register_user(db, "alice_test", "Password123!", display_name="爱丽丝")
        bob, token_bob = register_user(db, "bob_test", "Password123!", display_name="鲍勃")

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
            # Step 1: Alice logs in and sends DM to Bob
            # -------------------------------------------------------------
            print("Step 1: Alice logs in, opens messages page, sends DM to Bob...")
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

            # Go to direct messages tab to chat with Bob
            page_alice.goto(f"{BASE_URL}/?view=notifications&tab=dm&user=bob_test")
            page_alice.wait_for_selector("#hw-dm-input", timeout=8000)
            page_alice.fill("#hw-dm-input", "你好鲍勃，这是一条来自爱丽丝的测试私信！")
            page_alice.click("#hw-dm-send-btn")

            # Wait for bubble to appear in chat
            page_alice.wait_for_selector(".hw-dm-bubble-wrap.is-self", timeout=5000)
            print("  Alice sent message successfully.")

            # -------------------------------------------------------------
            # Step 2: Bob opens site -> Topbar badge shows 1
            # -------------------------------------------------------------
            print("Step 2: Bob opens site, verifying unread badge in topbar...")
            ctx_bob = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            ctx_bob.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_bob,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_bob = ctx_bob.new_page()
            page_bob.goto(f"{BASE_URL}/?view=discover")

            # Wait for topbar and unread badge
            page_bob.wait_for_selector('a[href*="notifications"] .hw-unread-badge', timeout=8000)
            badge_text = page_bob.inner_text('a[href*="notifications"] .hw-unread-badge')
            print(f"  Bob's topbar badge count: {badge_text}")
            assert badge_text == "1", f"Expected badge count 1, got {badge_text}"

            screenshot_badge = SCREENSHOT_DIR / "dm_01_bob_unread_badge_desktop.png"
            page_bob.screenshot(path=str(screenshot_badge))
            print(f"  Saved screenshot: {screenshot_badge}")

            # -------------------------------------------------------------
            # Step 3: Bob opens the conversation -> badge returns to 0
            # -------------------------------------------------------------
            print("Step 3: Bob opens conversation with Alice, verifying badge cleared to 0...")
            page_bob.click('a[href*="notifications"]')
            page_bob.wait_for_selector("#hw-msg-tab-dm", timeout=5000)
            page_bob.click("#hw-msg-tab-dm")

            # Select conversation with Alice
            page_bob.wait_for_selector('.hw-dm-conv-item[data-conv-id]', timeout=5000)
            page_bob.click('.hw-dm-conv-item[data-conv-id]')

            # Wait for messages area and read cursor to sync
            page_bob.wait_for_selector('.hw-dm-bubble-wrap.is-peer', timeout=5000)
            time.sleep(1.0)  # Allow read cursor network call and badge refresh

            # Badge should now be hidden (0 unread)
            badge_display = page_bob.eval_on_selector(
                'a[href*="notifications"] .hw-unread-badge',
                "el => window.getComputedStyle(el).display"
            )
            print(f"  Bob's badge display style after reading: {badge_display}")
            assert badge_display == "none", f"Expected badge to be hidden ('none'), got {badge_display}"

            screenshot_bob_read = SCREENSHOT_DIR / "dm_02_bob_conversation_read_desktop.png"
            page_bob.screenshot(path=str(screenshot_bob_read))
            print(f"  Saved screenshot: {screenshot_bob_read}")

            # -------------------------------------------------------------
            # Step 4: Alice checks conversation -> sees "已读"
            # -------------------------------------------------------------
            print("Step 4: Alice verifies her sent message shows '已读'...")
            page_alice.reload()
            page_alice.wait_for_selector('.hw-dm-conv-item[data-conv-id]', timeout=5000)
            page_alice.click('.hw-dm-conv-item[data-conv-id]')
            page_alice.wait_for_selector('.hw-dm-read-status.is-read', timeout=5000)
            read_status_text = page_alice.inner_text('.hw-dm-read-status.is-read')
            print(f"  Alice sees read status: {read_status_text}")
            assert "已读" in read_status_text, f"Expected '已读' in status, got {read_status_text}"

            screenshot_alice_read = SCREENSHOT_DIR / "dm_03_alice_sender_sees_read.png"
            page_alice.screenshot(path=str(screenshot_alice_read))
            print(f"  Saved screenshot: {screenshot_alice_read}")

            # -------------------------------------------------------------
            # Step 5: Mobile 390px viewport check
            # -------------------------------------------------------------
            print("Step 5: Testing Mobile 390x844 viewport...")
            ctx_mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                base_url=BASE_URL,
                is_mobile=True,
                has_touch=True,
            )
            ctx_mobile.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_bob,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_mobile = ctx_mobile.new_page()

            # Alice sends Bob another message so badge appears on mobile
            from backend.messaging import send_direct_message
            send_direct_message(db, alice, {
                "recipientId": bob["id"],
                "body": "鲍勃，这是移动端测试私信！",
                "clientMessageId": "mobile_test_msg_01",
            })

            page_mobile.goto(f"{BASE_URL}/?view=discover")
            page_mobile.wait_for_selector('a[href*="notifications"] .hw-unread-badge', timeout=8000)
            mob_badge = page_mobile.inner_text('a[href*="notifications"] .hw-unread-badge')
            print(f"  Mobile topbar badge: {mob_badge}")
            assert mob_badge == "1", f"Expected mobile badge 1, got {mob_badge}"

            # Open Messages page on mobile
            page_mobile.goto(f"{BASE_URL}/?view=notifications&tab=dm")
            page_mobile.wait_for_selector('.hw-dm-conv-item[data-conv-id]', timeout=8000)

            screenshot_mobile_list = SCREENSHOT_DIR / "dm_04_mobile_390_conv_list.png"
            page_mobile.screenshot(path=str(screenshot_mobile_list))
            print(f"  Saved screenshot: {screenshot_mobile_list}")

            # Open chat on mobile
            page_mobile.click('.hw-dm-conv-item[data-conv-id]')
            page_mobile.wait_for_selector('#hw-dm-messages-area .hw-dm-bubble-wrap', timeout=5000)
            time.sleep(0.5)

            screenshot_mobile_chat = SCREENSHOT_DIR / "dm_05_mobile_390_chat_view.png"
            page_mobile.screenshot(path=str(screenshot_mobile_chat))
            print(f"  Saved screenshot: {screenshot_mobile_chat}")

            # Verify no horizontal scrollbar on mobile
            has_h_scroll = page_mobile.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
            print(f"  Mobile page has horizontal scroll: {has_h_scroll}")
            assert not has_h_scroll, "Mobile page has horizontal scrollbar!"

            browser.close()

        print("\nALL BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")

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
