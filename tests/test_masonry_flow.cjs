"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
class Element {
  constructor(tag, attrs = {}) {
    this.tag = tag;
    this.attrs = attrs;
    this.children = [];
    this.listeners = {};
    this.value = attrs.value || "";
    this.style = {};
    this.isConnected = true;
  }
  append(...nodes) {
    this.children.push(...nodes.flat().filter((n) => n != null));
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  getBoundingClientRect() {
    return { height: this.height || 200 };
  }
  async emit(name) {
    return this.listeners[name]?.();
  }
}
const el = (tag, attrs, ...nodes) => {
  const n = new Element(tag, attrs);
  n.append(...nodes);
  return n;
};
const content = el("div"),
  actions = el("div");
const observers = [],
  resizers = [],
  calls = [],
  errors = [];
class IntersectionObserver {
  constructor(fn) {
    this.fn = fn;
    observers.push(this);
  }
  observe(node) {
    this.node = node;
  }
  unobserve() {
    this.node = null;
  }
  disconnect() {
    this.disconnected = true;
  }
}
class ResizeObserver {
  constructor(fn) {
    this.fn = fn;
    this.nodes = [];
    resizers.push(this);
  }
  observe(n) {
    this.nodes.push(n);
  }
  disconnect() {
    this.nodes = [];
    this.disconnected = true;
  }
}
const asset = (kind, i, source = "official") => ({
  id: `${kind}-${i}`,
  kind,
  source,
  name: `${kind} ${i}`,
  image: `/image-${i}.png`,
});
let pending,
  deferNext = false,
  failNext = false,
  community = false;
const window = { addEventListener() {} };
vm.runInNewContext(fs.readFileSync("plugin/public/market.js", "utf8"), {
  window,
  location: { search: "" },
  URLSearchParams,
  Set,
  ResizeObserver,
  IntersectionObserver,
  setTimeout,
  clearTimeout,
});
const market = window.HandrawMarket({
  state: { boot: {} },
  el,
  select: (q) => (q === "#content" ? content : actions),
  button: (label, fn) => el("button", { onclick: fn }, label),
  tell: (m) => errors.push(m),
  api: async (path) => {
    calls.push(path);
    if (deferNext) {
      deferNext = false;
      return new Promise((resolve) => {
        pending = resolve;
      });
    }
    if (failNext) {
      failNext = false;
      throw Error("offline");
    }
    const p = new URLSearchParams(path.split("?")[1]),
      kind = p.get("kind"),
      page = Number(p.get("page") || 1);
    return {
      assets: Array.from(
        { length: community ? (page === 1 ? 20 : 3) : 36 },
        (_, i) =>
          asset(
            kind,
            i + (page - 1) * 20,
            community ? "community" : "official",
          ),
      ),
    };
  },
});
const grid = () =>
  content.children.find((n) => n.attrs?.class?.startsWith("hw-masonry"));
const more = () => content.children.at(-1);
const tabs = () =>
  content.children.find((n) => n.attrs?.class === "hw-resource-tabs");
const clickMore = () => more().attrs.onclick();
(async () => {
  await market.explore();
  assert.equal(grid().children.length, 12);
  const first = grid().children[0];
  await clickMore();
  assert.equal(grid().children.length, 24);
  assert.equal(
    grid().children[0],
    first,
    "Appending must retain loaded images and cards",
  );
  assert.equal(
    calls.length,
    1,
    "Official metadata is reused without repeated requests",
  );
  first.height = 381;
  resizers.at(-1).fn([{ target: first }]);
  assert.equal(
    first.style.gridRowEnd,
    "span 52",
    "Image height determines masonry span",
  );
  await clickMore();
  assert.equal(grid().children.length, 36);
  assert.equal(more().hidden, true);
  community = true;
  await market.explore();
  assert.equal(
    observers[0].disconnected,
    true,
    "Old list observers are released",
  );
  const callCount = calls.length;
  deferNext = true;
  const next = clickMore();
  await clickMore();
  assert.equal(
    calls.length,
    callCount + 1,
    "Concurrent clicks reserve only one page request",
  );
  pending({
    assets: [asset("style", 20, "community"), asset("style", 21, "community")],
  });
  await next;
  assert.equal(grid().children.length, 22);
  assert.equal(more().hidden, true, "Exhausted community pages stop loading");
  await market.explore();
  deferNext = true;
  const oldRequest = clickMore();
  await tabs().children[1].attrs.onclick();
  await new Promise((resolve) => setImmediate(resolve));
  pending({ assets: [asset("style", 99, "community")] });
  await oldRequest;
  assert.ok(
    grid().children.every((n) =>
      n.children[2].children[0].children[0].startsWith("layout"),
    ),
    "Late style responses must not pollute the layout tab",
  );
  failNext = true;
  await clickMore();
  assert.deepEqual(errors, ["offline"]);
  assert.equal(
    more().disabled,
    false,
    "A failed request leaves an explicit retry button",
  );
  assert.equal(observers.at(-1).node, null, "Failures stop automatic retries");
  market.stopExplore();
  assert.equal(observers.at(-1).disconnected, true);
  console.log(
    "Masonry: append identity, size changes, pagination, concurrency, stale responses and retry passed",
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
