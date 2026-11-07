/* Handraw task journey: truthful progress, resilient polling and quiet motion.
 * Standalone utility reusable by document import and future asynchronous jobs.
 */
(function (global) {
  "use strict";
  const STORAGE = "handraw_active_document_import_v1";
  const REDUCED = () => global.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
  const escapeHtml = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const storage = {
    read() { try { return JSON.parse(global.localStorage.getItem(STORAGE) || "null"); } catch (_) { return null; } },
    write(value) { try { global.localStorage.setItem(STORAGE, JSON.stringify(value)); } catch (_) {} },
    clear() { try { global.localStorage.removeItem(STORAGE); } catch (_) {} }
  };
  function ensurePanel() {
    let el = document.getElementById("hw-task-journey");
    if (el) return el;
    el = document.createElement("aside");
    el.id = "hw-task-journey";
    el.className = "hw-task-journey";
    el.setAttribute("role", "region");
    el.setAttribute("aria-label", "任务进度");
    document.body.appendChild(el);
    return el;
  }
  let active = null;
  let restored = false;
  let recoveredImportHandler = null;
  function draw(task) {
    const el = ensurePanel();
    const state = task.state || "queued";
    const progress = task.progress || {};
    const done = Math.max(0, Number(progress.done) || 0);
    const total = Math.max(0, Number(progress.total) || 0);
    const percent = total > 0 ? Math.min(100, Math.round(done / total * 100)) : null;
    const complete = state === "done";
    const failed = state === "failed";
    const stage = task.stage || (state === "queued" ? "queued" : total ? "structuring" : "extracting");
    const message = complete ? "文档整理完成" : failed ? "文档导入未完成" :
      task.message || (stage === "queued" ? "已加入处理队列" :
        stage === "extracting" ? "正在提取文档结构与图片" :
        stage === "validating" ? "正在核对内容完整性，准备结果" :
        "AI 正在整理第 " + Math.min(done + 1, total) + " / " + total + " 段");
    const steps = [
      {id:"queued",label:"已提交"},
      {id:"extracting",label:"提取"},
      {id:"structuring",label:"AI 整理"},
      {id:"validating",label:"核对"},
      {id:"completed",label:"完成"}
    ];
    const stageOrder = ["queued", "extracting", "structuring", "validating", "completed"];
    const stageIndex = complete ? 4 : Math.max(0, stageOrder.indexOf(stage));
    const elapsed = task.startedAt ? Math.max(0, Math.floor((Date.now() - task.startedAt) / 1000)) : 0;
    el.innerHTML = `
      <div class="hw-task-head">
        <div class="hw-task-symbol" aria-hidden="true">${complete ? "✓" : failed ? "!" : "✦"}</div>
        <div class="hw-task-identity">
          <strong>${escapeHtml(message)}</strong>
          <span title="${escapeHtml(task.fileName || "")}">${escapeHtml(task.fileName || "文档导入")}</span>
        </div>
        <button class="hw-task-minimize" data-task-hide type="button" aria-label="收起任务面板">×</button>
      </div>
      <ol class="hw-task-steps" aria-label="导入处理阶段">
        ${steps.map((step, index) => `<li class="${index < stageIndex ? "is-passed" : index === stageIndex ? "is-current" : ""}" ${index === stageIndex ? 'aria-current="step"' : ""}><span class="hw-task-step-dot" aria-hidden="true">${index < stageIndex ? "✓" : index + 1}</span><span>${step.label}</span></li>`).join("")}
      </ol>
      <div class="hw-task-track" role="progressbar" aria-label="文档分段处理进度"
        aria-valuemin="0" ${percent === null ? "" : `aria-valuenow="${percent}" aria-valuemax="100"`}
        aria-valuetext="${total ? `已完成 ${done} / ${total} 段` : "正在准备文档"}">
        <div class="hw-task-track-fill ${percent === null ? "is-indeterminate" : ""}" style="${percent === null ? "" : "width:" + percent + "%"}"></div>
      </div>
      <div class="hw-task-stats" role="status" aria-live="polite">
        <span>${total ? `已整理 ${done} / ${total} 段` : complete ? "全部完成" : failed ? "处理失败" : "正在准备…"}</span>
        <span>${total ? percent + "% · " : ""}已等待 ${elapsed}s</span>
      </div>
      ${task.warning ? `<p class="hw-task-note">${escapeHtml(task.warning)}</p>` : ""}
      ${failed ? `<p class="hw-task-note is-error">${escapeHtml(task.error || "请重试；原有文章未更改。")}</p>` : ""}
      ${complete && task.recoverable ? `<div class="hw-task-recovery-actions">
        ${recoveredImportHandler ? '<button class="hw-task-action" data-task-apply type="button">审校并打开编辑器</button>' : ""}
        <button class="hw-task-action hw-task-secondary" data-task-recover type="button">下载 Markdown</button>
      </div>` : ""}
      ${!complete && !failed ? '<p class="hw-task-footnote">后台仍在处理；关闭此面板不会停止任务，刷新页面可以恢复查看。</p>' : ""}
    `;
    el.querySelector("[data-task-hide]")?.addEventListener("click", () => {
      el.classList.add("is-collapsed");
      el.innerHTML = '<button class="hw-task-reopen" type="button" aria-label="重新展开任务进度">✦ 查看任务进度</button>';
      el.querySelector(".hw-task-reopen")?.addEventListener("click", () => draw(task));
    });
    el.querySelector("[data-task-recover]")?.addEventListener("click", () => {
      if (task.result) {
        downloadMarkdown(task.result);
        storage.clear();
      }
    });
    el.querySelector("[data-task-apply]")?.addEventListener("click", async () => {
      if (!recoveredImportHandler || !task.result) return;
      const button = el.querySelector("[data-task-apply]");
      if (button) { button.disabled = true; button.textContent = "正在打开编辑器…"; }
      try {
        const confirmed = await reviewDocument(task.result, {replacing:false});
        if (confirmed) {
          const applied = await recoveredImportHandler(task.result);
          if (applied !== false) {
            task.recoverable = false;
            storage.clear();
            draw(task);
          }
        }
      } catch (error) {
        task.warning = "恢复文章失败，结果仍可下载：" + (error?.message || "请重试");
        draw(task);
      } finally {
        if (button?.isConnected) button.disabled = false;
      }
    });
    if (el.classList.contains("is-collapsed")) {
      // Keep the minimized pill in place on polling updates until user reopens it.
      el.classList.remove("is-hidden");
      el.innerHTML = '<button class="hw-task-reopen" type="button">✦ ' + escapeHtml(message) + '</button>';
      el.querySelector(".hw-task-reopen")?.addEventListener("click", () => {
        el.classList.remove("is-collapsed"); draw(task);
      });
    } else el.classList.remove("is-hidden");
    if (REDUCED()) el.classList.add("reduce-motion");
  }
  function normalizeDocument(result) {
    const normalized = { ...result };
    const title = String(normalized.title || "").trim();
    const markdown = String(normalized.markdown || "");
    if (title) {
      const lines = markdown.split("\n");
      let index = 0;
      while (index < lines.length && !lines[index].trim()) index++;
      if (index < lines.length && lines[index].trim() === "# " + title) {
        lines.splice(0, index + 1);
        while (lines.length && !lines[0].trim()) lines.shift();
        normalized.markdown = lines.join("\n");
      }
    }
    return normalized;
  }
  // Review every AI-imported document before applying it to an article.
  // No edited document is persisted by this dialog.
  function reviewDocument(result, options = {}) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "hw-document-review-overlay";
      const oldTitle = String(options.currentTitle || "");
      const oldBody = String(options.currentMarkdown || "");
      const title = String(result.title || options.fileName || "未命名文章");
      const body = String(result.markdown || "");
      const all = result.aiUsed === "all" || result.aiUsed === true;
      const partial = result.aiUsed === "partial";
      const warnings = Array.isArray(result.warnings) ? result.warnings : [];
      const fidelity = global.HandrawArticleReview?.fidelitySummary(result) || {
        segments: [], failures: 0, issues: 0, ratio: null
      };
      const fidelityRisk = fidelity.issues > 0 || fidelity.failures > 0 ||
        (fidelity.ratio !== null && Math.abs(fidelity.ratio) > 5);
      const aiLabel = all ? "全部段落已用 AI 整理" : partial
        ? "部分段落由原文补齐，请重点检查" : "AI 未参与排版，已保留原文";
      const changed = Boolean(options.replacing);
      const titleLabel = changed ? "确认替换文档" : "确认导入文章";
      const preview = body.slice(0, 7500);
      overlay.innerHTML = `
        <section class="hw-document-review" role="dialog" aria-modal="true" aria-labelledby="hw-doc-review-title">
          <header class="hw-document-review-head">
            <span class="hw-document-review-kicker">HANDRAW · 导入审校</span>
            <h2 id="hw-doc-review-title">${titleLabel}</h2>
            <p>AI 已完成文档整理。请先核对标题、正文和异常提示，确认后才更新编辑器。</p>
          </header>
          <div class="hw-document-review-meta">
            <div><small>识别标题</small><strong>${escapeHtml(title)}</strong></div>
            <div><small>处理结果</small><strong>${escapeHtml(aiLabel)}</strong></div>
            <div><small>正文长度</small><strong>${body.length.toLocaleString()} 字符${changed ? " · 原稿 " + oldBody.length.toLocaleString() + " 字符" : ""}</strong></div>
          </div>
          ${partial || !all || warnings.length ? `<p class="hw-document-review-warning" role="status">
            ${escapeHtml(partial ? "有段落处理失败并回退原文；请逐段核对后再应用。" : !all ? "本次未完整使用 AI 排版，请检查结果。" : "自动检查发现可能需要注意的内容。")}
            ${warnings.length ? " · 后端报告 " + warnings.length + " 项检查提醒" : ""}
          </p>` : ""}
          ${changed ? `<p class="hw-document-review-protect">原稿《${escapeHtml(oldTitle || "未命名文章")}》在确认前保持不变；建议下载一份导入结果备用。</p>` : ""}
          <div class="hw-document-fidelity" role="region" aria-label="内容保真核对">
            <strong>内容保真检查</strong>
            <span>分段 ${fidelity.segments.length} · AI 回退 ${fidelity.failures} 段 · 检查异常 ${fidelity.issues} 项
              ${fidelity.ratio !== null ? " · 文字差异 " + escapeHtml(fidelity.ratio) + "%" : ""}</span>
            <p>${fidelityRisk ? "存在需要核对的内容，请重点检查下方异常段落；字符比例不代表全部事实核验。" : "未发现明显结构差异。请检查标题、表格、数字和引用，自动检查不能保证内容完全一致。"}</p>
            ${fidelity.segments.length ? `<details class="hw-document-fidelity-details" ${fidelityRisk ? "open" : ""}>
              <summary>逐段查看原文与整理结果（${fidelity.segments.length} 段）</summary>
              ${fidelity.segments.map((segment, idx) => `<section class="hw-document-fidelity-segment">
                <h3>第 ${idx + 1} 段 · ${segment.aiUsed ? "AI 整理" : "原文回退"}
                  ${Array.isArray(segment.issues) && segment.issues.length ? " · " + segment.issues.length + " 项警告" : ""}</h3>
                ${Array.isArray(segment.issues) && segment.issues.length ? `<div class="hw-document-fidelity-issues">${segment.issues.map(x => escapeHtml(String(x))).join("、")}</div>` : ""}
                <div class="hw-document-fidelity-columns">
                  <div><b>原始内容</b><pre>${escapeHtml(segment.original || "")}</pre></div>
                  <div><b>整理后内容</b><pre>${escapeHtml(segment.result || "")}</pre></div>
                </div>
              </section>`).join("")}
            </details>` : "<p>本次导入没有分段原文数据，无法进行逐段自动对照。</p>"}
          </div>
          <label class="hw-document-review-preview-label" for="hw-doc-review-preview">Markdown 预览（最多展示前 7,500 字符）</label>
          <pre id="hw-doc-review-preview" class="hw-document-review-preview" tabindex="0">${escapeHtml(preview)}${body.length > preview.length ? "\\n…余下内容可下载后查看" : ""}</pre>
          <footer class="hw-document-review-actions">
            <button type="button" data-review-cancel>返回原稿</button>
            <button type="button" data-review-download>下载 Markdown</button>
            <button type="button" class="hw-document-review-primary" data-review-apply>${changed ? "确认替换正文" : "导入并打开编辑器"}</button>
          </footer>
        </section>`;
      const previousFocus = document.activeElement;
      let settled = false;
      const finish = (answer) => {
        if (settled) return;
        settled = true;
        overlay.removeEventListener("keydown", onKeyDown);
        overlay.remove();
        if (previousFocus && typeof previousFocus.focus === "function" && previousFocus.isConnected) previousFocus.focus();
        resolve(answer);
      };
      const onKeyDown = (event) => {
        if (event.key === "Escape") { event.preventDefault(); finish(false); }
        if (event.key === "Tab") {
          const buttons = [...overlay.querySelectorAll("button")];
          if (buttons.length === 0) return;
          const first = buttons[0], last = buttons[buttons.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      };
      overlay.addEventListener("keydown", onKeyDown);
      overlay.querySelector("[data-review-cancel]").addEventListener("click", () => finish(false));
      overlay.querySelector("[data-review-apply]").addEventListener("click", () => finish(true));
      overlay.querySelector("[data-review-download]").addEventListener("click", () => downloadMarkdown(result));
      document.body.appendChild(overlay);
      overlay.querySelector("[data-review-apply]").focus();
    });
  }
  function downloadMarkdown(result) {
    const md = String(result.markdown || "");
    const filename = String(result.title || "导入文章").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60) || "导入文章";
    const blob = new Blob([md], {type:"text/markdown;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename + ".md"; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  async function api(url, init) {
    const response = await fetch(url, { credentials: "include", ...init });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      const err = new Error(String(data.error || `请求失败 (HTTP ${response.status})`));
      err.status = response.status;
      err.code = data.code || "";
      throw err;
    }
    return data;
  }
  async function poll(task, onDone) {
    let consecutiveErrors = 0;
    while (active === task) {
      try {
        const status = await api("/api/studio/imports/" + encodeURIComponent(task.id));
        consecutiveErrors = 0;
        task.state = status.status;
        task.stage = status.stage || "";
        task.message = "";
        task.warning = "";
        task.progress = status.progress || { done: 0, total: 0 };
        if (task.state === "done") {
          task.result = normalizeDocument(status.result || {});
          task.recoverable = !onDone;
          draw(task);
          if (onDone) {
            // Preserve the server result if caller is no longer viewing the editor.
            const consumed = await onDone(task.result);
            task.recoverable = consumed === false;
            draw(task);
          }
          if (!task.recoverable) storage.clear();
          return task.result;
        }
        if (task.state === "failed") {
          task.error = status.error || "导入任务失败";
          storage.clear();
          draw(task);
          throw new Error(task.error);
        }
        draw(task);
      } catch (err) {
        if (task.state === "failed") throw err;
        if (err.status === 401 || err.status === 403 || err.status === 404) {
          task.state = "failed";
          task.error = err.status === 404 ? "导入任务不存在或已过期" : "登录已失效，或当前账号无权查看此任务";
          storage.clear();
          draw(task);
          throw new Error(task.error);
        }
        consecutiveErrors++;
        task.warning = "网络连接暂时不稳定，正在重试查询进度…";
        draw(task);
        if (consecutiveErrors >= 8) {
          task.warning = "暂时无法取得任务状态。可刷新页面继续查看，不必重复上传。";
          draw(task);
          throw err;
        }
      }
      await delay(2300);
    }
    return null;
  }
  async function submitImport(fileName, fileData, onDone) {
    if (active && active.state !== "done" && active.state !== "failed") {
      draw(active);
      throw new Error("已有文档正在处理中，请先完成当前导入");
    }
    const task = { id: "", fileName, state: "queued", progress: { done: 0, total: 0 }, startedAt: Date.now(), message: "正在上传文档…" };
    active = task;
    draw(task);
    try {
      const submitted = await api("/api/studio/imports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({fileName, fileData})
      });
      task.id = submitted.importId;
      if (!task.id) throw new Error("服务器未返回任务编号");
      task.message = "";
      storage.write({ id: task.id, startedAt: task.startedAt });
      return await poll(task, onDone);
    } catch (err) {
      if (!task.id || task.state === "failed") {
        task.state = "failed";
        task.error = err.message || "导入失败";
        draw(task);
      }
      throw err;
    }
  }
  async function resume() {
    if (restored) return;
    restored = true;
    const saved = storage.read();
    if (!saved?.id || active) return;
    const task = { id: saved.id, fileName: "上次导入的文档", state: "queued",
      startedAt: saved.startedAt || Date.now(), progress: { done: 0, total: 0 }, recoverable: true };
    active = task;
    draw(task);
    try { await poll(task, null); }
    catch (_) { /* Panel retains actionable status, never silently disappears. */ }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => resume(), {once: true});
  else resume();
  // Reusable non-percent activity trace for synchronous AI planning/export.
  // This intentionally never invents an ETA or a completion percentage.
  async function withActivity(label, work) {
    const id = "hw-activity-" + Math.random().toString(36).slice(2, 9);
    const el = document.createElement("div");
    el.id = id;
    el.className = "hw-activity-trace";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    const started = Date.now();
    let phase = "working";
    const render = () => {
      const seconds = Math.floor((Date.now() - started) / 1000);
      el.innerHTML = `<span class="hw-activity-pulse" aria-hidden="true">${phase === "done" ? "✓" : phase === "failed" ? "!" : "✦"}</span>
        <span class="hw-activity-label"><strong>${escapeHtml(phase === "done" ? "已完成" : phase === "failed" ? "处理失败" : label)}</strong>
          <small>${phase === "working" ? `已等待 ${seconds} 秒 · 任务仍在进行` : phase === "done" ? "结果已经更新" : "请检查提示并重试"}</small></span>`;
      el.classList.toggle("is-finished", phase !== "working");
    };
    document.body.appendChild(el);
    render();
    const interval = setInterval(() => { if (phase === "working") render(); }, 1000);
    try {
      const result = await work();
      phase = result && result.ok === false ? "failed" : "done";
      render();
      return result;
    } catch (error) {
      phase = "failed";
      render();
      throw error;
    } finally {
      clearInterval(interval);
      setTimeout(() => el.remove(), phase === "failed" ? 9000 : 3500);
    }
  }
  global.HandrawTaskJourney = {
    submitImport, resume, downloadMarkdown, reviewDocument, withActivity,
    setRecoveredImportHandler(handler) {
      recoveredImportHandler = typeof handler === "function" ? handler : null;
      if (active?.state === "done" && active.recoverable) draw(active);
    },
    acknowledgeImport() {
      if (!active || active.state !== "done") return;
      active.recoverable = false;
      storage.clear();
      draw(active);
    }
  };
})(window);
