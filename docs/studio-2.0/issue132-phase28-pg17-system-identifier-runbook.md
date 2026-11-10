# Studio 2.0 · Phase 28 · PostgreSQL 17 物理恢复集群身份双端关联

Issue #132 · 2026-11-10 · **仅授权隔离预生产、C 级工程，NO-GO 不变**

## 发现的问题

Phase26/27 已分别锁定恢复目录/WAL 独立路径和 loopback DSN 并检查真正服务端回环地址。但仍可能连接到**同一恢复主机上的另一个 PG17 实例**：这个实例同样可能 `pg_is_in_recovery()=true`、暂停 WAL，甚至有相同的 wallet/media 业务行。仅匹配部署主机、PostgreSQL 大版本及业务指纹，不能证明物理 basebackup 与 WAL 来自声明的原始源集群。

PostgreSQL 17 官方提供只读 `pg_control_system()`，其中 `system_identifier` 表示数据库集群身份。此值必须与**从源端独立取得、预先封存**的 system identifier 匹配。注意这仅是同源性的一项**必要检查**，不证明真实 WAL 字节、物理机独立性、来源真实性、备份恢复 RPO/RTO 或发布许可。

## Phase28 执行合同

`ops/studio_phase21_pg17_physical_pitr_132.py::verify_restored` 现要求 `--expected-witness` 原来的私有 JSON 增加必填：

```json
{
  "schemaVersion": 1,
  "targetUtc": "2026-11-10T00:00:00Z",
  "backupManifestSha256": "<真实 backup_manifest 字节的 sha256>",
  "sourceSystemIdentifierSha256": "<真实源集群 system_identifier 十进制字符串的 sha256>",
  "expected": {"rowCounts": {}, "rowSha256": {}}
}
```

这只是示意结构；`expected` 中的实际业务指纹必须包含既有验收的关键表，绝不能用示意的空表通过真现场验收。源系统标识必须由有授权的 DBA 在**源预生产集群**中独立只读采集，再由第二审核员登记并带外签名。生成规则：

1. 通过 `SELECT system_identifier FROM pg_control_system();` 获得 PG17 **源集群**标识。检查其是无符号有效的正整数；没有权限或来源不可信就停止并记录 BLOCKED。
2. 将其转为无空格、无符号、无前导零（零本身也不合法）的 canonical ASCII 十进制字符串，例如 `1234567890123456789`。
3. 对这串 ASCII 字节计算 SHA-256；仅将摘要置入经过受控签核的私有 `sourceSystemIdentifierSha256` 字段。原始来源记录必须存于独立审计系统，**不得上传 GitHub/Actions**。
4. 在隔离恢复主机上，Phase27 的 `host=127.0.0.1 hostaddr=127.0.0.1` 实际连接与 `inet_server_addr()` 限制先运行；PG17 版本、`pg_is_in_recovery()`、暂停 WAL、replay LSN 必须先有效，然后只读查询恢复目标 `pg_control_system().system_identifier` 并进行相同 canonical digest，对比独立源见证摘要。
5. 缺少 hash、格式错误、来源/目标不匹配、返回非法类型或权限不足均拒绝，**不进行后续业务表 fingerprint**。仅一致时才继续现有业务对账、Undo/RPO/RTO 离线复核。

结果仅新增布尔 `clusterIdentifierMatchesOutOfBandClaim=true` 与 `sourceClusterIdentityIndependentlyAuthenticatedHere=false`。默认运行仍严格只读，保持 `physicalClusterAndWALProvenByThisReport=false`、`independentHumanAuditStillRequired=true` 和 `decision=NO-GO`。此工具无法证明提供的源端 hash 是否真实，外部双人审查不可由代码代替。变更后的 witness 合同故意 **fail-closed**，旧格式的现场 JSON 不得静默兼容。

## 测试与门禁

`tests/test_studio_phase21_pg17_physical_pitr_132.py` 的 FakePg 增加 `pg_control_system()` 响应。负向用例覆盖：缺少来源摘要、非 64 字符十六进制摘要、错误但格式合法的摘要、不同源集群、空值、bool、字符串、零、负数、无权限，以及无法进入业务 fingerprint 的断言。全部 Mock，本次 CI 不接数据库、无真实物理 WAL、无真实供应商调用。

Phase27 正式 `studio2` Push #42751800904 和 PR #131 #42751806233 必须先全部 14/14；Phase28 独立分支自身先 14/14，再复核 ahead>0/behind=0、PR Draft、main 原 SHA，随后才能 `expected_sha` + `force=false` 安全快进 studio2，正式 Push/PR 再独立 14/14。

**发布红线：**FF-018、FF-019、FG-025 仍缺真实网站官方授权，17 项真实 D 外部核验 0/17，Issue #132 Open / NO-GO，PR #131 Draft，main 绝不改变。
