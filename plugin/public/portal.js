"use strict";

(() => {
  const $ = (query) => document.querySelector(query);
  const state = {
    boot: null,
    page: 1,
    kind: "",
    search: "",
    sort: "recommended",
    mine: "owned",
    entries: [],
    resourceTab: "official",
    view: "home",
  };
  const labels = {
    work: "作品",
    experience: "经验",
    style: "画风",
    layout: "图型",
  };
  let csrfPromise;
  const getCache = new Map();
  const pendingGets = new Map();
  let cooldownUntil = 0;
  async function getCsrf() {
    csrfPromise ||= fetch("/session/csrf.json", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new Error("暂时无法确认登录状态，请稍后再试");
        return (await response.json()).csrf;
      })
      .catch((error) => {
        csrfPromise = null;
        throw error;
      });
    return csrfPromise;
  }
  let activeRequest = 0;
  const timers = new WeakMap();

  function el(tag, attributes = {}, ...children) {
    const element = document.createElement(tag);
    if (tag === "img" && attributes.src) {
      attributes = { ...attributes, "data-hw-src": attributes.src };
      attributes.src =
        "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%224%22 height=%223%22%3E%3Cpath fill=%22%23eeeae2%22 d=%22M0 0h4v3H0z%22/%3E%3C/svg%3E";
    }
    for (const [key, value] of Object.entries(attributes)) {
      if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
      else if (key === "class") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (value !== null && value !== false)
        element.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child !== null && child !== undefined)
        element.append(
          child instanceof Node
            ? child
            : document.createTextNode(String(child)),
        );
    }
    return element;
  }

  function tell(message) {
    $("#notice").textContent = message;
  }

  async function api(path, options = {}) {
    const read = !options.method || options.method === "GET";
    const sensitive = /\/content(?:\?|$)|^\/generations|\/review/.test(path);
    if (read && !sensitive && getCache.get(path)?.expires > Date.now())
      return getCache.get(path).value;
    if (read && pendingGets.has(path)) return pendingGets.get(path);
    const request = async (retried = false) => {
      if (cooldownUntil > Date.now())
        await new Promise((resolve) =>
          setTimeout(resolve, cooldownUntil - Date.now()),
        );
      const headers = {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json",
        ...options.headers,
      };
      if (!read) {
        headers["X-CSRF-Token"] = await getCsrf();
        if (!(options.body instanceof FormData))
          headers["Content-Type"] = "application/json";
      }
      const response = await fetch(`/studio/api${path}`, {
        credentials: "same-origin",
        ...options,
        headers,
      });
      if (response.status === 429) {
        const seconds = Math.max(
          1,
          Math.min(60, Number(response.headers.get("Retry-After")) || 10),
        );
        cooldownUntil = Date.now() + seconds * 1000;
        if (read && !retried) return request(true);
        throw new Error(`操作较快，请在 ${seconds} 秒后再试。`);
      }
      if (response.status === 204) return null;
      const result = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(
          result.errors?.join("；") ||
            (response.status === 403
              ? "请登录获准参与的账号后再操作"
              : "操作未完成，请稍后重试"),
        );
      if (read && !sensitive)
        getCache.set(path, { value: result, expires: Date.now() + 15000 });
      return result;
    };
    const pending = request();
    if (read) pendingGets.set(path, pending);
    try {
      const value = await pending;
      if (!read && !path.endsWith("/events") && path !== "/impressions")
        getCache.clear();
      return value;
    } finally {
      if (read) pendingGets.delete(path);
    }
  }

  async function action(button, callback) {
    button.disabled = true;
    try {
      await callback();
    } catch (error) {
      tell(error.message);
      const target = $(".hw-form-error");
      if (target) target.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  function button(text, callback, quiet = false) {
    const node = el(
      "button",
      { type: "button", class: `hw-button${quiet ? " hw-button--quiet" : ""}` },
      text,
    );
    node.addEventListener("click", () => action(node, () => callback(node)));
    return node;
  }

  function needUser() {
    if (!state.boot.user) {
      location.href = "/login";
      return false;
    }
    return true;
  }

  function modal(title, ...children) {
    $("#modal-title").textContent = title;
    $("#modal-body").replaceChildren(...children);
    if (!$("#modal").open) $("#modal").showModal();
  }

  function field(name, label, type = "text", required = true, value = "") {
    const control =
      type === "textarea"
        ? el("textarea", { id: `field-${name}`, name, required })
        : el("input", { id: `field-${name}`, name, type, required });
    control.value = value;
    return el(
      "div",
      { class: "hw-field" },
      el("label", { for: `field-${name}` }, label),
      control,
    );
  }

  function selectField(name, label, choices) {
    return el(
      "div",
      { class: "hw-field" },
      el("label", { for: `field-${name}` }, label),
      el(
        "select",
        { id: `field-${name}`, name },
        choices.map(([value, text]) => el("option", { value }, text)),
      ),
    );
  }

  async function share(kind = null, initial = {}) {
    return market.share(typeof kind === "string" ? kind : null, initial || {});
  }

  async function save(entry, node) {
    if (!needUser()) return;
    await api(`/entries/${entry.id}/collection`, {
      method: entry.collected ? "DELETE" : "POST",
    });
    entry.collected = !entry.collected;
    node.textContent = entry.collected ? "已收藏 ♥" : "收藏 ♡";
    node.setAttribute("aria-pressed", String(entry.collected));
    tell(
      entry.collected ? "已加入我的收藏。" : "已取消收藏，已解锁资格仍然保留。",
    );
  }

  async function openEntry(id) {
    try {
      await market.openEntry(id);
    } catch (error) {
      tell(error.message);
    }
  }

  function report(entry) {
    const reason = field("reason", "请描述文件、内容或授权问题", "textarea");
    modal(
      "报告问题",
      reason,
      button("提交给版主", async () => {
        await api(`/entries/${entry.id}/report`, {
          method: "POST",
          body: JSON.stringify({
            reason: reason.querySelector("textarea").value,
          }),
        });
        $("#modal").close();
        tell("问题已提交，可在原帖继续补充证据。");
      }),
    );
  }

  function card(entry) {
    const saveButton = el(
      "button",
      {
        type: "button",
        class: "hw-work__save",
        "aria-pressed": String(entry.collected),
        onclick: (event) =>
          action(event.currentTarget, () => save(entry, event.currentTarget)),
      },
      entry.collected ? "已收藏 ♥" : "收藏 ♡",
    );
    const node = el("article", {
      class: `hw-work${entry.cover_url ? "" : " hw-work--text"}`,
      "data-entry-id": entry.id,
    });
    if (entry.cover_url) {
      node.append(
        el(
          "a",
          {
            class: "hw-work__visual",
            href: `/studio?entry=${entry.id}`,
            onclick: (event) => {
              event.preventDefault();
              openEntry(entry.id);
            },
          },
          el("img", {
            class: "hw-work__image",
            src: entry.cover_url,
            alt: entry.title,
            loading: "lazy",
          }),
          entry.featured
            ? el("span", { class: "hw-work__badge" }, "精选")
            : null,
        ),
      );
    }
    node.append(
      el(
        "p",
        { class: "hw-work__kind" },
        `${labels[entry.kind] || "资料"}${entry.source_label ? " / " + entry.source_label : ""}${entry.verified ? " / 已验证" : ""}${entry.paid ? ` / ${entry.price} 积分` : ""}`,
      ),
      el(
        "h3",
        {},
        el(
          "a",
          {
            href: `/studio?entry=${entry.id}`,
            onclick: (event) => {
              event.preventDefault();
              openEntry(entry.id);
            },
          },
          entry.title,
        ),
      ),
    );
    if (!entry.cover_url)
      node.append(el("p", { class: "hw-work__abstract" }, entry.summary));
    node.append(
      el(
        "div",
        { class: "hw-work__meta" },
        el(
          "a",
          {
            href: `/studio?creator=${encodeURIComponent(entry.author.username)}`,
          },
          `@${entry.author.username}`,
        ),
        saveButton,
      ),
    );
    impressionObserver?.observe(node);
    return node;
  }

  const seenImpressions = new Set();
  const pendingImpressions = new Set();
  let impressionFlush;
  async function flushImpressions() {
    const ids = [...pendingImpressions].slice(0, 20);
    ids.forEach((id) => pendingImpressions.delete(id));
    try {
      await api("/impressions", {
        method: "POST",
        body: JSON.stringify({
          entries: ids.map((id) => ({
            id,
            visible_ms: 2000,
            visible_ratio: 0.5,
          })),
        }),
      });
    } catch (_) {
      ids.forEach((id) => seenImpressions.delete(id));
    }
    if (pendingImpressions.size)
      impressionFlush = setTimeout(flushImpressions, 500);
  }
  function queueImpression(id) {
    if (seenImpressions.has(id)) return;
    seenImpressions.add(id);
    pendingImpressions.add(id);
    clearTimeout(impressionFlush);
    impressionFlush = setTimeout(flushImpressions, 500);
  }
  const impressionObserver =
    typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(
          (records) => {
            for (const record of records) {
              clearTimeout(timers.get(record.target));
              if (
                record.isIntersecting &&
                record.intersectionRatio >= 0.5 &&
                state.boot?.user
              ) {
                timers.set(
                  record.target,
                  setTimeout(() => {
                    if (
                      !record.target.isConnected ||
                      document.visibilityState !== "visible"
                    )
                      return;
                    queueImpression(record.target.dataset.entryId);
                    impressionObserver.unobserve(record.target);
                  }, 2000),
                );
              }
            }
          },
          { threshold: [0, 0.5] },
        )
      : null;

  function empty(title, subtitle, cta) {
    return el(
      "div",
      { class: "hw-empty" },
      el("strong", {}, title),
      el("p", {}, subtitle),
      cta || null,
    );
  }

  function tabs(choices, current, callback) {
    return choices.map(([id, name]) =>
      el(
        "button",
        {
          type: "button",
          class: "hw-tab",
          "aria-pressed": String(id === current),
          onclick: () => callback(id),
        },
        name,
      ),
    );
  }

  async function loadFeed(append = false) {
    const request = ++activeRequest;
    const kind =
      state.view === "works"
        ? "work"
        : state.view === "experience"
          ? "experience"
          : state.kind;
    const data = await api(
      `/feed?${new URLSearchParams({ kind, page: state.page, q: state.search, sort: state.sort })}`,
    );
    if (request !== activeRequest) return;
    state.entries = append ? state.entries.concat(data.entries) : data.entries;
    renderEntries(state.entries);
    $("#more").hidden = data.entries.length < 20;
    $("#discussions").replaceChildren(
      ...data.discussions.map((topic) =>
        el(
          "li",
          {},
          el("a", { href: topic.url }, topic.title),
          el("span", {}, `${Math.max(0, topic.posts_count - 1)} 条回复`),
        ),
      ),
    );
  }

  function renderEntries(entries) {
    $("#content").replaceChildren(
      entries.length
        ? el("div", { class: "hw-grid" }, entries.map(card))
        : empty(
            "第一份分享，正在等你",
            "晒一张作品，或写下你的制作方法。",
            button("分享我的创作 ↗", share),
          ),
    );
  }

  async function refreshAccount() {
    if (!state.boot.user) return;
    const wallet = await api("/wallet");
    $("#account").replaceChildren(
      el(
        "a",
        {
          class: "hw-wallet-pill",
          href: "/studio?view=wallet",
          "data-view": "wallet",
        },
        `${wallet.balance} 积分`,
      ),
      el(
        "a",
        { href: "/studio?view=mine", "data-view": "mine" },
        state.boot.user.name || state.boot.user.username,
      ),
    );
    return wallet;
  }

  async function showWallet() {
    if (!needUser()) return;
    const wallet = await refreshAccount();
    const children = [
      el("p", { class: "hw-help" }, "可用积分"),
      el("p", { class: "hw-balance" }, wallet.balance),
      el(
        "p",
        { class: "hw-help" },
        `待结算收益 ${wallet.pending} 分 · 解锁资源的作者收益在 ${state.boot.rules.settlement_days} 天后结算${wallet.frozen ? " · 当前账户已冻结" : ""}`,
      ),
    ];
    if (!wallet.welcome_claimed && state.boot.participant)
      children.push(
        button(
          `完成新人任务，领取 ${state.boot.rules.welcome} 积分`,
          async () => {
            modal(
              "欢迎开始创作",
              el(
                "p",
                {},
                "收藏免费；部分精选资源需积分解锁。请分享自己有权发布的作品，按真实使用体验反馈，不通过互刷获取积分。",
              ),
              el(
                "a",
                {
                  href: "/guidelines",
                  target: "_blank",
                  class: "hw-text-link",
                },
                "阅读社区准则 ↗",
              ),
              button("我已了解，开始参与", async () => {
                await api("/welcome", {
                  method: "POST",
                  body: JSON.stringify({ accepted: true }),
                });
                $("#modal").close();
                showWallet();
              }),
            );
          },
        ),
      );
    const rows = wallet.entries.map((item) =>
      el(
        "tr",
        {},
        el("td", {}, new Date(item.created_at).toLocaleString("zh-CN")),
        el("td", {}, item.reason),
        el("td", {}, `${item.amount > 0 ? "+" : ""}${item.amount}`),
      ),
    );
    const table = el(
      "table",
      { class: "hw-table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          ["时间", "说明", "积分变动"].map((text) => el("th", {}, text)),
        ),
      ),
      el("tbody", {}, rows),
    );
    children.push(el("div", { class: "hw-table-wrapper" }, table));
    $("#content").replaceChildren(...children);
  }

  async function showMine() {
    if (!needUser()) return;
    const request = ++activeRequest;
    const data = await api("/library");
    if (request !== activeRequest) return;
    $("#toolbar").replaceChildren(
      ...tabs(
        [
          ["owned", "我的分享"],
          ["style", "我的画风"],
          ["layout", "我的图型"],
          ["collected", "我的收藏"],
        ],
        state.mine,
        (value) => {
          state.mine = value;
          showMine().catch((error) => tell(error.message));
        },
      ),
    );
    const items =
      state.mine === "collected"
        ? data.collected
        : state.mine === "owned"
          ? data.owned
          : [
              ...new Map(
                [...data.owned, ...data.collected]
                  .filter((item) => item.kind === state.mine)
                  .map((item) => [item.id, item]),
              ).values(),
            ];
    renderEntries(items);
    if (
      ["collected", "style", "layout"].includes(state.mine) &&
      data.official?.length
    )
      $("#content").append(
        el("h3", {}, "收藏的官方画风与图型"),
        el(
          "div",
          { class: "hw-editorial-grid" },
          ...data.official
            .filter(
              (item) => state.mine === "collected" || item.kind === state.mine,
            )
            .map(market.assetCard),
        ),
      );
    if (state.mine === "collected")
      $("#content").prepend(
        el(
          "p",
          { class: "hw-help" },
          "收藏保存喜欢的作品、画风和图型，方便下次查找。打开分享即可查看描述与提示词。取消收藏不影响已有解锁资格。",
        ),
      );
  }

  async function showResources() {
    const request = ++activeRequest;
    $("#toolbar").replaceChildren(
      ...tabs(
        [
          ["official", "官方画风与图型"],
          ["community", "社区分享"],
          ["collected", "我的收藏"],
        ],
        state.resourceTab,
        (value) => {
          state.resourceTab = value;
          showResources().catch((error) => tell(error.message));
        },
      ),
    );
    if (state.resourceTab === "collected") {
      state.mine = "collected";
      await showMine();
      return;
    }
    if (state.resourceTab === "official") {
      const response = await fetch(
        "https://static.handraw-style.com/data/styles.json?web=2",
      );
      if (!response.ok)
        throw new Error("官方资源暂时无法加载，可直接访问画廊。");
      const styles = await response.json();
      if (request !== activeRequest) return;
      const selected = [
        "FA-001",
        "FB-006",
        "FC-029",
        "FE-053",
        "FH-001",
        "FI-032",
      ]
        .map((id) => styles.find((item) => item.number === id))
        .filter(Boolean);
      $("#content").replaceChildren(
        el(
          "div",
          { class: "hw-resource-intro" },
          el(
            "a",
            {
              href: "https://static.handraw-style.com/gallery/index.html?web=2",
            },
            "全部官方画风 ↗",
          ),
          el(
            "a",
            {
              href: "https://static.handraw-style.com/gallery/layouts.html?web=2",
            },
            "全部官方图型 ↗",
          ),
          el(
            "a",
            {
              href: "https://static.handraw-style.com/gallery/tutorials.html?web=2",
            },
            "提示词拼装器 ↗",
          ),
        ),
        el(
          "div",
          { class: "hw-grid" },
          selected.map((item) =>
            el(
              "article",
              { class: "hw-work" },
              el(
                "a",
                {
                  href: "https://static.handraw-style.com/gallery/index.html?web=2",
                  class: "hw-work__visual",
                },
                el("img", {
                  class: "hw-work__image",
                  src: `https://img.handraw-style.com/images/individual/${item.number.split("-")[0]}/${item.number}.webp`,
                  alt: item.reference,
                  loading: "lazy",
                }),
              ),
              el(
                "p",
                { class: "hw-work__kind" },
                `官方画风 / ${item.number} / 免费`,
              ),
              el("h3", {}, item.reference),
            ),
          ),
        ),
      );
      return;
    }
    const data = await api("/feed?kind=resource");
    if (request !== activeRequest) return;
    renderEntries(
      data.entries.filter((item) =>
        ["style", "layout", "package"].includes(item.kind),
      ),
    );
    $("#content").prepend(
      el(
        "div",
        { class: "hw-resource-intro" },
        el(
          "a",
          { href: "https://static.handraw-style.com/gallery/index.html?web=2" },
          "官方画风 ↗",
        ),
        el(
          "a",
          {
            href: "https://static.handraw-style.com/gallery/layouts.html?web=2",
          },
          "官方图型 ↗",
        ),
        el("span", {}, "收藏喜欢的画风与图型，复制描述与提示词开始创作。"),
      ),
    );
  }

  async function reviewAction(entry, actionName, extra = {}) {
    const reason = prompt("请填写审核理由（至少五个字，会保留记录）");
    if (reason === null) return;
    await api(`/entries/${entry.id}/review`, {
      method: "POST",
      body: JSON.stringify({ action_name: actionName, reason, ...extra }),
    });
    await showReview();
    tell("审核结果已保存。");
  }

  async function showReview() {
    const data = await api("/review");
    $("#content").replaceChildren(
      ...data.entries.map((entry) =>
        el(
          "article",
          { class: "hw-review-item" },
          el("h3", {}, `${entry.title} · @${entry.author.username}`),
          el(
            "p",
            { class: "hw-help" },
            `${labels[entry.kind]} / ${entry.status} / ${entry.featured ? "已精选" : "待精选"} / ${entry.market ? "完整内容已保护" : "原有公开内容"} / ${entry.paid_opt_in ? "申请积分交易" : "免费分享"}`,
          ),
          el("p", {}, entry.summary),
          el(
            "div",
            { class: "hw-actions" },
            button(
              "查看讨论",
              () => {
                location.href = entry.topic_url;
              },
              true,
            ),
            entry.market
              ? button(
                  "检查完整定义与示例",
                  async () => {
                    const result = await api(
                      `/entries/${entry.id}/review-download`,
                    );
                    modal(
                      "审核内容",
                      el("p", {}, entry.title),
                      el(
                        "pre",
                        { class: "hw-prompt-text" },
                        JSON.stringify(result.content, null, 2),
                      ),
                    );
                  },
                  true,
                )
              : entry.has_bundle
                ? el(
                    "a",
                    {
                      class: "hw-button hw-button--quiet",
                      href: `/studio/api/entries/${entry.id}/review-download`,
                    },
                    "查看历史附件",
                  )
                : null,
            button(
              entry.featured ? "取消精选" : "设为精选",
              () =>
                reviewAction(entry, entry.featured ? "unfeature" : "feature"),
              true,
            ),
            button(
              "验证复用并开放交易",
              () => reviewAction(entry, "approve_download"),
              true,
            ),
            button("暂停", () => reviewAction(entry, "pause"), true),
            button("恢复展示", () => reviewAction(entry, "restore"), true),
          ),
        ),
      ),
    );
    const reports = el("section", {}, el("h3", {}, "待处理问题与申诉"));
    for (const item of data.reports) {
      const entry = data.entries.find(
        (record) => record.internal_id === item.entry_id,
      );
      reports.append(
        el(
          "div",
          { class: "hw-review-item" },
          el("p", {}, `资源 #${item.entry_id}：${item.reason}`),
          entry
            ? el(
                "div",
                { class: "hw-actions" },
                button(
                  "确认问题",
                  () =>
                    reviewAction(entry, "confirm_report", {
                      report_id: item.id,
                    }),
                  true,
                ),
                button(
                  "驳回举报",
                  () =>
                    reviewAction(entry, "dismiss_report", {
                      report_id: item.id,
                    }),
                  true,
                ),
              )
            : null,
        ),
      );
    }
    $("#content").append(reports, el("h3", {}, "积分解锁与退款"));
    for (const sale of data.unlocks)
      $("#content").append(
        el(
          "div",
          { class: "hw-review-item" },
          el(
            "p",
            {},
            `交易 #${sale.id} / 资源 #${sale.entry_id} / ${sale.amount} 积分 / ${sale.settled_at ? "已结算" : "待结算"}`,
          ),
          button(
            "确认退款",
            async () => {
              const reason = prompt("请填写退款原因（至少五个字）");
              if (reason === null) return;
              await api(`/unlocks/${sale.id}/refund`, {
                method: "POST",
                body: JSON.stringify({ reason }),
              });
              await showReview();
            },
            true,
          ),
        ),
      );
    $("#content").append(
      el("h3", {}, "最近审核记录"),
      ...data.audits.map((audit) =>
        el(
          "p",
          { class: "hw-help" },
          `${new Date(audit.created_at).toLocaleString("zh-CN")} · ${audit.action} · ${audit.reason}`,
        ),
      ),
    );
  }

  const market = window.HandrawMarket({
    state,
    el,
    button,
    modal,
    tell,
    api,
    navigate,
    card,
    refreshAccount,
    observeImpression: (node) => impressionObserver?.observe(node),
  });
  const discover = window.HandrawDiscover({
    state,
    el,
    button,
    modal,
    tell,
    api,
    share,
    navigate,
    card,
    market,
  });

  async function render() {
    activeRequest += 1;
    const params = new URLSearchParams(location.search);
    const requested = params.get("view") || "home";
    state.view = params.has("creator")
      ? "creator"
      : requested === "resources"
        ? "explore"
        : requested;
    const titles = {
      home: "找到喜欢的画风",
      creator: "创作者主页",
      explore: "探索视觉灵感",
      create: "创作台",
      learn: "从这里开始",
      community: "创作社区",
      works: "社区作品",
      experience: "经验分享",
      mine: "我的创作",
      wallet: "积分与记录",
      review: "版主工作台",
    };
    const isHome = state.view === "home";
    document.body.dataset.view = state.view;
    $("#hero").hidden = !isHome;
    $("#home-sections").hidden = !isHome;
    $(".hw-workspace").hidden = isHome;
    $("#discussions-section").hidden = ![
      "community",
      "works",
      "experience",
    ].includes(state.view);
    $("#section-title").textContent = titles[state.view] || titles.home;
    $("#section-label").textContent = [
      "community",
      "works",
      "experience",
    ].includes(state.view)
      ? "COMMUNITY / 创作社区"
      : "HANDRAW / 开始创作";
    document.title = `${titles[state.view] || titles.home} · 手绘风`;
    $("#toolbar").replaceChildren();
    $("#heading-actions").replaceChildren();
    $("#more").hidden = true;
    tell("");
    $("#content").replaceChildren(
      el("p", { class: "hw-spinner" }, "正在加载…"),
    );
    const active = ["works", "experience", "community", "creator"].includes(
      state.view,
    )
      ? "community"
      : state.view;
    document.querySelectorAll(".hw-nav [data-view]").forEach((item) => {
      if (item.dataset.view === active)
        item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    if (state.boot.reviewer) $("#heading-actions").append(linkReview());
    if (isHome) {
      await discover.home();
      const entry = params.get("entry");
      if (entry) await openEntry(entry);
      return;
    }
    if (state.view === "explore") return discover.explore();
    if (state.view === "create") return discover.create();
    if (state.view === "learn") return discover.learn();
    $("#heading-actions").append(button("分享创作 ↗", share, true));
    if (state.view === "mine") return showMine();
    if (state.view === "wallet") return showWallet();
    if (state.view === "review") return showReview();
    if (["community", "works", "experience"].includes(state.view)) {
      state.kind =
        state.view === "works"
          ? "work"
          : state.view === "experience"
            ? "experience"
            : ["experience", "style", "layout", "resource"].includes(
                  params.get("kind"),
                )
              ? params.get("kind")
              : "work";
      $("#toolbar").append(
        ...tabs(
          [
            ["work", "作品广场"],
            ["experience", "经验分享"],
            ["style", "画风"],
            ["layout", "图型"],
          ],
          state.kind,
          (value) => navigate("community", { kind: value }),
        ),
        el("a", { href: "/latest", class: "hw-tab" }, "交流讨论 ↗"),
      );
    }
    const order = el(
      "select",
      { "aria-label": "内容排序", class: "hw-search" },
      el("option", { value: "recommended" }, "社区推荐"),
      el("option", { value: "latest" }, "最新投稿"),
    );
    order.value = state.sort;
    order.addEventListener("change", () => {
      state.sort = order.value;
      state.page = 1;
      loadFeed().catch((error) => tell(error.message));
    });
    $("#toolbar").append(order);
    const search = el("input", {
      class: "hw-search",
      type: "search",
      placeholder: "搜索作品、经验和资源 ↵",
      "aria-label": "搜索作品、经验和资源",
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        state.search = search.value;
        state.page = 1;
        loadFeed().catch((error) => tell(error.message));
      }
    });
    $("#toolbar").append(search);
    const creator = new URLSearchParams(location.search).get("creator");
    if (creator) {
      const data = await api(`/creators/${encodeURIComponent(creator)}`);
      $("#section-title").textContent =
        `${data.author.name || data.author.username} 的创作`;
      const stats = el("div", { class: "hw-contribution-records" });
      for (const [kind, label] of Object.entries(labels)) {
        const row = data.contributions?.[kind];
        if (row)
          stats.append(
            el(
              "p",
              {},
              `${label}：${row.published} 份 · ${row.featured} 次精选 · ${row.useful_users} 位用户认可${row.verified ? ` · ${row.verified} 份复用验证` : ""}${row.reuse_users ? ` · ${row.reuse_users} 位实际复用` : ""}${row.honor ? ` · ${row.honor}` : ""}`,
            ),
          );
      }
      $("#toolbar").append(stats);
      renderEntries(data.entries);
      return;
    }
    await loadFeed();
    const shareKind = params.get("share");
    if (["work", "experience", "style", "layout"].includes(shareKind))
      await share(
        shareKind,
        params.get("topic_id") ? { topic_id: params.get("topic_id") } : {},
      );
    const id = new URLSearchParams(location.search).get("entry");
    if (id) await openEntry(id);
  }

  function linkReview() {
    return el(
      "a",
      {
        href: "/studio?view=review",
        "data-view": "review",
        class: "hw-text-link",
      },
      "版主工作台 →",
    );
  }
  function navigate(view, values = {}) {
    const params = new URLSearchParams(values);
    params.set("view", view);
    history.pushState(
      {},
      "",
      view === "home" ? "/studio" : `/studio?${params}`,
    );
    $("#modal").close();
    state.page = 1;
    render().catch((error) => tell(error.message));
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-view]");
    if (link && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      navigate(link.dataset.view, new URL(link.href).searchParams);
    }
  });
  $("#home-search").addEventListener("submit", (event) => {
    event.preventDefault();
    navigate("explore", { q: $("#home-query").value.trim().slice(0, 100) });
  });
  $("#close-modal").addEventListener("click", () => $("#modal").close());
  $("#more").addEventListener("click", () => {
    state.page += 1;
    loadFeed(true).catch((error) => tell(error.message));
  });
  window.addEventListener("popstate", () =>
    render().catch((error) => tell(error.message)),
  );
  api("/boot")
    .then(async (boot) => {
      state.boot = boot;
      $("#release").textContent =
        boot.release === "development" ? "" : boot.release.slice(0, 8);
      await refreshAccount();
      await render();
    })
    .catch((error) => {
      tell(error.message);
      $("#content").replaceChildren(
        empty(
          "暂时无法加载",
          "请稍后重试，或先前往现有论坛。",
          el("a", { href: "/latest", class: "hw-button" }, "前往论坛 →"),
        ),
      );
    });
})();
