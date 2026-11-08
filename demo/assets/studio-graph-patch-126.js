/* Studio 2.0 #126: user-reviewed GraphPatch editor. The server owns all
 * structure/resource validation, proposal snapshots, CAS and rollback.
 * This controller never calls image-generation endpoints or writes a Graph
 * before the server acknowledges application.
 */
(function(root,factory){
  "use strict";
  const api=factory();
  root.HandrawStudioGraphPatch=api;
  if(typeof module==="object"&&module.exports) module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(){
  "use strict";
  const BASE="/api/studio/graph-patch";
  const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  const LABELS={addNode:"添加节点",removeNode:"删除节点",
    setNodeData:"修改参数",addEdge:"添加连线",removeEdge:"删除连线"};
  const errorText=x=>String(x?.message||x?.error||x||"未知错误");
  let active=null;

  async function api(method,resource,body){
    const res=await fetch(BASE+resource,{method,credentials:"same-origin",
      headers:{"Accept":"application/json",
        ...(body?{"Content-Type":"application/json"}:{})},
      ...(body?{body:JSON.stringify(body)}:{})});
    let json;
    try{json=await res.json();}catch(_){json={error:"服务没有返回有效 JSON"};}
    if(!res.ok||!json?.ok){
      const err=new Error(json?.error||json?.message||("HTTP "+res.status));
      err.code=json?.code||"graphpatch_http_error";
      err.status=res.status;
      throw err;
    }
    return json;
  }

  function summarize(report){
    if(!report)return "";
    const s=report.summary||{};
    const impact=report.costImpact||{};
    const conflicts=report.conflicts||[];
    const diff=Array.isArray(report.diffs)?report.diffs:[];
    const summary='<div class="gp126-metrics">'+
      '<span>新增节点 '+(s.nodesAdded||0)+'</span>'+
      '<span>移除节点 '+(s.nodesRemoved||0)+'</span>'+
      '<span>参数修改 '+(s.fieldsChanged||0)+'</span>'+
      '<span>连线 +'+(s.edgesAdded||0)+' / -'+(s.edgesRemoved||0)+'</span></div>';
    const cost='<p class="gp126-cost"><strong>潜在生成费用（预估）</strong>：增加约 '+
      Number(impact.additionalPotentialImages||0)+' 个生成槽位 · 约 '+
      Number(impact.estimatedAdditionalCredits||0)+' 积分。'+
      '<strong>当前仅预览，不生成、不扣费。</strong></p>';
    const conflictHtml=conflicts.length?
      '<div class="gp126-conflicts" role="alert"><strong>不可应用 · 检测到锁定冲突</strong>'+
      conflicts.map(c=>'<p>'+esc(c.nodeId)+' / '+esc(c.field)+' · '+esc(c.code)+'</p>').join('')+
      '</div>':'<p class="gp126-check">资源授权、图形结构与 DAG 已通过服务端预检。</p>';
    const lines=diff.map(d=>'<li><span class="gp126-op">'+esc(LABELS[d.op]||d.op)+
      '</span><code>'+esc(d.path)+'</code>'+
      '<small>'+esc(d.before===undefined||d.before===null?"无":JSON.stringify(d.before).slice(0,160))+
      ' → '+esc(d.after===undefined||d.after===null?"无":JSON.stringify(d.after).slice(0,160))+
      '</small></li>').join('');
    return summary+cost+conflictHtml+
      '<details class="gp126-details" open><summary>逐项差异（'+diff.length+' 项）</summary>'+
      '<ol>'+lines+'</ol></details>';
  }

  function contextValid(a,b){
    return Boolean(a&&b&&a.projectId===b.projectId&&
      a.baseRevision===b.baseRevision&&a.graphRevision===b.graphRevision&&
      b.saveState==="synced");
  }
  function contextFrom(raw){
    return {projectId:String(raw?.projectId||""),
      baseRevision:Number(raw?.baseRevision||0),
      graphRevision:Number(raw?.graphRevision||0),
      selectedIds:Array.isArray(raw?.selectedIds)?raw.selectedIds.slice(0,80):[],
      saveState:String(raw?.saveState||"")};
  }

  function open(options={}){
    if(typeof document==="undefined")return null;
    if(active?.root?.isConnected) active.destroy();
    const state={root:null,options,review:null,baseline:null,applied:null,
      busy:false,styles:[],mode:"platforms",closed:false};
    const backdrop=document.createElement("div");
    backdrop.id="gp126-backdrop";
    backdrop.className="gp126-backdrop";
    backdrop.innerHTML='<section class="gp126-dialog" role="dialog" aria-modal="true"'+
      ' aria-labelledby="gp126-title" tabindex="-1">'+
      '<header class="gp126-header"><div><h2 id="gp126-title">AI 修改画布</h2>'+
      '<p>先预览，再确认。不会自动生成图片或消费积分。</p></div>'+
      '<button type="button" class="gp126-close" data-gp126="close" aria-label="关闭">×</button></header>'+
      '<div class="gp126-body">'+
      '<label class="gp126-label">画布操作</label>'+
      '<div class="gp126-modes" role="group" aria-label="选择画布操作">'+
      '<button data-gp126-mode="seasons" type="button">四季系列</button>'+
      '<button data-gp126-mode="platforms" type="button">多平台尺寸</button>'+
      '<button data-gp126-mode="style_compare" type="button">双画风横评</button>'+
      '<button data-gp126-mode="ai" type="button">自由 AI 指令</button></div>'+
      '<div id="gp126-style-options" class="gp126-style-options" hidden>'+
      '<label>画风 A<select id="gp126-style-a" aria-label="横评画风 A"></select></label>'+
      '<label>画风 B<select id="gp126-style-b" aria-label="横评画风 B"></select></label></div>'+
      '<div id="gp126-ai-options" hidden><label class="gp126-label" for="gp126-instruction">'+
      'AI 修改说明</label><textarea id="gp126-instruction" rows="3" maxlength="800"'+
      ' placeholder="例如：在当前画布新增一个文字输入节点并连接到生成设置"></textarea></div>'+
      '<p class="gp126-note">结构化补丁仅作用于当前已保存的 Graph 项目。当前运行结果、媒体与计费账本不可修改。</p>'+
      '<div class="gp126-status" id="gp126-status" role="status" aria-live="polite"></div>'+
      '<div id="gp126-preview" class="gp126-preview"></div></div>'+
      '<footer class="gp126-actions">'+
      '<button type="button" data-gp126="close">取消</button>'+
      '<button type="button" data-gp126="preview" class="gp126-primary">生成差异预览</button>'+
      '<button type="button" data-gp126="apply" disabled>确认应用补丁</button>'+
      '<button type="button" data-gp126="undo" disabled>一键撤销本次应用</button>'+
      '</footer></section>';
    state.root=backdrop;
    document.body.appendChild(backdrop);
    const node=sel=>backdrop.querySelector(sel);
    const status=node("#gp126-status"),previewEl=node("#gp126-preview");
    const applyBtn=node('[data-gp126="apply"]');
    const previewBtn=node('[data-gp126="preview"]');
    const undoBtn=node('[data-gp126="undo"]');
    const modal=node(".gp126-dialog");
    const previousFocus=document.activeElement;
    function message(s,isError=false){
      status.textContent=s;
      status.classList.toggle("gp126-error",Boolean(isError));
    }
    function update(){
      backdrop.querySelectorAll("[data-gp126-mode]").forEach(b=>
        b.setAttribute("aria-pressed",String(b.dataset.gp126Mode===state.mode)));
      node("#gp126-style-options").hidden=state.mode!=="style_compare";
      node("#gp126-ai-options").hidden=state.mode!=="ai";
      applyBtn.disabled=state.busy||!state.review?.canApply||!!state.applied;
      previewBtn.disabled=state.busy||!!state.applied;
      undoBtn.disabled=state.busy||!state.applied;
      backdrop.querySelectorAll("[data-gp126-mode]").forEach(b=>b.disabled=state.busy||!!state.applied);
    }
    function reset(){
      state.review=null;state.baseline=null;
      previewEl.innerHTML="";
      update();
    }
    function setStyles(list){
      state.styles=list;
      const html=list.map(x=>'<option value="'+esc(x.id)+'">'+
        esc(x.name)+' ('+esc(x.id)+')</option>').join('');
      node("#gp126-style-a").innerHTML=html;
      node("#gp126-style-b").innerHTML=html;
      if(list.length>1)node("#gp126-style-b").selectedIndex=1;
    }
    async function generatePreview(){
      if(state.busy||state.applied)return;
      reset();
      const current=contextFrom(options.getContext?.());
      if(!current.projectId||!Number.isInteger(current.baseRevision)||
          current.baseRevision<1||!Number.isInteger(current.graphRevision)||
          current.saveState!=="synced"){
        message("请先登录并等待当前项目完成云端保存，再修改画布。",true);
        return;
      }
      const payload={projectId:current.projectId,
        baseRevision:current.baseRevision,graphRevision:current.graphRevision,
        selectedIds:current.selectedIds,mode:state.mode==="ai"?"ai":"preset"};
      if(state.mode==="ai"){
        payload.instruction=node("#gp126-instruction").value.trim();
        if(payload.instruction.length<2){message("请先填写 AI 修改说明。",true);return;}
      }else{
        payload.preset=state.mode;
        if(state.mode==="style_compare"){
          const a=node("#gp126-style-a").value,b=node("#gp126-style-b").value;
          if(!a||!b||a===b){message("请选择两个不同且已授权的画风。",true);return;}
          payload.styleIds=[a,b];
        }
      }
      state.busy=true;update();message("正在验证资源授权、拓扑依赖与版本…");
      try{
        const report=await api("POST","/preview",payload);
        if(state.closed)return;
        if(!contextValid(current,contextFrom(options.getContext?.()))){
          message("项目已经变化，旧预览已丢弃，请重新生成。",true);
          reset();return;
        }
        state.baseline=current;state.review=report;
        previewEl.innerHTML=summarize(report);
        message(report.canApply?"预览完成。请逐项核对后点击「确认应用补丁」。":
          "发现锁定冲突，补丁不能应用，请先解除冲突。",!report.canApply);
      }catch(err){if(!state.closed)message(errorText(err),true);}
      finally{state.busy=false;update();}
    }
    async function confirmApply(){
      if(state.busy||!state.review?.canApply||state.applied)return;
      const context=contextFrom(options.getContext?.());
      if(!contextValid(state.baseline,context)){
        message("项目版本已变化，必须重新审阅才能应用。",true);
        reset();return;
      }
      state.busy=true;update();message("正在向服务端确认并执行 CAS 应用…");
      try{
        const result=await api("POST","/apply",{
          reviewId:state.review.reviewId,confirmed:true});
        if(state.closed)return;
        const accepted=options.onApplied?.(result,state.baseline);
        if(accepted===false){
          message("服务端已应用；当前已切换项目，请重新打开云端项目。",true);
        }else{
          state.applied=result;
          message("已保存新 Graph 版本 "+result.graphRevision+
            "。如需恢复，点击「一键撤销本次应用」。");
          previewEl.innerHTML='<p class="gp126-success">云端已确认 · 项目版本 '+
            result.projectRevision+'，没有触发收费生成。</p>'+previewEl.innerHTML;
        }
      }catch(err){
        if(!state.closed)message(errorText(err)+"。请重新生成差异预览。",true);
        state.review=null;
      }finally{state.busy=false;update();}
    }
    async function revert(){
      if(state.busy||!state.applied)return;
      state.busy=true;update();message("正在撤销云端补丁，不覆盖其他标签的修改…");
      try{
        const result=await api("POST","/undo",{
          reviewId:state.applied.reviewId,confirmed:true});
        if(state.closed)return;
        const accepted=options.onApplied?.(result,{
          ...state.baseline,baseRevision:state.applied.projectRevision,
          graphRevision:state.applied.graphRevision});
        if(accepted===false){
          message("云端已撤销；请重新加载当前项目以恢复画布。",true);
        }else{
          message("已撤销并保存新的 Graph 版本 "+result.graphRevision+"。");
          previewEl.innerHTML='<p class="gp126-success">已回滚：旧图的 Run 与媒体引用保持不变。</p>';
        }
        state.applied=null;state.review=null;
      }catch(err){
        if(!state.closed)message(errorText(err),true);
      }finally{state.busy=false;update();}
    }
    function close(){
      if(state.closed)return;
      state.closed=true;backdrop.remove();
      document.removeEventListener("keydown",onKey);
      if(previousFocus&&previousFocus.isConnected)previousFocus.focus();
      if(active===state)active=null;
    }
    function onKey(e){
      if(e.key==="Escape"){e.preventDefault();close();return;}
      if(e.key!=="Tab")return;
      const focusables=[...backdrop.querySelectorAll('button:not([disabled]):not([hidden]),select:not([disabled]),textarea:not([disabled])')]
        .filter(el=>el.getClientRects().length);
      if(!focusables.length)return;
      const first=focusables[0],last=focusables[focusables.length-1];
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
    document.addEventListener("keydown",onKey);
    backdrop.addEventListener("click",e=>{if(e.target===backdrop)close();});
    backdrop.querySelectorAll("[data-gp126-mode]").forEach(b=>
      b.onclick=()=>{if(state.busy||state.applied)return;
        state.mode=b.dataset.gp126Mode;reset();message("");});
    backdrop.querySelectorAll('[data-gp126="close"]').forEach(b=>b.onclick=close);
    previewBtn.onclick=()=>void generatePreview();
    applyBtn.onclick=()=>void confirmApply();
    undoBtn.onclick=()=>void revert();
    node("#gp126-style-a").onchange=reset;
    node("#gp126-style-b").onchange=reset;
    node("#gp126-instruction").oninput=reset;
    update();
    modal.focus();
    active=state;
    state.destroy=close;
    api("GET","/styles").then(data=>{
      if(state.closed)return;
      setStyles(Array.isArray(data.styles)?data.styles:[]);
    }).catch(err=>{if(!state.closed)message("授权画风读取失败："+errorText(err),true);});
    return Object.freeze({close,destroy:close,preview:generatePreview,
      apply:confirmApply,undo:revert});
  }
  return Object.freeze({open,summarize,contextValid,contextFrom});
});
