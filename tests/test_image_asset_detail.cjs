/* Issue #97: V3 multi-image detail metadata must follow the selected media. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.resolve(__dirname, "../demo/assets/forum-work-post.js"), "utf8");

const win = {
  HANDRAW_SHARED: {
    esc: (value) => String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
    resourceLabel: (item) => item.name,
    filterDisplayPrompt: (value) => value,
    channelUrl: (_channel, params) => "/studio/?" + new URLSearchParams(params).toString(),
    toast: () => {},
  },
};
new Function("window", source)(win);
const FWP = win.HandrawForumWork;
const makeModel = (imageAssets) => FWP.fromTopic(
  { id: "topic_1", workId: "work_1", title: "Multi-image detail" },
  [{
    id: "work_1", title: "Multi-image detail", subject: "two distinct images",
    prompt: "two distinct images", styles: ["FA-011"], layout: "SC-001",
    images: ["/img/first.webp", "/img/second.webp"],
    imageAssets,
  }],
  {
    "FA-011": { id: "FA-011", kind: "style", name: "First Style" },
    "FB-022": { id: "FB-022", kind: "style", name: "Second Style" },
    "SC-001": { id: "SC-001", kind: "layout", name: "First Layout" },
    "IG-006": { id: "IG-006", kind: "layout", name: "Second Layout" },
  },
  true
);

function clickSecond(model) {
  const listeners = [];
  const imageAttrs = { src: "/img/first.webp", "data-hw-src": "/img/first.webp" };
  const main = {
    addEventListener() {},
    getAttribute(key) { return imageAttrs[key] || ""; },
    setAttribute(key, value) { imageAttrs[key] = value; },
  };
  const assets = { innerHTML: "" };
  const download = { setAttribute(key, value) { this[key] = value; } };
  const fork = { setAttribute(key, value) { this[key] = value; } };
  const stage = { querySelector(key) { return key === ".fwp-download-btn" ? download : null; } };
  const thumbs = ["/img/first.webp", "/img/second.webp"].map((url, index) => ({
    getAttribute(key) { return key === "data-fwp-src" ? url : null; },
    setAttribute() {},
    classList: { toggle() {} },
    addEventListener(event, callback) { if (event === "click") listeners[index] = callback; },
  }));
  const root = {
    querySelector(key) {
      return {
        ".fwp": root,
        "[data-fwp-stage]": stage,
        "[data-fwp-main]": main,
        "[data-fwp-assets]": assets,
        "[data-fwp-fork]": fork,
      }[key] || null;
    },
    querySelectorAll(key) { return key === ".fwp-thumb" ? thumbs : []; },
  };
  FWP.bind(root, model);
  assert.equal(typeof listeners[1], "function");
  listeners[1]();
  return { html: assets.innerHTML, src: imageAttrs.src, download: download.href, fork: fork.href };
}

const model = makeModel([
  { url: "/img/first.webp", styles: ["FA-011"], layout: "SC-001", scope: "image" },
  { url: "/img/second.webp", styles: ["FB-022"], layout: "IG-006", scope: "image" },
]);
const html = FWP.render(model);
assert.match(html, /FA-011/);
assert.match(html, /SC-001/);
assert.doesNotMatch(html, /FB-022/);
assert.doesNotMatch(html, /全部画风|全部图型/);
assert.match(html, /fork=work_1&amp;image=0/);
assert.match(html, /href="\/t\/SC-001" target="_blank" rel="noopener noreferrer"/);
const switched = clickSecond(model);
assert.equal(switched.src, "/img/second.webp");
assert.equal(switched.download, "/img/second.webp");
assert.match(switched.fork, /fork=work_1&image=1/);
assert.match(switched.html, /FB-022/);
assert.match(switched.html, /IG-006/);
assert.doesNotMatch(switched.html, /FA-011|SC-001/);

const partial = makeModel([
  { url: "/img/first.webp", styles: ["FA-011"], layout: "SC-001", scope: "image" },
  { url: "/img/second.webp", styles: [], layout: "", scope: "missing" },
]);
const partialSwitch = clickSecond(partial);
assert.match(partialSwitch.html, /当前图片未记录/);
assert.doesNotMatch(partialSwitch.html, /FA-011|SC-001/);

const onlyWorkMetadata = makeModel(undefined);
assert.match(FWP.render(onlyWorkMetadata), /仅保存了整组作品的参数/);
assert.match(clickSecond(onlyWorkMetadata).html, /仅保存了整组作品的参数/);
console.log("Issue #97 image asset detail tests passed.");
