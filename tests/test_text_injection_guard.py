import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.runtime_policy import (
    sanitize_html,
    sanitize_media_url,
    sanitize_plain_text,
    sanitize_rich_html,
    sanitize_submission_body,
)
from backend.server import HandrawRequestHandler, init_database, SESSION_COOKIE_NAME
from backend.services import register_user, publish_forum_topic_post, publish_forum_reply_post


class TextInjectionUnitTests(unittest.TestCase):
    def test_sanitize_plain_text_strips_scripts_and_tags(self):
        # 1. Script tag and content completely dropped
        self.assertEqual(sanitize_plain_text("<script>alert(1)</script>"), "")
        self.assertEqual(sanitize_plain_text("前缀<script>alert(1)</script>后缀"), "前缀后缀")

        # 2. Img onerror stripped
        self.assertEqual(sanitize_plain_text("<img src=x onerror=alert(1)>"), "")
        self.assertEqual(sanitize_plain_text("好图！<img src=x onerror=alert(1)> 赞！"), "好图！ 赞！")

        # 3. Anchor tag stripped, inner text preserved
        self.assertEqual(sanitize_plain_text('<a href="javascript:alert(1)">点我</a>'), "点我")

        # 4. Svg with onload dropped
        self.assertEqual(sanitize_plain_text('<svg onload="alert(1)"><circle cx="1" cy="1"/></svg>'), "")

        # 5. Nested bypass attempt
        self.assertEqual(sanitize_plain_text("<<SCRIPT>script>alert(1)<</SCRIPT>/script>"), "")

        # 6. Unclosed malicious tag stripped
        self.assertEqual(sanitize_plain_text("<img src=x onerror=alert(1)"), "")
        self.assertEqual(sanitize_plain_text("<script src='http://evil.com/xss.js'"), "")

        # 7. Null bytes and control characters stripped
        self.assertEqual(sanitize_plain_text("Hello\x00World\x1b!"), "HelloWorld!")

        # 8. Normal plain text with comparison operators preserved
        self.assertEqual(sanitize_plain_text("1 < 2 且 3 > 2"), "1 < 2 且 3 > 2")

        # 9. Markdown formatting preserved
        md = "> 引用内容\n* 列表项\n**粗体**"
        self.assertEqual(sanitize_plain_text(md), md)

        # 10. Length bounding
        long_str = "x" * 5000
        self.assertEqual(len(sanitize_plain_text(long_str, max_chars=100)), 100)

    def test_sanitize_media_url(self):
        # Dangerous protocols rejected
        self.assertEqual(sanitize_media_url("javascript:alert(1)"), "")
        self.assertEqual(sanitize_media_url("  javascript:alert(1)  "), "")
        self.assertEqual(sanitize_media_url("data:text/html,<script>alert(1)</script>"), "")
        self.assertEqual(sanitize_media_url("vbscript:msgbox(1)"), "")
        self.assertEqual(sanitize_media_url("file:///etc/passwd"), "")

        # Protocol-relative and backslash injection rejected
        self.assertEqual(sanitize_media_url("//evil.com/xss.js"), "")
        self.assertEqual(sanitize_media_url("/\\evil.com/xss.js"), "")
        self.assertEqual(sanitize_media_url("/images/..\\..\\evil.png"), "")

        # Safe local and remote URLs allowed
        self.assertEqual(sanitize_media_url("/uploads/sample.png"), "/uploads/sample.png")
        self.assertEqual(sanitize_media_url("/demo/assets/hero.png"), "/demo/assets/hero.png")
        self.assertEqual(sanitize_media_url("/assets/theme.css"), "/assets/theme.css")
        self.assertEqual(sanitize_media_url("https://example.com/photo.webp"), "https://example.com/photo.webp")
        self.assertEqual(sanitize_media_url("http://example.com/photo.webp"), "http://example.com/photo.webp")

        # Control characters rejected
        self.assertEqual(sanitize_media_url("/uploads/\x00evil.png"), "")

        # Data URL only allowed with allow_data=True and valid image base64
        self.assertEqual(sanitize_media_url("data:image/png;base64,invalid", allow_data=False), "")
        png_1x1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        self.assertEqual(sanitize_media_url(png_1x1, allow_data=False), "")
        self.assertEqual(sanitize_media_url(png_1x1, allow_data=True), png_1x1)

    def test_sanitize_rich_html(self):
        # 1. Scripts, styles, iframes dropped with contents
        html_input = '<p>正文段落<script>alert("xss")</script><style>body{color:red}</style>结束</p>'
        cleaned = sanitize_rich_html(html_input)
        self.assertNotIn("alert", cleaned)
        self.assertNotIn("script", cleaned.lower())
        self.assertNotIn("style", cleaned.lower())
        self.assertIn("<p>正文段落结束</p>", cleaned)

        # 2. Event handlers on allowed tags stripped
        img_input = '<img src="/uploads/pic.png" onerror="alert(1)" onload="alert(2)" alt="测试">'
        cleaned_img = sanitize_rich_html(img_input)
        self.assertNotIn("onerror", cleaned_img)
        self.assertNotIn("onload", cleaned_img)
        self.assertIn('src="/uploads/pic.png"', cleaned_img)
        self.assertIn('alt="测试"', cleaned_img)

        # 3. Bad href in link: <a> omitted, text preserved
        link_input = '<p><a href="javascript:alert(1)">危险链接</a></p>'
        cleaned_link = sanitize_rich_html(link_input)
        self.assertNotIn("javascript:", cleaned_link)
        self.assertNotIn("<a", cleaned_link)
        self.assertIn("<p>危险链接</p>", cleaned_link)

        # 4. Safe link preserved with noopener
        safe_link = '<p><a href="https://handraw-style.com/t/123" target="_blank">安全链接</a></p>'
        cleaned_safe = sanitize_rich_html(safe_link)
        self.assertIn('href="https://handraw-style.com/t/123"', cleaned_safe)
        self.assertIn('rel="noopener noreferrer"', cleaned_safe)

        # 5. Unclosed tags auto-balanced
        unclosed = "<div><p>未闭合内容"
        cleaned_unclosed = sanitize_rich_html(unclosed)
        self.assertEqual(cleaned_unclosed, "<div><p>未闭合内容</p></div>")


class TextInjectionIntegrationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "inject_test.db"
        self.uploads_dir = root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir = root / "generated"
        self.generated_dir.mkdir(parents=True, exist_ok=True)

        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(self.uploads_dir),
                "HANDRAW_GENERATED_DIR": str(self.generated_dir),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            },
        )
        self.env.start()
        self.db = init_database(self.db_path)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        # Seed test user
        self.user, self.token = register_user(self.db, "guard_tester", "Pass1234!")

        # Seed test topic
        topic_res = publish_forum_topic_post(
            self.db,
            self.user,
            {
                "title": "注入测试公开讨论帖",
                "body": "这是一篇用于测试文字注入加固的帖子正文。",
                "category": "experience",
            }
        )
        self.topic_id = topic_res["topicId"]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, cookie: str | None = None):
        req_headers = {"Accept": "application/json", "Origin": "http://trusted.test"}
        if cookie:
            req_headers["Cookie"] = f"{SESSION_COOKIE_NAME}={cookie}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                err_data = json.loads(error.read().decode("utf-8"))
            except Exception:
                err_data = {}
            return error.code, err_data

    def test_reply_injection_stripped(self):
        tid = self.topic_id
        # 1. Pure malicious payload stripped to empty -> rejected with 400
        code, res = self.request(
            "POST",
            f"/api/forum/topics/{tid}/replies",
            {"text": "<img src=x onerror=alert(1)><script>alert(2)</script>"},
            cookie=self.token,
        )
        self.assertEqual(code, 400)
        self.assertIn("请输入回复内容", res.get("error", ""))

        # 2. Mixed content: HTML tags stripped, clean text saved
        code, res = self.request(
            "POST",
            f"/api/posts/{tid}/replies",
            {"text": "非常精彩的分享！<script>alert('xss')</script><img src=x onerror=alert(1)>期待后续教程！"},
            cookie=self.token,
        )
        self.assertEqual(code, 200)
        self.assertTrue(res.get("ok"))

        # Verify database record
        row = self.db.get_conn().execute(
            "SELECT * FROM forum_replies WHERE topic_id = ? ORDER BY id DESC LIMIT 1",
            (tid,),
        ).fetchone()
        self.assertIsNotNone(row)
        saved_text = row["text"]
        self.assertNotIn("<script", saved_text)
        self.assertNotIn("alert", saved_text)
        self.assertNotIn("<img", saved_text)
        self.assertEqual(saved_text, "非常精彩的分享！期待后续教程！")

        # Verify GET /api/posts/{id}/replies returns clean text
        code, get_res = self.request("GET", f"/api/posts/{tid}/replies?limit=10")
        self.assertEqual(code, 200)
        items = get_res.get("items", get_res.get("replies", []))
        self.assertTrue(any("非常精彩的分享！期待后续教程！" in r["text"] for r in items))
        self.assertFalse(any("<script>" in r["text"] for r in items))

    def test_topic_title_and_body_injection_sanitized(self):
        # Topic with malicious title and body
        payload = {
            "title": "<script>alert(1)</script>实战心得与调优技巧",
            "body": "<p>正文第一段</p><script>alert('body_xss')</script><img src=x onerror=alert(1)><p>第二段</p>",
            "category": "experience",
        }
        code, res = self.request("POST", "/api/forum/topics", payload, cookie=self.token)
        self.assertEqual(code, 200)
        topic_id = res.get("topicId")
        self.assertIsNotNone(topic_id)

        # Check DB
        t_row = self.db.get_conn().execute("SELECT title, summary FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
        self.assertEqual(t_row["title"], "实战心得与调优技巧")
        self.assertNotIn("script", t_row["summary"].lower())
        self.assertNotIn("onerror", t_row["summary"].lower())
        self.assertIn("正文第一段", t_row["summary"])

    def test_work_media_url_validation(self):
        # Work with malicious javascript: image URL
        payload = {
            "title": "测试作品标题",
            "notes": "这是一篇用于测试安全防护的创作说明文字记录",
            "prompt": "高山流水，水墨写意",
            "images": ["javascript:alert(1)"],
        }
        code, res = self.request("POST", "/api/works", payload, cookie=self.token)
        self.assertEqual(code, 400)
        self.assertIn("image_required", res.get("code", ""))

        # Work with valid local image URL succeeds
        payload["images"] = ["/demo/assets/hero.png"]
        code, res = self.request("POST", "/api/works", payload, cookie=self.token)
        self.assertEqual(code, 200)
        self.assertTrue(res.get("ok"))

    def test_profile_update_sanitized(self):
        payload = {
            "displayName": "<script>alert(1)</script>安全绘师",
            "bio": "<img src=x onerror=alert(1)>专注于手绘与视觉设计",
        }
        code, res = self.request("POST", "/api/auth/profile", payload, cookie=self.token)
        self.assertEqual(code, 200)

        # Check DB
        u_row = self.db.get_conn().execute("SELECT display_name, bio FROM users WHERE id = ?", (self.user["id"],)).fetchone()
        self.assertEqual(u_row["display_name"], "安全绘师")
        self.assertEqual(u_row["bio"], "专注于手绘与视觉设计")


if __name__ == "__main__":
    unittest.main()


def test_prose_angle_brackets_survive():
    """A reply that says "x < y" must not lose characters to tag stripping."""
    assert sanitize_plain_text("x < y") == "x < y"
    assert sanitize_plain_text("3<4 且 5>2") == "3<4 且 5>2"


def test_form_tags_go_but_their_words_stay():
    """<form> is not allowed, but the author's sentence inside it is theirs."""
    assert sanitize_html("<form action=/x>正文</form>后面") == "正文后面"
    assert sanitize_html("<noscript>文字</noscript>后面") == "文字后面"


def test_script_contents_are_still_dropped_entirely():
    assert sanitize_html("<script>alert(1)</script>正文") == "正文"


def test_internal_link_with_query_survives():
    out = sanitize_html('<a href="/forum/?view=topic&id=t1">帖子</a>')
    assert "/forum/?view=topic" in out and "帖子" in out
