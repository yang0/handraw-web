"""Durable garbage collector for unreferenced private media assets.

GC is decoupled from SQL transactions and safe to retry after crashes.
Never delete a local/object-store file until canonical work and generation
references, personal library records, and legacy content references are gone.
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any

logger = logging.getLogger("handraw.media.gc")


def queue_media_cleanup(tx: Any, url: str, *, delay_seconds: int = 3600) -> None:
    """Enqueue an immutable private-media URL in the *current* DB transaction."""
    from .media_storage import local_path_for_url

    clean = str(url or "").split("?", 1)[0].strip()
    local_path_for_url(clean)  # Reject unrelated paths and path traversal.
    now = int(time.time())
    tx.execute(
        """
        INSERT INTO media_gc_jobs
          (media_url,created_at,next_attempt_at,attempts,claim_until,claim_token)
        VALUES (?,?,?,0,0,'')
        ON CONFLICT(media_url) DO UPDATE SET
          next_attempt_at=CASE
            WHEN media_gc_jobs.claim_until>? THEN media_gc_jobs.next_attempt_at
            ELSE excluded.next_attempt_at END
        """,
        (clean, now, now + max(60, int(delay_seconds)), now),
    )


def _still_referenced(conn: Any, url: str) -> bool:
    from .media_storage import local_path_for_url
    from .user_library import is_media_referenced

    # The canonical V3 tables take precedence; never collect an attached media
    # even if a stale JSON cache or media grant happens to be absent.
    row = conn.execute(
        """
        SELECT 1 FROM media_assets m
        WHERE m.storage_key=? AND (
            EXISTS (SELECT 1 FROM work_media w WHERE w.media_id=m.id)
            OR EXISTS (SELECT 1 FROM generation_items i WHERE i.media_id=m.id)
        ) LIMIT 1
        """,
        (url,),
    ).fetchone()
    if row:
        return True
    return is_media_referenced(conn, url, str(local_path_for_url(url)))


def drain_media_gc(db: Any, *, limit: int = 20) -> dict[str, int]:
    """Claim, recheck, and delete up to N orphaned files with bounded retries.

    A unique lease token prevents two PG workers from processing the same key.
    Object deletion occurs OUTSIDE the transaction, because the object store
    does not participate in SQL rollback. A partially completed deletion can
    simply be retried: S3 DeleteObject and local unlink are idempotent.
    """
    from .media_storage import local_path_for_url
    from .object_storage import delete_private_object

    stats = {"deleted": 0, "referenced": 0, "failed": 0}
    for _ in range(max(0, min(100, int(limit)))):
        now = int(time.time())
        token = secrets.token_hex(16)
        with db.transaction() as tx:
            sql = (
                "SELECT media_url FROM media_gc_jobs "
                "WHERE next_attempt_at<=? AND claim_until<? "
                "ORDER BY next_attempt_at,media_url LIMIT 1"
            )
            if getattr(tx, "dialect", "") == "postgresql":
                sql += " FOR UPDATE SKIP LOCKED"
            row = tx.execute(sql, (now, now)).fetchone()
            if not row:
                break
            url = str(row["media_url"])
            claim = tx.execute(
                """
                UPDATE media_gc_jobs SET claim_token=?, claim_until=?
                WHERE media_url=? AND claim_until<?
                """,
                (token, now + 600, url, now),
            )
            if claim.rowcount != 1:
                continue

        try:
            if _still_referenced(db.get_conn(), url):
                # The file is still used (or a safety check failed); defer
                # rather than deleting it or spinning on the same job.
                with db.transaction() as tx:
                    tx.execute(
                        """
                        UPDATE media_gc_jobs SET claim_token='',claim_until=0,
                          next_attempt_at=?,last_error='still referenced'
                        WHERE media_url=? AND claim_token=?
                        """,
                        (int(time.time()) + 86400, url, token),
                    )
                stats["referenced"] += 1
                continue

            delete_private_object(url)
            local_path_for_url(url).unlink(missing_ok=True)
            with db.transaction() as tx:
                tx.execute(
                    "DELETE FROM media_gc_jobs WHERE media_url=? AND claim_token=?",
                    (url, token),
                )
                # Only unreferenced asset metadata is eligible for reclamation.
                tx.execute(
                    """
                    DELETE FROM media_assets
                    WHERE storage_key=? AND NOT EXISTS (
                        SELECT 1 FROM work_media WHERE work_media.media_id=media_assets.id
                    ) AND NOT EXISTS (
                        SELECT 1 FROM generation_items WHERE generation_items.media_id=media_assets.id
                    )
                    """,
                    (url,),
                )
            stats["deleted"] += 1
        except Exception as error:
            logger.exception("Private media GC failed: %s", url)
            # Leave a job for eventual retry; do not hide a missing object
            # behind a successful task state.
            with db.transaction() as tx:
                current = tx.execute(
                    "SELECT attempts FROM media_gc_jobs WHERE media_url=? AND claim_token=?",
                    (url, token),
                ).fetchone()
                if current:
                    attempts = int(current["attempts"]) + 1
                    backoff = min(86400, 60 * (2 ** min(10, attempts)))
                    tx.execute(
                        """
                        UPDATE media_gc_jobs
                        SET attempts=?,last_error=?,next_attempt_at=?,
                            claim_token='',claim_until=0
                        WHERE media_url=? AND claim_token=?
                        """,
                        (attempts, str(error)[:500], int(time.time()) + backoff, url, token),
                    )
            stats["failed"] += 1
    return stats
