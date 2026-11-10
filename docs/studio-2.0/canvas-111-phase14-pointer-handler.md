# Studio 2.0 · #111 Phase 14：原生 Pointer 状态与 Studio 处理器独立隔离

日期：2026-11-09。**C 级受控诊断，未获得生产性能 GO。** #111 原 C 级 Issue 已关闭，仍有约 9,185 个 `UpdateLayoutTree` 元素的残余触发机制未归因；D 级设备、实际网络、供应商账单、PG17/对象存储、官方资源审批归 [#132](https://github.com/yang0/handraw-web/issues/132) 持续 Open。

## 因果问题

已归档的 [Phase 13](./canvas-111-phase13-pointer-residual.md) 表明：仅 idle/hover/按下静止无大树事件；在全部可见拖拽 DOM 更新被诊断性绕过的 `no-visual` 模式下，真实拖拽仍有一次约 9,184–9,186 元素的 `UpdateLayoutTree`。已知三条 hover 规则的单独屏蔽无法消除它。

尚有两种未区分的变量：浏览器随真实指针移动改变内部 hit test / active / capture 状态，以及 Studio `pointermove` 回调本身对 Graph/Undo、DOM 查询和浏览器样式计算的影响。此切片只改变**测试浏览器中的事件驱动方式**，不修改生产事件处理器、CSS、SVG、布局或发布代码。

## 六个 Chrome Trace 窗口

在真实 Studio HTTP / SQLite、300 张原生节点卡、150 条 SVG 边、120 张互异且已解码 WebP 的同一个受控浏览器项目，Chrome 模拟 CPU 1× 和 4× 各测试以下三组，全部复用 `no-visual` 诊断模式，trace 只保留脱敏计数和枚举：

| 输入驱动 | 浏览器真实指针位移 | Studio 回调执行 | Graph 坐标预期 | 用途 |
| --- | --- | --- | --- | --- |
| `native` | 是 | 是 | 前移，随后 Undo 回退 | 原生基线 |
| `synthetic` | **否**；Page.mouse.down 后保持实体鼠标位置不变 | 是：在当前 viewport 分发与真实 down **同一 pointerId** 的 `PointerEvent`，`isTrusted=false` | 前移，随后 Undo 回退 | 检查仅执行回调可否重现残余事件 |
| `native-handler-blocked` | 是 | 否：同一个 viewport capture 阶段暂时 `stopImmediatePropagation` | 未移动、无拖拽 Undo | 检查仅浏览器移动能否重现残余事件 |

每条原生 `pointerdown` 通过监听器拿到实际 `pointerId`；合成事件明确标记 `isTrusted=false`，且绝不伪装成实体设备验收。所有监听器在 `finally` 中撤销，原有 hover CSSOM 与 no-visual probe 恢复为正常。对合成事件数量、被拦截事件数量、Graph 坐标、节点/边/媒体计数、解码状态、真实 Undo、Trace 的非空性全部断言；任何失败必须红灯，不得因为被拦截事件的 Graph 没有移动就假装已经验证真实拖拽。

## 如何解释对比（仅作诊断，非最终根因）

- `synthetic` 也有大树事件、`native-handler-blocked` 无：进一步支持 Studio 回调或其中的浏览器测量与无视觉布局失效关联，但并**不**等于证明某一函数唯一致因。
- `native-handler-blocked` 也有大树事件、`synthetic` 无：进一步支持浏览器设备状态 / 命中测试 / PointerCapture；仍须分离样式伪类和复合处理器路径。
- 两组都有或都没有：仍有交互作用、绘制时序、测试合成事件与真实 input 不等价等混杂，不得下根因结论。
- 1× 与模拟 4× 仅检验是否可复现趋势；没有实体低端 CPU/GPU、VRAM、触屏、弱网证据，不是 D 级真实性能验收。

## 安全边界与归档

改动仅涉及 `ops/canvas_phase14_input_111.py`、诊断性的 `ops/canvas_phase13_pointer_111.py` 可选驱动、浏览器基准入口、测试、CI Artifact 路径和本文。所有浏览器局部监听器由独立测试设置和撤销，不触碰生产 `demo/assets/studio-app.js` 或 CSS。Chrome Trace 原始字节不写磁盘；输出只列元素/事件数、允许的分类和 `true/false`，不读取图像字节、任意 DOM 文本、账号密钥或业务数据。汇总 JSON 路径：`artifacts/studio-111-phase14/summary.json`，由现有 Chromium Job 上传。完整断言失败时当前分支不能进入 `studio2`。

严格遵守独立分支→14/14→compare ahead>0/behind=0→`expected_sha` + `force=false` 快进→同 SHA `studio2` Push 和 Draft PR #131 各 14/14。未验证的生产指标不写成已达标，PR #131 保持 Draft，`main` 不改，生产 NO-GO。FF-018/FG-025 网站审批、真实第三方付费、异机 PG17 物理恢复、R2/S3/CDN、Redis 多实例和实体设备验收全部仍属于 #132，必须单独签核。
