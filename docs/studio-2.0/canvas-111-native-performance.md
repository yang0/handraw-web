# Studio 2.0 Canvas · Issue #111 · 真实业务 10/50/100/300 节点测试与连线优化

2026-11-09。仓库 https://github.com/yang0/handraw-web，目标 `studio2`。本切片沿用已完成的 #127 合成 DOM 和 #112 实际 100 节点项目集成，针对 **原生 Studio 真实业务 Graph、真实项目 API、120 张仓库本地 WebP** 做 P2 性能实测。**不是生产上线签核，也不等同于所有手机或供应商场景。**

## 方法 / 可重现入口

```bash
python -m pip install "playwright>=1.50,<2"
python tests/benchmark_studio_native_canvas_111.py
node tests/test_studio_canvas_edges_111.cjs
node tests/test_studio_canvas_ui_129.cjs
python tests/smoke_studio_native_100_graph_112.py
```

基准通过 `backend.server.create_channel_server()` 创建真实 HTTP Studio 项目，测试账号 Cookie 登录；`graph_fixture(groups=1/5/10/30)` 使用原 #112 的 10 种真实类型模板（文字、画风、参考素材、生成设置、生成结果）、每 10 节点 5 条有向连线与 4 张项目内已存在的 WebP 图片；预期规模为：

| 节点 | 边 | WebP 图片节点 |
|---:|---:|---:|
| 10 | 5 | 4 |
| 50 | 25 | 20 |
| 100 | 50 | 40 |
| 300 | 150 | 120 |

浏览器打开 `/studio/?project=...`，验证完整 Graph/DOM 节点已出现、浏览器未进行任何付费 Generate POST。之后通过**仅 `__HANDRAW_TESTING__` 提供的接口**连续 7 次修改真实文本节点并运行生产 `renderWorldNodes`，读取计时、dirty node IDs、未变其他节点/图片的 DOM identity、另一节点输入框的焦点/选区；再更新生成设置状态并恢复。三次真实鼠标缩放点击校验 dock 可命中性和完整节点未丢失。报告 Chromium 版本、Python/系统与独立 JS heap 快照、原生 DOM 元素数。P95 是**单 CI runner 上 7 个样本和 3 个样本**，不是可对外承诺的稳定延迟 SLA；页面 mount 也混有网络、脚本执行、预热与 DB 读写。

## 只修经证据确认的两处瓶颈

### ① 300 分支的任务栏遮挡缩放 Dock

第一轮真实 300 节点样本发现：`#canvas-129-taskbar` 的 `.ic129-task-chips` 在 30 个 output_control 分支时**多行折叠区仍全量换行**，高度覆盖了 `#bl-zoom-in`。Playwright 的真实 pointer 点击报告 `ic129-task-head` intercepts pointer events，**不是 Playwright flaky，也不能 force click 绕过**。整改：任务摘要单行可横向滚动；右侧保留 zoom tool rail；右侧 dock 的层级保障点击；移动端原 CSS 保留窄屏条件，仍以实际 Chromium 既有 390px 检查为准。新浏览器测例要求 `elementFromPoint` 命中缩放按钮，外加真实 click，整个 300 节点基准已在优化前运行成功。

### ② 150 条边的逐端点 DOM 查询与无变化重建

改动前 `renderEdgesSvg()` 遍历每条边 `getNodeById(e.from/to)`，在 300 节点时最多 300 次 `Array.find`、300 次 `getPortWorldPos` 的 `querySelector` 和重复 `offsetWidth/Height` 读取；此外即使仅文字变化、连线坐标不动，也每次 `DOM.edgesSvg.innerHTML=...` 销毁所有 SVG paths。

现在 `studio-canvas-renderer.js` 的 `createEdgeGeometryIndex()` 在每次 SVG 绘制时仅构建一次 Graph ID 索引和 DOM Node 元素索引，对每个不同端点只读取一次真实宽高。路径由相同的原始坐标计算函数/尺寸语义确定，`renderEdgesSvg` 依然保留 typed ports、关联状态/选中态、拖拽实时布线和 SVG 曲线视觉。单次渲染查找从 `E×N` 线性扫描改为索引查找；`reconcileEdgeMarkup()` 对完整 markup 与上次一致时保留原 SVG DOM，不破坏边 hover/focus。进入空白工作区走 `clearEdgeMarkup()` 清缓存；Graph 更改、缩放尺寸变更、连线增删或选中高亮仍会重新计算并更新。该改动**没有引入虚拟化**，也没有改变后端 Graph Schema/Run/计费/授权。

`tests/test_studio_canvas_edges_111.cjs` 用 300 模型、500 次重复端点读，确认仅一次 DOM query、每个不同端点只测一次尺寸，与旧坐标/未挂载节点回退一致；还测试重复 SVG 不写入、新选中状态写入、清空后重建。真实浏览器进一步验证未改变文字卡的 SVG edge DOM identity 不被销毁，独立运行状态变化才允许路径几何变化。

## 优化前真实 CI 基线（取自同一测试脚本）

CI 记录：https://github.com/yang0/handraw-web/actions/runs/42541479491 （14/14 SUCCESS，**CSS 任务栏修复已在此版本**，连线索引优化尚未加入）。

| 原生节点 | 首次可见 mount(ms) | 修改一个文本节点 P95(ms) | 3 次鼠标缩放点击 P95(ms) | 已保存图片 DOM | DOM 子元素 | JS heap 快照 MB |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 752.4 | 6.4 | 80.4 | 4 | 274 | 6.6 |
| 50 | 698.7 | 22.7 | 96.5 | 20 | 1335 | 8.3 |
| 100 | 882.8 | 43.2 | 109.0 | 40 | 2660 | 10.6 |
| 300 | 1357.2 | 116.1 | 231.2 | 120 | 7960 | 25.1 |

这些数值说明**真实 300 节点下单卡刷新明显超过常见 16.7ms 帧间隔**。定位与改进必须继续使用同一测试脚本和 CI 工件，而不是引用此前的 `#127` 合成 DOM 3.2ms P95 充当完整应用吞吐。

最终优化后对照数据应以相同脚本新的 Actions 日志 / `artifacts/studio-111-native/native-10-50-100-300.json` 为准；不同时间 CI runner 的冷热启动、CPU 调度、JS GC 对 P95 影响显著，**不根据单次加速数值承诺性能预算**。

## 尚待收口

- 仍需在低端真实手机/浏览器、已授权真实多图网络图片、复杂 Graph/多账号多项目上验证 100/300 节点交互与 JS heap/GC 峰值。当前真实 HTTP 是临时 SQLite + 本地存储，不涉及付费供应商，也没有生产对象桶/真实跨主机。
- `renderWorldNodes` 仍为整图 HTML 模板生成、keyed DOM reconcile；300 节点的卡片层仍 O(N) 扫描。是否需要将 template 进一步拆分/按需脏卡渲染、视口裁剪、局部边增量，需要后续基准明确量化收益/兼容影响，不能盲目大重构。
- 本次不触碰服务器 Run 权威、GraphPatch、文章锚点、作品 V3、身份/媒体权限、付费计费或生产数据。#111 保持 Open，#112/#84 D 级仍 NO-GO；PR #131 始终 Draft，main 不变。
