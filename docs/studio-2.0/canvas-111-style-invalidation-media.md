# Studio 2.0 · #111 第八阶段：Chrome 样式失效 / 选择器 / 120 WebP 归因

日期：2026-11-09。基于 `studio2@97c1a3ed44b84b98bd094f6f91b34cd42fdeb4e1`，独立分支 `studio2-issue111-style-invalidation-media-20261109`。

**状态：诊断提交、等待独立分支全量 CI 实测。NO-GO，不发布，不合并 main。**

## 第七阶段可复用的事实

- 300 原生业务节点、150 SVG 边、120 本地 WebP；真实 Playwright 鼠标拖拽。
- 静止/按下不移动时 Style 成本接近 0；正常 12 次拖拽样式累计多次在 282–301ms；`no-visual` 仍为 47.68ms。上述数据来源为前一阶段的特定 CI 环境，不是新实验结论。
- `left/top` → `translate` 在普通 CPU 下回退；按 rAF 合并尝试后事件/提交数未减少，均已撤销。禁止把这些策略再次作为无证据生产默认。
- `contain: layout style` 已存在于 `.ic-node`。不得仅因看到 contain 就宣布隔离完成。

## 本轮新诊断

`ops/canvas_style_invalidation_111.py` 汇总 CDP `StyleRecalcInvalidationTracking`、`StyleInvalidatorInvalidationTracking`、`StyleInvalidationTracking`、`ScheduleStyleRecalculation` 事件，并在存在时记录 `UpdateLayoutTree.elementCount`。对原因仅做固定分类。不同 Chrome 版本可能完全不生成这类事件；此时必须报告 `invalidationEventsObserved=false`，不能报告“没有样式失效”。

`tests/benchmark_studio_native_canvas_111.py` 在原有 #111 的 10/50/100/300 HTTP Studio 项目验收之外，对 300 节点新增真实 CSSOM 选择器候选查询与同页四组追踪：

1. `normal`：原始 DOM/CSS/120 WebP 绘制。
2. `media-hidden`：只用**临时测试样式**抑制同 120 张图的绘制，图片 DOM、资源加载、图模型和边数不变；测试结束删除样式。
3. `normal-repeat`：回到原状态，防止顺序/缓存造成假收益。
4. `no-visual`：沿用上一阶段测试专用的图模型写入但跳过可视更新模式，pointerup 权威全量恢复。

每组采样 Style/Layout/Script CDP duration，Chrome tracing 仅留分类计数、受影响元素估值，严禁保存原始 trace/页面文本/URL/令牌。**Style duration 采样截至 pointerup 之前，而 tracing 聚合覆盖 pointerup 和其后收尾，两个观察窗口不能混为同一个分母**。

所有真实 gesture 继续校验：Graph 移动、`left/top` 与 Graph 一致、300 张卡、150 条边、至少 120 张 img、Ctrl+Z 恢复；0 个付费请求。4× CPU 仿真与真正低端机不同，CDP 样式总时长也不是呈现帧时间。

## CSS 选择器与风险初查（静态源码）

- `demo/assets/studio-canvas.css` 的 `.ic-node:hover`、`.ic-node:hover .ic-node-header-above` 与 `.ic-node:hover .ic-port-zone` 是**候选**，并非已定位根因。
- `.ic-doc-tab:has(+ .ic-doc-tab:hover)` 位于标签栏，不应未经 trace 证明就关联到节点树级重算。
- `.ic-node` 使用 `contain: layout style`；普通节点沿用 `left/top`。需查 Chrome 失效事件与匹配结果是否落在整棵世界层，再决定是否修改 DOM/CSS。
- CSSOM 的 `querySelectorAll` 匹配数量只能描述候选选择器的**影响范围**，不能直接归因某条规则的样式重算成本。

## 判定和收口规则

- 无 Chrome 失效事件：继续保留 unknown，不能臆造 invalidated node 数或“罪魁选择器”。
- 正常与媒体隐藏之间有稳定差异：只能形成图片绘制敏感性证据，**不能推论 WebP 解码/GPU/树级 Style 的因果关系**；须在同条件 A/B 验证具体优化、完整图层正确性与回退成本。
- 任何新 CSS、Canvas Renderer 改动必须在**独立分支**重复真实 300 节点、120 张 WebP、150 边、普通与模拟 4× CPU，保证 Graph/DOM、输入焦点、Undo/Redo、停止/刷新/权限不回归。
- 未有稳定收益就保留诊断及限制，#111 仍 Open；#84/#112 生产 D 级签核之前继续 NO-GO。

## 本轮交付证据（待 CI 回填）

- 源码：`ops/canvas_style_invalidation_111.py`；`tests/test_studio_canvas_style_invalidation_111.py`；`tests/benchmark_studio_native_canvas_111.py`。
- 输出：`artifacts/studio-111-native/native-10-50-100-300.json` 中 `styleInvalidation` + 既有 `styleIsolation` / `framePipeline`。
- 分支 CI（14/14）：**待验收**。
- `studio2` Push + Draft PR #131 同 SHA 两套 CI（各 14/14）：**未执行，不得快进**。
- 真实生产/物理低端设备：**待验证，NO-GO**。
