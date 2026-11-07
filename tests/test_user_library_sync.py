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
import contextlib
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
        """Fresh V3 never mutates malformed pre-launch legacy rows on GET."""
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

        # V3 is fresh-only: the GET path never performs hidden legacy backfills.
        s_list, l_res, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_list, 200)
        self.assertFalse(any(it["name"] == "Old Scene" for it in l_res["items"]))
        old_row = self.db.get_conn().execute(
            "SELECT asset_uid,change_seq FROM user_uploads WHERE id='UPL-legacy-001'"
        ).fetchone()
        self.assertIsNone(old_row["asset_uid"])
        self.assertIsNone(old_row["change_seq"])
        # A proper V3 write must receive complete metadata immediately.
        d, sha, _ = _make_data_url(color=(40, 50, 60))
        uid = _uid("fresh_v3_asset")
        status, _, _ = self._request(
            "PUT", f"/api/library/assets/{uid}",
            {"name": "New Scene", "dataUrl": d}, cookie=self.cookie_a,
        )
        self.assertEqual(status, 201)
        row = self.db.get_conn().execute(
            "SELECT asset_uid,change_seq,sha256 FROM user_uploads WHERE asset_uid=?",
            (uid,),
        ).fetchone()
        self.assertEqual(row["sha256"], sha)
        self.assertGreater(row["change_seq"], 0)

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
        # Old media remains until the durable GC queue is drained.
        self.assertTrue(fpath1.exists())
        from backend.media_gc import drain_media_gc
        with self.db.transaction() as tx:
            tx.execute("UPDATE media_gc_jobs SET next_attempt_at=0, claim_until=0")
        self.assertGreaterEqual(drain_media_gc(self.db)["deleted"], 1)
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
        self.assertTrue(fpath2.exists())
        with self.db.transaction() as tx:
            tx.execute("UPDATE media_gc_jobs SET next_attempt_at=0, claim_until=0")
        drain_media_gc(self.db)
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
        """Fresh V3 skips unsynced rows, and deduplicates valid new uploads."""
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

        # GET must not run a legacy backfill or leak malformed records.
        s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get, 200)
        self.assertFalse(any("Hist " in it["name"] for it in res_get["items"]))
        rows = self.db.get_conn().execute(
            "SELECT id,sha256,asset_uid,change_seq FROM user_uploads "
            "WHERE id IN ('UPL-hist-1','UPL-hist-2') ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["sha256"] is None and r["asset_uid"] is None for r in rows))

        # PUT works without 500
        u_new = _uid("hist_new")
        d, _, _ = _make_data_url(color=(21, 21, 21))
        s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{u_new}", {"name": "Fresh Item", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_put, 201)

        # An old malformed row cannot impersonate a newly uploaded V3 asset.
        d_dup = f"data:image/png;base64,{base64.b64encode(img_bytes).decode('ascii')}"
        s_leg, res_leg, _ = self._request("POST", "/api/uploads", {"dataUrl": d_dup, "nameZh": "Upload Hist Dup"}, cookie=self.cookie_a)
        self.assertEqual(s_leg, 200)
        self.assertFalse(res_leg.get("deduped"))
        s_again, res_again, _ = self._request("POST", "/api/uploads", {"dataUrl": d_dup, "nameZh": "Upload Again"}, cookie=self.cookie_a)
        self.assertEqual(s_again, 200)
        self.assertTrue(res_again.get("deduped"))
        self.assertEqual(res_again["id"], res_leg["id"])

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

    def test_26_forum_cat_does_not_block_quota_or_conflict_unique_sha(self):
        """Test B1: 500 forum rows do not block library quota and same sha does not collide with unique index."""
        # Pre-populate 500 forum rows
        with self.db.transaction() as tx:
            for i in range(500):
                tx.execute(
                    """
                    INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, asset_uid, revision, change_seq, updated_at)
                    VALUES (?, ?, 'forum', ?, '/test.png', '', 100, '2026-10-31T00:00:00Z', ?, 1, ?, '2026-10-31T00:00:00Z')
                    """,
                    (f"UPL-forum-{i}", self.user_a["id"], f"Forum {i}", _uid(f"forum_{i}"), i + 5000),
                )

        d_other, sha_other, _ = _make_data_url(color=(26, 1, 1))
        # 1. POST /api/uploads with cat="other" succeeds (not 413)
        s_up, res_up, _ = self._request("POST", "/api/uploads", {"dataUrl": d_other, "cat": "other", "nameZh": "Post In Library"}, cookie=self.cookie_a)
        self.assertEqual(s_up, 200)

        # 2. PUT /api/library/assets/{new_uid} succeeds (201, not 413)
        u_new = _uid("forum_quota_free")
        d_put, sha_put, _ = _make_data_url(color=(26, 1, 2))
        s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{u_new}", {"name": "Put After 500 Forum", "dataUrl": d_put}, cookie=self.cookie_a)
        self.assertEqual(s_put, 201)

        # 3. GET /api/library/assets only returns the library items, none of the 500 forum items
        s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get, 200)
        items = res_get["items"]
        self.assertTrue(all(it.get("cat") != "forum" for it in items))
        self.assertLessEqual(len(items), 10)

        # 4. Same sha between forum row and library asset row does not violate unique index
        d_same, sha_same, _ = _make_data_url(color=(26, 1, 3))
        # Forum upload with sha_same
        s_f, res_f, _ = self._request("POST", "/api/uploads", {"dataUrl": d_same, "cat": "forum", "nameZh": "Forum Same Sha"}, cookie=self.cookie_a)
        self.assertEqual(s_f, 200)
        # Library PUT with sha_same succeeds without UNIQUE constraint failed
        u_same = _uid("library_same_sha")
        s_lib, res_lib, _ = self._request("PUT", f"/api/library/assets/{u_same}", {"name": "Library Same Sha", "dataUrl": d_same}, cookie=self.cookie_a)
        self.assertEqual(s_lib, 201)

        # Clean up the 500 forum rows
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM user_uploads WHERE id LIKE 'UPL-forum-%'")

    def test_27_forum_rows_never_participate_in_library_dedup(self):
        """Test B2: Forum upload with identical content does not hijack library asset creation."""
        d_shared, sha_shared, _ = _make_data_url(color=(27, 27, 27))
        # 1. Create a forum upload
        s_f, res_f, _ = self._request("POST", "/api/uploads", {"dataUrl": d_shared, "cat": "forum", "nameZh": "Forum Post Image"}, cookie=self.cookie_a)
        self.assertEqual(s_f, 200)
        forum_id = res_f["id"]

        # 2. Skill/Client PUTs a library asset with the same byte content
        u_lib = _uid("library_shared_content")
        s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{u_lib}", {"name": "Library Asset", "dataUrl": d_shared}, cookie=self.cookie_a)
        self.assertEqual(s_put, 201)
        self.assertFalse(res_put.get("deduped", True))
        self.assertEqual(res_put["uid"], u_lib)

        # 3. Visible in GET /api/library/assets
        s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get, 200)
        uids = [it["uid"] for it in res_get["items"]]
        self.assertIn(u_lib, uids)

        # 4. Image endpoint works for u_lib
        s_img, _, b_img = self._request("GET", f"/api/library/assets/{u_lib}/image", cookie=self.cookie_a)
        self.assertEqual(s_img, 200)
        self.assertGreater(len(b_img), 0)

        # 5. DELETE works for u_lib
        s_del, res_del, _ = self._request("DELETE", f"/api/library/assets/{u_lib}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)

    def test_28_http_response_after_commit_and_rollback_safety(self):
        """Test B3: HTTP response is sent strictly after transaction COMMIT, and commit failure returns 5xx."""
        d, _, _ = _make_data_url(color=(28, 28, 28))
        u_delayed = _uid("commit_delayed")

        # Hook Database.transaction to inject a 0.15s commit delay
        orig_transaction = self.db.transaction

        @contextlib.contextmanager
        def delayed_transaction():
            with orig_transaction() as tx:
                yield tx
                time.sleep(0.15)

        self.db.transaction = delayed_transaction
        try:
            s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{u_delayed}", {"name": "Delayed Commit", "dataUrl": d}, cookie=self.cookie_a)
            self.assertEqual(s_put, 201)
            # Row MUST exist in database immediately upon response return
            row = self.db.get_conn().execute("SELECT * FROM user_uploads WHERE asset_uid = ?", (u_delayed,)).fetchone()
            self.assertIsNotNone(row)
        finally:
            self.db.transaction = orig_transaction

        # Now test commit failure: simulated exception on commit
        @contextlib.contextmanager
        def failing_transaction():
            with orig_transaction() as tx:
                yield tx
                raise sqlite3.OperationalError("Simulated COMMIT failure")

        u_fail = _uid("commit_fail")
        self.db.transaction = failing_transaction
        try:
            s_fail, res_fail, _ = self._request("PUT", f"/api/library/assets/{u_fail}", {"name": "Should Fail", "dataUrl": d}, cookie=self.cookie_a)
            # Must be 500, NEVER 201
            self.assertEqual(s_fail, 500)
            self.assertFalse(res_fail.get("ok", False))
            # Row must NOT exist in database
            check_row = self.db.get_conn().execute("SELECT * FROM user_uploads WHERE asset_uid = ?", (u_fail,)).fetchone()
            self.assertIsNone(check_row)
        finally:
            self.db.transaction = orig_transaction

    def test_29_media_reference_protection_without_status_filter(self):
        """Test B4: Reference check protects files across non-published statuses (draft, hidden, paused, revoked)."""
        d_orig, _, _ = _make_data_url(color=(29, 1, 1))
        d_new, _, _ = _make_data_url(color=(29, 2, 2))

        # 1. Draft work referencing image
        u_draft = _uid("ref_draft_work")
        s1, _, _ = self._request("PUT", f"/api/library/assets/{u_draft}", {"name": "Draft Work Ref", "dataUrl": d_orig}, cookie=self.cookie_a)
        self.assertEqual(s1, 201)
        r1 = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_draft,)).fetchone()
        f1, url1 = Path(r1["file_path"]), r1["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO works (id, author_username, author_name, title, prompt, status, images_json, published_at_ms, created_at, updated_at)
                VALUES ('work_draft_01', 'sync_alice', 'Alice', 'Draft Art', 'prompt', 'draft', ?, 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (json.dumps([url1]),),
            )

        # Replacing image: old file f1 must STILL exist because draft work references it
        s_rep1, _, _ = self._request("PUT", f"/api/library/assets/{u_draft}", {"baseRevision": 1, "dataUrl": d_new}, cookie=self.cookie_a)
        self.assertEqual(s_rep1, 200)
        self.assertTrue(f1.exists())

        # 2. Paused / Hidden topic referencing image
        u_paused = _uid("ref_paused_topic")
        d_p_orig = _make_data_url(color=(29, 3, 1))[0]
        d_p_new = _make_data_url(color=(29, 3, 2))[0]
        s2, _, _ = self._request("PUT", f"/api/library/assets/{u_paused}", {"name": "Paused Topic Ref", "dataUrl": d_p_orig}, cookie=self.cookie_a)
        self.assertEqual(s2, 201)
        r2 = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_paused,)).fetchone()
        f2, url2 = Path(r2["file_path"]), r2["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name, summary, status, published_at_ms, created_at, updated_at)
                VALUES ('top_paused_01', 'chat', 'Chat', 'Paused Topic', 'alice', 'Alice', ?, 'paused', 1700000000000, '2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')
                """,
                (f"Image is here: {url2}",),
            )

        s_rep2, _, _ = self._request("PUT", f"/api/library/assets/{u_paused}", {"baseRevision": 1, "dataUrl": d_p_new}, cookie=self.cookie_a)
        self.assertEqual(s_rep2, 200)
        self.assertTrue(f2.exists())

        # 3. Revoked grant referencing image
        u_rev = _uid("ref_revoked_grant")
        d_g_orig = _make_data_url(color=(29, 4, 1))[0]
        d_g_new = _make_data_url(color=(29, 4, 2))[0]
        s3, _, _ = self._request("PUT", f"/api/library/assets/{u_rev}", {"name": "Grant Ref", "dataUrl": d_g_orig}, cookie=self.cookie_a)
        self.assertEqual(s3, 201)
        r3 = self.db.get_conn().execute("SELECT file_path, image_url FROM user_uploads WHERE asset_uid = ?", (u_rev,)).fetchone()
        f3, url3 = Path(r3["file_path"]), r3["image_url"]

        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT OR IGNORE INTO studio_generations (id, user_id, created_at)
                VALUES ('gen_01', ?, '2026-01-01T00:00:00Z')
                """,
                (self.user_a["id"],),
            )
            tx.execute(
                """
                INSERT INTO media_public_grants (id, media_url, owner_user_id, generation_id, target_type, target_id, granted_by_user_id, granted_at, revoked_at)
                VALUES ('grant_rev_01', ?, ?, 'gen_01', 'topic', 'top_01', ?, '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
                """,
                (url3, self.user_a["id"], self.user_a["id"]),
            )

        s_rep3, _, _ = self._request("PUT", f"/api/library/assets/{u_rev}", {"baseRevision": 1, "dataUrl": d_g_new}, cookie=self.cookie_a)
        self.assertEqual(s_rep3, 200)
        self.assertTrue(f3.exists())

    def test_30_uuid_normalization_and_deduplication(self):
        """Test M1: UUIDs are normalized to canonical lowercase hyphenated form across case, braces, and URNs."""
        base_raw_uuid = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        d, _, _ = _make_data_url(color=(30, 30, 30))

        # 1. PUT with uppercase UUID
        upper_uuid = base_raw_uuid.upper()
        s_put1, res_put1, _ = self._request("PUT", f"/api/library/assets/{upper_uuid}", {"name": "Upper Case", "dataUrl": d}, cookie=self.cookie_a)
        self.assertEqual(s_put1, 201)
        self.assertEqual(res_put1["uid"], base_raw_uuid.lower())

        # Verify DB row is stored as lowercase
        row = self.db.get_conn().execute("SELECT asset_uid FROM user_uploads WHERE lower(asset_uid) = ?", (base_raw_uuid.lower(),)).fetchall()
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["asset_uid"], base_raw_uuid.lower())

        # 2. PUT with curly braces {UUID} updates the SAME asset (baseRevision=1) instead of creating a second row
        braced_uuid = f"{{{base_raw_uuid}}}"
        s_put2, res_put2, _ = self._request("PUT", f"/api/library/assets/{braced_uuid}", {"baseRevision": 1, "name": "Braced Case"}, cookie=self.cookie_a)
        self.assertEqual(s_put2, 200)
        self.assertEqual(res_put2["revision"], 2)

        # Still exactly 1 row in DB
        rows = self.db.get_conn().execute("SELECT asset_uid FROM user_uploads WHERE lower(asset_uid) = ?", (base_raw_uuid.lower(),)).fetchall()
        self.assertEqual(len(rows), 1)

    def test_31_get_library_assets_concurrent_read_lockfree(self):
        """Test M2: GET /api/library/assets uses read-only connection without taking global write lock."""
        holding_event = threading.Event()
        done_event = threading.Event()

        def _hold_write_lock():
            with self.db.transaction() as tx:
                tx.execute("SELECT 1")
                holding_event.set()
                done_event.wait(timeout=2.0)

        t = threading.Thread(target=_hold_write_lock)
        t.start()
        try:
            holding_event.wait(timeout=2.0)
            start_t = time.time()
            s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
            elapsed = time.time() - start_t
            self.assertEqual(s_get, 200)
            self.assertLess(elapsed, 1.0)
        finally:
            done_event.set()
            t.join()


    def test_32_forum_uid_adoption_and_idempotent_put(self):
        """Test N1: PUT with forum assetUid adopts it into personal library without 500 or orphan files."""
        # 1. Upload forum image via POST /api/uploads with cat='forum'
        d1, sha1, _ = _make_data_url(color=(80, 80, 80))
        s_upl, res_upl, _ = self._request("POST", "/api/uploads", {"dataUrl": d1, "cat": "forum", "nameZh": "Forum Image"}, cookie=self.cookie_a)
        self.assertEqual(s_upl, 200)
        forum_uid = res_upl.get("assetUid")
        self.assertTrue(forum_uid)

        # GET /api/library/assets does NOT show forum upload initially
        s_get1, res_get1, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get1, 200)
        uids_initial = [it["uid"] for it in res_get1["items"]]
        self.assertNotIn(forum_uid, uids_initial)

        # 2. PUT /api/library/assets/{forum_uid} adopts this forum image
        d2, sha2, _ = _make_data_url(color=(85, 85, 85))
        s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{forum_uid}", {"dataUrl": d2, "name": "Adopted Asset"}, cookie=self.cookie_a)
        self.assertIn(s_put, (200, 201))
        self.assertEqual(res_put["uid"], forum_uid)

        # Verify only 1 row in database for this UID
        rows = self.db.get_conn().execute("SELECT * FROM user_uploads WHERE asset_uid = ?", (forum_uid,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cat"], "other")

        # 3. GET /api/library/assets shows the adopted asset
        s_get2, res_get2, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
        self.assertEqual(s_get2, 200)
        uids_after = [it["uid"] for it in res_get2["items"]]
        self.assertIn(forum_uid, uids_after)

        # 4. GET /api/library/assets/{forum_uid}/image returns 200
        tok = self._create_token(self.user_a["id"], ["library"])
        s_img, _, b_img = self._request("GET", f"/api/library/assets/{forum_uid}/image", bearer=tok)
        self.assertEqual(s_img, 200)
        self.assertTrue(len(b_img) > 0)

        # 5. Repeat PUT with identical data is idempotent (returns 200 without creating duplicate row)
        s_put_repeat, res_put_repeat, _ = self._request("PUT", f"/api/library/assets/{forum_uid}", {"dataUrl": d2, "name": "Adopted Asset"}, cookie=self.cookie_a)
        self.assertEqual(s_put_repeat, 200)
        rows_repeat = self.db.get_conn().execute("SELECT * FROM user_uploads WHERE asset_uid = ?", (forum_uid,)).fetchall()
        self.assertEqual(len(rows_repeat), 1)

        # 6. DELETE /api/library/assets/{forum_uid}?baseRevision=1 returns 200
        s_del, res_del, _ = self._request("DELETE", f"/api/library/assets/{forum_uid}?baseRevision=1", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)
        self.assertTrue(res_del.get("deletedAt"))

    def test_33_migration_066_normalizes_uppercase_and_braced_uuids(self):
        """Test N2: Migration 066 normalizes historical uppercase, braced, URN, and unhyphenated UUIDs to lowercase 8-4-4-4-12."""
        raw_uuid_1 = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        upper_uuid = raw_uuid_1.upper()
        raw_uuid_2 = "2fa12345-6789-4abc-def0-123456789abc"
        braced_uuid = f"{{{raw_uuid_2}}}"
        raw_uuid_3 = "3e4f5a6b-7c8d-9e0f-1a2b-3c4d5e6f7a8b"
        urn_uuid = f"urn:uuid:{raw_uuid_3.upper()}"
        raw_uuid_4 = "4f5a6b7c-8d9e-0f1a-2b3c-4d5e6f7a8b9c"
        nodash_uuid = raw_uuid_4.replace("-", "")
        invalid_uid = "abc-not-a-uuid"

        uploads_dir = Path(os.environ["HANDRAW_UPLOADS_DIR"])
        dummy_file = uploads_dir / "dummy_norm.png"
        dummy_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82")

        # Insert historical rows directly into database with various non-canonical formats and invalid format
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, asset_uid, image_url, file_path, bytes, sha256, revision, change_seq, created_at, updated_at)
                VALUES ('UPL_hist_1', ?, 'characters', 'Hist Upper', ?, '/uploads/dummy_norm.png', ?, 100, 'sha1', 1, 100, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                       ('UPL_hist_2', ?, 'props', 'Hist Braced', ?, '/uploads/dummy_norm.png', ?, 100, 'sha2', 1, 101, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                       ('UPL_hist_3', ?, 'scenes', 'Hist URN', ?, '/uploads/dummy_norm.png', ?, 100, 'sha3', 1, 102, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                       ('UPL_hist_4', ?, 'other', 'Hist NoDash', ?, '/uploads/dummy_norm.png', ?, 100, 'sha4', 1, 103, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                       ('UPL_hist_5', ?, 'other', 'Hist Invalid', ?, '/uploads/dummy_norm.png', ?, 100, 'sha5', 1, 104, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (
                    self.user_a["id"], upper_uuid, str(dummy_file),
                    self.user_a["id"], braced_uuid, str(dummy_file),
                    self.user_a["id"], urn_uuid, str(dummy_file),
                    self.user_a["id"], nodash_uuid, str(dummy_file),
                    self.user_a["id"], invalid_uid, str(dummy_file),
                ),
            )

        # Run Migration 066 logic (first run)
        from backend.work_schema import normalize_historical_asset_uids
        conn = self.db.get_conn()
        normalize_historical_asset_uids(conn)

        # Verify DB rows are now canonical lowercase 8-4-4-4-12
        row1 = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_1'").fetchone()
        self.assertEqual(row1["asset_uid"], raw_uuid_1.lower())

        row2 = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_2'").fetchone()
        self.assertEqual(row2["asset_uid"], raw_uuid_2.lower())

        # Check URN row -> canonical lowercase
        row3 = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_3'").fetchone()
        self.assertEqual(row3["asset_uid"], raw_uuid_3.lower())

        # Check unhyphenated row -> canonical lowercase
        row4 = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_4'").fetchone()
        self.assertEqual(row4["asset_uid"], raw_uuid_4.lower())

        # Check invalid non-UUID row -> preserved as original, whole batch did not rollback
        row5 = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_5'").fetchone()
        self.assertEqual(row5["asset_uid"], invalid_uid)

        # Check Idempotence: run migration hook a second time
        normalize_historical_asset_uids(conn)
        row1_again = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_1'").fetchone()
        self.assertEqual(row1_again["asset_uid"], raw_uuid_1.lower())
        row3_again = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_3'").fetchone()
        self.assertEqual(row3_again["asset_uid"], raw_uuid_3.lower())
        row4_again = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_4'").fetchone()
        self.assertEqual(row4_again["asset_uid"], raw_uuid_4.lower())
        row5_again = conn.execute("SELECT asset_uid FROM user_uploads WHERE id = 'UPL_hist_5'").fetchone()
        self.assertEqual(row5_again["asset_uid"], invalid_uid)

        # Verify URN row operates cleanly via HTTP:
        tok = self._create_token(self.user_a["id"], ["library"])
        # GET .../image returns 200
        s_img, _, b_img = self._request("GET", f"/api/library/assets/{raw_uuid_3.lower()}/image", bearer=tok)
        self.assertEqual(s_img, 200)

        # PUT updates existing row (baseRevision=1) instead of creating second row
        s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{raw_uuid_3.lower()}", {"baseRevision": 1, "name": "Updated URN"}, cookie=self.cookie_a)
        self.assertEqual(s_put, 200)
        self.assertEqual(res_put["revision"], 2)
        count_urn = self.db.get_conn().execute("SELECT COUNT(*) FROM user_uploads WHERE asset_uid = ?", (raw_uuid_3.lower(),)).fetchone()[0]
        self.assertEqual(count_urn, 1)

        # DELETE returns 200
        s_del, res_del, _ = self._request("DELETE", f"/api/library/assets/{raw_uuid_3.lower()}?baseRevision=2", cookie=self.cookie_a)
        self.assertEqual(s_del, 200)

        # Verify unhyphenated row operates cleanly via HTTP:
        # GET .../image returns 200
        s_img4, _, _ = self._request("GET", f"/api/library/assets/{raw_uuid_4.lower()}/image", bearer=tok)
        self.assertEqual(s_img4, 200)

        # PUT updates row
        s_put4, res_put4, _ = self._request("PUT", f"/api/library/assets/{raw_uuid_4.lower()}", {"baseRevision": 1, "name": "Updated NoDash"}, cookie=self.cookie_a)
        self.assertEqual(s_put4, 200)
        count_nodash = self.db.get_conn().execute("SELECT COUNT(*) FROM user_uploads WHERE asset_uid = ?", (raw_uuid_4.lower(),)).fetchone()[0]
        self.assertEqual(count_nodash, 1)

        # DELETE returns 200
        s_del4, res_del4, _ = self._request("DELETE", f"/api/library/assets/{raw_uuid_4.lower()}?baseRevision=2", cookie=self.cookie_a)
        self.assertEqual(s_del4, 200)

    def test_34_backfill_does_not_let_forum_steal_sha(self):
        """An unsynced row and a forum upload cannot hijack fresh V3 dedup."""
        d, test_sha, _ = _make_data_url(color=(100, 100, 100))
        from backend.runtime_policy import decode_data_image_url

        uploads_dir = Path(os.environ["HANDRAW_UPLOADS_DIR"])
        dummy_file = uploads_dir / "lib_dummy_sha.png"
        dummy_file.write_bytes(decode_data_image_url(d)[0])

        with self.db.transaction() as tx:
            # 1. Existing forum row with this sha
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, asset_uid, image_url, file_path, bytes, sha256, revision, change_seq, created_at, updated_at)
                VALUES ('UPL_forum_sha', ?, 'forum', 'Forum Pic', 'uid-forum-sha', '/uploads/forum.png', '', 100, ?, 1, 200, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (self.user_a["id"], test_sha),
            )
            # 2. Existing library row without sha256 and without asset_uid
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, asset_uid, image_url, file_path, bytes, sha256, revision, change_seq, created_at, updated_at)
                VALUES ('UPL_lib_nosha', ?, 'props', 'Library Asset No SHA', NULL, '/uploads/lib_dummy_sha.png', ?, 100, NULL, 1, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (self.user_a["id"], str(dummy_file)),
            )

        from backend.user_library import ensure_user_uploads_synced
        ensure_user_uploads_synced(self.db, self.user_a["id"])

        # V3 never retroactively synthesizes a SHA or UID on a read.
        lib_row = self.db.get_conn().execute(
            "SELECT asset_uid,sha256 FROM user_uploads WHERE id='UPL_lib_nosha'"
        ).fetchone()
        self.assertIsNone(lib_row["asset_uid"])
        self.assertIsNone(lib_row["sha256"])
        # Newly uploaded image must be its own owned asset, not forum or
        # malformed legacy content sharing the same hash.
        new_uid = str(uuid.uuid4())
        s_put, res_put, _ = self._request(
            "PUT", f"/api/library/assets/{new_uid}",
            {"dataUrl": d, "name": "Dedup Test"}, cookie=self.cookie_a,
        )
        self.assertEqual(s_put, 201)
        self.assertEqual(res_put["uid"], new_uid)
        fresh = self.db.get_conn().execute(
            "SELECT sha256 FROM user_uploads WHERE asset_uid=?", (new_uid,)
        ).fetchone()
        self.assertEqual(fresh["sha256"], test_sha)

    def test_35_get_assets_fast_and_non_blocking_under_write_lock(self):
        """Test N4: GET /api/library/assets executes in < 1s and returns 200 without partial data when write lock is held."""
        # Insert an unsynced row for user_a
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, asset_uid, image_url, file_path, bytes, sha256, revision, change_seq, created_at, updated_at)
                VALUES ('UPL_unsynced_lock', ?, 'characters', 'Unsynced Asset', NULL, '/uploads/dummy.png', '', 100, NULL, 1, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (self.user_a["id"],),
            )

        holding_event = threading.Event()
        release_event = threading.Event()

        def _hold_write():
            with self.db.transaction() as tx:
                tx.execute("SELECT 1")
                holding_event.set()
                release_event.wait(timeout=3.0)

        t = threading.Thread(target=_hold_write)
        t.start()
        try:
            holding_event.wait(timeout=2.0)
            start_t = time.time()
            s_get, res_get, _ = self._request("GET", "/api/library/assets", cookie=self.cookie_a)
            elapsed = time.time() - start_t
            self.assertEqual(s_get, 200)
            self.assertLess(elapsed, 1.0)
            # Verify no partial asset (empty uid) is returned
            for it in res_get.get("items", []):
                self.assertTrue(it.get("uid"), "Item must not have empty uid")
        finally:
            release_event.set()
            t.join()

    def test_36_commit_failure_cleans_up_orphan_files(self):
        """Test N5: When transaction fails or is aborted before commit, newly created files are cleaned up."""
        uploads_dir = Path(os.environ["HANDRAW_UPLOADS_DIR"])
        files_before = set(uploads_dir.glob("UPL-*"))

        d, _, _ = _make_data_url(color=(110, 110, 110))
        target_uid = str(uuid.uuid4())

        from unittest.mock import patch
        with patch("backend.user_library.next_change_seq", side_effect=RuntimeError("Simulated Commit Crash")):
            s_put, res_put, _ = self._request("PUT", f"/api/library/assets/{target_uid}", {"dataUrl": d, "name": "Fail Asset"}, cookie=self.cookie_a)
            self.assertEqual(s_put, 500)

        files_after = set(uploads_dir.glob("UPL-*"))
        self.assertEqual(files_before, files_after, "No orphan files should remain in uploads dir after failure")

    def test_37_library_storage_failure_is_retryable_without_empty_asset(self):
        """Storage provider errors surface as 503; retrying the UID saves once."""
        data_url, _, _ = _make_data_url()
        uid = _uid("web-library-storage-failure")
        from backend.services import ServiceError

        with patch("backend.media_storage.persist_media_bytes",
                   side_effect=RuntimeError("simulated private object storage outage")):
            st, body, _ = self._request(
                "PUT", f"/api/library/assets/{uid}",
                {"name": "临时存储故障", "cat": "characters",
                 "dataUrl": data_url, "origin": "web"}, cookie=self.cookie_a,
            )
        self.assertEqual(st, 503)
        self.assertEqual(body.get("code"), "library_storage_unavailable")
        row = self.db.get_conn().execute(
            "SELECT id FROM user_uploads WHERE asset_uid = ?", (uid,)
        ).fetchone()
        self.assertIsNone(row, "Failed save must roll back the private asset")

        st, body, _ = self._request(
            "PUT", f"/api/library/assets/{uid}",
            {"name": "临时存储故障", "cat": "characters",
             "dataUrl": data_url, "origin": "web"}, cookie=self.cookie_a,
        )
        self.assertEqual(st, 201)
        self.assertEqual(body.get("uid"), uid)
        row = self.db.get_conn().execute(
            "SELECT COUNT(*) AS n FROM user_uploads WHERE asset_uid = ?", (uid,)
        ).fetchone()
        self.assertEqual(int(row["n"]), 1)


if __name__ == "__main__":
    unittest.main()
