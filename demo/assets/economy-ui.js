/* Separate cash, points and specification benefits, shared by all creation modes. */
(function(global){
  "use strict";
  const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const yuan=cents=>`¥${(Number(cents||0)/100).toFixed(2)}`;
  const paymentStatus=(status,refund=false)=>({pending:refund?'待审核':'待付款',paid:'已到账',partially_refunded:'部分退款',refunded:'已退款',processing:'处理中',unknown:'待核对',completed:'已退款',rejected:'确认未退款',failed:'失败',expired:'已过期',cancelled:'已取消'}[status]||status);
  const cashEntryLabel=kind=>({recharge:'充值到账',generation_hold:'生图费用预占',generation_settle:'生图结算',generation_release:'生图预占释放',refund_hold:'退款冻结',refund_complete:'原路退款',refund_release:'退款冻结释放',refund_reconciled:'退款核对',provider_refund:'支付退款冲回'}[kind]||kind);
  const api=async(url,opts={})=>{
    if(global.HANDRAW_SHARED)return global.HANDRAW_SHARED.apiJson(url,opts);
    const options={credentials:'include',...opts,headers:{'Content-Type':'application/json',...opts.headers}};
    if(options.body&&typeof options.body==='object')options.body=JSON.stringify(options.body);
    const response=await fetch(url,options),result=await response.json();
    if(!response.ok||result.ok===false)throw Object.assign(new Error(result.error||'请求失败'),{status:response.status});
    return result;
  };
  let chosenSpec="standard-1k",availableSpecs=[];
  const pickerLoads=new WeakMap();
  function picker(specs){return `<label>图片规格 <select data-economy-spec>${specs.filter(s=>s.enabled&&s.verified).map(s=>`<option value="${esc(s.id)}" ${s.id===chosenSpec?"selected":""}>${esc(s.name)} · ${s.priceCents==null?"付费价格未配置":yuan(s.priceCents)+"/张"}</option>`).join("")}</select></label>`;}
  function confirmDialog(quote){
    return new Promise(resolve=>{
      const dialog=document.createElement("dialog");dialog.className="economy-dialog";
      const resolveClose=value=>{dialog.close();dialog.remove();resolve(value);};
      const groups=new Map();for(const line of quote.items){const key=line.spec.id;const g=groups.get(key)||{spec:line.spec,count:0,free:0};g.count++;g.free+=Number(line.free);groups.set(key,g);}
      dialog.innerHTML=`<form><h2>确认生图费用</h2>${[...groups.values()].map(g=>`<p>${esc(g.spec.name)} · ${g.count} 张 · 免费 ${g.free} 张<br><small>${g.spec.priceCents==null?"尚未配置付费价格":yuan(g.spec.priceCents)+"/张"}</small></p>`).join("")}<p><strong>本次最高 ${yuan(quote.totalCents)}</strong> · 可用余额 ${yuan(quote.balanceCents)}</p><p>免费额度与余额提交后预占，成功出图结算，失败释放。社区积分不支付生图费用。</p><p role="alert">${quote.affordable?"":"余额不足，请先到钱包充值。"}</p><div class="economy-actions"><button type="button" data-cancel>取消</button><button type="submit" ${quote.affordable?"":"disabled"}>确认生成 ${quote.count} 张</button></div></form>`;
      dialog.querySelector('[data-cancel]').onclick=()=>resolveClose(null);
      dialog.oncancel=e=>{e.preventDefault();resolveClose(null);};
      dialog.querySelector('form').onsubmit=e=>{e.preventDefault();resolveClose(quote);};
      document.body.append(dialog);dialog.showModal();
    });
  }
  async function quote(items){return api('/api/studio/quote',{method:'POST',body:{items:items.map(item=>({specId:item.specId||chosenSpec,ratio:item.ratio||'3:4',slotPosition:item.slotPosition}))}});}
  async function confirm(items){return confirmDialog(await quote(items));}
  async function mountPicker(root){
    const load=Symbol();pickerLoads.set(root,load);
    try {
      const state=await api('/api/economy');
      if(!root.isConnected||pickerLoads.get(root)!==load)return;
      availableSpecs=state.specs;
      const allowed=state.specs.filter(s=>s.enabled&&s.verified);
      if(!allowed.some(s=>s.id===chosenSpec))chosenSpec=allowed[0]?.id||'standard-1k';
      if(!allowed.length){root.textContent='暂无已验证开放的生图规格';return;}
      root.innerHTML=picker(state.specs);root.querySelector('select').onchange=e=>{chosenSpec=e.target.value;};
    }catch(e){if(root.isConnected&&pickerLoads.get(root)===load){availableSpecs=[];root.textContent=e.message;}}
  }
  async function mountWallet(root){
    root.innerHTML='<p role="status">正在读取余额与权益…</p>';
    try{
      const state=await api('/api/economy');
      const orders=await api('/api/billing/orders');
      const boot=await api('/api/boot');
      if(!root.isConnected)return;
      const shared=global.HANDRAW_SHARED;
      if(shared?.App?.state){
        shared.syncWalletCredits?.(state.points);
        shared.App.state.dailyCheckedIn=Boolean(boot.state?.dailyCheckedIn??boot.dailyCheckedIn);
        const basic=state.freeQuota.find(q=>q.resolution==='1k');
        if(basic){shared.App.state.freeQuotaRemaining=basic.remaining;shared.App.state.freeQuotaMax=basic.total;}
        shared.renderChrome?.();
      }
      const packs=boot.state?.billing?.packages||boot.billing?.packages||[];
      root.innerHTML=`<section class="economy-wallet"><h1>钱包与权益</h1><div class="economy-cards"><article><h2>生图余额</h2><strong>${yuan(state.cash.balanceCents)}</strong><p>冻结中 ${yuan(state.cash.heldCents)} · 仅用于图片生成</p></article><article><h2>社区积分</h2><strong>${state.points} 积分</strong><p>解锁内容与资源，不兑换现金或生图余额</p></article><article><h2>免费生图额度</h2>${state.freeQuota.map(q=>`<p>${esc(q.resolution.toUpperCase())} · 剩余 <strong>${q.remaining}</strong> 张 · 预占 ${q.held} 张</p>`).join('')}<p>一次性额度，长期有效；活动赠送按具体期限使用。</p></article></div><h2>充值与购买</h2><div class="economy-cards">${packs.map(p=>`<article><h3>${p.purpose==='cash'?'生图余额充值':'购买社区积分'}</h3><strong>${p.purpose==='cash'?yuan(p.priceCents):p.credits+' 积分'}</strong><p>${esc(p.description)}</p><button data-purchase="${esc(p.id)}">支付 ${esc(p.priceDisplay)}</button></article>`).join('')||'<p>在线支付尚未配置，可通过社区贡献获得积分。</p>'}</div><h2>贡献与作者收益</h2><p>待结算 ${state.earnings.pending||0} 分 · 已结算 ${state.earnings.settled||0} 分 · 已冲回 ${state.earnings.reversed||0} 分。解锁分成80%，7天后可用。</p><p>账号验证20分；签到1分，每月最多20分；优质作品5分、原创资源20分、优质教程10分，每类每月最多10件。</p><button data-checkin>每日签到</button><h2>购买订单</h2>${(orders.orders||[]).map(o=>`<article class="economy-entry"><span>${o.purpose==='cash'?'生图余额':'社区积分'} · ${yuan(o.amountCents)} · ${esc(paymentStatus(o.status))}</span>${o.status==='pending'?`<button data-sync="${esc(o.id)}">核验到账</button>`:''}${['paid','partially_refunded'].includes(o.status)?`<button data-refund="${esc(o.id)}">申请退还未消费部分</button>`:''}</article>`).join('')||'<p>暂无订单</p>'}<details><summary>人民币余额明细</summary>${state.cashEntries.map(e=>`<p>${esc(cashEntryLabel(e.kind))} · ${yuan(e.delta_cents)} · 冻结变化 ${yuan(e.held_delta_cents)} · ${esc(e.created_at)}</p>`).join('')||'暂无明细'}</details><details><summary>社区积分明细</summary>${state.pointEntries.map(e=>`<p>${esc(e.reason)} · ${e.delta>0?'+':''}${e.delta} 分</p>`).join('')||'暂无明细'}</details><details><summary>已解锁内容与资源</summary>${state.unlocks.filter(u=>u.status==='settled').map(u=>`<p>${esc(u.target_id)} · ${u.target_type==='asset'?'站内持续使用权':'查看与复制'}</p>`).join('')||'暂无解锁'}</details><p role="status" data-message></p></section>`;
      const message=text=>{const target=root.querySelector('[data-message]');if(target)target.textContent=text;};
      root.onclick=async event=>{
        const button=event.target.closest('button');if(!button)return;button.disabled=true;
        try{
          if(button.dataset.purchase){const result=await api('/api/billing/checkout',{method:'POST',body:{packId:button.dataset.purchase}});const url=result.checkoutUrl||result.order?.checkoutUrl;if(url)global.location.assign(url);else throw Error('支付地址暂未返回，请在订单中核验');}
          else if(button.dataset.sync){await api(`/api/billing/orders/${encodeURIComponent(button.dataset.sync)}/sync`,{method:'POST',body:{}});await mountWallet(root);}
          else if(button.dataset.refund){await api('/api/billing/refund-requests',{method:'POST',body:{orderId:button.dataset.refund,reason:'申请退还未消费部分'}});await mountWallet(root);message('退款申请已提交，未消费部分已冻结，等待管理员审核。');}
          else if(button.hasAttribute('data-checkin')){const result=await api('/api/wallet/checkin',{method:'POST',body:{}});await mountWallet(root);message(`已签到，本次奖励 ${result.bonus} 积分，不改变生图额度。`);}
        }catch(e){message(e.message);}finally{button.disabled=false;}
      };
    }catch(e){root.textContent=e.message;}
  }
  async function mountAdmin(root){
    root.innerHTML='<p role="status">正在读取独立账务配置…</p>';
    try{
      const state=await api('/api/admin/economy');if(!root.isConnected)return;
      root.innerHTML=`<section class="economy-wallet"><h2>生图收费与社区积分</h2><p>账务对账：${state.reconciliation.ok?'一致':'发现差异，请检查后台报告'}</p><p>人民币生图、社区积分、按规格赠送额度独立记账。AI规划免费。</p><details open><summary>生图规格与价格</summary><p>售价必须填写整数分。先核验网关实际支持的模型、质量和像素，再勾选已验证。</p><select data-edit-spec><option value="">新增规格</option>${state.specs.map(s=>`<option value="${esc(s.id)}">${esc(s.name)} · ${s.price_cents==null?'未定价':yuan(s.price_cents)}${s.cost_cents==null?'':` · 毛利 ${s.price_cents?((s.price_cents-s.cost_cents)/s.price_cents*100).toFixed(1):0}%`}</option>`).join('')}</select><form data-admin-form="spec"><div class="economy-admin-grid"><label>规格编号<input name="id" required value="standard-1k"></label><label>名称<input name="name" required value="标准 1K"></label><label>模型<input name="model" required value="gpt-image-2"></label><label>分辨率<select name="resolution"><option>1k</option><option>2k</option><option>4k</option></select></label><label>质量<input name="quality" value="auto" required></label><label>售价（分）<input name="priceCents" type="number" min="1" step="1" placeholder="空白则禁止付费生成"></label><label>成本（分）<input name="costCents" type="number" min="0" step="1"></label><label><input name="enabled" type="checkbox">开放使用</label><label><input name="verified" type="checkbox">已验证网关实际支持</label></div><label>比例与实际像素映射<textarea name="sizes" rows="5" required></textarea></label><label>调整原因<input name="reason" required maxlength="500"></label><button type="submit">保存规格与价格</button></form></details><details open><summary>全员基础免费额度</summary><form data-admin-form="base"><label>规格<select name="resolution"><option>1k</option><option>2k</option><option>4k</option></select></label><label>每账号基础总张数<input name="units" type="number" min="0" max="10000" value="${state.policies.find(p=>p.resolution==='1k')?.base_units??10}" required></label><p>这是生命周期总额度，不是每日额度；已用和预占会扣除，额外赠送另计。</p><label>调整原因<input name="reason" required maxlength="500"></label><button type="submit">预览调整影响</button><div data-base-preview role="status"></div></form></details><details><summary>额外赠送额度</summary><form data-admin-form="grant"><label>对象<select name="group"><option value="selected">指定用户ID</option><option value="all">全员</option><option value="user">普通用户组</option><option value="reviewer">审核员组</option><option value="moderator">版主组</option></select></label><label>用户ID，逗号分隔<input name="userIds"></label><label>规格<select name="resolution"><option>1k</option><option>2k</option><option>4k</option></select></label><label>赠送张数<input name="units" type="number" min="1" max="10000" required></label><label>有效期（留空长期有效）<input name="expiresAt" type="datetime-local"></label><label>原因<input name="reason" required maxlength="500"></label><button type="submit">发放赠送</button></form>${state.grants.map(g=>`<p>${esc(g.username)} · ${esc(g.resolution)} ${g.units}张 · ${esc(g.reason)} ${g.revoked_at?'已撤回':`<button type="button" data-revoke="${esc(g.id)}">撤回未使用额度</button>`}</p>`).join('')}</details><details><summary>优质作品与教程奖励</summary><form data-admin-form="reward"><label>类型<select name="kind"><option value="quality_work">优质作品：5积分</option><option value="quality_topic">优质教程：10积分</option></select></label><label>已发布内容ID<input name="targetId" required></label><p>每种每作者每月最多10件，同一内容不重复奖励。</p><button>发放奖励</button></form></details><details><summary>积分价格档位</summary><form data-admin-form="point-prices"><label>类型<select name="kind"><option value="topic">帖子与提示词</option><option value="asset">画风与图型</option></select></label><label>价格档位，逗号分隔<input name="options" value="0,5,10,20,50,100" required></label><label>调整原因<input name="reason" required maxlength="500"></label><button>保存档位</button></form></details><details open><summary>原路退款审核</summary>${state.refunds.map(r=>`<p>${esc(r.username)} · ${r.purpose==='cash'?'生图余额':'社区积分'} · ${yuan(r.amount_cents)} · ${esc(r.reason)} · ${esc(paymentStatus(r.status,true))} ${r.status==='pending'?`<button type="button" data-approve-refund="${esc(r.id)}">审核并原路退款</button>`:''}${['pending','unknown','processing'].includes(r.status)?`请核对平台记录，禁止重复退款 <button type="button" data-reconcile-refund="${esc(r.id)}">记录平台核对结果</button>`:''}</p>`).join('')||'暂无退款申请'}</details><p data-admin-message role="status"></p></section>`;
      const specForm=root.querySelector('[data-admin-form="spec"]');
      function loadSpec(id){const s=state.specs.find(s=>s.id===id);if(!s)return;for(const key of ['id','name','model','resolution','quality'])specForm.elements[key].value=s[key];specForm.elements.priceCents.value=s.price_cents??'';specForm.elements.costCents.value=s.cost_cents??'';specForm.elements.sizes.value=JSON.stringify(s.sizes_json,null,2);specForm.elements.enabled.checked=s.enabled;specForm.elements.verified.checked=s.verified;}
      const specSelect=root.querySelector('[data-edit-spec]');
      if(state.specs.some(s=>s.id==='standard-1k')){specSelect.value='standard-1k';loadSpec('standard-1k');}
      specSelect.onchange=e=>{if(e.target.value)loadSpec(e.target.value);else {specForm.reset();specForm.elements.id.value='';specForm.elements.name.value='';}};
      const baseForm=root.querySelector('[data-admin-form="base"]');
      let baseDraftRevision=0;
      const invalidateBasePreview=()=>{baseDraftRevision++;baseForm.querySelector('[data-base-preview]').replaceChildren();};
      baseForm.addEventListener('input',invalidateBasePreview);
      baseForm.addEventListener('change',invalidateBasePreview);
      baseForm.elements.resolution.onchange=()=>{baseForm.elements.units.value=state.policies.find(p=>p.resolution===baseForm.elements.resolution.value)?.base_units??0;invalidateBasePreview();};
      const priceForm=root.querySelector('[data-admin-form="point-prices"]');
      const loadPointPrices=()=>{priceForm.elements.options.value=(state.pointPrices[priceForm.elements.kind.value]||[]).join(',');};
      priceForm.elements.kind.onchange=loadPointPrices;loadPointPrices();
      const message=text=>root.querySelector('[data-admin-message]').textContent=text;
      let grantRequest='gift_'+crypto.randomUUID().replace(/-/g,'');
      root.onsubmit=async event=>{
        const form=event.target.closest('[data-admin-form]');if(!form)return;event.preventDefault();
        const action=form.dataset.adminForm,body={action,...Object.fromEntries(new FormData(form))};const button=event.submitter;button.disabled=true;
        try{
          if(action==='spec'){body.sizes=JSON.parse(body.sizes);body.priceCents=body.priceCents===''?null:Number(body.priceCents);body.costCents=body.costCents===''?null:Number(body.costCents);body.enabled=form.elements.enabled.checked;body.verified=form.elements.verified.checked;}
          if(action==='base'){body.units=Number(body.units);const revision=baseDraftRevision;const preview=await api('/api/admin/economy',{method:'POST',body:{...body,action:'base-preview'}});if(revision!==baseDraftRevision)return;const el=form.querySelector('[data-base-preview]');el.textContent=`${preview.affectedUsers} 个现有账号：基础总量 ${preview.oldUnits} → ${preview.newUnits} 张。未来账号同样生效。`;const confirm=document.createElement('button');confirm.type='button';confirm.textContent='确认调整';confirm.onclick=async()=>{confirm.disabled=true;try{await api('/api/admin/economy',{method:'POST',body:{...body,confirmation:preview.confirmation}});const policy=state.policies.find(p=>p.resolution===body.resolution);if(policy)policy.base_units=body.units;else state.policies.push({resolution:body.resolution,base_units:body.units});message('全员基础额度已更新。');}catch(e){message(e.message);confirm.disabled=false;}};el.append(confirm);return;}
          if(action==='grant'){body.units=Number(body.units);body.userIds=body.userIds.split(/[,，\s]+/).filter(Boolean).map(Number);body.requestId=grantRequest;body.expiresAt=body.expiresAt?new Date(body.expiresAt).toISOString():null;}
          if(action==='point-prices')body.options=body.options.split(/[,，\s]+/).filter(Boolean).map(Number);
          const result=await api(action==='reward'?'/api/admin/economy/reward':'/api/admin/economy',{method:'POST',body});
          if(action==='spec'){
            const saved={id:body.id,name:body.name,model:body.model,resolution:body.resolution,quality:body.quality,sizes_json:body.sizes,price_cents:body.priceCents,cost_cents:body.costCents,enabled:body.enabled,verified:body.verified};
            const index=state.specs.findIndex(s=>s.id===body.id);if(index<0)state.specs.push(saved);else state.specs[index]={...state.specs[index],...saved};
            let option=[...specSelect.options].find(o=>o.value===body.id);if(!option){option=document.createElement('option');option.value=body.id;specSelect.append(option);}
            option.textContent=`${saved.name} · ${saved.price_cents==null?'未定价':yuan(saved.price_cents)}`;specSelect.value=body.id;
          }
          if(action==='point-prices')state.pointPrices[body.kind]=[...new Set([0,...body.options])].sort((a,b)=>a-b);
          if(action==='grant')grantRequest='gift_'+crypto.randomUUID().replace(/-/g,'');
          message(action==='reward'?`本次奖励 ${result.rewarded} 积分`:'保存成功，变更已记录审计。');
        }catch(e){message(e.message);}finally{button.disabled=false;}
      };
      root.onclick=async event=>{const button=event.target.closest('[data-revoke],[data-approve-refund],[data-reconcile-refund]');if(!button)return;button.disabled=true;try{if(button.dataset.reconcileRefund){const evidence=global.prompt('填写支付平台退款核对记录编号');if(!evidence)return;const outcome=global.prompt('确认平台结果：输入 completed 表示已退款，rejected 表示确认未退款');if(!['completed','rejected'].includes(outcome))throw Error('结果无效，未修改冻结款项');const reason=global.prompt('填写核对说明');if(!reason)return;await api('/api/admin/economy/refunds',{method:'POST',body:{action:'reconcile',refundId:button.dataset.reconcileRefund,outcome,providerReference:evidence,reason}});}else if(button.dataset.revoke){const reason=global.prompt('填写撤回未使用额度的原因');if(!reason)return;await api('/api/admin/economy',{method:'POST',body:{action:'revoke',grantId:button.dataset.revoke,reason}});}else{if(!global.confirm('将申请中冻结的未消费款项原路退回。确认审核通过？'))return;await api('/api/admin/economy/refunds',{method:'POST',body:{refundId:button.dataset.approveRefund}});}await mountAdmin(root);}catch(e){message(e.message);}finally{button.disabled=false;}};
    }catch(e){root.textContent=e.message;}
  }
  global.HandrawEconomy={quote,confirm,mountWallet,mountAdmin,mountPicker,yuan,get specId(){return chosenSpec;},get specs(){return availableSpecs;}};
})(window);
