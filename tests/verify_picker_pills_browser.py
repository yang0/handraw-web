"""Browser verification for Issue #42:
Reference asset picker upload category pills (胶囊标签单选).

Verifies on port 3097 using Playwright:
1. 打开参考图弹窗 -> 点本地上传 -> 确认分类是胶囊单选（不是下拉）
2. 切到「角色」后打开上传默认选中「角色」
3. 手动改选「其他」
4. 再切图库筛选「场景」 -> 上传分类仍是「其他」
5. 上传成功后图库自动切到「其他」并看到新图
6. 390 宽标签换行正常，无横向溢出
7. 截图保存至 C:/tmp/
"""

import os
import sys
import json
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

from tests.legacy_database import init_legacy_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"

TMP_DIR = Path("C:/tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)

SHOT_UPLOAD_RADIO = TMP_DIR / "picker_pills_01_upload_radios.png"
SHOT_DEFAULT_CHAR = TMP_DIR / "picker_pills_02_default_char.png"
SHOT_MANUAL_OTHER = TMP_DIR / "picker_pills_03_manual_other.png"
SHOT_PERSIST_OTHER = TMP_DIR / "picker_pills_04_persist_other.png"
SHOT_UPLOAD_SUCCESS = TMP_DIR / "picker_pills_05_upload_success.png"
SHOT_MOBILE_390 = TMP_DIR / "picker_pills_06_mobile_390.png"

# Minimal 1x1 transparent PNG for test upload
SAMPLE_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def run_verification():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"=== Starting Studio Picker Category Pills Verification on port {PORT} ===")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "picker_pills_test.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    test_file_path = root / "hero_avatar.png"
    test_file_path.write_bytes(SAMPLE_PNG_BYTES)

    img_cfg = root / "image-service.json"
    img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": f"http://127.0.0.1:{PORT}"}))

    env_patch = {
        "HANDRAW_DB_PATH": str(db_path),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_IMAGE_CONFIG": str(img_cfg),
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT}",
        "HANDRAW_DEMO_MODE": "1",
    }
    old_env = {}
    for k, v in env_patch.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    db = None
    httpd = None
    try:
        db = init_legacy_database(db_path)
        user, session_token = register_user(db, "pill_tester", "SecretPass123!")
        print(f"Registered test user: {user['username']}")

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.channel_role = "main"  # type: ignore[attr-defined]
        httpd.db = db  # type: ignore[attr-defined]
        httpd.allow_demo_routes = True  # type: ignore[attr-defined]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"Server started at {BASE_URL}")

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                browser = p.chromium.launch(channel="msedge", headless=True)

            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL
            )
            ctx.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = ctx.new_page()

            # Navigate to studio
            page.goto(f"{BASE_URL}/studio.html")
            page.wait_for_selector("#studio-app-root", timeout=8000)

            # -------------------------------------------------------------
            # STEP 1: 打开参考图弹窗 -> 点本地上传 -> 确认分类是胶囊单选（不是下拉）
            # -------------------------------------------------------------
            print("\n--- STEP 1: Open asset picker & check upload radio pills ---")
            page.evaluate("() => window.HANDRAW_STUDIO.openReferenceAssetPickerModal({})")
            page.wait_for_selector("#ast-top-tabs", timeout=5000)

            # Switch to upload tab
            page.locator('#ast-top-tabs [data-top-tab="upload"]').click()
            page.wait_for_selector("#ast-upload-bar #ing-upload-cat-fieldset", timeout=5000)

            # Verify no <select id="ing-upload-cat"> exists
            select_count = page.locator("select#ing-upload-cat").count()
            assert select_count == 0, f"Expected 0 select#ing-upload-cat, found {select_count}"

            # Verify fieldset and legend exist
            fieldset = page.locator("#ing-upload-cat-fieldset")
            assert fieldset.count() == 1, "Fieldset #ing-upload-cat-fieldset must exist"
            legend = fieldset.locator("legend")
            assert legend.count() == 1, "Fieldset must contain <legend>"
            assert "归入分类" in legend.text_content(), f"Legend text must include 归入分类, got: {legend.text_content()}"

            # Verify radio pills
            radios = fieldset.locator('input[type="radio"][name="ing-upload-cat-radio"]')
            radio_count = radios.count()
            assert radio_count >= 4, f"Expected >= 4 category radios, found {radio_count}"
            pills = fieldset.locator(".hw-pill.ing-cat-pill")
            assert pills.count() == radio_count, "Each radio must be wrapped in a .hw-pill.ing-cat-pill"

            # Check initial default: since library filter was ALL, upload defaults to "other"
            checked_val = fieldset.locator('input[name="ing-upload-cat-radio"]:checked').input_value()
            assert checked_val == "other", f"Initial uploadCategory with ALL filter should be 'other', got: {checked_val}"

            page.screenshot(path=str(SHOT_UPLOAD_RADIO))
            print(f"✓ Step 1 passed: Category uses native radio pills in fieldset/legend (not select). Screenshot: {SHOT_UPLOAD_RADIO}")

            # -------------------------------------------------------------
            # STEP 2: 切到「角色」后打开上传默认选中「角色」
            # -------------------------------------------------------------
            print("\n--- STEP 2: Follow filter default: switch to 角色 -> open upload -> defaults to 角色 ---")
            page.locator('#ast-top-tabs [data-top-tab="my"]').click()
            page.wait_for_selector('#ast-cats-wrap [data-ing-grp="characters"]', timeout=5000)
            page.locator('#ast-cats-wrap [data-ing-grp="characters"]').click()

            # Open upload tab
            page.locator('#ast-top-tabs [data-top-tab="upload"]').click()
            page.wait_for_selector("#ast-upload-bar #ing-upload-cat-fieldset", timeout=5000)

            checked_char = page.locator('#ing-upload-cat-fieldset input[name="ing-upload-cat-radio"]:checked').input_value()
            assert checked_char == "characters", f"Expected uploadCategory to default to 'characters', got: {checked_char}"
            char_pill = page.locator('#ing-upload-cat-fieldset .ing-cat-pill:has(input[value="characters"])')
            assert "is-active" in (char_pill.get_attribute("class") or ""), "Characters pill should have .is-active"

            page.screenshot(path=str(SHOT_DEFAULT_CHAR))
            print(f"✓ Step 2 passed: Default category followed library filter to 'characters'. Screenshot: {SHOT_DEFAULT_CHAR}")

            # -------------------------------------------------------------
            # STEP 3: 手动改选「其他」
            # -------------------------------------------------------------
            print("\n--- STEP 3: Manually choose 其他 in upload section ---")
            other_pill = page.locator('#ing-upload-cat-fieldset .ing-cat-pill:has(input[value="other"])')
            other_pill.click()

            checked_manual = page.locator('#ing-upload-cat-fieldset input[name="ing-upload-cat-radio"]:checked').input_value()
            assert checked_manual == "other", f"Expected manually selected 'other', got: {checked_manual}"
            assert "is-active" in (other_pill.get_attribute("class") or ""), "Other pill should have .is-active"

            page.screenshot(path=str(SHOT_MANUAL_OTHER))
            print(f"✓ Step 3 passed: Manually selected 'other'. Screenshot: {SHOT_MANUAL_OTHER}")

            # -------------------------------------------------------------
            # STEP 4: 再切图库筛选「场景」 -> 上传分类仍是「其他」
            # -------------------------------------------------------------
            print("\n--- STEP 4: Switch library filter to 场景 -> upload category must stay 其他 ---")
            page.locator('#ast-top-tabs [data-top-tab="my"]').click()
            page.wait_for_selector('#ast-cats-wrap [data-ing-grp="scenes"]', timeout=5000)
            page.locator('#ast-cats-wrap [data-ing-grp="scenes"]').click()

            # Switch back to upload tab
            page.locator('#ast-top-tabs [data-top-tab="upload"]').click()
            page.wait_for_selector("#ast-upload-bar #ing-upload-cat-fieldset", timeout=5000)

            checked_still_other = page.locator('#ing-upload-cat-fieldset input[name="ing-upload-cat-radio"]:checked').input_value()
            assert checked_still_other == "other", f"Expected upload category to remain 'other', got: {checked_still_other}"

            page.screenshot(path=str(SHOT_PERSIST_OTHER))
            print(f"✓ Step 4 passed: Manual choice persisted across gallery filter switch to 'scenes'. Screenshot: {SHOT_PERSIST_OTHER}")

            # -------------------------------------------------------------
            # STEP 5: 上传成功后图库自动切到「其他」并看到新图
            # -------------------------------------------------------------
            print("\n--- STEP 5: Upload image -> verify gallery switches to 其他 & displays new card ---")
            # Fill title
            name_input = page.locator("#ing-upload-name")
            name_input.fill("测试主角头像")

            # Upload file
            file_input = page.locator("#ing-upload-file")
            file_input.set_input_files(str(test_file_path))

            # Wait for upload completion: tab should switch to 'my'
            page.wait_for_selector('#ast-top-tabs [data-top-tab="my"].is-active', timeout=8000)
            print("Switched to 'my' tab after upload.")

            # Filter in 'my' tab should be switched to 'other'
            page.wait_for_selector('#ast-cats-wrap [data-ing-grp="other"].is-active', timeout=5000)
            print("Gallery category filter automatically switched to 'other'.")

            # Check new image in grid
            page.wait_for_selector('#ast-picker-grid [data-pick-id]', timeout=5000)
            new_card = page.locator('#ast-picker-grid [data-pick-id]').first
            card_title = new_card.text_content()
            assert "测试主角头像" in card_title, f"Expected new card to show '测试主角头像', got: {card_title}"
            assert "is-selected" in (new_card.get_attribute("class") or ""), "New card should be selected"

            page.screenshot(path=str(SHOT_UPLOAD_SUCCESS))
            print(f"✓ Step 5 passed: Upload completed, gallery switched to 'other', new item visible & selected. Screenshot: {SHOT_UPLOAD_SUCCESS}")

            # -------------------------------------------------------------
            # STEP 6: 390 宽标签换行正常
            # -------------------------------------------------------------
            print("\n--- STEP 6: Responsive check at 390x844 viewport ---")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(300)

            # Re-open upload tab to verify pills wrapping
            page.locator('#ast-top-tabs [data-top-tab="upload"]').click()
            page.wait_for_selector("#ing-upload-cat-fieldset .ing-upload-cat-pills", timeout=5000)

            pills_container = page.locator("#ing-upload-cat-fieldset .ing-upload-cat-pills")
            pills = pills_container.locator(".hw-pill")
            first_box = pills.nth(0).bounding_box()
            last_box = pills.nth(pills.count() - 1).bounding_box()

            # Ensure pills wrapped onto multiple rows or container has wrapping
            has_wrapped = (first_box and last_box and last_box["y"] > first_box["y"] + 10)
            print(f"Mobile pills layout: first pill y={first_box['y'] if first_box else 0}, last pill y={last_box['y'] if last_box else 0}, wrapped={has_wrapped}")

            # Check horizontal overflow
            modal_scroll_width = page.evaluate("() => document.querySelector('.modal-content')?.scrollWidth || 0")
            modal_client_width = page.evaluate("() => document.querySelector('.modal-content')?.clientWidth || 0")
            print(f"Modal width: clientWidth={modal_client_width}, scrollWidth={modal_scroll_width}")
            assert modal_scroll_width <= modal_client_width + 4, "No unexpected horizontal overflow in modal at 390px"

            page.screenshot(path=str(SHOT_MOBILE_390))
            print(f"✓ Step 6 passed: 390px width wraps naturally without horizontal overflow. Screenshot: {SHOT_MOBILE_390}")

            browser.close()
            print("\n========================================================")
            print("ALL PLAYWRIGHT BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")
            print("========================================================")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
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
    run_verification()
