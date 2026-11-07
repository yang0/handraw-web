"use strict";
/* Owner-only Skill gallery: real mount/filter/upload/delete wiring, no public URL. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const main = fs.readFileSync("demo/assets/main-app.js", "utf8");
const source = fs.readFileSync("demo/assets/cloud-center.js", "utf8");
const theme = fs.readFileSync("demo/assets/theme.css", "utf8");
assert.match(theme, /\.hw-personal-gallery-grid\.is-empty\s*\{\s*column-count:\s*1\s*;/, "Empty gallery must be one column");
assert.match(theme, /\.hw-personal-gallery-empty\s*\{[^}]*width:\s*100%/, "Empty gallery card must fill the gallery width");
assert.match(source, /cards\.classList\.toggle\("is-empty", visible\.length === 0\)/, "Empty state must toggle masonry off");
assert.match(main, /label: "我的图库"/, "Creative Resources must contain My Gallery");
assert.match(main, /type === "gallery" && isMe/, "Gallery is only shown to its owner");
assert.match(main, /if \(isMe && UI\.profileTab === "resources" && UI\.profileResourceFilter === "gallery"\)/);
assert.match(source, /mountGallery\(container, api\)/);
assert.match(source, /api\/library\/assets\?limit=100/);
assert.match(source, /pendingTasksBySlot|private user-owned assets/);

class Element {
  constructor() {
    this.innerHTML = "";
    this.hidden = false;
    this.disabled = false;
    this.isConnected = true;
    this.dataset = {};
    this.style = {};
    this.callbacks = {};
    this.attributes = {};
    this.classes = new Set();
    this.classList = {toggle: (name, force) => {
      const enabled = force === undefined ? !this.classes.has(name) : force;
      if (enabled) this.classes.add(name); else this.classes.delete(name);
    }};
  }
  addEventListener(name, fn) { this.callbacks[name] = fn; }
  focus() {}
  setAttribute(name, val) { this.attributes[name] = val; }
}
const cards = new Element(), more = new Element(), file = new Element(), status = new Element(), retry = new Element();
const form = new Element(), uploadName = new Element(), uploadCategory = new Element();
const uploadSubmit = new Element(), uploadCancel = new Element(), selectedFile = new Element();
form.hidden = true;
retry.hidden = true;
const categories = ["all", "characters", "props", "scenes", "other"].map(cat => {
  const el = new Element(); el.dataset.galleryCategory = cat; return el;
});
const elements = new Map([
  ["[data-gallery-cards]", cards], ["[data-gallery-more]", more],
  ["[data-gallery-file]", file], ["[data-gallery-message]", status],
  ["[data-gallery-retry]", retry],
  ["[data-gallery-upload-form]", form], ["[data-gallery-name]", uploadName],
  ["[data-gallery-upload-category]", uploadCategory],
  ["[data-gallery-selected-file]", selectedFile],
  ["[data-gallery-submit]", uploadSubmit], ["[data-gallery-cancel]", uploadCancel]
]);
const root = new Element();
root.querySelector = selector => elements.get(selector) || null;
root.querySelectorAll = selector => selector === "[data-gallery-category]" ? categories : [];
const uid = "11111111-1111-4111-8111-111111111111";
const anotherUid = "22222222-2222-4222-8222-222222222222";
const uploads = [ {uid, revision:1, name:"私家角色",
  imageUrl:"/api/library/assets/" + uid + "/image",
  publicUrl:"/uploads/should-not-be-used.webp", cat:"characters", origin:"skill"} ];
const calls = [];
let failNextPut = false;
async function api(path, init) {
  calls.push({path, init});
  if (path.startsWith("/api/library/assets?")) {
    return {ok:true, items:uploads.slice(), nextCursor:null, hasMore:false};
  }
  if (init?.method === "DELETE") {
    const i = uploads.findIndex(item => path.includes(item.uid));
    if (i >= 0) uploads.splice(i,1);
    return {ok:true};
  }
  if (init?.method === "PUT") {
    if (failNextPut) {
      failNextPut = false;
      const err = new Error("服务暂时出错（问题编号：60c109fd85ff4b4ab20a7084bc4c1560）");
      err.status = 500;
      err.code = "internal_error";
      throw err;
    }
    uploads.push({
      uid:anotherUid, revision:1, name:init.body.name, cat:init.body.cat, origin:"web",
      imageUrl:"/api/library/assets/" + anotherUid + "/image"
    });
    return {ok:true};
  }
  throw new Error("Unexpected API call: " + path);
}
class FakeReader {
  readAsDataURL() {
    this.result = "data:image/png;base64,AA==";
    this.onload();
  }
}
const win = {confirm:()=>true, crypto:{randomUUID:()=>anotherUid}};
const ctx = {window:win, document:{}, FileReader:FakeReader, Map, Object, Array, String, console};
vm.runInNewContext(source,ctx);
(async()=>{
  await win.HandrawCloudCenter.mountGallery(root,api);
  assert.match(cards.innerHTML,/私家角色/);
  assert.match(cards.innerHTML,/Skill 同步/);
  assert.match(cards.innerHTML,/\/api\/library\/assets\/11111111-1111-4111-8111-111111111111\/image/);
  assert.doesNotMatch(cards.innerHTML,/should-not-be-used\.webp/);
  assert.equal(status.textContent,"已加载 1 张私人素材");
  assert.equal(cards.classes.has("is-empty"), false, "Loaded gallery keeps masonry enabled");

  categories.find(x=>x.dataset.galleryCategory==="props").callbacks.click();
  assert.match(cards.innerHTML,/此分类暂无素材/);
  assert.equal(cards.classes.has("is-empty"), true, "Empty category uses one full-width panel");
  categories.find(x=>x.dataset.galleryCategory==="characters").callbacks.click();
  assert.match(cards.innerHTML,/私家角色/);
  assert.equal(cards.classes.has("is-empty"), false, "Returning to populated category restores masonry");

  await cards.callbacks.click({target:{closest:()=>({dataset:{galleryDelete:uid}})}});
  assert.equal(uploads.length,0);
  assert.match(cards.innerHTML,/图库暂无图片/);
  assert.equal(cards.classes.has("is-empty"), true, "Deleting final item switches to single empty panel");
  assert.ok(calls.some(c=>c.init?.method==="DELETE" && c.path.includes("baseRevision=1")));

  file.files=[{name:"新人设.png",size:120,type:"image/png"}];
  await file.callbacks.change();
  assert.equal(uploads.length,0,"Selecting a file must not immediately upload");
  assert.equal(form.hidden,false,"The review form opens after file selection");
  assert.equal(uploadName.value,"新人设","Suggest original filename without extension");
  assert.equal(uploadCategory.value,"characters","Current filter is only a preselection");
  uploadName.value = "手绘少女原型";
  uploadCategory.value = "props";
  uploadName.value = " ";
  await form.callbacks.submit({preventDefault(){}});
  assert.equal(uploads.length,0,"Blank names must not call API");
  assert.match(status.textContent,/请填写/);
  uploadName.value = "手绘少女原型";
  failNextPut = true;
  await form.callbacks.submit({preventDefault(){}});
  assert.equal(uploads.length, 0, "Failed upload must not add an empty card");
  assert.equal(retry.hidden, false, "Retry must be available after a server failure");
  assert.equal(form.hidden,false,"Failure must preserve the edit form");
  assert.equal(uploadName.value,"手绘少女原型");
  assert.equal(uploadCategory.value,"props");
  assert.match(status.textContent, /服务器保存失败/);
  assert.match(status.textContent, /60c109fd85ff4b4ab20a7084bc4c1560/);
  const failedPut = calls.filter(c => c.init?.method === "PUT").at(-1);
  await retry.callbacks.click();
  const successfulPut = calls.filter(c => c.init?.method === "PUT").at(-1);
  assert.equal(failedPut.path, successfulPut.path, "Retry must reuse the same asset UID");
  assert.equal(retry.hidden, true, "Retry must hide after a successful upload");
  assert.equal(uploads.length,1);
  assert.equal(uploads[0].name,"手绘少女原型");
  assert.ok(calls.some(c=>c.init?.method==="PUT" && c.init.body.cat==="props"));
  assert.match(cards.innerHTML,/手绘少女原型/);
  assert.equal(form.hidden,true,"Successful upload closes review form");
  assert.equal(cards.classes.has("is-empty"), false, "Uploading restores masonry mode");
  console.log("profile gallery: owner-scoped API, private image URLs, categories, add/delete OK");
})().catch(err=>{console.error(err);process.exitCode=1;});
