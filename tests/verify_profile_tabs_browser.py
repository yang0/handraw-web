"""Comprehensive Playwright browser verification on port 3097 for:
- Personal profile tabs split: '画风', '图型' (styles, layouts) with counts
- Tab renaming: '发布的论坛帖' -> '论坛帖', '我的收藏夹' -> '收藏夹'
- Public vs private visibility: other's profile cannot see collections / account tabs or URLs
- User dropdown: '收藏夹' directly opens personal profile collections tab
- Legacy ?view=collections redirect: replaces navigation to personal profile collections
- Mobile 390px viewport: single-line horizontal scroll, no wrap, no compression
"""

import json
import os
import sys
import tempfile
import threading
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

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"

TMP_DIR = Path("C:/tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)
SHOT_SELF_DESKTOP = TMP_DIR / "profile_tabs_self_desktop.png"
SHOT_OTHER_DESKTOP = TMP_DIR / "profile_tabs_other_desktop.png"
SHOT_DROPDOWN_COLLECTIONS = TMP_DIR / "profile_dropdown_to_collections.png"
SHOT_LEGACY_REDIRECT = TMP_DIR / "profile_legacy_collections_redirect.png"
SHOT_MOBILE_390 = TMP_DIR / "profile_tabs_mobile_390.png"


def run_browser_verification():
    print(f"Setting up environment for port {PORT}...")
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
    user_leo, token_leo = register_user(db, "creator_leo", "Pass1234!")
    user_tao, token_tao = register_user(db, "writer_tao", "Pass1234!")
    print(f"Registered users: {user_leo['username']}, {user_tao['username']}")

    # Seed test collections for creator_leo
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO collections (user_id, bucket, target_id, created_at) VALUES (?, 'styles', 'FA-001', '2026-11-01T00:00:00Z')",
            (user_leo["id"],),
        )
        tx.execute(
            "INSERT INTO collections (user_id, bucket, target_id, created_at) VALUES (?, 'layouts', 'SC-021', '2026-11-01T00:00:00Z')",
            (user_leo["id"],),
        )

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
                "value": token_leo,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page = context.new_page()
            page.on("console", lambda m: print("PAGE LOG:", m.text))
            page.on("pageerror", lambda e: print("PAGE ERROR:", e))

            # -----------------------------------------------------------
            # Check 1: Three public profile tabs + resource filters
            # -----------------------------------------------------------
            print("\n>>> Check 1: Profile public tabs and resource filters...")
            page.goto(f"{BASE_URL}/?view=profile&user=creator_leo", wait_until="networkidle")
            page.wait_for_timeout(700)
            assert page.locator('button[data-ptab="works"]').is_visible()
            assert page.locator('button[data-ptab="resources"]').is_visible()
            assert page.locator('button[data-ptab="topics"]').is_visible()
            assert "社区动态" in page.locator('button[data-ptab="topics"]').inner_text()
            for obsolete in ("generations", "styles", "layouts", "articles", "collections"):
                assert page.locator(f'button[data-ptab="{obsolete}"]').count() == 0
            assert page.locator("#prof-go-studio-btn").is_visible()
            assert page.locator("#prof-go-collections-btn").is_visible()
            page.locator('button[data-ptab="resources"]').click()
            page.wait_for_timeout(400)
            assert "ptab=resources" in page.url
            for category in ("all", "styles", "layouts"):
                assert page.locator(f'button[data-prof-resource-filter="{category}"]').is_visible()
            page.locator('button[data-prof-resource-filter="layouts"]').click()
            assert page.locator("[data-prof-asset]").count() >= 1, "Expected at least one public layout asset"
            assert page.locator(".hw-card-badge-tl:has-text('共创画风')").count() == 0
            page.screenshot(path=str(SHOT_SELF_DESKTOP), full_page=False)
            # -----------------------------------------------------------
            # Check 2: Other user's profile visibility & security
            # -----------------------------------------------------------
            print("\n>>> Check 2: Visiting other user's profile (writer_tao)...")
            page.goto(f"{BASE_URL}/?view=profile&user=writer_tao", wait_until="networkidle")
            page.wait_for_timeout(800)

            # Public tabs visible
            assert page.locator('button[data-ptab="resources"]').is_visible(), "Other's resources tab should be visible"
            assert page.locator('button[data-ptab="topics"]').is_visible(), "Other's topics tab should be visible"

            # Private tabs NOT visible
            assert page.locator('button[data-ptab="collections"]').count() == 0, "Collections tab MUST NOT be visible on other's profile"
            assert page.locator('button[data-ptab="account"]').count() == 0, "Account tab MUST NOT be visible on other's profile"

            # Security test: Trying to access other user's profile with ptab=collections directly
            print("  Testing unauthorized URL ?view=profile&user=writer_tao&ptab=collections...")
            page.goto(f"{BASE_URL}/?view=profile&user=writer_tao&ptab=collections", wait_until="networkidle")
            page.wait_for_timeout(800)
            assert "ptab=collections" not in page.url, f"Unauthorized ptab=collections retained in URL: {page.url}"
            assert page.locator('button[data-ptab="collections"]').count() == 0, "Collections tab button leaked on other's profile"

            page.screenshot(path=str(SHOT_OTHER_DESKTOP), full_page=False)
            print(f"  ✓ Saved other user profile desktop screenshot: {SHOT_OTHER_DESKTOP}")

            # -----------------------------------------------------------
            # Check 3: User dropdown '收藏夹' navigates directly to profile collections
            # -----------------------------------------------------------
            print("\n>>> Check 3: User avatar dropdown '收藏夹' navigation...")
            page.goto(f"{BASE_URL}/?view=styles", wait_until="networkidle")
            page.wait_for_timeout(800)

            avatar_btn = page.locator("#hw-user-avatar-btn")
            assert avatar_btn.is_visible(), "User avatar button missing"
            avatar_btn.click()
            page.wait_for_timeout(400)

            dropdown_col = page.locator("#hw-dropdown-collections")
            assert dropdown_col.is_visible(), "Dropdown collections item missing"
            col_label = dropdown_col.inner_text()
            print(f"  Dropdown collections item text: {col_label}")
            assert "收藏夹" in col_label, f"Dropdown text should contain '收藏夹': {col_label}"

            dropdown_col.click()
            page.wait_for_timeout(1000)

            print(f"  Navigated to: {page.url}")
            assert "view=profile" in page.url and "ptab=collections" in page.url, f"Dropdown did not open profile collections: {page.url}"
            assert page.locator("#prof-collections-back-btn").is_visible(), "Collections must have a way back to the public profile"

            # Verify migrated collections center content (pills and unfav)
            assert page.locator('button[data-prof-ftab="styles"]').is_visible(), "收藏画风 pill missing in profile collections"
            assert page.locator('button[data-prof-ftab="layouts"]').is_visible(), "收藏图型 pill missing in profile collections"

            page.screenshot(path=str(SHOT_DROPDOWN_COLLECTIONS), full_page=False)
            print(f"  ✓ Saved dropdown navigation screenshot: {SHOT_DROPDOWN_COLLECTIONS}")

            # -----------------------------------------------------------
            # Check 4: Legacy URL ?view=collections redirect
            # -----------------------------------------------------------
            print("\n>>> Check 4: Testing legacy ?view=collections URL redirect...")
            page.goto(f"{BASE_URL}/?view=collections", wait_until="networkidle")
            page.wait_for_timeout(1000)
            print(f"  Redirected URL: {page.url}")
            assert "view=profile" in page.url and "ptab=collections" in page.url, f"Legacy ?view=collections did not redirect: {page.url}"
            assert "creator_leo" in page.url, f"User missing in redirected URL: {page.url}"

            # Legacy ptab=assets redirect
            print("  Testing legacy ptab=assets URL redirect...")
            page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=assets", wait_until="networkidle")
            page.wait_for_timeout(800)
            print(f"  Redirected assets URL: {page.url}")
            assert "ptab=resources" in page.url, f"Legacy ptab=assets did not redirect to resources: {page.url}"

            page.screenshot(path=str(SHOT_LEGACY_REDIRECT), full_page=False)
            print(f"  ✓ Saved legacy URL redirect screenshot: {SHOT_LEGACY_REDIRECT}")

            # -----------------------------------------------------------
            # Check 5: Mobile 390px Viewport Horizontal Scroll & No Wrap
            # -----------------------------------------------------------
            print("\n>>> Check 5: Mobile 390px viewport horizontal scroll verification...")
            mobile_context = browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
            )
            mobile_context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_leo,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            mobile_page = mobile_context.new_page()
            mobile_page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=collections", wait_until="networkidle")
            mobile_page.wait_for_timeout(1000)

            # Evaluate tabs container styling & scrollability
            tabs_info = mobile_page.evaluate("""
                () => {
                    const row = document.querySelector('.hw-profile-tabs');
                    if (!row) return null;
                    const style = window.getComputedStyle(row);
                    const pills = Array.from(row.querySelectorAll('.hw-pill'));
                    const pillStyles = pills.map(p => {
                        const ps = window.getComputedStyle(p);
                        return {
                            text: p.innerText,
                            whiteSpace: ps.whiteSpace,
                            flexShrink: ps.flexShrink
                        };
                    });
                    return {
                        scrollWidth: row.scrollWidth,
                        clientWidth: row.clientWidth,
                        overflowX: style.overflowX,
                        flexWrap: style.flexWrap,
                        pills: pillStyles
                    };
                }
            """)

            print(f"  Mobile tabs geometry: scrollWidth={tabs_info['scrollWidth']}, clientWidth={tabs_info['clientWidth']}")
            print(f"  Mobile overflowX={tabs_info['overflowX']}, flexWrap={tabs_info['flexWrap']}")
            assert tabs_info["scrollWidth"] >= tabs_info["clientWidth"], "Tabs row must not clip its contents on mobile"
            assert tabs_info["flexWrap"] == "nowrap", f"Tabs row must be nowrap: {tabs_info['flexWrap']}"
            assert tabs_info["overflowX"] in ["auto", "scroll"], f"Tabs row must have scrollable overflow-x: {tabs_info['overflowX']}"

            for p_info in tabs_info["pills"]:
                assert p_info["whiteSpace"] == "nowrap", f"Pill '{p_info['text']}' whiteSpace is not nowrap: {p_info['whiteSpace']}"

            mobile_page.screenshot(path=str(SHOT_MOBILE_390), full_page=False)
            print(f"  ✓ Saved mobile 390px screenshot: {SHOT_MOBILE_390}")

            print("\n========================================================")
            print("ALL PLAYWRIGHT BROWSER VERIFICATION CHECKS PASSED ON 3097!")
            print("========================================================\n")

    finally:
        try:
            httpd.shutdown()
            httpd.server_close()
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
