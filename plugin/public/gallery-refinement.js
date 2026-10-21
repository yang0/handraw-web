"use strict";
(() => {
  const main = document.querySelector("main");
  if (!main) return;
  const cards = [
    ...main.querySelectorAll(
      ".style-card,.layout-card,.color-card,.asset-card",
    ),
  ];
  if (cards.length) {
    const bar = document.createElement("div");
    bar.className = "hw-gallery-search";
    const input = document.createElement("input");
    input.type = "search";
    input.maxLength = 100;
    input.placeholder = "搜索名称、编号或关键词";
    input.setAttribute("aria-label", "搜索图库");
    const status = document.createElement("span");
    status.setAttribute("aria-live", "polite");
    const update = () => {
      const query = input.value.toLowerCase().trim().replace(/^#/, "");
      let count = 0;
      for (const card of cards) {
        const text =
          `${card.textContent} ${Object.values(card.dataset).join(" ")}`.toLowerCase();
        const match = !query || text.includes(query);
        card.classList.toggle("hw-search-hidden", !match);
        if (match && !card.hidden) count++;
      }
      for (const group of main.querySelectorAll(".style-group")) {
        group.classList.toggle(
          "hw-search-hidden",
          ![...group.querySelectorAll(".style-card")].some(
            (card) => !card.classList.contains("hw-search-hidden"),
          ),
        );
      }
      status.textContent = query ? `${count} 个搜索结果` : "点击图片查看详情";
      window.dispatchEvent(new Event("resize"));
    };
    input.addEventListener("input", update);
    bar.append(input, status);
    const gallery = main.querySelector("#gallery");
    if (gallery && gallery.parentElement === main)
      main.insertBefore(bar, gallery);
    else main.prepend(bar);
    update();
  }
  const footer = document.createElement("details");
  footer.className = "hw-gallery-about";
  const summary = document.createElement("summary");
  summary.textContent = "使用示例与项目动态";
  footer.append(summary);
  for (const item of main.querySelectorAll(".prompt-examples,.prompt-notice"))
    footer.append(item);
  const links = document.createElement("p");
  const github = document.createElement("a");
  github.href = "https://github.com/yang0/handraw-style";
  github.textContent = "开源 Skill ↗";
  links.append(github);
  footer.append(links);
  main.append(footer);
})();
