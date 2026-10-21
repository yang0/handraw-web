"use strict";

window.HandrawDiscover = ({
  state,
  el,
  button,
  modal,
  tell,
  api,
  share,
  navigate,
  card,
}) => {
  const $ = (query) => document.querySelector(query);
  const editorial = () => state.boot.editorial;
  const assetBase = new URL(
    ".",
    document.querySelector('script[src*="/discover.js"]').src,
  );
  let catalogPromise;
  const catalog = () =>
    (catalogPromise ||= fetch(new URL("catalog.json", assetBase))
      .then((response) => {
        if (!response.ok) throw new Error("图库暂未加载，请稍后重试");
        return response.json();
      })
      .catch((error) => {
        catalogPromise = null;
        throw error;
      }));
  const draft = {
    mode: "pure",
    theme: "",
    style: "FA-001",
    layout: "",
    color: "",
    ratio: "1:1",
    mood: "",
  };
  try {
    const saved = JSON.parse(
      sessionStorage.getItem("handraw-create-draft") || "null",
    );
    if (saved && typeof saved.theme === "string") Object.assign(draft, saved);
    sessionStorage.removeItem("handraw-create-draft");
  } catch (_) {}
  const modes = {
    pure: "插画",
    "graphic-text": "图文",
    poster: "海报",
    "article-cover": "文章封面",
    "article-illust": "文章插图",
    photo: "摄影",
  };
  const kinds = { style: "画风", layout: "图型", color: "配色" };
  let engine;
  let engineReady;
  let requestNumber = 0;
  let composeTimer;
  const callbacks = new Map();

  function link(text, view, params = {}, className = "hw-text-link") {
    return el(
      "a",
      {
        href: `/studio?${new URLSearchParams({ view, ...params })}`,
        "data-view": view,
        class: className,
      },
      text,
    );
  }
  function heading(eyebrow, title, more) {
    return el(
      "div",
      { class: "hw-section-heading" },
      el(
        "div",
        {},
        el("p", { class: "hw-eyebrow" }, eyebrow),
        el("h2", {}, title),
      ),
      more || null,
    );
  }
  function resourceCard(item, compact = false) {
    const open = () => detail(item);
    return el(
      "article",
      { class: `hw-library-card${compact ? " hw-library-card--compact" : ""}` },
      el(
        "button",
        {
          type: "button",
          class: "hw-library-card__image",
          onclick: open,
          "aria-label": `查看 ${item.id} ${item.title || item.name}`,
        },
        el("img", {
          src: item.image,
          alt: item.title || item.name,
          width: 360,
          height: 390,
        }),
      ),
      el(
        "p",
        { class: "hw-library-card__label" },
        `${item.id} · 官方${kinds[item.kind]}`,
      ),
      el(
        "h3",
        {},
        el(
          "button",
          { type: "button", onclick: open },
          item.title || item.name,
        ),
      ),
      el(
        "p",
        { class: "hw-library-card__caption" },
        item.caption || item.description.slice(0, 52),
      ),
      link(`使用此${kinds[item.kind]} ↗`, "create", { [item.kind]: item.id }),
    );
  }
  function detail(item) {
    modal(
      `${item.id} · ${item.title || item.name}`,
      el(
        "div",
        { class: "hw-resource-detail" },
        el("img", {
          class: "hw-detail-image",
          src: item.image,
          alt: item.name,
        }),
        el(
          "div",
          {},
          el(
            "p",
            { class: "hw-eyebrow" },
            `官方${kinds[item.kind]} / ${item.id}`,
          ),
          el("h3", {}, item.name),
          el("p", {}, item.description),
          el(
            "p",
            { class: "hw-help" },
            "示例来自官方图库，用于了解视觉方向。实际效果会随主题、模型和比例变化。",
          ),
          el(
            "div",
            { class: "hw-actions" },
            link(
              `使用此${kinds[item.kind]} ↗`,
              "create",
              { [item.kind]: item.id },
              "hw-button",
            ),
            button(
              "复制描述",
              async () => {
                await navigator.clipboard.writeText(
                  item.definition || item.description,
                );
                tell("已复制描述。");
              },
              true,
            ),
          ),
        ),
      ),
    );
  }
  function guide(item) {
    modal(
      item.title,
      el("p", { class: "hw-help" }, `官方指南 · 约 ${item.minutes} 分钟`),
      ...item.steps.map(([title, body], index) =>
        el(
          "section",
          { class: "hw-guide-step" },
          el("h3", {}, `${index + 1}. ${title}`),
          el("p", {}, body),
        ),
      ),
      link("去创作台试试 →", "create", {}, "hw-button"),
    );
  }
  function guideCard(item, index) {
    return el(
      "button",
      { class: "hw-guide-link", type: "button", onclick: () => guide(item) },
      el(
        "span",
        { class: "hw-guide-link__number" },
        String(index + 1).padStart(2, "0"),
      ),
      el(
        "span",
        {},
        el("strong", {}, item.title),
        el("small", {}, item.summary),
      ),
      el("span", { "aria-hidden": "true" }, "↗"),
    );
  }
  async function home() {
    const data = editorial();
    $("#home-intro").textContent =
      `探索 ${data.counts.style} 种画风、${data.counts.layout} 种图型与 ${data.counts.color} 种配色。选一个喜欢的方向，让灵感有处落笔。`;
    const sections = el(
      "div",
      { class: "hw-home-content" },
      el(
        "section",
        { class: "hw-task-strip", "aria-label": "从用途开始" },
        el("p", {}, "今天，想做点什么？"),
        ...data.templates.map((item) =>
          link(`${item.title} ↗`, "create", { template: item.id }),
        ),
        link("自由创作 ↗", "create"),
      ),
      el(
        "section",
        { class: "hw-home-section" },
        heading(
          "A LITTLE INSPIRATION / 一点灵感",
          "从这些画风开始",
          link("探索全部画风 →", "explore"),
        ),
        el(
          "div",
          { class: "hw-editorial-grid" },
          data.featured.map((item) => resourceCard(item)),
        ),
      ),
      el(
        "section",
        { class: "hw-home-section hw-start-section" },
        heading("A PLACE TO START / 不必从空白开始", "带着一个想法，来试试"),
        el(
          "div",
          { class: "hw-template-grid" },
          data.templates.map((item, i) => {
            const style = data.featured.find(
              (style) => style.id === item.style,
            );
            return el(
              "article",
              { class: "hw-template" },
              link(
                "",
                "create",
                { template: item.id },
                "hw-template__visual",
              ).appendChild(
                el("img", {
                  src: style.image,
                  alt: `${style.title}，官方画风示例`,
                  width: 400,
                  height: 260,
                }),
              ).parentElement,
              el(
                "p",
                { class: "hw-eyebrow" },
                `组合建议 0${i + 1} / 官方画风示例`,
              ),
              el("h3", {}, item.title),
              el("p", {}, item.description),
              link("用这个组合开始 ↗", "create", { template: item.id }),
            );
          }),
        ),
      ),
      el(
        "section",
        { class: "hw-home-section hw-howto" },
        heading(
          "YOUR FIRST CREATION / 第一次创作",
          "三步，把想法变成画面",
          link("查看新手指南 →", "learn"),
        ),
        el(
          "ol",
          { class: "hw-steps" },
          ...[
            ["找到画风", "看真实示例，选一个你喜欢的视觉方向。"],
            ["写下主题", "说清想画什么，图型和配色按需选择。"],
            ["开始创作", "使用创作指令，完成后再分享你的作品。"],
          ].map(([title, text], i) =>
            el(
              "li",
              {},
              el("span", {}, `0${i + 1}`),
              el("h3", {}, title),
              el("p", {}, text),
            ),
          ),
        ),
      ),
      el(
        "section",
        { class: "hw-home-section" },
        heading("LEARN BY DOING / 边做边学", "刚刚好，够你开始"),
        el(
          "div",
          { class: "hw-guide-list" },
          data.guides.slice(0, 3).map(guideCard),
        ),
      ),
      el(
        "section",
        { class: "hw-home-section", id: "home-community" },
        heading(
          "MADE BY THE COMMUNITY / 来自社区",
          "看见彼此的创作",
          link("进入社区 →", "community"),
        ),
        el(
          "div",
          { id: "home-community-content" },
          el("p", { class: "hw-help" }, "正在整理社区作品…"),
        ),
      ),
      el(
        "section",
        { class: "hw-final-invite" },
        el(
          "div",
          {},
          el("p", { class: "hw-eyebrow" }, "THERE IS NO PERFECT FIRST TRY"),
          el("h2", {}, "先开始，画出你的第一张。"),
        ),
        link("打开创作台 ↗", "create", {}, "hw-button"),
      ),
    );
    $("#home-sections").replaceChildren(sections);
    try {
      const feed = await api("/feed?kind=work");
      if (state.view !== "home") return;
      const entries = feed.entries.filter((item) => item.cover_url).slice(0, 3);
      $("#home-community-content").replaceChildren(
        entries.length
          ? el("div", { class: "hw-grid" }, entries.map(card))
          : el(
              "div",
              { class: "hw-community-invite" },
              el("p", {}, "这里留给你的第一份作品。"),
              el(
                "p",
                { class: "hw-help" },
                "可以从一张图开始，讲讲自己的做法。",
              ),
              button("分享我的创作 ↗", share),
            ),
      );
    } catch (_) {
      if (state.view === "home")
        $("#home-community-content").replaceChildren(
          link("去社区看看大家的创作 →", "community"),
        );
    }
  }
  async function explore() {
    const data = await catalog();
    if (!["explore", "resources"].includes(state.view)) return;
    const params = new URLSearchParams(location.search);
    let kind = ["style", "layout", "color"].includes(params.get("kind"))
      ? params.get("kind")
      : "style";
    let query = (params.get("q") || "").slice(0, 100);
    let count = 12;
    const tabs = el("div", {
      class: "hw-resource-tabs",
      role: "group",
      "aria-label": "图库类型",
    });
    const search = el("input", {
      type: "search",
      class: "hw-library-search",
      placeholder: "搜索名称、编号或关键词，如水彩、FA-001",
      "aria-label": "搜索官方图库",
      maxlength: 100,
    });
    search.value = query;
    const status = el("p", { class: "hw-help", "aria-live": "polite" });
    const grid = el("div", { class: "hw-editorial-grid" });
    const more = button(
      "继续看 12 个 ↓",
      () => {
        count += 12;
        draw();
      },
      true,
    );
    const typeButtons = Object.entries(kinds).map(([id, title]) =>
      button(
        `${title} ${data.counts[id]}`,
        () => {
          kind = id;
          count = 12;
          draw();
        },
        true,
      ),
    );
    tabs.append(...typeButtons);
    function draw() {
      typeButtons.forEach((node, i) =>
        node.setAttribute(
          "aria-pressed",
          String(Object.keys(kinds)[i] === kind),
        ),
      );
      const q = query.trim().toLowerCase().replace(/^#/, "");
      const legacyQuery = kind === "style" && /^\d{1,3}$/.test(q);
      const items = data.resources.filter(
        (item) =>
          item.kind === kind &&
          (!q ||
            (legacyQuery
              ? item.legacy && Number(q) === Number(item.legacy)
              : `${item.id} ${item.name} ${item.description} ${item.group}`
                  .toLowerCase()
                  .includes(q))),
      );
      if (!q && kind === "style") {
        const order = new Map(
          editorial().featured.map((item, index) => [item.id, index]),
        );
        items.sort(
          (a, b) => (order.get(a.id) ?? 9999) - (order.get(b.id) ?? 9999),
        );
      }
      status.textContent = `${items.length} 个${kinds[kind]} · 已显示 ${Math.min(count, items.length)} 个`;
      grid.replaceChildren(
        ...items.slice(0, count).map((item) => resourceCard(item)),
      );
      if (!items.length)
        grid.append(
          el("p", { class: "hw-empty" }, "没有找到对应资源，试试其他关键词。"),
        );
      more.hidden = items.length <= count;
    }
    search.addEventListener("input", () => {
      query = search.value;
      count = 12;
      draw();
    });
    $("#content").replaceChildren(
      el(
        "p",
        { class: "hw-page-intro" },
        "不必先懂风格术语。先看效果，喜欢就带进创作。",
      ),
      tabs,
      search,
      status,
      grid,
      more,
      el(
        "p",
        { class: "hw-help hw-library-source" },
        "官方图库 · 编号与 Skill 保持一致。图片按需分批加载。",
      ),
    );
    $("#content").append(
      link("看看社区分享的画风与图型 →", "community", { kind: "resource" }),
    );
    draw();
    const selected = data.resources.find(
      (item) => item.id === params.get("id"),
    );
    if (selected) detail(selected);
  }
  function learn() {
    $("#content").replaceChildren(
      el(
        "p",
        { class: "hw-page-intro" },
        "先完成一次小创作，再慢慢熟悉其他功能。",
      ),
      el(
        "div",
        { class: "hw-guide-list hw-guide-list--full" },
        editorial().guides.map(guideCard),
      ),
      el(
        "div",
        { class: "hw-learn-footer" },
        el("h3", {}, "已经在使用 AI 助手？"),
        el("p", {}, "安装开源 Skill，在自己的工程里复用同一套画风与图型。"),
        el(
          "a",
          {
            href: "https://github.com/yang0/handraw-style#readme",
            target: "_blank",
            rel: "noopener noreferrer",
            class: "hw-text-link",
          },
          "查看 Skill 安装说明 ↗",
        ),
        link("到社区提问 →", "community"),
      ),
    );
    const selected = editorial().guides.find(
      (item) => item.id === new URLSearchParams(location.search).get("id"),
    );
    if (selected) guide(selected);
  }

  function ensureEngine() {
    if (engineReady) return engineReady;
    engine = el("iframe", {
      id: "composer-engine",
      title: "创作指令组件",
      hidden: true,
      src: `/studio/assets/composer.html?v=${state.boot.release}`,
    });
    engineReady = new Promise((resolve, reject) => {
      const deadline = setTimeout(() => {
        engineReady = null;
        engine.remove();
        reject(new Error("创作组件暂未就绪，请稍后重试"));
      }, 20000);
      engine.addEventListener(
        "load",
        () => {
          clearTimeout(deadline);
          resolve();
        },
        { once: true },
      );
    });
    document.body.append(engine);
    return engineReady;
  }
  window.addEventListener("message", (event) => {
    if (
      event.origin !== location.origin ||
      event.source !== engine?.contentWindow ||
      event.data?.type !== "handraw:composed"
    )
      return;
    const callback = callbacks.get(event.data.id);
    if (callback) {
      callbacks.delete(event.data.id);
      callback(event.data.command);
    }
  });
  async function compose() {
    await ensureEngine();
    const id = ++requestNumber;
    return new Promise((resolve, reject) => {
      const deadline = setTimeout(() => {
        callbacks.delete(id);
        reject(new Error("暂时没有收到创作指令，请重试"));
      }, 5000);
      callbacks.set(id, (command) => {
        clearTimeout(deadline);
        resolve(String(command || "").slice(0, 12000));
      });
      engine.contentWindow.postMessage(
        { type: "handraw:compose", id, ...draft },
        location.origin,
      );
    });
  }
  async function create() {
    const data = await catalog();
    if (state.view !== "create") return;
    const params = new URLSearchParams(location.search);
    const template = editorial().templates.find(
      (item) => item.id === params.get("template"),
    );
    const incoming = template || Object.fromEntries(params);
    for (const key of ["style", "layout", "color"])
      if (
        incoming[key] &&
        data.resources.some(
          (item) => item.kind === key && item.id === incoming[key],
        )
      )
        draft[key] = incoming[key];
    if (Object.hasOwn(modes, incoming.mode)) draft.mode = incoming.mode;
    if (["1:1", "3:4", "4:3", "16:9", "9:16"].includes(incoming.ratio))
      draft.ratio = incoming.ratio;
    if (template) {
      draft.theme = template.theme;
      draft.ratio = template.ratio;
      draft.layout = template.layout;
      draft.color = template.color;
    }
    const output = el("textarea", {
      class: "hw-command",
      readonly: true,
      "aria-label": "创作指令",
      rows: 5,
      placeholder: "写下主题后，创作指令会出现在这里。",
    });
    const status = el("p", { class: "hw-help", "aria-live": "polite" }, "");
    const theme = el("textarea", {
      class: "hw-create-theme",
      "aria-label": "你想画什么",
      placeholder: "例如：雨天的小书店，一只猫在窗边等老朋友",
      maxlength: 4000,
      rows: 4,
    });
    theme.value = draft.theme;
    let previewVersion = 0;
    const refresh = () => {
      const version = ++previewVersion;
      clearTimeout(composeTimer);
      if (!draft.theme.trim()) {
        output.value = "";
        return;
      }
      composeTimer = setTimeout(async () => {
        try {
          const command = await compose();
          if (version === previewVersion && output.isConnected) {
            output.value = command;
            status.textContent = "指令已更新。";
          }
        } catch (error) {
          if (output.isConnected) status.textContent = error.message;
        }
      }, 400);
    };
    theme.addEventListener("input", () => {
      draft.theme = theme.value;
      refresh();
    });
    const choices = el("div", { class: "hw-create-choices" });
    function drawChoices() {
      choices.replaceChildren(
        ...Object.entries(kinds).map(([kind, title]) => {
          const item = data.resources.find(
            (item) => item.id === draft[kind] && item.kind === kind,
          );
          return el(
            "button",
            {
              type: "button",
              class: "hw-create-choice",
              onclick: () => choose(kind),
            },
            el("span", { class: "hw-help" }, title),
            item
              ? el("img", {
                  src: item.image,
                  alt: item.name,
                  width: 80,
                  height: 70,
                })
              : el(
                  "span",
                  { class: "hw-choice-empty", "aria-hidden": "true" },
                  "+",
                ),
            el("strong", {}, item ? `${item.id} · ${item.name}` : "不指定"),
            el("small", {}, "点击选择 ↗"),
          );
        }),
      );
    }
    function choose(kind) {
      let limit = 12;
      const input = el("input", {
        type: "search",
        class: "hw-library-search",
        "aria-label": `查找${kinds[kind]}`,
        placeholder: "输入名称、编号或关键词",
        maxlength: 100,
      });
      const grid = el("div", { class: "hw-picker-grid" });
      const more = button(
        "继续看 12 个 ↓",
        () => {
          limit += 12;
          draw();
        },
        true,
      );
      function draw() {
        const query = input.value.toLowerCase();
        const items = data.resources.filter(
          (item) =>
            item.kind === kind &&
            `${item.id} ${item.name} ${item.description}`
              .toLowerCase()
              .includes(query),
        );
        grid.replaceChildren(
          ...items.slice(0, limit).map((item) =>
            el(
              "button",
              {
                type: "button",
                onclick: () => {
                  draft[kind] = item.id;
                  $("#modal").close();
                  drawChoices();
                  refresh();
                },
              },
              el("img", {
                src: item.image,
                alt: item.name,
                width: 160,
                height: 150,
              }),
              el("strong", {}, `${item.id} · ${item.name}`),
            ),
          ),
        );
        more.hidden = items.length <= limit;
      }
      input.addEventListener("input", () => {
        limit = 12;
        draw();
      });
      modal(
        `选择${kinds[kind]}`,
        input,
        button(
          "不指定，沿用画风或内容的需要",
          () => {
            draft[kind] = "";
            $("#modal").close();
            drawChoices();
            refresh();
          },
          true,
        ),
        grid,
        more,
      );
      draw();
    }
    const mode = el(
      "select",
      { id: "create-mode", "aria-label": "创作类型" },
      Object.entries(modes).map(([value, name]) =>
        el("option", { value }, name),
      ),
    );
    mode.value = draft.mode;
    mode.addEventListener("change", () => {
      draft.mode = mode.value;
      refresh();
    });
    const ratio = el(
      "select",
      { id: "create-ratio", "aria-label": "画幅比例" },
      ["1:1", "3:4", "4:3", "16:9", "9:16"].map((value) =>
        el("option", { value }, value),
      ),
    );
    ratio.value = draft.ratio;
    ratio.addEventListener("change", () => {
      draft.ratio = ratio.value;
      refresh();
    });
    const mood = el("input", {
      id: "create-mood",
      type: "text",
      "aria-label": "画面情绪",
      placeholder: "例如：安静、温暖",
      maxlength: 100,
    });
    mood.value = draft.mood;
    mood.addEventListener("input", () => {
      draft.mood = mood.value;
      refresh();
    });
    const workspace = el(
      "div",
      { class: "hw-create-workspace" },
      el(
        "section",
        { class: "hw-create-inputs" },
        el("label", { for: "create-mode" }, "01 / 你想做什么？"),
        mode,
        el("h3", {}, "02 / 写下你的画面"),
        theme,
        el(
          "div",
          { class: "hw-example-themes" },
          ...["窗台晒太阳的猫咪", "一家街角咖啡馆", "春天的野餐邀请"].map(
            (text) =>
              button(
                text,
                () => {
                  draft.theme = text;
                  theme.value = text;
                  refresh();
                },
                true,
              ),
          ),
        ),
        el("h3", {}, "03 / 选一个视觉方向"),
        choices,
        el(
          "details",
          { class: "hw-advanced" },
          el("summary", {}, "高级设置"),
          el("label", { for: "create-ratio" }, "画幅比例"),
          ratio,
          el("label", { for: "create-mood" }, "画面情绪（选填）"),
          mood,
        ),
      ),
      el(
        "section",
        { class: "hw-create-result" },
        el("p", { class: "hw-eyebrow" }, "YOUR NEXT PICTURE / 下一张画"),
        el("h3", {}, "准备好，就开始。"),
        el("div", { id: "online-generation" }),
        output,
        status,
        button(
          "复制创作指令",
          async (node) => {
            if (!draft.theme.trim()) throw new Error("先写下你想画什么。");
            const text = await compose();
            output.value = text;
            await navigator.clipboard.writeText(text);
            node.textContent = "已复制 ✓";
          },
          true,
        ),
        button(
          "分享这个视觉组合",
          async () => {
            const params = new URLSearchParams({
              view: "create",
              mode: draft.mode,
              ratio: draft.ratio,
            });
            for (const kind of ["style", "layout", "color"])
              if (draft[kind]) params.set(kind, draft[kind]);
            await navigator.clipboard.writeText(
              `${location.origin}/studio?${params}`,
            );
            tell("已复制组合链接，不包含你填写的主题或私人图片。");
          },
          true,
        ),
        el(
          "p",
          { class: "hw-help" },
          "复制给已安装手绘风 Skill 的 AI 助手使用。",
        ),
        el(
          "a",
          {
            href: "https://static.handraw-style.com/gallery/tutorials.html?web=3",
            class: "hw-text-link",
            target: "_blank",
            rel: "noopener",
          },
          "打开完整拼装器 ↗",
        ),
      ),
    );
    $("#content").replaceChildren(
      el(
        "p",
        { class: "hw-page-intro" },
        "先说清你想画什么。画风、图型和配色，慢慢挑。",
      ),
      workspace,
    );
    drawChoices();
    refresh();
    generationPanel($("#online-generation"), data);
  }
  let generationClient;
  let generationTimer;
  async function generationPanel(container, catalogData) {
    clearTimeout(generationTimer);
    const capability = state.boot.generation || {};
    container.className = "hw-online-panel";
    const generate = button(
      state.boot.user ? "在线生成一张" : "登录后在线生图",
      async () => {
        if (!state.boot.user) {
          sessionStorage.setItem("handraw-create-draft", JSON.stringify(draft));
          location.href = "/login";
          return;
        }
        if (draft.theme.trim().length < 5)
          throw new Error("用至少五个字描述你想画什么。");
        const selected = ["style", "layout", "color"]
          .map((kind) =>
            catalogData.resources.find(
              (item) => item.kind === kind && item.id === draft[kind],
            ),
          )
          .filter(Boolean);
        const prompt = [
          "请直接生成一张符合以下要求的图片。不要把说明、资源编号或参数标签画进画面。",
          `画面内容：${draft.theme.trim()}`,
          `创作类型：${modes[draft.mode]}。目标画幅比例：${draft.ratio}。${draft.mood ? `画面情绪：${draft.mood}` : ""}`,
          ...selected.map(
            (item) =>
              `${kinds[item.kind]}视觉定义（${item.id}）：${item.definition || item.description}`,
          ),
          draft.mode === "pure" || draft.mode === "photo"
            ? "除非画面内容明确要求，不要额外添加文字。"
            : "如果画面内容包含标题或文案，请保持文字准确、清晰可读。",
        ]
          .join("\n\n")
          .slice(0, 16000);
        const fingerprint = JSON.stringify([prompt, draft.ratio]);
        if (generationClient?.fingerprint !== fingerprint)
          generationClient = { fingerprint, id: crypto.randomUUID() };
        await api("/generations", {
          method: "POST",
          body: JSON.stringify({
            client_id: generationClient.id,
            prompt,
            title: draft.theme.trim(),
            ratio: draft.ratio,
          }),
        });
        await refresh(true);
      },
    );
    if (!capability.enabled || (state.boot.user && !capability.available))
      generate.disabled = true;
    container.append(
      generate,
      el(
        "p",
        { class: "hw-help" },
        !capability.enabled
          ? "在线生图正在准备。当前可使用上方的创作指令。"
          : !state.boot.user
            ? "登录后查看试运行资格。生成结果由你决定是否分享。"
            : !capability.available
              ? "目前向试运行创作者开放，其他账号可先使用创作指令。"
              : `试运行：每天最多提交 ${capability.daily_limit} 次，同时生成一张。生成结果不会自动公开。`,
      ),
    );
    if (!state.boot.user) return;
    const history = el("div", {
      class: "hw-generation-history",
      "aria-live": "polite",
    });
    container.append(history);
    async function refresh(poll = false) {
      if (!container.isConnected) return;
      try {
        const data = await api(`/generations${poll ? "?refresh=1" : ""}`);
        if (!container.isConnected) return;
        const pending = data.tasks.some((task) =>
          ["queued", "running"].includes(task.status),
        );
        if (
          generationClient &&
          data.tasks.some(
            (task) =>
              task.client_id === generationClient.id &&
              ["success", "error"].includes(task.status),
          )
        )
          generationClient = null;
        generate.disabled =
          !capability.available || pending || data.remaining <= 0;
        history.replaceChildren(
          el(
            "p",
            { class: "hw-help" },
            `今日还可提交 ${data.remaining} 次 · 最近的创作`,
          ),
          ...data.tasks.slice(0, 5).map((task) => {
            const row = el(
              "div",
              { class: "hw-generation" },
              el("p", {}, task.title),
              el(
                "small",
                {},
                {
                  queued: "排队或等待确认中…",
                  running: "正在绘制，请稍等…",
                  success: "已经画好了。",
                  error: "本次未能完成。",
                }[task.status] || task.status,
              ),
            );
            if (task.message)
              row.append(el("p", { class: "hw-help" }, task.message));
            if (task.status === "queued" && task.message)
              row.append(
                button(
                  "重试确认这次任务",
                  async () => {
                    await api(`/generations/${task.id}/retry`, {
                      method: "POST",
                      body: "{}",
                    });
                    await refresh(true);
                  },
                  true,
                ),
              );
            for (const [index, src] of task.images.entries()) {
              row.append(
                el("img", {
                  src,
                  alt: task.title,
                  class: "hw-generated-image",
                }),
                el(
                  "div",
                  { class: "hw-actions" },
                  el(
                    "a",
                    {
                      href: src,
                      download: `handraw-${task.id}-${index}.png`,
                      class: "hw-text-link",
                    },
                    "保存图片 ↓",
                  ),
                  button(
                    "分享这张图",
                    async () => {
                      const response = await fetch(src, {
                        credentials: "same-origin",
                      });
                      if (!response.ok)
                        throw new Error("图片暂时无法读取，请稍后再试");
                      const blob = await response.blob();
                      const image = new File([blob], `handraw-${task.id}.png`, {
                        type: blob.type,
                      });
                      share("work", {
                        title: task.title,
                        image,
                        summary: "在手绘风创作台完成的作品。",
                      });
                    },
                    true,
                  ),
                ),
              );
            }
            return row;
          }),
        );
        if (pending)
          generationTimer = setTimeout(() => {
            if (container.isConnected && document.visibilityState === "visible")
              refresh(true);
            else if (container.isConnected)
              generationTimer = setTimeout(() => refresh(true), 30000);
          }, 15000);
      } catch (error) {
        history.replaceChildren(
          el("p", { class: "hw-help" }, error.message),
          button("重新查看生成记录", () => refresh(true), true),
        );
      }
    }
    await refresh();
  }
  return { home, explore, create, learn, draft, catalog, compose };
};
