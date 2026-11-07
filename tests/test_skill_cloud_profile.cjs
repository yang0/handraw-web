"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "demo/assets/main-app.js"), "utf8");
const routes = fs.readFileSync(path.join(root, "backend/skill_cloud_routes.py"), "utf8");
const server = fs.readFileSync(path.join(root, "backend/server.py"), "utf8");

assert.match(source, /async function loadPersonalProfileCloud\(/, "owner-only cloud data loader");
assert.match(source, /\/api\/v1\/me\/resources/, "private resource endpoint");
assert.match(source, /\/api\/v1\/me\/generations/, "private generation endpoint");
assert.match(source, /UI\.profileTab === "history" && isMe/, "history must be owner only");
assert.match(source, /\["collections", "account", "articles", "history"\]\.includes\(UI\.profileTab\)/);
assert.match(source, /private-resource-editor/, "private style editor");
assert.match(source, /data-history-publish-form/, "private history must request explicit publish confirmation");
assert.match(source, /window\.confirm\("即将向所有访客公开/, "publishing requires user confirmation");
assert.match(source, /S\.apiJson\("\/api\/works", \{ method: "POST"/, "use canonical website publishing endpoint");
assert.match(source, /data-edit-private-resource/, "owner resource editor controls");
assert.match(source, /baseRevision: /g.test(source) ? /baseRevision: / : /body\.baseRevision = existing\.revision/, "optimistic concurrency");
assert.match(source, /visibility: "private"/, "resource writes must remain private");
assert.match(routes, /WHERE id=\? AND user_id=\? AND deleted_at IS NULL/, "owner-only reads");
assert.match(routes, /def import_generation\(/, "Skill generation import");
assert.match(routes, /"visibility": "private"/, "private default");
assert.match(server, /skill_generation_media WHERE media_url/, "private media ownership");
assert.match(server, /skill_cloud_get\(self, req_path, qs\)/, "server GET mount");
const getBlock = server.slice(server.indexOf("    def _handle_get(self)"), server.indexOf("    def _handle_put(self)"));
const putBlock = server.slice(server.indexOf("    def _handle_put(self)"), server.indexOf("    def _handle_post(self)"));
assert.doesNotMatch(getBlock, /skill_cloud_put\(/, "PUT action cannot be mounted in GET");
assert.match(putBlock, /skill_cloud_put\(self, req_path, self\._read_json_body\(\)\)/,
             "resource PUT must be mounted within HTTP PUT handler");
assert.match(server, /skill_cloud_post\(self, req_path, body\)/, "server POST mount");
console.log("Skill/Web private profile and API wiring: PASS");
