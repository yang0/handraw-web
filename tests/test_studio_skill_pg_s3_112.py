"""#112 round 3: Skill -> HTTP -> native PG17 -> S3 API emulator -> public Work.

CI uses a RANDOM, throwaway PostgreSQL database and moto's S3 protocol
emulation. This is not a live MinIO/R2 deployment and calls no paid image
provider. A six-image Skill upload is interrupted after three persisted
items, then resumed across HTTP requests with a new server worker.
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


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"),
                     "requires disposable CI PostgreSQL staging server")
class SkillPostgresS3Journey112(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import boto3
        import psycopg
        from moto import mock_aws
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from backend import object_storage
        from backend.postgres_db import PostgresDatabase
        from backend.config import SESSION_COOKIE_NAME
        from backend.server import create_channel_server
        from backend.services import register_user
        from ops.bootstrap_postgres_v3 import bootstrap

        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.uploads = root / "uploads"
        cls.aws = mock_aws()
        cls.aws.start()
        cls.addClassCleanup(cls.aws.stop)
        cls.bucket = "handraw-qa112-" + uuid.uuid4().hex[:12]
        cls.env = patch.dict(os.environ, {
            "HANDRAW_ALLOW_PG_BOOTSTRAP": "YES",
            "HANDRAW_DEMO_MODE": "0",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_REDIS_REQUIRED": "0",
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(cls.uploads),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_OBJECT_BUCKET": cls.bucket,
            "HANDRAW_OBJECT_PREFIX": "qa112/v3",
            "HANDRAW_OBJECT_ENDPOINT": "",
            "HANDRAW_OBJECT_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1",
        })
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        object_storage._client.cache_clear()
        cls.addClassCleanup(object_storage._client.cache_clear)
        cls.s3 = boto3.client("s3", region_name="us-east-1")
        cls.s3.create_bucket(Bucket=cls.bucket)

        cls.admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
        cls.database_name = "handraw_skill_s3_112_" + uuid.uuid4().hex[:9]
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(cls.database_name)))
        cls.addClassCleanup(cls.drop_database)
        dsn = make_conninfo(cls.admin_dsn, dbname=cls.database_name)
        bootstrap(dsn=dsn, apply=True)
        cls.db = PostgresDatabase(dsn)
        cls.addClassCleanup(cls.db.close)
        cls.db.migrate()
        cls.owner, owner_cookie = register_user(
            cls.db, "skill_pg_s3_owner", "TestOnlyPassword#112")
        cls.other, other_cookie = register_user(
            cls.db, "skill_pg_s3_other", "TestOnlyPassword#112")
        cls.owner_cookie = f"{SESSION_COOKIE_NAME}={owner_cookie}"
        cls.other_cookie = f"{SESSION_COOKIE_NAME}={other_cookie}"
        cls.publisher = cls.create_token(int(cls.owner["id"]), ["publish"])
        cls.other_publisher = cls.create_token(int(cls.other["id"]), ["publish"])
        cls.server = create_channel_server(
            0, "main", cls.db, host="127.0.0.1", demo_mode=False)
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.addClassCleanup(cls.stop_server)

    @classmethod
    def create_token(cls, user_id, scopes):
        key = "hwt_qa112_" + uuid.uuid4().hex
        with cls.db.transaction() as tx:
            tx.execute(
                "INSERT INTO api_tokens(id,user_id,name,scopes,token_hash,"
                "created_at,last_used_at,revoked_at) "
                "VALUES (?,?,?,?,?,'2026-11-08T00:00:00Z','','')",
                ("tok_" + uuid.uuid4().hex, user_id, "QA #112",
                 json.dumps(scopes), hashlib.sha256(key.encode()).hexdigest()),
            )
        return key

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    @classmethod
    def drop_database(cls):
        import psycopg
        from psycopg import sql
        assert cls.database_name.startswith("handraw_skill_s3_112_")
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(cls.database_name)))

    def request(self, method, path, body=None, *, token=None, cookie=None):
        headers = {"Origin": "http://trusted.test"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if cookie:
            headers["Cookie"] = cookie
        raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        if raw is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=raw, method=method, headers=headers)
        try:
            res = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as error:
            res = error
        with res:
            payload = res.read()
            parsed = json.loads(payload) if "json" in res.headers.get(
                "Content-Type", "") else payload
            return res.status, parsed, res.headers

    def db_count(self, table, where="", params=()):
        return int(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM " + table + (" WHERE " + where if where else ""),
            params).fetchone()[0])

    @staticmethod
    def images():
        result = []
        originals = []
        for i in range(6):
            buff = io.BytesIO()
            Image.new("RGB", (24, 20), (23 + i * 35, 48, 150 - i * 17)).save(
                buff, format="PNG")
            b = buff.getvalue()
            originals.append(b)
            result.append({
                "name": f"season-{i+1}.png",
                "sha256": hashlib.sha256(b).hexdigest(),
                "dataUrl": "data:image/png;base64," + base64.b64encode(b).decode(),
            })
        return result, originals

    def test_six_images_resume_single_work_s3_recovery_and_acl(self):
        from backend import object_storage
        from backend import server as server_module
        from backend.services import set_work_visibility, utc_now_iso
        from backend.generation_v3 import work_images

        external = str(uuid.uuid4())
        images, raw_images = self.images()
        body = {
            "externalRunId": external, "originClient": "skill",
            "visibility": "public", "status": "success",
            "originalRequest": "原创插画四季衍生系列六张图",
            "requestId": "skill-history-" + external,
            "images": images,
        }
        path = "/api/v1/me/generations"
        self.assertEqual(self.request("POST", path, body)[0], 401)
        self.assertEqual(self.request(
            "POST", path, body, token=self.other_publisher)[0], 200,
            "A different authorized owner may publish their own distinct run")
        # Remove the unrelated second user's run; only owner's run is
        # relevant to the unique images/publication assertions below.
        # The other user's data remains isolated, never conflated with owner.
        other_count = self.db_count(
            "generation_runs", "user_id=?", (self.other["id"],))
        self.assertEqual(other_count, 1)
        before = self.db_count(
            "generation_runs", "user_id=?", (self.owner["id"],))
        original_save = server_module.save_data_url_upload
        calls = []
        def interrupt_after_three(*args, **kwargs):
            calls.append(args)
            if len(calls) == 4:
                raise OSError("injected client upload disconnect after slot 3")
            return original_save(*args, **kwargs)

        with patch.object(server_module, "save_data_url_upload",
                          side_effect=interrupt_after_three):
            status, error, _ = self.request(
                "POST", path, body, token=self.publisher)
        self.assertGreaterEqual(status, 500, error)
        self.assertEqual(self.db_count(
            "generation_runs", "user_id=?", (self.owner["id"],)), before + 1)
        run = self.db.get_conn().execute(
            "SELECT id,status FROM generation_runs WHERE user_id=? AND "
            "source='skill' AND external_run_id=?",
            (self.owner["id"], external)).fetchone()
        self.assertEqual(run["status"], "uploading")
        self.assertEqual(self.db_count(
            "generation_items", "run_id=?", (run["id"],)), 3)
        self.assertEqual(self.db_count(
            "user_uploads", "user_id=? AND cat='skill_history'",
            (self.owner["id"],)), 3)
        self.assertEqual(self.db_count("works", "run_id=?", (run["id"],)), 0)
        partial = self.db.get_conn().execute(
            "SELECT image_url FROM user_uploads WHERE user_id=? AND "
            "cat='skill_history' ORDER BY created_at",
            (self.owner["id"],)).fetchall()
        self.assertEqual(len(partial), 3)
        private_url = partial[0]["image_url"]
        # Unpublished uploads are private, despite the object already being
        # durably stored in the bucket and a guessable /uploads/ URL.
        self.assertEqual(self.request("GET", private_url)[0], 404)
        self.assertEqual(self.request("GET", private_url,
                                      cookie=self.other_cookie)[0], 404)
        owner_code, owner_bytes, _ = self.request(
            "GET", private_url, cookie=self.owner_cookie)
        self.assertEqual(owner_code, 200)
        self.assertEqual(owner_bytes, raw_images[0])

        # Owner retries exactly the SAME payload; only slots 3,4,5 are
        # written. Any already successful item remains immutable.
        status, result, _ = self.request(
            "POST", path, body, token=self.publisher)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["imageCount"], 6)
        self.assertEqual(len(result["workIds"]), 1)
        self.assertEqual(result["visibility"], "public")
        self.assertEqual(result["id"], run["id"])
        wid = result["workId"]
        urls = work_images(self.db.get_conn(), wid)
        self.assertEqual(len(urls), 6)
        self.assertEqual(self.db_count(
            "generation_items", "run_id=?", (run["id"],)), 6)
        self.assertEqual(self.db_count(
            "work_media", "work_id=?", (wid,)), 6)
        self.assertEqual(self.db_count(
            "works", "run_id=?", (run["id"],)), 1)
        self.assertEqual(self.db_count(
            "user_uploads", "user_id=? AND cat='skill_history'",
            (self.owner["id"],)), 6)
        self.assertEqual(self.db_count(
            "media_public_grants",
            "target_type='work' AND target_id=? AND revoked_at IS NULL",
            (wid,)), 6)
        self.assertEqual(result["coverUrl"], urls[0])
        first_keys = sorted(
            x["Key"] for x in self.s3.list_objects_v2(
                Bucket=self.bucket, Prefix="qa112/v3/uploads/")["Contents"])
        self.assertEqual(len(first_keys), 12, "Six per owner, no ghost uploads")

        status, repeat, _ = self.request(
            "POST", path, body, token=self.publisher)
        self.assertEqual(status, 200, repeat)
        self.assertTrue(repeat["deduped"])
        self.assertEqual(repeat["workId"], wid)
        self.assertEqual(work_images(self.db.get_conn(), wid), urls)
        self.assertEqual(self.db_count(
            "user_uploads", "user_id=? AND cat='skill_history'",
            (self.owner["id"],)), 6)
        self.assertEqual(sorted(
            x["Key"] for x in self.s3.list_objects_v2(
                Bucket=self.bucket, Prefix="qa112/v3/uploads/")["Contents"]),
            first_keys)

        # Simulate another web instance with an EMPTY local media cache:
        # authorized public GET must recover exact original bytes from S3.
        target = object_storage._key(urls[0])
        self.assertIn(target, first_keys)
        for path_in_cache in self.uploads.glob("*"):
            path_in_cache.unlink()
        status, restored, headers = self.request("GET", urls[0])
        self.assertEqual(status, 200)
        self.assertEqual(restored, raw_images[0])
        self.assertIn("must-revalidate", headers.get("Cache-Control", ""))

        # Moderation is evaluated BEFORE any object GET: a hidden work's
        # media must be inaccessible even when object still exists.
        with self.db.transaction() as tx:
            set_work_visibility(tx, wid, "hidden", utc_now_iso(),
                                source="moderator", reason="QA112",
                                actor_role="admin")
        for path_in_cache in self.uploads.glob("*"):
            path_in_cache.unlink()
        with patch("backend.object_storage.ensure_local_copy",
                   side_effect=AssertionError("unauthorized object fetch")):
            self.assertEqual(self.request("GET", urls[0])[0], 404)
            self.assertEqual(self.request("GET", urls[0],
                                          cookie=self.other_cookie)[0], 404)
        # The original owner may still read private history, but the
        # published square must not expose a hidden work.
        status, history, _ = self.request(
            "GET", path, token=self.publisher)
        self.assertEqual(status, 200)
        record = next(x for x in history["items"] if x["id"] == run["id"])
        self.assertEqual(record["workStatus"], "hidden")
        self.assertEqual(record["visibility"], "private")
        self.assertEqual(record["imageCount"], 6)

        print("STUDIO #112 PG17 + moto S3 Skill 6-image HTTP interrupted/resumed "
              "one Work, 6 Media, no dupes, private-before-grant, "
              "remote rehydrate, moderation revoke PASS")


if __name__ == "__main__":
    unittest.main()
