# Issue #112 · 供应商账单 ↔ Handraw 付费积分流水双向对账工具

工程基线：从 `studio2@58830d980b271ecfbf2ebff4f8c35037060bab62` 独立分支开发。执行入口：`python -m ops.reconcile_provider_statement_112`；单测：`tests/test_reconcile_provider_statement_112.py`。

**仅限生产或预生产环境下授权人员导出的已脱敏、只读快照。默认拒绝不完整证据。它从不联网、不读取线上 DB、不调用付费 API、不执行退款/补扣、不写用户资产。无论对账结果如何，机器报告始终 `decision=NO-GO`，只表示“异常发现情况”，不代表来源真实性、财务结算授权或生产上线批准。**

## 1. 两套独立来源与边界

- 供应商账单：从真实供应商的任务记录、已结算 charge/refund 明细，**在授权环境**规范化成 `provider_export` JSON。必须有人确认账期已经完整、结算延迟窗口足够，并对原始供应商账单留存私有证据。不能把 Web 自己记录的网关 response 当作独立供应商财务凭据。
- Handraw：从生产类 PG 的 `studio_generations`、持久化 `ledgers` 和接收回调记录各自导出 `handraw_export` JSON。`studio_generations` 代表远端请求/扣费 attempt，不代表 V3 Work；`generation_runs` 和 `generation_items` 提供 Run/Item/Slot 关联。映射务必由 operator 确认，不能凭名称拼接。当前文件只支持真实 `cost_type=credits` 的扣款；`free` 免费额度**未覆盖，必须保留独立 NO-GO 门禁**，不能以空 ledger 假装零扣费。
- **强制用户作用域**：每条 provider task/event 和 Handraw attempt/ledger/callback 均要求同一个 `owner_key`（由授权导出人员用安全、不可逆的方式为同一账号赋予的**假名标识**）。匹配主键为 `(owner_key, request_id, attempt)`，因为 Web 的 requestId 幂等键并不保证跨账号全局唯一。它不是用户邮箱、原始 userId、access token，也不出现在机器报告里。真实供应商侧若不能把任务可靠归属到同一 owner_key，不得伪造关联，应明确登记无法对账并保持 NO-GO。
- 两者必须为同一个完整 40 字符部署 SHA、同一个 UTC 时间窗、同一个 environment（`preproduction` 或 `production`）。供应商发票 `invoice_final=true` 且 `exported_at_utc >= end_utc + settlement_grace_minutes`，其中 grace 至少 60 分钟；**满足声明不等于工具已证明供应商发票真实完整**。
- 供应商货币用 `amount_minor` 与 ISO 货币码（如 USD）；Handraw 钱包用 `delta_credits`。**两个不同单位绝不直接相等比较**。业务人员应凭已审批的计价映射完成另外一轮财务核对。
- 禁止原始 `authorization`、Cookie、email、prompt、URL、media、IP、用户资料、完整发票文本或密钥入仓库/工件。解析器严格拒绝不在合同里的额外字段。用户原始内容/账本保留在隔离目录。

## 2. Provider JSON 规格（以下全为虚拟数据）

```json
{
  "schema_version": 1,
  "source": "provider_export",
  "environment": "preproduction",
  "release_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "window": {
    "start_utc": "2026-11-01T00:00:00Z",
    "end_utc": "2026-11-02T00:00:00Z",
    "exported_at_utc": "2026-11-04T00:00:00Z",
    "settlement_grace_minutes": 1440,
    "invoice_final": true
  },
  "currency": "USD",
  "tasks": [
    {"owner_key": "owner-A", "request_id": "req-1", "attempt": 1, "provider_task_id": "task-1", "state": "succeeded"}
  ],
  "events": [
    {"event_id": "invoice-1", "owner_key": "owner-A", "request_id": "req-1", "attempt": 1,
     "provider_task_id": "task-1", "kind": "charge", "currency": "USD",
     "amount_minor": 125, "occurred_at_utc": "2026-11-01T12:00:00Z"}
  ]
}
```

任务状态只允许 `succeeded/failed/cancelled/unknown/queued/running`；charge/refund amount_minor 必须为正整数，允许一个 attempt 下分别出现有权威依据的 charge + refund。所有账务事件按给定时窗核验，跨账期清算需另行明确账期桥接方案，不能任意归并。provider account/task ID 的归属仍由实际供应商后台二次验证。

## 3. Handraw JSON 规格（仅付费积分示例）

```json
{
  "schema_version": 1,
  "source": "handraw_export",
  "environment": "preproduction",
  "release_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "window": {
    "start_utc": "2026-11-01T00:00:00Z",
    "end_utc": "2026-11-02T00:00:00Z"
  },
  "attempts": [
    {"owner_key": "owner-A", "request_id": "req-1", "attempt": 1, "run_id": "run-1",
     "item_id": "item-1", "slot_key": "slot-1",
     "provider_task_id": "task-1", "submitted": true,
     "status": "success", "cost_type": "credits"}
  ],
  "ledger_events": [
    {"event_key": "ledger-charge-1", "owner_key": "owner-A", "request_id": "req-1", "attempt": 1,
     "kind": "studio_gen", "delta_credits": -3,
     "occurred_at_utc": "2026-11-01T12:00:00Z"}
  ],
  "callbacks": [
    {"callback_event_id": "callback-1", "owner_key": "owner-A", "request_id": "req-1", "attempt": 1,
     "provider_task_id": "task-1", "state": "succeeded",
     "occurred_at_utc": "2026-11-01T12:00:00Z"}
  ]
}
```

- 内部状态允许 `success/refunded/failed/cancelled/error/queued/running`。因请求进入供应商但未取得 taskId 的情况，应记录 `submitted=true`、`provider_task_id=null`；这会被审计器标记 `unmatched_submitted_attempt`，**禁止将查询不到任务推断为“供应商肯定没收到”**。
- 在远端提交前确定失败可用 `submitted=false`、`provider_task_id=null`、`status=refunded`，并要求原 debit 和一次 refund。确定取消或失败后的 refund 必须仍关联相同 requestId/attempt。
- `callbacks` 可以为空，代表本窗口内无回调或执行采用轮询；不能借此推断真实 callback/迟到回调 D 级用例通过。重复同一 callback_event_id 且内容一致可重放，但冲突内容、成功回调碰到已退款、与供应商最终状态矛盾均作为异常。
- 同一 (owner_key,run_id,item_id,slot_key) 如果有两个成功的付费 attempt，列为重复成功/潜在双扣风险；真实重试及不同 OutputItem 的 identity 必须正确归一。

## 4. 使用方式与受控输出

操作员在隔离机器上生成两份 `0600`、不含账号密钥/用户 PII 的 JSON，保存于不向 CI 上传的私人目录。报告路径必须不存在，不能覆写历史证据。使用 Python 标准库即可：

```bash
python -m ops.reconcile_provider_statement_112 \
  --provider /private/qa112-provider.json \
  --handraw /private/qa112-handraw.json \
  --report /private/qa112-gateway-report.json
```

返回码：`0` 表示文件格式合格且**未由静态检查发现异常**；`1` 表示发现对账异常；`2` 表示证据不完整、私有文件权限/账期不合规或拒绝写入。**这三个状态都不能独立签发生产 GO**。

报告只包含发布 SHA、来源环境、行数、异常类别与输入行序号 `attemptOrdinal`，不写 requestId、providerTaskId、URL、Token、原始钱包变更量或供应商金额。报告使用独占创建的 `0600` 文件，人工将私有源文件行序号与财务工单对应；未经审阅不能公开真实报告。

覆盖的阻断异常：双方孤儿任务/事件、无供应商任务却声称已提交、未知/在途状态、重复外部 charge、内部重复 debit/refund/账本事件、退款超量、供应商已确认失败但钱包未退、成功却不存在最终账单、同一 V3 槽位重复付费成功、冲突回调及迟到成功与退款矛盾。独立来源的真实性、实际 wallet.balance、免费额度、更复杂跨账期退款、真实网关契约及人工账务纠纷处理**不在此工具验证能力之内，仍必须 D 级实测**。

## 5. 下一阶段真实财务验收

在隔离预发布环境中先由有权访问供应商账单与 DB 的操作员导出清洗后的样本，固定 invoice 时间窗口、计价规则、供应商账单证据 ID。逐条核对异常类别并记录 owner、resolution 和二次审核签名；实际 429/502/超时、慢回调、免费额度变化和长期 unknown 的完成条件单独签署。必须将真实对账报告、业务审批和生产部署元数据保存于专用运维证据系统，GitHub 仅登记不含敏感信息的证据编号。#112 仍 Open、上线 NO-GO、PR #131 仍 Draft，不改 main。
