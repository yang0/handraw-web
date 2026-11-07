/* Studio 2.0 shared pure contracts: adapters & Run read models (#119, #121).
 * Kept framework-agnostic and side-effect free except explicit legacy writes.
 * Production authorization, billing and Run lifecycle remain server-owned.
 */
(function (root) {
  "use strict";
  const VERSION = 1;
  const MODES = new Set(["graphic-text", "pure", "poster", "article-illust", "series"]);
  const MODE_RATIO = Object.freeze({ "graphic-text": "3:4", pure: "3:4", poster: "9:16", "article-illust": "4:3", series: "3:4" });
  const RESOURCE_TYPES = new Set(["style", "layout", "color", "tone"]);
  const PATCH_FIELDS = new Set([
    "subject", "outputMode", "style", "secondaryStyle", "fusionEnabled", "layout",
    "colors", "tones", "moods", "customMood", "whitespace", "ratio", "ratioSource",
    "referenceMedia", "layoutParams", "audience", "businessScene", "userNotes"
  ]);
  const clone = (value) => value == null ? value : JSON.parse(JSON.stringify(value));
  const text = (value) => String(value == null ? "" : value);
  const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj || {}, key);
  const resource = (id, type) => id ? { id: text(id), type } : null;
  const refs = (list, type) => (Array.isArray(list) ? list : []).filter(Boolean).map(id => resource(id, type));
  const modeOf = (mode) => mode === "pure-image" ? "pure" : (MODES.has(mode) ? mode : "graphic-text");

  function normalizeMedia(items) {
    // A local File/dataURL is not a server-owned media ID: preserve legacy
    // asset.items untouched in the graph until upload is confirmed.
    return (Array.isArray(items) ? items : []).flatMap(item => {
      const id = item && (item.mediaId || item.media_id || item.assetId || item.asset_id);
      if (!id) return [];
      const role = ["character", "scene", "object", "composition", "result", "other"].includes(item.role)
        ? item.role : "other";
      return [{ mediaId: text(id), role }];
    });
  }

  function normalizeLegacyParts(parts, options = {}) {
    const sd = parts?.skill?.data || {};
    const td = parts?.text?.data || {};
    const cd = parts?.ctrl?.data || {};
    const ad = parts?.asset?.data || {};
    const outputMode = modeOf(cd.mode);
    const ratio = text(cd.ratio || MODE_RATIO[outputMode]);
    // For pre-v1 drafts only, explicit non-default ratio can be inferred.
    const ratioSource = cd.ratioSource === "user" || cd.ratioExplicit === true
      || (!has(cd, "ratioSource") && Boolean(cd.ratio) && cd.ratio !== MODE_RATIO[outputMode])
      ? "user" : "default";
    const spec = {
      schemaVersion: VERSION,
      revision: Math.max(0, Number(options.revision) || 0),
      subject: text(td.text),
      outputMode,
      style: resource(sd.style1, "style"),
      secondaryStyle: resource(sd.style2, "style"),
      fusionEnabled: Boolean(sd.fusion),
      layout: resource(sd.layout, "layout"),
      colors: refs(sd.colors, "color"),
      tones: refs(sd.tones, "tone"),
      moods: clone(Array.isArray(sd.moods) ? sd.moods : []),
      customMood: text(sd.customMood),
      whitespace: text(sd.whitespace),
      ratio,
      ratioSource,
      referenceMedia: normalizeMedia(ad.items),
      layoutParams: {
        sc021Type: text(sd.sc021Type),
        sc022Name: text(sd.sc022Name),
        sc022Pinyin: text(sd.sc022Pinyin)
      },
      audience: text(sd.audience),
      businessScene: text(sd.businessScene),
      lockedFields: clone(Array.isArray(sd.lockedFields) ? sd.lockedFields : [])
    };
    const localReferences = (Array.isArray(ad.items) ? ad.items : []).length - spec.referenceMedia.length;
    return { spec, warnings: localReferences > 0 ? [{
      code: "unresolved_local_media", count: localReferences,
      message: "本地参考图仍在原工作流，上传成功前不可伪造云端媒体身份"
    }] : [] };
  }

  function applyLegacySpec(parts, spec) {
    if (!parts?.skill?.data || !parts?.text?.data || !parts?.ctrl?.data) throw new Error("missing_legacy_parts");
    const sd = parts.skill.data, td = parts.text.data, cd = parts.ctrl.data;
    td.text = text(spec.subject);
    sd.style1 = spec.style?.id || "";
    sd.style2 = spec.secondaryStyle?.id || "";
    sd.fusion = Boolean(spec.fusionEnabled);
    sd.layout = spec.layout?.id || "";
    sd.colors = (spec.colors || []).map(r => r.id);
    sd.tones = (spec.tones || []).map(r => r.id);
    sd.moods = clone(spec.moods || []);
    sd.customMood = text(spec.customMood);
    sd.whitespace = text(spec.whitespace);
    sd.audience = text(spec.audience);
    sd.businessScene = text(spec.businessScene);
    sd.lockedFields = clone(spec.lockedFields || []);
    if (spec.layoutParams) {
      for (const key of ["sc021Type", "sc022Name", "sc022Pinyin"]) {
        if (has(spec.layoutParams, key)) sd[key] = text(spec.layoutParams[key]);
      }
    }
    cd.mode = modeOf(spec.outputMode);
    cd.ratio = text(spec.ratio || MODE_RATIO[cd.mode]);
    cd.ratioSource = spec.ratioSource === "user" ? "user" : "default";
    // Preserve asset.items as-is: a MediaRef is not a usable legacy image item.
    // The asset service/picker owns the conversion after authorized upload.
    return parts;
  }

  function setMode(control, mode) {
    const next = modeOf(mode);
    const previous = modeOf(control?.mode);
    const oldRatio = text(control?.ratio || MODE_RATIO[previous]);
    const explicit = control?.ratioSource === "user" || control?.ratioExplicit === true
      || (!has(control, "ratioSource") && Boolean(control?.ratio) && oldRatio !== MODE_RATIO[previous]);
    control.mode = next;
    if (!explicit) control.ratio = MODE_RATIO[next];
    control.ratioSource = explicit ? "user" : "default";
    return control;
  }

  function setRatio(control, ratio) {
    const result = validateRatio(ratio);
    if (!result.ok) throw new Error(result.code);
    control.ratio = text(ratio).trim();
    control.ratioSource = "user";
    return control;
  }

  function validateRatio(ratio) {
    const match = /^([0-9]+(?:\.[0-9]+)?):([0-9]+(?:\.[0-9]+)?)$/.exec(text(ratio).trim());
    if (!match) return { ok: false, code: "invalid_ratio" };
    const width = Number(match[1]), height = Number(match[2]);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      return { ok: false, code: "invalid_ratio" };
    }
    return { ok: true, ratio: width / height }; // Server validates model-specific limits.
  }

  function catalogContains(catalog, id, type) {
    if (!catalog) return true; // No catalog means validate syntax only; server rechecks.
    const map = catalog.resourceMap;
    const byId = map && (typeof map.get === "function" ? map.get(id) : map[id]);
    const group = { style: "styles", layout: "layouts", color: "colors", tone: "tones" }[type];
    const value = byId || (Array.isArray(catalog[group]) ? catalog[group].find(v => v.id === id) : null);
    if (!value) return false;
    const foundType = value.kind || value.type;
    return !foundType || foundType === type || (type === "color" && foundType === "palette");
  }

  function validateSpec(spec, options = {}) {
    const errors = [];
    if (!spec || !text(spec.subject).trim()) errors.push({ field: "subject", code: "missing_subject" });
    if (!spec?.style?.id) errors.push({ field: "style", code: "missing_style" });
    if (!MODES.has(spec?.outputMode)) errors.push({ field: "outputMode", code: "invalid_mode" });
    if (!validateRatio(spec?.ratio).ok) errors.push({ field: "ratio", code: "invalid_ratio" });
    for (const [name, type, list] of [
      ["style", "style", spec?.style ? [spec.style] : []],
      ["secondaryStyle", "style", spec?.fusionEnabled && spec?.secondaryStyle ? [spec.secondaryStyle] : []],
      ["layout", "layout", spec?.layout ? [spec.layout] : []],
      ["colors", "color", spec?.colors || []],
      ["tones", "tone", spec?.tones || []]
    ]) {
      for (const item of list) {
        if (!item || !item.id || !RESOURCE_TYPES.has(type) || item.type !== type || !catalogContains(options.catalog, item.id, type)) {
          errors.push({ field: name, code: "invalid_resource", id: item?.id || "" });
        }
      }
    }
    return { ok: errors.length === 0, errors };
  }

  function applySpecPatch(spec, patch, baseRevision) {
    if (!spec || baseRevision !== spec.revision) throw new Error("revision_conflict");
    const next = clone(spec);
    for (const [key, value] of Object.entries(patch || {})) {
      if (!PATCH_FIELDS.has(key)) throw new Error("invalid_patch_field:" + key);
      if ((spec.lockedFields || []).includes(key)) throw new Error("locked_field:" + key);
      next[key] = clone(value);
    }
    next.revision = spec.revision + 1;
    return next;
  }

  function resolveEffectiveSpec(globalSpec, slot) {
    const result = clone(globalSpec);
    for (const [field, value] of Object.entries(slot?.overrides || {})) {
      if (!PATCH_FIELDS.has(field)) throw new Error("invalid_override_field:" + field);
      result[field] = clone(value);
    }
    return result;
  }

  function stableHash(value) {
    let h = 2166136261;
    for (let i = 0; i < value.length; i++) {
      h ^= value.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(36);
  }

  function normalizeLegacyBatch(loop, options = {}) {
    const ld = loop?.data || {};
    const rows = Array.isArray(ld.batchRows) ? ld.batchRows : [];
    const mode = ld.batchLayoutMode || (rows.length ? "ai" : "fixed");
    const titles = text(ld.promptListText).split(/\r?\n/).map(t => t.trim()).filter(Boolean);
    const active = mode === "ai" && rows.length ? rows : titles.map(theme => ({ theme }));
    const ids = Array.isArray(ld.studio2SlotIds) ? ld.studio2SlotIds : [];
    const slots = active.map((row, index) => {
      const subject = text(row.theme || row.subject).trim();
      const slotId = row.slotId || ids[index] || ("legacy-" + stableHash([text(ld.id || options.key || "batch"), index, subject].join("|")));
      const overrides = row.layout ? { layout: resource(row.layout, "layout") } : {};
      if (row.ratio) overrides.ratio = row.ratio;
      if (row.style1) overrides.style = resource(row.style1, "style");
      return {
        slotId: text(slotId), order: index, subject,
        overrides,
        referenceMedia: normalizeMedia(row.assetItems),
        skipGlobalRefs: Boolean(row.skipGlobalRefs),
        lockedFields: clone(Array.isArray(row.lockedFields) ? row.lockedFields : [])
      };
    });
    return { planId: text(options.planId || ld.planId || "legacy-batch"),
      revision: Math.max(0, Number(ld.planRevision) || 0),
      kind: text(ld.planKind || "story-series"), slots };
  }

  function pinLegacySlotIds(loop, plan) {
    if (!loop?.data || !plan?.slots) return;
    loop.data.studio2SlotIds = plan.slots.map(slot => slot.slotId);
    if (loop.data.batchLayoutMode === "ai" && Array.isArray(loop.data.batchRows)) {
      loop.data.batchRows.forEach((row, i) => {
        if (row && plan.slots[i] && !row.slotId) row.slotId = plan.slots[i].slotId;
      });
    }
  }

  // Replanning never destroys per-slot image references, manual locks or
  // stable identity. AI may revise unlocked subject/layout only.
  function mergeLegacyPlanRows(loop, items, mode) {
    const ld = loop?.data || {};
    const rows = Array.isArray(ld.batchRows) ? ld.batchRows : [];
    const ids = Array.isArray(ld.studio2SlotIds) ? ld.studio2SlotIds : [];
    const next = (Array.isArray(items) ? items : []).map((item, index) => {
      const prior = rows[index] || {};
      const lockedFields = Array.isArray(prior.lockedFields) ? prior.lockedFields : [];
      const proposedTheme = text(item?.subject || item?.theme);
      const slotId = prior.slotId || ids[index]
        || ("slot-" + stableHash([text(ld.id || "batch"), index, proposedTheme].join("|")));
      return {
        ...clone(prior), slotId,
        theme: lockedFields.includes("subject") && prior.theme ? prior.theme : proposedTheme,
        layout: lockedFields.includes("layout") ? text(prior.layout)
          : mode === "ai" ? text(item?.layout) : text(prior.layout)
      };
    });
    return {
      batchRows: next,
      promptListText: next.map(row => row.theme).join("\n"),
      studio2SlotIds: next.map(row => row.slotId),
      planRevision: Math.max(0, Number(ld.planRevision) || 0) + 1
    };
  }

  const RUN_PERSISTED = new Set(["pending", "uploading", "running", "partial", "success", "failed", "cancelled"]);
  const ITEM_PERSISTED = new Set(["pending", "generating", "success", "failed", "cancelled"]);
  function selectRunProjection(run, items = [], options = {}) {
    const expected = Math.max(0, Number(options.expectedCount ?? run?.expected_count ?? run?.expectedCount ?? 0) || 0);
    const bySlot = new Map();
    for (const item of Array.isArray(items) ? items : []) {
      const position = Number(item.position);
      if (!Number.isInteger(position) || position < 0) continue;
      const slot = Number(item.slotIndex ?? item.batchIndex ??
        (run?.source === "web" && position >= 1000 ? Math.floor(position / 1000) : position));
      if (!Number.isInteger(slot) || slot < 0 || (expected && slot >= expected)) continue;
      if (!bySlot.has(slot)) bySlot.set(slot, []);
      bySlot.get(slot).push(item);
    }
    const totals = { succeeded: 0, failed: 0, cancelled: 0, generating: 0, queued: 0, unknown: 0 };
    const width = Math.max(expected, ...[...bySlot.keys()].map(n => n + 1), 0);
    let partialOutputs = 0;
    for (let slot = 0; slot < width; slot++) {
      const candidates = bySlot.get(slot) || [];
      if (!candidates.length) { totals.queued++; continue; }
      const hasSuccess = candidates.some(item => item.status === "success" && (item.media_id || item.mediaId));
      const hasFailed = candidates.some(item => item.status === "failed");
      if (candidates.some(item => item.status === "generating")) totals.generating++;
      else if (candidates.some(item => item.status === "pending")) totals.queued++;
      else if (hasSuccess) totals.succeeded++;
      else if (hasFailed) totals.failed++;
      else if (candidates.every(item => item.status === "cancelled")) totals.cancelled++;
      else totals.unknown++;
      if (hasSuccess && hasFailed) partialOutputs++;
    }
    const total = Object.values(totals).reduce((a, b) => a + b, 0);
    const isTerminal = total > 0 && totals.succeeded + totals.failed + totals.cancelled === total;
    const isStopping = options.cancelRequested === true;
    return {
      runId: run?.id || run?.runId || "", persistedStatus: RUN_PERSISTED.has(run?.status) ? run.status : "unknown",
      total, ...totals, partialOutputs,
      processed: totals.succeeded + totals.failed + totals.cancelled,
      isTerminal, isStopping, canRetry: totals.failed + totals.cancelled > 0,
      viewStatus: isStopping && !isTerminal ? "cancel_requested"
        : totals.unknown ? "unknown" : isTerminal
        ? totals.succeeded === total && !partialOutputs ? "success"
          : totals.succeeded ? "partial" : totals.failed ? "failed" : "cancelled"
        : totals.generating ? "running" : "pending"
    };
  }

  const api = Object.freeze({
    VERSION, MODE_RATIO, normalizeLegacyParts, applyLegacySpec, setMode, setRatio,
    validateRatio, validateSpec, applySpecPatch, resolveEffectiveSpec,
    normalizeLegacyBatch, pinLegacySlotIds, mergeLegacyPlanRows, selectRunProjection,
    RUN_PERSISTED, ITEM_PERSISTED
  });
  root.HandrawStudioCore = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
