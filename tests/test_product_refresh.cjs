"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");
function extract(source, name) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  const end = source.indexOf("\n  function ", start + 1);
  return source.slice(start, end < 0 ? undefined : end);
}
const App = { state: { loggedIn: false } };
const CS = { engineMode: "api", serverCfg: {}, tabs: [] };
const context = { App, CS, URLSearchParams, window: { location: { search: "" } }, UI: {} };
vm.createContext(context);
vm.runInContext(extract(studio, "generationCostText"), context);
const cost = count => vm.runInContext(`generationCostText(${count})`, context);
assert.match(cost(4), /登录后/);
App.state = { loggedIn: true, credits: 18 };
assert.match(cost(4), /预计 待确认/);
App.state.freeQuotaRemaining = 2;
CS.serverCfg.creditPerImage = 3;
assert.match(cost(4), /预计 6 积分/);
assert.match(cost(1), /预计 0 积分/);
CS.engineMode = "demo";
assert.match(cost(4), /演示模式/);

// Quick entry creates a separate graph and reuses it, preserving advanced work.
let counter = 0;
context.E = {
  uid: () => `id${++counter}`,
  makeSkillParamsNode: () => ({ id: `s${++counter}`, type: "skill_params", data: {} }),
  makeTextInputNode: () => ({ id: `t${++counter}`, type: "text_input", data: { text: "" } }),
  makeOutputControlNode: (_x, _y, data) => ({ id: `c${++counter}`, type: "output_control", data })
};
const advanced = { id: "existing", graph: { nodes: [{ type: "article", data: { text: "private draft" } }] } };
CS.tabs.push(advanced);
const before = JSON.stringify(advanced);
context.createWorkflowTab = opts => { const tab = { ...opts, id: `tab${++counter}` }; CS.tabs.push(tab); return tab; };
context.activateWorkflowTab = id => { CS.activeTabId = id; CS.graph = CS.tabs.find(t => t.id === id).graph; };
context.persistOpenTabs = () => {};
vm.runInContext(extract(studio, "ensureQuickTab") + extract(studio, "getQuickParts"), context);
vm.runInContext("ensureQuickTab(); ensureQuickTab()", context);
assert.equal(CS.tabs.length, 2);
assert.equal(JSON.stringify(advanced), before);
assert.equal(vm.runInContext("getQuickParts().text.data.text", context), "");
assert.equal(vm.runInContext("getQuickParts().skill.data.style1", context), undefined);
CS.graph.nodes.push({ id: "article", type: "article" });
assert.equal(vm.runInContext("getQuickParts()", context), null);
CS.graph.nodes.pop();
CS.graph.edges = [];
assert.equal(vm.runInContext("getQuickParts()", context), null);

// Returning from an advanced canvas must open a usable form without losing it.
context.URL = URL;
context.window.location = { href:'http://127.0.0.1:3080/studio/?entry=canvas&tab=article' };
context.window.history = { replaceState(_a,_b,path) { context.window.location.href = new URL(path,context.window.location.href).href; } };
context.requestAnimationFrame = fn => fn();
context.fullRenderCanvas = () => {};
context.fitView = () => {};
context.toast = () => {};
context.activeCacheScope = "scope-test";
context.isArticleGraph = () => false;
context.switchIntoArticleMode = () => {};
context.switchToCanvasFromArticle = () => {};
context.readScopedReturnTab = () => null;
context.pickReturnCanvasTab = () => null;
// switchCreationStage flushes the unified editor before changing modes; stub the
// persist/render side effects it would otherwise trigger in this harness.
context.ensureMyArticlesInitialized = () => {
  if (!Array.isArray(CS.myArticles)) CS.myArticles = [];
};
context.persistMyArticles = () => {};
vm.runInContext(extract(studio, "flushUnifiedArticleEditor"), context);
let generationCalls = 0;
context.runOutputControlNode = () => { generationCalls++; };
context.activateWorkflowTab = id => {
  const current=CS.tabs.find(t=>t.id===CS.activeTabId);
  if (current) current.graph=JSON.parse(JSON.stringify(CS.graph));
  CS.activeTabId=id;
  CS.graph=JSON.parse(JSON.stringify(CS.tabs.find(t=>t.id===id).graph));
};
vm.runInContext(extract(studio,'switchCreationStage'),context);
const malformed={id:'old-quick',quickStart:true,graph:{nodes:[{type:'article',data:{text:'preserve old quick canvas'}}],edges:[]}};
CS.tabs.push(malformed);
const malformedBefore=JSON.stringify(malformed);
context.activateWorkflowTab(advanced.id);
vm.runInContext('switchCreationStage("quick")',context);
assert.equal(CS.stageView,'quick');
assert.ok(vm.runInContext('getQuickParts()',context));
assert.equal(JSON.stringify(malformed),malformedBefore);
assert.equal(JSON.stringify(advanced),before);
assert.match(context.window.location.href,/entry=quick/);
assert.doesNotMatch(context.window.location.href,/tab=/);
assert.equal(vm.runInContext('getQuickParts({nodes:CS.graph.nodes})',context),null);

// A cached quick snapshot may be simple while the live canvas has become complex.
const liveTab={id:'live-changed',quickStart:true,graph:JSON.parse(JSON.stringify(CS.graph))};
CS.tabs.push(liveTab);
context.activateWorkflowTab(liveTab.id);
CS.graph.nodes.push({id:'extra-article',type:'article',data:{text:'keep live edits'}});
const liveBefore=JSON.stringify(CS.graph);
vm.runInContext('switchCreationStage("quick")',context);
assert.notEqual(CS.activeTabId,liveTab.id);
assert.equal(JSON.stringify(liveTab.graph),liveBefore,'preserve the live advanced edits');
assert.ok(vm.runInContext('getQuickParts()',context));
const parts=vm.runInContext('getQuickParts()',context);
parts.text.data.text='模式切换验收';
Object.assign(parts.ctrl.data,{count:3,ratio:'16:9',mode:'pure-image'});
Object.assign(parts.skill.data,{style1:'FA-001',layout:'IG-001'});
const formBefore=JSON.stringify(CS.graph);
const formTab=CS.activeTabId;
vm.runInContext('switchCreationStage("canvas"); switchCreationStage("quick")',context);
assert.equal(CS.activeTabId,formTab);
assert.equal(JSON.stringify(CS.graph),formBefore,'switching views preserves every form parameter');
assert.equal(generationCalls,0,'switching modes never starts generation');

// All 3 mode controls (quick, canvas, article) stay available, including while browsing history.
const modeButtons={'#studio-mode-quick':{},'#studio-mode-canvas':{},'#studio-mode-article':{}};
context.DOM={entryBar:{hidden:true,innerHTML:'',querySelector:key=>modeButtons[key]}};
vm.runInContext(extract(studio,'renderCreationModeBar'),context);
for (const stage of ['quick','canvas','preview','history']) {
  CS.stageView=stage;
  vm.runInContext('renderCreationModeBar()',context);
  assert.equal(context.DOM.entryBar.hidden,false);
  assert.match(context.DOM.entryBar.innerHTML,new RegExp(`id="studio-mode-quick" aria-pressed="${stage==='quick'}"`));
  assert.match(context.DOM.entryBar.innerHTML,new RegExp(`id="studio-mode-canvas" aria-pressed="${stage==='canvas'}"`));
  assert.match(context.DOM.entryBar.innerHTML,new RegExp(`id="studio-mode-article" aria-pressed="${stage==='preview'||stage==='article'}"`));
  assert.match(context.DOM.entryBar.innerHTML,new RegExp(`id="studio-mode-history" aria-pressed="${stage==='history'}"`));
}

// Legacy root searches still open the catalog; the empty root opens discovery.
vm.runInContext(extract(fs.readFileSync("demo/assets/main-app.js", "utf8"), "parseInitialUrl"), context);
for (const [query, view] of [["", "discover"], ["?q=FA-001", "styles"], ["?asset=FA-001", "asset"], ["?work=w_101", "work"], ["?view=layouts", "layouts"]]) {
  context.window.location.search = query;
  vm.runInContext("parseInitialUrl()", context);
  assert.equal(App.view, view, query);
}

// Empty feeds stay empty, and user-provided titles/attributes remain escaped.
const esc = value => String(value ?? "").replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const S = { App, esc, channelUrl: (channel, params) => `/${channel}?${new URLSearchParams(params)}`, compareByRecency: (a, b) => b.publishedAtMs - a.publishedAtMs };
context.window.HANDRAW_SHARED = S;
vm.runInContext(fs.readFileSync("demo/assets/discovery.js", "utf8"), context);
const root = {};
App.state = { works: [], topics: [] };
context.window.HandrawDiscovery.render(root);
assert.match(root.innerHTML, /暂时还没有公开作品/);
assert.doesNotMatch(root.innerHTML, /data-hw-src/);
App.state.topics = [{id:"reference-post",title:"Practice",images:[{url:"/reference.webp",tag:"画风参考 FB-001"}]}];
context.window.HandrawDiscovery.render(root);
assert.match(root.innerHTML, /社区图文与参考/);
assert.match(root.innerHTML, /class="hw-discovery__all-works" href="\/main\?view=works"/);
assert.match(root.innerHTML, /画风参考 FB-001/);
assert.match(root.innerHTML, /\/forum\?view=topic/);
assert.doesNotMatch(root.innerHTML, /暂时还没有公开作品/);
App.state.topics = [];
App.state.works = [{ id: 'a"<', title: '<script>bad</script>', images: ['https://example.test/a" onerror="bad'], authorName: '<b>A</b>' }];
context.window.HandrawDiscovery.render(root);
assert.doesNotMatch(root.innerHTML, /<script>|<b>A/);
assert.match(root.innerHTML, /&lt;script&gt;/);
assert.match(root.innerHTML, /&quot; onerror=&quot;/);
console.log("Product refresh: costs, graph preservation, legacy routes and safe discovery passed");
