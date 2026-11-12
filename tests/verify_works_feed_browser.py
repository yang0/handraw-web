"""End-to-end browser verification script for works feed admission and square layout."""
from __future__ import annotations

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
    print("[1/5] Setting up temporary test environment...")
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = "http://trusted.test"
    os.environ["HANDRAW_PRIVATE_STORAGE"] = temp_dir.name

    db = browser_postgres_database()

    author, _ = register_user(db, "demo_creator", "password123")

    # Insert work 1: normal with prompt
    publish_user_work(
        db,
        author,
        {
            "title": "晨光林间速写",
            "prompt": "晨光透过薄雾洒在松树林上，水墨质感",
            "images": ["/images/individual/FA/FA-013.webp"],
            "styles": ["FA-013"],
            "ratio": "3:4",
        },
    )

    # Insert work 2: EMPTY prompt (Issue #50 admission test)
    publish_user_work(
        db,
        author,
        {
            "title": "自由写意花卉（无提示词）",
            "prompt": "",
            "images": ["/images/individual/SC/SC-001.webp"],
            "layout": "SC-001",
            "ratio": "1:1",
        },
    )

    # Insert work 3: Multi-image work
    publish_user_work(
        db,
        author,
        {
            "title": "水墨山水连作",
            "prompt": "连环水墨图册",
            "images": ["/images/individual/FA/FA-013.webp", "/images/individual/SC/SC-001.webp"],
            "ratio": "16:9",
        },
    )

    print("[2/5] Starting ephemeral channel server...")
    srv = create_channel_server(0, "main", db)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{srv.server_port}"
    print(f"Ephemeral server running at {base_url}")

    print("[3/5] Launching Playwright browser...")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception:
            # Fall back to installed system edge on Windows
            browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        target_url = f"{base_url}/?view=works"
        print(f"Navigating to {target_url}...")
        page.goto(target_url, wait_until="networkidle")

        # Give client JS time to settle
        page.wait_for_timeout(1500)

        print("[4/5] Asserting DOM elements and text...")
        # Check header
        title_head = page.locator(".hw-wb-title-head").inner_text()
        assert "作品与做法" in title_head, f"Unexpected title: {title_head}"
        print(f"[OK] Header verified: {title_head}")

        # Check subtitle
        sub_text = page.locator(".hw-wb-sub").inner_text()
        assert "浏览社区公开作品" in sub_text, f"Unexpected subtitle: {sub_text}"
        assert "已收录" not in sub_text, "Found outdated '已收录' in subtitle!"
        assert "通过收录后展示" not in page.content(), "Found outdated '通过收录后展示' in page!"
        print(f"[OK] Subtitle verified: {sub_text}")

        # Check format tabs
        tabs = page.locator(".hw-wb-tab").all_inner_texts()
        print(f"[OK] Tabs found: {tabs}")
        assert any("全部作品" in t for t in tabs)

        # Check cards
        cards = page.locator(".hw-wb-card")
        card_count = cards.count()
        print(f"[OK] Rendered work cards count: {card_count}")
        assert card_count >= 3, f"Expected at least 3 cards, got {card_count}"

        # Verify freeform work without prompt is visible
        card_texts = [cards.nth(i).inner_text() for i in range(card_count)]
        assert any("自由写意花卉（无提示词）" in txt for txt in card_texts), "Freeform work without prompt was NOT displayed in works square!"
        print("[OK] Confirmed: Work without prompt appears in works square!")

        print("[5/5] Saving screenshot...")
        out_dir = Path("C:/tmp")
        out_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = out_dir / "works_feed_desktop.png"
        page.screenshot(path=str(screenshot_path))
        print(f"[OK] Screenshot saved to {screenshot_path}")

        browser.close()

    srv.shutdown()
    db.get_conn().close()
    db.close()
    temp_dir.cleanup()
    print("ALL BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_verification()
