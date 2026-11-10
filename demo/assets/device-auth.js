/* Handraw Device Authorization & Authorized Devices Management */
(function () {
  "use strict";

  const S = window.HANDRAW_SHARED || {};
  const views = new Set(["device", "devices"]);
  const esc = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll('"', "&quot;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");

  const SCOPE_NAMES = {
    publish: "发布作品",
    library: "同步个人库",
  };

  function formatScopes(scopes) {
    if (!Array.isArray(scopes) || scopes.length === 0) {
      return "基本访问";
    }
    return scopes.map((s) => SCOPE_NAMES[s] || s).join("、");
  }

  function shell(root, title, body) {
    root.innerHTML = `<section class="hw-account-page"><div class="hw-subpage-bar"><a class="btn btn-sm" href="/?view=styles">&larr; 返回画风库</a></div><h1>${esc(title)}</h1>${body}<p id="device-auth-feedback" role="status" aria-live="polite" style="margin-top:16px;"></p></section>`;
  }

  function feedback(root, message, isError = false) {
    const el = root.querySelector("#device-auth-feedback");
    if (el) {
      el.textContent = message;
      el.style.color = isError ? "var(--color-danger, #c53030)" : "var(--ink-secondary, #4a453e)";
    }
  }

  let cachedDeviceCode = "";

  async function renderDeviceView(root) {
    const isLoggedIn = Boolean(S.App?.state?.loggedIn);
    const user = S.App?.state?.user || {};
    const params = new URLSearchParams(window.location.search);
    const urlCode = (params.get("code") || "").trim();
    if (urlCode) {
      cachedDeviceCode = urlCode;
    }
    const code = cachedDeviceCode || urlCode;

    if (!isLoggedIn) {
      shell(
        root,
        "设备授权",
        `<p class="hw-lead">请先登录账号。绑定设备需要先登录 Handraw 社区账号。</p>
        <div style="margin-top:20px;">
          <button type="button" class="btn btn-primary" id="btn-device-login">登录账号</button>
        </div>`
      );
      const loginBtn = root.querySelector("#btn-device-login");
      if (loginBtn) {
        loginBtn.onclick = () => {
          if (typeof S.openLoginModal === "function") {
            S.openLoginModal("登录账号以完成设备授权", async () => {
              if (typeof S.boot === "function") {
                try {
                  await S.boot();
                } catch (_) {}
              }
              // If URL lost code during modal login / syncUrl, restore it via history.replaceState
              if (cachedDeviceCode) {
                const sp = new URLSearchParams(window.location.search);
                if (!sp.get("code")) {
                  sp.set("code", cachedDeviceCode);
                  if (!sp.get("view")) sp.set("view", "device");
                  const nextUrl = `${window.location.pathname}?${sp.toString()}`;
                  try {
                    window.history.replaceState({ view: "device" }, "", nextUrl);
                  } catch (_) {}
                }
              }
              await renderDeviceView(root);
            });
          } else {
            window.location.reload();
          }
        };
      }
      return true;
    }

    if (code) {
      const sp = new URLSearchParams(window.location.search);
      if (!sp.get("code")) {
        sp.set("code", code);
        if (!sp.get("view")) sp.set("view", "device");
        const nextUrl = `${window.location.pathname}?${sp.toString()}`;
        try {
          window.history.replaceState({ view: "device" }, "", nextUrl);
        } catch (_) {}
      }
    }

    if (!code) {
      shell(
        root,
        "设备授权",
        `<p class="hw-lead">缺少设备验证码。请在终端命令中确认验证码后重新打开链接。</p>`
      );
      return true;
    }

    shell(
      root,
      "设备授权",
      `<div id="device-auth-container"><p style="color:var(--ink-muted);">正在查询设备码信息...</p></div>`
    );

    let info;
    try {
      info = await S.apiJson(`/api/auth/device/lookup?code=${encodeURIComponent(code)}`);
    } catch (err) {
      const container = root.querySelector("#device-auth-container");
      if (container) {
        container.innerHTML = `<div class="hw-detail-section-card" style="padding:24px;border:1px solid var(--paper-line);border-radius:8px;">
          <p style="color:var(--color-danger, #c53030);font-weight:600;">验证码不存在或已过期</p>
          <p style="color:var(--ink-muted);margin-top:8px;">该设备验证码可能已经过期或已处理，请在终端重新发起绑定。</p>
          <div style="margin-top:16px;">
            <a class="btn btn-sm" href="/?view=devices">查看已授权设备</a>
          </div>
        </div>`;
      }
      return true;
    }

    const container = root.querySelector("#device-auth-container");
    if (!container) return true;

    const displayName = user.displayName || user.username || "当前用户";
    const username = user.username || "";
    const clientName = info.clientName || "未命名设备";
    const scopesDesc = formatScopes(info.scopes);

    container.innerHTML = `
      <div class="hw-detail-section-card" style="padding:24px;border:1px solid var(--paper-line);border-radius:8px;max-width:560px;">
        <div style="margin-bottom:16px;">
          <span style="font-size:12px;color:var(--ink-muted);display:block;margin-bottom:4px;">登录账号</span>
          <span style="font-size:16px;font-weight:600;color:var(--ink-primary);">${esc(displayName)} (@${esc(username)})</span>
        </div>
        <div style="margin-bottom:16px;">
          <span style="font-size:12px;color:var(--ink-muted);display:block;margin-bottom:4px;">设备验证码</span>
          <span style="font-size:24px;font-weight:700;letter-spacing:2px;font-family:monospace;color:var(--brand-vermilion, #b74227);">${esc(code)}</span>
        </div>
        <div style="margin-bottom:16px;">
          <span style="font-size:12px;color:var(--ink-muted);display:block;margin-bottom:4px;">设备自报名称</span>
          <span style="font-size:15px;color:var(--ink-primary);">${esc(clientName)}</span>
        </div>
        <div style="margin-bottom:20px;">
          <span style="font-size:12px;color:var(--ink-muted);display:block;margin-bottom:4px;">申请授予权限</span>
          <span style="font-size:15px;color:var(--ink-primary);">${esc(scopesDesc)}</span>
        </div>
        <div style="padding:12px 16px;background:var(--paper-subtle, #f5f2eb);border-radius:6px;margin-bottom:24px;font-size:13px;line-height:1.6;color:var(--ink-secondary);">
          仅在你刚刚在自己电脑上发起绑定时点允许，并核对验证码与终端显示一致。
        </div>
        <div id="device-action-buttons" style="display:flex;gap:12px;">
          <button type="button" class="btn btn-primary" id="btn-device-approve">允许</button>
          <button type="button" class="btn" id="btn-device-deny">拒绝</button>
        </div>
      </div>
    `;

    const approveBtn = root.querySelector("#btn-device-approve");
    const denyBtn = root.querySelector("#btn-device-deny");
    const actionBtns = root.querySelector("#device-action-buttons");

    if (approveBtn) {
      approveBtn.onclick = async () => {
        approveBtn.disabled = true;
        if (denyBtn) denyBtn.disabled = true;
        try {
          await S.apiJson("/api/auth/device/approve", {
            method: "POST",
            body: { code },
          });
          if (actionBtns) {
            actionBtns.innerHTML = `
              <div style="padding:12px 16px;background:var(--paper-subtle, #f5f2eb);border-radius:6px;width:100%;">
                <p style="color:var(--ink-primary);font-weight:600;margin:0 0 6px 0;">已授权设备</p>
                <p style="color:var(--ink-secondary);font-size:13px;margin:0;">你可以返回终端继续操作。</p>
                <div style="margin-top:12px;">
                  <a class="btn btn-sm" href="/?view=devices">管理已授权设备</a>
                </div>
              </div>
            `;
          }
        } catch (err) {
          feedback(root, err.message || "授权操作失败，请重试", true);
          approveBtn.disabled = false;
          if (denyBtn) denyBtn.disabled = false;
        }
      };
    }

    if (denyBtn) {
      denyBtn.onclick = async () => {
        if (approveBtn) approveBtn.disabled = true;
        denyBtn.disabled = true;
        try {
          await S.apiJson("/api/auth/device/deny", {
            method: "POST",
            body: { code },
          });
          if (actionBtns) {
            actionBtns.innerHTML = `
              <div style="padding:12px 16px;background:var(--paper-subtle, #f5f2eb);border-radius:6px;width:100%;">
                <p style="color:var(--ink-primary);font-weight:600;margin:0 0 6px 0;">已拒绝授权</p>
                <p style="color:var(--ink-secondary);font-size:13px;margin:0;">该设备将无法通过此验证码获得访问凭据。</p>
              </div>
            `;
          }
        } catch (err) {
          feedback(root, err.message || "操作失败，请重试", true);
          if (approveBtn) approveBtn.disabled = false;
          denyBtn.disabled = false;
        }
      };
    }

    return true;
  }

  async function renderDevicesView(root) {
    const isLoggedIn = Boolean(S.App?.state?.loggedIn);

    if (!isLoggedIn) {
      shell(
        root,
        "已授权设备",
        `<p class="hw-lead">请先登录账号后再查看已授权设备。</p>
        <div style="margin-top:20px;">
          <button type="button" class="btn btn-primary" id="btn-devices-login">登录账号</button>
        </div>`
      );
      const loginBtn = root.querySelector("#btn-devices-login");
      if (loginBtn) {
        loginBtn.onclick = () => {
          if (typeof S.openLoginModal === "function") {
            S.openLoginModal("登录账号以查看已授权设备", async () => {
              if (typeof S.boot === "function") {
                try {
                  await S.boot();
                } catch (_) {}
              }
              await renderDevicesView(root);
            });
          } else {
            window.location.reload();
          }
        };
      }
      return true;
    }

    shell(
      root,
      "已授权设备",
      `<p class="hw-lead" style="margin-bottom:20px;">管理已授予个人令牌的设备与应用。撤销后对应设备将无法继续访问社区。</p>
      <div id="devices-list-container"><p style="color:var(--ink-muted);">正在加载设备列表...</p></div>`
    );

    async function loadTokens() {
      const container = root.querySelector("#devices-list-container");
      if (!container) return;

      let res;
      try {
        res = await S.apiJson("/api/auth/tokens");
      } catch (err) {
        container.innerHTML = `<p style="color:var(--color-danger, #c53030);">读取设备列表失败：${esc(err.message)}</p>`;
        return;
      }

      const tokens = res.tokens || [];
      if (tokens.length === 0) {
        container.innerHTML = `<div class="hw-detail-section-card" style="padding:32px;text-align:center;border:1px solid var(--paper-line);border-radius:8px;">
          <p style="color:var(--ink-muted);margin:0 0 12px 0;">当前没有已授权的设备或令牌。</p>
          <a class="btn btn-sm" href="/?view=skill">了解如何使用 Skill 绑定</a>
        </div>`;
        return;
      }

      let html = `<div style="display:flex;flex-direction:column;gap:12px;">`;
      for (const tok of tokens) {
        const lastUsedText = tok.lastUsedAt ? tok.lastUsedAt.replace("T", " ").replace("Z", "") : "未使用";
        const createdText = tok.createdAt ? tok.createdAt.replace("T", " ").replace("Z", "") : "";
        html += `
          <div class="hw-detail-section-card" style="display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border:1px solid var(--paper-line);border-radius:8px;background:var(--paper-card, #fffdfa);">
            <div>
              <div style="font-weight:600;font-size:15px;color:var(--ink-primary);margin-bottom:4px;">${esc(tok.name || "未命名设备")}</div>
              <div style="font-size:13px;color:var(--ink-secondary);margin-bottom:4px;">
                <span>权限：${esc(formatScopes(tok.scopes))}</span>
              </div>
              <div style="font-size:12px;color:var(--ink-muted);">
                <span>授权时间：${esc(createdText)}</span>
                <span style="margin-left:16px;">最后使用：${esc(lastUsedText)}</span>
              </div>
            </div>
            <div>
              <button type="button" class="btn btn-sm" data-action="revoke-token" data-token-id="${esc(tok.id)}">撤销</button>
            </div>
          </div>
        `;
      }
      html += `</div>`;
      container.innerHTML = html;

      container.querySelectorAll('[data-action="revoke-token"]').forEach((btn) => {
        btn.onclick = async () => {
          const tokenId = btn.getAttribute("data-token-id");
          if (!tokenId) return;
          const ok = await S.confirmAction?.("确定撤销该设备的访问权限吗？撤销后该设备将无法继续访问网站。", { danger: true, confirmText: "撤销授权" });
          if (!ok) return;

          btn.disabled = true;
          try {
            await S.apiJson(`/api/auth/tokens/${encodeURIComponent(tokenId)}/revoke`, {
              method: "POST",
              body: {},
            });
            await loadTokens();
          } catch (err) {
            feedback(root, err.message || "撤销失败，请重试", true);
            btn.disabled = false;
          }
        };
      });
    }

    await loadTokens();
    return true;
  }

  async function render(root, view) {
    if (!root) return false;
    if (view === "device") {
      return await renderDeviceView(root);
    }
    if (view === "devices") {
      return await renderDevicesView(root);
    }
    return false;
  }

  window.HandrawDeviceAuth = {
    views,
    render,
  };
})();
