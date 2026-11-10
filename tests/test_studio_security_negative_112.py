"""Issue #112 M0 security-negative HTTP contract (real handler, no paid gateway).

Two authenticated users and an anonymous caller exercise private Article,
Project, V3 Run and MediaRef authorization. This is CI defense in depth,
not a deployment penetration test or a server-log confidentiality audit.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.generation_v3 import ensure_run
from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.services import register_user


PRIVATE_ARTICLE = "QA112_PRIVATE_ARTICLE_SENTINEL_NOT_PUBLIC"
PROJECT = "qa112-private-article"
RUN_EXTERNAL = "qa112-owner-run"


class StudioSecurityNegative112(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "privacy-112.sqlite"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_AI_CONFIG": str(root / "no-provider.json"),
            "HANDRAW_IMAGE_CONFIG": str(root / "no-image-provider.json"),
        })
        self.env.start()
        self.db = init_database(root / "privacy-112.sqlite")
        self.alice, at = register_user(self.db, "qa112_priv_alice", "Pass12345!")
        self.bob, bt = register_user(self.db, "qa112_priv_bob", "Pass12345!")
        self.alice_cookie = SESSION_COOKIE_NAME + "=" + at
        self.bob_cookie = SESSION_COOKIE_NAME + "=" + bt
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.db = self.db
        self.httpd.channel_role = "main"
        self.httpd.allow_demo_routes = True
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, method, route, body=None, cookie=None):
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Origin": "http://trusted.test", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(self.base + route, method=method,
                                     data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def create_article(self):
        body = {
            "projectId": PROJECT, "kind": "article", "authority": "article",
            "title": "仅作者可见的内部文章", "idempotencyKey": "qa112-article-once",
            "draft": {
                "article": {"documentId": "qa112-doc", "revision": 1,
                            "markdown": "# 内部草稿\\n\\n" + PRIVATE_ARTICLE,
                            "anchors": [{"anchorId": "qa112-cover"}]},
                "plan": {"kind": "article", "planId": "qa112-plan", "revision": 1,
                         "documentId": "qa112-doc", "documentRevision": 1,
                         "slots": [{"slotId": "qa112-slot",
                                    "anchorId": "qa112-cover"}]},
                "activeView": "simple",
            },
        }
        status, created = self.request("POST", "/api/studio/projects", body,
                                       self.alice_cookie)
        self.assertEqual(status, 200, created)

    def assert_denied_without_leak(self, outcome, status_options=(401, 403, 404)):
        status, body = outcome
        self.assertIn(status, status_options, body)
        encoded = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(PRIVATE_ARTICLE, encoded)
        self.assertNotIn("仅作者可见的内部文章", encoded)
        self.assertNotIn("qa112-doc", encoded)
        self.assertNotIn("currentRevision", body,
                         "Unauthorized 409 must not reveal author's CAS revision")

    def test_article_project_run_cross_owner_read_patch_copy_are_denied(self):
        self.create_article()
        private_route = "/api/studio/projects/" + PROJECT
        owned_status, owned = self.request("GET", private_route,
                                          cookie=self.alice_cookie)
        self.assertEqual(owned_status, 200, owned)
        self.assertIn(PRIVATE_ARTICLE, json.dumps(owned, ensure_ascii=False))
        self.assert_denied_without_leak(self.request(
            "GET", private_route, cookie=self.bob_cookie), (404,))
        self.assert_denied_without_leak(self.request(
            "GET", private_route), (401,))
        self.assert_denied_without_leak(self.request(
            "PATCH", private_route + "/draft", cookie=self.bob_cookie, body={
                "baseRevision": 1, "idempotencyKey": "qa112-forged-patch",
                "patch": {"op": "set", "path": "/activeView", "value": "canvas"},
            }), (404,))
        self.assert_denied_without_leak(self.request(
            "POST", private_route + "/copy", cookie=self.bob_cookie, body={
                "newProjectId": "qa112-stolen-copy",
                "idempotencyKey": "qa112-forged-copy",
            }), (404,))
        bob_status, listing = self.request("GET", "/api/studio/projects",
                                           cookie=self.bob_cookie)
        self.assertEqual(bob_status, 200, listing)
        self.assertNotIn(PROJECT, json.dumps(listing))
        self.assertNotIn(PRIVATE_ARTICLE, json.dumps(listing))
        self.assertEqual(self.request("GET", private_route,
                                      cookie=self.alice_cookie)[1]["project"]["revision"], 1)
        with self.db.transaction() as tx:
            run_id = ensure_run(tx, user_id=int(self.alice["id"]), source="web",
                                external_run_id=RUN_EXTERNAL, expected_count=3)
        self.assertEqual(self.request("GET", "/api/studio/runs/" + run_id,
                                       cookie=self.alice_cookie)[0], 200)
        self.assert_denied_without_leak(self.request(
            "GET", "/api/studio/runs/" + run_id, cookie=self.bob_cookie), (404,))
        self.assert_denied_without_leak(self.request(
            "GET", "/api/studio/runs/" + run_id), (401,))

    def test_cross_owner_private_media_ref_never_accepted_by_project_http(self):
        with self.db.transaction() as tx:
            for owner, uid in ((self.alice, "qa112-alice-upload"),
                               (self.bob, "qa112-bob-upload")):
                tx.execute(
                    """INSERT INTO user_uploads
                    (id,user_id,cat,name_zh,image_url,created_at,asset_uid)
                    VALUES (?,?,?,'QA','/private/never-public.webp','2026-11-08',?)""",
                    ("internal-" + uid, owner["id"], "scenes", uid),
                )
        def payload(ident, pid):
            return {
                "projectId": pid, "idempotencyKey": "once-" + pid,
                "kind": "image", "authority": "spec", "title": "私有场景",
                "draft": {"creationSpec": {
                    "referenceMedia": [{"mediaId": ident, "role": "scene"}]}},
            }
        ok_status, ok = self.request("POST", "/api/studio/projects",
                                     payload("qa112-alice-upload", "qa112-owned-reference"),
                                     self.alice_cookie)
        self.assertEqual(ok_status, 200, ok)
        for ident in ("qa112-bob-upload", "qa112-nonexistent-upload"):
            denied = self.request("POST", "/api/studio/projects",
                                  payload(ident, "qa112-denied-" + ident),
                                  self.alice_cookie)
            self.assert_denied_without_leak(denied, (403,))
        status, owned = self.request("GET",
                                     "/api/studio/projects/qa112-owned-reference",
                                     cookie=self.alice_cookie)
        self.assertEqual(status, 200, owned)
        self.assertEqual(owned["project"]["revision"], 1)
        self.assertEqual(
            self.db.get_conn().execute(
                "SELECT COUNT(*) FROM studio_projects WHERE user_id=?",
                (int(self.alice["id"]),)).fetchone()[0], 1,
            "Failed media authorization must be transactional")

        self.assert_denied_without_leak(self.request(
            "GET", "/api/studio/projects/qa112-owned-reference",
            cookie=self.bob_cookie), (404,))


if __name__ == "__main__":
    unittest.main()
