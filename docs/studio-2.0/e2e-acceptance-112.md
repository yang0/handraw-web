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

## 8. 追加实测：M0 权限负向与 M3 原生 Studio 100 节点（#112 第二轮）

针对第一轮仍然没有覆盖的真实业务壳，新增**本地受控、可重复**的两类 CI 测试。两项均不使用付费 AI 接口、不读取任何真实用户文章或私有图片，不能取代 D 级生产准入。

1. `tests/test_studio_security_negative_112.py`：通过真实 HTTP Handler、两个独立账号与匿名调用，验证私有 ArticleDocument、其 PlanSlot 锚点、Project GET/PATCH/COPY、V3 Run 所属权限；越权响应不返回私有正文标记、项目标题、正文 ID 或 CAS revision；模拟 Alice/Bob 私有图库的 MediaRef 交叉引用，创建草稿被 403 拒绝，成功项目 revision 不变；失败操作不得留下额外项目记录。
2. `tests/smoke_studio_native_100_graph_112.py`：把 **100 个实际 Studio 节点类型（文本参数、画风参数、图片参数、生成设置、成图展示）+ 50 条 Graph 连线**，作为真实账户的云端 Project 经后端 API 保存，再用真实 Chromium 登录并通过 `?project=` 进入完整 Studio 画布；验证 40 张本仓库 WebP 图在 Canvas 原生节点成功解码、100 个 node ID 唯一、owner 项目与图片 DOM 身份、选中与连续缩放不丢图或丢卡，且未触发任何收费 `/api/studio/generate`；保留首屏实测耗时、缩放耗时、节点 DOM 数量、浏览器版本和截图到 `artifacts/studio-112-100-node/`。

**证据边界说明：** 本项相比 #127 的合成 Canvas DOM，更进一步运行了真实 Studio 业务渲染器、原生 Graph、Project API 与本地真实 WebP 解码。但图像仍是仓库测试样本，Graph 是受控构造的业务形态，不是实际客户作品，更没有生产图像尺寸分布/网络抖动/收费任务。首屏耗时仅记录为 CI Runner 的观察值，不设置未经真实硬件校准的性能 SLA。真实业务/生产 100 节点、跨设备弱网、隐私日志/URL 和外部供应商计费仍为 **PENDING / NO-GO**。

CI 新增以上 Python HTTP 套件与真实 Chromium 冒烟（`interaction-journey-regression`），验收矩阵在 `M0-05`、`M3-03` 中引用；`ops/check_studio_acceptance_112.py` 检查其不会脱离 CI。**本节只描述新增测试及预期断言；PASS 必须以最终同 SHA 的 GitHub Actions Job 日志为准**。


## 9. 第三轮：真实 PG17 + S3 协议模拟 · Web↔Skill 六图上传中断恢复

本轮在 #91/#93/#114 P0 工程收口后的 `studio2@5de44a778beca4d4f05d1012138550df518591ec` 创建独立分支 `studio2-issue112-real-integrations-round3`，新增 `tests/test_studio_skill_pg_s3_112.py` 并将其纳入 **原有 14 个 Job 中的 `production-storage-integration`**，以及 M2-04 矩阵。该测试不使用付费图像模型，不上传任何用户数据。

- **真实组件**：PostgreSQL 17 原生临时数据库、真实 Handraw HTTP 服务和 API Token、服务端 V3 Run/Media/Work/Grant 逻辑、boto3 S3 API、真实 PNG 字节。S3 由 Moto 在 CI 进程内模拟，不是 MinIO/R2/AWS 的真实部署。
- **真实流程**：两个独立用户、6 张不同 PNG、Skill `POST /api/v1/me/generations`；注入第 4 张上传失败，前三张 RunItem 已持久化但没有 Work，也没有匿名公共图片授权。原始同 requestId/ExternalRunId/内容重放，只补充剩余 3 张；Run 唯一、Work 唯一、6 个 WorkMedia 及有效授权、首图封面；再次重放不重复上传或更换已成功媒体。
- **对象与权限**：删除本地上传文件以模拟另一实例空缓存；通过匿名公开 Work 媒体 URL 从模拟 S3 恢复原始字节；隐藏 Work 后匿名和其他用户必须 404，且权限拒绝发生在任何对象存储回源之前。作者仍有对应私有历史，但 Work 的公共可见性被撤销。
- **原有局限**：这不是 Skill 仓库发布客户端的真实网络请求，也没有真实 MinIO/S3/R2、CDN、多副本故障/权限配置和真实计费结算。M2-04 的 `live_gate` 仍为 **PENDING**，全站上线判定仍是 **NO-GO**。测试输出的 PASS 只表示本行受控 CI 通过；实际是否通过以最终同一提交 SHA 的 GitHub Actions Log 为准。

后续真实门禁仍需：跨仓库 Skill 客户端从另一进程/主机上传、真实 S3 或 R2 凭证与私有桶配置、断网/对象存储异常和跨实例访问、删除后 GC/退款/生产账本对照；未经独立人工复核不得将 D 级升级为 EVIDENCED。


## 10. 第四轮：真实独立 Skill 客户端 × Web HTTP × PG17 × S3 协议模拟（#84 / #112）

前一轮 #112 的六图中断恢复测试主要由 Web 测试进程自己组装 Skill HTTP payload，证明了**服务端**续传、事务和对象权限，不能冒充「已运行真实 Skill 客户端」。本轮保留它作为服务器故障恢复用例，**额外直接加载并调用**来自 `yang0/handraw-style` 的实际 `skills/handraw-cloud/scripts/handraw_cloud.py` 命令入口（`history record` / `history upload`）；不再用模拟 Skill 的 HTTP 发送器代替真实客户端。

- **双仓代码绑定**：Web `.github/workflows/checks.yml` 在原有 `production-storage-integration` Job 内，使用公开仓库 `yang0/handraw-style` 的固定完整提交 `9542512c8fd49cd8a5bbc02b9378b82b6e6e9c24`，checkout 后通过 `git rev-parse HEAD` 校验精确 SHA；拒绝浮动分支拉取。原有 CI Job 数仍保持 14。Skill 自身在 `feature/skill-web-unification-v1-20261107` 上补齐 GIF 后通过独立仓库 CI；不修改 Skill 主干。
- **真实执行**：通过真实客户端 CLI 保存本地历史时阻断任何 API 调用，确认 `cloudState=local_only` 且数据库 Run 数不变；创建真实 1 张 PNG、5 张 PNG、1 张两帧动画 GIF，分别明确执行上传并再上传一次；检查一个 logical Run 对应至多一件 Work、N 个有序 Media、稳定首图封面、授予 N 个公开 Grant、服务器 byte-for-byte 原始媒体读取及作者私有历史可见性。上传 GIF 的扩展名与 `image/gif` MIME 沿用 Skill 真实客户端，Web 按帧数/像素上限严格验证。
- **负向保护**：伪造错误格式 GIF 经真实 Skill `record` 本地保存后执行 `upload`，服务端应以 HTTP 400 拒绝，Skill 不能错误地把本地记录设为 synced。读历史 API 在 publish-only Token 下应拒绝（403），public 才能获得已发布媒体。
- **执行范围**：真实 Skill 客户端实现、真实 Web HTTP、真实临时 PostgreSQL 17、真实 PNG/GIF 字节；对象层仍用 **Moto S3 API 模拟**，本机环回地址注入进客户端（替代正式 handraw-style.com）；不访问付费生图，不使用真实云端账号/令牌或用户数据。阶段证据为 **C 级受控跨仓验证**，不是生产网络、第三方收费网关或真实 R2/S3/MinIO。
- **审计依据**：`tests/test_studio_skill_pg_s3_112.py::test_z_actual_skill_cli_record_upload_retry_across_http_pg_and_s3`，GitHub Actions 的 `#84/#112 real Skill CLI -> local HTTP -> PG17 + S3 emulation` 步骤；本轮独立验证分支 [Actions #42511614919](https://github.com/yang0/handraw-web/actions/runs/42511614919) 已实际 14/14 SUCCESS（此后如更改文档，仍以最终同 SHA 的 CI 为准）。

**依然阻断生产发布的 D 级事项**：远程机器上运行实际 Skill 安装包指向正式部署地址；R2/MinIO/AWS 真实桶私有权限、跨实例和 CDN 缓存吊销、网络中断与对象垃圾回收；真实网关计费/退款/重复回调，正式 PG 迁移备份和恢复、Redis 故障演练、账号/媒体 IDOR 与日志脱敏，Firefox/WebKit/触屏与弱网。**#84、#112 均保持 OPEN，发布 NO-GO；PR #131 必须保持 Draft。**


## 11. 第五轮：积分扣费零暗扣账本 + PostgreSQL 17 备份/恢复/回滚（#112）

本轮不重新实现已有 `apply_wallet_delta`、`studio_quota_reservations` 或网关的 408/502 未知状态处理，而是追加**可重复的账本级核验**与缺失的真实 PG 物理恢复演练。所有变更在独立 `studio2-issue112-billing-pg-restore-20261109` 上验证，`main` 禁止改动，PR #131 保持 Draft。

### 11.1 严格零暗扣（Web 真正积分/免费额度 + 受控 Mock 图像任务供应商）

- `tests/test_studio_billing_112.py`：真实数据库事务及 Web HTTP，强制耗尽当日免费额度以走**真实积分扣款**路径；验证 idempotencyKey / requestId 重放、唯一扣费流水 `gen_spend_<genId>`、upstream submit claim 一次、429 已有在途任务不产生新扣款、网关未知超时 / 502 不可盲目退款、供应商确认取消或失败后精确释放一次 `gen_refund_<genId>`、迟到成功回调不能把退款任务复活为作品或再次消耗额度。
- 每条测试按交易链逐项核对：`wallet.balance = 初始余额 + SUM(本任务 studio_gen/studio_refund ledger.delta)`；各事件 `event_key` 唯一；每一流水的 `balance_after` 与交易序列一致；重复回调不改变既有成图、费用或任务。异常、跨账号调用不触发暗扣。
- 修复 `backend/services.py::complete_cloud_generation` 的状态保护：当记录不存在、已 `refunded` 或已 `success` 时，任何迟到、重复 callback 都在数据库事务内**立即返回**，不能重写成功媒体、篡改 taskId、把 refund 后 quota 标记 `consumed`、重复生成作品/统计。
- 保留现有 `tests/test_gen_timeout_refund.py` 的真实 HTTP 408/502/Timeout 和 Reconciler 路径；新版进一步核对**积分**而非仅免费 quota。Mock 测试不会调用用户付费供应商，不能证明真实商业支付网关或实际模型消费账单已核实。

### 11.2 真实 PostgreSQL 17 物理备份、恢复与回滚

- 脚本：`ops/pg_release_restore_drill_112.py`。使用 PG17 `pg_dump --format=custom` 生成 **0600 私有备份**；执行 `pg_restore --exit-on-error` 到**预先创建且无业务表**的两个 `handraw_restore_drill_*` 隔离数据库。原库始终只读，**从不清空、删除、覆盖原数据库**。
- 严格参数门禁：`HANDRAW_ALLOW_PG_RESTORE_DRILL=YES`；source / primary restore / rollback 三个明确、各不相同的 DSN；拒绝系统数据库、query dbname/host 覆盖、跨实例、非预留前缀、非空目标和已存在归档。
- 通过只读 `REPEATABLE READ` 快照，为 schema_migrations、users、wallets、ledgers、generation_runs/items、media_assets、work_media、works、studio_generations、studio_projects/requests 逐行计算 SHA256（**仅输出数量与哈希，不输出用户字段或密码**）；比对源库、恢复库、回滚副本全部一致。额外在恢复副本注入事务型 DDL 失败，验证 PostgreSQL 原子回滚，再从同一归档恢复另一空数据库实现备份级回退验证。
- `tests/test_pg_backup_restore_112.py` 实际对 CI PostgreSQL 17 服务创建随机独立三库、引导真实 V3 Schema、写入一名测试用户和配平的 studio_gen/studio_refund 流水，通过容器自带 PG17 `pg_dump/pg_restore` 完成物理恢复；结束自动删除**仅由测试创建**的三个临时库。不会访问付费模型，不使用生产用户数据。
- `.github/workflows/checks.yml` 将真正账本测试纳入 `v3-core-regression`，真实 PG17 恢复测试纳入现有 `production-storage-integration`，**保持原 14 个 Job**。CI 仅上传脱敏 `artifacts/studio-112-pg-backup-report.json` 审计报告，**绝不上传含用户数据的数据库备份本体**。

可在人工维护的隔离/预发布 PG 环境复用以下安全操作（必须先由操作员创建两个**空**的、命名合规的恢复库，并确认仅具备授权凭证；不要指向正在提供服务的恢复目标）：

```bash
export HANDRAW_ALLOW_PG_RESTORE_DRILL=YES
export HANDRAW_PG_DRILL_SOURCE_URL='postgresql://USER:PASS@HOST/staging_source'
export HANDRAW_PG_DRILL_RESTORE_URL='postgresql://USER:PASS@HOST/handraw_restore_drill_verify'
export HANDRAW_PG_DRILL_ROLLBACK_URL='postgresql://USER:PASS@HOST/handraw_restore_drill_rollback'
python -m ops.pg_release_restore_drill_112 \
  --archive /private/handraw-pg112-snapshot.dump \
  --report /private/handraw-pg112-audit.json
```

### 11.3 证据等级与剩余发布阻断

本轮 PostgreSQL 17 是 CI 中**真实数据库 + 原生 pg_dump/pg_restore**，有真正的二次恢复和 SHA 对账；但源库数据为人工构造的测试数据（含测试用户及模拟积分），不是生产大小/负载/权限与真实时间窗。测试使用的 S3 仍是 Moto；计费端是可控 Mock 图像网关并非真实商业支付通道。因此本轮证据为 **C 级受控真实组件验收**，不能冒充 D 级生产验收、声称已有正式备份 RTO/RPO 或付款成功。

后续必须完成：真实图像供应商的费用/回调/退款/取消逐单核算；正式生产类数据库快照与实际部署步骤下的备份/恢复测时和回滚切流；R2/S3/MinIO、Redis 多实例及私有媒体 ACL、物理移动端/弱网、双账号 IDOR 与密钥日志审计、灰度及发布负责人签核。**#112 保持 Open、全站生产 NO-GO、PR #131 始终 Draft，不允许合入 main。**
