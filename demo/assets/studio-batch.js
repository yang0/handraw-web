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
 * - 规划回调中的 this 正确绑定为控制器实例 (self).
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
      this.planNotice = "";
      this.isPlanning = false;
      this.progressState = null;
      this.lastSummary = "";
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
        <button type="button" class="btn batch-row-layout-btn" data-pick-layout-idx="${idx}" data-hover-src="${esc(thumbUrl)}" data-hover-code="${esc(codeText)}" data-hover-name="${esc(nameText)}" data-zoom-src="${esc(thumbUrl)}" data-zoom-title="${esc(codeText)} ${esc(nameText)}" title="${esc(btnTitle)}" aria-label="${esc(ariaLabel)}">
          <span class="batch-row-layout-thumb-wrap" data-zoom-src="${esc(thumbUrl)}" data-zoom-title="${esc(codeText)} ${esc(nameText)}">
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


    /* #141: One card per planned output, across editing, generation and completion. */
    renderSeriesCard(iter, idx, opts = {}) {
      const mode = opts.mode || "fixed";
      const row = mode === "ai" ? (opts.rows?.[idx] || {}) : {};
      const theme = mode === "ai" ? (row.theme || "") : (iter.theme || iter.title || "");
      const refs = Array.isArray(row.assetItems) ? row.assetItems : [];
      const globalLayout = opts.globalLayout || "";
      const layoutId = (mode === "ai" && row.layout) || iter.layout || globalLayout;
      const layoutRes = layoutId ? this.getResourceInfo(layoutId, "layouts") : null;
      const layoutImg = layoutRes?.image || iter.sampleImg || "";
      const image = opts.result?.imageUrl || "";
      const status = this.getRowStatus(idx, opts.busy, opts.currentStep || 0, opts.result, opts.activeIndex);
      const ratio = String(opts.ratio || "3:4").split(":").map(Number);
      const aspect = ratio.length === 2 && ratio.every(n => Number.isFinite(n) && n > 0)
        ? `${ratio[0]} / ${ratio[1]}` : "3 / 4";
      const label = theme || `第 ${idx + 1} 张画面`;
      const refHtml = refs.slice(0, 3).map((r, i) => {
        const url = typeof r === "string" ? r : (r.image || r.url || "");
        const name = typeof r === "string" ? `参考图 ${i + 1}` : (r.name || r.id || `参考图 ${i + 1}`);
        return url ? `<img src="${esc(url)}" alt="${esc(name)}" loading="lazy" />` : "";
      }).join("");
      let media;
      if (image) {
        media = `<button type="button" class="batch-iter-thumb-btn is-generated batch-series-image" data-zoom-src="${esc(image)}" data-zoom-title="${esc(label)}" aria-label="查看第 ${idx + 1} 张生成图片"><img data-hw-src="${esc(image)}" alt="${esc(label)}" loading="lazy" /></button>`;
      } else if (status.key === "generating") {
        media = `<div class="batch-series-pending" role="status" aria-label="第 ${idx + 1} 张图片生成中"><span class="batch-series-pending-mark" aria-hidden="true">·</span><span class="batch-series-shimmer" aria-hidden="true"></span><span class="batch-series-pending-label">正在生成…</span></div>`;
      } else if (status.key === "failed") {
        media = `<div class="batch-series-failed" role="status"><span>本张生成失败</span><small>可在卡片内单独重试</small></div>`;
      } else if (layoutImg) {
        media = `<button type="button" class="batch-iter-thumb-btn is-schematic batch-series-image" data-zoom-src="${esc(layoutImg)}" data-zoom-title="版式示意 · ${esc(layoutId)}" aria-label="查看第 ${idx + 1} 张版式示意"><img data-hw-src="${esc(layoutImg)}" alt="版式示意" loading="lazy" /><span class="batch-iter-schematic-badge">版式示意</span></button>`;
      } else {
        media = `<div class="batch-iter-placeholder batch-series-placeholder" role="img" aria-label="第 ${idx + 1} 张待生成"><span aria-hidden="true">·</span><small>等待创作</small></div>`;
      }
      const footer = image
        ? `<a class="btn btn-sm batch-btn-dl" href="${esc(image)}" download="series-${idx + 1}.webp">下载图片</a>`
        : status.key === "failed" ? `<button type="button" class="btn btn-sm batch-btn-retry" data-retry-idx="${idx}">重试这张</button>` : "";
      return `
        <article class="batch-series-card ${status.className}" data-batch-row="${idx}" data-row-idx="${idx}">
          <div class="batch-series-card-head">
            <strong>${String(idx + 1).padStart(2, "0")}</strong>
            <span class="batch-status-badge is-${esc(status.key)}" aria-live="polite">${esc(status.label)}</span>
            <button type="button" class="batch-series-delete" data-del-row-idx="${idx}" aria-label="删除第 ${idx + 1} 张画面" title="删除此张" ${opts.busy ? "disabled" : ""}>×</button>
          </div>
          <div class="batch-series-visual" style="aspect-ratio:${esc(aspect)}">${media}</div>
          <div class="batch-series-card-editor">
            <label class="batch-series-card-label" for="batch-series-theme-${idx}">画面主题</label>
            <textarea id="batch-series-theme-${idx}" class="make-image-textarea batch-series-theme-input" data-series-theme-idx="${idx}" rows="3" placeholder="描述这张画面的内容…" ${opts.busy ? "disabled" : ""}>${esc(theme)}</textarea>
            <div class="batch-series-card-settings">
              ${this.renderRowLayoutButtonHtml(row, idx, globalLayout)}
              <button type="button" class="batch-series-ref-picker" data-pick-row-refs-idx="${idx}" aria-label="调整第 ${idx + 1} 张参考图" ${opts.busy ? "disabled" : ""}>
                ${refHtml || '<span class="batch-series-plus">＋</span>'}
                <span>参考图${refs.length ? ` · ${refs.length}` : ""}</span>
              </button>
            </div>
            <label class="batch-series-global-toggle"><input type="checkbox" data-row-skip-global="${idx}" ${row.skipGlobalRefs ? "checked" : ""} ${opts.busy ? "disabled" : ""} />不使用全局参考图</label>
          </div>
          <div class="batch-series-card-foot">${footer}</div>
        </article>
      `;
    }

    render(host, context, actions) {
      if (host) this.hostElement = host;
      if (context) this.context = context;
      if (actions) this.actions = actions;
      if (!this.hostElement) return;

      const p = this.getParts();
      if (p?.ctrl?.data?.activeBatchId) {
        this.activeBatchId = p.ctrl.data.activeBatchId;
      }
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
      const globalAssetItems = Array.isArray(p.asset?.data?.items) ? p.asset.data.items : [];

      // M1: Single truth - each iteration generates 1 image in batch set planning
      const perIterCount = 1;
      const iterations = this.resolveIterations();
      const totalCount = Math.min(200, iterations.length * perIterCount);

      const busy = typeof this.progressState?.busy === "boolean" ? this.progressState.busy : Boolean(this.context?.busy);
      const displays = Array.isArray(this.context?.displays) ? this.context.displays : [];
      const results = Array.isArray(this.context?.results) ? this.context.results : [];

      const isBatchGallery = displays.some((d) => d.data?.kind === "batch_gallery");
      // The displayed slot results are the source of truth. Node progress can
      // be stale (0/2) after a re-render even while both images are visible.
      const slotResults = iterations.map((_, index) => this.seriesOutcomes?.get(index) || (this.context?.results || []).find(r => r.index === index) || this.getItemResult(index, displays, isBatchGallery));
      const progress = this.progressState?.batchId === this.activeBatchId ? this.progressState : null;
      const currentStep = ld.currentStep || 0;
      const totalSteps = ld.totalSteps || totalCount;
      const completedCount = Math.max(slotResults.filter((item) => item?.imageUrl).length,
        progress?.completedCount || 0);
      const failedCount = Math.max(slotResults.filter((item) => item?.failed && !item?.imageUrl).length,
        progress?.failedCount || 0);
      const isStopping = Boolean(progress?.isStopping || ld.isStopping);
      const activeIndices = Array.isArray(progress?.activeIndices) ? progress.activeIndices : [];
      const activeIndex = activeIndices.length ? activeIndices[0]
        : (busy && typeof ld.activeIndex === "number" ? ld.activeIndex
          : (busy && currentStep < totalSteps ? currentStep : null));

      const oldSeriesScroll = this.hostElement.querySelector(".batch-series-scroll")?.scrollTop || 0;
      const oldSeriesPropertiesScroll = this.hostElement.querySelector(".batch-series-properties")?.scrollTop || 0;
      this.hostElement.innerHTML = `
        <div class="make-image-container batch-container batch-series-container">
          <form class="make-image-form creation-form batch-series-form" novalidate onsubmit="return false;">
            <div class="make-image-main-grid creation-workspace batch-series-workspace">
              <section class="creation-settings batch-series-properties" aria-label="系列图设置">
              <!-- 套图规划 (Set Planning Section) -->
              <div class="batch-plan-card">
                <!-- 规划输入整体分区 (Planning Inputs Panel) -->
                <div class="batch-plan-inputs-panel">
                  <div class="batch-plan-inputs-head">
                    <span class="batch-plan-inputs-tag">规划输入</span>
                  </div>

                  <!-- 规划第一行: 母题 + 张数 + 图型策略 -->
                  <div class="batch-plan-row-a">
                    <div class="batch-seed-wrap">
                      <label for="batch-seed-input" class="make-image-field-label">母题</label>
                      <input type="text" class="make-image-input batch-seed-input" id="batch-seed-input" placeholder="输入这套图的创作母题（如：都市慢生活与手绘手账）..." value="${esc(batchSeed)}" />
                    </div>

                    <div class="batch-count-wrap">
                      <label for="batch-count-input" class="make-image-field-label">张数</label>
                      <input type="number" class="make-image-input batch-count-input" id="batch-count-input" min="1" max="20" value="${batchCount}" />
                    </div>

                    <div class="batch-strategy-wrap">
                      <span class="make-image-field-label">图型策略</span>
                      <div class="batch-strategy-seg" role="group" aria-label="图型策略">
                        <button type="button" class="batch-strategy-seg-btn ${batchLayoutMode === "fixed" ? "is-active" : ""}" id="batch-strategy-fixed" aria-pressed="${batchLayoutMode === "fixed"}">固定图型</button>
                        <button type="button" class="batch-strategy-seg-btn ${batchLayoutMode === "ai" ? "is-active" : ""}" id="batch-strategy-ai" aria-pressed="${batchLayoutMode === "ai"}">AI 推荐图型</button>
                      </div>
                    </div>
                  </div>

                  <!-- 规划第二行: 固定图型/图型要求 + 右下角【AI 规划这套图】主操作 -->
                  <div class="batch-plan-row-b-wrap">
                    ${batchLayoutMode === "fixed" ? `
                      <div class="batch-plan-row-b batch-fixed-layout-row">
                        <span class="make-image-field-label">固定图型</span>
                        <button type="button" class="btn btn-sm" id="batch-btn-pick-fixed-layout">选择图型</button>
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

                    <div class="batch-plan-action-wrap">
                      <button type="button" class="batch-btn-plan-hero batch-plan-trigger" id="batch-btn-plan" ${busy ? "disabled" : ""}>
                        <svg class="batch-plan-icon" viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
                          <path d="M7.5 0.5c.2 2.6 1.8 4.2 4.4 4.4.2 0 .2.3 0 .4-2.6.2-4.2 1.8-4.4 4.4 0 .2-.3.2-.4 0-.2-2.6-1.8-4.2-4.4-4.4-.2 0-.2-.3 0-.4 2.6-.2 4.2-1.8 4.4-4.4 0-.2.3-.2.4 0zm5 9c.1 1.5 1 2.4 2.5 2.5.1 0 .1.2 0 .2-1.5.1-2.4 1-2.5 2.5 0 .1-.2.1-.2 0-.1-1.5-1-2.4-2.5-2.5-.1 0-.1-.2 0-.2 1.5-.1 2.4-1 2.5-2.5 0-.1.2-.1.2 0z"/>
                        </svg>
                        <span>${busy ? "AI 规划中…" : "AI 规划这套图"}</span>
                      </button>
                      ${this.planNotice ? `<span class="batch-plan-notice" role="status">${esc(this.planNotice)}</span>` : ""}
                      ${this.lastPlanUndo ? '<button type="button" class="btn btn-sm" id="batch-undo-plan">撤销上次规划</button>' : ""}
                    </div>
                  </div>
                </div>


              ${batchLayoutMode === "fixed" ? `
                <details class="batch-series-bulk-input">
                  <summary>批量粘贴主题（可选）</summary>
                  <textarea class="make-image-textarea batch-prompts-textarea" id="batch-prompts-input" rows="5" aria-label="批量粘贴主题，每行一张" placeholder="每行一张画面主题…">${esc(promptListText)}</textarea>
                </details>
              ` : ""}
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

              <!-- Global References Row (Independent row outside collapsible) -->
              <div class="make-image-more-row batch-global-refs-row" id="batch-more-row-refs">
                <span class="make-image-field-label">参考图</span>
                <button type="button" class="btn btn-sm" id="batch-btn-pick-global-refs">选择参考图</button>
                <div class="make-image-more-thumbs batch-global-refs-thumbs" id="batch-global-refs-thumbs">
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


            <label style="display:flex;align-items:center;gap:8px;font-size:12px;">同时生成
              <select class="hw-input" id="batch-concurrency" aria-label="批量生图并发数量" ${busy ? "disabled" : ""}>
                ${[1,2,3,4].map((n) => `<option value="${n}" ${Number(ld.batchConcurrency || 3) === n ? "selected" : ""}>${n} 张</option>`).join("")}
              </select>
            </label>
              </section>
              <section class="creation-content batch-series-content" aria-label="系列图卡片工作区">
                <div class="batch-series-toolbar">
                  <span>系列画面 <strong>${totalCount}</strong> 张</span>
                  <button type="button" class="btn btn-sm" id="batch-btn-add-row" ${busy ? "disabled" : ""}>＋ 添加画面</button>
                </div>
                <div class="batch-series-scroll" role="region" aria-label="系列画面编辑与生成结果" tabindex="0">
                  <div class="batch-series-grid">
                    ${iterations.length ? iterations.map((iter, idx) => this.renderSeriesCard(iter, idx, {
                      mode: batchLayoutMode, rows: batchRows, globalLayout: sd.layout || "",
                      result: slotResults[idx], busy, currentStep, activeIndex, ratio: currentRatio
                    })).join("") : `<div class="batch-series-empty">还没有画面。可在左侧用 AI 规划，或点击「添加画面」开始。</div>`}
                  </div>
                </div>
              <!-- Bottom Bar: Cost + Action (Defect 2 Fixed) -->
              <div class="batch-action-bar">
                <div class="batch-cost-wrap">
                  ${this.renderCostHtml(totalCount)}
                  ${busy ? `<span class="batch-busy-status">${this.formatProgressStatus({ completedCount, totalCount: totalSteps, activeIndex, activeIndices, failedCount, isStopping })}</span>` : (this.lastSummary ? `<span class="batch-summary-status">${esc(this.lastSummary)}</span>` : "")}
                </div>

                <div class="batch-btn-wrap">
                  ${busy ? `<span class="batch-busy-hint">任务处理中，暂不能清空或再次生成</span>` : ""}
                  <button type="button" class="btn btn-sm" id="batch-btn-download-all" ${results.some(r => r?.imageUrl) ? "" : "disabled"}>全部下载</button>
                  <button type="button" class="btn btn-sm batch-btn-reset" id="batch-btn-reset" ${busy ? "disabled" : ""}>清空表单</button>
                  ${busy ? `
                    <button type="button" class="btn btn-sm batch-stop-btn" id="batch-btn-stop" ${isStopping ? "disabled" : ""}>${isStopping ? "正在停止…" : "停止"}</button>
                  ` : `
                    <button type="button" class="make-image-run-btn" id="batch-btn-start" ${totalCount === 0 ? "disabled" : ""}>生成系列图</button>
                  `}
                </div>
              </div>

              </section>
            </div>
          </form>
        </div>
      `;
      const newSeriesScroll = this.hostElement.querySelector(".batch-series-scroll");
      const newPropertiesScroll = this.hostElement.querySelector(".batch-series-properties");
      if (newSeriesScroll) newSeriesScroll.scrollTop = oldSeriesScroll;
      if (newPropertiesScroll) newPropertiesScroll.scrollTop = oldSeriesPropertiesScroll;

      if (typeof host.querySelectorAll === "function") {
        this.bindEvents(host, p, iterations);
      }

      if (global.HANDRAW_SHARED?.triggerImageLoaders) {
        global.HANDRAW_SHARED.triggerImageLoaders(this.hostElement);
      }
    }


    /* Repaint the SAME card grid for live progress, including concurrent slots;
       never append a second results list or detach the whole form. */
    refreshSeriesCards() {
      const host = this.hostElement;
      const grid = host?.querySelector(".batch-series-grid");
      const parts = this.getParts();
      if (!grid || !parts) return;
      const iterations = this.resolveIterations();
      const loop = parts.loop?.data || {};
      const ctrl = parts.ctrl?.data || {};
      const skill = parts.skill?.data || {};
      const isBusy = typeof this.progressState?.busy === "boolean" ? this.progressState.busy : Boolean(this.context?.busy);
      const active = this.progressState?.activeIndices || [];
      const activeIndex = active.length ? active[0] :
        this.progressState?.activeIndex ?? (isBusy ? Number(loop.activeIndex ?? 0) : null);
      const displays = this.context?.displays || [];
      const gallery = displays.some(d => d.data?.kind === "batch_gallery");
      const oldScroll = host.querySelector(".batch-series-scroll")?.scrollTop || 0;
      grid.innerHTML = iterations.length ? iterations.map((iter, idx) => {
        const cachedResult = this.seriesOutcomes?.get(idx);
        const cachedContext = (this.context?.results || []).find(r => r.index === idx);
        const displayResult = isBusy ? null : this.getItemResult(idx, displays, gallery);
        return this.renderSeriesCard(iter, idx, {
          mode: loop.batchLayoutMode || "fixed",
          rows: loop.batchRows || [],
          globalLayout: skill.layout || "",
          ratio: ctrl.ratio || "3:4",
          result: cachedResult || cachedContext || displayResult,
          busy: isBusy, currentStep: loop.currentStep || 0, activeIndex
        });
      }).join("") : '<div class="batch-series-empty">还没有画面。可在左侧用 AI 规划，或点击「添加画面」开始。</div>';
      const cardCount = host.querySelector(".batch-series-toolbar strong");
      if (cardCount) cardCount.textContent = String(iterations.length);
      const scroll = host.querySelector(".batch-series-scroll");
      if (scroll) scroll.scrollTop = oldScroll;
      this.bindEvents(grid, parts, iterations);
      if (global.HANDRAW_SHARED?.triggerImageLoaders) {
        global.HANDRAW_SHARED.triggerImageLoaders(grid);
      }
    }

    getItemResult(rowIndex, displays, isBatchGallery) {
      if (!displays || !displays.length) return null;
      if (isBatchGallery) {
        const gal = displays.find((d) => d.data?.kind === "batch_gallery") || displays[0];
        const it = gal?.data?.items?.[rowIndex] || null;
        if (this.activeBatchId && it?.batchId && it.batchId !== this.activeBatchId) return null;
        return it;
      }
      const dn = displays[rowIndex];
      const it = dn?.data?.items?.[0] || null;
      if (this.activeBatchId && it?.batchId && it.batchId !== this.activeBatchId) return null;
      return it;
    }

    getRowStatus(rowIndex, busy, currentStep, itemResult, activeIndex = null) {
      const isStale = Boolean(this.activeBatchId && itemResult?.batchId && itemResult.batchId !== this.activeBatchId);
      if (!isStale && itemResult?.imageUrl) {
        return { key: "done", label: "完成", className: "is-done" };
      }
      if (!isStale && (itemResult?.failed || (itemResult && !itemResult.imageUrl && itemResult.error))) {
        return { key: "failed", label: "失败", className: "is-failed" };
      }
      if (busy) {
        const activeSet = this.progressState?.batchId === this.activeBatchId
          ? this.progressState?.activeIndices : null;
        const isCurrentActive = Array.isArray(activeSet) && activeSet.length
          ? activeSet.includes(rowIndex) : activeIndex !== null
          ? activeIndex === rowIndex
          : (currentStep === rowIndex + 1 || (currentStep === 0 && rowIndex === 0));
        if (isCurrentActive) {
          return { key: "generating", label: "生成中", className: "is-generating" };
        }
        return { key: "waiting", label: "等待", className: "is-waiting" };
      }

      return { key: "waiting", label: "等待", className: "is-waiting" };
    }

    formatProgressStatus({ completedCount = 0, totalCount = 0, activeIndex = null, activeIndices = [], failedCount = 0, isStopping = false } = {}) {
      if (isStopping) {
        let msg = `正在停止…（已完成 ${completedCount} / ${totalCount} 张`;
        if (failedCount > 0) msg += ` · 失败 ${failedCount} 张`;
        msg += `）`;
        return msg;
      }
      let txt = `已完成 ${completedCount} / ${totalCount} 张`;
      if (Array.isArray(activeIndices) && activeIndices.length > 1) {
        txt += ` · 并行生成中 ${activeIndices.length} 张…`;
      } else if (activeIndex !== null && activeIndex >= 0 && activeIndex < totalCount) {
        txt += ` · 正在生成第 ${activeIndex + 1} 张…`;
      }
      if (failedCount > 0) {
        txt += ` · 失败 ${failedCount} 张`;
      }
      return txt;
    }

    formatSummaryStatus({ completedCount = 0, failedCount = 0, totalCount = 0 } = {}) {
      const unexecuted = Math.max(0, totalCount - completedCount - failedCount);
      if (completedCount === totalCount && failedCount === 0 && unexecuted === 0) {
        return `全部完成（${totalCount} / ${totalCount} 张）`;
      }
      const parts = [`已完成 ${completedCount} / ${totalCount} 张`];
      if (failedCount > 0) parts.push(`失败 ${failedCount} 张`);
      if (unexecuted > 0) parts.push(`未执行 ${unexecuted} 张`);
      return parts.join(" · ");
    }

    setStopping() {
      const host = this.hostElement;
      if (!host) return;
      const btnStop = host.querySelector("#batch-btn-stop");
      if (btnStop) {
        btnStop.disabled = true;
        btnStop.textContent = "正在停止…";
      }
      if (this.progressState) {
        this.progressState.isStopping = true;
        const costWrap = host.querySelector(".batch-cost-wrap");
        if (costWrap) {
          let busyEl = costWrap.querySelector(".batch-busy-status");
          if (!busyEl) {
            busyEl = document.createElement("span");
            busyEl.className = "batch-busy-status";
            costWrap.appendChild(busyEl);
          }
          busyEl.textContent = this.formatProgressStatus(this.progressState);
        }
      }
    }

    resetBatchProgress({ totalCount = 0, batchId = null, singleSlotIndex = null } = {}) {
      if (batchId) this.activeBatchId = batchId;
      const host = this.hostElement;
      if (singleSlotIndex !== null) {
        this.seriesOutcomes?.delete(singleSlotIndex);
        if (host?.querySelector(".batch-series-grid")) {
          if (this.context && Array.isArray(this.context.results)) {
            this.context.results = this.context.results.filter(r => r.index !== singleSlotIndex);
          }
          this.progressState = { ...(this.progressState || {}), busy:true, batchId:this.activeBatchId,
            activeIndex:singleSlotIndex, activeIndices:[singleSlotIndex] };
          this.refreshSeriesCards();
          return;
        }
        if (this.context && Array.isArray(this.context.results)) {
          this.context.results = this.context.results.filter((r) => r.index !== singleSlotIndex);
        }
        if (host) {
          const row = host.querySelector(`tr[data-batch-row="${singleSlotIndex}"]`);
          if (row) {
            row.className = "batch-table-row is-generating";
            const badge = row.querySelector(".batch-status-badge");
            if (badge) {
              badge.className = "batch-status-badge is-generating";
              badge.textContent = "生成中";
            }
            const action = row.querySelector(".batch-col-action");
            if (action) {
              action.innerHTML = '<span class="batch-action-idle">-</span>';
            }
            const cell = row.querySelector(".batch-iter-cell");
            if (cell) {
              const thumb = cell.querySelector(".batch-iter-thumb-btn");
              if (thumb) {
                const ph = document.createElement("div");
                ph.className = "batch-iter-placeholder";
                ph.title = "待生成";
                ph.setAttribute("aria-label", "待生成");
                ph.setAttribute("role", "img");
                ph.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="16" height="16" rx="3" /><circle cx="7" cy="7" r="1.5" /><path d="M18 13l-4-4-7 7" /></svg>';
                if (typeof thumb.replaceWith === "function") thumb.replaceWith(ph);
                else if (thumb.parentNode) thumb.parentNode.replaceChild(ph, thumb);
              }
            }
          }
          const card = host.querySelector(`[data-result-idx="${singleSlotIndex}"]`);
          if (card && typeof card.remove === "function") card.remove();
          const headTitle = host.querySelector(".batch-results-section .make-image-results-head h2");
          if (headTitle && this.context?.results) {
            headTitle.textContent = `批量生成结果 (${this.context.results.length})`;
          }
        }
        return;
      }

      if (!this.context) this.context = {};
      this.context.results = [];
      this.progressState = { completedCount: 0, failedCount: 0, totalCount, activeIndex: 0, activeIndices: [0], busy: true, isStopping: false, batchId: this.activeBatchId };
      this.seriesOutcomes = new Map();

      if (!host) return;
      if (host.querySelector(".batch-series-grid")) {
        this.refreshSeriesCards();
        const dlAll = host.querySelector("#batch-btn-download-all");
        if (dlAll) dlAll.disabled = true;
        const btnReset = host.querySelector("#batch-btn-reset");
        if (btnReset) btnReset.disabled = true;
        const btnStart = host.querySelector("#batch-btn-start");
        if (btnStart) btnStart.disabled = true;
        return;
      }

      const resultsSec = host.querySelector(".batch-results-section");
      if (resultsSec && typeof resultsSec.remove === "function") {
        resultsSec.remove();
      }

      const count = Number(totalCount) || 0;
      for (let rIdx = 0; rIdx < count; rIdx++) {
        const row = host.querySelector(`tr[data-batch-row="${rIdx}"]`);
        if (!row) continue;
        const isFirst = rIdx === 0;
        row.className = `batch-table-row ${isFirst ? "is-generating" : "is-waiting"}`;
        const badge = row.querySelector(".batch-status-badge");
        if (badge) {
          badge.className = `batch-status-badge ${isFirst ? "is-generating" : "is-waiting"}`;
          badge.textContent = isFirst ? "生成中" : "等待";
        }
        const action = row.querySelector(".batch-col-action");
        if (action) {
          action.innerHTML = '<span class="batch-action-idle">-</span>';
        }
        const cell = row.querySelector(".batch-iter-cell");
        if (cell) {
          const thumb = cell.querySelector(".batch-iter-thumb-btn");
          if (thumb) {
            const ph = document.createElement("div");
            ph.className = "batch-iter-placeholder";
            ph.title = "待生成";
            ph.setAttribute("aria-label", "待生成");
            ph.setAttribute("role", "img");
            ph.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="16" height="16" rx="3" /><circle cx="7" cy="7" r="1.5" /><path d="M18 13l-4-4-7 7" /></svg>';
            if (typeof thumb.replaceWith === "function") thumb.replaceWith(ph);
            else if (thumb.parentNode) thumb.parentNode.replaceChild(ph, thumb);
          }
        }
      }

      const costWrap = host.querySelector(".batch-cost-wrap");
      if (costWrap) {
        const sumEl = costWrap.querySelector(".batch-summary-status");
        if (sumEl && typeof sumEl.remove === "function") sumEl.remove();
        let busyEl = costWrap.querySelector(".batch-busy-status");
        if (!busyEl) {
          busyEl = document.createElement("span");
          busyEl.className = "batch-busy-status";
          costWrap.appendChild(busyEl);
        }
        busyEl.textContent = this.formatProgressStatus({ completedCount: 0, totalCount, activeIndex: 0, failedCount: 0, isStopping: false });
      }

      const btnReset = host.querySelector("#batch-btn-reset");
      if (btnReset) btnReset.disabled = true;
      const btnStop = host.querySelector("#batch-btn-stop");
      if (btnStop) {
        btnStop.disabled = false;
        btnStop.textContent = "停止";
      }
      const btnStart = host.querySelector("#batch-btn-start");
      if (btnStart) btnStart.disabled = true;
    }

    updateProgress({
      updatedIndex = null,
      itemResult = null,
      completedCount = 0,
      failedCount = 0,
      totalCount = 0,
      activeIndex = null,
      activeIndices = [],
      busy = false,
      isStopping = false,
      summaryText = null,
      batchId = null
    } = {}) {
      const incomingBatchId = batchId || itemResult?.batchId;
      if (incomingBatchId) {
        if (this.activeBatchId && incomingBatchId !== this.activeBatchId) {
          return;
        }
        this.activeBatchId = incomingBatchId;
      }
      // Once the user clicks Stop, late concurrent progress messages must
      // never re-enable the button or hide the stopping state.
      const stopping = Boolean(isStopping ||
        (busy && this.progressState?.batchId === this.activeBatchId && this.progressState?.isStopping));
      this.progressState = { completedCount, failedCount, totalCount, activeIndex, activeIndices,
        busy, isStopping: stopping, batchId: this.activeBatchId };
      isStopping = stopping;
      const host = this.hostElement;
      if (!host) return;

      // 1. Update Cost Wrap status
      const costWrap = host.querySelector(".batch-cost-wrap");
      if (costWrap) {
        if (busy) {
          const sumEl = costWrap.querySelector(".batch-summary-status");
          if (sumEl && typeof sumEl.remove === "function") sumEl.remove();
          let busyEl = costWrap.querySelector(".batch-busy-status");
          if (!busyEl) {
            busyEl = document.createElement("span");
            busyEl.className = "batch-busy-status";
            costWrap.appendChild(busyEl);
          }
          busyEl.textContent = this.formatProgressStatus({ completedCount, totalCount, activeIndex, activeIndices, failedCount, isStopping });
        } else {
          const busyEl = costWrap.querySelector(".batch-busy-status");
          if (busyEl && typeof busyEl.remove === "function") busyEl.remove();
          let sumEl = costWrap.querySelector(".batch-summary-status");
          if (!sumEl) {
            sumEl = document.createElement("span");
            sumEl.className = "batch-summary-status";
            costWrap.appendChild(sumEl);
          }
          const finalSummary = summaryText || this.formatSummaryStatus({ completedCount, failedCount, totalCount });
          sumEl.textContent = finalSummary;
          this.lastSummary = finalSummary;
        }
      }

      // 2. Buttons handling
      if (busy) {
        const btnStart = host.querySelector("#batch-btn-start");
        if (btnStart) btnStart.disabled = true;
        const btnReset = host.querySelector("#batch-btn-reset");
        if (btnReset) btnReset.disabled = true;
        if (isStopping) {
          const btnStop = host.querySelector("#batch-btn-stop");
          if (btnStop) {
            btnStop.disabled = true;
            btnStop.textContent = "正在停止…";
          }
        }
      } else {
        const btnStart = host.querySelector("#batch-btn-start");
        if (btnStart) btnStart.disabled = totalCount === 0;
        const btnReset = host.querySelector("#batch-btn-reset");
        if (btnReset) btnReset.disabled = false;
        const btnStop = host.querySelector("#batch-btn-stop");
        if (btnStop) {
          btnStop.disabled = false;
          btnStop.textContent = "停止";
        }
      }

      // #141: the series grid is the only source of visible status/results.
      if (host.querySelector(".batch-series-grid")) {
        if (updatedIndex !== null && updatedIndex !== undefined && itemResult) {
          if (!this.seriesOutcomes) this.seriesOutcomes = new Map();
          this.seriesOutcomes.set(updatedIndex, itemResult);
          if (itemResult.imageUrl) this.appendResultCard(itemResult, updatedIndex);
        }
        this.refreshSeriesCards();
        return;
      }

      // 3. Update specific completed or failed row
      if (updatedIndex !== null && updatedIndex !== undefined) {
        const row = host.querySelector(`tr[data-batch-row="${updatedIndex}"]`);
        if (row) {
          const hasImage = Boolean(itemResult?.imageUrl);
          const hasFailed = Boolean(itemResult?.failed || (itemResult && !itemResult.imageUrl && itemResult.error));
          if (hasImage) {
            row.className = "batch-table-row is-done";
          } else if (hasFailed) {
            row.className = "batch-table-row is-failed";
          }

          const statusBadge = row.querySelector(".batch-status-badge");
          if (statusBadge) {
            if (hasImage) {
              statusBadge.className = "batch-status-badge is-done";
              statusBadge.textContent = "完成";
            } else if (hasFailed) {
              statusBadge.className = "batch-status-badge is-failed";
              statusBadge.textContent = "失败";
            }
          }

          if (hasImage) {
            const cell = row.querySelector(".batch-iter-cell");
            const existingThumb = cell?.querySelector(".batch-iter-thumb-btn, .batch-iter-placeholder");
            if (existingThumb) {
              const genTitle = itemResult.title || `生成结果 #${updatedIndex + 1}`;
              const newBtn = document.createElement("button");
              newBtn.type = "button";
              newBtn.className = "batch-iter-thumb-btn is-generated";
              newBtn.dataset.zoomSrc = itemResult.imageUrl;
              newBtn.dataset.zoomTitle = genTitle;
              newBtn.dataset.hoverSrc = itemResult.imageUrl;
              newBtn.dataset.hoverCode = "";
              newBtn.dataset.hoverName = genTitle;
              newBtn.title = `${genTitle}（点击放大查看）`;
              newBtn.setAttribute("aria-label", "放大查看生成结果");
              newBtn.innerHTML = `<img data-hw-src="${esc(itemResult.imageUrl)}" class="batch-iter-thumb" alt="${esc(genTitle)}" loading="lazy" />`;
              newBtn.onclick = (e) => {
                e.stopPropagation();
                if (this.actions?.openImageLightbox) {
                  this.actions.openImageLightbox(itemResult.imageUrl, genTitle);
                }
              };
              if (typeof existingThumb.replaceWith === "function") {
                existingThumb.replaceWith(newBtn);
              } else if (existingThumb.parentNode) {
                existingThumb.parentNode.replaceChild(newBtn, existingThumb);
              }
              if (global.HANDRAW_SHARED?.triggerImageLoaders) {
                global.HANDRAW_SHARED.triggerImageLoaders(newBtn);
              }
            }
          }

          const actionCell = row.querySelector(".batch-col-action");
          if (actionCell) {
            if (hasImage) {
              actionCell.innerHTML = `
                <div class="batch-row-actions">
                  <a href="${esc(itemResult.imageUrl)}" download="batch-${updatedIndex + 1}.webp" class="btn btn-sm batch-btn-dl" title="下载此图">下载</a>
                </div>
              `;
            } else if (hasFailed) {
              actionCell.innerHTML = `<button type="button" class="btn btn-sm batch-btn-retry" data-retry-idx="${updatedIndex}">重试</button>`;
              const btnRetry = actionCell.querySelector("[data-retry-idx]");
              if (btnRetry) {
                btnRetry.onclick = () => {
                  if (this.actions?.runSingleRow) {
                    this.actions.runSingleRow(updatedIndex);
                  }
                };
              }
            }
          }
        }

        if (itemResult?.imageUrl) {
          this.appendResultCard(itemResult, updatedIndex);
        }
      }

      // 4. Update currently generating row
      if (activeIndex !== null && activeIndex >= 0 && busy) {
        const activeRow = host.querySelector(`tr[data-batch-row="${activeIndex}"]`);
        if (activeRow && !activeRow.classList.contains("is-done")) {
          activeRow.className = "batch-table-row is-generating";
          const badge = activeRow.querySelector(".batch-status-badge");
          if (badge) {
            badge.className = "batch-status-badge is-generating";
            badge.textContent = "生成中";
          }
          const action = activeRow.querySelector(".batch-col-action");
          if (action) {
            action.innerHTML = `<span class="batch-action-idle">-</span>`;
          }
        }
      }
    }

    appendResultCard(res, index) {
      const host = this.hostElement;
      if (!host || !res || !res.imageUrl) return;
      if (this.activeBatchId && res.batchId && res.batchId !== this.activeBatchId) return;

      if (!this.context) this.context = {};
      if (!Array.isArray(this.context.results)) {
        this.context.results = [];
      }
      const existingContextIdx = this.context.results.findIndex(
        (r) => r.index === index || (r.id && r.id === `${res.node?.id || "node"}:${index}`)
      );
      const resultObj = {
        id: `${res.node?.id || "node"}:${index}`,
        imageUrl: res.imageUrl,
        title: res.title || `批量图片 #${index + 1}`,
        node: res.node,
        item: res,
        index,
        batchId: res.batchId || this.activeBatchId
      };
      if (existingContextIdx >= 0) {
        this.context.results[existingContextIdx] = resultObj;
      } else {
        this.context.results.push(resultObj);
      }

      if (host.querySelector(".batch-series-grid")) {
        if (!this.seriesOutcomes) this.seriesOutcomes = new Map();
        this.seriesOutcomes.set(index, res);
        const dlAll = host.querySelector("#batch-btn-download-all");
        if (dlAll) dlAll.disabled = false;
        return;
      }
      let resultsSec = host.querySelector(".batch-results-section");
      if (!resultsSec) {
        const container = host.querySelector(".batch-container") || host;
        resultsSec = document.createElement("div");
        resultsSec.className = "make-image-results-section batch-results-section";
        resultsSec.innerHTML = `
          <div class="make-image-results-head">
            <h2>批量生成结果 (1)</h2>
            <button type="button" class="btn btn-sm" id="batch-btn-download-all">全部下载</button>
          </div>
          <div class="make-image-results-grid"></div>
        `;
        container.appendChild(resultsSec);
        const btnDlAll = resultsSec.querySelector("#batch-btn-download-all");
        if (btnDlAll) {
          btnDlAll.onclick = async () => {
            const results = this.context?.results || [];
            if (!results.length) return;
            btnDlAll.disabled = true;
            btnDlAll.textContent = "正在下载…";
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
            btnDlAll.disabled = false;
            btnDlAll.textContent = "全部下载";
          };
        }
      }

      const headTitle = resultsSec.querySelector(".make-image-results-head h2");
      if (headTitle) {
        headTitle.textContent = `批量生成结果 (${this.context.results.length})`;
      }

      const grid = resultsSec.querySelector(".make-image-results-grid");
      if (!grid) return;

      let card = grid.querySelector(`[data-result-idx="${index}"]`);
      const cardTitle = res.title || `图片 #${index + 1}`;
      if (card) {
        const img = card.querySelector("img");
        if (img) {
          img.setAttribute("data-hw-src", res.imageUrl);
          img.src = res.imageUrl;
        }
        const a = card.querySelector("a.btn");
        if (a) a.href = res.imageUrl;
      } else {
        const fig = document.createElement("figure");
        fig.className = "make-image-result-card";
        fig.setAttribute("data-result-idx", String(index));
        fig.innerHTML = `
          <div class="make-image-result-frame">
            <img data-hw-src="${esc(res.imageUrl)}" alt="${esc(cardTitle)}" loading="lazy" />
          </div>
          <figcaption class="make-image-result-caption">
            <strong class="make-image-result-title" title="${esc(cardTitle)}">${esc(cardTitle)}</strong>
            <div class="make-image-result-actions">
              <a href="${esc(res.imageUrl)}" download="handraw-batch-${index + 1}.webp" class="btn btn-sm">下载图片</a>
            </div>
          </figcaption>
        `;
        grid.appendChild(fig);
        if (global.HANDRAW_SHARED?.triggerImageLoaders) {
          global.HANDRAW_SHARED.triggerImageLoaders(fig);
        }
      }
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

      // #141: keep the planned card editable in-place. Creating a per-card
      // override in fixed mode transitions to row mode without losing themes.
      const ensureSeriesRow = (index) => {
        if (loop.data.batchLayoutMode !== "ai" || !Array.isArray(loop.data.batchRows) || !loop.data.batchRows.length) {
          const themes = String(loop.data.promptListText || "").split(/\r?\n/).map(x => x.trim()).filter(Boolean);
          loop.data.batchRows = themes.map(theme => ({theme, layout: skill.data.layout || "", assetItems: []}));
          loop.data.batchLayoutMode = "ai";
        }
        while (loop.data.batchRows.length <= index) {
          loop.data.batchRows.push({theme:"", layout:skill.data.layout || "", assetItems:[]});
        }
        return loop.data.batchRows[index];
      };

      root.querySelectorAll("[data-series-theme-idx]").forEach(input => {
        const idx = Number(input.getAttribute("data-series-theme-idx"));
        if (!Number.isFinite(idx)) return;
        const syncTheme = () => {
          if (loop.data.batchLayoutMode === "ai") {
            const row = ensureSeriesRow(idx);
            row.theme = input.value;
            loop.data.promptListText = loop.data.batchRows.map(r => r.theme || "").join("\n");
          } else {
            const lines = String(loop.data.promptListText || "").split(/\r?\n/).filter(x => x.trim());
            if (idx < lines.length) {
              lines[idx] = input.value.replace(/\r?\n/g, " ").trim();
              loop.data.promptListText = lines.join("\n");
            }
          }
        };
        input.oninput = syncTheme;
        input.onblur = () => {
          syncTheme();
          if (self.actions?.persistDraft) self.actions.persistDraft();
          else markDirty();
        };
      });


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
        card.onkeydown = (event) => {
          if (event.target !== card || !["Enter", " "].includes(event.key)) return;
          event.preventDefault();
          card.onclick(event);
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
        btnStratFixed.onkeydown = (e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowDown") {
            e.preventDefault();
            btnStratAi?.focus();
            btnStratAi?.click();
          }
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
        btnStratAi.onkeydown = (e) => {
          if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
            e.preventDefault();
            btnStratFixed?.focus();
            btnStratFixed?.click();
          }
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

      // Restore a replan in-place; undo does not re-run the AI or charge.
      const undoPlan = root.querySelector("#batch-undo-plan");
      if (undoPlan) undoPlan.onclick = () => {
        if (!self.lastPlanUndo) return;
        loop.data.promptListText = self.lastPlanUndo.promptListText;
        loop.data.batchRows = self.lastPlanUndo.batchRows;
        self.lastPlanUndo = null;
        self.planNotice = "已恢复原规划";
        markDirty();
        self.render();
      };

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

          // Direct action: no confirmation modal. Preserve the existing
          // planning data so a user can undo an accidental re-plan.
          const priorPlan = hasExisting ? {
            promptListText: loop.data.promptListText || "",
            batchRows: JSON.parse(JSON.stringify(loop.data.batchRows || []))
          } : null;

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
            // Never leak the previously selected fixed layout into AI recommendations.
            fixedLayout: currentMode === "fixed" ? (skill.data.layout || "") : "",
            layoutRequirement: loop.data.batchLayoutReq || "",
            styleId: skill.data.style1 || ""
          };

          btnPlan.disabled = true;
          const labelSpan = btnPlan.querySelector("span");
          if (labelSpan) labelSpan.textContent = "AI 规划中…";
          else btnPlan.textContent = "AI 规划中…";

          try {
            const resp = await (global.HandrawTaskJourney?.withActivity
              ? global.HandrawTaskJourney.withActivity("AI 正在规划这套图", () => fetch("/api/studio/batch-plan", {
                  method: "POST",
                  credentials: "include",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(reqBody)
                }))
              : fetch("/api/studio/batch-plan", {
                  method: "POST",
                  credentials: "include",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(reqBody)
                }));
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
              const requestId = String(data.requestId || resp.headers?.get("X-Request-ID") || "");
              const incident = /^[a-f0-9]{32}$/i.test(requestId) ? `（问题编号：${requestId}）` : "";
              throw new Error((data.error || `HTTP ${resp.status}`) + incident);
            }

            const items = Array.isArray(data.items) ? data.items : [];
            if (priorPlan) {
              self.lastPlanUndo = priorPlan;
              // Replan undo is an inline affordance, not a disruptive dialog.
              self.planNotice = "规划已更新，可点击撤销恢复原列表";
            }
            if (currentMode === "fixed") {
              loop.data.promptListText = items.map((it) => it.subject).join("\n");
              loop.data.batchRows = [];
            } else {
              loop.data.batchRows = items.map((it) => ({ theme: it.subject, layout: it.layout || "" }));
              loop.data.promptListText = items.map((it) => it.subject).join("\n");
            }

            if (data.source === "template") {
              self.planNotice = priorPlan ? "模板规划已更新，可撤销" : "未使用 AI 规划，已按模板生成";
            } else if (!priorPlan) {
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
            const labelSpan = btnPlan.querySelector("span");
            if (labelSpan) labelSpan.textContent = "AI 规划这套图";
            else btnPlan.textContent = "AI 规划这套图";
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
          self.refreshSeriesCards();

        };
        promptsInput.onblur = () => {
          loop.data.promptListText = promptsInput.value;
          // Save without replacing the button receiving this blur's click.
          if (self.actions?.persistDraft) self.actions.persistDraft();
          else markDirty();
        };
      }

      // (i) AI mode table events - Theme modal trigger (readonly input)
      root.querySelectorAll(".batch-row-theme-input").forEach((inp) => {
        inp.onclick = () => {
          const idx = Number(inp.getAttribute("data-row-idx"));
          self.openThemeEditModal(idx, "row");
        };
        inp.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            const idx = Number(inp.getAttribute("data-row-idx"));
            self.openThemeEditModal(idx, "row");
          }
        };
      });

      root.querySelectorAll("[data-pick-layout-idx]").forEach((btn) => {
        btn.onclick = (e) => {
          if (e && e.target && e.target.closest && e.target.closest(".batch-row-layout-thumb-wrap")) {
            self.hideHoverPreview(true);
            const src = btn.getAttribute("data-zoom-src");
            const title = btn.getAttribute("data-zoom-title") || "图型预览";
            if (src && self.actions?.openImageLightbox) {
              self.actions.openImageLightbox(src, title);
              return;
            }
          }
          self.hideHoverPreview(true);
          const idx = Number(btn.getAttribute("data-pick-layout-idx"));
          const currentRow = loop.data.batchLayoutMode === "ai" ? loop.data.batchRows?.[idx] : null;
          const curLayout = currentRow?.layout || skill.data.layout || "";
          const onPick = (pickedId) => {
            ensureSeriesRow(idx).layout = pickedId || "";
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
          const currentRow = loop.data.batchLayoutMode === "ai" ? loop.data.batchRows?.[idx] : null;
          const curRefs = Array.isArray(currentRow?.assetItems) ? currentRow.assetItems : [];

          if (self.actions?.openReferencePicker) {
            self.actions.openReferencePicker({
              items: curRefs,
              currentRefs: curRefs,
              maxCount: 3,
              title: `第 ${idx + 1} 张参考图（最多 3 张）`,
              onConfirm: (selectedItems) => {
                ensureSeriesRow(idx).assetItems = selectedItems;
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
          ensureSeriesRow(idx).skipGlobalRefs = Boolean(chk.checked);
          markDirty();
        };
      });

      root.querySelectorAll("[data-del-row-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.getAttribute("data-del-row-idx"));
          if (loop.data.batchLayoutMode === "ai" && Array.isArray(loop.data.batchRows)) {
            loop.data.batchRows.splice(idx, 1);
            loop.data.promptListText = loop.data.batchRows.map((r) => r.theme).filter(Boolean).join("\n");
          } else {
            const lines = String(loop.data.promptListText || "").split(/\r?\n/).filter(Boolean);
            lines.splice(idx, 1);
            loop.data.promptListText = lines.join("\n");
          }
          markDirty();
        };
      });

      const btnAddRow = root.querySelector("#batch-btn-add-row");
      if (btnAddRow) {
        btnAddRow.onclick = () => {
          const nextIndex = self.resolveIterations().length;
          ensureSeriesRow(nextIndex);
          const row = loop.data.batchRows[nextIndex];
          row.theme = "";
          row.layout = skill.data.layout || "";
          row.assetItems = [];
          markDirty();
          return;
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

      // Default three in-flight requests, with a user-selectable 1-4 bound.
      const concurrencyControl = root.querySelector("#batch-concurrency");
      if (concurrencyControl) concurrencyControl.onchange = () => {
        loop.data.batchConcurrency = Math.max(1, Math.min(4, Number(concurrencyControl.value) || 3));
        markDirty();
      };

      // 7. Preview Row Retries & Results
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

      // 7.5. Batch Iteration Thumbnail Zoom (Lightbox)
      root.querySelectorAll(".batch-iter-thumb-btn").forEach((btn) => {
        btn.onclick = (e) => {
          if (e && e.stopPropagation) e.stopPropagation();
          self.hideHoverPreview(true);
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

      // 7.6. Batch Iteration Theme Editing (Modal)
      root.querySelectorAll("[data-iter-theme-idx]").forEach((el) => {
        el.onclick = (e) => {
          if (e && e.stopPropagation) e.stopPropagation();
          const idx = Number(el.getAttribute("data-iter-theme-idx"));
          self.openThemeEditModal(idx, "iter");
        };
        el.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            const idx = Number(el.getAttribute("data-iter-theme-idx"));
            self.openThemeEditModal(idx, "iter");
          }
        };
      });

      // 7.7. Bind Layout Hover Preview Singleton
      self.bindHoverPreview(root);

      // 7.8. Reset Form Button
      const btnReset = root.querySelector("#batch-btn-reset");
      if (btnReset) {
        btnReset.onclick = () => {
          const currentBusy = typeof self.actions?.isBusy === "function"
            ? self.actions.isBusy()
            : Boolean(self.context?.busy || self.progressState?.busy);
          if (currentBusy) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("任务处理中，暂不能清空或再次生成");
            return;
          }
          const ok = typeof window.confirm === "function"
            ? window.confirm("清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？")
            : true;
          if (!ok) return;

          if (typeof self.actions?.isBusy === "function" && self.actions.isBusy()) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("任务处理中，暂不能清空或再次生成");
            return;
          }

          ctrl.data.mode = "graphic-text";
          ctrl.data.ratio = "3:4";
          ctrl.data.count = 1;
          ctrl.data.status = "idle";
          delete ctrl.data.error;
          delete ctrl.data.activeBatchId;
          ctrl.data.elapsedSec = 0;

          skill.data.fusion = false;
          skill.data.style1 = "";
          skill.data.style2 = "";
          skill.data.layout = "";
          skill.data.colors = [];
          skill.data.tones = [];
          skill.data.moods = [];
          skill.data.customMood = "";
          skill.data.whitespace = "balanced";
          skill.data.audience = "";
          skill.data.businessScene = "";
          skill.data.sc021Type = "";
          skill.data.sc022Name = "";
          skill.data.sc022Pinyin = "";
          skill.data.negativePrompt = "";

          if (text?.data) {
            text.data.text = "";
            text.data.subjectHint = "";
          }

          loop.data.batchSeed = "";
          loop.data.batchCount = 6;
          loop.data.batchLayoutMode = "fixed";
          loop.data.batchLayoutReq = "";
          loop.data.batchRows = [];
          loop.data.promptListText = "早八一杯热美式\n晚霞中的单车\n周末雨天读旧诗集";
          loop.data.status = "idle";
          loop.data.currentStep = 0;
          delete loop.data.activeBatchId;

          const curAsset = parts.asset || bp?.asset;
          if (curAsset?.data) {
            curAsset.data.items = [];
          }
          if (self.actions?.ensureAssetItems) {
            self.actions.ensureAssetItems([]);
          }

          if (typeof self.actions?.clearWorkspaceResults === "function") {
            self.actions.clearWorkspaceResults(ctrl.id);
          } else {
            const graph = self.context?.graph;
            if (graph && Array.isArray(graph.edges) && Array.isArray(graph.nodes)) {
              const outEdges = graph.edges.filter((e) => e.from === ctrl.id);
              const outIds = new Set(outEdges.map((e) => e.to));
              graph.nodes.forEach((n) => {
                if (outIds.has(n.id) && n.type === "output_display") {
                  n.data.items = [];
                  n.data.status = "idle";
                  delete n.data.error;
                  delete n.data.pendingTaskId;
                  delete n.data.pendingRequestId;
                  delete n.data.activeBatchId;
                  delete n.data.selectedIdx;
                  delete n.data.previewIdx;
                  delete n.data.downloadUrl;
                  n.data.pendingRequestIds = {};
                  n.data.pendingSpec = {};
                  n.data.elapsedSec = 0;
                  if (n.data.kind === "batch_gallery") n.data.page = 1;
                }
              });
            }
          }

          if (Array.isArray(self.context?.results)) {
            self.context.results = [];
          }
          self.progressState = null;
          self.lastSummary = "";
          self.planNotice = "";
          markDirty();
        };
      }

      // 8. Start Batch Generation Button (M1: single confirmation via confirmPotentialGenerationCost)
      const btnStart = root.querySelector("#batch-btn-start");
      if (btnStart) {
        btnStart.onclick = async () => {
          const currentBusy = typeof self.actions?.isBusy === "function"
            ? self.actions.isBusy()
            : Boolean(self.context?.busy || self.progressState?.busy);
          if (currentBusy) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("任务处理中，暂不能清空或再次生成");
            return;
          }
          const currentIters = self.resolveIterations();
          const totalCount = currentIters.length;

          if (totalCount === 0) {
            const S = global.HANDRAW_SHARED;
            if (S?.toast) S.toast("请先添加要批量生成的项（文案、图型）");
            return;
          }

          if (self.actions?.run) {
            // Prevent same-tick double click even before async run flips busy.
            btnStart.disabled = true;
            Promise.resolve().then(() => self.actions.run()).catch((err) => {
              btnStart.disabled = false;
              const S = global.HANDRAW_SHARED;
              S?.toast?.(err?.message || "批量任务启动失败");
            });
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
            // Do not lock the UI if there is no active local batch to stop.
            const cancelled = self.actions.cancel();
            if (cancelled !== false) self.setStopping();
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

    isTouchDevice() {
      if (typeof window === "undefined" || !window.matchMedia) return false;
      return Boolean(
        window.matchMedia("(hover: none)").matches ||
        window.matchMedia("(pointer: coarse)").matches ||
        (typeof window.innerWidth === "number" && window.innerWidth <= 768)
      );
    }

    ensureHoverPreviewElement() {
      const doc = (typeof document !== "undefined" && typeof document.getElementById === "function")
        ? document
        : ((global.document && typeof global.document.getElementById === "function") ? global.document : null);
      if (!doc) {
        return this._hoverPreviewEl || null;
      }
      if (this._hoverPreviewEl && doc.body && doc.body.contains && doc.body.contains(this._hoverPreviewEl)) {
        return this._hoverPreviewEl;
      }
      let el = doc.getElementById("batch-layout-hover-preview");
      if (!el) {
        el = doc.createElement("div");
        el.id = "batch-layout-hover-preview";
        el.className = "batch-layout-hover-preview";
        el.setAttribute("aria-hidden", "true");
        el.style.display = "none";
        el.style.opacity = "0";
        el.innerHTML = `
          <div class="batch-hover-img-wrap">
            <img class="batch-hover-img" alt="" />
          </div>
          <div class="batch-hover-meta">
            <span class="batch-hover-code"></span>
            <span class="batch-hover-name"></span>
          </div>
        `;
        if (doc.body && doc.body.appendChild) {
          doc.body.appendChild(el);
        }
      }
      this._hoverPreviewEl = el;
      return el;
    }

    positionHoverPreview(el, clientX, clientY, triggerRect) {
      if (!el) return;
      const win = typeof window !== "undefined" ? window : null;
      const vw = win && win.innerWidth ? win.innerWidth : 1440;
      const vh = win && win.innerHeight ? win.innerHeight : 900;
      const pad = 12;
      const gap = 16;
      const w = 320;
      const h = el.offsetHeight || 280;

      let x = clientX !== undefined ? clientX + gap : (triggerRect ? triggerRect.right + gap : 100);
      let y = clientY !== undefined ? clientY + gap : (triggerRect ? triggerRect.top : 100);

      if (x + w + pad > vw) {
        if (clientX !== undefined) {
          x = clientX - w - gap;
        } else if (triggerRect) {
          x = triggerRect.left - w - gap;
        }
      }
      if (x + w + pad > vw) x = vw - w - pad;
      if (x < pad) x = pad;

      if (y + h + pad > vh) {
        if (clientY !== undefined) {
          y = clientY - h - gap;
        } else if (triggerRect) {
          y = triggerRect.bottom - h;
        }
      }
      if (y + h + pad > vh) y = vh - h - pad;
      if (y < pad) y = pad;

      el.style.left = `${Math.round(x)}px`;
      el.style.top = `${Math.round(y)}px`;
    }

    showHoverPreview({ src, code, name, clientX, clientY, triggerEl }) {
      if (!src || this.isTouchDevice()) return;
      const el = this.ensureHoverPreviewElement();
      if (!el) return;

      const img = el.querySelector(".batch-hover-img");
      const codeEl = el.querySelector(".batch-hover-code");
      const nameEl = el.querySelector(".batch-hover-name");

      const ImageConstructor = typeof Image !== "undefined" ? Image : (global.Image || null);
      if (ImageConstructor) {
        const testImg = new ImageConstructor();
        testImg.onload = () => {
          if (el.dataset.activeSrc !== src) return;
          if (img) {
            img.src = src;
            img.alt = name ? `${code} ${name}` : (code || "图型预览");
          }
          if (codeEl) {
            codeEl.textContent = code || "";
            codeEl.style.display = code ? "inline" : "none";
          }
          if (nameEl) {
            nameEl.textContent = name || "";
          }
          el.style.display = "block";
          this.positionHoverPreview(el, clientX, clientY, triggerEl && triggerEl.getBoundingClientRect ? triggerEl.getBoundingClientRect() : null);
          if (typeof requestAnimationFrame !== "undefined") {
            requestAnimationFrame(() => {
              if (el.dataset.activeSrc === src) {
                el.style.opacity = "1";
              }
            });
          } else {
            el.style.opacity = "1";
          }
        };
        testImg.onerror = () => {
          this.hideHoverPreview(true);
        };
        el.dataset.activeSrc = src;
        testImg.src = src;
      } else {
        if (img) img.src = src;
        if (codeEl) codeEl.textContent = code || "";
        if (nameEl) nameEl.textContent = name || "";
        el.style.display = "block";
        el.style.opacity = "1";
        el.dataset.activeSrc = src;
      }
    }

    hideHoverPreview(immediate = false) {
      this.clearHoverTimer();
      const el = this.ensureHoverPreviewElement();
      if (!el) return;
      el.dataset.activeSrc = "";
      if (immediate) {
        el.style.opacity = "0";
        el.style.display = "none";
      } else {
        el.style.opacity = "0";
        if (this._hoverHideTimer) clearTimeout(this._hoverHideTimer);
        this._hoverHideTimer = setTimeout(() => {
          if (el && !el.dataset.activeSrc) {
            el.style.display = "none";
          }
        }, 150);
      }
    }

    clearHoverTimer() {
      if (this._hoverTimer) {
        clearTimeout(this._hoverTimer);
        this._hoverTimer = null;
      }
    }

    bindHoverPreview(root) {
      const self = this;
      if (this.isTouchDevice()) return;

      const triggers = root.querySelectorAll ? root.querySelectorAll(".batch-row-layout-btn, .batch-iter-thumb-btn") : [];
      triggers.forEach((btn) => {
        const getMeta = () => ({
          src: btn.getAttribute("data-hover-src") || btn.getAttribute("data-zoom-src"),
          code: btn.getAttribute("data-hover-code") || "",
          name: btn.getAttribute("data-hover-name") || btn.getAttribute("data-zoom-title") || ""
        });

        if (btn.addEventListener) {
          btn.addEventListener("pointerenter", (e) => {
            if (self.isTouchDevice()) return;
            self.clearHoverTimer();
            const meta = getMeta();
            if (!meta.src) return;
            const clientX = e.clientX;
            const clientY = e.clientY;
            self._hoverTimer = setTimeout(() => {
              self.showHoverPreview({ ...meta, clientX, clientY, triggerEl: btn });
            }, 300);
          });

          btn.addEventListener("pointermove", (e) => {
            if (self.isTouchDevice()) return;
            if (self._hoverPreviewEl && self._hoverPreviewEl.style.display !== "none") {
              self.positionHoverPreview(self._hoverPreviewEl, e.clientX, e.clientY, btn.getBoundingClientRect ? btn.getBoundingClientRect() : null);
            } else if (self._hoverTimer) {
              const meta = getMeta();
              self.clearHoverTimer();
              self._hoverTimer = setTimeout(() => {
                self.showHoverPreview({ ...meta, clientX: e.clientX, clientY: e.clientY, triggerEl: btn });
              }, 300);
            }
          });

          btn.addEventListener("pointerleave", () => {
            self.hideHoverPreview();
          });

          btn.addEventListener("focus", () => {
            if (self.isTouchDevice()) return;
            self.clearHoverTimer();
            const meta = getMeta();
            if (!meta.src) return;
            self._hoverTimer = setTimeout(() => {
              self.showHoverPreview({ ...meta, triggerEl: btn });
            }, 300);
          });

          btn.addEventListener("blur", () => {
            self.hideHoverPreview(true);
          });
        }
      });

      if (typeof window !== "undefined" && !self._scrollListenerAttached && window.addEventListener) {
        window.addEventListener("scroll", () => {
          self.hideHoverPreview(true);
        }, { capture: true, passive: true });
        self._scrollListenerAttached = true;
      }
    }

    openThemeEditModal(idx, source = "row") {
      const self = this;
      const S = global.HANDRAW_SHARED;
      if (!S?.openModal) return;

      const p = this.getParts();
      const loop = p?.loop;
      if (!loop || !loop.data) return;

      const isAiMode = loop.data.batchLayoutMode === "ai" && Array.isArray(loop.data.batchRows);
      let currentTheme = "";
      if (isAiMode && loop.data.batchRows[idx]) {
        currentTheme = loop.data.batchRows[idx].theme != null ? String(loop.data.batchRows[idx].theme) : "";
      } else {
        const rawLines = (loop.data.promptListText || "").split(/\r?\n/);
        const nonEmpties = [];
        rawLines.forEach((l, lIdx) => {
          if (l.trim()) nonEmpties.push({ text: l, lineIdx: lIdx });
        });
        if (nonEmpties[idx]) {
          currentTheme = nonEmpties[idx].text;
        } else if (rawLines[idx] != null) {
          currentTheme = rawLines[idx];
        }
      }

      const MAX_CHARS = 200;
      const title = `编辑第 ${idx + 1} 张的主题`;

      S.openModal({
        title,
        sizeClass: "modal-md",
        html: `
          <div class="batch-theme-modal" style="display:flex;flex-direction:column;gap:12px;">
            <div class="make-image-field-wrap">
              <label class="make-image-field-label" for="batch-theme-modal-textarea">完整主题内容（最多 200 字）</label>
              <textarea
                id="batch-theme-modal-textarea"
                class="make-image-textarea batch-theme-modal-textarea"
                rows="8"
                placeholder="输入该张画面的核心主题或场景描述…"
                style="min-height:200px;width:100%;box-sizing:border-box;resize:vertical;font-size:14px;line-height:1.6;padding:12px;"
              >${esc(currentTheme)}</textarea>
              <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;font-size:12px;">
                <span id="batch-theme-modal-tip" style="color:var(--ink-muted);">按 Ctrl+Enter 快速保存，Esc 取消</span>
                <span id="batch-theme-modal-counter" style="color:var(--ink-muted);">
                  <span id="batch-theme-char-count">0</span> / 200 字
                </span>
              </div>
            </div>
            <div class="make-image-modal-actions" style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px;">
              <button type="button" class="btn btn-sm" id="batch-theme-btn-cancel">取消</button>
              <button type="button" class="btn btn-sm btn-primary" id="batch-theme-btn-save">保存</button>
            </div>
          </div>
        `,
        onMount(modalRoot) {
          const ta = modalRoot.querySelector("#batch-theme-modal-textarea");
          const countEl = modalRoot.querySelector("#batch-theme-char-count");
          const counterWrap = modalRoot.querySelector("#batch-theme-modal-counter");
          const tipEl = modalRoot.querySelector("#batch-theme-modal-tip");
          const btnSave = modalRoot.querySelector("#batch-theme-btn-save");
          const btnCancel = modalRoot.querySelector("#batch-theme-btn-cancel");

          const updateCount = () => {
            if (!ta || !countEl) return;
            const val = ta.value;
            const len = val.length;
            countEl.textContent = String(len);
            if (len > MAX_CHARS) {
              if (btnSave) btnSave.disabled = true;
              if (counterWrap) {
                counterWrap.style.color = "var(--error-color, #e03131)";
                counterWrap.style.fontWeight = "700";
              }
              if (tipEl) {
                tipEl.textContent = "字数已超出 200 字上限，请精简";
                tipEl.style.color = "var(--error-color, #e03131)";
              }
            } else {
              if (btnSave) btnSave.disabled = false;
              if (counterWrap) {
                counterWrap.style.color = "var(--ink-muted)";
                counterWrap.style.fontWeight = "normal";
              }
              if (tipEl) {
                tipEl.textContent = "按 Ctrl+Enter 快速保存，Esc 取消";
                tipEl.style.color = "var(--ink-muted)";
              }
            }
          };

          updateCount();
          if (ta) {
            ta.focus();
            try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (_) {}
            ta.oninput = updateCount;
            ta.onkeydown = (e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                doSave();
              } else if (e.key === "Escape") {
                e.preventDefault();
                S.closeModal();
              }
            };
          }

          const doSave = () => {
            if (!ta || (btnSave && btnSave.disabled)) return;
            const newTheme = ta.value;
            if (newTheme.length > MAX_CHARS) return;

            if (isAiMode && Array.isArray(loop.data.batchRows) && loop.data.batchRows[idx]) {
              loop.data.batchRows[idx].theme = newTheme;
              loop.data.promptListText = loop.data.batchRows.map((r) => r.theme).filter(Boolean).join("\n");
            } else {
              const rawLines = (loop.data.promptListText || "").split(/\r?\n/);
              const nonEmpties = [];
              rawLines.forEach((l, lIdx) => {
                if (l.trim()) nonEmpties.push(lIdx);
              });
              if (nonEmpties[idx] !== undefined) {
                rawLines[nonEmpties[idx]] = newTheme;
              } else if (rawLines[idx] !== undefined) {
                rawLines[idx] = newTheme;
              } else {
                rawLines.push(newTheme);
              }
              loop.data.promptListText = rawLines.join("\n");
              if (Array.isArray(loop.data.batchRows) && loop.data.batchRows[idx]) {
                loop.data.batchRows[idx].theme = newTheme;
              }
            }

            S.closeModal();

            if (self.actions?.markDirtyAndRender) {
              self.actions.markDirtyAndRender();
            } else {
              self.render();
            }

            setTimeout(() => {
              const rootEl = self.hostElement;
              if (!rootEl) return;
              if (source === "row") {
                const inp = rootEl.querySelector(`.batch-row-theme-input[data-row-idx="${idx}"]`);
                inp?.focus();
              } else {
                const btn = rootEl.querySelector(`[data-iter-theme-idx="${idx}"]`);
                btn?.focus();
              }
            }, 60);
          };

          if (btnSave) btnSave.onclick = doSave;
          if (btnCancel) btnCancel.onclick = () => S.closeModal();
        }
      });
    }
  }

  global.HandrawBatchCreate = new BatchCreateController();

})(typeof window !== "undefined" ? window : globalThis);
