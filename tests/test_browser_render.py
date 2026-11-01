"""Real browser checks: the pages must render content after JavaScript runs.

The server can return 200 with a perfectly valid shell while the app renders
nothing — a missing module, a thrown exception during boot, or an empty view all
look identical over HTTP.  Only a browser catches that, so these tests drive
Chromium and assert on the rendered text.

Skipped when Playwright or its browser is unavailable, so the suite still runs
on a machine without them.
"""
from __future__ import annotations

import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import server as server_module
from backend.server import create_channel_server
from backend.services import publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"
WORK_TITLE = "浏览器渲染断言作品"
WORK_PROMPT = "浏览器渲染断言提示词"
HIDDEN_THREAD_TITLE = "主帖被隐藏的作品"
CURATION_ITEM = "浏览器共创条目"
DELETED_THREAD_TITLE = "作者删除了主帖的作品"

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright  # type: ignore

    _HAS_PLAYWRIGHT = True
except Exception:  # pragma: no cover
    _HAS_PLAYWRIGHT = False


@unittest.skipUnless(_HAS_PLAYWRIGHT, "playwright not installed")
class BrowserRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test", "HANDRAW_PRIVATE_STORAGE": cls.temp.name})
        cls._env.start()
        cls.db = server_module.init_database(Path(cls.temp.name) / "browser.db")
        author, _ = register_user(cls.db, "br_author", "password-a")
        cls.work = publish_user_work(
            cls.db,
            author,
            {"title": WORK_TITLE, "prompt": WORK_PROMPT, "images": [IMG], "styles": ["FA-013"]},
        )
        # A second work whose thread an admin hid: the forum must not show it,
        # while the work itself stays public.
        cls.hidden = publish_user_work(
            cls.db,
            author,
            {"title": HIDDEN_THREAD_TITLE, "prompt": "p", "images": [IMG], "styles": ["FA-013"]},
        )
        register_user(cls.db, "br_admin", "password-admin")
        conn = cls.db.get_conn()
        conn.execute("UPDATE users SET role = 'admin' WHERE username = 'br_admin'")
        conn.commit()
        admin = dict(conn.execute("SELECT * FROM users WHERE username = 'br_admin'").fetchone())
        cls.db.close_thread_conn()
        from backend.admin_services import admin_moderate_topic

        admin_moderate_topic(cls.db, admin, cls.hidden["topicId"], "hide")
        # A third work whose thread its author deleted.
        cls.deleted = publish_user_work(
            cls.db,
            author,
            {"title": DELETED_THREAD_TITLE, "prompt": "p", "images": [IMG], "styles": ["FA-013"]},
        )
        from backend.services import forum_moderator_action

        forum_moderator_action(cls.db, author, {"topicId": cls.deleted["topicId"], "action": "delete"})
        # A curation submission, so the logged-in "my submissions" tab has a
        # known item to render.
        uploads = Path(cls.temp.name) / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        img.save(uploads / "cover_square.jpg")
        with cls.db.transaction() as tx:
            tx.execute(
                "INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("upl_br_cov", author["id"], "other", "cover_square.jpg", "/uploads/cover_square.jpg", str(uploads / "cover_square.jpg"), 100, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
            )
        from backend import curation

        curation.submit(
            cls.db,
            author,
            {
                "title": "浏览器共创投稿",
                "text": "介绍",
                "items": [{
                    "kind": "style", "name": CURATION_ITEM, "title": CURATION_ITEM,
                    "cover": "/uploads/cover_square.jpg",
                    "images": [IMG],
                    "definition": "定义：纸纹墨线", "prompt": "提示：窗边一束花", "unlockCost": 5,
                }],
            },
        )
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        try:
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
            cls._available = True
        except Exception:  # pragma: no cover - browser binary missing
            cls._pw = None
            cls._browser = None
            cls._available = False

    @classmethod
    def tearDownClass(cls):
        if cls._browser is not None:
            cls._browser.close()
        if cls._pw is not None:
            cls._pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close_thread_conn()
        cls.db.get_conn().close()
        cls.db.close()
        cls.temp.cleanup()
        cls._env.stop()

    def setUp(self):
        if not self._available:
            self.skipTest("chromium not available")
        self.page = self._browser.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda exc: self.js_errors.append(str(exc)))

    def tearDown(self):
        if getattr(self, "page", None) is not None:
            self.page.close()

    def _load(self, path, wait_text=None):
        self.page.goto(self.base + path, wait_until="networkidle", timeout=20000)
        # Wait for the app to finish its first render rather than assuming
        # networkidle means the DOM is filled.
        try:
            self.page.wait_for_function(
                "() => document.body && document.body.innerText.trim().length > 50",
                timeout=15000,
            )
        except Exception:
            pass
        if wait_text:
            self.page.wait_for_function(
                "t => document.body.innerText.includes(t)", arg=wait_text, timeout=15000
            )
        return self.page.inner_text("body")

    def test_home_page_renders_content_without_js_errors(self):
        body = self._load("/", wait_text=WORK_TITLE)
        # WORK_TITLE can only reach the DOM after boot runs and the feed renders.
        self.assertGreater(len(body.strip()), 50, "home page rendered no text")
        self.assertIn(
            WORK_TITLE, body,
            "the home feed must render the seeded work, which requires the JS modules to run",
        )
        self.assertEqual(self.js_errors, [], f"JS errors on home: {self.js_errors}")

    def test_work_topic_page_shows_title_and_prompt(self):
        body = self._load(f"/forum/?view=topic&id={self.work['topicId']}", wait_text=WORK_TITLE)
        self.assertIn(WORK_TITLE, body, "the topic page must show the work title")
        self.assertIn(WORK_PROMPT, body, "the topic page must show the work prompt")
        self.assertEqual(self.js_errors, [], f"JS errors on topic page: {self.js_errors}")

    def test_receipt_page_shows_the_work(self):
        body = self._load(
            f"/forum/?view=resource&kind=work&id={self.work['workId']}", wait_text=WORK_TITLE
        )
        self.assertIn(WORK_TITLE, body)
        self.assertEqual(self.js_errors, [], f"JS errors on receipt page: {self.js_errors}")

    def test_forum_list_renders(self):
        body = self._load("/forum/")
        self.assertGreater(len(body.strip()), 50)
        self.assertEqual(self.js_errors, [], f"JS errors on forum list: {self.js_errors}")

    def test_curation_tab_renders(self):
        body = self._load("/forum/?view=curation&tab=share")
        self.assertNotIn("接口不存在", body, "the curation view must not report a missing API")
        self.assertEqual(self.js_errors, [], f"JS errors on curation: {self.js_errors}")

    def test_work_detail_page_shows_title_and_prompt(self):
        body = self._load(f"/?view=work&id={self.work['workId']}", wait_text=WORK_PROMPT)
        self.assertIn(WORK_TITLE, body)
        self.assertIn(WORK_PROMPT, body)
        self.assertEqual(self.js_errors, [], f"JS errors on work detail: {self.js_errors}")

    def test_logged_in_curation_tab_lists_the_submission(self):
        # The anonymous check above only proves the view did not error; this
        # one needs the curation API and its renderer to actually work.
        response = self.page.request.post(
            self.base + "/api/auth/login",
            data={"account": "br_author", "password": "password-a"},
            headers={"Origin": "http://trusted.test"},
        )
        self.assertEqual(response.status, 200, response.text())
        body = self._load("/forum/?view=curation&tab=mine", wait_text=CURATION_ITEM)
        self.assertIn(CURATION_ITEM, body)
        for bad in ("接口不存在", "加载失败"):
            self.assertNotIn(bad, body)
        self.assertEqual(self.js_errors, [], f"JS errors on my submissions: {self.js_errors}")

    def test_forum_list_omits_a_hidden_thread_but_keeps_the_published_one(self):
        body = self._load("/forum/", wait_text=WORK_TITLE)
        self.assertIn(WORK_TITLE, body, "the published thread must be listed")
        self.assertNotIn(HIDDEN_THREAD_TITLE, body, "a moderator-hidden thread must not be listed")
        self.assertEqual(self.js_errors, [])

    def test_admin_topic_list_offers_no_restore_on_a_deleted_thread(self):
        response = self.page.request.post(
            self.base + "/api/auth/login",
            data={"account": "br_admin", "password": "password-admin"},
            headers={"Origin": "http://trusted.test"},
        )
        self.assertEqual(response.status, 200, response.text())
        self.page.goto(self.base + "/admin.html", wait_until="networkidle", timeout=20000)
        self.page.locator('[data-nav-mod="governance"]').first.click()
        self.page.locator('[data-subtab="governance:topics_list"]').first.click()
        self.page.wait_for_function(
            "t => document.body.innerText.includes(t)", arg=DELETED_THREAD_TITLE, timeout=15000
        )
        deleted_id = self.deleted["topicId"]
        self.assertEqual(
            self.page.locator(f'[data-topic-act="publish"][data-topic-id="{deleted_id}"]').count(), 0,
            "a deleted thread must not offer a restore button",
        )
        # The hidden (not deleted) thread still offers it, so the check above
        # is not passing just because the list did not render buttons.
        hidden_id = self.hidden["topicId"]
        self.assertEqual(
            self.page.locator(f'[data-topic-act="publish"][data-topic-id="{hidden_id}"]').count(), 1
        )
        self.assertIn("已删除，不可恢复", self.page.inner_text("body"))
        self.assertEqual(self.js_errors, [], f"JS errors on admin: {self.js_errors}")

    def test_hidden_thread_page_does_not_show_the_thread(self):
        body = self._load(f"/forum/?view=topic&id={self.hidden['topicId']}")
        self.assertNotIn(HIDDEN_THREAD_TITLE, body)
        self.assertEqual(self.js_errors, [], f"JS errors on a hidden thread: {self.js_errors}")


if __name__ == "__main__":
    unittest.main()
