(function () {
  "use strict";

  var S = window.HANDRAW_SHARED;
  var App = S.App;

  function validImage(images) {
    return Array.isArray(images) && typeof images[0] === "string" && images[0];
  }

  function topTags(w, max) {
    var tags = []
      .concat(Array.isArray(w.styles) ? w.styles : [])
      .concat(w.layout ? [w.layout] : [])
      .filter(Boolean);
    return tags.slice(0, max);
  }

  function renderTasks() {
    var tasks = ["公众号配图", "小红书组图", "漫画绘本", "海报"];
    var items = tasks
      .map(function (label) {
        var href = S.channelUrl("studio", { entry: "quick", purpose: label });
        return (
          '<li class="hw-discovery__task">' +
          '<a class="hw-discovery__task-link" href="' + S.esc(href) + '">' +
          S.esc(label) +
          "</a></li>"
        );
      })
      .join("");
    return (
      '<section class="hw-discovery__tasks">' +
      '<h2 class="hw-discovery__heading">按用途开始</h2>' +
      '<ul class="hw-discovery__task-list">' + items + "</ul>" +
      "</section>"
    );
  }

  function renderEmpty() {
    var stylesHref = S.channelUrl("main", { view: "styles" });
    var studioHref = S.channelUrl("studio", { entry: "quick", purpose: "开始创作" });
    return (
      '<div class="hw-discovery__empty">' +
      "<p>暂时还没有公开作品。可以先看看画风与图型，或直接开始一次创作。</p>" +
      '<p><a class="hw-discovery__btn hw-discovery__btn--muted" href="' + S.esc(stylesHref) + '">浏览画风与图型</a> ' +
      '<a class="hw-discovery__btn" href="' + S.esc(studioHref) + '">开始创作</a></p>' +
      "</div>"
    );
  }

  function renderWorks(works, topics) {
    // Public illustrated discussions also provide a useful first visit when
    // no one has published a finished work yet. Keep their source explicit.
    var hasWorks = works.some(function (w) { return w && validImage(w.images); });
    if (!hasWorks) {
      works = topics.filter(function (t) {
        return t && Array.isArray(t.images) && t.images[0] && t.images[0].url;
      }).map(function (t) {
        return Object.assign({}, t, {
          images: [t.images[0].url],
          discussion: true,
          imageLabel: t.images[0].tag || "社区图文"
        });
      });
    }
    var picked = works
      .filter(function (w) {
        return w && typeof w.id !== "undefined" && validImage(w.images);
      })
      .slice()
      .sort(S.compareByRecency)
      .slice(0, 6);

    var body;
    if (!picked.length) {
      body = renderEmpty();
    } else {
      body =
        '<div class="hw-discovery__gallery">' +
        picked
          .map(function (w) {
            var href = S.channelUrl(w.discussion ? "forum" : "main", { view: w.discussion ? "topic" : "work", id: w.id });
            var tags = topTags(w, 3)
              .map(function (t) {
                return '<span class="hw-discovery__tag">' + S.esc(t) + "</span>";
              })
              .join("");
            return (
              '<a class="hw-discovery__card" href="' + S.esc(href) + '">' +
              '<span class="hw-discovery__media">' +
              '<img data-hw-src="' + S.esc(w.images[0]) + '" loading="lazy" alt="' + S.esc(w.title || "") + '">' +
              "</span>" +
              '<span class="hw-discovery__meta">' +
              '<span class="hw-discovery__title">' + S.esc(w.title || "") + "</span>" +
              (w.discussion ? '<span class="hw-discovery__author">' + S.esc(w.imageLabel) + "</span>" : "") +
              '<span class="hw-discovery__author">' + S.esc(w.authorName || w.author || "") + "</span>" +
              (tags ? '<span class="hw-discovery__tags">' + tags + "</span>" : "") +
              '<span class="hw-discovery__more">' + (w.discussion ? "查看讨论 →" : "查看帖子 →") + '</span>' +
              "</span>" +
              "</a>"
            );
          })
          .join("") +
        "</div>";
    }

    return (
      '<section class="hw-discovery__section">' +
      '<div class="hw-discovery__section-head">' +
      '<h2 class="hw-discovery__heading">' + (!hasWorks && picked.length ? "社区图文与参考" : "作品与做法") + '</h2>' +
      '<a class="hw-discovery__all-works" href="' + S.esc(S.channelUrl("main", {view:"works"})) + '">全部作品 →</a>' +
      '</div>' +
      body +
      "</section>"
    );
  }

  function renderResources(resources) {
    if (!Array.isArray(resources) || !resources.length) return "";
    var items = resources
      .slice()
      .sort(S.compareByRecency)
      .slice(0, 4)
      .map(function (r) {
        var href = S.channelUrl("main", { view: "asset", id: r.id });
        return (
          '<li class="hw-discovery__res-item">' +
          '<a href="' + S.esc(href) + '">' +
          '<img data-hw-src="' + S.esc(r.image || "") + '" loading="lazy" alt="' + S.esc(S.resourceLabel(r)) + '">' +
          '<span class="hw-discovery__res-name">' + S.esc(S.resourceLabel(r)) + "</span>" +
          '<span class="hw-discovery__res-id">#' + S.esc(String(r.id)) + "</span>" +
          "</a></li>"
        );
      })
      .join("");
    return (
      '<section class="hw-discovery__section">' +
      '<h2 class="hw-discovery__heading">最新资源</h2>' +
      '<ul class="hw-discovery__res-list">' + items + "</ul>" +
      "</section>"
    );
  }

  function renderTopics(topics) {
    if (!Array.isArray(topics) || !topics.length) return "";
    var items = topics
      .slice()
      .sort(S.compareByRecency)
      .slice(0, 3)
      .map(function (t) {
        var href = S.channelUrl("forum", { view: "topic", id: t.id });
        return (
          '<li class="hw-discovery__topic-item">' +
          '<a href="' + S.esc(href) + '">' +
          '<span class="hw-discovery__topic-title">' + S.esc(t.title || "") + "</span>" +
          '<span class="hw-discovery__topic-author">' + S.esc(t.authorName || "") + "</span>" +
          "</a></li>"
        );
      })
      .join("");
    return (
      '<section class="hw-discovery__section">' +
      '<h2 class="hw-discovery__heading">近期讨论</h2>' +
      '<ul class="hw-discovery__topic-list">' + items + "</ul>" +
      "</section>"
    );
  }

  function render(root) {
    var state = (App && App.state) || {};
    var works = Array.isArray(state.works) ? state.works : [];
    var topics = Array.isArray(state.topics) ? state.topics : [];
    var resources = []
      .concat(Array.isArray(App.styles) ? App.styles : [])
      .concat(Array.isArray(App.layouts) ? App.layouts : []);

    var discoverHref = S.channelUrl("main", { view: "works" });
    var createHref = S.channelUrl("studio", { entry: "quick", purpose: "开始创作" });

    var html =
      '<div class="hw-discover hw-discovery">' +
      '<div class="hw-discovery__intro">' +
      '<h1 class="hw-discovery__title">看看大家做出了什么，也把你的做法留下来。</h1>' +
      '<p class="hw-discovery__support">浏览画风、图型和真实作品，找到适合这次创作的方法。</p>' +
      '<p class="hw-discovery__cta">' +
      '<a class="hw-discovery__btn hw-discovery__btn--muted" href="' + S.esc(discoverHref) + '">发现作品</a> ' +
      '<a class="hw-discovery__btn" href="' + S.esc(createHref) + '">开始创作</a>' +
      "</p>" +
      "</div>" +
      renderWorks(works, topics) +
      renderTasks() +
      renderResources(resources) +
      renderTopics(topics) +
      "</div>";

    root.innerHTML = html;
  }

  window.HandrawDiscovery = { render: render };
})();
