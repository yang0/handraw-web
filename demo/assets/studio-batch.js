/**
 * Handraw Web Studio - Batch Creation Component (Phase 3b-2)
 *
 * Requirements:
 * - Operates directly on quick batch workflow nodes:
 *   skill_params, text_input, asset, loop, output_control.
 * - No custom data structures; 100% two-way fidelity with canvas.
 * - Row 1: 批量方式 (多文案/多画风/多图型/多图参) + 生成方式 (图文/纯图/海报) + 画风模式 (单画风/双画风融合)
 *   in ONE row, left-aligned in order.
 * - Row 2: Fixed parameter picker cards (same as 做图);
 *   hide style card when 多画风; hide layout card when 多图型.
 * - Row 3: Dynamic by batch mode:
 *   - 多文案: prompt list textarea (one per line) + button 【从母题裂变】
 *   - 多画风: 【选择画风】(multi) + selected thumbnails in same row
 *   - 多图型: 【选择图型】(multi) + selected thumbnails in same row
 *   - 多图参: 【选择参考图】(multi) + selected thumbnails in same row
 * - Row 4: Ratio buttons + inline ratio text input in ONE row.
 * - 更多设置 (Collapsible): tones, moods, whitespace, audience, businessScene, SC-021/SC-022.
 * - 预览表: listed before generation (index, title/item, status: waiting/generating/done/failed, retry for failed).
 * - 底部栏: "共 N 张：免费 X 张 + Y 积分" + 【开始批量生成】; during generation shows progress + 【停止】.
 * - Secondary confirmation when count > 20 (dialog stating count & total cost).
 * - Results: per-image download & publish; 【全部下载】 sequentially downloads without ZIP.
 * - AI Fission modal: POST /api/studio/fission with fallback template notice.
 * - No emoji in new UI text.
 */
(function (global) {
  "use strict";

  const BATCH_MODE_OPTIONS = [
    { id: "prompts", label: "多文案" },
    { id: "styles", label: "多画风" },
    { id: "layouts", label: "多图型" },
    { id: "assets", label: "多图参" }
  ];

  const OUTPUT_MODE_OPTIONS = [
    { id: "graphic-text", label: "图文", defaultRatio: "3:4" },
    { id: "pure", label: "纯图", defaultRatio: "3:4" },
    { id: "poster", label: "海报", defaultRatio: "9:16" }
  ];

  const RATIO_OPTIONS = [
    { label: "小红书", value: "3:4" },
    { label: "方图", value: "1:1" },
    { label: "横版", value: "4:3" },
    { label: "横屏视频", value: "16:9" },
    { label: "竖屏短视频", value: "9:16" },
    { label: "公众号封面", value: "2.35:1" }
  ];

  const PRESET_RATIOS = RATIO_OPTIONS.map((r) => r.value);

  const WHITESPACE_OPTIONS = [
    { value: "", label: "不限" },
    { value: "normal", label: "正常" },
    { value: "moderate", label: "适中" },
    { value: "high", label: "大量" }
  ];

  const SC021_PLAYSTYLES = [
    "双屏撕画",
    "撕纸拼贴双屏",
    "实物对比",
    "时空前后",
    "局部放大微距",
    "双面情绪",
    "照片手绘"
  ];

  const DEFAULT_MOODS = [
    "治愈", "诗意", "温暖", "宁静", "清幽", "松弛",
    "复古", "童趣", "浪漫", "幽默", "力量", "灵动"
  ];

  const FISSION_STRATEGIES = [
    { id: "daily_quote", label: "系列日签" },
    { id: "selling_points", label: "卖点切角" },
    { id: "knowledge_cards", label: "科普图鉴" },
    { id: "story_beats", label: "连续分镜" },
    { id: "custom", label: "自定义" }
  ];

  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalizeMoodLabel(raw) {
    if (raw == null) return "";
    if (typeof raw === "string") {
      const trimmed = raw.trim();
      return trimmed === "[object Object]" ? "" : trimmed;
    }
    if (typeof raw === "object") {
      const candidate = String(raw.label || raw.value || raw.name_zh || raw.name || "").trim();
      return candidate === "[object Object]" ? "" : candidate;
    }
    return "";
  }

  function formatMoodsText(moods, customMood) {
    const parts = [];
    if (Array.isArray(moods)) {
      moods.forEach((m) => {
        const clean = normalizeMoodLabel(m);
        if (clean && !parts.includes(clean)) parts.push(clean);
      });
    }
    if (customMood && typeof customMood === "string") {
      const cms = customMood.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
      cms.forEach((c) => {
        if (c && !parts.includes(c)) parts.push(c);
      });
    }
    return parts.join("，");
  }

  function parseMoodsText(rawText, presetSet) {
    const tokens = String(rawText || "")
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const newMoods = [];
    const newCustom = [];
    tokens.forEach((t) => {
      if (presetSet && presetSet.has(t)) {
        if (!newMoods.includes(t)) newMoods.push(t);
      } else {
        if (!newCustom.includes(t)) newCustom.push(t);
      }
    });
    return {
      moods: newMoods,
      customMood: newCustom.join("，")
    };
  }

  class BatchCreateController {
    constructor() {
      this.hostElement = null;
      this.context = null;
      this.actions = null;
      this.moreSettingsOpen = false;
      this.fissionModalOpen = false;
    }

    getParts() {
      return this.context?.parts || null;
    }

    getGraph() {
      return this.context?.graph || null;
    }

    getPromptEngine() {
      return global.HandrawStudioPromptEngine || global.HANDRAW_CANVAS_ENGINE || null;
    }

    getResourceInfo(id, kind) {
      if (!id) return null;
      const catalog = this.context?.catalog;
      if (catalog && catalog.resourceMap && catalog.resourceMap.has(id)) {
        return catalog.resourceMap.get(id);
      }
      if (catalog && Array.isArray(catalog[kind])) {
        const found = catalog[kind].find((x) => x.id === id);
        if (found) return found;
      }
      const shared = global.HANDRAW_SHARED;
      if (shared && shared.App && shared.App[kind]) {
        const found = shared.App[kind].find((x) => x.id === id);
        if (found) return found;
      }
      return { id, name: id, image: "" };
    }

    getKnownPresetMoods() {
      const catalog = this.context?.catalog;
      const rawPool = [
        ...(catalog?.moods || []),
        ...(global.HANDRAW_SHARED?.App?.options?.moods || []),
        ...DEFAULT_MOODS
      ];
      const set = new Set();
      rawPool.forEach((m) => {
        const label = normalizeMoodLabel(m);
        if (label) set.add(label);
      });
      return set;
    }

    resolveIterations() {
      const E = this.getPromptEngine();
      const p = this.getParts();
      const graph = this.getGraph();
      const catalog = this.context?.catalog;
      if (!E || !p || !graph) return [];
      try {
        const rec = E.resolveControlRecipe(graph, p.ctrl, catalog);
        return E.resolveLoopIterations(graph, p.loop, rec, catalog) || [];
      } catch (err) {
        console.warn("Failed to resolve loop iterations:", err);
        return [];
      }
    }

    calculateCost(totalCount) {
      const ctx = this.context || {};
      const loggedIn = Boolean(ctx.loggedIn);
      const freeRemaining = Number(ctx.freeQuotaRemaining || 0);
      const settings = ctx.siteSettings || {};
      const creditPerImage = Number(settings.credit_cost_per_image || settings.creditCostPerImage || 2);
      const freeCount = loggedIn ? Math.min(totalCount, Math.max(0, freeRemaining)) : 0;
      const paidCount = loggedIn ? Math.max(0, totalCount - freeCount) : totalCount;
      const totalCost = paidCount * creditPerImage;
      return { loggedIn, totalCount, freeCount, paidCount, creditPerImage, totalCost };
    }

    renderCostHtml(totalCount) {
      const cost = this.calculateCost(totalCount);
      if (!cost.loggedIn) {
        return `<span class="batch-cost-text">共 ${cost.totalCount} 张 · 登录后查看免费额度与预计积分</span>`;
      }
      if (cost.totalCount === 0) {
        return `<span class="batch-cost-text">共 0 张</span>`;
      }
      if (cost.paidCount === 0) {
        return `<span class="batch-cost-text">共 ${cost.totalCount} 张：免费 ${cost.freeCount} 张</span>`;
      }
      return `<span class="batch-cost-text">共 ${cost.totalCount} 张：免费 ${cost.freeCount} 张 + ${cost.totalCost} 积分</span>`;
    }

    renderPickerSlot(kind, label, res, onClear) {
      const hasRes = Boolean(res && res.id);
      const nameText = hasRes ? (res.name_zh || res.name || res.id) : `选择${label}`;
      const codeText = hasRes ? `${label} · ${res.id}` : label;

      return `
        <div class="make-image-picker-card ${hasRes ? "is-selected" : ""}" data-pick-kind="${esc(kind)}" role="button" tabindex="0" aria-label="${esc(hasRes ? `更换${label} ${res.id}` : `选择${label}`)}">
          <div class="make-image-picker-thumb">
            ${hasRes && res.image ? `<img data-hw-src="${esc(res.image)}" alt="${esc(nameText)}" loading="lazy" />` : `<span class="make-image-picker-placeholder">＋</span>`}
          </div>
          <div class="make-image-picker-info">
            <span class="make-image-picker-badge">${esc(codeText)}</span>
            <strong class="make-image-picker-name">${esc(nameText)}</strong>
            <span class="make-image-picker-hint">${hasRes ? "点击更换" : "点击选择"}</span>
          </div>
          ${hasRes && onClear ? `<button type="button" class="make-image-picker-clear" data-clear-kind="${esc(kind)}" title="清除">×</button>` : ""}
        </div>
      `;
    }

    render(host, context, actions) {
      if (host) this.hostElement = host;
      if (context) this.context = context;
      if (actions) this.actions = actions;
      if (!this.hostElement) return;

      const p = this.getParts();
      if (!p) {
        this.hostElement.innerHTML = `
          <div class="make-image-container">
            <div style="padding:48px 24px;text-align:center;color:var(--ink-muted);">
              <h3>正在载入批量工作流…</h3>
            </div>
          </div>
        `;
        return;
      }

      const sd = p.skill.data || {};
      const td = p.text?.data || {};
      const cd = p.ctrl.data || {};
      const ld = p.loop.data || {};
      const ad = p.asset?.data || {};

      const currentLoopMode = ld.loopMode || "prompts";
      const isFusion = Boolean(sd.fusion);
      const style1Id = sd.style1 || "";
      const style2Id = sd.style2 || "";
      const layoutId = sd.layout || "";
      const selectedColors = Array.isArray(sd.colors) ? sd.colors : [];
      const selectedTones = Array.isArray(sd.tones) ? sd.tones : [];
      const selectedMoods = (Array.isArray(sd.moods) ? sd.moods : []).map(normalizeMoodLabel).filter(Boolean);
      const customMood = sd.customMood || "";
      const moodTextValue = formatMoodsText(selectedMoods, customMood);

      const whitespace = sd.whitespace || "";
      const audience = sd.audience || "";
      const businessScene = sd.businessScene || "";
      const sc021Type = sd.sc021Type || SC021_PLAYSTYLES[1];
      const sc022Name = sd.sc022Name || "";
      const sc022Pinyin = sd.sc022Pinyin || "";

      const currentMode = cd.mode === "pure-image" ? "pure" : (cd.mode || "graphic-text");
      const currentRatio = cd.ratio || "3:4";

      const style1Obj = this.getResourceInfo(style1Id, "styles");
      const style2Obj = isFusion ? this.getResourceInfo(style2Id, "styles") : null;
      const layoutObj = this.getResourceInfo(layoutId, "layouts");
      const colorObj = selectedColors[0] ? this.getResourceInfo(selectedColors[0], "colors") : null;

      const promptListText = typeof ld.promptListText === "string" ? ld.promptListText : "";
      const selectedStyleIds = Array.isArray(ld.styleIds) ? ld.styleIds : [];
      const selectedLayoutIds = Array.isArray(ld.layoutIds) ? ld.layoutIds : [];
      const refItems = Array.isArray(ad.items) ? ad.items : [];
      const unifiedTheme = td.text || "";

      const iterations = this.resolveIterations();
      const totalCount = iterations.length;

      const busy = Boolean(this.context?.busy);
      const displays = Array.isArray(this.context?.displays) ? this.context.displays : [];
      const results = Array.isArray(this.context?.results) ? this.context.results : [];

      // Check if batch gallery node is used
      const isBatchGallery = displays.some((d) => d.data?.kind === "batch_gallery");
      const galleryNode = isBatchGallery ? displays.find((d) => d.data?.kind === "batch_gallery") : null;

      // Status text
      let currentStep = ld.currentStep || 0;
      let totalSteps = ld.totalSteps || totalCount;
      if (busy && currentStep === 0) currentStep = 1;

      // Determine show/hide for Row 2 cards
      const hideStyleCards = currentLoopMode === "styles";
      const hideLayoutCard = currentLoopMode === "layouts";

      this.hostElement.innerHTML = `
        <div class="make-image-container batch-container">
          <div class="make-image-head">
            <div class="make-image-head-left">
              <h1 class="make-image-title">批量</h1>
              <p class="make-image-lede">单维度循环批量出图：多文案、多画风、多图型或多图参，一键自动批量生产。</p>
            </div>
          </div>

          <form class="make-image-form" novalidate onsubmit="return false;">
            <div class="make-image-main-grid">

              <!-- Row 1: Batch Mode, Output Mode, Fusion Toggle in ONE Row (left-aligned) -->
              <div class="make-image-top-row batch-top-row">
                <div class="make-image-inline-group">
                  <span class="make-image-field-label">批量方式</span>
                  <div class="make-image-btn-group" role="group" aria-label="批量方式">
                    ${BATCH_MODE_OPTIONS.map((m) => `
                      <button type="button" class="btn btn-sm ${currentLoopMode === m.id ? "btn-primary is-active" : ""}" data-set-loop-mode="${esc(m.id)}" aria-pressed="${currentLoopMode === m.id}">${esc(m.label)}</button>
                    `).join("")}
                  </div>
                </div>

                <div class="make-image-inline-group">
                  <span class="make-image-field-label">生成方式</span>
                  <div class="make-image-btn-group" role="group" aria-label="生成方式">
                    ${OUTPUT_MODE_OPTIONS.map((m) => `
                      <button type="button" class="btn btn-sm ${currentMode === m.id ? "btn-primary is-active" : ""}" data-set-mode="${esc(m.id)}" aria-pressed="${currentMode === m.id}">${esc(m.label)}</button>
                    `).join("")}
                  </div>
                </div>

                <div class="make-image-inline-group">
                  <span class="make-image-field-label">画风模式</span>
                  <div class="make-image-btn-group" role="group" aria-label="画风模式">
                    <button type="button" class="btn btn-sm ${!isFusion ? "btn-primary is-active" : ""}" id="batch-mode-single" aria-pressed="${!isFusion}">单画风</button>
                    <button type="button" class="btn btn-sm ${isFusion ? "btn-primary is-active" : ""}" id="batch-mode-fusion" aria-pressed="${isFusion}">双画风融合</button>
                  </div>
                </div>
              </div>

              <!-- Row 2: Fixed parameter picker cards (hidden if varied) -->
              <div class="make-image-pickers-row batch-pickers-row ${isFusion && !hideStyleCards ? "has-style2" : ""}">
                ${!hideStyleCards ? `
                  ${this.renderPickerSlot("style1", isFusion ? "角色画风" : "画风", style1Obj, true)}
                  ${isFusion ? this.renderPickerSlot("style2", "场景画风", style2Obj, true) : ""}
                ` : ""}
                ${!hideLayoutCard ? `
                  ${this.renderPickerSlot("layout", "图型", layoutObj, true)}
                ` : ""}
                ${this.renderPickerSlot("color", "主题色", colorObj, true)}
              </div>

              ${isFusion && !hideStyleCards ? `
                <div class="make-image-style-note" role="note">角色画风决定人物与主体的画法，场景画风决定背景与环境</div>
              ` : ""}

              <!-- Row 3: Dynamic by Batch Mode -->
              <div class="batch-dimension-wrap">
                ${currentLoopMode === "prompts" ? `
                  <!-- Prompts Mode: Textarea + Button in same row -->
                  <div class="make-image-field-wrap">
                    <div class="batch-field-head">
                      <span class="make-image-field-label">主题列表（每行一条）</span>
                      <button type="button" class="btn btn-sm batch-fission-trigger" id="batch-btn-fission">从母题裂变</button>
                    </div>
                    <textarea class="make-image-textarea batch-prompts-textarea" id="batch-prompts-input" rows="4" placeholder="每行输入一个创作主题或文案，每行将生成一张独立画面...">${esc(promptListText)}</textarea>
                  </div>
                ` : ""}

                ${currentLoopMode === "styles" ? `
                  <!-- Styles Mode: Button + Selected Thumbnails in same row -->
                  <div class="make-image-field-wrap">
                    <div class="batch-chips-head">
                      <span class="make-image-field-label">循环画风列表</span>
                      <button type="button" class="btn btn-sm btn-primary" id="batch-btn-pick-styles">选择画风</button>
                    </div>
                    <div class="batch-chips-row" id="batch-styles-chips">
                      ${selectedStyleIds.length === 0 ? `
                        <div class="batch-empty-chips-hint">点击「选择画风」添加多款画风进行横评出图</div>
                      ` : selectedStyleIds.map((sid) => {
                        const sObj = this.getResourceInfo(sid, "styles");
                        return `
                          <div class="make-image-slot-card is-inline batch-chip" data-chip-style="${esc(sid)}">
                            <div class="make-image-slot-thumb-wrap">
                              ${sObj?.image ? `<img data-hw-src="${esc(sObj.image)}" alt="${esc(sObj.name || sid)}" loading="lazy" />` : ""}
                              <span class="make-image-slot-badge">${esc(sid)}</span>
                              <button type="button" class="make-image-slot-clear" data-remove-style="${esc(sid)}" title="移除">×</button>
                            </div>
                            <span class="make-image-slot-title">${esc(sObj?.name || sid)}</span>
                          </div>
                        `;
                      }).join("")}
                    </div>
                    <div class="batch-unified-theme-row">
                      <span class="batch-unified-theme-label">主文案（统一应用于各画风）：</span>
                      <input type="text" class="make-image-input batch-unified-input" id="batch-unified-theme-input" placeholder="输入画面共同创作主题或主文案..." value="${esc(unifiedTheme)}" />
                    </div>
                  </div>
                ` : ""}

                ${currentLoopMode === "layouts" ? `
                  <!-- Layouts Mode: Button + Selected Thumbnails in same row -->
                  <div class="make-image-field-wrap">
                    <div class="batch-chips-head">
                      <span class="make-image-field-label">循环图型列表</span>
                      <button type="button" class="btn btn-sm btn-primary" id="batch-btn-pick-layouts">选择图型</button>
                    </div>
                    <div class="batch-chips-row" id="batch-layouts-chips">
                      ${selectedLayoutIds.length === 0 ? `
                        <div class="batch-empty-chips-hint">点击「选择图型」添加多款版式进行批量排版出图</div>
                      ` : selectedLayoutIds.map((lid) => {
                        const lObj = this.getResourceInfo(lid, "layouts");
                        return `
                          <div class="make-image-slot-card is-inline batch-chip" data-chip-layout="${esc(lid)}">
                            <div class="make-image-slot-thumb-wrap">
                              ${lObj?.image ? `<img data-hw-src="${esc(lObj.image)}" alt="${esc(lObj.name || lid)}" loading="lazy" />` : ""}
                              <span class="make-image-slot-badge">${esc(lid)}</span>
                              <button type="button" class="make-image-slot-clear" data-remove-layout="${esc(lid)}" title="移除">×</button>
                            </div>
                            <span class="make-image-slot-title">${esc(lObj?.name || lid)}</span>
                          </div>
                        `;
                      }).join("")}
                    </div>
                    <div class="batch-unified-theme-row">
                      <span class="batch-unified-theme-label">主文案（统一应用于各图型）：</span>
                      <input type="text" class="make-image-input batch-unified-input" id="batch-unified-theme-input" placeholder="输入画面共同创作主题或主文案..." value="${esc(unifiedTheme)}" />
                    </div>
                  </div>
                ` : ""}

                ${currentLoopMode === "assets" ? `
                  <!-- Assets Mode: Button + Selected Thumbnails in same row -->
                  <div class="make-image-field-wrap">
                    <div class="batch-chips-head">
                      <span class="make-image-field-label">循环图参列表</span>
                      <button type="button" class="btn btn-sm btn-primary" id="batch-btn-pick-assets">选择参考图</button>
                    </div>
                    <div class="batch-chips-row" id="batch-assets-chips">
                      ${refItems.length === 0 ? `
                        <div class="batch-empty-chips-hint">点击「选择参考图」添加多张参考图片逐张驱动画面</div>
                      ` : refItems.map((ast, idx) => `
                        <div class="make-image-slot-card is-inline batch-chip" data-chip-asset="${esc(ast.id || idx)}">
                          <div class="make-image-slot-thumb-wrap">
                            ${ast.image ? `<img data-hw-src="${esc(ast.image)}" alt="${esc(ast.name || ast.id)}" loading="lazy" />` : ""}
                            <span class="make-image-slot-badge">${esc(ast.id || `P${idx + 1}`)}</span>
                            <button type="button" class="make-image-slot-clear" data-remove-asset-idx="${idx}" title="移除">×</button>
                          </div>
                          <span class="make-image-slot-title">${esc(ast.name || ast.id || `图参 ${idx + 1}`)}</span>
                        </div>
                      `).join("")}
                    </div>
                    <div class="batch-unified-theme-row">
                      <span class="batch-unified-theme-label">主文案（统一应用于各参考图）：</span>
                      <input type="text" class="make-image-input batch-unified-input" id="batch-unified-theme-input" placeholder="输入画面共同创作主题或主文案..." value="${esc(unifiedTheme)}" />
                    </div>
                  </div>
                ` : ""}
              </div>

              <!-- Row 4: Ratio Buttons + Inline Ratio Input in ONE Row -->
              <div class="make-image-ratio-row">
                <span class="make-image-field-label">画幅</span>
                <div class="make-image-ratio-controls">
                  <div class="make-image-btn-group" role="group" aria-label="预置比例">
                    ${RATIO_OPTIONS.map((r) => `
                      <button type="button" class="btn btn-sm ${currentRatio === r.value ? "btn-primary is-active" : ""}" data-set-ratio="${esc(r.value)}" aria-pressed="${currentRatio === r.value}">${esc(r.label)}</button>
                    `).join("")}
                  </div>
                  <input type="text" class="make-image-input make-image-ratio-input" id="batch-ratio-input" value="${esc(currentRatio)}" pattern="^\\d+(\\.\\d+)?:\\d+(\\.\\d+)?$" placeholder="宽:高" aria-label="比例数值" />
                </div>
              </div>

              <!-- Collapsible: 更多设置 (More Settings) -->
              <div class="make-image-collapsible-card">
                <button type="button" class="make-image-collapsible-toggle" id="batch-toggle-more-settings" aria-expanded="${this.moreSettingsOpen}">
                  <span>更多设置</span>
                  <span class="make-image-toggle-icon">${this.moreSettingsOpen ? "▲ 收起" : "▼ 展开"}</span>
                </button>
                <div class="make-image-collapsible-body" id="batch-body-more-settings" ${this.moreSettingsOpen ? "" : "hidden"}>
                  <div class="make-image-more-list">

                    <!-- Tones -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">影调</span>
                      <button type="button" class="btn btn-sm" id="batch-btn-pick-tones">选择影调</button>
                      <div class="make-image-more-thumbs" id="batch-tones-thumbs">
                        ${selectedTones.length ? selectedTones.map((tid) => {
                          const tObj = this.getResourceInfo(tid, "tones");
                          return `
                            <div class="make-image-slot-card is-inline">
                              <div class="make-image-slot-thumb-wrap">
                                ${tObj?.image ? `<img data-hw-src="${esc(tObj.image)}" alt="${esc(tObj.name || tid)}" loading="lazy" />` : ""}
                                <span class="make-image-slot-badge">${esc(tid)}</span>
                                <button type="button" class="make-image-slot-clear" data-remove-tone="${esc(tid)}" title="移除">×</button>
                              </div>
                              <span class="make-image-slot-title">${esc(tObj?.name || tid)}</span>
                            </div>
                          `;
                        }).join("") : `<span class="make-image-picker-hint">未指定影调</span>`}
                      </div>
                    </div>

                    <!-- Moods -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">情绪</span>
                      <button type="button" class="btn btn-sm" id="batch-btn-pick-moods">选择情绪</button>
                      <input type="text" class="make-image-input make-image-moods-input" id="batch-moods-input" value="${esc(moodTextValue)}" placeholder="输入或勾选情绪，多个用逗号隔开，如：诗意，松弛，治愈" />
                    </div>

                    <!-- Whitespace -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">留白</span>
                      <div class="make-image-btn-group" role="group" aria-label="画面留白">
                        ${WHITESPACE_OPTIONS.map((w) => `
                          <button type="button" class="btn btn-sm ${whitespace === w.value ? "btn-primary is-active" : ""}" data-set-whitespace="${esc(w.value)}" aria-pressed="${whitespace === w.value}">${esc(w.label)}</button>
                        `).join("")}
                      </div>
                    </div>

                    <!-- Audience & Business Scene -->
                    <div class="make-image-duo-row">
                      <div class="make-image-inline-field">
                        <span class="make-image-more-label">目标受众</span>
                        <input type="text" class="make-image-input" id="batch-audience-input" value="${esc(audience)}" placeholder="例如：手账爱好者、都市白领" />
                      </div>
                      <div class="make-image-inline-field">
                        <span class="make-image-more-label">业务场景</span>
                        <input type="text" class="make-image-input" id="batch-business-scene-input" value="${esc(businessScene)}" placeholder="例如：小红书图文封面、文创日签" />
                      </div>
                    </div>

                    <!-- SC-021 Options -->
                    ${layoutId === "SC-021" ? `
                      <div class="make-image-more-row">
                        <span class="make-image-more-label">SC-021玩法</span>
                        <select class="make-image-select" id="batch-sc021-select">
                          ${SC021_PLAYSTYLES.map((st) => `
                            <option value="${esc(st)}" ${sc021Type === st ? "selected" : ""}>${esc(st)}</option>
                          `).join("")}
                        </select>
                      </div>
                    ` : ""}

                    <!-- SC-022 Options -->
                    ${layoutId === "SC-022" ? `
                      <div class="make-image-more-row">
                        <span class="make-image-more-label">SC-022印鉴</span>
                        <div class="make-image-inline-inputs">
                          <input type="text" class="make-image-input" id="batch-sc022-name" value="${esc(sc022Name)}" placeholder="姓名，如：林知夏" style="width:140px;" />
                          <input type="text" class="make-image-input" id="batch-sc022-pinyin" value="${esc(sc022Pinyin)}" placeholder="拼音，如：LIN ZHIXIA" style="flex:1;" />
                        </div>
                      </div>
                    ` : ""}

                  </div>
                </div>
              </div>

              <!-- Preview Table: Listed before generation -->
              <div class="batch-preview-section">
                <div class="batch-preview-head">
                  <h3 class="batch-preview-title">批量清单与状态 (${totalCount} 张)</h3>
                </div>

                <div class="batch-table-wrap">
                  <table class="batch-preview-table">
                    <thead>
                      <tr>
                        <th style="width:48px;">序号</th>
                        <th>维度内容 / 主题</th>
                        <th style="width:110px;">状态</th>
                        <th style="width:120px;">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${iterations.length === 0 ? `
                        <tr>
                          <td colspan="4" class="batch-table-empty">暂无待批量生成的项，请在上方添加主题或选择维度</td>
                        </tr>
                      ` : iterations.map((iter, idx) => {
                        const itemResult = this.getItemResult(idx, displays, isBatchGallery);
                        const rowStatus = this.getRowStatus(idx, busy, currentStep, itemResult);
                        return `
                          <tr class="batch-table-row ${rowStatus.className}">
                            <td class="batch-col-idx">#${idx + 1}</td>
                            <td class="batch-col-content">
                              <div class="batch-iter-cell">
                                ${iter.sampleImg ? `<img data-hw-src="${esc(iter.sampleImg)}" class="batch-iter-thumb" alt="" loading="lazy" />` : ""}
                                <span class="batch-iter-label">${esc(iter.shortLabel || iter.title || iter.theme)}</span>
                              </div>
                            </td>
                            <td class="batch-col-status">
                              <span class="batch-status-badge is-${esc(rowStatus.key)}">${esc(rowStatus.label)}</span>
                            </td>
                            <td class="batch-col-action">
                              ${rowStatus.key === "failed" ? `
                                <button type="button" class="btn btn-sm batch-btn-retry" data-retry-idx="${idx}">重试</button>
                              ` : ""}
                              ${rowStatus.key === "done" && itemResult?.imageUrl ? `
                                <div class="batch-row-actions">
                                  <a href="${esc(itemResult.imageUrl)}" download="batch-${idx + 1}.webp" class="btn btn-sm batch-btn-dl" title="下载此图">下载</a>
                                  <button type="button" class="btn btn-sm batch-btn-publish" data-publish-idx="${idx}" title="发布晒图">晒图</button>
                                </div>
                              ` : ""}
                              ${rowStatus.key === "waiting" || rowStatus.key === "generating" ? `
                                <span class="batch-action-idle">-</span>
                              ` : ""}
                            </td>
                          </tr>
                        `;
                      }).join("")}
                    </tbody>
                  </table>
                </div>
              </div>

              <!-- Bottom Bar: Cost + Action -->
              <div class="batch-action-bar">
                <div class="batch-cost-wrap">
                  ${this.renderCostHtml(totalCount)}
                  ${busy ? `<span class="batch-busy-status">正在生成第 ${currentStep} / ${totalSteps} 张...</span>` : ""}
                </div>

                <div class="batch-btn-wrap">
                  ${busy ? `
                    <button type="button" class="btn btn-sm batch-stop-btn" id="batch-btn-stop">停止</button>
                  ` : `
                    <button type="button" class="make-image-run-btn" id="batch-btn-start" ${totalCount === 0 ? "disabled" : ""}>开始批量生成</button>
                  `}
                </div>
              </div>

            </div>
          </form>

          <!-- Results Section (when completed items exist) -->
          ${results.length > 0 ? `
            <div class="make-image-results-section batch-results-section">
              <div class="make-image-results-head">
                <h2>批量生成结果 (${results.length})</h2>
                <button type="button" class="btn btn-sm" id="batch-btn-download-all">全部下载</button>
              </div>

              <div class="make-image-results-grid">
                ${results.map((res, index) => `
                  <figure class="make-image-result-card" data-result-idx="${index}">
                    <div class="make-image-result-frame">
                      <img data-hw-src="${esc(res.imageUrl)}" alt="${esc(res.title || `批量图片 #${index + 1}`)}" loading="lazy" />
                    </div>
                    <figcaption class="make-image-result-caption">
                      <strong class="make-image-result-title" title="${esc(res.title || "")}">${esc(res.title || `图片 #${index + 1}`)}</strong>
                      <div class="make-image-result-actions">
                        <a href="${esc(res.imageUrl)}" download="handraw-batch-${index + 1}.webp" class="btn btn-sm">下载图片</a>
                        <button type="button" class="btn btn-sm btn-publish" data-res-pub-idx="${index}">晒图分享</button>
                      </div>
                    </figcaption>
                  </figure>
                `).join("")}
              </div>
            </div>
          ` : ""}

        </div>
      `;

      if (typeof host.querySelectorAll === "function") {
        this.bindEvents(host, p, iterations);
      }

      // Trigger lazy image loader if available
      if (global.HANDRAW_SHARED?.triggerImageLoaders) {
        global.HANDRAW_SHARED.triggerImageLoaders(this.hostElement);
      }
    }

    getItemResult(rowIndex, displays, isBatchGallery) {
      if (!displays || !displays.length) return null;
      if (isBatchGallery) {
        const gal = displays.find((d) => d.data?.kind === "batch_gallery") || displays[0];
        return gal?.data?.items?.[rowIndex] || null;
      }
      const dn = displays[rowIndex];
      return dn?.data?.items?.[0] || null;
    }

    getRowStatus(rowIndex, busy, currentStep, itemResult) {
      if (busy) {
        if (currentStep === rowIndex + 1) {
          return { key: "generating", label: "生成中", className: "is-generating" };
        }
        if (currentStep > rowIndex + 1) {
          if (itemResult?.imageUrl) {
            return { key: "done", label: "完成", className: "is-done" };
          }
          return { key: "failed", label: "失败", className: "is-failed" };
        }
        return { key: "waiting", label: "等待", className: "is-waiting" };
      }

      if (itemResult?.imageUrl) {
        return { key: "done", label: "完成", className: "is-done" };
      }
      if (itemResult && !itemResult.imageUrl) {
        return { key: "failed", label: "失败", className: "is-failed" };
      }
      return { key: "waiting", label: "等待", className: "is-waiting" };
    }

    bindEvents(root, parts, iterations) {
      const { loop, skill, ctrl, asset, text } = parts;

      const markDirty = () => {
        if (this.actions?.markDirtyAndRender) {
          this.actions.markDirtyAndRender();
        }
      };

      // 1. Batch Mode Switching
      root.querySelectorAll("[data-set-loop-mode]").forEach((btn) => {
        btn.onclick = () => {
          const mode = btn.getAttribute("data-set-loop-mode");
          if (!mode || loop.data.loopMode === mode) return;
          loop.data.loopMode = mode;
          markDirty();
        };
      });

      // 2. Output Generation Mode
      root.querySelectorAll("[data-set-mode]").forEach((btn) => {
        btn.onclick = () => {
          const mode = btn.getAttribute("data-set-mode");
          if (!mode) return;
          ctrl.data.mode = mode;
          const opt = OUTPUT_MODE_OPTIONS.find((o) => o.id === mode);
          if (opt?.defaultRatio) ctrl.data.ratio = opt.defaultRatio;
          markDirty();
        };
      });

      // 3. Fusion Toggle
      const btnSingle = root.querySelector("#batch-mode-single");
      if (btnSingle) {
        btnSingle.onclick = () => {
          if (!skill.data.fusion) return;
          skill.data.fusion = false;
          skill.data.style2 = "";
          markDirty();
        };
      }
      const btnFusion = root.querySelector("#batch-mode-fusion");
      if (btnFusion) {
        btnFusion.onclick = () => {
          if (skill.data.fusion) return;
          skill.data.fusion = true;
          if (!skill.data.style2 && skill.data.style1) {
            skill.data.style2 = skill.data.style1;
          }
          markDirty();
        };
      }

      // 4. Fixed Card Pickers
      root.querySelectorAll("[data-pick-kind]").forEach((card) => {
        card.onclick = (e) => {
          if (e.target.closest("[data-clear-kind]")) return;
          const kind = card.getAttribute("data-pick-kind");
          if (kind === "style1" || kind === "style2" || kind === "layout" || kind === "color") {
            this.actions?.openAssetPicker?.({ kind, field: kind === "color" ? "colors" : kind });
          }
        };
      });

      // Clear buttons on fixed cards
      root.querySelectorAll("[data-clear-kind]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const kind = btn.getAttribute("data-clear-kind");
          if (kind === "style1") skill.data.style1 = "";
          else if (kind === "style2") skill.data.style2 = "";
          else if (kind === "layout") skill.data.layout = "";
          else if (kind === "color") skill.data.colors = [];
          markDirty();
        };
      });

      // 5. Dynamic Row 3 Inputs
      // (a) Prompts mode
      const promptsInput = root.querySelector("#batch-prompts-input");
      if (promptsInput) {
        promptsInput.oninput = () => {
          loop.data.promptListText = promptsInput.value;
          // Re-render preview & cost without losing focus
          this.updatePreviewAndCost(root);
        };
        promptsInput.onblur = () => {
          loop.data.promptListText = promptsInput.value;
          markDirty();
        };
      }

      // Fission button trigger
      const btnFission = root.querySelector("#batch-btn-fission");
      if (btnFission) {
        btnFission.onclick = () => {
          this.openFissionModal(root, parts);
        };
      }

      // (b) Styles mode
      const btnPickStyles = root.querySelector("#batch-btn-pick-styles");
      if (btnPickStyles) {
        btnPickStyles.onclick = () => {
          this.actions?.openLoopMultiPicker?.("styles");
        };
      }
      root.querySelectorAll("[data-remove-style]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const sid = btn.getAttribute("data-remove-style");
          if (!sid) return;
          loop.data.styleIds = (loop.data.styleIds || []).filter((s) => s !== sid);
          markDirty();
        };
      });

      // (c) Layouts mode
      const btnPickLayouts = root.querySelector("#batch-btn-pick-layouts");
      if (btnPickLayouts) {
        btnPickLayouts.onclick = () => {
          this.actions?.openLoopMultiPicker?.("layouts");
        };
      }
      root.querySelectorAll("[data-remove-layout]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const lid = btn.getAttribute("data-remove-layout");
          if (!lid) return;
          loop.data.layoutIds = (loop.data.layoutIds || []).filter((l) => l !== lid);
          markDirty();
        };
      });

      // (d) Assets mode
      const btnPickAssets = root.querySelector("#batch-btn-pick-assets");
      if (btnPickAssets) {
        btnPickAssets.onclick = () => {
          this.actions?.openReferencePicker?.();
        };
      }
      root.querySelectorAll("[data-remove-asset-idx]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const idx = Number(btn.getAttribute("data-remove-asset-idx"));
          if (isNaN(idx) || !asset?.data?.items) return;
          asset.data.items.splice(idx, 1);
          markDirty();
        };
      });

      // Unified theme input (for styles, layouts, assets)
      const unifiedInput = root.querySelector("#batch-unified-theme-input");
      if (unifiedInput && text) {
        unifiedInput.oninput = () => {
          text.data.text = unifiedInput.value;
          this.updatePreviewAndCost(root);
        };
        unifiedInput.onblur = () => {
          text.data.text = unifiedInput.value;
          markDirty();
        };
      }

      // 6. Ratio Buttons & Inline Input
      root.querySelectorAll("[data-set-ratio]").forEach((btn) => {
        btn.onclick = () => {
          const ratio = btn.getAttribute("data-set-ratio");
          if (!ratio) return;
          ctrl.data.ratio = ratio;
          markDirty();
        };
      });

      const ratioInput = root.querySelector("#batch-ratio-input");
      if (ratioInput) {
        ratioInput.onchange = () => {
          const val = ratioInput.value.trim();
          if (/^\d+(\.\d+)?:\\d+(\\.\d+)?$/.test(val)) {
            const parts = val.split(":").map(Number);
            if (parts[0] > 0 && parts[1] > 0) {
              ctrl.data.ratio = val;
              markDirty();
              return;
            }
          }
          ratioInput.value = ctrl.data.ratio || "3:4";
        };
      }

      // 7. More Settings Toggle
      const toggleMore = root.querySelector("#batch-toggle-more-settings");
      const bodyMore = root.querySelector("#batch-body-more-settings");
      if (toggleMore && bodyMore) {
        toggleMore.onclick = () => {
          this.moreSettingsOpen = !this.moreSettingsOpen;
          toggleMore.setAttribute("aria-expanded", String(this.moreSettingsOpen));
          bodyMore.hidden = !this.moreSettingsOpen;
          const icon = toggleMore.querySelector(".make-image-toggle-icon");
          if (icon) icon.textContent = this.moreSettingsOpen ? "▲ 收起" : "▼ 展开";
        };
      }

      // Tones picker button
      const btnPickTones = root.querySelector("#batch-btn-pick-tones");
      if (btnPickTones) {
        btnPickTones.onclick = () => {
          this.actions?.openAssetPicker?.({ kind: "tone", field: "tones" });
        };
      }
      root.querySelectorAll("[data-remove-tone]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const tid = btn.getAttribute("data-remove-tone");
          skill.data.tones = (skill.data.tones || []).filter((t) => t !== tid);
          markDirty();
        };
      });

      // Moods picker button & text input
      const btnPickMoods = root.querySelector("#batch-btn-pick-moods");
      if (btnPickMoods) {
        btnPickMoods.onclick = () => {
          this.actions?.openAssetPicker?.({ kind: "mood", field: "moods" });
        };
      }
      const moodsInput = root.querySelector("#batch-moods-input");
      if (moodsInput) {
        moodsInput.onchange = () => {
          const parsed = parseMoodsText(moodsInput.value, this.getKnownPresetMoods());
          skill.data.moods = parsed.moods;
          skill.data.customMood = parsed.customMood;
          markDirty();
        };
      }

      // Whitespace buttons
      root.querySelectorAll("[data-set-whitespace]").forEach((btn) => {
        btn.onclick = () => {
          const val = btn.getAttribute("data-set-whitespace");
          skill.data.whitespace = val || "";
          markDirty();
        };
      });

      // Audience & Business Scene
      const audienceInput = root.querySelector("#batch-audience-input");
      if (audienceInput) {
        audienceInput.onchange = () => {
          skill.data.audience = audienceInput.value.trim();
          markDirty();
        };
      }
      const sceneInput = root.querySelector("#batch-business-scene-input");
      if (sceneInput) {
        sceneInput.onchange = () => {
          skill.data.businessScene = sceneInput.value.trim();
          markDirty();
        };
      }

      // SC-021 & SC-022
      const sc021Select = root.querySelector("#batch-sc021-select");
      if (sc021Select) {
        sc021Select.onchange = () => {
          skill.data.sc021Type = sc021Select.value;
          markDirty();
        };
      }
      const sc022Name = root.querySelector("#batch-sc022-name");
      if (sc022Name) {
        sc022Name.onchange = () => {
          skill.data.sc022Name = sc022Name.value.trim();
          markDirty();
        };
      }
      const sc022Pinyin = root.querySelector("#batch-sc022-pinyin");
      if (sc022Pinyin) {
        sc022Pinyin.onchange = () => {
          skill.data.sc022Pinyin = sc022Pinyin.value.trim();
          markDirty();
        };
      }

      // 8. Single Row Retry Action
      root.querySelectorAll("[data-retry-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-retry-idx"));
          if (isNaN(idx)) return;
          this.actions?.runSingleRow?.(idx);
        };
      });

      // 9. Single Row Publish Action
      root.querySelectorAll("[data-publish-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-publish-idx"));
          const displays = this.context?.displays || [];
          const isBatchGallery = displays.some((d) => d.data?.kind === "batch_gallery");
          const targetNode = isBatchGallery
            ? (displays.find((d) => d.data?.kind === "batch_gallery") || displays[0])
            : displays[idx];
          if (targetNode) {
            this.actions?.openPublish?.(targetNode);
          }
        };
      });

      // 10. Start Batch Generation Button
      const btnStart = root.querySelector("#batch-btn-start");
      if (btnStart) {
        btnStart.onclick = async () => {
          const count = iterations.length;
          if (count === 0) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("请先添加要批量生成的项（文案、画风、图型或图参）");
            return;
          }

          // Secondary confirmation when count > 20
          if (count > 20) {
            const cost = this.calculateCost(count);
            const costDesc = cost.loggedIn
              ? `预计消耗 ${cost.totalCost} 积分（其中免费额度 ${cost.freeCount} 张）`
              : "预计批量出图超20张";
            const confirmMsg = `本次将批量生成 ${count} 张图片，${costDesc}。确认开始批量生成吗？`;
            const ok = typeof window.confirm === "function" ? window.confirm(confirmMsg) : true;
            if (!ok) return;
          }

          this.actions?.run?.();
        };
      }

      // 11. Stop Batch Generation Button
      const btnStop = root.querySelector("#batch-btn-stop");
      if (btnStop) {
        btnStop.onclick = () => {
          this.actions?.cancel?.();
        };
      }

      // 12. Download All Button
      const btnDownloadAll = root.querySelector("#batch-btn-download-all");
      if (btnDownloadAll) {
        btnDownloadAll.onclick = async () => {
          const results = this.context?.results || [];
          if (!results.length) return;
          btnDownloadAll.disabled = true;
          btnDownloadAll.textContent = "正在下载…";
          for (let i = 0; i < results.length; i++) {
            const r = results[i];
            if (!r?.imageUrl) continue;
            const a = document.createElement("a");
            a.href = r.imageUrl;
            a.download = `handraw-batch-${i + 1}.webp`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            await new Promise((resolve) => setTimeout(resolve, 350));
          }
          btnDownloadAll.disabled = false;
          btnDownloadAll.textContent = "全部下载";
        };
      }

      // 13. Result card publish buttons
      root.querySelectorAll("[data-res-pub-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-res-pub-idx"));
          const res = (this.context?.results || [])[idx];
          if (res?.node) {
            this.actions?.openPublish?.(res.node);
          }
        };
      });
    }

    updatePreviewAndCost(root) {
      const iterations = this.resolveIterations();
      const totalCount = iterations.length;

      // Update cost text
      const costWrap = root.querySelector(".batch-cost-wrap");
      if (costWrap) {
        costWrap.innerHTML = this.renderCostHtml(totalCount);
      }

      // Update start button
      const btnStart = root.querySelector("#batch-btn-start");
      if (btnStart) {
        btnStart.disabled = totalCount === 0;
      }

      // Update table title
      const title = root.querySelector(".batch-preview-title");
      if (title) {
        title.textContent = `批量清单与状态 (${totalCount} 张)`;
      }
    }

    openFissionModal(root, parts) {
      const S = global.HANDRAW_SHARED;
      if (!S?.openModal) return;

      const seedDefault = (parts.text?.data?.text || "").trim() ||
        (parts.loop.data.promptListText || "").split(/\r?\n/)[0]?.trim() ||
        "都市慢生活与手绘手账";

      let currentStrategy = "daily_quote";
      let currentCount = 10;
      let generatedItems = [];
      let sourceTag = "model";

      S.openModal({
        title: "从母题裂变扩写主题",
        sizeClass: "modal-md",
        html: `
          <div class="batch-fission-modal" style="display:flex;flex-direction:column;gap:14px;">
            <div class="make-image-field-wrap">
              <label class="make-image-field-label" for="fission-modal-seed">母题</label>
              <input type="text" class="make-image-input" id="fission-modal-seed" value="${esc(seedDefault)}" placeholder="输入核心创作母题，例如：都市慢生活与手绘手账" />
            </div>

            <div class="make-image-field-wrap">
              <label class="make-image-field-label">裂变策略</label>
              <div class="make-image-btn-group" id="fission-strategy-group" role="group">
                ${FISSION_STRATEGIES.map((s) => `
                  <button type="button" class="btn btn-sm ${currentStrategy === s.id ? "btn-primary is-active" : ""}" data-fiss-strat="${esc(s.id)}">${esc(s.label)}</button>
                `).join("")}
              </div>
              <div id="fission-custom-wrap" style="display:none;margin-top:6px;">
                <input type="text" class="make-image-input" id="fission-custom-strategy" placeholder="输入自定义裂变角度，例如：四季时令节气风物" />
              </div>
            </div>

            <div class="make-image-field-wrap">
              <label class="make-image-field-label" for="fission-modal-count">扩写条数（1-50 条）</label>
              <input type="number" class="make-image-input" id="fission-modal-count" min="1" max="50" value="10" style="width:120px;" />
            </div>

            <div style="display:flex;justify-content:flex-end;gap:8px;">
              <button type="button" class="btn btn-sm btn-primary" id="fission-submit-btn">开始扩写</button>
            </div>

            <!-- Result Box -->
            <div id="fission-result-box" style="display:none;border-top:1px solid var(--line-soft);padding-top:12px;">
              <div id="fission-source-banner" style="display:none;padding:6px 10px;background:#fef3c7;border:1px solid #fde68a;border-radius:6px;font-size:12px;color:#92400e;margin-bottom:8px;">
                未使用 AI 扩写，已按模板生成
              </div>
              <div class="make-image-field-label" style="margin-bottom:6px;">扩写结果预览 (<span id="fission-result-count">0</span> 条)</div>
              <div id="fission-result-list" style="max-height:160px;overflow-y:auto;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:6px;padding:8px 12px;font-size:12px;line-height:1.6;display:flex;flex-direction:column;gap:4px;"></div>

              <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px;">
                <button type="button" class="btn btn-sm" id="fission-append-btn">追加到列表</button>
                <button type="button" class="btn btn-sm btn-primary" id="fission-replace-btn">替换列表</button>
              </div>
            </div>
          </div>
        `,
        onMount(modalRoot) {
          const seedInput = modalRoot.querySelector("#fission-modal-seed");
          const stratGroup = modalRoot.querySelector("#fission-strategy-group");
          const customWrap = modalRoot.querySelector("#fission-custom-wrap");
          const customInput = modalRoot.querySelector("#fission-custom-strategy");
          const countInput = modalRoot.querySelector("#fission-modal-count");
          const submitBtn = modalRoot.querySelector("#fission-submit-btn");
          const resultBox = modalRoot.querySelector("#fission-result-box");
          const sourceBanner = modalRoot.querySelector("#fission-source-banner");
          const resultCount = modalRoot.querySelector("#fission-result-count");
          const resultList = modalRoot.querySelector("#fission-result-list");
          const appendBtn = modalRoot.querySelector("#fission-append-btn");
          const replaceBtn = modalRoot.querySelector("#fission-replace-btn");

          stratGroup.querySelectorAll("[data-fiss-strat]").forEach((btn) => {
            btn.onclick = () => {
              stratGroup.querySelectorAll("[data-fiss-strat]").forEach((b) => b.classList.remove("btn-primary", "is-active"));
              btn.classList.add("btn-primary", "is-active");
              currentStrategy = btn.getAttribute("data-fiss-strat");
              customWrap.style.display = currentStrategy === "custom" ? "block" : "none";
            };
          });

          submitBtn.onclick = async () => {
            const seedVal = seedInput.value.trim();
            if (!seedVal) {
              if (S.toast) S.toast("请输入母题");
              seedInput.focus();
              return;
            }
            const cntVal = Math.max(1, Math.min(50, Number(countInput.value) || 10));
            const customVal = currentStrategy === "custom" ? customInput.value.trim() : "";

            submitBtn.disabled = true;
            submitBtn.textContent = "AI 思考扩写中…";

            try {
              const resp = await fetch("/api/studio/fission", {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  seed: seedVal,
                  strategy: currentStrategy,
                  customStrategy: customVal,
                  count: cntVal
                })
              });
              const data = await resp.json();
              if (!resp.ok || !data.ok) {
                throw new Error(data.error || `HTTP ${resp.status}`);
              }

              generatedItems = Array.isArray(data.items) ? data.items : [];
              sourceTag = data.source || "model";

              resultBox.style.display = "block";
              sourceBanner.style.display = sourceTag === "template" ? "block" : "none";
              resultCount.textContent = String(generatedItems.length);
              resultList.innerHTML = generatedItems.map((item, idx) => `
                <div>#${idx + 1} ${esc(item)}</div>
              `).join("");

            } catch (err) {
              if (S.toast) S.toast(`扩写失败：${err.message || err}`);
            } finally {
              submitBtn.disabled = false;
              submitBtn.textContent = "开始扩写";
            }
          };

          const applyItems = (replace) => {
            if (!generatedItems.length) return;
            const existing = (parts.loop.data.promptListText || "").trim();
            if (replace || !existing) {
              parts.loop.data.promptListText = generatedItems.join("\n");
            } else {
              parts.loop.data.promptListText = `${existing}\n${generatedItems.join("\n")}`;
            }
            S.closeModal();
            if (this.actions?.markDirtyAndRender) {
              this.actions.markDirtyAndRender();
            }
            if (S.toast) {
              S.toast(replace ? `已替换为 ${generatedItems.length} 条主题！` : `已追加 ${generatedItems.length} 条主题！`);
            }
          };

          appendBtn.onclick = () => applyItems(false);
          replaceBtn.onclick = () => applyItems(true);
        }
      });
    }
  }

  global.HandrawBatchCreate = new BatchCreateController();

})(typeof window !== "undefined" ? window : globalThis);
