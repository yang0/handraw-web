import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.legacy_database import Database
from tests.legacy_database import init_legacy_database
from backend.server import SESSION_COOKIE_NAME, HandrawRequestHandler
from backend.services import (
    ServiceError,
    delete_user_studio_article,
    get_studio_workspace,
    list_user_studio_articles,
    register_user,
    sync_user_studio_articles,
)


class ArticleDeleteServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "test_article_del.db"
        self.db = Database(self.db_path)
        self.db.migrate()

        self.user_alice, _ = register_user(self.db, "alice", "Secret123!", "alice@example.com", "Alice", "inv1")
        self.user_bob, _ = register_user(self.db, "bob", "Secret123!", "bob@example.com", "Bob", "inv2")

    def tearDown(self) -> None:
        self.db.close()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_delete_requires_valid_id(self) -> None:
        with self.assertRaises(ServiceError) as ctx:
            delete_user_studio_article(self.db, self.user_alice, "")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "article_id_required")

    def test_delete_nonexistent_returns_404(self) -> None:
        with self.assertRaises(ServiceError) as ctx:
            delete_user_studio_article(self.db, self.user_alice, "nonexistent_art_123")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, "article_not_found")

    def test_delete_someone_elses_article_returns_403(self) -> None:
        art_id = "art_alice_001"
        sync_user_studio_articles(
            self.db,
            self.user_alice,
            [{"id": art_id, "articleTitle": "Alice's Story", "markdown": "Content"}],
        )

        with self.assertRaises(ServiceError) as ctx:
            delete_user_studio_article(self.db, self.user_bob, art_id)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "article_forbidden")

        listed = list_user_studio_articles(self.db, self.user_alice)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["id"], art_id)

    def test_soft_delete_and_exclusion_from_lists_and_workspace(self) -> None:
        art_1 = "art_alice_001"
        art_2 = "art_alice_002"
        sync_user_studio_articles(
            self.db,
            self.user_alice,
            [
                {"id": art_1, "articleTitle": "First Post", "markdown": "Hello"},
                {"id": art_2, "articleTitle": "Second Post", "markdown": "World"},
            ],
        )

        ws_before = get_studio_workspace(self.db, self.user_alice)
        self.assertEqual(len(ws_before["articles"]), 2)
        list_before = list_user_studio_articles(self.db, self.user_alice)
        self.assertEqual(list_before["total"], 2)

        res = delete_user_studio_article(self.db, self.user_alice, art_1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["id"], art_1)
        self.assertTrue(res["deleted"])

        conn = self.db.get_conn()
        row = conn.execute("SELECT deleted_at FROM studio_articles WHERE id = ?", (art_1,)).fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(len(str(row["deleted_at"])) > 0)

        list_after = list_user_studio_articles(self.db, self.user_alice)
        self.assertEqual(list_after["total"], 1)
        self.assertEqual(list_after["items"][0]["id"], art_2)

        ws_after = get_studio_workspace(self.db, self.user_alice)
        self.assertEqual(len(ws_after["articles"]), 1)
        self.assertEqual(ws_after["articles"][0]["id"], art_2)

        with self.assertRaises(ServiceError) as ctx:
            delete_user_studio_article(self.db, self.user_alice, art_1)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, "article_not_found")

        sync_user_studio_articles(
            self.db,
            self.user_alice,
            [{"id": art_1, "articleTitle": "Resurrect Attempt", "markdown": "Back"}],
        )
        list_resurrect = list_user_studio_articles(self.db, self.user_alice)
        self.assertEqual(list_resurrect["total"], 1)
        self.assertEqual(list_resurrect["items"][0]["id"], art_2)


class ArticleDeleteHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "test_article_del_http.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            },
        )
        self.env.start()
        self.db = init_legacy_database(self.db_path)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        self.user_alice, token_alice = register_user(self.db, "alice", "Secret123!", "alice@example.com", "Alice")
        self.cookie_alice = f"{SESSION_COOKIE_NAME}={token_alice}"

        self.user_bob, token_bob = register_user(self.db, "bob", "Secret123!", "bob@example.com", "Bob")
        self.cookie_bob = f"{SESSION_COOKIE_NAME}={token_bob}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2.0)
        self.db.close()
        self.env.stop()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _req(self, method: str, path: str, payload: dict | None = None, cookie: str | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", "http://trusted.test")
        if cookie:
            req.add_header("Cookie", cookie)

        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def test_delete_endpoint_authentication_and_authorization(self) -> None:
        # Create article for Alice
        sync_user_studio_articles(
            self.db,
            self.user_alice,
            [{"id": "art_alice_http", "articleTitle": "Alice Story", "markdown": "Text"}],
        )

        # 1. Unauthenticated -> 401
        status, body = self._req("DELETE", "/api/studio/articles/art_alice_http")
        self.assertEqual(status, 401)
        self.assertFalse(body.get("ok"))

        # 2. Bob tries to delete Alice's article -> 403
        status, body = self._req("DELETE", "/api/studio/articles/art_alice_http", cookie=self.cookie_bob)
        self.assertEqual(status, 403)
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("code"), "article_forbidden")

        # 3. Alice deletes non-existent article -> 404
        status, body = self._req("DELETE", "/api/studio/articles/does_not_exist", cookie=self.cookie_alice)
        self.assertEqual(status, 404)
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("code"), "article_not_found")

        # 4. Alice deletes own article -> 200
        status, body = self._req("DELETE", "/api/studio/articles/art_alice_http", cookie=self.cookie_alice)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("id"), "art_alice_http")
        self.assertTrue(body.get("deleted"))

        # 5. Alice tries to delete again -> 404
        status, body = self._req("DELETE", "/api/studio/articles/art_alice_http", cookie=self.cookie_alice)
        self.assertEqual(status, 404)
        self.assertFalse(body.get("ok"))

    def test_post_delete_endpoints(self) -> None:
        sync_user_studio_articles(
            self.db,
            self.user_alice,
            [
                {"id": "art_post_1", "articleTitle": "Post 1", "markdown": "Text 1"},
                {"id": "art_post_2", "articleTitle": "Post 2", "markdown": "Text 2"},
            ],
        )

        # POST /api/studio/articles/delete
        status, body = self._req("POST", "/api/studio/articles/delete", {"id": "art_post_1"}, cookie=self.cookie_alice)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("id"), "art_post_1")

        # POST /api/studio/articles/<id>/delete
        status, body = self._req("POST", "/api/studio/articles/art_post_2/delete", cookie=self.cookie_alice)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("id"), "art_post_2")


if __name__ == "__main__":
    unittest.main()
