# Studio 2.0 / Issue #111 — 第十阶段：树级 Style 失效归因及定向隔离 A/B

日期：2026-11-09；起始基线 `studio2@4023c3bf7cfde7236f51df04def13e8a30a82c03`；独立分支 `studio2-issue111-tree-style-ablation-20261109`；关联 Draft PR #131（绝不合并 main）。

## 问题背景

Stage 8 Chromium `UpdateLayoutTree` 在 300 个真实节点、150 条 SVG 边、120 张复用 WebP 的测试中报告约 9,365 元素（中位数）；Chrome SelectorStats 提示其他界面的宽作用域选择器、`:has(...)` 和 Canvas hover 规则值得进一步分析。但 **`UpdateLayoutTree elementCount` 并不直接等价于由单条规则造成的全树 invalidation**。Stage 9 证明 120 个不同 WebP URL 在等像素条件下并未造成明显新增 Style 处理；不能将其理解成真实 GPU/VRAM、网络、低端设备已过关。

代码现状：`.ic-node` 原本已配置 `contain: layout style`。为避免无依据的性能承诺，本阶段先只在 **真实浏览器测量页中临时修改 CSS**，不改生产 CSS/JS。目的是观察隔离候选的增益与功能风险，找到可重复的因果线索。

## 诊断候选（仅测试注入，不进入用户界面）

1. `world-style-containment`：对 `#ic-nodes-layer` 注入 `contain: style`，检验世界层的样式隔离。
2. `world-layout-style-containment`：对世界层注入 `contain: layout style`，同时检查绝对定位与覆盖层坐标不漂移。
3. `selected-compositor-layer`：仅对 `.ic-node.is-selected` 注入 `will-change: transform`；**不是**对 300 个节点全部强制建图层，避免潜在 GPU 内存暴涨。注意 `will-change` 可能改变层叠上下文和 fixed 子元素定位，故只供受控消融。
4. `relational-selector-off`：通过测试页 CSSOM 暂时移除匹配 `.ic-canvas-stage:has(.ic-canvas-template-library)` 的规则，之后精确恢复原 `selectorText`；如果规则不存在或 CSSOM 不支持变更，标记为未验证，绝不虚构优化效果。

`contain: paint` 会裁切在节点外侧显示的标题、连接端口、弹层，未证明交互安全前不作为候选。CSS `contain`、`will-change` 及选择器消融不能替代消耗分析或真实设备测试。

## 测量与候选放行门槛

- 新建隔离 SQLite、Studio 登录与真实 HTTP Project；使用 Stage 9 的源图片派生器，在临时静态目录创建 **120 个独立 SHA256 WebP**（每张 960×720），全部 `img.decode()`，保持 300 节点/150 SVG edges。
- 真实 `page.mouse` 鼠标按下与 **12 个 pointer move**，逐次核对 Graph 坐标与 CSS 左上角、150 条边、300 张卡片、120 张图片的 DOM 不被重建、Undo 后回到原位；不向收费生图服务发请求。
- 对每个候选、每个 CPU 档位执行 **A-B-A-B-A**（baseline/candidate），采集 CDP 的拖动期间 `RecalcStyleDuration` 和 `LayoutDuration` 及 rAF gap P95；分别在原生 CPU 与 CDP 模拟 4× CPU 独立验收。
- 候选的两次独立采样都必须相对于三次 baseline 中位数至少减少 **10% Style 时间、10% Style+Layout 时间**，且 rAF P95 不得劣化超过 5%。候选几何、header/port 可见度必须与 baseline 一致；不满足任何条件则该候选 **promotionAllowed=false**。
- 用受大小上限保护的 Chrome Trace，在 baseline 与 CSSOM 关系选择器消融后记录 `UpdateLayoutTree` 影响元素数量及 invalidation 类别。**Trace 包含 pointerup/Undo，与 drag-only CDP Performance 窗口不同，不得放在相同分母比较**。
- 所有 CSSOM 修改必须恢复；测试结束不持久化样式规则、不上传图片、不存原始 Chrome Trace、URL、Cookie/令牌或用户数据。唯一产物：`artifacts/studio-111-tree-style/summary.json` 中脱敏数值及布尔门禁。
- 此门禁是 **采用生产 CSS 候选的必要而非充分条件**：即使某次 runner 两档均达标，还需在第二次独立 run 复验、Chromium UI 截图/交互验收和真实低端物理设备上确认，不应凭一次 CI 直接部署。

## 当前执行状态及发布纪律

- 实验程序：`tests/benchmark_studio_tree_style_111.py`，由 `.github/workflows/checks.yml` 的真实 Chromium job 调用。
- 此文档记录方案与判定准则；**实际运行结果以对应 CI log 和 summary.json 为准**，无实测不得填入收益数值。
- 独立 SHA 全部 14/14 CI 成功之后，核查 ahead>0/behind=0、使用 `force=false` + `expected_sha` 将 `studio2` 快进，复核同 SHA 的 Push/PR 分别 14/14。
- 如果没有找到正常与 4× CPU 都稳定获益且完全保真之候选，本阶段只交付 **诊断和可复验测试**，不允许宣称生产性能根因已解决，#111 保持 OPEN。
- 生产 **NO-GO**：真实 GPU/VRAM、低端实体机、PostgreSQL/Redis/R2、供应商账本及 #84/#112 D 级门禁仍需另行验收；PR #131 继续 Draft，严禁合入 `main`。
