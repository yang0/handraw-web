# Studio 2.0 Canvas · #111 P2 第七阶段：拖拽期 Style 重算归因

**日期**：2026-11-09  
**基线**：`studio2@316f5cbbcce9133232fee5a217d5a2263af0652e`  
**独立分支**：`studio2-issue111-drag-style-recalc-20261109`  
**跟踪**：[Issue #111](https://github.com/yang0/handraw-web/issues/111)、Draft PR #131。生产发布 #84/#112 D 级尚未签核，NO-GO。

## 依据

第六阶段已在 Chromium 300 节点真实 mouse drag、150 SVG 关联边、120 WebP 的受控 A/B 中，将 pointerup 后（`RecalcStyleDuration`）由约 135.2ms 降至约 0.3ms（CDP 4× CPU 模拟 620.7ms→1.6ms），而完整测试窗口 rAF 间隔 P95 仍约 83ms。证明 **拖拽中仍有重度浏览器样式/渲染开销**；不能再靠优化已不足 1ms 的 JS pointer handler 或宣布 60fps 达标。

CSS `.ic-node` 已启用 `contain: layout style`；尝试纯 CSS translate 的正常 CPU A/B 曾退化，因此不得未经因果验证就启用。此切片首先要**分离空闲背景重算与真实交互导致的样式无效化**，再定位真正热点。

## 可复现诊断

重用 `tests/benchmark_studio_native_canvas_111.py`，运行浏览器中实际已通过 HTTP 建立的 Studio Project。保持窗口 1440×900、真实 300 节点、150 SVG edges、120 张本地 WebP、Playwright `page.mouse` 真实拖拽、零付费 POST。

新增 `profile_drag_style_isolation`，在**同一个 Chrome 页面**依固定顺序测量：

- `idle`：静止，保留实际 Canvas DOM/CSS、脚本/动画；
- `hover`：不按住鼠标，12 段真实 move；
- `normal`：实际按住鼠标移动 12 段；
- `no-card`：仅测试时跳过卡片 `left/top` 写入，其他视觉更新照常；
- `no-edges`：仅测试时跳过 SVG 边路径写入；
- `no-overlay`：仅测试时跳过浮动 toolbar 跟随；
- `no-minimap`：仅测试时跳过小地图定位更新；
- `node-only`：仅保留卡片 `left/top`，屏蔽上述三种输出。

每个 ablation 之间重复一轮 `normal`，报告 CDP `Performance.getMetrics` 的 `RecalcStyleDuration` / `LayoutDuration` / `ScriptDuration` / `TaskDuration`、rAF gap p50/p95、样本数与实测窗口长度，防止把不同耗时窗口简单当作可比较的总累计。诊断不录入原始 Chrome Trace，不读取用户数据，不使用生产项目或收费 API。

**关键安全不变量**：

1. `__HANDRAW_TESTING__ !== true` 时所有视觉通道完全保持原来的生产逻辑；普通用户不能通过 UI 关闭连线、小地图或工具条。
2. 每个视觉旁路明确标记 edge-session 不可信，`pointerup` 保守 `fullRenderCanvas()` 恢复**全部**图层；此处仍保存 Graph 和本地草稿，不触及 Run/计费/权限。
3. 每次真实拖拽完成后检查 Graph/卡片 `left/top` 一致、300 个卡片、150 条 SVG、120 张图片仍存在、Ctrl+Z 恢复起始坐标，未产生付费请求。测试结束复位桥接标志和 CDP session。
4. 即使测试显示某通道有效，也只在下一小范围变更中按同图/同操作 A/B 证明，不用模拟限速单次结果下结论。rAF gap ≠ GPU Present/实体低端机 60fps；CDP Style time 是观察窗口累计，不是 frame exclusive time。

## 运行与 CI

```bash
node --check demo/assets/studio-app.js
node tests/test_studio_canvas_edges_111.cjs
python tests/benchmark_studio_native_canvas_111.py
```

保留旧有 10/50/100/300 工程/Undo/Redo/最小边集合/图片 DOM 验收，`CANVAS #111 DRAG STYLE ISOLATION` 日志与 artifact JSON 只记录**数值**，不导出真实会话或浏览器原始 Trace。独立分支 14/14 后，核查 ahead>0、behind=0 和 expected_sha，再使用 `update_ref(force=false)` 快进 studio2，最后等待 studio2 Push 与 Draft PR #131 **同 SHA 两套 14/14**；main 绝不改变。

## 待下一批数据决策

- 如果 `idle` 已经占绝大多数 Style 开销，优先检查循环动画/常驻 hover 影响，而不是错误地删边/改 minimap。
- 如果 `no-card` 显著降低 Style 重算，需在保持一致端口几何与多选语义下评估 CSS 位置更新替代方案；既有 CSS translate 已在正常 CPU 退化，不直接重启。
- 如果 `no-edges` / `no-overlay` / `no-minimap` 某一种显著改善，针对单一通道做保守增量优化，并验证多次重复与真实帧节奏。
- 没有清晰趋势则留存诊断代码与限制，不进行未经测量的产品改造；#111 仍 Open，正式发布仍 NO-GO。
