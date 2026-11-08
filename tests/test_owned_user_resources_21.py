"""#21 Private authored styles/layouts: one CAS authority, Web read model.

All records are disposable SQLite fixtures. No external storage/paid model.
The existing Skill/Web PUT+GET+DELETE API is the bidirectional transport;
this suite checks Studio/boot/favorites and stale-version protections.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from backend.db import Database
from backend import resource_registry, skill_web_bridge as bridge
from backend.services import (
    ServiceError, build_boot_payload, register_user, toggle_user_collection,
    prepare_cloud_generation,
)
from backend.studio_resources import check_resource_ref


class OwnedCustomResources21(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="custom21-")
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "custom.db")
        self.db.migrate()
        self.addCleanup(self.db.close)
        self.owner, self.owner_session = register_user(
            self.db, "custom21_owner", "StrongPass123!")
        self.other, self.other_session = register_user(
            self.db, "custom21_other", "StrongPass123!")

    def payload(self, rid, kind="style", **overrides):
        body = {
            "id": rid, "kind": kind, "name": "我的原创柔和笔触",
            "definition": {"zh": "原创柔和水彩边缘与纸纹", "en": "Soft ink wash edges and grain"},
            "license": "原创自用", "examples": ["原创人物"], "version": "1.0.0",
            "visibility": "private", "schemaVersion": 1,
        }
        body.update(overrides)
        return body

    def test_private_style_and_layout_resolve_favorite_and_boot_scope(self):
        for kind, prefix, bucket in (
            ("style", "USR-S", "styles"), ("layout", "USR-L", "layouts")
        ):
            rid = str(uuid.uuid4())
            data = bridge.put_resource(self.db, self.owner, rid, self.payload(rid, kind))
            resource = data["resource"]
            code = resource["code"]
            self.assertEqual(code, prefix + rid.replace("-", "").upper())
            self.assertEqual(resource["revision"], 1)
            self.assertEqual(resource["visibility"], "private")
            row = self.db.get_conn().execute(
                "SELECT code,kind,owner_user_id,definition,revision FROM user_resources "
                "WHERE id=?", (rid,)
            ).fetchone()
            self.assertEqual(row["code"], code)
            self.assertEqual(row["kind"], kind)
            self.assertEqual(int(row["owner_user_id"]), int(self.owner["id"]))
            self.assertEqual(row["revision"], 1)
            self.assertIn("纸纹", row["definition"])

            mine = resource_registry.resolve(
                self.db.get_conn(), code, viewer=self.owner, purpose="generate")
            self.assertTrue(mine["canUse"])
            self.assertTrue(mine["canCollect"])
            self.assertEqual(mine["source"], "private")
            self.assertIsNone(resource_registry.resolve(
                self.db.get_conn(), code, viewer=self.other, purpose="generate"))
            self.assertIsNone(resource_registry.resolve(
                self.db.get_conn(), code, viewer=None, purpose="view"))
            with self.db.transaction() as tx:
                check_resource_ref(
                    {"id": code, "type": kind, "source": "private", "version": 1},
                    kind, tx, self.owner)
                with self.assertRaises(ServiceError):
                    check_resource_ref(
                        {"id": code, "type": kind, "source": "private", "version": 1},
                        kind, tx, self.other)

            first = toggle_user_collection(self.db, self.owner, bucket, code, action="set")
            second = toggle_user_collection(self.db, self.owner, bucket, code, action="set")
            self.assertTrue(first["collected"])
            self.assertTrue(second["collected"])
            count = self.db.get_conn().execute(
                "SELECT COUNT(*) FROM collections WHERE user_id=? AND bucket=? AND target_id=?",
                (int(self.owner["id"]), bucket, code)).fetchone()[0]
            self.assertEqual(count, 1)
            with self.assertRaises(ServiceError):
                toggle_user_collection(self.db, self.other, bucket, code, action="set")

            owner_boot = build_boot_payload(self.db, self.owner)
            other_boot = build_boot_payload(self.db, self.other)
            anon_boot = build_boot_payload(self.db, None)
            self.assertTrue(any(x["code"] == code and x["source"] == "private"
                                for x in owner_boot.get("myResources", [])))
            for payload in (other_boot, anon_boot):
                self.assertFalse(any(x["code"] == code
                                     for x in payload.get("myResources", [])))
                self.assertNotIn(code, str(payload.get("pendingResources", [])))
                self.assertNotIn(code, str(payload.get("communityResources", [])))

    def test_two_client_cas_noop_update_conflict_and_tombstone(self):
        rid = str(uuid.uuid4())
        payload = self.payload(rid)
        first = bridge.put_resource(self.db, self.owner, rid, payload)["resource"]
        code = first["code"]
        self.assertEqual(first["revision"], 1)
        noop = bridge.put_resource(self.db, self.owner, rid, {**payload, "baseRevision": 1})
        self.assertTrue(noop["unchanged"])
        self.assertEqual(noop["resource"]["code"], code)
        self.assertEqual(noop["resource"]["revision"], 1)
        changed = bridge.put_resource(
            self.db, self.owner, rid,
            {**payload, "name": "作者更新后名称", "baseRevision": 1})["resource"]
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["code"], code)
        with self.assertRaises(ServiceError) as clash:
            bridge.put_resource(
                self.db, self.owner, rid,
                {**payload, "name": "另一设备旧版写入", "baseRevision": 1})
        self.assertEqual(clash.exception.status, 409)
        self.assertEqual(clash.exception.extra["current"]["revision"], 2)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT name,revision FROM user_resources WHERE id=?",
            (rid,)).fetchone()["name"], "作者更新后名称")
        listed = bridge.list_resources(self.db, self.owner, {})
        self.assertTrue(any(x["code"] == code and x["revision"] == 2
                            for x in listed["items"]))
        self.assertEqual(bridge.list_resources(self.db, self.other, {})["items"], [])
        deleted = bridge.delete_resource(self.db, self.owner, rid, "2")["resource"]
        self.assertEqual(deleted["revision"], 3)
        self.assertIsNotNone(deleted["deletedAt"])
        self.assertIsNone(resource_registry.resolve(
            self.db.get_conn(), code, viewer=self.owner))
        self.assertFalse(any(x["code"] == code
                             for x in build_boot_payload(self.db, self.owner)["myResources"]))
        with self.assertRaises(ServiceError) as deleted_again:
            bridge.put_resource(self.db, self.owner, rid, {**payload, "baseRevision": 2})
        self.assertEqual(deleted_again.exception.status, 409)

    def test_actual_web_http_writes_and_skill_http_pulls_same_private_revision(self):
        """Web cookie PUT -> Skill library GET -> signed-in owner-only Web boot."""
        import json
        import os
        import threading
        import urllib.error
        import urllib.request
        from unittest.mock import patch
        from backend.server import create_channel_server, SESSION_COOKIE_NAME

        rid = str(uuid.uuid4())
        body = self.payload(rid, "style")
        with patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "0",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"
        }):
            server = create_channel_server(0, "main", self.db)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                def req(method, path, session, payload=None):
                    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
                    request = urllib.request.Request(
                        base + path, data=raw, method=method,
                        headers={
                            "Origin": "http://trusted.test",
                            "Cookie": SESSION_COOKIE_NAME + "=" + session,
                            "Content-Type": "application/json",
                        })
                    try:
                        response = urllib.request.urlopen(request, timeout=20)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        return response.status, json.loads(response.read().decode("utf-8"))
                created_status, created = req(
                    "PUT", "/api/v1/me/resources/" + rid, self.owner_session, body)
                self.assertEqual(created_status, 200, created)
                code = created["resource"]["code"]
                self.assertEqual(code, "USR-S" + rid.replace("-", "").upper())
                status, listed = req(
                    "GET", "/api/v1/me/resources?limit=20", self.owner_session)
                self.assertEqual(status, 200, listed)
                self.assertEqual(len([x for x in listed["items"] if x["code"] == code]), 1)
                denied_status, denied = req(
                    "GET", "/api/v1/me/resources?limit=20", self.other_session)
                self.assertEqual(denied_status, 200, denied)
                self.assertFalse(any(x.get("code") == code for x in denied["items"]))
                stale_status, stale = req(
                    "PUT", "/api/v1/me/resources/" + rid, self.owner_session,
                    {**body, "name": "过期版本的覆盖", "baseRevision": 0})
                self.assertEqual(stale_status, 409, stale)
                self.assertEqual(stale["code"], "conflict")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(5)

    def test_id_validation_and_cross_account_id_collision(self):
        rid = str(uuid.uuid4())
        with self.assertRaises(ServiceError):
            bridge.put_resource(self.db, self.owner, "not-an-uuid", self.payload(rid))
        with self.assertRaises(ServiceError):
            bridge.put_resource(self.db, self.owner, rid, self.payload(rid, visibility="public"))
        first = bridge.put_resource(self.db, self.owner, rid, self.payload(rid))
        with self.assertRaises(ServiceError) as foreign:
            bridge.put_resource(self.db, self.other, rid, self.payload(rid))
        self.assertEqual(foreign.exception.status, 404)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM user_resources WHERE code=?",
            (first["resource"]["code"],)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
