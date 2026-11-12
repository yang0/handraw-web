import os
import sys
import json
import time
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

from tests.browser_postgres import browser_postgres_database
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME
from backend.services import register_user

PORT = 3098
BASE_URL = f"http://127.0.0.1:{PORT}"

SCREENSHOT_STYLE = Path("C:/tmp/detail_actions_style_desktop.png")
SCREENSHOT_WORK = Path("C:/tmp/detail_actions_work_desktop.png")
SCREENSHOT_MOBILE = Path("C:/tmp/detail_actions_mobile.png")
SCREENSHOT_STYLE.parent.mkdir(parents=True, exist_ok=True)


def run_browser_verification():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Setting up test server on port {PORT}...")
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
    author_user, _ = register_user(db, "author_alice", "Pass1234!")
    viewer_user, viewer_token = register_user(db, "viewer_bob", "Pass1234!")

    conn = db.get_conn()
    with db.transaction() as tx:
        # 1. Style Topic & Resource Link
        tx.execute("""
            INSERT INTO forum_topics (id, category, category_label, pinned, featured, title, author_username, author_name, views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id, images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body, status, published_at_ms, created_label, created_at, updated_at)
            VALUES ('t_style_1', 'assets', '🎨 画风专区', 0, 0, '松散黑线画风使用手册', 'author_alice', '爱丽丝', 10, 5, 2, 0, 0, 'none', 0, '', '[]', '["FA-001"]', '', '', '', 0, '画风详细说明', '', 'published', 1000, '刚刚', '2026-10-25 10:00:00', '2026-10-25 10:00:00')
        """)
        tx.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('style', 'FA-001', 't_style_1', 'official', '2026-10-25 10:00:00')")

        # 2. Work & Work Topic Link
        tx.execute("""
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, status, likes, favorites, forks, tips, published_at_ms, created_label, created_at, updated_at)
            VALUES ('w_1', 'author_alice', '爱丽丝', '墨色山水试作', '["/demo/assets/hero.png"]', '["FA-001"]', 'SC-001', 0, '墨色山水', 'published', 15, 7, 12, 40, 1000, '刚刚', '2026-10-25 10:00:00', '2026-10-25 10:00:00')
        """)
        tx.execute("""
            INSERT INTO forum_topics (id, category, category_label, pinned, featured, title, author_username, author_name, views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id, images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body, status, published_at_ms, created_label, created_at, updated_at)
            VALUES ('t_work_1', 'work', '🖼️ 作品广场', 0, 0, '墨色山水试作展示', 'author_alice', '爱丽丝', 20, 15, 7, 0, 0, 'none', 0, '', '["/demo/assets/hero.png"]', '["FA-001"]', 'SC-001', 'w_1', '', 0, '作品说明', '', 'published', 1000, '刚刚', '2026-10-25 10:00:00', '2026-10-25 10:00:00')
        """)
        tx.execute("INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', 'w_1', 't_work_1', 'work', '2026-10-25 10:00:00')")

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
                browser = p.chromium.launch(headless=True)
            except Exception:
                browser = p.chromium.launch(channel="msedge", headless=True)

            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"Origin": BASE_URL}
            )
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": viewer_token,
                "domain": "127.0.0.1",
                "path": "/"
            }])
            page = context.new_page()

            # -------------------------------------------------------------
            # Step 1: Style Detail Verification (Desktop 1440)
            # -------------------------------------------------------------
            print("\n[Step 1] Verifying Style Detail page...")
            page.goto(f"{BASE_URL}/forum/?view=topic&id=t_style_1")
            page.wait_for_selector("#topic-page-like", timeout=10000)

            # Check action bar buttons exist in unified order
            action_buttons = page.locator(".topic-action-bar button")
            btn_ids = [action_buttons.nth(i).get_attribute("id") for i in range(action_buttons.count())]
            print(f"Action bar button IDs: {btn_ids}")

            assert "topic-page-like" in btn_ids, "Missing like button"
            assert "topic-page-collect" in btn_ids, "Missing collect button"
            assert "topic-page-scroll-reply" in btn_ids, "Missing comment/reply button"
            assert "topic-page-tip" in btn_ids, "Missing tip button"
            assert "topic-page-share" in btn_ids, "Missing share button"

            like_idx = btn_ids.index("topic-page-like")
            collect_idx = btn_ids.index("topic-page-collect")
            reply_idx = btn_ids.index("topic-page-scroll-reply")
            tip_idx = btn_ids.index("topic-page-tip")
            share_idx = btn_ids.index("topic-page-share")
            assert like_idx < collect_idx < reply_idx < tip_idx < share_idx, "Buttons must follow unified order"

            # Check duplicate counts removal
            counts_text = page.locator("#topic-counts").text_content()
            print(f"Style #topic-counts text: '{counts_text}'")
            assert "点赞" not in counts_text, "Duplicate '点赞' must not appear in #topic-counts"
            assert "收藏" not in counts_text, "Duplicate '收藏' must not appear in #topic-counts"

            # Check no duplicate tip button in stamps
            stamp_tip_btn = page.locator("#topic-stamp-tip-btn")
            assert stamp_tip_btn.count() == 0, "Stamps section must not contain duplicate tip button"

            # Check stamps are retired (Issue #52)
            assert page.locator("#topic-stamp-recipe").count() == 0, "Resource detail must NOT contain #topic-stamp-recipe"
            assert page.locator("#topic-stamp-aesthetic").count() == 0, "Resource detail must NOT contain #topic-stamp-aesthetic"
            assert page.locator(".topic-resource-stamps").count() == 0, "Resource detail must NOT contain .topic-resource-stamps"
            style_body_text = page.locator("body").inner_text()
            assert "超实用配方" not in style_body_text, "'超实用配方' must not appear in resource detail"
            assert "审美在线" not in style_body_text, "'审美在线' must not appear in resource detail"

            # Check creative semantic button is present
            use_btn = page.locator("#topic-resource-use-btn")
            assert use_btn.is_visible(), "Style resource must render '去创作' button"

            page.screenshot(path=str(SCREENSHOT_STYLE), full_page=False)
            print(f"Saved style screenshot: {SCREENSHOT_STYLE}")

            # -------------------------------------------------------------
            # Step 2: Work Detail Verification (Desktop 1440)
            # -------------------------------------------------------------
            print("\n[Step 2] Verifying Work Detail page...")
            page.goto(f"{BASE_URL}/forum/?view=topic&id=t_work_1")
            page.wait_for_selector("#topic-page-like", timeout=10000)

            work_counts = page.locator("#topic-counts").text_content()
            print(f"Work #topic-counts text: '{work_counts}'")
            assert "点赞" not in work_counts, "Duplicate '点赞' must not appear in work #topic-counts"
            assert "收藏" not in work_counts, "Duplicate '收藏' must not appear in work #topic-counts"
            assert "获赞赏 40✦" in work_counts, "Work detail must display '获赞赏 40✦'"
            assert "做同款 12" in work_counts, "Work detail must display '做同款 12'"

            # Check stamps are retired in work detail
            assert page.locator("#topic-stamp-recipe").count() == 0, "Work detail must NOT contain #topic-stamp-recipe"
            assert page.locator("#topic-stamp-aesthetic").count() == 0, "Work detail must NOT contain #topic-stamp-aesthetic"
            assert page.locator(".topic-resource-stamps").count() == 0, "Work detail must NOT contain .topic-resource-stamps"
            work_body_text = page.locator("body").inner_text()
            assert "超实用配方" not in work_body_text, "'超实用配方' must not appear in work detail"
            assert "审美在线" not in work_body_text, "'审美在线' must not appear in work detail"

            # Work should have '做同款' action
            body_html = page.locator("#topic-article-body").inner_html()
            print(f"Article body HTML: {body_html[:300]}")
            fork_btn = page.locator(".fwp-fork, a[href*='fork='], [data-fwp-copy]")
            print(f"Fork btn count: {fork_btn.count()}")

            page.screenshot(path=str(SCREENSHOT_WORK), full_page=False)
            print(f"Saved work screenshot: {SCREENSHOT_WORK}")

            # -------------------------------------------------------------
            # Step 3: Partial Social Interaction (No Full Re-render)
            # -------------------------------------------------------------
            print("\n[Step 3] Testing partial social update on Work page...")
            like_btn = page.locator("#topic-page-like")
            initial_text = like_btn.text_content().strip()
            print(f"Initial like text: {initial_text}")
            assert "点赞" in initial_text

            like_btn.click()
            page.wait_for_function("document.querySelector('#topic-page-like').textContent.includes('已赞')")
            updated_text = like_btn.text_content().strip()
            print(f"Updated like text: {updated_text}")
            assert "已赞 (16)" in updated_text

            # Verify #topic-counts still clean
            work_counts_after = page.locator("#topic-counts").text_content()
            print(f"Work #topic-counts after like: '{work_counts_after}'")
            assert "点赞" not in work_counts_after
            assert "收藏" not in work_counts_after
            assert "获赞赏 40✦" in work_counts_after
            assert "做同款 12" in work_counts_after

            # -------------------------------------------------------------
            # Step 4: Mobile Viewport Responsive (390x844)
            # -------------------------------------------------------------
            print("\n[Step 4] Testing mobile viewport 390px...")
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload()
            page.wait_for_selector("#topic-page-like", timeout=10000)

            # Check no horizontal scrolling overflow on root/body
            overflow_res = page.evaluate("""() => {
                const bodyWidth = document.body.clientWidth;
                const bodyScroll = document.body.scrollWidth;
                const root = document.querySelector('#forum-root') || document.documentElement;
                return {
                    bodyWidth,
                    bodyScroll,
                    rootWidth: root.clientWidth,
                    rootScroll: root.scrollWidth,
                    hasHorizontalOverflow: root.scrollWidth > root.clientWidth + 2
                };
            }""")
            print(f"Mobile layout dimensions: {overflow_res}")
            assert not overflow_res["hasHorizontalOverflow"], f"Horizontal overflow detected on mobile: {overflow_res}"

            # Check stamps are retired in mobile view
            assert page.locator("#topic-stamp-recipe").count() == 0, "Mobile view must NOT contain #topic-stamp-recipe"
            assert page.locator("#topic-stamp-aesthetic").count() == 0, "Mobile view must NOT contain #topic-stamp-aesthetic"
            assert page.locator(".topic-resource-stamps").count() == 0, "Mobile view must NOT contain .topic-resource-stamps"
            mobile_body_text = page.locator("body").inner_text()
            assert "超实用配方" not in mobile_body_text, "'超实用配方' must not appear in mobile view"
            assert "审美在线" not in mobile_body_text, "'审美在线' must not appear in mobile view"

            page.screenshot(path=str(SCREENSHOT_MOBILE), full_page=False)
            print(f"Saved mobile screenshot: {SCREENSHOT_MOBILE}")

            print("\n=======================================================")
            print("ALL BROWSER PLAYWRIGHT VERIFICATIONS PASSED SUCCESSFULLY!")
            print("=======================================================")

    finally:
        httpd.shutdown()
        httpd.server_close()
        try:
            db.get_conn().close()
            db.close()
        except Exception:
            pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_browser_verification()
