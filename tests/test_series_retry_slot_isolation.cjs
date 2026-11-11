"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("demo/assets/studio-app.js", "utf8");
const marker = "const results = displays.flatMap((dn, displayIndex) =>";
const start = app.indexOf(marker);
const end = app.indexOf("\n        const markDirtyAndRender", start);
assert.ok(start >= 0 && end > start, "Series result projection must exist");
const projection = new Function("displays", "selectedSeriesIndex", app.slice(start, end) + "\nreturn results;");

test("#156 retrying image 3 never projects its image into image 1 when other slots are empty", () => {
  const displays = [
    {id:"first", data:{kind:"single",slotIndex:0,items:[]}},
    {id:"second", data:{kind:"single",slotIndex:1,items:[]}},
    {id:"third", data:{kind:"single",slotIndex:2,items:[{imageUrl:"/retry-third.webp",slotKey:"third"}]}}
  ];
  for (const selectedSeriesIndex of [2,0,1,2]) {
    const projected = projection(displays,selectedSeriesIndex);
    assert.equal(projected.length,1);
    assert.equal(projected[0].index,2);
    assert.equal(projected[0].imageUrl,"/retry-third.webp");
  }
});

test("#156 preserves image 1 and updates only image 3 across thumbnail navigation", () => {
  const displays = [
    {id:"first", data:{kind:"single",slotIndex:0,items:[{imageUrl:"/original-first.webp"}]}},
    {id:"second", data:{kind:"single",slotIndex:1,items:[]}},
    {id:"third", data:{kind:"single",slotIndex:2,items:[{imageUrl:"/retry-third.webp"}]}}
  ];
  for (const selection of [0,1,2]) {
    const projected = projection(displays, selection);
    assert.deepEqual(projected.map(r => [r.index,r.imageUrl]), [
      [0,"/original-first.webp"], [2,"/retry-third.webp"]
    ]);
  }
});

test("#156 shared batch gallery keeps each image at its own slot position", () => {
  const gallery = [{id:"gallery", data:{kind:"batch_gallery",slotIndex:0,items:[
    {imageUrl:"/first.webp"}, null, {imageUrl:"/third.webp"}
  ]}}];
  assert.deepEqual(projection(gallery,1).map(r=>r.index),[0,2]);
});

test("#156 discard result carrying a mismatched slotIndex", () => {
  const displays = [{id:"third",data:{kind:"single",slotIndex:2,items:[
    {imageUrl:"/wrong.webp",slotIndex:0}
  ]}}];
  assert.equal(projection(displays,1).length,0);
});
