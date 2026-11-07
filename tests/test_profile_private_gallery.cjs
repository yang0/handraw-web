"use strict";
/* Owner-only Skill gallery: real mount/filter/upload/delete wiring, no public URL. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const main = fs.readFileSync("demo/assets/main-app.js", "utf8");
const source = fs.readFileSync("demo/assets/cloud-center.js", "utf8");
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
    this.classList = {toggle() {}};
  }
  addEventListener(name, fn) { this.callbacks[name] = fn; }
  setAttribute(name, val) { this.attributes[name] = val; }
}
const cards = new Element(), more = new Element(), file = new Element(), status = new Element();
const categories = ["all", "characters", "props", "scenes", "other"].map(cat => {
  const el = new Element(); el.dataset.galleryCategory = cat; return el;
});
const elements = new Map([
  ["[data-gallery-cards]", cards], ["[data-gallery-more]", more],
  ["[data-gallery-file]", file], ["[data-gallery-message]", status]
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

  categories.find(x=>x.dataset.galleryCategory==="props").callbacks.click();
  assert.match(cards.innerHTML,/此分类暂无素材/);
  categories.find(x=>x.dataset.galleryCategory==="characters").callbacks.click();
  assert.match(cards.innerHTML,/私家角色/);

  await cards.callbacks.click({target:{closest:()=>({dataset:{galleryDelete:uid}})}});
  assert.equal(uploads.length,0);
  assert.ok(calls.some(c=>c.init?.method==="DELETE" && c.path.includes("baseRevision=1")));

  file.files=[{name:"新人设.png",size:120,type:"image/png"}];
  await file.callbacks.change();
  assert.equal(uploads.length,1);
  assert.equal(uploads[0].name,"新人设");
  assert.ok(calls.some(c=>c.init?.method==="PUT" && c.init.body.cat==="characters"));
  assert.match(cards.innerHTML,/新人设/);
  console.log("profile gallery: owner-scoped API, private image URLs, categories, add/delete OK");
})().catch(err=>{console.error(err);process.exitCode=1;});
