/* Conservative 2.0 image loader.
 * Images opt in with data-hw-src. Starts are limited to two concurrent
 * requests, spaced by 600ms; any failure pauses new starts for 10 seconds.
 */
(function () {
  "use strict";

  const MAX_ACTIVE = 2;
  const START_INTERVAL = 600;
  const RETRY_DELAY = 10_000;
  const pending = new Set();
  const failures = new Set();
  const inFlight = new WeakSet();
  const watched = new WeakSet();
  let active = 0;
  let lastStart = -START_INTERVAL;
  let retryAt = 0;
  let timer = null;
  let retryNotice = null;

  function nearby(image) {
    if (!image.isConnected || !image.getClientRects || !image.getClientRects().length) return false;
    const rect = image.getBoundingClientRect();
    return rect.bottom >= -120 && rect.top <= window.innerHeight + 120 && rect.right >= 0 && rect.left <= window.innerWidth;
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
    if (active >= MAX_ACTIVE || !pending.size) return;
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
    const source = image.dataset.hwSrc;
    if (!source || inFlight.has(image) || image.dataset.hwLoaded === source || image.dataset.hwFailed) return pump();
    active += 1;
    inFlight.add(image);
    lastStart = Date.now();
    image.dataset.hwManaged = "true";
    image.loading = "eager";
    image.decoding = "async";
    let finished = false;
    const done = (failed) => {
      if (finished) return;
      finished = true;
      image.removeEventListener("load", loaded);
      image.removeEventListener("error", errored);
      inFlight.delete(image);
      active = Math.max(0, active - 1);
      if (failed) {
        image.dataset.hwFailed = "true";
        failures.add(image);
        retryAt = Math.max(retryAt, Date.now() + RETRY_DELAY);
        showFailures();
      } else {
        failures.delete(image);
        image.dataset.hwLoaded = source;
      }
      pump();
    };
    const loaded = () => done(false);
    const errored = () => done(true);
    image.addEventListener("load", loaded);
    image.addEventListener("error", errored);
    image.src = source;
    // Keep draining the queue even while the current image is still pending;
    // the next pump will start the second slot once the 600ms spacing passes.
    timer = setTimeout(pump, START_INTERVAL);
  }

  function scan(root = document) {
    if (!root || !root.querySelectorAll) return;
    for (const image of root.querySelectorAll("img[data-hw-src]")) {
      if (watched.has(image)) continue;
      watched.add(image);
      if (observer) observer.observe(image);
      else if (nearby(image)) pending.add(image);
    }
    if (!observer) {
      for (const image of root.querySelectorAll("img[data-hw-src]")) {
        if (nearby(image) && !inFlight.has(image) && !image.dataset.hwFailed && image.dataset.hwLoaded !== image.dataset.hwSrc) pending.add(image);
      }
    }
    pump();
  }

  const observer = typeof IntersectionObserver === "undefined"
    ? null
    : new IntersectionObserver((entries) => {
        for (const { target, isIntersecting } of entries) {
          if (isIntersecting && !inFlight.has(target) && !target.dataset.hwFailed && target.dataset.hwLoaded !== target.dataset.hwSrc) pending.add(target);
          else pending.delete(target);
        }
        pump();
      }, { rootMargin: "120px 0px" });

  window.HandrawImageLoader = {
    scan,
    retry(image) {
      if (!image || !image.dataset.hwSrc) return false;
      delete image.dataset.hwFailed;
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
    constants: { MAX_ACTIVE, START_INTERVAL, RETRY_DELAY }
  };

  if (typeof MutationObserver !== "undefined") {
    new MutationObserver(() => scan(document)).observe(document.documentElement, { childList: true, subtree: true });
  }
  window.addEventListener("scroll", () => scan(document), { passive: true });
  window.addEventListener("resize", () => scan(document), { passive: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => scan(document), { once: true });
  else scan(document);
})();
