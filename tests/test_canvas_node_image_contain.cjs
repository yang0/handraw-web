"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const css = fs.readFileSync("demo/assets/studio-canvas.css","utf8");
const selectors = [
  ".ic-ing-thumb", ".ic-gen-img", ".ic-pv-slot-card img",
  ".ic-loop-item-card img", ".ic-v4-slot-thumb",
  ".ic-disp-item img", ".ic-disp-single-wrap img",
  ".ic-disp-gal-cell img", ".ic-aplan-mini-thumb"
];
function rule(selector) {
  const start = css.indexOf(selector + " {");
  assert.ok(start >= 0, `Missing canvas node preview selector: ${selector}`);
  const end = css.indexOf("}", start);
  return css.slice(start, end);
}
test("#163 canvas node images always show the full composition", () => {
  for (const selector of selectors) {
    const cssRule = rule(selector);
    assert.match(cssRule, /object-fit:\s*contain\s*;/, `${selector} must show complete image`);
    assert.doesNotMatch(cssRule, /object-fit:\s*cover\s*;/);
  }
});
test("#163 fixed preview boxes remain stable for all image ratios", () => {
  assert.match(rule(".ic-disp-single-wrap img"), /height:\s*224px/);
  assert.match(rule(".ic-disp-single-wrap img"), /object-position:\s*center/);
  assert.match(rule(".ic-disp-gal-cell img"), /height:\s*100%/);
  assert.match(rule(".ic-gen-img"), /height:\s*100%/);
});
test("#163 change only canvas node previews, not product/feed cover crops", () => {
  assert.match(rule(".ic-hist-img-tile img"), /object-fit:\s*cover/);
});
