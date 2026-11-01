# Handraw Web 架构设计

| 项 | 值 |
|---|---|
| 最后更新 | 2026-11-01 |
| 适用版本 | `integration` 分支 `183a711`（事实核对基于 `501a1f9`，并已核对 `183a711` 的收录封面改动） |
| 姊妹文档 | [`product.md`](product.md)、[`database.md`](database.md) |

**与历史文档的关系**：`architecture/decisions-20261029.md`（D-01…D-03）、`architecture/design-v1-20261029.md`（决策 1–10）、`single-backend.md`、`implementation.md` 等记录了决策当时的理由与方案，只作留档。当前结构以本文为准；本文与代码冲突时以代码为准。

## 1. 总体分层

```text
浏览器（4 个 HTML 页面 + demo/assets/*.js，无构建）      Skill 客户端（hwt_ 令牌）
                    │  HTTP，同源 Cookie / Bearer                  │
                    ▼                                              ▼
┌──────────────── HTTP 层  backend/server.py ─────────────────────────────────┐
│ HandrawRequestHandler：鉴权 → 令牌 scope → 写请求 Origin 校验 → 路由分发      │
│ 路由模块：post_routes · forum_resource_routes · curation_routes · features   │
│          device_auth_routes · user_library · recipe_routes                   │
│          fission_routes · batch_plan_routes · article_plan_routes            │
└──────────────────────────────────────────────────────────────────────────────┘
                    ▼
┌──────────────── 服务层 ──────────────────────────────────────────────────────┐
│ services（认证、boot、经济、作品、论坛、创作台）· admin_services（RBAC、治理）│
│ curation · resource_discussions · forum_resources · ranking · user_library   │
│ device_auth · document_importer / parser / structure · skill_prompt         │
│ media_dims（本站媒体尺寸读取，用于收录封面校验）                             │
│ ai_client（文本模型） · runtime_policy（安全策略） · security（密码、会话）   │
└──────────────────────────────────────────────────────────────────────────────┘
                    ▼
┌──────────────── 数据层  backend/db.py ───────────────────────────────────────┐
│ Database：线程本地连接，WAL，_write_lock + BEGIN IMMEDIATE；migrations 注册表 │
└──────────────────────────────────────────────────────────────────────────────┘
                    ▼
  SQLite（.local/handraw_v2.db）   文件：.local/uploads、.local/demo_generated
  外部：生图网关（image-service.json）、文本模型（ai-service.json）、
        Skill 仓库 E:\handraw-style（画风、图型引用文件与示例图）
```

HTTP、数据库、外部调用都用标准库：`http.server.ThreadingHTTPServer`、`sqlite3`、`http.client` / `urllib`。第三方依赖见 `requirements.txt`：Pillow（图片校验、缩略图）、python-docx 与 PyMuPDF（文档导入，缺失时该格式解析失败）。

## 2. 进程与入口

`python -m backend.server [--port 3080] [--host] [--db] [--reset-db] [--demo-mode]`，`main()` 依次执行：

1. `init_database`：`Database.migrate()` → `ensure_seeded` → `mark_legacy_imports_failed`。
2. `create_channel_server(port, "main", db)`：一个监听端口；同时创建文档导入管理器 `get_import_manager(db)`。
3. 启动后台线程：`GenerationReconciler`（默认每 15 秒，`HANDRAW_RECONCILE_INTERVAL`）、`start_blackbox_backfill`。
4. `serve_forever()`。

`create_channel_server(port, role, db)` 的 `role` 参数（`main` / `studio` / `forum` / `admin`）只在测试或本地多端口时使用；生产只起 `main`，按 Host 选页面：

| 条件 | 返回页面 |
|---|---|
| Host 以 `admin.` 开头，或路径 `/admin/` | `admin.html` |
| Host 以 `studio.` 开头，或路径 `/studio/` | `studio.html` |
| Host 以 `forum.` / `bbs.` 开头，或路径 `/forum/` | `forum.html` |
| 其他 | `index.html`（服务端注入 SEO 信息） |

无扩展名的未知路径回退到对应页面（前端路由）；`/api/*` 未命中返回 JSON 404，不回退到页面。

绑定地址默认 `127.0.0.1`；`0.0.0.0` / `::` 需要 `HANDRAW_ALLOW_PUBLIC_BIND=1`，否则降级到本机。生产在 nginx 之后（`ops/nginx-handraw-v2.conf.example`）。
## 3. 请求流转

### 3.1 通用前置

```text
do_GET / do_POST / do_PUT / do_DELETE
  ├─ _enforce_token_scope()      hwt_ 令牌只能访问白名单接口，否则 403 token_scope_denied
  ├─ _enforce_write_origin()     写请求（POST/PUT/DELETE）：带 Cookie 时 Origin 或 Referer 必须在
  │                              trusted_origins()；带 Authorization / X-Handraw-Token 时可省略
  ├─ _read_json_body()           上限 20 MB
  └─ 路由；ServiceError → {"ok":false,"error","code"} + 对应状态码；其他异常 → 500
```

鉴权（`services.authenticate_request`，每请求缓存一次）：

| 优先级 | 凭证 | 结果 |
|---|---|---|
| 1 | `Authorization: Bearer hwt_…` 或 `X-Handraw-Token` | 查 `api_tokens.token_hash`（SHA-256），`_auth_kind="token"`，带 scope |
| 2 | 同上但不是 `hwt_` 前缀 | 当作会话令牌查 `sessions`，scope `*` |
| 3 | Cookie `handraw_sid` | 查 `sessions`；只在没有上述头时才看 Cookie |

令牌 scope 白名单（`server._enforce_token_scope`）：任何令牌可 `GET /api/auth/me`；`publish` 可 `POST /api/uploads`、`/api/studio/uploads`；`library` 可读写 `/api/library/assets*`、`/api/skill/library` 与 `POST /api/collections/toggle`。`POST /api/entries`、`POST /api/works`（作品分享）不在白名单内，用 `hwt_` 令牌调用会返回 403；契约测试 `tests/test_work_publish_contract.py` 只用会话 Cookie 覆盖。Skill 分享走哪种凭证：待核实。

认证接口限流：进程内令牌桶，按 `_client_ip()`（只在来自本机反代时信任 `X-Real-IP` / `X-Forwarded-For`）。演示模式下关闭。

### 3.2 GET 分发顺序（`_handle_get`）

1. `post_routes`（`/api/posts/*`、`/t/<ref>`）→ `forum_resource_routes` → `curation_routes` → `features` → `device_auth_routes` → `user_library`
2. `/robots.txt`、`/sitemap.xml`、`/favicon.ico`、`/api/health`、`/api/boot`、其他 `/api/*` 内联分支
3. 静态数据 `/data/catalog.json`、`/data/options.json`（读 `plugin/content/`，替换 CDN 域名后缓存在内存）
4. 媒体 `/images/`（Skill 图片目录，公开缓存）、`/uploads/`、`/generated/`（逐次检查归属或公开授权 `media_public_grants`）；`?w=` 返回缩略图
5. 未命中的 `/api/*` → JSON 404
6. 页面与 `demo/` 下静态文件（路径越界返回 403）

POST 顺序相同：`forum_resource_routes` → `curation_routes` → `features` → `device_auth_routes` → `user_library` → `server.py` 内联分支。各路由模块用 `try: import … except ImportError` 加载，缺失时等于无此路由。

### 3.3 示例：生图 `POST /api/studio/generate`

```text
server._handle_post
  ├─ 未配置 image-service.json 且非模拟 → 503
  ├─ prepare_cloud_generation(db, user, body)                 [事务 1，持写锁]
  │    幂等：同 (user_id, request_id) 已存在 → 返回原记录
  │    检查在途数 ≤ max_inflight_per_user；读资源专属指令；扣免费额度或积分
  │    INSERT studio_generations(status=running, prompt_ready=0) + quota reservation
  ├─ _compose_skill_prompt → skill_prompt.compose_prompt     [无锁，可能调用文本模型]
  ├─ 写入最终 prompt / visible_prompt，prompt_ready=1          [事务 2]
  ├─ claim_cloud_generation_submission                        [事务 3] running → queued，只有一个请求能抢到
  ├─ gateway_request("/api/image-tasks/generations" 或 "/edits", timeout=28)   [无锁]
  ├─ complete_cloud_generation(gen_id, task_id)               [事务 4] 记录上游 task_id
  └─ 异常 → refund_failed_cloud_generation（退额度或积分，status=refunded）

后台 GenerationReconciler（每 15 秒）
  ├─ prompt_ready=0 超过 10 分钟的行强制置 1
  ├─ run_blackbox_backfill
  └─ 对 queued/running 的 live 任务查 /api/image-tasks?ids=…
       成功 → 下载图片到 .local/demo_generated → complete_cloud_generation(…, urls)
       明确失败 → refund；网络错误或未知 → 保持原状，下轮再查
```

前端用 `GET /api/studio/tasks` 轮询任务状态。
### 3.4 文本模型与 Skill 提示词

| 组件 | 职责 |
|---|---|
| `ai_client.chat(messages, json_mode, timeout)` | OpenAI 兼容 `/chat/completions`；配置读 `ai-service.json`（`HANDRAW_AI_CONFIG`），缺失时读 `HANDRAW_AI_URL/KEY/MODEL`，默认模型 `deepseek-v4.1-flash`；不走代理；响应上限 2 MB；只重试一次；不记录正文与密钥 |
| `fission_routes` / `batch_plan_routes` / `article_plan_routes` | 选题裂变、套图规划、文章配图规划；未配置模型时返回模板结果；`daily_usage` 限额；禁止 `hwt_` 令牌调用 |
| `skill_prompt.compose_prompt` | 读 Skill 仓库 `references/`，用文本模型组装生图提示词；无模型时用确定性模板 |
| `document_parser` / `document_structure` / `document_importer` | 文档解析（txt / md / docx / pdf）与异步导入队列 |

### 3.5 隐私：资源专属指令

资源专属指令（`catalog_assets.secret_blackbox_prompt`，后台称「黑盒提示词」）在生图时由服务端追加到提示词，绝不返回浏览器。

| 环节 | 机制 |
|---|---|
| 写入时判定 | `check_text_has_secret(text)`：文本包含任一专属指令全文，或其中任意连续 20 字，即判为含密；查询专属指令失败时抛 `SecretsScanError`，按含密处理 |
| 结果落库 | `works.prompt_has_secret`、`forum_topics.recipe_has_secret`、`studio_generations.visible_prompt` / `prompt_masked` |
| 读取时 | `get_work_client_prompt`、`get_topic_client_recipe_json`、`get_generation_visible_prompt`：只看落库标志，不再扫描；NULL 一律隐藏 |
| 补齐历史行 | `run_blackbox_backfill`，每批 200 行，专属指令集合变化时重扫生成记录 |
| 后台例外 | `is_admin_route=True` 时返回原文 |

## 4. 数据层与并发模型

| 项 | 实现（`backend/db.py`） |
|---|---|
| 连接 | 每线程一个 `sqlite3` 连接（`threading.local`），`isolation_level=None`（手动事务），`check_same_thread=False` |
| PRAGMA | `journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`、`busy_timeout=10000` |
| 写 | `db.transaction()`：进程级 `threading.RLock`（`_write_lock`）+ `BEGIN IMMEDIATE`，异常回滚 |
| 读 | `db.get_conn().execute(...)`，不加锁；WAL 下读不阻塞写 |
| 迁移 | `migrate()` 持写锁；每条迁移的 DDL 与 `schema_migrations` 记录拼成一个 `BEGIN IMMEDIATE … COMMIT` 脚本执行 |

约定：

- **外部调用不持锁**。生图网关、文本模型、文件下载都放在事务之外，用状态列（`prompt_ready`、`status`）衔接前后两个事务。
- **GET 不写库**。有记录的例外：`api_tokens.last_used_at`（每 5 分钟最多一次）、图库读时回填（拿不到写锁就跳过）。
- **幂等靠唯一索引**，不靠应用层先查后写（见 `database.md` §4.1）。
- 写锁是进程内锁，只在单进程部署下成立。多进程或多机部署需要重新设计（见 §8）。

后台线程：

| 线程 | 周期 | 工作 |
|---|---|---|
| `GenerationReconciler` | 15 秒（5–120 可调） | 对账生图任务、补 `prompt_ready`、黑盒回填 |
| `start_blackbox_backfill` | 启动时一次 | 黑盒回填 |
| 文档导入管理器 | 队列驱动 | 导入任务；看门狗把超时任务置 `failed`；约每小时清理 24 小时未引用的导入图与 30 天墓碑 |
## 5. 前端架构

### 5.1 页面与脚本

无构建步骤：原生 JS（IIFE，挂到 `window`）+ `<script src="/assets/x.js?v=N">`，靠 `?v=` 手动换缓存。`demo/assets/` 下 18 个 JS、10 个 CSS。

| 页面 | 加载顺序 |
|---|---|
| `index.html` | mock-data → image-loader → shared → account-tools → device-auth → discovery → works-browser → main-app |
| `studio.html` | mock-data → image-loader → shared → account-tools → studio-prompt-engine → quick-create → studio-make-image → studio-batch → studio-app |
| `forum.html` | mock-data → image-loader → shared → account-tools → curation-ui → forum-work-post → forum-resources → forum-app |
| `admin.html` | 只有 admin-app（自行请求 `/api/boot`，不用 `shared.js`） |

| 模块 | 行数 | 职责 |
|---|---|---|
| `shared.js` | 3780 | `App` 状态、`initApp`、`apiJson`、资源索引、`popularScore`、通用组件 |
| `studio-app.js` | 15237 | 创作台主控：模式切换、画布、历史、文章配图 |
| `studio-prompt-engine.js` | 2425 | 节点图 → 提示词（`assembleControlPrompt`）、蓝图 |
| `studio-make-image.js` / `studio-batch.js` | 1175 / 2037 | 做图、批量模式 |
| `forum-app.js` / `main-app.js` / `admin-app.js` | 3648 / 2903 / 2931 | 各页面主控 |
| `image-loader.js` | 267 | 懒加载队列（同时最多 2 张、错误后暂停） |
| `mock-data.js` | 1362 | 仅 `?demo_mode=1` 时使用的演示数据 |

### 5.2 启动与状态

`S.initApp(channel, onChange)`（`shared.js:668`）并行请求三个资源：

| 请求 | 内容 | 缓存 |
|---|---|---|
| `/data/catalog.json` | 官方画风、图型静态目录 | `public, max-age=300` |
| `/data/options.json` | 创作台选项（比例、情绪、影调等） | 同上 |
| `/api/boot` | `build_boot_payload` 生成的完整状态 | 不缓存 |

boot 载荷（`version: 4`）主要字段：`serverBacked`、`loggedIn`、`user`（含 `reviewAccess`、管理角色与能力）、`credits` / `freeQuotaRemaining` / `freeQuotaMax` / `dailyCheckedIn`、`collections`、`unlockedIds`、`cheeredIds`、`likedIds`、`works`、`topics`（含回复与投稿）、`forumBoards`、`forumModerators`、`exclusiveResources` / `communityResources` / `officialOverrides`、`officialPresets`、`assetCounts`、`assetComments`、`ledger`、`siteSettings`（只含 announcement 与 economy）。

- 写操作调用具体接口后，用响应局部更新 `App.state`，或调用 `refreshFromServer()` 重新拉取 boot。
- `serverBacked=false` 时只有 URL 带 `?demo_mode=1` 才回退到 `mock-data.js`，否则显示启动错误并提供重试。

### 5.3 无构建的取舍

| 收益 | 代价 |
|---|---|
| 部署只复制文件；服务端直接托管 `demo/` | 没有模块系统，依赖靠 `<script>` 顺序和全局变量 |
| 改完刷新即生效，排查不需要 source map | 没有类型检查和打包期死代码检查；`studio-app.js` 1.5 万行 |
| 没有 Node 构建链需要维护 | 缓存靠手改 `?v=`，漏改会让用户拿到旧脚本 |
| Node 测试可直接 `require` 部分模块（`tests/*.cjs`） | 浏览器行为需要 Playwright 另测 |
## 6. 关键设计决策

| 决策 | 内容 | 理由 | 来源 |
|---|---|---|---|
| 单后端按 Host 分发 | 一个端口服务四个页面，规范地址用主域名加路径 | 同域一份登录 Cookie、一份搜索收录；部署只有一个进程 | `single-backend.md`、design-v1 决策 10 |
| 作品只有一个身份 | `works.id` 是作品主键；帖子只是讨论区，经 `curation_resource_topics` 映射，不加 `works.topic_id` | 该映射表已被评论、资源详情、boot 共同读取，再加一份映射会出现两个事实来源 | D-01、design-v1 决策 1 |
| 作品即时发布 | 审核只用于画风、图型进入官方目录 | 消除「论坛已发、广场没有」的不一致；内容安全靠举报阈值与巡查 | D-02 |
| Skill 新契约，无旧接口兼容层 | 不模仿 Discourse 形状的接口；`/api/entries` 只做 Skill 载荷到作品发布的格式转换 | Skill 未发布，无存量用户 | D-03 |
| 评论统一存 `forum_replies` | `origin='submission'` 表示评论在 `forum_replies`；旧表只读 | 沿用已有枚举值，代码回滚后旧代码仍按 `origin` 读到正确的表 | design-v1 决策 4 |
| 排序只有一个实现 | `ranking.py` + 前端 `popularScore`，无时间衰减；复刻权重由设计的 3 降为 1 | 结果可解释、可用表达式索引；复刻可用免费额度刷出来 | design-v1 决策 3、`ranking.py` 注释 |
| 浏览数冻结 | `views` 列保留，不写不读 | 匿名访客无法可信去重；与「GET 不写库」冲突 | design-v1 决策 2 |
| 版块用常量 | `FORUM_BOARDS`，不建表 | 只有 6 个版块；超过 10 个或需要免发版新增时再建表 | design-v1 决策 7 |
| 迁移只加不减、不回滚 | 加表、加列、加索引；改语义时冻结旧列 | 代码可随时回滚到旧提交而不动库 | AGENTS.md |
| 外部调用不持锁、对账不重提 | 生图提交与网关调用拆成多个短事务；对账线程只查询，不重新提交 | 防止网关慢时阻塞全站写入；防止重试变成免费重复任务 | `GenerationReconciler` 文档 |
| 专属指令失败即隐藏 | 扫描失败、标志为 NULL 都按含密处理 | 漏掉一次就会泄露付费内容 | `services.check_text_has_secret` |

## 7. 扩展点

### 7.1 新增 API

1. 选模块：同一领域已有 `*_routes.py` 就加到其 `handle_get` / `handle_post`（返回 `True` 表示已处理）；否则在 `server.py` 对应方法中加分支，放在 `/api/*` 404 兜底之前。
2. 鉴权：`user = handler._current_user(required=True)`；角色判断复用 `admin_services.get_management_profile` 的 `capabilities`，不要另写角色字符串比较。
3. 写库：放进 `with db.transaction() as tx:`；外部调用放在事务外。
4. 错误：抛 `ServiceError(message, status=, code=)`，由分发层统一转成 JSON。
5. 幂等：可重试的写接口接收 `requestId`，用部分唯一索引保证。
6. 令牌：需要 Skill 访问时，在 `_enforce_token_scope` 加白名单并选定 scope。
7. 测试：`tests/` 下用临时库（`HANDRAW_DB_PATH` 或 `Database(tmp)`），不连项目库。

### 7.2 新增迁移

1. 在 `work_schema.py` 定义 SQL 常量，追加到 `WORK_MIGRATIONS` 末尾，版本号 67 起，名称匹配 `^[0-9]{3}_[a-z0-9_]+$`。
2. 只用 `CREATE … IF NOT EXISTS`、`ALTER TABLE … ADD COLUMN … DEFAULT`。SQLite 的 `ADD COLUMN` 没有 `IF NOT EXISTS`，靠迁移原子性保证不重复执行。
3. 需要 Python 处理数据时，DDL 写 `SELECT 1;`，函数登记到 `WORK_POST_MIGRATION_HOOKS`，必须幂等。
4. 用旧结构的库和空库各跑一次测试；更新 `database.md`。

### 7.3 新增前端页面

1. 新建 `demo/<page>.html`，按现有顺序引入 `shared.js`，调用 `S.initApp("<channel>", onChange)`。
2. 在 `server._handle_get` 的页面选择处加路径 `/<page>/`；需要子域名时加 Host 前缀判断，并把 `https://<sub>.handraw-style.com` 加入 `runtime_policy.trusted_origins` 默认值或部署环境的 `HANDRAW_ALLOWED_ORIGINS`。
3. 新脚本带 `?v=1`，之后每次修改递增。

### 7.4 检查命令

```bash
python -m pytest -q                              # 或 python -m unittest discover -s tests
for f in tests/*.cjs; do node "$f" || exit 1; done
```

## 8. 已知技术债与风险

| # | 问题 | 影响 | 位置 |
|---|---|---|---|
| 1 | 写锁是进程内 `RLock` | 只能单进程部署；多进程时互斥只剩 SQLite 的 `BEGIN IMMEDIATE` + `busy_timeout` | `db.py:33` |
| 2 | boot 一次下发全部已发布作品、帖子、回复、目录覆盖层，无分页 | 每次打开页面的耗时与载荷随内容量线性增长 | `services.build_boot_payload` |
| 3 | 超大文件 | `studio-app.js` 15237 行、`services.py` 4752 行、`server.py` 3299 行、`admin_services.py` 3010 行；改动冲突多、审查难 | — |
| 4 | 路由是长 if 链，模块路由用 `except ImportError` 静默降级 | 模块内部任何 ImportError 都会让整组接口变成 404，而不是启动失败 | `server._handle_get` / `_handle_post` |
| 5 | 同步提交生图时，任何异常（含 28 秒超时）立即退款 | 与对账线程「未知状态不退款」原则不一致；上游已受理的任务会变成免费成图或丢图 | `server.py:3013-3017` |
| 6 | 收入通知触发器的 `kind` 列表与实际流水不符 | 解锁分成、赞赏、悬赏奖金无通知 | `feature_schema.py:62`，见 `database.md` §5 |
| 7 | `sessions.token` 明文存库 | 数据库泄露即可冒用会话；`api_tokens` 已做哈希 | `services.py:418` |
| 8 | 迁移后钩子在提交之后执行 | 钩子失败时版本已记为完成，不会自动重跑 | `db.py:146` |
| 9 | 角色判断写法不一致 | `prepare_cloud_generation` 只认 `admin` / `reviewer`，`operator` 不算员工；`post_routes` 认三者 | `services.py:3920`、`post_routes.py:24` |
| 10 | 限流与令牌频率计数都在内存 | 重启清零；多进程不共享 | `runtime_policy._AUTH_LIMITERS`、`user_library` |
| 11 | 外部目录默认值是 Windows 绝对路径 | 新环境必须设置 `HANDRAW_STYLE_IMAGES_DIR`、`HANDRAW_STYLE_SKILL_DIR`、`HANDRAW_STYLE_REFS_DIR` | `config.py`、`skill_paths.py` |
| 12 | 各环境的 `schema_migrations` 不一致 | `main` 工作区未提交的 `curation_schema.py` 会登记 030 / 031；本分支不认识这两个版本（DDL 均为 IF NOT EXISTS，暂无冲突） | `migrations.py:525` |
| 13 | 作品回执地址仍指向待移除的资源详情视图 | 移除视图后 Skill 回执链接失效 | `curation.py:1978` |
