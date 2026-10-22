"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
class Element {
  constructor(tag, attrs = {}) {
    this.tag = tag;
    this.attrs = attrs;
    this.children = [];
  }
  append(...nodes) {
    this.children.push(...nodes.flat().filter((n) => n != null));
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
}
const el = (tag, attrs, ...nodes) => {
  const n = new Element(tag, attrs);
  n.append(...nodes);
  return n;
};
const content = el("div");
const window = { addEventListener() {} };
let modalCount = 0,
  messages = [],
  chooser;
const modal = (_title, ...nodes) => {
  modalCount++;
  chooser = nodes;
};
vm.runInNewContext(fs.readFileSync("plugin/public/discover.js", "utf8"), {
  window,
  URL,
  URLSearchParams,
  sessionStorage: { getItem: () => null, removeItem() {} },
  document: {
    querySelector: (q) =>
      q.startsWith("script")
        ? { src: "http://localhost/studio/assets/discover.js" }
        : content,
  },
});
const discover = window.HandrawDiscover({
  state: {
    boot: {
      editorial: {
        guides: [
          {
            id: "start",
            title: "真实的论坛教程",
            summary: "原帖简介，点击标题继续阅读。",
            url: "/t/17",
            topic_id: 17,
          },
        ],
      },
    },
  },
  el,
  modal,
});
discover.learn();
const guide = content.children[1].children[0];
assert.equal(guide.tag, "a");
assert.equal(guide.attrs.href, "/t/17");
assert.equal(
  guide.children[1].children[1].children[0],
  "原帖简介，点击标题继续阅读。",
);
assert.equal(
  guide.attrs.onclick,
  undefined,
  "Guide cards use real forum links rather than a detail dialog",
);
assert.equal(modalCount, 0);
vm.runInNewContext(fs.readFileSync("plugin/public/market.js", "utf8"), {
  window,
});
const market = window.HandrawMarket({
  state: { boot: {} },
  el,
  modal,
  button: (text) => el("button", {}, text),
  tell: (m) => messages.push(m),
});
(async () => {
  await market.share();
  const choices = chooser[1].children.map((n) => n.children[0]);
  assert.deepEqual(choices, ["分享作品", "分享画风", "分享图型"]);
  await market.share("experience");
  assert.equal(modalCount, 1, "Direct experience links cannot open a new form");
  assert.ok(messages[0].includes("版主"));
  console.log(
    "Forum navigation: guide links and summaries, three submission types, no experience form passed",
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
