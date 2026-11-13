"""Handraw V3 canonical generation, media and one-work-per-run persistence.

This is a FRESH-SCHEMA model, not a legacy history backfill. The existing
studio_generations table remains a gateway execution / billing ledger during
the service-layer cutover. Public run and media identities live here.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from typing import Any

from .postgres_db import PgConnection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *segments: object) -> str:
    payload = "\x1f".join(str(part) for part in segments).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:32]}"


def _storage_url(value: str) -> str:
    url = str(value or "").strip().split("?", 1)[0]
    # Upstream generation/upload authenticates media ownership. This layer
    # still rejects traversal, protocol-relative URLs and malformed paths.
    if not url or "\x00" in url or ".." in url.split("/"):
        raise ValueError("Invalid generated media URL")
    if url.startswith("/") and not url.startswith("//"):
        return url
    if url.startswith(("https://", "http://")):
        return url
    raise ValueError("Invalid generated media URL")


def ensure_run(
    tx: PgConnection,
    *,
    user_id: int,
    source: str,
    external_run_id: str,
    expected_count: int,
    request_id: str = "",
) -> str:
    """Idempotent logical run ID; retries cannot change run ownership/size."""
    if source not in ("web", "skill", "api"):
        raise ValueError("Unsupported run source")
    external_run_id = str(external_run_id or "").strip()
    if not external_run_id or not 1 <= expected_count <= 1000:
        raise ValueError("Invalid run identity or expected count")
    run_id = _stable_id("run", user_id, source, external_run_id)
    now = _now()
    # Atomic insert-or-read: two PostgreSQL workers may reserve the same
    # logical run concurrently. A separate SELECT-before-INSERT is racy.
    tx.execute(
        """
        INSERT INTO generation_runs
          (id,user_id,source,external_run_id,request_id,expected_count,
           status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,'running',?,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (run_id, user_id, source, external_run_id, request_id,
         expected_count, now, now),
    )
    existing = tx.execute(
        """
        SELECT user_id,source,external_run_id,expected_count,request_id
        FROM generation_runs WHERE id=?
        """,
        (run_id,),
    ).fetchone()
    if not existing or (
        int(existing["user_id"]) != user_id or
        str(existing["source"]) != source or
        str(existing["external_run_id"]) != external_run_id
    ):
        raise ValueError("Run identity collision")
    if int(existing["expected_count"]) != expected_count:
        raise ValueError("Run size changed during retry")
    if request_id and existing["request_id"] and existing["request_id"] != request_id:
        raise ValueError("Run request key changed during retry")
    return run_id


def _local_media_metadata(url: str) -> tuple[str, int | None, int | None, int | None]:
    """Best-effort byte identity and dimensions for a verified private file.

    This never downloads unauthenticated remote URLs or reads arbitrary paths.
    Content validation and object upload already happened in the caller.
    """
    from .config import get_generated_dir, get_uploads_dir

    roots = (("/generated/", get_generated_dir()), ("/uploads/", get_uploads_dir()))
    for prefix, root in roots:
        if not url.startswith(prefix):
            continue
        root = root.resolve()
        candidate = (root / url[len(prefix):]).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return "", None, None, None
        size = candidate.stat().st_size
        if size < 1 or size > 32 * 1024 * 1024:
            raise ValueError("Generated media has an invalid stored size")
        with candidate.open("rb") as file:
            checksum = hashlib.file_digest(file, "sha256").hexdigest()
        width = height = None
        try:
            from PIL import Image
            with Image.open(candidate) as img:
                width, height = int(img.width), int(img.height)
        except (OSError, ValueError):
            pass
        return checksum, width, height, size
    return "", None, None, None


def _upsert_media(
    tx: PgConnection,
    *,
    owner_id: int,
    url: str,
    sha256: str = "",
) -> str:
    url = _storage_url(url)
    digest = str(sha256 or "").strip().lower()
    if digest and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("Invalid media sha256")
    media_id = _stable_id("media", owner_id, url)
    exists = tx.execute(
        "SELECT sha256 FROM media_assets WHERE id=?", (media_id,),
    ).fetchone()
    local_digest, width, height, file_bytes = _local_media_metadata(url)
    if local_digest and digest and local_digest != digest:
        raise ValueError("Media checksum does not match the uploaded content")
    digest = local_digest or digest
    if exists and digest and exists["sha256"] and exists["sha256"] != digest:
        raise ValueError("Media storage key changed content")
    if not exists:
        tx.execute(
            """
            INSERT INTO media_assets
              (id,owner_user_id,storage_key,sha256,mime_type,width,height,size_bytes,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (media_id, owner_id, url, digest,
             mimetypes.guess_type(url)[0] or "application/octet-stream",
             width, height, file_bytes, _now()),
        )
    else:
        tx.execute(
            """
            UPDATE media_assets
            SET sha256=CASE WHEN sha256='' THEN ? ELSE sha256 END,
                width=COALESCE(width,?),
                height=COALESCE(height,?),
                size_bytes=COALESCE(size_bytes,?)
            WHERE id=?
            """,
            (digest, width, height, file_bytes, media_id),
        )
    return media_id


def reserve_skill_run(
    tx: PgConnection,
    *,
    user_id: int,
    external_run_id: str,
    request_id: str,
    request_hash: str,
    original_request: str,
    expected_count: int,
) -> str:
    """Same run for a retry, without silently accepting edited content."""
    run_id = ensure_run(
        tx, user_id=user_id, source="skill", external_run_id=external_run_id,
        expected_count=expected_count, request_id=request_id,
    )
    tx.execute(
        "SELECT id FROM generation_runs WHERE id=? FOR UPDATE", (run_id,),
    ).fetchone()
    row = tx.execute(
        "SELECT request_hash,original_request FROM generation_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    if row["request_hash"] and (
        row["request_hash"] != request_hash or
        row["original_request"] != original_request
    ):
        raise ValueError("Skill upload retry conflicts with the original request")
    tx.execute(
        """
        UPDATE generation_runs
        SET request_hash=?,original_request=?,status=CASE
              WHEN status='success' THEN 'success' ELSE 'uploading' END,
            updated_at=?
        WHERE id=?
        """,
        (request_hash, original_request, _now(), run_id),
    )
    return run_id


def record_skill_uploaded_item(
    tx: PgConnection,
    *,
    run_id: str,
    user_id: int,
    position: int,
    url: str,
    sha256: str,
) -> None:
    if position < 0:
        raise ValueError("Invalid upload position")
    row = tx.execute(
        "SELECT user_id,source,expected_count FROM generation_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    if not row or row["source"] != "skill" or int(row["user_id"]) != user_id:
        raise ValueError("Skill run ownership mismatch")
    if position >= int(row["expected_count"]):
        raise ValueError("Upload position outside declared run")
    media_id = _upsert_media(tx, owner_id=user_id, url=url, sha256=sha256)
    existing = tx.execute(
        "SELECT media_id FROM generation_items WHERE run_id=? AND position=?",
        (run_id, position),
    ).fetchone()
    if existing and existing["media_id"] != media_id:
        raise ValueError("Upload position changed during retry")
    now = _now()
    if not existing:
        tx.execute(
            """
            INSERT INTO generation_items
              (id,run_id,position,status,media_id,created_at,updated_at)
            VALUES (?,?,?,'success',?,?,?)
            """,
            (_stable_id("item", run_id, position), run_id, position, media_id, now, now),
        )
    tx.execute(
        "UPDATE generation_runs SET updated_at=? WHERE id=?", (now, run_id),
    )


def uploaded_skill_images(tx: PgConnection, run_id: str) -> list[dict[str, Any]]:
    """Get only *contiguous* uploaded positions, so retries resume correctly."""
    rows = tx.execute(
        """
        SELECT i.position,m.storage_key,m.sha256
        FROM generation_items i JOIN media_assets m ON m.id=i.media_id
        WHERE i.run_id=? AND i.status='success'
        ORDER BY i.position ASC
        """,
        (run_id,),
    ).fetchall()
    saved: list[dict[str, Any]] = []
    for row in rows:
        if int(row["position"]) != len(saved):
            raise ValueError("Skill uploaded image positions are not contiguous")
        saved.append({"url": row["storage_key"], "sha256": row["sha256"]})
    return saved


def refresh_run_status(tx: PgConnection, run_id: str) -> str:
    """Derive the single logical-run state from authoritative output slots.

    No gateway execution row or client-provided status can override a finished
    item. A batch remains running until all declared output slots are terminal.
    Failed and cancelled slots remain visible to the owner's history.
    """
    run = tx.execute(
        "SELECT id,source,status,expected_count FROM generation_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    if not run:
        raise ValueError("Generation run does not exist")
    rows = tx.execute(
        "SELECT position,ordinal,status FROM generation_items WHERE run_id=? AND retired_at IS NULL",
        (run_id,),
    ).fetchall()
    positions: dict[int, set[str]] = {}
    for row in rows:
        position = int(row["position"])
        slot = int(row["ordinal"]) if row["ordinal"] is not None else position // 1000 if run["source"] == "web" else position
        positions.setdefault(slot, set()).add(str(row["status"]))
    terminal = {"success", "failed", "cancelled"}
    if len(positions) < int(run["expected_count"]) or any(
        not states <= terminal for states in positions.values()
    ):
        # Skill media uploads must not be treated as a published task until
        # the work commit succeeds, even if some files have been uploaded.
        status = "uploading" if run["source"] == "skill" and run["status"] == "uploading" else "running"
    elif all("success" in states for states in positions.values()):
        status = "success"
    elif any("success" in states for states in positions.values()):
        status = "partial"
    elif all(states == {"cancelled"} for states in positions.values()):
        status = "cancelled"
    else:
        status = "failed"
    tx.execute(
        "UPDATE generation_runs SET status=?, updated_at=? WHERE id=?",
        (status, _now(), run_id),
    )
    return status


def record_public_work(
    tx: PgConnection,
    *,
    user_id: int,
    source: str,
    external_run_id: str,
    work_id: str,
    ordered_images: list[tuple[int, str, str]],
    expected_count: int,
    request_id: str = "",
) -> str:
    """Atomically make a run, its output media and its ONE public work agree.

    Caller must already have stored/authorized all media, and must execute this
    within its transaction. No file IO or external network calls happen here.
    The snapshot is replaced, so deleted/retried slots cannot leave stale media.
    """
    if not ordered_images:
        raise ValueError("Cannot publish an empty work")
    run_id = ensure_run(
        tx, user_id=user_id, source=source, external_run_id=external_run_id,
        expected_count=expected_count, request_id=request_id,
    )
    if tx.execute(
        "SELECT 1 FROM generation_runs WHERE id=? AND publication_deleted_at<>''",
        (run_id,),
    ).fetchone():
        raise ValueError("Deleted generation work cannot be republished")
    work = tx.execute(
        """SELECT id,run_id,author_username,cover_media_id,
                  cover_selected_by_author FROM works WHERE id=?""",
        (work_id,),
    ).fetchone()
    if not work:
        raise ValueError("Work must exist before media linkage")
    owner = tx.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if not owner or work["author_username"].lower() != str(owner["username"]).lower():
        raise ValueError("Cross-owner work linkage forbidden")
    if work["run_id"] and work["run_id"] != run_id:
        raise ValueError("Work already belongs to another generation run")
    linked = tx.execute("SELECT id FROM works WHERE run_id=?", (run_id,)).fetchone()
    if linked and linked["id"] != work_id:
        raise ValueError("A generation run already has a different work")

    ordered = sorted(ordered_images, key=lambda image: image[0])
    seen_positions: set[int] = set()
    seen_urls: set[str] = set()
    entries: list[tuple[int, str, str]] = []
    for position, url, digest in ordered:
        if not isinstance(position, int) or position < 0 or position in seen_positions:
            raise ValueError("Duplicate or invalid generation slot")
        key = _storage_url(url)
        if key in seen_urls:
            continue
        seen_positions.add(position)
        seen_urls.add(key)
        media_id = _upsert_media(tx, owner_id=user_id, url=key, sha256=digest)
        entries.append((position, media_id, key))
    if not entries:
        raise ValueError("No valid generated media")

    now = _now()
    previous_media_urls = work_images(tx, work_id) if work["run_id"] else []
    explicit_tasks = tx.execute(
        "SELECT 1 FROM studio_generations WHERE run_id=? AND item_id IS NOT NULL LIMIT 1", (run_id,),
    ).fetchone()
    # Unlink cover before replacing the ordered collection; DB triggers enforce
    # that a new cover belongs to this work.
    tx.execute("UPDATE works SET run_id=?, cover_media_id=NULL WHERE id=?", (run_id, work_id))
    tx.execute("DELETE FROM work_media WHERE work_id=?", (work_id,))
    # A task is a stable execution identity, not a replaceable publication
    # snapshot. Preserve its references, configuration and creation timestamp.
    # Successful outputs omitted from the new gallery become inactive in place.
    if not explicit_tasks:
        tx.execute(
            """UPDATE generation_items SET status='cancelled',media_id=NULL,
                      error_code='',updated_at=?
               WHERE run_id=? AND status='success' AND NOT(position=ANY(?))""",
            (now, run_id, [entry[0] for entry in entries]),
        )
    for rank, (position, media_id, _) in enumerate(entries):
        if not explicit_tasks:
            tx.execute(
                """
                INSERT INTO generation_items
                  (id,run_id,position,status,media_id,created_at,updated_at)
                VALUES (?,?,?,'success',?,?,?)
                ON CONFLICT(run_id,position) DO UPDATE SET status='success',
                    media_id=excluded.media_id,error_code='',updated_at=excluded.updated_at
                """,
                (_stable_id("item", run_id, position), run_id, position, media_id, now, now),
            )
        tx.execute(
            "INSERT INTO work_media(work_id,media_id,position) VALUES (?,?,?)",
            (work_id, media_id, rank),
        )
    previous_cover = str(work["cover_media_id"] or "")
    valid_media_ids = {entry[1] for entry in entries}
    # The default cover follows the first successful *planned* slot even if
    # responses arrive out of order. Only an explicit author choice is sticky.
    keep_author_cover = bool(work["cover_selected_by_author"]) and (
        previous_cover in valid_media_ids
    )
    cover_id = previous_cover if keep_author_cover else entries[0][1]
    tx.execute(
        """UPDATE works SET cover_media_id=?,cover_selected_by_author=?,
                  images_json=?,updated_at=? WHERE id=?""",
        (cover_id, int(keep_author_cover),
         json.dumps([e[2] for e in entries], ensure_ascii=False),
         now, work_id),
    )
    refresh_run_status(tx, run_id)
    # Replaced media must immediately lose this work's public grant. Physical
    # deletion happens only after a delayed, durable DB-reference check.
    removed_urls = set(previous_media_urls) - {entry[2] for entry in entries}
    for removed in removed_urls:
        tx.execute(
            """UPDATE media_public_grants SET revoked_at=?
               WHERE media_url=? AND revoked_at IS NULL AND (
                 (target_type='work' AND target_id=?) OR
                 (target_type='topic' AND target_id IN (
                    SELECT id FROM forum_topics WHERE work_id=?
                 ))
               )""",
            (now, removed, work_id, work_id),
        )
        if removed.startswith(("/generated/", "/uploads/")):
            from .media_gc import queue_media_cleanup
            queue_media_cleanup(tx, removed)
    return run_id


def work_images(tx: PgConnection, work_id: str) -> list[str]:
    """Always read the normalized media collection in visual order."""
    return [
        str(row["storage_key"]) for row in tx.execute(
            """
            SELECT m.storage_key
            FROM work_media wm JOIN media_assets m ON m.id=wm.media_id
            WHERE wm.work_id=?
            ORDER BY wm.position ASC
            """,
            (work_id,),
        )
    ]


def set_work_cover(db: Any, user: dict[str, Any], work_id: str, image_url: str) -> dict[str, Any]:
    """Author-only cover selection without changing a work's image order or ID.

    The cover must already be one of the completed media items of the work.
    Non-generated community submissions keep their own cover editing workflow.
    """
    from .services import ServiceError
    work_id = str(work_id or "").strip()
    try:
        url = _storage_url(image_url)
    except ValueError as error:
        raise ServiceError("封面图片地址无效", status=400, code="invalid_cover") from error
    if not work_id:
        raise ServiceError("作品编号不能为空", status=400, code="work_required")
    with db.transaction() as tx:
        work = tx.execute(
            "SELECT id,run_id,author_username,status FROM works WHERE id=?",
            (work_id,),
        ).fetchone()
        if not work or work["status"] == "deleted":
            raise ServiceError("作品不存在", status=404, code="work_not_found")
        if not work["run_id"]:
            raise ServiceError("该作品不支持修改生成封面", status=400, code="cover_not_generated")
        if not user or str(work["author_username"]).casefold() != str(user.get("username", "")).casefold():
            raise ServiceError("只有作品作者可以更换封面", status=403, code="cover_forbidden")
        media = tx.execute(
            """
            SELECT wm.media_id FROM work_media wm
            JOIN media_assets m ON m.id=wm.media_id
            JOIN generation_runs r ON r.id=?
            WHERE wm.work_id=? AND m.storage_key=? AND m.owner_user_id=r.user_id
            """,
            (work["run_id"], work_id, url),
        ).fetchone()
        if not media:
            raise ServiceError("只能选择本作品中已成功生成的图片作为封面", status=400, code="cover_not_in_work")
        tx.execute(
            """UPDATE works SET cover_media_id=?,cover_selected_by_author=1,
                      updated_at=? WHERE id=?""",
            (media["media_id"], _now(), work_id),
        )
    # The home scene API caches cards for 120 seconds; author edits must be
    # visible immediately rather than showing the previously chosen cover.
    from .home_scenarios import invalidate_scenarios_cache
    invalidate_scenarios_cache()
    return {"ok": True, "workId": work_id, "coverUrl": url, "coverMediaId": media["media_id"]}


def cancel_unsubmitted_web_slots(
    db: Any, user: dict[str, Any], batch_id: str, positions: list[Any],
) -> dict[str, Any]:
    """Cancel ONLY slots that have not reached the model gateway.

    Never claim to cancel a remote task or refund it. In-flight submissions
    are explicitly reported as skipped. Billing of an accepted task remains
    governed by authoritative gateway success/failure reconciliation.
    """
    import re
    from .services import ServiceError

    uid = int(user["id"])
    batch_id = str(batch_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", batch_id):
        raise ServiceError("批次 ID 无效", status=400, code="invalid_batch_id")
    if not isinstance(positions, list) or len(positions) > 200:
        raise ServiceError("取消图片索引无效", status=400, code="invalid_cancel_positions")
    if any(type(p) is not int or p < 0 for p in positions):
        raise ServiceError("取消图片索引必须为非负整数", status=400, code="invalid_cancel_positions")
    with db.transaction() as tx:
        from .studio_execution import lock_generation_actor
        lock_generation_actor(tx,uid)
        query = (
            "SELECT id,expected_count,creation_mode FROM generation_runs "
            "WHERE user_id=? AND source='web' AND external_run_id=?"
        )
        query += " FOR UPDATE"
        run = tx.execute(query, (uid, batch_id)).fetchone()
        if not run:
            raise ServiceError("找不到属于你的生成批次", status=404, code="run_not_found")
        if any(p >= int(run["expected_count"]) for p in positions):
            raise ServiceError("取消索引超出任务范围", status=400, code="invalid_cancel_positions")

        cancelled: list[int] = []
        skipped: list[int] = []
        now = _now()
        for pos in sorted(set(positions)):
            # Queued/running/success tasks have been submitted; the client
            # cannot honestly cancel them by closing a dialog.
            gateway = tx.execute(
                """
                SELECT 1 FROM studio_generations
                WHERE user_id=? AND batch_id=? AND batch_index=?
                  AND status IN ('queued','running','success')
                LIMIT 1
                """,
                (uid, batch_id, pos),
            ).fetchone()
            existing = tx.execute(
                "SELECT position,status FROM generation_items WHERE run_id=? AND (ordinal=? OR (ordinal IS NULL AND position=?))",
                (run["id"], pos,pos*1000),
            ).fetchone()
            if gateway or (existing and existing["status"] == "success"):
                skipped.append(pos)
                continue
            position=int(existing["position"]) if existing else pos*1000 if run["creation_mode"]=="other" else pos
            tx.execute(
                """
                INSERT INTO generation_items
                    (id,run_id,position,ordinal,status,media_id,error_code,created_at,updated_at)
                VALUES (?, ?, ?, ?, 'cancelled', NULL, '', ?, ?)
                ON CONFLICT(run_id,position) DO UPDATE SET
                    ordinal=COALESCE(generation_items.ordinal,excluded.ordinal),
                    status='cancelled',media_id=NULL,error_code='',updated_at=excluded.updated_at
                WHERE generation_items.status <> 'success'
                """,
                (_stable_id("item", run["id"], position),
                 run["id"], position,None if run["creation_mode"]=="other" else pos, now, now),
            )
            from .economy import release_item
            item=tx.execute("SELECT id FROM generation_items WHERE run_id=? AND position=?",(run["id"],position)).fetchone()
            if item:
                release_item(tx,item[0])
            for charge in tx.execute("SELECT c.* FROM generation_charges c JOIN generation_quotes q ON q.id=c.quote_id WHERE q.user_id=? AND q.batch_key=? AND c.slot_position=? AND c.generation_id IS NULL AND c.status='reserved' FOR UPDATE OF c",(uid,batch_id,pos)).fetchall():
                from .economy import finish_reservation
                finish_reservation(tx,charge)
            cancelled.append(pos)

        refresh_run_status(tx, str(run["id"]))

    return {
        "ok": True, "runId": run["id"], "batchId": batch_id,
        "cancelledPositions": cancelled,
        "alreadySubmittedPositions": skipped,
        "remoteTasksCancelled": False,
    }
