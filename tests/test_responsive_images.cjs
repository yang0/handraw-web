"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let now=0,seq=0,io,ro,mutation;
const timers=new Map(),requests=[];
function advance(ms){const end=now+ms;for(let i=0;i<10000;i++){const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next){now=end;return;}timers.delete(next[0]);now=next[1].at;next[1].fn();}throw Error('timer loop');}
class Img {
 constructor(width=32){this.dataset={};this.isConnected=true;this.nodeType=1;this.clientWidth=width;this.clientHeight=width;this.complete=false;this.naturalWidth=0;this.naturalHeight=0;this.listeners={};this.style={};const classes=new Set();this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)};}
 getBoundingClientRect(){return {width:this.clientWidth,height:this.clientHeight,left:0,right:this.clientWidth,top:0,bottom:this.clientHeight};}
 getClientRects(){return [{}];}
 matches(selector){return selector==='img'||selector==='img[data-hw-src]';}
 querySelectorAll(){return [];}
 getAttribute(name){return name==='src'?this.src:null;}
 addEventListener(name,fn){this.listeners[name]=fn;}
 removeEventListener(name,fn){if(this.listeners[name]===fn)delete this.listeners[name];}
 set src(value){this._src=value;this.complete=false;requests.push(value);}
 get src(){return this._src;}
 finish(){this.complete=true;this.naturalWidth=2000;this.naturalHeight=2000;this.listeners.load?.();}
 fail(){this.complete=true;this.naturalWidth=0;this.listeners.error?.();}
}
const window={devicePixelRatio:2,innerWidth:1440,innerHeight:900,location:{origin:'https://handraw-style.com'},addEventListener(){}};
const doc={readyState:'complete',documentElement:{},querySelectorAll:()=>[],body:{append(){}},createElement:()=>({style:{},setAttribute(){},append(){},addEventListener(){}})};
vm.runInNewContext(fs.readFileSync('demo/assets/image-loader.js','utf8'),{window,document:doc,
 IntersectionObserver:class{constructor(fn){io=fn;}observe(){}unobserve(){}},ResizeObserver:class{constructor(fn){ro=fn;}observe(){}unobserve(){}},MutationObserver:class{constructor(fn){mutation=fn;}observe(){}},
 Date:{now:()=>now},setTimeout(fn,ms){const id=++seq;timers.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>timers.delete(id)});
const component=window.HandrawImages;
const avatar=new Img();component.set(avatar,'/avatars/u1-01234567890123456789.webp');advance(100);
assert.equal(avatar.src,'/avatars/u1-01234567890123456789.webp?w=96');avatar.finish();
avatar.clientWidth=240;ro([{target:avatar}]);advance(100);assert(avatar.src.endsWith('?w=480'));avatar.finish();
const count=requests.length;ro([{target:avatar}]);advance(100);assert.equal(requests.length,count,'same size does not refetch');
avatar.clientWidth=32;ro([{target:avatar}]);advance(100);assert.equal(requests.length,count,'shrinking reuses sharper decoded image');
assert.equal(component.original(avatar),'/avatars/u1-01234567890123456789.webp');
const card=new Img(320);component.set(card,'/images/portrait.jpg?version=one&w=1280#focus');advance(100);assert.equal(card.src,'/images/portrait.jpg?version=one&w=640#focus');card.finish();
const detail=new Img(1000);component.set(detail,'/images/portrait.jpg');advance(100);assert.equal(detail.src,'/images/portrait.jpg?w=2560');detail.finish();
const changing=new Img(200);component.set(changing,'/generated/old.png');advance(100);component.set(changing,'/generated/new.png');advance(100);assert.equal(changing.src,'/generated/new.png?w=480');changing.finish();assert.equal(changing.dataset.hwLoaded,changing.src);
const retry=new Img(200);component.set(retry,'/uploads/retry.png');advance(100);const retryUrl=retry.src;retry.fail();advance(500);assert.equal(requests.filter(url=>url===retryUrl).length,2,'identical failed URL is reassigned for a real retry');retry.finish();
for(const raw of ['data:image/png;base64,AA','blob:https://handraw-style.com/id','/assets/avatar-default.svg','/images/animated.gif','https://third.example/signed.jpg?w=7&signature=keep']){
 const img=new Img(200);component.set(img,raw);advance(100);assert.equal(img.src,raw);img.finish();
}
const dynamic=new Img(200);dynamic.dataset.hwSrc='/images/before.jpg';component.scan(dynamic);io([{target:dynamic,isIntersecting:true}]);advance(100);dynamic.finish();dynamic.dataset.hwSrc='/images/after.jpg';mutation([{type:'attributes',attributeName:'data-hw-src',target:dynamic}]);advance(100);assert.equal(dynamic.src,'/images/after.jpg?w=480');dynamic.finish();
for(const path of fs.readdirSync('demo/assets').filter(name=>name.endsWith('.js')&&name!=='image-loader.js')){
 const source=fs.readFileSync('demo/assets/'+path,'utf8');
 for(const tag of source.match(/<img\b[^>]*>/g)||[])assert(!/(?<![\w-])src=/.test(tag),path+' renders an eager unmanaged original');
}
for(const name of ['index','forum','studio','admin','checkout'])assert(fs.readFileSync('demo/'+name+'.html','utf8').includes('image-loader.js'),name+' must load the component');
assert.equal(fs.readFileSync('demo/assets/image-loader.js','utf8'),fs.readFileSync('plugin/public/image-loader.js','utf8'));
console.log('Responsive images: DPR, size buckets, resize, original receipts, source changes, real retry, passthrough types and application-wide coverage passed');
