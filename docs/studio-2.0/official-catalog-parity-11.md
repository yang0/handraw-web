# #11 官方编号权威与跨仓快照验收 · 2026-11-09

Web: https://github.com/yang0/handraw-web (`studio2`)
Skill: https://github.com/yang0/handraw-style (`feature/skill-web-unification-v1-20261107`)

## 权威规则与当前事实

- 官方画风/图型由 **网站管理员审核、编号、发布**。Skill 仓库的新增条目不是网站发布的证据。网站新增官方资源请用 `POST /api/admin/catalog/official`；导出工具 `ops/export_official_assets.py` 只导出已批准记录至待审目录，不直接写 Skill 源码或部署环境。
- `ops/refresh_content.py` 是历史 Skill→Web 快照脚本，现已默认拒绝陌生编号；显式 `--accept` 应视为一次性人工迁移授权，**不是日常发布通道**。不得为了“目录一致”盲目执行它。
- Web `plugin/content/catalog.json` 目前有 **367 画风 + 170 图型**；Skill 分支 `references/styles.json` 有 **368 画风**、`references/layouts.json` 有 **170 图型**，唯一编号漂移为 **FG-025**：Skill `Perler Bead Pixel Art`，网站无此条。旧差异 FG-024 / IG-037 / IG-038 已对齐。现阶段不把 FG-025 导入 Web，也不删除 Skill 的用户原始数据。
- 权威批准之前：**#11 必须保持 Open**。公网发布严格门禁仍为 **NO-GO**。CI 不能把已知待审漂移当作“目录完全一致”。

## 只读工具与防漂移策略

`ops/check_official_catalog_parity.py` 读取**本地** Web catalog 和 Skill 官方 JSON，绝不修改文件、数据库或网络服务。检查官方编号集、类型、重复、Web-only、Skill-only。待审核的 FG-025 以完整 Skill JSON 的 SHA256 指纹固定在 `ops/official_catalog_pending_11.json`，并明确关联 Issue #11。

**常规 CI 审计**：

`python ops/check_official_catalog_parity.py --skill-root external/handraw-style-catalog/skills/handdraw-style-prompter --report artifacts/official-catalog-parity-11.json`

当只有已登记且内容未变的 FG-025 时返回退出码 0，但输出 `status=pending_review`、`readyForRelease=false`，**不得视为已获官网发布授权**；未列入审核清单的新编号、同号不同类型、修改过的待审内容、过期例外及 Web-only 均返回 2，阻断所有 14 项 CI。

**发布 / Issue 关闭严格审计**：

`python ops/check_official_catalog_parity.py --skill-root external/handraw-style-catalog/skills/handdraw-style-prompter --strict`

在 FG-025 未网站审定、未同步一致并移除待审例外前必然返回 2。不能使用普通 CI 全绿取代此项。

现有 `.github/workflows/checks.yml` 中的 PostgreSQL17/S3 集成 Job：
1. 保留 **pin 到固定 SHA** 的 Skill CLI checkout，确保跨仓 Web/Skill 集成用的是已审定且可复现的客户端代码；
2. **另外 checkout 最新 Skill 开发分支，仅当作 JSON 数据读取**，运行本只读对账，检测后续目录变更，而非仅测试滞后的 pinned 资源；
3. 上传 `official-catalog-parity-11` JSON 工件，记录仅公开编号及异常集合，不导出私有数据。

## 完成 #11 的实际条件

1. 网站维护者决定 FG-025 是否官方收录。批准则通过 Web 管理员接口、人工审核资源来源/授权及图片后再网站→Skill 同步；不批准则将其从 Skill 官方发布目录移至保留原内容的待审区（不得直接删除创作）。
2. 两个仓库同一发布基线完成编号和类别对账，消除待审 manifest；`--strict` 本地及 CI 均通过。需保证不是仅通过 Web catalog 静态文件核对就忽视网站 DB 的 `catalog_assets.source_type='official'` 动态项（生产部署仍有额外要求）。
3. 保留专项测试、14/14 工程 CI 和真实受控 Web→Skill 导出证据；验收通过才在 GitHub 关闭 #11/Skill #17。

**本工程切片只实现防漂移、审计与发布阻断，不变更任何已批准的官方资源，也不宣称已经完成发布。**
