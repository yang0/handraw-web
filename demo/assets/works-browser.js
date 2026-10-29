/* Pure browsing rules for published works. No content generation or permissions. */
(function () {
  "use strict";
  function imagesFor(work) {
    const images = work && Array.isArray(work.images) ? work.images : [];
    return images.map(image => typeof image === "string" ? image : image && image.url)
      .filter(image => typeof image === "string" && image.trim());
  }
  function formatFor(work) { return imagesFor(work).length > 1 ? "multi" : "single"; }
  function countFormats(works) {
    const counts = { all: 0, single: 0, multi: 0 };
    for (const work of works || []) {
      if (!imagesFor(work).length) continue;
      counts.all++; counts[formatFor(work)]++;
    }
    return counts;
  }
  function select(works, filters, resourceMap, shared) {
    const f = filters || {}, query = String(f.query || "").trim().toLowerCase();
    const result = (works || []).filter(work => {
      if (!work || !imagesFor(work).length) return false;
      if (f.format && f.format !== "all" && formatFor(work) !== f.format) return false;
      const price = Number(work.price) || 0;
      if (f.access === "free" && price > 0) return false;
      if (f.access === "paid" && price <= 0) return false;
      const codes = (Array.isArray(work.styles) ? work.styles : []).concat(work.layout || []).filter(Boolean);
      if (f.asset && !codes.includes(f.asset)) return false;
      if (f.author && work.author !== f.author) return false;
      if (query) {
        const resources = codes.map(code => {
          const item = resourceMap && resourceMap.get(code);
          return item ? [code, item.name, item.description].join(" ") : code;
        });
        const haystack = [work.title, work.notes, work.author, work.authorName, ...resources].join(" ").toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
    const recency = shared.compareByRecency;
    result.sort((a, b) => {
      // Legacy "favorites"/"cheers" links collapse onto the single popularity
      // formula instead of running their own bespoke sorts.
      if (["favorites", "cheers", "popular", "hot"].includes(f.sort)) {
        return shared.popularScore("work", b) - shared.popularScore("work", a) || recency(a,b);
      }
      return recency(a,b);
    });
    return result;
  }
  window.HandrawWorksBrowser = { imagesFor, formatFor, countFormats, select };
})();
