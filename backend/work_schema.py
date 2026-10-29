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

WORK_MIGRATIONS: list[tuple[int, str, str]] = [
    (40, "040_work_identity_columns", WORK_IDENTITY_SQL),
    (41, "041_social_target_indexes", SOCIAL_TARGET_INDEXES_SQL),
    (42, "042_work_forks", WORK_FORKS_SQL),
    (43, "043_reply_legacy_source", REPLY_LEGACY_SOURCE_SQL),
    (44, "044_work_popular_index", WORK_POPULAR_INDEX_SQL),
    (45, "045_resource_topic_map", RESOURCE_TOPIC_MAP_SQL),
    (46, "046_curation_tables", CURATION_TABLES_SQL),
]
