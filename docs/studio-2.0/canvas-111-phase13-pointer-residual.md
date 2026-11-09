# Studio 2.0 · #111 Phase 13 残余 `UpdateLayoutTree` 指针归因归档

2026-11-09 · 接续已关闭的 #111 **C 级工程诊断**，未决生产设备/性能风险继续由 [#132](https://github.com/yang0/handraw-web/issues/132) 跟踪；此处不恢复 #111 的生产交付含义。PR #131 继续 Draft，`main` 不动，生产严格 NO-GO。

## 已核验的原始证据来源

先前隔离分支 `studio2-closeout-remaining-issues-20261109@6a422563b588a57fc86323af608dbba681aa97b5` 的 [GitHub Actions #42609134113](https://github.com/yang0/handraw-web/actions/runs/42609134113) 为 **14/14 SUCCESS**；真实 Chromium `interaction-journey-regression` 日志包含 `CANVAS #111 PHASE13`，输出以下脱敏窗口：

| 真实指针窗口 | `UpdateLayoutTree` >= 8,000 元素 | 最大 `elementCount` | 属性变更 | 顶层 class 变更 |
| --- | ---: | ---: | ---: | ---: |
| idle-stationary | 0 | 无 | 无 | 0 |
| hover-moving | 0 | 4 | 无 | 0 |
| pressed-stationary | 0 | 无 | 无 | 0 |
| drag-no-visual | **1** | **9,184** | 无 | 0 |
| drag-no-visual-hover-mask | **1** | **9,185** | 无 | 0 |

`no-visual` 禁止本实验中节点坐标、SVG 路径、工具栏等拖拽可视写入，仅用于因果隔离；pointermove 仍走真实 Graph 拖拽处理、pointerup 全量 render 和 Undo。**没有记录到属性变更不代表完全没有 DOM 更新**：本阶段新增独立的 `childList` / `characterData` 脱敏计数器，并将结构变化按 `node / edge-svg / floating-toolbar / minimap / overlay / viewport / canvas-stage / other` 分类；只保留数量，不读取节点原文、用户数据或 Trace。

已知三个 `.ic-node:hover` 规则临时通过 CSSOM 精确屏蔽（结束后恢复），大树事件仍未消除。1×、模拟 4× CPU 的实际 A-B-A-B-A `RecalcStyleDuration` 中，B1/B2 不但未稳定达到至少 10% 改善，且相对原 no-visual 基线出现退化：

| CPU 档位 | no-visual 中位 Style (ms) | hover-mask B1/B2 (ms) | 两次 B 都达标 |
| --- | ---: | ---: | --- |
| 1× | 22.153 | 31.123 / 32.477 | 否 |
| 4× 模拟 | 96.503 | 150.425 / 132.197 | 否 |

以上计时属于诊断环境，非生产性能 SLA；鼠标事件时序、Trace 采样以及浏览器实验条件对结果有影响，**不允许将它外推为正式产品配置改变后的性能预期**。

### 支持与不支持的结论

- 支持：残余约 9,185 元素更新**至少与真实拖拽处理过程有关**，并不是普通空闲、hover、按下不动任一条件单独充分导致；已知三条 hover 规则不是独立充分原因。
- 不支持：已经定位唯一 CSS 选择器/布局树失效机制；拖拽 Graph、JavaScript 或 Chrome 自身某单一路径已经被证实为根因；`elementCount` 代表某一 CSS 规则重新匹配了 9,185 个 DOM 元素。
- 不支持：停用拖拽视觉反馈能作为产品优化。没有生产视觉保真 + 独立低端实体设备和 1×/4× 稳态收益，不修改任何生产 CSS/JS。

## 合入现行工程门禁的方式

本切片只从既有成功分支**按文件选择性移植**以下内容到基于当前 `studio2` 的新分支：

1. `ops/canvas_phase13_pointer_111.py`：严格五窗口、有界 Trace、视觉隔离、DOM 结构脱敏、真实 Graph Undo 校验；保证使用真实 300 节点 / 150 SVG 边 / 120 张独立解码 WebP 的现有 Studio HTTP fixture，断言零付费供应商调用。
2. `tests/test_canvas_phase13_pointer_111.py`：验证控制窗口、CSSOM 恢复、无敏感内容、非法输入 fail-closed。
3. `tests/benchmark_studio_phase12_111.py`：复用 Stage10/Phase12 同一个 Chrome 项目与 HTTP/SQLite fixture，不额外运行第二套冗余 Stage10 基准；在 Phase12 后追加 Phase13，并生成 `artifacts/studio-111-phase13/summary.json`。
4. `.github/workflows/checks.yml`：只增加 Phase13 的匿名汇总 JSON Artifact 路径，不改变 Job 总数、生产代码或试验阈值。

**完整交付严格要求：** 新独立分支 14/14；`compare(studio2, branch)` 为 ahead>0/behind=0；`expected_sha`+ `force=false` 快进；同 SHA 的 `studio2` Push / Draft PR #131 再各 14/14；期间任何红灯、分叉或实测与原结果矛盾都不写生产 CSS/JS、不开 GO。

**持续 D 级阻断：** 实际低端 CPU/GPU、弱网、触屏和真实存储/供应商/PG17/Skill 官方目录签核仍未提供。无论本档案的浏览器 CI 多次绿灯，[#132](https://github.com/yang0/handraw-web/issues/132) 继续 Open，FF-018、FG-025 不得未经网站审核发布，`--strict` 缺正式 DB 已批准数据时仍须失败。
