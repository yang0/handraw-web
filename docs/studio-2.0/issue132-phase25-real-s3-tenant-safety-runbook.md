# Studio 2.0 · Phase 25 · Issue #132 · 真实私有 R2/S3 两租户 QA 权限探针补强

**2026-11-10 · C 级安全工程；生产发布始终 NO-GO。** 承接 `studio2@51704a9b27801aedc96dbdcd9bcdd5f6f447d6ed`。本切片仅 `ops/tests/docs`，不访问生产、不向真实用户桶上传、不开真实付费 API、无任何 D 级自动 PASS。

## 为什么需要这轮补强

旧 `ops/studio_phase21_infra_probe_132.py` 已检查真实隔离 QA 桶的双租户 GET/PUT 拒绝、匿名 GET 拒绝、限时 URL 过期，但没有检查另一个租户是否能**删除**他人的对象，或 `ListObjectsV2` 是否暴露对方对象的元数据；且 `ownBytesMatched` 只在违规写操作之前检查。若真实网关错误地允许 DELETE、LIST 或“先覆盖、后回 403”，旧观察可能低估隔离漏洞。

Phase25 在**同一只允许 QA disposable bucket 和专用随机前缀**的 opt-in S3/R2 实验中增加：

1. 用 A、B 各自的独立凭据在 `handraw-phase21-qa-*` 测试桶创建**两个随机 canary**，先由各自 owner 读取校验原字节。
2. 测试 A→B 与 B→A 的 GET、PUT、DELETE、`list_objects_v2(Prefix=<other-tenant>)`，必须**两方向都明确 403/AccessDenied**；即便第一方向失败，也必须独立测试第二方向，不允许短路漏测。404/5xx/timeout/200 空列表均**不能**冒充明确拒绝。
3. 用匿名客户端分别 GET A 和 B 的私有 canary，两项必须显式拒绝；若开启 `--test-presigned-expiry`，有效签名 URL 先返回 200，过期后必须返回 401/403，不接受重定向/超时冒充安全拒绝。
4. 做完全部“越权写/删除”探针后，用各自 owner **再次读取原本的 64-byte 随机 canary**，验证完全相同。若网关先实际改写再返回 403，也必须 BLOCKED。
5. 无论是否 FAIL，`finally` 均尝试仅用各自 owner 凭据删除**本次随机产生**的两个 canary；**禁止清理任何非本次测试对象**。若真实 QA 网关删除失败，要由现场值班员按独立清单检查遗留测试对象；脚本不输出敏感对象路径或密钥。
6. 新增 `observed.crossTenantDeleteDeniedBothDirections`、`observed.crossTenantListDeniedBothDirections`、`observed.postDeniedProbeOwnBytesMatched`。和原 `observed.crossTenantReadDeniedBothDirections`、`crossTenantWriteDeniedBothDirections`、`anonymousDenied`、`ownBytesMatched` 一起必须全部为 true，才能说明**本次 QA canary 探针**结构通过。报告仍是 `decision=NO-GO`。

## 受控现场运行

保持 Phase21 原本的严格前置条件，不另开绕过通道。由有授权的运维在**预生产隔离机器**中准备两个独立 scoped QA bucket 凭据，权限分别限制至 `phase21-qa:.../tenant-a/` 和 `tenant-b/`；确认专用 QA 桶不会映射真实用户对象。记录实际 S3/R2 端点、区域、外部操作者/审核员与部署 Web/Skill SHA 到私有证据库，**不得写入 GitHub**。

```bash
export HANDRAW_PHASE21_INFRA_D_PROBE=YES
# HANDRAW_PHASE21_S3_A_KEY_ID / _SECRET、B_KEY_ID / _SECRET：
# 仅通过私有预生产的受控凭据管理器注入，不写到命令行或 repo。
python ops/studio_phase21_infra_probe_132.py \
  --mode s3 --environment preprod-qa-tenant-isolation \
  --endpoint https://<dedicated-qa-s3-endpoint> \
  --bucket handraw-phase21-qa-tenant-isolation \
  --prefix phase21-qa:dedicatedrandom123 \
  --test-presigned-expiry \
  --report /private/new-phase25-s3-qa-report.json
```

脚本原本要求 TLS、一次性 `HANDRAW_PHASE21_INFRA_D_PROBE=YES`、专用 QA 桶及前缀，`--report` 仅创建新的 0600 私有文件。输出即使观察字段均为 true 也**无法证明**实际已部署 app 的私有素材 ACL、CDN 下架 URL、真实签名撤销、恢复媒体、跨用户 Web/Skill 链路、Redis 故障切换或其他 17 项 D 验收。

**独立复核要求**：真实测试桶策略、A/B 凭据权限声明、实际 HTTP 状态、源对象和恢复字节摘要、CDN tombstone 和短效/撤销 URL 的受控原始日志由第二审核人单独核对，再关联 Phase22/24 witness ledger 与 17 D 级主表。同一个脚本的自报 JSON 不具有真实来源证明力。

## CI / 发布门禁

只运行离线 FakeS3 负向夹具，覆盖删除与列表漏洞、错误 403 仍改写原字节、404、timeout、双向拒绝和清理。测试命令：

```bash
python -m unittest discover -s tests -p 'test_studio_phase21_infra_probe_132.py' -v
```

独立分支 SHA 14/14、compare ahead>0/behind=0、PR #131 Draft、main 不变后，才执行 `update_ref(expected_sha,force=false)` 安全快进 studio2，再等待 Push 与 PR 两套相同 SHA 14/14。未满足任何条件时停在独立分支，Issue #132 Open、PR Draft、生产 NO-GO；FF-018/FF-019/FG-025 依旧未获真正官网许可，17 D 级真实复核 0/17。
