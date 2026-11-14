const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('demo/assets/economy-ui.js','utf8');
function setup(api){
  const window={HANDRAW_SHARED:{apiJson:api}};
  const context=vm.createContext({window,WeakMap,Symbol,Map,Promise,Number,String,Error,Object,JSON});
  vm.runInContext(source,context);
  return window.HandrawEconomy;
}
const spec=(id,extra={})=>({id,name:'标准规格',enabled:true,verified:true,priceCents:25,...extra});
function root(){return {isConnected:true,innerHTML:'',textContent:'',select:{},querySelector(){return this.select;}};}

test('guests do not query private economy data and sign-out fences an in-flight picker',async()=>{
  let calls=0,finish;
  const ui=setup(()=>{calls++;return new Promise(resolve=>finish=resolve);});
  const el=root();await ui.mountPicker(el,{loggedIn:false});assert.equal(calls,0);
  const pending=ui.mountPicker(el);
  await ui.mountPicker(el,{loggedIn:false});
  finish({specs:[spec('private')]});await pending;
  assert.match(el.textContent,/登录后/);assert.equal(el.innerHTML,'');
});
test('the displayed first valid specification is actually submitted; unverified specs stay unavailable',async()=>{
  let body;
  const ui=setup(async(path,opts)=>{if(path.endsWith('/quote')){body=opts.body;return {ok:true};}return {specs:[spec('unverified',{verified:false}),spec('active-2k')]};});
  const el=root();await ui.mountPicker(el);
  assert.equal(ui.specId,'active-2k');assert(!el.innerHTML.includes('unverified'));
  await ui.quote([{ratio:'16:9',slotPosition:3}]);
  assert.equal(body.items[0].specId,'active-2k');assert.equal(body.items[0].ratio,'16:9');assert.equal(body.items[0].slotPosition,3);
  assert(!('credits' in body));assert(!('amountCents' in body));
});
test('late requests from the previous account cannot replace the current specification picker',async()=>{
  const requests=[];const ui=setup(()=>new Promise(resolve=>requests.push(resolve)));
  const el=root();const old=ui.mountPicker(el),current=ui.mountPicker(el);
  requests[1]({specs:[spec('current')]});await current;
  requests[0]({specs:[spec('stale')]});await old;
  assert.equal(ui.specId,'current');assert(el.innerHTML.includes('current'));assert(!el.innerHTML.includes('stale'));
});
test('unavailable and unauthenticated specification loads clear previous choices',async()=>{
  let state={specs:[spec('active')]};const ui=setup(async()=>{if(state instanceof Error)throw state;return state;});
  const el=root();await ui.mountPicker(el);state=new Error('请登录');await ui.mountPicker(el);
  assert.equal(ui.specs.length,0);assert.equal(el.textContent,'请登录');
  state={specs:[spec('disabled',{enabled:false})]};await ui.mountPicker(el);
  assert.equal(el.textContent,'暂无已验证开放的生图规格');
});
test('specification names are escaped and money remains integer cents until presentation',async()=>{
  const ui=setup(async()=>({specs:[spec('safe',{name:'<img src=x onerror=alert(1)>'})]}));
  const el=root();await ui.mountPicker(el);assert(!el.innerHTML.includes('<img'));assert(el.innerHTML.includes('&lt;img'));
  assert.equal(ui.yuan(1),'¥0.01');assert.equal(ui.yuan(101),'¥1.01');
});

test('wallet check-in does not fetch orders; mountOrders sync and refund work and fence stale loads',async()=>{
  const calls=[];
  const state={cash:{balanceCents:1000,heldCents:0},points:0,freeQuota:[],earnings:{},cashEntries:[],pointEntries:[],unlocks:[]};
  const ui=setup(async(path)=>{
    calls.push(path);
    if(path==='/api/economy')return state;
    if(path==='/api/boot')return {billing:{packages:[]}};
    if(path==='/api/wallet/checkin'){state.points=1;return {bonus:1};}
    if(path.startsWith('/api/billing/orders?'))return {orders:[
      {id:'ord_pending',purpose:'cash',status:'pending',amountCents:1000,checkoutUrl:'/checkout/ord_pending'},
      {id:'ord_paid',purpose:'cash',status:'paid',amountCents:1000,refundableCents:1000},
      {id:'ord_consumed',purpose:'cash',status:'paid',amountCents:500,refundableCents:0},
      {id:'ord_refunding',purpose:'cash',status:'paid',amountCents:2000,refundableCents:0,refundRequest:{id:'ref_1',status:'pending',amountCents:2000}},
    ],total:4,page:1,pageSize:12,totalPages:1};
    if(path==='/api/billing/refund-requests'){state.cash={balanceCents:0,heldCents:1000};return {ok:true};}
    return {ok:true};
  });
  const status={textContent:''};
  const walletEl={isConnected:true,innerHTML:'',querySelector:()=>status};
  await ui.mountWallet(walletEl);
  assert(!calls.some(p=>p.startsWith('/api/billing/orders')),'wallet must not fetch orders list');
  assert(walletEl.innerHTML.includes('data-open-orders'));
  assert(!walletEl.innerHTML.includes('data-refund'));
  const clickEl=async(targetEl,dataset)=>{
    const button={type:'submit',disabled:false,isConnected:true,dataset,closest:()=>null,hasAttribute:name=>name==='data-checkin'&&dataset.checkin!==undefined};
    await targetEl.onclick({target:{closest:sel=>sel==='button'?button:null}});
    assert.equal(button.disabled,false);
  };
  await clickEl(walletEl,{checkin:''});
  assert(calls.includes('/api/wallet/checkin'));
  assert(walletEl.innerHTML.includes('1 积分'));
  assert(status.textContent.includes('本次奖励 1 积分'));
  const before=calls.length;
  await walletEl.onclick({target:{closest:sel=>sel==='button'?({type:'submit',closest:()=>({}),disabled:false}):null}});
  assert.equal(calls.length,before,'custom purchase form submits through its own handler only');

  const ordersEl={isConnected:true,innerHTML:'',querySelector:sel=>sel==='[data-message]'?status:null};
  await ui.mountOrders(ordersEl);
  assert(ordersEl.innerHTML.includes('data-order-row="ord_pending"'));
  assert(ordersEl.innerHTML.includes('可退未消费：¥10.00'));
  assert(ordersEl.innerHTML.includes('未消费余额：¥0.00（已消费）'));
  assert(ordersEl.innerHTML.includes('data-refund="ord_paid"'));
  assert(!ordersEl.innerHTML.includes('data-refund="ord_consumed"'));
  assert(!ordersEl.innerHTML.includes('data-refund="ord_refunding"'));
  assert(ordersEl.innerHTML.includes('data-refund-status="pending"'));
  await clickEl(ordersEl,{sync:'ord_pending'});
  assert(calls.includes('/api/billing/orders/ord_pending/sync'));
  await clickEl(ordersEl,{refund:'ord_paid'});
  assert(calls.includes('/api/billing/refund-requests'));
  assert(ordersEl.innerHTML.includes('退款申请已提交'));
  ui.unmount(ordersEl);
  assert.equal(ordersEl.onclick,null);
  assert.equal(ordersEl.onchange,null);
});

test('mountOrders escapes order fields, sends filters/pagination, and fences stale responses',async()=>{
  const pendingResolvers=[];
  const requestedPaths=[];
  const ui=setup(async(path)=>{
    requestedPaths.push(path);
    return new Promise(resolve=>pendingResolvers.push(resolve));
  });
  const ordersEl={isConnected:true,innerHTML:'',querySelector:()=>null};
  const firstMount=ui.mountOrders(ordersEl);
  const filterClick=ordersEl.onclick({target:{closest:sel=>sel==='button'?{dataset:{orderStatus:'paid'},disabled:false,closest:()=>null}:null}});
  assert.equal(requestedPaths.length,2);
  assert(requestedPaths[1].includes('status=paid&purpose=all&page=1&limit=20'));
  pendingResolvers[1]({orders:[{id:'ord_<img src=x>',purpose:'points',credits:50,status:'paid',amountCents:500}],total:25,page:1,pageSize:20,totalPages:2});
  pendingResolvers[0]({orders:[{id:'ord_stale_row',purpose:'cash',status:'pending',amountCents:1000}],total:1,page:1,pageSize:20,totalPages:1});
  await Promise.all([firstMount,filterClick]);
  assert(ordersEl.innerHTML.includes('ord_&lt;img src=x&gt;'));
  assert(!ordersEl.innerHTML.includes('<img'));
  assert(!ordersEl.innerHTML.includes('ord_stale_row'));
  assert(ordersEl.innerHTML.includes('第 1 / 2 页'));
  const secondPage=ordersEl.onclick({target:{closest:sel=>sel==='button'?{dataset:{orderPage:'2'},disabled:false,closest:()=>null}:null}});
  assert(requestedPaths[2].includes('status=paid&purpose=all&page=2&limit=20'));
  pendingResolvers[2]({orders:[],total:25,page:2,pageSize:20,totalPages:2});
  await secondPage;
  assert(ordersEl.innerHTML.includes('当前筛选条件下暂无订单记录'));
});
