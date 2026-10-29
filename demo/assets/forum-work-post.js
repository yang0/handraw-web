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
    for (const id of Array.isArray(ids) ? ids : (ids ? [ids] : [])) {
      if (!id || acc.ids.has(id)) continue;
      const item = resourceMapGet(resourceMap, id);
      if (!item || !item.id) continue;
      const kind = item.kind;
      if (!['style','layout'].includes(kind)) continue;
      if (kindHint && kind !== kindHint) continue;
      acc.ids.add(id);
      acc.list.push({
        kind,
        id: String(item.id),
        label: S.resourceLabel(item), image:safeImageUrl(item.image || '')
      });
    }
  }

  function fromTopic(topic, worksArray, resourceMap, topicUnlocked) {
    if (!topic || typeof topic !== "object") return null;
    const works = Array.isArray(worksArray) ? worksArray : [];

    // ---- 判定实际关联作品 ----
    let work = null;
    if (topic.workId) {
      work = works.find((w) => w && w.id === topic.workId) || null;
    }
    if (!work && topic.sharedCard && topic.sharedCard.kind === "work" && topic.sharedCard.id) {
      work = works.find((w) => w && w.id === topic.sharedCard.id) || null;
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
    // Images alone never qualify; a work must expose an actual reproduction path.
    if (work && (work.reproducible === false || (!work.promptMasked && !String(work.prompt || '').trim()))) work = null;

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
        prompt = String(work.prompt || "").trim();
      }
    } else if (!recipeLocked) {
      prompt = recipePrompt || recipeTheme;
    }
    // 锁定/隐藏时不回退到 masked 前缀或伪造
    if (locked) prompt = "";

    // ---- 复刻链接 ----
    let forkUrl = "";
    let canFork = false;
    if (work && !locked && prompt) {
      forkUrl = S.channelUrl("studio", { entry: ['graphic-text','pure-image','series'].includes(work.mode || 'graphic-text') ? 'quick' : 'canvas', fork: work.id });
      canFork = !!(forkUrl && safeHref(forkUrl));
    } else if (!work && hasRecipe && !recipeLocked && topic.id) {
      forkUrl = S.channelUrl("studio", { entry: ['graphic-text','pure-image','series'].includes(recipe.mode || 'graphic-text') ? 'quick' : 'canvas', forkTopic: topic.id });
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
      forkUrl,
      canFork,
      unavailableText
    };
  }

  function assetHref(asset) {
    if (!asset || (asset.kind !== "style" && asset.kind !== "layout") || !asset.id) return "";
    return S.channelUrl("forum", { view: "resource", kind: asset.kind, id: asset.id });
  }

  function renderGallery(images) {
    if (!images || !images.length) return "";
    const first = images[0];
    const firstUrl = typeof first === "string" ? first : first.url;
    const firstTag = typeof first === "object" ? first.tag : "";
    const main = safeImageUrl(firstUrl);
    if (!main) return "";
    const thumbs = images.length > 1
      ? `<div class="fwp-thumbs" role="tablist">${images.map((img, i) => {
          const u = typeof img === "string" ? img : img.url;
          const t = typeof img === "object" ? img.tag : "";
          return `<button type="button" class="fwp-thumb${i === 0 ? " is-active" : ""}" data-fwp-src="${esc(safeImageUrl(u))}" role="tab" aria-selected="${i===0}" aria-label="查看第${i + 1}张图"${t ? ` data-fwp-tag="${esc(String(t))}"` : ""}><img data-hw-src="${esc(safeImageUrl(u))}" alt="" loading="lazy"></button>`;
        }).join("")}</div>`
      : "";
    return `<div class="fwp-gallery">
  <div class="fwp-gallery-stage" data-fwp-stage>
    <img class="fwp-main" data-fwp-main data-hw-src="${esc(main)}" alt="${esc(firstTag || "作品图片")}" loading="lazy">
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
      forkHtml = `<a class="fwp-fork" href="${esc(safeHref(model.forkUrl))}">一键复刻</a>`;
    } else if (!model.locked) {
      forkHtml = `<button type="button" class="fwp-fork is-disabled" disabled>暂不可复刻</button>`;
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

  function renderAssets(assets, model) {
    if (!assets || !assets.length) return "";
    const items = assets.map((a) => {
      const href = safeHref(assetHref(a));
      const label = esc(String(a.label || (a.kind === "layout" ? "图型参考" : "画风参考")));
      const inner = `${a.image ? `<img data-hw-src="${esc(safeImageUrl(a.image))}" alt="${label}" loading="lazy">` : ''}<span class="fwp-asset-kind">${esc(a.kind === "layout" ? "图型" : "画风")}</span>
    <span class="fwp-asset-name">${label}</span>
    <span class="fwp-asset-id">${esc(a.id)}</span>`;
      return href
        ? `<a class="fwp-asset" href="${esc(href)}">${inner}</a>`
        : `<span class="fwp-asset">${inner}</span>`;
    }).join("");
    const listLinks = model.source === 'work' ? ['style','layout'].filter(kind=>assets.some(a=>a.kind===kind)).map(kind=>`<a href="${esc(S.channelUrl('forum',{view:'related',kind:'work',id:model.sourceId,tab:kind==='style'?'styles':'layouts'}))}">全部${kind==='style'?'画风':'图型'} →</a>`).join(' ') : '';
    return `<div class="fwp-assets">
  <h3 class="fwp-assets-title">使用的画风与图型</h3>
  <div class="fwp-asset-links">${listLinks}</div>
  <div class="fwp-asset-list">${items}</div>
</div>`;
  }

  function render(model) {
    if (!model || typeof model !== "object") return "";
    const title = esc(String(model.title || "作品帖"));
    const gallery = renderGallery(model.images);
    const prompt = renderPrompt(model);
    const notes = renderNotes(model.notes);
    const assets = renderAssets(model.assets,model);
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

    if (stage && main && thumbs.length) {
      thumbs.forEach((btn) => {
        btn.addEventListener("click", () => {
          const src = btn.getAttribute("data-fwp-src");
          if (!src || !safeImageUrl(src)) return;
          thumbs.forEach((b) => b.classList.toggle("is-active", b === btn));
          main.setAttribute("src", src);
          main.setAttribute('data-hw-src',src);
          thumbs.forEach(b=>b.setAttribute('aria-selected',String(b===btn)));
          const tag = btn.getAttribute("data-fwp-tag");
          main.setAttribute("alt", tag || "作品图片");
          if (window.HandrawImageLoader && window.HandrawImageLoader.scan) {
            window.HandrawImageLoader.scan(stage);
          }
        });
      });
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

  window.HandrawForumWork = { fromTopic, render, bind };
})();
