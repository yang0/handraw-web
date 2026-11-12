"""Additive account recovery, notifications and editor bookkeeping schema."""

FEATURE_MIGRATIONS = [
    (20, "020_account_recovery_and_notifications", """
    CREATE TABLE IF NOT EXISTS account_action_tokens (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        purpose TEXT NOT NULL, email TEXT NOT NULL,
        expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL,
        consumed_at INTEGER, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_account_action_user
        ON account_action_tokens(user_id, purpose, created_at);
    CREATE TABLE IF NOT EXISTS verified_emails (
        user_id INTEGER PRIMARY KEY, email TEXT NOT NULL, verified_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        kind TEXT NOT NULL, title TEXT NOT NULL, target_type TEXT NOT NULL DEFAULT '',
        target_id TEXT NOT NULL DEFAULT '', read_at TEXT, created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC);
    CREATE TRIGGER IF NOT EXISTS notify_work_comment AFTER INSERT ON work_comments
    WHEN NEW.status = 'published'
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        SELECT u.id,'comment','你的作品有新评论','work',NEW.work_id,NEW.created_at
        FROM users u JOIN works w ON w.author_username=u.username
        WHERE w.id=NEW.work_id AND u.username != NEW.author_username;
    END;
    CREATE TRIGGER IF NOT EXISTS notify_forum_reply AFTER INSERT ON forum_replies
    WHEN NEW.status = 'published'
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        SELECT u.id,'reply','你的帖子有新回复','topic',NEW.topic_id,NEW.created_at
        FROM users u JOIN forum_topics t ON t.author_username=u.username
        WHERE t.id=NEW.topic_id AND u.username != NEW.author_username;
    END;
    CREATE TRIGGER IF NOT EXISTS notify_asset_comment AFTER INSERT ON asset_comments
    WHEN NEW.status = 'published'
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        SELECT u.id,'comment','你的资源有新评论','asset',NEW.asset_code,NEW.created_at
        FROM users u JOIN catalog_assets a ON a.author_username=u.username
        WHERE a.code=NEW.asset_code AND u.username != NEW.author_username;
    END;
    CREATE TRIGGER IF NOT EXISTS notify_bounty_accepted AFTER UPDATE OF accepted ON forum_replies
    WHEN NEW.accepted=1 AND OLD.accepted=0
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        SELECT id,'bounty','你的回复已被采纳','topic',NEW.topic_id,strftime('%Y-%m-%dT%H:%M:%SZ','now')
        FROM users WHERE username=NEW.author_username;
    END;
    CREATE TRIGGER IF NOT EXISTS notify_report_resolved AFTER UPDATE OF status ON reports
    WHEN NEW.status != OLD.status AND NEW.status != 'pending'
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        VALUES(NEW.reporter_id,'report','你的举报已有处理结果',NEW.target_type,NEW.target_id,
            strftime('%Y-%m-%dT%H:%M:%SZ','now'));
    END;
    CREATE TRIGGER IF NOT EXISTS notify_wallet_income AFTER INSERT ON ledgers
    WHEN NEW.delta > 0 AND NEW.kind IN ('unlock_income','tip_income','bounty_reward','studio_refund','refund','tip_in','tip_official_in')
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        VALUES(NEW.user_id,'wallet',NEW.reason,CASE WHEN NEW.ref_type != '' THEN NEW.ref_type ELSE 'wallet' END,NEW.ref_id,NEW.created_at);
    END;
    CREATE TRIGGER IF NOT EXISTS notify_generation_failure AFTER UPDATE OF status ON studio_generations
    WHEN NEW.status IN ('refunded','failed') AND NEW.status != OLD.status
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        VALUES(NEW.user_id,'generation','生图任务失败，请查看任务记录与退款状态','generation',NEW.id,
            strftime('%Y-%m-%dT%H:%M:%SZ','now'));
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        SELECT id,'system','有生图任务失败，需要检查网关与退款记录','generation',NEW.id,
            strftime('%Y-%m-%dT%H:%M:%SZ','now') FROM users WHERE role='admin' AND status='active';
    END;
    """
    ),
    (72, "072_tip_notifications_and_indexes", """
    DROP TRIGGER IF EXISTS notify_wallet_income;
    CREATE TRIGGER notify_wallet_income AFTER INSERT ON ledgers
    WHEN NEW.delta > 0 AND NEW.kind IN ('unlock_income','tip_income','bounty_reward','studio_refund','refund','tip_in','tip_official_in')
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        VALUES(NEW.user_id,'wallet',NEW.reason,CASE WHEN NEW.ref_type != '' THEN NEW.ref_type ELSE 'wallet' END,NEW.ref_id,NEW.created_at);
    END;

    CREATE INDEX IF NOT EXISTS idx_ledgers_tips_lookup ON ledgers(kind, ref_type, ref_id);
    """
    ),
    (76, "076_tip_requests_and_rate_limits", """
    CREATE TABLE IF NOT EXISTS tip_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        request_id TEXT,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_tip_requests_user_request
        ON tip_requests(user_id, request_id)
        WHERE request_id IS NOT NULL AND request_id != '';

    CREATE INDEX IF NOT EXISTS idx_tip_requests_user_target_time
        ON tip_requests(user_id, target_type, target_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_tip_requests_user_time
        ON tip_requests(user_id, created_at);
    """
    ),
    (85, "085_expand_wallet_income_notify_kinds", """
    DROP TRIGGER IF EXISTS notify_wallet_income;
    CREATE TRIGGER notify_wallet_income AFTER INSERT ON ledgers
    WHEN NEW.delta > 0 AND NEW.kind IN ('unlock_income','tip_income','bounty_reward','studio_refund','refund','tip_in','tip_official_in','unlock_royalty','bounty_win','unlock_refund','bounty_admin_award','bounty_admin_refund','admin_grant')
    BEGIN
        INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
        VALUES(NEW.user_id,'wallet',NEW.reason,CASE WHEN NEW.ref_type != '' THEN NEW.ref_type ELSE 'wallet' END,NEW.ref_id,NEW.created_at);
    END;
    """
    ),
]
