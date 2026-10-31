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
    ["kind", "name", "title", "description", "notes", "definition", "prompt", "images", "styles", "layout", "ratio", "price", "unlockCost", "color", "tone", "mode", "mood"].forEach(function (k) {
      if (payload[k] != null) one[k] = payload[k];
    });
    if (one.kind) one.images = Array.isArray(one.images) ? one.images.slice() : (one.images ? [one.images] : []);
    return one.kind ? [one] : [];
  }

  /* ================= SHARE (page 1) ================= */
  function renderShare(root, params) {
    var epoch = ++EPOCH, username = currentUser();
    var kindDefault = (params.kind === "style" || params.kind === "layout") ? params.kind : "work";
    var editId = params.editId || ""; // revise target
    var draftId = params.draft || "";
    var formKey = uuid();
    var model = {
      title: "", text: "", items: [],
      requestId: uuid()
    };
    var resourceCache = {};

    function resourceLabel(code, kind) {
      if (!code) return "";
      var m = resourceCache[code];
      if (m) return m;
      var map = App.resourceMap;
      var r = map && typeof map.get === "function" ? map.get(code) : null;
      return r ? { name: r.name || code, id: r.id || code, kind: r.kind, image: r.image } : { name: code, id: code, kind: kind, image: "" };
    }

    function itemHtml(it, idx) {
      var kind = it.kind || kindDefault;
      var canUseStyle = kind === "work";
      var stylesHtml = "";
      if (kind === "style" || (canUseStyle && it.styles)) {
        var st = it.styles || (kind === "style" ? (it.code ? [it.code] : []) : []);
        stylesHtml = '';
        st.forEach(function (c) { stylesHtml += resourceChip(c, idx, "style"); formStylesCache(idx)[c] = resourceLabel(c, "style"); });
      }
      var layoutHtml = "";
      if (kind === "layout" || canUseStyle) {
        var lay = it.layout || (kind === "layout" ? (it.code || "") : "");
        if (lay) layoutHtml = resourceChip(lay, idx, "layout");
      }
      return (
        '<fieldset class="curation-item" data-idx="' + idx + '">' +
          '<legend>投稿项 ' + (idx + 1) + '</legend>' +
          '<label class="curation-field">类型' +
            '<select data-act="kind" data-idx="' + idx + '">' +
              ["work", "style", "layout"].map(function (k) {
                return '<option value="' + k + '"' + (k === kind ? " selected" : "") + '>' + KIND_LABEL[k] + '</option>';
              }).join("") +
            '</select></label>' +
          (kind !== 'work' ? '<label class="curation-field">名称<input data-act="name" data-idx="' + idx + '" value="' + esc(it.name || "") + '" maxlength="80" placeholder="如：江南淡墨"></label>' : '') +
          (kind === 'work' ? '<label class="curation-field">标题<input data-act="title" data-idx="' + idx + '" value="' + esc(it.title || "") + '" maxlength="120"></label>' : '') +
          '<label class="curation-field">说明<textarea data-act="description" data-idx="' + idx + '" rows="2" maxlength="600">' + esc(it.description || "") + '</textarea></label>' +
          '<label class="curation-field">' + (kind === "work" ? "做法 / 提示词" : "定义 / 使用说明") +
            '<textarea data-act="prompt" data-idx="' + idx + '" rows="3" maxlength="6000">' + esc(kind === "work" ? (it.prompt || "") : (it.definition || it.prompt || "")) + '</textarea></label>' +
          '<div class="curation-imgs" data-imgs="' + idx + '">' + (it.images || []).map(function (src, i) {
            return '<figure class="curation-thumb-wrap">' + imgTag(src, "预览") +
              '<button type="button" class="curation-x" data-act="delimg" data-idx="' + idx + '" data-i="' + i + '" aria-label="删除图片">×</button></figure>';
          }).join("") + '</div>' +
          '<label class="curation-field">预览图（可多选）<input type="file" accept="image/*" multiple data-act="file" data-idx="' + idx + '"></label>' +
          (canUseStyle ?
            '<div class="curation-pick">' +
              '<div class="curation-pick-row"><span>画风</span><button type="button" data-act="pick" data-idx="' + idx + '" data-target="style">选择画风</button><span class="curation-chips" data-chip="style" data-idx="' + idx + '">' + stylesHtml + '</span></div>' +
              '<div class="curation-pick-row"><span>图型</span><button type="button" data-act="pick" data-idx="' + idx + '" data-target="layout">选择图型</button><span class="curation-chips" data-chip="layout" data-idx="' + idx + '">' + layoutHtml + '</span></div>' +
            '</div>' : '') +
          '<button type="button" class="curation-x-item" data-act="delitem" data-idx="' + idx + '">删除此项</button>' +
        '</fieldset>'
      );
    }

    var stylesCache = {};
    function formStylesCache(idx) { return stylesCache[idx] || (stylesCache[idx] = {}); }

    function resourceChip(code, idx, target) {
      var r = resourceLabel(code, target === "layout" ? "layout" : "style");
      var src = r.image && typeof r.image === "string" ? r.image : "";
      return '<span class="curation-chip" data-code="' + esc(code) + '">' + imgTag(src, r.name) + '<b>' + esc(code) + '</b> ' + esc(r.name) + '</span>';
    }

    function draw() {
      var nav = ['share', 'mine', 'review'].map(function (tab) {
        return '<a class="curation-nav-' + (tab === "share" ? "on" : "") + '" href="' + esc(S.channelUrl("forum", { view: "curation", tab: tab })) + '">' +
          ({ share: "投稿", mine: "我的投稿", review: "审核队列" })[tab] + '</a>';
      });
      if (isAdmin()) nav.push('<a class="curation-nav-admin" href="' + esc(S.channelUrl("forum", { view: "curation", tab: "admin" })) + '">管理</a>');

      var itemsHtml = model.items.length ? model.items.map(itemHtml).join("") :
        '<p class="curation-empty">还没有投稿项，请至少添加一项。</p>';

      root.innerHTML =
        '<div class="curation-page">' +
          '<nav class="curation-nav">' + nav.join("") + '</nav>' +
          '<h1 class="curation-h1">' + (editId ? "编辑重提 · " + esc(KIND_LABEL[kindDefault] || "") : "投稿并申请收录") + '</h1>' +
          '<p class="curation-hint">图片先存入你的私有上传库，点击发布才公开。</p>' +
          (editId ? '<p class="curation-note">已收录项编辑后保留原帖；新版本审核期间旧版本继续使用。</p>' : '') +
          '<div class="curation-form">' +
            '<label class="curation-field">论坛标题<input data-act="ftitle" value="' + esc(model.title) + '" maxlength="120" placeholder="给这次分享起个标题"></label>' +
            '<label class="curation-field">公开说明<textarea data-act="ftext" rows="3" maxlength="1200" placeholder="介绍你的作品或画风（资源定义请写在下面各项）">' + esc(model.text) + '</textarea></label>' +
            '<div data-items>' + itemsHtml + '</div>' +
            (editId ? '' : '<button type="button" class="curation-add" data-act="additem">＋ 添加投稿项</button>') +
            '<p class="curation-err" data-err aria-live="polite"></p>' +
            '<button type="button" class="curation-submit" data-act="submit"' + (editId ? ' data-edit="1"' : '') + '>' + (editId ? "提交新版本" : "发布到论坛并申请收录") + '</button>' +
          '</div>' +
        '</div>';
      if (editId) {
        root.querySelector('[data-act="ftitle"]').closest('label').hidden=true;
        root.querySelector('[data-act="ftext"]').closest('label').hidden=true;
        root.querySelectorAll('[data-act="kind"]').forEach(function(el){el.disabled=true;});
      }
      bindImgs(root);
      bindShare();
    }

    function onInput(e) {
      var t = e.target, act = t.getAttribute && t.getAttribute("data-act");
      if (!act) return;
      if (act === "ftitle") model.title = t.value;
      else if (act === "ftext") model.text = t.value;
      else if (act === "name" || act === "title" || act === "description" || act === "prompt") {
        var i = +t.getAttribute("data-idx"), it = model.items[i]; if (!it) return;
        if (act === "prompt") { if (it.kind === "work" || !it.kind) it.prompt = t.value; else it.definition = t.value; if (!it.kind) it.prompt = t.value; }
        else { it[act] = t.value; if (act === "description" && it.kind === "work") it.notes=t.value; }
        model.requestId = uuid(); // content changed -> new request key
      }
    }

    function onKindChange(e) {
      var idx = +e.target.getAttribute("data-idx"), it = model.items[idx];
      if (!it) return;
      it.kind = e.target.value;
      if (it.kind !== "work") { delete it.styles; delete it.layout; }
      model.requestId = uuid();
      draw();
    }

    function onFiles(e) {
      var idx = +e.target.getAttribute("data-idx"), it = model.items[idx];
      var files = e.target.files; if (!it || !files || !files.length) return;
      if (files.length + (it.images || []).length > 9) { alert('每项最多9张图片'); return; }
      if (Array.from(files).some(function(f){return f.size>15*1024*1024;})) { alert('单张图片请小于15MB'); return; }
      var btn = root.querySelector('[data-act="submit"]'); if (btn) btn.disabled = true;
      var errEl = root.querySelector('[data-err]');
      var jobs = Array.prototype.map.call(files, function (f) {
        return readFile(f).then(function (d) { return uploadDataUrl(d, f.name); })
          .then(function (url) { return url; });
      });
      Promise.all(jobs).then(function (urls) {
        if (!guard(epoch, username)) return;
        urls.forEach(function (u) { if (u) { it.images = it.images || []; it.images.push(u); } });
        model.requestId = uuid();
        draw();
      }).catch(function (err) {
        if (errEl) errEl.textContent = "图片上传失败：" + (err && err.message || "请重试");
      }).then(function () {
        if (btn) btn.disabled = false; e.target.value = "";
      });
    }

    function onClick(e) {
      var t = e.target.closest("[data-act]"); if (!t) return;
      var act = t.getAttribute("data-act");
      var idx = +t.getAttribute("data-idx");
      if (act === "additem") {
        if (editId || model.items.length >= 20) return;
        model.items.push({ kind: kindDefault, images: [] }); model.requestId = uuid(); draw();
      } else if (act === "delitem") {
        model.items.splice(idx, 1); model.requestId = uuid(); draw();
      } else if (act === "delimg") {
        var it = model.items[idx]; if (!it) return;
        it.images.splice(+t.getAttribute("data-i"), 1); model.requestId = uuid(); draw();
      } else if (act === "pick") {
        pickResource(idx, t.getAttribute("data-target"));
      } else if (act === "submit") {
        submit(t, t.getAttribute("data-edit") === "1");
      }
    }

    function pickResource(idx, target) {
      var it = model.items[idx]; if (!it) return;
      var cur = target === "layout" ? it.layout : (it.styles && it.styles[0]);
      if (typeof S.openAssetPickerModal !== "function") return;
      S.openAssetPickerModal({ kind: target === "layout" ? "layout" : "style", currentId: cur || "", onSelect: function (asset) {
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
      } });
    }

    function submit(btn, isEdit) {
      var errEl = root.querySelector('[data-err]');
      if (errEl) errEl.textContent = "";
      if (!isEdit && !model.title.trim()) { if (errEl) errEl.textContent = "请填写论坛标题。"; return; }
      if (!model.items.length) { if (errEl) errEl.textContent = "请至少添加一项投稿项。"; return; }
      var items = model.items.map(function (it) {
        var kind = it.kind || kindDefault;
        var item = Object.assign({}, it, { kind: kind, name: it.name || "", title: it.title || "", images: (it.images || []).slice() });
        if (kind === "work") {
          item.description = it.description || "";
          item.prompt = it.prompt || "";
          item.ratio = it.ratio || "3:4";
          if (it.styles && it.styles[0]) item.styles = [it.styles[0]];
          if (it.layout) item.layout = it.layout;
        } else {
          item.description = it.description || "";
          item.definition = it.definition || it.prompt || "";
        }
        return item;
      });
      var body = { title: model.title.trim(), text: model.text || "", requestId: model.requestId, items: items };
      var url, method = "POST";
      var isWork = items.length === 1 && String(items[0].kind || "").toLowerCase() === "work";

      if (isEdit && editId) {
        url = "/api/curation/submissions/" + encodeURIComponent(editId) + "/revise";
        body = { payload: items[0] };
      } else if (isWork) {
        // Works publish immediately (D-02): they must not enter the review queue.
        var work = items[0];
        url = "/api/works";
        body = {
          title: model.title.trim(),
          prompt: work.prompt || "",
          notes: model.text || "",
          images: (work.images || []).slice(),
          styles: work.styles ? [work.styles[0]] : [],
          layout: work.layout || "",
          ratio: work.ratio || "3:4",
          requestId: model.requestId
        };
      } else {
        url = "/api/curation/submissions";
      }

      btn.disabled = true;
      var prev = btn.textContent; btn.textContent = "提交中…";
      api(url, { method: method, body: body }).then(function (res) {
        if (!guard(epoch, username)) return;
        if (isWork) {
          // The work is already live; send the author to its detail page.
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

    function bindShare() {
      var form = root.querySelector(".curation-form"); if (!form) return;
      form.addEventListener("input", onInput);
      form.addEventListener("change", function (e) {
        var act = e.target.getAttribute("data-act");
        if (act === "kind") onKindChange(e);
        else if (act === "file") onFiles(e);
      });
      form.addEventListener("click", onClick);
    }

    // Draw skeleton, then load draft (owner only) before final draw.
    model.items = [{ kind: kindDefault, images: [] }];
    var preload = editId ? api("/api/curation/mine").then(function(res) {
      if (!guard(epoch, username)) return;
      var found=(res.submissions || []).find(function(it){return it.id===editId;});
      if (!found) throw new Error("投稿不存在");
      model.items=normItems(found.payload); model.title=found.payload.title || found.payload.name || "";
    }) : draftId ? api("/api/curation/drafts/" + encodeURIComponent(draftId), { method: "GET" }).then(function (res) {
      if (!guard(epoch, username)) return;
      var p = res && res.payload; if (!p) return;
      var its = normItems(p);
      if (its.length) {
        model.items = its.map(function (it) {
          it.images = Array.isArray(it.images) ? it.images.slice() : (it.images ? [it.images] : []);
          if (it.images.length) resourceCache["__draft__"] = true;
          return it;
        });
      }
      if (p.title) model.title = p.title;
      if (p.text) model.text = p.text;
    }).catch(function () { if (guard(epoch, username)) { var errEl = root.querySelector('[data-err]'); if (errEl) errEl.textContent = "草稿加载失败。"; } }) : Promise.resolve();

    draw();
    preload.then(function () { if (guard(epoch, username)) draw(); }).catch(function(err) {
      if (guard(epoch,username)) root.querySelector('[data-err]').textContent='加载投稿失败：'+err.message;
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
          (votes ? '<ul class="curation-votes">' + votes + '</ul>' : '<p class="curation-muted">暂无审核意见</p>') + '<details><summary>查看此版本内容</summary><p class="curation-def">' + esc((v.payload || {}).definition || (v.payload || {}).prompt || '') + '</p></details></div>';
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
          '<div class="curation-def"><b>' + (assignment.kind === "work" ? "做法 / 提示词" : "定义") + '</b><p>' + esc(it.prompt || it.definition || "") + '</p></div>' +
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
          '<h3>'+esc(material.name || material.title || '')+'</h3>' + (material.images || []).slice(0,3).map(function(u){return imgTag(u,'投稿预览');}).join('') + '<p class="curation-def">'+esc(material.definition || material.prompt || '')+'</p><p>原理由：' + esc(a.reason) + '</p>' +
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
          links += '<a href="' + esc(S.channelUrl("main", { view: "asset", kind: s.kind, id: s.targetId })) + '">去查看资源</a>';
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
    var params = Object.fromEntries(new URLSearchParams(location.search));
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
    _epoch: function () { return EPOCH; }
  };
})();
