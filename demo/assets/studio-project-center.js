/* Studio2 Project Center: pure view model and accessible HTML.
 * Project != Workflow template != generated Run or public Work.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.HandrawStudioProjectCenter = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";
  const KINDS = Object.freeze({ image: "图片创作", series: "系列创作", article: "文章配图" });
  function escapeText(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[ch]);
  }
  function safeDate(value) {
    const ts = Date.parse(String(value || ""));
    if (!Number.isFinite(ts)) return "尚未同步时间";
    return new Date(ts).toLocaleString("zh-CN", {year:"numeric", month:"2-digit", day:"2-digit",hour:"2-digit",minute:"2-digit"});
  }
  function isLocallyUnsynced(tab) {
    return Boolean(tab && (tab.projectPending || tab.projectCopyPending ||
      ["local_only", "error", "conflict", "saving"].includes(tab.projectSaveState)));
  }
  function localDrafts(tabs) {
    return (Array.isArray(tabs) ? tabs : [])
      .filter(t => t && !String(t.blueprint || "").includes("article") && isLocallyUnsynced(t))
      .map(t => ({
        id: String(t.id || ""), projectId: String(t.projectId || ""),
        kind: t.batchStart || ["loop","loop_100","series","xhs","ip_story","style_ab"].includes(t.blueprint)
          ? "series" : "image",
        title: String(t.title || "未命名草稿"), saveState: t.projectSaveState || "local_only"
      })).filter(t => t.id);
  }
  function classifyRestore(localTab, cloudProject) {
    if (!localTab) return "open-cloud";
    if (isLocallyUnsynced(localTab)) return "keep-local";
    if (Number(localTab.projectRevision || 0) >= Number(cloudProject?.revision || 0)) {
      return "activate-local";
    }
    return "refresh-confirmed";
  }
  function model({projects=[], tabs=[], query="", loading=false, error="", loggedIn=false,
                  hasMore=false, loadingMore=false}={}) {
    const needle = String(query).trim().toLowerCase();
    const includes = item => !needle || [item.title, KINDS[item.kind], item.projectId].some(
      v => String(v || "").toLowerCase().includes(needle));
    const drafts = localDrafts(tabs).filter(includes);
    const cloud = (Array.isArray(projects) ? projects : [])
      .filter(p => p && p.id && includes({title:p.title, kind:p.kind, projectId:p.id}));
    return {drafts,cloud,query:String(query),loading,error,loggedIn,hasMore,loadingMore};
  }
  function localCard(d) {
    const x=escapeText;
    const detail = d.saveState === "conflict" ? "与云端版本有冲突，打开后可另存副本" :
      d.saveState === "error" ? "上次同步失败，打开后可重试" : "仍有未确认的本机修改，优先保留";
    return "<article class='ic-pc-card is-local'><span class='ic-pc-tag'>仅本机 · "+
      x(KINDS[d.kind]||"画布")+"</span><h3>"+x(d.title)+"</h3><p>"+detail+"</p>"+
      "<button type='button' class='btn btn-sm btn-primary' data-pc-local='"+x(d.id)+
      "'>继续本机草稿</button></article>";
  }
  function cloudCard(p) {
    const x=escapeText;
    const editable=p.authority==="graph";
    const authority=p.authority==="article"?"文章文档":p.authority==="spec"?"结构化方案":"画布";
    return "<article class='ic-pc-card'><span class='ic-pc-tag'>云端已保存 · "+
      x(KINDS[p.kind]||"项目")+"</span><h3>"+x(p.title||"未命名创作")+"</h3>"+
      "<p>更新于 "+x(safeDate(p.updatedAt))+"</p><div class='ic-pc-card-foot'>"+
      "<span>版本 "+x(p.revision||1)+" · "+x(authority)+"</span>"+
      (editable ? "<button type='button' class='btn btn-sm btn-primary' data-pc-open='"+x(p.id)+
      "'>继续编辑</button>" : "<span title='等待文章/结构化方案编辑器接入'>待编辑器接入</span>")+
      "</div></article>";
  }
  function render(state) {
    const s=model(state),x=escapeText;
    const cards=[
      ["image","01 / IMAGE","图片创作","主题、画风与图型，快速生成一张图"],
      ["series","02 / SERIES","系列创作","多张计划、统一风格、并行执行"],
      ["article","03 / ARTICLE","文章配图","文章正文、封面及正文插画"],
      ["workflow","04 / WORKFLOW","从工作流开始","选择模板或导入 JSON 进入画布"]
    ].map(([id,kicker,title,desc])=>
      "<button type='button' class='ic-pc-new-card' data-pc-new='"+id+"'>"+
      "<span class='ic-pc-new-kicker'>"+kicker+"</span><strong>"+title+
      "</strong><span>"+desc+"</span></button>").join("");
    let content="";
    if (s.drafts.length) {
      content+="<div class='ic-pc-subtitle'>本机待同步草稿 · "+s.drafts.length+
        "</div><div class='ic-pc-grid'>"+s.drafts.map(localCard).join("")+"</div>";
    }
    if (!s.loggedIn) {
      content+="<div class='ic-pc-empty' role='status'><strong>登录后查看云端项目</strong>"+
        "<p>本机草稿仍可继续编辑，登录后同步到个人账号。</p>"+
        "<button type='button' class='btn btn-primary btn-sm' data-pc-login>登录并查看项目</button></div>";
    } else if (s.loading) {
      content+="<div class='ic-pc-empty' role='status'>正在读取你的云端项目…</div>";
    } else if (s.error) {
      content+="<div class='ic-pc-empty' role='alert'><strong>云端项目读取失败</strong>"+
        "<p>"+x(s.error)+"</p><button type='button' class='btn btn-sm' data-pc-refresh>重试</button></div>";
    } else if (s.cloud.length) {
      content+="<div class='ic-pc-subtitle'>已加载云端项目 · "+s.cloud.length+
        "</div><div class='ic-pc-grid'>"+s.cloud.map(cloudCard).join("")+"</div>"+
        (s.hasMore ? "<div class='ic-pc-more'><button type='button' class='btn btn-sm' data-pc-more"+
         (s.loadingMore?" disabled":"")+">"+(s.loadingMore?"加载中…":"加载更多项目")+"</button></div>" : "");
    } else if (!s.drafts.length) {
      content+="<div class='ic-pc-empty' role='status'><strong>"+
        (s.query?"没有匹配的项目":"还没有云端项目")+
        "</strong><p>编辑后自动保存；状态显示「云端已保存」才代表服务器确认。</p></div>";
    }
    return "<div class='ic-pc-scroll'><div class='ic-pc-inner'>"+
      "<header class='ic-pc-header'><div><p class='ic-pc-eyebrow'>HANDRAW STUDIO / PROJECTS</p>"+
      "<h1>创作项目</h1><p>继续编辑已保存的项目，或从一个新的想法开始。"+
      "项目草稿、生图历史和工作流模板分别管理。</p></div>"+
      "<button type='button' class='btn btn-sm' data-pc-refresh>刷新项目</button></header>"+
      "<div class='ic-pc-new-grid' role='group' aria-label='开始创作'>"+cards+"</div>"+
      "<section class='ic-pc-library' aria-label='我的项目'><div class='ic-pc-toolbar'>"+
      "<div><h2>最近项目</h2><p>云端与本机待同步草稿会明确区分。</p></div>"+
      "<input type='search' id='pc-project-search' class='hw-input' placeholder='搜索项目名称…'"+
      " aria-label='搜索项目名称' value='"+x(s.query)+"' /></div>"+
      content+"</section></div></div>";
  }
  return {render,model,localDrafts,classifyRestore,isLocallyUnsynced};
});
