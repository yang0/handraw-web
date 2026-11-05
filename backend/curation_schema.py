"""Community curation schema migrations (additive only).

Ships as ``CURATION_MIGRATIONS`` so the primary reviewer can append it to
``backend/migrations.py`` without editing existing migration files.
"""
from __future__ import annotations

CURATION_SQL = """
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

CURATION_MIGRATIONS: list[tuple[int, str, str]] = [
    (30, "030_community_curation", CURATION_SQL),
    (31, "031_curation_vote_unique", "CREATE UNIQUE INDEX IF NOT EXISTS idx_curation_vote_reviewer ON curation_votes(submission_id,revision,reviewer_username);"),
]
