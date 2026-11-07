# Handraw Skill ↔ Web v1：网站端接口与开发记录

> 状态：开发分支中，未合并 main，未部署，生产 E2E 未验证。  
> 设计基线：https://github.com/yang0/handraw-web/blob/main/docs/skill-web-unification-v1.md  
> 日期：2026-11-07

## 双仓库地址与分支

| 项目 | GitHub 地址 | 开发分支 |
| --- | --- | --- |
| Skill 客户端 | https://github.com/yang0/handraw-style | feature/skill-web-unification-v1-20261107 |
| Web 业务与 API | https://github.com/yang0/handraw-web | feature/skill-web-v1-backend-20261107 |

Skill 开发 PR：https://github.com/yang0/handraw-style/pull/12 。两个仓库的默认分支分别为 master 和 main。不要将任何客户素材、私有密钥、生产配置或数据库写入 Git。

## 后端模块与数据迁移

- backend/skill_cloud_schema.py：migration 094，新增私有个人画风/图型、Skill 私有历史、媒体映射和评论幂等请求表，只做增量迁移。
- backend/skill_cloud_routes.py：v1 服务端 API，包括 owner-only 个人资源、revision/409、增量拉取、完整定义访问、私有生图历史、评论/点赞/通知。
- backend/server.py：路由注册和精确设备令牌 scope，私有 Skill 图片所有者校验。
- backend/services.py：生产环境新生成历史默认 private；已发布作品与历史链接不改；本人私有画风/图型加入旧版 Skill 资源清单及完整定义读取。
- demo/assets/main-app.js：本人账号个人主页可查看和编辑私有画风/图型；增加本人私有创作历史，区分公开作品。
- tests/test_skill_cloud_v1.py：隔离数据库 HTTP 合同测试。

## API 合同（对齐 Skill 分支 handraw_cloud.py）

| 方法与路径 | 授权 | 请求 / 响应 |
| --- | --- | --- |
| PUT /api/v1/me/resources/{uuid} | library | id,kind(style/layout),name,definition(zh/en),license,examples,version,visibility=private,baseRevision?；返回 resource.revision |
| GET /api/v1/me/resources?limit=100&since={cursor} | library | items,nextCursor,hasMore；增量 tombstone 带 deletedAt |
| DELETE /api/v1/me/resources/{uuid}?baseRevision=N | library | 乐观锁软删除，返回 deletedAt |
| GET /api/v1/me/collection-items | library | 收藏关系、完整访问资格与 syncEligible 状态 |
| GET /api/v1/resources/{id}/download | library | UUID 仅资源所有者；官方/社区资源复用授权检查 |
| POST /api/v1/me/generations | library | externalRunId,originClient=skill,visibility=private,status=success,originalRequest,images[{name,sha256,dataUrl}]；返回 id,deduped |
| GET /api/v1/me/generations?limit=100&cursor=... | library | 汇总本人网站与 Skill 生成记录，返回 items,nextCursor,hasMore |
| GET /api/v1/me/notifications?before=... | library | 复用已有网站通知列表，items,unread,nextBefore |
| POST /api/v1/works/{id}/likes | publish | liked:boolean；复用网站点赞表 |
| POST /api/v1/works/{id}/comments | publish | text,requestId；复用网站作品讨论，重复 requestId 防重 |
| GET /api/v1/works/{id}/comments | library 或网页会话 | 公开作品评论 |
| GET /generated/skill_*.png | library | 已认证本人私有图片；不授权按现有私有媒体访问控制返回不可见 |

客户端使用 Authorization: Bearer hwt_... 设备令牌；浏览器会话继续要求原有 Origin/CSRF 检查。网络失败不会把私有操作自动视为成功。

**保留兼容的已有接口**：
- 设备授权 POST /api/auth/device、/api/auth/device/token、GET /api/auth/me，作用域 library/publish。
- 原图库 GET/PUT /api/library/assets、DELETE、restore 和图片访问，允许 Skill 角色/道具/场景双向同步。
- GET /api/skill/library 与 GET /studio/api/library 继续返回 collected/owned/official，新私有画风/图型加入本人 owned。
- GET /studio/api/assets/{uuid}/content 返回旧 Skill 所需的 resource + SHA256：resource 里保留 kind/name/prompt_zh/prompt_en/license/version，以非 ASCII 转义的紧凑 JSON 字节计算 Hash。
- POST /api/uploads 与 POST /api/entries 继续提供**用户主动确认**后的作品发布入口。
- POST /api/collections/toggle 继续复用网站收藏表。

## 权限、隐私和一致性

1. 一个 user_id 对应 Skill 与 Web 的全部个人资产。私有云同步不等于公开发表。
2. 个人画风/图型仅允许 private。更新使用 baseRevision，冲突 409，软删除 tombstone 不同步删除设备上的本地文件。
3. Skill 生成记录原图检验类型、解码、图片哈希、尺寸、数量和容量；只有本人可以访问图片与原始指令。相同 externalRunId 重放返回同一记录，不创建 works。
4. 作品公开经独立确认发布流程；不能把私有历史自动投影到作品广场。已有公开作品不会批量更改。
5. 点赞/收藏/评论复用网站原有业务，不建立第二套社交关系和计数。
6. 评论请求预留唯一 requestId；提交结果不明时返回 outcome_uncertain，避免重复发送评论。
7. 资源已收藏不代表可以下载完整定义。已有某些付费解锁只能在线调用、不能离线导出的许可继续保持；不能绕过访问规则下载受限配方。
8. 图片私有访问仍采用网站受控本地存储。对象存储迁移是运维后续独立专项，本分支没有假称已经完成。

## 迁移与发布

- migration 094 仅新增表和索引；正式上线前备份，使用独立测试数据库运行测试。代码回滚不回滚数据库迁移。
- 生产新建网站生图历史默认 private；历史已有 public 作品继续原样可见，原 work ID、链接与互动保持。
- HANDRAW_LEGACY_AUTO_PUBLISH_GENERATIONS=1 仅作为明确临时兼容开关；不要当成新产品默认逻辑。
- 不在生产数据库执行演示、回填或集成测试；先灰度、对账，再推广。
- 验收 Skill 设备授权 → 私有图库 → 画风图型推拉 → 已授权收藏完整下载 → Skill 私有历史 → 明确点击发布作品 → 网站互动/通知；验证跨设备冲突、越权、重复请求、媒体访问隔离。

## 验证状态与明确限制

代码和隔离 HTTP 回归测试已经提交；已对 main-app.js 完成独立 JavaScript 语法解析检查。当前 GitHub Actions 的 Checks 在此分支多次出现全部 Job 在零执行步骤时失败、日志无法获取的情况，尚无法通过 CI 证明所有 Python 测试成功。需要修复仓库的 Runner/Actions 环境并完成真实账号双仓库 E2E，才能申请最终合并和部署。

本次保留旧版 Web 生图到作品的历史映射与数据兼容；完整旧记录迁移、对象存储部署和生产灰度均需独立实施并验收。
