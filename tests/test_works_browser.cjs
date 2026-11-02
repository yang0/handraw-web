"use strict";
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{},URLSearchParams,clearTimeout,setTimeout,document:{},localStorage:{getItem(){return null;},setItem(){}},location:{search:'',pathname:'/'}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('demo/assets/works-browser.js','utf8'),context);
const B=context.window.HandrawWorksBrowser;
const copy=value=>JSON.parse(JSON.stringify(value));
const map=new Map([['FA-001',{name:'松散黑线',description:'纸上练习'}],['SC-001',{name:'留白卡片'}]]);
// Load the REAL shared.js so this test cannot pass against a hand-written stub
// that drifts from the shipped ranking rule.
vm.runInContext(fs.readFileSync('demo/assets/shared.js','utf8'),context);
const SHARED=context.window.HANDRAW_SHARED;
assert.ok(SHARED&&typeof SHARED.popularScore==='function','shared.js must export popularScore');
const popularScore=SHARED.popularScore;
const S={compareByRecency:(a,b)=>(b.publishedAtMs||0)-(a.publishedAtMs||0),popularScore};
const works=[
  {id:'single',title:'春天植物',notes:'公开笔记',author:'writer',authorName:'小林',images:['/one.webp'],styles:['FA-001'],price:0,publishedAtMs:100,favorites:2,cheers:8},
  {id:'multi',title:'旅行记录',author:'writer',images:['/a.webp','/b.webp'],layout:'SC-001',price:9,prompt:'private-paid-only',publishedAtMs:200,favorites:2,cheers:3},
  {id:'freeform',title:'随手画',author:'other',images:[{url:'/c.webp'}],publishedAtMs:300,favorites:0,cheers:0},
  {id:'no-image',title:'不能显示为作品',images:[]}
];
assert.deepEqual(copy(B.countFormats(works)),{all:3,single:2,multi:1});
assert.deepEqual(copy(B.countFormats([])),{all:0,single:0,multi:0});
const select=f=>copy(B.select(works,f,map,S)).map(w=>w.id);
assert.deepEqual(select({format:'single'}),['freeform','single']);
assert.deepEqual(select({format:'multi'}),['multi']);
assert.deepEqual(select({access:'free'}),['freeform','single']);
assert.deepEqual(select({access:'paid'}),['multi']);
assert.deepEqual(select({asset:'FA-001',author:'writer'}),['single']);
assert.deepEqual(select({query:'松散黑线'}),['single']);
assert.deepEqual(select({query:'sc-001'}),['multi']);
assert.deepEqual(select({query:'小林'}),['single']);
assert.deepEqual(select({query:'private-paid-only'}),[],'Search cannot expose paid prompt text');
// Legacy "favorites"/"cheers" both collapse onto the one popularity formula:
// single = 2*2+8 = 12, multi = 2*2+3 = 7, freeform = 0.
assert.deepEqual(select({sort:'favorites'}),['single','multi','freeform'],'Legacy favorites maps to popular');
assert.deepEqual(select({sort:'cheers'}),['single','multi','freeform'],'Legacy cheers maps to popular');
assert.deepEqual(select({sort:'popular'}),['single','multi','freeform']);
assert.deepEqual(select({sort:'hot'}),['single','multi','freeform']);
assert.deepEqual(works.map(w=>w.id),['single','multi','freeform','no-image'],'Do not mutate shared works');

const source=fs.readFileSync('demo/assets/main-app.js','utf8');
function extract(name){const start=source.indexOf(`  function ${name}(`);assert.ok(start>=0);const end=source.indexOf('\n  function ',start+1);return source.slice(start,end<0?undefined:end);}
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const makeRoot=()=>({innerHTML:'',querySelector(){return {addEventListener(){}};},querySelectorAll(){return [];}});
context.App={view:'works',state:{works:[],loggedIn:false},resourceMap:map};
context.UI={workFormat:'all',workAccess:'all',workQuery:'',workFilterAsset:'',workFilterAuthor:'',workSort:'newest',workShownCount:24};
context.esc=escape;
context.channelUrl=(channel,params)=>`/${channel}?${new URLSearchParams(params)}`;
context.S={...S,isCollected:()=>false,getFavoriteCount:(_type,w)=>w.favorites||0,isUnlocked:(_id,w)=>!w.price,canModerateWork:()=>false,canDeleteWork:()=>false};
context.window.HandrawWorksBrowser=B;
vm.runInContext(extract('renderWorksSquare'),context);
const root=makeRoot();context.renderWorksSquare(root);
assert.match(root.innerHTML,/还没有已收录作品/);
assert.match(root.innerHTML,/data-wb-format="all"/);
assert.doesNotMatch(root.innerHTML,/data-wb-format="single"|data-wb-format="multi"/);
assert.match(root.innerHTML,/\/forum\?/,'Empty state goes to real forum');
assert.doesNotMatch(root.innerHTML,/data-wb-mod|画风\+图型齐全|综合曝光|高产加权/);
context.App.state.works=Array.from({length:30},(_,i)=>({...works[0],id:'work_'+i,publishedAtMs:i}));
context.renderWorksSquare(root);
assert.equal((root.innerHTML.match(/data-wb-work=/g)||[]).length,24);
assert.match(root.innerHTML,/id="hw-wb-more"/);
context.UI.workShownCount=48;context.renderWorksSquare(root);
assert.equal((root.innerHTML.match(/data-wb-work=/g)||[]).length,30);
context.App.state.works=[{...works[1],id:'quoted"<',title:'<script>alert(1)</script>',images:['/image" onerror="bad.webp','/two.webp']}];
context.renderWorksSquare(root);
assert.doesNotMatch(root.innerHTML,/<script>| onerror="bad/);
assert.match(root.innerHTML,/&lt;script&gt;/);
assert.doesNotMatch(root.innerHTML,/hw-wb-price|积分做法|已解锁做法/);
assert.doesNotMatch(root.innerHTML,/private-paid-only/);

context.window.location={search:'?view=works&format=multi&access=paid&sort=favorites&q=卡片&filterAsset=SC-001&author=writer',pathname:'/'};
vm.runInContext(extract('parseInitialUrl'),context);context.parseInitialUrl();
assert.equal(context.UI.workFormat,'multi');assert.equal(context.UI.workAccess,'paid');
assert.equal(context.UI.workSort,'favorites');assert.equal(context.UI.workQuery,'卡片');
assert.equal(context.UI.workFilterAsset,'SC-001');assert.equal(context.UI.workFilterAuthor,'writer');
context.window.location.search='?view=works';context.parseInitialUrl();
assert.equal(context.UI.workFormat,'all');assert.equal(context.UI.workQuery,'');assert.equal(context.UI.workFilterAuthor,'');
assert.equal(context.UI.workSort,'newest');
console.log('Works browser: format, access, public search, stable sorting, bounded cards, route restoration and safe empty states passed');
