"""Browser end-to-end verification for Phase 3b-13a.

Verifies:
1. Author opens /t/USR-S34F3CE03BA -> clicks '使用此画风' -> opens /studio/?style=USR-S34F3CE03BA
   -> style is loaded and selected -> click Run -> generation succeeds (200).
   Screenshot saved to C:/tmp/phase13a-author-studio.png.
2. Non-author visitor opens /t/USR-S34F3CE03BA -> definition is hidden in forum -> clicks '使用此画风'
   -> opens /studio/?style=USR-S34F3CE03BA -> style is loaded without definition leak
   -> click Run -> generation succeeds (200).
   Screenshot saved to C:/tmp/phase13a-visitor-studio.png.
3. Anonymous visitor opens /t/USR-S34F3CE03BA -> clicks '使用此画风' -> login modal opens.
   Screenshot saved to C:/tmp/phase13a-anon-modal.png.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user, utc_now_iso
from backend import curation as C
from backend import resource_discussions as RD

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("Setting up temporary environment and database...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    # Set up valid cover with PIL
    from PIL import Image
    cover_file = uploads_dir / "cover_ink.jpg"
    img = Image.new("RGB", (240, 240), color=(220, 215, 200))
    img.save(cover_file, "JPEG")

    # Set up dummy image-service config so liveImageEnabled is True
    img_cfg = root / "image-service.json"
    img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": f"http://127.0.0.1:{PORT}"}))

    env_patch = {
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
        "HANDRAW_IMAGE_CONFIG": str(img_cfg),
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT}",
        "HANDRAW_DEMO_MODE": "0",
        "HANDRAW_ENABLE_RECHARGE": "0",
    }
    old_env = {}
    for k, v in env_patch.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    db = browser_postgres_database()

    # Register users
    author_user, author_token = register_user(db, "ink_master", "Pass1234")
    visitor_user, visitor_token = register_user(db, "art_fan", "Pass1234")

    # Author uploads cover
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, updated_at)
            VALUES (?, ?, 'cover', 'cover_ink.jpg', '/uploads/cover_ink.jpg', ?, 1024, ?, ?)
            """,
            ("upl_cover_ink", author_user["id"], str(cover_file), now_iso, now_iso),
        )

    # Author submits a style submission
    pending_code = "USR-S34F3CE03BA"
    style_payload = {
        "title": "水墨写意风投稿",
        "requestId": "req_browser_verify_001",
        "items": [
            {
                "kind": "style",
                "name": "水墨写意",
                "description": "传统水墨画意境，留白写意",
                "definition": "中国传统水墨画风格，高山流水，淡雅写意，毛笔宣纸质感",
                "cover": "/uploads/cover_ink.jpg",
                "images": ["/uploads/cover_ink.jpg"],
                "targetId": pending_code,
            }
        ]
    }
    sub_res = C.submit(db, author_user, style_payload)
    topic_id = sub_res["topicId"]
    pending_code = sub_res["submissions"][0]["targetId"]
    print(f"Submission created! topic_id={topic_id}, pending_code={pending_code}")

    httpd = None
    server_thread = None
    try:
        # Start HTTP server
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.channel_role = "main"
        httpd.db = db
        httpd.allow_demo_routes = True
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        print(f"Server started on {BASE_URL}")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            
            # -------------------------------------------------------------
            # 1. Author Flow
            # -------------------------------------------------------------
            print("\n>>> Testing Flow 1: Author ('ink_master')...")
            ctx_author = browser.new_context(viewport={"width": 1440, "height": 960})
            ctx_author.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": author_token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_author = ctx_author.new_page()
            def route_generate(route):
                try:
                    payload = json.loads(route.request.post_data or "{}")
                    payload["simulateGateway"] = "ok"
                    route.continue_(post_data=json.dumps(payload))
                except Exception:
                    route.continue_()
            page_author.route("**/api/studio/generate", route_generate)
            page_author.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
            page_author.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))
            def log_resp(resp):
                print(f"[HTTP {resp.status}] {resp.url}")
                if resp.status >= 400:
                    try:
                        print(f"  --> ERROR BODY: {resp.text()[:400]}")
                    except Exception:
                        pass
            page_author.on("response", log_resp)

            # Open topic page
            topic_url = f"{BASE_URL}/t/{pending_code}"
            print(f"Navigating to {topic_url}...")
            page_author.goto(topic_url)
            page_author.wait_for_selector(".topic-resource-mount", timeout=10000)

            # Check badge
            badge_text = page_author.inner_text(".topic-resource-mount")
            assert "投稿中 · 可试用" in badge_text, f"Expected badge in author view: {badge_text}"
            assert "中国传统水墨画风格" in badge_text, "Author should see full definition"
            print("  ✓ Author sees '投稿中 · 可试用' and definition")

            # Click '使用此画风'
            use_btn = page_author.wait_for_selector("#topic-resource-use-btn", timeout=5000)
            use_btn.click()
            page_author.wait_for_url("**/studio/**", timeout=10000)
            print(f"  ✓ Navigated to studio: {page_author.url}")

            # Verify Studio state
            page_author.wait_for_selector("#make-image-subject", timeout=10000)
            # Wait for resource to be resolved and picked
            page_author.wait_for_selector(f"[data-pick-kind='style1'].is-selected", timeout=8000)
            picker_card_text = page_author.inner_text("[data-pick-kind='style1']")
            assert "水墨写意" in picker_card_text or pending_code in picker_card_text, f"Style card should show style: {picker_card_text}"
            print("  ✓ Style card selected in Studio Make-Image tab")

            # Fill topic
            page_author.fill("#make-image-subject", "远山含黛，轻舟已过万重山")
            
            # Click Generate (Run)
            run_btn = page_author.wait_for_selector("#make-image-btn-run", timeout=5000)
            print("Clicking Generate in Studio...")
            with page_author.expect_response(lambda r: "/api/studio/generate" in r.url and r.request.method == "POST") as resp_info:
                run_btn.click()
            gen_resp = resp_info.value
            assert gen_resp.status == 200, f"Expected 200 generation, got {gen_resp.status}: {gen_resp.text()}"
            resp_json = gen_resp.json()
            assert resp_json.get("ok") is True or "genId" in resp_json, f"Generation response: {resp_json}"
            print("  ✓ Generation request succeeded with 200 OK")

            time.sleep(1)
            author_screenshot_path = SCREENSHOT_DIR / "phase13a-author-studio.png"
            page_author.screenshot(path=str(author_screenshot_path), full_page=True)
            print(f"  ✓ Author screenshot saved to {author_screenshot_path}")
            ctx_author.close()

            # -------------------------------------------------------------
            # 2. Non-Author Visitor Flow
            # -------------------------------------------------------------
            print("\n>>> Testing Flow 2: Visitor ('art_fan')...")
            ctx_visitor = browser.new_context(viewport={"width": 1440, "height": 960})
            ctx_visitor.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": visitor_token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_visitor = ctx_visitor.new_page()
            page_visitor.route("**/api/studio/generate", route_generate)

            # Open topic page
            page_visitor.goto(topic_url)
            page_visitor.wait_for_selector(".topic-resource-mount", timeout=10000)

            # Check badge and privacy
            mount_text = page_visitor.inner_text(".topic-resource-mount")
            assert "投稿中 · 可试用" in mount_text, f"Expected badge in visitor view: {mount_text}"
            assert "投稿中 · 定义审核后公开" in mount_text, f"Expected masked definition text: {mount_text}"
            assert "中国传统水墨画风格" not in mount_text, "Visitor MUST NOT see raw definition in UI!"
            # Verify no tip button
            assert page_visitor.locator("#topic-stamp-tip-btn").count() == 0, "Pending resource should not show tip button"
            print("  ✓ Visitor sees '投稿中 · 可试用', masked definition '投稿中 · 定义审核后公开', and no tip button")

            # Click '使用此画风'
            use_btn_visitor = page_visitor.wait_for_selector("#topic-resource-use-btn", timeout=5000)
            use_btn_visitor.click()
            page_visitor.wait_for_url("**/studio/**", timeout=10000)
            print(f"  ✓ Navigated to studio: {page_visitor.url}")

            # Verify Studio state
            page_visitor.wait_for_selector("#make-image-subject", timeout=10000)
            page_visitor.wait_for_selector(f"[data-pick-kind='style1'].is-selected", timeout=8000)
            card_text = page_visitor.inner_text("[data-pick-kind='style1']")
            assert "水墨写意" in card_text or pending_code in card_text
            print("  ✓ Style card selected in Studio for visitor")

            # Verify prompt preview does NOT leak definition
            page_visitor.fill("#make-image-subject", "江南小镇春色，流水人家")
            # Open prompt preview if collapsible
            prompt_toggle = page_visitor.locator("#make-image-prompt-toggle")
            if prompt_toggle.count() > 0 and prompt_toggle.is_visible():
                prompt_toggle.click()
                time.sleep(0.5)
            readonly_prompt = page_visitor.locator(".make-image-textarea.is-readonly").inner_text() if page_visitor.locator(".make-image-textarea.is-readonly").count() > 0 else ""
            assert "中国传统水墨画风格" not in readonly_prompt, f"Definition leaked in visitor studio prompt preview: {readonly_prompt}"
            print("  ✓ No definition leak in Studio prompt preview")

            page_visitor.on("response", log_resp)
            # Click Generate (Run)
            run_btn_visitor = page_visitor.wait_for_selector("#make-image-btn-run", timeout=5000)
            print("Clicking Generate as visitor...")
            with page_visitor.expect_response(lambda r: "/api/studio/generate" in r.url and r.request.method == "POST") as resp_info:
                run_btn_visitor.click()
            gen_resp_v = resp_info.value
            assert gen_resp_v.status == 200, f"Expected 200 generation for visitor, got {gen_resp_v.status}: {gen_resp_v.text()}"
            print("  ✓ Visitor generation request succeeded with 200 OK")

            time.sleep(1)
            visitor_screenshot_path = SCREENSHOT_DIR / "phase13a-visitor-studio.png"
            page_visitor.screenshot(path=str(visitor_screenshot_path), full_page=True)
            print(f"  ✓ Visitor screenshot saved to {visitor_screenshot_path}")
            ctx_visitor.close()

            # -------------------------------------------------------------
            # 3. Anonymous Flow
            # -------------------------------------------------------------
            print("\n>>> Testing Flow 3: Anonymous...")
            ctx_anon = browser.new_context(viewport={"width": 1440, "height": 960})
            page_anon = ctx_anon.new_page()

            page_anon.goto(topic_url)
            page_anon.wait_for_selector("#topic-resource-use-btn", timeout=10000)
            
            # Click '使用此画风' -> opens login modal
            page_anon.click("#topic-resource-use-btn")
            page_anon.wait_for_selector("#standalone-forum-auth-page, #forum-auth-mount, .hw-modal-panel, #auth-modal", timeout=5000)
            print("  ✓ Login modal opened on anonymous click")

            time.sleep(0.5)
            anon_screenshot_path = SCREENSHOT_DIR / "phase13a-anon-modal.png"
            page_anon.screenshot(path=str(anon_screenshot_path), full_page=True)
            print(f"  ✓ Anonymous modal screenshot saved to {anon_screenshot_path}")
            ctx_anon.close()

            browser.close()

        print("\nALL BROWSER VERIFICATION FLOWS COMPLETED SUCCESSFULLY!")

    finally:
        if httpd:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        if server_thread:
            server_thread.join(timeout=3)
        try:
            db.close()
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
    main()
