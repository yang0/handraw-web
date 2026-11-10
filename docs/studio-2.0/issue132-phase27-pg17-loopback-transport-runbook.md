# Studio 2.0 · Phase 27 · PG17 物理恢复只读验收的 DSN 本地性与连接端点绑定

Issue #132 | 2026-11-10 | **预生产限定、C 级安全工程、生产始终 NO-GO**

## 故障路径

`ops/studio_phase21_pg17_physical_pitr_132.py::verify_restored` 原本只检查 `settings(target_dsn).host` 是 `127.0.0.1` 或 `localhost`、恢复主机名匹配；但 libpq 的 `hostaddr`、`service` 及默认环境 `PGHOSTADDR`、`PGSERVICE`、`PGSERVICEFILE` 可能影响**实际连接目的地**。DSN 显示 `host=localhost` 并非真实数据库位于本机的充分证明。尤其后续 `fingerprint(target_dsn)` 会开**第二条连接**，必须绑定同一物理网络目标。

## 补强

- **连接之前**检查 `settings(target_dsn)` 无 `hostaddr/service/servicefile`，且前述三个 PG 环境默认覆盖项均未设置；恢复主机 `declared_host` 必须仍与当前专用恢复主机身份匹配。
- 使用 `psycopg.conninfo.make_conninfo(target_dsn,host='127.0.0.1',hostaddr='127.0.0.1')` 强制两次核验连接均使用数值回环目的地，不接受外部 DNS 解析或隐式连接重定向。
- 只读事务建立后，先运行 `SELECT inet_server_addr()`，只接受真实返回地址 `127.0.0.1` 或 `::1`；若返回远端地址、NULL 或格式不符，停止在 PG17 版本、WAL replay 和业务表检查之前。
- 第二次业务指纹调用使用**同一个已规范化的 DSN**，不再重用未经钉住网络目的地的原始 DSN。
- 继续执行只读 PG17 `server_version_num`、`pg_is_in_recovery()`、`pg_get_wal_replay_pause_state()` 和 `pg_last_wal_replay_lsn()` 检查、对账 wallet/media 等表的业务指纹，并返回 `decision=NO-GO`。此过程不含自动启动 PostgreSQL、写入源库、删除任何数据库或操作生产流量。

## 授权现场执行前提

需先按 Phase26 的 `preflight` 取得独立恢复主机证明、专用隔离数据目录、独立 WAL 归档及第三方/第二审核员签署的真实源/恢复身份。受控 DBA **人工**启动本机恢复副本，暂停在确定的 PITR target；只有这个上下文允许核验。**本机 127.0.0.1 并不排除现场部署了恶意/错误的本地 TCP 代理转发**，所以代码断言并不能替代人工审查进程、PGDATA、PG system identifier、容器/网络命名空间和真实服务器来源；任何此类不确定性继续 fail-closed、按 D 级 NO-GO 处理。

## 负向回归

`tests/test_studio_phase21_pg17_physical_pitr_132.py` 使用 FakePg、Mock、临时目录，不调用真实 PG，验证：

- `hostaddr`、`service`、`servicefile` 原始配置应在发起连接前被拒绝；
- `PGHOSTADDR`、`PGSERVICE`、`PGSERVICEFILE` 环境默认值亦必须在发起连接前被拒绝；
- 实际 `inet_server_addr()` 返回 10.x、公共测试网地址、NULL 则禁止业务指纹；
- 正常回环连接只接受规范化后的 `host=127.0.0.1 hostaddr=127.0.0.1`，核验连接与业务指纹第二条连接必须完全一致；
- 所有假数据的通过仍 `decision=NO-GO`，没有实际 D 级通过。

## 合入规则

Phase26 正式 studio2 Push #42731592061 和 PR #42731598737 必须先完整 14/14；Phase27 独立 `studio2-issue132-phase27-pg17-loopback-dsn-20261110` 自身同 SHA 14/14；先检查 ahead>0/behind=0、PR #131 Draft/未合并、main 不变和差异仅 ops/tests/docs，之后才能用 `expected_sha`、`force=false` 快进 studio2，再核验正式 Push/PR 双 14/14。

官方 FF-018、FF-019、FG-025 仍需实际官网合法授权，17 项 D 级生产验收实际独立 PASS 仍为 **0/17**，Issue #132 Open / NO-GO。
