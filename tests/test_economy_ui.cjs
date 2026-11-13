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
