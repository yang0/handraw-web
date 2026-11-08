/* Issue #122: single-image form bridge to #121 CreationSpec.
 * The Graph node remains the only writable source during this rollout.
 * No prompt assembly, network call or independent draft store lives here.
 */
(function (root, factory) {
  "use strict";
  const core = root.HandrawStudioCore ||
    (typeof require === "function" && require("./studio-core.js"));
  const norm = root.HandrawStudioNormalization ||
    (typeof require === "function" && require("./studio-normalization.js"));
  const resources = root.HandrawStudioResources ||
    (typeof require === "function" && require("./studio-resources.js"));
  const api = factory(core, norm, resources);
  root.HandrawQuickSpec = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis, function (Core, N, RR) {
  "use strict";
  if (!Core || !N || !RR) throw new Error("studio_adapter_dependencies_missing");
  const own = (v, k) => Object.prototype.hasOwnProperty.call(v || {}, k);
  const clone = v => v == null ? v : JSON.parse(JSON.stringify(v));
  const resourceFields = {
    style: ["style1", "style"], secondaryStyle: ["style2", "style"],
    layout: ["layout", "layout"], colors: ["colors", "color"],
    tones: ["tones", "tone"]
  };
  const simpleFields = {
    subject: ["text","text"], fusionEnabled: ["skill","fusion"],
    customMood: ["skill","customMood"], moods: ["skill","moods"],
    whitespace: ["skill","whitespace"], audience: ["skill","audience"],
    businessScene: ["skill","businessScene"], userNotes: ["skill","userNotes"]
  };
  const patchable = new Set([...Object.keys(resourceFields),
    ...Object.keys(simpleFields),"outputMode","ratio","ratioSource","layoutParams"]);
  const fail=(code, field)=>Object.assign(new Error(code),{code,field});
  const required=(parts)=>{
    if (!parts?.skill?.data || !parts?.text?.data || !parts?.ctrl?.data)
      throw fail("missing_quick_nodes");
    return parts;
  };

  function read(parts) {
    required(parts);
    const {spec,warnings}=Core.normalizeLegacyParts(parts,{
      revision:Number(parts.skill.data.studioSpecRevision || 0)
    });
    return {spec:N.normalizeSpec(spec),warnings};
  }

  function resolveResource(field, value, options) {
    const cfg=resourceFields[field];
    const isMany=field==="colors"||field==="tones";
    const refs=isMany?(Array.isArray(value)?value:[]):[value];
    if (isMany && !Array.isArray(value)) throw fail("invalid_resource_list",field);
    const accepted=refs.map(raw=>{
      if (raw == null || raw === "") {
        if (isMany) throw fail("invalid_resource",field);
        return null;
      }
      const id=typeof raw==="string"?raw:raw?.id;
      if (!id) throw fail("invalid_resource",field);
      // All UI selections pass through the same Picker and catalog entitlement.
      if (!options.catalog) throw fail("resource_authorization_required",field);
      const checked=RR.resolveSelection(options.catalog,cfg[0],id,{
        isUnlocked:options.isUnlocked
      });
      if (!checked.ok) throw fail(checked.code,field);
      if (typeof raw==="object" && raw !== null) {
        if (raw.type !== cfg[1]) throw fail("resource_type_mismatch",field);
        if (raw.source && raw.source !== checked.ref.source)
          throw fail("resource_source_mismatch",field);
        if (raw.version != null && raw.version !== "current" &&
            String(raw.version)!==String(checked.ref.version))
          throw fail("resource_version_conflict",field);
      }
      return checked.ref;
    });
    return isMany?accepted:accepted[0];
  }

  function apply(parts, delta, options={}) {
    required(parts);
    const changes=Object.entries(delta||{});
    if (!changes.length) return read(parts).spec;
    if (changes.some(([key])=>!patchable.has(key))) throw fail("invalid_patch_field");
    const prior=read(parts).spec;
    // No write until the complete delta has passed validation and user locks.
    const verified={};
    for (const [field,value] of changes) {
      if (own(resourceFields,field)) verified[field]=resolveResource(field,value,options);
      else if (field==="layoutParams") {
        if (!value || typeof value!=="object" || Array.isArray(value))
          throw fail("invalid_layout_params",field);
        for (const key of Object.keys(value)) {
          if (!["sc021Type","sc022Name","sc022Pinyin"].includes(key))
            throw fail("invalid_layout_param",key);
          if (prior.lockedFields?.includes("layoutParams."+key))
            throw fail("locked_field",key);
        }
        verified[field]={...prior.layoutParams,...clone(value)};
      } else verified[field]=clone(value);
    }
    const next=Core.applySpecPatch(prior,verified,prior.revision);
    if (own(verified,"ratio") && !Core.validateRatio(next.ratio).ok)
      throw fail("invalid_ratio","ratio");
    if (own(verified,"outputMode") &&
        !["graphic-text","pure","poster"].includes(next.outputMode))
      throw fail("invalid_output_mode","outputMode");
    const sd=parts.skill.data, td=parts.text.data, cd=parts.ctrl.data;
    // Write ONLY touched fields. Never replace unrelated Graph node data.
    for (const [field,ref] of Object.entries(verified)) {
      if (own(resourceFields,field)) {
        const [legacy]=resourceFields[field], isMany=Array.isArray(ref);
        sd[legacy]=isMany?ref.map(r=>r.id):ref?.id||"";
        sd.resourceRefs={...(sd.resourceRefs||{}),[field]:clone(ref)};
      } else if (field==="subject") td.text=next.subject;
      else if (field==="outputMode") {
        Core.setMode(cd,next.outputMode);
      } else if (field==="ratio") {
        Core.setRatio(cd,next.ratio);
      } else if (field==="ratioSource") {
        cd.ratioSource=next.ratioSource;
      } else if (field==="layoutParams") {
        for (const key of Object.keys(delta.layoutParams)) sd[key]=next.layoutParams[key];
      } else if (own(simpleFields,field)) {
        const [,key]=simpleFields[field];
        sd[key]=clone(next[field]);
      }
    }
    sd.studioSpecRevision=next.revision;
    return read(parts).spec;
  }

  function setAssets(parts, items) {
    required(parts);
    if (!parts.asset?.data) throw fail("missing_asset_node");
    if (!Array.isArray(items)) throw fail("invalid_asset_items");
    // Never turn local preview/blob URLs into a fake owned media capability.
    parts.asset.data.items=clone(items);
    parts.skill.data.studioSpecRevision=
      Math.max(0,Number(parts.skill.data.studioSpecRevision)||0)+1;
    return read(parts);
  }

  function preflight(parts, options={}) {
    const spec=read(parts).spec;
    const errors=[...Core.validateSpec(spec,{catalog:options.catalog}).errors];
    if (!options.catalog) errors.push({field:"catalog",code:"resource_authorization_required"});
    for (const [field,legacy] of Object.entries({
      style:"style1",secondaryStyle:"style2",layout:"layout",
      colors:"colors",tones:"tones"
    })) {
      if (field==="secondaryStyle"&&!spec.fusionEnabled) continue;
      const val=spec[field];
      const list=Array.isArray(val)?val:(val?[val]:[]);
      for(const ref of list){
        const r=RR.resolveSelection(options.catalog,legacy,ref?.id,{
          isUnlocked:options.isUnlocked
        });
        if (!r.ok) errors.push({field,code:r.code,id:ref?.id});
      }
    }
    // Catalog identity and private media owner are separate. This preflight
    // is intentionally UX-only: backend must revalidate both at reservation.
    return {ok:errors.length===0,errors,spec};
  }

  function capture(parts,{graph,projectRevision=0,projectId="",catalog,isUnlocked}={}) {
    const result=preflight(parts,{catalog,isUnlocked});
    if (!result.ok) throw fail(result.errors[0]?.code||"invalid_spec",
      result.errors[0]?.field);
    return clone({schemaVersion:1,projectId,projectRevision,
      spec:Core.resolveEffectiveSpec(result.spec,null),
      graph:graph||null});
  }

  function fork(parts,draft,options={}) {
    if(!draft || typeof draft!=="object")return read(parts).spec;
    // Existing #100 supplies the exact selected image's parameters. They
    // remain visible even when a formerly usable catalog code is now revoked;
    // execution preflight rejects the stale code instead of substituting one.
    const src=parts.skill.data,td=parts.text.data,cd=parts.ctrl.data;
    const ownDraft=(k)=>own(draft,k);
    if (ownDraft("styleIds")) {
      src.style1=draft.styleIds?.[0]||"";
      src.style2=draft.styleIds?.[1]||"";
      src.fusion=Boolean(draft.styleIds?.length>1);
      if(src.resourceRefs) {
        delete src.resourceRefs.style;
        delete src.resourceRefs.secondaryStyle;
      }
    }
    if(ownDraft("layoutId")) {
      src.layout=draft.layoutId||"";
      if(src.resourceRefs) delete src.resourceRefs.layout;
    }
    for(const field of ["colors","tones","moods","customMood","whitespace","audience",
      "businessScene","sc021Type","sc022Name","sc022Pinyin"]){
      if(!ownDraft(field)) continue;
      src[field]=clone(draft[field]);
      if(src.resourceRefs && (field==="colors"||field==="tones"))
        delete src.resourceRefs[field];
    }
    const subject=String(draft.subjectHint || draft.subject || "").trim();
    if(subject) td.text=subject;
    if(ownDraft("ratio") && draft.ratio) {
      if (!Core.validateRatio(draft.ratio).ok) throw fail("invalid_ratio","ratio");
      cd.ratio=draft.ratio;cd.ratioSource="user";
    }
    if(ownDraft("mode")) Core.setMode(cd,draft.mode==="pure-image"?"pure":
      ["graphic-text","pure","poster"].includes(draft.mode)?draft.mode:"graphic-text");
    cd.count=1;
    src.studioSpecRevision=Math.max(0,Number(src.studioSpecRevision)||0)+1;
    return read(parts).spec;
  }

  // V3 Run + RunItems are server-owned. A DOM preview is not a successful
  // billed item, and an aborted browser request does not mean remote cancel.
  function projectRun(payload,{cancelRequested=false}={}) {
    if(!payload?.run || !Array.isArray(payload.items))
      return {ok:false,viewStatus:"unknown",completed:0,items:[],runId:""};
    const p=Core.selectRunProjection(payload.run,payload.items,{cancelRequested,authoritativeSlots:payload.slots});
    const results=payload.items.filter(item=>item.status==="success" &&
      item.mediaId && item.imageUrl);
    return {...p,ok:true,completed:p.succeeded,runId:payload.run.id,
      items:clone(payload.items),results:clone(results)};
  }

  const api=Object.freeze({read,apply,setAssets,preflight,capture,fork,projectRun});
  return api;
});
