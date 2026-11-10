/* Studio 2.0 #124: lossless Article/Canvas adapter.
 * This file is a read model. It does not execute a Graph, publish media,
 * mint Run IDs, assemble prompts or create a second ArticleDocument owner.
 */
(function (root, factory) {
  const dep = name => typeof require === "function" ? require(name) : null;
  const api = factory(root.HandrawStudioCore || dep("./studio-core.js"),
    root.HandrawStudioViews || dep("./studio-views.js"));
  if (typeof module === "object" && module.exports) module.exports = api;
  root.HandrawStudioIntegration = api;
})(typeof window !== "undefined" ? window : globalThis, function (Core, Views) {
  "use strict";
  const copy = x => x == null ? x : JSON.parse(JSON.stringify(x));
  const validId = x => typeof x === "string" && x.length > 0;
  function documentToken(draft, anchors = null) {
    // Compare actual content as well as version: old local drafts may lack a
    // monotonic revision. Do not use timestamps or JSON hashing as authority.
    const token = {
      id: String(draft?.id || draft?.documentId || ""),
      documentId: String(draft?.documentId || draft?.id || ""),
      revision: draft?.revision ?? draft?.documentRevision ?? null,
      title: String(draft?.title ?? draft?.articleTitle ?? ""),
      markdown: String(draft?.markdown ?? "")
    };
    if (anchors !== null) token.anchors = copy(anchors);
    return token;
  }
  function sameDocument(token, current, anchors = null) {
    if (!token || !current || !token.id) return false;
    const present = documentToken(current, anchors);
    return Object.keys(token).every(key => JSON.stringify(token[key]) === JSON.stringify(present[key]));
  }
  function assertCurrent(token, current, anchors = null) {
    if (!sameDocument(token, current, anchors)) {
      const error = new Error("article_document_conflict");
      error.code = "article_document_conflict";
      throw error;
    }
  }
  function articleFromDraft(draft, cards = []) {
    if (!validId(draft?.id)) throw new Error("missing_article_id");
    const seen = new Set();
    const anchors = [];
    for (const card of cards) {
      const id = String(card?.id || card?.slotId || "");
      if (!id) throw new Error("missing_article_slot_id");
      const anchorId = String(card.anchorId || "card-anchor-" + id);
      if (seen.has(anchorId)) throw new Error("duplicate_article_anchor");
      seen.add(anchorId);
      anchors.push({anchorId,kind:card.role === "cover" ? "cover" : "illustration",
        afterBlockIdx:Number.isInteger(card.afterBlockIdx) ? card.afterBlockIdx : -1});
    }
    return {documentId:draft.documentId || draft.id,
      revision:Number.isInteger(draft.documentRevision) ? draft.documentRevision :
        Number.isInteger(draft.revision) ? draft.revision : 0,
      markdown:String(draft.markdown || ""),anchors};
  }
  function articlePlan(article, cards, {planId, revision = 0} = {}) {
    if (!validId(article?.documentId) || !Number.isInteger(article.revision) || article.revision < 0)
      throw new Error("invalid_article_document");
    const anchors = new Set((article.anchors || []).map(a => a?.anchorId));
    const ids = new Set();
    const slots = (cards || []).map((card, order) => {
      const slotId = String(card?.slotId || card?.id || "");
      const anchorId = String(card?.anchorId || "card-anchor-" + slotId);
      if (!slotId || ids.has(slotId)) throw new Error("invalid_article_slot_id");
      if (!anchors.has(anchorId)) throw new Error("invalid_article_anchor");
      ids.add(slotId);
      return {slotId,anchorId,order,subject:String(card.subject || card.title || ""),
        lockedFields:copy(card.lockedFields || []),
        overrides:{...(card.ratio ? {ratio:card.ratio} : {}),
          ...(card.layoutRef || card.layoutId ? {layout:copy(card.layoutRef ||
            {id:card.layoutId,type:"layout"})} : {}),
          ...(card.styleRef || card.styleId ? {style:copy(card.styleRef ||
            {id:card.styleId,type:"style"})} : {})},
        referenceMedia:copy(card.referenceMedia || []),
        ...(card.mediaId ? {resultMediaId:card.mediaId} : {})};
    });
    return {planId:planId || "article-plan-" + article.documentId,
      revision,kind:"article",documentId:article.documentId,
      documentRevision:article.revision,slots};
  }
  function linkArticleGraph(graph, article, plan, {nodeId} = {}) {
    if (!Array.isArray(graph?.nodes) || !Array.isArray(graph?.edges))
      throw new Error("invalid_workflow_graph");
    if (article.documentId !== plan.documentId ||
        article.revision !== plan.documentRevision) throw new Error("article_revision_mismatch");
    const anchors = new Set((article.anchors || []).map(x => x.anchorId));
    if ((plan.slots || []).some(s => !anchors.has(s.anchorId)))
      throw new Error("invalid_article_anchor");
    const next = copy(graph);
    const existing = nodeId ? next.nodes.find(x => x.id === nodeId) :
      next.nodes.find(x => x.type === "article_plan" &&
        x.data?.documentId === article.documentId);
    if (!existing) throw new Error("article_plan_node_required");
    if (existing.type !== "article_plan") throw new Error("article_plan_node_type_mismatch");
    // Only linked identity changes here. Existing ports, outputs, groups,
    // fission, loops, bridge nodes, edges and runtime state stay byte-for-byte.
    existing.data = {...(existing.data || {}),
      documentId:article.documentId,documentRevision:article.revision,
      planId:plan.planId,planRevision:plan.revision,
      slotRefs:plan.slots.map(s => ({slotId:s.slotId,anchorId:s.anchorId}))};
    return next;
  }
  function graphRunRefs(graph) {
    const found = [];
    for (const node of graph?.nodes || []) {
      if (node?.type !== "output_control") continue;
      const runId = String(node.data?.runId || node.data?.studio2RunSnapshot?.runId || "");
      if (runId) found.push({nodeId:node.id,runId,
        slots:copy(node.data?.studio2RunSnapshot?.outputs || [])});
    }
    return found;
  }
  async function recoverGraphRuns(graph, fetchRun, {scope = ""} = {}) {
    if (!Core?.selectRunProjection || typeof fetchRun !== "function")
      throw new Error("run_reader_required");
    const refs = graphRunRefs(graph), pending = new Map();
    // All output controls recover concurrently. Multiple controls referring
    // to one Run share the same authorized GET and never start a new task.
    const pairs = await Promise.all(refs.map(async ref => {
      const key = scope + ":" + ref.runId;
      if (!pending.has(key)) pending.set(key, Promise.resolve().then(() => fetchRun(ref.runId)));
      const payload = await pending.get(key);
      if (!payload?.ok || !payload.run || !Array.isArray(payload.items) ||
          String(payload.run.id || payload.run.runId || "") !== ref.runId)
        throw new Error("unverified_run_response");
      const projection = Core.selectRunProjection(payload.run,payload.items,
        {expectedCount:ref.slots.length || undefined});
      return [ref.nodeId,{runId:ref.runId,projection,
        outputs:ref.slots.map((slot,index) => {
          const matched = payload.items.filter(item =>
            Number(item.slotIndex ?? Math.floor(Number(item.position)/1000)) === index);
          return {slotId:slot.slotId || slot.outputId,outputId:slot.outputId,
            items:copy(matched)};
        })}];
    }));
    return Object.fromEntries(pairs);
  }
  function safeGraphView(graph) {
    return Views?.classify(graph) || {mode:"read-only-summary",editableFields:[]};
  }
  return Object.freeze({documentToken,sameDocument,assertCurrent,articleFromDraft,
    articlePlan,linkArticleGraph,graphRunRefs,recoverGraphRuns,safeGraphView});
});
