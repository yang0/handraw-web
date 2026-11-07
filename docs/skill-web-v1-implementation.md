# Handraw Skill ↔ Web v1 服务端实现与联调交接

> 更新：2026-11-07  
> 功能分支：`feat/skill-web-backend-v1-20261107`（仅开发，不代表已部署）  
> Web 仓库（私有）：https://github.com/yang0/handraw-web  
> Skill 仓库（公开）：https://github.com/yang0/handraw-style  
> Skill 联动 PR：https://github.com/yang0/handraw-style/pull/12  
> Web 本期 PR：https://github.com/yang0/handraw-web/pull/83  
> 正式决策基线：https://github.com/yang0/handraw-web/blob/main/docs/skill-web-unification-v1.md

## 本期 Web 实现

- `backend/skill_web_schema.py`：三个**增量**迁移（094–096），不修改或删除既有表、历史 works 记录。
- `backend/skill_web_bridge.py`：个人私有画风/图型及授权读取、Skill 私有历史、手动发布、互动与通知。
- `backend/server.py`：统一路由，按现有 Token scopes 控制访问；上传 `share` 和 `skill_history` 单独归类，不混入普通图库。
- `backend/resource_discussions.py`：对 Skill 评论提供同事务幂等，复用既有 forum_replies。
- `backend/services.py`：`HANDRAW_PRIVATE_GENERATION_HISTORY_V1` 灰度开关。
- `demo/assets/cloud-center.js`、`main-app.js`、`demo/index.html`：网站「账号设置 → 个人云空间」，展示本人自建画风/图型、私有图库、完整收藏状态与云端历史，可新建、编辑个人资源，并在显式确认后选择私有历史图片发布到作品广场。
- `tests/test_skill_web_bridge.py`：SQLite/HTTP 契约测试、跨账号隔离、授权范围、冲突、评论/历史幂等、发布意愿、媒体验证与只读审计。

## 与 Skill CLI 对齐的可调用接口

| 路由 | Scope | 关键行为 |
| --- | --- | --- |
| `GET /api/auth/me` 与现有 Device Authorization | Device token | 直接复用既有逻辑 |
| `GET /api/library/assets?since=...`、`PUT /api/library/assets/{uid}` | library | 已有素材 UUID、SHA256、revision、软删除 |
| `GET /api/skill/library` 和已有受控资源内容 API | library | 收藏及已授权完整定义 |
| `GET /api/v1/me/resources?limit=100&since=cursor` | library | 私有 owned 画风/图型；`items`、`nextCursor`、`hasMore` |
| `PUT /api/v1/me/resources/{uuid}` | library | `visibility=private`、`baseRevision`、409 当前版本 |
| `DELETE /api/v1/me/resources/{uuid}?baseRevision=N` | library | 软删除、保留墓碑供增量同步 |
| `GET /api/v1/me/collection-items` | library | 可同步的资源授权状态；未授权不返回完整定义 |
| `GET /api/v1/resources/{id}/download` | library | 个人自有定义或现有可授权下载的目录资源 |
| `POST /api/v1/me/generations` | library | `externalRunId`、`requestId`，生成历史默认私有、失败可续传、不建公开作品 |
| `GET /api/v1/me/generations?limit=100` | library | Skill + 网站的本人历史，带 `canPublish`、`publishedWorkId` |
| `POST /api/v1/me/generations/{id}/publish` | publish | 要求 `confirmed:true`、title、公开 prompt、可选 indices，幂等生成作品和媒体公开授权 |
| `POST /api/entries`、`POST /api/uploads` | publish | 兼容 Skill 已有草稿分享发布 |
| `POST /api/v1/works/{id}/likes` | publish | `liked` 布尔，复用既有点赞和奖励计算 |
| `POST /api/v1/works/{id}/comments` | publish | `text`、`requestId`，同事务去重并进入网站真实讨论 |
| `GET /api/v1/works/{id}/comments` | library | 复用网站公开评论读取 |
| `GET /api/v1/me/notifications` | library | 仅本人通知，支持 before 游标 |
| `POST /api/collections/toggle` | library | 已有收藏 set/unset，与网页相同 |
| `GET /api/works/feed` 和 `GET /api/works/{id}` | 无需 token | 现有公开作品查询 |

以上采用网站现有 `user_id` 作为归属，返回不含其他用户私有素材、私有定义或未授权资源明文。无效令牌、不足 scope、409 版本冲突均应明确失败。

### 审计与补录（管理员，不能由 Skill 令牌调用）

- `GET /api/admin/skill-bridge/audit`：统计已有 **public** 成功历史及无映射 works 的数量，纯只读。
- `POST /api/admin/skill-bridge/reconcile`：提交 `{"confirmed":true,"batchSize":50,"cursor":null}`；只对旧数据明确标识为 public 的生成记录，调用已有幂等投影进行小批量修复。**不会扫描私有历史作公开补录。**

## 产品迁移边界

- 现有网站的 `studio_generations` 自动投影公开作品行为保留为兼容路径，以防原数据和老客户端受影响。
- 当操作人员在测试库验证完整链路后，可设置 `HANDRAW_PRIVATE_GENERATION_HISTORY_V1=1`，使**新产生**的网站生成记录默认私有；已经公开的旧作品完全不回写、不下架。
- `works` 主键、社区评论、收藏与旧公开链接均沿用。不要直接删除旧表或批量更改历史可见性。
- 私有 Skill 历史来自新 `skill_generation_runs`，不会因上传或成功而出现在公开主页。用户明确点选图片、提供可公开标题/提示词且确认，才创建作品。
- 生产环境部署前务必备份数据库与现存媒体，使用明确提交号部署；数据库迁移仅增量，回滚应用时不回滚迁移。

## 未经生产验收的限制和后续合同

1. **历史上传体积限制**：全站普通 JSON 请求仍为 20 MiB，仅已登录用户的 `POST /api/v1/me/generations` 为适配 Skill Base64 编码提升到 **64 MiB**。每张原图最大 15 MiB，账号私有历史存储限额 1 GiB，并受设备令牌限流。该上限不能承载任意 12 张 15 MiB 大图的一次性请求，多图超过时明确返回 413。大批量仍须跨仓库协同升级为预上传媒体 + 分次确认或受控分片协议，不能无限放大内存请求。
2. **OS/浏览器的实际生产登录**：需要真实站点 Device Token、个人素材、授权收藏、完整分享发布和媒体显示的端到端测试；现有 SQLite/离线代码覆盖不等于生产环境已验收。
3. **CI 环境**：本仓库主分支和开发分支的 Actions 持续出现所有 job 立即 failure、步骤列表为空、日志跳转 404 BlobNotFound 的现象。需要先恢复/排查 runner 或组织 Actions 策略，不能凭这些失败归因本变更，也不能把测试写成通过。
4. **跨数据库运行时**：如生产环境使用 PostgreSQL/Redis 兼容层，增量迁移及异步操作必须在隔离 staging 验证并监控性能；该分支尚未通过此验收。
5. **资源公开到社区**：当前个人资源同步只支持私有；真正将自建画风/图型作为社区资产发布，仍需走独立的投稿/审核与版权许可流程，不应该因私有同步而自动公开。
6. **通知**：从网站既有 notifications 单表读取；不另造通知记录。对作品讨论的通知需在真实数据库中验证评论触发器和消息投递。

## 上线前验收清单

- [ ] 全套后端测试与前端语法、HTTP 契约测试真实通过（含现有回归）
- [ ] Skill 与网站使用真实测试账号完成 Device Authorization 和令牌撤销
- [ ] 角色素材 A→网站→B 恢复，403 越权、409 冲突、软删除均按设计
- [ ] Skill owned 风格/布局 → 网站账号云空间 → Skill 另设备恢复
- [ ] 未解锁完整资源不能导出、已授权可用
- [ ] Skill 私有历史上传后，公开作品列表不变
- [ ] 手动确认发布后网页可见图片、正确作者与公开文案；重试无重复
- [ ] 点赞、评论、收藏、通知与网站共享事实来源
- [ ] 灰度开关关闭下既有公开生成链路回归；打开后新历史默认私有
- [ ] 生产备份、准入检查和回滚方案完成

**状态**：开发分支待审查和联调；**尚未合并 main，也未部署**。
