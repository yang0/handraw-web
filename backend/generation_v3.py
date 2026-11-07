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
            expected_count INTEGER NOT NULL CHECK(expected_count >= 1),
            status TEXT NOT NULL DEFAULT 'running'
                CHECK(status IN ('pending','running','partial','success','failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, source, external_run_id)
        );
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
    """),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *segments: object) -> str:
    payload = "\x1f".join(str(part) for part in segments).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:32]}"


def _storage_url(value: str) -> str:
    url = str(value or "").strip().split("?", 1)[0]
    if not url or not (
        url.startswith(("/generated/", "/uploads/"))
        or url.startswith(("https://", "http://", "/images/"))
    ):
        raise ValueError("Invalid generated media URL")
    return url


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
    existing = tx.execute(
        "SELECT id,expected_count,request_id FROM generation_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    if existing:
        if int(existing["expected_count"]) != expected_count:
            raise ValueError("Run size changed during retry")
        if request_id and existing["request_id"] and existing["request_id"] != request_id:
            raise ValueError("Run request key changed during retry")
        return run_id
    now = _now()
    tx.execute(
        """
        INSERT INTO generation_runs
          (id,user_id,source,external_run_id,request_id,expected_count,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,'running',?,?)
        """,
        (run_id, user_id, source, external_run_id, request_id, expected_count, now, now),
    )
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
    tx.execute("DELETE FROM generation_items WHERE run_id=?", (run_id,))
    for rank, (position, media_id, _) in enumerate(entries):
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
