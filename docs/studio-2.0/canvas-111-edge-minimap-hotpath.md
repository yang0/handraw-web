# Studio 2.0 · #111 Canvas P2 第三阶段：关联边与小地图热路径

**日期：** 2026-11-09  
**起点：** `studio2@43c93fb0f9857ad1d3bb2d0a5214b9b54b14ff96`  
**分支：** `studio2-issue111-edge-minimap-hotpath-20261109`  
**关联：** [#111](https://github.com/yang0/handraw-web/issues/111) / Draft PR #131。

## 测得的瓶颈与实现边界

上一阶段 300 个原生业务节点、150 条 SVG 连线、120 张本地 WebP 的真实 Studio 同页脏卡片更新测得全量 111.8ms / 定向 48.8ms（7 次样本的 P95）。虽然只解析 1 张卡片，原本仍无条件执行 `renderEdgesSvg()`，该函数逐次建立整个 Graph/DOM 几何索引、读取所有联边端点、拼接全部 SVG 标记。每次相机平移、滚轮缩放还会完整生成 minimap 的全部矩形。多节点拖拽则同时触发全边 SVG 重置和全小地图重置。

本切片保守收敛三个热点：

1. **单卡纯内容/状态补丁**：`renderWorldNodes([id])` 只有在可信局部路径且无测得节点宽高变化和布局碰撞时，才跳过 `renderEdgesSvg()`；全部 Graph/topology/全量路径、尺寸变化仍完整重算。
2. **拖拽路径**：`HandrawCanvasRenderer.patchMovedEdgePaths` 遍历现有 edge 模型找相邻边，预检查所有关联边的 Graph 与 SVG group、hit/line path，全部满足才就地设置两条 path 的 `d`；未关联 SVG 节点、hit 目标、stroke/selection 保持同一 DOM。缺失/重复绑定则返回 false 并由原始完整重绘回退；没有连边则直接成功。每次局部写入使完整 SVG 缓存失效，拖拽结束后的完整渲染重新校正。
3. **小地图**：只平移/缩放镜头时更新已挂载 `data-mini-lens` 的坐标和缩放文字，不再次拼接 300 个小矩形。节点拖拽时若仍在现有 bounds 内仅更新受影响的 `data-mini-node-id` 矩形；移出边界、结构/节点数不一致、首次挂载则回退 `renderMinimap()`。

不改变 Graph schema、DAG、连线允许规则、RunSnapshot、私有媒体、历史快照、权限和计费逻辑。局部优化**不**改掉 `renderEdgesSvg()` 和 `renderMinimap()` 两个权威完整路径。

## 可重复验收

```bash
node --check demo/assets/studio-app.js
node --check demo/assets/studio-canvas-renderer.js
node tests/test_studio_canvas_edges_111.cjs
node tests/test_studio_canvas_dirty_111.cjs
node tests/test_studio_canvas_incremental.cjs
python tests/benchmark_studio_native_canvas_111.py
python tests/smoke_studio_canvas_browser.py
```

既有 `test_studio_canvas_edges_111.cjs` 追加：一条联边更新只写对应的 SVG hit/line path、其他边 DOM 与 `d` 不变、重复相同几何不写、缺失边和无效 Graph 必须完整回退。真实 Chromium 基准追加：10/50/100/300 节点 7 次脏文本更新不得触发全图连线重算，三次真实缩放按钮点击不替换小地图节点或 lens DOM，原有焦点/选区、图片稳定、SVG identity、总节点数与 0 收费请求断言保留。初次挂载及完整项目操作也仍由原用例覆盖。

**性能报告规则：** 以同页/同一 Runner 的 before/after 为主要证据；CI 观测值具有抖动，不把任意一次 P95 当作真实低端设备性能 SLA。完整真实业务 300 节点、网络图片、移动/低端设备、GC 以及 D 级生产准入仍待验证。

## 发布红线

独立分支完整 14/14 后才能以 `force=false` 且核对旧 `studio2` SHA 快进；同步后单独验证 `studio2` Push 与 Draft PR #131 同 SHA 14/14。没有成功记录前不宣称完成。#111 保持 Open，#112/#84 生产 D 级继续 NO-GO，禁止修改 main。