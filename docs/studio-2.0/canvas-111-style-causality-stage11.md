# Studio 2.0 · #111 第十一阶段：同窗口 Chrome Style Invalidation 祖先/后代归因

2026-11-09；基线 `studio2@2caaf25fac663d6076e948f0d816a2c50f1dfce0`；独立分支 `studio2-issue111-style-causality-20261109`。关联 #111、#112、Draft PR #131。

## 实施目标与不能越过的证据边界

Stage 10 在相同条件下测得 `UpdateLayoutTree` 峰值约 9,235 个元素；但 Blink `elementCount` 是 Chrome 某阶段报告的元素计数，**不能直接解释为 9,235 个节点都被某条 CSS 选择器重新匹配或受这条规则的失效传播**。Stage 10 的全局 `contain`、选中图层与个别 `:has()` 消融均未获得稳态双 CPU 收益。下一步应从页面真实的属性变化和 Chrome 原生 invalidation 事件切入，不能再以 CSSOM 快照匹配数量替代因果证据。

本阶段先建立两条可信且彼此区别的数据链：
- **页面真实 DOM 侧**：仅在受限 Chrome Trace 期间启用 `MutationObserver`，只记录 `style`、`class` 属性变化对应的 *预定义节点角色*（node / node-header / port / edge-path / world / canvas-stage / studio-shell 等）及实际父级角色链；不保存 `id`、`data-node-id`、class 原值、文本、URL、图像字节、Cookies 或业务内容。
- **浏览器调度侧**：从相同原始 Chrome Trace 中以 `pid/tid`、`ts` 关联 `StyleRecalcInvalidationTracking`、`StyleInvalidatorInvalidationTracking` 与其后最多 50ms 内 `UpdateLayoutTree`，分析树级/属性/伪状态原因的数量，以及与大范围（阈值 8,000）`UpdateLayoutTree` 同窗的事件分类。

**严格不得推断的内容**：原生 Trace 的 `nodeId` 不是已通过 CDP 一一核验的页面 DOM backendNodeId。这里只报告“存在不透明标识字段”，不能把它直接映射为某个业务节点。CSSOM 选择器快照使用固定白名单显示 `.ic-node:hover .ic-port-zone` 等当前页面匹配量，**它与 DOM MutationObserver 的父级链不是同一个证据源，更不是浏览器确证的失效规则**。同窗口发生、同线程接近、CSSOM 匹配均不等于因果关系。

## 真实浏览器测试与候选消融

1. 复用 Stage 10 的隔离 HTTP Server / SQLite 项目与由仓库自有 3 张测试图片临时派生的 **120 个独立 WebP**；300 节点、150 edges、全量解码。所有测试图像只存在 `demo/starter` 下临时文件夹，不提交、不上传。
2. CDP 有界 Trace：真实鼠标 `pointerdown` 后启动 Trace 和 MutationObserver，仅包含 **3 次真实鼠标移动**的独立诊断窗口；结束 Trace 后再 `pointerup`、Ctrl+Z。30 MB 原始 Trace 内存上限不放宽，流数据从不落盘，超限显式标记 `available=false`，不将缺失指标当成 0。若 Chrome 未提供 `ts/pid/tid`，也不得伪造精确节点或链路。
3. 受控 CSSOM `selected-hover-guard`：仅重写三个静态本地 `.ic-node:hover` 选择器中已选节点的匹配，保留已选节点 `.is-selected` 标题/端口状态以及其它节点 hover 语义；操作只在测试页进行，精确恢复原 `selectorText`。
4. 诊断性 `node-hover-rules-off`：仅临时关闭这三个选择器的 hover 匹配，以判断该选择器族是否显著放大拖拽 Style 处理。**会改变交互语义，永远不视为可直接晋升的生产优化**。
5. 每个候选普通 CPU、模拟 4× CPU 分别 **A-B-A-B-A**：每次 12 次物理鼠标移动，必须验证 300 卡片、150 edges、120 图像身份/解码、Graph CSS 坐标、Undo；被测候选必须连续两次相对各 CPU 三次 baseline 中位至少降低 **10% Style 及 Style+Layout 累计时间**、rAF P95 不回退超过 5%，并保证标题/端口可见度、真实命中及几何不变。
6. 即使候选在两档 CPU 同时通过，它也只得到“可继续检查”资格，**还需独立 CI 第二次复验、原生 UI/跨视图回归与真实实体低端设备验证**才能提出任何生产 CSS 修改。无双档稳定收益则不更改生产 CSS/JS。

## 交付位置及验收纪律

- `ops/canvas_style_causality_111.py`：有界 Trace 的时间窗关联和严格脱敏；`tests/test_studio_canvas_style_causality_111.py` 单元回归。
- `ops/canvas_style_causality_browser_111.py`：真实浏览器的 MutationObserver/CSSOM/Chrome Trace，及精准 hover 消融。
- `tests/benchmark_studio_style_causality_111.py`：只在隔离的 QA 进程中复用 Stage 10 的真实 HTTP 项目、加入 Stage 11 归因和 A/B；不修改生产文件。
- `.github/workflows/checks.yml`：添加真实 Chromium 门禁并上传 `artifacts/studio-111-causality/summary.json`（**只包含脱敏汇总**）。
- 工程纪律：独立分支完整 14/14 CI → ahead>0/behind=0 → expected-SHA / force=false 快进 `studio2` → studio2 Push 与 Draft PR #131 同 SHA 各 14/14。所有结果必须有实际 SHA/CI 证据方可宣布成功。

**发布纪律不变：** #111 未定位并通过物理设备验收前保持 Open，#84/#112 真实供应商、PG17、R2/S3、Redis、多实例和物理低端设备 D 级未完成，生产 **NO-GO**，PR #131 永远保持 Draft，禁止合入 main。

## 实测结果

第一轮及覆盖层补充测试的结果见下方；最终交付 SHA 的 CI 验证记录应在实际全绿后于 Issue #111 同步。

## 2026-11-09 实测证据：归因缩窄但尚非核心根因

两套独立分支完整 CI 与脱敏 GitHub Actions artifact：

- 第一轮验证 [#42582127806](https://github.com/yang0/handraw-web/actions/runs/42582127806)：14/14 SUCCESS，3 次真实 pointermove、39 条 Chrome Style Invalidation、3 次大型 `UpdateLayoutTree`（最大 9,185），实测 DOM `style` 变更 10 次：node 5 次、暂未细分覆盖层路径 5 次。第一轮两种 hover CSSOM 消融均未通过普通与模拟 4× CPU 稳态双重复门槛。
- 补充精细化测试 [#42583855111](https://github.com/yang0/handraw-web/actions/runs/42583855111)：14/14 SUCCESS，脱敏 DOM 角色正式定位为 `node` 5 次、`floating-toolbar` 5 次；父级角色链分别通往 `canvas-stage > viewport > world > nodes-layer > node`，以及 `canvas-stage > canvas-overlay > floating-toolbar`。这是 `MutationObserver` 同窗口实测 DOM 目标，不是对 Chrome trace opaque `nodeId` 的已验证映射。
- 第二轮分别在原始 CSS 与仅增加覆盖层 `contain: style` 后进行有界 Chromium Trace，**两者均有 3 次大型 UpdateLayoutTree，最大 9,185 元素**。两窗口 `Style Invalidation` 分类完全相同：39 条（attribute/class 11、style-property 10、stylesheet/selector 8、tree-dependency 8、unknown 2）。50ms 同线程邻近合计 39 条，说明相关失效事件集中在拖拽更新窗口，但**尚不能识别单一的 CSS 源头链**，且该次覆盖层隔离并没有缩小受影响元素的最大范围。

### 目标候选实测（普通与 CDP 4× CPU；12 次物理 mousemove / 一轮）

每组先使用紧邻的 baseline 采集节点、标题、端口、小地图及工具栏几何与透明度，CSSOM 修改后立即恢复，随后针对各 CPU 以 `A-B-A-B-A` 反复采样。以下为拖拽期间 CDP `RecalcStyleDuration` 累积毫秒，候选 B1/B2 与 A 的三次中位对照；不是每帧延迟：

| 候选 | 普通 A 中位 | 普通 B1/B2 | 4× A 中位 | 4× B1/B2 | 双 CPU 稳态门槛 |
| --- | ---: | ---: | ---: | ---: | --- |
| 已选节点 hover 限制 | 263.206 | 262.981 / 260.102 | 1813.494 | 1910.414 / 1990.869 | 未通过 |
| 临时移除节点 hover（仅诊断） | 258.167 | 257.066 / 257.703 | 1616.287 | 1600.239 / 1819.779 | 未通过 |
| 浮动工具栏 `contain: layout style` | 263.332 | 262.107 / 259.009 | 1714.063 | 1669.039 / 1783.741 | 未通过 |
| 覆盖层 `contain: style` | 259.043 | 263.522 / 260.124 | 1824.122 | 1896.047 / 1864.202 | 未通过 |

此外每组都核对了 Style+Layout 总量和 rAF P95，指标必须同时达标才允许进入下一层审核。本轮 **4 个候选 `valid=true`、均未达到两种 CPU 各两次都快至少 10% 的门槛**。关闭 hover 会改变 UI 语义，因此无论测出什么数字它都不能直接上线。

**工程判定：** 这轮精准找到了拖拽期间的两个真实 DOM 样式更新目标（Node / Floating toolbar），但尚未证明它们中谁引发 Chrome 9,185 的布局树影响计数，也无法证明哪个祖先选择器/后代匹配链是根因。当前 `CSS contain` / 层隔离未提供稳定双 CPU 改善，**生产 CSS、JS 继续完全不变；#111 保持 OPEN、#112 生产 NO-GO**。

### CI 耗时治理

Stage 11 使用 Stage 10 的隔离 HTTP、图像、Graph 和 Undo 基础测试设备，但 Stage 10 的 4 种 CSS A-B-A-B-A 已由工作流独立运行；为避免重复耗时，Stage 11 入口在其独立测试进程临时设置 `stage10.CASES=()`，只执行 Stage 11 的 4 种候选，退出后恢复原对象。不得跳过工作流中独立 Stage 10 门禁。该编排优化必须重新跑最终 SHA 全部 14/14 CI 后才可交付。

此阶段数据来源是 Chrome 模拟 CPU 限速（不等于真实低端 CPU/GPU），没有真实浏览器 DOM backend node id 证明，任何“已找到唯一起因”或“生产性能提升 X%”声明都不成立。
