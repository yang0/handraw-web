const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const code = fs.readFileSync("demo/assets/studio-prompt-engine.js", "utf8");
const ctx = { window: {}, console };
vm.createContext(ctx);
vm.runInContext(code, ctx);
const E = ctx.window.HANDRAW_CANVAS_ENGINE;

// Explicit conversion copies configuration, preserving the archived graph.
const legacy={nodes:[
  {id:"text",type:"text_input",data:{text:"A woodland cabin"}},
  {id:"skill",type:"skill_params",data:{style1:"FA-001",layout:"IG-001",audience:"Readers"}},
  {id:"output",type:"output_control",data:{mode:"single",count:2,ratio:"16:9"}}
],edges:[{from:"text",to:"output"},{from:"skill",to:"output"}]};
const beforeLegacy=JSON.stringify(legacy);
const converted=E.convertLegacyCanvas(legacy,{resourceMap:new Map(),styles:[],layouts:[],colors:[],tones:[]});
assert.equal(JSON.stringify(legacy),beforeLegacy);
assert.equal(converted.nodes.find(n=>n.parameter==="prompt").values.length,2);
assert.ok(converted.nodes.find(n=>n.parameter==="prompt").values.every(v=>v.includes("A woodland cabin")));
assert.equal(converted.nodes.find(n=>n.type==="output").mode,"zip");
assert.throws(()=>E.convertLegacyCanvas({nodes:[{type:"article_plan"}],edges:[]},{}),/文章/);

console.log("Starting Article Blocks & Prompt Engine Tests...");

// Test Article F1
const F1 = `# 留白工作法

当我们把日历塞满会议时，大脑失去了呼吸缝隙。

## 一、塞满的日程表

现代职场最大的幻觉，是把响应速度当成产出质量。

## 二、像画水彩一样管理精力

桑贝的画里总有大片空白。

## 三、每日微停顿仪式

离开屏幕，下楼走两条街。`;

// 1. F1 withLines
const bF1 = E.parseArticleReadonlyBlocks(F1, { withLines: true, noStarter: true });
assert.equal(bF1.length, 8, "F1 must have 8 blocks");
assert.equal(bF1[0].kind, "h1");
assert.equal(bF1[0].startLine, 0);
assert.equal(bF1[0].endLine, 0);
assert.equal(bF1[1].kind, "p");
assert.equal(bF1[1].startLine, 2);
assert.equal(bF1[1].endLine, 2);
assert.equal(bF1[2].kind, "h2");
assert.equal(bF1[2].startLine, 4);
assert.equal(bF1[2].endLine, 4);
assert.equal(bF1[3].kind, "p");
assert.equal(bF1[3].startLine, 6);
assert.equal(bF1[3].endLine, 6);
assert.equal(bF1[4].kind, "h2");
assert.equal(bF1[4].startLine, 8);
assert.equal(bF1[4].endLine, 8);
assert.equal(bF1[5].kind, "p");
assert.equal(bF1[5].startLine, 10);
assert.equal(bF1[5].endLine, 10);
assert.equal(bF1[6].kind, "h2");
assert.equal(bF1[6].startLine, 12);
assert.equal(bF1[6].endLine, 12);
assert.equal(bF1[7].kind, "p");
assert.equal(bF1[7].startLine, 14);
assert.equal(bF1[7].endLine, 14);

console.log("✓ Test 1: Article F1 line boundaries verified");

// 2. noStarter: true with empty or whitespace-only text
const bEmpty = E.parseArticleReadonlyBlocks("", { noStarter: true });
assert.deepEqual(bEmpty, [], "empty markdown with noStarter: true must return []");
const bSpace = E.parseArticleReadonlyBlocks("   \n\n  ", { noStarter: true });
assert.deepEqual(bSpace, [], "whitespace markdown with noStarter: true must return []");

console.log("✓ Test 2: noStarter: true with empty input verified");

// 3. Backward compatibility (no options)
const bDef = E.parseArticleReadonlyBlocks("");
assert.ok(bDef.length > 0, "empty markdown with default options must return starter article");
assert.equal(bDef[0].kind, "h1");
assert.strictEqual(bDef[0].startLine, undefined, "default options must NOT have startLine");
assert.strictEqual(bDef[0].endLine, undefined, "default options must NOT have endLine");

console.log("✓ Test 3: Backward compatibility (no options) verified");

// 4. Complex multi-line paragraphs, code block, quote
const complex = `Line 0 heading
# Title

Line 3 para A
Line 4 para B

\`\`\`javascript
const x = 1;
const y = 2;
\`\`\`

> Quote line 1
> Quote line 2`;

const bComplex = E.parseArticleReadonlyBlocks(complex, { withLines: true });
assert.equal(bComplex[0].kind, "p");
assert.equal(bComplex[0].startLine, 0);
assert.equal(bComplex[0].endLine, 0);
assert.equal(bComplex[1].kind, "h1");
assert.equal(bComplex[1].startLine, 1);
assert.equal(bComplex[1].endLine, 1);
assert.equal(bComplex[2].kind, "p");
assert.equal(bComplex[2].startLine, 3);
assert.equal(bComplex[2].endLine, 4);
assert.equal(bComplex[3].kind, "code");
assert.equal(bComplex[3].startLine, 6);
assert.equal(bComplex[3].endLine, 9);
assert.equal(bComplex[4].kind, "blockquote");
assert.equal(bComplex[4].startLine, 11);
assert.equal(bComplex[4].endLine, 12);

console.log("✓ Test 4: Multi-line buffers and code block line tracking verified");

// 5. buildArticlePlanFromAi verification
const mockAiResp = {
  ok: true,
  source: "model",
  articleType: "knowledge",
  cover: {
    subject: "封面主题描述",
    purpose: "定位文章核心",
    layout: "SC-021"
  },
  illustrations: [
    {
      afterBlockIdx: 2,
      anchorText: "## 一、塞满的日程表",
      subject: "插图1描述",
      purpose: "说明时间管理",
      layout: "IG-013",
      imageType: "process"
    },
    {
      afterBlockIdx: 4,
      anchorText: "## 二、像画水彩一样",
      subject: "插图2描述",
      purpose: "说明精力留白",
      layout: "SC-001",
      imageType: "concept"
    }
  ]
};

const aiCards = E.buildArticlePlanFromAi(mockAiResp);
assert.equal(aiCards.length, 3, "Cover + 2 illustrations = 3 cards");
assert.equal(aiCards[0].role, "cover");
assert.equal(aiCards[0].afterBlockIdx, -1);
assert.equal(aiCards[0].subject, "封面主题描述");
assert.equal(aiCards[0].articleType, "knowledge");
assert.equal(aiCards[0].status, "idle");

assert.equal(aiCards[1].role, "inline");
assert.equal(aiCards[1].afterBlockIdx, 2);
assert.equal(aiCards[1].layoutId, "IG-013");
assert.equal(aiCards[1].imageType, "process");
assert.equal(aiCards[1].status, "idle");

assert.equal(aiCards[2].role, "inline");
assert.equal(aiCards[2].afterBlockIdx, 4);
assert.equal(aiCards[2].layoutId, "SC-001");
assert.equal(aiCards[2].imageType, "concept");

console.log("✓ Test 5: buildArticlePlanFromAi card transformation verified");

// 6. buildEditorSegments with F1 and template plan cards
const f1Cards = [
  { role: "cover", afterBlockIdx: -1 },
  { role: "inline", afterBlockIdx: 2 },
  { role: "inline", afterBlockIdx: 4 },
  { role: "inline", afterBlockIdx: 6 }
];
const f1Segs = E.buildEditorSegments(F1, f1Cards);
assert.equal(f1Segs.length, 4, "F1 with cuts at 2, 4, 6 must produce 4 segments");
assert.ok(f1Segs[0].text.startsWith("# 留白工作法"), "Seg 0 starts with # 留白工作法");
assert.ok(f1Segs[0].text.endsWith("## 一、塞满的日程表"), "Seg 0 ends with ## 一、塞满的日程表");
assert.equal(f1Segs[0].afterBlockIdx, 2);
assert.equal(f1Segs[1].afterBlockIdx, 4);
assert.equal(f1Segs[2].afterBlockIdx, 6);
assert.equal(f1Segs.map((s) => s.text).join("\n"), F1, "Joined segments must be byte-for-byte identical to F1");

console.log("✓ Test 6: buildEditorSegments F1 segmentation and lossless join verified");

// 7. buildEditorSegments empty cards -> 1 segment
const emptySegs = E.buildEditorSegments(F1, []);
assert.equal(emptySegs.length, 1);
assert.equal(emptySegs[0].text, F1);
assert.equal(emptySegs.map((s) => s.text).join("\n"), F1);

console.log("✓ Test 7: buildEditorSegments empty cards single segment verified");

console.log("\nAll Article Blocks & Prompt Engine Tests PASSED!\n");
