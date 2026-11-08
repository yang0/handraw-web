# 历史 P0/P1 #84/#85/#86/#87/#88/#90：实施、受控证据与开放风险对账

> 仓库 `yang0/handraw-web`，本轮从 `studio2@75fe03d22b2b96cb1aa6ee623f57cb4b53fea4dc` 切出
> `studio2-p0p1-84-85-86-87-88-90-audit`。所有测试使用临时 DB、mock 网关、
> 本地 HTTP / 真实 Chromium、CI PG17 + Redis7 / 模拟 S3，不调用付费供应商。
>
> **判定纪律**：代码存在 ≠ 测试执行；14/14 CI（验证分支、目标 Push 和 Draft PR）
> 必须以 GitHub 同 SHA Job SUCCESS 为证；所列“受控证据”不等于用户生产部署 E2E。
> 禁止触碰 main，PR #131 保持 Draft。存在 D 级未验收的 Issue 必须 Open。

## #84 · V3 单任务一作品、多媒体与封面

已有权威归一化路径：`backend/generation_v3.py` 的
`generation_runs`（逻辑任务）→ `generation_items` / `media_assets`
→ `works(run_id UNIQUE)` → `work_media`。默认封面选首个有序成功
slot；作者手动选封面在后续异步结果中保留；后续任务回调不得使被删除/
隐藏的图片重新公开。广场仅按 Work 计数、卡片展示封面。
`studio_generations` 仍承担计费执行/退款事实，不是 Work 权威库。

已有受控用例：
- `tests/test_generation_v3.py`：乱序/重复结果、首图封面、作者封面、
  失败 slot、全失败无作品、已删除作品不可复活、跨用户隔离。
- `tests/test_studio_series_run_contract.py`：多 slot/多候选和部分成功不复制 Work。
- `tests/test_skill_web_bridge.py`：上传、恢复、用户权限、多图与历史只一条 Run。
- `tests/test_studio_skill_pg_s3_112.py`：**真 PG17 + Moto S3 协议模拟**、
  6 图第 4 张中断、重试补缺、一次公开 1 Work/6 Media、空缓存对象恢复与
  审核下架断权。不是独立 Skill 客户端或者真 S3/R2。
- `tests/test_stage5_plaza_batch_folding.py` / 浏览器和布局专项用例。

**决定：暂不关闭 #84 的完整产品验收要求**。仍缺真正 Skill 仓库
调用者、部署的 Redis/S3/R2 多节点、实供应商计费/退款账本、跨移动端 GIF、
实际授权与生产数据安全验收。该剩余 D 级与 #112 同步推进，不能冒称 Go。

## #85 · 个人创作资源/批量真实进度/文章导入

- `main-app.js` + `cloud-center.js` 与 `user_library.py`
  已提供「个人主页→创作资源→我的图库」、按属主读取/分类/编辑名称与类别、
  错误编号和同 UID 重试。
- `studio-app.js` 有界并发可配置 1–4（默认 3）、单 slotKey/requestId、
  已成功/失败计数、取消未提交任务、远端 Run 状态投影与乱序更新。
  `studio-batch.js` 的进度不是仅靠重绘乐观图数；历史保留批次定位。
- `article-workbench.js` / `document_importer.py` 与 #109
  文档直覆编辑器、导入状态与 CAS 保护代码已有，不恢复文档“审阅弹框”。
- `tests/test_batch_concurrency_contract.cjs`、
  `tests/test_batch_progress_incremental.cjs`、
  `tests/test_batch_stop.cjs`、`tests/test_studio_series_run_contract.py`、
  `tests/smoke_studio_series_browser_108.py`、
  `tests/test_profile_private_gallery.cjs`、
  `tests/smoke_p0_gallery_upload_browser_91.py`、
  `tests/smoke_studio_article_browser_109.py` 互补覆盖。
- 本轮 async 删除确认补负向用例：取消不发 DELETE API、确认后才删。

**D 级限制**：供应商真并发/停止反馈、外部 Web↔Skill 上传、弱网大文章导入
需 #112 实际环境验收；受控回归不得冒充实际供应商成功。

## #86 · 历史/导航条真实宽度

`studio-canvas.css` 中早期的 1140px 是旧规则，文件末尾已有
`--ic-library-max-width: none` + 共用 `--hw-page-gutter`
高优先级覆盖。实际是否生效以本轮
`tests/smoke_legacy_library_dialogs_86_87.py` 测量为准：
真实 Chromium 1440/1360/1200/900/390 像素下，导航 content 边界、
历史筛选条、历史卡片容器、工作流工具栏与卡片容器逐点比较；
历史 5/4/3/2/1、工作流 3/2/1 列，三卡首行横向排列、无溢出，
记录坐标和截图至 `artifacts/legacy-86-87/`。
同时保留 `tests/test_studio_history_masonry.cjs`。

## #87 · 所有第一方原生弹窗治理

本轮新增 `demo/assets/app-dialogs.js`、`plugin/public/app-dialogs.js`；
四个 Web 入口和独立插件 `plugin/public/index.html` 均显式加载
同版异步对话框。提供真正的取消（false/null）、可选输入、
Escape、Tab 焦点约束、关闭后焦点恢复及移动端适配，不做
`confirm = () => true` 或改写原生浏览器全局函数。

- 已逐处替换的第一方文件：
  `admin-app.js`、`cloud-center.js`、`curation-ui.js`、
  `device-auth.js`、`forum-app.js`、`main-app.js`、
  `messaging.js`、`shared.js`、`studio-app.js`、
  `studio-batch.js`、`studio-make-image.js`、
  `plugin/public/portal.js`；包括管理退款/审核、删帖、
  弹窗输入、图库、账号解绑、批量及图片创作清空。
- `tests/test_native_dialogs_87.cjs`：遍历 first-party
  `demo/assets/*.js` 与 `plugin/public/*.js`，每个文件 JS
  语法解析、扫描原生 `alert/confirm/prompt` 调用、
  检查所有 HTML 入口加载、插件与主站对话框字节相同。
  测试夹具、文档和第三方库**不算产品调用点**，不对其生造修改。
- `tests/test_profile_private_gallery.cjs`：取消不删除、确定后再发起。
- Chromium 通过真实图片创作 Reset 取消/确定，站内输入框
  Escape 与 Enter、没有浏览器原生 `dialog` 事件。

**范围限制**：静态扫描可保证受管第一方 JS 没有直接原生调用，
但部署缓存、外部第三方脚本与所有业务角色的线下逐一点击仍在发布
#112 走查中，不把模拟卡片/一次 E2E 当所有终端验证。

## #88 / #90 · 推荐偏置、非 JSON、502 / 网关失败

`backend/batch_plan_routes.py`：
- 实时授权图型目录全量提供、图型名称和目录描述；
  AI 模式没有 SC-001/SC-006 首选、few-shot 或 first-N 截断；
  每个子主题独立接受语义上合适的布局，非法或矛盾编号返回错误，
  绝不静默伪造模板推荐。固定模式保留确定性离线模板。
- 启用 `chat(..., json_mode=True)`；只允许完整合法 JSON、
  gateway `<escape>` / Markdown Fence，拒绝随意找第一个大括号。
- 严格校验返回数量、重复/空主题、合法图型和 code/name 一致性。
  后端公开错误区分 502 `batch_plan_ai_invalid`
  （JSON/语义问题）与 503 `batch_plan_ai_unavailable`
  （网关/超时/上游不可达），并保留 requestId。
- **本轮真实缺陷修正**：若 `chat()` 直接抛异常，
  改为安全的 `stage=upstream reason=exception` 及 503；
  malformed metadata 和非文本响应统一分类，不能回落成 500；
  logger 只记 mode/count/stage/reason/type/长度，不记录主题、
  模型全文、密钥。
- `tests/test_batch_plan.py` 扩展模型抛异常、
  上游 502/无效 JSON/错类型、固定模式回退、
  120 条目录尾项和逐槽语义 ID 的 Mock HTTP 回归。

**D 级限制**：不对真实付费供应商的“审美推荐质量”作模拟外推；
真实 429/502 和样本质量由 #112 的外部网关验收补证。

## 收口程序

1. 以最新唯一 SHA 验证本分支 14/14 CI，检查上述每个新增测试 Job。
2. 对 GitHub 的开放 Issue 写入“实际原有代码、此次缺陷、验收步骤、
   测试 URL、实环境阻断项”；满足**工程验收**才关闭。
3. 分支落后 `studio2` 为 0 且领先提交已通过同 SHA CI，
   使用非强制 `update_ref(expected_sha=旧SHA, force=false)` 快进；
   再分别校验目标 Push 与 Draft PR #131 同 SHA 的 14/14 CI。
4. #84 与 #112 如有未验证的 D 级强制验收项，继续保持 Open；
   不动 main、Draft PR 不准转换 Ready / Merge。
