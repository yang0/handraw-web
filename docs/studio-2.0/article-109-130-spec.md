# Studio 2.0 · 文章配图独立编辑器（#130 设计规范 / #109 实施验收）

> 2026-11-08 · Epic #101 · 作图、系列、文章、画布四入口
>
> **文章配图是独立创作任务，不是另一套生图系统。**
> 正文 ArticleDocument 是唯一内容写入源；PlanSlot 是配图位置/参数的可编辑投影；Graph 是只读关联投影；Run/RunItem 是唯一执行与计费事实；Work 公共展示不包含私有正文或参考图。

## 一、信息架构与所有权

| 对象 | 权威拥有者 | 唯一写入口 | 不得执行 |
|---|---|---|---|
| 文章正文、标题、章节与光标 | Article 编辑器 / Project.draft.article | 文章编辑器 / 显式导入覆写 | GraphPatch 修改 markdown、历史图卡反写正文 |
| 图卡 anchorId/slotId、用途、位置、比例、资源、锁字段 | Project.draft.plan(kind=article) | 文章图卡及统一 AI 方案审查 | 用解析索引重新生成随机标识 |
| 画风/图型/比例与授权参考素材 | CreationSpec + slot.overrides | 统一资源选择器 | 未授权公开私有 MediaRef |
| 生成批次与失败单图 | Run/RunItem (Issue #119) | 既有 article runPool + generateSinglePlanCard | 本地将已提交任务标记未提交、重复收费 |
| 本机待提交草稿与服务端确认 | #103 ProjectClient CAS/outbox | 账号隔离缓存 + Project PATCH | 用本地写入冒充 cloud synced |
| 历史/广场 | GenerationHistory / public Work (#84) | 既有生图发布机制 | 将完整 article.markdown、附件、私有 URL 写到公开元数据 |

**同一 articleId 的 ID 规则：** documentId=articleId，正文 revision 独立于 Project CAS revision；Plan revision 独立于正文 revision；每张卡拥有稳定 slotId 与 anchorId，移动位置仅改锚点的 afterBlockIdx，不重建 Run。Plan.documentRevision 必须与 ArticleDocument.revision 一致。Project 的一次 PATCH 原子写入 article+plan+creationSpec，服务端拒绝失配或陈旧 revision。未通过权限验证的 mediaId 一律不能上传进私有 Project。

## 二、桌面与窄屏线框

### Desktop 1440px

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ HANDRAW / 文章配图      [编辑 | 预览]         [打开项目] [导入] [新建]       │
├───────────────┬──────────────────────────────────────────────────────────────┤
│ 文章列表/章节  │  标题输入                                   字数/版本        │
│ ● 第1节       │  # 标题                                                    │
│   └ 锚点01    │  段落一…                                                    │
│ ● 第2节       │  ┌ 插图卡 · slotId=...  📍第1节后 ┐                           │
│   └ 锚点02    │  │ 主题 画风 图型 比例 推荐理由   │                           │
│               │  │ [调整位置] [仅生成此图/重试] │                           │
│ 云端状态      │  └─────────────────────────────┘                           │
├───────────────┴──────────────────────────────────────────────────────────────┤
│ 已保存本机 / 正在同步云端 / 云端已确认 / 冲突      [AI规划] [生成剩余] [导出] │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Narrow ≤620px

```text
┌─────────────────────────────────┐
│ 文章配图       [编辑/预览] [菜单] │
├─────────────────────────────────┤
│ 标题                             │
│ 正文分段，可持续输入               │
│ ┌ 插图卡（纵向） ┐                 │
│ │ 主题/比例/资源 │                 │
│ │ [单张生成/重试]│                 │
│ └────────────────┘                 │
│ [展开章节/历史]                   │
├─────────────────────────────────┤
│ ☁ 状态/重试         [规划][导出]  │
└─────────────────────────────────┘
```

不在窄屏强制展示 Graph；主要操作可单手触达，卡片无横向滚动，正文 textarea 永不因后台同步冻结。

## 三、状态、恢复与错误矩阵

| 场景 | 用户可见状态 | 用户可选动作 | 系统保证 |
|---|---|---|---|
| 空白 | 填入正文/导入 | 粘贴 / 新建 / 导入 | 不自动创建付费 Run |
| 导入中 | 解析进度、可取消 | 取消/继续本机编辑 | 解析失败不改草稿；成功直接替换，无常规审阅 |
| 导入时仍在编辑 | 内容版本变化 | 保留当前/显式使用导入版本 | 不静默覆写新正文 |
| 编辑中 | 本机未保存 → 已在本机 | 继续编辑 | 不把 local_only 写成 synced |
| AI 规划中 | 章节分析/方案生成/审查中 | 取消 | 允许正文继续输入、旧卡片不被篡改 |
| AI 返回过期 | 新旧正文不一致及差异 | 保留旧卡片 / 重新规划 | 旧响应不得应用 |
| 方案建议 | 各 slot 位置/主题/理由/参数 | 勾选、换位置、修改资源或锁定 | 不修改原文 |
| 正在生成 | 每卡单独 generating、Run ID | 仅取消未提交 / 查看历史 | 网关超时不重发不同 key |
| 部分失败 | 成功卡仍展示；失败卡 error | 仅重试失败图卡 | 不重跑整篇 |
| 离线/弱网 | 本机已保存、待云端同步 | 重试/联网自动恢复 | frozen outbox & CAS |
| 多窗口冲突 | conflict / serverRevision | 查看差异、保留副本、丢弃本机 | 不使用 last-write-wins |
| 图片失效 | 图卡占位、明确失效提示 | 仅此卡重试/重新关联 | 其他图与正文无变化 |
| 预览与导出 | 正文原样排版、锚点定位图片 | 预览 / Markdown / ZIP | 只导出用户选定内容，失败不会触发收费生图 |

## 四、交互约束与文案

- **导入成功**直接替换当前编辑器正文；仅“导入开始后又编辑”的并发冲突允许额外选择，提示“导入期间正文已变更，是否仍替换？”；服务错误原文保留。
- **AI 规划**在内容变化时提示“正文已更新，旧方案没有应用”，提供重新规划。应用之前必须复核 documentToken/title/markdown/revision 和旧 Plan 版本。
- **生成**：一次选择多图默认并发 2，按 slotId 追踪；未完成的卡片是可重试集合；成功图卡不能因另一张失败而重新生成。
- **导出**：ZIP 含 article.md、preview.html、images/；原始正文取 ArticleDocument，不取 planNode.data.markdown。插图按固定 anchorId/afterBlockIdx 定位；失败卡标记缺图，不自动开始付费生图。
- **安全**：新的公开作品默认只暴露已生成图及获授权的可公开元数据；文章正文、MediaRef/私有参考 URL 与完整 Prompt 不自动进入公共 Work。

## 五、字段/接口与复用映射

| UI 操作 | 既有/新增模块 | 数据流 |
|---|---|---|
| 导入、编辑、章节 | `studio-app.js` ArticleEditor + TaskJourney | ArticleDocument 唯一写入 |
| 方案审核与锚点 | `studio-ai-plan.js`, `studio-article-integration.js` | CreationSpec/PlanSlot，稳定 slotId/anchorId |
| Project CAS | `studio-project-sync.js`, `studio-article-project-109.js`, `/api/studio/projects` | frozen outbox / optimistic baseRevision / 409 |
| 画布投影 | `studio-article-integration.js` | 只读 linkArticleGraph / 不修改正文 |
| 生成/重试/恢复 | `generateSinglePlanCard` + `article-workbench.runPool` + V3 Run read | 共用 Run/RunItem，不新增文章任务表 |
| 预览/导出 | `renderArticlePreviewPage` + `/api/studio/export-zip` | 当前 ArticleDocument + 卡片位次 |
| 历史与公开 | #84 generation history / Work | 排除原文与未授权素材 |

## 六、走查与自动验收依据

- Chromium：全量导入/编辑 → 规划与锚点 → 本机/云端 CAS → 离线刷新 → 预览与 ZIP 导出。
- 双标签：两个相同 Project baseRevision 编辑，第二个 409；用户显式解决冲突。
- 过期 AI：异步响应后正文变更、取消、浏览器刷新后旧响应不得写入新版本。
- 单图：一张成功、一张失败，再重试只能产生一个相应 RunItem，公共 Work 仍按任务封面单卡展示。
- 数据隐私：用户 B 不能 GET 用户 A Article Project；公开作品结果不包含全文及私有媒体引用。
- CI：`tests/smoke_studio_article_browser_109.py` 纳入 `interaction-journey-regression`，禁止真实生成 POST，验证 14/14 全绿。

关联：[#130](https://github.com/yang0/handraw-web/issues/130) · [#109](https://github.com/yang0/handraw-web/issues/109) · [#103](https://github.com/yang0/handraw-web/issues/103) · [#124](https://github.com/yang0/handraw-web/issues/124)
