"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

console.log("Starting Reference Asset Picker Category Pills Tests (Issue #42)...");

const studioAppSource = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const themeCssSource = fs.readFileSync("demo/assets/theme.css", "utf8");

// =========================================================================
// Test 1: Static Code Inspections (Markup, Accessibility, CSS)
// =========================================================================
{
  // 1.1 Verify removal of old <select id="ing-upload-cat">
  assert.ok(
    !studioAppSource.includes('<select class="hw-input" id="ing-upload-cat">'),
    "Old select #ing-upload-cat must be completely removed from studio-app.js"
  );

  // 1.2 Verify use of fieldset/legend for semantic radio grouping (no extra ARIA)
  assert.ok(
    studioAppSource.includes('<fieldset id="ing-upload-cat-fieldset"'),
    "Upload section must use <fieldset> to group radio pills"
  );
  assert.ok(
    studioAppSource.includes('<legend'),
    "Upload section must use <legend> to describe category choice"
  );
  assert.ok(
    !studioAppSource.includes('role="radiogroup"'),
    "Must NOT simulate ARIA radiogroup; use native fieldset/legend semantics"
  );
  assert.ok(
    !studioAppSource.includes('role="radio"'),
    "Must NOT simulate ARIA radio; use native <input type='radio'>"
  );

  // 1.3 Verify native radio inputs sharing name="ing-upload-cat-radio"
  assert.ok(
    studioAppSource.includes('type="radio"'),
    "Upload category options must use native radio buttons"
  );
  assert.ok(
    studioAppSource.includes('name="ing-upload-cat-radio"'),
    "Radio inputs must share name='ing-upload-cat-radio'"
  );

  // 1.4 Verify CSS pill radio styling, focus-visible and disabled states
  assert.ok(
    themeCssSource.includes('input[type="radio"]:checked'),
    "theme.css must support radio checked state on .hw-pill"
  );
  assert.ok(
    themeCssSource.includes('input[type="radio"]:focus-visible'),
    "theme.css must support keyboard focus-visible outline on .hw-pill"
  );
  assert.ok(
    themeCssSource.includes(".hw-cat-radio"),
    "theme.css must provide .hw-cat-radio class"
  );

  console.log("✓ Test 1 Passed: Static inspections (no select, native radio pills, fieldset/legend, CSS) verified");
}

// =========================================================================
// Test 2-5: Runtime DOM & Interaction Simulation
// =========================================================================
const VOID_TAGS = new Set(["AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"]);

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
    this.onclick = null;
    this.onchange = null;
    this.files = [];
  }

  get value() {
    if (this._value !== undefined) return this._value;
    return this.attrs.value !== undefined ? String(this.attrs.value) : "";
  }

  set value(v) {
    this._value = String(v);
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

  scrollIntoView() {}

  click() {
    if (typeof this.onclick === "function") {
      this.onclick({ target: this, stopPropagation: () => {} });
    }
    if (this._listeners["click"]) {
      this._listeners["click"].forEach((fn) => fn({ target: this, stopPropagation: () => {} }));
    }
  }

  querySelector(sel) {
    return querySelector(this, sel);
  }

  querySelectorAll(sel) {
    return querySelectorAll(this, sel);
  }
}

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

class MockFileReader {
  readAsDataURL(file) {
    setTimeout(() => {
      this.result = file._dataUrl || "data:image/png;base64,mockpngdata";
      if (typeof this.onload === "function") this.onload();
    }, 10);
  }
}

// Instantiate environment
let mountedRoot = null;
let lastPostedUpload = null;
const mockShared = {
  App: { state: { loggedIn: true, serverBacked: true } },
  esc: (s) => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
  toast: () => {},
  channelUrl: () => "#",
  initApp: () => {},
  openModal: (cfg) => {
    const root = new MockElement("DIV");
    root.innerHTML = cfg.html;
    cfg.onMount(root);
    mountedRoot = root;
  },
  closeModal: () => {}
};

const sandbox = {
  window: {
    HANDRAW_SHARED: mockShared,
    HANDRAW_CANVAS_ENGINE: {
      uid: () => "mock-id",
      makeSkillParamsNode: () => ({ id: "node-skill", type: "skill_params", data: { tones: [] } }),
      makeAssetNode: () => ({ id: "node-asset", type: "asset", data: { items: [] } }),
      makeTextInputNode: () => ({ id: "node-text", type: "text_input", data: {} }),
      makeBridgeNode: () => ({ id: "node-bridge", type: "bridge", data: {} }),
      makeOutputControlNode: () => ({ id: "node-ctrl", type: "output_control", data: {} }),
      makeOutputDisplayNode: () => ({ id: "node-disp", type: "output_display", data: {} })
    },
    localStorage: {
      _data: {},
      getItem(k) { return this._data[k] || null; },
      setItem(k, v) { this._data[k] = String(v); }
    },
    location: { href: "http://127.0.0.1:3000/studio.html", pathname: "/studio.html", search: "" },
    history: { replaceState: () => {} },
    URLSearchParams: globalThis.URLSearchParams,
    URL: globalThis.URL
  },
  document: {
    createElement: (t) => new MockElement(t),
    getElementById: (id) => new MockElement("DIV", { id }),
    addEventListener: () => {},
    removeEventListener: () => {}
  },
  URLSearchParams: globalThis.URLSearchParams,
  URL: globalThis.URL,
  FileReader: MockFileReader,
  fetch: async (url, opts) => {
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    lastPostedUpload = { url, payload: body };
    return {
      ok: true,
      json: async () => ({ ok: true, id: "USR-01", image: body.dataUrl })
    };
  },
  setTimeout: (fn, ms) => {
    if (ms === 0 || ms === 60 || ms === 40) fn();
    return 1;
  },
  setInterval: () => 1,
  clearTimeout: () => {},
  clearInterval: () => {},
  requestAnimationFrame: (fn) => fn(),
  console: {
    log: () => {},
    warn: () => {},
    error: () => {},
    info: () => {}
  }
};
sandbox.global = sandbox.window;
sandbox.window.window = sandbox.window;

vm.createContext(sandbox);
vm.runInContext(studioAppSource, sandbox);

const openPicker = sandbox.window.HANDRAW_STUDIO.openReferenceAssetPickerModal;
assert.ok(typeof openPicker === "function", "openReferenceAssetPickerModal must be exported on HANDRAW_STUDIO");

// Run picker with clean items
openPicker({ references: [] });
assert.ok(mountedRoot, "Modal must mount successfully");

const topTabs = mountedRoot.querySelectorAll("[data-top-tab]");
const uploadTabBtn = topTabs.find((b) => b.getAttribute("data-top-tab") === "upload");
const myTabBtn = topTabs.find((b) => b.getAttribute("data-top-tab") === "my");
assert.ok(uploadTabBtn, "Upload tab button must exist");
assert.ok(myTabBtn, "My library tab button must exist");

// =========================================================================
// Test 2: 默认跟随筛选 (Default follows filter)
// =========================================================================
{
  // 2.1 Default activeCategory is "ALL". Switch to upload tab -> defaults to "other"
  uploadTabBtn.click();
  const uploadBar = mountedRoot.querySelector("#ast-upload-bar");
  assert.ok(uploadBar, "Upload bar must be rendered in upload tab");
  const radiosInitial = uploadBar.querySelectorAll("input[name='ing-upload-cat-radio']");
  assert.ok(radiosInitial.length >= 4, "Must render at least 4 category radios");
  const checkedInitial = radiosInitial.find((r) => r.checked);
  assert.equal(checkedInitial?.value, "other", "Initial upload category with ALL filter must default to 'other'");

  // 2.2 Switch to 'my' tab, click category pill 'characters'
  myTabBtn.click();
  const catsWrap = mountedRoot.querySelector("#ast-cats-wrap");
  const filterPills = catsWrap.querySelectorAll("[data-ing-grp]");
  const charPill = filterPills.find((p) => p.getAttribute("data-ing-grp") === "characters");
  assert.ok(charPill, "Characters category pill must exist in gallery filter");
  charPill.click();

  // Switch to upload tab -> should follow filter and default to 'characters'
  uploadTabBtn.click();
  const radiosAfterChar = uploadBar.querySelectorAll("input[name='ing-upload-cat-radio']");
  const checkedChar = radiosAfterChar.find((r) => r.checked);
  assert.equal(checkedChar?.value, "characters", "Upload category must default to 'characters' matching active filter");
  console.log("✓ Test 2 Passed: 默认跟随筛选 (Default follows filter) verified");
}

// =========================================================================
// Test 3: 手动选择后切筛选不覆盖 (Manual selection preserved across filter changes)
// =========================================================================
{
  const uploadBar = mountedRoot.querySelector("#ast-upload-bar");
  const otherRadioPill = uploadBar.querySelectorAll(".ing-cat-pill").find((p) => {
    const r = p.querySelector("input[name='ing-upload-cat-radio']");
    return r && r.value === "other";
  });
  assert.ok(otherRadioPill, "Other category pill must exist in upload section");
  otherRadioPill.click();

  // Switch to 'my' tab and change gallery filter to 'scenes'
  myTabBtn.click();
  const catsWrap = mountedRoot.querySelector("#ast-cats-wrap");
  const scenesPill = catsWrap.querySelectorAll("[data-ing-grp]").find((p) => p.getAttribute("data-ing-grp") === "scenes");
  assert.ok(scenesPill, "Scenes category pill must exist in gallery filter");
  scenesPill.click();

  // Switch back to upload tab -> must still be 'other', NOT overwritten by 'scenes'
  uploadTabBtn.click();
  const radiosAfterManual = uploadBar.querySelectorAll("input[name='ing-upload-cat-radio']");
  const checkedAfterManual = radiosAfterManual.find((r) => r.checked);
  assert.equal(
    checkedAfterManual?.value,
    "other",
    "Manual selection of 'other' must persist and not be overwritten by 'scenes' filter"
  );
  console.log("✓ Test 3 Passed: 手动选择后切筛选不覆盖 (Manual selection preserved across filter changes) verified");
}

// =========================================================================
// Test 4: 自定义分类出现在标签里 (Custom categories appear in upload pills)
// =========================================================================
{
  myTabBtn.click();
  const catsWrap = mountedRoot.querySelector("#ast-cats-wrap");
  // Click new category toggle
  const newCatBtn = catsWrap.querySelector("#ing-toggle-new-cat");
  if (newCatBtn) newCatBtn.click();
  const catNameInput = catsWrap.querySelector("#ing-new-cat-name");
  const confirmCatBtn = catsWrap.querySelector("#ing-confirm-new-cat");
  if (catNameInput && confirmCatBtn) {
    catNameInput.value = "角色立绘";
    confirmCatBtn.click();
  }

  // Switch to upload tab -> new custom category must be present and selected
  uploadTabBtn.click();
  const uploadBar = mountedRoot.querySelector("#ast-upload-bar");
  const uploadPillsWithCustom = uploadBar.querySelectorAll(".ing-cat-pill");
  const customPill = uploadPillsWithCustom.find((p) => {
    const span = p.querySelector("span");
    return span && span.textContent && span.textContent.includes("角色立绘");
  });
  assert.ok(customPill, "New custom category '角色立绘' must appear in upload pills");
  const customRadio = customPill.querySelector("input[name='ing-upload-cat-radio']");
  assert.ok(customRadio && customRadio.checked, "New custom category must be selected by default as uploadCategory");
  console.log("✓ Test 4 Passed: 自定义分类出现在标签里 (Custom categories appear in upload pills and selected) verified");
}

// =========================================================================
// Test 5: 上传归类与选中标签一致 (Upload payload and state matching)
// =========================================================================
(async () => {
  const uploadBar = mountedRoot.querySelector("#ast-upload-bar");
  const fileInp = uploadBar.querySelector("#ing-upload-file");
  const fieldset = uploadBar.querySelector("#ing-upload-cat-fieldset");
  assert.ok(fileInp, "File input must exist in upload section");
  assert.ok(fieldset, "Fieldset element must exist in upload section");

  // Select 'props' category
  const propsPill = uploadBar.querySelectorAll(".ing-cat-pill").find((p) => {
    const r = p.querySelector("input[name='ing-upload-cat-radio']");
    return r && r.value === "props";
  });
  assert.ok(propsPill, "Props pill must exist");
  propsPill.click();

  // Simulate file selection
  const mockFile = { name: "test_weapon.png", _dataUrl: "data:image/png;base64,weapon123" };
  fileInp.files = [mockFile];

  // Trigger change
  fileInp.onchange({ target: { files: [mockFile] } });

  // Fieldset should be disabled during upload
  assert.equal(fieldset.disabled, true, "Fieldset must be disabled during active upload");

  // Wait for mock file reader & post to finish
  await new Promise((r) => setTimeout(r, 40));

  assert.ok(lastPostedUpload, "Upload API post must be called");
  assert.equal(lastPostedUpload.payload.cat, "props", "Uploaded category payload must match chosen pill 'props'");
  assert.equal(lastPostedUpload.payload.nameZh, "test_weapon", "Uploaded item name must match file base name");

  // Verify view switched to 'my' tab and activeCategory became 'props'
  const currentCatsWrap = mountedRoot.querySelector("#ast-cats-wrap");
  assert.ok(currentCatsWrap, "Cats wrap must be rendered after upload completion");
  const activePill = currentCatsWrap.querySelector(".hw-pill.is-active");
  assert.ok(activePill, "Active pill must exist in category filter");
  assert.equal(activePill.getAttribute("data-ing-grp"), "props", "Gallery filter must switch to uploaded category 'props'");

  console.log("✓ Test 5 Passed: 上传归类与选中标签一致 (Upload payload and state matching) verified");

  console.log("\n========================================================");
  console.log("ALL PICKER CATEGORY PILLS TESTS PASSED SUCCESSFULLY!");
  console.log("========================================================");
})().catch((err) => {
  console.error("Test failure:", err);
  process.exitCode = 1;
});
