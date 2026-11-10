# Studio 2.0 · Phase 24 · Issue #132 17×5×3 D 级离线证据强关联

**范围：**仅 C 级安全工程，不接生产、不伪造真实 D 级验收、不批准候选资源。独立分支 `studio2-issue132-phase24-d-evidence-join-20261110`，基于 `studio2@9d2a59be397845e98ae05ab5db052445dba077ae`。Phase23 正式 studio2 Push / PR #131 双 CI 需另外核实 14/14，不能用 Phase24 测试覆盖。

## 已存在四层独立的只读检查器

1. `ops/studio_d_environment_assertions_132.py`：17 个 D 主表 case（Web/Skill SHA、operator/reviewer、UTC、独立 evidenceId / evidenceDigest）。
2. `ops/studio_d_receipt_contract_132.py`：供应商费用、PG17 PITR、私有 R2/S3 三类业务证据 details（摘要绑定主表）。
3. `ops/studio_phase22_field_receipts_132.py`：PG17 物理恢复指标 / R2/S3+CDN / 多实例 Redis 现场报告的逻辑约束。
4. `ops/studio_phase22_witness_chain_132.py`：五类报告（官网、Postgres、Storage、Redis、Provider）的原始字节 SHA-256 与独立手工锚定 registry。

各套单独正确**不等于**是一套对应的同一现场事件。Phase24 新增 `ops/studio_phase24_release_join_132.py`：

- 主表要求恰好 17 项且均 `PASS` **声明**；三种详细收据必须齐全，五类被 SHA-pinned 的私有 witness 报告必须齐全；
- 统一 Web/Skill 完整 SHA、预生产环境、UTC 时效及证据标识；
- 五类 witness `evidenceId`、operator、independentReviewer、observedAtUtc **逐字段**对应 17 case 主表；跨项目交换见证/不同审查人/不同时间均阻断；
- PG17 detailed 和 field packet 的钱包原始/恢复摘要、RPO/RTO 实测/预算必须相等，不仅仅各自单独小于预算；
- 私有存储的 bucketPolicySha256 / cdnPolicySha256 必须跨详细合同与 field receipt 相等；
- 强制拒绝报告字节漂移、重复/遗漏的 case、不同 SHA、模拟证据标记、共享未经审核的身份；
- witness 报告 SHA 与 D detailed receipt SHA **刻意分别代表不同的对象**。前者绑定报告原始文件，后者绑定对应业务详情；不得为满足对账而将二者强行视为同一字节。

## 只在已获授权的隔离预生产审查机运行

私有原件、供应商结算单、PG host/WAL、存储私钥、含用户数据的媒体**不得上传 GitHub 或 CI**。四项输入 JSON 和五份 witness JSON 必须由不同权限审核人员取得且权限为 0600；锚定 `HANDRAW_PHASE22_TRUST_SHA256` 必须从独立管理渠道取得，不能由待核验报告自证。实际运行示意：

```bash
HANDRAW_PHASE22_TRUST_SHA256=<auditor-out-of-band-digest> \
python ops/studio_phase24_release_join_132.py \
  --claims /private/17-real-case-claims.json \
  --receipts /private/pg-s3-provider-details.json \
  --field-dossier /private/pg-s3-redis-field-packet.json \
  --registry /private/witness-registry.json \
  --proof-dir /private/five-source-witness-reports \
  --web-sha <exact-deployed-web-40-sha> \
  --skill-sha <exact-verified-skill-40-sha> \
  --report /private/new-phase24-join-report.json
```

即使输入中的 17 条均 `status=PASS`、五份报告与三份详情**形式全匹配**，报告仍为 `verifiedRealDPassCount=0`、`sourceAuthenticityEstablished=false`、`decision=NO-GO`。这不是独立真实验收结论。网站候选 FF-018、FF-019、FG-025 的许可与官网 DB 授权需独立完成；PG17 物理异机、S3/R2/CDN、Redis 真故障切换、供应商最终账单、低端实体硬件和回滚签核仍必须有真实来源及第二审核人。只有全部真实 17 个 D case 经独立复核且正式授权闭环后，发布责任人才可启动单独的发布判定；此脚本永不产生 GO 或关闭 #132。

测试：`python -m unittest tests/test_studio_phase24_release_join_132.py`（实际 CI 按现有 python-full 路径发现）。所有测试数据为合成，经过结构校验仍不代表现场真实发生。

**仓库红线：**先登记 #132 → 独立分支 CI 14/14 → 与 studio2 对比 ahead>0/behind=0 / main unchanged / PR Draft → `expected_sha` 和 `force=false` 快进 → Push 与 PR 同 SHA 双 14/14。若 Phase23 正式 CI 未完成，Phase24 不快进。生产一直 NO-GO。
