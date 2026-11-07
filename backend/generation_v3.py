"""Handraw V3 canonical generation, media and one-work-per-run persistence.

This is a FRESH-SCHEMA model, not a legacy history backfill. The existing
studio_generations table remains a gateway execution / billing ledger during
the service-layer cutover. Public run and media identities live here.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
from datetime import datetime, timezone
from typing import Any


V3_MIGRATIONS = [
    (99, "099_canonical_generation_media_v3", """
        CREATE TABLE IF NOT EXISTS generation_runs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            source TEXT NOT NULL CHECK(source IN ('web','skill','api')),
            external_run_id TEXT NOT NULL,
            request_id TEXT NOT NULL DEFAULT '',
            request_hash TEXT NOT NULL DEFAULT '',
            original_request TEXT NOT NULL DEFAULT '',
            expected_count INTEGER NOT NULL CHECK(expected_count >= 1),
            status TEXT NOT NULL DEFAULT 'running'
                CHECK(status IN ('pending','uploading','running','partial','success','failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, source, external_run_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_generation_runs_request
            ON generation_runs(user_id,source,request_id)
            WHERE request_id <> '';
        CREATE INDEX IF NOT EXISTS idx_generation_runs_owner_recent
            ON generation_runs(user_id,created_at DESC,id DESC);

        CREATE TABLE IF NOT EXISTS media_assets (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES users(id),
            storage_key TEXT NOT NULL,
            sha256 TEXT NOT NULL DEFAULT '',
            mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            width INTEGER CHECK(width IS NULL OR width > 0),
            height INTEGER CHECK(height IS NULL OR height > 0),
            size_bytes INTEGER CHECK(size_bytes IS NULL OR size_bytes >= 0),
            created_at TEXT NOT NULL,
            UNIQUE(owner_user_id,storage_key)
        );
        CREATE INDEX IF NOT EXISTS idx_media_assets_sha
            ON media_assets(owner_user_id,sha256) WHERE sha256 <> '';

        CREATE TABLE IF NOT EXISTS generation_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK(position >= 0),
            status TEXT NOT NULL
                CHECK(status IN ('pending','generating','success','failed','cancelled')),
            media_id TEXT REFERENCES media_assets(id),
            error_code TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id,position),
            CHECK(status <> 'success' OR media_id IS NOT NULL)
        );
        CREATE INDEX IF NOT EXISTS idx_generation_items_run_status
            ON generation_items(run_id,status,position);

        CREATE TABLE IF NOT EXISTS work_media (
            work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
            media_id TEXT NOT NULL REFERENCES media_assets(id),
            position INTEGER NOT NULL CHECK(position >= 0),
            PRIMARY KEY(work_id,media_id),
            UNIQUE(work_id,position)
        );

        ALTER TABLE works ADD COLUMN run_id TEXT;
        ALTER TABLE works ADD COLUMN cover_media_id TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_works_run_id
            ON works(run_id) WHERE run_id IS NOT NULL;

        -- SQLite cannot add a REFERENCES constraint to an existing table
        -- with ALTER COLUMN. Enforce the same relation at the DB boundary.
        CREATE TRIGGER IF NOT EXISTS trg_works_run_owner_insert
        BEFORE INSERT ON works
        WHEN NEW.run_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM generation_runs r
                JOIN users u ON u.id=r.user_id
                WHERE r.id=NEW.run_id AND u.username=NEW.author_username
            ) THEN RAISE(ABORT,'work_run_owner_mismatch') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_works_run_owner_update
        BEFORE UPDATE OF run_id,author_username ON works
        WHEN NEW.run_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM generation_runs r
                JOIN users u ON u.id=r.user_id
                WHERE r.id=NEW.run_id AND u.username=NEW.author_username
            ) THEN RAISE(ABORT,'work_run_owner_mismatch') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_work_media_owner_guard
        BEFORE INSERT ON work_media
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM works w
                JOIN users u ON u.username=w.author_username
                JOIN media_assets m ON m.id=NEW.media_id
                WHERE w.id=NEW.work_id AND m.owner_user_id=u.id
            ) THEN RAISE(ABORT,'work_media_owner_mismatch') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_works_cover_insert
        BEFORE INSERT ON works
        WHEN NEW.cover_media_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT,'cover_must_be_linked_media');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_works_cover_update
        BEFORE UPDATE OF cover_media_id ON works
        WHEN NEW.cover_media_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM work_media
                WHERE work_id=NEW.id AND media_id=NEW.cover_media_id
            ) THEN RAISE(ABORT,'cover_must_be_linked_media') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_work_media_delete_cover_guard
        BEFORE DELETE ON work_media
        WHEN (SELECT cover_media_id FROM works WHERE id=OLD.work_id)=OLD.media_id
        BEGIN
            SELECT RAISE(ABORT,'cannot_remove_cover_media');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_works_images_cache_guard
        BEFORE UPDATE OF images_json ON works
        WHEN NEW.run_id IS NOT NULL AND json(NEW.images_json) <> (
            SELECT COALESCE(json_group_array(storage_key),'[]') FROM (
                SELECT m.storage_key
                FROM work_media wm JOIN media_assets m ON m.id=wm.media_id
                WHERE wm.work_id=NEW.id ORDER BY wm.position ASC
            )
        )
        BEGIN
            SELECT RAISE(ABORT,'generated_work_media_cache_mismatch');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_work_media_owner_update
        BEFORE UPDATE OF media_id,work_id ON work_media
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM works w
                JOIN users u ON u.username=w.author_username
                JOIN media_assets m ON m.id=NEW.media_id
                WHERE w.id=NEW.work_id AND m.owner_user_id=u.id
            ) THEN RAISE(ABORT,'work_media_owner_mismatch') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_generation_item_owner_insert
        BEFORE INSERT ON generation_items
        WHEN NEW.media_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM generation_runs r
                JOIN media_assets m ON m.id=NEW.media_id
                WHERE r.id=NEW.run_id AND r.user_id=m.owner_user_id
            ) THEN RAISE(ABORT,'generation_item_owner_mismatch') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_generation_item_owner_update
        BEFORE UPDATE OF media_id,run_id ON generation_items
        WHEN NEW.media_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM generation_runs r
                JOIN media_assets m ON m.id=NEW.media_id
                WHERE r.id=NEW.run_id AND r.user_id=m.owner_user_id
            ) THEN RAISE(ABORT,'generation_item_owner_mismatch') END;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_generation_run_identity_immutable
        BEFORE UPDATE OF user_id,source,external_run_id ON generation_runs
        WHEN NEW.user_id<>OLD.user_id OR NEW.source<>OLD.source
             OR NEW.external_run_id<>OLD.external_run_id
        BEGIN
            SELECT RAISE(ABORT,'run_identity_is_immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_media_asset_identity_immutable
        BEFORE UPDATE OF owner_user_id,storage_key ON media_assets
        WHEN NEW.owner_user_id<>OLD.owner_user_id
             OR NEW.storage_key<>OLD.storage_key
        BEGIN
            SELECT RAISE(ABORT,'media_identity_is_immutable');
        END;
    """),
]


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
    tx: sqlite3.Connection,
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


def _upsert_media(
    tx: sqlite3.Connection,
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
    exists = tx.execute("SELECT sha256 FROM media_assets WHERE id=?", (media_id,)).fetchone()
    if exists and digest and exists["sha256"] and exists["sha256"] != digest:
        raise ValueError("Media storage key changed content")
    if not exists:
        tx.execute(
            """
            INSERT INTO media_assets
              (id,owner_user_id,storage_key,sha256,mime_type,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (media_id, owner_id, url, digest,
             mimetypes.guess_type(url)[0] or "application/octet-stream", _now()),
        )
    elif digest and not exists["sha256"]:
        tx.execute("UPDATE media_assets SET sha256=? WHERE id=?", (digest, media_id))
    return media_id


def reserve_skill_run(
    tx: sqlite3.Connection,
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
    if getattr(tx, "dialect", "") == "postgresql":
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
    tx: sqlite3.Connection,
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


def uploaded_skill_images(tx: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
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


def record_public_work(
    tx: sqlite3.Connection,
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
    work = tx.execute(
        "SELECT id,run_id,author_username FROM works WHERE id=?", (work_id,),
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
    # Unlink cover before replacing the ordered collection; DB triggers enforce
    # that a new cover belongs to this work.
    tx.execute("UPDATE works SET run_id=?, cover_media_id=NULL WHERE id=?", (run_id, work_id))
    tx.execute("DELETE FROM work_media WHERE work_id=?", (work_id,))
    # Replace successful snapshots, but do not erase failed/pending slots that
    # belong to the same logical batch. A retried successful position overrides
    # that position's earlier failure, while other failures remain auditable.
    tx.execute(
        "DELETE FROM generation_items WHERE run_id=? AND status='success'",
        (run_id,),
    )
    for rank, (position, media_id, _) in enumerate(entries):
        tx.execute(
            "DELETE FROM generation_items WHERE run_id=? AND position=?",
            (run_id, position),
        )
        tx.execute(
            """
            INSERT INTO generation_items
              (id,run_id,position,status,media_id,created_at,updated_at)
            VALUES (?,?,?,'success',?,?,?)
            """,
            (_stable_id("item", run_id, position), run_id, position, media_id, now, now),
        )
        tx.execute(
            "INSERT INTO work_media(work_id,media_id,position) VALUES (?,?,?)",
            (work_id, media_id, rank),
        )
    tx.execute(
        "UPDATE works SET cover_media_id=?,images_json=?,updated_at=? WHERE id=?",
        (entries[0][1], json.dumps([e[2] for e in entries], ensure_ascii=False),
         now, work_id),
    )
    run_status = "success" if len(entries) >= expected_count else "partial"
    tx.execute(
        "UPDATE generation_runs SET status=?,updated_at=? WHERE id=?",
        (run_status, now, run_id),
    )
    return run_id


def work_images(tx: sqlite3.Connection, work_id: str) -> list[str]:
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
