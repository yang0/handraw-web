"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Mock DOM environment for testing Handraw Curation Share Form (Phase 3b-7)
class MockElement {
  constructor(tagName = "DIV", attrs = {}) {
    this.tagName = tagName.toUpperCase();
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this._classes = new Set((attrs.class || "").split(/\s+/).filter(Boolean));
    const self = this;
    this.classList = {
      add(...cls) { cls.forEach((c) => self._classes.add(c)); },
      remove(...cls) { cls.forEach((c) => self._classes.delete(c)); },
      contains(c) { return self._classes.has(c); },
      toggle(c, force) {
        if (force === undefined) {
          if (self._classes.has(c)) { self._classes.delete(c); return false; }
          self._classes.add(c); return true;
        }
        if (force) { self._classes.add(c); return true; }
        self._classes.delete(c); return false;
      }
    };
    this.style = {};
    this._value = attrs.value !== undefined ? String(attrs.value) : undefined;
    this.disabled = attrs.disabled !== undefined;
    this.checked = attrs.checked !== undefined;
    this.id = attrs.id || "";
    this._textContent = null;
    this._listeners = {};
    this._doc = null;
  }

  get value() {
    if (this._value !== undefined) return this._value;
    if (this.tagName === "TEXTAREA") return this.textContent;
    return this.attrs.value !== undefined ? String(this.attrs.value) : "";
  }

  set value(v) {
    this._value = String(v);
    if (this.tagName === "TEXTAREA") {
      this.textContent = String(v);
    }
  }

  get textContent() {
    if (this._textContent !== null) return this._textContent;
    return this.children.map((c) => (typeof c === "string" ? c : c.textContent)).join("");
  }

  set textContent(v) {
    this._textContent = String(v);
    this.children = [String(v)];
  }

  get innerHTML() {
    return this.children.map((c) => (typeof c === "string" ? c : c.outerHTML)).join("");
  }

  set innerHTML(html) {
    this.children = [];
    this._textContent = null;
    parseHtmlToChildren(html, this);
  }

  get outerHTML() {
    const attrStr = Object.entries(this.attrs).map(([k, v]) => ` ${k}="${v}"`).join("");
    return `<${this.tagName.toLowerCase()}${attrStr}>${this.innerHTML}</${this.tagName.toLowerCase()}>`;
  }

  getAttribute(name) {
    const k = name.toLowerCase();
    if (k === "class") return Array.from(this._classes).join(" ");
    return this.attrs[k] !== undefined ? this.attrs[k] : null;
  }

  setAttribute(name, val) {
    const k = name.toLowerCase();
    this.attrs[k] = String(val);
    if (k === "id") this.id = String(val);
    if (k === "class") this._classes = new Set(String(val).split(/\s+/).filter(Boolean));
    if (k === "value") this.value = String(val);
  }

  removeAttribute(name) {
    delete this.attrs[name.toLowerCase()];
  }

  appendChild(child) {
    if (typeof child !== "string") {
      child.parent = this;
      child._doc = this._doc;
    }
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx >= 0) {
      if (typeof child !== "string") child.parent = null;
      this.children.splice(idx, 1);
    }
  }

  addEventListener(event, fn) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(fn);
  }

  dispatchEvent(event) {
    let curr = this;
    const evt = {
      type: event.type,
      target: event.target || this,
      preventDefault: () => {},
      stopPropagation: () => { evt._stopped = true; },
      _stopped: false,
      ...event
    };
    while (curr) {
      if (curr._listeners && curr._listeners[evt.type]) {
        for (const handler of curr._listeners[evt.type]) {
          handler.call(curr, evt);
          if (evt._stopped) return;
        }
      }
      curr = curr.parent;
    }
  }

  click() {
    this.dispatchEvent({ type: "click", target: this });
  }

  focus() {
    this._focused = true;
    let d = this._doc;
    let p = this.parent;
    while (!d && p) {
      d = p._doc;
      p = p.parent;
    }
    if (d) d.activeElement = this;
  }

  scrollIntoView(opts) {
    this._lastScrollOpts = opts;
  }

  closest(sel) {
    let curr = this;
    while (curr) {
      if (typeof curr !== "string" && matchesSelector(curr, sel)) {
        return curr;
      }
      curr = curr.parent;
    }
    return null;
  }

  querySelector(sel) {
    return querySelector(this, sel);
  }

  querySelectorAll(sel) {
    return querySelectorAll(this, sel);
  }
}

function parseAttributes(attrStr) {
  const attrs = {};
  const re = /([a-zA-Z0-9_-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
  let m;
  while ((m = re.exec(attrStr)) !== null) {
    const key = m[1].toLowerCase();
    const val = m[2] !== undefined ? m[2] : (m[3] !== undefined ? m[3] : (m[4] !== undefined ? m[4] : ""));
    attrs[key] = val;
  }
  return attrs;
}

const VOID_TAGS = new Set(["AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"]);

function parseHtmlToChildren(html, parentElement) {
  const tagRe = /<!--[\s\S]*?-->|<(\/)?([a-zA-Z0-9-]+)([^>]*)>|([^<]+)/g;
  let match;
  let current = parentElement;

  while ((match = tagRe.exec(html)) !== null) {
    const [full, isClosing, tagName, attrStr, text] = match;
    if (full.startsWith("<!--")) continue;
    if (text) {
      current.appendChild(text);
      continue;
    }
    const tag = tagName.toUpperCase();
    if (isClosing) {
      if (current.parent && current.tagName === tag) {
        current = current.parent;
      }
    } else {
      const attrs = parseAttributes(attrStr);
      const isSelfClosing = attrStr.trim().endsWith("/") || VOID_TAGS.has(tag);
      const el = new MockElement(tag, attrs);
      el._doc = parentElement._doc;
      current.appendChild(el);
      if (!isSelfClosing) {
        current = el;
      }
    }
  }
}

function matchesCompound(el, sel) {
  if (!el || typeof el === "string") return false;
  let remaining = sel.trim();

  const tagMatch = remaining.match(/^([a-zA-Z0-9_-]+)/);
  if (tagMatch) {
    if (el.tagName.toLowerCase() !== tagMatch[1].toLowerCase()) return false;
    remaining = remaining.slice(tagMatch[1].length);
  }

  while (remaining.length > 0) {
    if (remaining.startsWith(".")) {
      const m = remaining.match(/^\.([a-zA-Z0-9_-]+)/);
      if (!m) return false;
      if (!el.classList.contains(m[1])) return false;
      remaining = remaining.slice(m[0].length);
    } else if (remaining.startsWith("#")) {
      const m = remaining.match(/^#([a-zA-Z0-9_-]+)/);
      if (!m) return false;
      if (el.id !== m[1]) return false;
      remaining = remaining.slice(m[0].length);
    } else if (remaining.startsWith("[")) {
      const m = remaining.match(/^\[([a-zA-Z0-9_-]+)(?:([*^$]?=)(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]/);
      if (!m) return false;
      const [, attrName, op, v1, v2, v3] = m;
      const expected = v1 !== undefined ? v1 : (v2 !== undefined ? v2 : (v3 !== undefined ? v3 : null));
      const actual = el.getAttribute(attrName);
      if (expected === null) {
        if (actual === null) return false;
      } else {
        if (actual === null) return false;
        if (op === "=" && actual !== expected) return false;
        if (op === "*=" && !actual.includes(expected)) return false;
        if (op === "^=" && !actual.startsWith(expected)) return false;
        if (op === "$=" && !actual.endsWith(expected)) return false;
      }
      remaining = remaining.slice(m[0].length);
    } else if (remaining === ":checked") {
      return el.checked === true;
    } else {
      break;
    }
  }
  return true;
}

function matchesSelector(el, sel) {
  if (typeof el === "string") return false;
  sel = sel.trim();
  if (sel.includes(",")) {
    return sel.split(",").some((part) => matchesSelector(el, part.trim()));
  }
  if (sel.includes(" ")) {
    const parts = sel.split(/\s+/);
    if (parts.length >= 2) {
      const last = parts[parts.length - 1];
      if (!matchesCompound(el, last)) return false;
      let curr = el.parent;
      let pIdx = parts.length - 2;
      while (curr && pIdx >= 0) {
        if (matchesCompound(curr, parts[pIdx])) {
          pIdx--;
        }
        curr = curr.parent;
      }
      return pIdx < 0;
    }
  }
  return matchesCompound(el, sel);
}

function querySelector(root, sel) {
  const all = querySelectorAll(root, sel);
  return all.length ? all[0] : null;
}

function querySelectorAll(root, sel) {
  const results = [];
  function walk(node) {
    if (typeof node === "string") return;
    for (const child of node.children) {
      if (typeof child !== "string") {
        if (matchesSelector(child, sel)) {
          results.push(child);
        }
        walk(child);
      }
    }
  }
  walk(root);
  return results;
}

function createHarness() {
  const doc = {
    activeElement: null,
    createElement(tag) {
      const el = new MockElement(tag);
      el._doc = doc;
      return el;
    },
    querySelector(sel) { return root.querySelector(sel); },
    querySelectorAll(sel) { return root.querySelectorAll(sel); }
  };
  const root = new MockElement("DIV", { id: "app-root" });
  root._doc = doc;
  doc.body = root;

  let confirmResult = true;
  let lastConfirmMsg = "";
  const apiCalls = [];

  const fakeApiJson = async (url, opts = {}) => {
    apiCalls.push({ url, opts, method: opts.method || "GET", body: opts.body });
    if (url.startsWith("/api/curation/drafts/")) {
      const draftId = url.split("/").pop();
      if (draftId.startsWith("825e80af")) {
        return {
          payload: {
            title: "图文模式",
            topicTitle: "【画布创作晒图】图文模式",
            topicBody: "我的创作实测分享",
            prompt: "Prompt exact text for 825e80af testing",
            mood: "治愈",
            color: "C-15",
            tone: "T-01",
            mode: "graphic-text",
            ratio: "3:4",
            images: ["/test/img1.webp"]
          }
        };
      }
      return { payload: null };
    }
    if (url === "/api/curation/mine") {
      return {
        submissions: [
          {
            id: "edit_sub_01",
            kind: "style",
            payload: {
              kind: "style",
              name: "水墨江南",
              definition: "江南水墨烟雨淡彩",
              description: "适合江南园林水乡",
              images: ["/images/style-demo.webp"],
              extraCustomField: "should_be_preserved",
              authorLegacy: "artist_wang"
            }
          }
        ]
      };
    }
    if (url === "/api/uploads") {
      return { ok: true, url: "/uploads/uploaded_" + Math.random().toString(36).slice(2) + ".png" };
    }
    if (url === "/api/works") {
      return { ok: true, workId: "work_001", topicId: "topic_001" };
    }
    if (url === "/api/curation/submissions") {
      return { ok: true, id: "sub_002", topicId: "topic_002" };
    }
    if (url.includes("/revise")) {
      return { ok: true, topicId: "topic_001" };
    }
    return { ok: true };
  };

  class MockFileReader {
    readAsDataURL(file) {
      setTimeout(() => {
        this.result = "data:image/png;base64,mock";
        if (typeof this.onload === "function") this.onload();
      }, 5);
    }
  }

  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    Promise,
    URLSearchParams,
    Object,
    Array,
    String,
    Number,
    Boolean,
    Set,
    Map,
    FileReader: MockFileReader,
    document: doc,
    location: {
      href: "http://localhost:8088/curation",
      search: ""
    },
    confirm(msg) {
      lastConfirmMsg = msg;
      return confirmResult;
    },
    window: {
      document: doc,
      FileReader: MockFileReader,
      confirm(msg) {
        lastConfirmMsg = msg;
        return confirmResult;
      },
      crypto: {
        randomUUID: () => "mock-uuid-" + Math.random().toString(36).slice(2)
      },
      HandrawImageLoader: { scan: () => {} },
      HANDRAW_SHARED: {
        esc: (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
        apiJson: fakeApiJson,
        channelUrl: (ch, opts) => "/" + ch + (opts ? "?" + new URLSearchParams(opts).toString() : ""),
        App: {
          state: {
            loggedIn: true,
            user: { username: "tester", role: "user" }
          },
          resourceMap: new Map([
            ["FE-001", { id: "FE-001", name: "水彩柔光", kind: "style", image: "/img/fe.webp" }],
            ["SC-001", { id: "SC-001", name: "社交卡片", kind: "layout", image: "/img/sc.webp" }]
          ])
        },
        refreshFromServer: () => {}
      },
      location: {
        href: "http://localhost:8088/curation",
        search: ""
      }
    }
  };
  sandbox.window.location = sandbox.location;
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);

  const curationUiCode = fs.readFileSync(path.join(__dirname, "../demo/assets/curation-ui.js"), "utf8");
  vm.runInContext(curationUiCode, sandbox);

  return {
    root,
    doc,
    apiCalls,
    sandbox,
    setConfirmResult(r) { confirmResult = r; },
    getLastConfirmMsg() { return lastConfirmMsg; },
    Curation: sandbox.window.HandrawCuration
  };
}

async function runAllTests() {
  console.log("Starting Phase 3b-7 Curation Share Form Tests...");

  // ==========================================
  // TEST 1: 新建 kind=work
  // ==========================================
  {
    console.log("\n--- Test 1: 新建 kind=work ---");
    const { root, Curation } = createHarness();
    Curation.render(root, {}); // default is work

    const inputsAndTextareas = root.querySelectorAll(".curation-form input, .curation-form textarea");
    const count = (act) => inputsAndTextareas.filter((el) => el.getAttribute("data-act") === act).length;

    assert.equal(count("title"), 1, "Should have exactly 1 [data-act=title]");
    assert.equal(count("prompt"), 1, "Should have exactly 1 [data-act=prompt]");
    assert.equal(count("notes"), 1, "Should have exactly 1 [data-act=notes]");

    assert.equal(count("ftitle"), 0, "Should have 0 [data-act=ftitle]");
    assert.equal(count("ftext"), 0, "Should have 0 [data-act=ftext]");
    assert.equal(count("description"), 0, "Should have 0 [data-act=description]");

    const additemBtn = root.querySelectorAll("[data-act=additem]");
    assert.equal(additemBtn.length, 0, "Should have 0 [data-act=additem]");

    const kindSelect = root.querySelectorAll("select[data-act=kind]");
    assert.equal(kindSelect.length, 0, "Should have 0 select[data-act=kind]");

    const legend = root.querySelector("fieldset.curation-item legend");
    assert.ok(legend, "Legend exists");
    assert.equal(legend.textContent, "作品", "Legend text should be '作品' without index");

    console.log("✓ Test 1 Passed: kind=work form structure and elements verified.");
  }

  // ==========================================
  // TEST 2: 新建 kind=style 1 项 & 点击 additem
  // ==========================================
  {
    console.log("\n--- Test 2: 新建 kind=style 1 项 & 点击 additem ---");
    const { root, doc, Curation } = createHarness();
    Curation.render(root, { kind: "style" });

    const countAct = (act) => root.querySelectorAll(`[data-act="${act}"]`).length;
    assert.equal(countAct("name"), 1, "Initial: 1 [data-act=name]");
    assert.equal(countAct("definition"), 1, "Initial: 1 [data-act=definition]");
    assert.equal(countAct("description"), 1, "Initial: 1 [data-act=description]");

    const initialSet = root.querySelector(".curation-set");
    assert.equal(initialSet, null, "Initial: .curation-set should not exist for 1 item");

    const addBtn = root.querySelector("[data-act=additem]");
    assert.ok(addBtn, "Add item button exists");
    addBtn.click();

    const items = root.querySelectorAll(".curation-item");
    assert.equal(items.length, 2, "After additem: exactly 2 .curation-item elements");

    const updatedSet = root.querySelector(".curation-set");
    assert.ok(updatedSet, "After additem: .curation-set appears");
    assert.ok(updatedSet.querySelector("[data-act=ftitle]"), ".curation-set contains ftitle");
    assert.ok(updatedSet.querySelector("[data-act=ftext]"), ".curation-set contains ftext");

    const newItemFieldset = root.querySelector('.curation-item[data-idx="1"]');
    assert.ok(newItemFieldset, "New item fieldset exists at index 1");
    const newItemNameInput = newItemFieldset.querySelector('[data-act="name"]');
    assert.ok(newItemNameInput, "New item name input exists");
    assert.equal(newItemNameInput.value, "", "New item name should be empty");
    assert.equal(doc.activeElement, newItemNameInput, "New item name input should receive focus");

    console.log("✓ Test 2 Passed: kind=style 1 item to 2 items transition, .curation-set and focus verified.");
  }

  // ==========================================
  // TEST 3: 作品空表单提交
  // ==========================================
  {
    console.log("\n--- Test 3: 作品空表单提交 ---");
    const { root, doc, apiCalls, Curation } = createHarness();
    Curation.render(root, { kind: "work" });

    const submitBtn = root.querySelector('[data-act="submit"]');
    assert.ok(submitBtn, "Submit button exists");
    submitBtn.click();

    assert.equal(apiCalls.length, 0, "No request sent on empty form submission");

    const titleErr = root.querySelector('[data-err-for="title"]');
    const promptErr = root.querySelector('[data-err-for="prompt"]');
    const fileErr = root.querySelector('[data-err-for="file"]');

    assert.ok(titleErr && titleErr.textContent.trim().length > 0, "[data-err-for=title] has error message");
    assert.ok(promptErr && promptErr.textContent.trim().length > 0, "[data-err-for=prompt] has error message");
    assert.ok(fileErr && fileErr.textContent.trim().length > 0, "[data-err-for=file] has image error message");

    const titleInput = root.querySelector('[data-act="title"]');
    assert.equal(doc.activeElement, titleInput, "document.activeElement is [data-act=title]");

    const summaryErr = root.querySelector('[data-err]');
    assert.ok(summaryErr && summaryErr.textContent.includes("还有 3 处需要修改。"), "Summary error shows remaining count");

    console.log("✓ Test 3 Passed: Empty work form validation, errors display, and focus verified.");
  }

  // ==========================================
  // TEST 4: 草稿 825e80af 数据清洗与映射
  // ==========================================
  {
    console.log("\n--- Test 4: 草稿 825e80af 映射与去噪音 ---");
    const draft825e = {
      title: "图文模式",
      topicTitle: "【画布创作晒图】图文模式",
      topicBody: "我的创作实测分享",
      prompt: "Prompt exact text for 825e80af testing",
      mood: "治愈",
      color: "C-15",
      tone: "T-01",
      mode: "graphic-text",
      ratio: "3:4",
      images: ["/test/img1.webp"]
    };

    const { Curation } = createHarness();
    const model = Curation.shareModelFrom(draft825e, "work");

    assert.equal(model.items[0].title, "图文模式", "Title is '图文模式'");
    assert.equal(model.items[0].prompt, draft825e.prompt, "Prompt strictly equals draft prompt");
    assert.equal(model.items[0].notes, "", "Notes is empty (canned body stripped)");

    // Test full render with draft preload
    const harness = createHarness();
    harness.sandbox.window.location.search = "?draft=825e80af";
    harness.Curation.render(harness.root, { draft: "825e80af" });

    // Wait for promise resolution
    await new Promise((resolve) => setTimeout(resolve, 20));

    const titleEl = harness.root.querySelector('[data-act="title"]');
    const promptEl = harness.root.querySelector('[data-act="prompt"]');
    const notesEl = harness.root.querySelector('[data-act="notes"]');

    assert.equal(titleEl.value, "图文模式", "Rendered [data-act=title] value is '图文模式'");
    assert.equal(promptEl.value, draft825e.prompt, "Rendered [data-act=prompt] strictly equals draft");
    assert.equal(notesEl.value, "", "Rendered [data-act=notes] is empty");

    const allInputs = harness.root.querySelectorAll("input, textarea");
    for (const input of allInputs) {
      assert.ok(!input.value.includes("我的创作实测分享"), "No input or textarea should contain '我的创作实测分享'");
    }

    console.log("✓ Test 4 Passed: Draft 825e80af normalization and canned body stripping verified.");
  }

  // ==========================================
  // TEST 5: 同草稿提交到 /api/works
  // ==========================================
  {
    console.log("\n--- Test 5: 同草稿提交到 /api/works ---");
    const harness = createHarness();
    harness.sandbox.window.location.search = "?draft=825e80af";
    harness.Curation.render(harness.root, { draft: "825e80af" });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const submitBtn = harness.root.querySelector('[data-act="submit"]');
    submitBtn.click();

    await new Promise((resolve) => setTimeout(resolve, 20));

    const workCall = harness.apiCalls.find((c) => c.url === "/api/works");
    assert.ok(workCall, "POST /api/works was called");
    assert.equal(workCall.body.notes, "", "Request body notes === ''");
    assert.equal(workCall.body.prompt, "Prompt exact text for 825e80af testing", "Prompt strictly preserved");
    assert.equal(workCall.body.mood, "治愈", "Mood preserved");
    assert.equal(workCall.body.color, "C-15", "Color preserved");
    assert.equal(workCall.body.tone, "T-01", "Tone preserved");
    assert.equal(workCall.body.mode, "graphic-text", "Mode preserved");
    assert.equal(workCall.body.ratio, "3:4", "Ratio preserved");

    console.log("✓ Test 5 Passed: Draft 825e80af work submission payload and extra fields preserved.");
  }

  // ==========================================
  // TEST 6: 草稿无 title 但有 topicTitle 与 topicBody
  // ==========================================
  {
    console.log("\n--- Test 6: 草稿无 title，使用 topicTitle 与 topicBody ---");
    const draftNight = {
      topicTitle: "【画布创作晒图】夜航",
      topicBody: "先铺底色再勾线",
      prompt: "x"
    };

    const { Curation } = createHarness();
    const model = Curation.shareModelFrom(draftNight, "work");

    assert.equal(model.items[0].title, "夜航", "Title stripped tag to '夜航'");
    assert.equal(model.items[0].notes, "先铺底色再勾线", "Notes took custom topicBody");
    assert.equal(model.items[0].prompt, "x", "Prompt preserved");

    console.log("✓ Test 6 Passed: Tag stripping and topicBody notes fallback verified.");
  }

  // ==========================================
  // TEST 7: 画风单项与两项提交到 /api/curation/submissions
  // ==========================================
  {
    console.log("\n--- Test 7: 画风单项与两项提交 ---");
    // 7.1 Single item
    const harness1 = createHarness();
    harness1.Curation.render(harness1.root, { kind: "style" });

    const nameInput = harness1.root.querySelector('[data-act="name"]');
    nameInput.value = "水墨云山";
    nameInput.dispatchEvent({ type: "input", target: nameInput });

    const defInput = harness1.root.querySelector('[data-act="definition"]');
    defInput.value = "淡墨轻岚，笔触飘逸";
    defInput.dispatchEvent({ type: "input", target: defInput });

    const descInput = harness1.root.querySelector('[data-act="description"]');
    descInput.value = "适合写意山水插画";
    descInput.dispatchEvent({ type: "input", target: descInput });

    const fileInput = harness1.root.querySelector('[data-act="file"]');
    harness1.sandbox.window.FileReader = class {
      readAsDataURL(file) {
        setTimeout(() => {
          this.result = "data:image/png;base64,mock";
          if (this.onload) this.onload();
        }, 5);
      }
    };
    fileInput.files = [{ name: "s1.png", size: 1024 }];
    fileInput.dispatchEvent({
      type: "change",
      target: fileInput
    });

    await new Promise((resolve) => setTimeout(resolve, 25));

    const submit1 = harness1.root.querySelector('[data-act="submit"]');
    submit1.click();

    await new Promise((resolve) => setTimeout(resolve, 30));

    const subCall1 = harness1.apiCalls.find((c) => c.url === "/api/curation/submissions");
    assert.ok(subCall1, "Single item submitted to /api/curation/submissions");
    assert.equal(subCall1.body.title, "水墨云山", "Single item submission title === item name");
    assert.equal(subCall1.body.text, "适合写意山水插画", "Single item submission text === item description");
    assert.equal(subCall1.body.items.length, 1, "Items length is 1");
    const itKeys = Object.keys(subCall1.body.items[0]);
    assert.deepEqual(itKeys.sort(), ["definition", "description", "images", "kind", "name"], "Items contain only allowed keys");

    // 7.2 Two items with empty collection title
    const harness2 = createHarness();
    harness2.Curation.render(harness2.root, { kind: "style" });

    // Add 1st item
    harness2.root.querySelector('[data-act="name"]').value = "A";
    harness2.root.querySelector('[data-act="name"]').dispatchEvent({ type: "input", target: harness2.root.querySelector('[data-act="name"]') });
    harness2.root.querySelector('[data-act="definition"]').value = "Def A";
    harness2.root.querySelector('[data-act="definition"]').dispatchEvent({ type: "input", target: harness2.root.querySelector('[data-act="definition"]') });

    // Add 2nd item
    harness2.root.querySelector('[data-act="additem"]').click();
    const name2 = harness2.root.querySelectorAll('[data-act="name"]')[1];
    name2.value = "B";
    name2.dispatchEvent({ type: "input", target: name2 });
    const def2 = harness2.root.querySelectorAll('[data-act="definition"]')[1];
    def2.value = "Def B";
    def2.dispatchEvent({ type: "input", target: def2 });

    // Mock upload images on both items
    harness2.sandbox.window.FileReader = harness1.sandbox.window.FileReader;
    const file1 = harness2.root.querySelectorAll('[data-act="file"]')[0];
    file1.files = [{ name: "1.png", size: 10 }];
    file1.dispatchEvent({
      type: "change",
      target: file1
    });
    await new Promise((resolve) => setTimeout(resolve, 20));

    const file2 = harness2.root.querySelectorAll('[data-act="file"]')[1];
    file2.files = [{ name: "2.png", size: 10 }];
    file2.dispatchEvent({
      type: "change",
      target: file2
    });
    await new Promise((resolve) => setTimeout(resolve, 20));

    // Submit with empty collection title
    const submit2 = harness2.root.querySelector('[data-act="submit"]');
    submit2.click();

    await new Promise((resolve) => setTimeout(resolve, 20));

    const subCall2 = harness2.apiCalls.find((c) => c.url === "/api/curation/submissions");
    assert.ok(subCall2, "Two items submitted to /api/curation/submissions");
    assert.equal(subCall2.body.title, "投稿：A 等 2 项", "Two items collection title derived as '投稿：A 等 2 项'");

    console.log("✓ Test 7 Passed: Style single and multi-item submission payloads and title derivation verified.");
  }

  // ==========================================
  // TEST 8: 简介 301 字校验
  // ==========================================
  {
    console.log("\n--- Test 8: 简介 301 字超限校验 ---");
    const harness = createHarness();
    harness.Curation.render(harness.root, { kind: "style" });

    const descInput = harness.root.querySelector('[data-act="description"]');
    descInput.value = "字".repeat(301);
    descInput.dispatchEvent({ type: "input", target: descInput });

    const submitBtn = harness.root.querySelector('[data-act="submit"]');
    submitBtn.click();

    assert.equal(harness.apiCalls.length, 0, "No request sent when description exceeds 300 chars");

    const descErr = harness.root.querySelector('[data-err-for="description"]');
    assert.ok(descErr, "Description error span exists");
    assert.equal(descErr.textContent, "最多 300 字，当前 301 字。", "Error message matches spec table");

    console.log("✓ Test 8 Passed: 301-character description limit validation verified.");
  }

  // ==========================================
  // TEST 9: 编辑重提画风
  // ==========================================
  {
    console.log("\n--- Test 9: 编辑重提画风模式与未展示键保留 ---");
    const harness = createHarness();
    harness.Curation.render(harness.root, { editId: "edit_sub_01" });

    await new Promise((resolve) => setTimeout(resolve, 20));

    assert.equal(harness.root.querySelectorAll(".curation-kind-switch").length, 0, "No .curation-kind-switch in edit mode");
    assert.equal(harness.root.querySelectorAll(".curation-set").length, 0, "No .curation-set in edit mode");
    assert.equal(harness.root.querySelectorAll("[data-act=additem]").length, 0, "No additem button in edit mode");
    assert.equal(harness.root.querySelectorAll("[data-act=delitem]").length, 0, "No delitem button in edit mode");

    const submitBtn = harness.root.querySelector('[data-act="submit"]');
    assert.equal(submitBtn.textContent, "提交新版本", "Submit button text is '提交新版本'");
    submitBtn.click();

    await new Promise((resolve) => setTimeout(resolve, 20));

    const reviseCall = harness.apiCalls.find((c) => c.url.includes("/revise"));
    assert.ok(reviseCall, "Revise API called");
    assert.equal(reviseCall.body.payload.extraCustomField, "should_be_preserved", "Custom extra key preserved");
    assert.equal(reviseCall.body.payload.authorLegacy, "artist_wang", "Legacy author key preserved");
    assert.equal(reviseCall.body.payload.name, "水墨江南", "Name preserved");

    console.log("✓ Test 9 Passed: Edit mode controls suppression and extra payload keys retention verified.");
  }

  // ==========================================
  // TEST 10: 作品 <-> 画风 切换与 2 项取消确认
  // ==========================================
  {
    console.log("\n--- Test 10: 作品与画风往返切换及确认保护 ---");
    const harness = createHarness();
    harness.Curation.render(harness.root, { kind: "work" });

    const titleInput = harness.root.querySelector('[data-act="title"]');
    titleInput.value = "春山";
    titleInput.dispatchEvent({ type: "input", target: titleInput });

    const promptInput = harness.root.querySelector('[data-act="prompt"]');
    promptInput.value = "spring mountain landscape";
    promptInput.dispatchEvent({ type: "input", target: promptInput });

    const notesInput = harness.root.querySelector('[data-act="notes"]');
    notesInput.value = "my author notes";
    notesInput.dispatchEvent({ type: "input", target: notesInput });

    // 10.1 Switch work -> style
    const styleRadio = harness.root.querySelector('input[data-act="sharekind"][value="style"]');
    styleRadio.click();
    styleRadio.dispatchEvent({ type: "change", target: styleRadio });

    assert.equal(harness.root.querySelector('[data-act="name"]').value, "春山", "Work title -> Style name");
    assert.equal(harness.root.querySelector('[data-act="definition"]').value, "spring mountain landscape", "Work prompt -> Style definition");
    assert.equal(harness.root.querySelector('[data-act="description"]').value, "my author notes", "Work notes -> Style description");

    // 10.2 Switch style -> work
    const workRadio = harness.root.querySelector('input[data-act="sharekind"][value="work"]');
    workRadio.click();
    workRadio.dispatchEvent({ type: "change", target: workRadio });

    assert.equal(harness.root.querySelector('[data-act="title"]').value, "春山", "Style name -> Work title");
    assert.equal(harness.root.querySelector('[data-act="prompt"]').value, "spring mountain landscape", "Style definition -> Work prompt");
    assert.equal(harness.root.querySelector('[data-act="notes"]').value, "my author notes", "Style description -> Work notes");

    // 10.3 Add 2nd item in style, then switch to work with confirm cancelled
    styleRadio.click();
    styleRadio.dispatchEvent({ type: "change", target: styleRadio });
    harness.root.querySelector('[data-act="additem"]').click();
    assert.equal(harness.root.querySelectorAll(".curation-item").length, 2, "Now 2 items in style");

    harness.setConfirmResult(false);
    workRadio.click();
    workRadio.dispatchEvent({ type: "change", target: workRadio });

    assert.equal(harness.getLastConfirmMsg(), "切换为作品只保留第一项，确定吗？", "Confirm prompt matches spec");
    assert.equal(harness.root.querySelectorAll(".curation-item").length, 2, "Items still 2 after confirm cancel");
    const checkedRadio = harness.root.querySelector('input[data-act="sharekind"]:checked');
    assert.equal(checkedRadio.value, "style", "Radio value reverted to style");

    // 10.4 Switch to work with confirm accepted
    harness.setConfirmResult(true);
    workRadio.click();
    workRadio.dispatchEvent({ type: "change", target: workRadio });

    assert.equal(harness.root.querySelectorAll(".curation-item").length, 1, "Single item retained after confirm ok");
    assert.equal(harness.root.querySelector('input[data-act="sharekind"]:checked').value, "work", "Radio value is now work");

    console.log("✓ Test 10 Passed: Bidirectional kind switching, data preservation, and confirm behavior verified.");
  }

  console.log("\n=======================================================");
  console.log("ALL 10 CURATION SHARE FORM TESTS PASSED SUCCESSFULLY!");
  console.log("=======================================================\n");
}

runAllTests().catch((err) => {
  console.error("Test failed with error:", err);
  process.exit(1);
});
