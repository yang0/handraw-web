"""HTTP contract tests for Handraw Skill/Web v1.

Exercises the same payloads and Bearer-token scopes as the public Skill
branch, with isolated DB/media directories and no production access.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.db import utc_now_iso
from backend.server import HandrawRequestHandler, init_database
from backend.services import register_user


def image_payload():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), (210, 160, 80)).save(buf, format="PNG")
    data = buf.getvalue()
    return {
        "name": "skill.png", "sha256": hashlib.sha256(data).hexdigest(),
        "dataUrl": "data:image/png;base64," + base64.b64encode(data).decode(),
    }


class SkillCloudV1Tests(unittest.TestCase):
    def setUp(self):
        self.root_dir = tempfile.TemporaryDirectory()
        root = Path(self.root_dir.name)
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "skill.db"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
        })
        self.env.start()
        self.db = init_database(root / "skill.db")
        self.alice, _ = register_user(self.db, "skill_alice", "Password123")
        self.bob, _ = register_user(self.db, "skill_bob", "Password123")
        self.library_token = self.token(self.alice, ["library"])
        self.publish_token = self.token(self.alice, ["publish"])
        self.both_token = self.token(self.alice, ["library", "publish"])
        self.bob_token = self.token(self.bob, ["library", "publish"])
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.db = self.db
        self.httpd.channel_role = "main"
        self.httpd.allow_demo_routes = True
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.root_dir.cleanup()

    def token(self, user, scopes):
        secret = "hwt_test_" + uuid.uuid4().hex
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO api_tokens
                (id,user_id,name,scopes,token_hash,created_at,last_used_at,revoked_at)
                VALUES(?,?,?,?,?,?,'','')""",
                ("tok_" + uuid.uuid4().hex, user["id"], "Skill Test", json.dumps(scopes),
                 hashlib.sha256(secret.encode()).hexdigest(), utc_now_iso()),
            )
        return secret

    def req(self, method, path, body=None, token=None, raw=False):
        headers = {"Origin": "http://trusted.test"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = response.read()
                return response.status, payload if raw else json.loads(payload)
        except urllib.error.HTTPError as error:
            payload = error.read()
            return error.code, payload if raw else json.loads(payload)

    def resource(self, rid, name="我的独立画风", **extra):
        return {"id": rid, "kind": "style", "name": name,
                "definition": {"zh": "水彩材质与柔和光影", "en": "Watercolor texture and soft lighting"},
                "license": "个人使用", "examples": ["主题一"], "version": "1.0.0",
                "visibility": "private", "schemaVersion": 1, **extra}

    def test_resource_lifecycle_and_revision_conflicts(self):
        rid = str(uuid.uuid4())
        path = "/api/v1/me/resources/" + rid
        status, created = self.req("PUT", path, self.resource(rid), self.library_token)
        self.assertEqual(status, 200, created)
        self.assertEqual(created["resource"]["revision"], 1)
        self.assertEqual(created["resource"]["visibility"], "private")
        status, listing = self.req("GET", "/api/v1/me/resources?limit=2", token=self.library_token)
        self.assertEqual(status, 200, listing)
        self.assertEqual(listing["items"][0]["id"], rid)
        status, denied = self.req("PUT", path,
            self.resource(rid, name="冲突", baseRevision=0), self.library_token)
        self.assertEqual(status, 409, denied)
        self.assertEqual(denied["code"], "conflict")
        status, updated = self.req("PUT", path,
            self.resource(rid, name="新名称", baseRevision=1), self.library_token)
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["resource"]["revision"], 2)
        self.assertEqual(updated["resource"]["name"], "新名称")
        status, forbidden = self.req("GET", "/api/v1/resources/"+rid+"/download", token=self.bob_token)
        self.assertEqual(status, 404, forbidden)
        status, downloaded = self.req("GET", "/api/v1/resources/"+rid+"/download", token=self.library_token)
        self.assertEqual(status, 200, downloaded)
        self.assertEqual(downloaded["resource"]["definition"]["zh"], "水彩材质与柔和光影")

    def test_resource_tombstones_and_incremental_cursor(self):
        rid = str(uuid.uuid4())
        url = "/api/v1/me/resources/" + rid
        self.assertEqual(self.req("PUT", url, self.resource(rid), self.library_token)[0], 200)
        status, current = self.req("GET", "/api/v1/me/resources", token=self.library_token)
        cursor = current["nextCursor"]
        status, deleted = self.req("DELETE", url + "?baseRevision=1", token=self.library_token)
        self.assertEqual(status, 200, deleted)
        self.assertTrue(deleted["resource"]["deletedAt"])
        status, empty = self.req("GET", "/api/v1/me/resources", token=self.library_token)
        self.assertEqual(empty["items"], [])
        status, delta = self.req("GET", "/api/v1/me/resources?since="+cursor, token=self.library_token)
        self.assertEqual(status, 200, delta)
        self.assertEqual(delta["items"][0]["id"], rid)
        self.assertTrue(delta["items"][0]["deletedAt"])
        self.assertNotIn("definition", delta["items"][0])

    def test_scope_and_private_visibility_enforced(self):
        rid = str(uuid.uuid4())
        path = "/api/v1/me/resources/" + rid
        self.assertEqual(self.req("PUT", path, self.resource(rid), self.publish_token)[0], 403)
        self.assertEqual(self.req("PUT", path, self.resource(rid, visibility="public"), self.library_token)[0], 400)
        self.assertEqual(self.req("GET", "/api/v1/me/resources", token=self.publish_token)[0], 403)
        self.assertEqual(self.req("PUT", path, self.resource(rid), self.both_token)[0], 200)
        self.assertEqual(self.req("PUT", path, self.resource(rid), self.bob_token)[0], 404)

    def test_history_import_is_private_idempotent_and_owner_only(self):
        rid = str(uuid.uuid4())
        payload = {"externalRunId": rid, "originClient": "skill",
                   "visibility": "private", "status": "success",
                   "originalRequest": "请生成私有商业项目参考图",
                   "images": [image_payload()], "requestId": "skill-history-" + rid}
        status, saved = self.req("POST", "/api/v1/me/generations", payload, self.library_token)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["visibility"], "private")
        self.assertTrue(saved["id"])
        status, repeated = self.req("POST", "/api/v1/me/generations", payload, self.library_token)
        self.assertEqual(status, 200, repeated)
        self.assertEqual(saved["id"], repeated["id"])
        self.assertTrue(repeated["deduped"])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM skill_generation_runs WHERE user_id=?",
            (self.alice["id"],)).fetchone()[0], 1)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works WHERE author_username='skill_alice'").fetchone()[0], 0)
        status, owner = self.req("GET", "/api/v1/me/generations", token=self.library_token)
        self.assertEqual(status, 200, owner)
        self.assertEqual(owner["items"][0]["originalRequest"], payload["originalRequest"])
        img_url = owner["items"][0]["images"][0]["url"]
        self.assertEqual(self.req("GET", img_url, token=self.library_token, raw=True)[0], 200)
        self.assertNotEqual(self.req("GET", img_url, raw=True)[0], 200)
        self.assertNotEqual(self.req("GET", img_url, token=self.bob_token, raw=True)[0], 200)
        status, other = self.req("GET", "/api/v1/me/generations", token=self.bob_token)
        self.assertEqual(status, 200, other)
        self.assertEqual(other["items"], [])
        payload["originalRequest"] = "意外覆盖"
        self.assertEqual(self.req("POST", "/api/v1/me/generations", payload, self.library_token)[0], 409)

    def test_history_refuses_public_and_bad_hash(self):
        rid = str(uuid.uuid4())
        item = image_payload()
        data = {"externalRunId": rid, "originClient": "skill", "status": "success",
                "visibility": "public", "originalRequest": "private", "images": [item]}
        self.assertEqual(self.req("POST", "/api/v1/me/generations", data, self.library_token)[0], 400)
        data["visibility"] = "private"
        data["images"][0]["sha256"] = "0" * 64
        self.assertEqual(self.req("POST", "/api/v1/me/generations", data, self.library_token)[0], 400)
        self.assertEqual(self.req("POST", "/api/v1/me/generations", data, self.publish_token)[0], 403)

    def test_notification_owner_isolation_and_collection_access(self):
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
                   VALUES(?, 'comment','仅 Alice 可见','work','work_test',?)""",
                (self.alice["id"], utc_now_iso()))
        status, a = self.req("GET", "/api/v1/me/notifications", token=self.library_token)
        self.assertEqual(status, 200, a)
        self.assertTrue(any(x["title"] == "仅 Alice 可见" for x in a["items"]))
        status, b = self.req("GET", "/api/v1/me/notifications", token=self.bob_token)
        self.assertEqual(status, 200, b)
        self.assertFalse(b["items"])
        status, coll = self.req("GET", "/api/v1/me/collection-items", token=self.library_token)
        self.assertEqual(status, 200, coll)
        self.assertIn("items", coll)

    def test_published_work_likes_and_comments_share_domain(self):
        wid = "work_skill_" + uuid.uuid4().hex
        now = utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO works
                   (id,author_username,author_name,title,images_json,prompt,
                    status,published_at_ms,created_at,updated_at)
                   VALUES(?,?,?,?,?,'作品的公开说明','published',1700000000000,?,?)""",
                (wid, self.bob["username"], self.bob["display_name"],
                 "Skill 跨端互动测试", '["/images/example.png"]', now, now))
        status, liked = self.req("POST", "/api/v1/works/"+wid+"/likes",
                                 {"liked": True}, self.publish_token)
        self.assertEqual(status, 200, liked)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT likes FROM works WHERE id=?", (wid,)).fetchone()[0], 1)
        self.req("POST", "/api/v1/works/"+wid+"/likes", {"liked": True}, self.publish_token)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT likes FROM works WHERE id=?", (wid,)).fetchone()[0], 1)
        status, comment = self.req("POST", "/api/v1/works/"+wid+"/comments",
            {"text": "很棒的作品！", "requestId": "skill-comment-" + uuid.uuid4().hex}, self.publish_token)
        self.assertEqual(status, 200, comment)
        status, read = self.req("GET", "/api/v1/works/"+wid+"/comments")
        self.assertEqual(status, 200, read)
        self.assertTrue(isinstance(read["comments"], list))


if __name__ == "__main__":
    unittest.main()
