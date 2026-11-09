# Studio 2.0 Canvas · #111 P2 脏节点定向渲染

**日期：** 2026-11-09  
**仓库：** `yang0/handraw-web`，目标分支 `studio2`，Draft PR #131。  
**依赖：** `studio2@b6eeb1cf1e68e2fdb734d8914e65ad06b0fa2640`，该基准含真实 10/50/100/300 节点、120 张本地 WebP、150 条 SVG 连线；既有 Graph/Run 媒体权威与编辑历史均保持不变。

## 为什么这一轮要做脏节点

#127 已把不变节点的真实 DOM 保留，但 #111 的真实 Studio 基准确认，只改一个文本节点时 `renderWorldNodes()` 仍执行 `nodes.map(...)`，构造全部 300 张业务节点卡 HTML，接着整图解析 `template.innerHTML`。这不是节点 DOM 消失，但它仍会消耗主线程、GC 和 HTML 解析成本。上一阶段 300 节点真实业务单卡 P95 约 **57ms**，虽然低于更早的 116.1ms，仍明显高于 16.7ms 的目标帧间隔；数字是不同 Runner 的单次样本，不是生产 SLA。

## 保守实现

- `renderWorldNodes(changedNodeIds)` 显式传入少量 ID 时，先确认当前编辑视图确实为 Canvas、Graph 与挂载 DOM 的节点数一致、请求 ID 都是已挂载的真实 Graph 节点，且请求不超过 12 个 ID。否则**退回原有全图 reconciliation**。没有传入 ID 的全部旧调用语义不变。
- 确认可局部处理后，**在 `nodes.map` 之前过滤**。只为指定卡片生成 HTML；`HandrawCanvasRenderer.reconcile(..., partial=true)` 复用原图片/输入焦点保留策略，但不删除其他节点或公共 `datalist`。renderer 自身也禁止局部更新时传入未知节点或 datalist。
- 只把明确无拓扑变化、纯视图状态的三个用户操作接入：结果图集展开/收起、槽位对比切换、结果分页。涉及全局布局、节点增删、切项目、AI GraphPatch、DAG、文章结构、运行结果权限、保存等仍沿用原完整渲染路径。
- 连线仍经过完整几何检查、既有 index/cache 保障；局部更新后卡片尺寸变化仍走原来的纵向碰撞调整逻辑。这不是视口虚拟化，也不是完整 O(1) 画布渲染。

## 复现与验收

```bash
node --check demo/assets/studio-canvas-renderer.js
node --check demo/assets/studio-app.js
node tests/test_studio_canvas_dirty_111.cjs
node tests/test_studio_canvas_incremental.cjs
node tests/test_studio_canvas_edges_111.cjs
python tests/benchmark_studio_native_canvas_111.py
python tests/smoke_studio_canvas_browser.py
```

原生 Studio Playwright 基准通过本地临时真实 Project HTTP、Cookie 和 SQLite 验证 10/50/100/300 节点，在**同一个真实 Chrome 页面、相同 Graph/DOM/Runner** 下分别对同一输入卡做 7 次全量更新和 7 次单卡定向更新。分别记录 `fullNodePatchP95Ms`、`nodePatchP95Ms`（定向）、精确 `patch.nodes=Graph size/1` 和 `patch.partial`。检查未动节点、120 张静态本地图片、150 条边和活动输入的焦点与选区稳定；缺失/不合法脏 ID 回退全量；虚拟批量图集的**实际 Studio UI 事件处理器**必须单卡更新，其他卡片保持同一 DOM；绝无付费生图 POST。

CI 按原有 14 Job 保留 #111/#112/#127 全量回归。测试结果写入 `artifacts/studio-111-native/native-10-50-100-300.json`，附 Chromium 版本和 CI 平台。只有实际 Push/PR 同 SHA 成功才能并入目标分支。

## 待解决/不纳入本切片

- 仍可进一步测量 `fullRenderCanvas()` 和 Run 高频推送路径是否允许显式定向更新；不可在未明确受影响的节点集合前盲改其语义。
- 本轮仍需按 100/300 节点真实页面、低端设备和大媒体数据评估 O(N) 联边处理、局部视口裁剪和编辑历史差异日志是否有现实收益。
- 不改变 Graph Schema、持久化、私有媒体、文章锚点、权限、收费或工作流执行算法，PR #131 保持 Draft、`main` 不变。生产环境 D 级验收由 #112/#84 继续承担，#111 保留 Open。
