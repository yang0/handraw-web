"""Pure additive schema: safe to import while db.py initializes."""

SKILL_WEB_MIGRATIONS = [
    (94, "094_skill_personal_resources", """
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
            visibility TEXT NOT NULL DEFAULT 'private',
            schema_version INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1,
            change_seq INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skill_resources_user_seq
            ON skill_personal_resources(user_id,change_seq);
        CREATE TABLE IF NOT EXISTS skill_resource_changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            resource_id TEXT NOT NULL REFERENCES skill_personal_resources(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skill_change_user_seq ON skill_resource_changes(user_id,seq);
    """),
    (95, "095_skill_comment_receipts_v3", """
        -- The legacy Skill-only history / publication tables are intentionally
        -- absent in new databases. Skill uploads now use generation_runs,
        -- generation_items, media_assets, and works.run_id.
        CREATE TABLE IF NOT EXISTS skill_comment_receipts (
            user_id INTEGER NOT NULL REFERENCES users(id),
            request_id TEXT NOT NULL,
            work_id TEXT NOT NULL REFERENCES works(id),
            body_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id,request_id)
        );
    """),
    (98, "098_v3_generation_batches", """
        -- The UI's parallel image requests are children of ONE logical run.
        ALTER TABLE studio_generations ADD COLUMN batch_id TEXT NOT NULL DEFAULT '';
        ALTER TABLE studio_generations ADD COLUMN batch_index INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE studio_generations ADD COLUMN batch_total INTEGER NOT NULL DEFAULT 1;
        CREATE INDEX IF NOT EXISTS idx_studio_gen_user_batch
            ON studio_generations(user_id,batch_id,batch_index,created_at)
            WHERE batch_id <> '';

    """),


    (103, "103_author_private_resource_projection", """
        -- #21: user_resources is a derived READ MODEL of the pre-existing
        -- skill_personal_resources CAS authority. Never write it directly.
        -- A resource is private until explicitly submitted for publication via
        -- the existing moderated community curation workflow.
        CREATE TABLE IF NOT EXISTS user_resources (
            id TEXT PRIMARY KEY REFERENCES skill_personal_resources(id),
            code TEXT NOT NULL UNIQUE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL CHECK(kind IN ('style','layout')),
            name TEXT NOT NULL,
            definition TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            cover_url TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1,
            deleted_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_user_resources_owner
            ON user_resources(owner_user_id,kind,deleted_at,updated_at);
    """),

]

