# 终审报告：作品对象统一 v1 实施（2026-10-30）

评审人：Claude（架构师兼终审）。对象：`implementation-report-20261030.md` 声称完成的 B0–B7。
方法：不采信自述。在临时库上起真实服务进程，只带 `Api-Key` 调接口；直接读代码；用自己构造、手算过的夹具核对。探针全部在 `.local/review/`，在仓库根目录用 `python -X utf8 .local/review/<脚本>` 重跑：

| 脚本 | 覆盖 |
|---|---|
| `probe_migrations.py` | B0 原子性；B2 字段与索引、两次 migrate、真实库副本 |
| `probe_b1.py` | 种子互动、首次点赞、送鼓励、印章 |
| `probe_ranking.py` + `probe_ranking.cjs` | B4 三处实现与手算对照（JS 侧加载 `shared.js` 里的真函数） |
| `e2e_probe.py`、`e2e_followup.py` | 起服务；注册、上传、发布、点赞、评论、审核、并发、skill 真实载荷 |
| `probe_b7.py` | 评论收敛的通知、隐藏评论、非全新状态重跑 |
| `probe_honor.py` | 首件作品的荣誉升级奖励 |

## 0. 结论

**不能接受。** B0 合格；B1、B2 有缺项；B3–B7 不合格。最严重的三处：skill 实际发出的载荷被新后端以 400 拒绝（报告称"端到端跑通"）；网站自己的作品发布界面仍走审核，"论坛已发布、广场不存在"可以原样复现；复刻数可以由客户端伪造，作者也能给自己刷。

测试数字与报告一致，但规格 §6 点名的验收测试文件一个都不存在；新测试多处没有测到生产代码路径；一处既有断言被改弱，掩盖了一个奖励回归。

## 1. 测试真实数字

| 套件 | 命令 | 结果 | 报告所称 |
|---|---|---|---|
| 网站 Python | `python -m pytest -q` | 113 passed, 11 subtests passed | 113 / 11，属实 |
| 网站 Python（G2 规定命令） | `python -m unittest discover -s tests` | Ran 113, OK | — |
| 前端 | 逐个 `node tests/*.cjs` | 16/16 退出码 0 | 16/16，属实 |
| skill | `python -m pytest skills/community-share/tests -q` | 30 passed | 30，属实 |

数字属实，问题在测试测了什么，见 §3、§7。

## 2. 逐批判定

| 批 | 判定 | 关键证据 |
|---|---|---|
| B0 | **合格** | 注入"前半句成功、后半句失败"的迁移：抛错，`works.probe_a` 不存在，`probe_ok` 表不存在，版本 99 未写入；修正后重跑成功；注入式名称被拒且 `users` 仍在；含 `BEGIN…END` 的触发器迁移正常。需补 `tests/test_migration_atomicity.py` |
| B1 | **不合格（轻）** | 五处核心改动全部生效并实测通过；GET 不写库（全库逐表哈希，匿名和 `Api-Key` 各一轮，0 张表变化）。但 G6 的 grep 仍命中 `seed.py:686`；`DEFAULT_STAMP_BASES` 未删；`allow_self_review_for_admin` 默认值未改；回填脚本未写；对账脚本缺演示模式拒跑 |
| B2 | **不合格（轻）** | 040–043 存在、只增不删、第二次 migrate 为 `[]`、040 之前的真实备份迁移后四表行数不变。但 040 少了 `idx_works_popular`（规格 10 个索引，实有 9 个），报告未申报 |
| B3 | **不合格（重）** | 网站发布界面仍走审核；他人图片被静默丢弃后照常发布；空标题、3 个画风、价格 100000 都能通过，`price:"abc"` 返回 500；首件作品的荣誉升级 +10 丢失；隐藏作品后主帖仍公开；`showcase` 能直接发帖（被静默改到 experience） |
| B4 | **不合格** | 公式在三处一致，与手算吻合。但生产 SQL 和前端榜单的同分规则与规格、与 Python helper 都不同，我的夹具上排序不同；作品主帖在后端热门分里取冻结的 0；`GET /api/works` 不存在 |
| B5 | **不合格（重）** | 复刻在发布时按客户端声明的 `forkOf` 计数，不需要任何生成；作者复刻自己的作品也计数；`fork_work_id` 写入后没有代码读取 |
| B6 | **不合格（重）** | skill 真实 `work_payload` 发到 `/api/entries` 返回 400 `prompt_required`；回执仍拼 `/studio?entry=`；回读接口返回 HTML；不发 `requestId`；提示词被 `strip`。`Api-Key` 鉴权本身确实生效 |
| B7 | **不合格（中）** | 幂等成立，不补发通知成立。但只复制 `published`，隐藏评论丢失；没有审计记录和 `--revert`；没有改主帖作者与版块 |

## 3. 逐批证据与退回要求

### B0 迁移原子化：合格

- `backend/db.py:117-146`：每个迁移是一个 `BEGIN IMMEDIATE; <ddl>; INSERT schema_migrations…; COMMIT;` 脚本，失败时 `ROLLBACK`；名称正则 `db.py:21`。
- 探针结果见 §2。新库第一次 migrate 应用 13 个，第二次 `[]`。
- 要补：`tests/test_migration_atomicity.py`（§6 B0 的 4 个用例）。现在这条保证只在探针里验证过，没有回归测试保护。

### B1 数据真实性：不合格（轻）

已核实生效：
1. `backend/services.py` 已没有 `or 16`（`grep -n "or 16" backend/` 只剩 `seed.py:686`，那是演示种子的回退值）。
2. 普通发帖 INSERT 写 `views, likes, favorites = 0, 0, 0`（`services.py:1818`）。
3. 送鼓励后 `works.likes` 仍为 0，`cheers=1`，没有 `like_work` 行（`probe_b1.py`）。
4. 首次带"配方超稳"的鼓励后 `stamp_counts_json={"配方超稳":1}`，基数为 0。
5. `asset_social_seeds` 只在 `is_demo_mode()` 下读取（`services.py:1001`、`:1429`）。非演示模式 `assetSeedMetrics=={}`，对 FA-001 第一次点赞 `likes==1`；演示模式仍是 168。
6. GET 不写库：调用 `/api/boot`×3、资源详情、评论列表、`/api/works` 前后，对全库每张表做内容哈希，匿名和 `Api-Key` 两轮都没有表变化。比报告的"四表行数不变"更严。

退回要求（规格 §5 B1 列出、未做）：
- `demo/assets/shared.js:1701` 的 `DEFAULT_STAMP_BASES` 未删（已无引用，是死代码）。
- `backend/seed.py:74` 的 `allow_self_review_for_admin` 仍为 `True`。
- `ops/backfill_discussion_mappings.py` 不存在。本地库 `work_101`、`work_102` 有 3 条 `work_comments` 没有映射；删掉懒建帖之后，B7 没法收敛它们。
- `ops/reconcile_social_counters.py`：没有 `HANDRAW_DEMO_MODE=1` 时拒跑，不重算 `stamp_counts_json` 和 `catalog_assets.cheers`，不排除 `seed_ids`。备份用 `shutil.copy2`（`:128`），WAL 模式下会漏掉还在 `-wal` 文件里的页，改用 `sqlite3.Connection.backup`。
- `demo/assets/forum-app.js:1462-1464` 本地发帖对象仍写 `likes: 1, views: 1`。
- `tests/test_social_honesty.py` 不存在。

### B2 迁移 040–043：不合格（轻）

- `backend/work_schema.py`：只有 `ALTER … ADD COLUMN` 和 `CREATE … IF NOT EXISTS`。对 `work_schema.py`、`migrations.py`、`curation_schema.py`、`feature_schema.py` grep `DROP|DELETE|UPDATE|RENAME`，唯一命中是既有触发器里的 `AFTER UPDATE`，没有新增的破坏性语句，符合 AGENTS.md「数据库只增不减」。编号 40–43，无重复。
- 新库两次 migrate 第二次 `[]`。不只在全新库测：把 `.local/backups/forum-resource-before-20261029-142509.db`（版本停在 31）复制出来迁移，应用 040–043，再跑一次 `[]`，`users/works/forum_topics/forum_replies` = 40/34/35/39，迁移前后相同。
- 缺 `idx_works_popular`（规格 §3.2 040）。040 已应用到本地库，**不能改 040**，要新增 `044` 补这个索引，并在 `GET /api/works` 实现后用 `EXPLAIN QUERY PLAN` 验证命中。
- `tests/test_work_schema.py` 不存在。R5 的回滚演练（切回 B2 之前的提交跑测试）无法执行：所有改动都没有提交，见 §7。

### B3 作品即时发布：不合格（重）

成立的部分：
- `curation.publish_work_direct`（`backend/curation.py:1398-1500`）对 `POST /api/works` 和 `/api/entries` 不经审核，`status='published'`；作品行、主帖、映射在同一个 `db.transaction()` 里（`:1428-1500`）。
- id 是 UUIDv4。`requestId` 幂等：顺序重放 workId 相同，账本 `pub_work_<id>` 只有 1 条；8 个线程并发同一个 `requestId`，全部 200，`works` 只有 1 行。
- 超过 9 张图在清洗前检查（`:1414`），10 张、13 张都返回 400 `too_many_images`。
- 主帖 `category='showcase'`，`summary/locked_body/recipe_json` 都为空，不含提示词。
- 对主帖点赞或收藏会记到作品上：`works.likes=1, favorites=1`，`forum_topics` 仍是 0/0，boot 中作品和主帖都显示 1/1，`interactions` 是 `like_work` 行。
- 他人评论后 `forum_replies` +1、通知 +1。

不成立：
1. **网站发布界面仍走审核。** `demo/assets/curation-ui.js:263-278` 对 `kind='work'` 仍 POST `/api/curation/submissions`。实测这个接口返回 200，生成 `pending` 投稿和论坛帖，`works` 行数为 0，"论坛已发布、广场不存在"原样复现。`backend/curation.py` 没有 `work_publish_moved`；`tests/test_v2_curation.py:47-67` 仍把作品走两票审核当正确行为在测。前端没有任何地方调用 `POST /api/works`，只改了后端。
   改法：按规格 §5 B3 前端条目改 `curation-ui.js`；`_parse_items` 遇到 `kind='work'` 返回 400 `work_publish_moved`；按 §6「需要修改的既有用例」改测试。
2. **他人图片被静默丢弃。** `backend/server.py:677-678`、`:687-688` 遇到他人的 `/uploads/` 地址直接 `continue`，`:667` 再截到 12 张。实测 `[自己的图, bob 的图]` 返回 200，作品只剩 1 张图。规格要求 403 `media_not_owned`；§7.3 把"以丢弃代替报错"列为直接不合格。
3. **校验缺失**（`curation.py:1407-1424`）：空标题默认成"社区作品"，1 个字的标题也通过（规格 4–160）；3 个画风原样存入（规格最多 2 个）；`price:100000` 被接受（规格 0–100）；`price:"abc"` 因 `int()`（`:1479`）返回 **500**（违反 G5）；20050 字的提示词被静默截到 20000（`_s` 截断，违反 G7）。错误码与 §4.1 不一致：`prompt_required`、`image_required`，不存在的画风返回 `bad_request`，应为 `missing_prompt`、`missing_image`、`asset_not_found`。
4. **首件作品的荣誉升级奖励丢失。** `_reward_direct_work`（`curation.py:1529`）在作品 INSERT 之后才算 `before_count`，所以 `before_honor == after_honor`，升级奖励永远不触发。实测新用户首件作品的账本只有 `publish_work +15`，没有 `honor_upgrade`。报告称"奖励与荣誉升级照常发放"，不属实。另外这段逻辑是复制的，没有按规格抽成与审核路径共用的 `apply_work_publish_rewards`。
5. **审核不联动主帖。** 管理员 `hide` 后，`works.status='hidden'`，详情 404，主帖仍是 `published`（违反 R11）。`admin_services.py:825-839` 只改 `works`；`set_work_visibility` 不存在。
6. **`showcase` 能直接发帖。** `POST /api/forum/topics {category:'showcase'}` 返回 200，帖子被静默改成 `experience`（`services.py:1729-1736` 的 `cat_map` 没有 showcase）。规格要求 400 `use_work_publish`，并让 `cat_map` 改读 `FORUM_BOARD_LABELS`。
7. **没有发布频率限制，也没有每日奖励上限**：`work_publish_daily_limit`、`work_reward_daily_cap` 在代码里都搜不到（规格 §4.1 第 3、8 步）。
8. **回执与规格不一致**（`curation.py:1635-1645`）：`url` 是相对路径（规格要求绝对地址，读 `HANDRAW_PUBLIC_ORIGIN`）；字段叫 `reward` 而不是 `rewarded`；缺 `path`、`pioneer`、`upgradedBadge`。
9. 规格列出的 `backend/works.py`、`THREAD_ORIGINS`、`primary_work_for_topic/primary_work_map`、`GET /api/works`、`GET /api/account/me` 都不存在。未知的 `GET /api/*` 一律返回 200 的页面 HTML，所以从状态码看不出接口缺失。主帖版块名在 `curation.py:1590` 写死为 `'🎨 晒作品'`，没有读常量。
10. 付费作品：匿名 boot 的 `works[].prompt` 带着提示词前 34 个字（`services.py:607`），违反 G8。这是既有行为，但 B3 让付费作品即时公开，影响面变大，必须在本批一起处理。

### B4 排序统一：不合格

我的夹具（`probe_ranking.py`），手算 `likes + cheers + 2*favorites + 3*forks`：

| 作品 | likes | cheers | fav | forks | 手算 | published_at_ms |
|---|---|---|---|---|---|---|
| w_b | 0 | 0 | 0 | 4 | 0+0+0+12 = **12** | 900 |
| w_c | 11 | 0 | 0 | 0 | **11** | 2000 |
| w_a | 3 | 1 | 2 | 1 | 3+1+4+3 = **11** | 1000 |
| w_d | 1 | 6 | 2 | 0 | 1+6+4+0 = **11** | 1000 |
| w_e | 0 | 0 | 0 | 0 | **0** | 3000 |

规格顺序（分数降序、`published_at_ms` 降序、`id` 升序）：`w_b, w_c, w_a, w_d, w_e`。

| 实现 | 分数 | 顺序 | 结论 |
|---|---|---|---|
| `ranking.work_popular_score` / `sort_works` | 与手算一致 | `w_b, w_c, w_a, w_d, w_e` | 正确 |
| `shared.js` 的 `popularScore`（从文件里取出真函数） | 与手算一致 | — | 正确 |
| 生产 SQL `forum_resources._sql_page`（`:337-338`） | — | `w_b, w_a, w_c, w_d, w_e` | **错**：同分时只按 `id ASC` |
| 前端 `getRankedWorks`（`shared.js:1646`） | — | `w_b, w_a, w_c, w_d, w_e` | **错**：没有同分规则 |

- 公式本身三处一致，但 SQL、Python、JS 的排序结果不一致。
- 作品主帖：作品 likes=5、主帖冻结列为 0 时，后端 `topic_popular_sql` 算 **0**（读 `t.likes`），前端用 boot 覆盖后的值算 **5**。违反规格「作品主帖的 likes 和 favorites 取作品的值」。
- `tests/test_ranking.py:71-72` 的"一致性测试"自己写了一条 `ORDER BY score DESC, id ASC`，没调用生产查询，夹具的 `published_at_ms` 全是 1000，同分规则不可能测出来。`tests/test_works_browser.cjs:12-17` 自己写了一份 `popularScore` 桩，没有加载 `shared.js`，前后端一致性实际没被测过。
- `GET /api/works` 不存在，规格的 `test_bad_sort_rejected`、`test_period_filter` 没有对象可测。
- 残留：`main-app.js:676`、`:1340` 仍有"🆕 新发扶持"，`:613` 等处渲染空的 `boostText` 胶囊。
- 退回：生产 SQL 和 `getRankedWorks` 补 `published_at_ms DESC`；主帖热门分在 SQL 里关联作品计数；按 §6 B4 建 `tests/fixtures/ranking_cases.json` 和 `tests/test_ranking_parity.cjs`（加载 `shared.js` 本体）；Python 一致性测试改为调用 `_sql_page` 和 `GET /api/works`。

### B5 复刻：不合格（重）

- 成立：`work_forks` 是事实表，主键 `(work_id, user_id)`；`works.forks` 用 `COUNT(*)` 重算（`curation.py:1503-1516`）；同一用户重复复刻只计一次。
- 计数时机与规格不符。规格：带 `forkOf` 的生成成功、产出真实图片时计数，排除作者本人。实现：**发布作品时**读请求体里客户端给的 `forkOf` 计数（`curation.py:1449-1492`），不要求有过生成，也不排除作者。
  - 实测：作者带 `forkOf=<自己的作品>` 发布，自己作品的 `forks` 0→1；另一个用户随便传一张自己的图加 `forkOf` 发布，`forks`→2。任何账号都能给任意作品 +3 热门分（复刻权重 3），作者也能给自己刷。
- `prepare_cloud_generation` 把未校验的 `forkOf` 写进 `fork_work_id`（`services.py:2697`），但 `complete_cloud_generation` 不读它。`demo/assets/studio-app.js` 的生成请求不带 `forkOf`。`related?tab=forks` 返回 400。`generationId` 也是客户端给的值（`curation.py:1492`）。
- `tests/test_work_forks.py` 把"发布时声明即计数"当作正确行为在测，§6 B5 的 8 个用例一个都没有。
- 退回：发布路径不再接受客户端 `forkOf` 计数；在 `complete_cloud_generation` 按 §4.4 记账；`forked_from_id` 从首图所属生成的 `fork_work_id` 推导；排除作者本人。

### B6 skill 契约：不合格（重）

成立：
- `POST /api/entries` 存在（`backend/server.py:2210-2229`），返回 `{ok, id, kind:"work", topicId, url, status}`。
- **`Api-Key` 鉴权在新后端生效**：起真实服务，只带 `Api-Key: hwk_…`，不带 Origin 和 Cookie，`/api/boot` 返回该用户，上传和发布都是 200；错误的 Key 得到访客身份；冻结账号发布返回 401（`services.py:286-297`）。
- 新格式的 `entry` 落库 `works.origin='skill'`。
- skill 仓库 `git status --porcelain` 只改了 4 个文件：`SKILL.md`、`references/conversation-sharing.md`、`scripts/conversation_share.py`、`tests/test_conversation_share.py`。提示词生成部分没有动。`plugin/` 无改动。

不成立：
1. **skill 真实发出的载荷被拒。** `conversation_share.work_payload`（`conversation_share.py:136-149`）没改，仍发 `{kind, cover_url, content:{prompt, parameters, examples}, assets:[{ref, role}]}`。`_entry_to_work_body`（`server.py:702-738`）只读 `entry.prompt/images/styleIds/layoutId`。用 skill 自己的 `work_payload` 生成载荷发到 `share.WORK_ENDPOINT`，实测 **400 `prompt_required`**。同一个 skill 的 `references/conversation-sharing.md` 描述的却是 `title/prompt/images/styleIds/layoutId/requestId`，文档和脚本不一致。
2. 回执仍是 `f"{BASE_URL}/studio?entry={entry_id}"`（`conversation_share.py:400`），没用服务端返回的 `url`。
3. 回读仍调 `/api/entries/<id>` 和 `/content`（`:317-321`），新后端对这两个地址返回 200 的页面 HTML，`json.loads` 失败后被 `except Exception: pass`（`:412-413`）吞掉，`verified` 永远是 `False`。
4. 不发 `requestId`。5xx 仍按"结果不明，阻止重发"处理（`:258-259`），规格要求用同一个 `requestId` 重试。
5. 服务端把 `prompt` `.strip()`（`server.py:729`、`curation.py:61`），实测 `"  原文第一行\n【画风：FA-013 】\n"` 存成去掉首尾空白的版本，回读不可能逐字节一致。
6. `/api/account/me` 不存在，skill 用全量 `/api/boot`（71KB）核验账号。
7. 两边测试都绿，但互相对不上：skill 测试 mock 了 `request`，仍断言 `entry['assets']==[{'ref':'official:FA-013',…}]`（`test_conversation_share.py:276`），而新后端不读这个字段；网站的 `tests/test_work_publish_contract.py` 用 Cookie + Origin 登录（`:48-51`），不是 §6 B6 要求的只带 `Api-Key`，`entry` 也是手写的新格式，不是 skill 的 `work_payload`。
8. 偏离规格未申报：规格 §决策 6 要求 skill 直接调 `/api/works`、不做兼容层；实现新增了 `/api/entries` 转换层，报告没写这是偏离。

退回：删除 `_entry_to_work_body`。skill 的 `work_payload` 直接按 §4.6 发 `POST /api/works` 的请求体，`requestId=draft_id`，`source='skill'`；回执用响应里的 `url`（服务端返回绝对地址）；回读改为 `GET /api/forum/resources/work/<id>`；服务端原样存储 `prompt`。补一个跨仓库测试：导入 `conversation_share`，用真实 `prepare_draft → publish_draft`，把 `BASE_URL` 指向起好的测试服务。

### B7 评论收敛：不合格（中）

- 成立：`legacy_source` 唯一索引保证幂等。我把映射改回 `legacy` 后再跑一次 `apply`，复制行数仍是 2，没有重复；`status='migrating'` 先插再改能避开 `notify_forum_reply`（只在 INSERT 且 `status='published'` 时触发，`feature_schema.py:32-39`），实测通知增量 0（作者和评论者不同，坏实现必然会触发）。`created_at` 保留了原值。
- 不成立：
  1. 只复制 `status='published'`（`converge_work_comments.py:54`）。3 条中 1 条 `hidden` 没有复制，映射照样翻成 `submission`，此后读取 `forum_replies`，管理员再也看不到、也恢复不了这条隐藏评论。规格要求保留原状态。
  2. 没有改主帖的作者和版块（规格步骤 1）；没有 `audit_logs(action='comment.converge')`；没有 `--revert`。
  3. 所有作品放在一个事务里提交（`:113`），规格要求每件作品一个事务；备份同样用 `shutil.copy2`。
  4. `tests/test_ops_convergence.py` 不检查通知行数；"第二次运行不重复"是在映射已经翻转之后断言 `plan()==[]`，测的是映射翻转，没有测 `legacy_source` 去重。

## 4. 初始数据

- `images/` 有 676 个文件，49MB；`/images/individual/FA/FA-013.webp` 经 HTTP 返回 200。
- 本地库 10 件 starter 作品：`likes/cheers/favorites/forks/views` 全为 0，引用的 10 张图都在磁盘上。不伪造互动这一点成立。
- 问题：
  1. **测试密码硬编码**：`ops/seed_starter_library.py:22` 的 `STARTER_PASSWORD = "handraw-starter-2026"` 进代码，5 个账号共用，`--apply` 时还打印到终端（`:234`）。脚本已在默认库 `.local/handraw_v2.db` 上运行过（旁边有 `.bak-seed-20261030-003129`）。任何读过仓库的人都能登录这 5 个有积分、有作品的账号。改为每个账号随机密码或不可登录，只打印到本机 `.local/` 文件。
  2. 计数是真的，作者是假的：`linnan`、`chenmo`、`yuzi_art`、`helan`、`tangyuan` 是虚构的创作者，用官方画风样图以个人身份发布，还领了发布奖励。这与 B1"去掉虚构数据"的目标冲突。建议改为一个标明"官方示例"的账号，并且不发奖励。由创始人拍板。
  3. 脚本 `--apply` 前不备份（规格对 ops 写库脚本的通用要求）。
  4. `images/` 没有被 `.gitignore` 忽略，下一次 `git add -A` 会把 49MB 图片提交进仓库。AGENTS.md 禁止提交资源包。

## 5. 端到端（真实服务，临时库，随机端口）

| 步骤 | 结果 |
|---|---|
| 注册 → 上传 2 张图 → `POST /api/entries` | 200，`status=published` |
| 作品立即出现在 boot 的 `works` 中 | 是 |
| 主帖在 `showcase` 版 | 是，`category='showcase'`，boot 中带 `workId` |
| 他人对主帖点赞、收藏 | `works.likes=1, favorites=1`；boot 中作品和主帖都显示 1/1；`forum_topics` 冻结为 0/0 |
| 通过网站界面发布（`curation-ui` → `/api/curation/submissions`） | **进审核，`works` 不写入** |
| 管理员 hide | 作品 hidden，详情 404，**主帖仍为 published** |
| 付费作品匿名 boot | **提示词前 34 字可见** |
| 校验错误 | `price:"abc"` 返回 500，错误信息是 Python 原文 `invalid literal for int()…` |

## 6. 问题清单（按严重度）

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | 致命 | skill 真实载荷被新后端 400 拒绝，分享链路不通 | `E:\handraw-style\…\conversation_share.py:136-149`；`backend/server.py:702-738` |
| 2 | 致命 | 网站发布界面仍走审核，D-02 未落地 | `demo/assets/curation-ui.js:263-278`；`backend/curation.py:344` |
| 3 | 致命 | 复刻数由客户端声明，作者可自刷，污染热门榜 | `backend/curation.py:1449-1492`、`:1503-1516` |
| 4 | 致命 | 他人图片被静默丢弃后照常发布（§7.3 直接不合格项） | `backend/server.py:667`、`:677-678`、`:687-688` |
| 5 | 高 | 首件作品的荣誉升级奖励丢失，相关断言被删 | `backend/curation.py:1529`；`tests/test_v2_platform_and_admin.py` test_05 |
| 6 | 高 | 发布校验缺失；`price` 非数字返回 500；价格不设上限 | `backend/curation.py:1407-1424`、`:1479` |
| 7 | 高 | 付费作品提示词前 34 字匿名可见（G8） | `backend/services.py:607` |
| 8 | 高 | 审核隐藏作品后主帖仍公开；`set_work_visibility` 不存在 | `backend/admin_services.py:825-839` |
| 9 | 高 | 隐藏的旧评论在收敛后丢失 | `ops/converge_work_comments.py:54` |
| 10 | 高 | starter 账号共用硬编码密码，已在默认库上执行 | `ops/seed_starter_library.py:22`、`:234` |
| 11 | 中 | skill 回执拼旧地址；回读调不存在的接口且吞掉异常；不发 `requestId` | `conversation_share.py:258`、`:317-321`、`:400`、`:412` |
| 12 | 中 | 生产 SQL 与前端榜单的同分规则错误；主帖热门分在后端为 0 | `backend/forum_resources.py:337-338`；`backend/ranking.py:35-39`；`demo/assets/shared.js:1646` |
| 13 | 中 | 提示词被 `strip` 并截到 20000，非原样存储 | `backend/curation.py:61`、`:1409`；`backend/server.py:729` |
| 14 | 中 | `showcase` 可直接发帖并被静默改版块 | `backend/services.py:1729-1736` |
| 15 | 中 | 无发布频率限制、无奖励日上限 | `backend/curation.py:1398` 起 |
| 16 | 中 | 未知 `GET /api/*` 返回 200 HTML，掩盖接口缺失 | `backend/server.py` GET 兜底 |
| 17 | 中 | 缺 `idx_works_popular`；`GET /api/works`、`GET /api/account/me` 不存在 | `backend/work_schema.py`；`backend/server.py` |
| 18 | 中 | ops 脚本在 WAL 库上用文件复制备份；对账脚本缺演示模式拒跑和印章重算 | `ops/reconcile_social_counters.py:128`；`ops/converge_work_comments.py:148` |
| 19 | 中 | 评论收敛没有审计记录和 `--revert`，不改主帖作者与版块 | `ops/converge_work_comments.py` |
| 20 | 低 | `DEFAULT_STAMP_BASES` 死代码；`allow_self_review_for_admin` 仍为 True | `demo/assets/shared.js:1701`；`backend/seed.py:74` |
| 21 | 低 | "新发扶持"文案与空 `boostText` 胶囊残留 | `demo/assets/main-app.js:613`、`:676`、`:1340` |
| 22 | 低 | 主帖版块名写死，没有读常量 | `backend/curation.py:1590` |
| 23 | 低 | `images/` 未忽略，49MB 有误提交风险 | `.gitignore` |
| 24 | 低 | 本地发帖对象写 `likes:1, views:1` | `demo/assets/forum-app.js:1462-1464` |

## 7. 假完成

有，且不止一种。

**测试断言被改弱**
- `tests/test_v2_platform_and_admin.py` test_05（`git diff` 可见）：原断言是精确的 `credits == c0 + 5 + 10 + 10` 和 `assertTrue(res_w["pioneer"])`，覆盖"首发 + 开荒 + 荣誉升级"。改后：
  - 画风从 `FZ-999`（触发开荒）换成 `FA-013`；
  - 删掉 `pioneer` 断言；
  - 金额改成 `published_boot['credits'] == c0 + res_w['reward']`，用服务端自报的奖励去核对服务端的余额，是同义反复。
  这正好掩盖了 §3 B3 第 4 条的荣誉升级回归。`progress-20261030.md` 的"测试更新（非放宽）"只列了 `collect` 和 `pending→published`，没有申报这一处。违反 §7.3 最后一条。

**报告说做了，代码里找不到或不成立**
- "端到端探针真实跑通 `origin=skill` 落库"：只对手写的新格式 `entry` 成立；skill 真正发出的载荷返回 400。两边测试都绿，是因为 skill 测试 mock 了 HTTP，契约测试没有用 skill 的载荷。
- "奖励与荣誉升级照常发放"：荣誉升级不再发放。
- "9 图上限、缺图明确报错（此前会被静默截断）"：9 图上限属实；但他人图片仍被静默丢弃，提示词仍被静默截断。
- "`tests/test_ranking.py` 含 SQL 表达式与 Python helper 结果完全一致的对照测试"：测试里的 SQL 是测试自己写的，不是生产查询；用我的夹具，生产查询的顺序不同。前端一致性测试用的是桩函数。
- "`prepare_cloud_generation` 记录 `fork_work_id`"：写了，但没有代码读取，计数靠客户端声明。
- B2"四项全部应用"：规格 10 个索引只建了 9 个，缺的那个没有申报。

**只改了一端**
- 即时发布只在 API 层成立，网站界面仍走审核（只改了后端）。
- 规格 §5 B3、B5 的前端条目（`curation-ui.js`、`forum-app.js` 的 `visibleInAll`、`forum-work-post.js`、`studio-app.js` 的 `forkOf`、`forum-resources.js` 的复刻标签）都没有改。
- skill 侧改了接口地址和文档，没改 `work_payload`，文档与脚本不一致。

**证据不可复现**
- 报告中 B0、B1、B2 的"探针"没有落成测试文件。§6 点名的 `test_migration_atomicity.py`、`test_social_honesty.py`、`test_work_schema.py`、`test_work_publish.py`、`test_comment_convergence.py`、`test_showcase_feed.cjs`、`test_ranking_parity.cjs`、`tests/fixtures/ranking_cases.json` 都不存在。存在的 `test_work_counts.py`、`test_work_forks.py`、`test_work_publish_contract.py` 文件名对得上，用例不是 §6 的用例。
- 新增的 `.cjs` 没有加入 `.github/workflows/checks.yml`（规格 §6 约定），CI 只跑其中 6 个。

**幂等性**：迁移和评论收敛我都在非全新状态下重跑过，这两处的幂等成立，不算假完成。

**流程**：所有改动都没有提交，并且和本期之前就已存在、未提交的工作混在一起（`backend/curation.py`、`forum_resources.py`、`tests/test_v2_curation.py` 等都是未跟踪文件）。G1（改动范围）无法用 `git diff --stat` 核对，R5、R14 的回滚演练无法执行。规格要求"每批单独提交、单独验收"。

## 8. 上线前必须修的 3 件事

1. **打通 skill 真实链路，按规格 §4.6 走一条契约。** skill 的 `work_payload` 直接发 `POST /api/works`（`requestId=draft_id`、`source='skill'`），删除 `_entry_to_work_body`；服务端返回绝对 `url`，并原样存储 `prompt`；skill 回执用 `url`，回读用 `GET /api/forum/resources/work/<id>`，5xx 用同一个 `requestId` 重试。验收：一个跨仓库测试，用 skill 真实的 `prepare_draft → publish_draft`，只带 `Api-Key`，对起好的服务跑通 §6 B6 的 8 步。
2. **作品发布只留一条路，并且不静默丢数据。** 网站界面改调 `POST /api/works`，`/api/curation/submissions` 遇到 `kind='work'` 返回 400 `work_publish_moved`；他人图片返回 403 `media_not_owned`；补齐 §4.1 的全部校验和错误码，`price` 非法必须 4xx；修好荣誉升级的计数时机，并恢复 test_05 的精确金额断言；实现 `set_work_visibility`，让审核、举报、撤回同步主帖；付费作品在 boot 里不下发任何提示词片段。
3. **复刻计数改为按成功生成记账。** 去掉发布路径上对客户端 `forkOf` 的计数，按 §4.4 在 `complete_cloud_generation` 中记账（真实图片、非 `sample`、非作者本人）。复刻是热门公式里权重最高的一项，现在可以刷，B4 的榜单因此不可信。

上线前还要处理：§6 第 7 条（付费提示词片段）和第 10 条（硬编码密码）。

## 9. 退回范围

- B0：补 `tests/test_migration_atomicity.py`，可先合入。
- B1、B2：按 §3 补齐缺项；`idx_works_popular` 用新迁移 044 补，不改 040。
- B3–B7：按 §3 的退回要求重做，并补齐 §6 点名的测试文件。
- 重新提交时每批单独 commit，测试改动在提交说明里逐条写理由，与规格 §6「需要修改的既有用例」对应。
