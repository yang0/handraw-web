"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag, attrs = {}) {
    this.tag = tag;
    this.attrs = attrs;
    this.children = [];
    this.listeners = new Map();
    this.files = [];
    this.value = attrs.value || "";
    this.open = true;
  }
  append(...children) { this.children.push(...children.flat().filter(x => x != null)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(name, fn) { this.listeners.set(name, fn); }
  removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name); }
  async emit(name, event = {}) { return this.listeners.get(name)?.(event); }
  querySelector(tag) { return this.querySelectorAll(tag)[0]; }
  querySelectorAll(tag) {
    return this.children.filter(x => x instanceof Element).flatMap(x => [
      ...(x.tag === tag ? [x] : []), ...x.querySelectorAll(tag),
    ]);
  }
  close() { this.open = false; this.emit("close"); }
}
const el = (tag, attrs, ...children) => {
  const node = new Element(tag, attrs);
  node.append(...children);
  return node;
};
const dialog = new Element("dialog");
const objectUrls = new Map();
const revoked = [];
const uploaded = [];
const posted = [];
let sequence = 0;
let active;
const window = { addEventListener() {} };
vm.runInNewContext(fs.readFileSync("plugin/public/market.js", "utf8"), {
  window, document: { createElement: tag => new Element(tag) }, FormData,
  URL: {
    createObjectURL(file) { const url = `blob:preview-${++sequence}`; objectUrls.set(url, file); return url; },
    revokeObjectURL(url) { revoked.push(url); objectUrls.delete(url); },
  },
  fetch: async (url, options) => {
    if (url === "/session/csrf.json") return { json: async () => ({ csrf: "test" }) };
    assert.equal(url, "/uploads.json");
    uploaded.push(options.body.get("file"));
    return { ok: true, json: async () => ({ url: "/uploads/preview.png" }) };
  },
});
const market = window.HandrawMarket({
  state: { boot: { user: { id: 1 }, participant: true, fixed_price_max: 100 } },
  el, button: text => el("button", {}, text), tell() {}, navigate() {}, card() {},
  select: () => dialog,
  modal(title, ...nodes) { active = nodes[0]; dialog.open = true; },
  api: async (path, options) => {
    if (path === "/entries") {
      posted.push(JSON.parse(options.body).entry);
      return { id: "created" };
    }
    assert.equal(path, "/entries/created");
    return { id: "created", kind: "work", title: "作品", author: { id: 1 }, assets: [], license: "测试授权", market: false };
  },
});

(async () => {
  const generated = new File(["generated-image"], "generated.png", { type: "image/png" });
  const replacement = new File(["replacement-image"], "replacement.png", { type: "image/png" });
  await market.share("work", { title: "窗台晒太阳的猫咪", prompt: "完整的生成提示词，保留画风与主题。", image: generated,
    parameters: { ratio: "1:1" }, assets: [{ ref: "official:FA-001", kind: "style", role: "style" }] });
  const form = active;
  const cover = form.querySelectorAll("input").find(x => x.attrs.name === "cover");
  const preview = () => form.querySelectorAll("img")[0];
  assert.equal(objectUrls.get(preview().src), generated, "Generated attachment has a real image preview");
  assert.equal(uploaded.length, 0, "Preview must not publish or upload a private image");
  assert.equal(cover.attrs.required, false, "Generated attachment does not require choosing the file again");
  const originalUrl = preview().src;
  cover.files = [replacement];
  await cover.emit("change");
  assert.equal(objectUrls.get(preview().src), replacement, "Replacement updates the visible preview");
  assert.ok(revoked.includes(originalUrl));
  cover.files = [];
  await cover.emit("change");
  assert.equal(objectUrls.get(preview().src), generated, "Cancelling replacement preserves the generated attachment");
  await dialog.emit("close"); // Asset picker can close and reopen the same dialog before the event arrives.
  assert.equal(objectUrls.size, 1, "A reopened association dialog retains the draft preview");
  await form.emit("submit", { preventDefault() {} });
  assert.equal(uploaded[0].name, generated.name);
  assert.equal(await uploaded[0].text(), await generated.text());
  assert.equal(posted[0].cover_url, "/uploads/preview.png");
  assert.equal(posted[0].content.parameters.ratio, "1:1");
  assert.equal(posted[0].assets[0].ref, "official:FA-001");
  assert.equal(objectUrls.size, 0, "Closing the share form releases the local preview URL");
  console.log("Share preview: generated file, replacement, cancellation, submission and URL cleanup passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
