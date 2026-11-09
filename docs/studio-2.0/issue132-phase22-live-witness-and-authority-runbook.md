# Studio 2.0 · Phase 22 · #132：现场 D 级证据闭环与授权对账操作说明

2026-11-10。交付基线 `studio2@9ba7cd20d1f258e56fd0b737bf4feee7d397342d`，对应 Phase21 独立/Push/PR **同 SHA 三套 14/14**。本 Phase22 提交独立 branch，`main` 禁止改动，PR #131 保持 **Draft**，Issue #132 **Open / NO-GO**。所有工具均独立运行在**外部授权的预生产隔离环境**，CI 只使用无真实供应商、无私钥、无真实用户数据的假夹具。

## 一、三项官方画风：真实许可 + 双签 + Web ↔ Skill

唯一候选：`FF-018` Low Poly Art、`FF-019` Hyperreal 3D Cartoon Portrait、`FG-025` Perler Bead Pixel Art。当前网站官方静态 537，Skill main 540，差额 3 为**未经官网批准的待审候选**。**未获得真人许可核验、官网编辑实际批准动作、两个不同实体的 Ed25519 正式签名和真实已批准 Web DB 行前，不得发布或转正。**

1. 先由网站编辑检验**每项完整**原图来源与 SHA256、实际著作权/授权文件、商用/衍生/官网分发权限、素材署名、提示词通用性与描述来源；记录授权/许可 ID 与原件 SHA，不得把原始合同、含凭据的媒体或身份信息提交 GitHub。独立复核者必须具备另一角色的官网受控公钥注册表，并在审查系统独立维护校验值 `HANDRAW_OFFICIAL_TRUST_SHA256`；信任根不可由审批申请自己提交。
2. 真实官网审批操作中逐项记录 `websiteActionId`；在 PG17 限权账号用 `ops/studio_phase21_official_web_export_132.py` **只读**导出 `catalog_assets WHERE source_type='official' AND status='published'`，现在同时生成 `styles.json`、`layouts.json`、`readonly-export-receipt.json`、`raw-website-published-rows.json`（权限 0600，原始行仅限官网已批准的非个人元数据，且只存受控私有机器）。人工独立核验导出连接确属所声明官网部署数据库，导出源行 hash 和实际 DB 事务/动作日志；JSON 本身不能证明是 live DB。
3. 从审核 vault 导入三项独立签名、全部许可元数据与独立的 Web 已发布 DB 文件。Phase22 `ops/studio_phase22_official_provenance_132.py` 要求 **原始官网 DB 行 → 规范化 Web 官方样式导出 → 外部 SHA 已知的干净 Skill Git 完整 SHA 检出 → 三项完整双角色 Ed25519 签名 → `stage_transition` 的 537/540 及动态 Web 官方已发布 strict parity** 一步步校验。任何候选缺项、签名伪造、原始 DB 元数据变化、Skill 内容漂移或版本未锁定均拒绝。原始 `ops/studio_phase21_official_gate_132.py` 和 `ops/studio_official_approval_132.py` 继续是强制门禁，Phase22 不绕过它们。
4. 输出始终标识 `NO-GO`，即使 3 项外部签名声明与源行指纹形式一致，仍须由**独立官网/Skill 负责人**在实际环境确认发布与跨仓审核。脚本不修改网站 DB/Skill、不会修改 pending manifest、不会将网页或 Skill 的候选从待审自动转正。

在所有受控输入齐全后调用（文件路径为示意；只在受控主机执行）：

```bash
HANDRAW_OFFICIAL_TRUST_SHA256=<out-of-band-sha256> \
python ops/studio_phase22_official_provenance_132.py \
  --raw-web-rows /private/export/raw-website-published-rows.json \
  --skill-checkout /private/pinned-skill-checkout \
  --skill-sha <full-40-char-reviewed-skill-commit> \
  --catalog plugin/content/catalog.json \
  --skill-styles /private/pinned-skill-checkout/references/styles.json \
  --skill-layouts /private/pinned-skill-checkout/references/layouts.json \
  --pending-before ops/official_catalog_pending_11.json \
  --pending-after /private/reviewed-post-approval-pending.json \
  --published-styles /private/export/styles.json \
  --published-layouts /private/export/layouts.json \
  --approvals /private/independent-two-role-signatures.json \
  --rights /private/independent-rights-review.json \
  --trust-registry /private/out-of-band-trust-registry.json \
  --source-receipt /private/export/readonly-export-receipt.json \
  --deployed-sha <full-40-char-web-deployed-commit> \
  --report /private/new-phase22-official-report.json
```

如果真实审批材料为空，**禁止用测试签名、伪 Web DB 行或 Mock 权利记录填充“已批准”**；实际 Phase22 工具将拒绝并保持三项待审。

## 二、PG17：物理异机恢复闭环

运行 Phase21 `ops/studio_phase21_pg17_physical_pitr_132.py` 的 guarded `--mode plan / backup / prepare / verify`。**运营先核对**独立隔离物理主机、只读业务账户、预生产复制源、离线 WAL、单独空目录、许可的 RPO/RTO 预算；真实 `pg_basebackup`、`pg_verifybackup`、`recovery.signal` 和 `recovery_target_time` 用真实 WAL 完成恢复，恢复目标必须晚于基础备份结束。手工在隔离回环地址启动恢复库，并于 target UTC 暂停，通过只读 fingerprint 验证。

新增 `ops/studio_phase22_field_receipts_132.py` 与 `ops/templates/studio_phase22_field_receipts_132.json` 记录：备份及 WAL 归档 SHA；**源主机与恢复主机不同的物理身份 SHA**；确切恢复目标 UTC/WAL LSN；恢复前后 schema/业务/钱包/媒体摘要；真实 RPO/RTO 数值和预算，回滚演练完成的独立记录。任何不同、缺项、超预算都 BLOCKED。仅声明异机并非真正验证硬件，原始主机清单/对象存储归档与 WAL 文件必须交给独立审核员。

## 三、R2/S3/CDN：真实双租户 + URL 失效

在专用 QA bucket 与两个**服务端按资源范围限制的不同凭据**上运行 `ops/studio_phase21_infra_probe_132.py --mode s3`；用匿名身份和 A/B 互访互写校验真正 403，不能把 404 或超时当权限成功。再由独立现场 HTTP/CDN 测试收集**发布前私有、签名有效、签名过期、服务端授权撤销、CDN 下架旧 URL、已授权公有媒体和多图/原始字节恢复**的独立复核。Phase22 字段收据要求 bucket 与 CDN 策略 SHA、A/B 凭据策略不同、A/B 双向读写拒绝、原始/恢复对象 SHA 相同、下架 URL 真实拒绝。这些 CDN 证据在 Phase21 的 S3 probe 中尚**未覆盖**，不可将探针 PASS 视为完成。

## 四、Redis：多实例故障切换真实演练

Phase21 的四客户端 NX/ACL 探针只证明同一 Redis 服务端客户端一致性，**不证明双物理运行实例与故障切换**。Phase22 的 `ops/templates/studio_phase22_field_receipts_132.json` 中 `redis` 部分新增独立证据结构：拓扑/ACL 前后 SHA、两个物理实例身份、fencing epoch 严格单调增加、故障切换实际执行、旧主写入拒绝、新主恢复、旧/新锁所有者摘要、Run 幂等无重复、跨租户拒绝。实验由运营在独立 QA 实例中执行，需双人见证、网络故障记录、真实日志与回滚。此工具**只校验报告声称的状态和跨字段不变量**，不会故意断开生产 Redis。

## 五、供应商最终账单与免费额度联合对账

复用 `ops/reconcile_provider_statement_112.py` 的**实际成熟最终供应商 invoice ↔ Web Run/Item/Attempt、回调、钱包扣费和退款**逐笔核对，它会拒绝迟到成功后错误退款、重复收费、未知远端任务、账本不守恒等。新增 `ops/studio_phase22_provider_gate_132.py` 继续要求：
- 供应商与 Web 所有明细源自两个不同实际账本，周期 UTC 与部署 Web SHA 一致，原文件私有且各有 SHA256。
- 引入**独立免费额度导出**（`ops/templates/studio_phase22_free_quota_132.json`），通过 `before+granted-consumed+restored=after` 数值守恒，且无未匹配免费任务，杜绝把免费额度算成付费钱包。
- 引入 `ops/templates/studio_phase22_provider_scenarios_132.json`：`duplicate_callback` / `throttled_429` / `upstream_502` / `unknown_recovery` / `late_success` / `refund` / `free_quota` 七种**真实观测**各有非零次数、互异 SHA、独立操作者与审核者；场景快照绑定原始 provider/HandRaw/free 三份 JSON 字节 SHA。
- 结构及金额对账结果仍是 `NO-GO`，因为真实账单与来源真实性尚须独立复核，不能从自填测试 JSON 得到真实 D PASS。

示例：

```bash
python ops/studio_phase22_provider_gate_132.py \
  --provider /private/final-vendor-invoice.json \
  --handraw /private/web-run-wallet-callbacks.json \
  --free /private/independent-free-quota.json \
  --scenarios /private/observed-failure-scenarios.json \
  --web-sha <real-deployed-web-sha> \
  --report /private/new-phase22-paid-free-audit.json
```

## 六、独立 SHA 锚定的 D 证据链与 17 项发布门禁

新增 `ops/studio_phase22_witness_chain_132.py` 和 **默认全 BLOCKED** 的 `ops/templates/studio_phase22_independent_registry_132.json`。外部审计系统单独维护 registry SHA（环境变量 `HANDRAW_PHASE22_TRUST_SHA256`，不可从待验证包中自己导入），针对官网、PG17、对象存储/ CDN、Redis、供应商五类证据提供报告字节 SHA、规定来源类别、原始 Web/Skill SHA、现场 UTC、操作人/复核人及互不复用证据 ID。每个报告须放在私有 `0600` 目录固定文件名 `official.json`、`postgres.json`、`storage.json`、`redis.json`、`provider.json`。验证器只读取，不会联网，不会修改任何官方资源。

```bash
HANDRAW_PHASE22_TRUST_SHA256=<out-of-band-canonical-registry-sha256> \
python ops/studio_phase22_witness_chain_132.py \
  --registry /private/pinned-registry.json \
  --proof-dir /private/phase22-proof-reports \
  --web-sha <deployed-web-sha> --skill-sha <reviewed-skill-sha> \
  --report /private/new-phase22-witness-review.json

python ops/studio_phase22_field_receipts_132.py \
  --dossier /private/actual-pg-s3-redis-receipts.json \
  --web-sha <deployed-web-sha> --skill-sha <reviewed-skill-sha> \
  --report /private/new-phase22-field-review.json
```

以上**最多证明文档指纹/守恒/跨字段一致，不能独立证明外部真实设备、持有权、官网合法许可、付费来源**。真实 17 项统一由 `ops/studio_d_environment_assertions_132.py` + `ops/studio_d_receipt_contract_132.py` 继续作为结构核对器；任何缺现场证据、假夹具或独立复核者均为 BLOCKED。CI 只能运行**伪造/重放/缺失/跨 SHA/权限失败**的负向测试，本轮实际现场 17 项仍为 0 项独立 D PASS。生产继续 **NO-GO**，Issue #132 **Open**，PR #131 **Draft**，`main` 不变。

### 默认模板说明

`ops/templates/studio_phase22_{field_receipts,provider_scenarios,free_quota,independent_registry}_132.json` 中零值、false、历史 UTC、相同 SHA 等字段是**刻意设计的不可验收占位**；不得将其复制为真实事实，也不得在 CI 中通过自造真凭据将 `realDPass` 提升为正数。
