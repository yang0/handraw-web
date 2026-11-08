/* #120 Studio DAG scheduler: immutable graph, typed edges, shared slot permits.
 * No billing or Run/Item persistence here; #119 and the server own those facts.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HandrawStudioDAG120 = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";
  const OUTPUT = Object.freeze({
    skill_params:"style", text_input:"text", asset:"image", fission:"text",
    loop:"sequence", bridge:"sequence", output_control:"image",
    output_display:"image", article_plan:"document"
  });
  const INPUTS = Object.freeze({
    fission:["style","text"],
    loop:["style","text","image","sequence","document"],
    bridge:["style","text","image","sequence","document"],
    output_control:["style","text","image","sequence","document"],
    output_display:["image","document"],
    article_plan:["image"]
  });
  const RETRYABLE = new Set([429, 500, 502, 503, 504]);
  const clone = x => JSON.parse(JSON.stringify(x));
  function freezeDeep(x) {
    if (!x || typeof x !== "object" || Object.isFrozen(x)) return x;
    for (const v of Object.values(x)) freezeDeep(v);
    return Object.freeze(x);
  }
  function issue(code, id, reason) {
    const e = new Error(reason || code);
    e.code = code;
    e.nodeId = id || "";
    return e;
  }
  function loopConfigured(n) {
    const d=n.data||{};
    return !!(d.studio2Plan?.slots?.length ||
      (d.batchRows||[]).length || (d.styleIds||[]).length ||
      (d.layoutIds||[]).length || (d.assetIds||[]).length ||
      String(d.promptListText||"").trim() ||
      (Number(d.batchCount)>0 && String(d.batchSeed||"").trim()));
  }
  function compile(graph, {targets=null, revision=0, references={}}={}) {
    if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges))
      throw issue("invalid_graph","","Graph nodes/edges required");
    if (graph.nodes.length>1500 || graph.edges.length>6000)
      throw issue("graph_too_large","","Graph exceeds execution limits");
    const graphCopy=clone(graph);
    // Never drag historical RunSnapshot or transient network state into this Run.
    for (const n of graphCopy.nodes) {
      if (n?.data) {
        delete n.data.studio2RunSnapshot;
        delete n.data.projectPromise;
        delete n.data.pendingTaskId;
      }
    }
    const byId=new Map(),incoming=new Map(),outgoing=new Map(),indegree=new Map();
    for (const n of graphCopy.nodes) {
      if (!n || typeof n.id!=="string" || !n.id || byId.has(n.id) || !OUTPUT[n.type])
        throw issue("invalid_node",n?.id,"Unknown/duplicate DAG node");
      byId.set(n.id,n); incoming.set(n.id,[]);outgoing.set(n.id,[]);indegree.set(n.id,0);
    }
    for (const e of graphCopy.edges) {
      const src=byId.get(e?.from),dst=byId.get(e?.to);
      if (!src||!dst) throw issue("dangling_edge",e?.to||e?.from,"Edge endpoint missing");
      if (src.id===dst.id) throw issue("implicit_cycle",src.id,"Self-loop prohibited");
      const declaredOut=e.fromPort||e.sourcePort||e.outputPort||"";
      const declaredIn=e.toPort||e.targetPort||e.inputPort||"";
      const inferred=OUTPUT[src.type];
      if (declaredOut && !["out","output",inferred].includes(declaredOut))
        throw issue("typed_port_mismatch",src.id,"Source port type mismatch");
      if (declaredIn && !["in","input",inferred].includes(declaredIn))
        throw issue("typed_port_mismatch",dst.id,"Target port type mismatch");
      if (!(INPUTS[dst.type]||[]).includes(inferred))
        throw issue("typed_port_mismatch",dst.id,"Incompatible "+src.type+" → "+dst.type);
      incoming.get(dst.id).push(src.id);
      outgoing.get(src.id).push(dst.id);
      indegree.set(dst.id,indegree.get(dst.id)+1);
    }
    for (const n of graphCopy.nodes) {
      if (n.type==="output_control" && !incoming.get(n.id).length)
        throw issue("missing_required_input",n.id,"生成设置缺少输入");
      if (n.type==="loop" && !incoming.get(n.id).length && !loopConfigured(n))
        throw issue("missing_required_input",n.id,"批量节点缺少输入或显式 Loop/Series 方案");
    }
    const queue=graphCopy.nodes.filter(n=>indegree.get(n.id)===0).map(n=>n.id);
    const order=[];
    for (let p=0;p<queue.length;p++) {
      const id=queue[p];order.push(id);
      for (const dst of outgoing.get(id)) {
        indegree.set(dst,indegree.get(dst)-1);
        if (indegree.get(dst)===0) queue.push(dst);
      }
    }
    if (order.length!==byId.size)
      throw issue("implicit_cycle","", "Graph contains an implicit cycle");
    const allControls=order.filter(id=>byId.get(id).type==="output_control");
    const chosen=targets==null?allControls:[...new Set(targets)];
    if (!chosen.length) throw issue("no_output_control","","No output control selected");
    for (const id of chosen)
      if (!byId.has(id)||byId.get(id).type!=="output_control")
        throw issue("invalid_target",id,"Unknown output control");
    const dependencies={};
    function upstreamControlIds(id) {
      const seen=new Set(),controls=new Set(),pending=[...incoming.get(id)];
      while(pending.length) {
        const p=pending.pop();
        if(seen.has(p))continue;
        seen.add(p);
        if(byId.get(p).type==="output_control") controls.add(p);
        for(const ancestor of incoming.get(p))pending.push(ancestor);
      }
      return [...controls].filter(x=>chosen.includes(x));
    }
    for(const id of chosen)dependencies[id]=upstreamControlIds(id);
    const nodeNames={};
    for (const n of graphCopy.nodes)
      nodeNames[n.id]=String(n.data?.title||n.data?.label||n.title||n.id).slice(0,120);
    const frozen=freezeDeep({
      graph:graphCopy, revision:Number(revision)||0,
      references:clone(references||{}), dependencies,nodeNames,
      controls:chosen, order
    });
    return frozen;
  }

  function makeSharedPool({globalLimit=3,userLimit=3,gatewayLimit=3,modelLimit=3}={}) {
    const limits={global:Math.max(1,Number(globalLimit)||3),
      user:Math.max(1,Number(userLimit)||3),gateway:Math.max(1,Number(gatewayLimit)||3),
      model:Math.max(1,Number(modelLimit)||3)};
    const counts={global:0,user:new Map(),gateway:new Map(),model:new Map()};
    const queue=[];
    function current(kind,key){return counts[kind].get(key)||0;}
    function available(meta){
      return counts.global<limits.global &&
        current("user",meta.user)<limits.user &&
        current("gateway",meta.gateway)<limits.gateway &&
        current("model",meta.model)<limits.model;
    }
    function change(meta,delta){
      counts.global+=delta;
      for(const key of ["user","gateway","model"]){
        const n=current(key,meta[key])+delta;
        if(n<=0)counts[key].delete(meta[key]);else counts[key].set(meta[key],n);
      }
    }
    function drain(){
      for(let i=0;i<queue.length;) {
        const w=queue[i];
        if(w.signal?.aborted){queue.splice(i,1);w.cancel();continue;}
        if(!available(w.meta)){i++;continue;}
        queue.splice(i,1);change(w.meta,1);w.grant();
      }
    }
    function acquire({signal,user="current",gateway="default",model="default"}={}){
      const meta={user:String(user),gateway:String(gateway),model:String(model)};
      if(signal?.aborted)return Promise.reject(issue("cancelled","","Cancelled before submission"));
      return new Promise((resolve,reject)=>{
        let granted=false,settled=false;
        const off=()=>signal?.removeEventListener?.("abort",onAbort);
        const cancel=()=>{
          if(settled)return;
          settled=true;off();reject(issue("cancelled","","Cancelled while waiting for capacity"));
        };
        const onAbort=()=>{
          if(granted)return;const at=queue.indexOf(waiter);
          if(at>=0)queue.splice(at,1);cancel();drain();
        };
        const waiter={meta,signal,cancel,grant(){
          if(settled){change(meta,-1);drain();return;}
          granted=true;settled=true;off();
          let released=false;
          resolve(()=>{
            if(released)return;released=true;change(meta,-1);drain();
          });
        }};
        signal?.addEventListener?.("abort",onAbort,{once:true});
        queue.push(waiter);drain();
      });
    }
    async function withPermit(fn,opts={}){
      const release=await acquire(opts);
      try{
        if(opts.signal?.aborted)throw issue("cancelled","","Cancelled before submission");
        return await fn();
      }finally{release();}
    }
    return {acquire,withPermit,
      snapshot:()=>({running:counts.global,waiting:queue.length,limit:limits.global,
        user:[...counts.user],gateway:[...counts.gateway],model:[...counts.model]})};
  }
  const defaultPool=makeSharedPool();
  function makeBreaker({threshold=3,cooldownMs=12000,clock=()=>Date.now()}={}){
    const counters=new Map();
    function state(key) {
      const row=counters.get(key)||{failures:0,openUntil:0};
      return {...row,open:row.openUntil>clock()};
    }
    return {
      state,
      check(key){
        const row=state(key);
        if(row.open)throw issue("circuit_open","", "Gateway breaker open: "+key);
      },
      success(key){counters.delete(key);},
      fail(key){
        const row=state(key);row.failures++;
        if(row.failures>=threshold){row.openUntil=clock()+cooldownMs;row.failures=0;}
        counters.set(key,row);
      }
    };
  }
  const defaultBreaker=makeBreaker();
  function aborted(signal){if(signal?.aborted)throw issue("cancelled","","Cancelled");}
  function delay(ms,signal){
    if(ms<=0){aborted(signal);return Promise.resolve();}
    return new Promise((resolve,reject)=>{
      if(signal?.aborted){reject(issue("cancelled","","Cancelled"));return;}
      const t=setTimeout(()=>{signal?.removeEventListener?.("abort",onAbort);resolve();},ms);
      const onAbort=()=>{clearTimeout(t);reject(issue("cancelled","","Cancelled during backoff"));};
      signal?.addEventListener?.("abort",onAbort,{once:true});
    });
  }
  async function retryTransient(work,{signal,requestId="",maxAttempts=3,
    baseMs=250,maxMs=3000,jitter=0,breaker=defaultBreaker,
    key="default",sleep=delay,random=Math.random,onRetry=()=>{}}={}){
    const attempts=Math.max(1,Math.min(6,Math.round(maxAttempts)||3));
    for(let attempt=1;attempt<=attempts;attempt++){
      aborted(signal);breaker?.check(key);
      try{
        const result=await work({attempt,requestId,signal});
        breaker?.success(key);
        return result;
      }catch(err){
        if(signal?.aborted || err?.code==="cancelled")throw err;
        const status=Number(err?.status||err?.httpStatus||0);
        const transient=RETRYABLE.has(status) || (err?.transient===true);
        if(!transient)throw err;
        breaker?.fail(key);
        if(attempt>=attempts)throw err;
        const time=Math.min(maxMs,baseMs*Math.pow(2,attempt-1));
        const wait=Math.max(0,time+(jitter?Math.round(time*jitter*(random()*2-1)):0));
        onRetry({attempt,status,requestId,wait,key});
        await sleep(wait,signal);
      }
    }
  }

  async function run(compiled,execute,{signal=null,policy="continue",
    pool=defaultPool,onUpdate=()=>{}}={}){
    if(!compiled?.controls||typeof execute!=="function")
      throw issue("invalid_execution","","Missing frozen graph or executor");
    if(!["continue","fail-fast"].includes(policy))throw issue("invalid_failure_policy");
    const states={};
    const entries=new Set(compiled.controls);
    for(const id of compiled.controls) {
      for(const dep of compiled.dependencies[id]||[])
        if(!entries.has(dep))throw issue("target_missing_dependency",id,"Target excludes predecessor "+dep);
      states[id]={id,name:compiled.nodeNames[id],status:"waiting",
        blockedBy:[...(compiled.dependencies[id]||[])],total:0,succeeded:0,failed:0};
    }
    const active=new Map();
    let stopped=Boolean(signal?.aborted),hardFail=false;
    const stop=()=>{stopped=true;notify();};
    signal?.addEventListener?.("abort",stop,{once:true});
    function view(){
      const list=compiled.controls.map(id=>states[id]);
      const count=x=>list.filter(s=>s.status===x).length;
      const out={revision:compiled.revision,total:list.length,
        succeeded:count("success"),failed:count("failed"),
        cancelled:count("cancelled"),blocked:count("blocked"),
        running:count("running"),waiting:count("waiting"),
        slots:{total:0,succeeded:0,failed:0},
        nodes:list.map(x=>({...x,blockedBy:[...x.blockedBy]})),pool:pool.snapshot()};
      for(const s of list){out.slots.total+=s.total;out.slots.succeeded+=s.succeeded;out.slots.failed+=s.failed;}
      return out;
    }
    function notify(){try{onUpdate(view());}catch(_){/* UI observer cannot mutate Run */}}
    function report(id,slot){
      const s=states[id];if(!s)return;
      s.total=Math.max(s.total,Number(slot?.total)||0);
      s.succeeded=Math.max(s.succeeded,Number(slot?.succeeded)||0);
      s.failed=Math.max(s.failed,Number(slot?.failed)||0);
      notify();
    }
    function settleUnreachable(){
      let changed=false;
      for(const id of compiled.controls){
        const s=states[id];if(s.status!=="waiting")continue;
        const parents=compiled.dependencies[id]||[];
        if(stopped||hardFail){s.status="cancelled";s.blockedBy=parents.filter(p=>states[p].status!=="success");changed=true;}
        else if(parents.some(p=>["failed","blocked","cancelled"].includes(states[p].status))){
          s.status="blocked";s.blockedBy=parents.filter(p=>states[p].status!=="success");changed=true;
        }else s.blockedBy=parents.filter(p=>states[p].status!=="success");
      }
      if(changed)notify();
    }
    async function launch(id){
      const s=states[id];s.status="running";s.blockedBy=[];notify();
      try{
        const ok=await execute({
          id,node:compiled.graph.nodes.find(n=>n.id===id),
          graph:compiled.graph,revision:compiled.revision,
          references:compiled.references,signal,pool,
          report:detail=>report(id,detail)
        });
        s.status=signal?.aborted||stopped?"cancelled":ok===false?"failed":"success";
        if(s.status==="failed" && policy==="fail-fast")hardFail=true;
      }catch(e){
        s.status=e?.code==="cancelled"||signal?.aborted?"cancelled":"failed";
        s.error=String(e?.message||e);
        if(s.status==="failed" && policy==="fail-fast")hardFail=true;
      }finally{active.delete(id);notify();}
    }
    try{
      notify();
      while(true){
        settleUnreachable();
        if(!stopped&&!hardFail){
          for(const id of compiled.controls){
            if(states[id].status!=="waiting")continue;
            if((compiled.dependencies[id]||[]).every(p=>states[p].status==="success")){
              const p=launch(id);active.set(id,p);
            }
          }
        }
        if(!active.size){
          settleUnreachable();
          if(compiled.controls.every(id=>states[id].status!=="waiting"))break;
          // Empty ready set must never deadlock on an unsatisfied ancestor.
          for(const id of compiled.controls)
            if(states[id].status==="waiting"){states[id].status="blocked";states[id].blockedBy=compiled.dependencies[id]||[];}
          notify();break;
        }
        await Promise.race([...active.values()]);
      }
    }finally{signal?.removeEventListener?.("abort",stop);}
    return view();
  }
  return {compile,makeSharedPool,makeBreaker,retryTransient,run,defaultPool,
    defaultBreaker,issue,OUTPUT,INPUTS};
});
