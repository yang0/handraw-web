# 第二轮终审报告（2026-10-30）

> 历史产品评审。旧数据库实现内容已移除；当前数据库与运维以 `docs/local-operations.md` 为准。
评审人：Claude（架构师兼终审）。对象：`fix-report-round2-20261030.md`。

探针都在 `.local/review/round2/`，在仓库根目录用 `python -X utf8 .local/review/round2/<脚本>` 重跑：

| 脚本 | 覆盖 |
|---|---|
| `probe_skill.py` | 第 1 条：skill 真实链路，真实服务，只带 Api-Key |
| `probe_http.py` | 第 2、4、5、6、7、8 条（HTTP） |
| `probe_leak.py` | 第 7 条：付费提示词在哪些响应里出现 |
| `probe_forks.py` | 第 3 条：刷复刻数的反例（生产函数 + 对账脚本） |
| `probe_mixed.py` | 第 2 条：混合投稿审核通过后写入的作品 |
| `probe_misc.py` | HTTP 刷复刻、第 9 条评论收敛、干净库 seed、索引与查询计划 |
| `probe_default_db.py`、`probe_login.py` | 第 10 条：默认库 5 个账号的现状，HTTP 登录 |

## 0. 结论

**仍不能接受。** 本轮确实修了一部分：他人图片改为 403、校验补齐大半、评论收敛保留隐藏评论、荣誉升级奖励恢复、网站界面改调 `/api/works`。但致命项里，复刻数仍然能刷（5 个傀儡账号加 1 次真实生成，父作品 forks 从 0 变成 6）；默认库那 5 个账号**至今仍能用仓库里公开过的旧密码 `handraw-starter-2026` 登录**；付费提示词前 34 字仍出现在服务端渲染的 HTML 里，匿名和爬虫都能拿到。报告里有一处可以直接证伪的陈述（`DEFAULT_STAMP_BASES`「`git grep` 零命中」），另有多处把"部分修复"写成"已修复"。

## 1. 实际跑出的测试数字

| 套件 | 命令 | 结果 | 报告所称 |
|---|---|---|---|
| 网站 Python | `python -m pytest -q` | 135 passed, 11 subtests passed（31.1s） | 135 / 11，属实 |
| 网站 Python | `python -m unittest discover -s tests` | Ran 135, OK | 135，属实 |
| 前端 | 逐个 `node tests/*.cjs` | **17/17** 退出码 0 | 写的是 16/16。多出的 `test_ranking_parity.cjs` 修改时间是 01:13，晚于报告里的测试基线 |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | 30 passed | 30，属实 |

测试全绿，但下面的探针在全绿的前提下复现出 3 个致命问题。原因见 §4：新测试只测了修过的那条路径，没有测相邻路径。

## 2. 十条逐条判定

| # | 问题 | 判定 | 我的验证方式与关键结果 |
|---|---|---|---|
| 1 | skill 真实链路 | **部分修复** | `probe_skill.py`：真实 `prepare_draft → publish_draft`，只带 Api-Key。200，`styles=["FA-013"]`、`layout=SC-021`、首图和附图顺序正确、`origin=skill`。**但**提示词首部空白被去掉，不是原样；回执仍是 `/studio?entry=`（HTML 页）；`verified=False`；不带 `requestId`，同一载荷重放生成了第 2 件作品 |
| 2 | 网站界面走审核 | **部分修复** | `curation-ui.js:282-295` 单件作品改调 `/api/works`；纯作品投稿 400 `work_publish_moved`；`test_forum_resources.py` 绿。**但**混合投稿是一条后门：3 个画风、1 字标题、`price:100000` 的作品随画风过审后写成 `published` 作品（`probe_mixed.py`） |
| 3 | 复刻伪造 | **未修复** | `probe_forks.py`：5 个傀儡账号带 `forkOf` 发布，`work_forks` 写入 5 行；之后任意 1 次真实生成，父作品 `forks` 从 0 变 6；只跑对账脚本，从 0 变 5 |
| 4 | 他人图片静默丢弃 | **已修复（有残留）** | B 用 A 的图：列表、对象、`/api/entries` 封面、论坛帖都返回 403 `foreign_media`，0 件作品写入。残留：单图字段 `image` 仍会静默丢弃他人的图，返回 400 `image_required` |
| 5 | 荣誉升级奖励 | **部分修复** | 新用户首件作品：账本 `publish_work +15`、`honor_upgrade +10`，余额 20→45，**+25 正确**。但回执 `reward=15`，与实际增量 25 不符；test_05 把 `reward==15` 写成了断言，等于把这个不一致锁定为"正确" |
| 6 | 发布校验 | **已修复（点名 4 项）** | `title=""`、`styles=[3个]`、`price="abc"`、`price=100000` 都是 400，错误码 `title_required`、`too_many_styles`、`invalid_price`、`price_out_of_range`。残留：`price:Infinity` **500**；`9.7` 存成 9，`true` 存成 1；1 字和 500 字标题都通过（500 字被截断到 140）；20050 字提示词被截到 20000 |
| 7 | 付费提示词 | **部分修复** | boot 里匿名和他人看到的 `prompt` 是 `''`，作者能看到全文，属实。**但**服务端渲染的 SEO HTML 仍输出前 34 字：匿名 GET `/`、`/api/forum/topics` 等任意兜底页都包含 `SECRET-付费提示词-完整内容-0123456789…` |
| 8 | 隐藏作品同步主帖 | **部分修复** | 管理员 `hide`：作品和主帖都变 `hidden`。**但**举报确认后作品 `hidden`、主帖 `published`；3 人举报自动暂停后作品 `paused`、主帖 `published`；管理员删除作品后主帖仍 `published`，`work_id` 指向已删除的行 |
| 9 | 评论收敛丢隐藏评论 | **已修复（有残留）** | 我用第三方评论者构造 published + hidden 两条：都复制，状态和 `created_at` 保留，通知增量 0。残留：没有审计记录、没有 `--revert`、备份仍用 `shutil.copy2`、全部放在一个事务；没有评论的 legacy 映射不会被翻转 |
| 10 | starter 账号密码 | **未修复（默认库）** | 代码层面：常量已删、改为随机、凭据写到已忽略路径，属实。**默认库**：5 个账号已标注"官方示例"，但**旧密码 `handraw-starter-2026` 仍能通过 HTTP 登录全部 5 个账号**，每个余额 50。`.local/starter_credentials.json` 对默认库 0/5 匹配，对 `clean_v2.db` 5/5 匹配 |

## 3. 逐条证据

### 第 1 条 skill 真实链路：部分修复

草稿：`original_request = "  画一只在窗台上晒太阳的橘猫\n第二行要求：留白多一点  \n"`，3 张图，`style_ids=["FA-013"]`，`layout_ids=["SC-021"]`。`share.BASE_URL` 指向测试服务，`CommunityAPI` 只发 `Api-Key`。

| 检查项 | 结果 |
|---|---|
| 返回 | 200，`kind=work`，`status=published` |
| `content.prompt` 原样落库 | **否**。期望 `'  画一只…'`，实存 `'画一只…'`。`server.py:774` 的 `.strip()` 和 `curation.py:61-62` 的 `_s()` 都会去掉首尾空白；去掉首尾空白后两者相等 |
| `official:FA-013` → styles，`official:SC-021` → layout | 是，`["FA-013"]` / `SC-021` |
| `cover_url` 为首图，`examples` 为附图 | 是，顺序一致 |
| `origin` | `skill` |
| 回执地址 | `…/studio?entry=<id>`，返回 HTML（`conversation_share.py:400` 未改） |
| 回读 | `/api/entries/<id>`、`/content` 都返回 200 HTML，异常被吞，`verified=False`、`associations_verified=False`（`conversation_share.py:317-321`、`:412`） |
| 幂等 | 载荷没有 `requestId`（`work_payload` 在 `conversation_share.py:136-149`）。同一载荷再发一次得到**另一个** id，作品数从 1 变 2 |

skill 仓库本轮没有任何文件改动（修改时间都早于上一轮终审）。上一轮 §3 B6 第 2–5 条原样存在。

### 第 2 条 网站界面：部分修复

- 单件作品成立：`curation-ui.js:277` 判定 `items.length === 1 && kind === 'work'`，改发 `/api/works`，成功后跳详情页。
- `/api/curation/submissions`：只含作品 → 400；两件作品 → 400；混合 → 200。
- **混合投稿后门**（`probe_mixed.py`）：`[画风, 作品{title:'猫', styles:[3个], price:100000}]` 两票通过后，`works` 新增一行：`title='猫'`、`price=100`（被静默夹到 100，没有报错）、`styles_json` 含 3 个画风、`status='published'`、`origin='legacy'`、id 是 `work_…` 而不是 UUID。这一行没有经过 `publish_work_direct` 的任何校验。原因：`_normalise_item`（`curation.py:178-206`）对作品取 `[:3]` 个画风、`min(100, …)` 夹价格，`_publish_approved`（`:876` 起）照旧写 `works`。D-02 要求作品只有一条发布路径，现在仍有两条。
- UI 允许"添加一项"，作者加第二件作品后点提交，会收到 400 `work_publish_moved`，界面没有给出替代操作。

### 第 3 条 复刻伪造：未修复


| 攻击 | 结果（`works.forks`, `COUNT(work_forks)`） | 应为 |
|---|---|---|
| A. 5 个傀儡账号带 `forkOf` 发布，不生成 | (0, 5) | (0, 0) |
| A2. 之后任意一个无关用户真实生成 1 次 | **(6, 6)** | (1, 1) |
| A3. 只有傀儡，然后运行 `ops/reconcile_social_counters.py` 的 apply | **(0,5) → (5,5)** | (0,0) |
| HTTP 版：3 个傀儡经 `POST /api/works` 带 `forkOf` | (0, 3)；傀儡还各拿到发布奖励 15/5/5 | (0, 0)，且不应因此获利 |
| U. 同一用户先带 `forkOf` 发布，再真实生成 | (0, 1)，真实复刻永远不计 | (1, 1) |
| H. 对**已隐藏**的父作品真实生成 | (1, 1) | (0, 0) |
| J. `forkOf="not-a-work-id"` | 原样写进 `studio_generations.fork_work_id`（`services.py:2700`，不校验） | 拒绝或置空 |

另外：
- "sample 引擎不计"是无效判断。`prepare_cloud_generation` 把 `engine` 写死为 `'live'`（`services.py:2686`），`engine='sample'` 的行（`:2410`）从不经过 `complete_cloud_generation`。演示模式的 `simulateGateway=ok`（`server.py:2432-2434`）用固定演示图完成生成，也会计 1 次复刻。
- 前端没有任何地方发 `forkOf`（`grep forkOf demo/assets/*.js` 无结果），所以真实用户永远走不到计数路径，能走到的只有攻击路径。
- `test_work_forks.py` 只断言 `works.forks` 缓存，不查 `work_forks` 行数，所以 A 和 A2 测不出来。

### 第 4 条 他人图片：已修复（有残留）

`validate_publish_media`（`server.py:677-680`、`:691-692`）对列表里他人的 `/uploads/`、`/generated/` 抛 403 `foreign_media`。实测 6 种入口里 5 种返回 403，0 件作品写入。
残留：单图字段（`server.py:653-663`）遇到他人的图仍然 `out.pop(key)`，静默丢弃。只有这一张图时表现为 400 `image_required`，错误信息误导；如果同时带了 `images`，就会静默发布。

### 第 5 条 荣誉升级：部分修复

新用户 `newbie_r2`，首件作品，画风 FB-028（未开荒）：

| 项 | 值 |
|---|---|
| 账本 | `welcome +20`；`publish_work +15`（5 基础 + 10 开荒）；`honor_upgrade +10` |
| 余额 | 20 → 45，增量 **25** = 5 + 10 + 10，正确 |
| 回执 `reward` | **15** |
| 回执 `credits` | 45，与 boot 一致 |
| 回执字段 | `credits, deduplicated, ok, reward, status, topicId, url, workId`，没有 `pioneer`、`upgradedBadge` |

修复本身成立：`before_tier` 在 INSERT 之前取（`curation.py:1480-1481`）。但 `_work_receipt` 只读 `pub_work_<id>` 这一条账本（`curation.py:1698-1702`），荣誉奖励不计入 `reward`。

**test_05 是否恢复了精确金额：部分。** `credits == c0 + 5 + 10 + 10` 改回了常量算式，并且用 boot 读回余额，不再"用服务端自报的奖励核对服务端余额"，这一点达到我的要求。但同时新增的 `assertEqual(res_w['reward'], 15)`（`tests/test_v2_platform_and_admin.py:379`）把 `reward` 与实际增量不一致写成了期望值；原来的 `assertTrue(res_w["pioneer"])` 没有恢复；画风从 `FZ-999` 换成 `FA-013` 没有说明理由。

### 第 6 条 发布校验：点名 4 项已修复

见 §2 表。点名之外的残留：
- `price: Infinity`：Python 的 `json` 接受这个写法，`int(inf)` 抛 `OverflowError`，而 `curation.py:1447` 只捕获 `TypeError, ValueError`，于是返回 **500** `cannot convert float infinity to integer`。违反 G5。
- `price: 9.7` 存成 9，`price: true` 存成 1，都是静默转换。
- 标题长度规格是 4–160：1 字通过，500 字被截到 140 后通过（`curation.py:1420`）。
- 提示词 20050 字被静默截到 20000（`curation.py:1423`），违反 G7。
- 不存在的画风返回 `bad_request`，规格要求 `asset_not_found`（`curation.py:1391`）。

### 第 7 条 付费提示词：部分修复

`_serialize_work`（`services.py:604-610`）已改为空字符串，`/api/forum/resources/work/<id>` 也不含。但 `server.py` 的 SEO 预渲染仍是旧逻辑：
- `server.py:1377`：`summary_txt = w["notes"] or (… else w["prompt"][:34] + "…")`，输出到每个页面兜底 HTML 的作品卡片里；
- `server.py:1279`：作品详情页的 `<meta name="description">` 同样取 `prompt[:34]`。

实测匿名 GET `/api/forum/resources?kind=work`、`/api/forum/topics`、`/api/forum/topics/<id>`、`/api/works/<id>`，这些未知 GET 都返回首页 HTML，里面有 `<p>SECRET-付费提示词-完整内容-0123456789…</p>`。搜索引擎会收录这段文字。作者没有填 `notes` 时一定泄漏。`PaidPromptTests` 只测了 `build_boot_payload`。

### 第 8 条 隐藏同步主帖：部分修复

只改了 `admin_moderate_work`（`admin_services.py:869-883`）。规格要求的 `set_work_visibility` 不存在，其他改作品状态的路径都没有同步主帖：

| 路径 | 作品 | 主帖 |
|---|---|---|
| 管理员 hide | hidden | hidden |
| 举报确认 `admin_resolve_report`（`admin_services.py:1854-1855`） | hidden | **published** |
| 3 人举报自动暂停 `submit_abuse_report`（`services.py:2159`） | paused | **published** |
| 管理员删除（`admin_services.py:861-865`） | 行已删除 | **published**，`work_id` 悬空 |

举报是用户最常触发的下架路径，这里不同步，R11 就没有落实。

### 第 9 条 评论收敛：已修复（有残留）

`plan()` 去掉了状态过滤（`ops/converge_work_comments.py:53-58`），先插入 `migrating` 再改回原状态，触发器不会补发通知。重置映射后再跑一次，`legacy_source` 去重，复制行数仍是 2。残留与上一轮 §3 B7 第 2–3 条相同：没有 `audit_logs`、没有 `--revert`、单事务（`:116`）、`shutil.copy2` 备份（`:151`）。另外 `:146` 在没有待复制评论时直接返回，不翻转映射，没有评论的 legacy 作品永远停在 legacy。

### 第 10 条 starter 账号：未修复（默认库）

`probe_default_db.py` 在默认库的 `backup()` 副本上验证，`probe_login.py` 在副本上起服务、通过 HTTP 登录：

| 账号 | 显示名 | 旧密码 HTTP 登录 | 余额 |
|---|---|---|---|
| linnan | 官方示例·林南 | **200** | 50 |
| chenmo | 官方示例·陈默 | **200** | 50 |
| yuzi_art | 官方示例·柚子 | **200** | 50 |
| helan | 官方示例·何岚 | **200** | 50 |
| tangyuan | 官方示例·汤圆 | **200** | 50 |

- 报告称"默认库与干净库均已执行标注"，只说了标注，没说默认库的密码**没有轮换**。`label_starter_accounts.py` 只改 `display_name` 和 `bio`；`seed_starter_library.py:203-204` 遇到已存在的账号直接跳过。旧密码已经在仓库代码里出现过，所以这 5 个账号仍然是公开可登录的。
- `.local/starter_credentials.json` 是 `clean_v2.db` 的凭据（5/5 匹配），对默认库 0/5。
- 标注只改了 `users.display_name`。`works.author_name` 和 `forum_topics.author_name` 是冗余存储的旧名字，广场和主帖上仍显示"林南"等虚构作者名。
- 干净库 seed 时这 5 个账号仍然领奖励：`publish_work` 10 条共 150、`honor_upgrade` 共 100。上一轮建议"不发奖励"，本轮没有处理，也没有在报告里说明。

## 4. 假完成是否复发

**复发了，形式比上一轮隐蔽。** 这一轮没有把断言改弱，但有可以直接证伪的陈述，有"只修一条路径就报已修复"，新测试也只测修过的那条路径。

### 可以直接证伪的陈述

| 报告原文 | 事实 |
|---|---|
| 「`DEFAULT_STAMP_BASES` 在 B1 中已随 `base_map` 一并删除，`git grep` 零命中。审查报告可能基于旧快照。」 | `git grep -n DEFAULT_STAMP_BASES` 命中 `demo/assets/shared.js:1701`，退出码 0。这句话把没做的事说成做了，还暗示审查有误 |
| 「Node `.cjs` 16/16」 | 实际 17 个。`test_ranking_parity.cjs` 是在报告的测试基线之后才加的 |
| 「默认库与干净库均已执行标注」（放在"硬编码密码"条目下） | 默认库密码没有轮换，旧密码 5/5 能登录 |
| 「复刻可伪造：已修复」 | 事实表仍由客户端 `forkOf` 写入，见第 3 条 |
| 「`content.prompt` → 作品提示词」「提示词完整」 | 服务端仍 `.strip()`。对应测试用的是 `assertIn("原始提示词正文", row["prompt"])`（`tests/test_work_publish_contract.py:144`），注释写的是 "stored verbatim"，断言测不出首尾空白丢失 |
| 「付费提示词：锁定作品的 prompt 改为空字符串」 | 只改了 boot；SSR HTML 仍输出前 34 字 |

### `git diff tests/`

已跟踪的测试文件只有 `tests/test_v2_platform_and_admin.py` 有改动，其余新测试都是未跟踪文件，`git diff` 看不到。我按修改时间筛出本轮改过的 5 个测试文件（`test_v2_platform_and_admin.py`、`test_work_forks.py`、`test_work_publish_contract.py`、`test_publish_validation.py`、`test_review_fixes.py`），逐个读过：
- 没有发现新的断言放宽。`test_work_forks.py` 把"发布即计数"翻转为"发布不计数"，方向正确。
- test_05：见第 5 条，部分恢复，同时锁定了一个错误值。

### 规格 §6 点名的测试文件

| 文件 | 状态 |
|---|---|
| `tests/test_migration_atomicity.py` | 不存在 |
| `tests/test_social_honesty.py` | 不存在 |
| `tests/test_work_schema.py` | 不存在 |
| `tests/test_work_publish.py` | 不存在 |
| `tests/test_comment_convergence.py` | 不存在 |
| `tests/test_showcase_feed.cjs` | 不存在 |
| `tests/fixtures/ranking_cases.json` | 不存在 |
| `tests/test_ranking_parity.cjs` | 存在，但只比较 5 组计数的**分数**，不比较**排序**，同分规则测不到 |

8 个里 7 个仍不存在，与上一轮相同。新测试也没有加入 `.github/workflows/checks.yml`，CI 里仍只跑 6 个 `.cjs`。

### 新测试是否测到生产代码

| 测试 | 调用生产代码？ | 漏掉了什么 |
|---|---|---|
| `test_review_fixes.PaidPromptTests` | 是（`build_boot_payload`） | 只测 boot，没测 SSR HTML（`server.py:1279`、`:1377`） |
| `test_review_fixes.PopularIndexTests` | **否**。查询是测试自己写的 `ORDER BY expr DESC, published_at_ms DESC` | 生产 `_sql_page`（`forum_resources.py:339`）是 `ORDER BY expr DESC, w.id ASC`，查询计划多出 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY` |
| `test_review_fixes.ConvergeAllStatusesTests` | 是 | 评论者就是作者本人，触发器本来就不会通知，"不补发通知"测不出来 |
| `test_review_fixes.StarterCredentialTests` | 只测函数和常量 | 不检查已经运行过的默认库 |
| `test_publish_validation` | 是（`publish_user_work`、`admin_moderate_work`） | 只测管理员 hide/pause/publish，没测举报、自动暂停、删除 |
| `test_work_forks` | 是 | 只断言 `works.forks` 缓存，不查 `work_forks` 行数，所以傀儡写入事实表测不出来 |
| `test_work_publish_contract.test_entry_accepts_the_real_community_share_payload` | 是，但载荷是**手抄**的，不是导入 `conversation_share.work_payload`；用 Cookie + Origin 登录，不是只带 Api-Key | 回执、回读、`requestId`、原样存储都不在测试范围 |

### `tests/test_ranking.py`：未改

修改时间早于上一轮终审，本轮没有动。`RankingParityTests` 仍然自己写 `ORDER BY score DESC, id ASC`（`:70-73`），夹具的 `published_at_ms` 全是 1000。上一轮的批评原样成立。生产 `_sql_page`（`forum_resources.py:339`）和前端 `getRankedWorks`（`shared.js:1646`）的同分规则也没修。

### `test_works_browser.cjs`：已改

现在加载的是真实的 `shared.js`，取 `HANDRAW_SHARED.popularScore`，不再用桩。这一条成立。

## 5. 新增检查

| 检查 | 结果 |
|---|---|
| 迁移 044 `idx_works_popular` | 存在（`backend/work_schema.py:50-55`，`WORK_MIGRATIONS` 第 44 项）。默认库和新库的 `schema_migrations` 最大版本都是 44，索引都在 |
| `EXPLAIN QUERY PLAN` | 规格要求的排序（`… DESC, published_at_ms DESC`）：`SEARCH w USING INDEX idx_works_popular (status=?)`，完全命中。**生产查询**（`_sql_page` 的 `… DESC, w.id ASC`）：用上索引，但多一步 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`。规格里依赖这个索引的 `GET /api/works?sort=popular` 仍不存在，GET 返回首页 HTML |
| 迁移只增不删 | `grep -i "drop\|delete from\|rename"` 扫 `work_schema.py`、`migrations.py`、`curation_schema.py`、`feature_schema.py`、`db.py`：唯一命中是 `work_schema.py:4` 的注释。合格 |
| `.gitignore` 加入 `/images/` | 已加（`.gitignore:33`）。`git check-ignore images/x.webp` 命中。`starter_credentials.json` 也已忽略 |
| 干净库 seed：计数 | 新建库 → `seed_starter_library --apply`：10 件作品，`likes+cheers+favorites+forks+views>0` 的有 0 件。合格。密码不打印到终端，合格 |
| 干净库 seed：作者是否标注为官方示例 | **只跑 seed 时不会标注**，显示名是"林南""陈默"等，必须再手动跑 `label_starter_accounts.py --apply`。跑完后 `users.display_name` 带"官方示例·"，但 `works.author_name`、`forum_topics.author_name` 仍是原名。seed 还给这 5 个账号发了发布奖励和荣誉奖励 |

## 6. 剩余问题清单（按严重度）

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | 致命 | 发布时客户端 `forkOf` 写入 `work_forks` 事实表；之后任意 1 次真实生成或 1 次对账，都会把傀儡行算进 forks。同一用户"先发布后生成"的真实复刻反而永远不计 | `backend/curation.py:1527-1528`、`:1542-1553`、`:1562-1576`；`ops/reconcile_social_counters.py:42` |
| 2 | 致命 | 默认库 5 个 starter 账号仍可用仓库里出现过的旧密码登录（HTTP 5/5 成功，每个余额 50） | `.local/handraw_v2.db`；`ops/seed_starter_library.py:203-204`（已存在账号不轮换密码） |
| 3 | 致命 | 付费作品提示词前 34 字由服务端渲染进每个页面的 HTML 和作品详情的 meta description，匿名和爬虫可见（G8） | `backend/server.py:1377`、`:1279` |
| 4 | 高 | 混合投稿后门：随画风过审的作品不经过 `publish_work_direct` 校验，3 个画风、1 字标题、价格被静默夹到 100 后发布；id 非 UUID，`origin='legacy'` | `backend/curation.py:178-206`、`:876` 起；`:357-361` 只拦纯作品 |
| 5 | 高 | 举报确认、自动暂停、删除作品都不同步主帖；`set_work_visibility` 不存在 | `backend/admin_services.py:1854-1855`、`:861-865`；`backend/services.py:2159` |
| 6 | 高 | skill：提示词首尾空白被去掉；回执仍是 `/studio?entry=`；回读接口返回 HTML，`verified` 恒为 False；没有 `requestId`，重放会发布第二件作品 | `backend/server.py:774`；`backend/curation.py:61-62`；`E:\handraw-style\…\conversation_share.py:136-149`、`:317-321`、`:400`、`:412` |
| 7 | 高 | 回执 `reward` 不含荣誉奖励（报 15，实际 +25），没有 `pioneer`、`upgradedBadge`；test_05 把 15 写成了期望值 | `backend/curation.py:1698-1702`；`tests/test_v2_platform_and_admin.py:379` |
| 8 | 中 | `price: Infinity` 返回 500；小数和布尔值被静默转换 | `backend/curation.py:1444-1450` |
| 9 | 中 | 标题、提示词被静默截断，不报错；标题没有下限 | `backend/curation.py:1420`、`:1423` |
| 10 | 中 | 单图字段遇到他人的图仍静默丢弃 | `backend/server.py:653-663` |
| 11 | 中 | `prepare_cloud_generation` 不校验 `forkOf`，隐藏的父作品也计复刻；"sample 不计"的判断永远不会生效；演示模式模拟生成会计复刻 | `backend/services.py:2700`、`:2686`、`:2788`；`backend/server.py:2432-2434` |
| 12 | 中 | 前端从不发送 `forkOf`，真实复刻计数路径没有入口 | `demo/assets/studio-app.js` |
| 13 | 中 | 生产 SQL 和前端榜单的同分规则仍错误；`test_ranking.py` 仍用自写 SQL | `backend/forum_resources.py:339`；`demo/assets/shared.js:1646`；`tests/test_ranking.py:70-73` |
| 14 | 中 | 未知 `GET /api/*` 返回 200 首页 HTML（还带着付费提示词片段）；`GET /api/works`、`/api/account/me` 不存在 | `backend/server.py` GET 兜底 |
| 15 | 中 | `showcase` 仍能直接发帖，被静默改到 experience；没有发布频率限制和奖励日上限 | `backend/services.py:1732-1739`；`backend/curation.py:1410` 起 |
| 16 | 中 | 评论收敛：没有审计记录和 `--revert`，单事务，备份用 `copy2`，没有评论的 legacy 映射不翻转 | `ops/converge_work_comments.py:116`、`:146`、`:151` |
| 17 | 中 | starter：只跑 seed 不会标注；`works`/`forum_topics` 的 `author_name` 仍是虚构名；seed 仍发奖励；`--apply` 前不备份 | `ops/seed_starter_library.py:210-218`；`ops/label_starter_accounts.py:51-60` |
| 18 | 中 | 规格 §6 的 8 个测试文件缺 7 个；新 `.cjs` 没有加入 CI | `tests/`；`.github/workflows/checks.yml` |
| 19 | 低 | `DEFAULT_STAMP_BASES` 仍在（报告称已删）；`allow_self_review_for_admin` 仍为 True | `demo/assets/shared.js:1701`；`backend/seed.py:74` |
| 20 | 低 | "新发扶持"残留；本地发帖对象写 `likes: 1`；主帖版块名写死 | `demo/assets/main-app.js:676`、`:1340`；`demo/assets/forum-app.js:1462`；`backend/curation.py:1658` |
| 21 | 低 | UI 允许添加多件作品，提交时得到 400，没有替代操作 | `demo/assets/curation-ui.js:224`、`:277` |
| 22 | 流程 | 所有改动仍未提交，和本期之前的未提交工作混在一起，无法按批回滚 | 整个工作区 |

## 7. 是否满足上线条件

**不满足。** 上线前必须完成：

1. **复刻**：发布路径完全不写 `work_forks`，谱系只写 `works.forked_from_id`；清理已有的发布期行；`prepare_cloud_generation` 校验 `forkOf` 是已发布作品；补一个测试，断言傀儡发布后 `COUNT(work_forks)==0`，并且 1 次真实生成后 forks 恰好等于 1。
2. **默认库凭据**：立即轮换默认库 5 个账号的密码，或者把它们设为不可登录；重置它们的 Api-Key。确认任何线上或共享环境里都没有这 5 个账号使用旧密码。
3. **付费提示词**：`server.py:1279`、`:1377` 对付费作品不输出任何提示词片段；补一个测试：匿名 GET `/` 和作品详情页的 HTML 不含付费提示词。
4. **作品只有一条发布路径**：混合投稿里的作品要么拒绝，要么转交 `publish_work_direct`，不再经过 `_publish_approved` 写入 `works`。
5. **可见性**：实现 `set_work_visibility`，让举报确认、自动暂停、删除都通过它同步主帖。
6. **skill 契约**：服务端原样存储提示词；skill 发 `requestId`；回执使用服务端返回的地址，回读改用 `/api/forum/resources/work/<id>`；补一个导入 `conversation_share`、只带 Api-Key 的跨仓库测试，断言提示词逐字节相等。

第 7–21 条可以排进下一批，但 `price: Infinity` 返回 500 只要改一行，建议这一批一起修。报告里的不实陈述（`DEFAULT_STAMP_BASES`、16/16、默认库"已执行"）要在下一份报告里更正。

