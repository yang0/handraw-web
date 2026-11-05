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
 * Images opt in with data-hw-src. Optional attributes:
 *   data-hw-width  requested render width; drives ?w= on the source
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

  /** Build the URL actually requested for one image. */
  function resolveSource(image) {
    const raw = (image.dataset.hwSrc || "").trim();
    if (!raw) return "";
    if (raw.startsWith("data:")) return raw;
    if (/[?&]w=/.test(raw)) return raw;
    // Only the Handraw media endpoint guarantees ?w= thumbnail support.
    // Adding it to arbitrary remote hosts can break image URLs and caching.
    if (!/^\/(?:images|uploads|generated)\//.test(raw)) return raw;
    const width = parseInt(image.dataset.hwWidth || "", 10);
    if (!width || width <= 0) return raw;
    return raw + (raw.includes("?") ? "&" : "?") + "w=" + width;
  }

  /** Estimate a request width bucket from the rendered box. */
  function autoWidth(image) {
    const cssWidth = image.clientWidth || image.parentElement?.clientWidth || 0;
    if (!cssWidth) return 0;
    return Math.ceil((cssWidth * (window.devicePixelRatio || 1)) / 160) * 160;
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
    if (!/^\/(?:images|uploads|generated)\//.test(source) || /[?&]w=/.test(source)) return "";
    return source + (source.includes("?") ? "&" : "?") + "w=" + PREVIEW_WIDTH;
  }

  function revealPreview(image, source, dimensions) {
    const box = progressiveBox(image);
    if (!box || image.classList.contains("hw-img-ready")) return;
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
    if (!box || image.classList.contains("hw-img-ready")) return;
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

    let finished = false;
    let skeletonTimer = null;
    const done = (failed) => {
      if (finished) return;
      finished = true;
      if (skeletonTimer) clearTimeout(skeletonTimer);
      image.removeEventListener("load", loaded);
      image.removeEventListener("error", errored);
      inFlight.delete(image);
      active = Math.max(0, active - 1);
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
      }
      pump();
    };
    const loaded = () => done(false);
    const errored = () => done(true);
    image.addEventListener("load", loaded);
    image.addEventListener("error", errored);

    if (!decodedSources.has(source)) {
      // Defer the animated placeholder until we know this is not a fast
      // memory/disk-cache hit; the immediate flash was very noticeable.
      skeletonTimer = setTimeout(() => {
        if (!finished && image.isConnected) markLoading(image);
      }, SKELETON_DELAY);
    } else image.classList.remove("hw-img-loading");
    // A cached image can be complete immediately; avoid waiting for another event.
    if (image.getAttribute?.("src") !== source) image.src = source;
    if (image.complete && image.naturalWidth > 0) done(false);
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
      if (!watched.has(image)) {
        watched.add(image);
        if (!image.dataset.hwWidth) {
          const guess = autoWidth(image);
          if (guess > 0) image.dataset.hwWidth = String(guess);
        }
        applyRatio(image);
        preparePlaceholder(image);
        if (observer) observer.observe(image);
      }
      if (!observer && nearby(image)) enqueue(image);
    };
    if (root.matches?.("img[data-hw-src]")) register(root);
    if (root.querySelectorAll) {
      for (const image of root.querySelectorAll("img[data-hw-src]")) register(image);
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

  window.HandrawImageLoader = {
    scan,
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
    constants: { MAX_ACTIVE, START_INTERVAL, RETRY_DELAY, MAX_RETRIES, PREFETCH_MARGIN }
  };

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
        for (const node of record.addedNodes || []) {
          if (node.nodeType !== 1) continue;
          if (node.matches?.("img[data-hw-src]") || node.querySelector?.("img[data-hw-src]")) {
            addedRoots.add(node);
          }
        }
      }
      if (addedRoots.size) scheduleAdded();
    }).observe(document.documentElement, { childList: true, subtree: true });
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
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => scan(document), { once: true });
  else scan(document);
})();
