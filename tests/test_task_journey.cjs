/* Fast, provider-free regression checks for async import task UX. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const code = fs.readFileSync(path.join(__dirname, "../demo/assets/task-journey.js"), "utf8");

function harness(responses) {
  const requests = [];
  const saved = new Map();
  const panel = {
    className: "", innerHTML: "",
    attrs: {},
    classList: {
      _v: new Set(),
      add(value) { this._v.add(value); },
      remove(value) { this._v.delete(value); },
      contains(value) { return this._v.has(value); }
    },
    setAttribute(key, value) { this.attrs[key] = value; },
    querySelector() { return null; }
  };
  const document = {
    readyState: "loading",
    getElementById(id) { return id === "hw-task-journey" && panel._created ? panel : null; },
    createElement(tag) { if (tag === "aside") { panel._created = true; return panel; } return {click(){},remove(){}}; },
    body: {appendChild(){}},
    addEventListener(){}
  };
  const win = {
    document, matchMedia: () => ({matches:false}),
    localStorage: {
      getItem(key) { return saved.get(key) || null; },
      setItem(key,value){ saved.set(key,value); },
      removeItem(key){ saved.delete(key); }
    },
    URL, Blob
  };
  const context = {window:win,document,Blob,URL,Date,console,
    setTimeout:(fn)=>{ fn(); return 1; },
    fetch:async (url,opts)=> {
      requests.push({url,opts});
      if (!responses.length) throw new Error("no more mocked requests");
      const next = responses.shift();
      return {ok:next.ok !== false,status:next.status || 200,
        json:async()=>next.body};
    }
  };
  vm.runInNewContext(code,context);
  return { api:win.HandrawTaskJourney, panel, saved, requests };
}

(async () => {
  const t = harness([
    {body:{ok:true,importId:"imp_test123"}},
    {body:{ok:true,status:"queued",stage:"queued",progress:{done:0,total:0}}},
    {body:{ok:true,status:"running",stage:"structuring",progress:{done:1,total:3}}},
    {body:{ok:true,status:"done",stage:"completed",progress:{done:3,total:3},
      result:{title:"测试标题",markdown:"# 测试标题\n\n第一段\n第二段",aiUsed:"all"}}}
  ]);
  let result;
  result = await t.api.submitImport("sample.docx","data:application/octet-stream;base64,YQ==",
    async () => true);
  assert.equal(result.title,"测试标题");
  assert.equal(result.markdown,"第一段\n第二段","do not duplicate the H1 shown in the editor");
  assert.equal(t.requests[0].url,"/api/studio/imports");
  assert.equal(t.requests.length,4);
  assert.equal(t.saved.size,0,"completed import should clear recovery token");
  assert.match(t.panel.innerHTML,/文档整理完成/);

  const failure = harness([
    {body:{ok:true,importId:"imp_fail"}},
    {body:{ok:true,status:"failed",stage:"failed",error:"解析文件失败",progress:{done:0,total:0}}}
  ]);
  await assert.rejects(() => failure.api.submitImport("bad.pdf","base64",async()=>true),/解析文件失败/);
  assert.match(failure.panel.innerHTML,/解析文件失败/);
  assert.equal(failure.saved.size,0);

  console.log("task-journey: async phases, H1 normalization, recovery cleanup and failure feedback OK");
})().catch(e => {console.error(e);process.exitCode=1;});
