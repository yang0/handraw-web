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
  const mountLoads=new WeakMap();
  const viewUrl=view=>global.HANDRAW_SHARED?.channelUrl?global.HANDRAW_SHARED.channelUrl('main',{view}):`/?view=${encodeURIComponent(view)}`;
  const goView=(event,view)=>{
    if(event&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!event.altKey&&(!('button' in event)||event.button===0)&&global.HANDRAW_MAIN_SWITCH_VIEW){
      event.preventDefault();
      global.HANDRAW_MAIN_SWITCH_VIEW(view);
      return true;
    }
    return false;
  };
  const syncSharedEconomy=(state,boot=null)=>{
    const shared=global.HANDRAW_SHARED;
    if(!shared?.App?.state||!state)return;
    shared.syncWalletCredits?.(state.points);
    if(boot)shared.App.state.dailyCheckedIn=Boolean(boot.state?.dailyCheckedIn??boot.dailyCheckedIn);
    const basic=state.freeQuota?.find?.(q=>q.resolution==='1k');
    if(basic){shared.App.state.freeQuotaRemaining=basic.remaining;shared.App.state.freeQuotaMax=basic.total;}
    shared.renderChrome?.();
  };
  const formatOrderTime=raw=>{
    const text=String(raw||'').trim();
    if(!text)return '';
    if(typeof Date==='function'){
      const ts=Date.parse(text.includes('T')?text:text.replace(' ','T'));
      if(!Number.isNaN(ts)){
        const d=new Date(ts),pad=n=>String(n).padStart(2,'0');
        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      }
    }
    return text;
  };
  const unmount=root=>{
    if(!root)return;
    mountLoads.delete(root);
    root.onclick=null;
    root.onchange=null;
    root.oninput=null;
    root.onsubmit=null;
  };
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
  async function mountPicker(root,{loggedIn=true}={}){
    const load=Symbol();pickerLoads.set(root,load);
    if(!loggedIn){availableSpecs=[];root.textContent='登录后查看生图规格与免费额度';return;}
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
    const load=Symbol();
    mountLoads.set(root,load);
    root.onchange=null;
    root.innerHTML='<p role="status">正在读取余额与权益…</p>';
    try{
      const [state,boot]=await Promise.all([api('/api/economy'),api('/api/boot')]);
      if(!root.isConnected||mountLoads.get(root)!==load)return;
      syncSharedEconomy(state,boot);
      const billing=boot.state?.billing||boot.billing||{};
      const packs=billing.packages||[];
      const purchaseRows=['cash','points'].map(purpose=>{
        const title=purpose==='cash'?'生图余额充值':'购买社区积分';
        const presets=packs.filter(p=>(p.purpose||'points')===purpose);
        if(!presets.length&&!billing.customPurchases)return '';
        return `<section class="economy-purchase-row" data-purchase-row="${purpose}"><h3>${title}</h3><div class="economy-cards">${presets.map(p=>`<article><strong>${purpose==='cash'?yuan(p.priceCents):p.credits+' 积分'}</strong><p>${esc(p.description)}</p><button type="button" data-purchase="${esc(p.id)}">支付 ${esc(p.priceDisplay)}</button></article>`).join('')}${billing.customPurchases?`<article><form data-custom-purchase="${purpose}"><label for="custom-${purpose}">自定义金额（元）</label><input id="custom-${purpose}" name="amountYuan" type="number" min="1" max="10000" step="1" required inputmode="numeric" placeholder="1–10000" aria-describedby="custom-${purpose}-hint"><p id="custom-${purpose}-hint" data-custom-hint>${purpose==='cash'?'充值 1–10000 元生图余额':'1 元 = 10 积分，可购买 10–100000 积分'}</p><button type="submit">${purpose==='cash'?'充值生图余额':'购买积分'}</button><p role="status" data-custom-message></p></form></article>`:''}</div></section>`;
      }).join('')||'<p>在线支付尚未配置，可通过社区贡献获得积分。</p>';
      root.innerHTML=`<section class="economy-wallet" data-wallet-page><div class="economy-page-head"><div><h1>钱包与权益</h1></div><a class="economy-nav-link" href="${esc(viewUrl('orders'))}" data-open-orders>订单记录 →</a></div><div class="economy-cards"><article><h2>生图余额</h2><strong>${yuan(state.cash.balanceCents)}</strong><p>冻结中 ${yuan(state.cash.heldCents)} · 仅用于图片生成</p></article><article><h2>社区积分</h2><strong>${state.points} 积分</strong><p>解锁内容与资源，不兑换现金或生图余额</p></article><article><h2>免费生图额度</h2>${state.freeQuota.map(q=>`<p>${esc(q.resolution.toUpperCase())} · 剩余 <strong>${q.remaining}</strong> 张 · 预占 ${q.held} 张</p>`).join('')}<p>一次性额度，长期有效；活动赠送按具体期限使用。</p></article></div><h2>充值与购买</h2><div class="economy-purchases">${purchaseRows}</div><h2>贡献与作者收益</h2><p>待结算 ${state.earnings.pending||0} 分 · 已结算 ${state.earnings.settled||0} 分 · 已冲回 ${state.earnings.reversed||0} 分。解锁分成80%，7天后可用。</p><p>账号验证20分；签到1分，每月最多20分；优质作品5分、原创资源20分、优质教程10分，每类每月最多10件。</p><button data-checkin>每日签到</button><details><summary>人民币余额明细</summary>${state.cashEntries.map(e=>`<p>${esc(cashEntryLabel(e.kind))} · ${yuan(e.delta_cents)} · 冻结变化 ${yuan(e.held_delta_cents)} · ${esc(e.created_at)}</p>`).join('')||'暂无明细'}</details><details><summary>社区积分明细</summary>${state.pointEntries.map(e=>`<p>${esc(e.reason)} · ${e.delta>0?'+':''}${e.delta} 分</p>`).join('')||'暂无明细'}</details><details><summary>已解锁内容与资源</summary>${state.unlocks.filter(u=>u.status==='settled').map(u=>`<p>${esc(u.target_id)} · ${u.target_type==='asset'?'站内持续使用权':'查看与复制'}</p>`).join('')||'暂无解锁'}</details><p role="status" data-message></p></section>`;
      const message=text=>{const target=root.querySelector('[data-message]');if(target)target.textContent=text;};
      const openCheckout=async body=>{const result=await api('/api/billing/checkout',{method:'POST',body});const url=result.checkoutUrl||result.order?.checkoutUrl;if(url)global.location.assign(url);else throw Error('支付地址暂未返回，请在订单记录中核验');};
      root.oninput=event=>{
        const form=event.target.closest('[data-custom-purchase]');if(!form)return;
        form.querySelector('[data-custom-message]').textContent='';
        const input=form.elements.amountYuan,amount=Number(input.value);
        form.querySelector('[data-custom-hint]').textContent=input.value&&input.validity.valid?`支付 ${yuan(amount*100)}，${form.dataset.customPurchase==='cash'?'充值等额生图余额':'获得 '+amount*10+' 积分'}`:(form.dataset.customPurchase==='cash'?'充值 1–10000 元生图余额':'1 元 = 10 积分，可购买 10–100000 积分');
      };
      root.onsubmit=async event=>{
        const form=event.target.closest('[data-custom-purchase]');if(!form)return;
        event.preventDefault();
        if(!form.reportValidity())return;
        const button=form.querySelector('button[type=submit]');if(button.disabled)return;
        button.disabled=true;
        try{await openCheckout({purpose:form.dataset.customPurchase,amountYuan:Number(form.elements.amountYuan.value)});}
        catch(e){form.querySelector('[data-custom-message]').textContent=e.message;}
        finally{button.disabled=false;}
      };
      root.onclick=async event=>{
        const ordersLink=event.target.closest?.('[data-open-orders]');
        if(ordersLink){goView(event,'orders');return;}
        const button=event.target.closest('button');if(!button||button.closest('[data-custom-purchase]')||button.disabled)return;button.disabled=true;
        try{
          if(button.dataset.purchase){await openCheckout({packId:button.dataset.purchase});}
          else if(button.hasAttribute('data-checkin')){const result=await api('/api/wallet/checkin',{method:'POST',body:{}});if(!root.isConnected||mountLoads.get(root)!==load)return;await mountWallet(root);message(`已签到，本次奖励 ${result.bonus} 积分，不改变生图额度。`);}
        }catch(e){message(e.message);}finally{button.disabled=false;}
      };
    }catch(e){if(root.isConnected&&mountLoads.get(root)===load)root.textContent=e.message;}
  }
  async function mountOrders(root,initial={}){
    root.oninput=null;
    root.onsubmit=null;
    const st={
      status:['all','pending','paid','refund','closed'].includes(initial.status)?initial.status:'all',
      purpose:['all','cash','points'].includes(initial.purpose)?initial.purpose:'all',
      page:Number(initial.page)>0?Math.floor(Number(initial.page)):1,
      limit:Number(initial.limit)>0?Math.min(50,Math.floor(Number(initial.limit))):20,
      notice:''
    };
    const statusTabs=[['all','全部状态'],['pending','待付款'],['paid','已到账'],['refund','退款/售后'],['closed','已关闭']];
    const renderOrderCard=o=>{
      const req=o.refundRequest||null;
      const activeRefund=req&&['pending','processing','unknown'].includes(req.status);
      const canRefund=['paid','partially_refunded'].includes(o.status)&&!activeRefund&&(o.refundableCents===undefined||o.refundableCents>0);
      const created=formatOrderTime(o.createdAt),paid=formatOrderTime(o.paidAt);
      let refundableText='';
      if(['paid','partially_refunded'].includes(o.status)&&!activeRefund&&o.refundableCents!==undefined){
        refundableText=o.refundableCents>0?`可退未消费：${yuan(o.refundableCents)}`:'未消费余额：¥0.00（已消费）';
      }
      const actions=[];
      if(o.status==='pending'){
        if(o.checkoutUrl&&/^(\/|https:\/\/)/i.test(String(o.checkoutUrl)))actions.push(`<a class="economy-btn-link is-primary" href="${esc(o.checkoutUrl)}">继续付款</a>`);
        actions.push(`<button type="button" data-sync="${esc(o.id)}">核验到账</button>`);
      }
      if(canRefund)actions.push(`<button type="button" data-refund="${esc(o.id)}">申请退还未消费部分</button>`);
      return `<article class="economy-order-card" data-order-row="${esc(o.id)}"><div class="economy-order-top"><div class="economy-order-badges"><strong>${o.purpose==='cash'?'生图余额充值':`购买社区积分${o.credits?`（${Number(o.credits)} 积分）`:''}`}</strong><span class="economy-badge is-${esc(o.status)}">${esc(paymentStatus(o.status))}</span>${req?`<span class="economy-badge is-refund" data-refund-status="${esc(req.status)}">退款${esc(paymentStatus(req.status,true))} · ${yuan(req.amountCents)}</span>`:''}</div><strong class="economy-order-amount">${yuan(o.amountCents)}</strong></div><div class="economy-order-meta"><span>订单号：${esc(o.id)}</span>${created?`<span>下单：${esc(created)}</span>`:''}${paid?`<span>到账：${esc(paid)}</span>`:''}${refundableText?`<span>${esc(refundableText)}</span>`:''}</div>${actions.length?`<div class="economy-order-actions">${actions.join('')}</div>`:''}</article>`;
    };
    const loadOrders=async()=>{
      const load=Symbol();
      mountLoads.set(root,load);
      if(!root.querySelector?.('[data-orders-page]'))root.innerHTML='<p role="status">正在读取订单记录…</p>';
      try{
        const qs=`status=${encodeURIComponent(st.status)}&purpose=${encodeURIComponent(st.purpose)}&page=${st.page}&limit=${st.limit}`;
        const data=await api('/api/billing/orders?'+qs);
        if(!root.isConnected||mountLoads.get(root)!==load)return;
        const totalPages=Math.max(1,Number(data.totalPages)||1);
        if(st.page>totalPages){st.page=totalPages;return loadOrders();}
        const items=data.orders||[];
        const totalCount=Number(data.total??items.length);
        const noticeText=st.notice;
        st.notice='';
        root.innerHTML=`<section class="economy-wallet economy-orders" data-orders-page><div class="economy-page-head"><div><h1>订单记录</h1><p class="economy-page-sub">生图余额充值与社区积分购买订单独立管理；可在此继续付款、核验到账或申请退还未消费本金。</p></div><a class="economy-nav-link" href="${esc(viewUrl('wallet'))}" data-open-wallet>← 返回钱包与权益</a></div><div class="economy-order-filters"><div class="economy-filter-tabs" role="group" aria-label="订单状态">${statusTabs.map(([k,label])=>`<button type="button" data-order-status="${k}" aria-pressed="${st.status===k?'true':'false'}">${label}</button>`).join('')}</div><div class="economy-filter-right"><select data-order-purpose aria-label="订单用途"><option value="all" ${st.purpose==='all'?'selected':''}>全部用途</option><option value="cash" ${st.purpose==='cash'?'selected':''}>生图余额充值</option><option value="points" ${st.purpose==='points'?'selected':''}>社区积分购买</option></select><span class="economy-order-count">共 ${totalCount} 笔</span></div></div>${items.length?items.map(renderOrderCard).join(''):`<div class="economy-empty" data-orders-empty><p>${st.status==='all'&&st.purpose==='all'?'暂无购买订单记录。':'当前筛选条件下暂无订单记录。'}</p><a class="economy-nav-link" href="${esc(viewUrl('wallet'))}" data-open-wallet>前往钱包充值与购买</a></div>`}${totalPages>1?`<nav class="economy-pagination" aria-label="订单分页"><button type="button" data-order-page="${st.page-1}" ${st.page<=1?'disabled':''}>上一页</button><span>第 ${st.page} / ${totalPages} 页</span><button type="button" data-order-page="${st.page+1}" ${st.page>=totalPages?'disabled':''}>下一页</button></nav>`:''}<p role="status" aria-live="polite" data-message>${esc(noticeText)}</p></section>`;
      }catch(e){
        if(!root.isConnected||mountLoads.get(root)!==load)return;
        const msgEl=root.querySelector?.('[data-message]');
        if(msgEl)msgEl.textContent=e.message;
        else root.textContent=e.message;
      }
    };
    root.onchange=event=>{
      const select=event.target.closest?.('[data-order-purpose]');
      if(!select)return;
      st.purpose=select.value||'all';
      st.page=1;
      loadOrders();
    };
    root.onclick=async event=>{
      const walletLink=event.target.closest?.('[data-open-wallet]');
      if(walletLink){goView(event,'wallet');return;}
      const button=event.target.closest('button');
      if(!button||button.disabled)return;
      if(button.dataset.orderStatus){
        st.status=button.dataset.orderStatus;
        st.page=1;
        await loadOrders();
        return;
      }
      if(button.dataset.orderPage){
        st.page=Math.max(1,Number(button.dataset.orderPage)||1);
        await loadOrders();
        return;
      }
      if(!button.dataset.sync&&!button.dataset.refund)return;
      button.disabled=true;
      const activeLoad=mountLoads.get(root);
      try{
        if(button.dataset.sync){
          const res=await api(`/api/billing/orders/${encodeURIComponent(button.dataset.sync)}/sync`,{method:'POST',body:{}});
          if(!root.isConnected||mountLoads.get(root)!==activeLoad)return;
          const eco=await api('/api/economy').catch(()=>null);
          if(eco&&mountLoads.get(root)===activeLoad)syncSharedEconomy(eco);
          const nextStatus=res?.order?.status;
          st.notice=nextStatus==='paid'?'支付已核验到账，余额或积分已同步更新。':nextStatus==='pending'?'订单暂未确认到账，如已付款请稍等数秒后再次核验。':'订单状态已核验更新。';
          await loadOrders();
        }else if(button.dataset.refund){
          await api('/api/billing/refund-requests',{method:'POST',body:{orderId:button.dataset.refund,reason:'申请退还未消费部分'}});
          if(!root.isConnected||mountLoads.get(root)!==activeLoad)return;
          const eco=await api('/api/economy').catch(()=>null);
          if(eco&&mountLoads.get(root)===activeLoad)syncSharedEconomy(eco);
          st.notice='退款申请已提交，未消费部分已冻结，等待管理员审核。';
          await loadOrders();
        }
      }catch(e){
        if(!root.isConnected||mountLoads.get(root)!==activeLoad)return;
        const msgEl=root.querySelector?.('[data-message]');
        if(msgEl)msgEl.textContent=e.message;
      }finally{
        if(button.isConnected)button.disabled=false;
      }
    };
    await loadOrders();
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
  global.HandrawEconomy={quote,confirm,mountWallet,mountOrders,mountAdmin,mountPicker,unmount,yuan,get specId(){return chosenSpec;},get specs(){return availableSpecs;}};
})(window);
