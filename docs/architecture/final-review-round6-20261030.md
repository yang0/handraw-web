# 第六轮终审报告（2026-10-30）

评审人：Claude（架构师兼终审）。对象：网站仓库 `457bab8..e4c9351`，4 个提交 `b392771`、`ccb3cbc`、`6268e87`、`e4c9351`。本轮工程师**仍然没有写修复报告**（`docs/architecture/` 下最新的 fix-report 是 round4），以下「工程师声称」来自用户转述和提交信息。

方法：不采信自述，不改产品代码。

- HEAD 用 `git worktree add --detach` 干净检出到 `E:\projectHome\hw-r6-head`（`git status --porcelain` 0 行）。
- 对照组：`hw-r6-457`（上轮被审的 `457bab8`）、`hw-r6-head-plus`（HEAD + 工作区未跟踪的 12 个测试）、`hw-r6-mut`（变异测试用，跑完已 `git checkout` 复原，0 行改动）。
- 每个探针都在临时库上起真实服务进程，只用 `Api-Key` 或浏览器 cookie 调接口；页面用 headless Chromium 打开。
- `backend/`、`demo/forum.html`、`demo/assets/forum-app.js` 在工作区与 HEAD 之间 `git diff` 为空，所以治理和论坛的结论对两边都成立（两边都实跑过，判定行逐行一致）。

探针和输出在 `.local/review/round6/`，以被测代码目录为 cwd 执行 `python -X utf8 <脚本>`：

| 脚本 | 覆盖 |
|---|---|
| `probe_head6.py` | HEAD 可用性：页面引用的每个静态资源、帖子/回执/资源 API、curation 接口、未知 `/api/*`、浏览器打开 10 个页面、从列表点进帖子 |
| `probe_head6_views.py` | 浏览器里用户实际看到的内容（作品主帖正文、回执、共创页、首页） |
| `probe_debug_views.py` | 共创页和首页的网络请求明细 |
| `round3/probe_skill.py`（原样） | skill `publish_draft` → `get_work` 回读 |
| `round5/probe_gov5.py`（原样）、`round4/probe_gov.py`（原样） | 上两轮治理探针在 HEAD 重跑 |
| `probe_gov6.py` | 用户点名的 V5、V7a、V7b、N3、N4、N5，加新变体 M1–M14；`_on_457bab8.txt` 为上轮代码对照 |
| `mutate6.py` | 逐项撤销本轮的 10 处修复，看有没有测试失败 |

## 1. 一句话结论

**不能接受。** 前端依赖这次是真修好了：干净检出上帖子、作品主帖、发布回执都能在浏览器里打开，skill 回读 `verified=True`，未知 `/api/*` 返回 404 JSON。治理上轮点名的 6 项修好了 5 项，但「版主公开已隐藏作品的主帖返回 409」只在一个入口成立；上轮报告逐行点名的第二个入口 `/api/forum/moderate` 一行没改，而它正是论坛帖子页「隐藏帖子」按钮调用的接口。围绕这个入口又打穿 3 条，其中 1 条是本轮引入的回归。本轮三处核心治理修复全部没有测试：撤销任何一处，148 项测试照样全绿。

## 2. 两个阻塞组逐项判定

### 2.1 A 组：HEAD 能否运行（对应上轮 #1、#2、#20）

| 声称 | 判定 | 证据 |
|---|---|---|
| `forum-app.js` 对 `HandrawCuration`/`HandrawResourcePages`/`HandrawForumWork` 加保护，缺失时降级 | **属实**，但在 HEAD 上不起作用：三个模块现在都随 `ccb3cbc` 提交了，降级分支不会走到。变异 M-j（去掉 `fromTopic` 的保护）148 passed、Node 9/9，这条保护没有测试 | `b392771` diff；`mutate6.txt` |
| 提交 `forum-resources.js`、`forum-work-post.js`、对应 CSS、HTML | **属实**。但同一提交里的 HTML 还引用了 5 个**没有提交**的文件，见下文 | `ccb3cbc`；`probe_head6_HEAD.txt` |
| 提交 `backend/forum_resource_routes.py` | **属实**。`/api/forum/resources/work/<id>` 返回 200 JSON，`resource.id == workId`；不存在的作品返回 404 JSON；`resource-topics`、评论读写都正常 | `probe_head6_HEAD.txt` |
| 未匹配的 `/api/*` 返回 404 JSON | **属实**（GET）。POST、DELETE 原本就是 404。残留：`GET /api`（不带斜杠）、`GET /API/xxx` 仍是 200 + HTML，影响很小 | `backend/server.py:1995`；`probe_head6_HEAD.txt` |

**判定：上轮的 #1、#2、#20 已修复。** HEAD 上仍有同一类问题（已提交代码依赖未提交文件），只是出在论坛之外，见 §3。

### 2.2 B 组：治理（对应上轮 #3–#6）

**用户点名的 6 项**（`probe_gov6_HEAD.txt`，状态写作 (作品, 主帖)）：

| # | 变体 | `457bab8` | HEAD | 判定 |
|---|---|---|---|---|
| V5 | 管理员只隐藏主帖 → 举报作品 3 次 → 驳回 | (published, **published**) | (published, hidden) | **已修复** |
| V7a | 管理员隐藏作品 → 版主经 `/api/admin/topics/<id>/moderate` 公开主帖 | (hidden, **published**) | 409 `work_not_published`，(hidden, hidden) | **已修复** |
| V7b | 同上，经 `/api/forum/moderate` | (hidden, **published**) | **200，(hidden, published)，匿名 boot 列出主帖** | **未修复** |
| N3 | 作品举报被确认 → 另一人再举报 → 驳回 | (**published**, **published**) | (hidden, hidden)，来源 `moderator` | **已修复** |
| N4 | 主帖举报被确认 → 再举报主帖 → 驳回 | 主帖 **published** | 主帖 hidden | **已修复** |
| N5 | 主帖被举报 3 次自动暂停 → 驳回 | 主帖 **paused** | 主帖 published | **已修复** |

上两轮探针原样在 HEAD 重跑：`round5/probe_gov5.py` 输出 `FAILED: ['V7b', 'N2']`（`rerun_probe_gov5_HEAD.txt`）；`round4/probe_gov.py` 输出 `FAILED: ['V6e …', 'V9 …']`，这两项是上轮已列为「待定规则」的 #15。

**逐条核对工程师的说法：**

| 声称 | 判定 |
|---|---|
| 确认违规记为 `moderator` | **属实**，但只在 `autoAction` 为真时成立。`autoAction=false` 确认后，作品停在 `paused/report`，下一次驳回就公开（M11，原有问题） |
| 主帖自动暂停写 `status_source='report'` | **属实**（N5 修好）。但它和没改的 `/api/forum/moderate` 组合出一个新回归（M5） |
| `set_work_visibility` 同步主帖时尊重主帖的 moderator 来源（双向） | **部分属实**。只挡「举报流程 → 人工决定」；人工对人工完全不挡（M8）。守卫读的是 `status_source`，而 `/api/forum/moderate` 隐藏主帖时根本不写这一列，所以版主从论坛前台隐藏的主帖照样被举报流程复活（M3、M4） |
| 驳回时传 `source="report"` | **属实** |
| 版主公开已隐藏作品的主帖返回 409 | **只在一个入口成立**。`/api/forum/moderate` 返回 200 并公开主帖（V7b、M6b、M10b）。经删除作品绕开映射后，两个入口都能公开（M10a） |
| 作者编辑不再 strip 提示词 | **属实**。HTTP 实测：只改标题时提示词 `'  首尾有空格的提示词  \n'` 原样保留，改提示词时 `'  新提示词  '` 原样保存；`457bab8` 上两项都被 strip（M14） |
| `.gitignore` 加 `starter_credentials.*.json` | **属实**。`git check-ignore` 对 `starter_credentials.prod.json`、`data/starter_credentials.prod.db.json`、`ops/starter_credentials.e2e.json` 都命中 `.gitignore:37`，覆盖轮换脚本的输出名（`ops/rotate_starter_credentials.py:75`） |

**新变体**（`probe_gov6_HEAD.txt` 与 `probe_gov6_on_457bab8.txt` 对照）：

| # | 变体 | `457bab8` | HEAD | 性质 |
|---|---|---|---|---|
| M1 | 作品被举报暂停 → **管理员隐藏作品** → 驳回（用户指定的顺序） | (hidden, hidden) | (hidden, hidden) | 挡住 |
| M2 | 作品被举报暂停 → 版主经 `/api/admin/topics` 隐藏主帖 → 驳回 | (published, **published**) | (published, hidden) | 本轮修好（=上轮 N1） |
| M3 | 作品被举报暂停 → 版主经 `/api/forum/moderate` 隐藏主帖 → 驳回 | (published, **published**) | **(published, published)**，匿名可见 | 未修（=上轮 N2） |
| M4 | 版主经 `/api/forum/moderate` 隐藏主帖 → 举报作品 3 次 → 驳回 | (published, **published**) | **(published, published)**，匿名可见 | 未修（=V5 走第二个入口） |
| **M5** | 主帖被举报 3 次自动暂停 → 版主经 `/api/forum/moderate` 隐藏 → 驳回 | 主帖 hidden | **主帖 published** | **本轮引入的回归** |
| M6a | 作品被举报暂停 → 版主经 `/api/admin/topics` 公开主帖 | (paused, **published**) | 409，(paused, paused) | 本轮修好 |
| M6b | 同上，经 `/api/forum/moderate` | (paused, **published**) | **(paused, published)**，匿名可见 | 未修 |
| M7 | 作品被举报暂停，主帖另有 1 条举报 → 驳回**主帖**举报 | (paused, **published**) | **(paused, published)**，匿名可见 | 未修 |
| M8 | 管理员只隐藏主帖 → **operator** 对（本来就公开的）作品点 `publish` | (published, **published**) | **(published, published)**，匿名可见 | 未修；直接否定「双向」 |
| M9 | 管理员隐藏作品 → operator `publish`（#15/V6e） | (published, published) | (published, published) | 未变，待定规则 |
| M10a | 管理员**删除**作品 → 版主经 `/api/admin/topics` 公开残留主帖 | 主帖 **published** | **主帖 published**，匿名可见 | 未修；409 被绕开 |
| M10b | 同上，经 `/api/forum/moderate` | 主帖 **published** | **主帖 published** | 未修 |
| M11 | 作品被举报暂停 → `autoAction=false` 确认 → 新举报 → 驳回 | (**published**, **published**) | **(published, published)**，匿名可见 | 未修 |
| M12 | 3 人各举报 1 次，驳回其中 1 条 | 剩 0 条，恢复 | 剩 0 条，恢复 | 未变（V10） |
| M13 | 047 迁移前就被隐藏或暂停的行（来源 `''`）→ 举报 → 驳回 | 不恢复 | 不恢复 | 未变：旧数据里被举报暂停的行同样无法恢复 |
| M14 | 作者编辑保留提示词 | **strip** | 原样 | 本轮修好 |

「直接 UPDATE `status_source`」：客户端请求体里的 `status_source`/`statusSource`/`status` 仍被忽略（gov5 N6 重跑通过）。没有接口能直接写这一列。但 `/api/forum/moderate` 改了 `status` 却不改 `status_source`，留下的旧值等于替攻击者写了这一列，M3、M4、M5 都是这么来的。

**成因（行号以 HEAD `e4c9351` 为准）：**

- **第二个入口一行没改**（V7b、M3、M4、M5、M6b、M10b）：`backend/services.py:2116` 隐藏主帖时不写 `status_source`，`:2118` 公开主帖时既不查作品状态，也不清来源。上轮报告 §6 #4、#5 已经逐行点名 `services.py:2101-2106`、`:2107-2108`。这个入口就是论坛帖子页「🙈 隐藏帖子」按钮调用的接口（`demo/assets/forum-app.js:1578`、`:2012`），所以版主在前台最常用的操作，恰好落在没修的这一半上。
- **M5 是怎么引入的**：`6268e87` 让主帖自动暂停写 `status_source='report'`（`services.py:2231`）。版主随后经 `/api/forum/moderate` 隐藏，`status` 变成 `hidden`，来源仍是 `report`。驳回分支恢复条件是 `status IN ('paused','hidden') AND status_source='report'`（`backend/admin_services.py:1950`），于是把版主的隐藏当作举报流程的暂停撤销了。上轮 §7 建议「驳回只恢复 `status='paused' AND status_source='report'`，不恢复 `hidden`」，照做就不会有 M5。
- **M7**：主帖驳回分支（`admin_services.py:1947-1952`）不看对应作品是否还在暂停。
- **M8**：`admin_moderate_work` 的 `publish` 调 `set_work_visibility` 时用默认 `source="moderator"`，不带任何守卫（`admin_services.py:828`）。新守卫的条件是 `topic_source == "moderator" and source != "moderator"`（`services.py:1389`），人工发布永远放行。operator 对一件本来就公开的作品点一次「发布」，作品状态不变，却把管理员隐藏的主帖公开了。
- **M10**：删除作品时把主帖设为 `hidden`、不写来源（`admin_services.py:891-893`），随后删掉 `curation_resource_topics` 映射（`:895`）。409 检查靠这张映射表找作品（`:1540-1544`），映射没了，检查直接跳过。
- **M11**：`if auto_action and res == "confirmed"`（`admin_services.py:1912`）为假时什么都不写，作品保持 `paused/report`。

**判定：B 组部分修复，并引入 1 条回归。** 上轮 #3（N3/N4）、#6（N5）已修复；#4、#5 只修了 `/api/admin/topics` 这一个入口，`/api/forum/moderate` 原样，且出现新回归 M5。

## 3. HEAD 实际可用性（基于 HTTP 请求和浏览器）

干净检出 `e4c9351`，临时库，发布 1 件作品和 1 篇普通帖（`probe_head6_HEAD.txt`、`probe_head6_views_HEAD.txt`、`probe_skill_HEAD.txt`）。

| 检查 | HEAD | 工作区 |
|---|---|---|
| `GET /forum/?view=topic&id=<普通帖>` 浏览器 | 正常显示正文，无 pageerror | 同 |
| `GET /forum/?view=topic&id=<作品主帖>` 浏览器 | 正常，按作品帖渲染（提示词、「一键复刻」、画风 FA-013） | 同 |
| 发布回执 `/forum/?view=resource&kind=work&id=…` 浏览器 | 正常，显示作品、提示词、共用讨论、评论框 | 同 |
| 论坛列表点击进入帖子 | 正常 | 同 |
| `GET /api/forum/resources/work/<真实 workId>` | **200 JSON**，`resource.id == workId` | 同 |
| `GET /api/forum/resources/work/does-not-exist` | 404 JSON | 同 |
| `POST /api/forum/resources/work/<id>/comments` | 200 | 同 |
| `GET /api/xxx-does-not-exist` | **404 JSON** `code=not_found` | 同 |
| skill `publish_draft` → `get_work` | **`verified=True`、`associations_verified=True`**；幂等 A–E 全部成立 | 同 |
| **首页 `/`（默认「发现」视图）** | **只显示「发现页正在加载…」，永远不会加载出来** | 正常显示作品、画风、讨论 |
| **共创页 `/forum/?view=curation&tab=mine`、`tab=review`** | **「加载失败：接口不存在」** | 正常 |
| 页面引用的静态资源 | **5 个 404**：`curation.css`、`works-browser.css`、`discovery.js`、`quick-create.css`、`quick-create.js` | 0 个 |
| `/admin.html`、`/studio.html` | 能打开，无 pageerror | 同 |

skill 回读是真校验，不是走过场。`conversation_share.py:438-447` 逐项比对 `resource.id`、提示词逐字节、封面 URL、画风和图型，HEAD 上全部一致。

**首页空白**：`demo/assets/main-app.js:394-397` 在 `window.HandrawDiscovery` 不存在时显示「发现页正在加载…」，这个对象只在未跟踪的 `demo/assets/discovery.js` 里定义。`ccb3cbc` 让 `demo/index.html:20` 去加载 `discovery.js`，但文件没提交，返回 404。这不是本轮引入的：`457bab8` 上首页同样只显示这一行（`probe_head6_views_on_457bab8.txt`），依赖从 `8abba73` 就存在。**上轮我漏报了这一项**：上轮的页面探针只检查 pageerror 和 console error，这里两样都没有，页面只是没有内容。

**共创页**：已提交的 `demo/assets/curation-ui.js` 调用 `/api/curation/mine`、`/review-queue`、`/admin`、`/submissions`、`/votes`，这些接口由未跟踪的 `backend/curation_routes.py` 提供，HEAD 上全是 404。论坛首页有「我的投稿」「参与审核」按钮直接链过去（`forum-app.js:2491-2493`）。404 不再伪装成 200，这是本轮的改进；但用户点进去看到的是「接口不存在」。

**静态资源 404**：`ccb3cbc` 的提交信息只写了 forum 的脚本和样式。实际上它把工作区版本的 `forum.html`、`index.html`、`studio.html`、`admin.html` 整体提交了，其中 5 个引用的文件不在提交里（`demo/forum.html:9`、`demo/index.html:9`、`:20`、`demo/studio.html:10`、`:22`）。HEAD 的 `studio-app.js` 不调用 `HandrawQuickCreate`，所以 `quick-create.*` 和两个 CSS 404 只是控制台报错和样式缺失；`discovery.js` 404 就是上面的首页空白。

**结论：论坛和 skill 在 HEAD 上可用；首页和共创页不可用。** HEAD 部署后，访问根域名的用户看到的是一个永远加载不出来的发现页。

## 4. 是否仍有假完成

**有。** 数字都属实，断言没有改弱；但有两条可以直接证伪的陈述，核心治理修复没有任何测试。

### 4.1 断言没有改弱

`git diff 457bab8 HEAD -- tests` 只有一个新增文件 `tests/test_round6_fixes.py`（157 行，6 项），没有删除或修改任何已有断言。4 个提交逐个检出跑 pytest：`b392771` 142/3、`ccb3cbc` 142/3、`6268e87` 148/3、`e4c9351` 148/3，每个提交单独检出都是绿的，`git bisect` 不会踩坑。提交里没有 `.db`、凭据、`.env`、`images/`。

### 4.2 移出的测试放回 HEAD（`hw-r6-head-plus`）

| 文件 | HEAD 上结果 | 说明 |
|---|---|---|
| `test_forum_resources.py` | **9/9 通过**（上轮 8/9） | 测的是本轮已提交的代码，测试本身仍未跟踪 |
| `test_v2_single_backend.py` | **4/4 通过** | 同上 |
| `test_forum_work_post.cjs` | **通过** | 同上 |
| `test_single_backend_navigation.cjs` | **通过** | 同上 |
| `test_v2_curation.py` | 9/10，失败项 `test_http_private_routes_…`：`404 != 401` | 失败的原因正是 §3 的共创页：`curation_routes.py` 没提交 |
| `test_cold_start.py` | 0/4 | `cold_start_content.py` 未跟踪，排除合理 |
| `test_resource_presentation.cjs` | 失败，`ENOENT quick-create.js` | 依赖未提交文件 |
| `test_article_*`、`test_product_refresh`、`test_studio_mode_navigation`、`test_studio_resource_entry`（5 个 `.cjs`） | 失败 | 断言的是工作区 `studio-app.js` 里未提交的函数（`flushUnifiedArticleEditor`、`generationCostText`、`isArticleBlueprint` 等），排除合理 |

HEAD 上本轮声称修复的东西，没有一项是靠移出测试才变绿的。但有两点：

1. 4 个能在 HEAD 上通过、正好保护本轮新提交模块的测试，仍然没有提交。本轮提交了 `forum-resources.js`、`forum-work-post.js`、`forum_resource_routes.py`，却没提交测它们的测试。
2. `test_v2_curation` 的那 1 项失败，就是共创页坏掉的报警。

### 4.3 变异测试：核心治理修复没有测试

`mutate6.txt`，在 `hw-r6-mut` 上逐项撤销，跑全套 pytest：

| 撤销的修复 | 结果 |
|---|---|
| M-a 确认作品举报改回记 `report`（N3 的修复） | **148 passed，无失败** |
| M-b 确认主帖举报改回记 `report`（N4 的修复） | **148 passed，无失败** |
| M-c 去掉 `set_work_visibility` 的主帖来源守卫（V5 的修复） | **148 passed，无失败** |
| M-d 去掉主帖 publish 的 409（V7a 的修复） | **148 passed，无失败** |
| M-g 驳回不传 `source="report"` | **148 passed，无失败** |
| M-j 去掉 `forum-app.js` 的 `fromTopic` 保护 | **148 passed，Node 9/9** |
| M-e 管理员隐藏主帖不写 `moderator` | 1 failed |
| M-f 主帖自动暂停不写 `report` | 2 failed |
| M-h 未知 `/api/*` 回落到 SPA | 2 failed |
| M-i 作者编辑重新 strip | 1 failed |

新增的 6 项测试覆盖了 404、主帖暂停来源、作者编辑。B 组里真正关键的三处（N3/N4、V5、V7）没有一项回归测试。上轮 §7 的验收要求是「把 V5、V7a、V7b、N1、N3、N5 写成走 HTTP 或生产函数路径的测试」，本轮只写了 N5。上轮还要求「在干净检出上补一条打开帖子的浏览器测试」，本轮没有。

### 4.4 可以证伪的陈述

| 陈述 | 事实 |
|---|---|
| `b392771`：「Republishing a work's thread while the work is moderated is rejected with 409.」用户转述：「版主公开已隐藏作品的主帖返回 409」 | 只在 `/api/admin/topics/<id>/moderate` 成立。`/api/forum/moderate` 返回 **200** 并公开主帖，匿名可见（V7b、M6b）。上轮报告 §2.3 表格里 V7b 单独一行，§6 #5 写明了 `services.py:2107-2108`，用户本轮也要求「两个入口都要试」。`round5/probe_gov5.py` 原样重跑，输出第一行 FAILED 就是 `V7b` |
| `b392771`：「a moderator-held topic is never revived by automation」 | 版主从论坛前台（`/api/forum/moderate`）隐藏的主帖，经「举报作品 → 驳回」或「举报主帖 → 驳回」都会被自动流程公开（M3、M4、M5）。前台隐藏不写来源，所以对守卫来说它不算「moderator-held」 |
| `services.py:1382-1384` 注释和用户转述：「A human decision on the thread outranks the report flow **in both directions**」/「双向」 | 守卫只挡 `source != "moderator"` 的调用。operator 对一件已公开作品点「发布」，就能公开管理员隐藏的主帖（M8） |
| `admin_services.py:1887-1889` 注释：「capture the count *before* that sweep: the restoration decision below needs to know whether other people's reports were still pending」 | `sibling_open_before` 赋值后**从未被读取**（全仓库 grep 只有赋值这一行）。下面的恢复判断不看它。同一提交删掉了对 `_has_other_open_reports` 的调用，改成注释「a dismissal always settles it」，`test_round6_fixes.py` 的文档字符串写「the report sweep is documented as always settling the target」。上轮 #10 指出 `_has_other_open_reports` 是死代码、驳回一条就清空全部，本轮没有修行为，而是把这个行为写成了设计，并加了一个与代码不符的注释 |
| `ccb3cbc`：「forum.html references these scripts and stylesheets … so they belong with the frontend that calls them」 | 同一提交还修改了 `index.html`、`studio.html`、`admin.html`，新增 777 行的 `product-refresh.css`，并引入 5 个指向未提交文件的引用（§3），提交信息都没提 |

### 4.5 模式

第六轮，同一个模式：我上轮演示过的写法修好了，同一处缺陷的另一个入口没动，而另一个入口在上轮报告里有单独一行和行号。这一轮的第二个入口还是论坛前台按钮实际调用的那个。上轮最后一段要求标「已修复」之前在干净检出上重跑 `round4/`、`round5/` 下的探针；`probe_gov5.py` 在 HEAD 上跑约 1 分钟，输出 `FAILED: ['V7b', 'N2']`。没有修复报告，我无法判断是没跑，还是跑了没报告。

另外更正我自己：上轮 §3 写「4 个主要页面没有 pageerror 或 console error」，这句属实，但首页其实没有内容。这一项从 `8abba73` 起就存在，上轮应该发现而没有发现。

## 5. 实际测试数字

| 套件 | 命令 | HEAD `e4c9351` 干净检出 | 当前工作区 | 用户给的数字 |
|---|---|---|---|---|
| 网站 Python | `python -m pytest -q` | **148 passed, 3 skipped**（27.0s） | **178 passed**, 11 subtests（39.5s） | 148/3；178 ✅ |
| 网站 Python | `python -m unittest discover -s tests` | **Ran 151, OK (skipped=3)** | **Ran 178, OK** | — |
| 前端 | 逐个 `node tests/*.cjs` | **9/9** | **17/17** | 9；17 ✅ |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | — | **30 passed**（`0ea944a`） | 30 ✅ |
| 4 个提交逐个检出 | `pytest -q` | 142/3、142/3、148/3、148/3 | — | — |
| 移出的 Python 套件放回 HEAD | `pytest` 单独跑 | forum_resources **9/9**；single_backend **4/4**；curation 9/10；cold_start 0/4 | — | — |
| 移出的 8 个 Node 套件放回 HEAD | 逐个 `node` | **2/8**（forum_work_post、single_backend_navigation） | — | — |
| 浏览器：帖子 / 作品主帖 / 回执 / 列表点进 | `probe_head6.py` | **4/4** | 4/4 | — |
| 浏览器：首页 / 共创页 | `probe_head6_views.py` | **0/3** | 3/3 | — |
| skill 回读 | `round3/probe_skill.py` | **verified=True** | True | — |
| 上轮治理探针原样重跑 | `round5/probe_gov5.py` | `FAILED: ['V7b', 'N2']` | 同 HEAD | — |
| 本轮治理探针 | `probe_gov6.py` | **11 BAD**（`457bab8` 上 19 BAD） | 同 HEAD | — |
| 变异测试 | `mutate6.py` | 10 项里 **6 项无测试失败** | — | — |

HEAD 与工作区 passed 差 30（178 − 148）：27 项来自工作区里未跟踪的 4 个 Python 测试文件（4 + 9 + 10 + 4），3 项是 `test_seed_starter_library.py` 在工作区不 skip，因为本地有被忽略的 `images/`。

## 6. 剩余问题（按严重度）

行号以 HEAD `e4c9351` 为准。`backend/` 自 `457bab8` 以来只改了 `admin_services.py`、`features.py`、`server.py`、`services.py` 中的 `set_work_visibility`/`submit_abuse_report`，以及新增 `forum_resource_routes.py`；标「上轮 #n」的项目对应代码没有改动，本轮没有逐行复测。

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | **阻塞** | `/api/forum/moderate` 隐藏主帖不写 `status_source`，公开主帖不查作品状态。版主可以公开已隐藏或暂停作品的主帖（V7b、M6b）；版主从前台隐藏的主帖被举报流程复活（M3、M4）。这是论坛帖子页「隐藏帖子」按钮调用的接口 | `backend/services.py:2116`、`:2118`；`demo/assets/forum-app.js:1578`、`:2012` |
| 2 | **阻塞（本轮回归）** | 主帖驳回分支恢复 `hidden`：版主隐藏过的、曾被举报自动暂停的主帖，驳回后公开（M5） | `backend/admin_services.py:1947-1952`（`:1950` 的 `IN ('paused','hidden')`） |
| 3 | **阻塞** | HEAD 首页（默认「发现」视图）只显示「发现页正在加载…」：`discovery.js` 未提交，`index.html` 却引用它 | `demo/assets/main-app.js:394-397`；`demo/index.html:20` |
| 4 | **高** | 本轮三处核心治理修复没有测试：撤销 N3/N4、V5、V7a 的修复，148 项全绿。上轮要求的 V5、V7a、V7b、N1、N3 HTTP 测试和打开帖子的浏览器测试都没写 | `tests/test_round6_fixes.py`；`mutate6.txt` |
| 5 | **高** | 删除作品后，残留主帖可以被版主经任一入口重新公开：删除时不写来源，并删掉了 409 检查依赖的映射（M10a、M10b） | `backend/admin_services.py:891-895`、`:1540-1544` |
| 6 | **高** | operator 对一件已公开作品点「发布」，就会公开管理员隐藏的主帖。人工操作不受守卫约束（M8） | `backend/admin_services.py:828`；`backend/services.py:1389` |
| 7 | 中 | 主帖驳回不看作品是否仍在暂停：驳回一条主帖举报后，暂停中作品的主帖被公开（M7） | `backend/admin_services.py:1947-1952` |
| 8 | 中 | `autoAction=false` 确认后不改来源，下一次驳回就公开作品（M11） | `backend/admin_services.py:1912` |
| 9 | 中 | 共创页显示「加载失败：接口不存在」：`curation-ui.js` 已提交，`curation_routes.py` 未提交；论坛首页有入口 | `demo/assets/curation-ui.js`；`demo/assets/forum-app.js:2491-2493` |
| 10 | 中 | 驳回一条举报就清空同一目标的全部举报并恢复（V10/M12）。`sibling_open_before` 计算后从不读取，注释描述的行为与代码不符；`_has_other_open_reports` 已无调用者 | `backend/admin_services.py:1887-1895`、`:1932-1936`、`:1787` |
| 11 | 中 | 4 个能在 HEAD 上通过、保护本轮新提交模块的测试仍未跟踪 | `tests/test_forum_resources.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_single_backend_navigation.cjs` |
| 12 | 中 | 单个账号举报 3 次即可暂停任意作品或主帖（阈值数的是举报条数，不是举报人数） | `backend/services.py:2210-2217` |
| 13 | 中 | 复刻门槛形同虚设、每日上限无测试、没有累计上限；注册限流键含用户名；点赞无门槛（上轮 #8、#9） | `backend/curation.py:1600`、`:1614`；`backend/server.py:2100` |
| 14 | 中 | 退款后再收到成功回调仍授予私有媒体；prepare 后父作品被隐藏仍计复刻（上轮 #11、#12） | `backend/services.py` `complete_studio_generation` 一带（约 `:2860-2905`） |
| 15 | 低 | 5 个静态资源 404（除 `discovery.js` 外只是控制台报错和样式缺失） | `demo/forum.html:9`；`demo/index.html:9`；`demo/studio.html:10`、`:22` |
| 16 | 低 | operator `publish` 覆盖管理员 `hide`（V6e/M9）；公开作品的主帖举报被确认后作品仍公开（V9）。都需要先定规则 | `backend/admin_services.py:825-828` |
| 17 | 低 | 047 迁移之前就被举报暂停的行来源是 `''`，驳回后永远无法恢复（M13） | `backend/work_schema.py:228-232` |
| 18 | 低 | 作品驳回仍允许从 `hidden` 恢复（`allow_from=("paused","hidden")`）。目前没有路径能产生 `hidden/report` 的作品，但这和 #2 是同一类隐患 | `backend/admin_services.py:1945` |
| 19 | 低 | `GET /api`、`GET /API/xxx` 仍返回 200 + 首页 HTML | `backend/server.py:1995` |
| 20 | 低 | 清理脚本在旧库上抛 traceback；管理员价格上限 200 与发布上限 100 不一致（上轮 #17、#18） | `ops/purge_publish_time_forks.py:37`；`backend/admin_services.py:857`、`:1566`；`backend/services.py:1803` |

上轮的 #1、#2、#3、#6、#13、#19、#20 本轮已修复，从清单移除；#4、#5 只修了一个入口，剩余部分并入本表 #1。上轮 #16（`4636feb` 单独检出带着依赖未提交模块的测试）是历史提交，无法再改，不再列出。

## 7. 能否上线

**不能。**

相比上轮，A 组的论坛部分和 B 组的大半已经解决：帖子能打开，skill 回读通过，确认违规不再能被驳回撤销，误报暂停的主帖能恢复。剩下的缺口比上轮小，但每一项都会在生产上真实发生：

1. **治理的第二个入口（#1、#2，加上同一处的 #5、#7）。** 版主在论坛前台点「隐藏帖子」走的就是这个入口。需要改的地方：
   - `forum_moderator_action` 的 `hide` 写 `status_source='moderator'`；`publish` 复用 `admin_moderate_topic` 的作品状态检查（最好两个入口调用同一个函数，不再各写一份）。
   - 主帖驳回分支只恢复 `status='paused' AND status_source='report'`，并且对应作品不是 `published` 时不恢复。
   - 删除作品时，主帖写 `status_source='moderator'`；对没有映射、状态为 `hidden/moderator` 的作品主帖，`publish` 也要拒绝。
   - 验收：`probe_gov6.py` 在干净检出上除 M9 外 `FAILED` 为空；V7b、M3、M4、M5、M10 写成走 HTTP 的测试；`mutate6.py` 的 M-a、M-c、M-d 各至少让 1 项测试失败。
2. **HEAD 首页（#3）。** 二选一：把 `discovery.js`、`works-browser.css` 和对应测试作为一批提交；或者把 `index.html` 恢复到不引用它们的版本，并让 `main-app.js` 在 `HandrawDiscovery` 缺失时回落到作品列表，而不是一直显示「正在加载」。共创页（#9）和其余 4 个静态 404（#15）同理处理，或者把共创入口按钮先藏起来。
3. **补测试（#4、#11）。** 提交那 4 个已经能通过的测试；加一条浏览器测试，在干净检出上打开首页、一个作品主帖、一个回执，断言页面有内容。§3 的首页问题只有这种测试能发现，上轮的我也是因为只看报错才漏掉。

#6（operator 发布覆盖管理员隐藏主帖）建议本批一起修：它和 #16 是同一个规则问题，「operator 能否推翻 admin」定下来，两项一起改。

**如果以上做完，上线需要接受的风险：**

- #16：在规则定下来之前，operator 可以公开管理员隐藏的作品。
- #10、#12：驳回一条举报就清空全部；一个账号举报 3 次就能暂停任意内容。可以靠人工审核兜底，但审核负担会随用户数线性增长。
- #13：刷热门分没有统一的防刷方案（复刻门槛一次免审发布即可绕过、点赞无门槛、注册限流可以换用户名绕过）。
- #14：退款与成功回调的竞态、复刻计数竞态，概率低，影响限于单个账号。
- #17：迁移前被举报暂停的旧数据需要人工恢复。

对下一轮的要求和上轮一样：标「已修复」之前，在干净检出上把 `.local/review/round4/`、`round5/`、`round6/` 下的探针全部重跑，并在修复报告里贴出每个探针的 `FAILED:` 行。修复报告里的每一条「已修复」，请写明修了哪几个入口、行号是多少。

---

本轮使用的 4 个 worktree（`E:\projectHome\hw-r6-head`、`hw-r6-head-plus`、`hw-r6-457`、`hw-r6-mut`）留在磁盘上，方便复现。复核完可以用 `git worktree remove --force <路径>` 删除。
