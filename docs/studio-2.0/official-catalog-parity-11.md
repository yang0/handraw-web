# #11 官方编号权威与跨仓快照验收 · 2026-11-09

Web: https://github.com/yang0/handraw-web (`studio2`)
Skill: https://github.com/yang0/handraw-style (`main` 官方目录现状；跨仓 CLI 另 pin 固定 SHA)

## 权威规则与当前事实

- 官方画风/图型由 **网站管理员审核、编号、发布**。Skill 仓库的新增条目不是网站发布的证据。网站新增官方资源请用 `POST /api/admin/catalog/official`；导出工具 `ops/export_official_assets.py` 只导出已批准记录至待审目录，不直接写 Skill 源码或部署环境。
- `ops/refresh_content.py` 是历史 Skill→Web 快照脚本，现已默认拒绝陌生编号；显式 `--accept` 应视为一次性人工迁移授权，**不是日常发布通道**。不得为了“目录一致”盲目执行它。
- Web `plugin/content/catalog.json` 目前有 **367 画风 + 170 图型**；Skill `main@f4cba38b8682345168ccbcd80cf4f5a3d9feb761` 的 `references/styles.json` 有 **369 画风**、`references/layouts.json` 有 **170 图型**；两个 Skill-only 漂移为 **FF-018**（Low Poly Art）和 **FG-025**（Perler Bead Pixel Art），网站均无此条。旧差异 FG-024 / IG-037 / IG-038 已对齐。现阶段不把 FG-025 导入 Web，也不删除 Skill 的用户原始数据。
- 权威批准之前：**#11 必须保持 Open**。公网发布严格门禁仍为 **NO-GO**。CI 不能把已知待审漂移当作“目录完全一致”。

## 只读工具与防漂移策略

`ops/check_official_catalog_parity.py` 读取**本地** Web catalog 和 Skill 官方 JSON，绝不修改文件、数据库或网络服务。检查官方编号集、类型、重复、Web-only、Skill-only。待审核的 FF-018、FG-025 分别以完整 Skill JSON 的 SHA256 指纹固定在 `ops/official_catalog_pending_11.json`，并明确关联 Issue #11。

**常规 CI 审计**：

`python ops/check_official_catalog_parity.py --skill-root external/handraw-style-catalog/skills/handdraw-style-prompter --report artifacts/official-catalog-parity-11.json`

当只有已登记且内容未变的 FG-025 时返回退出码 0，但输出 `status=pending_review`、`readyForRelease=false`，**不得视为已获官网发布授权**；未列入审核清单的新编号、同号不同类型、修改过的待审内容、过期例外及 Web-only 均返回 2，阻断所有 14 项 CI。

**发布 / Issue 关闭严格审计**：

`python ops/check_official_catalog_parity.py --skill-root external/handraw-style-catalog/skills/handdraw-style-prompter --approved-export-dir /private/reviewed-web-official --strict`

在 FF-018 / FG-025 未网站审定、未同步一致并移除待审例外前必然返回 2。不能使用普通 CI 全绿取代此项。

现有 `.github/workflows/checks.yml` 中的 PostgreSQL17/S3 集成 Job：
1. 保留 **pin 到固定 SHA** 的 Skill CLI checkout，确保跨仓 Web/Skill 集成用的是已审定且可复现的客户端代码；
2. **另外 checkout 实际 Skill `main`，仅当作 JSON 数据读取**，运行本只读对账，检测后续目录变更，而非仅测试滞后的 pinned 资源；
3. 上传 `official-catalog-parity-11` JSON 工件，记录仅公开编号及异常集合，不导出私有数据。

## 完成 #11 的实际条件

1. 网站维护者分别决定 FF-018 和 FG-025 是否官方收录。批准则通过 Web 管理员接口、人工审核资源来源/授权及图片后再网站→Skill 同步；不批准则将其从 Skill 官方发布目录移至保留原内容的待审区（不得直接删除创作）。
2. 两个仓库同一发布基线完成编号和类别对账，消除待审 manifest；`--strict` 本地及 CI 均通过。需保证不是仅通过 Web catalog 静态文件核对就忽视网站 DB 的 `catalog_assets.source_type='official'` 动态项（生产部署仍有额外要求）。
3. 保留专项测试、14/14 工程 CI 和真实受控 Web→Skill 导出证据；验收通过才在 GitHub 关闭 #11/Skill #17。

**本工程切片只实现防漂移、审计与发布阻断，不变更任何已批准的官方资源，也不宣称已经完成发布。**


## 2026-11-09 · 发布版官网 DB 官方资源核对与只读导出补强

`catalog.json` 是静态官网目录，**并不包括网站数据库里管理员后来批准的 `source_type=official` 条目**。仅比较它与 Skill 会出现静态一致但生产官网 DB 仍缺 Skill 编号的假阳性。现在 `ops/check_official_catalog_parity.py` 支持 `--approved-export-dir` 同时读取官网 DB 已发布官方资源两份 JSON；合并静态 catalog 后，拒绝静态与动态重复编号、动态内部同号异类、Web-only、Skill-only 和未审 FG-025。报告增加 `approvedExportChecked`、`webDynamicApprovedCount`、`dbAuditRequired`；未提交 DB 导出时普通 CI 仍可完成编码漂移审计，但 `readyForRelease=false`，且 `--strict` **必须失败**。报告的“静态目录编号一致”不再自动等于“生产发布已通过”。

官网→Skill 导出器 `ops/export_official_assets.py` 同时支持：
- 开发用 SQLite：`--db /private/approved-website.db`，以 SQLite `mode=ro` 打开，不执行迁移。
- 正式 PG17：`--pg-dsn-env HANDRAW_OFFICIAL_EXPORT_PG_URL`，**从私有环境变量**读取有只读权限的 DSN，不在命令行/日志展示连接串；显式开启 `REPEATABLE READ READ ONLY` 快照，无写操作。
- 两者统一只读 `catalog_assets.source_type='official' AND status='published'`；未发布/隐藏/待审条目**绝不导出**。导出目标必须是**新的空目录**，阻断旧导出残留隐藏资源；即使 DB 新增官方记录为 0，也产生受审计的空 `styles.json` 与 `layouts.json`。

授权操作员在隔离环境的操作示例（**不含真实凭据/业务媒体**）：

```bash
# 由 DB 权限管理员事先配置 HANDRAW_OFFICIAL_EXPORT_PG_URL
python ops/export_official_assets.py \
  --pg-dsn-env HANDRAW_OFFICIAL_EXPORT_PG_URL \
  --skill-root /private/reviewed-handraw-style/skills/handdraw-style-prompter \
  --out /private/reviewed-web-official

# 不会写 Web/Skill，只作严格只读对账
python ops/check_official_catalog_parity.py \
  --skill-root /private/reviewed-handraw-style/skills/handdraw-style-prompter \
  --approved-export-dir /private/reviewed-web-official \
  --strict
```

必须先人工确认原始数据库确为已批准的、与对应部署 SHA/Skill 基线匹配的权威源；本工具不能验证数据库凭据或运营审批真实性，也不能自行合并导出到 Skill。复核导出结果、图片授权及付费定义保护后由维护者在 Skill **独立分支**审阅并同步。FF-018 与 FG-025 仍未官网审批，不得自动导入官网；因此本轮工程代码验收即使全绿也必须保持 #11 Open、`--strict` 未通过、生产 NO-GO、PR #131 Draft。真实 PostgreSQL、跨仓现场签核仍属于 D 级证据，不能用本地 SQLite/CI 代替。

## 2026-11-09 · Skill main 新增 FF-018 的漂移补漏

前一轮 CI 的目录数据 checkout 指向 `feature/skill-web-unification-v1-20261107`，仅包含 FG-025，因此曾把“最新 Skill”误称为该分支。已核验当前真正的 Skill `main@f4cba38b8682345168ccbcd80cf4f5a3d9feb761` 有 369 种画风、170 种图型，较 Web 静态已审批目录多两种画风：`FF-018 / Low Poly Art` 和 `FG-025 / Perler Bead Pixel Art`。两者已有 Skill 仓库图片和定义，**不能因此推导出网站官方发布授权**。共同的 537 个资源名称完全匹配。

- CI `production-storage-integration` 保留精确 SHA pin 的 Skill CLI 可执行客户端，另外以数据形式 checkout **Skill `main`**，只解析 `references/styles.json`、`references/layouts.json`，记录准确 checkout SHA，确保 FF-018 等后续变更能进入审计。新资源、篡改完整条目或同号异名都会阻断普通 CI。
- `ops/official_catalog_pending_11.json` 对 FF-018 与 FG-025 **分别锁定完整 JSON SHA256**、Issue #11 和编辑待审状态，不是自动发布白名单。严格 `--strict` 即便候选数只有 1 项也继续失败。
- `ops/check_official_catalog_parity.py` 新增 `mismatchedName`（报告仅公布编号），即使 Web、Skill 类型和编号一致，也拒绝展示名称不一致的资源；DB 新增的已发布官方资源同样检查 `generation_name` 与 Skill 名称一致。**这只覆盖名字，不替代提示词、图库授权和实际内容语义的人工对账**。
- Skill main 本身是可变化的发布分支；审计运行记录 checkout SHA。仅当 Web 已批准并发布、Skill 合入并在同一个正式发布基线上通过 `--strict` + 真实官网 DB 审核导出，才能关闭 #11/#17；普通 CI 允许审计后确认的 pending 状态，仍然标记 `readyForRelease=false`、生产 NO-GO。

本阶段不能擅自将 FF-018、FG-025 回填官网目录，也不能直接删除 Skill 源素材或修改 Skill main。
