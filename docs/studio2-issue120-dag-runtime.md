# Studio 2.0 · Issue #120 DAG Runtime 交付与边界

Issue：[120](https://github.com/yang0/handraw-web/issues/120) · 父任务 #104 · Draft PR #131

## 设计与权威边界

`studio-dag-scheduler-120.js` 提供同步图编译与独立的调度状态机。**运行开始即快照冻结**（含 Graph Revision、参数、数据引用），画布后续编辑只会改变本地新 revision。调度器本身不持久化、不进行收费结算、不创建新的 V3 Run 状态。Gateway POST 的幂等 ID、Run/Item 结果及取消/重试结算完全沿用 #119 的服务端契约。

### 运行拓扑

- 校验节点 ID 唯一、边端点存在、允许节点类型、source/target typed port、Kahn 拓扑无环；输出控制至少有一个输入。空 Loop 仅在存在显式 Series/Loop 参数时才允许作为生成输入。
- 每个 Output Control 是一个工作单元；通过上游 Output Display 或 Article Plan 等路径建立前置依赖。被依赖的 Control **全部成功**后才调度后继，确认成功的上游结果（不是编辑中的数据）作为后续的数据输入。失败节点下游标记 blocked，并显示前置节点名称/ID。
- `continue`（默认）策略允许其他独立分支继续；`fail-fast` 策略禁止新的待运行节点投入调度，已在途请求遵循 #119 处理。用户可在画布任务面板配置失败策略。
- **一个页面的所有 Control 和槽位共用同一个默认容量池**：global=3；默认按 user/gateway/model 分别限制 3；每个 Control 内可有最多四个 worker，但最终均必须先申请相同的 shared permit，直到该槽位完成或异常后释放。每次新运行也复用相同池，不存在 N×3 独立容量漏洞。配置入口 `makeSharedPool({globalLimit,userLimit,gatewayLimit,modelLimit})`，可由 Runtime 初始化时替换。服务端的最终限流、排队和扣费仍须作为跨浏览器/多设备的权威边界。
- `429/500/502/503/504` 使用指数退避并限定尝试次数。任一重试沿用原始 requestId、slotKey、idempotencyKey 和同一 batchId，失败重试不会由客户端创建新的账单请求身份。熔断器按 gateway/model 区分计数；非重试错误不触发额外提交。
- 取消以 `AbortController` 传播到运行上下文、所有仍等待共享配额的槽位和在途前端轮询。**停止本地等待并不等同于云端撤销计费**。已提交的请求 ID/slot ID 保持可恢复；未提交槽位走 #119 cancel-pending API。DOM 面板只投影运行状态，不更新 Run/Item 权威枚举。
- 快照含 source Graph 与引用身份，不读取启动后被编辑的画风/主题/附件；下游数据只从本次成功的上游结果注入其派生 Graph，不改写冻结快照。

## 测试矩阵

| 场景 | 验收 |
|---|---|
| 严格输入、非法有向环、typed port | 编译失败并提供错误 code / node ID |
| 两独立 Control 与其下游 | A/Z 并发，下游 B 必须在 A 输出成功后开始 |
| 共享容量 | 5 / 20 / 100 槽位分布在 5 个分支，峰值不能超过 3 |
| 取消 | 排队任务立即被拒绝，不发出未提交请求 |
| 故障重试 | 429→502→成功：请求 ID 不变；退避 100/200ms；模拟结算不重复 |
| 熔断/非重试错误 | 网关连续超载开启熔断，冷却后恢复；400 不重试 |
| 编辑快照 | 启动后修改原 Graph，编译快照不受影响 |
| 旧入口 | 默认三节点图、Loop/Series 显式方案使用相同编译器与节点命名 |

自动验证：`node tests/test_studio_dag_scheduler_120.cjs`，已纳入 `.github/workflows/checks.yml` 的 `interaction-journey-regression`。不调用真实计费图像模型或外部网关。浏览器 UI 仍沿用现有 Runtime 状态投影。

## 已知边界

共享 worker pool 的强约束覆盖**同一浏览器创作页**内的所有接入 Output Control 路径；跨进程/跨设备/跨服务实例的容量及用户级别计费安全必须继续由网关、队列或分布式锁保证。不要把浏览器池误当成服务器的全局配额。文章计划及独立批次的生成入口需要持续统一使用同一共享池并保持原有 #119 语义。
