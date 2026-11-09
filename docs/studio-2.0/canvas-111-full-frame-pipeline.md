# Studio 2.0 Canvas · #111 P2 第六阶段：真实完整帧与渲染管线测量

- **基线：** `studio2@98493a6bb18eb15fe95cbbe5f38577d0d8c23244`
- **独立分支：** `studio2-issue111-full-frame-profile-20261109`
- **登记：** [Issue #111](https://github.com/yang0/handraw-web/issues/111)
- **门禁：** Draft PR #131；`main` 不改；#112/#84 D 级未通过，发布 NO-GO。

## 目的与约束

前五阶段已将 300 节点真实 Chromium 的**鼠标处理器内部** P95 降至 0.5ms（4× CDP CPU 模拟 1.3ms）。这不包含浏览器 Layout、Paint、Raster、Composite、合成器提交、GPU Fence 或 Present，不代表 300 节点可稳定 60fps。不能用虚假的完整帧指标作下一次优化依据。

本阶段优先测量，不盲目改变产品渲染器：

1. `tests/benchmark_studio_native_canvas_111.py` 仍使用真实 HTTP Project、Chromium、10/50/100/300 原生节点、120 本地 WebP、150 SVG edges；原 9 次真实 `page.mouse` 拖拽及 Undo/Redo、SVG/迷你图/图片、零收费 POST 验证保持。
2. 对 100、300 节点补 **12 次带 20ms pacing 的真实 mouse.move**，并在鼠标按下/移动/松开以及松开后布局校正期间用 `requestAnimationFrame` 捕获屏幕帧回调间隔。输出 rAF P50/P95/max、超过 16.7 和 33.3ms 的样本数。这是 **rAF 节奏而不是 compositor 实际帧完成、显示器 Present 或 FPS SLA**。
3. 使用 Chromium DevTools Protocol `Performance.getMetrics` 在测量窗口前后取 `LayoutCount/LayoutDuration/RecalcStyleCount/RecalcStyleDuration/ScriptDuration/TaskDuration` 的差值；所有 duration 使用毫秒，缺指标输出 `null` 而不是误报 0。
4. 在相同窗口开始/结束 Chromium `Tracing`；按 whitelisted event name 输出 Layout、Style、Paint/PrePaint、CompositeLayers/UpdateLayerTree、RasterTask 的出现情况、计数和**非排他事件时长之和**。某个组没有事件时视为 `observed=false`、值 `null`；**绝不据此断言 GPU 耗时 0**。
5. 300 节点增加 CDP `Emulation.setCPUThrottlingRate=4` 的同类实验，明确这是 CPU 模拟，不是物理低端设备。真实网络媒体、触摸交互、实体低端机/显卡、GC 长期采样仍待 D 级复核。

## 安全与数据边界

- `ops/canvas_frame_trace_111.py` 仅保留白名单事件类别及时间汇总；原始 trace 在内存解码后即丢弃，不上传到 Actions、磁盘或测试日志。
- Trace stream 上限 30MB、事件数 400000；超过上限显式报错，而不是继续记录含 URL、token、提示词、用户输入等元数据的 raw trace。
- 结果包含 Chrome 版本、runner Python/OS/architecture、1440×900 视口及 CPU 模拟系数，可复现但不是生产 SLA。
- 新增 Python 单测 `tests/test_studio_canvas_frame_trace_111.py` 验证未知指标处理、trace 无敏感泄漏、内存上限、Unicode/二进制 CDP chunk、计时单位与 rAF 样本计算。

## 运行

```bash
python -m unittest discover -s tests -p 'test_studio_canvas_frame_trace_111.py' -v
python tests/benchmark_studio_native_canvas_111.py
```

GitHub Actions 现有 `interaction-journey-regression` 使用真实 Chromium 执行测试并上传 `artifacts/studio-111-native/native-10-50-100-300.json`；Python full suite sharded 自动发现新单测，**不增加额外付费 API 调用**。

## 验收纪律与后续

独立分支完整 14/14 → 核验 `ahead>0,behind=0` 与目标 HEAD 未漂移 → `update_ref(force=false,expected_sha=base)` 快进 `studio2` → Studio Push 与 PR #131 同 SHA 各 14/14。PR 保持 Draft，绝不合入 main。

如果 rAF gap 与 CDP Layout/Paint/Composite 显示明显剩余耗时，结合**同环境、同图、同操作的受控前后对照**决定是否修改 CSS contain、缩略图结构或视口管理。不要在证据不足时引入全量虚拟化、Canvas/WebGL 框架或声称上线性能达标。#111 继续 Open。
