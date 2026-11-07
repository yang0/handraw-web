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
    const matching = (works || []).filter(work => {
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

    // V3: gallery entries are canonical works, not individual image slots.
    // Never collapse distinct work IDs or expand a multi-image work during search.
    const result = matching;

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

  function normalizeResourceCodes(work) {
    const codes = new Set();
    if (!work) return codes;
    if (Array.isArray(work.styles)) {
      work.styles.forEach(s => {
        const code = String(s || "").trim().toUpperCase().replace(/^#/, "");
        if (code) codes.add(code);
      });
    } else if (typeof work.styles === "string" && work.styles.trim()) {
      try {
        const parsed = JSON.parse(work.styles);
        if (Array.isArray(parsed)) {
          parsed.forEach(s => {
            const code = String(s || "").trim().toUpperCase().replace(/^#/, "");
            if (code) codes.add(code);
          });
        }
      } catch {
        const code = work.styles.trim().toUpperCase().replace(/^#/, "");
        if (code) codes.add(code);
      }
    }
    if (work.layout && typeof work.layout === "string" && work.layout.trim()) {
      const code = work.layout.trim().toUpperCase().replace(/^#/, "");
      if (code) codes.add(code);
    }
    return codes;
  }

  function hasResourceConflict(codesA, codesB) {
    if (!codesA || !codesB || codesA.size === 0 || codesB.size === 0) {
      return false; // Freeform works with no styles/layouts do not participate in avoidance and can fill gaps!
    }
    for (const code of codesA) {
      if (codesB.has(code)) return true;
    }
    return false;
  }

  function parseAspectRatio(work, imgIndex) {
    const idx = Number(imgIndex) || 0;
    if (work && Array.isArray(work.imageDimensions) && work.imageDimensions[idx]) {
      const d = work.imageDimensions[idx];
      if (d.aspectRatio && Number(d.aspectRatio) > 0) return Number(d.aspectRatio);
      if (d.width && d.height && Number(d.height) > 0) return Number(d.width) / Number(d.height);
    } else if (work && work.imageDimensions && !Array.isArray(work.imageDimensions)) {
      const d = work.imageDimensions;
      if (d.aspectRatio && Number(d.aspectRatio) > 0) return Number(d.aspectRatio);
      if (d.width && d.height && Number(d.height) > 0) return Number(d.width) / Number(d.height);
    }
    // Do not use work.ratio (e.g. "3:4") to infer image box aspect-ratio.
    // When dimensions are missing, placeholder is 1:1.
    return 1.0;
  }

  function getColumnCount(containerWidth) {
    const w = Number(containerWidth) || (typeof window !== "undefined" ? window.innerWidth : 1440);
    if (w <= 340) return 1;
    if (w <= 760) return 2;
    if (w <= 1100) return 3;
    return 4;
  }

  function unpackWorkCandidates(works) {
    // One published work gets exactly one gallery card, regardless of its
    // number of media items. The detail view owns the full media collection.
    return (works || []).flatMap(w => {
      const imgs = imagesFor(w);
      if (!imgs.length) return [];
      const author = String(w.author || w.author_username || w.authorName || w.user || "").trim();
      return [{
        itemKey: `${w.id}_cover`,
        workId: String(w.id),
        author,
        authorUsername: author,
        imgIndex: 0,
        totalImages: imgs.length,
        imageUrl: imgs.includes(w.coverUrl) ? w.coverUrl : imgs[0],
        aspectRatio: parseAspectRatio(w, 0),
        work: w,
        batchId: w.batchId,
        batchTotal: 1,
        batchIndex: 1,
        resourceCodes: normalizeResourceCodes(w),
        styles: Array.isArray(w.styles) ? w.styles : [],
        layout: w.layout || ""
      }];
    });
  }

  function layoutWorksMasonry(newCandidates, options) {
    const opts = options || {};
    const colCount = Math.max(1, Number(opts.colCount) || 4);
    const viewportHeight = Math.max(200, Number(opts.viewportHeight) || (typeof window !== "undefined" && window.innerHeight) || 800);
    const colWidth = Math.max(100, Number(opts.colWidth) || 280);
    const gap = opts.gap != null ? Number(opts.gap) : (colCount <= 2 ? 10 : 16);
    const bodyHeight = Number(opts.bodyHeight) || 115;
    const candidateBufferCap = Number(opts.candidateBufferCap) || 120;

    const placed = Array.isArray(opts.existingPlaced) ? [...opts.existingPlaced] : [];
    const colHeights = Array.from({ length: colCount }, () => 0);
    placed.forEach(p => {
      if (p.col < colCount) {
        colHeights[p.col] = Math.max(colHeights[p.col], (p.top || 0) + (p.height || 0) + gap);
      }
    });

    let queue = [...(opts.remainingQueue || []), ...(newCandidates || [])];
    if (queue.length > candidateBufferCap) {
      queue = queue.slice(0, candidateBufferCap);
    }

    const newlyPlaced = [];

    function calcCardHeight(ar) {
      const clampedAr = Math.min(2.5, Math.max(0.4, Number(ar) || 0.75));
      const imgHeight = Math.round(colWidth / clampedAr);
      return imgHeight + bodyHeight;
    }

    const distinctAuthorsInQueue = new Set(queue.map(c => c.author).filter(Boolean));
    const hasMultipleAuthors = distinctAuthorsInQueue.size > 1;

    function isResourceConflict(candidate, targetTop, targetHeight) {
      if (!candidate.resourceCodes || candidate.resourceCodes.size === 0) return false;
      for (const p of placed) {
        if (!p.resourceCodes || p.resourceCodes.size === 0) continue;
        if (hasResourceConflict(candidate.resourceCodes, p.resourceCodes)) {
          const pTop = p.top;
          const pBottom = p.top + p.height;
          const cTop = targetTop;
          const cBottom = targetTop + targetHeight;
          if (cTop < pBottom + viewportHeight && pTop < cBottom + viewportHeight) {
            return true;
          }
        }
      }
      return false;
    }

    function isAuthorConflict(candidate, targetTop, targetHeight, col) {
      if (!hasMultipleAuthors || !candidate.author) return false;
      const coVisible = placed.filter(p => {
        const pBottom = p.top + p.height;
        const cBottom = targetTop + targetHeight;
        return targetTop < pBottom + viewportHeight && p.top < cBottom + viewportHeight;
      });
      if (coVisible.length === 0) return false;

      // If all visible cards in current window belong to candidate's author
      const sameAuthorCount = coVisible.filter(p => p.author === candidate.author).length;
      if (sameAuthorCount === coVisible.length) {
        return true;
      }
      // If >= 3 visible cards and author occupies >= 66%
      if (coVisible.length >= 3 && sameAuthorCount / coVisible.length >= 0.66) {
        return true;
      }
      // Column sequential check
      const colItems = placed.filter(p => p.col === col);
      if (colItems.length > 0) {
        const lastInCol = colItems[colItems.length - 1];
        if (lastInCol.author === candidate.author && (targetTop - (lastInCol.top + lastInCol.height)) < viewportHeight * 0.5) {
          return true;
        }
      }
      return false;
    }

    // A softer rule for pass 2: the author may repeat, but not past two thirds
    // of what is on screen at once.
    function isAuthorDominant(candidate, targetTop, targetHeight) {
      if (!hasMultipleAuthors || !candidate.author) return false;
      const coVisible = placed.filter((p) => {
        const pBottom = p.top + p.height;
        const cBottom = targetTop + targetHeight;
        return targetTop < pBottom + viewportHeight && p.top < cBottom + viewportHeight;
      });
      if (coVisible.length < 3) return false;
      const same = coVisible.filter((p) => p.author === candidate.author).length;
      return same / coVisible.length >= 0.66;
    }

    while (queue.length > 0) {
      let minCol = 0;
      let minH = colHeights[0];
      for (let c = 1; c < colCount; c++) {
        if (colHeights[c] < minH) {
          minH = colHeights[c];
          minCol = c;
        }
      }

      let foundIdx = -1;

      // Pass 1: Strict - No resource conflict AND no author conflict
      for (let i = 0; i < queue.length; i++) {
        const cand = queue[i];
        const h = calcCardHeight(cand.aspectRatio);
        if (!isResourceConflict(cand, minH, h) && !isAuthorConflict(cand, minH, h, minCol)) {
          foundIdx = i;
          break;
        }
      }

      // Pass 2: relax the author rule, but never let one author take the whole
      // screen. A queue dominated by a single author (24 of 67 in practice) has
      // no candidate that passes pass 1, so relaxing straight to "any author"
      // reproduced exactly the wall we were trying to avoid.
      if (foundIdx < 0) {
        for (let i = 0; i < queue.length; i++) {
          const cand = queue[i];
          const h = calcCardHeight(cand.aspectRatio);
          if (isResourceConflict(cand, minH, h)) continue;
          if (isAuthorDominant(cand, minH, h)) continue;
          foundIdx = i;
          break;
        }
      }

      // Pass 3: only when even that is impossible, ignore the author entirely.
      if (foundIdx < 0) {
        for (let i = 0; i < queue.length; i++) {
          const cand = queue[i];
          const h = calcCardHeight(cand.aspectRatio);
          if (!isResourceConflict(cand, minH, h)) {
            foundIdx = i;
            break;
          }
        }
      }

      if (foundIdx >= 0) {
        const cand = queue.splice(foundIdx, 1)[0];
        const h = calcCardHeight(cand.aspectRatio);
        const itemRecord = {
          ...cand,
          col: minCol,
          top: minH,
          height: h,
          extraMargin: 0
        };
        placed.push(itemRecord);
        newlyPlaced.push(itemRecord);
        colHeights[minCol] = minH + h + gap;
      } else {
        // Fallback when all remaining candidates have resource conflicts:
        // Do not push down with whitespace separation. Directly place at minH of shortest column,
        // picking the candidate with maximum vertical distance from already placed cards sharing the same code.
        let bestIdx = 0;
        let maxDist = -Infinity;
        for (let i = 0; i < queue.length; i++) {
          const cand = queue[i];
          const h = calcCardHeight(cand.aspectRatio);
          let minDistToConflict = Infinity;
          for (const p of placed) {
            if (hasResourceConflict(cand.resourceCodes, p.resourceCodes)) {
              let d;
              if (minH >= p.top + p.height) {
                d = minH - (p.top + p.height);
              } else if (p.top >= minH + h) {
                d = p.top - (minH + h);
              } else {
                const overlap = Math.min(minH + h, p.top + p.height) - Math.max(minH, p.top);
                d = -overlap;
              }
              if (d < minDistToConflict) {
                minDistToConflict = d;
              }
            }
          }
          if (minDistToConflict > maxDist) {
            maxDist = minDistToConflict;
            bestIdx = i;
          }
        }

        const cand = queue.splice(bestIdx, 1)[0];
        const h = calcCardHeight(cand.aspectRatio);
        const itemRecord = {
          ...cand,
          col: minCol,
          top: minH,
          height: h,
          extraMargin: 0
        };
        placed.push(itemRecord);
        newlyPlaced.push(itemRecord);
        colHeights[minCol] = minH + h + gap;
      }
    }

    return {
      placed,
      newlyPlaced,
      remainingQueue: queue,
      colHeights,
      colCount
    };
  }

  const rootScope = typeof window !== "undefined" ? window : globalThis;
  rootScope.HandrawWorksBrowser = {
    imagesFor,
    formatFor,
    countFormats,
    select,
    normalizeResourceCodes,
    hasResourceConflict,
    parseAspectRatio,
    getColumnCount,
    unpackWorkCandidates,
    layoutWorksMasonry
  };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = rootScope.HandrawWorksBrowser;
  }
})();
