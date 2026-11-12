"""Native PostgreSQL fixtures for historical data maintenance regressions."""
from __future__ import annotations
import json
import uuid
import logging
logger = logging.getLogger(__name__)
from typing import Any
from backend.postgres_db import PgConnection


def deduplicate_generation_history(conn: PgConnection, user_id: int | None = None) -> int:
    """Clean duplicate studio_generations records idempotently.

    1. Match by (user_id, request_id): when multiple active rows share the same user and non-empty request_id,
       keep the server record (preferring gen_ prefix or live engine), and soft-delete duplicate hist_ rows.
    2. Match by (user_id, complete image set): for rows of the same user with identical complete image sets,
       match hist_/gen_ pairs, keep the server/gen_ record, and soft-delete the duplicate hist_ record.
    3. Backfill subject / recipe_summary onto the kept record if missing.
    4. Never touches wallets, transactions, or accounting ledgers.
    """
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    count_deleted = 0

    in_tx = getattr(conn, "in_transaction", False)
    if not in_tx:
        conn.execute("BEGIN;")

    try:
        user_clause = "AND user_id = ?" if user_id is not None else ""
        user_args: tuple[Any, ...] = (user_id,) if user_id is not None else ()

        # 1. Deduplicate by (user_id, request_id)
        dup_reqs = conn.execute(
            f"""
            SELECT user_id, request_id, COUNT(*) as cnt
            FROM studio_generations
            WHERE COALESCE(deleted_at, '') = ''
              AND request_id IS NOT NULL AND request_id != ''
              {user_clause}
            GROUP BY user_id, request_id
            HAVING COUNT(*) > 1
            """,
            user_args,
        ).fetchall()

        for d_row in dup_reqs:
            u_id = d_row["user_id"]
            r_id = d_row["request_id"]
            group_rows = conn.execute(
                """
                SELECT * FROM studio_generations
                WHERE user_id = ? AND request_id = ? AND COALESCE(deleted_at, '') = ''
                ORDER BY
                  CASE WHEN id NOT LIKE 'hist_%' AND engine != 'sample' THEN 0
                       WHEN id NOT LIKE 'hist_%' THEN 1
                       WHEN engine != 'sample' THEN 2
                       ELSE 3 END,
                  created_at ASC,
                  id ASC
                """,
                (u_id, r_id),
            ).fetchall()
            if len(group_rows) <= 1:
                continue
            primary = group_rows[0]
            updates = []
            update_vals = []
            for dup in group_rows[1:]:
                if "subject = ?" not in updates and not primary["subject"] and dup["subject"]:
                    updates.append("subject = ?")
                    update_vals.append(dup["subject"])
                if "recipe_summary = ?" not in updates and not primary["recipe_summary"] and dup["recipe_summary"]:
                    updates.append("recipe_summary = ?")
                    update_vals.append(dup["recipe_summary"])
                conn.execute(
                    "UPDATE studio_generations SET deleted_at = ?, request_id = '' WHERE id = ? AND COALESCE(deleted_at, '') = ''",
                    (now_iso, dup["id"]),
                )
                count_deleted += 1
            if updates:
                update_vals.append(primary["id"])
                conn.execute(
                    f"UPDATE studio_generations SET {', '.join(updates)} WHERE id = ?",
                    tuple(update_vals),
                )

        # 2. Deduplicate by identical complete image set for same user
        cand_rows = conn.execute(
            f"""
            SELECT id, user_id, engine, subject, recipe_summary, items_json, created_at, request_id
            FROM studio_generations
            WHERE COALESCE(deleted_at, '') = ''
              AND status = 'success'
              AND items_json IS NOT NULL AND items_json != '' AND items_json != '[]'
              {user_clause}
            ORDER BY user_id, created_at ASC, id ASC
            """,
            user_args,
        ).fetchall()

        def _extract_urls(items_json_str: str) -> tuple[str, ...]:
            try:
                items = json.loads(items_json_str or "[]")
            except Exception:
                return ()
            urls: list[str] = []
            for it in (items if isinstance(items, list) else []):
                if isinstance(it, str) and it.strip():
                    urls.append(it.strip())
                elif isinstance(it, dict) and it.get("imageUrl"):
                    urls.append(str(it["imageUrl"]).strip())
            return tuple(sorted(urls))

        user_image_map: dict[tuple[int, tuple[str, ...]], list[Any]] = {}
        for r in cand_rows:
            urls = _extract_urls(r["items_json"])
            if not urls:
                continue
            key = (int(r["user_id"]), urls)
            user_image_map.setdefault(key, []).append(r)

        for (u_id, urls), rows_with_same_images in user_image_map.items():
            if len(rows_with_same_images) <= 1:
                continue

            server_rows = [r for r in rows_with_same_images if not str(r["id"]).startswith("hist_") and str(r["engine"]) != "sample"]
            client_rows = [r for r in rows_with_same_images if str(r["id"]).startswith("hist_") or str(r["engine"]) == "sample"]

            if server_rows and client_rows:
                primary = server_rows[0]
                updates = []
                update_vals = []
                for client_row in client_rows:
                    # Never merge distinct requests with different non-empty request IDs
                    client_req = str(client_row["request_id"] or "").strip()
                    primary_req = str(primary["request_id"] or "").strip()
                    if client_req and primary_req and client_req != primary_req:
                        continue

                    if "subject = ?" not in updates and not primary["subject"] and client_row["subject"]:
                        updates.append("subject = ?")
                        update_vals.append(client_row["subject"])
                    if "recipe_summary = ?" not in updates and not primary["recipe_summary"] and client_row["recipe_summary"]:
                        updates.append("recipe_summary = ?")
                        update_vals.append(client_row["recipe_summary"])
                    conn.execute(
                        "UPDATE studio_generations SET deleted_at = ? WHERE id = ? AND COALESCE(deleted_at, '') = ''",
                        (now_iso, client_row["id"]),
                    )
                    count_deleted += 1
                if updates:
                    update_vals.append(primary["id"])
                    conn.execute(
                        f"UPDATE studio_generations SET {', '.join(updates)} WHERE id = ?",
                        tuple(update_vals),
                    )

        if not in_tx:
            conn.execute("COMMIT;")
    except Exception:
        if not in_tx and getattr(conn, "in_transaction", False):
            conn.execute("ROLLBACK;")
        raise

    return count_deleted


STATUS_ACTOR_BACKFILL_SQL = """
UPDATE forum_topics SET status_source = 'work'
WHERE status <> 'published' AND status <> 'deleted'
  AND EXISTS (
    SELECT 1 FROM curation_resource_topics m JOIN works w ON w.id = m.target_id
    WHERE m.kind = 'work' AND m.topic_id = forum_topics.id
      AND w.status = forum_topics.status
      AND w.status_source = forum_topics.status_source
      AND w.status_reason = forum_topics.status_reason
  );

UPDATE works SET status_source = 'report'
WHERE status = 'paused' AND status_source = ''
  AND EXISTS (
    SELECT 1 FROM audit_logs a WHERE a.target_type = 'work' AND a.target_id = works.id
      AND a.action = 'moderation.auto_pause')
  AND NOT EXISTS (
    SELECT 1 FROM audit_logs a WHERE a.target_type = 'work' AND a.target_id = works.id
      AND a.action IN ('work.pause', 'work.hide', 'report.confirmed'));

UPDATE forum_topics SET status_source = 'report'
WHERE status = 'paused' AND status_source = ''
  AND EXISTS (
    SELECT 1 FROM audit_logs a WHERE a.target_type = 'topic' AND a.target_id = forum_topics.id
      AND a.action = 'moderation.auto_pause')
  AND NOT EXISTS (
    SELECT 1 FROM audit_logs a WHERE a.target_type = 'topic' AND a.target_id = forum_topics.id
      AND a.action IN ('topic.hide', 'forum.mod.hide', 'report.confirmed'));
"""


def normalize_historical_asset_uids(conn: PgConnection) -> None:
    """Normalize user_uploads asset_uid values to canonical lowercase 8-4-4-4-12 UUID format.

    Handles uppercase, curly braces, URN prefixes ('urn:uuid:...'), and 32-hex unhyphenated UUIDs.
    Preserves non-UUID custom identifiers without error or rollback.
    Resolves collisions within the same user by keeping the earliest row (lowest id)
    and setting conflicting rows' asset_uid to NULL.
    Idempotent across repeated executions.
    """
    rows = conn.execute(
        """
        SELECT id, user_id, asset_uid
        FROM user_uploads
        WHERE asset_uid IS NOT NULL AND asset_uid <> '' AND asset_uid NOT LIKE 'UPL-%'
        ORDER BY user_id ASC, id ASC
        """
    ).fetchall()

    if not rows:
        return

    in_tx = getattr(conn, "in_transaction", False)
    if not in_tx:
        conn.execute("BEGIN;")

    try:
        user_seen_uids: dict[int, set[str]] = {}

        for r in rows:
            row_id = r["id"]
            user_id = int(r["user_id"])
            raw = str(r["asset_uid"] or "").strip()
            if not raw:
                continue

            try:
                canon = str(uuid.UUID(raw)).lower()
            except (ValueError, AttributeError, TypeError):
                logger.warning("user_uploads id=%s has invalid UUID asset_uid=%r; leaving untouched", row_id, raw)
                continue

            if user_id not in user_seen_uids:
                user_seen_uids[user_id] = set()

            if canon == raw:
                user_seen_uids[user_id].add(canon)
                continue

            # canon != raw
            if canon in user_seen_uids[user_id]:
                logger.warning(
                    "user_uploads id=%s uid normalization collision on canon=%s for user_id=%s; clearing asset_uid",
                    row_id, canon, user_id,
                )
                conn.execute("UPDATE user_uploads SET asset_uid = NULL WHERE id = ?", (row_id,))
            else:
                existing = conn.execute(
                    "SELECT id FROM user_uploads WHERE user_id = ? AND asset_uid = ? AND id <> ? LIMIT 1",
                    (user_id, canon, row_id),
                ).fetchone()
                if existing is not None:
                    logger.warning(
                        "user_uploads id=%s uid normalization collision on canon=%s with existing id=%s; clearing asset_uid",
                        row_id, canon, existing["id"],
                    )
                    conn.execute("UPDATE user_uploads SET asset_uid = NULL WHERE id = ?", (row_id,))
                else:
                    conn.execute("UPDATE user_uploads SET asset_uid = ? WHERE id = ?", (canon, row_id))
                    user_seen_uids[user_id].add(canon)

        if not in_tx:
            conn.execute("COMMIT;")
    except Exception:
        if not in_tx and getattr(conn, "in_transaction", False):
            conn.execute("ROLLBACK;")
        raise


RESET_WORKS_PRICE_SQL = """
-- Migration 073: reset works price to zero
-- works.price column is retired. Zero out existing non-zero values idempotently.
UPDATE works SET price = 0 WHERE price != 0;
"""


ZERO_TOPIC_PUBLISH_CREDITS_SQL = """
-- Migration 075: zero out topic_publish_credits in site_settings
UPDATE site_settings
SET value_json = jsonb_set(value_json::jsonb, '{topic_publish_credits}', '0'::jsonb)::text
WHERE key = 'economy';
"""


def zero_topic_publish_credits_hook(conn: PgConnection) -> None:
    """Ensure site_settings.economy has topic_publish_credits set to 0 idempotently."""
    row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
    if row and row["value_json"]:
        try:
            data = json.loads(row["value_json"])
            if isinstance(data, dict) and data.get("topic_publish_credits") != 0:
                data["topic_publish_credits"] = 0
                conn.execute(
                    "UPDATE site_settings SET value_json = ? WHERE key = 'economy'",
                    (json.dumps(data, ensure_ascii=False),),
                )
        except Exception:
            pass


ZERO_REPLY_PUBLISH_CREDITS_SQL = """
-- Migration 077: zero out reply_publish_credits and reply_daily_cap in site_settings
UPDATE site_settings
SET value_json = jsonb_set(jsonb_set(value_json::jsonb, '{reply_publish_credits}', '0'::jsonb), '{reply_daily_cap}', '0'::jsonb)::text
WHERE key = 'economy';
"""


def zero_reply_publish_credits_hook(conn: PgConnection) -> None:
    """Ensure site_settings.economy has reply_publish_credits and reply_daily_cap set to 0 idempotently."""
    row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'economy'").fetchone()
    if row and row["value_json"]:
        try:
            data = json.loads(row["value_json"])
            if isinstance(data, dict):
                changed = False
                if data.get("reply_publish_credits") != 0:
                    data["reply_publish_credits"] = 0
                    changed = True
                if data.get("reply_daily_cap") != 0:
                    data["reply_daily_cap"] = 0
                    changed = True
                if changed:
                    conn.execute(
                        "UPDATE site_settings SET value_json = ? WHERE key = 'economy'",
                        (json.dumps(data, ensure_ascii=False),),
                    )
        except Exception:
            pass


def audit_and_deduplicate_work_topics(conn: PgConnection) -> list[dict[str, Any]]:
    """Audit and deduplicate duplicate work_id associations in forum_topics idempotently.

    For each work_id referenced by multiple topics in forum_topics:
      1. Inspects all candidate topics for that work_id.
      2. Chooses the primary topic based on:
         - Whether it is mapped in curation_resource_topics for kind='work' and target_id=work_id
         - Reply count in forum_replies
         - Likes count
         - Earliest created_at and id
      3. Keeps the primary topic attached to work_id.
      4. Clears work_id on duplicate topics (work_id = ''), preserving the topic,
         its replies, author, counters, and images (no loss of historical user data).
      5. Records audit events in audit_logs and returns a detailed manifest.
    """
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest: list[dict[str, Any]] = []

    in_tx = getattr(conn, "in_transaction", False)
    if not in_tx:
        conn.execute("BEGIN;")

    try:
        dup_rows = conn.execute(
            """
            SELECT work_id, COUNT(*) AS cnt
            FROM forum_topics
            WHERE work_id IS NOT NULL AND work_id <> ''
            GROUP BY work_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()

        for d_row in dup_rows:
            wid = str(d_row["work_id"]).strip()
            candidates = conn.execute(
                """
                SELECT t.id, t.title, t.author_username, t.likes, t.created_at,
                       COALESCE((SELECT COUNT(*) FROM forum_replies r WHERE r.topic_id = t.id), 0) AS reply_count,
                       EXISTS(
                           SELECT 1 FROM curation_resource_topics m
                           WHERE m.kind = 'work' AND m.target_id = ? AND m.topic_id = t.id
                       ) AS is_mapped
                FROM forum_topics t
                WHERE t.work_id = ?
                ORDER BY is_mapped DESC, reply_count DESC, t.likes DESC, t.created_at ASC, t.id ASC
                """,
                (wid, wid),
            ).fetchall()

            if len(candidates) <= 1:
                continue

            primary = candidates[0]
            duplicates = candidates[1:]

            for dup in duplicates:
                conn.execute("UPDATE forum_topics SET work_id = '' WHERE id = ?", (dup["id"],))
                try:
                    conn.execute(
                        """
                        INSERT INTO audit_logs (
                            actor_id, actor_username, actor_role, action, target_type, target_id,
                            reason, details_json, created_at
                        ) VALUES (NULL, 'system', 'system', 'topic.deduplicate_work_id', 'topic', ?, ?, ?, ?)
                        """,
                        (
                            str(primary["id"]),
                            f"Deduplicated work_id {wid}: kept primary topic {primary['id']}, unlinked duplicate {dup['id']}",
                            json.dumps(
                                {
                                    "work_id": wid,
                                    "primary_topic_id": str(primary["id"]),
                                    "unlinked_topic_id": str(dup["id"]),
                                    "unlinked_title": str(dup["title"] or ""),
                                    "unlinked_author": str(dup["author_username"] or ""),
                                    "unlinked_reply_count": int(dup["reply_count"] or 0),
                                },
                                ensure_ascii=False,
                            ),
                            now_iso,
                        ),
                    )
                except Exception as log_err:
                    logger.warning("Failed to record audit_log for deduplication: %s", log_err)

            item = {
                "work_id": wid,
                "primary_topic_id": str(primary["id"]),
                "primary_reply_count": int(primary["reply_count"] or 0),
                "unlinked_topic_ids": [str(d["id"]) for d in duplicates],
                "duplicates": [
                    {
                        "id": str(d["id"]),
                        "title": str(d["title"] or ""),
                        "author": str(d["author_username"] or ""),
                        "reply_count": int(d["reply_count"] or 0),
                    }
                    for d in duplicates
                ],
            }
            manifest.append(item)
            logger.info(
                "Deduplicated work_id %s: kept primary topic %s (%d replies), unlinked %d duplicate topic(s): %s",
                wid,
                primary["id"],
                primary["reply_count"],
                len(duplicates),
                [d["id"] for d in duplicates],
            )

        if not in_tx:
            conn.execute("COMMIT;")
    except Exception:
        if not in_tx and getattr(conn, "in_transaction", False):
            conn.execute("ROLLBACK;")
        raise

    return manifest


FORUM_TOPICS_LISTED_AT_SQL = """
-- Dedicated listing timestamp: separate original publish time from moderation
-- and user-facing feed placement. Keep nullable for non-published topics.
ALTER TABLE forum_topics ADD COLUMN listed_at_ms INTEGER;
"""


FORUM_TOPICS_WORK_UNIQUE_SQL = """
-- Defensive deduplication in case migration was executed without python hooks
UPDATE forum_topics
SET work_id = ''
WHERE work_id IS NOT NULL AND work_id <> ''
  AND id NOT IN (
      SELECT id FROM (
          SELECT id,
                 ROW_NUMBER() OVER (
                     PARTITION BY work_id
                     ORDER BY
                         CASE WHEN EXISTS (
                             SELECT 1 FROM curation_resource_topics
                             WHERE kind = 'work' AND target_id = forum_topics.work_id AND topic_id = forum_topics.id
                         ) THEN 0 ELSE 1 END ASC,
                         (SELECT COUNT(*) FROM forum_replies WHERE topic_id = forum_topics.id) DESC,
                         likes DESC,
                         created_at ASC,
                         id ASC
                 ) as rn
          FROM forum_topics
          WHERE work_id IS NOT NULL AND work_id <> ''
      ) ranked
      WHERE ranked.rn = 1
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_forum_topics_work_id
    ON forum_topics(work_id) WHERE work_id <> '' AND work_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_forum_topics_pinned_listed
    ON forum_topics(pinned, listed_at_ms, id);
"""
