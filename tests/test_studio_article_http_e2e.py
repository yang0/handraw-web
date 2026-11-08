"""Studio #124 end-to-end HTTP contract: auth -> CAS -> owner Run read.

Uses a real ThreadingHTTPServer, session cookies and SQLite. The test
does not call image-generation endpoints or publish any private media.
"""
import copy
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

from backend.server import HandrawRequestHandler, init_database
from backend.services import register_user
from backend.generation_v3 import ensure_run


class StudioArticleHttpE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "studio124.db"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_DEMO_MODE": "1",
        })
        self.env.start()
        self.db = init_database(root / "studio124.db")
        self.owner, _ = register_user(self.db, "studio124_http_owner", "password123")
        self.other, _ = register_user(self.db, "studio124_http_other", "password123")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "studio"
        self.httpd.db = self.db
        self.httpd.allow_demo_routes = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        with self.db.transaction() as tx:
            self.run_id = ensure_run(tx,user_id=self.owner["id"],source="web",
                                     external_run_id="http-test",expected_count=2)
            for position,status in ((0,"failed"),(1000,"pending")):
                tx.execute("""INSERT INTO generation_items
                (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                VALUES (?,?,?,?,NULL,'','2026-11-08','2026-11-08')""",
                (f"httpitem-{position}",self.run_id,position,status))
        self.cookie = self.login("studio124_http_owner")
        self.foreign_cookie = self.login("studio124_http_other")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=None, cookie=""):
        headers = {"Accept":"application/json","Origin":"http://trusted.test"}
        if cookie:
            headers["Cookie"]=cookie
        payload = None if body is None else json.dumps(body,ensure_ascii=False).encode()
        if payload is not None: headers["Content-Type"]="application/json"
        req = urllib.request.Request(self.base+path,data=payload,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                return response.status,response.headers,json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code,error.headers,json.loads(error.read())

    def login(self,name):
        status,headers,payload=self.request("POST","/api/auth/login",
            {"account":name,"password":"password123"})
        self.assertEqual(status,200,str(payload))
        return headers.get("Set-Cookie","").split(";",1)[0]

    def test_article_plan_conflict_ten_switches_and_run_owner(self):
        body = {
            "projectId":"studio124-http-project", "kind":"article", "authority":"article",
            "idempotencyKey":"studio124-http-create", "title":"龙井",
            "draft":{
                "article":{"documentId":"http-doc","revision":7,
                           "markdown":"# 龙井\n\n茶园",
                           "anchors":[{"anchorId":"cover"},{"anchorId":"p-1"}]},
                "plan":{"kind":"article","planId":"http-plan","revision":2,
                        "documentId":"http-doc","documentRevision":7,
                        "slots":[{"slotId":"cover-slot","anchorId":"cover"},
                                 {"slotId":"inline-slot","anchorId":"p-1"}]},
                "activeView":"simple",
                "editorLayout":{"runRefs":[{"runId":self.run_id}]},
            }
        }
        status,_,result=self.request("POST","/api/studio/projects",body,self.cookie)
        self.assertEqual(status,200,str(result))
        self.assertEqual(result["revision"],1)
        unchanged=copy.deepcopy(body["draft"])
        rev=1
        for idx in range(10):
            data={"baseRevision":rev,"idempotencyKey":f"http-switch-{idx:04d}",
                "patch":{"op":"set","path":"/activeView",
                         "value":"canvas" if idx%2==0 else "simple"}}
            status,_,result=self.request("PATCH","/api/studio/projects/studio124-http-project/draft",
                                         data,self.cookie)
            self.assertEqual(status,200,str(result))
            rev=result["revision"]
        status,_,read=self.request("GET","/api/studio/projects/studio124-http-project",
                                   cookie=self.cookie)
        self.assertEqual(status,200,str(read))
        self.assertEqual(read["project"]["draft"]["article"],unchanged["article"])
        self.assertEqual(read["project"]["draft"]["plan"],unchanged["plan"])
        self.assertEqual(read["project"]["draft"]["editorLayout"],unchanged["editorLayout"])
        status,_,conflict=self.request("PATCH","/api/studio/projects/studio124-http-project/draft",
            {"baseRevision":rev,"idempotencyKey":"http-stale-plan-124",
             "patch":{"op":"set","path":"/plan/documentRevision","value":6}},
            self.cookie)
        self.assertEqual(status,409,str(conflict))
        self.assertEqual(conflict.get("code"),"article_revision_conflict")
        status,_,owned=self.request("GET","/api/studio/runs/"+self.run_id,cookie=self.cookie)
        self.assertEqual(status,200,str(owned))
        self.assertEqual([it["slotIndex"] for it in owned["items"]],[0,1])
        status,_,hidden=self.request("GET","/api/studio/runs/"+self.run_id,
                                     cookie=self.foreign_cookie)
        self.assertEqual(status,404,str(hidden))
        status,_,hidden_project=self.request("GET",
            "/api/studio/projects/studio124-http-project",cookie=self.foreign_cookie)
        self.assertEqual(status,404,str(hidden_project))
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
