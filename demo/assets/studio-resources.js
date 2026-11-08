/* Studio2 ResourceRef adapter (#105).
 * Keeps existing Picker/Card UI and original Graph as the single writable truth.
 * For a selected catalog definition we preserve id/type/source/version; private
 * user uploads remain MediaRef, never DirectoryResourceRef.
 *
 * Browser checks are UX-only. The Project API must recheck access on the server.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HandrawStudioResources = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";
  const FIELDS = Object.freeze({
    style1: { type: "style", key: "style" },
    style2: { type: "style", key: "secondaryStyle" },
    layout: { type: "layout", key: "layout" },
    colors: { type: "color", key: "colors" },
    tones: { type: "tone", key: "tones" }
  });
  const GROUPS = Object.freeze({
    style: "styles", layout: "layouts", color: "colors", tone: "tones"
  });
  const SOURCE_TYPES = new Set(["official", "community", "override",
    "private", "pending", "exclusive"]);
  const RES_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{1,99}$/;
  const clone = obj => obj == null ? obj : JSON.parse(JSON.stringify(obj));

  function catalogFind(catalog, type, id) {
    const clean = String(id || "").trim();
    if (!clean || !GROUPS[type]) return null;
    const entry = catalog?.resourceMap?.get?.(clean) || catalog?.resourceMap?.[clean];
    if (entry && (!entry.kind && !entry.type || entry.kind === type ||
        entry.type === type || (type === "color" && entry.kind === "palette"))) return entry;
    return (catalog?.[GROUPS[type]] || []).find(item => item.id === clean) || null;
  }

  function makeRef(item, type, {catalogVersion = "current"} = {}) {
    if (!item || !RES_ID.test(String(item.id || "")) || !GROUPS[type]) {
      throw Object.assign(new Error("资源编号格式无效"), { code: "invalid_resource" });
    }
    const declaredType = item.kind || item.type;
    if (declaredType && declaredType !== type &&
        !(type === "color" && declaredType === "palette")) {
      throw Object.assign(new Error("资源类型与所选分类不匹配"), { code: "resource_type_mismatch" });
    }
    const rawSource = String(item.source || item.sourceType || item.source_type ||
      (item.private ? "private" : item.custom ? "private" : "official"));
    const source = rawSource === "official_override" ? "override" : rawSource;
    if (!SOURCE_TYPES.has(source)) {
      throw Object.assign(new Error("资源来源未被认可"), { code: "invalid_resource_source" });
    }
    // "current" explicitly means a mutable catalog entry. Never invent a
    // numeric revision when the definition does not expose one.
    const version = item.version ?? item.definitionVersion ?? item.revision ?? catalogVersion;
    if (!((typeof version === "string" && version.length > 0 && version.length <= 64) ||
          (Number.isInteger(version) && version >= 1))) {
      throw Object.assign(new Error("资源版本无效"), { code: "invalid_resource_version" });
    }
    return { id: String(item.id), type, source, version };
  }

  function resolveSelection(catalog, field, id, options = {}) {
    const config = FIELDS[field];
    if (!config) return {ok:false,code:"invalid_resource_field"};
    if (id === "" || id == null) return {ok:true,id:"",ref:null};
    const item = catalogFind(catalog, config.type, id);
    if (!item) return {ok:false,code:"resource_not_found",id:String(id)};
    const denied = item.canUse === false || item.access?.canUse === false ||
      (item.tier === "pro_credit" && options.isUnlocked && !options.isUnlocked(String(id), item));
    if (denied) return {ok:false,code:"resource_forbidden",id:String(id)};
    try {
      return {ok:true,id:String(id),ref:makeRef(item,config.type)};
    } catch (err) {
      return {ok:false,code:err.code || "invalid_resource",id:String(id)};
    }
  }

  function setLegacySelection(skillData, field, resolved) {
    const cfg=FIELDS[field];
    if (!skillData || !cfg || !resolved?.ok) return false;
    const refs = {...(skillData.resourceRefs || {})};
    if (field === "colors" || field === "tones") {
      const current = Array.isArray(skillData[field]) ? skillData[field].slice() : [];
      if (!resolved.id) {
        skillData[field] = [];
        refs[cfg.key] = [];
      } else {
        if (!current.includes(resolved.id)) current.push(resolved.id);
        skillData[field] = current;
        const mapped = current.map(id => {
          const found = (refs[cfg.key] || []).find(r => r.id === id);
          return id === resolved.id ? clone(resolved.ref) : found || null;
        });
        // Missing historical metadata is NOT proof of official ownership.
        // The catalog-aware syncLegacyRefs() will resolve it when saving.
        if (mapped.every(Boolean)) refs[cfg.key] = mapped;
        else delete refs[cfg.key];
      }
    } else {
      skillData[field] = resolved.id;
      refs[cfg.key] = resolved.ref;
    }
    skillData.resourceRefs = refs;
    return true;
  }

  function syncLegacyRefs(skillData, catalog, {strict = false} = {}) {
    if (!skillData || typeof skillData !== "object") return {data:skillData,errors:[]};
    const data=clone(skillData),old=data.resourceRefs || {},refs={...old},errors=[];
    for(const [field,cfg] of Object.entries(FIELDS)) {
      const chosen = field === "colors" || field === "tones"
        ? (Array.isArray(data[field]) ? data[field] : [])
        : data[field] ? [data[field]] : [];
      const mapped=[];
      for(const id of chosen) {
        const entry = catalogFind(catalog,cfg.type,id);
        if (!entry) {
          errors.push({field,code:"resource_not_found",id:String(id)});
          continue;
        }
        const ref = (Array.isArray(old[cfg.key]) ? old[cfg.key].find(x=>x?.id===id) :
          old[cfg.key]?.id === id ? old[cfg.key] : null);
        const result=resolveSelection(catalog,field,id);
        if(!result.ok) {
          errors.push({field,code:result.code,id:String(id)});
          continue;
        }
        mapped.push(ref && ref.type === cfg.type ? clone(ref) : result.ref);
      }
      if (mapped.length === chosen.length) {
        refs[cfg.key] = field === "colors" || field === "tones" ? mapped : mapped[0] || null;
      } else if (!strict) {
        // Preserve the legacy ID in the graph so users can repair a missing
        // resource, but NEVER manufacture an authorized ResourceRef for it.
        // The generation preflight blocks missing IDs before any provider call.
        delete refs[cfg.key];
      }
    }
    data.resourceRefs = refs;
    return {data,errors};
  }

  function deriveSpecResources(parts,catalog) {
    const sd=parts?.skill?.data || {};
    const normalized=syncLegacyRefs(sd,catalog);
    const r=normalized.data?.resourceRefs || {};
    return {style:r.style||null,secondaryStyle:r.secondaryStyle||null,
      layout:r.layout||null,colors:r.colors||[],tones:r.tones||[],
      fusionEnabled:Boolean(sd.fusion),errors:normalized.errors};
  }

  function mediaRefFromAsset(item) {
    // A preview URL, local File, benchmark image and upload row ID cannot be
    // used as an owned media capability. Only a real mediaId/assetUid from an
    // authenticated owner-scoped response may enter CreationSpec.
    const id = item?.mediaId || item?.assetUid;
    if (!id || typeof id !== "string" || id.length > 128) {
      return {ok:false,code:"media_upload_required",localOnly:true,ref:null};
    }
    const source = String(item.source || "");
    if (!["private","generated"].includes(source)) {
      return {ok:false,code:"media_source_unverified",ref:null};
    }
    const role = ({
      characters:"character", scenes:"scene", props:"object", other:"other"
    })[item.cat] || item.role || "other";
    if (!["character","scene","object","composition","result","other"].includes(role)) {
      return {ok:false,code:"invalid_project_media",ref:null};
    }
    return {ok:true,ref:{mediaId:id,role}};
  }

  function formatError(result) {
    const id=result?.id ? " #" + result.id : "";
    return ({
      invalid_resource_field:"不支持的资源分类",
      invalid_resource:"资源编号无效",
      resource_not_found:"资源已失效或不在当前目录中",
      resource_type_mismatch:"资源类型不匹配",
      resource_forbidden:"资源未授权或尚未解锁",
      invalid_resource_source:"资源来源无效",
      invalid_resource_version:"资源版本无效",
      resource_version_conflict:"资源定义已更新，请重新选择",
      media_upload_required:"该图片尚未上传云端，只能保存在本机草稿",
      media_source_unverified:"无法验证素材所有权，请从我的图库重新选择",
      invalid_project_media:"参考图用途无效"
    })[result?.code] || "资源不可用";
  }

  return {FIELDS,GROUPS,makeRef,resolveSelection,setLegacySelection,
    syncLegacyRefs,deriveSpecResources,catalogFind,mediaRefFromAsset,formatError};
});
