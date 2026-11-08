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
  const typedRef = (id, type, stored) => {
    // A ResourceRef is a verified catalog identity with source+version. Legacy
    // node strings remain readable until the user reselects a definition.
    if (!id) return null;
    if (stored && !Array.isArray(stored) && stored.id === id && stored.type === type) return clone(stored);
    return resource(id, type);
  };
  const refs = (list, type, stored) => (Array.isArray(list) ? list : []).filter(Boolean)
    .map(id => typedRef(id, type, (Array.isArray(stored) ? stored : []).find(x => x?.id === id)));
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
    const rr = sd.resourceRefs || {};
    const spec = {
      schemaVersion: VERSION,
      revision: Math.max(0, Number(options.revision) || 0),
      subject: text(td.text),
      outputMode,
      style: typedRef(sd.style1, "style", rr.style),
      secondaryStyle: typedRef(sd.style2, "style", rr.secondaryStyle),
      fusionEnabled: Boolean(sd.fusion),
      layout: typedRef(sd.layout, "layout", rr.layout),
      colors: refs(sd.colors, "color", rr.colors),
      tones: refs(sd.tones, "tone", rr.tones),
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
    // Keep the original Graph as the only mutable execution definition, with
    // normalized catalog identity metadata embedded in the SAME node.
    sd.resourceRefs = {
      style: spec.style ? clone(spec.style) : null,
      secondaryStyle: spec.secondaryStyle ? clone(spec.secondaryStyle) : null,
      layout: spec.layout ? clone(spec.layout) : null,
      colors: clone(spec.colors || []),
      tones: clone(spec.tones || [])
    };
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

  function catalogResolve(catalog, id, type) {
    if (!catalog) return null;
    const map = catalog.resourceMap;
    const byId = map && (typeof map.get === "function" ? map.get(id) : map[id]);
    const group = { style: "styles", layout: "layouts", color: "colors", tone: "tones" }[type];
    return byId || (Array.isArray(catalog[group]) ? catalog[group].find(v => v.id === id) : null);
  }

  function catalogContains(catalog, id, type) {
    if (!catalog) return true; // Offline drafts may load; server rechecks all.
    const value = catalogResolve(catalog, id, type);
    if (!value) return false;
    const foundType = value.kind || value.type;
    return !foundType || foundType === type || (type === "color" && foundType === "palette");
  }

  function validateSpec(spec, options = {}) {
    const errors = [];
    if (!spec || !text(spec.subject).trim()) errors.push({ field: "subject", code: "missing_subject" });
    if (!spec?.style?.id) errors.push({ field: "style", code: "missing_style" });
    if (spec?.fusionEnabled && !spec?.secondaryStyle?.id) {
      errors.push({ field: "secondaryStyle", code: "missing_secondary_style" });
    }
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
        if (!item || !item.id || !RESOURCE_TYPES.has(type) || item.type !== type ||
            !catalogContains(options.catalog, item.id, type)) {
          errors.push({ field: name, code: "invalid_resource", id: item?.id || "" });
          continue;
        }
        if (item.source != null && !["official","community","override","private",
          "pending","exclusive"].includes(item.source)) {
          errors.push({ field: name, code: "invalid_resource_source", id: item.id });
        }
        if (item.version != null && !(typeof item.version === "string" && item.version.length <= 64 &&
            item.version.length > 0) && !(Number.isInteger(item.version) && item.version > 0)) {
          errors.push({ field: name, code: "invalid_resource_version", id: item.id });
        }
        const entry = catalogResolve(options.catalog, item.id, type);
        if (entry) {
          if (entry.canUse === false || entry.access?.canUse === false) {
            errors.push({ field: name, code: "resource_forbidden", id: item.id });
          }
          const source = entry.source || entry.sourceType || entry.source_type;
          if (source && item.source && source !== item.source &&
              !(source === "official_override" && item.source === "override")) {
            errors.push({ field: name, code: "resource_source_mismatch", id: item.id });
          }
          const version = entry.version ?? entry.definitionVersion ?? entry.revision;
          if (version != null && item.version != null && item.version !== "current" &&
              String(version) !== String(item.version)) {
            errors.push({ field: name, code: "resource_version_conflict", id: item.id });
          }
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
    // A field-level user ratio edit is explicit unless the caller sends a
    // deliberate ratioSource override. Mode-default changes are not edits.
    if (has(patch,"ratio") && !has(patch,"ratioSource")) next.ratioSource = "user";
    if (has(patch,"outputMode") && !has(patch,"ratio") &&
        next.ratioSource !== "user") {
      next.ratio = MODE_RATIO[modeOf(next.outputMode)];
      next.ratioSource = "default";
    }
    next.revision = spec.revision + 1;
    return next;
  }

  function resolveEffectiveSpec(globalSpec, slot) {
    const result = clone(globalSpec);
    for (const [field, value] of Object.entries(slot?.overrides || {})) {
      if (!PATCH_FIELDS.has(field)) throw new Error("invalid_override_field:" + field);
      // Locked user choices are not subject to AI or slot-plan overrides.
      if ((globalSpec?.lockedFields || []).includes(field)) {
        if (JSON.stringify(result[field]) !== JSON.stringify(value))
          throw new Error("locked_field:" + field);
        continue;
      }
      // A slot lock protects its OWN explicitly saved override from subsequent
      // patches/replans; it must not suppress that value at execution time.
      result[field] = clone(value);
    }
    // A disabled secondary style is a draft-only preference. Never put it
    // into a RunSnapshot or a prompt request.
    if (!result.fusionEnabled) result.secondaryStyle = null;
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
    // After #123 the existing Loop's PlanSlot is the ONLY writable plan.
    // promptListText and batchRows are compatibility projections, not rival
    // sources. Older tabs without this field still import through the legacy
    // normalization below and pin their identities once.
    if (ld.studio2Plan?.slots) {
      const p=clone(ld.studio2Plan);
      if (!Array.isArray(p.slots) || new Set(p.slots.map(s=>s.slotId)).size!==p.slots.length)
        throw new Error("duplicate_slot_id");
      return p;
    }
    const rows = Array.isArray(ld.batchRows) ? ld.batchRows : [];
    const mode = ld.batchLayoutMode || (rows.length ? "ai" : "fixed");
    const titles = text(ld.promptListText).split(/\r?\n/).map(t => t.trim()).filter(Boolean);
    const active = mode === "ai" && rows.length ? rows : titles.map(theme => ({ theme }));
    const ids = Array.isArray(ld.studio2SlotIds) ? ld.studio2SlotIds : [];
    const identity = text(options.planId || ld.planId || loop?.id || ld.id || options.key || options.projectId);
    if (!identity) throw new Error("missing_plan_identity");
    const slots = active.map((row, index) => {
      const subject = text(row.subject ?? row.theme).trim();
      // Index is an initial import disambiguator, not the public logical ID.
      // Pin the resulting IDs on the source loop immediately after import.
      const slotId = row.slotId || ids[index] || ("legacy-" + stableHash([identity, index, subject].join("|")));
      const overrides = clone(row.overrides || {});
      if (row.layout && !has(overrides,"layout")) overrides.layout = clone(row.layoutRef && row.layoutRef.id === row.layout
        ? row.layoutRef : resource(row.layout, "layout"));
      if (row.ratio && !has(overrides,"ratio")) overrides.ratio = row.ratio;
      if (row.style1 && !has(overrides,"style")) overrides.style = clone(row.styleRef && row.styleRef.id === row.style1
        ? row.styleRef : resource(row.style1, "style"));
      if (row.style2 && !has(overrides,"secondaryStyle")) overrides.secondaryStyle = resource(row.style2, "style");
      const mapped = {
        slotId: text(slotId), order: Number.isInteger(row.order) && row.order >= 0 ? row.order : index, subject,
        overrides,
        referenceMedia: normalizeMedia(row.referenceMedia || row.assetItems),
        skipGlobalRefs: Boolean(row.skipGlobalRefs),
        lockedFields: clone(Array.isArray(row.lockedFields) ? row.lockedFields : [])
      };
      if (row.anchorId) mapped.anchorId = text(row.anchorId);
      return mapped;
    });
    if (new Set(slots.map(s => s.slotId)).size !== slots.length) throw new Error("duplicate_slot_id");
    const plan = { planId: identity,
      revision: Math.max(0, Number(ld.planRevision) || 0),
      kind: text(ld.planKind || "story-series"), slots };
    if (ld.documentId) plan.documentId = text(ld.documentId);
    if (Number.isInteger(ld.documentRevision)) plan.documentRevision = ld.documentRevision;
    return plan;
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
      const suggestedId = item?.slotId;
      const prior = suggestedId
        ? (rows.find(row => row?.slotId === suggestedId) || {})
        : (rows[index] || {});
      const lockedFields = Array.isArray(prior.lockedFields) ? prior.lockedFields : [];
      const proposedTheme = text(item?.subject || item?.theme);
      const stableParentId = text(ld.planId || ld.id || loop?.id);
      if (!stableParentId && !prior.slotId && !suggestedId && !ids[index]) {
        throw new Error("missing_plan_identity");
      }
      const slotId = prior.slotId || suggestedId || ids[index]
        || ("slot-" + stableHash([stableParentId, index, proposedTheme].join("|")));
      return {
        ...clone(prior), slotId,
        theme: lockedFields.includes("subject") && prior.theme ? prior.theme : proposedTheme,
        layout: lockedFields.includes("layout") ? text(prior.layout)
          : mode === "ai" ? text(item?.layout) : text(prior.layout)
      };
    });
    if (new Set(next.map(row => row.slotId)).size !== next.length) {
      throw new Error("duplicate_slot_id");
    }
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
        (run?.source === "web" ? Math.floor(position / 1000) : position));
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
      // A confirmed successful media item is immutable. Later retry/unknown
      // attempts must not demote the same logical slot to "generating".
      if (hasSuccess) totals.succeeded++;
      else if (candidates.some(item => item.status === "generating")) totals.generating++;
      else if (candidates.some(item => item.status === "pending")) totals.queued++;
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
        ? totals.succeeded === total ? "success"
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
