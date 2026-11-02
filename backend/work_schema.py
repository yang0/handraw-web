from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any
import uuid

logger = logging.getLogger("handraw.work_schema")

"""Additive schema for work identity, social counters, forks and reply provenance.

Migration numbers live in the 40 block.  Every statement here must stay
additive: no DROP, no destructive ALTER, and the file's modules must remain
importable on their own so a staged rollback can still boot.
"""

WORK_IDENTITY_SQL = """
ALTER TABLE works ADD COLUMN origin TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE works ADD COLUMN request_id TEXT NOT NULL DEFAULT '';
ALTER TABLE works ADD COLUMN forked_from_id TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_works_author_request
    ON works(author_username, request_id) WHERE request_id <> '';
CREATE INDEX IF NOT EXISTS idx_works_forked_from
    ON works(forked_from_id) WHERE forked_from_id <> '';
CREATE INDEX IF NOT EXISTS idx_works_author_created
    ON works(author_username, created_at);
"""

SOCIAL_TARGET_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_interactions_target
    ON interactions(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_collections_target
    ON collections(bucket, target_id);
CREATE INDEX IF NOT EXISTS idx_forum_topics_category
    ON forum_topics(category, status, published_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_forum_replies_topic_time
    ON forum_replies(topic_id, status, created_at DESC);
"""

WORK_FORKS_SQL = """
CREATE TABLE IF NOT EXISTS work_forks (
    work_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    first_generation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (work_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_work_forks_user ON work_forks(user_id, created_at DESC);
ALTER TABLE studio_generations ADD COLUMN fork_work_id TEXT NOT NULL DEFAULT '';
"""

REPLY_LEGACY_SOURCE_SQL = """
ALTER TABLE forum_replies ADD COLUMN legacy_source TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_forum_replies_legacy_source
    ON forum_replies(legacy_source) WHERE legacy_source <> '';
"""

# Added after 040 shipped, so it lives in its own migration: the ORDER BY in
# GET /api/works?sort=popular uses this exact expression, and SQLite only uses
# an expression index when the expression matches textually.
WORK_POPULAR_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_works_popular
    ON works(status, (likes + cheers + 2 * favorites + 3 * forks) DESC, published_at_ms DESC);
"""

# The work publish path maps a work to its discussion topic through this table.
# It originally shipped with the curation module, but the publish path depends
# on it, so it must exist wherever this backend runs. ``IF NOT EXISTS`` keeps it
# safe when the curation module also creates it.
RESOURCE_TOPIC_MAP_SQL = """
CREATE TABLE IF NOT EXISTS curation_resource_topics (
    kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'submission',
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, target_id)
);
CREATE INDEX IF NOT EXISTS idx_curation_map_topic ON curation_resource_topics(topic_id);
"""

# The publish path, review queue and appeal flow all live in ``curation.py``,
# which ships with this change, so their tables must be created here too.  The
# curation module keeps its own copy of this DDL; both use IF NOT EXISTS, so
# whichever migrates first wins and the other is a no-op.
CURATION_TABLES_SQL = """
-- Curated community submissions (one forum topic may host many items).
CREATE TABLE IF NOT EXISTS curation_submissions (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    owner_username TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_revision INTEGER NOT NULL DEFAULT 1,
    request_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(kind, target_id)
);

CREATE INDEX IF NOT EXISTS idx_curation_sub_owner ON curation_submissions(owner_username, created_at);
CREATE INDEX IF NOT EXISTS idx_curation_sub_status ON curation_submissions(status);
CREATE INDEX IF NOT EXISTS idx_curation_sub_topic ON curation_submissions(topic_id);

-- Immutable payload snapshots per revision.
CREATE TABLE IF NOT EXISTS curation_versions (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(submission_id, revision),
    FOREIGN KEY (submission_id) REFERENCES curation_submissions(id)
);

CREATE INDEX IF NOT EXISTS idx_curation_ver_sub ON curation_versions(submission_id, revision DESC);

-- Reviewer assignments (max 2 distinct per version, third on divergence).
CREATE TABLE IF NOT EXISTS curation_assignments (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    reviewer_username TEXT NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE(submission_id, revision, reviewer_username),
    FOREIGN KEY (submission_id) REFERENCES curation_submissions(id)
);

CREATE INDEX IF NOT EXISTS idx_curation_asg_sub ON curation_assignments(submission_id, revision, status);

-- Votes are immutable; a reviewer votes once per assignment.
CREATE TABLE IF NOT EXISTS curation_votes (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    reviewer_username TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(assignment_id),
    FOREIGN KEY (assignment_id) REFERENCES curation_assignments(id)
);

CREATE INDEX IF NOT EXISTS idx_curation_vote_sub ON curation_votes(submission_id, revision);

-- Per-kind review access granted to ordinary members.
CREATE TABLE IF NOT EXISTS curation_review_access (
    username TEXT NOT NULL,
    kind TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    manual_granted INTEGER NOT NULL DEFAULT 0,
    granted_by TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (username, kind)
);

-- Author appeals, admin audit records.
CREATE TABLE IF NOT EXISTS curation_appeals (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    author_username TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES curation_submissions(id)
);

CREATE INDEX IF NOT EXISTS idx_curation_appeal_sub ON curation_appeals(submission_id, status);

CREATE TABLE IF NOT EXISTS curation_admin_actions (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    admin_username TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_curation_admin_sub ON curation_admin_actions(submission_id, created_at);

-- Idempotent client request keys (defensive; also mirrored on submissions).
CREATE TABLE IF NOT EXISTS curation_requests (
    id TEXT PRIMARY KEY,
    owner_username TEXT NOT NULL,
    request_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(owner_username, request_id)
);

-- Target/topic mapping shared with the official-comment module.
CREATE TABLE IF NOT EXISTS curation_resource_topics (
    kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'submission',
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, target_id)
);

CREATE INDEX IF NOT EXISTS idx_curation_map_topic ON curation_resource_topics(topic_id);

CREATE TABLE IF NOT EXISTS curation_drafts (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at TEXT NOT NULL
);
-- Audit/event log for curation actions.
CREATE TABLE IF NOT EXISTS curation_events (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL DEFAULT '',
    actor_username TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_curation_events_sub ON curation_events(submission_id, created_at);
"""

# Who moved the work out of public view, and why.  A bare ``status`` column
# cannot distinguish "an admin deliberately hid this" from "automation paused it
# because of reports", so a later report dismissal happily republished moderated
# content.  ``status_source`` records the cause:
#   ''          never moderated
#   'report'    paused automatically by the abuse-report threshold
#   'moderator' hidden/paused by a human (admin, operator or board moderator)
#   'work'      (threads only, since 049) mirrors the linked work's state
#   'author'    (threads only, since 049) the author deleted the thread
STATUS_SOURCE_SQL = """
ALTER TABLE works ADD COLUMN status_source TEXT NOT NULL DEFAULT '';
ALTER TABLE works ADD COLUMN status_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE forum_topics ADD COLUMN status_source TEXT NOT NULL DEFAULT '';
ALTER TABLE forum_topics ADD COLUMN status_reason TEXT NOT NULL DEFAULT '';
"""

# The fork weight changed from 3 to 1 (see ranking.py), so the expression index
# must match the new ORDER BY text.  SQLite has no "replace index", so this uses
# a differently named index and then drops the superseded one.  Dropping an
# index is safe: it rebuilds automatically if code rolls back and asks for it.
POPULAR_INDEX_V2_SQL = """
CREATE INDEX IF NOT EXISTS idx_works_popular_v2
    ON works(status, (likes + cheers + 2 * favorites + forks) DESC, published_at_ms DESC);
DROP INDEX IF EXISTS idx_works_popular;
"""

# Thread visibility had one source value, 'moderator', for two different facts:
# "a human hid this thread" and "this thread mirrors its work, which a human
# hid".  Publishing the work could not tell them apart, so it republished
# threads a moderator had hidden on their own (M8).  Mirrored state now carries
# status_source = 'work'.
#
# ``status_actor_role`` records the rank of whoever made the current decision
# ('admin' > 'operator' > 'moderator' > 'author' / '' for automation).  A lower
# rank may not reverse a higher rank's decision (M9: admin wins, see
# services.actor_may_override).  Comments and replies get the same column so a
# board moderator cannot republish a reply an admin hid (R4).
#
# Backfill, in order:
#   1. Threads whose status, source and reason all equal their work's were
#      written by the old mirror code; mark them 'work'.  This must run before
#      step 2 changes works.status_source.
#   2. Rows paused before migration 047 have an empty source, so a dismissal
#      could never restore them.  When the audit log has an automatic pause
#      for the row and no human hide/pause/confirm ever, the automatic pause is
#      the only thing that can have paused it, so record it as 'report'.  (Old
#      code logged auto_pause even when it changed nothing, so "latest entry
#      is auto_pause" would misread an admin pause followed by reports.)
#   3. Mirrored threads of a work fixed by step 2 still say 'work', which is
#      already correct: the next dismissal publishes the work and the thread
#      follows it.
STATUS_ACTOR_DDL = """
ALTER TABLE works ADD COLUMN status_actor_role TEXT NOT NULL DEFAULT '';
ALTER TABLE forum_topics ADD COLUMN status_actor_role TEXT NOT NULL DEFAULT '';
ALTER TABLE forum_replies ADD COLUMN status_actor_role TEXT NOT NULL DEFAULT '';
ALTER TABLE work_comments ADD COLUMN status_actor_role TEXT NOT NULL DEFAULT '';
ALTER TABLE asset_comments ADD COLUMN status_actor_role TEXT NOT NULL DEFAULT '';
"""

# Kept separate from the DDL so tests can run it against legacy-shaped rows.
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

STATUS_ACTOR_SQL = STATUS_ACTOR_DDL + STATUS_ACTOR_BACKFILL_SQL

DAILY_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS daily_usage (
    user_id INTEGER NOT NULL,
    scope TEXT NOT NULL,
    usage_date TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, scope, usage_date)
);
"""

GENERATION_PROMPT_READY_SQL = """
ALTER TABLE studio_generations ADD COLUMN prompt_ready INTEGER NOT NULL DEFAULT 1;
"""

API_TOKENS_SQL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    scopes TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id);
"""

DEVICE_CODES_SQL = """
CREATE TABLE IF NOT EXISTS device_codes (
    device_code_hash TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    client_name TEXT NOT NULL DEFAULT '',
    scopes TEXT NOT NULL,
    user_id INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approved_at TEXT NOT NULL DEFAULT '',
    last_polled_at TEXT NOT NULL DEFAULT '',
    interval INTEGER NOT NULL DEFAULT 5
);
CREATE INDEX IF NOT EXISTS idx_device_codes_status_expires ON device_codes(status, expires_at);
"""

STUDIO_RECIPES_SQL = """
CREATE TABLE IF NOT EXISTS studio_recipes (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'single',
    style_ids TEXT NOT NULL DEFAULT '[]',
    layout_id TEXT NOT NULL DEFAULT '',
    colors TEXT NOT NULL DEFAULT '[]',
    tones TEXT NOT NULL DEFAULT '[]',
    moods TEXT NOT NULL DEFAULT '[]',
    whitespace TEXT NOT NULL DEFAULT '',
    ratio TEXT NOT NULL DEFAULT '3:4',
    mode TEXT NOT NULL DEFAULT 'graphic-text',
    subject TEXT NOT NULL DEFAULT '',
    references_json TEXT NOT NULL DEFAULT '[]',
    prompt TEXT NOT NULL DEFAULT '',
    prompt_customized INTEGER NOT NULL DEFAULT 0,
    prompt_stale INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    input_fingerprint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studio_recipes_user_kind ON studio_recipes(user_id, kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_studio_recipes_user_created ON studio_recipes(user_id, created_at DESC);
"""

RECIPE_AND_SUBJECT_COLUMNS_SQL = """
ALTER TABLE studio_generations ADD COLUMN recipe_id TEXT NOT NULL DEFAULT '';
ALTER TABLE works ADD COLUMN subject TEXT NOT NULL DEFAULT '';
"""

STUDIO_IMPORT_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS studio_import_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studio_import_jobs_user ON studio_import_jobs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_studio_import_jobs_status ON studio_import_jobs(status);
"""

USER_LIBRARY_SYNC_SQL = """
ALTER TABLE user_uploads ADD COLUMN asset_uid TEXT;
ALTER TABLE user_uploads ADD COLUMN local_id TEXT;
ALTER TABLE user_uploads ADD COLUMN name_en TEXT;
ALTER TABLE user_uploads ADD COLUMN tags_json TEXT DEFAULT '[]';
ALTER TABLE user_uploads ADD COLUMN sha256 TEXT;
ALTER TABLE user_uploads ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE user_uploads ADD COLUMN change_seq INTEGER;
ALTER TABLE user_uploads ADD COLUMN updated_at TEXT;
ALTER TABLE user_uploads ADD COLUMN deleted_at TEXT;
ALTER TABLE user_uploads ADD COLUMN origin TEXT DEFAULT 'web';

CREATE TABLE IF NOT EXISTS library_change_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_seq INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO library_change_counter (id, current_seq) VALUES (1, 0);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_uploads_user_asset_uid
    ON user_uploads(user_id, asset_uid) WHERE asset_uid IS NOT NULL AND asset_uid <> '';
CREATE INDEX IF NOT EXISTS idx_user_uploads_user_seq
    ON user_uploads(user_id, change_seq);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_uploads_user_sha256_active
    ON user_uploads(user_id, sha256) WHERE deleted_at IS NULL AND sha256 IS NOT NULL AND sha256 <> '' AND (cat IS NULL OR cat <> 'import');
"""

GENERATION_VISIBLE_PROMPT_AND_SNAPSHOT_SQL = """
ALTER TABLE studio_generations ADD COLUMN visible_prompt TEXT DEFAULT NULL;
ALTER TABLE studio_generations ADD COLUMN prompt_masked INTEGER NOT NULL DEFAULT 0;
ALTER TABLE studio_generations ADD COLUMN system_append_json TEXT DEFAULT NULL;
ALTER TABLE works ADD COLUMN prompt_has_secret INTEGER DEFAULT NULL;
ALTER TABLE forum_topics ADD COLUMN recipe_has_secret INTEGER DEFAULT NULL;
"""

USER_LIBRARY_SHA256_EXCLUDE_FORUM_SQL = """
DROP INDEX IF EXISTS idx_user_uploads_user_sha256_active;
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_uploads_user_sha256_active
    ON user_uploads(user_id, sha256)
    WHERE deleted_at IS NULL AND sha256 IS NOT NULL AND sha256 <> ''
      AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'));
"""

USER_LIBRARY_NORMALIZE_ASSET_UID_SQL = """
-- 066_user_library_normalize_asset_uid: schema bookkeeping; normalization performed via python post-hook
SELECT 1;
"""

GENERATION_SUBJECT_COLUMN_SQL = """
ALTER TABLE studio_generations ADD COLUMN subject TEXT NOT NULL DEFAULT '';
"""

GENERATION_VISIBILITY_AND_INDEX_SQL = """
ALTER TABLE studio_generations ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public';
CREATE INDEX IF NOT EXISTS idx_studio_gen_user_vis_created ON studio_generations(user_id, status, visibility, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_studio_gen_created_id ON studio_generations(created_at DESC, id DESC);
"""

GENERATION_SOCIAL_SQL = """
ALTER TABLE studio_generations ADD COLUMN fork_generation_id TEXT NOT NULL DEFAULT '';
ALTER TABLE studio_generations ADD COLUMN fork_item_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_studio_gen_fork_gen ON studio_generations(fork_generation_id);
"""


def normalize_historical_asset_uids(conn: sqlite3.Connection) -> None:
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
        conn.execute("BEGIN IMMEDIATE;")

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


DEDUPLICATE_GENERATION_HISTORY_SQL = """
-- Migration 069: Idempotent generation history deduplication hook
SELECT 1;
"""


RESET_WORKS_PRICE_SQL = """
-- Migration 073: reset works price to zero
-- works.price column is retired. Zero out existing non-zero values idempotently.
UPDATE works SET price = 0 WHERE price != 0;
"""


def deduplicate_generation_history(conn: sqlite3.Connection, user_id: int | None = None) -> int:
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
        conn.execute("BEGIN IMMEDIATE;")

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
            HAVING cnt > 1
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
                if not primary["subject"] and dup["subject"]:
                    updates.append("subject = ?")
                    update_vals.append(dup["subject"])
                if not primary["recipe_summary"] and dup["recipe_summary"]:
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
            SELECT id, user_id, engine, subject, recipe_summary, items_json, created_at
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
                    if not primary["subject"] and client_row["subject"]:
                        updates.append("subject = ?")
                        update_vals.append(client_row["subject"])
                    if not primary["recipe_summary"] and client_row["recipe_summary"]:
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
            elif len(rows_with_same_images) > 1 and not server_rows:
                for dup in rows_with_same_images[1:]:
                    conn.execute(
                        "UPDATE studio_generations SET deleted_at = ? WHERE id = ? AND COALESCE(deleted_at, '') = ''",
                        (now_iso, dup["id"]),
                    )
                    count_deleted += 1

        if not in_tx:
            conn.execute("COMMIT;")
    except Exception:
        if not in_tx and getattr(conn, "in_transaction", False):
            conn.execute("ROLLBACK;")
        raise

    return count_deleted


WORK_POST_MIGRATION_HOOKS: dict[int, Any] = {
    66: normalize_historical_asset_uids,
    69: deduplicate_generation_history,
}

WORK_MIGRATIONS: list[tuple[int, str, str]] = [
    (40, "040_work_identity_columns", WORK_IDENTITY_SQL),
    (41, "041_social_target_indexes", SOCIAL_TARGET_INDEXES_SQL),
    (42, "042_work_forks", WORK_FORKS_SQL),
    (43, "043_reply_legacy_source", REPLY_LEGACY_SOURCE_SQL),
    (44, "044_work_popular_index", WORK_POPULAR_INDEX_SQL),
    (45, "045_resource_topic_map", RESOURCE_TOPIC_MAP_SQL),
    (46, "046_curation_tables", CURATION_TABLES_SQL),
    (47, "047_status_source", STATUS_SOURCE_SQL),
    (48, "048_popular_index_v2", POPULAR_INDEX_V2_SQL),
    (49, "049_status_actor_role", STATUS_ACTOR_SQL),
    (50, "050_daily_usage", DAILY_USAGE_SQL),
    (51, "051_generation_prompt_ready", GENERATION_PROMPT_READY_SQL),
    (52, "052_api_tokens", API_TOKENS_SQL),
    (53, "053_device_codes", DEVICE_CODES_SQL),
    (60, "060_studio_recipes", STUDIO_RECIPES_SQL),
    (61, "061_recipe_and_subject_columns", RECIPE_AND_SUBJECT_COLUMNS_SQL),
    (62, "062_studio_import_jobs", STUDIO_IMPORT_JOBS_SQL),
    (63, "063_generation_visible_prompt_and_snapshot", GENERATION_VISIBLE_PROMPT_AND_SNAPSHOT_SQL),
    (64, "064_user_library_sync", USER_LIBRARY_SYNC_SQL),
    (65, "065_user_library_sha256_exclude_forum", USER_LIBRARY_SHA256_EXCLUDE_FORUM_SQL),
    (66, "066_user_library_normalize_asset_uid", USER_LIBRARY_NORMALIZE_ASSET_UID_SQL),
    (67, "067_generation_subject_column", GENERATION_SUBJECT_COLUMN_SQL),
    (68, "068_generation_visibility_and_index", GENERATION_VISIBILITY_AND_INDEX_SQL),
    (69, "069_deduplicate_generation_history", DEDUPLICATE_GENERATION_HISTORY_SQL),
    (73, "073_reset_works_price_to_zero", RESET_WORKS_PRICE_SQL),
    (74, "074_generation_social_and_fork", GENERATION_SOCIAL_SQL),
]
