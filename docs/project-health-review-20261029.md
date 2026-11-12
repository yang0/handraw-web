# Handraw Web 项目健康度审查 — 2026-10-29

> 历史产品评审。旧数据库实现内容已移除；当前数据库与运维以 `docs/local-operations.md` 为准。
审查范围：backend/、demo/assets/、tests/、ops/、.github/、仓库卫生。
方法与边界：并行三路审查（后端 / 前端 / 基础设施）+ 主审实测复核；凡与实测冲突的结论以实测为准（见文末「已澄清的误报」）。
本文件只做记录与排序，不含代码改动。

## 结论速览

项目**工程质量明显高于同类自建项目**：SQL 全参数化（91 处 f-string 逐一核对，无一注入）、零裸 except、迁移只增不删、部署脚本可回滚、CI 有隔离 PostgreSQL。当前主要风险不在「写得差」，而在**四个单文件失控**、**大量改动未入库**、**CI 覆盖落后于本地**、以及**一条已发现的凭据泄漏**。

实测基线：Python `82 passed`（pytest 与 `unittest discover` 一致），Node `.cjs` `16/16 exit=0`。**测试本身是健康的**，问题在覆盖面与入口规范。

## P0 已完成修复（本次已改）

| 项 | 原状况 | 处理 |
|---|---|---|
| `backend/config.py:72` 硬编码真实 Key `sk-a2a-...` | 兜底 dict 写死生产 Key，文件已在工作区 `M` | 改为读 `HANDRAW_AI_KEY/URL/MODEL` 环境变量，默认空 |
| `ai-service.json` 含明文 Key 且**未被忽略** | `git check-ignore` → NOT-IGNORED，`git status` 已列 `??` | `.gitignore` 补 `ai-service.json` |

复核：`git check-ignore -v ai-service.json` 已命中；已跟踪文件中无该 Key；`82 passed` 未回归。
**仍需你决策**：该 Key 曾以明文落在工作区文件中，建议视为已泄露并轮换。

## P0 待处理

1. **74 项改动未提交、20+ 新模块游离**——`backend/curation*.py`、`forum_resources.py`、`resource_discussions.py`、`demo/assets/{curation,works-browser,forum-work-post,quick-create}*`、`ops/deepseek_task.py` 等均为未跟踪状态。这是当前最大的工程风险：无版本历史、无回滚点、`git stash` 或误删即永久丢失。
   建议：按功能分批提交（curation / forum-resources / single-backend / studio-modes），每批先跑测试。

## P1 结构性（直接影响上下文开销）

| 文件 | 行数 | 问题 |
|---|---|---|
| `demo/assets/studio-app.js` | 11,870 | 单一 IIFE，16 个分节、96 个函数、10 个 localStorage key、76 处 `window.`；无法按需加载 |
| `demo/assets/shared.js` | 3,548 | 承载 App/路由/渲染/鉴权等跨页职责 |
| `backend/services.py` | 2,732 | 业务聚合层 |
| `backend/admin_services.py` | 2,477 | 后台逻辑 |
| `backend/server.py` | 2,407 | `_handle_post` 单函数 638 行、`_handle_get` 410 行 |

**这就是「上下文 200k 不够用」的直接原因**：任何触及这四个文件的任务，一读就是 10 万+ token。
可行的缓解（按收益排序）：
- 把 `studio-app.js` 按现有 16 个分节标记拆成 ES module（分节注释已存在，拆分成本远低于看起来的规模）；
- `server.py` 的路由按 `curation_routes.py` / `forum_resource_routes.py` 的现有模式继续外移；
- 日常审查走「grep 定位 + 分片 read」，避免整文件入上下文；
- 大分析任务交给子代理隔离（本次三路审查即如此，主上下文只收结论）。

## P1 其他

- **CI 覆盖落后**：10 个本地已绿的 `.cjs` 完全没进 CI（`test_v2_studio_state`、`test_studio_mode_navigation`、`test_product_refresh`、`test_resource_presentation`、`test_works_browser`、`test_article_unified_editor`、`test_single_backend_navigation`、`test_studio_resource_entry`、`test_forum_work_post`、`test_article_history_persistence`）。而 `ops/web.ps1 deploy` 以 CI 成功为部署前置——等于这些模块回归了照样能部署。建议改成 runner 循环执行 `tests/*.cjs`，不要手工列举。
- **端口三处不一致**：`config/environments.json` 与 `ops/web.ps1`、`run_dev.ps1` 用 **3000**；`service.bat`、README、`docs/single-backend.md` 用 **3080**。新环境会起错端口。
- **索引缺失**：`interactions` / `collections` / `unlocks` 三张高频过滤表 `CREATE INDEX` 零命中，而 `services.py:808-861` 大量按 `user_id`+`target_type` 过滤。加纯加性索引即可。
- **职责重叠**：`resource_discussions.resolve_resource:31-41` 与 `forum_resources._context:280-309` 各有一套资源可见性判定，且 `forum_resources → curation → resource_discussions → services` 形成反向依赖环。建议收敛为单一 registry。
- **依赖未锁定**：无 `requirements.txt` / `pyproject.toml` / `package.json`；唯一第三方 Python 依赖 playwright 写在测试文件里且无版本约束；`__pycache__` 同时存在 cp311/cp313 两套，说明多版本混跑。
- **`ops/dev_server.py --env production` 无拦截**：开发机一句命令即加载生产域名与真实生图网关，无 dry-run / 无本机校验。

## P2 建议

- 新增模块（`curation.py`、`forum_resources.py` 等）多数函数无类型注解，与 `services.py` 风格不一致。
- `seed.py:492-519` 的 `force_reset` 删除清单漏了 `curation_*` 与 `media_public_grants`，reset 后留悬空 `topic_id`（有 demo 双重守卫，生产安全）。
- `server.py` 在请求路径内 `import`，路由分发隐式依赖 import 顺序。
- `esc()` 未转义单引号；当前模板均用双引号属性故不构成问题，但建议补一行以防后续误用。
- `.gitignore` 中 `/plugin/public/composer.html` 已无对应文件，属历史残留。
- `docs/v2-acceptance-*.md` 声称的通过数字未随 CI 持续复验，建议标注「本机结果，CI 覆盖面见 checks.yml」。

## 做得好的地方

- **SQL 参数化彻底**：91 处 f-string SQL 无一处拼接用户输入。
- **零裸 `except:`**，55 处均带类型。
- **迁移零 `DROP`**，只增不删，符合 AGENTS.md。
- **部署链路稳健**：`server-deploy.sh` 有 flock、脏工作区拒绝、`--ff-only` + 40 位 SHA 校验、迁移前 `pg_dump` 验证、健康检查失败自动回滚且不降级数据库；`ops/web.ps1 deploy` 绑定已通过 CI 的 commit。
- **`ops/deepseek_task.py` 边界干净**：锁定 127.0.0.1:3065、只读已跟踪文件、拒绝隐藏路径、无 shell/eval/exec。
- **前端转义规范**：`esc()` 与 `safeHtml()` 封装统一，抽样未见未转义插值；`prefers-reduced-motion` 在 4 个 CSS 文件中已适配，符合 AGENTS.md 的动效要求。
- **测试是实打实的**：Python 82 项全绿，Node 16 项全绿，且输出为明确契约描述而非空壳。

## 已澄清的误报

- 某审查路径报告「`unittest discover` 84 errors / 全部失败」——**实测为 `Ran 82 tests / OK`**，系该审查进程自身沙箱下 `.local` 不可写所致，非代码问题。
- 「`studio-app.js` 无结构」——实际有 16 个清晰分节标记，问题是未拆分成模块而非无组织。
- 「文件存在 GBK 乱码」——实测 137 个源文件全部为合法 UTF-8，乱码仅出现在未指定编码的 shell 读取中。
