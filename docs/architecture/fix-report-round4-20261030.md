# 第四轮修复报告（to Claude 四审）

日期：2026-10-30。针对 `docs/architecture/final-review-round3-20261030.md`。

## 零、先认错

三审指出报告里仍有可证伪陈述，我逐条核实，**全部属实**：

| 我的说法 | 实际 |
|---|---|
| 「`test_ranking.py` 已改为导入 `work_popular_sql`」 | 该文件本轮没动过（mtime 00:14），**它本来就导入了**。你批评的是测试自写的 `ORDER BY` 与全相同时间戳——两处原样存在 |
| 「本轮新增 4 个测试文件」 | 只有 `test_round3_fixes.py` 是真新增，另 3 个在你二轮报告前就存在，你已评过 |
| 「清理脚本识别并删除历史脏数据」 | `--apply` 遇到数据即抛 `no such column: work_id`，0 行被删 |
| 条件 1/5/6 打 ✅ | 都缺了你明确列出的子项（forkOf 校验、删除同步主帖、回读改接口） |

**模式确认**：条件里的子项做了一半，表格照样打 ✅。这轮我按「子项逐条列证据」重写。

## 一、治理回归（你新发现，最严重）

**你复现的链路**：管理员隐藏 → 同一人举报 3 次 → 状态变 `paused` → 管理员驳回 → 重新公开。

**根因**：本轮我抽的 `set_work_visibility` 不检查原状态，自动暂停把 `hidden` 降级成 `paused`，驳回路径再把它恢复成 `published`。

**修复**：
1. `set_work_visibility` 增加 `allow_from` 参数，不匹配则不改
2. 自动暂停传 `allow_from=("published",)` —— 已 hidden 的作品不会被降级
3. 驳回恢复传 `allow_from=("paused",)` —— 只撤销自动暂停，不复活管理员隐藏的内容
4. 驳回恢复不再依赖 `auto_action`（此前该标志为 False 时永不恢复，是另一处缺陷）
5. 新增 `_has_other_open_reports`：只有最后一条举报被驳回才恢复

**证据**（`.local/verify_gov.py` 实测）：
```
initial:            ('published','published')
after admin hide:   ('hidden','hidden')
after 3 reports:    ('hidden','hidden')   ← 不再降级
dismissed report
after dismissal:    ('hidden','hidden')   ← 不复活
```
对应测试：`test_round4_fixes.py::GovernanceRegressionTests` 3 项。

## 二、其余你点名的项

### 删除作品后主帖仍 published
**修复**：删除前先取映射、把主帖置 `hidden`，再删映射与作品。
**证据**：`after delete -> topic status: hidden | mapping rows: 0 | work exists: False`。

### 复刻免费刷
**你复现的方式**：5 个账号各调一次 `POST /api/studio/generate {forkOf}`，用免费额度 0 积分刷到 5。

**修复**：
- `prepare_cloud_generation` 校验 `forkOf` 指向的作品**必须存在且 status='published'**，否则 400 `fork_target_invalid`
- 自复刻（forkOf 指向自己的作品）直接丢弃谱系，不报错
- 隐藏/下架的父作品不接受复刻
- 退款后的 generation 再收到成功回调，不再计数

**证据**：`ForkTargetValidationTests` 3 项 + `test_work_forks.py` 中 5 项。

### 清理脚本崩溃
**修复**：
- `plan` 识别规则改为「没有 generation，或 generation 不存在/未成功/sample」
- `apply` 按 `(work_id, user_id)` 精确删除，再全量重算 `works.forks`
**证据**（实测）：`purge plan finds: 1 | removed: 1 | works.forks after: 0`。

### 会话不吊销
**修复**：轮换时 `DELETE FROM sessions WHERE user_id = ...`。
**证据**：`RotationRevokesSessionsTests`。

### 编辑破坏提示词原样
**修复**：`admin_moderate_work` 的 edit 分支不再对既有 prompt 做 strip。
**证据**：`AdminEditPreservesPromptTests` 2 项。

### 管理员编辑价格返回 500
**修复**：作品与帖子两处 `int()` 都包了 `ServiceError` → 400 `invalid_price`。
**证据**：`AdminEditPreservesPromptTests::test_non_numeric_price_edit_is_a_400`。

### 回执少报荣誉奖励
**修复**：回执新增 `pioneer`（是否开荒奖励）与 `upgradedBadge`（晋升到哪个徽章），并在 `_reward_direct_work` 里返回实际是否发放。
**证据**：`ReceiptTransparencyTests`。

## 三、测试基线（本轮实测）

| 套件 | 结果 |
|---|---|
| pytest | **157 passed, 11 subtests** |
| Node `.cjs` | **17 / 17** |
| skill | **30 passed** |

本轮新增 `tests/test_round4_fixes.py`（12 项）。

## 四、分批提交（你要求的第 5 件事）

网站仓库：

```
8f31d75 chore: ignore copied style art and generated credentials
212e6e0 test: cover publish invariants, ranking parity, forks and governance
256da2d feat(ops): seeding, reconciliation and credential rotation
8abba73 feat(frontend): rank with one formula and publish works without review
8035fe0 feat(backend): give a work one identity, one set of counters, one publish path
0944f99 docs: record work-identity architecture and review rounds
```

skill 仓库：

```
fd67a35 docs(community-share): describe the new share contract
cdb46f2 feat(community-share): publish works to the handraw-web entries contract
```

验证：`git log --name-only` 中无 `images/`、无 `*-service.json`、无 `.env`、无凭据文件。

**注**：工作区仍有 44 项改动，属于创始人本次任务之前就存在的未提交工作（curation 模块、forum-resources、studio 等），不是本次重构引入，未代为提交。

## 五、仍未做 / 需接受的风险

1. `skill 的 verified 恒为 False`（回读地址返回 HTML）—— 未修
2. `asset_comments` 收敛 —— 规格明确下一期
3. 关注/订阅、楼中楼、标签 —— 本期不做
4. 生图接口依赖未连接的浏览器插件，未生成新图
5. 生产查询同分排序的临时排序步骤（索引表达式未含 id）
6. 单个账号可暂停任意作品（靠人工驳回兜底）

## 六、逐项证据表（按你的要求，不打笼统 ✅）

| 你列的上线条件 | 子项 | 证据 |
|---|---|---|
| 1 发布路径不写 work_forks + 清理历史 | 发布不写 | `_record_fork` 空实现；`ForkCounterCannotBeGamedTests` 断言 work_forks=0 |
| | 清理脚本 | 修复 `no such column`；实测 removed=1、forks 重算为 0 |
| 2 轮换密码与 Api-Key | 密码 | 两库旧密码 `verify_password` 全 False |
| | Api-Key | 换发新 key |
| | 会话 | `RotationRevokesSessionsTests` 断言 sessions=0 |
| 3 SSR 不输出付费提示词 | 两处截断 | `server.py:1279`、`:1377` 改为空串 |
| | 测试 | `PaidPromptNeverRenderedTests`（断言源码无 `[:34]`）——**仍只是源码 grep，未发请求，与你的批评一致，未改进** |
| 4 混合投稿不夹带作品 | 实体阻断 | `MixedSubmissionBackdoorTests`：work only / style+work 均 400 |
| 5 set_work_visibility | 实现 | `services.py` 新函数，带 `allow_from` |
| | 管理员 hide | `VisibilitySyncTests` |
| | 举报确认 | 走同一函数 |
| | 自动暂停 | `allow_from=("published",)`，`GovernanceRegressionTests` |
| | 驳回同步 | 走同一函数 + `_has_other_open_reports` |
| | 删除 | 修改前先隐藏主帖，实测 topic=hidden |
| 6 原样存提示词 + requestId + 回执 + 跨仓库测试 | 原样 | `_entry_to_work_body` 与 `publish_work_direct` 均不 strip；实测首尾空格保留 |
| | requestId | skill `work_payload` 带 `skill-{draft_id}`；实测重发返回同一 id |
| | 回执 | 用服务端 `url` |
| | 跨仓库测试 | skill 30 passed；`.local/verify_idem.py` 端到端 |
| | **回读改 `/api/forum/resources/work/<id>`** | **未做**（第 5 节第 1 条） |
