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

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright  # type: ignore

    _HAS_PLAYWRIGHT = True
except Exception:  # pragma: no cover
    _HAS_PLAYWRIGHT = False


@unittest.skipUnless(_HAS_PLAYWRIGHT, "playwright not installed")
class BrowserRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"})
        cls._env.start()
        cls.temp = TemporaryDirectory()
        cls.db = server_module.init_database(Path(cls.temp.name) / "browser.db")
        author, _ = register_user(cls.db, "br_author", "password-a")
        cls.work = publish_user_work(
            cls.db,
            author,
            {"title": WORK_TITLE, "prompt": WORK_PROMPT, "images": [IMG], "styles": ["FA-013"]},
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


if __name__ == "__main__":
    unittest.main()
