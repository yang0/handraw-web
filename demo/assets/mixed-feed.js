/* Handraw mixed discovery feed: works first, resources and independent discussions as supporting cards. */
(function () {
  "use strict";
  var S = window.HANDRAW_SHARED;
  var App = S.App;
  var currentTab = "recommended";
  var query = "";
  var visibleCount = 24;
  var observer = null;
  var searchTimer = 0;
  var searchSeq = 0;
  var searchAbort = null;
  var remoteSearch = null;
  var loadingScenarios = false;
  var ratioBoundRoots = new WeakSet();
  var SEARCH_CHANNEL_LABELS = {
    styles: "画风",
    layouts: "图型",
    colors: "主题色",
    works: "作品",
    forum: "社区"
  };
  var PATTERN = ["work", "work", "work", "resource", "work", "work", "work", "topic",
    "work", "work", "work", "resource", "work", "work", "work", "topic",
    "work", "work", "resource", "work"];
  var TABS = [
    ["recommended", "推荐"], ["latest", "最新"], ["work", "作品"],
    ["resource", "画风 / 图型"], ["topic", "讨论"]
  ];

  function esc(value) { return S.esc(value == null ? "" : String(value)); }
  function url(channel, params) { return esc(S.channelUrl(channel, params)); }
  function pic(input) {
    if (typeof input === "string") return input;
    return input && typeof input === "object" ? (input.url || input.imageUrl || "") : "";
  }
  function firstImage(items) {
    return Array.isArray(items) && items.length ? pic(items[0]) : "";
  }
  function mediaRatio(item) {
    var dims = Array.isArray(item.imageDimensions) ? item.imageDimensions[0] : item.imageDimensions;
    var x = Number(dims && (dims.width || dims.w));
    var y = Number(dims && (dims.height || dims.h));
    if (x > 0 && y > 0) return x + " / " + y;
    var ratio = String(item.ratio || item.aspectRatio || "").trim();
    var match = /^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/.exec(ratio);
    return match && Number(match[1]) > 0 && Number(match[2]) > 0 ?
      Number(match[1]) + " / " + Number(match[2]) : "";
  }
  function titleOf(item) { return String(item.title || item.name || "未命名作品"); }
  function authorOf(item) { return String(item.authorName || item.author || item.author_username || "社区创作者"); }
  function avatarFor(item, state) { const key = item.author || item.author_username; return (state && state.creatorAvatars && state.creatorAvatars[key]) || "/assets/avatar-default.svg"; }
  function timestampOf(item) {
    var raw = item.publishedAtMs || item.published_at_ms || item.createdAtMs || item.updatedAtMs || 0;
    if (Number(raw) > 100000000000) return Number(raw);
    var date = Date.parse(item.createdAt || item.updatedAt || "");
    return isFinite(date) ? date : 0;
  }
  function popularity(item) {
    return (Number(item.favorites) || 0) * 4 +
      (Number(item.forks) || 0) * 5 + (Number(item.likes) || 0) * 2 +
      (Number(item.cheers) || 0) + (Number(item.views) || 0) * 0.03 +
      (Array.isArray(item.replies) ? item.replies.length : 0) * 4;
  }
  function searchText(entry) {
    var d = entry.data;
    var codes = [].concat(Array.isArray(d.styles) ? d.styles : [])
      .concat(d.layout || d.layout_code || "");
    return [titleOf(d), d.notes, d.description, d.summary, d.authorName,
      d.author, d.id, codes.join(" ")].join(" ").toLowerCase();
  }
  function sortContent(items, latest) {
    return items.sort(function (a, b) {
      if (!latest) {
        var scoreA = popularity(a.data);
        var scoreB = popularity(b.data);
        if (scoreA !== scoreB) return scoreB - scoreA;
      }
      return timestampOf(b.data) - timestampOf(a.data);
    });
  }
  function makeItems(state, styles, layouts, opts) {
    var st = state || {};
    var options = opts || {};
    var tab = options.tab || "recommended";
    var term = String(options.query || "").trim().toLowerCase();
    var latest = tab === "latest";
    var seenWorks = new Set();
    var works = (Array.isArray(st.works) ? st.works : []).filter(function (w) {
      if (!w || !w.id || !firstImage(w.images)) return false;
      if (w.status && w.status !== "published") return false;
      var key = String(w.id);
      if (seenWorks.has(key)) return false;
      seenWorks.add(key);
      return true;
    }).map(function (w) { return { kind: "work", data: w }; });
    var seenRes = new Set();
    var resources = [].concat(Array.isArray(styles) ? styles : [])
      .concat(Array.isArray(layouts) ? layouts : [])
      .filter(function (r) {
        if (!r || !r.id || !(r.image || r.cover || r.thumbUrl)) return false;
        var key = String(r.id);
        if (seenRes.has(key)) return false;
        seenRes.add(key);
        return true;
      }).map(function (r) { return { kind: "resource", data: r }; });
    var topics = (Array.isArray(st.topics) ? st.topics : [])
      .filter(function (t) {
        // Work discussions already belong to their work card: never display twice.
        return t && t.id && t.category !== "showcase" && !t.workId && !t.work_id;
      }).map(function (t) { return { kind: "topic", data: t }; });
    var buckets = {
      work: sortContent(works, latest),
      resource: sortContent(resources, latest),
      topic: sortContent(topics, latest)
    };
    if (term) {
      Object.keys(buckets).forEach(function (kind) {
        buckets[kind] = buckets[kind].filter(function (entry) {
          return searchText(entry).indexOf(term) !== -1;
        });
      });
    }
    if (tab === "work" || tab === "resource" || tab === "topic") {
      return buckets[tab].slice(0, 480);
    }
    var result = [];
    var remaining = buckets.work.length + buckets.resource.length + buckets.topic.length;
    var idx = 0;
    var cursor = { work: 0, resource: 0, topic: 0 };
    while (remaining > 0 && result.length < 480) {
      var kind = PATTERN[idx % PATTERN.length];
      var choice = cursor[kind] < buckets[kind].length ? kind :
        (cursor.work < buckets.work.length ? "work" :
          (cursor.resource < buckets.resource.length ? "resource" : "topic"));
      if (cursor[choice] >= buckets[choice].length) break;
      result.push(buckets[choice][cursor[choice]++]);
      idx++;
      remaining--;
    }
    return result;
  }
  function workDetailHref(w, state) {
    var discussion = state && state.discussions && state.discussions[String(w.id)];
    var tid = discussion && discussion.topicId || w.topicId;
    return tid ? url("forum", { view: "topic", id: tid }) : url("main", { view: "work", id: w.id });
  }
  // A generation's requested aspect ratio is not always the actual image
  // dimensions (e.g. an edited/cropped work). Keep the estimated ratio only
  // while loading, then correct the reserved box from decoded pixels. This
  // removes the empty bands above/below object-fit:contain without cropping.
  function reconcileMediaRatio(img) {
    if (!img || !(img.naturalWidth > 0 && img.naturalHeight > 0)) return false;
    var box = img.parentElement;
    if (!box || !box.classList || !box.classList.contains("has-ratio")) return false;
    var ratio = Number(img.naturalWidth) / Number(img.naturalHeight);
    var parts = String(box.style.aspectRatio || "").split("/").map(Number);
    var previous = parts.length === 2 && parts[0] > 0 && parts[1] > 0 ?
      parts[0] / parts[1] : 0;
    // Avoid a pointless layout update when metadata already matches the image.
    if (previous > 0 && Math.abs(previous / ratio - 1) < 0.005) return false;
    box.style.aspectRatio = img.naturalWidth + " / " + img.naturalHeight;
    return true;
  }

  function bindMediaRatios(root) {
    if (!root || !root.addEventListener || !root.querySelectorAll) return;
    if (!ratioBoundRoots.has(root)) {
      // Native image 'load' doesn't bubble; capture covers cards appended
      // later, without one listener per image.
      root.addEventListener("load", function (event) {
        var img = event && event.target;
        if (img && img.tagName === "IMG") reconcileMediaRatio(img);
      }, true);
      ratioBoundRoots.add(root);
    }
    root.querySelectorAll(".hw-mf-media.has-ratio img").forEach(function (img) {
      if (img.complete) reconcileMediaRatio(img);
    });
  }

  function workCard(w, st) {
    var photo = firstImage(w.images);
    var likes = Number(w.likes || w.cheers || 0);
    var discussion = st.discussions && st.discussions[String(w.id)];
    var commentCount = Array.isArray(w.comments) ? w.comments.length :
      Number(w.replyCount || (discussion && discussion.replyCount) || 0);
    var codes = [].concat(Array.isArray(w.styles) ? w.styles : [])
      .concat(w.layout || "").filter(Boolean).slice(0, 2);
    var ratio = mediaRatio(w) || "3 / 4";
    return '<article class="hw-mf-card hw-mf-card--work">' +
      '<a class="hw-mf-media has-ratio hw-progressive-media" href="' + workDetailHref(w, st) +
      '" aria-label="查看作品：' + esc(titleOf(w)) +
      '" data-hw-refine-ratio="true" style="aspect-ratio:' + ratio + '">' +
      '<img data-hw-src="' + esc(photo) + '" alt="' + esc(titleOf(w)) + '" loading="lazy">' +
      '</a>' +
      '<div class="hw-mf-body">' +
      '<a class="hw-mf-title" href="' + workDetailHref(w, st) + '"><img class="hw-mf-title-icon" data-hw-src="/assets/feed-icons/work.png" alt="" aria-hidden="true" width="28" height="28" decoding="async">' + esc(titleOf(w)) + '</a>' +
      (codes.length ? '<div class="hw-mf-codes">' + codes.map(function (s) {
        return '<span>' + esc(s) + '</span>';
      }).join("") + '</div>' : "") +
      '<div class="hw-mf-footer"><span class="hw-mf-author">' + '<img class="hw-mf-author-avatar" alt="" data-hw-src="' + esc(avatarFor(w, st)) + '">' + esc(authorOf(w)) + '</span>' +
      '<span class="hw-mf-stats">♡ ' + esc(likes) + (commentCount ? ' · 💬 ' + esc(commentCount) : "") + '</span></div>' +
      '</div></article>';
  }
  function resourceCard(r) {
    var img = r.image || r.cover || r.thumbUrl || "";
    var kind = r.kind === "layout" || r.type === "layout" ||
      String(r.id).indexOf("SC-") === 0 || String(r.id).indexOf("IG-") === 0 ? "图型" : "画风";
    var href = url("main", { view: "asset", id: r.id });
    var ratio = mediaRatio(r) || "3 / 4";
    return '<article class="hw-mf-card hw-mf-card--resource">' +
      '<a class="hw-mf-media has-ratio hw-progressive-media" href="' + href +
      '" aria-label="查看' + kind + '：' + esc(titleOf(r)) +
      '" data-hw-refine-ratio="true" style="aspect-ratio:' + ratio + '">' +
      '<img data-hw-src="' + esc(img) + '" alt="' + esc(titleOf(r)) + '" loading="lazy">' +
      '</a>' +
      '<div class="hw-mf-body">' +
      '<a class="hw-mf-title" href="' + href + '">' + (kind === "图型" ? '<img class="hw-mf-title-icon" data-hw-src="/assets/feed-icons/layout.png" alt="" aria-hidden="true" width="28" height="28" decoding="async">' : '<img class="hw-mf-title-icon" data-hw-src="/assets/feed-icons/style.png" alt="" aria-hidden="true" width="28" height="28" decoding="async">') + esc(S.resourceLabel ? S.resourceLabel(r) : titleOf(r)) + '</a>' +
      '</div></article>';
  }
  function topicCard(t, st) {
    var img = firstImage(t.images);
    var href = url("forum", { view: "topic", id: t.id });
    var abstract = String(t.summary || t.description || t.body || "")
      .replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 90);
    var replies = Array.isArray(t.replies) ? t.replies.length : Number(t.replyCount || 0);
    // A single semantic link makes the whole text/image card clickable,
    // including whitespace, with native keyboard focus and Enter handling.
    return '<a class="hw-mf-card hw-mf-card--topic hw-mf-topic-link" href="' + href +
      '" aria-label="查看讨论：' + esc(titleOf(t)) + '">' +
      (img ? '<span class="hw-mf-media has-ratio hw-progressive-media" data-hw-refine-ratio="true" ' +
        'style="aspect-ratio:' + (mediaRatio(t) || "4 / 3") + '">' +
        '<img data-hw-src="' + esc(img) + '" alt="' +
        esc(titleOf(t)) + '" loading="lazy"></span>' : "") +
      '<div class="hw-mf-body">' +
      '<span class="hw-mf-title"><img class="hw-mf-title-icon" data-hw-src="/assets/feed-icons/discussion.png" alt="" aria-hidden="true" width="28" height="28" decoding="async">' + esc(titleOf(t)) + '</span>' +
      (abstract ? '<p class="hw-mf-excerpt">' + esc(abstract) + '</p>' : "") +
      '<div class="hw-mf-footer"><span class="hw-mf-author">' + '<img class="hw-mf-author-avatar" alt="" data-hw-src="' + esc(avatarFor(t, st)) + '">' + esc(authorOf(t)) + '</span>' +
      '<span class="hw-mf-stats">💬 ' + esc(replies) + '</span></div>' +
      '</div></a>';
  }
  function renderCard(item, st) {
    if (item.kind === "work") return workCard(item.data, st);
    if (item.kind === "resource") return resourceCard(item.data);
    return topicCard(item.data, st);
  }
  function scenarioChips(st) {
    var scenarios = Array.isArray(st.homeScenarios) && st.homeScenarios.length ?
      st.homeScenarios.slice(0, 6).map(function (s) {
        return { title: s.title, params: Object.assign({ entry: s.studioEntry || "quick" }, s.studioParams || {}) };
      }) : [
        { title: "小红书封面", params: { entry: "quick", purpose: "小红书封面" } },
        { title: "知识信息卡", params: { entry: "quick", purpose: "知识卡" } },
        { title: "公众号配图", params: { entry: "quick", purpose: "公众号配图" } },
        { title: "四格漫画", params: { entry: "quick", purpose: "四格漫画" } }
      ];
    return scenarios.map(function (s) {
      return '<a class="hw-mf-chip" href="' + url("studio", s.params) + '">' + esc(s.title) + '</a>';
    }).join("");
  }
  function requestScenarios(st, root) {
    if (loadingScenarios || st.homeScenariosFailed || Array.isArray(st.homeScenarios) || !S.apiJson) return;
    loadingScenarios = true;
    S.apiJson("/api/public/home-scenarios").then(function (res) {
      if (res && res.ok && Array.isArray(res.items) && res.items.length) {
        st.homeScenarios = res.items;
        var chips = root.querySelector(".hw-mf-scenarios");
        if (chips) chips.innerHTML = scenarioChips(st);
      } else {
        st.homeScenariosFailed = true;
      }
    }).catch(function () { st.homeScenariosFailed = true; })
      .finally(function () { loadingScenarios = false; });
  }
  function getFetch() {
    if (window && typeof window.fetch === "function") return window.fetch;
    return typeof fetch === "function" ? fetch : null;
  }
  function searchChannelForTab(tab) {
    if (tab === "work") return "works";
    if (tab === "topic") return "forum";
    return "all";
  }
  function fullSearchHref(q, tab) {
    var trimmed = String(q || "").trim();
    var ch = searchChannelForTab(tab);
    var parts = [];
    if (trimmed) parts.push("q=" + encodeURIComponent(trimmed));
    if (ch && ch !== "all") parts.push("channel=" + encodeURIComponent(ch));
    var qs = parts.length ? "?" + parts.join("&") : "";
    var base = (S && typeof S.channelUrl === "function") ? S.channelUrl("main") : "/";
    if (typeof URL === "function" && /^https?:\/\//i.test(String(base || ""))) {
      var u = new URL(base);
      u.pathname = "/search/";
      u.search = qs;
      return u.href;
    }
    return "/search/" + qs;
  }
  function safeUrl(u) {
    if (S && typeof S.safeHref === "function") return S.safeHref(u);
    var s = String(u || "");
    return /^(\/|https?:\/\/)/i.test(s) ? s : "#";
  }
  function safeImg(u) {
    if (S && typeof S.safeMediaUrl === "function") return S.safeMediaUrl(u);
    var s = String(u || "");
    return /^(\/|https?:\/\/)/i.test(s) ? s : "";
  }
  function renderParts(items) {
    if (!Array.isArray(items) || !items.length) return "";
    return items.map(function (p) {
      var text = esc((p && p.text) || "");
      return p && p.match ? "<mark>" + text + "</mark>" : text;
    }).join("");
  }
  function searchHitCard(hit) {
    var href = esc(safeUrl(hit && hit.url));
    var img = safeImg(hit && hit.image);
    var chLabel = SEARCH_CHANNEL_LABELS[hit && hit.channel] || "内容";
    var titleHtml = renderParts(hit && hit.titleParts) || esc((hit && hit.title) || chLabel);
    var snippetHtml = renderParts(hit && hit.snippetParts);
    var codeHtml = hit && hit.code ? '<span>' + esc(hit.code) + '</span>' : '';
    var authorText = hit && hit.author ? esc(hit.author) : '';
    var imgAttr = (window && window.HandrawImageLoader) ? 'data-hw-src="' : 'src="';
    return '<article class="hw-mf-card hw-mf-search-hit">' +
      (img ? '<a class="hw-mf-media" href="' + href + '">' +
        '<img ' + imgAttr + esc(img) + '" alt="" loading="lazy"></a>' : '') +
      '<div class="hw-mf-body">' +
        '<a class="hw-mf-title" href="' + href + '">' + titleHtml + '</a>' +
        (snippetHtml ? '<p class="hw-mf-snippet">' + snippetHtml + '</p>' : '') +
        '<div class="hw-mf-codes"><span>' + esc(chLabel) + '</span>' + codeHtml + '</div>' +
        '<div class="hw-mf-footer">' +
          '<span class="hw-mf-author">' + authorText + '</span>' +
          '<a class="hw-mf-stats hw-mf-remix" href="' + href + '">查看详情 ↗</a>' +
        '</div>' +
      '</div>' +
    '</article>';
  }
  function fetchSingleChannel(term, channel, sort, cursor, signal) {
    var fetchFn = getFetch();
    var qs = "q=" + encodeURIComponent(term) + "&channel=" + encodeURIComponent(channel) +
      "&sort=" + encodeURIComponent(sort);
    if (cursor) qs += "&cursor=" + encodeURIComponent(cursor);
    return fetchFn("/api/search?" + qs, {
      credentials: "include",
      cache: "no-store",
      signal: signal
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok || (data && data.ok === false)) {
          throw new Error((data && data.error) || "搜索失败");
        }
        return data || {};
      });
    });
  }
  function runRemoteSearch(root, term) {
    var fetchFn = getFetch();
    if (!term || !fetchFn) {
      remoteSearch = null;
      return;
    }
    var seq = ++searchSeq;
    if (searchAbort && typeof searchAbort.abort === "function") searchAbort.abort();
    var AC = typeof AbortController === "function" ? AbortController : (window && window.AbortController);
    searchAbort = AC ? new AC() : null;
    var signal = searchAbort ? searchAbort.signal : undefined;
    var tab = currentTab;
    var sort = tab === "latest" ? "newest" : "relevance";
    remoteSearch = {
      query: term,
      tab: tab,
      loading: true,
      loadingMore: false,
      error: "",
      hits: [],
      nextCursor: "",
      hasMore: false,
      limited: false,
      resourcePartial: false
    };
    refreshResults(root);
    var promise;
    if (tab === "resource") {
      promise = Promise.all(["styles", "layouts", "colors"].map(function (ch) {
        return fetchSingleChannel(term, ch, sort, "", signal);
      })).then(function (list) {
        var seen = {};
        var merged = [];
        list.forEach(function (d) {
          (d.hits || []).forEach(function (hit) {
            var key = (hit.channel || "") + ":" + (hit.url || hit.code || hit.title || "");
            if (!seen[key]) { seen[key] = true; merged.push(hit); }
          });
        });
        return {
          hits: merged,
          nextCursor: "",
          hasMore: list.some(function (d) { return Boolean(d.hasMore); }),
          limited: list.some(function (d) { return Boolean(d.limited); }),
          resourcePartial: true
        };
      });
    } else {
      promise = fetchSingleChannel(term, searchChannelForTab(tab), sort, "", signal);
    }
    promise.then(function (data) {
      if (seq !== searchSeq || String(query || "").trim() !== term) return;
      var inp = root.querySelector("#hw-mf-search");
      if (inp && inp.isConnected === false) return;
      remoteSearch = {
        query: term,
        tab: tab,
        loading: false,
        loadingMore: false,
        error: "",
        hits: Array.isArray(data.hits) ? data.hits : [],
        nextCursor: data.nextCursor || "",
        hasMore: Boolean(data.hasMore),
        limited: Boolean(data.limited),
        resourcePartial: Boolean(data.resourcePartial)
      };
      refreshResults(root);
    }, function (err) {
      if ((err && err.name === "AbortError") || seq !== searchSeq || String(query || "").trim() !== term) return;
      var inp = root.querySelector("#hw-mf-search");
      if (inp && inp.isConnected === false) return;
      remoteSearch = {
        query: term,
        tab: tab,
        loading: false,
        loadingMore: false,
        error: (err && err.message) ? err.message : "全站搜索暂时不可用",
        hits: [],
        nextCursor: "",
        hasMore: false,
        limited: false,
        resourcePartial: false
      };
      refreshResults(root);
    });
  }
  function loadMoreRemote(root) {
    if (!remoteSearch || remoteSearch.loading || remoteSearch.loadingMore) return;
    if (visibleCount < remoteSearch.hits.length) {
      visibleCount += 24;
      refreshResults(root);
      return;
    }
    if (remoteSearch.resourcePartial || !remoteSearch.hasMore || !remoteSearch.nextCursor) return;
    var seq = searchSeq;
    var snapshot = remoteSearch;
    var sort = snapshot.tab === "latest" ? "newest" : "relevance";
    snapshot.loadingMore = true;
    refreshResults(root);
    fetchSingleChannel(snapshot.query, searchChannelForTab(snapshot.tab), sort, snapshot.nextCursor, searchAbort ? searchAbort.signal : undefined)
      .then(function (data) {
        if (seq !== searchSeq || remoteSearch !== snapshot) return;
        snapshot.loadingMore = false;
        snapshot.hits = snapshot.hits.concat(Array.isArray(data.hits) ? data.hits : []);
        snapshot.nextCursor = data.nextCursor || "";
        snapshot.hasMore = Boolean(data.hasMore);
        visibleCount += 24;
        refreshResults(root);
      }, function () {
        if (seq !== searchSeq || remoteSearch !== snapshot) return;
        snapshot.loadingMore = false;
        refreshResults(root);
      });
  }
  function subheadTitle() {
    return currentTab === "latest" ? '最近更新' :
      currentTab === "work" ? '全部作品' : currentTab === "resource" ? '发现画风与图型' :
        currentTab === "topic" ? '社区经验与讨论' : '发现值得复刻的灵感';
  }
  function resultsHtml(st, items, create) {
    var trimmed = String(query || "").trim();
    var fullHref = esc(fullSearchHref(trimmed, currentTab));
    if (trimmed && remoteSearch && remoteSearch.query === trimmed && remoteSearch.tab === currentTab) {
      if (remoteSearch.loading && !items.length) {
        return '<div class="hw-mf-subhead"><h2>' + subheadTitle() + '</h2>' +
          '<span>正在检索全站索引…</span></div>' +
          '<div class="hw-mf-empty"><h2>正在搜索「' + esc(trimmed) + '」…</h2>' +
          '<p>正在检索全站画风、图型、主题色、作品与社区正文。</p></div>';
      }
      if (!remoteSearch.loading && !remoteSearch.error) {
        var hits = remoteSearch.hits;
        var visibleHits = hits.slice(0, visibleCount);
        var moreHits = visibleHits.length < hits.length || (!remoteSearch.resourcePartial && remoteSearch.hasMore);
        var statusText = hits.length
          ? '已显示 ' + visibleHits.length + (moreHits ? '+' : '') + ' 条全站结果'
          : '暂无匹配内容';
        return '<div class="hw-mf-subhead"><h2>' + subheadTitle() + '</h2>' +
          '<span class="hw-mf-submeta"><span>' + statusText + '</span>' +
          '<a class="hw-mf-fulltext-link" href="' + fullHref + '">在全站搜索页查看全部 ↗</a></span></div>' +
          (visibleHits.length ? '<div class="hw-mf-grid">' + visibleHits.map(searchHitCard).join("") + '</div>' :
            '<div class="hw-mf-empty"><h2>暂时没有匹配「' + esc(trimmed) + '」的内容</h2>' +
            '<p>换个关键词、编号，或切换频道在全站搜索页查看。</p>' +
            '<a href="' + fullHref + '">打开全站搜索 ↗</a></div>') +
          (moreHits ? '<div class="hw-mf-pager"><button type="button" id="hw-mf-search-more"' +
            (remoteSearch.loadingMore ? ' disabled>正在加载…</button></div>' : '>加载更多</button></div>') : '');
      }
    }
    var visible = items.slice(0, visibleCount);
    var errorNotice = (trimmed && remoteSearch && remoteSearch.query === trimmed && remoteSearch.error)
      ? '（全站检索暂不可用，当前显示已加载内容）'
      : '';
    var loadingNotice = (trimmed && remoteSearch && remoteSearch.query === trimmed && remoteSearch.loading)
      ? ' · 正在检索全站索引…'
      : '';
    return       '<div class="hw-mf-subhead"><h2>' + subheadTitle() + '</h2>' +
      '<span class="hw-mf-submeta"><span>' + (items.length ? '已找到 ' + items.length + ' 条内容' : '暂无匹配内容') +
      esc(errorNotice + loadingNotice) + '</span>' +
      (trimmed ? '<a class="hw-mf-fulltext-link" href="' + fullHref + '">在全站搜索页查看全部 ↗</a>' : '') + '</span></div>' +
      (visible.length ? '<div class="hw-mf-grid">' + visible.map(function (item) {
        return renderCard(item, st);
      }).join("") + '</div>' :
        '<div class="hw-mf-empty"><h2>暂时没有匹配的内容</h2><p>换个关键词，或从创作台开始你的第一张作品。</p>' +
        (trimmed ? '<a href="' + fullHref + '">前往全站搜索 ↗</a>' : '<a href="' + create + '">开始创作 ↗</a>') + '</div>') +
      (visible.length < items.length ? '<div class="hw-mf-pager"><button type="button" id="hw-mf-more">加载更多</button>' +
        '<div id="hw-mf-sentinel" aria-hidden="true"></div></div>' : '') +
      '';
  }
  function refreshResults(root) {
    var panel = root.querySelector(".hw-mf-results");
    if (!panel) { render(root); return; }
    if (observer) { observer.disconnect(); observer = null; }
    var st = App && App.state || {};
    var items = makeItems(st, App.styles, App.layouts, { tab: currentTab, query: query });
    panel.innerHTML = resultsHtml(st, items, url("studio", { entry: "quick" }));
    bind(root, items);
    bindMediaRatios(root);
    if (window && window.HandrawImageLoader && typeof window.HandrawImageLoader.scan === "function") {
      window.HandrawImageLoader.scan(panel);
    }
  }
  function bind(root, items) {
    root.querySelectorAll("[data-mf-tab]").forEach(function (btn) {
      btn.onclick = function () {
        currentTab = btn.getAttribute("data-mf-tab") || "recommended";
        visibleCount = 24;
        var trimmed = String(query || "").trim();
        if (trimmed && getFetch()) {
          render(root);
          runRemoteSearch(root, trimmed);
          return;
        }
        remoteSearch = null;
        render(root);
      };
    });
    var searchForm = root.querySelector("#hw-mf-search-form");
    var inp = root.querySelector("#hw-mf-search");
    function goFullSearch(raw, forceNavigate) {
      var trimmed = String(raw || "").trim();
      if (!trimmed && !forceNavigate) {
        if (inp && typeof inp.focus === "function") inp.focus();
        return;
      }
      if (window && window.location) window.location.href = fullSearchHref(trimmed, currentTab);
    }
    if (searchForm) {
      searchForm.onsubmit = function (event) {
        if (event && typeof event.preventDefault === "function") event.preventDefault();
        var viaFulltext = Boolean(event && event.submitter && event.submitter.id === "hw-mf-fulltext-btn");
        goFullSearch(inp ? inp.value : query, viaFulltext);
      };
    }
    if (inp) {
      function scheduleSearch() {
        query = inp.value;
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(function () {
          if (!inp.isConnected || inp.__hwComposing) return;
          visibleCount = 24;
          var trimmed = String(query || "").trim();
          if (!trimmed || !getFetch()) {
            if (searchAbort && typeof searchAbort.abort === "function") searchAbort.abort();
            remoteSearch = null;
            // Keep the live input/caret intact during debounced CJK search.
            refreshResults(root);
            return;
          }
          runRemoteSearch(root, trimmed);
        }, 200);
      }
      inp.oncompositionstart = function () {
        inp.__hwComposing = true;
        window.clearTimeout(searchTimer);
      };
      inp.oncompositionend = function () {
        inp.__hwComposing = false;
        scheduleSearch();
      };
      inp.oninput = function (event) {
        if (inp.__hwComposing || (event && event.isComposing)) return;
        scheduleSearch();
      };
      inp.onkeydown = function (event) {
        if (!event || event.key !== "Enter" || inp.__hwComposing || event.isComposing) return;
        if (typeof event.preventDefault === "function") event.preventDefault();
        goFullSearch(inp.value, false);
      };
    }
    var searchMore = root.querySelector("#hw-mf-search-more");
    if (searchMore) {
      searchMore.onclick = function () {
        loadMoreRemote(root);
      };
    }
    var more = root.querySelector("#hw-mf-more");
    var loadMore = function () {
      if (visibleCount >= items.length) return;
      var grid = root.querySelector(".hw-mf-grid");
      if (!grid) { render(root); return; }
      var nextCount = Math.min(items.length, visibleCount + 24);
      var nextHtml = items.slice(visibleCount, nextCount).map(function (item) {
        return renderCard(item, (App && App.state) || {});
      }).join("");
      // Keep existing image elements alive: re-rendering root.innerHTML caused
      // every previously decoded picture to flash on each "load more".
      grid.insertAdjacentHTML("beforeend", nextHtml);
      visibleCount = nextCount;
      if (visibleCount >= items.length) {
        if (observer) { observer.disconnect(); observer = null; }
        var pager = root.querySelector(".hw-mf-pager");
        if (pager) pager.remove();
      } else if (observer) {
        observer.disconnect();
        var nextSentinel = root.querySelector("#hw-mf-sentinel");
        if (nextSentinel) observer.observe(nextSentinel);
      }
      window.HandrawImageLoader?.scan(grid);
    };
    if (more) more.onclick = loadMore;
    var sentinel = root.querySelector("#hw-mf-sentinel");
    if (sentinel && typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) {
          if (observer) observer.disconnect();
          loadMore();
        }
      }, { rootMargin: "180px" });
      observer.observe(sentinel);
    }
    window.HandrawImageLoader?.scan(root);
  }
  function render(root) {
    if (!root) return;
    if (observer) { observer.disconnect(); observer = null; }
    var st = App && App.state || {};
    var items = makeItems(st, App.styles, App.layouts, { tab: currentTab, query: query });
    var visible = items.slice(0, visibleCount);
    var create = url("studio", { entry: "quick" });
    var isReturning = Boolean(st.loggedIn && st.user && st.user.username && st.user.username !== "guest");
    root.innerHTML = '<div class="hw-mixed-feed">' +
      '<header class="hw-mf-hero">' +
      '<div><p class="hw-mf-eyebrow">HANDRAW · 发现 / 创作 / 交流</p>' +
      '<h1>看见灵感，做出自己的作品。</h1>' +
      '<p class="hw-mf-intro">从社区作品中发现画风、图型和创作方法，喜欢就做同款。</p></div>' +
      '<a class="hw-mf-create" href="' + create + '">' + (isReturning ? '继续创作 ↗' : '开始创作 ↗') + '</a>' +
      '</header>' +
      '<div class="hw-mf-controls">' +
      '<form class="hw-mf-search-form" id="hw-mf-search-form" role="search">' +
      '<div class="hw-mf-search">' +
      '<button type="submit" class="hw-mf-search-btn" id="hw-mf-search-btn" aria-label="搜索" title="搜索">⌕</button>' +
      '<input id="hw-mf-search" type="search" enterkeyhint="search" placeholder="搜索作品、画风、图型、创作技巧…" value="' + esc(query) + '" aria-label="搜索首页内容" autocomplete="off"></div>' +
      '<button type="submit" class="hw-mf-fulltext-btn" id="hw-mf-fulltext-btn">全文搜索</button></form>' +
      '<nav class="hw-mf-tabs" aria-label="发现内容分类">' + TABS.map(function (tab) {
        return '<button type="button" data-mf-tab="' + tab[0] + '" class="' +
          (currentTab === tab[0] ? 'is-active' : '') + '" aria-pressed="' +
          (currentTab === tab[0] ? "true" : "false") + '">' + esc(tab[1]) + '</button>';
      }).join("") + '</nav>' +
      '</div>' +
      '<div class="hw-mf-shortcuts"><span>快速做一张</span><div class="hw-mf-scenarios">' +
      scenarioChips(st) + '</div></div>' +
      '<div class="hw-mf-results">' + resultsHtml(st, items, create) + '</div>' +
      '</div>';
    bind(root, items);
    bindMediaRatios(root);
    requestScenarios(st, root);
  }

  window.HandrawMixedFeed = {
    render: render,
    testing: { makeItems: makeItems, renderCard: renderCard, reconcileMediaRatio: reconcileMediaRatio }
  };
})();