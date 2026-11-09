# Studio 2.0 · 五项剩余 Issue 最终收口执行记录

**建立日期：2026-11-09** · Web: [yang0/handraw-web](https://github.com/yang0/handraw-web) · Skill: [yang0/handraw-style](https://github.com/yang0/handraw-style) · 目标：`studio2` / Draft PR #131；**禁止合入 main、禁止无真实审批放行生产**。

本专项从 `studio2@8f195bbe6c7eec83719ee8b9011a332699f460de` 建立独立分支 `studio2-closeout-remaining-issues-20261109`，只执行可审计且能重复运行的补验，不因“任务已分配”或“CI 已绿”宣称生产完成。

## 当前闭环事实与剩余阻塞

| Issue | 现有可复验成果 | 真实剩余条件 | 关闭状态 |
| --- | --- | --- | --- |
| [#111](https://github.com/yang0/handraw-web/issues/111) Canvas | Phase 12 300 节点、150 SVG edges、120 独立 WebP；单独无边/无卡/全局状态选择器消融都不能消除 ~9,185 更新；联合 no-visual 使大事件 3→1 但停掉视觉反馈 | 剩余 1 次大型更新的鼠标伪类/浏览器更新时机；等价交互下的稳定 1×/4× CPU 优化；低端实体硬件预算及焦点/多选/触屏实机验收 | OPEN |
| [#11](https://github.com/yang0/handraw-web/issues/11) 资源 | 当前 Web 静态 537、Skill main 539，只有 FF-018 / FG-025 两个受指纹保护的待审批项 | 网站维护者逐项决定收录/保留为非官方；授权证据；真实官网 DB 已发布导出；两仓正式 SHA 的 `--strict` 全绿 | OPEN |
| [#84](https://github.com/yang0/handraw-web/issues/84) V3 作品 | 逻辑 Run/Item/Work、封面、多图幂等和审核安全；Skill 真 CLI + PG17 + moto S3 模拟集成 | 真正的 R2/S3/CDN、跨账号多图移动端/GIF/作者换封面/下架、账本审查及远端 Skill 发布链 | OPEN |
| [#112](https://github.com/yang0/handraw-web/issues/112) E2E | 14/14 CI、本地浏览器、PG17 一次性库、多实例部分受控模拟、异常账本测试、S3 moto、逻辑 dump/restore | 真实对象桶访问控制、Redis 多实例恢复、供应商扣费退款双向对账、经批准的 PG17 物理冷备和异机恢复、实体低端 CPU/GPU、签核 | OPEN |
| [#101](https://github.com/yang0/handraw-web/issues/101) Epic | 四大主要创作模块及 Runtime/数据权威/画布功能已进入交付分支 | #111/#11/#84/#112 需要真实签核后才能最后关闭 | OPEN |

## #111 · 残余更新的下一层可证伪实验

入口：`ops/canvas_phase13_pointer_111.py`，由真实 Studio 300 节点浏览器基准调用，并且**只使用已有 `__HANDRAW_TESTING__` 模式，生产 CSS/JS 不改**。Phase 12 单条 `no-visual` 仍保留一次约 9,185 元素的 `UpdateLayoutTree`。本轮将它进一步分解为：

1. `idle-stationary`：鼠标停在画布节点，未按键也没有 move。
2. `hover-moving`：鼠标仅 hover 移动，没有拖拽/Graph 坐标改变。
3. `pressed-stationary`：真实 pointerdown 但没有 move。
4. `drag-no-visual`：真实按下移动，但临时跳过所有拖拽视觉写入。
5. `drag-no-visual-hover-mask`：与上项相同，仅在实验页用固定白名单 CSSOM 关闭已知节点 hover 规则，随后原样恢复。

每个 Trace 仅 0 或 3 次物理鼠标位移，有界 30MB 内存，输出只有原因分类、`elementCount` 和脱敏属性变更类别。最后两项再以模拟 1×、4× CPU A-B-A-B-A 对照样式累计时间、Style+Layout、rAF P95。任何缩减 hover 交互或关闭视觉写入的方案**只能作为诊断，不是生产候选**。仅当相同交互保真且稳定获益后，才有条件申请产品改动。

## #11 · 官网编辑与图片授权核对包

Skill `main@f4cba38b8682345168ccbcd80cf4f5a3d9feb761` 下：

| 编号 | Skill 官方目录名称 | 参考图片 | 评审必须补齐 |
| --- | --- | --- | --- |
| FF-018 | Low Poly Art（低多边形艺术） | [FF-018.webp](https://github.com/yang0/handraw-style/blob/f4cba38b8682345168ccbcd80cf4f5a3d9feb761/images/individual/FF/FF-018.webp) | 生成图原始来源、使用授权、是否允许公开售用、名称/描述/图像适配 |
| FG-025 | Perler Bead Pixel Art（拼豆像素画） | [FG-025.webp](https://github.com/yang0/handraw-style/blob/f4cba38b8682345168ccbcd80cf4f5a3d9feb761/images/individual/FG/FG-025.webp) | 同上，另核实商标/品牌名使用语境与图片来源 |

以上两项 **有 Skill 元数据、图像和仓库 LICENSE，不等于已获得网站官方收录许可或证明具体图片的原创授权**。对每项由网站维护者明确“批准官网收录 / 仅 Skill 非官方候选”。批准后通过官网管理员接口办理官方资源发布；不批准则在 Skill 的独立分支中从 *官方索引* 撤下，素材原件和用户草稿不删除。禁止默认导入 Web、删除素材或绕过 `--strict`。若两仓/DB 仍有 pending，#11 不得关闭。

授权维护者可在私有环境只读导出批准的官网 PG17 资源，随后执行：

```bash
python ops/export_official_assets.py \
  --pg-dsn-env HANDRAW_OFFICIAL_EXPORT_PG_URL \
  --skill-root /private/reviewed-skill/skills/handdraw-style-prompter \
  --out /private/new-empty-official-export

python ops/check_official_catalog_parity.py \
  --skill-root /private/reviewed-skill/skills/handdraw-style-prompter \
  --approved-export-dir /private/new-empty-official-export \
  --strict
```

必须确认网站 DB 和 Skill 的真实发布 SHA、审核结论与媒体授权证据。这些不能由当前 CI 自动提供。

## #84/#112 · 已具备真实环境操作脚本，缺的是受权私有证据

现有只读工具（真实操作环境由 DBA/安全/财务授权并提供，不在公共 Actions 中运行）：

- `ops/audit_object_leak_112.py`：实际媒体对象匿名、作者、跨用户、隐藏、过期签名及桶目录 8 场景 GET Range 探测，拒绝跟随重定向，不读媒体响应体。
- `ops/reconcile_provider_statement_112.py`：实际供应商账单与 Handraw 权威 ledger 的双向只读对账，退款/unknown/重复回调异常一票否决。供应商货币和 Handraw 积分**不做单位相加**。
- `ops/pg_release_restore_drill_112.py`：CI 使用一次性 PG17 逻辑备份与双独立恢复；**不能代替停库完整物理冷备、离站/异机恢复、物理回滚和 RPO/RTO 签核**。
- `ops/studio_release_d_attestation_112.py`：私有证据验收矩阵输入工具。精确覆盖 #11 3 项、#84 7 项、#112 6 项，共 16 项；**默认全部缺失且 NO-GO**。

D 级私有证据不进 Git、不进公共 CI Artifacts。每一项最少需要 `gate/status/evidenceId/operator/reviewer/observedAtUtc`，操作者和复核人不同；关联精确部署 40 位 SHA，30 天内 UTC 证据，任何空缺、过期、冲突或错误权限都不能宣称签核。

示例（只是一个未完成项目，不能代替真实 16 项）：

```json
{
  "schema_version": 1,
  "environment": "preproduction",
  "release_sha": "REPLACE_WITH_FULL_40_CHAR_DEPLOYED_SHA",
  "checks": [
    {
      "gate": "real_object_bucket_and_expired_url",
      "status": "PENDING",
      "evidenceId": "PRIVATE-REVIEW-TICKET",
      "operator": "qa-operator",
      "reviewer": "independent-reviewer",
      "observedAtUtc": "2026-11-09T00:00:00Z"
    }
  ]
}
```

私有文件只允许 0600 权限。在授予访问权限的机器执行：

```bash
python ops/studio_release_d_attestation_112.py \
  --manifest /private/authorized-d-acceptance.json \
  --release-sha FULL_40_CHAR_DEPLOYED_SHA \
  --report /private/new-redacted-closeout-report.json
```

输出**只保留每个固定 gate 的 PASS/PENDING/FAIL/BLOCKED/STALE 状态及总量**，不写入证据 ID、操作者姓名、账号、用户数据、DSN、URL、Cookie、账单原文。就算全部自报 PASS，该工具仍输出 **NO-GO、issueClosureAuthorized=false**：还必须在独立审计系统核验证据的真实性以及运营正式放行签字。

## 工程安全和 Issue 关闭规则

- 每项任务先有 Issue，本轮修改始终留在独立分支；14/14 全绿、ahead>0/behind=0、`force=false + expected_sha` 才能快进 `studio2`，同 SHA Push 和 Draft PR #131 又各自 14/14。
- 若没有 **1×/4× 双重复、等价可见拖拽体验** 的稳态收益，绝不修改生产 CSS/JS。
- 当且仅当 #11 官网正式审核和 strict 已成功、#84 实际 Web/Skill/存储完整验收、#112 真实供应商/备份/Redis/安全/实机和批准书齐备，才按实际证据逐项关闭；#111 对残余布局问题和物理硬件做独立验收；**#101 作为总 Epic 最后关闭**。
- 目前生产始终 **NO-GO**，PR #131 始终 Draft、`main` 不动。不能因为补齐工具或 CI 绿灯而声称上述外部验证已经发生。
