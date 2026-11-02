# Handraw Web 产品文档

| 项 | 值 |
|---|---|
| 最后更新 | 2026-11-01 |
| 适用版本 | `integration` 分支 `183a711`（事实核对基于 `501a1f9`，并已核对 `183a711` 的收录封面改动） |
| 姊妹文档 | [`architecture.md`](architecture.md)、[`database.md`](database.md) |

**与历史文档的关系**：`docs/` 下带日期的验收、评审、修复报告（如 `acceptance-2026-10-21.md`、`v2-acceptance-2026-10-27.md`、`architecture/*-20261029/30.md`）和 `product-direction.md`、`studio.md`、`功能全景树与缺口清单-本地2.0-2026-10-27.md` 均为阶段性快照，只作留档。产品现状以本文为准；本文与代码冲突时以代码为准，并回来修订本文。

状态标记：**已实现** = 后端接口、前端入口、测试都在；**部分实现** = 只有一端，或规则只落实一半；**未实现** = 只在设计文档中出现。

## 1. 定位与目标用户

Handraw 是手绘风格的图片创作社区。主线流程：

```text
发现作品 / 画风 / 图型 → 创作台在线生图 → 保存到个人历史 → 主动发布作品 → 社区讨论、复刻
```

| 用户 | 主要诉求 |
|---|---|
| 内容创作者（小红书、公众号、电商） | 选画风和图型，输入主题，在线出图；批量出套图；给文章配图 |
| 画风 / 图型作者 | 分享结构化的画风、图型定义，被收录进官方目录，获得积分分成 |
| Skill 用户（对话式 AI 客户端） | 通过设备码绑定账号，分享作品、同步个人图库 |
| 运营与版主 | 内容审核、举报处理、版块治理、积分与兑换码 |

画风、图型目录的权威数据在独立的 Skill 仓库 `E:\handraw-style`（`HANDRAW_STYLE_SKILL_DIR`、`HANDRAW_STYLE_IMAGES_DIR`）。网站只读这些文件，不复制一份目录。

## 2. 前端入口

单个后端进程同时提供四个页面（见 `architecture.md` §2）。

| 页面 | 本地路径 | 生产 Host | 文件 |
|---|---|---|---|
| 主站（发现、频道、账户） | `/` | `handraw-style.com` | `demo/index.html` |
| 创作台 | `/studio/` | `studio.*` | `demo/studio.html` |
| 社区 | `/forum/` | `forum.*`、`bbs.*` | `demo/forum.html` |
| 后台 | `/admin/` | `admin.*` | `demo/admin.html` |

## 3. 功能全景

### 3.1 发现（主站）

| 功能 | 做什么 | 谁能用 | 关键限制 | 状态 |
|---|---|---|---|---|
| 作品广场 `?view=works` | 已发布作品的信息流 | 所有人 | 排序只有 `newest` / `popular`（`backend/ranking.py`） | 已实现 |
| 榜单 `?view=rankings` | 作品、创作者、资源排行 | 所有人 | 浏览数不参与排序 | 已实现 |
| 作品详情 `?view=work` | 多图、配方、解锁付费提示词、复刻入口 | 所有人；付费提示词需解锁 | 含资源专属指令的提示词对外返回空串 | 已实现 |
| 收藏 `?view=profile&ptab=collections` | 按 `styles` / `layouts` / `works` / `topics` 四类收藏，整合于个人主页收藏夹 | 登录用户（仅本人） | 旧链接 `?view=collections` 自动跳转 | 已实现 |
| 钱包 `?view=wallet` | 余额、签到、兑换码、流水（最近 60 条） | 登录用户 | 现金充值关闭，见 §5 | 部分实现 |
| 个人主页 `?view=profile` | 作者作品与荣誉 | 所有人 | — | 已实现 |
| Skill 绑定 `?view=device` | 设备码授权页 | 登录用户 | 设备码 10 分钟过期 | 已实现 |
| SEO 首页 | 服务端为 `index.html` 注入标题、OG 图、站点地图 | 爬虫 | `/robots.txt`、`/sitemap.xml` | 已实现 |

热门公式（唯一实现在 `backend/ranking.py`，前端 `S.popularScore` 与之做一致性测试）：

| 对象 | `popularScore` |
|---|---|
| 作品 | `likes + cheers + 2*favorites + forks` |
| 帖子 | `已发布回复数 + likes + 2*favorites`；作品主帖取作品的计数 |
### 3.2 画风与图型频道（主站 `?view=styles` / `?view=layouts` / `?view=asset`）

| 功能 | 做什么 | 谁能用 | 关键限制 | 状态 |
|---|---|---|---|---|
| 目录浏览 | 官方画风（370+）、图型（170+）与已收录社区资源 | 所有人 | 静态目录来自 `plugin/content/catalog.json`，经 `/data/catalog.json` 下发 | 已实现 |
| 资源覆盖层 | `catalog_assets` 中 `exclusive` / `community` / `official_override` 三类，在 boot 时叠加到静态目录 | 所有人 | 只有 `status='published'` 下发 | 已实现 |
| 资源解锁 | 付费资源按 `unlock_cost` 扣积分 | 登录用户 | `exclusive` 资源解锁后也不返回定义正文 | 已实现 |
| 使用此画风 / 图型 | 跳转创作台并预填 | 所有人 | — | 已实现 |
| 资源讨论 | 评论统一写入该资源主帖的 `forum_replies` | 登录用户 | 单条 800 字（`resource_discussions.py:153`） | 已实现 |

社区画风、图型只有经过 §3.6 双人收录才会写入 `catalog_assets`，进入频道页。`catalog_assets` 的写入方只有 `curation`、`admin_services`、`seed`。

**评价信号（#24）**：官方资源与社区资源共用同一套评价信号：点赞、收藏、印章（🎯 超实用配方、✨ 审美在线）、赞赏，都按资源编号记录，从哪个入口进来都是同一份数据。无标签的「👏」与点赞重复，帖子页资源块不再显示（3b12）；存量数据继续计数。区别只在存储：社区资源的 `cheers` / `tips` / `stamp_counts_json` 缓存在 `catalog_assets` 列上；catalog.json 中的官方资源在该表里没有行，计数从 `interactions`（印章）和 `ledgers`（`tip_official_in`）聚合（`post_routes._handle_detail`）。这些信号**目前还没有进入资源排序**，见 §6。

### 3.3 创作台（`/studio/`）

模式切换条在 `studio-app.js` 的 `renderCreationModeBar`，URL 参数 `?entry=quick|batch|article|canvas`。

| 模式 | 前端模块 | 做什么 | 后端接口 | 状态 |
|---|---|---|---|---|
| 做图 | `studio-make-image.js` | 单张：画风（可双画风融合）+ 图型 + 配色 + 主题 → 生图；提示词预览只读 | `/api/studio/recipes*`、`/api/studio/generate` | 已实现 |
| 批量 | `studio-batch.js` | 母题 + 张数（1–20，默认 6）→ AI 规划套图或固定图型逐行主题；单次上限 200 张，超过 20 张二次确认 | `/api/studio/batch-plan`、`/api/studio/fission` | 已实现 |
| 文章配图 | `studio-app.js`（`article` 蓝图） | 粘贴或导入正文 → AI 规划封面与插图位置 → 生成 → 回填正文 | `/api/studio/article-plan`、`/api/studio/imports`、`/api/studio/parse-article` | 已实现 |
| 高级画布 | `studio-app.js` + `studio-prompt-engine.js` | 节点图工作流，含官方预设（`studio_workflows.is_official_preset`） | `/api/studio/workflows` | 已实现 |

四种模式共用 `studio-prompt-engine.js` 的 `assembleControlPrompt(graph, ctrl, catalog, format)`：`format="skill"` 生成可复制给 Skill 的指令，`format="cloud"` 生成在线生图提示词。服务端再经 `backend/skill_prompt.py` 读取 Skill 的 `references/` 重新组装提示词；未配置文本模型时退回确定性模板。

共用能力：

| 能力 | 说明 | 状态 |
|---|---|---|
| 配方 `studio_recipes` | 保存创作参数；`baseRevision` 乐观锁；可从作品复制（`/api/studio/recipes/from-work/<id>`） | 已实现 |
| 生图历史 | 最近 40 条，服务端持久化，跨刷新、跨日保留 | 已实现 |
| 文档导入 | 异步任务 `studio_import_jobs`，单段 6000 字 | 已实现 |
| 打包导出 | `/api/studio/export-zip` | 已实现 |
| 参考图 | 每次最多 6 张，逐张检查归属；`CH-001` 官方角色可选 | 已实现 |

生图计费与限制：

| 规则 | 值（`site_settings` 默认值，见 `backend/seed.py`） |
|---|---|
| 每日免费张数 | `economy.daily_free_quota = 3`（按 Asia/Shanghai 日期） |
| 免费用尽后每张扣积分 | `economy.studio_credit_per_image = 2` |
| 同一用户在途任务 | `gateway.max_inflight_per_user = 1` |
| 提示词 + 资源系统说明上限 | 4000 字，超出返回 400 `prompt_too_long` |
| 网关明确失败 | 自动退还免费额度或积分 |
| 网关超时等未知状态 | 不退款，由后台对账线程按 `task_id` 查询后处理 |
| AI 规划类每日上限 | `fission` 50、`batch_plan` 50、`article_plan` 30、提示词预览 `prompt` 100（`daily_usage`） |
### 3.4 社区（`/forum/`）

版块是常量 `FORUM_BOARDS`（`backend/services.py:51`），不建表：

| key | 名称 | 说明 |
|---|---|---|
| `showcase` | 晒作品 | 只能通过作品发布产生帖子，一帖对应一件作品 |
| `tuning` | 作品求调优 / 悬赏 | 悬赏帖、采纳回复 |
| `experience` | 实战经验与变现 | — |
| `assets` | 画风与图型专区 | 收录投稿帖也在这里 |
| `tools` | 工具流与问答 | — |
| `all` | 全区 | 仅用于版主任命范围，不是可发帖的版块 |

| 功能 | 做什么 | 谁能用 | 关键限制 | 状态 |
|---|---|---|---|---|
| 帖子列表与详情 `?view=topic&id=` | 帖子正文、楼层回复 | 所有人 | 回复分页 `GET /api/posts/<id>/replies?cursor=&limit=20` | 已实现 |
| 发帖 / 回复 | 正文经 `sanitize_html`；回复可挂载画风、图型 | 登录用户 | 发帖 +5、回复 +2 积分，回复奖励每日上限 5 次 | 已实现 |
| 付费帖 | `price` > 0 时 `locked_body` 解锁后可见 | 登录用户 | 发帖时截断到 0–100；后台编辑截断到 0–200 | 已实现 |
| 悬赏 | 发帖人采纳回复 `/accept-bounty` | 发帖人；运营可仲裁 | 悬赏 0–200 | 已实现 |
| 置顶 / 加精 / 移版 / 隐藏 | `/api/forum/moderate` | 版主（限所辖版块）、运营、管理员 | 管理员自加精受 `moderation.allow_self_review_for_admin` 控制 | 已实现 |
| 举报 | `/api/reports`；同一对象未处理举报数达 3 时自动暂停 | 登录用户 | `moderation.auto_pause_report_threshold = 3` | 已实现 |
| 短链 `/t/<ref>` | 解析为帖子；画风、图型代码跳转到主站资源页 | 所有人 | — | 已实现 |
| 资源详情 `?view=resource&kind=` | `forum-resources.js` 渲染的作品、画风、图型详情 | 所有人 | 创始人 2026-10-30 决定以帖子页为唯一详情页，此视图待移除 | 部分实现 |

### 3.5 作品发布与复刻

| 功能 | 做什么 | 谁能用 | 关键限制 | 状态 |
|---|---|---|---|---|
| 发布作品 `POST /api/works` | 立即发布（决策 D-02），同时在 `showcase` 建主帖，写入 `curation_resource_topics(kind='work')` 映射 | 登录用户 | 最多 9 张图；`requestId` 幂等；发布奖励 +5；引用的任一画风或图型已发布作品少于 3 件时另加先锋奖励 +10 | 已实现 |
| Skill 分享 `POST /api/entries` | 把 Skill 的 `{entry}` 转成作品发布；返回 `{id, kind:"work", url}` 回执 | Skill（`publish` scope 令牌）或登录用户 | 同上 | 已实现 |
| 付费作品 | `works.price` > 0，解锁后才返回提示词 | 作者设置 | 发布时 0–100，超出返回 400 `price_out_of_range`；后台编辑截断到 0–200 | 已实现 |
| 复刻 | 从作品进入创作台，带 `fork_work_id` 的生成成功后计入 `work_forks` | 登录用户 | 同一用户对同一作品只计一次；作者自刻不计 | 已实现 |
| 作者编辑 | `/api/content/works/<id>/edit` | 作者 | 编辑不重新审核 | 已实现 |

作品状态机（`works.status`）：`published` ⇄ `paused`（举报达阈值或人工）⇄ `hidden`；删除为物理删除，主帖改为 `hidden`。主帖状态跟随作品，统一由 `set_work_visibility` 维护。

### 3.6 收录体系（双人审核）

只适用于画风、图型进入官方目录。作品不走收录（`curation.submit` 收到 `kind='work'` 返回 400 `work_publish_moved`）。

```text
投稿 POST /api/curation/submissions（1–20 项；每项一张本站上传的正方形封面，另加 0–9 张任意比例示例图）
  → 建投稿帖（assets 版）+ 每项一条 curation_submissions(status=pending)
  → 审核者从 /api/curation/review-queue 领取分配（每项最多 2 个活动分配）
  → 2 票 approve → approved → _publish_approved 写入 catalog_assets，作者获奖励
  → 2 票 changes → changes_requested（退回必须写理由）
  → 1:1 分歧 → 等第三人领取
作者可 revise（版本 +1，旧分配作废）或 appeal（交管理员裁决）
管理员 /api/curation/admin/review 可 approve / changes / reopen / withdraw
```

审核资格（`curation._review_access_for`，按 kind 分别判断）：暂停 > 手动授予 > 管理员 > 自己已有该类收录内容。任何人不能审核自己的投稿。冷启动账号（`cold_start_registry`，表存在时）不因已有内容获得资格。

| 功能 | 状态 |
|---|---|
| 投稿、投票、修订、申诉、管理员裁决、30 分钟草稿 | 已实现 |
| 作品双人审核进精选 | 未实现（推迟到下一期，见 `architecture/design-v1-20261029.md` 决策 5） |
### 3.7 个人图库

创始人决定：Skill 自建图库与网站账号绑定后双向自动同步。实现在 `backend/user_library.py`，数据存于 `user_uploads`。

| 功能 | 做什么 | 谁能用 | 关键限制 | 状态 |
|---|---|---|---|---|
| 网页上传 | `POST /api/uploads`、`/api/studio/uploads`；同账号同图（sha256）去重 | 登录用户 | 单图 15 MB、4000 万像素；PNG / JPEG / WebP | 已实现 |
| 同步读取 | `GET /api/library/assets?since=<cursor>` 返回变更与墓碑 | 用户或 `library` scope 令牌 | 令牌每小时 1200 次 | 已实现 |
| 新建 / 修改 | `PUT /api/library/assets/<uuid>`，需 `baseRevision` | 同上 | UID 必须是 UUID；版本不符返回 409 `conflict` | 已实现 |
| 删除 / 恢复 | 软删除留墓碑，30 天内可 `restore` | 同上 | 30 天后由后台清理（约每小时一次）；被已发布作品引用的文件不删 | 已实现 |
| 配额 | 每账号 500 件、1 GB | — | — | 已实现 |
| Skill 侧客户端 | 冲突合并规则写在 `user_library.py` 模块文档 | — | 客户端在 `skill-addon/` 与外部 Skill 仓库，不在本文范围 | 待核实 |

### 3.8 账户与 Skill 授权

| 功能 | 做什么 | 关键限制 | 状态 |
|---|---|---|---|
| 注册 / 登录 / 登出 | Cookie 会话 `handraw_sid`，30 天 | 登录 8 次 / 5 分钟、注册 5 次 / 15 分钟（按 IP 令牌桶） | 已实现 |
| 找回密码 / 邮箱验证 | `account_action_tokens` 一次性令牌，经 SMTP 发信（`HANDRAW_SMTP_*`） | 生产 SMTP 是否已配置：待核实 | 已实现（代码） |
| 邀请码 | 邀请人 +15、被邀请人 +10 | — | 已实现 |
| Discourse 账号迁移 | 管理员导入；老用户用原用户名、邮箱、密码登录；导入时赠送 `discourse_migration_credits`（默认 50） | 只迁账号，不迁帖子 | 已实现 |
| 站内通知 | 7 个 SQLite 触发器生成（评论、回复、悬赏采纳、举报处理、收入、生图失败等） | — | 已实现 |
| 设备码授权 | RFC 8628 风格；Skill 拿到 `hwt_` 前缀个人令牌 | scope 仅 `publish`、`library`；令牌可吊销 | 已实现 |

### 3.9 后台（`/admin/`）

模块按角色下发（`admin_services.ROLE_MATRIX_SPEC`）：

| 角色 | 可见模块 |
|---|---|
| admin | dashboard、users、works、catalog、governance、gateway、settings |
| operator | dashboard、users、works、governance、settings |
| moderator | mod_overview、mod_topics、mod_replies、mod_reports |

主要能力：用户管理与冻结、内容审核与下架、举报裁定、版主任命、积分调账、解锁退款、兑换码、公告、网关监控、资源专属指令（黑盒提示词）读写、审计日志、收录管理。

## 4. 角色与权限

`users.role` 只存 `user`、`operator`、`admin` 三种值。`reviewer` 是旧值，读取时视为 `operator`，`seed.py` 启动时会把库里的 `reviewer` 改写为 `operator`。版主不是角色，由 `forum_moderators` 按版块任命。收录审核者也不是角色，由 `curation_review_access` 与已收录内容按 kind 判定。

| 能力 | 匿名 | user | 收录审核者 | 版主 | operator | admin |
|---|---|---|---|---|---|---|
| 浏览公开内容 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 生图、发布、评论、收藏、解锁 | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| 收录投票（不能审自己的） | — | — | ✓ | — | — | ✓（备用） |
| 置顶、加精、移版、隐藏帖子 | — | — | — | 所辖版块 | ✓ | ✓ |
| 内容下架 / 删除、举报裁定、冻结普通用户 | — | — | — | 所辖版块的举报 | ✓ | ✓ |
| 荣誉、免费额度重置、兑换码、公告、悬赏仲裁 | — | — | — | — | ✓ | ✓ |
| 建删用户、改角色、重置密码、任命版主 | — | — | — | — | — | ✓ |
| 积分调账、解锁退款、Discourse 导入 | — | — | — | — | — | ✓ |
| 系统设置、审计日志、网关、资源专属指令 | — | — | — | — | — | ✓ |

运营不能自审本人内容。`admin` 对本人内容加精、置顶受 `moderation.allow_self_review_for_admin` 控制（默认 `True`，见 §6）。
## 5. 积分与配额

积分（✦）只在站内流通。所有变动经 `apply_wallet_delta` 写 `ledgers`，`(user_id, event_key)` 唯一，同一事件不会重复入账。参数存在 `site_settings.economy`，管理员可在后台修改；下表是 `backend/seed.py` 的默认值。

| 键 | 默认 | 含义 |
|---|---|---|
| `welcome_credits` | 20 | 注册赠送 |
| `daily_checkin_credits` | 5 | 每日签到 |
| `work_publish_credits` | 5 | 发布作品 |
| `pioneer_bonus_credits` / `pioneer_work_threshold` | 10 / 3 | 先锋奖励及门槛 |
| `asset_publish_credits` | 15 | 画风、图型被收录 |
| `honor_upgrade_credits` | 10 | 荣誉升级 |
| `topic_publish_credits` | 5 | 发帖 |
| `reply_publish_credits` / `reply_daily_cap` | 2 / 5 | 回复奖励及每日次数 |
| `invite_inviter_credits` / `invite_invitee_credits` | 15 / 10 | 邀请双方 |
| `first_collect_credits` / `first_cheer_credits` | 2 / 2 | 首次收藏、首次鼓励 |
| `daily_free_quota` | 3 | 每日免费生图张数 |
| `studio_credit_per_image` | 2 | 免费用尽后每张积分 |
| `author_share_ratio` | 0.80 | 付费解锁时作者分成；官方内容（含 `exclusive`）无分成，解锁积分不入任何账户 |
| `official_tip_payee` | `""` | 官方资源赞赏的收款账号（用户名）。为空时官方资源赞赏关闭 |
| `discourse_migration_credits` | 50 | Discourse 迁移用户赠送 |

| 机制 | 规则 | 状态 |
|---|---|---|
| 付费解锁 | 作品、帖子、社区资源三类；一次解锁永久有效（`unlocks` 唯一键）；作者本人与免费内容直接可见 | 已实现 |
| 解锁退款 | 管理员 `/api/admin/unlocks/<id>/refund`，同时冲回作者分成 | 已实现 |
| 兑换码 | `redeem_codes` 有次数上限和过期时间，每人每码一次 | 已实现 |
| 赞赏 `/api/interactions/tip`（作品、社区资源） | 赞赏 1–50 积分（前端固定 2），全额转给作者，流水 `tip_out` / `tip_in`；不能赞赏自己。作者账号已不存在时只扣不入（现在只有已删除账号的作品与社区资源会遇到） | 已实现 |
| 赞赏官方资源（#24） | 官方画风、图型（catalog.json、`official_override`、`exclusive`）也可以赞赏。积分**不销毁**，入账给 `economy.official_tip_payee` 配置的超管账号，流水 `tip_official_out` / `tip_official_in`，与社区作者收入分开统计。未配置收款人、账号不存在或已停用时**拒绝赞赏**（400 `official_tips_disabled`），不静默扣分；收款人本人不能赞赏官方资源。前端文案不写「给 @作者」，确认框写明「入账官方运营账户」 | 已实现（`78bb703`） |
| 现金充值 `/api/wallet/recharge` | 仓库内没有支付渠道和回调。只有演示模式且 `HANDRAW_ENABLE_RECHARGE=1` 时可用，否则返回 503 `payment_disabled` | 未实现 |
| 荣誉等级 | 按已发布作品与资源数分 5 档（`CREATOR_HONOR_TIERS`），只显示徽章，不再影响排序 | 已实现 |

## 6. 已知缺口与待定事项

| 项 | 现状 | 依据 |
|---|---|---|
| 帖子页作为唯一详情页 | 创始人已决定，`forum-resources.js` 的资源详情视图仍在；`publish_work_direct` 返回的回执 `url` 仍是 `/forum/?view=resource&kind=work&id=` | `curation.py:1978`、`forum-app.js:210` |
| 作品双人审核进精选 | 未实现 | design-v1 决策 5 |
| 关注、楼中楼、自由标签 | 未实现，有意不做 | design-v1 决策 8 |
| 官方资源评论 `asset_comments` 收敛 | 新评论已统一写 `forum_replies`；历史数据由 `ops/converge_asset_comments.py` 迁移，生产是否执行：待核实 | `resource_discussions.py` |
| 浏览数 | `views` 列保留但冻结，不写入、不展示 | design-v1 决策 2 |
| 签到重置免费额度 | 签到会把当日 `free_quota_used` 清零，用户用完 3 张后签到可再得 3 张。是否为设计意图：待核实 | `services.py:2067` |
| `allow_self_review_for_admin` | design-v1 要求新安装默认改为 `False`，`seed.py:74` 仍为 `True` | `seed.py:74` |
| 公告文案 | 默认公告仍写「72h 首发曝光席」，热门排序已移除首发加分 | `seed.py:66`、`ranking.py` |
| 现金充值 | 未接支付 | `runtime_policy.recharge_enabled` |
| 资源推荐排序（#24 的目标） | 评价信号已经能记录，但还不能用于排序：① `ranking.asset_popular_score` 只按引用作品数（`usageCount`）排；② 榜单 `shared.js getRankedAssets` 另写了一套公式（引用数 ×36 + `cheers` ×1.1 + 来源加分 + 荣誉 `boost`），与「排序只有一个实现」「荣誉不影响排序」矛盾；③ boot 不下发官方资源的印章与赞赏聚合值，前端拿到的官方资源 `cheers` 恒为 0；④ 社区资源的 `cheers` 列混入了打赏（每次 +3），与官方资源按 interaction 计数的口径不同；⑤ 没有资源的 SQL 排序表达式与索引。需要：一个资源热门公式（写入 `ranking.py`，并与前端 `popularScore` 做一致性测试）、boot 或排序接口按编号下发统一口径的聚合计数、删除 `getRankedAssets` 中的荣誉与来源加分 | `ranking.py:74`、`shared.js:1670`、`services.py:1873` |
