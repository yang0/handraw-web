# 实施完成报告（to Claude 评审）

日期：2026-10-30。评审对象：`E:\projectHome\handraw-web`（网站）与 `E:\handraw-style`（skill 分享模块）。
依据：`docs/architecture/design-v1-20261029.md`（761 行规格）+ `docs/architecture/decisions-20261029.md`（创始人三条拍板）。

## 一、已完成的批次

### B0 迁移执行器原子化
- 证据：注入半途失败迁移后，`probe_ok` 表不存在、版本号未写入。

### B1 数据真实性 + GET 不写库
- `services.py:742` `or 16` → `or 0`
- 发帖初始 `views/likes` 由 `1,1` 改为 `0,0`
- 送鼓励不再 `likes+1`（此前导致计数与记录永久不一致）
- 印章基数 `6/8/4/5/4` → `0`
- `asset_social_seeds` 仅在演示模式读取（两处）
- `resource_discussions.apply_boot` 移除懒建帖：GET 不再写库
- 证据：`/api/boot` 调用前后 forum_topics / forum_replies / curation_resource_topics / works 四表行数不变。

### B2 迁移 040–043
- 新建 `backend/work_schema.py`：
  - 040 `works.origin / request_id / forked_from_id` + 3 个索引
  - 041 四个按目标计数的索引
  - 042 `work_forks` 表 + `studio_generations.fork_work_id`
  - 043 `forum_replies.legacy_source` + 唯一索引
- 证据：四项全部应用、重跑幂等（第二次 applied 为空）。

### B3 作品即时发布 + 晒作品版块
- 新增 `curation.publish_work_direct`：作品行、讨论帖、映射表在同一事务内写入，不经审核
- 新作品 id 用 UUIDv4；`requestId` 幂等
- 奖励与荣誉升级照常发放（复用同一套经济规则）
- 9 图上限、缺图/缺提示词明确报错（此前 10 图会被静默截断）
- 新增 `showcase`（🎨 晒作品）版块
- 证据：`status=published`、`reward=15`、映射 1:1、`category=showcase`、重复请求同 workId、10 图返回 `too_many_images`

### B4 排序统一
- 新建 `backend/ranking.py`：每类一个公式（作品 likes+cheers+2fav+3forks；帖子 replies+likes+2fav；资源 usageCount）
- 全站收敛为 `newest` / `popular` / `active`；旧参数 `favorites|cheers|hot|recommended` 映射到 `popular`
- 移除：`views` 参与排序、荣誉曝光系数、新发加分、`getAssetExposureScore`
- 前端新增 `S.popularScore`；`main-app` / `forum-app` / `works-browser` / `shared` 同步
- 证据：`tests/test_ranking.py` 9 项，含 SQL 表达式与 Python helper 结果完全一致的对照测试

### B5 复刻谱系
- `work_forks` 为事实，`works.forks` 从该表重算
- 同一用户重复复刻不重复计数；父作品未发布/不存在时不建悬空边
- `prepare_cloud_generation` 记录 `fork_work_id`
- 证据：`tests/test_work_forks.py` 4 项

### B3+ 计数归一
- 对作品主帖点赞/收藏，服务端重定向到作品（`toggle_user_like` / `toggle_user_collection`）
- boot 中作品主帖显示作品计数并暴露 `workId`
- 证据：`tests/test_work_counts.py` 5 项

### B6 skill 契约
- 新后端新增 `POST /api/entries`：收 `{"entry": {...}}`，返回 `{"id","kind":"work","topicId","url","status"}`
- `_entry_to_work_body` 做一次词汇映射（`styleIds`/`layoutId`/`originalRequest` → 作品字段），并记 `origin='skill'`
- skill 侧 `conversation_share.py`：`WORK_ENDPOINT` 改 `/api/entries`；`current_user`/`check_work_access` 改 `/api/boot`；`upload` 改 `POST /api/uploads`（data URL）
- 鉴权天然兼容：新后端已支持 `Api-Key` 头（`services.py:286-298`）
- 文档：`SKILL.md` 与 `references/conversation-sharing.md` 的分享段落同步（未动提示词生成部分）
- 证据：`tests/test_work_publish_contract.py` 6 项；skill 自有测试 30 passed；端到端探针真实跑通 `origin=skill` 落库

### B7 旧评论收敛 + 对账脚本
- `ops/converge_work_comments.py`：`work_comments` → `forum_replies`，用 `legacy_source` 幂等；先 `status='migrating'` 再更新，避免给历史评论补发通知
- `ops/reconcile_social_counters.py`：从 `interactions`/`collections`/`work_forks` 重算缓存计数
- 证据：`tests/test_ops_convergence.py` 4 项

## 二、初始数据

- **图片**：从 `E:\handraw-style\images` 复制 676 个真实图片文件（47MB）到本站 `images/`，覆盖 403 张画风图 + 173 张图型图 + 色卡等。已验证 `/images/individual/FA/FA-013.webp` 等返回 200。移除了零引用的 `individual_backup`（旧 001-200 编号备份）。
- **作品**：`ops/seed_starter_library.py` 创建 5 位创作者、10 件作品，全部指向真实画风图、带真实提示词，走正常发布路径。计数从 0 开始，不伪造互动。
- 证据：`tests/test_seed_starter_library.py` 3 项；boot 返回 10 works / 37 topics，10 件全部在 showcase 版，全部暴露 workId。

## 三、当前测试基线

- 网站：**Python 113 passed, 11 subtests passed**
- 前端：**Node 16/16 exit=0**
- skill：**30 passed**

## 四、真实运行验证

服务在 `127.0.0.1:3099` 启动后实测：

| 路径 | 结果 |
|---|---|
| `/` | 200, 8924 bytes |
| `/studio/` | 200 |
| `/forum/` | 200 |
| `/admin/` | 200 |
| `/api/boot` | 200, 71KB |
| `/data/catalog.json` | 200, 499KB |
| `/images/individual/FA/FA-013.webp` | 200, image/webp |

## 五、已知未完成 / 需评审判断

1. `works.views` / `forum_topics.views` 已冻结（不写、不排序），但前端仍在展示该字段。
2. 作品「进精选」仍是管理员单人操作，双人审核精选按规格推迟到下一期。
3. `asset_comments` 收敛未做（规格明确推到下一期）。
4. 关注/订阅、楼中楼、标签体系按规格本期不做。
5. 生图接口 `127.0.0.1:8000` 依赖一个未连接的浏览器插件（b1 CDP 9223 未开），本次未能生成新图，初始图片改用 skill 现有真实图库。
6. `ops/seed_cold_start.py` 的冷启动虚构账号未导入，也未删除。
