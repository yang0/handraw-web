"""Tests for Phase 3c-1: User Asset Library and Bi-directional Synchronization Backend.

Covers:
1. Incremental pull & cursor pagination (since, nextCursor, hasMore, tombstones with deletedAt).
2. Monotonic unique change_seq under concurrent writes.
3. Optimistic concurrency control (revision, 409 conflict, current version payload).
4. Image content deduplication by sha256 within user account.
5. Image validation (size limits, Pillow decoding, fake format rejection, sha256 consistency).
6. Cross-user isolation (foreign asset operations return 404).
7. API token scope enforcement ('library' scope allowed, 'publish' rejected with 403, 1200/hr rate limit).
8. Soft deletion and restore lifecycle (visibility in workspace, canvas selector, and since/non-since sync).
9. User quota enforcement (500 assets limit, 1GB storage limit returning 413).
10. Backward compatibility with legacy POST /api/uploads (auto-assigned sync fields, appears in sync).
11. Migration 064 idempotence and legacy database upgrade safety.
"""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.config import SESSION_COOKIE_NAME
from backend.db import Database, utc_now_iso
from backend.server import HandrawRequestHandler, init_database
from backend.services import register_user, get_studio_workspace
from backend.user_library import (
    MAX_ASSETS_PER_USER,
    MAX_STORAGE_BYTES_PER_USER,
    TOKEN_RATE_LIMIT_PER_HOUR,
    MAX_RATE_LIMIT_KEYS,
    MAX_IMAGE_PIXELS,
    next_change_seq,
    ensure_user_uploads_synced,
    check_token_rate_limit,
    cleanup_expired_library_tombstones,
    is_media_referenced,
    _token_rate_logs,
)


def _make_data_url(color=(200, 50, 50), fmt="PNG", size=(10, 10)) -> tuple[str, str, bytes]:
    im = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    raw = buf.getvalue()
    b64 = base64.b64encode(raw).decode("ascii")
    mime = "image/png" if fmt.upper() == "PNG" else "image/webp"
    data_url = f"data:{mime};base64,{b64}"
    sha = hashlib.sha256(raw).hexdigest()
    return data_url, sha, raw


def _uid(name: str) -> str:
    """Return a deterministic valid UUIDv5 string for test isolation."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


class UserLibrarySyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "library_sync_test.db"
        self.uploads_dir = root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir = root / "generated"
        self.generated_dir.mkdir(parents=True, exist_ok=True)

        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(self.uploads_dir),
                "HANDRAW_GENERATED_DIR": str(self.generated_dir),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE": "0",
            },
        )
        self.env.start()
        self.db = init_database(self.db_path)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        self.user_a, token_a = register_user(self.db, "sync_alice", "AlicePass123")
        self.user_b, token_b = register_user(self.db, "sync_bob", "BobPass123")
        self.cookie_a = f"{SESSION_COOKIE_NAME}={token_a}"
        self.cookie_b = f"{SESSION_COOKIE_NAME}={token_b}"

        # Clear rate limit logs between test runs
        _token_rate_logs.clear()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def _create_token(self, user_id: int, scopes: list[str], name: str = "TestToken") -> str:
        raw_token = f"hwt_test_{hashlib.sha256(os.urandom(16)).hexdigest()}"
        tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        tok_id = f"tok_{os.urandom(8).hex()}"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO api_tokens (id, user_id, name, scopes, token_hash, created_at, last_used_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, '2026-10-31T00:00:00Z', '', '')
                """,
                (tok_id, user_id, name, json.dumps(scopes), tok_hash),
            )
        return raw_token

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        cookie: str | None = None,
        bearer: str | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict, bytes]:
        req_headers = {"Origin": "http://trusted.test"}
        if cookie:
            req_headers["Cookie"] = cookie
        if bearer:
            req_headers["Authorization"] = f"Bearer {bearer}"
        if headers:
            req_headers.update(headers)

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except Exception:
                    parsed = {}
                self.db.close_thread_conn()
                return resp.status, parsed, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = {}
            self.db.close_thread_conn()
            return exc.code, parsed, raw

    def test_01_incremental_pull_and_cursor_pagination(self):
        """Test GET /api/library/assets with and without since, nextCursor, and tombstones."""
        # 1. Create 3 assets for Alice
        d1, sha1, _ = _make_data_url(color=(10, 10, 10))
        d2, sha2, _ = _make_data_url(color=(20, 20, 20))
        d3, sha3, _ = _make_data_url(color=(30, 30, 30))
        u1, u2, u3 = _uid("1"), _uid("2"), _uid("3")

        s1, res1, _ = self._request("PUT", f"/api/library/assets/{u1}", {"name": "Item 1", "dataUrl": d1, "cat": "characters"}, cookie=self.cookie_a)
        s2, res2, _ = self._request("PUT", f"/api/library/assets/{u2}", {"name": "Item 2", "dataUrl": d2, "cat": "props"}, cookie=self.cookie_a)
        s3, res3, _ = self._request("PUT", f"/api/library/assets/{u3}", {"name": "Item 3", "dataUrl": d3, "cat": "scenes"}, cookie=self.cookie_a)
        self.assertEqual(s1, 201)
        self.assertEqual(s2, 201)
        self.assertEqual(s3, 201)

        # 2. Query all undeleted assets (without since) with limit=2
        s, p1, _ = self._request("GET", "/api/library/assets?limit=2", cookie=self.cookie_a)
        self.assertEqual(s, 200)
        self.assertEqual(len(p1["items"]), 2)
        self.assertTrue(p1["hasMore"])
        cursor1 = p1["nextCursor"]
        self.assertIsNotNone(cursor1)
        self.assertEqual(p1["items"][0]["uid"], u1)
        self.assertEqual(p1["items"][1]["uid"], u2)

        # 3. Pull page 2 using cursor1
        s, p2, _ = self._request("GET", f"/api/library/assets?since={cursor1}&limit=2", cookie=self.cookie_a)
        self.assertEqual(s, 200)
        self.assertEqual(len(p2["items"]), 1)
        self.assertFalse(p2["hasMore"])
        self.assertEqual(p2["items"][0]["uid"], u3)
        cursor2 = p2["nextCursor"]

        # 4. Modify Item 2 (baseRevision=1) and soft-delete Item 1
        s_up, _, _ = self._request("PUT", f"/api/library/assets/{u2}", {"baseRevision": 1, "name": "Item 2 Updated"}, cookie=self.cookie_a)
        self.assertEqual(s_up, 200)
        s_del, del_res, _ = self._request("DELETE", f"/api/library/assets/{u1}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)
        self.assertIsNotNone(del_res["tombstone"]["deletedAt"])

        # 5. Incremental pull since cursor2: should return updated Item 2 and tombstone Item 1
        s, p3, _ = self._request("GET", f"/api/library/assets?since={cursor2}", cookie=self.cookie_a)
        self.assertEqual(s, 200)
        self.assertEqual(len(p3["items"]), 2)
        # Order by change_seq ASC: Item 2 updated first (seq 4), Item 1 deleted second (seq 5)
        self.assertEqual(p3["items"][0]["uid"], u2)
        self.assertEqual(p3["items"][0]["name"], "Item 2 Updated")
        self.assertIsNone(p3["items"][0]["deletedAt"])
        self.assertEqual(p3["items"][0]["revision"], 2)

        self.assertEqual(p3["items"][1]["uid"], u1)
        self.assertIsNotNone(p3["items"][1]["deletedAt"])
        self.assertEqual(p3["items"][1]["revision"], 2)

        # 6. Non-since pull now only returns undeleted: Item 2 and Item 3
        s, all_undel, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s, 200)
        uids = [it["uid"] for it in all_undel["items"]]
        self.assertEqual(set(uids), {u2, u3})
        self.assertNotIn(u1, uids)

    def test_02_concurrent_change_seq_monotonically_unique(self):
        """Test that concurrent writes generate strictly unique and monotonically increasing change_seq."""
        num_threads = 16
        results: list[int] = []
        lock = threading.Lock()

        def _worker(idx: int):
            with self.db.transaction() as tx:
                seq = next_change_seq(tx)
                with lock:
                    results.append(seq)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_worker, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(results), num_threads)
        # Verify strictly unique and sorted covers 1..num_threads
        sorted_results = sorted(results)
        self.assertEqual(len(set(sorted_results)), num_threads)
        self.assertEqual(sorted_results, list(range(1, num_threads + 1)))

    def test_03_optimistic_locking_and_409(self):
        """Test optimistic concurrency control: 409 conflict when baseRevision mismatches."""
        d, _, _ = _make_data_url(color=(40, 40, 40))
        u_lock = _uid("lock")
        # Create initial asset (revision 1)
        s, res, _ = self._request("PUT", f"/api/library/assets/{u_lock}", {"name": "Initial", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s, 201)
        self.assertEqual(res["revision"], 1)

        # Updating without baseRevision -> 400
        s_no_rev, err_no_rev, _ = self._request("PUT", f"/api/library/assets/{u_lock}", {"name": "Fail"}, cookie=self.cookie_a)
        self.assertEqual(s_no_rev, 400)
        self.assertEqual(err_no_rev.get("code"), "missing_base_revision")

        # Two concurrent updates with baseRevision=1: exactly one succeeds, the other gets 409
        status_codes = []
        responses = []

        def _update(name: str):
            st, body, _ = self._request(
                "PUT",
                f"/api/library/assets/{u_lock}",
                {"baseRevision": 1, "name": name},
                cookie=self.cookie_a,
            )
            status_codes.append(st)
            responses.append(body)

        t1 = threading.Thread(target=_update, args=("Winner A",))
        t2 = threading.Thread(target=_update, args=("Winner B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn(200, status_codes)
        self.assertIn(409, status_codes)

        conflict_res = next(r for r in responses if r.get("code") == "conflict")
        self.assertIn("current", conflict_res)
        self.assertEqual(conflict_res["current"]["revision"], 2)

        # DELETE with mismatched baseRevision also returns 409
        s_del_conflict, del_err, _ = self._request("DELETE", f"/api/library/assets/{u_lock}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del_conflict, 409)
        self.assertEqual(del_err.get("code"), "conflict")

    def test_04_deduplication_by_sha256(self):
        """Test that uploading the same image twice under one account reuses existing asset."""
        d, sha, raw = _make_data_url(color=(50, 50, 50))
        u_orig, u_dup, u_bob = _uid("orig"), _uid("dup"), _uid("bob")
        s1, res1, _ = self._request("PUT", f"/api/library/assets/{u_orig}", {"name": "Orig", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s1, 201)
        self.assertFalse(res1.get("deduped", True))
        self.assertEqual(res1["uid"], u_orig)

        # Second upload with same image content for same user
        s2, res2, _ = self._request("PUT", f"/api/library/assets/{u_dup}", {"name": "Dup", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s2, 200)
        self.assertTrue(res2.get("deduped"))
        self.assertEqual(res2["uid"], u_orig)  # Existing asset returned

        # Verify only one file exists on disk
        files = list(self.uploads_dir.glob("UPL-*"))
        self.assertEqual(len(files), 1)

        # Bob uploads the same image -> should NOT be deduped against Alice's image
        s_bob, res_bob, _ = self._request("PUT", f"/api/library/assets/{u_bob}", {"name": "Bob's Copy", "dataUrl": d}, cookie=self.cookie_b)
        self.assertEqual(s_bob, 201)
        self.assertFalse(res_bob.get("deduped", True))
        self.assertEqual(res_bob["uid"], u_bob)

    def test_05_image_validation_and_tampering(self):
        """Test that invalid images, fake formats, and sha256 tampering are rejected."""
        # 1. Fake PNG (plain text disguised as image/png)
        fake_b64 = base64.b64encode(b"not a real image at all").decode("ascii")
        fake_url = f"data:image/png;base64,{fake_b64}"
        u_fake, u_wrong_sha = _uid("fake"), _uid("wrong_sha")
        s1, err1, _ = self._request("PUT", f"/api/library/assets/{u_fake}", {"name": "Fake", "dataUrl": fake_url}, cookie=self.cookie_a)
        self.assertEqual(s1, 400)

        # 2. Sha256 mismatch
        d, sha, _ = _make_data_url(color=(60, 60, 60))
        wrong_sha = "0" * 64
        s2, err2, _ = self._request("PUT", f"/api/library/assets/{u_wrong_sha}", {"name": "Wrong Sha", "dataUrl": d, "sha256": wrong_sha}, cookie=self.cookie_a)
        self.assertEqual(s2, 400)
        self.assertEqual(err2.get("code"), "sha256_mismatch")

    def test_06_foreign_asset_404_isolation(self):
        """Test that assets belonging to another user always return 404."""
        d, _, _ = _make_data_url(color=(70, 70, 70))
        u_alice = _uid("alice_priv")
        s_create, _, _ = self._request("PUT", f"/api/library/assets/{u_alice}", {"name": "Secret", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_create, 201)

        # Bob attempts GET image, DELETE, and POST restore -> all 404
        s_get, _, _ = self._request("GET", f"/api/library/assets/{u_alice}/image", cookie=self.cookie_b)
        self.assertEqual(s_get, 404)

        s_del, _, _ = self._request("DELETE", f"/api/library/assets/{u_alice}", cookie=self.cookie_b)
        self.assertEqual(s_del, 404)

        s_res, _, _ = self._request("POST", f"/api/library/assets/{u_alice}/restore", cookie=self.cookie_b)
        self.assertEqual(s_res, 404)

        # Bob's asset listing does not reveal Alice's asset
        s_list, b_list, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_b)
        self.assertEqual(s_list, 200)
        self.assertEqual(len(b_list["items"]), 0)

    def test_07_token_scope_and_rate_limit(self):
        """Test token scopes ('library' vs 'publish') and 1200/hr rate limiting."""
        tok_lib = self._create_token(self.user_a["id"], ["library"], "LibToken")
        tok_pub = self._create_token(self.user_a["id"], ["publish"], "PubToken")

        # 1. Unauthenticated request -> 401
        s_unauth, _, _ = self._request("GET", "/api/library/assets")
        self.assertEqual(s_unauth, 401)

        # 2. 'publish' only token -> 403 on all library endpoints
        u_pub, u_tok = _uid("pub"), _uid("token")
        s_pub_get, _, _ = self._request("GET", "/api/library/assets", bearer=tok_pub)
        self.assertEqual(s_pub_get, 403)
        s_pub_put, _, _ = self._request("PUT", f"/api/library/assets/{u_pub}", {"name": "Pub"}, bearer=tok_pub)
        self.assertEqual(s_pub_put, 403)

        # 3. 'library' token -> 200 / 201
        d, _, _ = _make_data_url(color=(80, 80, 80))
        s_lib_put, _, _ = self._request("PUT", f"/api/library/assets/{u_tok}", {"name": "Token Item", "dataUrl": d}, bearer=tok_lib)
        self.assertEqual(s_lib_put, 201)

        s_lib_get, list_res, _ = self._request("GET", "/api/library/assets", bearer=tok_lib)
        self.assertEqual(s_lib_get, 200)
        self.assertEqual(len(list_res["items"]), 1)

        # GET image via library token
        s_img, _, img_bytes = self._request("GET", f"/api/library/assets/{u_tok}/image", bearer=tok_lib)
        self.assertEqual(s_img, 200)
        self.assertTrue(len(img_bytes) > 0)

        # 4. Rate limiting: test limiter rejection
        token_key = f"tok_test_rl_{os.urandom(4).hex()}"
        # Populate up to limit
        for _ in range(TOKEN_RATE_LIMIT_PER_HOUR):
            self.assertTrue(check_token_rate_limit(token_key, limit=TOKEN_RATE_LIMIT_PER_HOUR))
        # Exceeded limit
        self.assertFalse(check_token_rate_limit(token_key, limit=TOKEN_RATE_LIMIT_PER_HOUR))

    def test_08_soft_delete_and_restore_lifecycle(self):
        """Test soft delete, absence from workspace and canvas, and restoration within 30 days."""
        d, _, _ = _make_data_url(color=(90, 90, 90))
        u_life = _uid("life")
        s_put, _, _ = self._request("PUT", f"/api/library/assets/{u_life}", {"name": "Lifecycle", "dataUrl": d, "cat": "characters"}, cookie=self.cookie_a)
        self.assertEqual(s_put, 201)

        # Verify present in workspace uploads via API
        s_ws1, ws_before, _ = self._request("GET", "/api/studio/workspace", cookie=self.cookie_a)
        self.assertEqual(s_ws1, 200)
        self.assertTrue(any(u.get("name_zh") == "Lifecycle" for u in ws_before.get("uploads", [])))

        # Verify present in canvas references (/data/benchmark-assets.json)
        s_ref1, ref_before, _ = self._request("GET", "/data/benchmark-assets.json", cookie=self.cookie_a)
        self.assertEqual(s_ref1, 200)
        self.assertTrue(any(r["name"] == "Lifecycle" for r in ref_before.get("assets", [])))

        # Soft delete (requires baseRevision=1)
        s_del, del_tomb, _ = self._request("DELETE", f"/api/library/assets/{u_life}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)
        self.assertIsNotNone(del_tomb["item"]["deletedAt"])

        # Disappears from workspace uploads
        s_ws2, ws_after, _ = self._request("GET", "/api/studio/workspace", cookie=self.cookie_a)
        self.assertEqual(s_ws2, 200)
        self.assertFalse(any(u.get("name_zh") == "Lifecycle" for u in ws_after.get("uploads", [])))

        # Disappears from canvas references
        s_ref2, ref_after, _ = self._request("GET", "/data/benchmark-assets.json", cookie=self.cookie_a)
        self.assertEqual(s_ref2, 200)
        self.assertFalse(any(r["name"] == "Lifecycle" for r in ref_after.get("assets", [])))

        # Disappears from non-since GET /api/library/assets
        s_list, l_res, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_list, 200)
        self.assertNotIn(u_life, [it["uid"] for it in l_res["items"]])

        # Image endpoint returns 404 while soft-deleted
        s_img_del, _, _ = self._request("GET", f"/api/library/assets/{u_life}/image", cookie=self.cookie_a)
        self.assertEqual(s_img_del, 404)

        # Restore
        s_rest, rest_res, _ = self._request("POST", f"/api/library/assets/{u_life}/restore", cookie=self.cookie_a)
        self.assertEqual(s_rest, 200)
        self.assertIsNone(rest_res["deletedAt"])

        # Reappears in workspace uploads
        s_ws3, ws_restored, _ = self._request("GET", "/api/studio/workspace", cookie=self.cookie_a)
        self.assertEqual(s_ws3, 200)
        self.assertTrue(any(u.get("name_zh") == "Lifecycle" for u in ws_restored.get("uploads", [])))

        # Reappears in non-since GET /api/library/assets
        s_list_rest, l_rest_res, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_list_rest, 200)
        self.assertIn(u_life, [it["uid"] for it in l_rest_res["items"]])

        # Expired restore test (> 30 days)
        with self.db.transaction() as tx:
            expired_time = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
            tx.execute("UPDATE user_uploads SET deleted_at = ? WHERE asset_uid = ?", (expired_time, u_life))

        s_exp, err_exp, _ = self._request("POST", f"/api/library/assets/{u_life}/restore", cookie=self.cookie_a)
        self.assertEqual(s_exp, 410)
        self.assertEqual(err_exp.get("code"), "asset_expired")

    def test_09_quotas_enforcement(self):
        """Test count quota (500 assets) and storage quota (1 GB)."""
        # Test count quota: mock 500 assets in database
        with self.db.transaction() as tx:
            for i in range(500):
                tx.execute(
                    """
                    INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                    VALUES (?, ?, 'other', ?, '/test.png', '', 100, '2026-10-31T00:00:00Z', ?, 1, ?, '2026-10-31T00:00:00Z')
                    """,
                    (f"UPL-dummy-{i}", self.user_a["id"], f"Dummy {i}", _uid(f"dummy_{i}"), i + 1),
                )

        d, _, _ = _make_data_url(color=(100, 100, 100))
        u_501 = _uid("501")
        s_501, err_501, _ = self._request("PUT", f"/api/library/assets/{u_501}", {"name": "Overflow", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_501, 413)
        self.assertEqual(err_501.get("code"), "asset_count_quota_exceeded")

        # Test storage quota on user_b: set dummy usage close to 1GB
        u_huge = _uid("huge")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                VALUES ('UPL-huge', ?, 'other', 'Huge', '/test.png', '', ?, '2026-10-31T00:00:00Z', ?, 1, 1000, '2026-10-31T00:00:00Z')
                """,
                (self.user_b["id"], MAX_STORAGE_BYTES_PER_USER - 5, u_huge),
            )

        # Upload a 76-byte image on user_b -> exceeds remaining 5 bytes -> 413
        u_overflow = _uid("storage_overflow")
        s_storage, err_storage, _ = self._request("PUT", f"/api/library/assets/{u_overflow}", {"name": "Too Big", "dataUrl": d}, cookie=self.cookie_b)
        self.assertEqual(s_storage, 413)
        self.assertEqual(err_storage.get("code"), "asset_storage_quota_exceeded")

    def test_10_legacy_uploads_compatibility(self):
        """Test that POST /api/uploads populates sync columns and appears in GET /api/library/assets."""
        d, sha, _ = _make_data_url(color=(110, 110, 110))
        status, res, _ = self._request(
            "POST",
            "/api/uploads",
            {"dataUrl": d, "nameZh": "Legacy Web Upload", "cat": "props"},
            cookie=self.cookie_a,
        )
        self.assertEqual(status, 200)
        self.assertTrue(res.get("ok"))
        up_id = res.get("id")

        # Verify DB row has sync columns populated
        row = self.db.get_conn().execute("SELECT * FROM user_uploads WHERE id = ?", (up_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["asset_uid"])
        self.assertEqual(row["sha256"], sha)
        self.assertEqual(row["revision"], 1)
        self.assertIsNotNone(row["change_seq"])
        self.assertEqual(row["origin"], "web")

        # Verify it appears in library sync GET
        s_sync, sync_res, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_sync, 200)
        item = next((it for it in sync_res["items"] if it["name"] == "Legacy Web Upload"), None)
        self.assertIsNotNone(item)
        self.assertEqual(item["uid"], row["asset_uid"])
        self.assertEqual(item["sha256"], sha)
        self.assertEqual(item["cat"], "props")

    def test_11_migration_064_safety_and_idempotence(self):
        """Test that Migration 064 is idempotent and backfills legacy rows without corruption."""
        # 1. Calling db.migrate() again is safe and returns empty list (nothing unapplied)
        applied = self.db.migrate()
        self.assertEqual(applied, [])

        # 2. Insert a legacy row with NULL asset_uid and NULL change_seq
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, desc_zh, image_url, file_path, bytes, created_at)
                VALUES ('UPL-legacy-001', ?, 'scenes', 'Old Scene', 'Desc', '/uploads/old.png', '', 500, '2026-10-01T00:00:00Z')
                """,
                (self.user_a["id"],),
            )

        # Reading assets triggers ensure_user_uploads_synced
        s_list, l_res, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_list, 200)
        old_item = next((it for it in l_res["items"] if it["name"] == "Old Scene"), None)
        self.assertIsNotNone(old_item)
        self.assertTrue(len(old_item["uid"]) > 0)
        self.assertEqual(old_item["cat"], "scenes")
        self.assertEqual(old_item["bytes"], 500)

        # Verify DB row has change_seq backfilled
        old_row = self.db.get_conn().execute("SELECT * FROM user_uploads WHERE id = 'UPL-legacy-001'").fetchone()
        self.assertIsNotNone(old_row["change_seq"])
        self.assertEqual(old_row["asset_uid"], old_item["uid"])

    def test_12_put_tombstone_quota_and_expiry_enforcement(self):
        """Test that PUT on tombstones enforces 500-quota, 30-day expiry, and baseRevision."""
        d1, _, _ = _make_data_url(color=(120, 10, 10))
        u_tomb = _uid("tomb")
        # 1. Create and delete an asset to form a tombstone
        s_c, _, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"name": "Tombstone", "dataUrl": d1}, cookie=self.cookie_a)
        self.assertEqual(s_c, 201)
        s_d, _, _ = self._request("DELETE", f"/api/library/assets/{u_tomb}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_d, 200)

        # 2. Expired tombstone (> 30 days) returns 410 on PUT
        with self.db.transaction() as tx:
            expired_time = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
            tx.execute("UPDATE user_uploads SET deleted_at = ? WHERE asset_uid = ?", (expired_time, u_tomb))

        s_exp, err_exp, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"baseRevision": 2, "name": "Revive Expired"}, cookie=self.cookie_a)
        self.assertEqual(s_exp, 410)
        self.assertEqual(err_exp.get("code"), "asset_expired")

        # 3. Active quota limit (500 items): PUT on tombstone returns 413 instead of creating 501 items
        with self.db.transaction() as tx:
            # Set deleted_at to 1 hour ago (unexpired)
            recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            tx.execute("UPDATE user_uploads SET deleted_at = ? WHERE asset_uid = ?", (recent_time, u_tomb))
            # Fill 500 active dummy items
            for i in range(500):
                tx.execute(
                    """
                    INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                    VALUES (?, ?, 'other', ?, '/test.png', '', 100, '2026-10-31T00:00:00Z', ?, 1, ?, '2026-10-31T00:00:00Z')
                    """,
                    (f"UPL-tomb-quota-{i}", self.user_a["id"], f"Dummy {i}", _uid(f"tomb_quota_{i}"), i + 2000),
                )

        # PUT to revive returns 413
        s_q, err_q, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"baseRevision": 2, "name": "Revive Over Quota"}, cookie=self.cookie_a)
        self.assertEqual(s_q, 413)
        self.assertEqual(err_q.get("code"), "asset_count_quota_exceeded")

        # POST restore also returns 413
        s_rst_q, err_rst_q, _ = self._request("POST", f"/api/library/assets/{u_tomb}/restore", cookie=self.cookie_a)
        self.assertEqual(s_rst_q, 413)
        self.assertEqual(err_rst_q.get("code"), "asset_count_quota_exceeded")

        # Clean up the 500 dummy rows
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM user_uploads WHERE id LIKE 'UPL-tomb-quota-%'")

        # 4. Mismatched baseRevision on tombstone PUT returns 409
        s_mismatch, err_mismatch, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"baseRevision": 99, "name": "Mismatch"}, cookie=self.cookie_a)
        self.assertEqual(s_mismatch, 409)
        self.assertEqual(err_mismatch.get("code"), "conflict")

        # 5. Successful revival via PUT with correct baseRevision (2)
        s_rev, res_rev, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"baseRevision": 2, "name": "Revived Successfully"}, cookie=self.cookie_a)
        self.assertEqual(s_rev, 200)
        self.assertIsNone(res_rev["deletedAt"])
        self.assertEqual(res_rev["revision"], 3)
        self.assertEqual(res_rev["name"], "Revived Successfully")

    def test_13_legacy_upload_quotas_and_deduplication(self):
        """Test legacy POST /api/uploads enforces quota limits and active image deduplication."""
        d1, sha1, _ = _make_data_url(color=(130, 10, 10))
        # 1. Fill 500 active items
        with self.db.transaction() as tx:
            for i in range(500):
                tx.execute(
                    """
                    INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                    VALUES (?, ?, 'other', ?, '/test.png', '', 100, '2026-10-31T00:00:00Z', ?, 1, ?, '2026-10-31T00:00:00Z')
                    """,
                    (f"UPL-legacy-quota-{i}", self.user_a["id"], f"Dummy {i}", _uid(f"leg_q_{i}"), i + 3000),
                )

        s_over, err_over, _ = self._request("POST", "/api/uploads", {"dataUrl": d1, "nameZh": "Over"}, cookie=self.cookie_a)
        self.assertEqual(s_over, 413)
        self.assertEqual(err_over.get("code"), "asset_count_quota_exceeded")

        # Remove dummy rows
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM user_uploads WHERE id LIKE 'UPL-legacy-quota-%'")

        # 2. Storage quota enforcement
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                VALUES ('UPL-leg-huge', ?, 'other', 'Huge', '/test.png', '', ?, '2026-10-31T00:00:00Z', ?, 1, 4000, '2026-10-31T00:00:00Z')
                """,
                (self.user_a["id"], MAX_STORAGE_BYTES_PER_USER - 5, _uid("leg_huge")),
            )

        s_st, err_st, _ = self._request("POST", "/api/uploads", {"dataUrl": d1, "nameZh": "Over Storage"}, cookie=self.cookie_a)
        self.assertEqual(s_st, 413)
        self.assertEqual(err_st.get("code"), "asset_storage_quota_exceeded")

        with self.db.transaction() as tx:
            tx.execute("DELETE FROM user_uploads WHERE id = 'UPL-leg-huge'")

        # 3. Deduplication in legacy upload
        s_up1, res_up1, _ = self._request("POST", "/api/uploads", {"dataUrl": d1, "nameZh": "First Up"}, cookie=self.cookie_a)
        self.assertEqual(s_up1, 200)
        self.assertFalse(res_up1.get("deduped", True))
        first_id = res_up1["id"]

        s_up2, res_up2, _ = self._request("POST", "/api/uploads", {"dataUrl": d1, "nameZh": "Second Up Same Image"}, cookie=self.cookie_a)
        self.assertEqual(s_up2, 200)
        self.assertTrue(res_up2.get("deduped"))
        self.assertEqual(res_up2["id"], first_id)

    def test_14_file_unlinking_on_replace_and_tombstone_cleanup(self):
        """Test old files are deleted when unreferenced and kept when referenced by published works."""
        d1, _, _ = _make_data_url(color=(140, 10, 10))
        d2, _, _ = _make_data_url(color=(140, 20, 20))
        d3, _, _ = _make_data_url(color=(140, 30, 30))
        d4, _, _ = _make_data_url(color=(140, 40, 40))
        u_rep = _uid("replace_test")
        u_ref = _uid("ref_test")

        # A. Unreferenced file replaced -> unlinked
        s1, res1, _ = self._request("PUT", f"/api/library/assets/{u_rep}", {"name": "Replace Test", "dataUrl": d1}, cookie=self.cookie_a)
        self.assertEqual(s1, 201)
        row1 = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_rep,)).fetchone()
        fpath1 = Path(row1["file_path"])
        self.assertTrue(fpath1.is_file())

        s2, res2, _ = self._request("PUT", f"/api/library/assets/{u_rep}", {"baseRevision": 1, "dataUrl": d2}, cookie=self.cookie_a)
        self.assertEqual(s2, 200)
        # Old file should now be deleted because it is unreferenced
        self.assertFalse(fpath1.exists())
        row2 = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_rep,)).fetchone()
        fpath2 = Path(row2["file_path"])
        self.assertTrue(fpath2.is_file())

        # B. Referenced file replaced -> kept on disk
        s3, res3, _ = self._request("PUT", f"/api/library/assets/{u_ref}", {"name": "Ref Test", "dataUrl": d3}, cookie=self.cookie_a)
        self.assertEqual(s3, 201)
        row3 = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_ref,)).fetchone()
        fpath3 = Path(row3["file_path"])
        url3 = row3["image_url"]

        # Create published work reference to url3
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, prompt, status, images_json, published_at_ms, created_at, updated_at)
                VALUES ('work_ref_01', 'sync_alice', 'Alice', 'Published Art', 'prompt', 'published', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (json.dumps([url3]),),
            )

        s4, res4, _ = self._request("PUT", f"/api/library/assets/{u_ref}", {"baseRevision": 1, "dataUrl": d4}, cookie=self.cookie_a)
        self.assertEqual(s4, 200)
        # Old file fpath3 must STILL exist because it's referenced in published works!
        self.assertTrue(fpath3.exists())

        # C. 30-day tombstone cleanup
        # Soft delete u_rep (which currently holds fpath2)
        s_del, _, _ = self._request("DELETE", f"/api/library/assets/{u_rep}?baseRevision=2", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)

        # Before 30 days: cleanup does nothing
        cleaned_recent = cleanup_expired_library_tombstones(self.db, max_age_days=30)
        self.assertEqual(cleaned_recent, 0)
        self.assertTrue(fpath2.exists())

        # Mark tombstone as 35 days old
        old_dt = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.transaction() as tx:
            tx.execute("UPDATE user_uploads SET deleted_at = ? WHERE asset_uid = ?", (old_dt, u_rep))

        cleaned_old = cleanup_expired_library_tombstones(self.db, max_age_days=30)
        self.assertEqual(cleaned_old, 1)
        self.assertFalse(fpath2.exists())
        check_row = self.db.get_conn().execute("SELECT 1 FROM user_uploads WHERE asset_uid = ?", (u_rep,)).fetchone()
        self.assertIsNone(check_row)

    def test_15_sha256_active_uniqueness_across_four_paths(self):
        """Test active sha256 uniqueness across create, replace, restore, and tombstone revival."""
        dX, shaX, _ = _make_data_url(color=(150, 10, 10))
        dY, shaY, _ = _make_data_url(color=(150, 20, 20))
        u_sha1, u_sha2, u_sha3 = _uid("sha_1"), _uid("sha_2"), _uid("sha_3")

        # Asset 1 with shaX
        s1, res1, _ = self._request("PUT", f"/api/library/assets/{u_sha1}", {"name": "Asset 1", "dataUrl": dX}, cookie=self.cookie_a)
        self.assertEqual(s1, 201)

        # Asset 2 with shaY
        s2, res2, _ = self._request("PUT", f"/api/library/assets/{u_sha2}", {"name": "Asset 2", "dataUrl": dY}, cookie=self.cookie_a)
        self.assertEqual(s2, 201)

        # Path 1: Create with duplicate shaX -> returns 200 deduped with existingUid
        s_dup, res_dup, _ = self._request("PUT", f"/api/library/assets/{u_sha3}", {"name": "Asset 3", "dataUrl": dX}, cookie=self.cookie_a)
        self.assertEqual(s_dup, 200)
        self.assertTrue(res_dup.get("deduped"))
        self.assertEqual(res_dup.get("requestedUid"), u_sha3)
        self.assertEqual(res_dup.get("uid"), u_sha1)

        # Path 2: Replace image on Asset 2 with shaX -> returns 409 duplicate_image
        s_rep, err_rep, _ = self._request("PUT", f"/api/library/assets/{u_sha2}", {"baseRevision": 1, "dataUrl": dX}, cookie=self.cookie_a)
        self.assertEqual(s_rep, 409)
        self.assertEqual(err_rep.get("code"), "duplicate_image")
        self.assertEqual(err_rep.get("existingUid"), u_sha1)

        # Path 3: Restore collision
        # Soft delete Asset 1
        s_del1, _, _ = self._request("DELETE", f"/api/library/assets/{u_sha1}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del1, 200)

        # Now Asset 2 can replace image to shaX because Asset 1 is deleted
        s_rep2, _, _ = self._request("PUT", f"/api/library/assets/{u_sha2}", {"baseRevision": 1, "dataUrl": dX}, cookie=self.cookie_a)
        self.assertEqual(s_rep2, 200)

        # Restoring Asset 1 collides with now-active Asset 2
        s_rst, err_rst, _ = self._request("POST", f"/api/library/assets/{u_sha1}/restore", cookie=self.cookie_a)
        self.assertEqual(s_rst, 409)
        self.assertEqual(err_rst.get("code"), "duplicate_image")
        self.assertEqual(err_rst.get("existingUid"), u_sha2)

        # Path 4: Tombstone revival via PUT collides with active Asset 2
        s_rev_col, err_rev_col, _ = self._request("PUT", f"/api/library/assets/{u_sha1}", {"baseRevision": 2, "name": "Reviving Collide"}, cookie=self.cookie_a)
        self.assertEqual(s_rev_col, 409)
        self.assertEqual(err_rev_col.get("code"), "duplicate_image")
        self.assertEqual(err_rev_col.get("existingUid"), u_sha2)

    def test_16_delete_base_revision_validation(self):
        """Test DELETE strictly requires valid integer baseRevision."""
        d, _, _ = _make_data_url(color=(160, 10, 10))
        u_del = _uid("del_check")
        s_c, _, _ = self._request("PUT", f"/api/library/assets/{u_del}", {"name": "Delete Check", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_c, 201)

        # Missing baseRevision
        s1, e1, _ = self._request("DELETE", f"/api/library/assets/{u_del}", cookie=self.cookie_a)
        self.assertEqual(s1, 400)
        self.assertEqual(e1.get("code"), "base_revision_required")

        # Blank baseRevision
        s2, e2, _ = self._request("DELETE", f"/api/library/assets/{u_del}?baseRevision=", cookie=self.cookie_a)
        self.assertEqual(s2, 400)
        self.assertEqual(e2.get("code"), "base_revision_required")

        # Non-integer baseRevision
        s3, e3, _ = self._request("DELETE", f"/api/library/assets/{u_del}?baseRevision=invalid_abc", cookie=self.cookie_a)
        self.assertEqual(s3, 400)
        self.assertEqual(e3.get("code"), "base_revision_required")

        # Mismatched integer baseRevision
        s4, e4, _ = self._request("DELETE", f"/api/library/assets/{u_del}?baseRevision=999", cookie=self.cookie_a)
        self.assertEqual(s4, 409)
        self.assertEqual(e4.get("code"), "conflict")

        # Correct baseRevision
        s5, res5, _ = self._request("DELETE", f"/api/library/assets/{u_del}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s5, 200)
        self.assertIsNotNone(res5["tombstone"]["deletedAt"])

    def test_17_import_category_omitted_from_sync_and_quota(self):
        """Test cat='import' items are excluded from sync responses and quota calculations."""
        u_tmp = _uid("temp_import_1")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                VALUES ('UPL-temp-import-1', ?, 'import', 'Temporary Import Image', '/uploads/temp.png', '', 5000, '2026-10-31T00:00:00Z', ?, 1, 9999, '2026-10-31T00:00:00Z')
                """,
                (self.user_a["id"], u_tmp),
            )

        # GET /api/library/assets must NOT return cat='import'
        s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get, 200)
        self.assertNotIn(u_tmp, [it["uid"] for it in res_get["items"]])

        # GET with since must NOT return cat='import'
        s_since, res_since, _ = self._request("GET", "/api/library/assets?since=0", cookie=self.cookie_a)
        self.assertEqual(s_since, 200)
        self.assertNotIn(u_tmp, [it["uid"] for it in res_since["items"]])

    def test_18_image_pixel_bomb_protection(self):
        """Test images exceeding 40M pixels or triggering DecompressionBombWarning are rejected with 413."""
        # Create an image with 42,000,000 pixels (7000 x 6000)
        im = Image.new("L", (7000, 6000), 128)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        raw = buf.getvalue()
        b64 = base64.b64encode(raw).decode("ascii")
        bomb_data_url = f"data:image/png;base64,{b64}"
        u_bomb = _uid("bomb_test")

        s_bomb, err_bomb, _ = self._request("PUT", f"/api/library/assets/{u_bomb}", {"name": "Pixel Bomb", "dataUrl": bomb_data_url}, cookie=self.cookie_a)
        self.assertEqual(s_bomb, 413)
        self.assertEqual(err_bomb.get("code"), "image_too_large")

    def test_19_field_clearing_behavior(self):
        """Test explicit empty string or empty list clears nameEn and tags while omission preserves them."""
        d, _, _ = _make_data_url(color=(190, 10, 10))
        u_field = _uid("field_test")
        s_c, _, _ = self._request(
            "PUT",
            f"/api/library/assets/{u_field}",
            {"name": "Initial Name", "nameEn": "English Title", "tags": ["tag1", "tag2"], "dataUrl": d},
            cookie=self.cookie_a,
        )
        self.assertEqual(s_c, 201)

        # Clear nameEn with "" and clear tags with []
        s_clear, res_clear, _ = self._request(
            "PUT",
            f"/api/library/assets/{u_field}",
            {"baseRevision": 1, "nameEn": "", "tags": []},
            cookie=self.cookie_a,
        )
        self.assertEqual(s_clear, 200)
        self.assertEqual(res_clear["nameEn"], "")
        self.assertEqual(res_clear["tags"], [])

        # Omit nameEn and tags: should stay cleared (not resurrected or broken)
        s_omit, res_omit, _ = self._request(
            "PUT",
            f"/api/library/assets/{u_field}",
            {"baseRevision": 2, "name": "Updated Name Only"},
            cookie=self.cookie_a,
        )
        self.assertEqual(s_omit, 200)
        self.assertEqual(res_omit["name"], "Updated Name Only")
        self.assertEqual(res_omit["nameEn"], "")
        self.assertEqual(res_omit["tags"], [])

        # Set new nameEn and tags
        s_set, res_set, _ = self._request(
            "PUT",
            f"/api/library/assets/{u_field}",
            {"baseRevision": 3, "nameEn": "Brand New English", "tags": ["art", "props"]},
            cookie=self.cookie_a,
        )
        self.assertEqual(s_set, 200)
        self.assertEqual(res_set["nameEn"], "Brand New English")
        self.assertEqual(res_set["tags"], ["art", "props"])

        # Omit nameEn but change tags: nameEn should PRESERVE "Brand New English"
        s_pres, res_pres, _ = self._request(
            "PUT",
            f"/api/library/assets/{u_field}",
            {"baseRevision": 4, "tags": ["props"]},
            cookie=self.cookie_a,
        )
        self.assertEqual(s_pres, 200)
        self.assertEqual(res_pres["nameEn"], "Brand New English")
        self.assertEqual(res_pres["tags"], ["props"])

    def test_20_interface_conventions_and_rate_limit_hard_cap(self):
        """Test imageUrl vs publicUrl, foreign UID 404, and 10000 key rate limit hard cap."""
        d, _, _ = _make_data_url(color=(200, 10, 10))
        u_conv = _uid("conv")
        s_c, res_c, _ = self._request("PUT", f"/api/library/assets/{u_conv}", {"name": "Conventions", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_c, 201)
        # imageUrl points to authenticated endpoint, publicUrl points to /uploads/...
        self.assertEqual(res_c["imageUrl"], f"/api/library/assets/{u_conv}/image")
        self.assertTrue(res_c["publicUrl"].startswith("/uploads/"))

        # Bob attempts PUT on Alice's UID -> returns 404 (does NOT create in Bob's namespace)
        d_bob, _, _ = _make_data_url(color=(200, 20, 20))
        s_foreign, err_foreign, _ = self._request("PUT", f"/api/library/assets/{u_conv}", {"name": "Bob Hijack", "dataUrl": d_bob}, cookie=self.cookie_b)
        self.assertEqual(s_foreign, 404)

        # Rate limit hard cap (10000 keys)
        _token_rate_logs.clear()
        now = time.time()
        for i in range(MAX_RATE_LIMIT_KEYS):
            _token_rate_logs[f"token_{i}"] = [now]

        # 10001st key fails check_token_rate_limit
        self.assertFalse(check_token_rate_limit("token_overflow_10001"))

        # When caller uses a token that exceeds map capacity, server returns 429
        tok_overflow = self._create_token(self.user_a["id"], ["library"], "OverflowToken")
        s_429, err_429, _ = self._request("GET", "/api/library/assets", bearer=tok_overflow)
        self.assertEqual(s_429, 429)
        self.assertIn(err_429.get("code"), ("rate_limited", "rate_limit_capacity_exceeded"))

        _token_rate_logs.clear()

    def test_21_historical_duplicate_uploads_backfill_safe(self):
        """Test that historical duplicate uploads with identical sha256 don't crash backfill with 500."""
        # 1. Create a real image file on disk
        img_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        fpath = self.uploads_dir / "UPL-hist-dup.png"
        fpath.write_bytes(img_bytes)
        img_sha = hashlib.sha256(img_bytes).hexdigest()

        # Insert two legacy rows for user_a pointing to same file, NULL sha256, NULL asset_uid, NULL change_seq
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, sha256, asset_uid, change_seq, revision, created_at, updated_at)
                VALUES ('UPL-hist-1', ?, 'props', 'Hist 1', '/uploads/UPL-hist-dup.png', ?, ?, NULL, NULL, NULL, 1, '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')
                """,
                (self.user_a["id"], str(fpath), len(img_bytes)),
            )
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, sha256, asset_uid, change_seq, revision, created_at, updated_at)
                VALUES ('UPL-hist-2', ?, 'props', 'Hist 2', '/uploads/UPL-hist-dup.png', ?, ?, NULL, NULL, NULL, 1, '2026-09-02T00:00:00Z', '2026-09-02T00:00:00Z')
                """,
                (self.user_a["id"], str(fpath), len(img_bytes)),
            )

        # GET /api/library/assets triggers backfill: must succeed with 200 (NOT 500 UNIQUE constraint failed)
        s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get, 200)

        # Verify DB rows: one has sha256 = img_sha, other has sha256 IS NULL
        rows = self.db.get_conn().execute(
            "SELECT id, sha256, asset_uid, change_seq FROM user_uploads WHERE id IN ('UPL-hist-1', 'UPL-hist-2') ORDER BY id ASC"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        shas = [r["sha256"] for r in rows]
        self.assertIn(img_sha, shas)
        self.assertIn(None, shas)
        # Both must have valid asset_uid and change_seq
        self.assertTrue(all(r["asset_uid"] and r["change_seq"] for r in rows))

        # PUT works without 500
        u_new = _uid("hist_new")
        d, _, _ = _make_data_url(color=(21, 21, 21))
        s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{u_new}", {"name": "Fresh Item", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_put, 201)

        # Legacy upload with same content as hist dup returns existing asset (deduped: True)
        d_dup = f"data:image/png;base64,{base64.b64encode(img_bytes).decode('ascii')}"
        s_leg, res_leg, _ = self._request("POST", "/api/uploads", {"dataUrl": d_dup, "nameZh": "Upload Hist Dup"}, cookie=self.cookie_a)
        self.assertEqual(s_leg, 200)
        self.assertTrue(res_leg.get("deduped"))

    def test_22_media_reference_protection_expanded(self):
        """Test media reference check covers summary, locked_body, replies text, recipes references, and fails safe."""
        d_sum_base = _make_data_url(color=(22, 1, 1))[0]
        d_sum_repl = _make_data_url(color=(22, 1, 2))[0]
        d_body_base = _make_data_url(color=(22, 2, 1))[0]
        d_body_repl = _make_data_url(color=(22, 2, 2))[0]
        d_rep_base = _make_data_url(color=(22, 3, 1))[0]
        d_rep_repl = _make_data_url(color=(22, 3, 2))[0]
        d_rec_base = _make_data_url(color=(22, 4, 1))[0]
        d_rec_repl = _make_data_url(color=(22, 4, 2))[0]

        # 1. forum_topics.summary reference
        u_sum = _uid("ref_summary")
        s1, _, _ = self._request("PUT", f"/api/library/assets/{u_sum}", {"name": "Sum Ref", "dataUrl": d_sum_base}, cookie=self.cookie_a)
        self.assertEqual(s1, 201)
        r_sum = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_sum,)).fetchone()
        f_sum, url_sum = Path(r_sum["file_path"]), r_sum["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, published_at_ms, created_at, updated_at)
                VALUES ('top_sum_01', 'chat', 'Chat', 'Topic 1', 'alice', 'Alice', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (f"Image is here: {url_sum}",),
            )

        # Replacing image must NOT delete f_sum because forum_topics.summary references it
        s_rep_sum, _, _ = self._request("PUT", f"/api/library/assets/{u_sum}", {"baseRevision": 1, "dataUrl": d_sum_repl}, cookie=self.cookie_a)
        self.assertEqual(s_rep_sum, 200)
        self.assertTrue(f_sum.exists())

        # 2. forum_topics.locked_body reference
        u_body = _uid("ref_locked_body")
        s2, _, _ = self._request("PUT", f"/api/library/assets/{u_body}", {"name": "Body Ref", "dataUrl": d_body_base}, cookie=self.cookie_a)
        self.assertEqual(s2, 201)
        r_body = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_body,)).fetchone()
        f_body, url_body = Path(r_body["file_path"]), r_body["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, locked_body, published_at_ms, created_at, updated_at)
                VALUES ('top_body_01', 'chat', 'Chat', 'Topic 2', 'alice', 'Alice', '', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (f'<p><img src="{url_body}"></p>',),
            )

        s_rep_body, _, _ = self._request("PUT", f"/api/library/assets/{u_body}", {"baseRevision": 1, "dataUrl": d_body_repl}, cookie=self.cookie_a)
        self.assertEqual(s_rep_body, 200)
        self.assertTrue(f_body.exists())

        # 3. forum_replies.text reference
        u_rep = _uid("ref_reply_text")
        s3, _, _ = self._request("PUT", f"/api/library/assets/{u_rep}", {"name": "Reply Ref", "dataUrl": d_rep_base}, cookie=self.cookie_a)
        self.assertEqual(s3, 201)
        r_rep = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_rep,)).fetchone()
        f_rep, url_rep = Path(r_rep["file_path"]), r_rep["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, created_at)
                VALUES ('rep_01', 'top_sum_01', 'alice', 'Alice', ?, '2026-10-31T00:00:00Z')
                """,
                (f'See my screenshot <img src="{url_rep}">',),
            )

        s_rep_rep, _, _ = self._request("PUT", f"/api/library/assets/{u_rep}", {"baseRevision": 1, "dataUrl": d_rep_repl}, cookie=self.cookie_a)
        self.assertEqual(s_rep_rep, 200)
        self.assertTrue(f_rep.exists())

        # 4. studio_recipes.references_json reference
        u_rec = _uid("ref_recipe_json")
        s4, _, _ = self._request("PUT", f"/api/library/assets/{u_rec}", {"name": "Recipe Ref", "dataUrl": d_rec_base}, cookie=self.cookie_a)
        self.assertEqual(s4, 201)
        r_rec = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_rec,)).fetchone()
        f_rec, url_rec = Path(r_rec["file_path"]), r_rec["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_recipes (id, user_id, kind, references_json, created_at, updated_at)
                VALUES ('rec_01', ?, 'sketch', ?, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (self.user_a["id"], json.dumps([{"url": url_rec}])),
            )

        s_rep_rec, _, _ = self._request("PUT", f"/api/library/assets/{u_rec}", {"baseRevision": 1, "dataUrl": d_rec_repl}, cookie=self.cookie_a)
        self.assertEqual(s_rep_rec, 200)
        self.assertTrue(f_rec.exists())

        # 5. Tombstone cleanup with references: DB row removed, referenced file KEPT
        s_del_rec, _, _ = self._request("DELETE", f"/api/library/assets/{u_rec}?baseRevision=2", cookie=self.cookie_a)
        self.assertEqual(s_del_rec, 200)
        # Mark tombstone as 35 days old
        old_dt = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.transaction() as tx:
            tx.execute("UPDATE user_uploads SET deleted_at = ? WHERE asset_uid = ?", (old_dt, u_rec))

        # Cleanup deletes expired row from DB
        cleaned = cleanup_expired_library_tombstones(self.db, max_age_days=30)
        self.assertGreaterEqual(cleaned, 1)
        # But f_rec must STILL exist because recipe references it!
        self.assertTrue(f_rec.exists())

        # 6. Test fail-safe on query error: is_media_referenced returns True if query fails
        class BrokenConn:
            def execute(self, sql, params=None):
                raise sqlite3.OperationalError("Simulated DB error")

        self.assertTrue(is_media_referenced(BrokenConn(), "/uploads/any.png", "C:/tmp/any.png"))

    def test_23_upload_category_whitelist(self):
        """Test cat in uploads supports public categories, preserves internal 'forum', and downgrades 'import'/unknown to 'other'."""
        d_forum, _, _ = _make_data_url(color=(23, 23, 20))
        # 1. 'forum' internal category is preserved as 'forum', but excluded from library assets
        s_forum, res_forum, _ = self._request("POST", "/api/uploads", {"dataUrl": d_forum, "cat": "forum", "nameZh": "Forum Post Image"}, cookie=self.cookie_a)
        self.assertEqual(s_forum, 200)
        self.assertEqual(res_forum.get("cat"), "forum")
        row_forum = self.db.get_conn().execute("SELECT cat, asset_uid FROM user_uploads WHERE id = ?", (res_forum["id"],)).fetchone()
        self.assertEqual(row_forum["cat"], "forum")

        # Must NOT appear in GET /api/library/assets
        s_lib, res_lib, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_lib, 200)
        self.assertNotIn(res_forum["id"], [it["id"] for it in res_lib["items"]])
        if row_forum["asset_uid"]:
            self.assertNotIn(row_forum["asset_uid"], [it["uid"] for it in res_lib["items"]])

        # 2. 'import' category is disallowed from public upload and mapped to 'other'
        d, _, _ = _make_data_url(color=(23, 23, 23))
        s1, res1, _ = self._request("POST", "/api/uploads", {"dataUrl": d, "cat": "import", "nameZh": "Import Try"}, cookie=self.cookie_a)
        self.assertEqual(s1, 200)
        self.assertEqual(res1.get("cat"), "other")
        row1 = self.db.get_conn().execute("SELECT cat FROM user_uploads WHERE id = ?", (res1["id"],)).fetchone()
        self.assertEqual(row1["cat"], "other")

        # 3. Unknown / arbitrary category mapped to 'other'
        d2, _, _ = _make_data_url(color=(23, 23, 24))
        s2, res2, _ = self._request("POST", "/api/uploads", {"dataUrl": d2, "cat": "super_secret", "nameZh": "Arbitrary Cat"}, cookie=self.cookie_a)
        self.assertEqual(s2, 200)
        self.assertEqual(res2.get("cat"), "other")

        # 4. Valid category preserved
        d3, _, _ = _make_data_url(color=(23, 23, 25))
        s3, res3, _ = self._request("POST", "/api/uploads", {"dataUrl": d3, "cat": "scenes", "nameZh": "Scene Valid"}, cookie=self.cookie_a)
        self.assertEqual(s3, 200)
        self.assertEqual(res3.get("cat"), "scenes")

    def test_24_invalid_uid_format_rejected(self):
        """Test PUT strictly requires valid UUID format for uid."""
        d, _, _ = _make_data_url(color=(24, 24, 24))

        # Short IDs, arbitrary strings, or non-UUIDs are rejected with 400
        for bad_uid in ("CH-002", "short-id", "12345", "not-a-uuid", "g" * 36):
            s, err, _ = self._request("PUT", f"/api/library/assets/{bad_uid}", {"name": "Bad UID", "dataUrl": d}, cookie=self.cookie_a)
            self.assertEqual(s, 400, f"Expected 400 for {bad_uid}, got {s}")
            self.assertEqual(err.get("code"), "invalid_uid")

        # Valid UUID is accepted
        valid_uid = str(uuid.uuid4())
        s_ok, res_ok, _ = self._request("PUT", f"/api/library/assets/{valid_uid}", {"name": "Good UUID", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_ok, 201)
        self.assertEqual(res_ok["uid"], valid_uid)

    def test_25_expired_tombstone_put_order_of_checks(self):
        """Test expired tombstone returns 410 asset_expired before baseRevision check."""
        d, _, _ = _make_data_url(color=(25, 25, 25))
        u_tomb = _uid("expire_order")
        s_c, _, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"name": "Expiring Order", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_c, 201)
        s_del, _, _ = self._request("DELETE", f"/api/library/assets/{u_tomb}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)

        # Mark tombstone as 31 days old
        old_dt = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.transaction() as tx:
            tx.execute("UPDATE user_uploads SET deleted_at = ? WHERE asset_uid = ?", (old_dt, u_tomb))

        # PUT without baseRevision returns 410 (NOT 400 missing_base_revision)
        s1, err1, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"name": "No Rev"}, cookie=self.cookie_a)
        self.assertEqual(s1, 410)
        self.assertEqual(err1.get("code"), "asset_expired")

        # PUT with wrong baseRevision returns 410 (NOT 409 conflict)
        s2, err2, _ = self._request("PUT", f"/api/library/assets/{u_tomb}", {"baseRevision": 999, "name": "Wrong Rev"}, cookie=self.cookie_a)
        self.assertEqual(s2, 410)
        self.assertEqual(err2.get("code"), "asset_expired")


if __name__ == "__main__":
    unittest.main()
