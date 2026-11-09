# Studio 2.0 · Phase 21 · #132 官网审批与生产等价现场验收

2026-11-10。工程基线 `studio2@ed60030f4df2990b28355141580075e4ccf9b8a4` 已完成三套同 SHA 14/14 C 级门禁。本切片只做**独立分支**的审批闭环验证与 D 级非生产演练工具。**不自动发布**三项画风、不写网站 DB、不更改任何生产 JS/CSS、不连接真实生产基础设施；#132 Open，PR #131 Open Draft，`main` 不动，生产 NO-GO。

## 1. 画风 FF-018 / FF-019 / FG-025：审批须先于同步

现状：网站静态官方 537；Skill main @ `9248843ba4659a1d9afbc177ae73b91bb1af68a9` 540，其中以上三项均为未经官网批准的 Skill-only 候选，原始完整指纹位于 `ops/official_catalog_pending_11.json`。**严禁直接导入已发布官网**。在没有真实授权、正式官网编辑动作和两个人各自的 Ed25519 签名之前，任何对账与发布一律 fail closed。

### 审批的真实现场链路

1. 网站编辑分别复核提示词/描述的来源、全部原图 SHA256、权利人及可验证许可、商业使用/衍生使用/官网公开发布权、署名要求，按 `ops/templates/studio_official_rights_review_132.json` 填私有记录。私人许可文件及原图不要提交 GitHub。
2. 在网站**实际官方审批后台**为各候选执行独立审批动作，并记录 `websiteActionId`；先在 Web 的 `catalog_assets(source_type='official',status='published')` 中确认真实已发布 DB 行。两名角色 `website_editor` 与 `independent_reviewer` 使用独立密钥对同一规范化 payload 签名；签名覆盖候选 Skill 全元数据 SHA、已发布 DB 的完整官方行 SHA、**整条许可/来源记录 SHA**、部署 Web SHA、操作 ID、审查 UTC。信任注册表 SHA 由**申请材料外部**受控管道固定。
3. 使用最低权限、显式 read-only PG17 账号，在隔离验收机按 `ops/export_official_assets.py` 的查询与映射规则导出网站真实 `styles.json/layouts.json`；额外由操作人和独立复核者审视 DB 查询时点/身份/发布时间/环境并留下私有来源 receipt。签名/导出工具都**不能独立证明** DB 事实或真实许可有效。
4. 在隔离机运行原有 `ops/studio_official_approval_132.py` 双验签，再使用新增的 `ops/studio_phase21_official_gate_132.py` **单入口**：验签全部 3 项 → 核对独立 Web DB 导出 receipt 与真实部署 SHA → 调用 `stage_transition(...)` 严格检查 `--strict` 的动态 Web 已批准官方 DB、静态目录与完整 Skill main 的 540 项同步，检查所有候选的内容、编号、名称和防回退完整指纹。缺 1 项、伪造签名、旧 Skill 内容、旧 pending 清单、新旧 Web SHA 不匹配均 BLOCKED。
5. 以上阶段只允许产生 `SIGNED_AND_STRICTLY_STAGED_FOR_INDEPENDENT_REVIEW` / `NO-GO` 的脱敏结果。实际网站 DB 来源、权利真实性、跨仓 Skill 正式审核和部署仍由独立操作者外部验证。**绝不让离线脚本授予 GO、自动写 Web DB 或修改 Skill main。**

#### 流程调用（仅已获授权、离线私有环境）

```bash
# 没有全部真签名/已发布官方行等材料时，只产生 MISSING_WEBSITE_APPROVAL / NO-GO：
python ops/studio_phase21_official_gate_132.py \
  --deployed-sha FULL_DEPLOYED_WEB_40_CHAR_SHA \
  --report /private/new-official-no-go.json

# 以下文件均须从受控审批 vault 以 0600 导入，非仓库内假夹具：
HANDRAW_OFFICIAL_TRUST_SHA256=OUT_OF_BAND_PINNED_SHA256 \
python ops/studio_phase21_official_gate_132.py \
  --catalog plugin/content/catalog.json \
  --skill-styles /audited/skill-main/references/styles.json \
  --skill-layouts /audited/skill-main/references/layouts.json \
  --pending-before ops/official_catalog_pending_11.json \
  --pending-after /private/post-approved-pending.json \
  --published-styles /private/website-published-styles.json \
  --published-layouts /private/website-published-layouts.json \
  --approvals /private/website-editorial-signatures.json \
  --rights /private/three-rights-reviews.json \
  --trust-registry /private/independent-public-trust.json \
  --source-receipt /private/readonly-postgresql-export-receipt.json \
  --deployed-sha FULL_DEPLOYED_WEB_40_CHAR_SHA \
  --report /private/new-phase21-official-audit.json
```

其中 DB `source-receipt` JSON 只有 `schemaVersion=1,sourceSystem="website-postgresql-read-only",sourceRole="readonly-export",webDeployedSha,publishedStylesSha256,publishedLayoutsSha256,operatorId,independentReviewerId,exportSessionId`；它是来源**声明**而非独立认证。运营必须现场校验实际数据库只读会话、应用已发布状态、来源操作日志、导出原始摘要。3 项目前并无真实签名，因此 Phase21 没有尝试构造“已批准”的生产行。

## 2. PG17 物理恢复与 PITR 的受控执行

工具：`ops/studio_phase21_pg17_physical_pitr_132.py`。与 `ops/pg_release_restore_drill_112.py` 的 `pg_dump/pg_restore` 逻辑演练不同，新增工具支持真实 PG17 **物理 pg_basebackup + pg_verifybackup、独立只读 WAL 归档 PITR 预配置、暂停在精确 UTC 恢复点、已恢复 PG17 业务状态指纹读取**。

**非常重要的前提**：需有一台独立预生产恢复主机、显式确认的预生产 PG17 复制源、专用空路径（无任何运行库）、另一处已有 WAL 归档及最低权限数据库账号，运营已获批准并自行核实源和目标确属不同物理节点。它不会识别伪装为预生产的生产主机；操作者必须在真实环境做源库身份和访问控制核查。禁止在源库上执行本工具。 `--mode plan` 只校验身份/路径，**零外部连接**；`backup/prepare/verify` 均受 `HANDRAW_PHASE21_PG_ISOLATED_DRILL=YES` 保护。工具不执行 `pg_ctl`、不重启或删除实例，不覆盖任何文件、不输出密码或用户行。

```bash
# 仅在单独的预生产恢复主机执行；target-host 必须等于本机 hostname/fqdn
python ops/studio_phase21_pg17_physical_pitr_132.py \
  --mode plan --environment preprod-isolated-recovery \
  --source-host pg17-stage-replica.internal \
  --target-host actual-recovery-hostname \
  --root /srv/isolated-phase21 --leaf pitr-drill-20261110 \
  --archive-dir /srv/independently-staged-wal \
  --target-utc 2026-11-10T12:00:00Z \
  --report /private/new-pg17-plan.json

# 在明确的隔离审批后，使用同样参数改为 --mode backup
export HANDRAW_PHASE21_PG_ISOLATED_DRILL=YES
export HANDRAW_PHASE21_PG_REPLICATION_PASSWORD='(from-vault)'
# 并追加 --source-user/--source-port，工具内部调用真实 pg_basebackup
```

物理备份生成全新 `pitr-*` 目录，验证 PG17 `PG_VERSION`、`backup_manifest` 和 `pg_verifybackup`，记录副本摘要且不记录私钥。接着由运营将**真实归档 WAL** 独立复制到只读归档目录（命名和权限需复核），选择**严格晚于基础备份完成**的 UTC PITR 点后用 `--mode prepare` 写入 `recovery.signal`、仅在受控副本中追加 `restore_command`、`recovery_target_time`、`recovery_target_action=pause`，不触碰源库。运营另行在隔离回环地址/非默认端口启动 PG17，验证复制历史和恢复点；先前在该恢复时点保留独立表指纹 witness。最后 `--mode verify` 只读连接 `HANDRAW_PHASE21_PG_TARGET_DSN`，要求 PG major=17、replay pause、WAL LSN 非空、关键业务表 count + SHA 全一致，且已有物理备份/准备/恢复 witness 的目标 UTC 和 manifest 摘要完全一致。

真实 PITR 的 RPO/RTO 需要**现场计时**；单独异机审计复制证据、WAL 覆盖时间、账号身份和目标地址，按照 `ops/studio_d_receipt_contract_132.py` 与主 17 条 D 证据主表收集，不得把备份脚本退出 0 算作 D 完成。

## 3. R2/S3 + Redis 真正双租户隔离

工具：`ops/studio_phase21_infra_probe_132.py`。默认 `--mode plan` 不联网、不访问存储；`--mode s3|redis` 仅在 `HANDRAW_PHASE21_INFRA_D_PROBE=YES` 并有真实单独授权凭据时运行。

S3/R2 探针必须使用 TLS S3 endpoint 和仅限本轮的**专用测试桶** `handraw-phase21-qa-*` 与随机 `phase21-qa:*` 前缀，且两个凭据 A/B 各只能读写自己租户前缀。分别测试：A/B 各自读回字节完全一致、A 读取或写入 B（反向同理）均拒绝、完全匿名读取拒绝；可选 1 秒真实签名 URL 的**有效期前可读、过期后 401/403 拒绝**。只删除本次随机生成且由各自凭据拥有的 QA 对象。禁止使用真实用户的图片、公开桶、Moto、真实生产账号。CDN 缓存撤销/下架旧 URL、多图恢复字节校验仍需独立的应用/CDN 现场用例，这个 S3 探针**不为它们签发 PASS**。

Redis 探针需四个各自授权的连接：两个独立 Web 客户端的共同协调器 `COORD_A/COORD_B`，两个按键前缀隔离的 Redis ACL 凭据 `TENANT_A/TENANT_B`。使用 60 秒随机 QA key，验证跨连接共享的原子 `SET NX EX` 锁、两租户各自数据读取及双向跨租户 GET/SET 被 Redis 服务端 ACL 拒绝。清理用 compare-and-delete，不能删除他人的过期锁。**四条连接不等于实际两个运行实例，更不等于实测故障切换**；生产多实例 Redis failover 必须运营发起演练并另存独立现场证据。

```bash
# 零真实调用、保留 NO-GO
python ops/studio_phase21_infra_probe_132.py \
  --mode plan --environment preprod-isolated-r2 \
  --endpoint https://s3.preprod.example.invalid \
  --bucket handraw-phase21-qa-disposable-01 \
  --prefix phase21-qa:isolatedreview01 \
  --report /private/new-infra-plan.json

# 实际 S3/R2 测试额外需要：
# HANDRAW_PHASE21_INFRA_D_PROBE=YES
# HANDRAW_PHASE21_S3_A_KEY_ID / _SECRET
# HANDRAW_PHASE21_S3_B_KEY_ID / _SECRET
# 真实 --mode s3，可选 --test-presigned-expiry

# 实际 Redis 测试额外需要：
# HANDRAW_PHASE21_REDIS_COORD_A_URL / _COORD_B_URL
# HANDRAW_PHASE21_REDIS_TENANT_A_URL / _TENANT_B_URL
# --mode redis --prefix phase21-qa:isolatedreview01
```

无外部授权或专用资源时，真实阶段只标记 BLOCKED，不准模拟 PASS。所有脚本输出脱敏摘要、`decision=NO-GO` 和未完成证据项，避免误将工具成功等同上线许可。

## 4. 17 项 D 级发布阻断继续生效

验收主表 `ops/templates/studio_d_real_evidence_132.json` 有 17 个 case（#11=4、#84=7、#112=6）。真实证据必须包括完整已部署 Web/Skill SHA、原始不可替换摘要、UTC/环境/操作人/独立审核人及 RPO/RTO/回滚签核。离线评估器 `studio_d_environment_assertions_132.py` 和 `studio_d_receipt_contract_132.py` 都永不授权 GO。只有网站官方正式审批、版权/双签真实证据和 17 项外部独立审核全 PASS，才可讨论移除 #132 NO-GO；本 Phase21 不修改 `main` 或 PR Draft。
