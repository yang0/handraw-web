"use strict";
const assert=require("node:assert/strict");
const Article=require("../demo/assets/studio-article-project-109.js");
const Project=require("../demo/assets/studio-project-sync.js");
const Integration=require("../demo/assets/studio-article-integration.js");
const clone=x=>JSON.parse(JSON.stringify(x));

async function main() {
  const art={id:"article-109",articleTitle:"茶与山",title:"茶与山",
    markdown:"# 茶与山\n\n龙井茶园。\n\n## 云间茶事\n\n溪流。",
    documentRevision:7,planRevision:3,planId:"article-plan-109",
    style1:"FA-001",layout:"SC-021",coverRatio:"2.35:1",inlineRatio:"4:3",
    cards:[{id:"slot-cover",slotId:"slot-cover",role:"cover",
      anchorId:"anchor-cover",afterBlockIdx:-1,subject:"茶园封面",
      ratio:"2.35:1",purpose:"引出整篇文章",status:"done",
      imageUrl:"/generated/cover109.webp",runId:"run-109"},
      {id:"slot-inline",role:"inline",anchorId:"anchor-para-4",
       afterBlockIdx:3,anchorText:"云间茶事",subject:"茶山石阶",
       layoutId:"SC-021",styleId:"FA-001",ratio:"4:3",
       prompt:"原创茶山插图",status:"failed",requestId:"request-109"}],
    editRevision:1};
  const before=clone(art);
  const snapshot=Article.snapshot(art);
  assert.deepEqual(art,before,"Adapter never rewrites the editor's canonical Markdown");
  assert.equal(snapshot.authority,"article");
  assert.equal(snapshot.draft.article.documentId,"article-109");
  assert.equal(snapshot.draft.article.revision,7);
  assert.equal(snapshot.draft.article.markdown,art.markdown);
  assert.equal(snapshot.draft.plan.kind,"article");
  assert.equal(snapshot.draft.plan.documentRevision,7);
  assert.deepEqual(snapshot.draft.plan.slots.map(s=>s.anchorId),
    snapshot.draft.article.anchors.map(a=>a.anchorId));
  assert.deepEqual(snapshot.draft.plan.slots.map(s=>s.slotId),
    ["slot-cover","slot-inline"]);
  assert.equal(snapshot.draft.plan.slots[0].runId,"run-109");
  assert.equal(snapshot.draft.plan.slots[1].requestId,"request-109");
  assert.ok(!("graph" in snapshot.draft),"GraphPatch cannot own article Markdown");
  assert.equal(snapshot.draft.creationSpec.outputMode,"article-illust");
  const hydrated=Article.hydrate({id:"prj-109",kind:"article",authority:"article",
    title:"茶与山",revision:12,draft:snapshot.draft});
  assert.equal(hydrated.markdown,art.markdown);
  assert.equal(hydrated.projectRevision,12);
  assert.equal(hydrated.cards[1].afterBlockIdx,3);
  assert.equal(hydrated.cards[1].anchorId,"anchor-para-4");
  assert.equal(hydrated.cards[0].imageUrl,"/generated/cover109.webp");
  assert.equal(hydrated.cards[1].status,"failed");
  assert.equal(hydrated.cards[0].runId,"run-109");
  assert.deepEqual(Article.snapshot(hydrated).draft.article,snapshot.draft.article);
  assert.ok(!Article.articleChanged(before,clone(before)));
  assert.ok(Article.articleChanged(before,{...before,markdown:"新正文"}));
  assert.ok(Article.planChanged(before,{...before,cards:[...before.cards,{id:"new"}]}));
  assert.throws(()=>Article.snapshot({...art,cards:[art.cards[0],art.cards[0]]}),
    /article_slot_id_duplicate/);
  assert.throws(()=>Article.hydrate({id:"x",kind:"article",authority:"article",
    draft:{...snapshot.draft,plan:{...snapshot.draft.plan,documentRevision:6}}}),
    /article_revision_mismatch/);

  const calls=[];
  const api=Project.createClient({idFactory:(prefix)=>{
    const n=calls.filter(x=>x.kind==="id").length+1;
    calls.push({kind:"id",prefix});
    return prefix+"-109-"+n;
  },fetchImpl:async(path,opt)=>{
    const body=JSON.parse(opt.body);
    calls.push({path,body,method:opt.method});
    return {ok:true,status:200,json:async()=>({ok:true,
      projectId:body.projectId||tab.projectId,
      revision:opt.method==="POST"?1:2})};
  }});
  const tab={editRevision:1};
  let ack=await api.flush(tab,snapshot);
  assert.equal(ack.ok,true);
  assert.equal(tab.projectSaveState,"synced");
  const created=calls.find(x=>x.method==="POST");
  assert.equal(created.body.authority,"article");
  assert.equal(created.body.draft.article.markdown,art.markdown);
  tab.editRevision++;
  ack=await api.flush(tab,Article.snapshot({...art,markdown:"# 茶与山\n新稿"}));
  assert.equal(ack.ok,true);
  const patch=calls.find(x=>x.method==="PATCH");
  assert.equal(patch.body.baseRevision,1);
  assert.deepEqual(patch.body.patch.map(p=>p.path),
    ["/article","/plan","/creationSpec","/activeView","/editorLayout","/title"]);
  assert.ok(!patch.body.patch.some(p=>p.path.startsWith("/graph")));
  assert.equal(patch.body.patch[0].value.markdown,"# 茶与山\n新稿");

  let network=true;
  const uncertainCalls=[];
  const uncertain=Project.createClient({idFactory:p=>p+"-109-frozen",
    fetchImpl:async(path,opt)=>{
      const body=JSON.parse(opt.body);uncertainCalls.push(body);
      if(network)throw new Error("response lost");
      return {ok:true,status:200,json:async()=>({
        ok:true,projectId:body.projectId,revision:1})};
    }});
  const offline={editRevision:1};
  await uncertain.flush(offline,snapshot);
  const frozen=JSON.stringify(offline.projectPending);
  assert.equal(offline.projectSaveState,"error");
  offline.editRevision++;
  network=false;
  await uncertain.flush(offline,Article.snapshot({...art,markdown:"# 新内容"}));
  assert.equal(JSON.stringify(uncertainCalls[0]),JSON.stringify(uncertainCalls[1]),
    "Lost response replays the same POST/idempotencyKey");
  assert.equal(offline.projectSaveState,"local_only");
  assert.equal(offline.projectPending,null);
  assert.ok(frozen.includes("idempotencyKey"));

  let errors=0;
  const conflict=Project.createClient({fetchImpl:async()=>{
    errors++;return {ok:false,status:409,json:async()=>({
      ok:false,code:"project_revision_conflict",currentRevision:14})};
  }});
  const other={projectId:"prj-109",projectRevision:12,
    projectAuthority:"article",editRevision:2};
  const failed=await conflict.flush(other,snapshot);
  assert.equal(failed.conflict,true);
  assert.equal(other.projectSaveState,"conflict");
  await conflict.flush(other,snapshot);
  assert.equal(errors,1,"sticky conflict cannot blindly overwrite the remote");
  assert.equal(other.projectPending.payload.patch[0].path,"/article");

  const graph={nodes:[{id:"ap",type:"article_plan",data:{documentId:art.id}}],edges:[]};
  const projection=Integration.linkArticleGraph(graph,
    snapshot.draft.article,snapshot.draft.plan,{nodeId:"ap"});
  assert.ok(!JSON.stringify(projection).includes(art.markdown),
    "Graph only stores article PlanSlot refs, never full Markdown");
  console.log("Studio #109 ArticleDocument/PlanSlot/CAS/outbox/replay/Graph isolation PASS");
}
main().catch(e=>{console.error(e);process.exitCode=1});
