# Handraw V3 · 代码开发交付状态

记录时间：2026-11-07。追踪 Issue：https://github.com/yang0/handraw-web/issues/84

范围：Web https://github.com/yang0/handraw-web （main）；
Skill https://github.com/yang0/handraw-style （feature/skill-web-unification-v1-20261107）。

## 架构原则

网站未正式发布，且没有需要兼容的历史用户数据。采用全新 V3 Schema，不回填旧数据，不保留旧版逐图生成历史。每个逻辑生成任务最多形成一件公开多图作品，个人主页和广场只显示一张封面卡，详情展示全部成功图片或 GIF。

## 本轮开发提交内容

1. **作品封面编辑**：作者可在作品详情切换任意成功图片作为封面。API 为 POST /api/works/{workId}/cover，接受 imageUrl，返回 coverMediaId、coverUrl；后端校验身份、图片归属与作品媒体关系。前端广场、个人主页展示所选封面，后续异步完成任务不覆盖作者选择。
2. **统一多图生成与图片槽位重试**：文章批量生成和画布批量生成都使用同一 batchId + batchIndex + batchTotal。单张重试替换既有图片槽位，不创建同批第二件作品；失败重试不删除已经成功的旧图片。
3. **停止未提交的图片槽位**：POST /api/studio/batches/{batchId}/cancel-pending 接受 positions，只取消尚未发送到网关的槽位。已发送任务仍由网关实际状态和计费退款流程处理；不会对正在运行的远程任务伪报取消成功。
4. **GIF**：上传支持 image/gif，验证文件签名、总像素与最大帧数。广场按一帧的 WebP 缩略图展示，进入详情播放原始 GIF。
5. **媒体资产标准化**：media_assets 写入持久化媒体 SHA-256、长宽、字节数与 MIME。work_media、generation_items 为数据库媒体身份，works.images_json 只是列表缓存。
6. **私有对象存储**：新增 backend/object_storage.py，支持 S3/R2/MinIO；保留 /generated/ 和 /uploads/ 路由并在服务器做鉴权。文件写入和读取走私有桶，读取缺失本地缓存时验证权限后回源。可使用 HANDRAW_OBJECT_BUCKET、HANDRAW_OBJECT_ENDPOINT、HANDRAW_OBJECT_REGION、HANDRAW_OBJECT_PREFIX、HANDRAW_OBJECT_SSE；使用 boto3 的 AWS 凭证链。
7. **多实例 Redis 任务协调**：新增 backend/redis_jobs.py。后台生图结果协调使用带续租的 SET NX 租约，避免多个进程同时轮询/补录相同批次；生成状态与计费仍以数据库为准。
8. **全新 PostgreSQL 初始化**：新增 backend/postgres_v3_native.py 中的原生 FK、CHECK、权限和封面/媒体一致性触发器；ops/bootstrap_postgres_v3.py 从全新临时 SQLite 空白 schema 衍生所有业务辅助表，并在完全空白 PostgreSQL 中建立本地 V3 Schema，不导入任何用户数据。服务端启动检查 V3 的核心表和完整性约束。
9. **Skill 上传合同**：一次上传返回唯一 workId、workIds 单元素数组、imageCount、coverMediaId、coverUrl。Skill 既有开发分支持久化服务器回执与封面身份。
10. **权限安全**：默认不推断旧作品公开状态。匿名图片访问必须有有效 work/topic/asset 授权，且授权对象仍发布且图片仍属于该作品。管理员下架和图片槽位替换不会依靠遗留授权继续公开旧媒体。

## PostgreSQL 全新空库操作说明

默认执行：python -m ops.bootstrap_postgres_v3

上面只做 dry run，不会修改真实数据库。需要在**明确新建、完全空白**的 PostgreSQL 目标上设置 HANDRAW_DATABASE_URL 和 HANDRAW_ALLOW_PG_BOOTSTRAP=YES，然后执行：

python -m ops.bootstrap_postgres_v3 --apply

服务端 PostgreSQL 运行需同时设置 HANDRAW_REDIS_REQUIRED=1、HANDRAW_REDIS_URL 和 HANDRAW_PG_RUNTIME_ACK=V3_NATIVE。

注意：上面的代码已提交，但未在真实 PostgreSQL 服务及独立 S3/R2/MinIO 桶上运行过，因此不声称初始化已经验证成功。操作不会自动删除任何已有数据库。

## 暂不处理事项（用户明确要求先完成开发）

- Web GitHub Actions 与全量 Python/Node 测试，因 Runner/额度可能受限，暂不排查。
- 真实 Web ↔ Skill 上传与生成端到端、浏览器移动端、GIF 与多实例并发验收。
- PostgreSQL 全业务方言/触发器的实际运行验收、媒体存储恢复与 Redis 故障恢复验证，以及部署验证。

这些都是合并上线前的**验证门槛**，本轮不把它们算作已通过。Issue #84 保持 open，代码已提交不代表功能已上线。

## 2026-11-07 · 后续架构开发收敛（按要求暂不处理 CI/测试）

以下是代码提交状态，不等于已在真实环境验收：

1. 清除旧 SQLite 回填：个人素材库不再扫描旧文件或使用 PRAGMA / BEGIN IMMEDIATE 修复旧上传；新数据在写入时设置身份和变化序号。作品讨论帖回填已改成手工运行、PostgreSQL/SQLite 通用的当前作品关联修复。
2. 统一任务状态：generation_v3.refresh_run_status 只依赖 generation_items，Web 成功、失败退款、部分成功、取消都调用同一套逻辑，避免三份重复状态。
3. 批次历史删除：用户删除历史时支持 run ID、batch ID 和单次网关执行 ID，并在同一个事务中标记整个批次、隐藏关联作品；账单和退款轨迹保留。
4. 取消后的迟到请求：网关提交前锁定 run、检查已取消槽位；普通迟到提交返回 409，只有 UI 明确选择重试时允许 retryCancelled 解除取消状态。
5. 媒体回收：已结算的执行日志不再永久占用旧图片；替换图片时撤销作品和论坛旧授权，媒体 GC 通过权威 media_assets/work_media/generation_items 和仍有效的授权判断是否可以回收。
6. PostgreSQL SQL 适配：钱包免费额度选择时使用 FOR UPDATE；Seed 中 INSERT OR REPLACE 替换为 ON CONFLICT；资源管理的 sqlite_master 表检测改用 PostgreSQL information_schema；会话展示 ID 改为 token 不可逆哈希而非不存在的 id/SQLite rowid。
7. 安全读取：启动时绑定当前主数据库，prompt 黑盒安全扫描和画风目录查询不会在 PostgreSQL 模式误连到另一个 SQLite DB；移除旧黑盒历史 backfill 线程。
8. 空结果处理：上游即使宣称生成 success，若没有保存一张有效图，也进入失败和退款流程，避免成功任务空作品。

核心原则不变：每个逻辑生成任务最多一件多图公开作品；广场和主页只显示一张封面；Web/Skill 共用统一任务和媒体实体；不迁移任何旧数据。

暂缓范围：按用户要求，当前没有运行 CI、Python/Node 测试、真实 PostgreSQL/Redis/S3 集成测试、浏览器 E2E 或生产部署。功能代码是否完全正确尚待后续独立验收。
