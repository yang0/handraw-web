"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");

const forum = fs.readFileSync("demo/assets/forum-app.js","utf8");
const admin = fs.readFileSync("demo/assets/admin-app.js","utf8");
const backend = fs.readFileSync("backend/admin_services.py","utf8");
const boot = fs.readFileSync("backend/services.py","utf8");
const seed = fs.readFileSync("backend/seed.py","utf8");
const css = fs.readFileSync("demo/assets/forum-featured.css","utf8");
const page = fs.readFileSync("demo/forum.html","utf8");

test("#173 replaces hardcoded style/layout portal with curated featured list", () => {
  assert.doesNotMatch(forum,/画风与图型入口/);
  assert.doesNotMatch(forum,/\["FA-001", "SC-021", "FX-001", "IG-001"\]/);
  assert.match(forum,/forum-featured-panel/);
  assert.match(forum,/forum-featured-link/);
  assert.match(forum,/t\.featured === true/);
  assert.match(forum,/visible\.slice\(0, limit\)/);
  assert.match(forum,/t\.status !== "hidden"/);
  assert.match(forum,/t\.status !== "deleted"/);
  assert.match(forum,/t\.visibility !== "private"/);
  assert.match(forum,/aria-label="社区精华帖"/);
  assert.match(forum,/还没有精华帖/);
  assert.match(page,/forum-featured\.css\?v=1/);
  assert.match(css,/forum-featured-link:focus-visible/);
});
test("#173 short cache uses public boot topics and admin limit", () => {
  assert.match(forum,/FEATURED_CACHE_TTL_MS = 60 \* 1000/);
  assert.match(forum,/featuredSidebarCache\.topics === topics/);
  assert.match(forum,/featuredSidebarCache\.limit === limit/);
  assert.match(forum,/nowMs - featuredSidebarCache\.at < FEATURED_CACHE_TTL_MS/);
  assert.match(forum,/invalidateFeaturedSidebar\(\)/);
  assert.match(forum,/S\.refreshFromServer\(\)/);
  assert.match(boot,/"featured_sidebar_limit": max\(1, min\(5,/);
});
test("#173 only admins can save integer 1-5 to audited forum settings", () => {
  assert.match(seed,/"forum": \{\s*"featured_sidebar_limit": 5/);
  assert.match(backend,/if sec not in \("economy", "announcement", "moderation", "gateway", "forum"\)/);
  assert.match(backend,/if sec == "forum":\s*if set\(values\) != \{"featured_sidebar_limit"\}/);
  assert.match(backend,/not isinstance\(raw_limit, int\) or not 1 <= raw_limit <= 5/);
  assert.match(admin,/id="cfg-forum-featured-limit" min="1" max="5" step="1"/);
  assert.match(admin,/id="btn-save-forum-featured"/);
  assert.match(admin,/section: "forum", values: \{ featured_sidebar_limit: limit \}/);
});
