# Studio 2.0 · #111 Phase 12（SVG / 顶层状态 / 节点坐标）

日期：2026-11-09。基线：`studio2@aa140e098f5fcd78662e822f59e1e3b4d8047f80`。独立分支：`studio2-issue111-phase12-branch-isolations-20261109`。关联 #111、#11、#84、#112、Draft PR #131。

## 上一阶段留下的准确问题

Stage 11 在受限 3 次真实鼠标位移中观测到 39 条 Chrome Style Invalidation、3 次大范围 `UpdateLayoutTree`，`elementCount` 峰值 9,185；DOM 节点和浮动选中工具栏分别有 5 次属性变更。添加工具栏/覆盖层 `contain` 无稳态双 CPU 收益。**Chrome 的 `elementCount` 不是证明某个 CSS 规则重算了 9,185 个节点的证据**；任何路径都需要独立隔离与交叉验证。

## 三条可否证的根因假说

### A · SVG 连线

现有原生拖拽通过 `HandrawCanvasRenderer.createEdgeDragSession(...).update(...)` 计算增量连线。在 `demo/assets/studio-canvas-renderer.js` 中，路径变化通过 `path.setAttribute("d", d)` 应用。利用原产品既有、只在 `window.__HANDRAW_TESTING__===true` 下启用的 `canvasDragVisualProbeMode="no-edges"`，仍执行真实节点拖拽但**仅诊断性跳过 SVG 几何写入**，在每次 pointerup 强制真实全量渲染，并 Undo 验证 Graph / SVG / 图片一致性。

对照证据：原生 `svg-path.d` MutationObserver 计数、在 Chrome Trace 中 `UpdateLayoutTree` 的大事件数量与最大值、正常与 no-edges 的双 CPU Drag-only `RecalcStyleDuration`、`LayoutDuration`、rAF P95。

### B · 全局拖拽状态

在同一限时鼠标动作里，仅用白名单记录 `ic-studio-shell`、`ic-canvas-stage`、`ic-viewport`、`ic-world`、`ic-nodes-layer`、`ic-edges-svg` 顶层元素的 `class/style/transform` 变更数量；不保存真实类名、元素 ID、文本、样式原值。仅临时修改三个明确已审查的静态规则 `.ic-viewport.is-panning`、`.ic-studio-shell.is-wiring .ic-port-zone`、`.ic-studio-shell.edges-hidden ... .ic-edge-line` 的 CSSOM 选择器并精确恢复。匹配量与失效代价必须区分，类无变更也不能排除所有祖先依赖。

如果窗口内顶层 `class` 变更为 0，且屏蔽规则没有稳态收益，则当前“全局拖拽状态类导致重排”假说缺少支持；**这不是对其它隐式继承规则的证明或排除**。

### C · 节点坐标

原生 drag 在 pointermove 更新被选节点 `style.left` / `style.top`，并同步 Graph 坐标。使用仅测试模式 `no-card` 暂时抑制可视节点内联坐标写入，但仍在同一 pointerup 强制完整渲染、Undo 恢复；并将无效化 Trace 与 A 的 no-edges 做配对对照。**no-card 会破坏拖拽过程中的视觉反馈，绝不视作生产候选。** 此实验用于确定 Style 工作对节点绝对定位变更的敏感性，而不是直接提出隐藏节点方案。

额外 `no-overlay` 控制用于排除上阶段浮动工具栏位置变更对结论的干扰。

## 采集方法与工程纪律

- **真实而相同的负载**：本地 HTTP Studio 项目、隔离 SQLite、300 原生节点、150 SVG edge、120 张不同 SHA 的 WebP 且完全 decode；使用真实 Playwright mouse down / move / up。无付费生图请求；不访问第三方生产服务。
- **分离的归因 Trace**：每种代表性模式使用 3 次鼠标移动，CDP `invalidationTracking` 的 Trace 在 pointerdown 后开始、pointerup 前结束；内存 30MB 上限；原始数据绝不落盘。每种模式同时记录脱敏 DOM MutationObserver 聚合、顶层状态类变更数量。Trace 操作本身有额外成本，**不作为 A/B 性能 SLA**。
- **严格 A-B-A-B-A**：每种诊断模式分别在 1× CPU 与模拟 4× CPU 下各 3 个原始 A + 2 个隔离 B，逐次执行 12 次真实物理 mousemove，统计 **拖拽期间** Style、Style+Layout 和 rAF P95；两档 CPU、两次 B 都达到 Style 与联合指标至少 10% 改善、且 rAF P95 不回退超过 5% 方能称为稳态敏感性。即使达标也不等于可部署。
- **真实行为恢复**：所有视觉抑制只在 window.__HANDRAW_TESTING__ 生效；每轮 pointerup 强制 full render、实际 Graph 坐标与 DOM `left/top` 对账、SVG path/edge 数量、图片解码与 Undo 验证，重置测试模式和 CSSOM。不能从诊断性 bypass 得出生产优化的安全性结论。
- **输出**：`artifacts/studio-111-phase12/summary.json`，仅脱敏统计，无节点明文、用户提示词、URL、cookie、原始 trace。若 Chrome 无法给出节点源头映射，记录 `browserNodeIdentityProven=false`，不能把并发时间关联当因果证明。

本阶段不直接更改 `demo/assets/studio-app.js`、`studio-canvas.css`、`studio-canvas-renderer.js`。**没有两档稳态收益与视觉保真，绝不尝试推生产 CSS/JS。** 如果只有停画 SVG 或节点才变快，后续仍须设计保真替代实现并单独双 CPU 回归才可提案。

## #11 / #84 / #112 的并行真实环境验收夹具

新增只读 `ops/phase12_release_preflight_112.py` 以及单元测试：

- #11 核对 `ops/official_catalog_pending_11.json` 两项 Skill-only 提案 **FF-018 Low Poly Art、FG-025 Perler Bead Pixel Art** 保持 `awaiting_website_editorial_review`，检查当前 Skill main 目录并利用现有 `ops/check_official_catalog_parity.py` 的非 strict 对账报告。**不得自动发布或倒灌**；实际 Web 数据库已批准导出缺失时 `strictReleaseParityProven=false`。
- #84 复用 GitHub CI 已固定 Skill 客户端 SHA `dad8dad2d2af25bd9df45971a03a499461a723db`、真实 Skill CLI → 本地 HTTP → 一次性 PG17 → moto S3 的现有测试；只读检查固定客户端 SHA 与源文件存在。moto 不等于真实 R2/S3。
- #112 清单列明真实存储服务、Redis 多实例、计费与退款、PG17 真实 staging 备份恢复、低端实体 GPU/CPU、业务签核与回滚演练。CI 的本地 PG17 可以验证迁移和物理 dump/restore，但不能将其等同生产实施。未有外部证据一律 `readyForRelease=false`、`productionNoGo=true`。
- 只输出资源编号、公开提交 SHA、布尔前置条件及缺失清单，不读或持久化凭据值，不连接生产服务，不保存生产备份。独立 CI 上传 `artifacts/studio-phase12-release-preflight.json`。

## 交付验收要求

单独分支 14/14 → compare ahead>0/behind=0 → `studio2` 的 expected_sha + `force=false` 快进 → 同 SHA Push / PR #131 两套 14/14；PR 始终 Draft，`main` 不动，#111 / #11 / #84 / #112 不因测试交付而关闭，生产始终 **NO-GO**。

## 实测结果

本节必须在实际 Chromium Runner 完成后依据 `summary.json` 填写；不可预填收益、伪称已定位 9,185 元素的确定根因。
