# 第五轮终审报告（2026-10-30）

评审人：Claude（架构师兼终审）。对象：网站仓库 `6f34e8e..457bab8`（10 个提交，重点 `4636feb`、`8e2cf85`、`457bab8`）。本轮工程师**没有写修复报告**，`progress-20261030.md` 也没更新，以下核对的「工程师声称」来自用户转述和提交信息。

方法：不采信自述。HEAD 用 `git worktree add --detach` 干净检出（`git status --porcelain` 为 0 行）；临时库上起真实服务进程，只用 `Api-Key` 调接口；生图走本地模拟网关的真实 HTTP；论坛页面用 headless Chromium 打开；治理探针同时在 HEAD、工作区和上轮的 `6f34e8e` 上跑做对照。未改产品代码，本地库只用 `mode=ro` + `backup` 读取。`backend/services.py`、`admin_services.py`、`curation.py`、`ranking.py`、`ops/` 在工作区与 HEAD 之间 `git diff` 为空，所以治理、复刻、清理三项的结论对两边都成立（两边都实跑过，结果相同）。

探针在 `.local/review/round5/`，以被测代码目录为 cwd 执行 `python -X utf8 <脚本>`，输出存为同名 `.txt`：

| 脚本 | 覆盖 |
|---|---|
| `probe_gov5.py` | 治理：V4–V7 重跑 + 新变体 N1–N8（HTTP）；`_on_6f34e8e.txt` 为上轮代码对照 |
| `rerun_round4_probe_gov.txt` / `rerun_round4_probe_purge.txt` | 上轮探针原样在 HEAD 重跑 |
| `probe_sybil5.py` | 复刻刷量：原攻击、垃圾作品绕过、跨天、删除、sample、借 generation、并发、点赞对照 |
| `probe_purge5.py` | 清理脚本：脏库 + 活跃 WAL 上实跑 `--apply` 命令行 |
| `probe_head_routes.py`、`probe_skill_on_HEAD.txt` | HEAD 部署实际提供哪些接口；skill 回读 |
| `probe_browser_forum.py`、`probe_browser_pages.py` | 浏览器打开论坛帖子、发布回执、主要页面 |

## 1. 一句话结论

**不能接受。** 复刻刷量和清理脚本这次是真修好了，HEAD 的测试数字也属实；但 HEAD 上的论坛**打不开任何一个帖子**（测试变绿靠的是移出了能暴露问题的测试），治理上轮点名的 V5、V7 原样存在，并且本轮改动引入了一个新回归：**已确认违规而隐藏的作品，再有人举报一次、被驳回，就会重新公开。**

## 2. 四个阻塞项逐项判定

| # | 阻塞项 | 判定 |
|---|---|---|
| 1 | HEAD 能否运行 | **部分修复**：后端能启动、三套测试全绿；论坛帖子详情页和发布回执页全部报错，skill 回读失败 |
| 2 | 复刻免费刷 | **已修复**（作为上线阻塞项）；有可接受的残留 |
| 3 | 治理 | **部分修复，并引入回归**：V4、V6 修好；V5、V7 未动；新变体 N1–N5 中 5 条打穿，其中 N3、N4、N5 是本轮新引入的 |
| 4 | 清理脚本 | **已修复** |

### 2.1 HEAD 能否运行：部分修复

**测试数字属实。** 干净检出 `457bab8`：

- `python -m pytest -q`：**142 passed, 3 skipped**（34.7s）
- `python -m unittest discover -s tests`：**Ran 145, OK (skipped=3)**
- `node tests/<each>.cjs`：**9 个文件，9/9 退出码 0**
- 3 个 skip 都在 `test_seed_starter_library.py`，原因是 style 图片不在仓库里（`images/` 被忽略），属实，合理。
- 服务能启动；`/`、`/studio.html`、`/forum/`、`/admin.html`、`/api/boot` 都返回 200，浏览器打开这 4 个页面没有 pageerror 或 console error。
- 用 HEAD 建的库，再用工作区代码（含 `curation_schema`）启动，迁移 30/31 和 045/046 不冲突，升级成功。

**但 HEAD 上论坛的帖子详情打不开**（`probe_browser_forum_HEAD.txt`）。在 HEAD 上发布一件作品、一篇普通帖，用浏览器打开：

| 页面 | HEAD | 工作区（对照） |
|---|---|---|
| 普通帖 `/forum/?view=topic&id=…` | 「暂时无法加载论坛 · Cannot read properties of undefined (reading 'fromTopic')」 | 正常显示 |
| 作品主帖 `/forum/?view=topic&id=…` | 同上 | 正常显示 |
| 发布回执链接 `/forum/?view=resource&kind=work&id=…` | 「暂时无法加载论坛 · Cannot read properties of undefined (reading 'render')」 | 正常显示作品 |
| 论坛首页 `/forum/` | 正常 | 正常 |

原因：已提交的 `demo/assets/forum-app.js:1570` **无条件**调用 `window.HandrawForumWork.fromTopic(...)`，`:1531`、`:2382` 调用 `window.HandrawResourcePages.render(...)`。这两个对象只在未跟踪的 `demo/assets/forum-work-post.js`、`forum-resources.js` 里定义，HEAD 的 `demo/forum.html` 也不加载它们。所以从论坛列表点进**任何一个帖子**都会报错。这是上轮 §6 已经指出的同一组未跟踪文件。

**skill 回读在 HEAD 上失败**（`probe_skill_on_HEAD.txt`）。上轮 `round3/probe_skill.py` 在 HEAD 上重跑：发布成功、幂等仍成立，但回执是 `verified=False, associations_verified=False`；工作区是 `True/True`。原因是 skill 回读的 `/api/forum/resources/work/<id>`（`E:\handraw-style\skills\community-share\scripts\conversation_share.py:323`）由未跟踪的 `backend/forum_resource_routes.py` 提供。上轮判为「已修复」的 skill 回读，只在工作区成立。

**缺失的接口不报错。** `27a071d` 把 `curation_routes`、`forum_resource_routes` 的导入失败改为静默跳过（`backend/server.py:1627-1638`、`:2075-2086`），请求落到 SPA 兜底，返回 **200 + 首页 HTML**（`probe_head_routes.txt`：`/api/forum/resources/work/<id>`、`/api/forum/resource-topics/<id>`、`/api/curation/mine`、`/api/curation/review-queue` 全是 200 HTML）。客户端无法区分「接口不存在」和「成功」。

**测试为什么是绿的。** `786f249`/`457bab8` 移出的 8 个 Node 测试，复制回 HEAD 后 **8/8 失败**（`ENOENT` 或断言失败），它们正是会暴露上述依赖的测试。HEAD 上没有任何测试在浏览器里打开一个帖子。

**判定**：我上轮给的两种解法是「把未跟踪文件作为独立一批提交」或「把 `8035fe0` 里对它们的依赖拆出来」。工程师只拆了后端一半（导入变为可选），前端已提交代码仍然依赖未提交文件。「HEAD 能跑测试」成立，「HEAD 能上线」不成立。这一项仍需要创始人决定：要么把这些模块和资源作为一批提交，要么让 `forum-app.js` 对这两个对象做可选调用，并在 HEAD 上补一条打开帖子的浏览器测试。

### 2.2 复刻免费刷：已修复（作为阻塞项）

`probe_sybil5.txt`（HEAD 与工作区结果相同）：

| # | 攻击 | 结果 |
|---|---|---|
| S1 | 上轮原样：5 个新账号各调 1 次 `generate {forkOf}` | 5 次都是 `free_quota` 成功生图，**forks 0** ✅ |
| S2 | 绕过：10 个新账号各先发 1 件垃圾作品（免审，1 次上传 + 1 次 POST），再复刻 | **forks 8**，用时 0.9 秒；第 9、10 个被每日上限挡住 |
| S3 | 把 S2 的 8 行 `created_at` 改到 3 天前，再来 8 个号 | **forks 16**。上限按 UTC 自然日（`curation.py:1607`），没有累计上限：每件作品每月最多约 240 |
| S4 | 复刻记账后删掉垃圾作品 | forks 不变。门槛只在记账时检查 |
| S5 | 请求体带 `engine:"sample"` | 被忽略，入库为 `live`；sample 路径（`services.py:2468`）不写 `fork_work_id`，走不通 |
| S6 | 发布子作品时带别人成功的 `generationId` | 发布 200，forks 不变（`_record_fork` 是空函数）✅ |
| S7 | 12 个合格账号**并发**完成复刻 | forks 8，上限在 `BEGIN IMMEDIATE` 事务里，没有竞态 ✅ |
| S8 | 对照：10 个新账号各点 1 个赞 | **likes 10**，没有任何门槛 |
| S9 | 权重 | SQL `(likes + cheers + 2 * favorites + forks)`、`ranking.work_popular_score`、`shared.js:1610-1614` 一致，都是 1 倍；查询计划走 `idx_works_popular_v2`；旧索引已删 |

**判定**：上轮阻塞的理由是「免费额度 0.3 秒刷出 forks=5，并以 3 倍计入热门分」。现在 forks 权重和点赞一样是 1 倍，每件作品每天最多 +8，而点赞没有任何门槛。复刻已经不是刷热门分最便宜的路径，可以从阻塞清单划掉。

但用户转述的「全新账号刷不动」需要加限定：只对**一件作品都没发过的**账号成立。门槛「至少 1 件已发布作品」的成本是一次免审发布，S2 已证明可以绕过。残留问题见 §6 #8、#9：门槛形同虚设；没有累计上限；注册限流的键是「IP + 用户名」（`server.py:1451`），同一 IP 换个用户名就不受限，这是刷赞和刷复刻的共同根源，不属于本项范围；每次复刻都是一次真实网关调用，本次探针共触发 37 次，费用由平台承担。

变异测试：把 `daily_cap = 8` 改成 `10**9`，全套 **142 passed，没有任何测试失败**。每日上限没有测试。去掉「已有作品」门槛，`test_brand_new_account_generation_does_not_book_a_fork` 失败，这一条有覆盖。

### 2.3 治理：部分修复，并引入回归

`probe_gov5.txt`（HEAD）、`probe_gov5_worktree.txt`（工作区，结果相同）、`probe_gov5_on_6f34e8e.txt`（上轮代码对照）。状态写作 (作品, 主帖)。

| # | 变体 | 6f34e8e（上轮） | HEAD（本轮） | 判定 |
|---|---|---|---|---|
| V4 | 管理员 pause → 举报 1 次 → 驳回 | (published, published) | (paused, paused)，来源 `moderator` | **已修复** |
| V5 | 管理员只隐藏主帖 → 举报作品 3 次 → 驳回 | (published, published) | **(published, published)**，匿名 boot 列出主帖 | **未修复** |
| V6a–d | 隐藏后 operator/admin `feature`、`boost_new`；暂停后 operator `feature` | 全部复活或不一致 | 全部 409，状态不变 | **已修复** |
| V6e | 管理员 hide → operator `publish` | (published, published) | (published, published) | 未变，属于权限层级问题，待定规则 |
| V7a | 管理员 hide 作品 → 版主 `publish` 主帖（`/api/admin/topics/<id>/moderate`） | (hidden, published) | **(hidden, published)**，匿名 boot 列出主帖 | **未修复** |
| V7b | 同上，走 `/api/forum/moderate` | (hidden, published) | **(hidden, published)** | **未修复**（第二个入口） |
| N1 | 举报自动暂停 → **版主**隐藏主帖 → 驳回 | (published, published) | **(published, published)** | 打穿 |
| N2 | 举报自动暂停 → **管理员**经 `/api/forum/moderate` 隐藏主帖 → 驳回 | (published, published) | **(published, published)** | 打穿 |
| **N3** | 举报**被确认**（作品隐藏）→ 另一人再举报 1 次 → 驳回这条新举报 | (hidden, hidden) | **(published, published)**，匿名 boot 列出作品 | **本轮引入的回归** |
| **N4** | 主帖举报被确认（主帖隐藏）→ 再举报主帖 → 驳回 | 主帖 hidden | **主帖 published** | **本轮引入的回归** |
| **N5** | 主帖被举报 3 次自动暂停 → 驳回（误报，应恢复） | 主帖 published | **主帖仍 paused** | **本轮引入的回归** |
| N6 | 作者编辑 / 运营编辑时在请求体里带 `status_source`、`statusSource`、`status` | — | 被忽略，来源仍是 `moderator`，后续驳回不复活 | 挡住 |
| N7（=V10） | 3 条待处理举报，驳回 1 条 | 剩 0 条，恢复 | 剩 0 条，恢复 | 未变，`_has_other_open_reports` 仍是死代码 |
| N8（=V9） | 公开作品的主帖举报被确认 | (published, hidden) | (published, hidden) | 未变，待定规则 |

成因：

- **N3/N4（最严重）**：确认举报时把来源记为 `report`（`admin_services.py:1888-1892`、`:1894`），驳回时又允许撤销 `report` 来源的 `paused` **和 `hidden`**（`:1909-1918`）。于是「自动暂停（可撤销）」和「审核员确认违规（不可撤销）」共用同一个来源值。`submit_abuse_report` 不检查目标当前状态（`services.py:2161-2198`），任何人都可以对一件已确认违规的作品再举报一次；只要下一位审核员判断这条新举报是误报并驳回，违规内容就重新公开。这条在上轮代码上是挡住的。`:1886-1887` 的注释写「so a later dismissal knows it may undo it」，说明这是有意设计，不是笔误。
- **N5**：主帖的自动暂停（`services.py:2218`）不写 `status_source`，而驳回的恢复条件要求 `status_source = 'report'`（`admin_services.py:1916`），所以被误报暂停的主帖再也恢复不了。
- **V5/N1/N2**：`set_work_visibility` 只检查**作品**的来源，然后无条件覆盖主帖的 `status` 和 `status_source`（`services.py:1380-1384`）。两个主帖审核入口隐藏主帖时都不写 `status_source`（`admin_services.py:1538-1539`、`services.py:2101-2106`）。上轮报告 §8 第 3 条已经要求「`set_work_visibility` 同步主帖时，只覆盖当时与作品状态一致的主帖」，本轮没做。
- **V7**：两个主帖 `publish` 入口都不检查对应作品的状态（`admin_services.py:1536-1537`、`services.py:2107-2108`），本轮没改。

测试：`test_status_provenance.py`（8 项）和 `test_round4_fixes.py` 都调用生产函数。变异测试：去掉驳回的来源守卫（`allow_from`/`allow_sources` 改为 `None`），有 1 项失败，所以 V4 有真回归测试。但没有任何测试覆盖主帖级审核、版主操作、确认后再驳回、主帖自动暂停。`test_rejection_restores_a_report_paused_work` 仍是直接调用 `set_work_visibility`，不走举报路径。

### 2.4 清理脚本：已修复

`probe_purge5.txt`。构造的库：2 条**真实**复刻（复刻者各有 1 件已发布作品，满足新门槛），外加 5 条脏数据：空 generation id、伪造的 id、**借用他人成功的 generation**、自己成功的 generation 但指向另一件父作品、自己指向本作品但**已退款**的 generation。服务连接保持打开，WAL 里有 2.1MB 未落盘数据，其中包括一次只在 WAL 里的标题修改。

- 干跑列出 5 条，与构造的脏数据一一对应。
- `--apply` 退出码 0，删除 5 条；剩下的正好是 2 条真实复刻；`works.forks` 重算为父作品 **2**、另一件作品 **1**，都正确。
- **备份可用**：606KB，`PRAGMA integrity_check = ok`，`works/users/work_forks/studio_generations` 行数与执行前一致，**只在 WAL 里的标题在备份里**。
- 再跑一次：0 条，「无需清理」，幂等。
- 上轮探针原样重跑（`rerun_round4_probe_purge.txt`）：5 条全删，备份 44 张表。那份输出里 forks 为 0 而不是 1，是因为上轮探针里的 honest 账号没有作品，被新门槛挡住了，不是清理脚本的问题。
- 新增 2 条测试（`test_round4_fixes.py`：借用他人 generation、备份含数据）。
- 残留（低）：042 之前的旧库上仍抛 `no such table: work_forks` 的 traceback（`ops/purge_publish_time_forks.py:34`）；「备份非空」只检查 `works` 行数 ≥ 1，空库会误判为备份失败而中止（不影响正确性）。

## 3. HEAD 是否能运行

| 检查 | HEAD `457bab8` 干净检出 |
|---|---|
| `python -m pytest -q` | **142 passed, 3 skipped** |
| `python -m unittest discover -s tests` | **Ran 145, OK (skipped=3)** |
| `node tests/<each>.cjs` | **9/9** |
| 服务启动、4 个主要页面、`/api/boot` | 200，无页面错误 |
| 浏览器打开任意论坛帖子（普通帖、作品主帖） | **报错，0/2** |
| 浏览器打开发布回执链接 | **报错** |
| skill 发布后回读 | **`verified=False`** |

**测试能跑，论坛帖子打不开。** 工程师转述的 142/3、9/9 属实。

## 4. 是否仍有假完成

**有，但性质和前几轮不同。** 这轮的数字都属实，复刻和清理两项是真修好了，测试也没有改弱。问题在于「全部修复」这个总结论不成立，有几处说法可以证伪。

### 4.1 断言没有改弱

逐个看了 `6f34e8e..HEAD` 里跟踪测试的 diff：

- `test_ranking.py`：21 → 13，跟随权重从 3 改为 1，是行为变更，不是放宽。
- `test_review_fixes.py`：索引名改为 `_v2`，并新增了「旧索引已删」的断言，比原来更严。
- `test_work_forks.py`：给复刻者补发一件作品以满足新门槛，并新增了「新账号不计数」的用例。
- `test_round4_fixes.py`：自动暂停的用例改名并补上 `source="report"`，新增「管理员暂停不被驳回撤销」、借用 generation、备份含数据 3 项。
- `test_seed_starter_library.py`：没有图片时 `skipUnless`，原因属实。

### 4.2 HEAD 是否干净

`457bab8` 之后 `git status --porcelain` 为 0 行；`git ls-files tests` 里没有被移出的那 12 个文件。`4636feb` 曾用 `git add tests/` 把 12 个文件（1829 行）加回来，`457bab8` 又原样移出，两者内容一致。HEAD 是干净的，但 `4636feb` 这个提交单独检出跑不通，以后 `git bisect` 会踩到。提交里没有 `.db`、凭据、`.env`、`images/`。

### 4.3 可以证伪的陈述

| 陈述 | 事实 |
|---|---|
| 「工程师声称全部修复」（用户转述） | 治理一项，上轮点名的 V5、V7 原样存在（§2.3），上轮 §8 写明了修法；本轮又引入 N3/N4/N5 三个回归。HEAD 论坛帖子打不开（§2.1） |
| `4636feb`：「a dismissal now only undoes a change the report flow itself made」，修的是「dismissing a report could republish moderated content」 | 「审核员确认违规」也被记成 report flow 的改动。N3：已确认违规的作品，驳回一条新举报后重新公开。这正是该提交声称修掉的那一类问题，而且在上轮代码上是挡住的 |
| 用户转述：「驳回只撤销 `report` 来源的改动」 | 作品侧成立；主帖侧不成立。管理员或版主隐藏的主帖经「举报作品 → 驳回」后公开（V5/N1/N2），因为同步主帖时不检查主帖自己的来源 |
| `27a071d`：「the tree boots and the shipped tests run whether or not the feature modules are present」 | 后端成立。没有说明的是：已提交的 `forum-app.js` 仍然依赖这些模块配套的前端文件，HEAD 上任何帖子都打不开 |
| `786f249`/`457bab8`：这些测试「exercise the curation and forum-resource modules, which are not part of this history」 | `curation.py`、`forum_resources.py`、`resource_discussions.py` 都在 HEAD 里。把移出的 Python 测试放回 HEAD 跑：`test_v2_single_backend` **4/4 通过**，`test_v2_curation` 9/10 通过，`test_forum_resources` 8/9 通过（失败的都是 HTTP 路由用例）。21 项能通过、测的是已提交代码的测试被一并移出。8 个 Node 测试在 HEAD 上确实失败，但失败的原因正是已提交代码依赖未提交文件，移出它们等于去掉了报警 |

**模式**：前四轮是「修了我演示的那个写法，表格写整类已修」。这一轮仍是同一个模式：V4 和 V6 是我上轮演示的写法，修好了；V5、V7 也是上轮演示过的，没修；我没演示过的组合（确认后再举报、主帖自动暂停）被新改动打穿了。上轮最后一段要求「在每一行已修复旁边写出你自己尝试过但没能打穿的攻击变体」，本轮连修复报告都没有。另外，上轮的 `probe_gov.py` 就在 `.local/review/round4/`，原样在 HEAD 上跑一遍需要 1 分钟，输出里 `FAILED:` 一行会直接列出 V5、V7。

## 5. 实际测试数字

| 套件 | 命令 | HEAD `457bab8` 干净检出 | 当前工作区 |
|---|---|---|---|
| 网站 Python | `python -m pytest -q` | **142 passed, 3 skipped**（34.7s） | **172 passed**, 11 subtests（37.7s） |
| 网站 Python | `python -m unittest discover -s tests` | **Ran 145, OK (skipped=3)** | **Ran 172, OK** |
| 前端 | 逐个 `node tests/*.cjs` | **9/9** | **17/17** |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | — | **30 passed**（`0ea944a`） |
| 移出的 Python 套件放回 HEAD | `pytest` 单独跑 | single_backend 4/4；curation 9/10；forum_resources 8/9；cold_start 0/4 | — |
| 移出的 8 个 Node 套件放回 HEAD | 逐个 `node` | **0/8** | — |
| 浏览器：打开帖子 / 回执 | `probe_browser_forum.py` | **0/3** | 3/3 |
| 上轮治理探针原样重跑 | `round4/probe_gov.py` | `FAILED`: V5×2、V6e、V7、V9 | 同 HEAD |
| 本轮治理探针 | `probe_gov5.py` | 8 项 BAD（V5、V7a、V7b、N1–N5） | 同 HEAD |
| 变异：去掉每日上限 | `pytest` | 142 passed（**无测试失败**） | — |
| 变异：去掉「已有作品」门槛 | `pytest` | 1 failed | — |
| 变异：去掉驳回来源守卫 | `pytest` | 1 failed | — |

HEAD 与工作区的差额（172 − 142 = 30），来自工作区里未跟踪的那 12 个测试文件。

## 6. 剩余问题（按严重度）

行号以 HEAD `457bab8` 为准。

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | **阻塞** | HEAD 上论坛任何帖子详情页、发布回执页都报错，因为已提交的 `forum-app.js` 调用只在未跟踪文件里定义的 `HandrawForumWork`、`HandrawResourcePages` | `demo/assets/forum-app.js:1531`、`:1570`、`:2382`；`demo/forum.html`（HEAD 版不加载 `forum-resources.js`、`forum-work-post.js`） |
| 2 | **阻塞** | HEAD 上 skill 回读 `verified=False`；资源和策展接口缺失时返回 200 + 首页 HTML，客户端以为成功 | `backend/server.py:1627-1638`、`:2075-2086`；`conversation_share.py:323` |
| 3 | **阻塞（回归）** | 确认违规被记为 `report` 来源，再有人举报一次并被驳回，作品或主帖就重新公开（N3、N4） | `backend/admin_services.py:1888-1894`、`:1909-1918` |
| 4 | **高** | 同步主帖时不检查主帖自己的来源，无条件覆盖；两个主帖审核入口都不写 `status_source`。管理员或版主隐藏的主帖经「举报作品 → 驳回」后公开（V5、N1、N2） | `backend/services.py:1380-1384`；`backend/admin_services.py:1538-1539`；`backend/services.py:2101-2106` |
| 5 | **高** | 版主可以公开已隐藏作品的主帖，两个入口都可以，匿名 boot 能看到（V7a、V7b） | `backend/admin_services.py:1536-1537`；`backend/services.py:2107-2108` |
| 6 | **中（回归）** | 主帖的自动暂停不写 `status_source='report'`，被误报暂停的主帖驳回后无法恢复（N5） | `backend/services.py:2218`；`backend/admin_services.py:1916` |
| 7 | 中 | 测试缺口：没有测试覆盖主帖级审核、版主操作、确认后再驳回、主帖自动暂停、每日复刻上限（去掉上限后全套仍通过）。自动暂停的恢复用例不走举报路径 | `tests/test_status_provenance.py`；`tests/test_round4_fixes.py:81-98` |
| 8 | 中 | 复刻门槛「已有 1 件已发布作品」的成本是一次免审发布；门槛只在记账时检查，事后删掉作品也不影响 | `backend/curation.py:1593-1602` |
| 9 | 中 | 每日上限按 UTC 自然日计算，没有累计上限（每件作品每月约 240）；注册限流键为「IP + 用户名」；点赞没有门槛。三者是刷热门分的共同根源，需要一个统一的防刷方案 | `backend/curation.py:1607-1615`；`backend/server.py:1451` |
| 10 | 中 | `_has_other_open_reports` 仍是死代码，驳回一条就清空全部并恢复（V10/N7） | `backend/admin_services.py:1871-1875`、`:1901` |
| 11 | 中 | 退款后再收到成功回调，仍授予私有媒体（上轮 #8，未动） | `backend/services.py:2883-2892` |
| 12 | 中 | 复刻计数竞态：prepare 后父作品被隐藏，完成时仍计数（上轮 #11，未动） | `backend/services.py:2867-2873` |
| 13 | 中 | 作者编辑仍然 `.strip()` 提示词（上轮 #9，未动；HEAD 与工作区都在） | HEAD `backend/features.py:167`；工作区 `:176` |
| 14 | 中 | 单个账号举报 3 次即可暂停任意作品（已知风险，未变） | `backend/services.py:2176`、`:2200-2216` |
| 15 | 低 | operator `publish` 能覆盖管理员 `hide`（V6e）；公开作品的主帖举报被确认后作品仍公开（V9）。都需要先定规则 | `backend/admin_services.py:825-828`、`:1893-1894` |
| 16 | 低 | `4636feb` 单独检出时带着 12 个依赖未提交模块的测试，`git bisect` 会踩到 | `4636feb` |
| 17 | 低 | 清理脚本在 042 之前的旧库上抛 traceback；「备份非空」只看 `works` 行数 | `ops/purge_publish_time_forks.py:34`、`:110-117` |
| 18 | 低 | 管理员编辑价格上限 200、静默转换，发布上限 100（上轮 #14，未动） | `backend/admin_services.py:857`；`backend/services.py:1793` |
| 19 | 低 | `.gitignore` 只匹配 `starter_credentials.json`；轮换脚本输出 `starter_credentials.<库名>.json` 到库所在目录。库在 `.local/` 下时被 `/.local/` 忽略，库在别处时不被忽略 | `.gitignore:35`；`ops/rotate_starter_credentials.py:75` |
| 20 | 低 | 未知的 `/api/*` GET 返回 200 + 首页 HTML，掩盖了 #2 | `backend/server.py:1995-2001` |

本轮未复核：两个本地库里的 seed 会话（上轮 #13），以及上轮其余低级别项。本地库只读计数显示 `sessions` 表分别有 12 行和 6 行，没有逐条归属到 starter 账号，不下结论。

## 7. 能否上线

**不能。**

相比上轮，阻塞项从 4 个减到 2 组。复刻刷量和清理脚本已经可以从阻塞清单上划掉。剩下的两组：

1. **HEAD 的前端依赖（#1、#2）。** 需要创始人决定：要么把 `forum-resources.js`、`forum-work-post.js`、`forum_resource_routes.py`、`curation_routes.py` 等作为一批先提交；要么让 `forum-app.js` 在这两个对象不存在时降级，同时让缺失的 `/api/*` 返回 404 而不是 200 HTML。不管选哪种，都要在干净检出上补一条浏览器测试：发布一件作品，打开它的主帖和回执链接。
2. **治理（#3–#6）。** 根本问题仍是「谁造成的」没有记全。建议：
   - 来源至少分三种：`report`（阈值自动暂停，可撤销）、`moderator`（人工处置，包括**确认举报**，不可撤销）、空（从未处置）。确认举报时写 `moderator`；驳回只恢复 `status='paused' AND status_source='report'`，不恢复 `hidden`。
   - 主帖的所有隐藏和公开入口（两个主帖审核入口、主帖自动暂停）都要写 `status_source`。
   - `set_work_visibility` 同步主帖时，主帖来源是 `moderator`、作品来源不是，就不覆盖。
   - 主帖 `publish` 时，如果对应作品不是 `published`，就拒绝。
   - 验收方式：`probe_gov5.py` 在干净检出上跑出 `FAILED: []`，并把 V5、V7a、V7b、N1、N3、N5 写成走 HTTP 或生产函数路径的测试。

#7–#20 可以排到下一批。#7 里的每日上限测试很便宜，建议本批顺手补上。

对下一轮的要求，和上轮一样，只是更具体：标「已修复」之前，在**干净检出**上做两件事：把 `.local/review/round4/`、`round5/` 下的探针全部重跑一遍，再用浏览器打开一个帖子。两件事加起来不到 5 分钟，本轮的 V5、V7 和论坛报错都能提前发现。
