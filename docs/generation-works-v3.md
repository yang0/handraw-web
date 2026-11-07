# Handraw V3 — 统一生图任务、作品和媒体模型

> 2026-11-07 · 产品决策基线。跟踪 Issue：[ #84 ](https://github.com/yang0/handraw-web/issues/84)。
> 网站尚未正式发布，不再以旧版生成历史/作品 API 与旧数据模型兼容为重构约束；**严禁直接对未经确认的用户数据库执行清库**。
>
> Web：`yang0/handraw-web@main`；Skill：`yang0/handraw-style@feature/skill-web-unification-v1-20261107`。
> **本文件同时标记目标架构与实际提交状态；未标记为完成的项目不可宣称已上线。**

## 1. 不可变产品规则

1. **一个逻辑生成任务 = 最多一件作品 = 广场/个人主页最多一张封面卡片。**
2. 一件作品可以有 1–N 张成功生成的图片/GIF；单个生成请求失败或无有效图片时不产生公开作品。
3. 网站成功生图自动公开；Skill **用户主动把本地任务上传到网站**后自动公开，且一次上传只生成一件多图作品。无二次发布按钮。
4. 历史按任务分组（不是按图片）；详情按计划输出顺序显示全部成功图片、失败槽位、下载和复刻能力。默认封面为排序后的首张成功图。
5. 点赞、收藏、评论、举报、浏览、作品互动计数、论坛讨论全部绑定同一个 `work_id`；不会因一次任务有 5 张图产生 5 份互动或 5 个帖子。
6. 作品默认公开**不代表个人图库、角色/参考素材、私有画风/图型定义、内部系统提示词、凭据自动公开**。管理员隐藏/删除状态仍生效。
7. 同一批次异步完成或跨端重试均只会补充作品图片，不能新建第二份作品；对象存储上传/授权失败不得默默标记生成完成。

## 2. 任务语义：UI 批次 ≠ 模型请求

画布批量生图当前为每个输出槽位发出独立的 `POST /api/studio/generate`；不同的 `requestId` 只用于**子请求幂等**，不能用作作品身份。

V3 客户端增加：
- `batchId`：一次用户创作行为的稳定逻辑任务 ID，同一批 N 图共享。
- `batchIndex`：0-based 槽位索引。
- `batchTotal`：预期输出槽位数。

服务端用 `(user_id,batchId)` 确定唯一公开作品；已成功的槽位按 `batchIndex` 排序后汇入同一作品。首个槽位完成即可出现封面，后续完成原地追加；已隐藏作品不能因为其他槽位完成而被恢复公开。失败槽位只出现在任务历史中，不进入作品媒体。

Skill 本地以 `externalRunId` 表示逻辑任务；`history record` 不联网；`history upload` 一次上传全部图片，回执为 `workId`、`workIds: [workId]`、`imageCount`。重复上传使用相同 `externalRunId`/`requestId`。

## 3. 目标规范化数据库（P1 完成后）

```text
users 1─N generation_runs
                │ 1─N
                ▼
         generation_items ─────> media_assets
                │                     ▲
                │ 1:0..1              │
                ▼                     │
             works 1─N────────── work_media
                │
                ├── work_interactions / work_comments
                └── forum_threads (0..1)
```

- `generation_runs(id, user_id, source, external_run_id, request_id, status, params_json, created_at)`：统一网站/Skill/后续客户端；一个 run 最多一件 work。
- `generation_items(run_id, item_key, position, status, media_id)`：每个执行槽位有稳定主键和顺序；失败项可没有 media_id。
- `media_assets(id, owner_id, storage_key, sha256, mime_type, width, height, size_bytes)`：原图与 GIF 的文件身份；对象存储放二进制文件。
- `works(id, run_id NULLABLE UNIQUE, owner_id, title, cover_media_id, status, moderation_status, published_at)`：**唯一社区作品实体**。不由生成而来的直接作品可不关联 run。
- `work_media(work_id, media_id, position)`：唯一组合和稳定排序，封面必须属于当前作品媒体集合。
- `interactions`、`comments`、`forum`：统一关联单件 works，不做逐图作品。

规范化之后，生成任务 JSON 不再是公开媒体唯一身份；`generation_works`、`skill_generation_work_items`、`skill_history_publications` 等旧中间映射和两套独立生成历史会被替代。**这一步仍属于 P1，不应误报已完成。**

约束：
- `UNIQUE (user_id, source, request_id)`：请求幂等；来源/请求键不能为空时才启用。
- `UNIQUE (run_id)` on works：一个逻辑任务最多一件作品。
- `UNIQUE (run_id, item_key)` 和 `UNIQUE (run_id, position)`：任务输出稳定、不会重复。
- 只在状态成功且媒体存在、审核正常且未删除时广场可见；状态机与审核状态分离。
- 对象上传不可加入 PostgreSQL 事务：先可靠保存/验证媒体，再在数据库事务中提交关联与状态，失败可通过幂等任务重试和后台对账修复。
- PostgreSQL 负责权威数据；Redis 只承载任务队列、短期缓存和限流；S3/R2/MinIO 等对象存储负责原图/GIF/衍生文件。

## 4. 当前 P0 过渡实现（与最终规范化模型明确区分）

| 范围 | 当前完成情况 |
| --- | --- |
| 网站逻辑批次身份 | 已添加迁移 098：`studio_generations.batch_id/batch_index/batch_total`；`works.generation_batch_key` 及唯一索引 |
| Web 生成 → 作品 | `generation_works.project_generation_to_works` 按完成槽位聚合，不再逐张创建作品；所有图片保留在**同一 works.images_json** |
| Web 历史 | `services` 按 batchId 合并页面初始化历史；保留子请求 pendingTasks 供恢复 |
| Skill 上传 | 一次 run 创建一件包含 N 图的 works；回执 `workId`、单元素 `workIds`、`imageCount` |
| 作品广场 | `works-browser.unpackWorkCandidates` 一件作品只产生一张卡；显示 `N 张`角标 |
| 个人主页 | 直接按作品渲染一张封面卡片，不额外渲染三图横条 |
| 讨论详情 | 同一作品后续补图，`ensure_topic` 刷新主题媒体列表，保留原评论/主题 ID |
| 安全/审核 | 默认公开生成作品；私有素材权限及管理员隐藏不因批次追加改变 |
| P1 目标 | 统一 `generation_runs/generation_items/media_assets/work_media` 及去除旧重复表：**尚未完成** |

当前部分过渡实现仍使用 SQLite Schema 和 `works.images_json`，这不是最终最佳实践；先保证“一个逻辑 run 只产生一件作品”的业务正确性，再做干净规范化与 PostgreSQL 切换。

## 5. API 与 UI 验收

| 场景 | 预期 |
| --- | --- |
| Web 单图 | 1 run → 1 work → 1 卡，详情 1 图 |
| Web 批量 5 图，异步乱序 | 同 `batchId`、5 子请求 → 1 work、1 卡、详情 5 图；封面按 `batchIndex` 取首张成功图 |
| 5 图 3 成功 2 失败 | 1 work、详情 3 图；历史留失败槽位，不渲染空白公开卡 |
| 全失败/无图 | 不生成公开作品 |
| Skill 上传 5 张 | 1 work、1 卡、5 图、同一组互动；返回单个 `workId` |
| Skill 断点重传 | `workId` 不变；无重复图片/作品/帖子 |
| 匿名浏览多图详情 | 所有成功图能看，个人图库和内部 prompt 仍不可访问 |
| 被管理员隐藏的作品 | 后续子任务成功不能重新公开 |
| 数据出错 | 必须回滚或显式报错，不能“历史 18 张、作品 0 张”却静默成功 |

## 6. 质量门槛

- Web Python 单元/HTTP/权限测试、CJS 瀑布流/路由测试、Skill CLI 回执测试。
- 服务端隔离数据库：真实多图乱序完成、重试、并发、部分失败、媒体归属、hidden 作品、数据库唯一约束。
- 两端浏览器 E2E：个人主页、广场、详情、GIF、移动端、图片顺序与计数。
- GitHub Actions Runner 必须真正执行测试；**创建/合并提交≠部署上线，也不能把 Runner 分配失败写成 CI 通过。**
- 未正式发布时允许重建开发数据库进行干净迁移，但先确认开发环境与备份；不自动删除任何数据库。
