# 最终实现报告（2026-10-30）

执行人：Claude（开发者）。起点 HEAD `e1873fa`，终点 HEAD `0562318`。

## 1. 结论

**可以上线**，前提是创始人确认第 6 节标注「需创始人确认」的两条产品规则（M9 管理员优先、V9 主帖举报成立连带隐藏作品）。前几轮清单里的治理漏洞都已修复，每项修复都有测试，撤销后测试会失败。所有探针在干净检出上都通过，浏览器里各页面都有内容，没有 JS 错误。

## 2. 根因与修了什么

M8、A3、M7、M11 有同一个根因：主帖的 `status_source = 'moderator'` 同时表示两件事，一是「有人隐藏了这个帖子」，二是「这个帖子跟随作品，作品被人隐藏了」。作品发布时无法区分这两种情况，于是把版主单独隐藏的主帖也一起公开了。现在跟随作品的状态写 `status_source = 'work'`，这类同步永远不会覆盖帖子自己的决定。

| 提交 | 内容 | 对应问题 |
|---|---|---|
| `4b56936` | 作品同步主帖写 `'work'`，不覆盖帖子自己的决定（`moderator`、`author`），也不覆盖帖子自己的举报暂停 | **M8**、M8f、A3、M3、M4 |
| 同上 | 新列 `status_actor_role` 记录决定者的级别（admin > operator > moderator > author）。低级别不能撤销高级别的隐藏或暂停，返回 403 `decision_locked`。删除不受限制 | **M9**（管理员优先，代码注释写明待创始人确认） |
| 同上 | 回复和评论也记录级别：版主不能再公开管理员确认违规后隐藏的回复 | **R4** |
| 同上 | 驳回主帖举报时，回到作品允许的状态；作品仍暂停时主帖跟着作品，而不是直接公开 | **M7** |
| 同上 | `autoAction=false` 的确认把举报暂停转成人工裁定，之后驳回别的举报不能解除 | **M11** |
| 同上 | 运营或管理员确认作品主帖的举报，同时隐藏作品；版主的裁定只作用于帖子 | **V9**（待创始人确认） |
| 同上 | 作者删帖、管理员删作品主帖都经过 `set_topic_visibility`。作者删帖记来源 `author`，作品同步不能再改写；管理员删主帖保留行、不再物理删除，映射不会悬空 | **R2**、R2b、N2、**N5** |
| 同上 | 驳回不再传 `source="report"` | **M-g**，判断见下 |
| 同上 | 迁移 049：加列，并回填两类旧数据：(1) 与作品完全一致的主帖标为 `'work'`；(2) 047 之前被举报暂停、审计日志里只有自动暂停、从未有人工操作的行标为 `'report'`，之后驳回可以恢复 | **#21 旧数据**（部分） |
| 同上 | 删除从未被读取的 `sibling_open_before` 和没有调用者的 `_has_other_open_reports` | #11 的死代码 |
| `55ff921` | 每个账号对同一目标只保留一条未处理举报；阈值按不同举报人计数。自动暂停的审计记录只在真的暂停时写入 | **#12** |
| `b869fa4` | 管理后台对已删除主帖显示「已删除，不可恢复」，不再显示必然 409 的「✅ 恢复」 | N1d 的界面部分 |
| `59775fd` | 浏览器测试新增：作品详情页、登录后「我的投稿」、论坛列表不显示被隐藏主帖、被隐藏主帖页不显示内容。更正 `PageRendersTests` 中不实的 docstring | #4、#14 |
| `3098186` | `GET /api`、`/API/xxx` 返回 JSON 404，不再返回首页 HTML | #21 |
| `772c91e`、`0562318` | 补测试，覆盖变异运行中发现的 3 个未测到的守卫（见第 4 节） | — |

**M-g 的判断：冗余，已删除。** 在 HEAD `e1873fa` 上它不是冗余的（第九轮的 G6a/G6b 让探针失败）。改造之后，作品同步主帖时总是写 `'work'`，发布时作品自身的来源也会被清空，所以驳回时传什么 source 都不影响结果。我在干净检出上把它改成 `source="moderator"`，第 4、5、7、8、9 轮的 5 个治理探针全部通过（`.local/review/final/mg_equivalence.txt`）。这是一个等价变异，所以变异矩阵里它是唯一抓不到的一项。

**测试前提变化的说明。** `test_round4_fixes`、`test_round6_fixes`、`test_status_provenance` 里有几项测试用同一个账号举报 3 次来触发自动暂停。#12 修复后这个前提不再成立，我把它们改成 3 个不同账号，断言不变。`test_moderator_can_still_republish_its_own_decision` 原来直接调用函数、不带级别，现在显式传入级别，并新增「低级别被拒绝」的断言。没有删除或减弱任何断言。

## 3. 测试数字

| 环境 | pytest | unittest | Node `.cjs` |
|---|---|---|---|
| 干净检出 HEAD `0562318`（`E:\projectHome\hw-final-head`，porcelain 0） | **230 passed, 3 skipped** | Ran 233, OK (skipped=3) | **12/12** |
| 工作区（含创始人未提交的 7 个文件和 6 个未跟踪测试） | **237 passed** | Ran 237, OK | **17/17** |
| skill（`E:\handraw-style` `0ea944a`，porcelain 0） | **30 passed** | — | — |

起点为干净 HEAD 193 passed / 3 skipped，工作区 200。新增 37 项。工作区比 HEAD 多的 7 项，和之前几轮的原因相同：3 项种子测试在 HEAD 上 skip（`images/` 被忽略），4 项来自未跟踪的 `test_cold_start.py`。

交接文档说有 12 个测试文件不能提交，实际其中 6 个（`test_forum_resources.py`、`test_v2_curation.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_resource_presentation.cjs`、`test_single_backend_navigation.cjs`）已经由 `a65c6a4` 提交，并且在干净检出上通过。剩下 6 个仍未跟踪，我没有动。所有提交都逐个文件 `git add`。

**探针**（干净检出 `0562318`，输出在 `.local/review/final/`）：

| 探针 | 结果 |
|---|---|
| round8 `probe_gov8.py`（含 88 种穷举） | `FAILED: []`（上轮 M7、M8、M8f、M9、M11） |
| round9 `probe_gov9.py` | `FAILED: []`（上轮 A3） |
| round8 `probe_n1d.py` | 恢复返回 409 `topic_deleted`，匿名不可见 |
| round7 `probe_gov7.py` / `probe_gov7_reply.py` | `FAILED: []`；版主 `publish_reply` 403 `decision_locked`（上轮 R4 被公开） |
| round5 `probe_gov5.py` | `FAILED: []` |
| round4 `probe_gov.py` | 原样运行有 2 项失败（V3、V5），原因是它用 1 个账号举报 3 次，正是 #12 要挡住的情况。改成 3 个账号的副本 `probe_gov_distinct_reporters.py`：`FAILED: []`。上轮待定的 V6e、V9 现在通过 |
| round6 `probe_gov6.py` | M10a、M10b 是上轮已确认的探针误报（期望 `hidden`，实际是更严格的 `deleted`） |
| round3 `probe_skill.py` | `verified=True`、`associations_verified=True` |

**迁移**：用 SQLite backup API 复制开发库 `.local/handraw_v2.db`（原库只读，未修改），从 44 迁移到 49 成功，行数不变，`integrity_check` 为 ok，5 张表都有新列。这个库里没有非公开的行，所以回填只在 `test_migration_049.py` 的构造数据上验证过。

## 4. 变异矩阵

脚本 `.local/review/final/mutate_final.py`，沿用第九轮的规则：每个模式必须恰好匹配一次；改完先 `py_compile` / `node --check`，编译不过不计入；结论从 pytest 汇总行解析，collection error 记为 ERROR，不算「抓住」；跑完用 `git checkout` 还原，并打印 porcelain。全部 38 项都编译通过，没有 ERROR，跑完 porcelain 为空。

首轮在 `59775fd` 上运行（`mutate_final.txt`），抓到 33/37。抓不到的 4 项中，3 项补了测试，再连同新增的 N20 在终点 `0562318` 上重跑（`mutate_final_gaps_0562318.txt`）。

| # | 撤销什么 | 结果 | 失败数 |
|---|---|---|---|
| N1 | 作品同步写 `moderator` 而不是 `work`（M8） | CAUGHT | 4 |
| N2 | 自动流程可以覆盖帖子的人工决定（M8/A3） | CAUGHT | 7 |
| N3 | 作品同步可以覆盖帖子自己的举报暂停 | 首轮未抓到 → `772c91e` 补测试 → **CAUGHT** | 1 |
| N4 | 去掉主帖级别锁（M9） | CAUGHT | 2 |
| N5 | 去掉作品级别锁（M9） | CAUGHT | 1 |
| N6 | 去掉回复级别锁（R4） | CAUGHT | 1 |
| N7 | 驳回主帖举报时作品暂停也直接公开（M7） | CAUGHT | 1 |
| N8 | `autoAction=false` 确认不做任何事（M11） | CAUGHT | 1 |
| N9 | 运营确认主帖举报不再隐藏作品（V9） | CAUGHT | 1 |
| N10 | 版主确认主帖举报也隐藏作品 | CAUGHT | 1 |
| N11 | 主帖自动暂停不看当前状态（H4） | 首轮未抓到 → `0562318` 补测试 → **CAUGHT** | 1 |
| N12 | 同一账号的重复举报照样入库（#12） | CAUGHT | 1 |
| N13 | 阈值按行数计数（#12） | CAUGHT | 1 |
| N14 | 两处去重都去掉 | CAUGHT | 2 |
| N15 | 作者删帖改回裸 SQL、不写来源（R2） | CAUGHT | 1 |
| N16 | 管理员删作品主帖改回物理删除（N5） | CAUGHT | 1 |
| N17 | 回填判断镜像时不比较原因 | CAUGHT | 1 |
| N18 | 回填忽略人工审计记录 | CAUGHT | 1 |
| N19 | 后台对已删除主帖又显示「恢复」 | 首轮未抓到 → `0562318` 补浏览器测试 → **CAUGHT** | 1 |
| N20 | `/api`、大写路径又返回 HTML | **CAUGHT** | 1 |
| P1 | `deleted` 不再是终态 | CAUGHT | 3 |
| P2 | 发布不检查作品状态 | CAUGHT | 2 |
| P3 | 发布不清 `status_source`（MU5，上轮 0 失败） | CAUGHT | 3 |
| P4 | 确认违规记为 `report`（M-a/U4，上轮 0 失败） | CAUGHT | 2 |
| P5 | 前台隐藏不写来源 | CAUGHT | 3 |
| P6 | 删作品时主帖记 `hidden` 而不是 `deleted`（MU7） | CAUGHT | 5 |
| P7 | 后台入口发布绕过统一函数 | CAUGHT | 4 |
| P8 | 前台入口发布绕过统一函数 | CAUGHT | 4 |
| P9 | 驳回传 `source="moderator"`（M-g） | **NOT CAUGHT，等价变异**（第 2 节，5 个探针全部通过） | 0 |
| B1 | 首页不加载 `discovery.js` | CAUGHT | 2 |
| B2 | `shared.js` 加载即抛错 | CAUGHT | 9 |
| B3 | 帖子页渲染为空 | CAUGHT | 1 |
| B4 | 回执页渲染为空 | CAUGHT | 2 |
| B5 | 首页不调用发现页渲染（上轮 MH2 为 0 失败） | CAUGHT | 1 |
| B6 | `main-app.js` 加载即抛错（上轮 MH3 为 0 失败） | CAUGHT | 1 |
| B7 | 作品详情页渲染为空 | CAUGHT | 1 |
| B8 | 共创页渲染为空 | CAUGHT | 1 |
| B9 | 论坛列表包含被隐藏的帖子 | CAUGHT | 10 |

**终点 `0562318`：38 项中 37 项被抓到，剩下 1 项是等价变异。** 每项失败的具体测试名在两个 txt 文件里。

## 5. 浏览器验证

脚本 `.local/review/final/probe_pages_final.py`，在干净检出 `0562318` 上起真实服务（临时库），用 headless Chromium 读渲染后的 DOM，并收集 pageerror、console error 和所有 ≥400 的响应。截图在 `.local/review/final/shots/`。结果 `BAD: []`。

| 页面 | 渲染后 DOM 中的证据 | JS 错误 / ≥400 |
|---|---|---|
| 首页 `/` | 「作品与做法 / 终验作品标题 / fauthor / FA-013 / 查看做法 →」，主帖被隐藏的作品作为作品仍然列出 | 无 / 无 |
| 作品详情 `/?view=work` | 标题、「生图提示词 / 复制 / 一键复刻 / 终验提示词原文」、画风 FA-013 | 无 / 无 |
| 论坛列表 `/forum/` | 列出公开主帖；被隐藏和已删除的主帖**不出现** | 无 / 无 |
| 作品主帖 `/forum/?view=topic` | 「终验作品标题 / @fauthor / 点赞 收藏 回复 / 生图提示词 / 终验提示词原文 / 粗黑轮廓 FA-013」（截图 `work_thread.png`） | 无 / 无 |
| 回执 `/forum/?view=resource&kind=work` | 标题、提示词原文、「共用讨论 · 0 条回复 / 发表评论」 | 无 / 无 |
| 被隐藏的主帖 | 「未找到对应的论坛帖子」，不出现标题 | 无 JS 错误；资源接口 404，符合预期 |
| 共创「我的投稿」（登录） | 「我的投稿 / 画风待收录 / 终验共创画风 / 查看原帖 / 编辑重提 / 版本与意见」 | 无 / 无 |
| 共创「分享投稿」（登录） | 投稿表单完整 | 无 / 无 |
| 创作台、管理后台 | 正常渲染 | 无 / 无 |
| 后台话题列表 | 已删除行显示「已删除，不可恢复」，没有恢复按钮；被隐藏行仍有「✅ 恢复」（截图 `admin_topics.png`） | 无 |

## 6. 剩余风险

**需创始人确认的产品规则**

1. **M9 管理员优先。** 我选择了更安全的默认：管理员隐藏或暂停的内容只有管理员能恢复。规则实际比「admin 优先」更宽：运营隐藏的内容，版主也不能恢复（按级别 admin > operator > moderator）。如果希望同级以下也能互相撤销，改 `services.ACTOR_RANK` 即可。
2. **V9 主帖举报成立时连带隐藏作品。** 作品主帖展示的就是作品本身，所以运营或管理员确认后同时隐藏作品；版主确认只隐藏帖子。如果希望只隐藏讨论，删掉 `admin_resolve_report` 里 `linked and actor_role in (...)` 这一段。

**仍然存在的风险**

3. **3 个小号仍然可以暂停任意内容。** #12 只挡住了单个账号。注册限流的键仍然是 IP+用户名，未修。
4. **没有统一的防刷方案**（#13，未动）：点赞无门槛；复刻门槛和每日上限仍是原设计；退款回调与复刻计数的竞态未处理。
5. **驳回一条举报会关闭同目标的全部举报**（#11），这是有意保留的「一个目标一次裁定」。现在每条都来自不同账号，但举报理由可能不同，仍会被一并关闭。
6. **旧数据回填是启发式的。** 047 之前暂停、但审计日志里有任何人工操作的行，不会自动回填，仍需人工处理。047 之前「版主隐藏主帖」且「作品被隐藏」、两者原因文字也恰好相同的行，会被判为镜像，作品恢复时主帖也会恢复。开发库里没有非公开的行，所以回填只在构造数据上测试过。
7. **主帖自己的举报暂停不会随作品恢复而解除**，必须处理这条举报。这是有意的，但运营需要知道。
8. **旧的共创审核通道**（`curation.py` 中 `_publish_approved`，审核通过时写 `status='published'`）不经过 `set_work_visibility`。新作品投稿已被拒绝（D-02），所以只影响旧的作品投稿，并且只有共创管理员能触发。未修。
9. **画风/图型（`catalog_assets`）的举报流程没有来源记录**：驳回会恢复任何 `paused` 的画风。目前只有举报流程会暂停画风，所以暂时没有实际影响。未修。
10. **前端对 403 `decision_locked` 的提示未逐页验证**。后端会拒绝并返回中文原因，但我没有检查每个按钮如何显示这个错误。
11. **浏览器测试依赖 Playwright 和 Chromium**，没装时会跳过且不报错。CI 需要安装，否则第 4 节的 B 系列和 N19 在 CI 上抓不到。
12. **其他未处理的旧项**：`quick-create.js` 已提交但未接入（#18）；第八轮提到的清理脚本价格上限，在当前 `ops/purge_publish_time_forks.py` 里找不到对应代码，未核实。
13. **创始人工作区里 7 个已修改文件**（`studio-app.js` 等）和 6 个未跟踪测试不在本次提交中，我没有评审。工作区的数字包含它们。

## 7. 复现

- 干净检出：`E:\projectHome\hw-final-head`（`0562318`）；变异用：`E:\projectHome\hw-final-mut`。两个都是干净状态，复核完可以用 `git worktree remove <路径>` 删除。`hw-r9-*` 不是我建的，没有动。
- 变异：`cd <干净检出> && python -X utf8 ../handraw-web/.local/review/final/mutate_final.py [前缀...]`
- 浏览器：`cd <干净检出> && python -X utf8 ../handraw-web/.local/review/final/probe_pages_final.py`
