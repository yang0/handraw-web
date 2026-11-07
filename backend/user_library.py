"""User Asset Library and Bi-directional Synchronization.

Conflict Resolution Rules (for Skill client implementation):
1. Optimistic Concurrency via `revision`:
   - Both Web and Skill track `revision` as a strictly increasing integer per asset (starts at 1).
   - When Skill pushes updates to Web (`PUT /api/library/assets/{uid}`), it MUST include
     `baseRevision` matching the revision received from the previous sync.
   - If server revision != `baseRevision`, server rejects the request with HTTP 409 Conflict
     and returns the server's current asset payload in `{"ok": false, "code": "conflict", "current": {...}}`.

2. Handling 409 Conflict:
   - Case A: Server version is soft-deleted (`deletedAt` is non-null), but local has modifications:
     -> If tombstone is expired (> 30 days), server returns 410 `asset_expired`.
     -> If unexpired, Skill calls `POST /api/library/assets/{uid}/restore` first to revive it,
        receives the revived revision, and then issues `PUT` with the new revision.
   - Case B: Both sides modified metadata only:
     -> Compare timestamps using server `updatedAt` (millisecond-precision UTC ISO).
     -> The side with newer `updatedAt` wins. When equal, server version wins.
   - Case C: One side changed image, the other changed metadata only:
     -> Merge: take image from the image-replacement side, take metadata from the newer timestamp side.
   - Case D: Both sides modified image (image replacement collision):
     -> Keep both images! Save the local copy with a new UID as "{original_name} (冲突副本)".
   - Case E: Active duplicate image (`code`: "duplicate_image", HTTP 409):
     -> Returned when replacing image or restoring a tombstone would result in two active assets
        having the identical sha256 under the same account. Response includes `existingUid`.

3. Tombstones and Deletions:
   - Deletions are soft deletes (`deleted_at` set, `revision` and `change_seq` incremented).
   - `DELETE` requires a valid integer `baseRevision` parameter; missing or non-integer returns 400 `base_revision_required`.
   - `GET /api/library/assets?since={cursor}` returns tombstone items containing `deletedAt`.
   - `GET /api/library/assets` (without since) returns only currently active (undeleted) assets.
   - Soft-deleted assets are retained for 30 days and can be restored via `POST /api/library/assets/{uid}/restore`.
   - After 30 days, physical files and records are purged by periodic cleanup tasks (unless referenced by published works).

4. Deduplication & Requested UID:
   - When creating via `PUT /api/library/assets/{uid}`, if an active asset with identical sha256 already exists,
     the server returns `{"ok": true, "deduped": true, "requestedUid": uid, "uid": existing_asset["uid"], "item": {...}}`.
   - The Skill client can map its requested UID to the returned active asset UID.
   - Legacy `POST /api/uploads` also deduplicates against active assets and returns `deduped: true`.

5. Asset URLs:
   - `imageUrl`: `/api/library/assets/{uid}/image` (authorized with `library` scope token for Skill clients).
   - `publicUrl`: `/uploads/...` (original file path for web browser usage).

6. Read-time Lazy Backfill:
   - Older rows lacking `asset_uid` or `change_seq` are backfilled once on the first read.
   - Once backfilled, subsequent reads perform no write operations.

7. UID Requirement:
   - All asset UIDs in `PUT /api/library/assets/{uid}` must be standard UUID strings (e.g. UUIDv4).
   - Non-UUID format strings (such as "CH-002" or short names) are rejected with HTTP 400 `invalid_uid`.
   - Skill clients must generate standard UUIDv4 identifiers when creating new assets.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import mimetypes
import re
import sqlite3
import threading
import time
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

from .config import get_uploads_dir
from .db import Database, utc_now_iso
from .runtime_policy import decode_data_image_url
from .services import ServiceError

logger = logging.getLogger("handraw.user_library")

MAX_ASSETS_PER_USER = 500
MAX_STORAGE_BYTES_PER_USER = 1024 * 1024 * 1024  # 1 GB
TOKEN_RATE_LIMIT_PER_HOUR = 1200
TOKEN_RATE_LIMIT_WINDOW_SECONDS = 3600.0
MAX_RATE_LIMIT_KEYS = 10000
MAX_IMAGE_PIXELS = 40_000_000  # 40M pixels (~6324x6324)

_token_rate_limit_lock = threading.Lock()
_token_rate_logs: dict[str, list[float]] = {}


def utc_now_iso_ms() -> str:
    """Return ISO 8601 UTC timestamp with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _normalize_uuid(val: Any) -> str | None:
    """Validate and normalize UUID string to canonical 8-4-4-4-12 lowercase format.

    Returns canonical lowercase string, or None if invalid.
    """
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    try:
        u = uuid.UUID(s)
        return str(u).lower()
    except (ValueError, AttributeError, TypeError):
        return None



def check_token_rate_limit(
    token_key: str,
    limit: int = TOKEN_RATE_LIMIT_PER_HOUR,
    window_seconds: float = TOKEN_RATE_LIMIT_WINDOW_SECONDS,
) -> bool:
    """Shared Redis token quota in production; bounded local mode for development."""
    from .redis_rate_limit import check_limit
    distributed = check_limit("skill_token", str(token_key))
    if distributed is not None:
        return distributed
    now = time.time()
    with _token_rate_limit_lock:
        cutoff = now - window_seconds
        if token_key not in _token_rate_logs:
            if len(_token_rate_logs) >= MAX_RATE_LIMIT_KEYS:
                # Purge stale keys
                stale = [k for k, v in _token_rate_logs.items() if not v or v[-1] < cutoff]
                for k in stale:
                    _token_rate_logs.pop(k, None)
                if len(_token_rate_logs) >= MAX_RATE_LIMIT_KEYS:
                    return False
            _token_rate_logs[token_key] = []

        timestamps = _token_rate_logs[token_key]
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)
        if len(timestamps) >= limit:
            return False
        timestamps.append(now)
        return True


def next_change_seq(conn: sqlite3.Connection) -> int:
    """Atomically increment and return the global monotonic change sequence number."""
    conn.execute(
        """
        INSERT INTO library_change_counter (id, current_seq) VALUES (1, 1)
        ON CONFLICT(id) DO UPDATE SET current_seq = current_seq + 1;
        """
    )
    row = conn.execute("SELECT current_seq FROM library_change_counter WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("Failed to read change sequence from library_change_counter")
    return int(row["current_seq"] if isinstance(row, sqlite3.Row) else row[0])


def check_user_upload_quota(
    tx: sqlite3.Connection,
    user_id: int,
    new_bytes: int,
    *,
    is_new_item: bool = True,
    existing_bytes: int = 0,
) -> None:
    """Enforce maximum 500 undeleted assets and 1 GB storage limit per user."""
    if is_new_item:
        current_count = tx.execute(
            "SELECT COUNT(*) FROM user_uploads WHERE user_id = ? AND deleted_at IS NULL AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))",
            (user_id,),
        ).fetchone()[0]
        if current_count >= MAX_ASSETS_PER_USER:
            raise ServiceError("资产数量已达上限（最多500个）", status=413, code="asset_count_quota_exceeded")

    current_storage = tx.execute(
        "SELECT COALESCE(SUM(bytes), 0) FROM user_uploads WHERE user_id = ? AND deleted_at IS NULL AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))",
        (user_id,),
    ).fetchone()[0]
    delta = new_bytes - existing_bytes
    if current_storage + delta > MAX_STORAGE_BYTES_PER_USER:
        raise ServiceError("图库存储容量已达上限（最多1GB）", status=413, code="asset_storage_quota_exceeded")


def format_asset(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Format a database row into the standardized user library asset payload."""
    raw_tags = row["tags_json"] if isinstance(row, sqlite3.Row) else row.get("tags_json")
    tags: list[str] = []
    if raw_tags:
        try:
            parsed = json.loads(raw_tags)
            if isinstance(parsed, list):
                tags = [str(t) for t in parsed]
        except Exception:
            pass

    def _val(k: str, default: Any = None) -> Any:
        return row[k] if isinstance(row, sqlite3.Row) else row.get(k, default)

    uid = str(_val("asset_uid") or "")
    raw_image_url = str(_val("image_url") or "")
    # library token clients access /api/library/assets/{uid}/image; web pages can use publicUrl
    api_image_url = f"/api/library/assets/{uid}/image" if uid else raw_image_url

    return {
        "uid": uid,
        "localId": _val("local_id"),
        "cat": str(_val("cat") or "other"),
        "name": str(_val("name_zh") or ""),
        "nameEn": str(_val("name_en") or ""),
        "tags": tags,
        "sha256": str(_val("sha256") or ""),
        "revision": int(_val("revision") or 1),
        "updatedAt": str(_val("updated_at") or _val("created_at") or ""),
        "deletedAt": _val("deleted_at"),
        "origin": str(_val("origin") or "web"),
        "imageUrl": api_image_url,
        "publicUrl": raw_image_url,
        "bytes": int(_val("bytes") or 0),
    }


def ensure_user_uploads_synced(
    db_or_conn: Database | sqlite3.Connection,
    user_id: int,
    *,
    non_blocking: bool = False,
) -> bool:
    """V3 fresh schema: no legacy user-upload migration or SQLite lock polling.

    New uploads have their immutable asset UID, SHA and change sequence at
    creation time. Nothing is read or rewritten on list/sync requests. This
    keeps PostgreSQL and SQLite on the same behavior and avoids filesystem
    scans inside API requests. The parameters remain for existing callers.
    """
    return True


def _enforce_caller(handler: Any) -> tuple[dict[str, Any], int]:
    user = handler._current_user(required=True)
    if user.get("_auth_kind") == "token":
        token_key = str(user.get("_token_id") or user.get("id"))
        if not check_token_rate_limit(token_key):
            raise ServiceError("API 令牌请求过于频繁，请稍后再试", status=429, code="rate_limited")
    return user, int(user["id"])


def _validate_image_and_sha256(data_url: str, provided_sha: str) -> tuple[bytes, str, str]:
    """Validate dataUrl using decode_data_image_url and Pillow (max 40M pixels), and verify sha256."""
    try:
        raw_bytes, ext, _ = decode_data_image_url(data_url)
    except ValueError as exc:
        raise ServiceError(str(exc), status=400, code="invalid_image_upload") from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                w, h = pil_img.size
                if w * h > MAX_IMAGE_PIXELS:
                    raise ServiceError(f"图片尺寸过大（{w}x{h}={w * h} 像素，上限 4000 万像素）", status=413, code="image_too_large")
                pil_img.load()
                fmt = (pil_img.format or "").upper()
                if fmt not in ("PNG", "JPEG", "WEBP"):
                    raise ValueError(f"不支持的图片格式: {fmt}")
    except ServiceError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ServiceError(f"图片像素过多，触发解压炸弹保护: {exc}", status=413, code="image_too_large") from exc
    except Exception as exc:
        raise ServiceError(f"图片无效或已损坏: {exc}", status=400, code="invalid_image") from exc

    computed_sha = hashlib.sha256(raw_bytes).hexdigest()
    if provided_sha and provided_sha.strip().lower() != computed_sha:
        raise ServiceError("图片 sha256 与内容不一致", status=400, code="sha256_mismatch")

    return raw_bytes, ext, computed_sha


def is_media_referenced(
    conn: sqlite3.Connection,
    media_url: str,
    file_path: str,
    *,
    exclude_upload_id: str | None = None,
) -> bool:
    """Check if an image URL or physical file is referenced by active uploads or published content.

    Scans:
    - user_uploads (image_url, file_path)
    - media_public_grants (media_url)
    - works (images_json, prompt)
    - forum_topics (images_json, summary, locked_body, recipe_json)
    - forum_replies (text)
    - studio_recipes (references_json)
    - studio_articles (markdown, cards_json)
    - studio_generations (items_json, markdown)
    - studio_generation_media (media_url, storage_path)
    - curation_versions (payload_json)
    - curation_drafts (draft_json)
    - studio_import_jobs (result_json)
    - catalog_assets (image_url)
    - work_comments (text)
    - asset_comments (text)

    If ANY query encounters an unexpected error, fail-safe by treating the media as referenced (do NOT delete).
    """
    clean_url = (media_url or "").split("?", 1)[0].strip()
    clean_path = (file_path or "").strip()

    if not clean_url and not clean_path:
        return False

    url_like = f"%{clean_url}%" if clean_url else None

    def _check_query(table: str, sql: str, params: tuple) -> bool:
        try:
            row = conn.execute(sql, params).fetchone()
            return bool(row)
        except Exception as exc:
            logger.warning(
                "Error checking media reference in table '%s' for '%s': %s; treating as referenced for safety",
                table,
                clean_url or clean_path,
                exc,
            )
            return True

    # 1. Check other user_uploads records
    if _check_query(
        "user_uploads",
        """
        SELECT 1 FROM user_uploads
        WHERE (image_url = ? OR file_path = ?)
          AND (? IS NULL OR id <> ?)
        LIMIT 1
        """,
        (clean_url, clean_path, exclude_upload_id, exclude_upload_id),
    ):
        return True

    if clean_url:
        # 2. Check media public grants (any grant row means image was shared)
        if _check_query(
            "media_public_grants",
            "SELECT 1 FROM media_public_grants WHERE media_url = ? AND revoked_at IS NULL LIMIT 1",
            (clean_url,),
        ):
            return True

        # 3. Check works (active, draft, paused, or hidden)
        if _check_query(
            "works",
            "SELECT 1 FROM works WHERE images_json LIKE ? OR prompt LIKE ? LIMIT 1",
            (url_like, url_like),
        ):
            return True

        # 4. Check forum topics (active, draft, paused, or hidden)
        if _check_query(
            "forum_topics",
            "SELECT 1 FROM forum_topics WHERE images_json LIKE ? OR summary LIKE ? OR locked_body LIKE ? OR recipe_json LIKE ? LIMIT 1",
            (url_like, url_like, url_like, url_like),
        ):
            return True

        # 5. Check forum replies
        if _check_query(
            "forum_replies",
            "SELECT 1 FROM forum_replies WHERE text LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

        # 6. Check studio recipes
        if _check_query(
            "studio_recipes",
            "SELECT 1 FROM studio_recipes WHERE references_json LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

        # 7. Check studio articles
        if _check_query(
            "studio_articles",
            "SELECT 1 FROM studio_articles WHERE (markdown LIKE ? OR cards_json LIKE ?) AND COALESCE(deleted_at, '') = '' LIMIT 1",
            (url_like, url_like),
        ):
            return True

        # 8. Check studio generations
        if _check_query(
            "studio_generations",
            "SELECT 1 FROM studio_generations WHERE items_json LIKE ? OR markdown LIKE ? LIMIT 1",
            (url_like, url_like),
        ):
            return True

        # 9. Check studio generation media
        if _check_query(
            "studio_generation_media",
            "SELECT 1 FROM studio_generation_media WHERE media_url = ? OR storage_path = ? LIMIT 1",
            (clean_url, clean_path),
        ):
            return True

        # 10. Check curation versions
        if _check_query(
            "curation_versions",
            "SELECT 1 FROM curation_versions WHERE payload_json LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

        # 11. Check curation drafts
        if _check_query(
            "curation_drafts",
            "SELECT 1 FROM curation_drafts WHERE payload_json LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

        # 12. Check studio import jobs
        if _check_query(
            "studio_import_jobs",
            "SELECT 1 FROM studio_import_jobs WHERE result_json LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

        # 13. Check catalog assets
        if _check_query(
            "catalog_assets",
            "SELECT 1 FROM catalog_assets WHERE image_url = ? LIMIT 1",
            (clean_url,),
        ):
            return True

        # 14. Check work comments
        if _check_query(
            "work_comments",
            "SELECT 1 FROM work_comments WHERE text LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

        # 15. Check asset comments
        if _check_query(
            "asset_comments",
            "SELECT 1 FROM asset_comments WHERE text LIKE ? LIMIT 1",
            (url_like,),
        ):
            return True

    return False


def cleanup_expired_library_tombstones(db: Database, max_age_days: int = 30) -> int:
    """Delete library tombstones older than max_age_days and unlink their files if unreferenced."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cleaned_count = 0

    try:
        with db.transaction() as tx:
            rows = tx.execute(
                """
                SELECT id, image_url, file_path FROM user_uploads
                WHERE deleted_at IS NOT NULL AND deleted_at < ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                """,
                (cutoff,),
            ).fetchall()
    except Exception:
        return 0

    for row in rows:
        url = row["image_url"]
        fpath_str = row["file_path"]
        rid = row["id"]

        with db.transaction() as tx:
            # Library retention ends here; the actual private object is
            # deleted later after ALL other references have disappeared.
            tx.execute("DELETE FROM user_uploads WHERE id = ?", (rid,))
            if str(url or "").startswith(("/uploads/", "/generated/")):
                from .media_gc import queue_media_cleanup
                queue_media_cleanup(tx, str(url))
            cleaned_count += 1

    return cleaned_count


def list_assets(
    db: Database,
    user_id: int,
    since: int | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """List assets incrementally with cursor (excluding cat='import'), or list all undeleted assets."""
    limit = max(1, min(limit, 500))
    ensure_user_uploads_synced(db, user_id, non_blocking=True)
    conn = db.get_conn()
    if since is not None:
        rows = conn.execute(
            """
            SELECT * FROM user_uploads
            WHERE user_id = ? AND change_seq > ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
              AND asset_uid IS NOT NULL AND asset_uid <> '' AND change_seq IS NOT NULL
            ORDER BY change_seq ASC
            LIMIT ?
            """,
            (user_id, since, limit + 1),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM user_uploads
            WHERE user_id = ? AND deleted_at IS NULL AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
              AND asset_uid IS NOT NULL AND asset_uid <> '' AND change_seq IS NOT NULL
            ORDER BY change_seq ASC
            LIMIT ?
            """,
            (user_id, limit + 1),
        ).fetchall()

    has_more = len(rows) > limit
    items = rows[:limit]
    if items:
        next_cursor = str(items[-1]["change_seq"])
    elif since is not None:
        next_cursor = str(since)
    else:
        next_cursor = None

    return {
        "ok": True,
        "items": [format_asset(r) for r in items],
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


def handle_library_get(handler: Any, req_path: str, qs: dict[str, list[str]]) -> bool:
    """Handle GET /api/library/assets and GET /api/library/assets/{uid}/image."""
    if req_path == "/api/library/assets":
        user, user_id = _enforce_caller(handler)
        since_val = None
        since_raw = qs.get("since", [None])[0]
        if since_raw is not None and since_raw.strip() != "":
            try:
                since_val = int(since_raw.strip())
            except ValueError:
                raise ServiceError("无效的游标 since 参数", status=400, code="invalid_cursor")

        limit = 200
        limit_raw = qs.get("limit", [None])[0]
        if limit_raw is not None and limit_raw.strip() != "":
            try:
                limit = int(limit_raw.strip())
            except ValueError:
                pass

        result = list_assets(handler.db, user_id, since=since_val, limit=limit)
        handler._send_json(result)
        return True

    m_img = re.fullmatch(r"^/api/library/assets/([^/]+)/image$", req_path)
    if m_img:
        user, user_id = _enforce_caller(handler)
        raw_uid = unquote(m_img.group(1)).strip()
        uid = _normalize_uuid(raw_uid)
        if not uid:
            handler._send_json({"ok": False, "error": "Asset not found"}, status=404)
            return True
        conn = handler.db.get_conn()
        row = conn.execute(
            "SELECT * FROM user_uploads WHERE user_id = ? AND asset_uid = ? LIMIT 1",
            (user_id, uid),
        ).fetchone()
        if not row or row["deleted_at"] is not None:
            handler._send_json({"ok": False, "error": "Asset not found"}, status=404)
            return True

        fpath_str = str(row["file_path"] or "")
        fpath = Path(fpath_str) if fpath_str else None
        if not fpath or not fpath.is_file():
            handler._send_json({"ok": False, "error": "Image file not found"}, status=404)
            return True

        ctype = mimetypes.guess_type(str(fpath))[0] or "image/png"
        handler._send_bytes(fpath.read_bytes(), ctype, cache="private, max-age=86400")
        return True

    return False


def handle_library_put(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    """Handle PUT /api/library/assets/{uid}."""
    m = re.fullmatch(r"^/api/library/assets/([^/]+)$", req_path)
    if not m:
        return False

    user, user_id = _enforce_caller(handler)
    raw_uid = unquote(m.group(1)).strip()
    uid = _normalize_uuid(raw_uid)
    if not uid:
        raise ServiceError("资产 uid 必须为有效 UUID 格式", status=400, code="invalid_uid")

    data_url = str(body.get("dataUrl") or body.get("image") or "").strip()
    provided_sha = str(body.get("sha256") or "").strip().lower()
    origin = str(body.get("origin") or "skill").strip()

    raw_bytes = None
    ext = ".webp"
    computed_sha = provided_sha
    if data_url:
        raw_bytes, ext, computed_sha = _validate_image_and_sha256(data_url, provided_sha)

    # Fresh V3 accounts always create fully populated asset metadata.
    # No compatibility/backfill pass is needed in the request path.

    resp_payload: dict[str, Any] | None = None
    resp_status: int = 200
    file_to_unlink: str | None = None
    file_to_unlink_url: str | None = None
    newly_created_file: Path | None = None
    newly_created_url: str | None = None

    try:
        with handler.db.transaction() as tx:
            # Check if UID belongs to another user (UID is globally unique: foreign UID returns 404)
            foreign = tx.execute(
                "SELECT user_id FROM user_uploads WHERE asset_uid = ? AND user_id <> ? LIMIT 1",
                (uid, user_id),
            ).fetchone()
            if foreign is not None:
                resp_payload = {"ok": False, "error": "Asset not found"}
                resp_status = 404
            else:
                existing = tx.execute(
                    "SELECT * FROM user_uploads WHERE user_id = ? AND asset_uid = ? LIMIT 1",
                    (user_id, uid),
                ).fetchone()

                if existing is not None:
                    is_forum = (existing["cat"] == "forum")
                    is_tombstone = existing["deleted_at"] is not None

                    if is_forum and not is_tombstone:
                        # N1: Adopt forum row into personal library asset
                        # Forum row did not count toward library quota; adopting it counts as a new item.
                        new_image_len = len(raw_bytes) if raw_bytes is not None else int(existing["bytes"] or 0)
                        check_user_upload_quota(tx, user_id, new_image_len, is_new_item=True)

                        target_sha = computed_sha if raw_bytes is not None else existing["sha256"]
                        if target_sha:
                            dup_active = tx.execute(
                                """
                                SELECT asset_uid FROM user_uploads
                                WHERE user_id = ? AND sha256 = ? AND deleted_at IS NULL AND asset_uid <> ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                                LIMIT 1
                                """,
                                (user_id, target_sha, uid),
                            ).fetchone()
                            if dup_active is not None:
                                resp_payload = {
                                    "ok": False,
                                    "error": "同一账号下图库资产内容不可重复",
                                    "code": "duplicate_image",
                                    "existingUid": dup_active["asset_uid"],
                                }
                                resp_status = 409

                        if resp_payload is None:
                            old_file_path = existing["file_path"]
                            old_image_url = existing["image_url"]
                            if raw_bytes is not None:
                                uploads_dir = get_uploads_dir()
                                uploads_dir.mkdir(parents=True, exist_ok=True)
                                fname = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}{ext}"
                                fpath = uploads_dir / fname
                                newly_created_url = f"/uploads/{fname}"
                                from .media_storage import persist_media_bytes
                                persist_media_bytes(newly_created_url, raw_bytes)
                                newly_created_file = fpath
                                image_url = f"/uploads/{fname}"
                                file_path_str = str(fpath)
                                bytes_count = len(raw_bytes)
                                final_sha = computed_sha

                                if old_file_path and old_file_path != file_path_str:
                                    if not is_media_referenced(tx, old_image_url, old_file_path, exclude_upload_id=existing["id"]):
                                        file_to_unlink = old_file_path
                                        file_to_unlink_url = old_image_url
                            else:
                                image_url = existing["image_url"]
                                file_path_str = existing["file_path"]
                                bytes_count = existing["bytes"]
                                final_sha = existing["sha256"]

                            c = str(body.get("cat") or "other").strip().lower()
                            final_cat = c if c in ("characters", "props", "scenes", "other") else "other"
                            raw_n = body.get("name") if "name" in body else body.get("nameZh")
                            final_name = str(raw_n or existing["name_zh"] or "自建资产").strip()[:60] or "自建资产"
                            raw_ne = body.get("nameEn") if "nameEn" in body else body.get("name_en")
                            final_name_en = str(raw_ne or existing["name_en"] or "").strip()[:100]
                            raw_l = body.get("localId")
                            final_local_id = str(raw_l).strip() if raw_l else existing["local_id"]

                            if "tags" in body:
                                raw_t = body.get("tags")
                                final_tags = [str(t) for t in raw_t] if isinstance(raw_t, list) else []
                                tags_json = json.dumps(final_tags, ensure_ascii=False)
                            else:
                                tags_json = existing["tags_json"]

                            now = utc_now_iso_ms()
                            new_seq = next_change_seq(tx)

                            tx.execute(
                                """
                                UPDATE user_uploads
                                SET cat = ?, name_zh = ?, name_en = ?, tags_json = ?, local_id = ?,
                                    sha256 = ?, revision = 1, change_seq = ?, updated_at = ?, deleted_at = NULL,
                                    image_url = ?, file_path = ?, bytes = ?, origin = COALESCE(origin, 'web')
                                WHERE id = ? AND user_id = ?
                                """,
                                (
                                    final_cat, final_name, final_name_en, tags_json, final_local_id,
                                    final_sha, new_seq, now,
                                    image_url, file_path_str, bytes_count,
                                    existing["id"], user_id,
                                ),
                            )
                            updated_row = tx.execute("SELECT * FROM user_uploads WHERE id = ?", (existing["id"],)).fetchone()
                            res_asset = format_asset(updated_row)
                            resp_payload = {"ok": True, "deduped": False, "item": res_asset, **res_asset}
                            resp_status = 200

                    elif is_tombstone:
                        # 1. If tombstone, check 30-day expiry first
                        dt_str = str(existing["deleted_at"])
                        try:
                            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            if (datetime.now(timezone.utc) - dt).total_seconds() > 30 * 86400:
                                raise ServiceError("资产已超过30天恢复期限", status=410, code="asset_expired")
                        except ValueError:
                            pass

                        # Updating a tombstone requires baseRevision
                        if "baseRevision" not in body or body.get("baseRevision") is None:
                            raise ServiceError("更新资产必须提供 baseRevision", status=400, code="missing_base_revision")
                        try:
                            base_rev_int = int(body["baseRevision"])
                        except (ValueError, TypeError):
                            raise ServiceError("invalid_base_revision", status=400, code="invalid_base_revision")

                        if base_rev_int != int(existing["revision"]):
                            resp_payload = {
                                "ok": False,
                                "error": "资产版本冲突",
                                "code": "conflict",
                                "current": format_asset(existing),
                            }
                            resp_status = 409
                        else:
                            # Check if reviving collides with an existing active asset's sha256 (library categories only)
                            target_sha = computed_sha if raw_bytes is not None else existing["sha256"]
                            dup_active = tx.execute(
                                """
                                SELECT asset_uid FROM user_uploads
                                WHERE user_id = ? AND sha256 = ? AND deleted_at IS NULL AND asset_uid <> ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                                LIMIT 1
                                """,
                                (user_id, target_sha, uid),
                            ).fetchone()
                            if dup_active is not None:
                                resp_payload = {
                                    "ok": False,
                                    "error": "同一账号下已存在相同内容的活动资产，无法恢复",
                                    "code": "duplicate_image",
                                    "existingUid": dup_active["asset_uid"],
                                }
                                resp_status = 409
                            else:
                                # Check quota (reviving tombstone adds to active count and storage)
                                new_image_len = len(raw_bytes) if raw_bytes is not None else int(existing["bytes"] or 0)
                                check_user_upload_quota(tx, user_id, new_image_len, is_new_item=True)

                    else:
                        # Active library asset
                        has_base_rev = "baseRevision" in body and body.get("baseRevision") is not None
                        if not has_base_rev:
                            # Check if idempotent retry (same image / content)
                            if computed_sha and computed_sha == existing["sha256"]:
                                res_asset = format_asset(existing)
                                resp_payload = {"ok": True, "deduped": False, "item": res_asset, **res_asset}
                                resp_status = 200
                            else:
                                raise ServiceError("更新资产必须提供 baseRevision", status=400, code="missing_base_revision")
                        else:
                            try:
                                base_rev_int = int(body["baseRevision"])
                            except (ValueError, TypeError):
                                raise ServiceError("invalid_base_revision", status=400, code="invalid_base_revision")

                            if base_rev_int != int(existing["revision"]):
                                resp_payload = {
                                    "ok": False,
                                    "error": "资产版本冲突",
                                    "code": "conflict",
                                    "current": format_asset(existing),
                                }
                                resp_status = 409
                            elif raw_bytes is not None:
                                dup_active = tx.execute(
                                    """
                                    SELECT asset_uid FROM user_uploads
                                    WHERE user_id = ? AND sha256 = ? AND deleted_at IS NULL AND asset_uid <> ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                                    LIMIT 1
                                    """,
                                    (user_id, computed_sha, uid),
                                ).fetchone()
                                if dup_active is not None:
                                    resp_payload = {
                                        "ok": False,
                                        "error": "同一账号下图库资产内容不可重复",
                                        "code": "duplicate_image",
                                        "existingUid": dup_active["asset_uid"],
                                    }
                                    resp_status = 409
                                else:
                                    check_user_upload_quota(
                                        tx,
                                        user_id,
                                        len(raw_bytes),
                                        is_new_item=False,
                                        existing_bytes=int(existing["bytes"] or 0),
                                    )

                    # If no conflict so far and not already handled in forum adoption or idempotent retry, perform update
                    if resp_payload is None:
                        old_file_path = existing["file_path"]
                        old_image_url = existing["image_url"]
                        if raw_bytes is not None:
                            uploads_dir = get_uploads_dir()
                            uploads_dir.mkdir(parents=True, exist_ok=True)
                            fname = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}{ext}"
                            fpath = uploads_dir / fname
                            newly_created_url = f"/uploads/{fname}"
                            from .media_storage import persist_media_bytes
                            persist_media_bytes(newly_created_url, raw_bytes)
                            newly_created_file = fpath
                            image_url = f"/uploads/{fname}"
                            file_path_str = str(fpath)
                            bytes_count = len(raw_bytes)
                            final_sha = computed_sha

                            # Mark unreferenced old file for deletion after commit
                            if old_file_path and old_file_path != file_path_str:
                                if not is_media_referenced(tx, old_image_url, old_file_path, exclude_upload_id=existing["id"]):
                                    file_to_unlink = old_file_path
                                    file_to_unlink_url = old_image_url
                        else:
                            image_url = existing["image_url"]
                            file_path_str = existing["file_path"]
                            bytes_count = existing["bytes"]
                            final_sha = existing["sha256"]

                        if "name" in body or "nameZh" in body:
                            raw_n = body.get("name") if "name" in body else body.get("nameZh")
                            final_name = str(raw_n or "").strip()[:60]
                            if not final_name:
                                final_name = "自建资产"
                        else:
                            final_name = existing["name_zh"]

                        if "nameEn" in body or "name_en" in body:
                            raw_ne = body.get("nameEn") if "nameEn" in body else body.get("name_en")
                            final_name_en = str(raw_ne or "").strip()[:100]
                        else:
                            final_name_en = existing["name_en"]

                        if "tags" in body:
                            raw_t = body.get("tags")
                            final_tags = [str(t) for t in raw_t] if isinstance(raw_t, list) else []
                            tags_json = json.dumps(final_tags, ensure_ascii=False)
                        else:
                            tags_json = existing["tags_json"]

                        if "cat" in body:
                            c = str(body.get("cat") or "other").strip().lower()
                            final_cat = c if c in ("characters", "props", "scenes", "other") else "other"
                        else:
                            final_cat = existing["cat"]

                        if "localId" in body:
                            raw_l = body.get("localId")
                            final_local_id = str(raw_l).strip() if raw_l else None
                        else:
                            final_local_id = existing["local_id"]

                        now = utc_now_iso_ms()
                        new_seq = next_change_seq(tx)
                        new_revision = int(existing["revision"]) + 1

                        tx.execute(
                            """
                            UPDATE user_uploads
                            SET local_id = ?, cat = ?, name_zh = ?, name_en = ?, tags_json = ?,
                                sha256 = ?, revision = ?, change_seq = ?, updated_at = ?, deleted_at = NULL,
                                image_url = ?, file_path = ?, bytes = ?
                            WHERE id = ? AND user_id = ?
                            """,
                            (
                                final_local_id, final_cat, final_name, final_name_en, tags_json,
                                final_sha, new_revision, new_seq, now,
                                image_url, file_path_str, bytes_count,
                                existing["id"], user_id,
                            ),
                        )
                        updated_row = tx.execute("SELECT * FROM user_uploads WHERE id = ?", (existing["id"],)).fetchone()
                        res_asset = format_asset(updated_row)
                        resp_payload = {"ok": True, "deduped": False, "item": res_asset, **res_asset}
                        resp_status = 200

                else:
                    # Creating a brand new asset: requires dataUrl
                    if not data_url or raw_bytes is None:
                        raise ServiceError("创建资产必须提供 dataUrl", status=400, code="missing_data_url")

                    # Deduplication check against active assets for this user (library categories only)
                    existing_dup = tx.execute(
                        """
                        SELECT * FROM user_uploads
                        WHERE user_id = ? AND sha256 = ? AND deleted_at IS NULL AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                        LIMIT 1
                        """,
                        (user_id, computed_sha),
                    ).fetchone()
                    if existing_dup is not None:
                        res_dup = format_asset(existing_dup)
                        resp_payload = {
                            "ok": True,
                            "deduped": True,
                            "requestedUid": uid,
                            "uid": res_dup["uid"],
                            "item": res_dup,
                            **res_dup,
                        }
                        resp_status = 200
                    else:
                        # Check unified quotas (500 assets, 1 GB storage)
                        check_user_upload_quota(tx, user_id, len(raw_bytes), is_new_item=True)

                        uploads_dir = get_uploads_dir()
                        uploads_dir.mkdir(parents=True, exist_ok=True)
                        fname = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}{ext}"
                        fpath = uploads_dir / fname
                        newly_created_url = f"/uploads/{fname}"
                        from .media_storage import persist_media_bytes
                        persist_media_bytes(newly_created_url, raw_bytes)
                        newly_created_file = fpath
                        image_url = f"/uploads/{fname}"

                        name = str(body.get("name") or body.get("nameZh") or "").strip()[:60] or "自建资产"
                        name_en = str(body.get("nameEn") or body.get("name_en") or "").strip()[:100]
                        local_id = str(body.get("localId") or "").strip() or None
                        cat_in = str(body.get("cat") or "other").strip().lower()
                        cat = cat_in if cat_in in ("characters", "props", "scenes", "other") else "other"
                        tags = body.get("tags")
                        tags_list = [str(t) for t in tags] if isinstance(tags, list) else []
                        tags_json = json.dumps(tags_list, ensure_ascii=False)

                        now = utc_now_iso_ms()
                        up_id = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
                        new_seq = next_change_seq(tx)
                        tx.execute(
                            """
                            INSERT INTO user_uploads (
                                id, user_id, cat, name_zh, desc_zh, image_url, file_path, bytes, created_at,
                                asset_uid, local_id, name_en, tags_json, sha256, revision, change_seq, updated_at, deleted_at, origin
                            )
                            VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, ?)
                            """,
                            (
                                up_id, user_id, cat, name, image_url, str(fpath), len(raw_bytes), now,
                                uid, local_id, name_en, tags_json, computed_sha, new_seq, now, origin,
                            ),
                        )
                        new_row = tx.execute("SELECT * FROM user_uploads WHERE id = ?", (up_id,)).fetchone()
                        res_asset = format_asset(new_row)
                        resp_payload = {"ok": True, "deduped": False, "item": res_asset, **res_asset}
                        resp_status = 201
            if file_to_unlink_url:
                # Must commit cleanup intent atomically with the asset update.
                from .media_gc import queue_media_cleanup
                queue_media_cleanup(tx, file_to_unlink_url)
    except Exception:
        if newly_created_url:
            from .media_storage import discard_uncommitted_media
            discard_uncommitted_media(handler.db, newly_created_url)
        elif newly_created_file is not None:
            newly_created_file.unlink(missing_ok=True)
        raise

    # Old media is reclaimed asynchronously only after its references vanish.

    # Send response AFTER transaction has committed
    if resp_payload is not None:
        handler._send_json(resp_payload, status=resp_status)
        return True
    return False


def handle_library_delete(handler: Any, req_path: str, qs: dict[str, list[str]]) -> bool:
    """Handle DELETE /api/library/assets/{uid}?baseRevision=."""
    m = re.fullmatch(r"^/api/library/assets/([^/]+)$", req_path)
    if not m:
        return False

    user, user_id = _enforce_caller(handler)
    raw_uid = unquote(m.group(1)).strip()
    uid = _normalize_uuid(raw_uid)
    if not uid:
        handler._send_json({"ok": False, "error": "Asset not found"}, status=404)
        return True

    resp_payload: dict[str, Any] | None = None
    resp_status: int = 200

    with handler.db.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM user_uploads WHERE user_id = ? AND asset_uid = ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other')) LIMIT 1",
            (user_id, uid),
        ).fetchone()
        if not row or row["deleted_at"] is not None:
            resp_payload = {"ok": False, "error": "Asset not found"}
            resp_status = 404
        else:
            # Enforce baseRevision requirement
            base_revision = qs.get("baseRevision", [None])[0]
            if base_revision is None or str(base_revision).strip() == "":
                raise ServiceError("删除资产必须提供 baseRevision", status=400, code="base_revision_required")
            try:
                base_rev_int = int(str(base_revision).strip())
            except (ValueError, TypeError):
                raise ServiceError("baseRevision 必须为整数", status=400, code="base_revision_required")

            if base_rev_int != int(row["revision"]):
                resp_payload = {
                    "ok": False,
                    "error": "资产版本冲突",
                    "code": "conflict",
                    "current": format_asset(row),
                }
                resp_status = 409
            else:
                now = utc_now_iso_ms()
                new_seq = next_change_seq(tx)
                new_revision = int(row["revision"]) + 1
                tx.execute(
                    """
                    UPDATE user_uploads
                    SET deleted_at = ?, revision = ?, change_seq = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (now, new_revision, new_seq, now, row["id"], user_id),
                )
                updated_row = tx.execute("SELECT * FROM user_uploads WHERE id = ?", (row["id"],)).fetchone()
                tombstone = format_asset(updated_row)
                resp_payload = {"ok": True, "tombstone": tombstone, "item": tombstone, **tombstone}
                resp_status = 200

    # Sent AFTER transaction commits successfully
    if resp_payload is not None:
        handler._send_json(resp_payload, status=resp_status)
        return True
    return False


def handle_library_post(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    """Handle POST /api/library/assets/{uid}/restore."""
    m = re.fullmatch(r"^/api/library/assets/([^/]+)/restore$", req_path)
    if not m:
        return False

    user, user_id = _enforce_caller(handler)
    raw_uid = unquote(m.group(1)).strip()
    uid = _normalize_uuid(raw_uid)
    if not uid:
        handler._send_json({"ok": False, "error": "Asset not found"}, status=404)
        return True

    resp_payload: dict[str, Any] | None = None
    resp_status: int = 200

    with handler.db.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM user_uploads WHERE user_id = ? AND asset_uid = ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other')) LIMIT 1",
            (user_id, uid),
        ).fetchone()
        if not row:
            resp_payload = {"ok": False, "error": "Asset not found"}
            resp_status = 404
        elif row["deleted_at"] is None:
            current = format_asset(row)
            resp_payload = {"ok": True, "item": current, **current}
            resp_status = 200
        else:
            # Check 30-day restore window
            deleted_at_str = str(row["deleted_at"])
            try:
                dt = datetime.fromisoformat(deleted_at_str.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - dt).total_seconds() > 30 * 86400:
                    raise ServiceError("资产已超过30天恢复期限", status=410, code="asset_expired")
            except ValueError:
                pass

            # Check if restoring would collide with an existing active asset's sha256 (library categories only)
            dup_active = tx.execute(
                """
                SELECT asset_uid FROM user_uploads
                WHERE user_id = ? AND sha256 = ? AND deleted_at IS NULL AND asset_uid <> ? AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                LIMIT 1
                """,
                (user_id, row["sha256"], uid),
            ).fetchone()
            if dup_active is not None:
                resp_payload = {
                    "ok": False,
                    "error": "同一账号下已存在相同内容的活动资产，无法恢复",
                    "code": "duplicate_image",
                    "existingUid": dup_active["asset_uid"],
                }
                resp_status = 409
            else:
                # Quota checks before restore (item count + 1 <= 500, storage + bytes <= 1 GB)
                check_user_upload_quota(tx, user_id, int(row["bytes"] or 0), is_new_item=True)

                now = utc_now_iso_ms()
                new_seq = next_change_seq(tx)
                new_revision = int(row["revision"]) + 1
                tx.execute(
                    """
                    UPDATE user_uploads
                    SET deleted_at = NULL, revision = ?, change_seq = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (new_revision, new_seq, now, row["id"], user_id),
                )
                restored_row = tx.execute("SELECT * FROM user_uploads WHERE id = ?", (row["id"],)).fetchone()
                res_asset = format_asset(restored_row)
                resp_payload = {"ok": True, "item": res_asset, **res_asset}
                resp_status = 200

    # Sent AFTER transaction commits successfully
    if resp_payload is not None:
        handler._send_json(resp_payload, status=resp_status)
        return True
    return False
