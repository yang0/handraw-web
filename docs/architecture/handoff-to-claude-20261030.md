# 交接：交给 Claude 完成剩余开发

日期：2026-10-30 10:05。创始人指示：「实在不行你让 Claude 自己把活干完。」

## 你现在是谁

你是这个项目的**开发者兼架构师**。之前的模式是「Claude 出规格 → DeepSeek 实现 → Claude 评审」，经过九轮评审仍未通过。创始人决定改为**你直接动手写代码**。

你有权修改产品代码、提交、跑测试。唯一约束：不修改 `.gitignore` 覆盖的敏感文件，不提交 `/images/`、`*service.json`、`.env*`、`starter_credentials*`。

## 项目现状（实测）

| 环境 | pytest | Node `.cjs` |
|---|---|---|
| 工作区 | 200 passed | 17/17 |
| 干净检出 HEAD | 193 passed, 3 skipped | 12/12 |
| skill (`E:\handraw-style`) | 30 passed | — |

当前 HEAD：`e1873fa`。

## 已完成的核心重构

1. **作品对象统一**：`works.id` 是唯一主键，论坛帖只是讨论载体
2. **作品即时发布**：不再经审核；审核只用于画风/图型进官方目录
3. **排序统一**：`backend/ranking.py` 每类一个公式，前后端一致（有 parity 测试）
4. **复刻谱系**：`work_forks` 事实表，仅真实生成计数，且有防刷（需先有作品 + 每日上限）
5. **skill 契约**：`POST /api/entries`，`requestId` 幂等，回读 `/api/forum/resources/work/<id>`
6. **治理来源**：`status_source` / `status_reason`，驳回只撤销 `report` 来源的改动
7. **统一函数**：`services.set_topic_visibility` 是主帖状态的唯一写入点

## 已知遗留问题（第九轮评审正在验证，结果见 `final-review-round9-*.md`）

按前八轮的遗留清单，仍未修的：

1. **M8**：operator 对已公开作品点「发布」，会公开管理员隐藏的主帖
2. **M7 / M11**：举报/版主操作的边角情况
3. **R2/R4**：作者删帖后作品「隐藏→发布」，主帖被重新公开
4. **M9**：operator 能否覆盖 admin 的 hide —— 需要产品规则，未定
5. **驳回一条举报就清空同目标全部举报** —— 既有设计，未改
6. **一个账号举报 3 次就能暂停任意内容** —— 缺限流
7. **没有统一的防刷方案**（点赞无门槛、注册限流键是 IP+用户名）
8. **退款回调和复刻计数有竞态**，概率低
9. **047 迁移之前的旧数据**，被举报暂停后无法自动恢复，需人工
10. **M-g**：驳回传 `report` 来源这个点，DeepSeek 判断是「冗余防御」（work 层先拦截），需你确认

## 关键约束

- **HEAD 必须自洽**：已提交代码不能依赖未跟踪模块。曾有三次因 `git add tests/` 把依赖未跟踪代码的测试加进去，导致 HEAD 变红。
- **未跟踪的测试文件**（属于创始人之前的工作，不要提交）：
  `test_article_history_persistence.cjs`、`test_article_unified_editor.cjs`、
  `test_product_refresh.cjs`、`test_studio_mode_navigation.cjs`、
  `test_studio_resource_entry.cjs`、`test_cold_start.py`、
  `test_forum_resources.py`、`test_v2_curation.py`、`test_v2_single_backend.py`、
  `test_forum_work_post.cjs`、`test_resource_presentation.cjs`、`test_single_backend_navigation.cjs`
  它们依赖未跟踪的模块（curation 部分、studio、article），不要 `git add tests/` 一把梭。
- **变化测试（变异测试）必须先用 `py_compile` 验证**，否则 collection error 会被误判为「测试抓住了」。
- **不要伪造测试**：断言必须针对真实行为。测试过「只 grep 源码」、「检查永远为真的字符串」两次。

## 建议的完成标准

当你认为可以收尾时，请在报告里给出：

1. `git log --oneline` 的完整提交列表，说明每批的意图
2. 工作区与干净检出 HEAD 的 pytest / Node 数字
3. 变异矩阵：撤销每项关键修复 → 是否有测试失败
4. 浏览器验证：真实打开首页、作品主帖、回执、共创页，确认有内容且无 JS 错误
5. 剩余风险清单（必须列，不要隐瞒）
