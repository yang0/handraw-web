# Handraw Skill × Web · V3 统一任务与多图作品合同

> 2026-11-07 · 统一架构以 [Handraw V3 规范](generation-works-v3.md) 和 [Issue #84](https://github.com/yang0/handraw-web/issues/84) 为准。
>
> Web：https://github.com/yang0/handraw-web （`main`）
> Skill：https://github.com/yang0/handraw-style （`feature/skill-web-unification-v1-20261107`）
>
> **网站未发布且没有需保留的旧生成数据。全新数据库初始化，不做旧数据迁移或历史作品回填。**

## 1. 冻结产品合同

- 每个逻辑任务 `generation_runs` 最多只有一个公开 `works`，同一作品包含全部成功的图片/GIF。
- 作品广场、个人主页一件作品一张封面卡，显示图片数，详情按顺序展示全部图片。
- 网站成功生成时自动公开；Skill 仅在用户明确执行 `history upload` 时上传并公开；不需要二次发布。
- `generation_items` 保存全部输出槽位（包括失败项）；`media_assets` 和 `work_media` 是成功作品图片的权威身份与有序关联。
- 点赞、评论、收藏、举报全部关联唯一 `work_id`。参考图库、私有画风/图型、未上传的 Skill 本地文件和黑盒提示词依然受保护。

## 2. 关键接口

| 接口 | 核心行为 |
| --- | --- |
| `POST /api/studio/generate` | 一个画布批次共享 `batchId`，每张网关请求单独有 `requestId`、`batchIndex`、`batchTotal` |
| `POST /api/v1/me/generations` | Skill 主动上传整批图片，服务器返回 `workId`、`workIds: [workId]`、`imageCount`、`coverMediaId`、`coverUrl` |
| `GET /api/v1/me/generations` | 根据 `generation_runs` 分页，网站和 Skill 合并为一个逻辑任务历史，带图片和失败槽位 |
| `GET /api/works/feed` | 直接对 `works` 分页，一件作品一行/一张卡 |
| 作品详情/讨论主题 | 读取同一作品的全部图片，作品详情的权威图片顺序来自 `work_media JOIN media_assets` |

**旧接口已废弃**：`/api/admin/skill-bridge/audit`、`/api/admin/skill-bridge/reconcile`；旧 Skill 专用历史与作品映射表不再创建。作品回执 `workIds` 不是逐张图片列表，只能包含单个 `workId`。

## 3. 数据库与运行时边界

- PostgreSQL 新库基线包含 V3 规范化 Schema；旧 `generation_works`、`skill_generation_runs`、`skill_generation_work_items`、`skill_history_publications` 不再创建。
- `studio_generations` 仍专用于云端网关**执行、扣费、失败退款及任务恢复**，不再代表公开作品身份。
- `works.images_json` 是作品广场列表读取的缓存。同步写入规范化媒体后在同一数据库事务刷新，数据库触发器拒绝不一致；详情直接读取规范化媒体。
- `studio_generation_media`、`media_public_grants` 仍参与上传归属和媒体公开授权。隐藏作品时需要同时校验授权目标的公开状态。
- Redis 只承担缓存/限流/任务租约，不能成为生成历史或作品的权威数据库。
- 原生 PostgreSQL DDL 与本地集成测试已接入；实际生产部署与验收仍需单独完成。

## 4. 验收清单

- [x] 新 schema、直接 `works.run_id` 一对一关系、媒体身份和封面约束、失败槽位持久化逻辑已提交。
- [x] Web 批量 ID、Skill 可恢复上传、统一跨端历史、单封面瀑布流逻辑已提交。
- [x] 源码添加数据库约束、安全授权和回归测试。
- [ ] 真正执行 Web 全量 Python/Node CI，修复测试并保证全绿。
- [ ] 用真实 Web/Skill 客户端做跨端上传/生成、乱序、失败重试、GIF、移动端完整 E2E。
- [ ] PostgreSQL 原生 Schema、Redis 集成以及对象存储一致性和并发验收。

**提交到 GitHub 不等于部署到服务器，也不等于所有测试通过。Issue #84 保持开放直到验证完成。**
