// Clicking a notification must finish the write before it navigates, or the
// browser cancels the request and the item stays unread for ever.
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const src = fs.readFileSync(
  path.join(__dirname, "..", "demo", "assets", "messaging.js"),
  "utf8"
);

// Every notification click path awaits the write and holds the navigation.
const awaitsRead = src.match(/await\s+apiJson\(\s*["']\/api\/notifications\/read["']/g) || [];
assert.ok(awaitsRead.length >= 2, `both the first page and later pages must await the write, found ${awaitsRead.length}`);

const fireAndForget = src.match(/apiJson\(\s*["']\/api\/notifications\/read["'][^)]*\)\s*\.catch/g) || [];
assert.equal(fireAndForget.length, 0, "no path may fire the write and let navigation cancel it");

// A link that navigates must stop the default action first.
const clickHandlers = src.split("addEventListener(\"click\"").slice(1);
const notificationHandlers = clickHandlers.filter((h) => h.slice(0, 500).includes("notifications/read"));
assert.ok(notificationHandlers.length >= 1, "notification links must call the read endpoint");
for (const h of notificationHandlers) {
  assert.ok(h.slice(0, 500).includes("preventDefault"), "it must stop the immediate navigation");
}

// Read-all must survive a failed request without leaving the button dead.
const readAll = src.split('readAll.onclick = async')[1];
assert.ok(readAll, "read-all handler must exist");
assert.ok(readAll.slice(0, 600).includes("catch"), "read-all needs a failure path");

console.log("notification mark-read tests passed");
