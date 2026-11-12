"""Schema definitions for historical fixtures."""

from typing import Any

from backend.home_scenarios import seed_default_home_scenarios_hook


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
                CHECK(status IN ('pending','uploading','running','partial','success','failed','cancelled')),
            -- Permanent V3 publication tombstone: a deleted work cannot be
            -- recreated when a delayed gateway callback replays the run.
            publication_deleted_at TEXT NOT NULL DEFAULT '',
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
        -- Distinguish a temporary first-completion cover from a deliberate
        -- choice by the author. Async arrivals may revise only the former.
        ALTER TABLE works ADD COLUMN cover_selected_by_author INTEGER NOT NULL
            DEFAULT 0 CHECK(cover_selected_by_author IN (0,1));
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
    (100, "100_private_media_gc_queue", """
        -- Retryable, never-public file reclamation. A media key must not be
        -- physically deleted until all current database references are gone.
        CREATE TABLE IF NOT EXISTS media_gc_jobs (
            media_url TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            next_attempt_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            claim_until INTEGER NOT NULL DEFAULT 0,
            claim_token TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_media_gc_due
            ON media_gc_jobs(next_attempt_at,claim_until);
    """),
]


DM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dm_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_low_id INTEGER NOT NULL,
    user_high_id INTEGER NOT NULL,
    last_message_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_low_id, user_high_id),
    FOREIGN KEY (user_low_id) REFERENCES users(id),
    FOREIGN KEY (user_high_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_conv_low_high ON dm_conversations(user_low_id, user_high_id);
CREATE INDEX IF NOT EXISTS idx_dm_conv_updated ON dm_conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS dm_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    client_message_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(sender_id, client_message_id),
    FOREIGN KEY (conversation_id) REFERENCES dm_conversations(id),
    FOREIGN KEY (sender_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_messages_conv_id ON dm_messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_dm_messages_sender_time ON dm_messages(sender_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dm_members (
    conversation_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    last_read_message_id INTEGER NOT NULL DEFAULT 0,
    read_at TEXT,
    PRIMARY KEY (conversation_id, user_id),
    FOREIGN KEY (conversation_id) REFERENCES dm_conversations(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_members_user ON dm_members(user_id);

CREATE TABLE IF NOT EXISTS dm_blocks (
    user_id INTEGER NOT NULL,
    blocked_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, blocked_user_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (blocked_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_blocks_user ON dm_blocks(user_id);
CREATE INDEX IF NOT EXISTS idx_dm_blocks_blocked ON dm_blocks(blocked_user_id);

CREATE TABLE IF NOT EXISTS dm_contact_history (
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    first_contact_date TEXT NOT NULL,
    first_contact_at TEXT NOT NULL,
    PRIMARY KEY (sender_id, recipient_id),
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (recipient_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_contact_hist_date ON dm_contact_history(sender_id, first_contact_date);
"""

BROADCAST_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS message_broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    audience_cutoff TEXT NOT NULL,
    request_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    withdrawn_at TEXT,
    FOREIGN KEY (sender_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_broadcasts_request_id ON message_broadcasts(request_id);
CREATE INDEX IF NOT EXISTS idx_broadcasts_published ON message_broadcasts(published_at DESC);

CREATE TABLE IF NOT EXISTS message_broadcast_reads (
    broadcast_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (broadcast_id, user_id),
    FOREIGN KEY (broadcast_id) REFERENCES message_broadcasts(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_broadcast_reads_user ON message_broadcast_reads(user_id);
"""

DM_MIGRATIONS: list[tuple[int, str, str]] = [
    (70, "070_direct_messages", DM_SCHEMA_SQL),
    (71, "071_message_broadcasts", BROADCAST_SCHEMA_SQL),
]


HOME_SCENARIOS_SQL = """
CREATE TABLE IF NOT EXISTS home_scenarios (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL,
    studio_entry TEXT NOT NULL,
    studio_params_json TEXT NOT NULL DEFAULT '{}',
    match_rules_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_home_scenarios_order
    ON home_scenarios(sort_order ASC, is_enabled DESC);

CREATE TABLE IF NOT EXISTS scenario_pinned_works (
    scenario_key TEXT NOT NULL,
    work_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (scenario_key, work_id),
    FOREIGN KEY (scenario_key) REFERENCES home_scenarios(key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scenario_pins_order
    ON scenario_pinned_works(scenario_key, sort_order ASC);
"""


SCENARIOS_MIGRATIONS: list[tuple[int, str, str]] = [
    (86, "086_home_scenarios", HOME_SCENARIOS_SQL),
]

SCENARIOS_POST_MIGRATION_HOOKS: dict[int, Any] = {
    86: seed_default_home_scenarios_hook,
}
