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

(async () => {
  const adminSrc = fs.readFileSync("demo/assets/admin-app.js", "utf8");
  const elements = {};
  function getEl(id) {
    if (!elements[id]) {
      elements[id] = { id, innerHTML: "", value: "", addEventListener: () => {}, querySelectorAll: () => [], appendChild: () => {}, remove: () => {} };
    }
    return elements[id];
  }
  let domReady = null;
  let requestedUsersUrl = "";
  const context = {
    window: {
      location: {
        search: "?module=users&q=alice",
        protocol: "http:",
        hostname: "localhost",
        port: "3080",
        pathname: "/admin.html"
      },
      addEventListener: () => {},
      history: { replaceState: () => {} }
    },
    document: {
      getElementById: (id) => getEl(id),
      querySelectorAll: () => [],
      createElement: (tag) => ({ tagName: tag, classList: { add: () => {} }, style: {}, appendChild: () => {}, remove: () => {} }),
      body: { appendChild: () => {} },
      addEventListener: (event, fn) => {
        if (event === "DOMContentLoaded") domReady = fn;
      }
    },
    URLSearchParams,
    fetch: async (url) => {
      if (url.includes("/api/boot")) return { ok: true, status: 200, json: async () => ({ user: { loggedIn: true, role: "admin", username: "admin" } }) };
      if (url.includes("/api/admin/permissions")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            profile: {
              effectiveRole: "admin",
              allowedModules: ["dashboard", "users", "works", "catalog", "governance", "gateway", "settings"],
              capabilities: { manage_users: true }
            }
          })
        };
      }
      if (url.includes("/api/admin/users")) {
        requestedUsersUrl = url;
        return { ok: true, status: 200, json: async () => ({ items: [] }) };
      }
      if (url.includes("/api/admin/dashboard")) return { ok: true, status: 200, json: async () => ({ kpis: {} }) };
      return { ok: true, status: 200, json: async () => ({}) };
    },
    setTimeout,
    clearTimeout,
    console
  };
  vm.createContext(context);
  vm.runInContext(adminSrc, context);
  assert.ok(domReady, "DOMContentLoaded listener should be registered");
  await domReady();
  const root = context.document.getElementById("admin-root");
  assert.match(root.innerHTML, /id="flt-users-q"[^>]*value="alice"/);
  assert.match(requestedUsersUrl, /q=alice/);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});

