/**
 * Handraw Web Studio - Make Image Component (Phase 3b-1 Compact Layout)
 *
 * Requirements:
 * - Operates directly on quick workflow nodes (skill_params, text_input, output_control, asset).
 * - No private recipe data structures; 100% two-way fidelity with canvas.
 * - Row 1: Single/Dual-Style fusion toggle + Generation mode (图文 / 纯图 / 海报) in ONE row.
 * - Row 2: Style, layout, theme color picker cards (3 slots or 4 slots when fusion + note).
 * - Row 3: Topic textarea.
 * - Row 4: Ratio buttons (小红书, 方图, 横版, 横屏视频, 竖屏短视频, 公众号封面) + inline ratio input.
 * - Collapsible "More Settings" (each item in ONE row):
 *   - Tones: 【选择影调】+ thumbnails in same row
 *   - Moods: 【选择情绪】+ text input in same row (comma separated, auto split to moods & customMood)
 *   - Whitespace: 【不限 / 正常 / 适中 / 大量】 buttons in same row
 *   - Audience & Business scene in same row
 *   - SC-021 play style in one row (when selected)
 *   - SC-022 name & pinyin in one row (when selected)
 *   - References: 【选择参考图】+ thumbnails in same row
 * - Collapsible "Prompt Preview": read-only, non-editable, live sync from assembleControlPrompt.
 * - Cost gate: strictly 1 image per request.
 * - Results: download, "再来一张", "换个主题".
 * - No emoji in UI text.
 */
(function (global) {
  "use strict";

  let activeSubjectFlush = null;

  function ensureBeforeUnloadHandler() {
    if (typeof window !== "undefined" && typeof window.addEventListener === "function" && !window.__handrawSubjectBeforeUnloadRegistered) {
      window.__handrawSubjectBeforeUnloadRegistered = true;
      window.addEventListener("beforeunload", () => {
        if (typeof activeSubjectFlush === "function") {
          activeSubjectFlush();
        }
      });
    }
  }

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

  function formatCostText({ loggedIn, freeRemaining, creditPerImage, dailyQuota, balance }) {
    const unitPrice = Number.isFinite(creditPerImage) && creditPerImage > 0 ? creditPerImage : 2;
    const dailyFree = Number.isFinite(dailyQuota) && dailyQuota > 0 ? dailyQuota : 3;
    if (!loggedIn) {
      return `每张 ${unitPrice} 积分，新用户每天免费 ${dailyFree} 张`;
    }
    const free = Number(freeRemaining || 0);
    const bal = Number(balance || 0);
    if (free > 0) {
      return `本次 1 张：免费（积分余额：${bal}）`;
    }
    return `本次 1 张：需 ${unitPrice} 积分（积分余额：${bal}）`;
  }

  class MakeImageController {
    constructor() {
      this.hostElement = null;
      this.context = null;
      this.actions = null;
      this.moreSettingsOpen = false;
      this.promptPreviewOpen = false;
      this.settingsCollapsed = false;
      this.compareOpen = false;
      this.recipeOpen = false;
      this.previewVersionKey = null;
      this.lastControlId = null;
    }

    getParts() {
      return this.context?.parts || null;
    }

    // The legacy nodes are the only writable truth. #121 normalizes them
    // on read and #122 writes back only the changed fields.
    getSpec() {
      const parts=this.getParts();
      const bridge=global.HandrawQuickSpec;
      return bridge && parts ? bridge.read(parts).spec : null;
    }

    patchSpec(delta, fallback) {
      const bridge=global.HandrawQuickSpec;
      if (!bridge) {
        if (typeof fallback === "function") fallback();
        return true;
      }
      try {
        bridge.apply(this.getParts(),delta,{
          catalog:this.context?.catalog,
          isUnlocked:this.actions?.isUnlocked
        });
        return true;
      } catch(err) {
        const r=global.HandrawStudioResources;
        const detail=r?.formatError?.({code:err.code})||"";
        global.HANDRAW_SHARED?.toast?.(
          err.code === "locked_field" ? "该参数已被用户锁定，无法自动覆盖" :
          err.code === "invalid_ratio" ? "画幅比例格式无效" :
          err.code === "invalid_output_mode" ? "该创作模式不可用" :
          err.code?.startsWith("resource_") || err.code?.startsWith("invalid_resource")
            ? detail+"（"+(err.field||"所选资源")+"）" :
          "创作参数修改失败："+(err.code||err.message)
        );
        return false;
      }
    }

    getGraph() {
      return this.context?.graph || null;
    }

    getPromptEngine() {
      return global.HandrawStudioPromptEngine || global.HANDRAW_CANVAS_ENGINE || null;
    }

    getPromptPreview() {
      const E = this.getPromptEngine();
      const p = this.getParts();
      const graph = this.getGraph();
      if (!E || !p || !graph) return "";
      try {
        return E.assembleControlPrompt(graph, p.ctrl, this.context?.catalog, "cloud") || "";
      } catch (_) {
        return "";
      }
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

    renderCostHtml() {
      const ctx = this.context || {};
      const settings = ctx.siteSettings || {};
      const creditPerImage = Number(settings.credit_cost_per_image || settings.creditCostPerImage || 2);
      const dailyQuota = Number(settings.daily_free_quota || settings.dailyFreeQuota || 3);
      const freeRemaining = Number(ctx.freeQuotaRemaining || 0);
      const balance = Number(ctx.credits || 0);

      const text = formatCostText({
        loggedIn: ctx.loggedIn,
        freeRemaining,
        creditPerImage,
        dailyQuota,
        balance
      });

      return `<span class="make-image-cost-text">${esc(text)}</span>`;
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

      const priorImage = this.hostElement.querySelector?.("#make-image-primary-media");
      const preservedImage = priorImage?.getAttribute("src") ? priorImage : null;
      const focused = typeof document !== "undefined" ? document.activeElement : null;
      const restore = focused?.id && this.hostElement.contains?.(focused) ? {
        id: focused.id, start: focused.selectionStart, end: focused.selectionEnd,
        scroll: focused.scrollTop
      } : null;
      const p = this.getParts();
      if (!p) {
        this.hostElement.innerHTML = `
          <div class="make-image-container">
            <div style="padding:48px 24px;text-align:center;color:var(--ink-muted);">
              <h3>正在载入创作工作流…</h3>
            </div>
          </div>
        `;
        return;
      }

      const sd = p.skill.data || {};
      const td = p.text.data || {};
      const cd = p.ctrl.data || {};
      const ad = p.asset?.data || {};
      // A read-only canonical projection: legacy nodes stay the only writable
      // draft until the Project API is migrated (#121/#122).
      const effectiveSpec=this.getSpec();
      if(effectiveSpec)this.context.effectiveCreationSpec=effectiveSpec;

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

      const topicText = td.text || "";

      const currentMode = cd.mode === "pure-image" ? "pure" : (cd.mode || "graphic-text");
      const currentRatio = cd.ratio || "3:4";

      const refItems = Array.isArray(ad.items) ? ad.items : [];

      const style1Obj = this.getResourceInfo(style1Id, "styles");
      const style2Obj = isFusion ? this.getResourceInfo(style2Id, "styles") : null;
      const layoutObj = this.getResourceInfo(layoutId, "layouts");
      const colorObj = selectedColors[0] ? this.getResourceInfo(selectedColors[0], "colors") : null;

      const currentPrompt = this.getPromptPreview();
      const authoritative=this.context?.runProjection;
      const localBusy=typeof this.actions?.isBusy==="function"
        ? Boolean(this.actions.isBusy()):Boolean(this.context?.localBusy);
      const remoteBusy=Boolean(authoritative?.ok && !authoritative.isTerminal);
      const busy=localBusy||remoteBusy;
      const results=authoritative?.ok
        ? authoritative.results.map((it,i)=>({id:it.id||"run-"+i,
            imageUrl:it.imageUrl,title:"生成结果 #"+(i+1),
            item:{mediaId:it.mediaId,runId:authoritative.runId}}))
        : (Array.isArray(this.context?.results)?this.context.results:[]);
      const statusText=this.context?.statusText||"";
      const forkSource = this.context?.forkSource || this.forkSource || null;

      this.hostElement.innerHTML = `
        <div class="make-image-container">
          <div class="make-image-head">
            <div class="make-image-head-left">
              <h1 class="make-image-title">做图</h1>
              <p class="make-image-lede">选择画风、图型与主题色，填写创作主题，快速生成高画质手绘图。</p>
            </div>
          </div>
          ${forkSource ? `
            <div class="make-image-fork-banner" style="background:var(--paper-soft,#f4efe6);border:1px solid var(--brand-vermilion,#e15b3c);border-radius:8px;padding:8px 14px;margin-bottom:12px;font-size:13px;display:flex;justify-content:space-between;align-items:center;">
              <span>⚡ <strong>配方来自 @${esc(forkSource.authorName || forkSource.author)}</strong></span>
              <span style="font-size:12px;color:var(--ink-muted);">参数已预填，确认生成后才结算</span>
            </div>
          ` : ""}

          <form class="make-image-form" novalidate onsubmit="return false;">
            <div class="make-image-main-grid">

              <!-- Output mode is independent from the style/layout relationship. -->
              <div class="make-image-top-row">
                <div class="make-image-inline-group">
                  <span class="make-image-field-label">生成方式</span>
                  <div class="make-image-btn-group" role="group" aria-label="生成方式">
                    ${OUTPUT_MODE_OPTIONS.map((m) => `
                      <button type="button" class="btn btn-sm ${currentMode === m.id ? "btn-primary is-active" : ""}" data-set-mode="${esc(m.id)}" aria-pressed="${currentMode === m.id}">${esc(m.label)}</button>
                    `).join("")}
                  </div>
                </div>
              </div>

              <!-- Style mode changes the style picker structure, so it is
                   grouped with the actual style/layout controls. -->
              <section class="make-image-resource-group" aria-label="画风与图型配置">
                <div class="make-image-resource-head">
                  <strong class="make-image-field-label">画风与图型</strong>
                  <div class="make-image-style-mode-switch">
                    <span class="make-image-field-label">画风模式</span>
                    <div class="make-image-btn-group" role="group" aria-label="画风模式">
                      <button type="button" class="btn btn-sm ${!isFusion ? "btn-primary is-active" : ""}" id="make-image-mode-single" aria-pressed="${!isFusion}">单画风</button>
                      <button type="button" class="btn btn-sm ${isFusion ? "btn-primary is-active" : ""}" id="make-image-mode-fusion" aria-pressed="${isFusion}">双画风融合</button>
                    </div>
                  </div>
                </div>
                <div class="make-image-pickers-row ${isFusion ? "has-style2" : ""}">
                  ${this.renderPickerSlot("style1", isFusion ? "角色画风" : "画风", style1Obj, true)}
                  ${isFusion ? this.renderPickerSlot("style2", "场景画风", style2Obj, true) : ""}
                  ${this.renderPickerSlot("layout", "图型", layoutObj, true)}
                  ${this.renderPickerSlot("color", "主题色", colorObj, true)}
                </div>
                ${isFusion ? `
                  <div class="make-image-style-note" role="note">角色画风决定主体，场景画风决定环境；切换模式会改变可选画风槽位，保留已选参数。</div>
                ` : ""}
              </section>

              <!-- Row 3: Topic / Subject Input -->
              <div class="make-image-field-wrap">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                  <label for="make-image-subject" class="make-image-field-label" style="margin-bottom:0;">创作主题</label>
                  <button type="button" class="btn btn-sm" id="make-image-clear-subject" style="font-size:11.5px;padding:2px 8px;color:var(--ink-muted);${topicText ? "" : "display:none;"}">清空主题</button>
                </div>
                <textarea
                  id="make-image-subject"
                  class="make-image-textarea"
                  rows="2"
                  placeholder="输入你想创作的画面内容或主题，例如：暖阳下的单车少女，在咖啡馆门口停留"
                  aria-label="创作主题"
                >${esc(topicText)}</textarea>
              </div>

              <!-- Row 4: Ratio Buttons & Ratio Text Input in ONE Row -->
              <div class="make-image-ratio-row">
                <span class="make-image-field-label">画幅</span>
                <div class="make-image-ratio-controls">
                  <div class="make-image-btn-group" role="group" aria-label="画幅比例">
                    ${RATIO_OPTIONS.map((r) => {
                      const isMatched = currentRatio === r.value;
                      return `
                        <button type="button" class="btn btn-sm ${isMatched ? "btn-primary is-active" : ""}" data-set-ratio="${esc(r.value)}" aria-pressed="${isMatched}">${esc(r.label)}</button>
                      `;
                    }).join("")}
                  </div>
                  <input
                    type="text"
                    id="make-image-ratio-input"
                    class="make-image-input make-image-ratio-input"
                    value="${esc(currentRatio)}"
                    placeholder="如 3:4"
                    aria-label="画幅比例数值"
                  />
                </div>
              </div>

              <!-- Collapsible: More Settings (每项一行) -->
              <div class="make-image-collapsible-card">
                <button type="button" class="make-image-collapsible-toggle" id="make-image-more-toggle" aria-expanded="${this.moreSettingsOpen}">
                  <span>更多设置（影调、情绪、留白、受众、业务场景${layoutId === "SC-021" ? "、SC-021玩法" : layoutId === "SC-022" ? "、SC-022签名" : ""}）</span>
                  <span class="make-image-toggle-icon" aria-hidden="true">${this.moreSettingsOpen ? "▲" : "▼"}</span>
                </button>
                <div class="make-image-collapsible-body" ${this.moreSettingsOpen ? "" : "hidden"}>
                  <div class="make-image-more-list">

                    <!-- 1. 影调：【选择影调】+ 已选缩略图紧跟在同一行 -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">影调</span>
                      <button type="button" class="btn btn-sm" id="make-image-pick-tones">选择影调</button>
                      <div class="make-image-more-thumbs" id="make-image-tones-row">
                        ${selectedTones.map((tid) => {
                          const tObj = this.getResourceInfo(tid, "tones");
                          const tName = tObj ? (tObj.name_zh || tObj.name || tid) : tid;
                          const tImg = tObj?.image || `/images/individual/TONES/${tid}.webp`;
                          return `
                            <div class="make-image-slot-card is-inline" data-tone-card="${esc(tid)}">
                              <div class="make-image-slot-thumb-wrap">
                                <img src="${esc(tImg)}" alt="${esc(tName)}" />
                                <button type="button" class="make-image-slot-clear" data-del-tone="${esc(tid)}" title="移除影调">×</button>
                              </div>
                              <div class="make-image-slot-meta">
                                <span class="make-image-slot-code">${esc(tid)}</span>
                                <span class="make-image-slot-title">${esc(tName)}</span>
                              </div>
                            </div>
                          `;
                        }).join("")}
                      </div>
                    </div>

                    <!-- 2. 情绪：【选择情绪】+ 文本框同一行 -->
                    <div class="make-image-more-row">
                      <label for="make-image-moods-input" class="make-image-more-label">情绪</label>
                      <button type="button" class="btn btn-sm" id="make-image-pick-moods">选择情绪</button>
                      <input
                        type="text"
                        id="make-image-moods-input"
                        class="make-image-input make-image-moods-input"
                        placeholder="情绪词用中文逗号分隔，如：治愈，诗意，微醺"
                        value="${esc(moodTextValue)}"
                        aria-label="情绪设定"
                      />
                    </div>

                    <!-- 3. 留白：【不限 / 正常 / 适中 / 大量】按钮同一行 -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">留白</span>
                      <div class="make-image-btn-group" role="group" aria-label="留白">
                        ${WHITESPACE_OPTIONS.map((w) => `
                          <button type="button" class="btn btn-sm ${whitespace === w.value ? "btn-primary is-active" : ""}" data-set-ws="${esc(w.value)}" aria-pressed="${whitespace === w.value}">${esc(w.label)}</button>
                        `).join("")}
                      </div>
                    </div>

                    <!-- 4. 受众：[框]　业务场景：[框] —— 同一行 -->
                    <div class="make-image-more-row make-image-duo-row">
                      <div class="make-image-inline-field">
                        <label for="make-image-audience" class="make-image-more-label">受众：</label>
                        <input type="text" id="make-image-audience" class="make-image-input" placeholder="如：年轻女性、亲子家庭" value="${esc(audience)}" />
                      </div>
                      <div class="make-image-inline-field">
                        <label for="make-image-business-scene" class="make-image-more-label">业务场景：</label>
                        <input type="text" id="make-image-business-scene" class="make-image-input" placeholder="如：社交媒体配图、文创包装" value="${esc(businessScene)}" />
                      </div>
                    </div>

                    <!-- 5. SC-021 玩法：仅选了对应图型时出现，一行 -->
                    ${layoutId === "SC-021" ? `
                      <div class="make-image-more-row">
                        <label for="make-image-sc021-select" class="make-image-more-label">SC-021 玩法：</label>
                        <select id="make-image-sc021-select" class="make-image-select">
                          ${SC021_PLAYSTYLES.map((p) => `<option value="${esc(p)}" ${p === sc021Type ? "selected" : ""}>${esc(p)}</option>`).join("")}
                        </select>
                      </div>
                    ` : ""}

                    <!-- 6. SC-022 姓名/拼音：仅选了对应图型时出现，一行 -->
                    ${layoutId === "SC-022" ? `
                      <div class="make-image-more-row">
                        <span class="make-image-more-label">SC-022 姓名/拼音：</span>
                        <div class="make-image-inline-inputs">
                          <input type="text" id="make-image-sc022-name" class="make-image-input" placeholder="姓名（如：林知夏）" value="${esc(sc022Name)}" />
                          <input type="text" id="make-image-sc022-pinyin" class="make-image-input" placeholder="拼音（如：LIN ZHIXIA）" value="${esc(sc022Pinyin)}" />
                        </div>
                      </div>
                    ` : ""}

                    <!-- 7. 参考图：【选择参考图】+ 已选缩略图同一行 -->
                    <div class="make-image-more-row">
                      <span class="make-image-more-label">参考图</span>
                      <button type="button" class="btn btn-sm btn-primary" id="make-image-open-ref-picker">选择参考图</button>
                      <div class="make-image-more-thumbs" id="make-image-refs-row">
                        ${refItems.map((u, idx) => {
                          const imgUrl = typeof u === "string" ? u : (u.image || u.url || "");
                          const imgName = typeof u === "string" ? `P${idx + 1}` : (u.name || u.id || `P${idx + 1}`);
                          return `
                            <div class="make-image-slot-card is-inline" data-ref-card="${idx}">
                              <div class="make-image-slot-thumb-wrap">
                                <img src="${esc(imgUrl)}" alt="${esc(imgName)}" />
                                <button type="button" class="make-image-slot-clear" data-del-ref="${idx}" title="删除此参考图">×</button>
                              </div>
                              <div class="make-image-slot-meta">
                                <span class="make-image-slot-code">P${idx + 1}</span>
                                <span class="make-image-slot-title">${esc(imgName)}</span>
                              </div>
                            </div>
                          `;
                        }).join("")}
                      </div>
                    </div>

                  </div>
                </div>
              </div>

              <!-- Collapsible: Prompt Preview (只读, 可复制, 不可编辑) -->
              <div class="make-image-collapsible-card">
                <button type="button" class="make-image-collapsible-toggle" id="make-image-prompt-toggle" aria-expanded="${this.promptPreviewOpen}">
                  <span>查看提示词（实际发出的完整提示词）</span>
                  <span class="make-image-toggle-icon" aria-hidden="true">${this.promptPreviewOpen ? "▲" : "▼"}</span>
                </button>
                <div class="make-image-collapsible-body" ${this.promptPreviewOpen ? "" : "hidden"}>
                  <div class="make-image-prompt-inner">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                      <span style="font-size:12px;color:var(--ink-muted);">由系统根据当前参数实时组装，生成时原样发送至模型服务：</span>
                      <button type="button" class="btn btn-sm" id="make-image-copy-prompt">复制提示词</button>
                    </div>
                    <textarea
                      id="make-image-prompt"
                      class="make-image-textarea is-readonly"
                      rows="6"
                      readonly
                      aria-label="提示词预览"
                    >${esc(currentPrompt)}</textarea>
                  </div>
                </div>
              </div>

              <!-- Action & Cost Row (同一行) -->
              <div class="make-image-action-bar">
                <div class="make-image-cost" aria-live="polite">
                  ${this.renderCostHtml()}
                </div>
                <div class="make-image-btn-wrap">
                  ${busy ? `<span class="make-image-busy-hint">${localBusy?"正在提交/本地等待；停止不能保证取消已提交任务或退款":"服务端任务仍在进行，可刷新恢复并查看历史"}</span>` : ""}
                  <button type="button" class="btn btn-sm make-image-btn-reset" id="make-image-btn-reset" ${busy || this.context?.pendingCloud ? "disabled" : ""}>清空表单</button>
                  ${localBusy ? '<button type="button" class="btn btn-sm" id="make-image-btn-stop">停止等待</button>' : ""}
                  <button type="button" class="btn btn-sm" id="make-image-btn-ai-plan" ${this.isPlanning ? 'disabled' : ''} title="根据主题和实际可用画风、图型规划，不触发付费生图">${this.isPlanning ? 'AI 正在规划…' : 'AI 辅助设计'}</button>
                   ${this.context?.planUndoAvailable ? '<button type="button" class="btn btn-sm" id="make-image-btn-ai-undo">撤销 AI 规划</button>' : ''}
                  ${authoritative?.canRetry && !busy ? '<button type="button" class="btn btn-sm" id="make-image-btn-retry">重试失败项</button>' : ""}
                  <button type="button" class="btn btn-primary make-image-btn-run" id="make-image-btn-run" ${busy ? "disabled" : ""}>
                    ${busy ? "正在生成中…" : "开始生成 (1张)"}
                  </button>
                </div>
              </div>

               ${this.context?.aiPhase?'<p id="make-image-ai-status" role="status" aria-live="polite" style="font-size:12px;">'+esc(this.context.aiPhase)+'</p>':''}
               ${this.context?.aiProposal?.reasons?`<div class="make-image-ai-reasons" aria-label="AI 字段推荐理由" style="font-size:12px;padding:10px 0;line-height:1.7">
                 <strong>AI 推荐理由</strong>
                 <div>画风：${esc(this.context.aiProposal.reasons.style||"")}</div>
                 <div>图型：${esc(this.context.aiProposal.reasons.layout||"")}</div>
                 <div>画幅：${esc(this.context.aiProposal.reasons.ratio||"")}</div>
               </div>`:""}
              <!-- Status text -->
              ${statusText ? `<div class="make-image-status" role="status">${esc(statusText)}</div>` : ""}

              <!-- Results Gallery -->
              <div class="make-image-results-section make-image-result-workspace" aria-label="图片创作结果">
                ${results.length ? `
                  <div class="make-image-results-head">
                    <h3 style="margin:0;font-size:15px;font-weight:700;">生成结果 (${results.length} 张)</h3>
                    <div style="display:flex;gap:8px;">
                      <button type="button" class="btn btn-sm" id="make-image-btn-again">再来一张</button>
                      <button type="button" class="btn btn-sm" id="make-image-btn-new-theme">换个主题</button>
                    </div>
                  </div>
                  <div class="make-image-results-grid">
                    ${results.map((r, idx) => `
                      <div class="make-image-result-card" data-result-id="${esc(r.id)}">
                        <div class="make-image-result-thumb">
                          <img src="${esc(r.imageUrl)}" alt="生成结果 #${idx + 1}" loading="lazy" />
                        </div>
                        <div class="make-image-result-caption">
                          <strong class="make-image-result-title">${esc(r.title || `结果 #${idx + 1}`)}</strong>
                          <div class="make-image-result-actions">
                            <button type="button" class="btn btn-sm" data-action="view" data-result-idx="${idx}">查看大图</button>
                            <button type="button" class="btn btn-sm btn-primary" data-action="download" data-url="${esc(r.imageUrl)}">下载</button>
                            <button type="button" class="btn btn-sm" data-action="reference" data-result-idx="${idx}">作为参考图</button>
                            <button type="button" class="btn btn-sm" data-action="canvas">进入画布</button>
                          </div>
                        </div>
                      </div>
                    `).join("")}
                  </div>
              ` : `
                  <div class="make-image-empty-result" role="status">
                    <div class="make-image-empty-result-icon" aria-hidden="true">▧</div>
                    <strong>${busy ? "图片正在生成中…" : "创作结果将在这里显示"}</strong>
                    <p>${remoteBusy?"服务器正在执行已提交的任务，刷新不会遗失请求编号。":busy?"停止只结束本地等待，云端任务以服务器为准。":"左侧输入主题并选择画风，生成成功后可查看大图、下载或继续创作。"}</p>
                  </div>
              `}
              </div>

            </div>
          </form>
        </div>
      `;

      this.upgradeWorkspace(this.hostElement);
      if (preservedImage) {
        const fresh = this.hostElement.querySelector("#make-image-primary-media");
        if (fresh && fresh.getAttribute("src") === preservedImage.getAttribute("src")) {
          fresh.replaceWith(preservedImage);
        }
      }
      this.bindEvents(this.hostElement);
      this.bindWorkspaceEvents(this.hostElement);
      if (restore) {
        const target = this.hostElement.querySelector("#" + restore.id);
        if (target && typeof target.focus === "function") {
          target.focus({preventScroll:true});
          try {
            if (Number.isInteger(restore.start) && typeof target.setSelectionRange === "function")
              target.setSelectionRange(restore.start,restore.end);
          } catch (_) {}
          target.scrollTop = restore.scroll;
        }
      }
    }


    // Reorganize existing controls without recreating field logic or pickers.
    // Moving real DOM nodes is deliberate: all legacy SC-021/022 and fusion
    // inputs remain present and their old bindEvents handlers stay active.
    upgradeWorkspace(root) {
      const p=this.getParts();
      if (!p) return;
      const ctrl=p.ctrl.data;
      if (this.lastControlId!==p.ctrl.id) {
        this.previewVersionKey=null;
        this.compareOpen=false;
        this.recipeOpen=false;
        this.settingsCollapsed=false;
        this.lastControlId=p.ctrl.id;
      }
      const grid=root.querySelector(".make-image-main-grid");
      const form=root.querySelector(".make-image-form");
      const result=root.querySelector(".make-image-results-section");
      if (!grid||!form||!result) return;
      const advanced=root.querySelector(".make-image-more-list");
      const subject=root.querySelector(".make-image-field-wrap");
      const mode=root.querySelector(".make-image-top-row");
      const pickerRow=root.querySelector(".make-image-pickers-row");
      const color=root.querySelector('[data-pick-kind="color"]');
      if(subject) grid.insertBefore(subject,grid.firstChild);
      if(advanced&&mode)advanced.insertBefore(mode,advanced.firstChild);
      if(advanced&&color)advanced.insertBefore(color,advanced.children[1]||null);
      const refs=root.querySelector("#make-image-open-ref-picker")?.closest(".make-image-more-row");
      if(refs){
        const refPanel=document.createElement("div");
        refPanel.className="make-image-quick-references";
        refPanel.innerHTML='<div class="make-image-ref-heading"><strong>参考素材</strong><span>支持多图、粘贴及拖放 · 仅选用，不自动生成</span></div>'+
          '<div id="make-image-ref-dropzone" class="make-image-ref-dropzone" tabindex="0" aria-label="粘贴或拖放参考图片">'+
          '<button type="button" class="btn btn-sm" id="make-image-ref-upload">＋ 上传多张图片</button>'+
          '<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden id="make-image-ref-files" />'+
          '<span>或将图片拖入此处 / Ctrl+V 粘贴</span></div>';
        refPanel.appendChild(refs);
        if(advanced?.parentNode?.parentNode)grid.insertBefore(refPanel,grid.querySelector(".make-image-ratio-row"));
        const items=Array.isArray(p.asset?.data?.items)?p.asset.data.items:[];
        refs.querySelectorAll("[data-ref-card]").forEach(card=>{
          const i=Number(card.getAttribute("data-ref-card"));
          const entry=items[i];
          const chooser=document.createElement("select");
          chooser.className="make-image-ref-role";
          chooser.setAttribute("data-ref-role",String(i));
          chooser.setAttribute("aria-label","参考图用途");
          const roles=[["other","通用参考"],["character","人物/角色"],["scene","场景"],["object","道具/物品"],["composition","构图"]];
          chooser.innerHTML=roles.map(pair=>'<option value="'+pair[0]+'"'+(entry?.role===pair[0]?' selected':'')+'>'+pair[1]+'</option>').join("");
          card.appendChild(chooser);
        });
      }
      const layout=document.createElement("div");
      layout.className="make-image-workspace-layout";
      const settings=document.createElement("section");
      settings.className="make-image-settings-panel";
      const toggle=document.createElement("button");
      toggle.type="button";
      toggle.id="make-image-settings-collapse";
      toggle.className="make-image-settings-collapse";
      toggle.setAttribute("aria-expanded",String(!this.settingsCollapsed));
      toggle.textContent=this.settingsCollapsed?"展开创作设置":"收起创作设置";
      settings.appendChild(toggle);
      grid.parentNode.insertBefore(layout,grid);
      settings.appendChild(grid);
      layout.appendChild(settings);
      layout.appendChild(result);
      if(this.settingsCollapsed)settings.classList.add("is-collapsed");

      const V=global.HandrawQuickVersions;
      const remote=this.context?.runProjection;
      const live=Array.isArray(this.context?.results)?this.context.results:[];
      const remoteItems=remote?.ok ? (remote.results||[]).map(it=>({
        id:it.id,mediaId:it.mediaId,runId:remote.runId,
        imageUrl:it.imageUrl,title:"生成图片",item:{...it,runId:remote.runId}
      })) : [];
      const prior=Array.isArray(ctrl.quickVersionHistory)?ctrl.quickVersionHistory:[];
      const versions=V?V.merge(prior,[...live,...remoteItems],{
        runId:remote?.runId||ctrl.runId||"",
        runSpec:ctrl.quickLastSubmittedSpec||null
      }):prior;
      if(V&&JSON.stringify(prior)!==JSON.stringify(versions)){
        ctrl.quickVersionHistory=versions;
        this.actions?.persistDraft?.();
      }
      this.visibleVersions=versions;
      const selected=V?.select(versions,this.previewVersionKey);
      const selectedIndex=selected?versions.findIndex(v=>v.key===selected.key):-1;
      const other=selectedIndex>0?versions[selectedIndex-1]:
        selectedIndex===0&&versions.length>1?versions[1]:null;
      const state=remote?.ok?(remote.viewStatus||remote.persistedStatus||"unknown"):
        this.context?.localBusy?"running":ctrl.status==="stopped"?"cancel_requested":
        ctrl.status==="error"?"failed":this.context?.pendingCloud?"unknown":"idle";
      const statusMap={
        idle:"可以开始创作",pending:"已提交 · 等待服务器确认",queued:"排队中",
        running:"生成中 · 可以继续编辑左侧下一版草稿",uploading:"素材上传中",
        success:"本次生成成功",partial:"部分完成",failed:"生成失败 · 旧版本仍可使用",
        cancel_requested:"已停止本地等待 · 云端仍可能继续执行",
        cancelled:"服务端确认取消",unknown:"状态待核对 · 请勿重复提交"
      };
      const busy=Boolean(this.context?.localBusy || (remote?.ok&&!remote.isTerminal) || this.context?.pendingCloud);
      if(versions.length)layout.classList.add("has-results");
      const safeValue=v=>esc(v==null?"":v);
      const snapshot=selected?.recipeSnapshot||null;
      const snapText=snapshot?JSON.stringify(snapshot,null,2):"这张历史图片没有可验证的 CreationSpec 快照；不会用当前草稿冒充本次配方。";
      result.innerHTML='<header class="make-image-result-header"><div><small>图片创作 · 结果工作台</small>'+
        '<h2>当前结果 <span>'+versions.length+' 个版本</span></h2></div>'+
        '<button type="button" class="btn btn-sm" data-quick-action="compare" '+(versions.length<2?'disabled':'')+'>'+
        (this.compareOpen?"关闭对比":"版本对比")+'</button></header>'+
        '<div class="make-image-run-status" role="status" aria-live="polite"><span class="make-image-status-dot '+safeValue(state)+'"></span>'+
        '<span>'+safeValue(statusMap[state]||"正在核对任务状态")+'</span>'+
        (remote?.runId?'<code>Run '+safeValue(String(remote.runId).slice(0,18))+'</code>':"")+'</div>'+
        (selected?
          '<figure class="make-image-current-result"><div class="make-image-current-image">'+
          '<img id="make-image-primary-media" src="'+safeValue(selected.imageUrl)+'" data-version-key="'+safeValue(selected.key)+
          '" alt="'+safeValue(selected.title||"生成图片")+'" />'+
          '</div><figcaption><strong>版本 '+(selectedIndex+1)+'</strong>'+
          '<span>'+safeValue(selected.title||"生成图片")+'</span>'+
          (selected.runId?'<small>Run '+safeValue(String(selected.runId).slice(0,18))+'</small>':"")+'</figcaption></figure>':
          '<div class="make-image-empty-result" role="status"><strong>'+(busy?"任务已提交，正在等待生成结果":"创作结果将在这里出现")+
          '</strong><p>'+(busy?"旧版本会继续保留；可在左侧准备下一次创作。":"输入主题，选择画风与图型，然后生成第一张图片。")+'</p></div>')+
        (selected?'<div class="make-image-result-toolbar" aria-label="当前图片操作">'+
          '<button type="button" class="btn btn-sm" data-quick-action="view">放大</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="download">原图下载</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="again" '+(busy?'disabled':'')+'>同配方再来一张</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="reference">作为参考</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="variant">生成变体</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="recipe">真实配方</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="series">进入系列</button>'+
          '<button type="button" class="btn btn-sm" data-quick-action="canvas">进入画布</button>'+
          '</div>':"")+
        (selected&&this.recipeOpen?'<pre class="make-image-recipe-snapshot">'+safeValue(snapText)+'</pre>':"")+
        (versions.length?'<div class="make-image-version-section"><h3>创作版本 · 选择缩略图查看</h3>'+
          '<div class="make-image-version-strip" role="list">'+versions.map((v,i)=>
            '<button type="button" role="listitem" class="make-image-version-tile '+(selected?.key===v.key?"is-selected":"")+
            '" data-quick-version="'+safeValue(v.key)+'" aria-label="选择版本 '+(i+1)+'" aria-pressed="'+(selected?.key===v.key)+'">'+
            '<img src="'+safeValue(v.imageUrl)+'" alt="" loading="lazy" /><small>V'+(i+1)+'</small></button>'
          ).join("")+'</div></div>':"")+
        (this.compareOpen&&selected&&other?
          '<div class="make-image-comparison"><h3>版本并排比较</h3><div class="make-image-compare-grid">'+
          [other,selected].map(v=>'<figure><img src="'+safeValue(v.imageUrl)+'" alt="'+safeValue(v.title)+'" />'+
            '<figcaption>'+safeValue(v.mediaId)+(v.recipeSnapshot?
              '<pre>'+safeValue(JSON.stringify({style:v.recipeSnapshot.style?.id,layout:v.recipeSnapshot.layout?.id,
                ratio:v.recipeSnapshot.ratio,subject:v.recipeSnapshot.subject},null,2))+'</pre>':
              '<small>配方快照不可用</small>')+'</figcaption></figure>').join("")+
          '</div></div>':"");
      const aiReview=this.context?.aiReview;
      if(aiReview?.changes?.length){
        const anchor=grid.querySelector(".make-image-action-bar");
        const card=document.createElement("div");
        card.className="make-image-ai-review";
        card.innerHTML='<h3>AI 辅助设计建议 · 审阅后采纳</h3><p>只建议已授权资源；不会自动生成或扣费。原有人工选择默认保留。</p>'+
          aiReview.changes.map((c,i)=>'<label class="make-image-ai-choice">'+
            '<input type="checkbox" data-quick-ai-choice="'+i+'" '+(c.locked?'disabled':c.conflict?'':'checked')+' />'+
            '<span><strong>'+safeValue(c.field)+'</strong> '+safeValue(c.from?.id||c.from||"未选")+
            ' → '+safeValue(c.to?.id||c.to||"未选")+
            '<small>'+safeValue(c.reason||"")+(c.locked?" · 已锁定，不能覆盖":c.conflict?" · 人工设置，需明确勾选":"")+'</small></span></label>').join("")+
          '<div class="make-image-ai-review-actions"><button type="button" class="btn btn-sm" data-quick-ai="discard">保留原方案</button>'+
          '<button type="button" class="btn btn-primary btn-sm" data-quick-ai="accept">采纳选中建议</button></div>';
        grid.insertBefore(card,anchor||null);
      }
    }

    bindWorkspaceEvents(root) {
      const p=this.getParts();
      if(!p)return;
      const versions=this.visibleVersions||[];
      const selected=()=>versions.find(v=>v.key===this.previewVersionKey)||versions[versions.length-1]||null;
      const toast=msg=>global.HANDRAW_SHARED?.toast?.(msg);
      root.querySelector("#make-image-settings-collapse")?.addEventListener("click",()=>{
        this.settingsCollapsed=!this.settingsCollapsed;this.render();
      });
      root.querySelectorAll("[data-quick-version]").forEach(btn=>btn.addEventListener("click",()=>{
        this.previewVersionKey=btn.getAttribute("data-quick-version");
        this.compareOpen=false;this.render();
      }));
      root.querySelectorAll("[data-quick-action]").forEach(btn=>btn.addEventListener("click",()=>{
        const v=selected();
        const action=btn.getAttribute("data-quick-action");
        if(action==="compare"){this.compareOpen=!this.compareOpen;this.render();return;}
        if(!v)return;
        if(action==="view")return this.actions?.openImageLightbox?.(v.imageUrl,v.title);
        if(action==="download"){
          const a=document.createElement("a");a.href=v.imageUrl;a.download="handraw-"+v.mediaId+".webp";
          a.rel="noopener";a.click();return;
        }
        if(action==="recipe"){this.recipeOpen=!this.recipeOpen;this.render();return;}
        if(action==="canvas")return this.actions?.openCanvas?.(v);
        if(action==="series")return this.actions?.openSeries?.(v);
        if(action==="reference"||action==="variant"){
          this.actions?.addResultAsReference?.({imageUrl:v.imageUrl,title:v.title,item:{mediaId:v.mediaId}});
          if(action==="variant"){
            toast("已将选中版本加入参考；请描述希望保留及修改的内容，再生成变体");
            this.hostElement?.querySelector("#make-image-subject")?.focus();
          }return;
        }
        if(action==="again"){
          const spec=v.recipeSnapshot;
          if(!spec){toast("历史结果缺少真实配方快照，不能冒充同配方生成；请使用当前设置生成");return;}
          const delta={};
          for(const field of ["subject","style","secondaryStyle","layout","colors","tones",
            "moods","customMood","whitespace","audience","businessScene",
            "outputMode","ratio","fusionEnabled","layoutParams"]){
            if(Object.prototype.hasOwnProperty.call(spec,field))delta[field]=spec[field];
          }
          if(!this.patchSpec(delta))return;
          this.actions?.persistDraft?.();
          this.actions?.run?.();
        }
      }));
      root.querySelectorAll("[data-quick-ai]").forEach(btn=>btn.addEventListener("click",()=>{
        const report=this.context?.aiReview;
        if(btn.getAttribute("data-quick-ai")==="discard")return this.actions?.discardPlan?.();
        const approved=[...root.querySelectorAll("[data-quick-ai-choice]:checked")].map(input=>
          report?.changes?.[Number(input.getAttribute("data-quick-ai-choice"))]?.key).filter(Boolean);
        this.actions?.applyPlan?.(approved);
      }));
      root.querySelectorAll("[data-ref-role]").forEach(select=>select.addEventListener("change",()=>{
        const idx=Number(select.getAttribute("data-ref-role"));
        const items=(p.asset?.data?.items||[]).map((v,i)=>i===idx?{...v,role:select.value}:v);
        this.actions?.ensureAssetItems?.(items);
      }));
      const fileInput=root.querySelector("#make-image-ref-files");
      root.querySelector("#make-image-ref-upload")?.addEventListener("click",()=>fileInput?.click());
      fileInput?.addEventListener("change",()=>{
        if(fileInput.files?.length)this.actions?.uploadReferenceFiles?.([...fileInput.files]);
        fileInput.value="";
      });
      const zone=root.querySelector("#make-image-ref-dropzone");
      zone?.addEventListener("dragover",e=>{e.preventDefault();zone.classList.add("is-dragging");});
      zone?.addEventListener("dragleave",()=>zone.classList.remove("is-dragging"));
      zone?.addEventListener("drop",e=>{
        e.preventDefault();zone.classList.remove("is-dragging");
        if(e.dataTransfer?.files?.length)this.actions?.uploadReferenceFiles?.([...e.dataTransfer.files]);
      });
      // Re-renders share the same host: assign once instead of stacking handlers.
      root.onpaste=e=>{
        const files=[...(e.clipboardData?.items||[])].filter(i=>i.kind==="file"&&i.type.startsWith("image/"))
          .map(i=>i.getAsFile()).filter(Boolean);
        if(files.length){e.preventDefault();this.actions?.uploadReferenceFiles?.(files);}
      };
    }

    bindEvents(root) {
      const p = this.getParts();
      if (!p) return;
      const busy = Boolean(this.context?.busy);
      const sd = p.skill.data;
      const td = p.text.data;
      const cd = p.ctrl.data;
      const ad = p.asset?.data;

      // 1. Single / Fusion toggle
      const btnSingle = root.querySelector("#make-image-mode-single");
      if (btnSingle) {
        btnSingle.onclick = () => {
          if (this.patchSpec({fusionEnabled:false},()=>{sd.fusion=false})) {
            // The second style remains stored, but is not sent in a Run.
            this.actions?.markDirtyAndRender();
          }
        };
      }
      const btnFusion = root.querySelector("#make-image-mode-fusion");
      if (btnFusion) {
        btnFusion.onclick = () => {
          if (this.patchSpec({fusionEnabled:true},()=>{sd.fusion=true}))
            this.actions?.markDirtyAndRender();
        };
      }

      // 2. Main Pickers (style1, style2, layout, color)
      root.querySelectorAll("[data-pick-kind]").forEach((card) => {
        card.onclick = (e) => {
          if (e.target.closest(".make-image-picker-clear")) return;
          const kind = card.getAttribute("data-pick-kind");
          const field = kind === "style1" ? "style1" : kind === "style2" ? "style2" : kind === "layout" ? "layout" : "colors";
          const currentId = kind === "color" ? (sd.colors?.[0] || "") : (sd[field] || "");

          if (typeof this.actions?.openAssetPicker !== "function") {
            global.HANDRAW_SHARED?.toast?.("资源选择器尚未就绪，请刷新创作台重试");
            return;
          }
          this.actions.openAssetPicker({
            field,
            kind,
            currentId,
            onSelect: (id, ref) => {
              const names={style1:"style",style2:"secondaryStyle",layout:"layout",colors:"colors"};
              const key=names[field];
              if (this.patchSpec({[key]:kind==="color"?(id?[ref||id]:[]):(ref||id||null)},()=>{
                if (kind==="color") sd.colors=id?[id]:[];
                else sd[field]=id||"";
                sd.resourceRefs={...(sd.resourceRefs||{}),
                  [key]:kind==="color"?(ref?[ref]:[]):(ref||null)};
              })) this.actions?.markDirtyAndRender();
            }
          });
        };
        card.onkeydown = (event) => {
          if (event.target !== card || !["Enter", " "].includes(event.key)) return;
          event.preventDefault();
          card.onclick(event);
        };
      });

      // Clear buttons for main pickers
      root.querySelectorAll("[data-clear-kind]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const kind = btn.getAttribute("data-clear-kind");
          const field={style1:"style",style2:"secondaryStyle",layout:"layout",color:"colors"}[kind];
          if (field && this.patchSpec({[field]:field==="colors"?[]:null},()=>{
            if(kind==="color") sd.colors=[];
            else sd[kind]="";
            if(sd.resourceRefs)sd.resourceRefs[field]=field==="colors"?[]:null;
          }))this.actions?.markDirtyAndRender();
        };
      });

      // 3. Subject input
      const subjInput = root.querySelector("#make-image-subject");
      const clearSubjBtn = root.querySelector("#make-image-clear-subject");

      const updateClearSubjBtn = () => {
        if (clearSubjBtn) {
          clearSubjBtn.style.display = subjInput && subjInput.value ? "" : "none";
        }
      };

      let debounceTimer = null;
      const flushPersist = () => {
        if (debounceTimer) {
          clearTimeout(debounceTimer);
          debounceTimer = null;
        }
        if (typeof this.actions?.persistDraft === "function") {
          this.actions.persistDraft();
        }
      };

      if (subjInput) {
        activeSubjectFlush = flushPersist;
        ensureBeforeUnloadHandler();
        subjInput.oninput = () => {
          this.patchSpec({subject:subjInput.value},()=>{td.text=subjInput.value});
          this.syncPromptPreview();
          updateClearSubjBtn();
          if (debounceTimer) clearTimeout(debounceTimer);
          debounceTimer = setTimeout(() => {
            debounceTimer = null;
            flushPersist();
          }, 350);
        };
        subjInput.onchange = () => {
          this.patchSpec({subject:subjInput.value},()=>{td.text=subjInput.value});
          this.syncPromptPreview();
          updateClearSubjBtn();
          flushPersist();
        };
        subjInput.onblur = () => {
          flushPersist();
        };
      }

      // Clear subject button
      if (clearSubjBtn) {
        clearSubjBtn.onclick = () => {
          if(!this.patchSpec({subject:""},()=>{td.text=""}))return;
          td.subjectHint = "";
          this.actions?.markDirtyAndRender();
          const input = this.hostElement?.querySelector("#make-image-subject");
          if (input) input.focus();
        };
      }

      // 4. Output Mode buttons (graphic-text, pure, poster)
      root.querySelectorAll("[data-set-mode]").forEach((btn) => {
        btn.onclick = () => {
          const mode = btn.getAttribute("data-set-mode");
          if(this.patchSpec({outputMode:mode},()=>{
            if(global.HandrawStudioCore) global.HandrawStudioCore.setMode(cd,mode);
            else {
              const oldDefault=OUTPUT_MODE_OPTIONS.find(m=>m.id===cd.mode)?.defaultRatio||"3:4";
              const explicit=cd.ratioSource==="user" || (cd.ratio && cd.ratio!==oldDefault);
              cd.mode=mode;
              if(!explicit)cd.ratio=OUTPUT_MODE_OPTIONS.find(m=>m.id===mode)?.defaultRatio||"3:4";
              cd.ratioSource=explicit?"user":"default";
            }
          }))this.actions?.markDirtyAndRender();
        };
      });

      // 5. Ratio buttons
      root.querySelectorAll("[data-set-ratio]").forEach((btn) => {
        btn.onclick = () => {
          const ratio=btn.getAttribute("data-set-ratio");
          if(this.patchSpec({ratio},()=>{cd.ratio=ratio;cd.ratioSource="user"}))
            this.actions?.markDirtyAndRender();
        };
      });

      // Ratio text input (in the same row, live update & validation)
      const ratioInput = root.querySelector("#make-image-ratio-input");
      if (ratioInput) {
        ratioInput.oninput = () => {
          const val = ratioInput.value.trim();
          if (/^\d+(?:\.\d+)?:\d+(?:\.\d+)?$/.test(val)) {
            if(!this.patchSpec({ratio:val},()=>{cd.ratio=val;cd.ratioSource="user"}))return;
            root.querySelectorAll("[data-set-ratio]").forEach((b) => {
              const match = b.getAttribute("data-set-ratio") === val;
              b.classList.toggle("btn-primary", match);
              b.classList.toggle("is-active", match);
              b.setAttribute("aria-pressed", match ? "true" : "false");
            });
            this.syncPromptPreview();
          }
        };
        ratioInput.onchange = () => {
          const val = ratioInput.value.trim();
          if (/^\d+(?:\.\d+)?:\d+(?:\.\d+)?$/.test(val)) {
            if(this.patchSpec({ratio:val},()=>{cd.ratio=val;cd.ratioSource="user"}))
              this.actions?.markDirtyAndRender();
          } else {
            ratioInput.value = cd.ratio || "3:4";
          }
        };
      }

      // 6. More Settings collapsible toggle
      const moreToggle = root.querySelector("#make-image-more-toggle");
      if (moreToggle) {
        moreToggle.onclick = () => {
          this.moreSettingsOpen = !this.moreSettingsOpen;
          this.render();
        };
      }

      // Tones picker
      const pickTonesBtn = root.querySelector("#make-image-pick-tones");
      if (pickTonesBtn) {
        pickTonesBtn.onclick = () => {
          if (this.actions?.openAssetPicker) {
            this.actions.openAssetPicker({ kind: "tone", field: "tones" });
          } else {
            this.openTonePicker();
          }
        };
      }

      // Tone delete button
      root.querySelectorAll("[data-del-tone]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const tid = btn.getAttribute("data-del-tone");
          const tones=(sd.tones||[]).filter(x=>x!==tid);
          if(this.patchSpec({tones},()=>{sd.tones=tones}))this.actions?.markDirtyAndRender();
        };
      });

      // Moods picker modal button
      const pickMoodsBtn = root.querySelector("#make-image-pick-moods");
      if (pickMoodsBtn) {
        pickMoodsBtn.onclick = () => {
          if (this.actions?.openAssetPicker) {
            this.actions.openAssetPicker({ kind: "mood", field: "moods" });
          } else {
            this.openMoodPicker();
          }
        };
      }

      // Moods text input (auto-splits preset into sd.moods and the rest into sd.customMood)
      const moodsInput = root.querySelector("#make-image-moods-input");
      if (moodsInput) {
        const applyMoods = (triggerRender = false) => {
          const presetSet = this.getKnownPresetMoods();
          const parsed = parseMoodsText(moodsInput.value, presetSet);
          if(!this.patchSpec({moods:parsed.moods,customMood:parsed.customMood},()=>{
            sd.moods=parsed.moods;sd.customMood=parsed.customMood;
          }))return;
          if (triggerRender) {
            this.actions?.markDirtyAndRender();
          } else {
            this.syncPromptPreview();
          }
        };

        moodsInput.oninput = () => {
          applyMoods(false);
        };
        moodsInput.onchange = () => {
          applyMoods(true);
        };
      }

      // Whitespace
      root.querySelectorAll("[data-set-ws]").forEach((btn) => {
        btn.onclick = () => {
          const whitespace=btn.getAttribute("data-set-ws")||"";
          if(this.patchSpec({whitespace},()=>{sd.whitespace=whitespace}))
            this.actions?.markDirtyAndRender();
        };
      });

      // Audience
      const audInput = root.querySelector("#make-image-audience");
      if (audInput) {
        audInput.oninput = () => {
          this.patchSpec({audience:audInput.value.trim()},()=>{sd.audience=audInput.value.trim()});
          this.syncPromptPreview();
        };
        audInput.onchange = () => {
          if(this.patchSpec({audience:audInput.value.trim()},()=>{sd.audience=audInput.value.trim()}))
            this.actions?.markDirtyAndRender();
        };
      }

      // Business Scene
      const sceneInput = root.querySelector("#make-image-business-scene");
      if (sceneInput) {
        sceneInput.oninput = () => {
          this.patchSpec({businessScene:sceneInput.value.trim()},()=>{sd.businessScene=sceneInput.value.trim()});
          this.syncPromptPreview();
        };
        sceneInput.onchange = () => {
          if(this.patchSpec({businessScene:sceneInput.value.trim()},()=>{sd.businessScene=sceneInput.value.trim()}))
            this.actions?.markDirtyAndRender();
        };
      }

      // SC-021 select
      const sc021Select = root.querySelector("#make-image-sc021-select");
      if (sc021Select) {
        sc021Select.onchange = () => {
          if(this.patchSpec({layoutParams:{sc021Type:sc021Select.value}},
            ()=>{sd.sc021Type=sc021Select.value}))this.actions?.markDirtyAndRender();
        };
      }

      // SC-022 name & pinyin
      const sc022NameInput = root.querySelector("#make-image-sc022-name");
      if (sc022NameInput) {
        sc022NameInput.oninput = () => {
          this.patchSpec({layoutParams:{sc022Name:sc022NameInput.value.trim()}},()=>{sd.sc022Name=sc022NameInput.value.trim()});
          this.syncPromptPreview();
        };
        sc022NameInput.onchange = () => {
          if(this.patchSpec({layoutParams:{sc022Name:sc022NameInput.value.trim()}},()=>{sd.sc022Name=sc022NameInput.value.trim()}))
            this.actions?.markDirtyAndRender();
        };
      }
      const sc022PinyinInput = root.querySelector("#make-image-sc022-pinyin");
      if (sc022PinyinInput) {
        sc022PinyinInput.oninput = () => {
          this.patchSpec({layoutParams:{sc022Pinyin:sc022PinyinInput.value.trim()}},()=>{sd.sc022Pinyin=sc022PinyinInput.value.trim()});
          this.syncPromptPreview();
        };
        sc022PinyinInput.onchange = () => {
          if(this.patchSpec({layoutParams:{sc022Pinyin:sc022PinyinInput.value.trim()}},()=>{sd.sc022Pinyin=sc022PinyinInput.value.trim()}))
            this.actions?.markDirtyAndRender();
        };
      }

      // Reference picker
      const openRefPicker = root.querySelector("#make-image-open-ref-picker");
      if (openRefPicker) {
        openRefPicker.onclick = () => {
          const curRefs = (ad?.items || []).map((x) => x.image || x.url || x);
          this.actions?.openReferencePicker({
            currentRefs: curRefs,
            onConfirm: (selectedItems) => {
              this.actions?.ensureAssetItems(selectedItems);
            }
          });
        };
      }

      // Delete reference image
      root.querySelectorAll("[data-del-ref]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const idx = Number(btn.getAttribute("data-del-ref"));
          const currentItems = Array.isArray(ad?.items) ? [...ad.items] : [];
          currentItems.splice(idx, 1);
          this.actions?.ensureAssetItems(currentItems);
        };
      });

      // 7. Prompt Preview collapsible toggle & copy
      const promptToggle = root.querySelector("#make-image-prompt-toggle");
      if (promptToggle) {
        promptToggle.onclick = () => {
          this.promptPreviewOpen = !this.promptPreviewOpen;
          this.render();
        };
      }

      const copyPromptBtn = root.querySelector("#make-image-copy-prompt");
      if (copyPromptBtn) {
        copyPromptBtn.onclick = () => {
          const txt = this.getPromptPreview();
          if (navigator?.clipboard?.writeText) {
            navigator.clipboard.writeText(txt).then(() => {
              global.HANDRAW_SHARED?.toast?.("已复制提示词");
            });
          } else {
            global.HANDRAW_SHARED?.toast?.("已复制提示词");
          }
        };
      }

      // 8. Reset form button
      const resetBtn = root.querySelector("#make-image-btn-reset");
      if (resetBtn) {
        resetBtn.onclick = async () => {
          const currentBusy = typeof this.actions?.isBusy === "function" ? this.actions.isBusy() : Boolean(this.context?.busy);
          if (currentBusy || this.context?.pendingCloud ||
              (this.context?.runProjection?.ok && !this.context.runProjection.isTerminal)) {
            global.HANDRAW_SHARED?.toast?.("存在云端未确认任务，请先在生图历史查看结果，避免丢失恢复编号");
            return;
          }
          const ok = await global.HANDRAW_SHARED?.confirmAction?.(
            "清空后，当前表单将恢复默认，并清除本工作区的生成结果；生图历史仍保留。确定清空吗？",
            { title: "清空图片创作设置", danger: true, confirmText: "清空" });
          if (!ok) return;

          if (typeof this.actions?.isBusy === "function" && this.actions.isBusy()) {
            global.HANDRAW_SHARED?.toast?.("任务处理中，暂不能清空或再次生成");
            return;
          }

          cd.mode = "graphic-text";
          cd.ratio = "3:4";
          cd.ratioSource = "default";
          cd.count = 1;
          cd.status = "idle";
          delete cd.error;
          delete cd.activeBatchId;
          cd.elapsedSec = 0;

          sd.fusion = false;
          sd.style1 = "";
          sd.style2 = "";
          sd.layout = "";
          sd.colors = [];
          sd.tones = [];
          sd.moods = [];
          sd.customMood = "";
          sd.whitespace = "balanced";
          sd.audience = "";
          sd.businessScene = "";
          sd.sc021Type = "";
          sd.sc022Name = "";
          sd.sc022Pinyin = "";
          sd.negativePrompt = "";

          td.text = "";
          td.subjectHint = "";

          if (ad) ad.items = [];
          if (p.asset) p.asset.data.items = [];
          if (this.actions?.ensureAssetItems) {
            this.actions.ensureAssetItems([]);
          }

          // Clear downstream display nodes of this control node
          if (typeof this.actions?.clearWorkspaceResults === "function") {
            this.actions.clearWorkspaceResults(p.ctrl.id);
          } else {
            const graph = this.getGraph();
            if (graph && Array.isArray(graph.edges) && Array.isArray(graph.nodes)) {
              const outEdges = graph.edges.filter((e) => e.from === p.ctrl.id);
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

          if (Array.isArray(this.context?.results)) {
            this.context.results = [];
          }
          if (this.context) {
            this.context.statusText = "";
          }

          this.actions?.markDirtyAndRender();
        };
      }

      // Active quick jobs can be stopped locally without claiming that an
      // already-accepted cloud request has been cancelled or refunded.
      const stopBtn = root.querySelector("#make-image-btn-stop");
      if (stopBtn) {
        stopBtn.onclick = () => {
          const cancelled = this.actions?.cancel?.();
          if (cancelled !== false) {
            stopBtn.disabled = true;
            stopBtn.textContent = "正在停止…";
          }
        };
      }

      // A plan is distinct from generation. No duplicate confirmation modal.
      const planBtn = root.querySelector("#make-image-btn-ai-plan");
      if (planBtn) planBtn.onclick = async () => {
        const subject = String(td.text || "").trim();
        if (!subject) {
          global.HANDRAW_SHARED?.toast?.("请先填写创作主题，再使用 AI 辅助设计");
          return;
        }
        if (this.isPlanning) return;
        this.isPlanning = true;
        planBtn.disabled = true;
        planBtn.textContent = "AI 正在规划…";
        try {
          await this.actions?.plan?.();
        } finally {
          this.isPlanning = false;
          if (planBtn.isConnected) {
            planBtn.disabled = false;
            planBtn.textContent = "AI 辅助设计";
          }
        }
      };

      const aiUndo = root.querySelector("#make-image-btn-ai-undo");
      if(aiUndo)aiUndo.onclick=()=>this.actions?.undoPlan?.();
 
      // 9. Run button
      const runBtn = root.querySelector("#make-image-btn-run");
      if (runBtn) {
        runBtn.onclick = () => {
          const currentBusy = typeof this.actions?.isBusy === "function" ?
            this.actions.isBusy():Boolean(this.context?.busy);
          const remote=this.context?.runProjection;
          if (currentBusy || (remote?.ok && !remote.isTerminal)) {
            global.HANDRAW_SHARED?.toast?.("服务器仍在处理上一个任务，请查看当前状态后再生成");
            return;
          }
          this.actions?.run();
        };
      }

      const retryBtn=root.querySelector("#make-image-btn-retry");
      if(retryBtn)retryBtn.onclick=()=>{
        if(this.actions?.isBusy?.())return;
        this.actions?.retry?.();
      };

      // 9. Results Actions
      root.querySelectorAll("[data-action='download']").forEach((btn) => {
        btn.onclick = () => {
          const url = btn.getAttribute("data-url");
          if (!url) return;
          const a = document.createElement("a");
          a.href = url;
          a.download = "handraw-output.webp";
          a.rel = "noopener";
          a.click();
        };
      });

      root.querySelectorAll("[data-action='view']").forEach(btn => {
        btn.onclick = () => {
          const index = Number(btn.getAttribute("data-result-idx"));
          const result = this.context?.results?.[index];
          if (result?.imageUrl && this.actions?.openImageLightbox) {
            this.actions.openImageLightbox(result.imageUrl, result.title || "生成图片");
          }
        };
      });
      root.querySelectorAll("[data-action='reference']").forEach(btn => {
        btn.onclick = () => {
          const index = Number(btn.getAttribute("data-result-idx"));
          const result = this.context?.results?.[index];
          if (result?.imageUrl) this.actions?.addResultAsReference?.(result);
        };
      });
      root.querySelectorAll("[data-action='canvas']").forEach(btn => {
        btn.onclick = () => this.actions?.openCanvas?.();
      });

      const againBtn = root.querySelector("#make-image-btn-again");
      if (againBtn) {
        againBtn.onclick = () => {
          if(this.actions?.isBusy?.() ||
              (this.context?.runProjection?.ok && !this.context.runProjection.isTerminal)){
            global.HANDRAW_SHARED?.toast?.("请先确认当前云端任务已结束");
            return;
          }
          this.actions?.run();
        };
      }

      const newThemeBtn = root.querySelector("#make-image-btn-new-theme");
      if (newThemeBtn) {
        newThemeBtn.onclick = () => {
          if(!this.patchSpec({subject:""},()=>{td.text=""}))return;
          td.subjectHint = "";
          this.actions?.markDirtyAndRender();
          const input = this.hostElement?.querySelector("#make-image-subject");
          if (input) input.focus();
        };
      }
    }

    syncPromptPreview() {
      const ta = this.hostElement?.querySelector("#make-image-prompt");
      if (ta) {
        ta.value = this.getPromptPreview();
      }
    }

    openTonePicker() {
      const catalog = this.context?.catalog;
      const allTones = catalog?.tones || global.HANDRAW_SHARED?.App?.options?.tones || [];
      const p = this.getParts();
      if (!p) return;
      const current = new Set(p.skill.data.tones || []);
      const S = global.HANDRAW_SHARED;
      if (!S || typeof S.openModal !== "function") return;

      S.openModal({
        title: "选择影调（支持多选）",
        sizeClass: "modal-medium",
        html: `
          <div style="display:flex;flex-direction:column;gap:14px;">
            <div style="font-size:12px;color:var(--ink-muted);">可多选多个影调，系统将融合光影氛围（点击卡片勾选/取消）：</div>
            <div id="sp-tone-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;max-height:50vh;overflow-y:auto;padding:2px;"></div>
            <div style="display:flex;justify-content:space-between;align-items:center;padding-top:10px;border-top:1px solid var(--line-soft);">
              <button type="button" class="btn btn-sm" id="sp-tone-clear">清空已选</button>
              <button type="button" class="btn btn-primary" id="sp-tone-confirm">确认选用</button>
            </div>
          </div>
        `,
        onMount: (root) => {
          const grid = root.querySelector("#sp-tone-grid");
          const confirmBtn = root.querySelector("#sp-tone-confirm");
          const renderTones = () => {
            grid.innerHTML = allTones.map((t) => {
              const on = current.has(t.id);
              return `
                <div class="ic-picker-card ${on ? "is-selected" : ""}" data-tone-id="${esc(t.id)}" style="cursor:pointer;border:1.5px solid ${on ? "var(--vermilion)" : "var(--line-soft)"};border-radius:9px;padding:6px;background:${on ? "var(--vermilion-surface)" : "#fff"};display:flex;gap:8px;align-items:center;">
                  <img src="${esc(t.image || `/images/individual/TONES/${t.id}.webp`)}" alt="${esc(t.name_zh || t.name)}" style="width:40px;height:40px;object-fit:cover;border-radius:6px;" />
                  <div style="min-width:0;flex:1;">
                    <div style="font-size:10px;font-family:var(--font-mono);font-weight:700;color:var(--ink-muted);">${esc(t.id)}</div>
                    <div style="font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(t.name_zh || t.name || t.id)}</div>
                  </div>
                  ${on ? '<span style="color:var(--vermilion);font-weight:700;">✓</span>' : ""}
                </div>
              `;
            }).join("");
            grid.querySelectorAll("[data-tone-id]").forEach((card) => {
              card.onclick = () => {
                const tid = card.getAttribute("data-tone-id");
                if (current.has(tid)) current.delete(tid);
                else current.add(tid);
                renderTones();
              };
            });
            confirmBtn.textContent = `确认选用 (${current.size} 项)`;
          };
          renderTones();
          root.querySelector("#sp-tone-clear").onclick = () => {
            current.clear();
            renderTones();
          };
          confirmBtn.onclick = () => {
            p.skill.data.tones = [...current];
            S.closeModal();
            this.actions?.markDirtyAndRender();
          };
        }
      });
    }

    openMoodPicker() {
      const catalog = this.context?.catalog;
      const rawPool = [
        ...(catalog?.moods || []),
        ...(global.HANDRAW_SHARED?.App?.options?.moods || []),
        ...DEFAULT_MOODS
      ];
      const allMoods = [...new Set(rawPool.map(normalizeMoodLabel).filter(Boolean))];
      const p = this.getParts();
      if (!p) return;
      const current = new Set((p.skill.data.moods || []).map(normalizeMoodLabel).filter(Boolean));
      const S = global.HANDRAW_SHARED;
      if (!S || typeof S.openModal !== "function") return;

      S.openModal({
        title: "选择情绪（支持多选）",
        sizeClass: "modal-medium",
        html: `
          <div style="display:flex;flex-direction:column;gap:14px;">
            <div style="font-size:12px;color:var(--ink-muted);">可多选多个情绪词，提升画面氛围传达（点击标签勾选/取消）：</div>
            <div id="sp-mood-grid" style="display:flex;flex-wrap:wrap;gap:8px;max-height:50vh;overflow-y:auto;padding:2px;"></div>
            <div style="display:flex;justify-content:space-between;align-items:center;padding-top:10px;border-top:1px solid var(--line-soft);">
              <button type="button" class="btn btn-sm" id="sp-mood-clear">清空已选</button>
              <button type="button" class="btn btn-primary" id="sp-mood-confirm">确认选用</button>
            </div>
          </div>
        `,
        onMount: (root) => {
          const grid = root.querySelector("#sp-mood-grid");
          const confirmBtn = root.querySelector("#sp-mood-confirm");
          const renderMoods = () => {
            grid.innerHTML = allMoods.map((m) => {
              const on = current.has(m);
              return `<button type="button" class="hw-pill ${on ? "is-active" : ""}" data-mood-val="${esc(m)}">${on ? "✓ " : ""}${esc(m)}</button>`;
            }).join("");
            grid.querySelectorAll("[data-mood-val]").forEach((btn) => {
              btn.onclick = () => {
                const mv = btn.getAttribute("data-mood-val");
                if (current.has(mv)) current.delete(mv);
                else current.add(mv);
                renderMoods();
              };
            });
            confirmBtn.textContent = `确认选用 (${current.size} 项)`;
          };
          renderMoods();
          root.querySelector("#sp-mood-clear").onclick = () => {
            current.clear();
            renderMoods();
          };
          confirmBtn.onclick = () => {
            p.skill.data.moods = [...current];
            S.closeModal();
            this.actions?.markDirtyAndRender();
          };
        }
      });
    }

    setForkSource(source) {
      this.forkSource = source;
      if (this.actions?.markDirtyAndRender) {
        this.actions.markDirtyAndRender();
      } else if (this.hostElement) {
        this.render();
      }
    }

    applyForkDraft(draft) {
      if (!draft) return;
      if (draft.source) {
        this.forkSource = draft.source;
      }
      const p = this.getParts();
      if (!p) return;
      const sd = p.skill.data;
      const td = p.text.data;
      const cd = p.ctrl.data;

      sd.fusion = Array.isArray(draft.styleIds) && draft.styleIds.length > 1;
      sd.style1 = draft.styleIds?.[0] || "";
      sd.style2 = draft.styleIds?.[1] || "";
      sd.layout = draft.layoutId || "";
      sd.colors = Array.isArray(draft.colors) ? [...draft.colors] : [];
      sd.tones = Array.isArray(draft.tones) ? [...draft.tones] : [];
      sd.moods = (Array.isArray(draft.moods) ? draft.moods : []).map(normalizeMoodLabel).filter(Boolean);
      sd.customMood = draft.customMood || "";
      sd.whitespace = draft.whitespace || "";
      sd.audience = draft.audience || "";
      sd.businessScene = draft.businessScene || "";

      let extractedTheme = String(draft.subjectHint || draft.subject || "").trim();
      if (!extractedTheme && draft.prompt) {
        const rawPrompt = String(draft.prompt).trim();
        const sentences = rawPrompt.split(/[。！？\n.!?]/).map((s) => s.trim()).filter(Boolean);
        if (sentences.length > 0) extractedTheme = sentences[0].slice(0, 80);
      }
      td.text = extractedTheme;
      td.subjectHint = draft.subjectHint || extractedTheme || "";

      cd.ratio = draft.ratio || "3:4";
      cd.mode = draft.mode === "pure-image" ? "pure" : (draft.mode || "graphic-text");
      cd.count = 1;

      this.actions?.markDirtyAndRender();
    }
  }

  const defaultInstance = new MakeImageController();

  const publicApi = {
    MakeImageController,
    formatCostText,
    normalizeMoodLabel,
    formatMoodsText,
    parseMoodsText,
    OUTPUT_MODE_OPTIONS,
    RATIO_OPTIONS,
    PRESET_RATIOS,
    WHITESPACE_OPTIONS,
    SC021_PLAYSTYLES,
    DEFAULT_MOODS,
    render(host, context, actions) {
      return defaultInstance.render(host, context, actions);
    },
    setForkSource(source) {
      return defaultInstance.setForkSource(source);
    },
    applyForkDraft(draft) {
      return defaultInstance.applyForkDraft(draft);
    }
  };

  global.HandrawMakeImage = publicApi;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = publicApi;
  }
})(typeof window !== "undefined" ? window : globalThis);
