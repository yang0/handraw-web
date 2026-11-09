# #132 · D 级生产证据离线验收接收说明

工程基线：`studio2@5c4f61d03fc21aa0631064591f26af4a6336dfd8`。**PR #131 始终 Draft，生产 NO-GO，禁止合入 main。**

本切片仅从已验证的并行收口分支审查并迁入 `ops/studio_release_d_attestation_112.py` 与 `tests/test_studio_release_d_attestation_112.py`；不引入该并行分支的全部历史提交、不改变生产 CSS/JS、Web DB/Skill 官方目录或收费网关。

- 校验门禁共 **17 项**：#11 编辑批准/strict 对账 4 项（FF-018 / FF-019 / FG-025 分项审批），#84 多图/权限 7 项，#112 供应商账单/物理恢复/真实存储/实体设备/发布回滚 6 项。
- 无清单时 17 项均为 `MISSING`；输入须是只读私有 JSON，文件权限 0600（Unix），固定实际部署 40 位 SHA、UTC 30 日内、操作者与不同的复核人。
- 拒绝含额外字段、重复门禁、过期/未来时间、SHA 不符或非私有证据文件；报告只输出固定门禁标识和状态，不复制证据 ID、凭据、用户内容或原始媒体。
- 即使私有清单自报全部 PASS，结果仍为 `decision=NO-GO` 且 `issueClosureAuthorized=false`。工具只检查声明结构，**不能核验原始账单真实性或替代受授权运营/安全双签**。

受权人员在隔离工作机上运行：

```bash
python ops/studio_release_d_attestation_112.py \
  --manifest /private/authorized-d-evidence.json \
  --release-sha FULL_40_CHAR_DEPLOYED_SHA \
  --report /private/new-redacted-d-gate-report.json
```

无任何正式 D 级证据时也可生成缺项清单（无需真实凭据）：

```bash
python ops/studio_release_d_attestation_112.py \
  --release-sha FULL_40_CHAR_DEPLOYED_SHA \
  --report /private/new-missing-gates-report.json
```

输入范式见 `ops/studio_release_d_attestation_112.py` 的 `GROUPS` / `FIELDS`，详细现场流程见 [release-d-gates-112-84.md](release-d-gates-112-84.md)，最终工程审计见 [final-engineering-closure-20261109.md](final-engineering-closure-20261109.md)。

**真实发布最终条件**：FF-018、FF-019 和 FG-025 逐项网站审批、Web DB 和 Skill 官方严格 `--strict` 对账、真实供应商账单/退款、PG17 物理备份异机恢复/PITR、真实 R2/S3/CDN 权限、Redis 多实例、实体设备、独立审计与发布/回滚签核。所有外部证据未具备前，[#132](https://github.com/yang0/handraw-web/issues/132) 继续 Open 且生产 NO-GO。


## 2026-11-10 · 新增 FF-019 与真实环境来源契约（仍然 NO-GO）

由于 Skill `main` v1.9.11 加入第三项待审画风 FF-019，D 级签核的第一组由原来的两项编辑审批 + 严格目录对账（3 项）变为**三项独立编辑审批 + 严格目录对账（4 项）**，整体 **17 项**。先前的 16 项说明仅为历史快照，不能继续用 16/16 声称全部完整。新旧发布工具均没有自动 GO 权限。

额外只读来源声明校验器：

```bash
python ops/studio_d_environment_assertions_132.py \\
  --claims /private/real-environment-claims.json \\
  --web-sha FULL_DEPLOYED_WEB_SHA40 \\
  --skill-sha FULL_SKILL_SHA40 \\
  --report /private/new-redacted-d-source-report.json
```

17 条现场证据须分别声明**真实环境来源类别**、Web/Skill 实际 SHA、UTC 时间、独立操作者与复核者、外部原始证据的 SHA256 与私有证据 ID，明确 `isSimulation=false` / `physicalOrRealProviderClaim=true`，校验器拒绝 `moto-s3`、假账单、模拟 Redis、模拟 GPU 等错误类别。清单使用仅所有者可读的私有文件，禁止携带密钥、完整账单、用户正文或媒体字节。程序不读取原始账单或连接真实供应商；**17 条全部自报 PASS 仍仅表示字段和来源声明完整，必须再由有权限的两人验证原始证据，结果始终 NO-GO**。当前尚未提交任何真正的 D 级现场证据。
