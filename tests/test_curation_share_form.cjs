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

  getContext(type) {
    return {
      fillStyle: "",
      fillRect: () => {},
      drawImage: () => {}
    };
  }

  toDataURL(type, quality) {
    return "data:image/jpeg;base64,mockcropped";
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
    } else if (remaining.startsWith(":not(")) {
      const closeIdx = remaining.indexOf(")");
      if (closeIdx === -1) return false;
      const innerSel = remaining.slice(5, closeIdx);
      if (matchesCompound(el, innerSel)) return false;
      remaining = remaining.slice(closeIdx + 1);
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

class MockFileReader {
  readAsDataURL(file) {
    setTimeout(() => {
      this.result = file._dataUrl || "data:image/png;base64,mock";
      if (typeof this.onload === "function") this.onload();
    }, 5);
  }
}

class MockImage {
  constructor() {
    this.naturalWidth = MockImage.defaultWidth || 800;
    this.naturalHeight = MockImage.defaultHeight || 800;
    this.width = this.naturalWidth;
    this.height = this.naturalHeight;
    this._src = "";
  }
  set src(v) {
    this._src = v;
    if (MockImage.customDims && MockImage.customDims[v]) {
      this.naturalWidth = MockImage.customDims[v].w;
      this.naturalHeight = MockImage.customDims[v].h;
      this.width = this.naturalWidth;
      this.height = this.naturalHeight;
    }
    setTimeout(() => {
      if (typeof this.onload === "function") this.onload();
    }, 2);
  }
  get src() {
    return this._src;
  }
}
MockImage.defaultWidth = 800;
MockImage.defaultHeight = 800;
MockImage.customDims = {};

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
    Image: MockImage,
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
      Image: MockImage,
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

    // Spec Acceptance 1: legend count 0, fieldset.curation-item 0, div.curation-item 1
    assert.equal(root.querySelectorAll("legend").length, 0, "Legend count should be 0");
    assert.equal(root.querySelectorAll("fieldset.curation-item").length, 0, "fieldset.curation-item count should be 0");
    assert.equal(root.querySelectorAll("div.curation-item").length, 1, "div.curation-item count should be 1");

    console.log("✓ Test 1 Passed: kind=work form structure and elements verified.");
  }

  // ==========================================
  // TEST 2: 新建 kind=style 单项及封面与示例图元素
  // ==========================================
  {
    console.log("\n--- Test 2: 新建 kind=style 单项及封面与示例图元素 ---");
    const { root, doc, Curation } = createHarness();
    Curation.render(root, { kind: "style" });

    const countAct = (act) => root.querySelectorAll(`[data-act="${act}"]`).length;
    assert.equal(countAct("name"), 1, "Initial: 1 [data-act=name]");
    assert.equal(countAct("definition"), 1, "Initial: 1 [data-act=definition]");
    assert.equal(countAct("description"), 1, "Initial: 1 [data-act=description]");

    // Spec Acceptance 1: legend count 0, fieldset 0, div.curation-item 1, additem/delitem/curation-set 0
    assert.equal(root.querySelectorAll("legend").length, 0, "legend count should be 0");
    assert.equal(root.querySelectorAll("fieldset.curation-item").length, 0, "fieldset.curation-item count should be 0");
    assert.equal(root.querySelectorAll("div.curation-item").length, 1, "div.curation-item count should be 1");
    assert.equal(root.querySelectorAll("[data-act=additem]").length, 0, "additem button count should be 0");
    assert.equal(root.querySelectorAll("[data-act=delitem]").length, 0, "delitem button count should be 0");
    assert.equal(root.querySelectorAll(".curation-set").length, 0, ".curation-set count should be 0");

    // Spec Acceptance 2: .curation-cover input[data-act=cover]:not([multiple]) and .curation-examples input[data-act=file][multiple] each 1
    const coverInput = root.querySelectorAll('.curation-cover input[data-act="cover"]:not([multiple])');
    assert.equal(coverInput.length, 1, "Should have 1 .curation-cover input[data-act=cover]:not([multiple])");

    const examplesInput = root.querySelectorAll('.curation-examples input[data-act="file"][multiple]');
    assert.equal(examplesInput.length, 1, "Should have 1 .curation-examples input[data-act=file][multiple]");

    const helpEl = root.querySelector(".curation-cover .curation-help");
    assert.ok(helpEl, ".curation-cover has .curation-help");
    assert.equal(helpEl.textContent, "非正方形图片会自动居中裁剪", "Help text matches spec");

    console.log("✓ Test 2 Passed: kind=style single-item structure and cover/examples elements verified.");
  }

  // ==========================================
  // TEST 3: 作品空表单提交
  // ==========================================
  {
    console.log("\n--- Test 3: 作品空表单提交 ---");
    const { root, doc, Curation } = createHarness();
    Curation.render(root, {});

    const submitBtn = root.querySelector('[data-act="submit"]');
    submitBtn.click();

    const titleErr = root.querySelector('[data-err-for="title"]');
    const fileErr = root.querySelector('[data-err-for="file"]');
    const promptErr = root.querySelector('[data-err-for="prompt"]');

    assert.ok(titleErr && titleErr.textContent.trim().length > 0, "[data-err-for=title] has error message");
    assert.ok(fileErr && fileErr.textContent.trim().length > 0, "[data-err-for=file] has image error message");
    assert.ok(promptErr && promptErr.textContent.trim().length > 0, "[data-err-for=prompt] has prompt error message");

    const summaryErr = root.querySelector("[data-err]");
    assert.ok(summaryErr && summaryErr.textContent.includes("还有"), "Summary error shows remaining count");

    const titleInput = root.querySelector('[data-act="title"]');
    assert.equal(doc.activeElement, titleInput, "First invalid field received focus");

    console.log("✓ Test 3 Passed: Empty work form validation, errors display, and focus verified.");
  }

  // ==========================================
  // TEST 4: 草稿 825e80af 映射与去噪音
  // ==========================================
  {
    console.log("\n--- Test 4: 草稿 825e80af 映射与去噪音 ---");
    const { root, Curation } = createHarness();
    Curation.render(root, { draft: "825e80af" });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const titleInput = root.querySelector('[data-act="title"]');
    assert.equal(titleInput.value, "图文模式", "Title is from payload.title");

    const promptTextarea = root.querySelector('[data-act="prompt"]');
    assert.equal(promptTextarea.value, "Prompt exact text for 825e80af testing", "Prompt exact text matches");

    const notesTextarea = root.querySelector('[data-act="notes"]');
    assert.equal(notesTextarea.value, "", "Canned body '我的创作实测分享' should be stripped");

    const thumbs = root.querySelectorAll(".curation-thumb");
    assert.equal(thumbs.length, 1, "Exactly 1 image restored");

    console.log("✓ Test 4 Passed: Draft 825e80af normalization and canned body stripping verified.");
  }

  // ==========================================
  // TEST 5: 同草稿提交到 /api/works
  // ==========================================
  {
    console.log("\n--- Test 5: 同草稿提交到 /api/works ---");
    const harness = createHarness();
    harness.Curation.render(harness.root, { draft: "825e80af" });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const submitBtn = harness.root.querySelector('[data-act="submit"]');
    submitBtn.click();

    await new Promise((resolve) => setTimeout(resolve, 20));

    const workCall = harness.apiCalls.find((c) => c.url === "/api/works");
    assert.ok(workCall, "Submitted to /api/works");
    assert.equal(workCall.body.title, "图文模式", "Title submitted matches draft");
    assert.equal(workCall.body.notes, "", "Notes submitted is clean/empty");
    assert.equal(workCall.body.mode, "graphic-text", "Extra key mode preserved");
    assert.equal(workCall.body.mood, "治愈", "Extra key mood preserved");
    assert.equal(workCall.body.color, "C-15", "Extra key color preserved");
    assert.equal(workCall.body.tone, "T-01", "Extra key tone preserved");

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
  // TEST 7: 画风单项提交与封面裁剪 (Section 5 items 3, 4, 7)
  // ==========================================
  {
    console.log("\n--- Test 7: 画风单项提交与封面裁剪 ---");
    // 7.1: Missing cover validation: submitting with no cover & 0 examples
    const harness1 = createHarness();
    harness1.Curation.render(harness1.root, { kind: "style" });

    const submit1 = harness1.root.querySelector('[data-act="submit"]');
    submit1.click();

    const coverErr1 = harness1.root.querySelector('[data-err-for="cover"]');
    const fileErr1 = harness1.root.querySelector('[data-err-for="file"]');
    assert.ok(coverErr1 && coverErr1.textContent.includes("请上传一张正方形封面图"), "missing_cover message shown for cover");
    assert.equal(fileErr1 ? fileErr1.textContent.trim() : "", "", "0 example images should NOT trigger error");

    // 7.2: Selecting 10th example image -> displays too_many_images, no upload call fired
    const fileInput = harness1.root.querySelector('.curation-examples input[data-act="file"]');
    const tenFiles = Array.from({ length: 10 }, (_, i) => ({ name: `ex_${i}.png`, size: 1024 }));
    fileInput.files = tenFiles;
    fileInput.dispatchEvent({ type: "change", target: fileInput });

    const fileErr2 = harness1.root.querySelector('[data-err-for="file"]');
    assert.ok(fileErr2 && fileErr2.textContent.includes("示例图最多 9 张，当前 10 张。"), "too_many_images message displayed");
    const uploadCallsBefore = harness1.apiCalls.filter((c) => c.url === "/api/uploads");
    assert.equal(uploadCallsBefore.length, 0, "No upload fired on too_many_images");

    // 7.3: Select 1200x900 non-square image as cover -> canvas auto-crops to square and updates .curation-help
    MockImage.defaultWidth = 1200;
    MockImage.defaultHeight = 900;

    const coverInput = harness1.root.querySelector('.curation-cover input[data-act="cover"]');
    coverInput.files = [{ name: "cover_rect.png", size: 2048 }];
    coverInput.dispatchEvent({ type: "change", target: coverInput });

    await new Promise((resolve) => setTimeout(resolve, 30));

    const helpEl = harness1.root.querySelector(".curation-cover .curation-help");
    assert.ok(helpEl && helpEl.textContent.includes("已自动居中裁剪"), "Auto-crop hint displayed in .curation-help");

    const uploadCallCover = harness1.apiCalls.find((c) => c.url === "/api/uploads");
    assert.ok(uploadCallCover, "Upload called for cover");
    assert.equal(uploadCallCover.body.dataUrl, "data:image/jpeg;base64,mockcropped", "Cropped dataUrl uploaded");

    // 7.4: Submit valid style with cover and 1 example
    MockImage.defaultWidth = 800;
    MockImage.defaultHeight = 800;

    const nameInput = harness1.root.querySelector('[data-act="name"]');
    nameInput.value = "水墨云山";
    nameInput.dispatchEvent({ type: "input", target: nameInput });

    const defInput = harness1.root.querySelector('[data-act="definition"]');
    defInput.value = "淡墨轻岚，笔触飘逸";
    defInput.dispatchEvent({ type: "input", target: defInput });

    const descInput = harness1.root.querySelector('[data-act="description"]');
    descInput.value = "适合写意山水插画";
    descInput.dispatchEvent({ type: "input", target: descInput });

    fileInput.files = [{ name: "ex1.png", size: 1024 }];
    fileInput.dispatchEvent({ type: "change", target: fileInput });

    await new Promise((resolve) => setTimeout(resolve, 30));

    submit1.click();
    await new Promise((resolve) => setTimeout(resolve, 30));

    const subCall = harness1.apiCalls.find((c) => c.url === "/api/curation/submissions");
    assert.ok(subCall, "Single item submitted to /api/curation/submissions");
    assert.equal(subCall.body.title, "水墨云山", "Single item submission title === item name");
    assert.equal(subCall.body.text, "适合写意山水插画", "Single item submission text === item description");
    assert.equal(subCall.body.items.length, 1, "Items length is 1");
    const itemSubmitted = subCall.body.items[0];
    const itKeys = Object.keys(itemSubmitted).sort();
    assert.deepEqual(itKeys, ["cover", "definition", "description", "images", "kind", "name"], "Item has cover and examples keys");
    assert.ok(itemSubmitted.cover.includes("/uploads/uploaded_"), "Cover is set");
    assert.equal(itemSubmitted.images.length, 1, "Examples contains 1 image, excluding cover");

    console.log("✓ Test 7 Passed: Style single-item submission, cover validation, and auto-crop verified.");
  }

  // ==========================================
  // TEST 8: 简介 301 字超限校验
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

    const descErr = harness.root.querySelector('[data-err-for="description"]');
    assert.ok(descErr && descErr.textContent.includes("最多 300 字"), "Description 301 chars error displayed");

    console.log("✓ Test 8 Passed: 301-character description limit validation verified.");
  }

  // ==========================================
  // TEST 9: 编辑重提画风模式与未展示键保留 (D1, Acceptance 9)
  // ==========================================
  {
    console.log("\n--- Test 9: 编辑重提画风模式与未展示键保留 ---");
    MockImage.defaultWidth = 800;
    MockImage.defaultHeight = 800;

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
    assert.equal(reviseCall.body.payload.cover, "/images/style-demo.webp", "Cover extracted via coverOf");

    console.log("✓ Test 9 Passed: Edit mode controls suppression, coverOf extraction, and extra payload keys retention verified.");
  }

  // ==========================================
  // TEST 10: 作品与画风往返切换
  // ==========================================
  {
    console.log("\n--- Test 10: 作品与画风往返切换及字段保持 ---");
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

    console.log("✓ Test 10 Passed: Bidirectional single-item kind switching and data preservation verified.");
  }

  console.log("\n=======================================================");
  console.log("ALL 10 CURATION SHARE FORM TESTS PASSED SUCCESSFULLY!");
  console.log("=======================================================\n");
}

runAllTests().catch((err) => {
  console.error("Test failed with error:", err);
  process.exit(1);
});
