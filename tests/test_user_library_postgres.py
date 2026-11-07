"""Private gallery HTTP lifecycle against an isolated, fresh V3 PostgreSQL DB."""
import base64
import concurrent.futures
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

from PIL import Image
from backend import user_library
from backend.config import SESSION_COOKIE_NAME
from backend.server import create_channel_server
from backend.services import register_user


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL admin URL not provided")
class PostgresLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from backend.postgres_db import PostgresDatabase
        from ops.bootstrap_postgres_v3 import bootstrap
        cls.admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
        cls.database_name = "handraw_library_test_" + uuid.uuid4().hex[:12]
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.addClassCleanup(cls.drop_database)
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.uploads = root / "uploads"
        environment = patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "0", "HANDRAW_ALLOW_PG_BOOTSTRAP": "YES",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test", "HANDRAW_OBJECT_BUCKET": "",
            "HANDRAW_PRIVATE_STORAGE": str(root), "HANDRAW_UPLOADS_DIR": str(cls.uploads),
            "HANDRAW_GENERATED_DIR": str(root / "generated"), "HANDRAW_REDIS_REQUIRED": "0",
        })
        environment.start()
        cls.addClassCleanup(environment.stop)
        dsn = make_conninfo(cls.admin_dsn, dbname=cls.database_name)
        bootstrap(dsn=dsn, apply=True)
        cls.db = PostgresDatabase(dsn)
        cls.addClassCleanup(cls.db.close)
        cls.db.migrate()
        _, token = register_user(cls.db, "gallery_pg_owner", "IsolatedGalleryPassword!")
        _, other = register_user(cls.db, "gallery_pg_other", "IsolatedGalleryPassword!")
        cls.cookie = f"{SESSION_COOKIE_NAME}={token}"
        cls.other_cookie = f"{SESSION_COOKIE_NAME}={other}"
        cls.server = create_channel_server(0, "main", cls.db, host="127.0.0.1", demo_mode=False)
        cls.addClassCleanup(cls.server.server_close)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.thread.join(5)

    @classmethod
    def drop_database(cls):
        import psycopg
        from psycopg import sql
        assert cls.database_name.startswith("handraw_library_test_")
        with psycopg.connect(cls.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))

    @staticmethod
    def image(color):
        output = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(output, "PNG")
        raw = output.getvalue()
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii"), raw

    def request(self, method, path, payload=None, cookie=None):
        headers = {"Origin": "http://trusted.test", "Accept": "application/json", "Cookie": cookie or self.cookie}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            body = json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw
            return response.status, body

    def sequence(self):
        row = self.db.get_conn().execute("SELECT current_seq FROM library_change_counter WHERE id=1").fetchone()
        return int(row[0]) if row else 0

    def test_concurrent_counter_updates_are_unique_and_committed(self):
        before = self.sequence()
        def increment(_):
            try:
                with self.db.transaction() as tx:
                    return user_library.next_change_seq(tx)
            finally:
                self.db.close_thread_conn()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(increment, range(12)))
        self.assertEqual(sorted(values), list(range(before + 1, before + 13)))
        self.assertEqual(self.sequence(), before + 12)

    def test_http_upload_update_delete_restore_and_private_image(self):
        uid = str(uuid.uuid4())
        path = "/api/library/assets/" + uid
        data, raw = self.image((17, 88, 122))
        status, created = self.request("PUT", path, {"name": "私有测试图", "cat": "props", "dataUrl": data})
        self.assertEqual(status, 201, created)
        self.assertEqual(created["revision"], 1)
        first_seq = self.sequence()
        self.assertEqual(self.request("GET", created["imageUrl"]), (200, raw))
        self.assertIn(self.request("GET", created["imageUrl"], cookie=self.other_cookie)[0], (403, 404))
        duplicate = "/api/library/assets/" + str(uuid.uuid4())
        status, deduped = self.request("PUT", duplicate, {"name": "同内容", "dataUrl": data})
        self.assertEqual(status, 200, deduped)
        self.assertEqual(deduped["uid"], uid)
        self.assertEqual(self.sequence(), first_seq)
        status, updated = self.request("PUT", path, {"baseRevision": 1, "name": "修改名称"})
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["revision"], 2)
        self.assertGreater(self.sequence(), first_seq)
        update_seq = self.sequence()
        status, conflict = self.request("PUT", path, {"baseRevision": 1, "name": "旧版本"})
        self.assertEqual(status, 409, conflict)
        self.assertEqual(self.sequence(), update_seq)
        status, incremental = self.request("GET", "/api/library/assets?since=" + str(first_seq))
        self.assertEqual(status, 200, incremental)
        self.assertEqual(incremental["items"][0]["uid"], uid)
        self.assertEqual(incremental["items"][0]["revision"], 2)
        status, deleted = self.request("DELETE", path + "?baseRevision=2")
        self.assertEqual(status, 200, deleted)
        self.assertEqual(deleted["revision"], 3)
        self.assertTrue(deleted["deletedAt"])
        self.assertGreater(self.sequence(), update_seq)
        delete_seq = self.sequence()
        status, restored = self.request("POST", path + "/restore", {})
        self.assertEqual(status, 200, restored)
        self.assertEqual(restored["revision"], 4)
        self.assertIsNone(restored["deletedAt"])
        self.assertGreater(self.sequence(), delete_seq)

    def test_failed_save_rolls_back_sequence_and_file_then_retries_same_uid(self):
        uid = str(uuid.uuid4())
        path = "/api/library/assets/" + uid
        data, _ = self.image((220, 15, 78))
        before = self.sequence()
        files_before = set(self.uploads.glob("*"))
        original = user_library.next_change_seq
        def fail_after_increment(tx):
            original(tx)
            raise RuntimeError("injected gallery save failure")
        with patch.object(user_library, "next_change_seq", side_effect=fail_after_increment):
            status, failed = self.request("PUT", path, {"name": "可重试测试图", "dataUrl": data})
        self.assertEqual(status, 500, failed)
        self.assertNotIn("injected gallery save failure", str(failed))
        self.assertEqual(self.sequence(), before)
        self.assertEqual(set(self.uploads.glob("*")), files_before)
        self.assertIsNone(self.db.get_conn().execute("SELECT id FROM user_uploads WHERE asset_uid=?", (uid,)).fetchone())
        status, saved = self.request("PUT", path, {"name": "可重试测试图", "dataUrl": data})
        self.assertEqual(status, 201, saved)
        self.assertEqual(saved["uid"], uid)
        self.assertEqual(self.db.get_conn().execute("SELECT COUNT(*) FROM user_uploads WHERE asset_uid=?", (uid,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
