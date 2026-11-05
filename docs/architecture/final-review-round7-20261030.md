# 第七轮终审报告（2026-10-30）

评审人：Claude（架构师兼终审）。对象：网站仓库 `e4c9351..7996923`，3 个提交 `cb454b9`、`54443ad`、`7996923`。本轮工程师**仍然没有写修复报告**（`docs/architecture/` 下最新的 fix-report 还是 round4），以下「工程师声称」来自用户转述和提交信息。

方法：不采信自述，不改产品代码。

- HEAD 用 `git worktree add --detach` 干净检出到 `E:\projectHome\hw-r7-head`（`git status --porcelain` 0 行）。
- 对照组：`hw-r7-e4c`（上轮被审的 `e4c9351`）、`hw-r7-mut`（变异测试用，跑完 `git checkout` 复原，`porcelain` 为空）。
- 每个探针都在临时库上起真实服务进程，只用 `Api-Key` 调接口；页面用 headless Chromium 打开，读的是渲染后的 DOM 文本。
- 工作区与 HEAD 之间，`backend/` 只差 `runtime_policy.py`、`seed.py`，`demo/` 只差 `account-tools.js`、`studio-app.js`。治理和论坛的结论对两边都成立。

探针和输出在 `.local/review/round7/`，以被测代码目录为 cwd 执行 `python -X utf8 <脚本>`：

| 脚本 | 覆盖 |
|---|---|
| `probe_gov7.py` | 用户点名的 V7b、M3、M4、M5、M8、M10，加 M6b/M7/M11；`/api/forum/moderate` 的全部 action；围绕新状态 `deleted` 的新变体 R1–R3。`_on_e4c9351.txt` 为上轮代码对照 |
| `probe_gov7_reply.py` | `hide_reply` / `publish_reply` / `delete_reply` 作用于举报已确认的回复 |
| `round6/probe_gov6.py`、`round5/probe_gov5.py`、`round4/probe_gov.py`（原样） | 前三轮治理探针在 HEAD 重跑，输出 `rerun_*_HEAD.txt` |
| `round6/probe_head6.py`、`probe_head6_views.py`（原样） | HEAD 可用性：每个静态资源、帖子/回执/资源 API、共创接口、浏览器打开 10 个页面和点击进入帖子 |
| `round3/probe_skill.py`（原样） | skill `publish_draft` → `get_work` 回读 |
| `mutate7.py` | 16 个变异：用户指定的那一个，加上轮验收点名的 M-a/M-c/M-d，加首页 |
| `run_suites.sh` | HEAD、工作区、`e4c9351` 三处的 pytest / unittest / Node |

## 1. 一句话结论

**不能接受，但离上线已经很近。** 首页修好了，`/api/forum/moderate` 的隐藏和公开也真的修好了，用户点名的 V7b、M3、M4、M5 全部通过，撤销 publish 检查也确实有测试失败。没做完的有三块：删除作品后的残留主帖，经管理后台的「✅ 恢复」按钮一次点击就能公开（M10a，上轮点名，本轮没碰 `/api/admin/topics` 这个入口）；验收要求「治理探针除 M9 外无失败」不成立（M7、M8、M10a、M11 仍失败）；上轮要求的浏览器测试没有写，新增的「页面渲染测试」在首页空白的旧代码上照样通过。共创页仍是「加载失败：接口不存在」。

## 2. 三件事逐项判定

### 2.1 修好 `/api/forum/moderate`

**用户点名的项目**（`probe_gov7_HEAD.txt`，状态写作 (作品, 主帖)）：

| # | 变体 | `e4c9351` | HEAD | 判定 |
|---|---|---|---|---|
| V7b-src | 版主经 `/api/forum/moderate` 隐藏作品主帖，来源 | `('hidden', '')` | `('hidden', 'moderator')`，原因写入 `版主测试原因` | **已修复** |
| V7b | 管理员隐藏作品 → 版主经 `/api/forum/moderate` 公开主帖 | 200，(hidden, **published**) | **409 `work_not_published`**，(hidden, hidden) | **已修复** |
| M3 | 作品被举报暂停 → 版主前台隐藏主帖 → 驳回 | (published, **published**) | (published, hidden) | **已修复** |
| M4 | 版主前台隐藏主帖 → 举报作品 3 次 → 驳回 | (published, **published**) | (published, hidden) | **已修复** |
| M5 | 主帖被举报自动暂停 → 版主前台隐藏 → 驳回 | 主帖 **published** | 主帖 hidden | **已修复**（N5 仍正常：只被举报暂停的主帖驳回后恢复） |
| M6b | 作品被举报暂停 → 版主前台公开主帖 | (paused, **published**) | 409，(paused, paused) | **已修复** |
| M10b | 管理员删除作品 → 版主前台公开残留主帖 | 主帖 **published** | 409 `topic_deleted`，主帖 `deleted`，匿名不可见 | **已修复**（仅这一种走法，见 R1） |
| **M10a** | 管理员删除作品 → 版主经 `/api/admin/topics/<id>/moderate` 公开 | 主帖 **published** | **200，主帖 published，匿名 boot 列出** | **未修复** |
| M8 | 管理员只隐藏主帖 → operator 对已公开作品点 `publish` | (published, **published**) | **(published, published)** | **未修复**（上轮 #6，建议本批一起修） |
| M8f | 同上，主帖是从前台隐藏的 | (published, **published**) | **(published, published)** | **未修复** |
| M7 | 作品被举报暂停，主帖另有 1 条举报 → 驳回主帖举报 | (paused, **published**) | **(paused, published)**，匿名可见 | **未修复** |
| M11 | `autoAction=false` 确认 → 新举报 → 驳回 | (**published**, **published**) | **(published, published)** | **未修复** |
| M9 | 管理员隐藏作品 → operator `publish` | (published, published) | (published, published) | 未变，待定规则（上轮 #16） |

用户这次给的四条子要求：

| 子要求 | 判定 | 依据 |
|---|---|---|
| 隐藏时记录版主来源 | **属实** | `backend/services.py:2118-2122`；V7b-src；变异 MU4 有 1 项测试失败 |
| 公开前检查作品状态 | **属实**（前台入口） | `services.py:2133-2146`；V7b、M6b；变异 MU1 有 1 项测试失败 |
| 主帖驳回只恢复被举报自动暂停的 | **结果属实，条件没改** | M5 修好，原因是前台隐藏现在写 `moderator`，`admin_services.py:1955` 的 `status_source = 'report'` 不再匹配。条件本身仍是 `status IN ('paused', 'hidden')`，上轮建议去掉 `hidden`，没有改。目前没有路径能写出 `hidden/report`，所以是隐患，不是漏洞 |
| 删除作品后残留主帖不能再公开 | **只在一条走法上成立** | 见下面 R1、R1b 和 M10a |

**验收标准**（上轮 §7：「`probe_gov6.py` 在干净检出上除 M9 外 `FAILED` 为空」；本轮用户：「治理探针除 M9 外无失败」）：**不成立。**

- `round6/probe_gov6.py` 原样重跑：`FAILED: ['M7 …', 'M8 …', 'M9 …', "M10a …", 'M10b', 'M11 …']`（`rerun_probe_gov6_HEAD.txt`）。其中 M10b 是探针本身的误报：它期望 `hidden`，实际是更严格的 `deleted`，我已在 `probe_gov7.py` 里改成「不是 published」，M10b 通过。另外 5 项是真失败。
- `round5/probe_gov5.py`：`FAILED: []`（上轮是 `['V7b', 'N2']`）。
- `round4/probe_gov.py`：`FAILED: ['V6e …', 'V9 …']`，与上轮相同，都是待定规则的 #16。
- `probe_gov7.py`：HEAD 13 项失败，`e4c9351` 上 23 项。

**`/api/forum/moderate` 支持的 action，逐个试**（Part 2：先让管理员隐藏作品，再由全站版主对主帖执行该 action）：

| action | 结果 | 主帖状态 |
|---|---|---|
| `pin`、`unpin`、`feature`、`unfeature`、`move`（带 `targetCategory`） | 200 | 保持 hidden，可见性不变 |
| `hide` | 200 | hidden |
| `publish`、`PUBLISH`、`" Publish "`、用 `op` 字段代替 `action` | **409 `work_not_published`** | hidden |
| `hide_reply`、`publish_reply`、`delete_reply` | 200 | hidden |
| `bogus` | 400 | hidden |
| `delete`、`delete_topic` | 200 | `deleted`，**来源不写**（`services.py:2161`）。随后管理员对作品点「发布」，主帖变回 **published**（`e4c9351` 上同样，原有问题） |

**新变体**（Part 3 和回复探针）：

| # | 变体 | `e4c9351` | HEAD | 性质 |
|---|---|---|---|---|
| **R1** | 管理员删除作品 → 版主前台先 `hide` 再 `publish` | 主帖 published | **主帖 published，匿名 boot 列出** | **本轮新机制的缺口**。`hide` 不检查 `deleted`，把 `deleted` 覆盖成 `hidden`（`services.py:2112-2122`）；映射表已删，`publish` 的作品检查直接跳过 |
| R1b | 同上，经 `/api/admin/topics` | published | **published** | = M10a |
| R2 | 作者删除自己作品的主帖（前台 `delete`）→ 管理员隐藏作品 → 再发布作品 | published | **published，匿名可见** | 原有问题，本轮仍在。`set_work_visibility` 不跳过 `deleted`（`services.py:1385-1394`） |
| R2b | 作者删除主帖 → 作品被举报 3 次 → 驳回 | published | **published，匿名可见** | 同上，任何人举报 3 次再被驳回，就能复活作者删掉的帖子 |
| **R2c** | 作者删除主帖 → 版主公开，两个入口对比 | 两边都 200 | 前台 **409 `topic_deleted`**，后台 **200 并公开** | **本轮引入的不一致** |
| R4 | 回复被举报并确认（hidden）→ 版主 `publish_reply` | published | **published** | 原有问题。回复没有来源列，版主可以推翻管理员的确认（`services.py:2171-2174`） |
| R3 | 删除作品后匿名读资源页和主帖 | — | 资源 404，主帖不在 boot | 正常 |

**M10a/R1b 在真实界面上就是一次点击。** 管理后台的话题列表对非 `published` 的帖子显示「✅ 恢复」按钮（`demo/assets/admin-app.js:1169`），它调用 `/api/admin/topics/<id>/moderate`（`:2656`），`admin_list_topics` 不过滤 `deleted`。这个入口的 `publish` 不读 `deleted`，而映射已被删除（`admin_services.py:899`），作品检查（`:1548`）整段跳过。

提交信息说「Deleting a work marks its thread 'deleted' rather than 'hidden', so the fact survives the mapping being dropped」。实际上 `deleted` 只有前台 `publish` 一处在读（`services.py:2129`）。后台入口不读它；前台 `hide` 一次就把它抹掉。

**另一个没人会走到的分支。** 两个入口都加了 `work_row is None` / `work_status is None`（`services.py:2143`、`admin_services.py:1553`），注释写「A missing work (deleted) is as blocking as a hidden one」。仓库里删除作品只有一条路径（`admin_services.py:899-900`），它先删映射再删作品，所以「有映射但作品不存在」不会出现，这个分支永远不执行。变异 MU9（把它改回允许）156 passed 印证了这一点。代码本身无害，但注释描述的保护不存在，真正的删除保护靠的是 `deleted` 状态，而后者有上面的缺口。

**判定：第 1 件事大部分修好，没有通过验收。** 前台入口的隐藏、公开、M3/M4/M5 都已修复并有测试。删除作品后的残留主帖仍可经后台按钮或前台「隐藏→公开」两步公开；M7、M8、M11 没有处理。

### 2.2 修好 HEAD 首页

| 检查 | HEAD `7996923` | 判定 |
|---|---|---|
| 首页 `/` 浏览器渲染后的 `#main-app-root` 文本 | 「看看大家做出了什么……作品与做法 / 全部作品 → / 六轮视图作品 r6view FA-013 / 按用途开始 / 最新资源 松散黑线 #FA-001… / 近期讨论」，不再出现「发现页正在加载…」 | **已修复** |
| 页面引用的静态资源（4 个页面共 38 个引用，逐个 GET） | `/` 10 个、`/studio.html` 11 个、`/forum/` 13 个、`/admin.html` 4 个，**全部 200 且非 HTML** | **已修复**（上轮 5 个 404） |
| 共创页 `?view=curation&tab=mine`、`tab=review` | 浏览器显示「← 论坛 / 分享投稿 / 我的投稿 / 审核队列 / **加载失败：接口不存在**」；`/api/curation/mine`、`/review-queue`、`/admin` 404，`POST /submissions`、`/votes` 404 | **未修复**。`backend/curation_routes.py` 仍未跟踪；论坛首页仍有「我的投稿」「参与审核」两个入口（`demo/assets/forum-app.js:2491-2492`） |

`54443ad` 只提交了 `curation.css`，样式不再 404，接口仍然不存在。用户在共创页看到的东西和上轮一样。

**判定：首页和静态资源修好；共创页没修。**

### 2.3 补测试

| 上轮要求 | 判定 | 证据 |
|---|---|---|
| 提交能通过的测试（`test_forum_resources.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_single_backend_navigation.cjs`） | **没做**。4 个文件仍是 `UNTRACKED` | `git ls-files --error-unmatch` |
| 浏览器测试：干净检出上打开首页、作品主帖、回执，断言页面有内容 | **没做**。HEAD 跟踪的测试里没有一个新的浏览器测试（唯一用 Playwright 的 `tests/browser_acceptance.py` 是 10-28 的手动脚本，pytest 不收集） | 见 §4.2 |
| V5、V7a、V7b、N1、N3、N5、M3、M4、M5、M10 写成走 HTTP 的测试 | **只写了 V7b 和「隐藏写来源」两项**，外加 1 项直接调函数的 M10b | `tests/test_governance_http.py`、`tests/test_round4_fixes.py:132` |
| `mutate6.py` 的 M-a、M-c、M-d 各至少让 1 项测试失败 | **3 项全部 0 失败** | §4.1 |

**判定：第 3 件事基本没做。**

## 3. HEAD 实际可用性（真实 HTTP + 浏览器渲染后的页面文本）

干净检出 `7996923`，临时库，发布 1 件作品和 1 篇普通帖（`probe_head6_HEAD.txt`、`probe_head6_views_HEAD.txt`、`probe_skill_HEAD.txt`）。

| 页面 / 接口 | 状态码 | 用户实际看到的内容 |
|---|---|---|
| 首页 `/` | 200 | 作品卡片（标题、作者、画风）、「按用途开始」、最新资源、近期讨论。**有内容** |
| 作品详情 `/?view=work&id=…` | 200 | 含作品标题，无 pageerror |
| 作品主帖 `/forum/?view=topic&id=<作品主帖>` | 200 | 「生图提示词 / 复制 / 一键复刻 / 视图提示词原文 / 使用的画风与图型 / 粗黑轮廓 FA-013」。**有内容** |
| 发布回执 `/forum/?view=resource&kind=work&id=…` | 200 | 面包屑、作品标题、提示词原文、收藏/点赞/分享/举报、「共用讨论」、评论框。**有内容** |
| 普通帖、论坛列表、从列表点击进帖子 | 200 | 正文可见，无 pageerror |
| **共创页 `tab=mine`、`tab=review`** | 200（页面）/ **404（接口）** | **「加载失败：接口不存在」** |
| `/studio.html` | 200 | 正常，无 pageerror |
| `/admin.html` | 200 | 正常；普通用户 `403 /api/admin/permissions` 是预期行为 |
| `GET /api/forum/resources/work/<workId>` | 200 JSON | `resource.id == workId` |
| `GET /api/xxx-does-not-exist` | 404 JSON | — |
| `GET /api`、`GET /API/xxx` | 200 HTML | 上轮 #19，未变，影响很小 |
| skill `publish_draft` → `get_work` | — | **`verified=True`、`associations_verified=True`**；幂等 D 项（同 requestId 改标题返回同一 id）成立 |

`quick-create.js` 和 `quick-create.css` 现在是 200，但 HEAD 的 `studio-app.js` 里没有任何 `HandrawQuickCreate` 引用（`git show HEAD:demo/assets/studio-app.js | grep -c HandrawQuickCreate` 为 0，调用只在未提交的工作区版本里，`demo/assets/studio-app.js:12245`、`:12260`）。所以 `cb454b9` 说的「the studio's quick-create entry did nothing on a clean checkout」在 HEAD 上依然成立：文件加载了，没有人调用它。没有用户可见的损坏，只是提交信息说修好了一个其实没修的东西。

**结论：首页、作品主帖、回执、论坛、skill 在 HEAD 上可用；共创页不可用。**

## 4. 变异测试复现结果

### 4.1 `mutate7.py`（`hw-r7-mut`，每项跑全套 pytest，前端变异另跑 Node；跑完 `porcelain` 为空）

| 撤销的修复 | 结果 |
|---|---|
| **MU1 `services.py` publish 分支去掉作品状态检查（用户指定的这一项）** | **1 failed**：`test_governance_http.py::…::test_frontend_cannot_publish_a_thread_whose_work_is_hidden` |
| MU2 去掉 `deleted` 检查 | 1 failed：`test_round4_fixes.py::…::test_deleted_thread_cannot_be_republished` |
| MU3 两项都去掉 | 2 failed |
| MU4 前台 `hide` 不写 `moderator` | 1 failed：`test_frontend_hide_records_a_moderator_source` |
| MU5 前台 `publish` 不再清 `status_source` | **156 passed** |
| MU6 整个 `services.py` 回退到 `e4c9351` | 3 failed |
| MU7 删除作品时主帖改回 `hidden/''` | 2 failed |
| **MU8 后台 `/api/admin/topics` publish 去掉 409（= 上轮 M-d）** | **156 passed，无失败** |
| MU9 后台 publish 不再把「作品不存在」当阻塞 | 156 passed（分支不可达，见 §2.1） |
| **M-a 确认作品举报改回记 `report`** | **156 passed，无失败** |
| M-b 确认主帖举报改回记 `report` | **156 passed，无失败** |
| **M-c 去掉 `set_work_visibility` 的主帖来源守卫（V5 的修复）** | **156 passed，无失败** |
| M-g 驳回不传 `source="report"` | **156 passed，无失败** |
| M-k 主帖驳回改为也恢复 `moderator` 来源 | 1 failed（`test_round6_fixes.py`） |
| **MH1 `index.html` 不再加载 `discovery.js`** | **156 passed，Node 9/9** |
| **MH2 `main-app.js` 不渲染发现页（首页回到「正在加载」）** | **156 passed，Node 9/9** |

### 4.2 反向验证：本轮新测试放到 `e4c9351` 上跑

把 HEAD 的 `test_governance_http.py` 和 `test_round4_fixes.py` 复制到上轮代码上：5 failed、18 passed。失败的是两项前台治理测试、`test_every_linked_asset_exists`、两项删除测试。**`test_home_page_renders` 通过了**，而 `e4c9351` 的首页正是空白的。

原因：它断言的是服务器返回的 `index.html` 原文里没有「发现页正在加载」（`tests/test_governance_http.py:136-141`）。这句话写在 `main-app.js:396` 里，由 JS 在运行时插入，静态 HTML 里本来就没有，所以这条断言永远为真。`test_topic_page_renders_for_a_published_work`（`:143-150`）只断言返回的外壳 HTML 里含 `forum`，同样不看帖子内容。`test_every_linked_asset_exists`（`:168-178`）是真测试，能抓到「引用了不存在的文件」，但抓不到 MH1 这种「不引用了」。

### 4.3 结论

- **工程师的说法「撤销 publish 检查会导致测试失败」属实**，我复现了：MU1 有 1 项失败。
- 但它只覆盖本轮新写的前台检查。上轮验收点名的 M-a、M-c、M-d 仍然 **0 失败**，上轮那句「三处核心治理修复都没有测试」**仍然成立**。
- 首页空白这类故障，现有测试抓不到（MH1、MH2 全绿）。上轮要求的浏览器测试正是为此，没有写。

## 5. 是否仍有假完成

**有。** 测试数字属实，断言没有改弱；有几条可以直接证伪的陈述，「全部修复」不成立。

### 5.1 断言没有改弱

`git diff e4c9351 HEAD -- tests` 只有两个文件：新增 `test_governance_http.py`（7 项），`test_round4_fixes.py` 改 15 行。后者把 `assertEqual(topic, "hidden")` 改成 `"deleted"`，跟随行为变化，`deleted` 比 `hidden` 更严，不算改弱；另新增 1 项。没有删除任何测试。

### 5.2 可以证伪的陈述

| 陈述 | 事实 |
|---|---|
| 用户转述：「已全部修复」 | 第 1 件事：M10a 未修，验收「除 M9 外无失败」不成立（M7、M8、M10a、M11）。第 2 件事：共创页仍是「接口不存在」。第 3 件事：4 个测试没提交，浏览器测试没写，M-a/M-c/M-d 仍无测试 |
| `7996923`：「Adds HTTP-level governance tests **and a page-render test**」 | 没有任何测试渲染页面。`test_home_page_renders` 检查的是静态 HTML 里有没有一句只会由 JS 插入的话，在首页空白的 `e4c9351` 上**通过**（§4.2） |
| `7996923`：「Deleting a work marks its thread 'deleted' rather than 'hidden', **so the fact survives the mapping being dropped**」 | 后台入口不读 `deleted`，管理后台「✅ 恢复」一次点击就公开（M10a）；前台 `hide` 一次就把 `deleted` 覆盖成 `hidden`，随后 `publish` 200（R1） |
| `7996923`：「publishing rejects a thread whose work is hidden **or deleted**」 | 「作品已删除」那一半靠的是 `work_row is None`，这个分支不可达（MU9 全绿）。实际起作用的是 `deleted` 状态，有上面两个缺口 |
| `7996923`：「reverting the publish guard now fails the suite, which the review found it did not before」 | 前半句对**新加的前台检查**属实（MU1）。「the review found it did not before」指的是上轮 M-d，也就是**后台入口**的检查；撤销它，现在仍是 156 passed（MU8） |
| `cb454b9`：「…and **the studio's quick-create entry did nothing** on a clean checkout」（暗示已修） | HEAD 的 `studio-app.js` 不调用 `HandrawQuickCreate`，文件加载了也不会被用到 |

### 5.3 上轮批评「三处核心治理修复都没有测试」，现在有了吗？

**没有。** 本轮新增的测试测的是本轮新写的代码（前台隐藏写来源、前台公开检查、删除标记）。上轮那三处（N3/N4 的确认记 `moderator`、V5 的来源守卫、V7a 的后台 409）撤销后仍然全绿。上轮要求的 V5、V7a、N1、N3、N5、M3、M4、M5、M10 HTTP 测试，本轮写了其中的 V7b 一项。

### 5.4 模式

第七轮，模式和上轮一样，只是换了方向。上轮修了后台入口、漏了前台入口；这轮修了前台入口、漏了后台入口（M10a）。上轮报告 §2.2 表格里 M10a 和 M10b 是两行，§6 #5 写的是「经任一入口」，§7 写的是「对没有映射、状态为 `hidden/moderator` 的作品主帖，`publish` 也要拒绝」。`round6/probe_gov6.py` 在 HEAD 上跑约 1 分钟，输出 `FAILED` 第 4 项就是 M10a。上轮最后一段要求修复报告贴出每个探针的 `FAILED:` 行，本轮仍没有修复报告。

## 6. 实际测试数字

| 套件 | 命令 | HEAD `7996923` 干净检出 | 当前工作区 | `e4c9351` 对照 | 用户给的数字 |
|---|---|---|---|---|---|
| 网站 Python | `python -m pytest -q` | **156 passed, 3 skipped**（36.0s） | **186 passed**, 11 subtests（81.8s） | 148 passed, 3 skipped | 156/3 ✅；186 ✅ |
| 网站 Python | `python -m unittest discover -s tests` | Ran 159, OK (skipped=3) | Ran 186, OK | Ran 151, OK (skipped=3) | — |
| 前端 | 逐个 `node tests/*.cjs` | **9/9** | **17/17** | 9/9 | 9 ✅；17 ✅ |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | — | **30 passed**（`0ea944a`） | — | 30 ✅ |
| 浏览器：首页 / 作品主帖 / 回执 / 帖子 / 列表点进 | `probe_head6*.py` | **全部有内容** | — | 首页空白 | — |
| 浏览器：共创页 2 个 tab | `probe_head6_views.py` | **0/2**（「接口不存在」） | 2/2 | 0/2 | — |
| 静态资源 | `probe_head6.py` | **38/38** | — | 33/38 | — |
| skill 回读 | `round3/probe_skill.py` | **verified=True** | — | True | — |
| 治理探针 | `probe_gov7.py` | **13 失败** | 同 HEAD（`backend` 治理代码相同） | 23 失败 | — |
| 上轮探针原样重跑 | `round6/probe_gov6.py` | 6 失败（M10b 为探针误报，实际 5） | — | 11 | — |
| | `round5/probe_gov5.py` | `FAILED: []` | — | `['V7b','N2']` | — |
| | `round4/probe_gov.py` | `['V6e','V9']`（待定规则） | — | 同 | — |
| 变异测试 | `mutate7.py` | 16 项里 **9 项无测试失败** | — | — | — |

HEAD 与工作区 passed 差 30（186 − 156）：27 项来自工作区里未跟踪的 4 个 Python 测试文件，3 项是 `test_seed_starter_library.py` 在工作区不 skip（本地有被忽略的 `images/`），与上轮相同。HEAD 比 `e4c9351` 多 8 项：`test_governance_http.py` 7 项 + `test_round4_fixes.py` 1 项。

## 7. 剩余问题（按严重度）

行号以 HEAD `7996923` 为准。本轮 `backend/` 只改了 `services.py`、`admin_services.py`，标「上轮 #n」的项目对应代码没有改动，只更新了行号。

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | **阻塞** | 删除作品后的残留主帖可以重新公开：后台入口 `publish` 不读 `deleted`，映射已删，作品检查跳过；管理后台「✅ 恢复」按钮一次点击即可（M10a/R1b）。前台先 `hide` 再 `publish` 也行，`hide` 把 `deleted` 覆盖成 `hidden`（R1） | `backend/admin_services.py:1540-1560`、`:899`；`backend/services.py:2112-2122`；`demo/assets/admin-app.js:1169`、`:2656` |
| 2 | **高** | operator 对已公开作品点「发布」，公开管理员隐藏的主帖，前台或后台隐藏都一样（M8、M8f，上轮 #6） | `backend/admin_services.py:828`；`backend/services.py:1389` |
| 3 | **高** | 作者删除的作品主帖（`deleted`，来源为空），作品一经「隐藏→发布」或「举报 3 次→驳回」就被公开（R2、R2b）。`set_work_visibility` 不跳过 `deleted`，前台 `delete` 不写来源 | `backend/services.py:1385-1394`、`:2161` |
| 4 | **高** | 核心治理修复仍无测试：撤销 M-a、M-b、M-c、M-g、后台 409（MU8），156 项全绿。上轮要求的 HTTP 测试只写了 V7b | `tests/test_governance_http.py`；`mutate7.txt` |
| 5 | **高** | 没有浏览器测试；`test_home_page_renders` 断言的字符串只会由 JS 插入，在首页空白的代码上通过；首页回退（MH1、MH2）无测试失败 | `tests/test_governance_http.py:136-150` |
| 6 | 中 | 共创页「加载失败：接口不存在」：`curation_routes.py` 未提交，论坛首页有入口 | `demo/assets/curation-ui.js`；`demo/assets/forum-app.js:2491-2492` |
| 7 | 中 | 主帖驳回不看作品是否仍在暂停（M7） | `backend/admin_services.py:1952-1957` |
| 8 | 中 | `autoAction=false` 确认后不改来源，下一次驳回就公开作品（M11） | `backend/admin_services.py:1917` |
| 9 | 中 | 版主 `publish_reply` 能公开被管理员确认违规而隐藏的回复（R4），回复没有来源列 | `backend/services.py:2171-2174` |
| 10 | 中 | 两个入口对同一 `deleted` 主帖给出相反结果：前台 409，后台 200（R2c，本轮引入）。两个入口仍各写一份 publish 逻辑，上轮建议合成一个函数 | `backend/services.py:2123-2151`；`backend/admin_services.py:1540-1560` |
| 11 | 中 | 4 个能在 HEAD 上通过的测试仍未跟踪（上轮 #11） | `tests/test_forum_resources.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_single_backend_navigation.cjs` |
| 12 | 中 | 驳回一条举报就清空同一目标的全部举报；`sibling_open_before` 计算后从不读取；`_has_other_open_reports` 无调用者（上轮 #10） | `backend/admin_services.py:1892-1910`、`:1792` |
| 13 | 中 | 单个账号举报 3 次即可暂停任意作品或主帖（上轮 #12） | `backend/services.py:2219-2250` |
| 14 | 中 | 复刻门槛、每日上限、注册限流、点赞门槛（上轮 #13）；退款后成功回调、复刻计数竞态（上轮 #14） | `backend/curation.py:1600`、`:1614`；`backend/server.py:2100`；`backend/services.py:2901` 一带 |
| 15 | 低 | `work_row is None` / `work_status is None` 分支不可达，注释描述了一个不存在的保护（MU9） | `backend/services.py:2141-2143`；`backend/admin_services.py:1552-1553` |
| 16 | 低 | 主帖驳回条件仍含 `hidden`，目前没有路径产生 `hidden/report`，是隐患（上轮 #2 的条件部分；作品侧同类为上轮 #18） | `backend/admin_services.py:1955`、`:1950` |
| 17 | 低 | `quick-create.js` 已提交但 HEAD 不调用；提交信息说修好了快速创作入口 | `demo/studio.html:22`；`cb454b9` |
| 18 | 低 | 前台 `publish` 不清 `status_source` 无测试（MU5 全绿） | `backend/services.py:2147-2151` |
| 19 | 低 | operator `publish` 覆盖管理员 `hide`（M9/V6e）；主帖举报确认后作品仍公开（V9）。需先定规则（上轮 #16） | `backend/admin_services.py:825-828` |
| 20 | 低 | 047 迁移前被举报暂停的旧数据无法恢复（上轮 #17）；`GET /api`、`/API/xxx` 返回 HTML（上轮 #19）；清理脚本、价格上限不一致（上轮 #20） | `backend/work_schema.py:228-232`；`backend/server.py:1995`；`ops/purge_publish_time_forks.py:37` |

上轮的 #1（前台入口）、#2（M5 回归）、#3（首页）、#15（静态资源 404）本轮已修复，从清单移除。上轮 #5（删除后残留主帖）只修了前台入口，剩余部分为本表 #1。

## 8. 能否上线

**不能。** 但只差一小步，比上轮近得多。

本轮真实的进展：首页能用了，前台「隐藏帖子」按钮的治理问题（V7b、M3、M4、M5、M6b）修好了并且有测试，5 个静态资源不再 404，skill 回读通过。

**上线前必须做的（工作量估计半天）：**

1. **#1 删除后残留主帖。** 两个入口的 `publish` 都拒绝 `status = 'deleted'`；`hide` 不改写 `deleted`（或者对 `deleted` 直接拒绝）。最好把两个入口的 publish/hide 合成一个函数，#10 的不一致也就没了。顺手让 `set_work_visibility` 跳过 `deleted` 主帖，前台 `delete` 写 `status_source='moderator'`，#3 也就修好了。
2. **#5 一条真正的浏览器测试。** 在干净检出上起服务，用 Playwright 打开 `/`、一个作品主帖、一个回执，断言渲染后的 DOM 里出现作品标题和提示词。验收：MH1、MH2 至少各让 1 项测试失败。
3. **#4 补测试。** 把 M10a、R1、M3、M4、M5 写成 HTTP 测试；验收：`mutate7.py` 里 M-a、M-c、MU8 各至少 1 项失败。把那 4 个已经能通过的测试提交上去。
4. **#6 共创页。** 二选一：提交 `curation_routes.py` 和 `test_v2_curation.py`；或者在 HEAD 上把论坛首页的「我的投稿」「参与审核」入口先藏起来。

**建议同批处理**：#2（M8）。规则只需要一条：作品 `publish` 同步主帖时，主帖来源为 `moderator` 就不动。M9（#19）要不要一起改，取决于「operator 能否推翻 admin」的决定。

**如果只做完以上 4 项就上线，需要接受的风险：**

- #7、#8：主帖驳回和 `autoAction=false` 的边角情况会让暂停中的内容提前公开，需要审核员知道「确认时勾选自动处理」。
- #9：版主能恢复管理员确认隐藏的回复。版主本身是受信角色，可以靠审计日志追查。
- #12、#13：驳回一条就清空全部举报；一个账号举报 3 次就能暂停任意内容。用户量小时靠人工审核兜底，审核量会随用户数线性增长。
- #14：刷热门分没有统一防刷；退款与回调竞态概率低，影响限于单个账号。
- #19：规则定下来之前，operator 可以公开管理员隐藏的作品。
- #20：迁移前的旧暂停数据需要人工恢复。

对下一轮的要求和上轮一样，只加一句：标「已修复」之前，在干净检出上把 `.local/review/round4/` 到 `round7/` 下的探针全部重跑，并在修复报告里贴出每个探针的 `FAILED:` 行，以及 `mutate7.py` 的输出。

---

本轮使用的 3 个 worktree（`E:\projectHome\hw-r7-head`、`hw-r7-mut`、`hw-r7-e4c`）留在磁盘上，方便复现，均为干净状态。复核完可以用 `git worktree remove --force <路径>` 删除。
