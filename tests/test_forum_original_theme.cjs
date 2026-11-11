"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const win = { HANDRAW_SHARED: {
  esc: value => String(value == null ? "" : value),
  resourceLabel: item => item.name,
  filterDisplayPrompt: value => value,
  channelUrl: () => "/studio/",
  toast() {}
}};
new Function("window", fs.readFileSync("demo/assets/forum-work-post.js", "utf8"))(win);
const FWP = win.HandrawForumWork;
test("#161 forum selected image shows original theme textbox, not expanded generation prompt", () => {
  const m = FWP.fromTopic({id:"topic",workId:"work"},
    [{id:"work",title:"三张图",images:["/one.webp","/two.webp","/three.webp"],
      subject:"母题", prompt:"完整模型提示词（不能显示）",
      imageAssets:[
        {url:"/one.webp",prompt:"图1主题文本",promptScope:"image"},
        {url:"/two.webp",prompt:"图2主题文本",promptScope:"image"},
        {url:"/three.webp",prompt:"图3主题文本",promptScope:"image"}
      ]}], {}, true);
  assert.equal(FWP.promptForImage(m,"/one.webp"),"图1主题文本");
  assert.equal(FWP.promptForImage(m,"/two.webp"),"图2主题文本");
  assert.equal(FWP.promptForImage(m,"/three.webp"),"图3主题文本");
  assert.doesNotMatch(FWP.render(m),/完整模型提示词/);
  assert.match(FWP.render(m),/图1主题文本/);
});
test("#161 never guess theme from composed prompt if image lacks theme metadata", () => {
  const m = {source:"work",images:["/one.webp","/two.webp"],prompt:"完整合成提示词",
    imageAssets:[{url:"/one.webp",prompt:"图1主题",promptScope:"image"}],locked:false};
  assert.equal(FWP.promptForImage(m,"/two.webp"),"");
  assert.match(FWP.render({...m,title:"系列",coverUrl:"/two.webp"}),/当前图片未记录独立主题文本/);
});
test("#161 generated request stores theme separately from cloudPrompt", () => {
  const app = fs.readFileSync("demo/assets/studio-app.js","utf8");
  assert.match(app,/recipeSnapshot:\s*\{\s*\.\.\.\(sp\.recipeSnapshot \|\| \{\}\),\s*theme: sp\.theme \|\| ""/);
  assert.match(app,/prompt: cloudPrompt/);
});
