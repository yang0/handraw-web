# #21 · 作者自建画风/图型与 Web ↔ Skill 双向同步（Studio 2.0）

**目标分支：** `studio2`；跨仓 Skill 为 `yang0/handraw-style`。
**权限：** 私有资源只有作者可读取完整定义、生成和收藏。没有“自动发布到社区/官方频道”的隐式操作。

## 一、统一数据权威，避免重复数据库模型

- **唯一可写权威**：现有 `skill_personal_resources` + `skill_resource_changes`，UUID 主键、用户所有权、`revision` CAS、增量游标、软删除与 tombstone。
- **Web 专用查询模型**：新增迁移 `103_author_private_resource_projection` 中的 `user_resources` 表，存可解析的 `code`、属主、类别、中文定义、`revision` 及删除状态；已有数据只从 Skill 权威表回填，日常写入由同一事务 `_sync_web_read_model` 更新，**禁止独立修改此表**。
- **编号规则**：画风 `USR-S<32 位大写 UUID hex>`，图型 `USR-L<32 位大写 UUID hex>`；稳定、全局唯一，绝不消耗官方 `FA/FG/IG` 等系列号码，也不与论坛已有短 `USR-Sxxx` 投稿号混淆。客户端提交原始 UUID，**编号由服务端计算并返回**。
- 已有 `resource_registry.resolve` 统一解析到 `user_resources`，仅当前登录作者 `canRead/canUse/canCollect`。被删除、外部用户、匿名均不可解析私有定义。
- 创作台的 `build_boot_payload` 将作者私有资源加入其 `myResources`；`shared.js::rebuildResourceIndexes` 原有聚合即可选择，不建第二份画风索引。
- `studio_resources.check_resource_ref` 严格校验 `source=private` 与 `revision`；生成时仅服务器按属主许可把定义注入网关提示词，公共作品和跨账号查询不得返回私有资源定义。

## 二、双向同步协议（现有 API，新增稳定 code）

**Skill/网站提交/更新：**
```http
PUT /api/v1/me/resources/{uuid}
Authorization: Bearer <library-scope token>    # 或网页登录 Cookie
Content-Type: application/json
```

```json
{
  "id": "c0a801a5-10f6-496a-9014-3ff4c2d06a4b",
  "kind": "style",
  "name": "原创柔和纸纹",
  "definition": {"zh": "中文定义", "en": "English definition"},
  "license": "本人原创",
  "examples": [],
  "version": "1.0.0",
  "visibility": "private",
  "schemaVersion": 1,
  "baseRevision": 1
}
```

首次创建无 `baseRevision`；更新必须携带当前版本。重复相同内容返回 `unchanged`、版本不加一；不同内容使用旧版本将 **409 conflict**，响应含最新受保护的自身版本。别人 UUID 返回 404。公开 `visibility` 必定拒绝，不能从个人资源同步隐式发布社区。

**网站/Skill 拉取：** `GET /api/v1/me/resources?since=<cursor>&limit=100`，按递增 `change_seq` 增量推送变更和软删除；`DELETE /api/v1/me/resources/{uuid}?baseRevision=N` 由当前作者执行 CAS 软删除。旧版 SDK 不附 code 时客户端可从 UUID 推导一致的默认 code；新版 Skill 在 `resources push` 与 `resources restore` 校验网站回执 code 正确，否则拒绝本地状态更新，不会抹掉有本地修改的定义（除非显式 `--force`）。

## 三、论坛“未收录免费”与私有自建的区别

已通过论坛投稿但尚未收录的 **免费** 画风/图型沿用原 `curation_submissions`，仍允许所有人查看定义、登录用户合法试用和收藏。用户纯私有自建资源不经过投稿/审核，只有作者能用；私有资源同步不改变网站“作品全部公开”的作品策略，也不将资源定义公开。付费社区资源的秘密定义继续仅由后端注入，Skill 端不能下载。

## 四、测试门禁及未完成项

- `tests/test_owned_user_resources_21.py`：真实持久化 SQLite、Web 站点 HTTP `PUT` / Skill 合同 `GET`、跨账号隔离、匿名 boot、个人资源选择、收藏幂等、CAS 并发旧版冲突、删除后的 tombstone。
- `handraw-style/skills/handraw-cloud/tests/test_handraw_cloud.py`：真实 Skill 命令代码的可注入离线网关，验证 `push/restore` 稳定编号、版本状态、安全拒绝异常回执，确保不静默覆盖。
- `.github/workflows/checks.yml` 固定具体 Skill 提交 SHA，在现有生产存储 Job 中运行跨仓客户端契约测试；整个 Web 门禁保持 14 个 Job。
- 本套测试均不依赖收费生图供应商；PostgreSQL/R2/Redis/跨主机正式部署仍由 #84/#112 的 D 级发布门禁验收。
- `FG-025` 是 #11 真实的 Skill-only 官方目录漂移，**不得从 Skill 私有同步反向发布成官网官方资源**，该问题需独立审核。
