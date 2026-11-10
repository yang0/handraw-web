"""HTTP contract for Studio 2.0 Project APIs (real handler, no paid gateway)."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.services import register_user


class StudioProjectHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "studio-project-http.sqlite3"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
        })
        self.env.start()
        self.db = init_database(root / "studio-project-http.sqlite3")
        alice, token_a = register_user(self.db, "prjhttp_a", "Pass12345!")
        bob, token_b = register_user(self.db, "prjhttp_b", "Pass12345!")
        self.cookie_a = f"{SESSION_COOKIE_NAME}={token_a}"
        self.cookie_b = f"{SESSION_COOKIE_NAME}={token_b}"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.db = self.db
        self.httpd.channel_role = "main"
        self.httpd.allow_demo_routes = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def _request(self, method, path, body=None, cookie=None, origin="http://trusted.test"):
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "Origin": origin}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(self.base + path, data=payload,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            raw = err.read()
            return err.code, json.loads(raw) if raw else {}

    def test_project_create_list_patch_conflict_copy_and_acl(self):
        created = {"projectId": "http-project-a", "kind": "image",
                   "authority": "graph", "title": "我的画布",
                   "draft": {"graph": {"nodes": [{"id": "a"}], "edges": []}},
                   "idempotencyKey": "create-http-0001"}
        status, one = self._request("POST", "/api/studio/projects", created, self.cookie_a)
        self.assertEqual(status, 200, one)
        self.assertEqual(one["revision"], 1)
        status, listed = self._request("GET", "/api/studio/projects", cookie=self.cookie_a)
        self.assertEqual(status, 200, listed)
        self.assertEqual(len(listed["projects"]), 1)
        status, private = self._request("GET", "/api/studio/projects/http-project-a",
                                        cookie=self.cookie_b)
        self.assertEqual(status, 404, private)
        patch_body = {"baseRevision": 1, "idempotencyKey": "edit-http-0001",
                      "patch": {"op": "set", "path": "/graph/nodes",
                                "value": [{"id": "a"}, {"id": "b"}]}}
        status, patch_one = self._request(
            "PATCH", "/api/studio/projects/http-project-a/draft", patch_body, self.cookie_a)
        self.assertEqual(status, 200, patch_one)
        self.assertEqual(patch_one["revision"], 2)
        status, patch_again = self._request(
            "PATCH", "/api/studio/projects/http-project-a/draft", patch_body, self.cookie_a)
        self.assertEqual(status, 200, patch_again)
        self.assertTrue(patch_again["idempotentReplay"])
        status, conflict = self._request("PATCH", "/api/studio/projects/http-project-a/draft",
             {**patch_body, "idempotencyKey": "edit-http-0002"}, self.cookie_a)
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["currentRevision"], 2)
        status, original = self._request("GET", "/api/studio/projects/http-project-a",
                                         cookie=self.cookie_a)
        self.assertEqual(status, 200, original)
        self.assertEqual(len(original["project"]["draft"]["graph"]["nodes"]), 2)
        status, copy = self._request("POST", "/api/studio/projects/http-project-a/copy",
           {"newProjectId": "http-project-copy", "idempotencyKey": "copy-http-0001",
            "localDraft": {"graph": {"nodes": [{"id": "offline"}], "edges": []}}},
            self.cookie_a)
        self.assertEqual(status, 200, copy)
        self.assertEqual(copy["revision"], 1)
        status, copied = self._request("GET", "/api/studio/projects/http-project-copy",
                                       cookie=self.cookie_a)
        self.assertEqual(status, 200, copied)
        self.assertEqual(copied["project"]["draft"]["graph"]["nodes"][0]["id"], "offline")

    def test_project_search_and_invalid_cursor_over_http(self):
        body = {"projectId": "http-search-project", "kind": "image",
                "authority": "graph", "idempotencyKey": "search-http-0001",
                "title": "秋日海报100%", "draft": {}}
        status, _ = self._request("POST", "/api/studio/projects", body, self.cookie_a)
        self.assertEqual(status, 200)
        status, hits = self._request(
            "GET", "/api/studio/projects?q=" + quote("秋日") + "&limit=5",
            cookie=self.cookie_a)
        self.assertEqual(status, 200, hits)
        self.assertEqual([p["id"] for p in hits["projects"]], ["http-search-project"])
        self.assertFalse(hits["hasMore"])
        status, missing = self._request(
            "GET", "/api/studio/projects?q=" + quote("不匹配"),
            cookie=self.cookie_a)
        self.assertEqual(status, 200, missing)
        self.assertEqual(missing["projects"], [])
        status, bad = self._request(
            "GET", "/api/studio/projects?cursor=bad%%&limit=5",
            cookie=self.cookie_a)
        self.assertEqual(status, 400, bad)
        self.assertEqual(bad["code"], "invalid_project_cursor")

    def test_project_write_requires_authenticated_same_origin(self):
        body = {"projectId": "http-project-auth", "kind": "image",
                "authority": "graph", "idempotencyKey": "create-auth-0001", "draft": {}}
        unauth, _ = self._request("POST", "/api/studio/projects", body)
        self.assertEqual(unauth, 401)
        forbidden, _ = self._request("POST", "/api/studio/projects", body,
                                      self.cookie_a, "https://evil.invalid")
        self.assertEqual(forbidden, 403)
        missing, _ = self._request("GET", "/api/studio/projects",
                                    cookie=self.cookie_b)
        self.assertEqual(missing, 200)


if __name__ == "__main__":
    unittest.main()
