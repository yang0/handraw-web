# Issue #110 · AI 创作导演推荐质量：可重复离线评测门禁

截至 2026-11-08，本报告用于 AI 父任务 #110 的审计：子任务 #125（单图/系列/文章结构化规划）与 #126（GraphPatch 受控修改）都已按工程范围交付。**评测器本身能检测合法性、主题标签匹配、候选多样性、两次推荐一致性；离线正例不等于真实模型已经达到质量目标**。

## 评测边界

- 数据集：tests/fixtures/studio_ai_quality_110.json，六种主题与人工标定的合理画风、图型、画幅，包括幽默四格、极简线条、时间轴科普系列、中国水墨、科技商业摄影、儿童图文科普。场景含 image / series / article。
- 样本：每个场景两次结果，共 12 条；必须是 Studio 实际 /api/studio/ai-plan 返回的规范化 Proposal，而不接受任意未经校验的模型原始 JSON 假冒成功。
- 执行：ops/eval_studio_ai_quality_110.py。评估输入必须包含用户实际可用资源清单的安全快照，不会调用付费网关。
- 单元/集成门禁：tests/test_studio_ai_quality_110.py 使用真实当前 catalog 和临时测试账号、模拟 AI 合法回复，穿过真实后端 Schema/权限/资源解析，以验证评测器与规划器合同。正例和带偏置/漂移/非法资源/无效返回的反例都运行。
- 阈值：标签匹配度不小于 0.85；不同场景风格/布局最小唯一覆盖比不小于 0.65；同一场景两次输出一致比例不小于 0.90；所有样本需合法且理由/替代候选齐全。
- 指标：validResponses、editorialFit（风格/布局/画幅相符的分项比例）、distinctStyleCount、distinctLayoutCount、diversity、consistency，以及所有校验失败原因。
- 风险：该评测对人工预设的“合理”标签敏感，不应单靠 Top1 命中率评判真正优秀的多样化创意。模型质量上线结论需人工盲审、真实样本和长期偏置分析。

## 对实际模型运行结果的复评

测试环境或后续验收人员可以按以下流程评估**真实模型返回结果**，而不重新调用生图/收费接口：

1. 在有授权的测试账号环境下，以数据集六个 subject 分别调用 /api/studio/ai-plan 两次；每次响应连同 caseId、trial（1 或 2）组成 records 数组。不要把私有图片、Prompt 定义、Cookie、API 密钥或完整个人账号内容写入样本文件。
2. 从同一测试账号的 _user_catalog(db,user) 导出允许使用的 ID 列表（style 与 layout），仅保留必要 ID；不要导出隐藏定义、秘钥或访问凭据。务必使用同一有效资源版本。
3. 保存为本地质量数据文件后执行：

    python ops/eval_studio_ai_quality_110.py --corpus tests/fixtures/studio_ai_quality_110.json --responses /path/to/responses.json --allowlist /path/to/authorized-ids.json --output /path/to/report.json

4. 当评测报告 ok=false，先检查是否为授权目录版本变动、模型输出不合协议、场景标注有争议、推荐偏置，还是同主题漂移。评测器退出码为非零；不自动采用固定 FA/SC 编号“修复”失败，不会触发生图/扣费。
5. 保存脱敏模型回复摘要与人工盲审记录用于后续 #112 真实供应商验收；对不符合预期的评测样本调整或模型提示词应另提 Issue，不能仅通过修改金标掩盖失败。

示例结果 JSON 项最外层应有 caseId、trial 和 response；其中 response 必须是完整且成功的规范化 Studio AI Proposal（含 ok、schemaVersion、kind、source=model、phase=review、creationSpecPatch、cost、planPatch 等）。allowlist 形如 {"style":[{"id":"FA-001"}],"layout":[{"id":"SB-002"}]}，必须覆盖全部数据集可接受选项。

## 与父任务和上线门禁的关系

- #125 对应：授权完整目录、模型 JSON 合同、理由/候选、PlanSlot、锁定保护、版本、无付费 Run。
- #126 对应：Canvas GraphPatch 预设/自由 AI、选区作用域、后端 DAG、媒体授权、锁定、差异审阅、CAS、撤销。
- #88/#90 对应：目录选择偏置及非 JSON / 502 分类的现有回归，不能据此声称真实模型质量已达标。
- #110 对应：提供本可重复评测框架，且需要识别“结构回归”和“真实模型质量”的证据级别差异。
- #112 仍独立要求：真实 AI/图像供应商与财务账本、真实用户体验和跨环境对账。离线评测全绿不等于正式上线 Go。

验收 CI 保持原来的 14 个 Jobs，新增独立 step 运行本数据集和反例；生成 artifacts/ai-110-offline-eval.json，并明确 realModelQualityVerified=false。正式外部模型实测数据并不包含在本轮自动化 CI 中。
