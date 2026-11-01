/**
 * Handraw Web Studio - Batch Creation Component (Phase 3b-2 & Phase 3b-4 Redesign)
 *
 * Requirements:
 * - Operates directly on quick batch workflow nodes:
 *   skill_params, text_input, asset, loop, output_control.
 * - No custom data structures; 100% two-way fidelity with canvas.
 * - Row 1: 生成方式 (图文/纯图/海报) + 画风模式 (单画风/双画风融合) in ONE row, left-aligned in order.
 * - Row 2: Fixed parameter picker cards: 画风 / 角色画风, 场景画风 (when fusion), 主题色.
 * - 套图规划 (Set Planning):
 *   - 规划行 A: 母题 (seed) + 张数 (1-20, default 6) + 图型策略【固定图型 / AI 推荐图型】 + 【AI 规划这套图】按钮.
 *   - 规划行 B (固定图型): 图型【选择图型】按钮 + 已选图型卡 (same row).
 *   - 规划行 B (AI 推荐图型): 图型要求 (文本框，例如「前 3 张分镜、后面图鉴，不要封面图」).
 *   - 编辑区 (固定图型): 单个文本框，每行一条主题，用户直接改；不出现逐张行.
 *   - 编辑区 (AI 推荐图型): 逐张行表格：#1 [主题输入框] [图型下拉] [删除]，以及【＋ 添加一张】按钮.
 * - Row 4: 画幅预设按钮 + 比例数值输入框 (fixed regex without double escaping).
 * - 更多设置 (折叠): 影调、情绪、留白、受众、业务场景、SC-021/SC-022.
 * - 底部栏与费用: 统一计算 Math.min(200, iterations.length * perIterCount)；二次确认 (>20) 也用该张数与费用.
 * - 规划与裂变回调中的 this 正确绑定为控制器实例 (self).
 * - 新增与修改界面不包含任何 emoji.
 */
(function (global) {
  "use strict";

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
      this.planNotice = "";
      this.isPlanning = false;
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

    renderRowLayoutButtonHtml(row, idx, globalLayoutId) {
      const catalog = this.context?.catalog;
      const rMap = (catalog && catalog.resourceMap) || new Map();
      const hasSpecific = Boolean(row && row.layout && String(row.layout).trim());
      const specificId = hasSpecific ? String(row.layout).trim() : "";
      const effectiveId = specificId || globalLayoutId || "SC-021";
      const res = effectiveId ? (rMap.get(effectiveId) || catalog?.layouts?.find((l) => l.id === effectiveId)) : null;
      const thumbUrl = res?.image || "/images/layouts/social-cards/SC-021.webp";
      const codeText = effectiveId;
      const nameText = res ? (res.name_zh || res.name || effectiveId) : (hasSpecific ? specificId : "默认图型");
      const btnTitle = hasSpecific ? `图型版式：${effectiveId} ${nameText}（点击更换）` : `跟随全局图型 ${effectiveId}（点击更换）`;
      const ariaLabel = hasSpecific ? `图型版式：${effectiveId} ${nameText}` : `跟随全局图型 ${effectiveId} ${nameText}`;

      return `
        <button type="button" class="btn batch-row-layout-btn" data-pick-layout-idx="${idx}" title="${esc(btnTitle)}" aria-label="${esc(ariaLabel)}">
          <span class="batch-row-layout-thumb-wrap">
            <img data-hw-src="${esc(thumbUrl)}" alt="${esc(nameText)}" class="batch-row-layout-thumb" loading="lazy" />
          </span>
          <span class="batch-row-layout-info">
            <span class="batch-row-layout-code">${esc(codeText)}</span>
            <span class="batch-row-layout-name">${esc(nameText)}</span>
          </span>
        </button>
      `;
    }

    renderLayoutSelectOptions(selectedLayoutId) {
      const catalog = this.context?.catalog;
      const layouts = (catalog && Array.isArray(catalog.layouts) ? catalog.layouts : [])
        .filter((l) => l && l.id);

      const normSel = String(selectedLayoutId || "").trim().toUpperCase();
      let html = `<option value="">默认图型（跟随全局）</option>`;
      let foundSelected = false;

      layouts.forEach((l) => {
        const lid = esc(l.id);
        const lname = esc(l.name_zh || l.name || l.id);
        const isSel = normSel === String(l.id).toUpperCase();
        if (isSel) foundSelected = true;
        html += `<option value="${lid}" ${isSel ? "selected" : ""}>${lid} ${lname}</option>`;
      });

      if (normSel && !foundSelected) {
        html += `<option value="${esc(normSel)}" selected>${esc(normSel)}</option>`;
      }

      return html;
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

      // M1: ctrl.data.count folded into batchCount if > 1, then reset to 1
      if (p.ctrl?.data && Number(p.ctrl.data.count) > 1) {
        const rawCtrlCount = Math.round(Number(p.ctrl.data.count));
        const currentBatchCount = Math.max(1, Math.min(20, Number(ld.batchCount) || 6));
        const foldedCount = Math.max(1, Math.min(20, currentBatchCount * rawCtrlCount));
        p.loop.data.batchCount = foldedCount;
        p.ctrl.data.count = 1;
        this.planNotice = `已按每行一张折算，共 ${foldedCount} 张`;
      }

      // Batch set planning state
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

      // Set Planning specifics
      const batchLayoutMode = ld.batchLayoutMode || (Array.isArray(ld.batchRows) && ld.batchRows.length > 0 ? "ai" : "fixed");
      const batchSeed = ld.batchSeed != null ? ld.batchSeed : (td.text || "");
      const batchCount = Math.max(1, Math.min(20, Number(ld.batchCount) || 6));
      const batchLayoutReq = ld.batchLayoutReq || "";
      const batchRows = Array.isArray(ld.batchRows) ? ld.batchRows : [];
      const promptListText = typeof ld.promptListText === "string" ? ld.promptListText : "";
      const globalAssetItems = Array.isArray(this.parts?.asset?.data?.items) ? this.parts.asset.data.items : [];

      // M1: Single truth - each iteration generates 1 image in batch set planning
      const perIterCount = 1;
      const iterations = this.resolveIterations();
      const totalCount = Math.min(200, iterations.length * perIterCount);

      const busy = Boolean(this.context?.busy);
      const displays = Array.isArray(this.context?.displays) ? this.context.displays : [];
      const results = Array.isArray(this.context?.results) ? this.context.results : [];

      const isBatchGallery = displays.some((d) => d.data?.kind === "batch_gallery");
      let currentStep = ld.currentStep || 0;
      let totalSteps = ld.totalSteps || totalCount;
      if (busy && currentStep === 0) currentStep = 1;

      this.hostElement.innerHTML = `
        <div class="make-image-container batch-container">
          <div class="make-image-head">
            <div class="make-image-head-left">
              <h1 class="make-image-title">批量</h1>
              <p class="make-image-lede">套图规划批量出图：统一画风与母题，AI 规划每张主题与图型，支持自由微调。</p>
            </div>
          </div>

          <form class="make-image-form" novalidate onsubmit="return false;">
            <div class="make-image-main-grid">

              <!-- Row 1: Output Mode (Left) + Fusion Toggle in ONE Row -->
              <div class="make-image-top-row batch-top-row">
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

              <!-- Row 2: Fixed Parameter Picker Cards (Style1, Style2 if fusion, Color) -->
              <div class="make-image-pickers-row batch-pickers-row ${isFusion ? "has-style2" : ""}">
                ${this.renderPickerSlot("style1", isFusion ? "角色画风" : "画风", style1Obj, true)}
                ${isFusion ? this.renderPickerSlot("style2", "场景画风", style2Obj, true) : ""}
                ${this.renderPickerSlot("color", "主题色", colorObj, true)}
              </div>

              ${isFusion ? `
                <div class="make-image-style-note" role="note">角色画风决定人物与主体的画法，场景画风决定背景与环境</div>
              ` : ""}

              <!-- 套图规划 (Set Planning Section) -->
              <div class="batch-plan-card">
                <!-- 规划行 A: 母题 + 张数 + 图型策略 + AI 规划按钮 -->
                <div class="batch-plan-row-a">
                  <div class="batch-seed-wrap">
                    <span class="make-image-field-label">母题</span>
                    <input type="text" class="make-image-input batch-seed-input" id="batch-seed-input" placeholder="输入这套图的创作母题（如：都市慢生活与手绘手账）..." value="${esc(batchSeed)}" />
                  </div>

                  <div class="batch-count-wrap">
                    <span class="make-image-field-label">张数</span>
                    <input type="number" class="make-image-input batch-count-input" id="batch-count-input" min="1" max="20" value="${batchCount}" />
                  </div>

                  <div class="batch-strategy-wrap">
                    <span class="make-image-field-label">图型策略</span>
                    <div class="make-image-btn-group" role="group" aria-label="图型策略">
                      <button type="button" class="btn btn-sm ${batchLayoutMode === "fixed" ? "btn-primary is-active" : ""}" id="batch-strategy-fixed" aria-pressed="${batchLayoutMode === "fixed"}">固定图型</button>
                      <button type="button" class="btn btn-sm ${batchLayoutMode === "ai" ? "btn-primary is-active" : ""}" id="batch-strategy-ai" aria-pressed="${batchLayoutMode === "ai"}">AI 推荐图型</button>
                    </div>
                  </div>

                  <div class="batch-plan-action-wrap">
                    <button type="button" class="btn btn-sm btn-primary batch-plan-trigger" id="batch-btn-plan" ${busy ? "disabled" : ""}>AI 规划这套图</button>
                    ${this.planNotice ? `<span class="batch-plan-notice">${esc(this.planNotice)}</span>` : ""}
                  </div>
                </div>

                <!-- 规划行 B: 固定图型时选择图型卡；AI 推荐图型时填写图型要求 -->
                ${batchLayoutMode === "fixed" ? `
                  <div class="batch-plan-row-b batch-fixed-layout-row">
                    <span class="make-image-field-label">固定图型</span>
                    <button type="button" class="btn btn-sm btn-primary" id="batch-btn-pick-fixed-layout">选择图型</button>
                    <div class="batch-fixed-layout-card-wrap">
                      ${layoutObj?.id ? `
                        <div class="make-image-slot-card is-inline batch-chip" data-pick-kind="layout">
                          <div class="make-image-slot-thumb-wrap">
                            ${layoutObj.image ? `<img data-hw-src="${esc(layoutObj.image)}" alt="${esc(layoutObj.name || layoutObj.id)}" loading="lazy" />` : ""}
                            <button type="button" class="make-image-slot-clear" data-clear-kind="layout" title="清除">×</button>
                          </div>
                          <div class="make-image-slot-meta">
                            <span class="make-image-slot-code">${esc(layoutObj.id)}</span>
                            <span class="make-image-slot-title">${esc(layoutObj.name || layoutObj.id)}</span>
                          </div>
                        </div>
                      ` : `<span class="make-image-picker-hint">未选图型（将使用默认版式）</span>`}
                    </div>
                  </div>
                ` : `
                  <div class="batch-plan-row-b batch-ai-layout-row">
                    <span class="make-image-field-label">图型要求</span>
                    <input type="text" class="make-image-input batch-layout-req-input" id="batch-layout-req-input" placeholder="例如：前 3 张分镜、后面图鉴，不要封面图（可留空）" value="${esc(batchLayoutReq)}" />
                  </div>
                `}

                <!-- 编辑区: 固定图型为一个文本框；AI 推荐图型为逐张表格 -->
                ${batchLayoutMode === "fixed" ? `
                  <div class="batch-edit-area batch-fixed-edit-area">
                    <div class="batch-field-head">
                      <span class="make-image-field-label">主题列表（每行一条，直接编辑）</span>
                      <button type="button" class="btn btn-sm batch-fission-trigger" id="batch-btn-fission">从母题裂变</button>
                    </div>
                    <textarea class="make-image-textarea batch-prompts-textarea" id="batch-prompts-input" rows="5" placeholder="每行输入一个创作主题，每行将生成一张独立画面...">${esc(promptListText)}</textarea>
                  </div>
                ` : `
                  <div class="batch-edit-area batch-ai-edit-area">
                    <div class="batch-field-head">
                      <span class="make-image-field-label">逐张主题与图型调整</span>
                      <button type="button" class="btn btn-sm batch-fission-trigger" id="batch-btn-fission-ai">从母题裂变</button>
                    </div>
                    <div class="batch-table-wrap">
                      <table class="batch-edit-table">
                        <thead>
                          <tr>
                            <th style="width:44px;" class="batch-col-idx">序号</th>
                            <th>画面主题</th>
                            <th style="width:190px;" class="batch-col-layout">图型版式</th>
                            <th style="width:160px;" class="batch-col-refs">参考图</th>
                            <th style="width:52px;text-align:center;">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          ${batchRows.length === 0 ? `
                            <tr><td colspan="5" class="batch-table-empty">暂无主题，请点击「AI 规划这套图」或「＋ 添加一张」</td></tr>
                          ` : batchRows.map((row, idx) => {
                            const rowRefs = (row && Array.isArray(row.assetItems)) ? row.assetItems : [];
                            const isSkipGlobal = Boolean(row && row.skipGlobalRefs);
                            return `
                            <tr class="batch-edit-row" data-row-idx="${idx}">
                              <td class="batch-col-idx">#${idx + 1}</td>
                              <td>
                                <input type="text" class="make-image-input batch-row-theme-input" data-row-idx="${idx}" value="${esc(row.theme)}" placeholder="输入该张画面主题..." />
                              </td>
                              <td class="batch-col-layout">
                                ${this.renderRowLayoutButtonHtml(row, idx, sd.layout)}
                              </td>
                              <td class="batch-col-refs">
                                <div class="batch-row-refs-wrap">
                                  <div class="batch-row-refs-desktop">
                                    ${rowRefs.length === 0 ? `
                                      <button type="button" class="btn btn-sm batch-btn-pick-row-refs" data-pick-row-refs-idx="${idx}">+ 选择</button>
                                    ` : `
                                      <div class="batch-row-refs-thumbs" data-pick-row-refs-idx="${idx}" role="button" tabindex="0" title="点击调整此条参考图（共 ${rowRefs.length} 张）">
                                        ${rowRefs.slice(0, 3).map((ast, rIdx) => `
                                          <img src="${esc(ast.image)}" alt="${esc(ast.name || ast.id || `参考图 ${rIdx + 1}`)}" class="batch-row-ref-thumb" loading="lazy" />
                                        `).join("")}
                                        ${rowRefs.length < 3 ? `<span class="batch-row-refs-plus-badge" title="继续添加">+</span>` : ""}
                                      </div>
                                    `}
                                  </div>
                                  <div class="batch-row-refs-mobile">
                                    <button type="button" class="btn btn-sm batch-btn-row-refs-mobile" data-pick-row-refs-idx="${idx}">参考图：已选 ${rowRefs.length} 张</button>
                                  </div>
                                  <div class="batch-row-skip-global-wrap">
                                    <label class="batch-row-skip-global-label" title="本条生成时不使用全局参考图">
                                      <input type="checkbox" class="batch-row-skip-global-checkbox" data-row-skip-global="${idx}" ${isSkipGlobal ? "checked" : ""} />
                                      <span>不用全局</span>
                                    </label>
                                    ${isSkipGlobal ? `<span class="batch-ref-skip-badge">仅本条</span>` : ""}
                                  </div>
                                </div>
                              </td>
                              <td style="text-align:center;">
                                <button type="button" class="btn btn-sm btn-ghost batch-row-del-btn" data-del-row-idx="${idx}" title="删除此张">删除</button>
                              </td>
                            </tr>
                          `;}).join("")}
                        </tbody>
                      </table>
                    </div>
                    <div class="batch-add-row-wrap">
                      <button type="button" class="btn btn-sm" id="batch-btn-add-row">＋ 添加一张</button>
                    </div>
                  </div>
                `}
              </div>

              <!-- Row 4: Ratio Buttons + Inline Ratio Input (Defect 3 Fixed) -->
              <div class="make-image-ratio-row">
                <span class="make-image-field-label">画幅</span>
                <div class="make-image-ratio-controls">
                  <div class="make-image-btn-group" role="group" aria-label="预置比例">
                    ${RATIO_OPTIONS.map((r) => `
                      <button type="button" class="btn btn-sm ${currentRatio === r.value ? "btn-primary is-active" : ""}" data-set-ratio="${esc(r.value)}" aria-pressed="${currentRatio === r.value}">${esc(r.label)}</button>
                    `).join("")}
                  </div>
                  <input type="text" class="make-image-input make-image-ratio-input" id="batch-ratio-input" value="${esc(currentRatio)}" pattern="[0-9]+(?:\\.[0-9]+)?:[0-9]+(?:\\.[0-9]+)?" placeholder="宽:高" aria-label="比例数值" />
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
                                <button type="button" class="make-image-slot-clear" data-remove-tone="${esc(tid)}" title="移除">×</button>
                              </div>
                              <div class="make-image-slot-meta">
                                <span class="make-image-slot-code">${esc(tid)}</span>
                                <span class="make-image-slot-title">${esc(tObj?.name || tid)}</span>
                              </div>
                            </div>
                          `;
                        }).join("") : `<span class="make-image-picker-hint">未指定影调</span>`}
                      </div>
                    </div>

                    <!-- Global References -->
                    <div class="make-image-more-row" id="batch-more-row-refs">
                      <span class="make-image-more-label">参考图</span>
                      <button type="button" class="btn btn-sm" id="batch-btn-pick-global-refs">选择参考图</button>
                      <div class="make-image-more-thumbs" id="batch-global-refs-thumbs">
                        ${globalAssetItems.length ? globalAssetItems.map((ast, idx) => `
                          <div class="make-image-slot-card is-inline">
                            <div class="make-image-slot-thumb-wrap">
                              ${ast.image ? `<img data-hw-src="${esc(ast.image)}" alt="${esc(ast.name || ast.id || `参考图 ${idx + 1}`)}" loading="lazy" />` : ""}
                              <button type="button" class="make-image-slot-clear" data-remove-global-ref="${idx}" title="移除">×</button>
                            </div>
                            <div class="make-image-slot-meta">
                              <span class="make-image-slot-code">${esc(ast.id || `REF-${idx + 1}`)}</span>
                              <span class="make-image-slot-title">${esc(ast.name || ast.id || `参考图 ${idx + 1}`)}</span>
                            </div>
                          </div>
                        `).join("") : `<span class="make-image-picker-hint">未指定，可点此添加（最多 4 张）</span>`}
                      </div>
                    </div>

                    <!-- Moods -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">情绪</span>
                      <button type="button" class="btn btn-sm" id="batch-btn-pick-moods">选择情绪</button>
                      <div class="make-image-inline-inputs" style="flex:1;">
                        <input type="text" class="make-image-input" id="batch-moods-input" value="${esc(moodTextValue)}" placeholder="点击「选择情绪」或输入逗号分隔情绪词..." />
                      </div>
                    </div>

                    <!-- Whitespace -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">留白</span>
                      <div class="make-image-btn-group" role="group" aria-label="留白程度">
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
                          <td colspan="4" class="batch-table-empty">暂无待批量生成的项，请在上方规划主题或添加条目</td>
                        </tr>
                      ` : iterations.map((iter, idx) => {
                        const itemResult = this.getItemResult(idx, displays, isBatchGallery);
                        const rowStatus = this.getRowStatus(idx, busy, currentStep, itemResult);
                        const iterLayoutId = iter.layout || "";
                        const catalog = this.context?.catalog;
                        const rMap = (catalog && catalog.resourceMap) || new Map();
                        const layoutRes = iterLayoutId ? (rMap.get(iterLayoutId) || catalog?.layouts?.find((l) => l.id === iterLayoutId)) : null;
                        const layoutName = layoutRes ? (layoutRes.name_zh || layoutRes.name || iterLayoutId) : "";
                        const zoomTitle = iterLayoutId && layoutName ? `${iterLayoutId} ${layoutName}` : (iterLayoutId || iter.shortLabel || iter.title || "图型预览");

                        return `
                          <tr class="batch-table-row ${rowStatus.className}">
                            <td class="batch-col-idx">#${idx + 1}</td>
                            <td class="batch-col-content">
                              <div class="batch-iter-cell">
                                ${iter.sampleImg ? `
                                  <button type="button" class="batch-iter-thumb-btn" data-zoom-src="${esc(iter.sampleImg)}" data-zoom-title="${esc(zoomTitle)}" aria-label="放大查看${esc(zoomTitle)}">
                                    <img data-hw-src="${esc(iter.sampleImg)}" class="batch-iter-thumb" alt="${esc(zoomTitle)}" loading="lazy" />
                                  </button>
                                ` : ""}
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

              <!-- Bottom Bar: Cost + Action (Defect 2 Fixed) -->
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
      const self = this;
      const { loop, skill, ctrl, asset, text } = parts;

      const markDirty = () => {
        if (self.actions?.markDirtyAndRender) {
          self.actions.markDirtyAndRender();
        } else {
          const S = global.HANDRAW_SHARED;
          if (S?.toast) S.toast("当前操作不可用（缺少 action: markDirtyAndRender）");
        }
      };

      // 1. Output Generation Mode
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

      // 2. Fusion Toggle
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

      // 3. Fixed Card Pickers
      root.querySelectorAll("[data-pick-kind]").forEach((card) => {
        card.onclick = (e) => {
          if (e.target.closest("[data-clear-kind]")) return;
          const kind = card.getAttribute("data-pick-kind");
          if (kind === "style1" || kind === "style2" || kind === "layout" || kind === "color") {
            if (self.actions?.openAssetPicker) {
              self.actions.openAssetPicker({ kind, field: kind === "color" ? "colors" : kind });
            } else {
              const S = global.HANDRAW_SHARED;
              if (S?.toast) S.toast("当前操作不可用（缺少 action: openAssetPicker）");
            }
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

      // 4. Set Planning Controls
      // (a) Seed input
      const seedInput = root.querySelector("#batch-seed-input");
      if (seedInput) {
        seedInput.oninput = () => {
          loop.data.batchSeed = seedInput.value;
          if (text) text.data.text = seedInput.value;
        };
      }

      // (b) Count input (M1: write batchCount and enforce ctrl.count = 1)
      const countInput = root.querySelector("#batch-count-input");
      if (countInput) {
        countInput.oninput = () => {
          const val = Math.max(1, Math.min(20, Number(countInput.value) || 6));
          loop.data.batchCount = val;
          if (ctrl?.data) {
            ctrl.data.count = 1;
          }
        };
      }

      // (c) Strategy buttons (Fixed vs AI recommended)
      const btnStratFixed = root.querySelector("#batch-strategy-fixed");
      if (btnStratFixed) {
        btnStratFixed.onclick = () => {
          if (loop.data.batchLayoutMode === "fixed") return;
          // Switching from AI to Fixed: prompt confirmation if rows have varied layouts
          const rows = Array.isArray(loop.data.batchRows) ? loop.data.batchRows : [];
          if (rows.length > 0) {
            const hasCustomLayouts = rows.some((r) => r.layout && r.layout !== (skill.data.layout || ""));
            if (hasCustomLayouts) {
              const ok = typeof window.confirm === "function"
                ? window.confirm("切换到固定图型将丢失每张独立的图型设置，所有图片将使用统一图型。是否继续？")
                : true;
              if (!ok) return;
            }
            loop.data.promptListText = rows.map((r) => r.theme).filter(Boolean).join("\n");
            loop.data.batchRows = [];
          }
          loop.data.batchLayoutMode = "fixed";
          markDirty();
        };
      }

      const btnStratAi = root.querySelector("#batch-strategy-ai");
      if (btnStratAi) {
        btnStratAi.onclick = () => {
          if (loop.data.batchLayoutMode === "ai") return;
          // Switching from Fixed to AI: split promptListText lines into rows
          loop.data.batchLayoutMode = "ai";
          const rawText = typeof loop.data.promptListText === "string" ? loop.data.promptListText : "";
          const lines = rawText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
          if (lines.length > 0) {
            loop.data.batchRows = lines.map((line) => ({ theme: line, layout: skill.data.layout || "" }));
          } else {
            const cnt = Math.max(1, Math.min(20, Number(loop.data.batchCount) || 6));
            loop.data.batchRows = Array.from({ length: cnt }, () => ({ theme: "", layout: skill.data.layout || "" }));
          }
          markDirty();
        };
      }

      // (d) Pick fixed layout button in Row B
      const btnPickFixedLayout = root.querySelector("#batch-btn-pick-fixed-layout");
      if (btnPickFixedLayout) {
        btnPickFixedLayout.onclick = () => {
          if (self.actions?.openAssetPicker) {
            self.actions.openAssetPicker({ kind: "layout", field: "layout" });
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openAssetPicker）");
          }
        };
      }

      // (e) Layout requirement input
      const layoutReqInput = root.querySelector("#batch-layout-req-input");
      if (layoutReqInput) {
        layoutReqInput.oninput = () => {
          loop.data.batchLayoutReq = layoutReqInput.value;
        };
      }

      // (f) AI Planning Trigger
      const btnPlan = root.querySelector("#batch-btn-plan");
      if (btnPlan) {
        btnPlan.onclick = async () => {
          const currentMode = loop.data.batchLayoutMode || "fixed";
          const hasExisting = currentMode === "fixed"
            ? Boolean(loop.data.promptListText && loop.data.promptListText.trim())
            : (Array.isArray(loop.data.batchRows) && loop.data.batchRows.some((r) => r.theme && r.theme.trim()));

          if (hasExisting) {
            const ok = typeof window.confirm === "function"
              ? window.confirm("重新规划将覆盖当前已有的主题与图型内容，是否继续？")
              : true;
            if (!ok) return;
          }

          const seed = String(loop.data.batchSeed || text?.data?.text || "").trim();
          if (!seed) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("请先填写母题（例如：都市慢生活与手绘手账）");
            const seedEl = root.querySelector("#batch-seed-input");
            if (seedEl) seedEl.focus();
            return;
          }

          const reqBody = {
            seed,
            count: Math.max(1, Math.min(20, Number(loop.data.batchCount) || 6)),
            layoutMode: currentMode,
            fixedLayout: skill.data.layout || "",
            layoutRequirement: loop.data.batchLayoutReq || "",
            styleId: skill.data.style1 || ""
          };

          btnPlan.disabled = true;
          btnPlan.textContent = "AI 正在规划…";

          try {
            const resp = await fetch("/api/studio/batch-plan", {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(reqBody)
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
              throw new Error(data.error || `HTTP ${resp.status}`);
            }

            const items = Array.isArray(data.items) ? data.items : [];
            if (currentMode === "fixed") {
              loop.data.promptListText = items.map((it) => it.subject).join("\n");
              loop.data.batchRows = [];
            } else {
              loop.data.batchRows = items.map((it) => ({ theme: it.subject, layout: it.layout || "" }));
              loop.data.promptListText = items.map((it) => it.subject).join("\n");
            }

            if (data.source === "template") {
              self.planNotice = "未使用 AI 规划，已按模板生成";
            } else {
              self.planNotice = "";
            }

            if (data.defaultLayoutUsed && items.length > 0 && items[0].layout) {
              const defLayout = items[0].layout;
              if (skill?.data) {
                skill.data.layout = defLayout;
              }
              const defaultMsg = `未选图型，已使用默认图型 ${defLayout}`;
              self.planNotice = self.planNotice ? `${self.planNotice}（${defaultMsg}）` : defaultMsg;
            }

            markDirty();
          } catch (err) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast(`规划失败：${err.message || err}`);
          } finally {
            btnPlan.disabled = false;
            btnPlan.textContent = "AI 规划这套图";
          }
        };
      }

      // (g) Fixed layout textarea
      const promptsInput = root.querySelector("#batch-prompts-input");
      if (promptsInput) {
        promptsInput.oninput = () => {
          loop.data.promptListText = promptsInput.value;
          loop.data.batchRows = [];
          self.updatePreviewAndCost(root);
        };
        promptsInput.onblur = () => {
          loop.data.promptListText = promptsInput.value;
          markDirty();
        };
      }

      // (h) Fission button in fixed and AI edit areas
      root.querySelectorAll(".batch-fission-trigger, #batch-btn-fission, #batch-btn-fission-ai").forEach((btn) => {
        btn.onclick = () => {
          self.openFissionModal(root, parts);
        };
      });

      // (i) AI mode table events
      root.querySelectorAll(".batch-row-theme-input").forEach((inp) => {
        inp.oninput = () => {
          const idx = Number(inp.getAttribute("data-row-idx"));
          if (!Array.isArray(loop.data.batchRows) || !loop.data.batchRows[idx]) return;
          loop.data.batchRows[idx].theme = inp.value;
          loop.data.promptListText = loop.data.batchRows.map((r) => r.theme).filter(Boolean).join("\n");
          self.updatePreviewAndCost(root);
        };
        inp.onblur = () => {
          markDirty();
        };
      });

      root.querySelectorAll("[data-pick-layout-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-pick-layout-idx"));
          if (!Array.isArray(loop.data.batchRows) || !loop.data.batchRows[idx]) return;
          const currentRow = loop.data.batchRows[idx];
          const curLayout = currentRow.layout || "";

          const onPick = (pickedId) => {
            currentRow.layout = pickedId || "";
            markDirty();
          };

          if (self.actions?.openAssetPicker) {
            self.actions.openAssetPicker({
              kind: "layout",
              field: "layout",
              current: curLayout,
              title: `选择第 ${idx + 1} 张的图型`,
              onPick
            });
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openAssetPicker）");
          }
        };
      });

      root.querySelectorAll("[data-pick-row-refs-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-pick-row-refs-idx"));
          if (!Array.isArray(loop.data.batchRows) || !loop.data.batchRows[idx]) return;
          const currentRow = loop.data.batchRows[idx];
          const curRefs = Array.isArray(currentRow.assetItems) ? currentRow.assetItems : [];

          if (self.actions?.openReferencePicker) {
            self.actions.openReferencePicker({
              items: curRefs,
              currentRefs: curRefs,
              maxCount: 3,
              title: `第 ${idx + 1} 张参考图（最多 3 张）`,
              onConfirm: (selectedItems) => {
                currentRow.assetItems = selectedItems;
                markDirty();
              }
            });
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openReferencePicker）");
          }
        };
      });

      root.querySelectorAll("[data-row-skip-global]").forEach((chk) => {
        chk.onchange = () => {
          const idx = Number(chk.getAttribute("data-row-skip-global"));
          if (!Array.isArray(loop.data.batchRows) || !loop.data.batchRows[idx]) return;
          loop.data.batchRows[idx].skipGlobalRefs = Boolean(chk.checked);
          markDirty();
        };
      });

      root.querySelectorAll("[data-del-row-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-del-row-idx"));
          if (!Array.isArray(loop.data.batchRows)) return;
          loop.data.batchRows.splice(idx, 1);
          loop.data.promptListText = loop.data.batchRows.map((r) => r.theme).filter(Boolean).join("\n");
          markDirty();
        };
      });

      const btnAddRow = root.querySelector("#batch-btn-add-row");
      if (btnAddRow) {
        btnAddRow.onclick = () => {
          if (!Array.isArray(loop.data.batchRows)) loop.data.batchRows = [];
          loop.data.batchRows.push({
            theme: "",
            layout: skill.data.layout || "",
            assetItems: [],
            skipGlobalRefs: false
          });
          markDirty();
        };
      }

      // 5. Ratio Buttons & Inline Input (Defect 3 Fixed: /^\d+(?:\.\d+)?:\d+(?:\.\d+)?$/)
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
          if (/^\d+(?:\.\d+)?:\d+(?:\.\d+)?$/.test(val)) {
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

      // 6. More Settings Toggle
      const toggleMore = root.querySelector("#batch-toggle-more-settings");
      const bodyMore = root.querySelector("#batch-body-more-settings");
      if (toggleMore && bodyMore) {
        toggleMore.onclick = () => {
          self.moreSettingsOpen = !self.moreSettingsOpen;
          toggleMore.setAttribute("aria-expanded", String(self.moreSettingsOpen));
          bodyMore.hidden = !self.moreSettingsOpen;
          const icon = toggleMore.querySelector(".make-image-toggle-icon");
          if (icon) icon.textContent = self.moreSettingsOpen ? "▲ 收起" : "▼ 展开";
        };
      }

      // Tones picker button (B2: openAssetPicker with tone)
      const btnPickTones = root.querySelector("#batch-btn-pick-tones");
      if (btnPickTones) {
        btnPickTones.onclick = () => {
          if (self.actions?.openAssetPicker) {
            self.actions.openAssetPicker({ kind: "tone", field: "tones" });
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openAssetPicker）");
          }
        };
      }
      root.querySelectorAll("[data-remove-tone]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const tid = btn.getAttribute("data-remove-tone");
          if (!tid) return;
          skill.data.tones = (skill.data.tones || []).filter((t) => t !== tid);
          markDirty();
        };
      });

      // Global References Picker
      const btnPickGlobalRefs = root.querySelector("#batch-btn-pick-global-refs");
      if (btnPickGlobalRefs) {
        btnPickGlobalRefs.onclick = () => {
          if (self.actions?.openReferencePicker) {
            self.actions.openReferencePicker();
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openReferencePicker）");
          }
        };
      }

      root.querySelectorAll("[data-remove-global-ref]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const rIdx = Number(btn.getAttribute("data-remove-global-ref"));
          const curAsset = parts.asset || bp?.asset;
          if (curAsset && Array.isArray(curAsset.data?.items) && !isNaN(rIdx)) {
            curAsset.data.items.splice(rIdx, 1);
            if (self.actions?.ensureAssetItems) {
              self.actions.ensureAssetItems(curAsset.data.items);
            } else {
              markDirty();
            }
          }
        };
      });

      // Moods picker button (B2: openAssetPicker with mood)
      const btnPickMoods = root.querySelector("#batch-btn-pick-moods");
      if (btnPickMoods) {
        btnPickMoods.onclick = () => {
          if (self.actions?.openAssetPicker) {
            self.actions.openAssetPicker({ kind: "mood", field: "moods" });
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openAssetPicker）");
          }
        };
      }
      const moodsInput = root.querySelector("#batch-moods-input");
      if (moodsInput) {
        moodsInput.onchange = () => {
          const presetSet = self.getKnownPresetMoods();
          const parsed = parseMoodsText(moodsInput.value, presetSet);
          skill.data.moods = parsed.moods;
          skill.data.customMood = parsed.customMood;
          markDirty();
        };
      }

      // Whitespace
      root.querySelectorAll("[data-set-whitespace]").forEach((btn) => {
        btn.onclick = () => {
          const ws = btn.getAttribute("data-set-whitespace");
          skill.data.whitespace = ws || "";
          markDirty();
        };
      });

      // Audience & Business Scene
      const audInput = root.querySelector("#batch-audience-input");
      if (audInput) {
        audInput.onchange = () => {
          skill.data.audience = audInput.value.trim();
        };
      }
      const bzInput = root.querySelector("#batch-business-scene-input");
      if (bzInput) {
        bzInput.onchange = () => {
          skill.data.businessScene = bzInput.value.trim();
        };
      }

      // SC-021 Select
      const sc021Select = root.querySelector("#batch-sc021-select");
      if (sc021Select) {
        sc021Select.onchange = () => {
          skill.data.sc021Type = sc021Select.value;
        };
      }

      // SC-022 Inputs
      const sc022NameInput = root.querySelector("#batch-sc022-name");
      if (sc022NameInput) {
        sc022NameInput.onchange = () => {
          skill.data.sc022Name = sc022NameInput.value.trim();
        };
      }
      const sc022PinyinInput = root.querySelector("#batch-sc022-pinyin");
      if (sc022PinyinInput) {
        sc022PinyinInput.onchange = () => {
          skill.data.sc022Pinyin = sc022PinyinInput.value.trim();
        };
      }

      // 7. Preview Row Retries & Results (B2: openPublish / runSingleRow toast fallback)
      root.querySelectorAll("[data-retry-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-retry-idx"));
          if (!isNaN(idx)) {
            if (self.actions?.runSingleRow) {
              self.actions.runSingleRow(idx);
            } else {
              const S = global.HANDRAW_SHARED;
              if (S?.toast) S.toast("当前操作不可用（缺少 action: runSingleRow）");
            }
          }
        };
      });

      root.querySelectorAll("[data-publish-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-publish-idx"));
          const displays = Array.isArray(self.context?.displays) ? self.context.displays : [];
          const isBatchGallery = displays.some((d) => d.data?.kind === "batch_gallery");
          const itemResult = self.getItemResult(idx, displays, isBatchGallery);
          const S = global.HANDRAW_SHARED;
          if (itemResult?.node) {
            if (self.actions?.openPublish) {
              self.actions.openPublish(itemResult.node);
            } else {
              if (S?.toast) S.toast("当前操作不可用（缺少 action: openPublish）");
            }
          } else {
            if (S?.toast) S.toast("该行还没有生成结果");
          }
        };
      });

      // 7.5. Batch Iteration Thumbnail Zoom (Lightbox)
      root.querySelectorAll(".batch-iter-thumb-btn").forEach((btn) => {
        btn.onclick = () => {
          const src = btn.getAttribute("data-zoom-src");
          const title = btn.getAttribute("data-zoom-title") || "图型预览";
          if (!src) return;
          if (self.actions?.openImageLightbox) {
            self.actions.openImageLightbox(src, title);
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: openImageLightbox）");
          }
        };
      });

      // 8. Start Batch Generation Button (M1: single confirmation via confirmPotentialGenerationCost)
      const btnStart = root.querySelector("#batch-btn-start");
      if (btnStart) {
        btnStart.onclick = async () => {
          const currentIters = self.resolveIterations();
          const totalCount = currentIters.length;

          if (totalCount === 0) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("请先添加要批量生成的项（文案、图型）");
            return;
          }

          if (self.actions?.run) {
            self.actions.run();
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: run）");
          }
        };
      }

      // 9. Stop Batch Generation Button
      const btnStop = root.querySelector("#batch-btn-stop");
      if (btnStop) {
        btnStop.onclick = () => {
          if (self.actions?.cancel) {
            self.actions.cancel();
          } else {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("当前操作不可用（缺少 action: cancel）");
          }
        };
      }

      // 10. Download All Button
      const btnDownloadAll = root.querySelector("#batch-btn-download-all");
      if (btnDownloadAll) {
        btnDownloadAll.onclick = async () => {
          const results = self.context?.results || [];
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

      // 11. Result Card Publish Buttons
      root.querySelectorAll("[data-res-pub-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-res-pub-idx"));
          const res = (self.context?.results || [])[idx];
          const S = global.HANDRAW_SHARED;
          if (res?.node) {
            if (self.actions?.openPublish) {
              self.actions.openPublish(res.node);
            } else {
              if (S?.toast) S.toast("当前操作不可用（缺少 action: openPublish）");
            }
          } else {
            if (S?.toast) S.toast("该项还没有生成结果");
          }
        };
      });

      if (global.HandrawImageLoader?.scan) {
        global.HandrawImageLoader.scan(root);
      }
    }

    updatePreviewAndCost(root) {
      const iterations = this.resolveIterations();
      const totalCount = Math.min(200, iterations.length);

      const costWrap = root.querySelector(".batch-cost-wrap");
      if (costWrap) {
        costWrap.innerHTML = this.renderCostHtml(totalCount);
      }

      const btnStart = root.querySelector("#batch-btn-start");
      if (btnStart) {
        btnStart.disabled = totalCount === 0;
      }

      const title = root.querySelector(".batch-preview-title");
      if (title) {
        title.textContent = `批量清单与状态 (${totalCount} 张)`;
      }
    }

    // Fission Modal (Defect 1 Fixed: captures self = this)
    openFissionModal(root, parts) {
      const self = this;
      const S = global.HANDRAW_SHARED;
      if (!S?.openModal) return;

      const isAiMode = parts.loop.data.batchLayoutMode === "ai";

      const seedDefault = (parts.loop.data.batchSeed || parts.text?.data?.text || "").trim() ||
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

            <div id="fission-result-box" style="display:none;border-top:1px solid var(--line-soft);padding-top:12px;">
              <div id="fission-source-banner" style="display:none;padding:6px 10px;background:#fef3c7;border:1px solid #fde68a;border-radius:6px;font-size:12px;color:#92400e;margin-bottom:8px;">
                未使用 AI 扩写，已按模板生成
              </div>
              <div class="make-image-field-label" style="margin-bottom:6px;">扩写结果预览 (<span id="fission-result-count">0</span> 条)</div>
              <div id="fission-result-list" style="max-height:160px;overflow-y:auto;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:6px;padding:8px 12px;font-size:12px;line-height:1.6;display:flex;flex-direction:column;gap:4px;"></div>

              <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px;">
                <button type="button" class="btn btn-sm" id="fission-append-btn">${isAiMode ? "追加为新的逐张行" : "追加到列表"}</button>
                <button type="button" class="btn btn-sm btn-primary" id="fission-replace-btn">${isAiMode ? "替换全部逐张行" : "替换列表"}</button>
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

            if (replace) {
              const hasExisting = isAiMode
                ? Array.isArray(parts.loop.data.batchRows) && parts.loop.data.batchRows.length > 0
                : Boolean((parts.loop.data.promptListText || "").trim());
              if (hasExisting && typeof window.confirm === "function") {
                const confirmMsg = isAiMode
                  ? "替换将清空现有的逐张主题与图型设置，是否继续？"
                  : "替换将清空现有的主题列表，是否继续？";
                if (!window.confirm(confirmMsg)) return;
              }
            }

            if (isAiMode) {
              let targetRows = [];
              if (replace) {
                targetRows = generatedItems.map((item) => ({
                  theme: String(item).trim(),
                  layout: "",
                  assetItems: [],
                  skipGlobalRefs: false
                }));
              } else {
                const existingRows = Array.isArray(parts.loop.data.batchRows) ? parts.loop.data.batchRows : [];
                const newRows = generatedItems.map((item) => ({
                  theme: String(item).trim(),
                  layout: "",
                  assetItems: [],
                  skipGlobalRefs: false
                }));
                targetRows = [...existingRows, ...newRows];
              }
              let truncated = false;
              if (targetRows.length > 20) {
                targetRows = targetRows.slice(0, 20);
                truncated = true;
              }
              parts.loop.data.batchRows = targetRows;
              parts.loop.data.promptListText = targetRows.map((r) => r.theme).filter(Boolean).join("\n");
              if (truncated && S?.toast) {
                S.toast("超出 20 张部分已截断");
              }
            } else {
              const existingLines = (parts.loop.data.promptListText || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
              let combinedLines = replace ? [...generatedItems] : [...existingLines, ...generatedItems];
              let truncated = false;
              if (combinedLines.length > 20) {
                combinedLines = combinedLines.slice(0, 20);
                truncated = true;
              }
              parts.loop.data.promptListText = combinedLines.join("\n");
              if (truncated && S?.toast) {
                S.toast("超出 20 张部分已截断");
              }
            }

            S.closeModal();
            // Defect 1 Fixed: self.actions?.markDirtyAndRender() correctly called
            if (self.actions?.markDirtyAndRender) {
              self.actions.markDirtyAndRender();
            } else {
              if (S?.toast) S.toast("当前操作不可用（缺少 action: markDirtyAndRender）");
            }
            if (S?.toast) {
              const actionLabel = replace ? "替换" : "追加";
              const count = isAiMode ? parts.loop.data.batchRows.length : parts.loop.data.promptListText.split(/\r?\n/).filter(Boolean).length;
              const targetDesc = isAiMode ? "逐张行" : "条主题";
              S.toast(`已${actionLabel}为 ${count} ${targetDesc}！`);
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
