"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("#167 home search preserves input DOM during Pinyin composition and results filtering", () => {
  const shared = {
    App: { state: { works: [
      {id:"a",title:"猫咪插画",images:["/cat.webp"],status:"published",author:"creator"},
      {id:"b",title:"海边风景",images:["/sea.webp"],status:"published",author:"creator"}
    ], topics:[], discussions:{} }, styles:[], layouts:[] },
    esc: value => String(value || ""),
    channelUrl: (name,params) => "/" + name + "/" + (params?.id || ""),
    resourceLabel: r => r.name || r.id
  };
  let queued = null;
  const inp = {value:"",isConnected:true};
  const resultPane = {innerHTML:""};
  let fullRenderCount = 0;
  let resultRenderCount = 0;
  Object.defineProperty(resultPane,"innerHTML",{
    get(){return this.markup || "";},
    set(html){this.markup=html;resultRenderCount++;}
  });
  const root = {
    set innerHTML(markup){this.markup=markup;fullRenderCount++;},
    get innerHTML(){return this.markup || "";},
    querySelectorAll(){return [];},
    querySelector(selector){
      if(selector === "#hw-mf-search")return inp;
      if(selector === ".hw-mf-results")return resultPane;
      return null;
    },
    addEventListener(){}
  };
  const sandbox = {window:{
    HANDRAW_SHARED:shared,
    setTimeout(cb){queued=cb;return 1;},
    clearTimeout(){queued=null;}
  }};
  vm.runInNewContext(fs.readFileSync("demo/assets/mixed-feed.js","utf8"),sandbox);
  sandbox.window.HandrawMixedFeed.render(root);
  assert.equal(fullRenderCount,1);
  const sameInput = root.querySelector("#hw-mf-search");
  inp.oncompositionstart();
  inp.value="mao";
  inp.oninput({isComposing:true});
  assert.equal(queued,null,"Pinyin composition must never start search");
  inp.value="猫";
  inp.oncompositionend();
  assert.equal(typeof queued,"function");
  queued();
  assert.equal(fullRenderCount,1,"search must not replace input or page shell");
  assert.equal(root.querySelector("#hw-mf-search"),sameInput);
  assert.equal(resultRenderCount,1,"only results redraw after committing Chinese text");
  assert.match(resultPane.innerHTML,/猫咪插画/);
  assert.doesNotMatch(resultPane.innerHTML,/海边风景/);

  inp.value="海";
  inp.oninput({isComposing:false});
  assert.equal(typeof queued,"function");
  queued();
  assert.equal(fullRenderCount,1);
  assert.equal(resultRenderCount,2);
  assert.match(resultPane.innerHTML,/海边风景/);
  assert.doesNotMatch(resultPane.innerHTML,/猫咪插画/);
});
