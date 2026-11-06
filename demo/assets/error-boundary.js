/* Install before application scripts. This module has no application dependencies. */
(function () {
  "use strict";
  if (window.HandrawErrors) return;
  const transport = window.fetch && window.fetch.bind(window);
  const incidents = new WeakMap();
  let reportTimes = [];
  let latestIncident = null;
  const errorTypes = new Set(["Error", "TypeError", "ReferenceError", "SyntaxError", "RangeError", "AbortError", "NetworkError", "ResourceError", "HTTPError"]);
  const eventKinds = new Set(["runtime", "unhandledrejection", "resource", "api", "boot", "render"]);
  const validId = (value) => /^[a-f0-9]{32}$/.test(String(value || "")) ? value : "";
  const eventId = () => window.crypto && typeof window.crypto.randomUUID === "function"
    ? window.crypto.randomUUID().replace(/-/g, "")
    : Array.from({length: 32}, () => Math.floor(Math.random() * 16).toString(16)).join("");
  const channel = () => {
    const path = window.location.pathname;
    const host = window.location.hostname;
    return ["studio", "forum", "admin"].find(name => path.startsWith("/" + name) || host.startsWith(name + ".")) || "main";
  };
  function sourceLocation(error, meta) {
    const stack = typeof error?.stack === "string" ? error.stack : "";
    const match = stack.match(/\/assets\/([A-Za-z0-9_.-]+\.js)(?:\?[^\s:)]*)?:(\d+):(\d+)/);
    let script = "";
    if (meta.source) {
      try {
        const source = new URL(meta.source, window.location.href);
        if (source.origin === window.location.origin && source.pathname.startsWith("/assets/")) script = source.pathname.split("/").pop();
      } catch (_) {}
    }
    return {
      script: /^[A-Za-z0-9_.-]{1,100}\.js$/.test(script) ? script : (match ? match[1].slice(0, 100) : ""),
      line: Number(meta.line || (match && match[2]) || 0),
      column: Number(meta.column || (match && match[3]) || 0)
    };
  }
  function report(error, meta = {}) {
    const object = error && (typeof error === "object" || typeof error === "function");
    if (object && incidents.has(error)) return incidents.get(error);
    const now = Date.now();
    reportTimes = reportTimes.filter(time => now - time < 60000);
    if (reportTimes.length >= 5 && !validId(error?.requestId) && latestIncident) {
      if (object) incidents.set(error, latestIncident);
      return latestIncident;
    }
    const incident = {id: validId(error?.requestId) || eventId(), listeners: []};
    if (object) incidents.set(error, incident);
    if (!transport || reportTimes.length >= 5) return incident;
    latestIncident = incident;
    reportTimes.push(now);
    const body = Object.assign({
      kind: eventKinds.has(meta.kind) ? meta.kind : "runtime", errorType: errorTypes.has(error?.name) ? error.name : "UnknownError", channel: channel(),
      status: Number(error?.status || 0), relatedRequestId: validId(error?.requestId), eventId: incident.id
    }, sourceLocation(error, meta));
    // No raw messages, stacks, URLs, query parameters, headers or bodies leave the browser.
    transport("/api/client-errors", {
      method: "POST", credentials: "same-origin", keepalive: true,
      headers: {"Content-Type": "application/json", "Accept": "application/json"}, body: JSON.stringify(body)
    }).then(async response => {
      if (!response.ok) return;
      const data = await response.json();
      if (!validId(error?.requestId) && validId(data.requestId)) {
        incident.id = data.requestId;
        incident.listeners.forEach(listener => listener(incident.id));
      }
    }).catch(() => {}); // Reporting failures never trigger another error report.
    return incident;
  }
  function show(error, incident, meta) {
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", () => show(error, incident, meta), {once: true});
      return;
    }
    document.getElementById("handraw-error-notice")?.remove();
    const panel = document.createElement("section");
    panel.id = "handraw-error-notice";
    panel.setAttribute("role", "alert");
    panel.style.cssText = "position:fixed;z-index:2147483647;bottom:24px;right:24px;left:24px;max-width:520px;margin-left:auto;padding:24px;box-sizing:border-box;background:#fffdf8;color:#2b2925;border:1px solid #d8c7b9;border-radius:14px;box-shadow:0 12px 48px #30221524;font:15px/1.65 system-ui,sans-serif";
    const title = document.createElement("h2");
    title.textContent = meta.kind === "boot" ? "页面暂时无法加载" : "刚才的操作遇到问题";
    title.style.cssText = "font-size:20px;margin:0 0 8px;font-family:Georgia,serif";
    const description = document.createElement("p");
    description.textContent = error?.status >= 400 && error?.status < 500
      ? error.message : "请稍后重试；如果页面无法继续操作，可以刷新页面。";
    description.style.cssText = "margin:0 0 14px;color:#625d54";
    const reference = document.createElement("p");
    reference.style.cssText = "font-size:12px;overflow-wrap:anywhere;user-select:all";
    const update = id => { reference.textContent = "问题编号：" + id; };
    update(incident.id);
    incident.listeners.push(id => { if (panel.isConnected) update(id); });
    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;gap:12px;flex-wrap:wrap;margin-top:16px";
    for (const [label, action] of [["刷新页面", () => window.location.reload()], ["关闭提示", () => panel.remove()]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.style.cssText = "padding:8px 15px;border:1px solid #b74227;background:#fffdf8;color:#a63d24;border-radius:7px;font:inherit;cursor:pointer";
      button.onclick = action;
      actions.appendChild(button);
    }
    panel.append(title, description, reference, actions);
    document.body.appendChild(panel);
  }
  function handle(error, meta = {}) {
    const incident = report(error, meta);
    show(error, incident, meta);
    return incident;
  }
  function apiError(response, data = {}, meta = {}) {
    data = data && typeof data === "object" ? data : {};
    const id = validId(data.requestId) || validId(response.headers?.get("X-Request-ID"));
    const message = response.status >= 500 ? "服务暂时出错，请稍后重试" : (data.error || "暂时无法完成操作");
    const error = new Error(message + (id ? "（问题编号：" + id + "）" : ""));
    error.name = "HTTPError";
    error.status = response.status;
    error.code = data.code || "";
    error.requestId = id;
    if (response.status >= 500) report(error, Object.assign({kind: "api"}, meta));
    return error;
  }
  async function fetchJson(url, options = {}, meta = {}) {
    const headers = Object.assign({Accept: "application/json"}, options.headers || {});
    let response;
    try { response = await window.fetch(url, Object.assign({}, options, {headers})); }
    catch (error) {
      if (error?.name === "AbortError") throw error;
      const failure = new Error("网络连接暂时不可用，请稍后重试");
      failure.name = "NetworkError";
      failure.code = "network_error";
      report(failure, Object.assign({kind: "api"}, meta));
      throw failure;
    }
    if (response.ok && (response.status === 204 || response.status === 205)) return {};
    let data;
    try { data = await response.json(); } catch (_) {
      const error = apiError(response, {error: "服务响应格式异常，请稍后重试"}, meta);
      report(error, Object.assign({kind: "api"}, meta));
      throw error;
    }
    if (!response.ok || data?.ok === false) throw apiError(response, data || {}, meta);
    return data;
  }
  window.HandrawErrors = {report, handle, apiError, fetchJson};
  window.addEventListener("error", event => {
    try {
      if (event.target && event.target !== window) {
        if (event.target.tagName !== "SCRIPT") return; // Optional images are not application crashes.
        const error = new Error("Application script failed to load");
        error.name = "ResourceError";
        handle(error, {kind: "resource", source: event.target.src});
      } else {
        handle(event.error || new Error("Runtime error"), {kind: "runtime", source: event.filename, line: event.lineno, column: event.colno});
      }
    } catch (_) {}
  }, true);
  window.addEventListener("unhandledrejection", event => {
    try { handle(event.reason, {kind: "unhandledrejection"}); } catch (_) {}
  });
})();
