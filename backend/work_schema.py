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

WORK_MIGRATIONS: list[tuple[int, str, str]] = [
    (40, "040_work_identity_columns", WORK_IDENTITY_SQL),
    (41, "041_social_target_indexes", SOCIAL_TARGET_INDEXES_SQL),
    (42, "042_work_forks", WORK_FORKS_SQL),
    (43, "043_reply_legacy_source", REPLY_LEGACY_SOURCE_SQL),
    (44, "044_work_popular_index", WORK_POPULAR_INDEX_SQL),
]
