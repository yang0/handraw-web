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

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
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
    db_path = root / "browser_profile_tabs_verify.db"
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
            # Check 1: Personal Profile Tabs Split & Renaming
            # -----------------------------------------------------------
            print("\n>>> Check 1: Personal profile tabs split & renaming...")
            page.goto(f"{BASE_URL}/?view=profile&user=creator_leo", wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Check styles and layouts tabs exist
            styles_btn = page.locator('button[data-ptab="styles"]')
            layouts_btn = page.locator('button[data-ptab="layouts"]')
            topics_btn = page.locator('button[data-ptab="topics"]')
            cols_btn = page.locator('button[data-ptab="collections"]')
            acc_btn = page.locator('button[data-ptab="account"]')
            assets_btn = page.locator('button[data-ptab="assets"]')

            assert styles_btn.is_visible(), "Styles tab button missing"
            assert layouts_btn.is_visible(), "Layouts tab button missing"
            assert assets_btn.count() == 0, "Old merged assets tab must not exist"

            styles_text = styles_btn.inner_text()
            layouts_text = layouts_btn.inner_text()
            topics_text = topics_btn.inner_text()
            cols_text = cols_btn.inner_text()

            print(f"  Tabs detected: {styles_text} | {layouts_text} | {topics_text} | {cols_text}")
            assert "画风" in styles_text, f"Styles tab text wrong: {styles_text}"
            assert "图型" in layouts_text, f"Layouts tab text wrong: {layouts_text}"
            assert "论坛帖" in topics_text, f"Topics tab rename wrong: {topics_text}"
            assert "发布的论坛帖" not in topics_text, f"Old topics tab name still present: {topics_text}"
            assert "收藏夹" in cols_text, f"Collections tab rename wrong: {cols_text}"
            assert "我的收藏夹" not in cols_text, f"Old collections tab name still present: {cols_text}"
            assert acc_btn.is_visible(), "Account settings tab must be visible to owner"

            # Click styles tab
            styles_btn.click()
            page.wait_for_timeout(500)
            assert "is-active" in (styles_btn.get_attribute("class") or ""), "Styles tab not active"
            assert "ptab=styles" in page.url, f"URL did not update to ptab=styles: {page.url}"

            # Click layouts tab
            layouts_btn.click()
            page.wait_for_timeout(500)
            assert "is-active" in (layouts_btn.get_attribute("class") or ""), "Layouts tab not active"
            assert "ptab=layouts" in page.url, f"URL did not update to ptab=layouts: {page.url}"

            page.screenshot(path=str(SHOT_SELF_DESKTOP), full_page=False)
            print(f"  ✓ Saved personal profile desktop screenshot: {SHOT_SELF_DESKTOP}")

            # -----------------------------------------------------------
            # Check 2: Other user's profile visibility & security
            # -----------------------------------------------------------
            print("\n>>> Check 2: Visiting other user's profile (writer_tao)...")
            page.goto(f"{BASE_URL}/?view=profile&user=writer_tao", wait_until="networkidle")
            page.wait_for_timeout(800)

            # Public tabs visible
            assert page.locator('button[data-ptab="styles"]').is_visible(), "Other's styles tab should be visible"
            assert page.locator('button[data-ptab="layouts"]').is_visible(), "Other's layouts tab should be visible"
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
            active_pill = page.locator('button[data-ptab="collections"].is-active')
            assert active_pill.is_visible(), "Collections tab is not active after dropdown click"

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
            assert "ptab=styles" in page.url, f"Legacy ptab=assets did not redirect to ptab=styles: {page.url}"

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
            assert tabs_info["scrollWidth"] > tabs_info["clientWidth"], "Tabs row must overflow horizontally on 390px width"
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
