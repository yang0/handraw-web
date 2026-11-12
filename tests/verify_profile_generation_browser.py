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

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
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
            "items": ["/images/poster-demo-autumn-equinox.webp", "/images/A_001-016.webp"],
            "recipe_summary": "#FA-001 / #SC-021",
            "mode": "preset",
            "tab_title": "3:4",
        },
        {
            "id": "gen_leo_002",
            "subject": "复古海报·秋分丰收节",
            "created_at": "2026-11-01T14:20:00Z",
            "items": ["/images/graphic-text-mode-demo.webp"],
            "recipe_summary": "#FB-002",
            "mode": "preset",
            "tab_title": "1:1",
        },
        {
            "id": "gen_leo_001",
            "subject": "城市夜景与霓虹微光",
            "created_at": "2026-10-31T20:10:00Z",
            "items": ["/images/layouts/infographics/IG-005.webp", "/images/layouts/social-cards/SC-021.webp", "/images/B_036-048.webp"],
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
            page.wait_for_selector(".ic-hist-masonry-grid", timeout=6000)
            assert "view=history" in page.url, f"Studio history navigation failed: {page.url}"
            for category in ("all", "quick", "batch", "article", "canvas"):
                assert page.locator(f'[data-hist-filter="{category}"]').is_visible()
            assert page.locator("#hist-status-filter").is_visible()
            assert page.locator("#hist-sort").is_visible()
            assert page.locator("#hist-clear-all").count() == 0
            assert page.locator(".ic-hist-cover-download").count() > 0, "Cover images need a direct download action"
            assert page.locator("#hist-back-creation").count() == 0
            assert page.locator(".ic-hist-cover").count() == 3, "One cover per generation task"
            history_bar_box = page.locator(".ic-history-topbar").bounding_box()
            history_body_box = page.locator(".ic-hist-page-inner").bounding_box()
            assert history_bar_box is not None and history_body_box is not None
            # Homepage and history share the same responsive card count at 1440px.
            history_columns = page.locator(".ic-hist-masonry-grid").evaluate(
                "(el) => getComputedStyle(el).gridTemplateColumns.split(/\\s+/).length"
            )
            assert history_columns == 4, (
                f"History at 1440px should be four columns like homepage, got {history_columns}"
            )
            # Compare against the actual top navigation content gutter rather than a guessed fixed width.
            navigation_gutter = page.locator(".hw-topbar").evaluate(
                "(el) => parseFloat(getComputedStyle(el).paddingLeft)"
            )
            assert abs(history_bar_box["x"] - navigation_gutter) <= 2, "History toolbar must align with main navigation"
            assert abs(history_body_box["x"] - navigation_gutter) <= 2, "History cards must align with main navigation"
            assert abs(history_bar_box["width"] - (1440 - 2 * navigation_gutter)) <= 2
            assert abs(history_body_box["width"] - (1440 - 2 * navigation_gutter)) <= 2
            assert page.locator('[data-hist-filter="all"]').inner_text().endswith("(6)")
            page.locator('[data-hist-expand-batch="gen_leo_003"]').click()
            assert page.locator('[data-hist-img-toggle="gen_leo_003"]').count() == 2
            page.locator("#hist-search-inp").fill("山水")
            page.wait_for_timeout(300)
            assert page.locator('[data-hist-id="gen_leo_003"]').count() == 1
            assert page.locator('[data-hist-id="gen_leo_001"]').count() == 0
            page.locator("#hist-search-inp").fill("")
            page.locator("#hist-status-filter").select_option("success")
            page.locator("#hist-sort").select_option("oldest")
            assert page.locator('[data-hist-id="gen_leo_003"]').count() == 1
            page.locator("#studio-mode-quick").click()
            assert "entry=quick" in page.url, f"Quick creation navigation failed: {page.url}"
            page.goto(f"{BASE_URL}/studio/?entry=batch", wait_until="networkidle")
            page.locator("#studio-mode-history").click()
            page.locator("#studio-mode-batch").click()
            assert "entry=batch" in page.url, f"Batch creation navigation failed: {page.url}"

            # Check 4: Existing direct history URLs remain inside the studio.
            # -----------------------------------------------------------
            print("\n>>> Check 4: Legacy history deep link remains in studio...")
            page.goto(f"{BASE_URL}/studio/?view=history&page=2", wait_until="networkidle")
            page.wait_for_selector(".ic-hist-masonry-grid", timeout=6000)
            assert "view=history" in page.url, f"Legacy history URL left the studio: {page.url}"
            page.locator("#studio-mode-quick").click()
            assert "entry=quick" in page.url

            # Check 5: The workflow library has one global navigation and minimal tools.
            # -----------------------------------------------------------
            print("\\n>>> Check 5: Minimal workflow library and direct legacy URL...")
            page.goto(f"{BASE_URL}/studio/?view=workflows", wait_until="networkidle")
            page.wait_for_selector("#wf-search-inp", timeout=6000)
            assert page.locator("#studio-mode-workflows").is_visible()
            assert page.locator("#wf-import-file-inp").count() == 1
            assert page.locator("#wf-saved-list-box").count() == 1
            assert page.locator("#wf-saved-list-box.ic-wf-card-grid").count() == 1
            assert page.locator(".ic-wf-entry-card").count() >= 1
            assert page.locator("#studio-mode-canvas").inner_text().strip() == "画布"
            workflow_bar_box = page.locator(".ic-wf-minimal-tools").bounding_box()
            workflow_body_box = page.locator(".ic-wf-page-inner").bounding_box()
            for key in ("x", "width"):
                assert abs(workflow_bar_box[key] - history_bar_box[key]) <= 2, f"Library toolbar {key} misaligned"
                assert abs(workflow_body_box[key] - history_body_box[key]) <= 2, f"Library content {key} misaligned"
            workflow_columns = page.locator("#wf-saved-list-box").evaluate("(el) => getComputedStyle(el).gridTemplateColumns.split(/\\s+/).length")
            assert workflow_columns == 3, f"Desktop workflow grid expected 3 columns, got {workflow_columns}"
            assert not page.locator("#ic-workbench-bar").is_visible(), "Canvas tab navigation must be hidden"
            assert page.locator("#wf-back-canvas").count() == 0
            assert page.locator("#wf-restore-presets").count() == 0
            assert page.locator("#tb-open-wflib").count() == 0
            page.locator("#wf-search-inp").fill("no-such-workflow-search-value")
            assert page.locator("#wf-saved-list-box").count() == 0
            page.locator("#wf-search-inp").fill("")

            # Check 6: Mobile viewport.
            # -----------------------------------------------------------
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{BASE_URL}/studio/?view=history", wait_until="networkidle")
            page.wait_for_selector(".ic-hist-masonry-grid", timeout=6000)
            columns = page.locator(".ic-hist-masonry-grid").evaluate(
                "(el) => getComputedStyle(el).gridTemplateColumns.split(/\\s+/).length"
            )
            assert columns == 2, f"History at 390px should use two columns like homepage: {columns}"
            mobile_history_bar = page.locator(".ic-history-topbar").bounding_box()
            page.screenshot(path=str(MOBILE_SCREENSHOT), full_page=False)
            page.goto(f"{BASE_URL}/studio/?view=workflows", wait_until="networkidle")
            page.wait_for_selector("#wf-saved-list-box", timeout=6000)
            mobile_workflow_bar = page.locator(".ic-wf-minimal-tools").bounding_box()
            assert abs(mobile_workflow_bar["width"] - mobile_history_bar["width"]) <= 2
            assert abs(mobile_workflow_bar["x"] - mobile_history_bar["x"]) <= 2
            mobile_workflow_cols = page.locator("#wf-saved-list-box").evaluate("(el) => getComputedStyle(el).gridTemplateColumns.split(/\\s+/).length")
            assert mobile_workflow_cols == 1, f"Mobile workflow grid expected 1 column, got {mobile_workflow_cols}"

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
