"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const PC = require("../demo/assets/studio-project-center.js");
const Article109 = require("../demo/assets/studio-article-project-109.js");
const source = fs.readFileSync("demo/assets/studio-app.js","utf8");
const css = fs.readFileSync("demo/assets/studio-canvas.css","utf8");
const html = fs.readFileSync("demo/studio.html","utf8");
assert.ok(html.includes("studio-project-center.js"), "Page loads the Project Center module");
assert.ok(!source.includes('id="studio-mode-projects"'),
  "The retired Project Center must not be visible in the Studio navigation");
assert.ok(source.includes('viewParam === "projects"') && source.includes('cleaned.searchParams.delete("view")'),
  "Legacy ?view=projects bookmarks must redirect to the image form");
assert.ok(source.includes('params.get("project")'), "?project= project deep link is supported");
assert.ok(css.includes(".ic-projects-stage"), "Project Center is styled in shared shell");
assert.ok(css.includes("@media(max-width:620px)"), "Mobile layout has a responsive grid");

const projects=[{id:"prj-01",title:'<img src=x onerror=alert(1)> "evil"',kind:"image",
  authority:"graph",revision:4,updatedAt:"2026-11-08T12:00:00Z"}];
const tabs=[{id:"tab-1",projectId:"prj-01",title:"离线草稿",blueprint:"single",
  projectSaveState:"conflict",projectPending:{idempotencyKey:"existing"}}];
let mark=PC.render({projects,tabs,loggedIn:true});
assert.match(mark,/创作项目/);
assert.match(mark,/本机待同步草稿/);
assert.match(mark,/云端项目/);
assert.match(mark,/data-pc-local='tab-1'/);
assert.match(mark,/data-pc-open='prj-01'/);
assert.ok(mark.includes("&lt;img src=x onerror=alert(1)&gt;"),
  "Cloud metadata must be escaped");
assert.ok(!mark.includes('<img src=x'),"HTML injection never interpreted");
assert.equal(PC.classifyRestore(tabs[0],projects[0]),"keep-local");
assert.equal(PC.classifyRestore(null,projects[0]),"open-cloud");
assert.equal(PC.classifyRestore({projectRevision:4,projectSaveState:"synced"},projects[0]),
  "activate-local");
assert.equal(PC.classifyRestore({projectRevision:3,projectSaveState:"synced"},projects[0]),
  "refresh-confirmed");
assert.match(PC.render({loggedIn:false}),/登录后查看云端项目/);
assert.match(PC.render({loggedIn:true,loading:true}),/正在读取/);
assert.match(PC.render({loggedIn:true,error:"offline"}),/云端项目读取失败/);
assert.match(PC.render({loggedIn:true}),/还没有云端项目/);
const filtered=PC.model({projects,tabs,loggedIn:true,query:"不匹配"});
assert.equal(filtered.cloud.length,0);
assert.equal(filtered.drafts.length,0);

const begin = source.indexOf("  /* ======================== STUDIO2 PROJECT CENTER");
const end = source.indexOf("  function openWorkflowsPage(", begin);
assert.ok(begin>0 && end>begin, "Extract Project Center bindings for functional tests");
const fragment=source.slice(begin,end);
async function suite() {
  const CS={tabs:[],closedProjectDrafts:[],myArticles:[],activeTabId:null,graph:{nodes:[],edges:[]},cloudProjects:[],
    projectCenterLoading:false,projectCenterLoadingMore:false,projectHasMore:false,
    projectPageCursor:"",projectListRequestVersion:0,projectCenterError:"",projectQuery:"",stageView:"projects",
    projectOpeningId:""};
  const opened=[],toasts=[],created=[],paths=[],getCalls=[],entryCalls=[];
  let listResolver = async () => ({ok:true,projects,hasMore:false,nextCursor:""});
  const listCalls=[];
  let resolver = async id => ({
    ok:true,project:{id,kind:"image",title:"云端春景",authority:"graph",
      revision:2,draft:{activeView:"simple",graph:{blueprint:"single",
        nodes:[{id:"server-node"}],edges:[]}}}
  });
  const ProjectClient={list:async options=>{listCalls.push(options);return listResolver(options);},get:async id=>{
    getCalls.push(id);return resolver(id);
  }};
  const win={HANDRAW_STUDIO_PROJECT_UNUSED:true,HandrawStudioProjectCenter:PC,
    location:{href:"http://localhost:3080/studio/?view=projects"},
    history:{replaceState:(_a,_b,path)=>paths.push(path)}};
  const sandbox={
    CS,DOM:{projectsStage:null},ProjectClient,ArticleProject109:Article109,
    App:{state:{loggedIn:true,serverBacked:true}},
    window:win,activeCacheScope:"account-1",cacheScopeEpoch:10,
    isStaleScope:(epoch,scope)=>epoch!==sandbox.cacheScopeEpoch||scope!==sandbox.activeCacheScope,
    toast:msg=>toasts.push(msg),
    syncCurrentTabSnapshot:()=>{},
    renderTopAndBottomDocks:()=>{},
    normalizeGraphSchema:x=>JSON.parse(JSON.stringify(x)),
    cloneGraph:x=>JSON.parse(JSON.stringify(x)),
    getBatchParts:()=>null,getQuickParts:graph=>graph.nodes?.some(n=>n.id==="server-node")?{}:null,
    activateWorkflowTab:tabId=>{opened.push(tabId); CS.activeTabId=tabId;
      CS.graph=JSON.parse(JSON.stringify(CS.tabs.find(x=>x.id===tabId).graph));},
    createWorkflowTab:args=>{const tab={id:"tab-new-"+(created.length+1),title:args.title,
      graph:args.graph,blueprint:args.blueprint,dirty:false};
      created.push(tab);CS.tabs.push(tab);return tab;},
    persistOpenTabs:()=>{},writeJsonStorage:()=>{},scheduleProjectAutoSave:()=>{},
    ensureMyArticlesInitialized:()=>{if(!Array.isArray(CS.myArticles))CS.myArticles=[];},
    openUnifiedArticleEditor:id=>entryCalls.push("open-article:"+id),
    MY_ARTICLES_STORAGE_KEY:"my_articles",
    CLOSED_PROJECT_DRAFTS_KEY:"closed",
    fullRenderCanvas:()=>{},
    openWorkflowsPage:()=>entryCalls.push("workflow"),
    switchCreationStage:name=>entryCalls.push(name),
    buildForkGraphFromWork:()=>({blueprint:"single",nodes:[{id:"new"}],edges:[]}),
    E:{
      uid:(type)=>type+"-"+created.length+"-"+Math.random().toString(36).slice(2),
      makeSkillParamsNode:()=>({id:"sp-1",type:"skill_params",data:{}}),
      makeTextInputNode:()=>({id:"txt-1",type:"text_input",data:{text:""}}),
      makeAssetNode:()=>({id:"asset-1",type:"asset",data:{items:[]}}),
      makeLoopNode:()=>({id:"loop-1",type:"loop",data:{}}),
      makeOutputControlNode:()=>({id:"ctrl-1",type:"output_control",data:{}})
    },URL,document:{activeElement:null},S:{openLoginModal:()=>{}},
    isArticleTab:()=>false,
  };
  vm.createContext(sandbox);
  vm.runInContext(fragment+"\nglobalThis.center={openCloudProject,openProjectCenter,refreshProjectCenter,loadMoreProjects,renderProjectCenterStage,createProjectFromCenter};",sandbox);
  const c=sandbox.center;
  // Cloud restore is a real operation, not a second generation.
  await c.openCloudProject("prj-01");
  assert.equal(created.length,1);
  assert.equal(CS.tabs[0].projectId,"prj-01");
  assert.equal(CS.tabs[0].projectRevision,2);
  assert.equal(CS.tabs[0].projectSaveState,"synced");
  assert.equal(CS.tabs[0].graph.nodes[0].id,"server-node");
  assert.equal(CS.stageView,"quick");
  assert.ok(paths.some(path=>path.includes("?entry=quick")));
  // Reopening the same cloud revision reuses the existing tab; no duplicates.
  await c.openCloudProject("prj-01");
  assert.equal(created.length,1);

  const local=CS.tabs[0];
  local.projectSaveState="conflict";
  local.projectPending={payload:{baseRevision:1}};
  local.graph={blueprint:"single",nodes:[{id:"LOCAL"}],edges:[]};
  CS.graph=JSON.parse(JSON.stringify(local.graph));
  const beforeRequests=getCalls.length;
  await c.openCloudProject("prj-01");
  assert.equal(getCalls.length,beforeRequests,"Conflicting local draft must not be refetched over");
  assert.equal(CS.graph.nodes[0].id,"LOCAL","Conflicting local graph survives");
  assert.ok(toasts.some(x=>x.includes("未覆盖")));

  // An Article Project routes to its sole editor; it never imports its
  // Markdown into the currently active Graph.
  local.projectSaveState="synced";local.projectPending=null;local.dirty=false;
  resolver=async id=>({ok:true,project:{id,kind:"article",title:"Article",
    authority:"article",revision:8,draft:{article:{
      documentId:"cloud-doc",revision:3,markdown:"keep this",anchors:[]},
      plan:{kind:"article",planId:"plan-cloud",revision:1,
        documentId:"cloud-doc",documentRevision:3,slots:[]}}}});
  await c.openCloudProject("prj-01");
  assert.equal(created.length,1,"Article Project does not open as Graph tab");
  assert.equal(CS.graph.nodes[0].id,"LOCAL","Graph content is untouched");
  assert.equal(CS.myArticles[0].markdown,"keep this");
  assert.equal(CS.myArticles[0].projectRevision,8);
  assert.ok(entryCalls.includes("open-article:cloud-doc"));

  // Previously closed offline drafts take precedence over stale cloud data.
  CS.closedProjectDrafts=[{id:"closed-1",title:"关闭前的草稿",blueprint:"single",
    graph:{blueprint:"single",nodes:[{id:"unsynced"}],edges:[]},
    projectId:"prj-closed",projectRevision:5,projectSaveState:"error",
    projectPending:{method:"PATCH",payload:{idempotencyKey:"stable-replay-1"}}}];
  const readsBefore=getCalls.length;
  await c.openCloudProject("prj-closed");
  assert.equal(getCalls.length,readsBefore,"Closed draft takes precedence over cloud read");
  const recovered=CS.tabs.find(t=>t.projectId==="prj-closed");
  assert.ok(recovered);
  assert.equal(recovered.graph.nodes[0].id,"unsynced");
  assert.equal(recovered.projectPending.payload.idempotencyKey,"stable-replay-1");
  assert.equal(CS.closedProjectDrafts.length,0,"Recovered draft moves to open tabs");

  // Switching account mid-request must discard the old session's response.
  const count=CS.tabs.length;
  let release;
  resolver=async id=>new Promise(resolve=>{release=resolve});
  const pending=c.openCloudProject("prj-remote");
  sandbox.cacheScopeEpoch++;
  release({ok:true,project:{id:"prj-remote",kind:"image",authority:"graph",
    revision:1,draft:{graph:{nodes:[{id:"foreign"}],edges:[]}}}});
  await pending;
  assert.equal(CS.tabs.length,count,"Stale account request cannot create a tab");
  // Each task entry must create a fresh editable project, never reuse the
  // previous cloud project or accidentally start image generation.
  const beforeNew=CS.tabs.length;
  c.createProjectFromCenter("image");
  assert.equal(CS.tabs.length,beforeNew+1);
  assert.equal(CS.stageView,"quick");
  assert.equal(CS.tabs.at(-1).projectSaveState,"local_only");
  assert.equal(CS.tabs.at(-1).projectId,undefined);
  c.createProjectFromCenter("series");
  assert.equal(CS.tabs.length,beforeNew+2);
  assert.equal(CS.stageView,"batch");
  assert.equal(CS.tabs.at(-1).graph.edges.length,6);
  assert.equal(CS.tabs.at(-1).batchStart,true);
  c.createProjectFromCenter("workflow");
  c.createProjectFromCenter("article");
  assert.deepEqual(entryCalls,["open-article:cloud-doc","workflow","article"]);

  CS.projectQuery="春天";
  listResolver=async options => {
    if (options.cursor === "cursor-first") {
      return {ok:true,projects:[{id:"cloud2",title:"春天二",kind:"image"},
        {id:"cloud1",title:"春天一",kind:"image"}],hasMore:false,nextCursor:""};
    }
    return {ok:true,projects:[{id:"cloud1",title:"春天一",kind:"image"}],
      hasMore:true,nextCursor:"cursor-first"};
  };
  await c.refreshProjectCenter();
  assert.equal(CS.cloudProjects.length,1);
  assert.equal(CS.projectHasMore,true);
  assert.equal(CS.projectPageCursor,"cursor-first");
  assert.equal(listCalls.at(-1).query,"春天");
  await c.loadMoreProjects();
  assert.equal(CS.cloudProjects.length,2,"No duplicates between pages");
  assert.equal(CS.projectHasMore,false);
  assert.equal(listCalls.at(-1).cursor,"cursor-first");

  console.log("Studio2 Project Center tests pass: navigation, escaping, safe local/remote recovery, scope");
}
suite().catch(err=>{console.error(err);process.exitCode=1});
