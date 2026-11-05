// Quick-create view. Successful public generations appear in works; comments list discussions.
(function () {
  const S = window.HANDRAW_SHARED;
  const RATIO_PATTERN = "[0-9]+(\\.[0-9]+)?:[0-9]+(\\.[0-9]+)?";
  const MODE_OPTIONS = [
    ["graphic-text", "图文"],
    ["pure-image", "纯图"],
    ["series", "套图"]
  ];
  let currentActions = null;

  function esc(value) {
    return S && typeof S.esc === "function" ? S.esc(value) : "";
  }

  function parseRatio(text, checkPositive) {
    const match = /^([0-9]+(?:\.[0-9]+)?):([0-9]+(?:\.[0-9]+)?)$/.exec(String(text || "").trim());
    if (!match) return null;
    const w = Number(match[1]);
    const h = Number(match[2]);
    if (!isFinite(w) || !isFinite(h)) return null;
    if (checkPositive && (w <= 0 || h <= 0)) return null;
    return { w: w, h: h };
  }

  function isRatioCandidate(text) {
    return /^[0-9.]+(:[0-9.]*)?$/.test(String(text || "").trim());
  }

  function clampCount(raw) {
    const n = Math.round(Number(String(raw).trim()));
    if (!isFinite(n)) return 1;
    return Math.min(200, Math.max(1, n));
  }

  function pickerHtml(kind, resource) {
    const label = kind === "style" ? "画风" : "图型";
    return '<button type="button" class="qc-picker qc-resource-picker' + (resource ? ' is-selected' : '') + '" data-qc-pick="' + kind + '" aria-label="' + esc((resource ? '更换' : '选择') + label + (resource ? ' ' + resource.id : '')) + '">' +
      (resource && resource.image ? '<img data-hw-src="' + esc(resource.image) + '" alt="' + esc(S.resourceLabel(resource)) + '" loading="lazy">' : '<span class="qc-picker-empty" aria-hidden="true">＋</span>') +
      '<span class="qc-picker-copy"><span class="qc-picker-kind">' + label + (resource ? ' · ' + esc(resource.id) : ' · 可选') + '</span><strong>' + esc(resource ? S.resourceLabel(resource) : '选择' + label) + '</strong><span class="qc-picker-hint">' + (resource ? '点击更换' : '浏览图片') + '</span></span></button>';
  }

  function renderHead(host, model) {
    const ctx = typeof model.contextLabel === "string" ? model.contextLabel.trim() : "";
    const html = [
      '<div class="qc-head">',
      '<div><h1>快速开始</h1>',
      '<p class="qc-lede">选画风或图型，写下主题，开始创作。</p>',
      ctx ? '<p class="qc-estimate" data-qc-context>' + esc(ctx) + "</p>" : "",
      "</div>",
      "</div>"
    ].join("");
    host.innerHTML = html;
  }

  function renderUnavailable(host, model) {
    renderHead(host, model);
    const wrap = document.createElement("div");
    wrap.className = "qc-wrap";
    wrap.innerHTML = [
      '<div class="qc-empty">当前工作流使用高级节点，请进入画布继续。</div>',
      '<div class="qc-run-row">',
      '<button type="button" class="qc-run" data-qc-action="open-canvas">进入画布</button>',
      "</div>"
    ].join("");
    host.appendChild(wrap);
  }

  function renderForm(host, model) {
    const wrap = document.createElement("div");
    wrap.className = "qc-wrap";
    const modes = MODE_OPTIONS.map(function (item) {
      const sel = item[0] === model.mode ? " selected" : "";
      return '<option value="' + esc(item[0]) + '"' + sel + ">" + esc(item[1]) + "</option>";
    }).join("");
    const busyAttr = model.busy ? " disabled" : "";
    const countValue = Number.isFinite(Number(model.count)) ? Number(model.count) : 1;
    wrap.innerHTML = [
      '<form class="qc-form" novalidate>',
      '<fieldset' + (model.busy ? " disabled" : "") + ">",
      '<div class="qc-pickers">',
      pickerHtml("style", model.styleResource),
      pickerHtml("layout", model.layoutResource),
      "</div>",
      '<label class="qc-field qc-field-wide" for="qc-topic">创作主题</label>',
      '<textarea class="qc-field qc-field-wide" id="qc-topic" name="topic" aria-label="创作主题" rows="3" placeholder="描述你想画的内容">' + esc(model.topic || "") + "</textarea>",
      '<div class="qc-settings"><label class="qc-field" for="qc-count">图片数量',
      '<input class="qc-field" id="qc-count" name="count" type="number" inputmode="numeric" min="1" max="200" step="1" value="' + esc(String(clampCount(countValue))) + '" aria-label="图片数量">',
      '</label><label class="qc-field" for="qc-ratio">画幅比例',
      '<input class="qc-field" id="qc-ratio" name="ratio" type="text" inputmode="decimal" pattern="' + esc(RATIO_PATTERN) + '" value="' + esc(model.ratio || "") + '" aria-label="画幅比例">',
      '</label><label class="qc-field" for="qc-mode">生成方式',
      '<select class="qc-field" id="qc-mode" name="mode">' + modes + "</select>",
      '</label></div>',
      "</fieldset>",
      '<p class="qc-estimate"><span data-qc-cost role="status">' + esc(model.costText || "") + '</span> <span class="qc-estimate-note">资源解锁与生成费用分别计算。</span></p>',
      '<div class="qc-status" role="status" aria-live="polite" data-qc-status>' + esc(model.status || "") + "</div>",
      '<div class="qc-run-row">',
      '<button type="submit" class="qc-run"' + busyAttr + ">" + esc(runLabel(model)) + "</button>",
      "</div>",
      "</form>"
    ].join("");
    host.appendChild(wrap);

    const form = wrap.querySelector("form");
    const topicEl = wrap.querySelector("#qc-topic");
    const countEl = wrap.querySelector("#qc-count");
    const ratioEl = wrap.querySelector("#qc-ratio");
    const modeEl = wrap.querySelector("#qc-mode");

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (model.busy) return;
      const topic = topicEl ? topicEl.value : "";
      if (!topic || !topic.trim()) {
        if (topicEl) {
          topicEl.setCustomValidity("请填写创作主题");
          topicEl.reportValidity();
          topicEl.addEventListener("input", function clearValidity() {
            topicEl.setCustomValidity("");
            topicEl.removeEventListener("input", clearValidity);
          });
        }
        return;
      }
      if (ratioEl) {
        const ratio = ratioEl.value;
        if (!ratio.trim()) {
          ratioEl.setCustomValidity("请填写画幅比例");
          ratioEl.reportValidity();
          return;
        }
        if (!parseRatio(ratio, true)) {
          ratioEl.setCustomValidity("请输入形如 16:9 的正数比例");
          ratioEl.reportValidity();
          return;
        }
        ratioEl.setCustomValidity("");
      }
      if (currentActions && typeof currentActions.run === "function") {
        const result = currentActions.run();
        if (result && typeof result.catch === "function") result.catch(function () {});
      }
    });

    [topicEl, countEl, ratioEl].forEach(function (el) {
      if (!el) return;
      el.addEventListener("input", function (event) {
        const name = el.id === "qc-topic" ? "topic" : el.id === "qc-count" ? "count" : "ratio";
        const value = el.value;
        if (currentActions && typeof currentActions.set === "function") currentActions.set(name, value);
      });
    });

    if (countEl) {
      countEl.addEventListener("change", function () {
        const clamped = clampCount(countEl.value);
        countEl.value = String(clamped);
        if (currentActions && typeof currentActions.set === "function") currentActions.set("count", clamped);
      });
    }

    if (ratioEl) {
      ratioEl.addEventListener("change", function () {
        const raw = ratioEl.value;
        if (!raw.trim() || !parseRatio(raw, false)) return;
        ratioEl.setCustomValidity("");
      });
    }

    if (modeEl) {
      modeEl.addEventListener("change", function () {
        if (currentActions && typeof currentActions.set === "function") currentActions.set("mode", modeEl.value);
      });
    }

    wrap.querySelectorAll("[data-qc-pick]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const kind = btn.dataset.qcPick;
        if (currentActions && typeof currentActions.pick === "function") currentActions.pick(kind);
      });
    });
  }

  function runLabel(model) {
    if (!model.loggedIn && model.engineMode === "api") return "登录后生成";
    if (model.busy) return "生成中…";
    return "开始生成";
  }

  function renderResults(host, model) {
    const results = Array.isArray(model.results) ? model.results.filter(function (r) {
      return r && typeof r.imageUrl === "string" && r.imageUrl.trim();
    }) : [];
    const section = document.createElement("section");
    section.className = "qc-results";
    const items = results.map(function (r) {
      const id = String(r.id == null ? "" : r.id);
      return [
        '<figure class="qc-result" data-qc-id="' + esc(id) + '">',
        '<img data-hw-src="' + esc(r.imageUrl) + '" alt="' + esc(r.title || "生成结果") + '" loading="lazy">',
        '<figcaption>',
        '<span class="qc-result-title">' + esc(r.title || "") + "</span>",
        '<span class="qc-inline">',
        '<button type="button" class="qc-picker" data-qc-action="download" data-qc-id="' + esc(id) + '">下载</button>',
                "</span>",
        "</figcaption>",
        "</figure>"
      ].join("");
    }).join("");
    section.innerHTML = [
      "<h2>生成结果</h2>",
      '<p class="qc-estimate">成功生成的公开作品会自动进入作品广场；有评论后进入论坛。</p>',
      results.length ? '<div class="qc-results-grid">' + items + "</div>" : '<div class="qc-empty">还没有生成结果，填写主题后开始创作。</div>'
    ].join("");
    host.appendChild(section);
  }

  function render(host, model, actions) {
    if (!host) return;
    currentActions = actions || null;
    const safeModel = model || {};
    host.innerHTML = "";
    if (!safeModel.available) {
      renderUnavailable(host, safeModel);
      renderResults(host, safeModel);
      return;
    }
    renderHead(host, safeModel);
    renderForm(host, safeModel);
    renderResults(host, safeModel);
  }

  function updateCost(host, text) {
    if (!host) return;
    const target = host.querySelector("[data-qc-cost]");
    if (target) target.textContent = text == null ? "" : String(text);
  }

  document.addEventListener("click", function (event) {
    const btn = event.target && event.target.closest ? event.target.closest("[data-qc-action]") : null;
    if (!btn) return;
    const action = btn.dataset.qcAction;
    if (!currentActions) return;
    if (action === "open-canvas" && typeof currentActions.openCanvas === "function") currentActions.openCanvas();
    else if (action === "open-history" && typeof currentActions.openHistory === "function") currentActions.openHistory();
    else if (action === "download" && typeof currentActions.download === "function") currentActions.download(btn.dataset.qcId);
  });

  window.HandrawQuickCreate = { render: render, updateCost: updateCost };
})();
