"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const PC = require("../demo/assets/studio-project-center.js");
const source = fs.readFileSync("demo/assets/studio-app.js","utf8");
const css = fs.readFileSync("demo/assets/studio-canvas.css","utf8");
const html = fs.readFileSync("demo/studio.html","utf8");
assert.ok(html.includes("studio-project-center.js"), "Page loads the Project Center module");
assert.ok(source.includes('id="studio-mode-projects"'), "Project Center has visible navigation");
assert.ok(source.includes('viewParam === "projects"'), "Direct ?view=projects deep link is supported");
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
  const CS={tabs:[],activeTabId:null,graph:{nodes:[],edges:[]},cloudProjects:[],
    projectCenterLoading:false,projectCenterError:"",projectQuery:"",stageView:"projects",
    projectOpeningId:""};
  const opened=[],toasts=[],created=[],paths=[],getCalls=[];
  let resolver = async id => ({
    ok:true,project:{id,kind:"image",title:"云端春景",authority:"graph",
      revision:2,draft:{activeView:"simple",graph:{blueprint:"single",
        nodes:[{id:"server-node"}],edges:[]}}}
  });
  const ProjectClient={list:async()=>({ok:true,projects}),get:async id=>{
    getCalls.push(id);return resolver(id);
  }};
  const win={HANDRAW_STUDIO_PROJECT_UNUSED:true,HandrawStudioProjectCenter:PC,
    location:{href:"http://localhost:3080/studio/?view=projects"},
    history:{replaceState:(_a,_b,path)=>paths.push(path)}};
  const sandbox={
    CS,DOM:{projectsStage:null},ProjectClient,App:{state:{loggedIn:true,serverBacked:true}},
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
    persistOpenTabs:()=>{},
    fullRenderCanvas:()=>{},
    openWorkflowsPage:()=>{},switchCreationStage:()=>{},buildForkGraphFromWork:()=>{},
    E:{},URL,document:{activeElement:null},S:{openLoginModal:()=>{}},
    isArticleTab:()=>false,
  };
  vm.createContext(sandbox);
  vm.runInContext(fragment+"\nglobalThis.center={openCloudProject,openProjectCenter,refreshProjectCenter,renderProjectCenterStage};",sandbox);
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

  // Project authored by the article editor must never be silently opened
  // in an incompatible graph editor.
  local.projectSaveState="synced";local.projectPending=null;local.dirty=false;
  resolver=async id=>({ok:true,project:{id,kind:"article",title:"Article",
    authority:"article",revision:8,draft:{article:{markdown:"keep this"}}}});
  await c.openCloudProject("prj-01");
  assert.equal(created.length,1);
  assert.equal(CS.graph.nodes[0].id,"LOCAL");
  assert.ok(toasts.some(x=>x.includes("旧画布不能安全恢复")));

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
  console.log("Studio2 Project Center tests pass: navigation, escaping, safe local/remote recovery, scope");
}
suite().catch(err=>{console.error(err);process.exitCode=1});
