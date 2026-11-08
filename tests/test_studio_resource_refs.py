"""Studio2 ResourceRef server authorization: Project save is not a grant (#105)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import Database
from backend.services import ServiceError, register_user
from backend.studio_projects import create_project, get_project, patch_project


class ResourceRefProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/"resources.sqlite3")
        self.db.migrate()
        self.owner,_=register_user(self.db,"resource_owner_1","Pass12345!")
        self.other,_=register_user(self.db,"resource_other_1","Pass12345!")
        self.counter=0

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def ref(self, ident, kind, source="official", version=1):
        return {"id":ident,"type":kind,"source":source,"version":version}

    def create(self, draft, authority="spec", user=None):
        self.counter+=1
        return create_project(self.db,user or self.owner,{
            "projectId":f"resource-project-{self.counter}",
            "idempotencyKey":f"create-unique-{self.counter:05}",
            "kind":"image", "title":"资源验证", "authority":authority,
            "draft":draft
        })

    def test_real_catalog_and_creation_spec_roundtrip(self):
        spec={"subject":"杭州春天","style":self.ref("FA-001","style"),
              "secondaryStyle":self.ref("FA-002","style"),"fusionEnabled":False,
              "layout":self.ref("SC-021","layout"),
              "colors":[self.ref("C-01","color")],
              "tones":[self.ref("T-01","tone")],"referenceMedia":[]}
        result=self.create({"creationSpec":spec})
        saved=get_project(self.db,self.owner,result["projectId"])["project"]
        self.assertEqual(saved["draft"]["creationSpec"],spec)
        self.assertEqual(saved["authority"],"spec")

    def test_invalid_kind_source_version_or_missing_code_rejected(self):
        for ref,expected in [
            (self.ref("SC-021","style"),"resource_not_found"),
            (self.ref("FA-001","layout"),"resource_type_mismatch"),
            (self.ref("NOT-FOUND-999","style"),"resource_not_found"),
            (self.ref("C-01","tone"),"resource_type_mismatch"),
            (self.ref("FA-001","style","private"),"resource_source_mismatch"),
            (self.ref("C-01","color","official",899),"resource_version_conflict"),
            ({"id":"FA-001","type":"style","secret":"prompt"},"invalid_resource_ref"),
        ]:
            with self.subTest(ref=ref), self.assertRaises(ServiceError) as error:
                self.create({"creationSpec":{"style":ref}})
            self.assertEqual(error.exception.code,expected)

    def test_server_enforces_resource_unlock_and_private_ownership(self):
        allowed={"id":"USR-ABC","kind":"style","source":"private",
                 "canUse":True,"access":{"canUse":True},"_raw_row":{"revision":4}}
        private_ref=self.ref("USR-ABC","style","private",4)
        with patch("backend.resource_registry.resolve",return_value=allowed):
            result=self.create({"creationSpec":{"style":private_ref}})
        self.assertTrue(result["ok"])
        blocked={**allowed,"canUse":False,"access":{"canUse":False}}
        with patch("backend.resource_registry.resolve",return_value=blocked):
            with self.assertRaises(ServiceError) as error:
                self.create({"creationSpec":{"style":private_ref}})
            self.assertEqual(error.exception.status,403)
            self.assertEqual(error.exception.code,"resource_forbidden")
        with patch("backend.resource_registry.resolve",return_value=None):
            with self.assertRaises(ServiceError) as error:
                self.create({"creationSpec":{"style":private_ref}},user=self.other)
            self.assertEqual(error.exception.code,"resource_not_found")

    def test_private_upload_and_generated_media_are_owner_scoped(self):
        with self.db.transaction() as tx:
            for uid,ident in ((self.owner["id"],"media-owned-upload"),
                              (self.other["id"],"media-other-upload")):
                tx.execute("""INSERT INTO user_uploads
                    (id,user_id,cat,name_zh,image_url,created_at,asset_uid)
                    VALUES (?,?,?,'测试','/private/upload.webp','2026-11-08',?)""",
                    ("upload-"+ident,uid,"scenes",ident))
        spec={"referenceMedia":[{"mediaId":"media-owned-upload","role":"scene"}]}
        self.assertTrue(self.create({"creationSpec":spec})["ok"])
        for ident in ("media-other-upload","media-deleted-upload"):
            with self.subTest(ident=ident),self.assertRaises(ServiceError) as error:
                self.create({"creationSpec":{"referenceMedia":[{"mediaId":ident,"role":"scene"}]}})
            self.assertEqual(error.exception.code,"project_media_forbidden")
        with self.db.transaction() as tx:
            tx.execute("UPDATE user_uploads SET deleted_at='2026-11-08' WHERE asset_uid=?",
                       ("media-owned-upload",))
        with self.assertRaises(ServiceError) as error:
            self.create({"creationSpec":spec})
        self.assertEqual(error.exception.code,"project_media_forbidden")

    def test_graph_resource_refs_match_legacy_and_cas_patch_is_atomic(self):
        spec=self.ref("FA-001","style")
        graph={"nodes":[{"id":"s1","type":"skill_params","data":{
            "style1":"FA-001","layout":"SC-021","colors":[],"tones":[],
            "resourceRefs":{"style":spec,"layout":self.ref("SC-021","layout"),
                            "colors":[],"tones":[]}}}],"edges":[]}
        created=self.create({"graph":graph},authority="graph")
        project_id=created["projectId"]
        original=get_project(self.db,self.owner,project_id)["project"]
        self.assertEqual(original["revision"],1)
        broken={"nodes":[{"id":"s1","type":"skill_params","data":{
            "style1":"FA-001","resourceRefs":{"style":self.ref("FA-002","style")}}}]}
        with self.assertRaises(ServiceError) as error:
            patch_project(self.db,self.owner,project_id,{
                "baseRevision":1,"idempotencyKey":"patch-resource-mismatch-0001",
                "patch":{"op":"set","path":"/graph","value":broken}
            })
        self.assertEqual(error.exception.code,"resource_ref_mismatch")
        self.assertEqual(get_project(self.db,self.owner,project_id)["project"]["revision"],1)

    def test_private_gallery_asset_does_not_become_public_resource(self):
        # Private library uploads must be MediaRefs. Passing their ID as a
        # DirectoryResourceRef cannot grant access through the catalog.
        with self.assertRaises(ServiceError) as error:
            self.create({"creationSpec":{
                "style":{"id":"media-owned-upload","type":"style",
                         "source":"private","version":"current"}
            }})
        self.assertEqual(error.exception.code,"resource_not_found")


if __name__ == "__main__":
    unittest.main()
