BEGIN;
CREATE TABLE IF NOT EXISTS forum_boards (
    key text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_-]{0,63}$' AND key <> 'all'),
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
    description text NOT NULL DEFAULT '',
    visibility text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','private')),
    state text NOT NULL DEFAULT 'open' CHECK (state IN ('open','closed')),
    position integer NOT NULL DEFAULT 100,
    revision bigint NOT NULL DEFAULT 1,
    created_by bigint REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO forum_boards(key,label,description,position) VALUES
 ('showcase','作品讨论','公开作品的讨论',0),
 ('tuning','作品求调优 / 悬赏','实测诊断、提示词调优与积分悬赏',10),
 ('experience','实战经验与变现','分享创作经验与交付方法',20),
 ('assets','画风与图型专区','画风、图型使用心得与讨论',30),
 ('tools','工具流与问答','创作工具、工作流与问题交流',40)
ON CONFLICT DO NOTHING;
INSERT INTO forum_boards(key,label)
 SELECT DISTINCT category, MAX(COALESCE(NULLIF(category_label,''),category))
 FROM forum_topics WHERE category ~ '^[a-z][a-z0-9_-]{0,63}$' AND category <> 'all'
 GROUP BY category ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS forum_board_members (
    board_key text NOT NULL REFERENCES forum_boards(key),
    user_id bigint NOT NULL REFERENCES users(id),
    invited_by bigint NOT NULL REFERENCES users(id),
    invited_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at timestamptz,
    PRIMARY KEY(board_key,user_id)
);
CREATE INDEX IF NOT EXISTS forum_board_members_user_active ON forum_board_members(user_id,board_key) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS forum_topics_board_list ON forum_topics(category,published_at_ms DESC,id) WHERE status='published';
INSERT INTO schema_migrations(version,name,applied_at) VALUES(122,'forum_boards',CURRENT_TIMESTAMP::text) ON CONFLICT DO NOTHING;
COMMIT;
