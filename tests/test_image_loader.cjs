"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let now = 0;
let nextTimer = 0;
let io;
let mutation;
const scheduled = new Map();
const starts = [];
const images = [];
const notices = [];
class Element {
  constructor() {
    this.dataset = {};
    this.listeners = new Map();
    this.children = [];
    this.style = {};
    this.isConnected = true;
    this.visible = true;
  }
  setAttribute() {}
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(callback);
  }
  removeEventListener(name, callback) {
    this.listeners.get(name)?.delete(callback);
  }
  append(...children) { this.children.push(...children); }
  remove() { this.isConnected = false; }
  getClientRects() { return this.visible ? [{}] : []; }
  getBoundingClientRect() {
    return { top: 10, bottom: 100, left: 10, right: 100 };
  }
  set src(value) { this._src = value; starts.push({ image: this, value, at: now }); }
  get src() { return this._src || ""; }
  emit(name) { for (const fn of [...(this.listeners.get(name) || [])]) fn(); }
}
function advance(ms) {
  const end = now + ms;
  for (let i = 0; i < 10000; i++) {
    const next = [...scheduled].filter(([, v]) => v.at <= end).sort((a,b) => a[1].at-b[1].at)[0];
    if (!next) { now = end; return; }
    scheduled.delete(next[0]);
    now = next[1].at;
    next[1].fn();
  }
  throw new Error("Unexpected timer loop");
}
const document = {
  body: { append(node) { notices.push(node); } },
  documentElement: {},
  createElement() { return new Element(); },
  querySelectorAll() { return images; },
  addEventListener() {},
};
class IntersectionObserver {
  constructor(callback) { this.callback = callback; io = this; }
  observe() {}
  unobserve() {}
  show(nodes) { this.callback(nodes.map(target => ({target, isIntersecting:true}))); }
}
class MutationObserver {
  constructor(callback) { mutation = callback; }
  observe() {}
}
for (let i=0; i<6; i++) {
  const image = new Element(); image.dataset.hwSrc = `/image-${i}.webp`;
  images.push(image);
}
images[5].visible = false;
const window = { innerWidth:1440, innerHeight:900, addEventListener() {} };
vm.runInNewContext(fs.readFileSync("plugin/public/image-loader.js", "utf8"), {
  window, document, IntersectionObserver, MutationObserver,
  Date: { now: () => now },
  setTimeout(fn, delay) { const id=++nextTimer; scheduled.set(id,{fn,at:now+delay}); return id; },
  clearTimeout(id) { scheduled.delete(id); },
});

io.show(images);
assert.equal(starts.length,1);
advance(600);
assert.equal(starts.length,2);
advance(3000);
assert.equal(starts.length,2,"At most two unfinished image requests");
images[0].emit("load");
assert.equal(starts.length,3);
images[1].emit("error");
const failedAt = now;
advance(9999);
assert.equal(starts.length,3,"An error pauses new requests for ten seconds");
images[2].emit("load");
advance(1);
assert.equal(starts.length,4);
assert.equal(starts[3].at,failedAt+10000);
images[3].emit("load"); advance(600);
assert.equal(starts.length,5);
images[4].emit("load"); advance(20000);
assert.equal(starts.length,5,"Failed and hidden images are not retried automatically");
const retryButton = notices[0].children[1];
retryButton.emit("click");
assert.equal(starts.length,6);
assert.equal(starts[5].image,images[1]);
images[1].emit("load");
images[5].visible = true; io.show([images[5]]); advance(600);
assert.equal(starts.length,7,"Images load when revealed by scrolling or filtering");
images[5].emit("load");
mutation(); io.show(images); advance(2000);
assert.equal(starts.length,7,"Completed images are not requested again");
for(let i=1;i<starts.length;i++) assert.ok(starts[i].at-starts[i-1].at>=600);
console.log("Image queue: concurrency, pacing, cooldown, explicit retry and visibility passed");
