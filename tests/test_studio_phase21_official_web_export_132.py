"""Phase21 official Web DB read-only source export, entirely offline fixtures."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.studio_official_approval_132 import sha
from ops.studio_phase21_official_web_export_132 import (
    QUERY,transform,build_receipt,write_fresh,load_readonly_pg,main,
)


def rows():
    return [
        {"code":"FF-018","kind":"style","name":"Low Poly Art",
         "group_name":"mock-style-group","description":"Mock license-reviewed",
         "definition":"private mock definition","unlock_cost":0,
         "source_type":"official","status":"published"},
        {"code":"FF-019","kind":"style","name":"Hyperreal 3D Cartoon Portrait",
         "group_name":"mock-style-group","description":"",
         "definition":"test gated-paid-definition","unlock_cost":50,
         "source_type":"official","status":"published"},
        {"code":"FG-025","kind":"style","name":"Perler Bead Pixel Art",
         "group_name":"mock-style-group","description":"Bead style",
         "definition":"perler fixture","unlock_cost":0,
         "source_type":"official","status":"published"},
        {"code":"IG-001","kind":"layout","name":"Starter mock",
         "group_name":"infographic","description":"图表、概念",
         "definition":"layout fixture","unlock_cost":0,
         "source_type":"official","status":"published"},
    ]


class FakeCursor:
    def __init__(self,value): self.value=value
    def fetchone(self): return self.value
    def fetchall(self): return self.value


class FakeDb:
    def __init__(self,readonly="on",version="170002"):
        self.readonly=readonly
        self.version=version
        self.sql=[]
    def __enter__(self): return self
    def __exit__(self,*args): return None
    def execute(self,query):
        self.sql.append(query)
        if query=="SHOW transaction_read_only":
            return FakeCursor({"transaction_read_only":self.readonly})
        if query=="SHOW server_version_num":
            return FakeCursor({"server_version_num":self.version})
        if query==QUERY:
            return FakeCursor(rows())
        return FakeCursor(None)


class Phase21OfficialWebDbExportTest(unittest.TestCase):
    def test_three_website_published_style_rows_and_layout_can_be_read_without_skill_collision(self):
        styles,layouts,digest=transform(rows())
        self.assertEqual(len(styles),3)
        self.assertEqual(len(layouts),1)
        self.assertEqual({x["number"] for x in styles},
                         {"FF-018","FF-019","FG-025"})
        self.assertEqual(styles[1]["generation_name"],
                         "Hyperreal 3D Cartoon Portrait")
        self.assertNotIn("definition",styles[1])  # paid definition must not leak
        self.assertEqual(styles[1]["traits"],"")
        self.assertEqual(digest,sha(rows()))
        receipt=build_receipt(styles=styles,layouts=layouts,
            raw_digest=digest,deployed_sha="a"*40,
            operator="test-exporter",reviewer="test-independent-reviewer",
            session="mock-export-21")
        self.assertEqual(receipt["sourceRowsSha256"],digest)
        self.assertEqual(receipt["publishedStylesSha256"],sha(styles))
        self.assertEqual(receipt["publishedLayoutsSha256"],sha(layouts))
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/"export"
            result=write_fresh(out,styles,layouts,receipt)
            self.assertEqual(result["decision"],"NO-GO")
            self.assertFalse(result["automaticWebsiteApprovalGranted"])
            self.assertFalse(result["trueDbOriginIndependentlyAttested"])
            self.assertEqual(json.loads((out/"styles.json").read_text()),styles)
            self.assertEqual(json.loads((out/"readonly-export-receipt.json").read_text()),receipt)
            with self.assertRaises(ValueError):
                write_fresh(out,styles,layouts,receipt)

    def test_unapproved_or_duplicate_or_unsafe_metadata_fail_closed(self):
        for field,bad in (
            ("status","pending"),
            ("source_type","user"),
            ("name",""),
            ("code","../../escape"),
            ("unlock_cost",-1),
            ("group_name",["bad"]),
        ):
            test=rows()
            test[0][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):
                transform(test)
        test=rows()
        test[1]["code"]=test[0]["code"]
        with self.assertRaises(ValueError):
            transform(test)
        test=rows()
        test[3]["group_name"]="../private"
        with self.assertRaises(ValueError):
            transform(test)
        test=rows()
        test[0]["user_email"]="not-allowed"
        with self.assertRaises(ValueError):
            transform(test)

    def test_unpinned_or_self_reviewed_receipt_denied(self):
        styles,layouts,raw=transform(rows())
        with self.assertRaises(ValueError):
            build_receipt(styles=styles,layouts=layouts,raw_digest=raw,
                          deployed_sha="short",operator="a-valid",
                          reviewer="a-reviewer",session="mock-21")
        with self.assertRaises(ValueError):
            build_receipt(styles=styles,layouts=layouts,raw_digest=raw,
                          deployed_sha="a"*40,operator="same-id",
                          reviewer="same-id",session="mock-21")

    def test_without_explicit_real_pg_readonly_access_no_connection(self):
        with patch.dict(os.environ,{"HANDRAW_PHASE21_ALLOW_WEBSITE_READONLY_EXPORT":"",
                                    "HANDRAW_PHASE21_WEB_READONLY_DSN":"fake"}):
            with self.assertRaises(ValueError):
                load_readonly_pg(dsn_env="HANDRAW_PHASE21_WEB_READONLY_DSN")
        with self.assertRaises(ValueError):
            load_readonly_pg(dsn_env="PGPASSWORD")

    def test_actual_readonly_guard_and_pg17_version_inspected_with_mock_session(self):
        import psycopg
        fake=FakeDb()
        with patch.dict(os.environ,{"HANDRAW_PHASE21_ALLOW_WEBSITE_READONLY_EXPORT":"YES",
                                    "HANDRAW_PHASE21_WEB_READONLY_DSN":"fake"}), \
             patch.object(psycopg,"connect",return_value=fake):
            output=load_readonly_pg(dsn_env="HANDRAW_PHASE21_WEB_READONLY_DSN")
        self.assertEqual(len(output),4)
        self.assertIn("REPEATABLE READ READ ONLY",fake.sql[0])
        self.assertEqual(fake.sql[-1],QUERY)
        for kind,version in (("off","170002"),("on","160002")):
            fake=FakeDb(readonly=kind,version=version)
            with patch.dict(os.environ,{"HANDRAW_PHASE21_ALLOW_WEBSITE_READONLY_EXPORT":"YES",
                                        "HANDRAW_PHASE21_WEB_READONLY_DSN":"fake"}), \
                 patch.object(psycopg,"connect",return_value=fake):
                with self.subTest(kind=kind,version=version),self.assertRaises(ValueError):
                    load_readonly_pg(dsn_env="HANDRAW_PHASE21_WEB_READONLY_DSN")

    def test_export_cli_cannot_connect_without_explicit_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{"HANDRAW_PHASE21_ALLOW_WEBSITE_READONLY_EXPORT":""}):
                rc=main(["--dsn-env","HANDRAW_PHASE21_WEB_READONLY_DSN",
                    "--environment","preprod-official-check",
                    "--deployed-sha","a"*40,"--operator-id","qa-exporter",
                    "--independent-reviewer-id","qa-reviewer",
                    "--out",str(Path(tmp)/"never-created")])
            self.assertEqual(rc,2)
            self.assertFalse((Path(tmp)/"never-created").exists())


if __name__=="__main__":
    unittest.main()
