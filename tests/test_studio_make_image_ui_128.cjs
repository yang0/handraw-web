"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const Make=require("../demo/assets/studio-make-image.js");
const Versions=require("../demo/assets/studio-make-image-versions.js");
const html=fs.readFileSync("demo/studio.html","utf8");
const css=fs.readFileSync("demo/assets/quick-create.css","utf8");
const app=fs.readFileSync("demo/assets/studio-app.js","utf8");
const code=fs.readFileSync("demo/assets/studio-make-image.js","utf8");
assert.ok(html.indexOf("studio-make-image-versions.js")<html.indexOf("studio-make-image.js"));
assert.match(css,/make-image-workspace-layout\s*\{/);
assert.match(css,/\.make-image-resource-group\s*\{/);
const styleArea=code.indexOf('class="make-image-resource-group"');
const firstPicker=code.indexOf('class="make-image-pickers-row',styleArea);
const fusionButton=code.indexOf('id="make-image-mode-fusion"',styleArea);
assert.ok(styleArea>=0&&fusionButton>styleArea&&firstPicker>fusionButton,
  "fusion toggle must live inside the style/layout picker decision group");

assert.match(css,/@media \(max-width:760px\)/);
assert.match(css,/make-image-settings-panel\.is-collapsed/);
assert.match(css,/make-image-version-strip/);
for(const id of ["make-image-subject","make-image-ratio-input","make-image-moods-input",
 "make-image-sc021-select","make-image-sc022-name","make-image-sc022-pinyin",
 "make-image-pick-tones","make-image-open-ref-picker","make-image-btn-run","make-image-btn-ai-plan"]){
 assert.ok(code.includes(id),id+" still supported");
}
for(const action of ["view","download","again","reference","variant","recipe","compare","series","canvas"]){
 assert.ok(code.includes('action==="'+action+'"'),"version action "+action);
}
assert.match(code,/this\.hostElement\.querySelector\?\.\("#make-image-primary-media"\)/);
assert.match(code,/fresh\.replaceWith\(preservedImage\)/);
assert.match(code,/setSelectionRange\(restore\.start,restore\.end\)/);
assert.match(app,/quickLastSubmittedSpec=JSON\.parse\(JSON\.stringify\(validated\.spec\)\)/);
assert.match(app,/CS\.quickAIPending=\{ctrlId:p\.ctrl\.id,report,signature:before\}/);
assert.doesNotMatch(app,/const decision=await AI\.confirmDifferences\(report,\{title:"审阅作图 AI 方案"\}\)/);
assert.match(app,/uploadReferenceFiles: async \(files\)/);
assert.match(app,/openSeries: \(version\)/);
assert.equal(typeof Make.MakeImageController.prototype.upgradeWorkspace,"function");
assert.equal(typeof Versions.merge,"function");
const orig={mediaId:"m0",imageUrl:"/generated/a.webp",runId:"r0"};
const one=Versions.merge([], [orig], {runId:"r0",runSpec:{subject:"保存时的主题",ratio:"3:4"}});
const two=Versions.merge(one,[{mediaId:"m1",imageUrl:"/generated/b.webp",runId:"r1"}],
  {runId:"r1",runSpec:{subject:"下一个主题",ratio:"16:9"}});
assert.equal(two.length,2);
assert.equal(two[0].recipeSnapshot.subject,"保存时的主题");
assert.equal(two[1].recipeSnapshot.subject,"下一个主题");
assert.deepEqual(Versions.merge(two,[orig]).map(v=>v.mediaId),["m0","m1"]);
console.log("Studio #128 static, compatibility and immutable-version regression PASS");
