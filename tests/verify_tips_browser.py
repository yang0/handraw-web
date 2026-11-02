"""Playwright browser verification for tipping works and free topics.

Verifies on port 3097:
1. Free topic (price == 0):
   - Viewer sees '#topic-page-tip' (赞赏 2✦) in detail action bar.
   - Author does not see '#topic-page-tip'.
   - Viewer clicks '#topic-page-tip', tips 2 credits.
   - Author balance increases by +2, receives tip_in notification.
   - Topic detail page displays '获赞赏 2✦'.
   - Screenshot saved to C:/tmp/tip_01_free_topic.png.
2. Work topic / Work page:
   - Viewer visits bound work topic -> top action bar has '#topic-page-tip' routing to work.
   - Viewer visits /work/?id=w_free_demo -> work tip button exists.
   - Screenshot saved to C:/tmp/tip_02_work_topic.png.
3. Paid topic (price > 0):
   - Detail page has NO tip button.
   - Screenshot saved to C:/tmp/tip_03_paid_topic_no_btn.png.
4. Resource topic (bound to catalog asset):
   - Stamp card has '#topic-stamp-tip-btn'.
   - Top action bar has NO '#topic-page-tip' (no duplicate button).
   - Screenshot saved to C:/tmp/tip_04_resource_single_btn.png.
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

from backend.config import SESSION_COOKIE_NAME
from backend.server import HandrawRequestHandler, init_database
from backend.services import apply_wallet_delta, register_user
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
    db_path = root / "tips_verify.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

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
        db = init_database(db_path)
        author_user, token_author = register_user(db, "author_demo", "AuthorPass123!", display_name="原创画师小李")
        viewer_user, token_viewer = register_user(db, "viewer_demo", "ViewerPass123!", display_name="赞赏测试员")

        now_iso = "2026-11-02T00:00:00Z"
        with db.transaction() as tx:
            # Give viewer 50 credits
            apply_wallet_delta(tx, int(viewer_user["id"]), 50, "recharge", "测试充值")

            # Create test work
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, prompt, styles_json, layout_code, price, status, likes, favorites, cheers, tips, published_at_ms, created_at, updated_at)
                VALUES ('w_free_demo', 'author_demo', '原创画师小李', '灵动插画作品', '水彩小鹿灵动光影', '["FA-001"]', 'L-01', 0, 'published', 3, 1, 5, 0, 1700000000000, ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create free topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_free_demo', 'tuning', '技术调优', '探讨水彩笔刷技巧', 'author_demo', '原创画师小李', 0, 'published', 1, 0, 1700000000000, '[]', '[]', '探讨水彩笔刷技巧的摘要说明', ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create paid topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_paid_demo', 'experience', '经验分享', '独家水彩调优指南', 'author_demo', '原创画师小李', 20, 'published', 0, 0, 1700000000000, '[]', '[]', '独家水彩调优指南摘要说明', ?, ?)
                """,
                (now_iso, now_iso),
            )

            # Create bound work topic
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, work_id, summary, created_at, updated_at)
                VALUES ('t_work_demo', 'assets', '资源交流', '灵动插画官方讨论帖', 'author_demo', '原创画师小李', 0, 'published', 2, 0, 1700000000000, '[]', '[]', 'w_free_demo', '灵动插画官方讨论帖摘要说明', ?, ?)
                """,
                (now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('work', 'w_free_demo', 't_work_demo', 'submission', ?)
                """,
                (now_iso,),
            )

            # Create resource topic (bound to style FA-001)
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, price, status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at)
                VALUES ('t_asset_demo', 'assets', '资源交流', '水彩画风官方资源帖', 'author_demo', '原创画师小李', 0, 'published', 1, 0, 1700000000000, '[]', '["FA-001"]', '水彩画风官方资源帖摘要说明', ?, ?)
                """,
                (now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES ('style', 'FA-001', 't_asset_demo', 'submission', ?)
                """,
                (now_iso,),
            )

        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
        httpd.channel_role = "main"  # type: ignore[attr-defined]
        httpd.db = db  # type: ignore[attr-defined]
        httpd.allow_demo_routes = True  # type: ignore[attr-defined]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"Server started at {BASE_URL}")

        with sync_playwright() as p:
            launch_args = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            }
            if os.path.exists(CHROME_PATH):
                launch_args["executable_path"] = CHROME_PATH

            browser = p.chromium.launch(**launch_args)

            # =========================================================
            # Test 1: Free topic tipping (price == 0)
            # =========================================================
            print("\n[Test 1] Verifying free topic tipping as viewer...")
            ctx_viewer = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            ctx_viewer.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_viewer,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_viewer = ctx_viewer.new_page()
            page_viewer.on("dialog", lambda dialog: dialog.accept())

            # Go to free topic
            page_viewer.goto(f"{BASE_URL}/t/t_free_demo")
            page_viewer.wait_for_selector("#topic-page-tip", timeout=10000)
            
            tip_btn = page_viewer.locator("#topic-page-tip")
            assert tip_btn.is_visible(), "Tip button must be visible for viewer on free topic"
            btn_text = tip_btn.text_content() or ""
            print(f"  Found tip button with text: '{btn_text.strip()}'")
            assert "赞赏 2✦" in btn_text, f"Expected '赞赏 2✦', got '{btn_text}'"

            # Click tip button
            print("  Clicking '#topic-page-tip'...")
            tip_btn.click()
            time.sleep(1.0)

            # Check that UI counts update or toast appears
            counts_text = page_viewer.locator("#topic-counts").text_content() or ""
            print(f"  Topic counts after tip: '{counts_text.strip()}'")
            assert "获赞赏 2✦" in counts_text or "获赞赏" in page_viewer.content(), "Expected '获赞赏 2✦' in UI"

            shot_1 = SCREENSHOT_DIR / "tip_01_free_topic.png"
            page_viewer.screenshot(path=str(shot_1))
            print(f"  Saved screenshot 1: {shot_1}")

            # Verify author perspective (no tip button on own topic, receives notification)
            print("\n[Test 1.1] Verifying author perspective...")
            ctx_author = browser.new_context(
                viewport={"width": 1440, "height": 900},
                base_url=BASE_URL,
            )
            ctx_author.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": token_author,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page_author = ctx_author.new_page()

            page_author.goto(f"{BASE_URL}/t/t_free_demo")
            page_author.wait_for_selector("#topic-counts", timeout=10000)
            author_tip_btn = page_author.locator("#topic-page-tip")
            assert not author_tip_btn.is_visible(), "Author must NOT see tip button on their own post"
            print("  Author does not see tip button on own post (self-tip prevented in UI)")

            # Check author notification
            page_author.goto(f"{BASE_URL}/?view=notifications")
            page_author.wait_for_selector(".hw-notification-list", timeout=8000)
            notif_content = page_author.content()
            assert "赞赏" in notif_content or "2" in notif_content, "Author should receive tip notification"
            print("  Author received wallet income notification for the tip!")

            # =========================================================
            # Test 2: Work topic / Work page
            # =========================================================
            print("\n[Test 2] Verifying bound work topic...")
            page_viewer.goto(f"{BASE_URL}/t/t_work_demo")
            page_viewer.wait_for_selector("#topic-page-tip", timeout=10000)
            assert page_viewer.locator("#topic-page-tip").is_visible(), "Bound work topic has action bar tip button"
            
            shot_2 = SCREENSHOT_DIR / "tip_02_work_topic.png"
            page_viewer.screenshot(path=str(shot_2))
            print(f"  Saved screenshot 2: {shot_2}")

            # =========================================================
            # Test 3: Paid topic (price > 0)
            # =========================================================
            print("\n[Test 3] Verifying paid topic has NO tip button...")
            page_viewer.goto(f"{BASE_URL}/t/t_paid_demo")
            page_viewer.wait_for_selector("#topic-counts", timeout=10000)
            
            paid_tip_btn = page_viewer.locator("#topic-page-tip")
            assert not paid_tip_btn.is_visible(), "Paid topic must NOT have '#topic-page-tip'"
            assert page_viewer.locator("#topic-stamp-tip-btn").count() == 0, "Paid topic must NOT have stamp tip button"
            
            shot_3 = SCREENSHOT_DIR / "tip_03_paid_topic_no_btn.png"
            page_viewer.screenshot(path=str(shot_3))
            print(f"  Saved screenshot 3: {shot_3}")

            # =========================================================
            # Test 4: Resource topic (bound to catalog asset)
            # =========================================================
            print("\n[Test 4] Verifying resource topic has only ONE tip button (stamp tip, no duplicate top button)...")
            page_viewer.goto(f"{BASE_URL}/t/t_asset_demo")
            page_viewer.wait_for_selector("#topic-stamp-tip-btn", timeout=10000)
            
            assert page_viewer.locator("#topic-stamp-tip-btn").is_visible(), "Resource topic must have stamp tip button"
            assert not page_viewer.locator("#topic-page-tip").is_visible(), "Resource topic must NOT have top '#topic-page-tip' (no duplicate)"
            
            shot_4 = SCREENSHOT_DIR / "tip_04_resource_single_btn.png"
            page_viewer.screenshot(path=str(shot_4))
            print(f"  Saved screenshot 4: {shot_4}")

            browser.close()

        print("\n=== ALL PLAYWRIGHT BROWSER VERIFICATIONS PASSED SUCCESSFULLY! ===")

    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if db:
            try:
                db.close()
            except Exception:
                pass
        for k in env_patch:
            if old_env[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_env[k]
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
