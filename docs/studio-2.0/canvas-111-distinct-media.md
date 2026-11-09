# Studio 2.0 · #111 第九阶段：真实 120 个独立 WebP 解码的 Chrome 压力验证

日期：2026-11-09；基线 `studio2@362f0c2058844b006834f5eacc125d8ffddf533e`；独立分支 `studio2-issue111-distinct-media-browser-20261109`。关联 #111、#84、#112、Draft PR #131。

## 问题与原则

第八阶段证明：此前 300 节点的 120 个 `img` 实际复用了仓库内约 2 个 WebP URL，Chromium 可能共享相同解码缓存，无法据此声称「120 个独立大图」已验收。现有数据更支持**拖拽时广范围 Style 更新**的解释，但既不能锁定某一条 CSS 规则的因果效果，也不能否定独立大媒体的额外解码/内存开销。

本阶段先**补齐测试真实性**，不更改生产画布 CSS/JS、不引入全量虚拟化或 WebGL、不重复开启已回滚的 `translate`/rAF 合并方案。

## 受控测试设计

- `ops/canvas_unique_media_111.py`：从仓库现有三个公开测试 WebP **临时派生** 120 个不同 SHA256 文件，目标像素 960×720；仅裁切/亮度调整与独立 WebP 编码，未生成新艺术、未使用生产图或第三方 API。文件只存在测试期间的 `demo/starter/qa111-distinct-*` 临时目录，成功或失败退出后自动清除；不提交图像字节、不上传媒体文件到 CI artifacts。
- 启动临时隔离的 Studio HTTP 服务/数据库，创建两个全新测试 Project，各有 300 个真实类型节点、150 SVG edges、120 个 `img`；一组复用 2 个 WebP URL，一组使用 120 个不同本地 WebP URL。两组基于同一 `graph_fixture(30)`，且所有 Graph 结构/编辑状态一致。
- 实测顺序 A（重复源）→ B（独立编码源）→ A（重复源复测），同一 Chrome Runner/上下文。每组要求 **120/120 图片完成 `img.decode()`**，检查独立 URL 数 2/120/2、自然像素合计、CPU 计算量、JS Heap 的可用指标、页面错误、媒体 DOM 稳定及实际鼠标可命中。
- 每组真实 `page.mouse` 12 次拖拽，采 CDP `RecalcStyleDuration` / Layout / Script 等累计窗口与 rAF gap 分布；模型坐标与卡片 CSS 对齐，150 连线保持、图片 DOM 不重建、Ctrl+Z 回到原位。额外对 120 独立图进行一次 **Chrome CDP 模拟 4× CPU 限速** 的同类拖拽，始终不调用任何付费生图接口。
- 输出 `artifacts/studio-111-distinct-media/summary.json` 只包含环境、汇总耗时/像素/编码体积/计数，不包含图像二进制、完整 URL、Cookie、令牌、私有提示词或原始 Chrome Trace。测试用账号、Graph 与媒体均为自建临时数据。

## 判读边界

1. 自有仓库图像的派生变体虽然有 120 个独立编码哈希，但**不是 120 幅不同的真实用户内容、也不代表 CDN/R2/S3 的网络延迟与解码复杂性**。即使自然像素数接近真实大图，也不能外推复杂图的 VRAM/GPU Present 成本。
2. A→B→A 只能帮助排除一部分缓存/顺序偏差；重复测量与 CI Runner 抢占变化仍会影响耗时。累计 Style 时长不等于每帧花费；rAF 不等于 GPU 真正呈现。
3. 4× CPU 是模拟降速，不是实体低端手机；`performance.memory.usedJSHeapSize` **不包含可靠的 GPU 纹理/完整图片解码内存**，不得将其称为「全部占用内存」。
4. 若独立编码媒体明显增加耗时，先判定瓶颈在 load/decode/paint/composite 还是 Style，再考虑保留端口几何与交互的特定延迟加载/资源优化，不能不经生产 A/B 就调整所有节点。
5. 若没有稳定收益，不修改生产渲染器；保留测试门禁。发布仍按 #84/#112 真实存储、真实收费网关、真实多实例、真实设备及 #11 官方资源终审另行签核。

## CI 和收口

- 新增 Python 夹具边界单测与真实浏览器独立项目压力测试；保留原先 #111 基准测试与全部 14 Job。
- **等待完成：** 独立 SHA 14/14 → compare ahead>0/behind=0 → expected-SHA `force=false` 快进 `studio2` → 同 SHA 的 Push/PR 两套各 14/14。没有结果不得勾选，失败要留审计记录。
- PR #131 必须一直保持 Draft，绝不直接修改或合入 `main`。
- **生产发布：NO-GO**；#111 树级 Style 根因、低端机真实性及 #84/#112 D 级仍需独立验收。

## 实测结果与决策（2026-11-09）

### 首轮：测试工具工作正确，但两组自然像素总量不相同

独立分支 [GitHub Actions #42570307011](https://github.com/yang0/handraw-web/actions/runs/42570307011) 14/14 SUCCESS；120 张均已实际完成解码，物理拖拽、Ctrl+Z、150 条 SVG 和零付费调用均通过。注意复用原图组与独立派生组图片的自然像素总量不同，**首轮仅作为测试功能证据，不作为严格 A/B 耗时结论**。差异已在同独立分支修复：两个 Project 都使用相同的 960×720 媒体尺寸，复用组仅使用派生目录中的前两个 URL，独立组使用 120 个不同 URL；每组在 DOM 上均有 120 张 img、总计 82,944,000 自然像素。

### 严格等像素 A→B→A · 同一 SHA 14/14 SUCCESS

验证提交 `a73e040e2d9a2cad5f23d4501646b65605ae8c22`，独立分支 [GitHub Actions #42570819591](https://github.com/yang0/handraw-web/actions/runs/42570819591) **14/14 SUCCESS**；Chrome Runner 真正解析加载 120 份独立编码的 WebP，所有约束通过。

| 场景 | 独立 WebP URL | 总自然像素 | Chrome CDP Drag-only Style 累计 | rAF gap P95 |
| --- | ---: | ---: | ---: | ---: |
| A1 · 复用两源 | 2 | 82,944,000 | 209.095ms | 33.3ms |
| B · 120 独立文件 | 120 | 82,944,000 | 204.419ms | 33.3ms |
| A2 · 复用两源复测 | 2 | 82,944,000 | 202.990ms | 83.4ms |
| B / CDP 4× CPU 模拟 | 120 | 82,944,000 | 931.476ms | 详见 CI JSON |

三组正常 CPU 的 Style 累计在约 203–209ms 范围，没有呈现独立媒体造成的明显 Style 增量；但 A2 的 rAF gap P95 大幅波动，**不能宣称独立媒体不增加真实帧成本，也不能据此认定稳定 30fps 或 60fps**。此处 4× CPU 数值不能与未限速数据直接比性能增益。完整单项目加载/解码耗时、CDP Layout、Script、Task、rAF 统计及可用 JS Heap 观测数值都留在 CI `artifacts/studio-111-distinct-media/summary.json`；不把 JS Heap 当 VRAM/所有解码图片内存。

### 交付决策

1. **没有对产品 Canvas CSS、DOM 或 Graph Runtime 做任何变更**；已有局部卡片重绘、定向 pointerup 和历史性能优化保持。
2. 真实 300 节点、150 边、120 个不同 URL 的本地 WebP 解码与物理鼠标回归成为持续 CI 门禁；无付费网关及原始媒体 artifact 泄漏。
3. 本次结果没有证明某条选择器是树级样式重算的唯一原因，也没有为未经验证的 GPU/Canvas 虚拟化方案提供支持，因此**不引入无稳定收益的渲染层重构**。
4. #111 仍 **Open**；真实 CDN/R2/移动端、低端物理设备 GPU Present、超长会话 GC、真实媒体解码/纹理内存仍须 #112 D 级单独测试；#84/#11 也尚未验收，生产继续 **NO-GO**。

后续工程纪律：本次文档提交的新 HEAD 仍需独立分支 14/14，才能 non-force expected-SHA 快进 `studio2`；之后需要 `studio2` Push 与 Draft PR #131 的同 SHA 14/14。未通过不得同步，严禁修改 `main` 或将 PR 标 Ready。
