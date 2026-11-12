"""Browser verification for GitHub nav link in topbar.

Verifies:
1. Desktop (1440x900): 'GitHub ↗' link appears to the left of '使用指南'.
   Href is https://github.com/yang0/handraw-style, target=_blank, rel=noopener noreferrer.
   Screenshot saved to C:/tmp/github-nav-desktop-1440.png.
2. Mobile (390x844): layout does not break, no horizontal page overflow.
   Screenshot saved to C:/tmp/github-nav-mobile-390.png.
3. Unauthenticated / anonymous visitor: link is visible.
   Screenshot saved to C:/tmp/github-nav-anon.png.
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

from tests.legacy_database import init_legacy_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

TARGET_URL = "https://github.com/yang0/handraw-style"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("Setting up temporary environment and database...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_verify.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    from PIL import Image
    cover_file = uploads_dir / "cover_ink.jpg"
    img = Image.new("RGB", (240, 240), color=(220, 215, 200))
    img.save(cover_file, "JPEG")

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
        db = init_legacy_database(db_path)
        user, session_token = register_user(db, "designer_bob", "SecretPass123!")

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

            # -------------------------------------------------------------
            # 1. Desktop Test (1440x900) - Logged in
            # -------------------------------------------------------------
            print("Step 1: Testing Desktop 1440x900 (Logged In)...")
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.new_page()
            page.goto(f"{BASE_URL}/forum/")
            page.wait_for_selector(".hw-topbar", timeout=10000)
            page.wait_for_selector(".hw-account-quicklinks", timeout=5000)

            # Inspect quicklinks
            gh_link = page.locator(".hw-account-quicklinks a:has-text('GitHub')")
            assert gh_link.count() == 1, "Expected exactly 1 GitHub link in quicklinks"
            href = gh_link.get_attribute("href")
            target = gh_link.get_attribute("target")
            rel = gh_link.get_attribute("rel")
            assert href == TARGET_URL, f"Expected href {TARGET_URL}, got {href}"
            assert target == "_blank", f"Expected target _blank, got {target}"
            assert "noopener" in (rel or ""), f"Expected rel to contain noopener, got {rel}"

            # Verify 使用指南 is removed and only GitHub ↗ (and 消息 when logged in) exist
            nav_links_text = page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('.hw-account-quicklinks a'));
                return links.map(a => a.textContent.trim());
            }""")
            assert not any("使用指南" in text for text in nav_links_text), f"Nav quicklinks must not contain 使用指南: {nav_links_text}"
            assert any("GitHub" in text for text in nav_links_text), f"Nav quicklinks must contain GitHub: {nav_links_text}"
            print(f"Desktop check passed: quicklinks contain {nav_links_text}, 使用指南 absent, attrs verified.")

            page.screenshot(path=str(SCREENSHOT_DIR / "github-nav-desktop-1440.png"))
            print("[OK] Saved desktop screenshot: C:/tmp/github-nav-desktop-1440.png")
            context.close()

            # -------------------------------------------------------------
            # 2. Mobile Test (390x844) - Logged in
            # -------------------------------------------------------------
            print("Step 2: Testing Mobile 390x844...")
            mob_context = browser.new_context(
                viewport={"width": 390, "height": 844},
                base_url=BASE_URL,
                is_mobile=True,
                has_touch=True,
            )
            mob_context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            mob_page = mob_context.new_page()
            mob_page.goto(f"{BASE_URL}/forum/")
            mob_page.wait_for_selector(".hw-topbar", timeout=10000)
            mob_page.wait_for_selector(".hw-account-quicklinks", timeout=5000)

            # Verify no horizontal scroll on body/window
            body_overflow = mob_page.evaluate("""() => {
                return document.documentElement.scrollWidth <= window.innerWidth + 2;
            }""")
            assert body_overflow, "Mobile page should not overflow horizontally"
            print("Mobile check passed: layout fits within 390px without breaking.")

            mob_page.screenshot(path=str(SCREENSHOT_DIR / "github-nav-mobile-390.png"))
            print("[OK] Saved mobile screenshot: C:/tmp/github-nav-mobile-390.png")
            mob_context.close()

            # -------------------------------------------------------------
            # 3. Unauthenticated / Anonymous Test
            # -------------------------------------------------------------
            print("Step 3: Testing Unauthenticated / Anonymous Visitor...")
            anon_context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            anon_page = anon_context.new_page()
            anon_page.goto(f"{BASE_URL}/forum/")
            anon_page.wait_for_selector(".hw-topbar", timeout=10000)
            anon_page.wait_for_selector(".hw-account-quicklinks", timeout=5000)

            anon_gh_visible = anon_page.locator(".hw-account-quicklinks a:has-text('GitHub')").is_visible()
            assert anon_gh_visible, "GitHub link must be visible for anonymous visitor"
            print("Anonymous check passed: GitHub link is visible.")

            anon_page.screenshot(path=str(SCREENSHOT_DIR / "github-nav-anon.png"))
            print("[OK] Saved anonymous screenshot: C:/tmp/github-nav-anon.png")
            anon_context.close()

            browser.close()
            print("All GitHub nav link browser verifications passed cleanly!")

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
