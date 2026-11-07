"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");

const app = fs.readFileSync("demo/assets/main-app.js", "utf8");
const css = fs.readFileSync("demo/assets/theme.css", "utf8");
const homeCss = fs.readFileSync("demo/assets/mixed-feed.css", "utf8");
const gallery = fs.readFileSync("demo/assets/cloud-center.js", "utf8");

assert.match(app, /class="hw-profile-feed hw-profile-resource-feed"/,
  "Creator resources must use the new responsive masonry surface");
assert.match(app, /class="hw-profile-feed hw-profile-topic-feed"/,
  "Community posts must use the new responsive masonry surface");
assert.match(app, /class="forum-topic-card hw-profile-topic-card"/,
  "Community post click targets and existing details must be preserved");
assert.match(app, /data-prof-topic="\$\{esc\(t\.id\)\}"/,
  "Topic detail navigation must remain intact");
assert.match(app, /data-prof-asset="\$\{esc\(it\.id\)\}"/,
  "Creator style/layout detail navigation must remain intact");
assert.match(css, /\.hw-profile-feed\s*\{[^}]*column-count:\s*5;/s,
  "Wide profile feed must use five columns like homepage");
assert.match(homeCss, /\.hw-mf-grid\s*\{[^}]*column-count:\s*5;/s);
for (const [width, count] of [[1400,4],[1100,3],[760,2],[350,1]]) {
  assert.match(css, new RegExp("@media \\(max-width: " + width +
    "px\\)[^}]*\\.hw-profile-feed \\{ column-count: " + count + ";"),
    "Profile masonry at " + width + "px must match homepage: " + count);
  assert.ok(homeCss.includes("@media (max-width: " + width + "px)"),
    "Homepage breakpoint changed; review profile parity");
}
assert.match(css, /\.hw-profile-topic-card \.forum-card-split\s*\{[^}]*flex-direction:\s*column-reverse/,
  "One-image posts must stack the media above text in narrow cards");
assert.match(css, /\\.hw-personal-gallery-grid\\s*\\{[^}]*column-count:\\s*5;/s,
  "Private gallery cards must match the homepage's wide-screen density");
for (const [width,count] of [[1400,4],[1100,3],[760,2],[350,1]]) {
  assert.ok(css.includes("@media(max-width:" + width + "px) { .hw-personal-gallery-grid { column-count:" + count + "; }"),
    "Private gallery breakpoints should match homepage at " + width + "px");
}
assert.match(gallery, /data-gallery-upload-form hidden/, "Gallery must have a review form");
assert.match(gallery, /data-gallery-name/, "Review must allow editing the image name");
assert.match(gallery, /data-gallery-upload-category/, "Review must allow choosing the image category");
assert.match(gallery, /if \(uploadForm\) uploadForm\.addEventListener\("submit"/,
  "Selecting a file must not immediately send a request");
assert.match(gallery, /name: name/, "Upload must send the confirmed name");
assert.match(gallery, /uid: uid, cat: cat/, "Upload must send the confirmed category");
console.log("Profile masonry and editable gallery upload contract checks passed");
