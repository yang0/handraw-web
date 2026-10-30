"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function getFunction(path, name) {
  const src = fs.readFileSync(path,"utf8");
  const start = src.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  return src.slice(start,src.indexOf("\n  function ",start+1));
}
for (const [file,name,params] of [["shared.js","channelUrl",{view:"topic",id:"a b"}],["admin-app.js","channelHref","view=topic&id=a+b"]]) {
  const window = {location:{protocol:"http:",hostname:"127.0.0.1",port:"3080"}};
  const context = {window,URLSearchParams};
  vm.createContext(context);
  vm.runInContext(getFunction(`demo/assets/${file}`,name),context);
  for (const [channel,path] of Object.entries({main:"/",studio:"/studio/",forum:"/forum/",admin:"/admin/"})) {
    assert.equal(context[name](channel,params),`${path}?view=topic&id=a+b`);
  }
  window.location.port="8127";
  assert.equal(context[name]("forum"),"/forum/","arbitrary local ports must stay on the same origin");
  window.location = {protocol:"https:",hostname:"forum.handraw-style.com",port:""};
  for (const [channel,host] of Object.entries({main:"handraw-style.com",studio:"studio.handraw-style.com",forum:"forum.handraw-style.com",admin:"admin.handraw-style.com"})) {
    assert.equal(context[name](channel),`https://${host}/`);
  }
  window.location={protocol:"http:",hostname:"admin.localhost",port:"3080"};
  assert.equal(context[name]("main"),"http://localhost:3080/");
  assert.equal(context[name]("studio"),"http://studio.localhost:3080/");
}
console.log("Single backend navigation: same-origin local paths and production subdomains passed");

{
  const context={window:{location:{protocol:'http:',hostname:'127.0.0.1',port:'3080'}},URLSearchParams,App:{resourceMap:new Map([['IG-001',{kind:'layout'}]])}};
  vm.createContext(context);
  vm.runInContext(getFunction('demo/assets/shared.js','channelUrl'),context);
  assert.equal(context.channelUrl('main',{view:'asset',id:'IG-001'}),'/forum/?view=resource&kind=layout&id=IG-001');
  assert.equal(context.channelUrl('main',{view:'asset',id:'PENDING-STYLE',tab:'comments'}),'/forum/?view=resource&kind=asset&id=PENDING-STYLE&focus=comment');
  assert.equal(context.channelUrl('main',{view:'work',id:'work_one',focus:'comment'}),'/forum/?view=resource&kind=work&id=work_one&focus=comment');
  assert.equal(context.channelUrl('main',{view:'asset',id:'IG-001',tab:'topics'}),'/forum/?view=related&kind=layout&id=IG-001&tab=topics');
  context.window.location={protocol:'https:',hostname:'handraw-style.com',port:''};
  assert.equal(context.channelUrl('main',{view:'work',id:'work_one'}),'https://forum.handraw-style.com/?view=resource&kind=work&id=work_one');
  vm.runInContext(getFunction('demo/assets/forum-resources.js','topicUrl'),context);
  assert.equal(context.topicUrl('ordinary_topic'),'https://forum.handraw-style.com/?view=topic&id=ordinary_topic');
}
