# Studio 2.0 · Issue #112 · M0–M3 受控验收与发布门槛对账

> 仓库：[`yang0/handraw-web`](https://github.com/yang0/handraw-web)  
> 基线：`studio2@0d54811a6c815e9646ab5f6bf3a88ad32890a3e0`  
> 验证分支：`studio2-issue112-ci` → CI 全绿后非强制快进 `studio2`  
> 上级：[Epic #101](https://github.com/yang0/handraw-web/issues/101) · 受控 QA：[Issue #112](https://github.com/yang0/handraw-web/issues/112) · [Draft PR #131](https://github.com/yang0/handraw-web/pull/131)

## 0. 结论与证据边界

**发布决策：NO-GO（真实生产门禁尚未通过）。** 本报告的目标是把已有工程/离线浏览器证据固定为可复验的验收矩阵，并使未来变更无法在 CI 中静默删减核心用例；**不是**声称已执行实际收费图像模型、生产账本、S3/R2、跨设备和多实例验收。

证据分级：
- **A｜CI 契约/单测**：Node、Python、HTTP/SQLite、Mock。证明指定边界的确定性行为；不证明实际供应商的退款和收费事实。
- **B｜真实 Chromium + 本地服务**：登录态、UI/交互、CAS/断网/刷新、图卡/预览、固定媒体和确定性 AI 提案。是真实浏览器，但不是付费生图网关。
- **C｜CI PG17 + Redis7 服务**：在临时环境执行 `production-storage-integration`；不等同正式生产迁移/备份/恢复与跨实例对象存储测试。
- **D｜部署/实网关/真实计费/跨设备**：尚未提供完整可审计的运行证据，必须保留 **PENDING**；不能被 A/B/C 自动替代。

机器可读权威矩阵：[`acceptance-matrix-112.json`](acceptance-matrix-112.json)。`python ops/check_studio_acceptance_112.py --output artifacts/studio-112-matrix.json` 检查用例文件存在、与 Checks 的执行线路映射、14 项 Job 结构和每条场景的实环境门禁声明。输出中的 **matrix_contract=PASS 仅为“测试关联与防漏接线”通过**；不代表每个测试已执行成功，更不代表 D 通过。真实执行结果须读取 **同一 commit** 的 Actions 运行及其每个 Job / Step。

历史已验证基线：[`0d54811a` Push](https://github.com/yang0/handraw-web/actions/runs/42482310978) / [PR](https://github.com/yang0/handraw-web/actions/runs/42482315077)，各 14/14 success。#112 新提交的验证分支、`studio2` Push 和 PR 运行 URL 应在完成后回写 [Issue #112](https://github.com/yang0/handraw-web/issues/112)；不得在 CI 完成之前填写“通过”。

## 1. M0 · 基线、资源与历史缺陷

| 矩阵 ID | 验收事实 | 自动化依据（A/B） | D 级待验证 |
| --- | --- | --- | --- |
| M0-01 | 同一 V3 Run 至多 1 件 Work，乱序/重复媒体回调不重复插入 | `test_generation_v3.py`, `test_studio_series_run_contract.py` | 实际供应商账本与迟到 webhook 对账 |
| M0-02 | #95/#105 选择器点击/键盘/锁定/回显，四入口统一 | `test_studio_picker_interactions.cjs`, `smoke_studio_picker_browser_105.py` | 部署环境触屏、浏览器兼容和私有图库 |
| M0-03 | #96 僵尸 Busy 不锁死，已提交任务不伪称撤销 | `test_quick_stale_generation.cjs`, `smoke_studio_runtime_browser_119.py` | 实网关取消和突然断电 |
| M0-04 | #88/#90 AI 非 JSON/错误分类与合法推荐 | `test_studio_ai_plan.py`, `test_studio_ai_plan_http.py` | 真实模型响应质量、429/502 回包 |
| M0-05 | 私有媒体授权与资源类型/版本约束 | `test_studio_resource_refs.py`, `test_v3_media_visibility.py` | 实环境跨账号 IDOR/隐藏提示词/日志审计 |

M0 通过条件：上述自动化对指定 SHA 可复现；每条 `D` 风险已具名登记，历史 Issue 不因为“已有代码”被重复开发，也不因为“绿 CI”假定付费网关已通过。

## 2. M1 · 单图、状态、Picker、保存

| 矩阵 ID | 验收事实 | 自动化依据 | D 级待验证 |
| --- | --- | --- | --- |
| M1-01 | 单图主题/资源/参考素材→生成状态→版本/复刻 | `smoke_studio_make_image_browser_128.py`, `test_studio_quick_run_contract.py` | 真实图像费用、媒体上传及下载 |
| M1-02 | Run 可查询，重试/取消只操作合法 slot；请求幂等 | `test_studio_runtime_http_119.py`, `test_studio_cancel_pending.py` | 实际 attempt/退款/迟到异步回调 |
| M1-03 | #103 双标签 409/CAS、离线 Outbox、刷新、账号隔离 | `smoke_studio_project_reliability_103.py`, `test_studio_project_http.py` | 跨设备、跨实例与生产 DB 故障注入 |
| M1-04 | #105 四入口共享授权资源 Picker | `smoke_studio_picker_browser_105.py`, `test_studio_article_picker_105.cjs` | 生产私有图 ACL/实体触屏 |

禁止把客户端 `AbortController` 视为已经取消上游收费请求；未收到服务端确认的 `RunItem` 仍待定，刷新后应可核对；成功图片不得因取消、撤销编辑或页面重绘消失。

## 3. M2 · 六图系列、乱序并发、单 Work/多媒体

| 矩阵 ID | 验收事实 | 自动化依据 | D 级待验证 |
| --- | --- | --- | --- |
| M2-01 | 六个稳定 `PlanSlot` 的逐图编辑/排序/覆盖 | `smoke_studio_series_browser_108.py`, `test_studio_series_plan_integration.cjs` | 真实六图结果、逐图下载与 ZIP |
| M2-02 | 3 成功/2 失败/1 在途，乱序回显；单作品 | `test_studio_runtime_119.py`, `test_studio_series_run_contract.py` | 真实 webhook、逐项账本、部分成功结算 |
| M2-03 | 停止未提交任务、失败重试、DAG 共享容量/429 退避 | `test_batch_stop.cjs`, `test_studio_dag_scheduler_120.cjs`, `smoke_studio_dag_browser_120.py` | 网关真实限流/熔断/退款 |
| M2-04 | V3 作品广场一张卡、媒体顺序与 Skill 桥接合同 | `test_generation_v3.py`, `test_stage5_plaza_batch_folding.py`, `test_skill_web_bridge.py` | Web ↔ Skill 真实断点上传、对象存储 |

核心不变量：**逻辑 Run → 最多 1 Work → N 个 WorkMedia**；请求重播不得重复扣费/重复作品，但用户主动再次生成是新的可计费事实；失败 slot 的重试不覆盖成功 slot。**模拟数据库不等于真实供应商账本已经核实。**

## 4. M3 · 文章、复杂画布和性能

| 矩阵 ID | 验收事实 | 自动化依据 | D 级待验证 |
| --- | --- | --- | --- |
| M3-01 | 文章导入直覆编辑器、锚点/正文 CAS、失败单图重试、ZIP | `smoke_studio_article_browser_109.py`, `test_studio_article_project_109.cjs` | 真实附件格式、弱网、大稿与付费图像 |
| M3-02 | 复杂 Graph 进入简洁视图只读/部分编辑、无丢边 | `test_studio_view_authority.cjs`, `smoke_studio_canvas_browser.py` | 跨设备复杂项目运行中切视图 |
| M3-03 | 100 节点输入焦点、图像 DOM 复用和性能基线 | `benchmark_studio_canvas.py`, `test_studio_canvas_incremental.cjs` | 真实 100 节点业务模板/多张大图/低端机器 |
| M3-04 | 文章正文和私有资源不进入公共作品 | `test_studio_article_http_e2e.py`, `test_studio_resource_refs.py` | 生产外部浏览器与日志链路审计 |

#127 文档 [`canvas-127-baseline.md`](canvas-127-baseline.md) 提供合成 DOM 的 10/50/100/300 节点基线；**不对真实 300 节点画布做性能承诺**。对真实 100 节点 Graph 应另测输入焦点/图片重载/CPU/内存/帧耗时并记录机器与浏览器信息。

## 5. 正式环境与安全验收（阻断 Go 的统一依赖）

- [ ] 真正的计费网关：成功、429/502/超时、取消、重复回调、部分成功、重试 attempt、费用结算与退款逐项对账；记录 `requestId / runId / itemId / slotKey`，不得记录密钥、原始隐藏提示词或私有媒体字节。
- [ ] 两个独立账号实际验收 IDOR：Project API、Run/Item、MediaRef、Article 正文、私有图库、作品详情、历史与下载 URL；隐藏定义/敏感 `system` 配方不得进入公共响应、浏览器网络包和服务端非受限日志。
- [ ] PostgreSQL 迁移 101：生产类副本真实备份、dry-run、显式 apply、版本校验、恢复/回滚演练，记录恢复时间及任何兼容性缺口。不得在真实数据上未经备份操作。
- [ ] Redis、对象存储（S3/R2/MinIO）与跨实例：并发、持久化、访问鉴权、回调乱序、补偿/重试、故障恢复、对象清理。CI 的 PG/Redis 服务测试只是 C 级证据。
- [ ] Web/Skill 跨仓库：生成 N 图→同一 Run/Work→上传中断→重放只补缺失媒体→公众一张封面卡、详情 N 图→切换封面/审核/删除后不被迟到回包逆转。
- [ ] 浏览器矩阵：Chromium/Firefox/WebKit 或目标平台等效验证，1440px、390px、实体触屏与键盘；真实文章导入与 100 节点大图、弱网切换。
- [ ] 灰度/回滚：新入口开关或部署回退方案、数据库向前兼容性、完整数据保护与发布监控；至少一次备份恢复和回退演练。

建议统一日志字段：`projectId`, `workflowVersion`, `runId`, `itemId`, `requestId`, `slotKey`, `errorCode`。所有外部错误回包应有安全的问题编号；日志审查需保证禁止写入密钥、受保护的资源定义/提示词、私人正文和媒体内容。

## 6. CI 复验与证据提交方法

```bash
# 安全的接线检查，不会访问收费 AI 网关
python ops/check_studio_acceptance_112.py --output artifacts/studio-112-matrix.json

# 本地定向测试示例；正式结果以 GitHub Actions 同一 SHA 为准
python -m unittest discover -s tests -p 'test_studio_runtime_http_119.py' -v
node tests/test_studio_dag_scheduler_120.cjs
python tests/smoke_studio_project_reliability_103.py
python tests/smoke_studio_series_browser_108.py
python tests/smoke_studio_article_browser_109.py
python tests/benchmark_studio_canvas.py --require-browser --output artifacts/canvas-127.json
```

发布候选须满足 **14/14 同一 SHA 的 Checks Job SUCCESS**（包括六个 Python 分片与聚合门禁），且 Chromium 实际测试运行步骤成功、Artifact 非空。若 GitHub Runner、浏览器安装或预算导致任务未运行，必须标为 **BLOCKED**，不得按 PASS 处理。Push/PR 运行应分开记录。CI 测试结果是 A/B/C，不代替 D。

每轮 Issue #112 对账应记录：
`commit SHA / 分支 / 测试项目与断言 / Actions Push URL / Actions PR URL / Artifact URL / 是否付费网关 / 是否 PG/Redis/S3 真环境 / 已知风险 / Go-No-Go`。
CI 失败必须区分代码失败、Runner 失败、环境依赖与额度限制，不直接重试掩盖。

## 7. 发布门槛与保护分支

**No-Go**：存在 P0 数据丢失、重复扣费、非法状态推进、无限 Busy、越权/泄密、冻结 Run 被草稿修改、不可追溯的已提交任务或生产回滚路径不可用；任一真实环境阻断项目尚未完成也保持 No-Go。

**Go 候选**：M0–M3 关键 CI/浏览器覆盖通过 + 发布必需 D 级真实联测完成 + 关键安全/计费断言全部通过 + 可执行的备份/回滚 + 发布负责人明确签署。P2 #126 GraphPatch 可延期，但不得在 UI 中假装已提供。

**操作边界**：所有变更先有 Issue #112；先在 `studio2-issue112-ci` 验证。仅当该分支同 SHA 全部 14 项 CI 成功后，才以 `force=false` 和预期旧 HEAD 快进 `studio2`，再核对其 Push/PR CI。**PR #131 始终 Draft，严禁合入 main。** #112 保持 Open，直到全部上线阻断项有可审计证据。
