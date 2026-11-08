# Studio 2.0 · #115 / #116 / #117 产品设计走查与收口对账

基线：2026-11-08，仓库 yang0/handraw-web，开发分支 studio2。设计单 #115（Canvas）、#116（Series）、#117（Make Image）。实际 UI 由 #129/#108/#128 负责；共享实现 #102/#103/#105/#107/#119/#123/#125；本轮 #126 承接高级 GraphPatch。

本报告是**设计走查证据**，不代表付费网关、正式对象存储、真实用户或生产安全验收。设计 Issue 关闭须与发布 Go/No-Go 区分。

## 统一原则及布局说明

一个 Project、三种任务（image/series/article）、两种编辑视图（simple/canvas）；生成与计费权威仅 V3 Run/RunItem/Work/Artifact。GraphPatch 只改变用户 Graph 结构，不改既有 RunSnapshot 或媒体，不直接生成或扣费。资源、MediaRef 与隐私规则最终由服务端授权。

桌面图片创作：上方项目/保存状态；左边主题、画风、图型、比例、素材/高级折叠；右边最新结果与版本、作为参考、派生变体、比较。桌面系列创作：四种模式切换、Global Spec、卡片/表格 PlanSlot、每槽位编辑与运行状态、结果筛选与导出。桌面画布：左侧素材/节点/模板，中部可平移缩放 Graph/结果卡，右侧属性/AI 建议，顶栏项目/保存/视图/运行，底部可信任务栏；AI GraphPatch 以审阅对话层展示逐项 diff、费用预估、锁定冲突、确认和云端撤销。窄屏必须优先保留当前任务、操作及反馈；不能用遮挡或静默失败替代响应式设计。

## #115 Canvas 设计走查

| 验收项 | 实施/证据 | 判定 |
| --- | --- | --- |
| 主题起步、素材起步、模板与空态 | #129 studio-canvas-ui.js；smoke_studio_canvas_browser.py | 核心设计已有 UI |
| 云端保存、简洁/画布切换、跨刷新恢复 | #103/#107；smoke_studio_project_reliability_103.py | 本地 HTTP+浏览器已覆盖 |
| 节点类型、端口、选中、拖动、Undo、便签 | studio-app.js + CanvasRenderer；smoke_studio_canvas_browser.py | 核心交互已覆盖 |
| 生成结果/图片组、失败槽位与重新检查 | studio-canvas-ui.js；test_studio_canvas_ui_129.cjs | 状态/权限边界已对齐 |
| 任务队列、停止未提交、远端待核实 | #119 Run projection、#129 taskbar | 状态定义已对齐 |
| AI 增删改节点/连线的审阅/差异/锁定/费用/撤销 | #126 studio-graph-patch-126.js + 后端 + Chromium | 本阶段交付；结论须以最终 CI 为准 |
| 10–300 节点基线和原生 100 节点 | #127 benchmark_studio_canvas.py、#112 native 100-node | 本地已覆盖；大图真实负载仍待验 |

**状态/组件清单**：空态、单选、多选、编辑、运行中、部分成功、失败、远端待核实、保存冲突、AI 预览、锁定冲突、确认已应用、撤销成功/失败。GraphPatch 确认不应覆盖后续其他设备的 Graph 版本，撤销提升 graphRevision 而非回退版本号。

**至少五项用户旅程**：①主题直接新建；②素材先行与模板；③同主题多分支横评；④从系列或文章安全转画布；⑤云端恢复、停止/重试与结果组；⑥ AI 对选中图派生四季/多平台/双风格。设计流对应 #129/#107/#108/#119/#126。

**剩余工程缺口**：#111 大图视口虚拟化和 Undo 内存优化须以指标驱动；#112 真实触屏、低端设备、生产大图/弱网及收费网关。

## #116 Series 设计走查

| 验收项 | 实施/证据 | 判定 |
| --- | --- | --- |
| 四种任务：连续系列、同方案多张、横评、多平台 | studio-series-board-108.js KINDS | 四模式显式建模 |
| 单一 PlanSlot 身份、卡片/表格两种展示 | #123/#108；test_studio_series_ui_108.cjs | 核心实现 |
| Global Spec/逐图覆盖/锁定参数 | #123 studio-series-plan.js | 数据约束已对齐 |
| 合法目录 AI 规划、选择理由、可撤销 | #125 studio_ai_plan.py / studio-ai-plan.js | Mock/合同已覆盖 |
| 顺序稳定、3 成功 2 失败 1 等待、停止/重试 | #108/#119/#112；smoke_studio_series_browser_108.py | 本地 Chromium 已覆盖 |
| 结果筛选/比较/交付与跨视图 | #108 studio-batch.js、#107 | 核心流程；真网关交付仍待验 |
| 桌面/移动卡片响应式与原入口保留 | smoke_studio_series_browser_108.py | 1440/390 本地已覆盖 |

**十二条设计验收场景**：①同方案多张；②六幕系列；③双画风横评；④三种平台比例；⑤第 3 幕单独修改；⑥锁定公共画风；⑦逐图画幅覆盖；⑧ AI 规划撤销；⑨ 3+2+1 乱序运行；⑩定点失败重试；⑪停止未提交任务；⑫一批多图一件 Work、下载、刷新/历史。①–⑧为 #108/#123/#125 结构/交互合同覆盖，⑨–⑪为 #108/#119/#112 受控运行覆盖，⑫为 #84/#112 部分覆盖；真实 Web↔Skill 和真实收费网关必须继续验收。

**设计边界**：切换四种模式、卡片/表格不能丢 slotId/覆盖人工参数；旧 ?entry=batch 入口及本地草稿不得因收口清除。

## #117 Make Image 设计走查

| 验收项 | 实施/证据 | 判定 |
| --- | --- | --- |
| 设置/结果分区，主题/画风/图型/素材/比例核心可见 | #128 studio-make-image.js + UI test | 设计主路径已实现 |
| 单/双画风、参考素材、高级参数渐进显示 | studio-make-image.js、#105 Picker | 核心交互已实现 |
| AI 合法资源推荐、人工锁定、方案采纳与撤销 | #125 studio-ai-plan.js | 合同/Mock 已覆盖 |
| 结果版本、作为参考、变体与比较 | #128 studio-make-image-versions.js | 结果动作已实现 |
| 做同款、保存状态、断线恢复、进入画布 | #100/#122/#103/#107 | 主链已接入；跨页面人工走查待验 |
| 1440/390 界面及输入焦点/结果媒体 | smoke_studio_make_image_browser_128.py | 本地 Chromium 已覆盖 |

**十条设计验收场景**：①新用户输入主题；②未授权画风拒绝；③融合画风切换；④非法图型校验；⑤上传/复用素材；⑥ AI 规划采纳撤销；⑦单图生成与结果；⑧引用结果创作变体；⑨版本比较；⑩保存恢复、做同款与画布互通。#105/#119/#122/#125/#128 覆盖主要可重复场景。⑦真实供应商计费和⑩跨设备场景属于 #112 D 级门禁。

## 设计完成与上线的判定互不混淆

Design Done：每个设计单的版式、状态、组件、数据映射、用户场景以及开发对照已在原 Issue + 本文交付；实现截图/本地 Chromium 有独立脚本可重跑。可按设计关闭条件收口 #115/#116/#117，不必等生产上线。

Engineering Done：#129/#108/#128/#126 等实现 Issue 必须单独取得代码 SHA、测试与同 SHA CI 证据。设计关闭不能冒充代码验收。

Production Go：#112 的真实网关、退款账本、Web↔Skill、PG/Redis/对象存储、跨设备弱网/触屏/隐私与发布回滚仍独立阻断；目前 NO-GO。

## 检验入口

- Canvas：tests/smoke_studio_canvas_browser.py，tests/smoke_studio_native_100_graph_112.py，tests/smoke_studio_graph_patch_browser_126.py
- Series：tests/smoke_studio_series_browser_108.py，tests/test_studio_series_ui_108.cjs
- Make Image：tests/smoke_studio_make_image_browser_128.py，tests/test_studio_make_image_versions.cjs
- Project/运行：tests/smoke_studio_project_reliability_103.py，tests/test_studio_runtime_http_119.py
- 验收矩阵：docs/studio-2.0/e2e-acceptance-112.md
