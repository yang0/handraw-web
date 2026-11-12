# 本地 2.0 全站验收报告

验收日期：2026-10-27。对象：本地四站服务（主站 3080 / 创作台 3081 / 论坛 3082 / 管理后台 3083），演示模式 + 真实生图网关。

本轮验收以「跑起来」为准：启动真实服务、调用真实生图网关、用真实浏览器渲染四个站点，而不是只读代码或只跑单测。

## 1. 结论

| 验收层 | 项数 | 通过 | 失败 |
| --- | --- | --- | --- |
| 隔离单元/集成测试（`tests/test_v2_*.py`） | 55 | 55 | 0 |
| HTTP 全流程验收（`tests/e2e_full_site_flow.py`） | 66 | 66 | 0 |
| 浏览器验收（`tests/browser_acceptance.py`） | 25 | 25 | 0 |

真实生图网关 `https://chatgpt2api.handraw-style.com` 已接通，模型 `gpt-image-2` 可正常出图，创作台「点运行 → 出图 → 显示 → 下载/晒图」链路完整。

## 2. 本轮修复

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| — | `admin_services.py` f-string 内含反斜杠，Python 3.11 下整个 `backend` 包无法导入 | 把表达式移到 f-string 外 |
| — | 板块版主控制台 `NameError: moderator_user_filter`，接口必 500 | 在 `admin_get_moderator_console` 内补定义 |
| — | 拒绝写请求时未读 body，内核发 RST，客户端拿到连接重置而非 403 | 新增 `_drain_request_body()`，错误响应前读完 body |
| R08 | 前端用 `createdAt` 文本估算新发，与后端 `published_at_ms` 不一致，18 天前内容仍在新发区 | `isFreshRelease` 优先绝对时间戳并回退服务端标记；`getRecencyMinutes` 同步；官方覆盖不再无条件覆盖 `publishedAtMs` |
| R10 | 手机首屏被角色切换工具条整屏占据，主目录沉到首屏之外 | 720px 以下工具条折叠为单行横向滚动，隐藏说明行 |

R07（演示数据混入）在本轮核对中未复现：后端 `_seed_filter` 在非演示模式下按 ID 排除种子数据，社区资源与作品配图均能对上语义。

## 3. 已确认收口的既有风险项

以下为 `功能全景树与缺口清单` 中标注为 P0/P1、本轮复核确认代码已修复的项：

| 编号 | 当前状态 |
| --- | --- |
| R01 | `sandbox-switch` / `dev/reset` 均经 `_require_demo_mode()`；默认只监听回环 |
| R02 | `recharge_enabled()` 要求演示模式且显式开关，否则 503 `payment_disabled` |
| R04 | 历史删除按 `user_id` 校验，越权 403 |
| R06 | 任务查询限定当前用户行，访客 401、他人任务 404 |
| R09 | CORS 改为白名单，实测恶意来源 403 |
| R11 | boot 失败抛 `bootError`，仅 `?demo_mode=1` 才用静态 fixture |
| R12 | `/uploads/`、`/generated/` 校验所有者或已发布授权，访客 404 |
| R13 | `GenerationReconciler` 已随服务启动，按网关权威结果对账，不重复提交、不误退款 |

## 4. 本地运行方式

```bash
# 演示模式（可登录演示账号、可验收全部治理功能）
HANDRAW_DEMO_MODE=1 \
HANDRAW_UPLOADS_DIR=.local/uploads \
HANDRAW_GENERATED_DIR=.local/generated \
python -m backend.server --port 3080

# 验收
python -m unittest discover -s tests        # 55 项
python tests/e2e_full_site_flow.py          # 66 项 HTTP 全流程
python tests/browser_acceptance.py          # 25 项浏览器渲染
```

真实生图需要仓库根目录存在 `image-service.json`（已被 `.gitignore` 排除）：

```json
{ "url": "https://chatgpt2api.handraw-style.com/v1", "key": "<your-key>" }
```

服务启动时会把 `/v1` 后缀去掉，改为调用网关的 `/api/image-tasks` 系列接口。

## 5. 仍需人工确认的产品规则

以下属于产品决策，不是实现缺陷，本轮未擅自改动：

- **D01 收费规则**：现金充值入口保留但接口返回 503。是否接入真实支付、免费额度与积分扣费规则需要产品确认。
- **D02 旧站迁移**：Discourse 用户导入工具已就绪，但帖子、附件、积分与已解锁权益的迁移方案未定。
- **D03 收费内容**：编辑器和钱包已支持收费帖，但「哪些经验可收费」的规则未定。

演示模式下 `/api/dev/reset`、`/api/auth/sandbox-switch`、角色秒切工具条均可用，这是刻意的验收便利；生产模式（不设 `HANDRAW_DEMO_MODE`）下全部关闭。

## 6. 验收证据

截图位于 `.local/browser-acceptance/`（该目录已被 `.gitignore` 排除）：

- `01-main-home.png`、`02-main-*.png`：主站首页与各栏目
- `04-studio.png`、`10-studio-after-run.png`、`11-studio-result.png`：创作台生成前后
- `05-forum.png`、`06-forum-compose.png`：论坛列表与发帖页
- `07-admin.png`：管理后台
- `08-mobile-home.png`、`12-mobile-compact.png`：390px 移动端
