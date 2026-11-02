"""Browser verification for curation paste uploads (Issue #30).
Verifies:
1. 作品表单粘贴 2 张图 -> 都进作品图
2. 画风表单封面为空时粘贴 2 张 -> 第 1 张成封面、第 2 张进示例图
3. 封面已有再粘贴 -> 只追加示例图，封面不变
4. 文本框里粘贴普通文字 -> 正常输入
Screenshots saved to C:/tmp/
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

from http.server import ThreadingHTTPServer
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
    print(f"=== Starting verification server on port {PORT} ===")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "curation_paste_verify.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    img_cfg = root / "image-service.json"
    img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": f"http://127.0.0.1:{PORT}"}))

    env_patch = {
        "HANDRAW_DB_PATH": str(db_path),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_IMAGE_SERVICE_FILE": str(img_cfg),
        "HANDRAW_DEMO_MODE": "1",
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT}",
        "HANDRAW_ENABLE_RECHARGE": "0",
    }
    for k, v in env_patch.items():
        os.environ[k] = v

    db = init_database(db_path)
    user, session_token = register_user(db, "curation_paste_tester", "Pass12345!")

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"  # type: ignore[attr-defined]
    httpd.db = db  # type: ignore[attr-defined]
    httpd.allow_demo_routes = True  # type: ignore[attr-defined]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f"Server started at {BASE_URL}")

    try:
        with sync_playwright() as p:
            launch_args = {"headless": True}
            if os.path.exists(CHROME_PATH):
                launch_args["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"Origin": BASE_URL}
            )
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/"
            }])
            page = context.new_page()

            # Helper JS function to simulate pasting images into selector
            def paste_images_js(selector: str, configs: list[dict]):
                page.evaluate(
                    """([sel, cfgs]) => {
                        const target = document.querySelector(sel);
                        if (!target) throw new Error("Target selector not found: " + sel);
                        const dt = new DataTransfer();
                        cfgs.forEach((cfg, idx) => {
                            const canvas = document.createElement("canvas");
                            canvas.width = cfg.width || 800;
                            canvas.height = cfg.height || 800;
                            const ctx = canvas.getContext("2d");
                            ctx.fillStyle = cfg.color || "#4a90e2";
                            ctx.fillRect(0, 0, canvas.width, canvas.height);
                            const dataUrl = canvas.toDataURL("image/png");
                            const binStr = atob(dataUrl.split(",")[1]);
                            const arr = new Uint8Array(binStr.length);
                            for (let i = 0; i < binStr.length; i++) {
                                arr[i] = binStr.charCodeAt(i);
                            }
                            const file = new File([arr], cfg.name || ("pasted_" + idx + ".png"), { type: "image/png" });
                            dt.items.add(file);
                        });
                        const evt = new ClipboardEvent("paste", {
                            bubbles: true,
                            cancelable: true,
                            clipboardData: dt
                        });
                        target.dispatchEvent(evt);
                    }""",
                    [selector, configs]
                )

            # -------------------------------------------------------------
            # Scenario 1: 作品表单粘贴 2 张图 -> 都进作品图
            # -------------------------------------------------------------
            print("\n[Scenario 1] Testing paste 2 images into work form...")
            page.goto(f"{BASE_URL}/forum/?view=curation&tab=share")
            page.wait_for_selector(".curation-form", timeout=10000)

            # Ensure we are in work form
            page.wait_for_selector('input[data-act="title"]', timeout=5000)

            # Paste 2 images onto the form
            paste_images_js(".curation-form", [
                {"width": 800, "height": 800, "color": "#e74c3c", "name": "work_1.png"},
                {"width": 800, "height": 800, "color": "#3498db", "name": "work_2.png"},
            ])

            # Wait for thumbnails to appear
            page.wait_for_selector(".curation-imgs figure.curation-thumb-wrap:nth-child(2)", timeout=8000)
            work_thumbs_count = page.locator(".curation-imgs figure.curation-thumb-wrap").count()
            print(f"Work images count after paste: {work_thumbs_count}")
            assert work_thumbs_count == 2, f"Expected 2 work images, found {work_thumbs_count}"

            # Capture screenshot
            shot1 = SCREENSHOT_DIR / "curation_paste_work_2images.png"
            page.screenshot(path=str(shot1))
            print(f"Saved Screenshot 1: {shot1}")

            # -------------------------------------------------------------
            # Scenario 2: 画风表单封面为空时粘贴 2 张 -> 第 1 张成封面、第 2 张进示例图
            # -------------------------------------------------------------
            print("\n[Scenario 2] Testing paste 2 images into style form when cover is empty...")
            page.goto(f"{BASE_URL}/forum/?view=curation&tab=share&kind=style")
            page.wait_for_selector(".curation-form", timeout=10000)
            page.wait_for_selector('.curation-cover', timeout=5000)

            # Verify cover is currently empty
            assert page.locator('.curation-cover-preview').count() == 0, "Cover preview should not exist initially"

            # Paste 2 images on form
            paste_images_js(".curation-form", [
                {"width": 900, "height": 900, "color": "#2ecc71", "name": "style_cover.png"},
                {"width": 800, "height": 800, "color": "#f39c12", "name": "style_ex1.png"},
            ])

            # Wait for cover preview and example thumbnail
            page.wait_for_selector(".curation-cover-preview img", timeout=8000)
            page.wait_for_selector(".curation-examples .curation-imgs figure.curation-thumb-wrap", timeout=8000)

            has_cover = page.locator(".curation-cover-preview img").count()
            ex_count = page.locator(".curation-examples .curation-imgs figure.curation-thumb-wrap").count()
            print(f"Cover preview count: {has_cover}, example count: {ex_count}")
            assert has_cover == 1, "Expected 1st image to become cover preview"
            assert ex_count == 1, "Expected 2nd image to enter examples"

            cover_src = page.locator(".curation-cover-preview img").get_attribute("data-hw-src")

            # Capture screenshot
            shot2 = SCREENSHOT_DIR / "curation_paste_style_empty_cover_2images.png"
            page.screenshot(path=str(shot2))
            print(f"Saved Screenshot 2: {shot2}")

            # -------------------------------------------------------------
            # Scenario 3: 封面已有再粘贴 -> 只追加示例图，封面不变
            # -------------------------------------------------------------
            print("\n[Scenario 3] Testing paste when cover already exists (should only append examples)...")
            paste_images_js(".curation-form", [
                {"width": 800, "height": 800, "color": "#9b59b6", "name": "style_ex2.png"},
                {"width": 800, "height": 800, "color": "#1abc9c", "name": "style_ex3.png"},
            ])

            # Wait for example count to become 3 (1 previous + 2 new)
            page.wait_for_selector(".curation-examples .curation-imgs figure.curation-thumb-wrap:nth-child(3)", timeout=8000)
            ex_count_after = page.locator(".curation-examples .curation-imgs figure.curation-thumb-wrap").count()
            cover_src_after = page.locator(".curation-cover-preview img").get_attribute("data-hw-src")
            print(f"Example count after second paste: {ex_count_after}")
            assert ex_count_after == 3, f"Expected 3 example images, found {ex_count_after}"
            assert cover_src_after == cover_src, "Cover image must not change when cover already existed"

            # Capture screenshot
            shot3 = SCREENSHOT_DIR / "curation_paste_style_existing_cover_append.png"
            page.screenshot(path=str(shot3))
            print(f"Saved Screenshot 3: {shot3}")

            # -------------------------------------------------------------
            # Scenario 4: 文本框里粘贴普通文字 -> 正常输入
            # -------------------------------------------------------------
            print("\n[Scenario 4] Testing paste normal text into text input...")
            # Click and focus name input
            name_input = page.locator('input[data-act="name"]')
            name_input.click()

            # Simulate pasting text into name input
            page.evaluate(
                """([sel, textToPaste]) => {
                    const el = document.querySelector(sel);
                    el.focus();
                    const dt = new DataTransfer();
                    dt.setData("text/plain", textToPaste);
                    const evt = new ClipboardEvent("paste", {
                        bubbles: true,
                        cancelable: true,
                        clipboardData: dt
                    });
                    el.dispatchEvent(evt);
                    if (!evt.defaultPrevented) {
                        el.value = textToPaste;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                    }
                }""",
                ['input[data-act="name"]', "水墨淡彩新画风"]
            )

            # Wait a tick and verify value
            time.sleep(0.5)
            val = name_input.input_value()
            print(f"Input value after text paste: '{val}'")
            assert val == "水墨淡彩新画风", f"Expected '水墨淡彩新画风', got '{val}'"

            # Also check description textarea text paste
            desc_textarea = page.locator('textarea[data-act="description"]')
            desc_textarea.click()
            page.evaluate(
                """([sel, textToPaste]) => {
                    const el = document.querySelector(sel);
                    el.focus();
                    const dt = new DataTransfer();
                    dt.setData("text/plain", textToPaste);
                    const evt = new ClipboardEvent("paste", {
                        bubbles: true,
                        cancelable: true,
                        clipboardData: dt
                    });
                    el.dispatchEvent(evt);
                    if (!evt.defaultPrevented) {
                        el.value = textToPaste;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                    }
                }""",
                ['textarea[data-act="description"]', "适合写意山水插画创作，特点是意境幽远，笔触细腻。"]
            )
            time.sleep(0.5)
            desc_val = desc_textarea.input_value()
            assert "幽远" in desc_val, "Description textarea successfully received pasted text"

            # Capture screenshot
            shot4 = SCREENSHOT_DIR / "curation_paste_text_input_unaffected.png"
            page.screenshot(path=str(shot4))
            print(f"Saved Screenshot 4: {shot4}")

            browser.close()

        print("\n=== ALL PLAYWRIGHT BROWSER VERIFICATIONS PASSED SUCCESSFULLY! ===")
    finally:
        httpd.shutdown()
        if db:
            try:
                db.close()
            except Exception:
                pass
        temp_dir.cleanup()


if __name__ == "__main__":
    main()
