"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs");
const context={window:{},console};
vm.createContext(context);
vm.runInContext(fs.readFileSync("demo/assets/studio-prompt-engine.js","utf8"),context);
const {reconcileArticlePlan}=context.window.HANDRAW_CANVAS_ENGINE;
const plain=value=>JSON.parse(JSON.stringify(value));

test("unique semantic anchors retain slot identity, selection and custom parameters after text moves",()=>{
  const old=[{id:"stable",role:"inline",anchorHeading:"## Section",afterBlockIdx:2,prompt:"My prompt",promptCustomized:true,
    imageUrl:"/selected.webp",status:"done",selectedMediaId:"media",resultEpoch:8,style1:"FA-002",ratio:"3:2",refImages:["/ref.webp"],variants:[{imageUrl:"/older.webp"}]}];
  const next=[{id:"suggestion",role:"inline",anchorText:"Section",afterBlockIdx:9,prompt:"AI replacement",style1:"FA-001",ratio:"4:3"}];
  const before=JSON.stringify({old,next}),result=reconcileArticlePlan(next,old);
  assert.equal(JSON.stringify({old,next}),before);
  assert.equal(result.cards.length,1);const card=result.cards[0];
  for(const key of ["id","imageUrl","status","selectedMediaId","resultEpoch","prompt","style1","ratio","refImages","variants"])
    assert.deepEqual(plain(card[key]),old[0][key]);
  assert.equal(card.afterBlockIdx,9);assert.equal(result.retainedIds.length,0);
});

test("unmatched slots remain visible and two identical contents with distinct IDs remain distinct",()=>{
  const old=[{id:"one",role:"inline",prompt:"Same",imageUrl:"/one.webp"},{id:"two",role:"inline",prompt:"Same",imageUrl:"/two.webp"}];
  const result=reconcileArticlePlan([{id:"new",role:"inline",prompt:"New"}],old);
  assert.deepEqual(plain(result.cards.map(c=>c.id)),["new","one","two"]);
  assert.deepEqual(plain(result.retainedIds),["one","two"]);
});

test("ambiguous old or proposed anchors never guess ownership by array position",()=>{
  const old=[{id:"one",role:"inline",anchorText:"Repeated"},{id:"two",role:"inline",anchorText:"Repeated"}];
  const result=reconcileArticlePlan([{id:"new",role:"inline",anchorText:"Repeated",afterBlockIdx:0}],old);
  assert.equal(result.cards.length,3);assert.equal(result.retainedIds.length,2);
  const reverse=reconcileArticlePlan([{id:"n1",role:"inline",anchorText:"Repeated"},{id:"n2",role:"inline",anchorText:"Repeated"}],old.slice(0,1));
  assert.equal(reverse.cards.length,3);assert.equal(reverse.retainedIds[0],"one");
});

test("single cover and explicit slot IDs keep results while new prompts remain proposals",()=>{
  const cover={id:"cover",role:"cover",imageUrl:"/cover.webp",prompt:"Old prompt",resultEpoch:4};
  const result=reconcileArticlePlan([{id:"new-cover",role:"cover",prompt:"New prompt"}], [cover]);
  assert.equal(result.cards[0].id,"cover");assert.equal(result.cards[0].prompt,"New prompt");
  assert.equal(result.cards[0].imageUrl,"/cover.webp");assert.equal(cover.prompt,"Old prompt");
  const roleChange=reconcileArticlePlan([{id:"cover",role:"inline"}],[cover]);
  assert.equal(roleChange.cards.length,2);assert.notEqual(roleChange.cards[0].id,"cover");
});

class ReviewOverlay {
  set innerHTML(value) {
    this.html=value;this.checks=[...value.matchAll(/data-art-review-check="(\d+)"/g)].map(()=>({checked:true}));
    this.cancel={focus(){}};this.apply={};this.summary={};
  }
  querySelector(selector) {return selector==="[data-review-cancel]"?this.cancel:selector==="[data-review-apply]"?this.apply:this.summary;}
  querySelectorAll(selector) {return selector==="[data-art-review-check]"?this.checks:[...this.checks,this.cancel,this.apply];}
  addEventListener(){} removeEventListener(){} remove(){this.removed=true;}
}
let overlay;
context.document={activeElement:null,createElement(){return overlay=new ReviewOverlay();},body:{appendChild(){}}};
vm.runInContext(fs.readFileSync("demo/assets/article-review.js","utf8"),context);
const {reviewPlan}=context.window.HandrawArticleReview;

test("review shows retained results without mutation; cancelling preserves the original plan",async()=>{
  const old=[{id:"saved",role:"inline",imageUrl:"/saved.webp",prompt:"Keep"}];const before=JSON.stringify(old);
  const pending=reviewPlan([{id:"new",role:"inline",prompt:"Idea"}],{existingCards:old});
  assert.match(overlay.html,/保留原图位/);assert.match(overlay.html,/已保留采用图片/);
  overlay.cancel.onclick();assert.equal((await pending).approved,false);assert.equal(JSON.stringify(old),before);
});

test("explicitly unchecking an unmatched slot removes it only from the approved current plan",async()=>{
  const pending=reviewPlan([{id:"new",role:"inline",prompt:"Idea"}],{existingCards:[{id:"saved",role:"inline",imageUrl:"/saved.webp"}]});
  assert.equal(overlay.checks.length,2);overlay.checks[1].checked=false;overlay.checks[1].onchange();overlay.apply.onclick();
  const result=await pending;assert.equal(result.approved,true);assert.deepEqual(plain(result.cards.map(c=>c.id)),["new"]);
});

test("retained plus proposed slots exceeding the save limit require an explicit smaller selection",async()=>{
  const pending=reviewPlan([{id:"new",role:"inline"}],{existingCards:Array.from({length:200},(_,n)=>({id:"saved_"+n,role:"inline"}))});
  assert.equal(overlay.apply.disabled,true);overlay.checks[0].checked=false;overlay.checks[0].onchange();
  assert.equal(overlay.apply.disabled,false);overlay.cancel.onclick();await pending;
});

test("the current article applies template or approved plans without restoring removed slots or changing other forms",()=>{
  const source=fs.readFileSync("demo/assets/studio-app.js","utf8");
  const start=source.indexOf("  function planUnifiedArticleDraft(");
  const end=source.indexOf("  function renderUnifiedArticleCardsHtml(",start);
  const art={id:"current",cards:[{id:"saved-cover",role:"cover",imageUrl:"/cover.webp"},{id:"saved-inline",role:"inline",anchorText:"Section",imageUrl:"/inline.webp"}]};
  const target={art,planNode:{type:"article_plan",data:art},isActiveCanvas:false};
  const state={graph:{nodes:[{id:"another-form"}]},myArticles:[art]};const before=JSON.stringify(state.graph);
  const plan=new Function("E","CS","Catalog","syncArticleEditorDraftToHistory","resolveArticleTarget","isArticleGenerating","commitArticleTargetChanges",
    source.slice(start,end)+"\nreturn planUnifiedArticleDraft;")(
      context.window.HANDRAW_CANVAS_ENGINE,state,null,()=>{},()=>target,()=>false,()=>{}
    );
  const draft={id:"current",title:"Title",markdown:"# Title\n\nIntro\n\n## Section\n\nParagraph"};
  plan(draft);assert.equal(art.id,"current");assert.equal(art.cards.find(c=>c.id==="saved-inline").imageUrl,"/inline.webp");
  assert.equal(art.cards.find(c=>c.role==="cover").id,"saved-cover");
  plan(draft,{aiCards:[art.cards.find(c=>c.role==="cover")]});
  assert.equal(art.cards.length,1,"An explicit reviewed removal must not be reconciled back in");
  assert.equal(JSON.stringify(state.graph),before);assert.equal(state.myArticles.length,1);
});
