# Studio 2.0 Canvas #111 · P2 第四阶段：真实拖拽与拖拽会话索引

- **基线**：`studio2@765ca2fb638a0786720c8a32572bda3a3688b9e2`
- **开发分支**：`studio2-issue111-drag-session-20261109`
- **关联**：[#111](https://github.com/yang0/handraw-web/issues/111)，Draft PR #131
- **发布门禁**：真实 D 级未签核，继续 NO-GO；绝不修改 `main`。

## 已定位的热点

前一阶段只更新关联边，但 `patchMovedEdgePaths` 每个 `pointermove` 仍遍历 **全部** `graph.edges`、全部 SVG edge group、全部节点及画布 DOM，再为少量关联边计算贝塞尔路径。这让 300 节点拖拽有不必要的 O(N+E) 每帧开销。

## 最小范围实现

- `createEdgeDragSession(svg, graphEdges, nodes, layer, movedIds, bezierPath)` 在已完成节点选择和完整 SVG 更新后建立一次关联边与当前真实 DOM 的映射。
- 拖拽中逐帧仅校验关联边、读取关联端点实际 `offsetWidth/offsetHeight` 并原位更新对应 `hit/line d`；不同步替换无关 SVG 边，不改变连线颜色、命中范围、边选中状态。
- 对 Graph array 替换、节点/边数量变化、关联边的端点被修改、DOM group/path 被卸载、节点卡片不在 layer、缺失路径等校验失败时，立即返回 false；产品调用现有 `renderEdgesSvg()` 完整回退，再尝试建立新的会话。
- 在 pointerup/pointercancel 结束本次闭包的生命周期，原有 `fullRenderCanvas()` 负责完整落盘前 UI 校正。Graph 模型、Undo/Redo、DAG、运行结果、付费与媒体权限逻辑不变。
- 测试桥及采样器严格以 `__HANDRAW_TESTING__ === true` 为前提，不开放给普通网站访客。

## 真实交互验收

```bash
node --check demo/assets/studio-canvas-renderer.js
node --check demo/assets/studio-app.js
node tests/test_studio_canvas_edges_111.cjs
node tests/test_studio_canvas_dirty_111.cjs
node tests/test_studio_canvas_incremental.cjs
python tests/benchmark_studio_native_canvas_111.py
python tests/smoke_studio_canvas_browser.py
```

基准使用真实 HTTP Project + Chromium 10/50/100/300 业务节点，现有 120 张 WebP、150 条 SVG 边和专用账号 Cookie；浏览器真实 `page.mouse.down/move(steps=9)/up`，必须证明关联边 `hit/line` 路径随 Graph 改变、非关联边和小地图 DOM identity 保留、图片 DOM 不丢、Graph 节点位置更新且 Ctrl+Z/Ctrl+Y 真正恢复。

- 采集 9 段真实 pointermove 处理器 `totalMs` 和 `edgeAndPositionMs`，报告 p50/p95。第一段可能包含 Undo 历史捕获，单独检查波动，不能把所有时间都归功于新索引。
- 300 节点补充 CDP `Emulation.setCPUThrottlingRate=4` 的实验，恢复到 rate=1。**这是浏览器 CPU 限速模拟，不是实体低端设备、触屏或生产 SLA。**
- 前后对比不同 Runner 的数值只属于描述性观察；严格因果优化还需同机同图基准、长期采样和 frame/GC 分析。
- 任何付费生成 POST 应为 0，已有项目加载、Gallery、焦点/媒体、权限及 #112 全套 CI 不得退化。

## 验收纪律

独立分支 14/14，且 `ahead>0,behind=0`、`studio2` SHA 等于锁定基线，才允许 `update_ref(force=false,expected_sha=基线)`。之后必须取得 `studio2` Push 与 Draft PR #131 同 SHA 全绿。本文件与脚本不构成生产准入证据；#111 继续 Open，#112/#84/#11 按真实环境和官方资源审批规则保持 Open。
