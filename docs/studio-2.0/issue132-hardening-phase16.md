# Issue #132 · 官网审批防伪 / Canvas 首次拖拽 / 生产 D 级环境断言

2026-11-10。只读工程增强，不是发布授权。基线来自 `studio2@a16f919b3a48e23a392f632a5d8d056baec61796` 的独立分支、Push、Draft PR **同 SHA 三套 14/14 SUCCESS**。PR #131 继续 Draft，main 不合并，生产 NO-GO。

## A. 三项画风逐项网站审批 — 双角色密码学验签

Skill `main@9248843ba4659a1d9afbc177ae73b91bb1af68a9` 当前为 540 条、Web 已批准静态目录 537 条，Skill-only 为 FF-018 / FF-019 / FG-025。三项依旧仅在 `ops/official_catalog_pending_11.json` 指纹锁定等待人工审批，**不是 Web 已批准资源**。

`ops/studio_official_approval_132.py` 采用 Ed25519 校验同一批准声明上的两种独立角色：
- `website_editor` 必须持有由网站管理员体系授权的私有签名密钥；
- `independent_reviewer` 使用另一个独立公钥与签名；同一个公钥、复用一个角色、伪造角色均拒绝。

签名绑定 `candidateCode`、待审 Skill 完整 JSON 的 SHA256、网站正式发布官方 DB 中该行完整 JSON 的 SHA256、已部署网站 SHA、批准动作 ID、素材/授权审核证据 ID、UTC 时间、结果 `website_published_and_reviewed`。离线核验程序还读取**隔离导出的正式网站批准目录**，要求编号和已审名称与待审候选一致，防止错号或盗用旧签名。

**2026-11-10 双人签名再收紧**：仅有两个不同 `keyId` 并不代表两个独立签名密钥。验证器现在同时拒绝信任公钥清单中任意两条相同的 **32 字节 Ed25519 公钥材料**，即使角色和密钥 ID 不同、其整个清单 SHA256 已由受控配置签出也无法通过。此外，三个资源的 `websiteActionId` 必须彼此唯一；不能复用同一次网站审批动作对多个待审资源做别名。对应真实临时密钥、重复公钥与跨资源审批动作重用回归见 `tests/test_studio_official_approval_132.py`。这仍然无法在代码层证明两个密钥背后一定是不同自然人或实际 Web DB 导出可信；必须在受权环境独立检查人事/角色、签发/吊销记录与真实站点审计。即使证据的双签均有效也始终 **NO-GO**，不会自动将 FF-018/FF-019/FG-025 列为网站官方已批准。

**信任根不得由申请方自选**：公钥清单 `trust-registry` 必须来自网站安全管理员维护的外部私有环境，`HANDRAW_OFFICIAL_TRUST_SHA256` 必须由另一条受控配置链预先固定；验签记录自己填写的公钥、任意签名或自签根不得解锁。**私钥绝不提交仓库、CI、PR 或 Artifact**；本仓库仅包含临时生成的单测密钥。缺失信任锚、任意一位签名、指纹不一致、时间过期、网站已发布 DB 导出缺失、审核人与签发人角色冲突，必须 fail closed。

隔离环境的只读操作示例（所有输入文件 0600、报告新路径且不覆盖）：

```bash
# HANDRAW_OFFICIAL_TRUST_SHA256 只从独立安全配置/Vault 注入。
python ops/studio_official_approval_132.py \
  --bundle /private/editorial-signature-claims.json \
  --trust-registry /private/website-ops-public-keys.json \
  --published-web-styles /private/approved-web-official/styles.json \
  --deployed-sha FULL_DEPLOYED_40_CHAR_WEB_SHA \
  --report /private/new-redacted-editorial-claim-report.json
```

结果只包含 **三个固定代码**和每项 `MISSING` 或 `SIGNED_CLAIM_NEEDS_EXTERNAL_DB_AUTHENTICITY_REVIEW`，不含任何签名、公钥、证据 ID 或人物信息。即使三项真实密码学签名均验证成功，工具仍必须输出 `decision=NO-GO`、`automaticWebsiteApprovalGranted=false`。**外部读取的 DB 导出不是自动证明其就是实际部署来源**；必须再独立核验 DB 只读权限、生产签核与已批准网站资源导出的真实性，并运行 `ops/check_official_catalog_parity.py --strict`。当前三项在 Web 官方 DB 尚无正式审查证明，因此不改变待审 manifest 的状态，也不向 Web 反向发布。

## B. Phase 16 · 首次拖拽启动差异探针

Phase15 三次真实 CI 均观察到 1× 的 `synthetic-move-1` 同窗口有 **9,184 元素**大树更新、两次 `childList` 增删。Phase16 **只在真实 Studio 测试浏览器**，调用相同的 300 原生节点 / 150 SVG 边 / 120 张互异已解码 WebP、相同真实 `pointerdown` 和 3 次明确 `isTrusted=false` 的合成 move，分别在 1×/模拟 4× CPU 的四窗口内暂时安装并恢复：
- 根级元素 `class/style` MutationObserver：全局根、Studio shell、viewport、nodes layer、overlay；
- `childList` 观察浮层/工具栏与节点容器 mount/unmount，输出按角色的固定枚举计数；
- `getBoundingClientRect`、`getComputedStyle`、`offsetWidth/Height/Top/Left` 的调用计数包装器，记录其读取目标的**固定角色，不记录任何内容或定位符**；
- 与有界 Chrome CDP `UpdateLayoutTree` / 失效原因聚合对应，测试后恢复全部原型方法与监听器；Graph、Undo、120 图解码和 SVG 的已有严格校验不变。

本实验能对「首次拖拽是否出现祖先 class 切换 / 全局浮层挂载 / 额外几何读取」提出更具体的后续因果假设，但探针本身可能干扰布局刷新；**读属性次数不等于强制同步布局次数**，同窗口 Chrome Trace 也不证明某个函数独立致因。全部汇总保存 `artifacts/studio-111-phase16/summary.json`，没有原始 Trace、DOM 文本、原图、账号/付费请求。未经双模拟 CPU 稳定 A-B-A-B-A 收益，禁止改生产 `studio-app.js`/CSS。

## C. D 级真实环境 17 项断言矩阵

新版 `ops/studio_release_d_attestation_112.py` 新增独立 `editorial_ff019`，原 16 项→**17 项**，避免第三项待审画风被整体目录验收掩盖。

新 `ops/studio_d_environment_assertions_132.py` 仅离线验证签核申请的声明结构：17 项 caseID、真实服务来源类别、Web 与 Skill 完整部署 SHA、UTC 30 日内的观测时间、不同的操作者/复核人、每条独立私有证据 ID 与 SHA256、明确 `isSimulation=false`。它会拒绝 CI/Moto、模拟 Redis/供应商/触屏的来源类别冒充真实 D 级证据；证据文件仅接受 owner-only 私有路径，不复制用户数据、原始账单或密钥。

```bash
python ops/studio_d_environment_assertions_132.py \
  --claims /private/real-world-release-cases.json \
  --web-sha FULL_DEPLOYED_40_CHAR_WEB_SHA \
  --skill-sha FULL_SKILL_40_CHAR_SHA \
  --report /private/new-redacted-d-claims.json
```

**红线**：以上两套校验器都不能确认提交的原始物理设备、S3/R2/Redis 或供应商账单真实性，不能联网验证私有账单，不能自动签署生产发布。即使输入中 17 条全为 `PASS`，其输出也是 `decision=NO-GO`、`issueClosureAuthorized=false`。必须有独立权限人员在真实预生产/生产等价环境里复核原始材料、实地回滚演练、低端设备、PG17 物理恢复及 Web/Skill 双端正式审批后，才有资格人工评议发布。

## 执行纪律

所有改动限 `ops/`、`tests/`、CI artifact、说明与验证依赖，PR #131 保持 Open Draft，`main` 不变。独立分支 14/14 → 比对 ahead>0/behind=0 → `expected_sha` + `force=false` 安全快进至 `studio2` → 同一 SHA 的 Push/PR 双 14/14 后才称 C 级验收完成。Issue #132 在 D 级证据缺失时继续 Open、生产 NO-GO。
