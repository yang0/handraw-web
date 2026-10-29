"use strict";
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const studio=fs.readFileSync('demo/assets/studio-app.js','utf8');
const engine=fs.readFileSync('demo/assets/studio-prompt-engine.js','utf8');
function extract(name) {
  const start=studio.indexOf(`  function ${name}(`);
  assert.ok(start>=0,name);
  const end=studio.indexOf('\n  function ',start+1);
  return studio.slice(start,end<0?undefined:end);
}
function initialize(query,{stored=true,works=[],topics=[]}={}) {
  const initialHref='http://127.0.0.1:3080/studio/'+query;
  const context={URL,URLSearchParams,window:{location:{search:query,href:initialHref},history:{replaceState(_s,_t,p){const u=new URL(p,context.window.location.href);context.window.location.href=u.href;context.window.location.search=u.search;},pushState(){}}},CS:{stageView:'canvas'},App:{state:{works,topics}},OPEN_TABS_KEY:'test-tabs'};
  vm.createContext(context);
  vm.runInContext(engine,context);
  context.E=context.window.HANDRAW_CANVAS_ENGINE;
  context.Catalog={resourceMap:new Map([['FA-001',{id:'FA-001',kind:'style'}],['IG-001',{id:'IG-001',kind:'layout'}]])};
  const advanced={id:'advanced',title:'existing advanced',graph:context.E.createBlueprintGraph('article',context.Catalog,{})};
  const priorQuick={id:'quick-draft',title:'existing form',quickStart:true,graph:{nodes:[
    context.E.makeSkillParamsNode(0,0,{style1:'STALE-STYLE',layout:'STALE-LAYOUT'}),context.E.makeTextInputNode(0,0,{text:'keep existing theme'}),context.E.makeOutputControlNode(0,0,{mode:'graphic-text'})
  ],edges:[]}};
  priorQuick.graph.edges=priorQuick.graph.nodes.slice(0,2).map(n=>({from:n.id,to:priorQuick.graph.nodes[2].id}));
  const saved={activeTabId:'advanced',tabs:[advanced,priorQuick]};
  const before=JSON.stringify(saved);
  context.readJsonStorage=()=>stored?saved:null;
  context.ensureDefaultSavedWorkflows=()=>{};
  context.normalizeGraphSchema=g=>JSON.parse(JSON.stringify(g));
  context.persistOpenTabs=()=>{};
  context.ensureGenerationHistoryInitialized=()=>{};
  context.syncAllTabsArticlesIntoStore=()=>{};
  context.ensureArticleForArticleMode=()=>{};
for (const name of ['isArticleBlueprint','isArticleGraph','isArticleTab','currentCacheScopeKey','findArticleWorkspaceTab','ensureArticleWorkspace']) {
  const fn = extract(name);
  vm.runInContext(`var ${name} = (${fn});`, context, { filename: 'plugin.js#' + name });
}
context.ensureMyArticlesInitialized = () => {
  if (!Array.isArray(context.CS.myArticles)) context.CS.myArticles = [];
};
context.getSortedMyArticles = () => (context.CS.myArticles || []).slice();
context.persistMyArticles = () => {};
context.renderFullPreviewStage = () => {};
context.DOM = context.DOM || {};
for (const name of ['flushUnifiedArticleEditor','makeBlankArticleDraft','draftFromArticle','findArticleById','openUnifiedArticleEditor']) {
  const fn = extract(name);
  vm.runInContext(`var ${name} = (${fn});`, context, { filename: 'plugin.js#' + name });
}
  context.openMyArticlesPage=()=>{context.CS.stageView='preview';};
  context.createWorkflowTab=opts=>{const tab={...opts,id:'new-'+context.CS.tabs.length};context.CS.tabs.push(tab);return tab;};
  context.activateWorkflowTab=id=>{context.CS.activeTabId=id;context.CS.graph=context.CS.tabs.find(t=>t.id===id).graph;};
  let calls=0;
  context.runOutputControlNode=()=>{calls++;};
  vm.runInContext(['buildForkGraphFromWork','getQuickParts','ensureQuickTab','hydrateTabsAndUrlParams'].map(extract).join('\n'),context);
  vm.runInContext('hydrateTabsAndUrlParams()',context);
  assert.equal(JSON.stringify(saved),before,'initialization must preserve existing saved drafts');
  assert.equal(calls,0,'opening a resource never starts generation');
  return {context,parts:vm.runInContext('getQuickParts()',context)};
}
const cases=[
  ['?entry=quick&style=FA-001','FA-001',''],
  ['?entry=quick&layout=IG-001','','IG-001'],
  ['?entry=quick&style=FA-001&layout=IG-001','FA-001','IG-001'],
  ['?entry=quick&style=%20%23%20fa-001%20','FA-001',''],
  ['?style=FA-001','FA-001',''],
  ['?entry=quick&style=UNKNOWN','',''],
  ['?entry=quick&style=IG-001','',''],
  ['?entry=quick&layout=FA-001','',''],
  ['?entry=quick&style=','',''],
  ['?entry=quick&style=UNKNOWN&layout=IG-001','','IG-001']
];
for(const stored of [true,false]) for(const [query,style,layout] of cases) {
  const {context:c,parts:p}=initialize(query,{stored});
  assert.ok(p,query+' must render the actual form');
  assert.equal(c.CS.stageView,'quick');
  assert.equal(p.skill.data.style1,style,query);
  assert.equal(p.skill.data.style2,'');
  assert.equal(p.skill.data.layout,layout,query);
  assert.equal(p.text.data.text,'','resource URL must not load a preset or a prior theme');
  assert.equal(p.ctrl.data.mode,'graphic-text');
  assert.equal(p.ctrl.data.count,1);
  assert.equal(p.ctrl.data.ratio,'3:4');
  assert.equal(c.CS.graph.nodes.length,3);
  assert.equal(c.CS.graph.edges.length,2);
  if(query.includes('UNKNOWN') || query.includes('style=IG-001') || query.includes('layout=FA-001') || query.endsWith('style=')) assert.match(c.CS.resourceEntryWarning,/不存在或尚未收录/);
  else assert.equal(c.CS.resourceEntryWarning,'');
}
const canvas=initialize('?entry=canvas&style=FA-001');
assert.equal(canvas.context.CS.stageView,'canvas');
assert.equal(canvas.parts.skill.data.style1,'FA-001');
assert.equal(canvas.parts.skill.data.layout,'');
const articleMode=initialize('?entry=article&style=FA-001');
assert.equal(articleMode.context.CS.stageView,'preview');
const fork=initialize('?entry=quick&fork=work-real',{works:[{id:'work-real',title:'existing work',prompt:'preserve actual recipe',styles:['FA-001'],layout:'IG-001',mode:'pure-image',ratio:'16:9'}]});
assert.equal(fork.parts.text.data.text,'preserve actual recipe');
assert.equal(fork.parts.ctrl.data.mode,'pure-image');
assert.equal(fork.parts.ctrl.data.ratio,'16:9');
const recipeFork=initialize('?entry=quick&forkTopic=recipe-topic',{topics:[{id:'recipe-topic',title:'论坛标题',styles:['FA-001'],layout:'IG-001',recipe:{prompt:'必须复刻显示的这段提示词',theme:'不要用另一段主题',mode:'pure-image',ratio:'16:9'}}]});
assert.equal(recipeFork.parts.text.data.text,'必须复刻显示的这段提示词');
assert.equal(recipeFork.parts.skill.data.style1,'FA-001');
assert.equal(recipeFork.parts.skill.data.layout,'IG-001');
assert.equal(recipeFork.parts.ctrl.data.ratio,'16:9');
console.log('Studio resource entry: real hydration and engine, fresh/saved drafts, exact asset IDs, empty theme, validation, canvas and fork passed');
