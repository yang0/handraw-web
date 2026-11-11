"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const source = fs.readFileSync("demo/assets/forum-work-post.js", "utf8");
const window = { HANDRAW_SHARED: {
  esc: value => String(value == null ? "" : value),
  resourceLabel: x => x.name,
  filterDisplayPrompt: x => x,
  channelUrl: () => "/studio/",
  toast() {}
}};
new Function("window", source)(window);
const FWP = window.HandrawForumWork;
function model(imageAssets, masked = false) {
  return FWP.fromTopic(
    {id:"topic", workId:"work", title:"系列"},
    [{id:"work",title:"系列",images:["/first.webp","/second.webp","/third.webp"],
      prompt:"整套母题",subject:"整套母题",promptMasked:masked,imageAssets}],
    {},true
  );
}

test("#158 selected media owns its own prompt, not the work-level mother theme", () => {
  const m = model([
    {url:"/first.webp",styles:[],layout:"",scope:"missing",prompt:"第一张的完整提示词",promptScope:"image"},
    {url:"/second.webp",styles:[],layout:"",scope:"missing",prompt:"第二张的完整提示词",promptScope:"image"},
    {url:"/third.webp",styles:[],layout:"",scope:"missing",prompt:"第三张的完整提示词",promptScope:"image"}
  ]);
  for (const [i,url] of m.images.entries()) {
    assert.equal(FWP.promptForImage(m,url),["第一张的完整提示词","第二张的完整提示词","第三张的完整提示词"][i]);
  }
  assert.match(FWP.render(m),/第一张的完整提示词/);
  assert.doesNotMatch(FWP.render(m),/第三张的完整提示词/);
});
test("#158 missing per-image prompt never falls back to unrelated group prompt", () => {
  const m = model([{url:"/first.webp",prompt:"首图",promptScope:"image"}]);
  assert.equal(FWP.promptForImage(m,"/third.webp"),"");
  assert.match(FWP.render({...m,coverUrl:"/third.webp"}),/当前图片未公开独立提示词/);
});
test("#158 masked work must not show per-image prompts", () => {
  const m = model([{url:"/first.webp",prompt:"绝不暴露",promptScope:"image"}],true);
  assert.equal(FWP.promptForImage(m,"/first.webp"),"");
  assert.doesNotMatch(FWP.render(m),/绝不暴露/);
});
