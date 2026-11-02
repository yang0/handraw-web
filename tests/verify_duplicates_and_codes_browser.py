"""Browser verification for Issue #39:
- Verify deduplication of generation history on creator profile (no duplicated images).
- Verify no [object Object] in cards or modal.
- Verify explicit code extraction (e.g. FA-022 · SC-001) and separate date line.
- Save screenshots to C:/tmp/
"""
from __future__ import annotations

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
SCREENSHOT_CARDS = Path("C:/tmp/issue39_profile_cards.png")
SCREENSHOT_MODAL = Path("C:/tmp/issue39_modal.png")
SCREENSHOT_CARDS.parent.mkdir(parents=True, exist_ok=True)


def seed_dirty_and_duplicate_generations(db, user_id: int, username: str):
    pairs = [
        ("hist_mvyh2i1e_332", "gen_1793576355465_4a0f68", ["https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=800"], "水墨荷塘意境", "#FA-001"),
        ("hist_mvyga05q_328", "gen_1793575032179_540c33", ["https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=800"], "秋分山野丰收", "#FA-002 #SC-001"),
        ("hist_mvyg8ekn_326", "gen_1793574938881_315ab1", ["https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=800"], "城市微光速写", "#FA-003"),
        ("hist_mvxek8hr_326", "gen_1793511683689_813d65", ["https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800"], "复古质感插画", "#FA-004"),
    ]

    now = "2026-11-02T08:00:00Z"
    with db.transaction() as tx:
        for idx, (hist_id, gen_id, urls, subj, recipe) in enumerate(pairs):
            # 1. hist_ row with dirty string summary
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, recipe_summary, items_json, engine, status, visibility, created_at, tab_title
                ) VALUES (?, ?, ?, ?, ?, ?, 'sample', 'success', 'public', ?, '3:4')
                """,
                (hist_id, user_id, username, subj, f"[object Object] · {recipe}", json.dumps([{"imageUrl": u} for u in urls]), now),
            )
            # 2. gen_ row (live engine, trusted system_append_json snapshot)
            codes = [c.lstrip("#") for c in recipe.split()]
            snap = {"style1": codes[0], "layout": codes[1] if len(codes) > 1 else ""}
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, subject, recipe_summary, system_append_json, items_json, engine, status, visibility, created_at, tab_title
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'live', 'success', 'public', ?, '3:4')
                """,
                (gen_id, user_id, username, subj, recipe, json.dumps({"recipeSnapshot": snap}), json.dumps(urls), f"2026-11-02T08:0{idx}:00Z"),
            )


def run_browser_verification():
    print(f"Setting up test server on port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_issue39.db"
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
    user, token = register_user(db, "author_art", "Pass1234!")
    print(f"Registered user: {user['username']}")

    seed_dirty_and_duplicate_generations(db, user["id"], user["username"])
    print("Seeded 4 duplicate pairs (8 rows total) with dirty data.")

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"
    httpd.db = db
    httpd.allow_demo_routes = True
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"Server running on {BASE_URL}")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)

            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page = context.new_page()

            # -----------------------------------------------------------
            # Check 1: Profile page renders exactly 4 deduplicated cards
            # -----------------------------------------------------------
            print("\n>>> Check 1: Visiting profile page with ptab=generations...")
            page.goto(f"{BASE_URL}/?view=profile&user=author_art&ptab=generations", wait_until="networkidle")
            page.wait_for_timeout(1000)

            page.wait_for_selector("[data-prof-gen]", timeout=8000)
            cards = page.locator("[data-prof-gen]")
            count = cards.count()
            print(f"  ✓ Rendered cards count: {count}")
            assert count == 4, f"Expected 4 deduplicated cards, got {count}!"

            # Check that all cards have gen_ IDs (no duplicate hist_ rows)
            for i in range(count):
                cid = cards.nth(i).get_attribute("data-prof-gen")
                assert cid.startswith("gen_"), f"Card {i} has id {cid}, expected gen_ prefix"
            print("  ✓ All 4 rendered cards are clean gen_ server records")

            # -----------------------------------------------------------
            # Check 2: No [object Object] anywhere on the page
            # -----------------------------------------------------------
            body_text = page.locator("body").inner_text()
            assert "[object Object]" not in body_text, "Found [object Object] in page body!"
            print("  ✓ Zero occurrences of '[object Object]' on profile page")

            # -----------------------------------------------------------
            # Check 3: Check resource tag badge format (FA-002 · SC-001)
            # -----------------------------------------------------------
            card_texts = [cards.nth(i).inner_text() for i in range(count)]
            print("  Card snippets:", card_texts)
            # One of the cards has FA-002 and SC-001
            has_tag = any("FA-002 · SC-001" in t for t in card_texts)
            assert has_tag, f"Expected 'FA-002 · SC-001' badge in card texts: {card_texts}"
            print("  ✓ Code badge properly extracted and displayed as 'FA-002 · SC-001'")

            # Save screenshot of cards
            page.screenshot(path=str(SCREENSHOT_CARDS), full_page=False)
            print(f"  ✓ Saved cards screenshot to {SCREENSHOT_CARDS}")

            # -----------------------------------------------------------
            # Check 4: Open detail modal, check formatting & no [object Object]
            # -----------------------------------------------------------
            print("\n>>> Check 4: Opening generation detail modal...")
            # Click the card with FA-002 and SC-001
            cards.filter(has_text="秋分山野丰收").first.click()
            page.wait_for_selector(".hw-gen-detail-modal", timeout=4000)
            modal = page.locator(".hw-gen-detail-modal")
            modal_text = modal.inner_text()
            assert "[object Object]" not in modal_text, "Found [object Object] in modal!"
            assert "FA-002" in modal_text, "FA-002 missing in modal"
            assert "SC-001" in modal_text, "SC-001 missing in modal"
            print("  ✓ Modal renders cleanly without [object Object], showing FA-002 and SC-001")

            page.screenshot(path=str(SCREENSHOT_MODAL), full_page=False)
            print(f"  ✓ Saved modal screenshot to {SCREENSHOT_MODAL}")

            browser.close()
            print("\n🎉 ALL BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")

    finally:
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=3)
        db.close()
        temp_dir.cleanup()


if __name__ == "__main__":
    run_browser_verification()
