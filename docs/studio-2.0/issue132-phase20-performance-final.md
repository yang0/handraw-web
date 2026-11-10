# Studio 2.0 · Phase 20 #111 性能诊断最终结案（C 级，不是性能修复）

日期：2026-11-10。目标：停止重复的局部消融与无证据的生产改动，把剩余风险正式转入 #132 的真实低端设备 D 级门禁。Phase 19 独立基线为 `a11f01afe68d0313a4f59e536ce172917577e721`，CI [#42669617545](https://github.com/yang0/handraw-web/actions/runs/42669617545) 14/14 SUCCESS。浏览器测试 Artifact `studio2-canvas-127-benchmark` ID `13698203412`，文件 `studio-111-phase19/summary.json`；本页的数值来自该实际运行记录，不是模拟期望值。

## 事实与局限

真实本地 Chromium，Studio 300 节点、150 SVG edge、120 张独立解码 WebP；两档 CPU：1× 和 **仅 Chrome DevTools 模拟**的 4×。每档 5 个 A-B-A-B-A 独立拖拽，实机 pointerdown + 三次 `isTrusted=false` pointermove，采用一段连续 Chrome Trace 捕捉全部三个 move。受控 B **只跳过内容与当前 DOM 完全相同**的 `Node.textContent` 赋值，分别针对 `#bl-save-project` / `#studio-project-status`；文字真正改变时必须执行原生 setter。每次恢复原型，Graph/Undo/Media 保持成功。

| CPU | A 原始大树 UpdateLayoutTree 次数（3轮） | B 仅跳过相同标签（2轮） | A 最大元素数 | B 最大元素数 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 1× | `1,1,1` | `0,0` | `9185,9185,9186` | `2,3` | 对**完全相同的**文字写入，有稳定局部消融信号 |
| 模拟 4× | `1,1,2` | `2,1` | `9185,9185,9185` | `9185,9185` | B 两轮的两按钮写入都是**真实文字变化**，没有一次跳过，依旧有大树事件 |

4× B 的文字变化时，每轮仍有 2 added/2 removed 的文本 DOM 节点，且有 >=8,000 元素的 `UpdateLayoutTree`。不能以“不触发 setter”为优化方案，因为用户真实保存状态会错误显示。1× B 消除大树事件只证明一种**合成实验条件下的依赖**，不等于 Chrome 布局机制的唯一根因或真实用户普遍收益。Chrome `elementCount` 不等价于 CSS 重匹配元素数。

## 正式工程判定

- `dualCpuControlledSignalObserved=false`，`rootCauseUniquelyProven=false`，`productionVisualEquivalenceIndependentlyProven=false`，`physicalLowEndDeviceTested=false`，`productionChangeAuthorized=false`。
- **#111 C 级诊断正式归档结案，不再追加同类局部 A/B 或无限追踪单一 selector。** 这不等于把 9,185 元素布局风险标为“已修复”。
- 生产 `demo/assets/studio-app.js`、`demo/assets/studio-canvas.css`、`demo/assets/studio-canvas-renderer.js` 均不得因本实验调整；不能隐藏保存状态、禁用拖拽反馈或压制真正标签变化。
- 后续只在 #132 **真实低端硬件** D 级计划内验证：实际物理 CPU/GPU/VRAM、触屏、弱网、300 节点及素材解码、首帧拖拽/Zoom、Graph/Undo、保存反馈、交互可用性及逐步可见状态。记录原始封存证据、采样环境与双审核者；未见实机可接受结果仍为 BLOCKED。
- 若未来拿到稳定双 CPU + 实体设备、完整视觉无损收益，**另开独立 Issue**、生产代码专门评审、复测 14/14 后才讨论是否修改 JS/CSS；本次 Phase20 禁止预先优化。

## 交付边界

Phase20 保留 Phase19 的测试/测量工具供未来审计，不把模拟结果算作生产通过；把新开发优先级移至官网三项资源授权审批、Web/Skill strict 一致性，以及供应商账单、PG17 物理异机 PITR、真实 R2/S3/Redis 等 17 项 D 级发布门禁。#132 必须 Open、PR #131 必须 Draft、`main` 不变、生产一律 **NO-GO**。
