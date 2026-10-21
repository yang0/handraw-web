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
          child instanceof Node ? child : document.createTextNode(String(child))
        );
    }
    return element;
  }

  function tell(message) {
    $("#notice").textContent = message;
  }

  async function api(path, options = {}) {
    const read = !options.method || options.method === "GET";
    if (read && getCache.get(path)?.expires > Date.now())
      return getCache.get(path).value;
    if (read && pendingGets.has(path)) return pendingGets.get(path);
    const request = async (retried = false) => {
      if (cooldownUntil > Date.now())
        await new Promise((resolve) =>
          setTimeout(resolve, cooldownUntil - Date.now())
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
          Math.min(60, Number(response.headers.get("Retry-After")) || 10)
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
              : "操作未完成，请稍后重试")
        );
      if (read)
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
      text
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
      control
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
        choices.map(([value, text]) => el("option", { value }, text))
      )
    );
  }

  async function share(kind = null) {
    if (!kind || typeof kind !== "string") {
      return modal(
        "你想分享什么？",
        el("p", { class: "hw-help" }, "作品、制作方法，或你整理的画风与图型。"),
        el(
          "div",
          { class: "hw-share-choices" },
          ...[
            ["work", "晒作品", "上传一张图，说说你画了什么。"],
            ["experience", "写经验", "教程、创作过程、踩过的坑，都可以写。"],
            [
              "style",
              "分享画风或图型",
              "分享你用过的提示词、画风描述或排版方法。",
            ],
          ].map(
            ([value, title, description]) =>
              button("", () => share(value), true).appendChild(
                el(
                  "span",
                  {},
                  el("strong", {}, title),
                  el("small", {}, description)
                )
              ).parentElement
          )
        )
      );
    }
    if (state.boot.user && !state.boot.participant)
      return modal(
        "创作者试运行",
        el(
          "p",
          {},
          "目前由试运行创作者发布。你可以先收藏喜欢的内容，或到论坛交流。"
        ),
        el("a", { href: "/latest", class: "hw-text-link" }, "前往论坛")
      );
    const resource = ["style", "layout"].includes(kind);
    const titleLabel =
      kind === "work"
        ? "作品标题"
        : kind === "experience"
          ? "经验标题"
          : "给画风／图型起个名字";
    const bodyLabel =
      kind === "work"
        ? "创作说明（选填）"
        : kind === "experience"
          ? "写下你的方法"
          : "画风描述／提示词／布局要点";
    const titleField = field("title", titleLabel);
    titleField.querySelector("input").placeholder =
      kind === "work"
        ? "例如：用水彩画了一间街角咖啡馆"
        : kind === "experience"
          ? "例如：我是怎样让 AI 画出的文字更清楚的"
          : "例如：温暖的纸感水彩";
    const bodyField = field("summary", bodyLabel, "textarea", kind !== "work");
    bodyField.querySelector("textarea").placeholder =
      kind === "work"
        ? "用了什么画风？有什么想说的？"
        : kind === "experience"
          ? "想做什么 → 怎么做的 → 最后效果如何。写清一个小经验就很好。"
          : "粘贴你用过的提示词，或描述色彩、笔触和排版。附一张实际效果图更容易理解。";
    const form = el("form", { class: "hw-share-form" });
    if (!state.boot.user)
      form.append(
        el(
          "p",
          { class: "hw-help" },
          "登录后即可发布。先看看适合分享哪些内容。"
        )
      );
    const fields = el("fieldset", { disabled: !state.boot.user });
    if (resource)
      fields.append(
        selectField("kind", "分享类型", [
          ["style", "画风"],
          ["layout", "图型／排版"],
        ])
      );
    fields.append(titleField);
    const imageField = field(
      "image",
      kind === "work" ? "上传作品图片" : "配一张效果图（选填）",
      "file",
      kind === "work"
    );
    imageField.querySelector("input").accept =
      "image/png,image/jpeg,image/webp";
    if (kind === "work") fields.append(imageField, bodyField);
    else fields.append(bodyField, imageField);
    if (resource) {
      const advanced = el(
        "details",
        { class: "hw-advanced" },
        el("summary", {}, "附上可导入 Skill 的定义（选填）"),
        el(
          "p",
          { class: "hw-help" },
          "有从 Skill 导出的画风或图型文件，可以附在这里。没有文件也能分享描述与效果图。"
        ),
        field("bundle", "Skill 导出的 ZIP 文件", "file", false),
        field("license", "补充使用范围（选填）", "textarea", false)
      );
      advanced.querySelector('[name="bundle"]').accept = ".zip";
      fields.append(advanced);
    }
    fields.append(
      el(
        "label",
        { class: "hw-check" },
        el("input", { name: "rights", type: "checkbox", required: true }),
        "我有权分享以上内容。使用范围以作者说明为准。"
      )
    );
    form.append(fields, el("p", { class: "hw-form-error", role: "alert" }));
    const submit = el(
      "button",
      { class: "hw-button", type: "submit" },
      state.boot.user ? "发布分享" : "登录后发布"
    );
    form.append(submit);
    form.elements.title.minLength = 5;
    if (kind !== "work") form.elements.summary.minLength = 10;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!needUser()) return;
      await action(submit, async () => {
        const data = new FormData(form);
        let cover = "";
        const image = data.get("image");
        if (image?.size) {
          const imageForm = new FormData();
          imageForm.append("type", "composer");
          imageForm.append("synchronous", "true");
          imageForm.append("file", image);
          const response = await fetch("/uploads.json", {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "X-CSRF-Token": await getCsrf(),
              "X-Requested-With": "XMLHttpRequest",
            },
            body: imageForm,
          });
          const upload = await response.json();
          if (!response.ok || !upload.url)
            throw new Error(
              upload.errors?.join("；") || "图片上传失败，请稍后再试"
            );
          cover = upload.url.startsWith("//")
            ? `https:${upload.url}`
            : upload.url;
        }
        const entry = await api("/entries", {
          method: "POST",
          body: JSON.stringify({
            entry: {
              kind: resource ? data.get("kind") : kind,
              title: data.get("title"),
              summary:
                String(data.get("summary") || "").trim() ||
                "作者分享的创作作品，欢迎在原帖交流制作方法。",
              cover_url: cover,
              license: data.get("license") || undefined,
              paid_opt_in: false,
            },
          }),
        });
        const bundle = data.get("bundle");
        if (bundle?.size) {
          const upload = new FormData();
          upload.append("file", bundle);
          try {
            await api(`/entries/${entry.id}/bundle`, {
              method: "POST",
              body: upload,
            });
          } catch (error) {
            modal(
              "分享已发布，定义文件未上传",
              el("p", {}, error.message),
              button("到我的创作补充", () => {
                $("#modal").close();
                navigate("mine");
              })
            );
            return;
          }
        }
        $("#modal").close();
        navigate("mine");
        tell("分享已发布。");
      });
    });
    modal(
      kind === "work"
        ? "晒作品"
        : kind === "experience"
          ? "写经验"
          : "分享画风或图型",
      form,
      button("重新选择分享类型", () => share(), true)
    );
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
      entry.collected ? "已加入我的收藏。" : "已取消收藏，已解锁资格仍然保留。"
    );
  }

  async function openEntry(id) {
    try {
      const entry = await api(`/entries/${id}`);
      if (state.boot.user && state.boot.user.id !== entry.author.id)
        api(`/entries/${id}/events`, {
          method: "POST",
          body: JSON.stringify({ kind: "detail" }),
        }).catch(() => {});
      const body = [];
      if (entry.cover_url)
        body.push(
          el("img", {
            class: "hw-detail-image",
            src: entry.cover_url,
            alt: entry.title,
          })
        );
      body.push(
        el(
          "p",
          { class: "hw-help" },
          `${labels[entry.kind] || "资料"}${entry.source_label ? " · " + entry.source_label : ""} · ${entry.author.name || entry.author.username} · v${entry.version}${entry.featured ? " · 编辑精选" : ""}`
        )
      );
      body.push(el("p", { class: "hw-detail-text" }, entry.summary));
      const actions = el("div", { class: "hw-actions" });
      actions.append(
        button(
          entry.collected ? "已收藏 ♥" : "收藏 ♡",
          (node) => save(entry, node),
          true
        )
      );
      if (entry.bundle_available) {
        if (entry.unlocked)
          actions.append(
            el(
              "a",
              {
                class: "hw-button",
                href: `/studio/api/entries/${id}/download`,
              },
              "下载画风／图型定义 ↓"
            )
          );
        else
          actions.append(
            button(
              entry.price ? `${entry.price} 积分解锁` : "免费获取",
              async () => {
                if (!needUser()) return;
                if (
                  !confirm(
                    entry.price
                      ? `确认使用 ${entry.price} 积分解锁？作者获得 ${state.boot.rules.author_percent}%，同一资源后续下载与更新免费。`
                      : "确认免费获取并添加到已解锁资源？"
                  )
                )
                  return;
                await api(`/entries/${id}/unlock`, {
                  method: "POST",
                  body: JSON.stringify({
                    price: entry.price,
                    price_revision: entry.price_revision,
                  }),
                });
                await refreshAccount();
                await openEntry(id);
              }
            )
          );
      }
      actions.append(
        el(
          "a",
          { class: "hw-text-link", href: entry.topic_url },
          entry.source_label ? "阅读原帖与讨论 →" : "讨论与补充 →"
        )
      );
      body.push(actions);
      if (entry.paid)
        body.push(
          el(
            "p",
            { class: "hw-help" },
            `${entry.price_reason}。一次解锁后，重复下载与更新不再扣分。`
          )
        );
      if (state.boot.user && state.boot.user.id !== entry.author.id) {
        body.push(
          el(
            "div",
            { class: "hw-actions" },
            button(
              "使用后觉得有用",
              async () => {
                await api(`/entries/${id}/events`, {
                  method: "POST",
                  body: JSON.stringify({ kind: "useful" }),
                });
                tell("使用反馈已记录，谢谢分享真实体验。");
              },
              true
            ),
            button(
              "使用后不太有用",
              async () => {
                await api(`/entries/${id}/events`, {
                  method: "POST",
                  body: JSON.stringify({ kind: "not_useful" }),
                });
                tell("反馈已记录。");
              },
              true
            ),
            button("报告问题", () => report(entry), true)
          )
        );
      }
      if (state.boot.user?.id === entry.author.id)
        if (["style", "layout"].includes(entry.kind))
          body.push(bundleUpload(entry));
      body.push(el("p", { class: "hw-license" }, `授权说明：${entry.license}`));
      modal(entry.title, ...body);
    } catch (error) {
      tell(error.message);
    }
  }

  function bundleUpload(entry) {
    const input = el("input", {
      type: "file",
      accept: ".zip",
      "aria-label": "选择画风／图型定义文件",
    });
    return el(
      "div",
      { class: "hw-field" },
      el(
        "p",
        { class: "hw-help" },
        "如需让别人导入 Skill，可附上 Skill 导出的定义文件。更新后会重新审核。"
      ),
      input,
      button(
        "补充／更新定义文件",
        async () => {
          if (!input.files[0])
            throw new Error("请选择 Skill 导出的 ZIP 定义文件");
          const form = new FormData();
          form.append("file", input.files[0]);
          await api(`/entries/${entry.id}/bundle`, {
            method: "POST",
            body: form,
          });
          tell("定义文件已上传，等待版主审核。");
          $("#modal").close();
        },
        true
      )
    );
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
      })
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
      entry.collected ? "已收藏 ♥" : "收藏 ♡"
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
            : null
        )
      );
    }
    node.append(
      el(
        "p",
        { class: "hw-work__kind" },
        `${labels[entry.kind] || "资料"}${entry.source_label ? " / " + entry.source_label : ""}${entry.verified ? " / 已验证" : ""}${entry.paid ? ` / ${entry.price} 积分` : ""}`
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
          entry.title
        )
      )
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
          `@${entry.author.username}`
        ),
        saveButton
      )
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
                  }, 2000)
                );
              }
            }
          },
          { threshold: [0, 0.5] }
        )
      : null;

  function empty(title, subtitle, cta) {
    return el(
      "div",
      { class: "hw-empty" },
      el("strong", {}, title),
      el("p", {}, subtitle),
      cta || null
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
        name
      )
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
      `/feed?${new URLSearchParams({ kind, page: state.page, q: state.search, sort: state.sort })}`
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
          el("span", {}, `${Math.max(0, topic.posts_count - 1)} 条回复`)
        )
      )
    );
  }

  function renderEntries(entries) {
    $("#content").replaceChildren(
      entries.length
        ? el("div", { class: "hw-grid" }, entries.map(card))
        : empty(
            "第一份分享，正在等你",
            "晒一张作品，或写下你的制作方法。",
            button("分享我的创作 ↗", share)
          )
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
        `${wallet.balance} 积分`
      ),
      el(
        "a",
        { href: "/studio?view=mine", "data-view": "mine" },
        state.boot.user.name || state.boot.user.username
      )
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
        `待结算收益 ${wallet.pending} 分 · 解锁资源的作者收益在 ${state.boot.rules.settlement_days} 天后结算${wallet.frozen ? " · 当前账户已冻结" : ""}`
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
                "收藏免费；部分精选资源需积分解锁。请分享自己有权发布的作品，按真实使用体验反馈，不通过互刷获取积分。"
              ),
              el(
                "a",
                {
                  href: "/guidelines",
                  target: "_blank",
                  class: "hw-text-link",
                },
                "阅读社区准则 ↗"
              ),
              button("我已了解，开始参与", async () => {
                await api("/welcome", {
                  method: "POST",
                  body: JSON.stringify({ accepted: true }),
                });
                $("#modal").close();
                showWallet();
              })
            );
          }
        )
      );
    const rows = wallet.entries.map((item) =>
      el(
        "tr",
        {},
        el("td", {}, new Date(item.created_at).toLocaleString("zh-CN")),
        el("td", {}, item.reason),
        el("td", {}, `${item.amount > 0 ? "+" : ""}${item.amount}`)
      )
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
          ["时间", "说明", "积分变动"].map((text) => el("th", {}, text))
        )
      ),
      el("tbody", {}, rows)
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
        }
      )
    );
    const items =
      state.mine === "collected"
        ? data.collected
        : state.mine === "owned"
          ? data.owned
          : data.owned.filter((item) => item.kind === state.mine);
    renderEntries(items);
    if (state.mine === "collected")
      $("#content").prepend(
        el(
          "p",
          { class: "hw-help" },
          "收藏仅保存预览。解锁后下载 ZIP，或在 Skill 中输入“同步我的收藏”，选择导入并离线使用。取消收藏不影响已解锁资格。"
        )
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
        }
      )
    );
    if (state.resourceTab === "collected") {
      state.mine = "collected";
      await showMine();
      return;
    }
    if (state.resourceTab === "official") {
      const response = await fetch(
        "https://static.handraw-style.com/data/styles.json?web=2"
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
            "全部官方画风 ↗"
          ),
          el(
            "a",
            {
              href: "https://static.handraw-style.com/gallery/layouts.html?web=2",
            },
            "全部官方图型 ↗"
          ),
          el(
            "a",
            {
              href: "https://static.handraw-style.com/gallery/tutorials.html?web=2",
            },
            "提示词拼装器 ↗"
          )
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
                })
              ),
              el(
                "p",
                { class: "hw-work__kind" },
                `官方画风 / ${item.number} / 免费`
              ),
              el("h3", {}, item.reference)
            )
          )
        )
      );
      return;
    }
    const data = await api("/feed?kind=resource");
    if (request !== activeRequest) return;
    renderEntries(
      data.entries.filter((item) =>
        ["style", "layout", "package"].includes(item.kind)
      )
    );
    $("#content").prepend(
      el(
        "div",
        { class: "hw-resource-intro" },
        el(
          "a",
          { href: "https://static.handraw-style.com/gallery/index.html?web=2" },
          "官方画风 ↗"
        ),
        el(
          "a",
          {
            href: "https://static.handraw-style.com/gallery/layouts.html?web=2",
          },
          "官方图型 ↗"
        ),
        el("span", {}, "收藏免费，精选资源解锁后可导入 Skill。")
      )
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
            `${labels[entry.kind]} / ${entry.status} / ${entry.featured ? "已精选" : "待精选"} / ${entry.has_bundle ? "有资源包" : "无资源包"} / ${entry.paid_opt_in ? "申请积分下载" : "免费分享"}`
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
              true
            ),
            entry.has_bundle
              ? el(
                  "a",
                  {
                    class: "hw-button hw-button--quiet",
                    href: `/studio/api/entries/${entry.id}/review-download`,
                  },
                  "下载审核包"
                )
              : null,
            button(
              entry.featured ? "取消精选" : "设为精选",
              () =>
                reviewAction(entry, entry.featured ? "unfeature" : "feature"),
              true
            ),
            button(
              "验证并开放下载",
              () => reviewAction(entry, "approve_download"),
              true
            ),
            button("暂停", () => reviewAction(entry, "pause"), true),
            button("恢复展示", () => reviewAction(entry, "restore"), true)
          )
        )
      )
    );
    const reports = el("section", {}, el("h3", {}, "待处理问题与申诉"));
    for (const item of data.reports) {
      const entry = data.entries.find(
        (record) => record.internal_id === item.entry_id
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
                  true
                ),
                button(
                  "驳回举报",
                  () =>
                    reviewAction(entry, "dismiss_report", {
                      report_id: item.id,
                    }),
                  true
                )
              )
            : null
        )
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
            `交易 #${sale.id} / 资源 #${sale.entry_id} / ${sale.amount} 积分 / ${sale.settled_at ? "已结算" : "待结算"}`
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
            true
          )
        )
      );
    $("#content").append(
      el("h3", {}, "最近审核记录"),
      ...data.audits.map((audit) =>
        el(
          "p",
          { class: "hw-help" },
          `${new Date(audit.created_at).toLocaleString("zh-CN")} · ${audit.action} · ${audit.reason}`
        )
      )
    );
  }

  async function render() {
    activeRequest += 1;
    state.view = new URLSearchParams(location.search).get("view") || "home";
    const titles = {
      home: "作品与经验",
      works: "作品",
      experience: "经验与教程",
      resources: "画风与图型",
      mine: "我的创作",
      wallet: "积分与记录",
      review: "版主工作台",
    };
    $("#hero").hidden = state.view !== "home";
    $("#discussions-section").hidden = ![
      "home",
      "works",
      "experience",
    ].includes(state.view);
    $("#section-title").textContent = titles[state.view] || titles.home;
    $("#section-label").textContent =
      state.view === "home" ? "COMMUNITY / 社区发现" : "HANDRAW / 创作社区";
    document.title = `${titles[state.view] || titles.home} · 手绘风`;
    $("#toolbar").replaceChildren();
    $("#heading-actions").replaceChildren();
    $("#more").hidden = true;
    tell("");
    $("#content").replaceChildren(
      el("p", { class: "hw-spinner" }, "正在加载…")
    );
    document.querySelectorAll(".hw-nav [data-view]").forEach((item) => {
      if (item.dataset.view === state.view)
        item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    if (state.boot.reviewer)
      $("#heading-actions").append(
        el(
          "a",
          {
            href: "/studio?view=review",
            "data-view": "review",
            class: "hw-text-link",
          },
          "版主工作台 →"
        )
      );
    if (state.view !== "home")
      $("#heading-actions").append(button("分享 ↗", share, true));
    if (state.view === "mine") return showMine();
    if (state.view === "wallet") return showWallet();
    if (state.view === "review") return showReview();
    if (state.view === "resources") return showResources();
    const order = el(
      "select",
      { "aria-label": "内容排序", class: "hw-search" },
      el("option", { value: "recommended" }, "社区推荐"),
      el("option", { value: "latest" }, "最新投稿")
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
      renderEntries(data.entries);
      return;
    }
    await loadFeed();
    const id = new URLSearchParams(location.search).get("entry");
    if (id) await openEntry(id);
  }

  function navigate(view) {
    history.pushState(
      {},
      "",
      view === "home" ? "/studio" : `/studio?view=${view}`
    );
    state.page = 1;
    render().catch((error) => tell(error.message));
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-view]");
    if (link && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      navigate(link.dataset.view);
    }
  });
  $("#share").addEventListener("click", share);
  $("#close-modal").addEventListener("click", () => $("#modal").close());
  $("#more").addEventListener("click", () => {
    state.page += 1;
    loadFeed(true).catch((error) => tell(error.message));
  });
  window.addEventListener("popstate", () =>
    render().catch((error) => tell(error.message))
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
          el("a", { href: "/latest", class: "hw-button" }, "前往论坛 →")
        )
      );
    });
})();
