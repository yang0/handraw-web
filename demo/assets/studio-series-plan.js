/* Studio 2.0 #123 · PlanSlot is authoritative in the existing Loop node.
 * promptListText and batchRows are compatibility projections, not independent
 * writers. No prompt engine, Run state machine or new database is introduced.
 */
(function(root,factory) {
  "use strict";
  const core=root.HandrawStudioCore ||
    (typeof require==="function"&&require("./studio-core.js"));
  const normalized=root.HandrawStudioNormalization ||
    (typeof require==="function"&&require("./studio-normalization.js"));
  const refs=root.HandrawStudioResources ||
    (typeof require==="function"&&require("./studio-resources.js"));
  const api=factory(core,normalized,refs);
  root.HandrawStudioSeries=api;
  if(typeof module==="object"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(Core,N,Resources){
  "use strict";
  if(!Core||!N||!Resources)throw Error("series_adapter_dependencies_missing");
  const copy=x=>x==null?x:JSON.parse(JSON.stringify(x));
  const owns=(x,k)=>Object.prototype.hasOwnProperty.call(x||{},k);
  const err=(code)=>Object.assign(new Error(code),{code});
  let nextId=0;
  const newId=()=> "slot-"+Date.now().toString(36)+"-"+(++nextId).toString(36)+"-"+Math.random().toString(36).slice(2,8);
  const types={style:"style1",secondaryStyle:"style2",layout:"layout"};
  const keys=new Set(["style","secondaryStyle","layout","ratio","referenceMedia","skipGlobalRefs"]);
  function validateSlot(slot) {
    if(!slot?.slotId||typeof slot.slotId!=="string")throw err("missing_slot_id");
    if(!Array.isArray(slot.lockedFields))slot.lockedFields=[];
    if(!Array.isArray(slot.userOverrides))slot.userOverrides=[];
    if(!slot.overrides||typeof slot.overrides!=="object"||Array.isArray(slot.overrides))slot.overrides={};
    if(!Array.isArray(slot.referenceMedia))slot.referenceMedia=[];
    if(slot.overrides.ratio!=null&&!Core.validateRatio(slot.overrides.ratio).ok)throw err("invalid_ratio");
    for(const [field,type] of Object.entries({style:"style",secondaryStyle:"style",layout:"layout"})){
      const ref=slot.overrides[field];
      if(ref && (!ref.id||ref.type!==type))throw err("invalid_resource_ref");
    }
    if(!Number.isInteger(slot.order)||slot.order<0)throw err("invalid_slot_order");
    return slot;
  }
  function sync(loop, plan) {
    const ld=loop.data;
    const p=N.normalizePlan(plan);
    p.slots.sort((a,b)=>a.order-b.order);
    p.slots.forEach((slot,i)=>slot.order=i);
    p.slots.forEach(validateSlot);
    ld.studio2Plan=copy(p); // sole writable plan; all below are derived.
    ld.studio2SlotIds=p.slots.map(s=>s.slotId);
    ld.promptListText=p.slots.map(s=>s.subject).filter(Boolean).join("\n");
    ld.batchRows=p.slots.map(s=>({
      slotId:s.slotId,order:s.order,theme:s.subject,
      layout:s.overrides.layout?.id||s.suggestedLayout||"",
      layoutRef:copy(s.overrides.layout||null),
      style1:s.overrides.style?.id||"",
      style2:s.overrides.secondaryStyle?.id||"",
      ratio:s.overrides.ratio||"",
      assetItems:copy(s.referenceMedia||[]),
      skipGlobalRefs:Boolean(s.skipGlobalRefs),
      overrides:copy(s.overrides), lockedFields:copy(s.lockedFields),
      userOverrides:copy(s.userOverrides||[]),
      suggestedLayout:s.suggestedLayout||""
    }));
    ld.planRevision=p.revision;
    return copy(p);
  }
  function read(loop) {
    if(!loop?.data)throw err("missing_loop_node");
    if(loop.data.studio2Plan?.slots) {
      return N.normalizePlan(loop.data.studio2Plan);
    }
    const ld=loop.data;
    const old=Core.normalizeLegacyBatch(loop,{planId:ld.planId||loop.id});
    // Import hidden AI rows even when the currently displayed legacy mode
    // is Fixed. Old UI kept those rows across mode changes: discarding them
    // here would destroy manual layout/reference edits on first migration.
    const savedRows=Array.isArray(ld.batchRows)?ld.batchRows:[];
    const oldAi=ld.batchLayoutMode==="fixed"&&savedRows.length
      ? Core.normalizeLegacyBatch({id:loop.id,data:{...ld,batchLayoutMode:"ai"}},
          {planId:ld.planId||loop.id})
      : null;
    const byId=new Map((oldAi?.slots||[]).map(s=>[s.slotId,s]));
    old.slots.forEach((slot,index)=>{
      const source=oldAi ? (byId.get(slot.slotId)||oldAi.slots[index]) : slot;
      const row=savedRows.find(r=>r?.slotId===slot.slotId)||savedRows[index]||{};
      if(source&&source!==slot) {
        slot.overrides={...copy(source.overrides||{}),...copy(slot.overrides||{})};
        slot.referenceMedia=copy(source.referenceMedia||[]);
        slot.skipGlobalRefs=Boolean(source.skipGlobalRefs);
        slot.lockedFields=copy(source.lockedFields||[]);
      }
      slot.userOverrides=copy(Array.isArray(row.userOverrides)?row.userOverrides:[]);
      slot.lockedFields=copy(Array.isArray(row.lockedFields)
        ? row.lockedFields : slot.lockedFields||[]);
      // A legacy AI recommendation is not a manually locked per-slot
      // layout. Fixed mode inherits global, but stores recommendation for
      // switching back to AI; explicit user overrides stay active.
      if(slot.overrides.layout) {
        slot.suggestedLayout=slot.overrides.layout.id;
        if(ld.batchLayoutMode==="fixed"&&!slot.userOverrides.includes("layout"))
          delete slot.overrides.layout;
      }
      if(Array.isArray(row.assetItems)&&row.assetItems.length &&
          !slot.referenceMedia?.length)slot.referenceMedia=copy(row.assetItems);
      if(row.skipGlobalRefs)slot.skipGlobalRefs=true;
    });
    return sync(loop,old);
  }
  function assertRevision(plan,rev) {
    if(rev!=null && plan.revision!==rev)throw err("plan_revision_conflict");
  }
  function patchSlot(loop,slotId,patch,options={}) {
    const p=read(loop);
    assertRevision(p,options.baseRevision);
    const slot=p.slots.find(s=>s.slotId===slotId);
    if(!slot)throw err("unknown_slot_id");
    const proposed=copy(slot);
    const changes=Object.entries(patch||{});
    for(const [field,value] of changes) {
      if(!["subject","overrides","referenceMedia","skipGlobalRefs","lockedFields"].includes(field))
        throw err("invalid_slot_field");
      if(field==="overrides"){
        if(!value||typeof value!=="object"||Array.isArray(value))throw err("invalid_slot_overrides");
        for(const [k,v] of Object.entries(value)){
          if(!keys.has(k)||k==="referenceMedia"||k==="skipGlobalRefs")throw err("invalid_override_field");
          if(proposed.lockedFields.includes(k)&&!options.unlock)throw err("locked_field");
          if(owns(types,k) && v!=null){
            const id=typeof v==="string"?v:v?.id;
            if(!id)throw err("invalid_resource_ref");
            if(!options.catalog)throw err("resource_authorization_required");
            const checked=Resources.resolveSelection(options.catalog,types[k],id,
              {isUnlocked:options.isUnlocked});
            if(!checked.ok)throw err(checked.code);
            if(typeof v==="object"&&v.version!=null&&v.version!=="current"&&
               String(v.version)!==String(checked.ref.version))throw err("resource_version_conflict");
            proposed.overrides[k]=checked.ref;
          }else if(k==="ratio"){
            if(v!=null&&!Core.validateRatio(v).ok)throw err("invalid_ratio");
            if(v==null)delete proposed.overrides[k];else proposed.overrides[k]=v;
          }else if(v==null)delete proposed.overrides[k];else proposed.overrides[k]=copy(v);
          if(!proposed.userOverrides.includes(k))proposed.userOverrides.push(k);
        }
      }else if(field==="lockedFields"){
        if(!Array.isArray(value)||value.some(k=>k!=="subject"&&!keys.has(k)))
          throw err("invalid_locked_fields");
        proposed.lockedFields=[...new Set(value)];
      }else{
        if(proposed.lockedFields.includes(field)&&!options.unlock)throw err("locked_field");
        if(field==="subject"){
          proposed.subject=String(value??"");
          if(!proposed.userOverrides.includes("subject"))proposed.userOverrides.push("subject");
        }else if(field==="referenceMedia"){
          if(!Array.isArray(value)||value.length>6)throw err("invalid_reference_media");
          proposed.referenceMedia=copy(value);
          if(!proposed.userOverrides.includes(field))proposed.userOverrides.push(field);
        }else if(field==="skipGlobalRefs"){
          proposed.skipGlobalRefs=Boolean(value);
          if(!proposed.userOverrides.includes(field))proposed.userOverrides.push(field);
        }
      }
    }
    validateSlot(proposed);
    p.slots[p.slots.indexOf(slot)]=proposed;
    p.revision++;
    return sync(loop,p);
  }
  function updateText(loop,input,options={}) {
    const p=read(loop);assertRevision(p,options.baseRevision);
    const lines=String(input??"").split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(lines.length>200)throw err("too_many_slots");
    const prev=p.slots;
    // LCS preserves IDs for existing lines shifted by paste/insertion.
    const dp=Array.from({length:prev.length+1},()=>Array(lines.length+1).fill(0));
    for(let i=prev.length-1;i>=0;i--)for(let j=lines.length-1;j>=0;j--)
      dp[i][j]=prev[i].subject===lines[j]?1+dp[i+1][j+1]:
        Math.max(dp[i+1][j],dp[i][j+1]);
    const paired=new Map(),used=new Set();
    for(let i=0,j=0;i<prev.length&&j<lines.length;){
      if(prev[i].subject===lines[j]){paired.set(j,prev[i]);used.add(prev[i].slotId);i++;j++;}
      else if(dp[i+1][j]>=dp[i][j+1])i++;else j++;
    }
    const next=lines.map((subject,i)=>{
      if(paired.has(i))return {...copy(paired.get(i)),order:i};
      const old=prev[i];
      const existing=old&&!used.has(old.slotId)?old:null;
      if(existing)used.add(existing.slotId);
      const s=existing?copy(existing):{
        slotId:newId(),subject:"",order:i,overrides:{},referenceMedia:[],
        lockedFields:[],userOverrides:[],skipGlobalRefs:false
      };
      if(s.lockedFields.includes("subject")&&s.subject!==subject)throw err("locked_field");
      s.order=i;s.subject=subject;
      if(existing&&!s.userOverrides.includes("subject"))s.userOverrides.push("subject");
      return s;
    });
    if(new Set(next.map(s=>s.slotId)).size!==next.length)throw err("duplicate_slot_id");
    p.slots=next;p.revision++;return sync(loop,p);
  }
  function switchMode(loop,mode) {
    if(!["fixed","ai"].includes(mode))throw err("invalid_plan_mode");
    const p=read(loop);
    loop.data.batchLayoutMode=mode;
    return sync(loop,p);
  }
  function move(loop,slotId,to) {
    const p=read(loop),idx=p.slots.findIndex(s=>s.slotId===slotId);
    if(idx<0)throw err("unknown_slot_id");
    if(!Number.isInteger(to)||to<0||to>=p.slots.length)throw err("invalid_slot_order");
    p.slots.splice(to,0,p.slots.splice(idx,1)[0]);
    p.slots.forEach((slot,index)=>{slot.order=index;});
    p.revision++;return sync(loop,p);
  }
  function duplicate(loop,slotId) {
    const p=read(loop),idx=p.slots.findIndex(s=>s.slotId===slotId);
    if(idx<0)throw err("unknown_slot_id");
    const cloned=copy(p.slots[idx]);cloned.slotId=newId();
    cloned.lockedFields=[];p.slots.splice(idx+1,0,cloned);
    p.slots.forEach((slot,index)=>{slot.order=index;});
    p.revision++;return sync(loop,p);
  }
  function remove(loop,slotId) {
    const p=read(loop),idx=p.slots.findIndex(s=>s.slotId===slotId);
    if(idx<0)throw err("unknown_slot_id");
    p.slots.splice(idx,1);p.revision++;return sync(loop,p);
  }
  function add(loop,subject="") {
    const p=read(loop);
    if(p.slots.length>=200)throw err("too_many_slots");
    p.slots.push({slotId:newId(),order:p.slots.length,subject:String(subject),
      overrides:{},lockedFields:[],userOverrides:[],referenceMedia:[],skipGlobalRefs:false});
    p.revision++;return sync(loop,p);
  }
  function mergeAI(loop,items,mode,options={}) {
    const p=read(loop);assertRevision(p,options.baseRevision);
    const prior=p.slots;
    const next=(Array.isArray(items)?items:[]).map((item,i)=>{
      const s=item.slotId?prior.find(x=>x.slotId===item.slotId):prior[i];
      const original=s?copy(s):{slotId:newId(),order:i,subject:"",
        overrides:{},lockedFields:[],userOverrides:[],referenceMedia:[],skipGlobalRefs:false};
      if(!original.lockedFields.includes("subject") &&
         !original.userOverrides.includes("subject"))
        original.subject=String(item.subject??item.theme??original.subject);
      const layout=String(item.layout||"").trim();
      if(layout&&!original.lockedFields.includes("layout") &&
         !original.userOverrides.includes("layout")){
        if(!options.catalog)throw err("resource_authorization_required");
        const check=Resources.resolveSelection(options.catalog,"layout",layout,
          {isUnlocked:options.isUnlocked});
        if(!check.ok)throw err(check.code);
        original.suggestedLayout=layout;
        if(mode==="ai")original.overrides.layout=check.ref;
      }
      original.order=i;
      return original;
    });
    if(new Set(next.map(s=>s.slotId)).size!==next.length)throw err("duplicate_slot_id");
    p.slots=next;p.revision++;
    return sync(loop,p);
  }
  function candidateCount(loop) {
    const n=Number(loop?.data?.studio2CandidateCount||1);
    return Number.isInteger(n)?Math.min(4,Math.max(1,n)):1;
  }
  function setCandidates(loop,count) {
    const n=Number(count);
    if(!Number.isInteger(n)||n<1||n>4)throw err("invalid_candidate_count");
    read(loop);loop.data.studio2CandidateCount=n;
    return n;
  }
  function expand(plan,count=1) {
    const n=Number(count);
    if(!Number.isInteger(n)||n<1||n>4)throw err("invalid_candidate_count");
    const p=N.normalizePlan(plan);
    return p.slots.slice().sort((a,b)=>a.order-b.order).flatMap(s=>
      Array.from({length:n},(_,candidateIndex)=>({
        outputId:s.slotId+":candidate:"+candidateIndex,
        slotId:s.slotId,slotOrder:s.order,candidateIndex,
        outputIndex:s.order*n+candidateIndex,
        subject:s.subject,overrides:copy(s.overrides),
        referenceMedia:copy(s.referenceMedia),
        skipGlobalRefs:Boolean(s.skipGlobalRefs)
      })));
  }
  function freeze(loop,runId="",batchId="") {
    const plan=read(loop);
    return copy({schemaVersion:1,planId:plan.planId,planRevision:plan.revision,
      batchId,runId,mode:loop.data.batchLayoutMode||"fixed",
      slotCount:plan.slots.length,candidateCount:candidateCount(loop),
      outputCount:plan.slots.length*candidateCount(loop),
      outputs:expand(plan,candidateCount(loop))});
  }
  function project(snapshot,run,items=[],authoritativeSlots=[]) {
    if(!snapshot?.outputs||!Array.isArray(snapshot.outputs))throw err("invalid_run_snapshot");
    const raw=Core.selectRunProjection(run,items,{expectedCount:snapshot.outputCount,authoritativeSlots});
    const byIndex=new Map();
    for(const item of items){
      const pos=Number(item?.slotIndex??(Number(item?.position)/1000));
      if(!Number.isInteger(pos)||pos<0||pos>=snapshot.outputCount)continue;
      const previous=byIndex.get(pos);
      // Success with media wins over old failures or duplicate callbacks.
      if(!previous || (item.status==="success"&&item.mediaId&&item.imageUrl) ||
         (previous.status!=="success"&&item.status!=="pending"))
        byIndex.set(pos,item);
    }
    const ordered=snapshot.outputs.map(o=>{
      const item=byIndex.get(o.outputIndex)||null;
      const authoritative=authoritativeSlots.find(slot=>Number(slot?.slotIndex)===o.outputIndex);
      if(authoritative){
        const confirmed=authoritative.viewStatus==="success"&&authoritative.mediaId&&authoritative.imageUrl;
        return {...o,status:confirmed?"success":authoritative.viewStatus,
          imageUrl:confirmed?authoritative.imageUrl:"",
          mediaId:confirmed?authoritative.mediaId:"",
          itemId:authoritative.itemId||"",errorCode:authoritative.errorCode||""};
      }
      return {...o,status:item?.status||"pending",
        imageUrl:item?.status==="success"&&item.mediaId?item.imageUrl||"":"",
        mediaId:item?.status==="success"?item.mediaId||"",
        itemId:item?.id||"",errorCode:item?.errorCode||""};
    });
    return {...raw,runId:run?.id||snapshot.runId,slotCount:snapshot.slotCount,
      outputCount:snapshot.outputCount,outputs:ordered,
      results:ordered.filter(o=>Boolean(o.imageUrl))};
  }
  function validateForExecution(parts,options={}) {
    const errors=[],loop=parts?.loop;
    if(!loop?.data||!parts.skill?.data||!parts.ctrl?.data)
      return {ok:false,errors:[{code:"missing_series_graph"}]};
    if(!options.catalog)errors.push({code:"resource_authorization_required"});
    let plan;
    try{plan=read(loop);}
    catch(e){return {ok:false,errors:[{code:e.code||e.message}]};}
    if(!plan.slots.length)errors.push({code:"empty_plan"});
    const global=Core.normalizeLegacyParts(parts).spec;
    for(const slot of plan.slots){
      if(!String(slot.subject||"").trim()){
        errors.push({slotId:slot.slotId,field:"subject",code:"missing_subject"});
        continue;
      }
      try{
        const effective=Core.resolveEffectiveSpec(
          {...global,subject:slot.subject},
          {...slot,overrides:slot.overrides}
        );
        const check=Core.validateSpec(effective,{catalog:options.catalog});
        for(const e of check.errors)errors.push({...e,slotId:slot.slotId});
        // Resource entitlements are validated against the SAME picker rules.
        for(const [field,key] of Object.entries({style:"style1",
          secondaryStyle:"style2",layout:"layout"})){
          if(field==="secondaryStyle"&&!effective.fusionEnabled)continue;
          if(!effective[field]?.id)continue;
          const r=Resources.resolveSelection(options.catalog,key,effective[field].id,
            {isUnlocked:options.isUnlocked});
          if(!r.ok)errors.push({field,slotId:slot.slotId,code:r.code});
        }
        const media=slot.referenceMedia||[];
        if(!Array.isArray(media))errors.push({slotId:slot.slotId,code:"invalid_reference_media"});
        else for(const mediaRef of media){
          if(!mediaRef||typeof mediaRef!=="object"||
            !String(mediaRef.id||mediaRef.mediaId||mediaRef.image||""))
            errors.push({slotId:slot.slotId,code:"invalid_reference_media"});
        }
      }catch(e){
        errors.push({slotId:slot.slotId,code:e.code||e.message});
      }
    }
    const expected=plan.slots.length*candidateCount(loop);
    if(expected>200)errors.push({code:"too_many_outputs"});
    return {ok:errors.length===0,errors,slotCount:plan.slots.length,
      candidateCount:candidateCount(loop),outputCount:expected,plan};
  }
  return Object.freeze({read,sync,patchSlot,updateText,switchMode,move,duplicate,
    remove,add,mergeAI,candidateCount,setCandidates,expand,freeze,project,
    validateForExecution});
});
