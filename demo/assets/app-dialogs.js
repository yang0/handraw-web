/* Handraw accessible, asynchronous dialogs. No window.confirm/prompt/alert.
 * For destructive actions callers MUST await confirm; cancel resolves false.
 * Never dispatches a business API, preserves the caller's original guard.
 */
(function (global) {
  "use strict";
  if (global.HandrawDialogs) return;
  const CSS = \`
.hw-app-dialog-backdrop{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;background:rgba(15,23,42,.52);padding:20px;box-sizing:border-box}
.hw-app-dialog{box-sizing:border-box;width:min(440px,100%);max-height:min(85vh,720px);overflow:auto;border-radius:16px;padding:23px 24px 20px;background:var(--hw-surface,#fff);color:var(--hw-text,#1c2430);box-shadow:0 18px 70px rgba(0,0,0,.24);font:inherit}
.hw-app-dialog h2{font-size:18px;line-height:1.4;margin:0 0 12px;font-weight:650}
.hw-app-dialog p{font-size:14px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 18px}
.hw-app-dialog input{box-sizing:border-box;display:block;width:100%;height:44px;min-width:0;padding:8px 12px;font:inherit;color:inherit;border:1px solid #a0aaba;border-radius:8px;margin:0 0 20px;background:transparent}
.hw-app-dialog-actions{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}
.hw-app-dialog-actions button{font:inherit;font-weight:600;padding:9px 18px;min-height:40px;border-radius:8px;border:1px solid #b7c0c9;background:transparent;color:inherit;cursor:pointer}
.hw-app-dialog-actions button[data-primary]{background:#2663d6;color:#fff;border-color:#2663d6}
.hw-app-dialog-actions button:focus-visible,.hw-app-dialog input:focus-visible{outline:3px solid #7fa8f6;outline-offset:2px}
.hw-app-notice{position:fixed;right:18px;bottom:18px;z-index:2147483001;max-width:min(440px,calc(100vw - 36px));padding:13px 18px;border-radius:10px;background:#202e42;color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.18);font:14px/1.5 system-ui,sans-serif;overflow-wrap:anywhere}
@media(max-width:480px){.hw-app-dialog{padding:20px 16px}.hw-app-dialog-actions button{flex:1}}
\`;
  function ensureCss() {
    if (document.getElementById("hw-app-dialog-css")) return;
    const sheet = document.createElement("style");
    sheet.id = "hw-app-dialog-css";
    sheet.textContent = CSS;
    document.head.appendChild(sheet);
  }
  const queue = [];
  let active = false;
  function runNext() {
    if (active || !queue.length) return;
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", runNext, { once: true });
      return;
    }
    active = true;
    ensureCss();
    const task = queue.shift();
    const priorFocus = document.activeElement;
    const backdrop = document.createElement("div");
    backdrop.className = "hw-app-dialog-backdrop";
    const dialog = document.createElement("div");
    dialog.className = "hw-app-dialog";
    dialog.setAttribute("role", task.kind === "confirm" ? "alertdialog" : "dialog");
    dialog.setAttribute("aria-modal", "true");
    const title = document.createElement("h2");
    title.id = "hw-app-dialog-title";
    title.textContent = task.title || (task.kind === "confirm" ? "确认操作" : "请输入信息");
    dialog.setAttribute("aria-labelledby", title.id);
    const message = document.createElement("p");
    message.id = "hw-app-dialog-message";
    message.textContent = task.message;
    dialog.setAttribute("aria-describedby", message.id);
    dialog.append(title, message);
    let field = null;
    if (task.kind === "prompt") {
      field = document.createElement("input");
      field.type = "text";
      field.value = task.initial || "";
      field.maxLength = 500;
      field.setAttribute("aria-label", task.title || "输入内容");
      dialog.appendChild(field);
    }
    const actions = document.createElement("div");
    actions.className = "hw-app-dialog-actions";
    function makeButton(label, primary) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      if (primary) btn.dataset.primary = "true";
      actions.appendChild(btn);
      return btn;
    }
    const cancel = makeButton("取消", false);
    const accept = makeButton(task.kind === "prompt" ? "确定" : "确认", true);
    dialog.appendChild(actions);
    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);
    let finished = false;
    function finish(value) {
      if (finished) return;
      finished = true;
      backdrop.removeEventListener("keydown", onKeyDown);
      backdrop.remove();
      if (priorFocus && typeof priorFocus.focus === "function" && priorFocus.isConnected) {
        priorFocus.focus({ preventScroll: true });
      }
      active = false;
      task.resolve(value);
      runNext();
    }
    function onKeyDown(event) {
      if (event.key === "Escape") { event.preventDefault(); finish(task.kind === "confirm" ? false : null); return; }
      if (event.key === "Tab") {
        const stops = field ? [field, cancel, accept] : [cancel, accept];
        const first = stops[0], last = stops[stops.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }
    backdrop.addEventListener("keydown", onKeyDown);
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) finish(task.kind === "confirm" ? false : null);
    });
    cancel.addEventListener("click", () => finish(task.kind === "confirm" ? false : null));
    accept.addEventListener("click", () => finish(task.kind === "confirm" ? true : field.value));
    if (field) {
      field.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); finish(field.value); }
      });
    }
    (field || cancel).focus();
  }
  function open(kind, message, initial = "", title = "") {
    return new Promise((resolve) => {
      queue.push({ kind, message: String(message ?? ""), initial: String(initial ?? ""), title, resolve });
      runNext();
    });
  }
  function notice(message) {
    if (!document.body) return;
    ensureCss();
    let target = document.getElementById("hw-app-notice");
    if (!target) {
      target = document.createElement("div");
      target.id = "hw-app-notice";
      target.className = "hw-app-notice";
      target.setAttribute("role", "status");
      target.setAttribute("aria-live", "polite");
      document.body.appendChild(target);
    }
    target.textContent = String(message ?? "");
    if (target._dismiss) global.clearTimeout(target._dismiss);
    target._dismiss = global.setTimeout(() => target.remove(), 4200);
  }
  global.HandrawDialogs = Object.freeze({
    confirm: (message, title) => open("confirm", message, "", title),
    prompt: (message, initial, title) => open("prompt", message, initial, title),
    notice,
  });
})(window);
