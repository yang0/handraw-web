"use strict";

// Shared by the portal and static galleries. Native lazy loading can still
// start dozens of nearby thumbnails together, so all list images use a queue.
(() => {
  const MAX_ACTIVE = 2;
  const START_INTERVAL = 600;
  const RETRY_DELAY = 10000;
  const pending = new Set();
  const failures = new Set();
  const inFlight = new WeakSet();
  const watched = new WeakSet();
  let active = 0;
  let lastStart = -START_INTERVAL;
  let timer;
  let retryAt = 0;
  let retryNotice;

  function nearby(image) {
    if (!image.isConnected || !image.getClientRects().length) return false;
    const rect = image.getBoundingClientRect();
    return (
      rect.bottom >= -100 &&
      rect.top <= window.innerHeight + 100 &&
      rect.right >= 0 &&
      rect.left <= window.innerWidth
    );
  }

  function showFailures() {
    if (retryNotice || !failures.size) return;
    retryNotice = document.createElement("div");
    retryNotice.setAttribute("role", "status");
    retryNotice.style.cssText =
      "position:fixed;bottom:16px;right:16px;z-index:10000;padding:12px 16px;background:#fffdf9;color:#252722;border:1px solid #ded8cf;border-radius:6px;font:14px system-ui;box-shadow:0 3px 14px #0001";
    const text = document.createElement("span");
    text.textContent = "部分图片暂未显示。";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "稍后重试图片";
    retry.disabled = true;
    retry.style.cssText =
      "margin-left:8px;background:transparent;border:0;color:#a94028;cursor:pointer;font:inherit";
    const enableRetry = () => {
      if (Date.now() < retryAt) setTimeout(enableRetry, retryAt - Date.now());
      else {
        retry.disabled = false;
        retry.textContent = "重试图片";
      }
    };
    setTimeout(enableRetry, Math.max(0, retryAt - Date.now()));
    retry.addEventListener("click", () => {
      if (Date.now() < retryAt) return;
      retryNotice.remove();
      retryNotice = null;
      for (const image of failures) {
        if (!image.isConnected) continue;
        delete image.dataset.hwFailed;
        if (nearby(image)) pending.add(image);
      }
      failures.clear();
      pump();
    });
    retryNotice.append(text, retry);
    document.body.append(retryNotice);
  }

  function pump() {
    clearTimeout(timer);
    if (active >= MAX_ACTIVE || !pending.size) return;
    const wait = Math.max(
      START_INTERVAL - (Date.now() - lastStart),
      retryAt - Date.now(),
    );
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
    if (
      !source ||
      inFlight.has(image) ||
      image.dataset.hwLoaded === source ||
      image.dataset.hwFailed
    )
      return pump();
    active++;
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
      active--;
      if (image.dataset.hwSrc !== source) {
        if (nearby(image)) pending.add(image);
      } else if (failed) {
        image.dataset.hwFailed = "true";
        failures.add(image);
        retryAt = Math.max(retryAt, Date.now() + RETRY_DELAY);
        showFailures();
      } else {
        image.dataset.hwLoaded = source;
      }
      pump();
    };
    const loaded = () => done(false);
    const errored = () => done(true);
    image.addEventListener("load", loaded);
    image.addEventListener("error", errored);
    image.src = source;
    timer = setTimeout(pump, START_INTERVAL);
  }

  const observer =
    typeof IntersectionObserver === "undefined"
      ? null
      : new IntersectionObserver(
          (entries) => {
            for (const { target, isIntersecting } of entries) {
              if (
                isIntersecting &&
                !inFlight.has(target) &&
                !target.dataset.hwFailed &&
                target.dataset.hwLoaded !== target.dataset.hwSrc
              )
                pending.add(target);
              else pending.delete(target);
            }
            pump();
          },
          { rootMargin: "100px 0px" },
        );

  function scan() {
    for (const image of document.querySelectorAll("img[data-hw-src]")) {
      if (watched.has(image)) continue;
      watched.add(image);
      if (observer) observer.observe(image);
      else if (nearby(image)) pending.add(image);
    }
    if (!observer) {
      for (const image of document.querySelectorAll("img[data-hw-src]"))
        if (
          nearby(image) &&
          !inFlight.has(image) &&
          !image.dataset.hwFailed &&
          image.dataset.hwLoaded !== image.dataset.hwSrc
        )
          pending.add(image);
    }
    pump();
  }

  window.HandrawImages = {
    set(image, source) {
      if (!source || image.dataset.hwSrc === source) return;
      image.dataset.hwSrc = source;
      delete image.dataset.hwFailed;
      delete image.dataset.hwLoaded;
      failures.delete(image);
      if (observer) {
        observer.unobserve(image);
        observer.observe(image);
      } else scan();
    },
  };
  new MutationObserver(scan).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  window.addEventListener("scroll", scan, { passive: true });
  window.addEventListener("resize", scan, { passive: true });
  document.addEventListener("DOMContentLoaded", scan, { once: true });
  scan();
})();
