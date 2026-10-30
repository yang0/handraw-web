"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

// Emoji detection regex (matches standard Unicode emoji ranges)
const EMOJI_REGEX = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;

class MockElement {
  constructor(id = "", parent = null) {
    this.id = id;
    this.parent = parent;
    this._innerHTML = "";
    this.childrenById = new Map();
    this.buttons = [];
    this.onclick = null;
    this.disabled = false;
    this.style = {};
  }

  get innerHTML() {
    let result = this._innerHTML;
    for (const [childId, childEl] of this.childrenById) {
      const placeholder = `<div id="${childId}"></div>`;
      if (result.includes(placeholder)) {
        result = result.replace(placeholder, `<div id="${childId}">${childEl.innerHTML}</div>`);
      } else {
        result += childEl.innerHTML;
      }
    }
    return result;
  }

  set innerHTML(html) {
    this._innerHTML = String(html);
    // Find nested id divs
    const idMatches = [...this._innerHTML.matchAll(/id=["']([^"']+)["']/g)];
    for (const m of idMatches) {
      const childId = m[1];
      if (!this.childrenById.has(childId)) {
        const child = new MockElement(childId, this);
        this.childrenById.set(childId, child);
      }
    }
  }

  querySelector(selector) {
    if (selector.startsWith("#")) {
      const targetId = selector.slice(1);
      if (this.id === targetId) return this;
      if (this.childrenById.has(targetId)) return this.childrenById.get(targetId);
      for (const child of this.childrenById.values()) {
        const found = child.querySelector(selector);
        if (found) return found;
      }
      // If it exists in innerHTML but not yet registered as a child
      if (this._innerHTML.includes(`id="${targetId}"`) || this._innerHTML.includes(`id='${targetId}'`)) {
        const el = new MockElement(targetId, this);
        this.childrenById.set(targetId, el);
        return el;
      }
    }
    return null;
  }

  querySelectorAll(selector) {
    if (this.childrenById.has("devices-list-container")) {
      return this.childrenById.get("devices-list-container").querySelectorAll(selector);
    }
    if (!this._buttons) {
      this._buttons = [];
      const regex = /data-action=["']([^"']+)["']\s+data-token-id=["']([^"']+)["']/g;
      let match;
      const html = this.innerHTML;
      while ((match = regex.exec(html)) !== null) {
        const btn = new MockElement();
        btn.attributes = {
          "data-action": match[1],
          "data-token-id": match[2],
        };
        btn.getAttribute = (attr) => btn.attributes[attr] || null;
        this._buttons.push(btn);
      }
    }
    return this._buttons;
  }
}

async function runTests() {
  const code = fs.readFileSync("demo/assets/device-auth.js", "utf8");

  // Verify no emojis are in the source file itself
  assert.ok(!EMOJI_REGEX.test(code), "device-auth.js source code must not contain emojis");

  const calls = [];
  const mockApiJson = async (url, opts = {}) => {
    calls.push({ url, opts });
    if (url.startsWith("/api/auth/device/lookup")) {
      return {
        ok: true,
        clientName: "VS Code Handraw Skill",
        scopes: ["publish", "library"],
        expiresAt: "2026-10-31T01:00:00Z",
        status: "pending",
      };
    }
    if (url === "/api/auth/device/approve") {
      return { ok: true };
    }
    if (url === "/api/auth/device/deny") {
      return { ok: true };
    }
    if (url === "/api/auth/tokens") {
      return {
        ok: true,
        tokens: [
          {
            id: "tok_12345",
            name: "VS Code Handraw Skill",
            scopes: ["publish", "library"],
            createdAt: "2026-10-31T00:30:00Z",
            lastUsedAt: "2026-10-31T00:35:00Z",
          },
        ],
      };
    }
    if (url.startsWith("/api/auth/tokens/") && url.endsWith("/revoke")) {
      return { ok: true };
    }
    return { ok: true };
  };

  const windowMock = {
    HANDRAW_SHARED: {
      esc: (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
      apiJson: mockApiJson,
      App: {
        state: {
          loggedIn: true,
          user: {
            username: "test_creator",
            displayName: "测试创作者",
          },
        },
      },
    },
    location: {
      search: "?view=device&code=ABCD-EFGH",
      href: "http://localhost:3080/?view=device&code=ABCD-EFGH",
    },
    confirm: () => true,
  };

  const context = {
    window: windowMock,
    URLSearchParams,
    document: {},
  };
  vm.createContext(context);
  vm.runInContext(code, context);

  const DA = context.window.HandrawDeviceAuth;
  assert.ok(DA, "HandrawDeviceAuth must be exported on window");
  assert.ok(DA.views.has("device"), "views must contain 'device'");
  assert.ok(DA.views.has("devices"), "views must contain 'devices'");

  // 1. Render device confirmation view
  const rootDevice = new MockElement("root");
  const renderedDevice = await DA.render(rootDevice, "device");
  assert.equal(renderedDevice, true);
  const deviceHtml = rootDevice.innerHTML;
  assert.ok(deviceHtml.includes("ABCD-EFGH"), "Must display user code ABCD-EFGH");
  assert.ok(deviceHtml.includes("VS Code Handraw Skill"), "Must display client name");
  assert.ok(deviceHtml.includes("设备自报名称"), "Must label client name as 设备自报名称");
  assert.ok(deviceHtml.includes("发布作品"), "Must describe publish scope in Chinese");
  assert.ok(deviceHtml.includes("同步个人库"), "Must describe library scope in Chinese");
  assert.ok(deviceHtml.includes("仅在你刚刚在自己电脑上发起绑定时点允许，并核对验证码与终端显示一致"), "Must display verification warning text");
  assert.ok(!EMOJI_REGEX.test(deviceHtml), "Rendered device HTML must not contain emojis");

  // Verify lookup API was called
  const lookupCall = calls.find((c) => c.url.includes("/api/auth/device/lookup"));
  assert.ok(lookupCall, "Must call /api/auth/device/lookup");
  assert.ok(lookupCall.url.includes("code=ABCD-EFGH"));

  // Test button click: Approve
  const approveBtn = rootDevice.querySelector("#btn-device-approve");
  assert.ok(approveBtn && typeof approveBtn.onclick === "function", "Approve button must be wired");
  await approveBtn.onclick();
  const approveCall = calls.find((c) => c.url === "/api/auth/device/approve");
  assert.ok(approveCall, "Clicking approve must call /api/auth/device/approve");
  assert.equal(approveCall.opts.body.code, "ABCD-EFGH");

  // 2. Render devices list view
  calls.length = 0;
  const rootDevices = new MockElement("root");
  const renderedDevices = await DA.render(rootDevices, "devices");
  assert.equal(renderedDevices, true);
  const devicesHtml = rootDevices.innerHTML;
  assert.ok(devicesHtml.includes("VS Code Handraw Skill"), "Must display token name in list");
  assert.ok(devicesHtml.includes("发布作品"), "Must display scopes in list");
  assert.ok(devicesHtml.includes("撤销"), "Must display revoke button");
  assert.ok(!EMOJI_REGEX.test(devicesHtml), "Rendered devices HTML must not contain emojis");

  // Verify tokens API was called
  const tokensCall = calls.find((c) => c.url === "/api/auth/tokens");
  assert.ok(tokensCall, "Must call /api/auth/tokens");

  // Test revoke button
  const revokeButtons = rootDevices.querySelectorAll('[data-action="revoke-token"]');
  assert.equal(revokeButtons.length, 1);
  assert.equal(revokeButtons[0].getAttribute("data-token-id"), "tok_12345");
  assert.ok(typeof revokeButtons[0].onclick === "function", "Revoke button must be wired");
  await revokeButtons[0].onclick();
  const revokeCall = calls.find((c) => c.url.includes("/api/auth/tokens/tok_12345/revoke"));
  assert.ok(revokeCall, "Clicking revoke must call /api/auth/tokens/<id>/revoke");

  // 3. Test not logged in state and P5 S.openLoginModal callback re-render
  let loginModalOpened = false;
  let loginModalReason = "";
  let loginModalCallback = null;
  windowMock.HANDRAW_SHARED.App.state.loggedIn = false;
  windowMock.HANDRAW_SHARED.openLoginModal = (reason, cb) => {
    loginModalOpened = true;
    loginModalReason = reason;
    loginModalCallback = cb;
  };
  windowMock.HANDRAW_SHARED.boot = async () => {
    windowMock.HANDRAW_SHARED.App.state.loggedIn = true;
  };

  const rootUnauth = new MockElement("root");
  await DA.render(rootUnauth, "device");
  assert.ok(rootUnauth.innerHTML.includes("请先登录"), "Must prompt to login when unauthenticated");

  const loginBtn = rootUnauth.querySelector("#btn-device-login");
  assert.ok(loginBtn && typeof loginBtn.onclick === "function", "Login button must exist");
  await loginBtn.onclick();

  assert.equal(loginModalOpened, true, "Clicking login button must call S.openLoginModal");
  assert.ok(loginModalReason.includes("登录"), "Reason must mention login");
  assert.ok(typeof loginModalCallback === "function", "Callback must be provided to openLoginModal");

  // Simulate successful login callback: re-renders device authorization view and keeps code
  await loginModalCallback();
  assert.ok(rootUnauth.innerHTML.includes("ABCD-EFGH"), "Must re-render device confirmation view preserving code");

  console.log("Device auth frontend views test: passed (device & devices views, openLoginModal re-render, buttons wired, confirm hooked, no emoji)");

  await runIntegratedMainAppSyncUrlTest();
}

async function runIntegratedMainAppSyncUrlTest() {
  const mainAppCode = fs.readFileSync("demo/assets/main-app.js", "utf8");
  const deviceAuthCode = fs.readFileSync("demo/assets/device-auth.js", "utf8");

  let currentUrl = "http://localhost:3080/?view=device&code=WXYZ-5678";
  const locationMock = {
    get pathname() { return "/"; },
    get search() {
      const u = new URL(currentUrl);
      return u.search;
    },
    set search(v) {
      const u = new URL(currentUrl);
      u.search = v;
      currentUrl = u.toString();
    },
    get href() { return currentUrl; },
    set href(v) { currentUrl = v; }
  };

  const historyMock = {
    replaceState(state, title, url) {
      currentUrl = new URL(url, "http://localhost:3080").toString();
    },
    pushState(state, title, url) {
      currentUrl = new URL(url, "http://localhost:3080").toString();
    }
  };

  let loginCallback = null;
  const sharedMock = {
    App: {
      view: "device",
      channel: "main",
      state: {
        loggedIn: false,
        user: null
      }
    },
    esc: (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    toast: () => {},
    channelUrl: () => "/",
    saveState: () => {},
    closeModal: () => {},
    initApp: async () => {},
    openLoginModal: (reason, cb) => {
      loginCallback = cb;
    },
    boot: async () => {
      sharedMock.App.state.loggedIn = true;
      sharedMock.App.state.user = { username: "device_user", displayName: "设备用户" };
    },
    apiJson: async (url) => {
      if (url.includes("/api/auth/device/lookup")) {
        return {
          ok: true,
          clientName: "Integrated Terminal Client",
          scopes: ["publish", "library"],
          expiresAt: "2026-10-31T01:00:00Z",
          status: "pending"
        };
      }
      return { ok: true };
    }
  };

  const docMock = {
    title: "",
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => new MockElement(id),
  };

  const windowMock = {
    HANDRAW_SHARED: sharedMock,
    location: locationMock,
    history: historyMock,
    document: docMock,
    addEventListener: () => {},
    scrollTo: () => {},
    confirm: () => true
  };

  const context = {
    window: windowMock,
    document: docMock,
    URL,
    URLSearchParams
  };
  vm.createContext(context);

  // Load main-app.js first
  vm.runInContext(mainAppCode, context);
  // Load device-auth.js second
  vm.runInContext(deviceAuthCode, context);

  const DA = context.window.HandrawDeviceAuth;
  assert.ok(DA, "HandrawDeviceAuth must be defined");

  // 1. Initial render when unauthenticated
  const root = new MockElement("root");
  await DA.render(root, "device");
  assert.ok(root.innerHTML.includes("请先登录"), "Must prompt to login");

  // 2. Click login button
  const loginBtn = root.querySelector("#btn-device-login");
  assert.ok(loginBtn, "Login button must exist");
  await loginBtn.onclick();
  assert.ok(typeof loginCallback === "function", "openLoginModal callback must be registered");

  // 3. Simulate syncUrl() being called during login process in main-app
  assert.ok(typeof context.window.HANDRAW_MAIN_SWITCH_VIEW === "function");
  sharedMock.App.view = "device";
  context.window.HANDRAW_MAIN_SWITCH_VIEW("device");

  // Verify that syncUrl() in main-app.js retained the code parameter!
  const paramsAfterSync = new URLSearchParams(locationMock.search);
  assert.equal(paramsAfterSync.get("code"), "WXYZ-5678", "syncUrl() in main-app must retain code parameter for device view");

  // 4. Execute the login callback: user logged in, device view re-rendered
  await loginCallback();

  // Verify:
  // (a) root rendered device confirmation with approval button
  const approveBtn = root.querySelector("#btn-device-approve");
  assert.ok(approveBtn, "Approve button (#btn-device-approve) must be rendered after login callback");
  assert.ok(root.innerHTML.includes("WXYZ-5678"), "Code WXYZ-5678 must be displayed");
  assert.ok(root.innerHTML.includes("Integrated Terminal Client"), "Client name must be displayed");

  // (b) URL still has code
  const finalParams = new URLSearchParams(locationMock.search);
  assert.equal(finalParams.get("code"), "WXYZ-5678", "URL search must preserve code parameter");
  assert.equal(finalParams.get("view"), "device", "URL view must be device");

  // (c) no emoji
  assert.ok(!EMOJI_REGEX.test(root.innerHTML), "No emojis in rendered HTML");

  console.log("Integrated main-app syncUrl + device-auth test: passed (code retained across syncUrl, approve button rendered)");
}

runTests().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});
