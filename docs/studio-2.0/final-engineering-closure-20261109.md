# Studio 2.0 · Phase 12 → 最终工程收口审计（2026-11-09）

> **范围：工程 C 级归档，不是生产 D 级发布批准。** 交付基线为 `studio2@8f195bbe6c7eec83719ee8b9011a332699f460de`，本轮独立分支 `studio2-final-closure-audit-20261109`。**PR #131 始终 Draft，禁止合入 `main`；生产一律 NO-GO。**

## A. 工程准入与证据分级

| 级别 | 判定边界 | 本轮状态 |
| --- | --- | --- |
| C · 本地 + Actions | 可重复单测、真实本地 Chromium、一次性 PostgreSQL17、Redis7、pinned Skill CLI、本地 HTTP、Moto S3 模拟、无支付 API | 按 CI 运行记录逐项核查；基线 Push [#42596994472](https://github.com/yang0/handraw-web/actions/runs/42596994472) 与 PR [#42597002620](https://github.com/yang0/handraw-web/actions/runs/42597002620) 各 14/14 SUCCESS |
| D · 外部/生产等价 | 实际供应商收费账单、物理冷备/异机恢复、真实 R2/S3/CDN、独立跨实例/端设备、官方审核 DB 导出、双人签核 | **全部尚未在本轮证明。硬门禁转交 [#132](https://github.com/yang0/handraw-web/issues/132)，NO-GO** |

工程收口的含义是：已有能力和没有收益的实验都有可复查的证据；不是声称每个历史根因已经唯一归因，更不是将 D 级缺项勾选为成功。以下 5 个 Issue 的旧版“必须等到 D 级才关闭”门槛通过明确的范围分拆转交 #132。若没有完成新分支 14/14 和安全快进，**不得把任何一个 Issue 写为已工程关闭**。

## B. #111 · Canvas 性能因果归档与停止规则

[Phase 12 权威详细原始归纳](canvas-111-phase12-svg-global-coordinate.md)，[Stage 10](canvas-111-tree-style-stage10.md) 与 [Stage 11](canvas-111-style-causality-stage11.md)。Chrome 真实本地页面：300 节点、150 SVG edge、120 独立解码 WebP，真实鼠标和双档 CPU A-B-A-B-A。Phase 12 诊断观察：

| 隔离 | 可见 DOM 更新 | 大型 `UpdateLayoutTree` 次数 | 最大 `elementCount` | 生产可采纳 |
| --- | --- | ---: | ---: | --- |
| 原生 | 节点 style 5 / SVG d 6 / 工具栏 style 5 | 3 | 9,185 | 原样保留 |
| no-edges | SVG d=0 | 3 | 9,185 | 否 |
| no-card | 节点坐标 style=0 | 3 | 9,185 | 否 |
| global-selector-mask | 顶层 class mutation=0；受审规则屏蔽 | 3 | 9,185 | 否 |
| no-visual（联合**仅诊断**） | style/class/d/transform 变更 0 | **1** | **9,185** | **绝对否** |

- no-visual: 1× Style A 中位 255.196ms，B1/B2=42.275/42.521ms；模拟 4× A=1793.064ms，B1/B2=434.512/462.555ms，合计 Style+Layout 与 rAF P95 同时满足实验敏感性门槛；**但剥夺拖拽视觉反馈，`productionCandidate=false`**。
- 单独抑制 SVG / 节点坐标 / 受审状态规则 / 工具栏的方案，都未通过连续双 CPU 稳态收益和完整体验门槛。**一个路径不单独充分诱发全树刷新，不表示所有路径都完全无成本**。
- 残留的 **1 次 ~9,185** 树更新未证明由哪条隐式选择器、伪类、继承或 Chrome 内部追踪机制导致。Chrome `elementCount` 不是 CSS 重匹配节点数，也不是根因证据；Chrome 4× 仅为模拟而非真实低端 GPU/设备。
- 本轮严格禁止修改 `demo/assets/studio-app.js`、`demo/assets/studio-canvas.css`、`demo/assets/studio-canvas-renderer.js` 等生产路径。#111 的“工程诊断已证伪单点假说/归档已知限制”可结束；真实设备差距及性能风险接受转交 #132，不得写成“根因已解决”。

## C. #11 · 官方 Web ↔ Skill 只读对账与审核门禁

- Web 静态官方：**367 style + 170 layout = 537**；实际 Skill main 官方：**369 style + 170 layout = 539**；共同的 537 个编码、类型和展示名相符。
- Skill-only **FF-018 / Low Poly Art**、**FG-025 / Perler Bead Pixel Art** 为未批准候选。指纹与状态见 `ops/official_catalog_pending_11.json`；Web 不反向发布、Skill 原始创作不删除。
- `ops/check_official_catalog_parity.py` 对新增编号、错码、名称不一致、指纹改动、过期豁免 fail-closed；`--strict` 在两候选未完成审批、缺已批准官网 DB 导出时**必须失败**。`tests/test_official_catalog_snapshot_11.py` 将 537/539 与两候选逐一纳入 CI，实际 Skill main checkout 仅做 JSON 数据读取；真实 Skill CLI 单独 pin SHA。
- 正式发布条件：人工逐项审批 + Web DB published-only 只读导出 + Skill 审核合入 + 消除过期 pending manifest + 双仓固定发布 SHA 的静态/动态对账 `--strict` 成功。转交 #132；工程收口**不等于资源完全一致**。与 [Skill #17](https://github.com/yang0/handraw-style/issues/17) 联动。

## D. #84 · V3 Run/Item/Work/Media、跨端上传与权限对账

不重建运行/作品权威表、不保留虚构旧系统回填任务。维持逻辑 `1 Run → 0..1 Work → N successful Media`，私有素材和受保护定义继续不可泄漏。

**此前 C 级已覆盖**：真实 pinned Skill CLI `dad8dad2d2af25bd9df45971a03a499461a723db`，`history record` 离线、`history upload` 在线、1/5 PNG 与多帧 GIF、相同上传重试幂等、6 图第 3 张之后断线/重启服务状态恢复、单 Work、多 WorkMedia、S3 缓存复原、发布前私有、下架旧媒体 404，HTTP → disposable PG17 → Moto S3。

**本轮增量**：
- `ops/audit_v3_cross_client_84_112.py`：只读归一化对账，拒绝两个 owner 复用 Run/Work/Media、错位 `WorkMedia`、重复 slot、成功数不符、所有权不匹配、隐藏媒体仍有公开 grant；只返回统计与 `productionNoGo=true`，无图片/凭据/用户明文。
- `tests/test_v3_cross_client_audit_84_112.py`：模拟 Web 3 成功 / 2 失败（成功槽 0/2/4）、Skill 五图、已下架一图，与多种负向 ACL/归属/重放变化。
- `tests/test_studio_skill_pg_s3_112.py` 增加两个实际 Skill 公开号池用户用**完全相同 externalRunId/requestId**上传 5+5 PNG 的独立 PG/S3 HTTP 路径；逐项核对两个 Work、十媒体所有权、公共 grant、各自私有历史与单方下架不影响另一方。**同名请求键不应跨用户合并**。
- 上述是受控 C 级验收，不是跨主机的真实 Skill/R2/正式账户或生产授权审计。D 级矩阵转交 #132。

## E. #112 · 全链路 QA 与既有受控矩阵

- `docs/studio-2.0/acceptance-matrix-112.json` 含 M0–M3 **17 场景**；`ops/check_studio_acceptance_112.py` 校验测试文件/CI 接线，`.github/workflows/checks.yml` 保持 **14 jobs**（Python 六分片、全量、前端、真实 Chromium、PG17/Redis 和外部 Skill 本地网关模拟）。
- 已有 [E2E 报告](e2e-acceptance-112.md)、[生产 D 级手册](release-d-gates-112-84.md)、[供应商离线对账](provider-statement-reconcile-112.md)、`ops/phase12_release_preflight_112.py`、PG17 逻辑备份恢复与 Media read-only ACL 工具。
- 模拟网关计费/免费额度路径 ≠ 真实供应商账单；PG17 `pg_dump` 逻辑恢复 ≠ 物理冷备；Moto ≠ R2/S3；Playwright 浏览器 ≠ 实体触屏。每项 D 级现场 `testCaseId,deployedSha,skillSha,observedAtUtc,operator,reviewer,evidenceId,status` 未有有效双签时为 BLOCKED，交接 #132。

## F. #101 · Epic / PR #131 工程归档

| 单元 | 已提交的工程范围 | 证据接口 |
| --- | --- | --- |
| 图片创作 | `CreationSpec`、资源 Picker、生成结果/版本与做同款 | #121/#122/#128/#105 |
| 系列创作 | `PlanSlot`、并发/部分失败、方案编辑与任务结果 | #123/#108/#125 |
| 文章配图 | 正文/锚点保真、计划审核/导入、配图导出 | #124/#109/#130 |
| 画布视图 | 原生 Graph、双视图/回退、增量渲染、Undo/Redo、GraphPatch | #107/#129/#127/#126/#111 |
| 共享运行与可靠性 | Project CAS/Outbox、Run 权威、DAG/取消重试、V3 单 Work 权威 | #102/#103/#119/#120/#84 |
| 集成/发布安全 | 17 场景 C 级矩阵、PG/Skill/Moto、目录严格审批阻断、生产预检 | #112/#11/#132 |

PR #131 用途是保留完整未发布的 Studio 2.0 代码审查面，不因 Epic 工程完成就转换 Ready 或向 `main` 合并。

## G. 完成判定 / 回滚纪律

1. 独立分支先运行 **同 Head SHA 的 GitHub Actions Checks 14/14 SUCCESS**；不接受只看上一提交的绿灯。
2. 核实 `studio2` 未并发前进，并且 `compare(studio2...independent)` 为 `ahead>0, behind=0`；使用 `force=false` + `expected_sha` **非强制快进**，严禁覆写其他人的提交。
3. 快进后再确认 `studio2` Push 与 PR #131 两套相同 SHA 全部 14/14 SUCCESS；PR 仍 Draft，`main` 不变。
4. 只在全部完成之后，分别将五个旧 Issue 归档为 **C 级工程收口**，更新 Issue 评论明确未解决问题在 #132；不得勾选 D 级通过、不得把严格资源审批失败解释为一致通过。
5. #132 在实际外部证据、两人复核、`--strict` 正式绿灯之前始终 Open，`productionNoGo=true`。如任一 Actions 未通过或独立分支与 `studio2` 不再能快进，保持五个旧 Issue Open，先修复再重跑，不进行“先合再补”。

## H. 非目标及安全

- 不提交真实用户 ID/邮箱、供应商账单原件、API Key、session cookie、DSN、媒体字节或保密原始 Chrome trace。
- 不为了让性能测试变快而禁止拖拽视觉更新；不为了目录数字一致而自动提升待审画风；不调用真实付费生图，不操作生产 PG/对象存储。
- 本报告是可复核的架构与工程验收结论，不是对尚未执行的 D 级现场动作的承诺或成功证明。
