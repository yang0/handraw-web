/* Main Channel Interactive App (handraw-style.com / localhost:3080)
 * Views (100% Standalone Pages — Zero Content/Profile Modals):
 * styles | layouts | works | rankings | collections | wallet | asset | work | profile | auth | skill
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
    pageSize: 60,
    shownCount: 60,
    spotlightCollapsed: window.matchMedia("(max-width: 700px)").matches,
    workSort: "recommended", // 'recommended' | 'newest' | 'cheers' | 'favorites' | 'paid'
    workAssoc: "all", // 'all' | 'both' | 'style_only' | 'layout_only' | 'freeform'
    workFilterAsset: "",
    workFilterAuthor: "",
    workQuery: "",
    worksSpotlightCollapsed: window.matchMedia("(max-width: 700px)").matches,
    rankTab: "creators", // 'creators' | 'works' | 'assets'
    rankPeriod: "week", // 'week' | 'month' | 'all' — default 'week' so fresh active faces shine first!
    lastPrimaryView: "styles", // parent channel to return to from secondary/detail pages
    creatorRankMode: "prolific", // 'prolific' | 'cheers' | 'rising'
    workRankMode: "composite", // 'composite' | 'cheers' | 'rising' | 'forks'
    favTab: "styles", // 'styles' | 'layouts' | 'works' | 'topics'
    // Standalone Detail & Profile Page States
    activeAssetId: "",
    assetSubTab: "works", // 'works' | 'topics'
    assetInlineDrawer: "", // '' | 'share' | 'report'
    assetFocusComments: false,
    activeWorkId: "",
    activeWorkImgIdx: 0,
    workInlineDrawer: "", // '' | 'share' | 'report'
    workFocusComment: false,
    profileUser: "",
    profileTab: "works", // 'works' | 'assets' | 'topics' | 'collections' | 'account'
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

    // Standalone Asset Detail & Comment Page (?view=asset&id=FA-001 or legacy ?asset=FA-001)
    if (view === "asset" || legacyAsset) {
      const code = (p.get("id") || legacyAsset || "").trim().toUpperCase().replace(/^#/, "");
      if (code) {
        if (view === "layouts") UI.lastPrimaryView = "layouts";
        else if (view === "styles") UI.lastPrimaryView = "styles";
        App.view = "asset";
        UI.activeAssetId = code;
        const tabParam = p.get("tab") || "";
        UI.assetSubTab = tabParam === "topics" ? "topics" : "works";
        UI.assetFocusComments = tabParam === "comments";
        UI.assetInlineDrawer = tabParam === "report" ? "report" : "";
        return {};
      }
    }

    // Standalone Work Detail & Comment Page (?view=work&id=w_101 or legacy ?work=w_101)
    if (view === "work" || legacyWork) {
      const wid = (p.get("id") || legacyWork || "").trim();
      if (wid) {
        UI.lastPrimaryView = "works";
        App.view = "work";
        UI.activeWorkId = wid;
        UI.activeWorkImgIdx = 0;
        UI.workFocusComment = p.get("focus") === "comment";
        UI.workInlineDrawer = "";
        return {};
      }
    }

    // Standalone Personal Homepage & Account Center (?view=profile&user=... or ?view=account)
    if (view === "profile" || view === "account") {
      App.view = "profile";
      UI.profileUser = (p.get("user") || "").trim();
      const reqTab = view === "account" ? "account" : p.get("ptab") || "works";
      UI.profileTab = ["works", "assets", "topics", "collections", "account"].includes(reqTab) ? reqTab : "works";
      return {};
    }

    if (view === "manage") {
      App.view = "works";
      try {
        window.history.replaceState({ view: "works" }, "", `${window.location.pathname}?view=works`);
      } catch (_) {}
      return {};
    }

    if (["styles", "layouts", "works", "rankings", "collections", "wallet", "auth", "skill", "guide", "recovery", "reset-password", "verify-email", "notifications", "edit-work", "edit-topic"].includes(view)) {
      App.view = view;
    } else {
      App.view = "styles";
    }

    if (p.get("filterAsset")) {
      UI.workFilterAsset = p.get("filterAsset").toUpperCase();
      App.view = "works";
    }
    if (p.get("author")) {
      UI.workFilterAuthor = p.get("author");
      App.view = "works";
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
      styles: `${App.styles?.length || 0} 款画风视觉库 — 手绘风创作社区`,
      layouts: `${App.layouts?.length || 0} 款图型与版式库 — 手绘风创作社区`,
      works: `实测作品广场（${wc} 件手绘生图作品与提示词配方）— 手绘风创作社区`,
      rankings: "创作者荣誉榜单与作品风云榜 — 手绘风创作社区",
      collections: "我的四合一云端收藏夹 — 手绘风创作社区",
      wallet: "统一积分钱包与创作密钥中心 — 手绘风创作社区",
      auth: "登录 / 注册统一通行证 — 手绘风创作社区",
      skill: "开源画廊与官网在线创作联动 — 手绘风创作社区"
    };
    if (App.view === "asset" && UI.activeAssetId) {
      const it = App.resourceMap.get(UI.activeAssetId);
      document.title = `${UI.activeAssetId}${it ? ` ${it.name}` : ""} 详情与评论 — Handraw 手绘风社区`;
      return;
    }
    if (App.view === "work" && UI.activeWorkId) {
      const w = (App.state?.works || []).find((x) => x.id === UI.activeWorkId);
      if (w) {
        document.title = `${w.title} (@${w.authorName}) 作品详情与评论 — Handraw 手绘风社区`;
        return;
      }
    }
    if (App.view === "profile") {
      const uname = UI.profileUser || App.state?.user?.username || "";
      const prof = uname ? S.getCreatorProfile(uname) : null;
      document.title = `${prof ? `@${prof.authorName} 的个人主页` : "个人主页与账号中心"} — Handraw 手绘风社区`;
      return;
    }
    document.title = titles[App.view] || "Handraw 手绘风社区 2.0 — 画风库 · 图型库 · 实测作品广场";
  }

  function syncUrl(pushHistory = false) {
    const p = new URLSearchParams();
    p.set("view", App.view);
    if (App.view === "works") {
      if (UI.workFilterAsset) p.set("filterAsset", UI.workFilterAsset);
      if (UI.workFilterAuthor) p.set("author", UI.workFilterAuthor);
    } else if (App.view === "rankings") {
      if (UI.rankTab) p.set("rtab", UI.rankTab);
      if (UI.rankPeriod) p.set("period", UI.rankPeriod);
    } else if (App.view === "asset" && UI.activeAssetId) {
      p.set("id", UI.activeAssetId);
      if (UI.assetSubTab === "topics") p.set("tab", "topics");
    } else if (App.view === "work" && UI.activeWorkId) {
      p.set("id", UI.activeWorkId);
    } else if (App.view === "profile") {
      const uname = UI.profileUser || (App.state?.user?.username && App.state.user.username !== "guest" ? App.state.user.username : "");
      if (uname) p.set("user", uname);
      if (UI.profileTab && UI.profileTab !== "works") p.set("ptab", UI.profileTab);
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
    if (["styles", "layouts", "works"].includes(App.view) && nextView !== App.view) {
      UI.lastPrimaryView = App.view;
    } else if (["styles", "layouts", "works"].includes(nextView)) {
      UI.lastPrimaryView = nextView;
    }
    const viewChanged = App.view !== nextView;
    App.view = nextView;
    UI.shownCount = UI.pageSize;
    if (extra.filterAsset !== undefined) UI.workFilterAsset = extra.filterAsset;
    if (extra.filterAuthor !== undefined) UI.workFilterAuthor = extra.filterAuthor;
    if (extra.rankTab !== undefined) UI.rankTab = extra.rankTab;
    if (extra.rankPeriod !== undefined) UI.rankPeriod = extra.rankPeriod;
    if (extra.shareItem !== undefined) UI.walletShareItem = extra.shareItem;
    syncUrl(viewChanged);
    S.saveState();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openAssetPage(assetId, subTab = "") {
    S.closeModal();
    const code = String(assetId || "").trim().toUpperCase().replace(/^#/, "");
    const item = App.resourceMap.get(code);
    if (!item) {
      toast(`未找到资产编号：${code}`);
      return;
    }
    if (["styles", "layouts", "works"].includes(App.view)) {
      UI.lastPrimaryView = App.view;
    } else if (App.view !== "asset") {
      UI.lastPrimaryView = item.kind === "layout" ? "layouts" : "styles";
    }
    const isEntering = App.view !== "asset" || UI.activeAssetId !== code;
    App.view = "asset";
    UI.activeAssetId = code;
    if (subTab === "topics" || subTab === "works") {
      UI.assetSubTab = subTab;
    } else if (isEntering) {
      UI.assetSubTab = "works";
    }
    UI.assetFocusComments = subTab === "comments";
    if (subTab === "report") UI.assetInlineDrawer = "report";
    else if (isEntering) UI.assetInlineDrawer = "";

    syncUrl(isEntering);
    S.saveState();
    if (isEntering && subTab !== "comments") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function openWorkPage(workId, imgIndex = 0, focusComment = false) {
    S.closeModal();
    const work = (App.state.works || []).find((w) => w.id === workId);
    if (!work) return;
    if (["styles", "layouts", "works"].includes(App.view)) {
      UI.lastPrimaryView = App.view;
    }
    const isEntering = App.view !== "work" || UI.activeWorkId !== work.id;
    App.view = "work";
    UI.activeWorkId = work.id;
    UI.activeWorkImgIdx = Number(imgIndex) || 0;
    UI.workFocusComment = Boolean(focusComment);
    if (isEntering) UI.workInlineDrawer = "";

    syncUrl(isEntering);
    S.saveState();
    if (isEntering && !focusComment) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function openProfilePage(username, ptab = "works") {
    S.closeModal();
    const targetUser = String(username || (App.state.user && App.state.user.username) || "").trim();
    if (!targetUser || targetUser === "guest") {
      openAuthPage("登录后即可查看与管理你的个人主页");
      return;
    }
    if (["styles", "layouts", "works"].includes(App.view)) {
      UI.lastPrimaryView = App.view;
    }
    const cleanTab = ["works", "assets", "topics", "collections", "account"].includes(ptab) ? ptab : "works";
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
        activeAssetId: UI.activeAssetId,
        activeWorkId: UI.activeWorkId,
        profileUser: UI.profileUser,
        profileTab: UI.profileTab
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
    if (!App.state.loggedIn) {
      return `
        <div class="hw-my-honor-card">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
            <span style="font-size:12.5px;font-weight:850;color:var(--gold);">🏆 社区创作者荣誉与曝光激励计划</span>
            <div style="display:flex;align-items:center;gap:5px;">
              <span class="hw-boost-pill">最高 1.45× 曝光加权</span>
              ${
                App.view !== "rankings"
                  ? `<button type="button" class="hw-pill" style="padding:2px 8px;font-size:11px;" data-jump-rankings="creators">查看榜单 ↗</button>`
                  : ""
              }
            </div>
          </div>
          <div style="font-size:12.5px;color:var(--ink-body);line-height:1.5;">
            新发布的画风、图型与作品直通 <strong>72h 首发曝光席</strong>；累计多发解锁四阶荣誉勋章与专属联展位！
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:2px;">
            ${actionButtonsHtml}
          </div>
        </div>
      `;
    }

    const me = S.getCreatorProfile(App.state.user.username);
    const h = me.honor;
    const activePeriodMeta = getPeriodMeta(UI.rankPeriod);
    const periodRanked = S.getTopCreators(100, "prolific", UI.rankPeriod);
    const myRankIdx = periodRanked.findIndex((c) => c.username === me.username);
    const rankLabel =
      myRankIdx >= 0
        ? `${activePeriodMeta.label.replace(/^[^\s]+\s*/, "")} #${myRankIdx + 1}`
        : `${activePeriodMeta.label.replace(/^[^\s]+\s*/, "")}待上榜`;

    let progressPct = 100;
    let progressHint = "🎉 已登顶社区最高殿堂荣誉！常驻全站联展与 1.45× 曝光加权";
    if (h.nextAt) {
      const prevMin = h.minCount || 0;
      const span = Math.max(1, h.nextAt - prevMin);
      progressPct = Math.min(95, Math.max(18, Math.round(((me.totalPublished - prevMin) / span) * 100)));
      const diff = Math.max(1, h.nextAt - me.totalPublished);
      progressHint = `已分享 ${me.totalPublished} 项 · 再发 ${diff} 项晋升「${h.nextTitle}」并赢 +10✦ 荣誉礼金`;
    }

    return `
      <div class="hw-my-honor-card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <button type="button" class="hw-author-chip" data-open-creator="${esc(me.username)}" title="点击查看我的创作者荣誉名片">
            <span class="hw-creator-avatar-sm ${esc(h.sealClass)}">${esc(me.avatarChar)}</span>
            <strong style="font-size:13px;color:var(--ink-strong);">${esc(me.authorName)}</strong>
            <span class="hw-honor-badge ${esc(h.sealClass)}">${esc(h.badge)}</span>
          </button>
          <div style="display:flex;align-items:center;gap:5px;">
            <span class="hw-boost-pill">🔥 ${esc(h.boostText)}</span>
            <button type="button" class="hw-pill" style="padding:2px 8px;font-size:11px;" data-jump-rankings="creators">${esc(rankLabel)} ↗</button>
          </div>
        </div>
        <div class="hw-honor-progress-track">
          <div class="hw-honor-progress-fill" style="width:${progressPct}%;"></div>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <span style="font-size:11.8px;color:var(--ink-muted);">${esc(progressHint)}</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:2px;">
          ${actionButtonsHtml}
        </div>
      </div>
    `;
  }

  /* ======================== RENDER ENTRY ======================== */
  function renderMain() {
    const root = document.getElementById("main-app-root");
    if (!root || !App.state) return;

    if (window.HandrawAccountTools?.views.has(App.view)) {
      window.HandrawAccountTools.render(root, App.view);
      return;
    }

    if (App.view === "styles") renderAssetCatalog(root, "style");
    else if (App.view === "layouts") renderAssetCatalog(root, "layout");
    else if (App.view === "works") renderWorksSquare(root);
    else if (App.view === "rankings") renderRankingsHall(root);
    else if (App.view === "collections") renderCollectionsCenter(root);
    else if (App.view === "wallet") renderWalletCenter(root);
    else if (App.view === "asset") renderAssetDetailPage(root);
    else if (App.view === "work") renderWorkDetailPage(root);
    else if (App.view === "profile") renderCreatorProfilePage(root);
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
        const hay = `${item.id} ${item.legacy || ""} ${item.name} ${item.description || ""} ${item.group || ""} ${item.authorName || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function getAssetExposureScore(item, statsMap) {
    const wCount = S.getAssetWorkCount(item.id);
    const freshBonus = S.isFreshRelease(item) ? 160 : 0;
    const commBonus = item.sourceType === "community" ? 42 : item.sourceType === "exclusive" ? 55 : 0;
    const prof = item.author && statsMap ? statsMap.get(item.author) : null;
    const honorBoost = prof ? prof.honor.boost : 1.0;
    const cheers = Number(item.cheers || 0);
    return Math.round((wCount * 36 + cheers * 1.1 + commBonus) * honorBoost + freshBonus);
  }

  function renderAssetCatalog(root, kind) {
    const isStyle = kind === "style";
    const activeGroup = isStyle ? UI.styleGroup : UI.layoutGroup;
    const groups = isStyle ? S.STYLE_GROUPS : S.LAYOUT_GROUPS;
    const allItems = isStyle ? App.styles : App.layouts;
    const statsMap = S.getCreatorStatsMap();

    const commItems = allItems.filter((i) => i.sourceType === "community");
    const freshSpotlightItems = commItems.filter((item) => S.isFreshRelease(item))
      .sort((a, b) => {
        const af = S.isFreshRelease(a) ? 1 : 0;
        const bf = S.isFreshRelease(b) ? 1 : 0;
        if (bf !== af) return bf - af;
        return S.compareByRecency(a, b);
      })
      .slice(0, 3);

    const topCreators = S.getTopCreators(5, "prolific", UI.rankPeriod);
    const pMeta = getPeriodMeta(UI.rankPeriod);
    const filtered = filterAssets(kind, activeGroup);

    filtered.sort((a, b) => {
      if (UI.assetSort === "recommended") {
        const sb = getAssetExposureScore(b, statsMap);
        const sa = getAssetExposureScore(a, statsMap);
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
      } else if (UI.assetSort === "hot") {
        const cwA = S.getAssetWorkCount(a.id);
        const cwB = S.getAssetWorkCount(b.id);
        if (cwB !== cwA) return cwB - cwA;
      }
      return a.id.localeCompare(b.id, "en");
    });

    const visibleItems = filtered.slice(0, UI.shownCount);
    const remaining = Math.max(0, filtered.length - visibleItems.length);
    const favBucket = isStyle ? "styles" : "layouts";
    const showCommunityStage = !UI.assetQuery.trim() && !UI.spotlightCollapsed;

    const heroActionsHtml = `
      <button type="button" class="btn btn-primary btn-sm" id="hero-btn-contribute">＋ 发布新${isStyle ? "画风" : "图型"} (+10✦)</button>
      <a class="btn btn-sm" href="${esc(channelUrl("studio"))}">✨ 在线创作工坊 ↗</a>
    `;

    root.innerHTML = `
      <section class="hw-editorial-strip hw-reveal-section">
        <div style="max-width:680px;flex:1 1 380px;">
          <p class="hw-editorial-eyebrow">${isStyle ? "画风视觉目录与共创中枢" : "图型版式目录与共创中枢"}</p>
          <h1 class="hw-editorial-title">
            ${
              isStyle
                ? "选择适合这次创作的画风"
                : "从清晰的图型开始排版"
            }
          </h1>
          <p class="hw-editorial-sub">
            已收录 <strong>${allItems.length}</strong> 款${isStyle ? "画风" : "图型"}（含 <strong>${commItems.length}</strong> 款创作者共创 · <strong>${allItems.filter((i) => S.getAssetWorkCount(i.id) > 0).length}</strong> 款已有社区实测作品）。新贡献资产自动登顶<strong>「72h 首发曝光席」</strong>，高产创作者享全站优先推荐加权！
          </p>
        </div>
        ${renderMyHonorStatusCard(heroActionsHtml)}
      </section>

      ${
        UI.assetQuery.trim()
          ? ""
          : UI.spotlightCollapsed
          ? `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;background:var(--paper-card);border:1px solid var(--line-soft);border-radius:10px;padding:8px 14px;margin-bottom:14px;font-size:12.5px;">
              <span>🌱 已折叠「新发${isStyle ? "画风" : "图型"}首发曝光席」与「共创主理人荣誉榜 前五名」</span>
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
                  <button type="button" class="btn btn-sm" id="spot-btn-contribute">＋ 我也要发新${isStyle ? "画风" : "图型"}</button>
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
                          <div class="hw-new-card-media" data-open-asset="${esc(item.id)}">
                            <span class="hw-card-badge-tl badge-new-release">🆕 ${esc(item.createdAt || "新发")}</span>
                            <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" loading="lazy" />
                            <span class="hw-new-card-time">${esc(item.id)}</span>
                          </div>
                          <div class="hw-new-card-body">
                            <h3 class="hw-card-title" style="font-size:13.5px;" data-open-asset="${esc(item.id)}">${esc(item.name)}</h3>
                            <p class="hw-card-desc" style="margin:0;font-size:11.6px;">${esc(item.description || "")}</p>
                            <div style="margin-top:auto;padding-top:6px;border-top:1px dashed var(--line-soft);display:flex;align-items:center;justify-content:space-between;gap:6px;">
                              <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                                <span class="hw-creator-avatar-sm ${esc(h.sealClass)}">${esc(prof.avatarChar)}</span>
                                <span style="max-width:74px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(prof.authorName)}</span>
                                <span class="hw-honor-badge ${esc(h.sealClass)}" style="padding:1px 5px;font-size:10px;">${esc(h.shortBadge)}</span>
                              </button>
                              <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-asset="${esc(item.id)}" title="为新发布的共创资产送上鼓励">
                                👏 ${item.cheers || 16}
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
                          <span class="hw-creator-avatar-sm ${esc(c.honor.sealClass)}">${esc(c.avatarChar)}</span>
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
              const cnt = filterAssets(kind, g.key).length;
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
              <option value="recommended" ${UI.assetSort === "recommended" ? "selected" : ""}>⚡ 综合推荐（新发扶持 + 高产加权）</option>
              <option value="newest" ${UI.assetSort === "newest" ? "selected" : ""}>🌱 最新入库优先</option>
              <option value="hot" ${UI.assetSort === "hot" ? "selected" : ""}>🔥 实测作品最多</option>
              <option value="exclusive" ${UI.assetSort === "exclusive" ? "selected" : ""}>🔒 官网在线独占置顶</option>
              <option value="code" ${UI.assetSort === "code" ? "selected" : ""}>🔢 按编号字母顺序</option>
            </select>
            <span style="font-size:12.5px;color:var(--ink-muted);">共筛出 <strong>${filtered.length}</strong> 项</span>
          </div>

          <div class="hw-controls-right">
            <button type="button" class="btn btn-primary btn-sm" id="catalog-btn-publish-asset">＋ 发布新${isStyle ? "画风" : "图型"}</button>
            <span style="font-size:12px;color:var(--ink-muted);margin-left:6px;">浏览密度：</span>
            <div class="hw-segmented" id="catalog-density">
              <button type="button" class="hw-seg-btn ${UI.density === "compact" ? "is-active" : ""}" data-density="compact">紧凑 8列</button>
              <button type="button" class="hw-seg-btn ${UI.density === "standard" ? "is-active" : ""}" data-density="standard">标准 5列</button>
              <button type="button" class="hw-seg-btn ${UI.density === "large" ? "is-active" : ""}" data-density="large">大图 3列</button>
            </div>
          </div>
        </div>
      </div>

      ${S.renderMasonry(
        visibleItems.map((item) => {
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
                    <span class="hw-creator-avatar-sm ${esc(prof.honor.sealClass)}">${esc(prof.avatarChar)}</span>
                    <span style="max-width:78px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(prof.authorName)}</span>
                    <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:1px 5px;">${esc(prof.honor.shortBadge)}</span>
                  </button>
                  <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-asset="${esc(item.id)}" title="为贡献者送上鼓励">
                    👏 ${item.cheers || 16}
                  </button>
                </div>
              `
              : "";

          return `
            <article class="hw-card ${isFresh ? "is-fresh-highlight" : ""}" data-asset-card="${esc(item.id)}">
              <div class="hw-card-media" data-open-asset="${esc(item.id)}">
                ${topBadge}
                <button type="button" class="hw-card-fav-btn ${collected ? "is-collected" : ""}" data-fav-asset="${esc(item.id)}" title="收藏此${isStyle ? "画风" : "图型"}">
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
                      <div style="display:flex;align-items:center;justify-content:space-between;gap:5px;margin-top:8px;padding-top:7px;border-top:1px dashed var(--line-soft);">
                        <button type="button" class="btn btn-sm ${liked ? "btn-primary" : ""}" style="padding:2px 7px;font-size:11px;" data-like-asset="${esc(item.id)}" title="点赞此${isStyle ? "画风" : "图型"}">
                          👍 ${likeCnt}
                        </button>
                        <button type="button" class="btn btn-sm ${collected ? "btn-primary" : ""}" style="padding:2px 7px;font-size:11px;" data-fav-asset="${esc(item.id)}" title="收藏此${isStyle ? "画风" : "图型"}">
                          ${collected ? "♥" : "♡"} ${favCnt}
                        </button>
                        <button type="button" class="btn btn-sm" style="padding:2px 7px;font-size:11px;" data-comment-asset="${esc(item.id)}" title="查看与发表评论">
                          💬 ${commentCnt}
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
        }),
        UI.density
      )}

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

    root.querySelector("#hero-btn-contribute").onclick = () => S.goToForumCompose({ category: "assets" });
    const catPubBtn = root.querySelector("#catalog-btn-publish-asset");
    if (catPubBtn) catPubBtn.onclick = () => S.goToForumCompose({ category: "assets" });
    const spotContrib = root.querySelector("#spot-btn-contribute");
    if (spotContrib) spotContrib.onclick = () => S.goToForumCompose({ category: "assets" });

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
    searchInput.oninput = (e) => {
      UI.assetQuery = e.target.value;
      UI.shownCount = UI.pageSize;
      renderMain();
      const nextInput = document.getElementById("catalog-search");
      if (nextInput) {
        nextInput.focus();
        nextInput.setSelectionRange(nextInput.value.length, nextInput.value.length);
      }
    };

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
        openAssetDrawer(btn.getAttribute("data-comment-asset"), "comments");
      };
    });

    root.querySelectorAll("[data-open-asset]").forEach((el) => {
      el.onclick = () => openAssetDrawer(el.getAttribute("data-open-asset"));
    });

    const loadMoreBtn = root.querySelector("#btn-load-more-assets");
    if (loadMoreBtn) {
      loadMoreBtn.onclick = () => {
        UI.shownCount += 80;
        renderMain();
      };
    }
  }

  /* ======================== STANDALONE ASSET DETAIL & COMMENT PAGE (?view=asset&id=...) ======================== */
  function openAssetDrawer(assetId, activeSubTab = "") {
    // Strictly navigate to standalone Asset Detail & Comment Page — never a popup modal
    openAssetPage(assetId, activeSubTab);
  }

  function renderAssetDetailPage(root) {
    const item = App.resourceMap.get(UI.activeAssetId);
    if (!item) {
      root.innerHTML = `
        <div class="hw-locked-gate-box" style="padding:48px 24px;">
          <div style="font-size:32px;margin-bottom:8px;">🔎</div>
          <h2>未找到对应的画风或图型编号：${esc(UI.activeAssetId || "未知")}</h2>
          <p style="color:var(--ink-muted);margin-bottom:18px;">该编号可能尚未入库或已被归档，请返回目录浏览全部视觉资产。</p>
          <button type="button" class="btn btn-primary" id="asset-missing-back-btn">← 返回画风库</button>
        </div>
      `;
      root.querySelector("#asset-missing-back-btn").onclick = () => switchView("styles");
      return;
    }

    const isStyle = item.kind === "style";
    const parentCatalogView = isStyle ? "styles" : "layouts";
    const parentCatalogLabel = isStyle ? "🎨 画风库" : "📐 图型库";
    const pool = isStyle ? App.styles : App.layouts;
    const curIdx = pool.findIndex((x) => x.id === item.id);
    const prevAsset = curIdx > 0 ? pool[curIdx - 1] : null;
    const nextAsset = curIdx >= 0 && curIdx < pool.length - 1 ? pool[curIdx + 1] : null;

    const favBucket = isStyle ? "styles" : "layouts";
    const liked = S.isLiked(item.kind, item.id);
    const likeCnt = S.getLikeCount(item.kind, item);
    const collected = S.isCollected(favBucket, item.id);
    const favCnt = S.getFavoriteCount(item.kind, item);
    const assetComments = S.getAssetComments(item.id);
    const unlocked = S.isUnlocked(item.id, item);
    const relatedWorks = S.getAssetWorks(item.id);
    const relatedTopics = S.getAssetTopics(item.id);
    const contributorProf = item.author ? S.getCreatorProfile(item.author) : null;
    const cheered = S.isCheered(item.id);
    const effectiveSubTab = UI.assetSubTab === "topics" ? "topics" : "works";
    const totalAssetWorks = S.getAssetWorkCount(item.id);

    const contributorEncourageHtml = contributorProf
      ? `
        <div class="hw-stamp-bar">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
            <button type="button" class="hw-author-chip" id="asset-page-open-contributor">
              <span class="hw-creator-avatar-sm ${esc(contributorProf.honor.sealClass)}">${esc(contributorProf.avatarChar)}</span>
              <strong>@${esc(contributorProf.authorName)}</strong>
              <span class="hw-honor-badge ${esc(contributorProf.honor.sealClass)}">${esc(contributorProf.honor.badge)}</span>
              <span class="hw-boost-pill">${esc(contributorProf.honor.boostText)}</span>
            </button>
            <button type="button" class="btn btn-sm" id="asset-page-visit-profile-btn">🏠 访问贡献者个人主页 (${contributorProf.totalPublished}作) ↗</button>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <button type="button" class="hw-stamp-btn ${cheered ? "is-active" : ""}" id="drawer-btn-cheer-asset">
              👏 感谢贡献 (${item.cheers || 16})
            </button>
            <button type="button" class="hw-stamp-btn ${S.isCheered(item.id, "超实用配方") ? "is-active" : ""}" data-asset-stamp="超实用配方">🎯 超实用配方 (${S.getStampCount(item, "超实用配方")})</button>
            <button type="button" class="hw-stamp-btn ${S.isCheered(item.id, "审美在线") ? "is-active" : ""}" data-asset-stamp="审美在线">✨ 审美在线 (${S.getStampCount(item, "审美在线")})</button>
            <button type="button" class="btn btn-sm btn-gold" id="drawer-btn-tip-asset" style="margin-left:auto;">🎁 赞赏 +2✦ 鼓励作者</button>
          </div>
        </div>
      `
      : `
        <div class="hw-stamp-bar">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <span style="font-size:12px;font-weight:800;color:var(--ink-muted);margin-right:4px;">官方标准编号 · 质量印章：</span>
            <button type="button" class="hw-stamp-btn ${cheered ? "is-active" : ""}" id="drawer-btn-cheer-asset">
              👏 好用推荐 (${item.cheers || 16})
            </button>
            <button type="button" class="hw-stamp-btn ${S.isCheered(item.id, "超实用配方") ? "is-active" : ""}" data-asset-stamp="超实用配方">🎯 超实用配方 (${S.getStampCount(item, "超实用配方")})</button>
            <button type="button" class="hw-stamp-btn ${S.isCheered(item.id, "审美在线") ? "is-active" : ""}" data-asset-stamp="审美在线">✨ 审美在线 (${S.getStampCount(item, "审美在线")})</button>
          </div>
        </div>
      `;

    let defSectionHtml = "";
    if (item.sourceType === "exclusive") {
      if (item.tier === "pro_credit" && !unlocked) {
        defSectionHtml = `
          <div style="background:var(--gold-wash);border:1px solid var(--gold-border);border-radius:12px;padding:14px 16px;">
            <div style="font-weight:800;color:var(--gold);margin-bottom:6px;">💎 Pro 官网在线独占${isStyle ? "画风" : "图型"}（底层参数黑盒保护）</div>
            <p style="margin:0 0 12px;font-size:13.2px;color:var(--ink-body);">解锁后永久获得在线创作工坊调用权限，云端生图自动注入全套高阶笔触/排版控制，不对外导出明文提示词。</p>
            <button type="button" class="btn btn-primary btn-sm" id="drawer-btn-unlock-exclusive">
              🔓 使用 ${item.unlockCost} 积分永久解锁在线使用权
            </button>
          </div>
        `;
      } else {
        defSectionHtml = `
          <div style="background:var(--paper-inset);border:1px solid var(--line-strong);border-radius:12px;padding:14px 16px;font-size:13.2px;">
            <strong>🔒 官网在线独占黑盒保护</strong>：${
              App.state.loggedIn
                ? `<span style="color:var(--jade);font-weight:700;">✅ 你的账号已解锁在线使用权！</span>点击上方「去在线创作台使用」即可在云端生图时自动挂载底层特征词。`
                : `登录账号即可在在线创作工坊免费调用该独占${isStyle ? "画风" : "图型"}！`
            }
          </div>
        `;
      }
    } else if (item.unlockCost > 0 && !unlocked) {
      defSectionHtml = `
        <div style="background:var(--vermilion-wash);border:1px solid var(--vermilion-border);border-radius:12px;padding:14px 16px;">
          <div style="font-weight:800;color:var(--vermilion);margin-bottom:6px;">✨ 社区共创付费${isStyle ? "画风" : "图型"}（${item.unlockCost} 积分，80% 归原作者）</div>
          <button type="button" class="btn btn-primary btn-sm" id="drawer-btn-unlock-comm">
            🔓 花费 ${item.unlockCost} 积分解锁定义词与在线调用
          </button>
        </div>
      `;
    } else {
      defSectionHtml = `
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <span style="font-size:12.8px;font-weight:800;color:var(--ink-muted);">📜 标准定义与视觉特征描述</span>
            <button type="button" class="btn btn-sm" id="drawer-btn-copy-def">📋 复制定义词</button>
          </div>
          <div class="hw-prompt-box">${esc(item.definition || item.description)}</div>
        </div>
      `;
    }

    const inlineDrawerHtml =
      UI.assetInlineDrawer === "share"
        ? S.renderInlineSharePanelHtml(item.kind, item)
        : UI.assetInlineDrawer === "report"
        ? S.renderInlineReportPanelHtml("asset", item.id, `${item.id} ${item.name}`)
        : "";

    let subContentHtml = "";
    if (effectiveSubTab === "works") {
      if (relatedWorks.length === 0) {
        subContentHtml = `
          <div class="hw-locked-gate-box" style="border-color:var(--gold-border);background:var(--gold-wash);">
            <div style="font-size:26px;margin-bottom:6px;">🌟</div>
            <h3 style="margin:0 0 6px;font-size:16px;color:var(--gold);">当前暂无挂载此编号的实测成片</h3>
            <p style="margin:0 0 14px;font-size:13px;color:var(--ink-body);">
              前往社区论坛独立发帖页附加多图实测成片与调参心得，立得 <strong>+5✦ 积分</strong>！
            </p>
            <button type="button" class="btn btn-primary" id="drawer-btn-pioneer-share">
              ✏️ 去论坛独立页发同款图文帖 (+5✦) ↗
            </button>
          </div>
        `;
      } else {
        subContentHtml = `
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:14px;">
            ${relatedWorks
              .map(
                (w) => `
                  <article class="hw-card" style="margin:0;cursor:pointer;" data-drawer-open-work="${esc(w.id)}">
                    <div class="hw-card-media">
                      ${S.isFreshRelease(w) ? `<span class="hw-card-badge-tl badge-new-release">🆕 新发</span>` : w.price > 0 && !S.isUnlocked(w.id, w) ? `<span class="hw-card-badge-tl badge-paid">💎 ${w.price}积分</span>` : ""}
                      <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" style="height:165px;object-fit:cover;" />
                    </div>
                    <div style="padding:10px 12px;">
                      <div style="font-size:13.5px;font-weight:750;line-height:1.38;margin-bottom:5px;">${esc(w.title)}</div>
                      <div style="font-size:12px;color:var(--ink-muted);">@${esc(w.authorName)} · 👍 ${S.getLikeCount("work", w)} · ♥ ${S.getFavoriteCount("work", w)} · 💬 ${(w.comments || []).length}</div>
                    </div>
                  </article>
                `
              )
              .join("")}
          </div>
        `;
      }
    } else {
      subContentHtml =
        relatedTopics.length === 0
          ? `<div style="padding:28px;text-align:center;color:var(--ink-muted);background:var(--paper-bg);border-radius:12px;">暂无关联论坛帖，去论坛独立发帖页分享你的使用心得立得 +5 积分！</div>`
          : `<div style="display:grid;gap:10px;">
              ${relatedTopics
                .map(
                  (t) => `
                    <a class="smart-embed-card" href="${esc(channelUrl("forum", { view: "topic", id: t.id }))}" style="justify-content:space-between;text-decoration:none;">
                      <div>
                        <div style="font-size:11.8px;color:var(--vermilion);font-weight:800;">${esc(t.categoryLabel)} ${t.price > 0 ? `· 💎 ${t.price}积分解锁干货` : ""} ${t.bounty > 0 ? `· 💰 悬赏 ${t.bounty}积分` : ""}</div>
                        <div style="font-weight:800;font-size:14.5px;margin:3px 0;color:var(--ink-strong);">${esc(t.title)}</div>
                        <div style="font-size:12px;color:var(--ink-muted);">@${esc(t.authorName)} · 💬 ${(t.replies || []).length} 条回复 · 👁️ ${t.views || 0}</div>
                      </div>
                      <span class="btn btn-sm">阅读帖子详情 ↗</span>
                    </a>
                  `
                )
                .join("")}
            </div>`;
    }

    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-asset-detail-page">
        <nav class="hw-subpage-bar" aria-label="详情页返回与翻页导航">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="asset-btn-back">← 返回${esc(isStyle ? "画风库" : "图型库")}</button>
            <span>/</span>
            <button type="button" class="hw-pill" style="padding:2px 10px;font-size:12px;" id="asset-crumb-catalog">${esc(parentCatalogLabel)}</button>
            <span>/</span>
            <strong>#${esc(item.id)} ${esc(item.name)}</strong>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            ${
              prevAsset
                ? `<button type="button" class="btn btn-sm" data-nav-asset="${esc(prevAsset.id)}">◀ 上一款 (${esc(prevAsset.id)})</button>`
                : ""
            }
            ${
              nextAsset
                ? `<button type="button" class="btn btn-sm" data-nav-asset="${esc(nextAsset.id)}">下一款 (${esc(nextAsset.id)}) ▶</button>`
                : ""
            }
          </div>
        </nav>

        <section class="hw-detail-grid">
          <div class="hw-detail-stage-wrap">
            <div class="hw-detail-stage">
              <img class="main-stage-img" src="${esc(item.image)}" alt="${esc(item.name)}" />
              <div style="color:#d8cfc3;font-size:12.5px;">
                标准视觉样张 · 编号 <strong>${esc(item.id)}</strong> ${item.legacy ? `(兼容旧版 #${esc(item.legacy)})` : ""} · 累计驱动 <strong>${totalAssetWorks}</strong> 件实测作品
              </div>
            </div>
            ${contributorEncourageHtml}
          </div>

          <div class="hw-detail-meta-card">
            ${
              S.isAdmin && S.isAdmin()
                ? `
                  <div id="asset-admin-drawer" style="background:rgba(180,40,20,0.06);border:1px solid rgba(180,40,20,0.25);border-radius:10px;padding:9px 12px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
                    <div style="font-size:12.5px;color:var(--vermilion);font-weight:750;">
                      👑 <strong>超管黑盒与资产管理</strong>：${esc(item.tier || "标准")} · ${item.sourceType === "exclusive" ? "🔒 云端独占" : "🌐 开放"}
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                      <button type="button" class="btn btn-sm btn-gold" id="asset-admin-edit-btn">✏️ 编辑资产与黑盒参数</button>
                      ${item.sourceType === "community" ? `<button type="button" class="btn btn-sm" id="asset-admin-toggle-status-btn" style="color:var(--vermilion);">${item.status === "paused" ? "▶️ 恢复资产" : "⏸️ 下架审查"}</button>` : ""}
                    </div>
                  </div>
                `
                : S.canManageGlobal && S.canManageGlobal() && item.sourceType === "community"
                ? `
                  <div id="asset-operator-drawer" style="background:rgba(31,95,139,0.08);border:1px solid rgba(31,95,139,0.25);border-radius:10px;padding:9px 12px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
                    <div style="font-size:12.5px;color:#1f5f8b;font-weight:750;">
                      🧭 <strong>运营审查</strong>：社区共创资产治理 (${item.status === "paused" ? "已下架" : "已上架"})
                    </div>
                    <button type="button" class="btn btn-sm" id="asset-admin-toggle-status-btn" style="color:var(--vermilion);">${item.status === "paused" ? "▶️ 恢复上架" : "⏸️ 下架审查"}</button>
                  </div>
                `
                : ""
            }
            <div>
              <p class="hw-editorial-eyebrow" style="margin-bottom:6px;">
                ${isStyle ? "画风标本与实测配方详情" : "图型标本与版式结构详情"}
              </p>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
                <span class="hw-recipe-pill ${!isStyle ? "is-layout" : ""}" style="font-size:12.5px;padding:3px 9px;">#${esc(item.id)}</span>
                <span class="hw-card-group-tag" style="font-size:12px;padding:2px 8px;">${esc(item.group)}</span>
                ${S.isFreshRelease(item) ? `<span class="hw-honor-badge honor-pioneer">🌱 72h 新发曝光扶持中</span>` : ""}
                ${item.sourceType === "community" ? `<span class="hw-honor-badge honor-gold">✨ 社区共创资产</span>` : ""}
              </div>
              <h1 class="hw-detail-title">${esc(item.id)} · ${esc(item.name)}</h1>
              <p style="margin:10px 0 0;font-size:14.5px;color:var(--ink-body);line-height:1.68;">${esc(item.description || "")}</p>
            </div>

            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding-top:4px;">
              <a class="btn btn-primary" href="${esc(channelUrl("studio", isStyle ? { style: item.id } : { layout: item.id }))}">
                ✨ 用此${isStyle ? "画风" : "图型"}去无限画布创作 ↗
              </a>
              <button type="button" class="btn ${liked ? "btn-primary" : ""}" id="drawer-btn-like">
                👍 ${liked ? "已赞" : "点赞"} (${likeCnt})
              </button>
              <button type="button" class="btn ${collected ? "btn-primary" : ""}" id="drawer-btn-collect">
                ${collected ? "♥ 已收藏" : "♡ 收藏"} (${favCnt})
              </button>
              <button type="button" class="btn" id="drawer-btn-forum-compose">
                📑 作为卡片分享到论坛 ↗
              </button>
              <button type="button" class="btn btn-gold" id="drawer-btn-share">
                📤 分享赚积分
              </button>
              <button type="button" class="btn btn-sm" id="drawer-btn-report-asset" title="举报违规或标注不实资产">
                🚩 举报
              </button>
            </div>

            ${inlineDrawerHtml}

            ${defSectionHtml}
          </div>
        </section>

        <!-- FULL-WIDTH STANDALONE COMMENTS SECTION -->
        <section class="hw-detail-section-card" id="asset-comments-box">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
            <div>
              <h2 style="margin:0;font-size:19px;font-family:var(--font-serif);">
                💬 ${isStyle ? "画风" : "图型"}实测评论与避坑心得 (${assetComments.length})
              </h2>
              <div style="font-size:12.5px;color:var(--ink-muted);margin-top:3px;">
                交流 <code>#${esc(item.id)}</code> 的笔触表现、适用主题、文字留白控制与混搭建议
              </div>
            </div>
          </div>

          <div class="hw-comments-composer">
            <textarea class="hw-textarea" rows="3" id="asset-comment-input" placeholder="写下你对 #${esc(item.id)} ${esc(item.name)} 的实测出图评价、提示词调参心得或搭配建议…"></textarea>
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
              <span style="font-size:12px;color:var(--ink-muted);">友善真实的实测反馈将帮助更多创作者少走弯路</span>
              <button type="button" class="btn btn-primary" id="asset-comment-send">💬 发表评论</button>
            </div>
          </div>

          <div class="hw-comments-list">
            ${
              assetComments.length === 0
                ? `<div style="padding:28px;text-align:center;font-size:13.5px;color:var(--ink-muted);background:var(--paper-bg);border-radius:12px;">暂无评论，来写下第一条关于 <code>#${esc(item.id)}</code> 的出图质感评价或配比心得吧～</div>`
                : assetComments
                    .map((c, idx) => {
                      const cUser = c.user || c.username || "";
                      const cProf = cUser ? S.getCreatorProfile(cUser) : null;
                      const avatarChar = cProf ? cProf.avatarChar : String(c.name || "绘").charAt(0).toUpperCase();
                      return `
                        <div class="hw-comment-item">
                          <span class="hw-creator-avatar-md ${esc(cProf ? cProf.honor.sealClass : "")}" style="${cUser ? "cursor:pointer;" : ""}" ${cUser ? `data-open-creator="${esc(cUser)}"` : ""}>${esc(avatarChar)}</span>
                          <div style="flex:1;min-width:0;">
                            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
                              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                                <strong style="font-size:13.5px;${cUser ? "cursor:pointer;" : ""}" ${cUser ? `data-open-creator="${esc(cUser)}"` : ""}>@${esc(c.name)}</strong>
                                ${cProf ? `<span class="hw-honor-badge ${esc(cProf.honor.sealClass)}" style="font-size:10px;padding:0 5px;">${esc(cProf.honor.shortBadge)}</span>` : ""}
                                <span style="color:var(--ink-faint);font-size:11.8px;">${esc(c.time)}</span>
                              </div>
                              <div style="display:flex;gap:6px;align-items:center;">
                                ${S.isStaff && S.isStaff() ? `<button type="button" class="btn btn-sm" data-hide-asset-comment="${esc(c.id || idx)}" style="font-size:11px;padding:1px 6px;color:var(--ink-muted);">🙈 隐藏</button>` : ""}
                                ${(S.canDeleteComment ? S.canDeleteComment(c) : (App.state.loggedIn && (cUser === App.state.user.username || (S.isStaff && S.isStaff())))) ? `<button type="button" class="btn btn-sm" data-del-asset-comment="${esc(c.id || idx)}" style="font-size:11px;padding:1px 6px;color:var(--vermilion);">🗑️ 删除</button>` : ""}
                                <span class="hw-comment-floor">#${idx + 1}楼</span>
                              </div>
                            </div>
                            <div style="font-size:14px;color:var(--ink-body);line-height:1.62;">${esc(c.text)}</div>
                          </div>
                        </div>
                      `;
                    })
                    .join("")
            }
          </div>
        </section>

        <!-- FULL-WIDTH RELATED COMMUNITY WORKS & FORUM TOPICS -->
        <section class="hw-detail-section-card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
            <div class="hw-segmented">
              <button type="button" class="hw-seg-btn ${effectiveSubTab === "works" ? "is-active" : ""}" id="drawer-tab-works">
                🖼️ 社区同款实测作品 (${totalAssetWorks})
              </button>
              <button type="button" class="hw-seg-btn ${effectiveSubTab === "topics" ? "is-active" : ""}" id="drawer-tab-topics">
                📋 关联论坛讨论帖 (${relatedTopics.length})
              </button>
            </div>
            <button type="button" class="btn btn-sm btn-primary" id="drawer-btn-add-work">
              📑 作为卡片分享到论坛交流 (+5✦) ↗
            </button>
          </div>
          ${subContentHtml}
        </section>
      </div>
    `;

    root.querySelector("#asset-btn-back").onclick = () => navigateBack(parentCatalogView);
    root.querySelector("#asset-crumb-catalog").onclick = () => switchView(parentCatalogView);
    root.querySelectorAll("[data-nav-asset]").forEach((btn) => {
      btn.onclick = () => openAssetPage(btn.getAttribute("data-nav-asset"));
    });

    const openContrib = root.querySelector("#asset-page-open-contributor");
    if (openContrib && contributorProf) {
      openContrib.onclick = () => openProfilePage(contributorProf.username, "works");
    }
    const visitContribBtn = root.querySelector("#asset-page-visit-profile-btn");
    if (visitContribBtn && contributorProf) {
      visitContribBtn.onclick = () => openProfilePage(contributorProf.username, "works");
    }

    root.querySelectorAll("[data-open-creator]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openProfilePage(el.getAttribute("data-open-creator"), "works");
      };
    });

    const cheerAssetBtn = root.querySelector("#drawer-btn-cheer-asset");
    if (cheerAssetBtn) {
      cheerAssetBtn.onclick = () => S.toggleCheerItem("asset", item.id);
    }
    root.querySelectorAll("[data-asset-stamp]").forEach((sb) => {
      sb.onclick = () => S.toggleCheerItem("asset", item.id, sb.getAttribute("data-asset-stamp"));
    });
    const tipAssetBtn = root.querySelector("#drawer-btn-tip-asset");
    if (tipAssetBtn) {
      tipAssetBtn.onclick = () => S.sendEncourageTip("asset", item.id, 2);
    }

    root.querySelector("#drawer-btn-like").onclick = () => {
      S.toggleLike(item.kind, item.id, `${item.id} ${item.name}`);
    };
    root.querySelector("#drawer-btn-collect").onclick = () => {
      S.toggleCollect(favBucket, item.id, `${item.id} ${item.name}`);
    };
    root.querySelector("#drawer-btn-forum-compose").onclick = () =>
      S.goToForumCompose({
        category: "assets",
        style1: isStyle ? item.id : "",
        layout: !isStyle ? item.id : "",
        topicTitle: `围绕${isStyle ? "画风" : "图型"}《${item.name}》的创作实测分享`,
        sharedCard: {
          kind: isStyle ? "style" : "layout",
          id: item.id,
          title: item.name,
          image: item.image,
          authorName: item.authorName || "Handraw 官方",
          desc: item.description || ""
        }
      });

    root.querySelector("#drawer-btn-share").onclick = () => {
      UI.assetInlineDrawer = UI.assetInlineDrawer === "share" ? "" : "share";
      renderMain();
    };
    root.querySelector("#drawer-btn-report-asset").onclick = () => {
      if (!App.state.loggedIn) {
        openAuthPage("登录后即可参与社区内容自治举报反馈", () => {
          UI.assetInlineDrawer = "report";
          renderMain();
        });
        return;
      }
      UI.assetInlineDrawer = UI.assetInlineDrawer === "report" ? "" : "report";
      renderMain();
    };

    if (UI.assetInlineDrawer === "share") {
      S.bindInlineSharePanel(root, item.kind, item, () => {
        UI.assetInlineDrawer = "";
        renderMain();
      });
    } else if (UI.assetInlineDrawer === "report") {
      S.bindInlineReportPanel(root, "asset", item.id, () => {
        UI.assetInlineDrawer = "";
        renderMain();
      });
    }

    const cmtInput = root.querySelector("#asset-comment-input");
    const cmtSend = root.querySelector("#asset-comment-send");
    if (UI.assetFocusComments && cmtInput) {
      UI.assetFocusComments = false;
      setTimeout(() => {
        const box = document.getElementById("asset-comments-box");
        if (box) box.scrollIntoView({ behavior: "smooth", block: "start" });
        cmtInput.focus();
      }, 40);
    }
    if (cmtSend) {
      cmtSend.onclick = async () => {
        const val = cmtInput.value.trim();
        if (!val) {
          toast("请输入评论内容");
          return;
        }
        try {
          const created = await S.submitAssetComment(item.id, item.kind, val);
          if (created) renderMain();
        } catch (err) {
          toast(`评论失败：${err.message}`);
        }
      };
    }

    const copyDef = root.querySelector("#drawer-btn-copy-def");
    if (copyDef) {
      copyDef.onclick = async () => {
        try {
          await navigator.clipboard.writeText(item.definition || item.description || "");
        } catch (_) {}
        toast(`📋 已复制 ${item.id} 定义词`);
      };
    }

    const unlockExcl = root.querySelector("#drawer-btn-unlock-exclusive");
    if (unlockExcl) {
      unlockExcl.onclick = () => {
        if (S.unlockWithCredits(item.id, item.unlockCost, `${item.id} ${item.name}`, "", () => renderMain())) {
          renderMain();
        }
      };
    }

    const unlockComm = root.querySelector("#drawer-btn-unlock-comm");
    if (unlockComm) {
      unlockComm.onclick = () => {
        if (S.unlockWithCredits(item.id, item.unlockCost, `${item.id} ${item.name}`, item.authorName, () => renderMain())) {
          renderMain();
        }
      };
    }

    root.querySelector("#drawer-tab-works").onclick = () => {
      UI.assetSubTab = "works";
      syncUrl(false);
      renderMain();
    };
    root.querySelector("#drawer-tab-topics").onclick = () => {
      UI.assetSubTab = "topics";
      syncUrl(false);
      renderMain();
    };

    const pioneerBtn = root.querySelector("#drawer-btn-pioneer-share");
    if (pioneerBtn) {
      pioneerBtn.onclick = () =>
        S.goToForumCompose({
          category: "assets",
          style1: isStyle ? item.id : "",
          layout: !isStyle ? item.id : "",
          topicTitle: `首晒《${item.name}》实测图文与配方心得`,
          sharedCard: {
            kind: isStyle ? "style" : "layout",
            id: item.id,
            title: item.name,
            image: item.image,
            authorName: item.authorName || "Handraw 官方",
            desc: item.description || ""
          }
        });
    }

    const addWorkBtn = root.querySelector("#drawer-btn-add-work");
    if (addWorkBtn) {
      addWorkBtn.onclick = () =>
        S.goToForumCompose({
          category: "assets",
          style1: isStyle ? item.id : "",
          layout: !isStyle ? item.id : "",
          topicTitle: `围绕《${item.name}》实测成片对比分享`,
          sharedCard: {
            kind: isStyle ? "style" : "layout",
            id: item.id,
            title: item.name,
            image: item.image,
            authorName: item.authorName || "Handraw 官方",
            desc: item.description || ""
          }
        });
    }

    root.querySelectorAll("[data-drawer-open-work]").forEach((card) => {
      card.onclick = () => openWorkPage(card.getAttribute("data-drawer-open-work"));
    });

    // Asset In-Place Admin & Operator Handlers
    const assetAdminEditBtn = root.querySelector("#asset-admin-edit-btn");
    if (assetAdminEditBtn) {
      assetAdminEditBtn.onclick = () => openFrontAssetEditModal(item.id);
    }
    const assetToggleBtn = root.querySelector("#asset-admin-toggle-status-btn");
    if (assetToggleBtn) {
      assetToggleBtn.onclick = async () => {
        const nextStatus = item.status === "paused" ? "active" : "paused";
        if (!confirm(`确定要将资产 #${item.id} 状态修改为 [${nextStatus}] 吗？`)) return;
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/admin/assets/${encodeURIComponent(item.id)}`, {
              method: "PATCH",
              body: { status: nextStatus }
            });
          }
          item.status = nextStatus;
          toast(`✅ 资产状态已修改为 ${nextStatus}！`);
          await S.refreshFromServer();
          renderMain();
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
      };
    }

    // Asset comments delete & hide
    root.querySelectorAll("[data-del-asset-comment]").forEach((btn) => {
      btn.onclick = async () => {
        const cid = btn.getAttribute("data-del-asset-comment");
        if (!confirm("确定要删除此条资产评论吗？")) return;
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/comments/moderate`, {
              method: "POST",
              body: { commentType: "asset_comment", id: cid, assetCode: item.id, action: "delete" }
            });
          }
          toast("🗑️ 资产评论已删除！");
          await S.refreshFromServer();
          renderMain();
        } catch (err) {
          toast(`删除评论失败：${err.message}`);
        }
      };
    });
    root.querySelectorAll("[data-hide-asset-comment]").forEach((btn) => {
      btn.onclick = async () => {
        const cid = btn.getAttribute("data-hide-asset-comment");
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/comments/moderate`, {
              method: "POST",
              body: { commentType: "asset_comment", id: cid, assetCode: item.id, action: "hide" }
            });
          }
          toast("🙈 资产评论已隐藏！");
          await S.refreshFromServer();
          renderMain();
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
      };
    });
  }

  /* ======================== 2. WORKS SQUARE (PUBLIC SEO + HONOR SPOTLIGHT + NEW EXPOSURE + LEADERBOARD) ======================== */
  function renderWorksSquare(root) {
    const allWorks = App.state.works || [];
    const statsMap = S.getCreatorStatsMap();
    const pMeta = getPeriodMeta(UI.rankPeriod);
    const topCreators = S.getTopCreators(3, "prolific", UI.rankPeriod);
    const totalCheersAll = allWorks.reduce((sum, w) => sum + Number(w.cheers || 0), 0);

    const freshWorks = S.getRankedWorks(4, "rising", "week");
    const topRankedWorks = S.getRankedWorks(5, "composite", UI.rankPeriod);

    const q = UI.workQuery.trim().toLowerCase();
    const filtered = allWorks.filter((w) => {
      const hasS = w.styles && w.styles.length > 0;
      const hasL = Boolean(w.layout);
      if (UI.workAssoc === "both" && !(hasS && hasL)) return false;
      if (UI.workAssoc === "style_only" && !(hasS && !hasL)) return false;
      if (UI.workAssoc === "layout_only" && !(!hasS && hasL)) return false;
      if (UI.workAssoc === "freeform" && (hasS || hasL)) return false;
      if (UI.workFilterAsset) {
        const hit = (w.styles || []).includes(UI.workFilterAsset) || w.layout === UI.workFilterAsset;
        if (!hit) return false;
      }
      if (UI.workFilterAuthor && w.author !== UI.workFilterAuthor) return false;
      if (UI.workSort === "paid" && !(w.price > 0)) return false;
      if (q) {
        const hay = `${w.title} ${w.prompt} ${(w.styles || []).join(" ")} ${w.layout || ""} ${w.authorName}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    filtered.sort((a, b) => {
      if (UI.workSort === "newest") {
        return S.compareByRecency(a, b);
      }
      if (UI.workSort === "cheers") return (b.cheers || 0) - (a.cheers || 0);
      if (UI.workSort === "favorites") return (b.favorites || 0) - (a.favorites || 0);
      return S.getWorkCompositeScore(b, statsMap) - S.getWorkCompositeScore(a, statsMap);
    });

    const hasActiveFilter = Boolean(q || UI.workFilterAsset || UI.workFilterAuthor);
    const activeAuthorProf = UI.workFilterAuthor ? S.getCreatorProfile(UI.workFilterAuthor) : null;

    const heroActionsHtml = `
      <button type="button" class="btn btn-primary btn-sm" id="works-btn-publish">＋ 晒我的作品（入驻新发曝光席 +5~15✦）</button>
      <button type="button" class="btn btn-gold btn-sm" data-jump-rankings="works">🏆 冲击作品风云榜 ↗</button>
    `;

    root.innerHTML = `
      <section class="hw-editorial-strip hw-reveal-section">
        <div style="max-width:680px;flex:1 1 380px;">
          <p class="hw-editorial-eyebrow">社区实测作品与创作者联展</p>
          <h1 class="hw-editorial-title">每一份实测分享都值得被看见、被鼓励、被授予荣光</h1>
          <p class="hw-editorial-sub">
            全站累计沉淀 <strong>${allWorks.length}</strong> 件可复刻作品 · 共送出 <strong style="color:var(--vermilion);">👏 ${totalCheersAll}</strong> 次鼓励支持。新发作品保底登台破冰，高产主理人享专属三图联展与最高 <strong>1.45× 瀑布流优先曝光</strong>！
          </p>
        </div>
        ${renderMyHonorStatusCard(heroActionsHtml)}
      </section>

      ${
        hasActiveFilter
          ? ""
          : UI.worksSpotlightCollapsed
          ? `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;background:var(--paper-card);border:1px solid var(--line-soft);border-radius:10px;padding:8px 14px;margin-bottom:14px;font-size:12.5px;">
              <span>👑 已折叠「活跃主理人联展」「作品风云榜 前五名」与「新发破冰曝光席」</span>
              <div style="display:flex;gap:6px;">
                <button type="button" class="btn btn-sm btn-primary" data-jump-rankings="works">完整榜单 ↗</button>
                <button type="button" class="btn btn-sm" id="btn-toggle-works-spotlight">展开联展与排行榜 ▾</button>
              </div>
            </div>
          `
          : `
            <!-- Row 1: Prolific Creator Gallery Spotlight + Live Top-5 Works Leaderboard -->
            <section class="hw-community-stage hw-reveal-section">
              <div class="hw-spotlight-panel is-warm-gold">
                <div class="hw-panel-head">
                  <div>
                    <div class="hw-panel-title-wrap">
                      <h2 class="hw-panel-title">👑 活跃主理人 · 专属联展席</h2>
                      ${renderPeriodSwitchHtml(true)}
                    </div>
                    <div class="hw-panel-sub">${
                      UI.rankPeriod === "all"
                        ? "历史累计高产创作者联展，享最高 1.45× 推荐加权"
                        : `${esc(pMeta.shortPrefix)}新发与互动活跃榜（新人新作优先登台，告别熟面孔霸榜）`
                    }</div>
                  </div>
                  <button type="button" class="btn btn-sm btn-gold" data-jump-rankings="creators">创作者榜单 ↗</button>
                </div>

                <div class="hw-prolific-grid">
                  ${topCreators
                    .map((c, idx) => {
                      const pubVal = UI.rankPeriod === "all" ? c.totalPublished : c.periodPublished;
                      const cheerVal = UI.rankPeriod === "all" ? c.totalCheers : c.periodCheers;
                      const thumbPool =
                        UI.rankPeriod !== "all" && c.periodWorks && c.periodWorks.length ? c.periodWorks : c.works;
                      return `
                        <article class="hw-prolific-card">
                          <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">
                            <span class="hw-honor-badge ${esc(c.honor.sealClass)}">${idx === 0 ? "🥇 " : idx === 1 ? "🥈 " : "🥉 "}${esc(c.honor.badge)}</span>
                            <span class="hw-boost-pill">${esc(c.honor.boostText)}</span>
                          </div>
                          <div style="display:flex;align-items:center;gap:9px;cursor:pointer;" data-open-creator="${esc(c.username)}">
                            <span class="hw-creator-avatar-md ${esc(c.honor.sealClass)}">${esc(c.avatarChar)}</span>
                            <div style="min-width:0;flex:1;">
                              <div style="font-weight:850;font-size:13.8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(c.authorName)}</div>
                              <div style="font-size:11.3px;color:var(--ink-muted);">${esc(pMeta.shortPrefix)} <strong>${pubVal}</strong> 篇 · 获 <strong>${cheerVal}</strong> 👏</div>
                            </div>
                          </div>
                          <div class="hw-prolific-thumbs">
                            ${thumbPool
                              .slice(0, 3)
                              .map(
                                (pw) =>
                                  `<img data-hw-src="${esc(pw.images[0])}" alt="${esc(pw.title)}" title="${esc(pw.title)}" data-open-work="${esc(pw.id)}" loading="lazy" />`
                              )
                              .join("")}
                          </div>
                          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-top:auto;">
                            <button type="button" class="btn btn-sm" style="padding:2px 8px;font-size:11.5px;" data-open-creator="${esc(c.username)}">荣誉主页</button>
                            <button type="button" class="btn btn-sm btn-primary" style="padding:2px 8px;font-size:11.5px;" data-filter-author="${esc(c.username)}">看全部作品 (${c.works.length})</button>
                          </div>
                        </article>
                      `;
                    })
                    .join("")}
                </div>
              </div>

              <!-- Right: Live Top 5 Works Leaderboard -->
              <div class="hw-spotlight-panel">
                <div class="hw-panel-head">
                  <div>
                    <div class="hw-panel-title-wrap">
                      <h2 class="hw-panel-title">🔥 作品风云榜 前五名</h2>
                      ${renderPeriodSwitchHtml(true)}
                    </div>
                    <div class="hw-panel-sub">${
                      UI.rankPeriod === "all"
                        ? "历史经典作品综合热度排行"
                        : `${esc(pMeta.shortPrefix)}新发布高人气作品实时排定`
                    }</div>
                  </div>
                  <div style="display:flex;gap:6px;">
                    <button type="button" class="btn btn-sm btn-primary" data-jump-rankings="works">完整榜单 ↗</button>
                    <button type="button" class="btn btn-sm" id="btn-toggle-works-spotlight" title="收起展台">收起</button>
                  </div>
                </div>

                <div class="hw-mini-rank-list">
                  ${topRankedWorks
                    .map((w, idx) => {
                      const rankCls = idx < 3 ? `rank-${idx + 1}` : "";
                      const prof = statsMap.get(w.author) || S.getCreatorProfile(w.author);
                      const cheered = S.isCheered(w.id);
                      return `
                        <div class="hw-mini-rank-row" data-open-work="${esc(w.id)}">
                          <span class="hw-rank-num ${rankCls}">${String(idx + 1).padStart(2, "0")}</span>
                          <img data-hw-src="${esc(w.images[0])}" alt="" style="width:42px;height:42px;border-radius:7px;object-fit:cover;flex-shrink:0;border:1px solid var(--line-soft);" />
                          <div style="min-width:0;flex:1;">
                            <div style="font-size:12.6px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(w.title)}</div>
                            <div style="font-size:11.2px;color:var(--ink-muted);display:flex;align-items:center;gap:5px;margin-top:2px;">
                              <span>@${esc(w.authorName)}</span>
                              <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:9.8px;padding:0 5px;">${esc(prof.honor.shortBadge)}</span>
                            </div>
                          </div>
                          <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-work="${esc(w.id)}" title="点鼓励助作品冲榜">
                            👏 ${w.cheers || 12}
                          </button>
                        </div>
                      `;
                    })
                    .join("")}
                </div>
              </div>
            </section>

            <!-- Row 2: Newly Published Works Exposure & First-Cheer Stage -->
            <section class="hw-spotlight-panel is-fresh-jade hw-reveal-section" style="margin-bottom:18px;">
              <div class="hw-panel-head">
                <div>
                  <div class="hw-panel-title-wrap">
                    <h2 class="hw-panel-title">🌱 新发作品 · 破冰曝光与鼓励席</h2>
                    <span class="hw-honor-badge honor-pioneer">新发必有曝光 · 给新人与新作送上掌声</span>
                  </div>
                  <div class="hw-panel-sub">最新发布的社区作品优先在此轮展，你的每一次「👏 鼓励」都会直接帮新作获得更高推荐权重！</div>
                </div>
                <button type="button" class="btn btn-sm" id="fresh-stage-btn-share">＋ 发布作品抢占首排</button>
              </div>

              <div class="hw-new-works-grid">
                ${freshWorks
                  .map((w) => {
                    const prof = statsMap.get(w.author) || S.getCreatorProfile(w.author);
                    const cheered = S.isCheered(w.id);
                    return `
                      <article class="hw-new-card" data-fresh-work="${esc(w.id)}">
                        <div class="hw-new-card-media" data-open-work="${esc(w.id)}">
                          <span class="hw-card-badge-tl badge-new-release">🆕 ${esc(w.createdAt || "刚刚新发")}</span>
                          <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" loading="lazy" />
                        </div>
                        <div class="hw-new-card-body">
                          <h3 class="hw-card-title" style="font-size:13.3px;" data-open-work="${esc(w.id)}">${esc(w.title)}</h3>
                          <div style="font-size:11.4px;color:var(--ink-muted);display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;">
                            ${esc(w.notes || w.prompt)}
                          </div>
                          <div style="margin-top:auto;padding-top:7px;border-top:1px dashed var(--line-soft);display:flex;align-items:center;justify-content:space-between;gap:6px;">
                            <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                              <span class="hw-creator-avatar-sm ${esc(prof.honor.sealClass)}">${esc(prof.avatarChar)}</span>
                              <span style="max-width:74px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(w.authorName)}</span>
                              <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:1px 5px;">${esc(prof.honor.shortBadge)}</span>
                            </button>
                            <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-work="${esc(w.id)}">
                              👏 鼓励 ${w.cheers || 1}
                            </button>
                          </div>
                        </div>
                      </article>
                    `;
                  })
                  .join("")}
              </div>
            </section>
          `
      }

      <div class="hw-filter-bar">
        <div class="hw-pills-row">
          <button type="button" class="hw-pill ${UI.workAssoc === "all" ? "is-active" : ""}" data-wassoc="all">全部关联类型 (${allWorks.length})</button>
          <button type="button" class="hw-pill ${UI.workAssoc === "both" ? "is-active" : ""}" data-wassoc="both">🎨+📐 画风+图型齐全</button>
          <button type="button" class="hw-pill ${UI.workAssoc === "style_only" ? "is-active" : ""}" data-wassoc="style_only">🎨 仅指定画风</button>
          <button type="button" class="hw-pill ${UI.workAssoc === "layout_only" ? "is-active" : ""}" data-wassoc="layout_only">📐 仅指定图型</button>
          <button type="button" class="hw-pill ${UI.workAssoc === "freeform" ? "is-active" : ""}" data-wassoc="freeform">🌿 自由创作 (无编号)</button>
          ${
            UI.workFilterAsset
              ? `<button type="button" class="hw-pill is-active" id="clear-work-asset-filter">正在筛选资产：${esc(UI.workFilterAsset)} ×</button>`
              : ""
          }
          ${
            activeAuthorProf
              ? `<button type="button" class="hw-pill is-active" id="clear-work-author-filter">${esc(activeAuthorProf.honor.shortBadge)} 正在看 @${esc(activeAuthorProf.authorName)} 的全部作品 ×</button>`
              : ""
          }
        </div>

        <div class="hw-controls-row">
          <div class="hw-controls-left">
            <div class="hw-segmented">
              <button type="button" class="hw-seg-btn ${UI.workSort === "recommended" ? "is-active" : ""}" data-wsort="recommended">⚡ 综合曝光 (新发+高产加权)</button>
              <button type="button" class="hw-seg-btn ${UI.workSort === "newest" ? "is-active" : ""}" data-wsort="newest">🌱 最新发布</button>
              <button type="button" class="hw-seg-btn ${UI.workSort === "cheers" ? "is-active" : ""}" data-wsort="cheers">👏 最多鼓励</button>
              <button type="button" class="hw-seg-btn ${UI.workSort === "favorites" ? "is-active" : ""}" data-wsort="favorites">♥ 最多收藏</button>
              <button type="button" class="hw-seg-btn ${UI.workSort === "paid" ? "is-active" : ""}" data-wsort="paid">💎 付费精品配方</button>
            </div>
            <input type="search" class="hw-input" id="works-search-input" value="${esc(UI.workQuery)}" placeholder="搜作品标题 / 提示词 / 创作者…" />
          </div>
          <div class="hw-controls-right" style="margin-left:auto;display:flex;align-items:center;gap:10px;">
            <button type="button" class="btn btn-primary btn-sm" id="works-btn-square-publish">＋ 晒出实测作品</button>
            <span style="font-size:12.5px;color:var(--ink-muted);">共 <strong>${filtered.length}</strong> 件作品</span>
          </div>
        </div>
      </div>

      ${S.renderMasonry(
        filtered.map((w) => {
          const liked = S.isLiked("work", w.id);
          const likeCnt = S.getLikeCount("work", w);
          const collected = S.isCollected("works", w.id);
          const favCnt = S.getFavoriteCount("works", w);
          const cmtCnt = (w.comments || []).length;
          const unlocked = S.isUnlocked(w.id, w);
          const cheered = S.isCheered(w.id);
          const isFresh = S.isFreshRelease(w);
          const prof = statsMap.get(w.author) || S.getCreatorProfile(w.author);
          const hasS = w.styles && w.styles.length > 0;
          const hasL = Boolean(w.layout);

          let pillsHtml = "";
          if (hasS || hasL) {
            pillsHtml =
              (w.styles || [])
                .map((sid) => `<span class="hw-recipe-pill" data-pill-asset="${esc(sid)}">#${esc(sid)}</span>`)
                .join("") +
              (w.layout ? `<span class="hw-recipe-pill is-layout" data-pill-asset="${esc(w.layout)}">📐 ${esc(w.layout)}</span>` : "");
          } else {
            pillsHtml = `<span class="hw-recipe-pill" style="background:var(--jade-wash);border-color:#bce3cb;color:var(--jade);">🌿 自由创作</span>`;
          }

          let tlBadge = "";
          if (w.price > 0) {
            tlBadge = `<span class="hw-card-badge-tl badge-paid">${unlocked ? "💎 已解锁配方" : `💎 ${w.price} 积分配方`}</span>`;
          } else if (isFresh) {
            tlBadge = `<span class="hw-card-badge-tl badge-new-release">🆕 新发曝光 · ${esc(w.createdAt || "新作品")}</span>`;
          } else if (prof.honor.tier >= 4) {
            tlBadge = `<span class="hw-card-badge-tl badge-honor-hall">👑 殿堂主理人精选</span>`;
          }

          return `
            <article class="hw-card ${isFresh ? "is-fresh-highlight" : prof.honor.tier >= 4 ? "is-hall-highlight" : ""}" data-work-card="${esc(w.id)}">
              <div class="hw-card-media" data-open-work="${esc(w.id)}">
                ${tlBadge}
                <button type="button" class="hw-card-fav-btn ${collected ? "is-collected" : ""}" data-fav-work="${esc(w.id)}" title="收藏作品">
                  ${collected ? "♥" : "♡"}
                </button>
                <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" loading="lazy" />
                ${w.images.length > 1 ? `<span class="hw-card-workcount">1/${w.images.length} 多图</span>` : ""}
              </div>
              <div class="hw-card-body">
                <h3 class="hw-card-title" data-open-work="${esc(w.id)}">${esc(w.title)}</h3>
                <div class="hw-recipe-pills">${pillsHtml}</div>
                <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:6px;">
                  <button type="button" class="hw-author-chip" data-open-creator="${esc(prof.username)}">
                    <span class="hw-creator-avatar-sm ${esc(prof.honor.sealClass)}">${esc(prof.avatarChar)}</span>
                    <span style="max-width:86px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(w.authorName)}</span>
                    <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:1px 5px;">${esc(prof.honor.shortBadge)}</span>
                  </button>
                  <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" style="padding:2px 6px;font-size:11px;" data-cheer-work="${esc(w.id)}" title="为作者作品送上鼓励">
                    👏 ${w.cheers || 12}
                  </button>
                </div>
                <div class="hw-card-footer" style="gap:5px;flex-wrap:wrap;">
                  <button type="button" class="btn btn-sm ${liked ? "btn-primary" : ""}" style="padding:2px 7px;font-size:11px;" data-like-work="${esc(w.id)}" title="点赞作品">
                    👍 ${likeCnt}
                  </button>
                  <button type="button" class="btn btn-sm ${collected ? "btn-primary" : ""}" style="padding:2px 7px;font-size:11px;" data-fav-work="${esc(w.id)}" title="收藏作品">
                    ${collected ? "♥" : "♡"} ${favCnt}
                  </button>
                  <button type="button" class="btn btn-sm" style="padding:2px 7px;font-size:11px;" data-comment-work="${esc(w.id)}" title="评论作品">
                    💬 ${cmtCnt}
                  </button>
                  <span style="font-size:11px;color:var(--ink-muted);">⚡ ${w.forks || 0}</span>
                  ${
                    (S.canModerateWork ? S.canModerateWork(w) : false)
                      ? `
                        <span style="display:inline-flex;gap:3px;align-items:center;margin-left:auto;">
                          <button type="button" class="btn btn-sm" style="padding:1px 5px;font-size:10.5px;" data-work-mod-op="${w.featured ? "unfeature" : "feature"}" data-work-id="${esc(w.id)}">${w.featured ? "取消精选" : "🌟 精选"}</button>
                          <button type="button" class="btn btn-sm" style="padding:1px 5px;font-size:10.5px;color:var(--vermilion);font-weight:750;" data-work-mod-op="delete" data-work-id="${esc(w.id)}">🗑️ 删</button>
                        </span>
                      `
                      : (S.canDeleteWork ? S.canDeleteWork(w) : (App.state.loggedIn && App.state.user && w.author === App.state.user.username))
                      ? `
                        <button type="button" class="btn btn-sm" style="padding:1px 5px;font-size:10.5px;color:var(--vermilion);margin-left:auto;" data-work-mod-op="delete" data-work-id="${esc(w.id)}">🗑️ 删除</button>
                      `
                      : ""
                  }
                </div>
              </div>
            </article>
          `;
        }),
        "standard"
      )}
    `;

    root.querySelector("#works-btn-publish").onclick = () => S.goToForumCompose({ category: "tuning" });
    const sqPub = root.querySelector("#works-btn-square-publish");
    if (sqPub) sqPub.onclick = () => S.goToForumCompose({ category: "tuning" });
    const freshShareBtn = root.querySelector("#fresh-stage-btn-share");
    if (freshShareBtn) freshShareBtn.onclick = () => S.goToForumCompose({ category: "tuning" });

    const toggleWorksSpot = root.querySelector("#btn-toggle-works-spotlight");
    if (toggleWorksSpot) {
      toggleWorksSpot.onclick = () => {
        UI.worksSpotlightCollapsed = !UI.worksSpotlightCollapsed;
        renderMain();
      };
    }
    bindPeriodSwitch(root);

    root.querySelectorAll("[data-jump-rankings]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        switchView("rankings", { rankTab: btn.getAttribute("data-jump-rankings") || "works" });
      };
    });

    root.querySelectorAll("[data-open-creator]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openCreatorCard(el.getAttribute("data-open-creator"));
      };
    });

    root.querySelectorAll("[data-filter-author]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        UI.workFilterAuthor = btn.getAttribute("data-filter-author");
        syncUrl();
        renderMain();
      };
    });

    root.querySelectorAll("[data-cheer-work]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        S.toggleCheerItem("work", btn.getAttribute("data-cheer-work"));
      };
    });

    root.querySelectorAll("[data-wassoc]").forEach((b) => {
      b.onclick = () => {
        UI.workAssoc = b.getAttribute("data-wassoc");
        renderMain();
      };
    });
    root.querySelectorAll("[data-wsort]").forEach((b) => {
      b.onclick = () => {
        UI.workSort = b.getAttribute("data-wsort");
        renderMain();
      };
    });

    const clearChip = root.querySelector("#clear-work-asset-filter");
    if (clearChip) {
      clearChip.onclick = () => {
        UI.workFilterAsset = "";
        syncUrl();
        renderMain();
      };
    }
    const clearAuthorChip = root.querySelector("#clear-work-author-filter");
    if (clearAuthorChip) {
      clearAuthorChip.onclick = () => {
        UI.workFilterAuthor = "";
        syncUrl();
        renderMain();
      };
    }

    const wSearch = root.querySelector("#works-search-input");
    wSearch.oninput = (e) => {
      UI.workQuery = e.target.value;
      renderMain();
      const next = document.getElementById("works-search-input");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    };
    root.querySelectorAll("[data-like-work]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const wid = b.getAttribute("data-like-work");
        const w = allWorks.find((x) => x.id === wid);
        if (w) S.toggleLike("work", wid, w.title);
      };
    });
    root.querySelectorAll("[data-fav-work]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const wid = b.getAttribute("data-fav-work");
        const w = allWorks.find((x) => x.id === wid);
        if (w) S.toggleCollect("works", wid, w.title);
      };
    });
    root.querySelectorAll("[data-comment-work]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        openWorkLightbox(b.getAttribute("data-comment-work"), 0, true);
      };
    });
    root.querySelectorAll("[data-pill-asset]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openAssetDrawer(el.getAttribute("data-pill-asset"));
      };
    });
    root.querySelectorAll("[data-open-work]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openWorkLightbox(el.getAttribute("data-open-work"));
      };
    });
    root.querySelectorAll("[data-work-mod-op]").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const wid = btn.getAttribute("data-work-id");
        const action = btn.getAttribute("data-work-mod-op");
        if (action === "delete") {
          if (!confirm("确定要删除这件作品吗？此操作不可撤销。")) return;
        }
        try {
          const res = await S.apiJson(`/api/works/${wid}/moderate`, {
            method: "POST",
            body: { action }
          });
          if (!res.ok) throw new Error(res.error || "操作失败");
          await S.refreshFromServer();
          S.toast(action === "delete" ? "作品已成功删除" : "作品状态已更新！", "success");
          renderMain();
        } catch (err) {
          S.toast("操作失败：" + (err.message || err), "error");
        }
      };
    });
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
                    <div class="hw-creator-avatar-lg ${esc(c.honor.sealClass)}">${esc(c.avatarChar)}</div>
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
                    <span class="hw-creator-avatar-md ${esc(c.honor.sealClass)}" style="cursor:pointer;" data-open-creator="${esc(c.username)}">${esc(c.avatarChar)}</span>
                    <div>
                      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        <strong style="font-size:14px;cursor:pointer;" data-open-creator="${esc(c.username)}">${esc(c.authorName)}${isMe ? " (我)" : ""}</strong>
                        <span class="hw-honor-badge ${esc(c.honor.sealClass)}">${esc(c.honor.badge)}</span>
                        <span class="hw-boost-pill">${esc(c.honor.boostText)}</span>
                      </div>
                      <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">
                        ${esc(pMeta.shortPrefix)}画风 ${pStylesCnt} · 图型 ${pLayoutsCnt} · 实测作品 ${pWorksCnt}${
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
                      <span class="hw-creator-avatar-sm ${esc(prof.honor.sealClass)}">${esc(prof.avatarChar)}</span>
                      <span>${esc(w.authorName)}</span>
                      <span class="hw-honor-badge ${esc(prof.honor.sealClass)}" style="font-size:10px;padding:1px 5px;">${esc(prof.honor.shortBadge)}</span>
                    </button>
                    <button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-work="${esc(w.id)}">
                      👏 鼓励 ${w.cheers || 12}
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
                      👏 鼓励冲榜 (${w.cheers || 12})
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
          <span style="font-size:12.8px;font-weight:750;color:var(--ink-body);">📊 按「${esc(pMeta.fullLabel)}」内的同款实测作品驱动数与新共创热度排定</span>
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
                ? `累计驱动 <strong>${entry.totalWorkCnt}</strong> 件实测作品`
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
                        ? `<button type="button" class="hw-cheer-btn ${cheered ? "is-cheered" : ""}" data-cheer-asset="${esc(a.id)}">👏 鼓励 ${a.cheers || 16}</button>`
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
            默认展示<strong>「📅 周榜」</strong>（仅统计近 7 天新发布内容，不叠加历史殿堂曝光倍率），让每一位本周认真晒图与贡献配方的创作者都能冲上榜首，告别熟面孔长期霸榜！
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
        openAssetDrawer(el.getAttribute("data-open-asset"));
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
    const allWorks = App.state.works || [];
    const curIdx = allWorks.findIndex((w) => w.id === UI.activeWorkId);
    const work = curIdx >= 0 ? allWorks[curIdx] : null;

    if (!work) {
      root.innerHTML = `
        <div class="hw-detail-page" id="standalone-work-detail-page">
          <div class="hw-subpage-bar">
            <button type="button" class="btn btn-sm" id="work-missing-back">← 返回实测作品广场</button>
          </div>
          <div class="hw-detail-section-card" style="text-align:center;padding:48px 24px;">
            <h2 style="margin:0 0 8px;">未找到对应的作品详情</h2>
            <p style="color:var(--ink-muted);margin:0 0 18px;">该作品可能尚未公开展示或链接参数有误。</p>
            <button type="button" class="btn btn-primary" id="work-missing-go-works">浏览全部实测作品</button>
          </div>
        </div>
      `;
      root.querySelector("#work-missing-back").onclick = () => navigateBack("works");
      root.querySelector("#work-missing-go-works").onclick = () => switchView("works");
      return;
    }

    const prevWork = curIdx > 0 ? allWorks[curIdx - 1] : null;
    const nextWork = curIdx >= 0 && curIdx < allWorks.length - 1 ? allWorks[curIdx + 1] : null;
    const imgIndex = Math.max(0, Math.min((work.images || []).length - 1, Number(UI.activeWorkImgIdx) || 0));

    const liked = S.isLiked("work", work.id);
    const likeCnt = S.getLikeCount("work", work);
    const collected = S.isCollected("works", work.id);
    const favCnt = S.getFavoriteCount("works", work);
    const unlocked = S.isUnlocked(work.id, work);
    const cheered = S.isCheered(work.id);
    const authorProf = S.getCreatorProfile(work.author);
    const hasS = work.styles && work.styles.length > 0;
    const hasL = Boolean(work.layout);
    const comments = work.comments || [];
    const canDelWork = S.canDeleteWork ? S.canDeleteWork(work) : (App.state.loggedIn && App.state.user && work.author === App.state.user.username);
    const canModWork = S.canModerateWork ? S.canModerateWork(work) : false;
    const isWorkAuthor = Boolean(App.state.loggedIn && App.state.user && work.author === App.state.user.username);

    const backLabel =
      UI.lastPrimaryView === "styles"
        ? "画风视觉库"
        : UI.lastPrimaryView === "layouts"
        ? "图型结构库"
        : "实测作品广场";

    const mountedAssetsHtml =
      hasS || hasL
        ? `
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            ${(work.styles || [])
              .map((sid) => {
                const st = App.resourceMap.get(sid);
                return `<button type="button" class="hw-recipe-pill" data-lb-asset="${esc(sid)}">🎨 #${esc(sid)} ${esc(st ? st.name : "")}</button>`;
              })
              .join("")}
            ${
              work.layout
                ? (() => {
                    const ly = App.resourceMap.get(work.layout);
                    return `<button type="button" class="hw-recipe-pill is-layout" data-lb-asset="${esc(work.layout)}">📐 ${esc(work.layout)} ${esc(ly ? ly.name : "")}</button>`;
                  })()
                : ""
            }
          </div>
        `
        : `<div style="font-size:12.5px;color:var(--jade);font-weight:700;">🌿 自由创作作品（未绑定特定画风或图型编号，直接以纯提示词驱动）</div>`;

    const promptHtml = unlocked
      ? `
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;gap:8px;flex-wrap:wrap;">
            <span style="font-size:12.5px;font-weight:750;color:var(--ink-muted);">📜 完整生图提示词配方（支持复制或一键带入创作台）</span>
            <button type="button" class="btn btn-sm" id="lb-btn-copy-prompt">📋 复制完整提示词</button>
          </div>
          <div class="hw-prompt-box">${esc(work.prompt)}</div>
        </div>
      `
      : `
        <div style="background:var(--vermilion-wash);border:1.5px dashed var(--vermilion-border);border-radius:10px;padding:16px;text-align:center;">
          <div style="font-weight:800;color:var(--vermilion);margin-bottom:6px;">💎 创作者精品配方（需 ${work.price} 积分解锁）</div>
          <p style="margin:0 0 12px;font-size:12.8px;color:var(--ink-body);">
            预览摘要：${esc((work.prompt || "").slice(0, 42))}……（含完整微排版约束与避坑参数，80% 积分直达作者 @${esc(work.authorName)}）
          </p>
          <button type="button" class="btn btn-primary" id="lb-btn-unlock-work">
            🔓 花费 ${work.price} 积分解锁完整提示词与一键同款
          </button>
        </div>
      `;

    const inlineDrawerHtml =
      UI.workInlineDrawer === "share"
        ? S.renderInlineSharePanelHtml("work", work)
        : UI.workInlineDrawer === "report"
        ? S.renderInlineReportPanelHtml("work", work.id, work.title)
        : "";

    const relatedWorks = allWorks
      .filter((rw) => {
        if (rw.id === work.id) return false;
        if (work.layout && rw.layout === work.layout) return true;
        if (hasS && (rw.styles || []).some((s) => work.styles.includes(s))) return true;
        return rw.author === work.author;
      })
      .slice(0, 5);
    const fallbackRelated =
      relatedWorks.length >= 3
        ? relatedWorks
        : [
            ...relatedWorks,
            ...allWorks.filter((rw) => rw.id !== work.id && !relatedWorks.some((x) => x.id === rw.id))
          ].slice(0, 5);

    root.innerHTML = `
      <div class="hw-detail-page" id="standalone-work-detail-page">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="work-page-back-btn">← 返回${esc(backLabel)}</button>
            <span>/</span>
            <button type="button" class="hw-pill" id="work-crumb-works" style="padding:2px 9px;font-size:11.8px;">🖼️ 实测作品广场</button>
            <span>/</span>
            <strong>${esc(work.title)}</strong>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-sm" id="work-page-prev" ${prevWork ? "" : "disabled"} title="${esc(prevWork ? prevWork.title : "已是第一件")}">◀ 上一件</button>
            <button type="button" class="btn btn-sm" id="work-page-next" ${nextWork ? "" : "disabled"} title="${esc(nextWork ? nextWork.title : "已是最后一件")}">下一件 ▶</button>
          </div>
        </div>

        <div class="hw-detail-grid">
          <div class="hw-detail-stage-wrap">
            <div class="hw-detail-stage">
              <img class="main-stage-img" src="${esc(work.images[imgIndex] || work.images[0])}" alt="${esc(work.title)}" />
              ${
                work.images.length > 1
                  ? `<div class="hw-thumb-strip">
                      ${work.images
                        .map(
                          (u, idx) =>
                            `<img data-hw-src="${esc(u)}" class="${idx === imgIndex ? "is-active" : ""}" data-lb-thumb="${idx}" alt="P${idx + 1}" />`
                        )
                        .join("")}
                    </div>`
                  : ""
              }
            </div>

            <!-- Warm Encouragement Stamp Bar -->
            <div class="hw-stamp-bar">
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <button type="button" class="hw-stamp-btn ${cheered ? "is-active" : ""}" id="lb-btn-cheer-main">
                  👏 鼓励支持 (${work.cheers || 12})
                </button>
                <button type="button" class="hw-stamp-btn ${S.isCheered(work.id, "惊艳神图") ? "is-active" : ""}" data-lb-stamp="惊艳神图">🔥 惊艳神图 (${S.getStampCount(work, "惊艳神图")})</button>
                <button type="button" class="hw-stamp-btn ${S.isCheered(work.id, "配方超稳") ? "is-active" : ""}" data-lb-stamp="配方超稳">🎯 配方超稳 (${S.getStampCount(work, "配方超稳")})</button>
                <button type="button" class="hw-stamp-btn ${S.isCheered(work.id, "构图绝妙") ? "is-active" : ""}" data-lb-stamp="构图绝妙">💡 构图绝妙 (${S.getStampCount(work, "构图绝妙")})</button>
                <button type="button" class="btn btn-sm btn-gold" id="lb-btn-tip-author" style="margin-left:auto;">
                  🎁 赞赏 +2✦ 鼓励作者
                </button>
              </div>
            </div>
          </div>

          <div class="hw-detail-meta-card">
            ${
              canModWork
                ? `
                  <div id="work-mod-toolbar" style="background:rgba(31,95,139,0.08);border:1px solid rgba(31,95,139,0.28);border-radius:12px;padding:10px 14px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span style="font-size:12.8px;font-weight:850;color:#1f5f8b;">🛡️ 前台运审管理工具条</span>
                    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                      <button type="button" class="btn btn-sm" data-work-mod-op="${work.featured ? "unfeature" : "feature"}">${work.featured ? "取消精选" : "🌟 设为精选"}</button>
                      <button type="button" class="btn btn-sm" data-work-mod-op="boost_new">🚀 72h 首发提权</button>
                      <button type="button" class="btn btn-sm" data-work-mod-op="${work.status === "paused" ? "publish" : "pause"}">${work.status === "paused" ? "▶️ 恢复上架" : "⏸️ 暂存下架"}</button>
                      <button type="button" class="btn btn-sm" data-work-mod-op="hide">🙈 违规隐藏</button>
                      <button type="button" class="btn btn-sm" id="work-mod-edit-btn">✏️ 编辑作品</button>
                      <button type="button" class="btn btn-sm" data-work-mod-op="delete" style="color:var(--vermilion);font-weight:750;">🗑️ 删除作品</button>
                    </div>
                  </div>
                `
                : ""
            }
            <div>
              <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px;">
                <span class="hw-card-code">🖼️ 社区实测生图配方</span>
                <span style="font-size:12px;color:var(--ink-muted);">${esc(work.createdAt)} · 画幅 ${esc(work.ratio || "3:4")}</span>
              </div>
              <h1 class="hw-detail-title">${esc(work.title)}</h1>
            </div>

            <!-- Creator Honor Card (links to standalone Personal Homepage) -->
            <div style="background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:12px;padding:11px 14px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
              <button type="button" class="hw-author-chip" id="lb-open-author">
                <span class="hw-creator-avatar-sm ${esc(authorProf.honor.sealClass)}">${esc(authorProf.avatarChar)}</span>
                <strong style="font-size:13.8px;color:var(--ink-strong);">@${esc(work.authorName)}</strong>
                <span class="hw-honor-badge ${esc(authorProf.honor.sealClass)}">${esc(authorProf.honor.badge)}</span>
                <span class="hw-boost-pill">${esc(authorProf.honor.boostText)}</span>
              </button>
              <button type="button" class="btn btn-sm" id="lb-visit-profile-btn">🏠 访问个人主页 (${authorProf.totalPublished}) ↗</button>
            </div>

            <div>
              <div style="font-size:12px;font-weight:750;color:var(--ink-muted);margin-bottom:6px;">挂载的画风与图型资产（点击进入对应独立详情评论页）：</div>
              ${mountedAssetsHtml}
            </div>

            ${work.notes ? `<div style="background:var(--paper-inset);padding:11px 13px;border-radius:9px;font-size:13.2px;color:var(--ink-body);line-height:1.6;">💡 <strong>作者实测笔记：</strong>${esc(work.notes)}</div>` : ""}

            ${promptHtml}

            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding-top:4px;border-top:1px solid var(--line-soft);">
              ${
                unlocked
                  ? `<a class="btn btn-primary" href="${esc(channelUrl("studio", { fork: work.id }))}">⚡ 一键带入无限画布复刻 (${work.forks || 0}) ↗</a>`
                  : ""
              }
              <button type="button" class="btn ${liked ? "btn-primary" : ""}" id="lb-btn-like">
                👍 ${liked ? "已赞" : "点赞"} (${likeCnt})
              </button>
              <button type="button" class="btn ${collected ? "btn-primary" : ""}" id="lb-btn-collect">
                ${collected ? "♥ 已收藏" : "♡ 收藏"} (${favCnt})
              </button>
              <button type="button" class="btn" id="lb-btn-scroll-comments">
                💬 评论交流 (${comments.length})
              </button>
              <button type="button" class="btn" id="lb-btn-forum-post">
                📑 作为卡片分享到论坛 ↗
              </button>
              <button type="button" class="btn btn-gold ${UI.workInlineDrawer === "share" ? "btn-primary" : ""}" id="lb-btn-share">
                📤 分享赚积分
              </button>
              <button type="button" class="btn btn-sm ${UI.workInlineDrawer === "report" ? "btn-primary" : ""}" id="lb-btn-report" title="举报内容不实或违规">
                🚩 举报
              </button>
              ${isWorkAuthor && !canModWork ? `<button type="button" class="btn btn-sm" id="work-page-author-delete" style="color:var(--vermilion);" title="删除我的这件作品">🗑️ 删除我的作品</button>` : ""}
            </div>

            ${inlineDrawerHtml}
          </div>
        </div>

        <!-- Full-Width Dedicated Work Comments & Replication Feedback Section -->
        <section class="hw-detail-section-card" id="work-comments-section">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
            <div>
              <h2 style="margin:0;font-size:18px;font-family:var(--font-serif);">💬 作品评论与复刻交流区 (${comments.length})</h2>
              <div style="font-size:12.4px;color:var(--ink-muted);margin-top:3px;">交流复刻提示词参数、字号密度或构图微调技巧，点击评论者昵称可直达其独立个人主页。</div>
            </div>
            <span class="hw-boost-pill">友善评论与鼓励计入创作者荣誉加权</span>
          </div>

          <div class="hw-comments-composer">
            <textarea class="hw-textarea" rows="2" id="lb-comment-input" placeholder="写下你对《${esc(work.title)}》的赏析、参数提问或复刻反馈（Ctrl + Enter 快捷发送）…" style="flex:1;"></textarea>
            <button type="button" class="btn btn-primary" id="lb-comment-send" style="align-self:flex-end;">💬 发表评论</button>
          </div>

          <div class="hw-comments-list" style="margin-top:14px;">
            ${
              comments.length === 0
                ? `<div style="padding:26px;text-align:center;color:var(--ink-muted);background:var(--paper-bg);border-radius:10px;">沙发虚位以待～写一句鼓励或复刻心得，让创作者更有动力吧！</div>`
                : comments
                    .map(
                      (c, idx) => `
                        <div class="hw-comment-item">
                          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px;">
                            <div style="display:flex;align-items:center;gap:8px;">
                              <button type="button" class="hw-author-chip" data-comment-user="${esc(c.user || c.name || "yang0")}" style="padding:2px 8px;">
                                <strong style="font-size:13px;color:var(--ink-strong);">@${esc(c.name || c.user || "画友")}</strong>
                              </button>
                              <span style="color:var(--ink-faint);font-size:11.8px;">${esc(c.time || "刚刚")}</span>
                            </div>
                            <div style="display:flex;gap:6px;align-items:center;">
                              ${canModWork ? `<button type="button" class="btn btn-sm" data-hide-work-comment="${esc(c.id || idx)}" style="font-size:11px;padding:1px 6px;color:var(--ink-muted);">🙈 隐藏</button>` : ""}
                              ${(S.canDeleteComment ? S.canDeleteComment(c) : (App.state.loggedIn && (c.user === App.state.user.username || canModWork))) ? `<button type="button" class="btn btn-sm" data-del-work-comment="${esc(c.id || idx)}" style="font-size:11px;padding:1px 6px;color:var(--vermilion);">🗑️ 删除</button>` : ""}
                              <span class="hw-comment-floor">#${idx + 1}楼</span>
                            </div>
                          </div>
                          <div style="font-size:13.8px;color:var(--ink-body);line-height:1.65;white-space:pre-wrap;">${esc(c.text)}</div>
                        </div>
                      `
                    )
                    .join("")
            }
          </div>
        </section>

        ${
          fallbackRelated.length
            ? `
              <section class="hw-detail-section-card">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
                  <h2 style="margin:0;font-size:17.5px;font-family:var(--font-serif);">✨ 相关同款与推荐实测作品</h2>
                  <button type="button" class="btn btn-sm" id="work-more-square-btn">去作品广场探索更多 →</button>
                </div>
                ${S.renderMasonry(
                  fallbackRelated.map(
                    (rw) => `
                      <article class="hw-card" data-rel-work="${esc(rw.id)}" style="cursor:pointer;">
                        <div class="hw-card-media">
                          <img data-hw-src="${esc(rw.images[0])}" alt="${esc(rw.title)}" loading="lazy" />
                        </div>
                        <div class="hw-card-body">
                          <h3 class="hw-card-title">${esc(rw.title)}</h3>
                          <div style="font-size:12px;color:var(--ink-muted);display:flex;justify-content:space-between;">
                            <span>@${esc(rw.authorName)}</span>
                            <span>👏 ${rw.cheers || 12} · 💬 ${(rw.comments || []).length}</span>
                          </div>
                        </div>
                      </article>
                    `
                  ),
                  "standard"
                )}
              </section>
            `
            : ""
        }
      </div>
    `;

    root.querySelector("#work-page-back-btn").onclick = () => navigateBack(UI.lastPrimaryView || "works");
    root.querySelector("#work-crumb-works").onclick = () => switchView("works");
    if (prevWork) {
      root.querySelector("#work-page-prev").onclick = () => openWorkPage(prevWork.id, 0, false);
    }
    if (nextWork) {
      root.querySelector("#work-page-next").onclick = () => openWorkPage(nextWork.id, 0, false);
    }

    root.querySelector("#lb-open-author").onclick = () => openProfilePage(authorProf.username, "works");
    root.querySelector("#lb-visit-profile-btn").onclick = () => openProfilePage(authorProf.username, "works");

    root.querySelector("#lb-btn-cheer-main").onclick = () => {
      S.toggleCheerItem("work", work.id);
    };
    root.querySelectorAll("[data-lb-stamp]").forEach((sb) => {
      sb.onclick = () => {
        S.toggleCheerItem("work", work.id, sb.getAttribute("data-lb-stamp"));
      };
    });
    root.querySelector("#lb-btn-tip-author").onclick = () => {
      S.sendEncourageTip("work", work.id, 2);
    };

    root.querySelectorAll("[data-lb-thumb]").forEach((t) => {
      t.onclick = () => {
        UI.activeWorkImgIdx = Number(t.getAttribute("data-lb-thumb")) || 0;
        renderMain();
      };
    });
    root.querySelectorAll("[data-lb-asset]").forEach((b) => {
      b.onclick = () => openAssetPage(b.getAttribute("data-lb-asset"));
    });

    const copyBtn = root.querySelector("#lb-btn-copy-prompt");
    if (copyBtn) {
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(work.prompt);
        } catch (_) {}
        toast("📋 完整生图提示词已复制！");
      };
    }

    const unlockBtn = root.querySelector("#lb-btn-unlock-work");
    if (unlockBtn) {
      unlockBtn.onclick = () => {
        S.unlockWithCredits(work.id, work.price, work.title, work.authorName, () => renderMain());
      };
    }

    root.querySelector("#lb-btn-like").onclick = () => {
      S.toggleLike("work", work.id, work.title);
    };
    root.querySelector("#lb-btn-collect").onclick = () => {
      S.toggleCollect("works", work.id, work.title);
    };
    root.querySelector("#lb-btn-scroll-comments").onclick = () => {
      const sec = root.querySelector("#work-comments-section");
      if (sec) sec.scrollIntoView({ behavior: "smooth", block: "start" });
      const inp = root.querySelector("#lb-comment-input");
      if (inp) setTimeout(() => inp.focus(), 180);
    };
    root.querySelector("#lb-btn-forum-post").onclick = () =>
      S.goToForumCompose({
        category: "tuning",
        topicTitle: `围绕作品《${work.title}》的复刻与调优讨论`,
        images: work.images || [],
        sharedCard: {
          kind: "work",
          id: work.id,
          title: work.title,
          image: (work.images && work.images[0]) || "",
          authorName: work.authorName || work.author || "",
          desc: work.notes || work.prompt || ""
        }
      });

    root.querySelector("#lb-btn-share").onclick = () => {
      UI.workInlineDrawer = UI.workInlineDrawer === "share" ? "" : "share";
      renderMain();
    };
    root.querySelector("#lb-btn-report").onclick = () => {
      if (!App.state.loggedIn) {
        openAuthPage("登录后即可参与社区内容自治举报反馈", () => {
          UI.workInlineDrawer = "report";
        });
        return;
      }
      UI.workInlineDrawer = UI.workInlineDrawer === "report" ? "" : "report";
      renderMain();
    };

    if (UI.workInlineDrawer === "share") {
      S.bindInlineSharePanel(root, "work", work, () => {
        UI.workInlineDrawer = "";
        renderMain();
      });
    } else if (UI.workInlineDrawer === "report") {
      S.bindInlineReportPanel(root, "work", work.id, () => {
        UI.workInlineDrawer = "";
        renderMain();
      });
    }

    root.querySelectorAll("[data-comment-user]").forEach((btn) => {
      btn.onclick = () => {
        const u = btn.getAttribute("data-comment-user");
        if (u) openProfilePage(u, "works");
      };
    });

    root.querySelectorAll("[data-rel-work]").forEach((card) => {
      card.onclick = () => openWorkPage(card.getAttribute("data-rel-work"), 0, false);
    });
    const moreBtn = root.querySelector("#work-more-square-btn");
    if (moreBtn) moreBtn.onclick = () => switchView("works");

    const lbInp = root.querySelector("#lb-comment-input");
    if (UI.workFocusComment && lbInp) {
      UI.workFocusComment = false;
      setTimeout(() => {
        const sec = root.querySelector("#work-comments-section");
        if (sec) sec.scrollIntoView({ behavior: "smooth", block: "center" });
        lbInp.focus();
      }, 60);
    }

    const submitWorkComment = async () => {
      if (!App.state.loggedIn) {
        openAuthPage("登录后即可发表作品交流与鼓励留言！", () => openWorkPage(work.id, imgIndex, true));
        return;
      }
      const txt = lbInp.value.trim();
      if (!txt) {
        toast("请输入评论内容");
        return;
      }
      if (App.state.serverBacked) {
        try {
          const res = await S.apiJson(`/api/works/${encodeURIComponent(work.id)}/comments`, {
            method: "POST",
            body: { text: txt }
          });
          work.comments = work.comments || [];
          if (res.comment) work.comments.push(res.comment);
          toast("💬 作品评论已发布！");
          await S.refreshFromServer();
        } catch (err) {
          toast(`评论失败：${err.message}`);
        }
        return;
      }
      work.comments = work.comments || [];
      work.comments.push({
        id: "c_" + Date.now(),
        user: App.state.user.username,
        name: App.state.user.name,
        text: txt,
        time: "刚刚"
      });
      S.saveState();
      toast("💬 作品评论已发布！");
    };

    root.querySelector("#lb-comment-send").onclick = submitWorkComment;
    if (lbInp) {
      lbInp.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          submitWorkComment();
        }
      });
    }

    // Wire Front-Stage Work Moderation Toolbar
    root.querySelectorAll("#work-mod-toolbar [data-work-mod-op]").forEach((btn) => {
      btn.onclick = async () => {
        const op = btn.getAttribute("data-work-mod-op");
        if (!op) return;
        if (op === "delete") {
          if (!confirm(`确定要彻底删除作品《${work.title}》吗？此操作不可逆。`)) return;
        }
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/works/${encodeURIComponent(work.id)}/moderate`, {
              method: "POST",
              body: { action: op }
            });
          }
          if (op === "delete") {
            toast(`🗑️ 作品《${work.title}》已成功删除`);
            await S.refreshFromServer();
            switchView("works");
          } else {
            toast(`✅ 作品管理操作 [${op}] 已执行！`);
            await S.refreshFromServer();
            renderMain();
          }
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
      };
    });

    // Wire Work Author Delete Button
    const authorDelBtn = root.querySelector("#work-page-author-delete");
    if (authorDelBtn) {
      authorDelBtn.onclick = async () => {
        if (!confirm(`确定要删除您的作品《${work.title}》吗？删除后不可恢复。`)) return;
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/works/${encodeURIComponent(work.id)}/delete`, {
              method: "POST",
              body: {}
            });
          }
          toast("🗑️ 您的作品已成功删除！");
          await S.refreshFromServer();
          switchView("works");
        } catch (err) {
          toast(`删除作品失败：${err.message}`);
        }
      };
    }

    // Wire Work Edit Button
    const editModBtn = root.querySelector("#work-mod-edit-btn");
    if (editModBtn) {
      editModBtn.onclick = async () => {
        const nextTitle = prompt("修改作品标题：", work.title);
        if (nextTitle === null) return;
        const newTitle = nextTitle.trim() || work.title;
        const nextPriceStr = prompt("修改提示词查看积分（0 表示公开免费）：", String(work.price || 0));
        const newPrice = nextPriceStr !== null ? Math.max(0, parseInt(nextPriceStr, 10) || 0) : work.price;
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/works/${encodeURIComponent(work.id)}/moderate`, {
              method: "POST",
              body: { action: "edit", title: newTitle, price: newPrice }
            });
          }
          toast("✅ 作品信息已更新！");
          await S.refreshFromServer();
          renderMain();
        } catch (err) {
          toast(`更新失败：${err.message}`);
        }
      };
    }

    // Wire Work Comments Moderate (Delete / Hide)
    root.querySelectorAll("[data-del-work-comment]").forEach((btn) => {
      btn.onclick = async () => {
        const cid = btn.getAttribute("data-del-work-comment");
        if (!confirm("确定要删除此条作品评论吗？")) return;
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/comments/moderate`, {
              method: "POST",
              body: { commentType: "work_comment", id: cid, workId: work.id, action: "delete" }
            });
          }
          toast("🗑️ 评论已删除！");
          await S.refreshFromServer();
          renderMain();
        } catch (err) {
          toast(`删除评论失败：${err.message}`);
        }
      };
    });
    root.querySelectorAll("[data-hide-work-comment]").forEach((btn) => {
      btn.onclick = async () => {
        const cid = btn.getAttribute("data-hide-work-comment");
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/comments/moderate`, {
              method: "POST",
              body: { commentType: "work_comment", id: cid, workId: work.id, action: "hide" }
            });
          }
          toast("🙈 评论已隐藏！");
          await S.refreshFromServer();
          renderMain();
        } catch (err) {
          toast(`操作失败：${err.message}`);
        }
      };
    });
  }

  /* ======================== STANDALONE CREATOR PERSONAL HOMEPAGE & ACCOUNT CENTER (?view=profile) ======================== */
  function renderCreatorProfilePage(root) {
    const fallbackUser = App.state.loggedIn && App.state.user ? App.state.user.username : "";
    const targetUser = (UI.profileUser || fallbackUser || "").trim();

    if (!targetUser || targetUser === "guest") {
      openAuthPage("登录后即可访问与管理你的独立个人主页");
      return;
    }

    const prof = S.getCreatorProfile(targetUser);
    const isMe = Boolean(App.state.loggedIn && App.state.user && App.state.user.username === prof.username);
    if (!isMe && ["collections", "account"].includes(UI.profileTab)) {
      UI.profileTab = "works";
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
      `${prof.honor.desc} · 已在社区累计贡献 ${prof.works.length} 件实测作品与 ${prof.styles.length + prof.layouts.length} 项画风/图型资产。`;

    let tabBodyHtml = "";
    if (UI.profileTab === "works") {
      tabBodyHtml = prof.works.length
        ? S.renderMasonry(
            prof.works.map(
              (w) => `
                <article class="hw-card" data-prof-work="${esc(w.id)}" style="cursor:pointer;">
                  <div class="hw-card-media">
                    <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" loading="lazy" />
                    ${w.price > 0 ? `<span class="hw-card-badge-tl badge-exclusive-pro">💎 ${w.price}✦</span>` : ""}
                  </div>
                  <div class="hw-card-body">
                    <h3 class="hw-card-title">${esc(w.title)}</h3>
                    <div style="font-size:12px;color:var(--ink-muted);display:flex;justify-content:space-between;align-items:center;">
                      <span>${esc(w.createdAt || "近期")}</span>
                      <span>👏 ${w.cheers || 12} · 💬 ${(w.comments || []).length}</span>
                    </div>
                  </div>
                </article>
              `
            ),
            "standard"
          )
        : `<div class="hw-detail-section-card" style="text-align:center;padding:42px 20px;color:var(--ink-muted);">
            暂未发布实测作品。${isMe ? `去 <a href="${esc(channelUrl("studio"))}" style="color:var(--vermilion);font-weight:800;">无限画布创作台 ↗</a> 生成并晒出第一幅作品吧！` : ""}
          </div>`;
    } else if (UI.profileTab === "assets") {
      const assets = [...prof.styles, ...prof.layouts];
      tabBodyHtml = assets.length
        ? S.renderMasonry(
            assets.map(
              (it) => `
                <article class="hw-card" data-prof-asset="${esc(it.id)}" style="cursor:pointer;">
                  <div class="hw-card-media">
                    <span class="hw-card-badge-tl badge-community">✨ 共创${it.kind === "layout" ? "图型" : "画风"}</span>
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
              `
            ),
            "standard"
          )
        : `<div class="hw-detail-section-card" style="text-align:center;padding:42px 20px;color:var(--ink-muted);">暂未发布共创画风或图型资产。</div>`;
    } else if (UI.profileTab === "topics") {
      tabBodyHtml = prof.topics.length
        ? `<div style="display:grid;gap:12px;">
            ${prof.topics
              .map(
                (t) => `
                  <article class="forum-topic-card" data-prof-topic="${esc(t.id)}" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;">
                    <div style="flex:1;min-width:240px;">
                      <div style="display:flex;gap:6px;align-items:center;margin-bottom:5px;flex-wrap:wrap;">
                        <span class="hw-card-code">${esc(t.categoryLabel || "社区讨论")}</span>
                        ${t.pinned ? `<span class="hw-boost-pill">📌 置顶</span>` : ""}
                        ${t.featured ? `<span class="hw-honor-badge seal-master">🌟 精华</span>` : ""}
                      </div>
                      <h3 style="margin:0 0 6px;font-size:16px;">${esc(t.title)}</h3>
                      <div style="font-size:12.5px;color:var(--ink-muted);">${esc((t.body || "").slice(0, 90))}…</div>
                    </div>
                    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;font-size:12.5px;color:var(--ink-muted);">
                      <span>👍 ${S.getLikeCount("topic", t)} · 💬 ${(t.replies || []).length} 回复</span>
                      <span class="btn btn-sm btn-primary">阅读全文与楼层 ↗</span>
                    </div>
                  </article>
                `
              )
              .join("")}
          </div>`
        : `<div class="hw-detail-section-card" style="text-align:center;padding:42px 20px;color:var(--ink-muted);">
            暂未发布论坛实战帖。
            ${isMe ? `<div style="margin-top:12px;"><button type="button" class="btn btn-primary" id="prof-empty-compose-btn">✏️ 去发布第一篇图文论坛帖</button></div>` : ""}
          </div>`;
    } else if (UI.profileTab === "collections" && isMe) {
      const cols = App.state.collections || { styles: [], layouts: [], works: [], topics: [] };
      const subItems =
        UI.favTab === "styles" || UI.favTab === "layouts"
          ? (cols[UI.favTab] || []).map((id) => App.resourceMap.get(id)).filter(Boolean)
          : UI.favTab === "works"
          ? (cols.works || []).map((id) => (App.state.works || []).find((w) => w.id === id)).filter(Boolean)
          : (cols.topics || []).map((id) => (App.state.topics || []).find((t) => t.id === id)).filter(Boolean);

      tabBodyHtml = `
        <div class="hw-detail-section-card">
          <div class="hw-pills-row" style="margin-bottom:16px;">
            <button type="button" class="hw-pill ${UI.favTab === "styles" ? "is-active" : ""}" data-prof-ftab="styles">🎨 收藏画风 (${(cols.styles || []).length})</button>
            <button type="button" class="hw-pill ${UI.favTab === "layouts" ? "is-active" : ""}" data-prof-ftab="layouts">📐 收藏图型 (${(cols.layouts || []).length})</button>
            <button type="button" class="hw-pill ${UI.favTab === "works" ? "is-active" : ""}" data-prof-ftab="works">🖼️ 收藏作品 (${(cols.works || []).length})</button>
            <button type="button" class="hw-pill ${UI.favTab === "topics" ? "is-active" : ""}" data-prof-ftab="topics">💬 收藏帖子 (${(cols.topics || []).length})</button>
          </div>
          ${
            !subItems.length
              ? `<div style="padding:32px;text-align:center;color:var(--ink-muted);">该分类下暂无收藏项</div>`
              : UI.favTab === "topics"
              ? `<div style="display:grid;gap:10px;">
                  ${subItems
                    .map(
                      (t) => `
                        <div class="forum-topic-card" style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                          <div>
                            <span class="hw-card-code">${esc(t.categoryLabel)}</span>
                            <h3 style="margin:4px 0;font-size:15px;">${esc(t.title)}</h3>
                          </div>
                          <button type="button" class="btn btn-sm btn-primary" data-prof-topic="${esc(t.id)}">阅读帖子 ↗</button>
                        </div>
                      `
                    )
                    .join("")}
                </div>`
              : S.renderMasonry(
                  subItems.map((it) =>
                    UI.favTab === "works"
                      ? `
                        <article class="hw-card" data-prof-work="${esc(it.id)}" style="cursor:pointer;">
                          <div class="hw-card-media"><img data-hw-src="${esc(it.images[0])}" alt="${esc(it.title)}" /></div>
                          <div class="hw-card-body"><h3 class="hw-card-title">${esc(it.title)}</h3></div>
                        </article>
                      `
                      : `
                        <article class="hw-card" data-prof-asset="${esc(it.id)}" style="cursor:pointer;">
                          <div class="hw-card-media"><img data-hw-src="${esc(it.image)}" alt="${esc(it.name)}" /></div>
                          <div class="hw-card-body">
                            <div class="hw-card-code">${esc(it.id)}</div>
                            <h3 class="hw-card-title">${esc(it.name)}</h3>
                          </div>
                        </article>
                      `
                  ),
                  "standard"
                )
          }
        </div>
      `;
    } else if (UI.profileTab === "account" && isMe) {
      tabBodyHtml = S.renderAccountSettingsFormHtml();
    }

    root.innerHTML = `
      <div class="hw-profile-page" id="standalone-profile-page">
        <div class="hw-subpage-bar">
          <div class="hw-subpage-crumbs">
            <button type="button" class="btn btn-sm" id="prof-back-btn">← 返回浏览</button>
            <span>/</span>
            <span>🏠 创作者个人主页</span>
            <span>/</span>
            <strong>@${esc(prof.authorName)}</strong>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-sm" id="prof-rankings-btn">🏆 创作者荣誉榜单 ↗</button>
          </div>
        </div>

        <section class="hw-profile-hero">
          <div class="hw-profile-hero-top">
            <div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;flex:1;min-width:260px;">
              <div class="hw-profile-avatar-xl ${esc(prof.honor.sealClass)}">${esc(prof.avatarChar)}</div>
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
                    <button type="button" class="btn ${UI.profileTab === "account" ? "btn-primary" : ""}" id="prof-go-account-btn">⚙️ 账号资料与安全设置</button>
                    <button type="button" class="btn btn-gold" id="prof-go-wallet-btn">✦ 积分钱包 (${App.state.credits}✦)</button>
                    <button type="button" class="btn" id="prof-go-compose-btn">✏️ 发论坛帖</button>
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
              <span>被一键复刻同款</span>
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
        <div class="hw-pills-row">
          <button type="button" class="hw-pill ${UI.profileTab === "works" ? "is-active" : ""}" data-ptab="works">🖼️ 实测作品 (${prof.works.length})</button>
          <button type="button" class="hw-pill ${UI.profileTab === "assets" ? "is-active" : ""}" data-ptab="assets">🎨 共创画风与图型 (${prof.styles.length + prof.layouts.length})</button>
          <button type="button" class="hw-pill ${UI.profileTab === "topics" ? "is-active" : ""}" data-ptab="topics">💬 发布的论坛帖 (${prof.topics.length})</button>
          ${
            isMe
              ? `
                <button type="button" class="hw-pill ${UI.profileTab === "collections" ? "is-active" : ""}" data-ptab="collections">♥ 我的收藏夹</button>
                <button type="button" class="hw-pill ${UI.profileTab === "account" ? "is-active" : ""}" data-ptab="account">⚙️ 账号资料与安全设置</button>
              `
              : ""
          }
        </div>

        <div id="profile-tab-stage">
          ${tabBodyHtml}
        </div>
      </div>
    `;

    root.querySelector("#prof-back-btn").onclick = () => navigateBack(UI.lastPrimaryView || "styles");
    root.querySelector("#prof-rankings-btn").onclick = () => switchView("rankings", { rankTab: "creators" });

    root.querySelectorAll("[data-ptab]").forEach((btn) => {
      btn.onclick = () => {
        openProfilePage(prof.username, btn.getAttribute("data-ptab"));
      };
    });

    const goAccBtn = root.querySelector("#prof-go-account-btn");
    if (goAccBtn) goAccBtn.onclick = () => openProfilePage(prof.username, "account");
    const goWalBtn = root.querySelector("#prof-go-wallet-btn");
    if (goWalBtn) goWalBtn.onclick = () => switchView("wallet");
    const goCompBtn = root.querySelector("#prof-go-compose-btn");
    if (goCompBtn) goCompBtn.onclick = () => S.goToForumCompose();
    const emptyCompBtn = root.querySelector("#prof-empty-compose-btn");
    if (emptyCompBtn) emptyCompBtn.onclick = () => S.goToForumCompose();
    const filterAuthorBtn = root.querySelector("#prof-filter-author-btn");
    if (filterAuthorBtn) filterAuthorBtn.onclick = () => switchView("works", { filterAuthor: prof.username });

    const staffManageBtn = root.querySelector("#prof-staff-manage-btn");
    if (staffManageBtn) staffManageBtn.onclick = () => openFrontUserManageModal(prof.username);
    const staffBannerBtn = root.querySelector("#prof-staff-manage-banner-btn");
    if (staffBannerBtn) staffBannerBtn.onclick = () => openFrontUserManageModal(prof.username);

    root.querySelectorAll("[data-prof-work]").forEach((el) => {
      el.onclick = () => openWorkPage(el.getAttribute("data-prof-work"), 0, false);
    });
    root.querySelectorAll("[data-prof-asset]").forEach((el) => {
      el.onclick = () => openAssetPage(el.getAttribute("data-prof-asset"));
    });
    root.querySelectorAll("[data-prof-topic]").forEach((el) => {
      el.onclick = () => S.goToTopicPage(el.getAttribute("data-prof-topic"));
    });
    root.querySelectorAll("[data-prof-ftab]").forEach((btn) => {
      btn.onclick = () => {
        UI.favTab = btn.getAttribute("data-prof-ftab");
        renderMain();
      };
    });

    if (UI.profileTab === "account" && isMe) {
      S.bindAccountSettingsForm(root, () => renderMain());
    }
  }

  /* ======================== STANDALONE AUTH PASS PAGE (?view=auth) ======================== */
  function restoreAfterAuth(runSuccessCallback = false) {
    const snap = UI.authReturnSnapshot;
    const cb = UI.authOnSuccess;
    UI.authReturnSnapshot = null;
    UI.authOnSuccess = null;
    UI.authReason = "";

    if (snap && snap.view && snap.view !== "auth") {
      App.view = snap.view;
      UI.activeAssetId = snap.activeAssetId || UI.activeAssetId;
      UI.activeWorkId = snap.activeWorkId || UI.activeWorkId;
      UI.profileUser = snap.profileUser || UI.profileUser;
      UI.profileTab = snap.profileTab || UI.profileTab;
    } else {
      App.view = UI.lastPrimaryView || "styles";
    }
    syncUrl(false);
    S.saveState();
    if (runSuccessCallback && typeof cb === "function") {
      cb();
    }
  }

  function renderAuthPage(root) {
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
            <button type="button" class="btn" id="skill-go-wallet-btn">🔑 获取个人资产库同步密钥</button>
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
    root.querySelector("#skill-go-wallet-btn").onclick = () => switchView("wallet");
    root.querySelectorAll("[data-skill-asset]").forEach((card) => {
      card.onclick = () => openAssetPage(card.getAttribute("data-skill-asset"));
    });
  }

  /* ======================== 3. 4-IN-1 COLLECTIONS CENTER ======================== */
  function renderCollectionsCenter(root) {
    if (!App.state.loggedIn) {
      root.innerHTML = `
        <div class="hw-locked-gate-box" style="padding:48px 24px;">
          <div class="hw-locked-icon">♥</div>
          <h2>登录后同步你的跨端四合一收藏夹（画风 · 图型 · 作品 · 帖子）</h2>
          <p style="color:var(--ink-muted);margin-bottom:18px;">在主站收藏的任何画风与图型，都会自动出现在 <code>studio.</code> 在线创作台的置顶快捷栏中！</p>
          <button type="button" class="btn btn-primary" id="fav-login-btn">🔑 立即登录查看收藏夹</button>
        </div>
      `;
      root.querySelector("#fav-login-btn").onclick = () => S.openLoginModal();
      return;
    }

    const cols = App.state.collections;
    let bodyHtml = "";

    if (UI.favTab === "styles" || UI.favTab === "layouts") {
      const ids = cols[UI.favTab] || [];
      const items = ids.map((id) => App.resourceMap.get(id)).filter(Boolean);
      bodyHtml = items.length
        ? S.renderMasonry(
            items.map(
              (item) => `
                <article class="hw-card">
                  <div class="hw-card-media" data-fav-open-asset="${esc(item.id)}">
                    <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" />
                  </div>
                  <div class="hw-card-body">
                    <div class="hw-card-code">${esc(item.id)}</div>
                    <h3 class="hw-card-title" data-fav-open-asset="${esc(item.id)}">${esc(item.name)}</h3>
                    <div class="hw-card-footer">
                      <button type="button" class="btn btn-sm" data-unfav="${esc(item.id)}">移除</button>
                      <a class="btn btn-sm btn-primary" href="${esc(channelUrl("studio", item.kind === "style" ? { style: item.id } : { layout: item.id }))}">去创作 ↗</a>
                    </div>
                  </div>
                </article>
              `
            ),
            "standard"
          )
        : `<div style="padding:40px;text-align:center;color:var(--ink-muted);">暂未收藏该类资产，去库里点亮 ♡ 吧！</div>`;
    } else if (UI.favTab === "works") {
      const items = (cols.works || []).map((id) => App.state.works.find((w) => w.id === id)).filter(Boolean);
      bodyHtml = items.length
        ? S.renderMasonry(
            items.map(
              (w) => `
                <article class="hw-card">
                  <div class="hw-card-media" data-fav-open-work="${esc(w.id)}">
                    <img data-hw-src="${esc(w.images[0])}" alt="${esc(w.title)}" />
                  </div>
                  <div class="hw-card-body">
                    <h3 class="hw-card-title" data-fav-open-work="${esc(w.id)}">${esc(w.title)}</h3>
                    <div class="hw-card-footer">
                      <button type="button" class="btn btn-sm" data-unfav="${esc(w.id)}">移除</button>
                      <a class="btn btn-sm btn-primary" href="${esc(channelUrl("studio", { fork: w.id }))}">复刻同款 ↗</a>
                    </div>
                  </div>
                </article>
              `
            ),
            "standard"
          )
        : `<div style="padding:40px;text-align:center;color:var(--ink-muted);">暂未收藏实测作品</div>`;
    } else {
      const items = (cols.topics || []).map((id) => App.state.topics.find((t) => t.id === id)).filter(Boolean);
      bodyHtml = items.length
        ? `<div style="display:grid;gap:10px;">
            ${items
              .map(
                (t) => `
                  <div class="forum-topic-card" style="display:flex;justify-content:space-between;align-items:center;gap:14px;">
                    <div>
                      <span class="hw-card-code">${esc(t.categoryLabel)}</span>
                      <h3 style="margin:4px 0;font-size:15.5px;">${esc(t.title)}</h3>
                      <div style="font-size:12.5px;color:var(--ink-muted);">@${esc(t.authorName)}</div>
                    </div>
                    <div style="display:flex;gap:8px;">
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

    root.innerHTML = `
      <section class="hw-editorial-strip">
        <div>
          <p class="hw-editorial-eyebrow">个人云端资产 · 四合一云端收藏夹</p>
          <h1 class="hw-editorial-title">${esc(App.state.user.name)} 的创作资产库</h1>
          <p class="hw-editorial-sub">收藏的画风与图型已实时同步至 <code>studio.handraw-style.com</code> 选卡器置顶分组。</p>
        </div>
      </section>

      <div class="hw-pills-row" style="margin-bottom:18px;">
        <button type="button" class="hw-pill ${UI.favTab === "styles" ? "is-active" : ""}" data-ftab="styles">🎨 画风 (${(cols.styles || []).length})</button>
        <button type="button" class="hw-pill ${UI.favTab === "layouts" ? "is-active" : ""}" data-ftab="layouts">📐 图型 (${(cols.layouts || []).length})</button>
        <button type="button" class="hw-pill ${UI.favTab === "works" ? "is-active" : ""}" data-ftab="works">🖼️ 作品与提示词 (${(cols.works || []).length})</button>
        <button type="button" class="hw-pill ${UI.favTab === "topics" ? "is-active" : ""}" data-ftab="topics">💬 实战帖 (${(cols.topics || []).length})</button>
      </div>

      ${bodyHtml}
    `;

    root.querySelectorAll("[data-ftab]").forEach((b) => {
      b.onclick = () => {
        UI.favTab = b.getAttribute("data-ftab");
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
      b.onclick = () => {
        S.toggleCollect(UI.favTab, b.getAttribute("data-unfav"), b.getAttribute("data-unfav"));
      };
    });
  }

  /* ======================== 4. CREDITS WALLET & FLYWHEEL CENTER ======================== */
  function renderWalletCenter(root) {
    if (!App.state.loggedIn) {
      openAuthPage("登录后即可查看积分钱包、签到领额度与管理个人创作密钥", () => switchView("wallet"));
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
          <p style="font-size:12.8px;color:var(--ink-muted);margin:0 0 12px;">给实测作品少于 3 个的冷门宝藏画风/图型发实战帖，双倍加奖且入驻新发曝光席！</p>
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

        ${
          s.user && s.user.apiKey
            ? `
              <div class="studio-step-card" style="margin:0;">
                <div style="font-weight:800;margin-bottom:6px;">🔌 本地资产库同步创作密钥</div>
                <p style="font-size:12px;color:var(--ink-muted);margin:0 0 8px;">用于本地工具一键同步已收藏与已解锁资产（独占黑盒受云端保护不可导出）：</p>
                <div style="display:flex;gap:6px;align-items:center;">
                  <code style="flex:1;padding:5px 8px;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:6px;font-size:11.5px;overflow:hidden;text-overflow:ellipsis;">${esc(s.user.apiKeyMasked || s.user.apiKey)}</code>
                  <button type="button" class="btn btn-sm" id="wallet-btn-copy-apikey">复制</button>
                </div>
              </div>
            `
            : ""
        }
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

    const copyKeyBtn = root.querySelector("#wallet-btn-copy-apikey");
    if (copyKeyBtn) {
      copyKeyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(App.state.user.apiKey || "");
        } catch (_) {}
        toast("🔑 已复制个人本地扩展同步密钥！");
      };
    }

    root.querySelector("#wallet-btn-pioneer").onclick = () => S.goToForumCompose({ style1: "FB-055", category: "assets" });
    root.querySelector("#wallet-btn-invite").onclick = () => {
      UI.walletShareItem = { itemType: "style", item: App.resourceMap.get("FX-001") || App.styles[0] };
      renderMain();
    };
    root.querySelector("#wallet-btn-contrib").onclick = () => S.goToForumCompose({ category: "assets" });
  }

  /* ======================== FRONT-STAGE MANAGEMENT: MODALS & HUB ======================== */
  async function openFrontUserManageModal(targetUsername) {
    if (!targetUsername) return;
    const isSuperAdmin = S.isAdmin && S.isAdmin();
    const canGlobal = S.canManageGlobal && S.canManageGlobal();
    if (!canGlobal) {
      toast("权限不足：仅运营审查员与超级管理员可进行前台用户治理");
      return;
    }

    let target = null;
    try {
      if (App.state.serverBacked) {
        const res = await S.apiJson(`/api/front/user-manage?username=${encodeURIComponent(targetUsername)}`);
        target = res.user;
      }
    } catch (err) {
      console.warn("fetch front user-manage error:", err);
    }
    if (!target) {
      const p = S.getCreatorProfile(targetUsername);
      target = {
        username: p.username,
        name: p.authorName,
        role: "user",
        status: "active",
        credits: 100,
        freeQuota: 5,
        honorBadge: p.honor.badge,
        honorOverride: ""
      };
    }

    const isTargetAdmin = target.role === "admin";
    if (isTargetAdmin && !isSuperAdmin) {
      alert("安全保护：运营审查员无权对超级管理员账号进行治理修改。");
      return;
    }

    let modal = document.getElementById("hw-front-user-manage-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "hw-front-user-manage-modal";
      modal.className = "hw-auth-modal-backdrop";
      document.body.appendChild(modal);
    }
    modal.style.display = "flex";

    const statusColor = target.status === "frozen" ? "var(--vermilion)" : "var(--jade)";
    const statusText = target.status === "frozen" ? "❄️ 封禁中" : "✅ 正常";

    modal.innerHTML = `
      <div class="hw-auth-modal" style="max-width:580px;width:92%;max-height:90vh;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;border-bottom:1px solid var(--paper-line);padding-bottom:10px;">
          <h3 style="margin:0;font-size:17.5px;font-family:var(--font-display);display:flex;align-items:center;gap:8px;">
            <span>🛡️</span> <span>前台用户治理 · @${esc(target.name)} (${esc(target.username)})</span>
          </h3>
          <button type="button" class="btn btn-sm" id="hw-btn-close-user-manage" style="padding:2px 8px;">✕</button>
        </div>

        <div style="background:var(--paper-inset);border-radius:10px;padding:10px 14px;margin-bottom:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;font-size:12.5px;">
          <div><span style="color:var(--ink-muted);">当前身份：</span><strong>${esc(target.role || "user")}</strong></div>
          <div><span style="color:var(--ink-muted);">账号状态：</span><strong style="color:${statusColor};">${statusText}</strong></div>
          <div><span style="color:var(--ink-muted);">积分余额：</span><strong>${target.credits !== undefined ? target.credits : 0}✦</strong></div>
          <div><span style="color:var(--ink-muted);">今日免费额度：</span><strong>${target.freeQuota !== undefined ? target.freeQuota : 5}次</strong></div>
        </div>

        <div style="display:grid;gap:14px;margin-bottom:20px;">
          <!-- 账号状态 (Operator + Admin) -->
          <div>
            <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">账号状态：</label>
            <select class="hw-input" id="front-user-status" style="width:100%;box-sizing:border-box;">
              <option value="active" ${target.status !== "frozen" ? "selected" : ""}>✅ 正常使用 (active)</option>
              <option value="frozen" ${target.status === "frozen" ? "selected" : ""}>❄️ 违规封禁 (frozen - 禁止发帖/评论/生图)</option>
            </select>
          </div>

          <!-- 荣誉等阶覆盖 (Operator + Admin) -->
          <div>
            <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">创作者荣誉等阶（人工干预）：</label>
            <select class="hw-input" id="front-user-honor" style="width:100%;box-sizing:border-box;">
              <option value="" ${!target.honorOverride ? "selected" : ""}>跟随系统自动规则 (Auto)</option>
              <option value="honor-pioneer" ${target.honorOverride === "honor-pioneer" ? "selected" : ""}>🌱 新晋手绘创作者</option>
              <option value="honor-master" ${target.honorOverride === "honor-master" ? "selected" : ""}>⚡ 资深配方先锋</option>
              <option value="honor-gold" ${target.honorOverride === "honor-gold" ? "selected" : ""}>🌟 殿堂驻站画友</option>
              <option value="honor-legend" ${target.honorOverride === "honor-legend" ? "selected" : ""}>👑 社区领航导师</option>
            </select>
          </div>

          <!-- 重置今日免费工坊额度 (Operator + Admin) -->
          <div style="display:flex;align-items:center;justify-content:space-between;background:var(--paper-bg);border:1px solid var(--paper-line);padding:10px 12px;border-radius:8px;">
            <div>
              <div style="font-size:13px;font-weight:750;">今日 Studio 免费额度</div>
              <div style="font-size:11.8px;color:var(--ink-muted);">当前剩余 ${target.freeQuota !== undefined ? target.freeQuota : 5} 次，点击重置恢复每日赠送额度</div>
            </div>
            <button type="button" class="btn btn-sm btn-gold" id="front-btn-reset-quota">🔄 重置为 5 次</button>
          </div>

          <!-- Admin Only Section -->
          ${
            isSuperAdmin
              ? `
                <div style="border-top:1px dashed var(--paper-line);padding-top:14px;display:grid;gap:12px;">
                  <div style="font-size:12px;font-weight:800;color:var(--vermilion);">👑 超级管理员专属权限配置</div>

                  <div>
                    <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">系统角色变更：</label>
                    <select class="hw-input" id="front-user-role" style="width:100%;box-sizing:border-box;">
                      <option value="user" ${target.role === "user" ? "selected" : ""}>🎨 普通创作者 (user)</option>
                      <option value="moderator" ${target.role === "moderator" ? "selected" : ""}>🏛️ 论坛板块版主 (moderator)</option>
                      <option value="operator" ${target.role === "operator" ? "selected" : ""}>🧭 运营审查员 (operator - 合并运营与审核)</option>
                      <option value="admin" ${target.role === "admin" ? "selected" : ""}>👑 超级管理员 (admin)</option>
                    </select>
                  </div>

                  <div id="front-moderator-boards-wrap" style="display:${target.role === "moderator" ? "block" : "none"};">
                    <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">任命管理板块（仅版主生效）：</label>
                    <div style="display:flex;gap:10px;flex-wrap:wrap;font-size:12.5px;">
                      <label><input type="checkbox" value="tuning" class="front-mod-board-chk" ${(target.moderatorBoards || []).includes("tuning") ? "checked" : ""} /> 🎯 提示词调优</label>
                      <label><input type="checkbox" value="experience" class="front-mod-board-chk" ${(target.moderatorBoards || []).includes("experience") ? "checked" : ""} /> 💡 实战心得</label>
                      <label><input type="checkbox" value="assets" class="front-mod-board-chk" ${(target.moderatorBoards || []).includes("assets") ? "checked" : ""} /> 📦 画风与图型</label>
                      <label><input type="checkbox" value="tools" class="front-mod-board-chk" ${(target.moderatorBoards || []).includes("tools") ? "checked" : ""} /> 🛠️ 工具实战</label>
                      <label><input type="checkbox" value="all" class="front-mod-board-chk" ${(target.moderatorBoards || []).includes("all") ? "checked" : ""} /> 🌐 全区板块</label>
                    </div>
                  </div>

                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div>
                      <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">增减积分 (Delta)：</label>
                      <input type="number" class="hw-input" id="front-user-credits-delta" placeholder="例如 +50 或 -20" style="width:100%;box-sizing:border-box;" />
                    </div>
                    <div>
                      <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">调整理由：</label>
                      <input type="text" class="hw-input" id="front-user-credits-reason" placeholder="例如：前台内容首发奖励" style="width:100%;box-sizing:border-box;" />
                    </div>
                  </div>

                  <div>
                    <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">重置登录密码（留空不修改）：</label>
                    <input type="password" class="hw-input" id="front-user-new-pwd" placeholder="输入新密码" style="width:100%;box-sizing:border-box;" />
                  </div>
                </div>
              `
              : ""
          }
        </div>

        <div style="display:flex;justify-content:flex-end;gap:10px;align-items:center;border-top:1px solid var(--paper-line);padding-top:12px;">
          <button type="button" class="btn btn-sm" id="hw-btn-cancel-user-manage">取消</button>
          <button type="button" class="btn btn-primary" id="hw-btn-save-user-manage">💾 保存治理变更</button>
        </div>
      </div>
    `;

    const closeUserModal = () => {
      modal.style.display = "none";
    };
    modal.querySelector("#hw-btn-close-user-manage").onclick = closeUserModal;
    modal.querySelector("#hw-btn-cancel-user-manage").onclick = closeUserModal;

    const roleSelect = modal.querySelector("#front-user-role");
    if (roleSelect) {
      roleSelect.onchange = () => {
        const wrap = modal.querySelector("#front-moderator-boards-wrap");
        if (wrap) wrap.style.display = roleSelect.value === "moderator" ? "block" : "none";
      };
    }

    const resetQuotaBtn = modal.querySelector("#front-btn-reset-quota");
    if (resetQuotaBtn) {
      resetQuotaBtn.onclick = async () => {
        try {
          if (App.state.serverBacked) {
            await S.apiJson(`/api/admin/users/${encodeURIComponent(target.username)}/reset-quota`, {
              method: "POST",
              body: {}
            });
          }
          toast("🔄 今日 Studio 免费额度已重置为 5 次！");
          target.freeQuota = 5;
        } catch (err) {
          toast(`重置额度失败：${err.message}`);
        }
      };
    }

    modal.querySelector("#hw-btn-save-user-manage").onclick = async () => {
      const nextStatus = modal.querySelector("#front-user-status").value;
      const nextHonor = modal.querySelector("#front-user-honor").value;

      const payload = {
        status: nextStatus,
        honorOverride: nextHonor
      };

      if (isSuperAdmin) {
        const nextRole = roleSelect ? roleSelect.value : target.role;
        payload.role = nextRole;
        if (nextRole === "moderator") {
          const checked = Array.from(modal.querySelectorAll(".front-mod-board-chk:checked")).map((c) => c.value);
          payload.moderatorBoards = checked;
        }
        const deltaStr = modal.querySelector("#front-user-credits-delta").value.trim();
        if (deltaStr) {
          const delta = parseInt(deltaStr, 10);
          if (!isNaN(delta) && delta !== 0) {
            payload.creditsDelta = delta;
            payload.creditsReason = modal.querySelector("#front-user-credits-reason").value.trim() || "前台管理调整";
          }
        }
        const newPwd = modal.querySelector("#front-user-new-pwd").value.trim();
        if (newPwd) {
          payload.newPassword = newPwd;
        }
      }

      try {
        if (App.state.serverBacked) {
          await S.apiJson(`/api/admin/users/${encodeURIComponent(target.username)}`, {
            method: "PATCH",
            body: payload
          });
        }
        toast("✅ 用户治理变更已生效！");
        closeUserModal();
        await S.refreshFromServer();
        renderMain();
      } catch (err) {
        toast(`保存失败：${err.message}`);
      }
    };
  }

  async function openFrontAssetEditModal(assetCode) {
    const item = App.resourceMap.get(assetCode);
    if (!item) {
      toast(`未找到资产：${assetCode}`);
      return;
    }
    const isSuperAdmin = S.isAdmin && S.isAdmin();

    let modal = document.getElementById("hw-front-asset-edit-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "hw-front-asset-edit-modal";
      modal.className = "hw-auth-modal-backdrop";
      document.body.appendChild(modal);
    }
    modal.style.display = "flex";

    modal.innerHTML = `
      <div class="hw-auth-modal" style="max-width:620px;width:92%;max-height:90vh;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;border-bottom:1px solid var(--paper-line);padding-bottom:10px;">
          <h3 style="margin:0;font-size:17.5px;font-family:var(--font-display);display:flex;align-items:center;gap:8px;">
            <span>✏️</span> <span>编辑资产与黑盒参数 · #${esc(item.id)} ${esc(item.name)}</span>
          </h3>
          <button type="button" class="btn btn-sm" id="hw-btn-close-asset-edit" style="padding:2px 8px;">✕</button>
        </div>

        <div style="display:grid;gap:12px;margin-bottom:18px;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
            <div>
              <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">资产名称：</label>
              <input class="hw-input" id="front-asset-name" value="${esc(item.name)}" style="width:100%;box-sizing:border-box;" />
            </div>
            <div>
              <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">分组归类：</label>
              <input class="hw-input" id="front-asset-group" value="${esc(item.group || "")}" style="width:100%;box-sizing:border-box;" />
            </div>
          </div>

          <div>
            <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">公开简介 / 特征描述：</label>
            <textarea class="hw-textarea" rows="2" id="front-asset-desc" style="width:100%;box-sizing:border-box;">${esc(item.description || "")}</textarea>
          </div>

          <div>
            <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">公开标准提示词定义：</label>
            <textarea class="hw-textarea" rows="3" id="front-asset-def" style="width:100%;box-sizing:border-box;">${esc(item.definition || "")}</textarea>
          </div>

          ${
            isSuperAdmin
              ? `
                <div style="background:rgba(180,40,20,0.05);border:1px solid rgba(180,40,20,0.25);border-radius:8px;padding:10px 12px;">
                  <div style="font-size:12.5px;font-weight:800;color:var(--vermilion);margin-bottom:4px;">🔒 云端生图底层黑盒参数 (Admin Only)</div>
                  <div style="font-size:11.8px;color:var(--ink-muted);margin-bottom:6px;">仅超级管理员可阅览与修改。独占画风在 Studio 云端执行生图时自动注入此底层参数。</div>
                  <textarea class="hw-textarea" rows="3" id="front-asset-exclusive-prompt" placeholder="云端黑盒注入提示词..." style="width:100%;box-sizing:border-box;font-family:monospace;font-size:12px;">${esc(item.exclusivePrompt || "")}</textarea>
                </div>
              `
              : ""
          }

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
            <div>
              <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">解锁所需积分：</label>
              <input type="number" class="hw-input" id="front-asset-cost" value="${item.unlockCost || 0}" style="width:100%;box-sizing:border-box;" />
            </div>
            <div>
              <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:750;">上架状态：</label>
              <select class="hw-input" id="front-asset-status" style="width:100%;box-sizing:border-box;">
                <option value="active" ${item.status !== "paused" ? "selected" : ""}>✅ 正常上架展示</option>
                <option value="paused" ${item.status === "paused" ? "selected" : ""}>⏸️ 暂停下架</option>
              </select>
            </div>
          </div>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:10px;align-items:center;border-top:1px solid var(--paper-line);padding-top:12px;">
          <button type="button" class="btn btn-sm" id="hw-btn-cancel-asset-edit">取消</button>
          <button type="button" class="btn btn-primary" id="hw-btn-save-asset-edit">💾 保存资产配置</button>
        </div>
      </div>
    `;

    const closeAssetModal = () => {
      modal.style.display = "none";
    };
    modal.querySelector("#hw-btn-close-asset-edit").onclick = closeAssetModal;
    modal.querySelector("#hw-btn-cancel-asset-edit").onclick = closeAssetModal;

    modal.querySelector("#hw-btn-save-asset-edit").onclick = async () => {
      const payload = {
        name: modal.querySelector("#front-asset-name").value.trim() || item.name,
        group: modal.querySelector("#front-asset-group").value.trim() || item.group,
        description: modal.querySelector("#front-asset-desc").value.trim(),
        definition: modal.querySelector("#front-asset-def").value.trim(),
        unlockCost: Math.max(0, parseInt(modal.querySelector("#front-asset-cost").value, 10) || 0),
        status: modal.querySelector("#front-asset-status").value
      };
      if (isSuperAdmin && modal.querySelector("#front-asset-exclusive-prompt")) {
        payload.exclusivePrompt = modal.querySelector("#front-asset-exclusive-prompt").value.trim();
      }

      try {
        if (App.state.serverBacked) {
          await S.apiJson(`/api/admin/assets/${encodeURIComponent(item.id)}`, {
            method: "PATCH",
            body: payload
          });
        }
        Object.assign(item, payload);
        toast(`✅ 资产 #${item.id} 配置已更新！`);
        closeAssetModal();
        await S.refreshFromServer();
        renderMain();
      } catch (err) {
        toast(`保存失败：${err.message}`);
      }
    };
  }

  window.HandrawFrontManage = {
    openFrontUserManageModal,
    openFrontAssetEditModal
  };
  if (window.Handraw) {
    window.Handraw.openFrontUserManageModal = openFrontUserManageModal;
    window.Handraw.openFrontAssetEditModal = openFrontAssetEditModal;
  }

  /* ======================== BOOTSTRAP ======================== */
  parseInitialUrl();
  S.initApp("main", renderMain).then(() => {
    updateSeoTitle();
    renderMain();
  }).catch((error) => {
    const root=document.getElementById("main-app-root");
    root.innerHTML=`<section class="hw-account-page"><h1>暂时无法加载社区</h1><p role="alert">${esc(error.message)}</p><button class="btn btn-primary" id="main-retry-boot">重试</button></section>`;
    root.querySelector("#main-retry-boot").onclick=()=>location.reload();
  });
})();
