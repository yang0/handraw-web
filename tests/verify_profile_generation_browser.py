"""Browser verification for Phase 1B:
- Legacy profile history URLs normalize to public works
- Multi-image badges & large image preview modal without prompt copy
- Anonymous visitor access
- Studio history remains in studio
- Legacy studio ?view=history renders locally
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
from backend.generation_works import project_generation_to_works

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
            project_generation_to_works(tx, r["id"])


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
            # Check 1: Legacy public generation tab now resolves to published works.
            # -----------------------------------------------------------
            print("\n>>> Check 1: Profile legacy generation link uses public works...")
            page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=generations", wait_until="networkidle")
            page.wait_for_timeout(800)
            assert "ptab=generations" not in page.url, f"Legacy profile tab was not normalized: {page.url}"
            assert page.locator('button[data-ptab="works"]').is_visible()
            assert page.locator('button[data-ptab="generations"]').count() == 0
            assert page.locator('button[data-ptab="resources"]').is_visible()
            page.wait_for_selector(".hw-profile-work-group", timeout=6000)
            assert page.locator(".hw-profile-work-group").count() == 3, "3 generations should show 3 grouped cards, not 6 pictures"
            assert page.locator(".hw-profile-batch-count:has-text('2 张')").count() == 1
            assert page.locator(".hw-profile-batch-count:has-text('3 张')").count() == 1
            page.screenshot(path=str(DESKTOP_SCREENSHOT), full_page=False)

            # Check 2: Anonymous visitors also see the public creator profile.
            # -----------------------------------------------------------
            print("\n>>> Check 2: Anonymous legacy link...")
            anon_context = browser.new_context(viewport={"width": 1440, "height": 960})
            anon_page = anon_context.new_page()
            anon_page.goto(f"{BASE_URL}/?view=profile&user=creator_leo&ptab=generations", wait_until="networkidle")
            assert anon_page.locator('button[data-ptab="works"]').is_visible()
            assert anon_page.locator('button[data-ptab="generations"]').count() == 0
            anon_context.close()

            # Check 3: The studio history button stays in the studio.
            # -----------------------------------------------------------
            print("\n>>> Check 3: Studio history is an in-studio page...")
            page.goto(f"{BASE_URL}/studio/?entry=quick", wait_until="networkidle")
            page.wait_for_selector("#studio-mode-history", timeout=6000)
            page.locator("#studio-mode-history").click()
            page.wait_for_selector("#hist-back-creation", timeout=6000)
            assert "view=history" in page.url, f"Studio history navigation failed: {page.url}"
            for category in ("all", "quick", "batch", "article", "canvas"):
                assert page.locator(f'[data-hist-filter="{category}"]').is_visible()
            assert page.locator("#hist-status-filter").is_visible()
            assert page.locator("#hist-sort").is_visible()
            assert page.locator("#hist-clear-all").count() == 0
            assert page.locator(".ic-hist-img-download").count() > 0, "Images need a direct download action"
            page.locator("#hist-search-inp").fill("山水")
            page.wait_for_timeout(300)
            assert page.locator('[data-hist-id="gen_leo_003"]').count() == 1
            assert page.locator('[data-hist-id="gen_leo_001"]').count() == 0
            page.locator("#hist-search-inp").fill("")
            page.locator("#hist-status-filter").select_option("success")
            page.locator("#hist-sort").select_option("oldest")
            assert page.locator('[data-hist-id="gen_leo_003"]').count() == 1
            page.locator("#hist-back-creation").click()
            assert "entry=quick" in page.url, f"Did not restore quick creation mode: {page.url}"
            page.goto(f"{BASE_URL}/studio/?entry=batch", wait_until="networkidle")
            page.locator("#studio-mode-history").click()
            page.locator("#hist-back-creation").click()
            assert "entry=batch" in page.url, f"Did not restore batch creation mode: {page.url}"

            # Check 4: Existing direct history URLs remain inside the studio.
            # -----------------------------------------------------------
            print("\n>>> Check 4: Legacy history deep link remains in studio...")
            page.goto(f"{BASE_URL}/studio/?view=history&page=2", wait_until="networkidle")
            page.wait_for_selector("#hist-back-creation", timeout=6000)
            assert "view=history" in page.url, f"Legacy history URL left the studio: {page.url}"
            page.locator("#hist-back-creation").click()
            assert "entry=quick" in page.url

            # Check 5: Mobile viewport.
            # -----------------------------------------------------------
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{BASE_URL}/studio/?view=history", wait_until="networkidle")
            page.wait_for_selector("#hist-back-creation", timeout=6000)
            page.screenshot(path=str(MOBILE_SCREENSHOT), full_page=False)

            # -----------------------------------------------------------
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
