# Studio 2.0 · Phase 23 · #132：官网目录来源锁定与物理 PITR 收据加固

> 2026-11-10；独立分支 `studio2-issue132-phase23-source-pitr-20261110`；从 `studio2@9aa58176d7c51372de627342fd5a6e85e7960fac` 派生。本项工程为 **C-level fail-closed** 加固，不是官网批准或真实 D 级验收。严禁合入 `main`；PR #131 始终 Draft，Issue #132 持续 Open / NO-GO。

## 发现的两处来源绑定缺口

### 1. FF-018 / FF-019 / FG-025 的 Skill 来源不能由外部 JSON 冒充

Phase22 的 `check_skill_checkout()` 已验证 Skill Git 目录为固定完整 40 位 HEAD、无修改和未跟踪文件。但 `--skill-styles` / `--skill-layouts` 仍允许任意路径；即使所提交的 Skill checkout 真正干净，独立提供的样式/图型文件也不一定来自该 HEAD，从而使严格对账的证明链缺少关联。

Phase23 `load_pinned_skill_sources()` 额外实施：

1. `--skill-checkout` 必须为干净、非 symlink 的本地 Skill Git 检出，HEAD = `--skill-sha` 的**完整 SHA**；
2. `--skill-styles` 和 `--skill-layouts` 必须分别指向该检出树下真实非 symlink 的 `skills/handdraw-style-prompter/references/styles.json` 和 `skills/handdraw-style-prompter/references/layouts.json`，不能是其他位置即便内容相同的 JSON；
3. 使用 `git show <exact-SHA>:references/styles.json` 和 `git show <exact-SHA>:references/layouts.json` 读取 Git 对象，校验内容与 checkout 一致，拒绝 Git 中不存在的文件、脏树、JSON 漂移；
4. **只能把此 Git SHA 绑定的目录送进 Phase21 的 Ed25519 双签审核、Web 官方已批准 PG17 原始行 SHA、Web↔Skill `--strict` 校验**。脚本不会审批候选，也不会修改 Skill main / Web DB。

独立官网真实来源、商用许可、权利原件、行动日志、双人角色真伪仍需有权限的审核人核实。官网当前静态 537 与 Skill 540 的三个候选仍为 pending，不能用同名 JSON 替代正式网站发布动作。

### 2. PG17 物理异机 PITR 收据时间/LSN 校验

`studio_phase22_field_receipts_132.py` 过去仅检查 `targetUtc` 的字符串格式与 `recoveredReplayLsn` 的十六进制斜线结构。Phase23 拒绝：

- 不存在的日历日期、错误 UTC 格式、超过当前审核时间 5 分钟的未来 PITR target；
- 超过 30 天的新鲜度上限的旧目标（对应现有 D 级现场审核时限；如需历史恢复另建被审核协议，不可借旧票证通过当前发布）；
- `0/0` 零 LSN、过长 32-bit LSN 分段、非 PostgreSQL LSN 格式；
- 既有的同物理主机、业务/钱包/媒体指纹不一致、超出 RPO/RTO 预算仍保持阻断。

**结构正确的 JSON 不能证明**恢复主机身份、WAL 从独立归档读取、PG17 `pg_verifybackup`、真实业务恢复、计时器或回退成功。真实演练由现场人员在授权隔离预生产环境操作，保留 PG 日志/WAL/宿主机清单原始凭据至私有受控仓，第二审核人复核；这不是 CI 职责。

## 17 项 D 门禁仍全部待真实签核

原有矩阵、`ops/studio_d_environment_assertions_132.py`、`ops/studio_d_receipt_contract_132.py` 和 Phase22 的四项报告仍是权威的离线结构检查入口；**未新增任何可自主产生 GO 的路径**。

- **官网授权**：三个独立签名材料 + 官网已批准原始 PG17 DB 行 + Skill pinned SHA 的 Git 来源 + strict parity，经人工独立审核；FF-018/FF-019/FG-025 逐项失败则全部保留 pending。
- **PG17**：真实物理异机 `pg_basebackup`、WAL/PITR 恢复目标、RPO/RTO、回滚、业务与钱包与媒体指纹、源/恢复机身份、第二见证。
- **R2/S3/CDN**：真实双 tenant 独立凭据及读写双向拒绝、匿名 403、有效/过期/撤销签名链接、下架旧 CDN URL、恢复对象字节摘要；Moto 假网关不算 D。
- **Redis**：两台真正独立的 Web 实例和物理故障切换，fencing epoch、旧主拒写、恢复幂等、跨租户 ACL；单 Redis 多客户端 NX 探针不算 D。
- **供应商**：真实已结最终发票与 Web run/item/attempt/callback/钱包/免费额度逐笔独立核账，覆盖 429、502、unknown、late success、重复回调、退款；模拟账本不能算 D。
- **物理低端设备**：真实 CPU/GPU/触屏/弱网/300 节点高负载诊断；约 9,185 元素 UpdateLayoutTree 没有唯一根因/双 CPU 稳定获益之前，不触动生产 CSS/JS。
- **独立签核**：全部 17 项同一已部署 Web/Skill SHA，真实 UTC、操作人和不同复核者、来源摘要、环境身份、回滚计划。无原件/第二签名任一缺失均 BLOCKED。

## 工程验证与快进纪律

```bash
python -m unittest tests.test_studio_phase22_official_provenance_132 tests.test_studio_phase22_field_receipts_132
```

在**独立分支**同 SHA 14/14 CI 全绿，检查与当前 studio2 的 `ahead>0,behind=0`、PR #131 Draft、`main` SHA 不变、仅 `ops/tests/docs` 之后，才可 `update_ref(expected_sha=<previous-studio2>, force=false)` 安全快进；然后复核 studio2 Push 和 PR #131 两套**相同 HEAD** 14/14 成功。否则停在工程分支，不伪造 D 级证据。

发布决策 **NO-GO**（直到所有真正 D 原始证据及官网授权到位，经独立责任人批准）。任何 GitHub CI 成功只代表 C 级离线质量门禁。
