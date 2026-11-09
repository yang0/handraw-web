# Studio 2.0 · #111 Phase 15：首次移动与后续移动的 Trace 时间窗

2026-11-09 · **C 级诊断，不是生产性能优化。** 承接 [Phase14](./canvas-111-phase14-pointer-handler.md) 与开放的 [#132](https://github.com/yang0/handraw-web/issues/132)。本阶段没有修改生产 CSS/JS 或服务器。

## 观察到的问题

Phase14 在两个独立 CI 运行中，真实移动和明确 `isTrusted=false` 的合成事件均能在 `no-visual` 下复现约 9,185 个 `UpdateLayoutTree` 元素的更新。但是「原生移动 + 捕获阶段拦截 Studio `pointermove`」在 4× 模拟 CPU 下曾出现 1 次，在另一运行中又降到 0 次；因此**单一监听器被证明是唯一根因**这个说法并不成立。Phase14 之前的 Trace 是一次拖拽三次移动的总窗口，无法辨别大树更新是在首次动作前、首次移动、第二或第三次移动附近发生。

## 实验契约

在已有真实 Studio Chromium HTTP/SQLite 负载（300 原生节点、150 SVG 边、120 独立解码 WebP）的**同一次真实 pointerdown** 中，保持物理鼠标不移动；依次发出与实际 pointerId 相同的 3 次明确未受信任的合成 `PointerEvent`。在模拟 1× 和 4× CPU 下分别采集四个彼此独立且有边界的 CDP Trace：

| Trace 窗口 | 行为 | 主要判别 |
| --- | --- | --- |
| `pre-input-idle` | 真正 pointerdown 后无移动，先进行有限的 DOM 几何读取 | 检查鼠标按下及上一次渲染遗留的异步刷新 |
| `synthetic-move-1` | 仅派发第一次 untrusted move | 是否与 Undo 首次入栈、Graph 初次坐标改变同时出现 |
| `synthetic-move-2` | 第二次 move，不重新 pointerdown | 进一步区分初始化与持续拖拽 |
| `synthetic-move-3` | 第三次 move，继续同一 Graph 拖拽 | 评估后续持续拖拽是否同样触发大树更新 |

每个窗口分别记录脱敏 `UpdateLayoutTree` >=8000 次数及最大元素数、Chromium 已枚举的失效事件/原因、同线程 <=50ms 的**时间邻居**理由、只计数不读取文本的 DOM 属性和结构变化。必须强制校验 Trace 非空、四个窗口恰好有序、合成事件 3 次、没有真实鼠标移动、300/150/120 与媒体真实解码、权威 `pointerup` 全渲染、原生 Undo 恢复。任一条件失败必须让 CI 红灯。

### 因果解释限制

Trace 的启停、CDP/浏览器异步样式刷新、测量代码与事件循环会移动布局计算落在窗口的边界。**某个更新落在一次 move 的窗口内，不代表该 move 是唯一成因。** 如果 `pre-input-idle` 已发生大树更新，应首先标注前序渲染未结算/测量干扰；如果集中在 move #1，则后续再对 `pushUndo`、节点模型读写与命中状态进行更细的受控测试，但在此之前不能修改生产拖拽逻辑。如果每次都触发，则继续确认 UA 响应还是 UI 渲染读取导致。

本阶段只在测试浏览器注入已测试过、退出会立即清除的输入钩子，输出 `artifacts/studio-111-phase15/summary.json`（**不保存**原始 Trace、具体坐标、用户文本、账户内容或图片字节）。没有真实低端硬件、真实网络、费用账单/退款、PG17 物理恢复、实际 R2/S3/CDN、官方 FF-018/FG-025 审批或独立双人签核时，生产继续 NO-GO。

## 集成门禁

独立分支 `studio2-phase15-move-boundary-20261109`。本切片只改变 `ops/` 的诊断脚本、现有浏览器入口、单测、CI Artifact 路径以及本文。必须先独立 14/14 GitHub Actions，再校验和 `studio2` 比较 `ahead>0/behind=0`，使用 `expected_sha` + `force=false` 进行非强制快进；快进后同 SHA 的 Push、Draft PR #131 双 14/14 再分别验收。即便全部成功也只能作为 C 级诊断，[#132](https://github.com/yang0/handraw-web/issues/132) 保持 Open，PR #131 必须 Draft，`main` 不合并。
