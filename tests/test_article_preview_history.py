"""Playwright browser test for Issue #63: article preview browser history navigation."""
from __future__ import annotations

import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.legacy_database import init_legacy_database
from backend import server as server_module
from backend.server import create_channel_server
from backend.services import register_user

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright  # type: ignore

    _HAS_PLAYWRIGHT = True
except Exception:  # pragma: no cover
    _HAS_PLAYWRIGHT = False


@unittest.skipUnless(_HAS_PLAYWRIGHT, "playwright not installed")
class ArticlePreviewHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls._env = patch.dict(
            os.environ,
            {
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_PRIVATE_STORAGE": cls.temp.name,
            },
        )
        cls._env.start()
        cls.db = init_legacy_database(Path(cls.temp.name) / "browser_studio.db")
        register_user(cls.db, "studio_author", "password-s")
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        try:
            cls._pw = sync_playwright().start()
            try:
                cls._browser = cls._pw.chromium.launch()
            except Exception:
                try:
                    cls._browser = cls._pw.chromium.launch(channel="chrome")
                except Exception:
                    cls._browser = cls._pw.chromium.launch(channel="msedge")
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
            self.skipTest("chromium/chrome/msedge not available")
        self.page = self._browser.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda exc: self.js_errors.append(str(exc)))

    def tearDown(self):
        if getattr(self, "page", None) is not None:
            self.page.close()

    def test_article_preview_back_and_forward_preserves_editor_draft(self):
        # 1. 打开编辑器
        self.page.goto(f"{self.base}/studio/?entry=article", wait_until="networkidle", timeout=20000)
        self.page.wait_for_selector("#art-editor-paper", timeout=15000)
        self.assertTrue(self.page.locator("#art-editor-paper").is_visible())

        # 2. 输入标题和一句正文
        test_title = "测试文章历史导航标题"
        test_content = "这是刚刚输入的一句深度测试正文"
        self.page.fill("#editor-title-inp", test_title)
        seg_ta = self.page.locator(".ic-art-seg-ta").first
        seg_ta.fill(test_content)

        # 3. 点「预览」
        preview_btn = self.page.locator("#editor-switch-preview, #editor-btn-toggle-preview").first
        preview_btn.click()
        self.page.wait_for_selector(".ic-article-preview-root", timeout=15000)
        self.assertTrue(self.page.locator(".ic-article-preview-root").is_visible())
        preview_text = self.page.inner_text(".ic-article-preview-root")
        self.assertIn(test_title, preview_text)
        self.assertIn(test_content, preview_text)

        # 4. 浏览器后退 -> page.go_back()
        self.page.go_back()
        self.page.wait_for_selector("#art-editor-paper", timeout=15000)

        # 断言：编辑器可见、预览不可见、刚输入的那句还在
        self.assertTrue(self.page.locator("#art-editor-paper").is_visible())
        self.assertEqual(self.page.locator(".ic-article-preview-root").count(), 0)
        self.assertEqual(self.page.input_value("#editor-title-inp"), test_title)
        self.assertEqual(self.page.locator(".ic-art-seg-ta").first.input_value(), test_content)

        # 5. 浏览器前进 -> page.go_forward() -> 回到预览
        self.page.go_forward()
        self.page.wait_for_selector(".ic-article-preview-root", timeout=15000)
        self.assertTrue(self.page.locator(".ic-article-preview-root").is_visible())
        self.assertEqual(self.page.locator("#art-editor-paper").count(), 0)
        preview_text_after = self.page.inner_text(".ic-article-preview-root")
        self.assertIn(test_title, preview_text_after)
        self.assertIn(test_content, preview_text_after)

        self.assertEqual(self.js_errors, [], f"Unexpected JS errors: {self.js_errors}")


if __name__ == "__main__":
    unittest.main()
