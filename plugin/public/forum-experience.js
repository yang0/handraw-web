"use strict";

(() => {
  if (
    !document.querySelector('[data-surface="forum"]') ||
    window.handrawForumExperience
  )
    return;
  window.handrawForumExperience = true;
  const state = { boot: null };
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (tag === "img" && key === "src") continue;
      if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== false)
        node.setAttribute(key, value === true ? "" : value);
    }
    if (tag === "img") {
      node.loading = "lazy";
      if (window.HandrawImages && attrs.src)
        window.HandrawImages.set(node, attrs.src);
      else if (attrs.src) node.src = attrs.src;
    }
    for (const child of children.flat())
      if (child !== null && child !== undefined)
        node.append(
          child instanceof Node
            ? child
            : document.createTextNode(String(child)),
        );
    return node;
  }
  const shell = el("div", { class: "hw-forum-market" });
  const heading = el("h2", { id: "handraw-forum-dialog-title" });
  const body = el("div", { "data-handraw-id": "modal-body" });
  const notice = el("p", { role: "status", "aria-live": "polite" });
  const dialog = el(
    "dialog",
    {
      class: "hw-forum-dialog",
      "data-handraw-id": "modal",
      "aria-labelledby": "handraw-forum-dialog-title",
    },
    el(
      "div",
      { class: "hw-forum-dialog-heading" },
      heading,
      el(
        "button",
        { type: "button", "aria-label": "关闭", onclick: () => dialog.close() },
        "×",
      ),
    ),
    notice,
    body,
  );
  shell.append(dialog);
  document.body.append(shell);
  const tell = (message) => {
    notice.textContent = message;
  };
  const modal = (title, ...children) => {
    heading.textContent = title;
    body.replaceChildren(...children);
    if (!dialog.open) dialog.showModal();
  };
  let csrf;
  async function api(path, options = {}) {
    const headers = {
      Accept: "application/json",
      "X-Requested-With": "XMLHttpRequest",
    };
    if (options.method && options.method !== "GET") {
      csrf ||= fetch("/session/csrf.json", { credentials: "same-origin" })
        .then((r) => r.json())
        .then((r) => r.csrf);
      headers["X-CSRF-Token"] = await csrf;
      if (!(options.body instanceof FormData))
        headers["Content-Type"] = "application/json";
    }
    const response = await fetch(`/studio/api${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
    });
    if (response.status === 204) return null;
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.errors?.join("；") || "请登录已验证账号后再操作");
    return result;
  }
  function button(text, action, quiet = false) {
    const node = el(
      "button",
      {
        type: "button",
        class: quiet ? "hw-button hw-button--quiet" : "hw-button",
      },
      text,
    );
    node.addEventListener("click", async () => {
      node.disabled = true;
      try {
        await action(node);
      } catch (e) {
        tell(e.message);
      } finally {
        node.disabled = false;
      }
    });
    return node;
  }
  const navigate = (view, params = {}) => {
    location.href = `/studio?${new URLSearchParams({ view, ...params })}`;
  };
  const market = window.HandrawMarket({
    state,
    el,
    button,
    modal,
    tell,
    api,
    navigate,
    select: (query) =>
      shell.querySelector(`[data-handraw-id="${query.slice(1)}"]`),
    card: (entry) =>
      el(
        "article",
        {},
        entry.cover_url
          ? el("img", { src: entry.cover_url, alt: entry.title })
          : null,
        button(entry.title, () => market.openEntry(entry.id), true),
      ),
  });
  let topicChecked = "",
    timer;
  async function enhance() {
    if (!state.boot) return;
    const header = document.querySelector('[data-surface="forum"]');
    if (
      state.boot.participant &&
      header &&
      !header.querySelector(".hw-write-experience")
    ) {
      const write = button("写经验", () => market.share("experience"), true);
      write.classList.add("hw-write-experience");
      header.append(write);
    }
    const toolbar = document.querySelector(".d-editor-button-bar");
    if (
      state.boot.participant &&
      toolbar &&
      !toolbar.querySelector(".hw-compose-experience")
    ) {
      const write = button("分享经验", () => market.share("experience"), true);
      write.classList.add("hw-compose-experience");
      toolbar.append(write);
    }
    const match = location.pathname.match(/^\/t\/(?:[^/]+\/)?(\d+)/);
    if (!match) {
      topicChecked = "";
      return;
    }
    const firstPost = document.querySelector("#post_1 .cooked");
    if (!firstPost || topicChecked === match[1]) return;
    topicChecked = match[1];
    try {
      const result = await api(`/topics/${match[1]}/experience`);
      if (!firstPost.isConnected) return;
      if (result.entry) {
        firstPost.append(
          el(
            "div",
            { class: "hw-forum-experience-link" },
            button(
              result.entry.paid
                ? `完整经验 · ${result.entry.price} 积分${result.entry.unlocked ? " · 已解锁" : ""}`
                : "阅读完整经验",
              () => market.openEntry(result.entry.id),
            ),
          ),
        );
      } else if (state.boot.participant) {
        const username = document
          .querySelector("#post_1 .username")
          ?.textContent.trim();
        if (username === state.boot.user?.username)
          firstPost.append(
            el(
              "div",
              { class: "hw-forum-experience-link" },
              button(
                "收录为经验／添加进阶内容",
                () =>
                  market.share("experience", {
                    topic_id: Number(match[1]),
                    title:
                      document
                        .querySelector("#topic-title h1")
                        ?.textContent.trim() || "我的创作经验分享",
                    summary: "来自论坛的经验分享，阅读原帖或查看完整方法。",
                  }),
                true,
              ),
            ),
          );
      }
    } catch (_) {
      topicChecked = "";
    }
  }
  api("/boot")
    .then((boot) => {
      state.boot = boot;
      enhance();
      new MutationObserver(() => {
        clearTimeout(timer);
        timer = setTimeout(enhance, 350);
      }).observe(document.querySelector("#main") || document.body, {
        childList: true,
        subtree: true,
      });
    })
    .catch(() => {});
})();
