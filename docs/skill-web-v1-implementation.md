# Skill × Web：当前公开多图作品接口与联调说明（V3 P0）

> 2026-11-07。**以 [V3 规范](generation-works-v3.md) / [Issue #84](https://github.com/yang0/handraw-web/issues/84) 为准。**
> 这份文件代替原先“每张图片单独创建作品、二次发布”的 V1 实施说明。
> Web：`yang0/handraw-web@main`；Skill：`yang0/handraw-style@feature/skill-web-unification-v1-20261107`。

## 已实现的过渡合同（V3 P0）

- 网站每个“逻辑生成批次”对应最多一件公开作品；画布单张或批量请求带稳定 `batchId`、0-based `batchIndex`、`batchTotal`。每个模型执行槽位仍有自己的 `requestId`，不能拿请求 ID 当整批作品 ID。
- Web 使用 `studio_generations` 存各执行槽位，V3 迁移 098 添加批次字段；`works.generation_batch_key` 唯一索引约束同一用户同一批次仅有一件作品。各槽位成功后按计划顺序汇入同一 `works.images_json`；默认封面是第一张成功图片。
- 一次非批次请求也只能创建一件作品，作品内可以包含多张图。失败/无图的任务不创建公开作品。
- Skill `history record` 只写本地；明确执行 `history upload` 后发送全部图片，服务端自动公开为**一件多图作品**，返回 `{workId,workIds:[workId],imageCount}`；上传端校验回执，不确认全部图片就不把本地记录标成 synced。
- 作品广场、个人主页按作品计数，一个作品一张封面卡；多图卡显示数量。点击作品进入作品/关联讨论详情，完整图片列表由 `works.images_json` 提供；后续补图会同步更新论坛主题媒体。
- 社区点赞/收藏/评论/举报是整个 `work_id` 的行为，不能按每张图片复制作品或主题。管理员审核隐藏状态不可因为后续批次结果恢复公开。
- 网站成功生成图片自动公开，Skill 用户明确上传后公开；私人参考图库、自建画风/图型和未上传 Skill 本地图片仍保持私有。

## 接口与权限

| 入口 | 行为 |
| --- | --- |
| `POST /api/studio/generate` | 新增批次字段：`batchId`、`batchIndex`、`batchTotal`；成功时自动关联唯一作品 |
| `POST /api/v1/me/generations` | Skill 主动上传完整 run；必须具备 `publish` scope；幂等返回单一 `workId` |
| `GET /api/v1/me/generations` | 本人可见跨端历史，Web 批次按逻辑任务归组 |
| `GET /api/works/feed?author=用户名` | 个人公开作品分页，一件作品一行 |
| `GET /api/works/feed` | 广场分页，一件作品一张卡，多图标记实际数量 |
| 作品详情 / 论坛主题 | 同一 `work_id` 下展示全部图片和一套互动 |
| `GET /api/admin/skill-bridge/audit` | 管理员审核尚未完成的旧公开映射问题（开发环境辅助） |

**旧合同不再有效**：`workIds` 不是逐图片 ID 列表；它只能是 `[workId]`。不再提供生成历史的二次发布按钮或接口。

## 未完成（Issue #84 P1）

- 规范化统一 `generation_runs`、`generation_items`、`media_assets`、`work_media`，移除历史 JSON 媒体身份多处重复及旧双链映射表。
- PostgreSQL 权威数据与 Redis 任务状态/缓存、对象存储适配；跨端任务与媒体的规范化唯一约束。
- 可编辑封面，图片级状态与部分失败槽位的完整统一模型。
- 跨分页历史聚合、媒体授权异步补偿、端到端真实浏览器测试、Web CI 恢复。

## 已有验证与发布门禁

- Skill 开发分支 GitHub Actions `Skill cloud bridge contract tests` 最新提交通过（包含 Python 语法及离线合同测试）。
- Web 前端 JavaScript 语法检查通过，覆盖“一作品仅一候选封面”的直接检查；添加 Python 和 CJS 回归测试，**尚无可信 Web CI 全绿记录**。
- Web GitHub Actions jobs 在分配 Runner 之前失败且无任何测试步骤，不能把失败等同于测试失败，更不能宣称通过。
- Web `main` 的 GitHub 提交**不等于服务器部署**。发布前必须运行隔离数据库测试、跨端真实上传与批量乱序测试、手机/桌面作品详情测试，确认媒体授权及管理隐藏策略。
- 没有正式发布，允许设计干净的新 Schema；任何重建测试数据库之前依然要备份并确认数据库环境，不自动删除旧库。
