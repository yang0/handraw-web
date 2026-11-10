/* Studio 2.0 #121: pure, lossless canonical adapter over the existing
 * studio-core.js, studio-resources.js and studio-views.js contracts.
 * This module NEVER compiles prompts, grants media access or starts a Run.
 */
(function (root, factory) {
  const dep = name => (typeof require === "function" ? require(name) : null);
  const api = factory(root.HandrawStudioCore || dep("./studio-core.js"),
    root.HandrawStudioResources || dep("./studio-resources.js"),
    root.HandrawStudioViews || dep("./studio-views.js"));
  root.HandrawStudioNormalization = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis, function (Core, Resources, Views) {
  "use strict";
  if (!Core) throw new Error("studio_core_required");
  const clone = v => v === undefined ? undefined : JSON.parse(JSON.stringify(v));
  const own = (o,k) => Object.prototype.hasOwnProperty.call(o || {},k);
  const data = v => v && typeof v === "object" && !Array.isArray(v);
  const version = v => Number.isInteger(v) && v >= 0;
  const STYLE_FIELDS = Object.freeze({
    style:"style",secondaryStyle:"style",layout:"layout",
    colors:"color",tones:"tone"
  });
  const EDITABLE = new Set(["subject","outputMode","style","secondaryStyle",
    "fusionEnabled","layout","colors","tones","moods","customMood",
    "whitespace","ratio","ratioSource","referenceMedia","layoutParams",
    "audience","businessScene","userNotes"]);
  const RESOURCE_TYPES = new Set(["style","layout","color","tone"]);
  const MEDIA_ROLES = new Set(["character","scene","object","composition","result","other"]);
  const KINDS = new Set(["image","series","article"]);
  const AUTHORITIES = new Set(["spec","graph","article"]);
  const ALLOWED_PLAN = new Set(["same-spec","story-series","compare","multi-format","article"]);
  const ESCAPE = part => String(part).replace(/~/g,"~0").replace(/\//g,"~1");
  const fail = (code, path, detail) => {
    const err = new Error(code + (path ? ":" + path : ""));
    err.code=code;err.path=path||"";err.detail=detail||null;
    throw err;
  };
  const unsafe = v => {
    if (Array.isArray(v)) return v.some(unsafe);
    if (!data(v)) return false;
    return Object.entries(v).some(([k,child]) =>
      ["finalPrompt","secret_blackbox_prompt","secretBlackboxPrompt",
        "apiKey","accessToken","authorization","b64_json","base64"].includes(k) || unsafe(child));
  };

  function normalizeRef(value, type) {
    if (value == null || value === "") return null;
    if (typeof value === "string") return {id:value,type};
    if (!data(value)) return value; // Invalid input remains visible; preflight rejects.
    // Keep unknown metadata for error reports, do not invent source/version.
    return {...clone(value),type:own(value,"type") ? value.type : type};
  }

  function normalizeSpec(raw) {
    const spec=data(raw)?clone(raw):{};
    const mode=spec.outputMode || "graphic-text";
    const defaultRatio=Core.MODE_RATIO[mode] || "3:4";
    const ratio=own(spec,"ratio") ? spec.ratio : defaultRatio;
    const ratioSource=spec.ratioSource === "user" ||
      (spec.ratioSource == null && own(spec,"ratio") && ratio !== defaultRatio)
      ? "user" : "default";
    return {
      ...spec,schemaVersion:spec.schemaVersion ?? Core.VERSION,
      revision:spec.revision ?? 0,
      subject:spec.subject ?? "",outputMode:mode,
      style:normalizeRef(spec.style,"style"),
      secondaryStyle:normalizeRef(spec.secondaryStyle,"style"),
      fusionEnabled:spec.fusionEnabled === true,
      layout:normalizeRef(spec.layout,"layout"),
      colors:spec.colors===undefined?[]:
        Array.isArray(spec.colors)?spec.colors.map(r=>normalizeRef(r,"color")):clone(spec.colors),
      tones:spec.tones===undefined?[]:
        Array.isArray(spec.tones)?spec.tones.map(r=>normalizeRef(r,"tone")):clone(spec.tones),
      moods:spec.moods===undefined?[]:clone(spec.moods),
      customMood:spec.customMood ?? "",
      whitespace:spec.whitespace ?? "",ratio,ratioSource,
      referenceMedia:spec.referenceMedia===undefined?[]:clone(spec.referenceMedia),
      layoutParams:spec.layoutParams===undefined?{}:clone(spec.layoutParams),
      lockedFields:spec.lockedFields===undefined?[]:clone(spec.lockedFields)
    };
  }

  function normalizePlan(raw, article=null) {
    if (raw == null) return null;
    if (!data(raw)) fail("invalid_plan","/plan");
    const p=clone(raw);
    if (!Array.isArray(p.slots)) fail("invalid_plan_slots","/plan/slots");
    const ids=new Set();
    p.slots=p.slots.map((slot,i)=>{
      if (!data(slot) || typeof slot.slotId!=="string" || !slot.slotId.trim())
        fail("missing_slot_id","/plan/slots/"+i);
      if (ids.has(slot.slotId)) fail("duplicate_slot_id","/plan/slots/"+i);
      ids.add(slot.slotId);
      const result={...slot,
        order:own(slot,"order")?slot.order:i,
        subject:slot.subject ?? "",
        overrides:data(slot.overrides)?clone(slot.overrides):{},
        lockedFields:Array.isArray(slot.lockedFields)?clone(slot.lockedFields):[]};
      if (!version(result.order)) fail("invalid_slot_order",result.slotId);
      if (Array.isArray(slot.referenceMedia)) result.referenceMedia=clone(slot.referenceMedia);
      return result;
    });
    if (p.kind === "article") {
      if (!article || !Array.isArray(article.anchors)) fail("article_document_required","/article");
      const anchors=new Set(article.anchors.map(a=>a?.anchorId));
      if (anchors.size !== article.anchors.length || anchors.has(undefined))
        fail("duplicate_article_anchor","/article/anchors");
      for (const slot of p.slots) {
        if (!slot.anchorId || !anchors.has(slot.anchorId))
          fail("invalid_article_anchor",slot.slotId);
      }
      if (p.documentRevision != null && p.documentRevision !== article.revision)
        fail("article_revision_mismatch","/plan/documentRevision");
      p.documentId=p.documentId || article.documentId;
      p.documentRevision=article.revision;
    }
    return p;
  }

  function normalizeLegacyGraph(graph,options={}) {
    if (!data(graph) || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges))
      fail("invalid_project_graph","/graph");
    const next=clone(graph);
    const nodes=next.nodes;
    const find=type=>nodes.filter(n=>n && n.type===type);
    const sk=find("skill_params"),tx=find("text_input"),co=find("output_control"),assets=find("asset");
    const loops=find("loop");
    const warnings=[];
    let spec=null,plan=null;
    if (sk.length===1 && tx.length===1 && co.length===1) {
      const v=Core.normalizeLegacyParts({skill:sk[0],text:tx[0],ctrl:co[0],
        asset:assets.length===1?assets[0]:null},{revision:options.specRevision||0});
      spec=normalizeSpec(v.spec);
      warnings.push(...v.warnings);
    } else if (sk.length || tx.length || co.length) {
      warnings.push({code:"graph_projection_ambiguous",message:"此 Graph 只能在画布中编辑"});
    }
    if (loops.length===1) {
      const loop=loops[0];
      plan=Core.normalizeLegacyBatch(loop,{planId:loop.data?.planId || options.planId,
        key:loop.id,projectId:options.projectId});
      Core.pinLegacySlotIds(loop,plan);
    } else if (loops.length>1) {
      warnings.push({code:"multiple_loops_read_only",message:"多循环 Graph 仅保留原始节点"});
    }
    return {graph:next,projection:{spec,plan,expressibility:Views?.classify(next)||null},warnings};
  }

  function validateModel(model) {
    const errors=[];
    const add=(path,code)=>errors.push({path,code});
    const wire=model?.wire || model;
    if (!data(wire) || wire.schemaVersion !== 1) add("/schemaVersion","invalid_schema_version");
    const project=wire?.project;
    if (!data(project) || typeof project.id!=="string" || !project.id)
      add("/project/id","invalid_project_id");
    if (!KINDS.has(project?.kind)) add("/project/kind","invalid_project_kind");
    if (!AUTHORITIES.has(project?.authority)) add("/project/authority","invalid_project_authority");
    if (!version(project?.revision)) add("/project/revision","invalid_project_revision");
    const spec=wire?.creationSpec;
    if (!data(spec) || spec.schemaVersion!==1 || !version(spec.revision))
      add("/creationSpec","invalid_creation_spec");
    else {
      if (typeof spec.subject!=="string") add("/creationSpec/subject","invalid_subject");
      if (!Object.keys(Core.MODE_RATIO).includes(spec.outputMode))
        add("/creationSpec/outputMode","invalid_output_mode");
      if (spec.ratioSource!=="user" && spec.ratioSource!=="default")
        add("/creationSpec/ratioSource","invalid_ratio_source");
      if (!Core.validateRatio(spec.ratio).ok) add("/creationSpec/ratio","invalid_ratio");
      if (!Array.isArray(spec.referenceMedia)) add("/creationSpec/referenceMedia","invalid_media");
      if (!Array.isArray(spec.colors)||!Array.isArray(spec.tones))
        add("/creationSpec","invalid_resource_list");
      if (!Array.isArray(spec.moods)) add("/creationSpec/moods","invalid_moods");
      if (!Array.isArray(spec.lockedFields)||new Set(spec.lockedFields).size!==spec.lockedFields.length)
        add("/creationSpec/lockedFields","invalid_locks");
      if (!data(spec.layoutParams)) add("/creationSpec/layoutParams","invalid_layout_params");
      if (spec.style!=null && !data(spec.style)) add("/creationSpec/style","invalid_resource");
      for (const [field,type] of Object.entries(STYLE_FIELDS)) {
        const many=field==="colors" || field==="tones";
        const v=spec[field];
        for(const r of (many?Array.isArray(v)?v:[v]:v?[v]:[])) {
          if (!data(r) || typeof r.id!=="string" || !r.id || r.type!==type)
            add("/creationSpec/"+field,"invalid_resource_ref");
        }
      }
      for (const [idx,m] of (Array.isArray(spec.referenceMedia)?spec.referenceMedia:[]).entries()) {
        if (!data(m)||typeof m.mediaId!=="string"||!m.mediaId ||
            !MEDIA_ROLES.has(m.role)) add("/creationSpec/referenceMedia/"+idx,"invalid_media_ref");
      }
    }
    if (wire?.plan) {
      const plan=wire.plan;
      if (!data(plan) || !plan.planId || !version(plan.revision) ||
          !ALLOWED_PLAN.has(plan.kind) || !Array.isArray(plan.slots)) {
        add("/plan","invalid_plan");
      } else {
        const ids=new Set();
        for (const [i,s] of plan.slots.entries()) {
          if (!data(s)||!s.slotId||ids.has(s.slotId)||!version(s.order)||
              !data(s.overrides)||!Array.isArray(s.lockedFields))
            add("/plan/slots/"+i,"invalid_slot");
          if (s?.slotId) ids.add(s.slotId);
          if (plan.kind==="article" && !wire.article?.anchors?.some(a=>a.anchorId===s.anchorId))
            add("/plan/slots/"+i+"/anchorId","invalid_article_anchor");
        }
        if (plan.kind==="article" &&
            (plan.documentRevision!==wire.article?.revision ||
             plan.documentId!==wire.article?.documentId))
          add("/plan/documentRevision","article_revision_mismatch");
      }
    }
    if (project?.authority==="graph" &&
        (!data(wire?.graph)||!Array.isArray(wire.graph.nodes)||!Array.isArray(wire.graph.edges)))
      add("/graph","graph_authority_requires_graph");
    if (project?.authority==="article" &&
        (!data(wire?.article)||!Array.isArray(wire.article.anchors)||!version(wire.article.revision)))
      add("/article","article_authority_requires_document");
    return {ok:errors.length===0,errors};
  }

  function normalizeDocument(raw,options={}) {
    if (!data(raw)||!data(raw.project)) fail("invalid_studio_document");
    if (unsafe(raw)) fail("protected_prompt_in_client_draft");
    const wire=clone(raw);
    wire.schemaVersion=wire.schemaVersion??1;
    wire.creationSpec=normalizeSpec(wire.creationSpec);
    let projection=null,warnings=[];
    if (wire.graph) {
      const out=normalizeLegacyGraph(wire.graph,{
        projectId:wire.project.id,planId:wire.plan?.planId});
      wire.graph=out.graph;
      projection=out.projection;
      warnings=out.warnings;
    }
    if (wire.plan) wire.plan=normalizePlan(wire.plan,wire.article);
    else if (wire.project.authority==="graph" && projection?.plan) {
      // A legacy Graph loop can be read as Plan, but it is never persisted
      // as a competing writable source unless explicitly adopted.
      projection.plan=normalizePlan(projection.plan);
    }
    const check=validateModel(wire);
    if (!check.ok && options.strict) fail("invalid_studio_schema","",check.errors);
    return {wire,projection,warnings,validation:check,
      writable:wire.project.authority==="graph"?["graph"]:
        wire.project.authority==="article"?["article","creationSpec","plan"]:
          ["creationSpec","plan"]};
  }

  function serializeDocument(model) {
    const wire=clone(model?.wire||model);
    if (!data(wire)||unsafe(wire)) fail("protected_prompt_in_client_draft");
    // Derived views are deliberately not serialized. Preserve all original
    // Graph nodes/edges, document anchors, media metadata and unknown legacy data.
    const canonical=normalizeDocument(wire);
    if (!canonical.validation.ok) fail("invalid_studio_schema","",canonical.validation.errors);
    return JSON.stringify(canonical.wire);
  }
  function reload(serialized) { return normalizeDocument(JSON.parse(serialized)); }

  function patchDocument(model,patch,baseRevision) {
    const state=normalizeDocument(model.wire||model,{strict:true});
    const doc=state.wire;
    if (doc.project.revision!==baseRevision) fail("project_revision_conflict");
    const ops=Array.isArray(patch)?patch:[patch];
    if (!ops.length||ops.length>32) fail("invalid_patch");
    for (const op of ops) {
      if (!data(op)||op.op!=="set"||typeof op.path!=="string"||!own(op,"value"))
        fail("invalid_patch");
      const tokens=op.path.split("/").slice(1).map(p=>p.replace(/~1/g,"/").replace(/~0/g,"~"));
      const root=tokens[0];
      if (!state.writable.includes(root)) fail("editor_authority_conflict",op.path);
      if (root==="creationSpec"&&tokens.length===2) {
        const key=tokens[1];
        if (!EDITABLE.has(key)) fail("invalid_patch_field",op.path);
        doc.creationSpec=Core.applySpecPatch(doc.creationSpec,{[key]:op.value},
          doc.creationSpec.revision);
      } else if (root==="plan"&&tokens.length===5&&tokens[1]==="slotsById"&&
                 tokens[3]==="overrides") {
        const [slotId,field]=[tokens[2],tokens[4]];
        const plan=doc.plan;
        const candidates=plan?.slots?.filter(s=>s.slotId===slotId)||[];
        if(candidates.length!==1) fail("unknown_slot_id",op.path);
        if(!EDITABLE.has(field)) fail("invalid_override_field",op.path);
        const slot=candidates[0];
        if ((slot.lockedFields||[]).includes(field)||
            (doc.creationSpec.lockedFields||[]).includes(field))
          fail("locked_field",op.path);
        slot.overrides[field]=clone(op.value);
        plan.revision++;
      } else if(root==="graph"&&tokens.length===5&&tokens[1]==="nodesById"&&
               tokens[3]==="data"&&Views) {
        doc.graph=Views.patchNode(doc.graph,{nodeId:tokens[2],field:tokens[4],
          value:op.value,baseRevision:Number(doc.graph.revision||0)});
      } else fail("invalid_patch_field",op.path);
    }
    doc.project.revision++;
    const fresh=normalizeDocument(doc,{strict:true});
    return fresh;
  }

  function validateForExecution(spec,{catalog,verifyMediaOwner}={}) {
    const errors=[];
    errors.push(...Core.validateSpec(spec,{catalog}).errors);
    if (!catalog) errors.push({field:"catalog",code:"resource_authorization_required"});
    if (spec?.referenceMedia != null && !Array.isArray(spec.referenceMedia)) {
      errors.push({field:"referenceMedia",code:"invalid_project_media"});
    }
    for (const [index,ref] of (Array.isArray(spec?.referenceMedia)?spec.referenceMedia:[]).entries()) {
      if (!data(ref)||typeof ref.mediaId!=="string"||!ref.mediaId||
          !MEDIA_ROLES.has(ref.role)) {
        errors.push({field:"referenceMedia",index,code:"invalid_project_media"});
        continue;
      }
      if (typeof verifyMediaOwner!=="function")
        errors.push({field:"referenceMedia",index,code:"media_authorization_required",id:ref.mediaId});
      else if (!verifyMediaOwner(ref.mediaId))
        errors.push({field:"referenceMedia",index,code:"project_media_forbidden",id:ref.mediaId});
    }
    return {ok:errors.length===0,errors};
  }

  function executionSpec(globalSpec,slot,options={}) {
    const effective=Core.resolveEffectiveSpec(globalSpec,slot);
    // No token-capable client reference is proof of access. Caller must check
    // current catalog entitlement and owner media against the server.
    const check=validateForExecution(effective,options);
    if(!check.ok) fail("execution_preflight_failed","",check.errors);
    return effective;
  }

  return Object.freeze({normalizeSpec,normalizePlan,normalizeLegacyGraph,
    normalizeDocument,serializeDocument,reload,validateModel,patchDocument,
    validateForExecution,executionSpec});
});
