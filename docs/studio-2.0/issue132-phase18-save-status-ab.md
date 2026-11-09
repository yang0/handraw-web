# Issue #132 · Phase 18 首次拖拽保存状态按钮文字写入隔离

状态：**仅 C 级 Chromium 实验，不授予生产优化、上线或 Issue 关闭权限**。继承 `studio2@5012e08788bd0744e0a4923bf4c3817cecb7d0fe` 的 Phase17 标签祖先链观测；所有改动位于 `ops/`、`tests/`、CI Artifact 与文档，**未修改** `demo/assets/studio-app.js`、Canvas CSS、数据库或真实供应商。

## 1. 已确认的 Phase17 事实

独立 Run [#42660668860](https://github.com/yang0/handraw-web/actions/runs/42660668860) 14/14 SUCCESS；浏览器 `studio-111-phase16/summary.json` 在 1×/4× 两档首次 `synthetic-move-1` 中各捕捉 2 added / 2 removed 的 `#text`，其父节点标签为 `button`，脱敏标签祖先链为 `html > body > div > div > div > div > button`、`parentConnected=true`。1× 同窗另有 1 次 max=9184 的大树更新，4× 短窗无 >=8k 更新。

源码中 `pushUndo() → markActiveTabDirty() → updateProjectStatusIndicator()` 这条调用链可达 `#bl-save-project` 与 `#studio-project-status` 两个保存状态按钮的无条件 `btn.textContent=...` 写入。但 **Phase17 只记录标签，尚未证明这两只按钮是实际变更的完整来源**，更不能推断更新足以引发整个 `UpdateLayoutTree`。

## 2. Phase18 仅测试页可逆干预

`ops/canvas_phase18_status_text_132.py` 在 `window.__HANDRAW_TESTING__===true` 下短时包装 `Node.prototype.textContent` 原生 setter，按 DOM 对象身份严格限制为 `#bl-save-project` 与 `#studio-project-status` 两个已存在按钮，且只记录 **固定按钮角色** 的调用计数。不存储 DOM ID、文字内容、class、完整 Trace 或媒体；ID 仅用于本地寻找测试目标。

- **A（observe）**：原样执行全部按钮文字写入，记录首次拖拽窗口的 setter 调用、HTML childList、Chrome 原生大树更新汇总。
- **B（suppress）**：在真实已按下 pointer 的三次 `isTrusted=false` 合成 `pointermove` 期间，**只拦截这两只按钮的文字 setter**；其他元素与所有 Canvas Graph、Undo、连线/素材读写均按原路径运行。临时抑制两只按钮的 UI 文案意味着 B **不是可部署视觉方案**。
- 以相同 Studio HTTP/SQLite 300 节点、150 SVG 边、120 张独立解码 WebP，分别在 Chromium 模拟 CPU 1×、4× 下实施 **A-B-A-B-A** 五次独立拖拽，并复用 Phase15 的 pre-input-idle / move#1 / move#2 / move#3 独立有界 CDP Trace。每次 pointerup 后验证权威布局、Graph/Undo 恢复、节点坐标、图片解码与 SVG 路径。
- 每轮结束必须 `Object.defineProperty` 恢复原生 `Node.prototype.textContent` 描述符，移除监听器；任何无法恢复或计数不完整的试验 **fail-closed**。只上传 `artifacts/studio-111-phase18/summary.json`，不上传原始 trace。
- 对比两档 CPU 中 A/B 首移动的文本节点变更是否消失、`UpdateLayoutTree` 大事件是否消失，判断 `#111` 唯一诱发链能否进一步缩小。**Chrome 异步刷新可能跨越 Trace 切窗；即使 A/B 的一档结果明显，也不能宣称因果或上线。**

## 3. 结果判定纪律

必须逐项说明：两按钮是否实际捕捉到首次 move 的 setter 写入；B 是否完全拦截这些写入；B 后 childList 2+2 是否消失；两档 CPU 的 3 次 A 与 2 次 B 是否稳定且 Graph/Undo 不变。

若某 CPU 的 A 组本身未出现大型 UpdateLayoutTree、B 后仍有大型事件、Trace 切窗结果波动，结论一律写为 **不具备唯一因果证明 / 不具备双 CPU 稳定收益**。即使两档 A/B 均有效，也需在不改生产代码的独立、视觉完整浏览器验证及低端真实设备 D 级验证后，才能考虑生产改动的单独 Issue 与审批。

## 4. 与 D 级发布无关

FF-018、FF-019、FG-025 均仍待官网人工来源/版权审核与正式 Web 已发布 DB 证据；17 条真实 D 级门禁未凭本实验取得有效 PASS。真实供应商账单、PG17 物理备份异机恢复、真实 R2/S3/CDN、真实多实例 Redis、真实低端设备及双人发布签核缺失前，**#132 Open，PR #131 Draft，main 不变，生产 NO-GO**。
