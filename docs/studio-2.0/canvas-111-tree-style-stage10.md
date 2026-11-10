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


## Chrome Runner 首轮实测与结论（2026-11-09）

- 在中间 SHA `8cc12114ef08a9e914b55a2b7c374022d8139f51` 的 [独立分支 CI #42575332854](https://github.com/yang0/handraw-web/actions/runs/42575332854)，**14/14 SUCCESS**，含 Stage 10 的真实 Chromium 交叉运行；此前 `416ea995` 的首轮 Trace 因超过 30 MB 安全上限失败，已通过限定仅 3 次真实鼠标移动并捕捉上限错误修复，未放宽上限。
- **基线仍有大范围布局树更新**：3 步有界 Trace 中 `UpdateLayoutTree` 受影响元素数中位 **9,184**、最大 **9,235**（19 个有效样本）。与第八阶段 9,365 中位的差异属于不同采样窗口，**不是生产优化收益**，不能断言唯一 CSS 属性、继承链或选择器已经找到。
- `world-style-containment` 测量有效，但两档 CPU **均未达到连续两次至少 10% 的 Style 与 Style+Layout 降幅**：

| Chrome 档位 | baseline Style 中位 | candidate Style 两次 | baseline Style+Layout 中位 | candidate Style+Layout 两次 |
| --- | ---: | ---: | ---: | ---: |
| 普通 CPU | 155.069 ms | 162.042 / 151.125 ms | 160.545 ms | 167.383 / 156.268 ms |
| CDP 模拟 4× CPU | 625.773 ms | 619.488 / 625.125 ms | 647.612 ms | 642.075 / 646.365 ms |

- `world-layout-style-containment`、`selected-compositor-layer`、`relational-selector-off` 都未通过测量前置有效性检查，**不能拿它们的未测数据作为性能收益**；最新 runner 会在安全范围内显示拒绝原因，具体以该 runner 日志及 `summary.json` 为准。
- 此阶段的 **已验证结论** 仅是：为已有 `.ic-node { contain: layout style }` 的图再添加世界层 `contain: style`，不能稳定减少受测的 Style 工作。其它候选并未建立充分有效的 A/B 数据；`:has` / hover / 树级依赖仍是待证假说。
- **决策：不应用生产 CSS/JS 改动，不关闭 #111，不把未达到双 CPU 严格门槛的方案同步到用户界面。** 分支仅引入可重放诊断、CI 和证据，并继续保持生产 NO-GO。验收应推进更直接的 invalidation reason / matched selector 与祖先-后代依赖定位，以及实体低端设备测量。

### 有效性门禁复核（2026-11-09）

中间 CI #42576038664 在相同 SHA 上完成 14/14，但显示诊断预检的 **后三个 CSS 候选均因节点/标题/端口/小地图几何偏移而拒绝**。复查发现预检的原始几何坐标是在整个测试最初捕获，多个 A-B-A-B-A 拖拽、Undo 后已经不一定是相邻参照；这种偏移不应直接归因某个 CSS 候选。

新的测试改为 **每一个候选单独采集紧邻的原生 CSS baseline**，再比较 CSS 注入后的几何；这样将长期页面状态漂移与 CSS 的即时效果分离。最新 SHA 需重新执行完整 14/14 验证，再决定候选是否真实改变节点几何，不能引用旧报告中 `valid=false` 作为最终的 CSS 副作用定论。

本次不同有界 3 步 Trace 的 `UpdateLayoutTree` 受影响元素计数可出现大量小值，单轮样本中曾是 19 个报告样本中位 9,184，另一轮 21 样本中位 6、最大 9,235；**样本窗口与浏览器事件混合，不能把该中位数当稳定的同尺度性能 KPI，更不能据此宣称已锁定全树失效的唯一起因**。需要重点观察重复出现的高元素事件与对应 mutation/selector 的同窗关联。最终结论以固定后的同 SHA runner 数据为准。

## 修正相邻基线后的确认结果：四候选均真实可测，但均未达标

最终复核测试提交 `729ed5b8244114b39c68af05c37c8edb29564520`：[独立分支完整 CI #42576577211](https://github.com/yang0/handraw-web/actions/runs/42576577211) **14/14 SUCCESS**。测试脚本在各候选注入之前立即重新采集原生 CSS 几何基线，因此前一版因跨轮拖拽/Undo 导致的“几何不一致”误判不再出现。四候选 `valid=true`、全部 `promotionAllowed=false`；`relational-selector-off` 同时设置 `diagnosticOnly=true`，不能直接改生产样式规则。

普通 CPU 和 4× CPU 的 Style 累计（12 次真实 pointer move，单位 ms）：

| 候选 | 普通 CPU 基线中位 | 普通 CPU 候选 B1/B2 | 4× CPU 基线中位 | 4× CPU 候选 B1/B2 | 双 CPU 10% 门槛 |
| --- | ---: | ---: | ---: | ---: | --- |
| `world-style-containment` | 199.467 | 205.150 / 197.635 | 1082.348 | 1066.135 / 895.294 | 未通过 |
| `world-layout-style-containment` | 197.469 | 195.281 / 198.126 | 1037.993 | 1090.632 / 1063.778 | 未通过 |
| `selected-compositor-layer` | 199.867 | 196.431 / 202.283 | 920.209 | 1063.011 / 1073.758 | 未通过 |
| `relational-selector-off`（仅诊断） | 195.255 | 192.851 / 195.213 | 1081.466 | 882.306 / 1096.619 | 未通过 |

另外的 Style+Layout、rAF P95、CSSOM 有效性与 Graph/DOM/Undo 保真结果均包含在同一 CI `artifacts/studio-111-tree-style/summary.json`，绝不能仅截取最好的 B1 数值来证明收益。

**树级失效对照：** 在有界 3 次物理鼠标移动的 Chrome Trace 中，原生 baseline 与临时关闭匹配目标的 `.ic-canvas-stage:has(.ic-canvas-template-library)` 后的 `tree-dependency` 类计数**都是 386**。两组 `UpdateLayoutTree` 最大受影响元素均是 **9,235**，中位均是 **9,184**（baseline 17 个有效样本，消融 20 个）。该次证据不支持“该特定 `:has` 规则是大范围更新的唯一或主要触发器”；事件分类不是属性/选择器单点归因证据，且有限次 Trace 的不同事件窗口不足以证实所有其它规则无影响。

**确认决策：** Stage 10 已完成代码化消融、真实浏览器复验与审计证据；在当前 1×/4× CPU 条件下，**没有任何候选符合稳定收益且保真门槛**。因此保持生产 `demo/assets/studio-canvas.css` / `studio-app.js` 等完全不动。#111 继续 OPEN，后续应沿 Chrome tree-dependency 的安全分类深入做节点/祖先作用域归因，并由独立实体设备复验；#84/#112 发布门禁仍然 NO-GO。后续代码 SHA 的 CI/分支快进结果须另行记录，不把此独立 SHA 的成功套用至后续提交。
