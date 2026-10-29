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
    const s = String(v == null ? "" : v);
    if (!s) return "";
    if (!/[<>&]/.test(s)) return s;
    try {
      return new DOMParser().parseFromString(s, "text/html").body.textContent || "";
    } catch (_e) {
      return s;
    }
  }

  function detailUrl(kind, id) {
    return channelUrl("forum", { view: "resource", kind: kind, id: id });
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

  /* ----------------------- detail page ----------------------- */

  function renderDetail(root, params, reqKind, reqId) {
    renderLoading(root, "正在加载资源详情…");
    const myEpoch = _epoch + 1;
    _epoch = myEpoch;
    const myAccount = accountKey();

    function load() {
      const cur = ++_epoch;
      const acct = accountKey();
      apiGet(`/api/forum/resources/${encodeURIComponent(reqKind)}/${encodeURIComponent(reqId)}`)
        .then((res) => {
          if (cur !== _epoch || acct !== accountKey()) return;
          if (!res || !res.ok || !res.resource) throw new Error((res && res.error) || "资源不存在或不可见");
          paint(root, res, reqKind, reqId, function () { load(); });
        })
        .catch((err) => {
          if (cur !== _epoch) return;
          if (acct !== accountKey()) { renderDetail(root, params, reqKind, reqId); return; }
          renderError(root, (err && err.message) || "资源加载失败", load);
        });
    }
    load();
  }

  function paint(root, res, reqKind, reqId, reload) {
    const r = res.resource || {};
    const ck = canonKind(r, reqKind);
    try {
      if (ck !== reqKind) {
        const next = detailUrl(ck, r.id || reqId);
        if (window.location.href !== next) window.history.replaceState(window.history.state, "", next);
      }
    } catch (_e) {}

    const curation = res.curation || null;
    const thread = res.thread || null;
    const siblings = Array.isArray(res.siblings) ? res.siblings : [];
    const relations = Array.isArray(res.relations) ? res.relations : [];
    const pendingNoPub = !!(curation && !curation.hasPublishedVersion);
    const pendingWithPub = !!(curation && String(curation.status) !== "approved" && curation.hasPublishedVersion);
    const canUse = !!r.canUse && !pendingNoPub;
    r.reportTopicId = pendingNoPub ? thread?.id : null;
    const locked = r.unlocked === false;
    const name = ck === "work" ? resName(r) || "作品" : resourceLabel(ck,r);
    document.title = name + " — Handraw 社区";
    const kindName = ck === "work" ? (pendingNoPub ? "投稿预览" : "作品") : ck === "layout" ? "图型" : "画风";

    const images = [];
    if (Array.isArray(r.images)) r.images.forEach((x) => { const u = safeUrl(x); if (u) images.push(u); });
    if (safeUrl(r.image) && images.indexOf(safeUrl(r.image)) < 0) images.unshift(safeUrl(r.image));
    const mainImg = images[0] || "";
    const thumbs = images.length > 1
      ? `<div class="hrp-thumbs">${images.map((g, i) =>
          `<button type="button" class="hrp-thumb" data-hrp-thumb="${i}" aria-label="查看第 ${i + 1} 张图">${mediaHtml(g, name, "hrp-thumb-img")}</button>`
        ).join("")}</div>`
      : "";

    const desc = String(r.description || r.notes || "").trim();
    const definition = !locked && !pendingNoPub && canUse ? String(r.definition || r.prompt || "").trim() : "";
    const descBlock = desc
      ? `<section class="hrp-section"><h2 class="hrp-h2">说明</h2><p class="hrp-desc">${esc(desc)}</p></section>` : "";
    const defBlock = definition
      ? `<section class="hrp-section"><h2 class="hrp-h2">${ck === "work" ? "创作提示词" : ck === "layout" ? "图型定义" : "画风定义"}</h2><button type="button" class="btn btn-sm" data-hrp-copy>复制${ck === 'work' ? '提示词' : '定义'}</button><pre class="hrp-def">${esc(definition)}</pre></section>` : "";

    const useBtn = canUse
      ? `<a class="btn btn-primary hrp-use" href="${esc(useHref(ck, r))}" data-hrp-use="${esc(ck)}">${ck === "work" ? "🎨 复现此作品" : "✨ 使用此" + kindName}</a>`
      : "";

    let unlockBlock = "";
    if (locked && !pendingNoPub) {
      const cost = r.unlockCost != null ? r.unlockCost : r.price;
      unlockBlock = `<div class="hrp-unlock">
        <p class="hrp-unlock-note">🔒 此资源需解锁后使用</p>
        ${cost != null ? `<p class="hrp-unlock-cost">解锁花费 <strong>${esc(String(cost))}</strong> 积分</p>` : ""}
        <button type="button" class="btn btn-primary" data-hrp-unlock>解锁</button>
      </div>`;
    }

    let notice = "";
    if (pendingNoPub) notice = `<div class="hrp-notice" role="status">该资源尚未收录，当前仅提供预览。</div>`;
    else if (pendingWithPub) notice = `<div class="hrp-notice" role="status">该资源存在待审核修订，当前展示的是已发布版本，可正常使用。</div>`;

    const collected = isCollected(ck, r.id);
    const liked = isLiked(ck, r.id);
    const collectBtn = `<button type="button" class="btn btn-sm hrp-collect" data-hrp-collect aria-pressed="${collected}">${collected ? "♥ 已收藏" : "♡ 收藏"}</button>`;
    const likeBtn = `<button type="button" class="btn btn-sm hrp-like" data-hrp-like aria-pressed="${liked}">👍 点赞</button>`;
    const shareBtn = `<button type="button" class="btn btn-sm hrp-share" data-hrp-share>🔗 分享</button>`;
    const reportBtn = typeof S.openReportModal === "function"
      ? `<button type="button" class="btn btn-sm hrp-report" data-hrp-report>🚩 举报</button>` : "";

    const threadSummary = thread
      ? `<section class="hrp-section hrp-thread">
          <h2 class="hrp-h2">共用讨论</h2>
          <div class="hrp-thread-card">
            <div class="hrp-thread-title">${esc(thread.title || "讨论帖")}</div>
            <div class="hrp-thread-meta">${esc(categoryLabel(thread.category))}${thread.commentCount != null ? " · " + (Number(thread.commentCount) || 0) + " 条回复" : ""}${thread.closed ? " · 已关闭" : ""}</div>
            ${thread.body ? `<p class="hrp-thread-body">${esc(stripHtml(thread.body))}</p>` : ""}
            <a class="hrp-thread-link" href="#hrp-comments">查看共用讨论 ↓</a>
          </div>
        </section>`
      : "";

    const siblingBlock = siblings.length > 1
      ? `<section class="hrp-section hrp-siblings">
          <h2 class="hrp-h2">同帖资源</h2>
          <div class="hrp-sib-row">
            ${siblings.map((s) => {
              const sk = String(s.kind || "").toLowerCase();
              const active = String(s.id) === String(r.id);
              const href = active ? "#" : detailUrl(sk === "asset" ? "style" : sk, s.id);
              const label = resName(s) || String(s.id || "");
              return `<a class="hrp-sib${active ? " is-active" : ""}" href="${esc(href)}" ${active ? 'aria-current="page"' : ""}>${mediaHtml(s.image, label, "hrp-sib-img")}<span class="hrp-sib-name">${esc(label)}</span></a>`;
            }).join("")}
          </div>
        </section>`
      : "";

    const workPost = ck === "work" && !pendingNoPub ? window.HandrawForumWork.fromTopic(
      {id:thread?.id || '',workId:r.id,title:name,summary:r.notes || ''},
      [{...r,promptMasked:locked}],App.resourceMap,true
    ) : null;
    const relBlock = renderRelations(ck, ck === "work" ? relations.filter(x => x.tab === "topics") : relations, r.id, "");

    const composer = thread && thread.closed
      ? `<p class="hrp-composer-closed">该讨论帖已关闭，暂不可回复。</p>`
      : `<div class="hrp-composer">
          <label class="hrp-composer-label" for="hrp-composer-text">发表评论</label>
          <textarea id="hrp-composer-text" class="hrp-textarea" rows="3" placeholder="友善交流，分享你的想法…"></textarea>
          <div class="hrp-composer-actions">
            <button type="button" class="btn btn-primary" data-hrp-send>发送</button>
          </div>
        </div>`;

    root.innerHTML = `
      <div class="hrp-page hrp-detail" data-hrp-kind="${esc(ck)}">
        <nav class="hrp-crumb" aria-label="面包屑">
          <a href="${esc(channelUrl('forum'))}">社区</a>
          <span aria-hidden="true">/</span>
          <span>${esc(kindName)}</span>
          <span aria-hidden="true">/</span>
          <span class="hrp-crumb-cur">${esc(name)}</span>
        </nav>

        ${notice}
        ${pendingNoPub ? `<div class="hrp-preview-tag">预览模式</div>` : ""}

        ${ck === "work" && workPost ? `
          <article class="forum-thread-article hrp-work-thread">
            <div class="hrp-work-heading"><span class="forum-format-badge is-visual">作品分享</span><span>${esc(r.authorName || '创作者')}</span></div>
            <h1 class="hw-detail-title">${esc(name)}</h1>
            ${window.HandrawForumWork.render(workPost)}
            ${unlockBlock}
            <div class="hrp-social">${collectBtn}${likeBtn}${shareBtn}${reportBtn}</div>
            ${ownerEdit(ck,r,curation)}
            <div data-hrp-report-panel></div>
          </article>
        ` : `
        <div class="hrp-detail-grid">
          <div class="hrp-detail-main">
            <div class="hrp-hero">
              <div class="hrp-hero-main" id="hrp-hero-stage">${mediaHtml(mainImg, name, "hrp-hero-img")}</div>
              ${thumbs}
            </div>
          </div>
          <aside class="hrp-detail-side" aria-label="资源信息与操作">
            <h1 class="hrp-title">${esc(ck === "style" || ck === "layout" ? resourceLabel(ck, r) : name)}</h1>
            ${ck === "style" || ck === "layout" ? `<div class="hrp-code">#${esc(collectId(ck, r.id))}</div>` : ""}
            <div class="hrp-side-meta">
              ${r.authorName ? `<div class="hrp-meta-row"><span class="hrp-meta-k">作者</span><span class="hrp-meta-v">${r.author ? `<a href="${esc(channelUrl('main',{view:'profile',user:r.author}))}">${esc(r.authorName)}</a>` : esc(r.authorName)}</span></div>` : ""}
              ${r.sourceType ? `<div class="hrp-meta-row"><span class="hrp-meta-k">来源</span><span class="hrp-meta-v">${esc(sourceLabel(r.sourceType))}</span></div>` : ""}
              ${r.status ? `<div class="hrp-meta-row"><span class="hrp-meta-k">状态</span><span class="hrp-meta-v">${esc(statusLabel(r.status))}</span></div>` : ""}
              ${r.ratio ? `<div class="hrp-meta-row"><span class="hrp-meta-k">比例</span><span class="hrp-meta-v">${esc(r.ratio)}</span></div>` : ""}
              ${ck === 'work' ? `<div class="hrp-meta-row"><span class="hrp-meta-k">成图</span><span class="hrp-meta-v">${images.length} 张</span></div>` : ""}
            </div>
            <div class="hrp-actions">${useBtn}${unlockBlock}</div>
            <div class="hrp-social">${collectBtn}${likeBtn}${shareBtn}${reportBtn}</div>
            ${ownerEdit(ck, r, curation)}
            ${currentUser() && ['admin','operator','reviewer'].includes(currentUser().role) ? `<a class="hrp-edit-link" href="${esc(channelUrl('admin'))}">管理资源</a>` : ''}
          </aside>
        </div>

        ${descBlock}
        <div data-hrp-report-panel></div>
        ${defBlock}

        `}
        ${relBlock ? relBlock.html : ""}
        ${siblingBlock}
        ${threadSummary}

        <section class="hrp-section hrp-comments-section" id="hrp-comments">
          <h2 class="hrp-h2">讨论</h2>
          <div class="hrp-comments-list" id="hrp-comments-list" aria-live="polite"><div class="hrp-loading"><span class="hrp-spinner" aria-hidden="true"></span><span>正在加载评论…</span></div></div>
          ${composer}
        </section>

      </div>`;

    const draftKey = 'handraw.resourceReply:' + ck + ':' + r.id;
    const composerInput = root.querySelector('#hrp-composer-text');
    if (composerInput) {
      try { composerInput.value = sessionStorage.getItem(draftKey) || ''; } catch (_) {}
      composerInput.maxLength = 800;
      composerInput.oninput = () => { try { sessionStorage.setItem(draftKey, composerInput.value); } catch (_) {} };
    }
    bindDetail(root, r, ck, relations, reload);
    if (workPost) window.HandrawForumWork.bind(root,workPost);
    scan(root);

    loadComments(root, ck, r.id, 0, thread);
    if (new URLSearchParams(location.search).get("focus") === "comment") root.querySelector("#hrp-comments")?.scrollIntoView();
  }

  function useHref(ck, r) {
    const id = String(r.id || "");
    if (ck === "work") return studioWorkUrl(id);
    if (ck === "layout") return studioLayoutUrl(id);
    return studioStyleUrl(id);
  }

  function sourceLabel(t) {
    const k = String(t || "").toLowerCase();
    return SOURCE_LABEL[k] || "";
  }
  function statusLabel(t) {
    const k = String(t || "").toLowerCase();
    return STATUS_LABEL[k] || "";
  }
  function categoryLabel(c) {
    const k = String(c || "").trim();
    if (!k) return "讨论";
    try {
      if (S.forumCategoryLabel && typeof S.forumCategoryLabel === "function") {
        const v = S.forumCategoryLabel(k);
        if (v) return String(v);
      }
    } catch (_e) {}
    return ({assets:"画风与图型",tuning:"作品求改进",experience:"创作经验",tools:"工具流与问答"})[k] || "讨论";
  }

  function ownerEdit(ck, r, curation) {
    const u = currentUser();
    if (!u) return "";
    const me = String(u.username || "").toLowerCase();
    const author = String(r.author || r.authorName || "").toLowerCase();
    if (!me || me !== author) return "";
    if (!curation?.id) return ck === 'work' ? `<a class="hrp-edit-link" href="${esc(channelUrl('main',{view:'edit-work',id:r.id}))}">编辑作品</a>` : '';
    if (String(curation.status) === "pending") return "";
    const href = channelUrl("forum", {
      view: "curation",
      tab: "share",
      kind: ck === "layout" ? "layout" : ck === "work" ? "work" : "style",
      editId: curation.id,
    });
    return `<a class="hrp-edit-link" href="${esc(href)}">编辑资源资料</a>`;
  }

  /* ---- relations block (detail preview) ---- */

  function renderRelations(ck, relations, rid, preferredTab) {
    const allowed = REL_TABS[ck] || [];
    const present = relations.filter((x) => x && Number(x.total) > 0 && allowed.indexOf(x.tab) >= 0);
    if (!present.length) return null;
    let active = preferredTab;
    if (!present.some((x) => x.tab === active)) {
      active = (present.find((x) => Number(x.total) > 0) || present[0]).tab;
    }
    const tabsHtml = present.map((x) =>
      `<button type="button" class="hrp-tab${x.tab === active ? " is-active" : ""}" role="tab" aria-selected="${x.tab === active}" data-hrp-reltab="${esc(x.tab)}">${esc(x.label || TAB_LABEL[x.tab] || x.tab)} <span class="hrp-tab-count">${Number(x.total) || 0}</span></button>`
    ).join("");
    const html = `
      <section class="hrp-section hrp-rel" data-hrp-rel data-hrp-kind="${esc(ck)}">
        <div class="hrp-rel-head">
          <div class="hrp-tabs" role="tablist">${tabsHtml}</div>
          <a class="hrp-viewall" data-hrp-relviewall href="${esc(relatedUrl(ck, rid, active))}">查看全部 →</a>
        </div>
        <div class="hrp-rel-grid" data-hrp-relgrid></div>
      </section>`;
    return { html: html, tab: active };
  }

  function bindDetail(root, r, ck, relations, reload) {
    const copy = root.querySelector('[data-hrp-copy]');
    if (copy) copy.onclick = () => navigator.clipboard.writeText(r.definition || r.prompt || '').then(() => toast('已复制'),() => toast('复制失败，请手动选择文本复制'));
    // gallery thumbs
    root.querySelectorAll("[data-hrp-thumb]").forEach((b) => {
      b.onclick = () => {
        const images = [];
        if (Array.isArray(r.images)) r.images.forEach((x) => { const u = safeUrl(x); if (u) images.push(u); });
        if (safeUrl(r.image) && images.indexOf(safeUrl(r.image)) < 0) images.unshift(safeUrl(r.image));
        const idx = parseInt(b.getAttribute("data-hrp-thumb"), 10);
        const stage = root.querySelector("#hrp-hero-stage");
        if (stage && images[idx]) { stage.innerHTML = mediaHtml(images[idx], resName(r), "hrp-hero-img"); scan(stage); }
      };
    });

    // use (studio deep link is a plain anchor; no handler needed)

    // unlock
    const unlock = root.querySelector("[data-hrp-unlock]");
    if (unlock) {
      unlock.onclick = () => withLogin(() => {
        unlock.disabled = true;
        S.apiJson("/api/unlocks", { method: "POST", body: { targetId: r.id } })
          .then(() => (S.refreshFromServer ? S.refreshFromServer() : Promise.resolve()))
          .then(() => { toast("✨ 解锁成功"); reload(); })
          .catch((err) => { toast("解锁失败：" + ((err && err.message) || "未知错误")); unlock.disabled = false; });
      }, "登录后即可解锁资源");
    }

    // collect
    const collect = root.querySelector("[data-hrp-collect]");
    if (collect) {
      collect.disabled = r.status !== 'published';
      collect.onclick = () => withLogin(async () => {
        collect.disabled = true;
        try {
          const response = await S.apiJson('/api/collections/toggle',{method:'POST',body:{bucket:collectBucket(ck),id:collectId(ck,r.id),title:resName(r)}});
          toast(response.collected ? '已收藏' : '已取消收藏');
          await S.refreshFromServer();
        } catch (e) { toast('收藏失败：' + e.message); collect.disabled = false; }
      },'登录后即可收藏资源');
    }

    // like
    const like = root.querySelector("[data-hrp-like]");
    if (like) {
      like.disabled = r.status !== 'published';
      like.onclick = () => withLogin(async () => {
        like.disabled = true;
        try {
          const response = await S.apiJson('/api/interactions/like',{method:'POST',body:{targetType:likeType(ck),id:r.id}});
          toast(response.liked ? '已点赞' : '已取消点赞');
          await S.refreshFromServer();
        } catch (e) { toast('点赞失败：' + e.message); like.disabled = false; }
      },'登录后即可点赞');
    }

    // share
    const share = root.querySelector("[data-hrp-share]");
    if (share) share.onclick = () => copyShare(resName(r), window.location.href);

    // report
    const report = root.querySelector("[data-hrp-report]");
    if (report && typeof S.openReportModal === "function") {
      report.onclick = () => withLogin(() => {
        const panel=root.querySelector('[data-hrp-report-panel]');
        const type=r.reportTopicId ? 'topic' : ck==='work' ? 'work' : 'asset';
        const id=r.reportTopicId || r.id;
        panel.innerHTML=S.renderInlineReportPanelHtml(type,id,resName(r));
        S.bindInlineReportPanel(panel,type,id,()=>{ panel.innerHTML=''; });
        panel.scrollIntoView({block:'center'});
      },'登录后即可举报');
      if (new URLSearchParams(location.search).get('panel')==='report') report.click();
    }

    // relations tabs
    const relRoot = root.querySelector("[data-hrp-rel]");
    if (relRoot) {
      const byTab = {};
      relations.forEach((x) => { if (x && x.items) byTab[x.tab] = x; });
      const gridEl = relRoot.querySelector("[data-hrp-relgrid]");
      const viewAll = relRoot.querySelector("[data-hrp-relviewall]");
      const tabEls = relRoot.querySelectorAll("[data-hrp-reltab]");
      const showTab = (tab) => {
        const rel = byTab[tab];
        const items = (rel && rel.items) || [];
        if (gridEl) {
          gridEl.innerHTML = items.length ? renderCardGrid(items.slice(0, PREVIEW)) : `<div class="hrp-empty-inline">暂无内容</div>`;
          scan(gridEl);
        }
        if (viewAll) viewAll.href = relatedUrl(ck, r.id, tab);
        tabEls.forEach((t) => {
          const on = t.getAttribute("data-hrp-reltab") === tab;
          t.classList.toggle("is-active", on);
          t.setAttribute("aria-selected", on ? "true" : "false");
        });
      };
      tabEls.forEach((t) => { t.onclick = () => showTab(t.getAttribute("data-hrp-reltab")); });
      const initial = (relRoot.querySelector(".hrp-tab.is-active") || tabEls[0]);
      if (initial) showTab(initial.getAttribute("data-hrp-reltab"));
    }

    // comment send
    const send = root.querySelector("[data-hrp-send]");
    if (send) {
      send.onclick = () => withLogin(() => submitComment(root, ck, r.id, reload), "登录后即可发表评论");
    }
  }

  /* ---- comments ---- */

  function loadComments(root, ck, id, offset, thread) {
    const listEl = root.querySelector("#hrp-comments-list");
    if (!listEl) return;
    const cur = _epoch;
    const acct = accountKey();
    const qs = `offset=${offset}&limit=${COMMENT_PAGE}`;
    apiGet(`/api/forum/resources/${encodeURIComponent(ck)}/${encodeURIComponent(id)}/comments?${qs}`)
      .then((res) => {
        if (cur !== _epoch || acct !== accountKey()) return;
        bindComments(root, res, ck, id, offset, listEl, thread);
      })
      .catch((err) => {
        if (cur !== _epoch) return;
        // Preserve existing items on retry error.
        if (offset === 0) {
          listEl.innerHTML = `<div class="hrp-error-inline" role="alert">评论加载失败：${esc((err && err.message) || "")} <button type="button" class="btn btn-sm" data-hrp-retry-comments>重试</button></div>`;
          const rb = listEl.querySelector("[data-hrp-retry-comments]");
          if (rb) rb.onclick = () => { listEl.innerHTML = `<div class="hrp-loading">正在重试…</div>`; loadComments(root, ck, id, 0, thread); };
        } else {
          const more = listEl.querySelector("[data-hrp-more-comments]");
          if (more) { more.disabled = false; more.textContent = "加载更多评论（点此重试）"; }
          toast("加载更多评论失败，请重试");
        }
      });
  }

  function bindComments(root, res, ck, id, offset, listEl, thread) {
    const items = Array.isArray(res && res.items) ? res.items : [];
    const total = Number((res && res.total) || 0);

    if (offset === 0) {
      listEl.innerHTML = items.length
        ? items.map(renderComment).join("")
        : `<div class="hrp-empty-inline" role="status">${thread ? "还没有评论，来参与这场共用讨论。" : "还没有评论，来发表第一条讨论。"}</div>`;
    } else {
      const existing = listEl.querySelector("[data-hrp-more-comments]");
      if (existing) existing.remove();
      if (items.length) listEl.insertAdjacentHTML("beforeend", items.map(renderComment).join(""));
    }

    // Moderation binding AFTER HTML is inserted.
    listEl.querySelectorAll("[data-hrp-del]").forEach((b) => { b.onclick = () => moderate(root, b, "delete", ck, id, thread); });
    listEl.querySelectorAll("[data-hrp-hide]").forEach((b) => { b.onclick = () => moderate(root, b, "hide", ck, id, thread); });

    const loaded = offset + items.length;
    if (loaded < total) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "btn btn-sm hrp-more";
      more.setAttribute("data-hrp-more-comments", "");
      more.textContent = "加载更多评论";
      more.onclick = () => { more.disabled = true; loadComments(root, ck, id, loaded, thread); };
      listEl.appendChild(more);
    }
    scan(listEl);
  }

  function renderComment(c) {
    const name = c.name || c.user || "匿名";
    const typeLabel = COMMENT_TYPE_LABEL[c.type] || "";
    const mod = (c.canDelete || c.canHide)
      ? `<div class="hrp-comment-mod">
          ${c.canHide ? `<button type="button" class="btn btn-sm" data-hrp-hide="${esc(c.id)}" data-hrp-ctype="${esc(c.type)}">隐藏</button>` : ""}
          ${c.canDelete ? `<button type="button" class="btn btn-sm" data-hrp-del="${esc(c.id)}" data-hrp-ctype="${esc(c.type)}">删除</button>` : ""}
        </div>` : "";
    return `
      <article class="hrp-comment">
        <div class="hrp-comment-head">
          <span class="hrp-comment-name">${esc(name)}</span>
          <span class="hrp-comment-sub">${typeLabel ? `<span class="hrp-comment-type">${esc(typeLabel)}</span>` : ""}<span class="hrp-comment-time">${esc(c.time || "")}</span></span>
        </div>
        <p class="hrp-comment-text">${esc(stripHtml(c.text || ""))}</p>
        ${mod}
      </article>`;
  }

  function moderate(root, btn, action, ck, id, thread) {
    const ctype = btn.getAttribute("data-hrp-ctype");
    const cid = btn.getAttribute(action === "delete" ? "data-hrp-del" : "data-hrp-hide");
    btn.disabled = true;
    S.apiJson("/api/comments/moderate", { method: "POST", body: { commentType: ctype, id: cid, action: action } })
      .then(() => {
        toast(action === "delete" ? "已删除该评论" : "已隐藏该评论");
        const listEl = root.querySelector("#hrp-comments-list");
        if (listEl) { listEl.innerHTML = `<div class="hrp-loading">正在刷新评论…</div>`; loadComments(root, ck, id, 0, thread); }
        if (S.refreshFromServer) S.refreshFromServer().catch(() => {});
      })
      .catch((err) => { toast("操作失败：" + ((err && err.message) || "")); btn.disabled = false; });
  }

  function submitComment(root, ck, id, reload) {
    const ta = root.querySelector("#hrp-composer-text");
    if (!ta) return;
    const text = String(ta.value || "").trim();
    if (!text) { toast("请先输入评论内容"); return; }
    const btn = root.querySelector("[data-hrp-send]");
    if (btn) btn.disabled = true;
    S.apiJson(`/api/forum/resources/${encodeURIComponent(ck)}/${encodeURIComponent(id)}/comments`, { method: "POST", body: { text: text } })
      .then(() => {
        ta.value = "";
        try { sessionStorage.removeItem('handraw.resourceReply:' + ck + ':' + id); } catch (_) {}
        toast("💬 评论已发表");
        const listEl = root.querySelector("#hrp-comments-list");
        if (listEl) {
          listEl.innerHTML = `<div class="hrp-loading">正在刷新评论…</div>`;
          loadComments(root, ck, id, 0, null);
        }
        if (S.refreshFromServer) S.refreshFromServer().catch(() => {});
      })
      .catch((err) => toast("发表失败：" + ((err && err.message) || "")))
      .then(() => { if (btn) btn.disabled = false; });
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
