"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const shared = fs.readFileSync("demo/assets/shared.js", "utf8");
function fn(source, name) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf("\n  function ", start + 1));
}
const favorites = new Set();
const App = { resourceMap: new Map(), state: { exclusiveResources: [], communityResources: [] } };
const groups = [{key:"ALL",label:"全部"},{key:"COMMUNITY",label:"社区"},{key:"FAV",label:"收藏"},{key:"FA",label:"社论"},{key:"FB",label:"水彩"}];
const context = {
  App, STYLE_GROUPS: groups, LAYOUT_GROUPS: [], window: {},
  isCollected: (_bucket,id) => favorites.has(id),
  isFreshRelease: () => false, getAssetWorkCount: () => 0
};
vm.createContext(context);
for (const name of ["resourceLabel","resourceSearchText","resourceMatchesGroup","resourceGroupLabel","visibleResourceGroups","rebuildResourceIndexes"]) vm.runInContext(fn(shared, name), context);
const raw = {id:"FA-001",kind:"style",name:"Playful Deadpan Doodle",description:"松散黑线、怪萌人物",image:"/style.webp",group:"FA Editorial",definition:"unchanged generation definition"};
const layout = {id:"SC-001",kind:"layout",name:"留白卡片",group:"social-card",image:"/layout.webp"};
App.catalogRaw = {resources:[raw,layout]};
vm.runInContext("rebuildResourceIndexes()", context);
assert.equal(App.styles[0].name, "松散黑线");
assert.equal(App.styles[0].originalName, raw.name);
assert.equal(App.styles[0].definition, raw.definition);
assert.equal(raw.name, "Playful Deadpan Doodle", "display aliases must not edit canonical names");
const visible = query => JSON.parse(vm.runInContext(`JSON.stringify(visibleResourceGroups(App.styles, STYLE_GROUPS, ${JSON.stringify(query)}))`, context));
assert.deepEqual(visible("").map(g=>g.key), ["ALL","FA"]);
favorites.add("FA-001");
assert.deepEqual(visible("").map(g=>g.key), ["ALL","FAV","FA"]);
assert.deepEqual(visible("missing"), []);
assert.equal(visible("deadpan")[0].count, 1, "old English search still resolves its original resource");
context.color = {id:"C-01",name_zh:"朱砂",desc_zh:"温暖红色"};
assert.match(vm.runInContext("resourceSearchText(color)",context),/朱砂.*温暖红色/);
App.state.communityResources.push({id:"USR-S01",kind:"style",name:"新画风",group:"custom",sourceType:"community"});
vm.runInContext("rebuildResourceIndexes()", context);
assert.equal(visible("").find(g=>g.key==="COMMUNITY").count, 1, "empty categories return when they gain content");

const esc = value => String(value ?? "").replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;").replaceAll(">","&gt;");
context.S = {resourceLabel: context.resourceLabel};
context.esc = esc;
vm.runInContext(fn(fs.readFileSync("demo/assets/quick-create.js","utf8"),"pickerHtml"),context);
context.picked = App.styles.find(r=>r.id==="FA-001");
const html = vm.runInContext('pickerHtml("style", picked)',context);
assert.match(html,/data-hw-src="\/style.webp"/);
assert.match(html,/更换画风 FA-001/);
assert.doesNotMatch(html,/Playful|Deadpan/);
context.picked = {id:'bad"id',name:'中文<script>',image:'x" onerror="bad'};
assert.doesNotMatch(vm.runInContext('pickerHtml("style", picked)',context),/<script>|src="x" onerror=/);
context.S = {App, esc, resourceLabel:context.resourceLabel, compareByRecency:()=>0,channelUrl:(channel,params)=> (channel==="main" && params?.view==="asset") ? `/t/${params.id}` : `/${channel}?${new URLSearchParams(params)}`};
context.window.HANDRAW_SHARED = context.S;
App.state.works = []; App.state.topics = [];
vm.runInContext(fs.readFileSync("demo/assets/discovery.js","utf8"),context);
const root = {};
context.window.HandrawDiscovery.render(root);
assert.match(root.innerHTML,/data-hw-src="\/style.webp"/);
assert.match(root.innerHTML,/\/t\/FA-001/);
assert.doesNotMatch(root.innerHTML,/Playful Deadpan/);
const catalog = JSON.parse(fs.readFileSync("plugin/content/catalog.json","utf8"));
App.catalogRaw = catalog;
App.state.communityResources = [];
vm.runInContext("rebuildResourceIndexes()",context);
for (const rawItem of catalog.resources.filter(r=>["style","layout"].includes(r.kind))) {
  const shown = App.resourceMap.get(rawItem.id);
  assert.match(shown.name,/[\u3400-\u9fff]/,rawItem.id);
  assert.equal(shown.definition,rawItem.definition,rawItem.id);
  assert.equal(shown.image,rawItem.image,rawItem.id);
}
// Gallery category order must not depend on API/database row order.
favorites.clear();
vm.runInContext(shared.slice(shared.indexOf("  const STYLE_GROUPS = ["), shared.indexOf("  const SAMPLE_UPLOAD_IMAGES"))
  .replaceAll("const STYLE_GROUPS", "STYLE_GROUPS").replaceAll("const LAYOUT_GROUPS", "LAYOUT_GROUPS"), context);
for (const name of ["resourcePickerGroups", "sortResourcesByGroup"]) vm.runInContext(fn(shared, name), context);
context.layoutPool = [...catalog.resources.filter(r => r.kind === "layout")].reverse();
const layoutTabs = JSON.parse(vm.runInContext('JSON.stringify(visibleResourceGroups(layoutPool, resourcePickerGroups(layoutPool,"layout")))', context));
assert.deepEqual(layoutTabs.map(g => g.label), ["全部图型", "社媒卡", "信息图", "漫画分镜", "IP设计", "电商"]);
assert.equal(vm.runInContext('sortResourcesByGroup(layoutPool,"layout")[0].group',context), "social-card");
context.stylePool = [...catalog.resources.filter(r => r.kind === "style")].reverse();
const styleTabs = JSON.parse(vm.runInContext('JSON.stringify(visibleResourceGroups(stylePool, resourcePickerGroups(stylePool,"style")))',context));
assert.deepEqual(styleTabs.map(g=>g.label), ["全部画风","国际社论","经典绘本","现代平面","日本当代","新国风非遗","3D黏土纸雕","动漫和赛璐璐","先锋综合","写实摄影"]);
assert.equal(new Set(styleTabs.map(g=>g.key)).size,styleTabs.length,"long catalog group names must not duplicate category tabs");
assert.equal(vm.runInContext('sortResourcesByGroup(stylePool,"style")[0].id.startsWith("FA-")',context),true);
context.customPool = [{id:"USR-S99",kind:"style",group:"私人 分组"}];
assert.equal(vm.runInContext('visibleResourceGroups(customPool, resourcePickerGroups(customPool,"style"))[1].key',context),"私人 分组","custom category keys are preserved");
console.log("Resource presentation: Chinese display, unchanged definitions, dynamic groups and image selections passed");
