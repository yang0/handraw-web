/* Handraw Web 2.0 — Role-Differentiated Management Consoles (Super Admin · Operator · Reviewer · Board Moderator) */
(function () {
  "use strict";

  const ROLE_MODULES = {
    admin: [
      { id: "dashboard", icon: "📊", label: "数据总览", desc: "全站核心指标、366+168 目录覆盖度、积分铸造消耗与审计轨迹" },
      { id: "users", icon: "👥", label: "用户与权限管理", desc: "新建/移除账号、重置密码、RBAC 四级角色、论坛版主任命、积分调账与老站迁移" },
      { id: "works", icon: "🖼️", label: "作品与全站评论", desc: "社区作品流、72h 首发提权、精选推荐与作品/论坛/画风图型评论治理" },
      { id: "catalog", icon: "🔒", label: "专属黑盒与目录", desc: "官网独占 FX/LX 云端黑盒 Prompt、USR 共创资产与创作台官方预设" },
      { id: "governance", icon: "💬", label: "论坛·版主·悬赏", desc: "论坛版主团队任命、全区帖子置顶加精、用户举报裁定与积分悬赏仲裁" },
      { id: "gateway", icon: "⚡", label: "生图网关与监控", desc: "chatgpt2api 实时连通性探测、云端任务队列与失败自动退费日志" },
      { id: "settings", icon: "⚙️", label: "运营配置与审计", desc: "全站公告条、积分经济核心参数、自审风控开关与管理操作审计记录" },
    ],
    operator: [
      { id: "dashboard", icon: "📊", label: "运营审查看板", desc: "社区活跃作品、官方目录点亮覆盖度、待裁定举报预警与内容安全态势" },
      { id: "users", icon: "👥", label: "用户治理与兑换码", desc: "普通违规账号冻结、荣誉授勋、每日免费生图额度重置与活动积分兑换码发放" },
      { id: "works", icon: "🖼️", label: "作品精选与全站评论", desc: "优质作品精选推荐、72h 首发曝光提权、违规下架与作品/论坛/画风图型评论治理" },
      { id: "governance", icon: "💬", label: "论坛运营与举报裁定", desc: "优质交流帖置顶加精、积分悬赏人工仲裁、违规举报核实下架与误报驳回" },
      { id: "settings", icon: "📣", label: "社区公告配置", desc: "配置全站顶部运营活动横幅与行动号召文案（底层黑盒机密与网关参数已隔离）" },
    ],
    moderator: [
      { id: "mod_overview", icon: "🏛️", label: "所辖板块概览", desc: "查看您被任命管辖的论坛板块指标、值班同僚版主与版务待办" },
      { id: "mod_topics", icon: "📌", label: "本版帖子治理", desc: "在管辖板块内执行帖子置顶、加精、跨板块移动及违规帖隐藏恢复" },
      { id: "mod_replies", icon: "💬", label: "本版回复巡查", desc: "巡查所辖板块帖子下的楼层回复，支持违规回复隐藏与恢复" },
      { id: "mod_reports", icon: "🚩", label: "本版举报工单", desc: "专属处理本板块内的帖子与回复举报（跨板块与全站数据按板块权限隔离）" },
    ],
  };

  const FORUM_BOARD_OPTIONS = [
    { id: "all", label: "📋 全区总版主（管辖全部 4 大板块）", short: "全区总版" },
    { id: "tuning", label: "🎯 求调优 / 悬赏区", short: "求调优" },
    { id: "experience", label: "💡 实战心得与翻车复盘", short: "实战心得" },
    { id: "assets", label: "🎨 画风与图型专区", short: "画风图型" },
    { id: "tools", label: "🛠️ 好用的工具与工作流", short: "工具工作流" },
  ];

  const state = {
    boot: null,
    user: null,
    profile: null,
    urlParsedOnce: false,
    module: "dashboard",
    subtab: {
      works: "works_list",
      catalog: "assets_list",
      governance: "reports_list",
      users: "users_list",
      settings: "config_form",
    },
    filters: {
      worksStatus: "all",
      worksQ: "",
      commentsStatus: "all",
      commentsQ: "",
      catKind: "all",
      catSource: "all",
      catStatus: "all",
      catQ: "",
      reportsStatus: "all",
      topicsStatus: "all",
      topicsBountyOnly: false,
      topicsQ: "",
      usersRole: "all",
      usersStatus: "all",
      usersQ: "",
      unlocksStatus: "all",
      genStatus: "all",
      genEngine: "all",
      genQ: "",
      auditAction: "",
      auditActor: "",
      auditTarget: "all",
      modBoard: "",
      modQ: "",
    },
    data: {
      dashboard: null,
      works: [],
      comments: [],
      catalog: [],
      officialBrief: [],
      presets: [],
      reports: [],
      topics: [],
      forumModerators: [],
      moderatorCandidates: [],
      users: [],
      unlocks: [],
      redeemCodes: [],
      gateway: null,
      generations: [],
      settings: null,
      audits: [],
      modConsole: null,
    },
  };

  function esc(val) {
    return String(val ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function channelHref(channel, extraQuery) {
    const proto = window.location.protocol;
    const host = window.location.hostname;
    const portPart = window.location.port ? `:${window.location.port}` : "";
    const suffix = extraQuery ? (extraQuery.startsWith("?") ? extraQuery : `?${extraQuery}`) : "";
    if (host.endsWith("handraw-style.com")) {
      if (channel === "studio") return `${proto}//studio.handraw-style.com${portPart}/${suffix}`;
      if (channel === "forum") return `${proto}//forum.handraw-style.com${portPart}/${suffix}`;
      if (channel === "admin") return `${proto}//admin.handraw-style.com${portPart}/${suffix}`;
      return `${proto}//handraw-style.com${portPart}/${suffix}`;
    }
    if (host.endsWith(".localhost")) {
      const prefix = ["studio", "forum", "admin"].includes(channel) ? `${channel}.` : "";
      return `${proto}//${prefix}localhost${portPart}/${suffix}`;
    }
    const paths = { main: "/", studio: "/studio/", forum: "/forum/", admin: "/admin/" };
    return `${paths[channel] || "/"}${suffix}`;
  }

  function toast(msg, isError) {
    const stack = document.getElementById("admin-toast-stack");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = "adm-toast" + (isError ? " err" : "");
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  async function api(path, options) {
    const opts = Object.assign({ credentials: "include", headers: {} }, options || {});
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, opts);
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || `请求失败 (HTTP ${res.status})`);
      err.status = res.status;
      err.code = data.code || "";
      throw err;
    }
    return data;
  }

  function openModal(htmlContent) {
    const bd = document.getElementById("admin-modal-backdrop");
    const card = document.getElementById("admin-modal-card");
    if (!bd || !card) return;
    card.innerHTML = htmlContent;
    bd.hidden = false;
  }

  function closeModal() {
    const bd = document.getElementById("admin-modal-backdrop");
    if (bd) bd.hidden = true;
  }

  document.addEventListener("click", (ev) => {
    const bd = document.getElementById("admin-modal-backdrop");
    if (bd && ev.target === bd) closeModal();
  });

  function effRole() {
    const r = (state.profile && state.profile.effectiveRole) || "guest";
    return r === "reviewer" ? "operator" : r;
  }

  function caps() {
    return (state.profile && state.profile.capabilities) || {};
  }

  function isAdmin() {
    return effRole() === "admin";
  }

  function getActiveModules() {
    return ROLE_MODULES[effRole()] || [];
  }

  function syncUrlModule() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("module", state.module);
      window.history.replaceState({}, "", url.toString());
    } catch (_) {}
  }

  function sanitizeSubtabsForRole() {
    const r = effRole();
    const c = caps();
    if (r === "operator") {
      if (!["users_list", "redeem_list"].includes(state.subtab.users)) {
        state.subtab.users = "users_list";
      }
      if (state.subtab.governance === "moderators_list") state.subtab.governance = "reports_list";
      state.subtab.settings = "config_form";
    }
    if (!c.canViewAuditLogs && state.subtab.settings === "audit_list") {
      state.subtab.settings = "config_form";
    }
  }

  async function refreshBootAndPermissions() {
    const boot = await api("/api/boot");
    state.boot = boot;
    state.user = boot.user;
    if (!state.user || !state.user.loggedIn) {
      state.profile = null;
      return false;
    }
    try {
      const perm = await api("/api/admin/permissions");
      state.profile = perm.profile;
      return true;
    } catch (err) {
      state.profile = null;
      if (err.status === 403 || err.status === 401) return false;
      throw err;
    }
  }

  async function switchSandboxRole(username) {
    if (!state.boot?.demoMode) { toast("当前服务未启用演示身份切换", true); return; }
    try {
      await api("/api/auth/sandbox-switch", { method: "POST", body: { username } });
      await init();
      toast(username === "guest" ? "已退出后台登录" : `已切换管理视角为 @${username}`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderAccessGate() {
    const root = document.getElementById("admin-root");
    const logged = state.user && state.user.loggedIn;
    root.innerHTML = `
      <div class="adm-gate-wrap">
        <div class="adm-gate-card" style="max-width:660px;">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
            <span class="admin-brand-mark">H</span>
            <div>
              <div style="font-size:19px;font-weight:800;">Handraw 分级权限管理中枢</div>
              <div style="font-size:12.5px;color:var(--adm-ink-muted);">四级角色分权隔离 · 不同角色拥有专属管理后台 · admin.handraw-style.com</div>
            </div>
          </div>

          <div style="background:var(--adm-amber-soft);color:var(--adm-amber);padding:11px 14px;border-radius:10px;font-size:13px;font-weight:600;margin-bottom:14px;">
            ${logged
              ? `当前登录账号 @${esc(state.user.username)}（普通创作者 user，且未被任命为论坛版主）无后台管理权限。请在下方切换或登录任一管理角色体验对应的专属控制台。`
              : "当前处于未登录状态。管理后台按角色分权展示：超级管理员、运营管理员、内容审核员及论坛板块版主拥有各自专属的工作台。"}
          </div>

          <div class="adm-role-matrix-grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr));">
            <div class="adm-role-matrix-card">
              <div style="font-weight:800;color:#b74227;">👑 超级管理员 (admin)</div>
              <div style="color:var(--adm-ink-soft);margin-top:2px;">7 大全量模块：新建/删除用户、角色提权、任命论坛版主、云端黑盒 Prompt、积分调账、网关与审计。</div>
            </div>
            <div class="adm-role-matrix-card">
              <div style="font-weight:800;color:#9e5a12;">🧭 运营审查员 (operator)</div>
              <div style="color:var(--adm-ink-soft);margin-top:2px;">5 大运审模块：整合运营增长与内容安全巡检（举报裁定、下架冻结、精选推荐、荣誉授勋、兑换码与公告）。</div>
            </div>
            <div class="adm-role-matrix-card">
              <div style="font-weight:800;color:#3c4b7d;">🏛️ 论坛板块版主 (moderator)</div>
              <div style="color:var(--adm-ink-soft);margin-top:2px;">4 大本版模块：严格限所辖论坛板块执行置顶、加精、移板块、回复巡查与本版举报处理。</div>
            </div>
          </div>

          <form id="adm-login-form" style="margin-top:12px;">
            <div class="adm-form-grid">
              <div class="adm-field" style="margin-bottom:8px;">
                <label>管理账号 / 邮箱</label>
                <input class="adm-input" id="adm-login-user" value="${state.boot?.demoMode ? "yang0" : ""}" placeholder="管理账号或邮箱" autocomplete="username" required />
              </div>
              <div class="adm-field" style="margin-bottom:8px;">
                <label>登录密码</label>
                <input class="adm-input" id="adm-login-pass" type="password" value="${state.boot?.demoMode ? "handraw123" : ""}" placeholder="密码" autocomplete="current-password" required />
              </div>
            </div>
            <button type="submit" class="adm-btn adm-btn-primary" style="width:100%;padding:10px;margin-top:4px;">🔐 登录进入对应角色管理台</button>
          </form>

          <div data-demo-only style="margin-top:16px;padding-top:14px;border-top:1px solid var(--adm-border);">
            <div style="font-size:12px;color:var(--adm-ink-muted);margin-bottom:8px;">🎭 一键体验不同管理角色的差异化后台：</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button type="button" class="adm-btn adm-btn-sm" data-quick-switch="yang0">👑 超管 yang0</button>
              <button type="button" class="adm-btn adm-btn-sm" data-quick-switch="ops_lin">🧭 运营审查 ops_lin</button>
              <button type="button" class="adm-btn adm-btn-sm" data-quick-switch="momo_design">🏛️ 版主 momo_design (画风图型版)</button>
              <button type="button" class="adm-btn adm-btn-sm" data-quick-switch="pm_chen">🏛️ 版主 pm_chen (双板块)</button>
              <a class="adm-btn adm-btn-sm" href="${esc(channelHref("main"))}" style="text-decoration:none;">↗ 返回社区主站</a>
            </div>
          </div>
        </div>
      </div>
    `;

    if (!state.boot?.demoMode) root.querySelectorAll("[data-demo-only]").forEach(node => node.remove());
    const form = document.getElementById("adm-login-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const identifier = document.getElementById("adm-login-user").value.trim();
          const password = document.getElementById("adm-login-pass").value;
          await api("/api/auth/login", { method: "POST", body: { identifier, password } });
          await init();
          toast("已登录进入对应角色管理后台");
        } catch (err) {
          toast(err.message, true);
        }
      });
    }
    root.querySelectorAll("[data-quick-switch]").forEach((btn) => {
      btn.addEventListener("click", () => switchSandboxRole(btn.getAttribute("data-quick-switch")));
    });
  }

  async function loadModuleData(mod) {
    sanitizeSubtabsForRole();
    if (mod.startsWith("mod_")) {
      state.data.modConsole = await api(
        `/api/admin/moderator-overview?board=${encodeURIComponent(state.filters.modBoard)}&q=${encodeURIComponent(state.filters.modQ)}`
      );
      return;
    }

    if (mod === "dashboard") {
      state.data.dashboard = await api("/api/admin/dashboard");
    } else if (mod === "works") {
      if (state.subtab.works === "comments_list") {
        const res = await api(`/api/admin/comments?status=${encodeURIComponent(state.filters.commentsStatus)}&q=${encodeURIComponent(state.filters.commentsQ)}`);
        state.data.comments = res.items || [];
      } else {
        const res = await api(`/api/admin/works?status=${encodeURIComponent(state.filters.worksStatus)}&q=${encodeURIComponent(state.filters.worksQ)}`);
        state.data.works = res.items || [];
      }
    } else if (mod === "catalog") {
      if (state.subtab.catalog === "presets_list") {
        const res = await api("/api/admin/presets");
        state.data.presets = res.items || [];
      } else {
        const res = await api(
          `/api/admin/catalog?kind=${encodeURIComponent(state.filters.catKind)}&sourceType=${encodeURIComponent(state.filters.catSource)}&status=${encodeURIComponent(state.filters.catStatus)}&q=${encodeURIComponent(state.filters.catQ)}`
        );
        state.data.catalog = res.items || [];
        state.data.officialBrief = res.officialBrief || [];
      }
    } else if (mod === "governance") {
      if (state.subtab.governance === "topics_list") {
        const res = await api(
          `/api/admin/topics?status=${encodeURIComponent(state.filters.topicsStatus)}&bountyOnly=${state.filters.topicsBountyOnly ? "1" : "0"}&q=${encodeURIComponent(state.filters.topicsQ)}`
        );
        state.data.topics = res.items || [];
      } else if (state.subtab.governance === "moderators_list") {
        const res = await api("/api/admin/forum-moderators");
        state.data.forumModerators = res.items || [];
        state.data.moderatorCandidates = res.candidates || [];
      } else {
        const res = await api(`/api/admin/reports?status=${encodeURIComponent(state.filters.reportsStatus)}`);
        state.data.reports = res.items || [];
      }
    } else if (mod === "users") {
      const sub = state.subtab.users;
      if (sub === "unlocks_list" && caps().canRefundUnlocks) {
        const res = await api(`/api/admin/unlocks?status=${encodeURIComponent(state.filters.unlocksStatus)}`);
        state.data.unlocks = res.items || [];
      } else if (sub === "redeem_list" && caps().canManageRedeemCodes) {
        const res = await api("/api/admin/redeem-codes");
        state.data.redeemCodes = res.items || [];
      } else {
        const res = await api(
          `/api/admin/users?role=${encodeURIComponent(state.filters.usersRole)}&status=${encodeURIComponent(state.filters.usersStatus)}&q=${encodeURIComponent(state.filters.usersQ)}`
        );
        state.data.users = res.items || [];
      }
    } else if (mod === "gateway") {
      const [gw, gens] = await Promise.all([
        api("/api/admin/gateway"),
        api(
          `/api/admin/generations?status=${encodeURIComponent(state.filters.genStatus)}&engine=${encodeURIComponent(state.filters.genEngine)}&q=${encodeURIComponent(state.filters.genQ)}`
        ),
      ]);
      state.data.gateway = gw;
      state.data.generations = gens.items || [];
    } else if (mod === "settings") {
      if (state.subtab.settings === "audit_list" && caps().canViewAuditLogs) {
        const res = await api(
          `/api/admin/audit-logs?action=${encodeURIComponent(state.filters.auditAction)}&actor=${encodeURIComponent(state.filters.auditActor)}&targetType=${encodeURIComponent(state.filters.auditTarget)}`
        );
        state.data.audits = res.items || [];
      } else {
        const res = await api("/api/admin/settings");
        state.data.settings = res.settings || {};
      }
    }
  }

  function renderRoleScopeBanner() {
    const prof = state.profile;
    if (!prof) return "";
    const modPills = (prof.moderatedBoardDetails || [])
      .map((b) => `<span class="adm-badge exclusive" style="margin-left:4px;">🛡️ ${esc(b.shortLabel)}·${esc(b.title)}</span>`)
      .join("");
    return `
      <div class="adm-role-scope-banner" data-role-banner="${esc(prof.effectiveRole)}">
        <div>
          <div style="font-size:13.5px;font-weight:800;">
            ${esc(prof.badge)} · ${esc(prof.consoleTitle)} ${modPills}
          </div>
          <div style="font-size:12px;color:var(--adm-ink-soft);margin-top:3px;">${esc(prof.summary)}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <span class="adm-badge neutral">开放模块 ${getActiveModules().length} 个</span>
          ${caps().canCreateUser ? `<button class="adm-btn adm-btn-sm adm-btn-primary" id="banner-new-user-btn">+ 新建用户账号</button>` : ""}
          ${prof.effectiveRole === "moderator" ? `<a class="adm-btn adm-btn-sm" href="${esc(channelHref("forum"))}" style="text-decoration:none;">↗ 前往论坛前台巡版</a>` : ""}
        </div>
      </div>
    `;
  }

  /* ======================== BOARD MODERATOR CONSOLE (4 MODULES) ======================== */

  function renderModeratorToolbar() {
    const mc = state.data.modConsole;
    const boards = (mc && mc.allowedBoards) || [];
    return `
      <div class="adm-toolbar">
        <div class="adm-filters">
          <select class="adm-select" id="flt-mod-board">
            <option value="" ${!state.filters.modBoard ? "selected" : ""}>管辖范围内全部板块 (${boards.length})</option>
            ${boards.map((b) => `<option value="${esc(b.id)}" ${state.filters.modBoard === b.id ? "selected" : ""}>${esc(b.label)}</option>`).join("")}
          </select>
          <input class="adm-input" id="flt-mod-q" value="${esc(state.filters.modQ)}" placeholder="搜索本版帖子标题 / 回复内容 / 用户名…" style="width:250px;" />
          <button class="adm-btn" id="btn-mod-search">🔍 筛选本版内容</button>
        </div>
        <div style="font-size:12px;color:var(--adm-ink-muted);">权限边界：仅限管辖板块内容治理，其他板块及全站用户库已自动物理隔离</div>
      </div>
    `;
  }

  function renderModeratorOverviewSection() {
    const mc = state.data.modConsole;
    if (!mc) return `<div class="adm-panel">正在同步所辖板块版务数据…</div>`;
    const k = mc.kpis;
    return `
      <div class="adm-kpi-grid">
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🏛️ 管辖论坛板块数</div>
          <div class="adm-kpi-val vermilion">${k.boardsCount} 个板块</div>
          <div class="adm-kpi-foot">${(mc.allowedBoards || []).map((b) => b.shortLabel).join(" · ")}</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">📌 本版话题总数</div>
          <div class="adm-kpi-val">${k.topicsTotal}</div>
          <div class="adm-kpi-foot">置顶 ${k.topicsPinned} 篇 · 🌟 精华 ${k.topicsFeatured} 篇 · 待结悬赏 ${k.openBounties} 单</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">💬 本版楼层回复</div>
          <div class="adm-kpi-val jade">${k.repliesTotal}</div>
          <div class="adm-kpi-foot">支持违规广告/引战楼层一键隐藏与恢复</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🚩 本版待处理举报</div>
          <div class="adm-kpi-val ${k.openReports > 0 ? "vermilion" : ""}">${k.openReports} 单</div>
          <div class="adm-kpi-foot">仅展示落在您管辖板块内的帖子与回复举报</div>
        </div>
      </div>

      <div class="adm-grid-2">
        <div class="adm-panel">
          <div class="adm-panel-head">
            <h3 class="adm-panel-title">📋 我管辖的论坛板块</h3>
            <button class="adm-btn adm-btn-sm adm-btn-primary" data-jump-mod="mod_topics">进入帖子治理 →</button>
          </div>
          ${(mc.allowedBoards || []).map((b) => `
            <div style="padding:11px 12px;border:1px solid var(--adm-border);border-radius:10px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:10px;">
              <div>
                <div style="font-weight:800;font-size:13.5px;">${esc(b.label)}</div>
                <div style="font-size:12px;color:var(--adm-ink-soft);margin-top:2px;">${esc(b.desc)}</div>
              </div>
              <a class="adm-btn adm-btn-sm" href="${esc(channelHref("forum", `cat=${encodeURIComponent(b.id)}`))}" style="text-decoration:none;white-space:nowrap;">前台查看 ↗</a>
            </div>
          `).join("")}
        </div>

        <div class="adm-panel">
          <div class="adm-panel-head">
            <h3 class="adm-panel-title">🛡️ 同板块协同值班版主</h3>
          </div>
          <div class="adm-table-wrap">
            <table class="adm-table">
              <thead><tr><th>版主账号</th><th>管辖板块</th><th>头衔</th></tr></thead>
              <tbody>
                ${(mc.coModerators || []).map((m) => `
                  <tr>
                    <td><strong>${esc(m.displayName)}</strong> <span style="color:var(--adm-ink-muted);">(@${esc(m.username)})</span></td>
                    <td><span class="adm-badge neutral">${esc(m.shortLabel)}</span></td>
                    <td><span class="adm-badge exclusive">🛡️ ${esc(m.title)}</span></td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  }

  function renderModeratorTopicsSection() {
    const mc = state.data.modConsole;
    if (!mc) return `<div class="adm-panel">正在读取本版帖子列表…</div>`;
    return `
      <div class="adm-panel">
        ${renderModeratorToolbar()}
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>本版话题</th><th>所属板块</th><th>楼主</th><th>互动 / 悬赏</th><th>状态</th><th>版主治理操作</th></tr></thead>
            <tbody>
              ${(mc.topics || []).map((t) => `
                <tr>
                  <td style="max-width:320px;">
                    <div style="font-weight:700;">
                      ${t.pinned ? `<span class="adm-badge exclusive">📌 置顶</span> ` : ""}
                      ${t.featured ? `<span class="adm-badge published">🌟 精华</span> ` : ""}
                      ${esc(t.title)}
                    </div>
                    <div style="font-size:11.5px;color:var(--adm-ink-muted);margin-top:3px;">ID: ${esc(t.id)} · ${esc(t.createdAt)}</div>
                  </td>
                  <td><span class="adm-badge neutral">${esc(t.categoryLabel)}</span></td>
                  <td>${esc(t.authorName)}<div style="font-size:11.5px;color:var(--adm-ink-muted);">@${esc(t.authorUsername)}</div></td>
                  <td>
                    <div style="font-size:12px;">👍 ${t.likes} · 💬 ${t.repliesCount}</div>
                    ${t.bounty > 0 ? `<div style="font-size:11.5px;color:var(--adm-vermilion);">🎯 ${t.bounty}✦ (${esc(t.bountyStatus)})</div>` : ""}
                  </td>
                  <td><span class="adm-badge ${esc(t.status)}">${esc(t.status)}</span></td>
                  <td>
                    <div class="adm-actions">
                      <button class="adm-btn adm-btn-sm" data-mod-op="${t.pinned ? "unpin" : "pin"}" data-mod-tid="${esc(t.id)}">${t.pinned ? "取消置顶" : "📌 置顶"}</button>
                      <button class="adm-btn adm-btn-sm" data-mod-op="${t.featured ? "unfeature" : "feature"}" data-mod-tid="${esc(t.id)}">${t.featured ? "取消精华" : "🌟 设精华"}</button>
                      <select class="adm-select" style="padding:4px 8px;font-size:12px;width:auto;" data-mod-move-tid="${esc(t.id)}">
                        <option value="">📂 移至板块…</option>
                        ${FORUM_BOARD_OPTIONS.filter((b) => b.id !== "all" && b.id !== t.category).map((b) => `<option value="${esc(b.id)}">→ ${esc(b.short)}</option>`).join("")}
                      </select>
                      ${t.status === "deleted"
                        ? `<span class="adm-badge deleted">已删除，不可恢复</span>`
                        : t.status === "published"
                        ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-mod-op="hide" data-mod-tid="${esc(t.id)}">🙈 隐藏</button>`
                        : `<button class="adm-btn adm-btn-sm adm-btn-jade" data-mod-op="publish" data-mod-tid="${esc(t.id)}">✅ 恢复</button>`}
                    </div>
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">所辖板块暂无匹配话题</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderModeratorRepliesSection() {
    const mc = state.data.modConsole;
    if (!mc) return `<div class="adm-panel">正在读取本版回复列表…</div>`;
    return `
      <div class="adm-panel">
        ${renderModeratorToolbar()}
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>所属本版话题</th><th>板块</th><th>回复人</th><th>回复正文</th><th>状态</th><th>版主操作</th></tr></thead>
            <tbody>
              ${(mc.replies || []).map((r) => `
                <tr>
                  <td style="max-width:220px;font-weight:600;">${esc(r.topicTitle)}</td>
                  <td><span class="adm-badge neutral">${esc(r.categoryLabel)}</span></td>
                  <td>@${esc(r.authorUsername)}<div style="font-size:11px;color:var(--adm-ink-muted);">${esc(r.createdAt)}</div></td>
                  <td style="max-width:340px;">${esc(r.text)}</td>
                  <td><span class="adm-badge ${esc(r.status)}">${esc(r.status)}</span></td>
                  <td>
                    ${r.status === "published"
                      ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-mod-reply-op="hide_reply" data-mod-tid="${esc(r.topicId)}" data-mod-rid="${esc(r.id)}">🙈 隐藏回复</button>`
                      : `<button class="adm-btn adm-btn-sm adm-btn-jade" data-mod-reply-op="publish_reply" data-mod-tid="${esc(r.topicId)}" data-mod-rid="${esc(r.id)}">✅ 恢复展示</button>`}
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">所辖板块暂无回复记录</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderModeratorReportsSection() {
    const mc = state.data.modConsole;
    if (!mc) return `<div class="adm-panel">正在读取本版举报工单…</div>`;
    return `
      <div class="adm-panel">
        ${renderModeratorToolbar()}
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>工单#</th><th>本版目标</th><th>所属板块</th><th>举报原因</th><th>举报人</th><th>状态</th><th>裁定</th></tr></thead>
            <tbody>
              ${(mc.reports || []).map((r) => `
                <tr>
                  <td><strong>#${r.id}</strong></td>
                  <td><span class="adm-badge neutral">${esc(r.targetType)}</span> <strong>${esc(r.targetTitle || r.targetId)}</strong></td>
                  <td><span class="adm-badge exclusive">${esc(r.categoryLabel)}</span></td>
                  <td><div style="font-weight:700;color:var(--adm-vermilion);">${esc(r.reason)}</div><div style="font-size:12px;color:var(--adm-ink-soft);">${esc(r.detail || "—")}</div></td>
                  <td>@${esc(r.reporterUsername)}</td>
                  <td><span class="adm-badge ${esc(r.status)}">${esc(r.status)}</span></td>
                  <td>
                    ${r.status === "open"
                      ? `<div class="adm-actions">
                          <button class="adm-btn adm-btn-sm adm-btn-danger" data-rep-resolve="confirmed" data-rep-id="${r.id}">✅ 属实隐藏</button>
                          <button class="adm-btn adm-btn-sm adm-btn-jade" data-rep-resolve="dismissed" data-rep-id="${r.id}">↩ 驳回恢复</button>
                        </div>`
                      : `<span style="font-size:12px;color:var(--adm-ink-muted);">已结案</span>`}
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="7" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">🎉 您管辖的板块当前无举报工单</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  /* ======================== STAFF MODULES (ADMIN / OPERATOR / REVIEWER) ======================== */

  function renderDashboardSection() {
    const d = state.data.dashboard;
    if (!d) return `<div class="adm-panel">正在加载总览指标…</div>`;
    const k = d.kpis;
    const totalOfficial = k.officialStylesCount + k.officialLayoutsCount;
    const covPct = totalOfficial ? ((k.coveredOfficialCount * 100) / totalOfficial).toFixed(1) : "0.0";
    const r = effRole();

    return `
      <div class="adm-kpi-grid">
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">👥 注册创作者总数</div>
          <div class="adm-kpi-val">${k.usersTotal}</div>
          <div class="adm-kpi-foot">活跃 ${k.usersActive} · 冻结 ${k.usersFrozen} · 管理团队 ${k.usersStaff} · Discourse 迁移 ${k.discourseMigratedCount}</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🖼️ 社区作品广场</div>
          <div class="adm-kpi-val vermilion">${k.worksPublished}</div>
          <div class="adm-kpi-foot">72h 首发新秀 ${k.worksNew72h} · 精选 ${k.worksFeatured} · 暂停/隐藏 ${k.worksPaused + k.worksHidden}</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🎨 官方画风+图型覆盖度</div>
          <div class="adm-kpi-val jade">${covPct}%</div>
          <div class="adm-kpi-foot">已点亮 ${k.coveredOfficialCount}/${totalOfficial} · 荒地待开荒 ${k.pioneerZeroWorkCount} · 黑盒 ${k.exclusiveAssetsCount} / 共创 ${k.communityAssetsCount}</div>
        </div>
        ${r !== "reviewer" ? `
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">✦ 积分经济流转池</div>
          <div class="adm-kpi-val">${k.creditsCirculation}✦</div>
          <div class="adm-kpi-foot">累计铸造 +${k.creditsMintedTotal}✦ · 消耗 -${k.creditsBurnedTotal}✦ · 解锁 GMV ${k.unlockGmvCredits}✦</div>
        </div>` : ""}
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">💬 论坛悬赏与举报工单</div>
          <div class="adm-kpi-val ${k.openReportsCount > 0 ? "vermilion" : ""}">${k.openReportsCount} 待审举报</div>
          <div class="adm-kpi-foot">话题 ${k.topicsPublished} 篇 · 待结悬赏 ${k.openBountiesCount} 单 (${k.openBountiesEscrow}✦ 托管中)</div>
        </div>
        ${caps().canManageGateway ? `
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">⚡ 云端创作台生图任务</div>
          <div class="adm-kpi-val">${k.studioGenerationsTotal}</div>
          <div class="adm-kpi-foot">直连网关 ${k.studioGenerationsLive} 次 · 异常自动退费 ${k.studioGenerationsRefunded} 次</div>
        </div>` : ""}
      </div>

      <div class="adm-grid-2">
        <div class="adm-panel">
          <div class="adm-panel-head">
            <h3 class="adm-panel-title">🚩 待处理社区举报队列 (${(d.recentReports || []).length})</h3>
            <button class="adm-btn adm-btn-sm adm-btn-primary" data-jump-mod="governance">进入举报治理台 →</button>
          </div>
          ${(d.recentReports || []).length === 0
            ? `<div style="color:var(--adm-ink-muted);font-size:13px;padding:12px 0;">🎉 当前无待处理举报工单</div>`
            : `<div class="adm-table-wrap"><table class="adm-table">
                <thead><tr><th>目标</th><th>举报原因</th><th>举报人</th><th>时间</th></tr></thead>
                <tbody>
                  ${d.recentReports.map((rep) => `
                    <tr>
                      <td><span class="adm-badge open">${esc(rep.targetType)}</span> <strong>${esc(rep.targetTitle || rep.targetId)}</strong></td>
                      <td>${esc(rep.reason)}</td>
                      <td>@${esc(rep.reporterUsername)}</td>
                      <td style="color:var(--adm-ink-muted);">${esc(rep.createdAt)}</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table></div>`}
        </div>

        <div class="adm-panel">
          <div class="adm-panel-head">
            <h3 class="adm-panel-title">📐 官方目录分类作品覆盖度（Top 分组）</h3>
            <span style="font-size:12px;color:var(--adm-ink-muted);">荒地编号首晒自动奖 +15✦</span>
          </div>
          <div>
            ${(d.groupCoverage || []).slice(0, 8).map((g) => `
              <div class="adm-cov-row">
                <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(g.group)}">
                  ${g.kind === "layout" ? "📐" : "🎨"} ${esc(g.group)}
                </div>
                <div class="adm-cov-bar"><div class="adm-cov-fill" style="width:${Math.min(100, g.coveragePct)}%"></div></div>
                <div style="text-align:right;color:var(--adm-ink-soft);font-size:12px;">
                  ${g.coveredAssets}/${g.totalAssets} (${g.totalWorks}作)
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      </div>

      ${caps().canViewAuditLogs ? `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <h3 class="adm-panel-title">📜 最新管理审计轨迹（仅超级管理员可见）</h3>
          <button class="adm-btn adm-btn-sm" data-jump-audit="1">全部审计日志 →</button>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>操作人</th><th>动作</th><th>目标</th><th>原因摘要</th><th>时间</th></tr></thead>
            <tbody>
              ${(d.recentAudits || []).slice(0, 6).map((a) => `
                <tr>
                  <td><strong>@${esc(a.actorUsername)}</strong> <span class="adm-badge neutral">${esc(a.actorRole)}</span></td>
                  <td><code>${esc(a.action)}</code></td>
                  <td>${esc(a.targetId)}</td>
                  <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(a.reason)}</td>
                  <td style="color:var(--adm-ink-muted);">${esc(a.createdAt)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>` : ""}
    `;
  }

  function renderWorksSection() {
    const sub = state.subtab.works;
    return `
      <div class="adm-subtabs">
        <button class="adm-subtab ${sub === "works_list" ? "active" : ""}" data-subtab="works:works_list">🖼️ 社区作品审核 (${state.data.works.length})</button>
        <button class="adm-subtab ${sub === "comments_list" ? "active" : ""}" data-subtab="works:comments_list">💬 作品·论坛·画风图型评论治理</button>
      </div>
      ${sub === "comments_list" ? renderCommentsTable() : renderWorksTable()}
    `;
  }

  function renderWorksTable() {
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-works-status">
              <option value="all" ${state.filters.worksStatus === "all" ? "selected" : ""}>全部状态</option>
              <option value="published" ${state.filters.worksStatus === "published" ? "selected" : ""}>已发布 (published)</option>
              <option value="featured" ${state.filters.worksStatus === "featured" ? "selected" : ""}>精选推荐 (featured)</option>
              <option value="paused" ${state.filters.worksStatus === "paused" ? "selected" : ""}>保护暂停 (paused)</option>
              <option value="hidden" ${state.filters.worksStatus === "hidden" ? "selected" : ""}>已下架隐藏 (hidden)</option>
            </select>
            <input class="adm-input" id="flt-works-q" value="${esc(state.filters.worksQ)}" placeholder="搜索标题 / 作者 / 画风编号 / 图型编号…" style="width:260px;" />
            <button class="adm-btn" id="btn-works-search">🔍 筛选</button>
          </div>
          <div style="font-size:12px;color:var(--adm-ink-muted);">提示：审核员禁止自审本人作品；物理删除仅限超级管理员</div>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead>
              <tr>
                <th>预览</th>
                <th>作品信息与挂载配方</th>
                <th>作者</th>
                <th>定价 / 点赞收藏评论</th>
                <th>状态</th>
                <th>管理操作</th>
              </tr>
            </thead>
            <tbody>
              ${state.data.works.map((w) => `
                <tr>
                  <td><img class="adm-thumb" src="${esc(w.image)}" alt="${esc(w.title)}" loading="lazy" /></td>
                  <td style="max-width:340px;">
                    <div style="font-weight:700;margin-bottom:4px;">
                      ${esc(w.title)}
                      ${w.featured ? `<span class="adm-badge exclusive">⭐ 精选</span>` : ""}
                      ${w.isNew ? `<span class="adm-badge published">✨ 首发</span>` : ""}
                      ${w.openReportsCount > 0 ? `<span class="adm-badge hidden">🚩 ${w.openReportsCount} 举报</span>` : ""}
                    </div>
                    <div style="font-size:12px;color:var(--adm-ink-soft);margin-bottom:4px;">
                      配方：${(w.styles || []).map((s) => `<code>${esc(s)}</code>`).join(" ") || "无画风"}
                      ${w.layout ? ` · <code>${esc(w.layout)}</code>` : ""}
                      · ${esc(w.ratio)}
                    </div>
                    <div style="font-size:11.5px;color:var(--adm-ink-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(w.prompt)}">
                      Prompt: ${esc(w.prompt)}
                    </div>
                  </td>
                  <td>
                    <div style="font-weight:600;">${esc(w.authorName)}</div>
                    <div style="font-size:12px;color:var(--adm-ink-muted);">@${esc(w.authorUsername)}</div>
                  </td>
                  <td>
                    <div>${w.price > 0 ? `<strong style="color:var(--adm-vermilion);">${w.price}✦ 锁配方</strong>` : `<span style="color:var(--adm-jade);">开源免费</span>`}</div>
                    <div style="font-size:12px;color:var(--adm-ink-muted);">👍 ${w.likes ?? w.cheers} · 💬 ${w.commentsCount} · 🎁 ${w.tips}✦</div>
                  </td>
                  <td><span class="adm-badge ${esc(w.status)}">${esc(w.status)}</span></td>
                  <td>
                    <div class="adm-actions">
                      <button class="adm-btn adm-btn-sm" data-work-act="${w.featured ? "unfeature" : "feature"}" data-work-id="${esc(w.id)}">${w.featured ? "取消精选" : "⭐ 精选"}</button>
                      <button class="adm-btn adm-btn-sm" data-work-act="boost_new" data-work-id="${esc(w.id)}">✨ 72h提权</button>
                      <button class="adm-btn adm-btn-sm" data-work-edit="${esc(w.id)}">✏️ 编辑</button>
                      ${w.status === "published"
                        ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-work-act="hide" data-work-id="${esc(w.id)}">🚫 下架</button>`
                        : `<button class="adm-btn adm-btn-sm adm-btn-jade" data-work-act="publish" data-work-id="${esc(w.id)}">✅ 恢复上架</button>`}
                      ${caps().canDeleteContent ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-work-act="delete" data-work-id="${esc(w.id)}">🗑️</button>` : ""}
                    </div>
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">未匹配到作品记录</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderCommentsTable() {
    const typeLabel = (t) => (t === "work_comment" ? "🖼️ 作品评论" : t === "asset_comment" ? "🎨 画风/图型评论" : "💬 论坛回复");
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-comments-status">
              <option value="all" ${state.filters.commentsStatus === "all" ? "selected" : ""}>全部状态</option>
              <option value="published" ${state.filters.commentsStatus === "published" ? "selected" : ""}>正常展示 (published)</option>
              <option value="hidden" ${state.filters.commentsStatus === "hidden" ? "selected" : ""}>已隐藏 (hidden)</option>
            </select>
            <input class="adm-input" id="flt-comments-q" value="${esc(state.filters.commentsQ)}" placeholder="搜索作品/画风/图型评论或用户名…" style="width:260px;" />
            <button class="adm-btn" id="btn-comments-search">🔍 筛选</button>
          </div>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>评论归属类型</th><th>所属作品 / 画风 / 图型 / 话题</th><th>作者</th><th>评论正文</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              ${state.data.comments.map((c) => `
                <tr>
                  <td><span class="adm-badge ${c.commentType === "asset_comment" ? "exclusive" : "neutral"}">${typeLabel(c.commentType)}</span></td>
                  <td style="max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(c.parentTitle)}</td>
                  <td>@${esc(c.authorUsername)}</td>
                  <td style="max-width:340px;">${esc(c.text)}</td>
                  <td><span class="adm-badge ${esc(c.status)}">${esc(c.status)}</span></td>
                  <td>
                    <div class="adm-actions">
                      ${c.status === "published"
                        ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-cmt-act="hide" data-cmt-type="${esc(c.commentType)}" data-cmt-id="${esc(c.id)}">隐藏</button>`
                        : `<button class="adm-btn adm-btn-sm adm-btn-jade" data-cmt-act="publish" data-cmt-type="${esc(c.commentType)}" data-cmt-id="${esc(c.id)}">恢复</button>`}
                      ${caps().canDeleteContent ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-cmt-act="delete" data-cmt-type="${esc(c.commentType)}" data-cmt-id="${esc(c.id)}">删除</button>` : ""}
                    </div>
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:20px;">暂无评论数据</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderCatalogSection() {
    const sub = state.subtab.catalog;
    return `
      <div class="adm-subtabs">
        <button class="adm-subtab ${sub === "assets_list" ? "active" : ""}" data-subtab="catalog:assets_list">🔒 专属黑盒·共创·官方覆盖 (${state.data.catalog.length})</button>
        <button class="adm-subtab ${sub === "presets_list" ? "active" : ""}" data-subtab="catalog:presets_list">🎛️ 创作台官方预设工作流</button>
      </div>
      ${sub === "presets_list" ? renderPresetsPanel() : renderCatalogAssetsPanel()}
    `;
  }

  function renderCatalogAssetsPanel() {
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-cat-source">
              <option value="all" ${state.filters.catSource === "all" ? "selected" : ""}>全部来源</option>
              <option value="exclusive" ${state.filters.catSource === "exclusive" ? "selected" : ""}>🔒 官网独占黑盒 (FX/LX)</option>
              <option value="community" ${state.filters.catSource === "community" ? "selected" : ""}>🌱 社区共创 (USR-S/L)</option>
              <option value="official_override" ${state.filters.catSource === "official_override" ? "selected" : ""}>📌 官方目录覆盖增强</option>
            </select>
            <select class="adm-select" id="flt-cat-kind">
              <option value="all" ${state.filters.catKind === "all" ? "selected" : ""}>画风 + 图型</option>
              <option value="style" ${state.filters.catKind === "style" ? "selected" : ""}>仅画风 (style)</option>
              <option value="layout" ${state.filters.catKind === "layout" ? "selected" : ""}>仅图型 (layout)</option>
            </select>
            <input class="adm-input" id="flt-cat-q" value="${esc(state.filters.catQ)}" placeholder="搜索编号 FX-001 / USR-S01 / 名称…" style="width:220px;" />
            <button class="adm-btn" id="btn-cat-search">🔍 筛选</button>
          </div>
          ${caps().canViewBlackbox
            ? `<div style="display:flex;gap:8px;">
                <button class="adm-btn adm-btn-primary" id="btn-new-exclusive">+ 新建专属黑盒 FX/LX</button>
                <button class="adm-btn" id="btn-new-override">+ 官方目录覆盖项</button>
              </div>`
            : `<span class="adm-badge neutral">当前角色仅可审核社区共创 USR-*，黑盒底层仅限超管</span>`}
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead>
              <tr>
                <th>样张</th>
                <th>编号与名称</th>
                <th>来源 / 分类</th>
                <th>解锁门槛</th>
                <th>云端黑盒保护状态</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${state.data.catalog.map((a) => {
                const canEdit = caps().canViewBlackbox || a.sourceType === "community";
                return `
                  <tr>
                    <td><img class="adm-thumb" src="${esc(a.image)}" alt="${esc(a.code)}" loading="lazy" /></td>
                    <td>
                      <div><code><strong>${esc(a.code)}</strong></code> · <strong>${esc(a.name)}</strong></div>
                      <div style="font-size:12px;color:var(--adm-ink-muted);margin-top:3px;">@${esc(a.authorUsername)} · ${esc(a.kind === "layout" ? "图型框架" : "画风指令")}</div>
                    </td>
                    <td>
                      <span class="adm-badge ${a.sourceType === "exclusive" ? "exclusive" : "neutral"}">${esc(a.sourceType)}</span>
                      <div style="font-size:12px;color:var(--adm-ink-soft);margin-top:3px;">${esc(a.group)}</div>
                    </td>
                    <td>${a.unlockCost > 0 ? `<strong style="color:var(--adm-vermilion);">${a.unlockCost}✦</strong>` : `<span style="color:var(--adm-jade);">登录免费</span>`}</td>
                    <td style="max-width:290px;">
                      ${a.hasSecretBlackbox
                        ? `<div style="font-size:12px;color:var(--adm-vermilion);font-weight:700;">🔒 云端黑盒注入已激活（前端零泄露）</div>
                           <div style="font-size:11.5px;color:var(--adm-ink-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(a.secretBlackboxPrompt)}</div>`
                        : `<div style="font-size:12px;color:var(--adm-ink-soft);">明文/标准定义：${esc((a.definition || a.description || "").slice(0, 46))}</div>`}
                    </td>
                    <td><span class="adm-badge ${esc(a.status)}">${esc(a.status)}</span></td>
                    <td>
                      <div class="adm-actions">
                        <button class="adm-btn adm-btn-sm" data-cat-edit="${esc(a.code)}" ${canEdit ? "" : "disabled"}>✏️ 编辑</button>
                        ${caps().canDeleteContent ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-cat-del="${esc(a.code)}">🗑️ 删除</button>` : ""}
                      </div>
                    </td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderPresetsPanel() {
    return `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <h3 class="adm-panel-title">🎛️ 无限画布创作台官方场景预设工作流</h3>
          ${caps().canViewBlackbox ? `<button class="adm-btn adm-btn-primary" id="btn-new-preset">+ 新增官方预设</button>` : ""}
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>排序</th><th>预设标题</th><th>蓝图引擎 (blueprint)</th><th>场景角标</th><th>场景说明</th><th>启用状态</th><th>操作</th></tr></thead>
            <tbody>
              ${state.data.presets.map((p) => `
                <tr>
                  <td><strong>#${p.sortOrder}</strong></td>
                  <td><strong>${esc(p.title)}</strong></td>
                  <td><code>${esc(p.blueprint)}</code></td>
                  <td><span class="adm-badge exclusive">${esc(p.scenarioBadge)}</span></td>
                  <td style="max-width:320px;color:var(--adm-ink-soft);">${esc(p.scenarioDesc)}</td>
                  <td><span class="adm-badge ${p.enabled ? "published" : "hidden"}">${p.enabled ? "启用中" : "已停用"}</span></td>
                  <td>
                    <button class="adm-btn adm-btn-sm" data-preset-edit="${esc(p.id)}" ${caps().canViewBlackbox ? "" : "disabled"}>✏️ 编辑预设</button>
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderGovernanceSection() {
    const sub = state.subtab.governance;
    const openCnt = state.data.reports.filter((r) => r.status === "open").length;
    const showModeratorsTab = effRole() === "admin" || effRole() === "operator";
    return `
      <div class="adm-subtabs">
        <button class="adm-subtab ${sub === "reports_list" ? "active" : ""}" data-subtab="governance:reports_list">🚩 举报工单裁定 ${openCnt ? `(${openCnt} 待审)` : ""}</button>
        <button class="adm-subtab ${sub === "topics_list" ? "active" : ""}" data-subtab="governance:topics_list">💬 论坛帖子${caps().canArbitrateBounty ? "与悬赏仲裁" : "安全巡检"}</button>
        ${showModeratorsTab
          ? `<button class="adm-subtab ${sub === "moderators_list" ? "active" : ""}" data-subtab="governance:moderators_list">🛡️ 论坛版主团队设置</button>`
          : ""}
      </div>
      ${sub === "topics_list"
        ? renderTopicsGovernancePanel()
        : sub === "moderators_list"
        ? renderForumModeratorsPanel()
        : renderReportsPanel()}
    `;
  }

  function renderForumModeratorsPanel() {
    const canManage = caps().canManageModerators;
    return `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <div>
            <h3 class="adm-panel-title">🛡️ 论坛 4 大交流板块 + 全区总版主任命管理</h3>
            <div style="font-size:12px;color:var(--adm-ink-muted);margin-top:3px;">
              被任命的创作者将在论坛前台亮出「🛡️ 版主」专属徽章，并解锁属于其所辖板块的「论坛板块专属版务工作台」。
            </div>
          </div>
          ${canManage ? `<button class="adm-btn adm-btn-primary" id="btn-appoint-mod">+ 任命新论坛版主</button>` : `<span class="adm-badge neutral">仅超级管理员可变更版主任命</span>`}
        </div>

        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>版主账号</th><th>管辖论坛板块</th><th>版主头衔</th><th>任命备注</th><th>任命人 / 时间</th><th>操作</th></tr></thead>
            <tbody>
              ${state.data.forumModerators.map((m) => `
                <tr>
                  <td>
                    <div style="font-weight:700;">${esc(m.displayName)} <span style="color:var(--adm-ink-muted);">(@${esc(m.username)})</span></div>
                    <div style="font-size:11.5px;color:var(--adm-ink-muted);">系统角色：${esc(m.role)}</div>
                  </td>
                  <td><span class="adm-badge ${m.category === "all" ? "admin" : "exclusive"}">${esc(m.categoryLabel)}</span></td>
                  <td><strong>🛡️ ${esc(m.title)}</strong></td>
                  <td style="color:var(--adm-ink-soft);font-size:12.5px;">${esc(m.note || "日常板块巡查与加精引导")}</td>
                  <td style="font-size:12px;color:var(--adm-ink-muted);">@${esc(m.appointedBy)} · ${esc(m.createdAt)}</td>
                  <td>
                    ${canManage
                      ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-revoke-mod="${m.id}">卸任版主</button>`
                      : `<span style="color:var(--adm-ink-muted);font-size:12px;">只读</span>`}
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">尚未任命任何板块版主</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderReportsPanel() {
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-reports-status">
              <option value="all" ${state.filters.reportsStatus === "all" ? "selected" : ""}>全部工单</option>
              <option value="open" ${state.filters.reportsStatus === "open" ? "selected" : ""}>待处理 (open)</option>
              <option value="confirmed" ${state.filters.reportsStatus === "confirmed" ? "selected" : ""}>已裁定违规 (confirmed)</option>
              <option value="dismissed" ${state.filters.reportsStatus === "dismissed" ? "selected" : ""}>已驳回恢复 (dismissed)</option>
            </select>
            <button class="adm-btn" id="btn-reports-refresh">🔄 刷新队列</button>
          </div>
          <div style="font-size:12px;color:var(--adm-ink-muted);">自动风控：同一内容累计举报达阈值将自动保护性暂停 (paused)，驳回举报可一键恢复展示</div>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>工单#</th><th>被举报目标</th><th>举报理由与补充说明</th><th>举报人</th><th>状态 / 处理人</th><th>裁定操作</th></tr></thead>
            <tbody>
              ${state.data.reports.map((r) => `
                <tr>
                  <td><strong>#${r.id}</strong></td>
                  <td>
                    <span class="adm-badge neutral">${esc(r.targetType)}</span>
                    <div style="font-weight:700;margin-top:3px;">${esc(r.targetTitle || r.targetId)}</div>
                    <div style="font-size:11.5px;color:var(--adm-ink-muted);">ID: ${esc(r.targetId)}</div>
                  </td>
                  <td style="max-width:340px;">
                    <div style="font-weight:700;color:var(--adm-vermilion);">${esc(r.reason)}</div>
                    <div style="font-size:12px;color:var(--adm-ink-soft);margin-top:2px;">${esc(r.detail || "—")}</div>
                  </td>
                  <td>@${esc(r.reporterUsername)}<div style="font-size:11.5px;color:var(--adm-ink-muted);">${esc(r.createdAt)}</div></td>
                  <td>
                    <span class="adm-badge ${esc(r.status)}">${esc(r.status)}</span>
                    ${r.resolvedBy ? `<div style="font-size:11.5px;color:var(--adm-ink-muted);margin-top:3px;">@${esc(r.resolvedBy)}: ${esc(r.resolutionNote)}</div>` : ""}
                  </td>
                  <td>
                    ${r.status === "open"
                      ? `<div class="adm-actions">
                          <button class="adm-btn adm-btn-sm adm-btn-danger" data-rep-resolve="confirmed" data-rep-id="${r.id}">✅ 属实并下架</button>
                          <button class="adm-btn adm-btn-sm adm-btn-jade" data-rep-resolve="dismissed" data-rep-id="${r.id}">↩ 驳回并恢复</button>
                        </div>`
                      : `<span style="font-size:12px;color:var(--adm-ink-muted);">已结案</span>`}
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">暂无举报工单</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderTopicsGovernancePanel() {
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-topics-status">
              <option value="all" ${state.filters.topicsStatus === "all" ? "selected" : ""}>全部状态</option>
              <option value="published" ${state.filters.topicsStatus === "published" ? "selected" : ""}>已发布</option>
              <option value="paused" ${state.filters.topicsStatus === "paused" ? "selected" : ""}>暂停待审</option>
              <option value="hidden" ${state.filters.topicsStatus === "hidden" ? "selected" : ""}>已隐藏</option>
            </select>
            <label style="display:inline-flex;align-items:center;gap:5px;font-size:13px;cursor:pointer;">
              <input type="checkbox" id="flt-topics-bounty" ${state.filters.topicsBountyOnly ? "checked" : ""} />
              仅看积分悬赏帖
            </label>
            <input class="adm-input" id="flt-topics-q" value="${esc(state.filters.topicsQ)}" placeholder="搜索帖子标题 / 楼主…" style="width:220px;" />
            <button class="adm-btn" id="btn-topics-search">🔍 筛选</button>
          </div>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>话题标题与板块</th><th>楼主</th><th>付费锁帖 / 悬赏状态</th><th>回复数</th><th>状态</th><th>治理${caps().canArbitrateBounty ? "与悬赏仲裁" : "操作"}</th></tr></thead>
            <tbody>
              ${state.data.topics.map((t) => {
                const isOpenBounty = t.bounty > 0 && (t.bountyStatus === "open" || t.bountyStatus === "escrowed");
                return `
                  <tr>
                    <td style="max-width:340px;">
                      <div style="font-weight:700;">
                        ${t.pinned ? `<span class="adm-badge exclusive">📌 置顶</span> ` : ""}
                        ${t.featured ? `<span class="adm-badge published">🌟 精华</span> ` : ""}
                        ${esc(t.title)}
                      </div>
                      <div style="font-size:12px;color:var(--adm-ink-muted);margin-top:3px;">${esc(t.categoryLabel)} · ID: ${esc(t.id)}</div>
                    </td>
                    <td>${esc(t.authorName)}<div style="font-size:12px;color:var(--adm-ink-muted);">@${esc(t.authorUsername)}</div></td>
                    <td>
                      ${t.price > 0 ? `<div>🔒 付费解锁 <strong>${t.price}✦</strong></div>` : ""}
                      ${t.bounty > 0
                        ? `<div>🎯 悬赏 <strong>${t.bounty}✦</strong> · <span class="adm-badge ${isOpenBounty ? "open" : "settled"}">${esc(t.bountyStatus)}</span></div>`
                        : `<span style="color:var(--adm-ink-muted);font-size:12px;">普通交流帖</span>`}
                    </td>
                    <td>💬 ${t.repliesCount}</td>
                    <td><span class="adm-badge ${esc(t.status)}">${esc(t.status)}</span></td>
                    <td>
                      <div class="adm-actions">
                        <button class="adm-btn adm-btn-sm" data-topic-act="${t.pinned ? "unpin" : "pin"}" data-topic-id="${esc(t.id)}">${t.pinned ? "取消置顶" : "📌 置顶"}</button>
                        <button class="adm-btn adm-btn-sm" data-topic-act="${t.featured ? "unfeature" : "feature"}" data-topic-id="${esc(t.id)}">${t.featured ? "取消精华" : "🌟 精华"}</button>
                        ${t.status === "deleted"
                          ? `<span class="adm-badge deleted">已删除，不可恢复</span>`
                          : t.status === "published"
                          ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-topic-act="hide" data-topic-id="${esc(t.id)}">🚫 隐藏</button>`
                          : `<button class="adm-btn adm-btn-sm adm-btn-jade" data-topic-act="publish" data-topic-id="${esc(t.id)}">✅ 恢复</button>`}
                        ${isOpenBounty && caps().canArbitrateBounty
                          ? `<button class="adm-btn adm-btn-sm adm-btn-primary" data-topic-bounty="${esc(t.id)}">⚖️ 仲裁悬赏</button>`
                          : ""}
                      </div>
                    </td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderUsersSection() {
    const sub = state.subtab.users;
    const c = caps();
    return `
      <div class="adm-subtabs">
        <button class="adm-subtab ${sub === "users_list" ? "active" : ""}" data-subtab="users:users_list">👤 用户账号·角色·版主·状态管理</button>
        ${c.canRefundUnlocks ? `<button class="adm-subtab ${sub === "unlocks_list" ? "active" : ""}" data-subtab="users:unlocks_list">🧾 付费解锁订单与退款</button>` : ""}
        ${c.canManageRedeemCodes ? `<button class="adm-subtab ${sub === "redeem_list" ? "active" : ""}" data-subtab="users:redeem_list">🎟️ 积分兑换码管理</button>` : ""}
        ${c.canImportDiscourse ? `<button class="adm-subtab ${sub === "discourse_import" ? "active" : ""}" data-subtab="users:discourse_import">📥 Discourse 老用户迁移</button>` : ""}
      </div>
      ${sub === "unlocks_list" && c.canRefundUnlocks
        ? renderUnlocksPanel()
        : sub === "redeem_list" && c.canManageRedeemCodes
        ? renderRedeemCodesPanel()
        : sub === "discourse_import" && c.canImportDiscourse
        ? renderDiscourseImportPanel()
        : renderUsersTablePanel()}
    `;
  }

  function renderUsersTablePanel() {
    const c = caps();
    const roleLabelMap = {
      admin: "👑 超管 (admin)",
      operator: "🧭 运营审查 (operator)",
      reviewer: "🧭 运营审查 (operator)",
      user: "🎨 创作者 (user)",
    };
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-users-role">
              <option value="all" ${state.filters.usersRole === "all" ? "selected" : ""}>全部系统角色</option>
              <option value="admin" ${state.filters.usersRole === "admin" ? "selected" : ""}>👑 超级管理员 (admin)</option>
              <option value="operator" ${state.filters.usersRole === "operator" ? "selected" : ""}>🧭 运营审查员 (operator)</option>
              <option value="user" ${state.filters.usersRole === "user" ? "selected" : ""}>🎨 创作者用户 (user)</option>
            </select>
            <select class="adm-select" id="flt-users-status">
              <option value="all" ${state.filters.usersStatus === "all" ? "selected" : ""}>全部状态</option>
              <option value="active" ${state.filters.usersStatus === "active" ? "selected" : ""}>正常活跃 (active)</option>
              <option value="frozen" ${state.filters.usersStatus === "frozen" ? "selected" : ""}>已冻结封禁 (frozen)</option>
            </select>
            <input class="adm-input" id="flt-users-q" value="${esc(state.filters.usersQ)}" placeholder="搜索用户名 / 昵称 / 邮箱 / 邀请码…" style="width:240px;" />
            <button class="adm-btn" id="btn-users-search">🔍 搜索</button>
          </div>
          ${c.canCreateUser
            ? `<button class="adm-btn adm-btn-primary" id="btn-new-user">+ 新建用户账号</button>`
            : `<span class="adm-badge neutral">${effRole() === "operator" ? "运营模式：可授勋荣誉与重置额度" : "审核风控模式：仅限冻结违规普通用户"}</span>`}
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead>
              <tr>
                <th>ID / 账号信息</th>
                <th>系统角色 & 论坛版主职务</th>
                <th>共创荣誉等级</th>
                <th>积分钱包 / 今日免费额度</th>
                <th>状态 / 会话</th>
                <th>用户管理操作</th>
              </tr>
            </thead>
            <tbody>
              ${state.data.users.map((u) => {
                const modBadges = (u.moderatedBoards || [])
                  .map((m) => `<span class="adm-badge exclusive" style="margin-top:3px;display:inline-block;">🛡️ ${esc(m.shortLabel)}·${esc(m.title)}</span>`)
                  .join(" ");
                return `
                  <tr>
                    <td>
                      <div style="font-weight:700;">${esc(u.displayName)} <span style="color:var(--adm-ink-muted);font-weight:400;">(@${esc(u.username)})</span></div>
                      <div style="font-size:11.5px;color:var(--adm-ink-muted);">#${u.id} · ${esc(u.email || "未填邮箱")} ${u.discourseMigrated ? `· <span class="adm-badge neutral">老站迁移</span>` : ""}</div>
                    </td>
                    <td>
                      <div><span class="adm-badge ${u.role === "admin" ? "admin" : u.role === "operator" ? "exclusive" : u.role === "reviewer" ? "open" : "neutral"}">${esc(roleLabelMap[u.role] || u.role)}</span></div>
                      ${modBadges ? `<div>${modBadges}</div>` : ""}
                    </td>
                    <td>
                      <div>${esc(u.honorBadge)} ${u.honorOverride !== null && u.honorOverride !== undefined ? `<span class="adm-badge exclusive">人工授勋</span>` : ""}</div>
                      <div style="font-size:11.5px;color:var(--adm-ink-muted);">已发布内容：${u.publishedCount}</div>
                    </td>
                    <td>
                      <div><strong style="color:var(--adm-vermilion);">${u.credits}✦</strong> ${u.walletLocked ? `<span class="adm-badge hidden">钱包已锁</span>` : ""}</div>
                      <div style="font-size:11.5px;color:var(--adm-ink-muted);">今日免费生图剩余：${u.freeQuotaRemaining}/${u.freeQuotaMax}</div>
                    </td>
                    <td>
                      <span class="adm-badge ${esc(u.status)}">${esc(u.status)}</span>
                      <div style="font-size:11.5px;color:var(--adm-ink-muted);margin-top:2px;">在线 ${u.activeSessions} 会话</div>
                    </td>
                    <td>
                      <div class="adm-actions">
                        <button class="adm-btn adm-btn-sm" data-user-detail="${u.id}">📋 账号管理</button>
                        ${c.canManageModerators ? `<button class="adm-btn adm-btn-sm" data-user-mod-appoint="${esc(u.username)}">🛡️ 设版主</button>` : ""}
                        ${c.canAdjustCredits ? `<button class="adm-btn adm-btn-sm adm-btn-primary" data-user-credit="${u.id}" data-user-name="${esc(u.username)}">± 调账</button>` : ""}
                        ${c.canResetFreeQuota ? `<button class="adm-btn adm-btn-sm" data-user-quota="${u.id}">↺ 重置额度</button>` : ""}
                      </div>
                    </td>
                  </tr>
                `;
              }).join("") || `<tr><td colspan="6" style="text-align:center;color:var(--adm-ink-muted);padding:24px;">未匹配到用户账号</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderUnlocksPanel() {
    return `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <h3 class="adm-panel-title">🧾 付费解锁订单与一键退款追回（80% 创作者分成自动联动）</h3>
          <select class="adm-select" id="flt-unlocks-status">
            <option value="all" ${state.filters.unlocksStatus === "all" ? "selected" : ""}>全部订单</option>
            <option value="settled" ${state.filters.unlocksStatus === "settled" ? "selected" : ""}>已结算 (settled)</option>
            <option value="refunded" ${state.filters.unlocksStatus === "refunded" ? "selected" : ""}>已退款 (refunded)</option>
          </select>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>订单#</th><th>买家</th><th>解锁对象</th><th>作者</th><th>支付 / 作者分成 / 平台回收</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              ${state.data.unlocks.map((ul) => `
                <tr>
                  <td><strong>#${ul.id}</strong></td>
                  <td>@${esc(ul.buyerUsername)}</td>
                  <td><span class="adm-badge neutral">${esc(ul.targetType)}</span> <code>${esc(ul.targetId)}</code></td>
                  <td>@${esc(ul.authorUsername || "official")}</td>
                  <td>支付 <strong>${ul.cost}✦</strong> · 分成 <span style="color:var(--adm-jade);">+${ul.authorShare}✦</span> · 回收 ${ul.platformFee}✦</td>
                  <td>
                    <span class="adm-badge ${esc(ul.status)}">${esc(ul.status)}</span>
                    ${ul.refundReason ? `<div style="font-size:11.5px;color:var(--adm-ink-muted);">${esc(ul.refundReason)}</div>` : ""}
                  </td>
                  <td>
                    ${ul.status === "settled" && caps().canRefundUnlocks
                      ? `<button class="adm-btn adm-btn-sm adm-btn-danger" data-unlock-refund="${ul.id}">↩ 退款并追回分成</button>`
                      : `<span style="font-size:12px;color:var(--adm-ink-muted);">—</span>`}
                  </td>
                </tr>
              `).join("") || `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--adm-ink-muted);">暂无付费解锁订单</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderRedeemCodesPanel() {
    const canManage = caps().canManageRedeemCodes;
    return `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <h3 class="adm-panel-title">🎟️ 运营活动积分兑换码管理</h3>
          ${canManage ? `<button class="adm-btn adm-btn-primary" id="btn-new-redeem">+ 生成新兑换码</button>` : ""}
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>兑换码</th><th>面额</th><th>已领 / 上限</th><th>活动备注</th><th>创建人</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              ${state.data.redeemCodes.map((rc) => `
                <tr>
                  <td><code style="font-size:13.5px;font-weight:800;color:var(--adm-vermilion);">${esc(rc.code)}</code></td>
                  <td><strong>+${rc.credits}✦</strong></td>
                  <td>${rc.usedCount} / ${rc.maxUses}</td>
                  <td>${esc(rc.note)}</td>
                  <td>@${esc(rc.createdBy || "system")}</td>
                  <td><span class="adm-badge ${rc.active ? "published" : "hidden"}">${rc.active ? "生效中" : "已停用"}</span></td>
                  <td>
                    ${canManage
                      ? `<button class="adm-btn adm-btn-sm" data-redeem-toggle="${esc(rc.code)}" data-redeem-next="${rc.active ? "0" : "1"}">${rc.active ? "⏸ 停用" : "✅ 启用"}</button>`
                      : "—"}
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderDiscourseImportPanel() {
    const sampleJson = JSON.stringify(
      [
        { id: 1081, username: "old_ink_master", name: "老站水墨画师", email: "ink@handraw-style.com", admin: false },
        { id: 1082, username: "xhs_growth_cat", name: "阿橘做图文", email: "ju@handraw-style.com", admin: false },
      ],
      null,
      2
    );
    return `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <h3 class="adm-panel-title">📥 原 Discourse 社区注册用户一键无缝迁移（幂等防重 + PBKDF2 密码兼容）</h3>
        </div>
        <p style="font-size:13px;color:var(--adm-ink-soft);margin-top:0;">
          支持粘贴原站导出的 JSON 数组或 CSV 文本（字段支持 <code>id, username, name, email, password_hash, salt, admin, moderator</code>）。已存在的用户名/邮箱将自动幂等跳过，新迁移老用户自动发放激活礼金。
        </p>
        <div class="adm-field" style="max-width:260px;">
          <label>每位迁移老用户发放欢迎积分 (✦)</label>
          <input class="adm-input" type="number" id="imp-disc-bonus" value="50" min="0" max="1000" />
        </div>
        <div class="adm-field">
          <label>Discourse 导出数据 (JSON 或 CSV)</label>
          <textarea class="adm-textarea" id="imp-disc-payload" style="min-height:170px;font-family:monospace;">${esc(sampleJson)}</textarea>
        </div>
        <button class="adm-btn adm-btn-primary" id="btn-run-disc-import" ${caps().canImportDiscourse ? "" : "disabled"}>🚀 立即执行增量迁移导入</button>
      </div>
    `;
  }

  function renderGatewaySection() {
    const gw = state.data.gateway;
    if (!gw) return `<div class="adm-panel">正在读取生图网关状态…</div>`;
    const g = gw.gateway;
    const st = gw.stats;
    const p = gw.probe;
    return `
      <div class="adm-kpi-grid">
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🔌 网关上游地址</div>
          <div class="adm-kpi-val" style="font-size:17px;word-break:break-all;">${esc(g.baseUrl)}</div>
          <div class="adm-kpi-foot">密钥掩码：<code>${esc(g.apiKeyMasked)}</code> · 模型：<code>${esc(g.model)}</code></div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">📡 实时连通性探针</div>
          <div class="adm-kpi-val ${p.probed ? (p.reachable ? "jade" : "vermilion") : ""}" style="font-size:19px;">
            ${p.probed ? (p.reachable ? "✅ 在线正常" : "⚠️ 离线回退") : "待探测"}
          </div>
          <div class="adm-kpi-foot">${esc(p.detail)}</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🎨 累计生图任务</div>
          <div class="adm-kpi-val">${st.total}</div>
          <div class="adm-kpi-foot">云端直出 ${st.live} · 样张演示 ${st.sample} · 成功 ${st.success}</div>
        </div>
        <div class="adm-kpi-card">
          <div class="adm-kpi-label">🛡️ 失败自动退费保护</div>
          <div class="adm-kpi-val jade">${st.refunded} 单已退</div>
          <div class="adm-kpi-foot">累计积分消耗：${st.totalCreditsSpent}✦（网关报错 100% 原路秒退）</div>
        </div>
      </div>

      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <select class="adm-select" id="flt-gen-status">
              <option value="all" ${state.filters.genStatus === "all" ? "selected" : ""}>全部任务状态</option>
              <option value="success" ${state.filters.genStatus === "success" ? "selected" : ""}>成功 (success)</option>
              <option value="running" ${state.filters.genStatus === "running" ? "selected" : ""}>生成中 (running)</option>
              <option value="refunded" ${state.filters.genStatus === "refunded" ? "selected" : ""}>失败已退费 (refunded)</option>
            </select>
            <select class="adm-select" id="flt-gen-engine">
              <option value="all" ${state.filters.genEngine === "all" ? "selected" : ""}>全部引擎</option>
              <option value="live" ${state.filters.genEngine === "live" ? "selected" : ""}>云端直出 (live)</option>
              <option value="sample" ${state.filters.genEngine === "sample" ? "selected" : ""}>样张演示 (sample)</option>
            </select>
            <input class="adm-input" id="flt-gen-q" value="${esc(state.filters.genQ)}" placeholder="搜索用户 / 配方编号 / Prompt…" style="width:230px;" />
            <button class="adm-btn" id="btn-gen-search">🔍 筛选</button>
          </div>
          <button class="adm-btn adm-btn-primary" id="btn-probe-gateway">📡 立即探测网关连通性</button>
        </div>

        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>任务 ID</th><th>用户</th><th>引擎 / 扣费方式</th><th>挂载配方</th><th>Prompt 摘要</th><th>状态</th><th>时间</th></tr></thead>
            <tbody>
              ${state.data.generations.map((it) => `
                <tr>
                  <td><code>${esc(it.id)}</code></td>
                  <td>@${esc(it.username)}</td>
                  <td>
                    <span class="adm-badge ${it.engine === "live" ? "exclusive" : "neutral"}">${esc(it.engine)}</span>
                    <span style="font-size:12px;color:var(--adm-ink-soft);margin-left:4px;">${it.creditsSpent > 0 ? `-${it.creditsSpent}✦` : esc(it.costType)}</span>
                  </td>
                  <td><code>${esc(it.recipeSummary || it.mode)}</code></td>
                  <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(it.prompt)}">${esc(it.prompt)}</td>
                  <td>
                    <span class="adm-badge ${esc(it.status)}">${esc(it.status)}</span>
                    ${it.errorMsg ? `<div style="font-size:11px;color:var(--adm-crimson);">${esc(it.errorMsg)}</div>` : ""}
                  </td>
                  <td style="color:var(--adm-ink-muted);">${esc(it.createdAt)}</td>
                </tr>
              `).join("") || `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--adm-ink-muted);">暂无生图任务日志</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderSettingsSection() {
    const sub = state.subtab.settings;
    if (!caps().canViewAuditLogs) {
      return renderSettingsConfigPanel();
    }
    return `
      <div class="adm-subtabs">
        <button class="adm-subtab ${sub === "config_form" ? "active" : ""}" data-subtab="settings:config_form">⚙️ 全站运营与经济规则配置</button>
        <button class="adm-subtab ${sub === "audit_list" ? "active" : ""}" data-subtab="settings:audit_list">📜 管理操作审计记录</button>
      </div>
      ${sub === "audit_list" ? renderAuditLogsPanel() : renderSettingsConfigPanel()}
    `;
  }

  function renderSettingsConfigPanel() {
    const s = state.data.settings || {};
    const ann = s.announcement || {};
    const eco = s.economy || {};
    const mod = s.moderation || {};
    const canAnn = caps().canEditAnnouncement;
    const canSys = caps().canEditSystemSettings;

    return `
      <div class="${canSys ? "adm-grid-2" : ""}">
        <div class="adm-panel">
          <div class="adm-panel-head">
            <h3 class="adm-panel-title">📢 全站顶部运营公告条配置</h3>
            <span class="adm-badge published">超管 & 运营管理员可编辑</span>
          </div>
          <div class="adm-field">
            <label><input type="checkbox" id="cfg-ann-enabled" ${ann.enabled ? "checked" : ""} ${canAnn ? "" : "disabled"} /> 启用全站顶部公告横幅</label>
          </div>
          <div class="adm-form-grid">
            <div class="adm-field">
              <label>公告角标 (Badge)</label>
              <input class="adm-input" id="cfg-ann-badge" value="${esc(ann.badge || "")}" ${canAnn ? "" : "disabled"} />
            </div>
            <div class="adm-field">
              <label>行动按钮文案 (CTA)</label>
              <input class="adm-input" id="cfg-ann-cta" value="${esc(ann.cta_label || "")}" ${canAnn ? "" : "disabled"} />
            </div>
          </div>
          <div class="adm-field">
            <label>公告正文内容</label>
            <textarea class="adm-textarea" id="cfg-ann-text" ${canAnn ? "" : "disabled"}>${esc(ann.text || "")}</textarea>
          </div>
          <button class="adm-btn adm-btn-primary" id="btn-save-ann" ${canAnn ? "" : "disabled"}>💾 保存公告条配置</button>
        </div>

        ${canSys ? `
        <div class="adm-panel">
          <div class="adm-panel-head">
            <h3 class="adm-panel-title">🛡️ 审核与风控安全策略</h3>
          </div>
          <div class="adm-field">
            <label>累计待处理举报自动触发暂停阈值 (次)</label>
            <input class="adm-input" type="number" id="cfg-mod-threshold" value="${esc(mod.auto_pause_report_threshold ?? 3)}" min="1" max="20" />
          </div>
          <div class="adm-field" style="margin-top:10px;">
            <label style="display:flex;align-items:center;gap:6px;">
              <input type="checkbox" id="cfg-mod-admin-self" ${mod.allow_self_review_for_admin ? "checked" : ""} />
              允许超级管理员（admin）审核本人发布内容（注：reviewer 审核员永久禁止自审）
            </label>
          </div>
          <button class="adm-btn adm-btn-primary" id="btn-save-mod">💾 保存风控策略</button>
        </div>` : ""}
      </div>

      ${canSys ? `
      <div class="adm-panel">
        <div class="adm-panel-head">
          <h3 class="adm-panel-title">✦ 积分经济闭环核心参数（仅超级管理员可调）</h3>
        </div>
        <div class="adm-form-grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));">
          <div class="adm-field"><label>新用户注册欢迎礼 (✦)</label><input class="adm-input" type="number" id="eco-welcome" value="${esc(eco.welcome_credits ?? 20)}" /></div>
          <div class="adm-field"><label>每日签到奖励 (✦)</label><input class="adm-input" type="number" id="eco-checkin" value="${esc(eco.daily_checkin_credits ?? 5)}" /></div>
          <div class="adm-field"><label>晒作品基础奖励 (✦)</label><input class="adm-input" type="number" id="eco-work" value="${esc(eco.work_publish_credits ?? 5)}" /></div>
          <div class="adm-field"><label>荒地开荒额外加奖 (✦)</label><input class="adm-input" type="number" id="eco-pioneer" value="${esc(eco.pioneer_bonus_credits ?? 10)}" /></div>
          <div class="adm-field"><label>贡献共创画风/图型奖励 (✦)</label><input class="adm-input" type="number" id="eco-asset" value="${esc(eco.asset_publish_credits ?? 15)}" /></div>
          <div class="adm-field"><label>每日免费云端生图额度 (张)</label><input class="adm-input" type="number" id="eco-quota" value="${esc(eco.daily_free_quota ?? 3)}" /></div>
          <div class="adm-field"><label>超额单张云端生图消耗 (✦)</label><input class="adm-input" type="number" id="eco-gen-cost" value="${esc(eco.studio_credit_per_image ?? 2)}" /></div>
          <div class="adm-field"><label>付费解锁作者分成比例 (0~1)</label><input class="adm-input" type="number" step="0.05" id="eco-share" value="${esc(eco.author_share_ratio ?? 0.8)}" /></div>
        </div>
        <button class="adm-btn adm-btn-primary" id="btn-save-eco">💾 保存积分经济配置</button>
      </div>` : ""}
    `;
  }

  function renderAuditLogsPanel() {
    return `
      <div class="adm-panel">
        <div class="adm-toolbar">
          <div class="adm-filters">
            <input class="adm-input" id="flt-audit-action" value="${esc(state.filters.auditAction)}" placeholder="按动作筛选 (如 user. / moderator. / work.)" style="width:240px;" />
            <input class="adm-input" id="flt-audit-actor" value="${esc(state.filters.auditActor)}" placeholder="按操作人筛选 (如 yang0)" style="width:170px;" />
            <button class="adm-btn" id="btn-audit-search">🔍 查询审计轨迹</button>
          </div>
          <span class="adm-badge published">🔒 Append-Only 不可篡改审计存证</span>
        </div>
        <div class="adm-table-wrap">
          <table class="adm-table">
            <thead><tr><th>审计#</th><th>操作人</th><th>动作标识</th><th>目标对象</th><th>审计原因</th><th>变更快照 (JSON)</th><th>时间戳</th></tr></thead>
            <tbody>
              ${state.data.audits.map((a) => `
                <tr>
                  <td><strong>#${a.id}</strong></td>
                  <td><strong>@${esc(a.actorUsername)}</strong> <span class="adm-badge neutral">${esc(a.actorRole)}</span></td>
                  <td><code>${esc(a.action)}</code></td>
                  <td><span class="adm-badge neutral">${esc(a.targetType)}</span> <code>${esc(a.targetId)}</code></td>
                  <td>${esc(a.reason)}</td>
                  <td style="max-width:260px;font-family:monospace;font-size:11.5px;color:var(--adm-ink-soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(JSON.stringify(a.details))}">
                    ${esc(JSON.stringify(a.details))}
                  </td>
                  <td style="color:var(--adm-ink-muted);white-space:nowrap;">${esc(a.createdAt)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderMainConsole() {
    const root = document.getElementById("admin-root");
    const modules = getActiveModules();
    const activeMod = modules.find((m) => m.id === state.module) || modules[0];
    const prof = state.profile || {};
    const r = effRole();
    const openReportsBadge =
      r === "moderator"
        ? (state.data.modConsole ? state.data.modConsole.kpis.openReports : 0)
        : (state.data.dashboard ? state.data.dashboard.kpis.openReportsCount : 0);

    let bodyHtml = "";
    if (state.module === "mod_overview") bodyHtml = renderModeratorOverviewSection();
    else if (state.module === "mod_topics") bodyHtml = renderModeratorTopicsSection();
    else if (state.module === "mod_replies") bodyHtml = renderModeratorRepliesSection();
    else if (state.module === "mod_reports") bodyHtml = renderModeratorReportsSection();
    else if (state.module === "dashboard") bodyHtml = renderDashboardSection();
    else if (state.module === "works") bodyHtml = renderWorksSection();
    else if (state.module === "catalog") bodyHtml = renderCatalogSection();
    else if (state.module === "governance") bodyHtml = renderGovernanceSection();
    else if (state.module === "users") bodyHtml = renderUsersSection();
    else if (state.module === "gateway") bodyHtml = renderGatewaySection();
    else if (state.module === "settings") bodyHtml = renderSettingsSection();

    root.innerHTML = `
      <div class="admin-layout role-${esc(r)}">
        <aside class="admin-sidebar">
          <div class="admin-brand">
            <span class="admin-brand-mark">${r === "moderator" ? "版" : r === "operator" ? "营" : r === "reviewer" ? "审" : "H"}</span>
            <div>
              <div class="admin-brand-title">${esc(prof.consoleTitle || "Handraw 管理后台")}</div>
              <div class="admin-brand-sub">${esc(prof.badge || "RBAC 权限隔离")}</div>
            </div>
          </div>

          <nav class="admin-nav" aria-label="角色专属模块导航">
            ${modules.map((m) => `
              <button class="admin-nav-btn ${activeMod.id === m.id ? "active" : ""}" data-nav-mod="${m.id}">
                <span>${m.icon} ${esc(m.label)}</span>
                ${(m.id === "governance" || m.id === "mod_reports") && openReportsBadge > 0
                  ? `<span class="admin-nav-badge">${openReportsBadge}</span>`
                  : ""}
              </button>
            `).join("")}
          </nav>

          <div class="admin-sidebar-footer">
            <div style="font-size:11.5px;color:var(--adm-ink-muted);padding:0 4px;">跨频道直达：</div>
            <div class="admin-channel-links">
              ${effRole() === "admin" ? `<a class="admin-channel-link" href="${esc(channelHref("forum"))}?view=curation&tab=admin">社群审核资格</a>` : ""}
              <a class="admin-channel-link" href="${esc(channelHref("main"))}">🎨 主站</a>
              <a class="admin-channel-link" href="${esc(channelHref("studio"))}">✨ 创作台</a>
              <a class="admin-channel-link" href="${esc(channelHref("forum"))}">💬 论坛</a>
            </div>
          </div>
        </aside>

        <div class="admin-main">
          <header class="admin-topbar">
            <div>
              <h1 class="admin-topbar-title">${activeMod.icon} ${esc(activeMod.label)}</h1>
              <div class="admin-topbar-sub">${esc(activeMod.desc)}</div>
            </div>
            <div class="admin-topbar-right">
              <span class="admin-operator-pill">
                ${esc(prof.badge || "")} · @${esc(state.user.username)}
              </span>
              <select data-demo-only class="adm-select" id="adm-role-switcher" title="演示沙盒切换不同管理角色查看差异化后台">
                <option value="">🎭 切换不同角色管理台…</option>
                <option value="yang0">👑 超管 yang0 (7模块全权限)</option>
                <option value="ops_lin">🧭 运营 ops_lin (5模块增长运营台)</option>
                <option value="reviewer_su">🛡️ 审核员 reviewer_su (4模块风控审核台)</option>
                <option value="momo_design">🏛️ 版主 momo_design (画风图型版务台)</option>
                <option value="pm_chen">🏛️ 版主 pm_chen (实战+工具双版务台)</option>
                <option value="su_editorial">🎨 普通创作者 su_editorial (无后台拦截页)</option>
                <option value="guest">🔒 退出登录</option>
              </select>
              <button class="adm-btn" id="adm-refresh-btn">🔄 刷新</button>
            </div>
          </header>

          <main class="admin-content">
            ${renderRoleScopeBanner()}
            ${bodyHtml}
          </main>
        </div>
      </div>
    `;

    if (!state.boot?.demoMode) root.querySelectorAll("[data-demo-only]").forEach(node => node.remove());
    bindConsoleEvents();
  }

  /* ======================== MODALS (CREATE USER, USER DETAIL, MODERATORS, CATALOG, BOUNTY) ======================== */

  function openCreateUserModal() {
    openModal(`
      <h3 style="margin:0 0 12px;">➕ 新建社区用户 / 管理团队账号</h3>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>登录用户名 (2~32位英文/数字/下划线)</label>
          <input class="adm-input" id="cu-username" placeholder="如 editor_zhou" />
        </div>
        <div class="adm-field">
          <label>显示昵称</label>
          <input class="adm-input" id="cu-dname" placeholder="如 周编辑" />
        </div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>绑定邮箱</label>
          <input class="adm-input" id="cu-email" placeholder="留空自动生成 @handraw-style.com" />
        </div>
        <div class="adm-field">
          <label>初始登录密码 (至少 6 位)</label>
          <input class="adm-input" id="cu-pass" type="text" value="handraw123" />
        </div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>系统管理角色 (RBAC)</label>
          <select class="adm-select" id="cu-role">
            <option value="user">🎨 user — 普通创作者</option>
            <option value="operator">🧭 operator — 运营审查员（5模块运审台）</option>
            <option value="admin">👑 admin — 超级管理员（7模块全权中枢）</option>
          </select>
        </div>
        <div class="adm-field">
          <label>初始发放积分 (✦)</label>
          <input class="adm-input" type="number" id="cu-credits" value="30" min="0" max="5000" />
        </div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>同步任命论坛板块版主（可选）</label>
          <select class="adm-select" id="cu-mod-board">
            <option value="">不任命论坛版主</option>
            ${FORUM_BOARD_OPTIONS.map((b) => `<option value="${esc(b.id)}">${esc(b.label)}</option>`).join("")}
          </select>
        </div>
        <div class="adm-field">
          <label>版主头衔（任命版主时生效）</label>
          <input class="adm-input" id="cu-mod-title" value="版主" placeholder="如 特邀版主 / 总版主" />
        </div>
      </div>
      <div class="adm-field">
        <label>个人简介备注</label>
        <input class="adm-input" id="cu-bio" value="Handraw 社区认证成员" />
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
        <button class="adm-btn" id="cu-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="cu-save">✅ 立即创建账号</button>
      </div>
    `);
    document.getElementById("cu-cancel").onclick = closeModal;
    document.getElementById("cu-save").onclick = async () => {
      try {
        const res = await api("/api/admin/users/create", {
          method: "POST",
          body: {
            username: document.getElementById("cu-username").value.trim(),
            displayName: document.getElementById("cu-dname").value.trim(),
            email: document.getElementById("cu-email").value.trim(),
            password: document.getElementById("cu-pass").value,
            role: document.getElementById("cu-role").value,
            initialCredits: parseInt(document.getElementById("cu-credits").value || "20", 10),
            moderatorBoard: document.getElementById("cu-mod-board").value,
            moderatorTitle: document.getElementById("cu-mod-title").value.trim(),
            bio: document.getElementById("cu-bio").value.trim(),
          },
        });
        closeModal();
        toast(`已创建新账号 @${res.username}（角色：${res.role}）`);
        state.module = "users";
        state.subtab.users = "users_list";
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  function openAssignModeratorModal(prefillUsername) {
    const candidates = state.data.moderatorCandidates.length ? state.data.moderatorCandidates : state.data.users;
    openModal(`
      <h3 style="margin:0 0 12px;">🛡️ 任命论坛板块版主</h3>
      <p style="font-size:12.5px;color:var(--adm-ink-soft);margin-top:0;">
        同一用户可兼任多个板块版主，或直接任命为「全区总版主」。版主登录后进入后台将自动呈现所辖板块专属工作台。
      </p>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>目标用户名</label>
          <input class="adm-input" id="am-username" list="am-user-datalist" value="${esc(prefillUsername || "")}" placeholder="输入或选择用户名，如 momo_design" />
          <datalist id="am-user-datalist">
            ${(candidates || []).map((u) => `<option value="${esc(u.username)}">${esc(u.displayName)} (${esc(u.role)})</option>`).join("")}
          </datalist>
        </div>
        <div class="adm-field">
          <label>管辖论坛板块</label>
          <select class="adm-select" id="am-board">
            ${FORUM_BOARD_OPTIONS.map((b) => `<option value="${esc(b.id)}">${esc(b.label)}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>外显版主徽章头衔</label>
          <input class="adm-input" id="am-title" value="版主" placeholder="如 特邀版主 / 资深版主 / 总版主" />
        </div>
        <div class="adm-field">
          <label>任命职责说明</label>
          <input class="adm-input" id="am-note" value="负责本板块精华帖评选、求调优互助引导与违规巡查" />
        </div>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
        <button class="adm-btn" id="am-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="am-save">🛡️ 确认任命版主</button>
      </div>
    `);
    document.getElementById("am-cancel").onclick = closeModal;
    document.getElementById("am-save").onclick = async () => {
      try {
        const res = await api("/api/admin/forum-moderators", {
          method: "POST",
          body: {
            username: document.getElementById("am-username").value.trim(),
            category: document.getElementById("am-board").value,
            title: document.getElementById("am-title").value.trim(),
            note: document.getElementById("am-note").value.trim(),
          },
        });
        closeModal();
        toast(`已任命 @${res.username} 为 ${res.title}`);
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  async function openUserDetailModal(userId) {
    try {
      const detail = await api(`/api/admin/users/${userId}`);
      const u = detail.user;
      const c = caps();
      const targetIsStaff = ["admin", "operator", "reviewer"].includes(u.role);
      const readOnlyStaffForNonAdmin = !c.canEditSystemRole && targetIsStaff;
      const canDeleteThisUser = c.canDeleteUser && u.username !== "yang0" && (!state.user || u.id !== state.user.id);

      openModal(`
        <h3 style="margin:0 0 12px;">👤 用户档案与分级权限管理 — @${esc(u.username)} (#${u.id})</h3>
        ${readOnlyStaffForNonAdmin
          ? `<div style="background:var(--adm-amber-soft);color:var(--adm-amber);padding:8px 12px;border-radius:8px;font-size:12px;font-weight:600;margin-bottom:12px;">
               安全保护：该账号为管理团队成员（${esc(u.role)}），非超级管理员仅可查看档案，不可修改。
             </div>`
          : ""}
        <div class="adm-form-grid">
          <div class="adm-field"><label>显示昵称</label><input class="adm-input" id="mu-name" value="${esc(u.displayName)}" ${readOnlyStaffForNonAdmin ? "disabled" : ""} /></div>
          <div class="adm-field"><label>绑定邮箱</label><input class="adm-input" id="mu-email" value="${esc(u.email || "")}" ${readOnlyStaffForNonAdmin ? "disabled" : ""} /></div>
        </div>
        <div class="adm-form-grid">
          <div class="adm-field">
            <label>系统管理角色 (RBAC)</label>
            <select class="adm-select" id="mu-role" ${c.canEditSystemRole ? "" : "disabled"}>
              <option value="user" ${u.role === "user" ? "selected" : ""}>🎨 user (普通创作者)</option>
              <option value="operator" ${u.role === "operator" || u.role === "reviewer" ? "selected" : ""}>🧭 operator (运营审查员)</option>
              <option value="admin" ${u.role === "admin" ? "selected" : ""}>👑 admin (超级管理员)</option>
            </select>
          </div>
          <div class="adm-field">
            <label>账号状态（冻结将立即强制下线所有会话）</label>
            <select class="adm-select" id="mu-status" ${readOnlyStaffForNonAdmin ? "disabled" : ""}>
              <option value="active" ${u.status === "active" ? "selected" : ""}>active (正常活跃)</option>
              <option value="frozen" ${u.status === "frozen" ? "selected" : ""}>frozen (立即冻结封禁)</option>
            </select>
          </div>
        </div>
        <div class="adm-form-grid">
          <div class="adm-field">
            <label>创作者荣誉头衔人工覆盖</label>
            <select class="adm-select" id="mu-honor" ${c.canEditUserHonor && !readOnlyStaffForNonAdmin ? "" : "disabled"}>
              <option value="auto" ${u.honorOverride === null || u.honorOverride === undefined ? "selected" : ""}>自动按发布作品数计算 (${esc(u.honor.badge)})</option>
              <option value="4" ${u.honorOverride === 4 ? "selected" : ""}>👑 殿堂共创官 (Tier 4 · 1.45×)</option>
              <option value="3" ${u.honorOverride === 3 ? "selected" : ""}>🏅 金牌主理人 (Tier 3 · 1.25×)</option>
              <option value="2" ${u.honorOverride === 2 ? "selected" : ""}>🌟 先锋开荒者 (Tier 2 · 1.12×)</option>
              <option value="1" ${u.honorOverride === 1 ? "selected" : ""}>🌱 新锐创作者 (Tier 1 · 1.08×)</option>
              <option value="0" ${u.honorOverride === 0 ? "selected" : ""}>✨ 灵感探索者 (Tier 0)</option>
            </select>
          </div>
          <div class="adm-field">
            <label>个人简介</label>
            <input class="adm-input" id="mu-bio" value="${esc(u.bio || "")}" ${readOnlyStaffForNonAdmin ? "disabled" : ""} />
          </div>
        </div>
        ${c.canResetUserPassword ? `
        <div class="adm-form-grid">
          <div class="adm-field">
            <label>重置登录密码（留空不修改，填写则重置为新密码）</label>
            <input class="adm-input" id="mu-newpass" type="text" placeholder="输入 ≥6 位新密码以重置" />
          </div>
          <div class="adm-field" style="justify-content:flex-end;">
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
              <input type="checkbox" id="mu-reset-apikey" /> 同时轮换重置该用户的本地扩展同步密钥
            </label>
          </div>
        </div>` : ""}

        <div class="adm-field">
          <label><input type="checkbox" id="mu-wlock" ${u.wallet.locked ? "checked" : ""} ${readOnlyStaffForNonAdmin ? "disabled" : ""} /> 锁定该用户积分钱包支出（禁止消费/打赏，仅允许入账）</label>
        </div>

        <div style="font-size:12px;color:var(--adm-ink-soft);background:var(--adm-surface-alt);padding:9px 12px;border-radius:8px;margin-bottom:12px;">
          <div>当前余额：<strong>${u.wallet.balance}✦</strong> · 在线会话：<strong>${u.activeSessions}</strong> · Skill Key：<code>${esc(u.apiKeyMasked)}</code></div>
          <div style="margin-top:4px;">
            论坛版主职务：
            ${(u.moderatedBoards || []).length
              ? u.moderatedBoards
                  .map(
                    (mb) =>
                      `<span class="adm-badge exclusive" style="margin-right:6px;">🛡️ ${esc(mb.shortLabel)}·${esc(mb.title)} ${
                        c.canManageModerators ? `<button type="button" style="border:none;background:none;color:inherit;cursor:pointer;font-weight:800;" data-inline-revoke-mod="${mb.id}" title="卸任">×</button>` : ""
                      }</span>`
                  )
                  .join("")
              : `<span style="color:var(--adm-ink-muted);">未担任版主</span>`}
            ${c.canManageModerators ? `<button type="button" class="adm-btn adm-btn-sm" id="mu-add-mod" style="margin-left:6px;padding:2px 8px;">+ 任命版主</button>` : ""}
          </div>
        </div>

        <div class="adm-field"><label>治理审计备注</label><input class="adm-input" id="mu-reason" value="后台维护用户账号资料与角色权限" ${readOnlyStaffForNonAdmin ? "disabled" : ""} /></div>

        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:16px;">
          <div>
            ${canDeleteThisUser
              ? `<button type="button" class="adm-btn adm-btn-danger" id="mu-delete">🗑️ 移除此账号</button>`
              : ""}
          </div>
          <div style="display:flex;gap:8px;">
            <button type="button" class="adm-btn" id="mu-cancel">关闭</button>
            ${!readOnlyStaffForNonAdmin ? `<button type="button" class="adm-btn adm-btn-primary" id="mu-save">💾 保存账号变更</button>` : ""}
          </div>
        </div>

        <div style="border-top:1px solid var(--adm-border);padding-top:12px;">
          <div style="font-size:12.5px;font-weight:700;margin-bottom:6px;">最近积分账本流水 (${detail.ledgers.length})：</div>
          <div style="max-height:165px;overflow-y:auto;">
            <table class="adm-table">
              <thead><tr><th>变动</th><th>结余</th><th>类型</th><th>原因</th><th>时间</th></tr></thead>
              <tbody>
                ${detail.ledgers.slice(0, 15).map((l) => `
                  <tr>
                    <td style="font-weight:700;color:${l.delta >= 0 ? "var(--adm-jade)" : "var(--adm-vermilion)"};">${l.delta >= 0 ? `+${l.delta}` : l.delta}✦</td>
                    <td>${l.balanceAfter}✦</td>
                    <td><code>${esc(l.kind)}</code></td>
                    <td>${esc(l.reason)}</td>
                    <td style="color:var(--adm-ink-muted);">${esc(l.createdAt)}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `);

      document.getElementById("mu-cancel").onclick = closeModal;

      const addModBtn = document.getElementById("mu-add-mod");
      if (addModBtn) {
        addModBtn.onclick = () => openAssignModeratorModal(u.username);
      }

      document.querySelectorAll("[data-inline-revoke-mod]").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await api("/api/admin/forum-moderators/revoke", {
              method: "POST",
              body: { id: parseInt(btn.getAttribute("data-inline-revoke-mod"), 10) },
            });
            toast("已卸任该板块版主职务");
            await reloadCurrent();
            await openUserDetailModal(userId);
          } catch (err) {
            toast(err.message, true);
          }
        };
      });

      const delBtn = document.getElementById("mu-delete");
      if (delBtn) {
        delBtn.onclick = async () => {
          if (delBtn.getAttribute("data-armed") !== "1") {
            delBtn.setAttribute("data-armed", "1");
            delBtn.textContent = "⚠️ 再次点击确认永久删除";
            return;
          }
          try {
            await api(`/api/admin/users/${u.id}/delete`, {
              method: "POST",
              body: { reason: document.getElementById("mu-reason").value.trim() || `超管移除账号 @${u.username}` },
            });
            closeModal();
            toast(`已移除用户账号 @${u.username}`);
            await reloadCurrent();
          } catch (err) {
            toast(err.message, true);
          }
        };
      }

      const saveBtn = document.getElementById("mu-save");
      if (saveBtn) {
        saveBtn.onclick = async () => {
          try {
            const payload = {
              displayName: document.getElementById("mu-name").value.trim(),
              email: document.getElementById("mu-email").value.trim(),
              bio: document.getElementById("mu-bio").value.trim(),
              status: document.getElementById("mu-status").value,
              walletLocked: document.getElementById("mu-wlock").checked,
              reason: document.getElementById("mu-reason").value.trim(),
            };
            if (c.canEditUserHonor) {
              const hoVal = document.getElementById("mu-honor").value;
              payload.honorOverride = hoVal === "auto" ? null : parseInt(hoVal, 10);
            }
            if (c.canEditSystemRole) {
              payload.role = document.getElementById("mu-role").value;
            }
            if (c.canResetUserPassword) {
              const np = document.getElementById("mu-newpass").value.trim();
              if (np) payload.newPassword = np;
              if (document.getElementById("mu-reset-apikey").checked) payload.resetApiKey = true;
            }
            const res = await api(`/api/admin/users/${u.id}/update`, { method: "POST", body: payload });
            closeModal();
            toast(res.revokedSessions ? `已冻结账号并强制下线 ${res.revokedSessions} 个会话` : "用户资料与权限已更新");
            await reloadCurrent();
          } catch (err) {
            toast(err.message, true);
          }
        };
      }
    } catch (err) {
      toast(err.message, true);
    }
  }

  function openWorkEditModal(work) {
    openModal(`
      <h3 style="margin:0 0 14px;">✏️ 编辑作品详情与配方 — ${esc(work.id)}</h3>
      <div class="adm-field"><label>作品标题</label><input class="adm-input" id="mw-title" value="${esc(work.title)}" /></div>
      <div class="adm-form-grid">
        <div class="adm-field"><label>画风编号（逗号分隔）</label><input class="adm-input" id="mw-styles" value="${esc((work.styles || []).join(", "))}" /></div>
        <div class="adm-field"><label>图型编号</label><input class="adm-input" id="mw-layout" value="${esc(work.layout || "")}" /></div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field"><label>配方解锁定价 (✦，0 为免费开源)</label><input class="adm-input" type="number" id="mw-price" value="${work.price}" min="0" max="200" /></div>
        <div class="adm-field"><label>情绪氛围标签</label><input class="adm-input" id="mw-mood" value="${esc(work.mood || "")}" /></div>
      </div>
      <div class="adm-field"><label>完整生图 Prompt</label><textarea class="adm-textarea" id="mw-prompt">${esc(work.prompt)}</textarea></div>
      <div class="adm-field"><label>审核修订原因</label><input class="adm-input" id="mw-reason" value="运营校准作品编号与元数据" /></div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
        <button class="adm-btn" id="mw-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="mw-save">💾 保存修订</button>
      </div>
    `);
    document.getElementById("mw-cancel").onclick = closeModal;
    document.getElementById("mw-save").onclick = async () => {
      try {
        await api(`/api/admin/works/${encodeURIComponent(work.id)}/moderate`, {
          method: "POST",
          body: {
            action: "edit",
            title: document.getElementById("mw-title").value,
            styles: document.getElementById("mw-styles").value,
            layout: document.getElementById("mw-layout").value,
            price: parseInt(document.getElementById("mw-price").value || "0", 10),
            mood: document.getElementById("mw-mood").value,
            prompt: document.getElementById("mw-prompt").value,
            reason: document.getElementById("mw-reason").value,
          },
        });
        closeModal();
        toast("作品信息已更新并记入审计日志");
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  function openCatalogEditModal(existing, defaultSourceType) {
    const item = existing || {
      code: "",
      kind: "style",
      sourceType: defaultSourceType || "exclusive",
      name: "",
      group: defaultSourceType === "official_override" ? "官方增强覆盖" : "官网独占黑盒",
      unlockCost: defaultSourceType === "exclusive" ? 12 : 0,
      image: "/images/poster-demo-autumn-equinox.webp",
      description: "",
      definition: "",
      secretBlackboxPrompt: "",
      status: "published",
      featured: true,
      isNew: true,
    };
    const adminMode = caps().canViewBlackbox;
    openModal(`
      <h3 style="margin:0 0 14px;">${existing ? `✏️ 编辑目录资产 ${esc(item.code)}` : `🔒 新建${item.sourceType === "official_override" ? "官方目录覆盖项" : "专属黑盒资产"}`}</h3>
      <div class="adm-form-grid">
        <div class="adm-field">
          <label>资产编号 ${existing ? "(不可改)" : item.sourceType === "official_override" ? "(必填，如 FA-001)" : "(留空自动分配 FX/LX)"}</label>
          <input class="adm-input" id="mc-code" value="${esc(item.code)}" ${existing ? "disabled" : ""} placeholder="如 FX-005 或 FA-001" />
        </div>
        <div class="adm-field">
          <label>类型</label>
          <select class="adm-select" id="mc-kind" ${existing ? "disabled" : ""}>
            <option value="style" ${item.kind === "style" ? "selected" : ""}>🎨 画风 (style)</option>
            <option value="layout" ${item.kind === "layout" ? "selected" : ""}>📐 图型 (layout)</option>
          </select>
        </div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field"><label>展示名称</label><input class="adm-input" id="mc-name" value="${esc(item.name)}" /></div>
        <div class="adm-field"><label>所属分组</label><input class="adm-input" id="mc-group" value="${esc(item.group)}" /></div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field"><label>解锁积分门槛 (✦，0 为登录免费)</label><input class="adm-input" type="number" id="mc-cost" value="${item.unlockCost}" min="0" max="500" /></div>
        <div class="adm-field">
          <label>上架状态</label>
          <select class="adm-select" id="mc-status">
            <option value="published" ${item.status === "published" ? "selected" : ""}>published (上架)</option>
            <option value="paused" ${item.status === "paused" ? "selected" : ""}>paused (暂停)</option>
            <option value="hidden" ${item.status === "hidden" ? "selected" : ""}>hidden (隐藏)</option>
          </select>
        </div>
      </div>
      <div class="adm-field"><label>封面样张路径</label><input class="adm-input" id="mc-image" value="${esc(item.image)}" /></div>
      <div class="adm-field"><label>公开展示简介 (前端可见)</label><input class="adm-input" id="mc-desc" value="${esc(item.description)}" /></div>
      <div class="adm-field"><label>公开/解锁后明文规则 (共创 USR 适用；专属黑盒可留空或写公开导语)</label><textarea class="adm-textarea" id="mc-def" style="min-height:64px;">${esc(item.definition)}</textarea></div>
      ${adminMode
        ? `<div class="adm-field">
            <label style="color:var(--adm-vermilion);">🔒 服务端私有黑盒底层 Prompt（绝不下发浏览器，仅云端生图时由后端自动注入！）</label>
            <textarea class="adm-textarea" id="mc-secret" placeholder="输入核心私有画风/版式视觉指令…">${esc(item.secretBlackboxPrompt || "")}</textarea>
          </div>`
        : ""}
      <div style="display:flex;gap:16px;margin-bottom:12px;font-size:13px;">
        <label><input type="checkbox" id="mc-featured" ${item.featured ? "checked" : ""} /> ⭐ 精选推荐</label>
        <label><input type="checkbox" id="mc-new" ${item.isNew ? "checked" : ""} /> ✨ 72h 首发标识</label>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;">
        <button class="adm-btn" id="mc-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="mc-save">💾 保存资产配置</button>
      </div>
    `);
    document.getElementById("mc-cancel").onclick = closeModal;
    document.getElementById("mc-save").onclick = async () => {
      try {
        const body = {
          code: document.getElementById("mc-code").value.trim(),
          kind: document.getElementById("mc-kind").value,
          sourceType: item.sourceType,
          name: document.getElementById("mc-name").value.trim(),
          group: document.getElementById("mc-group").value.trim(),
          unlockCost: parseInt(document.getElementById("mc-cost").value || "0", 10),
          status: document.getElementById("mc-status").value,
          image: document.getElementById("mc-image").value.trim(),
          description: document.getElementById("mc-desc").value.trim(),
          definition: document.getElementById("mc-def").value.trim(),
          featured: document.getElementById("mc-featured").checked,
          isNew: document.getElementById("mc-new").checked,
        };
        if (adminMode && document.getElementById("mc-secret")) {
          body.secretBlackboxPrompt = document.getElementById("mc-secret").value.trim();
        }
        const res = await api("/api/admin/catalog", { method: "POST", body });
        closeModal();
        toast(`资产 ${res.code} 已保存生效`);
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  function openPresetEditModal(existing) {
    const p = existing || { id: "", title: "", blueprint: "single", scenarioBadge: "官方场景流", scenarioDesc: "", sortOrder: 8, enabled: true };
    openModal(`
      <h3 style="margin:0 0 14px;">🎛️ ${existing ? "编辑创作台官方预设" : "新增创作台官方预设"}</h3>
      <div class="adm-form-grid">
        <div class="adm-field"><label>预设标题</label><input class="adm-input" id="mp-title" value="${esc(p.title)}" /></div>
        <div class="adm-field"><label>蓝图标识 (blueprint)</label><input class="adm-input" id="mp-bp" value="${esc(p.blueprint)}" /></div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field"><label>场景角标</label><input class="adm-input" id="mp-badge" value="${esc(p.scenarioBadge)}" /></div>
        <div class="adm-field"><label>排序权重</label><input class="adm-input" type="number" id="mp-sort" value="${p.sortOrder}" /></div>
      </div>
      <div class="adm-field"><label>场景描述</label><textarea class="adm-textarea" id="mp-desc">${esc(p.scenarioDesc)}</textarea></div>
      <div class="adm-field"><label><input type="checkbox" id="mp-enabled" ${p.enabled ? "checked" : ""} /> 在无限画布「工作流库」中向全站用户展示</label></div>
      <div style="display:flex;justify-content:flex-end;gap:8px;">
        <button class="adm-btn" id="mp-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="mp-save">💾 保存预设</button>
      </div>
    `);
    document.getElementById("mp-cancel").onclick = closeModal;
    document.getElementById("mp-save").onclick = async () => {
      try {
        await api("/api/admin/presets", {
          method: "POST",
          body: {
            id: p.id || undefined,
            title: document.getElementById("mp-title").value.trim(),
            blueprint: document.getElementById("mp-bp").value.trim(),
            scenarioBadge: document.getElementById("mp-badge").value.trim(),
            sortOrder: parseInt(document.getElementById("mp-sort").value || "10", 10),
            scenarioDesc: document.getElementById("mp-desc").value.trim(),
            enabled: document.getElementById("mp-enabled").checked,
            graph: p.graph || { blueprint: document.getElementById("mp-bp").value.trim() },
          },
        });
        closeModal();
        toast("官方预设工作流已更新");
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  function openBountyArbitrateModal(topic) {
    openModal(`
      <h3 style="margin:0 0 8px;">⚖️ 积分悬赏仲裁 — 《${esc(topic.title)}》</h3>
      <p style="font-size:13px;color:var(--adm-ink-soft);margin-top:0;">
        楼主 @${esc(topic.authorUsername)} 托管悬赏 <strong style="color:var(--adm-vermilion);">${topic.bounty}✦</strong>。您可裁定采纳下方任意有效回复发放赏金，或关闭悬赏将托管积分原路退回楼主。
      </p>
      <div style="margin-bottom:14px;">
        <div style="font-size:12.5px;font-weight:700;margin-bottom:6px;">候选回复列表 (${(topic.replies || []).length})：</div>
        ${(topic.replies || []).length === 0
          ? `<div style="font-size:12.5px;color:var(--adm-ink-muted);padding:10px;background:var(--adm-surface-alt);border-radius:8px;">当前暂无回复，建议原路退回楼主托管积分。</div>`
          : (topic.replies || []).map((r) => `
              <div style="padding:10px 12px;border:1px solid var(--adm-border);border-radius:10px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:10px;">
                <div>
                  <div style="font-weight:700;font-size:12.5px;">@${esc(r.authorUsername)} (${esc(r.authorName)})</div>
                  <div style="font-size:12.5px;color:var(--adm-ink-soft);margin-top:2px;">${esc(r.text)}</div>
                </div>
                <button class="adm-btn adm-btn-sm adm-btn-jade" data-award-reply="${esc(r.id)}">🏆 采纳并发 +${topic.bounty}✦</button>
              </div>
            `).join("")}
      </div>
      <div class="adm-field"><label>仲裁审计备注</label><input class="adm-input" id="mb-reason" value="运营管理人工介入悬赏结算仲裁" /></div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px;">
        <button class="adm-btn adm-btn-danger" id="mb-refund">↩ 关闭悬赏并退回楼主 +${topic.bounty}✦</button>
        <button class="adm-btn" id="mb-cancel">关闭窗口</button>
      </div>
    `);
    document.getElementById("mb-cancel").onclick = closeModal;
    document.getElementById("mb-refund").onclick = async () => {
      try {
        await api(`/api/admin/topics/${encodeURIComponent(topic.id)}/moderate`, {
          method: "POST",
          body: { action: "refund_bounty", reason: document.getElementById("mb-reason").value },
        });
        closeModal();
        toast(`已将 ${topic.bounty}✦ 托管积分原路退回楼主`);
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
    document.querySelectorAll("[data-award-reply]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/admin/topics/${encodeURIComponent(topic.id)}/moderate`, {
            method: "POST",
            body: {
              action: "settle_bounty",
              replyId: btn.getAttribute("data-award-reply"),
              reason: document.getElementById("mb-reason").value,
            },
          });
          closeModal();
          toast(`悬赏仲裁完成，+${topic.bounty}✦ 已发放至答主钱包`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
  }

  function openCreditAdjustModal(userId, username) {
    openModal(`
      <h3 style="margin:0 0 12px;">✦ 人工积分调账 — @${esc(username)}</h3>
      <div class="adm-field">
        <label>积分增减数额（正数为发放奖励，负数为风控扣减）</label>
        <input class="adm-input" type="number" id="madj-delta" value="30" />
      </div>
      <div class="adm-field">
        <label>审计原因（必填，将同步展示于用户积分账本与审计日志）</label>
        <input class="adm-input" id="madj-reason" value="社区特别贡献奖人工激励发放" />
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
        <button class="adm-btn" id="madj-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="madj-save">✅ 确认调账</button>
      </div>
    `);
    document.getElementById("madj-cancel").onclick = closeModal;
    document.getElementById("madj-save").onclick = async () => {
      try {
        const delta = parseInt(document.getElementById("madj-delta").value || "0", 10);
        const reason = document.getElementById("madj-reason").value.trim();
        const res = await api(`/api/admin/users/${userId}/credits`, { method: "POST", body: { delta, reason } });
        closeModal();
        toast(`调账完成！@${username} 最新余额：${res.balanceAfter}✦`);
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  function openNewRedeemModal() {
    openModal(`
      <h3 style="margin:0 0 12px;">🎟️ 生成运营活动积分兑换码</h3>
      <div class="adm-form-grid">
        <div class="adm-field"><label>兑换码口令 (大写字母+数字)</label><input class="adm-input" id="mrc-code" value="SPRING2026" /></div>
        <div class="adm-field"><label>单次兑换积分面额 (✦)</label><input class="adm-input" type="number" id="mrc-credits" value="30" min="1" max="5000" /></div>
      </div>
      <div class="adm-form-grid">
        <div class="adm-field"><label>最大可兑换总人数</label><input class="adm-input" type="number" id="mrc-max" value="200" min="1" /></div>
        <div class="adm-field"><label>活动备注</label><input class="adm-input" id="mrc-note" value="春季创作节社群福利码" /></div>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
        <button class="adm-btn" id="mrc-cancel">取消</button>
        <button class="adm-btn adm-btn-primary" id="mrc-save">🎟️ 立即创建</button>
      </div>
    `);
    document.getElementById("mrc-cancel").onclick = closeModal;
    document.getElementById("mrc-save").onclick = async () => {
      try {
        const res = await api("/api/admin/redeem-codes", {
          method: "POST",
          body: {
            code: document.getElementById("mrc-code").value.trim(),
            credits: parseInt(document.getElementById("mrc-credits").value || "20", 10),
            maxUses: parseInt(document.getElementById("mrc-max").value || "100", 10),
            note: document.getElementById("mrc-note").value.trim(),
          },
        });
        closeModal();
        toast(`兑换码 ${res.code} 已生效，用户可在积分中心兑换`);
        await reloadCurrent();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  /* ======================== EVENT BINDINGS ======================== */

  function bindConsoleEvents() {
    const root = document.getElementById("admin-root");

    // Sidebar navigation
    root.querySelectorAll("[data-nav-mod]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.module = btn.getAttribute("data-nav-mod");
        syncUrlModule();
        await reloadCurrent();
      });
    });

    // Quick jump buttons
    root.querySelectorAll("[data-jump-mod]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.module = btn.getAttribute("data-jump-mod");
        syncUrlModule();
        await reloadCurrent();
      });
    });
    root.querySelectorAll("[data-jump-audit]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.module = "settings";
        state.subtab.settings = "audit_list";
        syncUrlModule();
        await reloadCurrent();
      });
    });

    const bannerNewUser = document.getElementById("banner-new-user-btn");
    if (bannerNewUser) bannerNewUser.onclick = openCreateUserModal;

    // Subtabs
    root.querySelectorAll("[data-subtab]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const [mod, sub] = btn.getAttribute("data-subtab").split(":");
        state.subtab[mod] = sub;
        await reloadCurrent();
      });
    });

    // Topbar refresh & role switcher
    const refBtn = document.getElementById("adm-refresh-btn");
    if (refBtn) refBtn.onclick = () => reloadCurrent().then(() => toast("已同步最新后台数据"));

    const switcher = document.getElementById("adm-role-switcher");
    if (switcher) {
      switcher.onchange = () => {
        if (switcher.value) switchSandboxRole(switcher.value);
      };
    }

    // Moderator Console Events
    const btnModSearch = document.getElementById("btn-mod-search");
    if (btnModSearch) {
      btnModSearch.onclick = () => {
        state.filters.modBoard = document.getElementById("flt-mod-board").value;
        state.filters.modQ = document.getElementById("flt-mod-q").value.trim();
        reloadCurrent();
      };
    }
    const fltModBoard = document.getElementById("flt-mod-board");
    if (fltModBoard) {
      fltModBoard.onchange = () => {
        state.filters.modBoard = fltModBoard.value;
        reloadCurrent();
      };
    }
    root.querySelectorAll("[data-mod-op]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const topicId = btn.getAttribute("data-mod-tid");
        const op = btn.getAttribute("data-mod-op");
        try {
          await api("/api/forum/moderate", {
            method: "POST",
            body: { topicId, op, reason: `版主工作台执行 ${op}` },
          });
          toast(`已对帖子 ${topicId} 执行 ${op}`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
    root.querySelectorAll("[data-mod-move-tid]").forEach((sel) => {
      sel.addEventListener("change", async () => {
        const targetCategory = sel.value;
        if (!targetCategory) return;
        const topicId = sel.getAttribute("data-mod-move-tid");
        try {
          await api("/api/forum/moderate", {
            method: "POST",
            body: { topicId, op: "move", targetCategory, reason: `版主移帖至 ${targetCategory}` },
          });
          toast(`已将帖子移至新板块`);
          await reloadCurrent();
        } catch (err) {
          sel.value = "";
          toast(err.message, true);
        }
      });
    });
    root.querySelectorAll("[data-mod-reply-op]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api("/api/forum/moderate", {
            method: "POST",
            body: {
              topicId: btn.getAttribute("data-mod-tid"),
              replyId: btn.getAttribute("data-mod-rid"),
              op: btn.getAttribute("data-mod-reply-op"),
              reason: "版主回复巡查治理",
            },
          });
          toast("楼层回复状态已更新");
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    // Works filters & actions
    const btnWorksSearch = document.getElementById("btn-works-search");
    if (btnWorksSearch) {
      btnWorksSearch.onclick = () => {
        state.filters.worksStatus = document.getElementById("flt-works-status").value;
        state.filters.worksQ = document.getElementById("flt-works-q").value.trim();
        reloadCurrent();
      };
    }
    root.querySelectorAll("[data-work-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const wid = btn.getAttribute("data-work-id");
        const act = btn.getAttribute("data-work-act");
        try {
          await api(`/api/admin/works/${encodeURIComponent(wid)}/moderate`, {
            method: "POST",
            body: { action: act, reason: `管理台快捷操作: ${act}` },
          });
          toast(`作品 ${wid} 已执行 ${act}`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
    root.querySelectorAll("[data-work-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const w = state.data.works.find((x) => x.id === btn.getAttribute("data-work-edit"));
        if (w) openWorkEditModal(w);
      });
    });

    // Comments filters & actions
    const btnCmtSearch = document.getElementById("btn-comments-search");
    if (btnCmtSearch) {
      btnCmtSearch.onclick = () => {
        state.filters.commentsStatus = document.getElementById("flt-comments-status").value;
        state.filters.commentsQ = document.getElementById("flt-comments-q").value.trim();
        reloadCurrent();
      };
    }
    root.querySelectorAll("[data-cmt-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api("/api/admin/comments/moderate", {
            method: "POST",
            body: {
              commentType: btn.getAttribute("data-cmt-type"),
              id: btn.getAttribute("data-cmt-id"),
              action: btn.getAttribute("data-cmt-act"),
            },
          });
          toast("评论治理状态已更新");
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    // Catalog filters & CRUD
    const btnCatSearch = document.getElementById("btn-cat-search");
    if (btnCatSearch) {
      btnCatSearch.onclick = () => {
        state.filters.catSource = document.getElementById("flt-cat-source").value;
        state.filters.catKind = document.getElementById("flt-cat-kind").value;
        state.filters.catQ = document.getElementById("flt-cat-q").value.trim();
        reloadCurrent();
      };
    }
    const btnNewEx = document.getElementById("btn-new-exclusive");
    if (btnNewEx) btnNewEx.onclick = () => openCatalogEditModal(null, "exclusive");
    const btnNewOv = document.getElementById("btn-new-override");
    if (btnNewOv) btnNewOv.onclick = () => openCatalogEditModal(null, "official_override");

    root.querySelectorAll("[data-cat-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = state.data.catalog.find((x) => x.code === btn.getAttribute("data-cat-edit"));
        if (item) openCatalogEditModal(item, item.sourceType);
      });
    });
    root.querySelectorAll("[data-cat-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const code = btn.getAttribute("data-cat-del");
        try {
          await api(`/api/admin/catalog/${encodeURIComponent(code)}/delete`, {
            method: "POST",
            body: { reason: `管理员删除目录项 ${code}` },
          });
          toast(`已删除资产 ${code}`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    // Presets
    const btnNewPreset = document.getElementById("btn-new-preset");
    if (btnNewPreset) btnNewPreset.onclick = () => openPresetEditModal(null);
    root.querySelectorAll("[data-preset-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const p = state.data.presets.find((x) => x.id === btn.getAttribute("data-preset-edit"));
        if (p) openPresetEditModal(p);
      });
    });

    // Forum Moderators Appointment & Revoke
    const btnAppointMod = document.getElementById("btn-appoint-mod");
    if (btnAppointMod) btnAppointMod.onclick = () => openAssignModeratorModal("");
    root.querySelectorAll("[data-revoke-mod]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api("/api/admin/forum-moderators/revoke", {
            method: "POST",
            body: { id: parseInt(btn.getAttribute("data-revoke-mod"), 10) },
          });
          toast("已卸任该论坛版主");
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    // Reports & Topics Governance
    const fltRepStatus = document.getElementById("flt-reports-status");
    if (fltRepStatus) {
      fltRepStatus.onchange = () => {
        state.filters.reportsStatus = fltRepStatus.value;
        reloadCurrent();
      };
    }
    const btnRepRefresh = document.getElementById("btn-reports-refresh");
    if (btnRepRefresh) btnRepRefresh.onclick = () => reloadCurrent();

    root.querySelectorAll("[data-rep-resolve]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const rid = btn.getAttribute("data-rep-id");
        const resolution = btn.getAttribute("data-rep-resolve");
        try {
          await api(`/api/admin/reports/${rid}/resolve`, {
            method: "POST",
            body: {
              resolution,
              note: resolution === "confirmed" ? "核实违规，已联动下架隐藏" : "核实无违规，予以驳回并恢复正常展示",
              autoAction: true,
            },
          });
          toast(`举报 #${rid} 已裁定为 ${resolution}`);
          if (effRole() !== "moderator") {
            state.data.dashboard = await api("/api/admin/dashboard");
          }
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    const btnTopicsSearch = document.getElementById("btn-topics-search");
    if (btnTopicsSearch) {
      btnTopicsSearch.onclick = () => {
        state.filters.topicsStatus = document.getElementById("flt-topics-status").value;
        state.filters.topicsBountyOnly = document.getElementById("flt-topics-bounty").checked;
        state.filters.topicsQ = document.getElementById("flt-topics-q").value.trim();
        reloadCurrent();
      };
    }
    root.querySelectorAll("[data-topic-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const tid = btn.getAttribute("data-topic-id");
        const act = btn.getAttribute("data-topic-act");
        try {
          await api(`/api/admin/topics/${encodeURIComponent(tid)}/moderate`, {
            method: "POST",
            body: { action: act },
          });
          toast(`话题 ${tid} 已执行 ${act}`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
    root.querySelectorAll("[data-topic-bounty]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const t = state.data.topics.find((x) => x.id === btn.getAttribute("data-topic-bounty"));
        if (t) openBountyArbitrateModal(t);
      });
    });

    // Users CRUD, Unlocks, Redeem Codes & Discourse Import
    const btnNewUser = document.getElementById("btn-new-user");
    if (btnNewUser) btnNewUser.onclick = openCreateUserModal;

    const btnUsersSearch = document.getElementById("btn-users-search");
    if (btnUsersSearch) {
      btnUsersSearch.onclick = () => {
        state.filters.usersRole = document.getElementById("flt-users-role").value;
        state.filters.usersStatus = document.getElementById("flt-users-status").value;
        state.filters.usersQ = document.getElementById("flt-users-q").value.trim();
        reloadCurrent();
      };
    }
    root.querySelectorAll("[data-user-detail]").forEach((btn) => {
      btn.addEventListener("click", () => openUserDetailModal(parseInt(btn.getAttribute("data-user-detail"), 10)));
    });
    root.querySelectorAll("[data-user-mod-appoint]").forEach((btn) => {
      btn.addEventListener("click", () => openAssignModeratorModal(btn.getAttribute("data-user-mod-appoint")));
    });
    root.querySelectorAll("[data-user-credit]").forEach((btn) => {
      btn.addEventListener("click", () =>
        openCreditAdjustModal(parseInt(btn.getAttribute("data-user-credit"), 10), btn.getAttribute("data-user-name"))
      );
    });
    root.querySelectorAll("[data-user-quota]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/admin/users/${btn.getAttribute("data-user-quota")}/reset-quota`, { method: "POST", body: {} });
          toast("已重置该用户今日免费生图额度");
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    const fltUnlocks = document.getElementById("flt-unlocks-status");
    if (fltUnlocks) {
      fltUnlocks.onchange = () => {
        state.filters.unlocksStatus = fltUnlocks.value;
        reloadCurrent();
      };
    }
    root.querySelectorAll("[data-unlock-refund]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const uid = btn.getAttribute("data-unlock-refund");
        try {
          const res = await api(`/api/admin/unlocks/${uid}/refund`, {
            method: "POST",
            body: { reason: "后台人工核实退款并追回分成" },
          });
          toast(`订单 #${uid} 已退还买家 +${res.refundedCost}✦，追回作者分成 -${res.clawedBackRoyalty}✦`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    const btnNewRedeem = document.getElementById("btn-new-redeem");
    if (btnNewRedeem) btnNewRedeem.onclick = openNewRedeemModal;
    root.querySelectorAll("[data-redeem-toggle]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const code = btn.getAttribute("data-redeem-toggle");
        const active = btn.getAttribute("data-redeem-next") === "1";
        try {
          await api(`/api/admin/redeem-codes/${encodeURIComponent(code)}/toggle`, { method: "POST", body: { active } });
          toast(`兑换码 ${code} 状态已更新`);
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    const btnDiscImport = document.getElementById("btn-run-disc-import");
    if (btnDiscImport) {
      btnDiscImport.onclick = async () => {
        try {
          const payload = document.getElementById("imp-disc-payload").value;
          const migrationCredits = parseInt(document.getElementById("imp-disc-bonus").value || "50", 10);
          const res = await api("/api/admin/users/import-discourse", {
            method: "POST",
            body: { payload, migrationCredits },
          });
          toast(`导入成功 ${res.imported} 人（幂等跳过 ${res.skipped} 人），每人已发放 +${res.bonusPerUser}✦`);
          state.subtab.users = "users_list";
          await reloadCurrent();
        } catch (err) {
          toast(err.message, true);
        }
      };
    }

    // Gateway & Generations
    const btnGenSearch = document.getElementById("btn-gen-search");
    if (btnGenSearch) {
      btnGenSearch.onclick = () => {
        state.filters.genStatus = document.getElementById("flt-gen-status").value;
        state.filters.genEngine = document.getElementById("flt-gen-engine").value;
        state.filters.genQ = document.getElementById("flt-gen-q").value.trim();
        reloadCurrent();
      };
    }
    const btnProbe = document.getElementById("btn-probe-gateway");
    if (btnProbe) {
      btnProbe.onclick = async () => {
        btnProbe.disabled = true;
        btnProbe.textContent = "⏳ 正在探测上游网关…";
        try {
          state.data.gateway = await api("/api/admin/gateway?probe=1");
          renderMainConsole();
          toast(state.data.gateway.probe.detail);
        } catch (err) {
          toast(err.message, true);
        }
      };
    }

    // Settings & Audit Logs
    const btnSaveAnn = document.getElementById("btn-save-ann");
    if (btnSaveAnn) {
      btnSaveAnn.onclick = async () => {
        try {
          const res = await api("/api/admin/settings", {
            method: "POST",
            body: {
              section: "announcement",
              values: {
                enabled: document.getElementById("cfg-ann-enabled").checked,
                badge: document.getElementById("cfg-ann-badge").value.trim(),
                cta_label: document.getElementById("cfg-ann-cta").value.trim(),
                text: document.getElementById("cfg-ann-text").value.trim(),
              },
              reason: "更新全站顶部运营公告横幅",
            },
          });
          state.data.settings = res.settings;
          toast("全站公告条配置已实时保存生效");
        } catch (err) {
          toast(err.message, true);
        }
      };
    }

    const btnSaveMod = document.getElementById("btn-save-mod");
    if (btnSaveMod) {
      btnSaveMod.onclick = async () => {
        try {
          const res = await api("/api/admin/settings", {
            method: "POST",
            body: {
              section: "moderation",
              values: {
                auto_pause_report_threshold: parseInt(document.getElementById("cfg-mod-threshold").value || "3", 10),
                allow_self_review_for_admin: document.getElementById("cfg-mod-admin-self").checked,
              },
              reason: "更新内容审核与自审风控参数",
            },
          });
          state.data.settings = res.settings;
          toast("审核风控策略已更新生效");
        } catch (err) {
          toast(err.message, true);
        }
      };
    }

    const btnSaveEco = document.getElementById("btn-save-eco");
    if (btnSaveEco) {
      btnSaveEco.onclick = async () => {
        try {
          const res = await api("/api/admin/settings", {
            method: "POST",
            body: {
              section: "economy",
              values: {
                welcome_credits: parseInt(document.getElementById("eco-welcome").value || "20", 10),
                daily_checkin_credits: parseInt(document.getElementById("eco-checkin").value || "5", 10),
                work_publish_credits: parseInt(document.getElementById("eco-work").value || "5", 10),
                pioneer_bonus_credits: parseInt(document.getElementById("eco-pioneer").value || "10", 10),
                asset_publish_credits: parseInt(document.getElementById("eco-asset").value || "15", 10),
                daily_free_quota: parseInt(document.getElementById("eco-quota").value || "3", 10),
                studio_credit_per_image: parseInt(document.getElementById("eco-gen-cost").value || "2", 10),
                author_share_ratio: parseFloat(document.getElementById("eco-share").value || "0.8"),
              },
              reason: "调整积分经济闭环发放与消耗参数",
            },
          });
          state.data.settings = res.settings;
          toast("积分经济参数已实时更新生效");
        } catch (err) {
          toast(err.message, true);
        }
      };
    }

    const btnAuditSearch = document.getElementById("btn-audit-search");
    if (btnAuditSearch) {
      btnAuditSearch.onclick = () => {
        state.filters.auditAction = document.getElementById("flt-audit-action").value.trim();
        state.filters.auditActor = document.getElementById("flt-audit-actor").value.trim();
        reloadCurrent();
      };
    }
  }

  async function reloadCurrent() {
    await loadModuleData(state.module);
    renderMainConsole();
  }

  async function init() {
    try {
      const ok = await refreshBootAndPermissions();
      if (!ok || !state.profile) {
        renderAccessGate();
        return;
      }

      if (!state.urlParsedOnce) {
        state.urlParsedOnce = true;
        const sp = new URLSearchParams(window.location.search);
        const reqMod = sp.get("module");
        const reqSub = sp.get("subtab");
        const reqQ = sp.get("q");
        if (reqMod) state.module = reqMod;
        if (reqMod && reqSub && state.subtab[reqMod] !== undefined) {
          state.subtab[reqMod] = reqSub;
        }
        if (reqQ && reqQ.trim()) {
          state.filters.usersQ = reqQ.trim();
        }
      }

      const allowed = state.profile.allowedModules || [];
      if (!allowed.includes(state.module)) {
        state.module = allowed[0] || "dashboard";
        syncUrlModule();
      }

      if (effRole() !== "moderator") {
        state.data.dashboard = await api("/api/admin/dashboard");
      }
      await loadModuleData(state.module);
      renderMainConsole();
    } catch (err) {
      renderAccessGate();
      toast(err.message, true);
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
