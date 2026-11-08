# Studio 2.0 · Issue #127 首轮画布渲染/输入稳定性基线

代码仓库：https://github.com/yang0/handraw-web  
目标分支：`studio2` · 父任务 #111 · 后续画布 UI #129 · 性能 QA #112。

## 结论（首轮，不承诺无限节点）

原画布已经存在按 `data-node-id` 的 DOM Key 增量替换，但对选中、高频状态反馈仍完整生成整层 markup/重复绑定大约 52 组交互；输入节点失焦与运行结果因 Undo/Redo 被较早 Graph 快照覆盖也是风险。#127 的修改在不变更 Graph Schema、typed ports、现有 prompt 编译器、项目 API 和 V3 Run 的前提下明确了三类边界：

1. **Canvas Renderer** — `demo/assets/studio-canvas-renderer.js`：按节点 ID reconcile，仅替换发生结构/数据变化的卡片，保持其他节点 DOM/图片对象；发生必要的单卡替换时复用同 URL `<img>`，恢复输入值、焦点、光标、滚动位置；返回 dirtyNodes + 可审计的改动计数。
2. **Selection/Editor** — `studio-app.js`：节点单击、框选、边选走轻量 `refreshCanvasSelection()`，只更新 class 与 SVG 连线，不重新生成卡片。事件绑定只触达 dirtyNodes，不在每次更新重绑所有卡片；布局测量只触达改动节点，有高度变化/节点增删才计算自动防碰撞位置。
3. **Run/History** — Undo/Redo 使用 `preserveRuntime(current, snapshot)`：恢复用户编辑的节点/边/参数，同时保留最新 output_display、Run ID、RunSnapshot、异步请求号、文章配图已有 media/RunItem；Graph revision 单调递增，不会因编辑撤销退回旧的已执行状态。

## 可重复测量

执行：

```bash
python -m pip install playwright
python tests/benchmark_studio_canvas.py --require-browser --output artifacts/canvas-127.json
python tests/smoke_studio_canvas_browser.py --screenshots artifacts/canvas-127-screen
node tests/test_studio_canvas_incremental.cjs
```

浏览器脚本用本地 Chromium，固定视口 1440×900；浏览器/机器信息与完整 JSON 保存于 Actions Artifact。无真实付费生图网关。

### 第一轮 Chromium 基线（CI #42452859215）

<caption>Chrome 156.0.8078.0 · x86_64 · 4 vCPU（浏览器 hardwareConcurrency）· 浏览器 reported memory 16 GB · 1440×900。合成 Canvas DOM 卡片，含真实 img/input 元素与交错模拟 Run 进度，**不是完整 Studio 300 节点真实业务吞吐测试**。</caption>

| 节点 | 首屏测量（ms） | 单张进度更新 P95（ms） | 平移/缩放帧 P95（ms） | DOM 元素数 | JS heap（MB） |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 188.4 | 0.4 | 16.7 | 42 | 1.79 |
| 50 | 25.3 | 5.1 | 16.7 | 210 | 2.28 |
| 100 | 32.5 | 1.3 | 16.8 | 420 | 2.25 |
| 300 | 31.8 | 3.2 | 16.7 | 1260 | 3.47 |

- 首个 10 节点场景含浏览器冷启动、页面首次动画帧等预热费用，不能用于断言小图比大图慢；帧间隔约 16.7ms 反映当前 60Hz 环境。
- 四组全部通过：未受影响节点复用原 DOM；全部已加载结果图像元素复用；单卡变化仍恢复输入光标/选区。
- 这里的 `firstScreenMs` 计时包含两帧 `requestAnimationFrame` 等待，与真实业务页面首次可交互时间不同。
- `usedJSHeapBytes` 为快照非峰值，且 Chromium GC 抖动可导致 100 节点的堆快照小于 50 节点；不得用此数直接做容量承诺。

### 浏览器/CI 证据

- [首轮 Chromium 14/14 检查记录](https://github.com/yang0/handraw-web/actions/runs/42452859215)
- 完整画布实站烟雾测试：选择、拖拽、缩放、布局、撤销/重做、截图（最新 CI 的 `interaction-journey-regression`）。
- 旧 Node 回归：`tests/test_studio_canvas_incremental.cjs` 的多分支 Run/media 保真与渲染边界，复用既有 #102/#107/#124 Graph 验证。

## 尚待单列评测

目前没有声称真实 300 节点业务画布具备流畅编辑能力。合成 DOM 基准**不包含**网络图片大尺寸解码、200 条文章配图、真实并发多个 Run 的后端负载，也不等价于低端手机浏览器。因此在 #129/#111 中持续测量实际模板/复杂 Graph 场景；以真实体验和稳定复测设定预算，不提前开启全量虚拟化。

#127 明确不实现高级 AI GraphPatch（#126）、DAG 并发调度（#120），也不重做画布完整 UI（#129）。
