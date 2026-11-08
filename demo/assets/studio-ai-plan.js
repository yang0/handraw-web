/* Studio #125: one review/merge/undo client for the three AI planning entries.
 * No network/generation or graph reconstruction: edits target #121/#123
 * canonical adapters only. Server models are untrusted until validated here.
 */
(function(root,factory){
  "use strict";
  const dep=name=>typeof require==="function"?require(name):null;
  const api=factory(root.HandrawQuickSpec||dep("./studio-quick-spec.js"),
    root.HandrawStudioSeries||dep("./studio-series-plan.js"),
    root.HandrawStudioResources||dep("./studio-resources.js"),
    root.HandrawStudioCore||dep("./studio-core.js"));
  root.HandrawStudioAIPlan=api;
  if(typeof module==="object"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(Quick,Series,Resources,Core){
  "use strict";
  const copy=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  const fail=(code)=>{const e=new Error(code);e.code=code;throw e;};
  const SPEC_FIELDS=["style","layout","ratio"];
  function validResponse(result,kind,baseRevision,planRevision) {
    if(!result?.ok||result.schemaVersion!==1||result.kind!==kind||
      result.source!=="model"||result.phase!=="review"||
      result.baseRevision!==baseRevision||
      result.creationSpecPatch?.baseRevision!==baseRevision ||
      !result.creationSpecPatch?.changes || !result.creationSpecPatch?.reasons ||
      result.cost?.generationStarted!==false||result.cost?.runCreated!==false)
      fail("ai_invalid_proposal");
    if(kind!=="image" && (!result.planPatch ||
      result.planPatch.baseRevision!==planRevision ||
      !Array.isArray(result.planPatch.slots)))fail("ai_plan_revision_conflict");
  }
  function verifyResource(field,value,catalog,isUnlocked) {
    if(typeof value!=="object"||!value?.id||!value?.source||
       !value?.version||value.type!==(field==="style"?"style":"layout"))
       fail("invalid_resource_ref");
    const checked=Resources.resolveSelection(catalog,field==="style"?"style1":"layout",
      value.id,{isUnlocked});
    if(!checked.ok)fail(checked.code);
    if(checked.ref.type!==value.type||checked.ref.source!==value.source||
      (value.version!=="current"&&checked.ref.version!=="current"&&
       String(checked.ref.version)!==String(value.version)))fail("resource_version_conflict");
    return checked.ref;
  }
  const display=v=>typeof v==="object"?v?.id||JSON.stringify(v):String(v??"");
  function review(result,{kind,baseRevision,planRevision=0,currentSpec={},
      currentPlan=null,catalog,isUnlocked,manualFields=[]}={}) {
    validResponse(result,kind,baseRevision,planRevision);
    const patches=result.creationSpecPatch;
    if(!catalog)fail("resource_authorization_required");
    const changeKeys=Object.keys(patches.changes);
    if(changeKeys.length!==3||changeKeys.some(k=>!SPEC_FIELDS.includes(k)))
      fail("ai_invalid_proposal");
    const proposed={
      style:verifyResource("style",patches.changes.style,catalog,isUnlocked),
      layout:verifyResource("layout",patches.changes.layout,catalog,isUnlocked),
      ratio:patches.changes.ratio
    };
    if(!Core.validateRatio(proposed.ratio).ok)fail("invalid_ratio");
    const locks=new Set(currentSpec.lockedFields||[]);
    const manual=new Set([...(manualFields||[]),...(currentSpec.userOverrides||[])]);
    const conflicts=[],accepted=[],all=[];
    const add=(key,field,from,to,reason,protectedField)=>{
      if(same(from,to))return;
      const item={key,field,from:copy(from),to:copy(to),
        reason:String(reason||"").slice(0,240),locked:Boolean(protectedField==="locked"),
        conflict:Boolean(protectedField)};
      all.push(item);
      if(item.conflict)conflicts.push(item);else accepted.push(item);
    };
    for(const field of SPEC_FIELDS){
      const from=currentSpec[field]||null,to=proposed[field];
      const isLocked=locks.has(field);
      const edited=manual.has(field)||
        (field==="ratio"?currentSpec.ratioSource==="user":
         !!from && typeof from==="object" && !!from.id);
      add(field,field,from,to,patches.reasons[field],isLocked?"locked":edited?"manual":null);
    }
    const planned=[];
    if(kind!=="image"){
      const currentSlots=currentPlan?.slots||[],raw=result.planPatch.slots;
      const ids=new Set();
      for(let i=0;i<raw.length;i++){
        const slot=raw[i],prior=currentSlots[i]||null;
        if(!slot||typeof slot.slotId!=="string"||!slot.slotId||ids.has(slot.slotId)||
           typeof slot.subject!=="string"||!slot.subject.trim()||
           !slot.overrides?.layout||!slot.overrides?.ratio||!slot.reasons)
           fail("ai_invalid_plan_slot");
        const layout=verifyResource("layout",slot.overrides.layout,catalog,isUnlocked);
        const ratio=slot.overrides.ratio;
        if(!Core.validateRatio(ratio).ok)fail("invalid_ratio");
        ids.add(slot.slotId);
        // Existing slots are authoritative by identity/order, not a model ID.
        if(prior && prior.slotId!==slot.slotId)fail("ai_slot_identity_conflict");
        const base=prior?copy(prior):{
          slotId:slot.slotId,order:i,subject:"",overrides:{},
          lockedFields:[],userOverrides:[],referenceMedia:[],skipGlobalRefs:false};
        const suggestions={subject:slot.subject.trim(),layout,ratio};
        const protectedFields=new Set(base.lockedFields||[]);
        const overrides=new Set(base.userOverrides||[]);
        for(const [field,to] of Object.entries(suggestions)){
          const from=field==="subject"?base.subject:base.overrides?.[field]||null;
          const manual=overrides.has(field)||
            (field==="subject" ? Boolean(base.subject) :
              Boolean(base.overrides?.[field]));
          add("slot:"+slot.slotId+":"+field,field,from,to,
            slot.reasons[field]||"",protectedFields.has(field)?"locked":manual?"manual":null);
        }
        planned.push({...base,order:i,
          ...(kind==="article"?{anchorId:slot.anchorId,
            afterBlockIdx:slot.afterBlockIdx,role:slot.role}:{} )});
      }
      // Never implicitly delete manually extended slots or their media.
      for(let i=raw.length;i<currentSlots.length;i++){
        planned.push({...copy(currentSlots[i]),order:planned.length});
      }
    }
    return {kind,baseRevision,planRevision,
      proposals:proposed,planned,changes:all,accepted,conflicts,
      source:result,hasConflicts:conflicts.length>0};
  }
  function approvedDelta(report,approvedKeys=[]){
    const granted=new Set(approvedKeys);
    const selected=report.changes.filter(x=>!x.conflict||
      (!x.locked&&granted.has(x.key)));
    const spec={},slots=new Map();
    for(const x of selected){
      if(x.key.startsWith("slot:")){
        const match=report.planned.find(s=>x.key.startsWith("slot:"+s.slotId+":"));
        if(!match)fail("ai_slot_identity_conflict");
        let m=slots.get(match.slotId);
        if(!m){m={};slots.set(match.slotId,m);}
        m[x.field]=copy(x.to);
      }else spec[x.field]=copy(x.to);
    }
    return {spec,slots,selected};
  }
  function signature(parts,loop){
    const output={skill:copy(parts?.skill?.data),text:copy(parts?.text?.data),
      ctrl:copy(parts?.ctrl?.data)};
    if(loop)output.loop=copy(loop.data);
    return JSON.stringify(output);
  }
  function apply(report,{parts,loop=null,catalog,isUnlocked,approvedKeys=[]}={}){
    if(!parts?.skill||!parts?.text||!parts?.ctrl)fail("missing_quick_nodes");
    if(!catalog)fail("resource_authorization_required");
    const currentRevision=Quick.read(parts).spec.revision;
    if(currentRevision!==report.baseRevision)fail("ai_revision_conflict");
    if(loop&&Series.read(loop).revision!==report.planRevision)
      fail("ai_plan_revision_conflict");
    const before=signature(parts,loop);
    const change=approvedDelta(report,approvedKeys);
    if(!change.selected.length && (!loop||!report.planned.some(s=>!s.subject)))
      return {applied:[],undo:null,conflicts:report.conflicts};
    // Stage both patches on detached node.data. Never partially write Graph.
    const stage=copy(parts);
    const stageLoop=loop?copy(loop):null;
    if(Object.keys(change.spec).length){
      Quick.apply(stage,change.spec,{catalog,isUnlocked});
    }
    if(stageLoop){
      const plan=Series.read(stageLoop),result=[];
      for(const slot of report.planned){
        const updated=copy(slot),changes=change.slots.get(slot.slotId)||{};
        for(const [field,value] of Object.entries(changes)){
          if(field==="subject")updated.subject=value;
          else updated.overrides={...(updated.overrides||{}),[field]:value};
        }
        result.push(updated);
      }
      if(!same(result,plan.slots)){
        Series.sync(stageLoop,{...plan,revision:plan.revision+1,slots:result});
      }
    }
    const pre=copy({skill:parts.skill.data,text:parts.text.data,
      ctrl:parts.ctrl.data,loop:loop?.data});
    // Only these canonical node.data owners are changed; graph topology,
    // ArticleDocument, referenceMedia and RunSnapshot are untouched.
    Object.assign(parts.skill.data,stage.skill.data);
    Object.assign(parts.text.data,stage.text.data);
    Object.assign(parts.ctrl.data,stage.ctrl.data);
    if(loop)Object.assign(loop.data,stageLoop.data);
    return {applied:change.selected.map(x=>x.key),conflicts:report.conflicts,
      undo:{before:pre,after:signature(parts,loop),reportRevision:report.baseRevision}};
  }
  function undo(token,{parts,loop=null}={}){
    if(!token||!parts||signature(parts,loop)!==token.after)fail("ai_undo_conflict");
    const before=token.before;
    // Undo only if every relevant source remained byte-for-byte unchanged
    // since our commit. This prevents overwriting later manual edits.
    for(const [node,data] of [["skill",before.skill],["text",before.text],["ctrl",before.ctrl]]){
      for(const key of Object.keys(parts[node].data))delete parts[node].data[key];
      Object.assign(parts[node].data,copy(data));
    }
    if(loop&&before.loop){
      for(const key of Object.keys(loop.data))delete loop.data[key];
      Object.assign(loop.data,copy(before.loop));
    }
    return true;
  }
  function message(code){
    return ({
      ai_upstream_502:"AI 上游 HTTP 502，请检查网关状态",
      ai_invalid_json:"AI 返回无效 JSON，原方案未修改",
      ai_resource_forbidden:"AI 推荐了没有使用权限的资源",
      ai_resource_not_found:"AI 返回不存在或已失效的资源",
      ai_cannot_recommend:"AI 未能产生完整方案，请调整主题",
      ai_schema_invalid:"AI 规划结构不符合规范，原方案未修改",
      ai_revision_conflict:"规划期间草稿已改变，未覆盖新版",
      ai_plan_revision_conflict:"分镜计划版本已变化，未覆盖新版",
      ai_undo_conflict:"撤销前方案已再次修改，无法安全撤销",
      resource_forbidden:"资源尚未解锁，请改用有权限的资源"
    })[code]||"AI 规划未能应用："+String(code||"unknown");
  }
  return Object.freeze({review,apply,undo,approvedDelta,validResponse,message});
});
