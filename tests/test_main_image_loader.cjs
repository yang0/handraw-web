"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

let now = 0, nextId = 0, imageStarts = 0, geometryReads = 0, documentScans = 0, io, mutation;
const timers = new Map(), rafs = [], windowEvents = {}, documentEvents = {};
class FakeImage {
  constructor(source) {
    this.dataset = { hwSrc: source };
    this.nodeType = 1;
    this.clientWidth = 250;
    this.style = {};
    this.isConnected = true;
    this.complete = false;
    this.naturalWidth = 0;
    this.listeners = {};
    this._classes = new Set();
    this.classList = {
      add: (x) => this._classes.add(x),
      remove: (x) => this._classes.delete(x),
      contains: (x) => this._classes.has(x)
    };
    this.parentElement = null;
  }
  matches(selector) { return selector === "img[data-hw-src]"; }
  querySelectorAll() { return []; }
  getClientRects() { geometryReads++; return [{}]; }
  getBoundingClientRect() {
    geometryReads++;
    return { top: 0, bottom: 200, right: 200, left: 0 };
  }
  addEventListener(name, cb) { this.listeners[name] = cb; }
  removeEventListener(name) { delete this.listeners[name]; }
  getAttribute(name) { return name === "src" ? this._src : null; }
  set src(source) { this._src = source; imageStarts++; }
  get src() { return this._src; }
  emit(name) { if (this.listeners[name]) this.listeners[name](); }
}
class FakeRoot {
  constructor(images) { this.nodeType = 1; this.images = images; this.isConnected = true; }
  matches() { return false; }
  querySelectorAll() { return this.images; }
  querySelector(selector) { return selector === "img[data-hw-src]" ? this.images[0] : null; }
}
class IntersectionObserver {
  constructor(cb) { this.cb = cb; io = this; }
  observe() {}
  show(images) { this.cb(images.map(target => ({ target, isIntersecting: true }))); }
}
class MutationObserver {
  constructor(cb) { mutation = cb; }
  observe() {}
}
function advance(ms) {
  const end = now + ms;
  for (let i = 0; i < 10000; i++) {
    const found = [...timers].filter(([, v]) => v.at <= end)
      .sort((a, b) => a[1].at - b[1].at)[0];
    if (!found) { now = end; return; }
    timers.delete(found[0]); now = found[1].at; found[1].fn();
  }
  throw Error("Infinite timer loop");
}
const first = new FakeImage("/images/a.webp");
const second = new FakeImage("/images/b.webp");
const document = {
  readyState: "loading",
  documentElement: {},
  body: { append() {} },
  addEventListener: (event, cb) => documentEvents[event] = cb,
  querySelectorAll: () => {documentScans++;return [first, second];},
  createElement() { return { style: {}, append() {}, addEventListener() {}, setAttribute() {} }; }
};
const window = {
  devicePixelRatio: 1, innerWidth: 1440, innerHeight: 900,
  addEventListener: (name, cb) => windowEvents[name] = cb
};
const sandbox = {
  window, document, IntersectionObserver, MutationObserver,
  setTimeout(cb, delay) { const id = ++nextId; timers.set(id, {fn: cb, at: now + delay}); return id; },
  clearTimeout(id) { timers.delete(id); },
  requestAnimationFrame(cb) { rafs.push(cb); },
  Date: { now: () => now }
};
const file = path.join(__dirname, "..", "demo", "assets", "image-loader.js");
vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file });
assert.ok(window.HandrawImageLoader);
assert.equal(windowEvents.scroll, undefined, "IO should handle scroll without global rescans");
assert.equal(typeof windowEvents.resize, 'function', "DPR and viewport changes can upgrade visible variants");

documentEvents.DOMContentLoaded();
io.show([first, second]);
advance(40);
assert.equal(imageStarts, 2, "visible images enter bounded request queue");
first.complete = true;
first.naturalWidth = 100;
first.emit("load");
assert.equal(first.dataset.hwLoaded, first.src);
assert.ok(first.classList.contains("hw-img-ready"));
const readsBefore = geometryReads;
const scansBefore = documentScans;

const added = new FakeImage("/images/c.webp");
const container = new FakeRoot([added]);
mutation([{ addedNodes: [container] }]);
assert.equal(rafs.length, 1, "DOM mutations batch into one animation frame");
mutation([{ addedNodes: [container] }]);
assert.equal(rafs.length, 1, "multiple mutations do not trigger additional full scans");
rafs.shift()();
io.show([added]);
advance(40);
assert.equal(imageStarts, 3, "newly appended image loads");
assert.equal(documentScans, scansBefore, "new subtree sizing never rescans the whole document");

added.complete = true;
added.naturalWidth = 100;
added.emit("load");
const cached = new FakeImage("/images/c.webp");
window.HandrawImageLoader.scan(cached);
io.show([cached]);
advance(40);
assert.equal(imageStarts, 4);
assert.ok(!cached.classList.contains("hw-img-loading"), "a previously decoded URL must not replay skeleton shimmer");
console.log("Main image-loader incremental scan, IO, and decoded image tests passed");
