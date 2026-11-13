-- Retire only the exact legacy promotional defaults; preserve authored announcements.
SET LOCAL lock_timeout='5s';
SELECT pg_advisory_xact_lock(186,121);
UPDATE site_settings SET value_json=jsonb_set(value_json::jsonb,'{text}',to_jsonb('生图余额与社区积分独立记账，新账号享10张1K免费生图额度，文章与系列图AI规划免费。'::text))::text,updated_by='migration:121',updated_at=CURRENT_TIMESTAMP::text
WHERE key='announcement' AND value_json::jsonb->>'text'='Handraw 手绘风社区升级版：360+ 画风与 160+ 图型全量打通无限画布，荒地首晒立奖 +15✦！';
UPDATE forum_topics SET title='【画风探索】试试这些冷门宝藏画风（FB-055 / FC-028 / FH-043）',summary='试试 FB-055 点描古地图幻想绘本风和 FH-043 复古普鲁士蓝珊瑚红丝网旅行插画。欢迎分享实测效果与创作经验；普通发布不发积分，优质作品经管理员评定后可获得贡献奖励。',updated_at=CURRENT_TIMESTAMP::text
WHERE id='topic_206' AND author_username='forest_mori' AND title='【荒地开垦召集令】这几个冷门宝藏画风（FB-055 / FC-028 / FH-043）出图美哭了，首晒立拿 +15 积分！' AND summary='大家别光盯着 FA 前二十号薅啦！FB-055 点描古地图幻想绘本风和 FH-043 复古普鲁士蓝珊瑚红丝网旅行插画美到窒息，而且现在这些编号下作品数不到 3 个，去晒首图系统直接奖 +15 积分！';
INSERT INTO schema_migrations(version,name,applied_at) VALUES(121,'121_retire_automatic_reward_promotions',CURRENT_TIMESTAMP::text) ON CONFLICT DO NOTHING;
