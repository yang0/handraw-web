# Studio 2.0 · #112 / #84 生产级 D 门禁执行手册

2026-11-09 · 工作起点 studio2@3ee76a00b3020e798242fcbf645efc9c39fce504。

**当前结论：NO-GO。PR #131 必须继续 Draft，严禁合入 main。** 本文是操作规约，不是生产验收成功记录。未经授权不得对生产数据库停机、恢复、迁移、写入或调用付费供应商。保密证据保存在授权的运维系统，不上传 Git、Issue、Actions Artifacts。

## 1. 已验证代码与缺失的现场证据

| 范围 | 现有 C 级受控证据 | 缺失的 D 级证据 |
| --- | --- | --- |
| 网关/账本 | tests/test_studio_billing_112.py 的真实本地账本 + Mock 网关，状态未知不猜测退款，Bearer 302 禁止跨域转发 | 供应商任务/扣费/退款、真实回调、双向账实核对 |
| PG17 | ops/pg_release_restore_drill_112.py 的 pg_dump custom **逻辑备份**、两个空库恢复和逐表指纹 | 停库的**物理冷备**、异机恢复、迁移 101/102、实际切流/回滚、RTO/RPO |
| 媒体 | boto3 + Moto S3 私有媒体、Web HTTP 与 PG17 联测 | 实际 R2/S3/MinIO/CDN 的桶策略、越权、签名失效和匿名访问 |
| Skill ↔ Web | 固定 Skill SHA 9542512c8fd49cd8a5bbc02b9378b82b6e6e9c24 的实际 CLI 1/5 PNG + 双帧 GIF，PG17 + Moto | 独立主机和真实网络/对象桶/Redis 多实例/移动终端 |

D 级证据必须绑定部署完整 SHA、配置版本、环境、UTC 时间、操作人、审核人和受控证据 ID。CI 的 14/14 不能替代外部证据。

## 2. 真实供应商网关：双向对账规约

### 2.1 授权人员准备的三份只读来源

从 PostgreSQL 权威记录、供应商任务与计费账单、Handraw 请求/回调日志分别导出。原始账单要留在权限隔离的审计环境，并能相互回查；公开报告只使用脱敏关联键。

| 字段 | 作用 |
| --- | --- |
| runId、itemId、slotKey、batchIndex | 一条逻辑任务 / 计划槽位身份 |
| requestId、attempt、providerTaskId | 实际提交、重试、回调与幂等关联 |
| providerAccountId（脱敏）、model、submittedAt、terminalAt | 供应商账单主体、版本、UTC 窗口 |
| providerState、gatewayHttpStatus、callbackEventId | 确定供应商是否收到任务、终态与重复回调 |
| providerCurrency、providerChargedMinor、providerRefundedMinor | **供应商货币**最小单位 |
| ledgerEventKey、walletDeltaCredits、walletBalanceAfter、freeQuotaDelta | **Handraw 积分/免费次数**不可变账本 |
| workId、mediaId、moderationState | 一 Run 最多一 Work、审核墓碑和媒体授权 |

严禁导出 Bearer、Cookie、签名媒体 URL、用户身份资料、隐藏/黑盒提示词、原始图片字节、完整私人请求正文。

### 2.2 逐单核验步骤与一票否决

1. 固定供应商账期、异步回调最大延迟、时区与已部署代码 SHA。**由供应商每一条 charge/refund → Handraw 的 requestId/attempt**，再反向从 Handraw 每次实际提交 → 供应商任务/账单，列出双方孤儿记录。
2. 对 (providerAccountId, providerTaskId, attempt) 核对收费唯一性，对 ledgerEventKey 核对扣款与退款幂等；重复 webhook、轮询、刷新或客户端断线不得重复扣/退。
3. **供应商货币和 Handraw 积分不能相加直接对比**。先各自按单位求净额：providerChargedMinor - providerRefundedMinor，walletDeltaCredits 和 freeQuotaDelta；依据经过授权的资费/免费额度规则核对转换关系。
4. 分开标记 succeeded、权威 failed、权威 cancelled、unknown、duplicated/replayed、供应商收费但无媒体、媒体已成功但供应商无可查任务。unknown 即使超过 30 分钟、查询返回空集合，也不得推断供应商没收到或擅自退款/重扣。保留原 wallet ledger，通知人工处理。
5. 现场至少覆盖真实 429、502、超时、迟到成功、停止/取消、3 成功 2 失败、重复回调、请求重试、已退款后的晚到结果、无返回 providerTaskId。仅客户端 AbortController 不是供应商取消成功。
6. 每项不一致必须有 reason、owner、providerEvidenceId、ledgerEvidenceId、disposition、observedAt。**存在资金差异、不可查的付费任务或缺失权威退款确认，NO-GO**。工程与财务/业务授权人员独立复核，不可为了对平而直接写钱包。
7. 约定 unknown 的人工处理 SLA、用户侧待确认提示和告警通道。未得到供应商查询能力、真实账单凭证及负责人签名，不签发 D 级通过。

## 3. PostgreSQL 17 物理冷备与恢复：操作员手册

### 3.1 核心区别和预条件

现有 CI 中的 pg_dump --format=custom / pg_restore 是**逻辑**备份；真正**物理冷备**必须在 PostgreSQL 17 实例**正常、完整停止**后复制完整 PGDATA、WAL 和全部表空间，保留物理文件身份及权限。pg_basebackup 是另一个在线物理备份机制，不能冒充停库冷备；仅复制 base/、在线直接复制 PGDATA 或仅备份 schema 都不符合本规约。

准备且经双人审批：实例版本 17.x / OS/CPU、data_directory、config_file、hba_file、ident_file、pg_wal 和 pg_tblspc 实际位置、所有外部 tablespaces、extensions、locale/collation、文件系统、服务管理方式。约定维护窗口、业务批准的 RPO/RTO、离站加密备份位置、完整磁盘空间、机密管理及 rollback owner。托管 PG 若不允许完整停机和读取数据目录，不得声明完成物理冷备，必须与供应商另设可审核的备份/PITR 策略。

### 3.2 现场执行步骤（人工审批，不由 CI 自动停机）

1. **运行时采样**：DBA 读取 SELECT version()、SHOW data_directory、SHOW config_file、SHOW archive_mode、表空间路径、schema_migrations、账本、generation_runs / works / work_media 计数和指纹。日志和工件不能含连接 DSN 或密钥。
2. **写入冻结**：停止新 Run/上传/收费，以及所有异步 Worker、队列消费者；等待运行中事务达到可恢复边界。记录最后一个账本事件、Run/Item 和对象存储同步时点；API 停止但后台依然写入不算冻结。
3. **完整停库**：授权 DBA 使用部署服务管理器正常执行 PostgreSQL 17 fast shutdown，等待退出，核查 shutdown checkpoint、进程与 postmaster.pid。未确认完全停止则中止冷备，不能边运行边直接复制。
4. **安全复制**：复制完整 PGDATA，包括 global/、base/、pg_wal/、pg_xact/、pg_multixact/、pg_tblspc/ 符号链接；逐个复制 pg_tblspc 指向的**外部表空间物理目录**，以及 PGDATA 外部配置/相关部署元数据。保留 owner/mode/ACL/symlink；跨挂载点确认不存在被排除的卷。禁止覆盖已有备份。
5. **校验与存档**：独立备份目录权限 0700、文件权限不放宽；对清单/容量/完整文件计算 SHA256，记录开始与结束 UTC、源版本、volume/表空间列表、操作者、机密保存位置，并校验加密备份副本在另一故障域可取。不要把包含原始文件名或数据的清单上传公开 Issue。
6. **隔离恢复**：在另一台没有用户流量、支付、邮件、对象删除和外部图像网关调用的独立 PostgreSQL 17 主机，把物理备份还原到**新空目录**，映射相同版本/权限/表空间路径/扩展/locale；以独立端口启动、查看 WAL/恢复日志、比对账本/所有关键表指纹、约束与 V3 作品媒体关系。**永不覆盖原 PGDATA**。
7. **迁移演练**：先查看该部署实际 schema 版本，再仅在恢复副本执行已审定的 migration 101/102 和相应 dry-run/apply；记录失败注入、锁表、旧版回退兼容、前后账本/媒体权限。实际生产可能已有部分迁移，不能盲目重复执行。
8. **物理回滚演练**：停止模拟新版本写入，再从原冷备恢复到**另一个全新隔离目标**；验证数据指纹、余额、媒体授权及旧版服务启动和恢复耗时。事务 rollback 不能等于结构迁移后的物理恢复。若切流后产生新写入，旧快照回滚会丢数据，必须事先审批写入冻结/重放方案，禁止盲目替换。
9. **记录签核**：记录 backupEvidenceId、restoreEvidenceId、rollbackEvidenceId、实际 RTO/RPO、错误及解决方案。达不到业务批准数值或未恢复真实媒体/权限则 NO-GO。

连续 PITR 必须另外完整验证 WAL archive 与恢复点；单次停库冷备不代表已经实现 PITR。Redis 缓存不是数据库权威事实，数据库快照和对象存储数据的**一致性边界**需要单独演练。

## 4. 真实对象存储的只读防泄漏探测器

新工具：ops/audit_object_leak_112.py，回归：tests/test_audit_object_leak_112.py。该工具只发 GET Range=0-0、**不读取响应体**、不改对象、不跟随重定向、不使用未经列明的 host；默认只允许 HTTPS，Loopback HTTP 只用于显式单测。禁止上传/提交实测 manifest、Bearer、Cookie、完整签名 URL 或对象明文。

| 必填 case id | 操作员准备的真实 URL | 必须结果 |
| --- | --- | --- |
| public_work | 已发布 Work 的图片 URL，无认证 | 200/206 + image/* |
| private_owner | 私有图片 URL，作者 A 凭据 | 200/206 + image/* |
| private_anonymous | 同一私有图片，匿名 | 401/403/404 |
| private_cross_user | 同一私有图片，独立 B 账号凭据 | 401/403/404 |
| hidden_work | 已下架/删除授权的旧图片 URL | 401/403/404 |
| private_bucket_object | 绕过 Web 的桶中私有对象直链 | 401/403/404 |
| expired_signed_url | 已过期的真实签名 URL，附过期 UTC | 401/403/404 |
| bucket_listing | 匿名桶目录列举 GET | 401/403/404 |

Manifest 结构：schema_version=1、environment=staging/preproduction/production、release_sha=40 位十六进制字符串、cases 为上述八个恰好各一条。每条含 id、url、expect；private_owner 与 private_cross_user 还须含 auth_env（形如 HANDRAW_AUDIT_OWNER_COOKIE）和 auth_kind（cookie 或 bearer）；expired_signed_url 还须含 expired_at_utc，例如 2020-01-01T00:00:00Z。expect 对前两者是 allow，其余都是 deny，无法通过改期望绕过安全门槛。

私有 manifest 保存于限定读取权限的目录（不进 Git），实际环境以操作员私下创建的测试媒体和经授权账号验证归属：

    python -m ops.audit_object_leak_112 \
      --manifest /private/studio112-media-manifest.json \
      --report /private/studio112-media-report.json \
      --allowed-host site.example.invalid \
      --allowed-host bucket.example.invalid \
      --allowed-host cdn.example.invalid

Token/Cookie **只能通过 HANDRAW_AUDIT_* 环境变量**注入，不传 CLI 参数。报告使用新建 0600 文件且不覆盖，**只记录 case ID、HTTP 状态、是否通过、部署 SHA**，绝不回显 URL / 密钥 / 响应体；302、500、TLS 失败、缺授权凭据和错误 Content-Type 均不得误判为通过。工具即使八项都通过，也**始终输出 decision=NO-GO**：它只是访问观察，不自动宣布生产合格。

授权审计员必须验证测试对象归属、同一媒体跨账号、签名确实已过期（包括真实 URL 内有效期）、对象存储策略/ACL、S3 Block Public Access/R2/MinIO 配置、CDN cache 和源站回源安全。还必须执行：下架后旧 URL 在不同实例不复活、缓存失效、私有引用不能越权、Media GC 不误删共享媒体。真实对象桶未检测之前该门禁为 PENDING。

## 5. #84 Web ↔ Skill 的 D 级实测矩阵

需要独立主机的 Skill CLI、实际部署的 Web、PG17、Redis、多实例和真正对象桶，至少 A/B 两个可独立认证账号。记录 Web 完整 SHA、Skill SHA、Run/Work/Item/Media 关联键、UTC、对象 provider、审核状态及截图/日志的私有证据编号。

| 场景 | 判定事实 | D 级状态 |
| --- | --- | --- |
| 单图成功 | 1 Run、1 Work、1 Media，广场/主页一张卡，详情一张 | PENDING |
| 五图乱序 | 同一 externalRunId，5 items、1 Work、5 Media，封面按 slot 排序 | PENDING |
| 3 成功 + 2 失败 | 5 slots、3 有效媒体、1 Work、详情 3 张 | PENDING |
| 全失败 | 1 Run、0 Work，保留失败历史，退款据供应商权威确认 | PENDING |
| Skill 断点续传和幂等 | 仅显式 history upload 上云；重放只补缺失对象，不重建 Work/扣费 | PENDING |
| GIF + 移动端 | 两帧 GIF 原件、静帧封面、实际触屏/390px/多浏览器 | PENDING |
| 作者换封面 | 主页、广场、搜索、OG 一致；Work 身份不变 | PENDING |
| 下架与迟到结果 | 隐藏墓碑、旧媒体 URL 拒绝；晚到成功不能重新公开 | PENDING |
| Redis/S3/多进程故障 | 租约、幂等锁、对象恢复、跨实例缓存失效与账本一致 | PENDING |

每场的私有证据格式：testCaseId、deployedSha、skillSha、runId、workId、observedAtUtc、storageProvider、expected、observed、artifactEvidenceId、operator、reviewer、PASS/FAIL/BLOCKED。公开 Issue 只写不含隐私的证据 ID 和汇总结论；没有真正运行不得写 PASS。现有 PG17+Moto 真实客户端 CI 属于 C 级，不可冒充此表已完成。

## 6. 生产 Go / No-Go 与分支纪律

任何真实供应商对账差异、支付/退款权威不明、物理冷备异机恢复失败、真实对象桶越权、跨用户 IDOR、业务数据恢复不一致、移动端/弱网未测、灰度/监控/签核缺失，均保持 **NO-GO**。#11 的 FG-025 官方编号差异仍为发布严格检查阻断，不能靠普通 CI 放行。

先 Issue 登记 → 独立分支 → 本地测试 → 分支 14/14 GitHub Actions 全绿 → compare 确认没有落后/无远端竞态 → update_ref force=false 且 expected_sha 匹配，快进 studio2 → 核对 studio2 Push、PR #131 的同 SHA 14/14。没有全部成功，只保留独立分支，不改 main，不关闭 #112/#84，不转 PR Ready。
