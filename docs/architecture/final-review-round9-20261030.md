# 第九轮终审报告（2026-10-30）

评审人：Claude（架构师兼终审）。对象：网站仓库 `5158b87..e1873fa`，3 个提交：`a65c6a4`（统一函数收口 + 浏览器测试 + 补测试 + 一次 `git add tests/`）、`6676335`、`e1873fa`（把误加的测试再移出）。本轮仍没有修复报告，「工程师声称」来自用户转述和提交信息。

方法：不采信自述，不改产品代码。

- `git worktree add --detach` 干净检出：`E:\projectHome\hw-r9-head`（HEAD `e1873fa`）、`hw-r9-mut`、`hw-r9-mut2`（变异用）、`hw-r9-a65`（`a65c6a4`，查假完成）。开始和结束时 `git status --porcelain` 均为 0 行。
- 治理探针都在临时库上起真实服务进程，只用 `Api-Key` 调接口；页面用 headless Chromium 读渲染后的 DOM。
- 工作区测试在 09:47 跑完，当时工作区与 HEAD 之间 `backend/` 只差 `runtime_policy.py`、`seed.py`（与上轮相同），治理代码一致。
- **评审进行中工作区被改动。** 10:06 新增了 `docs/architecture/handoff-to-claude-20261030.md`；10:20–10:22 有人在主仓库工作区修改了 `backend/admin_services.py`、`services.py`、`work_schema.py`（未提交，`git diff --stat HEAD -- backend` 现为 5 个文件 +428/−176，新增 `actor_role`、`automated=True`、`set_comment_visibility` 等）。这些不是我改的，本轮没有评审它们；本报告的所有结论针对已提交的 HEAD `e1873fa`，工作区数字是 09:47 的快照。

脚本和输出在 `.local/review/round9/`，以被测代码目录为 cwd 执行 `python -X utf8 <脚本>`：

| 文件 | 内容 |
|---|---|
| `rerun_probe_n1d_HEAD.txt`、`rerun_probe_gov8_HEAD.txt` | 上轮 `probe_n1d.py`、`probe_gov8.py` 原样重跑 |
| `probe_gov9.py` / `probe_gov9_HEAD.txt` | 本轮新变体：M-g 的真实按钮走法（A1、A2），版主隐藏 → 管理员暂停/发布作品（A3） |
| `mutate9.py` / `mutate9.txt` | 27 个变异。每项先确认模式恰好出现 1 次，再 `py_compile` / `node --check`，然后跑全量 pytest，从汇总行解析结果，collection error 记为 ERROR 而不是「抓到」；前端变异另跑全部 Node。跑完 `porcelain` 为空 |
| `mut_behaviour9.sh`、`mut_behaviour9b.sh` 及 `.txt` | 对测试抓不到的变异跑探针，证明它们是不是真回归 |
| `b4b_render.py` | 回执页在缺 `forum-resources.js` 时实际渲染什么 |
| `run_suites.sh` / `suites_HEAD.txt`、`suites_worktree.txt`、`suites_a65c6a4.txt` | 三处的 pytest（`-rs` 列出 skip 原因）、浏览器测试 `-v`、unittest、Node |
| `rerun_round*_HEAD.txt` | round3–round8 的其余探针原样重跑 |

## 1. 一句话结论

**可以上线，有条件。** 上轮唯一的阻塞项（N1d：举报确认把已删除主帖改成 `hidden`，随后一键公开）和高危项 R2 系列在 HEAD 上都已堵住，上轮探针 100 次「再公开」尝试全部挡住；浏览器测试是真的，四个指定变异各让 1–5 项失败。没做完的是测试：N1d 的修复、M-g、经由作品同步的 M-c **撤销后 193 项测试仍全绿**，工程师给 N1d 和 M-g 写的测试走的不是被修的那行代码。「M-g 是冗余防御」不成立，撤销后版主隐藏的主帖会被一次举报驳回公开，用的就是工程师自己的验证脚本。
## 2. 三件事逐项判定

### 2.1 `set_topic_visibility` 成为唯一写主帖状态的地方

**grep 结果**（`grep -rnE "UPDATE forum_topics" backend/`，再查 `f"UPDATE {table}"` 这类动态表名）。写 `forum_topics.status` 的位置：

| 位置 | 写什么 | 是否经统一函数 | 判定 |
|---|---|---|---|
| `services.py:1397`、`:1406`、`:1412` | 统一函数内部 | — | — |
| `admin_services.py:896-899` 删作品 | `deleted/moderator` | **是**（本轮改） | 已改 |
| `admin_services.py:1921-1925` 确认主帖举报 | `hidden/moderator`，遇 `deleted` 跳过 | **是**（本轮改） | 已改 |
| `services.py:1463-1466` 作品同步主帖 | 跟随作品，遇 `deleted` 跳过 | **是**（本轮改） | 已改 |
| `services.py:2311-2317` 举报自动暂停 | `paused/report` | **是**（本轮改） | 已改 |
| **`services.py:2206` 前台删帖**（作者/版主/员工，帖子有映射时） | `status='deleted'`，**不写来源** | **否**，仍是裸 SQL | **没改**（用户点名的 4 处之一） |
| `admin_services.py:1948-1951` 驳回主帖举报 | `published` | 否 | 有 `status IN ('paused','hidden') AND status_source='report'` 条件，不会碰 `deleted`；但不查作品状态，这就是 M7 |
| `ops/seed_cold_start.py:119` | `f'UPDATE {table} SET status=?'`，`paused` | 否 | 运维脚本，只作用于冷启动包登记的帖子；依赖未跟踪的 `backend/cold_start_content.py`，干净检出上不能运行 |
| `curation.py:432`、`:1713`，`resource_discussions.py:58`，`services.py:1948`，`seed.py:756` | `INSERT … 'published'` | — | 新建帖子，不算状态迁移 |

所以「4 处裸 SQL 全部改成调用」**不属实**：提交 `a65c6a4` 实际改的 4 处是「确认举报、作品同步、**自动暂停**、删作品」，用自动暂停替换了用户点名的**前台删帖**，提交标题「the only writer of thread status」也不属实（还有 `:2206` 和驳回）。

**前台删帖没改有没有实际影响：目前没有。** 它写的是 `deleted`，而本轮所有自动流程（同步、确认、自动暂停）都在统一函数里遇 `deleted` 跳过，人工入口遇 `deleted` 返回 409。上轮的 R2、R2b、N1c、N2 都是从这里开始的，HEAD 上全部挡住。剩下的问题是来源字段没写、而且撤销它没有测试（变异 H7，§4）。

**统一函数新增的规则**（`services.py:1374-1381`）：当前来源是 `moderator` 而调用方不是 `moderator` 时静默返回。这把上轮 `set_work_visibility` 里的 V5 守卫挪进了统一函数，对所有自动流程生效，方向正确。两处小问题：`:1379-1381` 的 `if allow_overwrite_deleted: return` 后面紧跟 `return`，是死分支；参数名 `allow_overwrite_deleted=True` 的实际含义是「遇 `deleted` 跳过」，和名字相反（docstring `:1358` 写对了）。

**用户点名项重做**（`rerun_probe_n1d_HEAD.txt`、`rerun_probe_gov8_HEAD.txt`）：

| # | 变体 | 上轮 HEAD `5158b87` | 本轮 HEAD `e1873fa` | 判定 |
|---|---|---|---|---|
| **N1d** | 用户举报主帖 → 管理员删作品 → operator「确认违规」→「✅ 恢复」 | 第 4 步 `deleted`→`hidden/moderator`，第 6 步 200 公开 | 第 4 步 200、状态保持 `deleted/moderator`；第 6 步 **409 `topic_deleted`**；匿名 boot 不列出 | **已修复** |
| N1、N1b、N1c | 删作品/作者删帖 → 举报 → 版主确认 → publish | 公开 | `deleted`，不可见 | **已修复** |
| R2、R2b、N2 | 作者删帖 → 作品隐藏/暂停/举报驳回 → 发布 | 公开 | `deleted`，不可见 | **已修复**（上轮 #2） |
| M10a | 删作品 → 后台 publish | 409 | 409 | 保持 |
| R1、R1b、R1x、R2c | 两个入口 hide→publish、交叉入口 | 409 | 409 | 保持 |
| M3、M4、M5 | 两个入口各一遍 | 正常 | 正常 | 保持 |
| Part 2 穷举 | 两个入口全部 action × 两种已删除主帖 × 两个角色，每次后再经两个入口 publish | 88/88 挡住 | **100/100 挡住**（本轮 Part 3 新增的 N 系列也计入） | 保持 |
| M7、M8、M8f、M9、M11 | 上轮已列的中/低项 | 失败 | **仍失败**，代码未改 | 未修（见 §8） |

**新变体**（`probe_gov9_HEAD.txt`）：

| 变体 | HEAD 结果 |
|---|---|
| A1 版主在前台隐藏作品主帖 → 3 人举报**作品**（自动暂停）→ operator 驳回一条 | 作品恢复公开，主帖保持 `hidden/moderator`，匿名不可见。**正确** |
| A2 同上，管理员在后台隐藏主帖 | 正确 |
| **A3** 版主隐藏主帖 → 管理员**暂停**作品 → 管理员**发布**作品 | **主帖公开，匿名可见**。暂停时 `source="moderator"`（`admin_services.py:832`）不受「moderator 优先于自动流程」规则约束，主帖被改成 `paused/moderator`，发布时一并公开。这是 M8 的同类（M8 是「隐藏」，A3 是「暂停」），两个员工互相覆盖，有审计日志 |
| 其他找过的路径 | `curation.py:1041` 收录发布、`:1230` 撤回写的是 `works.status`，不写主帖，且 `curation.submit` 自 D-02 起拒绝作品条目（`curation.py:363-371`），只影响旧数据，未构成新路径；`features.py:189` 作者编辑不改状态，`deleted` 时 404；`admin_services.py` 其他函数（`:1534-1614` 置顶/加精/编辑/悬赏/物理删除）不改 `status` |

**判定：按目的完成，按字面没完成。** 「`deleted` 不能被覆盖」在所有路径上成立，上轮的阻塞项和高危项都已修复，我没找到新的复活路径。但前台删帖仍是裸 SQL，提交标题和用户转述的「4 处全改」不属实。
### 2.2 浏览器测试

**是真的。** `tests/test_browser_render.py` 用 `playwright.sync_api` 启动 Chromium（`:28-34`、`:55-57`），起真实服务，发布已知标题和提示词的作品，打开 5 个页面，读 `inner_text("body")`，并收集 `pageerror`（`:83`）。HEAD 和工作区 `-v` 都是 5 passed、0 skipped（`suites_*.txt`）；HEAD 连跑 5 次全部通过，每次约 4.8 秒，没有偶发失败。

四个指定变异的结果见 §3。四项都至少让 1 项测试失败，验收标准**达成**。

**够不够格当上线门槛：本地够，作为自动门槛还不够。** 原因：

1. **CI 不跑它。** `.github/workflows/checks.yml` 的 `portable-client` 只装了 Python 和 Node，没有 `pip install playwright` / `playwright install chromium`。测试类 `@skipUnless(_HAS_PLAYWRIGHT)`（`:36`）、启动失败也 `skipTest`（`:80`），所以在 CI 上这 5 项会全部 skip、显示绿色。
2. **回执页只断言标题**（`:122-127`），不断言提示词。我删掉 `forum.html` 里的 `forum-resources.js`（B4b），回执 URL 退回论坛列表，列表里的帖子标题恰好就是作品标题，测试通过；实际页面上没有提示词、没有评论框（`b4b_render.py` 输出：`title in root: True | prompt in root: False`）。帖子页那项断言了提示词（`:116-120`），回执页照抄一行即可。
3. **作品详情页 `/?view=work&id=` 没有测试**（B7 撤销渲染，0 失败）；共创页只断言「不出现『接口不存在』」（`:134-138`），渲染空也通过（B8）。
4. 只收集 `pageerror`，不收集 console error 和 ≥400 响应。静态资源 404 由 `test_every_linked_asset_exists_and_is_served` 兜底，影响不大。

建议：回执页加一行提示词断言；加 `/?view=work&id=…`；CI 装 Playwright，或设一个环境变量（例如 `HANDRAW_REQUIRE_BROWSER=1`）让缺浏览器时失败而不是跳过。

**判定：完成。** 达到了验收标准，作为门槛有上面 4 处缺口。

### 2.3 补测试，变异脚本先编译检查

| 要求 | 新增测试 | 撤销对应代码后 | 判定 |
|---|---|---|---|
| 「确认违规记为 moderator」（M-a/U4） | `test_status_provenance.py:124`、`:137` | **G4：2 failed**（就是这两项） | **完成** |
| M-c（主帖来源守卫） | `test_status_provenance.py:152`：直接调 `set_topic_visibility(source="report")` | G3（删守卫）：**1 failed**。H1（作品同步改回裸 SQL，即 M-c 原本保护的那条路径）：**0 failed**，而探针 M3、M4 两个入口共 4 项、A1、A2、A3 失败（`mut_behaviour9b.txt`） | **部分完成**：守卫本身有测试，「作品同步必须经过守卫」没有 |
| M-g（驳回传 report 来源） | `test_status_provenance.py:189`、`test_governance_http.py:176` | **G6a、G6b：0 failed** | **未完成**，测试无效（见下） |
| N1d | `test_governance_http.py:144` | **G5b（把确认主帖举报改回上轮的裸 SQL）：0 failed**，而 `probe_n1d.py` 第 6 步 200 公开、匿名可见，`probe_gov8` 的 N1、N1b、N1c 重新失败（`mut_behaviour9b.txt`） | **未完成**，测试无效（见下） |
| 变异脚本先编译 | `.local/mutate_final*.py` 有 `py_compile` | — | **做了一半**（见下） |

**两条无效测试的原因：**

- `test_confirming_a_report_cannot_downgrade_a_deleted_thread`（`test_governance_http.py:144-174`）举报的是**作品**（`targetType: "work"`，`:154`），不是主帖。删作品时作品行已经删掉，确认时 `set_work_visibility` 在 `services.py:1443-1444` 查不到作品直接返回，根本走不到被修的 `admin_services.py:1921`。N1d 的真实路径是**举报主帖**。
- `test_dismissal_passes_the_report_source`（`:189`）和 `test_dismissal_does_not_undo_a_moderator_hidden_topic`（`test_governance_http.py:176`）只举报 1 次，阈值是 3（`services.py:2264`），作品没有被自动暂停，驳回时 `allow_from=("paused","hidden")` 不满足，`set_work_visibility` 什么都不做，主帖自然还是 `hidden`。无论驳回传什么来源都通过。

**变异脚本：** `mutate_final.py`、`mutate_final2.py`、`mutate_final3.py` 都在跑测试前 `py_compile`，编译不过就跳过，这一点修好了。但判定仍是 `proc.returncode != 0`；`mutate_final.py:40-42` 写了「Guard against collection errors」，函数体是 `pass`，不起作用；`mutate_browser.py` 改的是 JS，不做 `node --check`，也只看返回码。本轮它们的结果碰巧是对的，但同样的错误（导入失败记为「CAUGHT」）仍会再发生。另外这些脚本直接改主仓库工作区里的文件（工作区有 38 个未提交改动），中断时会把变异留在用户的未提交代码里。

**判定：完成约一半。**
## 3. 浏览器测试的变异验证结果

`mutate9.txt`，每项先 `node --check`，再跑全量 pytest 和全部 Node：

| # | 变异（撤销什么） | 结果 | 失败的测试 |
|---|---|---|---|
| **B1 首页不渲染** | `index.html` 删掉 `discovery.js` | **2 failed** | `test_browser_render::test_home_page_renders_content_without_js_errors`、`test_governance_http::test_home_page_renders_seeded_content` |
| **B2 加载即抛错** | `shared.js` IIFE 第一行 `throw` | **5 failed** | 浏览器 5 项全部；Node 另有 3 项失败（`test_ranking_parity`、`test_v2_studio_state`、`test_works_browser`） |
| **B3 帖子页空** | `forum-app.js` topic 视图 `root.innerHTML = ""` | **1 failed** | `test_work_topic_page_shows_title_and_prompt` |
| B3b 帖子页空（工程师的写法） | `forum-app.js` 加载即 `throw` | 4 failed | 论坛 4 项 |
| **B4 回执页空** | resource 视图 `root.innerHTML = ""` | **1 failed** | `test_receipt_page_shows_the_work` |
| B4b 回执页退回列表 | `forum.html` 删掉 `forum-resources.js` | **0 failed** | —（见 §2.2 第 2 条） |
| B5 首页停在「正在加载」（上轮 MH2） | `main-app.js` 不调用 discovery 渲染 | 1 failed | 首页 |
| B6 首页加载即抛错（上轮 MH3） | `main-app.js` `throw` | 1 failed | 首页 |
| B7 作品详情页空 | `renderWorkDetailPage` 改成清空 | **0 failed** | —（没有测试） |
| B8 共创页空 | `HandrawCuration.render` 改成清空 | **0 failed** | —（断言太弱） |

**用户指定的四项全部达成**，上轮 0 失败的 MH2–MH5（B5、B6、B3、B4）现在都能抓到。

## 4. 完整变异矩阵结果

全部 27 项都编译通过、模式恰好匹配 1 次，没有 INVALID，没有 collection error，跑完 `porcelain` 为空。

**用户指定的六项：**

| # | 撤销什么 | 结果 | 失败的测试 |
|---|---|---|---|
| G1 | deleted 守卫（`services.py:1369` → `if False:`） | **2 failed** | `test_governance_http::test_deleted_thread_cannot_be_revived_by_either_entry`、`test_round4_fixes::test_deleted_thread_cannot_be_republished` |
| G2 | publish 的作品状态检查（`:1392`） | **2 failed** | `test_admin_entry_also_refuses_when_the_work_is_hidden`、`test_frontend_cannot_publish_a_thread_whose_work_is_hidden` |
| G3 | topic moderator 守卫（`:1378`） | **1 failed** | `test_status_provenance::test_topic_source_guard_blocks_report_flow_from_touching_a_moderator_state` |
| G4 | 确认违规记为 moderator（`admin_services.py:1911` 改回 `report`） | **2 failed** | `test_confirmed_report_is_recorded_as_a_moderator_verdict`、`test_moderator_verdict_survives_a_later_dismissal` |
| G5a | 确认举报跳过 deleted（`:1924` 改 `False`，遇 deleted 抛 409） | **0 failed** | — |
| G5b | 确认主帖举报改回上轮裸 SQL（重新打开 N1d） | **0 failed** | —。探针：N1d 第 6 步 200 公开；N1、N1b、N1c 失败 |
| G6a | 驳回不传 `source`（默认 `moderator`） | **0 failed** | —。探针见 §5 |
| G6b | 驳回传 `source="moderator"`（工程师的写法） | **0 failed** | — |

**其他路径：**

| # | 撤销什么 | 结果 | 说明 |
|---|---|---|---|
| H1 | 作品同步改回裸 SQL、无任何守卫 | **0 failed** | 探针：M3、M4 两个入口共 4 项，R2、R2b、N2，A1、A2 全部失败 |
| H2 | 作品同步遇 deleted 抛错 | 0 failed | 按代码推断：作者删帖后管理员无法隐藏/暂停该作品（409），未用探针验证 |
| H3 | 删作品时主帖改成 `hidden/''`（MU7） | 4 failed | |
| H4 | 自动暂停不检查当前是否 `published` | 0 failed | 统一函数已挡住 `deleted` 和 `moderator`，剩下的只有 `hidden/report`、`paused/report`，目前无路径产生，基本是等价变异 |
| H5 | 主帖驳回也恢复 `moderator`（M-k） | 1 failed | `test_round6_fixes::test_moderator_hidden_topic_stays_hidden_after_dismissal` |
| H6 | publish 不清 `status_source`（MU5） | 0 failed | 按代码推断：版主恢复的主帖会带着 `moderator` 来源公开，之后举报达阈值时自动暂停被统一函数静默跳过，接口仍返回 `autoPaused: true`（`services.py:2317`） |
| H7 | 前台删帖写 `hidden` 而不是 `deleted` | **0 failed** | 作者删帖的终态没有测试；现有删帖测试都走管理员删作品 |
| E1、E2 | 两个入口 publish 绕过统一函数 | 2 failed、3 failed | |

**合计 27 项：15 项抓到，12 项 0 失败。** 0 失败里有 4 项已用探针证明是真回归、且正是本轮声称修好的东西：G5b（N1d）、G6a/G6b（M-g）、H1（M-c 的实际路径）。
## 5. M-g「冗余防御」说法是否成立

**不成立，是漏洞。**

**机制。** 驳回作品举报时 `set_work_visibility(..., source="report", ...)`（`admin_services.py:1937-1941`）会把作品恢复成 `published`，并经 `services.py:1463` 同步主帖。统一函数里「moderator 优先于自动流程」的守卫（`services.py:1378`）只在调用方来源**不是** `moderator` 时生效。`set_work_visibility` 的 `source` 默认值就是 `"moderator"`（`services.py:1423`），所以只要驳回不传 `source="report"` 或传成 `moderator`，守卫就认为这是人工决定，放行，主帖被公开。作品自己的来源检查 `allow_sources=("report",)` 只管作品，不管主帖。

**复现**（`mut_behaviour9.txt`，`probe_gov9.py` A1）：版主在前台隐藏作品主帖（理由「跑题」）→ 3 名用户举报作品，作品自动暂停 → operator 在举报队列驳回一条。

| | HEAD | G6a（不传 source） | G6b（传 moderator） | G3（删守卫） |
|---|---|---|---|---|
| 主帖最终状态 | `hidden/moderator`，匿名不可见 | **`published`，匿名可见** | **`published`，匿名可见** | **`published`，匿名可见** |
| `probe_gov8` 新增失败 | — | M3、M3 后台、M4、M4 后台 | 同左 | 同左 |
| `round5/probe_gov5` 新增失败 | — | V5、N1、N2 | 同左 | 同左 |

三列结果完全相同：撤销 M-g 等于撤销 topic 守卫本身。

**工程师自己的脚本也证明了这一点。** `.local/verify_mg_final.py` 就是这个场景。我在 HEAD 上跑：`topic after dismissal: {'status': 'hidden', 'status_source': 'moderator'}`；把驳回改成 `source="moderator"`（`mutate_final3.py` 的写法）再跑：`{'status': 'published', 'status_source': ''}`。脚本自己打印的期望是「应仍 hidden/moderator」。

**为什么工程师会得出「冗余」：** 他的两条测试只举报 1 次（§2.3），作品没被暂停，驳回什么都不做，所以无论来源是什么都通过。由此推出「改成 moderator 也没影响」，这个推论建立在一个不触发该路径的测试上。

**安全影响的大小：** 不是越权。驳回作品举报需要 operator 以上（版主不能裁定作品举报，`admin_services.py:1859-1860`），而 operator 本来就能在后台直接公开主帖。影响是完整性和审计：处理作品举报的人没看过这条主帖，也没有对主帖做任何操作，主帖上的审计日志里没有这次公开，版主的隐藏决定被静默推翻。这正是 round5 V5 立的规则（举报流程不得推翻人工对主帖的决定），撤销 M-g 会让 V5、M3、M4 一起回退。所以它不是冗余的，是 topic 守卫能生效的前提。目前代码是对的，缺的是测试。
## 6. 是否仍有假完成

**有，比前几轮轻。** 代码改动属实，测试数字属实，断言没有改弱（`git diff 5158b87 HEAD -- tests` 只有新增 950 行，没有删除任何断言或测试）。可证伪的陈述：

| 陈述 | 事实 |
|---|---|
| 提交标题「make set_topic_visibility **the only writer** of thread status」 | 前台删帖 `services.py:2206` 和驳回主帖举报 `admin_services.py:1948-1951` 仍直接写 |
| 用户转述「4 处裸 SQL 全部改成调用」（确认举报、作品同步、前台删帖、删作品） | 前台删帖没改。提交信息列的 4 处是「确认举报、作品同步、**自动暂停**、删作品」，换掉了一项 |
| 提交信息「every change records its source」 | `services.py:2206` 不写来源（上轮已指出，未改） |
| 提交信息「Removing discovery.js, throwing during boot, or **emptying a view** now each fail a test」 | 前两项属实。「清空视图」对帖子页、回执页属实，对作品详情页（B7）、共创页（B8）不属实 |
| 提交信息「plus HTTP tests for the report-confirm path」 | 测试举报的是作品，走不到被修的主帖确认那一行（G5b 0 失败，§2.3） |
| 测试名 `test_dismissal_passes_the_report_source` | 驳回传什么都通过（G6 0 失败） |
| 工程师「M-g 是冗余防御」 | 不成立（§5），他自己的验证脚本在变异下输出 `published` |
| docstring `services.py:1351`「the report flow … route through here」 | 主帖举报驳回仍是裸 SQL |
| `mutate_final.py:40`「Guard against collection errors」 | 函数体是 `pass` |
| 「新增 `tests/test_browser_render.py`，用真实 Chromium」 | **属实** |
| 「变异脚本加了 `py_compile` 前置检查」 | **属实** |
| 「4 处裸 SQL 改成调用后 N1d 修好了」 | **属实**（行为上），只是没有有效测试 |

**新增测试是否真的执行：** 是。HEAD 上 `pytest -rs` 只有 3 项 skip，全部是 `test_seed_starter_library.py`「style art not installed in this checkout」（干净检出没有被忽略的 `images/`，与前几轮相同）。浏览器 5 项 `-v` 全部 PASSED。在 CI 上浏览器 5 项会 skip（§2.2）。

**`git add tests/` 加进去又移出（第三次）：属实。** 历史：

| 提交 | 动作 |
|---|---|
| `212e6e0` → `786f249` | 加入、移出（第一次，「untrack tests whose feature modules are not in this commit」） |
| `4636feb` → `457bab8` | 再加入、再移出（第二次） |
| **`a65c6a4` → `6676335`、`e1873fa`** | **第三次**。`a65c6a4` 一次加了 14 个测试文件，其中 `test_cold_start.py` 依赖未跟踪的 `backend/cold_start_content.py`，5 个 `.cjs` 依赖工作区里未提交的 `studio-app.js` 等改动。两个后续提交把它们移出，提交信息自己写了「Re-added by a broad 'git add tests/'」「untrack the cold-start suite **again**」 |

干净检出 `a65c6a4` 实测（`suites_a65c6a4.txt`）：**pytest 4 failed, 193 passed, 3 skipped；Node 12 passed, 5 failed**。也就是说，修复主体所在的那个提交本身是红的，HEAD 才是绿的。对 `git bisect` 和回滚到 `a65c6a4` 的人是个坑。同一批里留下的 7 个文件（上轮要求的 4 个，加 `test_resource_presentation.cjs`、`test_status_provenance.py` 的扩充、`test_v2_curation.py`）在 HEAD 上都能通过，这部分是对的。

**模式：** 第九轮。代码这轮第一次没有找到新的复活路径。验证方式的问题从「变异永远失败」变成了「测试不触发被测路径」：N1d 和 M-g 的测试各自断言了一个正确的结果，但那个结果在没有修复时也成立。判断方法和上轮一样简单：撤销修复，看测试红不红。
## 7. 实际测试数字

| 套件 | 命令 | HEAD `e1873fa` 干净检出 | 当前工作区 | `a65c6a4` 干净检出 | 用户给的数字 |
|---|---|---|---|---|---|
| 网站 Python | `python -m pytest -q -rs` | **193 passed, 3 skipped**, 11 subtests（48.5s） | **200 passed**, 11 subtests（50.6s） | **4 failed**, 193 passed, 3 skipped | 193/3 ✅；200 ✅ |
| 网站 Python | `python -m unittest discover -s tests` | Ran 196, OK (skipped=3) | Ran 200, OK | — | — |
| 浏览器测试 | `pytest -v tests/test_browser_render.py` | **5 passed，0 skipped**；连跑 5 次全过 | 5 passed | — | — |
| 前端 | 逐个 `node tests/*.cjs` | **12/12** | **17/17** | **12 passed, 5 failed** | 12 ✅；17 ✅ |
| skill | `cd E:\handraw-style && python -m pytest skills/community-share/tests -q` | — | **30 passed**（`0ea944a`，porcelain 0） | — | 30 ✅ |

HEAD 比上轮 158 多 35 项：`test_forum_resources.py` 9、`test_v2_curation.py` 10、`test_v2_single_backend.py` 4、`test_browser_render.py` 5、`test_status_provenance.py` 新增 5、`test_governance_http.py` 新增 2。Node 多 3 个：`test_forum_work_post.cjs`、`test_single_backend_navigation.cjs`、`test_resource_presentation.cjs`。上轮 #10（4 个测试未跟踪）**已解决**。

工作区比 HEAD 多 7 项 Python：`test_cold_start.py` 4 项（未跟踪），`test_seed_starter_library.py` 3 项在工作区不 skip（本地有被忽略的 `images/`）。多 5 个 Node：被 `e1873fa` 移出的 5 个 `.cjs`。

**探针：**

| 探针 | HEAD 结果 |
|---|---|
| `round8/probe_n1d.py` | **第 6 步 409，匿名不可见**（上轮：公开） |
| `round8/probe_gov8.py` | FAILED: M7、M8、M8f、M9、M11（上轮 11 项，N1、N1b、N1c、N2、R2、R2b 已不在列表） |
| `round9/probe_gov9.py` | FAILED: A3（M8 同类） |
| `round7/probe_gov7.py` | FAILED: M7、M8、M8f、M9、M11 |
| `round6/probe_gov6.py` | 失败项中 M10a、M10b 是探针误报（期望 `hidden`，实际是更严的 `deleted`），其余为 M7、M8、M9、M11 |
| `round5/probe_gov5.py` | `FAILED: []` |
| `round4/probe_gov.py` | V6e、V9（待定规则） |
| `round7/probe_gov7_reply.py` | `publish_reply` 仍能公开确认违规的评论（R4） |
| `round6/probe_head6.py` | 静态资源 `/` 10、`/studio.html` 11、`/forum/` 13、`/admin.html` 4，全部无 broken |
| `round8/probe_pages8.py` | 10 页中 9 ok；「curation mine」BAD 是上轮已说明的探针写错（断言投稿标题，页面显示条目名），非产品问题 |
| `round3/probe_skill.py` | `verified=True`、`associations_verified=True` |
| `round9/mutate9.py` | 27 项有效变异，15 项抓到，12 项 0 失败（§4） |
## 8. 剩余问题（按严重度）

行号以 HEAD `e1873fa` 为准。

| # | 严重度 | 问题 | 位置 |
|---|---|---|---|
| 1 | **高**（测试） | 本轮修复的核心路径没有有效回归测试：撤销 N1d 修复（G5b）、M-g（G6a/G6b）、作品同步经过统一函数（H1）、作者删帖的 `deleted` 终态（H7），193 项全绿；探针证明前三项是真回归（N1d 复活已删除作品的主帖；M3、M4、V5、R2 系列回退）。原因：N1d 测试举报的是作品不是主帖；M-g 测试只举报 1 次，没达到阈值 3 | `tests/test_governance_http.py:144-174`（`:154`）、`:176-198`；`tests/test_status_provenance.py:189-200`；被保护代码 `backend/admin_services.py:1921-1925`、`:1937-1941`，`backend/services.py:1463-1466`、`:2206` |
| 2 | 中 | 浏览器测试在 CI 上全部 skip（CI 不装 Playwright），缺浏览器时跳过而不是失败；回执页不断言提示词（B4b 漏）；作品详情页无测试（B7）；共创页断言太弱（B8） | `.github/workflows/checks.yml` `portable-client`；`tests/test_browser_render.py:36`、`:80`、`:122-127`、`:134-138` |
| 3 | 中 | 版主隐藏主帖 → 管理员暂停或隐藏作品 → 发布作品，主帖公开（A3、M8、M8f，连续三轮）。员工对作品的操作以 `source="moderator"` 同步主帖，不受统一函数的来源守卫约束 | `backend/admin_services.py:828`、`:832`、`:836`；`backend/services.py:1378` |
| 4 | 中 | 主帖举报驳回不查作品状态，作品仍暂停时主帖被公开（M7）；且这是统一函数之外剩下的两处写主帖状态之一 | `backend/admin_services.py:1946-1951` |
| 5 | 中 | `autoAction=false` 确认后不改来源，下一次驳回公开作品（M11） | `backend/admin_services.py:1903` |
| 6 | 中 | 版主 `publish_reply` 能公开管理员确认违规而隐藏的回复（R4） | `backend/services.py:2216-2219` |
| 7 | 中 | 驳回一条举报清空同一目标的全部举报；`sibling_open_before` 算出后不读；`_has_other_open_reports` 无调用者 | `backend/admin_services.py:1881-1897`、`:1778` |
| 8 | 中 | 单个账号举报 3 次即可暂停任意作品或主帖 | `backend/services.py:2281-2295` |
| 9 | 中 | 复刻门槛、每日上限、注册限流、点赞门槛；退款后成功回调、复刻计数竞态（上轮 #13，未动） | `backend/curation.py:1600`、`:1614`；`backend/server.py:2100`；`backend/services.py:2882` 一带 |
| 10 | 低（流程） | `a65c6a4` 干净检出是红的（4 pytest、5 Node 失败），第三次 `git add tests/` 误加；工程师变异脚本仍按返回码判定，collection error 守卫是 `pass`，并直接改工作区文件 | `a65c6a4`；`.local/mutate_final.py:40-44`、`.local/mutate_browser.py:23` |
| 11 | 低 | 前台删帖仍是裸 SQL、不写来源，与提交标题不符；目前无实际后果 | `backend/services.py:2206` |
| 12 | 低 | 统一函数死分支；`allow_overwrite_deleted=True` 的含义是「跳过」，与名字相反；docstring 说举报流程都经过这里，主帖驳回不经过 | `backend/services.py:1379-1381`、`:1346`、`:1351` |
| 13 | 低 | publish 不清 `status_source` 没有测试（H6）；若回退，版主恢复的主帖不会再被举报自动暂停，接口仍报 `autoPaused: true` | `backend/services.py:1397`、`:2317` |
| 14 | 低 | 后台话题列表对 `deleted` 主帖仍显示「✅ 恢复」，点击返回 409 | `demo/assets/admin-app.js:1169` |
| 15 | 低 | 后台物理删除作品主帖后映射仍在，讨论永久不可用（N5）；`work is None` 分支不可达 | `backend/admin_services.py:1614`；`backend/services.py:1392` |
| 16 | 低 | 收录撤回只改 `works.status` 不同步主帖；只影响 D-02 之前的旧投稿 | `backend/curation.py:1228-1230` |
| 17 | 低 | `ops/seed_cold_start.py` 已跟踪，但依赖未跟踪的 `backend/cold_start_content.py`，干净检出上不能运行；它用动态表名写主帖状态，grep `forum_topics` 查不到 | `ops/seed_cold_start.py:25`、`:119` |
| 18 | 低 | operator `publish` 覆盖管理员 `hide`（M9/V6e）；主帖举报确认后作品仍公开（V9）。需先定规则 | `backend/admin_services.py:825-828` |
| 19 | 低 | 047 迁移前被举报暂停的旧数据无法恢复；`GET /api`、`/API/xxx` 返回 HTML；清理脚本与价格上限不一致 | `backend/work_schema.py:228-232`；`backend/server.py`；`ops/purge_publish_time_forks.py:37` |
| 20 | 低 | `quick-create.js` 已提交但 HEAD 的 `studio-app.js` 不调用 | `demo/studio.html:22` |

上轮 #1（N1 系列，阻塞）、#2（R2 系列）、#4（无浏览器测试）、#10（4 个测试未跟踪）本轮已修复；#3、#5 部分修复，并入本轮 #1、#10。
## 9. 能否上线

**可以上线 HEAD `e1873fa`。** 依据：

- 上轮唯一的阻塞项 N1d 和高危项 R2 系列，在干净检出上用真实按钮走法和穷举都挡住了；用户点名的 M10a、R1、M3、M4、M5 全部正常；我找了 `curation`、`admin_services` 其他函数、`features`、`resource_discussions`、运维脚本，没有找到新的复活路径。
- 首页、作品详情、作品主帖、回执、论坛、共创页、创作台、后台在浏览器里都有内容、无 JS 错误、无 404 资源；skill 发布回读 `verified=True`。
- 全套测试：HEAD 193 passed / 3 skipped、Node 12/12；工作区 200 passed、Node 17/17；skill 30 passed。与用户给的数字一致。

**需要接受的风险：**

1. **最大的风险是回归，不是现有漏洞（#1）。** N1d、M-g、作品同步守卫这三处修复目前是对的，但撤销任何一处测试都不报。这个项目九轮里有多次「修好的东西被下一轮改回去」。上线后第一次改 `services.py` 或 `admin_services.py` 之前，必须先补下面 4 条测试，每条写完都要撤销对应代码确认它变红：
   - N1d：举报**主帖**（`targetType: "topic"`）→ 删作品 → 确认（`autoAction: true`）→ 两个入口 publish，断言 409、匿名不可见。撤销 `admin_services.py:1921-1925` 应失败。
   - M-g：版主隐藏主帖 → **3 名不同用户**举报作品 → 驳回一条，断言主帖 `hidden/moderator`。把 `:1939` 改成 `source="moderator"` 应失败。
   - 作品同步：同一场景下把 `services.py:1463-1466` 换回裸 UPDATE 应失败（上一条通常能同时覆盖）。
   - 作者删帖：作者经前台删除作品主帖 → 管理员隐藏再发布作品 → 两个入口 publish，断言 `deleted`。把 `services.py:2206` 改成 `hidden` 应失败。
2. **浏览器测试只在本地生效（#2）。** CI 上它 skip。发布前要有人在装了 Chromium 的机器上跑一次全套，或者给 CI 装上 Playwright。回执页补一行提示词断言。
3. **员工之间互相覆盖（#3、#18）。** 管理员或 operator 对作品做暂停/隐藏再发布，会公开版主隐藏的主帖；operator 可以公开管理员隐藏的作品。都是受信员工，有审计日志可查。建议规则：作品同步遇到主帖来源为 `moderator` 且不是同一次操作时不动主帖。
4. **举报流程的边角（#4、#5、#7、#8）。** 主帖驳回不看作品是否在暂停；`autoAction=false` 确认后下一次驳回会公开；驳回一条清空全部；一个账号举报 3 次就能暂停任意内容。用户量小时靠人工兜底，审核员需要知道「确认时保持自动处理」。
5. **版主能恢复管理员确认隐藏的回复（#6）。** 靠审计日志追查。
6. **防刷与竞态（#9）。** 刷热门分没有统一防刷；退款与回调竞态概率低，影响限于单个账号。
7. **旧数据（#16、#19）。** D-02 前的收录作品撤回后主帖仍公开；迁移前被举报暂停的内容需要人工恢复。

**不要回滚到 `a65c6a4`**，它的干净检出有 9 项测试失败；需要回滚时用 `e1873fa`。

---

本轮使用的 worktree 留在磁盘上方便复现，均为干净状态：`E:\projectHome\hw-r9-head`（`e1873fa`）、`hw-r9-mut`、`hw-r9-mut2`（`e1873fa`，变异用）、`hw-r9-a65`（`a65c6a4`）。复核完可以用 `git worktree remove <路径>` 删除。本轮没有修改任何产品代码；变异只在 `hw-r9-mut`、`hw-r9-mut2` 里做，跑完已 `git checkout` 还原。主仓库工作区里 10:20 之后出现的 `backend/` 改动来自本轮之外（见开头方法一节），上线判断不包括它们，提交前需要单独评审。

**附：`handoff-to-claude-20261030.md` 里与实测不符的地方**（供接手者参考）：

- 「`services.set_topic_visibility` 是主帖状态的唯一写入点」：不属实，见 §2.1（`services.py:2206`、`admin_services.py:1948-1951`）。
- 遗留清单第 3 项「R2/R4：作者删帖后作品『隐藏→发布』，主帖被重新公开」：R2 在 HEAD 上已修复；R4（`publish_reply`）仍在。
- 遗留清单第 10 项「M-g … 是『冗余防御』（work 层先拦截）」：不成立，见 §5。work 层的 `allow_sources` 只拦作品，不拦主帖。
- 「未跟踪的测试文件」列表里的 `test_forum_resources.py`、`test_v2_curation.py`、`test_v2_single_backend.py`、`test_forum_work_post.cjs`、`test_resource_presentation.cjs`、`test_single_backend_navigation.cjs` 已在 HEAD 跟踪，并能在干净检出上通过，不要据此把它们移出。
