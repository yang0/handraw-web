/* Forum work posts: shared images, prompt, reproduction and author commentary.
 * 纯逻辑 fromTopic 不依赖 DOM；render 只产出转义后的 HTML 字符串。
 * bind 只绑定相册与复制，绝不触发生成或修改 App。
 */
(function () {
  "use strict";

  const S = window.HANDRAW_SHARED;
  const esc = S.esc;

  const IMG_RE = /^(?:[a-z][a-z0-9+.-]*:)?\/\//i; // protocol-relative or absolute scheme
  const SAFE_IMG = /^(https?:\/\/|\/(?!\/))/i;
  const SAFE_HREF = /^(https?:\/\/|\/(?!\/))/i;

  function safeImageUrl(u) {
    const s = typeof u === "string" ? u.trim() : "";
    if (!s || IMG_RE.test(s) && !/^https?:\/\//i.test(s)) return "";
    return SAFE_IMG.test(s) && !s.startsWith('/\\') ? s : "";
  }

  function safeHref(u) {
    const s = typeof u === "string" ? u.trim() : "";
    return s && SAFE_HREF.test(s) && !s.startsWith('/\\') ? s : "";
  }

  function normImages(list) {
    const out = [];
    const seen = new Set();
    for (const item of Array.isArray(list) ? list : []) {
      const url = safeImageUrl(typeof item === "string" ? item : item && item.url);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      const tag = typeof item === "object" && item ? String(item.tag || "") : "";
      out.push(tag ? { url, tag } : url);
    }
    return out;
  }

  function plainNotes(text) {
    const raw = typeof text === "string" ? text : "";
    if (!raw) return "";
    if (typeof DOMParser !== "undefined") {
      try {
        const doc = new DOMParser().parseFromString(raw, "text/html");
        return (doc.body && doc.body.textContent || "").replace(/\r\n?/g, "\n").trim();
      } catch (e) { /* fall through to raw */ }
    }
    return raw.replace(/\r\n?/g, "\n").trim();
  }

  function resourceMapGet(resourceMap, id) {
    if (!id || !resourceMap) return null;
    try {
      if (typeof resourceMap.get === "function") return resourceMap.get(id) || null;
      if (typeof resourceMap === "object" && resourceMap[id]) return resourceMap[id];
    } catch (e) { return null; }
    return null;
  }

  function collectAssets(ids, kindHint, resourceMap, acc) {
    for (const raw of Array.isArray(ids) ? ids : (ids ? [ids] : [])) {
      const candidate = typeof raw === "object" && raw ? (raw.code || raw.id || "") : raw;
      const id = String(candidate || "").trim().toUpperCase().replace(/^#/, "");
      if (!/^(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+$/.test(id) || acc.ids.has(id)) continue;
      const item = resourceMapGet(resourceMap, id);
      // Standalone detail may load before the catalog; preserve real recorded IDs.
      const kind = item?.kind || kindHint || (/^(?:SC|IG|SB|PO|IP|EC|LAY|USR-L)-/.test(id) ? "layout" : "style");
      if (!["style", "layout"].includes(kind) || (kindHint && kindHint !== kind)) continue;
      acc.ids.add(id);
      acc.list.push({
        kind, id, label: item ? S.resourceLabel(item) : id,
        image: safeImageUrl(item?.image || "")
      });
    }
  }

  function mapImageAssets(work, resourceMap) {
    if (!work || !Array.isArray(work.imageAssets)) return [];
    return work.imageAssets.map((snapshot) => {
      if (!snapshot || typeof snapshot !== "object") return null;
      const url = safeImageUrl(snapshot.url);
      if (!url) return null;
      const acc = { ids: new Set(), list: [] };
      collectAssets(snapshot.styles || [], "style", resourceMap, acc);
      collectAssets(snapshot.layout || [], "layout", resourceMap, acc);
      return {
        url,
        scope: ["image", "group", "missing"].includes(snapshot.scope) ? snapshot.scope : "missing",
        assets: acc.list
      };
    }).filter(Boolean);
  }

  function formatWorkPrompt(work, topic) {
    if (!work || typeof work !== "object") return "";
    const rawSubject = typeof work.subject === "string" ? work.subject.trim() : "";
    const rawPrompt = typeof work.prompt === "string" ? work.prompt.trim() : "";
    let subjectText = rawSubject || rawPrompt;
    if (!subjectText) return "";
    const clean = subjectText.replace(/^主题[：:]\s*/, "");
    return S && typeof S.filterDisplayPrompt === "function" ? S.filterDisplayPrompt(clean) : clean;
  }

  function fromTopic(topic, worksArray, resourceMap, topicUnlocked) {
    if (!topic || typeof topic !== "object") return null;
    const works = Array.isArray(worksArray) ? worksArray : [];

    // ---- 判定实际关联作品 ----
    let work = null;
    if (topic.workId) {
      work = works.find((w) => w && w.id === topic.workId) || null;
    }
    if (!work && topic.work && topic.work.id) {
      work = topic.work;
    }
    if (!work && topic.sharedCard && topic.sharedCard.kind === "work" && topic.sharedCard.id) {
      work = works.find((w) => w && w.id === topic.sharedCard.id) || null;
    }
    if (work && !work.subject) {
      const stateWorks = (typeof App !== "undefined" && App.state && Array.isArray(App.state.works) && App.state.works) ||
                         (S && S.App && S.App.state && Array.isArray(S.App.state.works) && S.App.state.works) || [];
      const match = stateWorks.find((w) => w && w.id === work.id);
      if (match && match.subject) {
        work = Object.assign({}, work, { subject: match.subject });
      }
    }

    // ---- 判定真实配方（非仅 recipe 对象存在）----
    const recipe = topic.recipe && typeof topic.recipe === "object" ? topic.recipe : null;
    const recipePrompt = recipe ? String(recipe.prompt || "").trim() : "";
    const recipeTheme = recipe ? String(recipe.theme || "").trim() : "";
    let recipeImages = [];
    if (recipe) {
      recipeImages = normImages(topic.images || recipe.images || recipe.imageUrls || []);
      if (!recipeImages.length && recipe.image) recipeImages = normImages([recipe.image]);
    }
    const hasRecipe = !!(recipe && (recipePrompt || recipeTheme));
    // Work media and reproduction are independent: a generated work remains
    // viewable and author-editable even when its prompt is confidential or
    // intentionally omitted. The "做同款" action remains gated by prompt.
    if (!work && !hasRecipe) return null;

    // ---- 标题：优先作品标题，其次帖子标题 ----
    const title = String(
      (work && work.title) || topic.title || "作品帖"
    );

    const notes = plainNotes(topic.summary || topic.body || "");

    // ---- 锁定状态 ----
    const recipeLocked = !!(topic.price > 0 && !topicUnlocked);
    const workLocked = !!(work && work.promptMasked);

    // ---- 图片 ----
    let images = normImages(work ? (work.images || []) : []);
    let locked = workLocked;
    if (!work && hasRecipe) {
      images = recipeImages;
      locked = recipeLocked;
    } else if (work) {
      locked = workLocked;
    }

    // ---- 提示词 ----
    let prompt = "";
    if (work) {
      if (!workLocked && !work.promptMasked) {
        prompt = formatWorkPrompt(work, topic);
      }
    } else if (!recipeLocked) {
      const rawRecipePrompt = recipePrompt || recipeTheme;
      prompt = S && typeof S.filterDisplayPrompt === "function" ? S.filterDisplayPrompt(rawRecipePrompt) : rawRecipePrompt;
    }
    // 锁定/隐藏时不回退到 masked 前缀或伪造
    if (locked) prompt = "";

    // ---- 复刻链接 ----
    // Only the canvas-only modes belong on the canvas. ``work.mode`` also holds
    // a picture ratio for some rows ("3:4"), and treating that as a mode sent
    // 做同款 to the empty canvas instead of the form that made the picture.
    const CANVAS_MODES = ['canvas', 'advanced', 'workflow'];
    const forkEntryFor = (mode) => (CANVAS_MODES.includes(String(mode || '').trim()) ? 'canvas' : 'quick');
    let forkUrl = "";
    let canFork = false;
    if (work && !locked && prompt) {
      forkUrl = S.channelUrl("studio", { entry: forkEntryFor(work.mode), fork: work.id });
      canFork = !!(forkUrl && safeHref(forkUrl));
    } else if (!work && hasRecipe && !recipeLocked && topic.id) {
      forkUrl = S.channelUrl("studio", { entry: forkEntryFor(recipe.mode), forkTopic: topic.id });
      canFork = !!(forkUrl && safeHref(forkUrl));
    }

    // ---- 资源附件：实际已发布样式/布局 ----
    const acc = { ids: new Set(), list: [] };
    if (work) {
      collectAssets(work.styles || [], "style", resourceMap, acc);
      collectAssets(work.layout || [], "layout", resourceMap, acc);
    }
    if (recipe) {
      collectAssets(recipe.style1, "style", resourceMap, acc);
      collectAssets(recipe.style2, "style", resourceMap, acc);
      collectAssets(recipe.layout, "layout", resourceMap, acc);
    }
    collectAssets(topic.styles || [], "style", resourceMap, acc);
    collectAssets(topic.layout || [], "layout", resourceMap, acc);
    const additional = topic.additionalRealAttachments;
    if (Array.isArray(additional)) {
      for (const a of additional) {
        if (!a) continue;
        const aid = typeof a === "string" ? a : (a.id || "");
        const kindHint = typeof a === "object" && (a.kind === "style" || a.kind === "layout") ? a.kind : "";
        collectAssets(aid, kindHint, resourceMap, acc);
      }
    }

    // ---- 不可用文案 ----
    let unavailableText = "";
    if (locked) {
      unavailableText = workLocked && work
        ? "解锁后查看提示词并复刻"
        : "解锁后查看提示词";
    } else if (!images.length) {
      unavailableText = "暂无可展示的图片";
    } else if (!prompt) {
      unavailableText = "作者暂未公开提示词";
    }

    return {
      source: work ? "work" : "recipe",
      sourceId: work ? work.id : topic.id,
      title,
      images,
      prompt,
      locked,
      notes,
      assets: acc.list,
      imageAssets: mapImageAssets(work, resourceMap),
      forkUrl,
      canFork,
      unavailableText,
      batchWorks: (work && work.batchWorks) || null,
      coverUrl: work && safeImageUrl(work.coverUrl || "") || ""
    };
  }

  function assetHref(asset) {
    if (!asset || (asset.kind !== "style" && asset.kind !== "layout") || !asset.id) return "";
    return `/t/${encodeURIComponent(asset.id)}`;
  }

  function renderGallery(images, model) {
    const batchWorks = model && Array.isArray(model.batchWorks) && model.batchWorks.length > 1 ? model.batchWorks : null;
    const currentImg = (model && model.coverUrl && (images || []).some(img => (typeof img === "string" ? img : img && img.url) === model.coverUrl) && model.coverUrl)
      || (images && images[0]) || (batchWorks && (batchWorks.find((b) => b.isCurrent) || batchWorks[0]).imageUrl) || "";
    const mainUrl = typeof currentImg === "string" ? currentImg : (currentImg && currentImg.url);
    const main = safeImageUrl(mainUrl);
    if (!main) return "";

    let thumbs = "";
    if (batchWorks) {
      thumbs = `<div class="fwp-thumbs" role="tablist" aria-label="同批次作品图片">${batchWorks.map((item, i) => {
        const u = safeImageUrl(item.imageUrl);
        const isActive = Boolean(item.isCurrent);
        return `<button type="button" class="fwp-thumb${isActive ? " is-active" : ""}" data-fwp-topic="${esc(item.topicId)}" data-fwp-work="${esc(item.workId)}" data-fwp-src="${esc(u)}" role="tab" aria-selected="${isActive}" aria-label="切换至同批第 ${item.index || (i + 1)}/${item.total || batchWorks.length} 张图"><img data-hw-src="${esc(u)}" alt="" loading="lazy"><span class="fwp-thumb-badge" style="position:absolute;bottom:2px;right:2px;background:rgba(0,0,0,0.6);color:#fff;font-size:10px;padding:0 4px;border-radius:3px;">${item.index || (i + 1)}/${item.total || batchWorks.length}</span></button>`;
      }).join("")}</div>`;
    } else if (images && images.length > 1) {
      thumbs = `<div class="fwp-thumbs" role="tablist">${images.map((img, i) => {
        const u = typeof img === "string" ? img : img.url;
        const t = typeof img === "object" ? img.tag : "";
        return `<button type="button" class="fwp-thumb${safeImageUrl(u) === main ? " is-active" : ""}" data-fwp-src="${esc(safeImageUrl(u))}" role="tab" aria-selected="${safeImageUrl(u) === main}" aria-label="查看第${i + 1}张图"${t ? ` data-fwp-tag="${esc(String(t))}"` : ""}><img data-hw-src="${esc(safeImageUrl(u))}" alt="" loading="lazy"></button>`;
      }).join("")}</div>`;
    }

    return `<div class="fwp-gallery">
  <div class="fwp-gallery-stage" data-fwp-stage style="position:relative;">
    <img class="fwp-main" data-fwp-main data-hw-src="${esc(main)}" alt="${esc(model?.title || "作品图片")}" loading="lazy" style="cursor:zoom-in;">
    <div class="fwp-gallery-overlay-bar" style="position:absolute;bottom:10px;right:10px;display:flex;gap:8px;z-index:2;">
      ${model && model.canEditCover && model.source === "work" && (model.images || []).length > 1
        ? `<button type="button" class="btn btn-sm fwp-set-cover-btn" data-fwp-set-cover title="将正在查看的图片设为作品封面">设为封面</button>`
        : ""}
      <a class="btn btn-sm btn-primary fwp-download-btn" href="${esc(main)}" download="handraw-work.webp" target="_blank" rel="noopener noreferrer" style="font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,0.25);">⬇️ 下载原图</a>
    </div>
  </div>
  ${thumbs}
</div>`;
  }

  function renderPrompt(model) {
    const t = "生图提示词";
    let body;
    if (model.locked) {
      body = `<p class="fwp-locked">${esc(model.unavailableText || "解锁后查看提示词")}</p>`;
    } else if (!model.prompt) {
      body = `<p class="fwp-missing">${esc(model.unavailableText || "作者暂未公开提示词")}</p>`;
    } else {
      body = `<pre class="fwp-prompt-text">${esc(model.prompt)}</pre>`;
    }
    const copyBtn = (!model.locked && model.prompt)
      ? `<button type="button" class="fwp-copy" data-fwp-copy>复制</button>`
      : "";
    let forkHtml = "";
    if (model.canFork && safeHref(model.forkUrl)) {
      forkHtml = `<a class="fwp-fork" href="${esc(safeHref(model.forkUrl))}">做同款</a>`;
    } else if (!model.locked) {
      forkHtml = `<button type="button" class="fwp-fork is-disabled" disabled>暂不可做同款</button>`;
    }
    return `<div class="fwp-prompt">
  <div class="fwp-prompt-head">
    <h3 class="fwp-prompt-title">${t}</h3>
    ${copyBtn}${forkHtml}
  </div>
  ${body}
</div>`;
  }

  function renderNotes(notes) {
    if (!notes) return "";
    return `<div class="fwp-notes">
  <h3 class="fwp-notes-title">作者点评</h3>
  <p class="fwp-notes-body">${esc(notes).replace(/\n/g, "<br>")}</p>
</div>`;
  }

  function renderAssetContents(model, currentUrl) {
    const snapshot = (model.imageAssets || []).find((item) => item.url === currentUrl);
    // A snapshot belongs to the selected media only. Never borrow the first
    // image's style or layout for a different image in the same V3 work.
    const assets = snapshot ? snapshot.assets : (model.assets || []);
    const scope = snapshot ? snapshot.scope : "work";
    const multiple = Array.isArray(model.images) && model.images.length > 1;
    const note = scope === "image"
      ? "当前图片的生成记录"
      : scope === "group"
        ? "该图片所属生成步骤的共用参数（未记录更细的逐图差异）"
        : scope === "missing"
          ? "当前图片的生成记录缺少画风与图型信息"
          : multiple
            ? "仅保存了整组作品的参数，无法确认每张图片的独立配置"
            : "";
    const items = assets.map((a) => {
      const href = safeHref(assetHref(a));
      const label = esc(String(a.label || (a.kind === "layout" ? "图型参考" : "画风参考")));
      const inner = `${a.image ? `<img data-hw-src="${esc(safeImageUrl(a.image))}" alt="${label}" loading="lazy">` : ""}<span class="fwp-asset-kind">${esc(a.kind === "layout" ? "图型" : "画风")}</span>
    <span class="fwp-asset-name">${label}</span>
    <span class="fwp-asset-id">${esc(a.id)}</span>`;
      return href
        ? `<a class="fwp-asset" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
        : `<span class="fwp-asset">${inner}</span>`;
    }).join("");
    const missing = ["style", "layout"]
      .filter((kind) => !assets.some((a) => a.kind === kind))
      .map((kind) => `<p class="fwp-missing">${kind === "style" ? "画风" : "图型"}：${scope === "missing" ? "当前图片未记录" : "没有可展示的信息"}</p>`)
      .join("");
    return `<h3 class="fwp-assets-title">${multiple ? "当前图片的画风与图型" : "使用的画风与图型"}</h3>
  ${note ? `<p class="fwp-asset-scope-note" style="font-size:12px;color:var(--ink-muted);margin:0 0 10px;">${esc(note)}</p>` : ""}
  <div class="fwp-asset-list">${items}</div>
  ${missing}`;
  }

  function renderAssets(model, currentUrl) {
    if (model.source !== "work" && !(model.assets || []).length) return "";
    return `<div class="fwp-assets" data-fwp-assets>${renderAssetContents(model, currentUrl)}</div>`;
  }

  function render(model) {
    if (!model || typeof model !== "object") return "";
    const title = esc(String(model.title || "作品帖"));
    const gallery = renderGallery(model.images, model);
    const prompt = renderPrompt(model);
    const notes = renderNotes(model.notes);
    const cover = model.coverUrl && model.images.some((img) =>
      (typeof img === "string" ? img : img && img.url) === model.coverUrl) ? model.coverUrl : "";
    const first = model.images[0];
    const initialUrl = cover || (typeof first === "string" ? first : first && first.url) || "";
    const assets = renderAssets(model, initialUrl);
    return `<section class="fwp" aria-label="作品详情">
  ${gallery}
  ${prompt}
  ${notes}
  ${assets}
</section>`;
  }

  function toast(kind) {
    try {
      if (S.toast) S.toast(kind);
    } catch (e) { /* ignore */ }
  }

  function bind(root, model) {
    if (!root || !root.querySelector || !model) return;
    const scope = root.querySelector(".fwp") || root;
    const stage = scope.querySelector("[data-fwp-stage]");
    const main = scope.querySelector("[data-fwp-main]");
    const thumbs = scope.querySelectorAll(".fwp-thumb");
    const coverButton = scope.querySelector("[data-fwp-set-cover]");
    const refreshCoverButton = () => {
      if (!coverButton || !main) return;
      const current = main.getAttribute("data-hw-src") || main.getAttribute("src") || "";
      const selected = current === model.coverUrl;
      coverButton.disabled = selected;
      coverButton.textContent = selected ? "当前封面" : "设为封面";
      coverButton.setAttribute("aria-label", selected ? "当前图片已是封面" : "将当前图片设为封面");
    };
    if (coverButton && model.canEditCover && model.source === "work") {
      refreshCoverButton();
      coverButton.addEventListener("click", async () => {
        const url = main && (main.getAttribute("data-hw-src") || main.getAttribute("src"));
        if (!url || !safeImageUrl(url) || coverButton.disabled) return;
        coverButton.disabled = true;
        try {
          const response = await S.apiJson(`/api/works/${encodeURIComponent(model.sourceId)}/cover`, {
            method: "POST", body: { imageUrl: url }
          });
          if (!response || response.ok === false) throw new Error(response && response.error || "更新失败");
          model.coverUrl = response.coverUrl || url;
          toast("已更新封面，广场及个人主页会显示这张图片");
          refreshCoverButton();
        } catch (error) {
          coverButton.disabled = false;
          toast("设置封面失败：" + (error.message || error));
        }
      });
    }

    if (stage && main) {
      main.addEventListener("click", () => {
        const currentSrc = main.getAttribute("src") || main.getAttribute("data-hw-src");
        if (currentSrc && typeof S.openModal === "function") {
          S.openModal({
            title: `🖼️ ${esc(model.title || "作品大图")}`,
            html: `
              <div class="hw-modal-lightbox-container" style="text-align:center;">
                <a href="${esc(currentSrc)}" target="_blank" rel="noopener noreferrer" title="点击新窗口打开" style="display:block;max-width:100%;">
                  <img class="hw-modal-lightbox-img" src="${esc(currentSrc)}" alt="${esc(model.title || "作品原图")}" style="max-height:75vh;border-radius:8px;" />
                </a>
                <div style="display:flex;gap:10px;align-items:center;margin-top:14px;justify-content:center;flex-wrap:wrap;">
                  <a class="btn btn-sm btn-primary" href="${esc(currentSrc)}" download="handraw-work.webp" target="_blank" rel="noopener noreferrer">⬇️ 下载原图</a>
                  <a class="btn btn-sm" href="${esc(currentSrc)}" target="_blank" rel="noopener noreferrer">↗️ 新窗口查看</a>
                </div>
              </div>
            `
          });
        }
      });

      if (thumbs.length) {
        thumbs.forEach((btn) => {
          btn.addEventListener("click", () => {
            const targetTid = btn.getAttribute("data-fwp-topic");
            if (targetTid && targetTid !== model.sourceId) {
              if (typeof window.HANDRAW_FORUM_OPEN_TOPIC === "function") {
                window.HANDRAW_FORUM_OPEN_TOPIC(targetTid, 0);
              } else {
                window.location.href = S.channelUrl("forum", { view: "topic", id: targetTid });
              }
              return;
            }

            const src = btn.getAttribute("data-fwp-src");
            if (!src || !safeImageUrl(src)) return;
            thumbs.forEach((b) => b.classList.toggle("is-active", b === btn));
            main.setAttribute("src", src);
            main.setAttribute("data-hw-src", src);
            thumbs.forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
            const tag = btn.getAttribute("data-fwp-tag");
            if (tag) main.setAttribute("alt", tag);
            const dlBtn = stage.querySelector(".fwp-download-btn");
            if (dlBtn) dlBtn.setAttribute("href", src);
            const assetsPanel = scope.querySelector("[data-fwp-assets]");
            if (assetsPanel) assetsPanel.innerHTML = renderAssetContents(model, src);
            refreshCoverButton();
            if (window.HandrawImageLoader && window.HandrawImageLoader.scan) {
              window.HandrawImageLoader.scan(stage);
            }
          });
        });
      }
    }

    const copyBtn = scope.querySelector("[data-fwp-copy]");
    if (copyBtn && !model.locked && model.prompt) {
      copyBtn.addEventListener("click", () => {
        const text = String(model.prompt || "");
        if (!text) return;
        const clip = typeof navigator !== 'undefined' && navigator.clipboard;
        if (clip && typeof clip.writeText === "function") {
          let p;
          try { p = clip.writeText(text); } catch (e) { toast("复制失败，请手动选择"); return; }
          if (p && typeof p.then === "function") {
            p.then(() => toast("提示词已复制")).catch(() => toast("复制失败，请手动选择"));
          } else {
            toast("提示词已复制");
          }
        } else {
          toast("当前环境无法复制，请手动选择");
        }
      });
    }
  }

  window.HandrawForumWork = { fromTopic, render, bind, formatWorkPrompt };
})();
