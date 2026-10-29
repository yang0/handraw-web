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
        FUI.topicInlineDrawer = "";
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
    if (isEntering) FUI.topicInlineDrawer = "";
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
    const studioActionLabel = isWork ? "⚡ 创作台复刻 ↗" : "✨ 创作台使用 ↗";

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

  function renderTopicDetailPage(root) {
    const allTopics = App.state.topics || [];
    const curIdx = allTopics.findIndex((t) => t.id === FUI.activeTopicId);
    const topic = curIdx >= 0 ? allTopics[curIdx] : null;

    if (!topic) {
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
      // A zero-comment official topic stays out of boot/feed; preserve its old URL.
      const missingId = FUI.activeTopicId;
      S.apiJson('/api/forum/resource-topics/' + encodeURIComponent(missingId)).then(resource => {
        if (FUI.view !== 'topic' || FUI.activeTopicId !== missingId || !resource.id) return;
        location.replace(channelUrl('forum',{view:'resource',kind:resource.kind,id:resource.id}));
      }).catch(() => {});
      return;
    }

    const submission = topic.submissions?.[0];
    const attached = topic.resourceDiscussion;
    // Only authoritative submission/mapping metadata identifies a resource post.
    if (submission || attached) {
      const kind = submission?.kind || attached.kind;
      const id = submission?.targetId || attached.targetId;
      const params = new URLSearchParams({view:"resource",kind,id});
      history.replaceState({}, "", channelUrl("forum", Object.fromEntries(params)));
      FUI.view = "resource";
      window.HandrawResourcePages.render(root, params);
      return;
    }
    const prevTopic = curIdx > 0 ? allTopics[curIdx - 1] : null;
    const nextTopic = curIdx >= 0 && curIdx < allTopics.length - 1 ? allTopics[curIdx + 1] : null;
    const unlocked = S.isUnlocked(topic.id, topic);
    const liked = S.isLiked("topic", topic.id);
    const likeCnt = S.getLikeCount("topic", topic);
    const collected = S.isCollected("topics", topic.id);
    const favCnt = S.getFavoriteCount("topics", topic);
    const imgs = normalizeTopicImages(topic);
    const activeImgIdx = Math.max(0, Math.min(imgs.length - 1, Number(FUI.activeTopicImgIdx) || 0));
    const canModerateThisBoard = S.canModerateForumBoard ? S.canModerateForumBoard(topic.category) : false;
    const authorProf = S.getCreatorProfile(topic.author) || {honor:{sealClass:""},avatarChar:"绘",authorName:"资源讨论",totalPublished:0,totalCheers:0,topics:[]};
    const boardMods = S.getBoardModerators ? S.getBoardModerators(topic.category) : [];
    const replies = topic.replies || [];

    const canArbitrate = topic.bounty > 0 && !topic.solved && App.state && App.state.loggedIn && (App.state.user.role === "admin" || App.state.user.role === "operator" || App.state.user.role === "reviewer");
    const isTopicAuthor = App.state && App.state.loggedIn && App.state.user && App.state.user.username === topic.author;

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

    const workPost = window.HandrawForumWork.fromTopic(topic, App.state.works || [], App.resourceMap, unlocked || S.isStaff?.());
    const cardsToRender = [];
    if (topic.sharedCard && topic.sharedCard.title) {
      cardsToRender.push(topic.sharedCard);
    }
    if (topic.workId && !cardsToRender.some((c) => c.kind === "work" && c.id === topic.workId)) {
      const w = (App.state?.works || []).find((x) => x.id === topic.workId);
      if (w) {
        cardsToRender.push({
          kind: "work",
          id: w.id,
          title: w.title,
          image: (w.images && w.images[0]) || "",
          authorName: w.authorName || w.author || "",
          desc: w.notes || w.prompt || ""
        });
      }
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

    const sameBoardHot = allTopics
      .filter((ot) => ot.id !== topic.id && ot.category === topic.category)
      .slice(0, 4);

    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-topic-detail-page">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="topic-back-list-btn">← 返回论坛列表</button>
            <span>/</span>
            <button type="button" class="hw-pill" id="topic-crumb-board" style="padding:2px 9px;font-size:11.8px;">${esc(topic.categoryLabel || "社区讨论")}</button>
            <span>/</span>
            <strong>帖子正文与楼层回复</strong>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-sm" id="topic-prev-btn" ${prevTopic ? "" : "disabled"} title="${esc(prevTopic ? prevTopic.title : "已是第一帖")}">◀ 上一帖</button>
            <button type="button" class="btn btn-sm" id="topic-next-btn" ${nextTopic ? "" : "disabled"} title="${esc(nextTopic ? nextTopic.title : "已是最后一帖")}">下一帖 ▶</button>
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
                  workPost ? `<span class="forum-format-badge is-visual">作品分享</span>` : imgs.length > 0
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
              ${window.HandrawCuration.topicPanelHtml(topic)}

              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding-bottom:12px;border-bottom:1px solid var(--line-soft);">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--ink-muted);">
                  <button type="button" class="hw-author-chip" data-open-creator="${esc(topic.author)}">
                    <span class="hw-creator-avatar-sm ${esc(authorProf.honor.sealClass)}">${esc(authorProf.avatarChar)}</span>
                    <strong style="color:var(--ink-strong);">@${esc(topic.authorName)}</strong>
                  </button>
                  ${renderModBadgeHtml(topic.author, topic.category)}
                  <span>· 发布于 ${esc(topic.createdAt)}</span>
                </div>

                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                  <button type="button" class="btn btn-sm ${liked ? "btn-primary" : ""}" id="topic-page-like">
                    👍 ${liked ? "已赞" : "点赞"} (${likeCnt})
                  </button>
                  <button type="button" class="btn btn-sm ${collected ? "btn-primary" : ""}" id="topic-page-collect">
                    ${collected ? "♥ 已收藏" : "♡ 收藏"} (${favCnt})
                  </button>
                  <button type="button" class="btn btn-sm" id="topic-page-scroll-reply">
                    💬 回复 (${replies.length})
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

              <!-- Cohesive Editorial Article Narrative & In-Flow Media/Cards -->
              <div class="forum-article-body" id="topic-article-body">
                ${workPost ? window.HandrawForumWork.render(workPost) : renderEditorialArticleHtml(topic, cardsToRender, unlocked)}
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
                  <h2 style="margin:0;font-size:18.5px;font-family:var(--font-serif);">💬 全部社区交流与调优楼层 (${replies.length})</h2>
                  <div style="font-size:12.4px;color:var(--ink-muted);margin-top:3px;">可以附上推荐的 #画风 或 #图型 编号，方便继续尝试。</div>
                </div>
                ${
                  topic.bounty > 0 && !topic.solved
                    ? `<span style="font-size:12.5px;font-weight:850;color:var(--vermilion);background:var(--vermilion-wash);padding:4px 10px;border-radius:999px;">💰 本帖托管悬赏 ${topic.bounty}✦ 待楼主采纳结算</span>`
                    : ""
                }
              </div>

              <div style="display:grid;gap:12px;margin-bottom:18px;">
                ${
                  replies.length === 0
                    ? `<div style="padding:28px;text-align:center;color:var(--ink-muted);background:var(--paper-bg);border-radius:10px;">还没有回复，欢迎分享你的想法。</div>`
                    : replies
                        .map((r, idx) => {
                          const canAccept =
                            topic.bounty > 0 &&
                            !topic.solved &&
                            (!App.state.serverBacked ||
                              (App.state.loggedIn &&
                                r.user !== topic.author &&
                                (topic.author === App.state.user.username ||
                                  App.state.user.role === "admin" ||
                                  App.state.user.role === "operator" ||
                                  App.state.user.role === "reviewer")));
                          return `
                            <div class="forum-reply-card">
                              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
                                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                                  <button type="button" class="hw-author-chip" data-open-creator="${esc(r.user || r.name)}" style="padding:2px 8px;">
                                    <strong style="font-size:13.2px;color:var(--ink-strong);">@${esc(r.name || r.user)}</strong>
                                  </button>
                                  ${renderModBadgeHtml(r.user, topic.category)}
                                  <span style="color:var(--ink-faint);font-size:12px;">${esc(r.time)}</span>
                                </div>
                                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                                  ${r.accepted ? `<span style="background:var(--jade);color:#fff;font-size:11.5px;font-weight:800;padding:2px 9px;border-radius:999px;">🏆 最佳采纳方案 (+${topic.bounty}✦)</span>` : ""}
                                  ${
                                    canAccept
                                      ? `<button type="button" class="btn btn-sm btn-gold" data-accept-reply="${esc(r.id)}">🏆 采纳并结算 ${topic.bounty}✦</button>`
                                      : ""
                                  }
                                  ${
                                    canModerateThisBoard
                                      ? `<button type="button" class="btn btn-sm" data-hide-reply="${esc(r.id)}" style="font-size:11px;padding:1px 7px;color:var(--ink-muted);">🙈 隐藏回复</button>`
                                      : ""
                                  }
                                  ${
                                    (S.canDeleteReply ? S.canDeleteReply(r, topic) : (App.state.loggedIn && (r.user === App.state.user.username || canModerateThisBoard)))
                                      ? `<button type="button" class="btn btn-sm" data-del-reply="${esc(r.id)}" style="font-size:11px;padding:1px 7px;color:var(--vermilion);">🗑️ 删除</button>`
                                      : ""
                                  }
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
                                <button type="button" class="btn btn-sm" data-reply-floor="${idx + 1}" data-reply-user="${esc(r.user || r.name)}" data-reply-name="${esc(r.name || r.user)}" style="font-size:12px;padding:3px 10px;">
                                  💬 回复
                                </button>
                                <button type="button" class="btn btn-sm" data-quote-floor="${idx + 1}" data-reply-user="${esc(r.user || r.name)}" data-reply-name="${esc(r.name || r.user)}" data-reply-id="${esc(r.id)}" style="font-size:12px;padding:3px 10px;">
                                  ❝ 引用回复
                                </button>
                              </div>
                            </div>
                          `;
                        })
                        .join("")
                }
              </div>

              <!-- Bottom Reply Composer -->
              <div style="background:var(--paper-bg);border:1px solid var(--line-strong);border-radius:12px;padding:14px 16px;">
                <div style="font-size:13px;font-weight:800;margin-bottom:8px;">✍️ 发表跟帖回复 / 交流讨论</div>
                <textarea class="hw-textarea" rows="3" id="topic-reply-input" placeholder="写下建议、经验或问题，支持 Ctrl + Enter 发送…"></textarea>
                <div style="display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap;">
                  <button type="button" class="btn btn-primary" id="topic-reply-submit">💬 发布回复</button>
                </div>
              </div>
            </section>
          </div>

          <!-- RIGHT AUTHOR & BOARD SIDEBAR -->
          <aside style="display:flex;flex-direction:column;gap:14px;">
            <div class="forum-side-card" style="display:grid;gap:12px;">
              <div style="font-size:11.5px;font-weight:800;color:var(--ink-muted);letter-spacing:0.04em;">作者</div>
              <div style="display:flex;gap:12px;align-items:center;">
                <div class="hw-creator-avatar-sm ${esc(authorProf.honor.sealClass)}" style="width:46px;height:46px;font-size:18px;">${esc(authorProf.avatarChar)}</div>
                <div style="min-width:0;">
                  <div style="font-weight:850;font-size:15px;color:var(--ink-strong);">@${esc(authorProf.authorName)}</div>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;text-align:center;background:var(--paper-bg);padding:8px;border-radius:9px;font-size:12px;">
                <div><strong style="display:block;font-size:15px;color:var(--ink-strong);">${authorProf.totalPublished}</strong><span style="color:var(--ink-muted);">总分享</span></div>
                <div><strong style="display:block;font-size:15px;color:var(--ink-strong);">${authorProf.totalCheers}</strong><span style="color:var(--ink-muted);">获鼓励</span></div>
                <div><strong style="display:block;font-size:15px;color:var(--ink-strong);">${authorProf.topics.length}</strong><span style="color:var(--ink-muted);">论坛帖</span></div>
              </div>
              <button type="button" class="btn btn-primary btn-sm" style="width:100%;justify-content:center;" data-open-creator="${esc(topic.author)}">
                🏠 访问 TA 的独立个人主页 ↗
              </button>
            </div>

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
              sameBoardHot.length
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

    window.HandrawCuration.bindTopicPanel(root,topic);
    if (!topic.author && topic.resourceDiscussion) {
      const authorCard=root.querySelector('aside .forum-side-card');
      if (authorCard) authorCard.remove();
    }
    root.querySelector("#topic-back-list-btn").onclick = () => openForumList(true);
    root.querySelector("#topic-crumb-board").onclick = () => {
      FUI.category = topic.category || "all";
      openForumList(true);
    };
    if (prevTopic) {
      root.querySelector("#topic-prev-btn").onclick = () => openTopicPage(prevTopic.id, 0);
    }
    if (nextTopic) {
      root.querySelector("#topic-next-btn").onclick = () => openTopicPage(nextTopic.id, 0);
    }
    root.querySelector("#topic-new-post-btn").onclick = () =>
      openComposeView({ category: topic.category || "experience" }, true);

    root.querySelectorAll("[data-open-creator]").forEach((btn) => {
      if (!btn.getAttribute("data-open-creator")) { btn.outerHTML='<span class="curation-muted">资源讨论</span>'; return; }
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
      imgEl.onclick = () => {
        openImageLightboxModal(imgEl.src);
      };
    });

    if (workPost) window.HandrawForumWork.bind(root,workPost);

    root.querySelector("#topic-page-like").onclick = () => {
      S.toggleLike("topic", topic.id, topic.title);
    };
    root.querySelector("#topic-page-collect").onclick = () => {
      S.toggleCollect("topics", topic.id, topic.title);
    };
    root.querySelector("#topic-page-scroll-reply").onclick = () => {
      const sec = root.querySelector("#topic-replies-section");
      if (sec) sec.scrollIntoView({ behavior: "smooth", block: "start" });
      const inp = root.querySelector("#topic-reply-input");
      if (inp) setTimeout(() => inp.focus(), 180);
    };

    root.querySelector("#topic-page-share").onclick = () => {
      FUI.topicInlineDrawer = FUI.topicInlineDrawer === "share" ? "" : "share";
      renderForum();
    };
    root.querySelector("#topic-page-report").onclick = () => {
      if (!App.state.loggedIn) {
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
          await S.refreshFromServer();
          if (op === "hide") {
            toast("🛡️ 版务操作生效：已隐藏该违规帖子");
            openForumList(true);
          } else if (op === "delete") {
            toast("🛡️ 帖子已彻底删除");
            openForumList(true);
          } else {
            toast("🛡️ 版务操作已生效！");
            renderForum();
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
          await S.refreshFromServer();
          toast("您的帖子已成功删除");
          openForumList(true);
        } catch (err) {
          toast(`删帖失败：${err.message}`);
        }
      };
    }

    const arbitrateBtn = root.querySelector("#topic-mod-arbitrate-bounty");
    if (arbitrateBtn) {
      arbitrateBtn.onclick = () => {
        const reps = topic.replies || [];
        if (!reps.length) {
          toast("该悬赏帖暂无回复可供仲裁采纳", "warning");
          return;
        }
        const repSummary = reps.map((r, i) => `#${i + 1}楼 @${r.name || r.user}: ${r.text.slice(0, 30)}`).join("\n");
        const chosenStr = prompt(`请输入要采纳的楼层编号 (1 到 ${reps.length})：\n\n${repSummary}`, "1");
        if (!chosenStr) return;
        const floorIdx = parseInt(chosenStr, 10) - 1;
        if (isNaN(floorIdx) || floorIdx < 0 || floorIdx >= reps.length) {
          toast("输入的楼层编号无效", "warning");
          return;
        }
        const chosenReply = reps[floorIdx];
        if (!confirm(`确定要代表社区运营将 ${topic.bounty} 悬赏积分仲裁结算给 @${chosenReply.name || chosenReply.user} 吗？`)) return;
        S.apiJson(`/api/admin/topics/${topic.id}/moderate`, {
          method: "POST",
          body: { action: "settle_bounty", replyId: chosenReply.id, reason: "管理人员前台仲裁采纳悬赏" }
        }).then(async (res) => {
          if (!res.ok) throw new Error(res.error || "仲裁失败");
          await S.refreshFromServer();
          toast(`🏆 悬赏仲裁采纳成功！${topic.bounty} 积分已发放给 @${chosenReply.name || chosenReply.user}`);
          renderForum();
        }).catch((err) => toast("仲裁失败：" + (err.message || err)));
      };
    }

    root.querySelectorAll("[data-del-reply]").forEach((btn) => {
      btn.onclick = async () => {
        const replyId = btn.getAttribute("data-del-reply");
        if (!confirm("确定要删除这条回复吗？此操作不可撤销。")) return;
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, replyId, op: "delete_reply" }
          });
          await S.refreshFromServer();
          toast("回复已成功删除");
          renderForum();
        } catch (err) {
          toast(`删除回复失败：${err.message}`);
        }
      };
    });

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
          await S.refreshFromServer();
          toast("🛡️ 已将该帖移动至目标板块！");
          renderForum();
        } catch (err) {
          toast(`移帖失败：${err.message}`);
        }
      };
    }

    root.querySelectorAll("[data-hide-reply]").forEach((btn) => {
      btn.onclick = async () => {
        const replyId = btn.getAttribute("data-hide-reply");
        try {
          await S.apiJson("/api/forum/moderate", {
            method: "POST",
            body: { topicId: topic.id, replyId, op: "hide_reply" }
          });
          await S.refreshFromServer();
          toast("🛡️ 已隐藏该条违规回复");
          renderForum();
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
      };
    });

    const unlockBtn = root.querySelector("#topic-btn-unlock");
    if (unlockBtn) {
      unlockBtn.onclick = () => {
        S.unlockWithCredits(topic.id, topic.price, topic.title, topic.authorName, () => renderForum());
      };
    }

    root.querySelectorAll("[data-accept-reply]").forEach((btn) => {
      btn.onclick = async () => {
        if (!App.state.loggedIn) {
          openForumAuthPage("登录后即可采纳最佳调优方案");
          return;
        }
        const rid = btn.getAttribute("data-accept-reply");
        if (App.state.serverBacked) {
          try {
            const res = await S.apiJson(`/api/forum/topics/${encodeURIComponent(topic.id)}/accept-bounty`, {
              method: "POST",
              body: { replyId: rid }
            });
            await S.refreshFromServer();
            toast(`🏆 已采纳 @${res.winnerName} 的调优方案，托管的 ${res.bounty}✦ 悬赏金已实时结算入账！`);
            renderForum();
          } catch (err) {
            toast(`采纳失败：${err.message}`);
          }
          return;
        }
        const rep = (topic.replies || []).find((x) => x.id === rid);
        if (!rep) return;
        topic.solved = true;
        rep.accepted = true;
        if (rep.user === App.state.user.username) {
          S.addLedger(`调优方案被采纳赏金入账《${topic.title.slice(0, 14)}…》`, +topic.bounty);
        }
        S.saveState();
        toast(`🏆 已采纳 @${rep.name} 的调优方案，${topic.bounty} 悬赏积分已自动结算！`);
        renderForum();
      };
    });

    const repInp = root.querySelector("#topic-reply-input");
    const submitReply = async () => {
      if (!App.state.loggedIn) {
        openForumAuthPage("登录后即可参与社区讨论并赢取悬赏积分！");
        return;
      }
      const txt = repInp.value.trim();
      if (!txt) {
        toast("请输入回复内容");
        return;
      }
      const styleInp = root.querySelector("#reply-mount-style");
      const layoutInp = root.querySelector("#reply-mount-layout");
      const ms = styleInp ? styleInp.value.trim().toUpperCase().replace(/^#/, "") : "";
      const ml = layoutInp ? layoutInp.value.trim().toUpperCase().replace(/^#/, "") : "";

      if (App.state.serverBacked) {
        try {
          const res = await S.apiJson(`/api/forum/topics/${encodeURIComponent(topic.id)}/replies`, {
            method: "POST",
            body: { text: txt, mountedStyle: ms || "", mountedLayout: ml || "" }
          });
          await S.refreshFromServer();
          toast(
            res.rewarded > 0
              ? `🎉 楼层回复已发布！获得 +${res.rewarded}✦ 互助积分`
              : "🎉 楼层回复已发布！（今日回帖积分奖励已达上限）"
          );
          renderForum();
        } catch (err) {
          toast(`回复失败：${err.message}`);
        }
        return;
      }

      topic.replies = topic.replies || [];
      topic.replies.push({
        id: "rep_" + Date.now(),
        user: App.state.user.username,
        name: App.state.user.name,
        time: "刚刚",
        text: txt,
        mountedStyle: ms || "",
        mountedLayout: ml || "",
        likes: 1
      });
      S.addLedger(`参与帖子《${topic.title.slice(0, 14)}…》深度回复激励`, +2);
      S.saveState();
      toast("🎉 楼层回复已发布！获得 +2 互助积分");
      renderForum();
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
                ? `<a class="btn btn-sm" style="padding:1px 8px;font-size:11.5px;" href="${esc(channelUrl("studio", { forkTopic: t.id }))}" data-stop-prop="1">⚡ 一键带入创作台复刻 ↗</a>`
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

  function renderForum() {
    const root = document.getElementById("forum-app-root");
    if (!root || !App.state) return;

    if (["resource", "related"].includes(FUI.view)) {
      window.HandrawResourcePages.render(root,new URLSearchParams(location.search));
      return;
    }
    window.HandrawResourcePages?.cancel();
    root.classList.remove('hrp');
    if (FUI.view === "curation") {
      document.title="共创收录 — Handraw";
      window.HandrawCuration.render(root,new URLSearchParams(location.search).get("tab") || "share");
      return;
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
