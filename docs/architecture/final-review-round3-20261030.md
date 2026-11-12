# 第三轮终审报告（2026-10-30）

> 历史产品评审。旧数据库实现内容已移除；当前数据库与运维以 `docs/local-operations.md` 为准。
评审人：Claude（架构师兼终审）。对象：`fix-report-round3-20261030.md`。

探针在 `.local/review/round3/`，仓库根目录执行 `python -X utf8 .local/review/round3/<脚本>`，输出已存为同名 `.txt`：

| 脚本 | 覆盖 |
|---|---|
| `probe_forks.py` | 第 1 条：生产函数层面的复刻攻击、对账脚本、清理脚本 |
| `probe_gen_http.py` | 第 1 条：`/api/studio/generate` 真实 HTTP 链路（本地模拟网关）、傀儡账号、跨用户 |
| `probe_purge.py` | 第 1 条：`ops/purge_publish_time_forks.py --apply` 命令行实跑 |
| `probe_default_db.py`、`probe_login.py` | 第 2 条：两个本地库的 5 个账号，`verify_password` + HTTP 登录 + Api-Key + 会话 |
| `probe_http.py` | 第 3、5、6、7 条及作者编辑路径 |
| `probe_skill.py` | 第 4 条：skill 真实链路、幂等（含并发） |
| `../round2/probe_misc.py`（重跑） | 第 8 条评论收敛、干净库 seed、索引与查询计划 |

## 0. 结论

**仍不能接受，但已接近。** 上一轮三条致命问题的原始攻击这次都打不通了：傀儡发布 + 对账不再改变 forks；默认库旧密码和旧 Api-Key 失效；付费提示词不再出现在任何 SSR 页面。混合投稿后门也关了，skill 的空白、幂等、回执地址都成立。

但这一轮引入了一个新的治理回归：**管理员隐藏的作品，可以被 3 次举报改成"暂停"，再被一次"驳回举报"重新公开**。删除作品后主帖仍是公开状态。复刻数换一条路仍能免费刷（5 个新账号各用一次免费额度，forks 0→5）。报告里新的清理工具 `--apply` 一跑就崩。报告又有几处可以直接证伪的陈述，形式和上一轮一样：条件里的子项没做，表格里照样打 ✅。

## 1. 实际测试数字

| 套件 | 命令 | 结果 | 报告所称 |
|---|---|---|---|
| 网站 Python | `python -m pytest -q` | 145 passed, 11 subtests passed（34.1s） | 145 / 11，属实 |
| 网站 Python | `python -m unittest discover -s tests` | Ran 145, OK（32.0s） | 145，属实 |
| 前端 | 逐个 `node tests/*.cjs` | 17 个文件，17/17 退出码 0 | 17/17，属实 |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | 30 passed | 30，属实 |

数字这次都对。但下面的探针在全绿的前提下又复现了问题，原因和上一轮一样：新测试只测修过的那一个调用点。

## 2. 上轮「未修复」三条

### 2.1 复刻数可刷：原攻击已堵，换路径仍可刷 → **部分修复**

`_record_fork` 已改为空函数（`backend/curation.py:1560-1571`），发布路径不再写 `work_forks`。

| 攻击 | 结果 (works.forks, COUNT(work_forks)) | 应为 | 判定 |
|---|---|---|---|
| A. 5 个傀儡带 `forkOf`（外加伪造 `generationId`）发布 | (0, 0) | (0, 0) | 已堵 |
| A3. 再跑 `reconcile_social_counters` apply | (0, 0) | (0, 0) | 已堵 |
| A2. 之后 1 个无关用户真实生成 1 次，再对账 | (1, 1) | (1, 1) | 正确 |
| U. 同一用户先带 `forkOf` 发布、再真实生成 | (1, 1) | (1, 1) | 上轮少计，已修 |
| 作者从自己作品生成 / 同一用户再生成 | 不增加 | 不增加 | 正确 |
| 完成时图片为 `[]` 或 `['', '   ']` | (0, 0) | (0, 0) | 正确 |
| `simulateGateway=ok`（非演示模式） | 404 `demo_disabled` | 拒绝 | 正确 |
| 轮询他人 `taskId` / `requestId` | 404 | 拒绝 | 正确 |
| **S. 5 个新注册账号（同一 IP），各发 1 次 `POST /api/studio/generate {forkOf}`** | **(5, 5)**，0.3 秒，`costType=free_quota`、`creditsSpent=0` | 不应免费可刷 | **仍可刷** |
| **H. 对已隐藏的父作品真实生成** | **(1, 1)** | (0, 0) | **未修** |
| **R. 生成被退款后，又收到一次成功回调** | **(1, 1)**，行状态仍是 `refunded` | (0, 0) | **新发现** |
| J. `forkOf="not-a-work-id"` | 原样写入 `studio_generations.fork_work_id` | 拒绝或置空 | 未修 |

攻击 S 的步骤：注册 5 个账号 → 每个账号带 `forkOf=父作品` 调 1 次生图 → 轮询 `/api/studio/tasks` 拿到成功。注册限流的键是 `IP|用户名`（`backend/server.py:1451`），换用户名就不受限；每人每天有免费额度，攻击者不花一分积分，生图成本由平台付。forks 在热门分里权重最高（`3 * forks`）。另外前端仍然没有任何地方发送 `forkOf`（`grep forkOf demo/assets/*.js` 无结果），所以**库里所有的复刻计数都只能来自手工构造的请求**。

H、J：上轮上线条件 1 明确要求「`prepare_cloud_generation` 校验 `forkOf` 是已发布作品」。没做：`backend/services.py:2719` 原样存储，`:2807-2825` 计数时不查父作品状态。

R：`complete_cloud_generation` 的状态更新带了 `status NOT IN ('refunded','success')`（`services.py:2796-2799`），但后面的复刻计数（`:2807-2825`）和私有媒体入库（`:2826-2845`）不看这次更新有没有生效。网关先报失败、后报成功时，用户拿到退款、拿到图、还计一次复刻。

清理工具 `ops/purge_publish_time_forks.py`：

- **识别规则有漏洞。** 旧的发布路径把客户端传来的 `generationId` 原样写进 `first_generation_id`（调用点 `curation.py:1546` 仍在传），所以伪造过 `generationId` 的历史行不是空串，`:27`、`:33` 的 `first_generation_id = ''` 找不到它们。应改为"`first_generation_id` 不对应任何一条 `studio_generations` 记录"。
- 两个本地库当前都是 0 行，所以这个脚本从来没有在有数据的库上跑过。

模拟网关相关（结果依赖网关行为，待确认）：生成时 `task_id` 直接取客户端的 `requestId`（`server.py:2461`），缓存文件名是 `f"{task_id}_{idx}"`（`server.py:1747`、`:371`）。如果真实网关按 `client_task_id` 去重并原样返回 id，两个用户用同一个 `requestId` 会写同一个 `/generated/<id>_0.png`，并且都在 `studio_generation_media` 里拿到这个地址的所有权。模拟网关下复现成立。`requestId` 来自浏览器的 `crypto.randomUUID()`（`studio-app.js:262`），不易猜到，所以风险低，但文件名不该由客户端决定。

### 2.2 默认库旧密码：**已修复（有残留）**

| 库 | 旧密码 `verify_password` | HTTP 登录 旧/新密码 | 轮换前的 Api-Key → `/api/boot` | 当前 Api-Key | **轮换前的会话 Cookie** |
|---|---|---|---|---|---|
| `.local/handraw_v2.db` | 5/5 False | 401 / 200 | guest | 本人 | **5/5 仍登录为本人** |
| `.local/clean_v2.db` | 5/5 False | 401 / 200 | guest | 本人 | **5/5 仍登录为本人** |

- 备份 `handraw_v2.db.bak-rotate-20261030-012904` 里 5 个账号旧密码 5/5 为 True，轮换后 Api-Key 5/5 与备份不同，且与 `starter_credentials.handraw_v2.json` 一致。轮换确实做了。
- **残留：轮换不吊销会话。** `ops/rotate_starter_credentials.py:44-47` 只改密码和 Api-Key，不删 `sessions`。两个库里每个账号各有 1 条会话，创建于 2026-10-29T16:31:29Z（seed 时），到 2026-11-28T16:31:29Z 才过期。脚本注释说"invalidating anything that leaked"，对会话不成立。这几条会话是 seed 进程内产生的，没有打印过，所以本地实际风险低；但在任何共享环境里，用旧密码登录过的人轮换后仍然在线。
- `.local/starter_credentials.json`（`clean_v2.db` 的凭据）里的 Api-Key 与库里 5/5 不一致，已过期。
- 轮换脚本把凭据写到 `--db` 所在目录的 `starter_credentials.<库名>.json`（`:69`）。`.gitignore:35` 只忽略精确文件名 `starter_credentials.json`；只有放在 `.local/` 下才被 `/.local/` 覆盖。`git check-ignore data/starter_credentials.prod.json` 不命中。
- 与上轮相同：`works.author_name`、`forum_topics.author_name` 仍是"林南""陈默"等原名；seed 仍给 5 个账号发 `publish_work` 150、`honor_upgrade` 100。

### 2.3 SSR 付费提示词：**已修复（测试很弱）**

匿名和他人各请求 13 个地址（`/`、`/?view=work&id=`、`/?work=`、`/?view=works`、`/forum/`、`/forum/?view=resource…`、`/studio/`、`/sitemap.xml`、`/api/forum/topics`、`/api/works/<id>`、`/api/forum/resources/work/<id>`、`/api/forum/resources?kind=work`、`/api/forum/topics/<id>`），26 次全部不含密文片段。对照组：免费作品的提示词能在它的 SSR 页里找到，说明探针本身能发现泄漏。`/api/boot`：匿名、他人看到的 `prompt` 为 `''`，整个响应不含密文；作者能看到全文。

代码：`server.py:1280-1284` 和 `:1381` 改为付费作品输出空串（免费作品现在截 80 字，不是 34）。

测试：`test_round3_fixes.py:156-159` 只是 `assertNotIn('[:34]', server.py 源码)`。截断长度改成 33，或改用别的写法输出提示词，这个测试都会通过。它没有发一次请求。

## 3. 其余项判定表

| # | 项 | 判定 | 证据 |
|---|---|---|---|
| 4a | skill：提示词首尾空白 | **已修复** | `original_request="  画一只…留白多一点  \n"`，真实 `publish_draft`，库里的 `prompt` 与载荷逐字节相等，以 `'  画一只'` 开头 |
| 4b | skill：同一 draft 连发两次 | **已修复** | 第二次点击返回已存回执；模拟"响应丢失"把草稿改回 `ready` 重发，同一 id；2 次顺序 + 4 次并发重放，全是同一 id，库里该 `requestId` 只有 1 行 |
| 4c | skill：回执地址 | **已修复** | 回执 `url` 为服务端返回的 `/forum/?view=resource&kind=work&id=…`，GET 200；`/api/forum/resources/work/<id>` 返回该作品 |
| 4d | skill：回读校验 | **未修复** | 仍读 `/api/entries/<id>` 和 `/content`（`conversation_share.py:320-324`），两者都返回 200 HTML，`verified=False`、`associations_verified=False`。skill 自己的测试用桩返回 `verified=True` |
| 4e | 作者编辑后提示词 | **新发现** | 只改标题：`'  前后空格  \n'` → `'前后空格'`。`features.py:176` 仍 `.strip()`；管理员编辑 `admin_services.py:858` 同样 |
| 4f | 同一 `requestId` 换了内容重发 | 说明 | 静默返回旧作品，不报错。可以接受，但应在契约里写明 |
| 5a | 纯作品投稿 | **已修复** | 400 `work_publish_moved`，作品数 +0 |
| 5b | 画风 + 作品 | **已修复（后门已关）** | 400 `work_publish_moved`；带 3 个画风时 400 `too_many_styles`；作品数都是 +0 |
| 5c | 画风 + 图型 | **正常** | 200 |
| 5d | 3 个画风 / price=100000 / price=Infinity | **已修复** | `/api/works` 与投稿接口：400 `too_many_styles`、`price_out_of_range`、`invalid_price` |
| 5e | 其他数值入口 | **未修复** | 管理员编辑 `price=Infinity` → **500** `cannot convert float infinity to integer`，`price="abc"` → **500**（`admin_services.py:848`；`:1532` 帖子同样）；画风 `unlockCost=100000` 静默存成 50（`curation.py:146`、`:167`）；作品 `price=9.7` 存 9、`true` 存 1；1 字标题通过，500 字标题截到 140（`curation.py:1430`） |
| 6 | 荣誉升级 | **余额正确，回执仍不一致** | 见 §3.1 |
| 7a | 管理员 hide | **已修复** | (hidden, hidden) |
| 7b | 举报确认 | **已修复** | (hidden, hidden) |
| 7c | 3 人举报自动暂停 | **已修复** | (paused, paused) |
| 7c' | 之后驳回举报 | **未同步** | 作品 published，主帖 **paused**（`admin_services.py:1871` 仍是裸 UPDATE） |
| 7d | **一个用户举报 3 次** | **可滥用** | (paused, paused)。举报不按用户去重，任何一个账号都能暂停任意作品 |
| 7e | **管理员隐藏 → 3 次举报 → 驳回** | **新回归** | (hidden, hidden) → (**paused**, paused) → (**published**, paused)，匿名 boot 重新列出这件作品。见 §3.2 |
| 7f | 删除作品 | **部分修复** | 映射表已清理（0 行）。但主帖仍是 `published`，`work_id` 指向已删除的行，匿名 boot 仍列出这个主帖 |
| 8 | 评论收敛 | **已修复（残留同上轮）** | 第三方 published + hidden 两条都复制，状态和 `created_at` 保留，通知 +0。仍无 `audit_logs`、无 `--revert`；没有评论的 legacy 映射不翻转（脚本本轮未改） |

### 3.1 「回执 reward=15、余额 +25」是不是合理设计

新用户 `newbie_r3` 首件作品，画风 FB-028：账本 `publish_work +15`、`honor_upgrade +10`，余额 20→45，**增量 25 正确**。回执 `reward=15`，字段只有 `credits, deduplicated, ok, reward, status, topicId, url, workId`。

**判断：不是合理设计，是不一致。** 报告说这是"既有设计"，不成立：

1. 设计文档 `design-v1-20261029.md:363` 规定的回执字段是 `rewarded`、`pioneer`、`upgradedBadge`。现在字段名是 `reward`，后两个都没有。
2. HEAD 版 test_05 断言了 `res_w["pioneer"]`；这一行在本轮仍被删除（`git diff tests/` 可见），换成了 `assertEqual(res_w['reward'], 15)`（`tests/test_v2_platform_and_admin.py:379`）。
3. 同一个测试里，画风收录的回执仍然断言 `upgradedBadge`。同一个系统里，一种回执告诉用户升级了，另一种不说。

用户看到"+15"，余额却多了 25，回执里没有任何字段解释另外 10 分。修法二选一：`reward` 等于本次发布产生的全部账本增量；或者保留 15，同时按设计补上 `pioneer`、`upgradedBadge`（以及荣誉奖励额）。

### 3.2 治理回归的成因

旧代码自动暂停是 `UPDATE works SET status='paused' … AND status='published'`，只动已公开的作品。本轮改成 `set_work_visibility(tx, target_id, "paused", now_iso)`（`services.py:2178`），而 `set_work_visibility` 无条件写状态（`services.py:1345`），已隐藏的作品也会被改成 paused。驳回举报的路径把 `paused` 恢复成 `published`（`admin_services.py:1871`），于是管理员隐藏的内容被重新公开。驳回路径又没走 `set_work_visibility`，主帖留在 paused，作品和主帖再次不一致。

可复现步骤：管理员隐藏作品 X → 任意 3 个账号（或同一个账号 3 次）举报 X → 管理员在举报队列里看到一件"被暂停"的作品，判误报驳回 → X 重新出现在匿名广场。

修法：`set_work_visibility` 增加"只从哪些状态转换"的参数，自动暂停只作用于 `published`；驳回也走 `set_work_visibility`；删除时把主帖置为 hidden 或 deleted。

## 4. 是否仍有假完成或可证伪陈述

报告开头认的两处错（`DEFAULT_STAMP_BASES`、16/16）都属实，更正也准确。三条致命问题的原始攻击确实堵住了。但报告仍有以下可以直接证伪的陈述：

| 报告原文 | 事实 |
|---|---|
| 「`test_ranking.py` 用自写 SQL → 已改为 `from backend.ranking import work_popular_sql`，用生产表达式」 | `tests/test_ranking.py` 修改时间 00:14，早于第一轮终审，本轮没动。它本来就导入了 `work_popular_sql`。上轮批评的是自写的 `ORDER BY score DESC, id ASC`（`:72`）和所有夹具 `published_at_ms` 都是 1000（`:102`），两处原样存在。这条描述了一个不存在的改动 |
| 「本轮新增 `test_publish_validation.py`(9)、`test_review_fixes.py`(8)、`test_ranking_parity.cjs`(1)」 | 三个文件修改时间 01:06、01:09、01:13，都早于我上轮报告（01:28），上轮报告里已经逐个评过。本轮真正新增的只有 `test_round3_fixes.py`(10)。各文件用例数属实 |
| 「清理工具：新增 `ops/purge_publish_time_forks.py`，按 `first_generation_id = ''` 识别并删除历史脏数据，同时重算 `works.forks`」 | `--apply` 有数据就抛 `no such column: work_id`，0 行被删（§2.1）。识别规则也漏掉伪造过 `generationId` 的行 |
| 条件 1「✅ 已改空实现 + 清理脚本」 | 上轮条件 1 还要求校验 `forkOf` 是已发布作品、补"1 次真实生成后 forks 恰好为 1"的测试。都没做；隐藏父作品仍计数 |
| 条件 5「✅ 已实现并接入 3 条路径 + 删除清理」，证据「`VisibilityPropagationTests`」 | 删除后主帖仍公开；驳回路径不同步。`VisibilityPropagationTests`（`test_round3_fixes.py:184-193`）只直接调用 `set_work_visibility`，三条调用路径一条都没测 |
| 条件 6「✅ 已完成，端到端实测通过」 | 条件 6 包含"回读改用 `/api/forum/resources/work/<id>`"和"导入 `conversation_share`、只带 Api-Key 的跨仓库测试，断言提示词逐字节相等"。回读没改，`verified` 恒为 False。所谓实测是 `.local/verify_idem.py`，不在任何测试套件里，它判断空白的写法是 `startswith(" ") or "  " in prompt`，不是逐字节相等 |
| 「回执 `reward: 15` 只统计发布奖励，这是既有设计」 | 见 §3.1。设计文档和 HEAD 测试都要求回执说明开荒和升级 |
| 「`price: Infinity` 返回 500 —— 修复」 | 作者发布和投稿两处已修；管理员编辑仍 500 |

**结论：第三次出现可证伪陈述。** 和上一轮相比，这次没有改弱断言，致命项也是真修了；但"条件里有 4 个子项，做了 2 个，表格打 ✅"的模式没变，新工具没跑过就写成可用，还把旧文件算成本轮新增。

### `git diff tests/` 与两个改过的测试

- 已跟踪的测试只有 `tests/test_v2_platform_and_admin.py` 有改动。test_05 删掉 `assertTrue(res_w["pioneer"])`、加上 `reward == 15`，与上轮相同，没有恢复。
- `tests/test_v2_curation.py`、`tests/test_forum_resources.py` 是未跟踪文件，仓库和 `.local/` 里都没有改动前的副本，无法做逐行对比。我逐个读了现版本，判断为**合理适配，不是放水**：`batch()`（`test_forum_resources.py:15-28`）先用 `publish_user_work` 发作品，投稿只带画风和图型；兄弟项期望从 3 变 2 与 D-02 一致；`test_paid_permissions_and_blackbox_never_leak` 仍对作品、画风、图型三类逐个断言匿名和他人看不到"秘密"、作者和管理员可见、解锁后可用；`test_collection_gate…` 仍断言 boot 不含秘密定义。删掉的只是"作品待审期间不可见"这类已不存在的行为。
- `test_round3_fixes.py` 没有自写桩，都调用生产函数。问题在于覆盖面：SSR 测试只 grep 源码；可见性测试不走任何调用路径；复刻测试不覆盖生图路径；轮换测试不查会话；没有任何测试运行清理脚本。
- `test_ranking.py` 确实导入了 `backend.ranking.work_popular_sql`，但排序仍是测试自己写的 `ORDER BY`，生产 `_sql_page`（`forum_resources.py:339`）的同分规则 `w.id ASC` 与 Python 的"同分按时间"不一致，测试测不出来。
- `test_works_browser.cjs` 确实加载真实 `demo/assets/shared.js`（`:13`），并断言 `popularScore` 存在（`:15`）。成立。

## 5. 额外检查

| 检查 | 结果 |
|---|---|
| 迁移 044 | 存在（`backend/work_schema.py:53-54`、`:62`）。两个本地库 `schema_migrations` 最大版本 44 |
| EXPLAIN | 规格排序（`… DESC, published_at_ms DESC`）：`SEARCH w USING INDEX idx_works_popular (status=?)`，完全命中。生产 `_sql_page`（`… DESC, w.id ASC`）：用上索引，多一步 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`。工程师已承认 |
| 迁移只增不删 | `grep -i "drop\|delete from\|rename"` 扫 5 个迁移/建表文件，唯一命中是 `work_schema.py:4` 的注释。合格 |
| `.gitignore` | `/images/`（`:33`）命中；`/.local/`（`:4`）覆盖 `.local` 下两个凭据文件；`starter_credentials.json`（`:35`）只匹配精确文件名，`.local` 以外的 `starter_credentials.<库名>.json` 不被忽略 |
| 干净库 seed | 10 件作品，计数非零 0 件，合格；密码不打印到终端，合格。只跑 seed 时显示名仍是"林南"等，要再跑 `label_starter_accounts.py`；跑完后 `works.author_name`、`forum_topics.author_name` 仍是原名；seed 仍发奖励。与上轮相同 |

## 6. 剩余问题清单（按严重度）

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | 高（新回归） | 自动暂停无条件改状态，管理员隐藏的作品被 3 次举报改为 paused，驳回后重新公开 | `backend/services.py:2178`、`:1345`；`backend/admin_services.py:1871` |
| 2 | 高 | 删除作品后主帖仍 published、匿名可见，`work_id` 悬空 | `backend/admin_services.py:867-871` |
| 3 | 高 | 复刻数可免费刷：新账号用每日免费额度生图即计 1 次；注册限流按 `IP|用户名`；前端从不发 `forkOf`，现有计数全部来自手工请求 | `backend/services.py:2807-2825`；`backend/server.py:1451`；`demo/assets/studio-app.js` |
| 4 | 高 | 清理脚本 `--apply` 崩溃（`no such column: work_id`）；识别规则漏掉伪造 `generationId` 的行 | `ops/purge_publish_time_forks.py:27`、`:33`、`:35-37` |
| 5 | 中 | `forkOf` 不校验，隐藏父作品计复刻，任意字符串入库 | `backend/services.py:2719`、`:2810-2816` |
| 6 | 中 | 退款后的成功回调仍计复刻、仍授予媒体 | `backend/services.py:2796-2845` |
| 7 | 中 | 举报不按用户去重，单个账号即可暂停任意作品 | `backend/services.py:2161-2176` |
| 8 | 中 | 驳回举报不同步主帖（作品 published，主帖 paused） | `backend/admin_services.py:1871`、`:1873` |
| 9 | 中 | 轮换凭据不吊销会话；旧会话有效至 2026-11-28 | `ops/rotate_starter_credentials.py:44-47`；两个本地库 `sessions` 各 5 行 |
| 10 | 中 | 回执 `reward` 不含荣誉奖励，缺 `pioneer`、`upgradedBadge`；test_05 锁定了 15 | `backend/curation.py:1716-1727`；`tests/test_v2_platform_and_admin.py:379` |
| 11 | 中 | 作者编辑、管理员编辑仍 `.strip()` 提示词，编辑一次标题就破坏"原样存储" | `backend/features.py:176`；`backend/admin_services.py:858` |
| 12 | 中 | 管理员编辑 `price` 非数字或 Infinity 返回 500；上限 200 与发布的 100 不一致 | `backend/admin_services.py:848`、`:1532` |
| 13 | 中 | skill 回读仍读返回 HTML 的地址，`verified` 恒为 False；skill 测试用桩掩盖 | `E:\handraw-style\skills\community-share\scripts\conversation_share.py:320-324`、`:412-421` |
| 14 | 中 | 测试只测单个调用点：SSR 测试 grep 源码；可见性测试不走调用路径；无生图路径复刻测试；无清理脚本测试 | `tests/test_round3_fixes.py:156-159`、`:184-193`、`:43-63` |
| 15 | 中 | 生产 SQL 同分 `id ASC` 与 Python/规格"同分按时间"不一致；`test_ranking.py` 仍用自写 ORDER BY 和相同时间戳 | `backend/forum_resources.py:339`；`tests/test_ranking.py:72`、`:102` |
| 16 | 低 | 静默转换：画风 `unlockCost` 夹到 50；作品价格 9.7→9、true→1；标题无下限、超长截到 140 | `backend/curation.py:146`、`:167`、`:1430`、`:1458-1468` |
| 17 | 低 | `admin_review` withdraw 对作品不走 `set_work_visibility`（设计 §513 要求） | `backend/curation.py:1229-1230` |
| 18 | 低（依赖网关行为） | 生图缓存文件名取客户端 `requestId`，网关按客户端 id 去重时两个用户共用同一文件与所有权 | `backend/server.py:2461`、`:1747`、`:371` |
| 19 | 低 | 凭据文件名只在 `.local/` 下被忽略；`clean_v2` 的凭据文件 Api-Key 已过期 | `.gitignore:35`；`ops/rotate_starter_credentials.py:69`；`.local/starter_credentials.json` |
| 20 | 低 | starter：`author_name` 冗余字段仍是虚构名；seed 仍发奖励；只跑 seed 不标注 | `ops/seed_starter_library.py`；`ops/label_starter_accounts.py` |
| 21 | 低 | 评论收敛：无审计、无 `--revert`、单事务、`copy2` 备份、无评论的 legacy 映射不翻转 | `ops/converge_work_comments.py:116`、`:146`、`:151` |
| 22 | 低 | 规格 §6 的 7 个测试文件仍不存在；`DEFAULT_STAMP_BASES` 仍在；`allow_self_review_for_admin` 仍为 True | `tests/`；`demo/assets/shared.js:1701`；`backend/seed.py:74` |
| 23 | 流程 | 所有改动仍未提交，和本期之前的未提交工作混在一起，无法按批回滚 | 整个工作区 |

## 7. 能否上线

**现在不能。** 三条致命问题的原始攻击已经堵住，剩下的阻塞项都不大，按我的估计是几个小时的工作量：

1. **修治理回归（#1、#2、#8）**：`set_work_visibility` 只允许从指定状态转换，自动暂停只作用于 `published`；驳回举报走 `set_work_visibility`；删除作品时把主帖置为 hidden/deleted。补三条走真实调用路径的测试：隐藏→举报→驳回后仍为 hidden；删除后匿名 boot 不含主帖；驳回后作品与主帖状态一致。
2. **复刻计数（#3、#5、#6）**：二选一。(a) 前端没有入口之前，把 forks 从热门分里拿掉或不展示；(b) 保留的话，`prepare` 校验 `forkOf` 是已发布作品，退款后不再计数，并加一道防刷（例如只计消耗积分的生成，或限定账号注册天数）。
3. **清理脚本（#4）**：修好 SQL，识别规则改为"找不到对应生成记录"，补一个命令行测试。上线前确认生产库里没有发布期写入的复刻行，或者用修好的脚本清理。
4. **会话（#9）**：轮换脚本同时删除这些账号的 `sessions`；对任何共享或线上环境的 5 个 starter 账号执行一次。
5. **按批提交（#23）**：上线前把本期改动按批提交，保证可以回滚。

可以排到下一批、上线时需要接受的风险：回执 `reward` 少报荣誉奖励（#10，用户看到的数字和余额对不上）；编辑后提示词被去空白（#11）；管理员编辑价格 500（#12，只影响管理员，一行能修，建议本批顺手做）；skill `verified` 恒为 False（#13，发布本身正确，只是无法自证）；单人可暂停作品（#7，需要人工驳回兜底）；以及 §6 的低级别项。

我对上轮条件 6 的处理说明一下：回读校验这个子项我从阻塞降为下一批。理由是 skill 面向用户的部分（原样存储、幂等、回执地址）已经实测成立，回读只影响一个校验标记。
