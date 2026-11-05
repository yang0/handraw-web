# 产品评审与 DeepSeek 执行协作

本项目由主评审负责用户路径、优先级、范围与验收；指定的 DeepSeek 模型负责分析源码及提出实现补丁。主评审核对补丁、应用修改并运行实际检查。不要把模型回复中的“已完成”当作验收证据。

## 本机配置

- 地址：`http://127.0.0.1:3065/v1`
- 模型：`deepseek-v4.1-flash`
- 凭据：`.local/deepseek-worker.json`，已由 `.gitignore` 排除；不放入命令参数、前端、文档或 Git。
- 入口：`ops/deepseek_task.py`，仅使用 Python 标准库。本地 3065 网关需保持运行。
- 当前 Codex 主会话与全局默认模型不变。

```powershell
python -X utf8 ops/deepseek_task.py --check
```

检查同时验证实时模型目录和实际推理返回，不会启动图片生成。

## 分派任务

先把目标、负责文件、禁止改动的范围和验收条件写入本地任务文件。使用显式文件列表给模型提供上下文，支持 `文件:起始行:结束行`，保留原始行号。默认自动附带项目 `AGENTS.md`。

```powershell
# 只读分析
python -X utf8 ops/deepseek_task.py `
  --task-file .local/deepseek-tasks/review.txt `
  --files docs/product-direction.md demo/assets/main-app.js:527:730 `
  --output .local/deepseek-tasks/review-result.md

# 生成实现补丁，随后由主评审检查和应用
python -X utf8 ops/deepseek_task.py `
  --mode patch `
  --task-file .local/deepseek-tasks/change.txt `
  --files demo/assets/forum-app.js:2434:2447 `
  --output .local/deepseek-tasks/change-proposal.md
```

行号示例会随源码变化，应先定位当前行号。任务与输出使用不同文件名；输出拒绝覆盖已有报告。输出限定在 `.local/deepseek-tasks/`，旁边的 `.meta.json` 记录模型、用量、上下文文件和 `changes_applied: false`。

## 实施与验收

1. 主评审确认问题证据，按影响与改动风险排序。
2. 小批次指定文件，让 DeepSeek 提出补丁；上下文仅限 Git 已跟踪的源码与文档，拒绝隐藏目录和超大输入。
3. 主评审检查文件范围、功能、权限边界及现有工作是否被保留，再应用接受的修改。补丁仍属于待验证建议。
4. 运行适合本次改动的检查；涉及页面时在浏览器核验。报告区分源码检查、自动检查、浏览器验收与生产发布。
5. 未经本次任务授权，不提交、推送、部署或发布；不使用生产数据库测试。

当前接入是“生成补丁 + 主评审应用”的协作方式，不是可以独立操作终端的无人值守编程代理。本机独立 Codex 子进程的文件读取在本次验证中被策略拒绝，因此使用显式源码上下文的 API 任务入口，不放宽机器策略。内置实现 worker 的路由仍遵循 `AGENTS.md` 中的 `luna_worker` 规则。

Codex 原生自定义 provider 要求 Responses 协议，参见 [官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)；本工具直接调用用户提供网关的 Chat Completions 兼容接口，不更改全局 provider 配置。
