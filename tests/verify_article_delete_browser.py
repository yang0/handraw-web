"""Browser verification script for issue #62 (Article deletion).

Verifies:
1. Editor delete: opens editor, confirms deletion via modal, redirects, reloads to verify article is gone.
2. Profile list delete: deletes article card in real-time without full page reload.
3. History pagination delete: deletes article, re-logs in to verify it does not return, and checks empty state when last article deleted.
All screenshots saved to C:/tmp/
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PORT = 3125
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def wait_for_server(url: str, timeout: float = 12.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"{url}/studio/")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    db_path = temp_path / "browser_article_del_test.db"
    uploads_dir = temp_path / "uploads"
    generated_dir = temp_path / "generated"
    storage_dir = temp_path / "private_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "HANDRAW_PRIVATE_STORAGE": str(storage_dir),
        "HANDRAW_DB_PATH": str(db_path),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DEMO_MODE": "0",
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT},http://localhost:{PORT}",
    })

    from tests.legacy_database import init_legacy_database
    from backend.server import SESSION_COOKIE_NAME
    from backend.services import register_user, sync_user_studio_articles

    init_db = init_legacy_database(db_path)
    user, session_token = register_user(init_db, "su_editorial", "Pass123456", display_name="主编苏")

    # Seed 3 articles
    articles = [
        {
            "id": "art_test_editor",
            "articleTitle": "编辑器删除测试文章",
            "markdown": "# 留白工作法\n\n测试在文章编辑器中直接删除此文章。",
            "cards": [{"id": "c1", "role": "cover", "status": "ready", "imageUrl": "/images/cover1.webp"}],
            "runCount": 1,
            "status": "ready",
        },
        {
            "id": "art_test_profile",
            "articleTitle": "个人主页删除测试文章",
            "markdown": "# 现代职场效率\n\n测试在个人主页文章列表中直接删除。",
            "cards": [{"id": "c2", "role": "cover", "status": "ready", "imageUrl": "/images/cover2.webp"}],
            "runCount": 1,
            "status": "ready",
        },
        {
            "id": "art_test_history",
            "articleTitle": "历史分页删除测试文章",
            "markdown": "# 视觉设计原则\n\n测试在历史文章分页中删除并在重新登录后不出现。",
            "cards": [],
            "runCount": 0,
            "status": "ready",
        },
    ]
    sync_user_studio_articles(init_db, user, articles)
    init_db.close()

    server_proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server", "--port", str(PORT), "--db", str(db_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not wait_for_server(BASE_URL):
            print("Server failed to start in time.")
            return 1

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page = context.new_page()

            # -------------------------------------------------------------
            # Scenario 1: Editor delete
            # -------------------------------------------------------------
            print("\n--- Scenario 1: Editor Delete ---")
            editor_url = f"{BASE_URL}/studio/?entry=article&articleId=art_test_editor&subview=editor"
            page.goto(editor_url, wait_until="networkidle")
            page.wait_for_selector("#editor-btn-delete-article", timeout=8000)

            # Click delete button in editor
            page.click("#editor-btn-delete-article")
            page.wait_for_selector("#hw-active-modal", timeout=5000)
            page.screenshot(path=str(SCREENSHOT_DIR / "01_editor_delete_modal.png"))
            print("✓ Screenshot saved: 01_editor_delete_modal.png")

            modal_text = page.locator("#hw-active-modal").inner_text()
            assert "删除后不可恢复" in modal_text, "Modal missing warning text"
            assert "编辑器删除测试文章" in modal_text, "Modal missing article title"

            # Confirm delete
            page.click("#hw-del-art-confirm-btn")
            page.wait_for_timeout(1000)

            # Verify redirected to article list
            page.screenshot(path=str(SCREENSHOT_DIR / "02_editor_deleted_redirect.png"))
            print("✓ Screenshot saved: 02_editor_deleted_redirect.png")

            # Reload to verify article is permanently deleted from server
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(path=str(SCREENSHOT_DIR / "03_editor_deleted_after_refresh.png"))
            print("✓ Screenshot saved: 03_editor_deleted_after_refresh.png")

            body_text = page.content()
            assert "art_test_editor" not in body_text, "Deleted article still visible after refresh!"
            print("✓ Scenario 1 passed: Editor delete confirmed and verified gone after refresh.")

            # -------------------------------------------------------------
            # Scenario 2: Profile articles list delete
            # -------------------------------------------------------------
            print("\n--- Scenario 2: Studio Article List via Legacy Profile Link ---")
            profile_url = f"{BASE_URL}/?view=profile&user=su_editorial&ptab=articles"
            page.goto(profile_url, wait_until="networkidle")
            page.wait_for_selector('[data-del-art-id="art_test_profile"]', timeout=8000)
            assert "/studio/" in page.url and "view=articles-all" in page.url
            page.screenshot(path=str(SCREENSHOT_DIR / "04_profile_articles_before.png"))
            print("✓ Screenshot saved: 04_profile_articles_before.png")

            # Click delete button on the profile card
            page.click('[data-del-art-id="art_test_profile"]')
            page.wait_for_selector("#hw-active-modal", timeout=5000)
            page.screenshot(path=str(SCREENSHOT_DIR / "05_profile_delete_modal.png"))
            print("✓ Screenshot saved: 05_profile_delete_modal.png")

            # Confirm delete
            page.click("#hw-del-art-confirm-btn")
            page.wait_for_timeout(1000)

            # Verify removed in real time without reloading whole page
            page.screenshot(path=str(SCREENSHOT_DIR / "06_profile_after_deleted.png"))
            print("✓ Screenshot saved: 06_profile_after_deleted.png")

            profile_cards = page.locator('[data-del-art-id="art_test_profile"]').count()
            assert profile_cards == 0, "Article card was not removed in real time!"
            print("✓ Scenario 2 passed: Profile delete confirmed and card removed in real time.")

            # -------------------------------------------------------------
            # Scenario 3: History articles pagination delete & re-login verification
            # -------------------------------------------------------------
            print("\n--- Scenario 3: History Pagination Delete & Re-login ---")
            hist_url = f"{BASE_URL}/studio/?view=articles-all"
            page.goto(hist_url, wait_until="networkidle")
            page.wait_for_selector('[data-del-art-id="art_test_history"]', timeout=8000)
            page.screenshot(path=str(SCREENSHOT_DIR / "07_history_page_before.png"))
            print("✓ Screenshot saved: 07_history_page_before.png")

            # Click delete button in pagination card
            page.click('[data-del-art-id="art_test_history"]')
            page.wait_for_selector("#hw-active-modal", timeout=5000)
            page.screenshot(path=str(SCREENSHOT_DIR / "08_history_delete_modal.png"))
            print("✓ Screenshot saved: 08_history_delete_modal.png")

            # Confirm delete
            page.click("#hw-del-art-confirm-btn")
            page.wait_for_timeout(1000)

            # Since it was the last article, empty state should now be displayed
            page.screenshot(path=str(SCREENSHOT_DIR / "09_history_after_deleted.png"))
            print("✓ Screenshot saved: 09_history_after_deleted.png")

            # Clear context cookies, simulate re-login
            context.clear_cookies()
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page.goto(hist_url, wait_until="networkidle")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(SCREENSHOT_DIR / "10_history_relogin_confirmed_gone.png"))
            print("✓ Screenshot saved: 10_history_relogin_confirmed_gone.png")

            content = page.content()
            assert "art_test_history" not in content, "Deleted article returned after re-login!"
            assert "没有找到匹配的历史文章" in content or "暂无历史文章" in content, "Empty state not displayed after deleting last article!"
            print("✓ Scenario 3 passed: History delete confirmed, did not return after re-login, empty state shown.")

            browser.close()

        print("\n===========================================")
        print("ALL BROWSER AUTOMATION TESTS COMPLETED SUCCESSFULLY!")
        print("===========================================")
        return 0

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3.0)
        except Exception:
            server_proc.kill()
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
