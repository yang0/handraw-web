# Studio 2.0 Phase 26 · PG17 物理异机 PITR 演练的路径/主机隔离约束

Issue #132 | **C 级只读安全加固，生产始终 NO-GO** | 2026-11-10

### 背景

原 `ops/studio_phase21_pg17_physical_pitr_132.py` 在 `plan/backup` 检查 WAL 归档目录与恢复根目录不相同/不互为祖先，但 `prepare/verify` 的 CLI 分支只判断目标目录已存在；同时 `_dir` 原本只检查目录**本身**是否是符号链接，没有检查祖先组件。`prepare_pitr` 会修改隔离恢复目录的 `postgresql.auto.conf` 并写 `recovery.signal`，因此路径、主机和 WAL 范围必须在文件写入之前校验。

### 本切片新增安全断言

- `_dir` 限制绝对路径、禁止 `..`、仅允许路径安全字符、**拒绝根目录 `/`**，从目标一路检查到根的每一个路径组件是否为符号链接；不能仅靠末级 `is_symlink()`。
- 用统一 `_host_pair` 对 source 与本机恢复 target 进行标识与独立性检查；`prepare/verify` CLI 与 `plan/backup` 使用同一套校验，不能以“恢复目录已经存在”为理由跳过主机身份检查。
- 用统一 `_separate_directories` 排除 WAL 目录与恢复根目录相等或互相嵌套；`prepare_pitr` 直接 Python 调用亦再次拒绝 WAL 包含/嵌入恢复数据目录。
- `run_backup` 不再相信调用方传入的任意 `plan` 字典：独立校验预生产标识、受控随机目标叶子、源/恢复主机、归档目录及恢复目录的父级路径，**在调用 `pg_basebackup` 前**阻断伪造 plan。
- 恢复文件只会在这些检查通过后写入；原始的 pg_basebackup、pg_verifybackup、人工启动隔离 PG 以及观测报告的 `NO-GO` 语义完全保留。没有新增破坏性 SQL、rm、drop、外部 API。

### 离线负向回归

测试文件：`tests/test_studio_phase21_pg17_physical_pitr_132.py`

包含：
1. 上级 symlink 的恢复根目录与 WAL 归档目录、根文件系统 `/` 拒绝。
2. 伪造 `plan` 的生产环境、同主机源/恢复、WAL 与恢复根目录重合、非受控恢复叶子在调用 runner 前拒绝。
3. 独立 Python 入口 `prepare_pitr` 必须先拒绝 WAL 位于恢复数据目录之下、WAL 目录包含恢复数据目录、恢复目录祖先 symlink；`postgresql.auto.conf` 保持原字节，`recovery.signal` 不得被创建。
4. CLI `prepare` 和 `verify` 的嵌套 WAL / 同主机参数拒绝，验证 `verify_restored` 从未执行。
5. 保持已有 PG17 物理 basebackup + pg_verifybackup 的 FakeRunner / read-only fingerprint 合同测试。

CI 只使用 Python unittest Mock、临时目录和假 WAL。测试不能证实实际 PG17 物理异机恢复、RPO/RTO、独立机房、实体回滚；实际现场必须由授权 DBA 在预生产独立主机执行，原始 backup manifest/WAL/业务指纹由审查员人工对账，绝不把模拟证据标成 D 级 PASS。

### 执行纪律

先登记 #132，再独立 `studio2-issue132-phase26-pg17-path-safety-20261110` 开发。Phase25 正式 `studio2` Push #42729704277 与 PR #42729717711 双 14/14 **必须先完成**；Phase26 独立同 SHA 14/14、compare ahead>0/behind=0、main 不变、PR #131 Draft/未合并后，才能用 `expected_sha` 和 `force=false` 快进 `studio2`，继续正式 Push/PR 双 14/14。

Issue #132 继续 Open/NO-GO；FF-018 / FF-019 / FG-025 未经官方网站实际授权，不自动发布。17 项 D 级真实独立核验仍为 0/17。
