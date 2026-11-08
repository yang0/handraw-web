/* Studio 2.0 #107: authority-safe graph compiler, expressibility and node-scoped patches.
 * Graph is the sole execution definition after entering Canvas. This module
 * never starts a Run, creates a Project or mutates its input arguments.
 */
(function (root, factory) {
  const api = factory(root.HandrawStudioCore ||
    (typeof require === "function" ? require("./studio-core.js") : null));
  if (typeof module === "object" && module.exports) module.exports = api;
  root.HandrawStudioViews = api;
})(typeof window !== "undefined" ? window : globalThis, function (Core) {
  "use strict";
  const copy = value => value == null ? value : JSON.parse(JSON.stringify(value));
  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj || {}, key);
  const EDITABLE = Object.freeze({
    text_input: ["text"],
    skill_params: ["style1", "style2", "fusion", "layout", "colors", "tones",
      "moods", "customMood", "whitespace", "audience", "businessScene",
      "sc021Type", "sc022Name", "sc022Pinyin", "resourceRefs"],
    output_control: ["ratio", "ratioSource", "mode", "count"]
  });
  const SIMPLE_TYPES = new Set(["skill_params", "text_input", "asset",
    "output_control", "output_display", "loop", "article_plan"]);
  const pointer = part => String(part).replace(/~/g, "~0").replace(/\//g, "~1");
  const json = value => JSON.stringify(value);

  function classify(graph) {
    const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
    const edges = Array.isArray(graph?.edges) ? graph.edges : [];
    const groups = type => nodes.filter(node => node?.type === type);
    const controls = groups("output_control"), skills = groups("skill_params"),
      texts = groups("text_input"), loops = groups("loop"), assets = groups("asset");
    const ids = nodes.map(n => n?.id);
    if (!nodes.length || ids.some(x => typeof x !== "string" || !x) ||
        new Set(ids).size !== ids.length || edges.some(e => !ids.includes(e.from) || !ids.includes(e.to)) ||
        controls.length < 1 || skills.length !== 1 || texts.length !== 1 ||
        assets.length > 1 || loops.length > 1 ||
        nodes.some(n => !SIMPLE_TYPES.has(n.type))) {
      return { mode: "read-only-summary", reason: "unknown_or_ambiguous_graph",
        editableFields: [], nodeIds: {}, graphRevision: Number(graph?.revision || 0) };
    }
    const inbound = id => new Set(edges.filter(e => e.to === id).map(e => e.from));
    const allInputs = controls.every(c => inbound(c.id).has(skills[0].id) &&
      inbound(c.id).has(texts[0].id));
    const shared = controls.length > 1 && allInputs && loops.length === 0;
    const one = controls.length === 1 && allInputs;
    const allCtrlEdgesKnown = controls.every(c => {
      const incoming = inbound(c.id);
      return [...incoming].every(id => {
        const t = nodes.find(n => n.id === id)?.type;
        return ["skill_params", "text_input", "asset", "loop"].includes(t);
      });
    });
    if ((!one && !shared) || !allCtrlEdgesKnown) {
      return { mode: "read-only-summary", reason: "graph_not_reversible",
        editableFields: [], nodeIds: {}, graphRevision: Number(graph?.revision || 0) };
    }
    const hasLoop = loops.length === 1;
    if (hasLoop && !edges.some(e => e.from === loops[0].id && e.to === controls[0].id)) {
      return { mode: "read-only-summary", reason: "unmapped_loop",
        editableFields: [], nodeIds: {}, graphRevision: Number(graph?.revision || 0) };
    }
    const isArticle = nodes.some(n => n.type === "article_plan") || graph.blueprint === "article";
    const mode = shared || isArticle ? "partial-editable" : "simple-editable";
    return {
      mode, reason: shared ? "multiple_output_branches" : isArticle ? "article_anchors_authoritative" : "",
      graphRevision: Number(graph?.revision || 0),
      editableFields: shared || isArticle ? ["subject", "style"] :
        ["subject", "style", "secondaryStyle", "fusionEnabled", "layout",
          "colors", "tones", "moods", "customMood", "whitespace", "ratio",
          "ratioSource", "outputMode", "audience", "businessScene", "layoutParams"],
      nodeIds: {
        text: texts[0].id, skill: skills[0].id,
        output: controls.length === 1 ? controls[0].id : null,
        outputs: controls.map(c => c.id), loop: loops[0]?.id || null,
        asset: assets[0]?.id || null
      }
    };
  }

  function specFromGraph(graph) {
    const state = classify(graph);
    if (state.mode === "read-only-summary" || !Core) {
      return { ...state, spec: null };
    }
    const find = id => graph.nodes.find(n => n.id === id);
    const parts = {
      text: find(state.nodeIds.text), skill: find(state.nodeIds.skill),
      ctrl: find(state.nodeIds.output || state.nodeIds.outputs[0]),
      asset: state.nodeIds.asset ? find(state.nodeIds.asset) : { data: { items: [] } }
    };
    const model = Core.normalizeLegacyParts(parts);
    return { ...state, spec: model.spec, warnings: model.warnings };
  }

  function makeId(prefix, role) {
    return "studio2-" + String(prefix || "project").replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 65) + "-" + role;
  }

  function compile(spec, plan = null, { projectId = "project", existingGraph = null,
    article = null } = {}) {
    if (!Core || !spec || !spec.subject && !plan) throw new Error("invalid_creation_spec");
    if (existingGraph) {
      const state = classify(existingGraph);
      if (state.mode !== "simple-editable") throw new Error("graph_authority_required");
      // A compiled graph must never overwrite any existing user-created nodes
      // even when it is still simple. Use the explicit node patch API instead.
      throw new Error("existing_graph_requires_patch");
    }
    const id = role => makeId(projectId, role);
    const skill = { id: id("skill"), type: "skill_params", x: 64, y: 56, data: {} };
    const text = { id: id("text"), type: "text_input", x: 64, y: 480,
      data: { text: String(spec.subject || "") } };
    const asset = { id: id("asset"), type: "asset", x: 64, y: 760,
      data: { items: copy(spec.referenceMedia || []) } };
    const ctrl = { id: id("output"), type: "output_control", x: 820, y: 200,
      data: { mode: spec.outputMode || "graphic-text", count: 1,
        ratio: spec.ratio || "3:4", ratioSource: spec.ratioSource || "default" } };
    Core.applyLegacySpec({skill, text, ctrl, asset}, spec);
    const nodes = [skill, text, asset], edges = [];
    const edge = (a,b) => edges.push({id:id("edge-"+a+"-"+b),from:id(a),to:id(b)});
    let blueprint = "single";
    const slots = Array.isArray(plan?.slots) ? plan.slots : [];
    if (slots.length > 0) {
      blueprint = "loop_100";
      const loop = { id:id("loop"), type:"loop", x:460,y:200, data: {
        loopMode: "prompts", batchLayoutMode:"ai",
        batchRows: slots.map((slot,i) => ({
          slotId: slot.slotId || id("slot-"+i),
          theme: String(slot.subject || ""), layout: slot.overrides?.layout?.id || "",
          anchorId: slot.anchorId || null,
          lockedFields: copy(slot.lockedFields || []),
          assetItems: copy(slot.referenceMedia || []),
          ratio: slot.overrides?.ratio || ""
        })),
        studio2SlotIds: slots.map((slot,i) => slot.slotId || id("slot-"+i)),
        promptListText: slots.map(slot => String(slot.subject || "")).join("\n"),
        planId: plan.planId || id("plan"), planRevision: Number(plan.revision || 0),
        planKind: plan.kind || "story-series", maxIterations: 200
      }};
      nodes.push(loop);
      edge("skill","loop"); edge("text","loop"); edge("asset","loop"); edge("loop","output");
    }
    nodes.push(ctrl);
    edge("skill","output");edge("text","output");edge("asset","output");
    // The article text/anchors are owned exclusively by ArticleDocument.
    // The Graph carries only reference IDs, never a second writable markdown.
    if (article || plan?.kind === "article") {
      blueprint = "article";
      nodes.push({id:id("article-plan"),type:"article_plan",x:460,y:560,
        data:{documentId:article?.documentId || "",documentRevision:article?.revision || 0,
          anchors:(article?.anchors || []).map(a => ({anchorId:a.anchorId,kind:a.kind || ""}))}});
    }
    return {blueprint, revision: 1, nodes, edges, selectedIds: []};
  }

  // Only permitted node.data fields may be changed via simple editor; this
  // keeps custom node internals, media, edges, branch outputs and Run untouched.
  function patchNode(graph, {nodeId, field, value, baseRevision}) {
    if (!graph || Number(graph.revision || 0) !== Number(baseRevision)) {
      throw new Error("graph_revision_conflict");
    }
    const state = classify(graph);
    const node = graph.nodes?.find(n => n.id === nodeId);
    if (!node || !EDITABLE[node.type]?.includes(field)) throw new Error("unsafe_graph_patch");
    const target = node.type === "text_input" ? "subject" :
      node.type === "skill_params" ? "style" : "ratio";
    if (state.mode === "read-only-summary" ||
        (state.mode === "partial-editable" && (target === "ratio" || (
          node.type === "skill_params" && !["style1","style2","fusion","resourceRefs"].includes(field))))) {
      throw new Error("graph_field_read_only");
    }
    if (node.type === "text_input" && state.nodeIds.text !== nodeId ||
        node.type === "skill_params" && state.nodeIds.skill !== nodeId ||
        node.type === "output_control" && state.nodeIds.output !== nodeId) {
      throw new Error("unsafe_graph_patch");
    }
    const next = copy(graph);
    const targetNode = next.nodes.find(n => n.id === nodeId);
    targetNode.data = targetNode.data || {};
    targetNode.data[field] = copy(value);
    next.revision = Number(graph.revision || 0) + 1;
    return next;
  }

  function graphFieldPatches(before, after) {
    if (!before || !after) return null;
    const b = before.nodes, a = after.nodes;
    if (!Array.isArray(b) || !Array.isArray(a) || b.length !== a.length ||
        json(before.edges || []) !== json(after.edges || []) ||
        before.blueprint !== after.blueprint) return null;
    const oldById = new Map(b.map(n => [n.id,n]));
    if (oldById.size !== b.length || a.some(n => !oldById.has(n.id))) return null;
    const changes = [];
    for (const node of a) {
      const prior = oldById.get(node.id);
      if (node.type !== prior.type) return null;
      const rest = value => {
        const {data, ...other} = value;
        return other;
      };
      if (json(rest(node)) !== json(rest(prior))) return null;
      const oldData = prior.data || {}, newData = node.data || {};
      for (const field of new Set([...Object.keys(oldData),...Object.keys(newData)])) {
        if (json(oldData[field]) === json(newData[field])) continue;
        if (!EDITABLE[node.type]?.includes(field) || !own(newData,field)) return null;
        // Do not send a stale patch when current Graph is ambiguous.
        const state = classify(after);
        if (state.mode === "read-only-summary" || state.mode === "partial-editable" &&
            (node.type === "output_control" || node.type === "skill_params" &&
             !["style1","style2","fusion","resourceRefs"].includes(field))) return null;
        changes.push({op:"set",
          path:"/graph/nodesById/"+pointer(node.id)+"/data/"+pointer(field),
          value:copy(newData[field])});
      }
    }
    // A view-only change must not touch /graph.
    return changes;
  }

  function switchView(state, nextView, layout = {}) {
    if (!["simple","canvas"].includes(nextView)) throw new Error("invalid_editor_view");
    const current = copy(state || {});
    const graph = current.graph;
    if (!graph) throw new Error("missing_graph");
    const projection = classify(graph);
    current.activeView = nextView;
    current.editorLayout = {
      ...(current.editorLayout || {}), ...copy(layout),
      selectedIds: copy(layout.selectedIds || current.editorLayout?.selectedIds || []),
      camera: copy(layout.camera || current.editorLayout?.camera || {vx:290,vy:48,vk:0.85})
    };
    // Neither runId nor server Run status may be synthesized here.
    return {state:current, projection};
  }

  return Object.freeze({classify,specFromGraph,compile,patchNode,
    graphFieldPatches,switchView});
});
