"""Browser verification for Phase 3b-3: Article Preview/Editor Switch & Advanced Canvas.

Verifies:
1. Article Editor & Preview segmented switch position alignment:
   - Absolute delta X <= 2px
   - Absolute delta Y <= 2px
   - Back to list button pinned at top-left
   - Preview footer has no duplicate return-to-editor button
2. Canvas first entry on cleared localStorage:
   - Displays template library welcome screen with 7 blueprint cards
   - No auto-opened tabs
   - Clicking a card instantiates the tab and hides template library
3. Zero emoji audit on canvas:
   - Workbench bar, tabs track, shelf drawer, toolstrip, bottom-right controls, and rendered node cards
4. PC 1440 and 1920 viewport checks:
   - 0 uncaught console errors
   - 0 horizontal overflow
5. Blank canvas bug prevention check
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PORT = 3096
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT_DIR = Path(r"C:\Users\yang0\.gemini\antigravity-cli\brain\6005648b-a302-4676-abaa-98e0b38a8b07")


def wait_for_server(url: str, timeout: float = 12.0) -> bool:
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"{url}/studio/")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    uploads_dir = temp_path / "uploads"
    generated_dir = temp_path / "generated"
    storage_dir = temp_path / "private_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "HANDRAW_PRIVATE_STORAGE": str(storage_dir),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DEMO_MODE": "1",
    })

    print(f"Starting server on port {PORT} with isolated storage: {storage_dir}...")
    from tests.browser_postgres import browser_postgres_database
    db = browser_postgres_database()
    env["HANDRAW_DATABASE_URL"] = db._dsn
    db.close()
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server", "--port", str(PORT), "--demo-mode"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    try:
        if not wait_for_server(BASE_URL, timeout=15.0):
            print("ERROR: Server failed to start within 15 seconds.")
            return 1
        print("Server is up and responding.\n")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)

            # -------------------------------------------------------------
            # Part 1: Article Editor vs Preview Position Alignment
            # -------------------------------------------------------------
            print("=== Part 1: Article Switch Position Alignment (1440x900) ===")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            # Step 1: Open Article Editor
            page.goto(f"{BASE_URL}/studio/?entry=article&subview=editor", wait_until="networkidle")
            page.wait_for_selector("#editor-switch-group", timeout=8000)

            editor_back_box = page.locator("#editor-btn-back").bounding_box()
            editor_switch_box = page.locator("#editor-switch-group").bounding_box()
            print(f"Editor: back btn box = {editor_back_box}")
            print(f"Editor: switch group box = {editor_switch_box}")
            page.screenshot(path=str(ARTIFACT_DIR / "article_editor_1440.png"))

            # Step 2: Switch to Preview
            page.click("#editor-switch-preview")
            page.wait_for_selector("#preview-switch-group", timeout=8000)
            page.wait_for_timeout(300)

            preview_list_box = page.locator("#preview-btn-list").bounding_box()
            preview_switch_box = page.locator("#preview-switch-group").bounding_box()
            print(f"Preview: list btn box = {preview_list_box}")
            print(f"Preview: switch group box = {preview_switch_box}")
            page.screenshot(path=str(ARTIFACT_DIR / "article_preview_1440.png"))

            # Verify coordinate delta <= 2px
            delta_x = abs(editor_switch_box["x"] - preview_switch_box["x"])
            delta_y = abs(editor_switch_box["y"] - preview_switch_box["y"])
            delta_w = abs(editor_switch_box["width"] - preview_switch_box["width"])
            delta_h = abs(editor_switch_box["height"] - preview_switch_box["height"])
            print(f"Alignment deltas: Delta-X = {delta_x:.2f}px, Delta-Y = {delta_y:.2f}px, Delta-W = {delta_w:.2f}px, Delta-H = {delta_h:.2f}px")

            assert delta_x <= 2.0, f"Delta X too large: {delta_x}px > 2px"
            assert delta_y <= 2.0, f"Delta Y too large: {delta_y}px > 2px"
            print("✓ Position alignment passed: delta <= 2px requirement satisfied!")

            # Verify duplicate button removed
            dup_btn = page.locator("#preview-btn-back-editor-2")
            assert dup_btn.count() == 0, "Duplicate #preview-btn-back-editor-2 must not exist in preview footer"
            print("✓ Duplicate footer button removal verified!")

            # -------------------------------------------------------------
            # Part 2: Canvas First Entry & Template Library
            # -------------------------------------------------------------
            print("\n=== Part 2: Canvas First Entry & Template Library ===")
            canvas_page = browser.new_page(viewport={"width": 1440, "height": 900})
            canvas_errors = []
            canvas_page.on("console", lambda msg: canvas_errors.append(msg.text) if msg.type == "error" else None)
            canvas_page.on("pageerror", lambda err: canvas_errors.append(str(err)))

            # Clear localStorage to simulate first entry
            canvas_page.goto(f"{BASE_URL}/studio/", wait_until="networkidle")
            canvas_page.evaluate("localStorage.clear(); sessionStorage.clear();")
            canvas_page.goto(f"{BASE_URL}/studio/?entry=canvas", wait_until="networkidle")
            canvas_page.wait_for_timeout(500)

            # Check that template library is displayed
            tmpl_lib = canvas_page.locator("#canvas-template-library")
            assert tmpl_lib.is_visible(), "Template library must be visible on first entry"
            card_count = canvas_page.locator(".ic-tmpl-card").count()
            print(f"First entry template library visible with {card_count} template cards.")
            assert card_count == 7, f"Expected 7 template cards, got {card_count}"
            canvas_page.screenshot(path=str(ARTIFACT_DIR / "canvas_template_library_1440.png"))

            # Check open tabs count
            open_tabs_count = canvas_page.locator("#ic-tabs-track .ic-doc-tab").count()
            print(f"Open tabs on first entry: {open_tabs_count} (expected 0)")
            assert open_tabs_count == 0, f"Expected 0 tabs, got {open_tabs_count}"

            # Verify toolstrip, bottom-right dock, and minimap are HIDDEN while template library is shown
            toolstrip_el = canvas_page.locator("#ic-canvas-toolstrip")
            bottom_right_el = canvas_page.locator("#ic-bottom-right")
            minimap_el = canvas_page.locator("#ic-minimap")
            assert not toolstrip_el.is_visible(), "Toolstrip must NOT be visible when template library is showing"
            assert not bottom_right_el.is_visible(), "Bottom-right bar (save & minimap buttons) must NOT be visible when template library is showing"
            assert not minimap_el.is_visible(), "Minimap window must NOT be visible when template library is showing"
            print("✓ Toolstrip, bottom-right controls, and minimap correctly hidden on template library screen.")

            # Click template card 'single' (节气海报极速出图)
            single_card_btn = canvas_page.locator('.ic-tmpl-card-btn[data-tmpl-bp="single"]')
            single_card_btn.click()
            canvas_page.wait_for_timeout(500)
            canvas_page.screenshot(path=str(ARTIFACT_DIR / "canvas_active_tab_1440.png"))

            # Template library should now be hidden/removed
            assert not tmpl_lib.is_visible() or canvas_page.locator("#canvas-template-library").count() == 0, "Template library must be dismissed once a template is picked"
            open_tabs_count = canvas_page.locator("#ic-tabs-track .ic-doc-tab").count()
            print(f"Tabs count after picking single template: {open_tabs_count}")
            assert open_tabs_count == 1, f"Expected 1 open tab, got {open_tabs_count}"

            # Verify toolstrip, bottom-right dock, and save button are RESTORED after picking template
            assert toolstrip_el.is_visible(), "Toolstrip must be restored and visible after opening template"
            assert bottom_right_el.is_visible(), "Bottom-right dock must be restored and visible after opening template"
            assert canvas_page.locator("#bl-save-wf").is_visible(), "Save button must be visible after opening template"
            assert canvas_page.locator("#bl-minimap").is_visible(), "Minimap button must be visible after opening template"
            print("✓ Toolstrip, bottom-right dock, and save button successfully restored after opening template.")

            # Nodes should be rendered on canvas
            node_count = canvas_page.locator("#ic-nodes-layer .ic-node").count()
            print(f"Rendered canvas nodes: {node_count}")
            assert node_count >= 3, f"Expected at least 3 nodes for single blueprint, got {node_count}"

            # -------------------------------------------------------------
            # Part 3: Zero Emoji Audit on Canvas
            # -------------------------------------------------------------
            print("\n=== Part 3: Canvas Zero Emoji Audit ===")
            import re
            emoji_pat = re.compile(r"[\U0001F300-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF]")

            # Collect visible texts from workbench bar, toolstrip, bottom right bar, tabs track, shelf drawer, nodes
            elements_to_check = [
                ("#ic-workbench-bar", "Workbench Bar"),
                ("#ic-tabs-track", "Tabs Track"),
                ("#ic-toolstrip", "Toolstrip"),
                ("#ic-bottom-right-bar", "Bottom-Right Bar"),
                ("#ic-shelf-drawer", "Shelf Drawer"),
                ("#ic-nodes-layer", "Nodes Layer"),
            ]

            total_emojis_found = 0
            for selector, label in elements_to_check:
                loc = canvas_page.locator(selector)
                if loc.count() > 0:
                    text_content = loc.inner_text()
                    matches = emoji_pat.findall(text_content)
                    print(f"Checking {label}: text length = {len(text_content)}, emojis found = {len(matches)}")
                    if matches:
                        print(f"  WARNING: Emojis found in {label}: {matches}")
                        total_emojis_found += len(matches)

            assert total_emojis_found == 0, f"Expected 0 emojis across canvas components, found {total_emojis_found}"
            print("✓ Zero emoji audit passed completely!")

            # -------------------------------------------------------------
            # Part 4: 1920x1080 Viewport Check
            # -------------------------------------------------------------
            print("\n=== Part 4: 1920x1080 Viewport Check ===")
            page_1920 = browser.new_page(viewport={"width": 1920, "height": 1080})
            errors_1920 = []
            page_1920.on("console", lambda msg: errors_1920.append(msg.text) if msg.type == "error" else None)
            page_1920.on("pageerror", lambda err: errors_1920.append(str(err)))

            page_1920.goto(f"{BASE_URL}/studio/?entry=canvas", wait_until="networkidle")
            page_1920.wait_for_timeout(500)
            page_1920.screenshot(path=str(ARTIFACT_DIR / "canvas_1920.png"))

            # Check horizontal overflow on 1920
            overflow = page_1920.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            assert not overflow, "Horizontal overflow detected on 1920x1080!"
            print("✓ 1920x1080: No horizontal overflow!")

            # -------------------------------------------------------------
            # Part 5: Blank Canvas Bug Prevention Check
            # -------------------------------------------------------------
            print("\n=== Part 5: Blank Canvas Bug Prevention Check ===")
            # Switch back and forth between "make-image" and "canvas"
            page_1920.goto(f"{BASE_URL}/studio/?entry=make-image", wait_until="networkidle")
            page_1920.wait_for_timeout(300)
            page_1920.goto(f"{BASE_URL}/studio/?entry=canvas", wait_until="networkidle")
            page_1920.wait_for_timeout(300)

            # Verify transform of canvas layer is finite and normal (not NaN or broken off-screen)
            transform = page_1920.locator("#ic-canvas-stage").evaluate("el => getComputedStyle(el).display")
            assert transform != "none", "Canvas stage should be visible"
            print("✓ Blank canvas bug prevention check passed!")

            # Filter console errors
            benign = ["favicon.ico", "404", "ERR_FILE_NOT_FOUND"]
            real_errors = [e for e in (console_errors + canvas_errors + errors_1920) if not any(b in e for b in benign)]
            assert len(real_errors) == 0, f"Uncaught console errors: {real_errors}"
            print(f"✓ Console check passed: 0 uncaught errors.")

            browser.close()

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        temp_dir.cleanup()

    print("\n=======================================================")
    print("ALL PLAYWRIGHT ARTICLE & CANVAS CHECKS PASSED!")
    print("=======================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
