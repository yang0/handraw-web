# Studio 2.0 Canvas · #111 P2 第五阶段（拖拽悬浮层）

**日期：** 2026-11-09  
**基线：** `studio2@7483d8eba6ab6d92aa83bfe213fec4886443fb0f`  
**分支：** `studio2-issue111-drag-overlay-hotpath-20261109`  
**关联：** [Issue #111](https://github.com/yang0/handraw-web/issues/111) 与 Draft PR #131。

## 为什么做这个切片

上一阶段 `createEdgeDragSession()` 利用缓存几何减少了每次 `pointermove` 的全图 forced layout。但真实 Chromium 10/50/100/300 业务节点的 9 个物理鼠标事件仍显示：300 节点 total handler P95 为 **43.6ms**、其中 edgeAndPosition P95 仅 **0.3ms**（4× CDP CPU 模拟为 162.0ms / 1.0ms）。之前不是同 Runner 实验，所以不能把所有下降归因于这一个优化。需要把剩余工作拆为浮动层与小地图，而不是虚报 300 节点已达 16.7ms 的帧预算。

在 `positionFloatingOverlays()` 内，每次移动卡片的 `style.left/top` 后都读取 `DOM.viewport.getBoundingClientRect()` 与悬浮 topbar 的 `offsetWidth`。这可能导致浏览器强制 layout，尤其在 DOM 中存在上百图片、节点与 SVG 的情况下。

## 保守实现

- 选择已处理、toolbar 已真实挂载之后，用 `captureDragOverlayMetrics(startPositions)` 一次性测量 viewport 宽高、toolbar 宽度，缓存当前 Graph 节点与选区的对象身份和原始索引。
- 拖动中 `validDragOverlayMetrics` 检查 Graph/selectedIds 引用、节点身份、viewport/overlay DOM、缩放、相机和侧栏状态；有效则只按现有节点的实时 `x/y/w` 算 topbar `left/top`，不触发 DOM 尺寸读取；失效则退回原来的权威 DOM 布局计算。
- 真正 window resize 使缓存失效，结束 drag 时不再保留会话引用；不增加永久观察器，不修改基础 Graph、媒体/Run、撤销、联边权限或收费路径。
- 浮动层 DOM 本身只更新 left/top，不重新生成 toolbar、按钮、图片或整张卡。

## 真实验收与测量边界

使用 `tests/benchmark_studio_native_canvas_111.py` 的隔离 HTTP 项目、Chromium 和 10/50/100/300 业务节点、120 本地 WebP、150 SVG 联边、真实鼠标 press/move/up。

```bash
node --check demo/assets/studio-app.js
node --check demo/assets/studio-canvas-renderer.js
node tests/test_studio_canvas_edges_111.cjs
python tests/benchmark_studio_native_canvas_111.py
python tests/smoke_studio_canvas_browser.py
```

每个 9-frame drag 新增 `overlayMs`、`minimapMs`、`edgeAndPositionMs` 统计，分别报告 P95。严格确认 9 帧均命中 overlay cache，真实工具条跟随拖动且保持同一 DOM；无关 SVG edge/minimap 仍保持相同身份，图片 DOM 未重载，Undo/Redo 恢复位置，付费 POST 为 0。300 节点继续报告 CDP 4× CPU 模拟，**不将模拟视为真实低端机 SLA**。

此阶段不盲改 `renderMinimapMovedNodes`。如测量显示小地图仍有强制 layout，再按另一独立微切片优化，并补充受控基准。

## 发布纪律

独立分支完整 14/14 之后进行 ahead/behind 与 expected_sha 原子检查；只允许 `force=false` 快进 studio2。再取 studio2 Push 和 Draft PR #131 同 SHA 的两套 14/14；从不修改 main，PR 永远保持 Draft，正式发布在 #112/#84 真实 D 级签核前 **NO-GO**。#111 留 Open 直到低端设备、真实网络媒体、大 Graph 和帧预算得到可信验证。
