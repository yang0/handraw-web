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
- `pressed-idle`：按住鼠标、完成 Pointer Capture 后保持静止 260ms；检验伪类/捕获本身的 style 成本，不改变 Graph；
- `normal`：实际按住鼠标移动 12 段；
- `no-card`：仅测试时跳过卡片 `left/top` 写入，其他视觉更新照常；
- `no-edges`：仅测试时跳过 SVG 边路径写入；
- `no-overlay`：仅测试时跳过浮动 toolbar 跟随；
- `no-minimap`：仅测试时跳过小地图定位更新；
- `node-only`：仅保留卡片 `left/top`，屏蔽上述三种输出；
- `no-visual`：保留 Graph `x/y` 更新与真正的 mousemove，但临时跳过卡片 CSS、连线、悬浮层和小地图全部视觉写入；pointerup 强制权威全图恢复。

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

## 第一批已通过的实测数据与解释

同一独立分支 SHA `60c6cf74cdc6ebf9cc706c6e81aec0399551d801` 完整 14/14 CI
([Run 42560803082](https://github.com/yang0/handraw-web/actions/runs/42560803082)) 真实 300 节点前 12 组数据：

| 场景 | 窗口墙钟耗时 | CDP Style 累计 | rAF gap P95 |
| --- | ---: | ---: | ---: |
| idle | 262ms | 0ms | 16.7ms |
| hover | 386ms | 0.33ms | 16.8ms |
| normal（五次重复） | 972–1042ms | 271–291ms | 66.8–83.4ms |
| no-card | 843ms | 269ms | 66.7ms |
| no-edges | 1061ms | 313ms | 83.3ms |
| no-overlay | 970ms | 283ms | 83.3ms |
| no-minimap | 973ms | 290ms | 66.7ms |
| node-only | 951ms | 299ms | 83.3ms |

每组都是相同的真实 300 节点 Studio，但墙钟时间、缓存热度和顺序并不相同；**不可以只看毫秒差额就宣称某个单通道是瓶颈**。可确定的是 idle/hover 样式成本远低于真实拖拽，而单独省略卡片/边/工具条/minimap 的某一路没有显著稳定改善。

为了确定「按住捕获」还是「只要存在任一视觉 style/attribute 写入就触发全图重算」，下一次新加 `pressed-idle`、`no-visual` 和 per-pointer 模式一致性断言。如果 no-visual 仍和正常 drag 类似，后续就不应继续在边/mini 做局部删减。

## 第二批对照：完整视觉关闭与 requestAnimationFrame 合并

补充 [独立 Run 42561615603](https://github.com/yang0/handraw-web/actions/runs/42561615603)，同一个 300 节点浏览器中：**pressed-idle**（真实 pointerdown、保持 260ms）CDP Style 0ms、rAF P95≈16.8ms；**no-visual**（12 次真实 pointermove + Graph 实时更新，但测试时跳过四类视觉 DOM 写入）Style **47.68ms**、rAF P95 **33.4ms**；同窗的正常 drag 重复组 Style 282–301ms、rAF P95≈83ms。说明同步视觉样式/属性失效是重要成本来源，但**不说明任意一个通道可以删除**。

为避免无意义地每个鼠标事件立即触发 DOM 样式变更，新增一个严格**测试态**的 rAF 合并策略，与普通用户原版 immediate 做同一 Chrome / 同一 300 节点 / 12 次 paced 真实鼠标拖拽 A/B：

1. 所有真实 `pointermove` **立即**更新 Graph 的权威 `x/y`；只有展示相关的卡片 `left/top`、SVG 关联边、浮动工具条和小地图更新才可在实验模式 `canvasDragFlushMode="raf"` 下被合并。
2. 最多登记一个尚未执行的 `requestAnimationFrame`，回调读取当前 Graph 的最新位置，不能拿旧闭包快照覆盖新输入；如果 DOM/Graph 被别的编辑动作替换，保留原有 edge-session 不可信回退逻辑。
3. `pointerup`/**`pointercancel`** 取消未执行的 rAF 并**同步 flush 最后的位置**，才释放 edge-session；防止尾帧丢失、连线/mini 落后、Graph 与 CSS 绝对坐标不一致。
4. 此阶段**生产默认保持 immediate**。只通过 `__HANDRAW_TESTING__===true` 的测试桥选择 `raf`；用 300 节点正常/4× CPU 同 Runner 记录 `physicalPointerMoves` 对 `visualFlushes`、rAF gap P95、drag-only RecalcStyle/Task/Layout、pointerup 最终视觉、WebP DOM identity、SVG hit/line、minimap/toolbar identity、Undo/Redo 与 0 付费。
5. 任何结果必须说明受 Chrome Trace 观察成本、固定 A/B 顺序及缓存影响。如果没有稳定收益，撤销测试态调度代码；如果确实受益，另做受控小切片再考虑生产默认开启。**不以本次测试给出真实 GPU present/实体低端机 SLA 声明**。

## 待下一批数据决策

- 如果 `idle` 已经占绝大多数 Style 开销，优先检查循环动画/常驻 hover 影响，而不是错误地删边/改 minimap。
- 如果 `no-card` 显著降低 Style 重算，需在保持一致端口几何与多选语义下评估 CSS 位置更新替代方案；既有 CSS translate 已在正常 CPU 退化，不直接重启。
- 如果 `no-edges` / `no-overlay` / `no-minimap` 某一种显著改善，针对单一通道做保守增量优化，并验证多次重复与真实帧节奏。
- 没有清晰趋势则留存诊断代码与限制，不进行未经测量的产品改造；#111 仍 Open，正式发布仍 NO-GO。
