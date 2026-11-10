/* Issue #105: Article consumes the same typed catalog and media adapters
 * as Quick, Series and Canvas. No duplicated picker or permission model.
 */
(function (root, factory) {
  const shared = root?.HandrawStudioResources ||
    (typeof require === "function" ? require("./studio-resources.js") : null);
  const api = factory(shared);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HandrawStudioArticlePicker105 = api;
})(typeof window !== "undefined" ? window : globalThis, function (Resources) {
  "use strict";
  const copy = value => value == null ? value : JSON.parse(JSON.stringify(value));
  const FIELDS = Object.freeze({
    style1:{id:"styleId",ref:"styleRef",type:"style"},
    layout:{id:"layoutId",ref:"layoutRef",type:"layout"}
  });
  function error(code, id = "") {
    return {ok:false,code,id,message:Resources?.formatError({code,id}) ||
      "资源不可用"};
  }
  function applyResource(draft,field,id,ref) {
    const cfg=FIELDS[field];
    if(!draft || !cfg) return error("invalid_resource_field",id);
    if(!id) return error("resource_required",id);
    if(!ref || ref.id!==id || ref.type!==cfg.type ||
       !ref.source || (ref.version == null))
      return error("resource_type_mismatch",id);
    draft[cfg.id]=id;
    draft[cfg.ref]=copy(ref);
    return {ok:true,id,ref:copy(ref)};
  }
  function validateForExecution(draft,catalog,{isUnlocked}={}) {
    if(!Resources) return error("invalid_resource_field");
    for(const [field,cfg] of Object.entries(FIELDS)) {
      const id=String(draft?.[cfg.id] || "");
      if(!id) return error("resource_required",id);
      const result=Resources.resolveSelection(catalog,field,id,{isUnlocked});
      if(!result.ok) return {...result,message:Resources.formatError(result)};
      const pinned=draft?.[cfg.ref];
      if(pinned && (pinned.id!==id || pinned.type!==cfg.type ||
         pinned.source!==result.ref?.source ||
         (pinned.version!=="current" && String(pinned.version)!==String(result.ref?.version))))
        return error("resource_version_conflict",id);
    }
    const media=Array.isArray(draft?.referenceMedia)?draft.referenceMedia:[];
    const seen=new Set();
    for(const ref of media) {
      if(!ref || typeof ref.mediaId!=="string" || !ref.mediaId ||
         !["character","scene","object","composition","result","other"].includes(ref.role) ||
         seen.has(ref.mediaId)) return error("invalid_project_media");
      seen.add(ref.mediaId);
    }
    return {ok:true,code:"ok"};
  }
  function normalizeAssetSelection(items) {
    if(!Array.isArray(items)) return error("invalid_project_media");
    if(items.length>6) return error("media_count_exceeded");
    const referenceItems=[],referenceMedia=[],seen=new Set();
    for(const item of items) {
      const id=String(item?.id||"");
      if(!id || seen.has(id)) return error("invalid_project_media");
      seen.add(id);
      const source=String(item?.source||"");
      const confirmed=Resources?.mediaRefFromAsset(item);
      // Official samples may be selected for prompt composition, but are
      // never presented as owner-authorized private MediaRefs.
      if(!confirmed?.ok && !(source==="official" && item?.image))
        return error(confirmed?.code||"media_upload_required",id);
      referenceItems.push({id,name:String(item.name||id),
        image:String(item.image||""),cat:String(item.cat||"other"),
        source,mediaId:confirmed?.ok?confirmed.ref.mediaId:"",
        role:confirmed?.ok?confirmed.ref.role:String(item.role||"other")});
      if(confirmed?.ok) referenceMedia.push(confirmed.ref);
    }
    return {ok:true,referenceItems,referenceMedia};
  }
  return Object.freeze({FIELDS,applyResource,validateForExecution,
    normalizeAssetSelection});
});
