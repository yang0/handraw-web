# Handraw V3 · 统一任务、媒体与公开多图作品

> **本轮开发进展（2026-11-07）**：封面编辑、文章批量归并、图片槽位重试/安全取消、GIF 静帧、S3/R2/MinIO 私有媒体、Redis 多实例租约、PostgreSQL 全新空库初始化与 Skill 封面回执已提交代码。最新开发与配置说明以 [V3 开发状态](v3-development-status.md) 为准。下文早期 P1 段落如仍将这些项列为“待开发”，以本注释和状态文件为准；真实运行验证仍未进行。

> 设计决策日期：2026-11-07 · 追踪：[Issue #84](https://github.com/yang0/handraw-web/issues/84)  
> 适用仓库：Web **https://github.com/yang0/handraw-web**（`main`）与 Skill **https://github.com/yang0/handraw-style**（`feature/skill-web-unification-v1-20261107`）。  
> **明确前提：网站尚未上线，没有需保留的用户旧数据。V3 采用全新数据库初始化，不做历史数据兼容、旧历史补录或旧图片迁移。** 任何实际重建/删除数据库仍需操作人员确认本机环境，本工程不会自动清库。

## 1. 冻结的业务规则

1. 一条**逻辑生成任务最多一件作品**。网站成功生成与 Skill 用户明确上传的作品自动公开，不提供“发布到广场”的二次操作。
2. 一件作品可包含 N 张成功图片或 GIF；**作品广场和个人主页均只显示封面一张卡**，多图卡显示真实媒体数量。详情显示所有成功图片，并保持计划输出顺序。
3. 批量生成与执行请求分离：画布一次“生成 N 张”拥有稳定 `batchId`；各网关请求有独立 `requestId`、`batchIndex`、`batchTotal`。一批中 3 成功 2 失败：1 件公开作品、3 张公开图片，任务历史保留全部失败槽位。
4. 点赞、收藏、评论、举报、复刻等作用于同一个 `works.id`，不为每张图片复制作品、讨论主题或互动。
5. 用户个人图库、参考素材、未上传的 Skill 本地图片、私有画风/图型定义和内部隐藏提示词不会因为生成作品默认公开而自动公开。
6. 作品隐藏/删除由审核状态控制；某个批次子请求失败或被删除不能自动隐藏剩余成功图片；管理员隐藏不能被后续子任务自动取消。
7. 失败必须显式记录并可恢复，存储成功但作品写入失败不能静默返回成功。

## 2. 规范化数据模型（PostgreSQL）

```text
users
 └── generation_runs (owner, source, external_run_id, idempotency key, status)
       ├── generation_items (position, status, media_id, error_code)
       │                         └── media_assets (owner, storage key, SHA-256, MIME)
       └── works (run_id UNIQUE, cover_media_id, title, moderation/interaction)
             ├── work_media (media_id, position) ────────────> media_assets
             ├── work_comments / social interactions / collections
             └── forum_topics (one shared discussion)
```

核心实现：`backend/generation_v3.py`；**数据库初始化定义** `V3_MIGRATIONS`，建立 `generation_runs`、`generation_items`、`media_assets`、`work_media`，给 `works` 增加 `run_id`、`cover_media_id`。

关键数据库约束：
- `UNIQUE(user_id,source,external_run_id)`、`UNIQUE(user_id,source,request_id)`（非空键）与 `works.run_id UNIQUE`，防止重试产生第二件作品。
- `UNIQUE(generation_items.run_id,position)`、`UNIQUE(work_media.work_id,position)`、`PRIMARY KEY(work_id,media_id)`，保证图片项稳定并且每件作品的媒体可排序。
- 外键、触发器阻止不同用户间篡改运行归属/媒体归属；封面必须属于当前作品；run/media 的关键身份不可更改。
- `works.images_json` **只是瀑布流列表的派生显示缓存**，唯一媒体身份在 `media_assets` + `work_media`。写入服务在同一事务中更新，数据库触发器拒绝与媒体关联不一致的缓存；作品详情直接读权威媒体表。
- `generation_items` 保留失败槽位与错误码；成功且有媒体 ID 的槽位才能出现在公开作品中。
- 原图、GIF 二进制不存入 SQL；文件存储与独立私有素材授权仍由现有服务管理。

**V3 不创建旧版 `generation_works`、`skill_generation_runs`、`skill_generation_work_items`、`skill_history_publications` 表。** 旧版历史补录管理接口及数据库 backfill hook 已移除。新库使用原生 PostgreSQL 基线与追加迁移初始化。

## 3. 写入与读取流程

### Web 云端生成

`POST /api/studio/generate` 接收 `batchId` / `batchIndex` / `batchTotal`，与网关子请求幂等 ID 分离。后端在生成计费/执行记录的事务中保留统一 `generation_runs` 记录；网关成功后，以真实结果构建 `generation_items` 和 `media_assets`，在一个数据库事务中关联最多一条 `works` 以及全部 `work_media`。生成失败/退款的子请求在 `generation_items` 留下失败状态，失败整批没有作品。分批/乱序返回按槽位顺序汇总，第一张成功图是默认封面。

`studio_generations` 暂时继续存在，定位为**网关执行、扣费、退款、任务恢复的底层记录**，不是作品或生成历史的权威模型。统一生成历史由 `generation_runs` 承载。

### Skill 用户主动上传

`history record` 为纯本地操作。`history upload` 提交一个稳定 `externalRunId`、请求哈希与全部图片；每张成功存储的媒体在 `generation_items` 持久登记，断点续传只上传缺失槽位。整个任务公开时仅创建一件 works，并在最后确认全部媒体授权与关联成功；回执为：

```json
{"ok":true,"id":"run_...","workId":"work_...","workIds":["work_..."],"imageCount":5,"visibility":"public"}
```

客户端确认 `workIds` 只包含 `workId`，且 `imageCount` 与本地图片数一致后，才标记上传成功。不接受同一外部运行 ID 使用不同原始指令或图片哈希重试。

### 统一读取

- 个人主页与广场：按 **works** 分页，一个作品一张封面卡。
- 作品详情：从 `work_media JOIN media_assets` 按 `position` 读取全部成功图片；评论和点赞统一绑定作品 ID。
- `GET /api/v1/me/generations`：按 `generation_runs` 分页，网站和 Skill 共享一套数据模型；包含图片、输出槽位状态与失败码。
- 论坛主题：每件作品最多一个帖子；批量后续成功图片会更新其详情图片列表。
- 管理员隐藏/删除不因新生成子项自动恢复公开。

## 4. 当前保留但不属于“旧版本兼容”的部分

网站核心的 `studio_generations`、`studio_generation_media` 和 `media_public_grants` 仍承担执行计费、媒体上传归属与公开读权限；不应与 `generation_runs` 的**逻辑任务**混淆。其功能拆分以后可以进一步收敛，但不要为了减少表名而破坏退款、授权或恢复机制。

现有 `works.images_json` 仅为公开列表缓存；PostgreSQL 外键和触发器保护规范化媒体关系与公开投影，直接手动修改会被数据库约束拒绝。

## 5. 质量与上线门槛（尚未全部满足）

- 已新增/更新隔离测试：独立任务一次生成多图；多路乱序到达；重复请求/上传；跨用户媒体归属；封面约束；列表缓存一致性；3 成功 2 失败的槽位保留；Skill 断点续传；单卡瀑布流和作品详情。
- 仍须实际运行 Python 全量单元测试、Node 交互回归、Web ↔ Skill 真实上传 E2E 与跨进程并发测试。**Web GitHub Actions 当前在 Runner 作业步骤开始前失败，没有可信全绿结果。**
- PostgreSQL 原生 V3 schema 与完整运行时适配、对象存储持久性与授权测试仍需单独完成；当前不可称为 PostgreSQL 生产部署就绪。
- 新库初始化拒绝覆盖任何已有业务表；历史数据修复与新库创建分别执行，不自动清空数据库。
- 未达到全部门槛前，Issue #84 保持开放，不能宣称全部完成或已部署。

> 本文件覆盖 `docs/skill-web-unification-v1.md` 及旧 V1 实施说明中所有“历史私有默认/逐图发布/二次发布/旧数据回填”的过时表述。
