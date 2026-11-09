# Issue #132 · Phase 20 现场审批与生产 D 级验收手册

**范围：本手册是执行规范和空白证据模板，不构成真实生产验收。** 当前 FF-018 / FF-019 / FG-025 都是 `awaiting_website_editorial_review`；17 个生产 D 级案例均没有有效、经过独立审核的实证 PASS。PR #131 维持 Draft，`main` 不变，**生产 NO-GO**。

## A. 官网官方资源：人审、授权和 Ed25519

**组织与职责分离**：网站编辑复核原始图片来源、创作者、可商业使用的许可证/书面许可、衍生使用及官网分发授权、归属/署名要求、描述与提示词来源；独立审核员检查许可真实性和网站审批动作。安全管理员管理受控公钥注册表（各角色原生 Ed25519 公钥字节必须不同）及 Vault 外部固定的 SHA256。网站/Skill 代码提交人不得自行充当信任根。编辑和复核签名私钥须各自隔离保管，可吊销、轮换并留审计；仓库不得包含私钥、原图、用户数据、真正许可文件或实际审核人身份。

1. 分别审 FF-018、FF-019、FG-025，并固定 Skill 全 JSON 候选 SHA256（当前受控清单 `ops/official_catalog_pending_11.json`）；核验官网尚未提前反向发布这三项。
2. 对每项填写私有 `ops/templates/studio_official_rights_review_132.json`：候选、完整 Skill hash、提示词来源、描述来源、许可复核 ID、**每个原图的 SHA256**、原创/明确许可/公有领域分类、权利持有人证据、具体授权凭据、署名凭据；商业、衍生、官网公开发布三个布尔值必须各自有**真实证据支持**，未审时保留 false + pending。
3. 编辑于**正式网站管理审批流**执行真实逐项审批（每项独立 `websiteActionId`）；网站官方数据源发布后，由独立运营人员使用最小只读权限导出真实已批准 `styles.json`；每行完整 JSON 的 SHA256 记录下来；不允许用户提供的任意 JSON 被视作生产 DB 事实。
4. 双角色分别对相同**规范化 JSON** 进行 Ed25519 签名。签名域包括 `candidateCode`、`skillSourceSha256`、`webDbPublishedRowSha256`、`deployedSha`、唯一 `websiteActionId`、`rightsReviewEvidenceId`、**`rightsReviewEvidenceSha256`（整条已检查授权记录的 canonical JSON digest）**、UTC `reviewedAtUtc` 和批准结果。防止替换原图 hash、许可证、署名信息或文案的任何字段。重复密钥材料、错角色、重复动作 ID、过期记录、错误 SHA、修改任何授权资料都必须拒绝。注意：被签署文件的真实性仍需人工核查，签名只证明密钥签署了这些字节。
5. 在隔离审核机上备齐权限 `0600` 的签名 bundle、独立信任注册表、真实 Web DB 导出和 rights reviews；信任注册表 hash 必须由**申请以外的安全配置通道**注入，而不是跟随申请 JSON。运行：

```bash
HANDRAW_OFFICIAL_TRUST_SHA256=EXTERNALLY_PINNED_TRUST_REGISTRY_SHA256 \
  python ops/studio_official_approval_132.py \
    --bundle /private/editorial-claims.json \
    --trust-registry /private/website-public-key-registry.json \
    --published-web-styles /private/live-approved-styles.json \
    --rights-reviews /private/rights-reviews.json \
    --deployed-sha FULL_40_CHARACTER_WEB_SHA \
    --report /private/new-approval-check-result.json
```

6. 无论签名校验是否成功，本验签工具都输出 `automaticWebsiteApprovalGranted=false`、`publishedDbOriginIndependentlyProven=false`、`decision=NO-GO`。实际源审核、真实官网批准 DB、发布部署 SHA 和两位独立实际授权人员身份都需要另行复核。
7. **仅在正式审批完成后**准备 Web 优先的增量目录变更及 Skill 独立审核 PR：移除相应 pending 指纹条目、以网站真实批准 DB 为权威，检查旧 537 静态资源无误，再执行 `check_official_catalog_parity.py --strict --approved-export-dir /private/reviewed-export`。阶段性 `ops/studio_official_transition_132.py` 为只读 dry run，针对三项同时验证**完整 Skill JSON 和完整官网 DB 行**哈希与签名 payload 的一致性，阻止“名称没变但内容回滚”、删除旧已批准资源、重复编号、旧 pending 留存、错误部署 SHA；它**不自己验签**，必须先单独执行第 5 步并核对可信来源。不可自动批准、不可擅自向 Web 导入 Skill-only 行。

## B. 17 条 D 级现场主表

模板：`ops/templates/studio_d_real_evidence_132.json`。按 #11=4 项、#84=7 项、#112=6 项，共 **17 项**。每条必须各自填写 `caseId,status,origin,evidenceDigestSha256,evidenceId,environmentId,deployedSha,skillSha,observedAtUtc,operator,reviewer,isSimulation,physicalOrRealProviderClaim`；两个 SHA 为**真实部署** 40 位，UTC 在 30 天内，原始凭据各自私有留存，操作者与复核者不同。模板故意以 `PENDING`、`isSimulation=true`、`physicalOrRealProviderClaim=false` 及无效占位符填写，**绝不能当作成功样例复制后改成 PASS**。

主表场景：
- #11（4）：`editorial_ff018`、`editorial_ff019`、`editorial_fg025`、`web_db_and_skill_main_strict_parity`。
- #84（7）：`one_run_one_public_work`、`five_images_out_of_order`、`three_success_two_failed`、`all_failed_zero_work`、`skill_explicit_upload_resume_and_gif`、`cover_moderation_tombstone`、`cross_user_private_media`。
- #112（6）：`real_object_bucket_and_expired_url`、`redis_multi_instance_failover`、`real_provider_charge_refund_ledger`、`pg17_offline_backup_restore_rollback`、`low_end_physical_browser`、`release_owner_rollback_signoff`。

现场证据可先由两个**离线**验证器检查结构和来源声明，严禁把本地测试/CI/Moto 冒充真实供应商或生产环境。即使 17 条清单全部自报 PASS，这些离线验证器依然返回 `NO-GO`，只供独立审核人进一步对原始凭据做审计。

```bash
python ops/studio_d_environment_assertions_132.py \
  --claims /private/real-d-cases.json \
  --web-sha FULL_40_CHARACTER_WEB_SHA \
  --skill-sha FULL_40_CHARACTER_SKILL_SHA \
  --report /private/new-redacted-17-case-audit.json
```

## C. 三大高风险门禁：专用证据回执

模板：`ops/templates/studio_d_critical_receipts_132.json`。每条 `details` 的 canonical JSON SHA256 必须既等于该 receipt 的 `evidenceDigestSha256`，也等于主表同 `caseId` 的 `evidenceDigestSha256`。此回执本身只是各真实私有原始证据的**不可替换索引**，不让自报值冒充事实。

**1. 实际供应商收费与钱包/免费额度逐笔对账**。分别从供应商原生系统导出真实结算账单、网站 Run/Item/Attempt、wallet/credit ledger 与 free quota source，不可从同一内部导出伪造两份。统一账期、币种最小单位、任务重试 attempt 与供应商 `provider_task_id`；逐笔核对真实 charge/refund 和钱包扣回补偿；覆盖重复回调、429、502、unknown 恢复、迟到成功。既有 `ops/reconcile_provider_statement_112.py` 可用于**付费积分**离线对账；免费额度还须独立复核。详细回执要求 `unmatchedProviderEntryCount=0`、`unmatchedWalletEntryCount=0`、`netChargeDeltaMinor=0`、`netRefundDeltaMinor=0`。保留供应商源文件签名/下载证据、原始 SHA、账期与独立复核人；工具无法联网验证供应商真实性。

**2. PG17 真正物理备份、异机 WAL/PITR 与回滚**。以实际源集群实施物理 base backup（非仅 `pg_dump`），验证完整 WAL 归档/时间线；在**不同主机/集群身份**新建隔离环境恢复到指定 PITR 时间点，不触碰原运行库。恢复 schema、wallet/ledger、Work/Media 业务表的行数/内容指纹并核对一致；演练迁移回退、实际计量 RPO/RTO 并与预定预算比较。独立留存 basebackup/WAL manifest SHA、恢复目标环境和演练日志、恢复前后业务指纹。现有 `ops/pg_release_restore_drill_112.py` 仅做受控逻辑双库恢复，不能替代此项。

**3. 真正私有 R2/S3/MinIO 网关与 CDN**。在实际私有桶和真实 CDN 域名（或真实部署网关）执行两个独立租户 A/B 的互相读取、写入、列举及签名链接测试；匿名访问必须拒绝，签名过期必须拒绝、作品下架后旧链接及 CDN 缓存必须不可访问，多图恢复后字节 SHA 与 ACL 一致；只允许正式公开作品按授权授予公开下载。记录桶策略和 CDN 策略 SHA、访问失败 HTTP 证据、真实恢复媒体 manifest SHA；测试不能拿 Moto 或模拟代理代替。仅保存脱敏证据 ID、sha 与布尔证明摘要，不向 GitHub 上传任何实际对象、签名 URL、账号信息。

```bash
python ops/studio_d_receipt_contract_132.py \
  --claims /private/real-d-cases.json \
  --receipts /private/real-critical-receipts.json \
  --web-sha FULL_40_CHARACTER_WEB_SHA \
  --skill-sha FULL_40_CHARACTER_SKILL_SHA \
  --report /private/new-redacted-three-gate-audit.json
```

该回执工具只核验严格字段、数据互相关联和异常计数约束：即使三条真实回执 + 17 条声明格式全通过，输出仍为 `externalSourceAuthenticityVerified=false`、`decision=NO-GO`。独立审核人必须离线访问真正原始账单、PG 物理恢复证明、对象存储权限日志和厂商后台，核查真实签核与 SHA 绑定；工具**没有发布权限**。

## D. 证据不可回退与最终判定

- 任意候选版权不清、签名公钥复用、审批 SHA 与已部署网站不一致、数据库已发布行或 Skill 完整 JSON 漂移、pending 清单旧条目未清理，**FAIL/BLOCKED**。不可把三项 Skill-only 草稿默认为网站官方。
- 任意 D 级证据缺失、非真实环境、存储权限泄露、账目失衡、PITR 未完成或超出 RPO/RTO、单人自审，**NO-GO**。一个 D 级 case 的证据摘要不能冒充另一个 case。
- 发布签核仍需双人审计原始凭据，部署 SHA、Skill SHA、环境配置、UTC、回滚计划/RPO/RTO 和恢复测试记录在隔离工作流里分别完整登记。**只有真实证据经独立审核**才能提出另一个发布决策；本仓库校验器一律不授予自动 GO。
- Phase 20 性能结案报告见 [issue132-phase20-performance-final.md](issue132-phase20-performance-final.md)。真实低端设备仍是必需的 `low_end_physical_browser` D 级门禁。
