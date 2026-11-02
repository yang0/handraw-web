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

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.services import register_user, publish_forum_topic_post, publish_forum_reply_post

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_PATH = Path("C:/tmp/inject_guard_browser.png")
SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)


def run_browser_verification():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Setting up test server on port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_inject_guard_test.db"
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
    httpd = None

    try:
        author_user, author_token = register_user(db, "author_normal", "Pass1234!")
        attacker_user, attacker_token = register_user(db, "attacker_joe", "Pass1234!")

        # 1. Create a normal topic
        topic_res = publish_forum_topic_post(
            db,
            author_user,
            {
                "category": "experience",
                "title": "测试安全防御的主题帖",
                "summary": "这是一个正常的主题帖",
                "body": "请在下方测试注入攻击防御能力",
                "images": [],
            },
        )
        topic_id = topic_res["topicId"]

        # 2. Attacker submits a reply with malicious payloads
        xss_payload = '<script>window.__INJECTED_SCRIPT_RUN = true;</script><img src="x" onerror="window.__INJECTED_IMG_RUN = true;">这是一条带有测试代码的回复内容'
        reply_res = publish_forum_reply_post(
            db,
            attacker_user,
            topic_id=topic_id,
            text=xss_payload,
            direct=True,
        )

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.db = db
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        print(f"Server running on {BASE_URL}")

        CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(CHROME_PATH):
            CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

        with sync_playwright() as p:
            browser_kwargs = {"headless": True}
            if os.path.exists(CHROME_PATH):
                browser_kwargs["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**browser_kwargs)

            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_cookies([
                {
                    "name": SESSION_COOKIE_NAME,
                    "value": author_token,
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ])

            page = context.new_page()

            # Navigate to topic detail page
            target_url = f"{BASE_URL}/t/{topic_id}"
            print(f"Navigating to {target_url}...")
            page.goto(target_url, wait_until="networkidle")
            page.wait_for_selector("#topic-replies-list", timeout=10000)

            # Wait to ensure no delayed onerror or script execution occurs
            page.wait_for_timeout(1000)

            # Check if any malicious script ran
            script_ran = page.evaluate("() => Boolean(window.__INJECTED_SCRIPT_RUN)")
            img_ran = page.evaluate("() => Boolean(window.__INJECTED_IMG_RUN)")
            print(f"Script executed: {script_ran}, Image onerror executed: {img_ran}")
            assert not script_ran, "SECURITY FAILURE: Malicious <script> executed in browser context!"
            assert not img_ran, "SECURITY FAILURE: Malicious <img onerror> executed in browser context!"

            # Verify replies contain sanitized plain text
            replies_text = page.locator("#topic-replies-list").inner_text()
            print(f"Replies list rendered text:\n{replies_text}")
            assert "这是一条带有测试代码的回复内容" in replies_text, "Expected reply content to be visible"

            # Check that no actual unescaped <script> tag is present inside the reply body DOM
            raw_html_eval = page.evaluate("""() => {
                const list = document.querySelector('#topic-replies-list');
                const scripts = list.querySelectorAll('script');
                const errImgs = list.querySelectorAll('img[onerror]');
                return { scriptCount: scripts.length, errImgCount: errImgs.length };
            }""")
            print(f"DOM inspection inside reply container: {raw_html_eval}")
            assert raw_html_eval["scriptCount"] == 0, "Found raw <script> element inside DOM!"
            assert raw_html_eval["errImgCount"] == 0, "Found raw <img onerror> element inside DOM!"

            # Take screenshot
            page.screenshot(path=str(SCREENSHOT_PATH))
            print(f"Saved screenshot to {SCREENSHOT_PATH}")

            print("\n=======================================================")
            print("INJECTION GUARD PLAYWRIGHT VERIFICATION PASSED! 🛡️")
            print("=======================================================")
            browser.close()

    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        try:
            db.get_conn().close()
            db.close()
        except Exception:
            pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_browser_verification()
