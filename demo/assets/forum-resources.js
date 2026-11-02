(function () {
  "use strict";

  const S = window.HANDRAW_SHARED;
  if (!S) return;
  const App = S.App;
  const esc = S.esc;
  const toast = S.toast;
  const channelUrl = S.channelUrl;

  const DETAIL_KINDS = ["style", "layout", "work", "asset"];
  const REL_TABS = {
    asset: ["works", "topics"],
    work: ["styles", "layouts", "topics"],
    style: ["works", "layouts", "topics"],
    layout: ["works", "styles", "topics"],
  };
  const TAB_LABEL = { works: "相关作品", styles: "相关画风", layouts: "相关图型", topics: "相关讨论" };
  const SORT_LABEL = { newest: "最新", popular: "热门" };
  const SOURCE_LABEL = {
    official: "官方", official_override: "官方", exclusive: "独占", community: "共创",
    submission: "投稿", fork: "二创",
  };
  const STATUS_LABEL = {
    published: "已发布", pending: "待审核", approved: "已通过", rejected: "已驳回", changes_requested:"待修改", withdrawn:"已撤回",
    hidden: "已下架", draft: "草稿", archived: "已归档",
  };
  const COMMENT_TYPE_LABEL = { asset_comment: "资源评论", work_comment: "作品评论", forum_reply: "帖子回复" };
  const PREVIEW = 4;
  const PAGE = 24;
  const PAGE_MAX = 36;
  const COMMENT_PAGE = 20;

  /* ----------------------- small utils ----------------------- */

  function safeUrl(u) {
    const s = String(u == null ? "" : u).trim();
    if (!s) return "";
    if (s[0] === "/" && s[1] !== "/" && s[1] !== "\\") return s;
    if (/^https?:\/\//i.test(s)) return s;
    return "";
  }

  function normReqKind(k) {
    const v = String(k || "").toLowerCase();
    if (v === "asset") return "asset";
    return DETAIL_KINDS.indexOf(v) >= 0 ? v : "";
  }

  function canonKind(resource, reqKind) {
    const k = String((resource && resource.kind) || "").toLowerCase();
    if (k === "asset") {
      const inner = String((resource && resource.assetKind) || "").toLowerCase();
      return inner === "layout" ? "layout" : "style";
    }
    if (DETAIL_KINDS.indexOf(k) >= 0) return k === "asset" ? "style" : k;
    return reqKind === "asset" ? "style" : reqKind || "work";
  }

  function resName(r) {
    return String((r && (r.name || r.title)) || "").trim();
  }

  function resourceLabel(kind, item) {
    try {
      if ((kind === "style" || kind === "layout") && S.resourceLabel) {
        const v = S.resourceLabel(item);
        if (v) return String(v);
      }
    } catch (_e) {}
    return resName(item) || String((item && item.id) || "");
  }

  function stripHtml(v) {
    if (S.stripHtmlToSnippet) return S.stripHtmlToSnippet(v, 99999);
    const s = String(v == null ? "" : v);
    if (!s) return "";
    try {
      const doc = new DOMParser().parseFromString(s, "text/html");
      doc.querySelectorAll("script, style, svg, math, iframe").forEach(el => el.remove());
      return doc.body.textContent || "";
    } catch (_e) {
      return s.replace(/<[^>]*>/g, "");
    }
  }

  function detailUrl(kind, id) {
    return channelUrl("main", { view: kind === "work" ? "work" : "asset", id: id });
  }
  function relatedUrl(kind, id, tab) {
    const base = channelUrl("forum", { view: "related", kind: kind, id: id });
    return tab ? base + (base.indexOf("?") >= 0 ? "&" : "?") + "tab=" + encodeURIComponent(tab) : base;
  }
  function topicUrl(id) {
    return channelUrl("forum", { view: "topic", id: id });
  }
  function studioWorkUrl(id) {
    return channelUrl("studio", { entry: "quick", fork: id });
  }
  function studioStyleUrl(id) {
    return channelUrl("studio", { entry: "quick", style: String(id || "").toUpperCase().replace(/^#/, "") });
  }
  function studioLayoutUrl(id) {
    return channelUrl("studio", { entry: "quick", layout: String(id || "").toUpperCase().replace(/^#/, "") });
  }
  function mainWorks() {
    return channelUrl("main", { view: "works" });
  }

  function apiGet(path) {
    return S.apiJson(path, { method: "GET" });
  }

  function mediaHtml(src, alt, cls) {
    const u = safeUrl(src);
    if (!u) return `<div class="${cls ? cls + "-empty" : "hrp-empty-media"} hrp-media-empty" role="img" aria-label="${esc(alt || "暂无图片")}"></div>`;
    return `<img data-hw-src="${esc(u)}" alt="${esc(alt || "")}" loading="lazy" decoding="async" class="${cls || ""}" />`;
  }

  function scan(root) {
    try {
      if (window.HandrawImageLoader && typeof window.HandrawImageLoader.scan === "function") {
        window.HandrawImageLoader.scan(root);
      }
    } catch (_e) {}
  }

  function isLoggedIn() {
    return !!(App && App.state && App.state.loggedIn);
  }
  function currentUser() {
    return (App && App.state && App.state.user) || null;
  }
  function accountKey() {
    const u = currentUser();
    return u ? String(u.id || u.username || "") : "";
  }

  function withLogin(action, reason) {
    if (isLoggedIn()) { action(); return; }
    const href = window.location.href;
    S.openLoginModal(reason || "登录后即可使用该功能。", function () {
      let same = false;
      try { same = window.location.href === href; } catch (_e) { same = false; }
      if (same) action();
      else window.location.href = href;
    });
  }

  function copyShare(title, url) {
    const text = (title ? title + "\n" : "") + url;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          () => toast("🔗 链接已复制，可粘贴分享"),
          () => fallbackShare(text)
        );
        return;
      }
    } catch (_e) {}
    fallbackShare(text);
  }
  function fallbackShare(text) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      toast(ok ? "🔗 链接已复制，可粘贴分享" : "复制失败，请手动复制地址栏链接");
    } catch (_e) {
      toast("复制失败，请手动复制地址栏链接");
    }
  }

  function collectBucket(kind) {
    if (kind === "layout") return "layouts";
    if (kind === "work") return "works";
    if (kind === "topic") return "topics";
    return "styles";
  }
  function collectId(kind, id) {
    if (kind === "style" || kind === "layout") return String(id || "").trim().toUpperCase().replace(/^#/, "");
    return String(id || "").trim();
  }
  function isCollected(kind, id) {
    try { return !!S.isCollected(collectBucket(kind), collectId(kind, id)); } catch (_e) { return false; }
  }
  function likeType(kind) {
    if (kind === "work") return "work";
    if (kind === "topic") return "topic";
    return kind === 'layout' ? 'layout' : 'style';
  }
  function isLiked(kind, id) {
    try {
      const key = kind === 'style' || kind === 'layout' ? collectId(kind, id) : String(id || "").trim();
      return !!S.isLiked(likeType(kind), key);
    } catch (_e) { return false; }
  }

  /* ----------------------- card model ----------------------- */

  function cardKind(item) {
    const k = String((item && item.kind) || "").toLowerCase();
    if (k === "topic") return "topic";
    if (k === "work") return "work";
    if (k === "layout") return "layout";
    return "style";
  }
  function cardHref(item) {
    const k = cardKind(item);
    if (k === "topic") return topicUrl(item.id);
    return detailUrl(k, item.id);
  }

  function renderCard(item) {
    const k = cardKind(item);
    const name = k === 'style' || k === 'layout' ? resourceLabel(k,item) : resName(item) || String(item.id || "");
    const kindLabel = k === "topic" ? "讨论" : k === "work" ? "作品" : k === "layout" ? "图型" : "画风";
    const idLine = k === "style" || k === "layout"
      ? `<span class="hrp-card-id">#${esc(collectId(k, item.id))}</span>`
      : "";
    const author = item.authorName ? `<span class="hrp-card-author">@${esc(item.authorName)}</span>` : "";
    const usage = (k === "style" || k === "layout") && item.usageCount != null
      ? `<span class="hrp-card-meta">${Number(item.usageCount) || 0} 次使用</span>` : "";
    return `
      <a class="hrp-card" href="${esc(cardHref(item))}" data-res-kind="${esc(k)}" data-res-id="${esc(item.id)}">
        <div class="hrp-card-media">
          ${mediaHtml(item.image, name, "hrp-card-img")}
          <span class="hrp-card-badge">${esc(kindLabel)}</span>
        </div>
        <div class="hrp-card-body">
          <div class="hrp-card-title">${esc(k === "style" || k === "layout" ? resourceLabel(k, item) : name)}</div>
          <div class="hrp-card-sub">${idLine}${author}${usage}</div>
        </div>
      </a>`;
  }

  function renderCardGrid(items) {
    if (!items || !items.length) return "";
    return `<div class="hrp-grid">${items.map(renderCard).join("")}</div>`;
  }

  /* ----------------------- chrome states ----------------------- */

  let _epoch = 0;

  function renderLoading(root, label) {
    root.innerHTML = `
      <div class="hrp-page">
        <div class="hrp-loading" role="status" aria-live="polite">
          <span class="hrp-spinner" aria-hidden="true"></span>
          <span>${esc(label || "正在加载…")}</span>
        </div>
      </div>`;
  }

  function renderError(root, msg, retry) {
    root.innerHTML = `
      <div class="hrp-page">
        <div class="hrp-error" role="alert">
          <p class="hrp-error-msg">${esc(msg || "加载失败，请稍后重试")}</p>
          <button type="button" class="btn btn-primary" data-hrp-retry>重试</button>
        </div>
      </div>`;
    const b = root.querySelector("[data-hrp-retry]");
    if (b) b.onclick = retry;
  }

  /* ----------------------- detail page (resolve and redirect) ----------------------- */

  function inferKind(kind, id) {
    if (kind && kind !== "asset") return kind;
    const clean = String(id || "").trim().toUpperCase().replace(/^#/, "");
    const prefix2 = clean.slice(0, 2);
    if (clean.startsWith("F") || prefix2.startsWith("F")) return "style";
    if (["SC", "IG", "SB", "IP", "EC", "LX"].includes(prefix2)) return "layout";
    return "style";
  }

  function renderDetail(root, params, reqKind, reqId) {
    renderLoading(root, "正在跳转至帖子…");
    const myEpoch = ++_epoch;
    const actualKind = inferKind(reqKind, reqId);
    apiGet(`/api/posts/by-ref/${encodeURIComponent(actualKind)}/${encodeURIComponent(reqId)}`)
      .then((res) => {
        if (myEpoch !== _epoch) return;
        if (res && res.ok && res.topicId) {
          const query = { view: "topic", id: res.topicId };
          const p = (params instanceof URLSearchParams) ? params : new URLSearchParams(params || "");
          if (p.get("focus") === "comment") {
            query.focus = "comment";
          }
          const dest = channelUrl("forum", query);
          window.location.replace(dest);
        } else {
          renderError(root, "资源不存在", null);
        }
      })
      .catch((_err) => {
        if (myEpoch !== _epoch) return;
        renderError(root, "资源不存在", null);
      });
  }

  /* ----------------------- related page ----------------------- */

  function renderRelated(root, params, reqKind, reqId) {
    let allowed = REL_TABS[reqKind] || REL_TABS.work;
    const st = {
      tab: String(params.get("tab") || "").toLowerCase(),
      sort: String(params.get("sort") || "newest").toLowerCase(),
      q: String(params.get("q") || ""),
      offset: parseInt(params.get("offset"), 10) || 0,
    };
    if (allowed.indexOf(st.tab) < 0) st.tab = allowed[0];
    if (st.sort !== "newest" && st.sort !== "popular") st.sort = "newest";
    if (st.offset < 0) st.offset = 0;

    renderLoading(root, "正在加载相关内容…");
    const myEpoch = _epoch + 1;
    _epoch = myEpoch;
    const myAccount = accountKey();

    function sourceIdentity(res) {
      const r = (res && res.resource) || {};
      const ck = canonKind(r, reqKind);
      const label = resName(r) || String(r.id || reqId);
      const link = detailUrl(ck, r.id || reqId);
      return `
        <nav class="hrp-crumb" aria-label="面包屑">
          <a href="${esc(channelUrl('forum'))}">社区</a>
          <span aria-hidden="true">/</span>
          <a href="${esc(link)}" data-hrp-backdetail>${esc(ck === "style" || ck === "layout" ? resourceLabel(ck, r) : label)}</a>
          <span aria-hidden="true">/</span>
          <span class="hrp-crumb-cur">${esc(TAB_LABEL[st.tab] || "相关内容")}</span>
        </nav>`;
    }

    function load() {
      const cur = ++_epoch;
      const acct = accountKey();
      // Fetch identity + related list in parallel.
      const relQs = new URLSearchParams();
      relQs.set("tab", st.tab);
      relQs.set("sort", st.sort);
      relQs.set("q", st.q);
      relQs.set("offset", String(st.offset));
      relQs.set("limit", String(Math.min(PAGE, PAGE_MAX)));
      const relatedPath = `/api/forum/resources/${encodeURIComponent(reqKind)}/${encodeURIComponent(reqId)}/related?${relQs.toString()}`;
      const detailPath = `/api/forum/resources/${encodeURIComponent(reqKind)}/${encodeURIComponent(reqId)}`;
      Promise.all([
        apiGet(relatedPath),
        apiGet(detailPath).catch(() => null),
      ])
        .then(([rel, det]) => {
          if (cur !== _epoch || acct !== accountKey()) return;
          if (!rel || !rel.ok) throw new Error((rel && rel.error) || "相关内容加载失败");
          paint(rel, det);
        })
        .catch((err) => {
          if (cur !== _epoch) return;
          if (acct !== accountKey()) { renderRelated(root, params, reqKind, reqId); return; }
          renderError(root, (err && err.message) || "相关内容加载失败", load);
        });
    }

    function pushUrl() {
      try {
        const link = channelUrl("forum", { view: "related", kind: reqKind, id: reqId });
        const p = new URLSearchParams();
        p.set("tab", st.tab);
        p.set("sort", st.sort);
        if (st.q) p.set("q", st.q);
        if (st.offset > 0) p.set("offset", String(st.offset));
        window.history.pushState({}, "", link + "&" + p.toString());
        params = new URLSearchParams(window.location.search);
      } catch (_e) {}
    }

    function paint(rel, det) {
      if (det?.resource) {
        const ck = canonKind(det.resource, reqKind);
        reqKind = ck;
        allowed = (REL_TABS[ck] || []).filter(t => t === st.tab || det.relations?.some(r => r.tab === t && r.total > 0));
      }
      const items = Array.isArray(rel.items) ? rel.items : [];
      const total = Number(rel.total) || 0;
      const appTotal = items.length;
      const start = st.offset;
      const end = total ? Math.min(start + appTotal, total) : 0;
      const hasPrev = start > 0;
      const hasNext = start + appTotal < total;

      root.innerHTML = `
        <div class="hrp-page hrp-related" data-hrp-kind="${esc(reqKind)}">
          ${sourceIdentity(det)}
          <div class="hrp-related-head">
            <h1 class="hrp-related-title">${esc(TAB_LABEL[st.tab] || "相关内容")}</h1>
            <span class="hrp-related-count">共 ${total} 项</span>
          </div>
          <div class="hrp-related-controls">
            <div class="hrp-tabs" role="tablist">
              ${allowed.map((t) => `<button type="button" class="hrp-tab${t === st.tab ? " is-active" : ""}" role="tab" aria-selected="${t === st.tab}" data-hrp-rtab="${esc(t)}">${esc(TAB_LABEL[t] || t)}</button>`).join("")}
            </div>
            <form class="hrp-search" data-hrp-search role="search">
              <label class="hrp-sr-label" for="hrp-search-input">搜索</label>
              <input id="hrp-search-input" class="hrp-search-input" type="search" name="q" value="${esc(st.q)}" placeholder="搜索关键词…" />
              <button type="submit" class="btn btn-sm">搜索</button>
            </form>
            <div class="hrp-sort" role="group" aria-label="排序">
              ${Object.keys(SORT_LABEL).map((k) => `<button type="button" class="hrp-sort-btn${k === st.sort ? " is-active" : ""}" data-hrp-sort="${k}" aria-pressed="${k === st.sort}">${esc(SORT_LABEL[k])}</button>`).join("")}
            </div>
          </div>
          <div class="hrp-related-body">
            ${items.length
              ? renderCardGrid(items)
              : `<div class="hrp-empty" role="status"><p>暂无相关内容${st.q ? "，可尝试清空搜索" : ""}。</p><button type="button" class="btn" data-hrp-clear>清空筛选并返回全部</button></div>`}
          </div>
          <div class="hrp-pager">
            <button type="button" class="btn btn-sm" data-hrp-prev ${hasPrev ? "" : "disabled"}>上一页</button>
            <span class="hrp-pager-info">${total ? `${start + 1}–${end} / ${total}` : "0 / 0"}</span>
            <button type="button" class="btn btn-sm" data-hrp-next ${hasNext ? "" : "disabled"}>下一页</button>
          </div>
        </div>`;

      bind(root);
      scan(root);
    }

    function bind(root) {
      root.querySelectorAll("[data-hrp-rtab]").forEach((b) => {
        b.onclick = () => { st.tab = b.getAttribute("data-hrp-rtab"); st.offset = 0; pushUrl(); renderRelated(root, params, reqKind, reqId); };
      });
      root.querySelectorAll("[data-hrp-sort]").forEach((b) => {
        b.onclick = () => { st.sort = b.getAttribute("data-hrp-sort"); st.offset = 0; pushUrl(); renderRelated(root, params, reqKind, reqId); };
      });
      const form = root.querySelector("[data-hrp-search]");
      if (form) {
        form.onsubmit = (ev) => {
          ev.preventDefault();
          const inp = form.querySelector('input[name="q"]');
          st.q = String((inp && inp.value) || "").trim();
          st.offset = 0;
          pushUrl();
          renderRelated(root, params, reqKind, reqId);
        };
      }
      const clear = root.querySelector("[data-hrp-clear]");
      if (clear) {
        clear.onclick = () => { st.q = ""; st.offset = 0; st.sort = "newest"; st.tab = allowed[0]; pushUrl(); renderRelated(root, params, reqKind, reqId); };
      }
      const prev = root.querySelector("[data-hrp-prev]");
      if (prev) prev.onclick = () => { if (st.offset <= 0) return; st.offset = Math.max(0, st.offset - PAGE); pushUrl(); renderRelated(root, params, reqKind, reqId); window.scrollTo(0, 0); };
      const next = root.querySelector("[data-hrp-next]");
      if (next) next.onclick = () => { st.offset += PAGE; pushUrl(); renderRelated(root, params, reqKind, reqId); window.scrollTo(0, 0); };
    }

    load();
  }

  /* ----------------------- entry ----------------------- */

  function render(root, params) {
    if (!root) return;
    if (!root.classList.contains("hrp")) root.classList.add("hrp");
    const p = (params instanceof URLSearchParams) ? params : new URLSearchParams(params || "");
    const view = String(p.get("view") || "").toLowerCase();
    const rawKind = normReqKind(p.get("kind"));
    const id = String(p.get("id") || "").trim();

    if (!rawKind || !id) {
      renderError(root, "参数不完整或类型不受支持", function () { render(root, p); });
      return;
    }
    if (view === "related") renderRelated(root, p, rawKind, id);
    else renderDetail(root, p, rawKind, id);
  }

  window.HandrawResourcePages = { render, cancel: () => { ++_epoch; } };
})();
