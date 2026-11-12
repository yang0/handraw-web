/* Handraw Infinite Canvas Studio v6 (studio.handraw-style.com)
 *
 * Clean Input -> Bridge -> Output Node Architecture:
 * - [输入节点]:
 *     1) 风格参数 (skill_params): 画风(含画面融合双画风) / 图型 / 主题色(可多选) / 影调(可多选) / 情绪(可多选) / 留白 / 受众 / 业务场景
 *     2) 图片参数 (asset):        角色 / 道具 / 场景 / 其他 / 自建分类 / 本地上传参考图片，支持更换与多选
 *     3) 文本参数 (text_input):   提示词与文章正文输入（内置本地 .md / .txt 文件选择附带与大屏编辑窗）
 * - [桥接节点]:
 *     4) 桥接     (bridge):       位于输入与输出之间，汇总一套输入参数并一对多分发至多个「输出控制」（如同一篇文章同时输出封面+正文插图）
 * - [输出节点]:
 *     5) 输出控制 (output_control): 纯创作台直接出图（模式 / 自主调节图片数量 / 比例 / 立即生成，无提示词输出与预置张数干扰）
 *     6) 输出显示 (output_display): 点击生成后自动在最右侧出现；重复点击生成原地刷新图片与文件；历次结果归档至「🕒 历史记录」
 */
(function () {
  const S = window.HANDRAW_SHARED;
  const E = window.HANDRAW_CANVAS_ENGINE;
  const { App, esc, toast, channelUrl } = S;

  function reportUnexpectedRuntimeError(err) {
    if (
      err instanceof TypeError ||
      err instanceof ReferenceError ||
      err instanceof SyntaxError ||
      err instanceof RangeError
    ) {
      window.HandrawErrors?.report?.(err, { kind: "render" });
    }
  }

  const UPLOAD_STORAGE_KEY = "handraw_canvas_uploads_v3";
  const CUSTOM_ASSET_CATS_KEY = "handraw_custom_asset_cats_v3";
  const PREFS_STORAGE_KEY = "handraw_canvas_prefs_v10";
  const SAVED_WORKFLOWS_KEY = "handraw_saved_workflows_v10";
  const OPEN_TABS_KEY = "handraw_open_tabs_v10";
  const HISTORY_STORAGE_KEY = "handraw_gen_history_v4";
  const MY_ARTICLES_STORAGE_KEY = "handraw_my_articles_v1";
  const ARTICLE_CONFLICT_BACKUP_KEY = "handraw_article_conflict_backup_v1";
  const RECENT_AUDIENCE_KEY = "handraw_recent_audiences_v1";
  const RECENT_SCENE_KEY = "handraw_recent_scenes_v1";
  const SCOPED_STORAGE_KEYS = new Set([
    UPLOAD_STORAGE_KEY,
    CUSTOM_ASSET_CATS_KEY,
    SAVED_WORKFLOWS_KEY,
    OPEN_TABS_KEY,
    HISTORY_STORAGE_KEY,
    MY_ARTICLES_STORAGE_KEY,
    ARTICLE_CONFLICT_BACKUP_KEY,
    RECENT_AUDIENCE_KEY,
    RECENT_SCENE_KEY
  ]);
  let activeCacheScope = "guest";
  let cacheScopeEpoch = 0;
  let _workspaceHydrationController = null;
  const _workspaceCollectionsReady=new Set();
  const _workspaceCollectionsLoading=new Map();
  let _articleOpenSerial=0;
  const _generationControllers = new Set();
  let _articlesSyncTimer = null;
  let _articlesSyncVersion = 0;
  const _articleCloudBases = new Map();
  const _articleCloudSnapshots = new Map();
  let _articlesSyncPromise = null;
  let _articlesCloudConflict = false;
  let _articlesSyncedVersion = 0;
  let _articlesSyncInFlight = false;
  let _articlesSyncStatus = "idle";
  function setArticlesSyncStatus(status) {
    _articlesSyncStatus = status;
    if (typeof CustomEvent === "function" && typeof document.dispatchEvent === "function") {
      document.dispatchEvent(new CustomEvent("handraw:article-cloud-sync", {detail:{status}}));
    }
  }
  let _activeBatchRun = null;
  let _activeArticleBatchRun = null;

  function isExplicitDemoMode() {
    const queryMode = new URLSearchParams(window.location.search || "").get("demo_mode");
    const config = typeof CS !== "undefined" ? CS.serverCfg || {} : {};
    return Boolean(
      (App.state && (App.state.demoMode === true || App.state.demo_mode === true)) ||
        config.demoMode === true ||
        config.demo_mode === true ||
        queryMode === "1" ||
        queryMode === "true" ||
        window.HANDRAW_DEMO_MODE === true
    );
  }

  function cacheScopeForState() {
    const state = App.state || {};
    const user = state.user || {};
    if (!state.loggedIn) return "guest";
    const raw = user.id ?? user.userId ?? user.username ?? "unknown";
    return `user_${String(raw).trim().replace(/[^a-zA-Z0-9_.-]/g, "_") || "unknown"}`;
  }

  function scopedStorageKey(key, scope = activeCacheScope) {
    return SCOPED_STORAGE_KEYS.has(key) ? `${key}::${scope}` : key;
  }

  const DEFAULT_ASSET_CATS = [
    { key: "characters", icon: "👤", label: "角色", builtin: true },
    { key: "props", icon: "🎒", label: "道具", builtin: true },
    { key: "scenes", icon: "🏞️", label: "场景", builtin: true },
    { key: "other", icon: "📎", label: "其他", builtin: true }
  ];

  const Catalog = {
    resourceMap: new Map(),
    styles: [],
    layouts: [],
    colors: [],
    tones: [],
    modes: [],
    ratios: [],
    moods: [],
    benchmarkAssets: { characters: [], props: [], scenes: [], other: [] }
  };

  function readJsonStorage(key, fallback) {
    try {
      const val = JSON.parse(localStorage.getItem(scopedStorageKey(key)) || "null");
      return val == null ? fallback : val;
    } catch (_) {
      return fallback;
    }
  }

  function writeJsonStorage(key, val) {
    try {
      // Only the warm cache is bounded; loaded pages remain available in
      // memory and older runs are always recoverable from PostgreSQL.
      const cached=key===HISTORY_STORAGE_KEY && Array.isArray(val)?val.slice(0,40):val;
      localStorage.setItem(scopedStorageKey(key), JSON.stringify(cached));
    } catch (_) {}
  }

  const savedPrefs = readJsonStorage(PREFS_STORAGE_KEY, {});

  const CS = {
    vx: 268,
    vy: 48,
    vk: 0.86,
    canvasTheme: savedPrefs.canvasTheme || "paper",
    gridMode: savedPrefs.gridMode || "dots",
    toolMode: "pan",
    spaceHeld: false,
    edgesHidden: false,
    snapToGrid: true,
    shelfOpen: savedPrefs.shelfOpen !== false,
    shelfQuery: "",
    minimapOpen: savedPrefs.minimapOpen !== false,
    stageView: "canvas", // "canvas" | "preview" | "history" | "workflows"
    previewTab: "article",
    articlePreviewMode: "desktop",
    articleSubView: "detail", // "detail" | "all-list" | "editor" | "reader" (?subview=preview)
    activeArticleId: null,
    articleListPage: 1,
    articleListQuery: "",
    articleListFilter: "all",
    historyPage: 1,
    historyCursor: "",
    historyLoading: false,
    historyError: "",
    historyFilter: "all",
    historyQuery: "",
    historyStatusFilter: "all",
    historySort: "newest",
    historyReturnStage: "quick",
    historyReturnUrl: "",
    historyExpandedPromptIds: {},
    historyExpandedBatchIds: {},
    historySelectedPreview: {},
    workflowQuery: "",
    activePlanNodeId: null,
    previewSlideIdx: 0,
    renamingTabId: null,
    engineMode: "disabled",
    demoMode: false,
    serverCfg: { liveImageEnabled: false, model: "gpt-image-2" },
    officialPresetMeta: null,
    pendingTasks: [],
    customUploads: [],
    customAssetCats: [],
    savedWorkflows: null,
    generationHistory: null,
    myArticles: null,
    recentAudiences: [],
    recentBusinessScenes: [],
    tabs: [],
    activeTabId: null,
    graph: { blueprint: "single", nodes: [], edges: [], selectedIds: [] },
    selectedEdgeId: null,
    selectedEdgePt: null,
    wiring: null,
    undoStack: [],
    redoStack: [],
    arrangeUndoSnapshot: null,
    zipExporting: false,
    activeBatchRun: null
  };

  const DOM = {};

  function resetStudioMemoryForScope(scope) {
    window.HandrawParameterCanvas?.reset();
    _workspaceCollectionsReady.clear();
    _workspaceCollectionsLoading.clear();
    _articleOpenSerial+=1;
    const changed = activeCacheScope !== scope;
    if (!changed && CS.tabs.length) return false;

    cacheScopeEpoch += 1;
    _articlesSyncVersion = 0;
    _articleCloudBases.clear();
    _articleCloudSnapshots.clear();
    _articlesSyncPromise = null;
    _articlesCloudConflict = false;
    _articlesSyncedVersion = 0;
    _articlesSyncInFlight = false;
    _articlesSyncStatus = "idle";
    if (_articlesSyncTimer) {
      clearTimeout(_articlesSyncTimer);
      _articlesSyncTimer = null;
    }
    if (_workspaceHydrationController) {
      try {
        _workspaceHydrationController.abort();
      } catch (_) {}
      _workspaceHydrationController = null;
    }
    for (const controller of _generationControllers) {
      try {
        controller.abort();
      } catch (_) {}
    }
    _generationControllers.clear();

    activeCacheScope = scope;
    CS.demoMode = isExplicitDemoMode();
    CS.officialPresetMeta = null;
    CS.pendingTasks = [];
    CS.customUploads = readJsonStorage(UPLOAD_STORAGE_KEY, []);
    CS.customAssetCats = readJsonStorage(CUSTOM_ASSET_CATS_KEY, []);
    CS.savedWorkflows = readJsonStorage(SAVED_WORKFLOWS_KEY, null);
    const rawHist = readJsonStorage(HISTORY_STORAGE_KEY, null);
    if (Array.isArray(rawHist)) {
      let normalizedHist = [];
      for (const item of rawHist) {
        normalizedHist = upsertHistoryEntry(normalizedHist, item, { isServer: false });
      }
      CS.generationHistory = normalizedHist;
      writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
    } else {
      CS.generationHistory = null;
    }
    CS.myArticles = readJsonStorage(MY_ARTICLES_STORAGE_KEY, null);
    CS.recentAudiences = (readJsonStorage(RECENT_AUDIENCE_KEY, []) || [])
      .filter((x) => typeof x === "string" && x.trim())
      .map((x) => x.trim())
      .slice(0, 8);
    CS.recentBusinessScenes = (readJsonStorage(RECENT_SCENE_KEY, []) || [])
      .filter((x) => typeof x === "string" && x.trim())
      .map((x) => x.trim())
      .slice(0, 8);

    // Open tabs, graph, undo history and article pointers are private memory;
    // never carry them across an account/session change.
    CS.tabs = [];
    CS.activeTabId = null;
    CS.activeArticleId = null;
    CS.activePlanNodeId = null;
    CS.articleEditorDraft = null;
    CS.articleEditorFlush = null;
    CS.graph = { blueprint: "single", nodes: [], edges: [], selectedIds: [] };
    CS.selectedEdgeId = null;
    CS.selectedEdgePt = null;
    CS.wiring = null;
    CS.undoStack = [];
    CS.redoStack = [];
    CS.arrangeUndoSnapshot = null;
    CS.historyExpandedPromptIds = {};
    CS.historyExpandedBatchIds = {};
    CS.historySelectedPreview = {};
    CS.stageView = "canvas";
    CS.historyPage = 1;
    CS.historyCursor = "";
    CS.historyLoading = false;
    CS.historyError = "";
    CS.historyFilter = "all";
    CS.historyQuery = "";
    CS.historyStatusFilter = "all";
    CS.historySort = "newest";
    CS.historyReturnStage = "quick";
    CS.historyReturnUrl = "";
    _activeBatchRun = null;
    CS.activeBatchRun = null;
    _activeArticleBatchRun = null;
    CS.activeArticleBatchRun = null;
    return true;
  }

  function hydrateLocalScopedState() {
    return resetStudioMemoryForScope(cacheScopeForState());
  }

  function isStaleScope(epoch, scope) {
    return epoch !== cacheScopeEpoch || scope !== activeCacheScope;
  }

  function configureGenerationEngine() {
    CS.demoMode = isExplicitDemoMode();
    const configured = Boolean(
      CS.serverCfg &&
        (CS.serverCfg.liveImageEnabled || CS.serverCfg.realImageGeneration || CS.serverCfg.configured)
    );
    CS.engineMode = configured ? "api" : CS.demoMode ? "demo" : "disabled";
    savePrefs();
    return CS.engineMode;
  }

  function isLiveGenerationEnabled() {
    return (
      CS.engineMode === "api" &&
      Boolean(CS.serverCfg && (CS.serverCfg.liveImageEnabled || CS.serverCfg.realImageGeneration || CS.serverCfg.configured))
    );
  }

  function isDemoGenerationEnabled() {
    return CS.engineMode === "demo" && isExplicitDemoMode();
  }

  function makeStableRequestId(prefix = "studio") {
    let random = "";
    try {
      random = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : "";
    } catch (_) {}
    if (!random) random = Math.random().toString(36).slice(2, 12);
    return `${prefix}_${Date.now().toString(36)}_${random}`;
  }

  function ensureStableRequestId(existing, prefix = "studio") {
    const current = String(existing || "").trim();
    return current || makeStableRequestId(prefix);
  }

  function estimateBillableImages(count) {
    const free = Number(App.state && (App.state.freeQuotaRemaining ?? App.state.free_quota_remaining));
    if (!Number.isFinite(free)) return 0;
    return Math.max(0, Number(count || 0) - Math.max(0, free));
  }

  // The batch UI displays quantities and forecast charges before the user
  // clicks Execute. A click immediately schedules the task; backend
  // reservation/credit checks remain authoritative and idempotent.
  function confirmPotentialGenerationCost(_count) {
    return true;
  }

  // A priced article action needs explicit opt-in. Price shown here is an
  // estimate; every actual reservation remains verified by the backend.
  async function confirmArticleGenerationCost(count, { replacing = false, skipped = 0 } = {}) {
    const guard = window.HandrawArticleGenerationGuard;
    if (!guard) {
      toast("费用确认模块尚未加载，请刷新页面后重试");
      return false;
    }
    const demo = isDemoGenerationEnabled();
    const free = App.state?.freeQuotaRemaining ?? App.state?.free_quota_remaining;
    const price = CS.serverCfg?.creditPerImage;
    const balance = App.state?.credits;
    const quote = guard.quote(count, { demo, free, unitPrice: price, balance });
    if (!quote.ok) {
      toast(quote.reason);
      return false;
    }
    if (!demo && !quote.affordable) {
      toast("当前积分余额不足，请减少生成张数或补充额度");
      return false;
    }
    const response = await guard.confirmGeneration(count, {
      demo, free, unitPrice: price, balance, replacing, skipped
    });
    return Boolean(response.approved);
  }

  function reconcileDetachedBatchState(parts) {
    if (!parts?.ctrl || !parts?.loop) return false;
    const ctrlId = parts.ctrl.id;
    // Persisted node flags and recovered remote requests do not own a local
    // submission queue. Only its live owner can expose a Stop action.
    if (_activeBatchRun?.ctrlId === ctrlId ||
        (quickBusy?.id === ctrlId && quickBusy.scope === activeCacheScope)) return false;
    const displays = getDownstreamDisplayNodes(ctrlId);
    const stale = parts.ctrl.data.status === "generating" ||
      parts.loop.data.status === "running" ||
      displays.some((node) => node.data?.status === "generating");
    if (!stale) return false;
    const items = displays.flatMap((node) => node.data?.items || []);
    const pending = displays.some((node) => node.data?.pendingTaskId || node.data?.pendingRequestId ||
      Object.keys(node.data?.pendingTasksBySlot || {}).length) ||
      (CS.pendingTasks || []).some((task) => task.ctrlId === ctrlId || task.tabId === CS.activeTabId);
    parts.ctrl.data.status = pending ? "stopped" : items.some((item) => item?.imageUrl) ? "done" : "idle";
    parts.loop.data.status = "idle";
    delete parts.loop.data.isStopping;
    for (const node of displays) {
      if (node.data?.status === "generating") {
        node.data.status = (node.data.items || []).some((item) => item?.imageUrl) ? "done" : "idle";
      }
    }
    // Recovery IDs, results, and billing records stay intact. Reconciliation
    // releases only the abandoned page controls, never a cloud reservation.
    if (window.HandrawBatchCreate) window.HandrawBatchCreate.progressState = null;
    persistOpenTabs();
    return true;
  }

  function reconcileDetachedQuickState(parts) {
    if (!parts?.ctrl) return false;
    const ctrlId = parts.ctrl.id;
    // Saved browser state cannot prove a network request is still owned by
    // this page. Only the live run/quick submit lock may disable editing.
    if (_activeBatchRun?.ctrlId === ctrlId ||
        (quickBusy?.id === ctrlId && quickBusy.scope === activeCacheScope)) return false;
    const displays = getDownstreamDisplayNodes(ctrlId);
    const stale = parts.ctrl.data.status === "generating" ||
      displays.some((node) => node.data?.status === "generating");
    if (!stale) return false;
    const pending = displays.some((node) => node.data?.pendingTaskId ||
      node.data?.pendingRequestId || Object.keys(node.data?.pendingTasksBySlot || {}).length) ||
      (CS.pendingTasks || []).some((task) => task.ctrlId === ctrlId || task.tabId === CS.activeTabId);
    const hasResult = displays.some((node) => (node.data?.items || []).some((item) => item?.imageUrl));
    parts.ctrl.data.status = pending ? "stopped" : hasResult ? "done" : "idle";
    for (const node of displays) {
      if (node.data?.status === "generating") {
        node.data.status = (node.data.items || []).some((item) => item?.imageUrl) ? "done" : "idle";
      }
    }
    // Keep upstream task/request IDs. The resumable poller may still deliver
    // results or refunds; this only unlocks abandoned local form controls.
    persistOpenTabs();
    return true;
  }

  function cancelActiveBatchGeneration(expectedCtrlId = null) {
    const run = _activeBatchRun;
    if (!run && expectedCtrlId) {
      const parts = getBatchParts();
      if (parts?.ctrl.id === expectedCtrlId && reconcileDetachedBatchState(parts)) {
        renderQuickStart();
        toast("已清除页面残留的运行状态；云端任务仍可在生图历史查看。");
        return false;
      }
    }
    // A stale pending remote task must not masquerade as a locally running
    // batch, and a batch button must never cancel a different workstream.
    if (!run || run.cancelled || (expectedCtrlId && run.ctrlId !== expectedCtrlId)) {
      toast("当前没有可停止的批量任务；已提交的云端任务可在生图历史查看。");
      return false;
    }
    run.cancelled = true;
    CS.activeBatchRun = run;
    // Abort the browser's in-flight POST/poll, not just queued worker slots.
    // The gateway might already have accepted a request: abort does NOT
    // cancel the model job or imply that its credits were refunded.
    if (run.controller && !run.controller.signal?.aborted) {
      try { run.controller.abort(); } catch (_) {}
    }
    const quickTask = CS.stageView === "quick" && getQuickParts()?.ctrl.id === run.ctrlId;
    if (!quickTask && window.HandrawBatchCreate?.setStopping) window.HandrawBatchCreate.setStopping();
    const submitted = run.submittedSlots?.size || 0;
    toast(submitted
      ? `正在停止本地等待；${submitted} 张已提交云端的图片仍可能生成或计费，请查看生图历史。`
      : quickTask ? "正在停止当前做图任务；未提交云端的请求不会发出。" :
        "已停止批量生成，尚未提交的图片不会计费。");
    return true;
  }

  function savePrefs() {
    writeJsonStorage(PREFS_STORAGE_KEY, {
      canvasTheme: CS.canvasTheme,
      gridMode: CS.gridMode,
      edgesHidden: CS.edgesHidden,
      snapToGrid: CS.snapToGrid,
      shelfOpen: CS.shelfOpen,
      minimapOpen: CS.minimapOpen,
      engineMode: CS.engineMode
    });
  }

  function cloneGraph(g) {
    return JSON.parse(JSON.stringify(g));
  }

  function normalizeMoodLabel(m) {
    if (!m) return "";
    if (typeof m === "string") {
      const s = m.trim();
      return s === "[object Object]" ? "" : s;
    }
    if (typeof m === "object") {
      const s = String(m.label || m.value || m.name_zh || m.name || "").trim();
      return s === "[object Object]" ? "" : s;
    }
    return "";
  }

  function normalizeRatioInput(raw) {
    return String(raw || "")
      .trim()
      .replace(/[：／/]/g, ":")
      .replace(/\s*:\s*/g, ":");
  }

  function isValidRatioInput(s) {
    const m = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(s);
    if (!m) return false;
    const w = Number(m[1]);
    const h = Number(m[2]);
    return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0;
  }

  function refreshRecentDatalistsDom() {
    if (!DOM.nodesLayer) return;
    const audDl = DOM.nodesLayer.querySelector("#ic-datalist-audience");
    if (audDl) {
      audDl.innerHTML = (CS.recentAudiences || [])
        .slice(0, 8)
        .map((v) => `<option value="${esc(v)}"></option>`)
        .join("");
    }
    const scnDl = DOM.nodesLayer.querySelector("#ic-datalist-scene");
    if (scnDl) {
      scnDl.innerHTML = (CS.recentBusinessScenes || [])
        .slice(0, 8)
        .map((v) => `<option value="${esc(v)}"></option>`)
        .join("");
    }
  }

  function recordRecentFieldValue(kind, rawVal) {
    const val = String(rawVal || "").trim();
    if (!val) return;
    if (kind === "audience") {
      CS.recentAudiences = [val, ...(CS.recentAudiences || []).filter((x) => x !== val)].slice(0, 8);
      writeJsonStorage(RECENT_AUDIENCE_KEY, CS.recentAudiences);
    } else if (kind === "businessScene") {
      CS.recentBusinessScenes = [val, ...(CS.recentBusinessScenes || []).filter((x) => x !== val)].slice(0, 8);
      writeJsonStorage(RECENT_SCENE_KEY, CS.recentBusinessScenes);
    }
    refreshRecentDatalistsDom();
  }

  /* ======================== LEGACY GRAPH NORMALIZER (SAFE JSON IMPORT) ======================== */
  function normalizeGraphSchema(rawGraph) {
    if (!rawGraph || !Array.isArray(rawGraph.nodes)) {
      return E.createBlueprintGraph("single", Catalog, window.HANDRAW_MOCK);
    }
    const g = cloneGraph(rawGraph);
    g.edges = Array.isArray(g.edges) ? g.edges : [];
    g.selectedIds = [];

    if (g.blueprint === "xhs") g.blueprint = "series";

    // Ensure no legacy "photo" or "xhs-batch" mode or outdated input titles remain
    for (const n of g.nodes) {
      if (n.type === "skill_params") {
        n.title = "风格参数";
        if (n.data && Array.isArray(n.data.moods)) {
          n.data.moods = [...new Set(n.data.moods.map(normalizeMoodLabel).filter(Boolean))];
        }
      }
      if (n.type === "asset") n.title = "图片参数";
      if (n.type === "text_input") {
        n.title = "文本参数";
        if (n.data && n.data.fileContent == null) {
          n.data.fileContent = "";
        }
      }
      if (n.type === "bridge") n.title = n.title || "桥接";
      if (n.type === "fission") {
        n.title = n.title || "选题裂变";
        n.w = n.w || 336;
        if (!n.data) n.data = {};
        const validStrats = (E.FISSION_STRATEGIES || []).map((s) => s.id);
        if (!validStrats.includes(n.data.strategy)) n.data.strategy = "daily_quote";
        if (typeof n.data.customStrategy !== "string") n.data.customStrategy = "";
        if (typeof n.data.seedTopic !== "string") n.data.seedTopic = "打工人反内卷治愈手绘日签";
        n.data.targetCount = Math.max(1, Math.min(200, Math.round(Number(n.data.targetCount ?? n.data.count) || 10)));
        delete n.data.count;
        if (!Array.isArray(n.data.generatedItems) || !n.data.generatedItems.length) {
          n.data.generatedItems = E.generateFissionTopics(
            n.data.seedTopic,
            n.data.strategy,
            n.data.targetCount,
            n.data.customStrategy
          );
        }
      }
      if (n.type === "loop") {
        n.title = n.title || "循环批量";
        n.w = n.w || 336;
        if (!n.data) n.data = {};
        const validLoopModes = ["prompts", "styles", "layouts", "assets"];
        if (!validLoopModes.includes(n.data.loopMode)) n.data.loopMode = "prompts";
        if (typeof n.data.promptListText !== "string") {
          n.data.promptListText = Array.isArray(n.data.promptItems) ? n.data.promptItems.join("\n") : "";
        }
        if (!Array.isArray(n.data.styleIds)) n.data.styleIds = [];
        if (!Array.isArray(n.data.layoutIds)) n.data.layoutIds = [];
        n.data.maxIterations = Math.max(1, Math.min(200, Math.round(Number(n.data.maxIterations) || 200)));
        if (n.data.status === "running") n.data.status = "idle";
      }
      if (n.type === "article_plan") {
        n.title = n.title || "文章配图方案";
        if (n.data && !Array.isArray(n.data.cards)) n.data.cards = [];
      }

      if (n.type === "output_control" && n.data) {
        if (n.data.mode === "photo") n.data.mode = "graphic-text";
        if (n.data.mode === "xhs-batch") n.data.mode = "series";
        if (n.data.mode === "article-cover") n.data.mode = "article-illust";
      }
      if (n.type === "output_display" && n.data) {
        if (n.data.mode === "xhs-batch") n.data.mode = "series";
        if (n.data.kind === "batch_gallery" || (Array.isArray(n.data.items) && n.data.items.length > 6)) {
          n.title = "批量图集";
          n.w = 388;
          n.data.kind = "batch_gallery";
          n.data.page = Math.max(1, Number(n.data.page) || 1);
        } else {
          n.title = "图片显示";
          n.w = 308;
          n.data.kind = "single";
        }
      }
      if (n.type === "generator") {
        // Convert legacy generator node into output_control so imported v2/v3 files work seamlessly
        n.type = "output_control";
        n.title = n.title || "输出控制";
        n.w = 344;
        n.h = 348;
        const d = n.data || {};
        const migratedMode = d.mode === "xhs-batch" ? "series" : d.mode && d.mode !== "photo" ? d.mode : "graphic-text";
        n.data = {
          mode: migratedMode,
          count: d.batchCount || 1,
          ratio: d.ratio || "3:4",
          coverRatio: "2.35:1",
          inlineRatio: "4:3",
          includeCover: true,
          mixLayouts: Boolean(d.mixLayouts),
          inlineTheme: d.theme || "",
          status: "idle",
          elapsedSec: 0
        };
      } else if (n.type === "prompt" || n.type === "splitter") {
        const oldText = n.data?.text || "";
        n.type = "text_input";
        n.title = "文本参数";
        n.w = 336;
        n.h = 256;
        n.data = { text: oldText, fileName: "", fileContent: "", fileSize: 0, autoSpawned: false };
      }
    }

    // Split any legacy small multi-image output_display node (<=6 items, non-batch_gallery) into individual 1-image "图片显示" nodes
    const splitNewNodes = [];
    for (const n of g.nodes) {
      if (
        n.type === "output_display" &&
        n.data?.kind !== "batch_gallery" &&
        Array.isArray(n.data?.items) &&
        n.data.items.length > 1 &&
        n.data.items.length <= 6
      ) {
        const allItems = n.data.items;
        n.data.items = [allItems[0]];
        n.data.slotIndex = 0;
        const upEdge = g.edges.find((e) => e.to === n.id);
        for (let k = 1; k < allItems.length; k++) {
          const extra = E.makeOutputDisplayNode(n.x, n.y + k * 336, {
            title: "图片显示",
            status: n.data.status || "done",
            mode: n.data.mode || "graphic-text",
            slotIndex: k,
            sourceNodeId: upEdge ? upEdge.from : "",
            updatedAt: n.data.updatedAt || "",
            runCount: n.data.runCount || 1,
            items: [allItems[k]]
          });
          splitNewNodes.push(extra);
          if (upEdge) {
            g.edges.push({ id: E.uid("edge"), from: upEdge.from, to: extra.id });
          }
        }
      }
    }
    if (splitNewNodes.length) {
      g.nodes.push(...splitNewNodes);
    }

    return g;
  }

  /* ======================== CLOUD WORKSPACE SYNC & WORKFLOW LIBRARY ======================== */
  function studioApiPost(url, payload, { requestScope = activeCacheScope, requestEpoch = cacheScopeEpoch } = {}) {
    if (!App.state || !App.state.serverBacked || !App.state.loggedIn) return Promise.resolve(null);
    if (requestScope !== activeCacheScope || requestEpoch !== cacheScopeEpoch) return Promise.resolve(null);
    return fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    })
      .then((r) => {
        if (requestScope !== activeCacheScope || requestEpoch !== cacheScopeEpoch) return null;
        return r.ok ? r.json() : null;
      })
      .catch(() => null);
  }

  const ARTICLE_RUNTIME_FIELDS = new Set([
    "imageUrl", "status", "errorText", "errorMsg", "taskId", "requestId", "genId", "batchId",
    "batchIndex", "batchTotal", "generationMode", "demoMode", "variants", "_genCount", "engine",
    "selectedMediaId", "illustrationId", "activeAttemptId", "resultEpoch", "updatedAt", "generatedAt"
  ]);

  function articleCloudPayload(article) {
    return {
      id: article.id, articleTitle: article.articleTitle || article.title || "未命名文章",
      markdown: article.markdown || "",
      cards: (article.cards || []).map(card => Object.fromEntries(
        Object.entries(card).filter(([key]) => !ARTICLE_RUNTIME_FIELDS.has(key)))),
      style1: article.style1 || "", layout: article.layout || "", status: "ready",
      runCount: article.runCount || 0, createdAtMs: article.createdAtMs || 0,
      settings: { ...(article.settings || {}),
        coverRatio: article.coverRatio || article.settings?.coverRatio || "2.35:1",
        inlineRatio: article.inlineRatio || article.settings?.inlineRatio || "4:3" }
    };
  }

  async function flushCloudArticlesSync() {
    if (!App.state?.serverBacked || !App.state?.loggedIn) return true;
    if (_articlesCloudConflict) return false;
    if (_articlesSyncTimer) clearTimeout(_articlesSyncTimer);
    _articlesSyncTimer = null;
    if (_articlesSyncPromise) return _articlesSyncPromise;
    const requestScope = activeCacheScope, requestEpoch = cacheScopeEpoch;
    const sameScope = () => requestScope === activeCacheScope && requestEpoch === cacheScopeEpoch;
    _articlesSyncInFlight = true;
    const operation = (async () => {
      try {
        while (sameScope()) {
          const changed = (CS.myArticles || []).filter(article=>!article._summary).map(articleCloudPayload)
            .filter(article => _articleCloudSnapshots.get(String(article.id)) !== JSON.stringify(article))
            .slice(0, 50);
          if (!changed.length) {
            _articlesSyncedVersion = _articlesSyncVersion;
            setArticlesSyncStatus("synced");
            return true;
          }
          setArticlesSyncStatus("syncing");
          const response = await fetch("/api/studio/articles", {
            method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ articles: changed.map(article => ({ ...article,
              baseUpdatedAtMs: _articleCloudBases.get(String(article.id)) ?? 0 })) })
          });
          const result = await response.json().catch(() => ({}));
          if (!sameScope()) return false;
          if (response.status === 409) {
            _articlesCloudConflict = true;
            writeJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, { createdAt: Date.now(),
              articles: JSON.parse(JSON.stringify(CS.myArticles || [])), activeId: CS.activeArticleId || "" });
            setArticlesSyncStatus("conflict");
            toast("另一窗口已更新文章，已保留本地稿并停止覆盖。请合并内容或另存为新文章。");
            return false;
          }
          if (!response.ok || !result.ok) {
            setArticlesSyncStatus("failed");
            return false;
          }
          for (const article of changed) {
            const id = String(article.id);
            if (result.versions?.[id] == null) {
              setArticlesSyncStatus("failed");
              return false;
            }
            _articleCloudBases.set(id, Number(result.versions[id]));
            _articleCloudSnapshots.set(id, JSON.stringify(article));
          }
        }
        return false;
      } catch (_) {
        if (sameScope()) setArticlesSyncStatus("failed");
        return false;
      }
    })();
    _articlesSyncPromise = operation;
    try { return await operation; }
    finally {
      if (_articlesSyncPromise === operation) {
        _articlesSyncPromise = null;
        _articlesSyncInFlight = false;
      }
    }
  }

  function scheduleCloudArticlesSync() {
    if (!App.state?.serverBacked || !App.state?.loggedIn) { setArticlesSyncStatus("local"); return; }
    _articlesSyncVersion += 1;
    if (_articlesCloudConflict) { setArticlesSyncStatus("conflict"); return; }
    setArticlesSyncStatus("pending");
    if (_articlesSyncTimer) clearTimeout(_articlesSyncTimer);
    _articlesSyncTimer = setTimeout(() => { void flushCloudArticlesSync(); }, 450);
  }

  async function selectArticleCardImage(target, card, imageUrl) {
    if (App.state?.serverBacked && App.state?.loggedIn) {
      if (!(await flushCloudArticlesSync())) throw new Error("文章尚未保存到云端");
      const result = await S.apiJson(`/api/studio/articles/${encodeURIComponent(target.art.id)}`, {});
      const current = result?.article?.cards?.find(item => item.id === card.id);
      if (!current) throw new Error("配图位已删除");
      if (card.resultEpoch != null && card.resultEpoch !== current.resultEpoch)
        throw new Error("配图状态已在其他窗口更新，请刷新后重选");
      const selection = await S.apiJson(`/api/studio/articles/${encodeURIComponent(target.art.id)}/illustrations/${encodeURIComponent(card.id)}/selection`, {
        method: "POST", body: { baseResultEpoch: current.resultEpoch, imageUrl }
      });
      card.resultEpoch = selection.resultEpoch;
      card.selectedMediaId = selection.selectedMediaId;
    }
    if (card.imageUrl && card.imageUrl !== imageUrl)
      window.HandrawArticleWorkbench?.pushVariant(card, card.imageUrl, "之前使用的图片");
    card.imageUrl = imageUrl;
    card.status = imageUrl ? "done" : "pending";
    card.errorText = "";
    commitArticleTargetChanges(target, { bumpTime: true });
  }

  async function ensureWorkspaceCollection(collection) {
    if(!App.state?.loggedIn||!App.state?.serverBacked||_workspaceCollectionsReady.has(collection)) return;
    if(_workspaceCollectionsLoading.has(collection)) return _workspaceCollectionsLoading.get(collection);
    const promise=hydrateCloudStudioWorkspace({collection});
    _workspaceCollectionsLoading.set(collection,promise);
    try {await promise;} finally {if(_workspaceCollectionsLoading.get(collection)===promise) _workspaceCollectionsLoading.delete(collection);}
  }

  async function loadMoreStudioHistory() {
    if(!CS.historyCursor||CS.historyLoading) return;
    const epoch=cacheScopeEpoch,scope=activeCacheScope;
    CS.historyLoading=true;CS.historyError="";
    if(CS.stageView==="history") renderHistoryStage();
    try {await hydrateCloudStudioWorkspace({collection:"history",cursor:CS.historyCursor});}
    finally {
      if(!isStaleScope(epoch,scope)) {
        CS.historyLoading=false;
        if(CS.stageView==="history") renderHistoryStage();
      }
    }
  }

  async function loadArticleDocument(id) {
    const epoch=cacheScopeEpoch,scope=activeCacheScope;
    const result=await S.apiJson(`/api/studio/articles/${encodeURIComponent(id)}`);
    if(isStaleScope(epoch,scope)) return false;
    const previous=findArticleById(id),article=result.article;
    if(!article) throw new Error("文章不存在");
    const payload=articleCloudPayload(article);
    if(previous && !previous._summary && _articleCloudSnapshots.has(id) &&
        JSON.stringify(articleCloudPayload(previous))!==_articleCloudSnapshots.get(id))
      throw new Error("当前文章有未保存内容，请先保存后再重新载入");
    CS.myArticles=(CS.myArticles || []).map(item=>item.id===id?{...article,_summary:false}:item);
    if(!previous) CS.myArticles.push({...article,_summary:false});
    _articleCloudBases.set(id,Number(article.updatedAtMs));
    _articleCloudSnapshots.set(id,JSON.stringify(payload));
    writeJsonStorage(MY_ARTICLES_STORAGE_KEY,CS.myArticles);
    return true;
  }

  async function hydrateCloudStudioWorkspace({collection="",cursor=""}={}) {
    if (!App.state || !App.state.serverBacked) return;
    const requestScope = activeCacheScope;
    const requestEpoch = cacheScopeEpoch;
    if (!collection && _workspaceHydrationController) {
      try {
        _workspaceHydrationController.abort();
      } catch (_) {}
    }
    if(!collection) _workspaceHydrationController = typeof AbortController !== "undefined" ? new AbortController() : null;
    try {
      const resp = await fetch(collection?`/api/studio/workspace?collection=${encodeURIComponent(collection)}${cursor?"&cursor="+encodeURIComponent(cursor):""}`:"/api/studio/workspace?bootstrap=1", {
        credentials: "include",
        signal: !collection && _workspaceHydrationController ? _workspaceHydrationController.signal : undefined
      });
      if (!resp.ok) throw new Error("云端记录载入失败，请重试");
      const ws = await resp.json();
      if (requestScope !== activeCacheScope || requestEpoch !== cacheScopeEpoch) return;
      while(ws.articleCursor) {
        const page=await S.apiJson(`/api/studio/articles?page=1&cursor=${encodeURIComponent(ws.articleCursor)}`);
        if(requestScope!==activeCacheScope||requestEpoch!==cacheScopeEpoch) return;
        ws.articles.push(...(page.items||[]));ws.articleCursor=page.nextCursor;
      }
      if(collection) _workspaceCollectionsReady.add(collection);
      if (Array.isArray(ws.officialPresets)) {
        CS.officialPresetMeta = ws.officialPresets;
      }
      if(Array.isArray(ws.pendingTasks)) CS.pendingTasks = Array.isArray(ws.pendingTasks)
        ? ws.pendingTasks.filter((task) => task && (task.taskId || task.requestId || task.genId))
        : [];
      if (ws.loggedIn) {
        ensureDefaultSavedWorkflows();
        if (Array.isArray(ws.workflows) && ws.workflows.length) {
          const byId = new Map((CS.savedWorkflows || []).map((w) => [w.id, w]));
          ws.workflows.forEach((rw) => {
            if (!rw || !rw.id || !rw.graph) return;
            const normG = normalizeGraphSchema(rw.graph);
            const item = {
              id: rw.id,
              title: rw.title || "云端工作流",
              updatedAt: "云端同步",
              updatedAtMs: Number(rw.updatedAtMs) || Date.now(),
              blueprint: rw.blueprint || normG.blueprint || "single",
              graph: normG
            };
            const prev = byId.get(rw.id);
            if (!prev || (Number(rw.updatedAtMs) || 0) >= (Number(prev.updatedAtMs) || 0)) {
              byId.set(rw.id, item);
            }
          });
          const customs = [...byId.values()].filter((w) => !w.isOfficialPreset);
          const officials = buildOfficialPresetWorkflows();
          CS.savedWorkflows = [...customs, ...officials];
          writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
        }

        if (Array.isArray(ws.articles)) {
          ensureMyArticlesInitialized();
          const conflictBackup = readJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, null);
          if (conflictBackup?.articles?.length) {
            _articlesCloudConflict = true;
            setArticlesSyncStatus("conflict");
          }
          const serverIds = new Set(ws.articles.map((a) => a.id));
          const artMap = new Map();
          ws.articles.forEach((ra) => {
            if (!ra || !ra.id) return;
            _articleCloudBases.set(String(ra.id), Number(ra.updatedAtMs) || 0);
            if(!ra._summary) _articleCloudSnapshots.set(String(ra.id), JSON.stringify(articleCloudPayload(ra)));
            const prev = (CS.myArticles || []).find((a) => a.id === ra.id);
            // A newer local/offline draft must be recoverable before the
            // cloud workspace replaces its in-memory representation.
            if (prev && !prev._summary && Number(prev.updatedAtMs || 0) > Number(ra.updatedAtMs || 0) &&
                (String(prev.markdown || "") !== String(ra.markdown || "") ||
                 JSON.stringify(prev.cards || []) !== JSON.stringify(ra.cards || []))) {
              const saved = readJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, null);
              const copy = saved?.articles?.length ? saved.articles.filter((a) => a.id !== prev.id) : [];
              copy.push(JSON.parse(JSON.stringify(prev)));
              writeJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, {
                createdAt: Date.now(), articles: copy, activeId: prev.id
              });
              _articlesCloudConflict = true;
              setArticlesSyncStatus("conflict");
            }
            artMap.set(ra.id, {
              ...(prev || {}),
              id: ra.id,
              articleTitle: ra.articleTitle || "未命名文章",
              _summary:Boolean(ra._summary),
              settings:ra.settings||{},coverRatio:ra.coverRatio||"2.35:1",inlineRatio:ra.inlineRatio||"4:3",
              markdown: ra.markdown || "",
              cards: Array.isArray(ra.cards) ? ra.cards : [],
              style1: ra.style1 || "",
              layout: ra.layout || "",
              status: ra.status || "ready",
              runCount: Number(ra.runCount) || 0,
              createdAtMs: Number(ra.createdAtMs) || Date.now(),
              updatedAtMs: Number(ra.updatedAtMs) || Date.now(),
              timeLabel: typeof formatArticleTimeLabel === "function" ? formatArticleTimeLabel(Number(ra.updatedAtMs) || Date.now()) : "近期"
            });
            if(ra._summary && prev && !prev._summary && Number(prev.updatedAtMs)===Number(ra.updatedAtMs))
              artMap.set(ra.id,prev);

          });
          (CS.myArticles || []).forEach((a) => {
            if (!a || !a.id || serverIds.has(a.id)) return;
            if (a.isNewDraft) {
              artMap.set(a.id, a);
              return;
            }
            // Could be an offline-created article or one deleted remotely.
            // Preserve a private recoverable copy; never resurrect it silently.
            const saved = readJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, null);
            const copies = (saved?.articles || []).filter((b) => b.id !== a.id);
            copies.push(JSON.parse(JSON.stringify(a)));
            writeJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, {
              createdAt: Date.now(), articles: copies, activeId: a.id
            });
            _articlesCloudConflict = true;
            setArticlesSyncStatus("conflict");
          });
          CS.myArticles = [...artMap.values()];
          writeJsonStorage(MY_ARTICLES_STORAGE_KEY, CS.myArticles);
        }

        if (Array.isArray(ws.uploads) && ws.uploads.length) {
          const upMap = new Map((CS.customUploads || []).map((u) => [u.id, u]));
          ws.uploads.forEach((ru) => {
            if (!ru || !ru.id) return;
            upMap.set(ru.id, {
              id: ru.id,
              name: ru.name_zh || ru.name || "云端图参",
              desc: ru.desc_zh || ru.desc || "云端上传图参",
              cat: ru.cat || "other",
              image: ru.image,
              dataUrl: ru.image
            });
          });
          CS.customUploads = [...upMap.values()];
          writeJsonStorage(UPLOAD_STORAGE_KEY, CS.customUploads);
        }

        if (Array.isArray(ws.history) && ws.history.length) {
          let curHist = Array.isArray(CS.generationHistory) ? CS.generationHistory : [];
          for (const sRow of ws.history) {
            curHist = upsertHistoryEntry(curHist, sRow, { isServer: true });
          }
          CS.generationHistory = curHist.sort((a,b)=>(Date.parse(b.createdAtISO||b.createdAt)||0)-(Date.parse(a.createdAtISO||a.createdAt)||0));
          writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
        }
        if(collection==="history") {CS.historyCursor=ws.nextCursor||"";CS.historyError="";}
      } else if (Array.isArray(CS.officialPresetMeta)) {
        // Refresh official preset overrides even for guests
        const officialList = buildOfficialPresetWorkflows();
        const customOnly = (CS.savedWorkflows || []).filter((w) => w && !w.isOfficialPreset && !/^preset_/.test(w.id));
        CS.savedWorkflows = [...customOnly, ...officialList];
        writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
      }
    } catch (_) {
      if(collection==="history" && !isStaleScope(requestEpoch,requestScope))
        CS.historyError="云端记录载入失败，请重试";
      // Abort and stale responses are expected during account switches. Do
      // not let an old account repopulate the newly selected cache scope.
    } finally {
      if (requestScope === activeCacheScope && requestEpoch === cacheScopeEpoch) {
        _workspaceHydrationController = null;
      }
    }
  }

  function buildOfficialPresetWorkflows() {
    const baseDefs = E.PRESET_WORKFLOW_DEFS || [];
    if (Array.isArray(CS.officialPresetMeta) && CS.officialPresetMeta.length) {
      const defByBp = new Map(baseDefs.map((d) => [d.blueprint, d]));
      const defById = new Map(baseDefs.map((d) => [d.id, d]));
      return CS.officialPresetMeta.map((meta) => {
        const def = defById.get(meta.id) || defByBp.get(meta.blueprint) || { blueprint: meta.blueprint || "single" };
        const bp = meta.blueprint || def.blueprint || "single";
        return {
          id: meta.id || def.id,
          title: meta.title || def.title || "官方示范工作流",
          scenarioBadge: meta.scenario_badge || def.scenarioBadge || "官方示范",
          scenarioDesc: meta.scenario_desc || def.scenarioDesc || "",
          isOfficialPreset: true,
          updatedAt: "官方场景示范",
          blueprint: bp,
          graph: E.createBlueprintGraph(bp, Catalog, window.HANDRAW_MOCK, { withPresetAssets: true })
        };
      });
    }
    return baseDefs.map((def) => ({
      id: def.id,
      title: def.title,
      scenarioBadge: def.scenarioBadge || "官方示范",
      scenarioDesc: def.scenarioDesc || "",
      isOfficialPreset: true,
      updatedAt: "官方场景示范",
      blueprint: def.blueprint,
      graph: E.createBlueprintGraph(def.blueprint, Catalog, window.HANDRAW_MOCK, { withPresetAssets: true })
    }));
  }

  function ensureDefaultSavedWorkflows() {
    const officialList = buildOfficialPresetWorkflows();
    const officialMap = new Map(officialList.map((w) => [w.id, w]));

    if (Array.isArray(CS.savedWorkflows)) {
      let mutated = false;
      // Remove superseded pre-v24 built-in presets while preserving all user-saved custom workflows
      const userSaved = CS.savedWorkflows.filter((w) => {
        if (!w || !w.id) return false;
        if (/^preset_v(6|10|23)_/.test(w.id)) {
          mutated = true;
          return false;
        }
        return !officialMap.has(w.id);
      });
      const existingOfficial = CS.savedWorkflows.filter((w) => w && officialMap.has(w.id));
      if (existingOfficial.length !== officialList.length) {
        CS.savedWorkflows = [...userSaved, ...officialList];
        mutated = true;
      } else {
        // Hydrate scenarioBadge / scenarioDesc on existing v24 presets
        CS.savedWorkflows.forEach((w) => {
          const def = officialMap.get(w.id);
          if (def && (!w.scenarioDesc || !w.scenarioBadge)) {
            w.scenarioBadge = def.scenarioBadge;
            w.scenarioDesc = def.scenarioDesc;
            w.isOfficialPreset = true;
            mutated = true;
          }
        });
      }
      if (mutated) writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
      return;
    }

    CS.savedWorkflows = officialList;
    writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
  }

  function syncCurrentTabSnapshot() {
    const cur = CS.tabs.find((t) => t.id === CS.activeTabId);
    if (!cur) return;
    cur.graph = cloneGraph(CS.graph);
    cur.vx = CS.vx;
    cur.vy = CS.vy;
    cur.vk = CS.vk;
    cur.undoStack = CS.undoStack.slice(-15);
    cur.redoStack = CS.redoStack.slice(-15);
  }

  function persistOpenTabs() {
    syncCurrentTabSnapshot();
    // The article workspace tab is created on demand to back the article editor;
    // it is not a preset the user picked, so persisting it made 📝 文章配图
    // reappear in the canvas tab strip after any visit to 文章模式.
    const slimTabs = CS.tabs
      .filter((t) => t.blueprint !== "article")
      .map((t) => ({
        id: t.id,
        title: t.title,
        blueprint: t.blueprint,
        dirty: Boolean(t.dirty),
        savedId: t.savedId || null,
        vx: t.vx,
        vy: t.vy,
        vk: t.vk,
        graph: t.graph,
        quickStart: t.quickStart === true,
        batchStart: t.batchStart === true
      }));
    writeJsonStorage(OPEN_TABS_KEY, { activeTabId: CS.activeTabId, tabs: slimTabs });
  }

  function createWorkflowTab({
    title,
    blueprint = "single",
    graph = null,
    savedId = null,
    makeActive = true,
    autoFit = true,
    switchToCanvas = false
  }) {
    if (CS.activeTabId) syncCurrentTabSnapshot();
    const g = graph ? normalizeGraphSchema(graph) : E.createBlueprintGraph(blueprint, Catalog, window.HANDRAW_MOCK);
    g.selectedIds = [];
    const tab = {
      id: E.uid("wftab"),
      title: title || "未命名工作流",
      blueprint: g.blueprint || blueprint,
      dirty: false,
      savedId,
      vx: 290,
      vy: 48,
      vk: 0.85,
      undoStack: [],
      redoStack: [],
      graph: g
    };
    CS.tabs.push(tab);
    if (makeActive) {
      activateWorkflowTab(tab.id, { autoFit, switchToCanvas });
    } else {
      persistOpenTabs();
      renderTopAndBottomDocks();
    }
    return tab;
  }

  function isArticleBlueprint(graph) {
    return String(graph?.blueprint || "") === "article";
  }

  function isArticleGraph(graph) {
    if (!graph) return false;
    if (isArticleBlueprint(graph)) return true;
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    return nodes.some((n) =>
      n.type === "article_plan" ||
      n.type === "article" ||
      (n.type === "output_control" && n.data?.mode === "article-illust")
    );
  }

  function isArticleTab(tab) {
    if (!tab) return false;
    return isArticleGraph(tab.id === CS.activeTabId ? CS.graph : tab.graph);
  }

  function currentCacheScopeKey() {
    try {
      return String(typeof activeCacheScope !== "undefined" && activeCacheScope ? activeCacheScope : "");
    } catch (_) {
      return "";
    }
  }

  function findArticleWorkspaceTab() {
    return CS.tabs.find((t) => isArticleTab(t)) || null;
  }

  function ensureArticleWorkspace() {
    // Article documents have their own store and never allocate a canvas tab.
    ensureMyArticlesInitialized();
    return null;
  }

  function pickReturnCanvasTab(excludeId) {
    // Existing non-article tab other than the current article tab.
    const candidates = CS.tabs.filter((t) => t.id !== excludeId && !isArticleTab(t));
    if (candidates.length) return candidates[candidates.length - 1].id;
    return null;
  }

  function readScopedReturnTab() {
    const rec = CS.articleReturnTab;
    if (!rec || typeof rec !== "object") return null;
    if (rec.scope !== currentCacheScopeKey()) return null;
    const tab = CS.tabs.find((t) => t.id === rec.id);
    return tab && !isArticleTab(tab) ? tab.id : null;
  }

  function writeScopedReturnTab(id) {
    if (id && CS.tabs.some((t) => t.id === id && !isArticleTab(t))) {
      CS.articleReturnTab = { scope: currentCacheScopeKey(), id };
    } else {
      delete CS.articleReturnTab;
    }
  }

  function switchIntoArticleMode() {
    syncAllTabsArticlesIntoStore();
    ensureMyArticlesInitialized();
    if (CS.stageView !== "preview" || CS.articleSubView !== "editor" || !CS.articleEditorDraft) {
      const targetId=CS.activeArticleId || null;
      openUnifiedArticleEditor(targetId,{createNew:!targetId,renderNow:false});
    } else {
      CS.stageView="preview";
      CS.articleSubView="editor";
    }
  }

  function switchToCanvasFromArticle() {
    CS.stageView="canvas";
  }

  function activateWorkflowTab(tabId, { autoFit = false, switchToCanvas = false } = {}) {
    if (CS.activeTabId) {
      syncCurrentTabSnapshot();
    }
    if (switchToCanvas && CS.stageView !== "canvas") {
      CS.stageView = "canvas";
      try {
        if (window.location.search.includes("view=")) {
          window.history.replaceState(null, "", window.location.pathname);
        }
      } catch (_) {}
    }
    const target = CS.tabs.find((t) => t.id === tabId);
    if (!target) return;
    const targetIsArticle = isArticleGraph(normalizeGraphSchema(target.graph));
    if (switchToCanvas && targetIsArticle && !isArticleGraph(CS.graph) && CS.activeTabId) {
      writeScopedReturnTab(CS.activeTabId);
    }
    CS.activeTabId = target.id;
    CS.graph = normalizeGraphSchema(target.graph);
    CS.vx = target.vx ?? 290;
    CS.vy = target.vy ?? 48;
    CS.vk = target.vk ?? 0.85;
    CS.undoStack = target.undoStack || [];
    CS.redoStack = target.redoStack || [];
    CS.selectedEdgeId = null;
    CS.arrangeUndoSnapshot = null;
    if (isArticleGraph(CS.graph)) {
      CS.previewTab = "article";
    } else if (CS.graph.blueprint === "series" || CS.graph.blueprint === "xhs") {
      CS.previewTab = "series";
    }
    if (switchToCanvas && targetIsArticle) {
      CS.stageView = "preview";
      CS.articleSubView = "portal";
      try {
        const u = new URL(window.location.href);
        u.searchParams.delete("view");
        u.searchParams.delete("tab");
        u.searchParams.set("entry", "article");
        window.history.replaceState(null, "", u.pathname + u.search);
      } catch (_) {}
    }
    if (DOM.world) {
      fullRenderCanvas();
      applyViewportTransform();
      if (autoFit) requestAnimationFrame(() => fitView());
      requestAnimationFrame(() => scrollActiveTabIntoView());
    }
    persistOpenTabs();
  }

  function closeWorkflowTab(tabId) {
    const idx = CS.tabs.findIndex((t) => t.id === tabId);
    if (idx < 0) return;
    CS.tabs.splice(idx, 1);
    if (!CS.tabs.length) {
      CS.activeTabId = null;
      CS.graph = { blueprint: "blank", nodes: [], edges: [], selectedIds: [] };
      persistOpenTabs();
      fullRenderCanvas();
      return;
    }
    if (CS.activeTabId === tabId) {
      const next = CS.tabs[Math.max(0, idx - 1)];
      activateWorkflowTab(next.id, { autoFit: false });
    } else {
      persistOpenTabs();
      renderTopAndBottomDocks();
    }
  }

  function markActiveTabDirty() {
    const cur = CS.tabs.find((t) => t.id === CS.activeTabId);
    if (cur) cur.dirty = true;
  }

  function saveCurrentWorkflow(asNew = false) {
    syncCurrentTabSnapshot();
    const cur = CS.tabs.find((t) => t.id === CS.activeTabId);
    if (!cur) return;
    ensureDefaultSavedWorkflows();

    const nowStr = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const nowMs = Date.now();
    const existing = !asNew && cur.savedId ? CS.savedWorkflows.find((w) => w.id === cur.savedId && !w.isOfficialPreset) : null;
    let savedTarget = null;

    if (existing) {
      existing.title = cur.title;
      existing.updatedAt = `今天 ${nowStr}`;
      existing.updatedAtMs = nowMs;
      existing.blueprint = CS.graph.blueprint;
      existing.graph = cloneGraph(CS.graph);
      savedTarget = existing;
    } else {
      const newId = E.uid("savedwf");
      cur.savedId = newId;
      savedTarget = {
        id: newId,
        title: asNew ? `${cur.title} (副本)` : cur.title,
        updatedAt: `今天 ${nowStr}`,
        updatedAtMs: nowMs,
        blueprint: CS.graph.blueprint,
        graph: cloneGraph(CS.graph)
      };
      CS.savedWorkflows.unshift(savedTarget);
    }
    cur.dirty = false;
    writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
    persistOpenTabs();
    renderTopAndBottomDocks();
    studioApiPost("/api/studio/workflows", {
      id: savedTarget.id,
      title: savedTarget.title,
      blueprint: savedTarget.blueprint,
      graph: savedTarget.graph,
      updatedAtMs: nowMs
    });
    toast(`💾 工作流《${cur.title}》已保存！（共 ${CS.graph.nodes.length} 个节点）`);
  }

  function exportWorkflowJsonFile(wfObj) {
    const payload = {
      schema: "handraw.workflow.v4",
      exportedAt: new Date().toISOString(),
      title: wfObj.title || "Handraw工作流",
      blueprint: wfObj.graph?.blueprint || wfObj.blueprint || "single",
      graph: wfObj.graph
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const a = document.createElement("a");
    const safeName = String(payload.title).replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 32) || "workflow";
    a.href = URL.createObjectURL(blob);
    a.download = `${safeName}.handraw.json`;
    a.click();
    toast(`📥 已导出工作流文件 ${safeName}.handraw.json`);
  }

  function importWorkflowJsonObject(rawObj, fallbackName = "导入的工作流") {
    const g = rawObj?.graph && Array.isArray(rawObj.graph.nodes) ? rawObj.graph : Array.isArray(rawObj?.nodes) ? rawObj : null;
    if (!g) {
      toast("⚠️ 无效的工作流 JSON 文件格式");
      return;
    }
    ensureDefaultSavedWorkflows();
    const title = rawObj.title || fallbackName.replace(/\.handraw\.json$|\.json$/i, "");
    const normGraph = normalizeGraphSchema(g);
    const savedId = E.uid("savedwf");
    const nowStr = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const nowMs = Date.now();
    const importedWf = {
      id: savedId,
      title: `📂 ${title}`,
      updatedAt: `导入于 ${nowStr}`,
      updatedAtMs: nowMs,
      blueprint: normGraph.blueprint || "single",
      graph: cloneGraph(normGraph)
    };
    CS.savedWorkflows.unshift(importedWf);
    writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
    studioApiPost("/api/studio/workflows", {
      id: importedWf.id,
      title: importedWf.title,
      blueprint: importedWf.blueprint,
      graph: importedWf.graph,
      updatedAtMs: nowMs
    });

    CS.stageView = "canvas";
    try {
      if (window.location.search.includes("view=")) {
        window.history.replaceState(null, "", window.location.pathname);
      }
    } catch (_) {}

    createWorkflowTab({
      title: `📂 ${title}`,
      blueprint: normGraph.blueprint || "single",
      graph: normGraph,
      savedId,
      makeActive: true,
      autoFit: true,
      switchToCanvas: true
    });
    toast(`🎉 已导入并打开工作流《${title}》！`);
  }

  function openWorkflowsPage({ renderNow = true } = {}) {
    ensureDefaultSavedWorkflows();
    syncCurrentTabSnapshot();
    CS.stageView = "workflows";
    try {
      window.history.replaceState(null, "", "?view=workflows");
    } catch (_) {}
    if (renderNow) {
      renderTopAndBottomDocks();
    }
  }

  function openWorkflowLibraryModal() {
    openWorkflowsPage();
  }

  function renderWorkflowsStage() {
    void ensureWorkspaceCollection("workflows").then(()=>{
      if(CS.stageView==="workflows" && _workspaceCollectionsReady.has("workflows")) renderLoadedWorkflowsStage();
    });
    renderLoadedWorkflowsStage();
  }

  function renderLoadedWorkflowsStage() {
    if (!DOM.workflowsStage) return;
    if (CS.stageView !== "workflows") {
      DOM.workflowsStage.style.display = "none";
      return;
    }
    DOM.workflowsStage.style.display = "flex";
    ensureDefaultSavedWorkflows();

    const wasSearchFocused = document.activeElement && document.activeElement.id === "wf-search-inp";
    const allWf = CS.savedWorkflows || [];
    const q = String(CS.workflowQuery || "").trim().toLowerCase();
    const filtered = allWf.filter((wf) => {
      if (!q) return true;
      return (
        String(wf.title || "").toLowerCase().includes(q) ||
        String(wf.scenarioBadge || "").toLowerCase().includes(q) ||
        String(wf.scenarioDesc || "").toLowerCase().includes(q) ||
        String(wf.updatedAt || "").toLowerCase().includes(q)
      );
    });

    const nodeTypeMeta = {
      skill_params: "风格参数",
      asset: "图片参数",
      text_input: "文本参数",
      fission: "AI 扩写主题",
      loop: "批量",
      bridge: "多尺寸输出",
      output_control: "生成设置",
      article_plan: "文章配图方案",
      output_display: "成图显示"
    };

    DOM.workflowsStage.innerHTML = `
      <div class="ic-wf-minimal-tools" role="search">
        <input type="search" class="hw-input" id="wf-search-inp"
          value="${esc(CS.workflowQuery || "")}" placeholder="搜索工作流…" aria-label="搜索工作流" />
        <label class="btn btn-primary btn-sm" style="cursor:pointer;font-weight:800;">
          导入工作流
          <input type="file" id="wf-import-file-inp" accept=".json,application/json" hidden />
        </label>
      </div>

      <div class="ic-wf-page-scroll" id="wf-page-scroll">
        <div class="ic-wf-page-inner">
          ${
            filtered.length === 0
              ? `
                <div style="padding:76px 24px;text-align:center;background:var(--ic-panel-solid);border:1px dashed var(--ic-border-strong);border-radius:18px;">
                  <div style="font-size:16px;font-weight:850;color:var(--ic-ink);margin-bottom:6px;">${
                    allWf.length === 0 ? "暂无已保存的工作流" : "没有匹配搜索词的工作流"
                  }</div>
                  <div style="font-size:13px;color:var(--ic-muted);">可在「画布」中保存工作流，或使用上方按钮导入 JSON 工作流。</div>
                </div>
              `
              : `
                <div class="ic-wf-card-grid" id="wf-saved-list-box">
                  ${filtered
                    .map((wf) => {
                      const nodes = wf.graph?.nodes || [];
                      const edges = wf.graph?.edges || [];
                      const countsByType = {};
                      nodes.forEach((n) => {
                        countsByType[n.type] = (countsByType[n.type] || 0) + 1;
                      });
                      const typePills = Object.entries(countsByType)
                        .map(([t, cnt]) => `<span class="ic-v4-tag" style="font-size:11px;background:var(--ic-surface);">${esc(nodeTypeMeta[t] || t)}${cnt > 1 ? ` ×${cnt}` : ""}</span>`)
                        .join("");

                      return `
                        <article class="ic-wf-entry-card" data-wf-id="${esc(wf.id)}">
                          <div class="ic-wf-card-content">
                            <div class="ic-wf-card-heading">
                              ${wf.scenarioBadge
                                ? `<span class="ic-node-badge ${wf.blueprint === "loop_100" || wf.blueprint === "style_ab" ? "ic-badge-loop" : wf.blueprint === "omnimedia" ? "ic-badge-bridge" : "ic-badge-output-ctrl"}">${esc(wf.scenarioBadge)}</span>`
                                : `<span class="ic-wf-card-type">工作流</span>`}
                              <strong class="ic-wf-card-title">${esc(wf.title || "未命名工作流")}</strong>
                            </div>
                            <div class="ic-wf-card-meta">
                              <span>${nodes.length} 个节点</span>
                              <span>${edges.length} 条连线</span>
                              <span>${esc(wf.updatedAt || "已保存")}</span>
                            </div>
                            ${wf.scenarioDesc ? `<p class="ic-wf-card-description">${esc(wf.scenarioDesc)}</p>` : ""}
                            ${typePills ? `<div class="ic-wf-card-tags">${typePills}</div>` : ""}
                          </div>
                          <div class="ic-wf-card-actions">
                            <button type="button" class="btn btn-sm btn-primary" data-wf-open="${esc(wf.id)}">查看存档</button>
                            <button type="button" class="btn btn-sm" data-wf-dl="${esc(wf.id)}">导出 JSON</button>
                            <button type="button" class="btn btn-sm" data-wf-rm="${esc(wf.id)}" title="删除此工作流">删除</button>
                          </div>
                        </article>
                      `;
                    })
                    .join("")}
                </div>
              `
          }
        </div>
      </div>
    `;

    if (wasSearchFocused) {
      const inp = DOM.workflowsStage.querySelector("#wf-search-inp");
      if (inp) {
        inp.focus();
        const len = inp.value.length;
        inp.setSelectionRange(len, len);
      }
    }

    const searchInp = DOM.workflowsStage.querySelector("#wf-search-inp");
    if (searchInp) {
      searchInp.oninput = () => {
        CS.workflowQuery = searchInp.value;
        renderWorkflowsStage();
      };
    }

    const importInp = DOM.workflowsStage.querySelector("#wf-import-file-inp");
    if (importInp) {
      importInp.onchange = (e) => {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
          try {
            const obj = JSON.parse(String(reader.result || "{}"));
            importWorkflowJsonObject(obj, f.name);
          } catch (_) {
            toast("⚠️ JSON 解析失败，请检查文件");
          }
        };
        reader.readAsText(f);
      };
    }

    DOM.workflowsStage.querySelectorAll("[data-wf-open]").forEach((btn) => {
      btn.onclick=()=>{
        const wf=(CS.savedWorkflows || []).find(item=>item.id===btn.getAttribute("data-wf-open"));
        if(!wf) return;
        const articleNodes=(wf.graph?.nodes || []).filter(node=>node.type==="article_plan");
        S.openModal({title:wf.title || "旧工作流存档",html:`
          <p>原有参数和连线已保留。转换会创建独立的参数画布，不修改此存档。</p>
          <p>存档含 ${(wf.graph?.nodes || []).length} 个节点、${(wf.graph?.edges || []).length} 条连线。</p>
          <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:20px;">
            <button type="button" class="btn" id="legacy-export">导出原文件</button>
            <button type="button" class="btn btn-primary" id="legacy-convert">${articleNodes.length?"提取到文章工作台":"转为参数画布"}</button>
          </div>`});
        document.getElementById("legacy-export").onclick=()=>exportWorkflowJsonFile(wf);
        document.getElementById("legacy-convert").onclick=async()=>{
          try {
            if(articleNodes.length) {
              const articles=articleNodes.map(node=>syncPlanNodeToMyArticles(JSON.parse(JSON.stringify(node)))).filter(Boolean);
              persistMyArticles();S.closeModal();
              if(articles[0]) openUnifiedArticleEditor(articles[0].id,{renderNow:true});
              toast(`已提取 ${articles.length} 篇独立文章，原存档保留`);
              return;
            }
            const graph=E.convertLegacyCanvas(wf.graph,Catalog);
            S.closeModal();switchCreationStage("canvas");
            if(await window.HandrawParameterCanvas.importDocument({name:wf.title,graph})) toast("已创建独立参数画布，请预览并确认组合");
          } catch(error) {toast(error.message || "无法转换，可导出原文件保留");}
        };
      };
    });

    DOM.workflowsStage.querySelectorAll("[data-wf-dl]").forEach((btn) => {
      btn.onclick = () => {
        const wid = btn.getAttribute("data-wf-dl");
        const wf = (CS.savedWorkflows || []).find((x) => x.id === wid);
        if (wf) exportWorkflowJsonFile(wf);
      };
    });

    DOM.workflowsStage.querySelectorAll("[data-wf-rm]").forEach((btn) => {
      btn.onclick = () => {
        const wid = btn.getAttribute("data-wf-rm");
        CS.savedWorkflows = (CS.savedWorkflows || []).filter((x) => x.id !== wid);
        writeJsonStorage(SAVED_WORKFLOWS_KEY, CS.savedWorkflows);
        studioApiPost("/api/studio/workflows/delete", { id: wid });
        renderTopAndBottomDocks();
        toast("已删除该工作流");
      };
    });
  }

  /* ======================== UNDO/REDO, GEOMETRY & CONNECTIONS ======================== */
  function pushUndo() {
    CS.undoStack.push(cloneGraph(CS.graph));
    if (CS.undoStack.length > 35) CS.undoStack.shift();
    CS.redoStack = [];
    markActiveTabDirty();
  }

  function undoGraph() {
    if (!CS.undoStack.length) {
      toast("已经是第一步");
      return;
    }
    CS.redoStack.push(cloneGraph(CS.graph));
    CS.graph = CS.undoStack.pop();
    CS.selectedEdgeId = null;
    fullRenderCanvas();
    persistOpenTabs();
    toast("↩ 已撤销上一步操作");
  }

  function redoGraph() {
    if (!CS.redoStack.length) {
      toast("没有可重做的操作");
      return;
    }
    CS.undoStack.push(cloneGraph(CS.graph));
    CS.graph = CS.redoStack.pop();
    CS.selectedEdgeId = null;
    fullRenderCanvas();
    persistOpenTabs();
    toast("↪ 已重做操作");
  }

  function snapVal(v) {
    return CS.snapToGrid ? Math.round(v / 16) * 16 : Math.round(v);
  }

  function screenToWorld(clientX, clientY) {
    const rect = DOM.viewport.getBoundingClientRect();
    return {
      x: (clientX - rect.left - CS.vx) / CS.vk,
      y: (clientY - rect.top - CS.vy) / CS.vk
    };
  }

  function worldToScreen(wx, wy) {
    return {
      x: wx * CS.vk + CS.vx,
      y: wy * CS.vk + CS.vy
    };
  }

  function getNodeById(id) {
    return (CS.graph.nodes || []).find((n) => n.id === id) || null;
  }

  function getPortWorldPos(node, dir) {
    if (!node) return { x: 0, y: 0 };
    const el = DOM.nodesLayer && DOM.nodesLayer.querySelector(`[data-node-id="${node.id}"]`);
    const w = el ? el.offsetWidth : node.w || 320;
    const h = el ? el.offsetHeight : node.h || 240;
    return {
      x: dir === "in" ? node.x : node.x + w,
      y: node.y + h * 0.5
    };
  }

  function bezierPath(x1, y1, x2, y2) {
    const dx = Math.abs(x2 - x1);
    const offset = Math.max(54, Math.min(180, dx * 0.46));
    return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + offset).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - offset).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }

  function edgeStrokeColor(srcNode) {
    if (!srcNode) return "var(--ic-edge-idle)";
    const map = {
      skill_params: "#c94c2e",
      asset: "#2d8658",
      text_input: "#7c4dff",
      fission: "#6d28d9",
      loop: "#0d9488",
      bridge: "#d97706",
      output_control: "#2563eb",
      article_plan: "#1f6f4a",
      output_display: "#b87918"
    };
    return map[srcNode.type] || "var(--ic-edge-idle)";
  }

  function isInputNodeType(type) {
    return type === "skill_params" || type === "asset" || type === "text_input" || type === "fission";
  }

  function wouldCreateCycle(fromId, toId) {
    if (fromId === toId) return true;
    const visited = new Set();
    const queue = [toId];
    while (queue.length > 0) {
      const cur = queue.shift();
      if (cur === fromId) return true;
      if (visited.has(cur)) continue;
      visited.add(cur);
      for (const e of CS.graph.edges || []) {
        if (e.from === cur && !visited.has(e.to)) queue.push(e.to);
      }
    }
    return false;
  }

  function canConnectNodes(fromNode, toNode) {
    if (!fromNode || !toNode || fromNode.id === toNode.id) return false;
    if (wouldCreateCycle(fromNode.id, toNode.id)) return false;

    if (toNode.type === "fission") {
      return fromNode.type === "text_input" || fromNode.type === "skill_params";
    }

    // Loop & Bridge sit between Input nodes (or chained Output Display) and Output Control nodes
    if (toNode.type === "bridge" || toNode.type === "loop") {
      return (
        isInputNodeType(fromNode.type) ||
        fromNode.type === "bridge" ||
        fromNode.type === "loop" ||
        fromNode.type === "output_display" ||
        fromNode.type === "article_plan"
      );
    }

    // Output Control accepts Input nodes directly, OR via Loop / Bridge, OR chained Output Display
    if (toNode.type === "output_control") {
      return (
        isInputNodeType(fromNode.type) ||
        fromNode.type === "bridge" ||
        fromNode.type === "loop" ||
        fromNode.type === "output_display" ||
        fromNode.type === "article_plan"
      );
    }

    if (fromNode.type === "output_control" && (toNode.type === "output_display" || toNode.type === "article_plan")) {
      return true;
    }
    if (fromNode.type === "article_plan" && toNode.type === "output_display") {
      return true;
    }
    return false;
  }

  function ensureEdge(fromId, toId) {
    const fromNode = getNodeById(fromId);
    const toNode = getNodeById(toId);
    if (!canConnectNodes(fromNode, toNode)) return false;
    if (CS.graph.edges.some((e) => e.from === fromId && e.to === toId)) return false;

    // Only 1 direct skill_params, 1 direct text_input, 1 fission, or 1 loop per bridge/loop/output_control to keep inputs unambiguous
    if (
      (toNode.type === "output_control" || toNode.type === "bridge" || toNode.type === "loop" || toNode.type === "fission") &&
      (fromNode.type === "skill_params" || fromNode.type === "text_input" || fromNode.type === "loop" || fromNode.type === "fission")
    ) {
      CS.graph.edges = CS.graph.edges.filter((e) => {
        if (e.to !== toId) return true;
        const other = getNodeById(e.from);
        return !other || other.type !== fromNode.type;
      });
    }

    CS.graph.edges.push({ id: E.uid("edge"), from: fromId, to: toId });
    markActiveTabDirty();
    return true;
  }

  function fitView(padding = 64) {
    if (!DOM.viewport) return;
    if (CS.stageView !== "canvas") return;
    const vRect = DOM.viewport.getBoundingClientRect();
    if (vRect.width <= 0 || vRect.height <= 0) return;
    const nodes = CS.graph.nodes || [];
    const leftOffset = CS.shelfOpen ? 252 : 32;
    const rightOffset = CS.minimapOpen ? 224 : padding;
    const bottomOffset = 60;
    const availW = Math.max(320, vRect.width - leftOffset - rightOffset);
    const availH = Math.max(240, vRect.height - 68 - bottomOffset);

    if (!nodes.length) {
      CS.vk = 0.9;
      CS.vx = leftOffset + 60;
      CS.vy = 72;
      applyViewportTransform();
      return;
    }

    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (const n of nodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y - 26);
      maxX = Math.max(maxX, n.x + (n.w || 320));
      maxY = Math.max(maxY, n.y + (n.h || 280));
    }

    const gw = Math.max(240, maxX - minX);
    const gh = Math.max(180, maxY - minY);
    const k = Math.max(0.32, Math.min(1.04, Math.min(availW / gw, availH / gh)));
    CS.vk = Number(k.toFixed(4));
    CS.vx = leftOffset + (availW - gw * CS.vk) * 0.5 - minX * CS.vk;
    CS.vy = 54 + (availH - gh * CS.vk) * 0.5 - minY * CS.vk;
    applyViewportTransform();
  }

  /* ======================== ASSET CATEGORIES & UNIFIED PICKER MODALS ======================== */
  function getAssetCategoryList() {
    const custom = Array.isArray(CS.customAssetCats) ? CS.customAssetCats : [];
    return [...DEFAULT_ASSET_CATS, ...custom.map((c) => ({ key: c.key, icon: c.icon || "🏷️", label: c.label, builtin: false }))];
  }

  function getAssetCatMeta(catKey) {
    const all = getAssetCategoryList();
    return all.find((c) => c.key === catKey) || { key: catKey || "other", icon: "📎", label: catKey || "其他", builtin: false };
  }

  function getAllAssetItems() {
    const bench = Catalog.benchmarkAssets || {};
    const builtins = [
      ...(bench.characters || []).map((x) => ({ ...x, cat: "characters", builtin: true })),
      ...(bench.props || []).map((x) => ({ ...x, cat: "props", builtin: true })),
      ...(bench.scenes || []).map((x) => ({ ...x, cat: "scenes", builtin: true })),
      ...(bench.other || []).map((x) => ({ ...x, cat: "other", builtin: true }))
    ];
    const uploads = (CS.customUploads || []).map((u) => ({
      id: u.id,
      name_zh: u.name || "自定义图参",
      desc_zh: u.desc || "用户本地上传图参",
      image: u.dataUrl || u.image,
      cat: u.cat || "other",
      custom: true,
      builtin: false
    }));
    return [...uploads, ...builtins];
  }

  // 1) Picker for Skill Params Node: Single-select (style1/style2/layout) & Multi-select (colors/tones/moods)
  function openSkillFieldPickerModal(skillNode, field, options = {}) {
    const hasCustomPick = typeof options?.onPick === "function";
    if (!hasCustomPick && (!skillNode || skillNode.type !== "skill_params")) return;
    const sd = (skillNode && skillNode.type === "skill_params") ? skillNode.data : {};

    // Dedicated Moods Multi-Select Modal
    if (field === "moods") {
      const cleanSavedMoods = (sd.moods || []).map(normalizeMoodLabel).filter(Boolean);
      const selected = new Set(cleanSavedMoods);
      const allMoodOptions = [
        ...new Set([...(Catalog.moods || []), ...E.DEFAULT_MOOD_POOL].map(normalizeMoodLabel).filter(Boolean))
      ];

      S.openModal({
        title: "✨ 选择情绪（支持多选 + 自定义补充情绪）",
        sizeClass: "modal-medium",
        html: `
          <div style="display:grid;gap:14px;">
            <div style="font-size:12.5px;color:var(--ink-muted);">可勾选多个情绪关键词叠加画面氛围，不选则不限制：</div>
            <div id="mood-pills-grid" style="display:flex;flex-wrap:wrap;gap:8px;"></div>
            <div style="display:grid;gap:6px;padding:12px;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:10px;">
              <label style="font-size:12.5px;font-weight:800;">✍️ 自定义补充情绪（多个用逗号分隔）：</label>
              <input type="text" class="hw-input" id="mood-custom-inp" value="${esc(sd.customMood || "")}" placeholder="例如：微醺夜色、颗粒胶片感、童话松弛感..." />
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <button type="button" class="btn btn-sm" id="mood-clear-btn">✕ 清空全部情绪</button>
              <button type="button" class="btn btn-primary" id="mood-confirm-btn">✓ 确认选用</button>
            </div>
          </div>
        `,
        onMount(root) {
          const grid = root.querySelector("#mood-pills-grid");
          const customInp = root.querySelector("#mood-custom-inp");
          const confirmBtn = root.querySelector("#mood-confirm-btn");

          function renderMoods() {
            grid.innerHTML = allMoodOptions
              .map((m) => {
                const on = selected.has(m);
                return `
                  <button type="button" data-mood-val="${esc(m)}" style="padding:7px 14px;border-radius:999px;font-size:13px;font-weight:800;cursor:pointer;border:1.5px solid ${
                  on ? "var(--vermilion)" : "var(--line-strong)"
                };background:${on ? "var(--vermilion)" : "#fff"};color:${on ? "#fff" : "var(--ink-main)"};">
                    ${on ? "✓ " : ""}${esc(m)}
                  </button>
                `;
              })
              .join("");

            grid.querySelectorAll("[data-mood-val]").forEach((btn) => {
              btn.onclick = () => {
                const v = btn.getAttribute("data-mood-val");
                if (selected.has(v)) selected.delete(v);
                else selected.add(v);
                renderMoods();
              };
            });
            confirmBtn.textContent = `✓ 确认选用 (${selected.size} 项)`;
          }

          renderMoods();

          root.querySelector("#mood-clear-btn").onclick = () => {
            selected.clear();
            customInp.value = "";
            renderMoods();
          };

          confirmBtn.onclick = () => {
            pushUndo();
            sd.moods = [...selected];
            sd.customMood = customInp.value.trim();
            S.closeModal();
            fullRenderCanvas();
            persistOpenTabs();
            toast(`✨ 已更新情绪参数（共 ${sd.moods.length + (sd.customMood ? 1 : 0)} 项）`);
          };
        }
      });
      return;
    }

    const isMulti = !hasCustomPick && (field === "colors" || field === "tones");
    const selectedSet = new Set(
      options?.current !== undefined
        ? (options.current ? [String(options.current).trim()] : [])
        : (field === "colors"
            ? sd.colors || []
            : field === "tones"
              ? sd.tones || []
              : sd[field]
                ? [sd[field]]
                : [])
    );

    const titles = {
      style1: sd.fusion ? `🎭 选择角色画风（${Catalog.styles.length} 款）` : `🎨 选择画风（${Catalog.styles.length} 款）`,
      style2: "🌄 选择场景画风（跨媒介画面融合）",
      layout: `📐 选择图型（${Catalog.layouts.length} 款）`,
      colors: "🌈 选择主题色（支持多选叠加色卡）",
      tones: "💡 选择影调（支持多选明暗与光效）"
    };

    let activeGroup = "ALL";
    let searchQuery = "";

    const modalTitle = (options && options.title) || titles[field] || "选择参数";

    S.openModal({
      title: modalTitle,
      sizeClass: "modal-wide",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;min-height:540px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
            <input type="search" class="hw-input" id="sp-picker-search" placeholder="🔍 搜索编号、名称、关键词..." style="flex:1;min-width:240px;padding:8px 12px;font-size:13px;" />
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <button type="button" class="btn btn-sm" id="sp-picker-rand">🎲 随机挑款</button>
              <button type="button" class="btn btn-sm" id="sp-picker-clear" style="color:var(--ink-muted);">✕ ${isMulti ? "清空已选" : "置空不指定"}</button>
              ${isMulti ? `<button type="button" class="btn btn-sm btn-primary" id="sp-picker-confirm">✓ 确认选用 (${selectedSet.size})</button>` : ""}
            </div>
          </div>
          <div id="sp-picker-groups" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--ink-muted);">
            <span id="sp-picker-count">加载中...</span>
            <span>${isMulti ? "支持多选：单击卡片勾选/取消，选好后点右上角「确认选用」" : "单击任意卡片立即选用"}</span>
          </div>
          <div id="sp-picker-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(178px,1fr));gap:12px;max-height:56vh;overflow-y:auto;padding:2px 4px 10px 2px;"></div>
        </div>
      `,
      onMount(root) {
        const searchInp = root.querySelector("#sp-picker-search");
        const groupsEl = root.querySelector("#sp-picker-groups");
        const countEl = root.querySelector("#sp-picker-count");
        const gridEl = root.querySelector("#sp-picker-grid");
        const confirmBtn = root.querySelector("#sp-picker-confirm");

        const updateConfirmText = () => {
          if (confirmBtn) confirmBtn.textContent = `✓ 确认选用 (${selectedSet.size})`;
        };

        searchInp.oninput = () => {
          searchQuery = searchInp.value.trim().toLowerCase();
          renderGroups();
          renderGrid();
        };

        root.querySelector("#sp-picker-rand").onclick = () => {
          if (hasCustomPick) {
            const pool = (field === "style1" || field === "style2") ? Catalog.styles : Catalog.layouts;
            const freeFirst = pool.filter((x) => x.tier !== "pro_credit");
            const src = freeFirst.length > 0 ? freeFirst : pool;
            const pick = src[Math.floor(Math.random() * src.length)];
            if (pick) options.onPick(pick.id);
            S.closeModal();
            return;
          }
          pushUndo();
          if (field === "style1" || field === "style2") {
            const pick = Catalog.styles[Math.floor(Math.random() * Catalog.styles.length)];
            if (pick) sd[field] = pick.id;
            S.closeModal();
            fullRenderCanvas();
            persistOpenTabs();
            toast(`🎲 已随机选用画风 #${pick?.id || ""}`);
          } else if (field === "layout") {
            const pick = Catalog.layouts[Math.floor(Math.random() * Catalog.layouts.length)];
            if (pick) sd.layout = pick.id;
            S.closeModal();
            fullRenderCanvas();
            persistOpenTabs();
            toast(`🎲 已随机选用图型 ${pick?.id || ""}`);
          } else if (field === "colors") {
            selectedSet.clear();
            const c1 = Catalog.colors[Math.floor(Math.random() * Catalog.colors.length)];
            const c2 = Catalog.colors[Math.floor(Math.random() * Catalog.colors.length)];
            if (c1) selectedSet.add(c1.id);
            if (c2) selectedSet.add(c2.id);
            updateConfirmText();
            renderGrid();
          } else if (field === "tones") {
            selectedSet.clear();
            const t1 = Catalog.tones[Math.floor(Math.random() * Catalog.tones.length)];
            if (t1) selectedSet.add(t1.id);
            updateConfirmText();
            renderGrid();
          }
        };

        root.querySelector("#sp-picker-clear").onclick = () => {
          if (hasCustomPick) {
            options.onPick("");
            S.closeModal();
            return;
          }
          if (isMulti) {
            selectedSet.clear();
            updateConfirmText();
            renderGrid();
          } else {
            pushUndo();
            sd[field] = "";
            S.closeModal();
            fullRenderCanvas();
            persistOpenTabs();
            toast("已置空该参数");
          }
        };

        if (confirmBtn) {
          confirmBtn.onclick = () => {
            pushUndo();
            if (field === "colors") sd.colors = [...selectedSet];
            else if (field === "tones") sd.tones = [...selectedSet];
            S.closeModal();
            fullRenderCanvas();
            persistOpenTabs();
            toast(`✓ 已保存${field === "colors" ? "主题色" : "影调"}选择（共 ${selectedSet.size} 项）`);
          };
        }

        function getGroupTabs() {
          if (["style1", "style2", "layout"].includes(field)) {
            const kind = field === "layout" ? "layout" : "style";
            const pool = kind === "style" ? Catalog.styles : Catalog.layouts;
            const groups = [{ key: "ALL", label: kind === "style" ? "全部画风" : "全部图型" }, { key: "FAV", label: "⭐ 收藏" },
              ...[...new Set(pool.map(x => x.group).filter(Boolean))].map(g => ({ key: g, label: S.resourceGroupLabel(g, kind) }))];
            return S.visibleResourceGroups(pool, groups, searchQuery).map(g => ({ ...g, label: `${g.label} (${g.count})` }));
          }
          if (field === "colors") {
            return E.COLOR_FAMILIES.map((f) => ({ key: f.key, label: f.label }));
          }
          if (field === "tones") {
            const s = new Set();
            Catalog.tones.forEach((t) => { if (t.category) s.add(t.category); });
            return [{ key: "ALL", label: `全部影调 (${Catalog.tones.length})` }, ...[...s].map((g) => ({ key: g, label: g }))];
          }
          return [{ key: "ALL", label: "全部" }];
        }

        function renderGroups() {
          const tabs = getGroupTabs();
          if (!tabs.some(g => g.key === activeGroup)) activeGroup = "ALL";
          groupsEl.innerHTML = tabs
            .map(
              (g) => `
              <button type="button" class="ic-shelf-group-chip ${activeGroup === g.key ? "is-active" : ""}" data-grp-k="${esc(g.key)}" style="padding:5px 11px;font-size:12px;">
                ${esc(g.label)}
              </button>
            `
            )
            .join("");
          groupsEl.querySelectorAll("[data-grp-k]").forEach((b) => {
            b.onclick = () => {
              activeGroup = b.getAttribute("data-grp-k");
              renderGroups();
              renderGrid();
            };
          });
        }

        function renderGrid() {
          let list = [];
          if (field === "style1" || field === "style2") {
            list = Catalog.styles.filter((s) => S.resourceMatchesGroup(s, activeGroup));
          } else if (field === "layout") {
            list = Catalog.layouts.filter((l) => S.resourceMatchesGroup(l, activeGroup));
          } else if (field === "colors") {
            list = Catalog.colors.filter((c) => E.colorMatchesFamily(c.id, activeGroup));
          } else if (field === "tones") {
            list = Catalog.tones.filter((t) => activeGroup === "ALL" || t.category === activeGroup);
          }

          if (searchQuery) {
            list = list.filter((it) => S.resourceSearchText(it).includes(searchQuery));
          }

          countEl.textContent = `共筛出 ${list.length} 项${selectedSet.size ? ` · 当前已选：${[...selectedSet].join("、")}` : ""}`;

          gridEl.innerHTML = list
            .slice(0, 180)
            .map((it) => {
              const id = it.id;
              const title = it.name || it.name_zh || id;
              const isSel = selectedSet.has(id);
              const proLocked = it.tier === "pro_credit" && !S.isUnlocked(id, it);
              return `
                <div class="ic-picker-card ${isSel ? "is-selected" : ""}" data-pick-id="${esc(id)}" tabindex="0" role="button" aria-label="${esc(id)} ${esc(title)}" style="border:1.5px solid ${
                isSel ? "var(--vermilion)" : "var(--line-soft)"
              };border-radius:11px;overflow:hidden;background:#fff;cursor:pointer;display:flex;flex-direction:column;box-shadow:${
                isSel ? "0 0 0 3px rgba(209,75,40,0.18)" : "0 2px 6px rgba(24,20,17,0.04)"
              };">
                  <div style="position:relative;aspect-ratio:4/3;background:#f3ede3;overflow:hidden;display:flex;align-items:center;justify-content:center;">
                    <img data-hw-src="${esc(it.image)}" alt="${esc(title)}" loading="lazy" style="width:100%;height:100%;object-fit:contain;display:block;" />
                    ${
                      isSel
                        ? `<span style="position:absolute;right:6px;top:6px;padding:2px 7px;border-radius:999px;background:var(--vermilion);color:#fff;font-size:10.5px;font-weight:800;">✓ 已选</span>`
                        : proLocked
                          ? `<span style="position:absolute;right:6px;top:6px;padding:2px 6px;border-radius:5px;background:rgba(209,75,40,0.92);color:#fff;font-size:10px;font-weight:800;">🔒 ${it.unlockCost || 5}积分</span>`
                          : ""
                    }
                  </div>
                  <div style="padding:8px 10px;display:flex;flex-direction:column;gap:2px;">
                    <div style="font-family:var(--font-mono, monospace);font-size:11px;font-weight:700;color:var(--ink-muted, #786f65);">${esc(id)}</div>
                    <div style="font-size:12.5px;font-weight:800;color:#221d18;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(title)}</div>
                    <div style="font-size:11px;color:#786f65;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(["style1", "style2", "layout"].includes(field) ? S.resourceGroupLabel(it.group, it.kind) : it.category || it.desc_zh || it.description || "点击选用")}</div>
                  </div>
                </div>
              `;
            })
            .join("");

          gridEl.querySelectorAll("[data-pick-id]").forEach((card) => {
            const onSelect = () => {
              const id = card.getAttribute("data-pick-id");
              const resObj = Catalog.resourceMap.get(id);
              if (resObj && resObj.tier === "pro_credit" && !S.isUnlocked(id, resObj)) {
                if (!App.state.loggedIn) {
                  S.closeModal();
                  S.openLoginModal(`编号 ${id} 为精调资源，登录即可体验！`, () => fullRenderCanvas());
                  return;
                }
                if (!S.unlockWithCredits(id, resObj.unlockCost || 5, `解锁 ${id}`)) return;
              }

              if (hasCustomPick) {
                options.onPick(id);
                S.closeModal();
                return;
              }

              if (isMulti) {
                if (selectedSet.has(id)) selectedSet.delete(id);
                else selectedSet.add(id);
                updateConfirmText();
                renderGrid();
              } else {
                pushUndo();
                sd[field] = id;
                S.closeModal();
                fullRenderCanvas();
                persistOpenTabs();
                toast(`✨ 已选用 ${id}`);
              }
            };
            card.onclick = onSelect;
            card.onkeydown = (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect();
              }
            };
          });

          if (window.HandrawImageLoader?.scan) {
            window.HandrawImageLoader.scan(gridEl);
          }
        }

        gridEl.addEventListener("scroll", () => {
          if (window.HandrawImageLoader?.scan) {
            window.HandrawImageLoader.scan(gridEl);
          }
        }, { passive: true });

        renderGroups();
        renderGrid();
        setTimeout(() => searchInp.focus(), 40);
      }
    });
  }

  // 2) Asset Picker Modal (我的图库 / 官方示例 / 本地上传 + 角色/道具/场景/其他分类)
  async function openAssetPickerModal(targetOrOptions, options = {}) {
    await ensureWorkspaceCollection("uploads");
    let curItems = [];
    let isNode = false;
    let onCommitCallback = null;

    const opts = (options && typeof options === "object") ? options : {};
    const maxCount = Math.max(1, Number(opts.maxCount || targetOrOptions?.maxCount) || 6);
    const modalTitle = opts.title || targetOrOptions?.title || "参考图与图参（我的图库 / 官方示例 / 本地上传）";

    function getMaxCountToast() {
      if (maxCount === 4) return "全局参考图最多 4 张";
      if (maxCount === 3) return "单条参考图最多 3 张";
      return `最多选用 ${maxCount} 张参考图`;
    }

    if (targetOrOptions && targetOrOptions.type === "asset") {
      isNode = true;
      curItems = Array.isArray(targetOrOptions.data.items) ? targetOrOptions.data.items : [];
      onCommitCallback = (items) => {
        pushUndo();
        targetOrOptions.data.items = items;
        fullRenderCanvas();
        persistOpenTabs();
        if (typeof opts.onConfirm === "function") {
          opts.onConfirm(items);
        }
        toast(
          items.length
            ? `✓ 已选用 ${items.length} 项图参：${items.map((x) => x.name || x.id).join("、")}`
            : "已置空资产节点"
        );
      };
    } else if (targetOrOptions && typeof targetOrOptions === "object") {
      const rawRefs = Array.isArray(targetOrOptions.items)
        ? targetOrOptions.items
        : (Array.isArray(targetOrOptions.currentRefs)
          ? targetOrOptions.currentRefs
          : (Array.isArray(targetOrOptions.references) ? targetOrOptions.references : []));
      const allItems = getAllAssetItems();
      curItems = rawRefs.map((r, idx) => {
        if (r && typeof r === "object" && (r.id || r.image)) {
          return { ...r };
        }
        const url = typeof r === "string" ? r : (r.url || r.image || "");
        const matched = allItems.find((it) => it.image === url || it.id === r || it.id === r.id);
        if (matched) return { ...matched };
        return {
          id: typeof r === "string" ? `REF-${idx + 1}` : (r.id || `REF-${idx + 1}`),
          name: typeof r === "string" ? `参考图 ${idx + 1}` : (r.name || r.name_zh || `参考图 ${idx + 1}`),
          image: url,
          cat: "other"
        };
      });
      onCommitCallback = (items) => {
        if (typeof targetOrOptions.onConfirm === "function") {
          targetOrOptions.onConfirm(items);
        } else if (typeof opts.onConfirm === "function") {
          opts.onConfirm(items);
        }
      };
    } else {
      return;
    }

    const selectedMap = new Map(curItems.map((x) => [x.id, { ...x }]));

    let topTab = App.state.loggedIn ? "my" : "official"; // "my" | "official" | "upload"
    let activeCategory = "ALL";
    let uploadCategory = "other";
    let uploadCategoryUserModified = false;
    let isUploading = false;
    let newlyUploadedAssetId = null;
    let searchQuery = "";
    let showNewCatForm = false;

    S.openModal({
      title: modalTitle,
      sizeClass: "modal-wide",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;min-height:540px;">
          <!-- Top 3 Tabs -->
          <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line-soft);padding-bottom:10px;gap:10px;flex-wrap:wrap;">
            <div class="hw-pills-row" id="ast-top-tabs">
              <button type="button" class="hw-pill ${topTab === "my" ? "is-active" : ""}" data-top-tab="my">我的图库</button>
              <button type="button" class="hw-pill ${topTab === "official" ? "is-active" : ""}" data-top-tab="official">官方示例</button>
              <button type="button" class="hw-pill ${topTab === "upload" ? "is-active" : ""}" data-top-tab="upload">本地上传</button>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button type="button" class="btn btn-sm" id="ast-picker-clear" style="color:var(--ink-muted);">清空已选</button>
              <button type="button" class="btn btn-sm btn-primary" id="ast-picker-confirm">✓ 确认选用 (${selectedMap.size})</button>
            </div>
          </div>

          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
            <input type="search" class="hw-input" id="ast-picker-search" placeholder="搜索资产编号、名称、分类..." style="flex:1;min-width:240px;padding:8px 12px;font-size:13px;" />
            <span style="font-size:12px;color:var(--ink-muted);" id="ast-picker-count">正在加载...</span>
          </div>

          <div id="ast-cats-wrap" style="display:flex;flex-direction:column;gap:8px;"></div>
          <div id="ast-upload-bar"></div>

          <div id="ast-picker-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(178px,1fr));gap:12px;max-height:50vh;overflow-y:auto;padding:2px 4px 10px 2px;"></div>
        </div>
      `,
      onMount(root) {
        const topTabsEl = root.querySelector("#ast-top-tabs");
        const searchInp = root.querySelector("#ast-picker-search");
        const catsWrap = root.querySelector("#ast-cats-wrap");
        const uploadBar = root.querySelector("#ast-upload-bar");
        const countEl = root.querySelector("#ast-picker-count");
        const gridEl = root.querySelector("#ast-picker-grid");
        const confirmBtn = root.querySelector("#ast-picker-confirm");

        const commitSelection = () => {
          const items = [...selectedMap.values()];
          S.closeModal();
          if (onCommitCallback) onCommitCallback(items);
        };

        const syncConfirmText = () => {
          confirmBtn.textContent = `✓ 确认选用 (${selectedMap.size} / ${maxCount})`;
        };

        topTabsEl.querySelectorAll("[data-top-tab]").forEach((btn) => {
          btn.onclick = () => {
            const nextTab = btn.getAttribute("data-top-tab");
            if (nextTab === topTab) return;
            topTab = nextTab;
            topTabsEl.querySelectorAll("[data-top-tab]").forEach((b) => {
              b.classList.toggle("is-active", b === btn);
            });
            if (topTab === "upload") {
              if (!uploadCategoryUserModified) {
                const validCats = getAssetCategoryList();
                if (activeCategory !== "ALL" && validCats.some((c) => c.key === activeCategory)) {
                  uploadCategory = activeCategory;
                } else {
                  uploadCategory = "other";
                }
              }
            }
            renderView();
          };
        });

        searchInp.oninput = () => {
          searchQuery = searchInp.value.trim().toLowerCase();
          renderGrid();
        };

        root.querySelector("#ast-picker-clear").onclick = () => {
          selectedMap.clear();
          syncConfirmText();
          renderGrid();
        };

        confirmBtn.onclick = commitSelection;

        function getPoolItems() {
          const allItems = getAllAssetItems();
          if (topTab === "my") {
            return allItems.filter((x) => Boolean(x.custom || !x.builtin));
          }
          if (topTab === "official") {
            return allItems.filter((x) => Boolean(x.builtin));
          }
          return allItems;
        }

        function renderView() {
          if (topTab === "upload") {
            catsWrap.innerHTML = "";
            renderUploadSection();
            gridEl.innerHTML = "";
            countEl.textContent = "支持本地上传图片并存入你的图库";
            return;
          }

          uploadBar.innerHTML = "";

          if (topTab === "my" && !App.state.loggedIn) {
            catsWrap.innerHTML = "";
            gridEl.innerHTML = `
              <div style="grid-column:1/-1;padding:50px 20px;text-align:center;color:var(--ink-muted);">
                <div style="font-size:14px;font-weight:700;margin-bottom:12px;">登录后可使用你的图库</div>
                <button type="button" class="btn btn-sm btn-primary" id="ast-login-btn">去登录</button>
              </div>
            `;
            countEl.textContent = "未登录";
            const loginBtn = gridEl.querySelector("#ast-login-btn");
            if (loginBtn) {
              loginBtn.onclick = () => {
                S.openLoginModal("使用图库请先登录账号", () => {
                  renderView();
                });
              };
            }
            return;
          }

          renderCategoryPills();
          renderGrid();
        }

        function renderCategoryPills() {
          const pool = getPoolItems();
          const cats = getAssetCategoryList();
          const groups = [
            { key: "ALL", label: `全部 (${pool.length})`, builtin: true },
            ...cats.map((c) => ({
              key: c.key,
              label: `${c.label} (${pool.filter((x) => (x.cat || "other") === c.key).length})`,
              builtin: c.builtin,
              rawLabel: c.label
            }))
          ];
          if (!groups.some((g) => g.key === activeCategory)) activeCategory = "ALL";

          catsWrap.innerHTML = `
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              ${groups.map((g) => `
                <button type="button" class="hw-pill ${activeCategory === g.key ? "is-active" : ""}" data-ing-grp="${esc(g.key)}" style="padding:4px 10px;font-size:12px;">
                  ${esc(g.label)}
                </button>
              `).join("")}
              ${topTab === "my" ? `
                <button type="button" class="btn btn-sm" id="ing-toggle-new-cat" style="padding:3px 8px;font-size:11.5px;border-style:dashed;color:var(--vermilion);border-color:var(--vermilion-border);">＋ 新建分类</button>
              ` : ""}
            </div>
            ${showNewCatForm && topTab === "my" ? `
              <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:8px;flex-wrap:wrap;">
                <span style="font-size:12px;font-weight:700;">新建资产分类：</span>
                <input type="text" class="hw-input" id="ing-new-cat-name" placeholder="分类名（如：角色IP）" style="width:200px;padding:4px 8px;font-size:12px;" />
                <button type="button" class="btn btn-sm btn-primary" id="ing-confirm-new-cat">创建</button>
                <button type="button" class="btn btn-sm" id="ing-cancel-new-cat">取消</button>
              </div>
            ` : ""}
          `;

          catsWrap.querySelectorAll("[data-ing-grp]").forEach((btn) => {
            btn.onclick = () => {
              activeCategory = btn.getAttribute("data-ing-grp");
              renderCategoryPills();
              renderGrid();
            };
          });

          const toggleNewCat = catsWrap.querySelector("#ing-toggle-new-cat");
          if (toggleNewCat) {
            toggleNewCat.onclick = () => {
              showNewCatForm = !showNewCatForm;
              renderCategoryPills();
            };
          }

          const confirmNewCat = catsWrap.querySelector("#ing-confirm-new-cat");
          if (confirmNewCat) {
            confirmNewCat.onclick = () => {
              const raw = (catsWrap.querySelector("#ing-new-cat-name")?.value || "").trim();
              if (!raw) return toast("请输入新分类名称");
              const newKey = "cat_" + Date.now().toString(36);
              CS.customAssetCats = [...(CS.customAssetCats || []), { key: newKey, icon: "", label: raw }];
              writeJsonStorage(CUSTOM_ASSET_CATS_KEY, CS.customAssetCats);
              activeCategory = newKey;
              uploadCategory = newKey;
              uploadCategoryUserModified = true;
              showNewCatForm = false;
              renderCategoryPills();
              renderGrid();
              toast(`已创建分类「${raw}」`);
            };
            catsWrap.querySelector("#ing-cancel-new-cat").onclick = () => {
              showNewCatForm = false;
              renderCategoryPills();
            };
          }
        }

        function renderUploadSection() {
          const cats = getAssetCategoryList();
          if (!cats.some((c) => c.key === uploadCategory)) {
            uploadCategory = "other";
          }

          uploadBar.innerHTML = `
            <div style="display:flex;flex-direction:column;gap:12px;padding:16px;background:var(--paper-bg);border:1px dashed var(--line-strong);border-radius:10px;">
              <div style="font-size:13px;font-weight:700;">本地图片上传并存入你的图库：</div>
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <input type="text" class="hw-input" id="ing-upload-name" placeholder="图参名称（如：主角设计稿）" style="width:220px;padding:6px 10px;font-size:12.5px;" ${isUploading ? "disabled" : ""} />
                <label class="btn btn-sm btn-primary" id="ing-upload-file-btn" style="cursor:pointer;margin-left:auto;${isUploading ? "opacity:0.6;pointer-events:none;" : ""}">
                  ${isUploading ? "正在上传..." : "＋ 选择本地图片上传"}
                  <input type="file" id="ing-upload-file" accept="image/*" hidden ${isUploading ? "disabled" : ""} />
                </label>
              </div>

              <fieldset id="ing-upload-cat-fieldset" style="border:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;" ${isUploading ? "disabled" : ""}>
                <legend style="font-size:12px;color:var(--ink-muted);font-weight:700;padding:0;margin-bottom:2px;">归入分类：</legend>
                <div class="ing-upload-cat-pills" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                  ${cats.map((c) => {
                    const isChecked = uploadCategory === c.key;
                    return `
                      <label class="hw-pill ing-cat-pill ${isChecked ? "is-active" : ""} ${isUploading ? "is-disabled" : ""}" style="cursor:pointer;user-select:none;padding:4px 10px;font-size:12px;">
                        <input
                          type="radio"
                          name="ing-upload-cat-radio"
                          value="${esc(c.key)}"
                          ${isChecked ? "checked" : ""}
                          class="hw-cat-radio ic-sr-only"
                          ${isUploading ? "disabled" : ""}
                        />
                        <span>${esc(c.label)}</span>
                      </label>
                    `;
                  }).join("")}
                </div>
              </fieldset>

              <div style="font-size:11.5px;color:var(--ink-muted);">上传后图片将存入你的个人图库，可重复用于做图与画布创作。</div>
            </div>
          `;

          const syncUploadCatPills = () => {
            uploadBar.querySelectorAll(".ing-cat-pill").forEach((pill) => {
              const r = pill.querySelector("input[name='ing-upload-cat-radio']");
              const active = Boolean(r && r.value === uploadCategory);
              if (r) r.checked = active;
              pill.classList.toggle("is-active", active);
            });
          };

          uploadBar.querySelectorAll(".ing-cat-pill").forEach((pill) => {
            const radio = pill.querySelector("input[name='ing-upload-cat-radio']");
            if (!radio) return;
            radio.onchange = () => {
              if (isUploading) return;
              if (radio.checked) {
                uploadCategory = radio.value;
                uploadCategoryUserModified = true;
                syncUploadCatPills();
              }
            };
            pill.onclick = (e) => {
              if (isUploading) return;
              if (e.target !== radio) {
                radio.checked = true;
              }
              uploadCategory = radio.value;
              uploadCategoryUserModified = true;
              syncUploadCatPills();
            };
          });

          const fileInp = uploadBar.querySelector("#ing-upload-file");
          if (fileInp) {
            fileInp.onchange = (ev) => {
              const f = ev.target.files && ev.target.files[0];
              if (!f) return;
              const customName = (uploadBar.querySelector("#ing-upload-name")?.value || "").trim() || f.name.replace(/\.[^.]+$/, "");
              const chosenCat = uploadBar.querySelector("input[name='ing-upload-cat-radio']:checked")?.value || uploadCategory || "other";
              const catMeta = getAssetCatMeta(chosenCat);

              isUploading = true;
              const catFieldset = uploadBar.querySelector("#ing-upload-cat-fieldset");
              if (catFieldset) catFieldset.disabled = true;
              uploadBar.querySelectorAll("input[name='ing-upload-cat-radio']").forEach((r) => { r.disabled = true; });
              uploadBar.querySelectorAll(".ing-cat-pill").forEach((p) => { p.classList.add("is-disabled"); });
              const nameInp = uploadBar.querySelector("#ing-upload-name");
              if (nameInp) nameInp.disabled = true;
              if (fileInp) fileInp.disabled = true;
              const fileBtn = uploadBar.querySelector("#ing-upload-file-btn");
              if (fileBtn) {
                fileBtn.classList.add("is-disabled");
                fileBtn.style.opacity = "0.6";
                fileBtn.style.pointerEvents = "none";
              }

              const resetUploadingState = () => {
                isUploading = false;
                if (catFieldset) catFieldset.disabled = false;
                uploadBar.querySelectorAll("input[name='ing-upload-cat-radio']").forEach((r) => { r.disabled = false; });
                uploadBar.querySelectorAll(".ing-cat-pill").forEach((p) => { p.classList.remove("is-disabled"); });
                if (nameInp) nameInp.disabled = false;
                if (fileInp) {
                  fileInp.disabled = false;
                  fileInp.value = "";
                }
                if (fileBtn) {
                  fileBtn.classList.remove("is-disabled");
                  fileBtn.style.opacity = "";
                  fileBtn.style.pointerEvents = "";
                }
              };

              const reader = new FileReader();
              reader.onerror = () => {
                resetUploadingState();
                toast("读取图片失败，请重试");
              };
              reader.onload = async () => {
                try {
                  const rawDataUrl = String(reader.result || "");
                  let finalId = "USR-" + String((CS.customUploads?.length || 0) + 1).padStart(2, "0");
                  let finalImg = rawDataUrl;
                  const uploaded = await studioApiPost("/api/studio/uploads", {
                    dataUrl: rawDataUrl,
                    nameZh: customName,
                    descZh: `${catMeta.label} · 本地上传图参`,
                    cat: chosenCat
                  });
                  if (uploaded && uploaded.ok && uploaded.image) {
                    finalId = uploaded.id || finalId;
                    finalImg = uploaded.image;
                  }
                  const newItem = {
                    id: finalId,
                    name: customName,
                    desc: `${catMeta.label} · 本地上传图参`,
                    cat: chosenCat,
                    image: finalImg,
                    dataUrl: finalImg,
                    custom: true,
                    builtin: false
                  };
                  CS.customUploads = [newItem, ...(CS.customUploads || []).filter((x) => x.id !== finalId)];
                  writeJsonStorage(UPLOAD_STORAGE_KEY, CS.customUploads);
                  if (selectedMap.size < maxCount) {
                    selectedMap.set(newItem.id, newItem);
                  }
                  syncConfirmText();
                  toast(`已上传《${customName}》并加入图参！`);

                  isUploading = false;
                  newlyUploadedAssetId = finalId;
                  topTab = "my";
                  activeCategory = chosenCat;
                  topTabsEl.querySelectorAll("[data-top-tab]").forEach((b) => {
                    b.classList.toggle("is-active", b.getAttribute("data-top-tab") === "my");
                  });
                  renderView();

                  setTimeout(() => {
                    if (newlyUploadedAssetId) {
                      const card = gridEl.querySelector(`[data-pick-id="${newlyUploadedAssetId}"]`);
                      if (card) {
                        card.scrollIntoView({ block: "nearest", behavior: "smooth" });
                        card.style.transition = "transform 0.25s ease, box-shadow 0.25s ease";
                        card.style.transform = "scale(1.02)";
                        card.style.boxShadow = "0 0 0 4px var(--vermilion), 0 6px 16px rgba(209,75,40,0.25)";
                        setTimeout(() => {
                          if (card) {
                            card.style.transform = "";
                            card.style.boxShadow = "";
                          }
                        }, 2200);
                      }
                    }
                  }, 60);
                } catch (err) {
                  console.error("Upload failed:", err);
                  resetUploadingState();
                  toast("上传失败，已保留分类选择");
                }
              };
              reader.readAsDataURL(f);
            };
          }
        }

        function renderGrid() {
          const pool = getPoolItems();
          let list = pool.filter((x) => activeCategory === "ALL" || (x.cat || "other") === activeCategory);
          if (searchQuery) {
            list = list.filter((it) => `${it.id} ${it.name_zh || it.name || ""} ${it.desc_zh || ""}`.toLowerCase().includes(searchQuery));
          }

          countEl.textContent = `共 ${list.length} 项 · 已选 ${selectedMap.size} / ${maxCount}`;

          if (!list.length) {
            gridEl.innerHTML = `<div style="grid-column:1/-1;padding:42px;text-align:center;color:var(--ink-muted);">暂无图参，可通过上方「本地上传」添加图片</div>`;
            return;
          }

          gridEl.innerHTML = list
            .map((it) => {
              const id = it.id;
              const title = it.name_zh || it.name || id;
              const isSel = selectedMap.has(id);
              const isNewlyUploaded = id === newlyUploadedAssetId;
              const catMeta = getAssetCatMeta(it.cat || "other");
              return `
                <div class="ic-picker-card ${isSel ? "is-selected" : ""} ${isNewlyUploaded ? "is-newly-uploaded" : ""}" data-pick-id="${esc(id)}" style="border:1.5px solid ${
                isSel ? "var(--vermilion)" : "var(--line-soft)"
              };border-radius:11px;overflow:hidden;background:#fff;cursor:pointer;display:flex;flex-direction:column;box-shadow:${
                isNewlyUploaded
                  ? "0 0 0 4px var(--vermilion), 0 6px 16px rgba(209,75,40,0.25)"
                  : (isSel ? "0 0 0 3px rgba(209,75,40,0.16)" : "0 2px 6px rgba(24,20,17,0.04)")
              };">
                  <div style="position:relative;aspect-ratio:4/3;background:#f3ede3;overflow:hidden;display:flex;align-items:center;justify-content:center;">
                    <img data-hw-src="${esc(it.image)}" alt="${esc(title)}" loading="lazy" style="width:100%;height:100%;object-fit:contain;display:block;" />
                    <span style="position:absolute;right:6px;top:6px;padding:2px 6px;border-radius:5px;background:${
                      isSel ? "var(--vermilion)" : "rgba(255,252,247,0.92)"
                    };color:${isSel ? "#fff" : "#2b2520"};font-size:10px;font-weight:700;">
                      ${isSel ? "✓ 已选" : esc(catMeta.label)}
                    </span>
                  </div>
                  <div style="padding:8px 10px;display:flex;flex-direction:column;gap:4px;flex:1;justify-content:space-between;">
                    <div>
                      <div style="font-family:var(--font-mono, monospace);font-size:11px;font-weight:700;color:var(--ink-muted, #786f65);">${esc(id)}</div>
                      <div style="font-size:12.5px;font-weight:700;color:#221d18;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(title)}</div>
                    </div>
                    ${!it.builtin ? `
                      <div style="display:flex;align-items:center;justify-content:flex-end;gap:4px;margin-top:2px;" data-stop-card-click="1">
                        <button type="button" class="btn btn-sm" data-del-asset-id="${esc(id)}" style="padding:1px 6px;font-size:10.5px;color:#dc2626;">删除</button>
                      </div>
                    ` : `<div style="font-size:11px;color:#786f65;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(it.desc_zh || "官方示例图参")}</div>`}
                  </div>
                </div>
              `;
            })
            .join("");

          gridEl.querySelectorAll("[data-stop-card-click]").forEach((el) => {
            el.onclick = (ev) => ev.stopPropagation();
          });

          gridEl.querySelectorAll("[data-del-asset-id]").forEach((btn) => {
            btn.onclick = () => {
              const aid = btn.getAttribute("data-del-asset-id");
              CS.customUploads = (CS.customUploads || []).filter((u) => u.id !== aid);
              writeJsonStorage(UPLOAD_STORAGE_KEY, CS.customUploads);
              selectedMap.delete(aid);
              syncConfirmText();
              renderGrid();
              toast("已删除图参");
            };
          });

          gridEl.querySelectorAll("[data-pick-id]").forEach((card) => {
            const id = card.getAttribute("data-pick-id");
            const picked = list.find((x) => x.id === id);
            if (!picked) return;
            const cm = getAssetCatMeta(picked.cat || "other");
            const itemObj = {
              id: picked.id,
              name: picked.name_zh || picked.name || picked.id,
              image: picked.image,
              cat: picked.cat || "other",
              catLabel: cm.label,
              custom: Boolean(picked.custom)
            };

            card.onclick = () => {
              if (selectedMap.has(id)) {
                selectedMap.delete(id);
              } else {
                if (selectedMap.size >= maxCount) {
                  toast(getMaxCountToast());
                  return;
                }
                selectedMap.set(id, itemObj);
              }
              syncConfirmText();
              renderGrid();
            };

            card.ondblclick = () => {
              selectedMap.clear();
              selectedMap.set(id, itemObj);
              commitSelection();
            };
          });

          if (newlyUploadedAssetId) {
            const newlyCard = gridEl.querySelector(`[data-pick-id="${newlyUploadedAssetId}"]`);
            if (newlyCard) {
              newlyCard.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }
          }
        }

        renderView();
      }
    });
  }

  /* ======================== URL DEEP-LINK & TAB HYDRATION ======================== */
  function buildForkGraphFromWork(w) {
    const styles = Array.isArray(w.styles) ? w.styles : [];
    const isDual = styles.length >= 2;
    const sp = E.makeSkillParamsNode(64, 56, {
      fusion: isDual,
      style1: styles[0] || "",
      style2: isDual ? styles[1] : "",
      layout: w.layout || "",
      colors: w.color ? [w.color] : [],
      tones: w.tone ? [w.tone] : [],
      moods: w.mood ? [w.mood] : []
    });
    const txt = E.makeTextInputNode(64, 496, {
      text: w.prompt || w.title || ""
    });
    const safeMode = w.mode && w.mode !== "photo" ? w.mode : "graphic-text";
    const ctrl = E.makeOutputControlNode(488, 176, {
      mode: safeMode,
      ratio: w.ratio || "3:4",
      count: 1
    });
    const nodes = [sp, txt, ctrl];
    const edges = [
      { id: E.uid("edge"), from: sp.id, to: ctrl.id },
      { id: E.uid("edge"), from: txt.id, to: ctrl.id }
    ];
    return { blueprint: isDual ? "fusion" : "single", nodes, edges, selectedIds: [] };
  }

  function routeArticleEntryFromUrl(params, { renderNow = true } = {}) {
    flushUnifiedArticleEditor();
    syncAllTabsArticlesIntoStore();
    ensureArticleWorkspace();
    CS.stageView = "preview";
    if (DOM.previewStage) DOM.previewStage.style.display = "flex";
    const aidParam = params.get("articleId");
    const subviewParam = params.get("subview");
    const targetAid = aidParam || CS.activeArticleId;
    const targetArt = targetAid ? (CS.myArticles || []).find((a) => a.id === targetAid) : null;

    // The editor and the reader preview are separate pages now: the editor
    // keeps the writing column at full width, and 预览 opens ?subview=preview,
    // which can jump back with ?subview=editor.
    if (subviewParam === "preview") {
      const activeDraft = (CS.articleEditorDraft && (!targetAid || CS.articleEditorDraft.id === targetAid))
        ? CS.articleEditorDraft
        : null;
      renderArticlePreviewPage(targetArt ? targetArt.id : (aidParam || CS.activeArticleId || null), activeDraft);
    } else if (targetArt) {
      openUnifiedArticleEditor(targetArt.id, { renderNow });
    } else if (aidParam) {
      openUnifiedArticleEditor(null, { createNew: true, renderNow });
    } else {
      openUnifiedArticleEditor(CS.activeArticleId || null, { renderNow });
    }
  }

  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("popstate", () => {
      const params = new URLSearchParams(window.location.search);
      if (params.get("entry") === "article") {
        routeArticleEntryFromUrl(params, { renderNow: true });
      }
    });
  }

  async function hydrateTabsAndUrlParams() {
    ensureDefaultSavedWorkflows();
    CS.resourceEntryWarning = "";
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get("tab");
    const forkId = params.get("fork");
    const forkTopicId = params.get("forkTopic");
    const forkGenId = params.get("forkGen") || params.get("forkGeneration");
    const forkItemId = params.get("forkItem") || "";
    const styleParam = params.get("style");
    const layoutParam = params.get("layout");

    const storedOpen = readJsonStorage(OPEN_TABS_KEY, null);
    if (storedOpen && Array.isArray(storedOpen.tabs) && storedOpen.tabs.length > 0) {
      CS.tabs = storedOpen.tabs
        // Older builds saved the article workspace as a tab; drop it so the
        // preset that bounced users into 文章模式 does not come back.
        .filter((t) => t && t.blueprint !== "article")
        .map((t) => {
        const bp = t.blueprint === "xhs" ? "series" : t.blueprint;
        const cleanTabTitle = String(t.title || "").includes("小红书组图") ? "🗂️ 套图创作" : t.title;
        return {
          ...t,
          title: cleanTabTitle,
          blueprint: bp,
          undoStack: [],
          redoStack: [],
          graph: normalizeGraphSchema(t.graph)
        };
      });
      CS.activeTabId = storedOpen.activeTabId || (CS.tabs.length ? CS.tabs[0].id : null);
    } else {
      CS.tabs = [];
      CS.activeTabId = null;
    }

    const normTabParam = tabParam === "xhs" || tabParam === "series" ? "ip_story" : tabParam;
    const validTabKeys = ["single", "loop_100", "style_ab", "ip_story", "omnimedia", "article", "fusion", "loop", "blank"];
    if (normTabParam && validTabKeys.includes(normTabParam)) {
      const existing = CS.tabs.find((t) => t.blueprint === normTabParam);
      if (existing) {
        CS.activeTabId = existing.id;
      } else {
        const titles = {
          single: "节气海报极速出图",
          loop_100: "百图矩阵批量生产",
          style_ab: "同文案多画风横评",
          ip_story: "IP角色连续绘本",
          omnimedia: "全媒体一稿三端",
          article: "深度长文自动配图",
          fusion: "跨媒介双画风融合",
          loop: "批量出图",
          blank: "空白工作流"
        };
        const created = createWorkflowTab({ title: titles[normTabParam], blueprint: normTabParam, makeActive: false });
        CS.activeTabId = created.id;
      }
    } else if (forkId) {
      // A V3 work can have different recipes for each image. Retain the image
      // selector until the server confirms the draft was applied; failed
      // requests stay retryable by refreshing the deep link.
      const forkCanvas = params.get("entry") === "canvas";
      CS.stageView = forkCanvas ? "canvas" : "quick";
      const forkImage = params.get("image");
      let forkStarted = false;
      const executeFork = async () => {
        if (forkStarted) return;
        if (!App.state?.loggedIn) {
          S.openLoginModal("做同款请先登录账号", () => {
            if (App.state?.loggedIn) executeFork();
          });
          return;
        }
        forkStarted = true;
        try {
          const query = forkImage === null ? "" : "?image=" + encodeURIComponent(forkImage);
          const resp = await fetch(`/api/studio/recipes/from-work/${encodeURIComponent(forkId)}${query}`, {
            credentials: "include"
          });
          if (!resp.ok) {
            let detail = "";
            try {
              const errorData = await resp.json();
              detail = errorData.message || errorData.error || "";
            } catch (_) {}
            throw new Error(detail || (resp.status === 404 ? "作品不存在或已不可见" : "无法读取作品配方"));
          }
          const data = await resp.json();
          if (!data || !data.draft) throw new Error("作品缺少可使用的配方参数");
          if (forkCanvas) {
            const draft = data.draft;
            const graph = buildForkGraphFromWork({
              styles: draft.styleIds || [],
              layout: draft.layoutId || "",
              color: (draft.colors || [])[0] || "",
              tone: (draft.tones || [])[0] || "",
              mood: (draft.moods || [])[0] || "",
              ratio: draft.ratio || "3:4",
              mode: ["canvas", "advanced", "workflow"].includes(draft.mode) ? "graphic-text" : draft.mode,
              prompt: draft.subjectHint || draft.subject || "",
              title: draft.subjectHint || "",
            });
            const created = createWorkflowTab({
              title: "做同款 · " + (draft.subjectHint || "作品"),
              blueprint: graph.blueprint, graph, makeActive: false,
            });
            activateWorkflowTab(created.id, { switchToCanvas: true });
            persistOpenTabs();
            fullRenderCanvas();
          } else {
            CS.stageView = "quick";
            // Use the real active graph, not the MakeImage singleton's transient
            // context which may still be empty during initial tab hydration.
            applyForkDraftToQuickNodes(data.draft);
            if (!getQuickParts()) throw new Error("创作台尚未准备好，请刷新重试");
          }
          const cleanUrl = new URL(window.location.href);
          cleanUrl.searchParams.delete("fork");
          cleanUrl.searchParams.delete("image");
          cleanUrl.searchParams.set("entry", forkCanvas ? "canvas" : "quick");
          window.history.replaceState(null, "", cleanUrl.pathname + cleanUrl.search);
          if (!forkCanvas) renderQuickStart();
          toast("已载入同款参数，可继续调整画风、图型和主题");
        } catch (error) {
          forkStarted = false;
          toast("做同款参数载入失败：" + (error.message || error));
        }
      };
      executeFork();
    } else if (forkGenId) {
      CS.stageView = "quick";
      const cleanUrl = new URL(window.location.href);
      cleanUrl.searchParams.delete("forkGen");
      cleanUrl.searchParams.delete("forkGeneration");
      cleanUrl.searchParams.delete("forkItem");
      cleanUrl.searchParams.set("entry", "quick");
      window.history.replaceState(null, "", cleanUrl.pathname + cleanUrl.search);

      const executeForkGen = async () => {
        const applyDraftData = (data) => {
          if (data && data.draft) {
            const draft = data.draft;
            if (data.source) {
              draft.source = data.source;
              CS.forkGenerationSource = data.source;
            }
            applyForkDraftToQuickNodes(draft);
            if (CS.stageView === "quick") {
              renderQuickStart();
            }
          }
        };

        if (!App.state?.loggedIn) {
          window.__pendingForkGenId = forkGenId;
          window.__pendingForkItemId = forkItemId;
          S.openLoginModal("复刻配方请先登录账号", () => {
            if (App.state?.loggedIn && window.__pendingForkGenId) {
              const fgid = window.__pendingForkGenId;
              const fitem = window.__pendingForkItemId;
              window.__pendingForkGenId = null;
              window.__pendingForkItemId = null;
              fetch(`/api/studio/generations/${encodeURIComponent(fgid)}/fork`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ itemId: fitem }),
                credentials: "include"
              })
                .then((r) => {
                  if (r.status === 404 || !r.ok) {
                    toast("该生图记录不可复刻或已下架");
                    return null;
                  }
                  return r.json();
                })
                .then((data) => {
                  if (data) applyDraftData(data);
                })
                .catch(() => toast("该生图记录不可复刻"));
            }
          });
          return;
        }

        try {
          const resp = await fetch(`/api/studio/generations/${encodeURIComponent(forkGenId)}/fork`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ itemId: forkItemId }),
            credentials: "include"
          });
          if (resp.status === 404 || !resp.ok) {
            toast("该生图记录不可复刻或已下架");
            return;
          }
          const data = await resp.json();
          if (data) applyDraftData(data);
        } catch (_) {
          toast("该生图记录不可复刻");
        }
      };
      executeForkGen();
    } else if (forkTopicId) {
      const t = (App.state.topics || []).find((x) => x.id === forkTopicId);
      if (t && t.recipe) {
        const r = t.recipe;
        const fg = buildForkGraphFromWork({
          title: t.title,
          mode: r.mode,
          ratio: r.ratio,
          mood: r.mood,
          prompt: r.prompt || r.theme || t.title,
          styles: [r.style1, r.style2, ...(t.styles || [])].filter((id,index,ids) => id && ids.indexOf(id) === index).slice(0,2),
          layout: r.layout || t.layout,
          color: r.color,
          tone: r.tone
        });
        const created = createWorkflowTab({ title: `💬 帖子配方 · ${t.title.slice(0, 9)}`, blueprint: fg.blueprint, graph: fg, makeActive: false });
        CS.activeTabId = created.id;
      }
    } else if (styleParam !== null || layoutParam !== null) {
      // Resource links start with a clean, form-compatible graph, never a preset.
      const code = value => String(value || "").trim().replace(/^#\s*/, "").toUpperCase();
      const styleCode = code(styleParam);
      const layoutCode = code(layoutParam);

      const ensureResourceLoaded = async (c) => {
        if (!c || Catalog.resourceMap.has(c)) return;
        try {
          const resp = await fetch(`/api/resources/${encodeURIComponent(c)}`);
          if (resp.ok) {
            const data = await resp.json();
            const res = data.resource || data;
            if (res && res.code) {
              const item = {
                id: res.code,
                name: res.name || res.code,
                originalName: res.name || res.code,
                kind: res.kind,
                sourceType: res.sourceType || res.source || "pending",
                image: res.image || res.cover || "",
                cover: res.image || res.cover || "",
                description: res.description || "",
                definition: res.definition || null,
                access: res.access || {},
                canUse: res.canUse !== false,
              };
              Catalog.resourceMap.set(item.id, item);
              if (item.kind === "style") {
                if (!Catalog.styles.some(s => s.id === item.id)) Catalog.styles.push(item);
              } else if (item.kind === "layout") {
                if (!Catalog.layouts.some(l => l.id === item.id)) Catalog.layouts.push(item);
              }
            }
          }
        } catch (e) {
          console.warn("Failed to fetch resource", c, e);
        }
      };

      if (styleCode && !Catalog.resourceMap.has(styleCode)) {
        await ensureResourceLoaded(styleCode);
      }
      if (layoutCode && !Catalog.resourceMap.has(layoutCode)) {
        await ensureResourceLoaded(layoutCode);
      }

      const validStyle = Catalog.resourceMap.get(styleCode)?.kind === "style" ? styleCode : "";
      const validLayout = Catalog.resourceMap.get(layoutCode)?.kind === "layout" ? layoutCode : "";
      const warnings = [];
      if (styleParam !== null && !validStyle) warnings.push("链接中的画风不存在或尚未收录，请重新选择");
      if (layoutParam !== null && !validLayout) warnings.push("链接中的图型不存在或尚未收录，请重新选择");
      CS.resourceEntryWarning = warnings.join("；");
      const g = buildForkGraphFromWork({
        styles: validStyle ? [validStyle] : [], layout: validLayout,
        mode: "graphic-text", ratio: "3:4", prompt: "", title: ""
      });
      const label = validStyle ? `🎨 试用 #${validStyle}` : validLayout ? `📐 试用 ${validLayout}` : "快速创作";
      const created = createWorkflowTab({ title: label, blueprint: "single", graph: g, makeActive: false });
      CS.activeTabId = created.id;
    }

    const activeTab = CS.tabs.find((t) => t.id === CS.activeTabId) || (CS.tabs.length ? CS.tabs[0] : null);
    if (activeTab) {
      CS.activeTabId = activeTab.id;
      CS.graph = normalizeGraphSchema(activeTab.graph);
      CS.vx = activeTab.vx ?? 276;
      CS.vy = activeTab.vy ?? 48;
      CS.vk = activeTab.vk ?? 0.84;
    } else {
      CS.activeTabId = null;
      CS.graph = { blueprint: "blank", nodes: [], edges: [], selectedIds: [] };
      CS.vx = 276;
      CS.vy = 48;
      CS.vk = 0.84;
    }

    ensureGenerationHistoryInitialized();
    syncAllTabsArticlesIntoStore();

    const viewParam = params.get("view");
    if (!viewParam && normTabParam === "article" && isArticleGraph(CS.graph)) {
      CS.stageView = "preview";
      if (!CS.articleSubView) CS.articleSubView = "portal";
    }
    if (viewParam === "articles-all") {
      CS.stageView = "preview";
      CS.articleSubView = "all-list";
      CS.articleListPage = Math.max(1, Number(params.get("page")) || 1);
    } else if (viewParam === "my-articles") {
      openMyArticlesPage({ renderNow: false });
    } else if (viewParam === "history") {
      // Keep the old deep link, but render the studio's own task history.
      ensureQuickTab();
      CS.historyReturnStage = "quick";
      CS.historyReturnUrl = window.location.pathname + "?entry=quick";
      CS.stageView = "history";
    } else if (viewParam === "workflows") {
      CS.stageView = "workflows";
    }
    if (!viewParam && !tabParam) {
      const entryParam = params.get("entry");
      if (entryParam === "canvas") {
        CS.stageView = "canvas";
      } else if (entryParam === "batch") {
        ensureBatchTab();
        CS.stageView = "batch";
      } else if (entryParam === "article") {
        routeArticleEntryFromUrl(params, { renderNow: false });
      } else {
        if (!forkId && !forkTopicId && styleParam === null && layoutParam === null) ensureQuickTab();
        CS.stageView = "quick";
      }
    }
  }

  /* ======================== LOOP NODE PICKER & BATCH LIST EDITOR MODALS ======================== */
  function openLoopPromptsModal(loopId) {
    const loopNode = getNodeById(loopId);
    if (!loopNode || loopNode.type !== "loop") return;
    const ld = loopNode.data;

    const presets = [
      {
        label: "四节气茶席海报",
        lines: [
          "春分 · 龙井新茶与青团手绘节气卡",
          "夏至 · 冰镇杨梅饮与竹编团扇海报",
          "秋分 · 桂花乌龙慢煮手账插画",
          "冬至 · 围炉煮茶与柿子红泥小火炉"
        ]
      },
      {
        label: "电商 4 大核心卖点卡",
        lines: [
          "卖点 01 · 100% 原叶冷萃，0 糖 0 脂轻负担",
          "卖点 02 · 高山云雾春采，三道慢焙锁住兰花香",
          "卖点 03 · 随身便携小方瓶，3 秒即溶冷热皆宜",
          "卖点 04 · 环保再生棉纸礼盒，东方美学伴手礼"
        ]
      },
      {
        label: "科普手绘 4 图鉴系列",
        lines: [
          "图鉴 01 · 手冲咖啡粉水比与水温黄金区间",
          "图鉴 02 · 浅烘、中烘、深烘风味轮对照图解",
          "图鉴 03 · 三段式注水手法水流轨迹拆解",
          "图鉴 04 · 居家手冲常见翻车原因与补救清单"
        ]
      },
      {
        label: "100条日签批量测试",
        lines: E.generateFissionTopics("打工人反内卷治愈手绘日签", "daily_quote", 100)
      }
    ];

    S.openModal({
      title: "编辑批量文案列表（每行 1 条 → 生成 1 张图）",
      sizeClass: "modal-wide",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              ${presets
                .map(
                  (p, idx) =>
                    `<button type="button" class="btn btn-sm" data-loop-preset="${idx}" style="font-size:12px;">${esc(p.label)}</button>`
                )
                .join("")}
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <label class="btn btn-sm" style="cursor:pointer;color:var(--vermilion);border-color:var(--vermilion-border);font-weight:800;">
                导入 .txt / .csv 列表
                <input type="file" id="loop-import-txt-inp" accept=".txt,.csv,.md,text/plain,text/csv,text/markdown" hidden />
              </label>
              <button type="button" class="btn btn-sm" id="loop-clear-txt-btn" style="color:var(--ink-muted);">✕ 清空</button>
            </div>
          </div>

          <textarea
            id="loop-modal-ta"
            class="hw-input"
            style="width:100%;min-height:240px;padding:12px 14px;font-size:13.5px;line-height:1.68;resize:vertical;"
            placeholder="每行输入一条出图主题或文案（空行自动忽略）…&#10;例如：&#10;春分 · 龙井新茶与青团手绘节气卡&#10;夏至 · 冰镇杨梅饮与竹编团扇海报"
          >${esc(ld.promptListText || "")}</textarea>

          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:8px 12px;border-radius:10px;background:var(--paper-bg);border:1px dashed var(--line-strong);font-size:12px;color:var(--ink-muted);">
            <span id="loop-modal-count" style="font-weight:800;color:#0f766e;">共 0 条循环项</span>
            <span>💡 小贴士：若左侧连入了「文本参数」，可在文本参数中写公共母本并用 <code>{item}</code> 引用每行内容、<code>{index}</code> 引用序号。</span>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:10px;">
            <button type="button" class="btn btn-primary" id="loop-modal-save" style="padding:8px 22px;font-weight:850;">保存批量列表</button>
          </div>
        </div>
      `,
      onMount(root) {
        const ta = root.querySelector("#loop-modal-ta");
        const countEl = root.querySelector("#loop-modal-count");
        const updateCnt = () => {
          const cnt = String(ta.value || "")
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean).length;
          countEl.textContent = `当前有效循环项：共 ${cnt} 条 → 运行后将批量生成 ${cnt} 张图`;
        };
        updateCnt();
        ta.oninput = updateCnt;

        root.querySelectorAll("[data-loop-preset]").forEach((btn) => {
          btn.onclick = () => {
            const p = presets[Number(btn.getAttribute("data-loop-preset"))];
            if (p) {
              ta.value = p.lines.join("\n");
              updateCnt();
            }
          };
        });

        root.querySelector("#loop-clear-txt-btn").onclick = () => {
          ta.value = "";
          updateCnt();
          ta.focus();
        };

        root.querySelector("#loop-import-txt-inp").onchange = (ev) => {
          const f = ev.target.files && ev.target.files[0];
          if (!f) return;
          const reader = new FileReader();
          reader.onload = () => {
            const raw = String(reader.result || "");
            const lines = raw
              .split(/\r?\n/)
              .map((line) => line.replace(/^["']|["']$/g, "").trim())
              .filter(Boolean);
            ta.value = lines.join("\n");
            updateCnt();
            toast(`📂 已从《${f.name}》导入 ${lines.length} 条循环文案`);
          };
          reader.readAsText(f);
        };

        root.querySelector("#loop-modal-save").onclick = () => {
          pushUndo();
          ld.promptListText = ta.value;
          ld.manualOverrideFission = Boolean(String(ta.value || "").trim());
          ld.loopMode = "prompts";
          S.closeModal();
          fullRenderCanvas();
          persistOpenTabs();
          const cnt = String(ld.promptListText || "")
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean).length;
          toast(
            cnt > 0
              ? `✓ 已保存 ${cnt} 条循环文案列表`
              : "✓ 已清空手动列表（若上游连有「选题裂变」将自动承接裂变清单）"
          );
        };
      }
    });
  }

  function openFissionListModal(nodeId) {
    const fn = getNodeById(nodeId);
    if (!fn || fn.type !== "fission") return;
    const fd = fn.data || {};
    let curSeed = fd.seedTopic || "打工人反内卷治愈手绘日签";
    let curStrat = fd.strategy || "daily_quote";
    let curCustomStrat = String(fd.customStrategy || "").trim();
    let curCount = Math.max(1, Math.min(200, Math.round(Number(fd.targetCount ?? fd.count) || 10)));
    const initLines = Array.isArray(fd.generatedItems) && fd.generatedItems.length
      ? fd.generatedItems
      : E.generateFissionTopics(curSeed, curStrat, curCount, curCustomStrat);

    S.openModal({
      title: "查看与编辑全部扩写子主题",
      sizeClass: "modal-wide",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;flex-direction:column;gap:10px;padding:12px 14px;border-radius:12px;background:var(--paper-bg);border:1px solid var(--line-soft);">
            <div style="grid-template-columns:1fr 140px auto;gap:10px;align-items:end;display:grid;">
              <div>
                <div style="font-size:11.5px;font-weight:800;color:var(--ink-muted);margin-bottom:4px;">核心母题</div>
                <input type="text" id="fis-modal-seed" class="hw-input" value="${esc(curSeed)}" style="width:100%;padding:7px 10px;font-size:13px;" placeholder="输入 1 个母题，例如：24节气茶饮海报 / 咖啡萃取科普…" />
              </div>
              <div>
                <div style="font-size:11.5px;font-weight:800;color:var(--ink-muted);margin-bottom:4px;">扩写条数 (1~200)</div>
                <input type="number" id="fis-modal-cnt" class="hw-input" min="1" max="200" value="${curCount}" style="width:100%;padding:7px 8px;font-size:13px;text-align:center;font-weight:800;" />
              </div>
              <button type="button" class="btn btn-sm btn-primary" id="fis-modal-regen" style="padding:8px 15px;font-weight:850;background:#6d28d9;border-color:#6d28d9;">
                重新扩写生成
              </button>
            </div>

            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span style="font-size:11.5px;font-weight:800;color:var(--ink-muted);">扩写方向：</span>
              <div id="fis-modal-strat-pills" style="display:flex;gap:6px;flex-wrap:wrap;">
                ${(E.FISSION_STRATEGIES || [])
                  .map(
                    (st) => `
                    <button
                      type="button"
                      class="ic-shelf-group-chip ${!curCustomStrat && curStrat === st.id ? "is-active" : ""}"
                      data-fis-m-strat="${esc(st.id)}"
                      style="padding:4px 10px;font-size:12px;"
                    >${esc(st.label)}</button>
                  `
                  )
                  .join("")}
              </div>
              <input
                type="text"
                id="fis-modal-custom-strat"
                class="hw-input"
                value="${esc(curCustomStrat)}"
                placeholder="或自行填写扩写方向（如：反常识职场痛点提问、节气特调配方拆解…）"
                style="flex:1;min-width:220px;padding:5px 10px;font-size:12.5px;"
              />
            </div>
          </div>

          <textarea
            id="fis-modal-ta"
            class="hw-input"
            style="width:100%;min-height:280px;padding:12px 14px;font-size:13px;line-height:1.65;resize:vertical;font-family:var(--font-sans);"
            placeholder="每行 1 条扩写子主题，可直接在此增删微调…"
          >${esc(initLines.join("\n"))}</textarea>

          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--ink-muted);">
            <span id="fis-modal-summary" style="font-weight:850;color:#6d28d9;">共 ${initLines.length} 条子主题</span>
            <span>连入右侧「批量」+ <strong>1 个</strong>「生成设置」即可一键批量出图。</span>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:10px;">
            <button type="button" class="btn btn-primary" id="fis-modal-save" style="padding:8px 22px;font-weight:850;">保存扩写清单</button>
          </div>
        </div>
      `,
      onMount(root) {
        const seedInp = root.querySelector("#fis-modal-seed");
        const customStratInp = root.querySelector("#fis-modal-custom-strat");
        const cntInp = root.querySelector("#fis-modal-cnt");
        const ta = root.querySelector("#fis-modal-ta");
        const sumEl = root.querySelector("#fis-modal-summary");

        const syncStratUi = () => {
          const hasCustom = Boolean(customStratInp.value.trim());
          root.querySelectorAll("[data-fis-m-strat]").forEach((b) => {
            b.classList.toggle("is-active", !hasCustom && b.getAttribute("data-fis-m-strat") === curStrat);
          });
        };

        const syncSummary = () => {
          const lines = String(ta.value || "")
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean);
          sumEl.textContent = `当前共 ${lines.length} 条不重样子主题 → 下游批量将自动按序生成 ${lines.length} 张图`;
        };
        syncSummary();
        ta.oninput = syncSummary;

        root.querySelectorAll("[data-fis-m-strat]").forEach((btn) => {
          btn.onclick = () => {
            curStrat = btn.getAttribute("data-fis-m-strat") || "daily_quote";
            curCustomStrat = "";
            customStratInp.value = "";
            syncStratUi();
          };
        });

        customStratInp.oninput = () => {
          curCustomStrat = customStratInp.value.trim();
          syncStratUi();
        };

        root.querySelector("#fis-modal-regen").onclick = () => {
          curSeed = seedInp.value.trim() || "手绘视觉专题";
          curCustomStrat = customStratInp.value.trim();
          curCount = Math.max(1, Math.min(200, Math.round(Number(cntInp.value) || 10)));
          cntInp.value = String(curCount);
          const nextItems = E.generateFissionTopics(curSeed, curStrat, curCount, curCustomStrat);
          ta.value = nextItems.join("\n");
          syncSummary();
          toast(`💡 已按「${curCustomStrat || "预置方向"}」重新裂变生成 ${nextItems.length} 条子选题`);
        };

        root.querySelector("#fis-modal-save").onclick = () => {
          const lines = String(ta.value || "")
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean)
            .slice(0, 200);
          pushUndo();
          fn.data.seedTopic = seedInp.value.trim() || "手绘视觉专题";
          fn.data.strategy = curStrat || "daily_quote";
          fn.data.customStrategy = customStratInp.value.trim();
          fn.data.targetCount = Math.max(1, lines.length || 10);
          fn.data.generatedItems = lines.length
            ? lines
            : E.generateFissionTopics(fn.data.seedTopic, fn.data.strategy, 10, fn.data.customStrategy);
          S.closeModal();
          fullRenderCanvas();
          persistOpenTabs();
          toast(`✓ 已保存 ${fn.data.generatedItems.length} 条选题裂变清单`);
        };
      }
    });
  }

  function openBatchGalleryModal(dispId) {
    const dispNode = getNodeById(dispId);
    if (!dispNode || dispNode.type !== "output_display") return;
    const items = Array.isArray(dispNode.data?.items) ? dispNode.data.items : [];
    if (!items.length) {
      toast("当前批量图集暂无成图，请先点击运行");
      return;
    }

    S.openModal({
      title: `🗂️ 批量图集画廊 · 共 ${items.length} 张成图`,
      sizeClass: "modal-wide",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;min-height:520px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
            <input
              type="search"
              id="bgal-search-inp"
              class="hw-input"
              placeholder="🔍 输入序号（如 18、#099）或关键词快速筛选百图…"
              style="flex:1;min-width:240px;padding:8px 12px;font-size:13px;"
            />
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span id="bgal-filter-cnt" style="font-size:12px;font-weight:800;color:var(--ink-muted);">显示全部 ${items.length} 张</span>
              <button type="button" class="btn btn-sm" id="bgal-zip-btn" style="font-weight:800;">📦 打包下载全部 ZIP (${items.length}张)</button>
            </div>
          </div>

          <div
            id="bgal-grid"
            style="display:grid;grid-template-columns:repeat(auto-fill,minmax(156px,1fr));gap:10px;max-height:62vh;overflow-y:auto;padding:2px 4px 10px 2px;"
          ></div>
        </div>
      `,
      onMount(root) {
        const searchInp = root.querySelector("#bgal-search-inp");
        const cntEl = root.querySelector("#bgal-filter-cnt");
        const gridEl = root.querySelector("#bgal-grid");

        const renderCells = () => {
          const q = String(searchInp.value || "").trim().toLowerCase();
          const matched = items
            .map((it, idx) => ({ it, idx }))
            .filter(({ it, idx }) => {
              if (!q) return true;
              const numTag = `#${String(idx + 1).padStart(3, "0")} #${idx + 1} ${idx + 1}`;
              const hay = `${numTag} ${it.title || ""} ${it.prompt || ""} ${it.ratio || ""}`.toLowerCase();
              return hay.includes(q);
            });

          cntEl.textContent = q ? `筛选命中 ${matched.length} / ${items.length} 张` : `显示全部 ${items.length} 张`;

          gridEl.innerHTML = matched
            .map(
              ({ it, idx }) => `
              <div
                class="card"
                data-bgal-idx="${idx}"
                style="padding:6px;border-radius:10px;cursor:pointer;display:flex;flex-direction:column;gap:5px;border:1px solid var(--line-soft);background:#fff;"
                title="点击放大查看第 ${idx + 1} 张：${esc(it.title || "")}"
              >
                <div class="hw-picker-card-media">
                  <img data-hw-src="${esc(it.imageUrl)}" alt="${esc(it.title || "")}" loading="lazy" />
                  <span style="position:absolute;left:5px;top:5px;padding:1px 6px;border-radius:5px;background:rgba(20,17,15,0.74);color:#fff;font-size:10px;font-family:var(--font-mono);font-weight:800;z-index:2;">
                    #${String(idx + 1).padStart(2, "0")}
                  </span>
                  ${it.demoMode ? '<span style="position:absolute;right:5px;top:5px;padding:2px 5px;border-radius:5px;background:#fff0bf;color:#7a4d00;font-size:10px;font-weight:900;z-index:2;">演示</span>' : ""}
                </div>
                <div style="font-size:11.5px;font-weight:800;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                  ${esc(it.title || `成图 #${idx + 1}`)}
                </div>
              </div>
            `
            )
            .join("");

          gridEl.querySelectorAll("[data-bgal-idx]").forEach((cardEl) => {
            cardEl.onclick = () => {
              const item = items[Number(cardEl.getAttribute("data-bgal-idx"))];
              if (item && item.imageUrl) {
                openImageLightbox(item.imageUrl, item.title || "批量成图预览");
              }
            };
          });
        };

        renderCells();
        searchInp.oninput = renderCells;

        root.querySelector("#bgal-zip-btn").onclick = () => {
          exportZipPackage(dispNode.id);
        };
      }
    });
  }

  function openLoopMultiPickerModal(loopNode, kind = "styles") {
    if (!loopNode || loopNode.type !== "loop") return;
    const ld = loopNode.data;
    const isStyle = kind === "styles";
    const pool = isStyle ? Catalog.styles : Catalog.layouts;
    const initialIds = isStyle ? ld.styleIds || [] : ld.layoutIds || [];
    const selectedOrder = [...initialIds.filter(Boolean)];

    let activeGroup = "ALL";
    let searchQuery = "";

    S.openModal({
      title: isStyle
        ? "🔁 选择循环画风列表（按勾选顺序逐款横评批量出图）"
        : "🔁 选择循环图型列表（按勾选顺序逐款版式批量出图）",
      sizeClass: "modal-wide",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;min-height:540px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
            <input type="search" class="hw-input" id="loop-pick-search" placeholder="🔍 搜索编号、名称、关键词..." style="flex:1;min-width:240px;padding:8px 12px;font-size:13px;" />
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <button type="button" class="btn btn-sm" id="loop-pick-rand4">🎲 随机挑 4 款</button>
              <button type="button" class="btn btn-sm" id="loop-pick-clear" style="color:var(--ink-muted);">✕ 清空已选</button>
              <button type="button" class="btn btn-sm btn-primary" id="loop-pick-confirm">✓ 确认加入循环 (${selectedOrder.length})</button>
            </div>
          </div>
          <div id="loop-pick-groups" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--ink-muted);">
            <span id="loop-pick-count">加载中...</span>
            <span>单击卡片按顺序加入/移出循环队列（最多 20 款）</span>
          </div>
          <div id="loop-pick-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(178px,1fr));gap:12px;max-height:56vh;overflow-y:auto;padding:2px 4px 10px 2px;"></div>
        </div>
      `,
      onMount(root) {
        const searchInp = root.querySelector("#loop-pick-search");
        const groupsEl = root.querySelector("#loop-pick-groups");
        const countEl = root.querySelector("#loop-pick-count");
        const gridEl = root.querySelector("#loop-pick-grid");
        const confirmBtn = root.querySelector("#loop-pick-confirm");

        const syncConfirm = () => {
          if (confirmBtn) {
            confirmBtn.textContent = `✓ 确认加入循环 (${selectedOrder.length})`;
          }
        };

        searchInp.oninput = () => {
          searchQuery = searchInp.value.trim().toLowerCase();
          renderGroups();
          renderGrid();
        };

        root.querySelector("#loop-pick-rand4").onclick = () => {
          const freeFirst = pool.filter((x) => x.tier !== "pro_credit");
          const source = freeFirst.length > 0 ? freeFirst : pool;
          selectedOrder.length = 0;
          const src = source.length >= 4 ? source : pool;
          const shuffled = [...src].sort(() => Math.random() - 0.5).slice(0, 4);
          shuffled.forEach((x) => selectedOrder.push(x.id));
          syncConfirm();
          renderGrid();
        };

        root.querySelector("#loop-pick-clear").onclick = () => {
          selectedOrder.length = 0;
          syncConfirm();
          renderGrid();
        };

        if (confirmBtn) {
          confirmBtn.onclick = () => {
            pushUndo();
            if (isStyle) {
              ld.styleIds = [...selectedOrder];
              ld.loopMode = "styles";
            } else {
              ld.layoutIds = [...selectedOrder];
              ld.loopMode = "layouts";
            }
            S.closeModal();
            fullRenderCanvas();
            persistOpenTabs();
            toast(`🔁 已设置 ${selectedOrder.length} 款循环${isStyle ? "画风" : "图型"}！`);
          };
        }

        function renderGroups() {
          const grpSet = new Set();
          pool.forEach((x) => {
            if (x.group) grpSet.add(x.group);
          });
          const tabs = S.visibleResourceGroups(pool, [
            { key: "ALL", label: `全部${isStyle ? "画风" : "图型"}` },
            { key: "FAV", label: "⭐ 收藏" },
            ...[...grpSet].map((g) => ({ key: g, label: S.resourceGroupLabel(g, isStyle ? "style" : "layout") }))
          ], searchQuery);
          if (!tabs.some(g => g.key === activeGroup)) activeGroup = "ALL";
          groupsEl.innerHTML = tabs
            .map(
              (g) => `
              <button type="button" class="ic-shelf-group-chip ${activeGroup === g.key ? "is-active" : ""}" data-lp-grp="${esc(g.key)}" style="padding:5px 11px;font-size:12px;">
                ${esc(g.label)}${g.count !== undefined ? ` (${g.count})` : ""}
              </button>
            `
            )
            .join("");
          groupsEl.querySelectorAll("[data-lp-grp]").forEach((b) => {
            b.onclick = () => {
              activeGroup = b.getAttribute("data-lp-grp");
              renderGroups();
              renderGrid();
            };
          });
        }

        function renderGrid() {
          let list = pool.filter((it) => S.resourceMatchesGroup(it, activeGroup));
          if (searchQuery) {
            list = list.filter((it) =>
              S.resourceSearchText(it)
                .includes(searchQuery)
            );
          }

          countEl.textContent = `共筛出 ${list.length} 项${selectedOrder.length ? ` · 循环顺序：${selectedOrder.join(" → ")}` : ""}`;

          gridEl.innerHTML = list
            .slice(0, 180)
            .map((it) => {
              const id = it.id;
              const title = it.name || it.name_zh || id;
              const orderIdx = selectedOrder.indexOf(id);
              const isSel = orderIdx >= 0;
              return `
                <div class="ic-picker-card ${isSel ? "is-selected" : ""}" data-lp-id="${esc(id)}" style="border:1.5px solid ${
                isSel ? "#0d9488" : "var(--line-soft)"
              };border-radius:11px;overflow:hidden;background:#fff;cursor:pointer;display:flex;flex-direction:column;box-shadow:${
                isSel ? "0 0 0 3px rgba(13,148,136,0.2)" : "0 2px 6px rgba(24,20,17,0.04)"
              };">
                  <div style="position:relative;aspect-ratio:4/3;background:#f3ede3;overflow:hidden;display:flex;align-items:center;justify-content:center;">
                    <img data-hw-src="${esc(it.image)}" alt="${esc(title)}" loading="lazy" style="width:100%;height:100%;object-fit:contain;display:block;" />
                    ${
                      isSel
                        ? `<span style="position:absolute;right:6px;top:6px;padding:2px 8px;border-radius:999px;background:#0d9488;color:#fff;font-size:10.5px;font-weight:850;">循环 #${orderIdx + 1}</span>`
                        : ""
                    }
                  </div>
                  <div style="padding:8px 10px;display:flex;flex-direction:column;gap:2px;">
                    <div style="font-family:var(--font-mono, monospace);font-size:11px;font-weight:700;color:var(--ink-muted, #786f65);">${esc(id)}</div>
                    <div style="font-size:12.5px;font-weight:800;color:#221d18;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(title)}</div>
                    <div style="font-size:11px;color:#786f65;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(S.resourceGroupLabel(it.group, it.kind))}</div>
                  </div>
                </div>
              `;
            })
            .join("");

          gridEl.querySelectorAll("[data-lp-id]").forEach((card) => {
            card.onclick = () => {
              const id = card.getAttribute("data-lp-id");
              const idx = selectedOrder.indexOf(id);
              if (idx >= 0) {
                selectedOrder.splice(idx, 1);
              } else {
                if (selectedOrder.length >= 20) {
                  toast("单次循环最多支持勾选 20 款");
                  return;
                }
                selectedOrder.push(id);
              }
              syncConfirm();
              renderGrid();
            };
          });
        }

        renderGroups();
        renderGrid();
      }
    });
  }

  /* ======================== SPAWN, BRIDGE FAN-OUT, AUTO-UPSTREAM ARTICLE RULE & GENERATION ENGINE ======================== */
  function spawnShelfItem(itemSpec, targetWorldPos = null, autoConnectTargetId = null) {
    pushUndo();
    const singleSel = CS.graph.selectedIds.length === 1 ? getNodeById(CS.graph.selectedIds[0]) : null;
    const loops = CS.graph.nodes.filter((n) => n.type === "loop");
    const bridges = CS.graph.nodes.filter((n) => n.type === "bridge");
    const ctrls = CS.graph.nodes.filter((n) => n.type === "output_control");

    const connectTarget =
      (autoConnectTargetId && getNodeById(autoConnectTargetId)) ||
      (singleSel && (singleSel.type === "loop" || singleSel.type === "bridge" || singleSel.type === "output_control")
        ? singleSel
        : loops.length === 1 && itemSpec.kind !== "loop" && itemSpec.kind !== "bridge" && itemSpec.kind !== "output_control"
          ? loops[0]
          : bridges.length === 1 && itemSpec.kind !== "loop" && itemSpec.kind !== "bridge" && itemSpec.kind !== "output_control"
            ? bridges[0]
            : ctrls.length === 1
              ? ctrls[0]
              : null);

    let wx = targetWorldPos ? snapVal(targetWorldPos.x) : 240;
    let wy = targetWorldPos ? snapVal(targetWorldPos.y) : 160;

    if (!targetWorldPos && itemSpec.kind === "output_control" && singleSel && (singleSel.type === "bridge" || singleSel.type === "loop")) {
      const existingDown = CS.graph.edges
        .filter((e) => e.from === singleSel.id)
        .map((e) => getNodeById(e.to))
        .filter(Boolean);
      wx = snapVal(singleSel.x + (singleSel.w || 336) + 88);
      wy = existingDown.length
        ? snapVal(Math.max(...existingDown.map((d) => d.y + (d.h || 348))) + 36)
        : snapVal(Math.max(48, singleSel.y - 40));
    } else if (!targetWorldPos && (itemSpec.kind === "bridge" || itemSpec.kind === "loop")) {
      if (singleSel && isInputNodeType(singleSel.type)) {
        wx = snapVal(singleSel.x + (singleSel.w || 336) + 88);
        wy = snapVal(Math.max(48, singleSel.y + 16));
      } else if (connectTarget && connectTarget.type === "output_control") {
        if (itemSpec.kind === "loop" && connectTarget.x < 840) {
          wx = snapVal(Math.max(468, connectTarget.x));
          wy = snapVal(Math.max(64, connectTarget.y - 20));
          connectTarget.x = snapVal(wx + 424);
        } else {
          wx = snapVal(Math.max(64, connectTarget.x - (itemSpec.kind === "loop" ? 416 : 336)));
          wy = snapVal(connectTarget.y + 24);
        }
      } else if (DOM.viewport) {
        const r = DOM.viewport.getBoundingClientRect();
        const c = screenToWorld(r.left + r.width * 0.5, r.top + r.height * 0.42);
        wx = snapVal(c.x - 160);
        wy = snapVal(c.y - 120);
      }
    } else if (!targetWorldPos && connectTarget && itemSpec.kind !== "output_control") {
      const upCount = CS.graph.edges.filter((e) => e.to === connectTarget.id).length;
      wx = snapVal(Math.max(48, connectTarget.x - 416));
      wy = snapVal(Math.max(48, connectTarget.y - 80 + upCount * 240));
    } else if (!targetWorldPos && DOM.viewport) {
      const r = DOM.viewport.getBoundingClientRect();
      const c = screenToWorld(r.left + r.width * 0.54, r.top + r.height * 0.42);
      wx = snapVal(c.x - 160);
      wy = snapVal(c.y - 140);
    }

    let created = null;
    if (itemSpec.kind === "skill_params") {
      created = E.makeSkillParamsNode(wx, wy);
      CS.graph.nodes.push(created);
      if (connectTarget) ensureEdge(created.id, connectTarget.id);
    } else if (itemSpec.kind === "asset") {
      created = E.makeAssetNode(wx, wy);
      CS.graph.nodes.push(created);
      if (connectTarget) ensureEdge(created.id, connectTarget.id);
    } else if (itemSpec.kind === "text_input") {
      created = E.makeTextInputNode(wx, wy);
      CS.graph.nodes.push(created);
      if (connectTarget) ensureEdge(created.id, connectTarget.id);
    } else if (itemSpec.kind === "fission") {
      created = E.makeFissionNode(wx, wy, itemSpec.overrides || {});
      CS.graph.nodes.push(created);
      if (connectTarget) ensureEdge(created.id, connectTarget.id);
    } else if (itemSpec.kind === "bridge") {
      created = E.makeBridgeNode(wx, wy);
      CS.graph.nodes.push(created);
      if (singleSel && isInputNodeType(singleSel.type)) {
        ensureEdge(singleSel.id, created.id);
      } else if (connectTarget && connectTarget.type === "output_control") {
        ensureEdge(created.id, connectTarget.id);
      }
    } else if (itemSpec.kind === "loop") {
      created = E.makeLoopNode(wx, wy, itemSpec.overrides || {});
      CS.graph.nodes.push(created);
      if (singleSel && (isInputNodeType(singleSel.type) || singleSel.type === "bridge")) {
        ensureEdge(singleSel.id, created.id);
        if (ctrls.length === 1) {
          if (ctrls[0].x < created.x + 360) ctrls[0].x = snapVal(created.x + 424);
          ensureEdge(created.id, ctrls[0].id);
        }
      } else if (connectTarget && connectTarget.type === "output_control") {
        // Splice loop cleanly between existing direct inputs and output_control when added from toolbox
        if (!targetWorldPos) {
          const directInputEdges = CS.graph.edges.filter((e) => {
            if (e.to !== connectTarget.id) return false;
            const src = getNodeById(e.from);
            return src && (isInputNodeType(src.type) || src.type === "bridge");
          });
          if (directInputEdges.length > 0) {
            const srcIds = directInputEdges.map((e) => e.from);
            CS.graph.edges = CS.graph.edges.filter((e) => !directInputEdges.includes(e));
            srcIds.forEach((sid) => ensureEdge(sid, created.id));
          }
        }
        ensureEdge(created.id, connectTarget.id);
      }
    } else if (itemSpec.kind === "output_control") {
      created = E.makeOutputControlNode(wx, wy);
      CS.graph.nodes.push(created);
      if (singleSel && (singleSel.type === "loop" || singleSel.type === "bridge" || isInputNodeType(singleSel.type))) {
        ensureEdge(singleSel.id, created.id);
      } else if (loops.length === 1 && !autoConnectTargetId) {
        ensureEdge(loops[0].id, created.id);
      } else if (bridges.length === 1 && !autoConnectTargetId) {
        ensureEdge(bridges[0].id, created.id);
      }
    }

    if (created) {
      CS.graph.selectedIds = [created.id];
    }
    fullRenderCanvas();
    persistOpenTabs();
    return created;
  }

  function spawnDownstreamControlFromLoop(loopId) {
    const lp = getNodeById(loopId);
    if (!lp || lp.type !== "loop") return null;
    pushUndo();

    const downCtrls = CS.graph.edges
      .filter((e) => e.from === lp.id)
      .map((e) => getNodeById(e.to))
      .filter((n) => n && n.type === "output_control");

    const wx = downCtrls.length ? downCtrls[0].x : snapVal(lp.x + (lp.w || 336) + 88);
    const wy = downCtrls.length
      ? snapVal(Math.max(...downCtrls.map((c) => c.y + (c.h || 348))) + 36)
      : snapVal(Math.max(48, lp.y - 20));

    const ctrl = E.makeOutputControlNode(wx, wy, { mode: "graphic-text", count: 1 });
    CS.graph.nodes.push(ctrl);
    ensureEdge(lp.id, ctrl.id);
    CS.graph.selectedIds = [ctrl.id];
    fullRenderCanvas();
    persistOpenTabs();
    toast("🔁 已从「循环批量」连接新的「输出控制」节点！");
    return ctrl;
  }

  function spawnDownstreamControlFromBridge(bridgeId) {
    const brg = getNodeById(bridgeId);
    if (!brg || brg.type !== "bridge") return null;
    pushUndo();

    const downCtrls = CS.graph.edges
      .filter((e) => e.from === brg.id)
      .map((e) => getNodeById(e.to))
      .filter((n) => n && n.type === "output_control");

    const wx = downCtrls.length ? downCtrls[0].x : snapVal(brg.x + (brg.w || 248) + 88);
    const wy = downCtrls.length
      ? snapVal(Math.max(...downCtrls.map((c) => c.y + (c.h || 348))) + 36)
      : snapVal(Math.max(48, brg.y - 60));

    let defaultMode = "graphic-text";
    if (!downCtrls.some((c) => c.data?.mode === "article-illust") && downCtrls.length > 0) {
      defaultMode = "series";
    }

    const ctrl = E.makeOutputControlNode(wx, wy, { mode: defaultMode });
    CS.graph.nodes.push(ctrl);
    ensureEdge(brg.id, ctrl.id);
    CS.graph.selectedIds = [ctrl.id];
    fullRenderCanvas();
    persistOpenTabs();
    toast(`🔗 已从「桥接」分发出新的「输出控制」节点！`);
    return ctrl;
  }

  function getDownstreamArticlePlanNode(ctrlNode) {
    if (!ctrlNode) return null;
    const outEdge = CS.graph.edges.find((e) => {
      if (e.from !== ctrlNode.id) return false;
      const t = getNodeById(e.to);
      return t && t.type === "article_plan";
    });
    return outEdge ? getNodeById(outEdge.to) : null;
  }

  function getDownstreamDisplayNodes(sourceNodeId) {
    if (!sourceNodeId) return [];
    const outNodes = CS.graph.edges
      .filter((e) => e.from === sourceNodeId)
      .map((e) => getNodeById(e.to))
      .filter((n) => n && n.type === "output_display");
    return outNodes.sort((a, b) => {
      const sa = typeof a.data?.slotIndex === "number" ? a.data.slotIndex : 999;
      const sb = typeof b.data?.slotIndex === "number" ? b.data.slotIndex : 999;
      return sa - sb || a.y - b.y;
    });
  }

  function clearControlWorkspaceResults(ctrlId) {
    const ctrl = getNodeById(ctrlId);
    if (!ctrl) return;
    ctrl.data.status = "idle";
    delete ctrl.data.error;
    delete ctrl.data.activeBatchId;
    ctrl.data.elapsedSec = 0;

    const displays = getDownstreamDisplayNodes(ctrl.id);
    for (const dn of displays) {
      dn.data.items = [];
      dn.data.status = "idle";
      delete dn.data.error;
      delete dn.data.pendingTaskId;
      delete dn.data.pendingRequestId;
      delete dn.data.activeBatchId;
      delete dn.data.selectedIdx;
      delete dn.data.previewIdx;
      delete dn.data.downloadUrl;
      dn.data.pendingRequestIds = {};
      dn.data.pendingSpec = {};
      dn.data.elapsedSec = 0;
      if (dn.data.kind === "batch_gallery") {
        dn.data.page = 1;
      }
    }
  }

  function removeOrphanedDisplayNode(dispNode, parentId = null) {
    if (!dispNode || dispNode.type !== "output_display") return;
    const hasDownstreamChain = CS.graph.edges.some((e) => e.from === dispNode.id);
    if (hasDownstreamChain) {
      if (parentId) {
        CS.graph.edges = CS.graph.edges.filter((e) => !(e.from === parentId && e.to === dispNode.id));
      }
      return;
    }
    CS.graph.nodes = CS.graph.nodes.filter((n) => n.id !== dispNode.id);
    CS.graph.edges = CS.graph.edges.filter((e) => e.from !== dispNode.id && e.to !== dispNode.id);
    CS.graph.selectedIds = (CS.graph.selectedIds || []).filter((id) => id !== dispNode.id);
  }

  const BATCH_GALLERY_THRESHOLD = 6;

  function syncControlDisplayNodes(ctrlNode, count, { markGenerating = false, onlyDispNodeId = null, onlyItemIdx = null, batchId = null, preserveCompleted = null } = {}) {
    if (!ctrlNode || ctrlNode.type !== "output_control") return { nodes: [], createdCount: 0, isBatchGallery: false };
    const safeCount = Math.max(1, Math.min(200, Math.round(Number(count) || 1)));
    const existing = getDownstreamDisplayNodes(ctrlNode.id);
    const baseX = snapVal(ctrlNode.x + (ctrlNode.w || 344) + 96);

    // Smart Single-Node Batch Gallery: when generating > 6 images (e.g. 12, 50, 100+),
    // converge into 1 paginated "🗂️ 批量图集" node instead of exploding the canvas into 100 nodes!
    if (safeCount > BATCH_GALLERY_THRESHOLD || (existing[0] && existing[0].data?.kind === "batch_gallery" && !onlyDispNodeId && onlyItemIdx === null)) {
      let galNode = existing[0] || null;
      let createdCount = 0;
      const spawnY = snapVal(Math.max(48, ctrlNode.y - 24));
      if (!galNode) {
        galNode = E.makeOutputDisplayNode(baseX, spawnY, {
          title: "批量图集",
          status: markGenerating ? "generating" : "idle",
          mode: ctrlNode.data.mode || "graphic-text",
          slotIndex: 0,
          sourceNodeId: ctrlNode.id,
          items: []
        });
        galNode.w = 388;
        galNode.data.kind = "batch_gallery";
        galNode.data.page = 1;
        galNode.data.totalTarget = safeCount;
        CS.graph.nodes.push(galNode);
        ensureEdge(ctrlNode.id, galNode.id);
        createdCount = 1;
      } else {
        galNode.title = "批量图集";
        galNode.w = 388;
        galNode.data.slotIndex = 0;
        galNode.data.sourceNodeId = ctrlNode.id;
        galNode.data.mode = ctrlNode.data.mode || "graphic-text";
        galNode.data.kind = "batch_gallery";
        galNode.data.page = 1;
        galNode.data.totalTarget = safeCount;
        ensureEdge(ctrlNode.id, galNode.id);
      }

      // Moving from N independent display nodes to the >6 gallery must
      // retain previously finished slots in their original positions.
      const preservedGalleryItems = preserveCompleted instanceof Map
        ? Array.from({length:safeCount},(_,idx)=>preserveCompleted.get(idx) || null)
        : null;
      if (markGenerating) {
        galNode.data.status = "generating";
        galNode.data.elapsedSec = 0;
        if (batchId) galNode.data.activeBatchId = batchId;
        if (onlyDispNodeId || onlyItemIdx !== null) {
          if (Array.isArray(galNode.data.items) && onlyItemIdx !== null && onlyItemIdx < galNode.data.items.length) {
            galNode.data.items[onlyItemIdx] = null;
          }
        } else {
          galNode.data.items = preservedGalleryItems || [];
          delete galNode.data.error;
          delete galNode.data.pendingTaskId;
          delete galNode.data.pendingRequestId;
          galNode.data.pendingRequestIds = {};
          galNode.data.pendingSpec = {};
        }
      }

      if (existing.length > 1) {
        for (const extra of existing.slice(1)) {
          removeOrphanedDisplayNode(extra, ctrlNode.id);
        }
      }
      return { nodes: [galNode], createdCount, isBatchGallery: true };
    }

    const startY =
      safeCount > 1 ? snapVal(Math.max(48, ctrlNode.y - 60)) : snapVal(Math.max(48, ctrlNode.y - 12));

    let nextY = existing.length
      ? snapVal(Math.max(...existing.map((d) => d.y + (d.h || 308))) + 32)
      : startY;

    const activeNodes = [];
    let createdCount = 0;

    for (let i = 0; i < safeCount; i++) {
      let disp = existing[i] || null;
      if (!disp) {
        const spawnY = existing.length === 0 ? snapVal(startY + i * 336) : nextY;
        disp = E.makeOutputDisplayNode(baseX, spawnY, {
          title: "图片显示",
          status: markGenerating ? "generating" : "idle",
          mode: ctrlNode.data.mode || "graphic-text",
          slotIndex: i,
          sourceNodeId: ctrlNode.id,
          items: []
        });
        CS.graph.nodes.push(disp);
        ensureEdge(ctrlNode.id, disp.id);
        nextY = snapVal(spawnY + 336);
        createdCount += 1;
      } else {
        disp.title = "图片显示";
        disp.w = 308;
        disp.data.slotIndex = i;
        disp.data.sourceNodeId = ctrlNode.id;
        disp.data.mode = ctrlNode.data.mode || "graphic-text";
        if (disp.data.kind === "batch_gallery" && Array.isArray(disp.data.items) && disp.data.items.length > 1) {
          disp.data.items = [disp.data.items[0]];
        }
        disp.data.kind = "single";
        ensureEdge(ctrlNode.id, disp.id);
      }

      const preservedItem = preserveCompleted instanceof Map ? preserveCompleted.get(i) : null;
      if (preservedItem?.imageUrl) {
        disp.data.items = [preservedItem];
        disp.data.status = "done";
      }
      const shouldMarkThis = markGenerating && !preservedItem?.imageUrl && (
        (!onlyDispNodeId && onlyItemIdx === null) ||
        (onlyDispNodeId && disp.id === onlyDispNodeId) ||
        (onlyItemIdx !== null && onlyItemIdx === i)
      );

      if (shouldMarkThis) {
        disp.data.status = "generating";
        disp.data.elapsedSec = 0;
        disp.data.items = [];
        delete disp.data.error;
        delete disp.data.pendingTaskId;
        delete disp.data.pendingRequestId;
        if (batchId) disp.data.activeBatchId = batchId;
      }
      activeNodes.push(disp);
    }

    if (!onlyDispNodeId && existing.length > safeCount) {
      for (const extra of existing.slice(safeCount)) {
        removeOrphanedDisplayNode(extra, ctrlNode.id);
      }
    }

    return { nodes: activeNodes, createdCount, isBatchGallery: false };
  }

  function syncArticlePlanDisplayNodes(planNode) {
    if (!planNode || planNode.type !== "article_plan") return { nodes: [], createdCount: 0 };
    const orderedCards = sortPlanCardsInDocOrder(planNode.data?.cards || []);
    const activeCards = orderedCards.filter((c) => Boolean(c.imageUrl) || c.status === "generating");
    const existing = getDownstreamDisplayNodes(planNode.id);
    const usedIds = new Set();

    const baseX = snapVal(planNode.x + (planNode.w || 392) + 96);
    const startY =
      activeCards.length > 1 ? snapVal(Math.max(48, planNode.y - 60)) : snapVal(Math.max(48, planNode.y - 12));
    let nextY = existing.length
      ? snapVal(Math.max(...existing.map((d) => d.y + (d.h || 308))) + 32)
      : startY;

    const syncedNodes = [];
    let createdCount = 0;

    activeCards.forEach((c, idx) => {
      let disp = existing.find((d) => !usedIds.has(d.id) && d.data?.planCardId === c.id) || null;
      if (!disp) {
        disp = existing.find((d) => !usedIds.has(d.id) && !d.data?.planCardId) || null;
      }

      if (!disp) {
        const spawnY = existing.length === 0 ? snapVal(startY + idx * 336) : nextY;
        disp = E.makeOutputDisplayNode(baseX, spawnY, {
          title: "图片显示",
          status: c.status === "generating" ? "generating" : "done",
          mode: "article-illust",
          slotIndex: idx,
          planCardId: c.id,
          sourceNodeId: planNode.id,
          updatedAt: planNode.data.updatedAt || "刚刚",
          runCount: Math.max(1, planNode.data.runCount || 1),
          items: c.imageUrl
            ? [
                {
                  id: c.id,
                  slotKey: c.id,
                  role: c.role || "inline",
                  title: c.title || "配图",
                  ratio: c.ratio || "4:3",
                  prompt: c.prompt || "",
                  imageUrl: c.imageUrl
                }
              ]
            : []
        });
        CS.graph.nodes.push(disp);
        ensureEdge(planNode.id, disp.id);
        nextY = snapVal(spawnY + 336);
        createdCount += 1;
      } else {
        disp.title = "图片显示";
        disp.w = 308;
        disp.data.slotIndex = idx;
        disp.data.planCardId = c.id;
        disp.data.sourceNodeId = planNode.id;
        disp.data.mode = "article-illust";
        disp.data.kind = "single";
        disp.data.status = c.status === "generating" ? "generating" : "done";
        disp.data.updatedAt = planNode.data.updatedAt || disp.data.updatedAt || "刚刚";
        disp.data.runCount = Math.max(1, planNode.data.runCount || disp.data.runCount || 1);
        disp.data.items = c.imageUrl
          ? [
              {
                id: c.id,
                slotKey: c.id,
                role: c.role || "inline",
                title: c.title || "配图",
                ratio: c.ratio || "4:3",
                prompt: c.prompt || "",
                imageUrl: c.imageUrl
              }
            ]
          : [];
        ensureEdge(planNode.id, disp.id);
      }

      usedIds.add(disp.id);
      syncedNodes.push(disp);
    });

    for (const oldDisp of existing) {
      if (!usedIds.has(oldDisp.id)) {
        removeOrphanedDisplayNode(oldDisp, planNode.id);
      }
    }

    return { nodes: syncedNodes, createdCount };
  }

  /* ======================== MY ARTICLES STORE, SEED ARCHIVE & LIVE SYNC ======================== */
  function formatArticleTimeLabel(ms) {
    const t = Number(ms) || Date.now();
    const diff = Date.now() - t;
    if (diff >= 0 && diff < 60 * 1000) return "刚刚";
    const d = new Date(t);
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${mm}-${dd} ${hh}:${min}`;
  }

  function createSeededMyArticles() {
    const now = Date.now();
    const hour = 3600 * 1000;
    const seeds = [
      {
        title: "为什么越忙的人，越需要「留白工作法」？",
        hoursAgo: 1,
        style1: "FA-003",
        layout: "IG-003",
        imgs: ["/images/poster-demo-autumn-equinox.webp", "/images/individual/FA/FA-003.webp", "/images/B_036-048.webp"],
        md: E.DEFAULT_STARTER_ARTICLE_MD
      },
      {
        title: "视觉笔记为什么能让人一眼记住核心逻辑？",
        hoursAgo: 3,
        style1: "FA-003",
        layout: "IG-003",
        imgs: ["/images/poster-demo-autumn-equinox.webp", "/images/layouts/infographics/IG-003.webp", "/images/individual/FA/FA-003.webp"],
        md: `# 视觉笔记为什么能让人一眼记住核心逻辑？\n\n在信息过载的阅读场景里，纯文字长文往往在第三屏就流失了 60% 的读者。手绘视觉笔记并不是简单的装饰，而是把抽象关系翻译成空间秩序。\n\n## 一、用空间位置替代冗长连接词\n\n当两个概念存在因果、递进或对比关系时，箭头与留白比三行解释更直观。读者先看到结构，再读进细节。\n\n## 二、给每张插图只保留一个视觉锚点\n\n一张好配图不追求塞满所有名词，而是用温暖的纸本肌理托住最核心的那句判断。`
      },
      {
        title: "独立创作者的内容复利：把一次深思考拆成十份表达",
        hoursAgo: 7,
        style1: "FA-013",
        layout: "SC-023",
        imgs: ["/images/graphic-text-mode-demo.webp", "/images/layouts/social-cards/SC-023.webp", "/images/individual/FA/FA-013.webp"],
        md: `# 独立创作者的内容复利：把一次深思考拆成十份表达\n\n很多创作者每周都在追热点，却很少沉淀属于自己的视觉母本。真正可持续的节奏，是先打磨一篇深度长文，再自然生长出封面、金句卡与系列插图。\n\n## 一、先定母题，再做多端视觉延展\n\n当底层观点足够扎实，公众号长文配图与社区讨论帖只需要切换画幅比例与信息密度。\n\n## 二、建立固定的个人色彩与笔触识别度\n\n长期保持宣纸暖底与朱砂点睛色，读者滑过信息流时无需看署名就能认出你的作品。`
      },
      {
        title: "从草稿纸到出版级专栏：手绘信息图的黄金三步",
        hoursAgo: 12,
        style1: "FB-031",
        layout: "IG-005",
        imgs: ["/images/layouts/infographics/IG-005.webp", "/images/individual/FB/FB-031.webp", "/images/A_001-016.webp"],
        md: `# 从草稿纸到出版级专栏：手绘信息图的黄金三步\n\n不需要美术科班功底，只要掌握拆解段落、匹配图型与克制用色三步，就能为技术或商业专栏配上耐看的手绘插图。\n\n## 一、提取每节的唯一转折句\n\n把两千字压缩成三个关键转折，每个转折对应一张 4:3 正文插图位。\n\n## 二、让色彩只承担重点高亮职责\n\n大面积使用低饱和暖灰与墨线，仅在结论处点缀一抹朱砂红。`
      },
      {
        title: "东方留白美学在现代数字产品设计中的回响",
        hoursAgo: 18,
        style1: "FA-003",
        layout: "SC-020",
        imgs: ["/images/poster-demo-autumn-equinox.webp", "/images/B_036-048.webp"],
        md: `# 东方留白美学在现代数字产品设计中的回响\n\n宋画里的计白当黑，放在今天的屏幕界面上依然成立。留白不是浪费像素，而是给用户的注意力留出呼吸的走廊。\n\n## 一、减少视觉噪音比增加功能更难\n\n每一个多余的按钮都在争夺主路径的权重。把非核心操作收进上下文，主画布才能清朗。\n\n## 二、温润纸感带来的心理松弛度\n\n相比刺眼的纯白冷光背景，微暖纸色能显著降低长文阅读与连续创作的视觉疲劳。`
      },
      {
        title: "如何用故事分镜感画好人物科普长文配图？",
        hoursAgo: 25,
        style1: "FA-013",
        layout: "SC-024",
        imgs: ["/images/H_217-232.webp", "/images/layouts/social-cards/SC-024.webp", "/images/layouts/social-cards/SC-006.webp"],
        md: `# 如何用故事分镜感画好人物科普长文配图？\n\n科普文章最怕变成枯燥的说明书。引入一个贯穿全文的手绘角色，在每个章节遇到具体困境并解开谜题，阅读完播率会翻倍。\n\n## 一、固定主角的外观特征与小道具\n\n通过上游图片参数锁定主角形象，确保封面与三张正文插图里的角色衣着笔触前后一致。\n\n## 二、用微表情传递情绪转折\n\n从开篇的困惑挠头，到豁然开朗的执笔记录，情绪递进让长文更有温度。`
      },
      {
        title: "慢下来做内容：我的周更专栏工作流复盘",
        hoursAgo: 32,
        style1: "FA-003",
        layout: "IG-003",
        imgs: ["/images/individual/FA/FA-003.webp", "/images/graphic-text-mode-demo.webp"],
        md: `# 慢下来做内容：我的周更专栏工作流复盘\n\n过去我常常卡在找配图这一步：免费图库千篇一律，自己画又耗时半天。把配图方案拆成卡片式编排后，写完正文十分钟就能配齐整套插图。\n\n## 一、原文只读，配图卡片自由拖拽\n\n定稿后的文章不再误触改乱字句，只需像摆桌上画片一样把插图拖到最合适的段落间隙。\n\n## 二、一键打包 ZIP 归档与论坛共创\n\n生成满意后直接导出图文包备份，再发到交流论坛听听同行调词建议。`
      },
      {
        title: "水彩淡彩与钢笔速写：两种最适合商业评论的画风对比",
        hoursAgo: 40,
        style1: "FB-031",
        layout: "SC-020",
        imgs: ["/images/individual/FB/FB-031.webp", "/images/A_001-016.webp", "/images/B_036-048.webp"],
        md: `# 水彩淡彩与钢笔速写：两种最适合商业评论的画风对比\n\n商业分析文章既需要理性锐度，又不能显得冰冷生硬。钢笔速写提供结构骨架，水彩淡彩注入人文柔和感。\n\n## 一、钢笔速写适合拆解复杂商业模型\n\n干净利落的墨线能清晰勾勒飞轮、漏斗与矩阵边界。\n\n## 二、淡彩晕染适合人物访谈与行业特写\n\n柔和的冷暖过渡能让深度人物报道更具杂志扉页质感。`
      },
      {
        title: "为什么好标题需要一张「不剧透但勾人」的宽幅封面？",
        hoursAgo: 49,
        style1: "FA-013",
        layout: "SC-023",
        imgs: ["/images/poster-demo-autumn-equinox.webp"],
        md: `# 为什么好标题需要一张「不剧透但勾人」的宽幅封面？\n\n2.35:1 的电影感首图封面，决定的不是把标题抄一遍，而是制造一个恰到好处的视觉悬念。\n\n## 一、避免封面文字与文章标题逐字重复\n\n用核心意象隐喻主题，让画面与标题形成互补而非复读。\n\n## 二、注意移动端裁剪安全区\n\n主体居中偏黄金分割位，即使在列表缩略成方形也能保持完整构图。`
      },
      {
        title: "知识博主的色彩账本：三组永不翻车的纸本配色方案",
        hoursAgo: 58,
        style1: "FA-003",
        layout: "IG-005",
        imgs: ["/images/layouts/infographics/IG-005.webp", "/images/H_217-232.webp"],
        md: `# 知识博主的色彩账本：三组永不翻车的纸本配色方案\n\n配色翻车90%是因为同一张图里出现了三种以上高纯度竞争色。学会做减法，画面质感立刻提升一个档次。\n\n## 一、暖宣纸 + 焦茶墨 + 朱砂点睛\n\n最适合人文、效率与方法论专栏，沉稳耐读且极具辨识度。\n\n## 二、米白纸 + 群青灰 + 赭石暖调\n\n适合科技趋势、产品拆解与深度书评，清透而不失温度。`
      },
      {
        title: "把复杂系统讲给外行听：视觉隐喻的四个日常来源",
        hoursAgo: 68,
        style1: "FA-013",
        layout: "IG-003",
        imgs: [],
        md: `# 把复杂系统讲给外行听：视觉隐喻的四个日常来源\n\n解释分布式系统、经济学模型或心理学效应时，直接画术语框图往往让人望而生畏；换成厨房、邮局、园艺或车站隐喻则一秒秒懂。\n\n## 一、用厨房备餐解释并发与流水线\n\n单厨师切菜炒菜与多工位协作，天然对应串行阻塞与异步队列。\n\n## 二、用修剪枝叶解释信息降噪\n\n减去旁逸斜出的枝蔓，主干才能把养分送到果实。`
      },
      {
        title: "手账感排版指南：网格、胶带与手写批注的分寸感",
        hoursAgo: 79,
        style1: "FB-031",
        layout: "SC-006",
        imgs: ["/images/layouts/social-cards/SC-006.webp", "/images/A_001-016.webp"],
        md: `# 手账感排版指南：网格、胶带与手写批注的分寸感\n\n手账风深受读者喜爱，是因为它保留了真人思考的痕迹：圈画重点、页边批注与纸张拼贴。\n\n## 一、批注只加在真正反直觉的句子旁\n\n如果每句话都画波浪线，等于整页都没有重点。\n\n## 二、保持呼吸感对齐基准线\n\n看似随性的手绘卡片，底层依然遵循清晰的左右边距与段落节奏。`
      }
    ];

    return seeds.map((s, idx) => {
      const ts = now - s.hoursAgo * hour;
      const blocks = E.parseArticleReadonlyBlocks(s.md);
      const h2Indices = blocks.filter((b) => b.kind === "h2").map((b) => b.idx);
      const cards = [
        {
          id: `seed_card_${idx}_cov`,
          role: "cover",
          title: `文章封面 · ${s.title.slice(0, 14)}`,
          afterBlockIdx: -1,
          ratio: "2.35:1",
          prompt: `【文章封面 · 2.35:1】围绕主题《${s.title}》，采用温暖手绘宣纸墨线与朱砂点睛风格，构图开阔留白，突出核心视觉隐喻。`,
          promptCustomized: false,
          imageUrl: s.imgs[0] || "",
          sampleImg: "/images/poster-demo-autumn-equinox.webp",
          status: s.imgs[0] ? "done" : "idle"
        },
        ...h2Indices.map((bIdx, cIdx) => {
          const blk = blocks[bIdx];
          const img = s.imgs[cIdx + 1] || "";
          return {
            id: `seed_card_${idx}_inl_${cIdx}`,
            role: "inline",
            title: `插图 ${cIdx + 1} · ${(blk?.text || "章节配图").slice(0, 14)}`,
            afterBlockIdx: bIdx,
            ratio: "4:3",
            prompt: `【正文插图 · 4:3】配合章节「${blk?.text || ""}」，细腻水彩手绘纸本肌理，画面叙事清晰克制，与封面保持同一画风。`,
            promptCustomized: false,
            imageUrl: img,
            sampleImg: "/images/graphic-text-mode-demo.webp",
            status: img ? "done" : "idle"
          };
        })
      ];

      return {
        id: `art_seed_${String(idx + 1).padStart(2, "0")}`,
        articleTitle: s.title,
        markdown: s.md,
        cards,
        status: "ready",
        createdAtMs: ts,
        updatedAtMs: ts,
        timeLabel: formatArticleTimeLabel(ts),
        linkedTabId: null,
        linkedPlanNodeId: null,
        style1: s.style1,
        layout: s.layout,
        runCount: s.imgs.length ? 1 : 0
      };
    });
  }

  function ensureMyArticlesInitialized() {
    if (!Array.isArray(CS.myArticles)) {
      CS.myArticles = isExplicitDemoMode() ? createSeededMyArticles() : [];
      writeJsonStorage(MY_ARTICLES_STORAGE_KEY, CS.myArticles);
    }
  }

  function persistMyArticles() {
    ensureMyArticlesInitialized();
    writeJsonStorage(MY_ARTICLES_STORAGE_KEY, CS.myArticles);
    if (_articlesCloudConflict) {
      // Keep entries omitted from the hydrated workspace; merge later edits
      // without deleting the offline versions saved before rehydration.
      const existing = readJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, null);
      const byId = new Map((existing?.articles || []).map(a => [a.id, a]));
      (CS.myArticles || []).forEach((a) => {
        if (a && byId.has(a.id)) byId.set(a.id, JSON.parse(JSON.stringify(a)));
      });
      writeJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, {
        createdAt: Date.now(), articles: [...byId.values()],
        activeId: CS.activeArticleId || existing?.activeId || ""
      });
    }
    scheduleCloudArticlesSync();
  }

  function isArticleGenerating(art) {
    if (!art) return false;
    if (art.status === "generating") return true;
    return Array.isArray(art.cards) && art.cards.some((c) => c.status === "generating");
  }

  function getSortedMyArticles() {
    ensureMyArticlesInitialized();
    return [...CS.myArticles].sort((a, b) => {
      const genA = isArticleGenerating(a) ? 1 : 0;
      const genB = isArticleGenerating(b) ? 1 : 0;
      if (genA !== genB) return genB - genA;
      return (Number(b.updatedAtMs) || 0) - (Number(a.updatedAtMs) || 0);
    });
  }

  function syncPlanNodeToMyArticles(planNode) {
    // One-time extraction of legacy article nodes. Existing documents always win;
    // subsequent canvas changes cannot overwrite them or create extra articles.
    if (!planNode || planNode.type !== "article_plan") return null;
    ensureMyArticlesInitialized();
    const data = planNode.data || {};
    let article = CS.myArticles.find(a => a.id === data.articleId || a.linkedPlanNodeId === planNode.id);
    if (!article) {
      article = { ...JSON.parse(JSON.stringify(data)), id: data.articleId || E.uid("art"),
        createdAtMs: Date.now(), updatedAtMs: Date.now() };
      CS.myArticles.unshift(article);
      data.articleId = article.id;
      persistMyArticles();
    }
    data.articleId = article.id;
    delete article.linkedPlanNodeId;
    delete article.linkedTabId;
    delete article.sourceControlId;
    return article;
  }

  function syncAllTabsArticlesIntoStore() {
    ensureMyArticlesInitialized();
    // Sync non-active tabs first, then active canvas graph so active tab takes precedence if needed
    for (const t of CS.tabs || []) {
      if (t.id === CS.activeTabId) continue;
      const g = t.graph;
      if (!g || !Array.isArray(g.nodes)) continue;
      for (const n of g.nodes) {
        if (n.type === "article_plan") {
          syncPlanNodeToMyArticles(n, { tabId: t.id, bumpTime: false, hostGraph: g });
        }
      }
    }
    for (const n of CS.graph?.nodes || []) {
      if (n.type === "article_plan") {
        syncPlanNodeToMyArticles(n, { tabId: CS.activeTabId, bumpTime: false, hostGraph: CS.graph });
      }
    }
  }

  function resolveArticleTarget(idOrNode) {
    ensureMyArticlesInitialized();
    if (!idOrNode) return null;
    let article = null;
    if (typeof idOrNode === "object") {
      const node = idOrNode.planNode || idOrNode;
      const key = idOrNode.art?.id || node._articleRef?.id || node.data?.articleId || node.id;
      article = CS.myArticles.find(a => a.id === key) || node._articleRef || null;
      if (!article && node.type === "article_plan") article = syncPlanNodeToMyArticles(node);
    } else {
      article = CS.myArticles.find(a => a.id === String(idOrNode) || a.linkedPlanNodeId === String(idOrNode));
    }
    if (!article) return null;
    // Rendering adapter only; it is never added to or executed by a graph.
    const planNode = { id: article.id, type: "article_plan", _isVirtualArticle: true,
      _articleRef: article, data: article };
    return { art: article, planNode, hostTab: null, isActiveCanvas: false };
  }

  function commitArticleTargetChanges(target, { bumpTime = false } = {}) {
    if (!target?.art) return;
    if (bumpTime) {
      target.art.updatedAtMs = Date.now();
      target.art.timeLabel = formatArticleTimeLabel(target.art.updatedAtMs);
    }
    persistMyArticles();
  }

  function publishArticleToForum(targetOrId) {
    const target = resolveArticleTarget(targetOrId);
    if (!target || !target.planNode) {
      toast("暂无可发布的文章");
      return;
    }
    const pd = target.planNode.data || {};
    const orderedCards = sortPlanCardsInDocOrder(pd.cards || []);
    const readyCards = orderedCards.filter((c) => c.imageUrl);
    const hostGraph = target.isActiveCanvas ? CS.graph : target.hostTab?.graph || null;
    const ctrl =
      hostGraph && pd.sourceControlId
        ? (hostGraph.nodes || []).find((n) => n.id === pd.sourceControlId && n.type === "output_control")
        : null;
    const rec = ctrl && hostGraph ? E.resolveControlRecipe(hostGraph, ctrl, Catalog) : null;

    const rawMd = String(pd.markdown || "").trim();
    const cleanBody = rawMd.replace(/^#\s+.+\r?\n+/, "").trim() || rawMd;

    S.goToForumCompose({
      category: "experience",
      topicTitle: pd.articleTitle || target.art?.articleTitle || "文章配图专栏分享",
      topicBody: cleanBody,
      topicImages: readyCards.slice(0, 4).map((c, idx) => ({
        url: c.imageUrl,
        tag: c.role === "cover" ? "封面" : `插图${idx + 1}`
      })),
      images: readyCards.map((c) => c.imageUrl),
      style1: rec?.style1Id || target.art?.style1 || "",
      layout: rec?.layoutId || target.art?.layout || "",
      mode: "article-illust"
    });
  }

  function ensureArticlePlanNodeForControl(ctrlNode, { forceRebuild = false } = {}) {
    if (!ctrlNode || ctrlNode.type !== "output_control") return { node: null, createdNew: false };
    const rec = E.resolveControlRecipe(CS.graph, ctrlNode, Catalog);
    const mdText = rec.articleSource || E.DEFAULT_STARTER_ARTICLE_MD;
    const built = E.buildArticlePlanData(mdText, ctrlNode, CS.graph, Catalog);

    // Clean up any direct output_display nodes attached to this control when operating in article-illust mode
    const directDisps = getDownstreamDisplayNodes(ctrlNode.id);
    for (const oldDisp of directDisps) {
      removeOrphanedDisplayNode(oldDisp, ctrlNode.id);
    }

    let planNode = getDownstreamArticlePlanNode(ctrlNode);
    if (!planNode) {
      planNode = E.makeArticlePlanNode(
        snapVal(ctrlNode.x + (ctrlNode.w || 344) + 96),
        snapVal(Math.max(48, ctrlNode.y - 12)),
        {
          status: "ready",
          sourceControlId: ctrlNode.id,
          articleTitle: built.articleTitle,
          markdown: built.markdown,
          cards: built.cards,
          updatedAt: "已生成方案"
        }
      );
      CS.graph.nodes.push(planNode);
      ensureEdge(ctrlNode.id, planNode.id);
      syncArticlePlanDisplayNodes(planNode);
      const art = syncPlanNodeToMyArticles(planNode, { tabId: CS.activeTabId, bumpTime: true, hostGraph: CS.graph });
      if (art) CS.activeArticleId = art.id;
      return { node: planNode, createdNew: true };
    }

    planNode.data.sourceControlId = ctrlNode.id;

    let didRebuild = false;
    if (
      forceRebuild ||
      planNode.data.markdown !== built.markdown ||
      !Array.isArray(planNode.data.cards) ||
      !planNode.data.cards.length
    ) {
      planNode.data.articleTitle = built.articleTitle;
      planNode.data.markdown = built.markdown;
      planNode.data.cards = built.cards;
      planNode.data.updatedAt = "已更新配图方案";
      didRebuild = true;
    } else {
      // Same markdown: preserve user-reordered positions, custom prompts, added/deleted cards, and generated images,
      // while refreshing uncustomized card prompts & ratios if upstream style or ratio changed!
      const freshByRoleIdx = {
        cover: built.cards.find((c) => c.role === "cover"),
        inlines: built.cards.filter((c) => c.role !== "cover")
      };
      let inlCounter = 0;
      for (const existingCard of planNode.data.cards) {
        if (!existingCard.promptCustomized) {
          if (existingCard.role === "cover" && freshByRoleIdx.cover) {
            existingCard.ratio = ctrlNode.data.coverRatio || existingCard.ratio || "2.35:1";
            existingCard.prompt = freshByRoleIdx.cover.prompt;
          } else if (existingCard.role !== "cover") {
            existingCard.ratio = ctrlNode.data.inlineRatio || existingCard.ratio || "4:3";
            const matchedFresh = freshByRoleIdx.inlines[inlCounter] || null;
            if (matchedFresh) existingCard.prompt = matchedFresh.prompt;
            inlCounter += 1;
          }
        }
      }
      planNode.data.articleTitle = built.articleTitle;
    }

    syncArticlePlanDisplayNodes(planNode);
    syncPlanNodeToMyArticles(planNode, { tabId: CS.activeTabId, bumpTime: didRebuild, hostGraph: CS.graph });
    return { node: planNode, createdNew: false };
  }

  function syncAllDownstreamArticlePlans({ forceRebuild = false } = {}) {
    const artCtrls = CS.graph.nodes.filter(
      (n) => n.type === "output_control" && n.data && n.data.mode === "article-illust"
    );
    for (const ctrl of artCtrls) {
      if (getDownstreamArticlePlanNode(ctrl)) {
        ensureArticlePlanNodeForControl(ctrl, { forceRebuild });
      }
    }
    const allPlans = CS.graph.nodes.filter((n) => n.type === "article_plan");
    for (const pn of allPlans) {
      syncArticlePlanDisplayNodes(pn);
      syncPlanNodeToMyArticles(pn, { tabId: CS.activeTabId, bumpTime: false, hostGraph: CS.graph });
    }
  }

  function openMyArticlesPage({ preferredPlanNodeId = null, preferredArticleId = null, subView = "editor", renderNow = true } = {}) {
    flushUnifiedArticleEditor();
    syncAllTabsArticlesIntoStore();

    let chosenArt = null;

    if (preferredArticleId) {
      const t = resolveArticleTarget(preferredArticleId);
      chosenArt = t?.art || (CS.myArticles || []).find((a) => a.id === preferredArticleId) || null;
    } else if (preferredPlanNodeId) {
      const liveNode = getNodeById(preferredPlanNodeId);
      if (liveNode && liveNode.type === "article_plan") {
        const ctrl = resolvePlanSourceControl(liveNode);
        if (ctrl) ensureArticlePlanNodeForControl(ctrl, { forceRebuild: false });
        chosenArt = syncPlanNodeToMyArticles(liveNode, { tabId: CS.activeTabId, bumpTime: false, hostGraph: CS.graph });
      } else {
        const t = resolveArticleTarget(preferredPlanNodeId);
        chosenArt = t?.art || null;
      }
    } else {
      const activeGeneratingPlan = CS.graph.nodes.find(
        (n) => n.type === "article_plan" && isArticleGenerating(n.data)
      );
      if (activeGeneratingPlan) {
        chosenArt = syncPlanNodeToMyArticles(activeGeneratingPlan, {
          tabId: CS.activeTabId,
          bumpTime: false,
          hostGraph: CS.graph
        });
      }
      if (!chosenArt) {
        const sorted = getSortedMyArticles();
        const anyGenerating = sorted.find((a) => isArticleGenerating(a));
        chosenArt = anyGenerating || sorted[0] || null;
      }
    }

    CS.previewTab = "article";
    CS.articlePreviewMode = "desktop";
    CS.stageView = "preview";

    if (subView === "all-list") {
      CS.articleSubView = "all-list";
      try {
        window.history.replaceState(null, "", `?view=articles-all&page=${CS.articleListPage || 1}`);
      } catch (_) {}
      if (renderNow) renderTopAndBottomDocks();
      return;
    }

    const targetId = chosenArt ? chosenArt.id : null;
    try {
      if (window.location.search.includes("view=articles-all")) {
        window.history.replaceState(null, "", window.location.pathname);
      }
    } catch (_) {}

    // Route all article entry views through the single unified editor.
    openUnifiedArticleEditor(targetId, { createNew: !chosenArt, renderNow: false });

    if (renderNow) renderTopAndBottomDocks();
  }

  function openArticlePlanWidePage(planNodeId = null) {
    if (planNodeId) {
      openMyArticlesPage({ preferredPlanNodeId: planNodeId, subView: "detail" });
    } else {
      openMyArticlesPage({ subView: "detail" });
    }
  }

  function switchOutputControlMode(ctrlNode, nextMode) {
    if (!ctrlNode || ctrlNode.type !== "output_control") return;
    pushUndo();
    const cd = ctrlNode.data;
    const prevMode = cd.mode;
    const cleanNext = nextMode === "article-cover" ? "article-illust" : nextMode;
    cd.mode = cleanNext;
    const defRatio = E.DEFAULT_MODE_RATIOS[cleanNext];
    if (defRatio) cd.ratio = defRatio;
    if (cleanNext === "series" && (!cd.count || cd.count <= 1)) cd.count = 4;
    if (prevMode === "series" && cleanNext !== "series" && (!cd.count || cd.count > 30)) cd.count = 1;

    if (cleanNext === "article-illust") {
      CS.previewTab = "article";
      fullRenderCanvas();
      persistOpenTabs();
      return;
    }

    // Switching away from article-illust: remove ungenerated article_plan node if present to keep canvas clean
    if (prevMode === "article-illust" && cleanNext !== "article-illust") {
      const oldPlan = getDownstreamArticlePlanNode(ctrlNode);
      if (oldPlan && !(oldPlan.data?.cards || []).some((c) => c.imageUrl)) {
        for (const d of getDownstreamDisplayNodes(oldPlan.id)) {
          removeOrphanedDisplayNode(d, oldPlan.id);
        }
        CS.graph.nodes = CS.graph.nodes.filter((n) => n.id !== oldPlan.id);
        CS.graph.edges = CS.graph.edges.filter((e) => e.from !== oldPlan.id && e.to !== oldPlan.id);
      }
    }

    if (cleanNext === "series") {
      CS.previewTab = "series";
    }

    fullRenderCanvas();
    persistOpenTabs();
  }

  function buildExecutionPlanForControl(ctrlNode) {
    const cd = ctrlNode.data || {};
    const rec = E.resolveControlRecipe(CS.graph, ctrlNode, Catalog);
    const mode = cd.mode === "xhs-batch" ? "series" : cd.mode || "graphic-text";

    function attachRecipeSnapshots(specsList) {
      if (!Array.isArray(specsList)) return;
      const rawUserSubject = String(rec.combinedText || rec.userNoteText || "").trim();
      specsList.forEach((sp) => {
        if (!sp.recipeSnapshot) {
          const s1 = sp.style1 || rec.style1Id || "";
          const s2 = rec.style2Id || "";
          const lay = sp.layout || rec.layoutId || "";
          const s1Res = s1 && Catalog?.resourceMap ? (Catalog.resourceMap.get(s1) || rec.style1Res) : rec.style1Res;
          const s2Res = s2 && Catalog?.resourceMap ? (Catalog.resourceMap.get(s2) || rec.style2Res) : rec.style2Res;
          const layRes = lay && Catalog?.resourceMap ? (Catalog.resourceMap.get(lay) || rec.layoutRes) : rec.layoutRes;
          let spSubj = "";
          if (sp.subject) {
            spSubj = String(sp.subject).trim();
          } else if (rawUserSubject) {
            spSubj = rawUserSubject;
          } else if (sp.theme && sp.theme !== "温暖手绘编辑风插画创作") {
            spSubj = String(sp.theme).trim();
          }
          sp.recipeSnapshot = {
            style1: s1,
            style1Name: s1Res?.name || s1Res?.title || "",
            style2: s2,
            style2Name: s2Res?.name || s2Res?.title || "",
            layout: lay,
            layoutName: layRes?.name || layRes?.title || "",
            subject: spSubj
          };
          if (!sp.subject && spSubj) {
            sp.subject = spSubj;
          }
        } else if (!sp.recipeSnapshot.subject) {
          let spSubj = "";
          if (sp.subject) {
            spSubj = String(sp.subject).trim();
          } else if (rawUserSubject) {
            spSubj = rawUserSubject;
          } else if (sp.theme && sp.theme !== "温暖手绘编辑风插画创作") {
            spSubj = String(sp.theme).trim();
          }
          if (spSubj) {
            sp.recipeSnapshot.subject = spSubj;
            if (!sp.subject) sp.subject = spSubj;
          }
        }
      });
    }

    if (mode === "article-illust") {
      const mdText =
        rec.articleSource ||
        "# 视觉笔记创作指南\n\n导语：用清晰的结构与手绘温度表达复杂观点。\n\n## 一、建立视觉层级\n\n## 二、统一全篇色彩与留白";
      // userNoteText here is the whole text the user attached or typed, so
      // appending it verbatim to every slot repeated the entire article in each
      // image prompt.  Keep only a short steer.
      const noteSteer = String(rec.userNoteText || "").trim();
      const shortNote = noteSteer.length > 120 ? noteSteer.slice(0, 120) + "…" : noteSteer;
      const slots = E.buildArticleSlotsSpec(mdText, {
        coverRatio: cd.coverRatio || "2.35:1",
        inlineRatio: cd.inlineRatio || "4:3",
        includeCover: cd.includeCover !== false
      }).map((s) =>
        rec.attachedFileContent && shortNote
          ? { ...s, theme: `${s.theme}（补充要求：${shortNote}）` }
          : s
      );
      const planRes = {
        kind: "article",
        markdown: mdText,
        specs: slots
      };
      attachRecipeSnapshots(planRes.specs);
      return planRes;
    }

    if (rec.loopNode) {
      const loopIters = E.resolveLoopIterations(CS.graph, rec.loopNode, rec, Catalog);
      if (!loopIters.length) {
        return {
          kind: "loop-empty",
          loopNodeId: rec.loopNode.id,
          loopCount: 0,
          markdown: rec.combinedText || "",
          specs: []
        };
      }
      const perIterCount = Math.min(50, Math.max(1, Math.round(Number(cd.count) || 1)));
      const loopSpecs = [];
      for (const iter of loopIters) {
        for (let sub = 0; sub < perIterCount; sub++) {
          if (loopSpecs.length >= 200) break;
          loopSpecs.push({
            fromLoop: true,
            loopNodeId: rec.loopNode.id,
            loopStepIndex: iter.index,
            loopTotalSteps: loopIters.length,
            slotKey: `loop_${iter.index}_${sub}`,
            role: mode === "article-cover" ? "cover" : "image",
            title: perIterCount > 1 ? `${iter.title} (${sub + 1}/${perIterCount})` : iter.title,
            anchorHeading: "",
            style1: iter.style1 || "",
            layout: iter.layout || rec.layoutId || "",
            assetItems: Array.isArray(iter.assetItems) ? iter.assetItems : null,
            mode,
            ratio: cd.ratio || "3:4",
            theme: iter.theme,
            sampleImg: iter.sampleImg || ""
          });
        }
      }
      const loopPlan = {
        kind: "loop",
        loopNodeId: rec.loopNode.id,
        loopCount: loopIters.length,
        markdown: rec.combinedText || "",
        specs: loopSpecs
      };
      attachRecipeSnapshots(loopPlan.specs);
      return loopPlan;
    }

    // Direct Fission -> Output Control (if user connects 选题裂变 straight to 输出控制 without 循环批量)
    if (rec.fissionNode && Array.isArray(rec.fissionNode.data?.generatedItems) && rec.fissionNode.data.generatedItems.length > 0) {
      const fItems = rec.fissionNode.data.generatedItems.slice(0, 200);
      const fisPlan = {
        kind: "loop",
        loopNodeId: "",
        loopCount: fItems.length,
        markdown: rec.combinedText || "",
        specs: fItems.map((line, idx) => ({
          fromLoop: true,
          slotKey: `fis_${idx}`,
          role: mode === "article-cover" ? "cover" : "image",
          title: `裂变 #${idx + 1} · ${String(line).slice(0, 18)}`,
          anchorHeading: "",
          style1: "",
          layout: rec.layoutId || "",
          assetItems: null,
          mode,
          ratio: cd.ratio || "3:4",
          theme: String(line),
          sampleImg: ""
        }))
      };
      attachRecipeSnapshots(fisPlan.specs);
      return fisPlan;
    }

    if (mode === "series") {
      const count = Math.min(200, Math.max(1, Math.round(Number(cd.count) || 4)));
      const topic = rec.combinedText || "高效手绘视觉笔记创作方法论";
      const slides = E.buildSeriesSlidesSpec(topic, count, cd.ratio || "3:4");
      const serPlan = {
        kind: "series",
        markdown: topic,
        specs: slides.map((s) => ({
          ...s,
          layout: cd.mixLayouts !== false ? s.layout : rec.layoutId || ""
        }))
      };
      attachRecipeSnapshots(serPlan.specs);
      return serPlan;
    }

    const count = Math.min(200, Math.max(1, Math.round(Number(cd.count) || 1)));
    const specs = Array.from({ length: count }, (_, idx) => {
      const slotKey = `single_${idx}`;
      const baseTheme = rec.combinedText || "温暖手绘编辑风插画创作";
      return {
        slotKey,
        role: mode === "article-cover" ? "cover" : "image",
        title: count > 1 ? `方案 #${idx + 1}` : E.OUTPUT_MODES.find((m) => m.id === mode)?.label || "生成结果",
        anchorHeading: "",
        layout: rec.layoutId || "",
        mode,
        ratio: cd.ratio || "3:4",
        theme: baseTheme,
        sampleImg: ""
      };
    });
    const defaultPlan = {
      kind: count > 1 ? "multi" : "single",
      markdown: rec.combinedText || "",
      specs
    };
    attachRecipeSnapshots(defaultPlan.specs);
    return defaultPlan;
  }

  function checkExclusiveGateForControl(ctrlNode) {
    const rec = E.resolveControlRecipe(CS.graph, ctrlNode, Catalog);
    const rMap = Catalog.resourceMap || new Map();
    const extraLoopRes = [];
    if (rec.loopNode && rec.loopNode.data) {
      const ld = rec.loopNode.data;
      if (ld.loopMode === "styles" && Array.isArray(ld.styleIds)) {
        ld.styleIds.forEach((id) => {
          const r = rMap.get(id);
          if (r) extraLoopRes.push(r);
        });
      } else if (ld.loopMode === "layouts" && Array.isArray(ld.layoutIds)) {
        ld.layoutIds.forEach((id) => {
          const r = rMap.get(id);
          if (r) extraLoopRes.push(r);
        });
      }
    }
    const itemsToCheck = [rec.style1Res, rec.style2Res, rec.layoutRes, ...extraLoopRes].filter(Boolean);
    for (const res of itemsToCheck) {
      if ((res.sourceType === "exclusive" || res.tier === "pro_credit") && !App.state.loggedIn) {
        S.openLoginModal(`参数中使用了独占编号 ${res.id}《${res.name}》，登录即可使用！`, () => fullRenderCanvas());
        return false;
      }
      if (res.tier === "pro_credit" && !S.isUnlocked(res.id, res)) {
        const ok = S.unlockWithCredits(res.id, res.unlockCost || 10, `解锁编号 ${res.id}《${res.name}》`);
        if (!ok) return false;
      }
    }
    return true;
  }

  function cancelledTaskWaitError() {
    const error = new Error("已停止本地等待；已提交的任务可能仍在云端执行");
    error.name = "AbortError";
    return error;
  }

  // The poll delay itself must be abortable. Otherwise Stop is stuck waiting
  // for the next 2.2-second interval even though the HTTP signal was aborted.
  function waitForCloudPollInterval(ms, signal) {
    if (signal?.aborted) return Promise.reject(cancelledTaskWaitError());
    return new Promise((resolve, reject) => {
      let timer = null;
      const onAbort = () => {
        clearTimeout(timer);
        if (signal) signal.removeEventListener("abort", onAbort);
        reject(cancelledTaskWaitError());
      };
      timer = setTimeout(() => {
        if (signal) signal.removeEventListener("abort", onAbort);
        resolve();
      }, ms);
      if (signal) {
        signal.addEventListener("abort", onAbort, { once: true });
        if (signal.aborted) onAbort();
      }
    });
  }

  async function pollCloudTask(taskId = "", { requestId = "", immediate = false, signal } = {}) {
    if (!taskId && !requestId) throw new Error("缺少 taskId 或 requestId");
    for (let attempt = 0; attempt < 45; attempt++) {
      if (signal?.aborted) throw cancelledTaskWaitError();
      if (!(immediate && attempt === 0)) await waitForCloudPollInterval(2200, signal);
      const params = new URLSearchParams();
      if (taskId) params.set("id", String(taskId));
      if (requestId) params.set("requestId", requestId);
      const resp = await fetch(`/api/studio/tasks?${params.toString()}`, { credentials: "include", signal });
      if (!resp.ok) continue;
      const d = await resp.json();
      if (d.status === "success" && d.images && d.images.length > 0) return d.images;
      if (["error", "failed", "refunded", "cancelled"].includes(d.status)) {
        const err = new Error(d.message || d.error || `云端生图${d.status}`);
        err.terminal = true;
        throw err;
      }
    }
    throw new Error("等待时间较长，生成结果出来后会出现在生图历史里；如果最终没有生成，额度或积分会自动退还。");
  }

  function applyDurableTaskResult(task, images, errorMessage = "") {
    const id = task.genId || task.id || "";
    const requestId = task.requestId || task.clientRequestId || "";
    const history = Array.isArray(CS.generationHistory) ? CS.generationHistory : [];
    let entry = history.find((item) => (id && item.id === id) || (requestId && item.requestId === requestId));
    const taskSubject = task.subject || task.recipeSnapshot?.subject || "";
    if (!entry && !errorMessage) {
      entry = {
        id: id || E.uid("hist"),
        requestId: requestId,
        createdAt: new Date().toISOString(),
        timeShort: "",
        tabTitle: task.tabTitle || "云端生图",
        subject: taskSubject,
        ctrlId: "",
        dispId: "",
        mode: task.mode || "generation",
        creationSource: task.creationSource || "",
        modeLabel: task.modeLabel || "云端直出",
        kind: task.kind || "single",
        recipeSummary: task.recipeSummary || "",
        prompt: task.prompt || "",
        markdown: "",
        items: []
      };
    }
    if (!entry) return;
    entry.id = id || entry.id;
    entry.requestId = requestId || entry.requestId || "";
    if (taskSubject && !entry.subject) entry.subject = taskSubject;
    if (task.creationSource) entry.creationSource = task.creationSource;
    entry.taskId = "";
    entry.status = errorMessage ? "error" : "success";
    entry.engine = "live";
    entry.demoMode = false;
    entry.error = errorMessage || "";
    if (!errorMessage) {
      entry.items = images.map((url, idx) => ({
        id: `${entry.id}_${idx}`,
        genId: id || "",
        requestId,
        title: task.tabTitle || `云端成图 ${idx + 1}`,
        subject: taskSubject || "",
        ratio: task.ratio || "3:4",
        prompt: task.prompt || entry.prompt || "",
        imageUrl: url,
        generationMode: "live",
        demoMode: false,
        recipeSnapshot: task.recipeSnapshot || entry.recipeSnapshot || null
      }));
    }
    CS.generationHistory = upsertHistoryEntry(history, entry, { isServer: false });
    writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
  }

  async function resumePendingCloudTasks() {
    const resumeEpoch = cacheScopeEpoch;
    const resumeScope = activeCacheScope;
    const resumeController = typeof AbortController !== "undefined" ? new AbortController() : null;
    if (resumeController) _generationControllers.add(resumeController);
    const resumedTaskIds = new Set();
    const durablePending = Array.isArray(CS.pendingTasks) ? CS.pendingTasks.slice() : [];

    await Promise.allSettled(
      durablePending.map(async (task) => {
        const taskId = String(task.taskId || "").trim();
        const requestId = String(task.requestId || task.clientRequestId || "").trim();
        if (!taskId && !requestId) return;
        try {
          const images = await pollCloudTask(taskId, {
            requestId,
            immediate: true,
            signal: resumeController ? resumeController.signal : undefined
          });
          if (isStaleScope(resumeEpoch, resumeScope)) return;
          applyDurableTaskResult(task, images);
          if (taskId) resumedTaskIds.add(taskId);
          if (requestId) resumedTaskIds.add(`request:${requestId}`);
          CS.pendingTasks = CS.pendingTasks.filter(
            (item) => item !== task && item.genId !== task.genId && item.requestId !== requestId
          );
        } catch (err) {
          if (isStaleScope(resumeEpoch, resumeScope)) return;
          if (String(err && err.name) !== "AbortError") {
            const entry = (CS.generationHistory || []).find(
              (item) => (task.genId && item.id === task.genId) || (requestId && item.requestId === requestId)
            );
            if (entry) {
              entry.status = "error";
              entry.error = err.message || String(err);
              writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
            }
          }
        }
      })
    );
    if (!isStaleScope(resumeEpoch, resumeScope) && CS.stageView === "history" && DOM.historyStage) {
      renderHistoryStage();
    }
    const pendingArticles = [];
    for (const art of Array.isArray(CS.myArticles) ? CS.myArticles : []) {
      for (const card of Array.isArray(art.cards) ? art.cards : []) {
        if (card && card.status === "generating" && (card.taskId || card.requestId)) pendingArticles.push({ art, card });
      }
    }

    const resumeArticle = async ({ art, card }) => {
      try {
        const images = await pollCloudTask(card.taskId || "", {
          requestId: card.requestId || "",
          immediate: true,
          signal: resumeController ? resumeController.signal : undefined
        });
        if (resumeEpoch !== cacheScopeEpoch || resumeScope !== activeCacheScope) return;
        card.imageUrl = (images && images[0]) || "";
        card.status = card.imageUrl ? "done" : "error";
        card.generationMode = "live";
        card.demoMode = false;
        card.taskId = "";
        persistMyArticles();
        renderFullPreviewStage();
      } catch (err) {
        if (resumeEpoch !== cacheScopeEpoch || resumeScope !== activeCacheScope) return;
        card.status = "error";
        card.error = err.message || String(err);
        card.taskId = "";
        if (err.terminal) card.requestId = "";
        persistMyArticles();
        renderFullPreviewStage();
      }
    };
    await Promise.allSettled(pendingArticles.map(resumeArticle));

    // Direct output nodes persist the task/spec pair so a refresh can finish
    // the already-submitted request without creating a second charge.
    // An output gallery is a shared node, but each concurrent slot has an
    // independent recoverable request. Never silently drop earlier slots.
    const clearPendingSlot = (data, slotKey) => {
      if (data.pendingTasksBySlot) delete data.pendingTasksBySlot[slotKey];
      const another = Object.values(data.pendingTasksBySlot || {})[0];
      data.pendingTaskId = another?.taskId || "";
      data.pendingRequestId = another?.requestId || "";
    };
    const pendingDisplays = [];
    for (const tab of CS.tabs || []) {
      const graph = tab.id === CS.activeTabId ? CS.graph : tab.graph;
      for (const node of graph?.nodes || []) {
        if (node.type !== "output_display") continue;
        const slots = Object.entries(node.data?.pendingTasksBySlot || {});
        if (slots.length) {
          slots.forEach(([slotKey, pending]) => {
            if (pending?.taskId || pending?.requestId) {
              pendingDisplays.push({
                tab, nodeId: node.id, node, slotKey,
                taskId: pending.taskId || "", requestId: pending.requestId || ""
              });
            }
          });
        } else if (node.data?.pendingTaskId || node.data?.pendingRequestId) {
          pendingDisplays.push({
            tab, nodeId: node.id, node, slotKey: "",
            taskId: node.data.pendingTaskId || "", requestId: node.data.pendingRequestId || ""
          });
        }
      }
    }
    await Promise.allSettled(
      pendingDisplays.map(async ({ tab, nodeId, node: initialNode, taskId, requestId, slotKey }) => {
        try {
          const images = await pollCloudTask(taskId, {
            requestId,
            immediate: true,
            signal: resumeController ? resumeController.signal : undefined
          });
          if (resumeEpoch !== cacheScopeEpoch || resumeScope !== activeCacheScope) return;
          const currentGraph = tab.id === CS.activeTabId ? CS.graph : tab.graph;
          const targetNode = currentGraph?.nodes?.find((n) => n.id === nodeId) || initialNode;
          const spec = targetNode.data?.pendingSpec?.[requestId] || (taskId ? targetNode.data?.pendingSpec?.[taskId] : null) || initialNode.data?.pendingSpec?.[requestId] || {};

          // Verify batch identity: stale batch responses must not overwrite a newer batch
          if (targetNode.data?.activeBatchId && spec.batchId && targetNode.data.activeBatchId !== spec.batchId) {
            clearPendingSlot(targetNode.data, slotKey || spec.slotKey || requestId);
            if (targetNode.data.pendingRequestIds) delete targetNode.data.pendingRequestIds[spec.slotKey || requestId];
            if (targetNode.data.pendingSpec) {
              delete targetNode.data.pendingSpec[requestId];
              if (taskId) delete targetNode.data.pendingSpec[taskId];
            }
            persistOpenTabs();
            return;
          }

          const item = {
            id: E.uid("outit"),
            batchId: spec.batchId || targetNode.data?.activeBatchId || "",
            requestId,
            taskId: "",
            generationMode: "live",
            demoMode: false,
            slotKey: spec.slotKey || requestId,
            role: spec.role || "image",
            title: spec.title || "图片",
            anchorHeading: spec.anchorHeading || "",
            ratio: spec.ratio || "3:4",
            theme: spec.theme || "",
            subject: spec.subject || spec.recipeSnapshot?.subject || "",
            prompt: spec.prompt || "",
            imageUrl: (images && images[0]) || "",
            recipeSnapshot: spec.recipeSnapshot || null
          };
          if (targetNode.data.kind === "batch_gallery") {
            if (!Array.isArray(targetNode.data.items)) targetNode.data.items = [];
            const existIdx = targetNode.data.items.findIndex(
              (it) => it && ((it.slotKey && it.slotKey === (spec.slotKey || requestId)) || (it.requestId && it.requestId === requestId))
            );
            if (existIdx >= 0) {
              targetNode.data.items[existIdx] = item;
            } else if (Number.isInteger(spec.index) && spec.index >= 0 && spec.index < 200) {
              targetNode.data.items[spec.index] = item;
            } else {
              targetNode.data.items.push(item);
            }
            targetNode.data.status = item.imageUrl ? "done" : "error";
          } else {
            targetNode.data.items = item.imageUrl ? [item] : [];
            targetNode.data.status = item.imageUrl ? "done" : "error";
          }
          clearPendingSlot(targetNode.data, slotKey || spec.slotKey || requestId);
          if (targetNode.data.pendingRequestIds) delete targetNode.data.pendingRequestIds[spec.slotKey || requestId];
          if (targetNode.data.pendingSpec) {
            delete targetNode.data.pendingSpec[requestId];
            if (taskId) delete targetNode.data.pendingSpec[taskId];
          }
          const hasPending = Object.keys(targetNode.data.pendingTasksBySlot || {}).length > 0;
          if (hasPending) targetNode.data.status = "generating";
          const ctrlNode = targetNode.data.sourceNodeId ? currentGraph?.nodes?.find((n) => n.id === targetNode.data.sourceNodeId) : null;
          if (ctrlNode && ctrlNode.data && ctrlNode.data.status === "generating" && !hasPending) {
            ctrlNode.data.status = item.imageUrl ? "done" : "error";
          }
          persistOpenTabs();
          if (tab.id === CS.activeTabId) {
            fullRenderCanvas();
            renderQuickStart();
          }
        } catch (err) {
          if (resumeEpoch !== cacheScopeEpoch || resumeScope !== activeCacheScope) return;
          const currentGraph = tab.id === CS.activeTabId ? CS.graph : tab.graph;
          const targetNode = currentGraph?.nodes?.find((n) => n.id === nodeId) || initialNode;
          const spec = targetNode.data?.pendingSpec?.[requestId] || (taskId ? targetNode.data?.pendingSpec?.[taskId] : null) || initialNode.data?.pendingSpec?.[requestId] || {};

          if (targetNode.data?.activeBatchId && spec.batchId && targetNode.data.activeBatchId !== spec.batchId) {
            clearPendingSlot(targetNode.data, slotKey || spec.slotKey || requestId);
            if (targetNode.data.pendingRequestIds) delete targetNode.data.pendingRequestIds[spec.slotKey || requestId];
            if (targetNode.data.pendingSpec) {
              delete targetNode.data.pendingSpec[requestId];
              if (taskId) delete targetNode.data.pendingSpec[taskId];
            }
            persistOpenTabs();
            return;
          }
          targetNode.data.status = "error";
          targetNode.data.error = err.message || String(err);
          clearPendingSlot(targetNode.data, slotKey || spec.slotKey || requestId);
          if (err.terminal) {
            if (targetNode.data.pendingRequestIds) {
              delete targetNode.data.pendingRequestIds[spec.slotKey || requestId];
            }
          }
          if (targetNode.data.pendingSpec) {
            delete targetNode.data.pendingSpec[requestId];
            if (taskId) delete targetNode.data.pendingSpec[taskId];
          }
          const hasPending = Object.keys(targetNode.data.pendingTasksBySlot || {}).length > 0;
          if (hasPending) targetNode.data.status = "generating";
          const ctrlNode = targetNode.data.sourceNodeId ? currentGraph?.nodes?.find((n) => n.id === targetNode.data.sourceNodeId) : null;
          if (ctrlNode && ctrlNode.data && ctrlNode.data.status === "generating" && !hasPending) {
            ctrlNode.data.status = "error";
          }
          persistOpenTabs();
          if (tab.id === CS.activeTabId) {
            fullRenderCanvas();
            renderQuickStart();
          }
        }
      })
    );
    if (resumeController) _generationControllers.delete(resumeController);
  }

  function formatParamValue(val) {
    if (val === null || val === undefined) return "";
    if (typeof val === "string") return val.trim();
    if (typeof val === "number" || typeof val === "boolean") return String(val);
    if (typeof val === "object") {
      const c = typeof val.code === "string" && val.code.trim() ? val.code.trim() : "";
      if (c) return c;
      const id = typeof val.id === "string" && val.id.trim() ? val.id.trim() : "";
      if (id) return id;
      const name = typeof val.name === "string" && val.name.trim() ? val.name.trim() : "";
      if (name) return name;
      const label = typeof val.label === "string" && val.label.trim() ? val.label.trim() : "";
      if (label) return label;
      const title = typeof val.title === "string" && val.title.trim() ? val.title.trim() : "";
      if (title) return title;
      const value = typeof val.value === "string" && val.value.trim() ? val.value.trim() : "";
      if (value) return value;
      return "";
    }
    return "";
  }

  function formatParamList(val, joiner = ",") {
    if (!val) return "";
    const arr = Array.isArray(val) ? val : [val];
    const cleaned = arr.map(formatParamValue).filter(Boolean);
    return cleaned.join(joiner);
  }

  function normalizeHistoryEntry(rawEntry) {
    if (!rawEntry || typeof rawEntry !== "object") return null;

    const rawItems = Array.isArray(rawEntry.items)
      ? rawEntry.items
      : (Array.isArray(rawEntry.images) ? rawEntry.images : []);

    const items = rawItems.map((it, idx) => {
      if (!it || typeof it !== "object") {
        const u = typeof it === "string" ? it.trim() : "";
        return {
          id: `${rawEntry.id || "item"}_${idx}`,
          genId: (rawEntry.id && String(rawEntry.id).startsWith("gen_")) ? rawEntry.id : "",
          requestId: rawEntry.requestId || rawEntry.request_id || "",
          imageUrl: u,
          ratio: rawEntry.ratio || "3:4",
          title: `成图 #${idx + 1}`,
          prompt: rawEntry.prompt || "",
          generationMode: rawEntry.engine === "live" ? "live" : "demo",
          demoMode: rawEntry.engine !== "live"
        };
      }
      const itGenId = it.genId || (it.id && String(it.id).startsWith("gen_") ? it.id : "");
      return {
        id: it.id || `${rawEntry.id || "item"}_${idx}`,
        genId: itGenId,
        requestId: it.requestId || rawEntry.requestId || rawEntry.request_id || "",
        taskId: it.taskId || "",
        title: it.title || `成图 #${idx + 1}`,
        ratio: it.ratio || rawEntry.ratio || "3:4",
        prompt: it.prompt || rawEntry.prompt || "",
        imageUrl: it.imageUrl || it.url || "",
        generationMode: it.generationMode || (rawEntry.engine === "live" ? "live" : "demo"),
        demoMode: typeof it.demoMode === "boolean" ? it.demoMode : rawEntry.engine !== "live",
        recipeSnapshot: it.recipeSnapshot || null,
        slotKey: it.slotKey || String(idx),
        role: it.role || "image",
        anchorHeading: it.anchorHeading || "",
        theme: it.theme || "",
        subject: it.subject || it.recipeSnapshot?.subject || rawEntry.subject || "",
        articleTitle: it.articleTitle || rawEntry.articleTitle || "",
        isCustomTitle: Boolean(it.isCustomTitle || it.titleSource === "manual"),
        titleSource: it.titleSource || (it.isCustomTitle ? "manual" : "auto"),
        failed: Boolean(it.failed),
        error: it.error || ""
      };
    });

    const isBatch = Boolean(
      rawEntry.kind === "loop" ||
      rawEntry.kind === "multi" ||
      rawEntry.kind === "series" ||
      items.length > 1
    );

    let id = String(rawEntry.id || "").trim();
    let requestId = String(rawEntry.requestId || rawEntry.request_id || "").trim();

    if (!isBatch && items.length === 1) {
      if (items[0].genId && (!id || id.startsWith("hist_"))) {
        id = items[0].genId;
      }
      if (!requestId && items[0].requestId) {
        requestId = items[0].requestId;
      }
    } else if (isBatch) {
      if (!id || (items.length > 1 && items[0]?.genId && id === items[0].genId)) {
        id = E.uid("hist_batch");
      }
    }

    if (!id) {
      id = E.uid("hist");
    }

    let summary = String(rawEntry.recipeSummary || rawEntry.recipe_summary || "")
      .replace(/\[object Object\]/g, "")
      .replace(/\s*·\s*·\s*/g, " · ")
      .replace(/^·\s*|\s*·$/g, "")
      .trim();

    return {
      ...rawEntry,
      id,
      requestId,
      kind: isBatch ? (rawEntry.kind || "multi") : (rawEntry.kind || "single"),
      mode: rawEntry.mode || "graphic-text",
      creationSource: ["quick", "batch", "article", "canvas", "other"].includes(rawEntry.creationSource) ? rawEntry.creationSource : "",
      modeLabel: rawEntry.modeLabel || (isBatch ? `批量生成 · ${items.length} 张` : "生成"),
      tabTitle: rawEntry.tabTitle || "当前工作流",
      subject: rawEntry.subject || (items.length > 0 ? (items[0].subject || items[0].recipeSnapshot?.subject) : "") || "",
      articleTitle: rawEntry.articleTitle || rawEntry.planNode?.data?.articleTitle || "",
      title: rawEntry.title || "",
      isCustomTitle: Boolean(rawEntry.isCustomTitle || rawEntry.titleSource === "manual"),
      titleSource: rawEntry.titleSource || (rawEntry.isCustomTitle ? "manual" : "auto"),
      recipeSummary: summary,
      prompt: typeof rawEntry.prompt === "string" ? rawEntry.prompt : "",
      createdAt: rawEntry.createdAt || rawEntry.created_at || new Date().toISOString(),
      timeShort: rawEntry.timeShort || "",
      engine: rawEntry.engine || (items.some((it) => it.generationMode === "live") ? "live" : "demo"),
      demoMode: typeof rawEntry.demoMode === "boolean" ? rawEntry.demoMode : rawEntry.engine !== "live",
      items,
      status: rawEntry.status || "success"
    };
  }

  function findMatchingHistoryIndex(list, entry) {
    if (!entry) return -1;
    const entryId = String(entry.id || "").trim();
    const entryReqId = String(entry.requestId || "").trim();

    if (entryId) {
      const idx = list.findIndex((h) => h && String(h.id).trim() === entryId);
      if (idx >= 0) return idx;
    }

    if (entryReqId) {
      const idx = list.findIndex((h) => h && String(h.requestId || "").trim() === entryReqId);
      if (idx >= 0) return idx;
    }

    if (entryId && entryId.startsWith("gen_")) {
      const idx = list.findIndex((h) => {
        if (!h || !Array.isArray(h.items) || h.items.length !== 1) return false;
        return h.items[0]?.genId === entryId;
      });
      if (idx >= 0) return idx;
    }

    if (Array.isArray(entry.items) && entry.items.length === 1 && entry.items[0].genId) {
      const gId = entry.items[0].genId;
      const idx = list.findIndex((h) => {
        if (!h || !Array.isArray(h.items) || h.items.length !== 1) return false;
        return h.id === gId || h.items[0]?.genId === gId;
      });
      if (idx >= 0) return idx;
    }

    return -1;
  }

  function upsertHistoryEntry(targetList, incomingEntry, { isServer = false } = {}) {
    const list = Array.isArray(targetList) ? [...targetList] : [];
    const normalized = normalizeHistoryEntry(incomingEntry);
    if (!normalized) return list;

    const existIdx = findMatchingHistoryIndex(list, normalized);

    if (existIdx >= 0) {
      const existing = list[existIdx];
      let merged;
      if (isServer) {
        merged = {
          ...normalized,
          id: normalized.id,
          requestId: normalized.requestId || existing.requestId || "",
          tabTitle: existing.tabTitle && existing.tabTitle !== "当前工作流" && existing.tabTitle !== "生成历史"
            ? existing.tabTitle
            : (normalized.tabTitle || existing.tabTitle),
          subject: existing.subject || normalized.subject || "",
          articleTitle: existing.articleTitle || normalized.articleTitle || "",
          title: (existing.isCustomTitle || existing.titleSource === "manual") ? existing.title : (normalized.title || existing.title || ""),
          isCustomTitle: Boolean(existing.isCustomTitle || normalized.isCustomTitle),
          titleSource: existing.titleSource || normalized.titleSource || "",
          recipeSummary: existing.recipeSummary || normalized.recipeSummary || "",
          // The server's masking decision always wins over stale local history.
          prompt: normalized.promptMasked ? "" : (normalized.prompt || existing.prompt || ""),
          promptMasked: Boolean(normalized.promptMasked),
          markdown: existing.markdown || normalized.markdown || "",
          ctrlId: existing.ctrlId || normalized.ctrlId || "",
          dispId: existing.dispId || normalized.dispId || "",
          recipeId: existing.recipeId || normalized.recipeId || "",
          creationSource: normalized.creationSource || existing.creationSource || "",
          recipeSnapshot: normalized.promptMasked ? null : (normalized.recipeSnapshot || existing.recipeSnapshot || null),
          items: (Array.isArray(normalized.items) && normalized.items.length) ? normalized.items : existing.items
        };
      } else {
        const isExistingServer = existing.engine === "live" || !String(existing.id).startsWith("hist_");
        merged = {
          ...existing,
          ...normalized,
          id: isExistingServer ? existing.id : normalized.id,
          engine: isExistingServer ? existing.engine : normalized.engine,
          status: isExistingServer ? existing.status : normalized.status,
          requestId: existing.requestId || normalized.requestId || "",
          creationSource: normalized.creationSource || existing.creationSource || "",
          subject: normalized.subject || existing.subject || "",
          articleTitle: normalized.articleTitle || existing.articleTitle || "",
          title: (existing.isCustomTitle || existing.titleSource === "manual") ? existing.title : (normalized.title || existing.title || ""),
          isCustomTitle: Boolean(existing.isCustomTitle || normalized.isCustomTitle),
          titleSource: existing.titleSource || normalized.titleSource || ""
        };
      }
      list[existIdx] = merged;
    } else {
      list.unshift(normalized);
    }

    return list;
  }

  function buildRecipeSummaryText(rec, ctrlNode) {
    const parts = [];
    if (rec.loopNode) {
      const lm = E.LOOP_MODES.find((m) => m.id === (rec.loopNode.data?.loopMode || "prompts"));
      const iters = E.resolveLoopIterations(CS.graph, rec.loopNode, rec, Catalog);
      parts.push(`循环:${lm ? lm.label : "批量"}×${iters.length}轮`);
    }
    const s1 = formatParamValue(rec.style1Id);
    const s2 = formatParamValue(rec.style2Id);
    if (rec.fusionToggleOn) {
      parts.push(`融合:${s1 || "未选"}×${s2 || "未选"}`);
    } else if (s1) {
      parts.push(`画风:${s1}`);
    }
    const lay = formatParamValue(rec.layoutId);
    if (lay) parts.push(`图型:${lay}`);
    const cols = formatParamList(rec.colorIds, ",");
    if (cols) parts.push(`主题色:${cols}`);
    const tones = formatParamList(rec.toneIds, ",");
    if (tones) parts.push(`影调:${tones}`);
    const moods = formatParamList(rec.allMoods, ",");
    if (moods) parts.push(`情绪:${moods}`);
    const assetsCount = Array.isArray(rec.assetItems) ? rec.assetItems.length : 0;
    if (assetsCount) parts.push(`图参×${assetsCount}`);
    if (!parts.length) parts.push(`默认自由发挥 · ${ctrlNode?.data?.ratio || "3:4"}`);
    return parts.join(" · ");
  }

  function recordGenerationHistory(ctrlNode, items = [], kind = "single", markdown = "", creationSource = "") {
    ensureGenerationHistoryInitialized();
    if (!ctrlNode || !Array.isArray(items) || !items.length) return;
    const isRecipe = Boolean(ctrlNode.styleIds || ctrlNode.style_ids || (typeof ctrlNode.id === "string" && ctrlNode.id.startsWith("rcp_")));
    const recipeId = isRecipe ? (ctrlNode.id || "") : (ctrlNode.recipeId || "");
    const mode = isRecipe ? (ctrlNode.mode || "graphic-text") : (ctrlNode.data?.mode || "graphic-text");
    const rec = isRecipe ? null : E.resolveControlRecipe(CS.graph, ctrlNode, Catalog);
    const curTab = CS.tabs.find((t) => t.id === CS.activeTabId);
    const now = new Date();
    const timeShort = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const dateFull = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${timeShort}`;
    const modeMeta = E.OUTPUT_MODES.find((m) => m.id === mode);
    const isLoopBatch = kind === "loop";

    let summaryText = "";
    if (isRecipe) {
      const parts = [];
      const sIds = formatParamList(ctrlNode.styleIds || ctrlNode.style_ids, "+");
      if (sIds) parts.push(`画风:${sIds}`);
      const lay = formatParamValue(ctrlNode.layoutId || ctrlNode.layout_id);
      if (lay) parts.push(`图型:${lay}`);
      const cols = formatParamList(ctrlNode.colors, ",");
      if (cols) parts.push(`主题色:${cols}`);
      const tones = formatParamList(ctrlNode.tones, ",");
      if (tones) parts.push(`影调:${tones}`);
      const moods = formatParamList(ctrlNode.moods, ",");
      if (moods) parts.push(`情绪:${moods}`);
      if (!parts.length) parts.push(`做图配方 · ${ctrlNode.ratio || "3:4"}`);
      summaryText = parts.join(" · ");
    } else {
      summaryText = buildRecipeSummaryText(rec, ctrlNode);
    }

    const hasLiveItems = Array.isArray(items) && items.some((it) => it && (it.generationMode === "live" || it.engine === "live"));
    const isLive = isLiveGenerationEnabled() || hasLiveItems;
    const isBatch = Boolean(isLoopBatch || items.length > 1 || kind === "multi" || kind === "series");
    const firstGenId = (Array.isArray(items) && items.find((it) => it && it.genId)?.genId) || "";
    const firstReqId = (Array.isArray(items) && items.find((it) => it && it.requestId)?.requestId) || "";

    const entryId = (!isBatch && firstGenId) ? firstGenId : (isBatch ? E.uid("hist_batch") : E.uid("hist"));

    const cleanSubject =
      (items && items[0]?.subject) ||
      (items && items[0]?.recipeSnapshot?.subject) ||
      (isRecipe
        ? (ctrlNode.subject || "")
        : (rec?.userNoteText || rec?.combinedText || ctrlNode.data?.inlineTheme || ctrlNode.data?.subject || "")) ||
      "";

    const resolvedItems = JSON.parse(JSON.stringify(items || [])).map((it) => {
      const itSubj = it.subject || it.recipeSnapshot?.subject || cleanSubject || "";
      return {
        ...it,
        subject: itSubj,
        ...(it.recipeSnapshot
          ? {
              recipeSnapshot: {
                ...it.recipeSnapshot,
                subject: it.recipeSnapshot.subject || itSubj
              }
            }
          : {})
      };
    });

    const isManualTitle = Boolean(ctrlNode?.data?.titleSource === "manual" && ctrlNode.data?.title);

    const entry = {
      id: entryId,
      requestId: firstReqId,
      createdAt: dateFull,
      timeShort,
      tabTitle: isRecipe ? "做图配方" : (curTab ? curTab.title : "当前工作流"),
      subject: cleanSubject,
      title: isManualTitle ? ctrlNode.data.title : "",
      isCustomTitle: isManualTitle,
      titleSource: isManualTitle ? "manual" : "auto",
      ctrlId: isRecipe ? "" : ctrlNode.id,
      recipeId: recipeId || "",
      dispId: "",
      mode: mode,
      modeLabel: `${isDemoGenerationEnabled() ? "🧪 演示样图 · " : ""}${
        isLoopBatch ? `循环批量 · ${items.length} 张` : `${modeMeta ? modeMeta.label : "生成"} · ${items.length} 张`
      }`,
      kind: kind || (items.length > 1 ? "multi" : "single"),
      creationSource: creationSource || (isRecipe ? "quick" : "canvas"),
      engine: isLive ? "live" : "demo",
      demoMode: isDemoGenerationEnabled(),
      recipeSummary: summaryText,
      recipeSnapshot: (items && items[0]?.recipeSnapshot)
        ? {
            ...items[0].recipeSnapshot,
            subject: items[0].recipeSnapshot.subject || cleanSubject
          }
        : (rec ? {
            style1: rec.style1Id || "",
            style2: rec.style2Id || "",
            layout: rec.layoutId || "",
            subject: cleanSubject
          } : null),
      prompt: isRecipe
        ? (ctrlNode.prompt || ctrlNode.subject || "")
        : isLoopBatch
          ? items.map((it, idx) => `【第 ${idx + 1} 轮】${it.prompt || it.theme || ""}`).join("\n\n")
          : E.assembleControlPrompt(CS.graph, ctrlNode, Catalog, "skill"),
      markdown: markdown || "",
      items: resolvedItems,
      ...(CS.forkGenerationSource?.generationId ? {
        forkGenerationId: CS.forkGenerationSource.generationId,
        forkItemId: CS.forkGenerationSource.itemId || ""
      } : {})
    };

    CS.generationHistory = upsertHistoryEntry(CS.generationHistory, entry, { isServer: false });
    writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
    if (!isLive) {
      studioApiPost("/api/studio/history", entry).then((res) => {
        if (res && res.ok && res.id && res.id !== entry.id) {
          entry.id = res.id;
          const idx = (CS.generationHistory || []).findIndex(
            (h) => h.id === entry.id || (entry.requestId && h.requestId === entry.requestId)
          );
          if (idx >= 0) {
            CS.generationHistory[idx].id = res.id;
            writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
          }
        }
      }).catch(() => {});
    }
    if (CS.stageView === "history") renderHistoryStage();
  }

  function sortPlanCardsInDocOrder(cards) {
    return [...(cards || [])]
      .map((c, idx) => ({ c, idx }))
      .sort((a, b) => {
        const ba = typeof a.c.afterBlockIdx === "number" ? a.c.afterBlockIdx : -1;
        const bb = typeof b.c.afterBlockIdx === "number" ? b.c.afterBlockIdx : -1;
        return ba - bb || a.idx - b.idx;
      })
      .map((x) => x.c);
  }

  function recordArticlePlanHistory(ctrlNode, planNode) {
    ensureGenerationHistoryInitialized();
    if (!planNode) return;
    const readyCards = sortPlanCardsInDocOrder(planNode.data.cards || []).filter((c) => c.imageUrl);
    if (!readyCards.length) return;
    const rec = ctrlNode ? E.resolveControlRecipe(CS.graph, ctrlNode, Catalog) : null;
    const curTab = CS.tabs.find((t) => t.id === CS.activeTabId);
    const now = new Date();
    const timeShort = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const dateFull = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${timeShort}`;

    const hasLiveCards = readyCards.some((c) => c && (c.generationMode === "live" || c.engine === "live"));
    const isLive = isLiveGenerationEnabled() || hasLiveCards;

    const articleTitle = String(planNode.data?.articleTitle || "").trim();
    const isManualTitle = Boolean(
      planNode.data?.articleTitleSource === "manual" ||
      planNode.data?.titleSource === "manual"
    );
    const artSubject = articleTitle || (readyCards[0]?.subject) || (readyCards[0]?.recipeSnapshot?.subject) || "";

    const entry = {
      id: planNode.data.generationId || E.uid("hist_art"),
      requestId: planNode.data.requestId || "",
      createdAt: dateFull,
      timeShort,
      tabTitle: curTab ? curTab.title : "文章配图方案",
      subject: artSubject,
      articleTitle: articleTitle,
      title: isManualTitle ? articleTitle : "",
      isCustomTitle: isManualTitle,
      titleSource: isManualTitle ? "manual" : "auto",
      ctrlId: ctrlNode ? ctrlNode.id : "",
      dispId: planNode.id,
      mode: "article-illust",
      creationSource: "article",
      modeLabel: `${isDemoGenerationEnabled() ? "🧪 演示样图 · " : ""}文章配图 · ${readyCards.length} 张`,
      kind: "article",
      engine: isLive ? "live" : "demo",
      demoMode: isDemoGenerationEnabled(),
      recipeSummary: rec && ctrlNode ? buildRecipeSummaryText(rec, ctrlNode) : `文章配图方案 · ${readyCards.length} 张`,
      prompt: readyCards.map((c) => c.prompt).filter(Boolean).join("\n\n---\n\n"),
      markdown: planNode.data.markdown || "",
      items: readyCards.map((c, idx) => ({
        id: c.id || `card_${idx}`,
        genId: c.genId || "",
        requestId: c.requestId || "",
        role: c.role || "inline",
        title: c.title || "配图",
        subject: c.subject || artSubject,
        articleTitle: articleTitle,
        ratio: c.ratio || "4:3",
        prompt: c.prompt || "",
        imageUrl: c.imageUrl
      }))
    };

    CS.generationHistory = upsertHistoryEntry(CS.generationHistory, entry, { isServer: false });
    writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
    if (!isLive) {
      studioApiPost("/api/studio/history", entry).then((res) => {
        if (res && res.ok && res.id && res.id !== entry.id) {
          entry.id = res.id;
          const idx = (CS.generationHistory || []).findIndex(
            (h) => h.id === entry.id || (entry.requestId && h.requestId === entry.requestId)
          );
          if (idx >= 0) {
            CS.generationHistory[idx].id = res.id;
            writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
          }
        }
      }).catch(() => {});
    }
    if (CS.stageView === "history") renderHistoryStage();
  }

  async function generateSinglePlanCard(planNodeOrArtId, cardId, { silent = false, skipHistory = false, skipCostConfirmation = false, batchId = "", batchIndex = 0, batchTotal = 1 } = {}) {
    const runEpoch = cacheScopeEpoch;
    const runScope = activeCacheScope;
    const target = resolveArticleTarget(planNodeOrArtId);
    const planNode = target?.planNode || null;
    if (!planNode || planNode.type !== "article_plan") return false;
    const card = (planNode.data.cards || []).find((c) => c.id === cardId);
    if (!card || card.status === "generating") return false;
    const previousImageUrl = card.imageUrl || "";
    let submittedInput = "";
    let submittedRequestId = "";
    const inputKey = () => JSON.stringify({
      card: articleCloudPayload(target.art).cards.find(item => item.id === card.id),
      style1: target.art.style1, layout: target.art.layout,
      settings: target.art.settings, coverRatio: target.art.coverRatio, inlineRatio: target.art.inlineRatio,
      imageUrl: card.imageUrl || "", resultEpoch: card.resultEpoch
    });
    const currentCard = () => (target.art.cards || []).includes(card) &&
      (!submittedInput || inputKey() === submittedInput);
    if (batchId) {
      card.batchId = batchId;
      card.batchIndex = batchIndex;
      card.batchTotal = batchTotal;
    }
    const sourcePrompt = String(card.prompt || "").trim();
    if (sourcePrompt.length > 4000) {
      if (!silent) toast("这张图的完整提示词超过 4000 字符，请精简后再生成；没有扣费");
      return false;
    }

    const useLiveApi = isLiveGenerationEnabled();
    const useDemo = isDemoGenerationEnabled();
    if (!useLiveApi && !useDemo) {
      if (!silent) toast("真实生图服务尚未配置，当前已禁用生成；仅显式 demo_mode 才能使用演示样图。");
      return false;
    }
    if (!App.state.loggedIn && useLiveApi) {
      S.openLoginModal("调用云端真实大模型生图需先登录账号！", () => renderFullPreviewStage());
      return false;
    }
    if (!skipCostConfirmation && !(await confirmArticleGenerationCost(1, {
      replacing: Boolean(card.imageUrl)
    }))) return false;
    if (isStaleScope(runEpoch, runScope) || card.status === "generating") return false;
    if (card.status !== "error") card.requestId = "";

    const hadDisplayBefore = target.isActiveCanvas
      ? getDownstreamDisplayNodes(planNode.id).some((d) => d.data?.planCardId === card.id)
      : false;
    card.status = "generating";
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    if (controller) _generationControllers.add(controller);
    commitArticleTargetChanges(target, { bumpTime: false });
    renderFullPreviewStage();
    if (target.isActiveCanvas) renderWorldNodes();

    try {
      const rec = null;
      if (rec?.audience) recordRecentFieldValue("audience", rec.audience);
      if (rec?.businessScene) recordRecentFieldValue("businessScene", rec.businessScene);

      const fallbackPool = [
        card.sampleImg,
        rec?.style1Res?.image,
        rec?.layoutRes?.image,
        rec?.style2Res?.image,
        rec?.assetItems?.[0]?.image,
        "/images/individual/FA/FA-003.webp",
        "/images/individual/FA/FA-013.webp",
        "/images/individual/FB/FB-031.webp",
        "/images/poster-demo-autumn-equinox.webp",
        "/images/graphic-text-mode-demo.webp",
        "/images/A_001-016.webp",
        "/images/B_036-048.webp"
      ].filter(Boolean);
      const uniquePool = [...new Set(fallbackPool)];

      let imgUrl = "";
      const cardS1 = card.style1 || target.art?.style1 || "";
      const cardS2 = (card.style2 ?? target.art?.settings?.style2) || "";
      const cardLay = card.layoutId || card.layout || rec?.layoutId || target.art?.layout || "";
      const cardS1Res = cardS1 && Catalog?.resourceMap ? (Catalog.resourceMap.get(cardS1) || rec?.style1Res) : rec?.style1Res;
      const cardS2Res = cardS2 && Catalog?.resourceMap ? (Catalog.resourceMap.get(cardS2) || rec?.style2Res) : rec?.style2Res;
      const cardLayRes = cardLay && Catalog?.resourceMap ? (Catalog.resourceMap.get(cardLay) || rec?.layoutRes) : rec?.layoutRes;
      const cardSubj = String(card.subject || card.theme || card.title || rec?.combinedText || "").trim();
      card.subject = cardSubj;
      card.recipeSnapshot = {
        style1: cardS1,
        style1Name: cardS1Res?.name || cardS1Res?.title || "",
        style2: cardS2,
        style2Name: cardS2Res?.name || cardS2Res?.title || "",
        layout: cardLay,
        layoutName: cardLayRes?.name || cardLayRes?.title || "",
        subject: cardSubj
      };
      submittedInput = inputKey();

      if (useLiveApi) {
        const refImages = card.refImages || [];
        if (!(await flushCloudArticlesSync())) throw new Error("文章尚未保存到云端，请先处理保存状态");
        const requestId = card.requestId = ensureStableRequestId(card.requestId, `article_${card.id || "card"}`);
        submittedRequestId = requestId;
        card.taskId = "";
        commitArticleTargetChanges(target, { bumpTime: false });
        const resp = await fetch("/api/studio/generate", {
          method: "POST",
          credentials: "include",
          signal: controller ? controller.signal : undefined,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt: card.prompt || card.title || "手绘文章配图",
            // Article cards already contain the complete user-visible prompt.
            // Prevent the backend from silently composing another AI prompt.
            promptFromSkill: Boolean(sourcePrompt),
            ratio: card.ratio || (card.role === "cover"
              ? target.art.coverRatio || target.art.settings?.coverRatio || "2.35:1"
              : target.art.inlineRatio || target.art.settings?.inlineRatio || "4:3"),
            style1: cardS1,
            style2: cardS2,
            layout: cardLay,
            refImages,
            recipeSnapshot: card.recipeSnapshot,
            creationSource: "article",
            articleId: target.art.id,
            cardId: card.id,
            ...(card.batchId ? {
              batchId: card.batchId,
              batchIndex: card.batchIndex || 0,
              batchTotal: card.batchTotal || 1,
              retryCancelled: card.status === "cancelled" || card.status === "error"
            } : {}),
            requestId,
            clientRequestId: requestId,
            confirmCost: true
          })
        });
        const data = await resp.json();
        if (isStaleScope(runEpoch, runScope)) return false;
        if (!resp.ok || !data.ok) {
          const error = new Error(data.error || `HTTP ${resp.status}`);
          error.terminal = resp.status >= 400 && resp.status < 500 && resp.status !== 408;
          throw error;
        }
        if (typeof data.credits === "number") App.state.credits = data.credits;
        if (typeof data.freeQuotaRemaining === "number") App.state.freeQuotaRemaining = data.freeQuotaRemaining;
        if (S.renderChrome) S.renderChrome();
        const activeReqId = data.requestId || requestId;
        const activeGenId = data.genId || "";
        submittedRequestId = activeReqId;
        card.genId = activeGenId;
        card.requestId = activeReqId;
        if (data.imageUrl) {
          imgUrl = data.imageUrl;
        } else if (Array.isArray(data.images) && data.images.length) {
          imgUrl = data.images[0];
        } else if (data.taskId || activeReqId) {
          card.taskId = data.taskId || "";
          commitArticleTargetChanges(target, { bumpTime: false });
          const imgs = await pollCloudTask(data.taskId || "", {
            requestId: activeReqId,
            signal: controller ? controller.signal : undefined
          });
          if (isStaleScope(runEpoch, runScope)) return false;
          imgUrl = (imgs && imgs[0]) || "";
        } else {
          throw new Error("云端未返回任务编号或图片");
        }
        if (!imgUrl) {
          throw new Error("云端没有返回图片");
        }
      } else {
        await new Promise((r) => setTimeout(r, 220));
        if (isStaleScope(runEpoch, runScope)) return false;
        const genTick = (card._genCount || 0) + 1;
        card._genCount = genTick;
        if (card.sampleImg && genTick === 1 && !card.imageUrl) {
          imgUrl = card.sampleImg;
        } else {
          const cardIdx = (planNode.data.cards || []).indexOf(card);
          imgUrl = uniquePool[(Math.max(0, cardIdx) + genTick) % uniquePool.length] || "/images/poster-demo-autumn-equinox.webp";
        }
      }

      if (isStaleScope(runEpoch, runScope) || !currentCard()) return false;
      if (App.state?.serverBacked && App.state?.loggedIn) {
        if (useLiveApi) {
          const saved = await S.apiJson(`/api/studio/articles/${encodeURIComponent(target.art.id)}`);
          if (isStaleScope(runEpoch, runScope) || !currentCard()) return false;
          const accepted = saved?.article?.cards?.find(item => item.id === card.id);
          if (!accepted || accepted.prompt !== card.prompt)
            throw new Error("文章配图已在其他窗口修改，请刷新查看；本次结果保留在生图历史");
          imgUrl = accepted.imageUrl || "";
          card.resultEpoch = accepted.resultEpoch;
          card.selectedMediaId = accepted.selectedMediaId;
          submittedInput = inputKey();
          if (!imgUrl) throw new Error("本次结果未应用到当前配图位，请刷新查看生图历史");
        } else {
          await selectArticleCardImage(target, card, imgUrl);
        }
      }
      if (previousImageUrl && previousImageUrl !== imgUrl) {
        window.HandrawArticleWorkbench?.pushVariant(card, previousImageUrl, "之前的成图");
      }
      card.imageUrl = imgUrl;
      card.generationMode = useLiveApi ? "live" : "demo";
      card.demoMode = !useLiveApi;
      card.taskId = "";
      card.status = "done";
      planNode.data.updatedAt = new Date().toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      });
      if (!skipHistory) {
        planNode.data.runCount = (planNode.data.runCount || 0) + 1;
        recordArticlePlanHistory(null, planNode);
      }
      commitArticleTargetChanges(target, { bumpTime: !skipHistory });
      if (!silent) {
        toast(
          target.isActiveCanvas
            ? `✨ 已生成「${card.title}」并同步右侧图片显示节点！`
            : `✨ 已生成「${card.title}」！`
        );
      }
      return true;
    } catch (err) {
      if (isStaleScope(runEpoch, runScope) || !currentCard()) return false;
      card.status = "error";
      card.errorText = String(err?.message || err || "").slice(0, 60);
      if (err.terminal) card.requestId = "";
      commitArticleTargetChanges(target, { bumpTime: false });
      if (!silent) toast(`⚠️ 配图生成失败：${err.message || err}`);
      return false;
    } finally {
      if (controller) _generationControllers.delete(controller);
      if (!isStaleScope(runEpoch, runScope)) {
        if (!currentCard() && (target.art.cards || []).includes(card) && card.status === "generating" &&
            card.requestId === submittedRequestId) {
          card.status = card.imageUrl ? "done" : "pending";
          card.taskId = "";
          card.requestId = "";
        }
        commitArticleTargetChanges(target, { bumpTime: false });
        renderFullPreviewStage();
        if (target.isActiveCanvas) {
          renderWorldNodes();
          renderMinimap();
        }
        renderWorkbenchBar();
        if (!skipHistory && !hadDisplayBefore && target.isActiveCanvas && CS.stageView === "canvas" && DOM.viewport) {
          requestAnimationFrame(() => fitView());
        }
      }
    }
  }

  async function generateBatchPlanCards(planNodeOrArtId, { onlyPending = true, silent = false } = {}) {
    const runEpoch = cacheScopeEpoch;
    const runScope = activeCacheScope;
    const target = resolveArticleTarget(planNodeOrArtId);
    const planNode = target?.planNode || null;
    if (!planNode || planNode.type !== "article_plan" || planNode.data.status === "generating") return false;
    if (_activeArticleBatchRun) {
      if (!silent) toast("另一批图片正在生成，请等待完成或停止后再操作");
      return false;
    }
    const allCards = sortPlanCardsInDocOrder(planNode.data.cards || []);
    if (!allCards.length) {
      if (!silent) toast("当前文章暂无配图卡片，请在段落间隙点击「＋ 在此处添加配图卡片」");
      return false;
    }

    // All batch entry points intentionally skip completed cards. Regenerating
    // an existing image must be a deliberate, separately priced card action.
    const guard = window.HandrawArticleGenerationGuard;
    if (!guard) { if (!silent) toast("配图确认模块尚未加载，请刷新页面"); return false; }
    const pending = guard.pendingCards(allCards);
    if (!pending.length) {
      if (!silent) toast("所有配图均已完成；需要重新生成时请在对应卡片操作");
      return false;
    }
    const selection = await window.HandrawArticleWorkbench.selectGeneration(pending);
    if (!selection.approved) return false;
    const effectiveTargets = window.HandrawArticleWorkbench.choices(pending, selection.ids);
    if (!effectiveTargets.length) return false;
    if (effectiveTargets.some((c) => String(c.prompt || "").trim().length > 4000)) {
      if (!silent) toast("本次选中的配图有提示词超过 4000 字符，请先精简；没有扣费");
      return false;
    }

    const useLiveApi = isLiveGenerationEnabled();
    const useDemo = isDemoGenerationEnabled();
    if (!useLiveApi && !useDemo) {
      if (!silent) toast("真实生图服务尚未配置，当前已禁用生成；仅显式 demo_mode 才能使用演示样图。");
      return false;
    }
    if (!App.state.loggedIn && useLiveApi) {
      S.openLoginModal("调用云端真实大模型批量生图需先登录账号！", () => renderFullPreviewStage());
      return false;
    }

    const prevDispCount = target.isActiveCanvas ? getDownstreamDisplayNodes(planNode.id).length : 0;
    if (!(await confirmArticleGenerationCost(effectiveTargets.length, {
      skipped: allCards.length - effectiveTargets.length
    }))) return false;
    if (isStaleScope(runEpoch, runScope) || planNode.data.status === "generating") return false;
    // Retry incomplete cards in the SAME logical run if all selected cards
    // belong to one unfinished batch. A new user batch gets a new work.
    const previousBatches = [...new Set(effectiveTargets.map(x => x.batchId).filter(Boolean))];
    const resumeBatch = previousBatches.length === 1 && effectiveTargets.every(x => x.batchId === previousBatches[0]);
    const resolvedBatchId = resumeBatch ? previousBatches[0] : makeStableRequestId("article_batch");
    const resolvedBatchTotal = resumeBatch ? (effectiveTargets[0].batchTotal || effectiveTargets.length) : effectiveTargets.length;
    effectiveTargets.forEach((card, index) => {
      card.batchId = resolvedBatchId;
      card.batchTotal = resolvedBatchTotal;
      if (!resumeBatch) card.batchIndex = index;
    });
    const batchRun = { id: resolvedBatchId, cancelled: false,
      total: effectiveTargets.length, completed: 0, failed: 0, running: 0,
      parallel: selection.parallel, startedAt: Date.now(), ids: effectiveTargets.map(x=>x.id) };
    CS.lastArticleBatchSummary = null;
    _activeArticleBatchRun = batchRun;
    CS.activeArticleBatchRun = batchRun;
    planNode.data.status = "generating";
    commitArticleTargetChanges(target, { bumpTime: true });
    renderFullPreviewStage();
    if (target.isActiveCanvas) renderWorldNodes();

    let okCount = 0;
    const targetRefId = target.isActiveCanvas ? planNode.id : target.art?.id || planNode.id;
    try {
      await window.HandrawArticleWorkbench.runPool(effectiveTargets, selection.parallel,
        async (c) => {
          if (isStaleScope(runEpoch, runScope) || batchRun.cancelled) return false;
          batchRun.running += 1;
          try {
            return await generateSinglePlanCard(targetRefId, c.id, {
              silent: true, skipHistory: true, skipCostConfirmation: true,
              batchId: c.batchId, batchIndex: c.batchIndex, batchTotal: c.batchTotal
            });
          } finally {
            batchRun.running = Math.max(0,batchRun.running-1);
          }
        },
        () => batchRun.cancelled || isStaleScope(runEpoch, runScope),
        (_,ok) => {
          batchRun.completed += 1;
          if (ok) okCount += 1;
          else batchRun.failed += 1;
          CS.lastArticleBatchSummary = {
            total: batchRun.total, succeeded: okCount, failed: batchRun.failed,
            skipped: allCards.length - effectiveTargets.length, parallel: selection.parallel,
            finished: batchRun.completed, startedAt: batchRun.startedAt,
            running: batchRun.running, ids: batchRun.ids
          };
          if (!isStaleScope(runEpoch, runScope)) renderFullPreviewStage();
        }
      );
      if (batchRun.cancelled) {
        if (useLiveApi) {
          try {
            const positions = effectiveTargets
              .filter(card => card.status !== "done")
              .map(card => card.batchIndex);
            if (positions.length) {
              await S.apiJson(`/api/studio/batches/${encodeURIComponent(resolvedBatchId)}/cancel-pending`, {
                method: "POST", body: { positions }
              });
            }
          } catch (error) {
            console.warn("文章配图尚未提交的图片槽位取消状态未能同步", error);
          }
        }
        if (!silent) toast(`已停止后续提交，${Math.max(0, effectiveTargets.length - okCount)} 项尚未全部成功；已提交上游的任务仍会按实际结果结算。`);
        return okCount > 0;
      }
      planNode.data.runCount = (planNode.data.runCount || 0) + 1;
      recordArticlePlanHistory(null, planNode);
      commitArticleTargetChanges(target, { bumpTime: true });
      if (!silent) {
        toast(`批量完成：成功 ${okCount} 张，失败 ${batchRun.failed} 张，跳过 ${allCards.length-effectiveTargets.length} 张；失败项可以单独重试。`);
      }
      return okCount > 0;
    } finally {
      if (_activeArticleBatchRun === batchRun) {
        _activeArticleBatchRun = null;
        CS.activeArticleBatchRun = null;
      }
      if (!isStaleScope(runEpoch, runScope)) {
        planNode.data.status = "ready";
        if (CS.lastArticleBatchSummary) CS.lastArticleBatchSummary.running = 0;
        commitArticleTargetChanges(target, { bumpTime: false });
        renderFullPreviewStage();
        if (target.isActiveCanvas) {
          renderWorldNodes();
          renderMinimap();
        }
        renderWorkbenchBar();
        if (target.isActiveCanvas) {
          const afterDisps = getDownstreamDisplayNodes(planNode.id);
          if (afterDisps.length > prevDispCount && CS.stageView === "canvas" && DOM.viewport) {
            requestAnimationFrame(() => fitView());
          }
        }
      }
    }
  }

  // CRITICAL AUTO-RULE #2: Multi-image output automatically connects multiple 1-image "图片显示" nodes!
  async function runOutputControlNode(ctrlId, { onlyItemIdx = null, onlyDispNodeId = null, silent = false } = {}) {
    const runEpoch = cacheScopeEpoch;
    const runScope = activeCacheScope;
    const creationSource = CS.stageView === "batch" ? "batch" : CS.stageView === "quick" ? "quick" : CS.stageView === "preview" || CS.stageView === "article" ? "article" : "canvas";
    const ctrl = getNodeById(ctrlId);
    if (!ctrl || ctrl.type !== "output_control" || ctrl.data.status === "generating") {
      if (ctrl && ctrl.data.status === "generating" && !silent) {
        toast("已有任务正在生成中，请等待完成或停止后再开始新批次");
      }
      return false;
    }

    if (!checkExclusiveGateForControl(ctrl)) return false;

    if (ctrl.data.mode === "article-illust") {
      const { node: planNode, createdNew } = ensureArticlePlanNodeForControl(ctrl);
      if (!planNode) return false;
      CS.activePlanNodeId = planNode.id;
      CS.previewTab = "article";
      ctrl.data.status = "generating";
      fullRenderCanvas();
      persistOpenTabs();
      if (createdNew && CS.stageView === "canvas" && DOM.viewport) {
        requestAnimationFrame(() => fitView());
      }
      try {
        const ok = await generateBatchPlanCards(planNode.id, { onlyPending: false, silent });
        ctrl.data.status = ok ? "done" : "idle";
        return ok;
      } finally {
        if (!isStaleScope(runEpoch, runScope)) {
          if (ctrl.data.status === "generating") ctrl.data.status = "done";
          fullRenderCanvas();
        }
      }
    }

    const useLiveApi = isLiveGenerationEnabled();
    const useDemo = isDemoGenerationEnabled();
    if (!useLiveApi && !useDemo) {
      if (!silent) toast("真实生图服务尚未配置，当前已禁用生成；仅显式 demo_mode 才能使用演示样图。");
      return false;
    }
    if (!App.state.loggedIn && useLiveApi) {
      S.openLoginModal("调用云端真实大模型生图需先登录账号！", () => fullRenderCanvas());
      return false;
    }

    const plan = buildExecutionPlanForControl(ctrl);
    if (plan.kind === "loop-empty") {
      const lp = getNodeById(plan.loopNodeId);
      const lm = lp?.data?.loopMode || "prompts";
      if (lm === "styles") {
        toast("请先在「循环批量」节点选择至少 1 款画风");
        if (lp) openLoopMultiPickerModal(lp, "styles");
      } else if (lm === "layouts") {
        toast("请先在「循环批量」节点选择至少 1 款图型");
        if (lp) openLoopMultiPickerModal(lp, "layouts");
      } else if (lm === "assets") {
        toast("请先在左侧连入包含参考图片的「图片参数」节点");
      } else {
        toast("请先在「循环批量」节点输入至少 1 行文案或主题");
        if (lp) openLoopPromptsModal(lp.id);
      }
      return false;
    }

    const activeLoopNode = plan.kind === "loop" ? getNodeById(plan.loopNodeId) : null;
    if (activeLoopNode && activeLoopNode.data.status === "running") {
      if (!silent) toast("已有批量任务正在运行中，请等待完成或停止后再开始新批次");
      return false;
    }

    const existingBefore = getDownstreamDisplayNodes(ctrl.id);
    let resolvedOnlyIdx = onlyItemIdx;
    let resolvedOnlyDispId = onlyDispNodeId;

    if (resolvedOnlyDispId && resolvedOnlyIdx === null) {
      const foundIdx = existingBefore.findIndex((d) => d.id === resolvedOnlyDispId);
      if (foundIdx >= 0) resolvedOnlyIdx = foundIdx;
    } else if (resolvedOnlyIdx !== null && !resolvedOnlyDispId && existingBefore[resolvedOnlyIdx]) {
      resolvedOnlyDispId = existingBefore[resolvedOnlyIdx].id;
    }

    // #146: a series run reuses successful output slots. A single-image
    // action remains an intentional regeneration and never skips itself.
    const isSeriesFill = creationSource === "batch" && resolvedOnlyIdx === null && plan.kind === "loop";
    const completedBefore = new Map();
    if (isSeriesFill) {
      const gallery = existingBefore[0]?.data?.kind === "batch_gallery";
      plan.specs.forEach((spec, index) => {
        const item = gallery ? existingBefore[0]?.data?.items?.[index]
          : existingBefore[index]?.data?.items?.[0];
        const expectedKey = spec.slotKey || String(index);
        // Do not attach a result from a different logical slot.
        if (item?.imageUrl && item.slotKey === expectedKey) completedBefore.set(index, item);
      });
      if (completedBefore.size === plan.specs.length) {
        if (!silent) toast("本系列图片已全部生成，无需重复提交；如需重做请单独选择图片。");
        return true;
      }
    }
    const pendingCount = resolvedOnlyIdx === null
      ? plan.specs.length - completedBefore.size : 1;
    if (!confirmPotentialGenerationCost(pendingCount)) return false;

    const prevActiveBatchId = ctrl.data.activeBatchId || "";
    const prevActiveBatchTotal = Number(ctrl.data.activeBatchTotal || 0);
    const hasMatchingBatch = Boolean(
      resolvedOnlyIdx !== null &&
      prevActiveBatchId &&
      (!prevActiveBatchTotal || prevActiveBatchTotal === plan.specs.length)
    );
    let batchId = hasMatchingBatch ? prevActiveBatchId : makeStableRequestId("batch");
    let isRotatedBatch = batchId !== prevActiveBatchId;
    ctrl.data.activeBatchId = batchId;
    ctrl.data.activeBatchTotal = plan.specs.length;

    const { nodes: dispNodes, createdCount, isBatchGallery } = syncControlDisplayNodes(ctrl, plan.specs.length, {
      markGenerating: true,
      onlyDispNodeId: resolvedOnlyDispId,
      onlyItemIdx: resolvedOnlyIdx,
      batchId,
      preserveCompleted: completedBefore.size ? completedBefore : null
    });

    ctrl.data.status = "generating";
    ctrl.data.elapsedSec = 0;
    ctrl.data.runCount = (ctrl.data.runCount || 0) + 1;
    const currentRunCount = ctrl.data.runCount;
    const preserveCompletedItemsForBatch = (targetBatchId) => {
      for (const dn of dispNodes) {
        if (resolvedOnlyIdx === null || dn.id === resolvedOnlyDispId || isBatchGallery || dn.data?.items?.some((it) => it?.imageUrl)) {
          dn.data.activeBatchId = targetBatchId;
        }
        if (Array.isArray(dn.data?.items)) {
          for (const item of dn.data.items) {
            if (item && item.imageUrl) item.batchId = targetBatchId;
          }
        }
      }
    };
    if (resolvedOnlyIdx !== null) {
      preserveCompletedItemsForBatch(batchId);
    } else {
      for (const dn of dispNodes) {
        dn.data.activeBatchId = batchId;
      }
    }
    if (activeLoopNode && resolvedOnlyIdx === null) {
      activeLoopNode.data.status = "running";
      activeLoopNode.data.currentStep = 0;
      activeLoopNode.data.totalSteps = plan.specs.length;
    }

    if (window.HandrawBatchCreate && plan.specs.length > 0) {
      if (typeof window.HandrawBatchCreate.resetBatchProgress === "function") {
        window.HandrawBatchCreate.resetBatchProgress({
          totalCount: plan.specs.length,
          batchId,
          singleSlotIndex: resolvedOnlyIdx,
          existingCompleted: completedBefore
        });
      }
      window.HandrawBatchCreate.updateProgress({
        completedCount: completedBefore.size,
        failedCount: 0,
        totalCount: plan.specs.length,
        activeIndex: resolvedOnlyIdx !== null ? resolvedOnlyIdx
          : plan.specs.findIndex((_,i)=>!completedBefore.has(i)),
        busy: true,
        batchId
      });
    }

    fullRenderCanvas();

    if (createdCount > 0 && CS.stageView === "canvas" && DOM.viewport) {
      requestAnimationFrame(() => {
        const vRect = DOM.viewport.getBoundingClientRect();
        const lastDisp = dispNodes[dispNodes.length - 1];
        if (lastDisp) {
          const brScreen = worldToScreen(lastDisp.x + (lastDisp.w || 308) + 36, lastDisp.y + (lastDisp.h || 308));
          if (brScreen.x > vRect.width || brScreen.y > vRect.height || lastDisp.x * CS.vk + CS.vx < 0) {
            fitView();
          }
        }
      });
    }

    const startedAt = Date.now();
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const submittedSlots = new Set();
    const batchRun = { id: batchId, ctrlId: ctrl.id, cancelled: false, controller, submittedSlots };
    if (controller) _generationControllers.add(controller);
    _activeBatchRun = batchRun;
    CS.activeBatchRun = batchRun;
    const timer = setInterval(() => {
      const sec = Math.floor((Date.now() - startedAt) / 1000);
      ctrl.data.elapsedSec = sec;
      for (const dn of dispNodes) {
        if (dn.data.status === "generating") {
          dn.data.elapsedSec = sec;
          const el = DOM.world && DOM.world.querySelector(`[data-timer-for="${dn.id}"]`);
          if (el) el.textContent = `${sec}s`;
        }
      }
    }, 450);

    let currentSlotKey = "";
    let currentReqId = "";

    try {
      const rec = E.resolveControlRecipe(CS.graph, ctrl, Catalog);
      if (rec.audience) recordRecentFieldValue("audience", rec.audience);
      if (rec.businessScene) recordRecentFieldValue("businessScene", rec.businessScene);
      const fallbackPool = [
        rec.style1Res?.image,
        rec.layoutRes?.image,
        rec.style2Res?.image,
        rec.assetItems[0]?.image,
        "/images/poster-demo-autumn-equinox.webp",
        "/images/graphic-text-mode-demo.webp",
        "/images/individual/FA/FA-003.webp",
        "/images/individual/FA/FA-013.webp",
        "/images/individual/FB/FB-031.webp",
        "/images/A_001-016.webp",
        "/images/B_036-048.webp",
        "/images/H_217-232.webp"
      ].filter(Boolean);
      const uniquePool = [...new Set(fallbackPool)];

      const nowStr = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const allItems = [];
      const completedSlots = new Set();
      const failedSlots = new Set();
      const existingItems = Array.from(completedBefore.entries()).map(([index,item])=>({
        index,item
      }));
      for (const {index,item} of existingItems) {
        completedSlots.add(plan.specs[index].slotKey || String(index));
      }
      const allItemsFromBefore = existingItems.map(({item})=>item);
      allItems.push(...allItemsFromBefore);
      let completedCount = completedSlots.size;
      let failedCount = 0;
      let lastFailureError = "";

      if (activeLoopNode && resolvedOnlyIdx === null) {
        activeLoopNode.data.currentStep = 0;
        activeLoopNode.data.totalSteps = plan.specs.length;
        activeLoopNode.data.completedCount = 0;
        activeLoopNode.data.failedCount = 0;
      }

      // Bounded worker pool: all requests share a logical batch, but each
      // slot has an independent id and stable output position.
      const runningIndices = new Set();
      let stopLaunching = false;
      // #143: the Series editor has no manual concurrency knob; run up to 4
      // in flight, bounded below by the existing plan/slot scheduler.
      const requestedConcurrency = CS.stageView === "batch" ? 4
        : Number(activeLoopNode?.data?.batchConcurrency || ctrl.data.batchConcurrency || 3);
      const concurrency = resolvedOnlyIdx !== null ? 1 : Math.max(1,
        Math.min(4, Number.isFinite(requestedConcurrency) ? requestedConcurrency : 3));
      const slotIndexes = resolvedOnlyIdx === null
        ? plan.specs.map((_,i)=>i).filter(i=>!completedBefore.has(i))
        : [resolvedOnlyIdx];
      if (resolvedOnlyIdx !== null) {
        for (let i = 0; i < plan.specs.length; i++) {
          if (i === resolvedOnlyIdx) continue;
          const dn = isBatchGallery ? dispNodes[0] : dispNodes[i];
          const old = isBatchGallery ? dn?.data?.items?.[i] : dn?.data?.items?.[0];
          if (!old) continue;
          if (isRotatedBatch && !old.imageUrl) continue;
          allItems.push(old);
          const key = plan.specs[i].slotKey || String(i);
          if (old.imageUrl) completedSlots.add(key);
          else if (old.failed) failedSlots.add(key);
        }
        completedCount = completedSlots.size;
        failedCount = failedSlots.size;
      }
      let nextSlotToLaunch = 0;
      async function runSlot(i) {
        if (batchRun.cancelled || stopLaunching || isStaleScope(runEpoch, runScope)) return;
        runningIndices.add(i);
        let currentSlotKey = "", currentReqId = "";
        try {
        if (isStaleScope(runEpoch, runScope)) return;
        if (batchRun.cancelled) return;
        const sp = plan.specs[i];
        const dn = isBatchGallery ? dispNodes[0] : dispNodes[i];
        if (activeLoopNode && resolvedOnlyIdx === null) {
          activeLoopNode.data.currentStep = completedCount;
          activeLoopNode.data.totalSteps = plan.specs.length;
          activeLoopNode.data.completedCount = completedCount;
          activeLoopNode.data.failedCount = failedCount;
          const progTxt = DOM.world && DOM.world.querySelector(`[data-loop-prog-text="${activeLoopNode.id}"]`);
          const progBar = DOM.world && DOM.world.querySelector(`[data-loop-prog-bar="${activeLoopNode.id}"]`);
          if (progTxt) progTxt.textContent = `⏳ 已完成 ${completedCount} / ${plan.specs.length} 张 · 并行生成中 ${runningIndices.size} 张`;
          if (progBar) progBar.style.width = `${Math.round(((completedCount + 0.5) / Math.max(1, plan.specs.length)) * 100)}%`;
        }
        if (isBatchGallery && dn) {
          const galProgEl = DOM.world && DOM.world.querySelector(`[data-gal-prog-for="${dn.id}"]`);
          if (galProgEl) galProgEl.textContent = `⏳ 正在批量出图：已完成 ${completedCount} / ${plan.specs.length} 张…`;
        }
        if (window.HandrawBatchCreate) {
          window.HandrawBatchCreate.updateProgress({
            completedCount,
            failedCount,
            totalCount: plan.specs.length,
            activeIndex: i,
            activeIndices: Array.from(runningIndices),
            busy: true,
            batchId
          });
        }

        const skillPrompt = E.assembleControlPrompt(CS.graph, ctrl, Catalog, "skill", sp);
        let imgUrl = "";
        let activeReqId = "";
        let activeGenId = "";
        let itemFailed = false;
        let itemErrorMsg = "";
        let itemIsTerminal = false;
        let isGlobalError = false;

        const slotKey = sp.slotKey || String(i);
        currentSlotKey = slotKey;
        // A deliberate image-level rerun must reserve a NEW gateway request
        // (and when batch count changed, never replay a stale batch or requestId).
        if (resolvedOnlyIdx !== null && dn && dn.data) {
          const staleReqId = dn.data.pendingRequestIds?.[slotKey];
          const hasLiveTask = Boolean(dn.data.pendingTaskId || dn.data.pendingTasksBySlot?.[slotKey]?.taskId);
          if (staleReqId && (!hasLiveTask || isRotatedBatch || !staleReqId.includes(batchId))) {
            if (dn.data.pendingRequestIds) delete dn.data.pendingRequestIds[slotKey];
            if (dn.data.pendingSpec) delete dn.data.pendingSpec[staleReqId];
            if (dn.data.pendingTasksBySlot) delete dn.data.pendingTasksBySlot[slotKey];
          }
        }
        let requestId = dn && dn.data && dn.data.pendingRequestIds && dn.data.pendingRequestIds[slotKey];
        if (!requestId) {
          requestId = makeStableRequestId(`out_${batchId}_${slotKey}`);
          if (dn) {
            dn.data.pendingRequestIds = dn.data.pendingRequestIds || {};
            dn.data.pendingRequestIds[slotKey] = requestId;
          }
        }
        currentReqId = requestId;
        if (dn) {
          dn.data.pendingTasksBySlot = dn.data.pendingTasksBySlot || {};
          dn.data.pendingTasksBySlot[slotKey] = {
            taskId: dn.data.pendingTasksBySlot[slotKey]?.taskId || "", requestId
          };
          dn.data.pendingRequestId = requestId;
        }
        if (dn) {
          dn.data.pendingRequestIds = dn.data.pendingRequestIds || {};
          dn.data.pendingRequestIds[slotKey] = requestId;
          dn.data.pendingSpec = dn.data.pendingSpec || {};
          dn.data.pendingSpec[requestId] = {
            batchId,
            slotKey,
            index: i,
            role: sp.role || "image",
            title: sp.title || `图片 #${i + 1}`,
            anchorHeading: sp.anchorHeading || "",
            ratio: sp.ratio || "3:4",
            theme: sp.theme || "",
            prompt: skillPrompt,
            recipeSnapshot: sp.recipeSnapshot ? JSON.parse(JSON.stringify(sp.recipeSnapshot)) : null
          };
          // Persist the request and its exact slot/spec together, before
          // the first network byte is sent or a stop can abort the fetch.
          persistOpenTabs();
        }

        try {
          if (useLiveApi) {
            const cloudPrompt = E.assembleControlPrompt(CS.graph, ctrl, Catalog, "cloud", sp);
            const effectiveAssets = Array.isArray(sp.assetItems) ? sp.assetItems : rec.assetItems;
            const refImages = effectiveAssets.map((a) => a.image).filter(Boolean);
            let resp = null;
            let data = null;
            for (let batchAttempt = 0; batchAttempt < 2; batchAttempt += 1) {
              submittedSlots.add(slotKey);
              resp = await fetch("/api/studio/generate", {
                method: "POST",
                credentials: "include",
                signal: controller ? controller.signal : undefined,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  prompt: cloudPrompt,
                  ratio: sp.ratio || "3:4",
                  style1: sp.style1 || rec.style1Id || "",
                  style2: rec.style2Id || "",
                  layout: sp.layout || rec.layoutId || "",
                  refImages,
                  // Preserve the exact user-entered per-image theme for the
                  // public series detail. The cloudPrompt remains separate.
                  recipeSnapshot: {
                    ...(sp.recipeSnapshot || {}),
                    theme: sp.theme || ""
                  },
                  creationSource,
                  batchId,
                  batchIndex: i,
                  batchTotal: plan.specs.length,
                  retryCancelled: resolvedOnlyIdx !== null,
                  requestId,
                  clientRequestId: requestId,
                  confirmCost: true,
                  ...(CS.forkGenerationSource?.generationId ? {
                    forkGenerationId: CS.forkGenerationSource.generationId,
                    forkItemId: CS.forkGenerationSource.itemId || ""
                  } : {})
                })
              });
              const serverReqId = (typeof resp.headers?.get === "function" && resp.headers.get("X-Request-ID")) || "";
              try {
                data = await resp.json();
              } catch (parseErr) {
                data = { ok: false, error: `HTTP ${resp.status}`, requestId: serverReqId };
                console.error("[Studio Generate] non-JSON response", { status: resp.status, requestId: serverReqId }, parseErr);
              }
              if (serverReqId && data && typeof data === "object" && !data.requestId) {
                data.requestId = serverReqId;
              }
              if (isStaleScope(runEpoch, runScope)) return;
              if (
                batchAttempt === 0 &&
                resolvedOnlyIdx !== null &&
                resp.status === 409 &&
                data?.code === "batch_size_mismatch" &&
                !batchRun.cancelled
              ) {
                const prevBatchId = batchId;
                const rotatedBatchId = makeStableRequestId("batch");
                const staleReqId = requestId;
                batchId = rotatedBatchId;
                isRotatedBatch = true;
                batchRun.id = rotatedBatchId;
                ctrl.data.activeBatchId = rotatedBatchId;
                ctrl.data.activeBatchTotal = plan.specs.length;
                preserveCompletedItemsForBatch(rotatedBatchId);
                requestId = makeStableRequestId(`out_${rotatedBatchId}_${slotKey}`);
                currentReqId = requestId;
                if (dn && dn.data) {
                  dn.data.activeBatchId = rotatedBatchId;
                  dn.data.pendingRequestIds = dn.data.pendingRequestIds || {};
                  dn.data.pendingRequestIds[slotKey] = requestId;
                  dn.data.pendingRequestId = requestId;
                  dn.data.pendingTasksBySlot = dn.data.pendingTasksBySlot || {};
                  dn.data.pendingTasksBySlot[slotKey] = { taskId: "", requestId };
                  dn.data.pendingSpec = dn.data.pendingSpec || {};
                  const prevSpec = dn.data.pendingSpec[staleReqId] || {
                    slotKey,
                    index: i,
                    role: sp.role || "image",
                    title: sp.title || `图片 #${i + 1}`,
                    anchorHeading: sp.anchorHeading || "",
                    ratio: sp.ratio || "3:4",
                    theme: sp.theme || "",
                    prompt: skillPrompt,
                    recipeSnapshot: sp.recipeSnapshot ? JSON.parse(JSON.stringify(sp.recipeSnapshot)) : null
                  };
                  delete dn.data.pendingSpec[staleReqId];
                  dn.data.pendingSpec[requestId] = { ...prevSpec, batchId: rotatedBatchId };
                  persistOpenTabs();
                }
                if (window.HandrawBatchCreate) {
                  if (typeof window.HandrawBatchCreate.rotateBatchId === "function") {
                    window.HandrawBatchCreate.rotateBatchId(prevBatchId, rotatedBatchId);
                  }
                  window.HandrawBatchCreate.updateProgress({
                    completedCount,
                    failedCount,
                    totalCount: plan.specs.length,
                    activeIndex: i,
                    activeIndices: Array.from(runningIndices),
                    busy: true,
                    batchId: rotatedBatchId
                  });
                }
                continue;
              }
              break;
            }
            if (!resp.ok || !data.ok) {
              const err = new Error(data.error || `HTTP ${resp.status}`);
              err.status = resp.status;
              err.code = data.code || "";
              err.requestId = data.requestId || requestId;
              console.error("[Studio Generate] API failed", {
                status: resp.status,
                code: err.code,
                requestId: err.requestId,
                batchId,
                slotKey: currentSlotKey,
                error: err.message
              });
              throw err;
            }
            if (typeof data.credits === "number") App.state.credits = data.credits;
            if (typeof data.freeQuotaRemaining === "number") App.state.freeQuotaRemaining = data.freeQuotaRemaining;
            if (S.renderChrome) S.renderChrome();
            activeReqId = data.requestId || requestId;
            activeGenId = data.genId || "";
            if (data.imageUrl) {
              imgUrl = data.imageUrl;
            } else if (Array.isArray(data.images) && data.images.length) {
              imgUrl = data.images[0];
            } else if (data.taskId || activeReqId) {
              if (dn) {
                if (data.taskId) dn.data.pendingTaskId = data.taskId;
                dn.data.pendingRequestId = activeReqId;
                dn.data.pendingTasksBySlot = dn.data.pendingTasksBySlot || {};
                dn.data.pendingTasksBySlot[slotKey] = { taskId: data.taskId || "", requestId: activeReqId };
                dn.data.pendingSpec = dn.data.pendingSpec || {};
                if (!dn.data.pendingSpec[activeReqId]) {
                  dn.data.pendingSpec[activeReqId] = dn.data.pendingSpec[requestId] || {
                    batchId,
                    slotKey,
                    index: i,
                    role: sp.role || "image",
                    title: sp.title || `图片 #${i + 1}`,
                    anchorHeading: sp.anchorHeading || "",
                    ratio: sp.ratio || "3:4",
                    theme: sp.theme || "",
                    prompt: skillPrompt,
                    recipeSnapshot: sp.recipeSnapshot ? JSON.parse(JSON.stringify(sp.recipeSnapshot)) : null
                  };
                }
                persistOpenTabs();
              }
              const imgs = await pollCloudTask(data.taskId || "", {
                requestId: activeReqId,
                signal: controller ? controller.signal : undefined
              });
              if (isStaleScope(runEpoch, runScope)) return;
              imgUrl = (imgs && imgs[0]) || "";
            } else {
              throw new Error("云端未返回任务编号或图片");
            }
            if (!imgUrl) {
              throw new Error("云端没有返回图片");
            }
          } else {
            const stepDelay = plan.specs.length > 25 ? 10 : plan.specs.length > 6 ? 35 : plan.specs.length > 1 ? 110 : 240;
            await new Promise((r) => setTimeout(r, stepDelay));
            if (isStaleScope(runEpoch, runScope)) return;
            if (sp.sampleImg && currentRunCount === 1 && resolvedOnlyIdx === null && plan.specs.length <= 6) {
              imgUrl = sp.sampleImg;
            } else {
              const iterPool = [sp.sampleImg, ...uniquePool].filter(Boolean);
              const dedupIterPool = [...new Set(iterPool)];
              imgUrl = dedupIterPool[(i + currentRunCount - 1) % dedupIterPool.length] || "/images/poster-demo-autumn-equinox.webp";
            }
          }
        } catch (itemErr) {
          if (isStaleScope(runEpoch, runScope)) return;
          if (batchRun.cancelled) return;
          console.error("[Studio Generate] slot exception", {
            slotKey: currentSlotKey,
            requestId: itemErr?.requestId || activeReqId || requestId,
            status: itemErr?.status,
            code: itemErr?.code
          }, itemErr);
          reportUnexpectedRuntimeError(itemErr);
          itemFailed = true;
          itemErrorMsg = itemErr?.message || "生成失败";
          lastFailureError = itemErrorMsg;
          itemIsTerminal = Boolean(itemErr?.terminal);
          const st = itemErr?.status;
          if (st === 401 || st === 402 || st === 403 || st === 429 ||
              /401|402|403|429|登录|login|unauthorized|余额|积分|配额|quota|credit|insufficient|forbidden|concurrency|并发/i.test(itemErrorMsg)) {
            isGlobalError = true;
          }
        }

        if (isStaleScope(runEpoch, runScope) || batchRun.cancelled) return;
        if (ctrl.data.activeBatchId && ctrl.data.activeBatchId !== batchId) return;

        if (itemFailed) {
          failedSlots.add(currentSlotKey);
          failedCount = failedSlots.size;
          const failedItem = {
            id: E.uid("outit_fail"),
            genId: activeGenId || "",
            batchId,
            requestId: activeReqId || requestId,
            slotKey: currentSlotKey,
            title: sp.title || `图片 #${i + 1}`,
            theme: sp.theme || "",
            failed: true,
            error: itemErrorMsg,
            nodeId: dn?.id
          };
          if (dn) {
            if (dn.data.pendingTasksBySlot) delete dn.data.pendingTasksBySlot[slotKey];
            const nextPending = Object.values(dn.data.pendingTasksBySlot || {})[0];
            dn.data.pendingTaskId = nextPending?.taskId || "";
            dn.data.pendingRequestId = nextPending?.requestId || "";
            if (itemIsTerminal) {
              if (dn.data.pendingRequestIds) delete dn.data.pendingRequestIds[currentSlotKey];
              if (dn.data.pendingSpec) {
                delete dn.data.pendingSpec[requestId];
                if (activeReqId) delete dn.data.pendingSpec[activeReqId];
              }
            }
            if (isBatchGallery) {
              if (!Array.isArray(dn.data.items)) dn.data.items = [];
              const existIdx = dn.data.items.findIndex(
                (it) => it && ((it.slotKey && it.slotKey === currentSlotKey) || (it.requestId && it.requestId === requestId))
              );
              if (existIdx >= 0) {
                dn.data.items[existIdx] = failedItem;
              } else {

                dn.data.items[i] = failedItem;

              }
            } else {
              dn.data.status = "error";
              dn.data.error = itemErrorMsg;
              dn.data.items = [failedItem];
            }
          }
          runningIndices.delete(i);
          if (activeLoopNode && resolvedOnlyIdx === null) {
            activeLoopNode.data.currentStep = completedCount;
            activeLoopNode.data.completedCount = completedCount;
            activeLoopNode.data.failedCount = failedCount;
          }
          markActiveTabDirty();
          persistOpenTabs();
          if (window.HandrawBatchCreate) {
            window.HandrawBatchCreate.updateProgress({
              updatedIndex: i,
              itemResult: failedItem,
              completedCount,
              failedCount,
              totalCount: plan.specs.length,
              activeIndex: null,
              activeIndices: Array.from(runningIndices),
              busy: true,
              batchId
            });
          }
          if (isGlobalError) {
            stopLaunching = true;
            if (!silent) toast(`批量生成中断：${itemErrorMsg}`, "error");
          }
          return;
        }

        if (!completedSlots.has(currentSlotKey)) {
          completedSlots.add(currentSlotKey);
          completedCount = completedSlots.size;
        }
        const builtItem = {
          id: E.uid("outit"),
          genId: activeGenId || "",
          batchId,
          requestId: activeReqId || requestId,
          taskId: "",
          generationMode: useLiveApi ? "live" : "demo",
          demoMode: !useLiveApi,
          slotKey: currentSlotKey,
          role: sp.role || "image",
          title: sp.title || `图片 #${i + 1}`,
          anchorHeading: sp.anchorHeading || "",
          ratio: sp.ratio || "3:4",
          theme: sp.theme || "",
          subject: sp.subject || sp.recipeSnapshot?.subject || "",
          prompt: skillPrompt,
          imageUrl: imgUrl,
          nodeId: dn?.id,
          recipeSnapshot: sp.recipeSnapshot ? JSON.parse(JSON.stringify(sp.recipeSnapshot)) : null
        };

        if (dn) {
          if (dn.data.pendingTasksBySlot) delete dn.data.pendingTasksBySlot[slotKey];
          const nextPending = Object.values(dn.data.pendingTasksBySlot || {})[0];
          dn.data.pendingTaskId = nextPending?.taskId || "";
          dn.data.pendingRequestId = nextPending?.requestId || "";
          if (dn.data.pendingRequestIds) delete dn.data.pendingRequestIds[currentSlotKey];
          if (dn.data.pendingSpec) {
            delete dn.data.pendingSpec[requestId];
            if (activeReqId) delete dn.data.pendingSpec[activeReqId];
          }
          if (isBatchGallery) {
            if (!Array.isArray(dn.data.items)) dn.data.items = [];
            const existIdx = dn.data.items.findIndex(
              (it) => it && ((it.slotKey && it.slotKey === currentSlotKey) || (it.requestId && it.requestId === requestId))
            );
            if (existIdx >= 0) {
              dn.data.items[existIdx] = builtItem;
            } else {

              dn.data.items[i] = builtItem;

            }
            dn.data.markdown = plan.markdown || "";
            dn.data.updatedAt = nowStr;
            dn.data.runCount = currentRunCount;
            if (completedCount === plan.specs.length && failedCount === 0) {
              dn.data.status = "done";
              dn.data.page = 1;
            }
          } else {
            dn.data.items = [builtItem];
            dn.data.markdown = plan.markdown || "";
            dn.data.updatedAt = nowStr;
            dn.data.runCount = currentRunCount;
            dn.data.status = "done";
            dn.data.activeIdx = 0;
          }
        }

        const existAllIdx = allItems.findIndex(
          (it) => it && ((it.slotKey && it.slotKey === currentSlotKey) || (it.requestId && it.requestId === requestId))
        );
        if (existAllIdx >= 0) {
          allItems[existAllIdx] = builtItem;
        } else {
          allItems.push(builtItem);
        }

        runningIndices.delete(i);
        if (activeLoopNode && resolvedOnlyIdx === null) {
          activeLoopNode.data.currentStep = completedCount;
          activeLoopNode.data.completedCount = completedCount;
          activeLoopNode.data.failedCount = failedCount;
        }
        markActiveTabDirty();
        persistOpenTabs();

        if (window.HandrawBatchCreate) {
          window.HandrawBatchCreate.updateProgress({
            updatedIndex: i,
            itemResult: builtItem,
            completedCount,
            failedCount,
            totalCount: plan.specs.length,
            activeIndex: null,
            activeIndices: Array.from(runningIndices),
            busy: true,
            batchId
          });
        }

        } finally {
          runningIndices.delete(i);
        }
      }
      async function worker() {
        while (nextSlotToLaunch < slotIndexes.length && !batchRun.cancelled && !stopLaunching) {
          const i = slotIndexes[nextSlotToLaunch++];
          await runSlot(i);
        }
      }
      await Promise.all(Array.from({length: Math.min(concurrency, slotIndexes.length)}, () => worker()));
      if (isStaleScope(runEpoch, runScope)) return false;
      const slotPositions = new Map(plan.specs.map((sp, i) => [sp.slotKey || String(i), i]));
      allItems.sort((x, y) =>
        (slotPositions.get(x.slotKey) ?? 9999) - (slotPositions.get(y.slotKey) ?? 9999)
      );

      if (batchRun.cancelled) {
        if (useLiveApi) {
          const notSubmitted = plan.specs
            .map((sp, i) => ({i, key: sp.slotKey || String(i)}))
            .filter(({key}) => !completedSlots.has(key) && !failedSlots.has(key) && !submittedSlots.has(key))
            .map(({i}) => i);
          if (notSubmitted.length) {
            try {
              await S.apiJson(`/api/studio/batches/${encodeURIComponent(batchId)}/cancel-pending`, {
                method: "POST", body: { positions: notSubmitted }
              });
            } catch (error) {
              console.warn("未提交图片的取消状态尚未同步到服务器", error);
            }
          }
        }
        // Local waiting is over. Pending upstream requests are recoverable
        // from the per-slot request IDs stored on the display nodes.
        ctrl.data.status = "stopped";
        for (const dn of dispNodes) {
          if (isBatchGallery) dn.data.status = Array.isArray(dn.data.items) && dn.data.items.length ? "done" : "idle";
          else if (dn.data.status === "generating") dn.data.status = Array.isArray(dn.data.items) && dn.data.items.length ? "done" : "idle";
        }
        if (activeLoopNode && resolvedOnlyIdx === null) {
          activeLoopNode.data.status = "idle";
          activeLoopNode.data.currentStep = completedCount;
          activeLoopNode.data.totalSteps = plan.specs.length;
        }
        if (allItems.length > 0) {
          recordGenerationHistory(ctrl, allItems, plan.kind, plan.markdown, creationSource);
        }
        markActiveTabDirty();
        persistOpenTabs();
        if (window.HandrawBatchCreate) {
          window.HandrawBatchCreate.updateProgress({
            completedCount,
            failedCount,
            totalCount: plan.specs.length,
            activeIndex: null,
            busy: false,
            isStopping: false,
            summaryText: `已停止 · 成功 ${completedCount} 张 · ${submittedSlots.size} 张已提交云端（可能仍在执行）`,
            batchId
          });
        }
        if (!silent) toast(`已停止本地等待并取消后续提交，已完成 ${completedCount} 张已保留；${submittedSlots.size} 张已提交的任务可能仍在云端执行或计费。`);
        return allItems.length > 0;
      }

      const allSucceeded = completedCount === plan.specs.length && failedCount === 0;
      ctrl.data.status = allSucceeded ? "done" : "error";
      for (let idx = 0; idx < dispNodes.length; idx++) {
        const dn = dispNodes[idx];
        if (isBatchGallery) {
          dn.data.status = allSucceeded ? "done" : (completedCount > 0 ? "done" : "error");
        } else {
          const curItem = dn.data.items?.[0];
          if (curItem?.imageUrl) {
            dn.data.status = "done";
          } else if (curItem?.failed || failedSlots.has(plan.specs[idx]?.slotKey || String(idx))) {
            dn.data.status = "error";
          } else {
            dn.data.status = "idle";
          }
        }
      }
      if (activeLoopNode && resolvedOnlyIdx === null) {
        activeLoopNode.data.status = allSucceeded ? "done" : (completedCount > 0 ? "idle" : "error");
        activeLoopNode.data.currentStep = completedCount;
        activeLoopNode.data.totalSteps = plan.specs.length;
      }
      if (allItems.length > 0) {
        recordGenerationHistory(ctrl, allItems, plan.kind, plan.markdown, creationSource);
      }
      markActiveTabDirty();
      persistOpenTabs();

      if (window.HandrawBatchCreate) {
        window.HandrawBatchCreate.updateProgress({
          completedCount,
          failedCount,
          totalCount: plan.specs.length,
          activeIndex: null,
          busy: false,
          isStopping: false,
          batchId
        });
      }

      if (!silent) {
        if (allSucceeded) {
          if (isBatchGallery) {
            toast(`🎉 批量出图完成！全部 ${allItems.length} 张图片已自动收纳进右侧 1 个「批量图集」节点`);
          } else if (plan.kind === "loop" && resolvedOnlyIdx === null) {
            toast(`🔁 循环批量完成！共出图 ${dispNodes.length} 张并自动连接「图片显示」节点`);
          } else {
            toast(`🎉 批量出图完成！已生成 ${completedCount} 张图片`);
          }
        } else {
          if (resolvedOnlyIdx !== null && failedCount > 0 && lastFailureError) {
            toast(`单张生成失败：${lastFailureError}`, "error");
          } else {
            const unexecuted = Math.max(0, plan.specs.length - completedCount - failedCount);
            const parts = [`已完成 ${completedCount} / ${plan.specs.length} 张`];
            if (failedCount > 0) parts.push(`失败 ${failedCount} 张`);
            if (unexecuted > 0) parts.push(`未执行 ${unexecuted} 张`);
            toast(`批量出图未全部完成：${parts.join(" · ")}`, "error");
          }
        }
      }
      return completedCount > 0;
    } catch (err) {
      if (isStaleScope(runEpoch, runScope)) return false;
      console.error("[Studio Generate] batch run exception", err);
      reportUnexpectedRuntimeError(err);
      ctrl.data.status = "error";
      if (activeLoopNode) activeLoopNode.data.status = "idle";
      for (const dn of dispNodes) {
        if (dn.data.status === "generating") dn.data.status = "error";
        delete dn.data.pendingTaskId;
        delete dn.data.pendingRequestId;
        if (err.terminal) {
          if (dn.data.pendingRequestIds && currentSlotKey) {
            delete dn.data.pendingRequestIds[currentSlotKey];
          }
          if (dn.data.pendingSpec && currentReqId) {
            delete dn.data.pendingSpec[currentReqId];
          }
        }
      }
      persistOpenTabs();
      if (window.HandrawBatchCreate) {
        window.HandrawBatchCreate.updateProgress({
          completedCount: 0,
          failedCount: 1,
          totalCount: plan.specs.length,
          activeIndex: null,
          busy: false,
          isStopping: false,
          summaryText: err?.message || "生成失败",
          batchId
        });
      }
      toast(`⚠️ 生成异常：${err.message || err}`);
      return false;
    } finally {
      if (_activeBatchRun === batchRun) {
        _activeBatchRun = null;
        CS.activeBatchRun = null;
      }
      if (controller) _generationControllers.delete(controller);
      clearInterval(timer);
      if (!isStaleScope(runEpoch, runScope)) fullRenderCanvas();
    }
  }

  async function runLoopNode(loopId) {
    const lp = getNodeById(loopId);
    if (!lp || lp.type !== "loop" || lp.data.status === "running") return false;

    const findDownCtrls = () => {
      const direct = CS.graph.edges
        .filter((e) => e.from === lp.id)
        .map((e) => getNodeById(e.to))
        .filter((n) => n && n.type === "output_control");
      if (direct.length) return direct;
      const viaBridges = CS.graph.edges
        .filter((e) => e.from === lp.id)
        .map((e) => getNodeById(e.to))
        .filter((n) => n && n.type === "bridge");
      const out = [];
      for (const b of viaBridges) {
        CS.graph.edges
          .filter((e) => e.from === b.id)
          .map((e) => getNodeById(e.to))
          .filter((n) => n && n.type === "output_control")
          .forEach((c) => {
            if (!out.includes(c)) out.push(c);
          });
      }
      return out;
    };

    let ctrls = findDownCtrls();
    if (!ctrls.length) {
      const selfRec = E.resolveControlRecipe(CS.graph, lp, Catalog);
      const selfIters = E.resolveLoopIterations(CS.graph, lp, selfRec, Catalog);
      if (!selfIters.length) {
        const lm = lp.data?.loopMode || "prompts";
        if (lm === "styles") {
          toast("请先在「循环批量」节点选择至少 1 款画风");
          openLoopMultiPickerModal(lp, "styles");
          return false;
        }
        if (lm === "layouts") {
          toast("请先在「循环批量」节点选择至少 1 款图型");
          openLoopMultiPickerModal(lp, "layouts");
          return false;
        }
        if (lm === "assets") {
          toast("请先在左侧连入包含参考图片的「图片参数」节点");
          return false;
        }
        toast("请先在「循环批量」节点输入至少 1 行文案或主题");
        openLoopPromptsModal(lp.id);
        return false;
      }
      const createdCtrl = spawnDownstreamControlFromLoop(lp.id);
      if (createdCtrl) {
        CS.graph.selectedIds = [lp.id];
        ctrls = [createdCtrl];
      }
    }

    let anyOk = false;
    for (const c of ctrls) {
      const ok = await runOutputControlNode(c.id, { silent: ctrls.length > 1 });
      if (ok) anyOk = true;
    }
    if (ctrls.length > 1 && anyOk) {
      toast(`🔁 已完成全部 ${ctrls.length} 组下游输出控制的循环批量出图！`);
    }
    return anyOk;
  }

  async function regenerateDisplayNode(dispNodeId) {
    const disp = getNodeById(dispNodeId);
    if (!disp || disp.type !== "output_display") return false;
    const upEdge = CS.graph.edges.find((e) => e.to === disp.id);
    const parent = upEdge ? getNodeById(upEdge.from) : null;
    if (parent && parent.type === "article_plan" && disp.data?.planCardId) {
      return await generateSinglePlanCard(parent.id, disp.data.planCardId);
    }
    if (parent && parent.type === "output_control") {
      return await runOutputControlNode(parent.id, { onlyDispNodeId: disp.id });
    }
    const fallbackCtrl = CS.graph.nodes.find((n) => n.type === "output_control");
    if (fallbackCtrl) {
      return await runOutputControlNode(fallbackCtrl.id);
    }
    toast("未找到该图片显示节点关联的上游控制节点");
    return false;
  }

  async function runAllOutputControls() {
    const ctrls = CS.graph.nodes.filter((n) => n.type === "output_control" && n.data.status !== "generating");
    if (!ctrls.length) {
      toast("当前画布暂无「输出控制」节点，请从左侧拖入一个");
      return;
    }
    for (const c of ctrls) {
      await runOutputControlNode(c.id, { silent: ctrls.length > 1 });
    }
    if (ctrls.length > 1) {
      toast(`🎉 已完成全部 ${ctrls.length} 个输出控制节点的运行！`);
    }
  }

  /* ======================== ZIP PACKAGE EXPORT & GENERATION HISTORY MODAL ======================== */
  async function exportZipFromPayload({ kind = "article", title = "Handraw视觉交付包", markdown = "", items = [] }) {
    if (CS.zipExporting) return;
    if (!items.length) {
      toast("暂无已生成的图片可供打包，请先点击运行");
      return;
    }

    let cleanTitle = String(title || "Handraw视觉交付包").replace(/^[^\w\u4e00-\u9fa5]+/, "").trim() || "Handraw交付包";
    if (kind === "article" && markdown) {
      const m = markdown.match(/^#\s+(.+)$/m);
      if (m) cleanTitle = m[1].trim();
    }

    CS.zipExporting = true;
    renderTopAndBottomDocks();
    renderWorldNodes();

    try {
      const buildZip = async () => {
        const resp = await fetch("/api/studio/export-zip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind: kind === "article" ? "article" : kind === "series" || kind === "xhs" ? "xhs" : "images",
            title: cleanTitle,
            markdown,
            items: items.map((it, idx) => ({
              role: it.role === "cover" || (kind === "article" && idx === 0) ? "cover" : "inline",
              title: it.title || `配图 ${idx + 1}`,
              anchorHeading: it.anchorHeading || "",
              theme: it.theme || "",
              prompt: it.prompt || "",
              imageUrl: it.imageUrl || "",
              afterLine: typeof it.afterLine === "number" ? it.afterLine : undefined
            }))
          })
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.blob();
      };
      const blob = window.HandrawTaskJourney?.withActivity
        ? await window.HandrawTaskJourney.withActivity("正在制作图文 ZIP 交付包", buildZip)
        : await buildZip();
      const dlUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const safeSlug = cleanTitle.replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 28) || "handraw-pack";
      a.href = dlUrl;
      a.download = `${safeSlug}-${kind === "article" ? "图文配图包" : "结果包"}.zip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(dlUrl), 5000);
      toast(`📦 已打包下载 ZIP！（含 ${kind === "article" ? "article.md + preview.html + " : ""}images/ 共 ${items.length} 张图）`);
    } catch (err) {
      toast(`⚠️ 打包 ZIP 失败：${err.message || err}`);
    } finally {
      CS.zipExporting = false;
      renderTopAndBottomDocks();
      renderWorldNodes();
    }
  }

  function buildArticlePlanExportPayload(planNode) {
    if (!planNode || planNode.type !== "article_plan") return null;
    const orderedCards = sortPlanCardsInDocOrder(planNode.data.cards || []);
    const readyCards = orderedCards.filter((c) => c.imageUrl);
    if (!readyCards.length) return null;

    const blocks = E.parseArticleReadonlyBlocks(planNode.data.markdown || "", { withLines: true, noStarter: true });
    return {
      kind: "article",
      title: planNode.data.articleTitle || "文章配图方案",
      markdown: planNode.data.markdown || "",
      items: readyCards.map((c) => {
        const isCover = c.role === "cover";
        const anchorBlock =
          typeof c.afterBlockIdx === "number" && c.afterBlockIdx >= 0 && blocks[c.afterBlockIdx]
            ? blocks[c.afterBlockIdx]
            : null;
        const afterLine = isCover ? -1 : (anchorBlock && typeof anchorBlock.endLine === "number" ? anchorBlock.endLine : -1);
        return {
          id: c.id,
          role: isCover ? "cover" : "inline",
          title: c.title || "配图",
          anchorHeading:
            anchorBlock && (anchorBlock.kind === "h1" || anchorBlock.kind === "h2" || anchorBlock.kind === "h3")
              ? anchorBlock.rawMd
              : "",
          ratio: c.ratio || "4:3",
          theme: c.title || "",
          prompt: c.prompt || "",
          imageUrl: c.imageUrl,
          afterLine
        };
      })
    };
  }

  async function exportZipPackage(dispOrCtrlId = null) {
    let targetNode = dispOrCtrlId ? getNodeById(dispOrCtrlId) : null;
    if (!targetNode && dispOrCtrlId) {
      const artTarget = resolveArticleTarget(dispOrCtrlId);
      if (artTarget?.planNode) targetNode = artTarget.planNode;
    }

    if (targetNode && targetNode.type === "article_plan") {
      if (!(targetNode.data.cards || []).some((c) => c.imageUrl)) {
        toast("⚡ 正在自动批量生成配图方案并打包下载 ZIP…");
        await generateBatchPlanCards(dispOrCtrlId || targetNode.id, { silent: true });
      }
      const payload = buildArticlePlanExportPayload(targetNode);
      if (payload) {
        await exportZipFromPayload(payload);
      } else {
        toast("暂无已生成的配图可供导出");
      }
      return;
    }

    if (!dispOrCtrlId && CS.stageView === "preview" && CS.activeArticleId) {
      const artTarget = resolveArticleTarget(CS.activeArticleId);
      if (artTarget?.planNode) {
        if (!(artTarget.planNode.data.cards || []).some((c) => c.imageUrl)) {
          toast("⚡ 正在自动批量生成配图方案并打包下载 ZIP…");
          await generateBatchPlanCards(CS.activeArticleId, { silent: true });
        }
        const payload = buildArticlePlanExportPayload(artTarget.planNode);
        if (payload) {
          await exportZipFromPayload(payload);
          return;
        }
      }
    }

    if (!dispOrCtrlId) {
      const activePlan =
        (CS.activePlanNodeId && getNodeById(CS.activePlanNodeId)) ||
        CS.graph.nodes.find((n) => n.type === "article_plan");
      if (activePlan && activePlan.type === "article_plan") {
        if (!(activePlan.data.cards || []).some((c) => c.imageUrl)) {
          toast("⚡ 正在自动批量生成配图方案并打包下载 ZIP…");
          await generateBatchPlanCards(activePlan.id, { silent: true });
        }
        const payload = buildArticlePlanExportPayload(activePlan);
        if (payload) {
          await exportZipFromPayload(payload);
          return;
        }
      }
    }

    if (targetNode && targetNode.type === "output_control") {
      if (!getDownstreamDisplayNodes(targetNode.id).some((d) => d.data?.items?.length)) {
        await runOutputControlNode(targetNode.id, { silent: true });
      }
      const planChild = getDownstreamArticlePlanNode(targetNode);
      if (planChild) {
        const payload = buildArticlePlanExportPayload(planChild);
        if (payload) await exportZipFromPayload(payload);
        return;
      }
      const sibItems = getDownstreamDisplayNodes(targetNode.id).flatMap((d) => d.data?.items || []);
      if (sibItems.length) {
        const curTab = CS.tabs.find((t) => t.id === CS.activeTabId);
        await exportZipFromPayload({
          kind: targetNode.data?.mode === "series" ? "series" : "images",
          title: curTab ? curTab.title : "Handraw交付包",
          markdown: "",
          items: sibItems
        });
        return;
      }
    }

    if (targetNode && targetNode.type === "output_display") {
      const upEdge = CS.graph.edges.find((e) => e.to === targetNode.id);
      const upNode = upEdge ? getNodeById(upEdge.from) : null;
      const sibItems = upNode ? getDownstreamDisplayNodes(upNode.id).flatMap((d) => d.data?.items || []) : targetNode.data?.items || [];
      if (sibItems.length) {
        const curTab = CS.tabs.find((t) => t.id === CS.activeTabId);
        await exportZipFromPayload({
          kind: upNode?.data?.mode === "series" ? "series" : "images",
          title: curTab ? curTab.title : "Handraw交付包",
          markdown: targetNode.data?.markdown || "",
          items: sibItems
        });
        return;
      }
    }

    let allDispItems = CS.graph.nodes
      .filter((n) => n.type === "output_display" && n.data?.items?.length)
      .sort((a, b) => a.y - b.y)
      .flatMap((n) => n.data.items || []);

    if (!allDispItems.length) {
      const allCtrls = CS.graph.nodes.filter((n) => n.type === "output_control");
      if (allCtrls.length) {
        toast("⚡ 正在自动运行并打包下载 ZIP…");
        for (const c of allCtrls) {
          await runOutputControlNode(c.id, { silent: true });
        }
        const planAfter = CS.graph.nodes.find((n) => n.type === "article_plan" && (n.data.cards || []).some((c) => c.imageUrl));
        if (planAfter) {
          const payload = buildArticlePlanExportPayload(planAfter);
          if (payload) {
            await exportZipFromPayload(payload);
            return;
          }
        }
        allDispItems = CS.graph.nodes
          .filter((n) => n.type === "output_display" && n.data?.items?.length)
          .sort((a, b) => a.y - b.y)
          .flatMap((n) => n.data.items || []);
      }
    }

    if (!allDispItems.length) {
      toast("暂无可导出的输出结果");
      return;
    }
    const curTab = CS.tabs.find((t) => t.id === CS.activeTabId);
    const hasSeriesCtrl = CS.graph.nodes.some((n) => n.type === "output_control" && n.data?.mode === "series");
    await exportZipFromPayload({
      kind: hasSeriesCtrl ? "series" : "images",
      title: curTab ? curTab.title : "Handraw交付包",
      markdown: "",
      items: allDispItems
    });
  }

  function openImageLightbox(url, title = "高清成图预览") {
    if (!url) return;
    S.openModal({
      title: `🔍 ${title}`,
      sizeClass: "modal-medium",
      html: `
        <div class="hw-modal-lightbox-container" style="gap:12px;">
          <a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="点击查看原图" style="display:block;max-width:100%;">
            <img src="${esc(url)}" class="hw-modal-lightbox-img" alt="${esc(title)}" />
          </a>
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:center;">
            <a class="btn btn-sm btn-primary" href="${esc(url)}" download="handraw-output.webp">⬇️ 下载高清原图</a>
            <a class="btn btn-sm" href="${esc(url)}" target="_blank" rel="noopener noreferrer">↗️ 查看原图</a>
          </div>
        </div>
      `
    });
  }

  function createSeededGenerationHistory() {
    const now = Date.now();
    const hour = 3600 * 1000;
    const fmt = (ms) => {
      const d = new Date(ms);
      const tShort = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const dFull = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${tShort}`;
      return { timeShort: tShort, createdAt: dFull };
    };

    const rawSeeds = [
      {
        id: "hist_seed_01",
        hoursAgo: 1.5,
        tabTitle: "图文与海报创作",
        subject: "秋分茶会主题手绘海报",
        mode: "poster",
        modeLabel: "视觉海报 · 1 张",
        kind: "single",
        recipeSummary: "画风 #FA-003 · 图型 #SC-023 · 色板 #C-08 · 3:4",
        prompt: "【视觉海报主画面】：采用 #FA-003 社论水彩手绘线条与 #SC-023 东方节气海报构图，描绘秋分傍晚清朗山居茶席，留白 55%，标题墨字『一半清朗，一半从容』。",
        markdown: "",
        items: [
          {
            id: "hi_01_1",
            title: "秋分茶会主题手绘海报",
            subject: "秋分茶会主题手绘海报",
            ratio: "3:4",
            prompt: "秋分傍晚清朗山居茶席，东方宣纸水彩手绘海报，留白呼吸感构图。",
            imageUrl: "/images/poster-demo-autumn-equinox.webp"
          }
        ]
      },
      {
        id: "hist_seed_02",
        hoursAgo: 4.2,
        tabTitle: "套图创作",
        subject: "职场效率反常识图解卡",
        mode: "series",
        modeLabel: "系列套图 · 4 张",
        kind: "series",
        recipeSummary: "画风 #FA-001 · 图型 #SC-025 · 色板 #C-21 · 3:4 · 套图 4 张",
        prompt: "【系列套图统一视觉母本】：采用 #FA-001 怪萌冷脸涂鸦与 #SC-025 社媒知识卡版式，统一暖米纸底与朱砂重点色，连续输出 4 张职场效率反常识图解卡。",
        markdown: "",
        items: [
          { id: "hi_02_1", title: "套图 P1 · 封面钩子卡", ratio: "3:4", imageUrl: "/images/A_001-016.webp" },
          { id: "hi_02_2", title: "套图 P2 · 核心痛点拆解", ratio: "3:4", imageUrl: "/images/graphic-text-mode-demo.webp" },
          { id: "hi_02_3", title: "套图 P3 · 三步落地清单", ratio: "3:4", imageUrl: "/images/layouts/social-cards/SC-006.webp" },
          { id: "hi_02_4", title: "套图 P4 · 总结收藏卡", ratio: "3:4", imageUrl: "/images/layouts/social-cards/SC-024.webp" }
        ]
      },
      {
        id: "hist_seed_03",
        hoursAgo: 7.5,
        tabTitle: "文章自动配图",
        articleTitle: "视觉笔记为什么能让人一眼记住核心逻辑？",
        subject: "视觉笔记为什么能让人一眼记住核心逻辑？",
        mode: "article-illust",
        modeLabel: "文章配图 · 3 张",
        kind: "article",
        recipeSummary: "画风 #FA-003 · 图型 #IG-003 · 封面 2.35:1 + 插图 4:3",
        prompt: "【文章封面视觉焦点】：围绕《视觉笔记为什么能让人一眼记住核心逻辑？》创作 2.35:1 宽幅手绘封面，搭配 2 张 4:3 章节信息图插图。",
        markdown: "# 视觉笔记为什么能让人一眼记住核心逻辑？\n\n手绘视觉笔记并不是简单的装饰，而是把抽象关系翻译成空间秩序。\n\n## 一、用空间位置替代冗长连接词\n\n## 二、手绘不完美感反而消解阅读防御",
        items: [
          { id: "hi_03_1", role: "cover", title: "文章封面", ratio: "2.35:1", imageUrl: "/images/poster-demo-autumn-equinox.webp" },
          { id: "hi_03_2", role: "inline", title: "插图 1 · 空间位置替代连接词", ratio: "4:3", imageUrl: "/images/H_217-232.webp" },
          { id: "hi_03_3", role: "inline", title: "插图 2 · 消解阅读防御", ratio: "4:3", imageUrl: "/images/individual/FA/FA-003.webp" }
        ]
      },
      {
        id: "hist_seed_04",
        hoursAgo: 12.8,
        tabTitle: "图文与海报创作",
        subject: "手绘科普图鉴",
        mode: "graphic-text",
        modeLabel: "图文创作 · 2 张",
        kind: "multi",
        recipeSummary: "画风 #FB-031 · 图型 #IG-005 · 色板 #C-12 · 4:3 · 2 张",
        prompt: "【手绘知识信息图】：采用 #FB-031 暖调水彩科普风与 #IG-005 解剖图鉴构图，清晰标注各模块名称与手写引线注释。",
        markdown: "",
        items: [
          { id: "hi_04_1", title: "图文方案 #1 · 手绘科普图鉴", ratio: "4:3", imageUrl: "/images/layouts/infographics/IG-005.webp" },
          { id: "hi_04_2", title: "图文方案 #2 · 暖纸重点卡片", ratio: "4:3", imageUrl: "/images/B_036-048.webp" }
        ]
      },
      {
        id: "hist_seed_05",
        hoursAgo: 19.4,
        tabTitle: "双画风融合",
        subject: "跨界续绘双拼插画",
        mode: "illustration",
        modeLabel: "纯绘插画 · 1 张",
        kind: "single",
        recipeSummary: "双画风 #FB-022 + #FX-001 · 图型 #SC-021 · 3:4",
        prompt: "【双画风跨界续绘】：上方纪实光影与下方暖宣纸水彩无缝衔接，水波跨过中线化作手绘溪流与林间灯火。",
        markdown: "",
        items: [
          { id: "hi_05_1", title: "跨界续绘双拼插画", ratio: "3:4", imageUrl: "/images/layouts/social-cards/SC-021.webp" }
        ]
      },
      {
        id: "hist_seed_06",
        hoursAgo: 27.0,
        tabTitle: "图文与海报创作",
        subject: "创作者灵感四格分镜",
        mode: "storyboard",
        modeLabel: "分镜漫画 · 1 张",
        kind: "single",
        recipeSummary: "画风 #FA-013 · 图型 #SC-024 · 情绪 幽默 · 4:3",
        prompt: "【多格故事分镜】：采用 #FA-013 独立叙事插画风绘制四格漫画，展现独立创作者从灵感枯竭到散步顿悟的反转瞬间。",
        markdown: "",
        items: [
          { id: "hi_06_1", title: "创作者灵感四格分镜", ratio: "4:3", imageUrl: "/images/H_217-232.webp" }
        ]
      },
      {
        id: "hist_seed_07",
        hoursAgo: 35.5,
        tabTitle: "角色资产设定",
        subject: "黑猫侍者 IP 设定卡",
        mode: "ip-design",
        modeLabel: "IP角色设定 · 1 张",
        kind: "single",
        recipeSummary: "画风 #FB-031 · 角色参考 #CH-001 · 1:1",
        prompt: "【IP角色三视图与表情包设定】：黑猫侍者形象设定表，含正侧背三视图、托盘道具特写与 3 组日常微表情。",
        markdown: "",
        items: [
          { id: "hi_07_1", title: "黑猫侍者 IP 设定卡", ratio: "1:1", imageUrl: "/images/characters/CH-001.webp" }
        ]
      },
      {
        id: "hist_seed_08",
        hoursAgo: 46.2,
        tabTitle: "文章自动配图",
        articleTitle: "手账感排版指南：网格、胶带与手写批注的分寸感",
        subject: "手账感排版指南：网格、胶带与手写批注的分寸感",
        mode: "article-illust",
        modeLabel: "文章配图 · 2 张",
        kind: "article",
        recipeSummary: "画风 #FB-031 · 图型 #SC-006 · 封面 2.35:1 + 插图 4:3",
        prompt: "【手账感专栏配图】：水彩森林色调封面搭配手账胶带批注风格章节插图。",
        markdown: "# 手账感排版指南：网格、胶带与手写批注的分寸感\n\n手账风深受读者喜爱，是因为它保留了真人思考的痕迹。\n\n## 一、批注只加在真正反直觉的句子旁",
        items: [
          { id: "hi_08_1", role: "cover", title: "文章封面 · 森林手账", ratio: "2.35:1", imageUrl: "/images/individual/FB/FB-031.webp" },
          { id: "hi_08_2", role: "inline", title: "插图 1 · 手账网格批注", ratio: "4:3", imageUrl: "/images/layouts/social-cards/SC-006.webp" }
        ]
      }
    ];

    return rawSeeds.map((s) => {
      const t = fmt(now - s.hoursAgo * hour);
      return {
        id: s.id,
        createdAt: t.createdAt,
        timeShort: t.timeShort,
        tabTitle: s.tabTitle,
        subject: s.subject || "",
        articleTitle: s.articleTitle || "",
        ctrlId: "",
        dispId: "",
        mode: s.mode,
        modeLabel: s.modeLabel,
        kind: s.kind,
        engine: "demo",
        demoMode: true,
        recipeSummary: s.recipeSummary,
        prompt: s.prompt,
        markdown: s.markdown,
        items: (s.items || []).map((it) => ({
          ...it,
          subject: it.subject || s.subject || "",
          articleTitle: it.articleTitle || s.articleTitle || ""
        }))
      };
    });
  }

  function ensureGenerationHistoryInitialized() {
    if (Array.isArray(CS.generationHistory)) return;
    CS.generationHistory = isExplicitDemoMode() ? createSeededGenerationHistory() : [];
    writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
  }

  function openHistoryPage() {
    void ensureWorkspaceCollection("history").then(()=>{if(CS.stageView==="history") renderHistoryStage();});
    if (CS.stageView === "history") return;
    flushUnifiedArticleEditor();
    CS.historyReturnStage = CS.stageView;
    CS.historyReturnUrl = window.location.pathname + window.location.search;
    CS.stageView = "history";
    const url = new URL(window.location.href);
    url.search = "?view=history";
    window.history.replaceState(null, "", url.pathname + url.search);
    renderTopAndBottomDocks();
  }

  function returnFromHistoryPage() {
    if (CS.stageView !== "history") return;
    CS.stageView = ["quick", "batch", "canvas", "preview", "article", "workflows"].includes(CS.historyReturnStage)
      ? (CS.historyReturnStage === "article" ? "preview" : CS.historyReturnStage)
      : "quick";
    window.history.replaceState(null, "", CS.historyReturnUrl || (window.location.pathname + "?entry=quick"));
    renderTopAndBottomDocks();
  }

  function openHistoryModal() {
    openHistoryPage();
  }

  async function restoreHistoryEntryToCanvas(entryId) {
    ensureGenerationHistoryInitialized();
    const h = (CS.generationHistory || []).find(item => item.id === entryId);
    if (!h || h.creationSource !== "canvas") return;
    if (!h.runId) {
      toast("旧工作流记录保留在存档中，可导出原文件或显式转换为独立参数画布");
      return;
    }
    switchCreationStage("canvas");
    try { await window.HandrawParameterCanvas?.openRun(h.runId); }
    catch (error) { toast(error.message || "批次载入失败，请重试"); }
  }

  function resolveShareTitle(h, item = null, options = {}) {
    // 1. 用户明确编辑的作品标题
    if (options && options.customTitle) {
      const ct = String(options.customTitle).trim();
      if (ct) return ct;
    }
    if (options && (options.isCustomTitle || options.titleSource === "manual") && options.title) {
      const ot = String(options.title).trim();
      if (ot) return ot;
    }
    const chosenItem = item || (h && Array.isArray(h.items) && h.items[0]) || null;
    if (chosenItem && (chosenItem.isCustomTitle || chosenItem.titleSource === "manual") && chosenItem.title) {
      const itTitle = String(chosenItem.title).trim();
      if (itTitle) return itTitle;
    }
    if (h && (h.isCustomTitle || h.titleSource === "manual") && h.title) {
      const ht = String(h.title).trim();
      if (ht) return ht;
    }

    // 2. 所选图片生成时的 subject
    const itemSubj = String(chosenItem?.subject || "").trim();
    if (itemSubj) return itemSubj;
    const entrySubj = String(h?.subject || "").trim();
    if (entrySubj) return entrySubj;

    // 3. 配方快照的 subject
    const itemRecipeSubj = String(chosenItem?.recipeSnapshot?.subject || "").trim();
    if (itemRecipeSubj) return itemRecipeSubj;
    const entryRecipeSubj = String(h?.recipeSnapshot?.subject || "").trim();
    if (entryRecipeSubj) return entryRecipeSubj;

    // 4. 文章标题
    const artTitle = String(
      h?.articleTitle ||
      chosenItem?.articleTitle ||
      options?.articleTitle ||
      h?.planNode?.data?.articleTitle ||
      (h?.markdown ? (String(h.markdown).match(/^#\s+(.+)$/m)?.[1] || "") : "") ||
      ""
    ).trim();
    if (artTitle) return artTitle;

    // 5. 「未命名作品」，允许分享前编辑
    return "未命名作品";
  }

  async function deleteCloudHistory(id, all = false) {
    if (!App.state || !App.state.serverBacked) return { ok: true };
    if (!App.state.loggedIn) throw new Error("登录后才能管理云端生图历史");
    const response = await fetch("/api/studio/history/delete", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(all ? { all: true } : { id })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `删除历史失败（HTTP ${response.status}）`);
    return data;
  }

  function historyRecordCategory(h) {
    const explicit = String(h.creationSource || "").toLowerCase();
    if (["quick", "batch", "article", "canvas", "other"].includes(explicit)) return explicit;
    // Older records did not persist an entry-point field: infer only from
    // reliable metadata. "graphic-text" and "3:4" describe output, not a canvas.
    const mode = String(h.mode || "").toLowerCase().replace(/_/g, "-");
    const kind = String(h.kind || "").toLowerCase();
    const label = `${h.modeLabel || ""} ${h.tabTitle || ""}`;
    if (["article-illust", "article-cover"].includes(mode) || kind === "article" ||
        h.articleTitle || /文章封面|文章配图|文章插图/.test(label) ||
        kind === "cover" || (Array.isArray(h.items) && h.items.length === 1 &&
          (h.items[0]?.role === "cover" || /封面/.test(String(h.items[0]?.title || ""))))) return "article";
    if (["loop", "series", "batch"].includes(kind) || ["series", "batch"].includes(mode) ||
        /循环批量|批量|套图/.test(label)) return "batch";
    if (h.recipeId || h.tabTitle === "做图配方" || /^rcp_/.test(String(h.requestId || ""))) return "quick";
    // A node ID is not proof of canvas origin: quick/batch forms also run graph nodes.
    return "other";
  }

  function historyImageCount(h) {
    return (Array.isArray(h.items) ? h.items : []).filter((it) => it && it.imageUrl).length;
  }

  function historyStatusCategory(h) {
    const status = String(h.status || "success").toLowerCase();
    if (["queued", "running", "pending", "generating"].includes(status)) return "active";
    if (["success", "completed", "done"].includes(status)) return "success";
    return "failed";
  }

  function historySearchText(h) {
    const snapshot = h.recipeSnapshot && typeof h.recipeSnapshot === "object" ? h.recipeSnapshot : {};
    const parts = [h.id, h.subject, h.title, h.tabTitle, h.mode, h.modeLabel, h.createdAt,
      h.created_at, h.recipeSummary, h.articleTitle, h.status, h.requestId,
      h.promptMasked ? "" : h.prompt,
      snapshot.subject, snapshot.layout, snapshot.layoutId, snapshot.layout_id,
      ...(Array.isArray(snapshot.styles) ? snapshot.styles : []),
      ...(Array.isArray(snapshot.styleIds) ? snapshot.styleIds : []),
      ...(Array.isArray(snapshot.style_ids) ? snapshot.style_ids : [])];
    for (const it of h.items || []) parts.push(it.title, it.subject, it.ratio, it.id);
    return parts.filter(Boolean).join(" ").toLowerCase();
  }

  function renderHistoryStage() {
    if (!DOM.historyStage) return;
    if (CS.stageView !== "history") {
      DOM.historyStage.style.display = "none";
      return;
    }
    DOM.historyStage.style.display = "flex";
    ensureGenerationHistoryInitialized();

    const wasSearchFocused = document.activeElement && document.activeElement.id === "hist-search-inp";
    const prevScrollTop = DOM.historyStage.querySelector("#hist-page-scroll")?.scrollTop || 0;
    const allHist = CS.generationHistory || [];
    const filterMode = CS.historyFilter || "all";
    const statusFilter = CS.historyStatusFilter || "all";
    const imageCounts = { all: 0, quick: 0, batch: 0, article: 0, canvas: 0, other: 0 };
    for (const history of allHist) {
      const amount = historyImageCount(history);
      imageCounts.all += amount;
      imageCounts[historyRecordCategory(history)] += amount;
    }
    const q = String(CS.historyQuery || "").trim().toLowerCase();

    const filtered = allHist.filter((h) => {
      if (filterMode !== "all" && historyRecordCategory(h) !== filterMode) return false;
      if (statusFilter !== "all" && historyStatusCategory(h) !== statusFilter) return false;
      if (q && !q.split(/\s+/).every((part) => historySearchText(h).includes(part))) return false;
      return true;
    });
    if (CS.historySort === "oldest") filtered.reverse();

    const PAGE_SIZE = 72;
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (CS.historyPage > totalPages) CS.historyPage = totalPages;
    if (CS.historyPage < 1) CS.historyPage = 1;
    const curPage = CS.historyPage;
    const pageItems = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);

    DOM.historyStage.innerHTML = `
      <div class="ic-pv-topbar ic-history-topbar">
        <div style="display:flex;align-items:center;gap:10px;min-width:0;">
          <span style="font-size:14px;font-weight:900;color:var(--ic-ink);">🕒 生图历史 · ${imageCounts.all} 张</span>
          <span style="font-size:12px;color:var(--ic-muted);" class="hide-sm">已载入 ${allHist.length} 次生成 · 按分类查看图片张数</span>
        </div>

        <div class="ic-history-controls">
          <div class="ic-view-seg">
            <button type="button" class="ic-view-seg-btn ${filterMode === "all" ? "is-active" : ""}" data-hist-filter="all">全部 (${imageCounts.all})</button>
            <button type="button" class="ic-view-seg-btn ${filterMode === "quick" ? "is-active" : ""}" data-hist-filter="quick">做图 (${imageCounts.quick})</button>
            <button type="button" class="ic-view-seg-btn ${filterMode === "batch" ? "is-active" : ""}" data-hist-filter="batch">批量 (${imageCounts.batch})</button>
            <button type="button" class="ic-view-seg-btn ${filterMode === "article" ? "is-active" : ""}" data-hist-filter="article">文章配图 (${imageCounts.article})</button>
            <button type="button" class="ic-view-seg-btn ${filterMode === "canvas" ? "is-active" : ""}" data-hist-filter="canvas">画布 (${imageCounts.canvas})</button>
            ${imageCounts.other ? `<button type="button" class="ic-view-seg-btn ${filterMode === "other" ? "is-active" : ""}" data-hist-filter="other">其他来源 (${imageCounts.other})</button>` : ""}
          </div>
          <input
            type="search"
            class="hw-input"
            id="hist-search-inp"
            value="${esc(CS.historyQuery || "")}"
            placeholder="搜索日期、名称、画风、图型或比例…"
            aria-label="搜索生图历史"
            style="width:220px;height:32px;padding:4px 10px;font-size:12.5px;"
          />
          <select id="hist-status-filter" class="hw-input" aria-label="生成状态筛选" style="height:32px;font-size:12px;">
            <option value="all" ${statusFilter === "all" ? "selected" : ""}>所有状态</option>
            <option value="success" ${statusFilter === "success" ? "selected" : ""}>生成成功</option>
            <option value="active" ${statusFilter === "active" ? "selected" : ""}>进行中</option>
            <option value="failed" ${statusFilter === "failed" ? "selected" : ""}>失败</option>
          </select>
          <select id="hist-sort" class="hw-input" aria-label="历史记录排序" style="height:32px;font-size:12px;">
            <option value="newest" ${CS.historySort !== "oldest" ? "selected" : ""}>最新优先</option>
            <option value="oldest" ${CS.historySort === "oldest" ? "selected" : ""}>最早优先</option>
          </select>
        </div>
      </div>

      <div class="ic-hist-page-scroll" id="hist-page-scroll">
        <div class="ic-hist-page-inner">
          ${
            pageItems.length === 0
              ? `
                <div style="padding:76px 24px;text-align:center;background:var(--ic-panel-solid);border:1px dashed var(--ic-border-strong);border-radius:18px;">
                  <div style="font-size:34px;margin-bottom:10px;">🕒</div>
                  <div style="font-size:16px;font-weight:850;color:var(--ic-ink);margin-bottom:6px;">${
                    allHist.length === 0 ? "暂无生成历史记录" : "没有匹配当前筛选条件的历史记录"
                  }</div>
                  <div style="font-size:13px;color:var(--ic-muted);margin-bottom:18px;">在做图、批量、文章配图或画布生成后，可以在此查找历史记录。</div>
                </div>
              `
              : `
                <div class="ic-hist-masonry-grid" id="hist-records-list">
                  ${pageItems
                    .map((h) => {
                      const promptExpanded = Boolean(CS.historyExpandedPromptIds[h.id]);
                      const selImgIdx =
                        typeof CS.historySelectedPreview[h.id] === "number" ? CS.historySelectedPreview[h.id] : -1;
                      const selImgItem =
                        selImgIdx >= 0 && (h.items || [])[selImgIdx] ? (h.items || [])[selImgIdx] : null;
                      const cleanPromptOneLine = String(S.filterDisplayPrompt ? S.filterDisplayPrompt(h.prompt || "") : (h.prompt || "")).replace(/\s+/g, " ").trim();
                      const coverIdx = (h.items || []).findIndex((it) => it && it.imageUrl);
                      const coverItem = coverIdx < 0 ? null : h.items[coverIdx];
                      const imageCount = historyImageCount(h);
                      const batchExpanded = Boolean(CS.historyExpandedBatchIds[h.id]);
                      const workId = String(h.workId || coverItem?.workId || "").trim();
                      const detailHref = workId && S.channelUrl ? S.channelUrl("main", { view: "work", id: workId }) : "";

                      return `
                        <article class="ic-hist-entry-card" data-hist-id="${esc(h.id)}">
                          <div class="ic-hist-entry-head">
                            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;">
                              <span class="ic-hist-category-chip">${esc(({ quick: "做图", batch: "批量", article: "文章配图", canvas: "画布", other: "其他来源" })[historyRecordCategory(h)])}</span>
                              <span class="ic-node-badge ${h.kind === "loop" ? "ic-badge-loop" : "ic-badge-output-ctrl"}">${esc(h.modeLabel || "生成记录")}</span>
                              ${h.demoMode || h.engine === "demo" ? '<span class="ic-node-badge" style="background:#fff4d6;color:#8a5a00;border:1px solid #e8c46a;">🧪 演示样图</span>' : ""}
                              <strong style="font-size:14.5px;font-weight:850;color:var(--ic-ink);">${esc(h.subject || h.title || h.tabTitle || "画布工作流")}</strong>
                              <span class="ic-hist-status is-${historyStatusCategory(h)}">${historyStatusCategory(h) === "success" ? "生成成功" : historyStatusCategory(h) === "active" ? "进行中" : "未完成"}</span>
                              <span style="font-size:12px;color:var(--ic-muted);">${(h.items || []).length} 张</span>
                              <span style="font-size:12px;color:var(--ic-muted);font-family:var(--font-mono);">${esc(h.createdAt || "")}</span>
                              <span style="font-size:12px;color:var(--ic-muted);">· ${esc(h.recipeSummary || "自由生图")}</span>
                            </div>

                            <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
                              ${h.recipeId && historyRecordCategory(h) === "quick" ? `<button type="button" class="btn btn-sm btn-primary" data-hist-redo-recipe="${esc(h.recipeId)}" style="font-weight:800;">使用原配方</button>` : historyRecordCategory(h) === "canvas" ? `<button type="button" class="btn btn-sm btn-primary" data-hist-restore="${esc(h.id)}" style="font-weight:800;">查看批次</button>` : historyRecordCategory(h) !== "other" ? `<button type="button" class="btn btn-sm btn-primary" data-hist-open-mode="${historyRecordCategory(h)}" style="font-weight:800;">${({quick: "去做图", batch: "去批量", article: "去文章配图"})[historyRecordCategory(h)]}</button>` : ""}
                              ${detailHref && imageCount > 1 ? `<button type="button" class="btn btn-sm" data-hist-expand-batch="${esc(h.id)}" aria-expanded="${batchExpanded}">${batchExpanded ? "收起图片" : `展开全部 ${imageCount} 张`}</button>` : ""}
                              <button type="button" class="btn btn-sm" data-hist-zip="${esc(h.id)}" ${!(h.items || []).some((it) => it.imageUrl) ? "disabled" : ""} style="color:#1f6f4a;border-color:rgba(31,111,74,0.35);font-weight:750;">📦 下载 ZIP</button>
                              <button type="button" class="btn btn-sm" data-hist-del="${esc(h.id)}" style="color:#dc2626;" title="删除此条历史记录">🗑️ 删除</button>
                            </div>
                          </div>

                          ${coverItem ? `
                            <div class="ic-hist-cover">
                              ${detailHref
                                  ? `<a class="ic-hist-cover-button" href="${esc(detailHref)}" target="_blank" rel="noopener noreferrer" aria-label="新标签查看作品详情">`
                                  : `<button type="button" class="ic-hist-cover-button" ${imageCount > 1
                                    ? `data-hist-expand-batch="${esc(h.id)}" aria-expanded="${batchExpanded}" aria-label="${batchExpanded ? "收起" : "展开"}全部 ${imageCount} 张图片"`
                                    : `data-hist-img-toggle="${esc(h.id)}" data-hist-img-idx="${coverIdx}" aria-label="预览生成图片"`}>`}
                                 <img data-hw-src="${esc(coverItem.imageUrl)}" alt="${esc(coverItem.title || h.subject || "生成图片")}" loading="lazy" />
                                 ${imageCount > 1 ? `<span class="ic-hist-cover-count">${imageCount} 张 · ${detailHref ? "查看作品详情" : batchExpanded ? "收起图片" : "查看全部"}</span>` : ""}
                                 ${detailHref ? "</a>" : "</button>"}
                              <a href="${esc(coverItem.imageUrl)}" class="ic-hist-cover-download" data-hist-image-download download="handraw-history.webp" aria-label="下载封面或首张生成图片">↓ 下载</a>
                            </div>
                          ` : `<div class="ic-hist-no-image">暂无可预览的图片</div>`}
                          ${batchExpanded && imageCount > 1 ? `
                          <div class="ic-hist-gallery ic-hist-expanded-gallery">
                            ${(h.items || [])
                              .map(
                                (it, iIdx) => `
                                  <div
                                    class="ic-hist-img-tile ${selImgIdx === iIdx ? "is-selected" : ""}"
                                    ${detailHref ? "" : `data-hist-img-toggle="${esc(h.id)}" data-hist-img-idx="${iIdx}"`}
                                    title="${detailHref ? "新标签打开作品详情" : "点击在页内展开/收起大图预览"}"
                                  >
                                    ${detailHref ? `<a class="ic-hist-tile-detail" href="${esc(detailHref)}" target="_blank" rel="noopener noreferrer" aria-label="新标签查看作品详情">` : ""}
                                     <img data-hw-src="${esc(it.imageUrl)}" alt="${esc(it.title || `成图 ${iIdx + 1}`)}" loading="lazy" />
                                    ${it.ratio ? `<span class="ic-hist-img-badge">${esc(it.ratio)}</span>` : ""}
                                    <div class="ic-hist-img-caption">${esc(it.title || `成图 #${iIdx + 1}`)}</div>
                                     ${detailHref ? "</a>" : ""}
                                    <a href="${esc(it.imageUrl)}" class="ic-hist-img-download" data-hist-image-download download="handraw-${iIdx + 1}.webp" aria-label="下载第 ${iIdx + 1} 张图片">↓ 下载</a>
                                  </div>
                                `
                              )
                              .join("")}
                          </div>
                          ` : ""}
                          ${
                            selImgItem
                              ? `
                                <div class="ic-hist-inline-preview">
                                  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
                                    <span style="font-size:12.5px;font-weight:800;color:var(--ic-ink);">🔍 页内高清预览：${esc(
                                      selImgItem.title || "历史成图"
                                    )}${selImgItem.ratio ? ` (${esc(selImgItem.ratio)})` : ""}</span>
                                    <div style="display:flex;gap:8px;align-items:center;">
                                      <a class="btn btn-sm btn-primary" href="${esc(selImgItem.imageUrl)}" download="handraw-history.webp">⬇️ 下载原图</a>
                                      <button type="button" class="btn btn-sm" data-hist-close-preview="${esc(h.id)}">收起预览 ✕</button>
                                    </div>
                                  </div>
                                  <img src="${esc(selImgItem.imageUrl)}" alt="${esc(selImgItem.title || "高清预览")}" />
                                </div>
                              `
                              : ""
                          }

                          ${
                            cleanPromptOneLine
                              ? `
                                <div class="ic-hist-prompt-bar">
                                  <span class="ic-hist-prompt-snippet"><strong>提示词：</strong>${esc(cleanPromptOneLine)}</span>
                                  <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
                                    <button type="button" class="btn btn-sm" data-hist-copy-prompt="${esc(h.id)}" style="padding:2px 8px;font-size:11.2px;">📋 复制</button>
                                    <button type="button" class="btn btn-sm" data-hist-toggle-prompt="${esc(h.id)}" style="padding:2px 8px;font-size:11.2px;">
                                      ${promptExpanded ? "收起提示词 ▴" : "展开提示词 ▾"}
                                    </button>
                                  </div>
                                </div>
                                ${promptExpanded ? `<div class="ic-hist-prompt-full">${esc(S.filterDisplayPrompt ? S.filterDisplayPrompt(h.prompt || "") : (h.prompt || ""))}</div>` : ""}
                              `
                              : ""
                          }
                        </article>
                      `;
                    })
                    .join("")}
                </div>

                <div class="ic-art-pagination" id="hist-pagination">
                  <button type="button" class="btn btn-sm" data-hist-page="${curPage - 1}" ${curPage <= 1 ? "disabled" : ""}>‹ 上一页</button>
                  ${Array.from({ length: totalPages }, (_, i) => i + 1)
                    .map(
                      (p) =>
                        `<button type="button" class="btn btn-sm ${p === curPage ? "btn-primary" : ""}" data-hist-page="${p}" style="min-width:34px;font-weight:800;">${p}</button>`
                    )
                    .join("")}
                  <button type="button" class="btn btn-sm" data-hist-page="${curPage + 1}" ${curPage >= totalPages ? "disabled" : ""}>下一页 ›</button>
                  <span style="font-size:12px;color:var(--ic-muted);margin-left:6px;">第 ${curPage} / ${totalPages} 页 · 共 ${filtered.length} 条记录</span>
                </div>
              `
          }
          ${CS.historyError?`<p role="alert">${esc(CS.historyError)}</p>`:""}
          ${CS.historyCursor?`<button type="button" class="btn btn-sm" data-hist-more ${CS.historyLoading?"disabled":""}>${CS.historyLoading?"正在载入…":"加载更早的记录"}</button>`:CS.historyError?'<button type="button" class="btn btn-sm" data-hist-reload>重新载入云端记录</button>':""}
        </div>
      </div>
    `;

    DOM.historyStage.querySelector("[data-hist-more]")?.addEventListener("click",()=>{void loadMoreStudioHistory();});
    DOM.historyStage.querySelector("[data-hist-reload]")?.addEventListener("click",()=>{
      void ensureWorkspaceCollection("history").then(()=>{if(CS.stageView==="history") renderHistoryStage();});
    });
    const scBeforeFocus = DOM.historyStage.querySelector("#hist-page-scroll");
    if (scBeforeFocus && prevScrollTop) scBeforeFocus.scrollTop = prevScrollTop;
    if (wasSearchFocused) {
      const inp = DOM.historyStage.querySelector("#hist-search-inp");
      if (inp) {
        inp.focus();
        const len = inp.value.length;
        inp.setSelectionRange(len, len);
      }
    }

    DOM.historyStage.querySelectorAll("[data-hist-filter]").forEach((btn) => {
      btn.onclick = () => {
        CS.historyFilter = btn.getAttribute("data-hist-filter") || "all";
        CS.historyPage = 1;
        renderHistoryStage();
      };
    });

    const searchInp = DOM.historyStage.querySelector("#hist-search-inp");
    if (searchInp) {
      searchInp.oninput = () => {
        CS.historyQuery = searchInp.value;
        CS.historyPage = 1;
        renderHistoryStage();
      };
    }
    const statusSelect = DOM.historyStage.querySelector("#hist-status-filter");
    if (statusSelect) statusSelect.onchange = () => {
      CS.historyStatusFilter = statusSelect.value;
      CS.historyPage = 1;
      renderHistoryStage();
    };
    const sortSelect = DOM.historyStage.querySelector("#hist-sort");
    if (sortSelect) sortSelect.onchange = () => {
      CS.historySort = sortSelect.value;
      CS.historyPage = 1;
      renderHistoryStage();
    };
    DOM.historyStage.querySelectorAll("[data-hist-image-download]").forEach((el) => {
      el.onclick = (event) => event.stopPropagation();
    });

    DOM.historyStage.querySelectorAll("[data-hist-open-mode]").forEach((btn) => {
      btn.onclick = () => {
        const source = btn.getAttribute("data-hist-open-mode");
        if (source === "quick" || source === "batch") switchCreationStage(source);
        else if (source === "article") switchCreationStage("article");
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-restore]").forEach((btn) => {
      btn.onclick = () => {
        if (typeof window.confirm === "function" && !window.confirm("将历史图片恢复到当前画布的输出节点，可能替换已有内容（可撤销）。确定继续吗？")) return;
        restoreHistoryEntryToCanvas(btn.getAttribute("data-hist-restore"));
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-redo-recipe]").forEach((btn) => {
      btn.onclick = async () => {
        const rcpId = btn.getAttribute("data-hist-redo-recipe");
        if (rcpId && window.HandrawMakeImage) {
          const ok = await window.HandrawMakeImage.loadRecipe(rcpId);
          if (ok) {
            switchCreationStage("quick");
            toast("已原样打开配方");
          } else {
            toast("配方不存在或无法加载");
          }
        }
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-zip]").forEach((btn) => {
      btn.onclick = () => {
        const hid = btn.getAttribute("data-hist-zip");
        const h = (CS.generationHistory || []).find((item) => item.id === hid);
        if (h) {
          exportZipFromPayload({
            kind: h.kind || "images",
            title: h.tabTitle || "历史交付包",
            markdown: h.markdown || "",
            items: h.items || []
          });
        }
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-del]").forEach((btn) => {
      btn.onclick = async () => {
        const hid = btn.getAttribute("data-hist-del");
        if (!hid) return;
        if (typeof window.confirm === "function" && !window.confirm("删除本次生成记录后，关联的公开作品可能同步下架，确定继续吗？")) return;
        btn.disabled = true;
        try {
          await deleteCloudHistory(hid, false);
          CS.generationHistory = (CS.generationHistory || []).filter((item) => item.id !== hid);
          delete CS.historyExpandedPromptIds[hid];
          delete CS.historyExpandedBatchIds[hid];
          delete CS.historySelectedPreview[hid];
          writeJsonStorage(HISTORY_STORAGE_KEY, CS.generationHistory);
          renderTopAndBottomDocks();
          toast("已删除生成记录；关联公开作品（如有）已同步下架");
        } catch (err) {
          toast(`删除历史失败：${err.message || err}`);
          btn.disabled = false;
        }
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-expand-batch]").forEach((btn) => {
      btn.onclick = () => {
        const hid = btn.getAttribute("data-hist-expand-batch");
        CS.historyExpandedBatchIds[hid] = !CS.historyExpandedBatchIds[hid];
        renderHistoryStage();
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-img-toggle]").forEach((tile) => {
      tile.onclick = () => {
        const hid = tile.getAttribute("data-hist-img-toggle");
        const idx = Number(tile.getAttribute("data-hist-img-idx"));
        if (CS.historySelectedPreview[hid] === idx) {
          delete CS.historySelectedPreview[hid];
        } else {
          CS.historySelectedPreview[hid] = idx;
        }
        renderHistoryStage();
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-close-preview]").forEach((btn) => {
      btn.onclick = () => {
        const hid = btn.getAttribute("data-hist-close-preview");
        delete CS.historySelectedPreview[hid];
        renderHistoryStage();
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-toggle-prompt]").forEach((btn) => {
      btn.onclick = () => {
        const hid = btn.getAttribute("data-hist-toggle-prompt");
        CS.historyExpandedPromptIds[hid] = !CS.historyExpandedPromptIds[hid];
        renderHistoryStage();
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-copy-prompt]").forEach((btn) => {
      btn.onclick = async () => {
        const hid = btn.getAttribute("data-hist-copy-prompt");
        const h = (CS.generationHistory || []).find((item) => item.id === hid);
        if (!h || !h.prompt) return;
        const textToCopy = S.filterDisplayPrompt ? S.filterDisplayPrompt(h.prompt) : h.prompt;
        try {
          await navigator.clipboard.writeText(textToCopy);
          toast("📋 已复制该条历史记录的完整提示词");
        } catch (_) {
          toast("已读取提示词");
        }
      };
    });

    DOM.historyStage.querySelectorAll("[data-hist-page]").forEach((btn) => {
      btn.onclick = () => {
        const nextP = Number(btn.getAttribute("data-hist-page"));
        if (!nextP || nextP < 1 || nextP > totalPages || nextP === curPage) return;
        CS.historyPage = nextP;
        try {
          window.history.replaceState(null, "", `?view=history&page=${nextP}`);
        } catch (_) {}
        renderHistoryStage();
        const sc = DOM.historyStage.querySelector("#hist-page-scroll");
        if (sc) sc.scrollTop = 0;
      };
    });
  }


  /* ======================== VIEWPORT, SVG EDGES & V4 NODE RENDERERS ======================== */
  function getRelatedSets() {
    const selSet = new Set(CS.graph.selectedIds || []);
    const relNodeIds = new Set(selSet);
    const relEdgeIds = new Set();
    for (const e of CS.graph.edges || []) {
      if (selSet.has(e.from) || selSet.has(e.to)) {
        relEdgeIds.add(e.id);
        relNodeIds.add(e.from);
        relNodeIds.add(e.to);
      }
    }
    return { selSet, relNodeIds, relEdgeIds };
  }

  function updateGridBackground() {
    if (!DOM.grid) return;
    if (CS.gridMode === "blank") {
      DOM.grid.style.backgroundImage = "none";
      return;
    }
    const step = Math.max(12, Math.round(24 * CS.vk));
    const ox = ((CS.vx % step) + step) % step;
    const oy = ((CS.vy % step) + step) % step;
    if (CS.gridMode === "lines") {
      DOM.grid.style.backgroundImage = `linear-gradient(to right, var(--ic-line) 1px, transparent 1px), linear-gradient(to bottom, var(--ic-line) 1px, transparent 1px)`;
    } else {
      const r = Math.max(1, Math.min(1.9, 1.35 * CS.vk));
      DOM.grid.style.backgroundImage = `radial-gradient(circle, var(--ic-dot) ${r.toFixed(2)}px, transparent ${(r + 0.5).toFixed(2)}px)`;
    }
    DOM.grid.style.backgroundSize = `${step}px ${step}px`;
    DOM.grid.style.backgroundPosition = `${ox}px ${oy}px`;
  }

  function applyViewportTransform() {
    if (!DOM.world) return;
    DOM.world.style.transform = `translate(${CS.vx.toFixed(1)}px, ${CS.vy.toFixed(1)}px) scale(${CS.vk.toFixed(4)})`;
    updateGridBackground();
    positionFloatingOverlays();
    renderMinimap();
    if (DOM.zoomPctBtn) DOM.zoomPctBtn.textContent = `${Math.round(CS.vk * 100)}%`;
  }

  function renderEdgesSvg() {
    if (!DOM.edgesSvg) return;
    const { relEdgeIds } = getRelatedSets();
    const parts = [];

    for (const e of CS.graph.edges || []) {
      const nFrom = getNodeById(e.from);
      const nTo = getNodeById(e.to);
      if (!nFrom || !nTo) continue;
      const p1 = getPortWorldPos(nFrom, "out");
      const p2 = getPortWorldPos(nTo, "in");
      const d = bezierPath(p1.x, p1.y, p2.x, p2.y);
      const isSel = CS.selectedEdgeId === e.id;
      const isRel = relEdgeIds.has(e.id);
      const stroke = edgeStrokeColor(nFrom);
      parts.push(`
        <g class="ic-edge-group ${isRel ? "is-related" : ""} ${isSel ? "is-selected" : ""}" data-edge-id="${esc(e.id)}">
          <path class="ic-edge-hit" d="${d}" data-edge-hit="${esc(e.id)}"></path>
          <path class="ic-edge-line" d="${d}" style="stroke:${stroke};"></path>
        </g>
      `);
    }

    if (CS.wiring) {
      const src = getNodeById(CS.wiring.fromNodeId);
      if (src) {
        const anchor = getPortWorldPos(src, CS.wiring.fromDir);
        const tx = CS.wiring.curWorldX;
        const ty = CS.wiring.curWorldY;
        const d = CS.wiring.fromDir === "out" ? bezierPath(anchor.x, anchor.y, tx, ty) : bezierPath(tx, ty, anchor.x, anchor.y);
        parts.push(`<path class="ic-edge-live" d="${d}"></path>`);
      }
    }

    DOM.edgesSvg.innerHTML = parts.join("");
  }

  function renderVisualSlotHtml(nodeId, field, label, icon, itemId) {
    const res = itemId ? Catalog.resourceMap.get(itemId) : null;
    if (!res) {
      return `
        <div class="ic-v4-visual-slot" data-sp-pick="${esc(nodeId)}" data-sp-field="${esc(field)}" title="点击选择${esc(label)}">
          <div style="text-align:center;padding:8px 6px;display:flex;flex-direction:column;align-items:center;gap:4px;">
            ${icon ? `<span style="font-size:17px;line-height:1;">${icon}</span>` : ""}
            <span style="font-size:11.2px;font-weight:800;color:var(--ic-ink);">${esc(label)} · 未选</span>
            <span class="btn btn-sm btn-primary" style="padding:1px 8px;font-size:10.5px;pointer-events:none;">＋ 选择</span>
          </div>
        </div>
      `;
    }
    return `
      <div class="ic-v4-visual-slot is-filled" data-sp-pick="${esc(nodeId)}" data-sp-field="${esc(field)}" title="${esc(res.id)} ${esc(res.name)}（点击更换）">
        <div style="position:relative;">
          <img class="ic-v4-slot-thumb" src="${esc(res.image)}" alt="${esc(res.name)}" />
          <span style="position:absolute;left:5px;top:5px;padding:1px 5px;border-radius:4px;background:rgba(20,17,15,0.72);color:#fff;font-size:9.5px;font-family:var(--font-mono);font-weight:700;">${esc(res.id)}</span>
          <button type="button" class="ic-mini-glass-btn" data-sp-clear-field="${esc(nodeId)}" data-sp-field="${esc(field)}" style="position:absolute;right:4px;top:4px;padding:1px 5px;font-size:10px;" title="清空此项">×</button>
        </div>
        <div class="ic-v4-slot-meta">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">${esc(res.name)}</span>
          <span style="color:var(--vermilion);font-size:10.5px;flex-shrink:0;">更换</span>
        </div>
      </div>
    `;
  }

  function countArticleSections(mdText) {
    const lines = String(mdText || "").split(/\r?\n/);
    let secs = 0;
    let hasH1 = false;
    for (const ln of lines) {
      const t = ln.trim();
      if (/^#\s+/.test(t)) hasH1 = true;
      else if (/^#{2,3}\s+/.test(t)) secs += 1;
    }
    return { hasH1, secs };
  }

  function renderWorldNodes() {
    if (!DOM.nodesLayer) return;
    const { selSet, relNodeIds } = getRelatedSets();
    const nodes = CS.graph.nodes || [];

    const audDatalistId = "ic-datalist-audience";
    const sceneDatalistId = "ic-datalist-scene";

    const cardsHtml = nodes
      .map((n) => {
        const isSel = selSet.has(n.id);
        const isRel = relNodeIds.has(n.id) && !isSel;
        const posStyle = `left:${n.x}px;top:${n.y}px;width:${n.w || 332}px;`;

        /* -------- 1) SKILL PARAMS COMBINED INPUT NODE (风格参数) -------- */
        if (n.type === "skill_params") {
          const sd = n.data || {};
          const colors = Array.isArray(sd.colors) ? sd.colors : [];
          const tones = Array.isArray(sd.tones) ? sd.tones : [];
          const moods = Array.isArray(sd.moods) ? sd.moods.map(normalizeMoodLabel).filter(Boolean) : [];
          const customMoodList = String(sd.customMood || "")
            .split(/[,，、]+/)
            .map((x) => x.trim())
            .filter(Boolean);
          const allMoodTags = [...moods, ...customMoodList];

          const hasAnyValue = Boolean(
            sd.fusion ||
              sd.style1 ||
              sd.style2 ||
              sd.layout ||
              colors.length ||
              tones.length ||
              allMoodTags.length ||
              sd.whitespace ||
              sd.audience ||
              sd.businessScene
          );

          return `
            <div class="ic-node ic-node-skill_params ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>风格参数</span>
                <div style="display:flex;align-items:center;gap:5px;">
                  ${hasAnyValue ? `<button type="button" class="ic-opt-pill" data-sp-reset-all="${esc(n.id)}" style="padding:1px 6px;font-size:10px;">重置</button>` : ""}
                  <span class="ic-node-badge ic-badge-input">输入</span>
                </div>
              </div>

              <div class="ic-v4-card">
                <!-- Fusion Switch -->
                <div class="ic-v4-row-head">
                  <span>是否画面融合</span>
                  <div class="ic-ctrl-seg">
                    <button type="button" class="ic-ctrl-pill ${!sd.fusion ? "is-active" : ""}" data-sp-fusion="${esc(n.id)}" data-val="0">单画风</button>
                    <button type="button" class="ic-ctrl-pill ${sd.fusion ? "is-active" : ""}" data-sp-fusion="${esc(n.id)}" data-val="1">双画风融合</button>
                  </div>
                </div>

                <!-- Style(s) & Layout Visual Slots -->
                ${
                  sd.fusion
                    ? `
                    <div class="ic-v4-slot-grid">
                      ${renderVisualSlotHtml(n.id, "style1", "角色画风", "", sd.style1)}
                      ${renderVisualSlotHtml(n.id, "style2", "场景画风", "", sd.style2)}
                    </div>
                    <div>
                      ${renderVisualSlotHtml(n.id, "layout", "图型", "", sd.layout)}
                    </div>
                  `
                    : `
                    <div class="ic-v4-slot-grid">
                      ${renderVisualSlotHtml(n.id, "style1", "画风", "", sd.style1)}
                      ${renderVisualSlotHtml(n.id, "layout", "图型", "", sd.layout)}
                    </div>
                  `
                }

                ${
                  sd.layout === "SC-021"
                    ? `
                    <div class="ic-v4-section">
                      <span style="font-size:10.8px;color:var(--ic-muted);font-weight:750;">SC-021 双拼子玩法：</span>
                      <select class="ic-v4-mini-inp" data-sp-sc021="${esc(n.id)}">
                        ${E.SC021_PLAYSTYLES.map((p) => `<option value="${esc(p)}" ${p === sd.sc021Type ? "selected" : ""}>${esc(p)}</option>`).join("")}
                      </select>
                    </div>
                  `
                    : sd.layout === "SC-022"
                      ? `
                      <div class="ic-v4-slot-grid">
                        <input class="ic-v4-mini-inp" data-sp-sc022-name="${esc(n.id)}" value="${esc(sd.sc022Name || "")}" placeholder="签名姓名" />
                        <input class="ic-v4-mini-inp" data-sp-sc022-py="${esc(n.id)}" value="${esc(sd.sc022Pinyin || "")}" placeholder="拼音" />
                      </div>
                    `
                      : ""
                }

                <!-- Theme Colors (Multi-select!) -->
                <div class="ic-v4-section">
                  <div class="ic-v4-row-head">
                    <span>主题色（可多选）</span>
                    <button type="button" class="ic-opt-pill" data-sp-pick="${esc(n.id)}" data-sp-field="colors">${colors.length ? `更换 (${colors.length})` : "未选 · ＋选择"}</button>
                  </div>
                  ${
                    colors.length
                      ? `<div class="ic-v4-chip-wrap">${colors
                          .map((cid) => {
                            const cObj = Catalog.resourceMap.get(cid);
                            return `<span class="ic-v4-tag">${esc(cid)} ${esc(cObj ? cObj.name.slice(0, 6) : "")}<button type="button" data-sp-rm-arr="${esc(n.id)}" data-field="colors" data-val="${esc(cid)}">×</button></span>`;
                          })
                          .join("")}</div>`
                      : ""
                  }
                </div>

                <!-- Tones (Multi-select) -->
                <div class="ic-v4-section">
                  <div class="ic-v4-row-head">
                    <span>影调</span>
                    <button type="button" class="ic-opt-pill" data-sp-pick="${esc(n.id)}" data-sp-field="tones">${tones.length ? `更换 (${tones.length})` : "未选 · ＋选择"}</button>
                  </div>
                  ${
                    tones.length
                      ? `<div class="ic-v4-chip-wrap">${tones
                          .map((tid) => {
                            const tObj = Catalog.tones.find((t) => t.id === tid);
                            return `<span class="ic-v4-tag">${esc(tObj ? tObj.name_zh : tid)}<button type="button" data-sp-rm-arr="${esc(n.id)}" data-field="tones" data-val="${esc(tid)}">×</button></span>`;
                          })
                          .join("")}</div>`
                      : ""
                  }
                </div>

                <!-- Moods (Multi-select) -->
                <div class="ic-v4-section">
                  <div class="ic-v4-row-head">
                    <span>情绪（可多选）</span>
                    <button type="button" class="ic-opt-pill" data-sp-pick="${esc(n.id)}" data-sp-field="moods">${allMoodTags.length ? `更换 (${allMoodTags.length})` : "未选 · ＋多选"}</button>
                  </div>
                  ${
                    allMoodTags.length
                      ? `<div class="ic-v4-chip-wrap">${moods
                          .map((m) => `<span class="ic-v4-tag">${esc(m)}<button type="button" data-sp-rm-arr="${esc(n.id)}" data-field="moods" data-val="${esc(m)}">×</button></span>`)
                          .concat(customMoodList.map((cm) => `<span class="ic-v4-tag">${esc(cm)}</span>`))
                          .join("")}</div>`
                      : ""
                  }
                </div>

                <!-- Whitespace -->
                <div class="ic-v4-section">
                  <div class="ic-v4-row-head"><span>留白</span></div>
                  <div class="ic-ctrl-seg">
                    ${E.WHITESPACE_OPTIONS.map(
                      (w) =>
                        `<button type="button" class="ic-ctrl-pill ${(sd.whitespace || "") === w.value ? "is-active" : ""}" data-sp-ws="${esc(n.id)}" data-val="${esc(w.value)}">${esc(w.label)}</button>`
                    ).join("")}
                  </div>
                </div>

                <!-- Audience & Business Scene -->
                <div class="ic-v4-slot-grid">
                  <div class="ic-v4-section">
                    <span style="font-size:11px;font-weight:800;color:var(--ic-ink);">受众</span>
                    <input type="text" list="${audDatalistId}" class="ic-v4-mini-inp" data-sp-aud="${esc(n.id)}" value="${esc(sd.audience || "")}" placeholder="可选：目标受众" />
                  </div>
                  <div class="ic-v4-section">
                    <span style="font-size:11px;font-weight:800;color:var(--ic-ink);">业务场景</span>
                    <input type="text" list="${sceneDatalistId}" class="ic-v4-mini-inp" data-sp-scene="${esc(n.id)}" value="${esc(sd.businessScene || "")}" placeholder="可选：投放/使用场景" />
                  </div>
                </div>
              </div>

              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="连入右侧「生成设置」节点">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 2) IMAGE PARAMETER INPUT NODE (图片参数) -------- */
        if (n.type === "asset") {
          const items = Array.isArray(n.data?.items) ? n.data.items : [];
          return `
            <div class="ic-node ic-node-asset ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>图片参数</span>
                <span class="ic-node-badge ic-badge-input">输入</span>
              </div>

              <div class="ic-v4-card">
                ${
                  !items.length
                    ? `
                    <div class="ic-ing-empty-slot" data-ast-open="${esc(n.id)}" style="height:142px;padding:12px;" title="选择图片资产或上传本地参考图片">
                      <div style="font-size:12px;font-weight:750;color:var(--ic-muted);">[图片]</div>
                      <div style="font-size:12px;font-weight:850;color:var(--ic-ink);">未选择参考图片</div>
                      <div style="font-size:10.8px;color:var(--ic-muted);text-align:center;">角色 / 道具 / 场景 / 其他 / 上传本地图</div>
                      <button type="button" class="btn btn-sm btn-primary" data-ast-open="${esc(n.id)}" style="padding:3px 11px;font-size:11.2px;margin-top:2px;">＋ 选择 / 上传图片</button>
                    </div>
                  `
                    : items.length === 1
                      ? (() => {
                          const it = items[0];
                          const cm = getAssetCatMeta(it.cat || "other");
                          return `
                            <div style="position:relative;border-radius:10px;overflow:hidden;border:1px solid var(--ic-border);height:132px;background:var(--ic-surface);" data-ast-open="${esc(n.id)}">
                              <img src="${esc(it.image)}" alt="${esc(it.name)}" style="width:100%;height:100%;object-fit:cover;display:block;cursor:pointer;" />
                              <span style="position:absolute;left:6px;top:6px;padding:2px 6px;border-radius:5px;background:rgba(20,17,15,0.72);color:#fff;font-size:10px;font-weight:750;">${esc(it.catLabel || cm.label)}</span>
                              <div style="position:absolute;right:6px;top:6px;display:flex;gap:4px;">
                                <button type="button" class="ic-mini-glass-btn" data-ast-open="${esc(n.id)}">更换</button>
                                <button type="button" class="ic-mini-glass-btn" data-ast-clear="${esc(n.id)}" title="清空图片参数">×</button>
                              </div>
                            </div>
                            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
                              <div style="min-width:0;">
                                <div style="font-size:12.2px;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(it.name)}</div>
                                <div style="font-size:10.8px;color:var(--ic-muted);">${esc(it.id)} · 作为输入参考图保持一致</div>
                              </div>
                              <button type="button" class="ic-opt-pill" data-ast-open="${esc(n.id)}" style="flex-shrink:0;">更换 / 增减</button>
                            </div>
                          `;
                        })()
                      : `
                      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;">
                        ${items
                          .slice(0, 4)
                          .map(
                            (it) => `
                            <div style="position:relative;border-radius:8px;overflow:hidden;height:78px;border:1px solid var(--ic-border);">
                              <img src="${esc(it.image)}" alt="${esc(it.name)}" style="width:100%;height:100%;object-fit:cover;display:block;" />
                              <span style="position:absolute;left:4px;bottom:4px;right:4px;padding:1px 4px;border-radius:4px;background:rgba(20,17,15,0.72);color:#fff;font-size:9.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(it.name)}</span>
                            </div>
                          `
                          )
                          .join("")}
                      </div>
                      <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="font-size:11.5px;font-weight:800;">已选 ${items.length} 张参考图</span>
                        <div style="display:flex;gap:5px;">
                          <button type="button" class="ic-opt-pill" data-ast-open="${esc(n.id)}">更换 / 增减</button>
                          <button type="button" class="ic-opt-pill" data-ast-clear="${esc(n.id)}">清空</button>
                        </div>
                      </div>
                    `
                }
              </div>

              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="将图片参数连入右侧「生成设置」节点">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 3) TEXT PARAMETER + FILE ATTACHMENT NODE (文本参数) -------- */
        if (n.type === "text_input") {
          const td = n.data || {};
          const attSize = Number(td.fileSize) || (td.fileContent || "").length || 0;
          const attSizeLabel =
            attSize >= 1024 ? `${(attSize / 1024).toFixed(1)} KB` : attSize > 0 ? `${attSize} B` : "";

          return `
            <div class="ic-node ic-node-text_input ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>文本参数</span>
                <span class="ic-node-badge ic-badge-input">输入</span>
              </div>

              <div class="ic-v4-card">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;">
                  <label class="ic-opt-pill" style="cursor:pointer;color:var(--vermilion);border-color:var(--vermilion-border);font-weight:800;" title="选择文件作为附件">
                    选择文件
                    <input type="file" data-txt-file="${esc(n.id)}" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden />
                  </label>
                </div>

                ${
                  td.fileName
                    ? `
                    <div class="ic-file-banner">
                      <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">附件: ${esc(td.fileName)}${attSizeLabel ? ` · ${esc(attSizeLabel)}` : ""}</span>
                      <button type="button" data-txt-clear-file="${esc(n.id)}" style="border:0;background:transparent;color:inherit;cursor:pointer;font-weight:900;" title="移除附件">×</button>
                    </div>
                  `
                    : ""
                }

                <textarea
                  class="ic-prompt-card-ta"
                  data-txt-ta="${esc(n.id)}"
                  data-canvas-no-zoom
                  readonly
                  style="min-height:112px;font-size:12.4px;line-height:1.56;cursor:pointer;"
                  title="点击弹出编辑窗口"
                  placeholder="点击此处输入画面描述或补充要求…"
                >${esc(td.text || "")}</textarea>

                <div style="display:flex;justify-content:space-between;align-items:center;font-size:10.8px;color:var(--ic-muted);">
                  <span>${td.fileName ? "已添加附件" : "文本输入"}</span>
                  <span>点击输入框编辑</span>
                </div>
              </div>

              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="连入右侧「多尺寸输出」或「生成设置」节点">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 3.5) BRIDGE HUB NODE (多尺寸输出：位于输入与输出之间，一分多分发) -------- */
        if (n.type === "bridge") {
          const rec = E.resolveControlRecipe(CS.graph, n, Catalog);
          const downCtrls = CS.graph.edges
            .filter((e) => e.from === n.id)
            .map((e) => getNodeById(e.to))
            .filter(Boolean);

          const bridgeTags = [];
          if (rec.skillNode) {
            const styleSummary = [rec.style1Id, rec.layoutId].filter(Boolean).join(" · ");
            bridgeTags.push(`风格参数${styleSummary ? `（${styleSummary}）` : ""}`);
          }
          if (rec.assetItems.length) bridgeTags.push("图片参数");
          if (rec.textNode) {
            if (rec.attachedFileName) bridgeTags.push(`附件: ${rec.attachedFileName}`);
            if (!rec.attachedFileName || rec.userNoteText) {
              bridgeTags.push("文本参数");
            }
          }

          return `
            <div class="ic-node ic-node-bridge ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>多尺寸输出</span>
                <span class="ic-node-badge ic-badge-bridge">多尺寸输出</span>
              </div>

              <div class="ic-v4-card">
                <div class="ic-bridge-hub-box">
                  <div style="font-size:10.8px;font-weight:800;color:var(--ic-ink);">已汇总输入</div>
                  <div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
                    ${
                      bridgeTags.length
                        ? bridgeTags.map((t) => `<span class="ic-v4-tag" style="background:var(--ic-panel-solid);font-size:10.3px;">${esc(t)}</span>`).join("")
                        : `<span style="font-size:10.6px;color:var(--ic-muted);">👈 左侧连入风格 / 图片 / 文本参数</span>`
                    }
                  </div>
                  <div style="font-size:10.5px;color:var(--ic-muted);border-top:1px dashed var(--ic-border);padding-top:5px;">
                    ${downCtrls.length ? `已分发至 ${downCtrls.length} 个生成设置节点` : "右侧可同时连出多个生成设置"}
                  </div>
                </div>

                <button type="button" class="ic-bridge-add-btn" data-bridge-add-ctrl="${esc(n.id)}" title="新增一个下游生成设置节点并自动连线">
                  ＋ 新增下游生成设置
                </button>
              </div>

              <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="汇总接收左侧输入节点（风格参数 / 图片参数 / 文本参数）">
                <span class="ic-port-dot">+</span>
              </div>
              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="一对多分发至右侧多个「输出控制」节点（例如封面 + 文章插图）">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 3.55) TOPIC FISSION NODE (AI 扩写主题：默认扩写 10 条，支持自填扩写方向与点击输入框弹窗查看全部) -------- */
        if (n.type === "fission") {
          const fd = n.data || {};
          const curStrat = fd.strategy || "daily_quote";
          const customStrat = String(fd.customStrategy || "").trim();
          const hasCustomStrat = Boolean(customStrat);
          const targetCnt = Math.max(1, Math.min(200, Math.round(Number(fd.targetCount ?? fd.count) || 10)));
          const genItems = Array.isArray(fd.generatedItems) ? fd.generatedItems : [];

          return `
            <div class="ic-node ic-node-fission ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>AI 扩写主题</span>
                <span class="ic-node-badge ic-badge-fission">已扩写 ${genItems.length} 条</span>
              </div>

              <div class="ic-v4-card">
                <div class="ic-v4-section">
                  <div class="ic-v4-row-head">
                    <span>核心母题</span>
                  </div>
                  <input
                    type="text"
                    class="ic-v4-input"
                    data-fis-seed="${esc(n.id)}"
                    data-canvas-no-zoom
                    value="${esc(fd.seedTopic || "")}"
                    placeholder="输入 1 个核心主题（如：春季新茶日签、咖啡科普图鉴）"
                  />
                </div>

                <div class="ic-v4-section">
                  <div class="ic-v4-row-head">
                    <span>扩写方向</span>
                    ${hasCustomStrat ? `<span style="font-size:10px;color:#6d28d9;font-weight:800;">已自填方向</span>` : ""}
                  </div>
                  <div class="ic-fission-strat-grid">
                    ${(E.FISSION_STRATEGIES || [])
                      .map(
                        (st) => `
                        <button type="button" class="ic-fission-strat-btn ${!hasCustomStrat && curStrat === st.id ? "is-active" : ""}" data-fis-strat="${esc(n.id)}" data-val="${esc(st.id)}" title="${esc(st.desc)}">
                          <span>${esc(st.label)}</span>
                        </button>
                      `
                      )
                      .join("")}
                  </div>
                  <input
                    type="text"
                    class="ic-v4-input"
                    data-fis-custom-strat="${esc(n.id)}"
                    data-canvas-no-zoom
                    value="${esc(customStrat)}"
                    placeholder="或自行填写扩写方向（如：反常识痛点提问…）"
                    style="${hasCustomStrat ? "border-color:#7c3aed;background:rgba(124,58,237,0.06);" : ""}"
                  />
                </div>

                <div class="ic-v4-section">
                  <div class="ic-count-row">
                    <span style="font-size:11.5px;font-weight:800;color:var(--ic-ink);">扩写条数</span>
                    <div class="ic-count-custom-box" title="自行填写扩写条数 (默认 10 条，支持 1~200 条)">
                      <button type="button" class="ic-count-step-btn" data-fis-cnt-step="${esc(n.id)}" data-delta="-1">−</button>
                      <input
                        type="number"
                        min="1"
                        max="200"
                        step="1"
                        class="ic-count-inp"
                        data-fis-cnt-inp="${esc(n.id)}"
                        data-canvas-no-zoom
                        value="${targetCnt}"
                      />
                      <button type="button" class="ic-count-step-btn" data-fis-cnt-step="${esc(n.id)}" data-delta="1">＋</button>
                      <span style="font-size:10.8px;color:var(--ic-muted);font-weight:750;padding-left:2px;">条</span>
                    </div>
                  </div>
                </div>

                <div class="ic-v4-section">
                  <div class="ic-v4-row-head">
                    <span>扩写子主题（共 ${genItems.length} 条）</span>
                    <span style="font-size:10px;color:#6d28d9;font-weight:750;">点击输入框查看全部</span>
                  </div>
                  <textarea
                    class="ic-prompt-card-ta"
                    data-fis-open-modal="${esc(n.id)}"
                    data-canvas-no-zoom
                    readonly
                    style="min-height:84px;max-height:92px;font-size:11.3px;line-height:1.52;cursor:pointer;background:rgba(124,58,237,0.04);border-color:rgba(124,58,237,0.28);"
                    title="点击弹出查看与编辑全部扩写子主题窗口"
                    placeholder="点击查看或微调全部扩写子主题…"
                  >${esc(genItems.slice(0, 6).join("\n"))}</textarea>
                </div>

                <button type="button" class="ic-fission-gen-btn" data-fis-gen="${esc(n.id)}">
                  AI 扩写 ${targetCnt} 条子主题
                </button>
              </div>

              <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="可选接收左侧「文本参数」作为母题补充">
                <span class="ic-port-dot">+</span>
              </div>
              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="连入右侧「批量」节点，驱动大批量出图">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 3.6) LOOP BATCH NODE (批量：支持多文案 / 多画风 / 多图型 / 多图参循环出图) -------- */
        if (n.type === "loop") {
          const ld = n.data || {};
          const curLoopMode = ["prompts", "styles", "layouts", "assets"].includes(ld.loopMode) ? ld.loopMode : "prompts";
          const rec = E.resolveControlRecipe(CS.graph, n, Catalog);
          const downCtrls = CS.graph.edges
            .filter((e) => e.from === n.id)
            .map((e) => getNodeById(e.to))
            .filter((x) => x && x.type === "output_control");
          const effectiveRec = downCtrls.length ? E.resolveControlRecipe(CS.graph, downCtrls[0], Catalog) : rec;
          const iters = E.resolveLoopIterations(CS.graph, n, effectiveRec, Catalog);
          const iterCount = iters.length;
          const rMap = Catalog.resourceMap || new Map();
          const upFission = CS.graph.edges
            .filter((e) => e.to === n.id)
            .map((e) => getNodeById(e.from))
            .find((x) => x && x.type === "fission") || rec.fissionNode || null;

          const upTags = [];
          if (rec.skillNode) upTags.push("公共风格");
          if (upFission) upTags.push(`AI扩写×${(upFission.data?.generatedItems || []).length}`);
          if (rec.assetItems.length) upTags.push(`图参×${rec.assetItems.length}`);
          if (rec.textNode) upTags.push("文本母本");

          const doneDispItems = downCtrls
            .flatMap((c) => getDownstreamDisplayNodes(c.id))
            .flatMap((d) => d.data?.items || [])
            .filter((it) => it && it.imageUrl);

          let modeBodyHtml = "";
          if (curLoopMode === "prompts") {
            const rawLines = String(ld.promptListText || "")
              .split(/\r?\n/)
              .map((s) => s.trim())
              .filter(Boolean);
            const usingFissionFeed = Boolean(upFission && !ld.manualOverrideFission && (upFission.data?.generatedItems || []).length > 0);
            modeBodyHtml = `
              <div class="ic-v4-section">
                <div class="ic-v4-row-head">
                  <span data-loop-line-cnt="${esc(n.id)}">批量文案（共 ${iterCount} 条 · 每行 1 张）</span>
                  <div style="display:flex;gap:4px;">
                    <button type="button" class="ic-opt-pill" data-loop-open-prompts="${esc(n.id)}" style="color:#0f766e;border-color:rgba(13,148,136,0.4);">大窗/导入</button>
                    ${
                      rawLines.length
                        ? `<button type="button" class="ic-opt-pill" data-loop-clear-prompts="${esc(n.id)}">清空</button>`
                        : `<button type="button" class="ic-opt-pill" data-loop-fill-demo="${esc(n.id)}">示例</button>`
                    }
                  </div>
                </div>
                ${
                  usingFissionFeed
                    ? `
                      <div
                        data-fis-open-modal="${esc(upFission.id)}"
                        title="点击查看或微调全部扩写子主题"
                        style="padding:8px 10px;border-radius:9px;background:rgba(124,58,237,0.08);border:1px solid rgba(124,58,237,0.26);font-size:11px;line-height:1.5;color:var(--ic-ink);cursor:pointer;"
                      >
                        <div style="font-weight:850;color:#6d28d9;margin-bottom:3px;">已自动接入上游「AI 扩写主题」共 ${iterCount} 条（点击查看全部）</div>
                        <div style="color:var(--ic-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">首条：${esc(iters[0]?.theme || "")}</div>
                      </div>
                    `
                    : `
                      <textarea
                        class="ic-loop-list-ta"
                        data-loop-ta="${esc(n.id)}"
                        data-canvas-no-zoom
                        placeholder="每行输入一条出图主题或文案…&#10;（也可点击右上角导入 .txt/.csv，或从左侧连入「AI 扩写主题」）"
                      >${esc(ld.promptListText || "")}</textarea>
                    `
                }
                <div style="font-size:10.3px;color:var(--ic-muted);display:flex;justify-content:space-between;gap:6px;">
                  <span>${rec.textNode ? "支持 {item} / {index} 变量" : iterCount > 6 ? "超 6 张自动聚合成 1 个图集节点" : "每行独立作为一轮出图主题"}</span>
                  <span>支持 1~200 轮</span>
                </div>
              </div>
            `;
          } else if (curLoopMode === "styles" || curLoopMode === "layouts") {
            const isStyle = curLoopMode === "styles";
            const ids = isStyle ? ld.styleIds || [] : ld.layoutIds || [];
            modeBodyHtml = `
              <div class="ic-v4-section">
                <div class="ic-v4-row-head">
                  <span>${isStyle ? `待循环画风 (${ids.length} 款)` : `待循环图型 (${ids.length} 款)`}</span>
                  <button type="button" class="ic-opt-pill" data-loop-rand="${esc(n.id)}" data-kind="${curLoopMode}" style="color:#0f766e;border-color:rgba(13,148,136,0.4);">随机4款</button>
                </div>
                ${
                  ids.length === 0
                    ? `
                      <div class="ic-ing-empty-slot" data-loop-pick="${esc(n.id)}" data-kind="${curLoopMode}" style="min-height:86px;padding:10px;">
                        <div style="font-size:11.5px;font-weight:800;">点击选择多款${isStyle ? "画风横评" : "图型对比"}</div>
                      </div>
                    `
                    : `
                      <div class="ic-loop-item-grid" data-canvas-no-zoom>
                        ${ids
                          .map((id, idx) => {
                            const r = rMap.get(id);
                            return `
                              <div class="ic-loop-item-card" title="${esc(r?.name || id)}">
                                ${r?.image ? `<img src="${esc(r.image)}" alt="${esc(id)}" />` : ""}
                                <div style="min-width:0;flex:1;">
                                  <div style="font-size:10px;font-family:var(--font-mono);font-weight:800;color:#0f766e;">#${idx + 1} · ${esc(id)}</div>
                                  <div style="font-size:10.5px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(r?.name || id)}</div>
                                </div>
                                <button type="button" data-loop-rm-item="${esc(n.id)}" data-kind="${curLoopMode}" data-val="${esc(id)}" style="border:0;background:transparent;color:var(--ic-muted);cursor:pointer;font-size:12px;padding:0 2px;">×</button>
                              </div>
                            `;
                          })
                          .join("")}
                      </div>
                      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
                        <button type="button" class="ic-opt-pill" data-loop-pick="${esc(n.id)}" data-kind="${curLoopMode}" style="flex:1;text-align:center;font-weight:800;">＋ 增减${isStyle ? "画风" : "图型"}</button>
                        <button type="button" class="ic-opt-pill" data-loop-clear-arr="${esc(n.id)}" data-kind="${curLoopMode}">清空</button>
                      </div>
                    `
                }
              </div>
            `;
          } else {
            // assets mode
            const astItems = effectiveRec.assetItems || [];
            modeBodyHtml = `
              <div class="ic-v4-section">
                <div class="ic-v4-row-head">
                  <span>逐张遍历参考图 (${astItems.length} 张)</span>
                  <button type="button" class="ic-opt-pill" data-loop-setup-assets="${esc(n.id)}" style="color:#0f766e;border-color:rgba(13,148,136,0.4);">＋ 选图参</button>
                </div>
                ${
                  astItems.length === 0
                    ? `
                      <div class="ic-ing-empty-slot" data-loop-setup-assets="${esc(n.id)}" style="min-height:86px;padding:10px;">
                        <div style="font-size:11.3px;font-weight:800;">点击添加或从左侧连入「图片参数」</div>
                        <div style="font-size:10.2px;color:var(--ic-muted);">每张参考图单独作为 1 轮主体批量出图</div>
                      </div>
                    `
                    : `
                      <div class="ic-loop-item-grid" data-canvas-no-zoom>
                        ${astItems
                          .slice(0, 12)
                          .map(
                            (it, idx) => `
                            <div class="ic-loop-item-card" title="${esc(it.name || it.id)}">
                              ${it.image ? `<img src="${esc(it.image)}" alt="${esc(it.name || "")}" />` : ""}
                              <div style="min-width:0;flex:1;">
                                <div style="font-size:10px;font-family:var(--font-mono);font-weight:800;color:#0f766e;">#${idx + 1}</div>
                                <div style="font-size:10.5px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(it.name || it.id)}</div>
                              </div>
                            </div>
                          `
                          )
                          .join("")}
                      </div>
                    `
                }
              </div>
            `;
          }

          const isLoopRunning = ld.status === "running";
          const curStep = Math.max(1, Number(ld.currentStep) || 1);
          const totSteps = Math.max(1, Number(ld.totalSteps) || iterCount || 1);
          const pct = Math.min(100, Math.round((curStep / totSteps) * 100));

          return `
            <div class="ic-node ic-node-loop ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>批量</span>
                <span class="ic-node-badge ic-badge-loop" data-loop-head-badge="${esc(n.id)}">${
            isLoopRunning ? `${curStep}/${totSteps}` : `共 ${iterCount} 轮`
          }</span>
              </div>

              <div class="ic-v4-card">
                <div style="padding:5px 8px;border-radius:8px;background:var(--ic-surface);border:1px solid var(--ic-border);font-size:10.5px;display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap;">
                  <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;">
                    ${
                      upTags.length
                        ? upTags.map((t) => `<span class="ic-v4-tag" style="background:var(--ic-panel-solid);font-size:10px;">${esc(t)}</span>`).join("")
                        : `<span style="color:var(--ic-muted);">可连入公共风格/文本</span>`
                    }
                  </div>
                  <span style="color:${downCtrls.length ? "#0f766e" : "var(--ic-muted)"};font-weight:800;">
                    ${downCtrls.length ? `已连 ${downCtrls.length} 个生成设置` : "自动连生成设置"}
                  </span>
                </div>

                <div class="ic-v4-section">
                  <div class="ic-loop-mode-grid">
                    ${E.LOOP_MODES.map(
                      (m) => `
                        <button type="button" class="ic-loop-mode-btn ${curLoopMode === m.id ? "is-active" : ""}" data-loop-mode="${esc(n.id)}" data-val="${esc(m.id)}" title="${esc(m.desc)}">
                          <span>${esc(m.label)}</span>
                        </button>
                      `
                    ).join("")}
                  </div>
                </div>

                ${modeBodyHtml}

                ${
                  isLoopRunning
                    ? `
                      <div class="ic-loop-progress-wrap">
                        <div style="font-size:11px;font-weight:800;color:#0f766e;" data-loop-prog-text="${esc(n.id)}">
                          正在循环第 ${curStep} / ${totSteps} 轮…
                        </div>
                        <div class="ic-loop-progress-track">
                          <div class="ic-loop-progress-fill" data-loop-prog-bar="${esc(n.id)}" style="width:${pct}%;"></div>
                        </div>
                      </div>
                    `
                    : !downCtrls.length
                      ? `
                        <button type="button" class="ic-bridge-add-btn" data-loop-add-ctrl="${esc(n.id)}" style="color:#0f766e;border-color:rgba(13,148,136,0.38);">
                          ＋ 连接下游「生成设置」节点
                        </button>
                      `
                      : `
                        <div
                          data-loop-ready-hint="${esc(n.id)}"
                          style="padding:6px 9px;border-radius:8px;background:rgba(13,148,136,0.06);border:1px dashed rgba(13,148,136,0.28);font-size:10.6px;color:#0f766e;font-weight:750;text-align:center;"
                        >
                          ${
                            doneDispItems.length > 0
                              ? `已完成 ${doneDispItems.length} 张批量出图 · 在右侧「生成设置」重新运行`
                              : `已编排 ${iterCount} 轮队列 · 由右侧「生成设置」统一触发运行`
                          }
                        </div>
                      `
                }
              </div>

              <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="接收上游公共参数（风格参数 / 图片参数 / 文本参数）">
                <span class="ic-port-dot">+</span>
              </div>
              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="连入右侧「生成设置」节点，驱动批量出图">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 4) OUTPUT CONTROL NODE (生成设置：纯创作台，直接出图，1个节点即可驱动1~200张批量出图) -------- */
        if (n.type === "output_control") {
          const cd = n.data || {};
          const curMode =
            cd.mode === "xhs-batch"
              ? "series"
              : cd.mode === "article-cover"
                ? "article-illust"
                : cd.mode || "graphic-text";
          const curCount = Math.max(1, Math.min(200, Math.round(Number(cd.count) || (curMode === "series" ? 4 : 1))));
          const rec = E.resolveControlRecipe(CS.graph, n, Catalog);
          const plan = buildExecutionPlanForControl(n);
          const downPlan = curMode === "article-illust" ? getDownstreamArticlePlanNode(n) : null;
          const planSlotCount = downPlan?.data?.cards?.length ?? plan.specs.length;
          const hasBridgeUp = CS.graph.edges.some((e) => e.to === n.id && getNodeById(e.from)?.type === "bridge");

          const connectedTags = [];
          if (rec.loopNode) {
            const lmObj = E.LOOP_MODES.find((m) => m.id === (rec.loopNode.data?.loopMode || "prompts"));
            connectedTags.push(`批量(${lmObj ? lmObj.label : "批量"})`);
          } else if (rec.fissionNode) {
            connectedTags.push("AI 扩写主题");
          }
          if (hasBridgeUp) connectedTags.push("经多尺寸输出接入");
          if (rec.skillNode) {
            connectedTags.push("风格参数");
          }
          if (rec.assetItems.length) connectedTags.push(`图片参数×${rec.assetItems.length}`);
          if (rec.textNode) {
            if (rec.attachedFileName) connectedTags.push(rec.attachedFileName);
            if (!rec.attachedFileName || rec.userNoteText) {
              connectedTags.push("文本参数");
            }
          }

          return `
            <div class="ic-node ic-node-output_control ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>${esc(n.title === "输出控制" ? "生成设置" : (n.title || "生成设置"))}</span>
                <span class="ic-node-badge ic-badge-output-ctrl">生成设置</span>
              </div>

              <div class="ic-v4-card">
                <!-- Connected Upstream Summary -->
                <div style="padding:6px 8px;border-radius:8px;background:var(--ic-surface);border:1px solid var(--ic-border);font-size:11px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
                  ${
                    connectedTags.length
                      ? connectedTags.map((t) => `<span class="ic-v4-tag" style="background:var(--ic-panel-solid);font-size:10.5px;">${esc(t)}</span>`).join("")
                      : `<span style="color:var(--ic-muted);">可从左侧连入输入节点或「多尺寸输出」节点</span>`
                  }
                </div>

                <!-- 5 Modes Grid (文章封面+插图已合并为统一的「文章配图」) -->
                <div class="ic-v4-section">
                  <div class="ic-v4-row-head"><span>输出模式</span></div>
                  <div class="ic-ctrl-mode-grid">
                    ${E.OUTPUT_MODES.filter((m) => m.id !== "article-illust").map(
                      (m) => `
                      <button type="button" class="ic-ctrl-mode-btn ${curMode === m.id ? "is-active" : ""}" data-ctrl-mode="${esc(n.id)}" data-val="${esc(m.id)}" title="${esc(m.desc)}">
                        <span>${esc(m.label)}</span>
                      </button>
                    `
                    ).join("")}
                  </div>
                </div>

                <!-- Dynamic Count & Ratio Controls by Mode -->
                ${
                  curMode === "article-illust"
                    ? `
                    <div class="ic-v4-section" style="padding:8px 10px;border-radius:9px;background:var(--ic-surface);border:1px solid var(--ic-border);">
                      <div class="ic-v4-row-head">
                        <span>文章配图（封面+插图）</span>
                      </div>
                      <label style="display:flex;align-items:center;gap:6px;font-size:11.5px;margin-top:2px;cursor:pointer;">
                        <input type="checkbox" data-ctrl-inc-cover="${esc(n.id)}" ${cd.includeCover !== false ? "checked" : ""} />
                        <span>包含首图封面卡片</span>
                      </label>
                      <div class="${cd.includeCover !== false ? "ic-v4-slot-grid" : ""}" style="margin-top:4px;">
                        ${
                          cd.includeCover !== false
                            ? `
                            <div class="ic-v4-section">
                              <span style="font-size:10.5px;color:var(--ic-muted);">封面比例（可选或自填）</span>
                              <input type="text" list="ic-datalist-ratios" class="ic-v4-mini-inp" data-ctrl-cov-ratio="${esc(n.id)}" data-canvas-no-zoom value="${esc(cd.coverRatio || "2.35:1")}" placeholder="如 2.35:1 或 5:2" />
                            </div>
                          `
                            : ""
                        }
                        <div class="ic-v4-section">
                          <span style="font-size:10.5px;color:var(--ic-muted);">插图比例（可选或自填）</span>
                          <input type="text" list="ic-datalist-ratios" class="ic-v4-mini-inp" data-ctrl-inl-ratio="${esc(n.id)}" data-canvas-no-zoom value="${esc(cd.inlineRatio || "4:3")}" placeholder="如 4:3 或 16:10" />
                        </div>
                      </div>
                    </div>
                  `
                    : (() => {
                        const curRatio = cd.ratio || "3:4";
                        const isCustomRatio = Boolean(curRatio && !E.RATIO_PRESETS.includes(curRatio));
                        return `
                        <div class="ic-v4-section">
                          <div class="ic-count-row">
                            <span style="font-size:11.5px;font-weight:800;color:var(--ic-ink);">${
                              rec.loopNode ? "每轮张数" : "图片数量"
                            }</span>
                            <div class="ic-count-custom-box" title="自主调节或直接填写图片数量 (1~200 张，>6张自动聚合为1个批量图集节点)">
                              <button type="button" class="ic-count-step-btn" data-ctrl-count-step="${esc(n.id)}" data-delta="-1">−</button>
                              <input type="number" min="1" max="200" step="1" class="ic-count-inp" data-ctrl-count-inp="${esc(n.id)}" value="${curCount}" data-canvas-no-zoom />
                              <button type="button" class="ic-count-step-btn" data-ctrl-count-step="${esc(n.id)}" data-delta="1">＋</button>
                              <span style="font-size:10.8px;color:var(--ic-muted);font-weight:750;padding-left:2px;">张</span>
                            </div>
                          </div>
                          ${
                            rec.loopNode
                              ? `<div style="font-size:10.8px;color:#0f766e;font-weight:800;">循环 ${plan.loopCount || 0} 轮 × 每轮 ${curCount} 张 = 批量共出 ${plan.specs.length} 张</div>`
                              : ""
                          }
                          ${
                            plan.specs.length > BATCH_GALLERY_THRESHOLD
                              ? `<div style="font-size:10.5px;color:#1f6f4a;font-weight:750;">超过 ${BATCH_GALLERY_THRESHOLD} 张：右侧自动聚合为 1 个「批量图集」节点，画布零爆炸</div>`
                              : ""
                          }
                          ${
                            curMode === "series"
                              ? `
                              <label style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--ic-muted);margin-top:2px;cursor:pointer;">
                                <input type="checkbox" data-ctrl-mix-lay="${esc(n.id)}" ${cd.mixLayouts !== false ? "checked" : ""} />
                                <span>成套自动混排不同卡片图型</span>
                              </label>
                            `
                              : ""
                          }
                        </div>
                        <div class="ic-v4-section">
                          <div class="ic-v4-row-head">
                            <span>画幅比例</span>
                            <div class="ic-ratio-custom-wrap ${isCustomRatio ? "is-custom-active" : ""}" title="除下方预置外，可直接填写任意画幅比例（如 5:2、21:9、2:3）">
                              <span class="ic-ratio-custom-lbl">自定义</span>
                              <input
                                type="text"
                                class="ic-ratio-custom-inp"
                                data-ctrl-ratio-inp="${esc(n.id)}"
                                data-canvas-no-zoom
                                value="${esc(isCustomRatio ? curRatio : "")}"
                                placeholder="如 5:2"
                              />
                            </div>
                          </div>
                          <div class="ic-ctrl-seg">
                            ${E.RATIO_PRESETS.map(
                              (r) => `<button type="button" class="ic-ctrl-pill ${curRatio === r ? "is-active" : ""}" data-ctrl-ratio="${esc(n.id)}" data-val="${r}">${r}</button>`
                            ).join("")}
                          </div>
                        </div>
                      `;
                      })()
                }

                <p class="qc-advanced-cost" role="status">${esc(generationCostText(plan.specs.length))}<br>资源解锁费用另计。</p>
                <button type="button" class="ic-ctrl-generate-btn" data-ctrl-run="${esc(n.id)}" ${cd.status === "generating" ? "disabled" : ""}>
                  ${
                    cd.status === "generating"
                      ? "运行中…"
                      : plan.kind === "loop"
                        ? `批量运行 (共 ${plan.specs.length} 张)`
                        : plan.specs.length > 1 && curMode !== "article-illust"
                          ? `批量运行 (共 ${plan.specs.length} 张)`
                          : "运行"
                  }
                </button>
              </div>

              <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="接收上游输入节点、批量或多尺寸输出节点">
                <span class="ic-port-dot">+</span>
              </div>
              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="输出「文章配图方案」、「成图显示」或「批量图集」节点">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 4.5) ARTICLE PLAN NODE (文章配图方案：仅保留一个「查看文章」按钮) -------- */
        if (n.type === "article_plan") {
          const pd = n.data || {};
          const orderedCards = sortPlanCardsInDocOrder(pd.cards || []);
          const doneCount = orderedCards.filter((c) => c.imageUrl).length;
          const previewCards = orderedCards.slice(0, 4);

          return `
            <div class="ic-node ic-node-article_plan ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}" title="点击查看文章并编排配图方案">
              <div class="ic-node-header-above">
                <span>文章配图方案</span>
                <span class="ic-node-badge ic-badge-output-disp">${pd.status === "generating" ? "运行中" : `共 ${orderedCards.length} 卡 · 已出 ${doneCount}`}</span>
              </div>

              <div class="ic-v4-card">
                <div style="padding:7px 9px;border-radius:9px;background:rgba(31,111,74,0.07);border:1px solid rgba(31,111,74,0.22);">
                  <div style="font-size:12.5px;font-weight:850;color:var(--ic-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${esc(pd.articleTitle || "文章配图方案")}
                  </div>
                  <div style="font-size:10.5px;color:var(--ic-muted);margin-top:1px;">
                    桌面宽屏排版 · 支持拖动排序与点击卡片改词
                  </div>
                </div>

                <div class="ic-aplan-mini-list">
                  ${
                    previewCards.length
                      ? previewCards
                          .map((c, idx) => {
                            const isCov = c.role === "cover";
                            const shortPrompt = String(c.prompt || "").replace(/\s+/g, " ").trim();
                            return `
                              <div class="ic-aplan-mini-row">
                                <span class="ic-plan-role-badge ${isCov ? "is-cover" : "is-inline"}" style="font-size:9.5px;padding:1px 6px;">
                                  ${isCov ? "封面" : `插图${idx + 1}`}
                                </span>
                                ${
                                  c.imageUrl
                                    ? `<img src="${esc(c.imageUrl)}" alt="" style="width:28px;height:20px;border-radius:4px;object-fit:cover;flex-shrink:0;border:1px solid var(--ic-border);" />`
                                    : ""
                                }
                                <span style="min-width:0;flex:1;font-size:11.2px;font-weight:750;color:var(--ic-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                  ${esc(c.title || shortPrompt || "配图位")}
                                </span>
                                <span style="font-size:10px;font-family:var(--font-mono);color:${c.imageUrl ? "#1f6f4a" : "var(--ic-muted)"};flex-shrink:0;">
                                  ${c.imageUrl ? "✓" : "○"} ${esc(c.ratio || "4:3")}
                                </span>
                              </div>
                            `;
                          })
                          .join("")
                      : `<div style="padding:12px;text-align:center;font-size:11.5px;color:var(--ic-muted);">点击下方按钮查看文章并添加配图卡片</div>`
                  }
                  ${
                    orderedCards.length > 4
                      ? `<div style="font-size:10.5px;color:var(--ic-muted);text-align:center;padding-top:2px;">… 另有 ${orderedCards.length - 4} 个配图卡片</div>`
                      : ""
                  }
                </div>

                <button type="button" class="ic-ctrl-generate-btn" data-plan-open-wide="${esc(n.id)}" style="background:#1f6f4a;box-shadow:0 4px 12px rgba(31,111,74,0.22);">
                  查看文章
                </button>
              </div>

              <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="来自左侧「生成设置」节点">
                <span class="ic-port-dot">+</span>
              </div>
              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="自动连接右侧已生成的「成图显示」节点">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        /* -------- 5) AUTO-SPAWNED DISPLAY NODE (≤6张一图一节点；>6张自动收纳为1个分页「批量图集」节点) -------- */
        if (n.type === "output_display") {
          const dd = n.data || {};
          const items = Array.isArray(dd.items) ? dd.items : [];
          const it = items[0] || null;
          const upEdge = CS.graph.edges.find((e) => e.to === n.id);
          const upParentId = upEdge ? upEdge.from : "";
          const isGallery =
            dd.kind === "batch_gallery" ||
            items.length > 1 ||
            (Number(dd.totalTarget) || 0) > BATCH_GALLERY_THRESHOLD;

          if (isGallery) {
            const pageSize = 9;
            const totalPages = Math.max(1, Math.ceil(Math.max(1, items.length) / pageSize));
            const curPage = Math.min(totalPages, Math.max(1, Math.round(Number(dd.page) || 1)));
            const sliceStart = (curPage - 1) * pageSize;
            const pageItems = items.slice(sliceStart, sliceStart + pageSize);

            return `
              <div class="ic-node ic-node-output_display ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
                <div class="ic-node-header-above">
                  <span>批量图集</span>
                  <span class="ic-node-badge ic-badge-output-disp">${
                    dd.status === "generating" ? "批量生成中" : `共 ${items.length} 张`
                  }</span>
                </div>

                <div class="ic-v4-card" style="position:relative;">
                  ${
                    dd.status === "generating"
                      ? `
                      <div style="padding:24px 14px;border-radius:10px;background:rgba(31,111,74,0.06);border:1px dashed rgba(31,111,74,0.38);text-align:center;display:flex;flex-direction:column;align-items:center;gap:6px;">
                        <div style="font-size:12.5px;font-weight:850;color:#1f6f4a;" data-gal-prog-for="${esc(n.id)}">
                          正在批量出图 ${items.length} / ${dd.totalTarget || items.length || 100} 张…
                        </div>
                        <div style="font-size:10.8px;color:var(--ic-muted);">所有成图自动汇聚于此节点，无需堆叠百个显示框</div>
                      </div>
                    `
                      : items.length > 0
                        ? `
                        <div class="ic-disp-gallery-grid">
                          ${pageItems
                            .map((gIt, gIdx) => {
                              const absIdx = sliceStart + gIdx;
                              return `
                                <div class="ic-disp-gal-cell" data-disp-zoom="${esc(gIt.imageUrl)}" data-disp-title="${esc(gIt.title || `成图 #${absIdx + 1}`)}" title="第 ${absIdx + 1} 张 · ${esc(gIt.title || "")}">
                                  <img data-hw-src="${esc(gIt.imageUrl)}" alt="${esc(gIt.title || "")}" loading="lazy" />
                                  <span class="ic-disp-gal-idx">#${String(absIdx + 1).padStart(2, "0")}</span>
                                  ${gIt.demoMode ? '<span style="position:absolute;right:4px;top:4px;padding:1px 4px;border-radius:4px;background:#fff0bf;color:#7a4d00;font-size:9px;font-weight:900;">演示</span>' : ""}
                                </div>
                              `;
                            })
                            .join("")}
                        </div>
                        <div class="ic-disp-gal-pager">
                          <button type="button" class="ic-opt-pill" data-disp-gal-page="${esc(n.id)}" data-delta="-1" ${curPage <= 1 ? "disabled" : ""} style="padding:2px 8px;font-size:10.8px;">‹ 上页</button>
                          <span>第 ${curPage} / ${totalPages} 页 · 共 ${items.length} 张</span>
                          <button type="button" class="ic-opt-pill" data-disp-gal-page="${esc(n.id)}" data-delta="1" ${curPage >= totalPages ? "disabled" : ""} style="padding:2px 8px;font-size:10.8px;">下页 ›</button>
                        </div>
                        <div class="ic-disp-deliverable-bar">
                          <div style="display:flex;gap:6px;">
                            <button type="button" class="btn btn-sm" data-disp-open-gal="${esc(n.id)}" style="flex:1.18;font-weight:800;">百图画廊</button>
                            <button type="button" class="btn btn-sm" data-disp-zip="${esc(n.id)}" style="flex:1;">ZIP</button>
                          </div>
                        </div>
                      `
                        : `
                        <div style="padding:28px 14px;border-radius:10px;background:var(--ic-surface);border:1px dashed var(--ic-border);text-align:center;font-size:11.5px;color:var(--ic-muted);">
                          等待上游批量运行出图（成图将自动分页收纳于此）…
                        </div>
                      `
                  }
                </div>

                <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="来自左侧「生成设置」节点">
                  <span class="ic-port-dot">+</span>
                </div>
                <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="可将图集首图连入下游新的「生成设置」节点">
                  <span class="ic-port-dot">+</span>
                </div>
              </div>
            `;
          }

          return `
            <div class="ic-node ic-node-output_display ${isSel ? "is-selected" : ""} ${isRel ? "is-related" : ""}" data-node-id="${esc(n.id)}" style="${posStyle}">
              <div class="ic-node-header-above">
                <span>成图显示</span>
                <span class="ic-node-badge ic-badge-output-disp">${dd.status === "generating" ? "生成中" : it?.demoMode ? "演示样图" : esc(it?.ratio || "成图")}</span>
              </div>

              <div class="ic-v4-card" style="position:relative;">
                ${
                  dd.status === "generating"
                    ? `
                    <div style="padding:32px 16px;border-radius:10px;background:var(--ic-surface);border:1px dashed var(--ic-border-strong);text-align:center;display:flex;flex-direction:column;align-items:center;gap:6px;">
                      <div style="font-size:12.5px;font-weight:850;">正在生成图片…</div>
                      <div style="font-size:11px;font-family:var(--font-mono);color:var(--ic-muted);" data-timer-for="${esc(n.id)}">${dd.elapsedSec || 0}s</div>
                    </div>
                  `
                    : it && it.imageUrl
                      ? `
                      <div class="ic-disp-single-wrap">
                        <img src="${esc(it.imageUrl)}" alt="${esc(it.title || "生成图片")}" data-disp-zoom="${esc(it.imageUrl)}" data-disp-title="${esc(it.title || "生成图片")}" />
                        <div style="position:absolute;right:8px;top:8px;display:flex;gap:5px;">
                          <button type="button" class="ic-mini-glass-btn" data-disp-zoom="${esc(it.imageUrl)}" data-disp-title="${esc(it.title || "生成图片")}">放大</button>
                          ${upParentId ? `<button type="button" class="ic-mini-glass-btn" data-disp-regen-node="${esc(n.id)}" title="单张重绘此节点">重绘</button>` : ""}
                        </div>
                      </div>
                      <div class="ic-disp-deliverable-bar">
                        <div style="font-size:11.5px;font-weight:800;color:var(--ic-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${esc(it.title || "生成图片")}">
                          ${esc(it.title || "生成图片")}
                        </div>
                        <div style="display:flex;gap:6px;">
                          <a class="btn btn-sm" href="${esc(it.imageUrl)}" download="handraw-output.webp" style="flex:1;text-align:center;">下载</a>
                        </div>
                      </div>
                    `
                      : `
                      <div style="padding:28px 14px;border-radius:10px;background:var(--ic-surface);border:1px dashed var(--ic-border);text-align:center;font-size:11.5px;color:var(--ic-muted);">
                        等待上游节点运行出图…
                      </div>
                    `
                }
              </div>

              <div class="ic-port-zone is-in" data-port-node="${esc(n.id)}" data-port-dir="in" title="来自左侧「生成设置」或「文章配图方案」节点">
                <span class="ic-port-dot">+</span>
              </div>
              <div class="ic-port-zone is-out" data-port-node="${esc(n.id)}" data-port-dir="out" title="可将此成图作为参考图参连入下游新的「生成设置」节点继续改图">
                <span class="ic-port-dot">+</span>
              </div>
            </div>
          `;
        }

        return "";
      })
      .join("");

    const datalistsHtml = `
      <datalist id="${audDatalistId}">
        ${(CS.recentAudiences || []).slice(0, 8).map((v) => `<option value="${esc(v)}"></option>`).join("")}
      </datalist>
      <datalist id="${sceneDatalistId}">
        ${(CS.recentBusinessScenes || []).slice(0, 8).map((v) => `<option value="${esc(v)}"></option>`).join("")}
      </datalist>
      <datalist id="ic-datalist-ratios">
        ${E.RATIO_PRESETS.map((r) => `<option value="${esc(r)}"></option>`).join("")}
      </datalist>
    `;

    DOM.nodesLayer.innerHTML = cardsHtml + datalistsHtml;

    // Sync actual rendered DOM heights back to node.h so port positions, wires, minimap & fitView are pixel-accurate!
    const elById = new Map();
    DOM.nodesLayer.querySelectorAll(".ic-node[data-node-id]").forEach((el) => {
      const nid = el.getAttribute("data-node-id");
      elById.set(nid, el);
      const n = getNodeById(nid);
      if (n && el.offsetHeight > 20) {
        n.h = el.offsetHeight;
        n.w = el.offsetWidth;
      }
    });

    // Prevent vertical collisions when a variable-height node (e.g. 风格参数 enabling 双画风融合 or multi-select chips) expands!
    const sortedByY = [...(CS.graph.nodes || [])].sort((a, b) => a.y - b.y || a.x - b.x);
    for (let i = 0; i < sortedByY.length; i++) {
      const upper = sortedByY[i];
      for (let j = i + 1; j < sortedByY.length; j++) {
        const lower = sortedByY[j];
        const xOverlap = Math.min(upper.x + (upper.w || 320), lower.x + (lower.w || 320)) - Math.max(upper.x, lower.x);
        if (xOverlap > 80) {
          const minLowerY = upper.y + (upper.h || 240) + 56;
          if (lower.y < minLowerY) {
            lower.y = snapVal(minLowerY);
            const lowerEl = elById.get(lower.id);
            if (lowerEl) lowerEl.style.top = `${lower.y}px`;
          }
        }
      }
    }

    renderEdgesSvg();
    bindNodeInteriorActions();
  }

  function bindNodeInteriorActions() {
    if (!DOM.nodesLayer) return;

    /* --- 1. Skill Params Actions --- */
    DOM.nodesLayer.querySelectorAll("[data-sp-fusion]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-sp-fusion"));
        if (!n) return;
        pushUndo();
        n.data.fusion = btn.getAttribute("data-val") === "1";
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-pick]").forEach((el) => {
      el.onclick = (e) => {
        if (e.target.closest("[data-sp-clear-field]")) return;
        e.stopPropagation();
        const n = getNodeById(el.getAttribute("data-sp-pick"));
        const field = el.getAttribute("data-sp-field");
        if (n && field) openSkillFieldPickerModal(n, field);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-clear-field]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-sp-clear-field"));
        const field = btn.getAttribute("data-sp-field");
        if (!n || !field) return;
        pushUndo();
        n.data[field] = "";
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-rm-arr]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-sp-rm-arr"));
        const field = btn.getAttribute("data-field");
        const val = btn.getAttribute("data-val");
        if (!n || !Array.isArray(n.data[field])) return;
        pushUndo();
        n.data[field] = n.data[field].filter((x) => x !== val);
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-ws]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-sp-ws"));
        if (!n) return;
        pushUndo();
        n.data.whitespace = btn.getAttribute("data-val");
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-aud]").forEach((inp) => {
      inp.oninput = () => {
        const n = getNodeById(inp.getAttribute("data-sp-aud"));
        if (n) {
          n.data.audience = inp.value;
          markActiveTabDirty();
        }
      };
      const commitAudience = () => {
        const n = getNodeById(inp.getAttribute("data-sp-aud"));
        if (!n) return;
        const val = inp.value.trim();
        n.data.audience = val;
        if (val) recordRecentFieldValue("audience", val);
        persistOpenTabs();
      };
      inp.onchange = commitAudience;
      inp.onblur = commitAudience;
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-scene]").forEach((inp) => {
      inp.oninput = () => {
        const n = getNodeById(inp.getAttribute("data-sp-scene"));
        if (n) {
          n.data.businessScene = inp.value;
          markActiveTabDirty();
        }
      };
      const commitScene = () => {
        const n = getNodeById(inp.getAttribute("data-sp-scene"));
        if (!n) return;
        const val = inp.value.trim();
        n.data.businessScene = val;
        if (val) recordRecentFieldValue("businessScene", val);
        persistOpenTabs();
      };
      inp.onchange = commitScene;
      inp.onblur = commitScene;
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-sc021]").forEach((sel) => {
      sel.onchange = () => {
        const n = getNodeById(sel.getAttribute("data-sp-sc021"));
        if (n) {
          n.data.sc021Type = sel.value;
          markActiveTabDirty();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-sc022-name]").forEach((inp) => {
      inp.oninput = () => {
        const n = getNodeById(inp.getAttribute("data-sp-sc022-name"));
        if (n) n.data.sc022Name = inp.value;
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-sc022-py]").forEach((inp) => {
      inp.oninput = () => {
        const n = getNodeById(inp.getAttribute("data-sp-sc022-py"));
        if (n) n.data.sc022Pinyin = inp.value;
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-sp-reset-all]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-sp-reset-all"));
        if (!n) return;
        pushUndo();
        Object.assign(n.data, {
          fusion: false,
          style1: "",
          style2: "",
          layout: "",
          colors: [],
          tones: [],
          moods: [],
          customMood: "",
          whitespace: "",
          audience: "",
          businessScene: ""
        });
        fullRenderCanvas();
        persistOpenTabs();
        toast("已重置风格参数节点");
      };
    });

    /* --- 2. Asset Node Actions --- */
    DOM.nodesLayer.querySelectorAll("[data-ast-open]").forEach((el) => {
      el.onclick = (e) => {
        if (e.target.closest("[data-ast-clear]")) return;
        e.stopPropagation();
        const n = getNodeById(el.getAttribute("data-ast-open"));
        if (n) openAssetPickerModal(n);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ast-clear]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-ast-clear"));
        if (!n) return;
        pushUndo();
        n.data.items = [];
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    /* --- 3. Text Input + File Attachment Actions (Click textarea opens clean single-button modal!) --- */
    DOM.nodesLayer.querySelectorAll("[data-txt-ta]").forEach((ta) => {
      ta.onclick = (e) => {
        e.stopPropagation();
        const nid = ta.getAttribute("data-txt-ta");
        if (nid) openTextEditModal(nid);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-txt-file]").forEach((inp) => {
      inp.onchange = (e) => {
        const f = e.target.files && e.target.files[0];
        const n = getNodeById(inp.getAttribute("data-txt-file"));
        if (!f || !n) return;
        const reader = new FileReader();
        reader.onload = () => {
          pushUndo();
          n.data.fileName = f.name;
          n.data.fileContent = String(reader.result || "");
          n.data.fileSize = f.size || n.data.fileContent.length;
          inp.value = "";
          fullRenderCanvas();
          persistOpenTabs();
          toast(`📎 已添加文件附件《${f.name}》`);
        };
        reader.readAsText(f);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-txt-clear-file]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-txt-clear-file"));
        if (!n) return;
        pushUndo();
        n.data.fileName = "";
        n.data.fileContent = "";
        n.data.fileSize = 0;
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    /* --- 3.4. Fission Node Actions (💡 选题裂变) --- */
    const regenFissionNode = (n, showToast = false) => {
      if (!n || n.type !== "fission") return;
      const cnt = Math.max(1, Math.min(200, Math.round(Number(n.data.targetCount) || 10)));
      n.data.targetCount = cnt;
      n.data.generatedItems = E.generateFissionTopics(
        n.data.seedTopic || "手绘视觉专题",
        n.data.strategy || "daily_quote",
        cnt,
        n.data.customStrategy || ""
      );
      CS.graph.edges
        .filter((ed) => ed.from === n.id)
        .map((ed) => getNodeById(ed.to))
        .filter((dn) => dn && dn.type === "loop")
        .forEach((lp) => {
          lp.data.manualOverrideFission = false;
          lp.data.loopMode = "prompts";
        });
      fullRenderCanvas();
      persistOpenTabs();
      if (showToast) {
        toast(`已扩写生成 ${cnt} 条不重样子主题！`);
      }
    };

    DOM.nodesLayer.querySelectorAll("[data-fis-seed]").forEach((inp) => {
      inp.oninput = () => {
        const n = getNodeById(inp.getAttribute("data-fis-seed"));
        if (n) {
          n.data.seedTopic = inp.value;
          markActiveTabDirty();
        }
      };
      const commitSeed = () => {
        const n = getNodeById(inp.getAttribute("data-fis-seed"));
        if (!n) return;
        pushUndo();
        n.data.seedTopic = inp.value.trim() || "手绘视觉专题";
        regenFissionNode(n, false);
      };
      inp.onchange = commitSeed;
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-fis-strat]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-fis-strat"));
        const nextStrat = btn.getAttribute("data-val");
        if (!n || !nextStrat) return;
        pushUndo();
        n.data.strategy = nextStrat;
        n.data.customStrategy = "";
        regenFissionNode(n, false);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-fis-custom-strat]").forEach((inp) => {
      inp.oninput = () => {
        const n = getNodeById(inp.getAttribute("data-fis-custom-strat"));
        if (n) {
          n.data.customStrategy = inp.value;
          markActiveTabDirty();
        }
      };
      const commitCustomStrat = () => {
        const n = getNodeById(inp.getAttribute("data-fis-custom-strat"));
        if (!n) return;
        pushUndo();
        n.data.customStrategy = inp.value.trim();
        regenFissionNode(n, Boolean(n.data.customStrategy));
      };
      inp.onchange = commitCustomStrat;
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-fis-cnt-step]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-fis-cnt-step"));
        if (!n) return;
        pushUndo();
        const delta = Number(btn.getAttribute("data-delta") || 0);
        const cur = Math.max(1, Math.min(200, Math.round(Number(n.data.targetCount) || 10)));
        n.data.targetCount = Math.max(1, Math.min(200, cur + delta));
        regenFissionNode(n, false);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-fis-cnt-inp]").forEach((inp) => {
      inp.onchange = () => {
        const n = getNodeById(inp.getAttribute("data-fis-cnt-inp"));
        if (!n) return;
        pushUndo();
        n.data.targetCount = Math.max(1, Math.min(200, Math.round(Number(inp.value) || 10)));
        regenFissionNode(n, true);
      };
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-fis-gen]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-fis-gen"));
        if (!n) return;
        pushUndo();
        regenFissionNode(n, true);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-fis-open-modal]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openFissionListModal(el.getAttribute("data-fis-open-modal"));
      };
    });

    /* --- 3.5. Bridge Node Actions --- */
    DOM.nodesLayer.querySelectorAll("[data-bridge-add-ctrl]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        spawnDownstreamControlFromBridge(btn.getAttribute("data-bridge-add-ctrl"));
      };
    });

    /* --- 3.6. Loop Batch Node Actions --- */
    DOM.nodesLayer.querySelectorAll("[data-loop-mode]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-loop-mode"));
        const nextMode = btn.getAttribute("data-val");
        if (!n || !nextMode) return;
        pushUndo();
        n.data.loopMode = nextMode;
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-ta]").forEach((ta) => {
      ta.oninput = () => {
        const n = getNodeById(ta.getAttribute("data-loop-ta"));
        if (!n) return;
        n.data.promptListText = ta.value;
        n.data.manualOverrideFission = Boolean(ta.value.trim());
        if (ta.value.trim()) n.data.splitUpstreamText = true;
        markActiveTabDirty();
        const downCtrls = CS.graph.edges
          .filter((e) => e.from === n.id)
          .map((e) => getNodeById(e.to))
          .filter((x) => x && x.type === "output_control");
        const effRec = downCtrls.length ? E.resolveControlRecipe(CS.graph, downCtrls[0], Catalog) : E.resolveControlRecipe(CS.graph, n, Catalog);
        const cnt = E.resolveLoopIterations(CS.graph, n, effRec, Catalog).length;
        const headBadge = DOM.nodesLayer.querySelector(`[data-loop-head-badge="${n.id}"]`);
        const lineCnt = DOM.nodesLayer.querySelector(`[data-loop-line-cnt="${n.id}"]`);
        const readyHint = DOM.nodesLayer.querySelector(`[data-loop-ready-hint="${n.id}"]`);
        if (headBadge) headBadge.textContent = `共 ${cnt} 轮`;
        if (lineCnt) lineCnt.textContent = `批量文案（共 ${cnt} 条 · 每行 1 张）`;
        if (readyHint && n.data.status !== "running") {
          readyHint.textContent = `已编排 ${cnt} 轮队列 · 由右侧「生成设置」统一触发运行`;
        }
        downCtrls.forEach((dc) => {
          const ctrlBtn = DOM.nodesLayer.querySelector(`[data-ctrl-run="${dc.id}"]`);
          if (ctrlBtn && dc.data?.status !== "generating") {
            const perRound = Math.max(1, Math.min(200, Math.round(Number(dc.data?.count) || 1)));
            ctrlBtn.textContent = `批量运行 (共 ${Math.min(200, cnt * perRound)} 张)`;
          }
        });
      };
      ta.onblur = () => {
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-open-prompts]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        openLoopPromptsModal(btn.getAttribute("data-loop-open-prompts"));
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-clear-prompts]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-loop-clear-prompts"));
        if (!n) return;
        pushUndo();
        n.data.promptListText = "";
        n.data.manualOverrideFission = false;
        n.data.splitUpstreamText = false;
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-fill-demo]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-loop-fill-demo"));
        if (!n) return;
        pushUndo();
        n.data.promptListText = E.DEFAULT_LOOP_PROMPT_LINES.join("\n");
        n.data.manualOverrideFission = true;
        n.data.splitUpstreamText = true;
        fullRenderCanvas();
        persistOpenTabs();
        toast("已填入 4 条节气出图示例");
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-pick]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(el.getAttribute("data-loop-pick"));
        const kind = el.getAttribute("data-kind") || "styles";
        if (n) openLoopMultiPickerModal(n, kind);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-rand]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-loop-rand"));
        const kind = btn.getAttribute("data-kind") || "styles";
        if (!n) return;
        pushUndo();
        const pool = kind === "styles" ? Catalog.styles : Catalog.layouts;
        const freeFirst = pool.filter((x) => x.tier !== "pro_credit");
        const src = freeFirst.length >= 4 ? freeFirst : pool;
        const picks = [...src].sort(() => Math.random() - 0.5).slice(0, 4).map((x) => x.id);
        if (kind === "styles") {
          n.data.styleIds = picks;
          n.data.loopMode = "styles";
        } else {
          n.data.layoutIds = picks;
          n.data.loopMode = "layouts";
        }
        fullRenderCanvas();
        persistOpenTabs();
        toast(`已随机挑选 4 款${kind === "styles" ? "画风" : "图型"}加入批量队列`);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-rm-item]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-loop-rm-item"));
        const kind = btn.getAttribute("data-kind");
        const val = btn.getAttribute("data-val");
        if (!n || !val) return;
        pushUndo();
        if (kind === "styles") {
          n.data.styleIds = (n.data.styleIds || []).filter((x) => x !== val);
        } else {
          n.data.layoutIds = (n.data.layoutIds || []).filter((x) => x !== val);
        }
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-clear-arr]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(btn.getAttribute("data-loop-clear-arr"));
        const kind = btn.getAttribute("data-kind");
        if (!n) return;
        pushUndo();
        if (kind === "styles") n.data.styleIds = [];
        else n.data.layoutIds = [];
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-setup-assets]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        const n = getNodeById(el.getAttribute("data-loop-setup-assets"));
        if (!n) return;
        const rec = E.resolveControlRecipe(CS.graph, n, Catalog);
        let astNode = rec.assetNode;
        if (!astNode) {
          pushUndo();
          astNode = E.makeAssetNode(snapVal(Math.max(48, n.x - 416)), snapVal(n.y));
          CS.graph.nodes.push(astNode);
          ensureEdge(astNode.id, n.id);
          fullRenderCanvas();
          persistOpenTabs();
        }
        openAssetPickerModal(astNode);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-loop-add-ctrl]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        spawnDownstreamControlFromLoop(btn.getAttribute("data-loop-add-ctrl"));
      };
    });

    /* --- 4. Output Control Node Actions --- */
    DOM.nodesLayer.querySelectorAll("[data-ctrl-mode]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const ctrl = getNodeById(btn.getAttribute("data-ctrl-mode"));
        const nextMode = btn.getAttribute("data-val");
        if (ctrl && nextMode) switchOutputControlMode(ctrl, nextMode);
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-count-step]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const ctrl = getNodeById(btn.getAttribute("data-ctrl-count-step"));
        if (!ctrl) return;
        pushUndo();
        const delta = Number(btn.getAttribute("data-delta") || 0);
        const cur = Math.max(1, Math.min(200, Math.round(Number(ctrl.data.count || 1))));
        ctrl.data.count = Math.max(1, Math.min(200, cur + delta));
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-count-inp]").forEach((inp) => {
      inp.oninput = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-count-inp"));
        if (!ctrl) return;
        const raw = Number(inp.value);
        if (!Number.isFinite(raw) || raw < 1) return;
        const clamped = Math.max(1, Math.min(200, Math.round(raw)));
        ctrl.data.count = clamped;
        markActiveTabDirty();
        renderWorkbenchBar();
      };
      inp.onchange = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-count-inp"));
        if (!ctrl) return;
        pushUndo();
        const clamped = Math.max(1, Math.min(200, Math.round(Number(inp.value) || 1)));
        ctrl.data.count = clamped;
        fullRenderCanvas();
        persistOpenTabs();
      };
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-mix-lay]").forEach((chk) => {
      chk.onchange = () => {
        const ctrl = getNodeById(chk.getAttribute("data-ctrl-mix-lay"));
        if (!ctrl) return;
        ctrl.data.mixLayouts = chk.checked;
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-ratio]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const ctrl = getNodeById(btn.getAttribute("data-ctrl-ratio"));
        if (!ctrl) return;
        pushUndo();
        ctrl.data.ratio = btn.getAttribute("data-val") || "3:4";
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-ratio-inp]").forEach((inp) => {
      inp.oninput = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-ratio-inp"));
        if (!ctrl) return;
        const norm = normalizeRatioInput(inp.value);
        const wrap = inp.closest(".ic-ratio-custom-wrap");
        if (isValidRatioInput(norm)) {
          ctrl.data.ratio = norm;
          markActiveTabDirty();
          const isPreset = E.RATIO_PRESETS.includes(norm);
          if (wrap) wrap.classList.toggle("is-custom-active", !isPreset);
          DOM.nodesLayer.querySelectorAll(`[data-ctrl-ratio="${ctrl.id}"]`).forEach((b) => {
            b.classList.toggle("is-active", b.getAttribute("data-val") === norm);
          });
        }
      };
      inp.onchange = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-ratio-inp"));
        if (!ctrl) return;
        const norm = normalizeRatioInput(inp.value);
        if (!norm) {
          if (!E.RATIO_PRESETS.includes(ctrl.data.ratio)) {
            pushUndo();
            ctrl.data.ratio = E.DEFAULT_MODE_RATIOS[ctrl.data.mode] || "3:4";
            fullRenderCanvas();
            persistOpenTabs();
          }
          return;
        }
        if (!isValidRatioInput(norm)) {
          toast("画幅比例请按「宽:高」格式填写，如 5:2、21:9 或 2:3");
          fullRenderCanvas();
          return;
        }
        pushUndo();
        ctrl.data.ratio = norm;
        fullRenderCanvas();
        persistOpenTabs();
      };
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-inc-cover]").forEach((chk) => {
      chk.onchange = () => {
        const ctrl = getNodeById(chk.getAttribute("data-ctrl-inc-cover"));
        if (!ctrl) return;
        pushUndo();
        ctrl.data.includeCover = chk.checked;
        const planNode = getDownstreamArticlePlanNode(ctrl);
        if (planNode && Array.isArray(planNode.data.cards)) {
          if (!chk.checked) {
            planNode.data.cards = planNode.data.cards.filter((c) => c.role !== "cover");
          } else if (!planNode.data.cards.some((c) => c.role === "cover")) {
            const built = E.buildArticlePlanData(planNode.data.markdown || "", ctrl, CS.graph, Catalog);
            const cov = built.cards.find((c) => c.role === "cover");
            if (cov) planNode.data.cards.unshift(cov);
          }
        }
        fullRenderCanvas();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-cov-ratio]").forEach((inp) => {
      inp.oninput = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-cov-ratio"));
        if (!ctrl) return;
        const norm = normalizeRatioInput(inp.value);
        if (isValidRatioInput(norm)) {
          ctrl.data.coverRatio = norm;
          markActiveTabDirty();
        }
      };
      inp.onchange = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-cov-ratio"));
        if (!ctrl) return;
        const norm = normalizeRatioInput(inp.value);
        if (!isValidRatioInput(norm)) {
          toast("封面比例请按「宽:高」格式填写，如 2.35:1 或 5:2");
          fullRenderCanvas();
          return;
        }
        pushUndo();
        ctrl.data.coverRatio = norm;
        fullRenderCanvas();
        persistOpenTabs();
      };
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-inl-ratio]").forEach((inp) => {
      inp.oninput = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-inl-ratio"));
        if (!ctrl) return;
        const norm = normalizeRatioInput(inp.value);
        if (isValidRatioInput(norm)) {
          ctrl.data.inlineRatio = norm;
          markActiveTabDirty();
        }
      };
      inp.onchange = () => {
        const ctrl = getNodeById(inp.getAttribute("data-ctrl-inl-ratio"));
        if (!ctrl) return;
        const norm = normalizeRatioInput(inp.value);
        if (!isValidRatioInput(norm)) {
          toast("正文插图比例请按「宽:高」格式填写，如 4:3 或 16:10");
          fullRenderCanvas();
          return;
        }
        pushUndo();
        ctrl.data.inlineRatio = norm;
        fullRenderCanvas();
        persistOpenTabs();
      };
      inp.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          inp.blur();
        }
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-ctrl-run]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        runOutputControlNode(btn.getAttribute("data-ctrl-run"));
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-plan-open-wide]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        openArticlePlanWidePage(btn.getAttribute("data-plan-open-wide"));
      };
    });

    /* --- 5. Image Display Actions --- */
    DOM.nodesLayer.querySelectorAll("[data-disp-zoom]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        openImageLightbox(el.getAttribute("data-disp-zoom"), el.getAttribute("data-disp-title") || "输出大图");
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-disp-regen-node]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        regenerateDisplayNode(btn.getAttribute("data-disp-regen-node"));
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-disp-gal-page]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const disp = getNodeById(btn.getAttribute("data-disp-gal-page"));
        if (!disp) return;
        const items = Array.isArray(disp.data?.items) ? disp.data.items : [];
        const totalPages = Math.max(1, Math.ceil(Math.max(1, items.length) / 9));
        const delta = Number(btn.getAttribute("data-delta") || 0);
        const cur = Math.min(totalPages, Math.max(1, Math.round(Number(disp.data?.page) || 1)));
        const next = Math.min(totalPages, Math.max(1, cur + delta));
        if (next === cur) return;
        disp.data.page = next;
        renderWorldNodes();
        persistOpenTabs();
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-disp-open-gal]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        openBatchGalleryModal(btn.getAttribute("data-disp-open-gal"));
      };
    });

    DOM.nodesLayer.querySelectorAll("[data-disp-zip]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        exportZipPackage(btn.getAttribute("data-disp-zip"));
      };
    });
  }

  function getGraphemeSegments(str) {
    if (!str) return [];
    if (typeof Intl !== "undefined" && Intl.Segmenter) {
      const seg = new Intl.Segmenter(undefined, { granularity: "grapheme" });
      return Array.from(seg.segment(str), (s) => s.segment);
    }
    return Array.from(str);
  }

  function formatSubjectTitle(rawSubject) {
    if (!rawSubject) return "";
    const clean = String(rawSubject).trim().replace(/\s+/g, " ");
    if (!clean) return "";
    const chars = getGraphemeSegments(clean);
    if (chars.length > 40) {
      return chars.slice(0, 39).join("") + "…";
    }
    return clean;
  }

  function getNormalizedRecipeSnapshot(obj) {
    if (!obj) return null;
    const snap = obj.recipeSnapshot || obj;
    const s1 = String(snap.style1 || "").trim().toUpperCase().replace(/^#/, "");
    const s2 = String(snap.style2 || "").trim().toUpperCase().replace(/^#/, "");
    const lay = String(snap.layout || "").trim().toUpperCase().replace(/^#/, "");
    const subj = String(snap.subject != null ? snap.subject : (obj.subject != null ? obj.subject : "")).trim();
    if (!s1 && !s2 && !lay && !subj) return null;
    return {
      style1: s1,
      style1Name: snap.style1Name || (s1 && Catalog?.resourceMap?.get(s1)?.name) || "",
      style2: s2,
      style2Name: snap.style2Name || (s2 && Catalog?.resourceMap?.get(s2)?.name) || "",
      layout: lay,
      layoutName: snap.layoutName || (lay && Catalog?.resourceMap?.get(lay)?.name) || "",
      subject: subj
    };
  }

  function buildPublishTitleFromRecipe(snapshot) {
    if (!snapshot) return "Handraw 画布创作";
    const s1 = String(snapshot.style1 || "").trim().toUpperCase().replace(/^#/, "");
    const s2 = String(snapshot.style2 || "").trim().toUpperCase().replace(/^#/, "");
    const lay = String(snapshot.layout || "").trim().toUpperCase().replace(/^#/, "");

    const s1Res = s1 && Catalog?.resourceMap ? Catalog.resourceMap.get(s1) : null;
    const s2Res = s2 && Catalog?.resourceMap ? Catalog.resourceMap.get(s2) : null;
    const layRes = lay && Catalog?.resourceMap ? Catalog.resourceMap.get(lay) : null;

    const s1Name = String(snapshot.style1Name || s1Res?.name || s1Res?.title || "").trim();
    const s2Name = String(snapshot.style2Name || s2Res?.name || s2Res?.title || "").trim();
    const layName = String(snapshot.layoutName || layRes?.name || layRes?.title || "").trim();

    // 3. 融合：编号A＋编号B · 融合晒图 (有图型再追加图型编号)
    if (s1 && s2) {
      if (lay) {
        return `${s1}＋${s2}＋${lay} · 融合晒图`;
      }
      return `${s1}＋${s2} · 融合晒图`;
    }

    // 2 & 4. 默认格式：编号 名称 · 晒图 (有图型再追加图型编号)
    if (s1 || s2) {
      const code = s1 || s2;
      const name = (s1 ? s1Name : s2Name);
      const prefix = name ? `${code} ${name}` : code;
      if (lay) {
        return `${prefix}＋${lay} · 晒图`;
      }
      return `${prefix} · 晒图`;
    }

    // 5. 无画风：用图型编号及名称
    if (lay) {
      const prefix = layName ? `${lay} ${layName}` : lay;
      return `${prefix} · 晒图`;
    }

    // 8. 缺快照回退
    return "Handraw 画布创作";
  }

  function resolvePublishDefaultTitle(rawItems, dispNode, isPlan, isFromArticle) {
    // 1. 用户手动填写的发布标题、文章标题保留（手动标题上限 120）
    if (dispNode?.data?.titleSource === "manual" && dispNode.data?.title) {
      return String(dispNode.data.title).slice(0, 120);
    }
    if (isPlan && dispNode?.data?.articleTitleSource === "manual" && dispNode.data?.articleTitle) {
      return String(dispNode.data.articleTitle).slice(0, 120);
    }

    const itemsWithImg = (rawItems || []).filter((it) => it && it.imageUrl);
    if (!itemsWithImg.length) {
      if (isPlan && dispNode?.data?.articleTitleSource === "manual" && dispNode.data?.articleTitle) {
        return String(dispNode.data.articleTitle).slice(0, 120);
      }
      return "Handraw 画布创作";
    }

    const recipes = itemsWithImg.map(getNormalizedRecipeSnapshot);
    const validRecipes = recipes.filter(Boolean);

    // 2. 该图生成时保存的用户主题（subject）——最高优先的自动来源
    const firstSubject = (validRecipes[0] && validRecipes[0].subject) ||
                         (rawItems[0] && (rawItems[0].subject || rawItems[0].recipeSnapshot?.subject)) || "";
    if (firstSubject) {
      const formatted = formatSubjectTitle(firstSubject);
      if (formatted) {
        return formatted;
      }
    }

    // 4. 旧结果缺快照时用 Handraw 画布创作，不要猜编号
    if (!validRecipes.length) {
      return "Handraw 画布创作";
    }

    // 混合配方多图：多配方创作晒图
    if (itemsWithImg.length > 1) {
      const distinctKeys = new Set(
        recipes.map((r) => (r ? `${r.style1}|${r.style2}|${r.layout}` : "__none__"))
      );
      if (distinctKeys.size > 1) {
        return "多配方创作晒图";
      }
    }

    // 3. 配方快照标题（编号 名称 · 晒图）
    return buildPublishTitleFromRecipe(validRecipes[0]);
  }

  if (typeof window !== "undefined") {
    window.HandrawStudioPublish = {
      getNormalizedRecipeSnapshot,
      buildPublishTitleFromRecipe,
      resolvePublishDefaultTitle,
      formatSubjectTitle,
      resolveShareTitle
    };
    window.resolveShareTitle = resolveShareTitle;
  }

  /* ======================== FLOATING SELECTION BAR & ITEM DELETION ======================== */
  function positionFloatingOverlays() {
    if (!DOM.overlayLayer || !DOM.viewport) return;
    const vRect = DOM.viewport.getBoundingClientRect();
    const selNodes = (CS.graph.selectedIds || []).map(getNodeById).filter(Boolean);
    if (!selNodes.length) return;

    const topbarEl = DOM.overlayLayer.querySelector("[data-float-topbar]");
    if (!topbarEl) return;

    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity;
    for (const n of selNodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + (n.w || 320));
    }

    const centerScreen = worldToScreen((minX + maxX) * 0.5, minY);
    const leftSafe = CS.shelfOpen ? 236 : 20;
    const tbW = topbarEl.offsetWidth || 320;
    const cx = Math.max(leftSafe + tbW * 0.5, Math.min(vRect.width - 20 - tbW * 0.5, centerScreen.x));
    const ty = Math.max(54, Math.min(vRect.height - 96, centerScreen.y - 34));
    topbarEl.style.left = `${cx}px`;
    topbarEl.style.top = `${ty}px`;
  }

  function renderFloatingOverlays() {
    if (!DOM.overlayLayer) return;
    const htmlParts = [];

    if (CS.selectedEdgeId && CS.selectedEdgePt) {
      htmlParts.push(`
        <button type="button" class="ic-edge-unlink-btn" id="ic-unlink-edge-btn" style="pointer-events:auto;left:${CS.selectedEdgePt.x}px;top:${CS.selectedEdgePt.y}px;">
          断开此连线 (Del)
        </button>
      `);
    }

    const selNodes = (CS.graph.selectedIds || []).map(getNodeById).filter(Boolean);
    if (selNodes.length >= 1) {
      const single = selNodes.length === 1 ? selNodes[0] : null;
      const existingLoop = CS.graph.nodes.find((n) => n.type === "loop");
      const existingBridge = CS.graph.nodes.find((n) => n.type === "bridge");
      const linkTargetLabel = existingLoop ? "批量" : existingBridge ? "多尺寸输出" : "生成设置";
      htmlParts.push(`
        <div class="ic-node-topbar" data-float-topbar data-canvas-no-zoom>
          <span style="font-size:11.5px;font-weight:800;padding:0 6px;color:var(--ic-select);">
            ${single ? esc(single.title || single.type) : `已选 ${selNodes.length} 个节点`}
          </span>
          <div class="ic-divider-v"></div>
          ${
            single && isInputNodeType(single.type)
              ? `<button type="button" class="ic-icon-btn" id="ov-link-ctrl">连线到${linkTargetLabel}</button>`
              : ""
          }
          ${
            single && single.type === "loop"
              ? `<button type="button" class="ic-icon-btn is-active" id="ov-loop-add-ctrl">＋ 新增下游生成设置</button>`
              : ""
          }
          ${
            single && single.type === "bridge"
              ? `<button type="button" class="ic-icon-btn is-active" id="ov-bridge-add-ctrl">＋ 新增下游生成设置</button>`
              : ""
          }
          ${
            single && single.type === "output_control"
              ? `<button type="button" class="ic-icon-btn is-active" id="ov-run-ctrl">运行</button>`
              : ""
          }
          ${
            single && single.type === "article_plan"
              ? `<button type="button" class="ic-icon-btn is-active" id="ov-open-plan">查看文章</button>`
              : ""
          }
          ${
            single && single.type === "output_display"
              ? ""
              : ""
          }
          ${single && single.type !== "output_display" && single.type !== "article_plan" ? `<button type="button" class="ic-icon-btn" id="ov-dup">复制</button>` : ""}
          <button type="button" class="ic-icon-btn" id="ov-del" style="color:#dc2626;">删除</button>
        </div>
      `);
    }

    DOM.overlayLayer.innerHTML = htmlParts.join("");
    positionFloatingOverlays();

    const unlinkBtn = DOM.overlayLayer.querySelector("#ic-unlink-edge-btn");
    if (unlinkBtn) unlinkBtn.onclick = deleteSelectedItems;

    const dupBtn = DOM.overlayLayer.querySelector("#ov-dup");
    if (dupBtn) dupBtn.onclick = () => duplicateNodes(CS.graph.selectedIds);

    const delBtn = DOM.overlayLayer.querySelector("#ov-del");
    if (delBtn) delBtn.onclick = deleteSelectedItems;

    const linkCtrlBtn = DOM.overlayLayer.querySelector("#ov-link-ctrl");
    if (linkCtrlBtn && selNodes[0]) {
      linkCtrlBtn.onclick = () => {
        pushUndo();
        let target =
          CS.graph.nodes.find((n) => n.type === "loop") ||
          CS.graph.nodes.find((n) => n.type === "bridge") ||
          CS.graph.nodes.find((n) => n.type === "output_control");
        if (!target) {
          target = E.makeOutputControlNode(snapVal(selNodes[0].x + 416), snapVal(selNodes[0].y));
          CS.graph.nodes.push(target);
        }
        ensureEdge(selNodes[0].id, target.id);
        fullRenderCanvas();
        persistOpenTabs();
        toast(
          `已连接至「${target.type === "loop" ? "批量" : target.type === "bridge" ? "多尺寸输出" : "生成设置"}」节点`
        );
      };
    }

    const loopAddBtn = DOM.overlayLayer.querySelector("#ov-loop-add-ctrl");
    if (loopAddBtn && selNodes[0]?.type === "loop") {
      loopAddBtn.onclick = () => spawnDownstreamControlFromLoop(selNodes[0].id);
    }

    const bridgeAddBtn = DOM.overlayLayer.querySelector("#ov-bridge-add-ctrl");
    if (bridgeAddBtn && selNodes[0]) {
      bridgeAddBtn.onclick = () => spawnDownstreamControlFromBridge(selNodes[0].id);
    }

    const runCtrlBtn = DOM.overlayLayer.querySelector("#ov-run-ctrl");
    if (runCtrlBtn && selNodes[0]) {
      runCtrlBtn.onclick = () => runOutputControlNode(selNodes[0].id);
    }

    const openPlanBtn = DOM.overlayLayer.querySelector("#ov-open-plan");
    if (openPlanBtn && selNodes[0]?.type === "article_plan") {
      openPlanBtn.onclick = () => openArticlePlanWidePage(selNodes[0].id);
    }

  }

  function deleteSelectedItems() {
    if (CS.selectedEdgeId) {
      pushUndo();
      CS.graph.edges = CS.graph.edges.filter((e) => e.id !== CS.selectedEdgeId);
      CS.selectedEdgeId = null;
      CS.selectedEdgePt = null;
      fullRenderCanvas();
      persistOpenTabs();
      toast("已断开连线");
      return;
    }
    const sel = new Set(CS.graph.selectedIds || []);
    if (!sel.size) return;
    pushUndo();
    CS.graph.nodes = CS.graph.nodes.filter((n) => !sel.has(n.id));
    CS.graph.edges = CS.graph.edges.filter((e) => !sel.has(e.from) && !sel.has(e.to));
    CS.graph.selectedIds = [];
    fullRenderCanvas();
    persistOpenTabs();
  }

  function duplicateNodes(ids) {
    const srcNodes = ids.map(getNodeById).filter((n) => n && n.type !== "output_display" && n.type !== "article_plan");
    if (!srcNodes.length) {
      toast("「文章配图方案」与「成图显示」由生成设置自动生成和连接，无需手动复制");
      return;
    }
    pushUndo();
    const idMap = new Map();
    const clones = [];
    for (const sn of srcNodes) {
      const c = JSON.parse(JSON.stringify(sn));
      c.id = E.uid(sn.type);
      c.x = snapVal(sn.x + 48);
      c.y = snapVal(sn.y + 48);
      idMap.set(sn.id, c.id);
      clones.push(c);
    }
    CS.graph.nodes.push(...clones);
    for (const e of [...CS.graph.edges]) {
      if (idMap.has(e.from) && idMap.has(e.to)) {
        CS.graph.edges.push({ id: E.uid("edge"), from: idMap.get(e.from), to: idMap.get(e.to) });
      } else if (!idMap.has(e.from) && idMap.has(e.to)) {
        const fromType = getNodeById(e.from)?.type;
        if (isInputNodeType(fromType) || fromType === "bridge" || fromType === "loop") {
          CS.graph.edges.push({ id: E.uid("edge"), from: e.from, to: idMap.get(e.to) });
        }
      }
    }
    CS.graph.selectedIds = clones.map((c) => c.id);
    fullRenderCanvas();
    persistOpenTabs();
    toast(`已复制 ${clones.length} 个节点`);
  }

  /* ======================== CLEAN 3-GROUP LEFT TOOLBOX (输入节点 / 批量与多尺寸 / 输出节点) ======================== */
  const NODE_TOOLBOX_GROUPS = [
    {
      section: "输入节点",
      items: [
        {
          icon: "",
          title: "风格参数",
          desc: "画风 / 图型 / 主题色 / 情绪 / 受众 / 场景 / 留白 / 影调 / 融合",
          payload: { kind: "skill_params" }
        },
        {
          icon: "",
          title: "图片参数",
          desc: "角色 / 道具 / 场景 / 其他 / 上传本地参考图片",
          payload: { kind: "asset" }
        },
        {
          icon: "",
          title: "文本参数",
          desc: "点击输入框弹窗撰写提示词或长文 · 支持附带文件",
          payload: { kind: "text_input" }
        }
      ]
    },
    {
      section: "扩写、批量与多尺寸",
      items: [
        {
          icon: "",
          title: "AI 扩写主题",
          desc: "输入 1 个母题，默认扩写 10 条（可自填方向与条数）子选题",
          payload: { kind: "fission" }
        },
        {
          icon: "",
          title: "批量",
          desc: "编排多文案 / 多画风 / 多图型 / 多图参迭代队列，交由右侧生成设置运行",
          payload: { kind: "loop" }
        },
        {
          icon: "",
          title: "多尺寸输出",
          desc: "位于输入与输出之间，汇总一套输入同时分发多个生成设置",
          payload: { kind: "bridge" }
        }
      ]
    },
    {
      section: "输出节点",
      items: [
        {
          icon: "",
          title: "生成设置",
          desc: "选模式 / 调整数量与比例 / 点击运行",
          payload: { kind: "output_control" }
        }
      ]
    }
  ];

  function renderShelfDrawer() {
    if (!DOM.shelf) return;
    const isShowingTemplateLib = CS.stageView === "canvas" && (!CS.tabs || !CS.tabs.length);
    if (isShowingTemplateLib) {
      DOM.shelf.style.display = "none";
      return;
    }
    DOM.shelf.style.display = "";
    DOM.shelf.classList.toggle("is-collapsed", !CS.shelfOpen);
    DOM.shelf.innerHTML = `
      <div style="padding:10px 12px;border-bottom:1px solid var(--ic-border);display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:12.5px;font-weight:850;color:var(--ic-ink);">节点工具箱</span>
        <button type="button" class="ic-icon-btn" id="ic-shelf-collapse-btn" title="收拢左侧节点箱" style="padding:2px 6px;font-size:11px;">«</button>
      </div>
      <div class="ic-shelf-grid" id="ic-shelf-grid-box" data-canvas-no-zoom style="grid-template-columns:1fr;padding:10px 10px 14px;gap:8px;"></div>
    `;

    DOM.shelf.querySelector("#ic-shelf-collapse-btn").onclick = () => {
      CS.shelfOpen = false;
      savePrefs();
      renderShelfDrawer();
      renderTopAndBottomDocks();
    };

    renderShelfGridOnly();
  }

  function renderShelfGridOnly() {
    const gridBox = DOM.shelf && DOM.shelf.querySelector("#ic-shelf-grid-box");
    if (!gridBox) return;

    const flatSpecs = [];
    const htmlBlocks = [];

    for (const grp of NODE_TOOLBOX_GROUPS) {
      if (!grp.items.length) continue;

      htmlBlocks.push(`<div style="font-size:11px;font-weight:850;color:var(--ic-ink);padding:4px 2px 1px;letter-spacing:0.02em;">${esc(grp.section)}</div>`);

      for (const it of grp.items) {
        const idx = flatSpecs.length;
        flatSpecs.push(it);
        htmlBlocks.push(`
          <div class="ic-node-toolbox-item" draggable="true" data-toolbox-idx="${idx}" title="拖拽到画布或点击直接添加">
            ${it.icon ? `<span class="ic-node-toolbox-icon">${it.icon}</span>` : ""}
            <div style="min-width:0;flex:1;">
              <div style="font-size:12.6px;font-weight:850;color:var(--ic-ink);line-height:1.25;">${esc(it.title)}</div>
              <div style="font-size:10.8px;color:var(--ic-muted);line-height:1.38;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">${esc(it.desc)}</div>
            </div>
            <span style="font-size:12px;color:var(--vermilion);font-weight:800;">＋</span>
          </div>
        `);
      }
    }

    gridBox.innerHTML = htmlBlocks.join("");

    gridBox.querySelectorAll("[data-toolbox-idx]").forEach((el) => {
      const entry = flatSpecs[Number(el.getAttribute("data-toolbox-idx"))];
      el.ondragstart = (ev) => ev.dataTransfer.setData("application/handraw-item", JSON.stringify(entry.payload));
      el.onclick = () => {
        spawnShelfItem(entry.payload);
        toast(`＋ 已添加「${entry.title}」节点`);
      };
    });
  }


  /* ======================== MINIMAP, TOP MULTI-TAB BAR & TOOLSTRIP ======================== */
  function renderMinimap() {
    if (!DOM.minimap) return;
    const isShowingTemplateLib = CS.stageView === "canvas" && (!CS.tabs || !CS.tabs.length);
    const show = CS.minimapOpen && CS.stageView === "canvas" && !isShowingTemplateLib;
    DOM.minimap.style.display = show ? "block" : "none";
    DOM.minimap.style.right = "14px";
    if (!show || !DOM.viewport) return;

    const nodes = CS.graph.nodes || [];
    const W = 198,
      H = 132;
    let minX = -80,
      minY = -80,
      maxX = 1150,
      maxY = 820;
    if (nodes.length) {
      minX = Math.min(...nodes.map((n) => n.x)) - 120;
      minY = Math.min(...nodes.map((n) => n.y)) - 120;
      maxX = Math.max(...nodes.map((n) => n.x + (n.w || 320))) + 120;
      maxY = Math.max(...nodes.map((n) => n.y + (n.h || 260))) + 120;
    }
    const spanW = Math.max(600, maxX - minX);
    const spanH = Math.max(400, maxY - minY);
    const scale = Math.min((W - 16) / spanW, (H - 26) / spanH);
    const offX = (W - spanW * scale) * 0.5;
    const offY = 20 + (H - 24 - spanH * scale) * 0.5;

    const vRect = DOM.viewport.getBoundingClientRect();
    const lensX = offX + (-CS.vx / CS.vk - minX) * scale;
    const lensY = offY + (-CS.vy / CS.vk - minY) * scale;
    const lensW = Math.max(18, (vRect.width / CS.vk) * scale);
    const lensH = Math.max(14, (vRect.height / CS.vk) * scale);

    DOM.minimap._mapMeta = { minX, minY, scale, offX, offY, vRect };

    const rectsHtml = nodes
      .map((n) => {
        const rx = offX + (n.x - minX) * scale;
        const ry = offY + (n.y - minY) * scale;
        const rw = Math.max(4, (n.w || 320) * scale);
        const rh = Math.max(4, (n.h || 240) * scale);
        const fill =
          n.type === "output_display" || n.type === "article_plan"
            ? "#1f6f4a"
            : n.type === "output_control"
              ? "#2563eb"
              : n.type === "loop"
                ? "#0d9488"
                : n.type === "fission"
                  ? "#6d28d9"
                  : n.type === "bridge"
                    ? "#d97706"
                    : n.type === "text_input"
                      ? "#7c4dff"
                      : n.type === "asset"
                        ? "#2d8658"
                        : "#b74227";
        return `<rect x="${rx.toFixed(1)}" y="${ry.toFixed(1)}" width="${rw.toFixed(1)}" height="${rh.toFixed(1)}" rx="2" fill="${fill}" opacity="0.84" />`;
      })
      .join("");

    DOM.minimap.innerHTML = `
      <div class="ic-minimap-head">
        <span>缩略图 (${nodes.length})</span>
        <span>${Math.round(CS.vk * 100)}%</span>
      </div>
      <svg width="${W}" height="${H}" style="display:block;">
        ${rectsHtml}
        <rect x="${lensX.toFixed(1)}" y="${lensY.toFixed(1)}" width="${lensW.toFixed(1)}" height="${lensH.toFixed(1)}" fill="rgba(37,99,235,0.12)" stroke="var(--ic-select)" stroke-width="1.5" rx="3" />
      </svg>
    `;
  }

  function scrollActiveTabIntoView() {
    const track = document.getElementById("ic-tabs-track");
    if (!track) return;
    const activeEl = track.querySelector(".ic-doc-tab.is-active");
    if (activeEl && activeEl.scrollIntoView) {
      activeEl.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    }
    setTimeout(updateTabScrollButtons, 80);
  }

  function updateTabScrollButtons() {
    const track = document.getElementById("ic-tabs-track");
    const btnL = document.getElementById("tb-scroll-left");
    const btnR = document.getElementById("tb-scroll-right");
    const allBtn = document.getElementById("tb-all-tabs");
    if (!track) return;
    const hasOverflow = track.scrollWidth > track.clientWidth + 4;
    if (btnL) {
      btnL.style.display = hasOverflow ? "inline-flex" : "none";
      btnL.disabled = track.scrollLeft <= 2;
    }
    if (btnR) {
      btnR.style.display = hasOverflow ? "inline-flex" : "none";
      btnR.disabled = track.scrollLeft + track.clientWidth >= track.scrollWidth - 2;
    }
    if (allBtn) allBtn.classList.toggle("is-overflowing", hasOverflow);
  }

  function closeAllTabsPopover() {
    if (DOM.allTabsPop) {
      DOM.allTabsPop.remove();
      DOM.allTabsPop = null;
    }
  }

  function openAllTabsPopover(anchorBtn) {
    if (DOM.allTabsPop) {
      closeAllTabsPopover();
      return;
    }
    syncCurrentTabSnapshot();
    const rect = anchorBtn.getBoundingClientRect();
    const pop = document.createElement("div");
    pop.className = "ic-all-tabs-popover";
    pop.style.left = `${Math.max(12, Math.min(window.innerWidth - 344, rect.right - 220))}px`;
    pop.style.top = `${rect.bottom + 6}px`;

    const bpIcons = {
      loop_100: "",
      loop: "",
      style_ab: "",
      ip_story: "",
      omnimedia: "",
      article: "",
      series: "",
      xhs: "",
      fusion: "",
      single: "",
      blank: ""
    };

    pop.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:2px 4px 6px;border-bottom:1px solid var(--ic-border);">
        <span style="font-size:12px;font-weight:850;">全部已打开工作流 (${CS.tabs.filter((t) => !isArticleTab(t)).length})</span>
        <button type="button" class="btn btn-sm btn-primary" id="atp-new-blank" style="padding:2px 8px;font-size:11px;">＋ 新建空白页</button>
      </div>
      <div class="ic-all-tabs-list">
        ${CS.tabs
          .filter((t) => !isArticleTab(t))
          .map((t, idx) => {
            const nCnt = t.graph?.nodes?.length || 0;
            const cleanTitle = String(t.title || "未命名").replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, "") || "未命名";
            return `
              <div class="ic-all-tabs-item ${t.id === CS.activeTabId ? "is-active" : ""}" data-atp-jump="${esc(t.id)}">
                <div style="min-width:0;flex:1;">
                  <div style="font-size:12.5px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${idx + 1}. ${esc(cleanTitle)} ${t.dirty ? "●" : ""}
                  </div>
                  <div style="font-size:10.8px;color:var(--ic-muted);">${nCnt} 个节点 · ${t.dirty ? "有未保存修改" : "已同步"}</div>
                </div>
                <button type="button" class="ic-icon-btn" data-atp-close="${esc(t.id)}" title="关闭此标签页" style="padding:2px 6px;font-size:12px;">×</button>
              </div>
            `;
          })
          .join("")}
      </div>
    `;

    (DOM.root || document.body).appendChild(pop);
    DOM.allTabsPop = pop;

    pop.querySelector("#atp-new-blank").onclick = () => {
      closeAllTabsPopover();
      createWorkflowTab({ title: "空白工作流", blueprint: "blank", makeActive: true, autoFit: true, switchToCanvas: true });
    };

    pop.querySelectorAll("[data-atp-jump]").forEach((row) => {
      row.onclick = (ev) => {
        if (ev.target.closest("[data-atp-close]")) return;
        const tid = row.getAttribute("data-atp-jump");
        closeAllTabsPopover();
        activateWorkflowTab(tid, { autoFit: false, switchToCanvas: true });
      };
    });

    pop.querySelectorAll("[data-atp-close]").forEach((btn) => {
      btn.onclick = (ev) => {
        ev.stopPropagation();
        const tid = btn.getAttribute("data-atp-close");
        closeAllTabsPopover();
        closeWorkflowTab(tid);
      };
    });
  }

  function renderWorkbenchBar() {
    if (!DOM.workbenchBar) return;
    const bpIcons = {
      loop_100: "",
      loop: "",
      style_ab: "",
      ip_story: "",
      omnimedia: "",
      article: "",
      series: "",
      xhs: "",
      fusion: "",
      single: "",
      blank: ""
    };
    const dispItemsCount =
      (CS.graph?.nodes || [])
        .filter((n) => n.type === "output_display" && !n.data?.planCardId)
        .reduce((acc, n) => acc + (n.data?.items?.length || 0), 0) +
      (CS.graph?.nodes || [])
        .filter((n) => n.type === "article_plan")
        .reduce((acc, n) => acc + (n.data?.cards?.length || 0), 0);
    const histCount = (CS.generationHistory || []).length;

    DOM.workbenchBar.innerHTML = `
      <div class="ic-tabs-rail">
        <button type="button" class="ic-tab-nav-btn" id="tb-scroll-left" title="向左滚动标签栏" style="display:none;">‹</button>
        <div class="ic-tabs-track" id="ic-tabs-track">
          ${CS.tabs
            .filter((t) => !isArticleTab(t))
            .map((t) => {
              const isAct = CS.stageView === "canvas" && t.id === CS.activeTabId;
              const isRenaming = CS.renamingTabId === t.id;
              const cleanTitle = String(t.title || "未命名").replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, "") || "未命名";
              const icon = bpIcons[t.blueprint] || "";
              return `
                <div class="ic-doc-tab ${isAct ? "is-active" : ""}" data-wftab-id="${esc(t.id)}" title="${esc(t.title)}（单击进入画布 · 双击直接改名）">
                  ${icon ? `<span class="ic-doc-tab-icon">${icon}</span>` : ""}
                  ${
                    isRenaming
                      ? `<input type="text" class="ic-tab-rename-inp" id="ic-tab-rename-active" value="${esc(cleanTitle)}" />`
                      : `<span class="ic-doc-tab-title">${esc(cleanTitle)}</span>`
                  }
                  ${t.dirty && !isRenaming ? `<span class="ic-doc-tab-dirty" title="有未保存改动"></span>` : ""}
                  <button type="button" class="ic-doc-tab-close" data-wftab-close="${esc(t.id)}" title="关闭标签页">×</button>
                </div>
              `;
            })
            .join("")}
        </div>
        <button type="button" class="ic-tab-nav-btn" id="tb-scroll-right" title="向右滚动标签栏" style="display:none;">›</button>
        <div class="ic-tabs-pinned">
          <button type="button" class="ic-tab-action-pill" id="tb-new-wf" title="新建工作流标签页">＋ 新建 ▾</button>
          <button type="button" class="ic-tab-action-pill" id="tb-all-tabs" title="展开全部已打开标签页列表">已打开 ${CS.tabs.filter((t) => !isArticleTab(t)).length} ▾</button>
        </div>
      </div>

      <div class="ic-workbench-tools">
        <button type="button" class="ic-icon-btn" id="tb-theme-toggle" title="切换宣纸暖昼 / 暗房深空" style="font-size:11px;font-weight:750;padding:2px 8px;">${CS.canvasTheme === "dark" ? "暖昼" : "深空"}</button>
        <button type="button" class="ic-icon-btn" id="tb-grid-toggle" title="切换网格">${CS.gridMode === "dots" ? "⠿" : CS.gridMode === "lines" ? "┼" : "□"}</button>
      </div>
    `;

    const track = DOM.workbenchBar.querySelector("#ic-tabs-track");
    if (track) {
      track.addEventListener(
        "wheel",
        (ev) => {
          if (Math.abs(ev.deltaY) > Math.abs(ev.deltaX)) {
            ev.preventDefault();
            track.scrollLeft += ev.deltaY;
            updateTabScrollButtons();
          }
        },
        { passive: false }
      );
      track.addEventListener("scroll", updateTabScrollButtons);
    }

    const btnL = DOM.workbenchBar.querySelector("#tb-scroll-left");
    const btnR = DOM.workbenchBar.querySelector("#tb-scroll-right");
    if (btnL && track) btnL.onclick = () => track.scrollBy({ left: -240, behavior: "smooth" });
    if (btnR && track) btnR.onclick = () => track.scrollBy({ left: 240, behavior: "smooth" });

    const renameInp = DOM.workbenchBar.querySelector("#ic-tab-rename-active");
    if (renameInp) {
      const targetTab = CS.tabs.find((x) => x.id === CS.renamingTabId);
      const commitRename = () => {
        if (targetTab && renameInp.value.trim()) {
          targetTab.title = renameInp.value.trim();
          persistOpenTabs();
        }
        CS.renamingTabId = null;
        renderWorkbenchBar();
      };
      setTimeout(() => {
        renameInp.focus();
        renameInp.select();
      }, 10);
      renameInp.onclick = (e) => e.stopPropagation();
      renameInp.ondblclick = (e) => e.stopPropagation();
      renameInp.onblur = commitRename;
      renameInp.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          renameInp.blur();
        } else if (e.key === "Escape") {
          CS.renamingTabId = null;
          renderWorkbenchBar();
        }
      };
    }

    DOM.workbenchBar.querySelectorAll("[data-wftab-id]").forEach((el) => {
      const tid = el.getAttribute("data-wftab-id");
      el.onclick = (e) => {
        if (e.target.closest("[data-wftab-close]") || e.target.closest(".ic-tab-rename-inp")) return;
        activateWorkflowTab(tid, { autoFit: false, switchToCanvas: true });
      };
      el.ondblclick = (e) => {
        if (e.target.closest("[data-wftab-close]")) return;
        e.stopPropagation();
        CS.renamingTabId = tid;
        renderWorkbenchBar();
      };
    });

    DOM.workbenchBar.querySelectorAll("[data-wftab-close]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        closeWorkflowTab(btn.getAttribute("data-wftab-close"));
      };
    });

    const newWfBtn = DOM.workbenchBar.querySelector("#tb-new-wf");
    if (newWfBtn) newWfBtn.onclick = (e) => {
      e.stopPropagation();
      const rect = newWfBtn.getBoundingClientRect();
      openContextMenu(rect.left, rect.bottom + 6, { x: 240, y: 180 }, { newWorkflowMenu: true });
    };

    const allTabsBtn = DOM.workbenchBar.querySelector("#tb-all-tabs");
    if (allTabsBtn) allTabsBtn.onclick = (e) => {
      e.stopPropagation();
      openAllTabsPopover(allTabsBtn);
    };

    const btnThemeToggle = DOM.workbenchBar.querySelector("#tb-theme-toggle");
    if (btnThemeToggle) btnThemeToggle.onclick = () => {
      CS.canvasTheme = CS.canvasTheme === "dark" ? "paper" : "dark";
      savePrefs();
      renderTopAndBottomDocks();
      updateGridBackground();
    };
    const btnGridToggle = DOM.workbenchBar.querySelector("#tb-grid-toggle");
    if (!btnGridToggle) { requestAnimationFrame(updateTabScrollButtons); return; }
    btnGridToggle.onclick = () => {
      const order = ["dots", "lines", "blank"];
      CS.gridMode = order[(order.indexOf(CS.gridMode) + 1) % order.length];
      savePrefs();
      renderWorkbenchBar();
      updateGridBackground();
    };

    requestAnimationFrame(updateTabScrollButtons);
  }

  function renderCanvasToolstrip() {
    if (!DOM.canvasToolstrip) return;
    const isShowingTemplateLib = CS.stageView === "canvas" && (!CS.tabs || !CS.tabs.length);
    if (isShowingTemplateLib) {
      DOM.canvasToolstrip.style.display = "none";
      DOM.canvasToolstrip.innerHTML = "";
      return;
    }
    DOM.canvasToolstrip.style.display = "";

    DOM.canvasToolstrip.innerHTML = `
      ${
        !CS.shelfOpen
          ? `<div class="ic-float-pill">
              <button type="button" class="ic-icon-btn" id="ic-shelf-reopen-btn" title="展开左侧节点箱">展开节点箱 »</button>
            </div>`
          : ""
      }
      <div class="ic-float-pill">
        <button type="button" class="ic-icon-btn" id="bc-undo" title="撤销 (Ctrl+Z)">↩</button>
        <button type="button" class="ic-icon-btn" id="bc-redo" title="重做 (Ctrl+Y)">↪</button>
        <div class="ic-divider-v"></div>
        <button type="button" class="ic-icon-btn" id="bl-arrange">自动整理</button>
      </div>
    `;

    const reopenShelfBtn = DOM.canvasToolstrip.querySelector("#ic-shelf-reopen-btn");
    if (reopenShelfBtn) {
      reopenShelfBtn.onclick = () => {
        CS.shelfOpen = true;
        savePrefs();
        renderShelfDrawer();
        renderTopAndBottomDocks();
      };
    }

    DOM.canvasToolstrip.querySelector("#bc-undo").onclick = undoGraph;
    DOM.canvasToolstrip.querySelector("#bc-redo").onclick = redoGraph;
    DOM.canvasToolstrip.querySelector("#bl-arrange").onclick = () => {
      pushUndo();
      E.autoArrangeGraph(CS.graph);
      fullRenderCanvas();
      fitView();
      const hasLoop = CS.graph.nodes.some((n) => n.type === "loop");
      const hasBridge = CS.graph.nodes.some((n) => n.type === "bridge");
      toast(
        hasLoop
          ? "已按「输入节点 → 批量 → 生成设置 → 成图显示」自动整理对齐！"
          : hasBridge
            ? "已按「输入节点 → 多尺寸输出 → 生成设置 → 成图显示」自动整理对齐！"
            : "已按「输入节点 → 生成设置 → 成图显示」自动整理对齐！"
      );
    };
  }

  /* ======================== CLEAN SINGLE-COLUMN TEXT PARAMETER MODAL (ONLY ONE "确定" BUTTON) ======================== */
  function openTextEditModal(nodeId) {
    const txt = (nodeId ? getNodeById(nodeId) : null) || CS.graph.nodes.find((n) => n.type === "text_input");
    if (!txt || txt.type !== "text_input") return;

    const curVal = txt.data.text || "";

    S.openModal({
      title: "文本参数",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;">
          <textarea
            class="hw-input"
            id="txt-modal-ta"
            style="width:100%;min-height:360px;padding:14px 16px;font-size:15px;line-height:1.72;resize:vertical;"
            placeholder="在此输入画面描述、海报文案或完整文章正文…"
          >${esc(curVal)}</textarea>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
            <span id="txt-modal-count" style="font-size:12px;color:var(--ink-muted);">当前 ${curVal.length} 字</span>
            <button type="button" class="btn btn-primary" id="txt-modal-ok" style="min-width:104px;font-weight:850;">确定</button>
          </div>
        </div>
      `,
      onMount(root) {
        const ta = root.querySelector("#txt-modal-ta");
        const countEl = root.querySelector("#txt-modal-count");
        const okBtn = root.querySelector("#txt-modal-ok");

        setTimeout(() => {
          ta.focus();
          ta.setSelectionRange(ta.value.length, ta.value.length);
        }, 15);

        ta.oninput = () => {
          if (countEl) countEl.textContent = `当前 ${ta.value.length} 字`;
        };

        okBtn.onclick = () => {
          if (txt.data.text !== ta.value) {
            pushUndo();
            txt.data.text = ta.value;
            markActiveTabDirty();
            fullRenderCanvas();
            persistOpenTabs();
          }
          S.closeModal();
        };
      }
    });
  }



  /* ======================== DESKTOP WIDE NOTION-STYLE ARTICLE ILLUSTRATION PLAN STUDIO ======================== */
  function resolvePlanSourceControl(planNode) {
    if (!planNode) return null;
    return (
      getNodeById(planNode.data?.sourceControlId) ||
      CS.graph.edges
        .filter((e) => e.to === planNode.id)
        .map((e) => getNodeById(e.from))
        .find((n) => n && n.type === "output_control") ||
      CS.graph.nodes.find((n) => n.type === "output_control" && n.data?.mode === "article-illust") ||
      CS.graph.nodes.find((n) => n.type === "output_control") ||
      null
    );
  }

  function buildDefaultCardPromptForPosition(planNode, cardRole, cardTitle, cardRatio, afterBlockIdx) {
    const ctrl = resolvePlanSourceControl(planNode);
    const blocks = E.parseArticleReadonlyBlocks(planNode.data?.markdown || "");
    let contextSnippet = "";
    if (afterBlockIdx < 0) {
      contextSnippet = blocks
        .slice(0, 3)
        .map((b) => b.text)
        .join(" ")
        .slice(0, 180);
    } else {
      const start = Math.max(0, afterBlockIdx);
      contextSnippet = blocks
        .slice(start, start + 3)
        .map((b) => b.text)
        .join(" ")
        .slice(0, 220);
    }
    return E.assembleArticleCardFullPrompt(CS.graph, ctrl, Catalog, {
      role: cardRole,
      title: cardTitle || (cardRole === "cover" ? "首图封面" : "正文插图"),
      articleTitle: planNode.data?.articleTitle || "文章配图",
      headingText: cardTitle || "",
      contextSnippet,
      ratio: cardRatio || (cardRole === "cover" ? "2.35:1" : "4:3")
    });
  }

  function openPlanCardPromptModal(planNode, cardId) {
    if (!planNode || planNode.type !== "article_plan") return;
    const card = (planNode.data?.cards || []).find((c) => c.id === cardId);
    if (!card) return;

    let draftRole = card.role === "cover" ? "cover" : "inline";
    let draftRatio = card.ratio || (draftRole === "cover" ? "2.35:1" : "4:3");
    const quickRatios = ["2.35:1", "16:9", "4:3", "3:4", "1:1"];

    S.openModal({
      title: `✎ 配图卡片提示词编辑器（完全体）`,
      sizeClass: "modal-medium",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:center;">
            <div class="ic-ctrl-seg" id="plan-card-role-seg">
              <button type="button" class="ic-ctrl-pill ${draftRole === "cover" ? "is-active" : ""}" data-role-val="cover">🖼️ 封面卡片</button>
              <button type="button" class="ic-ctrl-pill ${draftRole !== "cover" ? "is-active" : ""}" data-role-val="inline">🎨 插图卡片</button>
            </div>
            <input
              type="text"
              class="hw-input"
              id="plan-card-title-inp"
              value="${esc(card.title || "")}"
              placeholder="卡片标题（如：首图封面 / 章节一插图）"
              style="padding:7px 11px;font-size:13px;font-weight:750;"
            />
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;padding:8px 10px;border-radius:10px;background:var(--paper-bg);border:1px solid var(--line-soft);">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              <span style="font-size:12px;font-weight:800;color:var(--ink-main);">📐 画幅比例：</span>
              <div class="ic-ctrl-seg" id="plan-card-ratio-pills">
                ${quickRatios
                  .map(
                    (r) => `<button type="button" class="ic-ctrl-pill ${draftRatio === r ? "is-active" : ""}" data-ratio-pill="${r}">${r}</button>`
                  )
                  .join("")}
              </div>
              <input
                type="text"
                class="hw-input"
                id="plan-card-ratio-custom"
                value="${esc(quickRatios.includes(draftRatio) ? "" : draftRatio)}"
                placeholder="自定义 如 5:2"
                style="width:108px;padding:4px 8px;font-size:12px;font-family:var(--font-mono);"
              />
            </div>
            <button type="button" class="btn btn-sm" id="plan-card-reset-default" style="padding:3px 9px;font-size:11.5px;">↺ 恢复默认拼装词</button>
          </div>

          <div style="display:flex;flex-direction:column;gap:6px;">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--ink-muted);">
              <span style="font-weight:800;color:var(--ink-main);">📝 完整生图提示词（可直接增删修改画面细节、构图与风格要求）</span>
              <span id="plan-card-char-count">${(card.prompt || "").length} 字</span>
            </div>
            <textarea
              class="hw-input"
              id="plan-card-full-prompt-ta"
              style="width:100%;min-height:260px;padding:12px 14px;font-size:14px;line-height:1.68;resize:vertical;"
              placeholder="在此编辑该配图位的完整生图提示词…"
            >${esc(card.prompt || "")}</textarea>
          </div>

          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding-top:4px;">
            <button type="button" class="btn btn-sm" id="plan-card-modal-del" style="color:#dc2626;">🗑️ 删除此卡片</button>
            <div style="display:flex;align-items:center;gap:8px;">
              <button type="button" class="btn" id="plan-card-save-gen" style="font-weight:800;color:#1f6f4a;border-color:rgba(31,111,74,0.4);">⚡ 保存并生成此图</button>
              <button type="button" class="btn btn-primary" id="plan-card-ok" style="min-width:96px;font-weight:850;">确定</button>
            </div>
          </div>
        </div>
      `,
      onMount(root) {
        const titleInp = root.querySelector("#plan-card-title-inp");
        const ta = root.querySelector("#plan-card-full-prompt-ta");
        const countEl = root.querySelector("#plan-card-char-count");
        const customRatioInp = root.querySelector("#plan-card-ratio-custom");
        const roleSeg = root.querySelector("#plan-card-role-seg");
        const ratioPills = root.querySelector("#plan-card-ratio-pills");

        const syncRatioUi = () => {
          ratioPills.querySelectorAll("[data-ratio-pill]").forEach((b) => {
            b.classList.toggle("is-active", b.getAttribute("data-ratio-pill") === draftRatio);
          });
          if (quickRatios.includes(draftRatio)) {
            customRatioInp.value = "";
          } else {
            customRatioInp.value = draftRatio;
          }
        };

        roleSeg.querySelectorAll("[data-role-val]").forEach((btn) => {
          btn.onclick = () => {
            draftRole = btn.getAttribute("data-role-val") === "cover" ? "cover" : "inline";
            roleSeg.querySelectorAll("[data-role-val]").forEach((b) => {
              b.classList.toggle("is-active", b.getAttribute("data-role-val") === draftRole);
            });
          };
        });

        ratioPills.querySelectorAll("[data-ratio-pill]").forEach((btn) => {
          btn.onclick = () => {
            draftRatio = btn.getAttribute("data-ratio-pill") || "4:3";
            syncRatioUi();
          };
        });

        customRatioInp.oninput = () => {
          const norm = normalizeRatioInput(customRatioInp.value);
          if (isValidRatioInput(norm)) {
            draftRatio = norm;
            ratioPills.querySelectorAll("[data-ratio-pill]").forEach((b) => {
              b.classList.toggle("is-active", b.getAttribute("data-ratio-pill") === draftRatio);
            });
          }
        };

        ta.oninput = () => {
          if (countEl) countEl.textContent = `${ta.value.length} 字`;
        };

        root.querySelector("#plan-card-reset-default").onclick = () => {
          const fresh = buildDefaultCardPromptForPosition(
            planNode,
            draftRole,
            titleInp.value.trim() || card.title,
            draftRatio,
            typeof card.afterBlockIdx === "number" ? card.afterBlockIdx : -1
          );
          ta.value = fresh;
          card.promptCustomized = false;
          if (countEl) countEl.textContent = `${ta.value.length} 字`;
          toast("↺ 已恢复为上游参数拼装提示词");
        };

        root.querySelector("#plan-card-modal-del").onclick = () => {
          const target = resolveArticleTarget(planNode);
          if (target?.isActiveCanvas) pushUndo();
          planNode.data.cards = (planNode.data.cards || []).filter((c) => c.id !== card.id);
          commitArticleTargetChanges(target, { bumpTime: true });
          S.closeModal();
          renderFullPreviewStage();
          if (target?.isActiveCanvas) {
            renderWorldNodes();
            renderMinimap();
          }
          toast("🗑️ 已删除该配图卡片");
        };

        const applyEdits = () => {
          const customNorm = normalizeRatioInput(customRatioInp.value);
          if (customNorm) {
            if (!isValidRatioInput(customNorm)) {
              toast("自定义比例请按「宽:高」格式填写，如 5:2 或 21:9");
              return false;
            }
            draftRatio = customNorm;
          }
          const nextTitle = titleInp.value.trim() || (draftRole === "cover" ? "首图封面" : "正文插图");
          const nextPrompt = ta.value.trim();
          const changed =
            card.role !== draftRole ||
            card.title !== nextTitle ||
            card.ratio !== draftRatio ||
            card.prompt !== nextPrompt;
          if (changed) {
            const target = resolveArticleTarget(planNode);
            if (target?.isActiveCanvas) pushUndo();
            if (card.prompt !== nextPrompt) {
              card.promptCustomized = true;
            }
            card.role = draftRole;
            card.title = nextTitle;
            card.ratio = draftRatio;
            card.prompt = nextPrompt;
            commitArticleTargetChanges(target, { bumpTime: true });
          }
          return true;
        };

        root.querySelector("#plan-card-ok").onclick = () => {
          if (!applyEdits()) return;
          S.closeModal();
          renderFullPreviewStage();
          renderWorldNodes();
        };

        root.querySelector("#plan-card-save-gen").onclick = async () => {
          if (!applyEdits()) return;
          const target = resolveArticleTarget(planNode);
          const refId = target?.isActiveCanvas ? planNode.id : target?.art?.id || planNode.id;
          S.closeModal();
          renderFullPreviewStage();
          renderWorldNodes();
          await generateSinglePlanCard(refId, card.id);
        };

        setTimeout(() => {
          ta.focus();
        }, 20);
      }
    });
  }

  function insertNewPlanCard(planNode, afterBlockIdx, { openModal = true } = {}) {
    if (!planNode || planNode.type !== "article_plan") return null;
    const target = resolveArticleTarget(planNode);
    if (target?.isActiveCanvas) pushUndo();
    const ctrl = target?.isActiveCanvas ? resolvePlanSourceControl(planNode) : null;
    const blocks = E.parseArticleReadonlyBlocks(planNode.data?.markdown || "");
    const clampedIdx = Math.max(-1, Math.min(blocks.length - 1, Math.round(Number(afterBlockIdx))));
    const hasCoverAlready = (planNode.data?.cards || []).some((c) => c.role === "cover");
    const role = clampedIdx === -1 && !hasCoverAlready ? "cover" : "inline";
    const ratio =
      role === "cover"
        ? ctrl?.data?.coverRatio || "2.35:1"
        : ctrl?.data?.inlineRatio || "4:3";

    const anchorBlk = clampedIdx >= 0 ? blocks[clampedIdx] : null;
    const defaultTitle =
      role === "cover"
        ? `首图封面 · ${(planNode.data?.articleTitle || "文章").slice(0, 14)}`
        : anchorBlk
          ? `插图 · ${anchorBlk.text.slice(0, 14)}`
          : `新增插图 #${(planNode.data?.cards?.length || 0) + 1}`;

    const fullPrompt = buildDefaultCardPromptForPosition(planNode, role, defaultTitle, ratio, clampedIdx);
    const newCard = {
      id: E.uid("pcard"),
      role,
      title: defaultTitle,
      afterBlockIdx: clampedIdx,
      ratio,
      prompt: fullPrompt,
      promptCustomized: false,
      imageUrl: "",
      sampleImg: "/images/graphic-text-mode-demo.webp",
      status: "idle"
    };

    const existing = sortPlanCardsInDocOrder(planNode.data.cards || []);
    let insertAt = existing.length;
    for (let i = existing.length - 1; i >= 0; i--) {
      if ((existing[i].afterBlockIdx ?? -1) <= clampedIdx) {
        insertAt = i + 1;
        break;
      }
      if (i === 0) insertAt = 0;
    }
    existing.splice(insertAt, 0, newCard);
    planNode.data.cards = sortPlanCardsInDocOrder(existing);

    commitArticleTargetChanges(target, { bumpTime: true });
    renderFullPreviewStage();
    if (target?.isActiveCanvas) renderWorldNodes();
    renderWorkbenchBar();

    if (openModal) {
      openPlanCardPromptModal(planNode, newCard.id);
    } else {
      toast(`＋ 已在指定位置插入「${newCard.title}」`);
    }
    return newCard;
  }

  function openInsertCardPositionModal(planNode) {
    if (!planNode || planNode.type !== "article_plan") return;
    const blocks = E.parseArticleReadonlyBlocks(planNode.data?.markdown || "");

    const positions = [
      { afterIdx: -1, badge: "顶部封面位", desc: "插入到文章最顶部（标题之前）" },
      ...blocks.map((b) => {
        const tag =
          b.kind === "h1"
            ? "H1 标题后"
            : b.kind === "h2"
              ? "章节标题后"
              : b.kind === "h3"
                ? "小节标题后"
                : b.kind === "blockquote"
                  ? "引用块后"
                  : "正文段落后";
        return {
          afterIdx: b.idx,
          badge: tag,
          desc: b.text.length > 48 ? `${b.text.slice(0, 48)}…` : b.text
        };
      })
    ];

    S.openModal({
      title: "＋ 选择插入配图卡片的位置",
      sizeClass: "modal-medium",
      html: `
        <div style="display:flex;flex-direction:column;gap:10px;">
          <div style="font-size:12.5px;color:var(--ink-muted);">点击任意文章节点位置，即可在该段落下方插入一张新的配图卡片（也可直接在文章段落间隙点击「＋ 在此处添加配图卡片」）：</div>
          <div style="display:flex;flex-direction:column;gap:6px;max-height:56vh;overflow-y:auto;padding-right:4px;">
            ${positions
              .map(
                (p) => `
                <button
                  type="button"
                  class="ic-context-item"
                  data-pick-insert-pos="${p.afterIdx}"
                  style="display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--line-soft);border-radius:10px;background:#fff;text-align:left;"
                >
                  <span class="ic-node-badge ${p.afterIdx === -1 ? "ic-badge-input" : "ic-badge-output-disp"}" style="flex-shrink:0;">${esc(p.badge)}</span>
                  <span style="font-size:13px;font-weight:750;color:var(--ink-main);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(p.desc)}</span>
                  <span style="font-size:12px;font-weight:850;color:var(--vermilion);flex-shrink:0;">＋ 插入此处</span>
                </button>
              `
              )
              .join("")}
          </div>
        </div>
      `,
      onMount(root) {
        root.querySelectorAll("[data-pick-insert-pos]").forEach((btn) => {
          btn.onclick = () => {
            const idx = Number(btn.getAttribute("data-pick-insert-pos"));
            S.closeModal();
            insertNewPlanCard(planNode, idx, { openModal: true });
          };
        });
      }
    });
  }

  function renderReadonlyArticleBlockHtml(b) {
    if (b.kind === "h1") {
      return `<h1 class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="font-family:var(--font-serif);font-size:28px;font-weight:900;line-height:1.35;margin:8px 0 12px;color:var(--ic-ink);">${esc(b.text)}</h1>`;
    }
    if (b.kind === "h2") {
      return `<h2 class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="font-size:20px;font-weight:850;margin:22px 0 10px;padding-left:12px;border-left:4px solid var(--vermilion);color:var(--ic-ink);">${esc(b.text)}</h2>`;
    }
    if (b.kind === "h3") {
      return `<h3 class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="font-size:17px;font-weight:800;margin:16px 0 8px;color:var(--ic-ink);">${esc(b.text)}</h3>`;
    }
    if (b.kind === "blockquote") {
      return `<blockquote class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="margin:12px 0;padding:12px 16px;background:var(--ic-surface);border-left:3px solid var(--ic-border-strong);border-radius:0 10px 10px 0;font-size:14.5px;color:var(--ic-muted);line-height:1.75;">${esc(b.text)}</blockquote>`;
    }
    if (b.kind === "ul") {
      const lis = String(b.text || "")
        .split(/\r?\n/)
        .filter(Boolean)
        .map((ln) => `<li>${esc(ln)}</li>`)
        .join("");
      return `<ul class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="margin:10px 0 10px 20px;font-size:15.5px;line-height:1.8;color:var(--ic-text);">${lis}</ul>`;
    }
    if (b.kind === "code") {
      return `<pre class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="margin:12px 0;padding:12px 14px;border-radius:10px;background:var(--ic-surface);border:1px solid var(--ic-border);font-family:var(--font-mono);font-size:12.5px;overflow-x:auto;">${esc(b.text)}</pre>`;
    }
    if (b.kind === "hr") {
      return `<hr class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="border:none;border-top:1px dashed var(--ic-border-strong);margin:16px 0;" />`;
    }
    return `<p class="ic-readonly-art-block" data-art-block-idx="${b.idx}" style="font-size:16px;line-height:1.86;margin:10px 0;color:var(--ic-text);">${esc(b.text)}</p>`;
  }

  function renderPlanSlotCardHtml(card, inlineCounter) {
    const isCover = card.role === "cover";
    const isGen = card.status === "generating";
    const afterIdx = typeof card.afterBlockIdx === "number" ? card.afterBlockIdx : -1;
    const compactPrompt = String(card.prompt || "").trim() || "点击编辑此配图位提示词…";

    return `
      <div
        class="ic-plan-slot-card ${isCover ? "is-cover-card" : ""} ${isGen ? "is-generating" : ""}"
        id="pv-plan-card-${esc(card.id)}"
        data-plan-card-id="${esc(card.id)}"
        data-after-block="${afterIdx}"
      >
        <div class="ic-plan-slot-top">
          <span class="ic-plan-drag-handle" data-plan-drag="${esc(card.id)}" title="按住 ⋮⋮ 上下拖动调整该配图卡片在文章中的位置">⋮⋮</span>
          <span class="ic-plan-role-badge ${isCover ? "is-cover" : "is-inline"}">${isCover ? "🖼️ 封面" : `🎨 插图 #${inlineCounter}`}</span>
          <span class="ic-plan-slot-title">${esc(card.title || (isCover ? "首图封面" : "章节插图"))}</span>
          ${card.demoMode ? '<span style="font-size:10px;padding:1px 6px;border-radius:999px;background:#fff0bf;color:#7a4d00;font-weight:900;flex-shrink:0;">🧪 演示样图</span>' : ""}
          ${
            card.promptCustomized
              ? `<span style="font-size:10px;padding:1px 6px;border-radius:999px;background:rgba(209,75,40,0.1);color:var(--vermilion);font-weight:800;flex-shrink:0;">已调词</span>`
              : ""
          }
          <span class="ic-plan-slot-ratio">${esc(card.ratio || (isCover ? "2.35:1" : "4:3"))}</span>
          <button
            type="button"
            class="btn btn-sm"
            data-plan-edit="${esc(card.id)}"
            title="编辑这张图的完整生图提示词"
            style="padding:2px 9px;font-size:11px;font-weight:800;flex-shrink:0;"
          >
            ✏️ 调提示词
          </button>
          <button
            type="button"
            class="btn btn-sm ${card.imageUrl ? "" : "btn-primary"}"
            data-plan-gen-one="${esc(card.id)}"
            ${isGen ? "disabled" : ""}
            style="padding:2px 9px;font-size:11px;font-weight:800;flex-shrink:0;"
          >
            ${isGen ? "⏳ 生成中…" : card.imageUrl ? "🔄 重新生成" : "⚡ 生成"}
          </button>
          <button
            type="button"
            class="ic-icon-btn"
            data-plan-del="${esc(card.id)}"
            title="删除此配图卡片"
            style="padding:2px 6px;font-size:12px;color:#dc2626;flex-shrink:0;"
          >
            🗑️
          </button>
        </div>

        ${
          card.imageUrl
            ? `
            <div class="ic-plan-slot-img-box">
              <img src="${esc(card.imageUrl)}" alt="${esc(card.title)}" />
              <button
                type="button"
                class="ic-mini-glass-btn"
                data-plan-zoom="${esc(card.imageUrl)}"
                data-plan-zoom-title="${esc(card.title)}"
                style="position:absolute;right:10px;top:10px;"
              >
                🔍 放大
              </button>
            </div>
          `
            : ""
        }

        <div class="ic-plan-slot-prompt-row" title="点击弹窗查看与编辑完整提示词">
          <div class="ic-plan-slot-prompt-text">${esc(compactPrompt)}</div>
          <span class="ic-plan-slot-edit-hint">✎ 点击看完全体</span>
        </div>
      </div>
    `;
  }

  function renderNotionPlanSheetHtml(planNode) {
    const rawMd = planNode?.data?.markdown || E.DEFAULT_STARTER_ARTICLE_MD;
    const blocks = E.parseArticleReadonlyBlocks(rawMd);
    const maxBlockIdx = blocks.length - 1;
    const orderedCards = sortPlanCardsInDocOrder(planNode?.data?.cards || []);

    const cardsByPos = new Map();
    for (const c of orderedCards) {
      const rawPos = typeof c.afterBlockIdx === "number" ? c.afterBlockIdx : -1;
      const clampedPos = blocks.length ? Math.max(-1, Math.min(maxBlockIdx, rawPos)) : -1;
      if (!cardsByPos.has(clampedPos)) cardsByPos.set(clampedPos, []);
      cardsByPos.get(clampedPos).push(c);
    }

    let inlineCounter = 0;
    const renderCardsAt = (posIdx) => {
      const list = cardsByPos.get(posIdx) || [];
      return list
        .map((c) => {
          if (c.role !== "cover") inlineCounter += 1;
          return renderPlanSlotCardHtml(c, inlineCounter);
        })
        .join("");
    };

    const htmlParts = [];
    // Top slot (-1: before H1 / first block)
    htmlParts.push(renderCardsAt(-1));
    htmlParts.push(`
      <div class="ic-notion-gap" data-gap-idx="-1">
        <button type="button" class="ic-notion-insert-btn" data-plan-insert-at="-1">＋ 在此处添加封面图或首图卡片</button>
      </div>
    `);

    for (const b of blocks) {
      htmlParts.push(renderReadonlyArticleBlockHtml(b));
      htmlParts.push(renderCardsAt(b.idx));
      htmlParts.push(`
        <div class="ic-notion-gap" data-gap-idx="${b.idx}">
          <button type="button" class="ic-notion-insert-btn" data-plan-insert-at="${b.idx}">＋ 在此处添加章节插图卡片</button>
        </div>
      `);
    }

    return htmlParts.join("");
  }

  function bindNotionPlanSheetInteractions(planNode, rootEl = null) {
    const sheetEl = rootEl || (DOM.previewStage && DOM.previewStage.querySelector("#pv-notion-article-sheet"));
    if (!sheetEl || !planNode) return;
    const isEditorPage = !!sheetEl.closest("#art-editor-paper") || sheetEl.id === "art-editor-flow" || sheetEl.id === "art-editor-paper";
    const resolvedTarget = resolveArticleTarget(planNode);
    const targetRefId = resolvedTarget?.isActiveCanvas
      ? planNode.id
      : resolvedTarget?.art?.id || planNode.id;

    // 1. Click card -> open full prompt modal (excluding drag handle & action buttons)
    sheetEl.querySelectorAll(".ic-plan-slot-card[data-plan-card-id], .ic-art-card[data-plan-card-id]").forEach((cardEl) => {
      cardEl.onclick = (e) => {
        if (
          e.target.closest("[data-plan-drag]") ||
          e.target.closest("[data-plan-gen-one]") ||
          e.target.closest("[data-plan-edit]") ||
          e.target.closest("[data-plan-del]") ||
          e.target.closest("[data-plan-zoom]") ||
          e.target.closest("button")
        ) {
          return;
        }
        const cid = cardEl.getAttribute("data-plan-card-id");
        if (cid) openPlanCardPromptModal(planNode, cid);
      };
    });

    // 1b. The explicit 调提示词 button. Clicking the card body also opens this,
    // but a labelled button makes the affordance visible.
    sheetEl.querySelectorAll("[data-plan-edit]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const cid = btn.getAttribute("data-plan-edit");
        if (cid) openPlanCardPromptModal(planNode, cid);
      };
    });

    // Reuse personal generation history without submitting a paid image job.
    sheetEl.querySelectorAll("[data-plan-use-history]").forEach((btn) => {
      btn.onclick = async (event) => {
        event.stopPropagation();
        const card = (planNode.data.cards || []).find(c => c.id === btn.dataset.planUseHistory);
        if (!card || card.status === "generating") return;
        ensureGenerationHistoryInitialized();
        const picked = await window.HandrawArticleWorkbench.chooseHistory(CS.generationHistory || []);
        if (!picked) return;
        const t = resolveArticleTarget(planNode);
        try { await selectArticleCardImage(t, card, picked.url); }
        catch (error) { toast(error.message); return; }
        card.imageSource = "my-history";
        card.historyImageTitle = picked.title;
        commitArticleTargetChanges(t, {bumpTime:true});
        renderFullPreviewStage();
        toast("已从个人生图历史插入图片，未产生生成费用");
      };
    });
    sheetEl.querySelectorAll("[data-plan-variants]").forEach((btn) => {
      btn.onclick = async (event) => {
        event.stopPropagation();
        const card = (planNode.data.cards || []).find(c => c.id === btn.dataset.planVariants);
        if (!card || card.status === "generating") return;
        const selected = await window.HandrawArticleWorkbench.chooseVariant(card);
        if (!selected || !selected.imageUrl || selected.imageUrl === card.imageUrl) return;
        const t = resolveArticleTarget(planNode);
        try { await selectArticleCardImage(t, card, selected.imageUrl); }
        catch (error) { toast(error.message); return; }
        renderFullPreviewStage();
        toast("已切换采用图片，其他候选仍然保留");
      };
    });

    // 2. Single card generation
    sheetEl.querySelectorAll("[data-plan-gen-one]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const cid = btn.getAttribute("data-plan-gen-one");
        if (cid) generateSinglePlanCard(targetRefId, cid);
      };
    });

    // 3. Delete card
    sheetEl.querySelectorAll("[data-plan-del]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const cid = btn.getAttribute("data-plan-del");
        if (!cid) return;
        const t = resolveArticleTarget(planNode);
        if (t?.isActiveCanvas) pushUndo();
        const deletedCard = (planNode.data.cards || []).find((c) => c.id === cid);
        planNode.data.cards = (planNode.data.cards || []).filter((c) => c.id !== cid);
        if (t?.art) t.art.cards = planNode.data.cards;
        commitArticleTargetChanges(t, { bumpTime: true });
        renderFullPreviewStage();
        if (t?.isActiveCanvas) {
          renderWorldNodes();
          renderMinimap();
        }
        renderWorkbenchBar();
        const delTitle = deletedCard?.role === "cover" ? "封面" : (deletedCard?.title || "配图卡片");
        toast(`🗑️ 已删除${delTitle}`);
        if (typeof speakArt === "function") speakArt(`已删除${delTitle}`);
      };
    });

    // 4. Zoom image
    sheetEl.querySelectorAll("[data-plan-zoom]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        openImageLightbox(btn.getAttribute("data-plan-zoom"), btn.getAttribute("data-plan-zoom-title") || "配图预览");
      };
    });

    // 5. Insert card at exact gap position
    sheetEl.querySelectorAll("[data-plan-insert-at]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const afterIdx = Number(btn.getAttribute("data-plan-insert-at"));
        insertNewPlanCard(planNode, afterIdx, { openModal: true });
      };
    });

    // Skip old drag for editor page (handled by new editor drag system)
    if (isEditorPage) return;

    // 6. Notion-style Drag-and-Drop Reordering via ⋮⋮ handle
    sheetEl.querySelectorAll("[data-plan-drag]").forEach((handleEl) => {
      handleEl.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();

        const dragCardId = handleEl.getAttribute("data-plan-drag");
        const dragCard = (planNode.data.cards || []).find((c) => c.id === dragCardId);
        const cardDom = sheetEl.querySelector(`.ic-plan-slot-card[data-plan-card-id="${dragCardId}"]`);
        if (!dragCard || !cardDom) return;

        const scrollContainer = sheetEl.closest(".ic-pv-main-scroll");
        const startY = e.clientY;
        let moved = false;
        let bestTarget = null;
        let ghostEl = null;
        let indicatorEl = null;

        const ensureDragVisuals = () => {
          if (ghostEl) return;
          cardDom.classList.add("is-dragging");
          ghostEl = document.createElement("div");
          ghostEl.className = "ic-notion-drag-ghost";
          ghostEl.textContent = `⋮⋮ 移动配图：${dragCard.title || "配图卡片"}`;
          document.body.appendChild(ghostEl);

          indicatorEl = document.createElement("div");
          indicatorEl.className = "ic-notion-drop-indicator";
          sheetEl.appendChild(indicatorEl);
        };

        const computeDropCandidates = () => {
          const cands = [];
          sheetEl.querySelectorAll(".ic-notion-gap[data-gap-idx]").forEach((gEl) => {
            const r = gEl.getBoundingClientRect();
            cands.push({
              type: "gap",
              afterBlockIdx: Number(gEl.getAttribute("data-gap-idx")),
              y: r.top + r.height * 0.5
            });
          });
          sheetEl.querySelectorAll(".ic-plan-slot-card[data-plan-card-id]").forEach((cEl) => {
            const cid = cEl.getAttribute("data-plan-card-id");
            if (cid === dragCardId) return;
            const r = cEl.getBoundingClientRect();
            const blk = Number(cEl.getAttribute("data-after-block"));
            cands.push({
              type: "before-card",
              targetCardId: cid,
              afterBlockIdx: blk,
              y: r.top - 4
            });
            cands.push({
              type: "after-card",
              targetCardId: cid,
              afterBlockIdx: blk,
              y: r.bottom + 4
            });
          });
          return cands;
        };

        const onPointerMove = (ev) => {
          if (!moved && Math.abs(ev.clientY - startY) < 4) return;
          moved = true;
          ensureDragVisuals();

          ghostEl.style.left = `${ev.clientX + 14}px`;
          ghostEl.style.top = `${ev.clientY + 12}px`;

          if (scrollContainer) {
            const sr = scrollContainer.getBoundingClientRect();
            if (ev.clientY < sr.top + 56) scrollContainer.scrollTop -= 14;
            else if (ev.clientY > sr.bottom - 56) scrollContainer.scrollTop += 14;
          }

          const cands = computeDropCandidates();
          if (!cands.length) return;
          bestTarget = cands.reduce(
            (best, cur) => (Math.abs(cur.y - ev.clientY) < Math.abs(best.y - ev.clientY) ? cur : best),
            cands[0]
          );

          const sheetRect = sheetEl.getBoundingClientRect();
          indicatorEl.style.top = `${Math.round(bestTarget.y - sheetRect.top)}px`;
        };

        const onPointerUp = () => {
          window.removeEventListener("pointermove", onPointerMove);
          window.removeEventListener("pointerup", onPointerUp);
          window.removeEventListener("pointercancel", onPointerUp);

          cardDom.classList.remove("is-dragging");
          if (ghostEl) ghostEl.remove();
          if (indicatorEl) indicatorEl.remove();

          if (!moved || !bestTarget) return;

          const t = resolveArticleTarget(planNode);
          if (t?.isActiveCanvas) pushUndo();
          const others = sortPlanCardsInDocOrder((planNode.data.cards || []).filter((c) => c.id !== dragCardId));
          dragCard.afterBlockIdx = bestTarget.afterBlockIdx;

          if (bestTarget.type === "before-card") {
            const ti = others.findIndex((c) => c.id === bestTarget.targetCardId);
            others.splice(ti >= 0 ? ti : others.length, 0, dragCard);
          } else if (bestTarget.type === "after-card") {
            const ti = others.findIndex((c) => c.id === bestTarget.targetCardId);
            others.splice(ti >= 0 ? ti + 1 : others.length, 0, dragCard);
          } else {
            let insertAt = 0;
            for (let i = 0; i < others.length; i++) {
              const ob = typeof others[i].afterBlockIdx === "number" ? others[i].afterBlockIdx : -1;
              if (ob <= bestTarget.afterBlockIdx) {
                insertAt = i + 1;
              }
            }
            others.splice(insertAt, 0, dragCard);
          }

          planNode.data.cards = sortPlanCardsInDocOrder(others);
          commitArticleTargetChanges(t, { bumpTime: true });
          renderFullPreviewStage();
          if (t?.isActiveCanvas) renderWorldNodes();
          toast("✨ 已拖动调整配图位置");
        };

        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerUp);
      });
    });
  }

  function extractArticlePlainExcerpt(md) {
    const blocks = E.parseArticleReadonlyBlocks(md || "");
    const bodyText = blocks
      .filter((b) => b.kind !== "h1" && b.kind !== "hr")
      .map((b) => b.text)
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();
    return bodyText || "点击进入文章配图编排页，可调整封面与章节插图提示词并批量生成配图。";
  }

  function removeArticleFromWorkspace(aid) {
    if (!aid) return;
    if (CS.graph && Array.isArray(CS.graph.nodes)) {
      CS.graph.nodes = CS.graph.nodes.filter(
        (n) => !(n.type === "article_plan" && (n.id === aid || n.data?.articleId === aid))
      );
    }
    for (const t of CS.tabs || []) {
      if (t.graph && Array.isArray(t.graph.nodes)) {
        t.graph.nodes = t.graph.nodes.filter(
          (n) => !(n.type === "article_plan" && (n.id === aid || n.data?.articleId === aid))
        );
      }
    }
  }

  function deleteArticle(aid) {
    const art = findArticleById(aid) || (CS.myArticles || []).find((x) => x.id === aid);
    const title = art?.articleTitle || (CS.articleEditorDraft?.id === aid ? CS.articleEditorDraft.title : "") || "未命名文章";
    if (S && typeof S.deleteArticle === "function") {
      return S.deleteArticle(aid, {
        articleTitle: title,
        onSuccess() {
          CS.myArticles = (CS.myArticles || []).filter((x) => x.id !== aid);
          removeArticleFromWorkspace(aid);
          clearUnifiedArticleEditorFlush();
          persistMyArticles();
          persistOpenTabs();

          const wasActive = CS.activeArticleId === aid || CS.articleEditorDraft?.id === aid;
          if (wasActive) {
            CS.articleEditorDraft = null;
            CS.activeArticleId = CS.myArticles[0]?.id || null;
          }

          if (CS.articleSubView === "editor" || wasActive) {
            openMyArticlesPage({ subView: "all-list" });
          } else {
            renderFullPreviewStage();
          }
        }
      });
    }
    CS.myArticles = (CS.myArticles || []).filter((x) => x.id !== aid);
    removeArticleFromWorkspace(aid);
    clearUnifiedArticleEditorFlush();
    persistMyArticles();
    persistOpenTabs();
    const wasActive = CS.activeArticleId === aid || CS.articleEditorDraft?.id === aid;
    if (wasActive) {
      CS.articleEditorDraft = null;
      CS.activeArticleId = CS.myArticles[0]?.id || null;
    }
    if (CS.articleSubView === "editor" || wasActive) {
      openMyArticlesPage({ subView: "all-list" });
    } else {
      renderFullPreviewStage();
    }
  }

  function renderAllArticlesPaginatedPage(sortedArticles) {
    const PAGE_SIZE = 6;
    const q = String(CS.articleListQuery || "").trim().toLowerCase();
    const filter = CS.articleListFilter || "all";

    const filtered = sortedArticles.filter((a) => {
      const cards = a.cards || [];
      const readyCnt = cards.filter((c) => c.imageUrl).length;
      if (filter === "ready" && readyCnt === 0) return false;
      if (filter === "pending" && readyCnt > 0) return false;
      if (q) {
        const hay = `${a.articleTitle || ""} ${a.markdown || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (!CS.articleListPage || CS.articleListPage < 1) CS.articleListPage = 1;
    if (CS.articleListPage > totalPages) CS.articleListPage = totalPages;
    const curPage = CS.articleListPage;
    const pageItems = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);

    DOM.previewStage.innerHTML = `
      <div class="ic-pv-topbar">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:nowrap;">
          <button type="button" class="btn btn-sm" id="pv-all-back-detail" style="font-weight:850;">← 返回编辑模式</button>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <button type="button" class="btn btn-sm btn-primary" id="pv-all-new-article" style="font-weight:800;">＋ 新建文章</button>
        </div>

        <div style="display:flex;align-items:center;gap:8px;flex-wrap:nowrap;">
          <div class="ic-view-seg">
            <button type="button" class="ic-view-seg-btn ${filter === "all" ? "is-active" : ""}" data-art-filter="all">全部</button>
            <button type="button" class="ic-view-seg-btn ${filter === "ready" ? "is-active" : ""}" data-art-filter="ready">已配图</button>
            <button type="button" class="ic-view-seg-btn ${filter === "pending" ? "is-active" : ""}" data-art-filter="pending">待生图</button>
          </div>
          <input
            type="search"
            class="hw-input"
            id="pv-all-search"
            value="${esc(CS.articleListQuery || "")}"
            placeholder="搜索文章标题或正文…"
            style="width:220px;padding:5px 10px;font-size:12px;"
          />
        </div>
      </div>

      <div class="ic-art-page-scroll">
        <div class="ic-art-page-inner">
          ${
            !pageItems.length
              ? `
              <div style="padding:72px 24px;text-align:center;background:var(--ic-panel-solid);border:1px dashed var(--ic-border-strong);border-radius:18px;color:var(--ic-muted);">
                <div style="font-size:28px;margin-bottom:8px;">📄</div>
                <div style="font-size:14.5px;font-weight:800;color:var(--ic-ink);">没有找到匹配的历史文章</div>
                <div style="font-size:12.5px;margin-top:4px;">可尝试清空筛选关键词，或返回无限画布通过「文章配图」创建新文章</div>
              </div>
            `
              : `
              <div class="ic-art-page-grid" id="pv-all-articles-grid">
                ${pageItems
                  .map((a) => {
                    const ordered = sortPlanCardsInDocOrder(a.cards || []);
                    const readyCards = ordered.filter((c) => c.imageUrl);
                    const coverImg =
                      ordered.find((c) => c.role === "cover" && c.imageUrl)?.imageUrl ||
                      readyCards[0]?.imageUrl ||
                      "";
                    const generating = isArticleGenerating(a);
                    const excerpt = extractArticlePlainExcerpt(a.markdown);
                    return `
                      <article class="ic-art-page-card" data-open-art-id="${esc(a.id)}">
                        <div class="ic-art-page-cover">
                          ${
                            coverImg
                              ? `<img data-hw-src="${esc(coverImg)}" alt="${esc(a.articleTitle || "文章封面")}" loading="lazy" />`
                              : `
                              <div style="width:100%;height:100%;padding:20px 24px;display:flex;flex-direction:column;justify-content:center;gap:6px;background:linear-gradient(135deg, rgba(183,66,39,0.06), rgba(31,111,74,0.05));">
                                <span style="font-size:11px;font-weight:800;color:var(--vermilion);letter-spacing:0.04em;">手绘风专栏草稿</span>
                                <div style="font-family:var(--font-serif);font-size:16px;font-weight:850;color:var(--ic-ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
                                  ${esc(a.articleTitle || "未命名文章")}
                                </div>
                              </div>
                            `
                          }
                          <span style="position:absolute;right:10px;top:10px;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:800;background:${
                            generating
                              ? "var(--vermilion)"
                              : readyCards.length > 0
                                ? "rgba(20,17,15,0.74)"
                                : "rgba(255,253,249,0.92)"
                          };color:${generating || readyCards.length > 0 ? "#fff" : "var(--ic-muted)"};border:1px solid rgba(0,0,0,0.08);">
                            ${
                              generating
                                ? "⏳ 正在生图…"
                                : readyCards.length > 0
                                  ? `✓ 已配图 ${readyCards.length}/${ordered.length}`
                                  : `● 待生图 (${ordered.length} 卡位)`
                            }
                          </span>
                        </div>

                        <div style="padding:14px 16px 15px;display:flex;flex-direction:column;gap:8px;flex:1;">
                          <h3 style="margin:0;font-family:var(--font-serif);font-size:16px;font-weight:850;line-height:1.4;color:var(--ic-ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
                            ${esc(a.articleTitle || "未命名文章")}
                          </h3>
                          <p style="margin:0;font-size:12.6px;line-height:1.62;color:var(--ic-muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;flex:1;">
                            ${esc(excerpt)}
                          </p>
                          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding-top:8px;border-top:1px dashed var(--ic-border);">
                            <span style="font-size:11.5px;color:var(--ic-muted);font-family:var(--font-mono);">
                              ${esc(a.timeLabel || formatArticleTimeLabel(a.updatedAtMs))}
                            </span>
                            <div style="display:flex;align-items:center;gap:6px;">
                              <button type="button" class="btn btn-sm btn-primary" data-edit-art-btn="${esc(a.id)}" style="padding:3px 10px;font-size:11.5px;font-weight:750;">📖 打开文章</button>
                              <button type="button" class="ic-icon-btn" data-del-art-id="${esc(a.id)}" title="删除此历史文章记录" style="padding:3px 6px;font-size:12px;color:#dc2626;">🗑️</button>
                            </div>
                          </div>
                        </div>
                      </article>
                    `;
                  })
                  .join("")}
              </div>
            `
          }

          <nav class="ic-art-pagination" aria-label="文章列表分页导航">
            <button type="button" class="btn btn-sm" id="pv-page-prev" ${curPage <= 1 ? "disabled" : ""}>‹ 上一页</button>
            ${Array.from({ length: totalPages }, (_, idx) => {
              const p = idx + 1;
              return `<button type="button" class="btn btn-sm ${p === curPage ? "btn-primary" : ""}" data-art-page="${p}" style="min-width:34px;justify-content:center;font-weight:850;">${p}</button>`;
            }).join("")}
            <button type="button" class="btn btn-sm" id="pv-page-next" ${curPage >= totalPages ? "disabled" : ""}>下一页 ›</button>
            <span style="font-size:12px;color:var(--ic-muted);margin-left:8px;">
              第 ${curPage} / ${totalPages} 页 · 共 ${filtered.length} 篇文章
            </span>
          </nav>
        </div>
      </div>
    `;

    const allBackDetailBtn = DOM.previewStage.querySelector("#pv-all-back-detail");
    if (allBackDetailBtn) {
      allBackDetailBtn.onclick = () => {
        try {
          if (window.location.search.includes("view=")) {
            window.history.replaceState(null, "", window.location.pathname);
          }
        } catch (_) {}
        if (CS.activeArticleId) {
          openUnifiedArticleEditor(CS.activeArticleId);
        } else {
          openUnifiedArticleEditor(null, { createNew: true });
        }
      };
    }

    const allNewArtBtn = DOM.previewStage.querySelector("#pv-all-new-article");
    if (allNewArtBtn) {
      allNewArtBtn.onclick = () => {
        openUnifiedArticleEditor(null, { createNew: true });
      };
    };

    DOM.previewStage.querySelectorAll("[data-art-filter]").forEach((btn) => {
      btn.onclick = () => {
        CS.articleListFilter = btn.getAttribute("data-art-filter") || "all";
        CS.articleListPage = 1;
        renderFullPreviewStage();
      };
    });

    const searchInp = DOM.previewStage.querySelector("#pv-all-search");
    if (searchInp) {
      searchInp.oninput = () => {
        CS.articleListQuery = searchInp.value;
        CS.articleListPage = 1;
        const pos = searchInp.selectionStart;
        renderFullPreviewStage();
        const nextInp = DOM.previewStage.querySelector("#pv-all-search");
        if (nextInp) {
          nextInp.focus();
          try {
            nextInp.setSelectionRange(pos, pos);
          } catch (_) {}
        }
      };
    }

    const goToPage = (p) => {
      CS.articleListPage = Math.max(1, Math.min(totalPages, p));
      try {
        window.history.replaceState(null, "", `?view=articles-all&page=${CS.articleListPage}`);
      } catch (_) {}
      renderFullPreviewStage();
      const sc = DOM.previewStage.querySelector(".ic-art-page-scroll");
      if (sc) sc.scrollTop = 0;
    };

    const prevBtn = DOM.previewStage.querySelector("#pv-page-prev");
    if (prevBtn) prevBtn.onclick = () => goToPage(curPage - 1);
    const nextBtn = DOM.previewStage.querySelector("#pv-page-next");
    if (nextBtn) nextBtn.onclick = () => goToPage(curPage + 1);
    DOM.previewStage.querySelectorAll("[data-art-page]").forEach((btn) => {
      btn.onclick = () => goToPage(Number(btn.getAttribute("data-art-page")) || 1);
    });

    DOM.previewStage.querySelectorAll("[data-open-art-id]").forEach((cardEl) => {
      cardEl.onclick = (e) => {
        if (e.target.closest("[data-del-art-id]") || e.target.closest("[data-edit-art-btn]")) return;
        const aid = cardEl.getAttribute("data-open-art-id");
        if (aid) {
          openUnifiedArticleEditor(aid);
        }
      };
    });

    DOM.previewStage.querySelectorAll("[data-edit-art-btn]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const aid = btn.getAttribute("data-edit-art-btn");
        if (!aid) return;
        openUnifiedArticleEditor(aid);
      };
    });

    DOM.previewStage.querySelectorAll("[data-del-art-id]").forEach((delBtn) => {
      delBtn.onclick = (e) => {
        e.stopPropagation();
        const aid = delBtn.getAttribute("data-del-art-id");
        if (!aid) return;
        deleteArticle(aid);
      };
    });
  }

  function renderFullPreviewStage() {
    if (!DOM.previewStage) return;
    if (CS.stageView !== "preview") {
      DOM.previewStage.style.display = "none";
      return;
    }
    DOM.previewStage.style.display = "flex";

    syncAllTabsArticlesIntoStore();
    const sortedArticles = getSortedMyArticles();

    if (CS.articleSubView === "all-list") {
      renderAllArticlesPaginatedPage(sortedArticles);
      return;
    }

    const activeSummary=CS.activeArticleId && findArticleById(CS.activeArticleId);
    if(activeSummary?._summary) {
      DOM.previewStage.innerHTML='<p style="padding:32px" role="status">正在加载文章…</p>';
      if(CS.articleLoadingId!==activeSummary.id) {
        CS.articleLoadingId=activeSummary.id;
        const epoch=cacheScopeEpoch,scope=activeCacheScope;
        void loadArticleDocument(activeSummary.id).then(loaded=>{
          if(loaded&&!isStaleScope(epoch,scope)&&CS.activeArticleId===activeSummary.id) renderFullPreviewStage();
        }).catch(error=>toast(error.message||"文章加载失败，请重试")).finally(()=>{
          if(!isStaleScope(epoch,scope)&&CS.articleLoadingId===activeSummary.id) CS.articleLoadingId=null;
        });
      }
      return;
    }

    if (CS.articleSubView === "reader" && CS.activeArticleId) {
      renderArticlePreviewPage(CS.activeArticleId);
      return;
    }

    // Every non-directory article subview funnels into the unified editor workbench.
    if (CS.articleSubView !== "editor") {
      CS.articleSubView = "editor";
    }

    const draft = CS.articleEditorDraft;
    const draftId = draft ? draft.id : null;
    const shouldLoadActiveIncoming = !!(
      CS.activeArticleId &&
      draftId !== CS.activeArticleId &&
      !(draft && draft.isNewDraft && !CS.activeArticleId)
    );
    if (!draft) {
      const art = CS.activeArticleId ? findArticleById(CS.activeArticleId) : null;
      CS.articleEditorDraft = art ? draftFromArticle(art) : makeBlankArticleDraft();
    } else if (shouldLoadActiveIncoming) {
      const art = findArticleById(CS.activeArticleId);
      if (art) CS.articleEditorDraft = draftFromArticle(art);
    }

    renderArticleEditorPage(sortedArticles);
  }

  function renderTopAndBottomDocks() {
    if (!DOM.root) return;
    DOM.root.setAttribute("data-canvas-theme", CS.canvasTheme);
    DOM.root.classList.toggle("edges-hidden", CS.edgesHidden);

    // Legacy graphs remain an internal implementation of the quick/batch
    // forms. They are never the parameter canvas document or its execution.
    if (DOM.canvasStage) DOM.canvasStage.style.display="none";
    if (DOM.workbenchBar) DOM.workbenchBar.style.display="none";
    if (DOM.parameterStage) {
      DOM.parameterStage.style.display=CS.stageView==="canvas"?"flex":"none";
      if(CS.stageView==="canvas") window.HandrawParameterCanvas?.mount(DOM.parameterStage,{
        scope:activeCacheScope,api:S.apiJson,
        loggedIn:()=>Boolean(App.state?.loggedIn && App.state?.serverBacked),
        resources:kind=>kind==="style"?Catalog.styles:Catalog.layouts,
        pickReferences:settings=>openAssetPickerModal(settings)
      });
    }

    renderCreationModeBar();
    renderWorkbenchBar();
    renderCanvasToolstrip();
    renderFullPreviewStage();
    renderHistoryStage();
    renderWorkflowsStage();
    renderQuickStart();

    if (DOM.bottomRight) {
      DOM.bottomRight.style.display = "none";
      DOM.bottomRight.innerHTML = "";
      DOM.zoomPctBtn = null;
    }
  }

  /* ======================== CONTEXT MENU, VIEWPORT INTERACTIONS & BOOT ======================== */
  function zoomAroundPoint(clientX, clientY, factor) {
    if (!DOM.viewport) return;
    const rect = DOM.viewport.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const oldK = CS.vk;
    const newK = Math.max(0.2, Math.min(3.0, Number((oldK * factor).toFixed(4))));
    if (newK === oldK) return;
    const wx = (px - CS.vx) / oldK;
    const wy = (py - CS.vy) / oldK;
    CS.vk = newK;
    CS.vx = px - wx * newK;
    CS.vy = py - wy * newK;
    applyViewportTransform();
  }

  function zoomAroundCenter(factor) {
    if (!DOM.viewport) return;
    const r = DOM.viewport.getBoundingClientRect();
    zoomAroundPoint(r.left + r.width * 0.5, r.top + r.height * 0.5, factor);
  }

  function closeContextMenu() {
    if (DOM.ctxMenu) {
      DOM.ctxMenu.remove();
      DOM.ctxMenu = null;
    }
  }

  function openContextMenu(clientX, clientY, worldPos, fromPort = null) {
    closeContextMenu();
    const menu = document.createElement("div");
    menu.className = "ic-context-menu";
    menu.style.left = `${Math.min(window.innerWidth - 268, clientX)}px`;
    menu.style.top = `${Math.min(window.innerHeight - 320, clientY)}px`;

    let headerText = "添加节点";
    let actions = [];

    if (fromPort && fromPort.newWorkflowMenu) {
      headerText = "新建典型场景示范工作流";
      actions = [
        { icon: "", label: "节气海报极速出图（3节点·极简）", act: "wf_single" },
        { icon: "", label: "百图矩阵批量生产（1母题→100张·仅1输出）", act: "wf_loop_100" },
        { icon: "", label: "同文案多画风横评比稿（多画风×4）", act: "wf_style_ab" },
        { icon: "", label: "IP角色连续故事绘本（锁角色·套图混排）", act: "wf_ip_story" },
        { icon: "", label: "全媒体一稿三端宣发包（多尺寸→3规格生成设置）", act: "wf_omnimedia" },
        { icon: "", label: "深度长文自动配图与排版（.md+ZIP）", act: "wf_article" },
        { icon: "", label: "跨媒介双画风融合实验（双画风合成）", act: "wf_fusion" },
        { icon: "", label: "空白画布", act: "wf_blank" },
        { icon: "", label: "打开预置与我的工作流库…", act: "wf_lib" }
      ];
    } else if (fromPort && fromPort.dir === "out") {
      const srcNode = getNodeById(fromPort.nodeId);
      headerText = "松手新建下游节点";
      actions =
        srcNode && isInputNodeType(srcNode.type)
          ? [
              { icon: "", label: "新建【批量】并连线（批量出图）", act: "spawn_down_loop" },
              { icon: "", label: "新建【生成设置】并连线", act: "spawn_down_ctrl" },
              { icon: "", label: "新建【多尺寸输出】并连线（一分多规格）", act: "spawn_down_bridge" }
            ]
          : [{ icon: "", label: "新建【生成设置】并连线", act: "spawn_down_ctrl" }];
    } else if (fromPort && fromPort.dir === "in") {
      const dstNode = getNodeById(fromPort.nodeId);
      headerText = "松手补充上游节点";
      actions = [
        { icon: "", label: "连入【风格参数】节点", act: "spawn_up_skill_params" },
        { icon: "", label: "连入【图片参数】节点", act: "spawn_up_asset" },
        { icon: "", label: "连入【文本参数】节点（含文件选择）", act: "spawn_up_text_input" },
        { icon: "", label: "连入【AI 扩写主题】节点（默认10条·支持自填）", act: "spawn_up_fission" },
        ...(dstNode && dstNode.type === "output_control"
          ? [
              { icon: "", label: "连入【批量】节点", act: "spawn_up_loop" },
              { icon: "", label: "连入【多尺寸输出】节点", act: "spawn_up_bridge" }
            ]
          : [])
      ];
    } else {
      actions = [
        { icon: "", label: "输入：风格参数", act: "new_skill_params" },
        { icon: "", label: "输入：图片参数", act: "new_asset" },
        { icon: "", label: "输入：文本参数（可附带文件）", act: "new_text_input" },
        { icon: "", label: "扩写：AI 扩写主题（默认10条·支持自填）", act: "new_fission" },
        { icon: "", label: "批量：批量（批量出图）", act: "new_loop" },
        { icon: "", label: "多尺寸：多尺寸输出（一稿多规格）", act: "new_bridge" },
        { icon: "", label: "输出：生成设置", act: "new_output_control" }
      ];
    }

    menu.innerHTML = `
      <div style="padding:4px 8px;font-size:10.8px;font-weight:800;color:var(--ic-muted);">${esc(headerText)}</div>
      ${actions.map((a) => `<button type="button" class="ic-context-item" data-ctx-act="${a.act}">${a.icon ? `<span>${a.icon}</span>` : ""}<span>${esc(a.label)}</span></button>`).join("")}
    `;

    (DOM.root || document.body).appendChild(menu);
    DOM.ctxMenu = menu;

    menu.querySelectorAll("[data-ctx-act]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const act = btn.getAttribute("data-ctx-act");
        closeContextMenu();

        if (act.startsWith("wf_")) {
          if (act === "wf_lib") {
            openWorkflowLibraryModal();
            return;
          }
          const bp = act.replace("wf_", "");
          const names = {
            single: "节气海报极速出图",
            loop_100: "百图矩阵批量生产",
            loop: "百图矩阵批量生产",
            style_ab: "同文案多画风横评比稿",
            ip_story: "IP角色连续故事绘本",
            omnimedia: "全媒体一稿三端宣发包",
            article: "深度长文自动配图",
            series: "IP角色连续故事绘本",
            fusion: "跨媒介双画风融合",
            blank: "空白工作流"
          };
          createWorkflowTab({ title: names[bp] || "新工作流", blueprint: bp, makeActive: true, autoFit: true, switchToCanvas: true });
          return;
        }

        const wx = snapVal(worldPos.x - 140);
        const wy = snapVal(worldPos.y - 90);

        if (act === "spawn_down_ctrl") {
          pushUndo();
          const src = getNodeById(fromPort.nodeId);
          const ctrl = E.makeOutputControlNode(snapVal(worldPos.x), snapVal(worldPos.y - 140));
          CS.graph.nodes.push(ctrl);
          if (src) ensureEdge(src.id, ctrl.id);
          CS.graph.selectedIds = [ctrl.id];
          fullRenderCanvas();
          persistOpenTabs();
        } else if (act === "spawn_down_loop") {
          pushUndo();
          const src = getNodeById(fromPort.nodeId);
          const lp = E.makeLoopNode(snapVal(worldPos.x), snapVal(worldPos.y - 120));
          CS.graph.nodes.push(lp);
          if (src) ensureEdge(src.id, lp.id);
          CS.graph.selectedIds = [lp.id];
          fullRenderCanvas();
          persistOpenTabs();
        } else if (act === "spawn_down_bridge") {
          pushUndo();
          const src = getNodeById(fromPort.nodeId);
          const br = E.makeBridgeNode(snapVal(worldPos.x), snapVal(worldPos.y - 84));
          CS.graph.nodes.push(br);
          if (src) ensureEdge(src.id, br.id);
          CS.graph.selectedIds = [br.id];
          fullRenderCanvas();
          persistOpenTabs();
        } else if (act === "spawn_up_loop") {
          pushUndo();
          const dst = getNodeById(fromPort.nodeId);
          const lp = E.makeLoopNode(snapVal(worldPos.x - 240), snapVal(worldPos.y - 120));
          CS.graph.nodes.push(lp);
          if (dst) ensureEdge(lp.id, dst.id);
          CS.graph.selectedIds = [lp.id];
          fullRenderCanvas();
          persistOpenTabs();
        } else if (act === "spawn_up_bridge") {
          pushUndo();
          const dst = getNodeById(fromPort.nodeId);
          const br = E.makeBridgeNode(snapVal(worldPos.x - 200), snapVal(worldPos.y - 84));
          CS.graph.nodes.push(br);
          if (dst) ensureEdge(br.id, dst.id);
          CS.graph.selectedIds = [br.id];
          fullRenderCanvas();
          persistOpenTabs();
        } else if (act.startsWith("spawn_up_")) {
          const kind = act.replace("spawn_up_", "");
          spawnShelfItem({ kind }, { x: wx - 160, y: wy }, fromPort.nodeId);
        } else if (act.startsWith("new_")) {
          const kind = act.replace("new_", "");
          spawnShelfItem({ kind }, { x: wx, y: wy }, null);
        }
      };
    });
  }

  // Quick-create shares the canvas graph and the existing guarded task runner.
  let quickBusy = null;

  function generationCostText(count) {
    const qty = count != null && Number.isFinite(Number(count)) ? Math.max(0, Number(count)) : null;
    if (CS.engineMode === "demo") return `演示模式 · 本批 ${qty ?? "待确认"} 张，不消耗真实生图额度`;
    if (!App.state?.loggedIn) return "登录后查看免费额度、积分余额与本批预计费用";
    const rawFree = App.state.freeQuotaRemaining ?? App.state.free_quota_remaining;
    const rawPrice = CS.serverCfg?.creditPerImage;
    const free = rawFree == null ? NaN : Number(rawFree);
    const price = rawPrice == null ? NaN : Number(rawPrice);
    const freeKnown = Number.isFinite(free) && free >= 0;
    const priceKnown = Number.isFinite(price) && price >= 0;
    const total = qty !== null && freeKnown && priceKnown ? Math.max(0, qty - free) * price : null;
    const balance = Number(App.state.credits);
    return `本批 ${qty ?? "待确认"} 张 · 免费额度 ${freeKnown ? free : "待确认"} 张 · 单张 ${priceKnown ? price : "待确认"} 积分 · 预计 ${total ?? "待确认"} 积分${Number.isFinite(balance) ? ` · 余额 ${balance} 积分` : ""}`;
  }

  function getQuickParts(graph = CS.graph) {
    const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
    const edges = Array.isArray(graph?.edges) ? graph.edges : [];
    const allowed = new Set(["skill_params", "text_input", "output_control", "output_display", "asset"]);
    const controls = nodes.filter((n) => n.type === "output_control");
    const skills = nodes.filter((n) => n.type === "skill_params");
    const texts = nodes.filter((n) => n.type === "text_input");
    const assets = nodes.filter((n) => n.type === "asset");
    if (nodes.some((n) => !allowed.has(n.type)) || controls.length !== 1 || skills.length !== 1 || texts.length !== 1) return null;
    const ctrl = controls[0];
    if (!["graphic-text", "pure", "pure-image", "poster", "series"].includes(ctrl.data?.mode)) return null;
    // Multiple inputs or disconnected graphs must stay in the full canvas.
    const inbound = edges.filter((e) => e.to === ctrl.id).map((e) => e.from);
    if (!inbound.includes(skills[0].id) || !inbound.includes(texts[0].id)) return null;
    return { ctrl, skill: skills[0], text: texts[0], asset: assets[0] || null };
  }

  function ensureQuickTab() {
    const activeParts = getQuickParts(CS.graph);
    if (activeParts) {
      const activeTab = CS.tabs.find((t) => t.id === CS.activeTabId);
      if (activeTab) {
        activeTab.quickStart = true;
        return activeTab;
      }
    }
    let tab = CS.tabs.find((t) => {
      const graph = t.id === CS.activeTabId ? CS.graph : t.graph;
      return t.quickStart === true && graph && getQuickParts(graph);
    });
    if (!tab) {
      const sp = E.makeSkillParamsNode(64, 56, {});
      const txt = E.makeTextInputNode(64, 548, { text: "" });
      const ctrl = E.makeOutputControlNode(488, 176, { mode: "graphic-text", count: 1, ratio: "3:4" });
      const graph = {
        blueprint: "single",
        nodes: [sp, txt, ctrl],
        edges: [
          { id: E.uid("edge"), from: sp.id, to: ctrl.id },
          { id: E.uid("edge"), from: txt.id, to: ctrl.id }
        ],
        selectedIds: []
      };
      tab = createWorkflowTab({ title: "快速创作", blueprint: "single", graph, makeActive: false });
      tab.quickStart = true;
    }
    activateWorkflowTab(tab.id);
    persistOpenTabs();
    return tab;
  }

  function getBatchParts(graph = CS.graph) {
    const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
    const edges = Array.isArray(graph?.edges) ? graph.edges : [];
    const controls = nodes.filter((n) => n.type === "output_control");
    const loops = nodes.filter((n) => n.type === "loop");
    const skills = nodes.filter((n) => n.type === "skill_params");
    const texts = nodes.filter((n) => n.type === "text_input");
    const assets = nodes.filter((n) => n.type === "asset");
    if (controls.length !== 1 || loops.length !== 1 || skills.length !== 1) return null;
    const ctrl = controls[0];
    const loop = loops[0];
    const skill = skills[0];
    const text = texts[0] || null;
    const asset = assets[0] || null;
    const loopToCtrl = edges.some((e) => e.from === loop.id && e.to === ctrl.id);
    if (!loopToCtrl) return null;
    return { ctrl, loop, skill, text, asset };
  }

  function ensureBatchTab() {
    const activeParts = getBatchParts(CS.graph);
    if (activeParts) {
      const activeTab = CS.tabs.find((t) => t.id === CS.activeTabId);
      if (activeTab) {
        activeTab.batchStart = true;
        return activeTab;
      }
    }
    let tab = CS.tabs.find((t) => {
      const graph = t.id === CS.activeTabId ? CS.graph : t.graph;
      return t.batchStart === true && graph && getBatchParts(graph);
    });
    if (!tab) {
      const sp = E.makeSkillParamsNode(64, 56, {});
      const txt = E.makeTextInputNode(64, 480, { text: "" });
      const ast = E.makeAssetNode(64, 760, { items: [] });
      const lp = E.makeLoopNode(468, 200, {
        loopMode: "prompts",
        promptListText: "春日阳光下的街角手账\n午后一杯热咖啡的治愈时光\n暮色中的旧书摊与晚霞",
        batchLayoutMode: "ai",
        batchCount: 3,
        batchRows: [
          {theme:"春日阳光下的街角手账",layout:"",assetItems:[]},
          {theme:"午后一杯热咖啡的治愈时光",layout:"",assetItems:[]},
          {theme:"暮色中的旧书摊与晚霞",layout:"",assetItems:[]}
        ],
        maxIterations: 200
      });
      const ctrl = E.makeOutputControlNode(880, 200, { mode: "graphic-text", count: 1, ratio: "3:4" });
      const graph = {
        blueprint: "loop_100",
        nodes: [sp, txt, ast, lp, ctrl],
        edges: [
          { id: E.uid("edge"), from: sp.id, to: lp.id },
          { id: E.uid("edge"), from: sp.id, to: ctrl.id },
          { id: E.uid("edge"), from: txt.id, to: lp.id },
          { id: E.uid("edge"), from: ast.id, to: lp.id },
          { id: E.uid("edge"), from: ast.id, to: ctrl.id },
          { id: E.uid("edge"), from: lp.id, to: ctrl.id }
        ],
        selectedIds: []
      };
      tab = createWorkflowTab({ title: "系列图", blueprint: "loop_100", graph, makeActive: false });
      tab.batchStart = true;
    }
    activateWorkflowTab(tab.id);
    persistOpenTabs();
    return tab;
  }

  function setQuickField(field, value) {
    const p = getQuickParts();
    if (!p || p.ctrl.data.status === "generating") return;
    if (field === "topic") p.text.data.text = String(value);
    else if (field === "count") {
      p.ctrl.data.count = 1;
    } else if (field === "ratio") {
      if (!/^\d+(?:\.\d+)?:\d+(?:\.\d+)?$/.test(String(value)) || String(value).split(":").some((x) => Number(x) <= 0)) return;
      p.ctrl.data.ratio = String(value);
    } else if (field === "mode") {
      const mode = value === "pure-image" ? "pure" : value;
      if (["graphic-text", "pure", "pure-image", "poster", "series"].includes(value)) {
        p.ctrl.data.mode = mode;
        const defaultRatio = mode === "poster" ? "9:16" : (mode === "graphic-text" || mode === "pure" || mode === "pure-image") ? "3:4" : p.ctrl.data.ratio;
        p.ctrl.data.ratio = defaultRatio;
      }
    } else if (field === "fusion") {
      p.skill.data.fusion = Boolean(value);
      if (!p.skill.data.fusion) p.skill.data.style2 = "";
    } else if (field === "style1") {
      p.skill.data.style1 = String(value || "");
    } else if (field === "style2") {
      p.skill.data.style2 = String(value || "");
    } else if (field === "layout") {
      p.skill.data.layout = String(value || "");
    } else if (field === "colors") {
      p.skill.data.colors = Array.isArray(value) ? value : [];
    } else if (field === "tones") {
      p.skill.data.tones = Array.isArray(value) ? value : [];
    } else if (field === "moods") {
      p.skill.data.moods = Array.isArray(value) ? value : [];
    } else if (field === "customMood") {
      p.skill.data.customMood = String(value || "");
    } else if (field === "whitespace") {
      p.skill.data.whitespace = String(value || "");
    } else if (field === "audience") {
      p.skill.data.audience = String(value || "");
    } else if (field === "businessScene") {
      p.skill.data.businessScene = String(value || "");
    } else if (field === "sc021Type") {
      p.skill.data.sc021Type = String(value || "");
    } else if (field === "sc022Name") {
      p.skill.data.sc022Name = String(value || "");
    } else if (field === "sc022Pinyin") {
      p.skill.data.sc022Pinyin = String(value || "");
    } else return;
    const tab = CS.tabs.find((t) => t.id === CS.activeTabId);
    if (tab) tab.dirty = true;
    persistOpenTabs();
    if (CS.stageView === "quick") renderQuickStart();
  }

  function applyForkDraftToQuickNodes(draft) {
    if (!draft) return;
    if (draft.source) {
      CS.forkGenerationSource = draft.source;
    }
    ensureQuickTab();
    const p = getQuickParts();
    if (!p) return;
    const sd = p.skill.data;
    const td = p.text.data;
    const cd = p.ctrl.data;

    sd.fusion = Array.isArray(draft.styleIds) && draft.styleIds.length > 1;
    sd.style1 = draft.styleIds?.[0] || "";
    sd.style2 = draft.styleIds?.[1] || "";
    sd.layout = draft.layoutId || "";
    sd.colors = Array.isArray(draft.colors) ? [...draft.colors] : [];
    sd.tones = Array.isArray(draft.tones) ? [...draft.tones] : [];
    sd.moods = (Array.isArray(draft.moods) ? draft.moods : []).map(normalizeMoodLabel).filter(Boolean);
    sd.customMood = draft.customMood || "";
    sd.whitespace = draft.whitespace || "";
    sd.audience = draft.audience || "";
    sd.businessScene = draft.businessScene || "";

    let extractedTheme = String(draft.subjectHint || draft.subject || "").trim();
    if (!extractedTheme && draft.prompt) {
      const rawPrompt = String(draft.prompt).trim();
      const sentences = rawPrompt.split(/[。！？\n.!?]/).map((s) => s.trim()).filter(Boolean);
      if (sentences.length > 0) extractedTheme = sentences[0].slice(0, 80);
    }
    td.text = extractedTheme;
    td.subjectHint = draft.subjectHint || extractedTheme || "";

    cd.ratio = draft.ratio || "3:4";
    const forkMode = draft.mode === "pure-image" ? "pure" : (draft.mode || "graphic-text");
    cd.mode = ["graphic-text", "pure", "poster", "series"].includes(forkMode) ? forkMode : "graphic-text";
    cd.count = 1;

    // A fork is a new recipe, not a continuation of the previous quick draft.
    // Never inherit private reference assets from the previously active graph.
    // The from-work recipe endpoint does not grant those assets to a forker.
    if (p.asset?.data) p.asset.data.items = [];

    markActiveTabDirty();
    persistOpenTabs();
    if (CS.stageView === "quick") renderQuickStart();
  }
  if (window.HandrawMakeImage) {
    window.HandrawMakeImage.applyForkDraft = applyForkDraftToQuickNodes;
  }

  function ensureArticleForArticleMode() {
    syncAllTabsArticlesIntoStore();
    const sorted = getSortedMyArticles();
    if (sorted.length > 0) return;
    const tab = findArticleWorkspaceTab();
    const planNode = (isArticleGraph(CS.graph) ? CS.graph : tab?.graph)?.nodes?.find((n) => n.type === "article_plan");
    if (planNode) {
      syncPlanNodeToMyArticles(planNode, { tabId: tab ? tab.id : CS.activeTabId, bumpTime: false, hostGraph: tab ? tab.graph : CS.graph });
      return;
    }
    createNewArticlePlan();
  }

  function createNewArticlePlan({ title = "", markdown = "", coverRatio = "2.35:1", inlineRatio = "4:3", styleId = "FA-001", layoutId = "IG-001", articleId = null } = {}) {
    if (articleId) return planUnifiedArticleDraft({ id: articleId, title, markdown, styleId, layoutId, coverRatio, inlineRatio });
    ensureArticleWorkspace();
    const md = (markdown || "").trim() || (title ? `# ${title}\n\n在这里输入正文内容…` : E.DEFAULT_STARTER_ARTICLE_MD);

    let skillNode = CS.graph.nodes.find((n) => n.type === "skill_params" || n.type === "skill");
    if (!skillNode) {
      skillNode = E.makeSkillParamsNode(64, 48, {
        style1: styleId || "FA-001",
        layout: layoutId || "IG-001"
      });
      CS.graph.nodes.push(skillNode);
    } else {
      if (styleId) skillNode.data.style1 = styleId;
      if (layoutId) skillNode.data.layout = layoutId;
    }

    let ctrlNode = CS.graph.nodes.find((n) => n.type === "output_control" && n.data?.mode === "article-illust");
    if (!ctrlNode) {
      ctrlNode = E.makeOutputControlNode(488, 176, {
        mode: "article-illust",
        coverRatio: coverRatio || "2.35:1",
        inlineRatio: inlineRatio || "4:3",
        status: "ready"
      });
      CS.graph.nodes.push(ctrlNode);
    } else {
      ctrlNode.data.coverRatio = coverRatio || ctrlNode.data.coverRatio || "2.35:1";
      ctrlNode.data.inlineRatio = inlineRatio || ctrlNode.data.inlineRatio || "4:3";
    }
    ensureEdge(skillNode.id, ctrlNode.id);

    const built = E.buildArticlePlanData(md, ctrlNode, CS.graph, Catalog);
    if (title) built.articleTitle = title;

    let planNode = getDownstreamArticlePlanNode(ctrlNode);
    if (!planNode) {
      planNode = E.makeArticlePlanNode(
        snapVal(ctrlNode.x + (ctrlNode.w || 344) + 96),
        snapVal(Math.max(48, ctrlNode.y - 12)),
        {
          status: "ready",
          articleId: articleId || null,
          sourceControlId: ctrlNode.id,
          articleTitle: built.articleTitle,
          markdown: built.markdown,
          cards: built.cards,
          updatedAt: "已生成方案"
        }
      );
      CS.graph.nodes.push(planNode);
      ensureEdge(ctrlNode.id, planNode.id);
    } else {
      if (articleId) planNode.data.articleId = articleId;
      planNode.data.articleTitle = built.articleTitle;
      planNode.data.markdown = built.markdown;
      planNode.data.cards = built.cards;
      planNode.data.updatedAt = "已生成方案";
    }

    syncArticlePlanDisplayNodes(planNode);
    const art = syncPlanNodeToMyArticles(planNode, { tabId: CS.activeTabId, bumpTime: true, hostGraph: CS.graph });
    if (art) {
      CS.activeArticleId = art.id;
      CS.activePlanNodeId = planNode.id;
    }
    markActiveTabDirty();
    persistOpenTabs();
    return planNode;
  }

  function renderArticleSidebarHtml(sortedArticles, activeArtId) {
    const latestTen = sortedArticles.slice(0, 10);
    return `
      <aside class="ic-pv-outline">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:0 2px;">
          <span style="font-size:13px;font-weight:850;color:var(--ic-ink);">📚 历史文章</span>
          <button type="button" class="btn btn-sm" id="pv-sidebar-new-btn" style="padding:2px 8px;font-size:11.5px;font-weight:800;">＋ 新建</button>
        </div>

        <div class="ic-hist-art-list" id="pv-hist-art-list">
          ${
            !latestTen.length
              ? `<div style="padding:24px 8px;text-align:center;font-size:12px;color:var(--ic-muted);">暂无历史文章</div>`
              : latestTen
                  .map((a) => {
                    const isCur = activeArtId && a.id === activeArtId;
                    const cards = sortPlanCardsInDocOrder(a.cards || []);
                    const readyCnt = cards.filter((c) => c.imageUrl).length;
                    const thumbUrl =
                      cards.find((c) => c.role === "cover" && c.imageUrl)?.imageUrl ||
                      cards.find((c) => c.imageUrl)?.imageUrl ||
                      "";
                    const genNow = isArticleGenerating(a);
                    return `
                      <div class="ic-hist-art-item ${isCur ? "is-active" : ""}" data-hist-art-id="${esc(a.id)}" title="${esc(a.articleTitle || "文章")}">
                        ${
                          thumbUrl
                            ? `<img class="ic-hist-art-thumb" data-hw-src="${esc(thumbUrl)}" alt="" />`
                            : `<div class="ic-hist-art-placeholder">📄</div>`
                        }
                        <div style="min-width:0;flex:1;">
                          <div style="font-size:12.2px;font-weight:800;color:var(--ic-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                            ${esc(a.articleTitle || "未命名文章")}
                          </div>
                          <div style="font-size:10.6px;margin-top:2px;display:flex;align-items:center;gap:5px;color:var(--ic-muted);">
                            ${
                              genNow
                                ? `<span style="color:var(--vermilion);font-weight:800;">⏳ 正在生图…</span>`
                                : `
                                  <span>${esc(a.timeLabel || formatArticleTimeLabel(a.updatedAtMs))}</span>
                                  <span>·</span>
                                  <span style="color:${readyCnt > 0 ? "#1f6f4a" : "var(--ic-muted)"};font-weight:750;">配图 ${readyCnt}/${cards.length}</span>
                                `
                            }
                          </div>
                        </div>
                        <button type="button" class="ic-hist-art-delete" data-sidebar-del-art-id="${esc(a.id)}" title="删除此历史文章" aria-label="删除文章：${esc(a.articleTitle || "未命名文章")}">🗑</button>
                      </div>
                    `;
                  })
                  .join("")
          }
        </div>

        <div class="ic-hist-art-foot">
          <button type="button" class="btn btn-sm" id="pv-view-all-articles" style="width:100%;justify-content:center;font-weight:850;font-size:11.5px;">
            📑 历史文章分页 (${sortedArticles.length})
          </button>
        </div>
      </aside>
    `;
  }

  function bindArticleSidebar(container, activeArtId) {
    const newBtn = container.querySelector("#pv-sidebar-new-btn");
    if (newBtn) {
      newBtn.onclick = () => {
        openUnifiedArticleEditor(null, { createNew: true });
      };
    }
    const allBtn = container.querySelector("#pv-view-all-articles");
    if (allBtn) {
      // The list lives on the author's own profile now; the editor keeps its sidebar.
      allBtn.onclick = () => {
        const who = (typeof S !== "undefined" && S.App && S.App.state && S.App.state.user && S.App.state.user.username) || "";
        if (who && typeof S.channelUrl === "function") {
          window.location.href = S.channelUrl("main", { view: "profile", user: who, ptab: "articles" });
        } else {
          openMyArticlesPage({ subView: "all-list" });
        }
      };
    }
    container.querySelectorAll("[data-sidebar-del-art-id]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const aid = btn.getAttribute("data-sidebar-del-art-id");
        if (aid) deleteArticle(aid);
      };
    });
    container.querySelectorAll("[data-hist-art-id]").forEach((rowEl) => {
      rowEl.onclick = () => {
        const aid = rowEl.getAttribute("data-hist-art-id");
        if (!aid) return;
        if (CS.articleEditorDraft && CS.articleEditorDraft.id === aid && !CS.articleEditorDraft.isNewDraft) return;
        openUnifiedArticleEditor(aid);
        const sc = DOM.previewStage.querySelector(".ic-pv-main-scroll");
        if (sc) sc.scrollTop = 0;
      };
    });
  }

  function syncArticleEditorDraftToHistory(draft, { bumpTime = false } = {}) {
    if (!draft) return null;
    ensureMyArticlesInitialized();
    const targetId = draft.id || null;
    let targetArt = targetId ? (CS.myArticles || []).find((a) => a.id === targetId) : null;
    const now = Date.now();

    const title = (draft.title || "").trim();
    const md = draft.markdown || "";

    if (!targetArt && !title && !md) {
      return null;
    }

    if (!targetArt) {
      const newId = targetId || E.uid("art");
      draft.id = newId;
      draft.isNewDraft = false;
      targetArt = {
        id: newId,
        title: title || "未命名文章",
        articleTitle: title || "未命名文章",
        markdown: md,
        cards: [],
        status: "ready",
        createdAtMs: now,
        updatedAtMs: now,
        timeLabel: formatArticleTimeLabel(now),
        linkedTabId: null,
        linkedPlanNodeId: null,
        style1: draft.styleId || "FA-001",
        layout: "IG-001",
        coverRatio: draft.coverRatio || "2.35:1",
        inlineRatio: draft.inlineRatio || "4:3",
        runCount: 0
      };
      CS.myArticles.unshift(targetArt);
      CS.activeArticleId = newId;
    } else {
      targetArt.title = title || targetArt.title || targetArt.articleTitle || "未命名文章";
      targetArt.articleTitle = title || targetArt.articleTitle || targetArt.title || "未命名文章";
      targetArt.markdown = md;
      if (Array.isArray(draft.cards)) {
        targetArt.cards = draft.cards;
      }
      targetArt.style1 = draft.styleId || targetArt.style1 || "FA-001";
      targetArt.coverRatio = draft.coverRatio || targetArt.coverRatio || "2.35:1";
      targetArt.inlineRatio = draft.inlineRatio || targetArt.inlineRatio || "4:3";
      if (bumpTime) {
        targetArt.updatedAtMs = now;
        targetArt.timeLabel = formatArticleTimeLabel(now);
      }
      draft.isNewDraft = false;
    }

    // Saving the current document never writes into a canvas or rebuilds slots.
    persistMyArticles();
    return targetArt;
  }

  function restoreArticleConflictBackup() {
    const saved = readJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, null);
    const items = Array.isArray(saved?.articles) ? saved.articles.filter(a => a && a.id) : [];
    if (!items.length) { toast("暂无需要恢复的本地文章备份"); return; }
    S.openModal({
      title: "恢复本地文章备份",
      sizeClass: "modal-medium",
      html: `<div style="display:flex;flex-direction:column;gap:10px;">
        <p style="font-size:13px;line-height:1.65;">以下是云端版本冲突或离线编辑时保留的文章。选择一篇作为新文章恢复，原云端文章不会被覆盖。</p>
        ${items.map((a,i) => `<button type="button" class="btn" data-restore-conflict="${i}"
          style="text-align:left;white-space:normal;padding:12px;">
          ${esc(a.articleTitle || a.title || "未命名文章")} · ${String(a.markdown || "").length} 字符</button>`).join("")}
        <button type="button" class="btn" id="art-conflict-close">稍后处理</button>
      </div>`,
      onMount(root) {
        root.querySelector("#art-conflict-close").onclick = () => S.closeModal();
        root.querySelectorAll("[data-restore-conflict]").forEach(button => {
          button.onclick = () => {
            const index = Number(button.getAttribute("data-restore-conflict"));
            const source = items[index];
            if (!source) return;
            ensureMyArticlesInitialized();
            const copy = JSON.parse(JSON.stringify(source));
            copy.id = E.uid("art");
            copy.articleTitle = (copy.articleTitle || copy.title || "未命名文章") + " · 恢复副本";
            copy.title = copy.articleTitle;
            copy.linkedTabId = null;
            copy.linkedPlanNodeId = null;
            copy.isNewDraft = false;
            copy.createdAtMs = Date.now();
            copy.updatedAtMs = Date.now();
            CS.myArticles.unshift(copy);
            const remaining = items.filter((a) => a.id !== source.id);
            writeJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, remaining.length ? {
              createdAt: Date.now(), articles: remaining, activeId: remaining[0].id
            } : null);
            _articlesCloudConflict = remaining.length > 0;
            S.closeModal();
            persistMyArticles();
            openUnifiedArticleEditor(copy.id, {renderNow:true});
            toast("已恢复为独立新文章，原云端文章保持不变");
          };
        });
      }
    });
  }

  function renderArticlePortalPage(sortedArticles) {
    DOM.previewStage.innerHTML = `
      <div class="ic-pv-topbar">
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="font-size:13.5px;font-weight:850;color:var(--ic-ink);">📰 文章模式</span>
          <span style="font-size:12px;color:var(--ic-muted);">为文章智能配置插图与封面图</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <button type="button" class="btn btn-sm" id="portal-back-canvas" style="font-weight:750;">返回画布 ↗</button>
        </div>
      </div>

      <div class="ic-pv-body">
        ${renderArticleSidebarHtml(sortedArticles, null)}

        <div class="ic-pv-main-scroll" style="display:flex;align-items:center;justify-content:center;">
          <div style="max-width:820px;width:100%;padding:40px 24px;">
            ${readJsonStorage(ARTICLE_CONFLICT_BACKUP_KEY, null)?.articles?.length
              ? '<div class="hw-article-conflict-reminder" role="status">发现尚未恢复的本地文章备份。<button type="button" id="portal-restore-conflicts" class="btn btn-sm">查看并恢复</button></div>' : ""}
            <div style="text-align:center;margin-bottom:38px;">
              <div style="font-size:44px;margin-bottom:12px;">📰</div>
              <h1 style="font-size:24px;font-weight:850;color:var(--ic-ink);margin:0 0 10px;">文章模式：为文章配置插图与封面图</h1>
              <p style="font-size:13.5px;color:var(--ic-muted);margin:0;line-height:1.68;">
                支持上传文档由 AI 自动解析标题与正文结构，或直接在编辑器中撰写，一键生成微信公众号超宽封面与各章节生动手绘插图。
              </p>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;">
              <!-- Action 1: 上传文章 -->
              <div class="ic-art-portal-card" id="portal-card-upload" style="border:2px dashed var(--ic-border-strong);border-radius:16px;padding:36px 20px;text-align:center;cursor:pointer;background:var(--ic-panel-solid);transition:all 0.2s;" title="点击上传文档">
                <div style="font-size:40px;margin-bottom:12px;">📁</div>
                <div style="font-size:18px;font-weight:850;color:var(--ic-ink);margin-bottom:8px;">上传文章</div>
                <div style="font-size:12.5px;color:var(--ic-muted);line-height:1.6;margin-bottom:18px;">
                  支持 <strong>.md / .doc / .docx / .txt / .pdf</strong> 格式<br/>
                  服务端 AI 自动提取标题与标准 Markdown 正文
                </div>
                <button type="button" class="btn btn-primary" id="portal-btn-upload-file" style="font-weight:800;padding:8px 24px;">选择文件上传</button>
                <input type="file" id="portal-file-input" accept=".md,.markdown,.txt,.doc,.docx,.pdf" hidden />
              </div>

              <!-- Action 2: 新建文章 -->
              <div class="ic-art-portal-card" id="portal-card-new" style="border:1px solid var(--ic-border);border-radius:16px;padding:36px 20px;text-align:center;cursor:pointer;background:var(--ic-panel-solid);transition:all 0.2s;" title="进入 Markdown 编辑器">
                <div style="font-size:40px;margin-bottom:12px;">✍️</div>
                <div style="font-size:18px;font-weight:850;color:var(--ic-ink);margin-bottom:8px;">新建文章</div>
                <div style="font-size:12.5px;color:var(--ic-muted);line-height:1.6;margin-bottom:18px;">
                  直接进入 Markdown 编辑器<br/>
                  自由撰写或粘贴正文内容，随时调整各章节
                </div>
                <button type="button" class="btn" id="portal-btn-new-direct" style="font-weight:800;padding:8px 24px;">进入编辑器撰写</button>
              </div>
            </div>

            <div id="portal-upload-loading" style="display:none;text-align:center;padding:28px;background:var(--ic-panel-solid);border-radius:14px;border:1px solid var(--ic-border);">
              <div style="font-size:32px;margin-bottom:10px;">⏳</div>
              <div style="font-size:15px;font-weight:800;color:var(--vermilion);margin-bottom:6px;">正在由 AI 智能解析文档结构…</div>
              <div style="font-size:12.5px;color:var(--ic-muted);">正在提取文章标题、清洗噪点并排版为标准 Markdown，请稍候</div>
            </div>
          </div>
        </div>
      </div>
    `;

    bindArticleSidebar(DOM.previewStage, null);

    const backBtn = DOM.previewStage.querySelector("#portal-back-canvas");
    if (backBtn) backBtn.onclick = () => switchCreationStage("canvas");
    DOM.previewStage.querySelector("#portal-restore-conflicts")?.addEventListener("click", restoreArticleConflictBackup);

    const fileInput = DOM.previewStage.querySelector("#portal-file-input");
    const uploadCard = DOM.previewStage.querySelector("#portal-card-upload");
    const uploadBtn = DOM.previewStage.querySelector("#portal-btn-upload-file");
    const newCard = DOM.previewStage.querySelector("#portal-card-new");
    const newBtn = DOM.previewStage.querySelector("#portal-btn-new-direct");
    const loadingBox = DOM.previewStage.querySelector("#portal-upload-loading");

    if (uploadBtn && fileInput) uploadBtn.onclick = (e) => { e.stopPropagation(); fileInput.click(); };
    if (uploadCard && fileInput) uploadCard.onclick = () => fileInput.click();

    if (fileInput) {
      fileInput.onchange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        fileInput.value = "";
        if (loadingBox) loadingBox.style.display = "none";
        fileInput.disabled = true;
        const reader = new FileReader();
        reader.onerror = () => { fileInput.disabled = false; toast("文件读取失败，请重新选择"); };
        reader.onabort = () => { fileInput.disabled = false; };

        reader.onload = async (evt) => {
          const dataUrl = evt.target.result;
          try {
            // Import directly into a new editor without a review/approval step.
            // A completed task remains recoverable if the user navigated away.
            const res = await window.HandrawTaskJourney.submitImport(file.name, dataUrl, async () => false);
            if (!DOM.previewStage?.querySelector("#portal-file-input")) return;
            fileInput.disabled = false;

            ensureMyArticlesInitialized();
            const now = Date.now();
            const artId = E.uid("art");
            const parsedTitle = (res.title || file.name.replace(/\.[^.]+$/, "") || "未命名文章").trim();
            const parsedMd = res.markdown || "";

            let cards = [];
            try {
              const dummyCtrl = {
                data: {
                  coverRatio: "2.35:1",
                  inlineRatio: "4:3",
                  mode: "article-illust"
                }
              };
              const built = E.buildArticlePlanData(parsedMd, dummyCtrl, CS.graph, Catalog);
              cards = built.cards || [];
            } catch (_) {}

            const newArt = {
              id: artId,
              articleTitle: parsedTitle,
              markdown: parsedMd,
              cards: cards,
              status: "ready",
              createdAtMs: now,
              updatedAtMs: now,
              timeLabel: formatArticleTimeLabel(now),
              linkedTabId: null,
              linkedPlanNodeId: null,
              style1: "FA-001",
              layout: "IG-001",
              coverRatio: "2.35:1",
              inlineRatio: "4:3",
              runCount: 0
            };
            CS.myArticles.unshift(newArt);
            persistMyArticles();
            CS.activeArticleId = artId;

            CS.articleEditorDraft = {
              id: artId,
              title: parsedTitle,
              markdown: parsedMd,
              styleId: "FA-001",
              coverRatio: "2.35:1",
              inlineRatio: "4:3"
            };
            CS.articleSubView = "editor";

            const url = new URL(window.location.href);
            url.searchParams.set("entry", "article");
            url.searchParams.set("articleId", artId);
            url.searchParams.set("subview", "editor");
            window.history.replaceState(null, "", url.pathname + url.search);

            renderFullPreviewStage();
            window.HandrawTaskJourney.acknowledgeImport();
            let succMsg = (res.aiUsed === "all" || res.aiUsed === true) ? "已用 AI 整理为 Markdown" : res.aiUsed === "partial" ? "部分段落 AI 整理失败，已保留原文，请检查结果" : "AI 不可用，已按原文导入，请检查标题和排版";
            if (res.truncated) succMsg += "（正文过长，已截断）";
            toast(succMsg);
          } catch (err) {
            fileInput.disabled = false;
            if (err.status === 401 || err.code === "login_required") {
              toast("请先登录后再导入文档");
              if (typeof S.openLoginModal === "function") {
                S.openLoginModal("请先登录后再导入文档");
              }
            } else {
              toast("解析文档失败：" + (err.message || "请检查文件格式"));
              console.error("[Article Parse Error]", err);
            }
          }
        };
        reader.readAsDataURL(file);
      };
    }

    const startNewEditor = () => {
      ensureMyArticlesInitialized();
      const now = Date.now();
      const artId = E.uid("art");
      const newArt = {
        id: artId,
        articleTitle: "未命名文章",
        markdown: "",
        cards: [],
        status: "ready",
        createdAtMs: now,
        updatedAtMs: now,
        timeLabel: formatArticleTimeLabel(now),
        linkedTabId: null,
        linkedPlanNodeId: null,
        style1: "FA-001",
        layout: "IG-001",
        coverRatio: "2.35:1",
        inlineRatio: "4:3",
        runCount: 0
      };
      CS.myArticles.unshift(newArt);
      persistMyArticles();
      CS.activeArticleId = artId;

      CS.articleEditorDraft = {
        id: artId,
        title: "",
        markdown: "",
        styleId: "FA-001",
        coverRatio: "2.35:1",
        inlineRatio: "4:3"
      };
      CS.articleSubView = "editor";

      const url = new URL(window.location.href);
      url.searchParams.set("entry", "article");
      url.searchParams.set("articleId", artId);
      url.searchParams.set("subview", "editor");
      window.history.replaceState(null, "", url.pathname + url.search);

      renderFullPreviewStage();
    };

    if (newBtn) newBtn.onclick = (e) => { e.stopPropagation(); startNewEditor(); };
    if (newCard) newCard.onclick = () => startNewEditor();
  }

  function parseCardRatioNumbers(ratioStr) {
    const s = String(ratioStr || "").trim();
    if (s === "2.35:1") return { rw: 2.35, rh: 1 };
    if (s === "16:9") return { rw: 16, rh: 9 };
    if (s === "4:3") return { rw: 4, rh: 3 };
    if (s === "3:4") return { rw: 3, rh: 4 };
    if (s === "1:1") return { rw: 1, rh: 1 };
    const parts = s.split(":");
    if (parts.length === 2) {
      const w = parseFloat(parts[0]);
      const h = parseFloat(parts[1]);
      if (w > 0 && h > 0) return { rw: w, rh: h };
    }
    return { rw: 4, rh: 3 };
  }

  function renderWeChatArticlePreviewHtml(draft, styleObj, isMobile = false, options = {}) {
    const rawMd = draft.markdown || "";
    const title = (draft.title || draft.articleTitle || "").trim() || "未命名文章";
    const today = new Date().toISOString().slice(0, 10);
    const targetCards = options.cards || resolveArticleTarget(draft.id)?.planNode?.data?.cards || draft.cards || [];
    const cards = sortPlanCardsInDocOrder(targetCards);

    function renderInline(text) {
      if (!text) return "";
      let s = esc(text);

      // Images: ![alt](url)
      s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
        return `<div style="text-align:center;margin:18px 0;"><img src="${url}" alt="${alt}" style="max-width:100%;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.08);" />${alt ? `<div style="font-size:12px;color:#888;margin-top:5px;">${alt}</div>` : ""}</div>`;
      });

      // Links: [text](url)
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:#576b95;text-decoration:none;border-bottom:1px solid #576b95;">$1</a>');

      // Bold + Italic: ***text*** or ___text___
      s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
      s = s.replace(/___([^_]+)___/g, '<strong><em>$1</em></strong>');

      // Bold: **text** or __text__ (handles **AI 头像：** perfectly)
      s = s.replace(/\*\*([^*]+)\*\*/g, '<strong style="font-weight:850;color:#111;">$1</strong>');
      s = s.replace(/__([^_]+)__/g, '<strong style="font-weight:850;color:#111;">$1</strong>');

      // Italic: *text* or _text_
      s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      s = s.replace(/_([^_]+)_/g, '<em>$1</em>');

      // Strikethrough: ~~text~~
      s = s.replace(/~~([^~]+)~~/g, '<del style="color:#999;">$1</del>');

      // Inline Code: `code`
      s = s.replace(/`([^`]+)`/g, '<code style="background:#f0f2f5;color:#d63384;padding:2px 6px;border-radius:4px;font-family:var(--font-mono,monospace);font-size:13px;border:1px solid #e1e4e8;">$1</code>');

      return s;
    }

    function parseMarkdownBlocks(md, { skipTitleH1 = false } = {}) {
      if (!md) return `<div style="padding:48px 16px;text-align:center;color:var(--ic-muted,#999);">暂无正文内容，请切换到编写模式输入文字</div>`;

      const lines = md.split(/\r?\n/);
      const out = [];
      let i = 0;

      while (i < lines.length) {
        const line = lines[i];

        if (!line.trim()) {
          i++;
          continue;
        }

        // 1. Fenced Code Block (```lang ... ```)
        if (line.trim().startsWith("```")) {
          const codeLines = [];
          i++;
          while (i < lines.length && !lines[i].trim().startsWith("```")) {
            codeLines.push(lines[i]);
            i++;
          }
          if (i < lines.length) i++; // skip closing ```
          const codeText = esc(codeLines.join("\n"));
          out.push(`
            <pre style="margin:16px 0;padding:14px 16px;border-radius:8px;background:#2d3035;color:#f8f8f2;font-family:var(--font-mono,monospace);font-size:12.8px;line-height:1.6;overflow-x:auto;"><code>${codeText}</code></pre>
          `);
          continue;
        }

        // 2. Table parsing (| col1 | col2 |)
        if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*[-:]+[-| :]*\|?\s*$/.test(lines[i + 1])) {
          const headerLine = line;
          const sepLine = lines[i + 1];
          i += 2;

          const parseCells = (row) => {
            let trimmed = row.trim();
            if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
            if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
            return trimmed.split("|").map((c) => c.trim());
          };

          const headers = parseCells(headerLine);
          const seps = parseCells(sepLine);
          const aligns = seps.map((s) => {
            const left = s.startsWith(":");
            const right = s.endsWith(":");
            if (left && right) return "center";
            if (right) return "right";
            return "left";
          });

          const bodyRows = [];
          while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
            bodyRows.push(parseCells(lines[i]));
            i++;
          }

          let tableHtml = `<div style="overflow-x:auto;margin:20px 0;border-radius:8px;border:1px solid #e7e7e7;box-shadow:0 1px 3px rgba(0,0,0,0.03);">`;
          tableHtml += `<table style="width:100%;border-collapse:collapse;font-size:13.5px;color:#333;text-align:left;background:#ffffff;">`;
          tableHtml += `<thead><tr style="background:#f6f8fa;border-bottom:2px solid #dee2e6;">`;
          headers.forEach((h, idx) => {
            const a = aligns[idx] || "left";
            tableHtml += `<th style="padding:10px 14px;font-weight:850;color:#222;text-align:${a};border-right:1px solid #e9ecef;">${renderInline(h)}</th>`;
          });
          tableHtml += `</tr></thead><tbody>`;

          bodyRows.forEach((row, rIdx) => {
            const bg = rIdx % 2 === 1 ? "#fafbfc" : "#ffffff";
            tableHtml += `<tr style="background:${bg};border-bottom:1px solid #e9ecef;">`;
            headers.forEach((_, cIdx) => {
              const val = row[cIdx] || "";
              const a = aligns[cIdx] || "left";
              tableHtml += `<td style="padding:9px 14px;text-align:${a};border-right:1px solid #e9ecef;line-height:1.6;">${renderInline(val)}</td>`;
            });
            tableHtml += `</tr>`;
          });
          tableHtml += `</tbody></table></div>`;
          out.push(tableHtml);
          continue;
        }

        // 3. Headings (# H1, ## H2, ### H3, #### H4)
        const hMatch = line.match(/^(#{1,6})\s+(.*)$/);
        if (hMatch) {
          const level = hMatch[1].length;
          const hText = hMatch[2];
          // Skip first H1 if requested or if it duplicates the article title
          if (level === 1 && (skipTitleH1 || (out.length === 0 && hText.trim() === title.trim()))) {
            i++;
            continue;
          }
          if (level === 1) {
            out.push(`<h2 style="font-size:20px;font-weight:850;color:#222;margin:28px 0 12px;line-height:1.42;">${renderInline(hText)}</h2>`);
          } else if (level === 2) {
            out.push(`
              <h3 style="font-size:18px;font-weight:850;color:#222;margin:30px 0 14px;padding-left:11px;border-left:4px solid #07c160;line-height:1.45;">
                <span>${renderInline(hText)}</span>
              </h3>
            `);
          } else if (level === 3) {
            out.push(`<h4 style="font-size:16.5px;font-weight:800;color:#222;margin:22px 0 10px;line-height:1.45;">${renderInline(hText)}</h4>`);
          } else {
            out.push(`<h5 style="font-size:15px;font-weight:800;color:#333;margin:18px 0 8px;line-height:1.45;">${renderInline(hText)}</h5>`);
          }
          i++;
          continue;
        }

        // 4. Horizontal Rule (---, ***, ___)
        if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
          out.push(`<hr style="border:none;border-top:1px dashed #dcdcdc;margin:26px 0;" />`);
          i++;
          continue;
        }

        // 5. Blockquote (> ...)
        if (line.trim().startsWith(">")) {
          const bqLines = [];
          while (i < lines.length && lines[i].trim().startsWith(">")) {
            bqLines.push(lines[i].replace(/^>\s*/, ""));
            i++;
          }
          const bqContent = bqLines.join("\n").trim();

          // Check if it is an AI Illustration Slot Tag
          if (bqContent.includes("插图位建议") || bqContent.includes("🖼️") || bqContent.includes("配图")) {
            const cleanDesc = bqContent.replace(/^[>🖼️\s【插图位建议：】]+/, "").replace(/[】\s]+$/, "").trim() || bqContent;
            out.push(`
              <div style="border:2px dashed #07c160;border-radius:10px;padding:16px 18px;background:#fbfdfc;margin:22px 0;">
                <div style="display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:850;color:#07c160;margin-bottom:6px;">
                  <span>🖼️ AI 章节规划插图位</span>
                  <span style="font-size:11px;background:#eaf8f0;padding:2px 7px;border-radius:4px;font-weight:750;">画幅 ${esc(draft.inlineRatio || "4:3")}</span>
                  ${styleObj?.id ? `<span style="font-size:11px;background:#eaf8f0;padding:2px 7px;border-radius:4px;font-weight:750;">#${esc(styleObj.id)}</span>` : ""}
                </div>
                <div style="font-size:13.5px;color:#444;line-height:1.68;">${renderInline(cleanDesc)}</div>
              </div>
            `);
          } else {
            out.push(`
              <blockquote style="margin:16px 0;padding:12px 16px;background:#f8f9fa;border-left:3.5px solid #07c160;border-radius:0 6px 6px 0;color:#555;font-size:14px;line-height:1.75;">
                ${renderInline(bqContent).replace(/\n/g, "<br/>")}
              </blockquote>
            `);
          }
          continue;
        }

        // 6. Unordered List (- , * , + )
        if (/^\s*[-*+]\s+/.test(line)) {
          const listItems = [];
          while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
            listItems.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
            i++;
          }
          const lisHtml = listItems
            .map((item) => `<li style="margin-bottom:6px;">${renderInline(item)}</li>`)
            .join("");
          out.push(`<ul style="margin:12px 0 12px 20px;font-size:15px;line-height:1.8;color:#333;padding-left:14px;">${lisHtml}</ul>`);
          continue;
        }

        // 7. Ordered List (1. , 2. )
        if (/^\s*\d+\.\s+/.test(line)) {
          const listItems = [];
          while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
            listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
            i++;
          }
          const lisHtml = listItems
            .map((item) => `<li style="margin-bottom:6px;">${renderInline(item)}</li>`)
            .join("");
          out.push(`<ol style="margin:12px 0 12px 20px;font-size:15px;line-height:1.8;color:#333;padding-left:14px;">${lisHtml}</ol>`);
          continue;
        }

        // 8. Paragraph
        const pLines = [line];
        i++;
        while (
          i < lines.length &&
          lines[i].trim() &&
          !lines[i].trim().startsWith("```") &&
          !lines[i].trim().startsWith("#") &&
          !lines[i].trim().startsWith(">") &&
          !/^\s*[-*+]\s+/.test(lines[i]) &&
          !/^\s*\d+\.\s+/.test(lines[i]) &&
          !/^(\*{3,}|-{3,}|_{3,})$/.test(lines[i].trim()) &&
          !(lines[i].includes("|") && i + 1 < lines.length && /^\s*\|?\s*[-:]+[-| :]*\|?\s*$/.test(lines[i + 1]))
        ) {
          pLines.push(lines[i]);
          i++;
        }

        const pText = pLines.map((pl) => renderInline(pl)).join("<br/>");
        out.push(`<p style="font-size:15.5px;line-height:1.88;margin:14px 0;color:#333;text-align:justify;letter-spacing:0.02em;">${pText}</p>`);
      }

      return out.join("\n");
    }

    function renderPreviewFigureHtml(card, role, inlineNo) {
      const isCover = role === "cover";
      const status = card.status || "idle";
      const ratio = card.ratio || (isCover ? "2.35:1" : "4:3");
      const { rw, rh } = parseCardRatioNumbers(ratio);
      const roleLabel = isCover ? "封面" : `插图 ${inlineNo}`;
      const statusLabel =
        status === "done"
          ? "已完成"
          : status === "generating"
            ? `${roleLabel} · 生成中`
            : status === "error"
              ? `${roleLabel} · 生成失败`
              : `${roleLabel} · 待生成`;

      if (card.imageUrl) {
        return `
          <figure class="ic-wechat-figure" data-card-id="${esc(card.id)}" data-role="${esc(role)}" style="margin:18px 0;width:100%;text-align:center;">
            <img src="${esc(card.imageUrl)}" alt="${esc(card.title || roleLabel)}" class="hw-editor-body-img" loading="lazy" style="border-radius:6px;" />
          </figure>
        `;
      }

      return `
        <figure class="ic-wechat-figure is-pending" data-status="${esc(status)}" data-card-id="${esc(card.id)}" data-role="${esc(role)}" style="margin:18px 0;width:100%;aspect-ratio:calc(var(--r-w, ${rw})/var(--r-h, ${rh}));border:1.5px dashed var(--line-strong, #cbbfae);border-radius:6px;background:var(--paper-inset, #f3eee6);display:flex;flex-direction:column;align-items:center;justify-content:center;box-sizing:border-box;padding:12px;text-align:center;">
          <div style="font-size:13px;font-weight:700;color:var(--ink-strong,#1f1b16);">${esc(statusLabel)}</div>
          ${card.subject ? `<div style="font-size:12px;color:var(--ink-muted,#766d62);margin-top:4px;max-width:90%;">${esc(card.subject.slice(0, 40))}</div>` : ""}
        </figure>
      `;
    }

    let coverFigureHtml = "";
    let bodyHtml = "";

    if (!cards.length) {
      bodyHtml = parseMarkdownBlocks(rawMd.trim());
    } else {
      const coverCard = cards.find((c) => c.role === "cover");
      const inlineCards = cards.filter((c) => c.role !== "cover");
      if (coverCard) {
        coverFigureHtml = renderPreviewFigureHtml(coverCard, "cover", 0);
      }

      const blocks = E.parseArticleReadonlyBlocks(rawMd, { withLines: true, noStarter: true });
      const lines = rawMd.split(/\r?\n/);
      const firstH1Idx = blocks.find((b) => b.kind === "h1")?.idx ?? -1;
      const maxBlockIdx = blocks.length > 0 ? blocks[blocks.length - 1].idx : 0;

      const cardsByBlock = new Map();
      const overflowCards = [];
      inlineCards.forEach((c) => {
        const rawIdx = typeof c.afterBlockIdx === "number" ? c.afterBlockIdx : 0;
        if (blocks.length > 0 && rawIdx > maxBlockIdx) {
          overflowCards.push(c);
        } else {
          if (!cardsByBlock.has(rawIdx)) cardsByBlock.set(rawIdx, []);
          cardsByBlock.get(rawIdx).push(c);
        }
      });

      const bodyParts = [];
      blocks.forEach((b) => {
        const blkText = lines.slice(b.startLine, b.endLine + 1).join("\n");
        const blkHtml = parseMarkdownBlocks(blkText, { skipTitleH1: b.idx === firstH1Idx });
        if (blkHtml) bodyParts.push(blkHtml);

        const cardsHere = cardsByBlock.get(b.idx) || [];
        cardsHere.forEach((c) => {
          bodyParts.push(renderPreviewFigureHtml(c, "inline", inlineCards.indexOf(c) + 1));
        });
      });

      overflowCards.forEach((c) => {
        bodyParts.push(renderPreviewFigureHtml(c, "inline", inlineCards.indexOf(c) + 1));
      });

      bodyHtml = bodyParts.join("\n");
    }

    return `
      <div class="ic-wechat-preview-wrap ${isMobile ? "is-mobile-vp" : "is-desktop-vp"}">
        ${
          isMobile
            ? `
          <div class="ic-wechat-phone-notch">
            <span style="font-size:11px;font-weight:800;">9:41</span>
            <span style="font-size:11px;">5G ▮▮▮ 100%</span>
          </div>
        `
            : ""
        }

        <!-- Article Title -->
        <h1 style="font-size:${isMobile ? "21px" : "25px"};font-weight:850;line-height:1.42;color:#222;margin:0 0 12px;">
          ${esc(title)}
        </h1>

        <!-- Metadata Line -->
        <div class="ic-wechat-preview-meta" style="display:flex;align-items:center;gap:10px;font-size:12.5px;color:#888;margin-bottom:18px;flex-wrap:wrap;">
          <span style="color:#576b95;font-weight:750;">手绘风格社区</span>
          <span>${today}</span>
          <span style="background:#f2f2f2;color:#666;font-size:11px;padding:1px 6px;border-radius:3px;">原创</span>
        </div>

        ${coverFigureHtml}

        <!-- Selected Style Banner Badge -->
        <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;background:#f4f9f5;border-radius:8px;border:1px solid #d1ead7;margin-bottom:22px;">
          <img src="${esc(styleObj.image || '')}" style="width:40px;height:40px;border-radius:6px;object-fit:cover;border:1px solid #c2e2ca;flex-shrink:0;" alt="" onerror="this.style.display='none'" />
          <div style="flex:1;min-width:0;">
            <div style="font-size:12.5px;font-weight:850;color:#1f6f4a;display:flex;align-items:center;gap:6px;">
              <span>配图画风：#${esc(styleObj.id)} · ${esc(styleObj.name)}</span>
            </div>
            <div style="font-size:11.5px;color:#666;margin-top:2px;">
              封面画幅：<strong>${esc(draft.coverRatio)}</strong> · 章节插图：<strong>${esc(draft.inlineRatio)}</strong>
            </div>
          </div>
        </div>

        <div style="border-bottom:1px solid #eee;margin-bottom:20px;"></div>

        <!-- Body Content -->
        <div class="ic-wechat-preview-body" style="min-height:360px;">
          ${bodyHtml}
        </div>

        <!-- WeChat Reader Footer -->
        <div style="margin-top:36px;padding-top:18px;border-top:1px solid #f0f0f0;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:#8c8c8c;">
          <span>阅读 10万+</span>
          <div style="display:flex;align-items:center;gap:16px;">
            <span>在看 248</span>
            <span>👍 860</span>
            <span>分享</span>
          </div>
        </div>
      </div>
    `;
  }

  function flushUnifiedArticleEditor() {
    const fn = CS.articleEditorFlush;
    if (typeof fn !== "function") return;
    try {
      fn();
    } catch (err) {
      try { console.warn("[article-editor] flush failed", err); } catch (_) {}
    } finally {
      if (CS.articleEditorFlush === fn) CS.articleEditorFlush = null;
    }
  }

  function clearUnifiedArticleEditorFlush() {
    CS.articleEditorFlush = null;
  }

  function makeBlankArticleDraft() {
    return {
      id: E.uid("art"),
      title: "",
      markdown: "",
      cards: [],
      styleId: "FA-001",
      coverRatio: "2.35:1",
      inlineRatio: "4:3",
      isNewDraft: true
    };
  }

  function draftFromArticle(art) {
    return {
      id: art.id,
      title: art.articleTitle || art.title || "",
      titleSource: art.titleSource || (art.articleTitle ? "manual" : "auto"),
      markdown: art.markdown || "",
      cards: Array.isArray(art.cards) ? JSON.parse(JSON.stringify(art.cards)) : [],
      styleId: art.style1 || art.styleId || "FA-001",
      coverRatio: art.coverRatio || "2.35:1",
      inlineRatio: art.inlineRatio || "4:3",
      isNewDraft: false
    };
  }

  function findArticleById(articleId) {
    return (CS.myArticles || []).find((a) => a.id === articleId) || null;
  }

  function openUnifiedArticleEditor(articleId = null, { createNew = false, renderNow = true } = {}) {
    const openSerial=++_articleOpenSerial;
    flushUnifiedArticleEditor();
    if (!createNew) syncAllTabsArticlesIntoStore();
    ensureMyArticlesInitialized();

    let draft = null;
    if (createNew) {
      CS.activeArticleId = null;
      CS.activePlanNodeId = null;
      draft = makeBlankArticleDraft();
    } else {
      let art = null;
      if (articleId) {
        art = findArticleById(articleId);
      }
      if (!art && !articleId) {
        const currentDraft = CS.articleEditorDraft;
        if (currentDraft && currentDraft.id) art = findArticleById(currentDraft.id);
      }
      if (!art && !articleId && CS.activeArticleId) {
        art = findArticleById(CS.activeArticleId);
      }
      if (!art && !articleId) {
        const sorted = getSortedMyArticles();
        art = sorted.length ? sorted[0] : null;
      }
      if (art) {
        if(art._summary) {
          const epoch=cacheScopeEpoch,scope=activeCacheScope;
          void loadArticleDocument(art.id).then(loaded=>{
            if(loaded&&!isStaleScope(epoch,scope)&&openSerial===_articleOpenSerial) openUnifiedArticleEditor(art.id,{createNew:false,renderNow});
          }).catch(error=>toast(error.message||"文章加载失败，请重试"));
          return;
        }

        CS.activeArticleId = art.id;
        CS.activePlanNodeId = art.linkedPlanNodeId || null;
        draft = draftFromArticle(art);
      }
    }

    if (!draft) {
      CS.activePlanNodeId = null;
      draft = makeBlankArticleDraft();
    }

    CS.articleEditorDraft = draft;
    CS.previewTab = "article";
    CS.stageView = "preview";
    CS.articleSubView = "editor";

    const url = new URL(window.location.href);
    url.searchParams.set("entry", "article");
    if (draft.id && !draft.isNewDraft) {
      url.searchParams.set("articleId", draft.id);
    } else {
      url.searchParams.delete("articleId");
    }
    url.searchParams.set("subview", "editor");
    url.searchParams.delete("view");
    window.history.replaceState(null, "", url.pathname + url.search);

    if (renderNow) renderFullPreviewStage();
    return draft;
  }

  function planUnifiedArticleDraft(draft, { aiCards = null } = {}) {
    const {
      id: articleId = null,
      title = "",
      markdown = "",
      styleId = "FA-001",
      layoutId = "IG-001",
      coverRatio = "2.35:1",
      inlineRatio = "4:3"
    } = draft || {};
    if (!articleId) return null;

    syncArticleEditorDraftToHistory(draft, { bumpTime: true });

    const target = typeof resolveArticleTarget === "function"
      ? resolveArticleTarget(articleId)
      : null;
    if (!target) return null;
    if (isArticleGenerating(target.planNode?.data || target.art)) return target.planNode || null;

    const md = (markdown || "").trim() ||
      (title ? `# ${title}\n\n在这里输入正文内容…` : E.DEFAULT_STARTER_ARTICLE_MD);

    let matchedCards;
    let builtArticleTitle = title;
    let builtMarkdown = md;

    if (Array.isArray(aiCards)) {
      matchedCards = aiCards;
      builtArticleTitle = title || (draft.title || "");
      builtMarkdown = draft.markdown || md;
    } else {
      const built = E.buildArticleDocument(md, {
        styleId, layoutId, coverRatio, inlineRatio
      }, Catalog);
      if (title) built.articleTitle = title;
      builtArticleTitle = built.articleTitle;
      builtMarkdown = built.markdown;

      matchedCards = E.reconcileArticlePlan(built.cards, target.art?.cards).cards;
    }

    const planNode = target.planNode;
    if (planNode) {
      planNode.data = planNode.data || {};
      planNode.data.articleTitle = builtArticleTitle;
      planNode.data.articleTitleSource = draft?.titleSource || (builtArticleTitle ? "manual" : "auto");
      planNode.data.markdown = builtMarkdown;
      planNode.data.cards = matchedCards;
      planNode.data.updatedAt = "已生成方案";
    }

    const art = target.art || null;
    if (art) {
      art.articleTitle = builtArticleTitle;
      art.titleSource = draft?.titleSource || (builtArticleTitle ? "manual" : "auto");
      art.style1 = styleId || art.style1 || "FA-001";
      art.coverRatio = coverRatio || art.coverRatio || "2.35:1";
      art.inlineRatio = inlineRatio || art.inlineRatio || "4:3";
      art.cards = matchedCards;
      art.markdown = builtMarkdown;
    }

    if (draft) {
      draft.title = builtArticleTitle;
      draft.cards = matchedCards;
      draft.markdown = builtMarkdown;
    }

    commitArticleTargetChanges(target, { bumpTime: true });

    CS.activeArticleId = draft.id;
    CS.activePlanNodeId = target.art?.linkedPlanNodeId || null;

    return target.planNode || null;
  }

  function renderUnifiedArticleCardsHtml(draft) {
    const target = resolveArticleTarget(draft.id);
    const cards = sortPlanCardsInDocOrder(target?.planNode?.data?.cards || []);
    const blocks = E.parseArticleReadonlyBlocks(draft.markdown || "");
    const blockIndexes = blocks.map((b) => b.idx).sort((a, b) => a - b);
    const cardsByPos = new Map();
    cards.forEach((card) => {
      const pos = card.afterBlockIdx;
      const key = Number.isInteger(pos) && pos !== -1 ? pos : -1;
      if (!cardsByPos.has(key)) cardsByPos.set(key, []);
      cardsByPos.get(key).push(card);
    });
    const parts = [];
    let inlineCounter = 0;
    const renderCardAt = (card) => {
      if (card && card.role !== "cover") inlineCounter += 1;
      parts.push(renderPlanSlotCardHtml(card, inlineCounter));
    };
    (cardsByPos.get(-1) || []).forEach(renderCardAt);
    parts.push(renderNotionGapHtml(-1, "文章开头"));
    blockIndexes.forEach((idx) => {
      (cardsByPos.get(idx) || []).forEach(renderCardAt);
      const block = blocks.find((b) => b.idx === idx);
      const label = block && block.text ? String(block.text).slice(0, 24) : `第 ${idx + 1} 段`;
      parts.push(renderNotionGapHtml(idx, label));
    });
    const overflow = [];
    cardsByPos.forEach((cardList, pos) => {
      if (pos !== -1 && !blockIndexes.includes(pos)) overflow.push(...cardList);
    });
    if (overflow.length) {
      const tailIdx = blockIndexes.length ? blockIndexes[blockIndexes.length - 1] : -1;
      overflow.forEach(renderCardAt);
      parts.push(renderNotionGapHtml(tailIdx, "文章末尾"));
    }
    return parts.join("");
  }

  function renderNotionGapHtml(idx, label) {
    return `<div class="ic-notion-gap" data-gap-idx="${idx}"><button type="button" class="ic-notion-insert-btn" data-plan-insert-at="${idx}">＋ 在${esc(label)}添加配图</button></div>`;
  }

  // Reader preview as its own page.  The editor keeps the full width for writing
  // and 预览 opens ?subview=preview; 返回编辑 goes back with ?subview=editor.
  function renderArticlePreviewPage(articleId, draftOverride) {
    flushUnifiedArticleEditor();
    // Prefer the in-memory draft: right after saving a whole-page rerender the
    // cloud sync has not reached CS.myArticles yet, and looking only there
    // rendered the writer again instead of the preview.
    const candidates = [draftOverride, CS.activeArticleDraft, ...(CS.myArticles || [])].filter(Boolean);
    const art =
      candidates.find((a) => a && a.id === articleId) ||
      candidates.find((a) => a && (a.markdown || "").trim()) ||
      null;
    if (!art) {
      console.warn("[preview] no draft to preview:", articleId,
                   "known:", (CS.myArticles || []).map((a) => a.id).slice(0, 5));
      CS.articleSubView = "editor";
      renderArticleEditorPage(CS.myArticles || []);
      return;
    }
    CS.stageView = "preview";
    // The reader page needs its own sub-view: without it the next
    // renderFullPreviewStage() (boot calls it right after URL routing) drew the
    // editor over a ?subview=preview deep link or reload.
    CS.articleSubView = "reader";
    CS.activeArticleId = art.id;
    const styleObj = Catalog.resourceMap?.get(art.styleId) || {
      id: art.styleId || "FA-001",
      name: "手绘钢笔淡彩",
      image: "/images/individual/FA/FA-001.webp",
    };
    const cards = resolveArticleTarget(art.id)?.planNode?.data?.cards || [];

    DOM.previewStage.innerHTML = `
      <div class="ic-wechat-editor-root ic-article-preview-root">
        <header class="ic-wechat-topbar" id="wechat-topbar">
          <div style="display:flex;align-items:center;gap:10px;">
            <button type="button" class="btn btn-sm" id="preview-btn-list" style="font-weight:750;padding:3px 10px;height:28px;box-sizing:border-box;">← 文章列表</button>

          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <div class="ic-article-segmented-switch" id="preview-switch-group" role="group" aria-label="模式切换">
              <button type="button" class="ic-article-seg-btn" id="preview-switch-editor">编辑</button>
              <button type="button" class="ic-article-seg-btn is-active" id="preview-switch-preview">预览</button>
            </div>
          </div>
        </header>

        <div class="ic-wechat-body">
          <div class="ic-wechat-scroll-area" style="align-items:center;">
            <div class="ic-article-preview-sheet">
              ${renderWeChatArticlePreviewHtml(art, styleObj, false, { cards })}
            </div>
          </div>
        </div>

        <footer class="ic-wechat-bottombar" id="wechat-bottombar">
          <span class="ic-article-preview-meta">${art.markdown ? (art.markdown.replace(/[#*\s]/g, "").length) : 0} 字 · 配图 ${cards.filter((c) => c.imageUrl).length}/${cards.length} 张</span>
        </footer>
      </div>
    `;

    const back = () => {
      // Keep the draft in memory so the writer returns to the same text, and
      // carry the id in the URL so a reload lands on the same article.
      CS.articleEditorDraft = art;
      CS.activeArticleId = art.id;
      const url = new URL(location.href);
      url.searchParams.set("entry", "article");
      url.searchParams.set("subview", "editor");
      url.searchParams.set("articleId", art.id);
      history.pushState({}, "", url.toString());
      openUnifiedArticleEditor(art.id);
    };
    DOM.previewStage.querySelector("#preview-switch-editor")?.addEventListener("click", back);
    DOM.previewStage.querySelector("#preview-btn-back-editor")?.addEventListener("click", back);
    // Same destination as the editor's "← 文章列表"; this used to call an
    // undefined renderArticleDirectoryPage and threw.
    DOM.previewStage.querySelector("#preview-btn-list")?.addEventListener("click", () => {
      openMyArticlesPage({ subView: "all-list" });
    });
  }

  function speakArt(text) {
    if (!text) return;
    const el = DOM.previewStage && DOM.previewStage.querySelector("#art-live");
    if (el) {
      el.textContent = "";
      setTimeout(() => {
        el.textContent = text;
      }, 50);
    }
  }

  function renderArticleEditorCardHtml(card, inlineNo, anchorHtml, plainAnchor, options = {}) {
    const role = card.role || "inline";
    const isCover = role === "cover";
    const status = card.status || "idle";
    const isGenerating = Boolean(options.isGenerating);
    const { rw, rh } = parseCardRatioNumbers(card.ratio || (isCover ? "2.35:1" : "4:3"));

    let layoutName = "";
    if (card.layoutId) {
      const res = (options.catalog && options.catalog.resourceMap && options.catalog.resourceMap.get(card.layoutId)) || null;
      layoutName = (res && res.name) || "";
    }

    const ratioText = card.ratio || (isCover ? "2.35:1" : "4:3");
    let specMeta = ratioText;
    if (card.layoutId) {
      specMeta += ` · ${card.layoutId}${layoutName ? ' ' + layoutName : ''}`;
    }

    let statusText = "待生成";
    let statusPrefix = "";
    let genBtnText = "生成";
    let genBtnAria = isCover ? "生成封面" : `生成插图 ${inlineNo}`;

    if (status === "generating") {
      statusText = "生成中";
      statusPrefix = '<span class="art-spinner ic-art-spin-icon" style="margin-right:4px;"></span>';
      genBtnText = "生成中…";
      genBtnAria = isCover ? "封面生成中" : `插图 ${inlineNo} 生成中`;
    } else if (status === "done") {
      statusText = "已完成";
      statusPrefix = "✓ ";
      genBtnText = "重新生成";
      genBtnAria = isCover ? "重新生成封面" : `重新生成插图 ${inlineNo}`;
    } else if (status === "error") {
      statusText = "生成失败";
      statusPrefix = "! ";
      genBtnText = "重试";
      genBtnAria = isCover ? "重试封面" : `重试插图 ${inlineNo}`;
    }

    const cardPromptDesc = card.subject || (card.prompt ? String(card.prompt).slice(0, 60) : "未指定主题");

    if (isCover) {
      return `
        <div
          id="art-card-cover"
          class="ic-art-card ${card.isNewEntrance ? 'is-entering' : ''}"
          data-plan-card-id="${esc(card.id)}"
          data-card-id="${esc(card.id)}"
          data-role="cover"
          data-status="${esc(status)}"
          data-after-block="-1"
          role="group"
          aria-label="封面，${esc(statusText)}"
        >
          <div class="ic-art-card-head ic-art-head">
            <div class="ic-art-head-left" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              <span class="ic-art-chip-role" data-role="cover">封面</span>
              <span class="ic-art-chip-status" data-status="${esc(status)}">${statusPrefix}${esc(statusText)}</span>
              <span class="ic-art-spec-meta">${esc(specMeta)}</span>
            </div>
            <div class="ic-art-actions">
              <button
                type="button"
                class="btn btn-sm"
                data-plan-gen-one="${esc(card.id)}"
                aria-label="${esc(genBtnAria)}"
                ${status === "generating" || isGenerating ? "disabled" : ""}
              >${esc(genBtnText)}</button>
              <button
                type="button"
                class="btn btn-sm ic-art-btn-prompt"
                data-plan-edit="${esc(card.id)}"
                aria-label="调整封面的提示词"
              >调提示词</button>
            <button type="button" class="btn btn-sm" data-plan-use-history="${esc(card.id)}" ${status === "generating" ? "disabled" : ""} title="从我的历史图片选一张插入">用历史图</button>
            ${card.imageUrl && Array.isArray(card.variants) && card.variants.length ? `<button type="button" class="btn btn-sm" data-plan-variants="${esc(card.id)}">版本对比</button>` : ""}
              <button
                type="button"
                class="ic-art-btn-del"
                data-plan-del="${esc(card.id)}"
                title="删除配图位"
                aria-label="删除封面"
              >🗑</button>
            </div>
          </div>

          <div class="ic-art-cover-note" style="font-size:12px;color:var(--ink-muted,#766d62);">固定在文章开头</div>

          <div class="ic-art-cover-box ${card.imageUrl ? 'has-image' : 'is-empty'}" style="--r-w:${rw};--r-h:${rh};">
            ${
              card.imageUrl
                ? `
              <img src="${esc(card.imageUrl)}" alt="${esc(card.title || '文章封面')}" loading="lazy" />
              <button
                type="button"
                class="ic-mini-glass-btn"
                data-plan-zoom="${esc(card.imageUrl)}"
                data-plan-zoom-title="${esc(card.title || '文章封面')}"
                aria-label="放大查看封面"
                style="position:absolute;right:10px;top:10px;"
              >🔍 放大</button>
            `
                : `<span class="ic-art-thumb-ratio" style="font-size:12px;color:var(--ink-faint,#9e9589);">${esc(ratioText)}</span>`
            }
          </div>

          <div class="ic-art-subject">
            <span class="ic-art-subject-prefix ic-art-subject-lbl">主题：</span>${esc(cardPromptDesc)}
          </div>
          <div class="ic-art-reason"><strong>推荐理由：</strong>${esc(card.purpose || "辅助理解文章的核心内容")}</div>
          ${
            status === "error"
              ? `<div class="ic-art-error-note" style="font-size:12px;color:var(--art-err-ink);line-height:1.5;">${esc(card.errorText || "生成没有成功，可以重试")}</div>`
              : ""
          }
        </div>
      `;
    }

    // Inline card
    const anchorDesc = plainAnchor || "位于段落之后";
    const isOrphan = Boolean(options.isOrphan);
    const afterBlock = options.afterBlockIdxOverride != null ? options.afterBlockIdxOverride : (card.afterBlockIdx ?? 0);
    return `
      <div
        class="ic-art-card ${card.isNewEntrance ? 'is-entering' : ''} ${isOrphan ? 'is-orphan' : ''}"
        data-plan-card-id="${esc(card.id)}"
        data-card-id="${esc(card.id)}"
        data-role="inline"
        data-status="${esc(status)}"
        data-after-block="${afterBlock}"
        role="group"
        aria-label="插图 ${inlineNo}，${esc(statusText)}，${esc(anchorDesc)}"
      >
        <div class="ic-art-card-head ic-art-head" style="grid-area:head;">
          <div class="ic-art-head-left" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <button
              type="button"
              class="ic-art-handle"
              data-plan-drag="${esc(card.id)}"
              aria-label="移动插图 ${inlineNo}，当前${esc(anchorDesc)}"
              aria-describedby="art-handle-help"
            >⋮⋮</button>
            <span class="ic-art-chip-role" data-role="inline">插图 ${inlineNo}</span>
            <span class="ic-art-chip-status" data-status="${esc(status)}">${statusPrefix}${esc(statusText)}</span>
            <span class="ic-art-spec-meta">${esc(specMeta)}</span>
          </div>
          <div class="ic-art-actions">
            <button
              type="button"
              class="btn btn-sm"
              data-plan-gen-one="${esc(card.id)}"
              aria-label="${esc(genBtnAria)}"
              ${status === "generating" || isGenerating ? "disabled" : ""}
            >${esc(genBtnText)}</button>
            <button
              type="button"
              class="btn btn-sm ic-art-btn-prompt"
              data-plan-edit="${esc(card.id)}"
              aria-label="调整插图 ${inlineNo} 的提示词"
            >调提示词</button>
            <button type="button" class="btn btn-sm" data-plan-use-history="${esc(card.id)}" ${status === "generating" ? "disabled" : ""} title="从我的历史图片选一张插入">用历史图</button>
            ${card.imageUrl && Array.isArray(card.variants) && card.variants.length ? `<button type="button" class="btn btn-sm" data-plan-variants="${esc(card.id)}">版本对比</button>` : ""}
            <button
              type="button"
              class="ic-art-btn-del"
              data-plan-del="${esc(card.id)}"
              title="删除配图位"
              aria-label="删除插图 ${inlineNo}"
            >🗑</button>
          </div>
        </div>

        <div class="ic-art-thumb ${card.imageUrl ? 'has-image' : 'is-empty'}" style="grid-area:thumb;--r-w:${rw};--r-h:${rh};">
          ${
            card.imageUrl
              ? `
            <img src="${esc(card.imageUrl)}" alt="${esc(card.title || '插图 ' + inlineNo)}" loading="lazy" />
            <button
              type="button"
              class="ic-mini-glass-btn"
              data-plan-zoom="${esc(card.imageUrl)}"
              data-plan-zoom-title="${esc(card.title || '插图 ' + inlineNo)}"
              aria-label="放大查看插图 ${inlineNo}"
              style="position:absolute;right:6px;top:6px;"
            >🔍 放大</button>
          `
              : `<span class="ic-art-thumb-ratio" style="font-size:12px;color:var(--ink-faint,#9e9589);">${esc(ratioText)}</span>`
          }
        </div>

        <div class="ic-art-meta" style="grid-area:meta;">
          <div class="ic-art-anchor">${anchorHtml}</div>
          <div class="ic-art-subject">
            <span class="ic-art-subject-prefix ic-art-subject-lbl">主题：</span>${esc(cardPromptDesc)}
          </div>
          <div class="ic-art-reason"><strong>推荐理由：</strong>${esc(card.purpose || "辅助理解文章的核心内容")}</div>
          ${
            status === "error"
              ? `<div class="ic-art-error-note" style="font-size:12px;color:var(--art-err-ink);line-height:1.5;">${esc(card.errorText || "生成没有成功，可以重试")}</div>`
              : ""
          }
        </div>
      </div>
    `;
  }

  function openMoveCardPositionModal(planNode, card, inlineNo) {
    if (!planNode || !card) return;
    const blocks = E.parseArticleReadonlyBlocks(planNode.data?.markdown || "", { noStarter: true });
    if (!blocks.length) {
      toast("正文尚无段落，无法移动");
      return;
    }

    const positions = blocks.map((b) => {
      const tag =
        b.kind === "h1"
          ? "H1 标题后"
          : b.kind === "h2"
            ? "章节标题后"
            : b.kind === "h3"
              ? "小节标题后"
              : b.kind === "blockquote"
                ? "引用块后"
                : "正文段落后";
      const isCurrent = card.afterBlockIdx === b.idx;
      return {
        afterIdx: b.idx,
        badge: tag,
        desc: b.text.length > 48 ? `${b.text.slice(0, 48)}…` : b.text,
        isCurrent
      };
    });

    S.openModal({
      title: `把插图 ${inlineNo} 移到…`,
      sizeClass: "modal-medium",
      html: `
        <div id="art-move-modal" style="display:flex;flex-direction:column;gap:10px;">
          <div style="font-size:12.5px;color:var(--ink-muted);">选择目标段落，插图将紧贴在该段落下方：</div>
          <div style="display:flex;flex-direction:column;gap:6px;max-height:56vh;overflow-y:auto;padding-right:4px;">
            ${positions
              .map(
                (p) => `
                <button
                  type="button"
                  class="ic-context-item ${p.isCurrent ? 'is-active' : ''}"
                  data-move-to-pos="${p.afterIdx}"
                  ${p.isCurrent ? 'aria-current="true"' : ''}
                  style="display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid ${p.isCurrent ? 'var(--line-strong)' : 'var(--line-soft)'};border-radius:10px;background:${p.isCurrent ? 'var(--paper-inset)' : '#fff'};text-align:left;"
                >
                  <span class="ic-node-badge ic-badge-output-disp" style="flex-shrink:0;">${esc(p.badge)}</span>
                  <span style="font-size:13px;font-weight:750;color:var(--ink-main);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(p.desc)}</span>
                  ${p.isCurrent ? '<span style="font-size:12px;font-weight:700;color:var(--ink-muted);flex-shrink:0;">当前位置</span>' : '<span style="font-size:12px;font-weight:850;color:var(--ink-strong);flex-shrink:0;">移到此处</span>'}
                </button>
              `
              )
              .join("")}
          </div>
        </div>
      `,
      onMount(root) {
        const currentBtn = root.querySelector("[aria-current='true']");
        if (currentBtn) {
          setTimeout(() => currentBtn.focus(), 30);
        }
        root.querySelectorAll("[data-move-to-pos]").forEach((btn) => {
          btn.onclick = () => {
            const nextIdx = Number(btn.getAttribute("data-move-to-pos"));
            S.closeModal();
            if (nextIdx === card.afterBlockIdx) return;
            card.afterBlockIdx = nextIdx;
            planNode.data.cards = sortPlanCardsInDocOrder(planNode.data.cards || []);
            const target = resolveArticleTarget(planNode);
            if (target?.art) target.art.cards = planNode.data.cards;
            if (CS.articleEditorDraft?.cards) CS.articleEditorDraft.cards = planNode.data.cards;
            commitArticleTargetChanges(target, { bumpTime: true });
            renderFullPreviewStage();
            const newHandle = DOM.previewStage?.querySelector(`.ic-art-card[data-plan-card-id="${card.id}"] [data-plan-drag]`);
            if (newHandle) newHandle.focus();
            const targetBlock = blocks.find((b) => b.idx === nextIdx);
            const blockPreview = targetBlock ? targetBlock.text.slice(0, 16) : `第 ${nextIdx + 1} 段`;
            speakArt(`插图 ${inlineNo} 已移到「${blockPreview}」之后`);
          };
        });
      }
    });
  }

  function bindArticleEditorInteractions(planNode, flowEl) {
    if (!planNode || !flowEl) return;
    const target = resolveArticleTarget(planNode);
    const cards = planNode.data?.cards || [];
    const blocks = E.parseArticleReadonlyBlocks(planNode.data?.markdown || "", { noStarter: true });

    // Handle keys and clicks on card handles
    flowEl.querySelectorAll(".ic-art-handle[data-plan-drag]").forEach((handleEl) => {
      const cid = handleEl.getAttribute("data-plan-drag");
      const card = cards.find((c) => c.id === cid);
      if (!card) return;

      const inlineCards = cards.filter((c) => c.role !== "cover");
      const inlineNo = inlineCards.indexOf(card) + 1;

      // Click handle opens move modal
      handleEl.onclick = (e) => {
        e.stopPropagation();
        openMoveCardPositionModal(planNode, card, inlineNo);
      };

      // Keyboard navigation
      handleEl.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openMoveCardPositionModal(planNode, card, inlineNo);
          return;
        }

        const maxIdx = blocks.length > 0 ? blocks.length - 1 : 0;
        let newIdx = null;

        if (e.shiftKey && e.key === "ArrowDown") {
          e.preventDefault();
          const nextHeading = blocks.find((b) => b.idx > card.afterBlockIdx && (b.kind === "h1" || b.kind === "h2" || b.kind === "h3"));
          if (nextHeading) newIdx = nextHeading.idx;
          else speakArt("已在文章末尾");
        } else if (e.shiftKey && e.key === "ArrowUp") {
          e.preventDefault();
          const prevHeadings = blocks.filter((b) => b.idx < card.afterBlockIdx && (b.kind === "h1" || b.kind === "h2" || b.kind === "h3"));
          if (prevHeadings.length) newIdx = prevHeadings[prevHeadings.length - 1].idx;
          else speakArt("已在文章开头");
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          if (card.afterBlockIdx < maxIdx) newIdx = card.afterBlockIdx + 1;
          else speakArt("已在文章末尾");
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          if (card.afterBlockIdx > 0) newIdx = card.afterBlockIdx - 1;
          else speakArt("已在文章开头");
        }

        if (newIdx !== null && newIdx !== card.afterBlockIdx) {
          card.afterBlockIdx = newIdx;
          planNode.data.cards = sortPlanCardsInDocOrder(planNode.data.cards);
          if (target?.art) target.art.cards = planNode.data.cards;
          if (CS.articleEditorDraft?.cards) CS.articleEditorDraft.cards = planNode.data.cards;
          commitArticleTargetChanges(target, { bumpTime: true });
          renderFullPreviewStage();
          const refocused = DOM.previewStage?.querySelector(`.ic-art-card[data-plan-card-id="${card.id}"] [data-plan-drag]`);
          if (refocused) refocused.focus();
          const targetBlock = blocks.find((b) => b.idx === newIdx);
          const blockPreview = targetBlock ? targetBlock.text.slice(0, 16) : `第 ${newIdx + 1} 段`;
          speakArt(`插图 ${inlineNo} 已移到「${blockPreview}」之后`);
        }
      };
    });

    // Notion-style Drag and Drop on Handles
    flowEl.querySelectorAll(".ic-art-handle[data-plan-drag]").forEach((handleEl) => {
      handleEl.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const dragCardId = handleEl.getAttribute("data-plan-drag");
        const dragCard = cards.find((c) => c.id === dragCardId);
        const cardDom = flowEl.querySelector(`.ic-art-card[data-plan-card-id="${dragCardId}"]`);
        if (!dragCard || !cardDom) return;

        const scrollContainer = DOM.previewStage?.querySelector("#wechat-scroll-container");
        const startX = e.clientX;
        const startY = e.clientY;
        let moved = false;
        let ghostEl = null;
        let dropLineEl = null;
        let bestTarget = null;
        let autoScrollTimer = null;

        const inlineCards = cards.filter((c) => c.role !== "cover");
        const inlineNo = inlineCards.indexOf(dragCard) + 1;

        const cleanupDrag = () => {
          window.removeEventListener("pointermove", onPointerMove);
          window.removeEventListener("pointerup", onPointerUp);
          window.removeEventListener("keydown", onKeyDown);
          if (autoScrollTimer) clearInterval(autoScrollTimer);
          flowEl.classList.remove("is-dragging");
          if (cardDom) {
            cardDom.style.opacity = "";
            cardDom.style.borderStyle = "";
          }
          if (ghostEl && ghostEl.parentNode) ghostEl.parentNode.removeChild(ghostEl);
          if (dropLineEl && dropLineEl.parentNode) dropLineEl.parentNode.removeChild(dropLineEl);
        };

        const onKeyDown = (ke) => {
          if (ke.key === "Escape") {
            ke.preventDefault();
            cleanupDrag();
          }
        };

        const computeCandidates = () => {
          const cands = [];
          const segEls = flowEl.querySelectorAll(".ic-art-seg");
          segEls.forEach((segEl) => {
            const sIdx = Number(segEl.getAttribute("data-seg-idx") || 0);
            const ta = segEl.querySelector(".ic-art-seg-ta");
            if (!ta) return;
            const taRect = ta.getBoundingClientRect();
            const segAfterBlock = Number(segEl.nextElementSibling?.getAttribute("data-gap-after") ?? sIdx);
            cands.push({
              afterBlockIdx: Math.max(0, segAfterBlock),
              y: taRect.bottom,
              text: ta.value.slice(0, 16)
            });
          });
          flowEl.querySelectorAll(".ic-art-card[data-role='inline']").forEach((cEl) => {
            const cid = cEl.getAttribute("data-plan-card-id");
            if (cid === dragCardId) return;
            const r = cEl.getBoundingClientRect();
            const blk = Number(cEl.getAttribute("data-after-block") || 0);
            cands.push({
              afterBlockIdx: Math.max(0, blk),
              y: r.bottom,
              text: cEl.querySelector(".ic-art-subject")?.textContent?.slice(0, 16) || ""
            });
          });
          return cands;
        };

        let dropCandidates = [];

        const ensureDragVisuals = () => {
          if (ghostEl) return;
          flowEl.classList.add("is-dragging");
          cardDom.style.opacity = "0.4";
          cardDom.style.borderStyle = "dashed";

          ghostEl = document.createElement("div");
          ghostEl.className = "ic-notion-drag-ghost";
          ghostEl.textContent = `⋮⋮ 移动插图 ${inlineNo}：${dragCard.title || "配图卡片"}`;
          document.body.appendChild(ghostEl);

          dropLineEl = document.createElement("div");
          dropLineEl.className = "ic-art-drop-line";
          dropLineEl.innerHTML = `<span class="ic-art-drop-label"></span>`;
          flowEl.appendChild(dropLineEl);

          dropCandidates = computeCandidates();
        };

        const onPointerMove = (ev) => {
          if (!moved && Math.hypot(ev.clientX - startX, ev.clientY - startY) < 4) return;
          if (!moved) {
            moved = true;
            ensureDragVisuals();
          }

          ghostEl.style.left = `${ev.clientX + 14}px`;
          ghostEl.style.top = `${ev.clientY + 12}px`;

          if (scrollContainer) {
            const scRect = scrollContainer.getBoundingClientRect();
            if (ev.clientY < scRect.top + 56) {
              scrollContainer.scrollTop -= 14;
            } else if (ev.clientY > scRect.bottom - 56) {
              scrollContainer.scrollTop += 14;
            }
          }

          let minDist = Infinity;
          bestTarget = null;
          dropCandidates.forEach((cand) => {
            const dist = Math.abs(ev.clientY - cand.y);
            if (dist < minDist) {
              minDist = dist;
              bestTarget = cand;
            }
          });

          if (bestTarget && dropLineEl) {
            const flowRect = flowEl.getBoundingClientRect();
            dropLineEl.style.top = `${bestTarget.y - flowRect.top}px`;
            const lbl = dropLineEl.querySelector(".ic-art-drop-label");
            const targetBlock = blocks.find((b) => b.idx === bestTarget.afterBlockIdx);
            const previewText = targetBlock ? targetBlock.text.slice(0, 16) : (bestTarget.text || "");
            if (lbl) lbl.textContent = `放在「${previewText}」之后`;
          }
        };

        const onPointerUp = () => {
          const wasMoved = moved;
          const targetCand = bestTarget;
          cleanupDrag();

          if (wasMoved && targetCand && targetCand.afterBlockIdx !== dragCard.afterBlockIdx) {
            dragCard.afterBlockIdx = targetCand.afterBlockIdx;
            planNode.data.cards = sortPlanCardsInDocOrder(planNode.data.cards);
            if (target?.art) target.art.cards = planNode.data.cards;
            if (CS.articleEditorDraft?.cards) CS.articleEditorDraft.cards = planNode.data.cards;
            commitArticleTargetChanges(target, { bumpTime: true });
            renderFullPreviewStage();
            const refocused = DOM.previewStage?.querySelector(`.ic-art-card[data-plan-card-id="${dragCard.id}"] [data-plan-drag]`);
            if (refocused) refocused.focus();
            const targetBlock = blocks.find((b) => b.idx === targetCand.afterBlockIdx);
            const previewText = targetBlock ? targetBlock.text.slice(0, 16) : (targetCand.text || "");
            speakArt(`插图 ${inlineNo} 已移到「${previewText}」之后`);
          }
        };

        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("keydown", onKeyDown);
      });
    });
  }

  function reanchorCardsFromSegments(target, segTexts) {
    if (!target) return;
    const cards = target.planNode?.data?.cards || target.art?.cards || [];
    if (!cards.length || !segTexts || !segTexts.length) return;

    const segBlockCounts = segTexts.map((txt) => {
      return E.parseArticleReadonlyBlocks(txt || "", { noStarter: true }).length;
    });

    const flowEl = DOM.previewStage?.querySelector("#art-editor-flow");
    if (!flowEl) return;

    const segEls = Array.from(flowEl.querySelectorAll(".ic-art-seg"));
    if (!segEls.length) return;

    let cumulativeBlocks = 0;
    segEls.forEach((segEl, sIdx) => {
      const bCount = segBlockCounts[sIdx] || 0;
      cumulativeBlocks += bCount;
      const newAnchor = Math.max(0, cumulativeBlocks - 1);

      let nextEl = segEl.nextElementSibling;
      while (nextEl && !nextEl.classList.contains("ic-art-seg")) {
        if (nextEl.classList.contains("ic-art-card") && nextEl.dataset.role !== "cover") {
          const cid = nextEl.dataset.planCardId || nextEl.dataset.cardId;
          const cardObj = cards.find((c) => c.id === cid);
          if (cardObj) {
            if (sIdx === segEls.length - 1) {
              const totalBlocks = segBlockCounts.reduce((a, b) => a + b, 0);
              const maxIdx = Math.max(0, totalBlocks - 1);
              if (cardObj.afterBlockIdx >= maxIdx) {
                cardObj.afterBlockIdx = maxIdx;
                nextEl.dataset.afterBlock = String(maxIdx);
              }
            } else {
              cardObj.afterBlockIdx = newAnchor;
              nextEl.dataset.afterBlock = String(newAnchor);
            }
          }
        }
        nextEl = nextEl.nextElementSibling;
      }
    });

    if (target.planNode && target.planNode.data) {
      target.planNode.data.cards = cards;
    }
    if (target.art) {
      target.art.cards = cards;
    }
    commitArticleTargetChanges(target, { bumpTime: false });
  }

  function renderArticleEditorPage(sortedArticles) {
    const draft = CS.articleEditorDraft || {
      title: "",
      markdown: "",
      styleId: "FA-001",
      coverRatio: "2.35:1",
      inlineRatio: "4:3"
    };

    const isPreview = false;
    clearUnifiedArticleEditorFlush();
    const target = resolveArticleTarget(draft.id);
    const cards = sortPlanCardsInDocOrder(draft?.cards || target?.planNode?.data?.cards || target?.art?.cards || []);
    const blocks = E.parseArticleReadonlyBlocks(draft.markdown || "", { withLines: true, noStarter: true });
    const segments = E.buildEditorSegments(draft.markdown || "", cards);

    const hasCards = cards.length > 0;
    const hasImageUrl = cards.some((c) => c.imageUrl);
    const isGenerating = isArticleGenerating(target?.planNode?.data || {});
    const isPlanning = Boolean(CS.articleIsPlanning);
    const hasBodyText = Boolean((draft.markdown || "").trim());
    const idleOrErrorCount = cards.filter((c) => !c.imageUrl && c.status !== "generating").length;
    const allDone = hasCards && cards.every((c) => c.status === "done" && c.imageUrl);

    const canGenerate = idleOrErrorCount > 0 && !isGenerating && !isPlanning;
    const canExport = hasImageUrl && hasBodyText && !isGenerating && !isPlanning;
    const canPublish = hasImageUrl && hasBodyText && !isGenerating && !isPlanning;

    // Spec 4.6 Vermilion Primary Button Rule
    let isPrimaryPlan = false;
    let isPrimaryBatch = false;
    let isPrimaryPublish = false;
    if (isPlanning || isGenerating) {
      // none has btn-primary
    } else if (!hasCards) {
      isPrimaryPlan = true;
    } else if (idleOrErrorCount > 0) {
      isPrimaryBatch = true;
    } else if (allDone) {
      isPrimaryPublish = true;
    }

    const batchBtnText = idleOrErrorCount > 0 ? `生成剩余配图（${idleOrErrorCount} 张）` : "配图已全部生成";
    let planBtnHtml = "AI 规划配图";
    if (isPlanning) {
      planBtnHtml = '<span class="art-spinner ic-art-spin-icon" style="margin-right:4px;"></span>AI 规划中…';
    } else if (hasCards) {
      planBtnHtml = "重新规划";
    }
    const planDisabled = isGenerating || isPlanning;

    const styleObj = Catalog.resourceMap?.get(draft.styleId) || {
      id: draft.styleId || "FA-001",
      name: "手绘钢笔淡彩",
      image: "/images/individual/FA/FA-001.webp"
    };

    if (!draft._editorToken) {
      draft._editorToken = E.uid("ed");
    }
    const editorToken = draft._editorToken;

    // Construct #art-plan-summary HTML
    let summaryHtml = "";
    const showUndo = Boolean(CS.articlePlanUndoState && CS.articlePlanUndoState.expireAt > Date.now());
    const undoButtonHtml = showUndo
      ? '<button type="button" class="btn btn-sm" id="art-plan-undo" style="margin-left:auto;text-decoration:underline;background:none;border:none;cursor:pointer;color:var(--ink-strong,#1f1b16);font-weight:700;">撤销</button>'
      : "";

    if (isPlanning) {
      summaryHtml = `
        <div id="art-plan-summary" class="ic-art-summary-loading" role="status" tabindex="-1">
          <span class="art-spinner ic-art-spin-icon" style="margin-right:4px;"></span>
          <span>正在调用手绘 Skill 分析文章结构，约 10–30 秒…</span>
          <button type="button" class="btn btn-sm" id="art-plan-cancel" style="margin-left:auto;">取消</button>
        </div>
      `;
    } else if (CS.articlePlanError) {
      const err = CS.articlePlanError;
      summaryHtml = `
        <div id="art-plan-summary" class="ic-art-summary-error" role="alert" tabindex="-1">
          <span style="font-weight:700;margin-right:4px;">!</span>
          <span>${esc(err.text)}</span>
          <div style="margin-left:auto;display:flex;gap:8px;">
            ${err.canRetry ? '<button type="button" class="btn btn-sm" id="art-plan-retry" style="text-decoration:underline;background:none;border:none;cursor:pointer;color:inherit;font-weight:700;">重试</button>' : ''}
            ${err.canTemplate ? '<button type="button" class="btn btn-sm" id="art-plan-use-template" style="text-decoration:underline;background:none;border:none;cursor:pointer;color:inherit;font-weight:700;">用模板规划</button>' : ''}
          </div>
        </div>
      `;
    } else if (CS.articleDocReplacedNotice) {
      summaryHtml = `
        <div id="art-plan-summary" tabindex="-1">
          <span style="color:var(--art-warn-ink);font-weight:700;margin-right:4px;">!</span>
          <span>正文已替换，配图位置可能需要重新规划</span>
          <button type="button" class="btn btn-sm" id="art-plan-replan-btn" style="margin-left:auto;text-decoration:underline;background:none;border:none;cursor:pointer;color:var(--ink-strong);font-weight:700;">重新规划</button>
        </div>
      `;
    } else if (hasCards) {
      const planSource = cards.find((c) => c.planSource)?.planSource || "";
      const coverCard = cards.find((c) => c.role === "cover");
      const coverCount = coverCard ? 1 : 0;
      const inlineCount = cards.filter((c) => c.role !== "cover").length;
      const articleType = coverCard?.articleType || "";
      const articleTypeLabel = articleType === "narrative" ? "叙事类" : articleType === "knowledge" ? "知识类" : articleType;

      const inlineText = inlineCount > 0 ? `插图 ${inlineCount}` : "暂无插图";
      if (planSource === "template") {
        summaryHtml = `
          <div id="art-plan-summary" tabindex="-1">
            <span class="ic-art-chip-source" style="margin-right:6px;">模板规划</span>
            <span>${inlineCount > 0 ? 'AI 未参与，图位按章节标题分配，可拖动调整' : (coverCount > 0 ? `封面 ${coverCount} · ` : '') + '暂无插图'}</span>
            <button type="button" id="art-plan-retry-ai" class="btn btn-sm" style="margin-left:${showUndo ? '8px' : 'auto'};text-decoration:underline;background:none;border:none;cursor:pointer;color:var(--ink-strong);font-weight:700;">再试一次 AI</button>
            ${undoButtonHtml}
          </div>
        `;
      } else if (planSource === "model") {
        summaryHtml = `
          <div id="art-plan-summary" tabindex="-1">
            <span>AI 规划 · ${coverCount > 0 ? `封面 ${coverCount} · ` : ''}${inlineText}${articleTypeLabel ? ' · ' + articleTypeLabel : ''}</span>
            ${undoButtonHtml}
          </div>
        `;
      } else {
        summaryHtml = `
          <div id="art-plan-summary" tabindex="-1">
            <span>${coverCount > 0 ? `封面 ${coverCount} · ` : ''}${inlineText}</span>
            ${undoButtonHtml}
          </div>
        `;
      }
    }

    // Real task state is derived from settled card requests, never fake progress.
    const batchState = _activeArticleBatchRun || CS.lastArticleBatchSummary;
    const batchSummaryHtml = batchState && Array.isArray(batchState.ids || CS.lastArticleBatchSummary?.ids)
      ? `<section class="hw-article-generation-summary" aria-live="polite">
          <div class="hw-article-summary-head"><strong>${_activeArticleBatchRun ? "正在并发生图" : "本批生成结果"}</strong>
          <span>${batchState.completed ?? batchState.finished ?? 0} / ${batchState.total} 已处理 · ${batchState.parallel || 1} 路并发</span></div>
          <div class="hw-article-summary-meter" role="progressbar" aria-label="本批生成进度" aria-valuemin="0"
            aria-valuemax="${batchState.total}" aria-valuenow="${batchState.completed ?? batchState.finished ?? 0}">
            <span style="width:${Math.round(100 * (batchState.completed ?? batchState.finished ?? 0) / Math.max(1,batchState.total))}%"></span>
          </div>
          <p>成功 ${batchState.succeeded ?? 0} 张 · 失败 ${batchState.failed ?? 0} 张 · 跳过 ${batchState.skipped ?? 0} 张
            ${_activeArticleBatchRun ? " · 运行中 " + (_activeArticleBatchRun.running || 0) + " 张" : " · 失败项可单独重试"}</p>
        </section>` : "";

    // Construct #art-editor-flow HTML
    const renderCardHtml = (card, inlineNo, anchorHtml, plainAnchor, extraOpts = {}) => {
      return renderArticleEditorCardHtml(card, inlineNo, anchorHtml, plainAnchor, Object.assign({
        isGenerating,
        catalog: Catalog
      }, extraOpts));
    };

    let flowParts = [];
    const coverCard = cards.find((c) => c.role === "cover");
    const inlineCards = cards.filter((c) => c.role !== "cover");

    if (coverCard) {
      flowParts.push(renderCardHtml(coverCard, 0, "", ""));
    } else if (hasCards) {
      flowParts.push(`
        <div class="ic-art-gap is-visible" data-gap-after="-1">
          <button type="button" class="ic-art-gap-btn ic-art-insert-btn" data-plan-insert-at="-1" aria-label="添加封面">＋ 添加封面</button>
        </div>
      `);
    }

    if (!hasCards) {
      // Edge case A: Empty state
      flowParts.push(`
        <div class="ic-art-empty-hint">写完正文后点底部「AI 规划配图」，封面会放在文章开头，插图会放到对应段落之后。</div>
        <div class="ic-art-seg" data-seg-idx="0">
          <textarea
            class="ic-art-seg-ta"
            id="art-seg-ta-0"
            data-seg-idx="0"
            style="min-height:540px;"
            aria-label="正文"
            placeholder="# 文章主标题&#10;&#10;引言与核心导语，在此展开背景与核心论点…&#10;&#10;## 第一章：核心概念&#10;章节第一部分阐述…&#10;&#10;## 第二章：实战与落地&#10;章节第二部分内容…"
          >${esc(draft.markdown || "")}</textarea>
        </div>
        <div class="ic-art-gap is-visible ic-art-end-gap" data-gap-after="${blocks.length > 0 ? blocks.length - 1 : 0}">
          <button type="button" class="ic-art-gap-btn ic-art-insert-btn" data-plan-insert-at="${blocks.length > 0 ? blocks.length - 1 : 0}" aria-label="在文末添加插图">＋ 在文末添加插图</button>
        </div>
      `);
    } else {
      let inlineCounter = 0;
      const totalSegs = segments.length;
      const maxBlockIdx = blocks.length > 0 ? blocks.length - 1 : 0;
      const cardsByCut = new Map();
      const orphanCards = [];

      inlineCards.forEach((c) => {
        const rawIdx = typeof c.afterBlockIdx === "number" ? c.afterBlockIdx : 0;
        if (blocks.length > 0 && rawIdx > maxBlockIdx) {
          orphanCards.push(c);
        } else {
          if (!cardsByCut.has(rawIdx)) cardsByCut.set(rawIdx, []);
          cardsByCut.get(rawIdx).push(c);
        }
      });

      segments.forEach((seg, sIdx) => {
        const segAriaLabel = totalSegs > 1 ? `正文第 ${sIdx + 1} 段，共 ${totalSegs} 段` : "正文";
        const hasOddTicks = (seg.text.match(/```/g) || []).length % 2 === 1;

        flowParts.push(`
          <div class="ic-art-seg" data-seg-idx="${seg.segIdx}">
            <textarea
              class="ic-art-seg-ta"
              id="art-seg-ta-${seg.segIdx}"
              data-seg-idx="${seg.segIdx}"
              aria-label="${esc(segAriaLabel)}"
              placeholder="${seg.text ? '' : '这一段已清空。继续写，或删除下方的插图'}"
            >${esc(seg.text)}</textarea>
          </div>
        `);

        if (hasOddTicks) {
          flowParts.push('<div class="ic-art-seg-warn">! 代码块未闭合，配图位置可能不准</div>');
        }

        if (sIdx < totalSegs - 1) {
          const cardsHere = cardsByCut.get(seg.afterBlockIdx) || [];
          if (cardsHere.length >= 3) {
            flowParts.push(`<div class="ic-art-stack-warn">! 这里连续放了 ${cardsHere.length} 张插图，读者会连续看图，建议拖开</div>`);
          }

          cardsHere.forEach((c, cIdx) => {
            inlineCounter += 1;
            const b = blocks.find((blk) => blk.idx === c.afterBlockIdx);
            const isHeading = b && (b.kind === "h2" || b.kind === "h3");
            const prefix = isHeading ? "§ " : "";
            const previewText = b ? b.text.slice(0, 24) : `第 ${c.afterBlockIdx + 1} 段`;
            const plainAnchor = `位于「${previewText}」之后`;
            let anchorHtml;
            if (cIdx === 0) {
              anchorHtml = `<span>${prefix}位于「${esc(previewText)}」之后</span>`;
            } else {
              anchorHtml = '<span>↳ 同一位置</span>';
            }
            flowParts.push(renderCardHtml(c, inlineCounter, anchorHtml, plainAnchor));
          });

          const b = blocks.find((blk) => blk.idx === seg.afterBlockIdx);
          const gapLabel = b ? b.text.slice(0, 16) : `第 ${seg.afterBlockIdx + 1} 段`;
          flowParts.push(`
            <div class="ic-art-gap ic-art-gap-zone" data-gap-after="${seg.afterBlockIdx}">
              <button type="button" class="ic-art-gap-btn ic-art-insert-btn" data-plan-insert-at="${seg.afterBlockIdx}" aria-label="在「${esc(gapLabel)}」之后添加插图">＋ 在此添加插图</button>
            </div>
          `);
        } else {
          // Last segment
          const cardsHere = cardsByCut.get(seg.afterBlockIdx) || [];
          if (cardsHere.length >= 3) {
            flowParts.push(`<div class="ic-art-stack-warn">! 这里连续放了 ${cardsHere.length} 张插图，读者会连续看图，建议拖开</div>`);
          }

          cardsHere.forEach((c, cIdx) => {
            inlineCounter += 1;
            const b = blocks.find((blk) => blk.idx === c.afterBlockIdx);
            const isHeading = b && (b.kind === "h2" || b.kind === "h3");
            const prefix = isHeading ? "§ " : "";
            const previewText = b ? b.text.slice(0, 24) : (blocks.length > 0 ? "文末" : "");
            const plainAnchor = previewText ? `位于「${previewText}」之后` : "位于文末";
            let anchorHtml;
            if (cIdx === 0) {
              anchorHtml = `<span>${prefix}${plainAnchor}</span>`;
            } else {
              anchorHtml = '<span>↳ 同一位置</span>';
            }
            flowParts.push(renderCardHtml(c, inlineCounter, anchorHtml, plainAnchor));
          });

          const tailBlockIdx = blocks.length > 0 ? blocks[blocks.length - 1].idx : 0;

          // Orphan cards (Spec 3.6 D)
          orphanCards.forEach((c) => {
            inlineCounter += 1;
            const plainAnchor = "原位置的段落已删除";
            const anchorHtml = '<span class="ic-art-anchor is-orphan">! 原位置的段落已删除</span>';
            flowParts.push(renderCardHtml(c, inlineCounter, anchorHtml, plainAnchor, {
              isOrphan: true,
              afterBlockIdxOverride: tailBlockIdx
            }));
          });

          flowParts.push(`
            <div class="ic-art-gap is-visible ic-art-end-gap" data-gap-after="${tailBlockIdx}">
              <button type="button" class="ic-art-gap-btn ic-art-insert-btn" data-plan-insert-at="${tailBlockIdx}" aria-label="在文末添加插图">＋ 在文末添加插图</button>
            </div>
          `);
        }
      });
    }

    DOM.previewStage.innerHTML = `
      <div class="ic-wechat-editor-root">
        <div id="art-live" class="ic-sr-only" aria-live="polite"></div>
        <div id="art-handle-help" class="ic-sr-only">方向键上下移动一个段落，Shift 加方向键移到上一个或下一个标题，回车选择位置</div>

        <!-- 1. FIXED TOP TOOLBAR (顶部固定工具栏) -->
        <header class="ic-wechat-topbar" id="wechat-topbar">
          <div style="display:flex;align-items:center;gap:10px;">
            <button type="button" class="btn btn-sm" id="editor-btn-back" style="font-weight:750;padding:3px 10px;height:28px;box-sizing:border-box;">← 文章列表</button>

          </div>

          <!-- Mode / Formatting Tools -->
          <div style="display:flex;align-items:center;gap:10px;">
            <div class="ic-wechat-tools-group">
              <button type="button" class="ic-wechat-tool-btn" data-fmt="h1" title="一级主标题">H1</button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="h2" title="二级章节标题">H2</button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="h3" title="三级小节标题">H3</button>
              <div class="ic-wechat-tool-sep"></div>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="bold" title="加粗 (Ctrl+B)"><strong>B</strong></button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="italic" title="斜体 (Ctrl+I)"><em>I</em></button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="quote" title="重点引用">❝</button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="hr" title="分割线">—</button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="ul" title="无序列表">• 列表</button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="ol" title="有序列表">1. 列表</button>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="code" title="代码块">&lt;/&gt;</button>
              <div class="ic-wechat-tool-sep"></div>
              <button type="button" class="ic-wechat-tool-btn" data-fmt="illust" title="在此插入配图位">
                插入配图位
              </button>
            </div>
          </div>

          <!-- Top-right: reader preview & Document Upload -->
          <div style="display:flex;align-items:center;gap:10px;">
            <label class="btn btn-sm" style="cursor:pointer;padding:3px 10px;font-size:12px;font-weight:750;" title="上传文档重新由 AI 解析覆盖当前正文">
              导入/替换文档
              <input type="file" id="editor-file-replace-inp" accept=".md,.markdown,.txt,.doc,.docx,.pdf" hidden />
            </label>
            <div class="ic-article-segmented-switch" id="editor-switch-group" role="group" aria-label="模式切换">
              <button type="button" class="ic-article-seg-btn is-active" id="editor-switch-editor">编辑</button>
              <button type="button" class="ic-article-seg-btn" id="editor-switch-preview">预览</button>
            </div>
          </div>
        </header>

        <!-- 2. MIDDLE AREA (左侧大纲/历史 + 中间无滚动条滚动纸张) -->
        <div class="ic-wechat-body">
          ${renderArticleSidebarHtml(sortedArticles, CS.activeArticleId)}

          <div class="ic-wechat-scroll-area" id="wechat-scroll-container">
            <article class="ic-wechat-paper" id="art-editor-paper" data-editor-token="${editorToken}" ${isPlanning ? 'aria-busy="true"' : ''}>
              <!-- Article Title -->
              <div class="ic-wechat-title-box">
                <input
                  type="text"
                  class="ic-wechat-title-input"
                  id="editor-title-inp"
                  maxlength="64"
                  value="${esc(draft.title || "")}"
                  placeholder="请输入文章主标题（留空自动使用 Markdown 首行一级标题）"
                />
                <span class="ic-wechat-title-count" id="editor-title-count">${(draft.title || "").length}/64</span>
              </div>

              <div class="ic-wechat-paper-divider"></div>

              <!-- Summary / Status / Error bar -->
              ${summaryHtml}
              ${batchSummaryHtml}

              <!-- Editor Flow -->
              <div id="art-editor-flow">
                ${flowParts.join("\n")}
              </div>
            </article>
          </div>
        </div>

        <!-- 3. FIXED BOTTOM BAR (底部固定状态与主操作栏) -->
        <footer class="ic-wechat-bottombar" id="wechat-bottombar">
          <div class="ic-wechat-bottombar-left">
            <div class="ic-wechat-char-counter">
              正文字数 <strong id="editor-char-count">${(draft.markdown || "").length}</strong>
              <span id="editor-save-state" role="status" aria-live="polite" style="font-size:11px;color:var(--ic-muted);font-weight:750;margin-left:8px;"></span>
              <button type="button" id="editor-sync-retry" class="hw-article-sync-retry" hidden>重试云端同步</button>
            </div>

            <div class="ic-wechat-bottom-select-group">
              <!-- Visual Style Picker with Thumbnail Image -->
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:12px;color:var(--ic-muted);font-weight:750;">画风:</span>
                <button type="button" class="btn btn-sm ic-wechat-style-badge" id="editor-style-picker" title="点击更换手绘视觉画风（展示代表图，防止同名混淆）">
                  <img src="${esc(styleObj.image || '')}" class="ic-wechat-style-thumb" id="editor-style-thumb" alt="" onerror="this.style.display='none'" />
                  <div class="ic-wechat-style-meta">
                    <span class="ic-wechat-style-id" id="editor-style-id">#${esc(styleObj.id)}</span>
                    <span class="ic-wechat-style-name" id="editor-style-name">${esc(styleObj.name || styleObj.id)}</span>
                  </div>
                  <span style="font-size:10px;color:var(--ink-muted);font-weight:800;margin-left:4px;">更换 ▾</span>
                </button>
              </div>

              <!-- Cover Aspect Ratio Selector -->
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:12px;color:var(--ic-muted);font-weight:750;">封面画幅:</span>
                <select class="hw-select" id="editor-cover-ratio" style="padding:4px 8px;font-size:12px;">
                  <option value="2.35:1" ${draft.coverRatio === "2.35:1" ? "selected" : ""}>2.35:1（微信公众号超宽封面）</option>
                  <option value="16:9" ${draft.coverRatio === "16:9" ? "selected" : ""}>16:9（B站 / 视频横版封面）</option>
                  <option value="3:4" ${draft.coverRatio === "3:4" ? "selected" : ""}>3:4（小红书竖版封面）</option>
                  <option value="1:1" ${draft.coverRatio === "1:1" ? "selected" : ""}>1:1（方形封面）</option>
                </select>
              </div>

              <!-- Inline Illustration Ratio Selector -->
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:12px;color:var(--ic-muted);font-weight:750;">章节插图:</span>
                <select class="hw-select" id="editor-inline-ratio" style="padding:4px 8px;font-size:12px;">
                  <option value="4:3" ${draft.inlineRatio === "4:3" ? "selected" : ""}>4:3（经典阅读插图）</option>
                  <option value="16:9" ${draft.inlineRatio === "16:9" ? "selected" : ""}>16:9（宽屏图表插图）</option>
                  <option value="3:4" ${draft.inlineRatio === "3:4" ? "selected" : ""}>3:4（竖版信息卡）</option>
                  <option value="1:1" ${draft.inlineRatio === "1:1" ? "selected" : ""}>1:1（方形插图）</option>
                </select>
              </div>
            </div>
          </div>

          <div class="ic-wechat-bottombar-right">
            <!-- Main Primary Action Button -->
            <button
              type="button"
              class="btn btn-sm ${isPrimaryPlan ? 'btn-primary' : ''} ic-wechat-btn-plan"
              id="editor-btn-plan"
              ${planDisabled ? "disabled" : ""}
              ${isPlanning ? 'aria-busy="true"' : ''}
            >
              ${planBtnHtml}
            </button>
            <button
              type="button"
              class="btn btn-sm ${isPrimaryBatch ? 'btn-primary' : ''}"
              id="editor-btn-batch"
              ${canGenerate ? "" : "disabled"}
            >${esc(batchBtnText)}</button>
            <button type="button" class="btn btn-sm" id="editor-btn-export" ${canExport ? "" : "disabled"}>导出</button>
            <button
              type="button"
              class="btn btn-sm ${isPrimaryPublish ? 'btn-primary' : ''}"
              id="editor-btn-publish"
              ${canPublish ? "" : "disabled"}
            >发布</button>
          </div>
        </footer>
      </div>
    `;

    bindArticleSidebar(DOM.previewStage, CS.activeArticleId);

    const flowEl = DOM.previewStage.querySelector("#art-editor-flow");
    if (flowEl && target?.planNode) {
      bindArticleEditorInteractions(target.planNode, flowEl);
      bindNotionPlanSheetInteractions(target.planNode, flowEl);
    }

    const backBtn = DOM.previewStage.querySelector("#editor-btn-back");
    if (backBtn) {
      backBtn.onclick = () => {
        openMyArticlesPage({ subView: "all-list" });
      };
    }

    const titleInp = DOM.previewStage.querySelector("#editor-title-inp");
    const titleCountEl = DOM.previewStage.querySelector("#editor-title-count");
    const charCountEl = DOM.previewStage.querySelector("#editor-char-count");
    const coverSel = DOM.previewStage.querySelector("#editor-cover-ratio");
    const inlineSel = DOM.previewStage.querySelector("#editor-inline-ratio");
    const stylePickerBtn = DOM.previewStage.querySelector("#editor-style-picker");
    const replaceInp = DOM.previewStage.querySelector("#editor-file-replace-inp");
    const planBtn = DOM.previewStage.querySelector("#editor-btn-plan");
    const togglePreviewBtn = DOM.previewStage.querySelector("#editor-switch-preview, #editor-btn-toggle-preview");
    const batchBtn = DOM.previewStage.querySelector("#editor-btn-batch");
    const exportBtn = DOM.previewStage.querySelector("#editor-btn-export");
    const publishBtn = DOM.previewStage.querySelector("#editor-btn-publish");

    const getSegTextareas = () => {
      return Array.from(DOM.previewStage.querySelectorAll(".ic-art-seg-ta"));
    };

    const readMarkdown = () => {
      const tas = getSegTextareas();
      if (!tas.length) return draft.markdown || "";
      return tas.map((ta) => ta.value).join("\n");
    };

    const adjustSegHeights = () => {
      const tas = getSegTextareas();
      const isSingle = tas.length <= 1;
      tas.forEach((ta) => {
        ta.style.height = "auto";
        const minH = isSingle ? 540 : 48;
        ta.style.height = Math.max(minH, ta.scrollHeight) + "px";
      });
    };

    const saveCurrentDraftFromInputs = () => {
      if (titleInp) draft.title = titleInp.value;
      draft.markdown = readMarkdown();
      if (coverSel) draft.coverRatio = coverSel.value;
      if (inlineSel) draft.inlineRatio = inlineSel.value;
    };

    const autosaveScope = currentCacheScopeKey();
    let autosaveActive = true;
    let autoSyncTimer = null;

    const isCurrentEditor = () => {
      if (!autosaveActive || autosaveScope !== currentCacheScopeKey()) return false;
      if (CS.articleEditorDraft !== draft) return false;
      const paper = DOM.previewStage.querySelector("#art-editor-paper");
      return paper && paper.getAttribute("data-editor-token") === editorToken;
    };

    const collectDraftFromInputs = (d) => {
      if (!d) return d;
      if (titleInp) {
        d.title = titleInp.value;
        if (titleInp.value.trim()) d.titleSource = "manual";
      }
      d.markdown = readMarkdown();
      if (coverSel) d.coverRatio = coverSel.value;
      if (inlineSel) d.inlineRatio = inlineSel.value;
      return d;
    };

    const updateSavedState = (state) => {
      const el = DOM.previewStage.querySelector("#editor-save-state");
      if (!el) return;
      const retry = DOM.previewStage.querySelector("#editor-sync-retry");
      const remote = Boolean(App.state?.serverBacked && App.state?.loggedIn);
      if (retry) {
        retry.hidden = !remote || !["failed", "conflict"].includes(_articlesSyncStatus);
        retry.textContent = _articlesSyncStatus === "conflict" ? "恢复为新文章" : "重试云端同步";
      }
      if (state === "dirty") el.textContent = "本地保存中…";
      else if (state === "empty") el.textContent = "未填写";
      else if (!remote || _articlesSyncStatus === "local") el.textContent = "已保存到此浏览器";
      else if (_articlesSyncStatus === "conflict") el.textContent = "版本冲突 · 本地稿已保留，云端未覆盖";
      else if (_articlesSyncStatus === "failed") el.textContent = "本地已保存 · 云端同步失败";
      else if (_articlesSyncStatus === "pending" || _articlesSyncStatus === "syncing") el.textContent = "本地已保存 · 正在同步云端…";
      else if (_articlesSyncStatus === "synced") el.textContent = "已同步到云端";
      else el.textContent = "已保存到此浏览器 · 云端状态待确认";
    };
    const syncRetryBtn = DOM.previewStage.querySelector("#editor-sync-retry");
    if (syncRetryBtn) syncRetryBtn.onclick = () => {
      if (_articlesCloudConflict) {
        restoreArticleConflictBackup();
        return;
      }
      scheduleCloudArticlesSync();
      updateSavedState("saved");
    };
    const handleCloudSyncState = () => {
      if (isCurrentEditor()) updateSavedState(hasEditorContent() ? "saved" : "empty");
    };
    document.addEventListener("handraw:article-cloud-sync", handleCloudSyncState);

    const commitSync = ({ bumpTime = true, markSaved = true, collect = true } = {}) => {
      if (!isCurrentEditor()) return false;
      // A caller that just wrote the draft itself must not have it read back from
      // inputs that have not been re-rendered yet -- an import would be erased.
      if (collect) collectDraftFromInputs(draft);
      const saved = syncArticleEditorDraftToHistory(draft, { bumpTime });
      if (markSaved) {
        if (saved && draft.id) {
          try {
            const url = new URL(window.location.href);
            url.searchParams.set("entry", "article");
            url.searchParams.set("articleId", draft.id);
            url.searchParams.set("subview", "editor");
            window.history.replaceState(null, "", url.pathname + url.search);
          } catch (_) {}
          updateSavedState("saved");
        } else if (!saved) {
          updateSavedState("dirty");
        }
      }
      return saved;
    };

    const hasEditorContent = () =>
      Boolean((draft.title || "").trim() || (draft.markdown || "").trim());

    const triggerDebouncedSync = () => {
      if (!isCurrentEditor()) return;
      updateSavedState(hasEditorContent() ? "dirty" : "empty");
      if (autoSyncTimer) clearTimeout(autoSyncTimer);
      autoSyncTimer = setTimeout(() => {
        autoSyncTimer = null;
        if (!isCurrentEditor()) return;
        collectDraftFromInputs(draft);
        if (!commitSync({ bumpTime: true, markSaved: true }) && isCurrentEditor()) {
          updateSavedState(hasEditorContent() ? "dirty" : "empty");
        }
      }, 500);
    };

    const handleBeforeUnload = () => {
      if (!isCurrentEditor()) return;
      collectDraftFromInputs(draft);
      syncArticleEditorDraftToHistory(draft, { bumpTime: false });
    };
    window.addEventListener("beforeunload", handleBeforeUnload);

    CS.articleEditorFlush = () => {
      if (autosaveActive && isCurrentEditor()) {
        collectDraftFromInputs(draft);
        syncArticleEditorDraftToHistory(draft, { bumpTime: false });
      }
      autosaveActive = false;
      if (autoSyncTimer) {
        clearTimeout(autoSyncTimer);
        autoSyncTimer = null;
      }
      window.removeEventListener("beforeunload", handleBeforeUnload);
      document.removeEventListener("handraw:article-cloud-sync", handleCloudSyncState);
    };

    // 预览 opens the reader preview page
    if (togglePreviewBtn) {
      togglePreviewBtn.onclick = () => {
        collectDraftFromInputs(draft);
        syncArticleEditorDraftToHistory(draft, { bumpTime: false });
        const url = new URL(location.href);
        url.searchParams.set("entry", "article");
        url.searchParams.set("subview", "preview");
        url.searchParams.set("articleId", draft.id);
        history.pushState({}, "", url.toString());
        renderArticlePreviewPage(draft.id, draft);
      };
    }

    if (titleInp) {
      titleInp.oninput = () => {
        draft.title = titleInp.value;
        draft.titleSource = titleInp.value.trim() ? "manual" : "auto";
        if (titleCountEl) titleCountEl.textContent = `${titleInp.value.length}/64`;
        triggerDebouncedSync();
      };
    }

    // Segment textarea event handling
    let lastFocusedSeg = null;
    const segTas = getSegTextareas();
    segTas.forEach((ta, idx) => {
      if (segments[idx]) ta.value = segments[idx].text;
      ta.onfocus = () => {
        lastFocusedSeg = ta;
      };
      ta.oninput = () => {
        draft.markdown = readMarkdown();
        if (charCountEl) charCountEl.textContent = draft.markdown.length;
        adjustSegHeights();
        reanchorCardsFromSegments(target, getSegTextareas().map((t) => t.value));
        triggerDebouncedSync();
      };
      ta.onkeydown = (e) => {
        if (e.key === "ArrowDown") {
          const pos = ta.selectionStart;
          const textAfter = ta.value.slice(pos);
          if (!textAfter.includes("\n")) {
            const nextTa = segTas[idx + 1];
            if (nextTa) {
              e.preventDefault();
              nextTa.focus();
              nextTa.setSelectionRange(0, 0);
            }
          }
        } else if (e.key === "ArrowUp") {
          const pos = ta.selectionStart;
          const textBefore = ta.value.slice(0, pos);
          if (!textBefore.includes("\n")) {
            const prevTa = segTas[idx - 1];
            if (prevTa) {
              e.preventDefault();
              prevTa.focus();
              const endPos = prevTa.value.length;
              prevTa.setSelectionRange(endPos, endPos);
            }
          }
        } else if (e.key === "Backspace") {
          // Guard against merging segments on Backspace at start
          if (ta.selectionStart === 0 && ta.selectionEnd === 0 && idx > 0) {
            // Keep segment boundary; do not silently merge
          }
        }
      };
    });
    if (!lastFocusedSeg && segTas.length > 0) {
      lastFocusedSeg = segTas[0];
    }
    setTimeout(adjustSegHeights, 50);

    if (coverSel) {
      coverSel.onchange = () => {
        draft.coverRatio = coverSel.value;
        syncArticleEditorDraftToHistory(draft);
      };
    }
    if (inlineSel) {
      inlineSel.onchange = () => {
        draft.inlineRatio = inlineSel.value;
        syncArticleEditorDraftToHistory(draft);
      };
    }

    // Format toolbar button handlers
    const insertFormat = (prefix, suffix = "", defaultPlaceholder = "") => {
      const ta = lastFocusedSeg || getSegTextareas()[0];
      if (!ta) return;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const val = ta.value;
      const selected = val.substring(start, end) || defaultPlaceholder;
      const replacement = prefix + selected + suffix;
      const newPos = start + prefix.length + selected.length;
      ta.setRangeText(replacement, start, end, "select");
      draft.markdown = readMarkdown();
      if (charCountEl) charCountEl.textContent = draft.markdown.length;
      adjustSegHeights();
      ta.focus();
      try {
        ta.setSelectionRange(newPos, newPos);
      } catch (_) {}
      reanchorCardsFromSegments(target, getSegTextareas().map((t) => t.value));
      saveCurrentDraftFromInputs();
      syncArticleEditorDraftToHistory(draft, { bumpTime: true });
    };

    DOM.previewStage.querySelectorAll("[data-fmt]").forEach((btn) => {
      btn.onclick = () => {
        const fmt = btn.getAttribute("data-fmt");
        if (fmt === "h1") insertFormat("\n# ", "\n", "主标题");
        else if (fmt === "h2") insertFormat("\n## ", "\n", "章节标题");
        else if (fmt === "h3") insertFormat("\n### ", "\n", "小节标题");
        else if (fmt === "bold") insertFormat("**", "**", "加粗文本");
        else if (fmt === "italic") insertFormat("*", "*", "斜体文本");
        else if (fmt === "quote") insertFormat("\n> ", "\n", "重点引用内容");
        else if (fmt === "hr") insertFormat("\n\n---\n\n", "");
        else if (fmt === "ul") insertFormat("\n- ", "\n", "列表要点");
        else if (fmt === "ol") insertFormat("\n1. ", "\n", "列表序号");
        else if (fmt === "code") insertFormat("\n```\n", "\n```\n", "代码或提纲");
        else if (fmt === "illust") {
          // Spec 3.3: Insert plan card at cursor block position
          const ta = lastFocusedSeg || getSegTextareas()[0];
          let targetBlockIdx = 0;
          if (ta) {
            const currentTas = getSegTextareas();
            const segIdx = currentTas.indexOf(ta);
            let textBeforeCursor = "";
            for (let i = 0; i < segIdx; i++) {
              textBeforeCursor += currentTas[i].value + "\n";
            }
            textBeforeCursor += ta.value.slice(0, ta.selectionStart);
            const blocksBefore = E.parseArticleReadonlyBlocks(textBeforeCursor, { noStarter: true });
            targetBlockIdx = Math.max(0, blocksBefore.length - 1);
          }
          if (!target?.planNode) {
            createNewArticlePlan({
              title: draft.title,
              markdown: draft.markdown,
              styleId: draft.styleId,
              coverRatio: draft.coverRatio,
              inlineRatio: draft.inlineRatio,
              articleId: draft.id
            });
          }
          const updatedTarget = resolveArticleTarget(draft.id);
          if (updatedTarget?.planNode) {
            insertNewPlanCard(updatedTarget.planNode, targetBlockIdx, { openModal: true });
          }
        }
      };
    });

    if (stylePickerBtn) {
      stylePickerBtn.onclick = () => {
        S.openAssetPickerModal({
          kind: "style",
          currentId: draft.styleId || "FA-001",
          onSelect: (id) => {
            if (!isCurrentEditor()) return;
            draft.styleId = id;
            syncArticleEditorDraftToHistory(draft);
            const res = Catalog.resourceMap?.get(id);
            const thumbEl = DOM.previewStage.querySelector("#editor-style-thumb");
            const idEl = DOM.previewStage.querySelector("#editor-style-id");
            const nameEl = DOM.previewStage.querySelector("#editor-style-name");
            if (thumbEl && res?.image) {
              thumbEl.src = res.image;
              thumbEl.style.display = "block";
            }
            if (idEl) idEl.textContent = `#${id}`;
            if (nameEl) nameEl.textContent = res?.name || id;
          }
        });
      };
    }

    if (replaceInp) {
      replaceInp.onchange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        replaceInp.value = "";
        replaceInp.disabled = true;
        collectDraftFromInputs(draft);
        const savedSnapshot = { title: draft.title, markdown: draft.markdown };
        toast("正在解析文档…");
        const finishReplace = () => {
          replaceInp.disabled = false;
        };
        const reader = new FileReader();
        reader.onerror = () => {
          finishReplace();
          toast("文档读取失败，正文未更改");
        };
        reader.onabort = () => finishReplace();
        reader.onload = async (evt) => {
          try {
            const res = await window.HandrawTaskJourney.submitImport(file.name, evt.target.result, async () => false);
            if (!isCurrentEditor()) return;
            // No review modal: a successful import replaces the current
            // editor's title and Markdown immediately, then autosaves.
            if (!isCurrentEditor()) { toast("编辑器已切换，未覆盖其他文章"); return; }
            const okTitle = res && typeof res.title === "string" ? res.title : savedSnapshot.title;
            const okMarkdown = res && typeof res.markdown === "string" ? res.markdown : savedSnapshot.markdown;
            draft.title = okTitle;
            draft.markdown = okMarkdown;

            // Clamp existing cards to new blocks range
            const newBlocks = E.parseArticleReadonlyBlocks(okMarkdown, { noStarter: true });
            const maxIdx = Math.max(0, newBlocks.length - 1);
            const currentCards = target?.planNode?.data?.cards || target?.art?.cards || [];
            currentCards.forEach((c) => {
              if (c.role !== "cover" && typeof c.afterBlockIdx === "number" && c.afterBlockIdx > maxIdx) {
                c.afterBlockIdx = maxIdx;
              }
            });
            if (target?.planNode) target.planNode.data.cards = currentCards;
            if (target?.art) target.art.cards = currentCards;
            commitArticleTargetChanges(target, { bumpTime: true });

            CS.articleDocReplacedNotice = true;
            renderFullPreviewStage();
            commitSync({ bumpTime: true, markSaved: true, collect: false });
            renderFullPreviewStage();
            window.HandrawTaskJourney.acknowledgeImport();

            let succMsg = (res.aiUsed === "all" || res.aiUsed === true) ? "已用 AI 整理为 Markdown" : res.aiUsed === "partial" ? "部分段落 AI 整理失败，已保留原文，请检查结果" : "AI 不可用，已按原文导入，请检查标题和排版";
            if (res.truncated) succMsg += "（正文过长，已截断）";
            toast(succMsg);
          } catch (err) {
            if (isCurrentEditor()) {
              draft.title = savedSnapshot.title;
              draft.markdown = savedSnapshot.markdown;
              renderFullPreviewStage();
            }
            if (err.status === 401 || err.code === "login_required") {
              toast("请先登录后再导入文档");
              if (typeof S.openLoginModal === "function") {
                S.openLoginModal("请先登录后再导入文档");
              }
            } else {
              toast("解析文档失败：" + (err.message || "请检查文件格式"));
              console.error("[Article Replace Error]", err);
            }
          } finally {
            finishReplace();
          }
        };
        reader.readAsDataURL(file);
      };
    }

    updateSavedState(hasEditorContent() ? "saved" : "empty");

    // Local template plan fallback
    const applyLocalTemplatePlan = async () => {
      CS.articlePlanError = null;
      CS.articleDocReplacedNotice = false;
      const built = E.buildArticleDocument(draft.markdown || "", draft, Catalog);
      const templateCards = (built.cards || []).map((c) =>
        Object.assign({}, c, {
          planSource: "template",
          purpose: c.purpose || (c.role === "cover" ? "确立整篇文章的视觉主旨" : "在章节间提供阅读提示")
        })
      );
      const review = await window.HandrawArticleReview.reviewPlan(templateCards, {
        source: "template", articleType: "knowledge",
        existingCards: draft.cards || target?.planNode?.data?.cards || target?.art?.cards || []
      });
      if (!review.approved || !isCurrentEditor()) return;
      const oldCardsBackup = JSON.parse(
        JSON.stringify(target?.planNode?.data?.cards || target?.art?.cards || [])
      );
      CS.articlePlanUndoState = {
        cards: oldCardsBackup,
        expireAt: Date.now() + 10000
      };
      setTimeout(() => {
        if (CS.articlePlanUndoState && Date.now() >= CS.articlePlanUndoState.expireAt) {
          CS.articlePlanUndoState = null;
          const undoEl = DOM.previewStage?.querySelector("#art-plan-undo");
          if (undoEl) undoEl.remove();
        }
      }, 10000);

      planUnifiedArticleDraft(draft, { aiCards: review.cards });
      renderFullPreviewStage();
      const inlineCount = review.cards.filter((c) => c.role !== "cover").length;
      toast(`AI 暂不可用，已按章节模板规划 ${inlineCount} 张插图`);
      speakArt(`AI 暂不可用，已按章节模板规划 ${inlineCount} 张插图`);
    };

    // Plan button execution flow
    const executePlan = async () => {
      CS.articlePlanError = null;
      CS.articleDocReplacedNotice = false;
      CS.articleIsPlanning = true;
      const reqArticleId = draft.id;
      const controller = new AbortController();
      CS.articlePlanAbortController = controller;
      const timeoutId = setTimeout(() => {
        controller.abort();
      }, 45000);

      // In-place loading state (spec 2.3) without tearing down current editor instance
      const paper = DOM.previewStage?.querySelector("#art-editor-paper");
      if (paper) paper.setAttribute("aria-busy", "true");
      getSegTextareas().forEach((t) => (t.readOnly = true));
      DOM.previewStage?.querySelectorAll(".ic-art-card").forEach((c) => {
        c.style.opacity = ".5";
        c.style.pointerEvents = "none";
      });
      if (planBtn) {
        planBtn.disabled = true;
        planBtn.setAttribute("aria-busy", "true");
        planBtn.innerHTML = '<span class="art-spinner ic-art-spin-icon" style="margin-right:4px;"></span>AI 规划中…';
      }

      let summaryContainer = DOM.previewStage?.querySelector("#art-plan-summary");
      if (!summaryContainer) {
        summaryContainer = document.createElement("div");
        summaryContainer.id = "art-plan-summary";
        const divider = DOM.previewStage?.querySelector(".ic-wechat-paper-divider");
        if (divider && divider.nextSibling) {
          divider.parentNode.insertBefore(summaryContainer, divider.nextSibling);
        } else if (paper) {
          paper.appendChild(summaryContainer);
        }
      }
      summaryContainer.className = "ic-art-summary-loading";
      summaryContainer.setAttribute("role", "status");
      summaryContainer.setAttribute("tabindex", "-1");
      summaryContainer.innerHTML = `
        <span class="art-spinner ic-art-spin-icon" style="margin-right:4px;"></span>
        <span>正在调用手绘 Skill 分析文章结构，约 10–30 秒…</span>
        <button type="button" class="btn btn-sm" id="art-plan-cancel" style="margin-left:auto;">取消</button>
      `;
      const cancelBtn = summaryContainer.querySelector("#art-plan-cancel");
      if (cancelBtn) {
        cancelBtn.onclick = () => {
          CS.articlePlanUserCancelled = true;
          controller.abort();
        };
      }

      try {
        const rawBlocks = E.parseArticleReadonlyBlocks(draft.markdown || "", { withLines: true, noStarter: true });
        const reqBlocks = rawBlocks.slice(0, 200).map((b) => ({
          idx: b.idx,
          kind: b.kind,
          text: String(b.text || "").slice(0, 300)
        }));
        const charCount = String(draft.markdown || "").length;

        const resp = await fetch("/api/studio/article-plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            articleId: draft.id || CS.activeArticleId || "",
            title: draft.title || "",
            blocks: reqBlocks,
            charCount,
            styleId: draft.styleId || "FA-001",
            coverRatio: draft.coverRatio || "2.35:1",
            inlineRatio: draft.inlineRatio || "4:3",
            includeCover: true
          }),
          signal: controller.signal
        });
        clearTimeout(timeoutId);

        if (CS.activeArticleId !== reqArticleId || !isCurrentEditor()) {
          return;
        }

        if (!resp.ok) {
          const errBody = await resp.json().catch(() => ({}));
          const errCode = errBody?.code || errBody?.error || "";
          const errMsg = errBody?.error || resp.statusText || "";

          if (resp.status === 401 || errCode === "login_required") {
            CS.articlePlanError = {
              text: "登录后才能使用 AI 规划",
              canRetry: false,
              canTemplate: false
            };
            renderFullPreviewStage();
            if (typeof S.openLoginModal === "function") {
              S.openLoginModal("登录后才能使用 AI 规划");
            }
            return;
          }
          if (resp.status === 429) {
            CS.articlePlanError = {
              text: errMsg || "今日 AI 规划次数已达上限（30 次），请明天再试",
              canRetry: false,
              canTemplate: false
            };
            renderFullPreviewStage();
            return;
          }
          if (resp.status === 403 && (errCode === "token_disallowed" || errCode === "token_scope_denied")) {
            CS.articlePlanError = {
              text: "当前登录方式不支持 AI 规划，请在网页登录",
              canRetry: false,
              canTemplate: false
            };
            renderFullPreviewStage();
            return;
          }

          CS.articlePlanError = {
            text: `规划失败：${errMsg || resp.status}，正文和配图位都没有改动`,
            canRetry: true,
            canTemplate: true
          };
          renderFullPreviewStage();
          return;
        }

        const data = await resp.json();

        const aiCards = E.buildArticleDocumentFromAi(data, draft, Catalog);

        const review = await window.HandrawArticleReview.reviewPlan(aiCards, {
          source: data.source, articleType: data.articleType,
          existingCards: draft.cards || target?.planNode?.data?.cards || target?.art?.cards || []
        });
        if (!review.approved) {
          CS.articleIsPlanning = false;
          renderFullPreviewStage();
          toast("已保留原配图方案");
          return;
        }
        if (CS.activeArticleId !== reqArticleId || !isCurrentEditor()) return;
        const oldCardsBackup = JSON.parse(
          JSON.stringify(draft.cards || target?.planNode?.data?.cards || target?.art?.cards || [])
        );
        CS.articlePlanUndoState = {
          cards: oldCardsBackup,
          expireAt: Date.now() + 10000
        };
        setTimeout(() => {
          if (CS.articlePlanUndoState && Date.now() >= CS.articlePlanUndoState.expireAt) {
            CS.articlePlanUndoState = null;
            const undoEl = DOM.previewStage?.querySelector("#art-plan-undo");
            if (undoEl) undoEl.remove();
          }
        }, 10000);

        // Mark entrance animation for newly planned cards
        const approvedCards = review.cards;
        approvedCards.forEach((c) => {
          c.isNewEntrance = true;
        });

        draft.cards = approvedCards;
        planUnifiedArticleDraft(draft, { aiCards: approvedCards });

        const coverCards = approvedCards.filter((c) => c.role === "cover");
        const inlines = approvedCards.filter((c) => c.role !== "cover");
        if (data.source === "model") {
          const coverPart = coverCards.length ? `${coverCards.length} 张封面 + ` : "";
          toast(`已规划 ${coverPart}${inlines.length} 张插图`);
          speakArt(`已规划 ${coverPart}${inlines.length} 张插图`);
        } else {
          toast(`AI 暂不可用，已按章节模板规划 ${inlines.length} 张插图`);
          speakArt(`AI 暂不可用，已按章节模板规划 ${inlines.length} 张插图`);
        }

        CS.articleIsPlanning = false;
        renderFullPreviewStage();
        const summaryEl = DOM.previewStage?.querySelector("#art-plan-summary");
        if (summaryEl) summaryEl.focus();
      } catch (err) {
        clearTimeout(timeoutId);
        if (CS.activeArticleId !== reqArticleId || !isCurrentEditor()) return;
        if (err.name === "AbortError" || controller.signal.aborted) {
          if (CS.articlePlanUserCancelled) {
            CS.articlePlanUserCancelled = false;
            toast("已取消规划");
            speakArt("已取消规划");
          } else {
            CS.articlePlanError = {
              text: "规划超时，正文和配图位都没有改动",
              canRetry: true,
              canTemplate: true
            };
          }
        } else {
          CS.articlePlanError = {
            text: `规划失败：${err.message || err}，正文和配图位都没有改动`,
            canRetry: true,
            canTemplate: true
          };
        }
        renderFullPreviewStage();
      } finally {
        CS.articleIsPlanning = false;
        CS.articlePlanAbortController = null;
      }
    };

    if (planBtn) {
      planBtn.onclick = () => {
        if (isArticleGenerating(target?.planNode?.data || {})) return;
        saveCurrentDraftFromInputs();
        const title = (draft.title || "").trim();
        const md = (draft.markdown || "").trim();
        if (!title && !md) {
          toast("请输入文章标题或正文内容");
          return;
        }

        const existingCards = draft?.cards || target?.planNode?.data?.cards || target?.art?.cards || [];
        const nImages = existingCards.filter((c) => c.imageUrl).length;
        const mPrompts = existingCards.filter((c) => c.promptCustomized).length;

        if (nImages > 0 || mPrompts > 0) {
          let clause = "";
          if (nImages > 0 && mPrompts > 0) {
            clause = `当前有 ${nImages} 张已生成配图、${mPrompts} 张调过提示词。重新规划后它们会从文章中移除。`;
          } else if (nImages > 0) {
            clause = `当前有 ${nImages} 张已生成配图。重新规划后它们会从文章中移除。`;
          } else {
            clause = `当前有 ${mPrompts} 张调过提示词。重新规划后它们会从文章中移除。`;
          }

          S.openModal({
            title: "重新规划会替换现有配图位",
            sizeClass: "modal-small ic-modal",
            html: `
              <div style="font-size:14px;line-height:1.6;color:var(--ink-body);padding:8px 0 16px;">
                ${esc(clause)}
              </div>
              <div class="ic-modal-actions" style="display:flex;justify-content:flex-end;gap:10px;">
                <button type="button" class="btn btn-sm" id="art-overwrite-cancel">取消</button>
                <button type="button" class="btn btn-sm btn-primary" id="art-overwrite-confirm">确定替换</button>
              </div>
            `,
            onMount(root) {
              const cancelBtn = root.querySelector("#art-overwrite-cancel");
              cancelBtn?.focus();
              cancelBtn.onclick = () => S.closeModal();
              root.querySelector("#art-overwrite-confirm").onclick = () => {
                S.closeModal();
                executePlan();
              };
            }
          });
          return;
        }

        executePlan();
      };
    }

    // Bind summary action buttons
    const retryBtn = DOM.previewStage.querySelector("#art-plan-retry");
    if (retryBtn) retryBtn.onclick = () => executePlan();

    const useTemplateBtn = DOM.previewStage.querySelector("#art-plan-use-template");
    if (useTemplateBtn) useTemplateBtn.onclick = () => applyLocalTemplatePlan();

    const retryAiBtn = DOM.previewStage.querySelector("#art-plan-retry-ai");
    if (retryAiBtn) retryAiBtn.onclick = () => executePlan();

    const replanNoticeBtn = DOM.previewStage.querySelector("#art-plan-replan-btn");
    if (replanNoticeBtn) replanNoticeBtn.onclick = () => planBtn?.click();

    const cancelPlanBtn = DOM.previewStage.querySelector("#art-plan-cancel");
    if (cancelPlanBtn) {
      cancelPlanBtn.onclick = () => {
        if (CS.articlePlanAbortController) {
          CS.articlePlanUserCancelled = true;
          CS.articlePlanAbortController.abort();
        }
      };
    }

    const undoBtn = DOM.previewStage.querySelector("#art-plan-undo");
    if (undoBtn) {
      undoBtn.onclick = () => {
        if (!CS.articlePlanUndoState) return;
        const restored = JSON.parse(JSON.stringify(CS.articlePlanUndoState.cards || []));
        CS.articlePlanUndoState = null;
        if (target?.planNode) target.planNode.data.cards = restored;
        if (target?.art) target.art.cards = restored;
        draft.cards = restored;
        commitArticleTargetChanges(target, { bumpTime: true });
        renderFullPreviewStage();
        toast("已恢复原来的配图位");
        speakArt("已恢复原来的配图位");
      };
    }

    const persistBeforeAction = () => {
      saveCurrentDraftFromInputs();
      syncArticleEditorDraftToHistory(draft, { bumpTime: true });
    };

    const readTargetCards = (t) => t?.planNode?.data?.cards || t?.art?.cards || [];
    const readTargetHasImage = (t) => readTargetCards(t).some((c) => c?.imageUrl);
    const readTargetGenerating = (t) => isArticleGenerating(t?.planNode?.data || {});

    if (batchBtn) {
      batchBtn.onclick = async () => {
        persistBeforeAction();
        const t = resolveArticleTarget(draft.id);
        if (!readTargetCards(t).length) {
          toast("请先规划封面与插图位");
          return;
        }
        await generateBatchPlanCards(draft.id, { onlyPending: true });
      };
    }
    if (exportBtn) {
      exportBtn.onclick = async () => {
        if (!isCurrentEditor()) return;
        persistBeforeAction();
        const t = resolveArticleTarget(draft.id);
        if (!readTargetHasImage(t)) {
          toast("请先生成配图");
          return;
        }
        if (!((draft.markdown || "").trim())) {
          toast("请先填写正文");
          return;
        }
        await exportZipPackage(draft.id);
      };
    }
    if (publishBtn) {
      publishBtn.onclick = async () => {
        if (!isCurrentEditor()) return;
        persistBeforeAction();
        const t = resolveArticleTarget(draft.id);
        if (!readTargetHasImage(t)) {
          toast("请先生成配图");
          return;
        }
        if (!((draft.markdown || "").trim())) {
          toast("请先填写正文");
          return;
        }
        if (readTargetGenerating(t)) {
          toast("配图生成中，请稍候");
          return;
        }
        await publishArticleToForum(draft.id);
      };
    }
  }

  function switchCreationStage(next) {
    if (next !== "article") flushUnifiedArticleEditor();
    if(next==="article") switchIntoArticleMode();
    else if(next==="quick") {ensureQuickTab();CS.stageView="quick";}
    else if(next==="batch") {ensureBatchTab();CS.stageView="batch";}
    else CS.stageView=next;
    const url = new URL(window.location.href);
    url.searchParams.delete("view");
    url.searchParams.delete("tab");
    url.searchParams.delete("fork");
    url.searchParams.delete("forkTopic");
    url.searchParams.delete("style");
    url.searchParams.delete("layout");
    url.searchParams.set("entry", next === "quick" ? "quick" : next === "batch" ? "batch" : next === "article" ? "article" : "canvas");
    window.history.replaceState(null, "", url.pathname + url.search);
    fullRenderCanvas();

  }

  function renderCreationModeBar() {
    if (!DOM.entryBar) return;
    DOM.entryBar.hidden = false;
    const quick = CS.stageView === "quick";
    const batch = CS.stageView === "batch";
    const canvas = CS.stageView === "canvas";
    const article = CS.stageView === "preview" || CS.stageView === "article";
    const history = CS.stageView === "history";
    const workflows = CS.stageView === "workflows";
    const historyCount = (CS.generationHistory || []).length;
    DOM.entryBar.innerHTML = `<div class="qc-mode-switch" role="group" aria-label="创作任务">
      <button type="button" class="btn btn-sm${quick ? " btn-primary" : ""}" id="studio-mode-quick" aria-pressed="${quick}">单图</button>
      <button type="button" class="btn btn-sm${batch ? " btn-primary" : ""}" id="studio-mode-batch" aria-pressed="${batch}">系列图</button>
      <button type="button" class="btn btn-sm${article ? " btn-primary" : ""}" id="studio-mode-article" aria-pressed="${article}">文章配图</button>
      <button type="button" class="btn btn-sm${canvas ? " btn-primary" : ""}" id="studio-mode-canvas" aria-pressed="${canvas}">画布</button>
    </div><div class="qc-entry-actions"><button type="button" class="btn btn-sm qc-mode-history${history ? " btn-primary" : ""}" id="studio-mode-history" aria-pressed="${history}" title="查看生图历史记录">生图历史</button><button type="button" class="btn btn-sm qc-mode-workflows${workflows ? " btn-primary" : ""}" id="studio-mode-workflows" aria-pressed="${workflows}" title="查看我的工作流">工作流</button></div>`;

    const btnQuick = DOM.entryBar.querySelector("#studio-mode-quick");
    if (btnQuick) btnQuick.onclick = () => { switchCreationStage("quick"); };
    const btnBatch = DOM.entryBar.querySelector("#studio-mode-batch");
    if (btnBatch) btnBatch.onclick = () => { switchCreationStage("batch"); };
    const btnArticle = DOM.entryBar.querySelector("#studio-mode-article");
    if (btnArticle) btnArticle.onclick = () => { switchCreationStage("article"); };
    const btnCanvas = DOM.entryBar.querySelector("#studio-mode-canvas");
    if (btnCanvas) btnCanvas.onclick = () => { switchCreationStage("canvas"); };
    const btnHistory = DOM.entryBar.querySelector("#studio-mode-history");
    if (btnHistory) btnHistory.onclick = () => { openHistoryPage(); };
    const btnWorkflows = DOM.entryBar.querySelector("#studio-mode-workflows");
    if (btnWorkflows) btnWorkflows.onclick = () => { openWorkflowsPage(); };
  }

  let isRenderingQuickStart = false;
  function renderQuickStart() {
    if (isRenderingQuickStart) return;
    isRenderingQuickStart = true;
    try {
      if (!DOM.quickStage) return;
      const isQuick = CS.stageView === "quick";
      const isBatch = CS.stageView === "batch";
      DOM.quickStage.style.display = (isQuick || isBatch) ? "block" : "none";
      renderCreationModeBar();
      if (!isQuick && !isBatch) return;

    if (isBatch) {
      let bp = getBatchParts();
      if (!bp) {
        const tab = ensureBatchTab();
        bp = getBatchParts(tab?.graph || CS.graph);
      }
      if (window.HandrawBatchCreate && bp) {
        const isBatchCurrentBusy = () => {
          if (!bp) return false;
          reconcileDetachedBatchState(bp);
          if (_activeBatchRun?.ctrlId === bp.ctrl.id) return true;
          if (quickBusy?.id === bp.ctrl.id && quickBusy.scope === activeCacheScope) return true;
          // Stopping the local transport does not clear remote reservations.
          // Keep them recoverable, but don't trap the user in a stale
          // generating spinner or leave the Stop button permanently visible.
          if (bp.ctrl.data.status === "stopped") return false;
          return false;
        };
        const busy = isBatchCurrentBusy();
        const displays = bp ? getDownstreamDisplayNodes(bp.ctrl.id) : [];
        // Each standalone display contains items[0], but that is NOT image
        // slot 0 of the series. Derive the canonical series index from the
        // display node slotIndex; gallery entries use their array position.
        // Reusing the per-node item index caused image 3 to also render as 1.
        const results = displays.flatMap((dn, displayIndex) =>
          (dn.data.items || []).flatMap((it, itemIndex) => {
            if (!it?.imageUrl) return [];
            const slotIndex = dn.data.kind === "batch_gallery"
              ? itemIndex
              : Number.isInteger(dn.data.slotIndex) ? dn.data.slotIndex : displayIndex;
            if (Number.isInteger(it.slotIndex) && it.slotIndex !== slotIndex) return [];
            return [{
              id: `${dn.id}:${slotIndex}`,
              imageUrl: it.imageUrl,
              title: it.title || "生成结果",
              node: dn,
              item: it,
              index: slotIndex
            }];
          })
        );
        const markDirtyAndRender = () => {
          markActiveTabDirty();
          persistOpenTabs();
          renderQuickStart();
        };
        const ensureBatchAssetNode = (items) => {
          if (!bp) return;
          let ast = bp.asset;
          if (!ast) {
            ast = E.makeAssetNode(64, 760, { items: items || [] });
            CS.graph.nodes.push(ast);
            CS.graph.edges.push({ id: E.uid("edge"), from: ast.id, to: bp.loop.id });
            CS.graph.edges.push({ id: E.uid("edge"), from: ast.id, to: bp.ctrl.id });
            bp.asset = ast;
          } else if (items) {
            ast.data.items = items;
          }
          markDirtyAndRender();
        };

        window.HandrawBatchCreate.render(
          DOM.quickStage,
          {
            parts: bp,
            graph: CS.graph,
            loggedIn: Boolean(App.state?.loggedIn),
            serverCfg: CS.serverCfg,
            engineMode: CS.engineMode,
            freeQuotaRemaining: App.state?.freeQuotaRemaining ?? App.state?.free_quota_remaining,
            credits: App.state?.credits,
            siteSettings: App.state?.siteSettings,
            catalog: Catalog,
            results,
            displays,
            busy,
            statusText: busy ? "正在批量生成中…" : ""
          },
          {
            isBusy: isBatchCurrentBusy,
            persistDraft: () => {
              markActiveTabDirty();
              persistOpenTabs();
            },
            clearWorkspaceResults: (ctrlId) => {
              clearControlWorkspaceResults(ctrlId || bp.ctrl.id);
              if (bp.loop) {
                bp.loop.data.status = "idle";
                bp.loop.data.currentStep = 0;
                delete bp.loop.data.activeBatchId;
              }
            },
            markDirtyAndRender,
            ensureAssetItems: (items) => ensureBatchAssetNode(items),
            openAssetPicker: ({ kind, field, current, onPick, title } = {}) => {
              // Resource selection configures the next run, even when an older
              // batch is generating. Never silently swallow the click.
              if (!bp?.skill) {
                toast("画风/图型选择器暂不可用：请刷新创作台后重试");
                return;
              }
              const targetField = field || (kind === "style" || kind === "style1" ? "style1" : kind === "style2" ? "style2" : kind === "layout" ? "layout" : kind === "tone" ? "tones" : kind === "mood" ? "moods" : "colors");
              try {
                openSkillFieldPickerModal(bp.skill, targetField, { current, onPick, title });
              } catch (err) {
                console.error("Batch resource picker failed:", err);
                toast("无法打开选择器，请刷新页面后重试");
              }
            },
            openReferencePicker: (opts = {}) => {
              if (!bp || isBatchCurrentBusy()) return;
              ensureBatchAssetNode();
              if (opts && typeof opts === "object" && typeof opts.onConfirm === "function") {
                openAssetPickerModal(opts, {
                  maxCount: opts.maxCount || 3,
                  title: opts.title || "单条参考图（最多 3 张）"
                });
              } else {
                openAssetPickerModal(bp.asset, {
                  maxCount: 4,
                  title: "全局参考图（最多 4 张）",
                  ...opts
                });
              }
            },
            openLoopMultiPicker: (kind) => {
              if (!bp || isBatchCurrentBusy()) return;
              openLoopMultiPickerModal(bp.loop, kind);
            },
            openImageLightbox: (url, title) => {
              openImageLightbox(url, title);
            },
            run: async () => {
              if (!bp || isBatchCurrentBusy()) return;
              const scope = activeCacheScope;
              quickBusy = { id: bp.ctrl.id, scope };
              renderQuickStart();
              try {
                await runLoopNode(bp.loop.id);
              } catch (err) {
                console.error("[Studio Batch] quick run exception", err);
                reportUnexpectedRuntimeError(err);
              } finally {
                if (quickBusy?.scope === scope && quickBusy.id === bp.ctrl.id) quickBusy = null;
                renderQuickStart();
              }
            },
            runSingleRow: async (rowIndex) => {
              if (!bp || isBatchCurrentBusy()) return;
              const scope = activeCacheScope;
              quickBusy = { id: bp.ctrl.id, scope };
              renderQuickStart();
              try {
                await runOutputControlNode(bp.ctrl.id, { onlyItemIdx: rowIndex });
              } catch (err) {
                console.error("[Studio Batch] single row exception", { rowIndex }, err);
                reportUnexpectedRuntimeError(err);
              } finally {
                if (quickBusy?.scope === scope && quickBusy.id === bp.ctrl.id) quickBusy = null;
                renderQuickStart();
              }
            },
            cancel: () => {
              return cancelActiveBatchGeneration(bp.ctrl.id);
            }
          }
        );
        return;
      }
    }

    let p = getQuickParts();
    if (!p) {
      const tab = ensureQuickTab();
      p = getQuickParts(tab?.graph || CS.graph);
    }
    // A server restart leaves serialized "generating" flags in localStorage.
    // Recover only actual cloud requests; never let those flags lock the UI.
    reconcileDetachedQuickState(p);

    if (window.HandrawMakeImage) {
      const isCurrentBusy = () => {
        if (!p) return false;
        // Cloud recovery reservations must not impersonate a live local run.
        // A run is busy only while this page owns its submit/abort controller.
        return Boolean(
          (_activeBatchRun?.ctrlId === p.ctrl.id && !_activeBatchRun.cancelled) ||
          (quickBusy?.id === p.ctrl.id && quickBusy.scope === activeCacheScope)
        );
      };
      const busy = isCurrentBusy();
      const displays = p ? getDownstreamDisplayNodes(p.ctrl.id) : [];
      const results = displays.flatMap((dn) => (dn.data.items || []).filter((it) => it.imageUrl).map((it, index) => ({
        id: `${dn.id}:${index}`, imageUrl: it.imageUrl, title: it.title || "生成结果", node: dn
      })));
      let statusText = busy
        ? "正在生成，可点击「停止等待」结束当前页面的生成流程；已提交云端的任务可能继续执行或计费。"
        : p?.ctrl.data.status === "stopped"
        ? "上次生成已解除本地等待；云端任务可能仍在运行或计费。请先在生图历史确认结果，再决定是否重新生成。"
        : p?.ctrl.data.status === "error"
        ? "生成失败，可检查提示词后点击生成重试；任务与费用以服务端结果为准。"
        : results.length
        ? `已显示 ${results.length} 张结果，保存在你的生成历史中。`
        : "";

      const markDirtyAndRender = () => {
        markActiveTabDirty();
        persistOpenTabs();
        renderQuickStart();
      };

      const persistDraft = () => {
        markActiveTabDirty();
        persistOpenTabs();
      };

      const ensureAssetNode = (items) => {
        if (!p) return;
        let ast = p.asset;
        if (!ast) {
          ast = E.makeAssetNode(64, 800, { items: items || [] });
          CS.graph.nodes.push(ast);
          CS.graph.edges.push({ id: E.uid("edge"), from: ast.id, to: p.ctrl.id });
          p.asset = ast;
        } else {
          ast.data.items = items || [];
        }
        markDirtyAndRender();
      };

      window.HandrawMakeImage.render(DOM.quickStage, {
        parts: p,
        graph: CS.graph,
        loggedIn: Boolean(App.state?.loggedIn),
        serverCfg: CS.serverCfg,
        engineMode: CS.engineMode,
        freeQuotaRemaining: App.state?.freeQuotaRemaining ?? App.state?.free_quota_remaining,
        credits: App.state?.credits,
        siteSettings: App.state?.siteSettings,
        catalog: Catalog,
        results,
        busy,
        statusText,
        forkSource: CS.forkGenerationSource
      }, {
        isBusy: isCurrentBusy,
        cancel: () => {
          const stopped = cancelActiveBatchGeneration(p.ctrl.id);
          if (stopped) {
            // The active worker will persist its "stopped" state when its
            // in-flight fetch settles. The UI should become responsive now.
            renderQuickStart();
          }
          return stopped;
        },
        clearWorkspaceResults: (ctrlId) => clearControlWorkspaceResults(ctrlId || p.ctrl.id),
        markDirtyAndRender,
        persistDraft,
        ensureAssetItems: (items) => ensureAssetNode(items),
        openAssetPicker: ({ kind, field, currentId, onSelect } = {}) => {
          if (!p?.skill) {
            toast("画风/图型选择器暂不可用：请刷新创作台后重试");
            return;
          }
          // Editing the next generation's settings must not be blocked by a
          // pending image task from a previous run.
          const targetField = field || (kind === "style" || kind === "style1" ? "style1" : kind === "style2" ? "style2" : kind === "layout" ? "layout" : "colors");
          try {
            if (typeof onSelect === "function") {
              openSkillFieldPickerModal(p.skill, targetField, {
                current: currentId,
                onPick: (id) => {
                  if (!CS.graph.nodes.includes(p.skill)) return;
                  onSelect(id);
                }
              });
            } else {
              openSkillFieldPickerModal(p.skill, targetField);
            }
          } catch (err) {
            console.error("Make-image resource picker failed:", err);
            toast("无法打开选择器，请刷新页面后重试");
          }
        },
        openReferencePicker: ({ currentRefs, onConfirm }) => {
          if (!p || isCurrentBusy()) return;
          openAssetPickerModal({
            currentRefs,
            onConfirm: (selectedItems) => {
              ensureAssetNode(selectedItems);
            }
          });
        },
        run: async () => {
          if (!p || isCurrentBusy()) return;
          const topic = String(p.text.data.text || "").trim();
          if (!topic) {
            toast("请先填写创作主题");
            const input = DOM.quickStage.querySelector("#make-image-subject");
            if (input) input.focus();
            return;
          }
          // Strictly 1 image per brief
          p.ctrl.data.count = 1;
          const scope = activeCacheScope;
          quickBusy = { id: p.ctrl.id, scope };
          renderQuickStart();
          try {
            await runOutputControlNode(p.ctrl.id);
          } finally {
            if (quickBusy?.scope === scope && quickBusy.id === p.ctrl.id) quickBusy = null;
            renderQuickStart();
          }
        }
      });
      return;
    }

    if (!window.HandrawQuickCreate) return;
    p = getQuickParts();
    const busy = Boolean(p && (p.ctrl.data.status === "generating" || (quickBusy?.id === p.ctrl.id && quickBusy.scope === activeCacheScope)));
    const displays = p ? getDownstreamDisplayNodes(p.ctrl.id) : [];
    const results = displays.flatMap(dn => (dn.data.items || []).filter(it => it.imageUrl).map((it, index) => ({
      id: `${dn.id}:${index}`, imageUrl: it.imageUrl, title: it.title || "生成结果", node: dn
    })));
    const extra = p ? [p.skill.data.style2 ? `角色与场景画风：${[p.skill.data.style1, p.skill.data.style2].join(" + ")}` : "",
      CS.resourceEntryWarning || "",
      CS.graph.nodes.some(n => n.type === "asset") ? "已保留参考图片，可在画布中调整" : "",
      new URLSearchParams(window.location.search).get("purpose") || ""].filter(Boolean).join(" · ") : "";
    window.HandrawQuickCreate.render(DOM.quickStage, {
      available: Boolean(p), busy, loggedIn: Boolean(App.state?.loggedIn), engineMode: CS.engineMode,
      topic: p?.text.data.text || "", count: p?.ctrl.data.count || 1, ratio: p?.ctrl.data.ratio || "3:4",
      mode: p?.ctrl.data.mode || "graphic-text", contextLabel: extra,
      styleResource: p?.skill.data.style1 ? Catalog.resourceMap.get(p.skill.data.style1) : null,
      layoutResource: p?.skill.data.layout ? Catalog.resourceMap.get(p.skill.data.layout) : null,
      costText: generationCostText(p ? buildExecutionPlanForControl(p.ctrl).specs.length : null), results,
      status: busy ? "正在生成，可以稍后回到历史记录查看。" : p?.ctrl.data.status === "error" ? "本批未全部完成，可点击生成重试；任务与费用以服务端结果为准。" : results.length ? `已显示 ${results.length} 张结果，保存在你的生成历史中。` : "填写主题后开始。"
    }, {
      set: setQuickField,
      pick: kind => {
        if (!p || busy) return;
        const field = kind === "style" ? "style1" : "layout";
        S.openAssetPickerModal({ kind, currentId: p.skill.data[field] || "", onSelect: id => {
          if (!CS.graph.nodes.includes(p.skill)) return;
          p.skill.data[field] = id;
          CS.resourceEntryWarning = "";
          markActiveTabDirty(); persistOpenTabs(); renderQuickStart();
        } });
      },
      run: async () => {
        if (!p || busy || !p.text.data.text.trim()) return;
        const scope = activeCacheScope;
        quickBusy = { id: p.ctrl.id, scope };
        renderQuickStart();
        try { await runOutputControlNode(p.ctrl.id); }
        finally {
          if (quickBusy?.scope === scope && quickBusy.id === p.ctrl.id) quickBusy = null;
          renderQuickStart();
        }
      },
      openCanvas: () => switchCreationStage("canvas"),
      openHistory: () => { openHistoryPage(); },
      download: id => {
        const result = results.find(it => it.id === id);
        if (!result) return;
        const anchor = document.createElement("a"); anchor.href = result.imageUrl;
        anchor.download = "handraw-output.webp"; anchor.rel = "noopener"; anchor.click();
      }
    });
    } finally {
      isRenderingQuickStart = false;
    }
  }

  function renderCanvasTemplateLibrary() {
    if (!DOM.canvasStage) return;
    let libEl = DOM.canvasStage.querySelector("#canvas-template-library");
    if (!libEl) {
      libEl = document.createElement("div");
      libEl.id = "canvas-template-library";
      libEl.className = "ic-canvas-template-library";
      DOM.canvasStage.appendChild(libEl);
    }
    const defs = [
      {
        bp: "single",
        title: "节气海报极速出图",
        badge: "日常单图 · 3节点",
        desc: "最常用的日常海报/图文工作流：仅用「风格参数 + 文本参数 → 生成设置」3 个核心节点，零冗余极速出图。"
      },
      {
        bp: "loop_100",
        title: "百图矩阵批量生产（1母题→100张）",
        badge: "百图批量 · 4节点",
        desc: "演示如何输出 100 张图而不建 100 个节点：「AI 扩写主题」从 1 个母题生成 100 条日签 →「批量」驱动仅 1 个「生成设置」，结果自动收敛进 1 个分页「批量图集」节点。"
      },
      {
        bp: "style_ab",
        title: "同文案多画风横评比稿",
        badge: "提案选风 · 3节点",
        desc: "定好一句主文案，无需单独连风格参数，直接用「批量（多画风模式）」一次横评 4 款手绘风格快速定稿。"
      },
      {
        bp: "ip_story",
        title: "IP角色连续故事绘本",
        badge: "角色一致性 · 4节点",
        desc: "通过「图片参数」锁定原创角色与道具外观一致性，配合「套图模式」一次生成 4 幕连续故事分镜。"
      },
      {
        bp: "omnimedia",
        title: "全媒体一稿三端宣发包",
        badge: "多尺寸一分多 · 6节点",
        desc: "新品发布标准链路：一套视觉与卖点经「多尺寸输出」同时分发给 3 个不同规格生成设置（2.35:1 公众号头图 + 3:4 种草套图 + 9:16 竖版海报）。"
      },
      {
        bp: "fusion",
        title: "跨媒介双画风融合实验",
        badge: "双风碰撞 · 3节点",
        desc: "开启「风格参数」双画风融合开关：主体采用手作插画肌理，场景环境采用纪实胶片/水墨山水，打造高辨识度跨次元视觉。"
      },
      {
        bp: "blank",
        title: "空白工作流",
        badge: "自由搭建",
        desc: "从一张干净的空白画布开始，自由从左侧工具箱拖入或双击画布添加任意连接节点。"
      }
    ];

    libEl.innerHTML = `
      <div class="ic-tmpl-lib-wrap">
        <div class="ic-tmpl-lib-head">
          <h2 class="ic-tmpl-lib-title">工作流模板库</h2>
          <p class="ic-tmpl-lib-desc">选择一个典型场景模板快速开始创作，或从空白画布自由编排节点工作流。</p>
        </div>
        <div class="ic-tmpl-grid">
          ${defs
            .map(
              (d) => `
            <div class="ic-tmpl-card" data-tmpl-bp="${d.bp}">
              <div class="ic-tmpl-card-head">
                <span class="ic-tmpl-card-title">${esc(d.title)}</span>
                <span class="ic-tmpl-card-badge">${esc(d.badge)}</span>
              </div>
              <div class="ic-tmpl-card-desc">${esc(d.desc)}</div>
              <button type="button" class="ic-tmpl-card-btn" data-tmpl-bp="${d.bp}">使用此模板</button>
            </div>
          `
            )
            .join("")}
        </div>
      </div>
    `;

    libEl.querySelectorAll("[data-tmpl-bp]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        const bp = el.getAttribute("data-tmpl-bp");
        const found = defs.find((d) => d.bp === bp);
        createWorkflowTab({
          title: found ? found.title : "新工作流",
          blueprint: bp,
          makeActive: true,
          autoFit: true,
          switchToCanvas: true
        });
        libEl.remove();
        fullRenderCanvas();
      };
    });
  }

  function fullRenderCanvas() {
    if (!["quick","batch"].includes(CS.stageView)) {
      renderTopAndBottomDocks();
      return;
    }
    syncAllDownstreamArticlePlans();
    if (CS.stageView === "canvas" && (!CS.tabs || !CS.tabs.length)) {
      if (DOM.nodesLayer) DOM.nodesLayer.innerHTML = "";
      if (DOM.edgesSvg) DOM.edgesSvg.innerHTML = "";
      renderCanvasTemplateLibrary();
    } else {
      const tLib = DOM.canvasStage?.querySelector("#canvas-template-library");
      if (tLib) tLib.remove();
      renderWorldNodes();
      renderFloatingOverlays();
    }
    renderTopAndBottomDocks();
    renderMinimap();
    if (CS.stageView === "quick" || CS.stageView === "batch") {
      renderQuickStart();
    }
  }

  function bindViewportInteractions() {
    const vp = DOM.viewport;
    if (!vp) return;

    vp.addEventListener(
      "wheel",
      (e) => {
        if (e.target.closest("[data-canvas-no-zoom]")) return;
        e.preventDefault();
        closeContextMenu();
        zoomAroundPoint(e.clientX, e.clientY, e.deltaY < 0 ? 1.11 : 1 / 1.11);
      },
      { passive: false }
    );

    vp.addEventListener("dblclick", (e) => {
      if (e.target.closest(".ic-node") || e.target.closest("[data-edge-hit]")) return;
      openContextMenu(e.clientX, e.clientY, screenToWorld(e.clientX, e.clientY), null);
    });

    vp.addEventListener("dragover", (e) => {
      if (!e.dataTransfer.types.includes("application/handraw-item")) return;
      e.preventDefault();
    });

    vp.addEventListener("drop", (e) => {
      const raw = e.dataTransfer.getData("application/handraw-item");
      if (!raw) return;
      e.preventDefault();
      let spec = null;
      try {
        spec = JSON.parse(raw);
      } catch (_) {
        return;
      }
      const targetNodeEl = e.target.closest(".ic-node");
      const targetNode = targetNodeEl ? getNodeById(targetNodeEl.getAttribute("data-node-id")) : null;
      const wp = screenToWorld(e.clientX, e.clientY);

      if (
        targetNode &&
        (targetNode.type === "output_control" || targetNode.type === "bridge" || targetNode.type === "loop") &&
        (spec.kind === "skill_params" || spec.kind === "asset" || spec.kind === "text_input")
      ) {
        spawnShelfItem(spec, { x: targetNode.x - 416, y: targetNode.y }, targetNode.id);
        toast(
          `已将「${spec.kind === "skill_params" ? "风格参数" : spec.kind === "asset" ? "图片参数" : "文本参数"}」连入${
            targetNode.type === "loop" ? "批量" : targetNode.type === "bridge" ? "多尺寸输出" : "生成设置"
          }！`
        );
        return;
      }
      if (targetNode && targetNode.type === "output_control" && spec.kind === "loop") {
        spawnShelfItem(spec, { x: targetNode.x - 416, y: targetNode.y }, targetNode.id);
        toast("已将「批量」连入生成设置！");
        return;
      }

      spawnShelfItem(spec, { x: wp.x - 150, y: wp.y - 100 }, null);
    });

    let dragCtx = null;

    vp.addEventListener("pointerdown", (e) => {
      if (e.button === 2) return;
      closeContextMenu();

      if (
        e.target.closest("button") ||
        e.target.closest("input") ||
        e.target.closest("textarea") ||
        e.target.closest("select") ||
        e.target.closest("label") ||
        e.target.closest(".ic-v4-visual-slot") ||
        e.target.closest(".ic-ing-empty-slot") ||
        e.target.closest("[data-ast-open]") ||
        e.target.closest("[data-disp-zoom]")
      ) {
        return;
      }

      const portEl = e.target.closest("[data-port-node]");
      if (portEl) {
        e.stopPropagation();
        const wp = screenToWorld(e.clientX, e.clientY);
        CS.wiring = {
          fromNodeId: portEl.getAttribute("data-port-node"),
          fromDir: portEl.getAttribute("data-port-dir"),
          curWorldX: wp.x,
          curWorldY: wp.y,
          snapNodeId: null,
          snapDir: null
        };
        DOM.root.classList.add("is-wiring");
        dragCtx = { mode: "wiring", pointerId: e.pointerId };
        try {
          vp.setPointerCapture(e.pointerId);
        } catch (_) {}
        renderEdgesSvg();
        return;
      }

      const edgeHit = e.target.closest("[data-edge-hit]");
      if (edgeHit) {
        e.stopPropagation();
        CS.selectedEdgeId = edgeHit.getAttribute("data-edge-hit");
        CS.selectedEdgePt = { x: e.clientX, y: e.clientY - 18 };
        CS.graph.selectedIds = [];
        renderEdgesSvg();
        renderFloatingOverlays();
        return;
      }

      const nodeEl = e.target.closest(".ic-node");
      if (nodeEl && !CS.spaceHeld && e.button === 0) {
        const nid = nodeEl.getAttribute("data-node-id");
        const clickedNode = getNodeById(nid);
        if (!clickedNode) return;

        CS.selectedEdgeId = null;
        CS.selectedEdgePt = null;

        if (e.shiftKey || e.ctrlKey || e.metaKey) {
          const s = new Set(CS.graph.selectedIds);
          if (s.has(nid)) s.delete(nid);
          else s.add(nid);
          CS.graph.selectedIds = [...s];
        } else if (!CS.graph.selectedIds.includes(nid)) {
          CS.graph.selectedIds = [nid];
        }

        const startPositions = CS.graph.selectedIds
          .map((id) => {
            const n = getNodeById(id);
            return n ? { node: n, el: DOM.nodesLayer.querySelector(`[data-node-id="${id}"]`), ox: n.x, oy: n.y } : null;
          })
          .filter(Boolean);

        dragCtx = {
          mode: "node-drag",
          pointerId: e.pointerId,
          startX: e.clientX,
          startY: e.clientY,
          moved: false,
          undoPushed: false,
          clickedNodeId: nid,
          withModifier: Boolean(e.shiftKey || e.ctrlKey || e.metaKey),
          startPositions
        };
        try {
          vp.setPointerCapture(e.pointerId);
        } catch (_) {}
        renderWorldNodes();
        renderFloatingOverlays();
        return;
      }

      CS.selectedEdgeId = null;
      CS.selectedEdgePt = null;
      const isMarquee = (CS.toolMode === "select" || e.ctrlKey || e.metaKey) && !CS.spaceHeld && e.button === 0;

      if (isMarquee) {
        const box = document.createElement("div");
        box.className = "ic-marquee";
        document.body.appendChild(box);
        dragCtx = { mode: "marquee", pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, box };
        try {
          vp.setPointerCapture(e.pointerId);
        } catch (_) {}
      } else {
        if (!e.shiftKey && CS.graph.selectedIds.length) {
          CS.graph.selectedIds = [];
          renderWorldNodes();
          renderFloatingOverlays();
        }
        vp.classList.add("is-panning");
        dragCtx = { mode: "pan", pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, ovx: CS.vx, ovy: CS.vy };
        try {
          vp.setPointerCapture(e.pointerId);
        } catch (_) {}
      }
    });

    vp.addEventListener("pointermove", (e) => {
      if (!dragCtx || e.pointerId !== dragCtx.pointerId) return;

      if (dragCtx.mode === "pan") {
        CS.vx = dragCtx.ovx + (e.clientX - dragCtx.startX);
        CS.vy = dragCtx.ovy + (e.clientY - dragCtx.startY);
        applyViewportTransform();
        return;
      }

      if (dragCtx.mode === "node-drag") {
        const dxScreen = e.clientX - dragCtx.startX;
        const dyScreen = e.clientY - dragCtx.startY;
        if (!dragCtx.moved && Math.hypot(dxScreen, dyScreen) < 3) return;
        if (!dragCtx.undoPushed) {
          pushUndo();
          dragCtx.undoPushed = true;
          dragCtx.startPositions = dragCtx.startPositions
            .map((it) => {
              const n = getNodeById(it.node.id);
              return n ? { ...it, node: n, el: DOM.nodesLayer.querySelector(`[data-node-id="${n.id}"]`) } : null;
            })
            .filter(Boolean);
        }
        dragCtx.moved = true;
        const dxW = dxScreen / CS.vk;
        const dyW = dyScreen / CS.vk;
        for (const item of dragCtx.startPositions) {
          item.node.x = snapVal(item.ox + dxW);
          item.node.y = snapVal(item.oy + dyW);
          if (item.el) {
            item.el.style.left = `${item.node.x}px`;
            item.el.style.top = `${item.node.y}px`;
          }
        }
        renderEdgesSvg();
        positionFloatingOverlays();
        renderMinimap();
        return;
      }

      if (dragCtx.mode === "marquee") {
        dragCtx.box.style.left = `${Math.min(dragCtx.startX, e.clientX)}px`;
        dragCtx.box.style.top = `${Math.min(dragCtx.startY, e.clientY)}px`;
        dragCtx.box.style.width = `${Math.abs(e.clientX - dragCtx.startX)}px`;
        dragCtx.box.style.height = `${Math.abs(e.clientY - dragCtx.startY)}px`;
        return;
      }

      if (dragCtx.mode === "wiring" && CS.wiring) {
        const wp = screenToWorld(e.clientX, e.clientY);
        CS.wiring.curWorldX = wp.x;
        CS.wiring.curWorldY = wp.y;
        CS.wiring.snapNodeId = null;
        CS.wiring.snapDir = null;

        const srcNode = getNodeById(CS.wiring.fromNodeId);
        const targetDir = CS.wiring.fromDir === "out" ? "in" : "out";
        let bestDist = 48;
        DOM.nodesLayer.querySelectorAll(".ic-port-zone.is-snap").forEach((el) => el.classList.remove("is-snap"));

        for (const cand of CS.graph.nodes) {
          if (cand.id === CS.wiring.fromNodeId) continue;
          const valid = CS.wiring.fromDir === "out" ? canConnectNodes(srcNode, cand) : canConnectNodes(cand, srcNode);
          if (!valid) continue;
          const p = getPortWorldPos(cand, targetDir);
          const dist = Math.hypot(p.x - wp.x, p.y - wp.y);
          if (dist < bestDist) {
            bestDist = dist;
            CS.wiring.snapNodeId = cand.id;
            CS.wiring.snapDir = targetDir;
            CS.wiring.curWorldX = p.x;
            CS.wiring.curWorldY = p.y;
          }
        }
        if (CS.wiring.snapNodeId) {
          DOM.nodesLayer.querySelector(`[data-port-node="${CS.wiring.snapNodeId}"][data-port-dir="${CS.wiring.snapDir}"]`)?.classList.add("is-snap");
        }
        renderEdgesSvg();
      }
    });

    const finishPointer = (e) => {
      if (!dragCtx || e.pointerId !== dragCtx.pointerId) return;
      const ctx = dragCtx;
      dragCtx = null;
      vp.classList.remove("is-panning");

      if (ctx.mode === "node-drag" && ctx.moved) {
        fullRenderCanvas();
        persistOpenTabs();
      } else if (ctx.mode === "node-drag" && !ctx.moved && !ctx.withModifier && ctx.clickedNodeId) {
        const clicked = getNodeById(ctx.clickedNodeId);
        if (clicked && clicked.type === "article_plan") {
          openArticlePlanWidePage(clicked.id);
        }
      } else if (ctx.mode === "marquee") {
        const x1 = Math.min(ctx.startX, e.clientX);
        const y1 = Math.min(ctx.startY, e.clientY);
        const x2 = Math.max(ctx.startX, e.clientX);
        const y2 = Math.max(ctx.startY, e.clientY);
        ctx.box.remove();
        if (x2 - x1 > 6 && y2 - y1 > 6) {
          const w1 = screenToWorld(x1, y1);
          const w2 = screenToWorld(x2, y2);
          CS.graph.selectedIds = CS.graph.nodes
            .filter((n) => n.x + (n.w || 320) >= w1.x && n.x <= w2.x && n.y + (n.h || 240) >= w1.y && n.y <= w2.y)
            .map((n) => n.id);
          renderWorldNodes();
          renderFloatingOverlays();
        }
      } else if (ctx.mode === "wiring" && CS.wiring) {
        const w = CS.wiring;
        CS.wiring = null;
        DOM.root.classList.remove("is-wiring");
        DOM.nodesLayer.querySelectorAll(".ic-port-zone.is-snap").forEach((el) => el.classList.remove("is-snap"));

        if (w.snapNodeId) {
          pushUndo();
          if (w.fromDir === "out") ensureEdge(w.fromNodeId, w.snapNodeId);
          else ensureEdge(w.snapNodeId, w.fromNodeId);
          fullRenderCanvas();
          persistOpenTabs();
        } else {
          renderEdgesSvg();
          openContextMenu(e.clientX, e.clientY, screenToWorld(e.clientX, e.clientY), { nodeId: w.fromNodeId, dir: w.fromDir });
        }
      }
    };

    vp.addEventListener("pointerup", finishPointer);
    vp.addEventListener("pointercancel", finishPointer);

    DOM.minimap.addEventListener("pointerdown", (e) => {
      const meta = DOM.minimap._mapMeta;
      if (!meta) return;
      const r = DOM.minimap.getBoundingClientRect();
      const targetWX = meta.minX + (e.clientX - r.left - meta.offX) / meta.scale;
      const targetWY = meta.minY + (e.clientY - r.top - meta.offY) / meta.scale;
      CS.vx = meta.vRect.width * 0.5 - targetWX * CS.vk;
      CS.vy = meta.vRect.height * 0.5 - targetWY * CS.vk;
      applyViewportTransform();
    });

    window.addEventListener("pointerdown", (e) => {
      if (DOM.ctxMenu && !DOM.ctxMenu.contains(e.target)) closeContextMenu();
      if (DOM.allTabsPop && !DOM.allTabsPop.contains(e.target) && !e.target.closest("#tb-all-tabs")) {
        closeAllTabsPopover();
      }
    });

    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if(CS.stageView==="canvas") void window.HandrawParameterCanvas?.saveCurrent();
        else saveCurrentWorkflow(false);
        return;
      }

      if(CS.stageView==="canvas") return;
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) {
        if (e.key === "Escape") e.target.blur();
        return;
      }

      if (e.code === "Space") {
        CS.spaceHeld = true;
        vp.classList.add("is-pan-tool");
      } else if (e.key === "Escape") {
        closeContextMenu();
        closeAllTabsPopover();
        CS.selectedEdgeId = null;
        renderEdgesSvg();
        renderFloatingOverlays();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        deleteSelectedItems();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redoGraph();
        else undoGraph();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redoGraph();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") {
        e.preventDefault();
        duplicateNodes(CS.graph.selectedIds);
      }
    });

    window.addEventListener("keyup", (e) => {
      if (e.code === "Space") {
        CS.spaceHeld = false;
        vp.classList.toggle("is-pan-tool", CS.toolMode === "pan");
      }
    });

    window.addEventListener("resize", () => {
      positionFloatingOverlays();
      renderMinimap();
      updateTabScrollButtons();
    });
  }

  function mountStudioShell() {
    DOM.root = document.getElementById("studio-app-root");
    DOM.root.innerHTML = `
      <div class="qc-entry-bar" id="ic-entry-bar"></div>
      <header class="ic-workbench-bar" id="ic-workbench-bar"></header>
      <div class="ic-stage-wrap" id="ic-stage-wrap">
        <section class="ic-quick-stage" id="ic-quick-stage" style="display:none;"></section>
        <section class="pc-stage" id="ic-parameter-stage" style="display:none;"></section>
        <div class="ic-canvas-stage" id="ic-canvas-stage" style="display:none;">
          <div class="ic-viewport is-pan-tool" id="ic-viewport">
            <div class="ic-grid-layer" id="ic-grid-layer"></div>
            <div class="ic-world" id="ic-world">
              <svg class="ic-edges-svg" id="ic-edges-svg"></svg>
              <div id="ic-nodes-layer"></div>
            </div>
          </div>
          <div class="ic-floating-overlay-layer" id="ic-overlay-layer"></div>
          <aside class="ic-shelf-drawer" id="ic-shelf-drawer"></aside>
          <div class="ic-canvas-toolstrip" id="ic-canvas-toolstrip"></div>
          <div class="ic-minimap" id="ic-minimap"></div>
          <div class="ic-bottom-right-dock" id="ic-bottom-right"></div>
        </div>
        <section class="ic-preview-stage" id="ic-preview-stage" style="display:none;"></section>
        <section class="ic-history-stage" id="ic-history-stage" style="display:none;"></section>
        <section class="ic-workflows-stage" id="ic-workflows-stage" style="display:none;"></section>
      </div>
    `;

    DOM.entryBar = document.getElementById("ic-entry-bar");
    DOM.quickStage = document.getElementById("ic-quick-stage");
    DOM.workbenchBar = document.getElementById("ic-workbench-bar");
    DOM.stageWrap = document.getElementById("ic-stage-wrap");
    DOM.canvasStage = document.getElementById("ic-canvas-stage");
    DOM.parameterStage = document.getElementById("ic-parameter-stage");
    DOM.viewport = document.getElementById("ic-viewport");
    DOM.grid = document.getElementById("ic-grid-layer");
    DOM.world = document.getElementById("ic-world");
    DOM.edgesSvg = document.getElementById("ic-edges-svg");
    DOM.nodesLayer = document.getElementById("ic-nodes-layer");
    DOM.overlayLayer = document.getElementById("ic-overlay-layer");
    DOM.shelf = document.getElementById("ic-shelf-drawer");
    DOM.canvasToolstrip = document.getElementById("ic-canvas-toolstrip");
    DOM.minimap = document.getElementById("ic-minimap");
    DOM.bottomRight = document.getElementById("ic-bottom-right");
    DOM.previewStage = document.getElementById("ic-preview-stage");
    DOM.historyStage = document.getElementById("ic-history-stage");
    DOM.workflowsStage = document.getElementById("ic-workflows-stage");
  }

  function syncCatalogFromShared() {
    Catalog.resourceMap = App.resourceMap;
    Catalog.styles = App.styles;
    Catalog.layouts = App.layouts;
    Catalog.colors = App.colors;
    Catalog.tones = App.options?.tones || [];
    Catalog.modes = (App.options?.modes || []).filter((m) => m.id !== "photo");
    Catalog.ratios = App.options?.ratios || [];
    Catalog.moods = [...new Set((App.options?.moods || []).map(normalizeMoodLabel).filter(Boolean))];
  }

  async function boot() {
    try {
      await S.initApp("studio", () => {
        const scopeChanged = hydrateLocalScopedState();
        syncCatalogFromShared();
        hydrateCloudStudioWorkspace().then(async () => {
          if (DOM.root && DOM.nodesLayer) {
            if (scopeChanged) await hydrateTabsAndUrlParams();
            renderShelfDrawer();
            fullRenderCanvas();
            if (CS.stageView === "workflows") renderWorkflowsStage();
            if (CS.stageView === "history") renderHistoryStage();
            if (CS.stageView === "preview") renderFullPreviewStage();
          }
        });
      });
      hydrateLocalScopedState();
      syncCatalogFromShared();
      await hydrateCloudStudioWorkspace();

      const [cfgRes, benchRes] = await Promise.all([
        fetch("/api/studio/config").catch(() => null),
        fetch("/data/benchmark-assets.json").catch(() => null)
      ]);

      if (cfgRes && cfgRes.ok) {
        CS.serverCfg = await cfgRes.json();
      }
      configureGenerationEngine();
      const defaultOtherAssets = [
        { id: "OT-001", name_zh: "朱砂闲章与宣纸底纹", desc_zh: "东方手绘版面装饰印章参考", image: "/images/poster-demo-autumn-equinox.webp", cat: "other", custom: false },
        { id: "OT-002", name_zh: "手账胶带与便签边框", desc_zh: "拼贴感信息卡装饰元素参考", image: "/images/A_001-016.webp", cat: "other", custom: false }
      ];
      if (benchRes && benchRes.ok) {
        const rawBench = await benchRes.json();
        if (Array.isArray(rawBench?.assets)) {
          const arr = rawBench.assets;
          const otherFromJson = arr.filter((x) => x.cat === "other").map((x) => ({ ...x, custom: x.is_custom }));
          Catalog.benchmarkAssets = {
            characters: arr.filter((x) => x.cat === "characters").map((x) => ({ ...x, custom: x.is_custom })),
            props: arr.filter((x) => x.cat === "props").map((x) => ({ ...x, custom: x.is_custom })),
            scenes: arr.filter((x) => x.cat === "scenes").map((x) => ({ ...x, custom: x.is_custom })),
            other: otherFromJson.length ? otherFromJson : defaultOtherAssets
          };
        } else if (rawBench && typeof rawBench === "object") {
          Catalog.benchmarkAssets = {
            characters: rawBench.characters || [],
            props: rawBench.props || [],
            scenes: rawBench.scenes || [],
            other: rawBench.other && rawBench.other.length ? rawBench.other : defaultOtherAssets
          };
        }
      } else {
        Catalog.benchmarkAssets.other = defaultOtherAssets;
      }

      mountStudioShell();
      // A completed import from a previous tab/session may be recovered without
      // overwriting the article the user is currently editing.
      window.HandrawTaskJourney?.setRecoveredImportHandler(async (result) => {
        if (!App.state?.loggedIn) throw new Error("请先登录原账号，才能恢复导入文章");
        ensureMyArticlesInitialized();
        const now = Date.now();
        const id = E.uid("art");
        const title = String(result.title || "导入文章").trim() || "导入文章";
        const markdown = String(result.markdown || "");
        if (!markdown.trim()) throw new Error("导入结果为空，未创建文章");
        const art = {
          id, articleTitle: title, markdown, cards: [], status: "ready",
          createdAtMs: now, updatedAtMs: now, timeLabel: formatArticleTimeLabel(now),
          linkedTabId: null, linkedPlanNodeId: null, style1: "FA-001",
          layout: "IG-001", coverRatio: "2.35:1", inlineRatio: "4:3", runCount: 0
        };
        CS.myArticles.unshift(art);
        persistMyArticles();
        openUnifiedArticleEditor(id, {renderNow:true});
        renderTopAndBottomDocks();
        toast("已将恢复的文档作为新文章打开，未覆盖原有文章");
        return true;
      });
      await hydrateTabsAndUrlParams();
      renderShelfDrawer();
      fullRenderCanvas();
      bindViewportInteractions();
      if (CS.stageView === "canvas") requestAnimationFrame(() => fitView());
      resumePendingCloudTasks();
    } catch (err) {
      console.error("[Handraw Canvas Studio v4 Boot Error]", err);
      const r = document.getElementById("studio-app-root");
      if (r) {
        r.innerHTML = `<div style="padding:48px;text-align:center;color:#dc2626;">
          <h2 style="margin:0 0 10px;">创作台启动失败</h2>
          <p style="margin:0 0 18px;">${esc(err.message || err)}</p>
          <button type="button" class="btn btn-primary" id="studio-boot-retry">重新连接并重试</button>
        </div>`;
        const retry = r.querySelector("#studio-boot-retry");
        if (retry) retry.onclick = () => {
          retry.disabled = true;
          retry.textContent = "正在重试…";
          boot();
        };
      }
    }
  }

  window.HANDRAW_STUDIO = window.HANDRAW_STUDIO || {};
  window.HANDRAW_STUDIO.clearControlWorkspaceResults = clearControlWorkspaceResults;
  window.HANDRAW_STUDIO.cancelActiveBatchGeneration = cancelActiveBatchGeneration;
  window.HANDRAW_STUDIO.getCacheScope = () => activeCacheScope;
  window.HANDRAW_STUDIO.getEngineMode = () => CS.engineMode;
  window.HANDRAW_STUDIO.openReferenceAssetPickerModal = openAssetPickerModal;
  window.HANDRAW_STUDIO.openLoopMultiPickerModal = openLoopMultiPickerModal;
  window.HANDRAW_STUDIO.openSkillFieldPickerModal = openSkillFieldPickerModal;
  window.HANDRAW_STUDIO.openImageLightbox = openImageLightbox;
  window.HANDRAW_STUDIO.getBatchParts = getBatchParts;
  window.HANDRAW_STUDIO.ensureBatchTab = ensureBatchTab;
  window.HANDRAW_STUDIO.resolveShareTitle = resolveShareTitle;
  window.HANDRAW_STUDIO.openHistoryStage = openHistoryPage;
  window.HANDRAW_STUDIO.getHistory = () => CS.generationHistory;
  window.HANDRAW_STUDIO.setHistory = (list) => {
    CS.generationHistory = list;
    writeJsonStorage(HISTORY_STORAGE_KEY, list);
    if (CS.stageView === "history") renderHistoryStage();
  };
  if (window.__HANDRAW_TESTING__ === true) {
    window.CS = CS;
    Object.defineProperty(CS, "activeArticleDraft", {
      get() { return CS.articleEditorDraft; },
      set(v) { CS.articleEditorDraft = v; },
      configurable: true
    });
    window.renderArticleEditorPage = renderArticleEditorPage;
    window.renderFullPreviewStage = renderFullPreviewStage;
    window.HANDRAW_STUDIO_TESTING = {
      readScopedCache: (key, fallback = null) => readJsonStorage(key, fallback),
      writeScopedCache: (key, value) => writeJsonStorage(key, value),
      switchScope: (scope) => {
        resetStudioMemoryForScope(String(scope || "guest"));
        return { scope: activeCacheScope, epoch: cacheScopeEpoch };
      },
      getSnapshot: () => ({
        scope: activeCacheScope,
        epoch: cacheScopeEpoch,
        tabs: CS.tabs.length,
        graphNodes: CS.graph.nodes.length,
        articles: Array.isArray(CS.myArticles) ? CS.myArticles.length : null,
        history: Array.isArray(CS.generationHistory) ? CS.generationHistory.length : null,
        uploads: Array.isArray(CS.customUploads) ? CS.customUploads.length : null
      }),
      setPrivateState: (patch) => Object.assign(CS, patch || {}),
      getHistory: () => (Array.isArray(CS.generationHistory) ? JSON.parse(JSON.stringify(CS.generationHistory)) : null),
      getTabs: () => CS.tabs,
      getGraph: () => CS.graph,
      applyDurableTaskResult,
      isStaleScope,
      ensureStableRequestId,
      generateSinglePlanCard,
      resolveArticleTarget,
      syncArticleEditorDraftToHistory,
      planUnifiedArticleDraft,
      flushCloudArticlesSync,
      selectArticleCardImage,
      articleCloudPayload,
      loadArticleDocument,
      hydrateCloudStudioWorkspace,
      loadMoreStudioHistory,
      runOutputControlNode,
      pollCloudTask,
      resumePendingCloudTasks,
      upsertHistoryEntry,
      normalizeHistoryEntry,
      resolveShareTitle,
      formatParamValue,
      formatParamList
    };
  }

  boot();
})();
