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
  const START_INTERVAL = 40;
  const RETRY_DELAY = 4_000;
  const MAX_RETRIES = 2;
  const PREFETCH_MARGIN = "600px 0px";

  const pending = new Set();
  const failures = new Set();
  const inFlight = new WeakSet();
  const watched = new WeakSet();
  const retries = new WeakMap();
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
      const image = [...pending].find(nearby);
      if (!image) {
        pending.clear();
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
    const done = (failed) => {
      if (finished) return;
      finished = true;
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
        image.classList.add("hw-img-ready");
        image.classList.remove("hw-img-loading");
      }
      pump();
    };
    const loaded = () => done(false);
    const errored = () => done(true);
    image.addEventListener("load", loaded);
    image.addEventListener("error", errored);

    markLoading(image);
    image.src = source;
  }

  function markLoading(image) {
    if (!image.dataset.hwLqipApplied && image.dataset.hwLqip) {
      image.style.backgroundImage = `url("${image.dataset.hwLqip}")`;
      image.style.backgroundSize = "cover";
      image.style.backgroundPosition = "center";
      image.dataset.hwLqipApplied = "true";
    }
    image.classList.add("hw-img-loading");
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
    pending.add(image);
  }

  function scan(root = document) {
    if (!root || !root.querySelectorAll) return;
    for (const image of root.querySelectorAll("img[data-hw-src]")) {
      if (!watched.has(image)) {
        watched.add(image);
        if (!image.dataset.hwWidth) {
          const guess = autoWidth(image);
          if (guess > 0) image.dataset.hwWidth = String(guess);
        }
        applyRatio(image);
        if (observer) observer.observe(image);
      }
      if (!observer) {
        if (nearby(image)) enqueue(image);
      }
    }
    pump();
  }

  const observer = typeof IntersectionObserver === "undefined"
    ? null
    : new IntersectionObserver((entries) => {
        for (const { target, isIntersecting } of entries) {
          if (isIntersecting) enqueue(target);
          else pending.delete(target);
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

  if (typeof MutationObserver !== "undefined") {
    new MutationObserver(() => scan(document)).observe(document.documentElement, { childList: true, subtree: true });
  }
  window.addEventListener("scroll", () => scan(document), { passive: true });
  window.addEventListener("resize", () => scan(document), { passive: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => scan(document), { once: true });
  else scan(document);
})();
