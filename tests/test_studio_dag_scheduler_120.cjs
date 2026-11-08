"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const DAG=require("../demo/assets/studio-dag-scheduler-120.js");
const tick=ms=>new Promise(r=>setTimeout(r,ms));
const node=(id,type,data={})=>({id,type,data});
const edge=(from,to)=>({from,to});
function basic(prefix="x") {
  return {nodes:[node(prefix+"s","skill_params"),node(prefix+"t","text_input"),
    node(prefix+"c","output_control")],
    edges:[edge(prefix+"s",prefix+"c"),edge(prefix+"t",prefix+"c")]};
}
function threeControls(){
  return {nodes:[
    node("s","skill_params"),node("a","output_control",{title:"主图"}),
    node("d","output_display"),node("b","output_control",{title:"引用上游结果"}),
    node("x","text_input"),node("z","output_control",{title:"独立分支"})
  ],edges:[edge("s","a"),edge("a","d"),edge("d","b"),edge("x","z")]};
}
async function suite(){
  const before=basic();
  const frozen=DAG.compile(before,{revision:42,references:{projectId:"original",media:[{id:"a"}]}});
  before.nodes[0].data.theme="editor changed";
  before.edges.length=0;
  assert.equal(frozen.revision,42);
  assert.equal(frozen.graph.nodes[0].data.theme,undefined);
  assert.equal(frozen.graph.edges.length,2);
  assert.equal(frozen.references.media[0].id,"a");
  assert.ok(Object.isFrozen(frozen.graph.nodes[0]));
  assert.throws(()=>DAG.compile({nodes:[node("a","output_control")],edges:[]}),
    e=>e.code==="missing_required_input");
  assert.throws(()=>DAG.compile({nodes:[node("l","loop")],edges:[]}),
    e=>e.code==="missing_required_input");
  assert.doesNotThrow(()=>DAG.compile({nodes:[
    node("l","loop",{promptListText:"first\nsecond"}),
    node("c","output_control")],edges:[edge("l","c")]}));
  assert.throws(()=>DAG.compile({nodes:[node("s","skill_params"),
    node("t","text_input"),node("c","output_control")],
    edges:[edge("s","c"),edge("c","t")]}),
    e=>e.code==="typed_port_mismatch");
  assert.throws(()=>DAG.compile({nodes:[
    node("c","output_control"),node("d","output_display")],
    edges:[edge("c","d"),edge("d","c")]}),
    e=>e.code==="implicit_cycle");
  assert.throws(()=>DAG.compile({nodes:[
    node("s","skill_params"),node("c","output_control")],
    edges:[{from:"s",to:"c",fromPort:"image"}]}),
    e=>e.code==="typed_port_mismatch");
  assert.throws(()=>DAG.compile({nodes:[node("s","text_input"),
    node("c","output_control")],edges:[edge("s","missing")]}),
    e=>e.code==="dangling_edge");

  const graph=threeControls(),plan=DAG.compile(graph,{revision:8});
  assert.deepEqual(plan.dependencies.a,[]);
  assert.deepEqual(plan.dependencies.z,[]);
  assert.deepEqual(plan.dependencies.b,["a"]);
  const partial=DAG.compile(graph,{targets:["b"]});
  await assert.rejects(DAG.run(partial,async()=>true),
    e=>e.code==="target_missing_dependency",
    "A partial run may not bypass an unselected upstream Control");
  assert.deepEqual(new Set(plan.controls),new Set(["a","b","z"]));
  assert.ok(plan.order.indexOf("a") < plan.order.indexOf("b"));
  const pool=DAG.makeSharedPool({globalLimit:2,userLimit:2,gatewayLimit:2,modelLimit:1});
  const events=[],updates=[];
  let active=0,max=0;
  const result=await DAG.run(plan,async ({id,pool,report})=>{
    events.push("start:"+id);
    const meta={user:"alice",gateway:"gw",model:id==="z"?"modelB":"modelA"};
    const jobs=Array.from({length:id==="a"?2:1},(_,i)=>pool.withPermit(async()=>{
      active++;max=Math.max(max,active);
      await tick(3);events.push("finish-slot:"+id+":"+i);active--;
    },meta));
    await Promise.all(jobs);
    report({total:jobs.length,succeeded:jobs.length});
    events.push("done:"+id);
    return true;
  },{pool,onUpdate:x=>updates.push(x)});
  assert.equal(max,2);
  assert.deepEqual([result.total,result.succeeded,result.failed,result.blocked],[3,3,0,0]);
  assert.ok(events.indexOf("start:a")<events.indexOf("start:b"));
  assert.ok(events.indexOf("start:z")<events.indexOf("done:a"),"Independent branch starts concurrently");
  assert.ok(events.indexOf("start:b")>events.indexOf("done:a"),"Consumer must wait for upstream success");
  assert.ok(updates.some(u=>u.nodes.find(n=>n.id==="b").blockedBy.includes("a")),"Wait reason names predecessor");
  assert.equal(result.slots.total,4);

  // Continue independent branch, fail downstream. Fail-fast cancels pending.
  const failed=await DAG.run(plan,async ({id})=>id!=="a",{policy:"continue"});
  assert.equal(failed.failed,1);
  assert.equal(failed.blocked,1);
  assert.equal(failed.succeeded,1);
  assert.deepEqual(failed.nodes.find(n=>n.id==="b").blockedBy,["a"]);
  const failFast=await DAG.run(plan,async ({id})=>id!=="a",{policy:"fail-fast"});
  assert.equal(failFast.failed,1);
  assert.equal(failFast.nodes.find(n=>n.id==="b").status,"cancelled");

  // Global limit shared by independent Control branches AND each Control's slots.
  for(const slots of [5,20,100]){
    const nodes=[node("input","skill_params")];
    const edges=[];
    for(let c=0;c<5;c++){nodes.push(node("control"+c,"output_control"));edges.push(edge("input","control"+c));}
    const many=DAG.compile({nodes,edges},{revision:slots});
    const shared=DAG.makeSharedPool({globalLimit:3,userLimit:3,gatewayLimit:3,modelLimit:3});
    let simultaneous=0,peak=0,finished=0,issued=0;
    const workers=Array.from({length:5},(_,i)=>Math.floor(slots/5)+(i<slots%5?1:0));
    const out=await DAG.run(many,async ({id,pool,report})=>{
      const total=workers[Number(id.replace("control",""))];
      let next=0,success=0;
      const threads=Array.from({length:Math.min(4,total)},async()=>{
        while(next<total){
          const n=next++;
          await pool.withPermit(async()=>{
            simultaneous++;issued++;peak=Math.max(peak,simultaneous);
            await tick(1);finished++;success++;simultaneous--;
          },{user:"alice",gateway:"proxy",model:"gpt-image",signal:null});
          report({total,succeeded:success});
        }
      });
      await Promise.all(threads);
      return true;
    },{pool:shared});
    assert.equal(issued,slots);
    assert.equal(finished,slots);
    assert.equal(out.slots.succeeded,slots);
    assert.ok(peak<=3,"Global shared pool exceeded under "+slots+" slots: "+peak);
    assert.equal(shared.snapshot().running,0);
    assert.equal(shared.snapshot().waiting,0);
  }

  // Cancel aborts all waiting slots before admission. Already admitted work
  // may settle, but MUST NOT authorize another queued POST.
  const controller=new AbortController(),cancelPool=DAG.makeSharedPool({globalLimit:2});
  let issued=0;
  const cancellation=DAG.run(DAG.compile({
    nodes:[node("i","text_input"),node("a","output_control"),node("b","output_control")],
    edges:[edge("i","a"),edge("i","b")]}),
    async ({pool,signal})=>{
      const work=Array.from({length:50},async()=>{
        try{
          await pool.withPermit(async()=>{
            if(signal.aborted)return;
            issued++;await tick(15);
          },{signal,user:"alice"});
        }catch(e){assert.equal(e.code,"cancelled");}
      });
      await Promise.all(work);
      return !signal.aborted;
    },{signal:controller.signal,pool:cancelPool});
  await tick(2);controller.abort();
  const cancelled=await cancellation;
  assert.ok(issued<=2,"No pending slot sent after abort: "+issued);
  assert.equal(cancelled.cancelled,2);
  assert.equal(cancelPool.snapshot().waiting,0);

  // Stable idempotency key on all HTTP retries: do not create double billing.
  const retryLog=[],waits=[];
  let charged=0;const chargedKeys=new Set();
  const breaker=DAG.makeBreaker({threshold:5});
  const value=await DAG.retryTransient(async ({attempt,requestId})=>{
    retryLog.push({attempt,requestId});
    if(attempt===1)throw Object.assign(new Error("limit"),{status:429});
    if(attempt===2)throw Object.assign(new Error("gateway"),{status:502});
    if(!chargedKeys.has(requestId)){chargedKeys.add(requestId);charged++;}
    return "success";
  },{requestId:"run120-slot0",breaker,key:"gw:model",
    baseMs:100,maxAttempts:3,jitter:0,sleep:async ms=>waits.push(ms)});
  assert.equal(value,"success");
  assert.deepEqual(retryLog.map(x=>x.requestId),["run120-slot0","run120-slot0","run120-slot0"]);
  assert.deepEqual(waits,[100,200]);
  assert.equal(charged,1);
  let now=1000;
  const br=DAG.makeBreaker({threshold:2,cooldownMs:5000,clock:()=>now});
  br.fail("same");br.fail("same");
  assert.throws(()=>br.check("same"),e=>e.code==="circuit_open");
  await assert.rejects(DAG.retryTransient(async()=>{throw Object.assign(new Error("503"),{status:503})},
    {breaker:br,key:"same",maxAttempts:3,sleep:async()=>{}}),e=>e.code==="circuit_open");
  now=6001;assert.doesNotThrow(()=>br.check("same"));
  br.success("same");
  assert.equal(br.state("same").open,false);
  // Ambiguous timeout is retryable only with the exact same billed identity.
  const timeoutIds=[];
  const timeoutResult=await DAG.retryTransient(async ({attempt,requestId})=>{
    timeoutIds.push(requestId);
    if(attempt===1)throw Object.assign(new Error("timeout"),{
      name:"TimeoutError",code:"ETIMEDOUT"});
    return "recovered";
  },{requestId:"run120-timeout",maxAttempts:2,baseMs:1,sleep:async()=>{}});
  assert.equal(timeoutResult,"recovered");
  assert.deepEqual(timeoutIds,["run120-timeout","run120-timeout"]);
  // No retry for client validation / authentication / exhausted credit errors.
  let nonRetry=0;
  await assert.rejects(DAG.retryTransient(async()=>{nonRetry++;throw Object.assign(new Error("bad"),{status:400})},
    {sleep:async()=>{}}),e=>e.status===400);
  assert.equal(nonRetry,1);

  // Real-app and HTML wiring are part of the regression.
  const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
  const page=fs.readFileSync("demo/studio.html","utf8");
  const workflow=fs.readFileSync(".github/workflows/checks.yml","utf8");
  assert.ok(page.includes("studio-dag-scheduler-120.js"));
  assert.ok(page.indexOf("studio-dag-scheduler-120.js")<page.indexOf("studio-app.js"));
  assert.ok(app.includes("runDAGOutputControls"));
  assert.ok(app.includes("slotPool.withPermit"));
  assert.ok(app.includes("executionGraphOverride"));
  assert.ok(app.includes("data?.items||[]"));
  assert.ok(app.includes("runtimeSignal"));
  assert.ok(app.includes("idempotencyKey: requestId"));
  assert.ok(workflow.includes("test_studio_dag_scheduler_120.cjs"));
  console.log("Studio #120 typed DAG, graph snapshots, branch dependencies, "+
    "5/20/100 shared capacity, cancel, retry/breaker and CI contract PASS");
}
suite().catch(e=>{console.error(e);process.exitCode=1;});
