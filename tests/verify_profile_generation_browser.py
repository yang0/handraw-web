"""Browser verification for Phase 1B:
- User profile '生图历史' tab in reverse-chronological order
- Multi-image badges & large image preview modal without prompt copy
- Anonymous visitor access
- Studio '生图历史' button redirect to own profile
- Legacy studio ?view=history redirect
- 全站「实测作品」->「晒作品」
- Desktop (1440x960) and Mobile (390x844) screenshots to C:/tmp/
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
DESKTOP_SCREENSHOT = Path("C:/tmp/profile_history_desktop.png")
MOBILE_SCREENSHOT = Path("C:/tmp/profile_history_mobile.png")
DESKTOP_SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)


def seed_test_generations(db, user_id: int, username: str):
    records = [
        {
            "id": "gen_leo_003",
            "subject": "山水水墨意境·远山红日",
            "created_at": "2026-11-02T08:30:00Z",
            "items": ["https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=800", "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?w=800"],
            "recipe_summary": "#FA-001 / #SC-021",
            "mode": "preset",
            "tab_title": "3:4",
        },
        {
            "id": "gen_leo_002",
            "subject": "复古海报·秋分丰收节",
            "created_at": "2026-11-01T14:20:00Z",
            "items": ["https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=800"],
            "recipe_summary": "#FB-002",
            "mode": "preset",
            "tab_title": "1:1",
        },
        {
            "id": "gen_leo_001",
            "subject": "城市夜景与霓虹微光",
            "created_at": "2026-10-31T20:10:00Z",
            "items": ["https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=800", "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=800", "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800"],
            "recipe_summary": "#FC-003 / #IG-002",
            "mode": "preset",
            "tab_title": "16:9",
        },
    ]

    with db.transaction() as tx:
        for r in records:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, tab_title, mode, mode_label, recipe_summary,
                    status, visibility, engine, created_at, deleted_at,
                    items_json, prompt, prompt_ready
                ) VALUES (?, ?, ?, ?, ?, ?, '预设', ?, 'success', 'public', 'recraft', ?, '', ?, 'Secret prompt text', 1)
                """,
                (
                    r["id"],
                    user_id,
                    username,
                    r["subject"],
                    r["tab_title"],
                    r["mode"],
                    r["recipe_summary"],
                    r["created_at"],
                    json.dumps([{"imageUrl": u} for u in r["items"]]),
                ),
            )


def run_browser_verification():
    print(f"Setting up environment for port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_p1b_verify.db"
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

    seed_test_generations(db, user["id"], user["username"])
    print("Seeded test generations into database.")

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
            page.on("console", lambda m: print("PAGE LOG:", m.text))
            page.on("pageerror", lambda e: print("PAGE ERROR:", e))

            # -----------------------------------------------------------
            # Check 1: Personal Profile Generation History Tab
            # -----------------------------------------------------------
            print("\n>>> Check 1: Visiting personal profile with ptab=generations...")
            page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=generations", wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Check that tab button exists and is active
            gen_tab_btn = page.locator('button[data-ptab="generations"]')
            assert gen_tab_btn.is_visible(), "Generation history tab button missing in profile"
            assert "is-active" in (gen_tab_btn.get_attribute("class") or ""), "Generation tab button not active"
            print("  ✓ '生图历史' tab button exists and is active")

            # Check that works tab is renamed to 晒作品
            works_tab_btn = page.locator('button[data-ptab="works"]')
            works_text = works_tab_btn.inner_text()
            assert "晒作品" in works_text, f"Works tab button does not contain '晒作品': {works_text}"
            assert "实测作品" not in works_text, f"Works tab button still contains '实测作品': {works_text}"
            print("  ✓ Profile tab correctly renamed from '实测作品' to '晒作品'")

            # Wait for generation cards to render
            page.wait_for_selector("[data-prof-gen]", timeout=6000)
            cards = page.locator("[data-prof-gen]")
            card_count = cards.count()
            print(f"  ✓ Found {card_count} generation cards rendered in profile masonry")
            assert card_count == 3, f"Expected 3 cards, got {card_count}"

            # Check reverse-chronological order: first card should be gen_leo_003
            first_card_id = cards.first.get_attribute("data-prof-gen")
            assert first_card_id == "gen_leo_003", f"Expected first card to be gen_leo_003, got {first_card_id}"
            print("  ✓ Generation history is sorted in reverse-chronological order")

            # Check multi-image badge on first card (which has 2 images)
            first_badge = cards.first.locator(".hw-card-badge-tl")
            assert "2 张" in first_badge.inner_text(), "Multi-image badge '2 张' missing on card"
            print("  ✓ Multi-image badge correctly displays '2 张'")

            # Desktop Screenshot
            page.screenshot(path=str(DESKTOP_SCREENSHOT), full_page=False)
            print(f"  ✓ Saved desktop screenshot: {DESKTOP_SCREENSHOT}")

            # -----------------------------------------------------------
            # Check 2: Modal Preview without Prompt Copy
            # -----------------------------------------------------------
            print("\n>>> Check 2: Clicking generation card to open detail modal...")
            cards.first.click()
            page.wait_for_selector(".hw-gen-detail-modal", timeout=4000)
            modal = page.locator(".hw-gen-detail-modal")
            assert modal.is_visible(), "Generation detail modal did not open"

            modal_text = modal.inner_text()
            assert "山水水墨意境·远山红日" in modal_text, "Topic missing in modal"
            assert "@creator_leo" in modal_text, "Author missing in modal"
            assert "2 张" in modal_text, "Image count missing in modal"

            # Strict security assertion: Prompt or Secret must NOT exist in modal
            assert "Secret prompt text" not in modal_text, "Secret prompt leaked into modal!"
            assert page.locator(".hw-modal-panel button:has-text('复制提示词')").count() == 0, "Found copy prompt button in modal!"
            assert page.locator(".hw-modal-panel button:has-text('复制')").count() == 0, "Found generic copy button in modal!"
            print("  ✓ Modal displays high-res images and safe metadata; prompt copy is strictly omitted")

            # Close modal
            close_btn = page.locator("#hw-modal-close-x, .hw-modal-close")
            if close_btn.count():
                close_btn.first.click()
                page.wait_for_timeout(300)

            # -----------------------------------------------------------
            # Check 3: Anonymous Visitor Access
            # -----------------------------------------------------------
            print("\n>>> Check 3: Anonymous visitor viewing public generation history...")
            anon_context = browser.new_context(viewport={"width": 1440, "height": 960})
            anon_page = anon_context.new_page()
            anon_page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=generations", wait_until="networkidle")
            anon_page.wait_for_selector("[data-prof-gen]", timeout=6000)
            anon_cards = anon_page.locator("[data-prof-gen]")
            assert anon_cards.count() == 3, f"Anonymous saw {anon_cards.count()} cards, expected 3"
            print("  ✓ Anonymous visitor can view public generation history without logging in")
            anon_context.close()

            # -----------------------------------------------------------
            # Check 4: Studio '生图历史' Button Navigation
            # -----------------------------------------------------------
            print("\n>>> Check 4: Studio '生图历史' button redirects to personal profile...")
            page.goto(f"{BASE_URL}/studio/", wait_until="networkidle")
            page.wait_for_selector("#studio-mode-history", timeout=6000)
            eval_info = page.evaluate("() => ({ loggedIn: window.HANDRAW_SHARED?.App?.state?.loggedIn, user: window.HANDRAW_SHARED?.App?.state?.user, hasHandler: !!document.querySelector('#studio-mode-history')?.onclick })")
            print("  Studio state before click:", eval_info)
            studio_hist_btn = page.locator("#studio-mode-history")
            assert studio_hist_btn.is_visible(), "Studio mode history button missing"
            studio_hist_btn.click()
            page.wait_for_timeout(1000)

            current_url = page.url
            assert "view=profile" in current_url, f"Did not redirect to profile: {current_url}"
            assert "ptab=generations" in current_url, f"Did not include ptab=generations: {current_url}"
            assert "user=creator_leo" in current_url, f"Did not include user=creator_leo: {current_url}"
            print(f"  ✓ Studio '生图历史' button successfully navigated to: {current_url}")

            # -----------------------------------------------------------
            # Check 5: Studio Legacy ?view=history&page=2 Replacement Redirect
            # -----------------------------------------------------------
            print("\n>>> Check 5: Legacy studio ?view=history&page=2 replacement redirect...")
            page.goto(f"{BASE_URL}/studio/?view=history&page=2", wait_until="networkidle")
            page.wait_for_timeout(1000)

            redirected_url = page.url
            assert "view=profile" in redirected_url, f"Legacy URL did not redirect to profile: {redirected_url}"
            assert "ptab=generations" in redirected_url, f"Legacy URL missing ptab=generations: {redirected_url}"
            assert "page=" not in redirected_url, f"Legacy URL inherited old page parameter: {redirected_url}"
            print(f"  ✓ Legacy history URL replaced to profile generations tab without inheriting page: {redirected_url}")

            # -----------------------------------------------------------
            # Check 6: Mobile Viewport Screenshot (390x844)
            # -----------------------------------------------------------
            print("\n>>> Check 6: Capturing mobile viewport screenshot...")
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=generations", wait_until="networkidle")
            page.wait_for_selector("[data-prof-gen]", timeout=6000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(MOBILE_SCREENSHOT), full_page=False)
            print(f"  ✓ Saved mobile screenshot: {MOBILE_SCREENSHOT}")

            browser.close()
            print("\n>>> ALL BROWSER CHECKS PASSED SUCCESSFULLY!")

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
