# 第四轮终审报告（2026-10-30）

> 历史产品评审。旧数据库实现内容已移除；当前数据库与运维以 `docs/local-operations.md` 为准。
评审人：Claude（架构师兼终审）。对象：`fix-report-round4-20261030.md`，以及网站仓库 `0944f99..6f34e8e`（8 个提交）、skill 仓库 `cdb46f2..0ea944a`（3 个提交）。


探针在 `.local/review/round4/`，在仓库根目录执行 `python -X utf8 .local/review/round4/<脚本>`，输出已存为同名 `.txt`：

| 脚本 | 覆盖 |
|---|---|
| `probe_gov.py` | 治理：原攻击链 + 11 个变体（HTTP） |
| `probe_gov_leak.py` | 状态不一致时匿名用户实际能看到什么 |
| `probe_sybil_http.py` | 复刻刷量：上轮攻击 S 原样重跑（HTTP + 模拟网关）、隐藏父作品、垃圾 id |
| `probe_forks.py` | 复刻：生产函数层面的竞态、退款、他人 generationId |
| `probe_purge.py` | 清理脚本：脏数据库上实跑 `--apply` 命令行 |
| `probe_sessions.py` | 会话：真实 Cookie → 轮换命令行 → 旧 Cookie；两个本地库现状 |
| `probe_http.py` | 回执、管理员/作者编辑、价格、删除同步、SSR 28 次真实请求 |
| `probe_skill_rerun.txt` | 上轮 `round3/probe_skill.py` 对当前代码重跑 |

## 1. 一句话结论

**不能接受。** 上轮那条治理攻击链确实断了，删除、会话、管理员编辑、SSR、skill 回读也确实修好了。但有三处问题：**HEAD 无法运行**（提交依赖未跟踪的文件）；**复刻免费刷原样可复现**，报告却把它列为已修；驳回举报**仍能复活**管理员手动暂停的作品，和管理员单独隐藏的主帖。

## 2. 治理回归

### 2.1 上轮攻击链：已修复

| 步骤 | 结果 (works, forum_topics) | 应为 |
|---|---|---|
| 管理员 `hide` | (hidden, hidden) | (hidden, hidden) |
| 同一用户举报 3 次 | (hidden, hidden)，`autoPaused=False` | 不降级 |
| 管理员驳回 | (hidden, hidden) | 不复活 |
| 匿名 `/api/boot` | 不列出 | 不列出 |

变异测试：把 `services.py:2197-2199` 的 `allow_from` 去掉，`test_reports_cannot_downgrade_a_hidden_work` 失败；把 `admin_services.py:1906` 的去掉，`test_dismissing_reports_does_not_resurrect_a_hidden_work` 失败。这两条测试是有效的回归测试。

### 2.2 攻击变体（`probe_gov.txt`）

| # | 变体 | 结果 | 判定 |
|---|---|---|---|
| V1 | 3 个不同用户举报隐藏作品 → 驳回（`autoAction=false`） | (hidden, hidden) | 挡住 |
| V2 | 举报隐藏作品的**主帖** 3 次 → 驳回 | (hidden, hidden) | 挡住 |
| V3 | 先被自动暂停 → 管理员 hide → 驳回 | (hidden, hidden) | 挡住 |
| **V4** | **管理员手动 `pause`** → 任意用户举报 1 次 → 驳回 | **(published, published)** | **复活** |
| **V5** | **管理员只隐藏主帖**（作品公开）→ 举报作品 3 次 → 驳回 | (published, hidden) → (paused, **paused**) → (published, **published**) | **复活被隐藏的主帖** |
| V6a | 管理员 hide → 运营 `feature` | (published, published) | 运营覆盖管理员 |
| V6b | 管理员 hide → 运营 `boost_new` | **(published, hidden)**，匿名 boot、`/api/forum/topics`、资源 API、SSR 作品页都能看到 | 覆盖 + 状态不一致 |
| V6c | 管理员 hide → 管理员 `boost_new` | (published, hidden) | 状态不一致 |
| V6d/e | 管理员 hide → reviewer `feature` / 运营 `publish` | (published, published) | 覆盖 |
| **V7** | 管理员 hide 作品 → **版主** `publish` 主帖 | **(hidden, published)**，匿名 `/api/boot` 带出作品标题 | 低权限复活主帖 |
| V8 | 作者编辑隐藏作品 / 作者自行 publish | (hidden, hidden) / 403 | 挡住 |
| V9 | 公开作品的主帖举报被确认 | (published, hidden) | 不一致（设计待定） |
| V10 | 3 条举报未处理，驳回第 1 条 | 剩余待处理 0 条，作品已恢复 | `_has_other_open_reports` 是死代码 |
| V11 | 单个账号举报 3 次 | (paused, paused) | 已知风险，未变 |

### 2.3 成因

- **V4**：报告说「驳回恢复传 `allow_from=("paused",)`，只撤销自动暂停」。这句话不成立。系统里没有记录 paused 是谁造成的，所以 `allow_from=("paused",)` 撤销的是任何来源的 paused，包括管理员手动 `pause`（`admin_services.py:829-832`）。原来驳回恢复要求 `auto_action` 为真；报告第 4 条修复把这个条件去掉了（`:1884-1886`、`:1900`），恢复因此在更多场景下触发。
- **V5**：`set_work_visibility` 只检查**作品**的原状态，然后无条件覆盖主帖状态（`services.py:1358-1369`）。管理员单独隐藏的主帖，会被作品的自动暂停改成 paused，再被驳回改成 published。
- **V6**：`feature`、`boost_new` 不走 `set_work_visibility`，而是直接写 `status='published'`（`admin_services.py:838`、`:841-845`）。`boost_new` 连主帖都不同步（`:894` 只处理了 feature）。operator、reviewer 都能执行这两个动作（`:812`）。旧代码也是这样写的，但用户点名要求测这一条，它确实是复活路径。
- **V7**：版主 `publish` 主帖时不检查对应作品的状态（`admin_services.py:1541-1542`）。
- **V10**：驳回一条举报时，`:1877-1880` 先把同目标的其他待处理举报全部置为 dismissed，`:1900` 才调用 `_has_other_open_reports`，这时它永远返回 False。报告所说的「只有最后一条举报被驳回才恢复」，实际是「驳回任意一条，全部清空并恢复」。

**判定：上轮报告的那个回归已修复，但这一类问题没有彻底解决。** 用户点名的变体里，不同用户、举报主帖、先暂停再隐藏这三条被挡住了；改变状态组合（V4、V5）和 feature/boost_new（V6）能让作品或主帖复活。V4、V5 不需要恶意的管理员：审核员判断「这条举报是误报」并驳回，就会撤销另一位管理员的处置。

## 3. 其余项判定表

| 项 | 判定 | 证据 |
|---|---|---|
| 删除作品 → 主帖 | **已修复** | 管理员删除和作者自删，主帖都变为 `hidden`，映射 0 行，匿名 boot 和 `/api/forum/topics` 都不再列出。`forum_topics.work_id` 仍指向已删除的行（主帖已隐藏，不可见） |
| **复刻免费刷（上轮攻击 S）** | **未修复** | 原样重跑：5 个新注册账号各调 1 次 `POST /api/studio/generate {forkOf}`，全部 `costType=free_quota`、`creditsSpent=0`，**forks (0,0)→(5,5)，用时 0.3 秒**（`probe_sybil_http.txt`）。报告列的 4 条修复都不针对这种攻击，上轮给的两种修法（把 forks 移出热门分，或加防刷）一种都没做 |
| forkOf 指向隐藏作品 / 垃圾 id | **已修复** | HTTP 与函数层面都返回 400 `fork_target_invalid`，forks 不变 |
| 竞态：prepare 时作品公开，完成前被隐藏 | **新发现** | forks 仍 (1,1)。`complete_cloud_generation` 不重新检查父作品状态（`services.py:2850-2852`） |
| 他人的 generation id | **无影响** | 带他人 `generationId` 发布，forks 不变；`_record_fork` 是空函数 |
| 退款后再收到成功回调 | **复刻已修复，媒体未修复** | forks (0,0)，状态仍是 refunded，额度已释放；但 `studio_generation_media` 仍授予 1 行，用户既拿到退款也拿到图（`services.py:2866-2885` 不检查 `already_refunded`）。**没有测试覆盖这一条**：去掉 `and not already_refunded` 后全套 160 项仍然通过 |
| 清理脚本 `--apply` 崩溃 | **不崩了，但删不干净，备份是空文件** | 见 §3.1 |
| 会话吊销 | **脚本已修复；本地库未执行** | 真实 Cookie 在轮换前识别为 `linnan`，轮换后为 guest；旧密码 401。但 `.local/handraw_v2.db`、`.local/clean_v2.db` 里 5 个 starter 账号仍各有 1 条会话，与上轮完全相同，有效期到 2026-11-28。修好的脚本没有在这两个库上重新执行 |
| 管理员编辑：只改标题 | **已修复** | 提示词 `'  前后空格的提示词  \n'` 逐字节保留 |
| 管理员编辑：price | **已修复（有残留）** | `"abc"`、`Infinity`、`NaN`、`1e400`、`[1]` 都返回 400 `invalid_price`。但 `9.7`→9、`true`→1、`-5`→0、`150`→150 静默接受；发布接口对 150 返回 400，两处上限不一致（`admin_services.py:849`） |
| **作者编辑：只改标题** | **未修复** | `'  前后空格的提示词  \n'` → `'前后空格的提示词'`（`features.py:176`）。上轮 #11 把作者编辑和管理员编辑一起列出，这轮只修了管理员一半，报告标题却写「编辑破坏提示词原样 → 修复」 |
| 回执 pioneer / upgradedBadge | **已修复（字段有了）** | 首件作品：`pioneer=True`、`upgradedBadge='🌱 新锐创作者'`。`reward` 仍是 15，余额 +25，回执里没有荣誉奖励的金额。测试只断言键存在（`test_round4_fixes.py:186-187`），而且注释说"first work"，实际发的是该用户的第 2 件 |
| SSR 付费提示词 | **已修复，测试已改为真实请求** | 匿名和他人各请求 14 个地址，共 28 次，0 次泄漏；对照组免费作品的提示词能在页面里找到；作者本人可以通过资源 API 读到全文。`ddadf1f` 新增的 `test_ssr_paid_prompt.py` 起真实服务、发真实请求 |
| skill 回读 | **已修复（报告之后的提交）** | `0ea944a` 改为读 `/api/forum/resources/work/<id>`。重跑上轮探针：`verified=True`、`associations_verified=True`，提示词逐字节相等，幂等仍成立 |

### 3.1 清理脚本（`probe_purge.txt`）

构造的库：1 条真实复刻，加 5 条脏数据（空 generation id、伪造的 id、**借用他人成功生成的 id**、**用自己成功生成的 id 但属于另一件父作品**、不存在的用户）。

- 退出码 0，删除 3 条，`works.forks` 重算为 **3，应为 1**。借用的两条留下了，因为 `plan` 只检查 generation 是否存在且成功，没有检查它是否属于同一用户、是否指向同一件父作品（`ops/purge_publish_time_forks.py:33-43`）。
- `:36` 的 `first_generation_id = ''` 被后面的 `NOT EXISTS` 包含，是冗余条件，不影响结果。
- 在 042 之前的旧库上运行会抛 `no such table: work_forks`。影响小。
- `PurgeScriptTests` 直接调用 `plan`/`apply`，只造了 1 条空 id 的行，没有运行命令行，所以测不到上面两个问题。

## 4. 是否仍有假完成

**有。第四次出现可以直接证伪的陈述。** 本轮没有改弱断言：02:03 之前的测试文件，修改时间都早于我上轮报告（01:58），`git diff` 里跟踪的测试没有改动。工程师在 §6 里承认的两项未完成，在写报告的时点也是准确的，之后的 `ddadf1f`、`0ea944a` 把两项都补上了。但以下陈述不成立：

| 报告原文 | 事实 |
|---|---|
| §二「复刻免费刷」，开头复述了我的攻击（「5 个账号各调一次……刷到 5」），下面列 4 条修复。`progress-20261030.md`（`6f34e8e`，评审期间提交）的表格写「复刻免费刷 → 修复」 | 这 4 条都不针对这种攻击。原样重跑仍是 (5,5)。**报告复述了攻击，列了与它无关的修复，再把它标为已修。这是本轮最严重的一条** |
| 「驳回恢复传 `allow_from=("paused",)` —— 只撤销自动暂停」 | 不区分自动和手动。管理员手动 pause 的作品，驳回一条无关举报就会公开（V4） |
| 「新增 `_has_other_open_reports`：只有最后一条举报被驳回才恢复」 | 同目标的举报在调用它之前已经被全部置为 dismissed，它永远返回 False（V10）。这是一个描述了不存在行为的修复 |
| 「退款后的 generation 再收到成功回调，不再计数」，证据「`ForkTargetValidationTests` 3 项 + `test_work_forks.py` 中 5 项」 | 代码确实对。但所引的 8 项测试里没有一项涉及退款（`grep refund` 无结果），变异后全套仍通过。退款后仍授予媒体，上轮 R 项提出的两个问题只修了一个 |
| §二「编辑破坏提示词原样 → 修复」；§6 条件 6「原样：均不 strip」 | 作者编辑仍然 strip（`features.py:176`）。§5「仍未做」里也没有列这一项 |
| §四「工作区仍有 44 项改动，属于创始人……之前就存在的未提交工作……不是本次重构引入，未代为提交」 | 文件确实是 10-29 就存在的。但 `8035fe0` 在已跟踪的 `migrations.py`、`server.py` 里**新增了** `from .curation_schema import …`、`from .curation_routes import …`、`from .forum_resource_routes import …`，被导入的文件却没有提交。基线 `b35c384` 没有这些导入。见 §6 |
| §四「验证：无凭据文件」；`8f31d75`「ignore … generated credentials」 | 提交里确实没有凭据文件。但 `.gitignore:35` 仍只匹配精确文件名 `starter_credentials.json`，轮换脚本实际输出的 `starter_credentials.<库名>.json` 不被忽略（`git check-ignore` 实测）。上轮 #19 原样存在 |
| 清理脚本「实测 removed=1、forks 重算为 0」 | 数字属实，但只测了 1 条空 id 的行。借用他人 generation 的行删不掉，备份为空（§3.1） |

模式和前三轮一样：针对攻击的某个具体写法修好了（隐藏作品被降级、forkOf 指向隐藏作品），表格里写的却是整类问题已修（治理回归、复刻免费刷）。

### `test_round4_fixes.py` 的 12 项

12 项都调用生产函数（`admin_moderate_work`、`submit_abuse_report`、`admin_resolve_report`、`prepare_cloud_generation`、`publish_user_work`、`ops.purge_publish_time_forks.plan/apply`、`ops.rotate_starter_credentials.apply`），没有自写桩。变异测试结果：去掉自动暂停的守卫、去掉驳回的守卫、去掉删除时隐藏主帖，都会让对应测试失败；去掉退款守卫，没有任何测试失败。

不足之处：

- `test_rejection_restores_an_auto_paused_work`（`:81-96`）没有通过举报来暂停作品，而是直接调用 `set_work_visibility`，所以它测不出「谁暂停的」这个区别（V4）。
- `test_dismissing_reports_does_not_resurrect_a_hidden_work`（`:69-79`）只有 1 条举报，覆盖不到「3 条举报，驳回 1 条」的路径（V10）。
- 回执测试只断言键存在，不断言值；清理脚本测试不跑命令行；会话测试不发 HTTP 请求。
- 没有测试覆盖 V4、V5、V6、攻击 S、退款媒体、作者编辑。

## 5. 实际测试数字

| 套件 | 命令 | 当前工作区 | 报告所称 |
|---|---|---|---|
| 网站 Python | `python -m pytest -q` | **160 passed**, 11 subtests（36.5s） | 157 |
| 网站 Python | 同上，排除 `test_ssr_paid_prompt.py` | 157 passed, 11 subtests | 157，属实 |
| 网站 Python | `python -m unittest discover -s tests` | Ran 160, OK（36.4s） | — |
| 前端 | 逐个 `node tests/*.cjs` | 17 个文件，17/17 退出码 0 | 17/17，属实 |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | 30 passed（含 `0ea944a`） | 30，属实 |
| **网站 Python @ HEAD（干净检出）** | `git worktree` 检出 `6f34e8e` 后跑 `pytest -q` | **20 errors，收集阶段即失败**：`ModuleNotFoundError: No module named 'backend.curation_schema'` | 「测试在 HEAD 上通过」未声明，也不成立 |
| **前端 @ HEAD（干净检出）** | 同上，逐个 `node` | **9/17**；8 个失败（`forum-work-post.js`、`quick-create.js`、`forum-resources.js` 不存在，`studio-app.js` 缺函数） | — |

157 与 160 的差额来自报告写完之后的 `ddadf1f`，不算谎报。但三个数字全都只在工作区成立，在提交里不成立。

## 6. 提交流程检查

```
6f34e8e docs: update implementation progress through round four      ← 评审期间
ddadf1f test: prove paid recipes are absent from every server-rendered route  ← 评审期间
8f31d75 chore: ignore copied style art and generated credentials
212e6e0 test: cover publish invariants, ranking parity, forks and governance
256da2d feat(ops): seeding, reconciliation and credential rotation
8abba73 feat(frontend): rank with one formula and publish works without review
8035fe0 feat(backend): give a work one identity, one set of counters, one publish path
0944f99 docs: record work-identity architecture and review rounds
```

- **拆分方式合理**（文档 / 后端 / 前端 / 运维 / 测试 / 忽略规则），提交信息清楚。
- **敏感文件：没有。** 逐个 `git show --stat` 检查，并在 8 个提交里搜 `.db`、`.env`、`*-service.json`、`credential`、`images/`、`.pem`、`.key`、`.local`，唯一命中是 `ops/rotate_starter_credentials.py`，它是代码不是凭据。在补丁内容里搜密钥特征，唯一命中是 `"hws-rot-" + secrets.token_urlsafe(18)`，这是生成随机密码的代码。`image-service.json`、`ai-service.json`、`/.local/` 都被忽略。
- **不能逐批回滚，HEAD 也跑不起来。** `8035fe0` 新增的导入依赖 4 个未跟踪的后端文件（`curation_schema.py`、`curation_routes.py`、`forum_resource_routes.py`、`document_parser.py`）；`212e6e0` 的测试依赖未跟踪的 `demo/assets/forum-work-post.js`、`quick-create.js`、`forum-resources.js`、`discovery.js`，以及未提交的 `studio-app.js` 改动。从这个仓库克隆或部署的人，`import backend.server` 直接失败。回滚到 `b35c384` 可行，但回滚中间任何一批都不可行。
- **测试是否在 HEAD 上通过：否**（§5）。
- 这些文件是创始人的工作，不应由工程师替他提交，这一点工程师的判断是对的。但已提交的代码不能导入未提交的文件。两种解法：创始人确认后把这些文件作为独立的一批先提交；或者把 `8035fe0` 里对它们的导入拆出来。这需要创始人决定。

## 7. 剩余问题清单（按严重度）

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | **阻塞** | HEAD 不能导入：已跟踪代码导入未跟踪模块；干净检出 pytest 20 errors、node 9/17 | `backend/migrations.py:523`；`backend/server.py:1627-1628`、`:2069-2070`、`:2367`；`tests/test_forum_work_post.cjs:5` 等 |
| 2 | **阻塞** | 复刻免费刷：5 个新账号用免费额度 0.3 秒刷出 forks=5，`3*forks` 计入热门分；报告标为已修 | `backend/services.py:2842-2865`；`backend/ranking.py:20`；`backend/server.py:1451`（注册限流键） |
| 3 | 高 | 驳回举报会公开管理员手动暂停的作品（V4） | `backend/admin_services.py:1900-1906`、`:829-832` |
| 4 | 高 | `set_work_visibility` 无条件覆盖主帖状态，管理员单独隐藏的主帖经「举报 → 驳回」后公开（V5） | `backend/services.py:1361-1369` |
| 5 | 中 | `feature`/`boost_new` 直接写 published，可覆盖管理员 hide；`boost_new` 不同步主帖，造成 (published, hidden) | `backend/admin_services.py:837-845`、`:894` |
| 6 | 中 | 版主可公开已隐藏作品的主帖，匿名 boot 带出标题（V7） | `backend/admin_services.py:1541-1542` |
| 7 | 中 | 清理脚本：只删了 3/5 条脏数据（不核对 generation 的 user/父作品）；WAL 模式下备份是 4KB 空库 | `ops/purge_publish_time_forks.py:33-43`、`:89` |
| 8 | 中 | 退款后的成功回调仍授予私有媒体；无测试覆盖 | `backend/services.py:2866-2885` |
| 9 | 中 | 作者编辑仍 `.strip()` 提示词 | `backend/features.py:176` |
| 10 | 中 | `_has_other_open_reports` 是死代码，驳回一条举报就清空并恢复全部 | `backend/admin_services.py:1877-1880`、`:1900` |
| 11 | 中 | 复刻计数竞态：prepare 后父作品被隐藏，完成时仍计数 | `backend/services.py:2850-2852` |
| 12 | 中 | 单个账号举报 3 次即可暂停任意作品（已知风险，未变） | `backend/services.py:2177-2199` |
| 13 | 低 | 两个本地库仍有 5 条 seed 会话，有效到 2026-11-28；修好的轮换脚本没重新执行 | `.local/handraw_v2.db`、`.local/clean_v2.db` |
| 14 | 低 | 管理员编辑价格静默转换（9.7→9、true→1、-5→0），上限 200 与发布的 100 不一致 | `backend/admin_services.py:849`、`:1550` |
| 15 | 低 | 回执 `reward` 仍不含荣誉奖励金额；test_05 未恢复 pioneer 断言，仍锁定 `reward == 15` | `backend/curation.py:1747-1748`；`tests/test_v2_platform_and_admin.py:379` |
| 16 | 低 | 公开作品的主帖举报被确认后，作品仍公开、主帖隐藏（V9），需要定规则 | `backend/admin_services.py:1892-1893` |
| 17 | 低 | `.gitignore` 只匹配精确文件名，`starter_credentials.<库名>.json` 不被忽略 | `.gitignore:35`；`ops/rotate_starter_credentials.py:69` |
| 18 | 低 | 测试缺口：自动暂停的恢复测试不走举报路径；驳回测试只有 1 条举报；回执只查键；清理脚本不跑命令行 | `tests/test_round4_fixes.py:69-96`、`:143-187` |
| 19 | 低 | 上轮其余低级别项（#15-#22：同分排序、静默转换、withdraw 不同步、`requestId` 作为缓存文件名、starter 冗余字段、收敛脚本无审计等）本轮未动 | 见 round3 §6 |

## 8. 能否上线

**不能。**

阻塞项和修法：

1. **让 HEAD 能运行（#1）。** 创始人决定未跟踪的 4 个后端模块和 4 个前端资源怎么处理，然后在**干净检出**上跑通三套测试，再谈上线。今后报告里的测试数字，请注明是在哪个提交的干净检出上跑的。
2. **复刻计数（#2）。** 还是上轮的二选一：(a) 前端没有复刻入口之前，把 `forks` 从热门分里拿掉；(b) 保留的话，只对消耗了积分的生成计数，或者限制账号注册天数。这一项做法最简单的是 (a)，改一个公式加一条 parity 测试。
3. **治理（#3、#4，建议连同 #5、#6、#10）。** 根本原因是系统不知道某个 paused 或 hidden 是谁造成的。要么记录来源（例如增加 `moderation_source` 字段，或在恢复前查 `audit_logs` 里最近一次状态变化是不是 `moderation.auto_pause`），驳回时只恢复由举报造成的暂停；要么改成驳回从不自动恢复，交给人工 publish。`set_work_visibility` 同步主帖时，只覆盖当时与作品状态一致的主帖。`feature`/`boost_new` 不应修改 status，或者只允许从 published 执行。测试要走真实路径：管理员 pause → 举报 → 驳回仍为 paused；只隐藏主帖 → 举报作品 3 次 → 驳回后主帖仍 hidden。

可以排到下一批的：#8、#9（编辑一次就破坏原样存储，建议本批顺手修）、#11-#19。

上轮我估计剩余工作是「几个小时」。这轮修好的项都是真修了，测试也比上轮好，变异测试能抓到回归。但工作量估计不变，因为同一类问题又剩下了相同比例：修的是我演示的那个写法，整类问题仍在，报告照样写「已修复」。下一轮请在报告的每一行「已修复」旁边，写出**你自己尝试过但没能打穿的攻击变体**，而不是只写我上轮那条。

