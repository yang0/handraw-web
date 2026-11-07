/* Main Channel Interactive App (handraw-style.com / localhost:3080)
 * Views (100% Standalone Pages — Zero Content/Profile Modals):
 * styles | layouts | works | rankings | wallet | asset | work | profile | auth | skill
 */
(function () {
  const S = window.HANDRAW_SHARED;
  const { App, esc, toast, channelUrl } = S;

  const UI = {
    styleGroup: "ALL",
    layoutGroup: "ALL",
    assetQuery: "",
    assetSort: "recommended", // 'recommended' | 'newest' | 'hot' | 'exclusive' | 'code'
    density: "standard", // 'compact' | 'standard' | 'large'
    pageSize: 40,
    shownCount: 40,
    spotlightCollapsed: true,
    workSort: "newest", // newest | favorites | cheers
    workFormat: "all", // all | single | multi
    workAccess: "all", // all | free | paid
    workShownCount: 24,
    workFilterAsset: "",
    workFilterAuthor: "",
    workQuery: "",
    worksSpotlightCollapsed: true,
    rankTab: "creators", // 'creators' | 'works' | 'assets'
    rankPeriod: "week", // 'week' | 'month' | 'all' — default 'week' so fresh active faces shine first!
    lastPrimaryView: "discover", // parent channel to return to from secondary/detail pages
    creatorRankMode: "prolific", // 'prolific' | 'cheers' | 'rising'
    workRankMode: "composite", // 'composite' | 'cheers' | 'rising' | 'forks'
    favTab: "styles", // 'styles' | 'layouts' | 'works' | 'topics' | 'generations'
    _collectedGenerations: null,
    _fetchingColGen: false,
    // Standalone Detail & Profile Page States
    activeWorkId: "",
    activeWorkImgIdx: 0,
    workInlineDrawer: "", // '' | 'share' | 'report'
    workFocusComment: false,
    profileUser: "",
    profileTab: "works", // public content tabs only
    profileResourceFilter: "all", // all | styles | layouts
    profileWorksUser: "",
    profileWorkRows: null,
    profileWorksLoading: false,
    profileWorksError: "",
    profileWorksCursor: "",
    profileWorksHasMore: false,
    profileWorksTotal: null,
    accountSection: "profile", // profile | email | security | devices | cloud
    profGenerations: null,
    profGenUser: "",
    profGenLoading: false,
    profGenCursor: "",
    profGenHasMore: false,
    profGenTotal: null,
    authReason: "",
    authOnSuccess: null,
    authReturnSnapshot: null,
    walletShareItem: null,
    navHistoryDepth: 0
  };

  function getPeriodMeta(period = UI.rankPeriod) {
    const list = S.RANK_PERIODS || [];
    return (
      list.find((p) => p.key === period) || {
        key: "week",
        label: "📅 周榜",
        fullLabel: "📅 周榜 · 近7天",
        shortPrefix: "本周",
        desc: "统计近 7 天新发布与互动热度"
      }
    );
  }

  function renderPeriodSwitchHtml(compact = false) {
    const periods = S.RANK_PERIODS || [
      { key: "week", label: "📅 周榜", fullLabel: "📅 周榜 · 近7天" },
      { key: "month", label: "🗓️ 月榜", fullLabel: "🗓️ 月榜 · 近30天" },
      { key: "all", label: "🏛️ 总榜", fullLabel: "🏛️ 总榜 · 历史累计" }
    ];
    return `
      <div class="hw-segmented" role="tablist" aria-label="榜单统计周期" style="${compact ? "padding:2px;gap:2px;" : ""}">
        ${periods
          .map(
            (p) => `
              <button
                type="button"
                class="hw-seg-btn ${UI.rankPeriod === p.key ? "is-active" : ""}"
                data-rank-period="${esc(p.key)}"
                style="${compact ? "padding:3px 9px;font-size:11.5px;" : ""}"
              >${esc(compact ? p.label.replace(/^[^\s]+\s*/, "") : p.fullLabel)}</button>
            `
          )
          .join("")}
      </div>
    `;
  }

  function bindPeriodSwitch(root) {
    root.querySelectorAll("[data-rank-period]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const nextP = btn.getAttribute("data-rank-period");
        if (nextP && ["week", "month", "all"].includes(nextP)) {
          UI.rankPeriod = nextP;
          syncUrl();
          renderMain();
        }
      };
    });
  }

  function parseInitialUrl() {
    const p = new URLSearchParams(window.location.search);
    const view = p.get("view") || "";
    const legacyAsset = p.get("asset") ? p.get("asset").trim().toUpperCase().replace(/^#/, "") : "";
    const legacyWork = p.get("work") ? p.get("work").trim() : "";

    if (p.get("rtab") && ["creators", "works", "assets"].includes(p.get("rtab"))) {
      UI.rankTab = p.get("rtab");
    }
    if (p.get("period") && ["week", "month", "all"].includes(p.get("period"))) {
      UI.rankPeriod = p.get("period");
    }
    if (p.get("q")) {
      UI.assetQuery = p.get("q");
      UI.workQuery = p.get("q");
    }

    // Legacy Asset Detail URL compatibility (?view=asset&id=FA-001 or legacy ?asset=FA-001)
    if (view === "asset" || legacyAsset) {
      const code = (p.get("id") || legacyAsset || "").trim().toUpperCase().replace(/^#/, "");
      if (code) {
        const tabParam = p.get("tab") || "";
        const panelParam = p.get("panel") || "";
        const focusParam = p.get("focus") || "";
        location.replace(channelUrl("main", {
          view: "asset",
          id: code,
          tab: tabParam,
          panel: panelParam,
          focus: focusParam
        }));
        return {};
      }
    }

    // Standalone Work Detail & Comment Page (?view=work&id=w_101 or legacy ?work=w_101) -> unified into forum topic
    if (view === "work" || legacyWork) {
      const wid = (p.get("id") || legacyWork || "").trim();
      if (wid) {
        const focus = p.get("focus") === "comment";
        const disc = (App.state && App.state.discussions && App.state.discussions[wid]) || null;
        const tid = disc ? disc.topicId : null;
        if (tid) {
          window.location.replace(channelUrl("forum", { view: "topic", id: tid, ...(focus ? { focus: "comment" } : {}) }));
        } else {
          window.location.replace(`/t/work-${encodeURIComponent(wid)}${focus ? "?focus=comment" : ""}`);
        }
        return {};
      }
    }

    // Standalone Collections view (?view=collections) is retired -> replace navigation to profile collections
    if (view === "collections") {
      const curU = (App.state && App.state.user && App.state.user.username && App.state.user.username !== "guest") ? App.state.user.username : "";
      if (App.state && App.state.loggedIn && curU) {
        App.view = "profile";
        UI.profileUser = curU;
        UI.profileTab = "collections";
        try {
          const nextP = new URLSearchParams();
          nextP.set("view", "profile");
          nextP.set("user", curU);
          nextP.set("ptab", "collections");
          window.history.replaceState({ view: "profile" }, "", `${window.location.pathname}?${nextP.toString()}`);
        } catch (_) {}
        return {};
      } else if (App.state && !App.state.loggedIn) {
        openAuthPage("登录后查看与同步你的云端收藏夹", () => {
          if (App.state && App.state.user && App.state.user.username) {
            openProfilePage(App.state.user.username, "collections");
          }
        });
        try {
          const nextP = new URLSearchParams();
          nextP.set("view", "auth");
          window.history.replaceState({ view: "auth" }, "", `${window.location.pathname}?${nextP.toString()}`);
        } catch (_) {}
        return {};
      } else {
        // App.state not ready yet (booting), defer resolution to post-boot
        App.view = "collections";
        return {};
      }
    }

    // Separate account settings from the public creator profile; keep old links working.
    if (view === "account" || (view === "profile" && p.get("ptab") === "account")) {
      App.view = "account";
      UI.accountSection = ["profile", "email", "security", "devices", "cloud"].includes(p.get("section")) ? p.get("section") : "profile";
      if (view !== "account") {
        window.history.replaceState({ view: "account" }, "", channelUrl("main", { view: "account", section: UI.accountSection }));
      }
      return {};
    }
    if (view === "profile") {
      App.view = "profile";
      UI.profileUser = (p.get("user") || "").trim();
      let reqTab = p.get("ptab") || "works";
      let urlChanged = false;
      if (["assets", "styles", "layouts"].includes(reqTab)) {
        UI.profileResourceFilter = reqTab === "layouts" ? "layouts" : "styles";
        reqTab = "resources";
        urlChanged = true;
      } else if (reqTab === "generations") {
        // The public profile shows generated images via published works only.
        reqTab = "works";
        urlChanged = true;
      }
      if (reqTab === "articles" && App.state?.loggedIn && App.state.user?.username === UI.profileUser) {
        window.location.replace(channelUrl("studio", { view: "articles-all", page: 1 }));
        return {};
      }
      const isMe = Boolean(App.state && App.state.loggedIn && App.state.user && App.state.user.username && App.state.user.username === UI.profileUser);
      if (App.state && !isMe && ["collections", "account", "articles"].includes(reqTab)) {
        reqTab = "works";
        urlChanged = true;
      }
      if (urlChanged) {
        try {
          const nextP = new URLSearchParams(p);
          if (reqTab === "works") {
            nextP.delete("ptab");
          } else {
            nextP.set("ptab", reqTab);
          }
          window.history.replaceState({ view: "profile" }, "", `${window.location.pathname}?${nextP.toString()}`);
        } catch (_) {}
      }
      UI.profileTab = ["works", "resources", "topics", "collections", "articles"].includes(reqTab) ? reqTab : "works";
      return {};
    }

    if (view === "manage") {
      App.view = "works";
      try {
        window.history.replaceState({ view: "works" }, "", `${window.location.pathname}?view=works`);
      } catch (_) {}
      return {};
    }

    if (["discover", "styles", "layouts", "works", "rankings", "wallet", "auth", "skill", "guide", "recovery", "reset-password", "oauth-register", "verify-email", "notifications", "edit-work", "edit-topic", "device", "devices"].includes(view)) {
      App.view = view;
    } else {
      App.view = !view && p.get("q") ? "styles" : "discover";
    }

    if (p.get("filterAsset")) {
      UI.workFilterAsset = p.get("filterAsset").toUpperCase();
      App.view = "works";
    }
    if (p.get("author")) {
      UI.workFilterAuthor = p.get("author");
      App.view = "works";
    }
    if (p.get("scenario")) {
      UI.workScenario = p.get("scenario").trim().toLowerCase();
      App.view = "works";
    }
    if (App.view === "works") {
      UI.workFormat = ["single","multi"].includes(p.get("format")) ? p.get("format") : "all";
      UI.workAccess = ["free","paid"].includes(p.get("access")) ? p.get("access") : "all";
      UI.workSort = ["favorites","cheers"].includes(p.get("sort")) ? p.get("sort") : "newest";
      UI.workQuery = p.get("q") || "";
      UI.workFilterAsset = (p.get("filterAsset") || "").toUpperCase();
      UI.workFilterAuthor = p.get("author") || "";
      UI.workShownCount = 24;
    }
    if (["styles", "layouts", "works"].includes(App.view)) {
      UI.lastPrimaryView = App.view;
    }
    return {};
  }

  function updateSeoTitle(customTitle) {
    if (customTitle) {
      document.title = `${customTitle} — 手绘风创作社区`;
      return;
    }
    const wc = (App.state && App.state.works && App.state.works.length) || 0;
    const titles = {
      discover: "AI 视觉创作与实测分享 — 手绘风创作社区",
      styles: `${App.styles?.length || 0} 款画风视觉库 — 手绘风创作社区`,
      layouts: `${App.layouts?.length || 0} 款图型与版式库 — 手绘风创作社区`,
      works: `作品与做法（${wc} 件社区作品）— 手绘风创作社区`,
      rankings: "创作者荣誉榜单与作品风云榜 — 手绘风创作社区",
      wallet: "统一积分钱包与资产中心 — 手绘风创作社区",
      auth: "登录 / 注册统一通行证 — 手绘风创作社区",
      skill: "开源画廊与官网在线创作联动 — 手绘风创作社区"
    };
    if (App.view === "work" && UI.activeWorkId) {
      const w = (App.state?.works || []).find((x) => x.id === UI.activeWorkId);
      if (w) {
        document.title = `${w.title} (@${w.authorName}) 作品详情与评论 — Handraw 手绘风社区`;
        return;
      }
    }
    if (App.view === "account") {
      document.title = "账号设置与安全中心 — Handraw 手绘风社区";
      return;
    }
    if (App.view === "profile") {
      const uname = UI.profileUser || App.state?.user?.username || "";
      const prof = uname ? S.getCreatorProfile(uname) : null;
      document.title = `${prof ? `@${prof.authorName} 的个人主页` : "个人主页与账号中心"} — Handraw 手绘风社区`;
      return;
    }
    document.title = titles[App.view] || "Handraw 手绘风社区 2.0 — 画风库 · 图型库 · 作品广场";
  }

  function syncUrl(pushHistory = false) {
    const p = new URLSearchParams();
    p.set("view", App.view);
    if (App.view === "works") {
      if (UI.workScenario) p.set("scenario", UI.workScenario);
      if (UI.workFilterAsset) p.set("filterAsset", UI.workFilterAsset);
      if (UI.workFilterAuthor) p.set("author", UI.workFilterAuthor);
      if (UI.workFormat !== "all") p.set("format", UI.workFormat);
      if (UI.workAccess !== "all") p.set("access", UI.workAccess);
      if (UI.workSort !== "newest") p.set("sort", UI.workSort);
      if (UI.workQuery.trim()) p.set("q", UI.workQuery.trim());
    } else if (App.view === "rankings") {
      if (UI.rankTab) p.set("rtab", UI.rankTab);
      if (UI.rankPeriod) p.set("period", UI.rankPeriod);
    } else if (App.view === "work" && UI.activeWorkId) {
      p.set("id", UI.activeWorkId);
    } else if (App.view === "account") {
      p.set("section", UI.accountSection || "profile");
    } else if (App.view === "profile") {
      const uname = UI.profileUser || (App.state?.user?.username && App.state.user.username !== "guest" ? App.state.user.username : "");
      if (uname) p.set("user", uname);
      if (UI.profileTab && UI.profileTab !== "works") p.set("ptab", UI.profileTab);
    } else if (App.view === "device") {
      const rawCode = (new URLSearchParams(window.location.search).get("code") || "").trim().toUpperCase();
      if (/^[A-Z0-9-]{4,20}$/.test(rawCode)) {
        p.set("code", rawCode);
      }
    }
    const next = `${window.location.pathname}?${p.toString()}`;
    if (pushHistory && window.location.search !== `?${p.toString()}`) {
      UI.navHistoryDepth += 1;
      window.history.pushState({ view: App.view }, "", next);
    } else {
      window.history.replaceState({ view: App.view }, "", next);
    }
    updateSeoTitle();
  }

  function navigateBack(fallbackView = "styles", extra = {}) {
    if (UI.navHistoryDepth > 0 && window.history.length > 1) {
      UI.navHistoryDepth = Math.max(0, UI.navHistoryDepth - 1);
      window.history.back();
      return;
    }
    switchView(fallbackView, extra);
  }

  function switchView(nextView, extra = {}) {
    S.closeModal();
    if (nextView === "collections") {
      const curU = (App.state && App.state.user && App.state.user.username && App.state.user.username !== "guest") ? App.state.user.username : "";
      if (App.state && App.state.loggedIn && curU) {
        openProfilePage(curU, "collections");
      } else {
        openAuthPage("登录后查看与同步你的云端收藏夹", () => {
          if (App.state && App.state.user && App.state.user.username) {
            openProfilePage(App.state.user.username, "collections");
          }
        });
      }
      return;
    }
    if (["styles", "layouts", "works"].includes(App.view) && nextView !== App.view) {
      UI.lastPrimaryView = App.view;
    } else if (["styles", "layouts", "works"].includes(nextView)) {
      UI.lastPrimaryView = nextView;
    }
    const viewChanged = App.view !== nextView;
    if (viewChanged && ["styles","layouts"].includes(nextView)) UI.assetQuery = "";
    App.view = nextView;
    UI.shownCount = UI.pageSize;
    if (extra.filterAsset !== undefined) UI.workFilterAsset = extra.filterAsset;
    if (extra.filterAuthor !== undefined) UI.workFilterAuthor = extra.filterAuthor;
    if (nextView === "works" && (extra.filterAsset !== undefined || extra.filterAuthor !== undefined)) {
      UI.workFormat="all"; UI.workAccess="all"; UI.workQuery=""; UI.workShownCount=24;
    }
    if (extra.rankTab !== undefined) UI.rankTab = extra.rankTab;
    if (extra.rankPeriod !== undefined) UI.rankPeriod = extra.rankPeriod;
    if (extra.shareItem !== undefined) UI.walletShareItem = extra.shareItem;
    syncUrl(viewChanged);
    S.saveState();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openAssetPage(assetId, subTab = "") {
    S.goToAssetPage(assetId, subTab);
  }

  function openWorkPage(workId, imgIndex = 0, focusComment = false) {
    const wid = String(workId || "").trim();
    if (!wid) return;
    const disc = (App.state && App.state.discussions && App.state.discussions[wid]) || null;
    const tid = disc ? disc.topicId : null;
    if (tid) {
      window.location.href = channelUrl("forum", { view: "topic", id: tid, ...(focusComment ? { focus: "comment" } : {}) });
    } else {
      S.goToWorkPage(wid, focusComment);
    }
  }

  function formatArticleUpdated(ms) {
    const t = Number(ms) || 0;
    if (!t) return "刚刚";
    const diff = Date.now() - t;
    if (diff < 60 * 1000) return "刚刚";
    if (diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 24 * 60 * 60 * 1000) return `${Math.floor(diff / 3600000)} 小时前`;
    if (diff < 30 * 24 * 60 * 60 * 1000) return `${Math.floor(diff / 86400000)} 天前`;
    try {
      return new Date(t).toLocaleDateString("zh-CN");
    } catch (_) {
      return "较早";
    }
  }

  function openProfilePage(username, ptab = "works") {
    if (ptab === "account") { switchView("account"); return; }
    S.closeModal();
    const targetUser = String(username || (App.state && App.state.user && App.state.user.username) || "").trim();
    if (!targetUser || targetUser === "guest") {
      openAuthPage("登录后即可查看与管理你的个人主页");
      return;
    }
    if (["styles", "layouts", "works"].includes(App.view)) {
      UI.lastPrimaryView = App.view;
    }
    let cleanTab = ["works", "resources", "topics", "articles", "collections"].includes(ptab) ? ptab : "works";
    if (["assets", "styles", "layouts"].includes(ptab)) {
      cleanTab = "resources";
      UI.profileResourceFilter = ptab === "layouts" ? "layouts" : "styles";
    } else if (ptab === "resources") {
      UI.profileResourceFilter = "all";
    }
    const isMe = Boolean(App.state && App.state.loggedIn && App.state.user && App.state.user.username && App.state.user.username === targetUser);
    if (cleanTab === "articles" && isMe) {
      window.location.href = channelUrl("studio", { view: "articles-all", page: 1 });
      return;
    }
    if (!isMe && ["collections", "account", "articles"].includes(cleanTab)) {
      cleanTab = "works";
    }
    const isEntering = App.view !== "profile" || UI.profileUser !== targetUser || UI.profileTab !== cleanTab;
    App.view = "profile";
    UI.profileUser = targetUser;
    UI.profileTab = cleanTab;
    syncUrl(isEntering);
    S.saveState();
    if (isEntering) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function openAuthPage(reasonText = "", onSuccess = null) {
    S.closeModal();
    if (App.view !== "auth") {
      UI.authReturnSnapshot = {
        view: App.view,
        activeWorkId: UI.activeWorkId,
        profileUser: UI.profileUser,
        profileTab: UI.profileTab,
        accountSection: UI.accountSection,
        deviceCode: App.view === "device" ? (new URLSearchParams(window.location.search).get("code") || "").trim() : ""
      };
    }
    UI.authReason = reasonText || "";
    UI.authOnSuccess = onSuccess || null;
    App.view = "auth";
    syncUrl(true);
    S.saveState();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  window.addEventListener("popstate", () => {
    parseInitialUrl();
    S.saveState();
  });

  window.HANDRAW_MAIN_SWITCH_VIEW = switchView;
  window.HANDRAW_MAIN_OPEN_ASSET = openAssetPage;
  window.HANDRAW_MAIN_OPEN_WORK = openWorkPage;
  window.HANDRAW_MAIN_OPEN_PROFILE = openProfilePage;
  window.HANDRAW_MAIN_OPEN_AUTH = openAuthPage;
  window.HANDRAW_MAIN_GLOBAL_SEARCH = (q) => {
    UI.assetQuery = q;
    UI.workQuery = q;
    if (!["styles", "layouts", "works"].includes(App.view)) {
      App.view = "styles";
      syncUrl(true);
    }
    renderMain();
  };

  function openCreatorCard(username) {
    openProfilePage(username, "works");
  }

  function renderMyHonorStatusCard(actionButtonsHtml) {
    return `
      <div class="hw-product-actions">
        ${actionButtonsHtml}
      </div>
    `;
  }

  /* ======================== RENDER ENTRY ======================== */
  function renderMain() {
    const root = document.getElementById("main-app-root");
    if (!root || !App.state) return;

    // Product-browse layout class only applies to styles/layouts/works.
    const isBrowse = ["styles", "layouts", "works"].includes(App.view);
    root.classList.toggle("hw-product-browse", isBrowse);
    root.classList.toggle("hw-home-feed-root", App.view === "discover");

    if (window.HandrawAccountTools?.views.has(App.view)) {
      window.HandrawAccountTools.render(root, App.view);
      return;
    }

    if (window.HandrawDeviceAuth?.views.has(App.view)) {
      window.HandrawDeviceAuth.render(root, App.view);
      return;
    }

    if (App.view === "discover") {
      if (window.HandrawMixedFeed?.render) {
        window.HandrawMixedFeed.render(root);
      } else if (window.HandrawDiscovery?.render) {
        window.HandrawDiscovery.render(root);
      } else {
        root.innerHTML = `<div style="padding:48px 0;text-align:center;color:var(--ink-muted);">发现页正在加载…</div>`;
      }
    }
    else if (App.view === "styles") renderAssetCatalog(root, "style");
    else if (App.view === "layouts") renderAssetCatalog(root, "layout");
    else if (App.view === "works") renderWorksSquare(root);
    else if (App.view === "rankings") renderRankingsHall(root);
    else if (App.view === "collections") {
      const curU = (App.state && App.state.user && App.state.user.username && App.state.user.username !== "guest") ? App.state.user.username : "";
      if (App.state && App.state.loggedIn && curU) {
        openProfilePage(curU, "collections");
        syncUrl(false);
      } else {
        openAuthPage("登录后查看与同步你的云端收藏夹", () => {
          if (App.state && App.state.user && App.state.user.username) {
            openProfilePage(App.state.user.username, "collections");
            syncUrl(false);
          }
        });
        syncUrl(false);
      }
      return;
    }
    else if (App.view === "wallet") renderWalletCenter(root);
    else if (App.view === "work") renderWorkDetailPage(root);
    else if (App.view === "profile") renderCreatorProfilePage(root);
    else if (App.view === "account") renderAccountSettingsPage(root);
    else if (App.view === "auth") renderAuthPage(root);
    else if (App.view === "skill") renderSkillFunnelPage(root);
    else renderAssetCatalog(root, "style");
  }

  /* ======================== 1. STYLES & LAYOUTS CATALOG ======================== */
  function filterAssets(kind, groupKey) {
    const isStyle = kind === "style";
    const list = isStyle ? App.styles : App.layouts;
    const q = UI.assetQuery.trim().toLowerCase();

    return list.filter((item) => {
      if (groupKey === "NEW_RELEASE" && !S.isFreshRelease(item)) return false;
      if (groupKey === "EXCLUSIVE" && item.sourceType !== "exclusive") return false;
      if (groupKey === "COMMUNITY" && item.sourceType !== "community") return false;
      if (groupKey === "HAS_WORKS" && S.getAssetWorkCount(item.id) === 0) return false;
      if (!["ALL", "NEW_RELEASE", "EXCLUSIVE", "COMMUNITY", "HAS_WORKS"].includes(groupKey)) {
        if (isStyle) {
          if (!item.id.startsWith(groupKey + "-")) return false;
        } else {
          if (item.group !== groupKey) return false;
        }
      }
      if (q) {
        const hay = S.resourceSearchText(item);
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  // Removed ``getAssetExposureScore``: it blended freshness, source type and an
  // honour multiplier into catalogue ordering.  Styles and layouts now rank by
  // the single rule in ``S.popularScore`` (published works referencing them).

  function renderAssetCatalog(root, kind) {
    const isStyle = kind === "style";
    let activeGroup = isStyle ? UI.styleGroup : UI.layoutGroup;
    const groups = (isStyle ? S.STYLE_GROUPS : S.LAYOUT_GROUPS)
      .map(g => ({ ...g, count: filterAssets(kind, g.key).length }))
      .filter(g => g.count > 0);
    if (!groups.some(g => g.key === activeGroup)) {
      activeGroup = "ALL";
      if (isStyle) UI.styleGroup = activeGroup;
      else UI.layoutGroup = activeGroup;
    }
    const allItems = isStyle ? App.styles : App.layouts;
    const statsMap = S.getCreatorStatsMap();

    const freshSpotlightItems = !UI.assetQuery.trim() && !UI.spotlightCollapsed
      ? allItems.filter((item) => item.sourceType === "community" && S.isFreshRelease(item))
          .sort(S.compareByRecency).slice(0, 3)
      : [];

    const topCreators = !UI.assetQuery.trim() && !UI.spotlightCollapsed
      ? S.getTopCreators(5, "prolific", UI.rankPeriod) : [];
    const pMeta = getPeriodMeta(UI.rankPeriod);
    const filtered = filterAssets(kind, activeGroup);
    // Repeatedly recomputing usage for both sides of every sort comparison
    // was quadratic in practice on large style/layout catalogs.
    const usageCounts = new Map();
    if (UI.assetSort === "recommended" || UI.assetSort === "hot") {
      for (const item of filtered) usageCounts.set(item.id, S.getAssetWorkCount(item.id));
    }

    filtered.sort((a, b) => {
      if (UI.assetSort === "recommended" || UI.assetSort === "hot") {
        // "recommended" and "hot" merged into the single popularity rule:
        // how many published works reference this style or layout.
        const sb = S.popularScore("style", { ...b, usageCount: usageCounts.get(b.id) || 0 });
        const sa = S.popularScore("style", { ...a, usageCount: usageCounts.get(a.id) || 0 });
        if (sb !== sa) return sb - sa;
      } else if (UI.assetSort === "newest") {
        const af = S.isFreshRelease(a) ? 1 : 0;
        const bf = S.isFreshRelease(b) ? 1 : 0;
        if (bf !== af) return bf - af;
        const rc = S.compareByRecency(a, b);
        if (rc !== 0) return rc;
        const ac = a.sourceType === "community" ? 1 : 0;
        const bc = b.sourceType === "community" ? 1 : 0;
        if (bc !== ac) return bc - ac;
      } else if (UI.assetSort === "exclusive") {
        const ea = a.sourceType === "exclusive" ? 1 : 0;
        const eb = b.sourceType === "exclusive" ? 1 : 0;
        if (eb !== ea) return eb - ea;
      }
      return a.id.localeCompare(b.id, "en");
    });

    const visibleItems = filtered.slice(0, UI.shownCount);
    const remaining = Math.max(0, filtered.length - visibleItems.length);
    const favBucket = isStyle ? "styles" : "layouts";
    const showCommunityStage = !UI.assetQuery.trim() && !UI.spotlightCollapsed;

    const assetCardRatio = (item) => {
      // Prefer actual cover dimensions; a generation target ratio may differ
      // from the saved bitmap and is corrected by its 48px preview later.
      const dims = Array.isArray(item.imageDimensions) ? item.imageDimensions[0] : item.imageDimensions;
      const width = Number(item.imageWidth || item.coverWidth || (dims && dims.width));
      const height = Number(item.imageHeight || item.coverHeight || (dims && dims.height));
      if (width > 0 && height > 0) return width + " / " + height;
      const raw = String(item.imageRatio || item.ratio || item.aspectRatio || "");
      const match = /^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/.exec(raw);
      if (match && Number(match[1]) > 0 && Number(match[2]) > 0)
        return Number(match[1]) + " / " + Number(match[2]);
      const numeric = Number(raw);
      return numeric > 0.2 && numeric < 5 ? numeric + " / 1" : "3 / 4";
    };

    const renderAssetCard = (item) => {
          const wCount = S.getAssetWorkCount(item.id);
          const liked = S.isLiked(item.kind, item.id);
          const likeCnt = S.getLikeCount(item.kind, item);
          const collected = S.isCollected(favBucket, item.id);
          const favCnt = S.getFavoriteCount(item.kind, item);
          const commentCnt = S.getAssetComments(item.id).length;
          const unlocked = S.isUnlocked(item.id, item);
          const isFresh = S.isFreshRelease(item);
          const prof = item.author ? statsMap.get(item.author) : null;
          const cheered = S.isCheered(item.id);
          const displayRatio = assetCardRatio(item);

          let topBadge = "";
          if (isFresh) {
            topBadge = `<span class="hw-card-badge-tl badge-new-release">🆕 新发扶持 · ${esc(item.createdAt || "新入库")}</span>`;
          } else if (item.sourceType === "exclusive") {
            topBadge =
              item.tier === "pro_credit"
                ? `<span class="hw-card-badge-tl badge-exclusive-pro">${unlocked ? "💎 专业版已解锁" : `💎 专业独占 · ${item.unlockCost}积分`}</span>`
                : `<span class="hw-card-badge-tl badge-exclusive-free">🔒 登录免费独占</span>`;
          } else if (item.sourceType === "community") {
            topBadge = `<span class="hw-card-badge-tl badge-community">${item.unlockCost > 0 && !unlocked ? `✨ 共创 · ${item.unlockCost}积分` : "✨ 社区共创"}</span>`;
          }

          const contributorHtml =
            item.sourceType === "community" && prof && UI.density !== "compact"
              ? `
                <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:7px;padding:4px 7px;background:var(--paper-bg);border-radius:7px;">
                  <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                    ${S.creatorAvatarHtml(prof, "sm")}
                    <span style="max-width:78px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(prof.authorName)}</span>
                    <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:1px 5px;">${esc(prof.honor.shortBadge)}</span>
                  </button>
                  <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-asset="${esc(item.id)}" title="为贡献者送上鼓励">
                    👏 ${item.cheers ?? 0}
                  </button>
                </div>
              `
              : "";

          return `
            <article class="hw-card ${isFresh ? "is-fresh-highlight" : ""}" data-asset-card="${esc(item.id)}">
              <div class="hw-card-media hw-progressive-media" data-open-asset="${esc(item.id)}" data-hw-refine-ratio="true" style="aspect-ratio:${displayRatio}">
                ${topBadge}
                <button type="button" class="hw-card-fav-btn ${collected ? "is-collected" : ""}" data-fav-asset="${esc(item.id)}" data-social-action="collect" data-social-type="${isStyle ? "style" : "layout"}" data-social-id="${esc(item.id)}" data-social-role="icon-only" title="收藏此${isStyle ? "画风" : "图型"}">
                  ${collected ? "♥" : "♡"}
                </button>
                <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" loading="lazy" />
                ${wCount > 0 ? `<span class="hw-card-workcount">${wCount} 作品</span>` : ""}
              </div>
              <div class="hw-card-body">
                <div class="hw-card-code-row">
                  <span class="hw-card-code">${esc(item.id)}</span>
                  <span class="hw-card-group-tag">${esc(S.groupShortLabel(item))}</span>
                </div>
                <h3 class="hw-card-title" data-open-asset="${esc(item.id)}">${esc(item.name)}</h3>
                <p class="hw-card-desc">${esc(item.description || "")}</p>
                ${contributorHtml}
                ${
                  UI.density !== "compact"
                    ? `
                      <div class="hw-card-actions" style="display:flex;align-items:center;justify-content:space-between;gap:5px;margin-top:8px;padding-top:7px;border-top:1px dashed var(--line-soft);">
                        <button type="button" class="btn btn-sm hw-action-btn ${liked ? "btn-primary is-active" : ""}" data-like-asset="${esc(item.id)}" data-social-action="like" data-social-type="${isStyle ? "style" : "layout"}" data-social-id="${esc(item.id)}" title="点赞此${isStyle ? "画风" : "图型"}">
                          👍 <span class="hw-social-count">${likeCnt}</span>
                        </button>
                        <button type="button" class="btn btn-sm hw-action-btn ${collected ? "btn-primary is-active" : ""}" data-fav-asset="${esc(item.id)}" data-social-action="collect" data-social-type="${isStyle ? "style" : "layout"}" data-social-id="${esc(item.id)}" title="收藏此${isStyle ? "画风" : "图型"}">
                          <span class="hw-fav-icon">${collected ? "♥" : "♡"}</span> <span class="hw-social-count">${favCnt}</span>
                        </button>
                        <button type="button" class="btn btn-sm hw-action-btn" data-comment-asset="${esc(item.id)}" title="查看与发表评论">
                          💬 <span class="hw-social-count">${commentCnt}</span>
                        </button>
                      </div>
                      <div class="hw-card-footer">
                        <button type="button" class="btn btn-sm" style="padding:2px 8px;font-size:11.5px;" data-open-asset="${esc(item.id)}">
                          ${wCount > 0 ? `🖼️ 看作品 (${wCount})` : "💬 详情与评论"}
                        </button>
                        <a class="btn btn-sm btn-primary" style="padding:2px 8px;font-size:11.5px;" href="${esc(channelUrl("studio", isStyle ? { style: item.id } : { layout: item.id }))}">
                          去创作 ↗
                        </a>
                      </div>
                    `
                    : ""
                }
              </div>
            </article>
          `;
    };

    root.innerHTML = `
      <section class="hw-catalog-actions" aria-label="${isStyle ? "画风" : "图型"}频道">
        <button type="button" class="btn btn-primary btn-sm" id="hero-btn-contribute">＋ 发布新${isStyle ? "画风" : "图型"}</button>
      </section>

      ${
        UI.assetQuery.trim()
          ? ""
          : UI.spotlightCollapsed
          ? `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;background:var(--paper-card);border:1px solid var(--line-soft);border-radius:10px;padding:8px 14px;margin-bottom:14px;font-size:12.5px;">
              <span>新资源与贡献者</span>
              <div style="display:flex;gap:6px;">
                <button type="button" class="btn btn-sm btn-gold" data-jump-rankings="creators">完整榜单 ↗</button>
                <button type="button" class="btn btn-sm" id="btn-toggle-spotlight">展开曝光席与荣誉榜 ▾</button>
              </div>
            </div>
          `
          : `
            <section class="hw-community-stage hw-reveal-section" aria-label="新发曝光与共创荣誉榜">
              <!-- Left: Newly Published Styles / Layouts Exposure Rail -->
              <div class="hw-spotlight-panel is-fresh-jade">
                <div class="hw-panel-head">
                  <div>
                    <div class="hw-panel-title-wrap">
                      <h2 class="hw-panel-title">🌱 新发${isStyle ? "画风" : "图型"} · 72h 首发曝光席</h2>
                      <span class="hw-honor-badge honor-pioneer">新发流量扶持</span>
                    </div>
                    <div class="hw-panel-sub">最新由社区创作者提炼贡献的${isStyle ? "画风" : "图型"}，享有置顶曝光席位，快给作者点个鼓励吧！</div>
                  </div>
                </div>

                <div class="hw-new-release-grid">
                  ${freshSpotlightItems.length ? "" : '<p class="hw-empty-state">最近 72 小时还没有新资源。你可以浏览下方目录，或分享自己的创作。</p>'}
                  ${freshSpotlightItems
                    .map((item) => {
                      const prof = statsMap.get(item.author) || S.getCreatorProfile(item.author);
                      const h = prof.honor;
                      const cheered = S.isCheered(item.id);
                      return `
                        <article class="hw-new-card" data-spot-asset="${esc(item.id)}">
                          <div class="hw-new-card-media hw-progressive-media" data-open-asset="${esc(item.id)}">
                            <span class="hw-card-badge-tl badge-new-release">🆕 ${esc(item.createdAt || "新发")}</span>
                            <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" loading="lazy" />
                            <span class="hw-new-card-time">${esc(item.id)}</span>
                          </div>
                          <div class="hw-new-card-body">
                            <h3 class="hw-card-title" style="font-size:13.5px;" data-open-asset="${esc(item.id)}">${esc(item.name)}</h3>
                            <p class="hw-card-desc" style="margin:0;font-size:11.6px;">${esc(item.description || "")}</p>
                            <div style="margin-top:auto;padding-top:6px;border-top:1px dashed var(--line-soft);display:flex;align-items:center;justify-content:space-between;gap:6px;">
                              <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                                ${S.creatorAvatarHtml(prof, "sm")}
                                <span style="max-width:74px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(prof.authorName)}</span>
                                <span class="hw-honor-badge ${esc(h.sealClass)}" style="padding:1px 5px;font-size:10px;">${esc(h.shortBadge)}</span>
                              </button>
                              <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-asset="${esc(item.id)}" title="为新发布的共创资产送上鼓励">
                                👏 ${item.cheers ?? 0}
                              </button>
                            </div>
                          </div>
                        </article>
                      `;
                    })
                    .join("")}
                </div>
              </div>

              <!-- Right: Embedded Prolific Creator Honor Leaderboard -->
              <div class="hw-spotlight-panel is-warm-gold">
                <div class="hw-panel-head">
                  <div>
                    <div class="hw-panel-title-wrap">
                      <h2 class="hw-panel-title">🏆 共创荣誉榜 前五名</h2>
                      ${renderPeriodSwitchHtml(true)}
                    </div>
                    <div class="hw-panel-sub">${
                      UI.rankPeriod === "all"
                        ? "历史累计高产主理人，享最高 1.45× 推荐加权"
                        : `${esc(pMeta.shortPrefix)}活跃贡献榜（不叠加历史殿堂权重，新人公平上榜）`
                    }</div>
                  </div>
                  <div style="display:flex;gap:6px;">
                    <button type="button" class="btn btn-sm btn-gold" data-jump-rankings="creators">完整榜单 ↗</button>
                    <button type="button" class="btn btn-sm" id="btn-toggle-spotlight" title="收起展台">收起</button>
                  </div>
                </div>

                <div class="hw-mini-rank-list">
                  ${topCreators
                    .map((c, idx) => {
                      const rankCls = idx < 3 ? `rank-${idx + 1}` : "";
                      const isMe = App.state.loggedIn && c.username === App.state.user.username;
                      const pubVal = UI.rankPeriod === "all" ? c.totalPublished : c.periodPublished;
                      const assetVal =
                        UI.rankPeriod === "all"
                          ? c.styles.length + c.layouts.length
                          : c.periodStyles.length + c.periodLayouts.length;
                      const workVal = UI.rankPeriod === "all" ? c.works.length : c.periodWorks.length;
                      const cheerVal = UI.rankPeriod === "all" ? c.totalCheers : c.periodCheers;
                      return `
                        <div class="hw-mini-rank-row" data-open-creator="${esc(c.username)}" title="点击查看 @${esc(c.authorName)} 的荣誉主页与全部作品">
                          <span class="hw-rank-num ${rankCls}">${String(idx + 1).padStart(2, "0")}</span>
                          ${S.creatorAvatarHtml(c, "sm")}
                          <div style="min-width:0;flex:1;">
                            <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;">
                              <strong style="font-size:12.8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(c.authorName)}${isMe ? " (我)" : ""}</strong>
                              <span class="hw-honor-badge ${esc(c.honor.sealClass)}" style="font-size:10.5px;padding:1px 6px;">${esc(c.honor.badge)}</span>
                            </div>
                            <div style="font-size:11.2px;color:var(--ink-muted);margin-top:1px;">
                              ${esc(pMeta.shortPrefix)}新发 <strong>${pubVal}</strong> 项（资产 ${assetVal} · 作品 ${workVal}）· 👏 ${cheerVal}
                            </div>
                          </div>
                          <span class="hw-boost-pill">${esc(c.honor.boostText)}</span>
                        </div>
                      `;
                    })
                    .join("")}
                </div>
              </div>
            </section>
          `
      }

      <div class="hw-filter-bar">
        <div class="hw-pills-row" id="catalog-group-pills">
          ${groups
            .map((g) => {
              const cnt = g.count;
              return `
                <button type="button" class="hw-pill ${activeGroup === g.key ? "is-active" : ""}" data-group="${esc(g.key)}">
                  ${esc(g.label)} <span class="hw-pill-count">${cnt}</span>
                </button>
              `;
            })
            .join("")}
        </div>

        <div class="hw-controls-row">
          <div class="hw-controls-left">
            <input type="search" class="hw-input" id="catalog-search" style="width:248px;" value="${esc(UI.assetQuery)}" placeholder="过滤编号（如 ${isStyle ? "FA-001 / USR-S05 / FX-001" : "SC-021 / USR-L04 / LX-001"}）或作者…" />
            <select class="hw-select" id="catalog-sort">
              <option value="recommended" ${UI.assetSort === "recommended" ? "selected" : ""}>🔥 热门（被作品采用最多）</option>
              <option value="newest" ${UI.assetSort === "newest" ? "selected" : ""}>🌱 最新入库优先</option>
              <option value="exclusive" ${UI.assetSort === "exclusive" ? "selected" : ""}>🔒 官网在线独占置顶</option>
              <option value="code" ${UI.assetSort === "code" ? "selected" : ""}>🔢 按编号字母顺序</option>
            </select>
            <span style="font-size:12.5px;color:var(--ink-muted);">共筛出 <strong>${filtered.length}</strong> 项</span>
          </div>

          <div class="hw-controls-right">
            <span style="font-size:12px;color:var(--ink-muted);margin-left:6px;">浏览密度：</span>
            <div class="hw-segmented" id="catalog-density">
              <button type="button" class="hw-seg-btn ${UI.density === "compact" ? "is-active" : ""}" data-density="compact">紧凑 8列</button>
              <button type="button" class="hw-seg-btn ${UI.density === "standard" ? "is-active" : ""}" data-density="standard">标准 5列</button>
              <button type="button" class="hw-seg-btn ${UI.density === "large" ? "is-active" : ""}" data-density="large">大图 3列</button>
            </div>
          </div>
        </div>
      </div>

      ${S.renderMasonry(visibleItems.map(renderAssetCard), UI.density)}

      ${
        remaining > 0
          ? `
            <div style="text-align:center;margin-top:24px;">
              <button type="button" class="btn btn-primary" id="btn-load-more-assets">
                展开更多${isStyle ? "画风" : "图型"}（还有 ${remaining} 项）
              </button>
            </div>
          `
          : ""
      }
    `;

    root.querySelector("#hero-btn-contribute").onclick = () => S.goToCurationShare({ kind: UI.view === "layouts" ? "layout" : "style" });
    const catPubBtn = root.querySelector("#catalog-btn-publish-asset");
    if (catPubBtn) catPubBtn.onclick = () => S.goToCurationShare({ kind: UI.view === "layouts" ? "layout" : "style" });
    const spotContrib = root.querySelector("#spot-btn-contribute");
    if (spotContrib) spotContrib.onclick = () => S.goToCurationShare({ kind: UI.view === "layouts" ? "layout" : "style" });

    const toggleSpotBtn = root.querySelector("#btn-toggle-spotlight");
    if (toggleSpotBtn) {
      toggleSpotBtn.onclick = () => {
        UI.spotlightCollapsed = !UI.spotlightCollapsed;
        renderMain();
      };
    }
    bindPeriodSwitch(root);

    root.querySelectorAll("[data-jump-rankings]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        switchView("rankings", { rankTab: btn.getAttribute("data-jump-rankings") || "creators" });
      };
    });

    root.querySelectorAll("[data-open-creator]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openCreatorCard(el.getAttribute("data-open-creator"));
      };
    });

    root.querySelectorAll("[data-cheer-asset]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        S.toggleCheerItem("asset", btn.getAttribute("data-cheer-asset"));
      };
    });

    root.querySelectorAll("[data-group]").forEach((btn) => {
      btn.onclick = () => {
        const g = btn.getAttribute("data-group");
        if (isStyle) UI.styleGroup = g;
        else UI.layoutGroup = g;
        UI.shownCount = UI.pageSize;
        renderMain();
      };
    });

    const searchInput = root.querySelector("#catalog-search");
    let catalogSearchTimer = null;
    let catalogComposing = false;
    const scheduleCatalogSearch = () => {
      UI.assetQuery = searchInput.value;
      clearTimeout(catalogSearchTimer);
      if (catalogComposing) return;
      catalogSearchTimer = setTimeout(() => {
        if (!searchInput.isConnected || App.view !== (isStyle ? "styles" : "layouts")) return;
        const start = searchInput.selectionStart;
        const end = searchInput.selectionEnd;
        UI.shownCount = UI.pageSize;
        renderMain();
        const next = document.getElementById("catalog-search");
        if (next) {
          next.focus();
          if (start != null && end != null) next.setSelectionRange(start, end);
        }
      }, 180);
    };
    searchInput.addEventListener("compositionstart", () => {
      catalogComposing = true;
      clearTimeout(catalogSearchTimer);
    });
    searchInput.addEventListener("compositionend", () => {
      catalogComposing = false;
      scheduleCatalogSearch();
    });
    searchInput.oninput = scheduleCatalogSearch;

    root.querySelector("#catalog-sort").onchange = (e) => {
      UI.assetSort = e.target.value;
      renderMain();
    };

    root.querySelectorAll("[data-density]").forEach((btn) => {
      btn.onclick = () => {
        UI.density = btn.getAttribute("data-density");
        renderMain();
      };
    });

    root.querySelectorAll("[data-like-asset]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const id = btn.getAttribute("data-like-asset");
        const item = App.resourceMap.get(id);
        S.toggleLike(kind, id, `${id} ${item ? item.name : ""}`);
      };
    });

    root.querySelectorAll("[data-fav-asset]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const id = btn.getAttribute("data-fav-asset");
        const item = App.resourceMap.get(id);
        S.toggleCollect(favBucket, id, `${id} ${item ? item.name : ""}`);
      };
    });

    root.querySelectorAll("[data-comment-asset]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        openAssetPage(btn.getAttribute("data-comment-asset"), "comments");
      };
    });

    root.querySelectorAll("[data-open-asset]").forEach((el) => {
      el.onclick = () => openAssetPage(el.getAttribute("data-open-asset"));
    });

    // New cards are bound in isolation; previously rendered cards and loaded
    // <img> elements stay mounted and do not have to reload or decode.
    function bindNewAssetCard(card) {
      card.querySelectorAll("[data-open-creator]").forEach((el) => {
        el.onclick = (e) => { e.stopPropagation(); openCreatorCard(el.getAttribute("data-open-creator")); };
      });
      card.querySelectorAll("[data-cheer-asset]").forEach((btn) => {
        btn.onclick = (e) => { e.stopPropagation(); S.toggleCheerItem("asset", btn.getAttribute("data-cheer-asset")); };
      });
      card.querySelectorAll("[data-like-asset]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const id = btn.getAttribute("data-like-asset");
          const item = App.resourceMap.get(id);
          S.toggleLike(kind, id, `${id} ${item ? item.name : ""}`);
        };
      });
      card.querySelectorAll("[data-fav-asset]").forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          const id = btn.getAttribute("data-fav-asset");
          const item = App.resourceMap.get(id);
          S.toggleCollect(favBucket, id, `${id} ${item ? item.name : ""}`);
        };
      });
      card.querySelectorAll("[data-comment-asset]").forEach((btn) => {
        btn.onclick = (e) => { e.stopPropagation(); openAssetPage(btn.getAttribute("data-comment-asset"), "comments"); };
      });
      card.querySelectorAll("[data-open-asset]").forEach((el) => {
        el.onclick = () => openAssetPage(el.getAttribute("data-open-asset"));
      });
    }

    const loadMoreBtn = root.querySelector("#btn-load-more-assets");
    if (loadMoreBtn) {
      loadMoreBtn.onclick = () => {
        const waterfall = root.querySelector(".hw-waterfall");
        const columns = waterfall ? Array.from(waterfall.querySelectorAll(".hw-wf-col")) : [];
        if (!columns.length) { UI.shownCount += 80; renderMain(); return; }
        const oldCount = Math.min(UI.shownCount, filtered.length);
        const nextCount = Math.min(filtered.length, oldCount + 40);
        for (let idx = oldCount; idx < nextCount; idx++) {
          const wrapper = document.createElement("template");
          wrapper.innerHTML = renderAssetCard(filtered[idx]);
          const card = wrapper.content.firstElementChild;
          if (!card) continue;
          columns[idx % columns.length].appendChild(card);
          bindNewAssetCard(card);
        }
        UI.shownCount = nextCount;
        if (nextCount >= filtered.length) {
          loadMoreBtn.parentElement?.remove();
        } else {
          loadMoreBtn.textContent = `展开更多${isStyle ? "画风" : "图型"}（还有 ${filtered.length - nextCount} 项）`;
        }
        window.HandrawImageLoader?.scan(waterfall);
      };
    }
  }

  function renderWorksSquare(root) {
    const B = window.HandrawWorksBrowser;
    const allWorks = App.state.works || [];
    const filters = {
      format: UI.workFormat || "all",
      access: UI.workAccess || "all",
      query: UI.workQuery || "",
      asset: UI.workFilterAsset || "",
      author: UI.workFilterAuthor || "",
      scenario: UI.workScenario || "",
      sort: UI.workSort === "newest" || UI.workSort === "popular" || UI.workSort === "favorites" || UI.workSort === "cheers"
        ? UI.workSort : "newest"
    };

    const filterKey = `${filters.format}|${filters.access}|${filters.sort}|${filters.asset}|${filters.author}|${filters.scenario}|${filters.query}`;

    if (typeof S.apiJson === "function" && (!UI.worksFeed || UI.worksFeed.key !== filterKey)) {
      const prevCounts = UI.worksFeed?.counts || B.countFormats(allWorks);
      UI.worksFeed = {
        key: filterKey,
        items: [],
        nextCursor: null,
        hasMore: false,
        counts: prevCounts,
        total: 0,
        loading: true,
        loadingMore: false,
        error: null,
      };

      const params = new URLSearchParams();
      params.set("limit", "24");
      if (filters.format && filters.format !== "all") params.set("format", filters.format);
      if (filters.access && filters.access !== "all") params.set("access", filters.access);
      if (filters.sort) params.set("sort", filters.sort);
      if (filters.asset) params.set("asset", filters.asset);
      if (filters.author) params.set("author", filters.author);
      if (filters.scenario) params.set("scenario", filters.scenario);
      if (filters.query) params.set("q", filters.query);

      S.apiJson(`/api/works/feed?${params.toString()}`)
        .then((res) => {
          if (UI.worksFeed && UI.worksFeed.key === filterKey) {
            UI.worksFeed.loading = false;
            if (res && res.ok) {
              UI.worksFeed.items = res.items || [];
              UI.worksFeed.counts = res.counts || prevCounts;
              UI.worksFeed.total = typeof res.total === "number" ? res.total : (res.items || []).length;
              UI.worksFeed.nextCursor = res.nextCursor || null;
              UI.worksFeed.hasMore = Boolean(res.hasMore);
              (res.items || []).forEach((w) => {
                const idx = App.state.works.findIndex((x) => String(x.id) === String(w.id));
                if (idx >= 0) App.state.works[idx] = w;
                else App.state.works.push(w);
              });
            } else {
              UI.worksFeed.error = res?.error || "加载作品失败";
            }
            if (App.view === "works") renderMain();
          }
        })
        .catch((err) => {
          if (UI.worksFeed && UI.worksFeed.key === filterKey) {
            UI.worksFeed.loading = false;
            UI.worksFeed.error = err.message || "加载作品失败";
            if (App.view === "works") renderMain();
          }
        });
    }

    const counts = (UI.worksFeed && UI.worksFeed.counts) || B.countFormats(allWorks);
    if (!counts[filters.format]) filters.format = UI.workFormat = "all";
    const filtered = B.select(allWorks, filters, App.resourceMap, S);
    const shownCount = Math.max(24, Number(UI.workShownCount) || 24);
    const visible = (UI.worksFeed && UI.worksFeed.key === filterKey && (UI.worksFeed.items.length || !UI.worksFeed.loading))
      ? UI.worksFeed.items
      : filtered.slice(0, shownCount);
    const hasFilters = Boolean(
      filters.format !== "all" || filters.access !== "all" ||
      String(filters.query).trim() || filters.asset || filters.author || filters.scenario
    );
    const selectedAsset = filters.asset && App.resourceMap ? App.resourceMap.get(filters.asset) : null;
    const author = filters.author ? S.getCreatorProfile(filters.author) : null;
    const assetImage = selectedAsset && (selectedAsset.thumbUrl || selectedAsset.image || selectedAsset.cover || "");

    const formatButton = (key, label, count) => key === "all" || count > 0
      ? `<button type="button" class="hw-wb-tab ${filters.format === key ? "is-active" : ""}" data-wb-format="${esc(key)}" aria-pressed="${filters.format === key}">${esc(label)} <span class="hw-wb-tab-count">${count}</span></button>`
      : "";

    const colCount = (B.getColumnCount && typeof window !== "undefined")
      ? B.getColumnCount(window.innerWidth)
      : 4;
    const viewportHeight = (typeof window !== "undefined" && window.innerHeight) || 800;

    const candidates = B.unpackWorkCandidates ? B.unpackWorkCandidates(visible) : visible.map((w) => ({
      itemKey: `${w.id}_0`,
      workId: String(w.id),
      imgIndex: 0,
      totalImages: 1,
      imageUrl: (B.imagesFor(w)[0] || ""),
      aspectRatio: (B.parseAspectRatio ? B.parseAspectRatio(w, 0) : 1.0),
      work: w,
      batchId: w.batchId,
      batchTotal: w.batchTotal || 1,
      batchIndex: w.batchIndex || 1,
      resourceCodes: B.normalizeResourceCodes ? B.normalizeResourceCodes(w) : new Set(),
      styles: Array.isArray(w.styles) ? w.styles : [],
      layout: w.layout || ""
    }));

    const layoutResult = (B.layoutWorksMasonry)
      ? B.layoutWorksMasonry(candidates, { colCount, viewportHeight })
      : { placed: candidates.map((c, i) => ({ ...c, col: i % colCount, top: 0, height: 300, extraMargin: 0 })), remainingQueue: [] };

    UI._worksMasonryPlaced = layoutResult.placed;
    UI._worksMasonryQueue = layoutResult.remainingQueue;
    UI._worksMasonryColCount = colCount;

    const renderCardHtml = (item) => {
      const w = item.work || item;
      const id = String(w.id);
      const itemKey = item.itemKey || `${id}_0`;
      const imgIdx = item.imgIndex != null ? item.imgIndex : 0;
      const totalImgs = item.totalImages || 1;
      const imageUrl = item.imageUrl || (B.imagesFor(w)[0] || "");
      const ar = item.aspectRatio || (B.parseAspectRatio ? B.parseAspectRatio(w, imgIdx) : 1.0);
      const disc = (App.state && App.state.discussions && App.state.discussions[id]) || null;
      const tid = disc ? disc.topicId : (w.topicId || null);
      const href = channelUrl("main", { view: "work", id });
      const liked = Boolean(S.isLiked && S.isLiked("work", id));
      const likeCnt = (S.getLikeCount && S.getLikeCount("work", w)) ?? Number(w.likes || 0);
      const collected = Boolean(S.isCollected && S.isCollected("works", id));
      const favCnt = (S.getFavoriteCount && S.getFavoriteCount("work", w)) ?? Number(w.favorites || 0);
      const cmtCnt = (w.comments || []).length;
      const canModerate = Boolean(S.canModerateWork && S.canModerateWork(w));
      const canDelete = Boolean(
        (S.canDeleteWork && S.canDeleteWork(w)) ||
        (App.state.loggedIn && App.state.user && w.author === App.state.user.username)
      );
      const marginStyle = (item.extraMargin && item.extraMargin > 0) ? `margin-top:${item.extraMargin}px;` : "";

      // The gallery shows only the cover. The count refers to media inside
      // this work, not to sibling works from a historical batch.
      const badgeHtml = totalImgs > 1
        ? `<span class="hw-wb-img-badge" aria-label="共 ${totalImgs} 张图片">🖼️ ${totalImgs} 张</span>`
        : "";

      return `
        <article class="hw-wb-card" data-wb-work="${esc(id)}" data-wb-card-key="${esc(itemKey)}" data-wb-author="${esc(item.author || item.authorUsername || w.author || w.author_username || "")}" style="${marginStyle}">
          <a class="hw-wb-media hw-progressive-media" href="${esc(href)}" data-wb-open="${esc(id)}" data-wb-img-idx="${imgIdx}" aria-label="打开作品：${esc(w.title || "未命名作品")}" style="aspect-ratio:${ar};">
            <img data-hw-src="${esc(imageUrl)}" alt="${esc(w.title || "作品图片")}" loading="lazy" />
            ${badgeHtml}
          </a>
          <div class="hw-wb-body">
            <h3 class="hw-wb-title"><a href="${esc(href)}" data-wb-open="${esc(id)}" data-wb-img-idx="${imgIdx}">${esc(w.title || "未命名作品")}</a></h3>
            <div class="hw-wb-meta">
              <button type="button" class="hw-wb-author" data-wb-author="${esc(w.author || "")}">${esc(w.authorName || w.author || "社区作者")}</button>
            </div>
            <div class="hw-wb-actions">
              <button type="button" class="btn btn-sm hw-action-btn ${liked ? "btn-primary is-active" : ""}" data-wb-like="${esc(id)}" data-social-action="like" data-social-type="work" data-social-id="${esc(id)}" aria-label="${liked ? "取消点赞" : "点赞"} ${likeCnt}" aria-pressed="${liked}" title="点赞此作品">👍 <span class="hw-social-count">${likeCnt}</span></button>
              <button type="button" class="btn btn-sm hw-action-btn ${collected ? "btn-primary is-active" : ""}" data-wb-fav="${esc(id)}" data-social-action="collect" data-social-type="work" data-social-id="${esc(id)}" aria-label="${collected ? "取消收藏" : "收藏"} ${favCnt}" aria-pressed="${collected}" title="收藏此作品"><span class="hw-fav-icon">${collected ? "♥" : "♡"}</span> <span class="hw-social-count">${favCnt}</span></button>
              <button type="button" class="btn btn-sm hw-action-btn" data-wb-comment="${esc(id)}" aria-label="评论 ${cmtCnt}" title="查看评论">💬 <span class="hw-social-count">${cmtCnt}</span></button>
              ${canModerate ? `<button type="button" class="btn btn-sm hw-action-btn" data-wb-mod="${w.featured ? "unfeature" : "feature"}" data-wb-id="${esc(id)}">${w.featured ? "取消精选" : "精选"}</button>` : ""}
              ${canDelete ? `<button type="button" class="btn btn-sm hw-action-btn is-danger" data-wb-mod="delete" data-wb-id="${esc(id)}">删除</button>` : ""}
            </div>
          </div>
        </article>`;
    };

    const masonryColsHtml = Array.from({ length: colCount }, (_, c) => {
      const colItems = layoutResult.placed.filter(p => p.col === c);
      return `<div class="hw-wb-col" data-col-index="${c}">${colItems.map(renderCardHtml).join("")}</div>`;
    }).join("");

    const masonryHtml = `<div class="hw-wb-masonry hw-wb-grid" id="hw-wb-masonry" data-columns="${colCount}">${masonryColsHtml}</div>`;

    const totalCount = (UI.worksFeed && UI.worksFeed.key === filterKey && typeof UI.worksFeed.total === "number")
      ? UI.worksFeed.total
      : filtered.length;

    const hasMore = (UI.worksFeed && UI.worksFeed.key === filterKey && typeof S.apiJson === "function")
      ? Boolean(UI.worksFeed.hasMore)
      : (visible.length < filtered.length);

    const emptyHtml = !counts.all
      ? `<div class="hw-wb-empty"><h2>还没有已收录作品</h2><p>作品发布后，会展示在这里。</p><a class="btn btn-sm" href="${esc(channelUrl("forum"))}">先逛逛社区 →</a></div>`
      : `<div class="hw-wb-empty"><p>没有符合当前条件的作品。</p><button type="button" class="btn btn-sm" id="hw-wb-reset-empty">重置筛选</button></div>`;

    const gridHtml = (UI.worksFeed && UI.worksFeed.key === filterKey && UI.worksFeed.loading && !visible.length)
      ? `<div style="text-align:center;padding:48px 20px;color:var(--ink-muted);font-size:14px;">⏳ 正在加载公开作品...</div>`
      : visible.length
        ? masonryHtml
        : emptyHtml;

    root.innerHTML = `
      <section class="hw-works-browser">
        <header class="hw-wb-head">
          <div>
            <h1 class="hw-wb-title-head">作品与做法</h1>
            <p class="hw-wb-sub">浏览社区公开作品，按画风、图型或关键词查找。</p>
          </div>
          <div class="hw-wb-head-actions">
            <a class="btn btn-primary btn-sm" href="${esc(channelUrl("studio", {entry:"quick"}))}">开始创作</a>
            <a class="hw-wb-rank-link" href="${esc(channelUrl("main",{view:"rankings",rtab:"works"}))}" id="hw-wb-rank">作品榜单 ↗</a>
          </div>
        </header>

        <div class="hw-wb-tabs" role="group" aria-label="作品类型">
          ${formatButton("all", "全部作品", counts.all)}
          ${formatButton("single", "单图作品", counts.single)}
          ${formatButton("multi", "多图作品", counts.multi)}
        </div>

        <div class="hw-wb-toolbar"><div class="hw-wb-filters">
          <label class="hw-wb-search-wrap">
            <span class="hw-wb-sr">搜索作品</span>
            <input type="search" id="hw-wb-search" class="hw-wb-search" value="${esc(filters.query)}" placeholder="搜索标题 / 作者 / 编号 / 资源名称" autocomplete="off" />
          </label>
          <button type="button" class="hw-wb-chip" data-wb-picker="style">选择画风</button>
          <button type="button" class="hw-wb-chip" data-wb-picker="layout">选择图型</button>
        </div>
        <div class="hw-wb-options">
          <label>排序<select id="hw-wb-sort"><option value="newest" ${filters.sort === "newest" ? "selected" : ""}>最新发布</option><option value="favorites" ${filters.sort === "favorites" ? "selected" : ""}>最多收藏</option><option value="cheers" ${filters.sort === "cheers" ? "selected" : ""}>最多鼓励</option></select></label>
          ${hasFilters ? `<button type="button" class="hw-wb-reset" id="hw-wb-reset">清除筛选</button>` : ""}
        </div></div>
        <div class="hw-wb-selected" ${!filters.asset && !filters.author && !filters.scenario ? "hidden" : ""}>
          ${filters.scenario ? `<button type="button" class="hw-wb-chip is-active" id="hw-wb-scenario" aria-label="清除场景筛选"><span>场景：${esc(filters.scenario)}</span><span aria-hidden="true">×</span></button>` : ""}
          ${filters.asset ? `<button type="button" class="hw-wb-chip is-active" id="hw-wb-clear-asset" aria-label="清除资源筛选">${assetImage ? `<img data-hw-src="${esc(assetImage)}" alt="${esc(selectedAsset?.name || filters.asset)}" />` : ""}<span>${esc(selectedAsset?.name || "资源")} · ${esc(filters.asset)}</span><span aria-hidden="true">×</span></button>` : ""}
          ${filters.author ? `<button type="button" class="hw-wb-chip is-active" id="hw-wb-author" aria-label="清除作者筛选">作者：${esc(author?.authorName || filters.author)} <span aria-hidden="true">×</span></button>` : ""}
        </div>

        <div class="hw-wb-count" aria-live="polite">共 ${totalCount} 件</div>
        ${gridHtml}
        ${hasMore ? `<div class="hw-wb-more"><button type="button" class="btn btn-sm" id="hw-wb-more" ${UI.worksFeed?.loadingMore ? "disabled" : ""}>${UI.worksFeed?.loadingMore ? "加载中..." : "加载更多"}</button></div>` : ""}
      </section>`;

    const rerender = () => { if (typeof syncUrl === "function") syncUrl(); renderMain(); };
    const change = (fn) => { fn(); UI.workShownCount = 24; rerender(); };
    const clearFilters = () => change(() => {
      UI.workQuery = ""; UI.workFormat = "all"; UI.workAccess = "all";
      UI.workFilterAsset = ""; UI.workFilterAuthor = ""; UI.workScenario = "";
    });
    const rank = root.querySelector("#hw-wb-rank");
    if (rank) rank.onclick = (e) => { e.preventDefault(); switchView("rankings", { rankTab: "works" }); };

    root.querySelectorAll("[data-wb-format]").forEach((el) => {
      el.onclick = () => change(() => { UI.workFormat = el.getAttribute("data-wb-format"); });
    });
    const wbAccess = root.querySelector("#hw-wb-access");
    if (wbAccess) wbAccess.onchange = e => change(() => { UI.workAccess = e.target.value; });
    root.querySelector("#hw-wb-sort").onchange = e => change(() => { UI.workSort=e.target.value; });
    root.querySelectorAll("#hw-wb-reset, #hw-wb-reset-empty").forEach((el) => { el.onclick = clearFilters; });

    root.querySelectorAll("[data-wb-picker]").forEach(btn => {
      btn.onclick = () => S.openAssetPickerModal({ kind:btn.getAttribute("data-wb-picker"), currentId:UI.workFilterAsset,onSelect(value) {
        if (App.view !== "works") return;
        const code = value && typeof value === "object" ? (value.code || value.id || "") : (value || "");
        change(() => { UI.workFilterAsset=String(code); });
      }});
    });
    const clearAsset = root.querySelector("#hw-wb-clear-asset");
    if (clearAsset) clearAsset.onclick = () => change(() => { UI.workFilterAsset=""; });
    const clearScenario = root.querySelector("#hw-wb-scenario");
    if (clearScenario) clearScenario.onclick = () => change(() => { UI.workScenario=""; });
    const authorBtn = root.querySelector("#hw-wb-author");
    if (authorBtn) authorBtn.onclick = (e) => {
      change(() => { UI.workFilterAuthor = ""; });
    };

    const search = root.querySelector("#hw-wb-search");
    if (search) {
      let timer = null;
      let composing = false;
      const queueSearch = () => {
        UI.workQuery = search.value;
        clearTimeout(timer);
        if (composing) return;
        timer = setTimeout(() => {
          if (App.view !== "works" || !search.isConnected) return;
          const start=search.selectionStart,end=search.selectionEnd;
          UI.workShownCount = 24;
          syncUrl();
          renderMain();
          const next = document.getElementById("hw-wb-search");
          if (next) { next.focus(); if(start!==null && end!==null) next.setSelectionRange(start,end); }
        }, 180);
      };
      search.addEventListener("compositionstart", () => { composing = true; clearTimeout(timer); });
      search.addEventListener("compositionend", () => { composing = false; queueSearch(); });
      search.oninput = queueSearch;
    }

    let relayoutRaf = null;
    function scheduleRelayout() {
      if (relayoutRaf) return;
      const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : setTimeout;
      relayoutRaf = raf(() => {
        relayoutRaf = null;
        const masonryEl = document.getElementById("hw-wb-masonry");
        if (!masonryEl) return;
        const curCols = Number(masonryEl.getAttribute("data-columns")) || colCount;
        reLayoutMasonry(curCols);
      }, 16);
    }

    function bindCardElementEvents(card) {
      const wid = card.getAttribute("data-wb-work");
      const imgIdx = Number(card.querySelector("[data-wb-img-idx]")?.getAttribute("data-wb-img-idx")) || 0;
      const w = (UI.worksFeed?.items || allWorks).find((x) => String(x.id) === wid);

      const img = card.querySelector(".hw-wb-media img");
      if (img) {
        const handleImageDimensions = () => {
          if (!img.naturalWidth || !img.naturalHeight) return;
          const realAr = img.naturalWidth / img.naturalHeight;
          const media = card.querySelector(".hw-wb-media");
          if (media) {
            media.style.aspectRatio = `${realAr}`;
          }
          const itemKey = card.getAttribute("data-wb-card-key") || card.getAttribute("data-wb-work");
          const placedItem = (UI._worksMasonryPlaced || []).find((p) => (p.itemKey && p.itemKey === itemKey) || p.workId === itemKey);
          if (placedItem) {
            const oldAr = Number(placedItem.aspectRatio) || 1.0;
            if (Math.abs(oldAr - realAr) > 0.005) {
              placedItem.aspectRatio = realAr;
              if (w) {
                if (!Array.isArray(w.imageDimensions)) w.imageDimensions = [];
                w.imageDimensions[imgIdx] = {
                  width: img.naturalWidth,
                  height: img.naturalHeight,
                  aspectRatio: realAr
                };
              }
              scheduleRelayout();
            }
          }
        };

        if (img.complete && img.naturalWidth > 0) {
          handleImageDimensions();
        } else {
          img.addEventListener("load", handleImageDimensions, { once: true });
        }
      }

      card.querySelectorAll("[data-wb-open]").forEach((a) => {
        a.addEventListener("click", (e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
          e.preventDefault();
          const idx = Number(a.getAttribute("data-wb-img-idx")) || imgIdx;
          openWorkLightbox(wid, idx, false);
        });
      });
      card.querySelectorAll("[data-wb-comment]").forEach((button) => {
        button.onclick = () => openWorkLightbox(wid, imgIdx, true);
      });
      card.querySelectorAll("[data-wb-author]").forEach((button) => {
        button.onclick = () => S.goToCreatorProfile(button.getAttribute("data-wb-author"));
      });
      card.querySelectorAll("[data-wb-like]").forEach((b) => {
        b.onclick = () => {
          if (w) S.toggleLike("work", w.id, w.title);
        };
      });
      card.querySelectorAll("[data-wb-fav]").forEach((b) => {
        b.onclick = () => {
          if (w) S.toggleCollect("works", w.id, w.title);
        };
      });
      card.querySelectorAll("[data-wb-mod]").forEach((b) => {
        b.onclick = async () => {
          const action = b.getAttribute("data-wb-mod");
          if (action === "delete" && !confirm("确定删除这件作品？此操作不可撤销。")) return;
          b.disabled = true;
          try {
            const res = await S.apiJson(`/api/works/${encodeURIComponent(b.getAttribute("data-wb-id"))}/moderate`, { method: "POST", body: { action } });
            if (!res.ok) throw new Error(res.error || "操作失败");
            UI.worksFeed = null;
            await S.refreshFromServer();
            toast(action === "delete" ? "作品已删除" : "作品状态已更新");
            renderMain();
          } catch (err) { toast("操作失败：" + (err.message || err)); }
          finally { if (b.isConnected) b.disabled = false; }
        };
      });
    }

    root.querySelectorAll(".hw-wb-card").forEach(bindCardElementEvents);

    root.querySelectorAll("[data-wb-open]").forEach((a) => {
      a.addEventListener("click", (e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        openWorkLightbox(a.getAttribute("data-wb-open"), 0, false);
      });
    });
    root.querySelectorAll("[data-wb-comment]").forEach(button => {
      button.onclick = () => openWorkLightbox(button.getAttribute("data-wb-comment"),0,true);
    });
    root.querySelectorAll("[data-wb-author]").forEach(button => {
      button.onclick = () => S.goToCreatorProfile(button.getAttribute("data-wb-author"));
    });
    root.querySelectorAll("[data-wb-like]").forEach((b) => {
      b.onclick = () => {
        const wid = b.getAttribute("data-wb-like");
        const w = (UI.worksFeed?.items || allWorks).find((x) => String(x.id) === wid);
        if (w) S.toggleLike("work", w.id, w.title);
      };
    });
    root.querySelectorAll("[data-wb-fav]").forEach((b) => {
      b.onclick = () => {
        const wid = b.getAttribute("data-wb-fav");
        const w = (UI.worksFeed?.items || allWorks).find((x) => String(x.id) === wid);
        if (w) S.toggleCollect("works", w.id, w.title);
      };
    });
    root.querySelectorAll("[data-wb-mod]").forEach((b) => {
      b.onclick = async () => {
        const action = b.getAttribute("data-wb-mod");
        if (action === "delete" && !confirm("确定删除这件作品？此操作不可撤销。")) return;
        b.disabled = true;
        try {
          const res = await S.apiJson(`/api/works/${encodeURIComponent(b.getAttribute("data-wb-id"))}/moderate`, { method: "POST", body: { action } });
          if (!res.ok) throw new Error(res.error || "操作失败");
          UI.worksFeed = null;
          await S.refreshFromServer();
          toast(action === "delete" ? "作品已删除" : "作品状态已更新");
          renderMain();
        } catch (err) { toast("操作失败：" + (err.message || err)); }
        finally { if (b.isConnected) b.disabled=false; }
      };
    });

    const more = root.querySelector("#hw-wb-more");
    if (more) {
      more.onclick = () => {
        if (UI.worksFeed && UI.worksFeed.key === filterKey && typeof S.apiJson === "function") {
          if (UI.worksFeed.loadingMore || !UI.worksFeed.hasMore || !UI.worksFeed.nextCursor) return;
          UI.worksFeed.loadingMore = true;
          more.disabled = true;
          more.textContent = "加载中...";

          const params = new URLSearchParams();
          params.set("limit", "24");
          if (filters.format && filters.format !== "all") params.set("format", filters.format);
          if (filters.access && filters.access !== "all") params.set("access", filters.access);
          if (filters.sort) params.set("sort", filters.sort);
          if (filters.asset) params.set("asset", filters.asset);
          if (filters.author) params.set("author", filters.author);
          if (filters.query) params.set("q", filters.query);
          params.set("cursor", UI.worksFeed.nextCursor);

          S.apiJson(`/api/works/feed?${params.toString()}`)
            .then((res) => {
              UI.worksFeed.loadingMore = false;
              if (res && res.ok && UI.worksFeed.key === filterKey) {
                const newItems = res.items || [];
                UI.worksFeed.items.push(...newItems);
                UI.worksFeed.nextCursor = res.nextCursor || null;
                UI.worksFeed.hasMore = Boolean(res.hasMore);
                newItems.forEach((w) => {
                  const idx = App.state.works.findIndex((x) => String(x.id) === String(w.id));
                  if (idx >= 0) App.state.works[idx] = w;
                  else App.state.works.push(w);
                });

                // Incremental append: do NOT destroy existing cards!
                const masonryEl = root.querySelector("#hw-wb-masonry");
                const colEls = masonryEl ? Array.from(masonryEl.querySelectorAll(".hw-wb-col")) : [];
                if (masonryEl && colEls.length === colCount && B.unpackWorkCandidates && B.layoutWorksMasonry) {
                  const newCandidates = B.unpackWorkCandidates(newItems);
                  const layoutRes = B.layoutWorksMasonry(newCandidates, {
                    colCount,
                    viewportHeight,
                    existingPlaced: UI._worksMasonryPlaced || [],
                    remainingQueue: UI._worksMasonryQueue || []
                  });
                  UI._worksMasonryPlaced = layoutRes.placed;
                  UI._worksMasonryQueue = layoutRes.remainingQueue;

                  layoutRes.newlyPlaced.forEach((item) => {
                    const colEl = colEls[item.col];
                    if (colEl) {
                      const tempWrap = document.createElement("div");
                      tempWrap.innerHTML = renderCardHtml(item);
                      const cardEl = tempWrap.firstElementChild;
                      if (cardEl) {
                        colEl.appendChild(cardEl);
                        bindCardElementEvents(cardEl);
                      }
                    }
                  });

                  window.HandrawImageLoader?.scan(masonryEl);

                  const countEl = root.querySelector(".hw-wb-count");
                  if (countEl) countEl.textContent = `共 ${UI.worksFeed.total || UI.worksFeed.items.length} 件`;

                  if (UI.worksFeed.hasMore && UI.worksFeed.nextCursor) {
                    more.disabled = false;
                    more.textContent = "加载更多";
                  } else {
                    const moreWrap = root.querySelector(".hw-wb-more");
                    if (moreWrap) moreWrap.remove();
                  }
                  return;
                }

                renderMain();
              }
            })
            .catch((err) => {
              UI.worksFeed.loadingMore = false;
              if (typeof toast === "function") toast("加载失败：" + (err.message || err));
              if (more.isConnected) {
                more.disabled = false;
                more.textContent = "加载更多";
              }
            });
          return;
        }

        const nextId = filtered[shownCount]?.id;
        UI.workShownCount = shownCount + 24;
        renderMain();
        const nextCard = Array.from(root.querySelectorAll("[data-wb-work]")).find((el) => el.getAttribute("data-wb-work") === nextId);
        nextCard?.querySelector("a")?.focus({ preventScroll: true });
      };
    }

    function reLayoutMasonry(newCols, preferredAnchor) {
      const masonryEl = document.getElementById("hw-wb-masonry");
      if (!masonryEl || !B.layoutWorksMasonry) return;

      const cards = Array.from(masonryEl.querySelectorAll(".hw-wb-card"));
      let anchorKey = preferredAnchor?.key || null;
      let anchorOffset = preferredAnchor?.offset ?? 0;
      if (!anchorKey) {
        for (const card of cards) {
          const rect = card.getBoundingClientRect();
          if (rect.bottom > 0 && rect.top >= 0) {
            anchorKey = card.getAttribute("data-wb-card-key") || card.getAttribute("data-wb-work");
            anchorOffset = rect.top;
            break;
          }
        }
      }

      const cardNodes = new Map();
      cards.forEach(c => {
        const k = c.getAttribute("data-wb-card-key") || c.getAttribute("data-wb-work");
        if (k) cardNodes.set(k, c);
      });

      const itemsToPlace = UI._worksMasonryPlaced || [];
      if (!itemsToPlace.length) return;

      const viewportHeight = (typeof window !== "undefined" && window.innerHeight) || 800;
      const layoutRes = B.layoutWorksMasonry(itemsToPlace, {
        colCount: newCols,
        viewportHeight,
        existingPlaced: [],
        remainingQueue: UI._worksMasonryQueue || []
      });

      UI._worksMasonryPlaced = layoutRes.placed;
      UI._worksMasonryQueue = layoutRes.remainingQueue;
      UI._worksMasonryColCount = newCols;

      const newColEls = Array.from({ length: newCols }, (_, c) => {
        const colDiv = document.createElement("div");
        colDiv.className = "hw-wb-col";
        colDiv.setAttribute("data-col-index", String(c));
        return colDiv;
      });

      layoutRes.placed.forEach(item => {
        const cardEl = cardNodes.get(item.itemKey) || cardNodes.get(item.workId);
        if (cardEl) {
          if (item.extraMargin > 0) {
            cardEl.style.marginTop = `${item.extraMargin}px`;
          } else {
            cardEl.style.marginTop = "";
          }
          newColEls[item.col].appendChild(cardEl);
        }
      });

      masonryEl.setAttribute("data-columns", String(newCols));
      masonryEl.replaceChildren(...newColEls);

      if (anchorKey) {
        const targetCard = cardNodes.get(anchorKey);
        if (targetCard) {
          const curRect = targetCard.getBoundingClientRect();
          window.scrollBy(0, curRect.top - anchorOffset);
        }
      }
    }

    if (typeof window !== "undefined" && typeof window.addEventListener === "function" && !window._hwWorksResizeBound) {
      window._hwWorksResizeBound = true;
      let resizeTimer = null;
      let lastW = window.innerWidth;
      let pendingAnchor = null;
      window.addEventListener("resize", () => {
        if (App.view !== "works") return;
        const curW = window.innerWidth;
        if (Math.abs(curW - lastW) < 25) return;
        if (!pendingAnchor) {
          const masonryEl = document.getElementById("hw-wb-masonry");
          if (masonryEl) {
            const cards = Array.from(masonryEl.querySelectorAll(".hw-wb-card"));
            for (const card of cards) {
              const rect = card.getBoundingClientRect();
              if (rect.bottom > 0 && rect.top >= 0) {
                pendingAnchor = {
                  key: card.getAttribute("data-wb-card-key") || card.getAttribute("data-wb-work"),
                  offset: rect.top
                };
                break;
              }
            }
          }
        }
        lastW = curW;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          if (App.view !== "works") return;
          const masonryEl = document.getElementById("hw-wb-masonry");
          if (!masonryEl || !B.getColumnCount) return;
          const newCols = B.getColumnCount(curW);
          const curCols = Number(masonryEl.getAttribute("data-columns")) || 4;
          const anchor = pendingAnchor;
          pendingAnchor = null;
          if (newCols === curCols) return;
          reLayoutMasonry(newCols, anchor);
        }, 100);
      });
    }
  }

  /* ======================== 2.5 STANDALONE HONOR & POPULARITY RANKINGS HALL (?view=rankings) ======================== */
  function renderRankingsHall(root) {
    const statsMap = S.getCreatorStatsMap();
    const pMeta = getPeriodMeta(UI.rankPeriod);
    const isAllTime = UI.rankPeriod === "all";
    const heroActionsHtml = `
      <button type="button" class="btn btn-primary btn-sm" id="rank-btn-pub-work">✏️ 去论坛发实测图文帖 (+5✦)</button>
      <button type="button" class="btn btn-sm" id="rank-btn-pub-style">💬 参与画风/图型板块交流</button>
    `;

    let tabBodyHtml = "";

    if (UI.rankTab === "creators") {
      const creators = S.getTopCreators(15, UI.creatorRankMode, UI.rankPeriod);
      const podium = creators.slice(0, 3);
      const rest = creators.slice(3);

      tabBodyHtml = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
          <div class="hw-segmented">
            <button type="button" class="hw-seg-btn ${UI.creatorRankMode === "prolific" ? "is-active" : ""}" data-crank-mode="prolific">🏆 ${esc(pMeta.shortPrefix)}高产贡献榜</button>
            <button type="button" class="hw-seg-btn ${UI.creatorRankMode === "cheers" ? "is-active" : ""}" data-crank-mode="cheers">👏 ${esc(pMeta.shortPrefix)}获赞人气榜</button>
            <button type="button" class="hw-seg-btn ${UI.creatorRankMode === "rising" ? "is-active" : ""}" data-crank-mode="rising">🌱 新秀破冰潜力榜</button>
          </div>
          <span style="font-size:12.5px;color:var(--ink-muted);">${esc(pMeta.desc)}</span>
        </div>

        <div class="hw-podium-grid">
          ${podium
            .map((c, idx) => {
              const medals = isAllTime
                ? ["🥇 总榜榜首 · 殿堂联展主理人", "🥈 总榜榜眼 · 荣誉推荐主理人", "🥉 总榜探花 · 荣誉推荐主理人"]
                : [`🥇 ${pMeta.shortPrefix}冠军 · 活跃之星`, `🥈 ${pMeta.shortPrefix}亚军 · 人气主理人`, `🥉 ${pMeta.shortPrefix}季军 · 实力创作者`];
              const thumbPool = !isAllTime && c.periodWorks && c.periodWorks.length ? c.periodWorks : c.works;
              const thumbsHtml = thumbPool.length
                ? `
                  <div class="hw-prolific-thumbs">
                    ${thumbPool
                      .slice(0, 3)
                      .map((pw) => `<img data-hw-src="${esc(pw.images[0])}" alt="${esc(pw.title)}" data-rank-open-work="${esc(pw.id)}" />`)
                      .join("")}
                  </div>
                `
                : "";
              const pStylesCnt = isAllTime ? c.styles.length : c.periodStyles.length;
              const pLayoutsCnt = isAllTime ? c.layouts.length : c.periodLayouts.length;
              const pWorksCnt = isAllTime ? c.publicWorksCount || c.works.length : c.periodWorks.length;
              const pPubCnt = isAllTime ? c.totalPublished : c.periodPublished;
              const pCheerCnt = isAllTime ? c.totalCheers : c.periodCheers;
              const pForkCnt = isAllTime ? c.totalForks : c.periodForks;

              return `
                <article class="hw-podium-card podium-${idx + 1}" data-rank-creator-card="${esc(c.username)}">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                    <span style="font-size:12px;font-weight:900;color:var(--vermilion);">${esc(medals[idx])}</span>
                    <span class="hw-boost-pill">🔥 ${esc(c.honor.boostText)}</span>
                  </div>
                  <div style="display:flex;align-items:center;gap:12px;cursor:pointer;" data-open-creator="${esc(c.username)}">
                    ${S.creatorAvatarHtml(c, "lg")}
                    <div style="min-width:0;flex:1;">
                      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        <strong style="font-size:16.5px;font-family:var(--font-serif);">${esc(c.authorName)}</strong>
                        <span class="hw-honor-badge ${esc(c.honor.sealClass)}">${esc(c.honor.badge)}</span>
                      </div>
                      <div style="font-size:12px;color:var(--ink-muted);margin-top:3px;">
                        ${esc(pMeta.shortPrefix)}分享 <strong>${pPubCnt}</strong> 项（画风 ${pStylesCnt} · 图型 ${pLayoutsCnt} · 作品 ${pWorksCnt}）${
                          !isAllTime ? ` · 历史总计 ${c.totalPublished} 项` : ""
                        }
                      </div>
                    </div>
                  </div>
                  ${thumbsHtml}
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding-top:6px;border-top:1px dashed var(--line-strong);">
                    <span style="font-size:12.5px;font-weight:800;color:var(--ink-body);">👏 ${esc(pMeta.shortPrefix)}获赞 ${pCheerCnt} · ⚡ ${pForkCnt} 次被复刻</span>
                    <button type="button" class="btn btn-sm btn-primary" data-open-creator="${esc(c.username)}">荣誉主页 ↗</button>
                  </div>
                </article>
              `;
            })
            .join("")}
        </div>

        <div class="hw-rank-list-card">
          ${rest
            .map((c, i) => {
              const rankNum = i + 4;
              const isMe = App.state.loggedIn && c.username === App.state.user.username;
              const pStylesCnt = isAllTime ? c.styles.length : c.periodStyles.length;
              const pLayoutsCnt = isAllTime ? c.layouts.length : c.periodLayouts.length;
              const pWorksCnt = isAllTime ? c.publicWorksCount || c.works.length : c.periodWorks.length;
              const pPubCnt = isAllTime ? c.totalPublished : c.periodPublished;
              const pCheerCnt = isAllTime ? c.totalCheers : c.periodCheers;
              return `
                <div class="hw-rank-table-row" style="${isMe ? "background:var(--vermilion-wash);" : ""}">
                  <div style="display:flex;align-items:center;gap:12px;min-width:240px;flex:1;">
                    <span class="hw-rank-num">${String(rankNum).padStart(2, "0")}</span>
                    <span data-open-creator="${esc(c.username)}" style="cursor:pointer;">${S.creatorAvatarHtml(c, "md")}</span>
                    <div>
                      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        <strong style="font-size:14px;cursor:pointer;" data-open-creator="${esc(c.username)}">${esc(c.authorName)}${isMe ? " (我)" : ""}</strong>
                        <span class="hw-honor-badge ${esc(c.honor.sealClass)}">${esc(c.honor.badge)}</span>
                        <span class="hw-boost-pill">${esc(c.honor.boostText)}</span>
                      </div>
                      <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">
                        ${esc(pMeta.shortPrefix)}画风 ${pStylesCnt} · 图型 ${pLayoutsCnt} · 作品 ${pWorksCnt}${
                          !isAllTime ? `（历史共 ${c.totalPublished} 项）` : ""
                        }
                      </div>
                    </div>
                  </div>
                  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
                    <div style="text-align:right;font-size:12.5px;">
                      <strong>${esc(pMeta.shortPrefix)} ${pPubCnt} 项分享</strong>
                      <div style="color:var(--vermilion);font-weight:750;">👏 ${pCheerCnt} 次鼓励</div>
                    </div>
                    <button type="button" class="btn btn-sm" data-open-creator="${esc(c.username)}">查看名片</button>
                  </div>
                </div>
              `;
            })
            .join("")}
        </div>
      `;
    } else if (UI.rankTab === "works") {
      const rankedWorks = S.getRankedWorks(15, UI.workRankMode, UI.rankPeriod);
      const podiumW = rankedWorks.slice(0, 3);
      const restW = rankedWorks.slice(3);

      tabBodyHtml = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
          <div class="hw-segmented">
            <button type="button" class="hw-seg-btn ${UI.workRankMode === "composite" ? "is-active" : ""}" data-wrank-mode="composite">🔥 ${esc(pMeta.shortPrefix)}综合热度榜</button>
            <button type="button" class="hw-seg-btn ${UI.workRankMode === "cheers" ? "is-active" : ""}" data-wrank-mode="cheers">👏 ${esc(pMeta.shortPrefix)}最多鼓励榜</button>
            <button type="button" class="hw-seg-btn ${UI.workRankMode === "rising" ? "is-active" : ""}" data-wrank-mode="rising">🌱 新发飙升榜 (新人/新作专场)</button>
            <button type="button" class="hw-seg-btn ${UI.workRankMode === "forks" ? "is-active" : ""}" data-wrank-mode="forks">⚡ ${esc(pMeta.shortPrefix)}最多复刻榜</button>
          </div>
          <span style="font-size:12.5px;color:var(--ink-muted);">${esc(pMeta.desc)}</span>
        </div>

        <div class="hw-podium-grid">
          ${podiumW
            .map((w, idx) => {
              const medals = [
                `🥇 ${pMeta.shortPrefix}作品 TOP 1`,
                `🥈 ${pMeta.shortPrefix}作品 TOP 2`,
                `🥉 ${pMeta.shortPrefix}作品 TOP 3`
              ];
              const prof = statsMap.get(w.author) || S.getCreatorProfile(w.author);
              const cheered = S.isCheered(w.id);
              const score = S.getWorkCompositeScore(w, statsMap, UI.rankPeriod);
              return `
                <article class="hw-podium-card podium-${idx + 1}" data-rank-work-card="${esc(w.id)}">
                  <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:12.5px;font-weight:900;color:var(--vermilion);">${esc(medals[idx])}</span>
                    <span class="hw-boost-pill">热度值 ${score}</span>
                  </div>
                  <div class="hw-new-card-media" style="height:190px;border-radius:10px;" data-rank-open-work="${esc(w.id)}">
                    <span class="hw-card-badge-tl ${S.isFreshRelease(w) ? "badge-new-release" : "badge-community"}">${
                      S.isFreshRelease(w) ? `🆕 ${esc(w.createdAt)}` : esc(w.createdAt)
                    }</span>
                    <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" />
                  </div>
                  <h3 class="hw-card-title" style="font-size:15px;" data-rank-open-work="${esc(w.id)}">${esc(w.title)}</h3>
                  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:auto;padding-top:8px;border-top:1px dashed var(--line-strong);">
                    <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                      ${S.creatorAvatarHtml(prof, "sm")}
                      <span>${esc(w.authorName)}</span>
                      <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:1px 5px;">${esc(prof.honor.shortBadge)}</span>
                    </button>
                    <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-work="${esc(w.id)}">
                      👏 鼓励 ${w.cheers ?? 0}
                    </button>
                  </div>
                </article>
              `;
            })
            .join("")}
        </div>

        <div class="hw-rank-list-card">
          ${restW
            .map((w, i) => {
              const rankNum = i + 4;
              const prof = statsMap.get(w.author) || S.getCreatorProfile(w.author);
              const cheered = S.isCheered(w.id);
              return `
                <div class="hw-rank-table-row" data-rank-work-row="${esc(w.id)}">
                  <div style="display:flex;align-items:center;gap:12px;min-width:260px;flex:1;">
                    <span class="hw-rank-num">${String(rankNum).padStart(2, "0")}</span>
                    <img data-hw-src="${esc(w.images[0])}" alt="" style="width:54px;height:54px;border-radius:8px;object-fit:cover;cursor:pointer;border:1px solid var(--line-soft);" data-rank-open-work="${esc(w.id)}" />
                    <div style="min-width:0;flex:1;">
                      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        <strong style="font-size:14px;cursor:pointer;" data-rank-open-work="${esc(w.id)}">${esc(w.title)}</strong>
                        <span class="hw-honor-badge ${S.isFreshRelease(w) ? "honor-pioneer" : "honor-member"}">${esc(w.createdAt)}</span>
                      </div>
                      <div style="display:flex;align-items:center;gap:6px;margin-top:3px;font-size:12px;color:var(--ink-muted);">
                        <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                          <span>@${esc(w.authorName)}</span>
                          <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:0 5px;">${esc(prof.honor.shortBadge)}</span>
                        </button>
                        <span>· ♥ ${w.favorites || 0} 收藏 · ⚡ ${w.forks || 0} 同款</span>
                      </div>
                    </div>
                  </div>
                  <div style="display:flex;align-items:center;gap:10px;">
                    <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-work="${esc(w.id)}">
                      👏 鼓励冲榜 (${w.cheers ?? 0})
                    </button>
                    <button type="button" class="btn btn-sm" data-rank-open-work="${esc(w.id)}">看配方</button>
                  </div>
                </div>
              `;
            })
            .join("")}
        </div>
      `;
    } else {
      // Tab 3: Co-created & Hot Styles / Layouts Asset Leaderboard (Period-aware!)
      const rankedAssetEntries = S.getRankedAssets(12, UI.rankPeriod);

      tabBodyHtml = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px;">
          <span style="font-size:12.8px;font-weight:750;color:var(--ink-body);">📊 按「${esc(pMeta.fullLabel)}」内的同款作品驱动数与新共创热度排定</span>
          <span style="font-size:12.5px;color:var(--ink-muted);">${esc(pMeta.desc)}</span>
        </div>
        <div class="hw-rank-list-card">
          ${rankedAssetEntries
            .map((entry, idx) => {
              const a = entry.asset;
              const rankCls = idx < 3 ? `rank-${idx + 1}` : "";
              const prof = a.author ? statsMap.get(a.author) : null;
              const cheered = S.isCheered(a.id);
              const driveDesc = isAllTime
                ? `累计驱动 <strong>${entry.totalWorkCnt}</strong> 件作品`
                : `${esc(pMeta.shortPrefix)}驱动 <strong>${entry.periodWorkCnt}</strong> 件新作 · 历史累计 ${entry.totalWorkCnt} 件`;
              return `
                <div class="hw-rank-table-row">
                  <div style="display:flex;align-items:center;gap:12px;min-width:260px;flex:1;">
                    <span class="hw-rank-num ${rankCls}">${String(idx + 1).padStart(2, "0")}</span>
                    <img data-hw-src="${esc(a.image)}" alt="" style="width:54px;height:54px;border-radius:8px;object-fit:cover;cursor:pointer;border:1px solid var(--line-soft);" data-open-asset="${esc(a.id)}" />
                    <div>
                      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        <span class="hw-card-code">${esc(a.id)}</span>
                        <strong style="font-size:14px;cursor:pointer;" data-open-asset="${esc(a.id)}">${esc(a.name)}</strong>
                        ${S.isFreshRelease(a) ? `<span class="hw-honor-badge honor-pioneer">🆕 新发扶持</span>` : ""}
                        ${a.sourceType === "community" ? `<span class="hw-honor-badge honor-gold">✨ 社区共创</span>` : ""}
                      </div>
                      <div style="font-size:12px;color:var(--ink-muted);margin-top:3px;">
                        ${
                          prof
                            ? `贡献者：@${esc(prof.authorName)} (${esc(prof.honor.shortBadge)}) · `
                            : "官方核心库 · "
                        }${driveDesc}
                      </div>
                    </div>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;">
                    ${
                      a.sourceType === "community"
                        ? `<button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-asset="${esc(a.id)}">👏 鼓励 ${a.cheers ?? 0}</button>`
                        : ""
                    }
                    <a class="btn btn-sm btn-primary" href="${esc(channelUrl("studio", a.kind === "style" ? { style: a.id } : { layout: a.id }))}">去创作 ↗</a>
                  </div>
                </div>
              `;
            })
            .join("")}
        </div>
      `;
    }

    const backView = ["styles", "layouts", "works"].includes(UI.lastPrimaryView) ? UI.lastPrimaryView : "works";
    const backLabelMap = { styles: "画风库", layouts: "图型库", works: "作品广场" };
    const backLabel = backLabelMap[backView] || "作品广场";

    root.innerHTML = `
      <nav aria-label="二级页面返回导航" style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;font-size:13px;color:var(--ink-muted);">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-sm" id="rank-btn-back-parent" style="padding:4px 12px;">
            ← 返回${esc(backLabel)}
          </button>
          <span style="opacity:0.55;">/</span>
          <span style="color:var(--ink-strong);font-weight:750;">🏆 社区荣誉与热度榜单（周榜 · 月榜 · 总榜）</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <button type="button" class="hw-pill" style="padding:3px 10px;font-size:12px;" data-rank-return-view="works">🖼️ 作品广场</button>
          <button type="button" class="hw-pill" style="padding:3px 10px;font-size:12px;" data-rank-return-view="styles">🎨 画风库</button>
          <button type="button" class="hw-pill" style="padding:3px 10px;font-size:12px;" data-rank-return-view="layouts">📐 图型库</button>
        </div>
      </nav>

      <section class="hw-editorial-strip hw-reveal-section">
        <div style="max-width:680px;flex:1 1 380px;">
          <p class="hw-editorial-eyebrow">社区创作榜单 · 周榜 · 月榜 · 总榜</p>
          <h1 class="hw-editorial-title">周榜捧新人新作，月榜看中坚黑马，总榜敬殿堂传奇</h1>
          <p class="hw-editorial-sub">
            默认展示<strong>「📅 周榜」</strong>（仅统计近 7 天新发布内容，不叠加历史殿堂曝光倍率），让每一位本周认真创作与贡献配方的创作者都能冲上榜首，告别熟面孔长期霸榜！
          </p>
        </div>
        ${renderMyHonorStatusCard(heroActionsHtml)}
      </section>

      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px;background:var(--paper-card);border:1px solid var(--line-soft);border-radius:12px;padding:10px 14px;">
        <div class="hw-pills-row" style="margin:0;">
          <button type="button" class="hw-pill ${UI.rankTab === "creators" ? "is-active" : ""}" data-rtab="creators">👑 创作者榜（用户榜）</button>
          <button type="button" class="hw-pill ${UI.rankTab === "works" ? "is-active" : ""}" data-rtab="works">🖼️ 作品风云榜（作品榜）</button>
          <button type="button" class="hw-pill ${UI.rankTab === "assets" ? "is-active" : ""}" data-rtab="assets">🎨 共创画风 & 图型热度榜</button>
        </div>
        ${renderPeriodSwitchHtml(false)}
      </div>

      ${tabBodyHtml}
    `;

    root.querySelector("#rank-btn-back-parent").onclick = () => switchView(backView);
    root.querySelectorAll("[data-rank-return-view]").forEach((btn) => {
      btn.onclick = () => switchView(btn.getAttribute("data-rank-return-view") || "works");
    });
    root.querySelector("#rank-btn-pub-work").onclick = () => S.openQuickPublishModal("work");
    root.querySelector("#rank-btn-pub-style").onclick = () => S.openQuickPublishModal("style");
    bindPeriodSwitch(root);

    root.querySelectorAll("[data-rtab]").forEach((btn) => {
      btn.onclick = () => {
        UI.rankTab = btn.getAttribute("data-rtab");
        syncUrl();
        renderMain();
      };
    });

    root.querySelectorAll("[data-crank-mode]").forEach((btn) => {
      btn.onclick = () => {
        UI.creatorRankMode = btn.getAttribute("data-crank-mode");
        renderMain();
      };
    });

    root.querySelectorAll("[data-wrank-mode]").forEach((btn) => {
      btn.onclick = () => {
        UI.workRankMode = btn.getAttribute("data-wrank-mode");
        renderMain();
      };
    });

    const rankLoginBtn = root.querySelector("#rank-works-login-btn");
    if (rankLoginBtn) {
      rankLoginBtn.onclick = () => S.openLoginModal(null, () => renderMain());
    }

    root.querySelectorAll("[data-jump-rankings]").forEach((btn) => {
      btn.onclick = () => {
        UI.rankTab = btn.getAttribute("data-jump-rankings") || "creators";
        syncUrl();
        renderMain();
      };
    });

    root.querySelectorAll("[data-open-creator]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openCreatorCard(el.getAttribute("data-open-creator"));
      };
    });

    root.querySelectorAll("[data-rank-open-work]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openWorkLightbox(el.getAttribute("data-rank-open-work"));
      };
    });

    root.querySelectorAll("[data-open-asset]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openAssetPage(el.getAttribute("data-open-asset"));
      };
    });

    root.querySelectorAll("[data-cheer-work]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        S.toggleCheerItem("work", btn.getAttribute("data-cheer-work"));
      };
    });

    root.querySelectorAll("[data-cheer-asset]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        S.toggleCheerItem("asset", btn.getAttribute("data-cheer-asset"));
      };
    });
  }

  /* ======================== STANDALONE WORK DETAIL & COMMENT PAGE (?view=work&id=...) ======================== */
  function openWorkLightbox(workId, imgIndex = 0, focusComment = false) {
    openWorkPage(workId, imgIndex, focusComment);
  }

  function renderWorkDetailPage(root) {
    const wid = UI.activeWorkId;
    const focus = UI.workFocusComment;
    const disc = (App.state && App.state.discussions && App.state.discussions[wid]) || null;
    const tid = disc ? disc.topicId : null;
    if (tid) {
      window.location.replace(channelUrl("forum", { view: "topic", id: tid, ...(focus ? { focus: "comment" } : {}) }));
    } else {
      window.location.replace(`/t/work-${encodeURIComponent(wid)}${focus ? "?focus=comment" : ""}`);
    }
  }

  async function loadUserGenerations(username, cursor = "", append = false) {
    if (UI.profGenLoading) return;
    UI.profGenLoading = true;
    try {
      const q = new URLSearchParams();
      if (cursor) q.set("cursor", cursor);
      q.set("limit", "24");
      const res = await S.apiJson(`/api/users/${encodeURIComponent(username)}/generations?${q.toString()}`);
      if (res && res.ok) {
        const list = Array.isArray(res.generations) ? res.generations : [];
        if (append && Array.isArray(UI.profGenerations)) {
          UI.profGenerations = [...UI.profGenerations, ...list];
        } else {
          UI.profGenerations = list;
        }
        UI.profGenCursor = res.nextCursor || "";
        UI.profGenHasMore = !!res.hasMore;
        UI.profGenTotal = typeof res.total === "number" ? res.total : UI.profGenerations.length;
      } else {
        if (!append) UI.profGenerations = [];
        UI.profGenHasMore = false;
      }
    } catch (err) {
      console.warn("Failed to load user generations:", err);
      if (!append) UI.profGenerations = [];
      UI.profGenHasMore = false;
    } finally {
      UI.profGenLoading = false;
      renderMain();
    }
  }

  function openGenerationDetailModal(genItem) {
    if (!genItem) return;
    const images = Array.isArray(genItem.images) && genItem.images.length ? genItem.images : [];
    const count = genItem.imageCount || images.length;
    const title = genItem.topic || genItem.title || "生图历史记录详情";
    const styles = Array.isArray(genItem.styles) ? genItem.styles : [];
    const layouts = Array.isArray(genItem.layouts) ? genItem.layouts : [];
    const modeLabel = genItem.mode === "free" ? "自由创作" : "预设配方";

    const formatResourceItems = (list) => {
      if (!Array.isArray(list)) return "";
      return list
        .map((it) => {
          if (!it) return "";
          if (typeof it === "string") return it.trim();
          const code = (it.code || "").trim();
          const name = (it.name || "").trim();
          if (code && name && code !== name) {
            return `${code}（${name}）`;
          }
          return code || name || "";
        })
        .filter(Boolean)
        .join("、");
    };

    const styleStr = formatResourceItems(styles);
    const layoutStr = formatResourceItems(layouts);

    const isMe = Boolean(App.state.loggedIn && App.state.user && App.state.user.username === genItem.author);
    let isLikedState = S.isLiked("generation", genItem.id) || Boolean(genItem.liked);
    let isCollectedState = (App.state.collections?.generations || []).includes(genItem.id) || Boolean(genItem.favorited);
    let likeCount = Number(genItem.likes || 0);
    let favCount = Number(genItem.favorites || 0);

    let forkBanner = "";
    if (genItem.fork && genItem.fork.visible) {
      const srcAuthor = genItem.fork.authorName || genItem.fork.author || "原作者";
      forkBanner = `
        <div style="background:var(--paper-soft);border:1px dashed var(--brand-vermilion,#e15b3c);border-radius:8px;padding:8px 12px;font-size:12.5px;color:var(--brand-vermilion,#e15b3c);display:flex;align-items:center;gap:6px;">
          <span>⚡ 配方来自 <strong>@${esc(srcAuthor)}</strong></span>
        </div>
      `;
    }

    S.openModal({
      title: esc(title),
      html: `
        <div class="hw-gen-detail-modal" style="display:flex;flex-direction:column;gap:16px;">
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;max-height:58vh;overflow-y:auto;padding:4px;">
            ${images.map((img) => `
              <div style="border-radius:8px;overflow:hidden;background:var(--paper-soft);border:1px solid var(--line-soft);text-align:center;">
                <img src="${esc(img)}" alt="${esc(title)}" style="max-width:100%;max-height:460px;object-fit:contain;display:block;margin:0 auto;" />
              </div>
            `).join("")}
          </div>
          ${forkBanner}
          <div style="background:var(--paper-soft);border:1px solid var(--line-soft);border-radius:8px;padding:12px 14px;font-size:12.8px;display:flex;flex-direction:column;gap:8px;">
            <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;">
              <span><strong>作者：</strong>@${esc(genItem.author)}</span>
              <span><strong>生成时间：</strong>${esc(genItem.createdAt || genItem.created_at || "近期")}</span>
            </div>
            ${genItem.topic ? `<div><strong>主题：</strong>${esc(genItem.topic)}</div>` : ""}
            <div style="display:flex;gap:16px;flex-wrap:wrap;">
              ${genItem.ratio ? `<span><strong>画幅比例：</strong>${esc(genItem.ratio)}</span>` : ""}
              <span><strong>创作模式：</strong>${esc(modeLabel)}</span>
              <span><strong>成图数量：</strong>${count} 张</span>
            </div>
            ${styleStr ? `<div><strong>画风：</strong>${esc(styleStr)}</div>` : ""}
            ${layoutStr ? `<div><strong>图型：</strong>${esc(layoutStr)}</div>` : ""}
          </div>
          <div class="hw-modal-actions" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;padding-top:10px;border-top:1px solid var(--line-soft);">
            <div style="display:flex;gap:10px;align-items:center;">
              <button type="button" class="btn btn-sm ${isLikedState ? "btn-primary is-active" : ""}" id="gen-modal-like-btn" ${isMe ? 'disabled title="不能给自己的历史点赞"' : ""}>
                👍 <span id="gen-modal-like-text">${isLikedState ? "已点赞" : "点赞"}</span> (<span id="gen-modal-like-count">${likeCount}</span>)
              </button>
              <button type="button" class="btn btn-sm ${isCollectedState ? "btn-primary is-active" : ""}" id="gen-modal-fav-btn">
                ⭐️ <span id="gen-modal-fav-text">${isCollectedState ? "已收藏" : "收藏"}</span> (<span id="gen-modal-fav-count">${favCount}</span>)
              </button>
            </div>
            <div>
              <a class="btn btn-sm btn-primary" id="gen-modal-fork-btn" href="${esc(channelUrl("studio", { forkGen: genItem.id, entry: "quick" }))}">
                ⚡ 用这个配方复刻 ↗
              </a>
            </div>
          </div>
        </div>
      `,
      onMount: (root) => {
        const likeBtn = root.querySelector("#gen-modal-like-btn");
        const favBtn = root.querySelector("#gen-modal-fav-btn");
        if (likeBtn && !isMe) {
          likeBtn.onclick = () => {
            if (!App.state?.loggedIn) {
              S.openLoginModal("登录后即可点赞生图历史！");
              return;
            }
            S.toggleLike("generation", genItem, title);
            isLikedState = !isLikedState;
            likeCount = Math.max(0, likeCount + (isLikedState ? 1 : -1));
            genItem.likes = likeCount;
            genItem.liked = isLikedState;
            likeBtn.className = `btn btn-sm ${isLikedState ? "btn-primary is-active" : ""}`;
            const txt = root.querySelector("#gen-modal-like-text");
            if (txt) txt.textContent = isLikedState ? "已点赞" : "点赞";
            const cnt = root.querySelector("#gen-modal-like-count");
            if (cnt) cnt.textContent = likeCount;
          };
        }
        if (favBtn) {
          favBtn.onclick = () => {
            if (!App.state?.loggedIn) {
              S.openLoginModal("登录后即可收藏生图历史！");
              return;
            }
            S.toggleCollect("generations", genItem.id, title);
            isCollectedState = !isCollectedState;
            favCount = Math.max(0, favCount + (isCollectedState ? 1 : -1));
            genItem.favorites = favCount;
            genItem.favorited = isCollectedState;
            favBtn.className = `btn btn-sm ${isCollectedState ? "btn-primary is-active" : ""}`;
            const txt = root.querySelector("#gen-modal-fav-text");
            if (txt) txt.textContent = isCollectedState ? "已收藏" : "收藏";
            const cnt = root.querySelector("#gen-modal-fav-count");
            if (cnt) cnt.textContent = favCount;
          };
        }
      }
    });
  }

  function renderAccountSettingsPage(root) {
    if (!App.state?.loggedIn || !App.state?.user) {
      root.innerHTML = `<section class="hw-account-page"><h1>请先登录</h1><p>登录后可管理个人资料与账号安全。</p><button class="btn btn-primary" id="account-login-btn">登录账号</button></section>`;
      root.querySelector("#account-login-btn").onclick = () => openAuthPage("登录后管理账号设置");
      return;
    }
    const section = ["profile", "email", "security", "devices", "cloud"].includes(UI.accountSection) ? UI.accountSection : "profile";
    const sections = [
      ["profile", "个人资料", "头像、昵称与简介"],
      ["email", "邮箱与验证", "邮箱状态、验证与换绑"],
      ["security", "登录与安全", "密码与登录会话"],
      ["devices", "设备与应用授权", "管理 Skill 与终端授权"],
      ["cloud", "个人云空间", "我的画风、图型与生成历史"]
    ];
    root.innerHTML = `
      <section class="hw-account-settings hw-detail-page" id="account-settings-page">
        <div class="hw-account-layout">
          <nav class="hw-account-nav" aria-label="账号设置导航">
            ${sections.map(([key,label,desc]) => `<a class="hw-account-nav-link ${section===key?"is-active":""}" ${section===key?'aria-current="page"':""} href="${esc(channelUrl("main",{view:"account",section:key}))}" data-account-section="${key}"><strong>${label}</strong><small>${desc}</small></a>`).join("")}
          </nav>
          <div class="hw-account-content">
            <h2 class="hw-account-section-title">${sections.find(s => s[0] === section)[1]}</h2>
            ${section === "cloud" ? '<div id="hw-cloud-content"></div>' : S.renderAccountSettingsFormHtml()}
          </div>
        </div>
      </section>`;
    // Render only controls that belong to the selected account task.
    root.querySelectorAll("[data-account-panel]").forEach(node => {
      if (node.dataset.accountPanel !== section) node.remove();
    });
    root.querySelectorAll("[data-account-section]").forEach(a => {
      a.onclick = (event) => {
        event.preventDefault();
        if (UI.accountSection === a.dataset.accountSection) return;
        UI.accountSection = a.dataset.accountSection;
        syncUrl(true);
        renderMain();
      };
    });
    if (section === "cloud") {
      const content = root.querySelector("#hw-cloud-content");
      if (content && window.HandrawCloudCenter) {
        window.HandrawCloudCenter.mount(content, S.apiJson);
      }
    } else {
      S.bindAccountSettingsForm(root, () => renderMain());
    }
  }

  function groupProfilePublishedWorks(rows) {
    // V3 has one work per logical run. Fold duplicate records only by work ID,
    // never by batchId: different work IDs must remain independently addressable.
    const seen = new Set();
    return (Array.isArray(rows) ? rows : [])
      .filter(w => {
        if (!w || !w.id || !Array.isArray(w.images) || !w.images.length) return false;
        const id = String(w.id);
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
      })
      .map(w => ({ cover: w, total: w.images.length }));
  }

  async function loadProfilePublishedWorks(username, cursor = "", append = false) {
    if (UI.profileWorksLoading || UI.profileWorksUser !== username) return;
    UI.profileWorksLoading = true;
    UI.profileWorksError = "";
    try {
      const q = new URLSearchParams({ author: username, sort: "newest", limit: "24" });
      if (cursor) q.set("cursor", cursor);
      const res = await S.apiJson(`/api/works/feed?${q}`);
      if (UI.profileWorksUser !== username) return;
      if (!res || res.ok === false || !Array.isArray(res.items)) throw new Error("作品加载失败");
      const existing = append ? (UI.profileWorkRows || []) : [];
      const merged = new Map(existing.map((w) => [String(w.id), w]));
      res.items.forEach((w) => merged.set(String(w.id), w));
      UI.profileWorkRows = [...merged.values()];
      UI.profileWorksCursor = res.nextCursor || "";
      UI.profileWorksHasMore = Boolean(res.hasMore && res.nextCursor);
      UI.profileWorksTotal = typeof res.total === "number" ? res.total : null;
      // Keep the shared work cache usable for existing detail navigation.
      res.items.forEach((w) => {
        const idx = App.state.works.findIndex((item) => String(item.id) === String(w.id));
        if (idx >= 0) App.state.works[idx] = w;
        else App.state.works.push(w);
      });
    } catch (err) {
      if (UI.profileWorksUser !== username) return;
      UI.profileWorksError = "公开作品暂时加载失败，请重试。";
    } finally {
      if (UI.profileWorksUser === username) {
        UI.profileWorksLoading = false;
        const visibleUser = UI.profileUser || (App.state.loggedIn && App.state.user?.username) || "";
        if (App.view === "profile" && visibleUser === username && UI.profileTab === "works") renderMain();
      }
    }
  }

  function renderCreatorProfilePage(root) {
    const fallbackUser = App.state.loggedIn && App.state.user ? App.state.user.username : "";
    const targetUser = (UI.profileUser || fallbackUser || "").trim();

    if (!targetUser || targetUser === "guest") {
      openAuthPage("登录后即可访问与管理你的独立个人主页");
      return;
    }

    const prof = S.getCreatorProfile(targetUser);
    const isMe = Boolean(App.state.loggedIn && App.state.user && App.state.user.username === prof.username);
    if (UI.profileTab === "articles" && isMe) {
      window.location.replace(channelUrl("studio", { view: "articles-all", page: 1 }));
      return;
    }
    if (!isMe && ["collections", "account", "articles"].includes(UI.profileTab)) {
      UI.profileTab = "works";
      syncUrl(false);
    }
    if (["assets", "styles", "layouts", "generations"].includes(UI.profileTab)) {
      UI.profileTab = "works";
      syncUrl(false);
    }

    const modBadges = S.getUserModeratorBadges(prof.username);
    const curUser = App.state.user || {};
    const myMgmtRole =
      isMe &&
      (curUser.managementRole ||
        (["admin", "operator", "reviewer"].includes(curUser.role)
          ? curUser.role
          : modBadges.length
          ? "moderator"
          : "none"));

    const bioText =
      (isMe && curUser.bio) ||
      prof.bio ||
      `${prof.honor.desc} · 已在社区累计贡献 ${prof.works.length} 件作品与 ${prof.styles.length + prof.layouts.length} 项画风/图型资产。`;

    let tabBodyHtml = "";
    if (UI.profileTab === "works") {
      const serverBacked = Boolean(App.state.serverBacked && typeof S.apiJson === "function");
      if (serverBacked && UI.profileWorksUser !== prof.username) {
        UI.profileWorksUser = prof.username;
        UI.profileWorkRows = null;
        UI.profileWorksCursor = "";
        UI.profileWorksHasMore = false;
        UI.profileWorksTotal = null;
        UI.profileWorksLoading = false;
        UI.profileWorksError = "";
      }
      if (serverBacked && UI.profileWorkRows === null && !UI.profileWorksLoading && !UI.profileWorksError) {
        loadProfilePublishedWorks(prof.username);
      }
      const rows = serverBacked ? UI.profileWorkRows : prof.works;
      const groups = groupProfilePublishedWorks(rows);
      if (rows === null && !UI.profileWorksError) {
        tabBodyHtml = `<div class="hw-detail-section-card" role="status" style="padding:44px;text-align:center;color:var(--ink-muted);">正在加载公开作品…</div>`;
      } else {
        tabBodyHtml = groups.length
          ? S.renderMasonry(groups.map(({ cover, total }) => `
              <article class="hw-card hw-profile-work-group" data-prof-work="${esc(cover.id)}" tabindex="0" role="button" aria-label="查看作品：${esc(cover.title)}${total > 1 ? `，共 ${total} 张` : ""}" style="cursor:pointer;">
                <div class="hw-card-media">
                  <img data-hw-src="${esc(cover.coverUrl && cover.images.includes(cover.coverUrl) ? cover.coverUrl : cover.images[0])}" alt="${esc(cover.title)}" loading="lazy" />
                  ${total > 1 ? `<span class="hw-card-badge-tl hw-profile-batch-count">🖼️ ${total} 张</span>` : ""}
                </div>
                <div class="hw-card-body">
                  <h3 class="hw-card-title">${esc(cover.title)}</h3>
                  <div style="font-size:12px;color:var(--ink-muted);display:flex;justify-content:space-between;gap:8px;align-items:center;">
                    <span>${esc(cover.createdAt || "近期")}</span>
                    <span>${total > 1 ? "查看全部图片" : `👏 ${cover.cheers ?? 0} · 💬 ${(cover.comments || []).length}`}</span>
                  </div>
                </div>
              </article>
            `), "standard")
          : `<div class="hw-detail-section-card" style="text-align:center;padding:42px 20px;color:var(--ink-muted);">暂无公开作品。${isMe ? `去 <a href="${esc(channelUrl("studio", { entry: "quick" }))}" style="color:var(--vermilion);font-weight:800;">创作台 ↗</a> 开始创作吧！` : ""}</div>`;
        if (serverBacked && UI.profileWorksHasMore) {
          tabBodyHtml += `<div style="text-align:center;padding:18px 0;"><button type="button" class="btn" id="prof-work-loadmore-btn" ${UI.profileWorksLoading ? "disabled" : ""}>${UI.profileWorksLoading ? "加载中…" : "加载更多作品"}</button></div>`;
        }
      }
      if (serverBacked && UI.profileWorksError) {
        tabBodyHtml += `<div class="hw-detail-section-card" role="alert" style="text-align:center;padding:14px;"><span>${esc(UI.profileWorksError)}</span><button type="button" class="btn btn-sm" id="prof-work-retry-btn">重试加载</button></div>`;
      }
    } else if (UI.profileTab === "resources") {
      const resourceOptions = [{ value: "all", label: "全部" }, { value: "styles", label: "画风" }, { value: "layouts", label: "图型" },
        ...(isMe ? [{ value: "gallery", label: "我的图库" }] : [])];
      const type = [...(isMe ? ["gallery"] : []), "styles", "layouts"].includes(UI.profileResourceFilter) ? UI.profileResourceFilter : "all";
      const resources = [
        ...prof.styles.map((it) => ({ ...it, _profileResourceType: "styles" })),
        ...prof.layouts.map((it) => ({ ...it, _profileResourceType: "layouts" }))
      ].filter((it) => type === "all" || type === it._profileResourceType);
      tabBodyHtml = `
        <div class="hw-pills-row hw-profile-resource-filters" role="group" aria-label="创作资源分类" style="margin:0 0 16px;">
          ${resourceOptions.map((opt) => `<button type="button" class="hw-pill ${type === opt.value ? "is-active" : ""}" data-prof-resource-filter="${opt.value}" aria-pressed="${type === opt.value}">${opt.label}${opt.value === "gallery" ? " · 私有" : ` (${opt.value === "all" ? prof.styles.length + prof.layouts.length : opt.value === "styles" ? prof.styles.length : prof.layouts.length})`}</button>`).join("")}
        </div>
        ${type === "gallery" && isMe ? '<div id="hw-profile-private-gallery" aria-live="polite">正在加载我的图库…</div>' : resources.length
          ? S.renderMasonry(resources.map((it) => `
              <article class="hw-card" data-prof-asset="${esc(it.id)}" style="cursor:pointer;">
                <div class="hw-card-media">
                  <span class="hw-card-badge-tl badge-community">✨ ${it._profileResourceType === "styles" ? "共创画风" : "共创图型"}</span>
                  <img data-hw-src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy" />
                </div>
                <div class="hw-card-body">
                  <div class="hw-card-code">${esc(it.id)}</div>
                  <h3 class="hw-card-title">${esc(it.name)}</h3>
                  <div style="font-size:12px;color:var(--ink-muted);display:flex;justify-content:space-between;">
                    <span>🖼️ ${S.getAssetWorkCount(it.id)} 件同款作品</span>
                    <span>💬 ${S.getAssetComments(it.id).length} 条评论</span>
                  </div>
                </div>
              </article>
            `), "standard")
          : `<div class="hw-detail-section-card" style="text-align:center;padding:42px 20px;color:var(--ink-muted);">暂无公开的${type === "all" ? "创作资源" : type === "styles" ? "共创画风" : "共创图型"}。</div>`}
      `;
    } else if (UI.profileTab === "topics") {
      tabBodyHtml = prof.topics.length
        ? `<div style="display:flex;flex-direction:column;gap:12px;">
            ${prof.topics
              .map((t) => {
                const imgs = S.normalizeTopicImages ? S.normalizeTopicImages(t) : (t.images || []).map((im) => typeof im === "string" ? { url: im, tag: "" } : { url: im.url, tag: im.tag || "" });
                const imgCount = imgs.length;
                const cleanSnippet = typeof S.stripHtmlToSnippet === "function" ? S.stripHtmlToSnippet(t.summary || t.body || "", 140) : (t.summary || t.body || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 140);

                const metaRowHtml = `
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:7px;">
                    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                      ${t.pinned ? `<span style="background:var(--vermilion);color:#fff;font-size:11px;font-weight:800;padding:1px 7px;border-radius:4px;">📌 置顶</span>` : ""}
                      ${t.featured ? `<span style="background:var(--gold);color:#fff;font-size:11px;font-weight:800;padding:1px 7px;border-radius:4px;">🌟 精华</span>` : ""}
                      <span style="font-size:12px;font-weight:800;color:var(--vermilion);">${esc(t.categoryLabel || "社区讨论")}</span>
                      ${
                        imgCount > 0
                          ? `<span class="forum-format-badge is-visual">🖼️ ${imgCount > 1 ? `${imgCount} 图分享` : "图文分享"}</span>`
                          : ""
                      }
                      ${
                        t.price > 0
                          ? `<span style="background:var(--gold-wash);border:1px solid var(--gold-border);color:var(--gold);font-size:11.5px;font-weight:800;padding:1px 7px;border-radius:999px;">💎 ${t.price} 积分</span>`
                          : ""
                      }
                      ${
                        t.bounty > 0
                          ? `<span style="background:${t.solved ? "var(--jade-wash)" : "var(--vermilion-wash)"};color:${t.solved ? "var(--jade)" : "var(--vermilion)"};font-size:11.5px;font-weight:800;padding:1px 8px;border-radius:999px;">${t.solved ? "✅ 已结" : `💰 悬赏 ${t.bounty}✦`}</span>`
                          : ""
                      }
                    </div>
                    <span style="font-size:12px;color:var(--ink-muted);">${esc(t.createdAt || "")}</span>
                  </div>
                `;

                let bodyAndMediaHtml = "";
                if (imgCount === 0) {
                  bodyAndMediaHtml = `
                    ${metaRowHtml}
                    <h2 style="margin:0 0 6px;font-size:16.5px;line-height:1.42;">${esc(t.title)}</h2>
                    ${cleanSnippet ? `<p style="margin:0;font-size:13.5px;color:var(--ink-body);line-height:1.62;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${esc(cleanSnippet)}</p>` : ""}
                  `;
                } else if (imgCount === 1) {
                  const im = imgs[0];
                  bodyAndMediaHtml = `
                    <div class="forum-card-split" style="margin-bottom:0;">
                      <div style="min-width:0;">
                        ${metaRowHtml}
                        <h2 style="margin:0 0 6px;font-size:16.5px;line-height:1.4;">${esc(t.title)}</h2>
                        ${cleanSnippet ? `<p style="margin:0;font-size:13.5px;color:var(--ink-body);line-height:1.58;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${esc(cleanSnippet)}</p>` : ""}
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
                    <h2 style="margin:0 0 6px;font-size:16.5px;line-height:1.4;">${esc(t.title)}</h2>
                    ${cleanSnippet ? `<p style="margin:0 0 8px;font-size:13.5px;color:var(--ink-body);line-height:1.56;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">${esc(cleanSnippet)}</p>` : ""}
                    <div class="forum-media-strip ${stripColClass}" style="margin-bottom:0;">
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

                return `
                  <article class="forum-topic-card" data-prof-topic="${esc(t.id)}" style="margin-bottom:0;">
                    ${bodyAndMediaHtml}
                  </article>
                `;
              })
              .join("")}
          </div>`
        : `<div class="hw-detail-section-card" style="text-align:center;padding:42px 20px;color:var(--ink-muted);">
            暂未发布论坛实战帖。
            ${isMe ? `<div style="margin-top:12px;"><button type="button" class="btn btn-primary" id="prof-empty-compose-btn">✏️ 去发布第一篇图文论坛帖</button></div>` : ""}
          </div>`;
    } else if (UI.profileTab === "collections" && isMe) {
      const cols = App.state.collections || { styles: [], layouts: [], works: [], topics: [], generations: [] };
      if (!["styles", "layouts", "works", "topics", "generations"].includes(UI.favTab)) {
        UI.favTab = "styles";
      }

      const ids = cols[UI.favTab] || [];
      if (UI.favTab === "generations" && UI._collectedGenerations === null && !UI._fetchingColGen) {
        UI._fetchingColGen = true;
        fetch("/api/collections/generations", { credentials: "include" })
          .then((r) => r.ok ? r.json() : null)
          .then((data) => {
            UI._collectedGenerations = (data && data.generations) || [];
          })
          .catch(() => {
            UI._collectedGenerations = [];
          })
          .finally(() => {
            UI._fetchingColGen = false;
            renderMain();
          });
      }
      if (UI.favTab === "works") {
        // boot no longer carries every work, so a kept work may be missing here.
        const missing = (cols.works || []).filter((id) => !(App.state.works || []).some((w) => String(w.id) === String(id)));
        if (missing.length && typeof S.apiJson === "function" && !UI._fetchingProfColWorks) {
          UI._fetchingProfColWorks = true;
          S.apiJson(`/api/works/feed?ids=${encodeURIComponent(missing.join(","))}`)
            .then((res) => {
              if (res && res.items && res.items.length) {
                res.items.forEach((item) => {
                  if (!(App.state.works || []).some((w) => String(w.id) === String(item.id))) {
                    (App.state.works = App.state.works || []).push(item);
                  }
                });
                if (App.view === "profile" && UI.profileTab === "collections") renderMain();
              }
            })
            .catch(() => {})
            .finally(() => {
              UI._fetchingProfColWorks = false;
            });
        }
      }
      if (UI.favTab === "styles" || UI.favTab === "layouts") {
        const missingIds = ids.filter((id) => !App.resourceMap.has(id));
        if (missingIds.length && !UI._fetchingFavs) {
          UI._fetchingFavs = true;
          Promise.all(
            missingIds.map((mid) =>
              fetch(`/api/resources/${encodeURIComponent(mid)}`)
                .then((r) => (r.ok ? r.json() : null))
                .then((data) => {
                  const res = data?.resource || data;
                  if (res && res.code) {
                    const it = {
                      id: res.code,
                      code: res.code,
                      name: res.name || res.code,
                      originalName: res.name || res.code,
                      kind: res.kind,
                      sourceType: res.sourceType || res.source || "pending",
                      status: res.status,
                      image: res.image || res.cover || "",
                      cover: res.image || res.cover || "",
                      description: res.description || "",
                      definition: res.definition || null,
                      access: res.access || {},
                      canUse: res.canUse !== false,
                    };
                    App.resourceMap.set(it.id, it);
                  }
                })
                .catch(() => null)
            )
          ).finally(() => {
            UI._fetchingFavs = false;
            renderMain();
          });
        }
      }

      let innerContentHtml = "";
      if (UI.favTab === "styles" || UI.favTab === "layouts") {
        const items = ids.map((id) => App.resourceMap.get(id)).filter(Boolean);
        innerContentHtml = items.length
          ? S.renderMasonry(
              items.map((item) => {
                const isWithdrawn = item.status === "withdrawn" || item.status === "hidden" || item.access?.hiddenBy === "withdrawn";
                const isPending = !isWithdrawn && (item.status === "pending" || item.status === "changes_requested" || item.sourceType === "pending" || item.access?.hiddenBy === "pending");
                if (isWithdrawn) {
                  return `
                    <article class="hw-card hw-card-withdrawn" style="opacity:0.75;filter:grayscale(0.85);background:var(--paper-soft, #f4efe6);">
                      <div class="hw-card-media" style="cursor:default;">
                        <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" />
                      </div>
                      <div class="hw-card-body">
                        <div class="hw-card-code" style="color:var(--ink-muted);">${esc(item.id)} <span class="badge" style="margin-left:4px;font-size:11px;padding:1px 6px;border-radius:4px;background:var(--line-soft, #e5e5e5);color:var(--ink-muted);">已下架</span></div>
                        <h3 class="hw-card-title">${esc(item.name)}</h3>
                        <div class="hw-card-footer">
                          <button type="button" class="btn btn-sm" data-unfav="${esc(item.id)}">取消收藏</button>
                          <button type="button" class="btn btn-sm" disabled style="opacity:0.5;cursor:not-allowed;">不可使用</button>
                        </div>
                      </div>
                    </article>
                  `;
                }
                return `
                  <article class="hw-card">
                    <div class="hw-card-media" data-fav-open-asset="${esc(item.id)}" style="cursor:pointer;">
                      <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" />
                    </div>
                    <div class="hw-card-body">
                      <div class="hw-card-code">
                        ${esc(item.id)}
                        ${isPending ? `<span class="badge" style="margin-left:4px;font-size:11px;padding:1px 6px;border-radius:4px;background:var(--gold-soft, #fef3c7);color:var(--gold-strong, #92400e);font-weight:700;">投稿中</span>` : ""}
                      </div>
                      <h3 class="hw-card-title" data-fav-open-asset="${esc(item.id)}" style="cursor:pointer;">${esc(item.name)}</h3>
                      <div class="hw-card-footer">
                        <button type="button" class="btn btn-sm" data-unfav="${esc(item.id)}">移除</button>
                        <a class="btn btn-sm btn-primary" href="${esc(channelUrl("studio", item.kind === "style" ? { style: item.id } : { layout: item.id }))}">去创作 ↗</a>
                      </div>
                    </div>
                  </article>
                `;
              }),
              "standard"
            )
          : `<div style="padding:40px;text-align:center;color:var(--ink-muted);">暂未收藏该类资产，去库里点亮 ♡ 吧！</div>`;
      } else if (UI.favTab === "works") {
        const items = (cols.works || []).map((id) => (App.state.works || []).find((w) => w.id === id)).filter(Boolean);
        innerContentHtml = items.length
          ? S.renderMasonry(
              items.map(
                (w) => `
                  <article class="hw-card">
                    <div class="hw-card-media" data-fav-open-work="${esc(w.id)}" style="cursor:pointer;">
                      <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" />
                    </div>
                    <div class="hw-card-body">
                      <h3 class="hw-card-title" data-fav-open-work="${esc(w.id)}" style="cursor:pointer;">${esc(w.title)}</h3>
                      <div class="hw-card-footer">
                        <button type="button" class="btn btn-sm" data-unfav="${esc(w.id)}">移除</button>
                        <a class="btn btn-sm btn-primary" href="${esc(channelUrl("studio", { fork: w.id }))}">做同款 ↗</a>
                      </div>
                    </div>
                  </article>
                `
              ),
              "standard"
            )
          : `<div style="padding:40px;text-align:center;color:var(--ink-muted);">暂未收藏作品</div>`;
      } else if (UI.favTab === "generations") {
        const items = UI._collectedGenerations || [];
        innerContentHtml = items.length
          ? S.renderMasonry(
              items.map((g) => {
                const img0 = (g.images && g.images[0]) || "/images/poster-demo-autumn-equinox.webp";
                const gTitle = g.topic || g.title || "手绘风生成作品";
                return `
                  <article class="hw-card" data-prof-gen="${esc(g.id)}" style="cursor:pointer;">
                    <div class="hw-card-media"><img data-hw-src="${esc(img0)}" alt="${esc(gTitle)}" /></div>
                    <div class="hw-card-body">
                      <h3 class="hw-card-title">${esc(gTitle)}</h3>
                      <div style="font-size:12px;color:var(--ink-muted);display:flex;justify-content:space-between;">
                        <span>@${esc(g.author)}</span>
                        <span>👍 ${g.likes || 0} · ⭐️ ${g.favorites || 0}</span>
                      </div>
                    </div>
                  </article>
                `;
              }),
              "standard"
            )
          : `<div style="padding:40px;text-align:center;color:var(--ink-muted);">暂未收藏生图历史</div>`;
      } else {
        const items = (cols.topics || []).map((id) => (App.state.topics || []).find((t) => t.id === id)).filter(Boolean);
        innerContentHtml = items.length
          ? `<div style="display:grid;gap:10px;">
              ${items
                .map(
                  (t) => `
                    <div class="forum-topic-card" style="display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;">
                      <div>
                        <span class="hw-card-code">${esc(t.categoryLabel)}</span>
                        <h3 style="margin:4px 0;font-size:15.5px;">${esc(t.title)}</h3>
                        <div style="font-size:12.5px;color:var(--ink-muted);">@${esc(t.authorName)}</div>
                      </div>
                      <div style="display:flex;gap:8px;align-items:center;">
                        <button type="button" class="btn btn-sm" data-unfav="${esc(t.id)}">取消收藏</button>
                        <a class="btn btn-sm btn-primary" href="${esc(channelUrl("forum", { view: "topic", id: t.id }))}">阅读帖子 ↗</a>
                      </div>
                    </div>
                  `
                )
                .join("")}
            </div>`
          : `<div style="padding:40px;text-align:center;color:var(--ink-muted);">暂未收藏论坛好帖</div>`;
      }

      tabBodyHtml = `
        <div class="hw-detail-section-card hw-profile-collections">
          <div class="hw-collections-toolbar">
            <div class="hw-pills-row hw-collections-tabs" role="tablist" aria-label="收藏内容分类">
              <button type="button" class="hw-pill ${UI.favTab === "styles" ? "is-active" : ""}" data-prof-ftab="styles" role="tab" aria-selected="${UI.favTab === "styles"}">🎨 收藏画风 (${(cols.styles || []).length})</button>
              <button type="button" class="hw-pill ${UI.favTab === "layouts" ? "is-active" : ""}" data-prof-ftab="layouts" role="tab" aria-selected="${UI.favTab === "layouts"}">📐 收藏图型 (${(cols.layouts || []).length})</button>
              <button type="button" class="hw-pill ${UI.favTab === "works" ? "is-active" : ""}" data-prof-ftab="works" role="tab" aria-selected="${UI.favTab === "works"}">🖼️ 收藏作品 (${(cols.works || []).length})</button>
              <button type="button" class="hw-pill ${UI.favTab === "generations" ? "is-active" : ""}" data-prof-ftab="generations" role="tab" aria-selected="${UI.favTab === "generations"}">⚡ 收藏生图 (${(cols.generations || []).length})</button>
              <button type="button" class="hw-pill ${UI.favTab === "topics" ? "is-active" : ""}" data-prof-ftab="topics" role="tab" aria-selected="${UI.favTab === "topics"}">💬 收藏帖子 (${(cols.topics || []).length})</button>
            </div>
            ${
              (cols[UI.favTab] || []).length > 0
                ? `<button type="button" class="btn btn-sm" id="prof-col-batch-unfav-btn" style="font-size:12px;">🗑️ 清空此分类收藏</button>`
                : ""
            }
          </div>
          ${innerContentHtml}
        </div>
      `;
    }

    root.innerHTML = `
      <div class="hw-profile-page" id="standalone-profile-page">

        <section class="hw-profile-hero">
          <div class="hw-profile-hero-top">
            <div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;flex:1;min-width:260px;">
              <img class="hw-profile-avatar-xl hw-creator-avatar-image" src="${esc(prof.avatarUrl || "/assets/avatar-default.svg")}" alt="${esc(prof.authorName)}的头像" />
              <div style="flex:1;min-width:220px;">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;">
                  <h1 style="margin:0;font-size:24px;font-family:var(--font-serif);color:var(--ink-strong);">@${esc(prof.authorName)}</h1>
                  <span style="font-size:12.5px;color:var(--ink-muted);">ID: ${esc(prof.username)}</span>
                  <span class="hw-honor-badge ${esc(prof.honor.sealClass)}">${esc(prof.honor.badge)}</span>
                  <span class="hw-boost-pill">🔥 ${esc(prof.honor.boostText)}</span>
                  ${modBadges
                    .map(
                      (mb) =>
                        `<span class="hw-honor-badge" style="background:rgba(31,95,139,0.12);color:#1f5f8b;border:1px solid rgba(31,95,139,0.3);">🛡️ ${esc(mb.shortBoardLabel || mb.boardLabel)} · ${esc(mb.title)}</span>`
                    )
                    .join("")}
                </div>
                <p style="margin:0 0 10px;font-size:13.8px;color:var(--ink-body);line-height:1.6;">${esc(bioText)}</p>
                ${
                  (prof.achievements || []).length
                    ? `<div style="display:flex;gap:6px;flex-wrap:wrap;">
                        ${prof.achievements.map((ach) => `<span class="hw-pill" style="padding:2px 9px;font-size:11.5px;cursor:default;">${esc(ach)}</span>`).join("")}
                      </div>`
                    : ""
                }
              </div>
            </div>

            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              ${
                isMe
                  ? `
                    <button type="button" class="btn" id="prof-go-collections-btn">♥ 收藏夹</button>
                    <button type="button" class="btn" id="prof-go-account-btn">⚙️ 账号设置</button>
                    <button type="button" class="btn btn-gold" id="prof-go-wallet-btn">✦ 积分钱包 (${App.state.credits}✦)</button>
                    ${
                      myMgmtRole && myMgmtRole !== "none"
                        ? `<a class="btn btn-primary" href="${esc(channelUrl("admin", myMgmtRole === "admin" ? { module: "users" } : {}))}">🏛️ 管理后台 ↗</a>`
                        : ""
                    }
                  `
                  : `
                    <button type="button" class="btn btn-primary" id="prof-filter-author-btn">🖼️ 在作品广场筛选 TA 的作品</button>
                    ${
                      S.isStaff && S.isStaff()
                        ? `<button type="button" class="btn btn-gold" id="prof-staff-manage-btn">🛡️ 治理此创作者 (封禁/荣誉/额度/身份)</button>`
                        : ""
                    }
                  `
              }
            </div>
          </div>

          ${
            !isMe && S.isStaff && S.isStaff()
              ? `
                <div id="prof-staff-banner" style="margin-top:12px;background:rgba(31,95,139,0.08);border:1px solid rgba(31,95,139,0.3);border-radius:10px;padding:9px 14px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
                  <div style="font-size:12.8px;font-weight:750;color:#1f5f8b;">
                    🛡️ <strong>前台用户治理</strong>：当前正以前台管理视角查看创作者 @${esc(prof.authorName)} (${esc(prof.username)})
                  </div>
                  <div style="display:flex;gap:6px;align-items:center;">
                    <button type="button" class="btn btn-sm btn-primary" id="prof-staff-manage-banner-btn">⚙️ 就地治理此创作者账号</button>
                  </div>
                </div>
              `
              : ""
          }

          <div class="hw-profile-kpis">
            <div class="hw-profile-kpi">
              <strong>${prof.totalPublished}</strong>
              <span>累计公开分享</span>
            </div>
            <div class="hw-profile-kpi">
              <strong>${prof.totalCheers}</strong>
              <span>收获掌声与鼓励</span>
            </div>
            <div class="hw-profile-kpi">
              <strong>${prof.totalForks}</strong>
              <span>被做同款</span>
            </div>
            <div class="hw-profile-kpi">
              <strong>${prof.topics.length}</strong>
              <span>发布实战论坛帖</span>
            </div>
          </div>

          <!-- 4-Tier Honor Ladder -->
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:8px;padding-top:4px;">
            ${(S.CREATOR_HONOR_TIERS || [])
              .slice()
              .reverse()
              .map((tier) => {
                const active = tier.key === prof.honor.key;
                return `
                  <div style="padding:9px 12px;border-radius:10px;border:1px solid ${active ? "var(--vermilion)" : "var(--line-soft)"};background:${active ? "var(--vermilion-wash)" : "var(--paper-bg)"};font-size:12px;">
                    <div style="font-weight:850;color:${active ? "var(--vermilion)" : "var(--ink-strong)"};">${esc(tier.badge)} ${active ? "· 当前等级" : ""}</div>
                    <div style="color:var(--ink-muted);margin-top:2px;">累计分享 ≥ ${tier.minCount} 项 · ${esc(tier.boostText)}</div>
                  </div>
                `;
              })
              .join("")}
          </div>
        </section>

        <!-- Standalone Profile Section Tabs -->
        ${UI.profileTab !== "collections" ? `<div class="hw-pills-row hw-profile-tabs" role="tablist" aria-label="创作者主页分类标签">
          <button type="button" class="hw-pill ${UI.profileTab === "works" ? "is-active" : ""}" data-ptab="works" role="tab" aria-selected="${UI.profileTab === "works"}">🖼️ 作品${UI.profileWorksUser === prof.username && UI.profileWorksTotal !== null ? ` (${UI.profileWorksTotal})` : ""}</button>
          <button type="button" class="hw-pill ${UI.profileTab === "resources" ? "is-active" : ""}" data-ptab="resources" role="tab" aria-selected="${UI.profileTab === "resources"}">🎨 创作资源 (${prof.styles.length + prof.layouts.length})</button>
          <button type="button" class="hw-pill ${UI.profileTab === "topics" ? "is-active" : ""}" data-ptab="topics" role="tab" aria-selected="${UI.profileTab === "topics"}">💬 社区动态 (${prof.topics.length})</button>
        </div>` : ""}
        <div id="profile-tab-stage">
          ${tabBodyHtml}
        </div>
      </div>
    `;

    const activeTabPill = root.querySelector(".hw-profile-tabs .hw-pill.is-active");
    if (activeTabPill) {
      const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      try {
        activeTabPill.scrollIntoView({ inline: "nearest", block: "nearest", behavior: prefersReducedMotion ? "auto" : "smooth" });
      } catch (_) {}
    }


    root.querySelectorAll("[data-ptab]").forEach((btn) => {
      btn.onclick = () => {
        openProfilePage(prof.username, btn.getAttribute("data-ptab"));
      };
    });

    const collectionsBtn = root.querySelector("#prof-go-collections-btn");
    if (collectionsBtn) collectionsBtn.onclick = () => openProfilePage(prof.username, "collections");
    root.querySelectorAll("[data-prof-resource-filter]").forEach((btn) => {
      btn.onclick = () => {
        UI.profileResourceFilter = btn.getAttribute("data-prof-resource-filter") || "all";
        renderMain();
      };
    });
    if (isMe && UI.profileTab === "resources" && UI.profileResourceFilter === "gallery") {
      const galleryRoot = root.querySelector("#hw-profile-private-gallery");
      if (galleryRoot && window.HandrawCloudCenter?.mountGallery) {
        window.HandrawCloudCenter.mountGallery(galleryRoot, S.apiJson);
      } else if (galleryRoot) {
        galleryRoot.textContent = "图库模块暂时不可用，请刷新后重试。";
      }
    }
    const goAccBtn = root.querySelector("#prof-go-account-btn");
    if (goAccBtn) goAccBtn.onclick = () => switchView("account");
    const goWalBtn = root.querySelector("#prof-go-wallet-btn");
    if (goWalBtn) goWalBtn.onclick = () => switchView("wallet");
    const emptyCompBtn = root.querySelector("#prof-empty-compose-btn");
    if (emptyCompBtn) emptyCompBtn.onclick = () => S.goToForumCompose();
    const filterAuthorBtn = root.querySelector("#prof-filter-author-btn");
    if (filterAuthorBtn) filterAuthorBtn.onclick = () => switchView("works", { filterAuthor: prof.username });

    const staffManageBtn = root.querySelector("#prof-staff-manage-btn");
    if (staffManageBtn) staffManageBtn.onclick = () => window.open(channelUrl("admin", { module: "users", q: prof.username }), "_blank");
    const staffBannerBtn = root.querySelector("#prof-staff-manage-banner-btn");
    if (staffBannerBtn) staffBannerBtn.onclick = () => window.open(channelUrl("admin", { module: "users", q: prof.username }), "_blank");

    const workLoadmoreBtn = root.querySelector("#prof-work-loadmore-btn");
    if (workLoadmoreBtn) workLoadmoreBtn.onclick = () => {
      if (UI.profileWorksCursor) loadProfilePublishedWorks(prof.username, UI.profileWorksCursor, true);
    };
    const workRetryBtn = root.querySelector("#prof-work-retry-btn");
    if (workRetryBtn) workRetryBtn.onclick = () => {
      UI.profileWorksError = "";
      loadProfilePublishedWorks(prof.username, UI.profileWorkRows ? UI.profileWorksCursor : "", Boolean(UI.profileWorkRows));
    };
    root.querySelectorAll("[data-prof-work]").forEach((el) => {
      el.onclick = () => openWorkPage(el.getAttribute("data-prof-work"), 0, false);
      el.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          el.click();
        }
      };
    });
    root.querySelectorAll("[data-prof-asset]").forEach((el) => {
      el.onclick = () => openAssetPage(el.getAttribute("data-prof-asset"));
    });
    root.querySelectorAll("[data-prof-topic]").forEach((el) => {
      el.onclick = () => S.goToTopicPage(el.getAttribute("data-prof-topic"));
    });
    root.querySelectorAll("[data-prof-gen]").forEach((el) => {
      el.onclick = () => {
        const gid = el.getAttribute("data-prof-gen");
        const found = (UI.profGenerations || []).find((x) => x.id === gid) || (UI._collectedGenerations || []).find((x) => x.id === gid);
        if (found) {
          openGenerationDetailModal(found);
        }
      };
    });
    const loadMoreGenBtn = root.querySelector("#prof-gen-loadmore-btn");
    if (loadMoreGenBtn) {
      loadMoreGenBtn.onclick = () => {
        if (UI.profGenCursor && prof && prof.username) {
          loadUserGenerations(prof.username, UI.profGenCursor, true);
        }
      };
    }
    root.querySelectorAll("[data-prof-ftab]").forEach((btn) => {
      btn.onclick = () => {
        UI.favTab = btn.getAttribute("data-prof-ftab");
        renderMain();
      };
    });

    root.querySelectorAll("[data-fav-open-asset]").forEach((el) => {
      el.onclick = () => openAssetPage(el.getAttribute("data-fav-open-asset"));
    });
    root.querySelectorAll("[data-fav-open-work]").forEach((el) => {
      el.onclick = () => openWorkPage(el.getAttribute("data-fav-open-work"));
    });
    root.querySelectorAll("[data-unfav]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const id = b.getAttribute("data-unfav");
        S.toggleCollect(UI.favTab, id, id);
        renderMain();
      };
    });
    const batchUnfavBtn = root.querySelector("#prof-col-batch-unfav-btn");
    if (batchUnfavBtn) {
      batchUnfavBtn.onclick = () => {
        const list = [...(App.state?.collections?.[UI.favTab] || [])];
        if (!list.length) return;
        if (!window.confirm(`确定要移除当前分类下的全部 ${list.length} 个收藏项吗？`)) return;
        list.forEach((id) => {
          S.toggleCollect(UI.favTab, id, id);
        });
        renderMain();
      };
    }

    // Account editing lives on ?view=account (legacy profile URLs redirect).
  }

  /* ======================== STANDALONE AUTH PASS PAGE (?view=auth) ======================== */
  function restoreAfterAuth(runSuccessCallback = false) {
    const snap = UI.authReturnSnapshot;
    const cb = UI.authOnSuccess;
    UI.authReturnSnapshot = null;
    UI.authOnSuccess = null;
    UI.authReason = "";

    if (runSuccessCallback && typeof cb !== "function") {
      App.view = "discover";
    } else if (snap && snap.view && snap.view !== "auth") {
      App.view = snap.view;
      UI.activeWorkId = snap.activeWorkId || UI.activeWorkId;
      UI.profileUser = snap.profileUser || UI.profileUser;
      UI.profileTab = snap.profileTab || UI.profileTab;
      UI.accountSection = snap.accountSection || UI.accountSection;
      if (snap.view === "device" && snap.deviceCode) {
        const p = new URLSearchParams(window.location.search);
        p.set("code", snap.deviceCode);
        window.history.replaceState({ view: "device" }, "", `${window.location.pathname}?${p.toString()}`);
      }
    } else {
      App.view = UI.lastPrimaryView || "discover";
    }
    syncUrl(false);
    S.saveState();
    if (runSuccessCallback && typeof cb === "function") {
      cb();
    }
  }

  function renderAuthPage(root) {
    if (App.state?.loggedIn && App.state.user?.username && App.state.user.username !== "guest") {
      const oauthFailed = new URLSearchParams(window.location.search).has("oauth_error");
      App.view = oauthFailed ? "account" : "discover";
      if (oauthFailed) UI.accountSection = "security";
      syncUrl(false);
      if (oauthFailed) renderAccountSettingsPage(root);
      else renderMain();
      if (oauthFailed) S.toast("第三方授权未完成。当前登录仍有效，请在账号安全中重新操作。");
      return;
    }
    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-auth-page" style="max-width:600px;margin:0 auto;">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="auth-page-back-btn">← 返回继续浏览</button>
            <span>/</span>
            <strong>🔑 登录 / 注册统一通行证</strong>
          </div>
        </div>
        <div class="hw-detail-section-card" style="padding:26px 28px;">
          <h1 style="margin:0 0 6px;font-size:22px;font-family:var(--font-serif);">Handraw 手绘风社区统一通行证</h1>
          <p style="margin:0 0 16px;font-size:13px;color:var(--ink-muted);">一次登录，主站视觉库、无限画布创作台、社区实战论坛与专属管理台实时互通。</p>
          <div id="standalone-auth-mount"></div>
        </div>
      </div>
    `;

    root.querySelector("#auth-page-back-btn").onclick = () => restoreAfterAuth(false);
    S.mountAuthPassStage(root.querySelector("#standalone-auth-mount"), {
      reasonText: UI.authReason,
      onCancel: () => restoreAfterAuth(false),
      onSuccess: () => restoreAfterAuth(true)
    });
  }

  /* ======================== STANDALONE SKILL GALLERY FUNNEL PAGE (?view=skill) ======================== */
  function renderSkillFunnelPage(root) {
    const sampleCodes = ["FA-001", "FX-001", "SC-021", "FB-031"];
    const sampleItems = sampleCodes.map((c) => App.resourceMap.get(c)).filter(Boolean);

    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-skill-page">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="skill-page-back-btn">← 返回画风库</button>
            <span>/</span>
            <strong>🔌 开源 Skill 本地画廊与官网联动指南</strong>
          </div>
        </div>

        <section class="hw-editorial-strip">
          <div>
            <p class="hw-editorial-eyebrow">开源扩展与在线创作双向飞轮</p>
            <h1 class="hw-editorial-title">从本地静态预览，一键跃迁至官网实测与无限画布</h1>
            <p class="hw-editorial-sub">本地用户浏览 375+ 画风与 174+ 图型卡时，点击编号即可直达官网独立详情评论页，查看真实生图案例或登录后在线创作。</p>
          </div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <a class="btn btn-primary" href="${esc(channelUrl("studio"))}">✨ 进入无限画布创作台 ↗</a>
            <button type="button" class="btn" id="skill-go-devices-btn">管理已授权设备</button>
          </div>
        </section>

        <section class="hw-detail-section-card">
          <h2 style="margin:0 0 14px;font-size:18px;font-family:var(--font-serif);">🎯 点击任一代表性资产，体验从本地卡片直达官网独立详情评论页</h2>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;">
            ${sampleItems
              .map(
                (it) => `
                  <article class="hw-card" data-skill-asset="${esc(it.id)}" style="cursor:pointer;margin:0;">
                    <div class="hw-card-media">
                      <img data-hw-src="${esc(it.image)}" alt="${esc(it.name)}" style="height:165px;object-fit:cover;" />
                    </div>
                    <div class="hw-card-body">
                      <div class="hw-card-code">${esc(it.id)}</div>
                      <h3 class="hw-card-title">${esc(it.name)}</h3>
                      <div style="font-size:12px;color:var(--ink-muted);margin-bottom:8px;">🖼️ ${S.getAssetWorkCount(it.id)} 件实测 · 💬 ${S.getAssetComments(it.id).length} 条评论</div>
                      <span class="btn btn-sm btn-primary" style="width:100%;justify-content:center;">打开独立详情与评论页 →</span>
                    </div>
                  </article>
                `
              )
              .join("")}
          </div>
        </section>
      </div>
    `;

    root.querySelector("#skill-page-back-btn").onclick = () => navigateBack("styles");
    const skillDevBtn = root.querySelector("#skill-go-devices-btn");
    if (skillDevBtn) {
      skillDevBtn.onclick = () => switchView("devices");
    }
    root.querySelectorAll("[data-skill-asset]").forEach((card) => {
      card.onclick = () => openAssetPage(card.getAttribute("data-skill-asset"));
    });
  }

  /* ======================== 3. CREDITS WALLET & FLYWHEEL CENTER ======================== */
  function renderWalletCenter(root) {
    if (!App.state.loggedIn) {
      openAuthPage("登录后即可查看积分钱包、签到领额度与管理已授权设备", () => switchView("wallet"));
      return;
    }
    const s = App.state;
    const shareTarget = UI.walletShareItem;

    root.innerHTML = `
      <section class="hw-editorial-strip">
        <div>
          <p class="hw-editorial-eyebrow">通用创作钱包 · 跨频道积分与权益中心</p>
          <h1 class="hw-editorial-title">当前可用：✦ ${s.credits} 积分</h1>
          <p class="hw-editorial-sub">今日免费云端生图额度：<strong>${s.freeQuotaRemaining} / ${s.freeQuotaMax} 次</strong> · 积分在主站、在线创作台与定制论坛实时互通。</p>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          ${s.demoMode ? `<button type="button" class="btn" data-topup="50">演示积分充值（不涉及付款）</button>` : `<span class="hw-wallet-payment-status">现金充值暂未开放，可通过签到、活动兑换与社区贡献获得积分。</span>`}
        </div>
      </section>

      ${
        shareTarget && shareTarget.item
          ? `<div style="margin-bottom:18px;">${S.renderInlineSharePanelHtml(shareTarget.itemType || "style", shareTarget.item)}</div>`
          : ""
      }

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:14px;margin-bottom:20px;">
        <div class="studio-step-card" style="margin:0;">
          <div style="font-weight:800;margin-bottom:6px;">📅 每日创作打卡 (+5 积分)</div>
          <p style="font-size:12.8px;color:var(--ink-muted);margin:0 0 12px;">每日访问签到领积分，并重置 3 次免费在线云端直出生图额度。</p>
          <button type="button" class="btn btn-sm ${s.dailyCheckedIn ? "" : "btn-primary"}" id="wallet-btn-checkin" ${s.dailyCheckedIn ? "disabled" : ""}>
            ${s.dailyCheckedIn ? "✅ 今日已打卡" : "立即签到领 +5 积分"}
          </button>
        </div>

        <div class="studio-step-card" style="margin:0;">
          <div style="font-weight:800;margin-bottom:6px;">🎟️ 积分礼券兑换码</div>
          <p style="font-size:12.5px;color:var(--ink-muted);margin:0 0 8px;">输入活动兑换码立领积分（可试：<code>HANDRAW2026</code>）</p>
          <div style="display:flex;gap:6px;">
            <input class="hw-input" id="wallet-redeem-input" placeholder="输入兑换码…" style="flex:1;padding:6px 9px;font-size:12.5px;" />
            <button type="button" class="btn btn-sm btn-primary" id="wallet-btn-redeem">兑换</button>
          </div>
        </div>

        <div class="studio-step-card" style="margin:0;">
          <div style="font-weight:800;margin-bottom:6px;">🌟 荒地开垦首晒奖 (+15 积分)</div>
          <p style="font-size:12.8px;color:var(--ink-muted);margin:0 0 12px;">给作品少于 3 个的冷门宝藏画风/图型发实战帖，双倍加奖且入驻新发曝光席！</p>
          <button type="button" class="btn btn-sm btn-primary" id="wallet-btn-pioneer">去发实战帖拿 +15 积分</button>
        </div>

        <div class="studio-step-card" style="margin:0;">
          <div style="font-weight:800;margin-bottom:6px;">📤 分享专属链接邀好友 (+15 积分/人)</div>
          <p style="font-size:12.8px;color:var(--ink-muted);margin:0 0 12px;">分享任意画风、图型或作品专属链接，好友注册双方得奖。</p>
          <button type="button" class="btn btn-sm btn-gold" id="wallet-btn-invite">展开专属分享面板</button>
        </div>

        <div class="studio-step-card" style="margin:0;">
          <div style="font-weight:800;margin-bottom:6px;">🎨 共创画风 / 图型讨论 (+15 积分)</div>
          <p style="font-size:12.8px;color:var(--ink-muted);margin:0 0 12px;">直通首发曝光席并冲刺殿堂荣誉，被解锁自动享 80% 积分分账。</p>
          <button type="button" class="btn btn-sm" id="wallet-btn-contrib">去共创交流板块</button>
        </div>

        <div class="studio-step-card" style="margin:0;">
          <div style="font-weight:800;margin-bottom:6px;">已授权设备与客户端</div>
          <p style="font-size:12.8px;color:var(--ink-muted);margin:0 0 12px;">管理已授予个人令牌的本地扩展与终端工具。</p>
          <button type="button" class="btn btn-sm" id="wallet-btn-go-devices">管理已授权设备</button>
        </div>
      </div>

      <div class="studio-step-card">
        <h3 style="margin:0 0 12px;font-size:16px;">📜 积分收支明细账本</h3>
        <div style="display:grid;gap:8px;">
          ${(s.ledger || [])
            .map(
              (row) => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 12px;background:var(--paper-bg);border-radius:8px;font-size:13.5px;">
                  <div>
                    <span style="color:var(--ink-muted);font-size:12px;margin-right:10px;">${esc(row.time)}</span>
                    <strong>${esc(row.reason)}</strong>
                  </div>
                  <strong style="color:${row.delta >= 0 ? "var(--jade)" : "var(--vermilion)"};font-variant-numeric:tabular-nums;">
                    ${row.delta >= 0 ? `+${row.delta}` : row.delta} ✦
                  </strong>
                </div>
              `
            )
            .join("")}
        </div>
      </div>
    `;

    if (shareTarget && shareTarget.item) {
      S.bindInlineSharePanel(root, shareTarget.itemType || "style", shareTarget.item, () => {
        UI.walletShareItem = null;
        renderMain();
      });
    }

    root.querySelectorAll("[data-topup]").forEach((btn) => {
      btn.onclick = async () => {
        const amt = Number(btn.getAttribute("data-topup"));
        if (App.state.serverBacked) {
          try {
            const res = await S.apiJson("/api/wallet/recharge", { method: "POST", body: { amount: amt } });
            await S.refreshFromServer();
            toast(`💎 充值到账 +${res.added} 积分！当前可用 ${res.credits}✦`);
          } catch (err) {
            toast(`充值失败：${err.message}`);
          }
          return;
        }
        S.addLedger(`在线充值积分加油包 (+${amt} 积分)`, amt);
        S.saveState();
        toast(`💎 充值演示成功！已到账 +${amt} 积分`);
      };
    });

    const ck = root.querySelector("#wallet-btn-checkin");
    if (ck) {
      ck.onclick = () => S.performServerCheckin();
    }

    const redeemBtn = root.querySelector("#wallet-btn-redeem");
    if (redeemBtn) {
      redeemBtn.onclick = async () => {
        const code = root.querySelector("#wallet-redeem-input").value.trim().toUpperCase();
        if (!code) {
          toast("请输入积分兑换码（例如 HANDRAW2026）");
          return;
        }
        if (App.state.serverBacked) {
          try {
            const res = await S.apiJson("/api/wallet/redeem", { method: "POST", body: { code } });
            await S.refreshFromServer();
            toast(`🎟️ 兑换成功！礼券码 ${res.code} 已到账 +${res.added}✦ 积分`);
          } catch (err) {
            toast(`兑换失败：${err.message}`);
          }
          return;
        }
        S.addLedger(`兑换积分礼券码 ${code}`, +30);
        S.saveState();
        toast(`🎟️ 兑换成功 +30 积分！`);
      };
    }

    const devBtn = root.querySelector("#wallet-btn-go-devices");
    if (devBtn) {
      devBtn.onclick = () => switchView("devices");
    }

    root.querySelector("#wallet-btn-pioneer").onclick = () => S.goToForumCompose({ style1: "FB-055", category: "assets" });
    root.querySelector("#wallet-btn-invite").onclick = () => {
      UI.walletShareItem = { itemType: "style", item: App.resourceMap.get("FX-001") || App.styles[0] };
      renderMain();
    };
    root.querySelector("#wallet-btn-contrib").onclick = () => S.goToCurationShare({ kind: UI.view === "layouts" ? "layout" : "style" });
  }



  /* ======================== BOOTSTRAP ======================== */
  parseInitialUrl();
  S.initApp("main", renderMain).then(() => {
    if (App.view === "collections") {
      const curU = (App.state && App.state.user && App.state.user.username && App.state.user.username !== "guest") ? App.state.user.username : "";
      if (App.state && App.state.loggedIn && curU) {
        openProfilePage(curU, "collections");
        syncUrl(false);
      } else {
        openAuthPage("登录后查看与同步你的云端收藏夹", () => {
          if (App.state && App.state.user && App.state.user.username) {
            openProfilePage(App.state.user.username, "collections");
            syncUrl(false);
          }
        });
        syncUrl(false);
      }
    } else if (App.view === "profile") {
      const curU = (App.state && App.state.user && App.state.user.username && App.state.user.username !== "guest") ? App.state.user.username : "";
      const isMe = Boolean(App.state && App.state.loggedIn && curU && curU === UI.profileUser);
      let urlChanged = false;
      if (UI.profileTab === "assets") {
        UI.profileTab = "styles";
        urlChanged = true;
      }
      if (!isMe && ["collections", "account", "articles"].includes(UI.profileTab)) {
        UI.profileTab = "works";
        urlChanged = true;
      }
      if (urlChanged) {
        syncUrl(false);
      }
    }
    updateSeoTitle();
    renderMain();
  }).catch((error) => {
    const incident = window.HandrawErrors?.report(error, {kind: "boot"});
    const root=document.getElementById("main-app-root");
    const message = error.status >= 400 && error.status < 500 ? error.message : "页面初始化未能完成，请稍后重试。";
    root.innerHTML=`<section class="hw-account-page"><h1>暂时无法加载社区</h1><p role="alert">${esc(message)}</p><p id="main-boot-reference" style="font-size:12px;overflow-wrap:anywhere;user-select:all"></p><button class="btn btn-primary" id="main-retry-boot">重试</button></section>`;
    const reference = root.querySelector("#main-boot-reference");
    if (incident && reference) {
      reference.textContent = "问题编号：" + incident.id;
      incident.listeners.push(id => { if (reference.isConnected) reference.textContent = "问题编号：" + id; });
    }
    root.querySelector("#main-retry-boot").onclick=()=>location.reload();
  });
})();
