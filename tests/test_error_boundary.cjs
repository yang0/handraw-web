/* Execute the actual dependency-free boundary with a small DOM and transport. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../demo/assets/error-boundary.js'), 'utf8');

function fixture({failReporting = false} = {}) {
  const nodes = new Map(), listeners = {}, reports = [];
  class Element {
    constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.style = {}; this.isConnected = false; this.attributes = {}; }
    setAttribute(name, value) { this.attributes[name] = value; }
    append(...elements) { elements.forEach(element => this.appendChild(element)); }
    appendChild(element) { this.children.push(element); element.isConnected = true; if (element.id) nodes.set(element.id, element); return element; }
    remove() { this.isConnected = false; if (this.id) nodes.delete(this.id); }
  }
  const document = {
    body: new Element('body'), createElement: name => new Element(name), getElementById: id => nodes.get(id),
    addEventListener: (name, callback) => { listeners['document:' + name] = callback; }
  };
  const location = new URL('http://localhost:3080/studio/?token=private-location-token');
  location.reload = () => {};
  let idCounter = 1;
  const window = {
    location, crypto: {randomUUID: () => String(idCounter++).padStart(32, '0')},
    addEventListener: (name, callback) => { listeners[name] = callback; },
    fetch: async (url, options) => {
      reports.push({url, body: JSON.parse(options.body)});
      if (failReporting) throw new Error('report endpoint offline');
      return {ok: true, json: async () => ({requestId: 'c'.repeat(32)})};
    }
  };
  vm.runInNewContext(source, {window, document, URL, WeakMap, Error, Date, Math, Array, Number, String});
  return {window, document, listeners, reports, nodes};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const f = fixture();
  const error = new TypeError('private error message with password=secret');
  f.listeners.error({target: f.window, error, filename: 'http://localhost:3080/assets/main-app.js?token=private-source-token', lineno: 84, colno: 3});
  await settle();
  assert.equal(f.reports.length, 1);
  assert.equal(f.reports[0].url, '/api/client-errors');
  assert.equal(f.reports[0].body.script, 'main-app.js');
  assert.equal(f.reports[0].body.channel, 'studio');
  assert.equal(f.reports[0].body.line, 84);
  assert.equal(f.reports[0].body.errorType, 'TypeError');
  const report = JSON.stringify(f.reports);
  for (const privateValue of ['private error message', 'password', 'secret', 'private-source-token', 'private-location-token']) assert.ok(!report.includes(privateValue));
  const panel = f.nodes.get('handraw-error-notice');
  assert.equal(panel.attributes.role, 'alert');
  assert.equal(panel.children[2].textContent, '问题编号：' + 'c'.repeat(32));
  assert.equal(panel.children[3].children[0].textContent, '刷新页面');
  f.listeners.unhandledrejection({reason: error});
  await settle();
  assert.equal(f.reports.length, 1, 'the same error is reported only once');

  const api = fixture();
  const apiError = api.window.HandrawErrors.apiError({status: 500, headers: {get: () => 'a'.repeat(32)}}, {error: 'private SQL detail'});
  api.window.HandrawErrors.handle(apiError, {kind: 'unhandledrejection'});
  await settle();
  assert.equal(api.reports.length, 1);
  assert.equal(api.reports[0].body.relatedRequestId, 'a'.repeat(32));
  assert.ok(!apiError.message.includes('private SQL'));
  assert.equal(api.nodes.get('handraw-error-notice').children[2].textContent, '问题编号：' + 'a'.repeat(32));
  const expected = api.window.HandrawErrors.apiError({status: 401, headers: {get: () => null}}, {error: '请先登录'});
  assert.ok(expected.message.includes('请先登录'));
  assert.equal(api.reports.length, 1, 'expected handled 4xx errors do not generate crash reports');

  const loading = fixture();
  loading.listeners.error({target: {tagName: 'IMG', src: '/missing.png'}});
  assert.equal(loading.reports.length, 0);
  loading.listeners.error({target: {tagName: 'SCRIPT', src: 'http://localhost:3080/assets/shared.js?private=token'}});
  await settle();
  assert.equal(loading.reports[0].body.kind, 'resource');
  assert.equal(loading.reports[0].body.script, 'shared.js');
  assert.ok(loading.nodes.has('handraw-error-notice'));

  const offline = fixture({failReporting: true});
  offline.listeners.unhandledrejection({reason: new Error('network down')});
  await settle();
  assert.equal(offline.reports.length, 1, 'report transport failure does not recurse');
  assert.ok(offline.nodes.has('handraw-error-notice'), 'visible recovery remains available offline');
  for (let i = 0; i < 12; i++) offline.window.HandrawErrors.report(new Error('repeated error'));
  await settle();
  assert.equal(offline.reports.length, 5, 'client-side report storms are bounded');

  const request = fixture();
  let requestedOptions;
  request.window.fetch = async (url, options) => {
    requestedOptions = options;
    return {status: 500, ok: false, headers: {get: () => 'd'.repeat(32)}, json: async () => ({ok: false, error: 'private server detail'})};
  };
  await assert.rejects(request.window.HandrawErrors.fetchJson('/api/work', {method: 'POST'}), error => error.requestId === 'd'.repeat(32) && error.status === 500);
  await settle();
  assert.equal(requestedOptions.headers.Accept, 'application/json');
  assert.equal(request.reports.length, 1);
  request.window.fetch = async () => ({status: 204, ok: true});
  assert.deepEqual(Object.keys(await request.window.HandrawErrors.fetchJson('/api/work')), []);
  request.window.fetch = async () => ({status: 200, ok: true, headers: {get: () => null}, json: async () => { throw new SyntaxError('private HTML response'); }});
  await assert.rejects(request.window.HandrawErrors.fetchJson('/api/work'), /响应格式异常/);
  await settle();
  assert.equal(request.reports.length, 2);
  request.window.fetch = async () => { throw new TypeError('network offline'); };
  await assert.rejects(request.window.HandrawErrors.fetchJson('/api/work'), /网络连接暂时不可用/);
  await settle();
  assert.equal(request.reports.length, 3);
  const privateName = fixture();
  const custom = new Error('private custom error');
  custom.name = 'password=private-error-name';
  privateName.window.HandrawErrors.report(custom, {kind: 'private-event-kind'});
  await settle();
  assert.equal(privateName.reports[0].body.errorType, 'UnknownError');
  assert.equal(privateName.reports[0].body.kind, 'runtime');
  assert.ok(!JSON.stringify(privateName.reports).includes('private-error-name'));

  for (const template of ['index.html', 'forum.html', 'studio.html', 'admin.html']) {
    const html = fs.readFileSync(path.join(__dirname, '../demo', template), 'utf8');
    const scripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)].map(match => match[1]);
    assert.equal(scripts[0], '/assets/error-boundary.js?v=1', template + ' installs the handler first');
  }
  const main = fs.readFileSync(path.join(__dirname, '../demo/assets/main-app.js'), 'utf8');
  const authRender = main.slice(main.indexOf('  function renderAuthPage(root)'), main.indexOf('  /* ======================== STANDALONE SKILL'));
  const app = {state: {loggedIn: true, user: {username: 'signed_in'}}, view: 'auth'};
  let accountRenders = 0, homeRenders = 0, urlSyncs = 0;
  vm.runInNewContext(authRender + '\nrenderAuthPage(root);', {
    App: app, UI: {}, root: {}, window: {location: {search: ''}}, URLSearchParams, syncUrl: () => { urlSyncs++; },
    renderAccountSettingsPage: () => { accountRenders++; }, renderMain: () => { homeRenders++; }
  });
  assert.equal(app.view, 'discover');
  assert.equal(accountRenders, 0);
  assert.equal(homeRenders, 1, 'a signed-in user returns to the home page');
  assert.equal(urlSyncs, 1);
  const authUI = {};
  let notice = '';
  vm.runInNewContext(authRender + '\nrenderAuthPage(root);', {
    App: app, UI: authUI, root: {}, window: {location: {search: '?view=auth&oauth_error=oauth_state_invalid'}}, URLSearchParams,
    syncUrl: () => {}, renderAccountSettingsPage: () => {}, S: {toast: value => { notice = value; }}
  });
  assert.equal(authUI.accountSection, 'security');
  assert.ok(notice.includes('授权未完成'), 'an existing session must not hide an OAuth rejection');
  console.log('Application boundary: runtime, promises, API correlation, scripts, privacy, deduplication and rate limiting passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
