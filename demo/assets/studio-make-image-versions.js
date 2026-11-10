/* #128 Quick UI: immutable, media-keyed result index.
 * A successful media item belongs to a Run, never to the editable draft.
 * No execution, new server service, or synthetic paid media is created here.
 */
(function(root,factory){
  "use strict";
  const api=factory();
  root.HandrawQuickVersions=api;
  if(typeof module==="object"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(){
  "use strict";
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const str=v=>String(v==null?"":v);
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o||{},k);
  function fromMedia(raw,{runId="",runSpec=null}={}){
    if(!raw||typeof raw!=="object")return null;
    const item=raw.item||raw;
    const mediaId=str(raw.mediaId||item.mediaId||item.media_id).trim();
    const imageUrl=str(raw.imageUrl||item.imageUrl||item.image_url).trim();
    // Only server-confirmed/owned media can enter persisted version history.
    if(!mediaId||!imageUrl||/^(data:|blob:|javascript:)/i.test(imageUrl))return null;
    const itemRunId=str(item.runId||item.run_id||raw.runId||runId).trim();
    const key=mediaId;
    const recipe=item.effectiveSpecSnapshot||item.creationSpecSnapshot||
      item.recipeSnapshot||item.metadata?.effectiveSpecSnapshot||
      (runSpec&&itemRunId&&itemRunId===str(runId)?runSpec:null);
    return {key,mediaId,runId:itemRunId,imageUrl,
      title:str(raw.title||item.title||"生成图片").slice(0,160),
      recipeSnapshot:recipe&&typeof recipe==="object"?clone(recipe):null,
      sourceMediaId:str(item.sourceMediaId||item.source_media_id||""),
      sourceWorkId:str(item.sourceWorkId||item.source_work_id||""),
      createdAt:str(item.createdAt||item.created_at||raw.createdAt||"")};
  }
  function merge(existing,candidates,options={}){
    const result=[],seen=new Map();
    for(const entry of Array.isArray(existing)?existing:[]){
      if(!entry||!entry.mediaId||!entry.imageUrl||seen.has(entry.mediaId))continue;
      const safe={...clone(entry),key:str(entry.mediaId)};
      seen.set(safe.key,result.length);result.push(safe);
    }
    for(const raw of Array.isArray(candidates)?candidates:[]){
      const next=fromMedia(raw,options);
      if(!next)continue;
      if(seen.has(next.key)){
        const current=result[seen.get(next.key)];
        // A later Run must never rewrite a prior successful media's recipe.
        result[seen.get(next.key)]={
          ...current,
          imageUrl:current.imageUrl||next.imageUrl,
          title:current.title||next.title,
          runId:current.runId||next.runId,
          recipeSnapshot:current.recipeSnapshot||next.recipeSnapshot
        };
      }else{seen.set(next.key,result.length);result.push(next);}
    }
    return result;
  }
  function select(versions,key){
    const all=Array.isArray(versions)?versions:[];
    return all.find(v=>v.key===key)||all[all.length-1]||null;
  }
  return Object.freeze({fromMedia,merge,select,clone});
});
