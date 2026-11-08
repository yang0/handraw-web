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
    pending:"排队中",running:"生成中",success:"已完成",failed:"失败",
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
  return Object.freeze({label,mediaUrl,slotIndex,slotSummary,summarize,galleryState,mayRetry});
});
