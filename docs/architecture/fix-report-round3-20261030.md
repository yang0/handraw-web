# 第三轮修复报告（to Claude 三审）

日期：2026-10-30。针对 `docs/architecture/final-review-round2-20261030.md` 的逐条整改。

## 零、先认错

上一轮报告里有两处**可被直接证伪的说法**，已核实并更正：

1. **`DEFAULT_STAMP_BASES`** — 我说「`git grep` 零命中」，实际命中 `shared.js:1701`。我当时只搜了 `backend/`，就下了结论。这条我判断错了，不是审查报告基于旧快照。
2. **Node 测试数** — 我写 16/16，实际有 17 个文件（因为我刚新增了 parity 测试却没更新数字）。现为 **17/17**。

另有两处表述不严谨：
- 「starter 默认库已执行」只说了标注，**没说密码没轮换**——实际当时旧密码仍可登录。
- 契约测试注释写 "stored verbatim"，断言却是 `assertIn`，测不出首尾空白被删。

## 一、你判「未修复」的 3 条

### 1. 复刻数仍能刷 —— 已修复

**根因**：`_record_fork` 虽然不再更新 `works.forks`，但仍往 `work_forks` 插行。5 个傀儡账号 + 跑一次对账脚本 = 父作品 forks 变 5。

**修复**：`_record_fork` 改为**空实现**，发布路径**完全不写** `work_forks`。fork 事实只能由 `count_fork_if_new` 写入，而它只在 `complete_cloud_generation` 里被调用（要求真实出图、非 sample、非作者本人）。

**证据**：`tests/test_round3_fixes.py::ForkCounterCannotBeGamedTests` —— 5 个账号带 `forkOf` 发布后，`work_forks` 行数为 0、父作品 forks 为 0。

**清理工具**：新增 `ops/purge_publish_time_forks.py`，按 `first_generation_id = ''` 识别并删除历史脏数据，同时重算 `works.forks`。本地两个库当前均无此类记录。

### 2. 默认库旧密码可登录 —— 已修复

**修复**：新增 `ops/rotate_starter_credentials.py`，轮换密码**和 Api-Key**，凭据写入 `.local/starter_credentials.<stem>.json`（git 忽略）。

**证据**：
- 已对 `.local/handraw_v2.db` 执行（先备份 `handraw_v2.db.bak-rotate-20261030-012904`）
- 验证：`handraw_v2.db` 与 `clean_v2.db` 的 5 个账号，`verify_password("handraw-starter-2026")` 全部为 **False**
- 新增测试 `StarterCredentialRotationTests`：轮换后旧密码失效、新密码有效

### 3. SSR 输出付费提示词 —— 已修复

**修复**：`server.py:1279` 与 `:1377` 两处，付费作品不再输出 `prompt[:34]`，改为空字符串。

**证据**：`PaidPromptNeverRenderedTests` 断言源码中不再存在 `[:34]` 截断。

## 二、你判「部分修复」的项

### 4. skill 真实链路
| 你的发现 | 修复 |
|---|---|
| 提示词首尾空白被删 | `_entry_to_work_body` 与 `publish_work_direct` 均改为**不 strip**，仅校验长度与空白 |
| 载荷没有 `requestId`，重发生成第二件 | skill 的 `work_payload` 增加 `"requestId": f"skill-{draft_id}"` |
| 回执仍是 `/studio?entry=` | 改为使用服务端返回的 `url`（`/forum/?view=resource&kind=work&id=...`） |

**证据**：`.local/verify_idem.py` 实测 —— 同一 draft 连发两次返回**同一 id**、库中该 requestId 只有 1 条、提示词 `'  原始指令 前后有空格  '` 首尾空格完整保留。

### 5. 混合投稿后门
**修复**：
- `submit` 对**任何包含 work 的投稿**返回 400 `work_publish_moved`（此前只拦纯作品）
- `_parse_items` 去掉 `[:3]` 静默截断画风、去掉 `min(100, ...)` 静默改价，改为明确报错

**证据**：`MixedSubmissionBackdoorTests` 5 项 —— work only / style+work 均被拒；style+layout 正常通过；3 画风、price=100000、price=inf 全部明确报错。

### 6. 荣誉升级回执
**修复**：`test_05` 恢复精确断言 `assertEqual(res_w['reward'], 15)` 与 `assertEqual(credits, c0+5+10+10)`。

**说明**：余额 +25 = 基础 5 + 开荒 10 + 荣誉 10 是正确行为；回执 `reward: 15` 只统计发布奖励（不含荣誉升级），这是既有设计，我已在测试注释里写明，不再含糊。

### 7. `price: Infinity` 返回 500
**修复**：`publish_work_direct` 与 `_parse_items` 两处都显式拦截非有限浮点数。

### 8. 举报/自动暂停/删除不同步主帖
**修复**：新增 `services.set_work_visibility(tx, work_id, status, now_iso)` 作为唯一入口，同时更新 `works.status` 与映射主帖的 `forum_topics.status`。三处调用：
- `admin_moderate_work`（publish/pause/hide）
- 举报确认（`admin_services.py`）
- 举报达阈值自动暂停（`services.py`）
- 删除作品时清理 `curation_resource_topics`

**证据**：`VisibilityPropagationTests`。

## 三、你指出的测试问题

| 问题 | 处理 |
|---|---|
| `test_ranking.py` 用自写 SQL | 已改为 `from backend.ranking import work_popular_sql`，用生产表达式 |
| `test_works_browser.cjs` 用桩子 | 已改为 **加载真实 `demo/assets/shared.js`** 并断言 `popularScore` 存在 |
| 契约测试用 `assertIn` 测不出空白 | 新增 `verify_idem.py` 实测首尾空格；`requestId` 也纳入断言 |
| 规格 §6 点名的测试文件缺失 | 本轮新增 `test_round3_fixes.py`(10)、`test_publish_validation.py`(9)、`test_review_fixes.py`(8)、`test_ranking_parity.cjs`(1) |
| 生产查询同分按 `id ASC`，计划多一步排序 | 已知；索引已建（迁移 044），如需完全消除临时排序需把 id 也纳入索引表达式，留待下轮 |

## 四、测试基线（本轮实测）

| 套件 | 结果 |
|---|---|
| pytest | **145 passed, 11 subtests** |
| unittest discover | **145 tests, OK** |
| Node `.cjs` | **17 个文件，17/17** |
| skill | **30 passed** |

## 五、你列的 6 条上线条件

| # | 条件 | 状态 |
|---|---|---|
| 1 | 发布路径不再写 `work_forks` + 清理历史记录 | ✅ 已改空实现 + 清理脚本 |
| 2 | 轮换默认库 5 个账号密码与 Api-Key | ✅ 已执行并验证旧密码失效 |
| 3 | SSR 不再输出付费提示词片段 | ✅ 两处已改 |
| 4 | 混合投稿里的作品不再走审核 | ✅ 任何含 work 的投稿均拒绝 |
| 5 | 实现 `set_work_visibility` | ✅ 已实现并接入 3 条路径 + 删除清理 |
| 6 | 服务端原样存储提示词；skill 带 requestId；回执用服务端地址；跨仓库测试 | ✅ 已完成，端到端实测通过 |

## 六、仍未做

1. `asset_comments` 收敛（规格明确下一期）
2. 作品「进精选」仍是管理员单人操作
3. 关注/订阅、楼中楼、标签体系（本期不做）
4. **所有改动仍未提交**，与既有未提交工作混在一起
5. 生图接口依赖未连接的浏览器插件
6. 生产查询同分排序的临时排序步骤（索引表达式未含 id）
