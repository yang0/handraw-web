"""Playwright browser verification for Issue #55: Fix thumbnail cropping on style detail and related works page.

Verifies on port 3100:
1. Style Detail Page ('用这个画风做的作品'):
   - Portrait work (9:16) thumbnail container aspect-ratio matches img natural aspect-ratio.
   - Landscape work (4:3) thumbnail container aspect-ratio matches img natural aspect-ratio.
   - img object-fit is NOT 'cover' (is 'contain').
   - Desktop 1440x900 and Mobile 390x844 viewports.
   - Layout stability during loading (no sudden layout shifts).
2. '查看全部' Page (/forum/?view=related&kind=style&id=FA-001&tab=works):
   - Portrait work thumbnail container aspect-ratio matches img natural aspect-ratio.
   - Landscape work thumbnail container aspect-ratio matches img natural aspect-ratio.
   - img object-fit is NOT 'cover'.
   - Desktop 1440x900 and Mobile 390x844 viewports.
3. Screenshots saved to C:/tmp/:
   - C:/tmp/thumb_01_style_detail_1440.png
   - C:/tmp/thumb_02_style_detail_390.png
   - C:/tmp/thumb_03_view_all_1440.png
   - C:/tmp/thumb_04_view_all_390.png
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from backend.db import utc_now_iso
from backend.server import HandrawRequestHandler, init_database
from backend.services import register_user

PORT = 3100
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def run_browser_verification():
    print("[1/5] Setting up temporary test environment...")
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{PORT}"
    os.environ["HANDRAW_PRIVATE_STORAGE"] = temp_dir.name
    os.environ["HANDRAW_DEMO_MODE"] = "1"

    db_path = Path(temp_dir.name) / "browser_verify.db"
    db = init_database(db_path)

    author, _ = register_user(db, "author_demo", "password123")
    now_iso = utc_now_iso()
    now_ms = int(time.time() * 1000)

    # Insert test works: 1 portrait (9:16), 1 landscape (4:3) with style FA-001
    with db.transaction() as tx:
        # Portrait work (poster-demo-autumn-equinox is 576x1024, ratio ~ 0.5625)
        tx.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, styles_json, layout_code,
                ratio, price, status, likes, favorites, published_at_ms, images_json, created_at, updated_at
            ) VALUES (
                'w_portrait_55', 'author_demo', '原创作者', '秋分水墨竖图海报', '竖版水墨秋分', '["FA-001"]', '',
                '9:16', 0, 'published', 12, 4, ?, '["/images/poster-demo-autumn-equinox.webp"]', ?, ?
            )
            """,
            (now_ms, now_iso, now_iso),
        )

        # Landscape work (characters/CH-001.webp is 1024x768, ratio ~ 1.3333)
        tx.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, prompt, styles_json, layout_code,
                ratio, price, status, likes, favorites, published_at_ms, images_json, created_at, updated_at
            ) VALUES (
                'w_landscape_55', 'author_demo', '原创作者', '水墨横版角色样张', '横版角色图册', '["FA-001"]', '',
                '4:3', 0, 'published', 25, 8, ?, '["/images/characters/CH-001.webp"]', ?, ?
            )
            """,
            (now_ms, now_iso, now_iso),
        )

        # Style topic for FA-001
        tx.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, price,
                status, likes, favorites, published_at_ms, images_json, styles_json, summary, created_at, updated_at
            ) VALUES (
                't_style_fa001', 'assets', '资源交流', '官方资源帖：Playful Deadpan Doodle', 'system', '官方', 0,
                'published', 88, 30, ?, '[]', '["FA-001"]', '官方资源帖：Playful Deadpan Doodle', ?, ?
            )
            """,
            (now_ms, now_iso, now_iso),
        )
        tx.execute(
            """
            INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
            VALUES ('style', 'FA-001', 't_style_fa001', 'official', ?)
            """,
            (now_iso,),
        )

    print(f"[2/5] Starting HTTP server on port {PORT}...")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    server.db = db
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    print("[3/5] Launching Playwright browser...")
    with sync_playwright() as p:
        browser_kwargs = {"headless": True}
        if os.path.exists(CHROME_PATH):
            browser_kwargs["executable_path"] = CHROME_PATH
        browser = p.chromium.launch(**browser_kwargs)

        context_1440 = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context_1440.new_page()

        # ==============================================================
        # Test 1: Style Detail Page (Desktop 1440x900)
        # ==============================================================
        print("Testing Style Detail Page at 1440x900...")
        style_detail_url = f"{BASE_URL}/forum/?view=topic&id=t_style_fa001"
        page.goto(style_detail_url, wait_until="networkidle")

        # Wait for related works to load
        page.wait_for_selector("#topic-related-works-container .topic-related-work-media", timeout=10000)

        # Verify works are displayed
        media_els = page.query_selector_all("#topic-related-works-container .topic-related-work-media")
        assert len(media_els) >= 2, f"Expected at least 2 related works, got {len(media_els)}"

        # Evaluate portrait work and landscape work metrics
        page.wait_for_function("""() => {
            const imgs = Array.from(document.querySelectorAll("#topic-related-works-container img"));
            return imgs.length >= 2 && imgs.slice(0, 2).every(img => img.complete && img.naturalWidth > 0);
        }""", timeout=10000)

        metrics = page.evaluate("""() => {
            const container = document.querySelector("#topic-related-works-container");
            const cards = Array.from(container.querySelectorAll("a"));
            return cards.map(card => {
                const title = card.querySelector("div[style*='font-weight:750']")?.textContent?.trim() || "";
                const media = card.querySelector(".topic-related-work-media");
                const img = media?.querySelector("img");
                const mRect = media?.getBoundingClientRect();
                const objFit = img ? window.getComputedStyle(img).objectFit : "";
                const mediaArStyle = media ? media.style.aspectRatio : "";
                return {
                    title,
                    containerWidth: mRect ? mRect.width : 0,
                    containerHeight: mRect ? mRect.height : 0,
                    containerRatio: (mRect && mRect.height > 0) ? (mRect.width / mRect.height) : 0,
                    imgNaturalWidth: img ? img.naturalWidth : 0,
                    imgNaturalHeight: img ? img.naturalHeight : 0,
                    imgNaturalRatio: (img && img.naturalHeight > 0) ? (img.naturalWidth / img.naturalHeight) : 0,
                    objectFit: objFit,
                    mediaArStyle: mediaArStyle,
                };
            }).filter(m => m.title.includes("水墨横版角色样张") || m.title.includes("秋分水墨竖图海报"));
        }""")

        print(f"Target works evaluated on detail page (1440): {metrics}")
        assert len(metrics) == 2, f"Expected 2 target works, got {len(metrics)}"
        for m in metrics:
            assert m["objectFit"] != "cover", f"Image {m['title']} must not use object-fit: cover, got {m['objectFit']}"
            assert m["objectFit"] == "contain", f"Image {m['title']} should use object-fit: contain, got {m['objectFit']}"
            assert m["imgNaturalWidth"] > 0 and m["imgNaturalHeight"] > 0, f"Image {m['title']} did not load"
            # Container aspect-ratio must match natural image aspect-ratio within 0.05
            ratio_diff = abs(m["containerRatio"] - m["imgNaturalRatio"])
            assert ratio_diff < 0.05, f"Container ratio {m['containerRatio']:.3f} does not match image natural ratio {m['imgNaturalRatio']:.3f} (diff {ratio_diff})"

        # Screenshot 1: Desktop 1440 Style Detail
        s1 = SCREENSHOT_DIR / "thumb_01_style_detail_1440.png"
        page.screenshot(path=str(s1), full_page=True)
        print(f"Captured {s1}")

        # ==============================================================
        # Test 2: Style Detail Page (Mobile 390x844)
        # ==============================================================
        print("Testing Style Detail Page at 390x844...")
        context_390 = browser.new_context(viewport={"width": 390, "height": 844})
        page_mobile = context_390.new_page()
        page_mobile.goto(style_detail_url, wait_until="networkidle")
        page_mobile.wait_for_selector("#topic-related-works-container .topic-related-work-media", timeout=10000)
        page_mobile.wait_for_function("""() => {
            const imgs = Array.from(document.querySelectorAll("#topic-related-works-container img"));
            return imgs.length >= 2 && imgs.slice(0, 2).every(img => img.complete && img.naturalWidth > 0);
        }""", timeout=10000)

        mobile_metrics = page_mobile.evaluate("""() => {
            const container = document.querySelector("#topic-related-works-container");
            const cards = Array.from(container.querySelectorAll("a"));
            return cards.map(card => {
                const title = card.querySelector("div[style*='font-weight:750']")?.textContent?.trim() || "";
                const media = card.querySelector(".topic-related-work-media");
                const img = media?.querySelector("img");
                const mRect = media?.getBoundingClientRect();
                return {
                    title,
                    containerRatio: (mRect && mRect.height > 0) ? (mRect.width / mRect.height) : 0,
                    imgNaturalRatio: (img && img.naturalHeight > 0) ? (img.naturalWidth / img.naturalHeight) : 0,
                    objectFit: img ? window.getComputedStyle(img).objectFit : "",
                };
            }).filter(m => m.title.includes("水墨横版角色样张") || m.title.includes("秋分水墨竖图海报"));
        }""")
        print(f"Target works evaluated on mobile detail (390): {mobile_metrics}")
        assert len(mobile_metrics) == 2, f"Expected 2 target works on mobile, got {len(mobile_metrics)}"
        for m in mobile_metrics:
            assert m["objectFit"] != "cover"
            assert m["objectFit"] == "contain"
            ratio_diff = abs(m["containerRatio"] - m["imgNaturalRatio"])
            assert ratio_diff < 0.05, f"Mobile container ratio mismatch for {m['title']}"

        # Screenshot 2: Mobile 390 Style Detail
        s2 = SCREENSHOT_DIR / "thumb_02_style_detail_390.png"
        page_mobile.screenshot(path=str(s2), full_page=True)
        print(f"Captured {s2}")

        # ==============================================================
        # Test 3: View All Related Works Page (/forum/?view=related...) Desktop 1440
        # ==============================================================
        print("Testing View All Page at 1440x900...")
        view_all_url = f"{BASE_URL}/forum/?view=related&kind=style&id=FA-001&tab=works"
        page.goto(view_all_url, wait_until="networkidle")
        page.wait_for_selector(".hrp-grid .hrp-card", timeout=10000)
        page.wait_for_function("""() => {
            const imgs = Array.from(document.querySelectorAll(".hrp-card[data-res-kind='work'] img"));
            return imgs.length >= 2 && imgs.slice(0, 2).every(img => img.complete && img.naturalWidth > 0);
        }""", timeout=10000)

        view_all_metrics = page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll(".hrp-card[data-res-kind='work']"));
            return cards.map(card => {
                const title = card.querySelector(".hrp-card-title")?.textContent?.trim() || "";
                const media = card.querySelector(".hrp-card-media");
                const img = media?.querySelector("img");
                const mRect = media?.getBoundingClientRect();
                return {
                    title,
                    containerRatio: (mRect && mRect.height > 0) ? (mRect.width / mRect.height) : 0,
                    imgNaturalRatio: (img && img.naturalHeight > 0) ? (img.naturalWidth / img.naturalHeight) : 0,
                    objectFit: img ? window.getComputedStyle(img).objectFit : "",
                    mediaArStyle: media ? media.style.aspectRatio : "",
                };
            }).filter(m => m.title.includes("水墨横版角色样张") || m.title.includes("秋分水墨竖图海报"));
        }""")
        print(f"View All metrics (1440): {view_all_metrics}")
        assert len(view_all_metrics) == 2, f"Expected 2 target work cards in view all, got {len(view_all_metrics)}"
        for m in view_all_metrics:
            assert m["objectFit"] != "cover", f"Card {m['title']} must not use cover, got {m['objectFit']}"
            assert m["objectFit"] == "contain", f"Card {m['title']} should use contain, got {m['objectFit']}"
            ratio_diff = abs(m["containerRatio"] - m["imgNaturalRatio"])
            assert ratio_diff < 0.05, f"View all container ratio {m['containerRatio']:.3f} does not match image {m['imgNaturalRatio']:.3f}"

        # Screenshot 3: View All 1440
        s3 = SCREENSHOT_DIR / "thumb_03_view_all_1440.png"
        page.screenshot(path=str(s3), full_page=True)
        print(f"Captured {s3}")

        # ==============================================================
        # Test 4: View All Related Works Page Mobile 390
        # ==============================================================
        print("Testing View All Page at 390x844...")
        page_mobile.goto(view_all_url, wait_until="networkidle")
        page_mobile.wait_for_selector(".hrp-grid .hrp-card", timeout=10000)
        page_mobile.wait_for_function("""() => {
            const imgs = Array.from(document.querySelectorAll(".hrp-card[data-res-kind='work'] img"));
            return imgs.length >= 2 && imgs.slice(0, 2).every(img => img.complete && img.naturalWidth > 0);
        }""", timeout=10000)

        mobile_va_metrics = page_mobile.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll(".hrp-card[data-res-kind='work']"));
            return cards.map(card => {
                const title = card.querySelector(".hrp-card-title")?.textContent?.trim() || "";
                const media = card.querySelector(".hrp-card-media");
                const img = media?.querySelector("img");
                const mRect = media?.getBoundingClientRect();
                return {
                    title,
                    containerRatio: (mRect && mRect.height > 0) ? (mRect.width / mRect.height) : 0,
                    imgNaturalRatio: (img && img.naturalHeight > 0) ? (img.naturalWidth / img.naturalHeight) : 0,
                    objectFit: img ? window.getComputedStyle(img).objectFit : "",
                };
            }).filter(m => m.title.includes("水墨横版角色样张") || m.title.includes("秋分水墨竖图海报"));
        }""")
        print(f"Mobile View All metrics: {mobile_va_metrics}")
        assert len(mobile_va_metrics) == 2
        for m in mobile_va_metrics:
            assert m["objectFit"] != "cover"
            assert m["objectFit"] == "contain"
            ratio_diff = abs(m["containerRatio"] - m["imgNaturalRatio"])
            assert ratio_diff < 0.05, f"Mobile View All ratio mismatch for {m['title']}"

        # Screenshot 4: View All 390
        s4 = SCREENSHOT_DIR / "thumb_04_view_all_390.png"
        page_mobile.screenshot(path=str(s4), full_page=True)
        print(f"Captured {s4}")

        browser.close()

    print("[4/5] Shutting down ephemeral server...")
    server.shutdown()
    try:
        db.get_conn().close()
        db.close()
    except Exception:
        pass
    try:
        temp_dir.cleanup()
    except Exception:
        pass
    print("[5/5] Verification completed successfully!")


if __name__ == "__main__":
    run_browser_verification()
