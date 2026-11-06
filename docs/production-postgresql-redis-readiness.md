# Handraw 正式上线：PostgreSQL + Redis 改造与验收清单

> 状态：**生产化方案与配置模板修订，不代表 Python 2.0 已切换 PostgreSQL。**
> 本项目有两条运行时路线。上线前必须选定唯一的业务数据权威来源；不能把
> Discourse 的 PostgreSQL 与 Python 的 SQLite 互称为“同一生产数据库”。

## 1. 实际架构盘点

| 组件 | 当前实现 | 对 PostgreSQL + Redis 上线的含义 |
|---|---|---|
| Discourse / `plugin/` | Rails/ActiveRecord + PostgreSQL + Redis，`ops/server-deploy.sh` 发布插件 | 此路线已有基础设施与 PG 迁移、备份能力，仍需在隔离库验收 |
| Python Web 2.0 / `backend/` | `sqlite3`、WAL、线程本地连接、进程级 `RLock`、`BEGIN IMMEDIATE`、SQLite migration/trigger | **不兼容直接指定 PostgreSQL DSN**；必须改造 SQL、连接、事务、迁移与并发 |
| Python Web 部署 | `http.server.ThreadingHTTPServer` 单端口 3080 + Nginx；业务后台线程同进程 | 单个进程避免重复任务；多实例前需先做租约/任务幂等和跨进程协调 |
| Python 用户会话/限流 | SQLite sessions，进程内限流 | PostgreSQL 可持久化会话；Redis 用于限流/临时状态，不可覆盖持久化凭据数据 |
| 上传/创作文件 | 本地私有 `uploads/generated` | 多实例需独立私有对象存储或共享介质及权限校验；不可 Nginx 公共缓存 |

**选择建议**：若正式站点以 Web 2.0 的账号、作品、积分和 P2 增长功能为准，
以 Python 业务为迁移目标，单独 PostgreSQL schema 或 database（例如 `handraw_v2`）。
原 Discourse 的 PostgreSQL schema/身份体系不能不经映射直接承接这些 SQLite 表。
若以 Discourse 为唯一生产后端，需要将 Python 独有功能完整迁移到 Rails 插件，
不能仅保留一个只用来接收部分请求的 Python “第二个权威库”。

## 2. 目标生产拓扑

```text
                    HTTPS 443 / Nginx / TLS / 安全头
             handraw-style.com + studio/forum/admin 子域
                                  |
                    127.0.0.1:3080 (单 Python API)
                                  |
                         服务/事务与鉴权层
                         /              \
                PostgreSQL            Redis
         主业务唯一权威来源      短期缓存/限流/队列租约
                |                    |
         WAL/PITR/定期备份       TTL/内存上限/持久性策略
                |
     私有文件或对象存储 + 专属授权下载接口
```

如果继续部署原 Discourse，Discourse Web + Sidekiq 是**另一组明确隔离的服务**，
按现有 Rails 的 PostgreSQL/Redis 配置运行，不应让 Python 以相同业务表双写。

## 3. PostgreSQL 适配必须完成的项目

1. **连接与迁移**：独立 Postgres adapter（可使用 psycopg3 + 受控连接池），
   所有业务仅经统一数据库接口。明确 `HANDRAW_DATABASE_URL` 和数据库引擎；
   配成 PG 时必须禁止悄悄退回 SQLite。TLS 必须校验数据库证书。
2. **SQL 方言清单**：审计 `INSERT OR IGNORE`、`INSERT OR REPLACE`、
   `ON CONFLICT`、`last_insert_rowid()`、`sqlite_master`、`PRAGMA`、
   `json_extract`、`strftime`、`date('now')`、`AUTOINCREMENT`、
   `COLLATE NOCASE`、`?` 占位符、部分索引、SQLite trigger 和
   `executescript`。迁移 schema 要另建 PostgreSQL 版本，不直接执行 SQLite DDL。
3. **事务/并发**：`_write_lock` 与 `BEGIN IMMEDIATE` 只保证同进程内 SQLite
   顺序写入。改为 PostgreSQL 事务 + 行级锁/唯一约束/原子更新，
   并重点测试积分扣费与退款、日额度、库存、任务抢占、重复回调、邀请码、
   提交审核和第三方 OAuth 注册的竞态。
4. **池和超时**：连接池大小按实例数 × worker 数制定总预算；
   `statement_timeout`、`lock_timeout`、`idle_in_transaction_session_timeout`
   与 `application_name` 明确配置；采用最小权限独立数据库用户。
5. **数据和触发器**：迁移 `users`、会话散列、已验证邮箱、
   `oauth_identities`、作品/论坛、积分账本、收藏、创作任务与 P2 事件。
   使用序列、时区、约束和唯一索引的 PostgreSQL 语义重新实现通知和增长触发器。
6. **在线迁移与回退**：先备份并验证恢复，然后在隔离库演练
   SQLite → PG ETL → 行数/主键/外键/余额/媒体校验和核对 →
   停写窗口最终同步 → 只读验收 → 切换流量。不要两库双写且不做一致性检查。
   数据库 schema 只向前迁移，代码回退不能擅自降级 schema。

## 4. Redis 的边界

- 适合：按用户+IP 的统一限流、短生命周期 OAuth state **及一次性消费的原子保障**、
  登录失败退避、热点公开列表短缓存、任务通知/轻量工作队列租约。
- 不适合：唯一的账号记录、积分余额/账本、购买和退款、审核裁决、
  永久作品元数据、已验证身份映射。**PostgreSQL 才是这些数据的权威库。**
- 键统一前缀 `handraw:prod:`，预览/测试使用隔离实例或独立前缀与 ACL。
  所有缓存设置 TTL，控制容量和淘汰策略；保密数据必须访问受限，
  不在日志中打印会话/OAuth 凭据。
- 关键写入不能依赖 Redis 的“尽力缓存成功”来保证金融与安全一致性；
  付款/退款/授权最终状态始终由数据库事务确定。

## 5. 部署、备份和运维验收

- 生产 API 在 Nginx 后只绑定 `127.0.0.1:3080`；四域名指向同一进程，
  Nginx 示例：`ops/nginx-handraw-v2.conf.example`。用真实服务器证书路径替换示例，
  `nginx -t` 后才 reload。**私有 `/uploads/` 和 `/generated/` 不强制公开缓存**。
- PostgreSQL 管理日志/慢查询/连接池饱和告警；Redis 连接失败、命中率、内存/淘汰、
  队列滞留和 key TTL 监控；请求错误率、p95/p99 延迟、任务退款率、安全邮件队列也入监控。
- PostgreSQL 做自动备份 + WAL/PITR，设置 RPO/RTO，定期执行**异机恢复演练**；
  作品图片和私有文件须独立备份及访问校验。Redis 缓存丢失应能重建。
- 生产密钥：数据库和 Redis 凭据、Google/GitHub OAuth 凭据、SMTP 和生图网关密钥
  放权限受控的 secret store 或服务环境，不进入 Git。第三方 OAuth 两个实际回调
  分别是 `/api/auth/google/callback`、`/api/auth/github/callback`。
- CI 在临时 PostgreSQL + Redis 中运行事务/并发与端到端测试；生产迁移前应完成
  账号注册、邮件验证/重置、OAuth 绑定、收藏/创作、积分扣费退款、用户数据导出、
  P2 cohort 和禁用账号注销的验收。不能只通过静态语法检查。
- 在得到运维授权且**生产备份已验证**后，使用固定提交 SHA 发布；
  新部署必须有健康检查与代码级回退路径。未通过全量 CI 的候选版本不能称为上线就绪。

## 6. 目前的阻断项

- Python `backend/db.py` 仍是纯 SQLite 管理器，无 PG adapter 或正式的数据转换工具。
- Python 的业务模块有大量 SQLite SQL 与事务假设；尚无 PG 迁移集成测试。
- `ops/server-deploy.sh` 发布的是 Discourse 插件，并非 Python v2 的完整发布包。
- OAuth/SMTP 实际凭据、上线服务器环境、备份策略和负载指标尚待验证。
- **截至本文件创建：本次没有执行生产数据库迁移、Redis 切换或部署。**
