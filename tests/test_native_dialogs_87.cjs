'use strict';
// #87 all authored demo JavaScript must parse and use awaitable site dialogs,
// never window.alert/confirm/prompt. Test fixtures, docs and vendor code are
// explicitly outside this directory scan.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..', 'demo');
const assets = path.join(root, 'assets');
const inputs = fs.readdirSync(assets).filter(file => file.endsWith('.js'))
  .map(file => path.join(assets, file));
let parsed = 0;
for (const file of inputs) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotThrow(() => new vm.Script(source, {filename: file}), file);
  parsed++;
  // Accept ordinary user text with words "confirm" and "prompt"; reject
  // actual calls to the three browser-native blocking functions.
  const hits = source.match(/(?<![\w.])(?:(?:window|globalThis)\s*\.\s*)?(?:alert|confirm|prompt)\s*\(/g);
  assert.equal(hits, null, file + ' still has native blocking dialog: ' + String(hits));
}
for (const name of ['index.html', 'forum.html', 'studio.html', 'admin.html']) {
  const html = fs.readFileSync(path.join(root, name), 'utf8');
  const dialogIdx = html.indexOf('src="/assets/app-dialogs.js');
  assert.ok(dialogIdx >= 0, name + ' missing async dialog module');
  assert.ok(dialogIdx < html.indexOf('src="/assets/', dialogIdx + 8),
    name + ' should load the dialog module early');
}
const dialog = fs.readFileSync(path.join(assets, 'app-dialogs.js'), 'utf8');
assert.ok(dialog.includes('role", task.kind === "confirm" ? "alertdialog" : "dialog"'));
assert.ok(dialog.includes('if (event.key === "Escape")'));
assert.ok(dialog.includes('event.key === "Tab"'));
assert.ok(dialog.includes('task.resolve(value)'));
assert.ok(!/window\s*\.\s*confirm\s*=/.test(dialog), 'do not monkeypatch native confirm');
console.log('#87 native-dialog static gate: ' + parsed + ' modules parsed, all no native dialogs, 4 entrypoints wired');
