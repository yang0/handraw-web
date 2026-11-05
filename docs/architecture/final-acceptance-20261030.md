# 最终验收（2026-10-30）

验收人：Claude。对象：handraw-web `2ca828b`（main），skill 仓库 `E:\handraw-style` `0ea944a`（master），种子库 `.local/seed_v2.db`。
本文所有数字都是本次重新运行得到的，没有沿用之前报告里的数字。验收脚本、截图和测量数据在 `.local/review/acceptance-20261030/`（被 git 忽略）。

## 1. 结论

**未全部达成，不建议按当前状态上线。** 创始人的四项要求里，网站开发、skill 调整、Claude 测试评估三项已达成。「初始化数据和图片」的数量、零互动、文件存在都符合要求，但 10 件示例作品的图片与它们的标题、提示词全部对不上，「官方示例」标注也没出现在作品卡片上。另外，验收中发现一个任何登录用户都能用来无限刷积分的线上按钮（P0-1）。

## 2. 逐项判定

| # | 创始人要求 | 判定 | 我的验证方式 |
|---|---|---|---|
| 1 | 完整的网站开发 | **达成** | 新建干净检出 `E:\projectHome\hw-accept-2ca828b`（porcelain 0）并跑全部测试；在干净 HEAD 和工作区上分别起真实服务（用种子库副本），用 headless Chromium 打开 11 个页面，每个页面测 1280 和 390 两种宽度，收集 pageerror、console error 和所有 ≥400 的响应 |
| 2 | skill 调整 | **达成（代码）/ 未发布** | 读 `conversation_share.py`；跑 skill 测试；用 skill 自己的 `prepare_draft → publish_draft` 对干净 HEAD 服务真实发布一次，只把 `BASE_URL` 改到本地 |
| 3 | 初始化数据和图片 | **部分** | 只读打开种子库逐表检查；10 张图逐个确认文件存在；通过 HTTP 和浏览器加载图片；把 10 张图与标题、提示词拼成对照图逐张人工核对（`seed_sheet.png`） |
| 4 | 让 Claude 做测试评估 | **达成** | 九轮评审报告加本次验收 |

### 2.1 网站开发：逐页结果（干净 HEAD `2ca828b`，种子库副本）

| 页面 | 路径 | 有内容 | JS 错误 | ≥400 |
|---|---|---|---|---|
| 首页 | `/` | 6 件最新作品、用途入口、最新资源、近期讨论 | 0 | 0 |
| 画风库 | `/?view=styles` | 366 个画风，60 张图全部加载 | 0 | 0 |
| 作品广场 | `/?view=works` | 10 件作品 | 0 | 0 |
| 作品详情 | `/?view=work&id=…` | 标题、提示词、画风编号 | 0 | 0 |
| 论坛列表 | `/forum/` | 10 个作品主帖 | 0 | 0 |
| 作品主帖 | `/forum/?view=topic&id=…` | 标题、作者、点赞/收藏/回复 (0)、图、提示词 | 0 | 0 |
| 作品回执 | `/forum/?view=resource&kind=work&id=…` | 标题、图、提示词、共用讨论 | 0 | 0 |
| 共创（投稿 / 分享投稿） | `/forum/?view=curation`、`&tab=share` | 投稿表单完整（已登录） | 0 | 0 |
| 创作台 | `/studio/` | 表单/画布/文章模式、快速开始（已登录） | 0 | 0 |
| 管理后台 | `/admin/` | 数据总览：用户、作品 10、积分池（admin 账号） | 0 | 0 |

工作区服务的结果相同。11 个页面 × 2 种宽度 × 2 份代码，共 44 次加载：pageerror 0，console error 0，≥400 响应 0。`/api/nonexistent` 返回 JSON 404。

**视觉（`2ca828b` 的 CSS 修复）：没有回退，裁切为 0，但留白仍在。** 我测了全部 10 件作品在主帖、回执、详情三个页面的渲染尺寸，然后用 `0562318`（修复前）同样测了一遍：

| 场景（1280 宽，方图） | 修复前 `0562318` | 修复后 `2ca828b` |
|---|---|---|
| 主帖：图片显示尺寸 / 单侧留白 | 320×320 / 232px | 640×640 / 72px |
| 回执、详情：图片显示尺寸 / 单侧留白 | 320×320 / 331px | 640×640 / 171px |
| 被裁切的作品 | 0/10 | 0/10 |
| 390 宽（手机） | 留白 1px | 留白 1px |

修复是改进，不是回退：图完整显示，没有被裁。但提交说明里写的 "there are no empty bands" 不成立，方图在桌面端两侧仍各有 72–171px 的底色。还有一个根本原因 CSS 解决不了：种子图片原图只有 301–512px，桌面端被放大到 2.1–2.5 倍，看起来会糊。
### 2.2 skill 调整

`E:\handraw-style\skills\community-share\scripts\conversation_share.py`：

| 检查项 | 结果 | 位置 |
|---|---|---|
| 目标是 `/api/entries` | 是 | `:27` `WORK_ENDPOINT = "/api/entries"`，`:316-318` |
| 有 `requestId`（幂等） | 是，按草稿固定：`skill-<draft_id>` | `:151` |
| 回执用服务端返回的 url | 是，服务端没给时才回退 | `:418` |
| 回读 `/api/forum/resources/work/<id>` | 是 | `:323`，核验 `:427-447` |

用真实服务（干净 HEAD）发布一次的结果：

- 回执 `verified=true`，`associations_verified=true`
- 同一草稿再次发布：返回同一个 `entry_id`
- 用相同 `requestId` 直接重放 `POST /api/entries`：服务端返回同一个 id，库里同标题作品仍然只有 1 行
- 回执 url 与服务端返回的 url 一致，打开返回 200
- 回读结果：styles `["FA-013"]`，layout `SC-021`；库中 `origin='skill'`

**未发布**：skill 仓库 `master` 比 `origin/master` 多 3 个提交（`cdb46f2`、`fd67a35`、`0ea944a`），还没有推送。

### 2.3 初始化数据与图片

| 检查项 | 结果 |
|---|---|
| 10 作品 / 10 话题 / 5 创作者 | 是。每个作品都有一个指向它的主帖（`forum_topics.work_id`）和一条 `curation_resource_topics` 映射 |
| 互动数全 0 | 是。works 的 cheers/likes/favorites/forks/tips/views 和 topics 的 views/likes 全部为 0，`stamp_counts_json='{}'`，没有回复和评论 |
| 图片文件真实存在 | 10/10。路径 `/images/individual/<组>/<编号>.webp` |
| HTTP 访问图片 | 抽查 FE-012、FA-013、FF-006、FB-028，全部 200 `image/webp`，字节数与文件一致；浏览器里 10 张主图全部加载成功 |
| 作者标注「官方示例」 | **只在 `users.display_name` 和 bio 中有**（`官方示例·林南`）。作品卡片、首页、论坛列表、主帖署名显示的是 `works.author_name` / `forum_topics.author_name`，值是「林南」，没有标注 |
| 测试残留 | 库中只有 5 个账号，没有 `e2e_user` 等测试账号；对全部表的文本列搜索 e2e/test/probe/验收 等关键词，命中 0 |
| 图片数量 | `handraw-web/images/` 676 个文件、47.1 MB，与报告一致。它与 `E:\handraw-style\images`（992 个）逐字节对比：是后者的子集，没有内容不同的文件。注意服务端实际从 `HANDRAW_STYLE_IMAGES_DIR` 读图（默认 `E:\handraw-style\images`，`backend/config.py:11`），不读 `handraw-web/images/` |

**图文不符（P0-2）**：我把 10 张图和它们的标题、提示词逐张对照，没有一件对得上：

| 作品标题 | 提示词写的内容 | 图片实际内容 |
|---|---|---|
| 梅雨天里的一碗面 | 雨中街角面馆、一碗汤面 | 旗袍女子与仙鹤，图上印着「李旻 传统文化 现代编辑风」 |
| 通勤路上的三种表情 | 地铁车厢里三个人物 | 一个抱冲浪板的人，图上印着「Jean Jullien」 |
| 旧书店的下午四点 | 旧书店书架、午后光线 | 大胡子男人与一只鹅在书桌前 |
| 关于失眠的一页绘本 | 深夜房间、盯着天花板 | 河边石头上的小熊 |
| 桂花乌龙的海报尝试 | 桂花枝叶与茶汤特写 | 坐在滑板上的少年，印着「Free-Line Urban Youth Comic」 |
| 中秋礼盒的包装草图 | 月饼礼盒俯拍 | 海边小镇与猫，印着「Oamul Lu 旅行与季节」 |
| 给朋友做的生日插画 | 女孩抱蛋糕坐在窗边 | 趴着写手帐的女孩，印着「Notebook Lifestyle Doodle」 |
| 雨后玻璃窗的特写 | 雨滴玻璃、霓虹虚化 | 海边白墙前戴草帽的女子 |
| 卡通形象的第一版设定 | 圆脸角色正面站姿、白底 | 两个老年卡通人物，画风与某部经典动画电影非常接近 |
| 猫在键盘上睡着了 | 橘猫趴在键盘上 | 3D 黏土风的男人拿着咖啡站在街头 |

原因：`ops/seed_starter_library.py:150-154` 用画风编号直接取画风库的封面图（`/images/individual/<组>/<编号>.webp`），标题和提示词是 `:42-139` 另外写的。这 10 张图是画风库里该画风的参考封面，不是用这些提示词生成的作品。

这件事的影响：
- 页面上把它们展示成「官方示例·林南」等人的作品，附带「一键复刻」。用户复制提示词去生成，得到的结果和看到的图毫无关系。
- 多张图上印着其他作者的署名（李旻、Jean Jullien、Oamul Lu），却挂在虚构的创作者名下。
- 画风库「有实测作品 10」、每张画风卡上的「1 作品」，计数的对象是这件画风自己的封面图，属于循环计数。
- 脚本文档字符串（`:1-11`）写的是「carries a real prompt ... so the counters start at zero and stay honest」。计数确实是 0，但「真实作品」这一点不成立，和 `docs/product-direction.md` 不伪造内容的要求冲突。

## 3. 实际测试数字

| 环境 | pytest | Node `.cjs` |
|---|---|---|
| 干净检出 HEAD `2ca828b`（porcelain 0） | **230 passed, 3 skipped**（3 项都是 `test_seed_starter_library.py`，原因 "style art not installed in this checkout"） | **12/12** |
| 工作区（含创始人未提交的改动） | **237 passed** | **17/17** |
| skill `E:\handraw-style` `0ea944a`（porcelain 0） | **30 passed** | — |
| 浏览器 | 44 次页面加载：JS 错误 0，≥400 响应 0 | — |
| skill 真实发布 | `verified=True`，`associations_verified=True`，重复发布 / 重放都返回同一 id | — |
| 图片渲染测量 | 10 作品 × 3 页面 × 2 宽度 = 60 次，裁切 0 次；1280 宽下方图单侧留白 72px（主帖）/ 171px（回执、详情） | — |

验收过程中原始 `.local/seed_v2.db` 只以只读方式打开；结束时 sha256 `da81bdf6…` 与开始时一致。
## 4. 仍然存在的问题（按严重度）

行号按 `2ca828b` 计。

### P0：上线阻断

**P0-1 任何登录用户都能无限刷积分，并造出用公开密码登录的账号。**
- `demo/assets/shared.js:2634` 在分享面板里渲染「🧪 模拟好友注册 (+15✦)」按钮，没有 demo 开关。作品主帖点「分享帖子链接」就会出现，我用普通登录账号在浏览器里确认按钮可见（`sim_invite.png`）。
- `demo/assets/shared.js:2717-2725` 点击后调用真实的 `POST /api/auth/register`，用户名随机，密码固定为 `handraw123`，并带上当前用户的邀请码。
- `backend/services.py:368`、`:412` 给邀请人入账 `invite_inviter` +15。
- `backend/server.py:1451` 注册限流的键是 `IP|用户名`，用户名每次都不同，所以限流不起作用。
- 复现（干净 HEAD）：同一 IP 连续注册 18 次，全部 200、0 次被拒；邀请人余额从 20 涨到 290；造出的 `friend_*` 账号用 `handraw123` 可以登录（200）。积分可以用来解锁付费配方和云端生图（单张 2 积分），等于直接消耗真钱。

**P0-2 10 件种子作品的图片与标题、提示词全部不符，且图上带有他人署名。** 详见 2.3。`ops/seed_starter_library.py:150-154`、`:42-139`。

### P1：上线前应修

**P1-1 「官方示例」只出现在个人资料里，作品卡片和帖子署名上没有。** `ops/label_starter_accounts.py:56` 只更新 `users.display_name` 和 `bio`，不改 `works.author_name` 和 `forum_topics.author_name`。首页、作品广场、论坛列表、主帖署名显示的都是「林南」等名字（`boot.works[].authorName` 实测为 林南/陈默/柚子/何岚/汤圆），只有主帖右侧作者卡显示「@官方示例·林南」。普通访客会把这些作品当成社区成员的作品。

**P1-2 种子库带有可用的登录凭据和发放出去的积分。**
- `sessions` 表有 5 条会话，`expires_at=1795923369`（约 2026-11-29），来自 `register_user`（`ops/seed_starter_library.py:206`）。每个账号还有 api_key 和密码哈希，明文密码在 `.local/starter_credentials*.json`（已被 git 忽略，没有提交）。
- 5 个钱包各 70 积分：欢迎礼 20、2 次发布各 15（5 + 先锋奖 10）、2 次荣誉晋升各 10。每个账号都晋升为「🌟 先锋开荒者」。种子作品占掉了这 10 个画风的先锋名额（阈值 3），第一个真实用户在这些画风上拿到的先锋奖会少一份。

**P1-3 skill 发布顺序。** `conversation_share.py:23` 的 `BASE_URL = "https://handraw-style.com"` 是写死的。如果 skill 的 3 个提交在 handraw-web 上线之前推送，用户点「分享」会打到旧站点，那里没有 `/api/entries`。

### P2：不阻断上线

- **P2-1 桌面端方图仍有留白，`2ca828b` 的提交说明与实际不符**（见 2.1）。`demo/assets/forum-work-post.css:38-46` 用 `width:100%` + `max-height:640px` + `contain`。如果要完全去掉留白，可以让舞台按图片宽度收缩（`width:auto; max-width:100%`），或者为种子作品换更高分辨率的图。这条 CSS 修复没有测试覆盖，现有浏览器测试只检查内容和错误，不检查布局。
- **P2-2 skill 文档字段名与代码不一致。** `references/conversation-sharing.md:9-10` 和 `SKILL.md:12` 写的是 `styleIds`、`layoutId`、`entry.images`、`originalRequest`；代码（`:141-152`）发送的是 `cover_url`、`content.parameters.style_ids`、`assets`。服务端两种写法都接受（`backend/server.py:728`、`:756-761`），所以不影响功能，但读文档的人会被误导。`SKILL.md:3` 的描述仍写「打通 handraw-style.com (Discourse)」。
- **P2-3 部署要配置图片目录。** 服务端只从 `HANDRAW_STYLE_IMAGES_DIR` 读图（`backend/config.py:11`，默认是 Windows 路径 `E:\handraw-style\images`）。生产环境不设置这个变量，所有作品图都会 404。`handraw-web/images/` 目录服务端不会用到。
- **P2-4 上一份实现报告里的遗留风险仍然有效**：3 个账号可以暂停任何内容（`final-implementation-20261030.md` §6 第 3 条，P0-1 让凑出 3 个账号几乎没有成本）；没有统一的防刷方案；驳回一条举报会关闭同一目标的全部举报；浏览器测试缺 Playwright 时会静默跳过。

### 遗留检查（第 4 项）

- **未提交的产品代码**：`git status` 共 41 项（8 个 M、33 个 ??），与「创始人之前的 41 项」一致。其中 `backend/services.py` 只有 CRLF 行尾差异，`git diff --ignore-cr-at-eol` 为空。实际有内容改动的是创始人的 7 个文件（`AGENTS.md`、`README.md`、`runtime_policy.py`、`seed.py`、`account-tools.js`、`studio-app.js`、`product-direction.md`）。开发者没有遗留未提交的改动。
- **测试残留账号**：种子库里没有。
- **敏感文件**：两个仓库的已跟踪文件里都没有 `.env`、`*service.json`、`starter_credentials*`、`*.db`、`images/`；历史提交里只加入过 `.env.example`。`ai-service.json`、`image-service.json`、`.local/` 都被 `.gitignore` 覆盖。已跟踪代码里有两处固定凭据：`shared.js:2723` 的 `handraw123`（即 P0-1）；`backend/seed.py:559` 的 `hwk_yang0_local_dev_key`，它只在 `HANDRAW_DEMO_MODE=1` 时写入（`seed.py:482-484`），生产环境不会生效。
- **验收时新增的东西**：worktree `E:\projectHome\hw-accept-2ca828b` 和临时目录 `E:\projectHome\accept-tmp\`（含种子库副本和验收账号），都在仓库之外，没有修改任何已跟踪文件。复核完可以用 `git worktree remove ../hw-accept-2ca828b` 删除 worktree。

## 5. 上线前必须做的事

1. **关掉刷积分的路径**：删除或用 demo 开关隐藏 `shared.js:2634` 的按钮；注册限流改为只按 IP（或 IP + 设备）计数；邀请奖励改为被邀请人完成一次真实行为（如首次发布）后才发放。
2. **重做 10 件种子作品**：用每条提示词实际生成图片；如果继续用画风封面，就把标题和提示词改成如实描述图片，并标成「画风参考示例」。带他人署名的图、与经典动画画面相似的图，确认授权后再用，否则替换。之后重新生成 `seed_v2.db`。
3. **把「官方示例」标在作品上**：写入 `works.author_name` / `forum_topics.author_name`，或者在卡片和署名处显示官方标记。
4. **交付种子库前清理凭据**：清空 `sessions`，轮换 5 个账号的 api_key 和密码（已有 `ops/rotate_starter_credentials.py`）。先锋奖和荣誉是否保留，见第 6 节。
5. **部署顺序**：先上线 handraw-web，并设置 `HANDRAW_STYLE_IMAGES_DIR`，确认作品图 200；再推送 skill 的 3 个提交。
6. CI 安装 Playwright 和 Chromium，否则浏览器测试会静默跳过。

## 6. 需要创始人确认的产品规则

1. **M9 管理员优先**（沿用上一份报告）：高级别的隐藏只有同级或更高级别能撤销，级别顺序 admin > operator > moderator。
2. **V9**（沿用上一份报告）：运营或管理员确认作品主帖的举报时，作品也一起隐藏。
3. **种子作品的定位**：可以用画风库封面作为「官方示例」作品吗？如果可以，它们要不要计入画风的「有实测作品」统计？
4. **种子账号的奖励**：官方示例账号要不要拿欢迎礼、发布奖、先锋奖和荣誉晋升？要不要占用先锋名额？
5. **邀请奖励规则**：注册免费、不需要验证的情况下，邀请奖励在什么条件下发放？
