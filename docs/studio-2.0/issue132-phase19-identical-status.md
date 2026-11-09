# #132 Phase19 · 仅跳过重复保存状态文案（测试页可逆拦截）

**严格 C 级**，不得据此修改生产 CSS/JS、合并 main 或解除 NO-GO。继承 Phase18 独立 CI [#42665892806](https://github.com/yang0/handraw-web/actions/runs/42665892806) 14/14 真实 Chrome Artifact：1× A-B-A-B-A 的正常首移动均有 1× max=9185 大树更新，拦截全部保存按钮文字写入后均为 0（max=2）；两个已知按钮文本变化各消失 1 次。模拟 4× 的 A 组三次均未在短 CDP 窗口捕获 >=8k，**无法证明双 CPU 可靠收益**。两档的 B 都使子节点 2+2 变 0+0。1× 所有按钮写入 `identical=true`，4× 有部分 `identical=false` 的真实文案变化，因此禁止把 Phase18 的「屏蔽全部保存按钮文字」作为生产优化。

## Phase19 测试目标和执行

仅在真实 Studio **测试页**使用 `Node.prototype.textContent` setter 的临时包装；不同于 Phase18 的全屏蔽，`skip_identical` 仅在目标按钮既有文案与即将写入的新文案**完全相同**时跳过冗余赋值，真实变化必须调用原 setter。每次赋值在浏览器内验证调用后的按钮文本是否等于本次目标文本，只对外输出固定按钮角色的**计数和布尔校验**；不收集、输出、保存实际文案/用户数据/原生 Trace。每次保证原型恢复；失败 fail closed。

在原来 300 节点、150 SVG 连线、120 张独立 WebP 的原生 Chromium 中，每档模拟 CPU 1×/4× 做 A-B-A-B-A（A observe，B skip_identical），单次真实 pointerdown + 三次 `isTrusted=false` synthetic move、四个独立 CDP Trace 窗口，Graph/Undo/图片解码/节点坐标强断言。每档报告首次移动的：
- 两按钮 setter writes / identical / skipped / necessary writes 的聚合；
- 子节点新增/移除数；
- >=8000 UpdateLayoutTree 事件数与最大受影响元素数；
- 每轮原型恢复、文本语义、Graph/Undo 不变量。

## 严格判断

若 A 组 4× 短窗不出现大型 UpdateLayoutTree，则 B 组没有大型事件不证明 4× 受益；若 B 仍出现变化，只能报告真实文案变更与 async Trace 时序。**即便两 CPU 的短窗 A/B 都成功**，因为仍是 Chromium synthetic throttle 与测试探针干预，也需要非诊断真实视觉验证、实体低端硬件、多次稳定性能验证与独立审批，才能考虑生产代码。不得以 test-only `no-visual` 上线。

FF-018、FF-019、FG-025 网站官方审批仍缺真实证明，17 项 D 级证据缺正式核验；#132 保持 Open、PR #131 Draft、生产 NO-GO。