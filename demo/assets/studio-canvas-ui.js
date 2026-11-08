/* Issue #129: view-only Canvas presentation selectors.
 * Project Graph/RunFact/Artifact live in their existing owners, never here.
 */
(function(root,factory){
  "use strict";
  const api=factory();
  root.HandrawCanvasUI=api;
  if(typeof module==="object"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(){
  "use strict";
  const STATUS_LABELS=Object.freeze({
    pending:"排队中",generating:"生成中",running:"生成中",success:"已完成",failed:"失败",
    partial:"部分完成",cancel_requested:"正在停止",cancelled:"已取消",
    unknown:"远端待核实"
  });
  function label(status){return STATUS_LABELS[status]||STATUS_LABELS.unknown;}
  function mediaUrl(value){
    const url=String(value||"").trim();
    return (url.startsWith("/")&&!url.startsWith("//")&&!url.includes("\\"))||
      /^https:\/\/[^/\s]+(?:\/|$)/i.test(url)?url:"";
  }
  function slotIndex(item,source){
    const explicit=Number(item?.slotIndex??item?.batchIndex);
    if(Number.isInteger(explicit)&&explicit>=0)return explicit;
    const pos=Number(item?.position);
    if(!Number.isInteger(pos)||pos<0)return -1;
    return source==="web"?Math.floor(pos/1000):pos;
  }
  function slotSummary(items,count,source="web"){
    const rows=Array.from({length:Math.max(0,Math.min(200,Number(count)||0))},
      (_,index)=>({index,status:"pending",imageUrl:"",mediaId:"",runItemId:"",error:""}));
    const priority={pending:0,unknown:1,cancelled:2,failed:3,generating:4,success:5};
    for(const item of Array.isArray(items)?items:[]){
      const index=slotIndex(item,source);
      if(index<0||index>=rows.length)continue;
      const status=String(item.status||"unknown");
      const success=status==="success"&&Boolean(item.mediaId||item.media_id)&&
        Boolean(mediaUrl(item.imageUrl||item.image_url));
      const current=rows[index];
      const next=success?"success":status;
      if((priority[next]??1)<=(priority[current.status]??0))continue;
      rows[index]={
        index,status:next,
        imageUrl:success?mediaUrl(item.imageUrl||item.image_url):"",
        mediaId:success?String(item.mediaId||item.media_id):"",
        runItemId:String(item.id||item.runItemId||""),
        error:next==="failed"?String(item.error||item.error_message||"生成失败"):""
      };
    }
    return rows;
  }
  function summarize(graph,projectRun){
    return (graph?.nodes||[]).filter(node=>node.type==="output_control")
      .map(node=>{
        const runId=String(node.data?.runId||node.data?.studio2RunSnapshot?.runId||"");
        const projection=runId?projectRun(node):null;
        return {
          controlId:node.id,runId,projection:projection||null,
          state:projection?.viewStatus||"unknown",
          text:projection?label(projection.viewStatus):
            runId?"远端状态待核实":node.data?.status==="generating"?
              "正在提交 · 远端待核实":"未运行",
          total:projection?.total??null,
          done:projection?.succeeded??null,
          failed:projection?.failed??null,
          queued:projection?.queued??null,
          generating:projection?.generating??null,
          isTerminal:Boolean(projection?.isTerminal)
        };
      });
  }
  function galleryState(node,projection){
    const local=Array.isArray(node?.data?.items)?node.data.items:[];
    const expected=Math.max(1,Math.min(200,Number(node?.data?.totalTarget)||local.length||1));
    const slots=Array.from({length:expected},(_,index)=>{
      const it=local[index];
      const url=mediaUrl(it?.imageUrl);
      return {index,status:url?"success":it?.failed?"failed":
        node?.data?.status==="generating"?"generating":"pending",
        imageUrl:url,error:String(it?.error||"")};
    });
    // Server-owned RunItem rows always win over optimistic/local slot state.
    if(Array.isArray(projection?.slots)){
      for(const s of projection.slots)if(Number.isInteger(s.index)&&s.index<expected&&s.index>=0){
        if((s.status==="pending"||s.status==="unknown")&&slots[s.index].imageUrl)continue;
        slots[s.index]={
          index:s.index,status:s.status,
          imageUrl:s.status==="success"?mediaUrl(s.imageUrl):"",
          error:String(s.error||"")
        };
      }
    }
    const counts=slots.reduce((acc,row)=>{
      const k=row.status==="success"?"success":row.status==="failed"?"failed":
        row.status==="generating"?"generating":"pending";
      acc[k]++;return acc;
    },{success:0,failed:0,generating:0,pending:0});
    return {slots,counts,expected};
  }
  function mayRetry(slot,projection){
    return slot?.status==="failed"&&Boolean(projection?.runId)&&
      Boolean(projection?.isTerminal)&&Boolean(projection?.canRetry);
  }

  const expanded=new Set();
  function expandedGallery(id){return expanded.has(String(id));}
  function toggleGallery(id){const key=String(id);if(expanded.has(key))expanded.delete(key);else expanded.add(key);return expanded.has(key);}
  function htmlEscape(s){return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}
  function galleryHtml(node,projection){
    const state=galleryState(node,projection),isExpanded=expandedGallery(node.id);
    const c=state.counts,slots=state.slots,first=slots.find(x=>x.imageUrl);
    let out='<div class="ic129-group-head"><strong>系列结果组 · '+state.expected+' 张</strong>'+
      '<span role="status">'+c.success+' 成功 · '+c.failed+' 失败 · '+
      (c.generating+c.pending)+' 进行中/待确认</span></div>';
    if(first&&!isExpanded)out+='<div class="ic129-group-cover"><img loading="lazy" src="'+htmlEscape(first.imageUrl)+'" alt="系列结果封面" data-disp-zoom="'+htmlEscape(first.imageUrl)+'" />'+
      '<span class="ic129-cover-count">'+state.expected+' 张</span></div>';
    if(isExpanded){
      out+='<div class="ic129-group-grid" role="list" aria-label="系列全部槽位">';
      for(const slot of slots){
        out+='<div class="ic129-result-slot ic129-slot-'+htmlEscape(slot.status)+'" role="listitem" data-slot="'+slot.index+'">'+
          '<span class="ic129-slot-index">#'+(slot.index+1)+' · '+htmlEscape(label(slot.status))+'</span>';
        if(slot.imageUrl){
          out+='<img loading="lazy" src="'+htmlEscape(slot.imageUrl)+'" alt="第'+(slot.index+1)+'张成图" data-disp-zoom="'+htmlEscape(slot.imageUrl)+'" />'+
            '<div class="ic129-result-actions"><a href="'+htmlEscape(slot.imageUrl)+'" download="handraw-'+(slot.index+1)+'.webp">下载</a>'+
            '<button type="button" data-disp-variant="'+htmlEscape(node.id)+'">生成变体</button>'+
            '<button type="button" data-disp-reference="'+htmlEscape(node.id)+'" data-slot="'+slot.index+'">作为参考</button></div>';
        }else{
          out+='<div class="ic129-slot-placeholder">'+htmlEscape(slot.error||label(slot.status))+'</div>';
          if(mayRetry(slot,projection))out+='<button type="button" data-disp-retry-slot="'+htmlEscape(node.id)+
            '" data-slot="'+slot.index+'">仅重试此张（可能计费）</button>';
        }
        out+='</div>';
      }
      out+='</div>';
    }
    out+='<div class="ic129-result-actions"><button type="button" data-disp-toggle="'+htmlEscape(node.id)+
      '" aria-expanded="'+isExpanded+'">'+(isExpanded?'收起结果':'展开全部槽位')+'</button>'+
      '<button type="button" data-disp-open-gal="'+htmlEscape(node.id)+'">查看图集</button>'+
      '<button type="button" data-disp-zip="'+htmlEscape(node.id)+'">下载 ZIP</button></div>';
    return out;
  }
  function ensurePanel(stage,id,tag){
    let el=stage.querySelector("#"+id);
    if(!el){el=stage.ownerDocument.createElement(tag||"div");el.id=id;stage.appendChild(el);}
    return el;
  }
  function renderWorkspace(options){
    const stage=options?.stage;
    if(!stage)return;
    const graph=options.graph||{nodes:[],edges:[],selectedIds:[]};
    const active=options.activeTab||null;
    const selected=(graph.nodes||[]).find(n=>(graph.selectedIds||[]).includes(n.id));
    const runRows=options.runs||[];
    const isCanvas=Boolean(options.isCanvas);
    const top=ensurePanel(stage,"canvas-129-topbar","nav");
    const side=ensurePanel(stage,"canvas-129-inspector","aside");
    const bottom=ensurePanel(stage,"canvas-129-taskbar","section");
    const empty=ensurePanel(stage,"canvas-129-empty","section");
    for(const el of [top,side,bottom,empty])el.hidden=!isCanvas;
    if(!isCanvas)return;
    const topHtml='<div class="ic129-project-name">'+htmlEscape(active?.title||"新项目")+'</div>'+
      '<span class="ic129-save-state" role="status">'+htmlEscape(options.saveText||"仅本机")+'</span>'+
      '<button type="button" data-c129="save">保存项目</button>'+
      '<button type="button" data-c129="simple">简洁编辑</button>'+
      '<button type="button" data-c129="undo">撤销</button>'+
      '<button type="button" data-c129="redo">重做</button>'+
      '<button type="button" class="ic129-primary" data-c129="run">▶ '+(selected?.type==="output_control"?"运行选中分支":"运行画布")+'</button>'+
      '<button type="button" data-c129="inspector" aria-expanded="'+inspectorOpen+'">属性 '+(inspectorOpen?'‹':'›')+'</button>';
    if(top.innerHTML!==topHtml)top.innerHTML=topHtml;
    let inspectorHtml='<div class="ic129-inspector-title"><strong>属性</strong><button type="button" data-c129="ai" aria-pressed="'+(inspectorTab==="ai")+'">AI 建议</button></div>';
    if(inspectorTab==="ai"){
      inspectorHtml+='<div class="ic129-inspector-info"><h3>AI 创作导演</h3><p>此处提供当前项目和选中节点的创作提示。结构化 GraphPatch 审阅与应用由 #126 实现；不会在这里直接修改执行图或自动发起收费生成。</p>'+
        '<p>可先调整主题、画风与素材，再运行明确选择的分支。</p></div>';
    }else if(selected){
      const d=selected.data||{};
      inspectorHtml+='<div class="ic129-inspector-info"><h3>'+htmlEscape(selected.title||selected.type)+'</h3>'+
        '<p>节点 ID：<code>'+htmlEscape(selected.id)+'</code></p>'+
        '<p>类型：'+htmlEscape(selected.type)+' · 已选 '+(graph.selectedIds||[]).length+' 个</p>';
      if(selected.type==="text_input")inspectorHtml+='<p>主题：'+htmlEscape(String(d.text||"").slice(0,200)||"未填写")+'</p><button type="button" data-c129="edit">编辑文案</button>';
      else if(selected.type==="skill_params")inspectorHtml+='<p>画风：'+htmlEscape(d.style1||"待选")+' · 图型：'+htmlEscape(d.layout||"待选")+'</p>'+
        '<button type="button" data-c129="style">选择画风</button><button type="button" data-c129="layout">选择图型</button>';
      else if(selected.type==="asset")inspectorHtml+='<p>参考素材：'+(d.items?.length||0)+' 张</p><button type="button" data-c129="asset">选择素材</button>';
      else if(selected.type==="output_control")inspectorHtml+='<p>比例：'+htmlEscape(d.ratio||"默认")+' · 数量：'+htmlEscape(d.count||"按方案")+'</p><button type="button" data-c129="run">运行此分支</button>';
      else if(selected.type==="output_display")inspectorHtml+='<p>输出图像会保留原始媒体引用与上游运行记录，不在此面板重写。</p>';
      inspectorHtml+='</div>';
    }else{
      inspectorHtml+='<div class="ic129-inspector-info"><p>选中节点后编辑其配置。复杂参数保留在节点详情，运行与作品状态由服务端提供。</p><p>Shift / Ctrl 多选，空白区域框选，双击空白添加节点。</p></div>';
    }
    if(side.innerHTML!==inspectorHtml)side.innerHTML=inspectorHtml;
    side.hidden=!inspectorOpen;
    let taskHtml='<div class="ic129-task-head"><strong>任务队列</strong><span>'+runRows.length+' 个执行分支</span>'+
      '<button type="button" data-c129="tasks" aria-expanded="'+taskExpanded+'">'+(taskExpanded?'收起':'展开')+'</button></div>';
    if(runRows.length){
      taskHtml+='<div class="ic129-task-chips">';
      for(const row of runRows){
        taskHtml+='<div class="ic129-task-chip"><span>'+htmlEscape(row.text)+'</span>'+
          (row.total===null?'':('<span>'+row.done+'/'+row.total+' 已确认</span>'))+'</div>';
      }
      taskHtml+='</div>';
      if(taskExpanded){
        taskHtml+='<div class="ic129-task-details">';
        for(const row of runRows){
          taskHtml+='<div><strong>'+htmlEscape(row.runId||row.controlId)+'</strong> · '+htmlEscape(row.text)+
            (row.total===null?'':(' · 成功 '+row.done+' / 失败 '+row.failed+' / 排队 '+row.queued+' / 生成 '+row.generating))+
            (!row.isTerminal?'<button type="button" data-c129="stop" data-control="'+htmlEscape(row.controlId)+'">停止未提交任务</button>':'')+
            '</div>';
        }
        taskHtml+='</div>';
      }
    }else taskHtml+='<p>暂无已提交任务。这里会显示真实 Run 的进度，不推测成功张数。</p>';
    if(bottom.innerHTML!==taskHtml)bottom.innerHTML=taskHtml;
    const isEmpty=!graph.nodes?.length&&Boolean(active);
    empty.hidden=!isEmpty;
    if(isEmpty&&!empty.querySelector("form")){
      empty.innerHTML='<div class="ic129-empty-card"><h2>从一个想法开始创作</h2>'+
        '<p>先输入主题，自动生成可运行的单图工作流，不需要手工连线。</p>'+
        '<form id="canvas-129-quick-form"><input name="subject" placeholder="描述你想创作的画面" required maxlength="4000" aria-label="创作主题" />'+
        '<button type="submit" class="ic129-primary">创建单图工作流</button></form>'+
        '<div class="ic129-empty-actions"><button type="button" data-c129="add-asset">添加素材</button>'+
        '<button type="button" data-c129="template">应用模板</button></div></div>';
      empty.querySelector("form").onsubmit=e=>{
        e.preventDefault();options.onStart?.(empty.querySelector('input[name="subject"]').value);
      };
    }
    const bind=(el)=>{
      el.querySelectorAll("[data-c129]").forEach(btn=>{
        btn.onclick=(e)=>{e.stopPropagation();const action=btn.dataset.c129;
          if(action==="inspector"){inspectorOpen=!inspectorOpen;renderWorkspace(options);}
          else if(action==="ai"){inspectorTab=inspectorTab==="ai"?"props":"ai";renderWorkspace(options);}
          else if(action==="tasks"){taskExpanded=!taskExpanded;renderWorkspace(options);}
          else if(action==="stop")options.onStop?.(btn.dataset.control);
          else options.onAction?.(action,selected);
        };
      });
    };
    bind(top);bind(side);bind(bottom);if(isEmpty)bind(empty);
  }
  let inspectorOpen=true,inspectorTab="props",taskExpanded=false;

  return Object.freeze({label,mediaUrl,slotIndex,slotSummary,summarize,galleryState,mayRetry,expandedGallery,toggleGallery,galleryHtml,renderWorkspace});
});
