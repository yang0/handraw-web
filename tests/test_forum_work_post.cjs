"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const S={esc,resourceLabel:x=>x.name,channelUrl:(ch,p)=>`/${ch}/?${new URLSearchParams(p)}`,App:{}};
const ctx={window:{HANDRAW_SHARED:S}};vm.createContext(ctx);vm.runInContext(fs.readFileSync('demo/assets/forum-work-post.js','utf8'),ctx);
const W=ctx.window.HandrawForumWork;
const resources=new Map([['FA-001',{id:'FA-001',kind:'style',name:'测试画风',image:'/style.webp'}],['IG-001',{id:'IG-001',kind:'layout',name:'测试图型',image:'/layout.webp'}]]);
const topic={id:'topic-one',title:'作品分享',summary:'作者的真实点评',images:['/image.webp'],styles:['FA-001'],layout:'IG-001'};
assert.equal(W.fromTopic(topic,[],resources,false),null,'images plus references stay ordinary');
assert.equal(W.fromTopic({...topic,recipe:{sharedCard:{kind:'style',id:'FA-001'}}},[],resources,false),null);
assert.equal(W.fromTopic({...topic,workId:'missing'},[],resources,false),null);
assert.equal(W.fromTopic({...topic,workId:'empty'},[{id:'empty',prompt:'  ',images:['/image.webp']}],resources,false),null,'unreproducible image posts are not works');
const recipe={theme:'真正的生图提示词',style1:'FA-001',layout:'IG-001',ratio:'16:9',mode:'pure-image'};
const model=W.fromTopic({...topic,recipe},[],resources,true);
assert.equal(model.prompt,recipe.theme);assert.equal(model.canFork,true);assert.match(model.forkUrl,/entry=quick&forkTopic=topic-one/);
assert.equal(model.images.length,1);assert.equal(model.assets.length,2);
const html=W.render(model);
assert.ok(html.indexOf('fwp-gallery')<html.indexOf('生图提示词'));
assert.ok(html.indexOf('生图提示词')<html.indexOf('作者点评'));
assert.ok(html.indexOf('作者点评')<html.indexOf('使用的画风与图型'));
assert.match(html,/做同款/);assert.match(html,/data-hw-src="\/style.webp"/);assert.match(html,/data-hw-src="\/layout.webp"/);
assert.doesNotMatch(html,/<img[^>]*\ssrc=/,'initial image loading uses existing queue');
const paid=W.fromTopic({...topic,price:5,recipe},[],resources,false);
assert.equal(paid.locked,true);assert.equal(paid.prompt,'');assert.equal(paid.canFork,false);
assert.doesNotMatch(W.render(paid),/真正的生图提示词|forkTopic|data-fwp-copy/);
const work={id:'work-one',title:'真实作品',images:['/work.webp','/second.webp'],prompt:'实际作品提示词',promptMasked:false,styles:['FA-001'],layout:'IG-001',mode:'poster'};
const actual=W.fromTopic({...topic,workId:work.id},[work],resources,true);
assert.equal(actual.prompt,'FA-001, IG-001, 主题：实际作品提示词');assert.match(actual.forkUrl,/entry=canvas&fork=work-one/,'unsupported form modes retain their actual canvas configuration');
assert.equal(actual.images.length,2);
const masked=W.fromTopic({...topic,workId:work.id},[{...work,prompt:'PRIVATE_MASKED_PREFIX',promptMasked:true,price:5}],resources,true);
assert.equal(masked.prompt,'');assert.equal(masked.canFork,false);assert.doesNotMatch(W.render(masked),/PRIVATE_MASKED_PREFIX/);
assert.equal(W.fromTopic({...topic,workId:work.id},[{...work,reproducible:false}],resources,true),null);

// Old work without subject: styles, layout, prompt
const oldWork = {id:'w-old', title:'梅雨天里的一碗面', images:['/img.webp'], styles:['FE-012'], layout:'SC-021', prompt:'手绘风插画，雨中街角面馆，……社论插画感', subject:''};
const oldModel = W.fromTopic({id:'t-old', workId:'w-old'}, [oldWork], resources, true);
assert.equal(oldModel.prompt, 'FE-012, SC-021, 主题：手绘风插画，雨中街角面馆，……社论插画感');
assert.match(W.render(oldModel), /<pre class="fwp-prompt-text">FE-012, SC-021, 主题：手绘风插画，雨中街角面馆，……社论插画感<\/pre>/);

// New work with subject: uses subject over prompt
const newWork = {id:'w-new', title:'新作品', images:['/img.webp'], styles:['FE-012'], layout:'SC-021', prompt:'手绘风插画，雨中街角面馆，……社论插画感', subject:'雨中街角面馆，热气腾腾的一碗汤面'};
const newModel = W.fromTopic({id:'t-new', workId:'w-new'}, [newWork], resources, true);
assert.equal(newModel.prompt, 'FE-012, SC-021, 主题：雨中街角面馆，热气腾腾的一碗汤面');

// Fusion work: two styles, with layout
const fusionWork = {id:'w-fus', title:'融合作品', images:['/img.webp'], styles:['FE-012', 'FA-001'], layout:'SC-021', prompt:'老提示词', subject:'雨中街角面馆'};
const fusionModel = W.fromTopic({id:'t-fus', workId:'w-fus'}, [fusionWork], resources, true);
assert.equal(fusionModel.prompt, 'FE-012, FA-001, SC-021, 主题：雨中街角面馆');

// Fusion work: no layout (omitted)
const noLayoutWork = {id:'w-nl', title:'无图型作品', images:['/img.webp'], styles:['FE-012', 'FA-001'], layout:'', prompt:'老提示词', subject:'雨中街角面馆'};
const noLayoutModel = W.fromTopic({id:'t-nl', workId:'w-nl'}, [noLayoutWork], resources, true);
assert.equal(noLayoutModel.prompt, 'FE-012, FA-001, 主题：雨中街角面馆');

// Original text already contains code -> not repeated
const dupWork = {id:'w-dup', title:'已有编号作品', images:['/img.webp'], styles:['FE-012'], layout:'SC-021', prompt:'FE-012, 雨中街角面馆'};
const dupModel = W.fromTopic({id:'t-dup', workId:'w-dup'}, [dupWork], resources, true);
assert.equal(dupModel.prompt, 'SC-021, 主题：FE-012, 雨中街角面馆');

const bothDupWork = {id:'w-bdup', title:'已有全部编号作品', images:['/img.webp'], styles:['FE-012'], layout:'SC-021', prompt:'FE-012, SC-021, 雨中街角面馆'};
const bothDupModel = W.fromTopic({id:'t-bdup', workId:'w-bdup'}, [bothDupWork], resources, true);
assert.equal(bothDupModel.prompt, '主题：FE-012, SC-021, 雨中街角面馆');

// No codes at all
const noCodeWork = {id:'w-nc', title:'无编号作品', images:['/img.webp'], styles:[], layout:'', prompt:'老提示词', subject:'雨中街角面馆'};
const noCodeModel = W.fromTopic({id:'t-nc', workId:'w-nc'}, [noCodeWork], resources, true);
assert.equal(noCodeModel.prompt, '主题：雨中街角面馆');

// Copy button copies formatted prompt
let copiedText = '';
const mockRoot = {
  querySelector: sel => sel === '[data-fwp-copy]' ? {
    addEventListener: (evt, handler) => { mockRoot._handler = handler; }
  } : null,
  querySelectorAll: () => []
};
ctx.navigator = { clipboard: { writeText: async txt => { copiedText = txt; } } };
W.bind(mockRoot, newModel);
mockRoot._handler();
assert.equal(copiedText, 'FE-012, SC-021, 主题：雨中街角面馆，热气腾腾的一碗汤面');
const hostile=W.render({...model,prompt:'<script>bad()</script>',notes:'<img onerror=bad()>',images:['javascript:bad()','//evil.test/x'],assets:[{id:'FA-001',kind:'style',label:'<b>bad</b>',image:'data:x'}]});
assert.doesNotMatch(hostile,/<script>|<img onerror|javascript:|src="data:|src="\/\/evil/);
assert.match(hostile,/&lt;script&gt;/);
console.log('Forum work posts: classification, real reproduction, locked privacy, ordered content, picture attachments and escaping passed');
