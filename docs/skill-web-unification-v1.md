# Handraw Skill × 网站一体化产品与架构设计 v1.0（历史基线）

> **现行 V3 决策（2026-11-07）：** 生图任务、公开作品与多图展现请以 [Handraw V3 架构](generation-works-v3.md) 和 [Issue #84](https://github.com/yang0/handraw-web/issues/84) 为准。一个逻辑任务最多产生一件作品，广场和个人主页只展示封面，详情包含该任务全部成功生成的图片。网站生成成功或 Skill 用户主动上传后自动公开，不再二次发布。**本文下方关于“生成历史默认私有”“主动发布后才有作品”“每图独立作品”的旧版描述全部被 V3 覆盖，勿作为新开发依据。**个人图库、参考素材、自建画风/图型仍独立保护。

> 状态：**已批准的开发规划基线（设计决策）**；不是已实现声明。  
> 日期：2026-11-07  
> 责任边界：网站后端为账号、云端资产、授权、作品和互动的事实来源；Skill 为本地创作和离线缓存客户端。  
> 变更策略：任何改变隐私默认值、资产归属、历史作品迁移、接口契约的实现须先修订本文，再发起代码 PR。

> **2026-11-07 产品决策更新，覆盖下文旧版 D02/D05 中有关生成历史私有、二次发布的描述：**网站新生成的成功图片直接进入公开作品库；Skill 用户主动运行 `history upload` 提交的成功图片即视为公开提交，并自动进入同一公开作品库。页面不再提供「发布到作品广场」的第二道按钮/接口。仅本地记录、传输失败、未上传的文件不公开；**已有标记为私有的历史记录不做追溯公开**。画风、图型与个人图库继续私有。必须使用作品作者身份、幂等作品映射和媒体公开授权；Skill 上传端明确告知会公开图片和原始创作指令。此条与下文旧文案冲突时，以本条为准。

## 0. 双仓库地址、分支及协作职责（必须保留）

| 仓库 | GitHub 地址 | 默认分支 | 本轮职责 |
| --- | --- | --- | --- |
| **handraw-style**（公开） | **https://github.com/yang0/handraw-style** | master | Skill 设备绑定交互、本地图库、个人画风/图型、收藏离线缓存、生成历史上报、分享发布客户端与画廊 UI |
| **handraw-web**（私有） | **https://github.com/yang0/handraw-web** | main | 统一身份与授权、云端资产与资源模型、同步 API、生成历史与作品发布、互动服务、权限与补偿、数据迁移 |

**Skill 专用开发分支**：https://github.com/yang0/handraw-style/tree/feature/skill-web-unification-v1-20261107 。任何 Skill 侧功能先在该分支开发与测试，经过 PR 审核再合并 master，不直接覆盖官方预置编号库、用户私有目录或已发布资源。

**本文为双仓库共用的主架构基线**（存储位置：https://github.com/yang0/handraw-web/blob/main/docs/skill-web-unification-v1.md ）。Skill 仓库对应协作说明：https://github.com/yang0/handraw-style/blob/feature/skill-web-unification-v1-20261107/docs/skill-web-unification-v1.md 。公开仓库不能保存用户密钥、生产接口凭据、私有库数据或内部部署信息。

## 1. 产品目标与边界

定位：**一个 Handraw 账号 + 一个个人创作空间 + Skill/网页两种创作入口 + 一个资源与作品生态**。

用户需要闭环：在 Skill 绑定网站账号 → 创建图库/画风/图型并私有同步 → 从网站获取已授权完整收藏 → 在任意客户端创作 → 生成历史私有留存 → 用户主动发布作品 → 跨端查看点赞、收藏、评论和通知。

七类业务需求：
1. Skill 使用网站统一账号身份及可撤销的客户端授权。
2. Skill 自建角色、道具、场景、参考图库支持服务端私有备份和双向同步。
3. Skill 自建画风与图型可存为个人资源并同步到网站；独立决定是否公开。
4. 网站已获得完整访问权的画风/图型可以进入 Skill 画廊；未解锁资源不能下载完整定义。
5. Skill 生成图片可保存在用户私有云端，用户确认后发布到网站作品广场。
6. Skill 复用网站统一的点赞、收藏、评论、通知和作品/资源查看能力。
7. 规范生成历史、图片资产、发布草稿、公开作品之间的关系，解决历史存在但作品空白的语义及同步故障问题。

本期**不做**：微服务拆分、自动公开私人内容、收益分成、新支付体系、大规模实时推送、重写整套站点权限或收藏业务。

## 2. 不可违反的产品决策（ADR 基线）

- **D01 统一用户**：站点 user_id 是资源、收藏、历史、作品与互动的权威所有者；Skill 本地 ID 仅用于离线标识与幂等。
- **D02 私有优先**：生成历史、素材、个人画风/图型默认私有。同步到云端≠发布到社区；不得自动公开。
- **D03 权限分离**：收藏（bookmark）、完整访问权（entitlement）、下载到 Skill（local sync）是三件不同的事。已收藏但未授权时只能展示可公开的摘要。
- **D04 两种结构资源**：图片型素材（角色/道具/场景/参考图）与结构化画风/图型分离建模。官方编号库只读，不与用户自建资源共享可冲突主键。
- **D05 历史≠作品**：生成任务记录创作事实；作品是用户主动选择媒体、编辑公开文案并发布的实体。生成成功不等于发布。
- **D06 只有一个互动事实来源**：Skill 使用网站的点赞、收藏、评论等既有领域业务，不建第二套数据表。
- **D07 离线优先但云端仲裁**：Skill 本地可离线创作；联网后由服务端决定版本、授权、发布状态和可访问范围。
- **D08 尊重来源及许可**：自建、官方、已购买、收藏、派生资源均保留来源、作者、许可证与版本。复制到个人库不自动转移版权。
- **D09 可恢复与可观测**：同步/发布操作携带幂等键、版本及请求 ID；失败可以重试、对账并告警，不得仅静默记录日志。

## 3. 现有实现判断（2026-11-07 代码盘点，不代表生产环境验收）

| 能力 | 当前代码位置 | 判断 / 待验证 |
| --- | --- | --- |
| Device Authorization | handraw-web/backend/device_auth.py、device_auth_routes.py | 已有设备码、网页批准、令牌、撤销、publish/library scope，优先复用 |
| 图片素材同步 | handraw-web/backend/user_library.py | 已有 UUID、SHA256、revision、409 冲突、change_seq 增量游标、软删除及恢复；扩展而非重造 |
| Skill 本地图库 | handraw-style/skills/custom-asset-manager/SKILL.md、custom_library_manager.py | 本地 library.json + WebP + 离线画廊，需要接入云端 |
| Skill 本地个人资源 | handraw-web/skill-addon/scripts/personal_library.py、handraw-style/gallery/personal-library.js | 本地画风/图型与社区收藏已有雏形，需统一数据契约 |
| Skill 作品分享 | handraw-style/skills/community-share/scripts/conversation_share.py | 已有草稿、上传、/api/entries 与防重复机制；需真实鉴权、来源检查和线上验收 |
| 作品与生成关联 | handraw-web/backend/generation_works.py、works_feed.py | 现有 studio_generations→generation_works→works 自动投影；与“主动发布”产品原则冲突 |
| 发布令牌 | handraw-web/backend/server.py | 当前代码白名单已包含 publish scope 的 POST /api/entries 和 /api/works；旧文档有过时相反描述，以当下代码+集成测试为准 |

**已知风险**：成功生成后向 works 投影的异常可能只记录 warning；可能出现“生图历史存在，但公开作品列表为空”。不应未经生产数据核查即断言所有空白均由该原因导致；还需核对公开状态、过滤条件、用户身份及部署版本。生成历史私人化迁移不得意外公开或隐藏已有合法公开作品。

## 4. 目标信息架构

### 4.1 用户可理解的六个业务区域

- **我的图库**：角色 / 道具 / 场景 / 参考图，私有素材。
- **我的资源**：自建画风 / 自建图型，私有定义、版本及可选公开发布。
- **我的收藏**：收藏关系、完整访问资格、Skill 本地缓存状态明确区分。
- **生成历史**：来自网页或 Skill 的每次生成任务及其结果，默认仅本人可见。
- **我的作品**：发布草稿、已发布、隐藏/下架的内容，公开个人主页仅显示可见作品。
- **互动与通知**：作品/资源点赞、评论、收藏、回复和消息，网站统一记录。

Skill 与网页尽量使用相同命名。Skill 画廊主入口建议：官方画风/图型｜我的画风/图型｜我的收藏｜我的图库。

### 4.2 数据对象

| 对象 | 建议实体/迁移策略 | 权威 |
| --- | --- | --- |
| 账号和设备 | users / device grants / scoped access tokens（复用） | web |
| 个人图片资产 | user_uploads（逐步抽象为 media_assets；保留旧 API 和 UID） | web |
| 个人结构化资源 | personal_resources + personal_resource_versions（新增） | web |
| 收藏关系 | 复用现有 collections，提供规范化汇总读取 | web |
| 完整获取资格 | 复用授权/解锁体系；独立于是否收藏 | web |
| 生成运行 | 复用 studio_generations，逐步纳入 Skill 来源与外部任务标识 | web |
| 媒体引用 | media_assets 或渐进过渡的 media 引用表；关联 owner/sha256/storage_key | web |
| 作品 | works（保留现有 ID/链接） | web |
| 作品图片 | work_media（建议新增顺序、封面、媒体 ID 关联，渐进兼容 images_json） | web |
| 生成与媒体来源 | generation_media 或兼容映射，不用生成成功直接创建作品 | web |
| 作品讨论 | 复用既有作品与论坛讨论的映射，避免双写 | web |

画风定义仅包含视觉特征（线条、媒介、质感、色彩、光影等），不从参考图偷带人物、服装、场景或情节；图型定义布局约束、区域关系与排版规则。对个人资源校验此领域约束。

统一 ID 为 UUID；官方展示编号、本地旧编号、来源编号都是别名，严禁作为跨端主键。资源应有 kind、owner_id、title、definition、examples、version/revision、visibility、license、origin、created_at、updated_at、deleted_at。结构化定义按 schemaVersion 兼容演进。

## 5. 身份与权限

**首次绑定用户旅程**：
1. Skill 申请设备码和用户验证码，跳转网站授权页。
2. 用户在网站以现有登录状态批准所请求的 scopes。
3. Skill 轮询并兑换设备令牌，调用 GET /api/auth/me 确认 user_id 对应账号。
4. Skill 显示已连接用户名、允许的能力及最近同步状态；网站可查看/撤销已授权设备。
5. 令牌过期、撤销或 scope 不足时重新授权；不能用网页登录 Cookie 复制到 Skill 充当长期令牌。

保留 publish / library 已有 scope；未来若互动能力单独授权，再评估新增 interaction scope。不要为方便而放宽为全站写权限。客户端凭据优先保存在操作系统凭据管理服务；不得放进 Git、明文共享目录、URL 参数或普通日志。校验服务端 user_id、资源归属、权限及许可；服务端发放的临时媒体 URL 有效期短且可撤销。

## 6. 双向同步方案

### 6.1 图片图库（Skill ↔ 网站）

- 延用 GET /api/library/assets?since=cursor、PUT /api/library/assets/{uid}、DELETE 与 restore。
- 支持分类 characters/props/scenes/other，并将“参考图”作为明确的客户端视图或新增受控类别，不破坏旧数据。
- 本地保持稳定 UUID、图片 SHA256、本地文件路径映射、revision、同步游标及 tombstone。
- 云端持久保存图片原文件（逐步使用对象存储）和关系元数据；服务端不保存用户机器绝对路径。
- 默认仅本人可见；网站本人与授权 Skill 的访问都经过鉴权。禁止把私有图片永久公共 URL 放到客户端缓存。
- 复用既有 optimistic locking：baseRevision 不匹配返回 409；客户端区分元数据冲突、图片替换冲突与远端删除；图片冲突保留副本。
- 删除采用软删除和有限恢复期；被已发布作品引用的原媒体不能被无条件物理清除。默认不因单端删除而无确认抹掉另一端唯一的离线数据。
- 服务端配额、格式校验、内容哈希、分页及上传重试必须有显式状态。

### 6.2 画风与图型（独立资源同步）

- 新增个人结构化资源 API，不把 JSON 画风/图型嵌入图片资产表。
- create/update/upsert 通过 UUID + baseRevision；GET 支持增量同步、分页和 tombstone。
- 网站与 Skill 在同一个 user_id 下创建/编辑同一份资源；本地只作副本，不成为第二权威。
- 发布社区资源为独立操作；个人资源同步成功时仍 private。
- 保存来源作者、授权许可、fork lineage 和生成时用到的资源版本，避免改版导致历史作品的配方歧义。
- “完整画风/图型”仅包含合法授权的完整定义；服务端每次请求重新判断 entitlement。

### 6.3 收藏与获取

收藏、已解锁、已同步独立显示。已收藏但无 entitlement：可同步公开 metadata，不返回完整定义；已获取且允许离线使用：可同步定义及必要预览；许可禁止二次传播时仅可个人创作使用。授权撤销后停止新的云端下载/更新，不能未经许可远程删除用户本地文件。

## 7. 生成历史与公开作品：新目标契约

### 7.1 生命周期

生成任务：queued → running → success / failed / refunded → history retained。

作品发布：draft → validation/moderation → published → hidden / removed。

一个 generation_run 可产生多项 media；一件 work 可引用多项 media；一项 media 可以被多个 work 引用。**生成记录与作品非一对一，且不应以自动复制 works 记录来表达历史本身。**

### 7.2 核心规则

- 任何网站或 Skill 生图结果先归入本人生成历史和私有媒体库。
- 仅用户选择“保存到云端”时上传 Skill 本地历史；不能静默上传整个本地历史。
- 只有用户明确点击“发布”或明确授权的分享操作，才创建/公开 works。
- 发布前确认标题、所选图片、说明、公开范围、公开提示词、画风/图型引用、版权来源。
- 私有原始创作指令可本地/私有云保存；公开提示词须由用户确认可分享的内容，不泄露商业信息、私有路径和凭据。
- 发布操作携带稳定 requestId/idempotency key。超时后查询原请求结果，禁止无确认重复发布。
- 用户个人公开主页“作品”只展示 published 且可见作品；个人创作空间“生成历史”展示网站 + Skill 的本人私有任务。界面清楚说明两个区域的区别。
- 发布后删除历史记录的行为，应依关联和用户授权决定，不应误删仍被作品引用的媒体。

### 7.3 存量数据迁移

1. 对现存 studio_generations、works、generation_works 和图片引用做只读统计与一致性审计，按 owner、status、visibility、engine 与原始发布时间分组。
2. 识别已有公开作品的真实用户意愿与既有权限；保留原 work ID、URL、互动及来源。
3. 对未明确公开的旧记录保守处理，不能批量自动发布；也不得擅自把已有真实公开作品下架。
4. 新旧逻辑通过 feature flag 并行过渡；先双读/对账，再切换写路径，最后清理旧自动投影。
5. 为公开作品缺失、媒体缺失、状态异常提供可重试且幂等的修复任务；失败进入异常队列，不能吞错。
6. 数据库迁移只增不减，提前备份；生产上线逐步放量且可回滚应用代码。

## 8. API 合同草案（URL 需在实现 PR 中冻结）

**已有基础**：
- POST /api/auth/device、POST /api/auth/device/approve、POST /api/auth/device/token、GET /api/auth/me。
- GET /api/library/assets、PUT /api/library/assets/{uid}、DELETE /api/library/assets/{uid}、POST /api/library/assets/{uid}/restore。
- GET /api/skill/library、资源受控内容 API、POST /api/collections/toggle（实际权限需测）。
- POST /api/uploads、POST /api/entries（当前代码 publish scope 已放行，需验证上传及原点安全策略）。

**规划新增（不表示当前已实现）**：
- GET /api/v1/me/resources?since=...：个人画风/图型增量列表。
- PUT /api/v1/me/resources/{id}：按 baseRevision 创建或更新。
- GET /api/v1/me/collection-items：收藏 + entitlement + sync eligibility 汇总。
- GET /api/v1/resources/{id}/download：按授权返回完整结构化定义。
- POST /api/v1/me/generations：导入/声明 Skill 生成历史，稳定 externalRunId 幂等。
- GET /api/v1/me/generations：跨端私有历史分页查询。
- POST /api/v1/works/{id}/publish 或现有 /api/entries 的统一增强契约：显式发布。
- GET /api/v1/works/{id}/comments、POST /api/v1/works/{id}/likes、GET /api/v1/me/notifications：复用网站领域服务的客户端适配层。

跨端统一数据属性：id、ownerId、originClient、schemaVersion、revision、updatedAt、deletedAt、requestId；分页 cursor 必须 opaque；错误返回 machine-readable code（401/403/409/410/413/429/5xx），所有写入均需要验证所有权与 scope。接口返回不得暴露密钥、内部绝对路径、私密图片原始访问地址。

## 9. 分阶段实施路线

| 阶段 | 目标 | handraw-web 负责 | handraw-style 负责 | 验收 |
| --- | --- | --- | --- | --- |
| **P0 基础可靠性** | 账号绑定与数据链路可信 | Device token 端到端验证；审计 generation→work；建立同步失败重试、告警与对账；CI 恢复 | 设备授权 UI/CLI、状态提示、凭据安全持久化 | 同账号认证、撤销生效；历史与公开作品差异有解释；失败可定位 |
| **P1 资产同步** | 私有图库、画风图型、完整收藏双向可用 | 复用图库 API；个人资源模型和授权读取；revision/tombstone | 接入本地图库/画廊；增量拉取、离线缓存、冲突副本；完整授权同步 | 电脑 A 创建、电脑 B 恢复；私有不泄漏；未解锁不能取全量 |
| **P2 生成与发布** | Skill 生成历史 → 私有云 → 主动作品发布 | 历史导入、媒体关联、幂等发布、旧数据迁移 | 导入生成结果、云端保存入口、发布确认与回执 | 同一任务不重复；不点发布不公开；发布后作品广场可查 |
| **P3 社区互动** | 跨端继续查看与互动 | 统一评论/点赞/收藏/通知适配 API | Skill 查看/执行互动、状态同步与通知 | Skill 操作在网站可查；网站新评论 Skill 能拉到 |

建议顺序 P0 → P1 → P2 → P3，不以“接口已经存在”代替 E2E 验收。时程是候选规划，不构成发布日期承诺。

## 10. 必须覆盖的 E2E 验收场景

1. 新 Skill 实例通过设备授权绑定已有网站账户；网站撤销设备后写操作失败。
2. Skill 创建角色、道具、场景、参考图，网站看到同一 UID 与正确私有图片；第二设备完整恢复。
3. 同一个资产两端修改触发 409，按既定规则合并或保存冲突副本，任何一侧不静默丢数据。
4. Skill 创建私有画风/图型并同步；网站可编辑及预览；未主动发布前访客不可见。
5. 网站仅收藏未解锁的资源，Skill 不得取得完整定义；已解锁资源按许可同步使用。
6. Skill 生成成功，云端保存后个人私有历史存在，公开主页作品无新增。
7. 经过明确确认发布后，网站作品列表及详情出现恰好一条内容；重复提交/超时重试无重复。
8. 旧公开作品的 URL、评论、点赞、展示权限和原媒体在迁移后全部保留。
9. Skill 阅读/提交作品评论、点赞、收藏，与网站显示一致；未经授权请求被拒绝。
10. 断网、token 过期、配额超限、对象存储失败、服务端 5xx 均有恢复、错误码和日志追踪路径。

**质量门禁**：后端单元/契约测试、Skill CLI 集成测试、真实浏览器授权与发布旅程、私有权限/越权测试、线上灰度读写对账。任何失败 CI 都必须解释或修复，不以直接合并替代测试通过。

## 11. 性能、存储及运维原则

先保持 handraw-web 模块化单体，避免无谓拆微服务。关系数据库存结构化元数据；对象存储存原图/预览/资源包；后台任务处理缩略图、历史补偿、清理和通知。每个写路径具备幂等/审计/权限，上传做内容类型、尺寸、SHA256、大小与配额检查。对外限流，图片使用短期受控地址，个人库可离线缓存；监控设备绑定成功率、同步成功率、历史落库率、作品发布成功率及重试异常数量。

## 12. 双仓库开发流程与文档治理

- 本文为**产品/架构约束基线 v1.0**；实现前可以提出 RFC/ADR 调整，但不默默改变默认私有、发布意愿和资源授权原则。
- handraw-style 的开发从 feature/skill-web-unification-v1-20261107 分支推进，分功能提交 PR 到 master；handraw-web 的后端改动从 main 创建对应功能分支并通过 PR 验证，禁止在生产数据上试验。
- 跨仓库特性使用相同 issue/PR 标识与契约测试；服务端先兼容旧客户端，再升级 Skill；上线时保留双向兼容窗口和显式 rollback。
- 先冻结身份、图库、个人资源、生成历史、发布及互动的公共 DTO；API 契约由 web 管理，Skill 通过客户端适配层使用。
- 每期完成标注实际状态（未开始 / 开发中 / 测试中 / 已发布）、提交 SHA、验收记录，不将“规划”写成“已实现”。
- 主文档位于 handraw-web，公开 Skill 仓库保留可开发的协作摘录与回链；重大变更两个仓库同时更新链接和版本号。

---

**结论**：建设重点不是新增七组彼此独立的同步按钮，而是让 Handraw 成为“同一个账号、同一份个人资产、不同创作入口、主动公开作品、统一社区互动”的完整产品。