"""Issue #125: real HTTP Mock-AI contract; no upstream paid gateway."""
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

from backend.server import HandrawRequestHandler, init_database, SESSION_COOKIE_NAME
from backend.services import register_user
from backend.studio_ai_plan import _user_catalog


class AIPlanHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"studio125.db"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_ALLOWED_ORIGINS":"http://trusted.test",
            "HANDRAW_DEMO_MODE":"1"})
        self.env.start()
        self.db=init_database(root/"studio125.db")
        self.user,token=register_user(self.db,"ai_plan_125_http","Pass12345!")
        self.cookie=SESSION_COOKIE_NAME+"="+token
        self.other,other_token=register_user(self.db,"ai_plan_125_other","Pass12345!")
        self.other_cookie=SESSION_COOKIE_NAME+"="+other_token
        self.httpd=ThreadingHTTPServer(("127.0.0.1",0),HandrawRequestHandler)
        self.httpd.channel_role="studio"
        self.httpd.db=self.db
        self.httpd.allow_demo_routes=True
        self.base=f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.gateway_calls=0

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def post(self,body,cookie=None):
        headers={"Origin":"http://trusted.test","Content-Type":"application/json"}
        if cookie: headers["Cookie"]=cookie
        req=urllib.request.Request(self.base+"/api/studio/ai-plan",method="POST",
            headers=headers,data=json.dumps(body,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as err:
            return err.code,json.loads(err.read())

    def gateway(self,messages,**kwargs):
        self.gateway_calls+=1
        self.assertTrue(kwargs["json_mode"])
        req=json.loads(messages[-1]["content"])
        style=req["allowedStyles"][0]["id"]
        layout=req["allowedLayouts"][-1]["id"]
        slots=[]
        if req["kind"]=="series":
            slots=[{"subject":f"第{i+1}张","layoutId":layout,
                    "ratio":"3:4","reason":"契合主题"} for i in range(req["count"])]
        if req["kind"]=="article":
            slots=[{"subject":"封面" if i==0 else f"段落{i}",
                   "layoutId":layout,"ratio":"3:4","reason":"图文呼应",
                   "role":"cover" if i==0 else "illustration",
                   "afterBlockIdx":-1 if i==0 else req["articleBlocks"][i-1]["idx"]}
                   for i in range(req["count"])]
        model={"styleId":style,"layoutId":layout,"ratio":"3:4",
               "reasons":{"style":"水彩视觉","layout":"版式匹配","ratio":"竖屏合适"},
               "slots":slots}
        return json.dumps(model,ensure_ascii=False),{"ok":True}

    def test_image_series_article_http_and_no_generation(self):
        cases=[
            {"kind":"image","subject":"春日","count":1,"baseRevision":0},
            {"kind":"series","subject":"东方神话","count":6,"baseRevision":2,
             "planRevision":4,"currentSlots":[{"slotId":f"series-{i}"} for i in range(6)]},
            {"kind":"article","subject":"龙井茶","count":3,"baseRevision":9,"planRevision":8,
             "blocks":[{"idx":1,"kind":"p","text":"第一段","anchorId":"p-one"},
                       {"idx":4,"kind":"h2","text":"第二段","anchorId":"p-two"}]},
        ]
        before_runs=self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs").fetchone()[0]
        before_works=self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works").fetchone()[0]
        with patch("backend.studio_ai_plan.chat",side_effect=self.gateway):
            for case in cases:
                with self.subTest(kind=case["kind"]):
                    status,data=self.post(case,self.cookie)
                    self.assertEqual(status,200,str(data))
                    self.assertEqual(data["kind"],case["kind"])
                    self.assertEqual(data["phase"],"review")
                    self.assertEqual(data["baseRevision"],case["baseRevision"])
                    self.assertFalse(data["cost"]["generationStarted"])
                    if case["kind"]=="series":
                        self.assertEqual(len(data["planPatch"]["slots"]),6)
                        self.assertEqual(data["planPatch"]["slots"][2]["slotId"],"series-2")
                    if case["kind"]=="article":
                        self.assertEqual([s["anchorId"] for s in data["planPatch"]["slots"]],
                                         ["cover","p-one","p-two"])
        self.assertEqual(self.gateway_calls,3)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs").fetchone()[0],before_runs)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works").fetchone()[0],before_works)

    def test_http_failures_and_forbidden_identity(self):
        base={"kind":"image","subject":"茶文化","count":1,"baseRevision":0}
        self.assertEqual(self.post(base)[0],401)
        self.assertEqual(self.post({**base,"baseRevision":"0"},self.cookie)[1]["code"],
                         "ai_revision_required")
        with patch("backend.studio_ai_plan.chat",return_value=("",{"ok":False,"reason":"http_502"})):
            status,err=self.post(base,self.cookie)
        self.assertEqual(status,502)
        self.assertEqual(err["code"],"ai_upstream_502")
        with patch("backend.studio_ai_plan.chat",return_value=("prose",{"ok":True})):
            status,err=self.post(base,self.cookie)
        self.assertEqual(status,502)
        self.assertEqual(err["code"],"ai_invalid_json")

    def test_no_leakage_of_disallowed_media_or_blackbox(self):
        with patch("backend.studio_ai_plan.chat",side_effect=self.gateway) as mocked:
            status,result=self.post({"kind":"image","subject":"国风海报",
                "baseRevision":0,"current":{"styleId":"FA-001",
                "referenceMedia":[{"privatePrompt":"do-not-leak"}]},
                "privatePrompt":"do-not-leak"},self.cookie)
        self.assertEqual(status,200,str(result))
        sent=json.dumps(mocked.call_args.args[0],ensure_ascii=False)
        self.assertNotIn("do-not-leak",sent)
        self.assertNotIn("secret_blackbox_prompt",sent)
        self.assertNotIn("_raw_definition",sent)


if __name__=="__main__":
    unittest.main()
