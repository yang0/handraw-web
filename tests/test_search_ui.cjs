const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

for (const rel of [
  'demo/assets/search-page.js',
  'demo/assets/search-admin.js',
  'demo/assets/shared.js',
  'demo/assets/main-app.js',
  'demo/assets/forum-app.js',
  'demo/assets/admin-app.js',
  'demo/assets/studio-app.js',
]) {
  test(`syntax check ${rel}`, () => {
    const code = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    new vm.Script(code, { filename: rel });
  });
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function makeFakeElement(tag) {
  return {
    tagName: tag.toUpperCase(),
    className: '',
    hidden: false,
    disabled: false,
    isConnected: true,
    children: [],
    dataset: {},
    value: '',
    textContent: '',
    _innerHTML: '',
    set innerHTML(v) {
      this._innerHTML = String(v);
      this.children = [];
    },
    get innerHTML() {
      return this._innerHTML;
    },
    replaceChildren() {
      this.children = [];
      this._innerHTML = '';
    },
    append(...nodes) {
      this.children.push(...nodes);
    },
    querySelectorAll() {
      return [];
    },
  };
}

function buildSearchPageHarness({ search = '?q=%E6%B0%B4%E5%BD%A9&channel=forum', fetchImpl }) {
  const formEl = { onsubmit: null };
  const queryInput = { value: decodeURIComponent(new URLSearchParams(search).get('q') || '') };
  const sortEl = { onchange: null, value: 'relevance' };
  const statusEl = makeFakeElement('p');
  const resultsEl = makeFakeElement('div');
  const moreEl = makeFakeElement('button');
  moreEl.hidden = true;
  const pillEls = ['all', 'styles', 'layouts', 'colors', 'works', 'forum'].map((ch) => ({
    dataset: { searchChannel: ch },
    onclick: null,
  }));
  const topQ = { value: '' };
  const topCh = { value: 'all' };

  const root = {
    isConnected: true,
    _html: '',
    set innerHTML(html) {
      this._html = String(html);
      const valMatch = this._html.match(/name="q"[^>]*value="([^"]*)"/);
      if (valMatch) queryInput.value = valMatch[1];
    },
    get innerHTML() {
      return this._html;
    },
    set textContent(v) {
      this._text = String(v);
    },
    get textContent() {
      return this._text || '';
    },
    querySelector(sel) {
      if (sel === 'form') return formEl;
      if (sel === '[name=q]') return queryInput;
      if (sel === '#search-sort') return sortEl;
      if (sel === '#search-status') return statusEl;
      if (sel === '#search-results') return resultsEl;
      if (sel === '#search-more') return moreEl;
      return null;
    },
    querySelectorAll(sel) {
      if (sel === '[data-search-channel]') return pillEls;
      return [];
    },
  };

  let authListener = null;
  const locationObj = {
    href: `https://handraw-style.com/search/${search}`,
    search,
  };
  const windowObj = {
    location: locationObj,
    HANDRAW_SHARED: {
      App: { view: '', state: { user: { id: 'u1' } } },
      esc,
      safeHref: (u) => String(u || '#'),
      safeMediaUrl: (u) => String(u || ''),
      initApp: async (_ch, listener) => {
        authListener = listener;
        if (listener) listener();
      },
      renderChrome() {},
      refreshFromServer: async () => {},
    },
  };

  const context = vm.createContext({
    window: windowObj,
    global: windowObj,
    document: {
      createElement: (tag) => makeFakeElement(tag),
      getElementById: (id) => {
        if (id === 'search-root') return root;
        if (id === 'hw-global-search-input') return topQ;
        if (id === 'hw-global-search-channel') return topCh;
        return null;
      },
      addEventListener() {},
    },
    location: locationObj,
    history: {
      pushState(_s, _t, urlObj) {
        locationObj.href = String(urlObj);
        locationObj.search = new URL(String(urlObj)).search;
      },
    },
    fetch: fetchImpl,
    AbortController,
    URL,
    URLSearchParams,
    Error,
    Object,
    String,
    addEventListener() {},
  });

  const code = fs.readFileSync(path.join(ROOT, 'demo/assets/search-page.js'), 'utf8');
  vm.runInContext(code, context, { filename: 'demo/assets/search-page.js' });

  return {
    root,
    statusEl,
    resultsEl,
    moreEl,
    pillEls,
    topQ,
    topCh,
    locationObj,
    triggerAccountSwitch(newId) {
      windowObj.HANDRAW_SHARED.App.state.user.id = newId;
      if (authListener) authListener();
    },
  };
}

test('search-page escapes XSS fragments inside <mark>, syncs topbar, and switches to all-site search', async () => {
  const requests = [];
  const h = buildSearchPageHarness({
    search: '?q=%E6%B0%B4%E5%BD%A9&channel=forum',
    fetchImpl: async (url) => {
      requests.push(url);
      return {
        ok: true,
        async json() {
          return {
            ok: true,
            hits: [
              {
                id: 'd1',
                channel: 'forum',
                code: '',
                author: 'alice',
                url: '/t/t1?reply=r1',
                image: '',
                title: '<img onerror=alert(1)>',
                titleParts: [{ text: '<img onerror=alert(1)>', match: true }],
                snippetParts: [
                  { text: '前文<script>x</script>', match: false },
                  { text: '水彩', match: true },
                ],
              },
            ],
            hasMore: false,
            nextCursor: '',
          };
        },
      };
    },
  });

  await new Promise((r) => setTimeout(r, 20));
  assert.equal(requests.length, 1);
  assert.match(requests[0], /channel=forum/);
  assert.equal(h.topCh.value, 'forum');
  assert.equal(h.topQ.value, '水彩');
  assert.equal(h.resultsEl.children.length, 1);
  const cardHtml = h.resultsEl.children[0].innerHTML;
  assert(cardHtml.includes('<mark>&lt;img onerror=alert(1)&gt;</mark>'));
  assert(!cardHtml.includes('<script>'));
  assert(cardHtml.includes('<mark>水彩</mark>'));

  // Status bar offers one-click "搜索全站" when viewing a single channel
  const allSwitch = h.statusEl.children.find((c) => c && c.textContent === '搜索全站');
  assert(allSwitch, 'expected 搜索全站 switch button in single-channel status');
  allSwitch.onclick();
  await new Promise((r) => setTimeout(r, 20));
  assert.match(h.requests ? h.requests[1] : requests[1], /channel=all/);
});

test('search-page aborts stale request and re-queries on account switch', async () => {
  const resolvers = [];
  const signals = [];
  const h = buildSearchPageHarness({
    search: '?q=FA-001&channel=all',
    fetchImpl: (_url, opts) => {
      signals.push(opts.signal);
      return new Promise((resolve, reject) => {
        if (opts.signal) {
          opts.signal.addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        }
        resolvers.push(resolve);
      });
    },
  });

  await new Promise((r) => setTimeout(r, 10));
  assert.equal(resolvers.length, 1);
  h.pillEls.find((b) => b.dataset.searchChannel === 'styles').onclick();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(signals[0].aborted, true);
  assert.equal(resolvers.length, 2);

  resolvers[1]({
    ok: true,
    async json() {
      return {
        ok: true,
        hits: [{ id: 's1', channel: 'styles', code: 'FA-001', url: '/t/FA-001', title: 'Style', titleParts: [{ text: 'Style', match: true }], snippetParts: [] }],
        hasMore: false,
      };
    },
  });
  await new Promise((r) => setTimeout(r, 15));
  assert.equal(h.resultsEl.children.length, 1);

  h.triggerAccountSwitch('u2');
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(resolvers.length, 3);
});

test('search-admin renders channel metrics and triggers rebuild & retry', async () => {
  const calls = [];
  const rebuildBtn = { dataset: { rebuild: 'styles' }, disabled: false, onclick: null };
  const retryBtn = { disabled: false, onclick: null };
  const refreshBtn = { onclick: null };
  const msgEl = { textContent: '' };
  const root = {
    isConnected: true,
    _html: '',
    set innerHTML(v) {
      this._html = String(v);
    },
    get innerHTML() {
      return this._html;
    },
    querySelector(sel) {
      if (sel === '[data-retry]') return retryBtn;
      if (sel === '[data-refresh]') return refreshBtn;
      if (sel === '[data-index-message]') return msgEl;
      return null;
    },
    querySelectorAll(sel) {
      if (sel === '[data-rebuild]') return [rebuildBtn];
      return [];
    },
  };

  const windowObj = {};
  const context = vm.createContext({
    window: windowObj,
    global: windowObj,
    setTimeout: () => 1,
    clearTimeout() {},
    fetch: async (url, opts) => {
      calls.push({ url, method: opts.method || 'GET', body: opts.body });
      if (url === '/api/admin/search') {
        return {
          ok: true,
          async json() {
            return {
              ok: true,
              available: true,
              channels: [{ channel: 'styles', document_count: 367, pending: 2, failed: 1, lag_seconds: 3.4, last_success_at: '2026-11-14T10:00:00Z', last_error: 'timeout & retry <bad>' }],
              jobs: [{ channel: 'styles', status: 'running', done: 100, total: 367, created_at: '2026-11-14T10:00:00Z', error: '' }],
            };
          },
        };
      }
      return { ok: true, async json() { return { ok: true }; } };
    },
    Error,
    Object,
    String,
    Math,
    JSON,
  });
  const code = fs.readFileSync(path.join(ROOT, 'demo/assets/search-admin.js'), 'utf8');
  vm.runInContext(code, context, { filename: 'demo/assets/search-admin.js' });

  await windowObj.HandrawSearchAdmin.mount(root);
  assert(root.innerHTML.includes('367'));
  assert(root.innerHTML.includes('&lt;bad&gt;'));
  await rebuildBtn.onclick();
  assert(calls.some((c) => c.url === '/api/admin/search/rebuild' && c.method === 'POST'));
  await retryBtn.onclick({ target: retryBtn });
  assert(calls.some((c) => c.url === '/api/admin/search/retry' && c.method === 'POST'));
});
