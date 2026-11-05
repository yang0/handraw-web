"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let now = 0, nextTimer = 0, io, mutation;
const timers = new Map(), documentEvents = {};
const previews = [], fullRequests = [];
function classList(initial = []) {
  const classes = new Set(initial);
  return { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x) };
}
function style(initial = {}) {
  return {
    ...initial,
    setProperty(key, value) { this[key] = value; },
    getPropertyValue(key) { return this[key] || ""; }
  };
}
class Media {
  constructor(ratio = "3 / 4") {
    this.classList = classList(["hw-progressive-media"]);
    this.dataset = { hwRefineRatio: "true" };
    this.style = style({ aspectRatio: ratio });
    this.clientWidth = 240;
  }
}
class ImageElement {
  constructor(url, box) {
    this.nodeType = 1; this.tagName = "IMG";
    this.dataset = { hwSrc: url }; this.parentElement = box;
    this.classList = classList(); this.style = style();
    this.clientWidth = 240; this.isConnected = true;
    this.complete = false; this.naturalWidth = 0; this.naturalHeight = 0;
    this.listeners = new Map();
  }
  matches(selector) { return selector === "img[data-hw-src]"; }
  querySelectorAll() { return []; }
  getAttribute(k) { return k === "src" ? this._src : null; }
  addEventListener(k, cb) { this.listeners.set(k, cb); }
  removeEventListener(k) { this.listeners.delete(k); }
  set src(v) { this._src = v; fullRequests.push(v); }
  get src() { return this._src || ""; }
  emit(event) { this.listeners.get(event)?.(); }
}
class PreviewImage {
  constructor() {
    this.naturalWidth = 48; this.naturalHeight = 32;
    previews.push(this);
  }
  set src(v) { this._src = v; }
  get src() { return this._src; }
  finish(w=48,h=32) { this.naturalWidth=w; this.naturalHeight=h; this.onload(); }
  fail() { this.onerror(); }
}
class IntersectionObserver {
  constructor(cb) { this.cb=cb; io=this; }
  observe() {}
  show(images) { this.cb(images.map(target => ({target,isIntersecting:true}))); }
}
class MutationObserver {
  constructor(cb) { mutation=cb; }
  observe() {}
}
function advance(ms) {
  const end=now+ms;
  for (let n=0; n<1000; n++) {
    const entry=[...timers].filter(([,v])=>v.at<=end)
      .sort((a,b)=>a[1].at-b[1].at)[0];
    if (!entry) { now=end;return; }
    now=entry[1].at; timers.delete(entry[0]); entry[1].cb();
  }
  throw Error("unexpected timer recursion");
}

const mainBox = new Media();
const first = new ImageElement("/images/sample.webp", mainBox);
const document = {
  readyState:"loading", documentElement:{}, body:{append(){}},
  querySelectorAll() { return [first]; },
  addEventListener(k,cb) { documentEvents[k]=cb; }
};
const window = { devicePixelRatio:1, innerHeight:900, innerWidth:1400, addEventListener() {} };
const sandbox = { document, window, Image:PreviewImage, IntersectionObserver, MutationObserver,
  Date:{now:()=>now},
  setTimeout(cb,ms) { const id=++nextTimer; timers.set(id,{cb,at:now+ms});return id; },
  clearTimeout(id) {timers.delete(id);}
};
const jsFile = path.join(__dirname,"..","demo","assets","image-loader.js");
vm.runInNewContext(fs.readFileSync(jsFile,"utf8"),sandbox,{filename:jsFile});
documentEvents.DOMContentLoaded();

assert.ok(mainBox.style["--hw-placeholder-color"],"placeholder color appears before network");
assert.equal(mainBox.style.aspectRatio,"3 / 4","reserve expected picture height immediately");
assert.ok(!mainBox.classList.contains("hw-preview-ready"));

io.show([first]);
assert.equal(previews.length,1);
assert.equal(previews[0].src,"/images/sample.webp?w=48");
assert.equal(fullRequests.length,1,"full image requests are not blocked on blur");
assert.ok(!first.classList.contains("hw-img-ready"));
previews[0].finish(48,32);
assert.equal(mainBox.style.aspectRatio,"48 / 32","preview dimensions correct geometry before clear image");
assert.equal(mainBox.style["--hw-preview-image"],'url("/images/sample.webp?w=48")');
assert.ok(mainBox.classList.contains("hw-preview-ready"));

first.complete = true; first.naturalWidth=1200; first.naturalHeight=800; first.emit("load");
assert.equal(first.classList.contains("hw-img-ready"),true);
assert.equal(mainBox.style.aspectRatio,"48 / 32","matching dimensions avoid extra relayout");

// A repeat card reuses the ready preview rather than downloading it again.
const repeatBox = new Media();
const repeat = new ImageElement("/images/sample.webp",repeatBox);
window.HandrawImageLoader.scan(repeat); io.show([repeat]);
advance(30);
assert.equal(previews.length,1,"same thumbnail URL should be reused");
assert.ok(repeatBox.classList.contains("hw-preview-ready"));

// Remote images must not receive an unsupported thumbnail query parameter.
const externalBox=new Media("4 / 5");
const external=new ImageElement("https://cdn.example.org/photo.jpg",externalBox);
window.HandrawImageLoader.scan(external); io.show([external]);
advance(30);
assert.equal(previews.length,1,"no image-width probing on unknown third-party CDNs");
assert.ok(fullRequests.some(x=>x==="https://cdn.example.org/photo.jpg"));
assert.ok(externalBox.style["--hw-placeholder-color"],"remote gets colored placeholder");

// A failed tiny preview does not mark a real full-size image as broken.
const failBox=new Media();
const failImg=new ImageElement("/generated/slow.png",failBox);
window.HandrawImageLoader.scan(failImg); io.show([failImg]);
advance(30);
assert.equal(previews.length,2);
previews[1].fail();
assert.ok(!failImg.dataset.hwFailed);
assert.ok(!failBox.classList.contains("hw-preview-ready"));

// CSS contract: opt-in image starts transparent and a crisp image fades in.
const css=fs.readFileSync(path.join(__dirname,"..","demo","assets","mixed-feed.css"),"utf8");
assert.match(css,/\.hw-progressive-media\.hw-preview-ready::before\s*\{\s*opacity:\s*1/);
assert.match(css,/\.hw-progressive-media > img\[data-hw-src\]\.hw-img-ready\s*\{\s*opacity:\s*1/);
assert.match(css,/prefers-reduced-motion:\s*reduce/);
console.log("Progressive feed: color, 48px blurred preview, true image, cache reuse, remote fallback passed");
