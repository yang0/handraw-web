"""Comprehensive Playwright browser verification on port 3097 for:
1. 填超长主题生成 -> 分享标题为截断主题 (最多 40 可见字符，含末尾 …，硬截断，组合 emoji 完整)
2. 换主题后刷新再分享仍是原主题 (生成时保存的主题优先于 live 状态)
3. 海报不填受众/渠道生成，提示词无那两行占位
4. 导航 1440 与 390 都只剩 GitHub ↗ 和 消息 (使用指南入口已移除)
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

from playwright.sync_api import sync_playwright

from tests.legacy_database import init_legacy_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user
from http.server import ThreadingHTTPServer

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
    db_path = root / "guidance_verify.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    # Set up dummy image-service config
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
    old_env = {}
    for k, v in env_patch.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    db = None
    httpd = None
    try:
        db = init_legacy_database(db_path)
        user, session_token = register_user(db, "guidance_tester", "SecretPass123!")

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.channel_role = "main"  # type: ignore[attr-defined]
        httpd.db = db  # type: ignore[attr-defined]
        httpd.allow_demo_routes = True  # type: ignore[attr-defined]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"Server started at {BASE_URL}")

        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            if os.path.exists(CHROME_PATH):
                launch_kwargs["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**launch_kwargs)

            # =============================================================
            # STEP 1: Navigation checks (1440 and 390 viewports)
            # =============================================================
            print("\n--- STEP 1: Navigation check at 1440x900 & 390x844 ---")
            ctx_1440 = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=BASE_URL)
            ctx_1440.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page_1440 = ctx_1440.new_page()
            page_1440.goto(f"{BASE_URL}/forum/")
            page_1440.wait_for_selector(".hw-topbar", timeout=10000)
            page_1440.wait_for_selector(".hw-account-quicklinks", timeout=5000)

            links_1440 = page_1440.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('.hw-account-quicklinks a'));
                return links.map(a => a.textContent.trim());
            }""")
            print(f"1440 Desktop quicklinks: {links_1440}")
            assert any("GitHub" in t for t in links_1440), f"GitHub link missing in 1440 nav: {links_1440}"
            assert any("消息" in t for t in links_1440), f"消息 link missing in 1440 nav: {links_1440}"
            assert not any("使用指南" in t for t in links_1440), f"使用指南 link MUST be absent: {links_1440}"

            screenshot_1440 = SCREENSHOT_DIR / "nav-desktop-1440.png"
            page_1440.screenshot(path=str(screenshot_1440))
            print(f"[OK] Saved desktop screenshot: {screenshot_1440}")
            ctx_1440.close()

            # Mobile 390 viewport
            ctx_390 = browser.new_context(
                viewport={"width": 390, "height": 844},
                base_url=BASE_URL,
                is_mobile=True,
                has_touch=True,
            )
            ctx_390.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page_390 = ctx_390.new_page()
            page_390.goto(f"{BASE_URL}/forum/")
            page_390.wait_for_selector(".hw-topbar", timeout=10000)
            page_390.wait_for_selector(".hw-account-quicklinks", timeout=5000)

            links_390 = page_390.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('.hw-account-quicklinks a'));
                return links.map(a => a.textContent.trim());
            }""")
            print(f"390 Mobile quicklinks: {links_390}")
            assert any("GitHub" in t for t in links_390), f"GitHub link missing in 390 nav: {links_390}"
            assert any("消息" in t for t in links_390), f"消息 link missing in 390 nav: {links_390}"
            assert not any("使用指南" in t for t in links_390), f"使用指南 link MUST be absent: {links_390}"

            screenshot_390 = SCREENSHOT_DIR / "nav-mobile-390.png"
            page_390.screenshot(path=str(screenshot_390))
            print(f"[OK] Saved mobile screenshot: {screenshot_390}")
            ctx_390.close()

            # =============================================================
            # STEP 2: Super long subject with composite emoji -> Share title is truncated subject (40 chars)
            # =============================================================
            print("\n--- STEP 2: Super long subject generation & truncation ---")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=BASE_URL)
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.new_page()
            page.goto(f"{BASE_URL}/studio/")
            page.wait_for_selector("#make-image-subject", timeout=15000)

            # 50+ characters with fullwidth punctuation, brackets and composite emoji 👨‍👩‍👧
            long_subject = "雨天街角便利店👨‍👩‍👧热气腾腾的关东煮与温暖灯光在暮色中闪烁（测试超长标题硬截断完整组合表情与标点符号）这是一段非常非常长的文字内容"
            page.fill("#make-image-subject", long_subject)
            # Trigger input event to ensure store gets the text
            page.evaluate("""(val) => {
                const el = document.querySelector('#make-image-subject');
                if (el) { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); }
            }""", long_subject)
            time.sleep(0.3)

            # Click Run button
            print("Clicking Generate button...")
            run_btn = page.locator("#make-image-btn-run")
            run_btn.click()

            # Wait for generation result card and publish button
            print("Waiting for generation result...")
            page.wait_for_selector('[data-action="publish"]', timeout=15000)
            time.sleep(0.5)

            # Click "晒" (publish/share) button
            print("Clicking Share/Publish button...")
            page.click('[data-action="publish"]')

            # Wait for curation share page / modal to load
            page.wait_for_selector('[data-act="title"]', timeout=10000)
            time.sleep(0.5)

            share_title = page.input_value('[data-act="title"]')
            print(f"Prefilled Share Title: {share_title}")

            # Verify visible characters count using Intl.Segmenter in browser
            grapheme_len = page.evaluate("""(str) => {
                const seg = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
                return Array.from(seg.segment(str)).length;
            }""", share_title)
            print(f"Grapheme length of share title: {grapheme_len}")
            assert grapheme_len == 40, f"Expected exactly 40 visible characters, got {grapheme_len}"
            assert share_title.endswith("…"), f"Expected title to end with …, got {share_title}"
            assert "👨‍👩‍👧" in share_title, f"Composite emoji 👨‍👩‍👧 must remain intact, got: {share_title}"

            screenshot_share1 = SCREENSHOT_DIR / "share-title-truncated.png"
            page.screenshot(path=str(screenshot_share1))
            print(f"[OK] Saved truncated title screenshot: {screenshot_share1}")

            # =============================================================
            # STEP 3: Change subject, refresh, share again -> Still original generation subject
            # =============================================================
            print("\n--- STEP 3: Change subject, refresh, verify original subject retained ---")
            page.goto(f"{BASE_URL}/studio/")
            page.wait_for_selector("#make-image-subject", timeout=15000)

            # Fill with completely different subject
            new_subject = "赛博朋克霓虹雨夜飞车追逐"
            page.evaluate("""(val) => {
                const el = document.querySelector('#make-image-subject');
                if (el) { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }
            }""", new_subject)
            time.sleep(0.5)

            # Refresh the page
            print("Reloading studio page...")
            page.reload()
            page.wait_for_selector('[data-action="publish"]', timeout=15000)
            time.sleep(0.5)

            # Click "晒" (publish/share) button again on the previously generated item
            print("Clicking Share/Publish on existing item after refresh...")
            page.click('[data-action="publish"]')
            page.wait_for_selector('[data-act="title"]', timeout=10000)
            time.sleep(0.5)

            retained_title = page.input_value('[data-act="title"]')
            print(f"Share Title after changing subject & refresh: {retained_title}")
            assert retained_title == share_title, f"Expected retained generation-time title {share_title}, but got {retained_title}"
            assert new_subject not in retained_title, f"Live subject '{new_subject}' should NOT have overwritten generation-time subject!"

            screenshot_retained = SCREENSHOT_DIR / "share-title-retained-after-refresh.png"
            page.screenshot(path=str(screenshot_retained))
            print(f"[OK] Saved retained subject screenshot: {screenshot_retained}")

            # =============================================================
            # STEP 4: Poster mode without audience/channel -> Prompt has NO placeholders
            # =============================================================
            print("\n--- STEP 4: Poster mode without audience/channel ---")
            page.goto(f"{BASE_URL}/studio/")
            page.wait_for_selector('button[data-set-mode="poster"]', timeout=15000)

            # Switch mode to poster
            page.click('button[data-set-mode="poster"]')
            time.sleep(0.3)

            poster_topic = "秋季新品发布商业海报"
            page.evaluate("""(val) => {
                const el = document.querySelector('#make-image-subject');
                if (el) { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); }
            }""", poster_topic)
            time.sleep(0.3)

            # Generate in poster mode
            page.click("#make-image-btn-run")
            page.wait_for_selector('[data-action="publish"]', timeout=15000)
            time.sleep(0.5)

            # Check prompt from Make-Image preview textarea
            preview_prompt = page.input_value("#make-image-prompt") if page.locator("#make-image-prompt").count() else ""
            print(f"Make-Image Preview Prompt:\n{preview_prompt}")
            if preview_prompt:
                assert "受众：【可指定受众群体】" not in preview_prompt, "Poster preview must NOT contain audience placeholder"
                assert "海报投放渠道：【可指定业务场景】" not in preview_prompt, "Poster preview must NOT contain channel placeholder"
                assert "【可指定" not in preview_prompt, "Poster preview must NOT contain 【可指定"

            # Click publish and verify prompt in share form as well
            page.click('[data-action="publish"]')
            page.wait_for_selector('[data-act="prompt"]', timeout=10000)
            time.sleep(0.5)
            form_prompt = page.input_value('[data-act="prompt"]')
            print(f"Share Form Prompt:\n{form_prompt}")
            assert "【可指定" not in form_prompt, "Share form prompt must not contain 【可指定"
            assert "受众：【可指定受众群体】" not in form_prompt, "Share form prompt must not contain audience placeholder"

            screenshot_poster = SCREENSHOT_DIR / "poster-prompt-clean.png"
            page.screenshot(path=str(screenshot_poster))
            print(f"[OK] Saved clean poster prompt screenshot: {screenshot_poster}")

            context.close()
            browser.close()
            print("\nALL BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")

    finally:
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
        if db:
            try:
                db.close_thread_conn()
                db.get_conn().close()
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
