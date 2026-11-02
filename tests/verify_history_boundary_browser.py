"""Browser verification for generation history public boundary,
safe code-only prompt assembly, and catalog definition removal (#22).

Runs on port 3097 using Playwright.
Verifies:
1. Opens /studio/?style=FA-001&layout=SC-021
2. Enters theme '落日余晖中的古塔' into #make-image-subject
3. Opens prompt preview (#make-image-prompt-toggle)
4. Asserts prompt preview textarea (#make-image-prompt) displays ONLY codes (#FA-001, #SC-021) and user text, without definition text
5. Clicks copy prompt button (#make-image-copy-prompt) -> clipboard is code-only
6. Clicks generate button (#make-image-btn-run) -> request payload contains code-only prompt
7. In history view: snippet is code-only, copy prompt from history is code-only
8. /data/catalog.json has no definitions
9. Screenshot saved to C:/tmp/history_boundary_verified.png
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

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_PATH = Path("C:/tmp/history_boundary_verified.png")
SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)


def run_browser_verification():
    print(f"Setting up environment for port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_boundary_verify.db"
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
    user, token = register_user(db, "creator_leo", "Pass1234!")
    print(f"Registered user: {user['username']}")

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"
    httpd.db = db
    httpd.allow_demo_routes = True
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"Server started on {BASE_URL}")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)

            context = browser.new_context(
                viewport={"width": 1440, "height": 960},
                permissions=["clipboard-read", "clipboard-write"],
            )
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page = context.new_page()

            # 1. Verify /data/catalog.json via API
            print("1. Verifying /data/catalog.json has no definitions...")
            resp = page.request.get(f"{BASE_URL}/data/catalog.json")
            assert resp.status == 200, f"Failed to fetch catalog: {resp.status}"
            cat_data = resp.json()
            resources = cat_data.get("resources", [])
            assert len(resources) > 0, "Catalog resources empty"
            for r in resources:
                assert "definition" not in r, f"Found definition in resource {r.get('id')}"
            print("   [OK] /data/catalog.json stripped of all definitions!")

            # 2. Intercept generate API to check payload & return mock success
            generate_called = False
            def handle_generate(route):
                nonlocal generate_called
                generate_called = True
                try:
                    payload = json.loads(route.request.post_data or "{}")
                    prompt_sent = payload.get("prompt", "")
                    print(f"   [Generate API Called] Prompt sent by browser:\n{prompt_sent}")
                    assert "#FA-001" in prompt_sent or "FA-001" in prompt_sent
                    assert "#SC-021" in prompt_sent or "SC-021" in prompt_sent
                    assert "落日余晖中的古塔" in prompt_sent
                    assert "松散黑线" not in prompt_sent
                    assert "散漫线条" not in prompt_sent
                    assert "Adaptive Split" not in prompt_sent

                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({
                            "ok": True,
                            "genId": "gen_verify_test_001",
                            "status": "success",
                            "finalPrompt": "",
                            "promptMasked": False,
                            "imageUrl": "https://img.handraw-style.com/images/individual/FA/FA-001.webp",
                            "images": ["https://img.handraw-style.com/images/individual/FA/FA-001.webp"],
                            "items": [
                                {
                                    "id": "item_1",
                                    "imageUrl": "https://img.handraw-style.com/images/individual/FA/FA-001.webp",
                                    "title": "落日余晖中的古塔",
                                    "ratio": "3:4"
                                }
                            ]
                        })
                    )
                except Exception as exc:
                    print(f"   [Error in route handler]: {exc}")
                    route.abort()

            page.route("**/api/studio/generate", handle_generate)

            # 3. Open Studio with preselected style and layout
            target_url = f"{BASE_URL}/studio/?style=FA-001&layout=SC-021"
            print(f"2. Navigating to {target_url}...")
            page.goto(target_url)
            page.wait_for_selector("#make-image-subject", timeout=15000)
            print("   [OK] Studio loaded with style=FA-001 and layout=SC-021")

            # 4. Fill Subject
            print("3. Entering theme '落日余晖中的古塔'...")
            subject_input = page.locator("#make-image-subject")
            subject_input.fill("落日余晖中的古塔")
            # trigger input and change events to update internal state
            subject_input.dispatch_event("input")
            subject_input.dispatch_event("change")
            page.wait_for_timeout(500)

            # 5. Open Prompt Preview
            print("4. Inspecting prompt preview in Studio form...")
            prompt_toggle = page.locator("#make-image-prompt-toggle")
            if prompt_toggle.is_visible():
                prompt_toggle.click()
                page.wait_for_timeout(300)

            prompt_ta = page.locator("#make-image-prompt")
            assert prompt_ta.is_visible(), "Prompt preview textarea should be visible"
            preview_val = prompt_ta.input_value()
            print(f"   [Prompt Preview Value]:\n{preview_val}")

            assert "#FA-001" in preview_val, "Expected #FA-001 in prompt preview"
            assert "#SC-021" in preview_val, "Expected #SC-021 in prompt preview"
            assert "落日余晖中的古塔" in preview_val, "Expected theme in prompt preview"
            assert "散漫线条" not in preview_val, "Style definition must not leak"
            assert "松散黑线" not in preview_val, "Style definition must not leak"
            assert "自适应双拼" not in preview_val, "Layout definition must not leak"
            assert "Adaptive Split" not in preview_val, "Layout definition must not leak"
            print("   [OK] Studio prompt preview contains only code recipe and user text!")

            # 6. Test copy prompt button
            print("5. Testing copy prompt button (#make-image-copy-prompt)...")
            copy_btn = page.locator("#make-image-copy-prompt")
            copy_btn.click()
            page.wait_for_timeout(300)
            copied_text = page.evaluate("() => navigator.clipboard.readText()")
            print(f"   [Copied text]:\n{copied_text}")
            assert "#FA-001" in copied_text
            assert "#SC-021" in copied_text
            assert "落日余晖中的古塔" in copied_text
            assert "散漫线条" not in copied_text
            assert "松散黑线" not in copied_text
            print("   [OK] Copied prompt is code-only!")

            # 7. Click Generate
            print("6. Clicking generate button (#make-image-btn-run)...")
            run_btn = page.locator("#make-image-btn-run")
            run_btn.click()
            page.wait_for_timeout(2000)
            assert generate_called, "Generate API should have been called"
            print("   [OK] Generation triggered and succeeded!")

            # 8. Check History view
            print("7. Verifying History Stage prompt display and copy...")
            hist_btn = page.locator("#studio-mode-history")
            hist_btn.click()
            page.wait_for_selector(".ic-hist-prompt-snippet", timeout=10000)
            hist_snippet = page.inner_text(".ic-hist-prompt-snippet")
            print(f"   [History Snippet]: {hist_snippet}")
            assert "#FA-001" in hist_snippet
            assert "#SC-021" in hist_snippet
            assert "落日余晖中的古塔" in hist_snippet
            assert "散漫线条" not in hist_snippet
            assert "松散黑线" not in hist_snippet
            print("   [OK] History snippet is code-only!")

            # Test history copy button
            hist_copy = page.locator("[data-hist-copy-prompt]").first
            hist_copy.click()
            page.wait_for_timeout(300)
            hist_copied = page.evaluate("() => navigator.clipboard.readText()")
            print(f"   [History Copied text]:\n{hist_copied}")
            assert "#FA-001" in hist_copied
            assert "#SC-021" in hist_copied
            assert "落日余晖中的古塔" in hist_copied
            assert "散漫线条" not in hist_copied
            assert "松散黑线" not in hist_copied
            print("   [OK] History copied prompt is code-only!")

            # 9. Screenshot
            print(f"8. Capturing full-page screenshot to {SCREENSHOT_PATH}...")
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            assert SCREENSHOT_PATH.is_file(), "Screenshot file was not created"
            print(f"   [OK] Screenshot successfully saved! ({SCREENSHOT_PATH.stat().st_size} bytes)")

            browser.close()

    finally:
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=5)
        db.close_thread_conn()
        db.close()
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_browser_verification()
    print("\n=======================================================")
    print("ALL BROWSER END-TO-END VERIFICATION CHECKS PASSED!")
    print("=======================================================")
