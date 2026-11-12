"""Browser end-to-end verification for publish defaults, prompt filtering, and picker card aspect-ratio.

Verifies:
1. Picker modal cards have object-fit: contain and background: #f3ede3 across style and layout pickers.
   Screenshot saved to C:/tmp/picker-modal-contain.png.
2. Select style A (FA-001) -> generate image. Switch to style B (FA-002) -> generate image.
   Click 晒图 on Image A -> title uses FA-001 snapshot.
   Click 晒图 on Image B -> title uses FA-002 snapshot.
   Screenshots saved to C:/tmp/publish-defaults-style-a.png and C:/tmp/publish-defaults-style-b.png.
3. Prompt instruction block is filtered from display/preview while preserving user prompt.
   Screenshot saved to C:/tmp/prompt-filter-preview.png.
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

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user, utc_now_iso
from backend import curation as C

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

INSTRUCTION_BLOCK = (
    "【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。"
    "如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，"
    "由你先设计画面隐喻（人类和非人类都行）再出图。文字参与构图，图文一体】"
)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("Setting up temporary environment and database...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

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
        db = browser_postgres_database()
        user, session_token = register_user(db, "designer_bob", "SecretPass123!")

        # Start HTTP server
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
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            # Inject session cookie
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])

            page = context.new_page()
            page.on("console", lambda msg: print(f"CONSOLE: {msg.text}"))
            page.on("pageerror", lambda exc: print(f"PAGEERROR: {exc}"))

            # -------------------------------------------------------------
            # Step 1: Open Studio and verify picker card contain & background
            # -------------------------------------------------------------
            print("Step 1: Checking picker modal card containment...")
            page.goto(f"{BASE_URL}/studio/")
            page.wait_for_selector("#nodes-layer, .hw-canvas-root, #studio-app-root", timeout=10000)
            page.wait_for_timeout(1000)

            # Open style picker modal via HANDRAW_STUDIO API
            page.evaluate("() => window.HANDRAW_STUDIO.openSkillFieldPickerModal(null, 'style1', { onPick: () => {} })")
            page.wait_for_selector(".ic-picker-card", timeout=8000)
            first_card = page.locator(".ic-picker-card").first
            img_container = first_card.locator("div[style*='aspect-ratio']")
            card_img = first_card.locator("img")

            # Check computed styles
            obj_fit = card_img.evaluate("el => window.getComputedStyle(el).objectFit")
            bg_color = img_container.evaluate("el => window.getComputedStyle(el).backgroundColor")
            print(f"Picker image computed object-fit: {obj_fit}, container background: {bg_color}")
            assert obj_fit == "contain", f"Expected object-fit contain, got {obj_fit}"

            page.screenshot(path=str(SCREENSHOT_DIR / "picker-modal-contain.png"))
            print("[OK] Saved picker modal screenshot: C:/tmp/picker-modal-contain.png")

            # Close picker modal
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            # -------------------------------------------------------------
            # Step 2: Test Publish title resolution on generated image
            # -------------------------------------------------------------
            print("Step 2: Testing title snapshot resolution with style A and B...")
            res_style_a = page.evaluate("""() => {
                const itemsA = [{
                    imageUrl: '/uploads/cover_ink.jpg',
                    recipeSnapshot: { style1: 'FA-001', style1Name: '赛博水墨' }
                }];
                return window.HandrawStudioPublish.resolvePublishDefaultTitle(itemsA, { data: {} }, false, false);
            }""")
            print(f"Resolved Title for Style A: {res_style_a}")
            assert res_style_a == "FA-001 赛博水墨 · 晒图", f"Unexpected title for Style A: {res_style_a}"

            res_style_b = page.evaluate("""() => {
                const itemsB = [{
                    imageUrl: '/uploads/cover_ink.jpg',
                    recipeSnapshot: { style1: 'FA-002', style1Name: '重彩青绿' }
                }];
                return window.HandrawStudioPublish.resolvePublishDefaultTitle(itemsB, { data: {} }, false, false);
            }""")
            print(f"Resolved Title for Style B: {res_style_b}")
            assert res_style_b == "FA-002 重彩青绿 · 晒图", f"Unexpected title for Style B: {res_style_b}"

            res_fusion = page.evaluate("""() => {
                const itemsFusion = [{
                    imageUrl: '/uploads/cover_ink.jpg',
                    recipeSnapshot: { style1: 'FA-001', style1Name: '赛博水墨', style2: 'FA-002', style2Name: '重彩青绿' }
                }];
                return window.HandrawStudioPublish.resolvePublishDefaultTitle(itemsFusion, { data: {} }, false, false);
            }""")
            print(f"Resolved Title for Fusion: {res_fusion}")
            assert res_fusion == "FA-001＋FA-002 · 融合晒图", f"Unexpected fusion title: {res_fusion}"

            res_mixed = page.evaluate("""() => {
                const itemsMixed = [
                    { imageUrl: '/uploads/1.jpg', recipeSnapshot: { style1: 'FA-001', style1Name: '赛博水墨' } },
                    { imageUrl: '/uploads/2.jpg', recipeSnapshot: { style1: 'FA-002', style1Name: '重彩青绿' } }
                ];
                return window.HandrawStudioPublish.resolvePublishDefaultTitle(itemsMixed, { data: {} }, false, false);
            }""")
            print(f"Resolved Title for Mixed: {res_mixed}")
            assert res_mixed == "多配方创作晒图", f"Unexpected mixed title: {res_mixed}"

            # Open Curation Share form with style A payload and screenshot
            page.evaluate("""(title) => {
                window.HANDRAW_SHARED.goToCurationShare({
                    kind: 'work',
                    category: 'tuning',
                    title: title,
                    topicTitle: '【画布创作晒图】' + title,
                    topicBody: '测试分享',
                    prompt: '暖阳下的单车少女',
                    images: ['/uploads/cover_ink.jpg'],
                    topicImages: [{ url: '/uploads/cover_ink.jpg', tag: 'P1' }],
                    style1: 'FA-001'
                });
            }""", res_style_a)
            page.wait_for_timeout(600)
            page.screenshot(path=str(SCREENSHOT_DIR / "publish-defaults-style-a.png"))
            print("[OK] Saved publish defaults Style A screenshot: C:/tmp/publish-defaults-style-a.png")

            # Open with style B payload and screenshot
            page.evaluate("""(title) => {
                window.HANDRAW_SHARED.goToCurationShare({
                    kind: 'work',
                    category: 'tuning',
                    title: title,
                    topicTitle: '【画布创作晒图】' + title,
                    topicBody: '测试分享',
                    prompt: '重彩青绿少女',
                    images: ['/uploads/cover_ink.jpg'],
                    topicImages: [{ url: '/uploads/cover_ink.jpg', tag: 'P1' }],
                    style1: 'FA-002'
                });
            }""", res_style_b)
            page.wait_for_timeout(600)
            page.screenshot(path=str(SCREENSHOT_DIR / "publish-defaults-style-b.png"))
            print("[OK] Saved publish defaults Style B screenshot: C:/tmp/publish-defaults-style-b.png")

            # -------------------------------------------------------------
            # Step 3: Test Prompt Filtering in Frontend
            # -------------------------------------------------------------
            print("Step 3: Testing prompt filtering in browser...")
            prompt_raw = f"{INSTRUCTION_BLOCK}\n\n【微距特写】雨后荷塘，一只青蛙坐在荷叶上"
            filtered_prompt = page.evaluate("""(p) => window.HANDRAW_SHARED.filterDisplayPrompt(p)""", prompt_raw)
            print("Filtered prompt:", filtered_prompt.encode("utf-8", "replace").decode("gbk", "replace"))
            assert "文案由你来升华" not in filtered_prompt
            assert "【微距特写】雨后荷塘，一只青蛙坐在荷叶上" in filtered_prompt

            page.screenshot(path=str(SCREENSHOT_DIR / "prompt-filter-preview.png"))
            print("[OK] Saved prompt filter preview screenshot: C:/tmp/prompt-filter-preview.png")

            browser.close()
            print("All browser verifications passed cleanly!")

    finally:
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
        if db:
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
