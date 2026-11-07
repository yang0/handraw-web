"""Skill/Web v1 contract tests: private by default, scoped, idempotent.

All data are disposable SQLite fixtures; no user or production resources.
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
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.server import HandrawRequestHandler, init_database
from backend.services import register_user, publish_user_work, ServiceError
from backend import skill_web_bridge as bridge


class SkillWebBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "test.db"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
        })
        env.start()
        self.addCleanup(env.stop)
        self.db = init_database(root / "test.db")
        self.addCleanup(self.db.close)
        self.owner, _ = register_user(self.db, "skill_owner", "Password123!", display_name="创作者")
        self.other, _ = register_user(self.db, "skill_other", "Password123!", display_name="另一位用户")

    def payload(self, uid=None, **changes):
        data = {
            "id": uid or str(uuid.uuid4()), "kind": "style", "name": "暖纸手绘",
            "definition": {"zh": "纸质肌理与细线描", "en": "Paper texture and fine ink lines"},
            "license": "仅供个人使用", "examples": ["主题验证 A"], "version": "1.0.0",
            "visibility": "private", "schemaVersion": 1,
        }
        data.update(changes)
        return data

    def test_resource_create_update_conflict_and_idempotence(self):
        body = self.payload()
        first = bridge.put_resource(self.db, self.owner, body["id"], body)
        self.assertEqual(first["resource"]["revision"], 1)
        self.assertEqual(first["resource"]["visibility"], "private")
        same = bridge.put_resource(self.db, self.owner, body["id"], {**body, "baseRevision": 1})
        self.assertTrue(same["unchanged"])
        self.assertEqual(same["resource"]["revision"], 1)
        changed = bridge.put_resource(self.db, self.owner, body["id"],
                                      {**body, "name": "木刻画风", "baseRevision": 1})
        self.assertEqual(changed["resource"]["revision"], 2)
        with self.assertRaises(ServiceError) as error:
            bridge.put_resource(self.db, self.owner, body["id"],
                                {**body, "name": "旧版本覆盖", "baseRevision": 1})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(error.exception.extra["current"]["name"], "木刻画风")

    def test_private_resource_is_owner_only(self):
        body = self.payload()
        bridge.put_resource(self.db, self.owner, body["id"], body)
        self.assertEqual(bridge.list_resources(self.db, self.other, {})["items"], [])
        with self.assertRaises(ServiceError) as error:
            bridge.put_resource(self.db, self.other, body["id"], body)
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ServiceError) as error:
            bridge.download_resource(self.db, self.other, body["id"])
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ServiceError) as error:
            bridge.put_resource(self.db, self.owner, body["id"], self.payload(body["id"], visibility="public"))
        self.assertEqual(error.exception.code, "private_only")

    def test_resources_incremental_cursor_and_tombstones(self):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for rid in ids:
            bridge.put_resource(self.db, self.owner, rid, self.payload(rid))
        first = bridge.list_resources(self.db, self.owner, {"limit": ["2"]})
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["hasMore"])
        nxt = bridge.list_resources(self.db, self.owner,
                                    {"limit": ["2"], "since": [first["nextCursor"]]})
        self.assertEqual(len(nxt["items"]), 1)
        tombstone = bridge.delete_resource(self.db, self.owner, ids[0], "1")
        self.assertIsNotNone(tombstone["resource"]["deletedAt"])
        recent = bridge.list_resources(self.db, self.owner,
                                       {"since": [nxt["nextCursor"]]})
        self.assertEqual(len(recent["items"]), 1)
        self.assertEqual(recent["items"][0]["id"], ids[0])
        self.assertIsNotNone(recent["items"][0]["deletedAt"])

    def test_rollout_flag_makes_new_website_history_private_without_rewriting_legacy(self):
        from backend.services import record_user_studio_history
        with patch.dict(os.environ, {"HANDRAW_PRIVATE_GENERATION_HISTORY_V1": "1"}):
            record_user_studio_history(self.db, self.owner, {
                "id": "web_hist_private_flag", "tabTitle": "本地记录",
                "mode": "graphic-text", "kind": "single",
                "items": [{"imageUrl": "/images/individual/FA/FA-013.webp"}],
            })
        row=self.db.get_conn().execute(
            "SELECT visibility FROM studio_generations WHERE id='web_hist_private_flag'"
        ).fetchone()
        self.assertEqual(row["visibility"], "private")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_works WHERE generation_id='web_hist_private_flag'"
        ).fetchone()[0],0)
        own=bridge.list_history(self.db,self.owner,{})
        self.assertTrue(any(r["id"]=="web_hist_private_flag" and r["canPublish"] for r in own["items"]))

    def test_history_private_idempotent_and_not_work(self):
        rid = str(uuid.uuid4())
        image = b"fixture-image"
        data = {"externalRunId": rid, "originClient": "skill", "visibility": "private",
                "status": "success", "requestId": "skill-history-" + rid,
                "originalRequest": "用户最初的创作要求",
                "images": [{"name": "image.png", "sha256": hashlib.sha256(image).hexdigest(),
                             "dataUrl": "data:image/png;base64," +
                             base64.b64encode(image).decode("ascii")}]}
        saves = []
        def save_stub(db, user, data_url, name_zh, cat):
            self.assertEqual(cat, "skill_history")
            saves.append(data_url)
            return {"url": "/uploads/private-" + str(len(saves)) + ".png"}
        before = self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        first = bridge.import_history(self.db, self.owner, data, save_stub)
        repeat = bridge.import_history(self.db, self.owner, data, save_stub)
        self.assertEqual(first["id"], repeat["id"])
        self.assertTrue(repeat["deduped"])
        self.assertEqual(len(saves), 1)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0], before)
        own = bridge.list_history(self.db, self.owner, {})
        self.assertTrue(any(x["id"] == first["id"] and x["visibility"] == "private"
                            for x in own["items"]))
        self.assertFalse(any(x["id"] == first["id"] for x in
                             bridge.list_history(self.db, self.other, {})["items"]))
        with self.assertRaises(ServiceError) as error:
            bridge.import_history(self.db, self.owner, {**data, "originalRequest": "被篡改"}, save_stub)
        self.assertEqual(error.exception.status, 409)

    def test_history_upload_resumes_after_interruption_without_duplicate_media(self):
        rid=str(uuid.uuid4())
        a,b=b"image-one",b"image-two"
        images=[{"name":name,"sha256":hashlib.sha256(blob).hexdigest(),
                 "dataUrl":"data:image/png;base64,"+base64.b64encode(blob).decode()}
                for name,blob in (("one.png",a),("two.png",b))]
        payload={"externalRunId":rid,"originClient":"skill","visibility":"private",
                 "status":"success","requestId":"skill-history-"+rid,
                 "originalRequest":"多图片批量任务", "images":images}
        saved=[]
        def failing_store(db,user,data_url,name_zh,cat):
            if len(saved)==1:
                raise RuntimeError("temporary image upload failure")
            saved.append(data_url)
            return {"url":"/uploads/saved-one.png"}
        with self.assertRaises(RuntimeError):
            bridge.import_history(self.db,self.owner,payload,failing_store)
        row=self.db.get_conn().execute(
            "SELECT status,images_json FROM skill_generation_runs WHERE user_id=? AND external_run_id=?",
            (self.owner["id"],rid)).fetchone()
        self.assertEqual(row["status"],"uploading")
        self.assertEqual(len(json.loads(row["images_json"])),1)
        self.assertFalse(any(item["externalRunId"]==rid for item in
                             bridge.list_history(self.db,self.owner,{})["items"]))
        def resume_store(db,user,data_url,name_zh,cat):
            self.assertEqual(data_url,images[1]["dataUrl"])
            saved.append(data_url)
            return {"url":"/uploads/saved-two.png"}
        completed=bridge.import_history(self.db,self.owner,payload,resume_store)
        self.assertEqual(completed["visibility"],"private")
        self.assertEqual(len(saved),2)
        self.assertTrue(bridge.import_history(self.db,self.owner,payload,resume_store)["deduped"])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM skill_generation_runs WHERE user_id=? AND external_run_id=?",
            (self.owner["id"],rid)).fetchone()[0],1)

    def test_history_invalid_payload_is_rejected_before_storage(self):
        rid = str(uuid.uuid4())
        data = {"externalRunId": rid, "originClient": "skill", "visibility": "private",
                "status": "success", "requestId": "skill-history-" + rid,
                "originalRequest": "hello", "images": [{
                    "dataUrl": "data:image/png;base64,aGVsbG8=",
                    "sha256": "0" * 64}]}
        with self.assertRaises(ServiceError):
            bridge.import_history(self.db, self.owner, data,
                                  lambda *a, **kw: self.fail("must never save"))
        with self.assertRaises(ServiceError):
            bridge.import_history(self.db, self.owner, {**data, "visibility": "public"},
                                  lambda *a, **kw: self.fail("must never save"))

    def test_notifications_scoped_to_owner(self):
        with self.db.transaction() as tx:
            tx.execute("INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)"
                       " VALUES (?, 'comment','新评论','work','work_1',?)",
                       (self.owner["id"], "2026-11-07T00:00:00Z"))
        self.assertEqual(len(bridge.notification_list(self.db, self.owner, {})["items"]), 1)
        self.assertEqual(bridge.notification_list(self.db, self.other, {})["items"], [])

    def test_skill_comment_retries_do_not_create_duplicates(self):
        publication = publish_user_work(
            self.db, self.owner,
            {"title": "Skill 来源画作", "prompt": "铅笔线描",
             "images": ["/images/individual/FA/FA-013.webp"],
             "styles": [], "layout": "", "price": 0})
        wid = publication["workId"]
        data = {"text": "图型布局好看", "requestId": "skill-comment-" + str(uuid.uuid4())}
        first = bridge.social_comment(self.db, self.other, wid, data)
        again = bridge.social_comment(self.db, self.other, wid, data)
        self.assertEqual(first["replyId"], again["replyId"])
        count = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM forum_replies WHERE id=?", (first["replyId"],)).fetchone()[0]
        self.assertEqual(count, 1)
        with self.assertRaises(ServiceError) as error:
            bridge.social_comment(self.db, self.other, wid, {**data, "text": "换一句话"})
        self.assertEqual(error.exception.status, 409)

    def test_work_likes_reuse_existing_social_store(self):
        publication = publish_user_work(
            self.db,self.owner,{"title":"原画","prompt":"画风","images":["/images/individual/FA/FA-013.webp"],
                                "styles":[],"layout":"","price":0})
        wid = publication["workId"]
        self.assertTrue(bridge.social_like(self.db,self.other,wid,{"liked":True})["liked"])
        self.assertEqual(bridge.social_like(self.db,self.other,wid,{"liked":True})["likes"],1)
        self.assertFalse(bridge.social_like(self.db,self.other,wid,{"liked":False})["liked"])


class SkillWebHttpScopeTests(SkillWebBridgeTests):
    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        self.httpd = ThreadingHTTPServer(("127.0.0.1",0),HandrawRequestHandler)
        self.httpd.channel_role = "main"
        self.httpd.db = self.db
        self.httpd.allow_demo_routes = True
        self.base = "http://127.0.0.1:" + str(self.httpd.server_port)
        self.thread = threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(lambda: self.thread.join(5))

    def token(self, scopes):
        secret = "hwt_fixture_" + uuid.uuid4().hex
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO api_tokens(id,user_id,name,scopes,token_hash,
                created_at,last_used_at,revoked_at) VALUES(?,?,?,?,?,'2026-11-07T00:00:00Z','','')""",
                ("tok_"+uuid.uuid4().hex,self.owner["id"],"Skill test",json.dumps(scopes),
                 hashlib.sha256(secret.encode()).hexdigest()))
        return secret

    def request(self, method, path, token=None, body=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        payload = None if body is None else json.dumps(body).encode()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req=urllib.request.Request(self.base+path,data=payload,method=method,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=5) as resp:
                return resp.status,json.load(resp)
        except urllib.error.HTTPError as exc:
            return exc.code,json.load(exc)

    def test_http_scopes_owner_and_private_resources(self):
        library=self.token(["library"])
        publish=self.token(["publish"])
        rid=str(uuid.uuid4())
        body=self.payload(rid)
        status,data=self.request("PUT","/api/v1/me/resources/"+rid,library,body)
        self.assertEqual(status,200,data)
        self.assertEqual(data["resource"]["visibility"],"private")
        self.assertEqual(self.request("GET","/api/v1/me/resources",library)[0],200)
        self.assertEqual(self.request("GET","/api/v1/me/resources",publish)[0],403)
        self.assertEqual(self.request("PUT","/api/v1/me/resources/"+rid,publish,body)[0],403)
        self.assertEqual(self.request("GET","/api/v1/me/resources")[0],401)

    def test_http_explicit_publication_is_idempotent_and_grants_media(self):
        library=self.token(["library"])
        publisher=self.token(["publish"])
        img=Image.new("RGB",(4,4),(44,66,88))
        buf=io.BytesIO(); img.save(buf,format="PNG")
        raw=buf.getvalue()
        rid=str(uuid.uuid4())
        payload={"externalRunId":rid,"originClient":"skill","visibility":"private",
                 "status":"success","originalRequest":"不公开的原始指令",
                 "requestId":"skill-history-"+rid,
                 "images":[{"name":"01.png","sha256":hashlib.sha256(raw).hexdigest(),
                            "dataUrl":"data:image/png;base64,"+base64.b64encode(raw).decode()}]}
        status,history=self.request("POST","/api/v1/me/generations",library,payload)
        self.assertEqual(status,200,history)
        hid=history["id"]
        before=self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        self.assertEqual(before,self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0])
        no_consent={"title":"公开作品","prompt":"公开安全的提示词"}
        self.assertEqual(self.request("POST","/api/v1/me/generations/"+hid+"/publish",
                                      publisher,no_consent)[0],400)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],before)
        consent={**no_consent,"confirmed":True,"indices":[0]}
        status,work=self.request("POST","/api/v1/me/generations/"+hid+"/publish",
                                 publisher,consent)
        self.assertEqual(status,200,work)
        self.assertTrue(work["workId"])
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],before+1)
        status,repeat=self.request("POST","/api/v1/me/generations/"+hid+"/publish",
                                   publisher,consent)
        self.assertEqual(status,200,repeat)
        self.assertEqual(repeat["workId"],work["workId"])
        self.assertTrue(repeat["alreadyPublished"])
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],before+1)
        result=bridge.list_history(self.db,self.owner,{})
        self.assertEqual(result["items"][0]["publishedWorkId"],work["workId"])
        self.assertFalse(result["items"][0]["canPublish"])
        record=self.db.get_conn().execute("SELECT images_json FROM works WHERE id=?",
                                         (work["workId"],)).fetchone()
        image_url=json.loads(record["images_json"])[0]
        granted=self.db.get_conn().execute(
            "SELECT 1 FROM media_public_grants WHERE media_url=? AND revoked_at IS NULL",
            (image_url,)).fetchone()
        self.assertIsNotNone(granted)

    def test_http_publication_respects_token_scope(self):
        reader=self.token(["library"])
        self.assertEqual(self.request("POST","/api/v1/me/generations/skillgen_unknown/publish",
                                      reader,{"confirmed":True,"title":"作品","prompt":"公开"})[0],403)

    def test_http_private_import_does_not_create_work(self):
        library=self.token(["library"])
        img=Image.new("RGB",(3,3),(255,0,0))
        out=io.BytesIO(); img.save(out,format="PNG")
        raw=out.getvalue()
        rid=str(uuid.uuid4())
        body={"externalRunId":rid,"originClient":"skill","visibility":"private",
              "status":"success","originalRequest":"私人创作指令",
              "requestId":"skill-history-"+rid,
              "images":[{"name":"01.png","sha256":hashlib.sha256(raw).hexdigest(),
                         "dataUrl":"data:image/png;base64,"+base64.b64encode(raw).decode()}]}
        before=self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        status,created=self.request("POST","/api/v1/me/generations",library,body)
        self.assertEqual(status,200,created)
        self.assertEqual(created["visibility"],"private")
        self.assertEqual(self.request("POST","/api/v1/me/generations",library,body)[1]["deduped"],True)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],before)
        self.assertEqual(self.request("GET","/api/v1/me/generations",library)[0],200)
        self.assertEqual(self.request("POST","/api/v1/me/generations",self.token(["publish"]),body)[0],403)
