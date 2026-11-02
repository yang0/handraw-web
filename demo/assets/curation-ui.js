/* Handraw Curation UI — share / mine / review / admin + topic panel
 * Depends on window.HANDRAW_SHARED (= S). No eval, no prefetch of full library.
 */
(function () {
  "use strict";
  var HW = window.HANDRAW_SHARED;
  if (!HW) return;
  var S = HW;
  var App = S.App || (S.App = {});
  
  var EPOCH = 0;
  var esc = S.esc || function (v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };

  function api(url, opts) {
    if (typeof S.apiJson === "function") return S.apiJson(url, opts || {});
    return fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {})).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error((j && j.error) || ("HTTP " + r.status)); return j; });
    });
  }
  function currentUser() { return (App.state.user && App.state.user.username) || ""; }
  function isAdmin() { return !!(App.state.user && App.state.user.role === "admin"); }
  function guard(epoch, username) { return epoch === EPOCH && currentUser() === username; }
  function imgTag(src, alt) {
    if (!src) return '<div class="curation-thumb-ph" aria-hidden="true"></div>';
    return '<img class="curation-thumb" data-hw-src="' + esc(src) + '" alt="' + esc(alt || "") + '" loading="lazy">';
  }
  function filterPrompt(str) {
    return (S && typeof S.filterDisplayPrompt === "function") ? S.filterDisplayPrompt(str) : (str || "");
  }
  function uuid() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) {}
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0, v = c === "x" ? r : (r & 3 | 8); return v.toString(16);
    });
  }
  function bindImgs(root) {
    if (window.HandrawImageLoader) window.HandrawImageLoader.scan(root);
  }
  var KIND_LABEL = { work: "作品", style: "画风", layout: "图型" };
  var STATUS_LABEL = { pending: "待收录", approved: "已收录", changes_requested: "待补充", withdrawn: "已下架" };

  /* ---------- dataURL upload helper ---------- */
  function readFile(file) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result || "")); };
      r.onerror = function () { reject(new Error("图片读取失败")); };
      r.readAsDataURL(file);
    });
  }
  function uploadDataUrl(dataUrl, nameZh) {
    return api("/api/uploads", { method: "POST", body: { dataUrl: dataUrl, nameZh: nameZh || "", cat: "forum" } })
      .then(function (res) { return res && (res.url || res.image || res.path) || ""; });
  }

  /* ---------- draft payload normalization ---------- */
  function normItems(payload) {
    if (!payload) return [];
    if (Array.isArray(payload.items) && payload.items.length) return payload.items.slice();
    var one = {};
    ["kind", "name", "title", "subject", "description", "notes", "definition", "prompt", "cover", "image", "images", "styles", "layout", "ratio", "price", "unlockCost", "color", "tone", "mode", "mood"].forEach(function (k) {
      if (payload[k] != null) one[k] = payload[k];
    });
    if (one.kind) one.images = Array.isArray(one.images) ? one.images.slice() : (one.images ? [one.images] : []);
    return one.kind ? [one] : [];
  }

  function coverOf(p) {
    if (!p || typeof p !== "object") return "";
    var raw = p.cover || p.image;
    if (raw && typeof raw === "string" && raw.trim()) return raw.trim();
    if (Array.isArray(p.images) && p.images.length) {
      var first = p.images[0];
      if (first && typeof first === "string" && first.trim()) return first.trim();
    }
    return "";
  }

  function examplesOf(p) {
    if (!p || typeof p !== "object") return [];
    var cov = coverOf(p);
    var arr = Array.isArray(p.images) ? p.images : [];
    return arr.filter(function (u) {
      return u && typeof u === "string" && u.trim() && u.trim() !== cov;
    });
  }

  function isSquare(w, h) {
    if (!w || !h) return false;
    return Math.abs(w - h) <= Math.max(2, Math.round(0.01 * Math.max(w, h)));
  }

  /* ================= SHARE (page 1) ================= */
  var CANNED_BODIES = ["我的创作实测分享"];

  var PLACEHOLDER_TOPIC_TITLES = [
    "图文模式", "纯图模式", "纯图", "生成结果", "当前工作流",
    "未命名", "无标题", "默认草稿", "画布创作", "云端生图",
    "生图结果", "图片展示", "作品展示"
  ];

  function validateTopicTitle(title) {
    if (typeof S !== "undefined" && typeof S.validateTopicTitle === "function") {
      return S.validateTopicTitle(title);
    }
    var raw = String(title || "").trim();
    var nonWs = raw.replace(/\s+/g, "");
    if (nonWs.length < 4) {
      return "帖子标题至少需要 4 个非空白字符";
    }
    var strippedPlaceholder = raw.replace(/[\s\-_+|｜·#/\\#()（）\[\]【】\d+＋]+/g, "");
    for (var i = 0; i < PLACEHOLDER_TOPIC_TITLES.length; i++) {
      var p = PLACEHOLDER_TOPIC_TITLES[i];
      if (raw === p || nonWs === p || strippedPlaceholder === p) {
        return "标题不能使用默认占位词，请填写具体的主题或说明";
      }
    }
    var residual = raw.replace(/(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+/gi, "");
    var residualMeaningful = residual.replace(/[\s\-_+|｜·#/\\#()（）\[\]【】\d+＋]+/g, "");
    if (!residualMeaningful) {
      return "标题不能仅由编号组成，请添加具体的主题或说明";
    }
    return "";
  }

  function stripTag(str) {
    if (!str || typeof str !== "string") return "";
    return str.replace(/^【[^】]*】\s*/, "").trim();
  }

  function shareModelFrom(payload, kind) {
    var p = payload || {};
    var targetKind = (kind === "style" || kind === "layout") ? kind : "work";
    var allItems = normItems(p);

    if (targetKind === "work") {
      var it = allItems.find(function (x) { return x.kind === "work"; }) || p;
      var title = it.title || p.title || stripTag(p.topicTitle) || "";
      var prompt = it.prompt || p.prompt || "";
      var rawBody = p.topicBody;
      var cleanBody = (typeof rawBody === "string" && CANNED_BODIES.indexOf(rawBody.trim()) !== -1) ? "" : (rawBody || "");
      var notes = it.notes || it.description || p.text || cleanBody || "";

      var rawImgs = (it.images && it.images.length) ? it.images : p.images;
      var images = Array.isArray(rawImgs) ? rawImgs.slice() : (rawImgs ? [rawImgs] : []);

      var rawStyles = it.styles || p.styles || (p.style1 ? [p.style1] : []);
      var styles = Array.isArray(rawStyles) ? rawStyles.slice() : (rawStyles ? [rawStyles] : []);
      var layout = it.layout || p.layout || "";
      var ratio = it.ratio || p.ratio || "";
      var color = it.color || p.color || "";
      var tone = it.tone || p.tone || "";
      var mode = it.mode || p.mode || "";
      var mood = it.mood || p.mood || "";
      var subject = it.subject || p.subject || "";

      var workItem = {
        kind: "work",
        title: title,
        prompt: prompt,
        notes: notes,
        images: images,
        styles: styles,
        layout: layout
      };
      if (ratio) workItem.ratio = ratio;
      if (color) workItem.color = color;
      if (tone) workItem.tone = tone;
      if (mode) workItem.mode = mode;
      if (mood) workItem.mood = mood;
      if (subject) workItem.subject = subject;

      return {
        kind: "work",
        title: "",
        text: "",
        items: [workItem],
        rawPayload: p,
        skippedCount: 0
      };
    }

    var matched = allItems.filter(function (x) { return x.kind === targetKind; });
    var it = matched[0] || (allItems.length > 0 ? allItems[0] : p);
    var skippedCount = (matched.length > 1) ? (matched.length - 1) : (allItems.length > 1 ? allItems.length - 1 : 0);

    var c = coverOf(it);
    var exs = examplesOf(it);
    var name = it.name || it.title || "";
    var desc = it.description || it.notes || "";
    var def = it.definition || it.prompt || "";
    var rawCost = it.unlockCost != null ? it.unlockCost : (p.unlockCost != null ? p.unlockCost : (it.price != null ? it.price : (p.price != null ? p.price : 0)));
    var unlockCost = Math.max(0, Math.min(50, parseInt(rawCost, 10) || 0));

    var itemObj = Object.assign({}, it, {
      kind: targetKind,
      name: name,
      description: desc,
      definition: def,
      cover: c,
      images: exs,
      unlockCost: unlockCost
    });

    return {
      kind: targetKind,
      title: itemObj.name,
      text: itemObj.description,
      items: [itemObj],
      skippedCount: skippedCount,
      rawPayload: p
    };
  }

  function renderShare(root, params) {
    var epoch = ++EPOCH, username = currentUser();
    var kindDefault = (params.kind === "style" || params.kind === "layout") ? params.kind : "work";
    var editId = params.editId || ""; // revise target
    var draftId = params.draft || "";
    var formKey = uuid();
    var model = shareModelFrom(null, kindDefault);
    model.requestId = uuid();
    var resourceCache = {};
    var activeTarget = null;

    function updateActiveDropzoneUI() {
      var isWork = model.kind === "work";
      var dzs = root.querySelectorAll(".curation-dropzone");
      dzs.forEach(function (dz) {
        var tType = dz.getAttribute("data-target");
        var isActive = Boolean(activeTarget && (activeTarget === tType || (isWork && tType === "file")));
        if (isActive) {
          dz.classList.add("curation-dropzone-active");
        } else {
          dz.classList.remove("curation-dropzone-active");
        }
        var targetEl = dz.querySelector(".curation-dropzone-target");
        if (targetEl) {
          if (isActive) {
            var label = tType === "cover" ? "封面" : (isWork ? "作品图片" : "示例图");
            targetEl.innerHTML = '<span class="curation-dropzone-target-text">当前粘贴到：' + label + '</span>' +
              '<span class="curation-dropzone-shortcut">（按 Ctrl+V / ⌘V 粘贴）</span>';
            targetEl.removeAttribute("hidden");
          } else {
            targetEl.innerHTML = "";
            targetEl.setAttribute("hidden", "hidden");
          }
        }
      });
    }

    function setActiveTarget(t) {
      activeTarget = t;
      updateActiveDropzoneUI();
    }

    function resourceLabel(code, kind) {
      if (!code) return "";
      var m = resourceCache[code];
      if (m) return m;
      var map = App.resourceMap;
      var r = map && typeof map.get === "function" ? map.get(code) : null;
      return r ? { name: r.name || code, id: r.id || code, kind: r.kind, image: r.image } : { name: code, id: code, kind: kind, image: "" };
    }

    var stylesCache = {};
    function formStylesCache(idx) { return stylesCache[idx] || (stylesCache[idx] = {}); }

    function resourceChip(code, idx, target) {
      var r = resourceLabel(code, target === "layout" ? "layout" : "style");
      var src = r.image && typeof r.image === "string" ? r.image : "";
      return '<span class="curation-chip" data-code="' + esc(code) + '">' + imgTag(src, r.name) + '<b>' + esc(code) + '</b> ' + esc(r.name) + '</span>';
    }

    function getLen(str) {
      return str ? [...str].length : 0;
    }

    function draw() {
      var nav = ['share', 'mine', 'review'].map(function (tab) {
        return '<a class="curation-nav-' + (tab === "share" ? "on" : "") + '" href="' + esc(S.channelUrl("forum", { view: "curation", tab: tab })) + '">' +
          ({ share: "投稿", mine: "我的投稿", review: "审核队列" })[tab] + '</a>';
      });
      if (isAdmin()) nav.push('<a class="curation-nav-admin" href="' + esc(S.channelUrl("forum", { view: "curation", tab: "admin" })) + '">管理</a>');

      var h1Text = editId ? ("编辑重提 · " + esc(KIND_LABEL[model.kind] || "")) : "投稿并申请收录";

      var kindSwitchHtml = editId ? "" : (
        '<div class="curation-kind-switch" role="radiogroup" aria-label="投稿类型">' +
          ['work', 'style', 'layout'].map(function (k) {
            return '<label class="curation-kind-opt">' +
              '<input type="radio" name="share-kind" data-act="sharekind" value="' + k + '"' + (model.kind === k ? " checked" : "") + '> ' +
              esc(KIND_LABEL[k]) +
            '</label>';
          }).join("") +
        '</div>'
      );

      var setHtml = "";

      var itemsHtml = "";
      if (model.kind === "work") {
        var it = model.items[0] || {};
        var stylesHtml = "";
        if (it.styles && it.styles.length) {
          it.styles.forEach(function (c) {
            stylesHtml += resourceChip(c, 0, "style");
            formStylesCache(0)[c] = resourceLabel(c, "style");
          });
        }
        var layoutHtml = "";
        if (it.layout) {
          layoutHtml = resourceChip(it.layout, 0, "layout");
        }

        itemsHtml = (
          '<div class="curation-item" data-idx="0">' +
            '<label class="curation-field">作品标题<span class="curation-field-err" data-err-for="title"></span>' +
              '<input data-act="title" data-idx="0" value="' + esc(it.title || "") + '" maxlength="120" placeholder="例如：雨天便利店｜水彩画风尝试">' +
            '</label>' +
            '<p class="curation-help">示例：雨天便利店｜水彩画风尝试（至少 4 字，勿用纯编号或「图文模式」等占位词）。</p>' +
            '<div class="curation-imgs" data-imgs="0">' + (it.images || []).map(function (src, i) {
              return '<figure class="curation-thumb-wrap">' + imgTag(src, "预览") +
                '<button type="button" class="curation-x" data-act="delimg" data-idx="0" data-i="' + i + '" aria-label="删除图片">×</button></figure>';
            }).join("") + '</div>' +
            '<div class="curation-field">' +
              '<span class="curation-field-label">作品图片<span class="curation-field-err" data-err-for="file"></span></span>' +
              '<div class="curation-dropzone" data-dropzone="work" data-target="file" data-idx="0" tabindex="0" role="region" aria-label="作品图片上传区">' +
                '<input type="file" accept="image/*" multiple data-act="file" data-idx="0" class="curation-file-input" tabindex="-1" aria-hidden="true">' +
                '<div class="curation-dropzone-body">' +
                  '<div class="curation-dropzone-icon" aria-hidden="true">' +
                    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3" ry="3"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><path d="m21 15-5-5L5 21"></path></svg>' +
                  '</div>' +
                  '<button type="button" class="curation-dropzone-btn" data-act="browse" data-target="file" data-idx="0">选择图片</button>' +
                  '<p class="curation-dropzone-desc">' +
                    '<span class="curation-dropzone-desc-desk">选择、拖入或粘贴图片，最多 9 张</span>' +
                    '<span class="curation-dropzone-desc-mob">点击选择图片，最多 9 张</span>' +
                  '</p>' +
                  '<div class="curation-dropzone-target" aria-live="polite" hidden></div>' +
                '</div>' +
              '</div>' +
            '</div>' +
            '<label class="curation-field">生图提示词<span class="curation-field-err" data-err-for="prompt"></span>' +
              '<textarea data-act="prompt" data-idx="0" rows="5" maxlength="20000" placeholder="粘贴实际发给模型的完整提示词">' + esc(it.prompt || "") + '</textarea>' +
            '</label>' +
            '<p class="curation-help">读者看到并复制的就是这段原文。</p>' +
            '<label class="curation-field">创作说明（必填）<span class="curation-field-err" data-err-for="notes"></span>' +
              '<textarea data-act="notes" data-idx="0" rows="3" maxlength="1200" placeholder="例如：画了什么？尝试了什么？效果如何？（至少 8 字）">' + esc(it.notes || "") + '</textarea>' +
            '</label>' +
            '<p class="curation-help">示例：画了什么？尝试了什么？效果如何？将作为帖子正文展示。</p>' +
            '<div class="curation-pick">' +
              '<div class="curation-pick-row"><span>画风</span><button type="button" data-act="pick" data-idx="0" data-target="style">选择画风</button><span class="curation-chips" data-chip="style" data-idx="0">' + stylesHtml + '</span></div>' +
              '<div class="curation-pick-row"><span>图型</span><button type="button" data-act="pick" data-idx="0" data-target="layout">选择图型</button><span class="curation-chips" data-chip="layout" data-idx="0">' + layoutHtml + '</span></div>' +
            '</div>' +
          '</div>'
        );
      } else {
        var it = model.items[0] || {};
        var coverPreviewHtml = it.cover ? (
          '<div class="curation-cover-preview"><figure class="curation-thumb-wrap">' +
            imgTag(it.cover, "封面预览") +
            '<button type="button" class="curation-x" data-act="delcover" data-idx="0" aria-label="删除封面">×</button>' +
          '</figure></div>'
        ) : "";

        var coverHelpText = it.coverCropNote || "非正方形图片会自动居中裁剪";

        var examplesThumbHtml = (it.images && it.images.length) ? (
          '<div class="curation-imgs" data-imgs="0">' + it.images.map(function (src, i) {
            return '<figure class="curation-thumb-wrap">' + imgTag(src, "预览") +
              '<button type="button" class="curation-x" data-act="delimg" data-idx="0" data-i="' + i + '" aria-label="删除图片">×</button></figure>';
          }).join("") + '</div>'
        ) : '<div class="curation-imgs" data-imgs="0"></div>';

        itemsHtml = (
          '<div class="curation-item" data-idx="0">' +
            '<label class="curation-field">名称<span class="curation-field-err" data-err-for="name"></span>' +
              '<input data-act="name" data-idx="0" value="' + esc(it.name || "") + '" maxlength="80" placeholder="如：江南淡墨">' +
            '</label>' +
            '<div class="curation-cover">' +
              '<div class="curation-field">' +
                '<span class="curation-field-label">封面图 · 必填<span class="curation-field-err" data-err-for="cover"></span></span>' +
                '<div class="curation-dropzone" data-dropzone="cover" data-target="cover" data-idx="0" tabindex="0" role="region" aria-label="封面上传区">' +
                  '<input type="file" accept="image/*" data-act="cover" data-idx="0" class="curation-file-input" tabindex="-1" aria-hidden="true">' +
                  '<div class="curation-dropzone-body">' +
                    '<div class="curation-dropzone-icon" aria-hidden="true">' +
                      '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3" ry="3"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><path d="m21 15-5-5L5 21"></path></svg>' +
                    '</div>' +
                    '<button type="button" class="curation-dropzone-btn" data-act="browse" data-target="cover" data-idx="0">选择图片</button>' +
                    '<p class="curation-dropzone-desc">' +
                      '<span class="curation-dropzone-desc-desk">选择、拖入或粘贴图片；自动居中裁为正方形</span>' +
                      '<span class="curation-dropzone-desc-mob">点击选择图片；自动居中裁为正方形</span>' +
                    '</p>' +
                    '<div class="curation-dropzone-target" aria-live="polite" hidden></div>' +
                  '</div>' +
                '</div>' +
              '</div>' +
              coverPreviewHtml +
              '<p class="curation-help">' + esc(coverHelpText) + '</p>' +
            '</div>' +
            '<div class="curation-examples">' +
              '<div class="curation-field">' +
                '<span class="curation-field-label">示例图 · 可选，0–9 张<span class="curation-field-err" data-err-for="file"></span></span>' +
                '<div class="curation-dropzone" data-dropzone="examples" data-target="file" data-idx="0" tabindex="0" role="region" aria-label="示例图上传区">' +
                  '<input type="file" accept="image/*" multiple data-act="file" data-idx="0" class="curation-file-input" tabindex="-1" aria-hidden="true">' +
                  '<div class="curation-dropzone-body">' +
                    '<div class="curation-dropzone-icon" aria-hidden="true">' +
                      '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3" ry="3"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><path d="m21 15-5-5L5 21"></path></svg>' +
                    '</div>' +
                    '<button type="button" class="curation-dropzone-btn" data-act="browse" data-target="file" data-idx="0">选择图片</button>' +
                    '<p class="curation-dropzone-desc">' +
                      '<span class="curation-dropzone-desc-desk">选择、拖入或粘贴图片，比例不限</span>' +
                      '<span class="curation-dropzone-desc-mob">点击选择图片，比例不限</span>' +
                    '</p>' +
                    '<div class="curation-dropzone-target" aria-live="polite" hidden></div>' +
                  '</div>' +
                '</div>' +
              '</div>' +
              examplesThumbHtml +
            '</div>' +
            '<label class="curation-field">定义<span class="curation-field-err" data-err-for="definition"></span>' +
              '<textarea data-act="definition" data-idx="0" rows="4" maxlength="6000" placeholder="' +
                (model.kind === "style" ? "画风：笔触、用色、质感" : "图型：版式结构与元素位置") + '">' + esc(it.definition || "") + '</textarea>' +
            '</label>' +
            '<label class="curation-field">简介（必填）<span class="curation-field-err" data-err-for="description"></span>' +
              '<textarea data-act="description" data-idx="0" rows="2" maxlength="300" placeholder="例如：适合画什么？有什么特点？（至少 8 字）">' + esc(it.description || "") + '</textarea>' +
            '</label>' +
            '<p class="curation-help">示例：适合画什么？有什么特点？将作为资源帖公开介绍。</p>' +
            '<label class="curation-field">解锁积分<span class="curation-field-err" data-err-for="unlockCost"></span>' +
              '<input type="number" min="0" max="50" step="1" data-act="unlockCost" data-idx="0" value="' + esc(it.unlockCost != null ? it.unlockCost : 0) + '" placeholder="0–50 整数，0 为免费">' +
              '<div class="curation-price-presets" style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;">' +
                '<button type="button" class="hw-price-chip" data-set-cost="0">免费</button>' +
                '<button type="button" class="hw-price-chip" data-set-cost="5">5✦</button>' +
                '<button type="button" class="hw-price-chip" data-set-cost="10">10✦</button>' +
                '<button type="button" class="hw-price-chip" data-set-cost="20">20✦</button>' +
                '<button type="button" class="hw-price-chip" data-set-cost="50">50✦</button>' +
              '</div>' +
            '</label>' +
            ((it.unlockCost != null && it.unlockCost > 0) ? (
              '<p class="curation-help" data-help-for="unlockCost">' +
                '<strong>设置为付费' + esc(KIND_LABEL[model.kind] || "资源") + '后：</strong><br>' +
                '• 别人需要消耗 <strong>' + esc(it.unlockCost) + '</strong> 积分才能在创作台使用<br>' +
                '• 定义不会公开显示（未解锁看不到，解锁后也只在创作台生效）<br>' +
                '• 你按比例获得分成<br>' +
                '• 你自己使用不扣积分' +
              '</p>'
            ) : (
              '<p class="curation-help" data-help-for="unlockCost">0 为免费公开资源。所有人均可免费在创作台调用；设为 1–50 积分则需解锁后调用，你自己使用不扣积分。</p>'
            )) +
          '</div>'
        );
      }

      var addBtnHtml = "";

      var submitText = editId ? "提交新版本" : (model.kind === "work" ? "发布作品" : "发布到论坛并申请收录");

      root.innerHTML =
        '<div class="curation-page">' +
          '<nav class="curation-nav">' + nav.join("") + '</nav>' +
          '<h1 class="curation-h1">' + h1Text + '</h1>' +
          '<p class="curation-hint">图片先存入你的私有上传库，点击发布才公开。</p>' +
          (editId ? '<p class="curation-note">已收录项编辑后保留原帖；新版本审核期间旧版本继续使用。</p>' : '') +
          '<div class="curation-form">' +
            kindSwitchHtml +
            setHtml +
            '<div data-items>' + itemsHtml + '</div>' +
            addBtnHtml +
            '<p class="curation-err" data-err aria-live="polite"></p>' +
            '<button type="button" class="curation-submit" data-act="submit"' + (editId ? ' data-edit="1"' : '') + '>' + submitText + '</button>' +
          '</div>' +
        '</div>';

      if (model.skippedCount > 0) {
        var errEl = root.querySelector('[data-err]');
        if (errEl) errEl.textContent = "草稿中有 " + model.skippedCount + " 项与当前类型不符，已略过。";
      }

      bindImgs(root);
      bindShare();
    }

    function onInput(e) {
      var t = e.target, act = t.getAttribute && t.getAttribute("data-act");
      if (!act) return;
      if (act === "title") {
        if (model.items[0]) model.items[0].title = t.value;
      } else if (act === "prompt") {
        if (model.items[0]) model.items[0].prompt = t.value;
      } else if (act === "notes") {
        if (model.items[0]) model.items[0].notes = t.value;
      } else if (act === "name") {
        if (model.items[0]) {
          model.items[0].name = t.value;
          model.title = t.value;
        }
      } else if (act === "definition") {
        if (model.items[0]) model.items[0].definition = t.value;
      } else if (act === "description") {
        if (model.items[0]) {
          model.items[0].description = t.value;
          model.text = t.value;
        }
      } else if (act === "unlockCost") {
        var rawCost = t.value.trim();
        var numCost = rawCost === "" ? 0 : parseInt(rawCost, 10);
        if (isNaN(numCost)) numCost = 0;
        else if (numCost < 0) numCost = 0;
        else if (numCost > 50) numCost = 50;
        if (model.items[0]) model.items[0].unlockCost = numCost;
        var cHelp = root.querySelector('[data-help-for="unlockCost"]');
        if (cHelp) {
          cHelp.innerHTML = numCost > 0 ? (
            '<strong>设置为付费' + esc(KIND_LABEL[model.kind] || "资源") + '后：</strong><br>' +
            '• 别人需要消耗 <strong>' + esc(numCost) + '</strong> 积分才能在创作台使用<br>' +
            '• 定义不会公开显示（未解锁看不到，解锁后也只在创作台生效）<br>' +
            '• 你按比例获得分成<br>' +
            '• 你自己使用不扣积分'
          ) : (
            '0 为免费公开资源。所有人均可免费在创作台调用；设为 1–50 积分则需解锁后调用，你自己使用不扣积分。'
          );
        }
      }
      model.requestId = uuid();

      var label = t.closest(".curation-field") || t.closest("label");
      if (label) {
        var errSpan = label.querySelector('[data-err-for="' + act + '"]');
        if (errSpan) errSpan.textContent = "";
        t.removeAttribute("aria-invalid");
        t.removeAttribute("aria-describedby");
      }
      var errEl = root.querySelector('[data-err]');
      if (errEl && errEl.textContent.indexOf("还有") === 0) {
        var remaining = 0;
        root.querySelectorAll('.curation-field-err').forEach(function (s) {
          if (s.textContent.trim()) remaining++;
        });
        if (remaining > 0) {
          errEl.textContent = "还有 " + remaining + " 处需要修改。";
        } else {
          errEl.textContent = "";
        }
      }
    }

    function onKindChange(e) {
      var newKind = e.target.value;
      if (newKind === model.kind) return;
      activeTarget = null;

      if (newKind === "work") {
        var it = model.items[0] || {};
        var imgs = [];
        if (it.cover) imgs.push(it.cover);
        if (it.images) imgs = imgs.concat(it.images);
        model.items = [{
          kind: "work",
          title: it.name || it.title || "",
          prompt: it.definition || it.prompt || "",
          notes: it.description || it.notes || "",
          images: imgs,
          styles: it.styles || [],
          layout: it.layout || ""
        }];
        model.kind = "work";
        model.title = "";
        model.text = "";
      } else if (model.kind === "work") {
        var it = model.items[0] || {};
        var c = (it.images && it.images[0]) || "";
        var exs = (it.images && it.images.length > 1) ? it.images.slice(1) : [];
        var rawCost = it.unlockCost != null ? it.unlockCost : 0;
        var unlockCost = Math.max(0, Math.min(50, parseInt(rawCost, 10) || 0));
        model.items = [{
          kind: newKind,
          name: it.title || it.name || "",
          definition: it.prompt || it.definition || "",
          description: it.notes || it.description || "",
          cover: c,
          images: exs,
          unlockCost: unlockCost
        }];
        model.kind = newKind;
        model.title = model.items[0].name;
        model.text = model.items[0].description;
      } else {
        model.kind = newKind;
        if (model.items[0]) {
          model.items[0].kind = newKind;
        }
      }

      model.requestId = uuid();
      draw();
      if (model.kind !== "work" && model.items[0] && model.items[0].cover) {
        checkCoverSquare(model.items[0], function () {
          if (!guard(epoch, username)) return;
          var it = model.items[0];
          if (it && it.coverSquare === false) {
            var errSpan = root.querySelector('[data-err-for="cover"]');
            if (errSpan) {
              errSpan.textContent = "封面需要是正方形（当前 " + (it.coverDims || "") + "），请重新选择或使用自动裁剪。";
            }
          }
        });
      }
    }

    function checkCoverSquare(it, onDone) {
      if (!it || !it.cover) {
        it.coverSquare = undefined;
        it.coverDims = "";
        if (typeof onDone === "function") onDone();
        return;
      }
      var Img = (typeof Image !== "undefined") ? Image : (window.Image || null);
      if (!Img) {
        if (typeof onDone === "function") onDone();
        return;
      }
      var img = new Img();
      img.onload = function () {
        var w = img.naturalWidth || img.width || 0;
        var h = img.naturalHeight || img.height || 0;
        it.coverDims = w + "×" + h;
        it.coverSquare = isSquare(w, h);
        if (typeof onDone === "function") onDone();
      };
      img.onerror = function () {
        it.coverSquare = undefined;
        it.coverDims = "";
        if (typeof onDone === "function") onDone();
      };
      img.src = it.cover;
    }

    function processCoverUpload(file, it) {
      return readFile(file).then(function (dataUrl) {
        return new Promise(function (resolve, reject) {
          var Img = (typeof Image !== "undefined") ? Image : (window.Image || null);
          if (!Img) {
            uploadDataUrl(dataUrl, file.name).then(function (url) {
              it.coverCropNote = "";
              it.coverSquare = undefined;
              resolve(url);
            }).catch(reject);
            return;
          }
          var img = new Img();
          img.onload = function () {
            var w = img.naturalWidth || img.width || 0;
            var h = img.naturalHeight || img.height || 0;
            if (isSquare(w, h)) {
              it.coverCropNote = "";
              it.coverSquare = true;
              it.coverDims = w + "×" + h;
              uploadDataUrl(dataUrl, file.name).then(resolve).catch(reject);
            } else {
              try {
                var s = Math.min(Math.min(w, h), 2048);
                var canvas = document.createElement("canvas");
                canvas.width = s;
                canvas.height = s;
                var ctx = canvas.getContext("2d");
                if (ctx && typeof ctx.fillRect === "function") {
                  ctx.fillStyle = "#ffffff";
                  ctx.fillRect(0, 0, s, s);
                  var cropSize = Math.min(w, h);
                  var sx = Math.floor((w - cropSize) / 2);
                  var sy = Math.floor((h - cropSize) / 2);
                  if (typeof ctx.drawImage === "function") {
                    ctx.drawImage(img, sx, sy, cropSize, cropSize, 0, 0, s, s);
                  }
                }
                var croppedDataUrl = (typeof canvas.toDataURL === "function") ?
                  canvas.toDataURL("image/jpeg", 0.92) : dataUrl;
                it.coverCropNote = "已自动居中裁剪为正方形（原尺寸 " + w + "×" + h + "）";
                it.coverSquare = true;
                it.coverDims = s + "×" + s;
                uploadDataUrl(croppedDataUrl, file.name).then(resolve).catch(reject);
              } catch (err) {
                it.coverCropNote = "";
                uploadDataUrl(dataUrl, file.name).then(resolve).catch(reject);
              }
            }
          };
          img.onerror = function () {
            reject(new Error("图片无法解析"));
          };
          img.src = dataUrl;
        });
      });
    }

    var isUploading = false;

    function uploadFiles(files, idx, targetType) {
      var it = model.items[idx || 0];
      var fileList = Array.from(files || []);
      if (!it || !fileList.length) return;

      var isWork = model.kind === "work";
      if (isWork) {
        targetType = "file";
      }

      var coverFile = null;
      var sampleFiles = [];

      if (targetType === "cover") {
        if (fileList.length > 1) {
          var coverErrSpan = root.querySelector('[data-err-for="cover"]');
          if (coverErrSpan) coverErrSpan.textContent = "封面只能上传 1 张图片，当前包含 " + fileList.length + " 张。";
          var cIn = root.querySelector('input[data-act="cover"]');
          if (cIn) cIn.value = "";
          return;
        }
        coverFile = fileList[0];
      } else if (targetType === "file") {
        sampleFiles = fileList;
      } else {
        // "auto" mode for style / layout
        if (!it.cover) {
          coverFile = fileList[0];
          sampleFiles = fileList.slice(1);
        } else {
          sampleFiles = fileList;
        }
      }

      // Validations:
      if (coverFile && coverFile.size > 15 * 1024 * 1024) {
        var cErr = root.querySelector('[data-err-for="cover"]');
        if (cErr) cErr.textContent = "单张图片请小于15MB";
        var cIn2 = root.querySelector('input[data-act="cover"]');
        if (cIn2) cIn2.value = "";
        return;
      }

      if (sampleFiles.length > 0) {
        var curImgs = it.images || [];
        var totalCount = sampleFiles.length + curImgs.length;
        if (totalCount > 9) {
          var fErr = root.querySelector('[data-err-for="file"]');
          if (fErr) {
            fErr.textContent = (isWork ? "作品图片最多 9 张，当前 " : "示例图最多 9 张，当前 ") + totalCount + " 张。";
          }
          var fIn = root.querySelector('input[data-act="file"]');
          if (fIn) fIn.value = "";
          return;
        }
        if (sampleFiles.some(function (f) { return f.size > 15 * 1024 * 1024; })) {
          var fErr2 = root.querySelector('[data-err-for="file"]');
          if (fErr2) fErr2.textContent = "单张图片请小于15MB";
          var fIn2 = root.querySelector('input[data-act="file"]');
          if (fIn2) fIn2.value = "";
          return;
        }
      }

      // Clear errors
      if (coverFile) {
        var cErrClear = root.querySelector('[data-err-for="cover"]');
        if (cErrClear) cErrClear.textContent = "";
      }
      if (sampleFiles.length > 0) {
        var fErrClear = root.querySelector('[data-err-for="file"]');
        if (fErrClear) fErrClear.textContent = "";
        var fInputEl = root.querySelector('input[data-act="file"]');
        if (fInputEl) {
          fInputEl.removeAttribute("aria-invalid");
          fInputEl.removeAttribute("aria-describedby");
        }
      }
      var mainErr = root.querySelector('[data-err]');
      if (mainErr) mainErr.textContent = "";

      var btn = root.querySelector('[data-act="submit"]');
      if (btn) btn.disabled = true;
      isUploading = true;

      var tasks = [];
      if (coverFile) {
        tasks.push(
          processCoverUpload(coverFile, it).then(function (url) {
            return { type: "cover", url: url };
          })
        );
      }
      if (sampleFiles.length > 0) {
        var jobs = sampleFiles.map(function (f) {
          return readFile(f).then(function (d) {
            return uploadDataUrl(d, f.name);
          });
        });
        tasks.push(
          Promise.all(jobs).then(function (urls) {
            return { type: "file", urls: urls, count: sampleFiles.length };
          })
        );
      }

      Promise.all(tasks).then(function (results) {
        if (!guard(epoch, username)) return;
        var hasCoverResult = false;
        var addedCount = 0;
        results.forEach(function (res) {
          if (res.type === "cover" && res.url) {
            it.cover = res.url;
            hasCoverResult = true;
          } else if (res.type === "file" && res.urls) {
            it.images = it.images || [];
            res.urls.forEach(function (u) {
              if (u) {
                it.images.push(u);
                addedCount++;
              }
            });
          }
        });
        model.requestId = uuid();
        draw();

        var msg = "";
        if (hasCoverResult && addedCount > 0) {
          msg = "已设置封面 / 已加入 " + addedCount + " 张示例图";
        } else if (hasCoverResult) {
          msg = "已设置封面";
        } else if (addedCount > 0) {
          msg = isWork
            ? ("已加入 " + addedCount + " 张作品图")
            : ("已加入 " + addedCount + " 张示例图");
        }
        if (msg && S && typeof S.toast === "function") {
          S.toast(msg);
        }
      }).catch(function (err) {
        if (coverFile) {
          var coverErr = root.querySelector('[data-err-for="cover"]');
          if (coverErr) coverErr.textContent = "封面上传失败：" + ((err && err.message) || "请重试");
        }
        if (sampleFiles.length > 0) {
          var fileErr = root.querySelector('[data-err-for="file"]');
          if (fileErr) fileErr.textContent = "图片上传失败：" + ((err && err.message) || "请重试");
        }
      }).then(function () {
        isUploading = false;
        var submitBtn = root.querySelector('[data-act="submit"]');
        if (submitBtn) submitBtn.disabled = false;
        var coverIn = root.querySelector('input[data-act="cover"]');
        if (coverIn) coverIn.value = "";
        var fileIn = root.querySelector('input[data-act="file"]');
        if (fileIn) fileIn.value = "";
      });
    }

    function onCoverFile(e) {
      var idx = parseInt(e.target.getAttribute("data-idx"), 10) || 0;
      uploadFiles(e.target.files, idx, "cover");
    }

    function onFiles(e) {
      var idx = parseInt(e.target.getAttribute("data-idx"), 10) || 0;
      uploadFiles(e.target.files, idx, "file");
    }

    function onPaste(e) {
      var cd = e.clipboardData || window.clipboardData;
      if (!cd) return;

      var targetEl = e.target || document.activeElement;

      function isTextInput(el) {
        if (!el) return false;
        var tag = (el.tagName || "").toUpperCase();
        if (tag === "TEXTAREA") return true;
        if (tag === "INPUT") {
          var t = (el.type || "").toLowerCase();
          return t === "text" || t === "search" || t === "url" || t === "tel" || t === "password" || t === "number" || !t;
        }
        if (el.isContentEditable) return true;
        return false;
      }

      var text = "";
      try {
        text = (typeof cd.getData === "function") ? cd.getData("text/plain") : "";
      } catch (ex) {}

      var hasText = typeof text === "string" && text.length > 0;

      if (isTextInput(targetEl) && hasText) {
        return;
      }

      var imageFiles = [];
      if (cd.items && cd.items.length) {
        for (var i = 0; i < cd.items.length; i++) {
          var item = cd.items[i];
          if (item && item.kind === "file") {
            var itemType = (item.type || "").toLowerCase();
            if (itemType.indexOf("image/") === 0) {
              var f = typeof item.getAsFile === "function" ? item.getAsFile() : null;
              if (f) imageFiles.push(f);
            }
          }
        }
      }
      if (!imageFiles.length && cd.files && cd.files.length) {
        for (var j = 0; j < cd.files.length; j++) {
          var file = cd.files[j];
          var fType = (file.type || "").toLowerCase();
          if (fType.indexOf("image/") === 0 || (!fType && file.name && /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(file.name))) {
            imageFiles.push(file);
          }
        }
      }

      if (!imageFiles.length) {
        var html = "";
        try {
          html = (typeof cd.getData === "function") ? cd.getData("text/html") : "";
        } catch (ex) {}
        var hasHtml = typeof html === "string" && html.trim().length > 0;
        var isLink = typeof text === "string" && /^https?:\/\//i.test(text.trim());

        if ((hasHtml || isLink) && !isTextInput(targetEl)) {
          if (typeof e.preventDefault === "function") e.preventDefault();
          var tipMsg = "剪贴板仅包含链接，请改用选择文件";
          var errEl = root.querySelector('[data-err]');
          if (errEl) errEl.textContent = tipMsg;
          if (S && typeof S.toast === "function") S.toast(tipMsg);
        }
        return;
      }

      if (typeof e.preventDefault === "function") e.preventDefault();

      var cardIdx = 0;
      var itemEl = targetEl && targetEl.closest ? targetEl.closest(".curation-item") : null;
      if (itemEl && itemEl.getAttribute("data-idx")) {
        cardIdx = parseInt(itemEl.getAttribute("data-idx"), 10) || 0;
      }

      var targetType = "auto";
      if (model.kind === "work") {
        targetType = "file";
      } else {
        var isCover = false;
        if (targetEl && targetEl.closest) {
          if (targetEl.closest(".curation-cover") || targetEl.closest('[data-dropzone="cover"]') || (targetEl.getAttribute && targetEl.getAttribute("data-act") === "cover")) {
            isCover = true;
          }
        }
        var isExamples = false;
        if (targetEl && targetEl.closest) {
          if (targetEl.closest(".curation-examples") || targetEl.closest('[data-dropzone="examples"]') || (targetEl.getAttribute && targetEl.getAttribute("data-act") === "file")) {
            isExamples = true;
          }
        }

        if (isCover) {
          targetType = "cover";
        } else if (isExamples) {
          targetType = "file";
        } else if (activeTarget === "cover") {
          targetType = "cover";
        } else if (activeTarget === "file") {
          targetType = "file";
        } else {
          targetType = "auto";
        }
      }

      uploadFiles(imageFiles, cardIdx, targetType);
    }

    function onClick(e) {
      var t = e.target.closest("[data-act]"); if (!t) return;
      var act = t.getAttribute("data-act");
      if (act === "delcover") {
        var it = model.items[0];
        if (it) {
          it.cover = "";
          it.coverSquare = undefined;
          it.coverDims = "";
          it.coverCropNote = "";
          model.requestId = uuid();
          draw();
        }
      } else if (act === "delimg") {
        var it = model.items[0]; if (!it) return;
        var i = +t.getAttribute("data-i");
        (it.images || []).splice(i, 1);
        model.requestId = uuid();
        draw();
      } else if (act === "pick") {
        pickResource(0, t.getAttribute("data-target"));
      } else if (act === "submit") {
        submit(t, t.getAttribute("data-edit") === "1");
      }
    }

    function pickResource(idx, target) {
      var it = model.items[idx]; if (!it) return;
      var cur = target === "layout" ? it.layout : (it.styles && it.styles[0]);
      if (typeof S.openAssetPickerModal !== "function") return;
      S.openAssetPickerModal({
        kind: target === "layout" ? "layout" : "style",
        currentId: cur || "",
        onSelect: function (asset) {
          if (!asset) return;
          if (!guard(epoch, username)) return;
          if (typeof asset === "string") asset = App.resourceMap.get(asset) || { id: asset };
          var code = asset.code || asset.id || asset.style || asset.layout || "";
          var label = { name: asset.name || code, id: code, kind: asset.kind || target, image: asset.image || asset.thumb || "" };
          resourceCache[code] = label;
          if (target === "layout") it.layout = code;
          else { it.styles = [code]; }
          model.requestId = uuid();
          draw();
        }
      });
    }

    function validate() {
      var errors = [];

      if (model.kind === "work") {
        var it = model.items[0] || {};
        var titleEl = root.querySelector('[data-act="title"]');
        var fileEl = root.querySelector('[data-act="file"]');
        var promptEl = root.querySelector('[data-act="prompt"]');
        var notesEl = root.querySelector('[data-act="notes"]');

        var titleVal = (it.title || "").trim();
        var titleErr = validateTopicTitle(titleVal);
        if (titleErr) {
          errors.push({ el: titleEl, act: "title", message: titleErr });
        } else if (getLen(it.title) > 120) {
          errors.push({ el: titleEl, act: "title", message: "最多 120 字，当前 " + getLen(it.title) + " 字。" });
        }

        if (!it.images || it.images.length === 0) {
          errors.push({ el: fileEl, act: "file", message: "请至少上传一张图片。" });
        } else if (it.images.length > 9) {
          errors.push({ el: fileEl, act: "file", message: "作品图片最多 9 张，当前 " + it.images.length + " 张。" });
        }

        var promptVal = (it.prompt || "").trim();
        if (!promptVal) {
          errors.push({ el: promptEl, act: "prompt", message: "请填写生图提示词。" });
        } else if (getLen(it.prompt) > 20000) {
          errors.push({ el: promptEl, act: "prompt", message: "最多 20000 字，当前 " + getLen(it.prompt) + " 字。" });
        }

        var notesVal = (it.notes || "").trim();
        var notesNonWs = notesVal.replace(/\s+/g, "");
        if (!notesNonWs) {
          errors.push({ el: notesEl, act: "notes", message: "请填写作品创作说明（至少 8 字）。" });
        } else if (notesNonWs.length < 8) {
          errors.push({ el: notesEl, act: "notes", message: "创作说明至少需要 8 个字，当前 " + notesNonWs.length + " 字。" });
        } else if (getLen(it.notes) > 1200) {
          errors.push({ el: notesEl, act: "notes", message: "最多 1200 字，当前 " + getLen(it.notes) + " 字。" });
        }
      } else {
        var it = model.items[0] || {};
        var nameEl = root.querySelector('[data-act="name"]');
        var coverEl = root.querySelector('[data-act="cover"]');
        var fileEl = root.querySelector('[data-act="file"]');
        var defEl = root.querySelector('[data-act="definition"]');
        var descEl = root.querySelector('[data-act="description"]');
        var costEl = root.querySelector('[data-act="unlockCost"]');

        var nameVal = (it.name || "").trim();
        if (!nameVal) {
          errors.push({ el: nameEl, act: "name", idx: 0, message: "请填写名称。" });
        } else if (getLen(it.name) > 80) {
          errors.push({ el: nameEl, act: "name", idx: 0, message: "最多 80 字，当前 " + getLen(it.name) + " 字。" });
        }

        var covVal = (it.cover || "").trim();
        if (!covVal) {
          errors.push({ el: coverEl, act: "cover", idx: 0, message: "请上传一张正方形封面图。" });
        } else if (it.coverSquare === false) {
          errors.push({
            el: coverEl,
            act: "cover",
            idx: 0,
            message: "封面需要是正方形（当前 " + (it.coverDims || "") + "），请重新选择或使用自动裁剪。"
          });
        }

        if (it.images && it.images.length > 9) {
          errors.push({ el: fileEl, act: "file", idx: 0, message: "示例图最多 9 张，当前 " + it.images.length + " 张。" });
        }

        var defVal = (it.definition || "").trim();
        if (!defVal) {
          errors.push({ el: defEl, act: "definition", idx: 0, message: "请填写定义。" });
        } else if (getLen(it.definition) > 6000) {
          errors.push({ el: defEl, act: "definition", idx: 0, message: "最多 6000 字，当前 " + getLen(it.definition) + " 字。" });
        }

        var descVal = (it.description || "").trim();
        var descNonWs = descVal.replace(/\s+/g, "");
        if (!descNonWs) {
          errors.push({ el: descEl, act: "description", idx: 0, message: "请填写简介（至少 8 字）。" });
        } else if (descNonWs.length < 8) {
          errors.push({ el: descEl, act: "description", idx: 0, message: "简介至少需要 8 个字，当前 " + descNonWs.length + " 字。" });
        } else if (getLen(it.description) > 300) {
          errors.push({ el: descEl, act: "description", idx: 0, message: "最多 300 字，当前 " + getLen(it.description) + " 字。" });
        }

        var costVal = parseInt(it.unlockCost, 10);
        if (isNaN(costVal) || costVal < 0 || costVal > 50) {
          errors.push({ el: costEl, act: "unlockCost", idx: 0, message: "解锁积分需在 0 到 50 之间。" });
        }
      }

      return errors;
    }

    function submit(btn, isEdit) {
      if (isUploading) return;
      var errEl = root.querySelector('[data-err]');
      if (errEl) errEl.textContent = "";

      root.querySelectorAll('.curation-field-err').forEach(function (s) { s.textContent = ""; });
      root.querySelectorAll('[aria-invalid]').forEach(function (el) {
        el.removeAttribute("aria-invalid");
        el.removeAttribute("aria-describedby");
      });

      var errors = validate();
      if (errors.length > 0) {
        errors.forEach(function (err) {
          var label = err.el ? (err.el.closest(".curation-field") || err.el.closest("label")) : null;
          var errSpan = label ? label.querySelector('[data-err-for="' + err.act + '"]') : null;
          if (errSpan) {
            errSpan.textContent = err.message;
            var errId = "curation-err-" + err.act + "-" + (err.idx || 0);
            errSpan.id = errId;
            if (err.el) {
              err.el.setAttribute("aria-invalid", "true");
              err.el.setAttribute("aria-describedby", errId);
            }
          }
        });

        if (errEl) errEl.textContent = "还有 " + errors.length + " 处需要修改。";

        if (errors[0].el && typeof errors[0].el.focus === "function") {
          errors[0].el.focus();
        }
        return;
      }

      var url, method = "POST", body;
      var isWork = model.kind === "work";

      if (isEdit && editId) {
        url = "/api/curation/submissions/" + encodeURIComponent(editId) + "/revise";
        var currentItem = model.items[0] || {};
        var payloadItem = Object.assign({}, model.rawPayload || {});
        if (model.kind === "work") {
          delete payloadItem.price;
          payloadItem.title = (currentItem.title || "").trim();
          payloadItem.prompt = currentItem.prompt || "";
          payloadItem.notes = currentItem.notes || "";
          payloadItem.images = (currentItem.images || []).slice();
          if (currentItem.styles) payloadItem.styles = currentItem.styles.slice();
          if (currentItem.layout) payloadItem.layout = currentItem.layout;
        } else {
          payloadItem.kind = model.kind;
          payloadItem.name = (currentItem.name || "").trim();
          payloadItem.description = currentItem.description || "";
          payloadItem.definition = currentItem.definition || "";
          payloadItem.cover = currentItem.cover || "";
          payloadItem.images = (currentItem.images || []).slice();
          if (currentItem.unlockCost != null) {
            payloadItem.unlockCost = Math.max(0, Math.min(50, parseInt(currentItem.unlockCost, 10) || 0));
          }
        }
        if (payloadItem.prompt === "[包含资源专属指令，已隐藏]") payloadItem.prompt = "";
        if (payloadItem.subject === "[包含资源专属指令，已隐藏]") payloadItem.subject = "";
        if (payloadItem.definition === "[包含资源专属指令，已隐藏]") payloadItem.definition = "";
        body = { payload: payloadItem };
      } else if (isWork) {
        var work = model.items[0] || {};
        url = "/api/works";
        var workBody = {
          title: work.title.trim(),
          prompt: work.prompt,
          notes: work.notes || "",
          images: (work.images || []).slice(),
          requestId: model.requestId
        };
        if (work.styles && work.styles[0]) workBody.styles = [work.styles[0]];
        else if (work.styles && work.styles.length) workBody.styles = work.styles.slice();
        if (work.layout) workBody.layout = work.layout;
        if (work.ratio) workBody.ratio = work.ratio;
        if (work.color) workBody.color = work.color;
        if (work.tone) workBody.tone = work.tone;
        if (work.mode) workBody.mode = work.mode;
        if (work.mood) workBody.mood = work.mood;
        if (work.subject) workBody.subject = work.subject;
        body = workBody;
      } else {
        url = "/api/curation/submissions";
        var it = model.items[0] || {};
        var subTitle = (it.name || "").trim();
        var subText = it.description || "";
        var itemObj = {
          kind: it.kind,
          name: subTitle,
          description: subText,
          definition: it.definition || "",
          cover: it.cover || "",
          images: (it.images || []).slice(),
          unlockCost: Math.max(0, Math.min(50, parseInt(it.unlockCost, 10) || 0))
        };
        if (it.group != null) itemObj.group = it.group;
        body = {
          title: subTitle,
          text: subText,
          requestId: model.requestId,
          items: [itemObj]
        };
      }

      btn.disabled = true;
      var prev = btn.textContent; btn.textContent = "提交中…";
      api(url, { method: method, body: body }).then(function (res) {
        if (!guard(epoch, username)) return;
        if (isWork) {
          try {
            location.href = res.topicId ? S.channelUrl("forum", { view: "topic", id: res.topicId }) : S.channelUrl("main", { view: "work", id: res.workId });
          } catch (e) {
            if (errEl) errEl.textContent = "作品已发布。";
          }
          if (typeof S.refreshFromServer === "function") S.refreshFromServer();
          return;
        }
        var topicId = res && (res.topicId || res.id);
        if (topicId) {
          try { location.href = S.channelUrl("forum", { view: "topic", id: topicId }); }
          catch (e) { if (errEl) errEl.textContent = "已提交，请手动前往原帖。"; }
        } else {
          if (errEl) errEl.textContent = "提交成功，但未返回帖子地址。";
          if (typeof S.refreshFromServer === "function") S.refreshFromServer();
        }
      }).catch(function (err) {
        if (errEl) errEl.textContent = "提交失败：" + ((err && err.message) || "请重试");
      }).then(function () {
        btn.disabled = false; btn.textContent = prev;
      });
    }

    function bindDropzones() {
      var dzs = root.querySelectorAll(".curation-dropzone");
      dzs.forEach(function (dz) {
        var tType = dz.getAttribute("data-target") || "file";

        function onActivate() {
          setActiveTarget(tType);
        }

        dz.addEventListener("click", function (e) {
          if (e.target && e.target.closest && e.target.closest(".curation-dropzone-btn")) {
            return;
          }
          onActivate();
        });
        dz.addEventListener("focusin", onActivate);

        var btn = dz.querySelector(".curation-dropzone-btn");
        var input = dz.querySelector("input[type=file]");

        if (btn) {
          btn.addEventListener("click", function (e) {
            e.stopPropagation();
            onActivate();
            if (input && typeof input.click === "function") {
              input.click();
            }
          });
        }

        if (input) {
          input.addEventListener("focus", onActivate);
          input.addEventListener("click", onActivate);
        }

        dz.addEventListener("dragenter", function (e) {
          e.preventDefault();
          e.stopPropagation();
          dz.classList.add("curation-dropzone-dragover");
        });
        dz.addEventListener("dragover", function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (e.dataTransfer) {
            try { e.dataTransfer.dropEffect = "copy"; } catch (err) {}
          }
          dz.classList.add("curation-dropzone-dragover");
        });
        dz.addEventListener("dragleave", function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (e.relatedTarget && typeof dz.contains === "function" && dz.contains(e.relatedTarget)) {
            return;
          }
          dz.classList.remove("curation-dropzone-dragover");
        });
        dz.addEventListener("drop", function (e) {
          e.preventDefault();
          e.stopPropagation();
          dz.classList.remove("curation-dropzone-dragover");
          setActiveTarget(tType);

          var dt = e.dataTransfer;
          if (!dt) return;

          var rawFiles = [];
          if (dt.files && dt.files.length) {
            rawFiles = Array.from(dt.files);
          } else if (dt.items && dt.items.length) {
            for (var i = 0; i < dt.items.length; i++) {
              var itm = dt.items[i];
              if (itm && itm.kind === "file") {
                var f = typeof itm.getAsFile === "function" ? itm.getAsFile() : null;
                if (f) rawFiles.push(f);
              }
            }
          }

          var imageFiles = rawFiles.filter(function (file) {
            var fType = (file.type || "").toLowerCase();
            return fType.indexOf("image/") === 0 || (!fType && file.name && /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(file.name));
          });

          if (!imageFiles.length) {
            return;
          }

          var idx = parseInt(dz.getAttribute("data-idx"), 10) || 0;
          uploadFiles(imageFiles, idx, tType);
        });
      });
    }

    function bindShare() {
      var form = root.querySelector(".curation-form"); if (!form) return;
      bindDropzones();
      updateActiveDropzoneUI();
      form.addEventListener("dragover", function (e) { e.preventDefault(); });
      form.addEventListener("drop", function (e) { e.preventDefault(); });
      form.addEventListener("input", onInput);
      form.addEventListener("paste", onPaste);
      form.addEventListener("change", function (e) {
        var act = e.target.getAttribute("data-act");
        if (act === "sharekind") onKindChange(e);
        else if (act === "cover") onCoverFile(e);
        else if (act === "file") onFiles(e);
        else if (act === "unlockCost") {
          var it = model.items[0];
          if (it && it.unlockCost != null) e.target.value = it.unlockCost;
        }
      });
      form.addEventListener("click", function (e) {
        var btnCost = e.target.closest("[data-set-cost]");
        if (btnCost) {
          e.preventDefault();
          var cVal = parseInt(btnCost.getAttribute("data-set-cost"), 10);
          var cInput = root.querySelector('input[data-act="unlockCost"]');
          if (cInput) {
            cInput.value = cVal;
            cInput.dispatchEvent(new Event("input", { bubbles: true }));
          }
          return;
        }
        onClick(e);
      });
    }

    var preload = editId ? api("/api/curation/mine").then(function(res) {
      if (!guard(epoch, username)) return;
      var found = (res.submissions || []).find(function(it) { return it.id === editId; });
      if (!found) throw new Error("投稿不存在");
      var subKind = (found.payload && found.payload.kind) || found.kind || kindDefault;
      model = shareModelFrom(found.payload, subKind);
      model.rawPayload = found.payload;
      kindDefault = subKind;
    }) : draftId ? (function () {
      var resolvedDraftId = (draftId.length < 32 && /^[0-9a-f]+$/i.test(draftId)) ? draftId.padEnd(32, "0") : draftId;
      return api("/api/curation/drafts/" + encodeURIComponent(resolvedDraftId), { method: "GET" });
    })().then(function (res) {
      if (!guard(epoch, username)) return;
      var p = res && res.payload; if (!p) return;
      model = shareModelFrom(p, kindDefault);
      model.rawPayload = p;
    }).catch(function () {
      if (guard(epoch, username)) {
        var errEl = root.querySelector('[data-err]');
        if (errEl) errEl.textContent = "草稿加载失败。";
      }
    }) : Promise.resolve();

    draw();
    if (model.kind !== "work" && model.items[0] && model.items[0].cover) {
      checkCoverSquare(model.items[0], function () {
        if (!guard(epoch, username)) return;
        var it = model.items[0];
        if (it && it.coverSquare === false) {
          var errSpan = root.querySelector('[data-err-for="cover"]');
          if (errSpan) {
            errSpan.textContent = "封面需要是正方形（当前 " + (it.coverDims || "") + "），请重新选择或使用自动裁剪。";
          }
        }
      });
    }

    preload.then(function () {
      if (guard(epoch, username)) {
        draw();
        if (model.kind !== "work" && model.items[0] && model.items[0].cover) {
          checkCoverSquare(model.items[0], function () {
            if (!guard(epoch, username)) return;
            var it = model.items[0];
            if (it && it.coverSquare === false) {
              var errSpan = root.querySelector('[data-err-for="cover"]');
              if (errSpan) {
                errSpan.textContent = "封面需要是正方形（当前 " + (it.coverDims || "") + "），请重新选择或使用自动裁剪。";
              }
            }
          });
        }
      }
    }).catch(function(err) {
      if (guard(epoch, username)) {
        var errEl = root.querySelector('[data-err]');
        if (errEl) errEl.textContent = '加载投稿失败：' + err.message;
      }
    });
  }

  /* ================= MINE (page 2) ================= */
  function renderMine(root) {
    var epoch = ++EPOCH, username = currentUser();
    if (!App.state.loggedIn) {
      root.innerHTML = '<div class="curation-page"><p class="curation-empty">请先登录查看我的投稿。</p><button class="curation-submit" data-act="login">登录</button></div>';
      root.querySelector('[data-act="login"]').addEventListener("click", function () { S.openLoginModal("查看我的投稿", function () { renderMine(root); }); });
      return;
    }
    root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("mine") + '</nav><p class="curation-empty">加载中…</p></div>';
    api("/api/curation/mine", { method: "GET" }).then(function (res) {
      if (!guard(epoch, username)) return;
      var subs = (res && res.submissions) || [];
      draw(subs);
    }).catch(function (err) {
      if (!guard(epoch, username)) return;
      root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("mine") + '</nav><p class="curation-err">加载失败：' + esc(err && err.message) + '</p></div>';
    });

    function draw(subs) {
      var cards = subs.length ? subs.map(subCard).join("") : '<p class="curation-empty">还没有投稿，去「投稿」发起一次。</p>';
      root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("mine") + '</nav><h1 class="curation-h1">我的投稿</h1>' + cards + '</div>';
      bindImgs(root);
      bindMine(subs);
    }

    function subCard(s) {
      var p = s.payload || {}, prev = normItems(p)[0] || {};
      var imgs = (prev.images || []).slice(0, 4).map(function (u) { return imgTag(u, prev.title || prev.name); }).join("");
      var st = STATUS_LABEL[s.status] || s.status;
      var canAppeal = s.status === "changes_requested" || s.status === "withdrawn";
      var versions = (s.versions || []).map(function (v) {
        var votes = (v.votes || []).map(function (v2) {
          return '<li>' + esc(v2.reviewer) + ' · ' + (v2.decision === "approve" ? "通过" : "退回") + (v2.reason ? '：' + esc(v2.reason) : '') + '</li>';
        }).join("");
        return '<div class="curation-ver"><b>v' + esc(v.revision) + '</b> <span class="curation-time">' + esc(v.createdAt || "") + '</span>' +
          (votes ? '<ul class="curation-votes">' + votes + '</ul>' : '<p class="curation-muted">暂无审核意见</p>') + '<details><summary>查看此版本内容</summary><p class="curation-def">' + esc(filterPrompt((v.payload || {}).definition || (v.payload || {}).prompt || '')) + '</p></details></div>';
      }).join("");
      return '<article class="curation-card" data-sub="' + esc(s.id) + '">' +
        '<div class="curation-card-media">' + imgs + '</div>' +
        '<div class="curation-card-body">' +
          '<div class="curation-badges"><span class="curation-kind">' + esc(KIND_LABEL[s.kind] || s.kind) + '</span>' +
            '<span class="curation-status st-' + esc(s.status) + '">' + esc(st) + '</span>' +
            (isAdmin() ? '<span class="curation-rev">v' + esc(s.revision) + '</span>' : '') + '</div>' +
          '<h3 class="curation-card-title">' + esc(prev.title || prev.name || "未命名") + '</h3>' +
          '<p class="curation-card-desc">' + esc(prev.description || "") + '</p>' +
          '<div class="curation-actions">' +
            (s.topicId ? '<a href="' + esc(S.channelUrl("forum", { view: "topic", id: s.topicId })) + '">查看原帖</a>' : '') +
            '<button type="button" data-act="edit" data-id="' + esc(s.id) + '" data-kind="' + esc(s.kind) + '">编辑重提</button>' +
            (canAppeal ? '<button type="button" data-act="appeal" data-id="' + esc(s.id) + '">申诉</button>' : '') +
            '<button type="button" data-act="toggle" data-id="' + esc(s.id) + '">版本与意见</button>' +
          '</div>' +
          '<div class="curation-details" data-details="' + esc(s.id) + '" hidden>' +
            (versions || '<p class="curation-muted">暂无版本记录</p>') +
            (s.adminActions || []).map(function(a){return '<p>管理员复核：'+esc({approve:'收录',changes:'退回',reopen:'重开审核',withdraw:'下架'}[a.action] || a.action)+' · '+esc(a.reason)+'</p>';}).join('') +
            ((s.appeals && s.appeals.length) ? '<div class="curation-appeals">' + s.appeals.map(function (a) {
              return '<p>申诉：' + esc(a.reason) + ' · ' + esc({open:"待复核",resolved:"已处理"}[a.status] || a.status || "") + '</p>'; }).join("") + '</div>' : '') +
          '</div>' +
        '</div>' +
      '</article>';
    }

    function bindMine(subs) {
      root.onclick = function (e) {
        var t = e.target.closest("[data-act]"); if (!t) return;
        var act = t.getAttribute("data-act"), id = t.getAttribute("data-id");
        if (act === "toggle") {
          var d = root.querySelector('[data-details="' + id + '"]'); if (d) d.hidden = !d.hidden;
        } else if (act === "edit") {
          var s = subs.find(function (x) { return x.id === id; }); if (!s) return;
          var payload = s.payload || {}, items = normItems(payload);
          if (!items.length) items = [{ kind: s.kind }];
          
          location.href = S.channelUrl("forum", { view: "curation", tab: "share", kind: s.kind || "work", editId: id });
        } else if (act === "appeal") {
          appeal(id, t);
        }
      };
    }

    function appeal(id, btn) {
      var card=btn.closest('.curation-card-body');
      var box=card.querySelector('.curation-appeal-compose');
      if (box) { box.querySelector('textarea').focus(); return; }
      card.insertAdjacentHTML('beforeend','<div class="curation-appeal-compose"><label class="curation-field">申诉理由<textarea rows="3" maxlength="1000" placeholder="说明需要复核的地方"></textarea></label><p class="curation-err" aria-live="polite"></p><button type="button" class="curation-submit">提交申诉</button></div>');
      box=card.querySelector('.curation-appeal-compose');
      box.querySelector('button').onclick=function () {
        var send=this, reason=box.querySelector('textarea').value.trim(), error=box.querySelector('.curation-err');
        if (!guard(epoch,username)) return;
        if (!reason) { error.textContent='请填写申诉理由'; return; }
        send.disabled=true;
        api('/api/curation/submissions/'+encodeURIComponent(id)+'/appeal',{method:'POST',body:{reason:reason}}).then(function(){
          if (!guard(epoch,username)) return;
          S.toast && S.toast('申诉已提交，等待管理员复核');
          renderMine(root);
        }).catch(function(err){if(guard(epoch,username)){error.textContent='申诉失败：'+err.message;send.disabled=false;}});
      };
      box.querySelector('textarea').focus();
    }
  }

  /* ================= REVIEW (page 3) ================= */
  function renderReview(root) {
    var epoch = ++EPOCH, username = currentUser();
    if (!App.state.loggedIn) {
      root.innerHTML = '<div class="curation-page"><p class="curation-empty">请先登录。</p><button class="curation-submit" data-act="login">登录</button></div>';
      root.querySelector('[data-act="login"]').addEventListener("click", function () { S.openLoginModal("进入审核队列", function () { renderReview(root); }); });
      return;
    }
    root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("review") + '</nav><p class="curation-empty">加载中…</p></div>';
    load();

    function load() {
      api("/api/curation/review-queue", { method: "GET" }).then(function (res) {
        if (!guard(epoch, username)) return;
        draw(res || {});
      }).catch(function (err) {
        if (!guard(epoch, username)) return;
        root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("review") + '</nav><p class="curation-err">加载失败：' + esc(err && err.message) + '</p></div>';
      });
    }

    function draw(res) {
      var access = res.access || [], assignment = res.assignment;
      var head = '<nav class="curation-nav">' + navTabs("review") + '</nav>';
      if (!access.length) {
        root.innerHTML = '<div class="curation-page">' + head + '<p class="curation-empty">你还没有审核资格。获得同类收录，或由管理员指定后即可参与审核。</p></div>';
        return;
      }
      if (!assignment) {
        root.innerHTML = '<div class="curation-page">' + head + '<h1 class="curation-h1">审核队列</h1><p class="curation-note">可审核：' + access.map(function(k){return esc(KIND_LABEL[k]);}).join("、") + '</p><p class="curation-empty">暂无分配给你的审核任务，稍后再来。</p></div>';
        return;
      }
      var p = assignment.payload || {}, items = normItems(p), it = items[0] || {};
      var imgs = (it.images || []).map(function (u) { return imgTag(u, it.title || it.name); }).join("");
      root.innerHTML = '<div class="curation-page">' + head +
        '<h1 class="curation-h1">审核任务 · ' + esc(KIND_LABEL[assignment.kind] || assignment.kind) + ' v' + esc(assignment.revision) + '</h1>' +
        '<article class="curation-review">' +
          '<div class="curation-review-media">' + imgs + '</div>' +
          '<h2 class="curation-card-title">' + esc(it.title || it.name || p.title || "未命名") + '</h2>' +
          '<p class="curation-card-desc">' + esc(it.description || "") + '</p>' +
          '<div class="curation-def"><b>' + (assignment.kind === "work" ? "做法 / 提示词" : "定义") + '</b><p>' + esc(filterPrompt(it.prompt || it.definition || "")) + '</p></div>' +
          (assignment.topicId ? '<p><a href="' + esc(S.channelUrl("forum", { view: "topic", id: assignment.topicId })) + '">查看原帖</a></p>' : '') +
          '<label class="curation-field">退回理由（退回必填）<textarea data-act="reason" rows="2" maxlength="500"></textarea></label>' +
          '<p class="curation-err" data-err aria-live="polite"></p>' +
          '<div class="curation-actions">' +
            '<button type="button" class="curation-approve" data-act="approve">通过</button>' +
            '<button type="button" class="curation-changes" data-act="changes">退回</button>' +
          '</div>' +
        '</article></div>';
      bindImgs(root);
      var approving = false;
      root.querySelector('[data-act="approve"]').addEventListener("click", function () { vote("approve", this); });
      root.querySelector('[data-act="changes"]').addEventListener("click", function () { vote("changes", this); });

      function vote(decision, btn) {
        if (approving) return;
        var reasonEl = root.querySelector('[data-act="reason"]'), errEl = root.querySelector('[data-err]');
        var reason = (reasonEl && reasonEl.value || "").trim();
        if (errEl) errEl.textContent = "";
        if (decision === "changes" && !reason) { if (errEl) errEl.textContent = "退回必须填写理由。"; return; }
        approving = true;
        var both = root.querySelectorAll('.curation-actions button');
        both.forEach(function (b) { b.disabled = true; });
        api("/api/curation/votes", { method: "POST", body: { assignmentId: assignment.assignmentId, decision: decision, reason: reason } }).then(function (res) {
          if (!guard(epoch, username)) return;
          S.toast && S.toast(res.status === 'approved' ? '已收录' : res.status === 'changes_requested' ? '已退回补充' : '意见已记录，等待其他审核者');
          S.refreshFromServer && S.refreshFromServer();
          load();
        }).catch(function (err) {
          if (errEl) errEl.textContent = "提交失败：" + ((err && err.message) || "请重试");
          approving = false; both.forEach(function (b) { b.disabled = false; });
        });
      }
    }
  }

  /* ================= ADMIN (page 4) ================= */
  function renderAdmin(root) {
    var epoch = ++EPOCH, username = currentUser();
    if (!isAdmin()) {
      root.innerHTML = '<div class="curation-page"><p class="curation-empty">仅管理员可访问此页面。</p></div>';
      return;
    }
    root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("admin") + '</nav><p class="curation-empty">加载中…</p></div>';
    api("/api/curation/admin", { method: "GET" }).then(function (res) {
      if (!guard(epoch, username)) return;
      draw(res || {});
    }).catch(function (err) {
      if (!guard(epoch, username)) return;
      root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("admin") + '</nav><p class="curation-err">加载失败：' + esc(err && err.message) + '</p></div>';
    });

    function draw(res) {
      var users = res.users || [], access = res.access || [], pending = res.pending || [], appeals = (res.appeals || []).filter(function(a){return a.status === "open";});
      var events = res.adminActions || [];
      var userOpts = users.filter(function(u){return u.status==='active';}).map(function (u) {
        return '<label class="curation-user"><input type="checkbox" value="' + esc(u.username) + '"> ' + esc(u.displayName || u.username) + ' <small>' + esc({user:"普通用户",admin:"管理员",operator:"运营",reviewer:"运营"}[u.role] || "用户") + '</small></label>';
      }).join("");
      var accessRows = access.map(function (a) {
        return '<li class="curation-access-row">' + esc(a.username) + ' · ' + esc(KIND_LABEL[a.kind] || a.kind) +
          (a.paused ? ' <b class="curation-status st-withdrawn">已暂停</b>' : ' <b class="curation-status st-approved">有效</b>') +
          ' <span class="curation-muted">'+esc({accepted:'同类收录获得',grant:'管理员指定',admin:'管理员补位',paused:'暂停'}[a.source] || '')+'</span>' +
          (a.reason ? ' <span class="curation-muted">' + esc(a.reason) + '</span>' : '') + '</li>';
      }).join("");
      var pendingRows = pending.map(function (p) {
        var it = normItems(p.payload)[0] || {};
        return '<li class="curation-pending-row">' + esc(KIND_LABEL[p.kind] || p.kind) + ' · v' + esc(p.revision) +
          ' · ' + esc(p.owner) + ' · ' + esc(STATUS_LABEL[p.status] || p.status) +
          '<div class="curation-muted">' + esc(it.title || it.name || "") + '</div></li>';
      }).join("");
      var appealRows = appeals.map(function (a) {
        var material=a.payload || {};
        return '<li class="curation-appeal" data-sub="' + esc(a.submission_id) + '">' +
          '<div><b>' + esc(a.author_username) + '</b> · ' + esc({open:"待复核",resolved:"已处理"}[a.status] || a.status) + '</div>' +
          '<h3>'+esc(material.name || material.title || '')+'</h3>' + (material.images || []).slice(0,3).map(function(u){return imgTag(u,'投稿预览');}).join('') + '<p class="curation-def">'+esc(filterPrompt(material.definition || material.prompt || ''))+'</p><p>原理由：' + esc(a.reason) + '</p>' +
          '<label class="curation-field">处理理由<textarea data-act="areason" rows="2" maxlength="500"></textarea></label>' +
          '<div class="curation-actions">' +
            '<button type="button" data-act="review" data-sub="' + esc(a.submission_id) + '" data-decision="approve">通过</button>' +
            '<button type="button" data-act="review" data-sub="' + esc(a.submission_id) + '" data-decision="changes">退回</button>' +
            '<button type="button" data-act="review" data-sub="' + esc(a.submission_id) + '" data-decision="reopen">重开</button>' +
            '<button type="button" data-act="review" data-sub="' + esc(a.submission_id) + '" data-decision="withdraw">下架</button>' +
          '</div></li>';
      }).join("");

      root.innerHTML = '<div class="curation-page"><nav class="curation-nav">' + navTabs("admin") + '</nav>' +
        '<h1 class="curation-h1">收录管理</h1>' +
        '<section class="curation-admin-sec">' +
          '<h2>批量授予 / 暂停 / 恢复</h2>' +
          '<input class="curation-search" data-act="user-search" placeholder="搜索用户…" aria-label="搜索用户">' +
          '<div class="curation-userlist" data-userlist>' + userOpts + '</div>' +
          '<div class="curation-kinds">' + ["work", "style", "layout"].map(function (k) {
            return '<label><input type="checkbox" value="' + k + '" data-kind> ' + KIND_LABEL[k] + '</label>';
          }).join("") + '</div>' +
          '<label class="curation-field">理由<input data-act="access-reason" maxlength="200"></label>' +
          '<p class="curation-err" data-err aria-live="polite"></p>' +
          '<div class="curation-actions">' +
            '<button type="button" data-act="access" data-action="grant">授予</button>' +
            '<button type="button" data-act="access" data-action="pause">暂停</button>' +
            '<button type="button" data-act="access" data-action="resume">恢复</button>' +
          '</div>' +
          '<ul class="curation-access-list">' + (accessRows || '<li class="curation-muted">暂无资格记录</li>') + '</ul>' +
        '</section>' +
        '<section class="curation-admin-sec">' +
          '<h2>申诉复核</h2>' + (appealRows || '<p class="curation-empty">暂无申诉</p>') +
        '</section>' +
        '<section class="curation-admin-sec">' +
          '<h2>待处理预览（只读）</h2>' +
          '<ul class="curation-pending-list">' + (pendingRows || '<li class="curation-muted">暂无待处理</li>') + '</ul>' +
          (events.length ? '<h3>最近审核记录</h3><ul class="curation-events">' + events.map(function (ev) {
            return '<li>' + esc({approve:'收录',changes:'退回',reopen:'重开',withdraw:'下架'}[ev.action] || ev.action || '') + ' · ' + esc(ev.admin_username || '') + ' · ' + esc(ev.reason || '') + ' · ' + esc(ev.createdAt || ev.created_at || "") + '</li>';
          }).join("") + '</ul>' : '') +
        '</section></div>';
      bindImgs(root);
      bindAdmin();
    }

    function bindAdmin() {
      var search = root.querySelector('[data-act="user-search"]');
      if (search) search.addEventListener("input", function () {
        var q = search.value.trim().toLowerCase();
        root.querySelectorAll(".curation-user").forEach(function (el) {
          var name = (el.textContent || "").toLowerCase();
          el.style.display = !q || name.indexOf(q) >= 0 ? "" : "none";
        });
      });
      root.onclick = function (e) {
        var t = e.target.closest("[data-act]"); if (!t) return;
        var act = t.getAttribute("data-act");
        if (act === "access") doAccess(t.getAttribute("data-action"), t);
        else if (act === "review") doReview(t);
      };
    }

    function doAccess(action, btn) {
      var errEl = root.querySelector('[data-err]'); if (errEl) errEl.textContent = "";
      var usernames = Array.prototype.map.call(root.querySelectorAll("[data-userlist] input[type=checkbox]:checked"), function (c) { return c.value; });
      var kinds = Array.prototype.map.call(root.querySelectorAll("input[data-kind]:checked"), function (c) { return c.value; });
      var reason = (root.querySelector('[data-act="access-reason"]') || {}).value || "";
      if (!usernames.length) { if (errEl) errEl.textContent = "请选择用户。"; return; }
      if (!kinds.length) { if (errEl) errEl.textContent = "请选择类型。"; return; }
      btn.disabled = true;
      api("/api/curation/access", { method: "POST", body: { usernames: usernames, kinds: kinds, action: action, reason: reason } }).then(function () {
        if (!guard(epoch, username)) return;
        renderAdmin(root);
      }).catch(function (err) {
        if (errEl) errEl.textContent = "操作失败：" + ((err && err.message) || "请重试");
        btn.disabled = false;
      });
    }

    function doReview(btn) {
      var li = btn.closest(".curation-appeal");
      var reason = ((li && li.querySelector('[data-act="areason"]')) || {}).value || "";
      var sub = btn.getAttribute("data-sub"), decision = btn.getAttribute("data-decision");
      var buttons = (li || root).querySelectorAll('[data-act="review"]');
      buttons.forEach(function (b) { b.disabled = true; });
      api("/api/curation/admin/review", { method: "POST", body: { submissionId: sub, action: decision, reason: reason } }).then(function () {
        if (!guard(epoch, username)) return;
        renderAdmin(root);
      }).catch(function (err) {
        alert("处理失败：" + ((err && err.message) || "请重试"));
        buttons.forEach(function (b) { b.disabled = false; });
      });
    }
  }

  function navTabs(active) {
    var tabs = [["share", "分享投稿"], ["mine", "我的投稿"], ["review", "审核队列"]];
    var html = tabs.map(function (t) {
      return '<a class="curation-nav-' + (t[0] === active ? "on" : "") + '" href="' + esc(S.channelUrl("forum", { view: "curation", tab: t[0] })) + '">' + t[1] + '</a>';
    });
    html=html.join("");
    if (isAdmin()) html += ('<a class="curation-nav-admin' + (active === "admin" ? " on" : "") + '" href="' + esc(S.channelUrl("forum", { view: "curation", tab: "admin" })) + '">管理</a>');
    return '<a href="' + esc(S.channelUrl("forum")) + '">← 论坛</a>' + (Array.isArray(html) ? html.join("") : html);
  }

  /* ================= TOPIC PANEL ================= */
  function topicPanelHtml(topic) {
    var subs = (topic && topic.submissions) || [];
    var rd = topic && topic.resourceDiscussion;
    var head = '<div class="curation-topic-panel">' +
      '<h2 class="curation-topic-h2">收录预览</h2>' +
      (rd ? '<p class="curation-rd">' + esc(rd.label || "资源详情与论坛共用同一组评论。") + '</p>' : '');
    if (!subs.length) return rd ? '<p class="curation-rd">资源讨论 · 此处与资源详情共用评论</p>' : '';
    var cards = subs.map(function (s) {
      var p = s.preview || {}, imgs = (p.images || []).map(function (u) { return imgTag(u, p.title || p.name); }).join("");
      var approved = s.status === "approved";
      var links = '';
      if (approved) {
        if (s.kind === "work") {
          links += '<a href="' + esc(S.channelUrl("main", { view: "work", id: s.targetId })) + '">查看作品</a>';
          links += '<a href="' + esc(S.channelUrl("studio", { fork: s.targetId })) + '">复刻作品</a>';
        } else if (s.kind === "style" || s.kind === "layout") {
          links += '<a href="' + esc(S.channelUrl("studio", s.kind === "style" ? {style:s.targetId} : {layout:s.targetId})) + '">在创作台使用</a>';
        }
      }
      var votes = (s.reviews || []).map(function (v) {
        return '<li>v'+esc(v.revision || s.revision)+' · ' + esc(v.reviewer || "") + ' · ' + (v.decision === "approve" ? "通过" : "退回") +
          (v.reason ? '：' + esc(v.reason) : '') + '</li>';
      }).join("");
      return '<article class="curation-topic-card" data-sub="' + esc(s.id) + '">' +
        '<div class="curation-topic-media">' + imgs + '</div>' +
        '<h3>' + esc(p.name || p.title || "未命名") + '</h3>' +
        '<span class="curation-kind">' + esc(KIND_LABEL[s.kind] || s.kind) + '</span> ' +
        '<span class="curation-status st-' + esc(s.status) + '">' + esc(STATUS_LABEL[s.status] || s.status) + ' · v' + esc(s.revision) + '</span>' +
        (p.description || p.notes ? '<p class="curation-card-desc">' + esc(p.description || p.notes) + '</p>' : '') +
        (votes ? '<ul class="curation-votes">' + votes + '</ul>' : '') +
        (links ? '<div class="curation-actions">' + links + '</div>' : '') +
      '</article>';
    }).join("");
    return head + cards + '</div>';
  }
  function bindTopicPanel(root, topic) {
    if (!root) return;
    bindImgs(root);
    // Status/links are static anchors already rendered; no further async mutation needed.
    return;
  }

  /* ================= RENDER DISPATCH ================= */
  function render(root, tab) {
    if (!root) return;
    var params = (tab && typeof tab === "object") ? tab : Object.fromEntries(new URLSearchParams(location.search));
    root.onclick=null;
    if (!App.state.loggedIn) {
      ++EPOCH;
      var returnUrl=location.href;
      root.innerHTML='<div class="curation-page"><a href="'+esc(S.channelUrl("forum"))+'">← 论坛</a><h1>登录后参与共创</h1><button class="curation-submit" data-login>登录 / 注册</button></div>';
      root.querySelector('[data-login]').onclick=function(){S.openLoginModal('登录后参与共创',function(){location.href=returnUrl;});};
      return;
    }
    if (tab === "mine") return renderMine(root);
    if (tab === "review") return renderReview(root);
    if (tab === "admin") return renderAdmin(root);
    return renderShare(root, params);
  }

  window.HandrawCuration = {
    render: render,
    topicPanelHtml: topicPanelHtml,
    bindTopicPanel: bindTopicPanel,
    shareModelFrom: shareModelFrom,
    _epoch: function () { return EPOCH; }
  };
})();
