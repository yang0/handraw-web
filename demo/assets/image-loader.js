/* Responsive image loader modelled on how Pinterest streams a feed.
 *
 * Design goals, in priority order:
 *   1. never show a broken/empty frame — reserve space and show a placeholder
 *      shimmer until real pixels arrive;
 *   2. show the first screen fast — high concurrency, near-viewport prefetch,
 *      and an optional inline low-quality placeholder that paints immediately;
 *   3. keep the server healthy — bound concurrency, retry a dropped request,
 *      and back off instead of stalling the whole queue.
 *
 * Templates use data-hw-src to avoid an eager original request. Native images
 * are adopted automatically; data-hw-width is a fallback CSS size hint.
 * Optional attributes:
 *   data-hw-ratio  "w/h" aspect ratio used to reserve layout space
 *   data-hw-lqip   tiny inline data URI painted before the real image
 *
 * The previous implementation allowed two requests with a 600ms gap between
 * starts, so a 30-image grid needed ~18s even on a fast connection, and it set
 * no src at all until its turn, which is what produced visible broken frames.
 */
(function () {
  "use strict";

  // Browsers already cap per-host connections around 6 on HTTP/1.1. Staying at
  // that ceiling keeps the queue moving without starving other resources.
  const MAX_ACTIVE = 6;
  const START_INTERVAL = 24; // One or two image starts per frame without a visible cascade.
  const SKELETON_DELAY = 120; // Fast local/cache hits should never flash a shimmer.
  const RETRY_DELAY = 4_000;
  const MAX_RETRIES = 2;
  const PREFETCH_MARGIN = "600px 0px";
  const PREVIEW_MAX_ACTIVE = 3;
  const PREVIEW_WIDTH = 48;
  const WIDTHS = [48, 96, 160, 240, 320, 480, 640, 960, 1280, 1600, 1920, 2560];
  const states = new WeakMap();
  const cancellations = new WeakMap();
  const managedImages = new Set();

  const pending = new Set();
  const failures = new Set();
  const inFlight = new WeakSet();
  const watched = new WeakSet();
  // Avoid replaying a skeleton animation for images previously decoded on this page.
  const decodedSources = new Set();
  const visible = new WeakSet();
  const retries = new WeakMap();
  // Progressive cards are opt-in. A bounded secondary queue loads tiny local
  // previews only; unsupported remote URLs go straight from color to full image.
  const previewPending = new Set();
  const previewQueued = new WeakSet();
  const previewRequests = new Map();
  const previewCache = new Map();
  let previewActive = 0;
  let active = 0;
  let lastStart = -START_INTERVAL;
  let retryAt = 0;
  let timer = null;
  let retryNotice = null;

  function widthBucket(width) {
    return WIDTHS.find(value => value >= width) || WIDTHS[WIDTHS.length - 1];
  }

  function localMedia(raw) {
    let source = String(raw || '').trim();
    const origin = window.location?.origin;
    if (origin && source.startsWith(origin + '/')) source = source.slice(origin.length);
    // These are first-party public mirrors, never an arbitrary URL proxy.
    source = source.replace(/^https:\/\/(?:img|static)\.handraw-style\.com(?=\/images\/)/i, '');
    return /^\/(?:images|uploads|generated|avatars|assets)\//.test(source) ? source : '';
  }

  function variantUrl(raw, width) {
    const local = localMedia(raw);
    if (!local || /\.(?:svg|gif)(?:[?#]|$)/i.test(local)) return raw;
    const [path, fragment = ''] = local.split('#');
    const clean = path.replace(/([?&])w=[^&]*&?/g, '$1').replace(/[?&]$/, '');
    const base = window.HandrawImageConfig?.mediaOrigin || '';
    return base + clean + (clean.includes('?') ? '&' : '?') + 'w=' + widthBucket(width) + (fragment ? '#' + fragment : '');
  }

  /** Build a derivative URL without ever changing the original source receipt. */
  function resolveSource(image) {
    const raw = (image.dataset.hwSrc || "").trim();
    if (!raw) return "";
    if (image.dataset.hwOriginal === 'true' || !localMedia(raw)) return raw;
    const width = autoWidth(image);
    if (!width) return '';
    const state = states.get(image);
    // A smaller box can reuse already decoded pixels; expanding it upgrades.
    const desired = widthBucket(width);
    if (state?.raw === raw && state.width >= desired) return state.url;
    return variantUrl(raw, desired);
  }

  /** Estimate a request width bucket from the rendered box. */
  function autoWidth(image) {
    const rect = image.getBoundingClientRect?.();
    let cssWidth = rect?.width || image.clientWidth || Number(image.dataset.hwWidth) || image.parentElement?.clientWidth || 0;
    const cssHeight = rect?.height || image.clientHeight || 0;
    if (cssWidth > 0 && cssHeight > 0 && image.naturalWidth > 0 && image.naturalHeight > 0) {
      const fit = window.getComputedStyle?.(image)?.objectFit;
      const widthForHeight = cssHeight * image.naturalWidth / image.naturalHeight;
      if (fit === 'contain') cssWidth = Math.min(cssWidth, widthForHeight);
      if (fit === 'cover') cssWidth = Math.max(cssWidth, widthForHeight);
    }
    if (!cssWidth) return 0;
    return Math.ceil(cssWidth * Math.min(3, Math.max(1, window.devicePixelRatio || 1)));
  }

  function nearby(image) {
    if (!image.isConnected || !image.getClientRects || !image.getClientRects().length) return false;
    const rect = image.getBoundingClientRect();
    return rect.bottom >= -600 && rect.top <= window.innerHeight + 600 && rect.right >= -200 && rect.left <= window.innerWidth + 200;
  }


  const PLACEHOLDER_PALETTE = [
    "#e5ddd2", "#dde7e5", "#e7e4ed", "#eadfd8",
    "#e3e9d9", "#dae4ed", "#f0e1d9", "#e6e2d7"
  ];

  function progressiveBox(image) {
    const box = image && image.parentElement;
    return box && box.classList?.contains("hw-progressive-media") ? box : null;
  }

  /** Deterministic muted placeholder colors prevent a uniform grey feed. */
  function preparePlaceholder(image) {
    const box = progressiveBox(image);
    if (!box || box.dataset.hwPlaceholderReady) return;
    const key = image.dataset.hwSrc || "";
    let hash = 0;
    for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
    box.style.setProperty("--hw-placeholder-color",
      PLACEHOLDER_PALETTE[(hash >>> 0) % PLACEHOLDER_PALETTE.length]);
    box.dataset.hwPlaceholderReady = "true";
  }

  /** The preview and the final image share the same aspect-ratio container. */
  function updateProgressiveRatio(image, width, height) {
    const box = progressiveBox(image);
    if (!box || box.dataset.hwRefineRatio !== "true" || !(width > 0 && height > 0)) return;
    const ratio = width / height;
    const existing = String(box.style.aspectRatio || "").split("/").map(Number);
    const previous = existing.length === 2 && existing[0] > 0 && existing[1] > 0
      ? existing[0] / existing[1] : Number(box.style.aspectRatio);
    if (previous > 0 && Math.abs(previous / ratio - 1) < 0.005) return;
    box.style.aspectRatio = width + " / " + height;
  }

  /** Never guess a query-string thumbnail contract for third-party images. */
  function previewSource(image) {
    const source = String(image.dataset.hwSrc || "").trim();
    if (!localMedia(source) || /\.(?:svg|gif)(?:[?#]|$)/i.test(source)) return "";
    return variantUrl(source, PREVIEW_WIDTH);
  }

  function revealPreview(image, source, dimensions) {
    const box = progressiveBox(image);
    if (!box || image.classList.contains("hw-img-ready") || previewSource(image) !== source) return;
    updateProgressiveRatio(image, dimensions.width, dimensions.height);
    box.style.setProperty("--hw-preview-image", "url(" + JSON.stringify(source) + ")");
    box.classList.add("hw-preview-ready");
  }

  function trimPreviewCache() {
    // Only metadata is retained. Browser HTTP cache owns the actual 48px bytes.
    if (previewCache.size > 400) previewCache.delete(previewCache.keys().next().value);
  }

  function queuePreview(image) {
    const box = progressiveBox(image);
    if (!box || image.classList.contains("hw-img-ready") ||
        (image.complete && image.naturalWidth > 0) ||
        decodedSources.has(resolveSource(image))) return;
    preparePlaceholder(image);
    const source = previewSource(image);
    if (!source) return;
    const cached = previewCache.get(source);
    if (cached) { revealPreview(image, source, cached); return; }
    if (previewQueued.has(image) || typeof Image === "undefined") return;
    previewQueued.add(image);
    previewPending.add(image);
    pumpPreviews();
  }

  function pumpPreviews() {
    while (previewActive < PREVIEW_MAX_ACTIVE && previewPending.size) {
      const image = previewPending.values().next().value;
      previewPending.delete(image);
      if (!image.isConnected || image.classList.contains("hw-img-ready")) continue;
      const source = previewSource(image);
      if (!source) continue;
      const cached = previewCache.get(source);
      if (cached) { revealPreview(image, source, cached); continue; }
      if (previewRequests.has(source)) {
        previewRequests.get(source).push(image);
        continue;
      }
      previewActive++;
      previewRequests.set(source, [image]);
      const preview = new Image();
      preview.decoding = "async";
      preview.onload = () => {
        const dims = { width: preview.naturalWidth, height: preview.naturalHeight };
        const interested = previewRequests.get(source) || [];
        previewRequests.delete(source);
        previewActive = Math.max(0, previewActive - 1);
        if (dims.width > 0 && dims.height > 0) {
          previewCache.set(source, dims);
          trimPreviewCache();
          for (const candidate of interested) revealPreview(candidate, source, dims);
        }
        pumpPreviews();
      };
      preview.onerror = () => {
        previewRequests.delete(source);
        previewActive = Math.max(0, previewActive - 1);
        // Tiny preview failure is cosmetic, not an image delivery failure.
        pumpPreviews();
      };
      preview.src = source;
    }
  }

  function showFailures() {
    if (retryNotice || !failures.size || !document.body) return;
    retryNotice = document.createElement("div");
    retryNotice.setAttribute("role", "status");
    retryNotice.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:10000;padding:12px 16px;background:#fffdf9;color:#252722;border:1px solid #ded8cf;border-radius:6px;font:14px system-ui;box-shadow:0 3px 14px #0001";
    const text = document.createElement("span");
    text.textContent = "部分图片暂未显示。";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "重试图片";
    button.disabled = true;
    button.style.cssText = "margin-left:8px;background:transparent;border:0;color:#a94028;cursor:pointer;font:inherit";
    const enable = () => {
      const wait = retryAt - Date.now();
      if (wait > 0) setTimeout(enable, wait);
      else {
        button.disabled = false;
        button.textContent = "重试图片";
      }
    };
    enable();
    button.addEventListener("click", () => {
      if (Date.now() < retryAt) return;
      retryNotice.remove();
      retryNotice = null;
      for (const image of failures) {
        if (image.isConnected && nearby(image)) {
          delete image.dataset.hwFailed;
          image.classList.remove("hw-img-failed");
          retries.delete(image);
          pending.add(image);
        }
      }
      failures.clear();
      pump();
    });
    retryNotice.append(text, button);
    document.body.append(retryNotice);
  }

  function pump() {
    clearTimeout(timer);
    while (active < MAX_ACTIVE && pending.size) {
      const wait = Math.max(START_INTERVAL - (Date.now() - lastStart), retryAt - Date.now());
      if (wait > 0) {
        timer = setTimeout(pump, wait);
        return;
      }
      let image = null;
      for (const candidate of pending) {
        if (!candidate.isConnected) { pending.delete(candidate); continue; }
        // IO tells us visibility without a forced getBoundingClientRect per image.
        if (observer ? visible.has(candidate) : nearby(candidate)) {
          image = candidate;
          break;
        }
      }
      if (!image) {
        if (!observer) pending.clear();
        return;
      }
      pending.delete(image);
      if (inFlight.has(image) || image.dataset.hwFailed) continue;
      const source = resolveSource(image);
      if (!source || image.dataset.hwLoaded === source) continue;
      start(image, source);
    }
  }

  function start(image, source) {
    active += 1;
    inFlight.add(image);
    lastStart = Date.now();
    image.dataset.hwManaged = "true";
    image.decoding = "async";
    // Never let the browser defer the image we already scheduled.
    image.loading = "eager";
    const raw = image.dataset.hwSrc;
    const width = /[?&]w=(\d+)/.exec(source);
    states.set(image, {raw, url:source, width:width ? Number(width[1]) : 0});

    let finished = false;
    let skeletonTimer = null;
    const done = (failed, obsolete = false) => {
      if (finished) return;
      finished = true;
      if (skeletonTimer) clearTimeout(skeletonTimer);
      image.removeEventListener("load", loaded);
      image.removeEventListener("error", errored);
      inFlight.delete(image);
      cancellations.delete(image);
      active = Math.max(0, active - 1);
      if (obsolete || image.dataset.hwSrc !== raw || !image.isConnected) {
        if (image.isConnected) pending.add(image);
        pump();
        return;
      }
      if (failed) {
        const tries = (retries.get(image) || 0) + 1;
        retries.set(image, tries);
        if (tries < MAX_RETRIES) {
          // One dropped request must not surface as a broken frame: drop it
          // back into the queue and let the normal path re-issue the request.
          setTimeout(() => {
            if (image.isConnected && !image.dataset.hwFailed) {
              delete image.dataset.hwLoaded;
              pending.add(image);
            }
            pump();
          }, 250 * tries);
        } else {
          image.dataset.hwFailed = "true";
          markFailed(image);
          failures.add(image);
          retryAt = Math.max(retryAt, Date.now() + RETRY_DELAY);
          showFailures();
        }
      } else {
        failures.delete(image);
        retries.delete(image);
        image.dataset.hwLoaded = source;
        updateProgressiveRatio(image, image.naturalWidth, image.naturalHeight);
        decodedSources.add(source);
        if (decodedSources.size > 1500) decodedSources.delete(decodedSources.values().next().value);
        image.classList.add("hw-img-ready");
        image.classList.remove("hw-img-loading");
        // A container may have expanded while this request was in flight.
        if (resolveSource(image) !== source) pending.add(image);
      }
      pump();
    };
    const loaded = () => done(false);
    const errored = () => done(true);
    image.addEventListener("load", loaded);
    image.addEventListener("error", errored);
    cancellations.set(image, () => done(false, true));

    if (!decodedSources.has(source)) {
      // Defer the animated placeholder until we know this is not a fast
      // memory/disk-cache hit; the immediate flash was very noticeable.
      skeletonTimer = setTimeout(() => {
        if (!finished && image.isConnected) markLoading(image);
      }, SKELETON_DELAY);
    } else image.classList.remove("hw-img-loading");
    // A cached image can be complete immediately; avoid waiting for another event.
    if (image.getAttribute?.('src') === source && image.complete && image.naturalWidth > 0) done(false);
    else {
      // Reassign even an identical failed URL; otherwise no new load/error
      // event fires and an explicit retry would occupy a queue slot forever.
      image.src = source;
      if (image.complete && image.naturalWidth > 0) done(false);
    }
  }

  function markLoading(image) {
    if (!image.dataset.hwLqipApplied && image.dataset.hwLqip) {
      image.style.backgroundImage = `url("${image.dataset.hwLqip}")`;
      image.style.backgroundSize = "cover";
      image.style.backgroundPosition = "center";
      image.dataset.hwLqipApplied = "true";
    }
    if (!progressiveBox(image)) image.classList.add("hw-img-loading");
  }

  function markFailed(image) {
    image.classList.remove("hw-img-loading");
    image.classList.add("hw-img-failed");
  }

  function applyRatio(image) {
    const ratio = (image.dataset.hwRatio || "").trim();
    if (!ratio) return;
    const [w, h] = ratio.split(/[/:x]/).map((n) => parseFloat(n));
    if (!w || !h) return;
    image.style.aspectRatio = `${w} / ${h}`;
  }

  function enqueue(image) {
    if (!image.isConnected || inFlight.has(image) || image.dataset.hwFailed) return;
    if (image.dataset.hwLoaded && image.dataset.hwLoaded === resolveSource(image)) return;
    queuePreview(image);
    pending.add(image);
  }

  function scan(root = document) {
    if (!root) return;
    const register = (image) => {
      if (!image || !image.isConnected) return;
      if (!image.dataset.hwSrc) {
        const source = image.getAttribute?.('src');
        if (!source) return;
        image.dataset.hwSrc = source;
      }
      if (!watched.has(image)) {
        watched.add(image);
        managedImages.add(image);
        resizeObserver?.observe(image);
        applyRatio(image);
        preparePlaceholder(image);
        if (observer) observer.observe(image);
      }
      if (!observer && nearby(image)) enqueue(image);
    };
    if (root.matches?.("img") || root.matches?.("img[data-hw-src]")) register(root);
    if (root.querySelectorAll) {
      for (const image of root.querySelectorAll("img")) register(image);
    }
    pump();
  }

  const observer = typeof IntersectionObserver === "undefined"
    ? null
    : new IntersectionObserver((entries) => {
        for (const { target, isIntersecting } of entries) {
          if (isIntersecting) {
            visible.add(target);
            enqueue(target);
          } else {
            visible.delete(target);
            pending.delete(target);
          }
        }
        pump();
      }, { rootMargin: PREFETCH_MARGIN });

  const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
    for (const {target} of entries) if (visible.has(target)) enqueue(target);
    pump();
  });

  function set(image, source, options = {}) {
    if (!image || !source) return;
    if (image.dataset.hwSrc !== source) {
      const cancel = cancellations.get(image);
      image.dataset.hwSrc = source;
      states.delete(image);
      delete image.dataset.hwLoaded;
      delete image.dataset.hwFailed;
      retries.delete(image);
      image.classList?.remove('hw-img-ready');
      const box = progressiveBox(image);
      box?.classList.remove('hw-preview-ready');
      if (box) delete box.dataset.hwPlaceholderReady;
      cancel?.();
    }
    if (options.width) image.dataset.hwWidth = String(options.width);
    scan(image);
    if (nearby(image)) {visible.add(image);enqueue(image);pump();}
  }

  function transformHtml(html, forDisplay) {
    const template = document.createElement('template');
    template.innerHTML = String(html || '');
    if (!template.content) return template.innerHTML;
    for (const image of template.content.querySelectorAll('img')) {
      const source = image.getAttribute('data-hw-src') || image.getAttribute('src');
      if (!source) continue;
      if (forDisplay) {
        image.setAttribute('data-hw-src', source);
        image.removeAttribute('src');
        image.removeAttribute('srcset');
      } else {
        image.setAttribute('src', source);
        for (const attribute of [...image.attributes])
          if (attribute.name.startsWith('data-hw-')) image.removeAttribute(attribute.name);
        image.classList.remove('hw-img-ready','hw-img-loading','hw-img-failed');
      }
    }
    return template.innerHTML;
  }

  window.HandrawImageLoader = {
    scan,
    set,
    url: variantUrl,
    original: image => image?.dataset?.hwSrc || image?.getAttribute?.('src') || '',
    prepareHtml: html => transformHtml(html, true),
    originalHtml: html => transformHtml(html, false),
    retry(image) {
      if (!image || !image.dataset.hwSrc) return false;
      delete image.dataset.hwFailed;
      image.classList.remove("hw-img-failed");
      retries.delete(image);
      failures.delete(image);
      pending.add(image);
      pump();
      return true;
    },
    retryFailed() {
      const count = failures.size;
      for (const image of [...failures]) this.retry(image);
      return count;
    },
    constants: { MAX_ACTIVE, START_INTERVAL, RETRY_DELAY, MAX_RETRIES, PREFETCH_MARGIN, WIDTHS }
  };
  window.HandrawImages = window.HandrawImageLoader;

  // Batch DOM additions into a single scan of only the new subtrees. Never
  // rescan the whole document on each card append or on every scroll tick.
  const addedRoots = new Set();
  let scanScheduled = false;
  function flushAdded() {
    scanScheduled = false;
    const roots = [...addedRoots];
    addedRoots.clear();
    for (const root of roots) if (root.isConnected) scan(root);
  }
  function scheduleAdded() {
    if (scanScheduled) return;
    scanScheduled = true;
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(flushAdded);
    else setTimeout(flushAdded, 0);
  }
  if (typeof MutationObserver !== "undefined") {
    new MutationObserver((records) => {
      for (const record of records || []) {
        if (record.type === 'attributes') {
          const image = record.target;
          if (record.attributeName === 'src' && image.getAttribute('src') !== states.get(image)?.url) {
            const source = image.getAttribute('src');
            if (source && source !== image.dataset.hwSrc) set(image, source);
          } else if (record.attributeName === 'data-hw-src') {
            if (states.get(image)?.raw !== image.dataset.hwSrc) {
              const cancel = cancellations.get(image);
              states.delete(image); delete image.dataset.hwLoaded;
              delete image.dataset.hwFailed; retries.delete(image);
              cancel?.();
            }
            enqueue(image);pump();
          }
        }
        for (const node of record.addedNodes || []) {
          if (node.nodeType !== 1) continue;
          if (node.matches?.("img") || node.matches?.("img[data-hw-src]") || node.querySelector?.("img") || node.querySelector?.("img[data-hw-src]")) {
            addedRoots.add(node);
          }
        }
        for (const node of record.removedNodes || []) {
          if (node.nodeType !== 1) continue;
          const detached = [node, ...(node.querySelectorAll?.('img') || [])];
          for (const image of detached) if (!image.isConnected) {
            managedImages.delete(image); pending.delete(image);failures.delete(image);
            watched.delete(image);cancellations.get(image)?.();
            observer?.unobserve?.(image);resizeObserver?.unobserve?.(image);
          }
        }
      }
      if (addedRoots.size) scheduleAdded();
    }).observe(document.documentElement, { childList: true, subtree: true, attributes:true, attributeFilter:['src','data-hw-src'] });
  }
  // IntersectionObserver already tracks scroll/resize; only use a throttled
  // viewport scan on old browsers without it.
  if (!observer) {
    let fallbackScheduled = false;
    const onViewport = () => {
      if (fallbackScheduled) return;
      fallbackScheduled = true;
      const run = () => { fallbackScheduled = false; scan(document); };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
      else setTimeout(run, 100);
    };
    window.addEventListener("scroll", onViewport, { passive: true });
    window.addEventListener("resize", onViewport, { passive: true });
  }
  if (observer) window.addEventListener('resize', () => {
    for (const image of managedImages) if (image.isConnected && visible.has(image)) enqueue(image);
    pump();
  }, {passive:true});
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => scan(document), { once: true });
  else scan(document);
})();
