# Studio 2.0 Canvas · #111 P2 编辑历史内存切片

日期：2026-11-09。仓库 `yang0/handraw-web`，目标 `studio2`，Issue #111，设计边界 #115，P1 基线 #127。不是“无限节点流畅”的性能承诺。

## 做与不做

`#127` 通过真实 Chromium 的**合成** DOM 基线测得 300 卡单项状态更新 P95 约 3.2ms、拖拽/缩放帧间隔 P95 约 16.7ms；没有大型真实 Graph、多图片网络解码、低端手机、真实供应商并发证据。因此**暂不引入完整 viewport 虚拟化**，也不为此替换渲染器或前端框架。

`studio-app.js` 原先 `pushUndo`、`undoGraph`、`redoGraph` 每一次都 `JSON.stringify/parse` 整份 Graph，在 35 步记忆历史里复制多张不可变媒体、RunSnapshot、后台任务 ID 以及文章生成结果。新 `studio-canvas-renderer.js:captureEditableGraph()` 仅在**易失浏览器标签的历史**中共享这些已由服务器或 Run 拥有的数据对象引用；仍对文本、参数、文章正文、卡片 subject、节点几何、边、选中集合深拷贝。删除 output_display 后的 Undo 仍保留原展示节点与媒体，避免只存 ID placeholder 无法恢复的错误。历史数据不写入 `OPEN_TABS_KEY` 或服务端 Project；真正项目存储、Graph Schema、RunSnapshot、作品和计费数据**没有修改**。

| Graph 类型 | Undo Snapshot | 恢复语义 |
|---|---|---|
| `text_input` / `skill_params` 等 | editable `data` 深拷贝 | 撤销用户编辑 |
| `output_control` / `loop` | 用户配置独立深拷贝；`RUN_FIELDS` 引用共享 | 最新 Run ID、请求号、进度和快照覆盖历史 |
| `article_plan` | 正文/卡片文案深拷贝；卡片 `ARTICLE_CARD_FIELDS` 引用共享 | 历史正文可撤销，已生成 media/variants 保留 |
| `output_display` | 完整布局、node id；Run/media `data` 引用共享 | 可撤销误删展示节点，但不回退成功图片/状态 |
| `graph.runRefs`、`meta.runRefs` | 共享只读权威引用 | `preserveRuntime` 保留当前权威引用 |
| 所有边、选择、节点非 runtime 属性 | 深拷贝 | 保持原 Graph 编辑历史语义 |

这里的共享数据在当前 JavaScript 对象可能继续被异步更新。这是有意设计：**Run/媒体不是可撤销用户编辑**。在销毁标签、切账号时历史数组被清除；持久化项目仍始终完整序列化当前 Graph。旧全量 Undo 快照仍可由 `preserveRuntime` 恢复，没有数据库迁移。

## 可重复测试与测量

```bash
node --check demo/assets/studio-canvas-renderer.js
node tests/test_studio_canvas_edit_history_111.cjs
node tests/test_studio_canvas_incremental.cjs
python tests/benchmark_studio_canvas.py --require-browser --output artifacts/canvas-127.json
python tests/smoke_studio_canvas_browser.py --screenshots artifacts/canvas-127-screen
```

新 Node 测试构造包含 10/50/100/300 个节点、真实结构的大字符串媒体结果/RunSnapshot 并连续 35 次采集。在输出 JSON 中记录 capture 的 wall clock（不是 Chromium 帧时间）、不复刻全 Graph 的媒体对象唯一引用数、`theoreticalFullSnapshotBytes`（35 份旧 JSON 快照长度）和估计的共享引用 payload 数量；这些**不是精确 heap 测量**，不应把保守估算当成客户端 RAM 下降百分比。每个级别都要求 runtime 对象在 35 个步骤中共享同一 identity、可编辑对象不共享；另外测试从编辑中撤销、重做、运行中更新和删除展示节点后恢复媒体。

Node 专项接入现有 `feed-ui-regression`，不增加 14 个 Job 总数。原 `#127`、`#129` 真实 Chromium 画布烟雾测试继续覆盖拖拽、缩放、焦点、Undo/Redo、复制与多选；必须全绿才有资格并回 `studio2`。

## 剩余 #111 验收（不虚报已关闭）

- 当前工具测的是 Run/媒体共享对象和编辑历史捕获成本；**尚未**覆盖多机型完整业务 100/300 节点、网络大图 decode、滚动 viewport 的实际 input latency 和低端设备内存峰值。
- `studio-app.js` 仍有大块的流程代码，下一次按真实 profile 决定是否把 Graph History 完整模块化、改为真正的逆操作/增量差分日志或按需裁剪视口。不能用这次共享引用优化称为“真正 O(1) Undo”，其 editable nodes 仍需 O(N) 拷贝。
- 若大 Graph 仍超预算，再将有证据的瓶颈拆成有限可验收 Issue。保持全部 Run、私密媒体、审核、保存 CAS 与多账号边界。

该工程切片不是生产 D 级验收；Issue #112/#84 继续待真实供应商、PG17、对象存储、Skill/实体移动端现场验收，PR #131 持续 Draft，main 不变。
