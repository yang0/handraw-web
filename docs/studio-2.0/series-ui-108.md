# Studio 2.0 · 系列创作方案板（Issue #108，第一批 MVP）

相关：[#108](https://github.com/yang0/handraw-web/issues/108) · 设计 [#116](https://github.com/yang0/handraw-web/issues/116) · 底座 [#123](https://github.com/yang0/handraw-web/issues/123) · AI [#125](https://github.com/yang0/handraw-web/issues/125) · Runtime [#119](https://github.com/yang0/handraw-web/issues/119)。

## 执行边界

- 仅替换 **系列创作简洁视图** 的视觉编排；`studio-series-board-108.js` 只读 `SeriesPlan/PlanSlot` 并生成 UI，不保存第二份方案。
- 所有新增/编辑/复制/排序/参考图/比例修改直接调用 `HandrawStudioSeries`，`Loop.data.studio2Plan` 仍为唯一可写权威；`batchRows`、`promptListText` 为 #123 兼容镜像。
- 图卡的成功媒体必须来自 **V3 服务器 RunProjection** 且具备真实 `mediaId` + `imageUrl`。缺少可核实身份时显示待核对，不把图型示意图宣称生成成功。
- 已提交任务使用 `studio2RunSnapshot.outputs[].slotId/candidateIndex/outputIndex` 冻结映射，草稿修改/排序不改变旧 Run 与媒体关系；失败重试仍调用既有 `runSingleRow(outputIndex)`。
- 保留原系列固定/AI 图型、参考素材、双画风融合、特殊 SC 参数、并发 1–4、每槽候选 1–4、执行成本、停止/恢复和历史画廊，紧凑表格切换仅改变视图。
- 四种意图入口是 **同一方案的任务视角**；本批在连续系列/同方案多张场景上优先完善编辑与交付。横评需用户逐卡选择真实资源，多平台通过明确点击设置未覆盖图卡的参考比例，不静默改写人工选项。

## 首批交付

1. 桌面左侧统一设置、右侧图卡方案板，窄屏单列；底部执行栏集中真实额度/候选输出、停止状态。
2. 默认卡片视图、可切回旧紧凑表格；全部/待核实/运行中/成功/失败/已锁定筛选。
3. 图卡内编辑主题并防抖保存；逐卡现有的参数/素材弹窗、复制、上移、安全移除确认；批量追加主题不覆盖现有图卡。
4. RunProjection 图卡内逐候选状态、真媒体放大与下载、终态失败候选定点重试，成功媒体 DOM 节点跨结果刷新复用。
5. 复用 #125 AI 结构化系列规划，规划不自动付费生图；沿用现有 PlanSlot 锁定/撤销机制。

## 可复现自动化

- Node：`tests/test_studio_series_ui_108.cjs`；覆盖 slotId 顺序、运行结果乱序、无媒体身份不误报、候选状态、重试门禁、锁定、过滤、XSS、安全回归以及脚本加载顺序。
- 真实 Chromium：`tests/smoke_studio_series_browser_108.py`；账户登录态、真实页面、图卡/表格切换、逐图编辑/复制/排序、平台比例、3 成功/2 失败/1 待核实的真实归属 V3 种子媒体、桌面/390px、主题焦点与图片节点稳定性；断言未产生新的付费生成请求。
- CI：`.github/workflows/checks.yml` `interaction-journey-regression` 门禁；截图/JSON 保存到 `artifacts/series-108-screen`。

## 仍需完整验收的后续范围

- 真实供应商收费生成和生产环境 PostgreSQL/对象存储/额度确认；本批 CI 的种子 V3 媒体 **不等于真实模型出图**。
- 完整 `同方案多张` 大于四候选的专用流程、横评公平性批量设置、不同平台构图引导；作品级 ZIP + 清单、跨用户权限现场验证。
- 5/20/100 槽位性能与分页/虚拟化；真实跨视图复杂 Graph 往返和草稿冲突演练属于 #107/#112。
- 整个 #108 在所有分期的真实浏览器/生产环境验收前不得以第一批 CI 关闭。
