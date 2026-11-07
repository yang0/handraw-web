# Skill × Web v1 实施与联调说明（公开作品规则）

> 更新：2026-11-07；正式决策以 `docs/skill-web-unification-v1.md` 顶部最新补充为准。  
> Web 代码：`yang0/handraw-web@main`；Skill 代码：`yang0/handraw-style@feature/skill-web-unification-v1-20261107`。

## 一、最新公开规则

**网站生成成功、Skill 用户主动执行作品上传，都直接公开，不再存在“发布到作品广场”的第二步。**

- 网站：`record_user_studio_history` 和 `prepare_cloud_generation` 的**新记录**固定 `visibility='public'`；`complete_cloud_generation` 成功后自动投影 `studio_generations → generation_works → works`，每张图片有独立作品。投影异常不再仅记警告、同时返回成功，而应回滚相关事务。失败/未完成、无图片、模拟引擎、删除及管理员下架不公开。
- Skill：`history record` 只在本地保存；用户明确执行 `history upload --run-id` 后，向 `POST /api/v1/me/generations` 提交 `originClient=skill`、`visibility=public`、`status=success`、原始指令、每张图片 SHA256/Base64、稳定 `externalRunId` 和 `requestId`。**上传本身就是公开提交**，服务端立刻为每张图片创建 `works.status=published` 的作品，返回 `workIds`。无须单独发布按钮。
- Skill 图片作品关联持久记录在增量迁移 **097** 的 `skill_generation_work_items`；作品发布使用网站统一的 `publish_user_work`、媒体归属检查及 `media_public_grants`，防止无效图片、越权和重试产生重复作品。
- Skill 上传要求 Device Token 具有 `publish` scope，历史查询使用 `library` scope；Skill 客户端绑定默认申请二者。**旧版只带 private 的客户端请求会被拒绝，不会偷偷公开。**
- `/api/v1/me/generations/{id}/publish` 不再提供，账号中心不再显示「发布到作品广场」按钮。已有独立 `community-share publish --draft` 是直接创建作品的历史兼容入口，不是图片生成后的二次发布步骤。

## 二、历史数据和安全边界

- **不会将旧私有历史自动公开。** 既有 `studio_generations.visibility='private'`、旧 `skill_generation_runs.visibility='private'` 与个人角色/道具/场景、个人画风/图型继续受现有私有权限保护。
- 迁移 **097 的一次性 post-migration hook** 会对已经明确标记 `public`、成功、未删除且非演示的旧网站历史重新做**幂等**作品映射，以修复“历史有图片但个人主页作品为 0”的旧记录问题。不会改变历史记录 visibility，尊重管理员对作品的隐藏状态。
- 若部分旧公开历史仍无法映射，可在备份后用管理员只读 `GET /api/admin/skill-bridge/audit` 审计，并通过明确确认的管理员补录接口 `POST /api/admin/skill-bridge/reconcile` 小批量处理。绝不直接给 private 历史改 public。
- Skill 的上传历史可断点续传；原图最大 15 MiB，受控请求体最大 64 MiB、账号生图历史存储上限 1 GiB。大批量超出请求体限制需要未来两端的预上传/分批协议；失败保留本地文件，并可通过同一 `runId` 幂等重试。提示词会随作品公开，上传前必须确认无私人信息、商业秘密或未授权素材；服务端对已知受保护文本执行拦截。

## 三、同一用户和接口

| 能力 | 关键路由/服务 | 结果 |
| --- | --- | --- |
| 统一账号 | `/api/auth/device`、`/api/auth/device/token`、`/api/auth/me` | 复用设备码授权 |
| 个人图片图库 | `/api/library/assets` | 私有、UUID/revision、增量游标 |
| 自建画风/图型 | `/api/v1/me/resources` | 私有、乐观锁及软删除 |
| 获取授权资源 | `/api/skill/library`、`/api/v1/me/collection-items` | 受许可与解锁权限控制 |
| 网站成功生图 | `studio_generations → works` | 自动公开 |
| Skill 上传作品 | `POST /api/v1/me/generations` | 自动公开、返回 workIds |
| 本人生成历史 | `GET /api/v1/me/generations` | 包括既有私有记录，返回公开作品关联 |
| 个人主页作品 | `GET /api/works/feed?author=用户名` | 只显示 published 作品 |
| 社区互动 | `/api/v1/works/{id}/likes`、`.../comments`、`/api/v1/me/notifications` | 复用已有点赞、论坛评论及通知 |

## 四、验证步骤与风险

1. 完整备份数据库和媒体，再在隔离环境执行数据库迁移 097 和一次性公开历史修复；检查旧 private 记录数、已发布作品数、公开媒体 grants 是否符合预期。
2. 网站生成两张真实图片：`studio_generations.status=success,visibility=public`，`generation_works` 有两条映射，个人主页出现对应图片，匿名查看图片成功。
3. Skill `history record` 不应创建云端作品；执行 `history upload` 后返回 `visibility=public,workIds`，个人主页立即可见且媒体可公开访问；同一 runId 重试不增加作品条数。
4. Skill 旧私有记录保持私有；只持有 library scope 不能公开上传；错误图片哈希、跨账号图片、包含受保护内容的提示词必须被拒绝。
5. 对存在缺失 works 映射的旧公开历史执行一次性修复后应恢复展示；管理员隐藏作品不应重新公开。

**当前验收状态**：Skill 原分支离线 CI 已通过；Web 私有仓库 GitHub Actions 因没有 Runner 分配仍无法运行，未完成 Web 端真实测试及生产部署。**修改 Web `main` 并不代表网站服务器已更新或数据库已执行迁移。**
