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
  market,
}) => {
  const $ = (query) => document.querySelector(query);
  const editorial = () => state.boot.editorial;
  const kinds = { style: "画风", layout: "图型", color: "配色" };
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
  async function detail(item) {
    return market.assetDetail(item.ref || `official:${item.id}`);
  }

  function guideCard(item, index) {
    return el(
      "a",
      { class: "hw-guide-link", href: item.url || `/t/${item.topic_id}` },
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
        { class: "hw-home-section" },
        heading(
          "LAYOUTS / 给内容一个结构",
          "让内容找到合适的图型",
          link("探索全部图型 →", "explore", { type: "layout" }),
        ),
        el(
          "div",
          { class: "hw-template-grid" },
          ...(data.featured_layouts || []).map((item) =>
            market.assetCard({
              ...item,
              source: "official",
              ref: `official:${item.id}`,
            }),
          ),
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
    return market.explore();
  }
  function learn() {
    $("#content").replaceChildren(
      el(
        "p",
        { class: "hw-page-intro" },
        "整理自社区的使用教程与创作方法。点击标题，直接阅读论坛原帖。",
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
  }

  let studio;
  function create() {
    studio ||= window.HandrawStudio({
      state,
      el,
      button,
      modal,
      tell,
      api,
      share,
      market,
    });
    return studio.create();
  }
  return { home, explore, learn, create, stop: () => studio?.stop() };
};
