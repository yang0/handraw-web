# Handraw Web 数据库结构

| 项 | 值 |
|---|---|
| 最后更新 | 2026-11-01 |
| 适用版本 | `integration` 分支 `183a711`（`501a1f9` → `183a711` 未改迁移与表结构） |
| 引擎 | SQLite 3，WAL，`foreign_keys=ON`，`busy_timeout=10000`（`backend/db.py`） |
| 默认路径 | `.local/handraw_v2.db`；`HANDRAW_DB_PATH` 或 `HANDRAW_PRIVATE_STORAGE` 覆盖（`backend/config.py`） |
| 姊妹文档 | [`architecture.md`](architecture.md)、[`product.md`](product.md) |

**与历史文档的关系**：`architecture/design-v1-20261029.md` §3 等历史文件记录了某次变更的设计意图。表结构现状以本文为准，本文又以迁移代码为准。

**查证方法**：在临时目录新建空库，执行 `Database(path).migrate()` 跑完全部迁移，再读 `sqlite_master`、`PRAGMA table_info / foreign_key_list / index_list`。不读、不改任何项目库。下文列名、索引名均来自这次结果。

## 1. 规模

| 项 | 数量 | 说明 |
|---|---|---|
| 迁移 | 28 条 | 版本 1–6、20、40–53、60–66；最后一条 `066_user_library_normalize_asset_uid` |
| 表 | 49 张 | 含 `schema_migrations`；不含 SQLite 内部表 |
| 触发器 | 7 个 | 全部用于生成站内通知（迁移 020） |
| 视图 | 0 | — |
| 迁移后钩子 | 1 个 | 版本 66 → `work_schema.normalize_historical_asset_uids` |

`cold_start_registry` 不在本分支的迁移里。它由 `main` 工作区未提交的 `backend/cold_start_content.py` 创建；`curation._accepted_kinds_for` 会先查 `sqlite_master` 再读它，表不存在时跳过。

## 2. 表（按域）

列名后的 `PK` 为主键，`U` 为唯一约束。「写入方」指在 `backend/` 中对该表执行 INSERT / UPDATE / DELETE 的模块（不含迁移文件）。

### 2.1 用户、会话与令牌

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `users` | 账号 | `id` PK，`username` U，`email` U，`password_hash`、`password_algo`、`discourse_salt`，`role`（user / operator / admin），`status`（active / frozen），`invite_code` U，`invited_by`，`honor_override`，`api_key` U（旧字段） | `idx_users_role_status` | services、admin_services、features、seed |
| `sessions` | 浏览器会话 | `token` PK（明文存储），`user_id` → users，`expires_at`（epoch 秒） | `idx_sessions_user` | services、admin_services、features |
| `api_tokens` | Skill 个人令牌 | `id` PK，`user_id`，`scopes`（JSON），`token_hash` U（SHA-256），`last_used_at`，`revoked_at`（空串 = 有效） | `idx_api_tokens_user_id`；无外键 | device_auth、services（更新 `last_used_at`） |
| `device_codes` | 设备码授权中间态 | `device_code_hash` PK，`user_code` U，`status`，`expires_at`，`interval` | `idx_device_codes_status_expires` | device_auth |
| `account_action_tokens` | 找回密码、邮箱验证一次性令牌 | `token_hash` PK，`user_id` → users（CASCADE），`purpose`，`consumed_at` | `idx_account_action_user` | features |
| `verified_emails` | 已验证邮箱 | `user_id` PK → users（CASCADE），`email` | — | features |

### 2.2 资源目录

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `catalog_assets` | 静态目录之上的数据库覆盖层 | `code` PK，`kind`（style / layout），`source_type`（exclusive / community / official_override），`author_username`，`tier`，`unlock_cost`，`definition`，`prompt_en`，`secret_blackbox_prompt`（资源专属指令，永不下发），`status` | `idx_catalog_kind_status` | curation、admin_services、services、seed |
| `asset_social_seeds` | 演示用基础点赞、收藏数 | `asset_code` PK，`base_likes`，`base_favorites` | 非演示模式读取时视为空表 | seed |
| `asset_comments` | 官方资源旧评论 | `id` PK，`asset_code`，`text`，`status`，`status_actor_role` | `idx_asset_comments_code` | seed 插入；审核经 `services._COMMENT_TABLES` 动态表名更新状态。新评论改写 `forum_replies` |
### 2.3 作品

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `works` | 作品本体（D-01：`works.id` 是唯一主键） | `id` PK，`author_username`，`title`，`images_json`（≤ 9 张），`styles_json`，`layout_code`，`price`，`prompt`，`prompt_has_secret`（NULL / 1 = 对外隐藏），`status`，`status_source` / `status_reason` / `status_actor_role`，`likes` / `cheers` / `favorites` / `forks`（缓存计数），`views`（冻结），`origin`，`request_id`，`forked_from_id`，`subject` | `idx_works_author_request` U 部分（`request_id <> ''`）；`idx_works_forked_from` 部分；`idx_works_popular_v2`（表达式 `likes+cheers+2*favorites+forks`）；`idx_works_status_pub`；`idx_works_author`；`idx_works_author_created` | curation、admin_services、services、features、seed |
| `work_forks` | 复刻去重记录 | `(work_id, user_id)` PK，`first_generation_id` | `idx_work_forks_user`；无外键 | curation |
| `work_comments` | 旧作品评论 | `id` PK，`work_id` → works，`status` | `idx_work_comments_work` | seed 插入；审核同 `asset_comments`。由 `ops/converge_work_comments.py` 收敛到 `forum_replies` |

### 2.4 社区论坛

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `forum_topics` | 帖子（含作品主帖、投稿帖） | `id` PK，`category`，`category_label`（冻结，读常量），`pinned`，`featured`，`price`，`bounty`，`bounty_status`，`accepted_reply_id`，`work_id`，`recipe_json`，`recipe_has_secret`，`locked_body`，`status` + 三个 `status_*`，`likes` / `favorites`，`views`（冻结） | `idx_forum_topics_status`；`idx_forum_topics_category` | services、curation、admin_services、features、resource_discussions、seed |
| `forum_replies` | 统一回复存储（帖子回复、作品评论、资源评论） | `id` PK，`topic_id` → forum_topics，`mounted_style` / `mounted_layout`，`accepted`，`status`，`legacy_source` | `idx_forum_replies_legacy_source` U 部分（`legacy_source <> ''`，防重复迁移）；`idx_forum_replies_topic`；`idx_forum_replies_topic_time` | services、admin_services、seed |
| `forum_moderators` | 版主任命 | `id` PK，`user_id` → users，`username`，`category`（版块 key 或 `all`） | U `(username, category)`；`idx_forum_moderators_user`；`idx_forum_moderators_cat` | admin_services、seed |

### 2.5 互动

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `interactions` | 点赞、鼓励、印章 | PK `(user_id, target_type, target_id, stamp_label)`；`target_type` 如 `like_work`、`work` | `idx_interactions_target` | services、admin_services |
| `collections` | 收藏 | PK `(user_id, bucket, target_id)`；`bucket` ∈ styles / layouts / works / topics | `idx_collections_target` | services、admin_services、seed |

### 2.6 收录体系

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `curation_submissions` | 每个投稿项一行 | `id` PK，`topic_id`，`owner_username`，`kind`，`target_id`（提交时分配的稳定 id），`status`，`current_revision`，`request_id` | U `(kind, target_id)`；`idx_curation_sub_topic` / `_status` / `_owner` | curation |
| `curation_versions` | 每个版本的完整载荷 | `submission_id` → submissions，`revision`，`payload_json` | U `(submission_id, revision)` | curation |
| `curation_assignments` | 审核分配 | `submission_id` →，`revision`，`reviewer_username`，`seq`，`status`（active / voted / stale / released） | U `(submission_id, revision, reviewer_username)` | curation |
| `curation_votes` | 投票，写入后不可改 | `assignment_id` → assignments，`decision`（approve / changes），`reason` | U `(assignment_id)` | curation |
| `curation_review_access` | 按 kind 的手动授予与暂停 | PK `(username, kind)`，`paused`，`manual_granted`，`granted_by` | — | curation |
| `curation_appeals` | 申诉 | `submission_id` →，`status`（open / resolved） | `idx_curation_appeal_sub` | curation |
| `curation_admin_actions` | 管理员裁决记录 | `submission_id`，`admin_username`，`action`，`reason` | `idx_curation_admin_sub` | curation |
| `curation_requests` | 投稿幂等账本 | `owner_username`，`request_id`，`submission_id` | U `(owner_username, request_id)` | curation |
| `curation_events` | 投稿事件流 | `submission_id`，`event_type`，`detail_json` | `idx_curation_events_sub` | curation |
| `curation_drafts` | 30 分钟临时草稿 | `id` PK，`owner_user_id`，`payload_json`，`expires_at`（epoch 秒，浮点） | 写入时顺带删除过期行 | curation_routes |
| `curation_resource_topics` | 资源 ↔ 讨论帖映射（作品、画风、图型） | PK `(kind, target_id)`，`topic_id`，`origin`（`submission` = 评论在 `forum_replies`；`official` / `legacy` = 评论在旧表） | `idx_curation_map_topic` | curation、admin_services、resource_discussions |
### 2.7 创作台

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `studio_generations` | 每次生图任务 | `id` PK，`user_id`，`engine`（live / sample），`prompt`（含专属指令，仅服务端）、`visible_prompt`（可下发）、`prompt_masked`，`system_append_json`，`cost_type`（free_quota / credits），`credits_spent`，`task_id`，`status`，`request_id`，`reservation_date`，`deleted_at`，`fork_work_id`，`prompt_ready`，`recipe_id` | `idx_studio_gen_user_request` U 部分（`request_id <> ''`）；`idx_studio_gen_task`；`idx_studio_gen_user` | services、server、seed |
| `studio_quota_reservations` | 免费额度预占 | `generation_id` PK → generations，`reservation_date`，`units`，`status`（reserved / consumed / released） | `idx_studio_quota_res_user_date` | services |
| `studio_generation_media` | 生成图片归属 | `generation_id` →，`media_url`，`storage_path`，`visibility` | U `(generation_id, media_url)`；`idx_studio_generation_media_owner` | services |
| `media_public_grants` | 私有图片被发布后的公开授权 | `media_url`，`owner_user_id` →，`generation_id` →，`target_type` / `target_id`，`revoked_at` | U `(media_url, target_type, target_id)`；`_target`、`_url` 索引 | server、services、curation |
| `studio_recipes` | 创作参数配方 | `id` PK，`user_id`，`kind`，`style_ids` / `colors` / `tones` / `moods`（JSON），`layout_id`，`ratio`，`mode`，`subject`，`prompt`，`prompt_customized`，`prompt_stale`，`revision`，`input_fingerprint` | `_user_kind`、`_user_created` | recipe_routes |
| `studio_workflows` | 画布工作流与官方预设 | `id` PK，`user_id`，`blueprint`，`graph_json`，`is_official_preset`，`enabled`，`sort_order` | `idx_studio_workflows_user` | services、admin_services、seed |
| `studio_articles` | 文章配图稿 | `id` PK，`user_id`，`markdown`，`cards_json`，`style1`，`layout_code`，`run_count` | `idx_studio_articles_user` | services、admin_services |
| `studio_import_jobs` | 文档导入异步任务 | `id` PK，`user_id`，`status`，`progress_done` / `progress_total`，`result_json`，`error` | `_user`、`_status` | document_importer、server |
| `daily_usage` | 按日计数的 AI 调用限额 | PK `(user_id, scope, usage_date)`，`count` | — | services、server |

### 2.8 个人图库

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `user_uploads` | 用户上传与同步图库 | `id` PK，`user_id` → users，`cat`（图库分类 characters / props / scenes / other；`forum` = 发帖、投稿内嵌图；`import` = 文档导入临时图，24 小时未引用即清理），`image_url`，`file_path`，`bytes`，`asset_uid`（UUID），`local_id`，`name_zh` / `name_en`，`tags_json`，`sha256`，`revision`（≥1），`change_seq`，`updated_at`（毫秒 ISO），`deleted_at`（墓碑），`origin`（web / skill） | `idx_user_uploads_user_asset_uid` U 部分；`idx_user_uploads_user_sha256_active` U 部分（见 §4）；`idx_user_uploads_user_seq` | user_library、server、document_importer、admin_services |
| `library_change_counter` | 全局单调递增同步游标 | `id` PK（`CHECK id = 1`，单行），`current_seq` | — | user_library（`next_change_seq`） |

### 2.9 经济与积分

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `wallets` | 余额与当日额度 | `user_id` PK → users，`balance`，`free_quota_date`，`free_quota_used`，`checkin_date`，`locked` | — | services、admin_services、seed |
| `ledgers` | 积分流水（只追加） | `id` PK，`user_id` →，`delta`，`balance_after`，`kind`，`event_key`，`ref_type` / `ref_id`，`actor_id` | U `(user_id, event_key)`（NULL 不参与）；`idx_ledgers_user_time` | services、admin_services、seed |
| `unlocks` | 付费解锁 | `user_id` →，`author_username`，`target_type`（work / topic / asset），`target_id`，`cost`，`author_share`，`status`（settled / refunded） | U `(user_id, target_type, target_id)` | services、admin_services、seed |
| `redeem_codes` | 兑换码 | `code` PK，`credits`，`max_uses`，`used_count`，`active`，`expires_at` | — | admin_services、services、seed |
| `redeem_code_uses` | 兑换记录 | PK `(code, user_id)` | — | services、admin_services |

### 2.10 审计、通知与治理

| 表 | 用途 | 关键列 | 约束 / 索引 | 写入方 |
|---|---|---|---|---|
| `audit_logs` | 管理操作审计 | `actor_id`，`actor_role`，`action`（如 `moderation.auto_pause`），`target_type` / `target_id`，`details_json` | `idx_audit_logs_time` | services、seed |
| `notifications` | 站内通知 | `user_id` → users（CASCADE），`kind`，`title`，`target_type` / `target_id`，`read_at` | `idx_notifications_user` | features（已读）；触发器（新增） |
| `reports` | 举报 | `reporter_id`，`target_type` / `target_id`，`reason`，`status`，`resolved_by`，`resolution_note` | `idx_reports_status` | services、admin_services、seed |
| `site_settings` | 运营参数 | `key` PK（economy / announcement / moderation / gateway），`value_json` | — | admin_services、services、seed |
| `schema_migrations` | 已执行迁移 | `version` PK，`name`，`applied_at` | — | db |
## 3. 迁移清单

注册顺序：`migrations.MIGRATIONS`（1–6）→ `feature_schema.FEATURE_MIGRATIONS`（20）→ `curation_schema.CURATION_MIGRATIONS`（本分支无此文件，空列表）→ `work_schema.WORK_MIGRATIONS`（40–66）。执行器按列表顺序跑，跳过 `schema_migrations` 已有的版本号，不按数值排序。

「数据变更」列标出会改写或丢弃已有数据、或改变已有索引语义的迁移。按 AGENTS.md，所有迁移都**不回滚**：代码回滚时保留数据库现状，旧代码必须能读新结构。

| 版本 | 名称 | 内容 | 数据变更 |
|---|---|---|---|
| 1 | `001_initial_handraw_v2_core` | users、sessions、wallets、ledgers、catalog_assets、works、work_comments、forum_topics、forum_replies、collections、unlocks、interactions | — |
| 2 | `002_admin_governance_and_studio_cloud` | reports、redeem_codes、redeem_code_uses、studio_workflows、studio_articles、studio_generations、user_uploads、site_settings、audit_logs | — |
| 3 | `003_forum_board_moderators` | forum_moderators | — |
| 4 | `004_asset_comments_and_social_metrics` | asset_comments、asset_social_seeds | — |
| 5 | `005_studio_generation_safety` | generations 加 `request_id` / `reservation_date` / `deleted_at` 与幂等唯一索引；studio_quota_reservations | — |
| 6 | `006_private_studio_media_public_grants` | studio_generation_media、media_public_grants | — |
| 20 | `020_account_recovery_and_notifications` | account_action_tokens、verified_emails、notifications 与 7 个触发器 | — |
| 40 | `040_work_identity_columns` | works 加 `origin` / `request_id` / `forked_from_id` 与索引 | — |
| 41 | `041_social_target_indexes` | interactions、collections、forum_topics、forum_replies 索引 | — |
| 42 | `042_work_forks` | work_forks；generations 加 `fork_work_id` | — |
| 43 | `043_reply_legacy_source` | forum_replies 加 `legacy_source` 与部分唯一索引 | — |
| 44 | `044_work_popular_index` | 表达式索引 `idx_works_popular`（`3*forks`） | 被 48 删除 |
| 45 | `045_resource_topic_map` | curation_resource_topics | — |
| 46 | `046_curation_tables` | 收录 10 张表（IF NOT EXISTS，与 `curation_schema` 030 重复定义，先到者生效） | — |
| 47 | `047_status_source` | works、forum_topics 加 `status_source` / `status_reason` | — |
| 48 | `048_popular_index_v2` | 新建 `idx_works_popular_v2`（`1*forks`），删除 v1 | 是：删索引 |
| 49 | `049_status_actor_role` | 五张内容表加 `status_actor_role`，并按 `audit_logs` 回填 `status_source` | 是：UPDATE 回填 |
| 50 | `050_daily_usage` | daily_usage | — |
| 51 | `051_generation_prompt_ready` | generations 加 `prompt_ready`（默认 1） | — |
| 52 | `052_api_tokens` | api_tokens | — |
| 53 | `053_device_codes` | device_codes | — |
| 60 | `060_studio_recipes` | studio_recipes | — |
| 61 | `061_recipe_and_subject_columns` | generations 加 `recipe_id`；works 加 `subject` | — |
| 62 | `062_studio_import_jobs` | studio_import_jobs | — |
| 63 | `063_generation_visible_prompt_and_snapshot` | generations 加 `visible_prompt` / `prompt_masked` / `system_append_json`；works 加 `prompt_has_secret`；forum_topics 加 `recipe_has_secret` | 新列默认 NULL，读取按「隐藏」处理，由后台回填 |
| 64 | `064_user_library_sync` | user_uploads 加 10 列；library_change_counter；三个索引 | — |
| 65 | `065_user_library_sha256_exclude_forum` | 重建 sha256 去重索引，只覆盖四个图库分类 | 是：删除并重建索引 |
| 66 | `066_user_library_normalize_asset_uid` | DDL 为 `SELECT 1`；迁移后钩子把 `asset_uid` 规范为小写 UUID，同用户冲突时保留 id 最小的一行，其余置 NULL | 是：改写数据，不可逆 |
## 4. 一致性约束

### 4.1 部分唯一索引（幂等与去重）

| 索引 | 条件 | 保证 |
|---|---|---|
| `idx_works_author_request` | `request_id <> ''` | 同一作者同一 `requestId` 只产生一件作品（发布重试安全） |
| `idx_studio_gen_user_request` | `request_id <> ''` | 同一用户同一 `requestId` 只预占一次额度 |
| `idx_forum_replies_legacy_source` | `legacy_source <> ''` | 旧评论迁移到 `forum_replies` 不重复 |
| `idx_user_uploads_user_asset_uid` | `asset_uid IS NOT NULL AND asset_uid <> ''` | 同一用户 UID 唯一（含墓碑） |
| `idx_user_uploads_user_sha256_active` | `deleted_at IS NULL AND sha256 非空 AND (cat IS NULL OR cat IN ('characters','props','scenes','other'))` | 同一用户活动图库中同图只存一份；论坛图、导入图不参与 |
| `ledgers` U `(user_id, event_key)` | `event_key` 为 NULL 时不约束 | 签到、奖励等按事件入账一次 |
| `unlocks` U `(user_id, target_type, target_id)` | — | 一次解锁永久有效；退款后再解锁复用同一行 |

### 4.2 状态机

| 对象 | 列 | 取值与流转 | 维护函数 |
|---|---|---|---|
| 作品 | `works.status` | `published` ⇄ `paused` ⇄ `hidden`；删除为物理删除 | `services.set_work_visibility` |
| 作品主帖 | `forum_topics.status` | 跟随作品，`status_source='work'` | 同上 |
| 普通帖子、回复、评论 | `status` + `status_actor_role` | 低等级角色不能推翻高等级角色的决定（`ACTOR_RANK`：author 1 < moderator 2 < operator 3 < admin 4） | `services.actor_may_override` |
| 收录投稿 | `curation_submissions.status` | `pending` → `approved` / `changes_requested`；作者 revise 回到 `pending`；管理员可 `withdrawn` | `curation.vote` / `revise` / `admin_review` |
| 审核分配 | `curation_assignments.status` | `active` → `voted` / `stale`（版本变化或已出结果）/ `released`（资格失效） | `curation._release_invalid_assignments` |
| 生图任务 | `studio_generations.status` | `running`（`prompt_ready=0` 时等待提示词）→ `queued` → `success` / `refunded`（失败一律退款并记为 `refunded`；触发器还识别 `failed`，当前代码不写该值） | `prepare_` / `claim_` / `complete_` / `refund_failed_cloud_generation` |
| 免费额度预占 | `studio_quota_reservations.status` | `reserved` → `consumed` / `released` | 同上 |
| 解锁 | `unlocks.status` | `settled` ⇄ `refunded` | `unlock_paid_item`、`admin_refund_unlock` |

### 4.3 个人图库同步

| 机制 | 实现 |
|---|---|
| 游标 | 每次写入调用 `next_change_seq`，`library_change_counter` 单行自增，写入行的 `change_seq`；客户端用 `?since=` 增量拉取 |
| 乐观锁 | `revision` 从 1 开始，每次写入 +1；`PUT` / `DELETE` 必须带 `baseRevision`，不符返回 409 |
| 墓碑 | 删除只设 `deleted_at` 并递增 `revision` / `change_seq`；30 天内可恢复；之后 `cleanup_expired_library_tombstones` 物理删除，被已发布作品引用的文件保留 |
| 读时回填 | 旧行缺 `asset_uid` / `change_seq` 时首次读取回填一次；拿不到写锁则跳过本次（`non_blocking`） |

### 4.4 隐私列

`catalog_assets.secret_blackbox_prompt` 与 `studio_generations.prompt` 只在服务端使用。对外下发的提示词经过以下检查，判断结果写在列上，读取时不再扫描：

| 列 | NULL | 0 | 1 |
|---|---|---|---|
| `works.prompt_has_secret` | 隐藏（未扫描） | 可下发 | 隐藏 |
| `forum_topics.recipe_has_secret` | 隐藏配方中的提示词字段 | 可下发 | 隐藏 |
| `studio_generations.visible_prompt` | 隐藏 | — | — |

后台对账线程调用 `run_blackbox_backfill` 分批回填这些列（每批 200 行）。

## 5. 触发器

全部在迁移 020 中定义，只写 `notifications`。

| 触发器 | 事件 | 通知对象 |
|---|---|---|
| `notify_work_comment` | `work_comments` 插入且 `published` | 作品作者 |
| `notify_forum_reply` | `forum_replies` 插入且 `published` | 帖子作者 |
| `notify_asset_comment` | `asset_comments` 插入且 `published` | 资源作者 |
| `notify_bounty_accepted` | `forum_replies.accepted` 0 → 1 | 回复作者 |
| `notify_report_resolved` | `reports.status` 离开 `pending` | 举报人 |
| `notify_wallet_income` | `ledgers` 插入，`delta > 0` 且 `kind IN ('unlock_income','tip_income','bounty_reward','studio_refund','refund')` | 收款人 |
| `notify_generation_failure` | `studio_generations.status` 变为 `failed` / `refunded` | 任务用户与所有在职 admin |

**已知问题**：代码实际写入的收入类流水 `kind` 是 `unlock_royalty`、`tip_in`、`bounty_win`、`unlock_refund`、`studio_refund`。触发器只匹配到 `studio_refund`，作者收到解锁分成、赞赏、悬赏奖金时不会产生通知。修复需要新增迁移重建触发器（`DROP TRIGGER` + `CREATE TRIGGER`），不能改 020。

## 6. 维护规则

- 新迁移追加到 `work_schema.WORK_MIGRATIONS` 末尾，版本号取 67 起；名称必须匹配 `^[0-9]{3}_[a-z0-9_]+$`。
- 只做加法：加表、加列（带默认值）、加索引。改列语义时保留旧列，在本文标「冻结」。
- 每条迁移与 `schema_migrations` 记录在同一事务内提交。`POST_MIGRATION_HOOKS` 在提交**之后**执行；钩子失败时该版本已记为完成，下次启动不会重跑，钩子必须幂等并能单独补跑。
- 集成测试使用临时库，不连生产库。
- 本文的表与列应在新增迁移后按 §「查证方法」重新生成核对。
