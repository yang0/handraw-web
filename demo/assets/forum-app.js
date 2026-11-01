/* Custom Deeply-Integrated Forum App (forum.handraw-style.com / localhost:3082)
 * 100% Standalone Page Architecture — Zero Content/Profile/Moderator/Auth Modals:
 * - ?view=list        : Forum Mixed Stream (Multi-Image Gallery + Single-Image Split + Clean Text)
 * - ?view=topic&id=.. : Standalone Forum Post Detail & Floor Replies Page
 * - ?view=compose     : Standalone Full-Page Forum Post Composer (strictly Forum Posts with multi-image + text)
 * - ?view=moderators  : Standalone Board Moderator Appointment & Governance Page (Super-Admin)
 * - ?view=auth        : Standalone Unified Auth Pass Page (preserves in-memory compose/reply drafts)
 */
(function () {
  const S = window.HANDRAW_SHARED;
  const { App, esc, toast, channelUrl } = S;

  // Resource pages, curation panel and work-post rendering live in optional
  // modules.  They are loaded on the full site but may be absent in a partial
  // build, so every call site degrades to a plain-thread fallback instead of
  // throwing — a hard reference here broke every topic page.
  function optionalModule(name) {
    const mod = window[name];
    return mod && typeof mod === "object" ? mod : null;
  }
  function hasModule(name, method) {
    const mod = optionalModule(name);
    return !!(mod && typeof mod[method] === "function");
  }

  const BOARD_DEFS = [
    { key: "tuning", label: "🎯 作品求改进 / 悬赏", short: "求调优" },
    { key: "experience", label: "📘 创作经验", short: "创作经验" },
    { key: "assets", label: "🎨 画风与图型专区", short: "画风图型" },
    { key: "tools", label: "🛠️ 工具流与问答", short: "工具问答" }
  ];

  function buildIntextMediaHtml(url, tag = "") {
    return `
      <figure class="hw-intext-media" contenteditable="false" draggable="true" data-media-url="${esc(url)}" title="按住可拖拽调整段落位置">
        <div class="hw-intext-media-wrap">
          <img src="${esc(url)}" alt="${esc(tag || '实测配图')}" loading="lazy" />
          <button type="button" class="hw-intext-del-btn" title="删除配图">✕</button>
        </div>
        <figcaption contenteditable="true" placeholder="点击添加配图说明或对比说明…">${esc(tag || "")}</figcaption>
      </figure>
      <p><br></p>
    `;
  }

  function buildIntextCardHtml(card) {
    const isWork = card.kind === "work";
    const isLayout = card.kind === "layout";
    const badgeLabel = isWork ? "🖼️ 附带实测作品" : isLayout ? "📐 附带图型" : "🎨 附带画风";
    const badgeClass = isWork ? "badge-work" : isLayout ? "badge-layout" : "badge-style";
    return `
      <div class="hw-intext-card" contenteditable="false" draggable="true"
           data-card-kind="${esc(card.kind)}"
           data-card-id="${esc(card.id)}"
           data-card-title="${esc(card.title)}"
           data-card-image="${esc(card.image)}"
           data-card-author="${esc(card.authorName || '')}"
           data-card-desc="${esc(card.desc || '')}"
           title="按住可拖拽调整段落位置">
        <div class="hw-intext-card-inner">
          <img src="${esc(card.image)}" alt="${esc(card.title)}" class="hw-intext-card-thumb" />
          <div class="hw-intext-card-meta">
            <div class="hw-intext-card-badge ${badgeClass}">${badgeLabel}${card.authorName ? ` · @${esc(card.authorName)}` : ""}</div>
            <div class="hw-intext-card-title">${esc(card.title)}</div>
            <div class="hw-intext-card-desc">${esc(card.desc || "")}</div>
          </div>
          <button type="button" class="hw-intext-del-btn" title="移除卡片">✕</button>
        </div>
      </div>
      <p><br></p>
    `;
  }

  function buildPaywallDividerHtml() {
    return `
      <div class="hw-paywall-divider" contenteditable="false" draggable="true" title="按住可拖拽调整付费截断位置">
        <div class="hw-paywall-divider-line"></div>
        <div class="hw-paywall-divider-pill">
          <span class="hw-paywall-pill-icon">🔒</span>
          <span class="hw-paywall-pill-text">此处以下为 10✦ 专属核心交付章节</span>
          <button type="button" class="hw-intext-del-btn" title="移除付费截断线">✕</button>
        </div>
        <div class="hw-paywall-divider-line"></div>
      </div>
      <p><br></p>
    `;
  }

  function createEmptyDraft(overrides = {}) {
    const cat = overrides.category && BOARD_DEFS.some((b) => b.key === overrides.category)
      ? overrides.category
      : "experience";
    let bodyHtml = String(overrides.bodyHtml || overrides.body || "");
    const sharedCard = overrides.sharedCard || null;

    if (sharedCard && !bodyHtml.includes("hw-intext-card")) {
      const cardBlock = buildIntextCardHtml(sharedCard);
      const prefix = `<p>分享一件我很喜欢的高品质${sharedCard.kind === "work" ? "实测作品" : sharedCard.kind === "layout" ? "图型" : "画风"}：</p>`;
      bodyHtml = prefix + cardBlock + (bodyHtml ? `<p>${esc(bodyHtml)}</p>` : `<p><br></p>`);
    }

    if (Array.isArray(overrides.images) && overrides.images.length > 0 && !bodyHtml.includes("hw-intext-media")) {
      for (const im of overrides.images) {
        const u = typeof im === "string" ? im : im.url;
        const tg = typeof im === "string" ? "" : im.tag || "";
        if (u) {
          bodyHtml += buildIntextMediaHtml(u, tg);
        }
      }
    }

    return {
      category: cat,
      title: String(overrides.title || ""),
      body: String(overrides.body || ""),
      bodyHtml: bodyHtml,
      images: Array.isArray(overrides.images)
        ? overrides.images
            .map((im, idx) =>
              typeof im === "string"
                ? { url: im, tag: `实测图 P${idx + 1}` }
                : { url: String(im.url || ""), tag: String(im.tag || `实测图 P${idx + 1}`) }
            )
            .filter((x) => x.url)
        : [],
      sharedCard: sharedCard,
      style1: String(overrides.style1 || overrides.style || "").trim().toUpperCase().replace(/^#/, ""),
      layout: String(overrides.layout || "").trim().toUpperCase().replace(/^#/, ""),
      publishMode: overrides.publishMode || "free", // 'free' | 'bounty_10' | 'bounty_20' | 'paid_10'
      lockedBody: String(overrides.lockedBody || ""),
      submitting: false
    };
  }

  const FUI = {
    view: "list", // 'list' | 'compose' | 'topic' | 'moderators' | 'auth'
    category: "all", // 'all' | 'tuning' | 'experience' | 'assets' | 'tools'
    format: "all", // 'all' | 'visual' | 'text'
    sort: "hot", // 'hot' | 'newest' | 'featured' | 'bounty' | 'paid'
    query: "",
    filterAsset: "",
    composeDraft: createEmptyDraft(),
    activeTopicId: "",
    activeTopicImgIdx: 0,
    topicInlineDrawer: "", // '' | 'share' | 'report'
    notFoundCode: "",
    topicCountedViews: new Set(),
    modInitialBoard: "assets",
    modListData: null,
    modLoading: false,
    authReason: "",
    authOnSuccess: null,
    authReturnView: "list",
    navHistoryDepth: 0
  };

  let draftAccount = null;
  let draftSaveTimer = null;
  const draftKey = () => `handraw_forum_draft_v2:${S.App.state?.user?.id || "guest"}`;
  function saveComposeDraft() {
    try {
      const { submitting, ...draft } = FUI.composeDraft;
      localStorage.setItem(draftKey(), JSON.stringify({ ...draft, savedAt: Date.now() }));
      const hint=document.querySelector("#compose-draft-status");if(hint)hint.textContent="草稿已保存到此浏览器";
    } catch (_) {
      const hint=document.querySelector("#compose-draft-status");if(hint)hint.textContent="草稿未能保存，请先复制正文备份";
    }
  }
  function restoreComposeDraft() {
    const account=S.App.state?.user?.id || "guest";
    if(draftAccount===account)return;
    if(draftAccount!==null)FUI.composeDraft=createEmptyDraft();
    draftAccount=account;
    try{
      const saved=JSON.parse(localStorage.getItem(draftKey())||"null");
      if(saved && !FUI.composeDraft.title && !FUI.composeDraft.bodyHtml){
        saved.bodyHtml=window.HandrawAccountTools.safeHtml(saved.bodyHtml);
        FUI.composeDraft=createEmptyDraft(saved);
      }
    }catch(_){ /* An invalid local draft must not prevent opening the forum. */ }
  }
  function hasUnpublishedDraft() {
    return Boolean(FUI.composeDraft.title.trim() || stripHtmlToSnippet(FUI.composeDraft.bodyHtml,200).trim());
  }
  for(const eventName of ["input","change"]){
    document.addEventListener(eventName,event=>{
      if(!event.target.closest("#forum-compose-page"))return;
      clearTimeout(draftSaveTimer);
      const account=draftAccount;
      draftSaveTimer=setTimeout(()=>{if(account===draftAccount)syncDraftInputsFromDom(document.querySelector("#forum-app-root"));},250);
    });
  }
  window.addEventListener("beforeunload",event=>{
    if(FUI.view!=="compose" || !hasUnpublishedDraft() || FUI.composeDraft.submitting)return;
    syncDraftInputsFromDom(document.querySelector("#forum-app-root"));event.preventDefault();event.returnValue="";
  });

  function parseInitialForumUrl() {
    const tPathMatch = window.location.pathname.match(/^\/t\/(.+)$/);
    if (tPathMatch) {
      FUI.view = "not_found";
      FUI.notFoundCode = decodeURIComponent(tPathMatch[1]).trim();
      return;
    }

    const p = new URLSearchParams(window.location.search);
    const view = p.get("view") || "";
    const legacyTopic = (p.get("topic") || "").trim();

    if (p.get("asset")) FUI.filterAsset = p.get("asset").toUpperCase();
    if (p.get("category") && ["all", "tuning", "experience", "assets", "tools"].includes(p.get("category"))) {
      FUI.category = p.get("category");
    }
    if (p.get("format") && ["all", "visual", "text"].includes(p.get("format"))) {
      FUI.format = p.get("format");
    }

    if (["resource", "related"].includes(view)) { FUI.view=view; return; }
    if (view === "curation") { FUI.view="curation"; return; }

    if (view === "topic" || legacyTopic) {
      const tid = (p.get("id") || legacyTopic || "").trim();
      if (tid) {
        FUI.view = "topic";
        FUI.activeTopicId = tid;
        FUI.activeTopicImgIdx = 0;
        FUI.topicInlineDrawer = p.get("panel") === "report" ? "report" : "";
        return;
      }
    }

    if (view === "moderators") {
      FUI.view = "moderators";
      const b = p.get("board") || "assets";
      FUI.modInitialBoard = ["assets", "tuning", "experience", "tools", "all"].includes(b) ? b : "assets";
      return;
    }

    if (view === "auth") {
      FUI.view = "auth";
      return;
    }

    if (view === "compose") {
      let parsedImgs = [];
      const rawImgs = p.get("imgs");
      if (rawImgs) {
        try {
          const arr = JSON.parse(rawImgs);
          if (Array.isArray(arr)) parsedImgs = arr;
        } catch (_) {}
      }
      let sharedCard = null;
      if (p.get("card")) {
        try {
          sharedCard = JSON.parse(p.get("card"));
        } catch (_) {}
      }
      if (!sharedCard) {
        const wId = (p.get("work") || "").trim();
        const sId = (p.get("style") || "").trim().toUpperCase().replace(/^#/, "");
        const lId = (p.get("layout") || "").trim().toUpperCase().replace(/^#/, "");
        if (wId) {
          const w = (App.state?.works || []).find((x) => x.id === wId);
          if (w) {
            sharedCard = {
              kind: "work",
              id: w.id,
              title: w.title,
              image: (w.images && w.images[0]) || "",
              authorName: w.authorName || w.author || "",
              desc: w.notes || w.prompt || ""
            };
          }
        } else if (sId) {
          const st = App.resourceMap.get(sId);
          if (st) {
            sharedCard = {
              kind: "style",
              id: st.id,
              title: st.name,
              image: st.image,
              authorName: st.authorName || "Handraw 官方",
              desc: st.description || ""
            };
          }
        } else if (lId) {
          const lt = App.resourceMap.get(lId);
          if (lt) {
            sharedCard = {
              kind: "layout",
              id: lt.id,
              title: lt.name,
              image: lt.image,
              authorName: lt.authorName || "Handraw 官方",
              desc: lt.description || ""
            };
          }
        }
      }
      const cat = p.get("category");
      FUI.view = "compose";
      FUI.composeDraft = createEmptyDraft({
        category: cat && cat !== "all" ? cat : sharedCard?.kind === "work" ? "tuning" : sharedCard ? "assets" : "experience",
        sharedCard,
        style1: sharedCard?.kind === "style" ? sharedCard.id : p.get("style") || "",
        layout: sharedCard?.kind === "layout" ? sharedCard.id : p.get("layout") || "",
        title: p.get("title") || "",
        body: p.get("body") || "",
        images: parsedImgs
      });
      return;
    }

    FUI.view = "list";
  }

  function updateForumTitle() {
    if (FUI.view === "topic" && FUI.activeTopicId) {
      const t = (App.state?.topics || []).find((x) => x.id === FUI.activeTopicId);
      if (t) {
        document.title = `${t.title} (@${t.authorName}) — Handraw 创作者论坛`;
        return;
      }
    }
    if (FUI.view === "compose") {
      document.title = "发布论坛交流帖（支持多图图文与配方挂载）— Handraw 创作者论坛";
      return;
    }
    if (FUI.view === "moderators") {
      document.title = "论坛板块版主设置与治理 — Handraw 创作者论坛";
      return;
    }
    if (FUI.view === "auth") {
      document.title = "登录 / 注册统一通行证 — Handraw 创作者论坛";
      return;
    }
    document.title = "社区实战论坛 — Handraw 手绘风社区";
  }

  function syncForumUrl(pushHistory = false) {
    if (["curation", "resource", "related"].includes(FUI.view)) return;
    const u = new URL(window.location.href);
    u.search = "";
    if (FUI.view === "topic" && FUI.activeTopicId) {
      u.searchParams.set("view", "topic");
      u.searchParams.set("id", FUI.activeTopicId);
      if (FUI.topicInlineDrawer === "report") u.searchParams.set("panel", "report");
    } else if (FUI.view === "compose") {
      u.searchParams.set("view", "compose");
      u.searchParams.set("category", FUI.composeDraft.category);
      if (FUI.composeDraft.style1) u.searchParams.set("style", FUI.composeDraft.style1);
      if (FUI.composeDraft.layout) u.searchParams.set("layout", FUI.composeDraft.layout);
    } else if (FUI.view === "moderators") {
      u.searchParams.set("view", "moderators");
      if (FUI.modInitialBoard) u.searchParams.set("board", FUI.modInitialBoard);
    } else if (FUI.view === "auth") {
      u.searchParams.set("view", "auth");
    } else {
      if (FUI.category !== "all") u.searchParams.set("category", FUI.category);
      if (FUI.filterAsset) u.searchParams.set("asset", FUI.filterAsset);
    }

    const nextHref = u.toString();
    if (pushHistory && window.location.href !== nextHref) {
      FUI.navHistoryDepth += 1;
      window.history.pushState({ view: FUI.view }, "", nextHref);
    } else {
      window.history.replaceState({ view: FUI.view }, "", nextHref);
    }
    updateForumTitle();
  }

  function openForumList(pushHistory = true) {
    S.closeModal();
    const changed = FUI.view !== "list";
    FUI.view = "list";
    syncForumUrl(pushHistory && changed);
    window.scrollTo({ top: 0, behavior: "smooth" });
    renderForum();
  }

  function openTopicPage(topicId, activeImgIdx = 0) {
    S.closeModal();
    const tid = String(topicId || "").trim();
    if (!tid) return;
    const isEntering = FUI.view !== "topic" || FUI.activeTopicId !== tid;
    const topic = (App.state?.topics || []).find((t) => t.id === tid);
    // View counts are frozen by design (see backend/ranking.py): they have no
    // trusted write path and a client-side increment would be a fake number.
    FUI.view = "topic";
    FUI.activeTopicId = tid;
    FUI.activeTopicImgIdx = Number(activeImgIdx) || 0;
    if (isEntering && FUI.topicInlineDrawer !== "report") FUI.topicInlineDrawer = "";
    syncForumUrl(isEntering);
    if (isEntering) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    renderForum();
  }

  function openComposeView(prefill = {}, pushHistory = true) {
    S.closeModal();
    const defaultCat =
      prefill.category && prefill.category !== "all"
        ? prefill.category
        : FUI.category !== "all"
        ? FUI.category
        : prefill.sharedCard?.kind === "work"
        ? "tuning"
        : prefill.sharedCard || prefill.style1 || prefill.layout
        ? "assets"
        : "experience";
    const changed = FUI.view !== "compose";
    FUI.view = "compose";
    FUI.composeDraft = createEmptyDraft({
      ...prefill,
      category: defaultCat
    });
    syncForumUrl(pushHistory && changed);
    window.scrollTo({ top: 0, behavior: "smooth" });
    renderForum();
  }

  function exitComposeView(pushHistory = true) {
    openForumList(pushHistory);
  }

  async function openModeratorsPage(initialBoard = "all") {
    S.closeModal();
    if (!App.state.loggedIn || App.state.user?.role !== "admin") {
      toast("仅超级管理员可任命或撤销板块版主");
      return;
    }
    const defaultBoard = initialBoard && initialBoard !== "all" ? initialBoard : "assets";
    const isEntering = FUI.view !== "moderators";
    FUI.view = "moderators";
    FUI.modInitialBoard = defaultBoard;
    FUI.modLoading = true;
    syncForumUrl(isEntering);
    if (isEntering) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    renderForum();

    let data = { moderators: S.getBoardModerators("all"), boards: {} };
    if (App.state.serverBacked) {
      try {
        data = await S.apiJson("/api/admin/forum-moderators");
      } catch (err) {
        toast(`读取版主列表失败：${err.message}`);
      }
    }
    FUI.modListData = data;
    FUI.modLoading = false;
    if (FUI.view === "moderators") {
      renderForum();
    }
  }

  function openForumAuthPage(reasonText = "", onSuccess = null) {
    S.closeModal();
    if (FUI.view !== "auth") {
      FUI.authReturnView = FUI.view;
    }
    FUI.authReason = reasonText || "";
    FUI.authOnSuccess = onSuccess || null;
    FUI.view = "auth";
    syncForumUrl(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
    renderForum();
  }

  function restoreAfterForumAuth(runSuccessCallback = false) {
    const targetView = FUI.authReturnView && FUI.authReturnView !== "auth" ? FUI.authReturnView : "list";
    const cb = FUI.authOnSuccess;
    FUI.authReason = "";
    FUI.authOnSuccess = null;
    FUI.view = targetView;
    syncForumUrl(false);
    renderForum();
    if (runSuccessCallback && typeof cb === "function") {
      cb();
    }
  }

  window.HANDRAW_FORUM_OPEN_COMPOSE = (prefill = {}) => openComposeView(prefill, true);
  window.HANDRAW_FORUM_OPEN_TOPIC = (tid, imgIdx = 0) => openTopicPage(tid, imgIdx);
  window.HANDRAW_FORUM_OPEN_AUTH = (reason, onSuccess) => openForumAuthPage(reason, onSuccess);

  window.addEventListener("popstate", () => {
    parseInitialForumUrl();
    updateForumTitle();
    renderForum();
  });

  function normalizeTopicImages(t) {
    return (t.images || []).map((im) =>
      typeof im === "string" ? { url: im, tag: "" } : { url: im.url, tag: im.tag || "" }
    );
  }

  function formatBodyHtml(text) {
    return esc(text || "")
      .replace(/^### (.+)$/gm, '<h4 style="margin:12px 0 6px;color:var(--vermilion);font-size:14.5px;">$1</h4>')
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, '<code style="background:var(--paper-inset);padding:1px 5px;border-radius:4px;">$1</code>')
      .replace(/\n/g, "<br/>");
  }

  function stripHtmlToSnippet(html, maxLen = 140) {
    if (!html) return "";
    if (!/[<>]/.test(html)) {
      const trimmed = String(html).replace(/\s+/g, " ").trim();
      return trimmed.length > maxLen ? trimmed.slice(0, maxLen) + "…" : trimmed;
    }
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    tmp.querySelectorAll(".hw-intext-del-btn, .btn, figcaption, .hw-honor-badge").forEach((el) => el.remove());
    const text = (tmp.textContent || tmp.innerText || "").replace(/\s+/g, " ").trim();
    return text.length > maxLen ? text.slice(0, maxLen) + "…" : text;
  }

  function buildSmartCardHtml(card) {
    const isWork = card.kind === "work";
    const isLayout = card.kind === "layout";
    const badgeLabel = isWork ? "🖼️ 附带实测作品卡片" : isLayout ? "📐 附带图型卡片" : "🎨 附带画风卡片";
    const badgeClass = isWork ? "honor-pioneer" : "honor-gold";
    const detailUrl = isWork
      ? channelUrl("main", { view: "work", id: card.id })
      : channelUrl("main", { view: "asset", id: card.id });
    const studioUrl = isWork
      ? channelUrl("studio", { fork: card.id })
      : channelUrl("studio", isLayout ? { layout: card.id } : { style: card.id });
    const studioActionLabel = isWork ? "⚡ 做同款 ↗" : "✨ 创作台使用 ↗";

    return `
      <div class="smart-embed-card" style="margin:10px 0;">
        <img src="${esc(card.image)}" alt="${esc(card.title)}" />
        <div style="flex:1;min-width:0;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap;">
            <span class="hw-honor-badge ${badgeClass}" style="font-size:11px;padding:2px 7px;">${badgeLabel}</span>
            ${card.authorName ? `<span style="font-size:12px;color:var(--ink-muted);">作者：<strong>@${esc(card.authorName)}</strong></span>` : ""}
          </div>
          <div style="font-weight:850;font-size:15px;color:var(--ink-strong);line-height:1.35;margin-bottom:3px;">${esc(card.title)}</div>
          <div style="font-size:12px;color:var(--ink-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(card.desc || "")}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;flex-shrink:0;">
          <a class="btn btn-sm btn-primary" style="font-size:12px;padding:4px 10px;" href="${esc(detailUrl)}">查看${isWork ? "作品" : isLayout ? "图型" : "画风"}详情 ↗</a>
          <a class="btn btn-sm" style="font-size:12px;padding:4px 10px;" href="${esc(studioUrl)}">${studioActionLabel}</a>
        </div>
      </div>
    `;
  }

  function openImageLightboxModal(src, caption = "") {
    S.openModal({
      title: "🖼️ 查看高清配图",
      html: `
        <div style="text-align:center;padding:10px 4px;">
          <img src="${esc(src)}" alt="${esc(caption)}" style="max-width:100%;max-height:76vh;object-fit:contain;border-radius:10px;box-shadow:var(--shadow-card);" />
          ${caption ? `<div style="font-size:13.5px;color:var(--ink-body);margin-top:12px;line-height:1.5;">${esc(caption)}</div>` : ""}
        </div>
      `
    });
  }

  function renderEditorialArticleHtml(topic, cardsToRender = [], unlocked = false) {
    const rawBody = (topic.price > 0 && unlocked && topic.lockedBody)
      ? topic.lockedBody
      : (topic.summary || topic.body || "");
    const imgs = normalizeTopicImages(topic);
    const hasInline = rawBody.includes("hw-intext-media") || rawBody.includes("hw-intext-card") || rawBody.includes("hw-paywall-divider") || rawBody.includes("<figure");

    if (hasInline) {
      const div = document.createElement("div");
      div.innerHTML = rawBody;
      div.querySelectorAll(".hw-intext-del-btn").forEach((btn) => btn.remove());

      // Transform any in-text card block to full interactive smart-embed-card
      div.querySelectorAll(".hw-intext-card").forEach((cardEl) => {
        const kind = cardEl.getAttribute("data-card-kind") || "style";
        const id = cardEl.getAttribute("data-card-id") || "";
        const title = cardEl.getAttribute("data-card-title") || "";
        const image = cardEl.getAttribute("data-card-image") || "";
        const authorName = cardEl.getAttribute("data-card-author") || "";
        const desc = cardEl.getAttribute("data-card-desc") || "";

        const cardObj = { kind, id, title, image, authorName, desc };
        const temp = document.createElement("div");
        temp.innerHTML = buildSmartCardHtml(cardObj);
        cardEl.replaceWith(temp.firstElementChild || temp);
      });

      // Handle paywall divider in detail view
      div.querySelectorAll(".hw-paywall-divider").forEach((pw) => {
        if (unlocked) {
          const pill = document.createElement("div");
          pill.style.cssText = "margin:26px 0 18px;display:flex;align-items:center;gap:10px;";
          pill.innerHTML = '<div style="flex:1;height:1px;background:var(--gold-border);"></div><span style="font-size:12px;font-weight:800;color:var(--gold);background:var(--gold-wash);padding:4px 14px;border-radius:999px;">🔓 已解锁 10✦ 专栏核心交付章节</span><div style="flex:1;height:1px;background:var(--gold-border);"></div>';
          pw.replaceWith(pill);
        } else {
          pw.remove();
        }
      });

      // Mark all images for zoom lightbox
      div.querySelectorAll("img").forEach((im) => {
        im.setAttribute("data-zoom-img", im.src);
      });

      return div.innerHTML;
    }

    // Legacy or plain text post
    let mediaFlowHtml = "";
    if (imgs.length === 1) {
      const im = imgs[0];
      mediaFlowHtml = `
        <figure class="hw-intext-media" style="margin:0 0 18px;">
          <div class="hw-intext-media-wrap">
            <img src="${esc(im.url)}" data-zoom-img="${esc(im.url)}" alt="${esc(im.tag || topic.title)}" />
          </div>
          ${im.tag ? `<figcaption>${esc(im.tag)}</figcaption>` : ""}
        </figure>
      `;
    } else if (imgs.length > 1) {
      mediaFlowHtml = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:0 0 20px;">
          ${imgs.map((im, idx) => `
            <div class="hw-intext-media-wrap" style="cursor:zoom-in;">
              <img src="${esc(im.url)}" data-zoom-img="${esc(im.url)}" alt="P${idx + 1}" style="height:190px;width:100%;object-fit:cover;" />
              ${im.tag ? `<div style="font-size:11.5px;color:var(--ink-muted);padding:4px 8px;text-align:center;">${esc(im.tag)}</div>` : ""}
            </div>
          `).join("")}
        </div>
      `;
    }

    const formattedText = formatBodyHtml(rawBody);
    const embeddedCards = cardsToRender.length > 0
      ? cardsToRender.map((c) => buildSmartCardHtml(c)).join("")
      : "";

    return mediaFlowHtml + formattedText + embeddedCards;
  }

  function renderReplyContentHtml(rawText) {
    const str = String(rawText || "");
    const lines = str.split("\n");
    let html = "";
    let quoteLines = [];

    function flushQuote() {
      if (quoteLines.length > 0) {
        html += `<blockquote class="forum-reply-quote">${quoteLines.map((l) => esc(l)).join("<br>")}</blockquote>`;
        quoteLines = [];
      }
    }

    for (const line of lines) {
      if (line.startsWith(">")) {
        quoteLines.push(line.replace(/^>\s?/, ""));
      } else {
        flushQuote();
        if (line.trim()) {
          html += `<p style="margin:0 0 6px;">${esc(line)}</p>`;
        } else {
          html += `<br>`;
        }
      }
    }
    flushQuote();
    return html || esc(str);
  }

  function renderModBadgeHtml(username, category = "") {
    const badges = S.getUserModeratorBadges ? S.getUserModeratorBadges(username, category) : [];
    if (!badges.length) return "";
    const top = badges[0];
    return `<span style="display:inline-flex;align-items:center;gap:2px;background:rgba(31,95,139,0.11);color:#1f5f8b;border:1px solid rgba(31,95,139,0.28);font-size:11px;font-weight:800;padding:1px 6px;border-radius:999px;vertical-align:middle;" title="${esc(top.boardLabel || "")} · ${esc(top.title || "版主")}">🛡️ ${esc(top.title || "版主")}</span>`;
  }

  /* ======================== 1. STANDALONE AUTH PAGE (?view=auth) ======================== */
  function renderForumAuthPage(root) {
    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-forum-auth-page" style="max-width:600px;margin:0 auto;">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="fauth-back-btn">← 返回论坛继续浏览</button>
            <span>/</span>
            <strong>🔑 登录 / 注册统一通行证</strong>
          </div>
        </div>
        <div class="hw-detail-section-card" style="padding:26px 28px;">
          <h1 style="margin:0 0 6px;font-size:22px;font-family:var(--font-serif);">登录 Handraw 创作者论坛</h1>
          <p style="margin:0 0 16px;font-size:13px;color:var(--ink-muted);">登录后即可发布图文交流帖、回复赢取互助与悬赏积分，并同步全站收藏夹。</p>
          <div id="forum-auth-mount"></div>
        </div>
      </div>
    `;

    root.querySelector("#fauth-back-btn").onclick = () => restoreAfterForumAuth(false);
    S.mountAuthPassStage(root.querySelector("#forum-auth-mount"), {
      reasonText: FUI.authReason,
      onCancel: () => restoreAfterForumAuth(false),
      onSuccess: () => restoreAfterForumAuth(true)
    });
  }

  /* ======================== 2. STANDALONE BOARD MODERATORS PAGE (?view=moderators) ======================== */
  function renderModeratorsPage(root) {
    if (!App.state.loggedIn || App.state.user?.role !== "admin") {
      openForumList(false);
      return;
    }
    const defaultBoard = FUI.modInitialBoard || "assets";
    const mods = (FUI.modListData && FUI.modListData.moderators) || S.getBoardModerators("all") || [];

    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-moderators-page" style="max-width:920px;margin:0 auto;">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="fmod-back-btn">← 返回论坛讨论列表</button>
            <span>/</span>
            <strong>🛡️ 论坛板块版主设置与权限治理</strong>
          </div>
          <a class="btn btn-sm" href="${esc(channelUrl("admin", { module: "governance", subtab: "moderators_list" }))}">🏛️ 进入后台治理中心 ↗</a>
        </div>

        <section class="hw-detail-section-card" style="display:grid;gap:16px;">
          <div>
            <p class="hw-editorial-eyebrow" style="margin:0 0 4px;">社区版务治理 · 板块自治权限配置</p>
            <h1 style="margin:0 0 6px;font-size:22px;font-family:var(--font-serif);">🛡️ 任命或调整论坛各板块版主</h1>
            <p style="margin:0;font-size:13px;color:var(--ink-muted);">
              版主可对所辖板块执行<strong>置顶、设精华、跨板块移帖、隐藏违规帖与回复</strong>，并自动开通独立的<strong>🏛️ 版主专属版务工作台</strong>。
            </p>
          </div>

          <div style="background:var(--paper-bg);border:1px solid var(--line-strong);border-radius:12px;padding:14px 16px;">
            <div style="font-size:13.5px;font-weight:850;margin-bottom:10px;">+ 任命新板块版主</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:center;">
              <input class="hw-input" id="fmod-username" placeholder="输入用户名 (如 su_editorial)" />
              <select class="hw-select" id="fmod-category">
                <option value="assets" ${defaultBoard === "assets" ? "selected" : ""}>🎨 画风与图型专区</option>
                <option value="tuning" ${defaultBoard === "tuning" ? "selected" : ""}>🎯 作品求改进 / 悬赏</option>
                <option value="experience" ${defaultBoard === "experience" ? "selected" : ""}>📘 创作经验</option>
                <option value="tools" ${defaultBoard === "tools" ? "selected" : ""}>🛠️ 工具流与问答</option>
                <option value="all" ${defaultBoard === "all" ? "selected" : ""}>🏛️ 全区总版主 (全部板块)</option>
              </select>
              <input class="hw-input" id="fmod-title" value="版主" placeholder="头衔 如 特邀版主" />
              <button type="button" class="btn btn-primary" id="fmod-add-btn" style="justify-content:center;">🛡️ 确认任命版主</button>
            </div>
          </div>

          <div>
            <div style="font-size:14px;font-weight:850;margin-bottom:10px;">当前在任版主名单 (${mods.length})</div>
            <div style="display:grid;gap:10px;">
              ${
                FUI.modLoading
                  ? `<div style="padding:24px;text-align:center;color:var(--ink-muted);">正在同步最新板块版主名单…</div>`
                  : mods.length === 0
                  ? `<div style="padding:24px;text-align:center;color:var(--ink-muted);background:var(--paper-bg);border-radius:10px;">暂无已任命的板块版主</div>`
                  : mods
                      .map(
                        (m) => `
                          <div style="background:#fff;border:1px solid var(--line-soft);border-radius:10px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
                            <div>
                              <div style="font-size:14px;font-weight:800;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                                <button type="button" class="hw-author-chip" data-open-creator="${esc(m.username)}" style="padding:2px 8px;">
                                  <strong>@${esc(m.displayName || m.username)}</strong>
                                </button>
                                <code style="font-size:11.5px;color:var(--ink-muted);">(${esc(m.username)})</code>
                                <span style="background:rgba(31,95,139,0.12);color:#1f5f8b;font-size:11.5px;font-weight:800;padding:2px 9px;border-radius:999px;">
                                  🛡️ ${esc(m.boardLabel || m.category)} · ${esc(m.title || "版主")}
                                </span>
                              </div>
                              ${m.note ? `<div style="font-size:12px;color:var(--ink-muted);margin-top:4px;">备注：${esc(m.note)}</div>` : ""}
                            </div>
                            <button type="button" class="btn btn-sm" data-revoke-user="${esc(m.username)}" data-revoke-cat="${esc(m.category)}" style="color:var(--vermilion);">
                              撤销版主权限
                            </button>
                          </div>
                        `
                      )
                      .join("")
              }
            </div>
          </div>
        </section>
      </div>
    `;

    root.querySelector("#fmod-back-btn").onclick = () => openForumList(true);
    root.querySelectorAll("[data-open-creator]").forEach((btn) => {
      if (!btn.getAttribute("data-open-creator")) { btn.outerHTML='<span class="curation-muted">资源讨论</span>'; return; }
      btn.onclick = () => S.goToCreatorProfile(btn.getAttribute("data-open-creator"));
    });

    root.querySelector("#fmod-add-btn").onclick = async () => {
      const username = root.querySelector("#fmod-username").value.trim();
      const category = root.querySelector("#fmod-category").value;
      const title = root.querySelector("#fmod-title").value.trim() || "版主";
      if (!username) {
        toast("请填写要任命为版主的用户名");
        return;
      }
      try {
        await S.apiJson("/api/admin/forum-moderators", {
          method: "POST",
          body: { username, category, title }
        });
        await S.refreshFromServer();
        toast(`🛡️ 已任命 @${username} 为版主！`);
        openModeratorsPage(category);
      } catch (err) {
        toast(`任命失败：${err.message}`);
      }
    };

    root.querySelectorAll("[data-revoke-user]").forEach((btn) => {
      btn.onclick = async () => {
        const username = btn.getAttribute("data-revoke-user");
        const category = btn.getAttribute("data-revoke-cat");
        try {
          await S.apiJson("/api/admin/forum-moderators/revoke", {
            method: "POST",
            body: { username, category }
          });
          await S.refreshFromServer();
          toast(`已撤销 @${username} 的版主权限`);
          openModeratorsPage(defaultBoard);
        } catch (err) {
          toast(`撤销失败：${err.message}`);
        }
      };
    });
  }

  /* ======================== 3. STANDALONE COMPOSE PAGE (?view=compose) ======================== */
  function syncDraftInputsFromDom(root) {
    if (!root) return;
    const titleEl = root.querySelector("#compose-title-input");
    const editorEl = root.querySelector("#compose-rich-editor");
    const modeEl = root.querySelector("#compose-mode-dropdown");
    if (titleEl) FUI.composeDraft.title = titleEl.value;
    if (editorEl) FUI.composeDraft.bodyHtml = editorEl.innerHTML;
    if (modeEl) FUI.composeDraft.publishMode = modeEl.value;
    saveComposeDraft();
  }

  function renderComposePage(root) {
    const d = FUI.composeDraft;

    root.innerHTML = `
      <div id="forum-compose-page" class="hw-compose-container">
        <!-- Top Navigation & Unified Action Bar -->
        <header class="hw-compose-header">
          <div class="hw-compose-header-left">
            <button type="button" class="btn btn-sm" id="compose-back-btn">← 返回论坛</button>
            <div class="hw-compose-board-pills" id="compose-board-pills">
              ${BOARD_DEFS.map(
                (b) => `
                  <button type="button" class="hw-compose-board-pill ${d.category === b.key ? "is-active" : ""}" data-compose-cat="${esc(b.key)}">
                    ${esc(b.label)}
                  </button>
                `
              ).join("")}
            </div>
          </div>
        </header>

        ${
          !App.state.loggedIn
            ? `
              <div style="background:var(--gold-wash);border:1px solid var(--gold-border);border-radius:12px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
                <div style="font-size:13px;color:var(--ink-body);">
                  🔑 <strong>当前为未登录访客状态</strong>：您可以先编辑图文草稿，发布前登录账号立赠 20✦ 积分。
                </div>
                <button type="button" class="btn btn-primary btn-sm" id="compose-login-btn">立即登录 / 注册</button>
              </div>
            `
            : ""
        }

        <!-- Single Editorial Writing Desk -->
        <main class="hw-compose-paper">
          <input
            type="text"
            id="compose-title-input"
            class="hw-compose-title"
            placeholder="输入帖子标题…"
            value="${esc(d.title)}"
            maxlength="120"
            autocomplete="off"
          />

          <!-- Rich Text Formatting & Insertion Toolbar -->
          <div class="hw-editor-toolbar" id="compose-editor-toolbar">
            <div class="hw-toolbar-group">
              <button type="button" class="hw-tool-btn" data-cmd="bold" title="加粗 (Ctrl+B)"><b>B</b></button>
              <button type="button" class="hw-tool-btn" data-cmd="italic" title="斜体 (Ctrl+I)"><i>I</i></button>
              <button type="button" class="hw-tool-btn" data-format="h2" title="二级标题"><b>H2</b></button>
              <button type="button" class="hw-tool-btn" data-format="h3" title="三级标题"><b>H3</b></button>
              <button type="button" class="hw-tool-btn" data-format="blockquote" title="引用块">“ ”</button>
              <button type="button" class="hw-tool-btn" data-format="code" title="代码块">&lt;/&gt;</button>
              <button type="button" class="hw-tool-btn" data-cmd="insertUnorderedList" title="无序列表">• 列表</button>
            </div>

            <div class="hw-toolbar-divider"></div>

            <div class="hw-toolbar-group">
              <button type="button" class="hw-tool-btn hw-tool-btn-highlight" id="tb-insert-image" title="在光标处插入图片与图注">
                <span>🖼️ 插入图片</span>
              </button>
              <button type="button" class="hw-tool-btn hw-tool-btn-highlight" id="tb-insert-style" title="在光标处插入画风卡片">
                <span>🎨 插入画风</span>
              </button>
              <button type="button" class="hw-tool-btn hw-tool-btn-highlight" id="tb-insert-layout" title="在光标处插入图型卡片">
                <span>📐 插入图型</span>
              </button>
              <button type="button" class="hw-tool-btn hw-tool-btn-highlight" id="tb-insert-work" title="在光标处插入作品卡片">
                <span>🖼️ 插入作品</span>
              </button>
              <button type="button" class="hw-tool-btn hw-tool-btn-gold" id="tb-insert-paywall" title="在光标处插入付费截断点（此线以下需付费解锁）" style="${d.publishMode === "paid_10" ? "" : "display:none;"}">
                <span>🔒 插入付费点</span>
              </button>
            </div>

            <input type="file" id="compose-hidden-file" accept="image/*" multiple style="display:none;" />
          </div>

          <!-- WYSIWYG Contenteditable Canvas -->
          <div
            id="compose-rich-editor"
            class="hw-rich-editor"
            contenteditable="true"
            role="textbox"
            aria-multiline="true"
            data-placeholder="在此撰写帖子正文… 支持段落、大标题、引用，并随时从上方工具栏将配图、画风、图型、作品卡片或付费截断线插入到文字流中。"
          >${d.bodyHtml || ""}</div>
        </main>

        <!-- Bottom Post Action Footer (below editor text canvas) -->
        <footer class="hw-compose-footer" id="compose-action-footer">
          <span id="compose-draft-status" role="status">草稿会自动保存到此浏览器</span>
          <div class="hw-compose-footer-left">
            <span style="font-size:12.5px;color:var(--ink-muted);line-height:1.6;">
              ✨ 论坛交流发帖立得 <strong>+5✦</strong> 社区积分 · 支持在编辑器内<strong>拖拽卡片与配图</strong>调整段落顺序 · 支持剪贴板图片<strong>直接粘贴 (Ctrl+V)</strong>
            </span>
          </div>
          <div class="hw-compose-footer-right" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <div style="display:flex;align-items:center;gap:6px;">
              <label for="compose-mode-dropdown" style="font-size:13px;font-weight:750;color:var(--ink-body);white-space:nowrap;">发帖模式：</label>
              <select class="hw-select" id="compose-mode-dropdown" style="padding:6px 10px;font-size:13px;height:36px;border-radius:8px;">
                <option value="free" ${d.publishMode === "free" ? "selected" : ""}>✨ 公开免费（发布立得 +5✦）</option>
                <option value="paid_10" ${d.publishMode === "paid_10" ? "selected" : ""}>💎 10✦ 付费阅读专栏</option>
                <option value="bounty_10" ${d.publishMode === "bounty_10" ? "selected" : ""}>💰 托管 10✦ 悬赏求调优</option>
                <option value="bounty_20" ${d.publishMode === "bounty_20" ? "selected" : ""}>💰 托管 20✦ 悬赏求调优</option>
              </select>
            </div>
            <button type="button" class="btn" id="compose-cancel-btn">取消返回</button>
            <button type="button" class="btn btn-primary" id="compose-submit-btn" ${d.submitting ? "disabled" : ""} style="padding:9px 28px;font-size:14.5px;font-weight:800;border-radius:10px;">
              ${d.submitting ? "⏳ 正在发布入库…" : "🚀 立即发布论坛帖"}
            </button>
          </div>
        </footer>
      </div>
    `;

    let savedRange = null;
    const editorEl = root.querySelector("#compose-rich-editor");
    const fileInput = root.querySelector("#compose-hidden-file");

    function saveEditorSelection() {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const r = sel.getRangeAt(0);
        if (editorEl && editorEl.contains(r.commonAncestorContainer)) {
          savedRange = r.cloneRange();
        }
      }
    }

    function restoreEditorSelection() {
      if (!editorEl) return;
      editorEl.focus();
      if (savedRange) {
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(savedRange);
      }
    }

    function insertHtmlAtCaret(html) {
      if (!editorEl) return;
      editorEl.focus();
      const sel = window.getSelection();
      let range = null;
      if (sel && sel.rangeCount > 0) {
        const r = sel.getRangeAt(0);
        if (editorEl.contains(r.commonAncestorContainer)) {
          range = r;
        }
      }
      if (!range && savedRange) {
        range = savedRange;
      }
      if (range) {
        range.deleteContents();
        const temp = document.createElement("div");
        temp.innerHTML = html;
        const frag = document.createDocumentFragment();
        let node, lastNode;
        while ((node = temp.firstChild)) {
          lastNode = frag.appendChild(node);
        }
        range.insertNode(frag);
        if (lastNode) {
          range = range.cloneRange();
          range.setStartAfter(lastNode);
          range.collapse(true);
          sel.removeAllRanges();
          sel.addRange(range);
        }
      } else {
        editorEl.innerHTML += html;
      }
      saveEditorSelection();
    }

    ["mouseup", "keyup", "input", "blur"].forEach((evt) => {
      editorEl.addEventListener(evt, saveEditorSelection);
    });

    root.querySelector("#compose-back-btn").onclick = () => {
      syncDraftInputsFromDom(root);
      exitComposeView(true);
    };

    const loginBtn = root.querySelector("#compose-login-btn");
    if (loginBtn) {
      loginBtn.onclick = () => {
        syncDraftInputsFromDom(root);
        openForumAuthPage("登录后即可正式发布论坛帖！");
      };
    }

    root.querySelectorAll("[data-compose-cat]").forEach((btn) => {
      btn.onclick = () => {
        const cat = btn.getAttribute("data-compose-cat");
        d.category = cat;
        root.querySelectorAll("[data-compose-cat]").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
      };
    });

    const modeDropdown = root.querySelector("#compose-mode-dropdown");
    const paywallBtn = root.querySelector("#tb-insert-paywall");
    modeDropdown.onchange = () => {
      d.publishMode = modeDropdown.value;
      if (d.publishMode.startsWith("bounty_")) {
        d.category = "tuning";
        root.querySelectorAll("[data-compose-cat]").forEach((b) => {
          b.classList.toggle("is-active", b.getAttribute("data-compose-cat") === "tuning");
        });
      }
      if (d.publishMode === "paid_10") {
        if (paywallBtn) paywallBtn.style.display = "inline-flex";
        toast("💡 已开启付费专栏模式！请在编辑器中点击【🔒 插入付费点】划定试读截断线。");
      } else {
        if (paywallBtn) paywallBtn.style.display = "none";
        const existingDivider = editorEl.querySelector(".hw-paywall-divider");
        if (existingDivider) existingDivider.remove();
      }
    };

    if (paywallBtn) {
      paywallBtn.onclick = () => {
        saveEditorSelection();
        const existing = editorEl.querySelector(".hw-paywall-divider");
        if (existing) {
          existing.remove();
        }
        restoreEditorSelection();
        insertHtmlAtCaret(buildPaywallDividerHtml());
        toast("🔒 已在当前光标位置插入付费截断线（此线以下内容需付费解锁）！");
      };
    }

    root.querySelectorAll("[data-cmd]").forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        const cmd = btn.getAttribute("data-cmd");
        document.execCommand(cmd, false, null);
        editorEl.focus();
      };
    });

    root.querySelectorAll("[data-format]").forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        const fmt = btn.getAttribute("data-format");
        if (fmt === "code") {
          const sel = window.getSelection();
          if (sel && sel.toString()) {
            document.execCommand("insertHTML", false, `<code>${esc(sel.toString())}</code>`);
          } else {
            document.execCommand("formatBlock", false, "<pre>");
          }
        } else {
          document.execCommand("formatBlock", false, `<${fmt}>`);
        }
        editorEl.focus();
      };
    });

    // In-editor delete button handler
    editorEl.addEventListener("click", (e) => {
      const delBtn = e.target.closest(".hw-intext-del-btn");
      if (delBtn) {
        e.preventDefault();
        const block = delBtn.closest(".hw-intext-media, .hw-intext-card, .hw-paywall-divider");
        if (block) {
          block.remove();
          saveEditorSelection();
        }
      }
    });

    async function insertMediaFile(file, customTag = "") {
      if (!file) return;
      const dataUrl = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => resolve("");
        reader.readAsDataURL(file);
      });
      if (!dataUrl) return;
      const baseTag = customTag || (file.name ? file.name.replace(/\.[^.]+$/, "").slice(0, 24) : "实测配图");
      let finalUrl = dataUrl;
      if (App.state.loggedIn && App.state.serverBacked) {
        try {
          const up = await S.apiJson("/api/uploads", {
            method: "POST",
            body: { dataUrl, nameZh: baseTag, cat: "forum" }
          });
          if (up && up.url) finalUrl = up.url;
        } catch (_) {}
      }
      restoreEditorSelection();
      insertHtmlAtCaret(buildIntextMediaHtml(finalUrl, baseTag));
    }

    // Direct Native File Chooser (No popup modal window)
    root.querySelector("#tb-insert-image").onclick = () => {
      saveEditorSelection();
      fileInput.click();
    };

    fileInput.onchange = async (ev) => {
      const files = Array.from(ev.target.files || []);
      for (const file of files) {
        await insertMediaFile(file);
      }
      fileInput.value = "";
    };

    // Paste Images Directly into Editor via Clipboard (Ctrl+V)
    editorEl.addEventListener("paste", async (e) => {
      const items = Array.from(e.clipboardData?.items || []);
      const imgItem = items.find((it) => it.type && it.type.startsWith("image/"));
      if (imgItem) {
        e.preventDefault();
        const file = imgItem.getAsFile();
        if (file) {
          const timeStr = new Date().toTimeString().slice(0, 8).replace(/:/g, "");
          await insertMediaFile(file, `剪贴板截图_${timeStr}`);
          toast("📋 已通过剪贴板直接插入图片！");
        }
      }
    });

    // In-editor Drag and Drop to Reposition Cards & Media Figures
    let draggedBlock = null;
    let dropIndicator = null;

    editorEl.addEventListener("dragstart", (e) => {
      if (e.target.closest("figcaption, button")) {
        return;
      }
      const block = e.target.closest(".hw-intext-media, .hw-intext-card, .hw-paywall-divider");
      if (block && editorEl.contains(block)) {
        draggedBlock = block;
        const dragId = block.getAttribute("data-card-id") || block.getAttribute("data-media-url") || "dragged-block";
        e.dataTransfer.setData("text/plain", dragId);
        e.dataTransfer.effectAllowed = "move";
        setTimeout(() => {
          if (draggedBlock) draggedBlock.classList.add("is-dragging");
        }, 0);
      }
    });

    editorEl.addEventListener("dragend", () => {
      if (draggedBlock) {
        draggedBlock.classList.remove("is-dragging");
        draggedBlock = null;
      }
      if (dropIndicator && dropIndicator.parentNode) {
        dropIndicator.remove();
      }
      editorEl.classList.remove("is-drag-over-files");
    });

    editorEl.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";

      if (e.dataTransfer.types && Array.from(e.dataTransfer.types).includes("Files")) {
        editorEl.classList.add("is-drag-over-files");
        return;
      }

      if (draggedBlock) {
        const targetBlock = e.target.closest(".hw-intext-media, .hw-intext-card, .hw-paywall-divider, p, h2, h3, blockquote, pre");
        if (targetBlock && targetBlock !== draggedBlock && editorEl.contains(targetBlock)) {
          if (!dropIndicator) {
            dropIndicator = document.createElement("div");
            dropIndicator.className = "hw-drop-indicator";
          }
          const rect = targetBlock.getBoundingClientRect();
          const placeAfter = (e.clientY - rect.top) > (rect.height / 2);
          if (placeAfter) {
            targetBlock.after(dropIndicator);
          } else {
            targetBlock.before(dropIndicator);
          }
        }
      }
    });

    editorEl.addEventListener("dragleave", (e) => {
      if (!editorEl.contains(e.relatedTarget)) {
        editorEl.classList.remove("is-drag-over-files");
        if (dropIndicator && dropIndicator.parentNode) {
          dropIndicator.remove();
        }
      }
    });

    editorEl.addEventListener("drop", async (e) => {
      e.preventDefault();
      editorEl.classList.remove("is-drag-over-files");

      // Handle dropped files from local OS
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        for (const file of Array.from(e.dataTransfer.files)) {
          if (file.type.startsWith("image/")) {
            await insertMediaFile(file);
          }
        }
        return;
      }

      // Handle repositioning dragged card or image block
      if (draggedBlock) {
        if (dropIndicator && dropIndicator.parentNode) {
          dropIndicator.replaceWith(draggedBlock);
        } else {
          let range = null;
          if (document.caretRangeFromPoint) {
            range = document.caretRangeFromPoint(e.clientX, e.clientY);
          }
          if (range && editorEl.contains(range.commonAncestorContainer) && !draggedBlock.contains(range.commonAncestorContainer)) {
            range.insertNode(draggedBlock);
          }
        }
        if (!draggedBlock.nextElementSibling || draggedBlock.nextElementSibling.classList.contains("hw-intext-card") || draggedBlock.nextElementSibling.classList.contains("hw-intext-media") || draggedBlock.nextElementSibling.classList.contains("hw-paywall-divider")) {
          const p = document.createElement("p");
          p.innerHTML = "<br>";
          draggedBlock.after(p);
        }
        draggedBlock.classList.remove("is-dragging");
        draggedBlock = null;
        saveEditorSelection();
        toast("✨ 已调整卡片/配图在正文中的位置！");
      }
    });

    root.querySelector("#tb-insert-style").onclick = () => {
      saveEditorSelection();
      S.openSharedCardPickerModal({
        kind: "style",
        onSelect(pickedCard) {
          restoreEditorSelection();
          insertHtmlAtCaret(buildIntextCardHtml(pickedCard));
        }
      });
    };

    root.querySelector("#tb-insert-layout").onclick = () => {
      saveEditorSelection();
      S.openSharedCardPickerModal({
        kind: "layout",
        onSelect(pickedCard) {
          restoreEditorSelection();
          insertHtmlAtCaret(buildIntextCardHtml(pickedCard));
        }
      });
    };

    root.querySelector("#tb-insert-work").onclick = () => {
      saveEditorSelection();
      S.openSharedCardPickerModal({
        kind: "work",
        onSelect(pickedCard) {
          restoreEditorSelection();
          insertHtmlAtCaret(buildIntextCardHtml(pickedCard));
        }
      });
    };

    const cancelBtn = root.querySelector("#compose-cancel-btn");
    if (cancelBtn) {
      cancelBtn.onclick = () => {
        syncDraftInputsFromDom(root);
        exitComposeView(true);
      };
    }

    root.querySelector("#compose-submit-btn").onclick = async () => {
      syncDraftInputsFromDom(root);
      if (!App.state.loggedIn) {
        openForumAuthPage("请先登录账号后再发布论坛帖");
        return;
      }
      const title = (d.title || "").trim();
      if (title.length < 4) {
        toast("帖子标题至少输入 4 个字");
        const el = root.querySelector("#compose-title-input");
        if (el) el.focus();
        return;
      }

      // Extract in-text media figures
      const mediaFigures = Array.from(editorEl.querySelectorAll(".hw-intext-media"));
      const extractedImages = mediaFigures
        .map((fig) => {
          const url = fig.getAttribute("data-media-url") || fig.querySelector("img")?.src || "";
          const tag = fig.querySelector("figcaption")?.innerText?.trim() || "";
          return { url, tag };
        })
        .filter((x) => Boolean(x.url));

      // Extract in-text cards
      const cardDivs = Array.from(editorEl.querySelectorAll(".hw-intext-card"));
      const extractedCards = cardDivs
        .map((cd) => ({
          kind: cd.getAttribute("data-card-kind") || "style",
          id: cd.getAttribute("data-card-id") || "",
          title: cd.getAttribute("data-card-title") || "",
          image: cd.getAttribute("data-card-image") || "",
          authorName: cd.getAttribute("data-card-author") || "",
          desc: cd.getAttribute("data-card-desc") || ""
        }))
        .filter((x) => Boolean(x.id));

      // Clean clone HTML for persistence
      const clone = editorEl.cloneNode(true);
      clone.querySelectorAll(".hw-intext-del-btn").forEach((btn) => btn.remove());
      clone.querySelectorAll("figcaption").forEach((fc) => fc.removeAttribute("contenteditable"));
      const cleanHtml = clone.innerHTML.trim();

      const plainText = stripHtmlToSnippet(cleanHtml, 9999);
      if (plainText.length < 8 && extractedImages.length === 0 && extractedCards.length === 0) {
        toast("正文至少输入 8 个字或插入配图/卡片");
        editorEl.focus();
        return;
      }

      const bounty = d.publishMode === "bounty_10" ? 10 : d.publishMode === "bounty_20" ? 20 : 0;
      const price = d.publishMode === "paid_10" ? 10 : 0;

      let summaryHtml = cleanHtml;
      let lockedHtml = cleanHtml;

      if (price > 0) {
        const dividerInClone = clone.querySelector(".hw-paywall-divider");
        if (!dividerInClone) {
          toast("您已开启付费专栏模式，请先点击上方工具栏【🔒 插入付费点】以划定付费线！");
          if (paywallBtn) {
            paywallBtn.focus();
          }
          return;
        }

        const beforeWrap = document.createElement("div");
        let foundDivider = false;
        Array.from(clone.childNodes).forEach((child) => {
          if (child === dividerInClone || (child.contains && child.contains(dividerInClone))) {
            foundDivider = true;
            return;
          }
          if (!foundDivider) {
            beforeWrap.appendChild(child.cloneNode(true));
          }
        });

        summaryHtml = beforeWrap.innerHTML.trim() || cleanHtml;
        lockedHtml = cleanHtml;
      }

      if (bounty > 0 && (App.state.credits || 0) < bounty) {
        toast(`当前积分不足托管 ${bounty}✦ 悬赏金`);
        return;
      }

      d.submitting = true;
      renderForum();
      try {
        let createdTopicId = "";
        const primaryCard = extractedCards[0] || d.sharedCard || null;
        const effStyles = [];
        let effLayout = "";
        let effWorkId = "";

        for (const c of extractedCards) {
          if (c.kind === "style" && !effStyles.includes(c.id)) effStyles.push(c.id);
          if (c.kind === "layout" && !effLayout) effLayout = c.id;
          if (c.kind === "work" && !effWorkId) effWorkId = c.id;
        }
        if (!effStyles.length && primaryCard?.kind === "style") effStyles.push(primaryCard.id);
        if (!effLayout && primaryCard?.kind === "layout") effLayout = primaryCard.id;
        if (!effWorkId && primaryCard?.kind === "work") effWorkId = primaryCard.id;

        const effImages = extractedImages.length > 0 ? extractedImages : d.images;

        if (App.state.serverBacked) {
          const res = await S.apiJson("/api/forum/topics", {
            method: "POST",
            body: {
              title,
              category: d.category,
              summary: summaryHtml,
              body: cleanHtml,
              images: effImages,
              styles: effStyles,
              layout: effLayout,
              workId: effWorkId,
              sharedCard: primaryCard,
              bounty,
              price,
              lockedBody: price > 0 ? lockedHtml : ""
            }
          });
          createdTopicId = (res.topic && res.topic.id) || res.topicId || "";
          await S.refreshFromServer();
          toast(
            bounty > 0
              ? `🎉 悬赏帖已发布（已托管 ${bounty}✦ 悬赏积分）！`
              : `🎉 论坛帖发布成功！${res.rewarded > 0 ? `获得 +${res.rewarded}✦ 社区发帖积分` : ""}`
          );
        } else {
          createdTopicId = "top_" + Date.now();
          const bDef = BOARD_DEFS.find((x) => x.key === d.category) || BOARD_DEFS[1];
          App.state.topics.unshift({
            id: createdTopicId,
            category: d.category,
            categoryLabel: bDef.label,
            title,
            summary: summaryHtml,
            body: cleanHtml,
            author: App.state.user.username,
            authorName: App.state.user.name,
            createdAt: "刚刚",
            images: effImages,
            styles: effStyles,
            layout: effLayout,
            workId: effWorkId,
            sharedCard: primaryCard,
            bounty,
            price,
            lockedBody: price > 0 ? lockedHtml : "",
            likes: 1,
            favorites: 0,
            views: 1,
            replies: []
          });
          S.addLedger(`发布论坛交流帖《${title.slice(0, 14)}…》`, +5);
          await S.saveState();
          toast("🎉 论坛帖发布成功！获得 +5✦ 积分");
        }
        FUI.category = d.category;
        clearTimeout(draftSaveTimer);
        localStorage.removeItem(draftKey());
        FUI.composeDraft = createEmptyDraft({ category: d.category });
        if (createdTopicId) {
          openTopicPage(createdTopicId, 0);
        } else {
          openForumList(true);
        }
      } catch (err) {
        d.submitting = false;
        renderForum();
        toast(`发布失败：${err.message}`);
      }
    };
  }

  /* ======================== 4. STANDALONE TOPIC DETAIL & REPLIES PAGE (?view=topic&id=...) ======================== */
  function openTopicModal(topicId, activeImgIdx = 0) {
    openTopicPage(topicId, activeImgIdx);
  }

  let _activeTopicDetailGen = 0;
  const _socialInFlight = new Set();
  const _socialSeq = new Map();
  if (typeof window !== "undefined") {
    window._socialInFlight = _socialInFlight;
    window._socialSeq = _socialSeq;
  }

  function _getTopicLikeState(topicData) {
    if (!topicData) return { liked: false, count: 0 };
    const topic = topicData.topic || {};
    const mount = topicData.mount || { kind: "discussion" };
    const viewer = topicData.viewer || {};
    const liked = Boolean(viewer.liked);
    let count = 0;
    if (mount.kind === "work" && mount.work) {
      count = Number(mount.work.likes != null ? mount.work.likes : topic.likes || 0);
    } else if ((mount.kind === "style" || mount.kind === "layout") && mount.resource) {
      count = Number(mount.resource.likes != null ? mount.resource.likes : topic.likes || 0);
    } else {
      count = Number(topic.likes || 0);
    }
    return { liked, count: Math.max(0, count) };
  }

  function _getTopicFavoriteState(topicData) {
    if (!topicData) return { favorited: false, count: 0 };
    const topic = topicData.topic || {};
    const mount = topicData.mount || { kind: "discussion" };
    const viewer = topicData.viewer || {};
    const favorited = Boolean(viewer.favorited);
    let count = 0;
    if (mount.kind === "work" && mount.work) {
      count = Number(mount.work.favorites != null ? mount.work.favorites : topic.favorites || 0);
    } else if ((mount.kind === "style" || mount.kind === "layout") && mount.resource) {
      count = Number(mount.resource.favorites != null ? mount.resource.favorites : topic.favorites || 0);
    } else {
      count = Number(topic.favorites || 0);
    }
    return { favorited, count: Math.max(0, count) };
  }

  function _setTopicLikeState(topicData, liked, count) {
    if (!topicData) return;
    const finalCount = Math.max(0, Number(count) || 0);
    if (!topicData.viewer) topicData.viewer = {};
    topicData.viewer.liked = Boolean(liked);
    if (topicData.topic) topicData.topic.likes = finalCount;
    if (topicData.mount) {
      if (topicData.mount.resource) {
        topicData.mount.resource.likes = finalCount;
      } else if (topicData.mount.work) {
        topicData.mount.work.likes = finalCount;
      }
    }
  }

  function _setTopicFavoriteState(topicData, favorited, count) {
    if (!topicData) return;
    const finalCount = Math.max(0, Number(count) || 0);
    if (!topicData.viewer) topicData.viewer = {};
    topicData.viewer.favorited = Boolean(favorited);
    if (topicData.topic) topicData.topic.favorites = finalCount;
    if (topicData.mount) {
      if (topicData.mount.resource) {
        topicData.mount.resource.favorites = finalCount;
      } else if (topicData.mount.work) {
        topicData.mount.work.favorites = finalCount;
      }
    }
  }

  function _updateTopicCountsUI() {
    const el = document.querySelector("#topic-counts");
    if (!el || !_activeTopicDetail?.topicData) return;
    const tData = _activeTopicDetail.topicData;
    const { count: curLikes } = _getTopicLikeState(tData);
    const { count: curFavs } = _getTopicFavoriteState(tData);
    const mKind = tData.mount?.kind;
    const curForks = mKind === "work" ? Number(tData.mount?.work?.forks || 0) : 0;
    el.textContent = `点赞 ${curLikes} · 收藏 ${curFavs}${mKind === "work" ? ` · 做同款 ${curForks}` : ""}`;
  }

  function _updateTopicLikeBtnUI() {
    const el = document.querySelector("#topic-page-like");
    if (!el || !_activeTopicDetail?.topicData) return;
    const { liked: curLiked, count: curLikes } = _getTopicLikeState(_activeTopicDetail.topicData);
    el.textContent = `👍 ${curLiked ? "已赞" : "点赞"} (${curLikes})`;
    el.classList.toggle("btn-primary", curLiked);
  }

  function _updateTopicFavBtnUI() {
    const el = document.querySelector("#topic-page-collect");
    if (!el || !_activeTopicDetail?.topicData) return;
    const { favorited: curFav, count: curFavs } = _getTopicFavoriteState(_activeTopicDetail.topicData);
    el.textContent = `${curFav ? "♥ 已收藏" : "♡ 收藏"} (${curFavs})`;
    el.classList.toggle("btn-primary", curFav);
  }

  function _applyTopicSocialCalibration(targetTopicData, postRes, action = null) {
    if (!targetTopicData || !postRes) return;
    const freshTopic = postRes.topic || {};
    const freshViewer = postRes.viewer || {};
    const freshMount = postRes.mount || {};

    if (!targetTopicData.viewer) targetTopicData.viewer = {};

    const updateLike = !action || action === "like";
    const updateCollect = !action || action === "collect";

    if (updateLike) {
      if (freshViewer.liked !== undefined) targetTopicData.viewer.liked = Boolean(freshViewer.liked);
      if (targetTopicData.topic && freshTopic.likes !== undefined) {
        targetTopicData.topic.likes = Number(freshTopic.likes) || 0;
      }
      if (targetTopicData.mount && freshMount) {
        if (targetTopicData.mount.resource && freshMount.resource && freshMount.resource.likes !== undefined) {
          targetTopicData.mount.resource.likes = Number(freshMount.resource.likes) || 0;
        }
        if (targetTopicData.mount.work && freshMount.work && freshMount.work.likes !== undefined) {
          targetTopicData.mount.work.likes = Number(freshMount.work.likes) || 0;
        }
      }
    }

    if (updateCollect) {
      if (freshViewer.favorited !== undefined) targetTopicData.viewer.favorited = Boolean(freshViewer.favorited);
      if (targetTopicData.topic && freshTopic.favorites !== undefined) {
        targetTopicData.topic.favorites = Number(freshTopic.favorites) || 0;
      }
      if (targetTopicData.mount && freshMount) {
        if (targetTopicData.mount.resource && freshMount.resource && freshMount.resource.favorites !== undefined) {
          targetTopicData.mount.resource.favorites = Number(freshMount.resource.favorites) || 0;
        }
        if (targetTopicData.mount.work && freshMount.work && freshMount.work.favorites !== undefined) {
          targetTopicData.mount.work.favorites = Number(freshMount.work.favorites) || 0;
        }
      }
    }
  }

  function _releaseSocialLock(topicId, action) {
    const lockKey = `${topicId}:${action}`;
    _socialInFlight.delete(lockKey);
    if (_activeTopicDetail && _activeTopicDetail.id === topicId) {
      const btnId = action === "like" ? "#topic-page-like" : "#topic-page-collect";
      const curBtn = document.querySelector(btnId);
      if (curBtn) {
        curBtn.disabled = false;
        curBtn.removeAttribute("aria-busy");
      }
    }
  }

  let _activeTopicDetail = {
    id: null,
    gen: 0,
    status: "idle",
    topicData: null,
    replies: [],
    pendingReplies: [],
    nextCursor: null,
    err: null
  };

  function getScrollBehavior() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  }

  function renderSingleFloorReplyHtml(r, idx, topic) {
    const authorName = r.authorName || r.name || r.author || r.user || "创作者";
    const authorUsername = r.author || r.user || authorName;
    const timeLabel = r.time || "刚刚";
    const isFloorAuthor = App.state && App.state.loggedIn && (r.author === App.state.user.username || r.user === App.state.user.username);
    const canModerateThisBoard = S.canModerateForumBoard ? S.canModerateForumBoard(topic.category) : false;
    const isStaff = App.state && App.state.loggedIn && (App.state.user.role === "admin" || App.state.user.role === "operator" || App.state.user.role === "reviewer");
    const canAccept =
      topic.bounty > 0 &&
      !topic.solved &&
      !r.accepted &&
      App.state &&
      App.state.loggedIn &&
      r.user !== topic.author &&
      r.author !== topic.author &&
      (topic.author === App.state.user.username || isStaff);
    const canDeleteReply = S.canDeleteReply
      ? S.canDeleteReply(r, topic)
      : (App.state && App.state.loggedIn && (isFloorAuthor || canModerateThisBoard));

    return `
      <div class="forum-reply-card ${r.accepted ? "is-accepted" : ""}" data-reply-id="${esc(r.id)}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <button type="button" class="hw-author-chip" data-open-creator="${esc(authorUsername)}" style="padding:2px 8px;">
              <strong style="font-size:13.2px;color:var(--ink-strong);">@${esc(authorName)}</strong>
            </button>
            ${renderModBadgeHtml(authorUsername, topic.category)}
            <span style="color:var(--ink-faint);font-size:12px;">${esc(timeLabel)}</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            ${r.accepted ? `<span style="background:var(--jade);color:#fff;font-size:11.5px;font-weight:800;padding:2px 9px;border-radius:999px;">🏆 最佳采纳方案(+${topic.bounty || 0}✦)</span>` : ""}
            ${canAccept ? `<button type="button" class="btn btn-sm btn-gold" data-accept-reply="${esc(r.id)}">🏆 采纳并结帖 ${topic.bounty}✦</button>` : ""}
            ${canModerateThisBoard ? `<button type="button" class="btn btn-sm" data-hide-reply="${esc(r.id)}" style="font-size:11px;padding:1px 7px;color:var(--ink-muted);">🙈 隐藏回复</button>` : ""}
            ${canDeleteReply ? `<button type="button" class="btn btn-sm" data-del-reply="${esc(r.id)}" style="font-size:11px;padding:1px 7px;color:var(--vermilion);">🗑️ 删除</button>` : ""}
            <span class="hw-comment-floor">#${idx + 1}楼</span>
          </div>
        </div>
        <div style="font-size:14.2px;color:var(--ink-body);line-height:1.68;">${renderReplyContentHtml(r.text)}</div>
        ${
          r.mountedStyle || r.mountedLayout
            ? `<div style="margin-top:8px;">
                <a class="btn btn-sm" style="padding:2px 9px;font-size:11.5px;" href="${esc(channelUrl("studio", { style: r.mountedStyle || "", layout: r.mountedLayout || "" }))}">去无限画布试此方案 ↗</a>
              </div>`
            : ""
        }
        <div class="forum-reply-footer">
          <button type="button" class="btn btn-sm" data-reply-floor="${idx + 1}" data-reply-user="${esc(authorUsername)}" data-reply-name="${esc(authorName)}" style="font-size:12px;padding:3px 10px;">
            💬 回复
          </button>
          <button type="button" class="btn btn-sm" data-quote-floor="${idx + 1}" data-reply-user="${esc(authorUsername)}" data-reply-name="${esc(authorName)}" data-reply-id="${esc(r.id)}" style="font-size:12px;padding:3px 10px;">
            ❝ 引用回复
          </button>
        </div>
      </div>
    `;
  }

  function renderResourceMountArticleHtml(kind, res) {
    if (!res) return "";
    const isStyle = kind === "style";
    const kindName = isStyle ? "画风" : "图型";
    const useBtnText = isStyle ? "使用此画风" : "使用此图型";
    const worksTitle = isStyle ? "用这个画风做的作品" : "用这个图型做的作品";
    const relatedWorksHref = S.channelUrl("forum", { view: "related", kind: kind, id: res.code, tab: "works" });

    const isStaff = Boolean(App.state?.loggedIn && App.state?.user && ["admin", "superadmin", "moderator", "operator", "reviewer"].includes(App.state.user.role));
    const isExclusive = res.sourceType === "exclusive";

    const viewerStamps = res.viewerStamps || _activeTopicDetail?.topicData?.viewer?.stamps || [];
    const stampedRecipe = viewerStamps.includes("超实用配方");
    const stampedAesthetic = viewerStamps.includes("审美在线");
    const recipeCount = (res.stampCounts && res.stampCounts["超实用配方"]) || 0;
    const aestheticCount = (res.stampCounts && res.stampCounts["审美在线"]) || 0;
    const canTip = Boolean(
      res.sourceType === "community" &&
      res.author &&
      (!App.state?.loggedIn || !App.state?.user || App.state.user.username !== res.author)
    );

    return `
      <style>
        .topic-resource-stamps {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 14px;
          margin-bottom: 14px;
          flex-wrap: wrap;
        }
        .topic-resource-stamps .hw-stamp-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          border-radius: 999px;
          border: 1px solid var(--line-soft);
          background: var(--paper-card);
          font-size: 13px;
          cursor: pointer;
          color: var(--ink-base);
          transition: all 0.15s ease;
        }
        .topic-resource-stamps .hw-stamp-btn:hover {
          border-color: var(--gold);
        }
        .topic-resource-stamps .hw-stamp-btn.is-active {
          background: #fbf5e8;
          border-color: var(--gold);
          color: #8a5a00;
          font-weight: 700;
        }
        .topic-resource-stamps .topic-stamp-tip-btn {
          margin-left: auto;
        }
        @media (max-width: 480px) {
          .topic-resource-stamps .topic-stamp-tip-btn {
            margin-left: 0;
            width: 100%;
            text-align: center;
            margin-top: 6px;
          }
        }
      </style>
      <div class="topic-resource-mount" style="min-width:0;max-width:100%;">
        <div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;margin-bottom:20px;">
          ${res.image ? `
            <div style="flex:0 0 240px;max-width:100%;">
              <img src="${esc(res.image)}" alt="${esc(res.name)}" data-zoom-img="${esc(res.image)}" style="width:100%;border-radius:10px;border:1px solid var(--line-soft);cursor:zoom-in;display:block;" />
              ${Array.isArray(res.examples) && res.examples.length ? `
                <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
                  ${res.examples.map(ex => `
                    <img src="${esc(ex)}" alt="示例图" data-zoom-img="${esc(ex)}" style="width:72px;height:72px;object-fit:cover;border-radius:6px;border:1px solid var(--line-soft);cursor:zoom-in;display:block;" />
                  `).join("")}
                </div>
              ` : ""}
            </div>
          ` : ""}
          <div style="flex:1;min-width:240px;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
              <div style="font-size:12px;font-weight:800;color:var(--vermilion);margin-bottom:4px;">#${esc(res.code)}</div>
              ${isStaff ? `<a href="${esc(S.channelUrl("admin", { module: "catalog", q: res.code }))}" target="_blank" class="btn btn-sm btn-ghost" style="font-size:12px;color:var(--ink-muted);padding:2px 8px;text-decoration:none;" title="在后台目录中管理此资源">🛠 在后台编辑 ↗</a>` : ""}
            </div>
            <h2 style="margin:0 0 10px;font-size:20px;font-family:var(--font-serif);">${esc(res.name)}</h2>
            ${res.description ? `<p style="margin:0 0 14px;font-size:13.5px;color:var(--ink-muted);line-height:1.6;overflow-wrap:anywhere;">${esc(res.description)}</p>` : ""}
            <div style="margin-top:12px;">
              <a class="btn btn-primary" href="${esc(res.useUrl)}" style="font-weight:750;">${esc(useBtnText)} ↗</a>
            </div>
          </div>
        </div>

        <div class="topic-resource-stamps">
          <button type="button" class="hw-stamp-btn ${stampedRecipe ? "is-active" : ""}" id="topic-stamp-recipe" data-stamp-label="超实用配方">
            🎯 超实用配方 (${recipeCount})
          </button>
          <button type="button" class="hw-stamp-btn ${stampedAesthetic ? "is-active" : ""}" id="topic-stamp-aesthetic" data-stamp-label="审美在线">
            ✨ 审美在线 (${aestheticCount})
          </button>
          ${canTip ? `
            <button type="button" class="btn btn-sm btn-gold topic-stamp-tip-btn" id="topic-stamp-tip-btn">
              🎁 赞赏 2✦ 给 @${esc(res.authorName || res.author)}
            </button>
          ` : ""}
        </div>

        <div style="margin-top:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <h3 style="margin:0;font-size:15px;font-weight:800;">${esc(kindName)}定义</h3>
            ${(!isExclusive && res.unlocked && res.definition) ? `<button type="button" class="btn btn-sm" id="resource-copy-def-btn">复制定义</button>` : ""}
          </div>
          ${
            isExclusive
              ? (res.unlocked || !res.unlockCost
                  ? `<p style="color:var(--ink-muted);font-size:13px;padding:14px;background:var(--paper-bg);border-radius:8px;border:1px solid var(--line-soft);margin:0;">官网独占：只能在创作台在线调用，不展示定义</p>`
                  : `<div class="hw-locked-gate-box" style="padding:24px;text-align:center;background:var(--paper-bg);border:1px dashed var(--line-strong);border-radius:10px;">
                      <div style="font-weight:850;font-size:15px;color:var(--gold);margin-bottom:6px;">🔒 此资源需解锁后在线使用</div>
                      <p style="margin:0 0 12px;font-size:12.5px;color:var(--ink-muted);">官网独占：只能在创作台在线调用，不展示定义。解锁花费 <strong>${res.unlockCost || 0}</strong> 积分</p>
                      <button type="button" class="btn btn-primary btn-sm" id="resource-btn-unlock">🔓 解锁后可在线使用</button>
                    </div>`)
              : (res.unlocked
                  ? (res.definition
                      ? `<pre class="fwp-prompt-text" style="white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;background:var(--paper-bg);padding:14px;border-radius:8px;border:1px solid var(--line-soft);font-size:13px;line-height:1.6;">${esc(res.definition)}</pre>`
                      : `<p style="color:var(--ink-muted);font-size:13px;">暂无定义内容</p>`)
                  : `<div class="hw-locked-gate-box" style="padding:24px;text-align:center;background:var(--paper-bg);border:1px dashed var(--line-strong);border-radius:10px;">
                      <div style="font-weight:850;font-size:15px;color:var(--gold);margin-bottom:6px;">🔒 此资源需解锁后查看定义</div>
                      <p style="margin:0 0 12px;font-size:12.5px;color:var(--ink-muted);">解锁花费 <strong>${res.unlockCost || 0}</strong> 积分</p>
                      <button type="button" class="btn btn-primary btn-sm" id="resource-btn-unlock">🔓 立即解锁</button>
                    </div>`)
          }
        </div>

        <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--line-soft);min-width:0;max-width:100%;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h3 style="margin:0;font-size:16px;font-weight:800;">${esc(worksTitle)}</h3>
            <a class="btn btn-sm" href="${esc(relatedWorksHref)}" id="topic-related-works-all">查看全部 →</a>
          </div>
          <div id="topic-related-works-container" style="min-width:0;max-width:100%;">
            <div style="color:var(--ink-muted);font-size:13px;">正在加载相关作品…</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderTopicDetailPage(root) {
    const tid = String(FUI.activeTopicId || "").trim();
    if (!tid) {
      root.innerHTML = `
        <div class="hw-detail-page" id="standalone-topic-detail-page">
          <div class="hw-subpage-bar">
            <button type="button" class="btn btn-sm" id="topic-missing-back">← 返回论坛讨论列表</button>
          </div>
          <div class="hw-detail-section-card" style="text-align:center;padding:48px 24px;">
            <h2 style="margin:0 0 8px;">未找到对应的论坛帖子</h2>
            <p style="color:var(--ink-muted);margin:0 0 18px;">该帖子可能已被版主归档或链接参数有误。</p>
            <button type="button" class="btn btn-primary" id="topic-missing-list">返回社区论坛首页</button>
          </div>
        </div>
      `;
      root.querySelector("#topic-missing-back").onclick = () => openForumList(true);
      root.querySelector("#topic-missing-list").onclick = () => openForumList(true);
      return;
    }

    if (_activeTopicDetail.id !== tid) {
      _activeTopicDetailGen++;
      _activeTopicDetail = { id: tid, gen: _activeTopicDetailGen, status: "loading", topicData: null, replies: [], pendingReplies: [], nextCursor: null, err: null };
    }

    if (_activeTopicDetail.status === "loading") {
      root.innerHTML = `
        <div class="hw-detail-page" id="standalone-topic-detail-page">
          <div class="hw-subpage-bar">
            <div class="hw-subpage-crumbs">
              <button type="button" class="btn btn-sm" id="topic-loading-back">← 返回论坛列表</button>
            </div>
          </div>
          <div class="hw-detail-section-card" style="text-align:center;padding:48px 24px;">
            <h2 style="margin:0 0 8px;">正在加载…</h2>
            <p style="color:var(--ink-muted);margin:0;">正在加载帖子与楼层回复…</p>
          </div>
        </div>
      `;
      const backBtn = root.querySelector("#topic-loading-back");
      if (backBtn) backBtn.onclick = () => openForumList(true);

      const targetId = tid;
      Promise.all([
        S.apiJson(`/api/posts/${encodeURIComponent(targetId)}`),
        S.apiJson(`/api/posts/${encodeURIComponent(targetId)}/replies?limit=20`)
      ]).then(([postRes, repliesRes]) => {
        if (FUI.view !== "topic" || FUI.activeTopicId !== targetId) return;
        if (!postRes || !postRes.ok || !postRes.topic) {
          _activeTopicDetail.status = "404";
          renderTopicDetailPage(root);
          return;
        }
        _activeTopicDetail.status = "loaded";
        _activeTopicDetail.topicData = postRes;
        _activeTopicDetail.replies = (repliesRes && repliesRes.items) || [];
        _activeTopicDetail.pendingReplies = [];
        _activeTopicDetail.nextCursor = (repliesRes && repliesRes.nextCursor) || null;
        renderTopicDetailPage(root);
      }).catch((err) => {
        if (FUI.view !== "topic" || FUI.activeTopicId !== targetId) return;
        if (err && (err.status === 404 || String(err.message || "").includes("404") || String(err.message || "").includes("不存在") || String(err.message || "").includes("不可见"))) {
          _activeTopicDetail.status = "404";
        } else {
          _activeTopicDetail.status = "error";
          _activeTopicDetail.err = err;
        }
        renderTopicDetailPage(root);
      });
      return;
    }

    if (_activeTopicDetail.status === "404") {
      root.innerHTML = `
        <div class="hw-detail-page" id="standalone-topic-detail-page">
          <div class="hw-subpage-bar">
            <button type="button" class="btn btn-sm" id="topic-missing-back">← 返回论坛讨论列表</button>
          </div>
          <div class="hw-detail-section-card" style="text-align:center;padding:48px 24px;">
            <h2 style="margin:0 0 8px;">帖子不存在或已不可见</h2>
            <p style="color:var(--ink-muted);margin:0 0 18px;">该帖子可能已被版主归档或链接参数有误。</p>
            <button type="button" class="btn btn-primary" id="topic-missing-list">返回社区论坛首页</button>
          </div>
        </div>
      `;
      root.querySelector("#topic-missing-back").onclick = () => openForumList(true);
      root.querySelector("#topic-missing-list").onclick = () => openForumList(true);
      return;
    }

    if (_activeTopicDetail.status === "error") {
      root.innerHTML = `
        <div class="hw-detail-page" id="standalone-topic-detail-page">
          <div class="hw-subpage-bar">
            <button type="button" class="btn btn-sm" id="topic-error-back">← 返回论坛讨论列表</button>
          </div>
          <div class="hw-detail-section-card" style="text-align:center;padding:48px 24px;">
            <h2 style="margin:0 0 8px;">网络加载失败</h2>
            <p style="color:var(--ink-muted);margin:0 0 18px;">${esc((_activeTopicDetail.err && _activeTopicDetail.err.message) || "请求失败，请检查网络后重试。")}</p>
            <button type="button" class="btn btn-primary" id="topic-retry-btn">重新加载</button>
          </div>
        </div>
      `;
      root.querySelector("#topic-error-back").onclick = () => openForumList(true);
      root.querySelector("#topic-retry-btn").onclick = () => {
        _activeTopicDetail.status = "loading";
        renderTopicDetailPage(root);
      };
      return;
    }

    // Render Loaded State
    const topic = _activeTopicDetail.topicData.topic;
    const mount = _activeTopicDetail.topicData.mount || { kind: "discussion" };
    const viewer = _activeTopicDetail.topicData.viewer || {};
    const { liked, count: likeCnt } = _getTopicLikeState(_activeTopicDetail.topicData);
    const { favorited, count: favCnt } = _getTopicFavoriteState(_activeTopicDetail.topicData);
    let forks = mount.kind === "work" ? Number(mount.work?.forks || 0) : 0;
    const unlocked = S.isUnlocked(topic.id, topic);
    const imgs = normalizeTopicImages(topic);
    const canModerateThisBoard = S.canModerateForumBoard ? S.canModerateForumBoard(topic.category) : false;
    const authorProf = S.getCreatorProfile(topic.author) || { honor: { sealClass: "" }, avatarChar: "绘", authorName: topic.authorName || "创作者", totalPublished: 0, totalCheers: 0, topics: [] };
    const boardMods = S.getBoardModerators ? S.getBoardModerators(topic.category) : [];
    const isTopicAuthor = App.state && App.state.loggedIn && App.state.user && App.state.user.username === topic.author;
    const canArbitrate = topic.bounty > 0 && !topic.solved && App.state && App.state.loggedIn && (App.state.user.role === "admin" || App.state.user.role === "operator" || App.state.user.role === "reviewer");

    const modToolbarHtml = canModerateThisBoard
      ? `
        <div id="topic-mod-toolbar" style="background:rgba(31,95,139,0.08);border:1px solid rgba(31,95,139,0.28);border-radius:12px;padding:11px 16px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
          <span style="font-size:13px;font-weight:850;color:#1f5f8b;">🛡️ 前台版务治理工具栏</span>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-sm" data-mod-op="${topic.pinned ? "unpin" : "pin"}">${topic.pinned ? "取消置顶" : "📌 置顶本帖"}</button>
            <button type="button" class="btn btn-sm" data-mod-op="${topic.featured ? "unfeature" : "feature"}">${topic.featured ? "取消精华" : "🌟 设为精华"}</button>
            <select class="hw-select" id="topic-mod-move-select" style="padding:4px 8px;font-size:12px;">
              ${BOARD_DEFS.map((b) => `<option value="${esc(b.key)}" ${b.key === topic.category ? "selected" : ""}>移至：${esc(b.short)}</option>`).join("")}
            </select>
            <button type="button" class="btn btn-sm" id="topic-mod-move-btn">📂 确认移帖</button>
            <button type="button" class="btn btn-sm" data-mod-op="hide" style="color:var(--vermilion);">🙈 隐藏帖子</button>
            <button type="button" class="btn btn-sm" data-mod-op="delete" style="color:var(--vermilion);font-weight:750;">🗑️ 彻底删帖</button>
            ${canArbitrate ? `<button type="button" class="btn btn-sm btn-gold" id="topic-mod-arbitrate-bounty">🏆 仲裁结帖/采纳</button>` : ""}
          </div>
        </div>
      `
      : "";

    const workPost = mount.kind === "work" && mount.work && hasModule("HandrawForumWork", "fromTopic")
      ? window.HandrawForumWork.fromTopic(topic, [mount.work], App.resourceMap, unlocked || S.isStaff?.())
      : null;

    const cardsToRender = [];
    if (topic.sharedCard && topic.sharedCard.title) {
      cardsToRender.push(topic.sharedCard);
    }
    const mountedAssetIds = [...(topic.styles || []), topic.layout].filter(Boolean);
    for (const aid of mountedAssetIds) {
      if (!cardsToRender.some((c) => c.id === aid)) {
        const item = App.resourceMap.get(aid);
        if (item) {
          cardsToRender.push({
            kind: item.kind === "layout" ? "layout" : "style",
            id: item.id,
            title: item.name,
            image: item.image,
            authorName: item.authorName || "Handraw 官方",
            desc: item.description || ""
          });
        }
      }
    }

    const paidSectionHtml =
      topic.price > 0
        ? unlocked
          ? `
            <div style="margin-top:20px;padding:12px 18px;background:var(--jade-wash);border:1px solid #bce3cb;border-radius:12px;display:flex;align-items:center;gap:10px;font-size:13px;font-weight:800;color:var(--jade);">
              <span>✅ 已付费解锁专栏全文（感谢支持原创创作者 @${esc(topic.authorName)}）</span>
            </div>
          `
          : `
            <div class="hw-locked-gate-box" style="padding:28px 24px;margin-top:20px;text-align:center;">
              <div style="font-weight:850;font-size:17px;color:var(--gold);margin-bottom:8px;">
                🔒 此处以下为 10✦ 付费专属核心章节
              </div>
              <p style="margin:0 0 16px;font-size:13px;color:var(--ink-muted);">
                支付 10✦ 积分解锁后续全文（包含核心生图控制词与防翻车交付细节，80% 收益实时转入作者 @${esc(topic.authorName)} 账户）
              </p>
              <button type="button" class="btn btn-primary" id="topic-btn-unlock" style="padding:10px 28px;font-size:14.5px;font-weight:800;border-radius:10px;">
                🔓 立即使用 10✦ 积分解锁全文
              </button>
            </div>
          `
        : "";

    const inlineDrawerHtml =
      FUI.topicInlineDrawer === "share"
        ? S.renderInlineSharePanelHtml("topic", topic)
        : FUI.topicInlineDrawer === "report"
        ? S.renderInlineReportPanelHtml("topic", topic.id, topic.title)
        : "";

    const allTopics = App.state?.topics || [];
    const sameBoardHot = allTopics
      .filter((ot) => ot.id !== topic.id && ot.category === topic.category)
      .slice(0, 4);

    let articleBodyHtml = "";
    if (workPost && hasModule("HandrawForumWork", "render")) {
      articleBodyHtml = window.HandrawForumWork.render(workPost);
    } else if (mount.kind === "style" || mount.kind === "layout") {
      articleBodyHtml = renderResourceMountArticleHtml(mount.kind, mount.resource);
    } else {
      articleBodyHtml = renderEditorialArticleHtml(topic, cardsToRender, unlocked);
    }

    const likeInFlight = _socialInFlight.has(`${topic.id}:like`);
    const collectInFlight = _socialInFlight.has(`${topic.id}:collect`);
    const countsDisplay = `点赞 ${likeCnt} · 收藏 ${favCnt}${mount.kind === "work" ? ` · 做同款 ${forks}` : ""}`;
    const isResourceKind = mount.kind === "style" || mount.kind === "layout";
    const pairedTitle = mount.kind === "style" ? "常搭配的图型" : "常搭配的画风";

    const totalRepliesCount = _activeTopicDetail.replies.length + _activeTopicDetail.pendingReplies.length;

    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-topic-detail-page">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="topic-back-list-btn">← 返回论坛列表</button>
            <span>/</span>
            <button type="button" class="hw-pill" id="topic-crumb-board" style="padding:2px 9px;font-size:11.8px;">${
              mount.kind === "style"
                ? "← 画风频道"
                : mount.kind === "layout"
                ? "← 图型频道"
                : esc(topic.categoryLabel || "社区讨论")
            }</button>
            <span>/</span>
            <strong>帖子正文与楼层回复</strong>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-sm btn-primary" id="topic-new-post-btn">✏️ 发新帖</button>
          </div>
        </div>

        <div class="forum-thread-layout">
          <!-- LEFT MAIN THREAD COLUMN -->
          <div style="display:flex;flex-direction:column;gap:16px;min-width:0;">
            ${modToolbarHtml}

            <article class="forum-thread-article">
              <div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap;">
                ${topic.pinned ? `<span style="background:var(--vermilion);color:#fff;font-size:11.5px;font-weight:800;padding:2px 8px;border-radius:5px;">📌 置顶</span>` : ""}
                ${topic.featured ? `<span style="background:var(--gold);color:#fff;font-size:11.5px;font-weight:800;padding:2px 8px;border-radius:5px;">🌟 精华</span>` : ""}
                <span style="font-size:12.5px;font-weight:800;color:var(--vermilion);">${esc(topic.categoryLabel)}</span>
                ${
                  workPost ? `<span class="forum-format-badge is-visual">作品分享</span>` : isResourceKind ? `<span class="forum-format-badge">${mount.kind === "style" ? "🎨 画风推荐" : "📐 图型推荐"}</span>` : imgs.length > 0
                    ? `<span class="forum-format-badge is-visual">🖼️ ${imgs.length} 图分享帖</span>`
                    : `<span class="forum-format-badge">📝 纯文讨论帖</span>`
                }
                ${
                  topic.bounty > 0
                    ? `<span style="background:${topic.solved ? "var(--jade-wash)" : "var(--vermilion-wash)"};color:${topic.solved ? "var(--jade)" : "var(--vermilion)"};font-size:12px;font-weight:800;padding:2px 9px;border-radius:999px;">${topic.solved ? `✅ 悬赏 ${topic.bounty}✦ 已结` : `💰 悬赏 ${topic.bounty}✦ 待采纳`}</span>`
                    : ""
                }
              </div>

              <h1 class="hw-detail-title">${esc(topic.title)}</h1>
              ${hasModule("HandrawCuration", "topicPanelHtml") ? window.HandrawCuration.topicPanelHtml(topic) : ""}

              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding-bottom:12px;border-bottom:1px solid var(--line-soft);">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--ink-muted);">
                  <button type="button" class="hw-author-chip" data-open-creator="${esc(topic.author)}">
                    <span class="hw-creator-avatar-sm ${esc(authorProf.honor?.sealClass || "")}">${esc(authorProf.avatarChar || "绘")}</span>
                    <strong style="color:var(--ink-strong);">@${esc(topic.authorName || "创作者")}</strong>
                  </button>
                  ${renderModBadgeHtml(topic.author, topic.category)}
                  <span>· 发布于 ${esc(topic.createdAt || "刚刚")} · </span>
                  <span class="topic-counts" id="topic-counts">${esc(countsDisplay)}</span>
                </div>

                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                  <button type="button" class="btn btn-sm ${liked ? "btn-primary" : ""}" id="topic-page-like" ${likeInFlight ? 'disabled aria-busy="true"' : ""}>
                    👍 ${liked ? "已赞" : "点赞"} (${likeCnt})
                  </button>
                  <button type="button" class="btn btn-sm ${favorited ? "btn-primary" : ""}" id="topic-page-collect" ${collectInFlight ? 'disabled aria-busy="true"' : ""}>
                    ${favorited ? "♥ 已收藏" : "♡ 收藏"} (${favCnt})
                  </button>
                  <button type="button" class="btn btn-sm" id="topic-page-scroll-reply">
                    💬 回复 (${totalRepliesCount})
                  </button>
                  <button type="button" class="btn btn-sm" id="topic-page-quote-reply" title="引用主帖正文进行回复">
                    ❝ 引用回复
                  </button>
                  <button type="button" class="btn btn-sm btn-gold ${FUI.topicInlineDrawer === "share" ? "btn-primary" : ""}" id="topic-page-share">📤 分享帖子链接</button>
                  <button type="button" class="btn btn-sm ${FUI.topicInlineDrawer === "report" ? "btn-primary" : ""}" id="topic-page-report" title="举报违规或虚假内容">🚩 举报</button>
                  ${isTopicAuthor && !canModerateThisBoard ? `<button type="button" class="btn btn-sm" id="topic-page-author-delete" style="color:var(--vermilion);" title="删除我发布的这篇帖子">🗑️ 删除帖子</button>` : ""}
                </div>
              </div>

              ${inlineDrawerHtml}

              <!-- Article narrative / mount -->
              <div class="forum-article-body" id="topic-article-body">
                ${articleBodyHtml}
              </div>

              ${paidSectionHtml}

              <!-- Article Bottom Actions Bar -->
              <div class="forum-article-actions" style="margin-top:20px;padding-top:14px;border-top:1px solid var(--line-soft);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
                <div style="font-size:12.5px;color:var(--ink-muted);">
                  欢迎带上具体问题、参考或调整过程一起交流。
                </div>
                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                  <button type="button" class="btn btn-sm" id="topic-page-bottom-reply">
                    💬 回复楼主
                  </button>
                  <button type="button" class="btn btn-sm" id="topic-page-bottom-quote">
                    ❝ 引用楼主正文
                  </button>
                </div>
              </div>
            </article>

            <!-- STANDALONE FLOOR REPLIES & COMPOSER -->
            <section class="hw-detail-section-card" id="topic-replies-section">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
                <div>
                  <h2 style="margin:0;font-size:18.5px;font-family:var(--font-serif);" id="topic-replies-title">💬 回复 (${totalRepliesCount})</h2>
                  <div style="font-size:12.4px;color:var(--ink-muted);margin-top:3px;">可以附上推荐的 #画风 或 #图型 编号，方便继续尝试。</div>
                </div>
                ${
                  topic.bounty > 0 && !topic.solved
                    ? `<span style="font-size:12.5px;font-weight:850;color:var(--vermilion);background:var(--vermilion-wash);padding:4px 10px;border-radius:999px;">💰 本帖托管悬赏 ${topic.bounty}✦ 待楼主采纳结算</span>`
                    : ""
                }
              </div>

              <div id="topic-replies-list" style="display:grid;gap:12px;margin-bottom:18px;">
                ${
                  _activeTopicDetail.replies.length === 0 && _activeTopicDetail.pendingReplies.length === 0
                    ? `<div id="topic-replies-empty" style="padding:28px;text-align:center;color:var(--ink-muted);background:var(--paper-bg);border-radius:10px;">还没有回复，欢迎分享你的想法。</div>`
                    : _activeTopicDetail.replies.map((r, idx) => renderSingleFloorReplyHtml(r, idx, topic)).join("")
                }
              </div>

              ${
                _activeTopicDetail.nextCursor
                  ? `<div id="topic-replies-loadmore-wrap" style="text-align:center;margin-bottom:18px;">
                      <button type="button" class="btn btn-sm" id="topic-load-more-replies-btn">加载更多回复</button>
                    </div>`
                  : ""
              }

              ${
                _activeTopicDetail.pendingReplies.length > 0
                  ? `<div id="topic-pending-replies-wrap" style="margin-bottom:18px;padding:12px 14px;background:var(--paper-bg);border:1px dashed var(--line-strong);border-radius:10px;">
                      <div style="font-size:12.5px;font-weight:750;color:var(--ink-muted);margin-bottom:10px;">你刚发表的回复：</div>
                      <div id="topic-pending-replies-list" style="display:grid;gap:12px;">
                        ${_activeTopicDetail.pendingReplies.map((r, idx) => renderSingleFloorReplyHtml(r, _activeTopicDetail.replies.length + idx, topic)).join("")}
                      </div>
                    </div>`
                  : ""
              }

              <!-- Bottom Reply Composer -->
              <div id="topic-reply-box" style="background:var(--paper-bg);border:1px solid var(--line-strong);border-radius:12px;padding:14px 16px;">
                <div style="font-size:13px;font-weight:800;margin-bottom:8px;">✍️ 发表跟帖回复 / 交流讨论</div>
                <textarea class="hw-textarea" rows="3" id="topic-reply-input" placeholder="写下建议、经验或问题，支持 Ctrl + Enter 发送…"></textarea>
                <div style="display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap;">
                  <button type="button" class="btn btn-primary" id="topic-reply-submit">💬 发布回复</button>
                </div>
              </div>
            </section>
          </div>

          <!-- RIGHT SIDEBAR -->
          <aside style="display:flex;flex-direction:column;gap:14px;min-width:0;max-width:100%;">
            ${
              isResourceKind
                ? `
                  <div class="forum-side-card" id="topic-paired-resources-card" style="min-width:0;max-width:100%;">
                    <div style="font-weight:800;font-size:13.5px;margin-bottom:10px;">🔥 ${esc(pairedTitle)}</div>
                    <div id="topic-paired-resources-container" style="display:grid;gap:8px;min-width:0;max-width:100%;">
                      <div style="color:var(--ink-muted);font-size:12px;">正在加载搭配推荐…</div>
                    </div>
                  </div>
                `
                : `
                  <div class="forum-side-card" style="display:grid;gap:12px;">
                    <div style="font-size:11.5px;font-weight:800;color:var(--ink-muted);letter-spacing:0.04em;">作者</div>
                    <div style="display:flex;gap:12px;align-items:center;">
                      <div class="hw-creator-avatar-sm ${esc(authorProf.honor?.sealClass || "")}" style="width:46px;height:46px;font-size:18px;">${esc(authorProf.avatarChar || "绘")}</div>
                      <div style="min-width:0;">
                        <div style="font-weight:850;font-size:15px;color:var(--ink-strong);">@${esc(authorProf.authorName || topic.authorName || "创作者")}</div>
                      </div>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;text-align:center;background:var(--paper-bg);padding:8px;border-radius:9px;font-size:12px;">
                      <div><strong style="display:block;font-size:15px;color:var(--ink-strong);">${authorProf.totalPublished || 0}</strong><span style="color:var(--ink-muted);">总分享</span></div>
                      <div><strong style="display:block;font-size:15px;color:var(--ink-strong);">${authorProf.totalCheers || 0}</strong><span style="color:var(--ink-muted);">获鼓励</span></div>
                      <div><strong style="display:block;font-size:15px;color:var(--ink-strong);">${(authorProf.topics || []).length}</strong><span style="color:var(--ink-muted);">论坛帖</span></div>
                    </div>
                    <button type="button" class="btn btn-primary btn-sm" style="width:100%;justify-content:center;" data-open-creator="${esc(topic.author)}">
                      🏠 访问 TA 的独立个人主页 ↗
                    </button>
                  </div>
                `
            }

            <div class="forum-side-card">
              <div style="font-size:12px;font-weight:800;color:var(--ink-muted);margin-bottom:8px;">🛡️ 本版值班版主</div>
              <div style="display:grid;gap:6px;">
                ${
                  boardMods.length === 0
                    ? `<div style="font-size:12px;color:var(--ink-muted);">全站管理员共同巡查</div>`
                    : boardMods
                        .map(
                          (m) => `
                            <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;background:var(--paper-bg);border-radius:8px;font-size:12px;">
                              <button type="button" class="hw-author-chip" data-open-creator="${esc(m.username)}" style="padding:1px 6px;">
                                <strong>@${esc(m.displayName || m.username)}</strong>
                              </button>
                              <span style="color:#1f5f8b;font-weight:800;font-size:11px;">${esc(m.title || "版主")}</span>
                            </div>
                          `
                        )
                        .join("")
                }
              </div>
            </div>

            ${
              !isResourceKind && sameBoardHot.length
                ? `
                  <div class="forum-side-card">
                    <div style="font-weight:800;font-size:13.5px;margin-bottom:10px;">🔥 同板块相关讨论</div>
                    <div style="display:grid;gap:9px;">
                      ${sameBoardHot
                        .map(
                          (ot) => `
                            <button type="button" data-switch-topic="${esc(ot.id)}" style="text-align:left;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:9px;padding:9px 11px;cursor:pointer;">
                              <div style="font-size:13px;font-weight:750;color:var(--ink-strong);line-height:1.42;margin-bottom:4px;">${esc(ot.title)}</div>
                              <div style="font-size:11.5px;color:var(--ink-muted);">@${esc(ot.authorName)} · 💬 ${(ot.replies || []).length} 回复</div>
                            </button>
                          `
                        )
                        .join("")}
                    </div>
                  </div>
                `
                : ""
            }
          </aside>
        </div>
      </div>
    `;

    // Bind HandrawCuration
    if (hasModule("HandrawCuration", "bindTopicPanel")) {
      window.HandrawCuration.bindTopicPanel(root, topic);
    }
    if (!topic.author && topic.resourceDiscussion) {
      const authorCard = root.querySelector("aside .forum-side-card");
      if (authorCard && !isResourceKind) authorCard.remove();
    }

    // Navigation buttons
    root.querySelector("#topic-back-list-btn").onclick = () => openForumList(true);
    root.querySelector("#topic-crumb-board").onclick = () => {
      if (mount.kind === "style") {
        window.location.href = S.channelUrl("main", { view: "styles" });
        return;
      }
      if (mount.kind === "layout") {
        window.location.href = S.channelUrl("main", { view: "layouts" });
        return;
      }
      FUI.category = topic.category || "all";
      openForumList(true);
    };
    root.querySelector("#topic-new-post-btn").onclick = () => {
      if (mount.kind === "style" && mount.resource?.code) {
        openComposeView({ category: "assets", style1: mount.resource.code }, true);
      } else if (mount.kind === "layout" && mount.resource?.code) {
        openComposeView({ category: "assets", layout: mount.resource.code }, true);
      } else {
        openComposeView({ category: topic.category || "experience" }, true);
      }
    };

    root.querySelectorAll("[data-open-creator]").forEach((btn) => {
      if (!btn.getAttribute("data-open-creator")) { btn.outerHTML = '<span class="curation-muted">资源讨论</span>'; return; }
      btn.onclick = () => S.goToCreatorProfile(btn.getAttribute("data-open-creator"));
    });
    root.querySelectorAll("[data-switch-topic]").forEach((btn) => {
      btn.onclick = () => openTopicPage(btn.getAttribute("data-switch-topic"), 0);
    });
    root.querySelectorAll("[data-reply-asset]").forEach((btn) => {
      btn.onclick = () => S.goToAssetPage(btn.getAttribute("data-reply-asset"));
    });

    root.querySelectorAll("[data-zoom-img]").forEach((imgEl) => {
      imgEl.onclick = () => {
        const src = imgEl.getAttribute("data-zoom-img") || imgEl.src;
        const fig = imgEl.closest("figure") || imgEl.parentElement;
        const caption = fig?.querySelector("figcaption")?.innerText || imgEl.getAttribute("alt") || "";
        openImageLightboxModal(src, caption);
      };
    });

    root.querySelectorAll("[data-topic-page-img]").forEach((imgEl) => {
      imgEl.onclick = () => openImageLightboxModal(imgEl.src);
    });

    if (workPost && hasModule("HandrawForumWork", "bind")) {
      window.HandrawForumWork.bind(root, workPost);
    }

    // Dynamic Updates for Like & Favorite (Optimistic UI, no refreshFromServer)
    const updateCountsUI = _updateTopicCountsUI;
    const updateLikeBtnUI = _updateTopicLikeBtnUI;
    const updateFavBtnUI = _updateTopicFavBtnUI;

    const isStyleMount = mount.kind === "style";
    const isLayoutMount = mount.kind === "layout";
    const isAssetMount = isStyleMount || isLayoutMount;

    const likeBtn = root.querySelector("#topic-page-like");
    if (likeBtn) {
      likeBtn.onclick = () => {
        const lockKey = `${topic.id}:like`;
        if (_socialInFlight.has(lockKey)) return;
        if (!App.state?.loggedIn) {
          openForumAuthPage("登录后即可点赞！");
          return;
        }
        _socialInFlight.add(lockKey);
        likeBtn.disabled = true;
        likeBtn.setAttribute("aria-busy", "true");

        const reqTopicId = topic.id;
        const reqGen = _activeTopicDetail.gen;
        const currentSeq = (_socialSeq.get(lockKey) || 0) + 1;
        _socialSeq.set(lockKey, currentSeq);
        const reqSeq = currentSeq;

        const curLikeState = _getTopicLikeState(_activeTopicDetail.topicData);
        const oldLiked = curLikeState.liked;
        const oldLikeCnt = curLikeState.count;
        const optimisticLiked = !oldLiked;
        const optimisticLikeCnt = optimisticLiked ? oldLikeCnt + 1 : Math.max(0, oldLikeCnt - 1);

        _setTopicLikeState(_activeTopicDetail.topicData, optimisticLiked, optimisticLikeCnt);
        _updateTopicLikeBtnUI();
        _updateTopicCountsUI();

        const likePayload = isAssetMount
          ? { targetType: isStyleMount ? "style" : "layout", id: mount.resource.code }
          : { targetType: "topic", id: topic.id };

        S.apiJson("/api/interactions/like", {
          method: "POST",
          body: likePayload
        }).then((res) => {
          if (!_activeTopicDetail) {
            _releaseSocialLock(reqTopicId, "like");
            return;
          }
          if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen === reqGen) {
            if (_socialSeq.get(lockKey) === reqSeq) {
              let finalLiked = optimisticLiked;
              if (res && res.liked != null) finalLiked = Boolean(res.liked);
              let finalCount;
              if (isAssetMount) {
                finalCount = Math.max(0, oldLikeCnt + (finalLiked ? 1 : -1));
              } else if (res && res.likes != null) {
                finalCount = Number(res.likes);
              } else {
                finalCount = Math.max(0, oldLikeCnt + (finalLiked ? 1 : -1));
              }
              _setTopicLikeState(_activeTopicDetail.topicData, finalLiked, finalCount);
              _updateTopicLikeBtnUI();
              _updateTopicCountsUI();
              toast(finalLiked ? "👍 已点赞" : "已取消点赞");
            }
            _releaseSocialLock(reqTopicId, "like");
          } else if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen !== reqGen) {
            const calibGen = _activeTopicDetail.gen;
            const calibSeq = reqSeq;
            S.apiJson(`/api/posts/${encodeURIComponent(reqTopicId)}`).then((postRes) => {
              if (postRes && postRes.ok && postRes.topic &&
                  _activeTopicDetail && _activeTopicDetail.id === reqTopicId &&
                  _activeTopicDetail.gen === calibGen &&
                  _socialSeq.get(lockKey) === calibSeq) {
                _applyTopicSocialCalibration(_activeTopicDetail.topicData, postRes, "like");
                _updateTopicLikeBtnUI();
                _updateTopicCountsUI();
              }
            }).catch(() => {})
            .finally(() => {
              _releaseSocialLock(reqTopicId, "like");
            });
          } else {
            _releaseSocialLock(reqTopicId, "like");
          }
        }).catch((err) => {
          if (!_activeTopicDetail) {
            _releaseSocialLock(reqTopicId, "like");
            return;
          }
          if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen === reqGen) {
            _setTopicLikeState(_activeTopicDetail.topicData, oldLiked, oldLikeCnt);
            _updateTopicLikeBtnUI();
            _updateTopicCountsUI();
            toast(`点赞失败：${(err && err.message) || err}`);
            _releaseSocialLock(reqTopicId, "like");
          } else if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen !== reqGen) {
            const calibGen = _activeTopicDetail.gen;
            const calibSeq = reqSeq;
            S.apiJson(`/api/posts/${encodeURIComponent(reqTopicId)}`).then((postRes) => {
              if (postRes && postRes.ok && postRes.topic &&
                  _activeTopicDetail && _activeTopicDetail.id === reqTopicId &&
                  _activeTopicDetail.gen === calibGen &&
                  _socialSeq.get(lockKey) === calibSeq) {
                _applyTopicSocialCalibration(_activeTopicDetail.topicData, postRes, "like");
                _updateTopicLikeBtnUI();
                _updateTopicCountsUI();
              }
            }).catch(() => {})
            .finally(() => {
              _releaseSocialLock(reqTopicId, "like");
            });
          } else {
            _releaseSocialLock(reqTopicId, "like");
          }
        });
      };
    }

    const collectBtn = root.querySelector("#topic-page-collect");
    if (collectBtn) {
      collectBtn.onclick = () => {
        const lockKey = `${topic.id}:collect`;
        if (_socialInFlight.has(lockKey)) return;
        if (!App.state?.loggedIn) {
          openForumAuthPage("登录后即可收藏！");
          return;
        }
        _socialInFlight.add(lockKey);
        collectBtn.disabled = true;
        collectBtn.setAttribute("aria-busy", "true");

        const reqTopicId = topic.id;
        const reqGen = _activeTopicDetail.gen;
        const currentSeq = (_socialSeq.get(lockKey) || 0) + 1;
        _socialSeq.set(lockKey, currentSeq);
        const reqSeq = currentSeq;

        const curFavState = _getTopicFavoriteState(_activeTopicDetail.topicData);
        const oldFav = curFavState.favorited;
        const oldFavCnt = curFavState.count;
        const optimisticFav = !oldFav;
        const optimisticFavCnt = optimisticFav ? oldFavCnt + 1 : Math.max(0, oldFavCnt - 1);

        _setTopicFavoriteState(_activeTopicDetail.topicData, optimisticFav, optimisticFavCnt);
        _updateTopicFavBtnUI();
        _updateTopicCountsUI();

        const collectPayload = isAssetMount
          ? { bucket: isStyleMount ? "styles" : "layouts", targetId: mount.resource.code, id: mount.resource.code, title: mount.resource.name }
          : { bucket: "topics", targetId: topic.id, title: topic.title };

        S.apiJson("/api/collections/toggle", {
          method: "POST",
          body: collectPayload
        }).then((res) => {
          if (!_activeTopicDetail) {
            _releaseSocialLock(reqTopicId, "collect");
            return;
          }
          if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen === reqGen) {
            if (_socialSeq.get(lockKey) === reqSeq) {
              let finalFav = optimisticFav;
              if (res && res.collected != null) finalFav = Boolean(res.collected);
              let finalCount;
              if (isAssetMount) {
                finalCount = Math.max(0, oldFavCnt + (finalFav ? 1 : -1));
              } else if (res && res.favorites != null) {
                finalCount = Number(res.favorites);
              } else {
                finalCount = Math.max(0, oldFavCnt + (finalFav ? 1 : -1));
              }
              _setTopicFavoriteState(_activeTopicDetail.topicData, finalFav, finalCount);
              _updateTopicFavBtnUI();
              _updateTopicCountsUI();
              toast(finalFav ? "♥ 已收藏" : "已取消收藏");
            }
            _releaseSocialLock(reqTopicId, "collect");
          } else if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen !== reqGen) {
            const calibGen = _activeTopicDetail.gen;
            const calibSeq = reqSeq;
            S.apiJson(`/api/posts/${encodeURIComponent(reqTopicId)}`).then((postRes) => {
              if (postRes && postRes.ok && postRes.topic &&
                  _activeTopicDetail && _activeTopicDetail.id === reqTopicId &&
                  _activeTopicDetail.gen === calibGen &&
                  _socialSeq.get(lockKey) === calibSeq) {
                _applyTopicSocialCalibration(_activeTopicDetail.topicData, postRes, "collect");
                _updateTopicFavBtnUI();
                _updateTopicCountsUI();
              }
            }).catch(() => {})
            .finally(() => {
              _releaseSocialLock(reqTopicId, "collect");
            });
          } else {
            _releaseSocialLock(reqTopicId, "collect");
          }
        }).catch((err) => {
          if (!_activeTopicDetail) {
            _releaseSocialLock(reqTopicId, "collect");
            return;
          }
          if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen === reqGen) {
            _setTopicFavoriteState(_activeTopicDetail.topicData, oldFav, oldFavCnt);
            _updateTopicFavBtnUI();
            _updateTopicCountsUI();
            toast(`收藏失败：${(err && err.message) || err}`);
            _releaseSocialLock(reqTopicId, "collect");
          } else if (_activeTopicDetail.id === reqTopicId && _activeTopicDetail.gen !== reqGen) {
            const calibGen = _activeTopicDetail.gen;
            const calibSeq = reqSeq;
            S.apiJson(`/api/posts/${encodeURIComponent(reqTopicId)}`).then((postRes) => {
              if (postRes && postRes.ok && postRes.topic &&
                  _activeTopicDetail && _activeTopicDetail.id === reqTopicId &&
                  _activeTopicDetail.gen === calibGen &&
                  _socialSeq.get(lockKey) === calibSeq) {
                _applyTopicSocialCalibration(_activeTopicDetail.topicData, postRes, "collect");
                _updateTopicFavBtnUI();
                _updateTopicCountsUI();
              }
            }).catch(() => {})
            .finally(() => {
              _releaseSocialLock(reqTopicId, "collect");
            });
          } else {
            _releaseSocialLock(reqTopicId, "collect");
          }
        });
      };
    }

    const scrollReplyBtn = root.querySelector("#topic-page-scroll-reply");
    if (scrollReplyBtn) {
      scrollReplyBtn.onclick = () => {
        const sec = root.querySelector("#topic-replies-section");
        if (sec) sec.scrollIntoView({ behavior: getScrollBehavior(), block: "start" });
        const inp = root.querySelector("#topic-reply-input");
        if (inp) setTimeout(() => inp.focus(), 180);
      };
    }

    const bottomReplyBtn = root.querySelector("#topic-page-bottom-reply");
    if (bottomReplyBtn) {
      bottomReplyBtn.onclick = () => {
        const inp = root.querySelector("#topic-reply-input");
        if (inp) {
          inp.scrollIntoView({ behavior: getScrollBehavior(), block: "center" });
          inp.focus();
        }
      };
    }

    const quoteReplyBtn = root.querySelector("#topic-page-quote-reply");
    if (quoteReplyBtn) {
      quoteReplyBtn.onclick = () => {
        const inp = root.querySelector("#topic-reply-input");
        if (inp) {
          const authorText = topic.authorName || topic.author || "楼主";
          inp.value = `引用 @${authorText} 楼主正文：\n> ` + (inp.value || "");
          inp.scrollIntoView({ behavior: getScrollBehavior(), block: "center" });
          inp.focus();
        }
      };
    }

    const bottomQuoteBtn = root.querySelector("#topic-page-bottom-quote");
    if (bottomQuoteBtn) {
      bottomQuoteBtn.onclick = () => {
        const inp = root.querySelector("#topic-reply-input");
        if (inp) {
          const authorText = topic.authorName || topic.author || "楼主";
          inp.value = `引用 @${authorText} 楼主正文：\n> ` + (inp.value || "");
          inp.scrollIntoView({ behavior: getScrollBehavior(), block: "center" });
          inp.focus();
        }
      };
    }

    root.querySelector("#topic-page-share").onclick = () => {
      FUI.topicInlineDrawer = FUI.topicInlineDrawer === "share" ? "" : "share";
      renderForum();
    };
    root.querySelector("#topic-page-report").onclick = () => {
      if (!App.state?.loggedIn) {
        openForumAuthPage("登录后即可参与社区内容自治举报反馈", () => {
          FUI.topicInlineDrawer = "report";
          renderForum();
        });
        return;
      }
      FUI.topicInlineDrawer = FUI.topicInlineDrawer === "report" ? "" : "report";
      renderForum();
    };

    if (FUI.topicInlineDrawer === "share") {
      S.bindInlineSharePanel(root, "topic", topic, () => {
        FUI.topicInlineDrawer = "";
        renderForum();
      });
    } else if (FUI.topicInlineDrawer === "report") {
      S.bindInlineReportPanel(root, "topic", topic.id, () => {
        FUI.topicInlineDrawer = "";
        renderForum();
      });
    }

    // Mod Toolbar Actions
    root.querySelectorAll("[data-mod-op]").forEach((btn) => {
      btn.onclick = async () => {
        const op = btn.getAttribute("data-mod-op");
        if (op === "delete") {
          if (!confirm("确定要彻底删除该帖子吗？此操作将一并删除所有楼层回复，不可撤销。")) return;
        }
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, op }
          });
          if (op === "hide") {
            toast("🛡️ 版务操作生效：已隐藏该违规帖子");
            openForumList(true);
          } else if (op === "delete") {
            toast("🛡️ 帖子已彻底删除");
            openForumList(true);
          } else {
            toast("🛡️ 版务操作已生效！");
            _activeTopicDetail.status = "loading";
            renderTopicDetailPage(root);
          }
        } catch (err) {
          toast(`版务操作失败：${err.message}`);
        }
      };
    });

    const authorDelBtn = root.querySelector("#topic-page-author-delete");
    if (authorDelBtn) {
      authorDelBtn.onclick = async () => {
        if (!confirm("确定要删除您发布的这篇帖子吗？此操作不可撤销。")) return;
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, op: "delete" }
          });
          toast("您的帖子已成功删除");
          openForumList(true);
        } catch (err) {
          toast(`删帖失败：${err.message}`);
        }
      };
    }

    const moveBtn = root.querySelector("#topic-mod-move-btn");
    if (moveBtn) {
      moveBtn.onclick = async () => {
        const targetCategory = root.querySelector("#topic-mod-move-select").value;
        if (targetCategory === topic.category) {
          toast("当前已在该板块");
          return;
        }
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, op: "move", targetCategory }
          });
          toast("🛡️ 已将该帖移动至目标板块！");
          _activeTopicDetail.status = "loading";
          renderTopicDetailPage(root);
        } catch (err) {
          toast(`移帖失败：${err.message}`);
        }
      };
    }

    const arbitrateBtn = root.querySelector("#topic-mod-arbitrate-bounty");
    if (arbitrateBtn) {
      arbitrateBtn.onclick = () => {
        const reps = [..._activeTopicDetail.replies, ..._activeTopicDetail.pendingReplies];
        if (!reps.length) {
          toast("该悬赏帖暂无回复可供仲裁采纳", "warning");
          return;
        }
        const repSummary = reps.map((r, i) => `#${i + 1}楼 @${r.name || r.user || r.author}: ${(r.text || "").slice(0, 30)}`).join("\n");
        const chosenStr = prompt(`请输入要采纳的楼层编号(1 到 ${reps.length})：\n\n${repSummary}`, "1");
        if (!chosenStr) return;
        const floorIdx = parseInt(chosenStr, 10) - 1;
        if (isNaN(floorIdx) || floorIdx < 0 || floorIdx >= reps.length) {
          toast("输入的楼层编号无效", "warning");
          return;
        }
        const chosenReply = reps[floorIdx];
        if (!confirm(`确定要代表社区运营将 ${topic.bounty} 悬赏积分仲裁结算给 @${chosenReply.name || chosenReply.user || chosenReply.author} 吗？`)) return;
        S.apiJson(`/api/admin/topics/${topic.id}/moderate`, {
          method: "POST",
          body: { action: "settle_bounty", replyId: chosenReply.id, reason: "管理人员前台仲裁采纳悬赏" }
        }).then(async (res) => {
          if (!res.ok) throw new Error(res.error || "仲裁失败");
          topic.solved = true;
          chosenReply.accepted = true;
          if (_activeTopicDetail.topicData?.topic) {
            _activeTopicDetail.topicData.topic.solved = true;
          }
          toast(`🏆 悬赏仲裁采纳成功！${topic.bounty} 积分已发放给 @${chosenReply.name || chosenReply.user || chosenReply.author}`);
          renderTopicDetailPage(root);
        }).catch((err) => toast("仲裁失败：" + (err.message || err)));
      };
    }

    const unlockBtn = root.querySelector("#topic-btn-unlock");
    if (unlockBtn) {
      unlockBtn.onclick = () => {
        S.unlockWithCredits(topic.id, topic.price, topic.title, topic.authorName, () => {
          _activeTopicDetail.status = "loading";
          renderTopicDetailPage(root);
        });
      };
    }

    // Resource Mount - copy button & related works & paired resources
    if (mount.kind === "style" || mount.kind === "layout") {
      const bindStampBtn = (btnId, stampLabel) => {
        const btn = root.querySelector(btnId);
        if (!btn || !mount.resource) return;
        btn.onclick = () => {
          if (!App.state?.loggedIn) {
            openForumAuthPage("登录后即可盖印章！");
            return;
          }
          const viewerStamps = mount.resource.viewerStamps || _activeTopicDetail?.topicData?.viewer?.stamps || [];
          if (viewerStamps.includes(stampLabel) || btn.classList.contains("is-active")) {
            toast("已盖过此印章");
            return;
          }
          viewerStamps.push(stampLabel);
          mount.resource.viewerStamps = viewerStamps;
          if (_activeTopicDetail?.topicData?.viewer) {
            _activeTopicDetail.topicData.viewer.stamps = viewerStamps;
          }
          if (!mount.resource.stampCounts) mount.resource.stampCounts = {};
          const curCount = (mount.resource.stampCounts[stampLabel] || 0) + 1;
          mount.resource.stampCounts[stampLabel] = curCount;
          btn.classList.add("is-active");
          btn.innerHTML = `${stampLabel === "超实用配方" ? "🎯 超实用配方" : "✨ 审美在线"} (${curCount})`;

          S.apiJson("/api/interactions/cheer", {
            method: "POST",
            body: { targetType: "asset", targetId: mount.resource.code, stampLabel: stampLabel, stamp: stampLabel }
          }).then((res) => {
            if (res && res.firstCheerReward) {
              toast(`🎯 盖章成功！首次盖章获得 ${res.firstCheerReward}✦ 积分奖励`);
              if (App.state?.user) App.state.user.credits = (App.state.user.credits || 0) + res.firstCheerReward;
            } else {
              toast("🎯 盖章成功！");
            }
          }).catch((err) => {
            const idx = viewerStamps.indexOf(stampLabel);
            if (idx >= 0) viewerStamps.splice(idx, 1);
            mount.resource.stampCounts[stampLabel] = Math.max(0, curCount - 1);
            btn.classList.remove("is-active");
            btn.innerHTML = `${stampLabel === "超实用配方" ? "🎯 超实用配方" : "✨ 审美在线"} (${mount.resource.stampCounts[stampLabel]})`;
            toast(`盖章失败：${(err && err.message) || err}`);
          });
        };
      };

      bindStampBtn("#topic-stamp-recipe", "超实用配方");
      bindStampBtn("#topic-stamp-aesthetic", "审美在线");

      const tipBtn = root.querySelector("#topic-stamp-tip-btn");
      if (tipBtn && mount.resource) {
        tipBtn.onclick = () => {
          if (!App.state?.loggedIn) {
            openForumAuthPage("登录后即可赞赏支持作者！");
            return;
          }
          const author = mount.resource.authorName || mount.resource.author || "创作者";
          if (!confirm(`赞赏 2✦ 给 @${author}，不会解锁任何内容。确定赞赏吗？`)) return;
          tipBtn.disabled = true;
          S.apiJson("/api/interactions/tip", {
            method: "POST",
            body: { targetType: "asset", targetId: mount.resource.code, amount: 2 }
          }).then((res) => {
            if (res && res.credits != null && App.state?.user) {
              App.state.user.credits = res.credits;
            }
            toast(`🎁 赞赏成功！已向 @${author} 送出 2✦ 积分`);
            mount.resource.tips = (mount.resource.tips || 0) + 2;
          }).catch((err) => {
            toast(`赞赏失败：${(err && err.message) || err}`);
          }).finally(() => {
            tipBtn.disabled = false;
          });
        };
      }

      const copyDefBtn = root.querySelector("#resource-copy-def-btn");
      if (copyDefBtn && mount.resource?.definition) {
        copyDefBtn.onclick = () => {
          const text = String(mount.resource.definition || "");
          if (navigator?.clipboard?.writeText) {
            navigator.clipboard.writeText(text)
              .then(() => toast("定义已复制"))
              .catch(() => toast("复制失败，请手动选择复制"));
          } else {
            toast("定义已复制");
          }
        };
      }

      const resUnlockBtn = root.querySelector("#resource-btn-unlock");
      if (resUnlockBtn) {
        resUnlockBtn.onclick = () => {
          if (!App.state?.loggedIn) {
            openForumAuthPage("登录后即可解锁资源！");
            return;
          }
          resUnlockBtn.disabled = true;
          S.apiJson("/api/unlocks", {
            method: "POST",
            body: { targetId: mount.resource.code, targetType: "asset" }
          }).then(() => {
            toast("🔓 解锁成功");
            _activeTopicDetail.status = "loading";
            renderTopicDetailPage(root);
          }).catch((err) => {
            toast("解锁失败：" + ((err && err.message) || "未知错误"));
            resUnlockBtn.disabled = false;
          });
        };
      }

      // Fetch related works
      const worksContainer = root.querySelector("#topic-related-works-container");
      if (worksContainer && mount.resource?.code) {
        S.apiJson(`/api/forum/resources/${encodeURIComponent(mount.kind)}/${encodeURIComponent(mount.resource.code)}/related?tab=works&limit=8`)
          .then((res) => {
            const items = (res && res.items) || [];
            if (!items.length) {
              const useUrl = mount.kind === "style"
                ? S.channelUrl("studio", { style: mount.resource.code })
                : S.channelUrl("studio", { layout: mount.resource.code });
              worksContainer.innerHTML = `<div style="padding:16px;text-align:center;color:var(--ink-muted);font-size:13px;background:var(--paper-bg);border-radius:8px;">暂无使用此资源创作的作品 · <a href="${esc(useUrl)}" class="btn-link" style="color:var(--vermilion);text-decoration:none;font-weight:700;">用它做第一张 ↗</a></div>`;
              return;
            }
            worksContainer.innerHTML = `
              <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(130px, 1fr));gap:12px;min-width:0;max-width:100%;">
                ${items.slice(0, 8).map((w) => `
                  <a href="${esc(S.channelUrl("main", { view: "work", id: w.id }))}" style="text-decoration:none;color:inherit;display:block;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:8px;overflow:hidden;min-width:0;max-width:100%;">
                    <div style="aspect-ratio:1;background:var(--paper-deep);overflow:hidden;">
                      <img src="${esc(w.image || (w.images && w.images[0]) || "")}" alt="${esc(w.title || "")}" style="width:100%;height:100%;object-fit:cover;" />
                    </div>
                    <div style="padding:6px 8px;min-width:0;">
                      <div style="font-size:12px;font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;overflow-wrap:anywhere;">${esc(w.title || "作品")}</div>
                      <div style="font-size:11px;color:var(--ink-muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">@${esc(w.authorName || w.author || "")}</div>
                    </div>
                  </a>
                `).join("")}
              </div>
            `;
          })
          .catch(() => {
            worksContainer.innerHTML = `<div style="color:var(--ink-muted);font-size:13px;">加载相关作品失败</div>`;
          });
      }

      // Fetch paired resources
      const pairedContainer = root.querySelector("#topic-paired-resources-container");
      if (pairedContainer && mount.resource?.code) {
        const pairedTab = mount.kind === "style" ? "layouts" : "styles";
        S.apiJson(`/api/forum/resources/${encodeURIComponent(mount.kind)}/${encodeURIComponent(mount.resource.code)}/related?tab=${pairedTab}&limit=6`)
          .then((res) => {
            const items = (res && res.items) || [];
            if (!items.length) {
              pairedContainer.innerHTML = `<div style="color:var(--ink-muted);font-size:12px;padding:8px 0;">暂无搭配推荐</div>`;
              return;
            }
            pairedContainer.innerHTML = items.slice(0, 6).map((it) => `
              <a href="${esc(S.channelUrl("main", { view: "asset", id: it.id }))}" style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:8px;text-decoration:none;color:inherit;min-width:0;max-width:100%;">
                ${it.image ? `<img src="${esc(it.image)}" alt="${esc(it.name || it.title || it.id)}" style="width:36px;height:36px;border-radius:6px;object-fit:cover;flex-shrink:0;" />` : ""}
                <div style="min-width:0;flex:1;overflow:hidden;">
                  <div style="font-size:12.5px;font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;overflow-wrap:anywhere;">${esc(it.name || it.title || it.id)}</div>
                  <div style="font-size:11px;color:var(--vermilion);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">#${esc(it.id)}</div>
                </div>
              </a>
            `).join("");
          })
          .catch(() => {
            pairedContainer.innerHTML = `<div style="color:var(--ink-muted);font-size:12px;">加载搭配推荐失败</div>`;
          });
      }
    }

    // Delegated click handler on floor replies (R6 + R3)
    const handleFloorAction = async (e) => {
      const btn = e.target.closest("button, a, [data-open-creator]");
      if (!btn) return;

      const replyFloor = btn.getAttribute("data-reply-floor");
      if (replyFloor) {
        const name = btn.getAttribute("data-reply-name");
        const repInp = root.querySelector("#topic-reply-input");
        if (repInp) {
          repInp.value = `@${name} #${replyFloor}楼 ` + (repInp.value || "");
          repInp.scrollIntoView({ behavior: getScrollBehavior(), block: "center" });
          repInp.focus();
        }
        return;
      }

      const quoteFloor = btn.getAttribute("data-quote-floor");
      if (quoteFloor) {
        const user = btn.getAttribute("data-reply-user");
        const name = btn.getAttribute("data-reply-name");
        const repInp = root.querySelector("#topic-reply-input");
        if (repInp) {
          repInp.value = `回复 #${quoteFloor} 楼 @${name || user}：\n> ` + (repInp.value || "");
          repInp.scrollIntoView({ behavior: getScrollBehavior(), block: "center" });
          repInp.focus();
        }
        return;
      }

      const openCreator = btn.getAttribute("data-open-creator");
      if (openCreator) {
        S.goToCreatorProfile(openCreator);
        return;
      }

      const acceptRid = btn.getAttribute("data-accept-reply");
      if (acceptRid) {
        if (!App.state?.loggedIn) {
          openForumAuthPage("登录后即可采纳最佳调优方案！");
          return;
        }
        try {
          const res = await S.apiJson(`/api/forum/topics/${encodeURIComponent(topic.id)}/accept-bounty`, {
            method: "POST",
            body: { replyId: acceptRid }
          });
          topic.solved = true;
          if (_activeTopicDetail.topicData?.topic) {
            _activeTopicDetail.topicData.topic.solved = true;
          }
          const allReps = [..._activeTopicDetail.replies, ..._activeTopicDetail.pendingReplies];
          const rep = allReps.find((x) => x.id === acceptRid);
          if (rep) rep.accepted = true;
          toast(`🏆 已采纳 @${res.winnerName || (rep && (rep.name || rep.user || rep.author))} 的调优方案，托管的 ${res.bounty || topic.bounty}✦ 悬赏金已实时结算入账！`);
          renderTopicDetailPage(root);
        } catch (err) {
          toast(`采纳失败：${err.message}`);
        }
        return;
      }

      const delRid = btn.getAttribute("data-del-reply");
      if (delRid) {
        if (!confirm("确定要删除这条回复吗？此操作不可撤销。")) return;
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, replyId: delRid, op: "delete_reply" }
          });
          _activeTopicDetail.replies = _activeTopicDetail.replies.filter((x) => x.id !== delRid);
          _activeTopicDetail.pendingReplies = _activeTopicDetail.pendingReplies.filter((x) => x.id !== delRid);
          toast("回复已成功删除");
          renderTopicDetailPage(root);
        } catch (err) {
          toast(`删除回复失败：${err.message}`);
        }
        return;
      }

      const hideRid = btn.getAttribute("data-hide-reply");
      if (hideRid) {
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, replyId: hideRid, op: "hide_reply" }
          });
          _activeTopicDetail.replies = _activeTopicDetail.replies.filter((x) => x.id !== hideRid);
          _activeTopicDetail.pendingReplies = _activeTopicDetail.pendingReplies.filter((x) => x.id !== hideRid);
          toast("🛡️ 已隐藏该条违规回复");
          renderTopicDetailPage(root);
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
        return;
      }
    };

    const repListEl = root.querySelector("#topic-replies-list");
    if (repListEl) repListEl.onclick = handleFloorAction;
    const pendListEl = root.querySelector("#topic-pending-replies-list");
    if (pendListEl) pendListEl.onclick = handleFloorAction;

    // Load More Replies Pagination (R7: de-duplicate & chronological order)
    const loadMoreBtn = root.querySelector("#topic-load-more-replies-btn");
    if (loadMoreBtn) {
      loadMoreBtn.onclick = () => {
        if (!_activeTopicDetail.nextCursor) return;
        loadMoreBtn.disabled = true;
        loadMoreBtn.textContent = "正在加载…";
        S.apiJson(`/api/posts/${encodeURIComponent(topic.id)}/replies?limit=20&cursor=${encodeURIComponent(_activeTopicDetail.nextCursor)}`)
          .then((res) => {
            const newItems = (res && res.items) || [];
            _activeTopicDetail.nextCursor = (res && res.nextCursor) || null;

            // De-duplicate against existing replies
            const seenIds = new Set(_activeTopicDetail.replies.map((r) => r.id));
            const freshItems = newItems.filter((r) => !seenIds.has(r.id));

            // Also check if any item is in pendingReplies, remove from pendingReplies
            if (_activeTopicDetail.pendingReplies.length > 0) {
              const freshIds = new Set(freshItems.map((r) => r.id));
              _activeTopicDetail.pendingReplies = _activeTopicDetail.pendingReplies.filter((r) => !freshIds.has(r.id));
            }

            const currentCount = _activeTopicDetail.replies.length;
            _activeTopicDetail.replies.push(...freshItems);

            const listEl = root.querySelector("#topic-replies-list");
            if (listEl) {
              const emptyEl = listEl.querySelector("#topic-replies-empty");
              if (emptyEl) emptyEl.remove();
              freshItems.forEach((r, i) => {
                const div = document.createElement("div");
                div.innerHTML = renderSingleFloorReplyHtml(r, currentCount + i, topic);
                const child = div.firstElementChild;
                if (child) listEl.appendChild(child);
              });
            }

            if (!_activeTopicDetail.nextCursor) {
              const loadWrap = root.querySelector("#topic-replies-loadmore-wrap");
              if (loadWrap) loadWrap.remove();

              // Merge pending replies if any
              if (_activeTopicDetail.pendingReplies.length > 0) {
                const remainingIds = new Set(_activeTopicDetail.replies.map((r) => r.id));
                const remainingPending = _activeTopicDetail.pendingReplies.filter((r) => !remainingIds.has(r.id));
                const pendCount = _activeTopicDetail.replies.length;
                _activeTopicDetail.replies.push(...remainingPending);
                _activeTopicDetail.pendingReplies = [];
                if (listEl) {
                  remainingPending.forEach((r, i) => {
                    const div = document.createElement("div");
                    div.innerHTML = renderSingleFloorReplyHtml(r, pendCount + i, topic);
                    const child = div.firstElementChild;
                    if (child) listEl.appendChild(child);
                  });
                }
              }
            } else {
              loadMoreBtn.disabled = false;
              loadMoreBtn.textContent = "加载更多回复";
            }

            // Unconditionally update pending replies wrap
            const pendWrap = root.querySelector("#topic-pending-replies-wrap");
            if (_activeTopicDetail.pendingReplies.length === 0) {
              if (pendWrap) pendWrap.remove();
            } else {
              const pendList = root.querySelector("#topic-pending-replies-list");
              if (pendList) {
                pendList.innerHTML = _activeTopicDetail.pendingReplies
                  .map((r, i) => renderSingleFloorReplyHtml(r, _activeTopicDetail.replies.length + i, topic))
                  .join("");
              }
            }

            const titleEl = root.querySelector("#topic-replies-title");
            if (titleEl) {
              titleEl.textContent = `💬 回复 (${_activeTopicDetail.replies.length + _activeTopicDetail.pendingReplies.length})`;
            }
            const scrollRepBtn = root.querySelector("#topic-page-scroll-reply");
            if (scrollRepBtn) {
              scrollRepBtn.textContent = `💬 回复 (${_activeTopicDetail.replies.length + _activeTopicDetail.pendingReplies.length})`;
            }
          })
          .catch((err) => {
            loadMoreBtn.disabled = false;
            loadMoreBtn.textContent = "加载更多回复";
            toast(`加载回复失败：${(err && err.message) || err}`);
          });
      };
    }

    // Submit Reply
    const repInp = root.querySelector("#topic-reply-input");
    const submitReply = async () => {
      if (!App.state?.loggedIn) {
        openForumAuthPage("登录后即可参与社区讨论并赢取悬赏积分！");
        return;
      }
      const txt = (repInp?.value || "").trim();
      if (!txt) {
        toast("请输入回复内容");
        return;
      }
      const submitBtn = root.querySelector("#topic-reply-submit");
      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await S.apiJson(`/api/forum/topics/${encodeURIComponent(topic.id)}/replies`, {
          method: "POST",
          body: { text: txt, mountedStyle: "", mountedLayout: "" }
        });

        const user = App.state.user || {};
        const newRep = {
          id: res.replyId || `rep_${Date.now()}`,
          topicId: topic.id,
          author: user.username || "me",
          authorName: user.name || user.display_name || user.username || "创作者",
          time: "刚刚",
          text: txt,
          likes: 0,
          accepted: false
        };

        if (_activeTopicDetail.nextCursor) {
          // Pagination in progress, put in pendingReplies so order remains strictly chronological
          _activeTopicDetail.pendingReplies.push(newRep);

          // Append to pending replies wrap or create it
          let pendWrap = root.querySelector("#topic-pending-replies-wrap");
          let pendList = root.querySelector("#topic-pending-replies-list");
          if (!pendWrap) {
            pendWrap = document.createElement("div");
            pendWrap.id = "topic-pending-replies-wrap";
            pendWrap.style.cssText = "margin-bottom:18px;padding:12px 14px;background:var(--paper-bg);border:1px dashed var(--line-strong);border-radius:10px;";
            pendWrap.innerHTML = `
              <div style="font-size:12.5px;font-weight:750;color:var(--ink-muted);margin-bottom:10px;">你刚发表的回复：</div>
              <div id="topic-pending-replies-list" style="display:grid;gap:12px;"></div>
            `;
            const box = root.querySelector("#topic-reply-box");
            if (box && box.parentNode) {
              box.parentNode.insertBefore(pendWrap, box);
            }
            pendList = pendWrap.querySelector("#topic-pending-replies-list");
            if (pendList) pendList.onclick = handleFloorAction;
          }
          if (pendList) {
            const div = document.createElement("div");
            div.innerHTML = renderSingleFloorReplyHtml(newRep, _activeTopicDetail.replies.length + _activeTopicDetail.pendingReplies.length - 1, topic);
            const child = div.firstElementChild;
            if (child) pendList.appendChild(child);
          }
        } else {
          _activeTopicDetail.replies.push(newRep);
          const listEl = root.querySelector("#topic-replies-list");
          if (listEl) {
            const emptyEl = listEl.querySelector("#topic-replies-empty");
            if (emptyEl) emptyEl.remove();
            const div = document.createElement("div");
            div.innerHTML = renderSingleFloorReplyHtml(newRep, _activeTopicDetail.replies.length - 1, topic);
            const child = div.firstElementChild;
            if (child) listEl.appendChild(child);
          }
        }

        const titleEl = root.querySelector("#topic-replies-title");
        if (titleEl) {
          titleEl.textContent = `💬 回复 (${_activeTopicDetail.replies.length + _activeTopicDetail.pendingReplies.length})`;
        }
        const scrollRepBtn = root.querySelector("#topic-page-scroll-reply");
        if (scrollRepBtn) {
          scrollRepBtn.textContent = `💬 回复 (${_activeTopicDetail.replies.length + _activeTopicDetail.pendingReplies.length})`;
        }

        if (repInp) repInp.value = "";
        toast(res.rewarded > 0 ? `🎉 回复已发布！获得 +${res.rewarded}✦ 互助积分` : "🎉 回复已发布！");
      } catch (err) {
        toast(`回复失败：${(err && err.message) || err}`);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    };

    root.querySelector("#topic-reply-submit").onclick = submitReply;
    if (repInp) {
      repInp.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          submitReply();
        }
      });
    }

    // Check focus=comment query parameter on load
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.get("focus") === "comment") {
      setTimeout(() => {
        const sec = root.querySelector("#topic-replies-section");
        if (sec) sec.scrollIntoView({ behavior: getScrollBehavior(), block: "start" });
        const inp = root.querySelector("#topic-reply-input");
        if (inp) inp.focus();
      }, 120);
    }
  }

  /* ======================== 5. TOPIC CARD & FORUM LIST STREAM ======================== */
  function renderTopicCard(t) {
    const liked = S.isLiked("topic", t.id);
    const likeCnt = S.getLikeCount("topic", t);
    const collected = S.isCollected("topics", t.id);
    const favCnt = S.getFavoriteCount("topics", t);
    const unlocked = S.isUnlocked(t.id, t);
    const imgs = normalizeTopicImages(t);
    const imgCount = imgs.length;
    const modBadge = renderModBadgeHtml(t.author, t.category);
    const canDel = S.canDeleteTopic ? S.canDeleteTopic(t) : (App.state.loggedIn && App.state.user && t.author === App.state.user.username);
    const canMod = S.canModerateForumBoard ? S.canModerateForumBoard(t.category) : false;

    const metaRowHtml = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:7px;">
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          ${t.pinned ? `<span style="background:var(--vermilion);color:#fff;font-size:11px;font-weight:800;padding:1px 7px;border-radius:4px;">📌 置顶</span>` : ""}
          ${t.featured ? `<span style="background:var(--gold);color:#fff;font-size:11px;font-weight:800;padding:1px 7px;border-radius:4px;">🌟 精华</span>` : ""}
          <span style="font-size:12px;font-weight:800;color:var(--vermilion);">${esc(t.categoryLabel)}</span>
          ${
            imgCount > 0
              ? `<span class="forum-format-badge is-visual">🖼️ ${imgCount > 1 ? `${imgCount} 图分享` : "图文分享"}</span>`
              : `<span class="forum-format-badge">📝 纯文讨论</span>`
          }
          ${
            t.price > 0
              ? `<span style="background:var(--gold-wash);border:1px solid var(--gold-border);color:var(--gold);font-size:11.5px;font-weight:800;padding:1px 7px;border-radius:999px;">${unlocked ? "💎 干货已解锁" : `💎 ${t.price} 积分解锁全文`}</span>`
              : ""
          }
          ${
            t.bounty > 0
              ? `<span style="background:${t.solved ? "var(--jade-wash)" : "var(--vermilion-wash)"};color:${t.solved ? "var(--jade)" : "var(--vermilion)"};font-size:11.5px;font-weight:800;padding:1px 8px;border-radius:999px;">${t.solved ? `✅ 悬赏 ${t.bounty}✦ 已结` : `💰 悬赏 ${t.bounty} 积分待采纳`}</span>`
              : ""
          }
        </div>
        <span style="font-size:12px;color:var(--ink-muted);">
          <button type="button" class="hw-author-chip" data-card-creator="${esc(t.author)}" style="padding:1px 7px;font-size:12px;">@${esc(t.authorName)}</button>
          ${modBadge} · ${esc(t.createdAt)}
        </span>
      </div>
    `;

    let bodyAndMediaHtml = "";
    const cleanSnippet = stripHtmlToSnippet(t.summary || t.body, 140);

    if (imgCount === 0) {
      bodyAndMediaHtml = `
        ${metaRowHtml}
        <h2 style="margin:0 0 7px;font-size:17px;line-height:1.42;">${esc(t.title)}</h2>
        <p style="margin:0 0 11px;font-size:13.6px;color:var(--ink-body);line-height:1.62;">${esc(cleanSnippet)}</p>
      `;
    } else if (imgCount === 1) {
      const im = imgs[0];
      bodyAndMediaHtml = `
        <div class="forum-card-split">
          <div style="min-width:0;">
            ${metaRowHtml}
            <h2 style="margin:0 0 7px;font-size:17px;line-height:1.4;">${esc(t.title)}</h2>
            <p style="margin:0;font-size:13.5px;color:var(--ink-body);line-height:1.58;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${esc(cleanSnippet)}</p>
          </div>
          <div class="forum-split-thumb" data-open-topic-img="0">
            <img data-hw-src="${esc(im.url)}" alt="${esc(im.tag || t.title)}" loading="lazy" />
            ${im.tag ? `<span class="forum-thumb-tag">${esc(im.tag)}</span>` : ""}
          </div>
        </div>
      `;
    } else {
      const shownImgs = imgs.slice(0, 4);
      const extraCount = imgs.length - shownImgs.length;
      const stripColClass = shownImgs.length === 2 ? "cols-2" : shownImgs.length === 4 ? "cols-4" : "";
      bodyAndMediaHtml = `
        ${metaRowHtml}
        <h2 style="margin:0 0 6px;font-size:17px;line-height:1.4;">${esc(t.title)}</h2>
        <p style="margin:0 0 8px;font-size:13.5px;color:var(--ink-body);line-height:1.56;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">${esc(cleanSnippet)}</p>
        <div class="forum-media-strip ${stripColClass}">
          ${shownImgs
            .map(
              (im, idx) => `
                <div class="forum-media-item" data-open-topic-img="${idx}">
                  <img data-hw-src="${esc(im.url)}" alt="${esc(im.tag || t.title)}" loading="lazy" />
                  ${im.tag ? `<span class="forum-thumb-tag">${esc(im.tag)}</span>` : ""}
                  ${
                    idx === shownImgs.length - 1 && extraCount > 0
                      ? `<span style="position:absolute;inset:0;background:rgba(20,17,15,0.55);color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:850;">+${extraCount}</span>`
                      : ""
                  }
                </div>
              `
            )
            .join("")}
        </div>
      `;
    }

    let cardBadgeHtml = "";
    if (t.sharedCard && t.sharedCard.title) {
      const isWork = t.sharedCard.kind === "work";
      const isLayout = t.sharedCard.kind === "layout";
      const icon = isWork ? "🖼️ 附带作品" : isLayout ? "📐 附带图型" : "🎨 附带画风";
      const cls = isWork ? "honor-pioneer" : "honor-gold";
      cardBadgeHtml = `<span class="hw-honor-badge ${cls}" style="font-size:11px;padding:2px 8px;">${icon} · ${esc(t.sharedCard.title)}</span>`;
    } else if (t.workId) {
      const w = (App.state?.works || []).find((x) => x.id === t.workId);
      if (w) cardBadgeHtml = `<span class="hw-honor-badge honor-pioneer" style="font-size:11px;padding:2px 8px;">🖼️ 附带作品 · ${esc(w.title)}</span>`;
    } else if (t.styles && t.styles.length) {
      const st = App.resourceMap.get(t.styles[0]);
      if (st) cardBadgeHtml = `<span class="hw-honor-badge honor-gold" style="font-size:11px;padding:2px 8px;">🎨 附带画风 · ${esc(st.name)}</span>`;
    } else if (t.layout) {
      const lt = App.resourceMap.get(t.layout);
      if (lt) cardBadgeHtml = `<span class="hw-honor-badge honor-gold" style="font-size:11px;padding:2px 8px;">📐 附带图型 · ${esc(lt.name)}</span>`;
    }

    return `
      <article class="forum-topic-card" data-open-topic="${esc(t.id)}">
        ${bodyAndMediaHtml}

        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding-top:10px;border-top:1px dashed var(--line-soft);">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            ${cardBadgeHtml}
            ${
              t.recipe
                ? `<a class="btn btn-sm" style="padding:1px 8px;font-size:11.5px;" href="${esc(channelUrl("studio", { forkTopic: t.id }))}" data-stop-prop="1">⚡ 做同款 ↗</a>`
                : ""
            }
          </div>

          <div style="display:flex;gap:8px;align-items:center;font-size:12.5px;color:var(--ink-muted);">
            <button type="button" class="btn btn-sm ${liked ? "btn-primary" : ""}" style="padding:2px 8px;font-size:11.5px;" data-like-topic="${esc(t.id)}">
              👍 ${liked ? "已赞" : "点赞"} (${likeCnt})
            </button>
            <button type="button" class="btn btn-sm ${collected ? "btn-primary" : ""}" style="padding:2px 8px;font-size:11.5px;" data-fav-topic="${esc(t.id)}">
              ${collected ? "♥ 已收藏" : "♡ 收藏"} (${favCnt})
            </button>
            <span>💬 ${(t.replies || []).length} 回复</span>
            ${
              canMod
                ? `
                  <span style="display:inline-flex;gap:4px;align-items:center;margin-left:4px;">
                    <button type="button" class="btn btn-sm" style="padding:1px 6px;font-size:11px;" data-card-mod-op="${t.pinned ? "unpin" : "pin"}" data-topic-id="${esc(t.id)}">${t.pinned ? "取消置顶" : "📌 置顶"}</button>
                    <button type="button" class="btn btn-sm" style="padding:1px 6px;font-size:11px;" data-card-mod-op="${t.featured ? "unfeature" : "feature"}" data-topic-id="${esc(t.id)}">${t.featured ? "取消精华" : "🌟 精华"}</button>
                    <button type="button" class="btn btn-sm" style="padding:1px 6px;font-size:11px;color:var(--vermilion);font-weight:750;" data-card-mod-op="delete" data-topic-id="${esc(t.id)}">🗑️ 删帖</button>
                  </span>
                `
                : canDel
                ? `
                  <button type="button" class="btn btn-sm" style="padding:1px 6px;font-size:11px;color:var(--vermilion);margin-left:4px;" data-card-mod-op="delete" data-topic-id="${esc(t.id)}">🗑️ 删除</button>
                `
                : ""
            }
          </div>
        </div>
      </article>
    `;
  }

  function renderNotFoundPage(root, code = "") {
    document.title = "没有找到这个帖子或资源 — Handraw 手绘风社区";
    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-topic-not-found-page">
        <div class="hw-subpage-bar">
          <button type="button" class="btn btn-sm" id="topic-404-back">← 返回论坛</button>
        </div>
        <div class="hw-detail-section-card" style="text-align:center;padding:48px 24px;">
          <h2 style="margin:0 0 8px;">没有找到这个帖子或资源</h2>
          <p style="color:var(--ink-muted);margin:0 0 18px;">该资源可能尚未入库、已被移除或链接有误。</p>
          <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-secondary" id="btn-return-forum">返回论坛</button>
            <a href="/?q=${encodeURIComponent(code)}" class="btn btn-primary" id="btn-search-channel">在频道页搜索 ${esc(code)}</a>
          </div>
        </div>
      </div>
    `;
    const back1 = root.querySelector("#topic-404-back");
    if (back1) back1.onclick = () => openForumList(true);
    const back2 = root.querySelector("#btn-return-forum");
    if (back2) back2.onclick = () => openForumList(true);
  }

  function renderForum() {
    const root = document.getElementById("forum-app-root");
    if (!root || !App.state) return;

    if (FUI.view === "not_found") {
      renderNotFoundPage(root, FUI.notFoundCode);
      return;
    }

    if (["resource", "related"].includes(FUI.view)) {
      if (hasModule("HandrawResourcePages", "render")) {
        window.HandrawResourcePages.render(root,new URLSearchParams(location.search));
        return;
      }
      // No resource-page module: fall through to the plain stream.
      FUI.view = "list";
    }
    if (hasModule("HandrawResourcePages", "cancel")) window.HandrawResourcePages.cancel();
    root.classList.remove('hrp');
    if (FUI.view === "curation") {
      if (hasModule("HandrawCuration", "render")) {
        document.title="共创收录 — Handraw";
        window.HandrawCuration.render(root,new URLSearchParams(location.search).get("tab") || "share");
        return;
      }
      FUI.view = "list";
    }
    if (FUI.view === "compose") {
      renderComposePage(root);
      return;
    }
    if (FUI.view === "topic") {
      renderTopicDetailPage(root);
      return;
    }
    if (FUI.view === "moderators") {
      renderModeratorsPage(root);
      return;
    }
    if (FUI.view === "auth") {
      renderForumAuthPage(root);
      return;
    }

    const allTopics = App.state.topics || [];
    const visualCount = allTopics.filter((t) => (t.images || []).length > 0).length;
    const textOnlyCount = allTopics.length - visualCount;

    const cats = [
      { key: "all", label: "📋 全部社区讨论", count: allTopics.length },
      ...BOARD_DEFS.map((b) => ({
        key: b.key,
        label: b.label,
        count: allTopics.filter((t) => t.category === b.key).length
      }))
    ];

    const activeBoardModerators = S.getBoardModerators ? S.getBoardModerators(FUI.category) : [];
    const isSuperAdmin = Boolean(App.state.loggedIn && App.state.user?.role === "admin");
    const canModCurrent = S.canModerateForumBoard ? S.canModerateForumBoard(FUI.category) : false;

    const q = FUI.query.trim().toLowerCase();
    const filtered = allTopics.filter((t) => {
      const hasImgs = (t.images || []).length > 0;
      if (FUI.category !== "all" && t.category !== FUI.category) return false;
      if (FUI.format === "visual" && !hasImgs) return false;
      if (FUI.format === "text" && hasImgs) return false;
      if (FUI.sort === "featured" && !t.featured) return false;
      if (FUI.sort === "bounty" && !(t.bounty > 0 && !t.solved)) return false;
      if (FUI.sort === "paid" && !(t.price > 0)) return false;
      if (FUI.filterAsset) {
        const hit = (t.styles || []).includes(FUI.filterAsset) || t.layout === FUI.filterAsset;
        if (!hit) return false;
      }
      if (q) {
        const hay = `${t.title} ${stripHtmlToSnippet(t.summary || t.body, 300)} ${(t.styles || []).join(" ")} ${t.layout || ""} ${t.authorName}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    filtered.sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      if (FUI.sort === "newest") return (b.activityAtMs || b.publishedAtMs || 0) - (a.activityAtMs || a.publishedAtMs || 0);
      // "hot" uses the shared topic formula: replies + likes + 2*favourites.
      return S.popularScore("topic", b) - S.popularScore("topic", a);
    });

    const hotAssetIds = ["FA-001", "FX-001", "SC-021", "FC-029", "IG-001", "LX-001"];

    root.innerHTML = `
      <section class="hw-editorial-strip">
        <div>
          <p class="hw-editorial-eyebrow">以图为先的创作者社区 · 晒图交流与灵感互助</p>
          <h1 class="hw-editorial-title">晒作品、聊配方、求改图建议</h1>
          <p class="hw-editorial-sub">在这里晒图交流作品，分享可复用的<strong>画风、图型与提示词</strong>；遇到问题也可以<strong>发帖求助</strong>，和大家一起探讨。</p>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-primary" id="forum-btn-new-visual">分享投稿</button>
          <a class="btn" href="${esc(channelUrl("forum", {view:"curation",tab:"mine"}))}">我的投稿</a>
          <a class="btn" href="${esc(channelUrl("forum", {view:"curation",tab:"review"}))}">参与审核</a>
          ${isSuperAdmin ? `<a class="btn" href="${esc(channelUrl("forum", {view:"curation",tab:"admin"}))}">审核资格管理</a>` : ""}
          <button type="button" class="btn" id="forum-btn-new-text">📝 发纯文讨论帖</button>
        </div>
      </section>

      <div class="forum-layout">
        <!-- LEFT SIDEBAR -->
        <aside class="forum-side-card">
          <div style="font-size:12px;font-weight:800;color:var(--ink-muted);margin-bottom:8px;padding:0 6px;">板块分类</div>
          ${cats
            .map(
              (c) => `
                <button type="button" class="forum-cat-btn ${FUI.category === c.key ? "is-active" : ""}" data-fcat="${esc(c.key)}">
                  <span>${esc(c.label)}</span>
                  <span style="font-size:11.5px;opacity:0.85;">${c.count}</span>
                </button>
              `
            )
            .join("")}

          <!-- BOARD MODERATORS PANEL -->
          <div id="forum-moderators-panel" style="border-top:1px solid var(--line-soft);margin:12px 0;padding-top:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;">
              <span style="font-size:12px;font-weight:800;color:var(--ink-muted);">
                🛡️ ${FUI.category === "all" ? "论坛版主团队" : "本版值班版主"}
              </span>
              ${
                isSuperAdmin
                  ? `<button type="button" class="btn btn-sm" id="forum-btn-manage-mods" style="padding:1px 7px;font-size:11px;">⚙️ 设置版主</button>`
                  : ""
              }
            </div>
            <div style="display:grid;gap:6px;">
              ${
                activeBoardModerators.length === 0
                  ? `<div style="font-size:12px;color:var(--ink-muted);padding:4px;">暂未任命专属版主</div>`
                  : activeBoardModerators
                      .map(
                        (m) => `
                          <button type="button" data-sidebar-creator="${esc(m.username)}" style="display:flex;justify-content:space-between;align-items:center;gap:6px;padding:6px 8px;background:var(--paper-bg);border:1px solid transparent;border-radius:8px;font-size:12px;cursor:pointer;text-align:left;width:100%;">
                            <span style="font-weight:750;color:var(--ink-strong);">@${esc(m.displayName || m.username)}</span>
                            <span style="font-size:11px;color:#1f5f8b;font-weight:800;">${esc(m.shortBoardLabel || "全区")}·${esc(m.title || "版主")}</span>
                          </button>
                        `
                      )
                      .join("")
              }
            </div>
            ${
              canModCurrent
                ? `<a class="btn btn-sm" href="${esc(channelUrl("admin"))}" style="width:100%;margin-top:8px;justify-content:center;">🏛️ 进入我的版务工作台 ↗</a>`
                : ""
            }
          </div>

          <div style="border-top:1px solid var(--line-soft);margin:12px 0;padding-top:12px;">
            <div style="font-size:12px;font-weight:800;color:var(--ink-muted);margin-bottom:8px;padding:0 4px;">按挂载编号筛帖</div>
            <div class="hw-pills-row">
              ${hotAssetIds
                .map(
                  (id) =>
                    `<button type="button" class="hw-pill ${FUI.filterAsset === id ? "is-active" : ""}" data-fasset="${esc(id)}" style="font-size:11.5px;padding:3px 9px;">${esc(id)}</button>`
                )
                .join("")}
            </div>
            ${
              FUI.filterAsset
                ? `<button type="button" class="btn btn-sm" style="width:100%;margin-top:8px;" id="forum-clear-asset">× 清除筛选 (${esc(FUI.filterAsset)})</button>`
                : ""
            }
          </div>
        </aside>

        <!-- CENTER TOPIC STREAM -->
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <div class="hw-segmented">
                <button type="button" class="hw-seg-btn ${FUI.sort === "hot" ? "is-active" : ""}" data-fsort="hot">🔥 热门精选</button>
                <button type="button" class="hw-seg-btn ${FUI.sort === "newest" ? "is-active" : ""}" data-fsort="newest">🕒 最新动态</button>
                <button type="button" class="hw-seg-btn ${FUI.sort === "featured" ? "is-active" : ""}" data-fsort="featured">🌟 精华帖</button>
                <button type="button" class="hw-seg-btn ${FUI.sort === "bounty" ? "is-active" : ""}" data-fsort="bounty">💰 悬赏待结</button>
                <button type="button" class="hw-seg-btn ${FUI.sort === "paid" ? "is-active" : ""}" data-fsort="paid">💎 实战干货</button>
              </div>

              <div class="hw-segmented" title="筛选图文帖或纯文字帖">
                <button type="button" class="hw-seg-btn ${FUI.format === "all" ? "is-active" : ""}" data-fformat="all">全部 (${allTopics.length})</button>
                <button type="button" class="hw-seg-btn ${FUI.format === "visual" ? "is-active" : ""}" data-fformat="visual">🖼️ 图文 (${visualCount})</button>
                <button type="button" class="hw-seg-btn ${FUI.format === "text" ? "is-active" : ""}" data-fformat="text">📝 纯文 (${textOnlyCount})</button>
              </div>
            </div>

            <input type="search" class="hw-input" id="forum-search-input" value="${esc(FUI.query)}" placeholder="搜索帖子 / 编号 / 报价 / 避坑词…" style="min-width:210px;" />
          </div>

          ${
            filtered.length === 0
              ? `<div class="forum-side-card" style="text-align:center;padding:42px;color:var(--ink-muted);">暂无符合筛选条件的帖子</div>`
              : filtered.map((t) => renderTopicCard(t)).join("")
          }
        </div>

        <!-- RIGHT SIDEBAR -->
        <aside class="forum-aside-right" style="display:flex;flex-direction:column;gap:14px;">
          <div class="forum-side-card" style="background:linear-gradient(160deg,#fffdf9 0%,#f7efe2 100%);">
            <div style="font-size:12px;font-weight:800;color:var(--vermilion);margin-bottom:6px;">交流与求助</div>
            <div style="font-weight:800;font-size:14.5px;margin-bottom:6px;">把做法说清楚，让交流更有用</div>
            <p style="margin:0;font-size:12.5px;color:var(--ink-body);line-height:1.58;">
              • <strong>分享作品</strong>：附上主题、使用的画风或图型。<br/>
              • <strong>交流做法</strong>：说明提示词、参考与调整过程。<br/>
              • <strong>遇到问题</strong>：贴出结果和预期，方便大家帮忙。
            </p>
          </div>

          <div class="forum-side-card">
            <div style="font-weight:800;font-size:13.8px;margin-bottom:10px;">画风与图型入口</div>
            <div style="display:grid;gap:8px;">
              ${["FA-001", "SC-021", "FX-001", "IG-001"]
                .map((id) => {
                  const item = App.resourceMap.get(id);
                  if (!item) return "";
                  const wc = S.getAssetWorkCount(id);
                  return `
                    <a href="${esc(channelUrl("main", { view: "asset", id }))}" style="display:flex;align-items:center;gap:10px;padding:6px;border-radius:8px;background:var(--paper-bg);">
                      <img src="${esc(item.image)}" alt="" style="width:42px;height:42px;border-radius:6px;object-fit:cover;" />
                      <div style="min-width:0;flex:1;">
                        <div style="font-size:12px;font-weight:800;color:var(--vermilion);">${esc(item.id)}</div>
                        <div style="font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(item.name)}</div>
                      </div>
                      <span style="font-size:11px;color:var(--ink-muted);">${wc}作品 ↗</span>
                    </a>
                  `;
                })
                .join("")}
            </div>
          </div>
        </aside>
      </div>
    `;

    root.querySelector("#forum-btn-new-visual").onclick = () => S.goToCurationShare({kind:"work"});

    root.querySelector("#forum-btn-new-text").onclick = () =>
      openComposeView({
        category: FUI.category !== "all" ? FUI.category : "experience",
        images: []
      });

    const manageModsBtn = root.querySelector("#forum-btn-manage-mods");
    if (manageModsBtn) {
      manageModsBtn.onclick = () => openModeratorsPage(FUI.category);
    }

    root.querySelectorAll("[data-sidebar-creator]").forEach((btn) => {
      btn.onclick = () => S.goToCreatorProfile(btn.getAttribute("data-sidebar-creator"));
    });

    root.querySelectorAll("[data-fcat]").forEach((b) => {
      b.onclick = () => {
        FUI.category = b.getAttribute("data-fcat");
        syncForumUrl(false);
        renderForum();
      };
    });
    root.querySelectorAll("[data-fasset]").forEach((b) => {
      b.onclick = () => {
        const id = b.getAttribute("data-fasset");
        FUI.filterAsset = FUI.filterAsset === id ? "" : id;
        syncForumUrl(false);
        renderForum();
      };
    });
    const clearAsset = root.querySelector("#forum-clear-asset");
    if (clearAsset) {
      clearAsset.onclick = () => {
        FUI.filterAsset = "";
        syncForumUrl(false);
        renderForum();
      };
    }
    root.querySelectorAll("[data-fsort]").forEach((b) => {
      b.onclick = () => {
        FUI.sort = b.getAttribute("data-fsort");
        renderForum();
      };
    });
    root.querySelectorAll("[data-fformat]").forEach((b) => {
      b.onclick = () => {
        FUI.format = b.getAttribute("data-fformat");
        renderForum();
      };
    });

    const searchInput = root.querySelector("#forum-search-input");
    searchInput.oninput = (e) => {
      FUI.query = e.target.value;
      renderForum();
      const next = document.getElementById("forum-search-input");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    };
    root.querySelectorAll("[data-stop-prop]").forEach((el) => {
      el.onclick = (e) => e.stopPropagation();
    });
    root.querySelectorAll("[data-card-creator]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        S.goToCreatorProfile(btn.getAttribute("data-card-creator"));
      };
    });
    root.querySelectorAll("[data-jump-main-asset]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        S.goToAssetPage(el.getAttribute("data-jump-main-asset"));
      };
    });
    root.querySelectorAll("[data-like-topic]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const tid = b.getAttribute("data-like-topic");
        const t = allTopics.find((x) => x.id === tid);
        if (t) S.toggleLike("topic", tid, t.title);
      };
    });
    root.querySelectorAll("[data-fav-topic]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const tid = b.getAttribute("data-fav-topic");
        const t = allTopics.find((x) => x.id === tid);
        if (t) S.toggleCollect("topics", tid, t.title);
      };
    });
    root.querySelectorAll("[data-card-mod-op]").forEach((b) => {
      b.onclick = async (e) => {
        e.stopPropagation();
        const tid = b.getAttribute("data-topic-id");
        const op = b.getAttribute("data-card-mod-op");
        if (op === "delete") {
          if (!confirm("确定要删除这篇帖子吗？此操作不可撤销。")) return;
        }
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: tid, op }
          });
          await S.refreshFromServer();
          toast(op === "delete" ? "帖子已成功删除" : "版务操作已生效");
          renderForum();
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
      };
    });
    root.querySelectorAll("[data-open-topic]").forEach((card) => {
      const tid = card.getAttribute("data-open-topic");
      card.querySelectorAll("[data-open-topic-img]").forEach((thumb) => {
        thumb.onclick = (e) => {
          e.stopPropagation();
          openTopicPage(tid, Number(thumb.getAttribute("data-open-topic-img")) || 0);
        };
      });
      card.onclick = () => openTopicPage(tid, 0);
    });
  }

  window.addEventListener('popstate', () => {
    FUI.view = 'list';
    parseInitialForumUrl();
    renderForum();
  });
  parseInitialForumUrl();
  S.initApp("forum", () => { restoreComposeDraft(); renderForum(); }).then(() => {
    restoreComposeDraft();
    if (FUI.view === "moderators") {
      openModeratorsPage(FUI.modInitialBoard);
    } else {
      updateForumTitle();
      renderForum();
    }
  }).catch((error) => {
    const root=document.getElementById("forum-app-root");
    root.innerHTML=`<section class="hw-account-page"><h1>暂时无法加载论坛</h1><p role="alert">${esc(error.message)}</p><button class="btn btn-primary" id="forum-retry-boot">重试</button></section>`;
    root.querySelector("#forum-retry-boot").onclick=()=>location.reload();
  });
})();
