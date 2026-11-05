# 第八轮终审报告（2026-10-30）

评审人：Claude（架构师兼终审）。对象：网站仓库 `7996923..5158b87`，2 个提交 `ed23dee`（提交 `curation_routes.py`）、`5158b87`（`set_topic_visibility` 统一函数 + 测试）。本轮**仍没有修复报告**（`docs/architecture/` 最新的 fix-report 还是 round4），「工程师声称」来自用户转述和提交信息。

方法：不采信自述，不改产品代码。

- HEAD 用 `git worktree add --detach` 干净检出到 `E:\projectHome\hw-r8-head`。对照组：`hw-r8-799`（上轮 `7996923`）、`hw-r8-e4c`（首页空白的 `e4c9351`）、`hw-r8-mut`（变异用）。全部 `git status --porcelain` 为 0 行。
- 每个探针都在临时库上起真实服务进程，只用 `Api-Key` 调接口；页面用 headless Chromium 打开，读渲染后的 DOM，同时收集 pageerror、console error 和所有 ≥400 的响应。
- 工作区与 HEAD 之间，`backend/` 只差 `runtime_policy.py`、`seed.py`，治理代码相同。

探针和输出在 `.local/review/round8/`，以被测代码目录为 cwd 执行 `python -X utf8 <脚本>`：

| 脚本 | 覆盖 |
|---|---|
| `probe_gov8.py` | Part 1：M10a、R1、R1b、M3、M4、M5、M8、M11 及 V7a/V7b/M6b/M7/R2/R2b/R2c，M3–M5 两个入口各测一遍。Part 2：两个入口的**全部 action** × 两种已删除主帖（管理员删作品、作者删帖）× 两个角色（版主、管理员），每个 action 之后再经两个入口各 `publish` 一次。Part 3：大小写、空白、`op` 字段、无前缀路由、举报→确认→公开等新变体 |
| `probe_n1d.py` | 只用管理后台真实按钮的走法：先有举报 → 删作品 → 「确认违规」→「✅ 恢复」 |
| `probe_pages8.py` | HEAD 可用性：10 个页面浏览器渲染 + 共创接口完整走一遍（授权、投稿、我的投稿、审核队列、管理概览） |
| `mutate8.py` | 22 个变异。**每个变异先过 `py_compile` / `node --check`**，编译不过的不计入，然后跑全量 pytest（前端变异另跑全部 Node） |
| `mut_behaviour.txt` | 对测试抓不到的 3 个变异，用探针证明它们是真回归 |
| `engineer_mutate_matrix_rerun.txt` | 工程师自己的 `.local/mutate_matrix.py` 原样重跑 |
| `rerun_*_HEAD.txt` | round3–round7 的探针原样重跑 |
| `run_suites.sh` | HEAD、工作区、`7996923` 三处的 pytest / unittest / Node |

## 1. 一句话结论

**不能接受，但只差一个具体的口子和一条测试。** 统一函数是真的，两个入口都调它，我把两个入口的全部 action 在已删除主帖上穷举了 88 种组合，HEAD 上**全部挡住**（上轮代码 88 种全破）；共创页修好了。没做完的有：举报流程的「确认违规」不走统一函数，会把 `deleted` 改写成 `hidden`，随后「✅ 恢复」一点就公开，管理后台两次点击即可复活已删除作品的帖子；工程师的变异矩阵 4 项「CAUGHT」**全部是语法错误造成的**，其中「确认违规记为 moderator」撤销后 158 项测试仍全绿；Playwright 测试没写，替代方案抓不到 JS 运行时错误和渲染逻辑回退。
## 2. 四件事逐项判定

### 2.1 统一函数 / 两个入口拒绝公开 `deleted`

**代码。** `set_topic_visibility`（`backend/services.py:1338-1400`）：`deleted` 且目标不是 `deleted` 时 409 `topic_deleted`（`:1366`）；`published` 时检查关联作品必须 published（`:1371-1381`）；其他状态写 `source`/`reason`（`:1397-1400`）。两个入口确实都调它：

| 入口 | publish | hide |
|---|---|---|
| `/api/admin/topics/<id>/moderate`（也匹配无前缀的 `/api/topics/<id>/moderate`，`server.py:2605`） | `admin_services.py:1543` | `admin_services.py:1547-1550` |
| `/api/forum/moderate` | `services.py:2189` | `services.py:2181-2184` |

**两个入口所有 action 穷举**（`probe_gov8_HEAD.txt` Part 2）。前台 13 个 action（pin/unpin/feature/unfeature/move/hide/publish/delete/delete_topic/hide_reply/publish_reply/delete_reply/bogus），后台 12 个（pin/unpin/feature/unfeature/publish/hide/edit/settle_bounty/refund_bounty/delete/`/delete` 路由/bogus），在「管理员删作品」和「作者删帖」两种 `deleted` 主帖上，版主和管理员各做一遍，每次之后再经两个入口各 `publish` 一次，并检查匿名 boot 和 `/api/forum/resource-topics/<id>`：

| | HEAD `5158b87` | 上轮 `7996923` |
|---|---|---|
| 88 种「action → 再公开」组合 | **88/88 挡住**。hide/publish 一律 409 `topic_deleted`；pin/feature/move/edit 200 但状态仍 `deleted`；delete 物理删除行 | **88/88 被公开** |

**用户点名项重做：**

| # | 变体 | `7996923` | HEAD | 判定 |
|---|---|---|---|---|
| M10a | 删作品 → 版主经后台 `publish` | 200，公开 | 409 `topic_deleted`，匿名不可见 | **已修复** |
| R1 | 删作品 → 前台 `hide` → `publish` | 公开 | hide 409、publish 409 | **已修复** |
| R1b | 同上走后台 | 公开 | 409 / 409 | **已修复** |
| R1x | 交叉：前台 hide → 后台 publish → 后台 hide → 前台 publish | 公开 | `deleted` | **已修复** |
| R2c | 作者删帖 → 两个入口 publish | 前台 409、后台 200 | 两边都 409 | **已修复**（不一致消除） |
| M3、M4、M5 | 前台入口 | 正常 | 正常 | 保持。**新增**：后台入口各做一遍也正常 |
| N5 | 只被举报暂停的主帖驳回后恢复 | 正常 | 正常 | 保持 |
| V7a、V7b、M6b | 作品隐藏/暂停时两个入口 publish | 正常 | 409 | 保持 |
| M8、M8f | 管理员只隐藏主帖 → operator 对作品点「发布」 | 主帖公开 | **主帖公开** | **未修复**（上轮 #2，建议同批，未做） |
| M11 | `autoAction=false` 确认 → 新举报 → 驳回 | 公开 | **公开** | **未修复**（上轮 #8） |
| M7 | 作品暂停 + 主帖 1 条举报 → 驳回主帖举报 | 主帖公开 | **主帖公开** | **未修复**（上轮 #7） |
| M9 | 管理员隐藏作品 → operator 发布 | 公开 | 公开 | 待定规则（上轮 #19） |

**新变体**（Part 3）：

| 变体 | HEAD 结果 |
|---|---|
| 前台 `PUBLISH`、`" Publish "`、`"publish\n"`、`"publish　"`、`op=publish`、`op=HIDE` 后 publish | 全部 409 `topic_deleted`（`services.py:2096` 先 `strip().lower()`，`　` 也被 `str.strip` 去掉） |
| 前台 `action=["publish"]` | 400 |
| 后台 `PUBLISH`、`" Hide "` 后 publish、无前缀路由 `/api/topics/<id>/moderate` 及其 hide→publish | 全部 409 |
| 后台用 `op` 字段 | 400（后台只读 `action`，`server.py:2608`） |
| **N1** 删作品 → 有人举报残留主帖 → 版主「确认」→ 版主 publish | **200，公开，匿名 boot 列出** |
| **N1b** 同上，举报由这名版主自己提交（一个账号、无管理员参与） | **200，公开** |
| **N1c** 作者删帖 → 举报 → 版主确认 → publish | **200，公开** |
| **N1d** 用户先举报 → 管理员删作品 → operator 在举报队列点「确认违规」→ 在话题列表点「✅ 恢复」（`probe_n1d_HEAD.txt`） | **第 4 步主帖从 `deleted` 变成 `hidden/moderator`，第 6 步 200 公开，匿名 boot 列出** |
| N2 作者删帖 → 管理员**暂停**作品 → 发布作品 | **公开**（R2 的同类） |
| N3 已删主帖被举报 3 次 → 驳回 | 保持 `deleted`（自动暂停只作用于 `published`） |
| N6 作者编辑 / 回复已删主帖 | 404 |

**N1 系列的机制。** 「确认违规」对主帖的处理是一条裸 SQL：`UPDATE forum_topics SET status = 'hidden', status_source = 'moderator' ... WHERE id = ?`（`admin_services.py:1915`），不经过 `set_topic_visibility`，不看当前是不是 `deleted`。改写之后映射已在删作品时删掉（`admin_services.py:899`），`set_topic_visibility` 的作品检查查不到映射（`services.py:1371-1374`），于是放行。管理后台举报列表不按目标状态过滤（`admin_services.py:1789-1794`），确认请求固定带 `autoAction: true`（`demo/assets/admin-app.js:2628`），话题列表对任何非 `published` 状态都显示「✅ 恢复」（`admin-app.js:1169`）。所以 N1d 是两次真实点击，而「先有举报、再删作品」正是删作品最常见的原因。版主可以裁定本板块主帖举报（`admin_services.py:1857-1871`），自审只防作者本人（`:1873-1875`），所以 N1b 一名版主单独就能做到。N1d 在 `7996923` 上同样成立（`probe_n1d_on_7996923.txt`），不是本轮引入，但它正好违反本轮提交声明的规则「nothing may silently downgrade deleted to hidden」。

**R2 / R2b / N2 的机制**（上轮 #3，未改）：`set_work_visibility` 同步主帖时只跳过 `status_source == 'moderator'`（`services.py:1454`），不跳过 `deleted`；作者前台删帖用裸 SQL 写 `status='deleted'`、不写来源（`services.py:2199`），所以管理员一次隐藏/暂停作品就把它改成 `hidden/moderator` 或 `paused`，再发布作品就公开（`services.py:1456-1459`）。

**不经过统一函数、仍直接写 `forum_topics.status` 的位置**（`grep "UPDATE forum_topics SET[^\"]*status"`）：

| 位置 | 写什么 | 读不读 `deleted` |
|---|---|---|
| `services.py:1456-1459` `set_work_visibility` 同步主帖 | 任意状态 | **否**（R2/R2b/N2） |
| `services.py:2199` 前台 delete | `deleted`，不写来源 | — |
| `services.py:2301-2305` 举报自动暂停 | `paused/report` | `AND status='published'`，安全 |
| `admin_services.py:895` 删作品 | `deleted/moderator` | — |
| `admin_services.py:1915` 确认主帖举报 | `hidden/moderator` | **否**（N1 系列） |
| `admin_services.py:1938-1942` 驳回主帖举报 | `published` | `status IN ('paused','hidden') AND source='report'`，安全 |

**判定：第 1 件事按字面完成，按目的没完成。** 用户点名的「两个入口」都拒绝了，穷举无一漏网，入口合成了一个函数。但「`deleted` 不能被覆盖」这个目标仍有两条旁路：举报确认（N1 系列，阻塞）和作品可见性同步（R2 系列，原有问题）。函数的 docstring 声称「the automatic report pause route through here」（`services.py:1350`），实际自动暂停不走这里（`:2301`）。
### 2.2 Playwright 测试

**没写。** HEAD 跟踪的测试里用到 Playwright 的只有 `tests/browser_acceptance.py`、`verify_composer_enhancements.py`、`verify_rich_editor_and_inline_media.py`，都是 10-28 之前的手动脚本，文件名不匹配 `test_*`，pytest 不收集。工程师用 `PageRendersTests` 的 HTTP + 资源检查代替（`tests/test_governance_http.py:166-240`）。

**替代方案够不够：不够。** 它由三种断言组成：

| 测试 | 实际断言 | 能抓到 | 抓不到 |
|---|---|---|---|
| `test_home_page_renders_seeded_content`（`:188-201`） | `/api/boot` 的 JSON 含作品标题；`index.html` 原文含 4 个 `<script src>` 字符串 | 接口数据丢失；HTML 删掉一个 script 引用（MH1） | 引用的文件 404；JS 抛错；渲染函数不调用或渲染空；DOM 和 JSON 字段对不上 |
| `test_topic_page_names_the_work`（`:203-211`） | `/api/forum/resources/work/<id>` 的 JSON 标题和提示词；外壳 HTML 含 `forum-app.js` | 接口字段 | 帖子页本身的任何渲染问题 |
| `test_every_linked_asset_exists_and_is_served`（`:226-240`） | 4 个页面引用的 `/assets/*` 磁盘存在且返回 200 | 引用了不存在的文件 | 文件存在但内容错 |

**问：首页空白时会不会失败？** 分情况，我逐个试了：

| 首页空白的原因 | 这组测试 |
|---|---|
| `e4c9351` 的真实故障：`index.html` 引用了 `discovery.js` 等，文件不存在 | `test_home_page_renders_seeded_content` **通过**（它只查 HTML 里有没有这个字符串，`e4c9351` 有）；只有 `test_every_linked_asset_exists_and_is_served` 失败（报 `missing /assets/works-browser.css`）。在 `hw-r8-e4c` 上实测：Page 类 4 passed、1 failed |
| MH1 `index.html` 删掉 `discovery.js` 引用 | 1 failed（新测试这次能抓到） |
| MH2 `main-app.js` 不调用 `HandrawDiscovery.render`（首页停在「正在加载」） | **158 passed** |
| MH3 `main-app.js` 加载时 `throw`（整页空白） | **158 passed** |
| MH4 论坛 topic 视图 `innerHTML = ""` | **158 passed** |
| MH5 回执页（resource 视图）`innerHTML = ""` | **158 passed** |

所以新写法比上轮的「永远为真」好一点：首页测试改成了查 boot 数据和 script 引用，能抓到「接口没给作品」和「HTML 少引用一个文件」。但测试名说的「renders」它没有测，JS 一行不执行。上轮要求的验收是「MH1、MH2 至少各让 1 项测试失败」，MH2 仍 0 失败。类里的 docstring 写「look for its specific title on the rendered page」（`:171-173`），实际是在 JSON 里找。

**具体差在哪：** 缺一个真正执行 JS 的步骤。`probe_pages8.py` 就是这样一条测试的样子：起服务、发布已知标题和提示词的作品、Chromium 打开 `/`、`/forum/?view=topic&id=…`、`/forum/?view=resource&kind=work&id=…`，在 `#main-app-root` / `#forum-app-root` 的 `inner_text()` 里断言标题和提示词，并断言无 `pageerror`。MH2–MH5 都会让它失败。环境里 Playwright 和 Chromium 已经装好（我的探针就在用），可以加 `pytest.importorskip("playwright")` 让没装浏览器的环境跳过。

**判定：没做，替代方案不够。**

### 2.3 补 HTTP 测试、提交 4 个测试

| 要求 | 判定 | 证据 |
|---|---|---|
| M10a、R1 写成 HTTP 测试 | **做了** | `test_deleted_thread_cannot_be_revived_by_either_entry`（`tests/test_governance_http.py:144-164`）对两个入口各发 publish 和 hide，断言 409 和状态不变；`test_admin_entry_also_refuses_when_the_work_is_hidden`（`:132-142`） |
| M3、M4、M5 写成 HTTP 测试 | **没做** | `test_governance_http.py` 里没有任何 dismiss。M3/M4 无论直调还是 HTTP 都没有测试，M5 只有 `test_round6_fixes.py:118` 的直调测试（且走的是后台 hide，不是用户点名的前台入口）。变异 M-c 让 M3、M4 两个入口共 4 项探针失败，测试 158 全绿 |
| M-a 被撤销时有测试失败 | **没有**：U4 158 passed | `mutate8.txt` |
| M-c 被撤销时有测试失败 | **没有**：158 passed | 同上 |
| 后台 409 被撤销时有测试失败（MU8/M-d） | **有**：E1 2 failed | 同上 |
| 提交 `test_forum_resources.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_single_backend_navigation.cjs` | **没做**，4 个仍未跟踪 | `git ls-files tests` |

**判定：完成约三分之一。**

### 2.4 共创页

`ed23dee` 提交了 `backend/curation_routes.py`（99 行），`server.py:1628`、`:2084` 早已按可选模块导入它。依赖 `curation.py`、表结构（`work_schema.py:62`、`:79` 起）都已跟踪；未跟踪的 `curation_schema.py` 只在 `migrations.py:525-528` 里 try-import，干净检出上为空列表，表仍由 `work_schema.py` 建好（实测 11 张 `curation_*` 表，迁移到 48）。

干净检出实测（`probe_pages8_HEAD.txt`）：

| 检查 | `7996923` | HEAD |
|---|---|---|
| `GET /api/curation/mine`、`/access`、`/review-queue`、`/admin` | 404 | **200** |
| `POST /api/curation/access`（管理员授权 3 名审核员） | 404 | 200 |
| `POST /api/curation/submissions`（画风投稿） | 404 | **200**，返回 `topicId` 和 `USR-S…` 编号 |
| 浏览器「我的投稿」 | 「加载失败：接口不存在」 | 「我的投稿 / 画风待收录 / 八轮微光 / 查看原帖 / 编辑重提 / 版本与意见」 |
| 浏览器「审核队列」（审核员登录） | 「加载失败：接口不存在」 | 「审核任务 · 画风 v1 / 八轮微光 / 定义：纸纹墨线 / 退回理由 / 通过 / 退回」 |
| 匿名打开两个 tab | — | 「登录后参与共创 / 登录 / 注册」，`/api/curation/mine` 401 |

**判定：已修复。**（我的探针第一次把「我的投稿」判 BAD，原因是我断言的是投稿标题「八轮投稿」，页面显示的是条目名「八轮微光」，是探针写错，不是产品问题。）
## 3. 变异测试复现结果

### 3.1 工程师的变异矩阵是无效的

工程师的脚本在 `.local/mutate_matrix.py`（另有 `mutate_all.py`，只跑 `test_governance_http.py` 一个文件）。它的变异方式是把目标那一行替换成 `"if False: pass  # " + 原文`：

- 前 3 项的目标是 `if …:` 行或多行调用的第一行，替换后下一行缩进不合法；
- 第 4 项的目标是函数调用的一个关键字参数，替换后是 `invalid syntax`。

我用 `py_compile` 逐个检查（`hw-r8-mut` 上）：

| 工程师的变异 | 编译结果 |
|---|---|
| 前台 publish 检查作品状态 | **SyntaxError**: unexpected indent（line 1379） |
| deleted 终态守卫 | **SyntaxError**: unexpected indent（line 1367） |
| hide 记录 moderator 来源 | **SyntaxError**: unexpected indent（line 2182） |
| 确认违规记为 moderator | **SyntaxError**: invalid syntax（line 1911） |

原样重跑（`engineer_mutate_matrix_rerun.txt`）4 项都输出 `CAUGHT (good)`。以第 4 项为例单独跑全量 pytest：**`16 errors during collection`，16 处 `SyntaxError: invalid syntax`，一个测试都没执行**。脚本只看 `returncode != 0`，所以导入失败也算「CAUGHT」。提交信息「disabling any of the four governance guards now fails the suite」所依据的就是这个输出。

### 3.2 我的变异矩阵（`mutate8.txt`，每项先编译通过再跑全量 pytest；跑完 `porcelain` 为空）

**用户指定的四项，及其在两个入口上的展开：**

| 撤销什么 | 结果 | 失败的测试 |
|---|---|---|
| **U1** 去掉 `set_topic_visibility` 的 deleted 守卫（`services.py:1366` → `if False:`） | **2 failed** | `test_deleted_thread_cannot_be_revived_by_either_entry`、`test_round4_fixes::test_deleted_thread_cannot_be_republished` |
| U1b 守卫只拦 publish，hide 可以改写 deleted | 1 failed | `test_deleted_thread_cannot_be_revived_by_either_entry` |
| **U2** 去掉 publish 的作品状态检查（`services.py:1378`） | **2 failed** | 前台、后台各 1 项 |
| **U3** 前台 hide 不写来源 | **1 failed** | `test_frontend_hide_records_a_moderator_source` |
| U3b 后台 hide 不写来源 | 1 failed | `test_round6_fixes::test_moderator_hidden_topic_stays_hidden_after_dismissal` |
| U3c 统一函数的通用 UPDATE 不写来源 | 2 failed | 上面两项 |
| **U4 「确认违规记为 moderator」改回 `report`（= 上轮 M-a，`admin_services.py:1911`）** | **158 passed，0 失败** | — |
| U4b 确认**主帖**举报改回 `report`（= M-b，`:1915`） | **158 passed，0 失败** | — |

**两个入口的覆盖**（用户要求确认这次覆盖的是两个入口）：

| 撤销什么 | 结果 |
|---|---|
| E1 后台入口 publish 绕过统一函数，改回裸 UPDATE（= 上轮 M-d / MU8） | **2 failed**（上轮 0） |
| E2 前台入口 publish 绕过统一函数 | 3 failed |
| E3 后台入口 hide 绕过统一函数 | 1 failed |
| E4 前台入口 hide 绕过统一函数 | 1 failed |

**前几轮的修复：**

| 撤销什么 | 结果 |
|---|---|
| **M-c** 去掉 `set_work_visibility` 的主帖来源守卫（V5，`services.py:1454`） | **158 passed，0 失败** |
| M-g 驳回不传 `source="report"` | **158 passed，0 失败** |
| M-k 主帖驳回也恢复 `moderator` 来源 | 1 failed |
| MU5 publish 不再清 `status_source` | 158 passed |
| MU7 删作品时主帖改回 `hidden/''` | 3 failed |

**页面：**

| 撤销什么 | 结果 |
|---|---|
| MH1 `index.html` 不再加载 `discovery.js` | 1 failed（`test_home_page_renders_seeded_content`） |
| MH2 `main-app.js` 不渲染发现页 | **158 passed，Node 9/9** |
| MH3 `main-app.js` 加载即抛错 | **158 passed，Node 9/9** |
| MH4 论坛帖子页渲染空 | **158 passed，Node 9/9** |
| MH5 回执页渲染空 | **158 passed，Node 9/9** |

### 3.3 测试抓不到的变异是不是真回归

`mut_behaviour.txt`：分别施加 U4、M-c、M-g（都编译通过），跑探针：

| 变异 | 158 项测试 | `round5/probe_gov5.py` | `probe_gov8.py` 相对 HEAD 新增失败 |
|---|---|---|---|
| U4（M-a） | 全绿 | **`N3 confirmed-abusive work stays hidden`** 失败：确认违规的作品，被下一次驳回重新公开 | 无（probe_gov8 没有覆盖这条） |
| M-c | 全绿 | `V5`、`N1`、`N2` 失败 | M3、M4 两个入口共 4 项 |
| M-g | 全绿 | `V5`、`N1`、`N2` 失败 | M3、M4 两个入口共 4 项 |

三项都是会让管理员或版主的决定被举报流程推翻的真回归，测试一项都不报。

### 3.4 结论

- 用户指定的四项：**3 项属实**（U1、U2、U3 撤销后有测试失败，且覆盖了两个入口）；**第 4 项「确认违规记为 moderator」不属实**，撤销后 0 失败，工程师的「CAUGHT」来自语法错误。
- 上轮验收「M-a、M-c、MU8 各至少 1 项失败」：只有 MU8（E1）达成。
- 上轮验收「MH1、MH2 各至少 1 项失败」：只有 MH1 达成。
## 4. HEAD 实际可用性

干净检出 `5158b87`，临时库，发布 1 件已知标题/提示词的作品、1 篇普通帖、1 份画风投稿。浏览器读渲染后的 DOM（`probe_pages8_HEAD.txt`），静态资源用 `round6/probe_head6.py` 原样重跑（`rerun_round6_probe_head6_HEAD.txt`）。

| 页面 | 状态码 | 标题/提示词出现在 DOM | pageerror / console error / ≥400 响应 | 用户看到的内容 |
|---|---|---|---|---|
| 首页 `/`（匿名） | 200 | 标题 ✅ | 无 / 无 / 无 | 「看看大家做出了什么…作品与做法 / 八轮页面作品标题 / p8author / FA-013 / 按用途开始 / 最新资源 / 近期讨论」 |
| 作品详情 `/?view=work&id=…` | 200 | 标题 ✅ | 无 | 面包屑、作者、「生图提示词 / 复制 / 一键复刻 / 八轮页面提示词原文」、画风、收藏/点赞/分享/举报 |
| 论坛列表 `/forum/` | 200 | 标题 ✅ | 无 | 板块、计数、「分享投稿 / 我的投稿 / 参与审核」 |
| 作品主帖 `/forum/?view=topic&id=…` | 200 | 标题 ✅ 提示词 ✅ | 无 | 正文、点赞/收藏/回复、提示词原文、画风 FA-013 |
| 回执 `/forum/?view=resource&kind=work&id=…` | 200 | 标题 ✅ 提示词 ✅ | 无 | 提示词原文、「共用讨论 · 0 条回复」、评论框 |
| 普通帖 | 200 | 正文 ✅ | 无 | 正文、回复区 |
| **共创「我的投稿」** | 200 | ✅ | 无 / 无 / **无 404** | 投稿条目、「编辑重提 / 版本与意见」。**不再显示「接口不存在」** |
| **共创「审核队列」** | 200 | ✅ | 无 / 无 / 无 | 「审核任务 · 画风 v1」、定义、通过/退回 |
| `/studio.html` | 200 | — | 无 | 正常 |
| `/admin.html`（管理员） | 200 | — | 无 | 超管控制台 |
| 静态资源 | — | — | — | `/` 10、`/studio.html` 11、`/forum/` 13、`/admin.html` 4，**38/38 全部 200 且非 HTML** |
| skill `publish_draft` → 回读 | — | — | — | `verified=True`、`associations_verified=True`（`rerun_round3_probe_skill_HEAD.txt`） |
| `GET /api/`、`/api/boot/extra` | 404 JSON | | | 与上轮相同 |
| `GET /api`、`GET /API/xxx` | 200 HTML | | | 未变（上轮 #20），影响很小 |

**结论：HEAD 上首页、作品详情、作品主帖、回执、论坛、共创页、创作台、后台全部可用，无 JS 错误，无 404 资源。** 上轮唯一不可用的共创页已修好。

## 5. 是否仍有假完成

**有。** 测试数字属实，断言没有改弱；变异矩阵和三处 docstring 是可证伪的。

### 5.1 断言有没有改弱

`git diff 7996923 5158b87 -- tests` 只动了 `test_governance_http.py`：新增 2 项治理测试；`PageRendersTests` 把 `test_home_page_renders`、`test_topic_page_renders_for_a_published_work` 换成 `test_home_page_renders_seeded_content`、`test_topic_page_names_the_work`，`test_every_linked_asset_exists` 加了「服务器返回 200」。旧的两项是永远为真的空断言，新的比旧的严，**不算改弱**。没有删除其他测试。

### 5.2 新首页测试在「首页空白」时会不会失败

见 §2.2：**只在「HTML 少引用一个 script」这一种空白下失败**（MH1）。`e4c9351` 的真实空白（引用的文件不存在）它通过，是隔壁的资源测试抓到的；JS 不调用渲染（MH2）、JS 抛错（MH3）它都通过。测试名和 docstring 说「renders」「on the rendered page」，实际不执行 JS。

### 5.3 可以证伪的陈述

| 陈述 | 事实 |
|---|---|
| `5158b87`：「Adds HTTP tests for both entries **and a mutation matrix: disabling any of the four governance guards now fails the suite**」 | 矩阵 4 项全是 SyntaxError（§3.1）。用有效变异重做，「确认违规记为 moderator」撤销后 158 passed（U4） |
| `5158b87`：「Both now call set_topic_visibility, which owns: **deleted is terminal (no publish, no downgrade to hidden)**」 | 对两个 moderate 入口属实。举报确认（`admin_services.py:1915`）和作品同步（`services.py:1456`）都会把 `deleted` 改掉，随后可公开（N1d、R2） |
| `5158b87`：「**every change records its source**」 | 前台 delete（`services.py:2199`）不写来源；确认主帖举报（`admin_services.py:1915`）不写原因 |
| `services.py:1350` docstring：「Both moderation entries … **and the automatic report pause route through here**」 | 自动暂停是裸 SQL（`services.py:2301-2305`），不调用这个函数 |
| `services.py:1389` 注释：「'deleted' is set only by the delete path」 | `deleted` 由两条删除路径各写一次裸 SQL（`services.py:2199`、`admin_services.py:895`），都不经过这个函数的 `deleted` 分支；该分支（`:1390-1396`）没有调用者 |
| `test_governance_http.py:171-173` docstring：「look for its specific title **on the rendered page**」 | 在 `/api/boot` 和资源接口的 JSON 里找 |
| 用户转述：「加了 HTTP 测试」 | M10a、R1 有；M3、M4、M5 没有（§2.3） |
| `ed23dee`：「Its dependencies are all part of this history」 | 属实（§2.4） |
| 工程师：「没有写 Playwright」 | 属实，自己承认了 |

### 5.4 模式

第八轮。治理代码本身这轮是真进步：上轮的「修一个入口漏一个入口」被统一函数终结了，88 种组合全部挡住，这是七轮来第一次一个入口问题都找不到。但验证方式仍是假的：上轮是「测试断言永远为真」，这轮是「变异永远失败」。两次的共同点是只看了「有没有红」，没看「为什么红」。一个 `py_compile` 或者看一眼 pytest 输出里的 `errors during collection` 就能发现。
## 6. 实际测试数字

| 套件 | 命令 | HEAD `5158b87` 干净检出 | 当前工作区 | `7996923` 对照 | 用户给的数字 |
|---|---|---|---|---|---|
| 网站 Python | `python -m pytest -q` | **158 passed, 3 skipped**（49.4s） | **188 passed**, 11 subtests（58.1s） | 156 passed, 3 skipped | 158/3 ✅；188 ✅ |
| 网站 Python | `python -m unittest discover -s tests` | Ran 161, OK (skipped=3) | Ran 188, OK | Ran 159, OK (skipped=3) | — |
| 前端 | 逐个 `node tests/*.cjs` | **9/9** | **17/17** | 9/9 | 9 ✅；17 ✅ |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | — | **30 passed**（`0ea944a`，porcelain 0） | — | 30 ✅ |
| 浏览器 10 个页面 | `probe_pages8.py` | **10/10 有内容、无 JS 错误、无 ≥400** | — | 8/10（共创 2 页「接口不存在」） | — |
| 共创接口 | 同上 | **5/5 为 200** | — | 0/5（404） | — |
| 静态资源 | `round6/probe_head6.py` | **38/38** | — | 38/38 | — |
| skill 回读 | `round3/probe_skill.py` | **verified=True** | — | True | — |
| 治理探针（本轮） | `probe_gov8.py` | **11 失败**（M7、M8、M8f、M9、M11、R2、R2b、N1、N1b、N1c、N2） | 同 HEAD | **109 失败**（含 Part 2 穷举 88 项） | — |
| | `probe_n1d.py` | **主帖被公开** | — | 主帖被公开 | — |
| 上轮探针原样重跑 | `round7/probe_gov7.py` | 9 失败（上轮 13）：M10a、R1、R1b、R2c 已不在列表 | — | 13 | — |
| | `round6/probe_gov6.py` | 6 失败，其中 M10a、M10b 是探针误报（期望 `hidden`，实际是更严的 `deleted`），实际 4 项：M7、M8、M9、M11 | — | — | — |
| | `round5/probe_gov5.py` | `FAILED: []` | — | — | — |
| | `round4/probe_gov.py` | `['V6e','V9']`（待定规则） | — | — | — |
| | `round7/probe_gov7_reply.py` | `publish_reply` 仍能公开确认违规的评论（R4） | — | — | — |
| 变异测试 | `mutate8.py` | 22 项有效变异，**9 项 0 失败**：U4、U4b、M-c、M-g、MU5、MH2、MH3、MH4、MH5 | — | — | — |
| 工程师变异矩阵 | `.local/mutate_matrix.py` | 4/4「CAUGHT」，**4/4 为 SyntaxError** | — | — | — |

HEAD 比 `7996923` 多 2 项：`test_admin_entry_also_refuses_when_the_work_is_hidden`、`test_deleted_thread_cannot_be_revived_by_either_entry`（页面测试换了 2 项、总数不变）。工作区比 HEAD 多 30 项：27 项来自 4 个未跟踪的 Python 测试文件，3 项是 `test_seed_starter_library.py` 在工作区不 skip（本地有被忽略的 `images/`），与前两轮相同。
## 7. 剩余问题（按严重度）

行号以 HEAD `5158b87` 为准。本轮只改了 `services.py`、`admin_services.py`、`test_governance_http.py`，新增 `curation_routes.py`；标「上轮 #n」的项目代码未改，只更新行号。

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | **阻塞** | 已删除作品的主帖可经举报流程复活（N1、N1b、N1c、N1d）。「确认违规」对主帖用裸 SQL 写 `hidden/moderator`，不走 `set_topic_visibility`，把 `deleted` 改写；映射已删，随后 `publish` 放行。管理后台两次点击（举报队列「确认违规」→ 话题列表「✅ 恢复」），或一名版主自己举报、自己确认、自己公开。复活后匿名可见原作品标题和图片，图片 URL 仍返回 200 | `backend/admin_services.py:1915`、`:899`；`backend/services.py:1371-1374`；`demo/assets/admin-app.js:2628`、`:1169` |
| 2 | **高** | 作者删除的作品主帖，作品一经「隐藏/暂停→发布」或「举报 3 次→驳回」就被公开（R2、R2b、N2，上轮 #3）。`set_work_visibility` 不跳过 `deleted`；前台 delete 不写来源 | `backend/services.py:1450-1459`、`:2199` |
| 3 | **高** | 核心治理修复仍无测试：撤销 U4（= M-a，确认违规记 moderator）、U4b、M-c（V5 来源守卫）、M-g，158 项全绿；探针证明这些都是真回归（`mut_behaviour.txt`）。M3、M4、M5 没有 HTTP 测试 | `tests/test_governance_http.py`；`mutate8.txt` |
| 4 | **高** | 没有浏览器测试。页面测试不执行 JS，MH2–MH5（不渲染、加载即抛错、帖子页空、回执页空）全绿 | `tests/test_governance_http.py:166-211` |
| 5 | **高**（流程） | 工程师的变异脚本把 SyntaxError 计为「CAUGHT」，并据此写入提交信息 | `.local/mutate_matrix.py`、`.local/mutate_all.py`；`5158b87` 提交信息 |
| 6 | 中 | operator 对已公开作品点「发布」，公开管理员隐藏的主帖（M8、M8f，上轮 #2，连续两轮建议同批修复） | `backend/admin_services.py:828`；`backend/services.py:1454-1459` |
| 7 | 中 | 主帖驳回不看作品是否仍在暂停（M7，上轮 #7） | `backend/admin_services.py:1937-1942` |
| 8 | 中 | `autoAction=false` 确认后不改来源，下一次驳回就公开作品（M11，上轮 #8） | `backend/admin_services.py:1902` |
| 9 | 中 | 版主 `publish_reply` 能公开被管理员确认违规而隐藏的回复（R4，上轮 #9） | `backend/services.py:2209-2212` |
| 10 | 中 | 4 个能在 HEAD 上通过的测试仍未跟踪（上轮 #11，连续三轮） | `tests/test_forum_resources.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_single_backend_navigation.cjs` |
| 11 | 中 | 驳回一条举报就清空同一目标的全部举报；`sibling_open_before` 计算后从不读取；`_has_other_open_reports` 无调用者（上轮 #12） | `backend/admin_services.py:1880-1895`、`:1777` |
| 12 | 中 | 单个账号举报 3 次即可暂停任意作品或主帖（上轮 #13） | `backend/services.py:2281-2306` |
| 13 | 中 | 复刻门槛、每日上限、注册限流、点赞门槛；退款后成功回调、复刻计数竞态（上轮 #14） | `backend/curation.py:1600`、`:1614`；`backend/server.py:2100`；`backend/services.py:2882` 一带 |
| 14 | 低 | 三处注释/docstring 描述了不存在的行为：自动暂停「route through here」；「'deleted' is set only by the delete path」（`deleted` 分支无调用者）；页面测试「on the rendered page」 | `backend/services.py:1350`、`:1389-1396`；`tests/test_governance_http.py:171-173` |
| 15 | 低 | 后台对作品主帖执行 delete 会物理删除行，映射仍指向它：资源页 200，评论 POST 404「帖子不存在或已下架」，讨论永久不可用（N5，原有问题） | `backend/admin_services.py:1610-1613`；`backend/resource_discussions.py` `ensure_topic` |
| 16 | 低 | `work is None` 分支不可达（删作品先删映射），注释描述的保护不存在（上轮 #15） | `backend/services.py:1376-1378` |
| 17 | 低 | 主帖驳回条件仍含 `hidden`，目前无路径产生 `hidden/report`（上轮 #16） | `backend/admin_services.py:1940` |
| 18 | 低 | `quick-create.js` 已提交但 HEAD 的 `studio-app.js` 不调用（上轮 #17） | `demo/studio.html:22` |
| 19 | 低 | publish 不清 `status_source` 无测试（MU5） | `backend/services.py:1383` |
| 20 | 低 | operator `publish` 覆盖管理员 `hide`（M9/V6e）；主帖举报确认后作品仍公开（V9）。需先定规则（上轮 #19） | `backend/admin_services.py:825-828` |
| 21 | 低 | 047 迁移前被举报暂停的旧数据无法恢复；`GET /api`、`/API/xxx` 返回 HTML；清理脚本与价格上限不一致（上轮 #20） | `backend/work_schema.py:228-232`；`backend/server.py`；`ops/purge_publish_time_forks.py:37` |

上轮的 #1（M10a/R1 两个入口）、#6（共创页）、#10（两个入口不一致）本轮已修复，从清单移除。
## 8. 能否上线

**不能。** 离上线比上轮更近：两个入口的问题终于收口，共创页可用，HEAD 所有页面在浏览器里都有内容、没有 JS 错误。挡住上线的是 #1：管理员删掉的违规作品，运营在后台点两下就能让它的标题和图片重新对匿名用户公开，而且「先被举报、再被删除」是删作品最常见的顺序。

**上线前必须做的（工作量估计半天）：**

1. **#1、#2：让 `set_topic_visibility` 成为唯一写 `forum_topics.status` 的地方。** 把 `admin_services.py:1915`（确认主帖举报）、`services.py:1456`（作品同步主帖）、`services.py:2199`（前台删帖）、`admin_services.py:895`（删作品）都改成调用它。给自动流程加一个「目标已 `deleted` 时静默跳过」的选项（确认举报、作品同步用），人工入口保持 409。验收：`probe_gov8.py` 的 N1、N1b、N1c、N2、R2、R2b 和 `probe_n1d.py` 不再公开主帖；`grep "UPDATE forum_topics SET[^\"]*status" backend/` 只剩统一函数内部和自动暂停（`AND status='published'`）、驳回（带 `source='report'` 条件）两处。
2. **#4：一条真正的浏览器测试。** 照 `probe_pages8.py` 的形状写成 `tests/test_pages_browser.py`：起服务、发布已知标题和提示词的作品，Chromium 打开 `/`、作品主帖、回执，断言渲染后的 DOM 含标题和提示词、无 `pageerror`；`pytest.importorskip("playwright")`。验收：MH2、MH3、MH4、MH5 各至少 1 项失败。
3. **#3、#5：补测试并修好变异脚本。** 为 U4（确认违规后，下一次驳回不能公开作品，即 `round5` 的 N3）、M-c（M3/M4 两个入口）、M-g 各写 1 条 HTTP 测试，再加 #1 的 N1d 回归测试。变异脚本在跑测试前先 `py_compile`，并解析 pytest 输出里的 `N failed`，不要只看 return code。验收：`mutate8.py` 里 U4、U4b、M-c、M-g、MH2–MH5 全部至少 1 项失败。顺手把 #10 那 4 个测试提交上去。

**做完以上 3 项、探针通过后，我认为可以上线**，需要接受的风险：

- #6（M8）：运营对已公开作品点「发布」会公开管理员隐藏的主帖。双方都是受信员工，有审计日志可查；规则只需一条（作品同步时主帖来源为 `moderator` 就不动），建议仍同批修。
- #7、#8：主帖驳回和 `autoAction=false` 的边角情况会让暂停中的内容提前公开。审核员需要知道「确认时保持自动处理」。
- #9：版主能恢复管理员确认隐藏的回复，靠审计日志追查。
- #11、#12：驳回一条就清空全部举报；一个账号举报 3 次就能暂停任意内容。用户量小时靠人工兜底，审核量随用户数线性增长。
- #13：刷热门分没有统一防刷；退款与回调竞态概率低，影响限于单个账号。
- #20：规则定下来之前，operator 可以公开管理员隐藏的作品。
- #21：迁移前的旧暂停数据需要人工恢复。

对下一轮的要求不变：标「已修复」之前，在干净检出上把 `.local/review/round4/` 到 `round8/` 的探针全部重跑，在修复报告里贴出每个探针的 `FAILED:` 行和 `mutate8.py` 的完整输出（不是自己的矩阵）。

---

本轮使用的 worktree 留在磁盘上方便复现，均为干净状态：`E:\projectHome\hw-r8-head`（`5158b87`）、`hw-r8-mut`（`5158b87`，变异用）、`hw-r8-799`（`7996923`）、`hw-r8-e4c`（`e4c9351`）。复核完可以用 `git worktree remove <路径>` 删除。本轮没有修改任何产品代码，主仓库工作区的 7 个已修改文件与本轮开始时相同。
