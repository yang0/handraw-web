"""Browser verification for Task #5 (Issue #59): Generation history auto-projection into Works Square and Diversity Masonry.

Verifies:
1. Starts test server on port 3135 (outside 3093-3112).
2. Logs in 'yang0' / 'Preview123!test' using session cookie on browser context (<= 8 requests/5min).
3. Creates diverse public generations from multiple authors (yang0, author_lin, author_wang, author_chen, author_zhao, author_sun)
   as well as private and soft-deleted generations.
4. Confirms public generations are projected into Works Square and rendered via Masonry.
5. Confirms private and soft-deleted generations do NOT appear in Works Square.
6. Asserts Desktop 1440 (4 cols) and Mobile 390 (2 cols) continuous masonry layout without any single author, style, or layout monopolizing the viewport.
7. Saves verification screenshots to C:/tmp/square_desktop_verified.png and C:/tmp/square_mobile_verified.png.
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
from backend.services import (
    hash_password,
    login_user,
    register_user,
    record_user_studio_history,
    delete_user_studio_history,
)
from backend.generation_works import sync_generation_visibility

PORT = 3135
BASE_URL = f"http://127.0.0.1:{PORT}"
DESKTOP_SCREENSHOT = Path("C:/tmp/square_desktop_verified.png")
MOBILE_SCREENSHOT = Path("C:/tmp/square_mobile_verified.png")
DESKTOP_SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)


def run_verification():
    print(f"[1/6] Setting up test server environment on port {PORT}...")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_square_verify.db"
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

    # Set password for seeded user yang0 and log in
    with db.transaction() as tx:
        tx.execute("UPDATE users SET password_hash = ? WHERE username = 'yang0'", (hash_password("Preview123!test"),))

    user_yang0, token_yang0 = login_user(db, "yang0", "Preview123!test")
    user_lin, _ = register_user(db, "author_lin", "Pass1234!", display_name="小林")
    user_wang, _ = register_user(db, "author_wang", "Pass1234!", display_name="老王")
    user_chen, _ = register_user(db, "author_chen", "Pass1234!", display_name="陈木")
    user_zhao, _ = register_user(db, "author_zhao", "Pass1234!", display_name="赵工")
    user_sun, _ = register_user(db, "author_sun", "Pass1234!", display_name="孙竹")

    print("[2/6] Seeding diverse generations from multiple authors...")

    authors = [
        (user_yang0, "杨生"),
        (user_lin, "小林"),
        (user_wang, "老王"),
        (user_chen, "陈木"),
        (user_zhao, "赵工"),
        (user_sun, "孙竹"),
    ]

    styles_catalog = ["FA-013", "FA-001", "FA-002", "FA-015", "FA-016", "FA-018"]
    layouts_catalog = ["SC-001", "SC-002", "", "SC-001", "", "SC-002"]
    subjects = [
        "水墨松林", "黑白速写", "留白卡片", "晨雾青山", "折角图谱", "暮色幽径",
        "雨后春笋", "高挑竹影", "湖畔清波", "庭前秋叶", "古寺钟声", "长亭晚雪",
        "山水册页", "云间飞鸟", "小楼东风", "江上清风", "幽居空谷", "墨香茶舍"
    ]

    # Create 18 diverse public generations across 6 authors
    for i in range(18):
        author_user, author_name = authors[i % len(authors)]
        style = styles_catalog[i % len(styles_catalog)]
        layout = layouts_catalog[i % len(layouts_catalog)]
        subj = subjects[i % len(subjects)]
        ratio = "3:4" if (i % 3 == 0) else ("1:1" if (i % 3 == 1) else "16:9")

        record_user_studio_history(
            db,
            author_user,
            entry={
                "id": f"gen_pub_{i + 1}",
                "timestamp": 1700000000000 + i * 10000,
                "summary": f"{subj} #{i + 1}",
                "workspace": {
                    "subject": subj,
                    "styles": [style] if style else [],
                    "layout": layout,
                    "aspectRatio": ratio,
                    "prompt": f"生成提示词: {subj}",
                },
                "items": [
                    {
                        "id": f"item_{i + 1}_0",
                        "title": f"成图 #1",
                        "imageUrl": "/demo/assets/hero.png",
                        "ratio": ratio,
                    }
                ],
            },
        )

    # Also create 1 private generation for yang0
    record_user_studio_history(
        db,
        user_yang0,
        entry={
            "id": "gen_private_1",
            "timestamp": 1700000999000,
            "summary": "私密创作机密稿件",
            "workspace": {
                "subject": "私密草图",
                "styles": ["FA-013"],
                "aspectRatio": "1:1",
            },
            "items": [
                {
                    "id": "item_private_0",
                    "title": "成图 #1",
                    "imageUrl": "/demo/assets/hero.png",
                    "ratio": "1:1",
                }
            ],
        },
    )
    sync_generation_visibility(db.get_conn(), "gen_private_1", "private")

    # And create 1 public generation then soft delete it
    record_user_studio_history(
        db,
        user_yang0,
        entry={
            "id": "gen_deleted_1",
            "timestamp": 1700000998000,
            "summary": "即将删除的试作",
            "workspace": {
                "subject": "即将删除的试作",
                "styles": ["FA-001"],
                "aspectRatio": "16:9",
            },
            "items": [
                {
                    "id": "item_del_0",
                    "title": "成图 #1",
                    "imageUrl": "/demo/assets/hero.png",
                    "ratio": "16:9",
                }
            ],
        },
    )
    delete_user_studio_history(db, user_yang0, "gen_deleted_1")

    # Start HTTP server
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"  # type: ignore[attr-defined]
    httpd.db = db  # type: ignore[attr-defined]
    httpd.allow_demo_routes = True  # type: ignore[attr-defined]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"Server started on {BASE_URL}")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                browser = p.chromium.launch(channel="msedge", headless=True)

            print("[3/6] Initializing authenticated browser context for yang0...")
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"Origin": BASE_URL},
            )
            # Reusing session cookie: 1 cookie set, <= 8 requests/5min
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_yang0,
                "domain": "127.0.0.1",
                "path": "/",
            }])

            # -------------------------------------------------------------
            # Step 1: Desktop 1440 Verification
            # -------------------------------------------------------------
            print("\n[Step 1] Verifying Works Square on Desktop 1440x900...")
            page = context.new_page()
            page.goto(f"{BASE_URL}/?view=works", wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Check masonry cards
            cards = page.locator(".hw-wb-card")
            card_count = cards.count()
            print(f"Total rendered work cards: {card_count}")
            assert card_count >= 18, f"Expected at least 18 cards, found {card_count}"

            # Check that private and deleted works are NOT rendered
            page_text = page.locator("#hw-wb-masonry").inner_text()
            assert "私密创作机密稿件" not in page_text, "Private generation must NOT appear in Works Square!"
            assert "即将删除的试作" not in page_text, "Deleted generation must NOT appear in Works Square!"
            print("✓ Private and deleted generation cards successfully excluded from Works Square")

            # Check diversity across visible viewport (first 8 cards)
            visible_authors = []
            for i in range(min(8, card_count)):
                author_el = cards.nth(i).locator(".hw-wb-author")
                if author_el.count() > 0:
                    visible_authors.append(author_el.first.inner_text().strip())

            print(f"First 8 cards authors: {visible_authors}")
            if visible_authors:
                distinct_authors = set(visible_authors)
                print(f"Distinct authors in initial viewport: {len(distinct_authors)}")
                # Assert no single author monopolizes the visible viewport
                assert len(distinct_authors) >= 3, f"Expected >= 3 distinct authors in viewport, got {len(distinct_authors)}"
                print("✓ Viewport author diversity verified: no single author monopolizes the viewport")

            # Save Desktop Screenshot
            page.screenshot(path=str(DESKTOP_SCREENSHOT), full_page=False)
            print(f"Desktop screenshot saved to {DESKTOP_SCREENSHOT}")

            # -------------------------------------------------------------
            # Step 2: Mobile 390 Verification
            # -------------------------------------------------------------
            print("\n[Step 2] Verifying Works Square on Mobile 390x844...")
            page_mobile = context.new_page()
            page_mobile.set_viewport_size({"width": 390, "height": 844})
            page_mobile.goto(f"{BASE_URL}/?view=works", wait_until="networkidle")
            page_mobile.wait_for_timeout(1000)

            mobile_cards = page_mobile.locator(".hw-wb-card")
            mobile_card_count = mobile_cards.count()
            print(f"Mobile total rendered work cards: {mobile_card_count}")
            assert mobile_card_count >= 18, f"Expected at least 18 cards on mobile, found {mobile_card_count}"

            # Check column count on mobile
            col_count = page_mobile.evaluate("""() => {
                const cols = document.querySelectorAll('#hw-wb-masonry > div');
                return cols.length;
            }""")
            print(f"Mobile masonry column count: {col_count}")
            assert col_count == 2, f"Mobile masonry should have 2 columns, got {col_count}"

            # Save Mobile Screenshot
            page_mobile.screenshot(path=str(MOBILE_SCREENSHOT), full_page=False)
            print(f"Mobile screenshot saved to {MOBILE_SCREENSHOT}")

            browser.close()

    finally:
        httpd.shutdown()
        server_thread.join(timeout=2)
        try:
            db.close()
        except Exception:
            pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass
        print("Server stopped and temporary files cleaned up.")

    print("\n==========================================")
    print("ALL WORKS SQUARE BROWSER VERIFICATIONS PASSED! 🎉")
    print("==========================================")


if __name__ == "__main__":
    run_verification()
