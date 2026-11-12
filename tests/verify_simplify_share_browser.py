import os
import sys
import json
import time
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"

SCREENSHOT_DESKTOP = Path("C:/tmp/share_panel_desktop.png")
SCREENSHOT_MOBILE = Path("C:/tmp/share_panel_mobile.png")
SCREENSHOT_PICKER = Path("C:/tmp/card_picker_contain.png")
SCREENSHOT_DESKTOP.parent.mkdir(parents=True, exist_ok=True)


def run_browser_verification():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
    user, token = register_user(db, "share_tester", "Pass1234!")
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
                browser = p.chromium.launch(headless=True)
            except Exception:
                browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"Origin": BASE_URL}
            )
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "domain": "127.0.0.1",
                "path": "/"
            }])
            page = context.new_page()

            # -------------------------------------------------------------
            # 1. Check Topic Share Drawer (Desktop 1440)
            # -------------------------------------------------------------
            print("\n[Step 1] Navigating to forum to find a topic...")
            page.goto(f"{BASE_URL}/forum/")
            page.wait_for_selector(".forum-topic-card", timeout=10000)

            first_card = page.locator(".forum-topic-card").first
            first_card.click()
            page.wait_for_selector("#topic-page-share", timeout=10000)
            print("Opened topic detail page")

            # Click topic share button
            share_btn = page.locator("#topic-page-share")
            share_btn.click()
            page.wait_for_selector("[data-inline-share-panel]", timeout=5000)

            # Verify share drawer is visible
            panel = page.locator("[data-inline-share-panel]")
            assert panel.is_visible(), "Inline share panel must be visible"

            # Verify only 1 action button: 📋 复制分享口令
            action_btns = panel.locator(".hw-inline-share-actions button")
            assert action_btns.count() == 1, f"Expected exactly 1 button in actions, found {action_btns.count()}"
            btn_text = action_btns.first.inner_text()
            assert "📋 复制分享口令" in btn_text, f"Expected button text '📋 复制分享口令', got {btn_text}"

            # Verify NO '作为卡片分享到论坛' button
            assert page.locator("[data-btn-share-card-forum]").count() == 0, "Must NOT have data-btn-share-card-forum"

            # Verify share copy URL has /t/ format
            textarea = panel.locator("[data-share-copy-textarea]")
            val = textarea.input_value()
            assert "https://handraw-style.com/t/" in val, f"Expected /t/ permalink in topic shareCopy, got: {val}"
            print("✓ Topic share drawer verified: sole copy button, no forum card button, /t/ URL")

            # Verify thumbnail container has hw-share-thumb-wrap and img has contain
            thumb_wrap = panel.locator(".hw-share-thumb-wrap")
            assert thumb_wrap.count() == 1, "hw-share-thumb-wrap container must exist"
            thumb_img = thumb_wrap.locator("img")
            fit_val = thumb_img.evaluate("el => window.getComputedStyle(el).objectFit")
            assert fit_val == "contain", f"Expected object-fit: contain, got {fit_val}"
            print(f"✓ Thumbnail verified: hw-share-thumb-wrap with object-fit: {fit_val}")

            # Screenshot desktop share panel
            panel.screenshot(path=str(SCREENSHOT_DESKTOP))
            print(f"✓ Saved desktop share screenshot to {SCREENSHOT_DESKTOP}")

            # -------------------------------------------------------------
            # 2. Check Mobile Viewport (390px)
            # -------------------------------------------------------------
            print("\n[Step 2] Verifying share panel on mobile (390px)...")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(500)

            copy_btn = panel.locator("[data-btn-copy-share]")
            box = copy_btn.bounding_box()
            parent_box = panel.locator(".hw-inline-share-actions").bounding_box()
            assert box and parent_box, "Buttons must have bounding boxes"
            # Button should be full width (>= 90% of parent width)
            assert box["width"] >= parent_box["width"] * 0.9, f"Mobile copy button should be full width: btn={box['width']}, parent={parent_box['width']}"
            print(f"✓ Mobile full-width verified: button width {box['width']}px in container {parent_box['width']}px")

            panel.screenshot(path=str(SCREENSHOT_MOBILE))
            print(f"✓ Saved mobile share screenshot to {SCREENSHOT_MOBILE}")

            # -------------------------------------------------------------
            # 3. Check Rich Editor Card Attachment Modal (contain & 1:1)
            # -------------------------------------------------------------
            print("\n[Step 3] Verifying rich editor card picker modal (contain & 1:1)...")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(f"{BASE_URL}/forum/?view=compose")
            page.wait_for_selector("#tb-insert-style", timeout=10000)

            insert_style_btn = page.locator("#tb-insert-style")
            insert_style_btn.click()
            page.wait_for_selector(".hw-modal-panel", timeout=5000)

            modal = page.locator(".hw-modal-panel")
            assert modal.is_visible(), "Card picker modal must be visible"

            # Check cards inside picker grid
            page.wait_for_selector("#card-picker-grid .hw-card", timeout=5000)
            cards = page.locator("#card-picker-grid .hw-card")
            assert cards.count() > 0, "Must have cards in picker grid"
            print(f"Found {cards.count()} cards in style tab")

            # Check first card media container
            first_media = cards.first.locator(".hw-picker-card-media")
            assert first_media.count() == 1, "Card must have .hw-picker-card-media container"

            media_style = first_media.evaluate("""el => {
                const s = window.getComputedStyle(el);
                return {
                    aspectRatio: s.aspectRatio,
                    width: el.clientWidth,
                    height: el.clientHeight
                };
            }""")
            print(f"Media container computed: {media_style}")
            assert abs(media_style["width"] - media_style["height"]) <= 2, f"Expected 1:1 square ratio, got width {media_style['width']} vs height {media_style['height']}"

            # Check first card img object-fit
            first_img = first_media.locator("img")
            img_fit = first_img.evaluate("el => window.getComputedStyle(el).objectFit")
            assert img_fit == "contain", f"Expected card img object-fit: contain, got {img_fit}"
            print(f"✓ Card media verified: 1:1 aspect ratio ({media_style['width']}x{media_style['height']}), object-fit: {img_fit}")

            # Switch to layout tab
            layout_tab = page.locator("[data-card-kind='layout']")
            layout_tab.click()
            page.wait_for_timeout(400)
            layout_cards = page.locator("#card-picker-grid .hw-card")
            assert layout_cards.count() > 0, "Layout tab should have cards"
            layout_media = layout_cards.first.locator(".hw-picker-card-media")
            assert layout_media.count() == 1, "Layout card must use .hw-picker-card-media"
            print("✓ Layout cards use .hw-picker-card-media")

            # Switch to work tab
            work_tab = page.locator("[data-card-kind='work']")
            work_tab.click()
            page.wait_for_timeout(400)
            work_cards = page.locator("#card-picker-grid .hw-card")
            if work_cards.count() > 0:
                work_media = work_cards.first.locator(".hw-picker-card-media")
                assert work_media.count() == 1, "Work card must use .hw-picker-card-media"
                print("✓ Work cards use .hw-picker-card-media")

            # Screenshot card picker modal
            modal.screenshot(path=str(SCREENSHOT_PICKER))
            print(f"✓ Saved card picker modal screenshot to {SCREENSHOT_PICKER}")

            # Close modal
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            # -------------------------------------------------------------
            # 4. Check Asset Picker Modal (openAssetPickerModal)
            # -------------------------------------------------------------
            print("\n[Step 4] Verifying openAssetPickerModal (contain & 1:1)...")
            page.evaluate("() => window.HANDRAW_SHARED.openAssetPickerModal({ kind: 'style' })")
            page.wait_for_selector("#picker-grid .hw-card", timeout=5000)

            asset_cards = page.locator("#picker-grid .hw-card")
            assert asset_cards.count() > 0, "Asset picker must show cards"
            first_asset_media = asset_cards.first.locator(".hw-picker-card-media")
            assert first_asset_media.count() == 1, "Asset picker card must use .hw-picker-card-media"
            asset_img_fit = first_asset_media.locator("img").evaluate("el => window.getComputedStyle(el).objectFit")
            assert asset_img_fit == "contain", f"Expected object-fit: contain in asset picker, got {asset_img_fit}"
            print(f"✓ Asset picker cards use .hw-picker-card-media with object-fit: {asset_img_fit}")

            # -------------------------------------------------------------
            # 5. Check Studio compose / publish entrance pipeline intact
            # -------------------------------------------------------------
            print("\n[Step 5] Verifying goToForumCompose and studio pipeline intact...")
            can_compose = page.evaluate("() => typeof window.HANDRAW_SHARED.goToForumCompose === 'function'")
            assert can_compose, "goToForumCompose must be exported and intact"
            print("✓ goToForumCompose pipeline verified")

            browser.close()
            print("\n========================================================")
            print("ALL PLAYWRIGHT BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")
            print("========================================================")
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_browser_verification()
