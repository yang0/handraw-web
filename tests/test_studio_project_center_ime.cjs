"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const src=fs.readFileSync("demo/assets/studio-app.js","utf8");
const start=src.indexOf("  function renderProjectCenterStage() {");
const end=src.indexOf("  function openWorkflowsPage(",start);
assert.ok(start>0 && end>start, "Project Center rendering function is extractable");
const fragment=src.slice(start,end);
const CS={
  stageView:"projects",cloudProjects:[],tabs:[],closedProjectDrafts:[],
  projectQuery:"未选择 文字",projectCenterLoading:false,projectCenterError:"",
  projectHasMore:true,projectCenterLoadingMore:false,projectListRequestVersion:10
};
let calls=0, refreshes=0, timerSeq=0;
const timers=new Map(),clears=[];
const document={activeElement:null};
function makeInput(){
  return {id:"pc-project-search",value:CS.projectQuery,selectionStart:0,selectionEnd:0,
    oninput:null,oncompositionstart:null,oncompositionend:null,onkeydown:null,
    focus(){document.activeElement=this;},
    setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}}
}
const stage={
  style:{},currentScroller:{scrollTop:485},currentInput:makeInput(),
  querySelector(selector){
    if(selector===".ic-pc-scroll")return this.currentScroller;
    if(selector==="#pc-project-search")return this.currentInput;
    return null;
  },
  querySelectorAll(){return []},
  set innerHTML(html){
    this.markup=html;
    this.currentScroller={scrollTop:0};
    this.currentInput=makeInput();
    calls++;
  },
  get innerHTML(){return this.markup||""}
};
document.activeElement=stage.currentInput;
document.activeElement.value="未选择 文字";
document.activeElement.selectionStart=2;
document.activeElement.selectionEnd=4;
const sandbox={
  CS,DOM:{projectsStage:stage},document,
  ProjectCenter:{render:()=>"<section><input/></section>"},
  App:{state:{serverBacked:true,loggedIn:true}},
  activeCacheScope:"account_A",cacheScopeEpoch:3,
  _projectSearchTimer:null,
  isStaleScope:(epoch,scope)=>epoch!==sandbox.cacheScopeEpoch||scope!==sandbox.activeCacheScope,
  renderTopAndBottomDocks:()=>{},refreshProjectCenter:()=>{refreshes++},
  setTimeout:(fn,delay)=>{const id=++timerSeq;timers.set(id,{fn,delay});return id;},
  clearTimeout:id=>{clears.push(id);timers.delete(id);},
  S:{openLoginModal:()=>{}},toast:()=>{},ProjectClient:{}
};
vm.createContext(sandbox);
vm.runInContext(fragment+"\nglobalThis.renderCenter=renderProjectCenterStage;",sandbox);
sandbox.renderCenter();
assert.equal(stage.currentScroller.scrollTop,485,"Paginated list must keep scroll position");
assert.equal(stage.currentInput.selectionStart,2);
assert.equal(stage.currentInput.selectionEnd,4);
assert.equal(document.activeElement,stage.currentInput,"Rerender must restore search focus");

const input=stage.currentInput,afterRender=calls;
input.oncompositionstart();
input.value="杭州 春天";
input.oninput();
assert.equal(timers.size,0,"IME composition must not trigger search");
assert.equal(calls,afterRender,"IME composition must not recreate input DOM");
input.oncompositionend();
assert.equal(CS.projectQuery,"杭州 春天");
assert.equal(timers.size,1);
assert.equal([...timers.values()][0].delay,300);
assert.equal(calls,afterRender,"Debounce must not recreate input DOM");
assert.equal(input,stage.currentInput);

input.value="杭州 夏天";
input.oninput();
assert.equal(timers.size,1,"New query replaces older debounce");
assert.equal(CS.projectQuery,"杭州 夏天");
assert.ok(clears.length>0);
assert.ok(CS.projectListRequestVersion>10);
for(const {fn} of timers.values())fn();
assert.equal(refreshes,1);

timers.clear();
let prevented=false;
input.onkeydown({key:"Enter",isComposing:false,preventDefault(){prevented=true;}});
assert.equal(prevented,true);
assert.equal([...timers.values()][0].delay,0,"Enter triggers immediate search");
console.log("Studio2 Project Center IME, focus, scroll and search debounce regression passed");
