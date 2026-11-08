/* Handraw Direct Messaging (Phase 1A) Frontend
 * Provides:
 * - Dual-tab message center (Notifications / Direct Messages)
 * - Navigation unread badge (>99 shows '99+', 0 hidden)
 * - Standalone /api/messages/unread polling (30s foreground, 5s conversation, visibility pause, logout clear)
 * - Read cursor reporting (monotonically advancing, displayed-only, visible-only)
 * - Blocking and reporting integration
 * - '发私信' button on user profiles and author info cards (omitted for self)
 * - Mobile responsive down to 390px viewport
 */
(function() {
  "use strict";

  function getS() {
    return window.HANDRAW_SHARED || window.HandrawShared || {};
  }

  function esc(s) {
    const sharedEsc = getS().esc;
    if (typeof sharedEsc === "function") return sharedEsc(s);
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async function apiJson(url, opts = {}) {
    const s = getS();
    if (typeof s.apiJson === "function") {
      return s.apiJson(url, opts);
    }
    const headers = { Accept: "application/json", ...(opts.headers || {}) };
    let body = opts.body;
    if (body && typeof body === "object" && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    const res = await fetch(url, { ...opts, headers, body });
    const data = await res.json();
    if (!res.ok) {
      const err = new Error(data?.error || `HTTP ${res.status}`);
      err.code = data?.code;
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function channelUrl(channel, params = {}) {
    const s = getS();
    if (typeof s.channelUrl === 'function') return s.channelUrl(channel, params);
    const q = new URLSearchParams(params).toString();
    const prefix = channel === 'main' ? '/' : '/' + channel + '/';
    return prefix + (q ? '?' + q : '');
  }

  function getApp() {
    return getS().App || window.App || {};
  }


  // Status and errors remain in-app and never block the JS event loop.
  function notice(message, type = "info") {
    const shared = getS();
    if (typeof shared.toast === "function") return shared.toast(message, type);
    const node = document.createElement("div");
    node.setAttribute("role", "status");
    node.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:999999;max-width:90vw;padding:12px 18px;border-radius:9px;background:#28231f;color:white;";
    node.textContent = String(message);
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  // State
  let unreadState = { notifications: 0, direct: 0, broadcasts: 0, total: 0 };
  let pollUnreadTimer = null;
  let pollConvTimer = null;
  let activeConversationId = null;
  let activePeerUser = null;
  let activeTab = "notifications"; // "notifications" | "dm"
  let conversationCache = [];
  let isSending = false;

  // CSS Injection
  function injectStyles() {
    if (document.getElementById("hw-messaging-styles")) return;
    const style = document.createElement("style");
    style.id = "hw-messaging-styles";
    style.textContent = `
      .hw-unread-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        font-size: 11px;
        font-weight: 800;
        line-height: 1;
        color: #fffdf9;
        background: var(--vermilion, #b74227);
        border-radius: 999px;
        margin-left: 4px;
        vertical-align: middle;
        box-shadow: 0 1px 3px rgba(183, 66, 39, 0.3);
      }
      .hw-msg-center-tabs {
        display: flex;
        gap: 8px;
        margin-bottom: 20px;
        border-bottom: 2px solid var(--line-soft, #e6ded2);
        padding-bottom: 8px;
      }
      .hw-msg-tab-btn {
        background: none;
        border: none;
        padding: 8px 16px;
        font-size: 15px;
        font-weight: 750;
        color: var(--ink-muted, #7c736a);
        cursor: pointer;
        border-radius: 8px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        transition: all 0.15s ease;
      }
      .hw-msg-tab-btn:hover {
        background: var(--paper-soft, #f4efe6);
        color: var(--ink-strong, #1f1b18);
      }
      .hw-msg-tab-btn.is-active {
        color: var(--vermilion, #b74227);
        background: rgba(183, 66, 39, 0.08);
      }
      .hw-dm-container {
        display: grid;
        grid-template-columns: 320px 1fr;
        gap: 16px;
        min-height: 520px;
        background: var(--paper-bg, #fbf7ee);
        border: 1px solid var(--line-soft, #e6ded2);
        border-radius: 12px;
        overflow: hidden;
      }
      .hw-dm-sidebar {
        border-right: 1px solid var(--line-soft, #e6ded2);
        display: flex;
        flex-direction: column;
        background: #fffdf9;
      }
      .hw-dm-sidebar-header {
        padding: 12px 16px;
        border-bottom: 1px solid var(--line-soft, #e6ded2);
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .hw-dm-conv-list {
        flex: 1;
        overflow-y: auto;
      }
      .hw-dm-conv-item {
        padding: 12px 14px;
        border-bottom: 1px solid var(--line-soft, #e6ded2);
        cursor: pointer;
        display: flex;
        gap: 10px;
        align-items: center;
        transition: background 0.12s ease;
      }
      .hw-dm-conv-item:hover {
        background: var(--paper-soft, #f4efe6);
      }
      .hw-dm-conv-item.is-active {
        background: rgba(183, 66, 39, 0.08);
        border-left: 3px solid var(--vermilion, #b74227);
      }
      .hw-dm-chat-pane {
        display: flex;
        flex-direction: column;
        background: #fffdf9;
        min-width: 0;
      }
      .hw-dm-chat-header {
        padding: 12px 16px;
        border-bottom: 1px solid var(--line-soft, #e6ded2);
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: var(--paper-bg, #fbf7ee);
      }
      .hw-dm-back-button {
        display: none;
      }
      .hw-dm-messages-area {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        min-height: 340px;
        max-height: 480px;
      }
      .hw-dm-bubble-wrap {
        display: flex;
        flex-direction: column;
        max-width: 78%;
      }
      .hw-dm-bubble-wrap.is-self {
        align-self: flex-end;
        align-items: flex-end;
      }
      .hw-dm-bubble-wrap.is-peer {
        align-self: flex-start;
        align-items: flex-start;
      }
      .hw-dm-bubble {
        padding: 10px 14px;
        border-radius: 12px;
        font-size: 14px;
        line-height: 1.5;
        word-break: break-word;
        white-space: pre-wrap;
      }
      .hw-dm-bubble-wrap.is-self .hw-dm-bubble {
        background: var(--ink-strong, #1f1b18);
        color: #fffdf9;
        border-bottom-right-radius: 2px;
      }
      .hw-dm-bubble-wrap.is-peer .hw-dm-bubble {
        background: var(--paper-soft, #f4efe6);
        color: var(--ink-strong, #1f1b18);
        border: 1px solid var(--line-soft, #e6ded2);
        border-bottom-left-radius: 2px;
      }
      .hw-dm-meta {
        font-size: 11px;
        color: var(--ink-muted, #7c736a);
        margin-top: 3px;
        display: flex;
        gap: 8px;
        align-items: center;
      }
      .hw-dm-read-status {
        font-weight: 700;
      }
      .hw-dm-read-status.is-read {
        color: var(--jade, #2e6f40);
      }
      .hw-dm-read-status.is-unread {
        color: var(--ink-muted, #7c736a);
      }
      .hw-dm-footer {
        padding: 12px 16px;
        border-top: 1px solid var(--line-soft, #e6ded2);
        background: var(--paper-bg, #fbf7ee);
      }
      .hw-dm-blocked-banner {
        padding: 10px 14px;
        background: rgba(183, 66, 39, 0.1);
        border: 1px solid rgba(183, 66, 39, 0.3);
        border-radius: 8px;
        color: var(--vermilion, #b74227);
        font-size: 13px;
        text-align: center;
      }
      .hw-dm-input-row {
        display: flex;
        gap: 8px;
        align-items: flex-end;
      }
      .hw-dm-textarea {
        flex: 1;
        resize: none;
        border: 1px solid var(--line-soft, #e6ded2);
        border-radius: 8px;
        padding: 8px 10px;
        font-family: inherit;
        font-size: 14px;
        line-height: 1.4;
        background: #fffdf9;
      }
      .hw-dm-textarea:focus {
        outline: none;
        border-color: var(--vermilion, #b74227);
      }
      .hw-dm-counter {
        font-size: 11.5px;
        color: var(--ink-muted, #7c736a);
        text-align: right;
        margin-top: 4px;
      }
      @media (max-width: 640px) {
        .hw-dm-back-button {
          display: inline-flex;
        }
        .hw-dm-container {
          grid-template-columns: 1fr;
        }
        .hw-dm-sidebar.is-chat-active {
          display: none;
        }
        .hw-dm-chat-pane {
          display: none;
        }
        .hw-dm-chat-pane.is-chat-active {
          display: flex;
        }
        .hw-dm-bubble-wrap {
          max-width: 90%;
        }
      }
    `;
    document.head.append(style);
  }

  // Unread polling & badge update
  async function fetchUnreadCounts() {
    const app = getApp();
    if (app?.state && app.state.loggedIn === false) {
      unreadState = { notifications: 0, direct: 0, broadcasts: 0, total: 0 };
      updateNavBadge();
      updateTabBadges();
      return;
    }
    try {
      const res = await apiJson("/api/messages/unread");
      if (res && res.ok) {
        unreadState = res;
        updateNavBadge();
        updateTabBadges();
      }
    } catch (_) {}
  }

  function updateNavBadge() {
    const msgLinks = document.querySelectorAll('.hw-topbar a[href*="notifications"], #hw-topbar-mount a[href*="notifications"], a[href*="notifications"], [data-nav-messages]');
    if (!msgLinks || msgLinks.length === 0) return;

    msgLinks.forEach(msgLink => {
      let badge = msgLink.querySelector(".hw-unread-badge");
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "hw-unread-badge";
        msgLink.append(badge);
      }
      if (unreadState.total <= 0) {
        badge.style.display = "none";
      } else {
        badge.style.display = "inline-flex";
        badge.textContent = unreadState.total > 99 ? "99+" : String(unreadState.total);
      }
    });
  }

  function updateTabBadges() {
    const nTab = document.querySelector("#hw-msg-tab-notifications .hw-unread-badge");
    if (nTab) {
      nTab.style.display = unreadState.notifications > 0 ? "inline-flex" : "none";
      nTab.textContent = unreadState.notifications > 99 ? "99+" : String(unreadState.notifications);
    }
    const dTab = document.querySelector("#hw-msg-tab-dm .hw-unread-badge");
    if (dTab) {
      const dmAndBcTotal = (unreadState.direct || 0) + (unreadState.broadcasts || 0);
      dTab.style.display = dmAndBcTotal > 0 ? "inline-flex" : "none";
      dTab.textContent = dmAndBcTotal > 99 ? "99+" : String(dmAndBcTotal);
    }
    const pinnedBcBadge = document.querySelector('.hw-dm-broadcast-pinned .hw-unread-badge');
    if (pinnedBcBadge) {
      pinnedBcBadge.style.display = unreadState.broadcasts > 0 ? "inline-flex" : "none";
      pinnedBcBadge.textContent = unreadState.broadcasts > 99 ? "99+" : String(unreadState.broadcasts);
    }
  }

  function startUnreadPolling() {
    stopUnreadPolling();
    fetchUnreadCounts();
    pollUnreadTimer = setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchUnreadCounts();
      }
    }, 30000);
  }

  function stopUnreadPolling() {
    if (pollUnreadTimer) {
      clearInterval(pollUnreadTimer);
      pollUnreadTimer = null;
    }
  }

  function startConvPolling() {
    stopConvPolling();
    pollConvTimer = setInterval(async () => {
      if (document.visibilityState !== "visible" || !activeConversationId) return;
      await pollIncrementalMessages(activeConversationId);
    }, 5000);
  }

  function stopConvPolling() {
    if (pollConvTimer) {
      clearInterval(pollConvTimer);
      pollConvTimer = null;
    }
  }

  // Conversation incremental fetch
  async function pollIncrementalMessages(convId) {
    const area = document.querySelector("#hw-dm-messages-area");
    if (!area || activeConversationId !== convId) return;

    const lastMsgEl = area.querySelector(".hw-dm-bubble-wrap:last-child");
    const lastId = lastMsgEl ? Number(lastMsgEl.dataset.msgId || 0) : 0;
    try {
      const res = await apiJson(`/api/dm/conversations/${convId}/messages?after=${lastId}`);
      if (res && res.ok) {
        if (res.conversation && res.conversation.peerLastReadMessageId) {
          const peerReadId = res.conversation.peerLastReadMessageId;
          area.querySelectorAll(".hw-dm-bubble-wrap.is-self").forEach(wrap => {
            const mid = Number(wrap.dataset.msgId || 0);
            if (mid <= peerReadId) {
              const statusEl = wrap.querySelector(".hw-dm-read-status");
              if (statusEl && !statusEl.classList.contains("is-read")) {
                statusEl.className = "hw-dm-read-status is-read";
                statusEl.textContent = "✓ 已读";
              }
            }
          });
        }
        if (res.messages && res.messages.length > 0) {
          let maxPeerId = 0;
          res.messages.forEach(m => {
            if (!area.querySelector(`[data-msg-id="${m.id}"]`)) {
              area.append(renderBubble(m));
              if (!m.isSelf && m.id > maxPeerId) maxPeerId = m.id;
            }
          });
          area.scrollTop = area.scrollHeight;
          if (maxPeerId > 0 && document.visibilityState === "visible") {
            markConversationRead(convId, maxPeerId);
          }
        }
      }
    } catch (_) {}
  }

  // Mark read cursor (monotonically advancing, displayed-only)
  async function markConversationRead(convId, messageId) {
    if (!messageId || messageId <= 0) return;
    try {
      await apiJson(`/api/dm/conversations/${convId}/read`, {
        method: "POST",
        body: { messageId }
      });
      const itemBadge = document.querySelector(`.hw-dm-conv-item[data-conv-id="${convId}"] .hw-unread-badge`);
      if (itemBadge) itemBadge.style.display = "none";
      await fetchUnreadCounts();
    } catch (_) {}
  }

  // Render a single message bubble
  function renderBubble(m) {
    const wrap = document.createElement("div");
    wrap.className = `hw-dm-bubble-wrap ${m.isSelf ? "is-self" : "is-peer"}`;
    wrap.dataset.msgId = String(m.id);

    const bubble = document.createElement("div");
    bubble.className = "hw-dm-bubble";
    bubble.textContent = m.body; // textContent escapes HTML safely

    const meta = document.createElement("div");
    meta.className = "hw-dm-meta";

    const timeSpan = document.createElement("span");
    timeSpan.textContent = formatMessageTime(m.createdAt);
    meta.append(timeSpan);

    if (m.isSelf) {
      const readSpan = document.createElement("span");
      readSpan.className = `hw-dm-read-status ${m.isRead ? "is-read" : "is-unread"}`;
      readSpan.textContent = m.isRead ? "✓ 已读" : "未读";
      meta.append(readSpan);
    } else {
      const reportBtn = document.createElement("button");
      reportBtn.type = "button";
      reportBtn.className = "btn btn-sm";
      reportBtn.style.padding = "0 4px";
      reportBtn.style.fontSize = "10px";
      reportBtn.style.height = "16px";
      reportBtn.style.lineHeight = "1";
      reportBtn.textContent = "举报";
      reportBtn.onclick = () => openReportModal(m.id);
      meta.append(reportBtn);
    }

    wrap.append(bubble, meta);
    return wrap;
  }

  function formatMessageTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      const hours = String(d.getHours()).padStart(2, "0");
      const mins = String(d.getMinutes()).padStart(2, "0");
      return `${hours}:${mins}`;
    } catch (_) {
      return iso;
    }
  }

  // Abuse Report Modal for DM Message
  async function openReportModal(messageId) {
    const reason = await getS().promptAction?.("请输入举报原因（例如：垃圾广告、骚扰辱骂、诈骗违规）：", { title: "举报私信", defaultValue: "违规私信内容", required: true });
    if (reason === null) return;
    const detail = await getS().promptAction?.("可补充详细说明（选填）：", { title: "补充举报说明", multiline: true });
    if (detail == null) return;
    apiJson("/api/reports", {
      method: "POST",
      body: {
        targetType: "dm_message",
        targetId: String(messageId),
        reason: (reason || "违规私信").trim(),
        detail: (detail || "").trim(),
      }
    }).then(() => {
      notice("举报已提交，平台将尽快审核处理。");
    }).catch(err => {
      notice("举报提交失败：" + (err.message || "请稍后重试"));
    });
  }

  // Build the Message Center Shell with dual tabs
  async function renderMessageCenter(root) {
    injectStyles();
    const urlParams = new URLSearchParams(window.location.search);
    const reqTab = urlParams.get("tab") || "notifications";
    const reqUser = urlParams.get("user") || "";
    activeTab = reqTab === "dm" || reqUser ? "dm" : "notifications";

    root.innerHTML = `
      <section class="hw-page-header">
        <h1 class="hw-page-title">消息中心</h1>
        <p class="hw-page-sub">查看系统提醒、社区动态互动与私信往来。</p>
      </section>
      <div class="hw-msg-center-tabs">
        <button type="button" class="hw-msg-tab-btn ${activeTab === "notifications" ? "is-active" : ""}" id="hw-msg-tab-notifications">
          🔔 互动通知 <span class="hw-unread-badge" style="display:${unreadState.notifications > 0 ? "inline-flex" : "none"};">${unreadState.notifications > 99 ? "99+" : unreadState.notifications}</span>
        </button>
        <button type="button" class="hw-msg-tab-btn ${activeTab === "dm" ? "is-active" : ""}" id="hw-msg-tab-dm">
          ✉️ 私信对话 <span class="hw-unread-badge" style="display:${unreadState.direct > 0 ? "inline-flex" : "none"};">${unreadState.direct > 99 ? "99+" : unreadState.direct}</span>
        </button>
      </div>
      <div id="hw-msg-tab-content"></div>
    `;

    root.querySelector("#hw-msg-tab-notifications").onclick = () => {
      activeTab = "notifications";
      root.querySelector("#hw-msg-tab-notifications").classList.add("is-active");
      root.querySelector("#hw-msg-tab-dm").classList.remove("is-active");
      renderNotificationsTab(root.querySelector("#hw-msg-tab-content"));
    };

    root.querySelector("#hw-msg-tab-dm").onclick = () => {
      activeTab = "dm";
      root.querySelector("#hw-msg-tab-dm").classList.add("is-active");
      root.querySelector("#hw-msg-tab-notifications").classList.remove("is-active");
      renderDirectMessagesTab(root.querySelector("#hw-msg-tab-content"), new URLSearchParams(window.location.search).get("user") || "");
    };

    const tabContent = root.querySelector("#hw-msg-tab-content");
    if (activeTab === "dm") {
      renderDirectMessagesTab(tabContent, reqUser);
    } else {
      renderNotificationsTab(tabContent);
    }
  }

  function returnToConversationList(container) {
    container.querySelector("#hw-dm-sidebar")?.classList.remove("is-chat-active");
    container.querySelector("#hw-dm-chat-pane")?.classList.remove("is-chat-active");
    stopConvPolling();
    activeConversationId = null;
    activePeerUser = null;
    container.querySelectorAll(".hw-dm-conv-item.is-active").forEach(item => item.classList.remove("is-active"));
    const url = new URL(window.location.href);
    url.searchParams.delete("user");
    url.searchParams.set("tab", "dm");
    window.history.replaceState(null, "", url.pathname + url.search);
  }

  // Render Notifications Tab
  async function renderNotificationsTab(container) {
    stopConvPolling();
    container.innerHTML = `<p style="padding:24px;text-align:center;color:var(--ink-muted);">正在读取通知…</p>`;
    try {
      const result = await apiJson("/api/notifications");
      container.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <p style="margin:0;font-size:14px;color:var(--ink-muted);">${result.unread || 0} 条未读通知</p>
          <button class="btn btn-sm" id="notifications-read-all">全部标为已读</button>
        </div>
        <div class="hw-notification-list">
          ${(result.items || []).map(n => `
            <article class="hw-detail-section-card ${n.read_at ? "" : "is-unread"}" style="margin-bottom:8px;padding:12px 16px;">
              <a href="${esc(targetUrl(n))}" data-notification-id="${n.id}" style="font-weight:700;color:var(--ink-strong);text-decoration:none;">${esc(n.title)}</a>
              <div style="font-size:11.5px;color:var(--ink-muted);margin-top:4px;">${esc(n.created_at)}</div>
            </article>
          `).join("") || '<p class="hw-empty-state" style="padding:32px;text-align:center;color:var(--ink-muted);">暂时没有新通知。收到回复、评论或处理结果后，会出现在这里。</p>'}
        </div>
        ${result.nextBefore ? '<button class="btn" id="notifications-more" style="margin-top:12px;">加载更早通知</button>' : ''}
      `;

      const readAll = container.querySelector("#notifications-read-all");
      if (readAll) readAll.onclick = async () => {
        readAll.disabled = true;
        try {
          await apiJson("/api/notifications/read", { method: "POST", body: { all: true } });
          fetchUnreadCounts();
          renderNotificationsTab(container);
        } catch (err) {
          readAll.disabled = false;
          const s = getS();
          if (typeof s.toast === "function") s.toast("标记已读失败：" + (err.message || "请重试"));
        }
      };

      container.querySelectorAll("[data-notification-id]").forEach(a => {
        a.addEventListener("click", async (ev) => {
          // Following the link unloads the page and cancels the request, so the
          // notification stayed unread. Wait for the write, then navigate.
          if (a.dataset.markingRead === "1") return;
          a.dataset.markingRead = "1";
          ev.preventDefault();
          try {
            await apiJson("/api/notifications/read", { method: "POST", body: { id: Number(a.dataset.notificationId) } });
            a.closest(".hw-detail-section-card")?.classList.remove("is-unread");
            fetchUnreadCounts();
          } catch (_) {}
          window.location.href = a.getAttribute("href");
        });
      });

      let before = result.nextBefore;
      const more = container.querySelector("#notifications-more");
      if (more) {
        more.onclick = async () => {
          more.disabled = true;
          try {
            const page = await apiJson(`/api/notifications?before=${before}`);
            const list = container.querySelector(".hw-notification-list");
            (page.items || []).forEach(n => {
              const article = document.createElement("article");
              article.className = `hw-detail-section-card ${n.read_at ? "" : "is-unread"}`;
              article.style.marginBottom = "8px";
              article.style.padding = "12px 16px";
              article.innerHTML = `
                <a href="${esc(targetUrl(n))}" data-notification-id="${n.id}" style="font-weight:700;color:var(--ink-strong);text-decoration:none;">${esc(n.title)}</a>
                <div style="font-size:11.5px;color:var(--ink-muted);margin-top:4px;">${esc(n.created_at)}</div>
              `;
              article.querySelector("a").onclick = async (ev) => {
                ev.preventDefault();
                try {
                  await apiJson("/api/notifications/read", { method: "POST", body: { id: n.id } });
                  article.classList.remove("is-unread");
                  fetchUnreadCounts();
                } catch (_) {}
                window.location.href = targetUrl(n);
              };
              list.append(article);
            });
            before = page.nextBefore;
            more.hidden = !before;
          } catch (_) {} finally {
            more.disabled = false;
          }
        };
      }
    } catch (e) {
      container.innerHTML = `<p style="padding:24px;text-align:center;color:var(--vermilion);">加载通知失败：${esc(e.message)}</p>`;
    }
  }

  function targetUrl(n) {
    if (n.target_type === "generation") {
      const S = getS();
      const u = (S.App && S.App.state && S.App.state.user && S.App.state.user.username) || "";
      return channelUrl("main", u ? { view: "profile", user: u, ptab: "generations" } : { view: "auth" });
    }
    if (n.target_type === "work") return channelUrl("main", { view: "work", id: n.target_id });
    if (n.target_type === "topic") return channelUrl("forum", { view: "topic", id: n.target_id });
    if (n.target_type === "asset") return channelUrl("main", { view: "asset", id: n.target_id });
    return channelUrl("main", { view: "notifications" });
  }

  // Render Direct Messages Tab (Master-Detail Split Pane)
  async function renderDirectMessagesTab(container, autoSelectUser) {
    container.innerHTML = `
      <div class="hw-dm-container" id="hw-dm-container">
        <aside class="hw-dm-sidebar" id="hw-dm-sidebar">
          <div class="hw-dm-sidebar-header">
            <strong style="font-size:14px;color:var(--ink-strong);">私信列表</strong>
            <button type="button" class="btn btn-sm btn-primary" id="hw-dm-new-btn">✉️ 新建对话</button>
          </div>
          <div class="hw-dm-conv-list" id="hw-dm-conv-list">
            <p style="padding:20px;text-align:center;color:var(--ink-muted);">正在加载私信会话…</p>
          </div>
        </aside>
        <section class="hw-dm-chat-pane" id="hw-dm-chat-pane">
          <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--ink-muted);padding:40px 20px;text-align:center;">
            <div style="font-size:36px;margin-bottom:12px;">✉️</div>
            <h3 style="margin:0 0 6px;color:var(--ink-strong);">选择左侧会话或发起新私信</h3>
            <p style="margin:0;font-size:13px;">与社区创作者点对点交流灵感与图型配方。</p>
          </div>
        </section>
      </div>
    `;

    container.querySelector("#hw-dm-new-btn").onclick = () => openNewConversationModal();

    await loadConversationList(container, autoSelectUser);
  }

  async function loadConversationList(container, autoSelectUser) {
    const listEl = container.querySelector("#hw-dm-conv-list");
    try {
      const [res, bcRes] = await Promise.all([
        apiJson("/api/dm/conversations").catch(() => ({ conversations: [] })),
        apiJson("/api/message-broadcasts?limit=1").catch(() => ({ broadcasts: [] }))
      ]);
      conversationCache = (res && res.conversations) || [];
      const latestBc = (bcRes && bcRes.broadcasts && bcRes.broadcasts[0]) || null;
      let latestBcTitle = "官方系统公告与服务通知";
      if (latestBc) {
        latestBcTitle = latestBc.isWithdrawn ? "【公告已撤回】" + latestBc.title : latestBc.title;
      }

      const pinnedHtml = `
        <div class="hw-dm-conv-item hw-dm-broadcast-pinned ${activeConversationId === "broadcasts" ? "is-active" : ""}" data-conv-id="broadcasts" style="border-left: 3px solid var(--vermilion, #b74227); background: rgba(183, 66, 39, 0.03);">
          <div class="hw-creator-avatar-sm" style="width:36px;height:36px;font-size:16px;flex-shrink:0;background:var(--paper-soft);display:flex;align-items:center;justify-content:center;border-radius:999px;">📢</div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong style="font-size:13.5px;color:var(--vermilion, #b74227);">管理员公告</strong>
              <small style="font-size:10.5px;color:var(--ink-muted);background:rgba(183,66,39,0.08);padding:1px 5px;border-radius:4px;font-weight:700;">官方</small>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px;">
              <span style="font-size:12px;color:var(--ink-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px;">${esc(latestBcTitle)}</span>
              ${unreadState.broadcasts > 0 ? `<span class="hw-unread-badge">${unreadState.broadcasts > 99 ? "99+" : unreadState.broadcasts}</span>` : ""}
            </div>
          </div>
        </div>
      `;

      const dmsHtml = conversationCache.map(c => `
        <div class="hw-dm-conv-item ${activeConversationId === c.id ? "is-active" : ""}" data-conv-id="${c.id}">
          <div class="hw-creator-avatar-sm seal-novice" style="width:36px;height:36px;font-size:14px;flex-shrink:0;">${esc((c.peer.displayName || c.peer.username || "创")[0])}</div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong style="font-size:13.5px;color:var(--ink-strong);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(c.peer.displayName || c.peer.username)}</strong>
              <small style="font-size:11px;color:var(--ink-muted);">${esc(formatMessageTime(c.updatedAt))}</small>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px;">
              <span style="font-size:12px;color:var(--ink-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px;">${esc(c.lastMessage ? c.lastMessage.body : "暂无内容")}</span>
              ${c.unreadCount > 0 ? `<span class="hw-unread-badge">${c.unreadCount > 99 ? "99+" : c.unreadCount}</span>` : ""}
            </div>
          </div>
        </div>
      `).join("");

      listEl.innerHTML = pinnedHtml + dmsHtml;

      listEl.querySelectorAll(".hw-dm-conv-item").forEach(item => {
        item.onclick = () => {
          if (item.dataset.convId === "broadcasts") {
            openBroadcastConversation(container);
          } else {
            const cid = Number(item.dataset.convId);
            openConversation(container, cid);
          }
        };
      });

      // Handle autoSelectUser parameter or broadcasts
      if (autoSelectUser === "broadcasts") {
        openBroadcastConversation(container);
      } else if (autoSelectUser) {
        const found = conversationCache.find(c => c.peer.username.toLowerCase() === autoSelectUser.toLowerCase());
        if (found) {
          openConversation(container, found.id);
        } else {
          prepareNewConversationWithUser(container, autoSelectUser);
        }
      }
    } catch (e) {
      listEl.innerHTML = `<p style="padding:20px;text-align:center;color:var(--vermilion);font-size:13px;">加载私信列表失败：${esc(e.message)}</p>`;
    }
  }

  // Open & render Admin Broadcasts (Read-only, non-replyable)
  async function openBroadcastConversation(container) {
    activeConversationId = "broadcasts";
    stopConvPolling();
    const sidebar = container.querySelector("#hw-dm-sidebar");
    const chatPane = container.querySelector("#hw-dm-chat-pane");

    sidebar.classList.add("is-chat-active");
    chatPane.classList.add("is-chat-active");

    container.querySelectorAll(".hw-dm-conv-item").forEach(el => {
      el.classList.toggle("is-active", el.dataset.convId === "broadcasts");
    });

    const curUser = getApp()?.state?.user;
    const isAdmin = curUser?.role === "admin";

    chatPane.innerHTML = `
      <div class="hw-dm-chat-header">
        <div style="display:flex;align-items:center;gap:10px;">
          <button type="button" class="btn btn-sm hw-dm-back-button" id="hw-dm-back-btn" style="padding:4px 8px;font-size:12px;">← 返回列表</button>
          <div class="hw-creator-avatar-sm" style="width:32px;height:32px;font-size:14px;background:var(--paper-soft);display:flex;align-items:center;justify-content:center;border-radius:999px;">📢</div>
          <div>
            <strong style="font-size:14px;color:var(--ink-strong);">管理员公告</strong>
            <span style="font-size:11.5px;color:var(--ink-muted);margin-left:4px;">(官方系统公告 · 只读)</span>
          </div>
        </div>
        <div>
          ${isAdmin ? `<button type="button" class="btn btn-sm btn-primary" id="hw-bc-publish-btn" style="font-size:12px;">📢 发布群发公告</button>` : ""}
        </div>
      </div>
      <div class="hw-dm-messages-area" id="hw-dm-messages-area">
        <p style="padding:40px;text-align:center;color:var(--ink-muted);">正在加载公告…</p>
      </div>
      <div class="hw-dm-footer" id="hw-dm-footer" style="padding:14px 16px;text-align:center;color:var(--ink-muted);font-size:13px;background:var(--paper-bg);border-top:1px solid var(--line-soft);">
        <span style="margin-right:6px;">📢</span>官方系统公告由管理员发布，仅供阅读，不支持回复。
      </div>
    `;

    chatPane.querySelector("#hw-dm-back-btn").onclick = () => returnToConversationList(container);

    if (isAdmin) {
      const pubBtn = chatPane.querySelector("#hw-bc-publish-btn");
      if (pubBtn) pubBtn.onclick = () => openAdminBroadcastModal(container);
    }

    try {
      const res = await apiJson("/api/message-broadcasts");
      const area = chatPane.querySelector("#hw-dm-messages-area");
      const broadcasts = (res && res.broadcasts) || [];

      if (broadcasts.length === 0) {
        area.innerHTML = `<p style="padding:40px;text-align:center;color:var(--ink-muted);font-size:13.5px;">暂无管理员公告。</p>`;
        return;
      }

      const list = [...broadcasts].reverse();
      area.innerHTML = list.map(b => `
        <div class="hw-bc-card ${b.isWithdrawn ? "is-withdrawn" : ""}" data-bc-id="${b.id}" style="padding:16px;border-radius:10px;background:${b.isWithdrawn ? 'rgba(0,0,0,0.03)' : '#fffdf9'};border:1px solid ${b.isWithdrawn ? 'var(--line-soft)' : 'rgba(183,66,39,0.2)'};margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
            <div>
              <strong style="font-size:15px;color:${b.isWithdrawn ? 'var(--ink-muted)' : 'var(--ink-strong)'};">📌 ${esc(b.title)}</strong>
              <div style="font-size:11.5px;color:var(--ink-muted);margin-top:2px;">
                ${b.isWithdrawn ? `【公告已撤回】发布于 ${formatMessageTime(b.publishedAt)}` : `发布于 ${formatMessageTime(b.publishedAt)}`}
              </div>
            </div>
            ${isAdmin && !b.isWithdrawn ? `<button type="button" class="btn btn-sm btn-bc-withdraw" data-bc-id="${b.id}" style="padding:2px 8px;font-size:11px;color:var(--vermilion);">撤回公告</button>` : ""}
          </div>
          ${b.isWithdrawn ? `
            <div style="font-size:13px;color:var(--ink-muted);font-style:italic;">【公告已撤回】正文已被管理员撤回</div>
          ` : `
            <div style="font-size:14px;color:var(--ink-strong);line-height:1.6;white-space:pre-wrap;word-break:break-word;">${esc(b.body)}</div>
          `}
        </div>
      `).join("");

      area.scrollTop = area.scrollHeight;

      // Wire withdraw buttons
      if (isAdmin) {
        area.querySelectorAll(".btn-bc-withdraw").forEach(btn => {
          btn.onclick = async () => {
            const bcId = btn.dataset.bcId;
            if (!await getS().confirmAction?.("确定要撤回该公告吗？撤回后所有用户正文将被隐藏，未读数将被移除。", { danger: true, confirmText: "撤回公告" })) return;
            try {
              await apiJson(`/api/admin/message-broadcasts/${bcId}/withdraw`, { method: "POST" });
              openBroadcastConversation(container);
            } catch (err) {
              notice("撤回失败：" + (err.message || "请稍后重试"));
            }
          };
        });
      }

      // Mark unread broadcasts as read
      let markedAny = false;
      for (const b of broadcasts) {
        if (!b.isRead && !b.isWithdrawn) {
          await apiJson(`/api/message-broadcasts/${b.id}/read`, { method: "POST" }).catch(() => {});
          markedAny = true;
        }
      }
      if (markedAny) {
        const pinnedBadge = container.querySelector('.hw-dm-broadcast-pinned .hw-unread-badge');
        if (pinnedBadge) pinnedBadge.style.display = "none";
        fetchUnreadCounts();
      }
    } catch (err) {
      chatPane.querySelector("#hw-dm-messages-area").innerHTML = `<p style="padding:40px;text-align:center;color:var(--vermilion);">加载公告失败：${esc(err.message)}</p>`;
    }
  }

  // Admin Broadcast Publish Modal ("先预览再二次确认")
  function openAdminBroadcastModal(container) {
    let modalBackdrop = document.getElementById("hw-bc-modal");
    if (modalBackdrop) modalBackdrop.remove();

    modalBackdrop = document.createElement("div");
    modalBackdrop.id = "hw-bc-modal";
    modalBackdrop.style.cssText = `
      position: fixed; inset: 0; background: rgba(0,0,0,0.5);
      display: flex; align-items: center; justify-content: center; z-index: 10000;
      padding: 16px;
    `;

    function renderStep1() {
      modalBackdrop.innerHTML = `
        <div style="background: #fffdf9; border-radius: 12px; width: 100%; max-width: 540px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); border: 1px solid var(--line-soft);">
          <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h3 style="margin:0; font-size: 17px; color: var(--ink-strong);">📢 发布全员群发公告</h3>
            <button type="button" class="btn btn-sm" id="hw-bc-close-btn" style="border:none; font-size:16px;">✕</button>
          </div>
          <div style="margin-bottom: 14px;">
            <label style="display:block; font-size: 13px; font-weight:700; margin-bottom: 6px; color: var(--ink-strong);">公告标题 (4–80 字)</label>
            <input class="hw-input" id="hw-bc-title-input" placeholder="请输入公告标题…" style="width:100%; box-sizing:border-box; padding: 8px 10px; border-radius: 6px; border: 1px solid var(--line-soft);" maxlength="80" />
          </div>
          <div style="margin-bottom: 16px;">
            <label style="display:block; font-size: 13px; font-weight:700; margin-bottom: 6px; color: var(--ink-strong);">公告正文 (1–5000 字，纯文本)</label>
            <textarea class="hw-dm-textarea" id="hw-bc-body-input" rows="5" placeholder="请输入公告正文内容…" style="width:100%; box-sizing:border-box;" maxlength="5000"></textarea>
          </div>
          <div style="display:flex; justify-content: flex-end; gap: 8px;">
            <button type="button" class="btn" id="hw-bc-cancel-btn">取消</button>
            <button type="button" class="btn btn-primary" id="hw-bc-preview-btn">预览公告 (先预览)</button>
          </div>
        </div>
      `;

      modalBackdrop.querySelector("#hw-bc-close-btn").onclick = () => modalBackdrop.remove();
      modalBackdrop.querySelector("#hw-bc-cancel-btn").onclick = () => modalBackdrop.remove();
      modalBackdrop.querySelector("#hw-bc-preview-btn").onclick = () => {
        const title = modalBackdrop.querySelector("#hw-bc-title-input").value.trim();
        const body = modalBackdrop.querySelector("#hw-bc-body-input").value.trim();

        if (title.length < 4 || title.length > 80) {
          notice("公告标题长度须在 4–80 个字之间");
          return;
        }
        if (body.length < 1 || body.length > 5000) {
          notice("公告正文长度须在 1–5000 个字之间");
          return;
        }
        if (/<[a-zA-Z\/][^>]*>/.test(body)) {
          notice("公告正文暂不支持 HTML 内容");
          return;
        }

        renderStep2(title, body);
      };
    }

    function renderStep2(title, body) {
      modalBackdrop.innerHTML = `
        <div style="background: #fffdf9; border-radius: 12px; width: 100%; max-width: 540px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); border: 1px solid var(--line-soft);">
          <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
            <h3 style="margin:0; font-size: 17px; color: var(--ink-strong);">👁️ 公告效果预览</h3>
            <button type="button" class="btn btn-sm" id="hw-bc-close-btn" style="border:none; font-size:16px;">✕</button>
          </div>

          <div style="background: var(--paper-bg); border: 1px solid rgba(183,66,39,0.25); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
            <strong style="font-size: 15px; color: var(--ink-strong); display:block; margin-bottom: 6px;">📌 ${esc(title)}</strong>
            <div style="font-size: 13.5px; color: var(--ink-strong); line-height: 1.5; white-space: pre-wrap; word-break: break-word;">${esc(body)}</div>
          </div>

          <div style="padding: 10px 12px; background: rgba(183,66,39,0.08); border-radius: 6px; font-size: 12px; color: var(--vermilion, #b74227); line-height: 1.4; margin-bottom: 18px;">
            ⚠️ <strong>发送确认提示</strong>：本公告将向全站所有已注册用户发送，每位用户未读数 +1。发布后内容不可修改，仅可撤回。之后新注册的用户将不会收到此公告。
          </div>

          <div style="display:flex; justify-content: flex-end; gap: 8px;">
            <button type="button" class="btn" id="hw-bc-back-edit-btn">返回修改</button>
            <button type="button" class="btn btn-primary" id="hw-bc-confirm-send-btn">向全部现有用户发送</button>
          </div>
        </div>
      `;

      modalBackdrop.querySelector("#hw-bc-close-btn").onclick = () => modalBackdrop.remove();
      modalBackdrop.querySelector("#hw-bc-back-edit-btn").onclick = () => {
        renderStep1();
        modalBackdrop.querySelector("#hw-bc-title-input").value = title;
        modalBackdrop.querySelector("#hw-bc-body-input").value = body;
      };

      const sendBtn = modalBackdrop.querySelector("#hw-bc-confirm-send-btn");
      sendBtn.onclick = async () => {
        sendBtn.disabled = true;
        sendBtn.textContent = "发送中…";
        try {
          const reqId = "bc_req_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
          const res = await apiJson("/api/admin/message-broadcasts", {
            method: "POST",
            body: { title, body, requestId: reqId }
          });
          if (res && res.ok) {
            notice("公告发布成功！");
            modalBackdrop.remove();
            openBroadcastConversation(container);
            fetchUnreadCounts();
          }
        } catch (err) {
          notice("发布失败：" + (err.message || "请稍后再试"));
          sendBtn.disabled = false;
          sendBtn.textContent = "向全部现有用户发送";
        }
      };
    }

    renderStep1();
    document.body.append(modalBackdrop);
  }

  // Open & render a specific conversation
  async function openConversation(container, convId) {
    activeConversationId = convId;
    const sidebar = container.querySelector("#hw-dm-sidebar");
    const chatPane = container.querySelector("#hw-dm-chat-pane");

    // Responsive toggle
    sidebar.classList.add("is-chat-active");
    chatPane.classList.add("is-chat-active");

    // Update active highlight in sidebar list
    container.querySelectorAll(".hw-dm-conv-item").forEach(el => {
      el.classList.toggle("is-active", Number(el.dataset.convId) === convId);
    });

    chatPane.innerHTML = `<p style="padding:40px;text-align:center;color:var(--ink-muted);">正在加载对话…</p>`;

    try {
      const res = await apiJson(`/api/dm/conversations/${convId}/messages`);
      if (!res || !res.ok) throw new Error(res?.error || "加载对话失败");

      const conv = res.conversation;
      activePeerUser = conv.peer;

      chatPane.innerHTML = `
        <div class="hw-dm-chat-header">
          <div style="display:flex;align-items:center;gap:10px;">
            <button type="button" class="btn btn-sm hw-dm-back-button" id="hw-dm-back-btn" style="padding:4px 8px;font-size:12px;">← 返回列表</button>
            <div class="hw-creator-avatar-sm seal-novice" style="width:32px;height:32px;font-size:13px;">${esc((conv.peer.displayName || conv.peer.username)[0])}</div>
            <div>
              <strong style="font-size:14px;color:var(--ink-strong);">@${esc(conv.peer.displayName || conv.peer.username)}</strong>
              <span style="font-size:11.5px;color:var(--ink-muted);margin-left:4px;">(${esc(conv.peer.username)})</span>
            </div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <button type="button" class="btn btn-sm" id="hw-dm-block-btn" style="font-size:12px;">${conv.isBlocked ? "解除拉黑" : "🚫 拉黑"}</button>
          </div>
        </div>
        <div class="hw-dm-messages-area" id="hw-dm-messages-area"></div>
        <div class="hw-dm-footer" id="hw-dm-footer">
          ${conv.isBlocked ? `
            <div class="hw-dm-blocked-banner">双方存在拉黑关系，无法发送新私信（历史消息可阅读）。</div>
          ` : `
            <div class="hw-dm-input-row">
              <textarea class="hw-dm-textarea" id="hw-dm-input" rows="2" placeholder="输入私信内容（纯文本，1–2000 字，Enter 发送，Shift+Enter 换行）…"></textarea>
              <button type="button" class="btn btn-primary" id="hw-dm-send-btn" style="align-self:stretch;display:flex;align-items:center;">发送</button>
            </div>
            <div class="hw-dm-counter" id="hw-dm-counter">0 / 2000 字</div>
          `}
        </div>
      `;

      // Back button on mobile
      chatPane.querySelector("#hw-dm-back-btn").onclick = () => returnToConversationList(container);

      // Block/Unblock button
      chatPane.querySelector("#hw-dm-block-btn").onclick = async () => {
        const isBlocked = conv.isBlocked;
        if (!isBlocked && !await getS().confirmAction?.(`确定要拉黑用户 @${conv.peer.username} 吗？拉黑后双方无法互发私信。`, { danger: true, confirmText: "确认拉黑" })) return;
        try {
          if (isBlocked) {
            await apiJson(`/api/dm/blocks/${conv.peer.id}`, { method: "DELETE" });
          } else {
            await apiJson("/api/dm/blocks", { method: "POST", body: { userId: conv.peer.id } });
          }
          openConversation(container, convId);
        } catch (err) {
          notice("操作失败：" + (err.message || "请稍后重试"));
        }
      };

      // Populate messages
      const area = chatPane.querySelector("#hw-dm-messages-area");
      let maxPeerId = 0;
      (res.messages || []).forEach(m => {
        area.append(renderBubble(m));
        if (!m.isSelf && m.id > maxPeerId) maxPeerId = m.id;
      });
      area.scrollTop = area.scrollHeight;

      // Mark read only after body is successfully displayed and page is visible
      if (maxPeerId > 0 && document.visibilityState === "visible") {
        markConversationRead(convId, maxPeerId);
      }

      // Wire send message
      const input = chatPane.querySelector("#hw-dm-input");
      const sendBtn = chatPane.querySelector("#hw-dm-send-btn");
      const counter = chatPane.querySelector("#hw-dm-counter");

      if (input && sendBtn) {
        input.oninput = () => {
          const nonWsLen = input.value.replace(/\s+/g, "").length;
          counter.textContent = `${nonWsLen} / 2000 字`;
          counter.style.color = nonWsLen > 2000 ? "var(--vermilion, #b74227)" : "var(--ink-muted, #7c736a)";
        };

        input.onkeydown = (e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            doSend();
          }
        };

        sendBtn.onclick = () => doSend();

        async function doSend() {
          if (isSending) return;
          const text = input.value.trim();
          const nonWsLen = text.replace(/\s+/g, "").length;
          if (nonWsLen < 1) {
            notice("请输入私信内容（不能全为空白字符）");
            return;
          }
          if (nonWsLen > 2000) {
            notice("私信内容过长（最多 2000 个非空白字符）");
            return;
          }
          if (/<[a-zA-Z\/][^>]*>/.test(text)) {
            notice("首版私信暂不支持 HTML 内容");
            return;
          }

          isSending = true;
          sendBtn.disabled = true;
          sendBtn.textContent = "发送中…";

          const clientMessageId = `cm_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

          try {
            const sendRes = await apiJson("/api/dm/messages", {
              method: "POST",
              body: {
                recipientId: conv.peer.id,
                body: text,
                clientMessageId: clientMessageId,
              }
            });

            if (sendRes && sendRes.ok && sendRes.message) {
              input.value = "";
              counter.textContent = "0 / 2000 字";
              area.append(renderBubble(sendRes.message));
              area.scrollTop = area.scrollHeight;
              fetchUnreadCounts();
            }
          } catch (err) {
            notice("发送失败：" + (err.message || "请稍后再试"));
          } finally {
            isSending = false;
            sendBtn.disabled = false;
            sendBtn.textContent = "发送";
            input.focus();
          }
        }
      }

      // Start 5s incremental polling
      startConvPolling();
    } catch (err) {
      chatPane.innerHTML = `<p style="padding:40px;text-align:center;color:var(--vermilion);">加载会话失败：${esc(err.message)}</p>`;
    }
  }

  // Prepare a blank chat pane to start a brand new conversation with a specified username
  function prepareNewConversationWithUser(container, targetUsername) {
    const sidebar = container.querySelector("#hw-dm-sidebar");
    const chatPane = container.querySelector("#hw-dm-chat-pane");

    sidebar.classList.add("is-chat-active");
    chatPane.classList.add("is-chat-active");

    chatPane.innerHTML = `
      <div class="hw-dm-chat-header">
        <div style="display:flex;align-items:center;gap:10px;">
          <button type="button" class="btn btn-sm hw-dm-back-button" id="hw-dm-back-btn" style="padding:4px 8px;font-size:12px;">← 返回列表</button>
          <div class="hw-creator-avatar-sm seal-novice" style="width:32px;height:32px;font-size:13px;">${esc(targetUsername[0])}</div>
          <div>
            <strong style="font-size:14px;color:var(--ink-strong);">发私信给 @${esc(targetUsername)}</strong>
          </div>
        </div>
      </div>
      <div class="hw-dm-messages-area" id="hw-dm-messages-area">
        <div style="padding:32px;text-align:center;color:var(--ink-muted);font-size:13px;">
          这将是你们的第一条对话消息。文明友善交流，禁止垃圾广告与骚扰。
        </div>
      </div>
      <div class="hw-dm-footer">
        <div class="hw-dm-input-row">
          <textarea class="hw-dm-textarea" id="hw-dm-input" rows="2" placeholder="输入私信内容（纯文本，1–2000 字，Enter 发送）…"></textarea>
          <button type="button" class="btn btn-primary" id="hw-dm-send-btn" style="align-self:stretch;">发送</button>
        </div>
        <div class="hw-dm-counter" id="hw-dm-counter">0 / 2000 字</div>
      </div>
    `;

    chatPane.querySelector("#hw-dm-back-btn").onclick = () => returnToConversationList(container);

    const input = chatPane.querySelector("#hw-dm-input");
    const sendBtn = chatPane.querySelector("#hw-dm-send-btn");
    const counter = chatPane.querySelector("#hw-dm-counter");

    input.oninput = () => {
      const nonWsLen = input.value.replace(/\s+/g, "").length;
      counter.textContent = `${nonWsLen} / 2000 字`;
    };

    async function doFirstSend() {
      const text = input.value.trim();
      const nonWsLen = text.replace(/\s+/g, "").length;
      if (nonWsLen < 1 || nonWsLen > 2000) {
        notice("请输入 1–2000 个非空白字符的私信内容");
        return;
      }
      sendBtn.disabled = true;
      sendBtn.textContent = "发送中…";
      try {
        const res = await apiJson("/api/dm/messages", {
          method: "POST",
          body: {
            recipientUsername: targetUsername,
            body: text,
            clientMessageId: `cm_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
          }
        });
        if (res && res.ok) {
          await loadConversationList(container, targetUsername);
        }
      } catch (err) {
        notice("发送失败：" + (err.message || "请稍后重试"));
        sendBtn.disabled = false;
        sendBtn.textContent = "发送";
      }
    }

    input.onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        doFirstSend();
      }
    };
    sendBtn.onclick = () => doFirstSend();
  }

  // Open New Conversation Dialog
  async function openNewConversationModal() {
    const username = await getS().promptAction?.("请输入要发私信的用户账号 ID / 用户名（例如：momo_design）：", { title: "新建私信", required: true });
    if (!username || !username.trim()) return;
    const clean = username.trim();
    if (getApp()?.state?.user && clean.toLowerCase() === getApp().state.user.username.toLowerCase()) {
      notice("不能给自己发送私信");
      return;
    }
    const container = document.querySelector("#hw-dm-container");
    if (container) {
      prepareNewConversationWithUser(container, clean);
    } else {
      window.location.href = channelUrl("main", { view: "notifications", tab: "dm", user: clean });
    }
  }

  // Decorate User Profile & Author Cards with '发私信' button
  function mountProfileAndAuthorDMLinks() {
    const curUser = getApp()?.state?.user;
    if (!getApp()?.state?.loggedIn || !curUser) return;

    // 1. User Profile Page Hero Actions
    const filterBtn = document.querySelector("#prof-filter-author-btn");
    if (filterBtn && !document.querySelector("#prof-send-dm-btn")) {
      const urlParams = new URLSearchParams(window.location.search);
      const targetUser = urlParams.get("user") || "";
      if (targetUser && targetUser.toLowerCase() !== curUser.username.toLowerCase()) {
        const dmBtn = document.createElement("button");
        dmBtn.type = "button";
        dmBtn.className = "btn";
        dmBtn.id = "prof-send-dm-btn";
        dmBtn.textContent = "✉️ 发私信";
        dmBtn.onclick = () => {
          window.location.href = channelUrl("main", { view: "notifications", tab: "dm", user: targetUser });
        };
        filterBtn.insertAdjacentElement("afterend", dmBtn);
      }
    }

    // 2. Forum Sidebar Author Card
    const forumAuthorBtn = document.querySelector(".forum-side-card [data-open-creator]");
    if (forumAuthorBtn && !document.querySelector("[data-sidebar-dm-btn]")) {
      const author = forumAuthorBtn.getAttribute("data-open-creator") || "";
      if (author && author.toLowerCase() !== curUser.username.toLowerCase()) {
        const sideDmBtn = document.createElement("button");
        sideDmBtn.type = "button";
        sideDmBtn.className = "btn btn-sm";
        sideDmBtn.dataset.sidebarDmBtn = "1";
        sideDmBtn.style.width = "100%";
        sideDmBtn.style.justifyContent = "center";
        sideDmBtn.style.marginTop = "6px";
        sideDmBtn.textContent = "✉️ 发私信";
        sideDmBtn.onclick = () => {
          window.location.href = channelUrl("main", { view: "notifications", tab: "dm", user: author });
        };
        forumAuthorBtn.insertAdjacentElement("afterend", sideDmBtn);
      }
    }
  }

  // Hook into HandrawAccountTools
  function hookAccountTools() {
    if (window.HandrawAccountTools) {
      const origRender = window.HandrawAccountTools.render;
      window.HandrawAccountTools.render = function(root, view) {
        if (view === "notifications") {
          renderMessageCenter(root);
          return true;
        }
        return origRender.apply(this, arguments);
      };
    }
  }

  // Hook applyBootState to sync unread polling and badge on boot / login / logout
  function hookBoot() {
    const s = getS();
    if (s && typeof s.applyBootState === "function" && !s._dmBootHooked) {
      s._dmBootHooked = true;
      const origApplyBoot = s.applyBootState;
      s.applyBootState = function(boot) {
        const ret = origApplyBoot.apply(this, arguments);
        if (boot?.auth?.authenticated || boot?.user?.id || getApp()?.state?.loggedIn) {
          fetchUnreadCounts();
        } else {
          stopUnreadPolling();
          unreadState = { notifications: 0, direct: 0, broadcasts: 0, total: 0 };
          updateNavBadge();
          updateTabBadges();
        }
        return ret;
      };
    }
  }

  // Hook immediately
  hookAccountTools();
  hookBoot();

  // Initialization & Lifecycle
  function init() {
    injectStyles();
    hookAccountTools();
    hookBoot();

    // Listen to visibility & window focus
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        fetchUnreadCounts();
        if (activeConversationId) {
          pollIncrementalMessages(activeConversationId);
        }
      }
    });

    window.addEventListener("focus", () => {
      fetchUnreadCounts();
    });

    // Start unread polling if logged in
    startUnreadPolling();

    // Observe DOM mutations to mount buttons and nav badges
    let scheduled = false;
    new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        updateNavBadge();
        mountProfileAndAuthorDMLinks();
        hookAccountTools();
      });
    }).observe(document.body, { childList: true, subtree: true });

    mountProfileAndAuthorDMLinks();
    updateNavBadge();
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.HandrawMessaging = {
    fetchUnreadCounts,
    getUnreadState: () => unreadState,
    renderMessageCenter,
    openConversation,
    openBroadcastConversation,
    openAdminBroadcastModal,
  };
})();
