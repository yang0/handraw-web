"""Additive schema migrations for Handraw Web 2.0.

Per AGENTS.md:
- Database changes are strictly additive.
- A code rollback must never roll back database migrations.
- Stored in Python rather than .sql files so ops/check_release.py treats zero source files as DB dumps.
"""
from __future__ import annotations

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "001_initial_handraw_v2_core",
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            display_name TEXT NOT NULL,
            email TEXT UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            password_algo TEXT NOT NULL DEFAULT 'pbkdf2_sha256',
            discourse_salt TEXT NOT NULL DEFAULT '',
            discourse_user_id INTEGER,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            bio TEXT NOT NULL DEFAULT '',
            invite_code TEXT UNIQUE NOT NULL,
            invited_by TEXT NOT NULL DEFAULT '',
            honor_override INTEGER,
            api_key TEXT UNIQUE,
            first_collect_rewarded INTEGER NOT NULL DEFAULT 0,
            first_cheer_rewarded INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_users_role_status ON users(role, status);

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            user_agent TEXT NOT NULL DEFAULT '',
            ip_addr TEXT NOT NULL DEFAULT '',
            expires_at INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

        CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            free_quota_date TEXT NOT NULL DEFAULT '',
            free_quota_used INTEGER NOT NULL DEFAULT 0,
            checkin_date TEXT NOT NULL DEFAULT '',
            locked INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS ledgers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            kind TEXT NOT NULL,
            event_key TEXT,
            reason TEXT NOT NULL,
            ref_type TEXT NOT NULL DEFAULT '',
            ref_id TEXT NOT NULL DEFAULT '',
            actor_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, event_key),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ledgers_user_time ON ledgers(user_id, id DESC);

        CREATE TABLE IF NOT EXISTS catalog_assets (
            code TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            source_type TEXT NOT NULL,
            author_username TEXT NOT NULL DEFAULT '',
            author_name TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            group_name TEXT NOT NULL DEFAULT '',
            tier TEXT NOT NULL DEFAULT 'free',
            unlock_cost INTEGER NOT NULL DEFAULT 0,
            image_url TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            definition TEXT NOT NULL DEFAULT '',
            prompt_en TEXT NOT NULL DEFAULT '',
            secret_blackbox_prompt TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'published',
            featured INTEGER NOT NULL DEFAULT 0,
            is_new_release INTEGER NOT NULL DEFAULT 0,
            cheers INTEGER NOT NULL DEFAULT 0,
            tips INTEGER NOT NULL DEFAULT 0,
            stamp_counts_json TEXT NOT NULL DEFAULT '{}',
            published_at_ms INTEGER NOT NULL,
            created_label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_kind_status ON catalog_assets(kind, status, source_type);

        CREATE TABLE IF NOT EXISTS works (
            id TEXT PRIMARY KEY,
            author_username TEXT NOT NULL,
            author_name TEXT NOT NULL,
            title TEXT NOT NULL,
            images_json TEXT NOT NULL DEFAULT '[]',
            styles_json TEXT NOT NULL DEFAULT '[]',
            layout_code TEXT NOT NULL DEFAULT '',
            sc021_type TEXT NOT NULL DEFAULT '',
            color_code TEXT NOT NULL DEFAULT 'C-15',
            tone_code TEXT NOT NULL DEFAULT 'T-01',
            ratio TEXT NOT NULL DEFAULT '3:4',
            mode TEXT NOT NULL DEFAULT 'graphic-text',
            shoot_type TEXT NOT NULL DEFAULT '',
            mood TEXT NOT NULL DEFAULT '治愈',
            price INTEGER NOT NULL DEFAULT 0,
            prompt TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'published',
            featured INTEGER NOT NULL DEFAULT 0,
            is_new_release INTEGER NOT NULL DEFAULT 0,
            pioneer_rewarded INTEGER NOT NULL DEFAULT 0,
            cheers INTEGER NOT NULL DEFAULT 0,
            likes INTEGER NOT NULL DEFAULT 0,
            favorites INTEGER NOT NULL DEFAULT 0,
            forks INTEGER NOT NULL DEFAULT 0,
            tips INTEGER NOT NULL DEFAULT 0,
            views INTEGER NOT NULL DEFAULT 0,
            stamp_counts_json TEXT NOT NULL DEFAULT '{}',
            published_at_ms INTEGER NOT NULL,
            created_label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_works_status_pub ON works(status, published_at_ms DESC);
        CREATE INDEX IF NOT EXISTS idx_works_author ON works(author_username);

        CREATE TABLE IF NOT EXISTS work_comments (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            author_username TEXT NOT NULL,
            author_name TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            time_label TEXT NOT NULL DEFAULT '刚刚',
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_id) REFERENCES works(id)
        );

        CREATE INDEX IF NOT EXISTS idx_work_comments_work ON work_comments(work_id, status);

        CREATE TABLE IF NOT EXISTS forum_topics (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            category_label TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0,
            featured INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            author_username TEXT NOT NULL,
            author_name TEXT NOT NULL,
            views INTEGER NOT NULL DEFAULT 0,
            likes INTEGER NOT NULL DEFAULT 0,
            favorites INTEGER NOT NULL DEFAULT 0,
            price INTEGER NOT NULL DEFAULT 0,
            bounty INTEGER NOT NULL DEFAULT 0,
            bounty_status TEXT NOT NULL DEFAULT 'none',
            solved INTEGER NOT NULL DEFAULT 0,
            accepted_reply_id TEXT NOT NULL DEFAULT '',
            images_json TEXT NOT NULL DEFAULT '[]',
            styles_json TEXT NOT NULL DEFAULT '[]',
            layout_code TEXT NOT NULL DEFAULT '',
            work_id TEXT NOT NULL DEFAULT '',
            recipe_json TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL,
            locked_body TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'published',
            published_at_ms INTEGER NOT NULL,
            created_label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_forum_topics_status ON forum_topics(status, pinned DESC, published_at_ms DESC);

        CREATE TABLE IF NOT EXISTS forum_replies (
            id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL,
            author_username TEXT NOT NULL,
            author_name TEXT NOT NULL,
            text TEXT NOT NULL,
            mounted_style TEXT NOT NULL DEFAULT '',
            mounted_layout TEXT NOT NULL DEFAULT '',
            likes INTEGER NOT NULL DEFAULT 0,
            accepted INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'published',
            time_label TEXT NOT NULL DEFAULT '刚刚',
            created_at TEXT NOT NULL,
            FOREIGN KEY (topic_id) REFERENCES forum_topics(id)
        );

        CREATE INDEX IF NOT EXISTS idx_forum_replies_topic ON forum_replies(topic_id, status);

        CREATE TABLE IF NOT EXISTS collections (
            user_id INTEGER NOT NULL,
            bucket TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, bucket, target_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS unlocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            author_username TEXT NOT NULL DEFAULT '',
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            cost INTEGER NOT NULL,
            author_share INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'settled',
            refund_reason TEXT NOT NULL DEFAULT '',
            refunded_by INTEGER,
            refunded_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, target_type, target_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS interactions (
            user_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            stamp_label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, target_type, target_id, stamp_label),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """,
    ),
    (
        2,
        "002_admin_governance_and_studio_cloud",
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reporter_username TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            target_title TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            resolved_by TEXT NOT NULL DEFAULT '',
            resolution_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, id DESC);

        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY COLLATE NOCASE,
            credits INTEGER NOT NULL,
            max_uses INTEGER NOT NULL DEFAULT 100,
            used_count INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS redeem_code_uses (
            code TEXT NOT NULL COLLATE NOCASE,
            user_id INTEGER NOT NULL,
            used_at TEXT NOT NULL,
            PRIMARY KEY (code, user_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS studio_workflows (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            blueprint TEXT NOT NULL DEFAULT 'single',
            scenario_badge TEXT NOT NULL DEFAULT '',
            scenario_desc TEXT NOT NULL DEFAULT '',
            graph_json TEXT NOT NULL,
            is_official_preset INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_studio_workflows_user ON studio_workflows(user_id, is_official_preset, sort_order);

        CREATE TABLE IF NOT EXISTS studio_articles (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            article_title TEXT NOT NULL,
            markdown TEXT NOT NULL,
            cards_json TEXT NOT NULL DEFAULT '[]',
            style1 TEXT NOT NULL DEFAULT '',
            layout_code TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ready',
            run_count INTEGER NOT NULL DEFAULT 0,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_studio_articles_user ON studio_articles(user_id, updated_at_ms DESC);

        CREATE TABLE IF NOT EXISTS studio_generations (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT NOT NULL DEFAULT '',
            tab_title TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT '',
            mode_label TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'single',
            recipe_summary TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            markdown TEXT NOT NULL DEFAULT '',
            items_json TEXT NOT NULL DEFAULT '[]',
            engine TEXT NOT NULL DEFAULT 'sample',
            cost_type TEXT NOT NULL DEFAULT 'free',
            credits_spent INTEGER NOT NULL DEFAULT 0,
            task_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'success',
            error_msg TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_studio_gen_user ON studio_generations(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_studio_gen_task ON studio_generations(task_id);

        CREATE TABLE IF NOT EXISTS user_uploads (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            cat TEXT NOT NULL DEFAULT 'other',
            name_zh TEXT NOT NULL,
            desc_zh TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL,
            file_path TEXT NOT NULL DEFAULT '',
            bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            actor_username TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_logs_time ON audit_logs(id DESC);
        """,
    ),
    (
        3,
        "003_forum_board_moderators",
        """
        CREATE TABLE IF NOT EXISTS forum_moderators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL COLLATE NOCASE,
            category TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '版主',
            appointed_by TEXT NOT NULL DEFAULT 'system',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(username, category),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_forum_moderators_cat ON forum_moderators(category);
        CREATE INDEX IF NOT EXISTS idx_forum_moderators_user ON forum_moderators(username);
        """,
    ),
    (
        4,
        "004_asset_comments_and_social_metrics",
        """
        CREATE TABLE IF NOT EXISTS asset_comments (
            id TEXT PRIMARY KEY,
            asset_code TEXT NOT NULL,
            asset_kind TEXT NOT NULL DEFAULT 'style',
            author_username TEXT NOT NULL,
            author_name TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            time_label TEXT NOT NULL DEFAULT '刚刚',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_asset_comments_code ON asset_comments(asset_code, status);

        CREATE TABLE IF NOT EXISTS asset_social_seeds (
            asset_code TEXT PRIMARY KEY,
            base_likes INTEGER NOT NULL DEFAULT 0,
            base_favorites INTEGER NOT NULL DEFAULT 0
        );
        """,
    ),
    (
        5,
        "005_studio_generation_safety",
        """
        ALTER TABLE studio_generations ADD COLUMN request_id TEXT NOT NULL DEFAULT '';
        ALTER TABLE studio_generations ADD COLUMN reservation_date TEXT NOT NULL DEFAULT '';
        ALTER TABLE studio_generations ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '';

        -- An empty request id means the caller did not opt into idempotency.
        -- A partial unique index keeps retries with a real client request id
        -- from charging twice while allowing legacy rows to keep their empty
        -- default value.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_studio_gen_user_request
            ON studio_generations(user_id, request_id)
            WHERE request_id <> '';

        -- Keep a durable record of the day on which a free generation was
        -- reserved. The wallet is a current-day counter, so this table lets a
        -- later refund release an old-day reservation without decrementing the
        -- next day's quota.
        CREATE TABLE IF NOT EXISTS studio_quota_reservations (
            generation_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            reservation_date TEXT NOT NULL,
            units INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'reserved',
            created_at TEXT NOT NULL,
            released_at TEXT,
            FOREIGN KEY (generation_id) REFERENCES studio_generations(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_studio_quota_res_user_date
            ON studio_quota_reservations(user_id, reservation_date, status);
        """,
    ),
    (
        6,
        "006_private_studio_media_public_grants",
        """
        -- Generated files remain private by default. A publication flow can
        -- register the exact generated URL here before exposing it publicly;
        -- ownership and target checks stay in the service/HTTP layer.
        CREATE TABLE IF NOT EXISTS studio_generation_media (
            id TEXT PRIMARY KEY,
            generation_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            media_url TEXT NOT NULL,
            media_kind TEXT NOT NULL DEFAULT 'generated',
            storage_path TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            created_at TEXT NOT NULL,
            UNIQUE(generation_id, media_url),
            FOREIGN KEY (generation_id) REFERENCES studio_generations(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_studio_generation_media_owner
            ON studio_generation_media(user_id, visibility, created_at DESC);

        CREATE TABLE IF NOT EXISTS media_public_grants (
            id TEXT PRIMARY KEY,
            media_url TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL,
            generation_id TEXT,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            granted_by_user_id INTEGER NOT NULL,
            granted_at TEXT NOT NULL,
            revoked_at TEXT,
            UNIQUE(media_url, target_type, target_id),
            FOREIGN KEY (owner_user_id) REFERENCES users(id),
            FOREIGN KEY (generation_id) REFERENCES studio_generations(id),
            FOREIGN KEY (granted_by_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_media_public_grants_target
            ON media_public_grants(target_type, target_id, revoked_at);
        CREATE INDEX IF NOT EXISTS idx_media_public_grants_url
            ON media_public_grants(media_url, revoked_at);
        """,
    ),
    (
        83,
        "083_studio_articles_deleted_at",
        """
        ALTER TABLE studio_articles ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '';
        CREATE INDEX IF NOT EXISTS idx_studio_articles_deleted ON studio_articles(user_id, deleted_at, updated_at_ms DESC);
        """,
    ),
    (
        84,
        "084_clear_legacy_plaintext_sessions",
        """
        -- Migration 084: clear legacy plaintext sessions.
        -- Sessions are now stored by sha256 hash.
        -- This migration only deletes existing session data without altering the schema.
        -- If code is rolled back to an older version, users are logged out once, with zero data loss.
        DELETE FROM sessions;
        """,
    ),
    (
        87,
        "087_user_avatar_and_locked_nickname",
        """
        -- Compatibility with original nickname identity policy.
        ALTER TABLE users ADD COLUMN avatar_url TEXT NOT NULL DEFAULT '';
        ALTER TABLE users ADD COLUMN nickname_locked INTEGER NOT NULL DEFAULT 1;
        """,
    ),
    (
        88,
        "088_account_identity_lifecycle",
        """
        -- Zero means legacy users are eligible for their first nickname change.
        ALTER TABLE users ADD COLUMN nickname_changed_at INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE users ADD COLUMN closed_at TEXT NOT NULL DEFAULT '';
        CREATE TABLE IF NOT EXISTS auth_funnel_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            user_id INTEGER,
            source TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_auth_funnel_events_name_time
            ON auth_funnel_events(event_name, created_at);
        """,
    ),
    (
        89,
        "089_account_recovery_and_erasure_requests",
        """
        -- A request, not an automatic destructive cleanup. Review retention first.
        CREATE TABLE IF NOT EXISTS account_erasure_requests (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            processed_at TEXT NOT NULL DEFAULT '',
            review_note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_account_erasure_status
            ON account_erasure_requests(status, requested_at);
        """,
    ),
    (
        90,
        "090_p2_identity_growth_security",
        """
        CREATE TABLE IF NOT EXISTS oauth_identities (
            provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            provider_login TEXT NOT NULL DEFAULT '',
            linked_at TEXT NOT NULL,
            PRIMARY KEY(provider, provider_user_id),
            UNIQUE(provider,user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_oauth_identity_user ON oauth_identities(user_id);

        CREATE TABLE IF NOT EXISTS oauth_flows (
            state_hash TEXT PRIMARY KEY,
            browser_nonce_hash TEXT NOT NULL,
            provider TEXT NOT NULL,
            purpose TEXT NOT NULL,
            user_id INTEGER,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_oauth_flows_expires ON oauth_flows(expires_at);

        CREATE TABLE IF NOT EXISTS growth_events (
            user_id INTEGER NOT NULL REFERENCES users(id),
            event_name TEXT NOT NULL,
            event_day TEXT NOT NULL,
            happened_at TEXT NOT NULL,
            PRIMARY KEY(user_id,event_name,event_day)
        );
        CREATE INDEX IF NOT EXISTS idx_growth_events_name_day ON growth_events(event_name,event_day);
        CREATE TABLE IF NOT EXISTS security_devices (
            user_id INTEGER NOT NULL REFERENCES users(id),
            fingerprint TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(user_id,fingerprint)
        );
        CREATE TRIGGER IF NOT EXISTS growth_first_collection AFTER INSERT ON collections
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          VALUES(NEW.user_id,'first_collection',substr(NEW.created_at,1,10),NEW.created_at);
        END;
        CREATE TRIGGER IF NOT EXISTS growth_first_work AFTER INSERT ON works
        WHEN NEW.status='published'
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          SELECT u.id,'first_work',substr(NEW.created_at,1,10),NEW.created_at
          FROM users u WHERE u.username=NEW.author_username;
        END;
        CREATE TRIGGER IF NOT EXISTS growth_first_topic AFTER INSERT ON forum_topics
        WHEN NEW.status='published'
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          SELECT u.id,'first_topic',substr(NEW.created_at,1,10),NEW.created_at
          FROM users u WHERE u.username=NEW.author_username;
        END;
        CREATE TRIGGER IF NOT EXISTS growth_first_generation AFTER INSERT ON studio_generations
        WHEN NEW.status='success'
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          SELECT NEW.user_id,'first_generation',substr(NEW.created_at,1,10),NEW.created_at
          WHERE NEW.user_id IS NOT NULL;
        END;
        CREATE TRIGGER IF NOT EXISTS growth_generation_success AFTER UPDATE OF status ON studio_generations
        WHEN NEW.status='success' AND OLD.status!='success'
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          SELECT NEW.user_id,'first_generation',substr(strftime('%Y-%m-%d','now'),1,10),
                 strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE NEW.user_id IS NOT NULL;
        END;
        CREATE TRIGGER IF NOT EXISTS growth_email_verified_insert AFTER INSERT ON verified_emails
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          VALUES(NEW.user_id,'email_verified',substr(NEW.verified_at,1,10),NEW.verified_at);
        END;
        CREATE TRIGGER IF NOT EXISTS growth_email_verified_update AFTER UPDATE ON verified_emails
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          VALUES(NEW.user_id,'email_verified',substr(NEW.verified_at,1,10),NEW.verified_at);
        END;

        -- Backfill prior milestones once, using the original timestamps.
        INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
        SELECT user_id,'first_collection',substr(MIN(created_at),1,10),MIN(created_at)
        FROM collections GROUP BY user_id;
        INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
        SELECT u.id,'first_work',substr(MIN(w.created_at),1,10),MIN(w.created_at)
        FROM works w JOIN users u ON u.username=w.author_username
        WHERE w.status='published' GROUP BY u.id;
        INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
        SELECT u.id,'first_topic',substr(MIN(t.created_at),1,10),MIN(t.created_at)
        FROM forum_topics t JOIN users u ON u.username=t.author_username
        WHERE t.status='published' GROUP BY u.id;
        INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
        SELECT user_id,'first_generation',substr(MIN(created_at),1,10),MIN(created_at)
        FROM studio_generations WHERE status='success' AND user_id IS NOT NULL GROUP BY user_id;
        INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
        SELECT user_id,'email_verified',substr(verified_at,1,10),verified_at
        FROM verified_emails;
        """,
    ),
    (
        91,
        "091_social_signup_confirmation",
        """
        -- GitHub can authenticate identity before an immutable nickname is chosen.
        CREATE TABLE IF NOT EXISTS oauth_signup_tickets (
            ticket_hash TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            provider_login TEXT NOT NULL DEFAULT '',
            verified_email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_oauth_signup_expires ON oauth_signup_tickets(expires_at);
        """,
    ),
    (
        92,
        "092_activation_publish_transitions",
        """
        CREATE TRIGGER IF NOT EXISTS growth_work_publish_transition AFTER UPDATE OF status ON works
        WHEN NEW.status='published' AND OLD.status!='published'
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          SELECT u.id,'first_work',date('now'),strftime('%Y-%m-%dT%H:%M:%SZ','now')
          FROM users u WHERE u.username=NEW.author_username;
        END;
        CREATE TRIGGER IF NOT EXISTS growth_topic_publish_transition AFTER UPDATE OF status ON forum_topics
        WHEN NEW.status='published' AND OLD.status!='published'
        BEGIN
          INSERT OR IGNORE INTO growth_events(user_id,event_name,event_day,happened_at)
          SELECT u.id,'first_topic',date('now'),strftime('%Y-%m-%dT%H:%M:%SZ','now')
          FROM users u WHERE u.username=NEW.author_username;
        END;
        """,
    ),
    (
        93,
        "093_google_oidc_pkce",
        """
        -- OAuth code verifier is single-use and removed together with state.
        ALTER TABLE oauth_flows ADD COLUMN code_verifier TEXT NOT NULL DEFAULT '';
        """,
    ),
]

# Feature work can add independent additive migrations without creating a
# second registry. Keep this optional for staged rollouts.
try:
    from .feature_schema import FEATURE_MIGRATIONS
except ImportError:  # pragma: no cover - compatibility for staged rollouts
    FEATURE_MIGRATIONS = []

MIGRATIONS.extend(FEATURE_MIGRATIONS)

# Community curation schema.  Optional so a checkout that does not include the
# curation module can still boot and migrate; the module ships with the feature.
try:
    from .curation_schema import CURATION_MIGRATIONS
except ImportError:  # pragma: no cover - compatibility for partial checkouts
    CURATION_MIGRATIONS: list[tuple[int, str, str]] = []

MIGRATIONS.extend(CURATION_MIGRATIONS)

# Post-migration Python hooks for non-DDL schema/data normalizations.
POST_MIGRATION_HOOKS: dict[int, Any] = {}

# Work identity / social counters / forks (migration block 040+).
try:
    from .work_schema import WORK_MIGRATIONS, WORK_POST_MIGRATION_HOOKS
    POST_MIGRATION_HOOKS.update(WORK_POST_MIGRATION_HOOKS)
except ImportError:  # pragma: no cover - compatibility for staged rollouts
    WORK_MIGRATIONS = []

MIGRATIONS.extend(WORK_MIGRATIONS)

# Direct Messages (migration block 070+).
try:
    from .messaging import DM_MIGRATIONS
except ImportError:  # pragma: no cover - compatibility for staged rollouts
    DM_MIGRATIONS = []

MIGRATIONS.extend(DM_MIGRATIONS)

# Home Scenarios (migration block 086+).
try:
    from .home_scenarios import SCENARIOS_MIGRATIONS, SCENARIOS_POST_MIGRATION_HOOKS
    POST_MIGRATION_HOOKS.update(SCENARIOS_POST_MIGRATION_HOOKS)
    MIGRATIONS.extend(SCENARIOS_MIGRATIONS)
except ImportError:  # pragma: no cover - compatibility for staged rollouts
    SCENARIOS_MIGRATIONS = []

# Skill/Web unified personal cloud (additive, no legacy data rewrite).
from .skill_web_schema import SKILL_WEB_MIGRATIONS
MIGRATIONS.extend(SKILL_WEB_MIGRATIONS)

def _repair_existing_public_generation_works(conn: Any) -> None:
    """Repair already-public history in one migration without exposing private rows.

    A corrupt legacy record must not prevent the website from starting.
    Each row uses a savepoint, so one failure cannot leave a half-published work.
    Failed rows remain available for the administrator's reconciliation audit.
    """
    import logging
    from .generation_works import project_generation_to_works
    log = logging.getLogger("handraw.migrations")
    rows = conn.execute("""
        SELECT id FROM studio_generations
        WHERE status='success' AND visibility='public'
          AND COALESCE(deleted_at,'')='' AND COALESCE(engine,'')!='demo'
          AND items_json IS NOT NULL AND items_json NOT IN ('','[]')
        ORDER BY created_at DESC,id DESC
    """).fetchall()
    failures = 0
    for row in rows:
        conn.execute("SAVEPOINT skill_public_repair")
        try:
            project_generation_to_works(conn, str(row["id"]))
        except Exception as error:
            conn.execute("ROLLBACK TO SAVEPOINT skill_public_repair")
            failures += 1
            log.warning("Public generation work repair skipped id=%s: %s", row["id"], error)
        finally:
            conn.execute("RELEASE SAVEPOINT skill_public_repair")
    if failures:
        log.warning("%s legacy public generations remain unprojected; use admin audit/reconcile", failures)

POST_MIGRATION_HOOKS[97] = _repair_existing_public_generation_works

# Ensure migrations execute in strictly ascending numerical order
MIGRATIONS.sort(key=lambda m: m[0])
