"""Issue #125: strict, authorized three-entrance planner (mocked AI gateway)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_ai_plan import execute_ai_plan, _user_catalog

BASE = {"kind":"image","subject":"杭州春天","baseRevision":0,"count":1,
        "current":{},"lockedFields":[]}


class AIPlanContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/"issue125.db")
        self.db.migrate()
        self.user,_=register_user(self.db,"plan_125_user","Pass12345!",
            "plan125@example.com","Planner","invite-125")
        self.messages=[]
        self.calls=0

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_plan(self, body=None, response=None, meta=None):
        payload={**BASE,**(body or {})}
        def gateway(messages, **kwargs):
            self.calls+=1
            self.assertTrue(kwargs["json_mode"])
            self.messages.append(messages)
            req=json.loads(messages[-1]["content"])
            if response is not None:
                return response, meta or {"ok":True}
            styles=req["allowedStyles"]
            layouts=req["allowedLayouts"]
            self.assertGreater(len(styles),0)
            self.assertGreater(len(layouts),0)
            first, last=styles[0]["id"],layouts[-1]["id"]
            output={"styleId":first,"layoutId":last,"ratio":"3:4",
                    "reasons":{"style":"匹配主题光线","layout":"适合内容密度","ratio":"适合移动屏幕"},
                    "slots":[]}
            if req["kind"]!="image":
                for idx in range(req["count"]):
                    item={"subject":f"内容{idx+1}","layoutId":last,"ratio":"3:4",
                          "reason":f"第{idx+1}张的构图依据"}
                    if req["kind"]=="article":
                        item.update({"afterBlockIdx":-1 if idx==0 else req["articleBlocks"][idx-1]["idx"],
                            "role":"cover" if idx==0 else "illustration",
                            "purpose":"辅助理解","imageType":"scene"})
                    output["slots"].append(item)
            return json.dumps(output,ensure_ascii=False), {"ok":True}
        with patch("backend.studio_ai_plan.chat",side_effect=gateway):
            return execute_ai_plan(self.db,self.user,payload)

    def test_only_theme_returns_real_resources_and_no_paid_run(self):
        before=self.db.get_conn().execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0]
        result=self.run_plan()
        self.assertEqual(result["kind"],"image")
        self.assertEqual(result["source"],"model")
        self.assertEqual(result["phase"],"review")
        self.assertEqual(result["creationSpecPatch"]["baseRevision"],0)
        self.assertEqual(result["planPatch"],None)
        self.assertEqual(set(result["creationSpecPatch"]["reasons"]),{"style","layout","ratio"})
        self.assertEqual(result["cost"],{"generationStarted":False,"runCreated":False})
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_runs").fetchone()[0],before)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM generation_items").fetchone()[0],0)

    def test_uses_entire_authorized_catalog_not_first_40(self):
        result=self.run_plan({"subject":"城市交通信息图"})
        req=json.loads(self.messages[-1][-1]["content"])
        all_resources=_user_catalog(self.db,self.user)
        self.assertEqual(len(req["allowedStyles"]),len(all_resources["style"]))
        self.assertEqual(len(req["allowedLayouts"]),len(all_resources["layout"]))
        self.assertEqual(result["creationSpecPatch"]["changes"]["layout"]["id"],
                         req["allowedLayouts"][-1]["id"])
        self.assertNotIn("secret_blackbox_prompt",str(self.messages[-1]))
        self.assertNotIn("definition",str(self.messages[-1]))

    def test_six_slot_plan_stable_ids_and_reasons(self):
        slots=[{"slotId":f"p-{i}"} for i in range(6)]
        result=self.run_plan({"kind":"series","count":6,"planRevision":9,
                              "currentSlots":slots,"subject":"海边六图教程"})
        self.assertEqual(result["planPatch"]["baseRevision"],9)
        self.assertEqual([s["slotId"] for s in result["planPatch"]["slots"]],
                         [f"p-{i}" for i in range(6)])
        self.assertTrue(all(s["reasons"]["layout"] for s in result["planPatch"]["slots"]))
        self.assertEqual(result["validResources"]["layouts"],
                         len(_user_catalog(self.db,self.user)["layout"]))

    def test_article_preserves_real_block_anchor_and_revision(self):
        blocks=[{"idx":2,"kind":"h2","text":"春天第一章","anchorId":"a-2"},
                {"idx":7,"kind":"p","text":"采茶过程","anchorId":"a-7"},
                {"idx":10,"kind":"p","text":"传统工艺","anchorId":"a-10"}]
        result=self.run_plan({"kind":"article","subject":"龙井茶","baseRevision":7,
            "planRevision":4,"count":4,"blocks":blocks,"currentSlots":[]})
        slots=result["planPatch"]["slots"]
        self.assertEqual([x["anchorId"] for x in slots],["cover","a-2","a-7","a-10"])
        self.assertEqual([x["afterBlockIdx"] for x in slots],[-1,2,7,10])
        self.assertEqual(result["baseRevision"],7)

    def test_escaped_and_fenced_json(self):
        allowed=_user_catalog(self.db,self.user)
        data=json.dumps({"styleId":allowed["style"][0]["id"],
          "layoutId":allowed["layout"][0]["id"],"ratio":"1:1",
          "reasons":{"style":"理由一","layout":"理由二","ratio":"理由三"},"slots":[]})
        for wrapped in (f"```json\n{data}\n```",f"<escape>{data}</escape>"):
            with self.subTest(wrapper=wrapped[:7]):
                result=self.run_plan(response=wrapped)
                self.assertEqual(result["creationSpecPatch"]["changes"]["ratio"],"1:1")

    def test_error_types_are_exact_and_no_template_success(self):
        cases=[
            ('',{"ok":False,"reason":"http_502"},"ai_upstream_502"),
            ('',{"ok":False,"reason":"invalid_json"},"ai_invalid_json"),
            ('not-json',None,"ai_invalid_json"),
            ('{"styleId": "FA-001"}',None,"ai_schema_invalid"),
        ]
        for raw,meta,code in cases:
            with self.subTest(code=code):
                with patch("backend.studio_ai_plan.chat",return_value=(raw,meta or {"ok":True})):
                    with self.assertRaises(ServiceError) as ctx:
                        execute_ai_plan(self.db,self.user,BASE)
                self.assertEqual(ctx.exception.code,code)

    def test_unknown_and_unauthorized_resource_errors(self):
        layout=_user_catalog(self.db,self.user)["layout"][0]["id"]
        model=lambda style: json.dumps({"styleId":style,"layoutId":layout,
            "ratio":"3:4","reasons":{"style":"原因","layout":"原因","ratio":"原因"},
            "slots":[]})
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan(response=model("STYLE-NOT-FOUND"))
        self.assertEqual(ctx.exception.code,"ai_resource_not_found")
        from backend.studio_ai_plan import resolve as original_resolve
        allowed=_user_catalog(self.db,self.user)["style"][0]["id"]
        def denied(conn,code,**kwargs):
            if code==allowed:
                return {"kind":"style","canUse":False,"access":{"canUse":False}}
            return original_resolve(conn,code,**kwargs)
        with patch("backend.studio_ai_plan.resolve",side_effect=denied):
            with self.assertRaises(ServiceError) as ctx:
                self.run_plan(response=model(allowed))
        self.assertEqual(ctx.exception.code,"ai_resource_forbidden")

    def test_invalid_fields_bad_anchor_and_zero_slots_fail(self):
        allowed=_user_catalog(self.db,self.user)
        style=allowed["style"][0]["id"]
        layout=allowed["layout"][0]["id"]
        core={"styleId":style,"layoutId":layout,"ratio":"3:4",
              "reasons":{"style":"甲","layout":"乙","ratio":"丙"}}
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan(response=json.dumps({**core,"slots":[{"subject":"unexpected"}]}))
        self.assertEqual(ctx.exception.code,"ai_cannot_recommend")
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan({"kind":"article","count":2,"blocks":[
                {"idx":1,"kind":"p","text":"文章内容"}]},
                response=json.dumps({**core,"slots":[
                    {"subject":"封面","layoutId":layout,"ratio":"3:4","reason":"理由",
                     "afterBlockIdx":-1,"role":"cover"},
                    {"subject":"插图","layoutId":layout,"ratio":"3:4","reason":"理由",
                     "afterBlockIdx":99,"role":"illustration"}]}))
        self.assertEqual(ctx.exception.code,"ai_anchor_invalid")

    def test_project_revision_cas_and_no_run(self):
        from backend.studio_projects import create_project,patch_project
        create_project(self.db,self.user,{"projectId":"plan-revision-125",
            "kind":"image","authority":"spec","title":"原图",
            "idempotencyKey":"create-125","draft":{
                "creationSpec":{"subject":"测试","ratio":"3:4"},"activeView":"simple"}})
        self.run_plan({"baseRevision":1,"projectId":"plan-revision-125"})
        patch_project(self.db,self.user,"plan-revision-125",{
            "baseRevision":1,"idempotencyKey":"change-125",
            "patch":{"op":"set","path":"/creationSpec/subject","value":"已修改"}})
        count=self.calls
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan({"baseRevision":1,"projectId":"plan-revision-125"})
        self.assertEqual(ctx.exception.code,"ai_revision_conflict")
        self.assertEqual(self.calls,count,"outdated request rejects before charging any AI quota")

    def test_token_and_bad_revision_reject_before_model(self):
        with self.assertRaises(ServiceError) as ctx:
            execute_ai_plan(self.db,{**self.user,"_auth_kind":"token"},BASE)
        self.assertEqual(ctx.exception.code,"token_disallowed")
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan({"baseRevision":-1})
        self.assertEqual(ctx.exception.code,"ai_revision_required")


if __name__=="__main__":
    unittest.main()
