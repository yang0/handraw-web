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

    def test_website_new_generations_are_public_even_when_legacy_flag_set(self):
        from backend.services import record_user_studio_history
        with patch.dict(os.environ, {"HANDRAW_PRIVATE_GENERATION_HISTORY_V1": "1"}):
            record_user_studio_history(self.db, self.owner, {
                "id": "web_hist_public", "tabTitle": "生成记录",
                "mode": "graphic-text", "kind": "single",
                "prompt": "纸上绘制风景",
                "items": [{"imageUrl": "/images/individual/FA/FA-013.webp"}],
            })
        row = self.db.get_conn().execute(
            "SELECT visibility FROM studio_generations WHERE id='web_hist_public'"
        ).fetchone()
        self.assertEqual(row["visibility"], "public")
        mapped = self.db.get_conn().execute(
            "SELECT work_id FROM generation_works WHERE generation_id='web_hist_public'"
        ).fetchone()
        self.assertIsNotNone(mapped)
        own = bridge.list_history(self.db, self.owner, {})
        self.assertTrue(any(r["id"] == "web_hist_public" and r["visibility"] == "public"
                            for r in own["items"]))

    def test_skill_upload_publishes_one_work_per_image_without_duplicates(self):
        from backend.server import save_data_url_upload
        img = Image.new("RGB", (3, 3), (30, 160, 80))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()
        rid = str(uuid.uuid4())
        data = {"externalRunId": rid, "originClient": "skill", "visibility": "public",
                "status": "success", "requestId": "skill-history-" + rid,
                "originalRequest": "纸张纹理上的绿色小树",
                "images": [{"name": "image.png", "sha256": hashlib.sha256(raw).hexdigest(),
                             "dataUrl": "data:image/png;base64," +
                             base64.b64encode(raw).decode("ascii")}]}
        before = self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        first = bridge.import_history(self.db, self.owner, data, save_data_url_upload)
        repeat = bridge.import_history(self.db, self.owner, data, save_data_url_upload)
        self.assertEqual(first["id"], repeat["id"])
        self.assertEqual(first["workIds"], repeat["workIds"])
        self.assertTrue(repeat["deduped"])
        self.assertEqual(first["visibility"], "public")
        self.assertEqual(len(first["workIds"]), 1)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0], before + 1)
        work = self.db.get_conn().execute(
            "SELECT status,author_username,images_json FROM works WHERE id=?",
            (first["workIds"][0],)).fetchone()
        self.assertEqual(work["status"], "published")
        self.assertEqual(work["author_username"], self.owner["username"])
        own = bridge.list_history(self.db, self.owner, {})
        self.assertTrue(any(x["id"] == first["id"] and x["visibility"] == "public"
                            and x["workIds"] == first["workIds"] for x in own["items"]))
        self.assertFalse(any(x["id"] == first["id"] for x in
                             bridge.list_history(self.db, self.other, {})["items"]))
        with self.assertRaises(ServiceError) as error:
            bridge.import_history(self.db, self.owner, {**data, "originalRequest": "被篡改"},
                                  save_data_url_upload)
        self.assertEqual(error.exception.status, 409)

    def test_skill_multi_image_run_creates_one_public_work(self):
        from backend.server import save_data_url_upload
        images = []
        for index in range(3):
            picture = Image.new("RGB", (4, 4), (index * 50, 90, 110))
            buffer = io.BytesIO()
            picture.save(buffer, format="PNG")
            raw = buffer.getvalue()
            images.append({
                "name": f"frame_{index}.png",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "dataUrl": "data:image/png;base64," + base64.b64encode(raw).decode(),
            })
        rid = str(uuid.uuid4())
        payload = {
            "externalRunId": rid, "originClient": "skill", "visibility": "public",
            "status": "success", "requestId": "skill-history-" + rid,
            "originalRequest": "三张同画风插画", "images": images,
        }
        before = self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        first = bridge.import_history(self.db, self.owner, payload, save_data_url_upload)
        repeat = bridge.import_history(self.db, self.owner, payload, save_data_url_upload)
        self.assertEqual(first["workIds"], repeat["workIds"])
        self.assertEqual(first["imageCount"], 3)
        self.assertEqual(len(first["workIds"]), 1)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0], before + 1)
        work = self.db.get_conn().execute(
            "SELECT images_json FROM works WHERE id=?", (first["workId"],)
        ).fetchone()
        urls = json.loads(work["images_json"])
        self.assertEqual(len(urls), 3)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_works WHERE generation_id=?", (first["id"],)
        ).fetchone()[0], 1)
        for url in urls:
            self.assertTrue(self.db.get_conn().execute(
                "SELECT 1 FROM media_public_grants WHERE media_url=? AND target_type='work' "
                "AND target_id=? AND revoked_at IS NULL", (url, first["workId"])
            ).fetchone())

    def test_history_upload_resumes_after_interruption_without_duplicate_media(self):
        rid=str(uuid.uuid4())
        a,b=b"image-one",b"image-two"
        images=[{"name":name,"sha256":hashlib.sha256(blob).hexdigest(),
                 "dataUrl":"data:image/png;base64,"+base64.b64encode(blob).decode()}
                for name,blob in (("one.png",a),("two.png",b))]
        payload={"externalRunId":rid,"originClient":"skill","visibility":"public",
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
        with patch.object(bridge, "_publish_skill_run_images", return_value=["work_a"]):
            completed=bridge.import_history(self.db,self.owner,payload,resume_store)
            self.assertEqual(completed["visibility"],"public")
            self.assertEqual(completed["workIds"],["work_a"])
            self.assertEqual(len(saved),2)
            self.assertEqual(completed["imageCount"], 2)
            self.assertTrue(bridge.import_history(self.db,self.owner,payload,resume_store)["deduped"])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM skill_generation_runs WHERE user_id=? AND external_run_id=?",
            (self.owner["id"],rid)).fetchone()[0],1)

    def test_private_history_quota_rejects_without_writing_new_media(self):
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO user_uploads
                (id,user_id,cat,name_zh,image_url,bytes,created_at)
                VALUES (?,?, 'skill_history','Existing history','/uploads/quota-existing.png',?,?)""",
                ("UPL_quota_test",self.owner["id"],1024*1024*1024,"2026-11-07T00:00:00Z"))
        rid=str(uuid.uuid4())
        blob=b"another-asset"
        payload={"externalRunId":rid,"originClient":"skill","visibility":"public",
                 "status":"success","requestId":"skill-history-"+rid,
                 "originalRequest":"私人提示词","images":[{
                    "name":"test.png","sha256":hashlib.sha256(blob).hexdigest(),
                    "dataUrl":"data:image/png;base64,"+base64.b64encode(blob).decode()}]}
        with self.assertRaises(ServiceError) as error:
            bridge.import_history(self.db,self.owner,payload,
                                  lambda *a,**kw:self.fail("storage call must not happen"))
        self.assertEqual(error.exception.status,413)
        self.assertEqual(error.exception.code,"skill_history_storage_quota_exceeded")
        self.assertIsNone(self.db.get_conn().execute(
            "SELECT id FROM skill_generation_runs WHERE external_run_id=?", (rid,)).fetchone())

    def test_history_invalid_payload_is_rejected_before_storage(self):
        rid = str(uuid.uuid4())
        data = {"externalRunId": rid, "originClient": "skill", "visibility": "public",
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

    def test_legacy_reconciliation_excludes_existing_private_history(self):
        with self.assertRaises(ServiceError) as unauthorised:
            bridge.legacy_generation_audit(self.db, self.owner)
        self.assertEqual(unauthorised.exception.status, 403)
        admin = {**self.owner, "role": "admin"}
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO studio_generations
                (id,user_id,username,tab_title,mode,prompt,items_json,status,created_at,visibility,engine)
                VALUES ('private_audit_only',?,?,?,?,?,'["/images/individual/FA/FA-013.webp"]',
                        'success','2026-11-07T00:00:00Z','private','sample')""",
                (self.owner["id"], self.owner["username"], "私有旧历史",
                 "graphic-text", "仅本人可见"))
        with self.assertRaises(ServiceError):
            bridge.reconcile_legacy_generations(self.db, admin, {"batchSize":10})
        before = self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        repaired = bridge.reconcile_legacy_generations(
            self.db, admin, {"batchSize":10,"confirmed":True})
        self.assertTrue(repaired["ok"])
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0], before)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT visibility FROM studio_generations WHERE id='private_audit_only'"
        ).fetchone()[0], "private")

    def test_migration_repair_maps_only_existing_public_history(self):
        from backend.migrations import POST_MIGRATION_HOOKS
        self.assertIn(97, POST_MIGRATION_HOOKS)
        with self.db.transaction() as tx:
            for hid, visibility, path in (
                ("public_missing_work", "public", "/images/individual/FA/FA-013.webp"),
                ("private_preserved", "private", "/images/individual/FA/FA-014.webp"),
            ):
                tx.execute("""INSERT INTO studio_generations
                    (id,user_id,username,tab_title,mode,prompt,items_json,status,
                     created_at,visibility,engine)
                    VALUES (?,?,?,?,?, ?, ?, 'success', ?, ?, 'sample')""",
                    (hid,self.owner["id"],self.owner["username"],hid,
                     "graphic-text","一张铅笔风格插画",json.dumps([path]),
                     "2026-11-07T00:00:00Z",visibility))
        with self.db.transaction() as tx:
            POST_MIGRATION_HOOKS[97](tx)
            POST_MIGRATION_HOOKS[97](tx)
        public_count=self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_works WHERE generation_id='public_missing_work'"
        ).fetchone()[0]
        private_count=self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_works WHERE generation_id='private_preserved'"
        ).fetchone()[0]
        self.assertEqual(public_count,1)
        self.assertEqual(private_count,0)

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

    def test_http_upload_is_public_idempotent_and_media_accessible(self):
        library = self.token(["library"])
        publisher = self.token(["publish"])
        img = Image.new("RGB",(4,4),(44,66,88))
        buf = io.BytesIO()
        img.save(buf,format="PNG")
        raw = buf.getvalue()
        rid = str(uuid.uuid4())
        payload = {"externalRunId":rid,"originClient":"skill","visibility":"public",
                   "status":"success","originalRequest":"公开手绘红色花朵",
                   "requestId":"skill-history-"+rid,
                   "images":[{"name":"01.png","sha256":hashlib.sha256(raw).hexdigest(),
                              "dataUrl":"data:image/png;base64,"+base64.b64encode(raw).decode()}]}
        before = self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        self.assertEqual(self.request("POST","/api/v1/me/generations",library,payload)[0],403)
        status,first=self.request("POST","/api/v1/me/generations",publisher,payload)
        self.assertEqual(status,200,first)
        self.assertEqual(first["visibility"],"public")
        self.assertEqual(len(first["workIds"]),1)
        status,again=self.request("POST","/api/v1/me/generations",publisher,payload)
        self.assertEqual(status,200,again)
        self.assertTrue(again["deduped"])
        self.assertEqual(again["workIds"],first["workIds"])
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],before+1)
        wid=first["workIds"][0]
        row=self.db.get_conn().execute(
            "SELECT status,images_json FROM works WHERE id=?", (wid,)).fetchone()
        self.assertEqual(row["status"],"published")
        image_url=json.loads(row["images_json"])[0]
        grant=self.db.get_conn().execute(
            "SELECT 1 FROM media_public_grants WHERE media_url=? AND target_type='work' "
            "AND target_id=? AND revoked_at IS NULL", (image_url,wid)).fetchone()
        self.assertIsNotNone(grant)
        self.assertEqual(self.request("GET","/api/v1/me/generations",library)[0],200)

    def test_http_second_publish_step_is_not_available(self):
        publisher = self.token(["publish"])
        status,_=self.request("POST","/api/v1/me/generations/skillgen_unknown/publish",
                              publisher,{"confirmed":True,"title":"作品","prompt":"公开"})
        self.assertNotEqual(status,200)

    def test_http_old_private_upload_is_rejected_without_publication(self):
        publisher=self.token(["publish"])
        img=Image.new("RGB",(3,3),(255,0,0))
        out=io.BytesIO()
        img.save(out,format="PNG")
        raw=out.getvalue()
        rid=str(uuid.uuid4())
        body={"externalRunId":rid,"originClient":"skill","visibility":"private",
              "status":"success","originalRequest":"历史私有指令",
              "requestId":"skill-history-"+rid,
              "images":[{"name":"01.png","sha256":hashlib.sha256(raw).hexdigest(),
                         "dataUrl":"data:image/png;base64,"+base64.b64encode(raw).decode()}]}
        before=self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0]
        status,failed=self.request("POST","/api/v1/me/generations",publisher,body)
        self.assertEqual(status,400,failed)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],before)

