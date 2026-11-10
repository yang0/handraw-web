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

## Chrome 原生 Selector Stats（二级证据）

本轮追加真正的 Chrome `SelectorStats`（`disabled-by-default-blink.debug`）：只在第一组 `normal` 实测启用，汇总经过白名单筛选的 `.ic-/#ic-` 规则的 **elapsed (us)、match_attempts、match_count、fast_reject_count**。该采集会显著增加 Chrome 自身匹配计时开销，**不可直接把开启 Selector Stats 的 Style 总时长与未开启时进行 A/B 性能比较**。只用这个报告挑选下一轮 CSS 单点优化候选，再做不带 Selector Stats 的正常/限速 A/B 验证。绝不保存原始 `style_sheet_id`、私人选择器、trace event 或 URL。

如果本次 Chrome 构建没有提供 `SelectorStats`，`selectorStatsEventsObserved=false` 代表“未观察到”，不代表不存在规则匹配开销。

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


## 实测证据（Chrome Runner，2026-11-09）

### 首轮原生 invalidation 追踪 · 14/14 SUCCESS

独立分支 `26af6f233c0266eebddbb2aa28f04c48d32a136a`，Actions [#42565811037](https://github.com/yang0/handraw-web/actions/runs/42565811037)。保留本报告前述 12 次鼠标拖拽标准：normal 306.875ms、media-hidden 290.620ms、normal-repeat 286.466ms、no-visual 48.762ms。布局树 UpdateLayoutTree 受影响元素计数中位约 9365，最大 9431。不是精确的「全部元素重新进行规则匹配」证明。

### Blink SelectorStats 插桩与修复 · 14/14 SUCCESS

初次尝试 `707341a80ae397f93732ea3dd0feb8ff29fbc078` 的 [CI #42566401875](https://github.com/yang0/handraw-web/actions/runs/42566401875) 有 13 个 Job 成功、1 个失败：`disabled-by-default-blink.debug` 追踪超出 30MB 内存上限，诊断脚本按设计拒绝继续读取；**不是产品故障**。该失败和失败日志保留用于审计，未向 studio2 快进。

随后 `108c68b16cb0a77bc1d7ab3b5a774cdc2c02b1d2` 的 [CI #42566872332](https://github.com/yang0/handraw-web/actions/runs/42566872332) **14/14 SUCCESS**；移除非必要高流量 tracing 类别，仅 SelectorStats 试验用**3 次真实鼠标移动**，其余非插桩对照仍用 12 次。保留 30MB 上限、原始 trace 不落盘、全量节点/边/图片/Undo 检查。

- 真实 Studio 300 节点、150 SVG 边、120 张 img 均 decoded；DOM 自然像素和 110,100,480。**图片源是仓库 fixture 内复用的少量 WebP，不等于 120 张不同大图片，也不能代表真实 R2/CDN 的低端设备负载。**
- 非 SelectorStats 的 12 次真实鼠标对照：`media-hidden` 383.202ms、`normal-repeat` 386.050ms、`no-visual` 64.446ms，均为 CDP Drag-only Style 累计。隐藏已有图片绘制几乎未改变 Style 值；不能据此否定解码、GPU/内存、网络传输的真实成本。
- SelectorStats **仅在 3 次鼠标移动样本中打开**，观察到 14 个 SelectorStats 事件、206 个可安全显示的 `.ic-/#ic-` 匹配规则；同一插桩录制的 Style 总时间 2280.313ms **包含巨大的测量开销，完全不能与 12 次普通拖拽耗时比较**。
- 规则匹配热点（仅插桩内的排序，非真实帧外推）：`.ic-wechat-bottombar > *` 8.060ms / 142286 attempts / 0 matches（均 fast reject）；`.ic-canvas-stage:has(.ic-canvas-template-library) .ic-shelf-drawer` 7.623ms / 8 attempts / 0 matches；`.ic-pv-article-sheet.is-notion-dragging *` 4.334ms / 71143 attempts / 0 matches（均 fast reject）；`.ic-node:hover .ic-port-zone` 2.346ms / 3121 attempts / 1 match；`.ic-node:hover .ic-node-header-above` 1.380ms / 2401 attempts / 1 match。
- 可见其它页面的选择器也参与了同一文档的匹配，但**尚未证明哪一条 CSS 规则是全树 Style 失效的触发源**；选择器匹配时间之外还存在计算样式、树失效传播及布局等工作。
- 决策：**不为几个毫秒的插桩排名直接改生产 CSS**，不恢复已证明倒退的 CSS translate/rAF，也不贸然使用 `content-visibility` 或 DOM 虚拟化影响节点端口。继续保留定向渲染与追踪工具，#111 深度性能/重媒体设备 D 级验收仍 Open。

### 发布状态

本轮实验与 C 级 CI 不能替代实体低端机/独立真实媒体/Chromium GPU Present 性能标准，不声称 300 节点 60fps。#11 两个官方资源尚待签核；#84/#112 真实生产部署门禁仍未通过。**Studio 2.0：NO-GO；PR #131 保持 Draft；不得合入 main。**
