"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

const channelUrl = (channel, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return `/${channel}${qs ? "?" + qs : ""}`;
};

const App = {
  state: {
    works: [],
    topics: [],
    resources: [],
    homeScenarios: [],
    homeScenariosFailed: false,
    _scenariosFetching: false,
  },
};

const S = {
  App,
  esc,
  channelUrl,
  compareByRecency: () => 0,
};

const context = {
  window: {},
  document: {
    getElementById(id) {
      return null;
    },
  },
  URLSearchParams,
  clearTimeout,
  setTimeout,
  App,
  S,
  esc,
};
context.window.HANDRAW_SHARED = S;

vm.createContext(context);
vm.runInContext(fs.readFileSync("demo/assets/discovery.js", "utf8"), context);

const Discovery = context.window.HandrawDiscovery;
assert.ok(Discovery, "HandrawDiscovery must be exported on window");
assert.equal(typeof Discovery.render, "function");
assert.equal(typeof Discovery.renderScenarioCard, "function");
assert.equal(typeof Discovery.renderScenariosInner, "function");

// 1. Test renderScenarioCard with samples
const testSc1 = {
  key: "xiaohongshu",
  title: "小红书套图",
  subtitle: "多图连贯排版",
  studioEntry: "batch",
  studioParams: { purpose: "小红书套图", layout: "SC-001" },
  samples: [
    { id: "w1", title: "样图1", imageUrl: "/img/w1.png" },
    { id: "w2", title: "样图2", imageUrl: "/img/w2.png" },
  ],
};

const cardHtml1 = Discovery.renderScenarioCard(testSc1);
assert.match(cardHtml1, /data-scenario="xiaohongshu"/);
assert.match(cardHtml1, /hw-scenario-collage--2/);
assert.match(cardHtml1, /data-hw-src="\/img\/w1\.png"/);
assert.match(cardHtml1, /href="\/studio\?entry=batch&amp;purpose=%E5%B0%8F%E7%BA%A2%E4%B9%A6%E5%A5%97%E5%9B%BE&amp;layout=SC-001"/);
assert.match(cardHtml1, /用这个做一张/);
assert.match(cardHtml1, /href="\/main\?view=works&amp;scenario=xiaohongshu"/);
assert.match(cardHtml1, /看同类作品/);

// 2. Test renderScenarioCard with 0 samples (placeholder degradation)
const testScEmpty = {
  key: "comic_4panel",
  title: "漫画四格",
  subtitle: "分镜连环画",
  studioEntry: "quick",
  studioParams: { purpose: "漫画四格" },
  samples: [],
};

const cardHtmlEmpty = Discovery.renderScenarioCard(testScEmpty);
assert.match(cardHtmlEmpty, /hw-scenario-card__media--empty/);
assert.match(cardHtmlEmpty, /hw-scenario-card__placeholder/);
assert.match(cardHtmlEmpty, /用这个做一张/);
assert.match(cardHtmlEmpty, /看同类作品/);
assert.doesNotMatch(cardHtmlEmpty, /hw-scenario-collage/);

// 3. XSS escaping test
const testScXss = {
  key: "xss_key",
  title: '<script>alert("title")</script>',
  subtitle: '<img src="x" onerror="alert(1)">',
  studioEntry: "quick",
  samples: [{ id: "bad", title: 'bad"title', imageUrl: 'bad"url' }],
};
const cardHtmlXss = Discovery.renderScenarioCard(testScXss);
assert.doesNotMatch(cardHtmlXss, /<script|<img[^>]*onerror/i);
assert.match(cardHtmlXss, /&lt;script&gt;/);
assert.match(cardHtmlXss, /&lt;img/);

// 4. Test renderScenariosInner
const innerHtml = Discovery.renderScenariosInner([testSc1, testScEmpty]);
assert.match(innerHtml, /你想做什么/);
assert.match(innerHtml, /hw-scenario-grid/);
assert.equal(Discovery.renderScenariosInner([]), "");

// 5. Test HandrawDiscovery.render with populated scenarios
App.state.homeScenarios = [testSc1, testScEmpty];
App.state.homeScenariosFailed = false;
const root1 = {};
Discovery.render(root1);
assert.match(root1.innerHTML, /id="hw-discovery-scenarios-root"/);
assert.match(root1.innerHTML, /data-scenario="xiaohongshu"/);
assert.match(root1.innerHTML, /data-scenario="comic_4panel"/);
assert.doesNotMatch(root1.innerHTML, /id="hw-discovery-scenarios-root"[^>]*hidden/);

// 6. Test HandrawDiscovery.render failure degradation
App.state.homeScenarios = null;
App.state.homeScenariosFailed = true;
const root2 = {};
Discovery.render(root2);
assert.match(root2.innerHTML, /id="hw-discovery-scenarios-root"[^>]*hidden/);

console.log("PASS test_home_scenarios_ui.cjs");
