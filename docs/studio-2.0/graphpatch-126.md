# Issue #126 · GraphPatch v1 API、审阅/确认/回滚合同

适用代码：backend/studio_graph_patch.py、backend/studio_projects.py 102 migration、demo/assets/studio-graph-patch-126.js、studio-canvas-ui.js、studio-app.js。

## 业务安全不变量

1. 唯一可写目标：**已云端确认、authority=graph 的本人 Project.draft.graph**。Spec/Article 不是 GraphPatch 的隐式写入权威；必须先由现有视图切换/云保存机制显式建立 Graph 权威。
2. 实际 Run/RunItem/Work/Artifact、已完成媒体的存储和网关计费**绝不写入**。新增 output_control 只是潜在待运行分支，预览与应用都不会提交生成请求。
3. Preview 是用户须审阅的 **Diff 提案**，不写 Graph。本人的候选资源在同一数据库事务内校验授权、MediaRef 归属、字段白名单、DAG 无环和 512 KiB 草稿上限。
4. 新增/删除节点与连线及参数修改是白名单结构操作；不能更改既有 output_display、article_plan、拥有 RunSnapshot/媒体/运行中状态的节点。删除有连线的节点必须先显式删除对应边。
5. 锁定的字段返回 conflicts 且 canApply=false；禁止隐式解除锁、跳过预览或覆盖用户布局。
6. 预览生成 128-bit+ 不可预测审阅 ID，数据库持久化 owner + project + ProjectRevision + graphRevision + 原 Graph + operations + 审阅摘要。有效期 30 分钟；应用按用户确认且 CAS 一次性事务执行，重复调用幂等。审阅 ID 并不是公共共享链接。
7. 撤销只允许同一用户对**已经应用且尚未发生其他项目写入**的审阅记录执行；撤销也产生新的 Project/graphRevision（版本单调递增）。有后续变更即返回 409，拒绝覆盖别人或另一标签的新数据。
8. AI 指令只获取用户主动输入文本、Graph 节点/边 ID 和类型、所选范围、用户当前可用画风/图型的**授权 ID 与展示名称**。不向模型发送 Graph 的原文主题、私有媒体 URL、Prompt 内容、运行 ID、黑盒画风定义或历史结果。
9. 模型调用在数据库写事务之外执行；返还操作后重新取得写锁并校验 Project+Graph 版本，旧回复必须拒绝。每天有独立 AI 规划次数限制。任何错误不修改 Project。
10. #112 真实供应商、正式对象存储与数据恢复门禁仍为 NO-GO，本功能仅证明受控环境结构安全。

## 接口版本 1

| 方法及路径 | 请求 | 返回及副作用 |
| --- | --- | --- |
| GET /api/studio/graph-patch/styles | 网站登录 Cookie | 用户可用画风 ID 和展示名（不含受保护 Prompt） |
| POST /api/studio/graph-patch/preview | projectId、baseRevision、graphRevision、mode、scope、selectedIds；附 preset/styleIds 或 instruction 或 operations | reviewId、canApply、summary、逐项 diffs、conflicts、costImpact；只新增审阅记录，不写 Graph |
| POST /api/studio/graph-patch/apply | reviewId、confirmed=true | 单次 CAS 生成新 Graph + projectRevision / graphRevision；受保护的旧成果保持 |
| POST /api/studio/graph-patch/undo | reviewId、confirmed=true | 即时撤销且 CAS 生效；有并发编辑则 409 |

### 操作对象

- addNode：node 对象，要求合法 ID、已允许的节点类型、几何坐标和受控 data 字段。
- removeNode：id，禁止任何已有 Run/Artifact/结果节点；已连接节点需先逐边删除。
- setNodeData：id、field、value，按节点类型字段白名单校验、锁定参数拒绝、资源从服务端生成 canonical ResourceRef。
- addEdge：edge 对象 id/from/to，所有目标必须存在，不得自连、不得双 ID、不得形成拓扑环。
- removeEdge：id，禁止破坏已完成成果与运行证据的连接。
- scope=project：在本人 Project Graph 内按白名单增改删。
- scope=selection：对既有节点的直接改/删只能限于 selectedIds；移除边须触及被选子图；新连线须与所选或本补丁新节点关联。提交时服务器再次检查。

### 三个预设

- seasons：以所选文案或原主题派生春夏秋冬 4 个文本节点及对应 4 个生成设置节点、输入边；如选择已有成图，则可以将旧成图作为新分支输入，**旧媒体不改变**。
- platforms：基于现有文案和授权画风增加公众号头图 2.35:1、小红书 3:4、抖音竖图 9:16 三条生成设置分支。
- style_compare：用户明确选择两个不同的已授权画风 ID，产生两套风格参数/生成设置和共享文案连线；服务端验证每个 ID 的权限并构造 ResourceRef。

### 费用解释

costImpact.additionalPotentialImages = 新增的潜在生成张数上界（非实际完成数）；estimatedAdditionalCredits = 基于网站当前每张积分规则估算的增量；chargedNow=false、generationStarted=false。实际生成须另由原 V3 网关路径/额度门禁处理。不得将 estimate 直接记账。

### 冲突及异常

- graphpatch_review_missing / expired：无效、跨用户或过期审阅，拒绝应用。
- project_revision_conflict / graphpatch_revision_conflict：另一个标签或设备修改，要求重新加载/审阅，不自动重试提交。
- graphpatch_scope_forbidden / locked_field：选区外修改或锁定字段，阻止应用。
- graphpatch_cycle / invalid_edge / protected_node / protected_field：拓扑、已有成果或运行状态受保护。
- graphpatch_resource_forbidden / project_media_forbidden：资源使用权限或私有媒体归属不足。
- graphpatch_ai_invalid_json / graphpatch_ai_schema：模型生成了非法结构，不会静默改为固定方案。

## 测试与审核证据

- Python schema/权限/资源/DAG/锁定/作用域/幂等/CAS/并发 AI/撤销：tests/test_studio_graph_patch_126.py
- Node 前端 Diff XSS 转义、作用域与 app 装载契约：tests/test_studio_graph_patch_126.cjs
- 真 Chromium 与临时 HTTP/SQLite：tests/smoke_studio_graph_patch_browser_126.py（真实审阅、确认、原 Run 保留、撤销、画风合法列表及无付费生成 POST）。
- GitHub Checks 在原有 14 个 Job 中追加三项门禁，截图与 JSON 归档在 artifacts/graphpatch-126。
- PostgreSQL migration 102 必须在正式发布前经 #112 正式数据/备份恢复门禁验证，不因 SQLite 受控自动化通过宣称生产上线。
