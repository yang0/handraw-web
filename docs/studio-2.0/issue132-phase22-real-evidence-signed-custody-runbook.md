# Studio 2.0 · Phase 22 · #132 真实签名、现场取证与 17 项 D 门禁对账

日期：2026-11-10。工程基线 `studio2@9ba7cd20d1f258e56fd0b737bf4feee7d397342d`，PR #131 **始终 Draft**，`main` 保持不动，#132 **Open / NO-GO**。本阶段交付“有现场凭据时可执行的验签/对账工具”，**未获得真实官网管理员许可、供应商账单、生产等价 PG17/R2/S3/Redis 的现场授权和审计材料**，故没有进行线上修改、私网探测或真实 D 验收。任何纯 JSON 自填、CI、签名密钥演示/受控 fixture 都不能替代现场真实性。

## 1. 三项候选的官网审批真实闭环

仍为 pending：**FF-018 Low Poly Art、FF-019 Hyperreal 3D Cartoon Portrait、FG-025 Perler Bead Pixel Art**。先按原有 `studio_editorial_rights_132.py` 审核每张原图来源/原始 SHA256/商业与衍生及官网授权、提示词与描述来源；两名真实独立官网角色的 Ed25519 签名由 `studio_official_approval_132.py` 使用**仓库外独立注册表 SHA pin** 验证。签名须覆盖候选 Skill 全元数据指纹、整条许可元数据指纹、管理员正式操作 ID、已发布的 Web DB 官方行和精确部署 SHA。

只有网站人工正式审批和实际写入官网 `catalog_assets(source_type='official', status='published')` 后，才用 `studio_phase21_official_web_export_132.py` 的**已授权 PG17 只读连接**导出官网实际已发布官方资源。此程序不负责审批、不修改官网、不更新 Skill。

再通过 `studio_phase21_official_gate_132.py` 实施**三候选双签优先 → 官网已发布 DB 只读摘要 → Web 静态 + 动态已批准 DB + Skill main 的 strict parity → 候选精确指纹防漂移/无旧 pending 回退**。现状仍是网站静态 537、Skill main 540、差异 3 项待审；没有真实签名和官网 DB 导出时严格阻断。正常发布需要 Skill 侧另行独立审核及双仓真实 Git SHA 复核。

Phase22 在此基础上增加 `studio_phase22_signed_custody_132.py`：分别对**真实 Web DB 只读导出、Skill checkout、PG17、S3/R2、Redis、供应商最终账本**这六个独立来源，使用**另一个**仓库外 SHA pin 信任注册表中 `field_operator` 和 `independent_reviewer` 的不同 Ed25519 公钥验签。规范化签名载荷包含 `scope, webSha, skillSha, sourceDigestSha256, recordedAtUtc, witnessSessionId, nonce, result`，防重复身份、重复公钥、篡改、过期、同 nonce 重放和角色伪造。此第二层**签名仅证明声明内容被可信密钥签过，不证明数据库真实、版权有效或实际部署来源**：审核者还必须在受控环境外部核对日志、Git commit、对象/账单/时间的独立原始证明。私钥和 pin 不得在同一来源内交付，也不可提交仓库。

## 2. 四个基础设施/供应商现场取证协议

`ops/studio_phase22_field_matrix_132.py` 依据 `ops/templates/studio_phase22_field_records_132.json` 中**刻意标为 PENDING**的记录格式，按每一个 step 保存原始证据 SHA256、UTC、独立操作人和审核人。每项步骤必须有**不同的真实证据摘要**，步骤不可缺省、重排、造假或用假 `PASS` 声明替代 `OBSERVED`。此文件仅是保存在**私有 vault**的 D 现场观测声明；校验器输出永远为 `NO-GO`。

**PG17（8 个观察步骤）**：真实独立恢复机身份与源库身份、PG17 物理 `pg_basebackup` 及 `pg_verifybackup`、独立 WAL 归档完整性与可覆盖 PITR 目标、启动只在受控目标回环地址、回放暂停确认、真实 schema/钱包/媒体元数据恢复前后 SHA、隔离回滚，以及逐次实际 RPO/RTO 时长。工具复用 Phase21 `studio_phase21_pg17_physical_pitr_132.py`，不进行源端删除/数据库写入；强制比对异机/异集群身份、PG major 17、恢复指纹和预算上限。**没有**物理备份日志与现场启动审计不能宣称 PITR PASS。

**R2/S3（8 个观察步骤）**：使用仅供测试的 TLS 专用桶和分别限定前缀的真实 A/B 凭据，验证各自 PUT/GET 字节，双向跨租户读写返回明确的 403，匿名被拒，TTL 前正常及过期被拒，已撤销签名 URL/下架旧 URL 的 CDN 缓存清理，媒体恢复字节完整与公开发布 ACL。运行 Phase21 `studio_phase21_infra_probe_132.py` 的真实命令之前必须人工核实预生产专用桶及授权，**探针本身不替代 CDN/应用侧独立测试**。Phase22 要求实际策略快照/媒体字节摘要/租户不同身份指纹和全部步骤见证。

**Redis（7 个观察步骤）**：两台**真实独立应用实例**各自身份、跨实例原子 `SET NX EX` / fencing token、不同 ACL 租户的双向 GET/SET 禁止、受控故障注入、故障期间锁所有权 fencing、防止重复扣费/重复作品、在预算内恢复。Phase21 的四客户端小探针并不证明真实两台物理实例或断网恢复；Phase22 另需真实 fault start/end UTC、不同应用身份 SHA 和连续日志指纹，实际故障注入只允许授权的隔离环境与回滚窗口。**不可在生产 Redis 直接执行故障注入。**

**供应商/财务（8 个观察步骤）**：从供应商结算**最终账单**及 HandRaw Run/Item/Attempt、钱包预扣/退款、免费额度分别导出**两条独立来源**；确认已经超过迟到成功/迟到计费结算期，逐个验证重复 callback、429、502、unknown、late success、退款与免费额度；按 `ops/reconcile_provider_statement_112.py` 用规范化的私有账单和 ledger **逐笔核对**，不得将供应商法币最小单位与钱包 credits 混为一谈。Phase22 进一步把 `paidAttemptCount`、`refundCount`、币种、两份原始规范化数据 SHA、既有对账报告 SHA 与记录中的计量值一一核对。免费额度和特殊异常场景仍需要独立原始见证，不能仅靠统计大于 0 的声明。

## 3. 17 项 D 级主表、关键回执和签名逐层锁定

`ops/studio_phase22_release_join_132.py` 对接：
- `ops/studio_d_environment_assertions_132.py` 的全部 **17** case（#11 4、#84 7、#112 6，要求精确 Web/Skill 部署 SHA、现场 UTC、独立操作人和复核者）；
- `ops/studio_d_receipt_contract_132.py` 的三份重点详细 receipt：PG17 / 真实私有 R2/S3 / 供应商最终流水；
- 新增 PG 关键表/备份清单/时间数值、对象桶和 CDN 策略、供应商财务的逐字段**交叉绑定**；Redis 的整份事件记录摘要必须绑定 D 主表的 `redis_multi_instance_failover.evidenceDigestSha256`；
- `ops/studio_phase22_signed_custody_132.py` 的完整六来源的外部信任双签。

即使完整的自填数据/受控测试都满足以上契约，仍仅证明**结构、关联和签名语法**，不证明被签数据源真实；所有输出保留 `NO-GO`，不得擅自把 #132 关闭或把 PR #131 改 Ready。

最终单入口：`ops/studio_phase22_full_chain_132.py`，先跑真实三候选双签/Phase21 strict parity → 校验四种现场观测协议与供应商两个真实独立来源 → 检查六种来源 SHA 的独立 Ed25519 密钥角色 → 与 17 项主表和三份关键 receipt 一致性比对。失败返回 code 2，**结果不会自动签发 D 级通过或发布权限**。

## 4. 私有现场执行次序

在项目根目录运行（全部输入均应为 `0600` 权限、新生成输出路径、只读 vault，绝不能放 GitHub/CI）：

```bash
# 第一步：由独立平台管理员通过外部可信渠道固定两组 trust-root SHA
export HANDRAW_OFFICIAL_TRUST_SHA256="REPLACE_PINNED_WEB_EDITORIAL_TRUST_SHA256"
export HANDRAW_PHASE22_TRUST_SHA256="REPLACE_PINNED_FIELD_AUDITOR_TRUST_SHA256"

# 第二步：官网编辑完成原图许可审核和网站正式审批后，先验证 Phase21
# 官方已发布数据库只读快照与 Skill checkout 的真实 SHA。

# 第三步：由每项现场负责人在隔离环境收集独立原始日志、
# WAL/CDN/Redis/供应商真实回执；双角色签署六来源载荷；
# 运行四项现场事件结构校验，再运行 17 项主表交叉核验。

python ops/studio_phase22_full_chain_132.py \
  --official-inputs /private/official-review-and-web-skill-inputs.json \
  --field-records /private/field-protocol-records.json \
  --witnesses /private/independently-signed-custody.json \
  --witness-registry /private/out-of-band-field-public-keys.json \
  --master /private/d-real-17-case-manifest.json \
  --critical /private/pg17-s3-provider-critical-receipts.json \
  --provider /private/provider-final-normalized-statement.json \
  --handraw /private/handraw-billing-normalized-export.json \
  --web-sha EXACT_DEPLOYED_WEB_40_SHA \
  --skill-sha EXACT_DEPLOYED_SKILL_40_SHA \
  --report /private/new-phase22-no-go-audit.json
```

输入 `official-inputs` JSON 必须正好具备 Phase21 官方链字段：`catalog`、`skill_styles`、`skill_layouts`、`pending_before`、`pending_after`、`published_styles`、`published_layouts`、`approvals`、`rights_reviews`、`trust_registry`、`source_receipt`、`deployed_sha`；**不得**自行塞入 `trust_sha` 冒充外部 pin（CLI 只从独立环境变量读取）。`field-records` 是模板的四种 kind 对象；其中 `providerStatementSha256` 和 `webRunItemAttemptSha256` 为**规范化私有 JSON 的规范化哈希**，`reconciliationReportSha256` 为原始对账器的**完整报告规范化哈希**；Redis 事件整包摘要须与 17 项主表中的对应 case 绑定。独立 witness 的 `sourceDigestSha256` 不能来自签名申请人的任意声称，必须从现场独立重算：官网 readonly-export-receipt 的 SHA；Skill `{styles,layouts,expectedGitSha}` 规范化 SHA；四份现场 protocol 记录的规范化 SHA。相关规范化算法复用 `studio_official_approval_132.sha`。

## 5. 本轮明确缺失的生产事实（不得由 C 级测试冒充）

目前三项官方风格没有真实官网授权与两名管理员的签名；尚无经过独立检查的原始官网官方 DB 行、Skill 正式审核合入、真实 PG17 异机 WAL/PITR、R2/S3 双租户/CDN、Redis 两实例故障注入、供应商最终收费退款、低端实机 Canvas 等 D 级证据。因此 **17 项真实独立 D PASS 仍然为 0，生产 NO-GO**。所有 Phase22 fixture 均为 synthetic；即使私有 JSON 获得脚本 `NO-GO` 输出并成功验证，不得将其输入生产 GO 或官方审批 API。

发布纪律：独立分支 CI 14/14 → 比较 behind=0 → `force=false` 安全快进 studio2 → 同 SHA Push/PR 各 14/14；PR #131 必须保持 Draft，`main` 不动、Issue #132 Open NO-GO，直到真正的 D 级外部双签与发布复核。 
