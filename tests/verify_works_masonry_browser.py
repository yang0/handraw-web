"""End-to-end browser verification script for works masonry layout and viewport diversity."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from tests.browser_postgres import browser_postgres_database
from backend import server as server_module
from backend.server import create_channel_server
from backend.services import publish_user_work, register_user


def run_verification():
    print("[1/5] Setting up temporary test environment and diverse works dataset...")
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = "http://trusted.test"
    os.environ["HANDRAW_PRIVATE_STORAGE"] = temp_dir.name

    db = None
    srv = None
    try:
        db = browser_postgres_database()

        author, _ = register_user(db, "demo_creator", "password123")

        # Define diverse works with varying ratios, styles, layouts, fusions, and freeform
        works_specs = [
            # Set 1: Style FA-013 with 3:4 portrait
            {"title": "水墨松林 1", "prompt": "晨雾水墨松树", "images": ["/images/individual/FA/FA-013.webp"], "styles": ["FA-013"], "ratio": "3:4"},
            # Set 2: Style FA-001 with 1:1 square
            {"title": "黑线练习 1", "prompt": "极简黑线构图", "images": ["/images/individual/FA/FA-001.webp"], "styles": ["FA-001"], "ratio": "1:1"},
            # Set 3: Layout SC-001 with 16:9 landscape
            {"title": "留白卡片 1", "prompt": "留白卡片版式", "images": ["/images/individual/SC/SC-001.webp"], "layout": "SC-001", "ratio": "16:9"},
            # Set 4: Style FA-014 with 9:16 tall portrait
            {"title": "高挑竹林", "prompt": "纵向高挑竹林", "images": ["/images/individual/FA/FA-014.webp"], "styles": ["FA-014"], "ratio": "9:16"},
            # Set 5: Freeform (no style, no layout) with 4:3
            {"title": "自由速写 A", "prompt": "生活速写", "images": ["/images/individual/FA/FA-013.webp"], "ratio": "4:3"},
            # Set 6: Dual-style fusion (FA-013 + FA-001)
            {"title": "水墨黑线交融", "prompt": "水墨与黑线交融构图", "images": ["/images/individual/FA/FA-013.webp"], "styles": ["FA-013", "FA-001"], "ratio": "1:1"},
            # Set 7: Style FA-015
            {"title": "青绿山水", "prompt": "青绿重彩水墨", "images": ["/images/individual/FA/FA-015.webp"], "styles": ["FA-015"], "ratio": "3:4"},
            # Set 8: Multi-image work (2 images with different ratios)
            {"title": "双联画作", "prompt": "对联与双幅作品", "images": ["/images/individual/FA/FA-014.webp", "/images/individual/SC/SC-001.webp"], "styles": ["FA-016"], "ratio": "16:9"},
            # Set 9: Layout SC-002
            {"title": "折角方块", "prompt": "折角版式", "images": ["/images/individual/SC/SC-002.webp"], "layout": "SC-002", "ratio": "1:1"},
            # Set 10: Freeform 2
            {"title": "自由速写 B", "prompt": "静物练习", "images": ["/images/individual/FA/FA-001.webp"], "ratio": "3:4"},
        ]

        # Repeat with unique titles to create 35 works (testing pagination & scrolling)
        for i in range(35):
            spec = dict(works_specs[i % len(works_specs)])
            spec["title"] = f"{spec['title']} #{i + 1}"
            publish_user_work(db, author, spec)

        print("[2/5] Starting test server on port 3097 (with fallback)...")
        port = 3097
        try:
            srv = create_channel_server(port, "main", db)
        except Exception:
            srv = create_channel_server(0, "main", db)
            port = srv.server_port
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        base_url = f"http://127.0.0.1:{port}"
        print(f"Test server running at {base_url}")

        print("[3/5] Launching Playwright browser...")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception:
                browser = pw.chromium.launch(channel="msedge", headless=True)

            # -------------------------------------------------------------
            # Test A: Desktop 1440 (1440x900)
            # -------------------------------------------------------------
            print("\n--- Testing Desktop 1440x900 ---")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda msg: print("CONSOLE:", msg.text))
            target_url = f"{base_url}/?view=works"
            page.goto(target_url, wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Assert masonry container exists and has 4 columns
            masonry = page.locator("#hw-wb-masonry")
            assert masonry.count() == 1, "Masonry container #hw-wb-masonry must exist"
            cols = page.locator(".hw-wb-col")
            assert cols.count() == 4, f"Desktop 1440 must have 4 columns, got {cols.count()}"

            # Assert non-equal card heights (true masonry)
            cards = page.locator(".hw-wb-card")
            card_count = cards.count()
            print(f"Initial rendered cards count: {card_count}")
            assert card_count >= 15, "Should have rendered initial cards"

            heights = []
            for i in range(min(10, card_count)):
                box = cards.nth(i).bounding_box()
                if box:
                    heights.append(box["height"])
            assert len(set(heights)) > 1, f"Cards must not be equal-height grid! Got heights: {heights}"
            print(f"[OK] True Masonry verified: card heights vary across items ({min(heights):.1f}px to {max(heights):.1f}px)")

            # Continuous scroll diversity assertion on Desktop
            total_height = page.evaluate("document.body.scrollHeight")
            step = 250
            print(f"Testing continuous scroll diversity from Y=0 to Y={total_height} (step={step})...")

            for scroll_y in range(0, int(total_height), step):
                page.evaluate(f"window.scrollTo(0, {scroll_y})")
                page.wait_for_timeout(50)

                # Retrieve all cards currently visible in the 900px viewport
                visible_cards = page.evaluate("""() => {
                    const V_H = window.innerHeight;
                    const cards = Array.from(document.querySelectorAll('.hw-wb-card'));
                    return cards.map(c => {
                        const rect = c.getBoundingClientRect();
                        const isVisible = rect.bottom > 0 && rect.top < V_H;
                        if (!isVisible) return null;
                        const wid = c.getAttribute('data-wb-work');
                        const work = (window.App && window.App.state && window.App.state.works || []).find(w => String(w.id) === wid);
                        const styles = (work && work.styles) || [];
                        const layout = (work && work.layout) || '';
                        const codes = [].concat(styles).concat(layout ? [layout] : []).map(s => String(s).toUpperCase().replace(/^#/, ''));
                        return { id: wid, codes: Array.from(new Set(codes)), top: rect.top, bottom: rect.bottom };
                    }).filter(Boolean);
                }""")

                # Assert: for any pair of visible cards with codes, codes两两无交集
                for i in range(len(visible_cards)):
                    for j in range(i + 1, len(visible_cards)):
                        c1 = visible_cards[i]
                        c2 = visible_cards[j]
                        shared = set(c1["codes"]).intersection(set(c2["codes"]))
                        assert not shared, (
                            f"At scroll Y={scroll_y}, viewport conflict detected between work {c1['id']} and {c2['id']}: "
                            f"shared resource codes {shared}! (c1: {c1['codes']} at {c1['top']:.0f}-{c1['bottom']:.0f}, "
                            f"c2: {c2['codes']} at {c2['top']:.0f}-{c2['bottom']:.0f})"
                        )

            print("[OK] Desktop 1440 scroll diversity verified: Every viewport window has ZERO overlapping styles/layouts!")

            # Screenshot Desktop
            Path("C:/tmp").mkdir(parents=True, exist_ok=True)
            desktop_shot = "C:/tmp/works_masonry_desktop.png"
            page.screenshot(path=desktop_shot)
            print(f"[OK] Saved desktop screenshot to {desktop_shot}")

            # -------------------------------------------------------------
            # Test B: Mobile 390 (390x844)
            # -------------------------------------------------------------
            print("\n--- Testing Mobile 390x844 ---")
            page_m = browser.new_page(viewport={"width": 390, "height": 844})
            page_m.goto(target_url, wait_until="networkidle")
            page_m.wait_for_timeout(1000)

            # Assert mobile has 2 columns
            cols_m = page_m.locator(".hw-wb-col")
            assert cols_m.count() == 2, f"Mobile 390 must have 2 columns, got {cols_m.count()}"

            total_height_m = page_m.evaluate("document.body.scrollHeight")
            print(f"Testing continuous scroll diversity on mobile from Y=0 to Y={total_height_m}...")
            for scroll_y in range(0, int(total_height_m), 250):
                page_m.evaluate(f"window.scrollTo(0, {scroll_y})")
                page_m.wait_for_timeout(50)

                visible_cards = page_m.evaluate("""() => {
                    const V_H = window.innerHeight;
                    const cards = Array.from(document.querySelectorAll('.hw-wb-card'));
                    return cards.map(c => {
                        const rect = c.getBoundingClientRect();
                        const isVisible = rect.bottom > 0 && rect.top < V_H;
                        if (!isVisible) return null;
                        const wid = c.getAttribute('data-wb-work');
                        const work = (window.App && window.App.state && window.App.state.works || []).find(w => String(w.id) === wid);
                        const styles = (work && work.styles) || [];
                        const layout = (work && work.layout) || '';
                        const codes = [].concat(styles).concat(layout ? [layout] : []).map(s => String(s).toUpperCase().replace(/^#/, ''));
                        return { id: wid, codes: Array.from(new Set(codes)), top: rect.top, bottom: rect.bottom };
                    }).filter(Boolean);
                }""")

                for i in range(len(visible_cards)):
                    for j in range(i + 1, len(visible_cards)):
                        c1 = visible_cards[i]
                        c2 = visible_cards[j]
                        shared = set(c1["codes"]).intersection(set(c2["codes"]))
                        assert not shared, (
                            f"Mobile scroll Y={scroll_y} conflict between {c1['id']} and {c2['id']}: shared {shared}"
                        )

            print("[OK] Mobile 390 scroll diversity verified: Every viewport window has ZERO overlapping styles/layouts!")
            mobile_shot = "C:/tmp/works_masonry_mobile.png"
            page_m.screenshot(path=mobile_shot)
            print(f"[OK] Saved mobile screenshot to {mobile_shot}")

            # Independent tablet context also reads the PostgreSQL-backed feed.
            page_t = browser.new_page(viewport={"width": 820, "height": 1180})
            page_t.goto(target_url, wait_until="networkidle")
            page_t.locator(".hw-wb-card").first.wait_for(state="visible")
            assert page_t.locator(".hw-wb-card").count() >= 24
            assert page_t.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page_t.screenshot(path="C:/tmp/works_masonry_tablet.png")
            print("[OK] Tablet 820 feed rendered without horizontal overflow")
            page_t.close()

            # -------------------------------------------------------------
            # Test C: Resize Stability & Scroll Anchor
            # -------------------------------------------------------------
            print("\n--- Testing Resize Stability & Scroll Anchor ---")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.evaluate("window.scrollTo(0, 500)")
            page.wait_for_timeout(200)

            anchor_info = page.evaluate("""() => {
                const cards = Array.from(document.querySelectorAll('.hw-wb-card'));
                for (const c of cards) {
                    const r = c.getBoundingClientRect();
                    if (r.bottom > 0 && r.top >= 0) {
                        return { key: c.getAttribute('data-wb-card-key') || c.getAttribute('data-wb-work'), top: r.top };
                    }
                }
                return null;
            }""")
            print(f"Anchor card before resize: {anchor_info}")
            assert anchor_info is not None

            # Resize width from 1440 to 390
            page.set_viewport_size({"width": 390, "height": 900})
            page.wait_for_timeout(500)

            # Check new columns
            assert page.locator(".hw-wb-col").count() == 2, "Columns should re-layout to 2"

            # Check anchor card position after resize
            new_top = page.evaluate(f"""(key) => {{
                const el = document.querySelector(`[data-wb-card-key="${{key}}"]`) || document.querySelector(`[data-wb-work="${{key}}"]`);
                return el ? el.getBoundingClientRect().top : null;
            }}""", anchor_info["key"])

            print(f"Anchor card top after resize: {new_top} (was {anchor_info['top']})")
            assert new_top is not None, "Anchor card must remain in DOM"
            assert 0 <= new_top < 900, f"Anchor card must remain visible in viewport! Got {new_top}"
            print("[OK] Resize scroll anchor verified: Position remained visible in viewport!")

            # -------------------------------------------------------------
            # Test D: Image Non-Recreation on Load More
            # -------------------------------------------------------------
            print("\n--- Testing Image Non-Recreation on Load More ---")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(target_url, wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Stamp all existing image DOM nodes
            initial_img_count = page.evaluate("""() => {
                const imgs = Array.from(document.querySelectorAll('.hw-wb-card img'));
                imgs.forEach((img, idx) => {
                    img.setAttribute('data-initial-index', String(idx));
                    img._loadCount = 1;
                });
                return imgs.length;
            }""")
            print(f"Existing stamped images: {initial_img_count}")

            # Click "加载更多" button
            more_btn = page.locator("#hw-wb-more")
            if more_btn.is_visible():
                more_btn.click()
                page.wait_for_timeout(1500)

                # Check that initial images were NOT destroyed or recreated
                preserved = page.evaluate(f"""() => {{
                    let intact = 0;
                    for (let i = 0; i < {initial_img_count}; i++) {{
                        const el = document.querySelector(`img[data-initial-index="${{i}}"]`);
                        if (el) intact++;
                    }}
                    const total = document.querySelectorAll('.hw-wb-card img').length;
                    return {{ intact, total }};
                }}""")
                print(f"Preserved initial images: {preserved['intact']}/{initial_img_count}, new total: {preserved['total']}")
                assert preserved["intact"] == initial_img_count, "All existing image DOM nodes must be preserved without recreation!"
                assert preserved["total"] > initial_img_count, "New cards should be appended"
                print("[OK] Existing cards preserved without recreation on load more!")

            browser.close()

        print("\n========================================================")
        print("ALL PLAYWRIGHT MASONRY & DIVERSITY ASSERTIONS PASSED!")
        print("========================================================")
    finally:
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_verification()
