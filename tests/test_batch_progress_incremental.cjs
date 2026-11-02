"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

console.log("Starting Batch Progress Incremental & Non-Destructive Update Tests (Issue #41)...");

const studioBatchSource = fs.readFileSync("demo/assets/studio-batch.js", "utf8");
const studioAppSource = fs.readFileSync("demo/assets/studio-app.js", "utf8");

// =========================================================================
// Test 1: Code inspections - busy fallback removal & zero emoji
// =========================================================================
{
  // 1.1 Verify removal of busy && currentStep === 0 fallback to 1
  assert.ok(
    !studioBatchSource.includes("if (busy && currentStep === 0) currentStep = 1;"),
    "studio-batch.js must NOT force currentStep to 1 when busy and currentStep is 0"
  );

  // 1.2 Verify zero emoji in studio-batch.js
  const emojiRegex = /[\u{1F300}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F900}-\u{1F9FF}\u{1F1E0}-\u{1F1FF}]/u;
  const match = studioBatchSource.match(emojiRegex);
  assert.equal(match, null, `studio-batch.js must not contain any emoji (found: ${match?.[0]})`);

  console.log("✓ Test 1 Passed: Busy fallback removal and zero emoji in studio-batch.js verified");
}

// =========================================================================
// Test 2: Status formatting logic on BatchCreateController
// =========================================================================
{
  const sandbox = {
    window: {},
    globalThis: {}
  };
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(studioBatchSource, sandbox);

  const controller = sandbox.HandrawBatchCreate;
  assert.ok(controller, "HandrawBatchCreate controller must be instantiated");

  // 2.1 Initial progress: 0 completed out of 3, generating 1st
  const initialText = controller.formatProgressStatus({
    completedCount: 0,
    totalCount: 3,
    activeIndex: 0,
    failedCount: 0,
    isStopping: false
  });
  assert.equal(initialText, "已完成 0 / 3 张 · 正在生成第 1 张…");

  // 2.2 Progress: 1 completed out of 3, generating 2nd
  const step2Text = controller.formatProgressStatus({
    completedCount: 1,
    totalCount: 3,
    activeIndex: 1,
    failedCount: 0,
    isStopping: false
  });
  assert.equal(step2Text, "已完成 1 / 3 张 · 正在生成第 2 张…");

  // 2.3 Progress with 1 failure: 1 completed, 1 failed, generating 3rd
  const failProgText = controller.formatProgressStatus({
    completedCount: 1,
    totalCount: 3,
    activeIndex: 2,
    failedCount: 1,
    isStopping: false
  });
  assert.equal(failProgText, "已完成 1 / 3 张 · 正在生成第 3 张… · 失败 1 张");

  // 2.4 In-flight cancellation text: "正在停止…"
  const stoppingText = controller.formatProgressStatus({
    completedCount: 1,
    totalCount: 3,
    activeIndex: 1,
    failedCount: 0,
    isStopping: true
  });
  assert.equal(stoppingText, "正在停止…（已完成 1 / 3 张）");

  // 2.5 Summary: All completed
  const allDoneText = controller.formatSummaryStatus({
    completedCount: 3,
    failedCount: 0,
    totalCount: 3
  });
  assert.equal(allDoneText, "全部完成（3 / 3 张）");

  // 2.6 Summary: Partial completed with failures
  const partialFailText = controller.formatSummaryStatus({
    completedCount: 2,
    failedCount: 1,
    totalCount: 3
  });
  assert.equal(partialFailText, "已完成 2 / 3 张 · 失败 1 张");

  // 2.7 Summary: Stopped early (unexecuted items remain)
  const stoppedSummary = controller.formatSummaryStatus({
    completedCount: 1,
    failedCount: 0,
    totalCount: 3
  });
  assert.equal(stoppedSummary, "已完成 1 / 3 张 · 未执行 2 张");

  console.log("✓ Test 2 Passed: formatProgressStatus and formatSummaryStatus verified");
}

// =========================================================================
// Test 3: getRowStatus state machine
// =========================================================================
{
  const sandbox = { window: {}, globalThis: {} };
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(studioBatchSource, sandbox);
  const controller = sandbox.HandrawBatchCreate;

  // 3.1 Completed item with imageUrl is always done
  const doneStatus = controller.getRowStatus(0, true, 2, { imageUrl: "https://example.com/1.png" }, 1);
  assert.equal(doneStatus.key, "done");
  assert.equal(doneStatus.label, "完成");
  assert.equal(doneStatus.className, "is-done");

  // 3.2 Failed item is always failed
  const failStatus = controller.getRowStatus(1, true, 2, { failed: true, error: "Timeout" }, 2);
  assert.equal(failStatus.key, "failed");
  assert.equal(failStatus.label, "失败");
  assert.equal(failStatus.className, "is-failed");

  // 3.3 Active generating row
  const genStatus = controller.getRowStatus(2, true, 2, null, 2);
  assert.equal(genStatus.key, "generating");
  assert.equal(genStatus.label, "生成中");
  assert.equal(genStatus.className, "is-generating");

  // 3.4 Waiting row
  const waitStatus = controller.getRowStatus(3, true, 2, null, 2);
  assert.equal(waitStatus.key, "waiting");
  assert.equal(waitStatus.label, "等待");
  assert.equal(waitStatus.className, "is-waiting");

  // 3.5 Idle with no image
  const idleStatus = controller.getRowStatus(0, false, 0, null, null);
  assert.equal(idleStatus.key, "waiting");
  assert.equal(idleStatus.label, "等待");

  console.log("✓ Test 3 Passed: getRowStatus state machine verified");
}

// =========================================================================
// Test 4: updateProgress DOM mutations & input preservation
// =========================================================================
{
  // Build a realistic DOM structure using mock DOM nodes
  class MockElement {
    constructor(tagName = "div") {
      this.tagName = tagName.toUpperCase();
      this.className = "";
      this.textContent = "";
      this.innerHTML = "";
      this.attributes = {};
      this.dataset = {};
      this.children = [];
      this.parentNode = null;
      this.disabled = false;
      this.onclick = null;
      this.classList = {
        contains: (cls) => (this.className || "").split(/\s+/).includes(cls),
        add: (cls) => { if (!this.classList.contains(cls)) this.className = (this.className + " " + cls).trim(); },
        remove: (cls) => { this.className = (this.className || "").replace(new RegExp(`\\b${cls}\\b`, "g"), "").trim(); }
      };
    }
    setAttribute(k, v) { this.attributes[k] = String(v); }
    getAttribute(k) { return this.attributes[k] != null ? this.attributes[k] : null; }
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    }
    removeChild(child) {
      const idx = this.children.indexOf(child);
      if (idx >= 0) this.children.splice(idx, 1);
      child.parentNode = null;
      return child;
    }
    replaceWith(newChild) {
      if (this.parentNode) {
        const idx = this.parentNode.children.indexOf(this);
        if (idx >= 0) {
          this.parentNode.children[idx] = newChild;
          newChild.parentNode = this.parentNode;
          this.parentNode = null;
        }
      }
    }
    remove() {
      if (this.parentNode) this.parentNode.removeChild(this);
    }
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    }
    querySelectorAll(sel) {
      const parts = sel.split(",").map((s) => s.trim());
      const res = [];
      const walk = (node) => {
        for (const child of node.children) {
          let match = false;
          for (const s of parts) {
            if (s.startsWith(".")) {
              const cls = s.slice(1);
              if (child.classList?.contains(cls)) match = true;
            } else if (s.startsWith("#")) {
              const id = s.slice(1);
              if (child.attributes.id === id) match = true;
            } else if (s.startsWith("tr[data-batch-row=\"")) {
              const rowIdx = s.match(/tr\[data-batch-row="(\d+)"\]/)?.[1];
              if (child.tagName === "TR" && child.attributes["data-batch-row"] === rowIdx) match = true;
            } else if (s.includes("[data-result-idx=\"")) {
              const rIdx = s.match(/\[data-result-idx="(\d+)"\]/)?.[1];
              if (child.attributes["data-result-idx"] === rIdx) match = true;
            } else if (s === ".batch-cost-wrap" && child.classList?.contains("batch-cost-wrap")) {
              match = true;
            } else if (child.tagName.toLowerCase() === s.toLowerCase()) {
              match = true;
            }
          }
          if (match) res.push(child);
          walk(child);
        }
      };
      walk(this);
      return res;
    }
  }

  const sandbox = {
    window: {},
    globalThis: {},
    document: {
      createElement: (tag) => new MockElement(tag)
    },
    HANDRAW_SHARED: {}
  };
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(studioBatchSource, sandbox);
  const controller = sandbox.HandrawBatchCreate;

  // Create mock DOM for batch UI
  const host = new MockElement("div");
  host.className = "batch-container";

  const costWrap = new MockElement("div");
  costWrap.className = "batch-cost-wrap";
  host.appendChild(costWrap);

  const btnWrap = new MockElement("div");
  btnWrap.className = "batch-btn-wrap";
  const btnStop = new MockElement("button");
  btnStop.setAttribute("id", "batch-btn-stop");
  btnStop.textContent = "停止";
  btnWrap.appendChild(btnStop);
  host.appendChild(btnWrap);

  // Table row 0
  const row0 = new MockElement("tr");
  row0.className = "batch-table-row is-generating";
  row0.setAttribute("data-batch-row", "0");

  const cell0 = new MockElement("div");
  cell0.className = "batch-iter-cell";
  const placeholder0 = new MockElement("div");
  placeholder0.className = "batch-iter-placeholder";
  cell0.appendChild(placeholder0);

  // Theme input / button in row 0 - must be preserved across updates!
  const themeBtn0 = new MockElement("button");
  themeBtn0.className = "batch-iter-label-btn";
  themeBtn0.textContent = "秋季水彩少女";
  cell0.appendChild(themeBtn0);
  row0.appendChild(cell0);

  const badge0 = new MockElement("span");
  badge0.className = "batch-status-badge is-generating";
  badge0.textContent = "生成中";
  row0.appendChild(badge0);

  const action0 = new MockElement("td");
  action0.className = "batch-col-action";
  row0.appendChild(action0);
  host.appendChild(row0);

  // Table row 1
  const row1 = new MockElement("tr");
  row1.className = "batch-table-row is-waiting";
  row1.setAttribute("data-batch-row", "1");
  const badge1 = new MockElement("span");
  badge1.className = "batch-status-badge is-waiting";
  badge1.textContent = "等待";
  row1.appendChild(badge1);
  host.appendChild(row1);

  controller.hostElement = host;
  controller.context = { results: [] };
  controller.actions = { openPublish: () => {}, openImageLightbox: () => {} };

  // Step 1: Complete row 0 with an image, set row 1 to active
  controller.updateProgress({
    updatedIndex: 0,
    itemResult: {
      imageUrl: "/images/generated_autumn_0.webp",
      title: "秋季水彩少女"
    },
    completedCount: 1,
    failedCount: 0,
    totalCount: 3,
    activeIndex: 1,
    busy: true
  });

  // Verify cost status text
  const busyStatusEl = costWrap.querySelector(".batch-busy-status");
  assert.ok(busyStatusEl, "Must render .batch-busy-status");
  assert.equal(busyStatusEl.textContent, "已完成 1 / 3 张 · 正在生成第 2 张…");

  // Verify row 0 updated to done
  assert.equal(row0.className, "batch-table-row is-done");
  assert.equal(badge0.textContent, "完成");
  assert.equal(badge0.className, "batch-status-badge is-done");

  // CRITICAL: verify theme button in cell 0 was NOT touched or destroyed
  assert.equal(cell0.children.length, 2, "Cell must keep thumbnail button and theme button");
  assert.equal(themeBtn0.textContent, "秋季水彩少女", "Theme label/input must retain value");
  assert.equal(themeBtn0.parentNode, cell0, "Theme button must remain attached to parent cell");

  // Verify thumbnail replaced placeholder with new button
  const thumbBtn = cell0.querySelector(".batch-iter-thumb-btn");
  assert.ok(thumbBtn, "Thumbnail button must replace placeholder");
  assert.equal(thumbBtn.dataset.zoomSrc, "/images/generated_autumn_0.webp");

  // Verify row 1 updated to generating
  assert.equal(row1.className, "batch-table-row is-generating");
  assert.equal(badge1.textContent, "生成中");

  // Step 2: Row 1 fails, set row 2 to active
  controller.updateProgress({
    updatedIndex: 1,
    itemResult: {
      failed: true,
      error: "Gateway timeout"
    },
    completedCount: 1,
    failedCount: 1,
    totalCount: 3,
    activeIndex: 2,
    busy: true
  });

  assert.equal(row1.className, "batch-table-row is-failed");
  assert.equal(badge1.textContent, "失败");
  assert.equal(badge1.className, "batch-status-badge is-failed");
  assert.equal(busyStatusEl.textContent, "已完成 1 / 3 张 · 正在生成第 3 张… · 失败 1 张");

  // Step 3: Cancellation during generation
  controller.setStopping();
  assert.equal(btnStop.disabled, true);
  assert.equal(btnStop.textContent, "正在停止…");
  assert.equal(busyStatusEl.textContent, "正在停止…（已完成 1 / 3 张 · 失败 1 张）");

  // Step 4: Finished with busy: false
  controller.updateProgress({
    completedCount: 1,
    failedCount: 1,
    totalCount: 3,
    activeIndex: null,
    busy: false,
    isStopping: false
  });

  const summaryEl = costWrap.querySelector(".batch-summary-status");
  assert.ok(summaryEl, "Must render .batch-summary-status on finish");
  assert.equal(summaryEl.textContent, "已完成 1 / 3 张 · 失败 1 张 · 未执行 1 张");
  assert.equal(costWrap.querySelector(".batch-busy-status"), null, ".batch-busy-status must be removed on finish");

  console.log("✓ Test 4 Passed: updateProgress DOM mutations & theme input preservation verified");
}

// =========================================================================
// Test 5: Global error identification in studio-app.js
// =========================================================================
{
  assert.ok(
    studioAppSource.includes("isGlobalError"),
    "studio-app.js must handle global error branching"
  );
  assert.ok(
    studioAppSource.includes("401|402|403|429"),
    "studio-app.js must check 401, 402, 403, 429 status codes"
  );
  console.log("✓ Test 5 Passed: Global error detection verified in studio-app.js");
}

// =========================================================================
// Test 6: Continuous Rerun Regression Test (Issue #41)
// 2 consecutive rounds of 3 images each. Round 2 must NOT display any
// Round 1 images, and mid-run failure must not report completion.
// =========================================================================
{
  class MockElement {
    constructor(tagName = "div") {
      this.tagName = tagName.toUpperCase();
      this.className = "";
      this.textContent = "";
      this.innerHTML = "";
      this.attributes = {};
      this.dataset = {};
      this.children = [];
      this.parentNode = null;
      this.disabled = false;
      this.onclick = null;
      this.classList = {
        contains: (cls) => (this.className || "").split(/\s+/).includes(cls),
        add: (cls) => { if (!this.classList.contains(cls)) this.className = (this.className + " " + cls).trim(); },
        remove: (cls) => { this.className = (this.className || "").replace(new RegExp(`\\b${cls}\\b`, "g"), "").trim(); }
      };
    }
    setAttribute(k, v) { this.attributes[k] = String(v); }
    getAttribute(k) { return this.attributes[k] != null ? this.attributes[k] : null; }
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    }
    removeChild(child) {
      const idx = this.children.indexOf(child);
      if (idx >= 0) this.children.splice(idx, 1);
      child.parentNode = null;
      return child;
    }
    replaceWith(newChild) {
      if (this.parentNode) {
        const idx = this.parentNode.children.indexOf(this);
        if (idx >= 0) {
          this.parentNode.children[idx] = newChild;
          newChild.parentNode = this.parentNode;
          this.parentNode = null;
        }
      }
    }
    remove() {
      if (this.parentNode) this.parentNode.removeChild(this);
    }
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    }
    querySelectorAll(sel) {
      const parts = sel.split(",").map((s) => s.trim());
      const res = [];
      const walk = (node) => {
        for (const child of node.children) {
          let match = false;
          for (const s of parts) {
            if (s.startsWith(".")) {
              const cls = s.slice(1);
              if (child.classList?.contains(cls)) match = true;
            } else if (s.startsWith("#")) {
              const id = s.slice(1);
              if (child.attributes.id === id) match = true;
            } else if (s.startsWith("tr[data-batch-row=\"")) {
              const rowIdx = s.match(/tr\[data-batch-row="(\d+)"\]/)?.[1];
              if (child.tagName === "TR" && child.attributes["data-batch-row"] === rowIdx) match = true;
            } else if (s.includes("[data-result-idx=\"")) {
              const rIdx = s.match(/\[data-result-idx="(\d+)"\]/)?.[1];
              if (child.attributes["data-result-idx"] === rIdx) match = true;
            } else if (s === ".batch-cost-wrap" && child.classList?.contains("batch-cost-wrap")) {
              match = true;
            } else if (child.tagName.toLowerCase() === s.toLowerCase()) {
              match = true;
            }
          }
          if (match) res.push(child);
          walk(child);
        }
      };
      walk(this);
      return res;
    }
  }

  const sandbox = {
    window: {},
    globalThis: {},
    document: {
      createElement: (tag) => new MockElement(tag)
    },
    HANDRAW_SHARED: {}
  };
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(studioBatchSource, sandbox);
  const controller = sandbox.HandrawBatchCreate;

  const host = new MockElement("div");
  host.className = "batch-container";

  const costWrap = new MockElement("div");
  costWrap.className = "batch-cost-wrap";
  host.appendChild(costWrap);

  const rows = [];
  for (let r = 0; r < 3; r++) {
    const row = new MockElement("tr");
    row.className = "batch-table-row is-waiting";
    row.setAttribute("data-batch-row", String(r));

    const cell = new MockElement("div");
    cell.className = "batch-iter-cell";
    const ph = new MockElement("div");
    ph.className = "batch-iter-placeholder";
    cell.appendChild(ph);

    const themeBtn = new MockElement("button");
    themeBtn.className = "batch-iter-label-btn";
    themeBtn.textContent = `主题 #${r + 1}`;
    cell.appendChild(themeBtn);
    row.appendChild(cell);

    const badge = new MockElement("span");
    badge.className = "batch-status-badge is-waiting";
    badge.textContent = "等待";
    row.appendChild(badge);

    const action = new MockElement("td");
    action.className = "batch-col-action";
    row.appendChild(action);

    host.appendChild(row);
    rows.push(row);
  }

  controller.hostElement = host;
  controller.context = { results: [] };
  controller.actions = { openPublish: () => {}, openImageLightbox: () => {} };

  // --- ROUND 1: Generate 3 images ---
  controller.resetBatchProgress({ totalCount: 3, batchId: "batch_round_1" });
  for (let r = 0; r < 3; r++) {
    controller.updateProgress({
      updatedIndex: r,
      itemResult: {
        imageUrl: `/images/round1_${r}.webp`,
        title: `第1轮图 #${r + 1}`,
        batchId: "batch_round_1"
      },
      completedCount: r + 1,
      failedCount: 0,
      totalCount: 3,
      activeIndex: r + 1 < 3 ? r + 1 : null,
      busy: r + 1 < 3,
      batchId: "batch_round_1"
    });
  }
  controller.updateProgress({
    completedCount: 3,
    failedCount: 0,
    totalCount: 3,
    activeIndex: null,
    busy: false,
    isStopping: false,
    batchId: "batch_round_1"
  });

  // Verify Round 1 completed
  assert.equal(controller.context.results.length, 3);
  assert.equal(controller.context.results[0].imageUrl, "/images/round1_0.webp");
  const summary1 = costWrap.querySelector(".batch-summary-status")?.textContent;
  assert.equal(summary1, "全部完成（3 / 3 张）");

  // --- ROUND 2: User clicks start again (rerun) ---
  // IMMEDIATELY on reset, before any image returns:
  controller.resetBatchProgress({ totalCount: 3, batchId: "batch_round_2" });

  // 1. context.results must be cleared immediately!
  assert.equal(controller.context.results.length, 0, "Round 2 results cache must be empty immediately");
  // 2. Results section in DOM must be removed immediately!
  assert.equal(host.querySelector(".batch-results-section"), null, "Results section must be removed immediately on rerun");
  // 3. Table rows must be reset immediately: no round 1 thumbnails!
  for (let r = 0; r < 3; r++) {
    const thumbBtn = rows[r].querySelector(".batch-iter-thumb-btn");
    assert.equal(thumbBtn, null, `Row ${r} must not have thumbnail immediately after reset`);
    const ph = rows[r].querySelector(".batch-iter-placeholder");
    assert.ok(ph, `Row ${r} must have placeholder after reset`);
  }
  // 4. Progress text must show 0 / 3
  const busyStatusRerunning = costWrap.querySelector(".batch-busy-status")?.textContent;
  assert.equal(busyStatusRerunning, "已完成 0 / 3 张 · 正在生成第 1 张…");

  // Generate round 2 incrementally: slot 0 finishes
  controller.updateProgress({
    updatedIndex: 0,
    itemResult: {
      imageUrl: "/images/round2_0.webp",
      title: "第2轮图 #1",
      batchId: "batch_round_2"
    },
    completedCount: 1,
    failedCount: 0,
    totalCount: 3,
    activeIndex: 1,
    busy: true,
    batchId: "batch_round_2"
  });

  // Check: row 0 has round 2 image, row 1 & 2 still placeholder
  const thumb0 = rows[0].querySelector(".batch-iter-thumb-btn");
  assert.ok(thumb0, "Row 0 must have thumbnail");
  assert.equal(thumb0.dataset.zoomSrc, "/images/round2_0.webp");
  assert.equal(rows[1].querySelector(".batch-iter-thumb-btn"), null, "Row 1 must NOT have round 1 image");
  assert.equal(rows[2].querySelector(".batch-iter-thumb-btn"), null, "Row 2 must NOT have round 1 image");

  // Late arriving response from batch_round_1 must be dropped
  controller.updateProgress({
    updatedIndex: 1,
    itemResult: {
      imageUrl: "/images/round1_stale_late.webp",
      title: "第1轮迟到响应",
      batchId: "batch_round_1"
    },
    completedCount: 1,
    failedCount: 0,
    totalCount: 3,
    activeIndex: 1,
    busy: true,
    batchId: "batch_round_1"
  });
  assert.equal(rows[1].querySelector(".batch-iter-thumb-btn"), null, "Row 1 must NOT accept late response from batch 1");

  // Complete round 2
  for (let r = 1; r < 3; r++) {
    controller.updateProgress({
      updatedIndex: r,
      itemResult: {
        imageUrl: `/images/round2_${r}.webp`,
        title: `第2轮图 #${r + 1}`,
        batchId: "batch_round_2"
      },
      completedCount: r + 1,
      failedCount: 0,
      totalCount: 3,
      activeIndex: r + 1 < 3 ? r + 1 : null,
      busy: r + 1 < 3,
      batchId: "batch_round_2"
    });
  }
  controller.updateProgress({
    completedCount: 3,
    failedCount: 0,
    totalCount: 3,
    activeIndex: null,
    busy: false,
    isStopping: false,
    batchId: "batch_round_2"
  });

  // Verify that NONE of the results or DOM thumbnails contain round 1 images!
  assert.equal(controller.context.results.length, 3);
  for (let r = 0; r < 3; r++) {
    assert.ok(controller.context.results[r].imageUrl.includes("round2"), `Result ${r} must be round 2`);
    assert.ok(!controller.context.results[r].imageUrl.includes("round1"), `Result ${r} must not be round 1`);
    const th = rows[r].querySelector(".batch-iter-thumb-btn");
    assert.ok(th.dataset.zoomSrc.includes("round2"), `Row ${r} thumb must be round 2`);
    assert.ok(!th.dataset.zoomSrc.includes("round1"), `Row ${r} thumb must not be round 1`);
  }

  // --- ROUND 3: Mid-run failure: only 1 of 3 succeeds ---
  controller.resetBatchProgress({ totalCount: 3, batchId: "batch_round_3" });
  controller.updateProgress({
    updatedIndex: 0,
    itemResult: {
      imageUrl: "/images/round3_0.webp",
      title: "第3轮图 #1",
      batchId: "batch_round_3"
    },
    completedCount: 1,
    failedCount: 0,
    totalCount: 3,
    activeIndex: 1,
    busy: true,
    batchId: "batch_round_3"
  });
  // Slot 1 fails, global interruption terminates run
  controller.updateProgress({
    updatedIndex: 1,
    itemResult: {
      failed: true,
      error: "429 额度不足",
      batchId: "batch_round_3"
    },
    completedCount: 1,
    failedCount: 1,
    totalCount: 3,
    activeIndex: null,
    busy: false,
    isStopping: false,
    batchId: "batch_round_3"
  });

  const summary3 = costWrap.querySelector(".batch-summary-status")?.textContent;
  assert.equal(summary3, "已完成 1 / 3 张 · 失败 1 张 · 未执行 1 张", "Partial failure must not report completion");
  assert.ok(!summary3.includes("全部完成"), "Partial failure must never say 全部完成");
  assert.equal(rows[0].className, "batch-table-row is-done");
  assert.equal(rows[1].className, "batch-table-row is-failed");
  assert.equal(rows[2].className, "batch-table-row is-waiting");

  console.log("✓ Test 6 Passed: Continuous rerun regression & mid-run failure verified");
}

console.log("\n========================================================");
console.log("ALL BATCH PROGRESS INCREMENTAL TESTS PASSED SUCCESSFULLY!");
console.log("========================================================\n");
