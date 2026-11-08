/* Studio 2.0 #108: Series workspace presentation only.
 * PlanSlot remains writable exclusively through HandrawStudioSeries.
 * V3 Run/RunItem is the only authority for success and retry identity.
 */
(function(root,factory){
  "use strict";
  const api=factory();
  root.HandrawSeriesBoard108=api;
  if(typeof module==="object"&&module.exports)module.exports=api;
})(typeof window!=="undefined"?window:globalThis,function(){
  "use strict";
  const esc=x=>String(x==null?"":x).replace(/[&<>"']/g,c=>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const KINDS=Object.freeze([
    {id:"story-series",name:"连续系列",note:"逐张规划画面、分镜与图型"},
    {id:"same-spec",name:"同方案多张",note:"共享配方，多候选采样"},
    {id:"compare",name:"画风/图型横评",note:"逐张指定要比较的资源"},
    {id:"multi-format",name:"多尺寸/平台",note:"每张独立设置画幅与构图"}
  ]);
  const FILTERS=Object.freeze([
    ["all","全部"],["waiting","未生成/待核对"],["running","生成中"],
    ["success","成功"],["failed","失败"],["locked","已锁定"]
  ]);
  const validId=x=>typeof x==="string"&&x.length>0;
  const array=x=>Array.isArray(x)?x:[];
  function outputsFor(slot,snapshot,projection){
    const frozen=array(snapshot?.outputs).filter(o=>o.slotId===slot.slotId)
      .sort((a,b)=>Number(a.candidateIndex||0)-Number(b.candidateIndex||0));
    if(!frozen.length)return [];
    const current=array(projection?.outputs);
    return frozen.map(item=>{
      const remote=current.find(o=>o.slotId===item.slotId &&
        Number(o.candidateIndex||0)===Number(item.candidateIndex||0) &&
        Number(o.outputIndex)===Number(item.outputIndex));
      // A local spinner / optimistic preview never constitutes paid success.
      const state=remote?.status||"unknown";
      const owned=state==="success"&&validId(remote.mediaId)&&validId(remote.imageUrl);
      return {...item,status:owned?"success":state==="success"?"unknown":state,
        mediaId:owned?remote.mediaId:"",imageUrl:owned?remote.imageUrl:"",
        errorCode:remote?.errorCode||"",
        runId:projection?.runId||snapshot?.runId||""};
    });
  }
  function status(slot,outputs,busy){
    if(!outputs.length)return {key:"waiting",label:"待生成"};
    const success=outputs.filter(x=>x.status==="success").length;
    const failed=outputs.filter(x=>x.status==="failed").length;
    const active=outputs.some(x=>["running","generating","uploading","pending","queued","cancel_requested"].includes(x.status));
    const unknown=outputs.some(x=>x.status==="unknown");
    if(success===outputs.length)return {key:"success",label:success+" / "+outputs.length+" 成功"};
    if(failed && !active && !unknown)return {key:"failed",label:failed+" 失败 · "+success+" 成功"};
    if(active&&busy)return {key:"running",label:success+" 成功 · "+failed+" 失败 · 运行/排队中"};
    if(unknown)return {key:"waiting",label:"服务器状态待核对 · "+success+" 成功"};
    if(failed)return {key:"failed",label:failed+" 失败 · "+success+" 成功"};
    return {key:"waiting",label:success+" 成功 · 待生成"};
  }
  function catalogEntry(catalog,refOrId){
    const id=typeof refOrId==="string"?refOrId:refOrId?.id;
    if(!id)return null;
    return catalog?.resourceMap?.get?.(id)||null;
  }
  function renderCard(slot,index,opt){
    const outputs=outputsFor(slot,opt.snapshot,opt.projection);
    const state=status(slot,outputs,opt.busy);
    const filter=opt.filter;
    if(filter==="success"&&!outputs.some(x=>x.status==="success"))return "";
    if(filter==="failed"&&!outputs.some(x=>x.status==="failed"))return "";
    if(filter==="running"&&state.key!=="running")return "";
    if(filter==="waiting"&&state.key!=="waiting")return "";
    if(filter==="locked"&&!array(slot.lockedFields).length)return "";
    const first=outputs.find(x=>x.imageUrl)||null;
    const overridden=slot.overrides||{};
    const style=overridden.style?.id||opt.globalSpec?.style?.id||"";
    const layout=overridden.layout?.id||opt.globalSpec?.layout?.id||"";
    const ratio=overridden.ratio||opt.globalSpec?.ratio||"3:4";
    const layoutResource=catalogEntry(opt.catalog,layout);
    const styleResource=catalogEntry(opt.catalog,style);
    const cover=first?'<img class="series108-image" src="'+esc(first.imageUrl)+
      '" data-series-media="'+esc(first.mediaId)+'" alt="第 '+(index+1)+' 张生成结果" loading="lazy" />':
      layoutResource?.image?'<img class="series108-layout-example" src="'+esc(layoutResource.image)+
      '" alt="图型示意（非生成结果）" loading="lazy" /><span class="series108-example-mark">图型示意 · 尚未生成</span>':
      '<div class="series108-placeholder" role="img" aria-label="尚无生成结果"><span>尚未生成</span></div>';
    const outputStr=outputs.length?'<div class="series108-candidates">'+outputs.map((o,i)=>{
      const result=o.status==="success"&&o.mediaId;
      return '<span class="series108-candidate '+esc(o.status)+'">'+
        (result?'<button type="button" data-series-action="view" data-series-slot="'+esc(slot.slotId)+
          '" data-series-output="'+o.outputIndex+'" title="放大此候选">候选 '+(i+1)+' ✓</button>':
          '<small>候选 '+(i+1)+' · '+esc(o.status==="unknown"?"待核对":o.status)+'</small>')+
        (o.status==="failed" && opt.projection?.isTerminal && Number.isInteger(o.outputIndex)
          ?'<button type="button" data-series-action="retry" data-series-slot="'+esc(slot.slotId)+
            '" data-series-output="'+o.outputIndex+'">重试</button>':"")+
        '</span>';
    }).join("")+'</div>':"";
    return '<article class="series108-card series108-'+state.key+'" data-series-slot-card="'+esc(slot.slotId)+'" role="listitem">'+
      '<header class="series108-card-head"><span class="series108-num">#'+String(index+1).padStart(2,"0")+
      '</span><span class="series108-slot-id" title="'+esc(slot.slotId)+'">'+esc(slot.slotId.slice(-9))+
      '</span><span class="series108-state '+state.key+'">'+esc(state.label)+'</span></header>'+
      '<div class="series108-cover">'+cover+'</div>'+
      '<label class="series108-subject-label">画面主题<textarea rows="3" data-series-subject="'+esc(slot.slotId)+
      '" maxlength="1200" aria-label="第 '+(index+1)+' 张画面主题">'+esc(slot.subject||"")+'</textarea></label>'+
      '<div class="series108-pills"><span title="'+esc(styleResource?.name_zh||style)+'">'+
      (overridden.style?"本图画风 ":"继承画风 ")+esc(style||"待选择")+'</span>'+
      '<span title="'+esc(layoutResource?.name_zh||layout)+'">'+
      (overridden.layout?"本图图型 ":"继承图型 ")+esc(layout||"待选择")+'</span>'+
      '<span>'+(overridden.ratio?"独立比例 ":"比例 ")+esc(ratio)+'</span>'+
      (array(slot.referenceMedia).length?'<span>独立参考 '+array(slot.referenceMedia).length+' 张</span>':"")+
      (slot.skipGlobalRefs?'<span>不使用全局参考</span>':"")+
      '</div>'+
      (array(slot.lockedFields).length?
        '<small class="series108-locked">锁定：'+esc(array(slot.lockedFields).join("、"))+'</small>':"")+
      outputStr+
      '<div class="series108-card-actions">'+
      '<button type="button" data-series-action="edit" data-series-slot="'+esc(slot.slotId)+'">逐张参数</button>'+
      '<button type="button" data-series-action="refs" data-series-slot="'+esc(slot.slotId)+'">参考图</button>'+
      '<button type="button" data-series-action="copy" data-series-slot="'+esc(slot.slotId)+'">复制</button>'+
      '<button type="button" data-series-action="up" data-series-slot="'+esc(slot.slotId)+'" '+(index===0?"disabled":"")+'>上移</button>'+
      (first?'<button type="button" data-series-action="download" data-series-slot="'+esc(slot.slotId)+
        '" data-series-output="'+first.outputIndex+'">下载</button>':"")+
      '<button type="button" data-series-action="delete" data-series-slot="'+esc(slot.slotId)+'">移除</button>'+
      '</div></article>';
  }
  function render(opt={}){
    const slots=array(opt.plan?.slots).slice().sort((a,b)=>a.order-b.order);
    const current=KINDS.some(k=>k.id===opt.intent)?opt.intent:"story-series";
    const view=opt.view==="table"?"table":"cards";
    const filter=FILTERS.some(x=>x[0]===opt.filter)?opt.filter:"all";
    const renderOpts={...opt,filter};
    const cards=slots.map((slot,i)=>renderCard(slot,i,renderOpts)).filter(Boolean);
    const count=slots.length;
    const cand=Number(opt.candidateCount)||1;
    return '<div class="series108-head"><div><h2>系列创作 · 方案板</h2>'+
      '<p>统一 PlanSlot 编排，生成和重试由原 Run 执行；切换展示方式不会修改方案。</p></div>'+
      '<div class="series108-view" role="group" aria-label="方案视图">'+
      '<button type="button" data-series-view="cards" aria-pressed="'+(view==="cards")+'">图卡</button>'+
      '<button type="button" data-series-view="table" aria-pressed="'+(view==="table")+'">紧凑表格</button></div></div>'+
      '<div class="series108-kinds" role="group" aria-label="系列创作类型">'+KINDS.map(k=>
        '<button type="button" data-series-kind="'+esc(k.id)+'" aria-pressed="'+(k.id===current)+'" title="'+esc(k.note)+'">'+esc(k.name)+'</button>').join("")+'</div>'+
      '<p class="series108-kind-note">'+esc(KINDS.find(k=>k.id===current).note)+
      '；模式切换只调整创作意图，不会清空已有图卡、资源、结果或运行快照。</p>'+
      '<div class="series108-controls"><div class="series108-filters" role="group" aria-label="图卡过滤">'+
      FILTERS.map(([id,label])=>'<button type="button" data-series-filter="'+id+
        '" aria-pressed="'+(id===filter)+'">'+label+'</button>').join("")+
      '</div><div class="series108-extra">'+
      '<button type="button" data-series-action="add">＋ 新增图卡</button>'+
      '<button type="button" data-series-action="paste">批量粘贴</button>'+
      (current==="multi-format"?'<button type="button" data-series-action="ratios">填入常用平台比例</button>':"")+
      '</div></div>'+
      '<div class="series108-totals" role="status">计划 '+count+' 张 · 每张候选 '+cand+
      ' · 实际输出 '+(count*cand)+' 次 · '+cards.length+' 张符合当前筛选</div>'+
      (view==="table"?'<p class="series108-table-hint">下方为兼容的紧凑编辑与执行清单；逐张修改仍保留稳定槽位 ID。</p>':
        '<div class="series108-grid" role="list">'+(cards.length?cards.join(""): 
          '<div class="series108-empty">没有符合此筛选条件的图卡。切换「全部」或新增图卡。</div>')+'</div>')+
      '<footer class="series108-footnote">修改中的主题不会改写已提交的 RunSnapshot；旧成功图片与作品保留在生成历史。</footer>';
  }
  return Object.freeze({KINDS,FILTERS,outputsFor,status,render,renderCard});
});
