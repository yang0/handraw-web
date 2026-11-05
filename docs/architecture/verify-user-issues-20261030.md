# 创始人三个问题的独立验收（2026-10-30）

验收对象：`main` @ `d0cbde0`（工作区另有 5 个已修改、3 个未跟踪的 backend 模块），运行中的服务 `http://127.0.0.1:3099`（`--db .local\seed_v2.db`），测试账号 `linnan`。
所有脚本、截图、原始结果在 `.local/verify-20261030/`（已被 `.gitignore` 忽略）。

## 1. 一句话结论

在 3099 这台正在运行的服务上，文档导入已经修好；文章编辑器的配图卡片和独立预览页基本可用。但「深度长文自动配图」标签仍会以两种方式出现，所以问题 1 只修好了一半。更严重的是 `HEAD` 没有提交 `backend/document_parser.py`，任何从 git 部署的环境导入任何格式都会返回 500。另外，「所有生图先经过手绘 skill」只对 10 张种子图成立，网站上的实时生图（包括文章配图）都没有经过 skill。

## 2. 三个问题逐项判定

### 问题 1：删除「深度长文自动配图」标签：**部分解决**

| 检查 | 方式 | 结果 |
|---|---|---|
| 全新浏览器打开画布 | Playwright，访客和 linnan 各一次，`i1_tabs.py` | 只有 🎯 节气海报、🔁 百图矩阵、🔗 全媒体一稿三端 3 个标签 ✅ |
| 文章模式 `?entry=article` | 同上 | 能进入编辑器，「文章模式」按钮高亮 ✅ |
| 进过一次文章模式后回到画布 | 点 `#studio-mode-canvas` | **出现第 4 个标签「📝 文章配图」**，刷新后仍在；点它会跳到 `?entry=article` ❌ |
| 老用户浏览器（本地存着修复前的标签） | 往 `handraw_open_tabs_v10::guest` 写入旧的「📰 深度长文自动配图」后刷新，`i1_legacy.py` | **旧标签原样显示**，点击跳到文章模式 ❌ |
| 其他入口 | 读代码 + 浏览器 | 「工作流」库、「＋ 新建」菜单、`?tab=article` 都还能建出这个标签 ❌ |

截图：`i1_linnan_canvas_after_article.png`（4 个标签）、`i1_legacy.png`。

原因：只改了默认标签列表（`demo/assets/studio-app.js:2342-2350`）。`ensureArticleWorkspace()` 在进入文章模式时会新建一个 article 蓝图的标签（`:847`），标签栏不加过滤地渲染所有标签（`:8879`）。从本地存储恢复的标签也没有清理旧 article 标签（`:2325`）。

创始人自己的浏览器就属于「老用户」这一类，他再打开画布，大概率还会看到原来那个标签。对他来说，这个问题实际上没有变化。

### 问题 2：导入文档：**运行中的站点已解决；提交的代码未解决**

**真实点击测试**（`i2_import.py`）：点击「🔄 导入/替换文档」这个 label，通过文件选择器上传文件，而不是直接对隐藏的 input 调用 `set_input_files`。测试文件都由 python-docx / PyMuPDF 生成。第一行是噪声「内部资料 · 仅供评审 · 第3版」，真正的标题放在第二行。如果标题是按启发式规则取的，结果会是第一行；所以只有 AI 解析才能让标题落在第二行。

| 格式 | API | rawLength | 编辑器标题 | 正文被替换 | 丢掉了噪声首行 |
|---|---|---|---|---|---|
| .docx | 200 | 184 | 城市夜跑者的手绘地图 | ✅ | ✅ |
| .pdf | 200 | 170 | 城市夜跑者的手绘地图 | ✅ | ✅ |
| .md | 200 | 196 | 城市夜跑者的手绘地图 | ✅ | ✅ |
| .txt | 200 | 190 | 城市夜跑者的手绘地图 | ✅ | ✅ |

页面的字数计数随之更新，无 JS 错误。直接调用 `/api/studio/parse-article` 的结果相同（`api_parse_result.json`，每次 1.8–4.7 秒）。

**依赖**：
- `requirements.txt` 已声明 `python-docx>=1.1`、`PyMuPDF>=1.24`，这个声明也在 HEAD 里 ✅
- 3099 的服务实际跑在 `E:\tools\hermes\hermes-agent\venv`（父进程 14020）里。那里装了 python-docx 1.2.0 和 PyMuPDF，`D:\Python313` 也装了 ✅。这是一个 agent 工具的 venv，不是本项目自己的环境。
- `ops/*.sh`、`ops/*.ps1`、`service.bat`、`run_dev.ps1` 里**都没有** `pip install -r requirements.txt`。新机器照着部署脚本装，还是会缺这两个库。
**提交的代码缺解析模块**：`backend/server.py:2422` 导入 `backend.document_parser`，但这个文件在工作区里是未跟踪状态（`git status` 显示 `??`）。我用 `git worktree` 检出干净的 HEAD，在 3199 端口另起一个服务，结果 `.docx` 和 `.md` 都返回：

```
HTTP 500 {"ok": false, "error": "No module named 'backend.document_parser'"}
```

也就是说，提交 `745688f`「fix: import .docx and .pdf again」本身并不包含修复。测试套件发现不了这个问题，因为 `tests/` 里没有任何一个测试覆盖 `parse-article`。

### 问题 3：文章编辑模式：**部分解决**

测试脚本 `i3_editor.py`，视口 1440×900。

| 检查 | 结果 |
|---|---|
| 点「规划封面与插图」后出现配图卡片 | 3 张：文章封面 2.35:1、插图 1 · 一、为什么要手绘路线 4:3、插图 2 · 二、从草图到作品 4:3 ✅ |
| 每张卡都有标题、画幅、✏️ 调提示词、⚡ 生成、🗑️ 删除 | 3/3 ✅ |
| 「调提示词」弹窗 | 能打开，显示完整提示词，可编辑，有「⚡ 保存并生成此图」✅ |
| 保存并生成 | 弹窗关闭，**真实生成 1 张图**并显示在卡片里；我追加的「【验收追加】：画面右下角加一只橘猫」出现在发给 `/api/studio/generate` 的 prompt 中，生成的图里也有这只猫 ✅ |
| 底部「生成配图」批量按钮 | 规划前禁用，规划后启用 ✅（为了不消耗额度，没有点它） |
| 卡片可见 | 滚动后每张卡的「生成」按钮都没被遮挡，可以点击 ✅；**但规划后第一屏看不到任何卡片**：第一张卡的顶部在 y=907，视口高 900（`i3_after_plan_firstscreen.png`）。点了按钮，用户只看到一条 toast，页面本身没有变化 ⚠️ |
| 所见即所得地「在文章中」插入占位卡 | ❌ 正文仍然是一个 Markdown 源码 `<textarea>`。卡片排在正文下方单独的 `<section id="pv-notion-article-sheet">` 里（`studio-app.js:11825`），这个区域里正文段落数为 0，只有「＋ 在××添加配图」的插入点。工具栏的「🖼️ 插入配图位」只是往正文里插一段 `> 🖼️ 【插图位建议：…】` 文字（`:12119`），不会生成卡片。截图 `i3_cards_scrolled.png` |

**补充要求（独立预览页）**：

| 检查 | 结果 |
|---|---|
| 编辑器没有内联预览栏 | 编辑区只有两列：历史列表 260px 和写作区 1180px ✅ |
| 点「👁 预览」跳到 `?subview=preview` | ✅，刚输入、还没等自动保存的一句话也显示在预览里 |
| 预览页「← 返回编辑」 | 回到 `?subview=editor`，正文和 3 张卡都还在 ✅ |
| 在预览页刷新，或直接打开预览链接 | ❌ URL 仍是 `subview=preview`，但页面显示编辑器。我在 0/300/1000/3000ms 分别检查，都没有预览页。原因：`renderFullPreviewStage()` 把所有非列表的 subview 都强制改成 editor（`studio-app.js:10222`），初始化时渲染的预览页随即被覆盖 |
| 浏览器后退键 | ❌ URL 变了，页面不变。代码里没有任何 `popstate` 监听 |

## 3. 「生图经过 skill」是否成立：**只对种子图成立**

| 检查 | 结论 | 证据 |
|---|---|---|
| `backend/skill_prompt.py` 读 skill 的 `styles.json`、`layouts.json` | ✅ | `:39-54` 读 styles/layouts/colors.json；`:95-108` 读图型自己的 `layouts/<id>.md` 排版规则。实测 SC-021 规则 7583 字、EC-002 1076 字都能读到 |
| skill 来源 | ✅ | `E:\handraw-style`，HEAD `0ea944a`，0 处改动。remote 是 gitee 镜像，不是 github.com/yang0/handraw-style；内容是否一致我没有核对 |
| 种子图用 skill 生成 | ✅（有保留） | `ops/generate_starter_images.py:75` 调 `skill_prompt.compose_prompt`；用 `--prompts-only` 实跑得到 `source=model`。10 张图的构图和各自图型一致，例如 SC-021 是上半照片、下半插画，EC-002 是多角度分格（`starter_sheet.png`）。保留：仓库里没有记录用哪个 prompt 生成了哪张 `.webp`，脚本输出 `.png`，提交的是 `.webp`，中间的转换步骤不在仓库里 |
| skill 输出有没有校验 | ❌ | 实跑 `FG-004 / EC-002` 时，模型返回的开头是 "I can't generate images directly, but here's a ready-to-use prompt…"，`compose_prompt` 会把这段原样当作 prompt（`skill_prompt.py:219`）。FA-013 返回的是带 `#`、`---` 的 Markdown 文档 |
| **网站实时生图经过 skill** | ❌ | 整个仓库只有 `ops/generate_starter_images.py` 导入了 `skill_prompt`。`backend/services.py:3014` 加了 `promptFromSkill` 开关，但前端从来不传这个字段。数据库里这次生成的最终 prompt 是 `立即生成图片：…请直接调用画图工具立即生成图片…`，就是网站原有的通用外壳（`studio_generations.prompt`） |
| 文章配图提示词含图型 | 有这一行，但起不到作用 | 见下文 |

**文章配图的「图型」**：`assembleArticleCardFullPrompt`（`studio-prompt-engine.js:1504`）实际输出：

```
【构图与图型参考 IG-001】：标题金字塔图标信息图 —— 带标题、金字塔示意图、分层结构、标签图标、多层信息图
```

1. 这一行只有图型名和 `layouts.json` 里的关键词，**没有 `IG-001.md` 里的排版规则**，所以不满足「包含图型的排版规则」。
2. 图型写死为 `IG-001`（`studio-app.js:10575`、`:11446`），编辑器里没有选择图型的入口。于是每篇文章的封面和每张章节插图都按「金字塔信息图」来画。我生成的那张章节插图确实画成了金字塔信息图。图型是「用上了」，但用的是一个不适合叙事插图、用户也改不了的默认值。
3. 每张卡的提示词里都有一行 `【补充创作要求】：`，后面是**整篇文章正文**。原因：article 蓝图的文本节点自带一份示例 `fileContent`（`studio-prompt-engine.js:1656-1660`），所以 `:1464` 的判断条件恒为真，`userNoteText`（即全文，`studio-app.js:11479`）被当作补充要求塞进了每张卡。文章越长，每张卡的提示词越长，各卡之间也会互相串内容。
## 4. 实际测试数字

| 套件 | 命令 | 结果 |
|---|---|---|
| 网站 Python，工作区 | `python -m pytest -q -rs` | **240 passed**, 11 subtests（99.4s） |
| 网站 Node，工作区 | 逐个 `node tests/*.cjs` | **17/17** |
| 网站 Python，干净检出 HEAD `d0cbde0` | 同上，`git worktree`，porcelain 0 | **233 passed, 3 skipped**, 11 subtests（95.6s）。3 个 skip 都是 `test_seed_starter_library.py`「style art not installed in this checkout」 |
| 网站 Node，干净检出 HEAD | 同上 | **12/12** |
| 干净 HEAD 实际起服务 | 3199 端口，调 `parse-article` | **500**（`No module named 'backend.document_parser'`），测试是绿的，但功能是坏的 |
| skill `E:\handraw-style` `0ea944a` | `python -m pytest skills/community-share/tests -q` | **30 passed** |
| skill 资料校验 | `python skills/handdraw-style-prompter/scripts/validate_library.py` | FAIL：`skills/release-illustration-planner/SKILL.md:94` 写了本机路径 `file:///E:/handraw-style/...`。这与本次修复无关。这个脚本还会把该文件的换行改成 CRLF，我已用 `git checkout` 还原，skill 仓库回到 0 处改动 |
| 浏览器巡检 | `crawl.py`，访客和 linnan 各一遍 | 首页、作品列表、作品详情、论坛、创作台（表单/画布）、文章列表、文章编辑器、预览页、后台：全部 200，**0 个 JS 异常，0 个 404**。唯一的错误是 linnan 打开后台时 `403 /api/admin/permissions`，这个账号不是管理员，属于预期行为 |
| 编辑器测试期间 | `i3_editor.py` | 2 次 `502 /api/studio/tasks?...`：轮询时生图网关暂时失败（`server.py:1797`），之后自动重试成功 |

## 5. 仍然存在的问题

按严重程度排序。

| # | 问题 | 位置 |
|---|---|---|
| 1 | **导入功能的模块没有提交**：HEAD 部署后，所有格式的导入都返回 500 | `backend/document_parser.py`（未跟踪），调用处 `backend/server.py:2422`；`backend/cold_start_content.py` 同样未跟踪，`ops/seed_cold_start.py:25` 依赖它 |
| 2 | 网站实时生图（文章配图、画布、表单）都不经过 skill，`promptFromSkill` 是一条没人调用的分支 | `backend/services.py:3014`；`demo/assets/studio-app.js:4674`、`:5062` 的请求不传这个字段 |
| 3 | 每张卡的提示词都带着整篇正文 | `demo/assets/studio-prompt-engine.js:1464`、`:1656-1660`；`demo/assets/studio-app.js:11479` |
| 4 | 图型写死为 IG-001 金字塔信息图，没有选择入口，提示词里也没有排版规则 | `demo/assets/studio-app.js:10575`、`:11446`；`demo/assets/studio-prompt-engine.js:1504` |
| 5 | 「📝 文章配图」和旧的「📰 深度长文自动配图」标签还会出现，点了跳到文章模式 | `demo/assets/studio-app.js:847`、`:2325`、`:2354`、`:2366`、`:8879`、`:10351`、`:10421`；预设 `backend/seed.py:127`、`demo/assets/studio-prompt-engine.js:259-261` |
| 6 | 配图卡在正文下方单独列出，不在正文中；规划后第一屏看不到卡片 | `demo/assets/studio-app.js:11825`（第一张卡 y=907，视口 900） |
| 7 | 预览页刷新或直接打开链接时显示编辑器；后退键不起作用 | `demo/assets/studio-app.js:10222`；整个文件没有 `popstate` |
| 8 | `parse-article` 不要求登录，也没有限流，匿名用户可以无限调用 AI 解析。连续 12 次匿名请求全部返回 200 | `backend/server.py:2420` |
| 9 | AI key 写死在代码里。这个文件目前未跟踪，按问题 1 提交它时 key 会一起进仓库 | `backend/document_parser.py:226` |
| 10 | AI 解析失败时退回到「取第一行做标题」，前端和接口都没有标出这是降级结果 | `backend/document_parser.py:289-292`，返回体中没有 `source` 字段 |
| 11 | skill 输出不经校验就当作 prompt（拒绝语、Markdown 都会原样通过） | `backend/skill_prompt.py:218-220` |
| 12 | skill 路径默认写死为 `E:\handraw-style\...` | `backend/skill_paths.py:24` |
| 13 | 部署和启动脚本不安装 `requirements.txt`；当前服务依赖 hermes agent 的 venv | `ops/server-deploy.sh`、`service.bat`、`run_dev.ps1` |
| 14 | 后台页标题是乱码（早于本次改动，从 `f7b4396` 就有） | `demo/admin.html:6` |

## 6. 能否交付给创始人继续试用

**本机 3099 可以继续试用，但不能告诉创始人「三个问题都已修好」。**

可以试用的部分：文档导入（四种格式，AI 提取标题）、配图卡的调词和单张生成、预览页的往返。这些我都实际点过。

试用前应该先告诉创始人：
- 他浏览器里原来那个标签可能还在，清除站点数据后才会消失；
- 配图卡在正文下方，不在正文段落之间；规划后需要往下滚才能看到；
- 不要刷新预览页。

在说「已修好」或部署到任何其他环境之前，至少要做到：
1. 提交 `backend/document_parser.py`（先删掉写死的 key），为 `parse-article` 加至少一个测试；
2. 修复问题 3（正文被塞进每张卡的提示词），否则每张配图的提示词都是错的；
3. 和创始人确认：「生图必须经过 skill」是否包括网站的实时生图。如果包括（他的原话是「不管是文章配图还是其他图片生成」），目前没有实现；
4. 清理旧标签：恢复存储时过滤 article 蓝图，并去掉库、菜单和 `?tab=article` 这几个入口。

## 附：本次验收的副作用

- linnan 账号里新建了 3 篇测试文章（标题「城市夜跑者的手绘地图」/「导入前的旧标题」）；
- 真实生成 1 张图，用掉 1 次每日免费额度；
- 本地 AI 服务被调用约 20 次（导入测试和限流测试）；
- 临时 worktree `E:\tmp-verify-head-d0cbde0` 和 3199 端口的服务已删除、关闭；网站仓库的工作区状态与验收前相同。
