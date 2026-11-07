"""Additive schema for Skill ↔ Web v1 personal resources and private history.

All tables are owner-scoped.  Skill-generated content is NEVER automatically
projected into the public works table.
"""
SKILL_CLOUD_MIGRATIONS = [
    (94, "094_skill_cloud_personal_resources_and_history", """
        CREATE TABLE IF NOT EXISTS skill_resource_change_counter (
            id INTEGER PRIMARY KEY CHECK(id=1),
            next_seq INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO skill_resource_change_counter(id,next_seq) VALUES (1,0);
        CREATE TABLE IF NOT EXISTS skill_personal_resources (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL CHECK(kind IN ('style','layout')),
            name TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            license TEXT NOT NULL,
            examples_json TEXT NOT NULL DEFAULT '[]',
            version TEXT NOT NULL DEFAULT '1.0.0',
            origin_json TEXT NOT NULL DEFAULT 'null',
            visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility='private'),
            revision INTEGER NOT NULL DEFAULT 1,
            change_seq INTEGER NOT NULL,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skill_personal_resources_user_seq
            ON skill_personal_resources(user_id,change_seq);
        CREATE TABLE IF NOT EXISTS skill_generation_runs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            external_run_id TEXT NOT NULL,
            origin_client TEXT NOT NULL DEFAULT 'skill',
            status TEXT NOT NULL DEFAULT 'success',
            original_request TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id,external_run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_skill_runs_user_created
            ON skill_generation_runs(user_id,created_at DESC,id DESC);
        CREATE TABLE IF NOT EXISTS skill_generation_media (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES skill_generation_runs(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            media_url TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id,position)
        );
        CREATE INDEX IF NOT EXISTS idx_skill_generation_media_owner
            ON skill_generation_media(user_id,media_url);
        CREATE TABLE IF NOT EXISTS skill_comment_requests (
            user_id INTEGER NOT NULL REFERENCES users(id),
            request_id TEXT NOT NULL,
            work_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            reply_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id,request_id)
        );
    """)
]
