/* Studio 2.0 #109: ArticleDocument/PlanSlot private Project read/write adapter.
 * This is NOT a second article generation engine. It uses the same #103 CAS
 * client, #124 identity adapter and existing Run/RunItem execution path.
 * Never write the full article text into a Graph projection or public Work.
 */
(function (root, factory) {
  const api = factory(root.HandrawStudioIntegration ||
    (typeof require === "function" ? require("./studio-article-integration.js") : null));
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.HandrawStudioArticle109 = api;
})(typeof window !== "undefined" ? window : globalThis, function (Integration) {
  "use strict";
  const clone = x => x == null ? x : JSON.parse(JSON.stringify(x));
  const str = x => String(x == null ? "" : x);
  const int = x => Number.isInteger(Number(x)) && Number(x) >= 0 ? Number(x) : 0;
  function cardsOf(art) {
    const seen = new Set();
    return (Array.isArray(art?.cards) ? art.cards : []).map((source,index) => {
      const card = clone(source);
      card.id = str(card.slotId || card.id || "article-slot-" + index);
      card.slotId = card.id;
      card.anchorId = str(card.anchorId || "card-anchor-" + card.id);
      if (seen.has(card.id)) throw new Error("article_slot_id_duplicate");
      seen.add(card.id);
      return card;
    });
  }
  function snapshot(art) {
    if (!Integration || !art?.id) throw new Error("article_document_required");
    const cards = cardsOf(art);
    const article = Integration.articleFromDraft({
      id:art.id,documentId:art.id,markdown:art.markdown || "",
      documentRevision:int(art.documentRevision)
    },cards);
    const plan = Integration.articlePlan(article,cards,{
      planId:str(art.planId || "article-plan-" + art.id),
      revision:int(art.planRevision)
    });
    // Public Work identity is private Article Project metadata; it must
    // survive refresh and cross-device restoration, never be regenerated for
    // another single-card retry.
    if (art.generationId) plan.generationId = str(art.generationId);
    // PlanSlot is canonical; retain card-specific delivery fields so another
    // device can restore completed images without requiring an old Graph.
    plan.slots = plan.slots.map((slot,i) => {
      const c = cards[i];
      return {...slot,
        role:c.role === "cover" ? "cover" : "inline",
        afterBlockIdx:Number.isInteger(c.afterBlockIdx) ? c.afterBlockIdx : -1,
        anchorText:str(c.anchorText), title:str(c.title),
        purpose:str(c.purpose), prompt:str(c.prompt),
        promptCustomized:c.promptCustomized === true,
        imageUrl:str(c.imageUrl), status:str(c.status || "idle"),
        runId:str(c.runId),requestId:str(c.requestId),taskId:str(c.taskId),
        genId:str(c.genId),mediaId:str(c.mediaId),
        sampleImg:str(c.sampleImg),
        ratio:str(c.ratio || (c.role === "cover" ? art.coverRatio || "2.35:1" : art.inlineRatio || "4:3")),
        ...(c.variants ? {variants:clone(c.variants)} : {})
      };
    });
    const styleId=str(art.style1 || art.styleId || "");
    const layoutId=str(art.layout || art.layoutId || "");
    // Article owns the same typed ResourceRefs; old Project drafts may only
    // contain the IDs, which the server re-resolves on the next CAS write.
    const typed=(id,ref,type)=>id?(ref?clone(ref):{id,type}):null;
    const creationSpec = {
      schemaVersion:1,revision:int(art.specRevision),
      subject:str(art.articleTitle || art.title),
      outputMode:"article-illust",
      style:typed(styleId,art.styleRef,"style"),
      layout:typed(layoutId,art.layoutRef,"layout"),
      ratio:art.inlineRatio || "4:3",
      ratioSource:"user",
      fusionEnabled:false,
      colors:[],tones:[],moods:[],
      referenceMedia:clone(art.referenceMedia || []),
      lockedFields:clone(art.lockedFields || [])
    };
    return {kind:"article",authority:"article",
      title:str(art.articleTitle || art.title || "未命名文章"),
      draft:{article,plan,creationSpec,activeView:"simple",
        editorLayout:{runRefs:cards.filter(c=>c.runId).map(c=>({
          runId:c.runId,slotId:c.slotId,anchorId:c.anchorId
        }))}}
    };
  }
  function hydrate(project, previous = null) {
    if (!project || project.kind !== "article" || project.authority !== "article" ||
        !project.draft?.article?.documentId)
      throw new Error("invalid_article_project");
    const {article,plan,creationSpec}=project.draft;
    if (plan && (plan.documentId !== article.documentId ||
        Number(plan.documentRevision) !== Number(article.revision)))
      throw new Error("article_revision_mismatch");
    const anchors = new Map((article.anchors || []).map(x=>[x.anchorId,x]));
    const cards = (plan?.slots || []).map((s,i)=>{
      if (!anchors.has(s.anchorId)) throw new Error("article_anchor_invalid");
      const link=anchors.get(s.anchorId);
      return {
        id:s.slotId,slotId:s.slotId,anchorId:s.anchorId,
        role:s.role || (link.kind === "cover" ? "cover" : "inline"),
        title:s.title || (i===0?"封面":"正文插图 "+i),
        subject:s.subject || "",purpose:s.purpose || "",
        prompt:s.prompt || "",promptCustomized:s.promptCustomized === true,
        afterBlockIdx:Number.isInteger(s.afterBlockIdx)?s.afterBlockIdx:
          Number.isInteger(link.afterBlockIdx)?link.afterBlockIdx:-1,
        anchorText:s.anchorText || "",layoutId:s.overrides?.layout?.id || "",
        styleId:s.overrides?.style?.id || "",
        ratio:s.ratio || s.overrides?.ratio || "",
        lockedFields:clone(s.lockedFields || []),
        referenceMedia:clone(s.referenceMedia || []),
        imageUrl:s.imageUrl || "",status:s.status || "idle",
        runId:s.runId || "",requestId:s.requestId || "",taskId:s.taskId || "",
        genId:s.genId || "",mediaId:s.mediaId || s.resultMediaId || "",
        sampleImg:s.sampleImg || "",variants:clone(s.variants || [])
      };
    });
    const title=str(project.title);
    // Keep unrelated local UI layout fields; the remote ArticleDocument and
    // Plan replace only after owner-scoped GET and CAS/local-draft checks.
    return {...(previous || {}),id:article.documentId,
      title,articleTitle:title,markdown:str(article.markdown),
      cards,style1:creationSpec?.style?.id || previous?.style1 || "",
      layout:creationSpec?.layout?.id || previous?.layout || "",
      styleRef:clone(creationSpec?.style || null),
      layoutRef:clone(creationSpec?.layout || null),
      referenceMedia:clone(creationSpec?.referenceMedia || []),
      inlineRatio:creationSpec?.ratio || previous?.inlineRatio || "4:3",
      coverRatio:cards.find(c=>c.role==="cover")?.ratio || previous?.coverRatio || "2.35:1",
      documentRevision:int(article.revision),planRevision:int(plan?.revision),
      planId:plan?.planId || "article-plan-" + article.documentId,
      generationId:str(plan?.generationId || previous?.generationId || ""),
      projectId:project.id,projectRevision:int(project.revision),
      projectAuthority:"article",projectSaveState:"synced",
      projectPending:null,projectCopyPending:null,projectError:"",
      projectRemoteRevision:0,isNewDraft:false
    };
  }
  function articleChanged(before, after) {
    return str(before?.articleTitle || before?.title) !== str(after?.articleTitle || after?.title) ||
      str(before?.markdown) !== str(after?.markdown);
  }
  function planChanged(before, after) {
    return JSON.stringify(cardsOf(before)) !== JSON.stringify(cardsOf(after)) ||
      str(before?.style1) !== str(after?.style1) ||
      str(before?.layout) !== str(after?.layout) ||
      JSON.stringify(before?.styleRef||null) !== JSON.stringify(after?.styleRef||null) ||
      JSON.stringify(before?.layoutRef||null) !== JSON.stringify(after?.layoutRef||null) ||
      JSON.stringify(before?.referenceMedia||[]) !== JSON.stringify(after?.referenceMedia||[]) ||
      str(before?.coverRatio) !== str(after?.coverRatio) ||
      str(before?.inlineRatio) !== str(after?.inlineRatio);
  }
  return Object.freeze({snapshot,hydrate,cardsOf,articleChanged,planChanged});
});
