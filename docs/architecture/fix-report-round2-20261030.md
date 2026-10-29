# 第二轮修复报告（to Claude 复审）

日期：2026-10-30。针对 `docs/architecture/final-review-20261030.md` 的逐条整改。

## 一、致命项（4 条）

### 1. skill 真实链路不通
**问题**：`work_payload` 发的是 `content.prompt` + `assets[].ref`，`_entry_to_work_body` 只认顶层 `prompt`，返回 400 `prompt_required`。

**修复**：`backend/server.py` 重写 `_entry_to_work_body`，解析真实结构：
- `content.prompt` → 作品提示词
- `content.parameters.style_ids` / `layout_ids` → 画风、图型
- `assets[]` 的 `official:<CODE>` 按 `role` 拆分
- `cover_url` + `content.examples[]` → 图片列表
- 保留扁平字段兼容（直接调 `/api/works` 也可）

**证据**：
- 真实 `community_share.work_payload` 端到端：`create_work` 返回 `{id, kind:"work", status:"published"}`，落库 `origin=skill`、`styles=["FA-013"]`、`layout=SC-021`、提示词完整
- 新增测试 `test_entry_accepts_the_real_community_share_payload`（构造真实载荷，验收标题/提示词/画风/图型/首图/附图）

### 2. 网站界面仍走审核
**问题**：`curation-ui.js` 作品提交走 `/api/curation/submissions`，`works` 不写入。

**修复**：
- `curation-ui.js`：作品（单条 kind=work）改调 `/api/works`，成功后跳作品详情页
- `curation.py:submit`：纯作品投稿返回 400 `work_publish_moved`；**混合投稿（画风/图型 + 作品引用）仍放行**，因为那是目录审核，作品只是随附

**证据**：`test_forum_resources.py` 的多资源共用帖测试仍全绿（说明没有误伤），同时纯作品路径被拦截。

### 3. 复刻可伪造
**问题**：发布时按客户端传的 `forkOf` 直接计数，任何人可刷（fork 权重 3）。

**修复**：
- 发布路径 `_record_fork` **只记谱系、不计数**
- 新增 `count_fork_if_new`，仅在 `complete_cloud_generation` 调用，且要求：真实出图（非空）、`engine != 'sample'`、调用者非父作品作者

**证据**：`tests/test_work_forks.py` 8 项，其中：
- `test_publishing_a_fork_records_lineage_but_does_not_count`：发布只写谱系，计数 0
- `test_publishing_without_generating_cannot_inflate_forks`：反复提交 `forkOf`，计数仍 0
- `test_successful_generation_counts_the_fork_once`：真实生成后计数 1，重复完成不重复计
- `test_author_generating_from_own_work_does_not_count`：自复刻不计
- `test_generation_without_images_does_not_count`：没出图不计

### 4. 他人图片静默丢弃
**修复**：`server.py` 两处（字符串与对象分支）改为抛 403 `foreign_media`。

## 二、高优先级项

### 5. 首件作品荣誉升级奖励丢失
**问题**：`before_count` 在作品 INSERT **之后**才计算，发布前状态已被污染。

**修复**：在 INSERT 前快照 `before_count` 与 `before_tier`，作为参数传入 `_reward_direct_work`。

**证据**：`test_05` 恢复精确断言（见第 8 条）。

### 6. 发布校验缺失
**修复**：空标题 → 400 `title_required`；超过 2 个画风 → `too_many_styles`；`price:"abc"` → 400 `invalid_price`（此前是 500）；价格超出 0–100 → `price_out_of_range`。

**证据**：`tests/test_publish_validation.py` 6 项。

### 7. 付费提示词泄露
**修复**：锁定作品的 `prompt` 由「前 34 字 + 提示」改为**空字符串**。

**证据**：`tests/test_review_fixes.py::PaidPromptTests` 3 项（他人/匿名看不到，作者能看）。

### 8. 隐藏作品后主帖仍公开
**修复**：`admin_moderate_work` 在 publish/pause/hide/feature 后同步主帖状态；删除时清理映射表。

**证据**：`tests/test_publish_validation.py::VisibilitySyncTests` 3 项。

### 9. 评论收敛丢隐藏评论
**修复**：`converge_work_comments.plan` 去掉 `status='published'` 过滤，复制全部状态，状态原样保留。

**证据**：`tests/test_review_fixes.py::ConvergeAllStatusesTests`（隐藏评论按 `hidden` 状态复制）。

### 10. starter 账号硬编码密码
**修复**：
- 删除 `STARTER_PASSWORD` 常量，改为每次运行 `secrets.token_urlsafe` 随机生成
- 凭据写入 `.local/starter_credentials.json`（已加入 `.gitignore`），不打印到控制台
- 新增 `ops/label_starter_accounts.py`：把 5 个虚构作者标注为「官方示例·XXX」，bio 说明是官方示例

**证据**：`tests/test_review_fixes.py::StarterCredentialTests` 2 项；默认库与干净库均已执行标注。

## 三、其他

### idx_works_popular 缺失
新增迁移 **044**（不修改已发布的 040）。表达式与 `ranking.work_popular_sql` 文本一致。

**证据**：`test_query_planner_uses_the_index` —— `EXPLAIN QUERY PLAN` 显示 `SEARCH works USING INDEX idx_works_popular (status=?)`。

### DEFAULT_STAMP_BASES
复核：该常量在 B1 中已随 `base_map` 一并删除，`git grep` 零命中。审查报告可能基于旧快照。

## 四、测试断言被改弱（审查报告 §5）

**已恢复并加强**：
- `test_05`：`assertEqual(res_w['reward'], 15)` + `assertEqual(credits, c0+5+10+10)`，重新要求精确金额
- 新增 `tests/test_review_fixes.py`、`tests/test_publish_validation.py`，共 17 项，专门锁住本轮修掉的每个洞

## 五、当前测试基线

| 套件 | 结果 |
|---|---|
| pytest | **135 passed, 11 subtests** |
| unittest discover（CI 入口） | **135 tests, OK** |
| Node `.cjs` | **16/16** |
| skill | **30 passed** |

## 六、真实运行验证

干净库 `.local/clean_v2.db`（10 作品 / 10 话题 / 5 官方示例账号 / 计数全 0），服务 `127.0.0.1:3099`：

- `/`、`/studio/`、`/forum/`、`/admin/`、`/data/catalog.json`、两张画风/图型图 → 全部 200
- 端到端：注册 200 → 发布 200 `published` → 立即出现在 works 与 showcase → 经帖子点赞 → `work.likes == topic.likes`、topic 暴露 `workId`

## 七、仍未做（需创始人拍板或下一期）

1. `asset_comments` 收敛（规格明确推到下一期）
2. 作品「进精选」仍是管理员单人操作
3. 关注/订阅、楼中楼、标签体系（本期不做）
4. **所有改动仍未提交** —— 与之前 74+ 项未提交工作混在一起。建议评审通过后分批提交。
5. 生图接口依赖未连接的浏览器插件，本轮未生成新图。
