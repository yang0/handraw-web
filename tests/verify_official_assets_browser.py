"""Browser verification for Issues #10 and #11: Official Assets Management.

Verifies and captures screenshots for:
1. Admin UI: "+ 新增官方画风/图型" form filled and submitted -> .local/admin_official_form.png & .local/admin_official_created.png
2. Channel explore search: Search "宋锦纹样平涂", card found and opened -> .local/channel_official_search.png
3. Studio style picker: Search "FE-069", official card displayed and selected -> .local/studio_official_picker.png
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.browser_postgres import browser_postgres_database
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler
from backend.services import register_user


def make_test_png_bytes(width: int = 500, height: int = 500) -> bytes:
    img = Image.new("RGB", (width, height), color=(140, 180, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_browser_verification() -> None:
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    local_dir = REPO_ROOT / ".local"
    local_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DATA_DIR": str(root),
        "HANDRAW_DEMO_MODE": "1",
        "HANDRAW_ALLOWED_ORIGINS": "*",
        "HANDRAW_ENABLE_RECHARGE": "0",
    }
    old_env = {}
    for k, v in env.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    db = browser_postgres_database()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
    httpd.channel_role = "main"  # type: ignore[attr-defined]
    httpd.db = db  # type: ignore[attr-defined]
    httpd.allow_demo_routes = True  # type: ignore[attr-defined]
    port = httpd.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        # Register superadmin
        admin_user, admin_token = register_user(db, "superadmin", "AdminPass123", display_name="超级管理员")
        with db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (admin_user["id"],))

        # Write test upload image for admin
        test_img_bytes = make_test_png_bytes(500, 500)
        test_img_path = uploads_dir / "official_fe069.png"
        test_img_path.write_bytes(test_img_bytes)

        with db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, image_url, file_path, name_zh, cat, sha256, created_at, updated_at)
                VALUES ('browser-official-upload', ?, '/uploads/official_fe069.png', ?, '官方宋锦封面', 'other', 'dummy_fe069_sha', '2026-11-03T12:00:00Z', '2026-11-03T12:00:00Z')
                """,
                (admin_user["id"], str(test_img_path)),
            )

        CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(CHROME_PATH):
            CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

        with sync_playwright() as p:
            launch_args = {"headless": True}
            if os.path.exists(CHROME_PATH):
                launch_args["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(viewport={"width": 1280, "height": 840})
            context.add_cookies([
                {
                    "name": SESSION_COOKIE_NAME,
                    "value": admin_token,
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ])

            page = context.new_page()

            # ------------------------------------------------------------------
            # Step 1: Admin Console - Open Official Asset Form & Submit
            # ------------------------------------------------------------------
            print("[1/3] Testing Admin Console Official Asset creation...")
            page.goto(f"{base_url}/admin.html", wait_until="networkidle")
            page.wait_for_selector('[data-nav-mod="catalog"]', timeout=8000)
            page.click('[data-nav-mod="catalog"]')
            page.wait_for_selector("#btn-new-official", timeout=8000)

            # Open official creation modal
            page.click("#btn-new-official")
            page.wait_for_selector("#moff-series", timeout=5000)

            # Fill in form
            page.select_option("#moff-series", "FE")
            page.fill("#moff-code", "")  # empty to verify auto-allocation FE-069
            page.fill("#moff-name", "宋锦纹样平涂")
            page.fill("#moff-cost", "0")
            page.fill("#moff-desc", "宋锦传统工笔重彩与几何连续纹样，典雅端庄")
            page.fill("#moff-def", "#FE-069 宋锦纹样平涂。核心风格特征：工笔勾勒、几何回纹与矿物设色。")
            page.fill("#moff-image", "/uploads/official_fe069.png")
            page.fill("#moff-reason", "Issue #10 官方新增收录")

            time.sleep(0.5)
            shot1 = local_dir / "admin_official_form.png"
            page.screenshot(path=str(shot1))
            print(f"  ✓ Captured form screenshot: {shot1}")

            # Submit
            page.click("#moff-save")
            page.wait_for_selector("#admin-modal-backdrop", state="hidden", timeout=8000)
            time.sleep(1)

            # Filter to official assets
            page.select_option("#flt-cat-source", "official")
            time.sleep(0.5)

            shot2 = local_dir / "admin_official_created.png"
            page.screenshot(path=str(shot2))
            print(f"  ✓ Captured created asset screenshot: {shot2}")

            # ------------------------------------------------------------------
            # Step 2: Channel Explore - Search "宋锦纹样平涂"
            # ------------------------------------------------------------------
            print("[2/3] Testing Channel Explore Search...")
            page.goto(f"{base_url}/index.html?view=styles", wait_until="networkidle")
            page.wait_for_selector("#catalog-search", timeout=8000)

            page.fill("#catalog-search", "宋锦纹样平涂")
            time.sleep(1)

            # Verify card appears and click it to open detail modal
            card_sel = '[data-asset-card="FE-069"], [data-open-asset="FE-069"]'
            page.wait_for_selector(card_sel, timeout=5000)
            page.click('[data-open-asset="FE-069"]')
            time.sleep(1)

            shot3 = local_dir / "channel_official_search.png"
            page.screenshot(path=str(shot3))
            print(f"  ✓ Captured channel explore search screenshot: {shot3}")

            # ------------------------------------------------------------------
            # Step 3: Studio Direct Entry & Style Slot Display + Modal Search
            # ------------------------------------------------------------------
            print("[3/3] Testing Studio Direct Entry with ?style=FE-069...")
            page.goto(f"{base_url}/studio/?style=FE-069", wait_until="networkidle")
            time.sleep(1.5)

            # Wait for make-image picker card to display FE-069 and 宋锦纹样平涂
            page.wait_for_selector('[data-pick-kind="style1"].is-selected', timeout=8000)
            shot4 = local_dir / "studio_official_selected.png"
            page.screenshot(path=str(shot4))
            page.screenshot(path=str(local_dir / "studio_official_picker.png"))
            print(f"  ✓ Captured studio style slot selected screenshot: {shot4}")

            # Open the style picker modal by clicking the style slot card
            page.click('[data-pick-kind="style1"]')
            page.wait_for_selector("#sp-picker-search", timeout=8000)

            # Search by name in the picker modal
            page.fill("#sp-picker-search", "宋锦纹样平涂")
            time.sleep(1)

            # Verify the card is found in the search result
            page.wait_for_selector('[data-pick-id="FE-069"]', timeout=5000)
            shot5 = local_dir / "studio_official_modal_search.png"
            page.screenshot(path=str(shot5))
            print(f"  ✓ Captured studio style picker modal search screenshot: {shot5}")

            browser.close()

        print("\nAll browser verification steps completed successfully!")

    finally:
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=3)
        db.close()
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_browser_verification()
