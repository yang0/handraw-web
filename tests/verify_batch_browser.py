"""Browser verification for Phase 3b-4 Redesign: Studio Batch Set Planning.

Tests:
1. 1440x900 desktop:
   - 0 uncaught console errors
   - 0 horizontal overflow
   - Row 1: 生成方式 -> 画风模式 (批量方式 buttons removed)
   - Fixed layout mode:
     - Row A (母题 + 张数 + 策略 + 规划按钮)
     - Row B (选择图型 + 图型卡)
     - Edit area (single promptListText textarea)
     - Screenshot: batch_1440_fixed.png
   - AI recommended layout mode:
     - Row B (图型要求文本框)
     - Edit area (row-by-row table with #, theme input, layout select, delete, add row button)
     - Screenshot: batch_1440_ai_recommended.png
   - Planning action:
     - Click AI 规划这套图 -> populates items into editing table
     - Screenshot: batch_1440_planned.png
2. 390x844 mobile:
   - 0 uncaught console errors
   - 0 horizontal overflow
   - Responsive layout in both fixed and AI recommended modes
   - Screenshots: batch_390_fixed.png, batch_390_ai_recommended.png
3. Defect 4 verification:
   - Reload /studio/?entry=batch 3 times, verify batch tab is reused and no extra tabs created.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

PORT = 3097
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
    db_path = temp_path / "browser_batch_test.db"
    uploads_dir = temp_path / "uploads"
    generated_dir = temp_path / "generated"
    storage_dir = temp_path / "private_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "HANDRAW_PRIVATE_STORAGE": str(storage_dir),
        "HANDRAW_DB_PATH": str(db_path),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DEMO_MODE": "1",
        "HANDRAW_ENABLE_RECHARGE": "0",
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT},http://localhost:{PORT}",
    })

    from backend.server import SESSION_COOKIE_NAME, init_database
    from backend.services import register_user

    init_db = init_database(db_path)
    user, session_token = register_user(init_db, "batch_tester", "Pass123456")
    init_db.close()

    server_proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server", "--port", str(PORT), "--demo-mode", "--db", str(db_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        print(f"Waiting for studio server on port {PORT}...")
        if not wait_for_server(BASE_URL, timeout=12.0):
            print("ERROR: Server failed to start in time.")
            return 1
        print("Studio server is up and running.")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)

            # -------------------------------------------------------------
            # Pass 1: Desktop 1440x900
            # -------------------------------------------------------------
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            page = context.new_page()

            console_errors = []
            all_dialogs = []
            page.on("console", lambda msg: (print("CONSOLE:", msg.text), console_errors.append(msg.text) if msg.type == "error" else None))
            page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
            page.on("dialog", lambda dialog: (all_dialogs.append(dialog.message), dialog.accept()))
            page.on("request", lambda r: print("REQ:", r.url, r.post_data) if "batch-plan" in r.url else None)
            page.on("response", lambda r: print("RESP:", r.url, r.status, r.text()) if "batch-plan" in r.url else None)

            print("Navigating to Desktop 1440 /studio/?entry=batch&demo_mode=1...")
            page.goto(f"{BASE_URL}/studio/?entry=batch&demo_mode=1", wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Verify no console errors
            ignorable = ("favicon", "net::err_aborted")
            real_errors = [e for e in console_errors if not any(x in e.lower() for x in ignorable)]
            if real_errors:
                print(f"FAILED: Console errors encountered: {real_errors}")
                return 1
            print("PASS: 0 console errors on desktop load.")

            # Verify horizontal scroll
            has_h_scroll = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth")
            if has_h_scroll:
                print("FAILED: Horizontal overflow detected on 1440 desktop!")
                return 1
            print("PASS: No horizontal overflow on 1440 desktop.")

            # Verify Row 1: 生成方式 -> 画风模式
            row1_text = page.locator(".batch-top-row").inner_text()
            assert "生成方式" in row1_text and "画风模式" in row1_text, "Row 1 must contain 生成方式 and 画风模式"
            assert "批量方式" not in row1_text, "Old 批量方式 must not exist in Row 1"
            assert row1_text.find("生成方式") < row1_text.find("画风模式"), "生成方式 must appear before 画风模式"
            print("PASS: Row 1 groups and order verified.")

            # Fixed layout mode checks
            assert page.locator("#batch-strategy-fixed.is-active").is_visible(), "Fixed strategy should be active initially"
            assert page.locator("#batch-btn-pick-fixed-layout").is_visible(), "Fixed layout picker button must be visible in Row B"
            assert page.locator("#batch-prompts-input").is_visible(), "Textarea must be visible in Fixed edit area"
            assert not page.locator(".batch-edit-table").is_visible(), "Row table must not be visible in Fixed layout mode"

            # Scenario 1: Fixed mode without selecting layout -> Click AI 规划这套图
            print("Verifying Scenario 1: Fixed mode without selecting layout can plan successfully...")
            page.fill("#batch-seed-input", "都市慢生活与手绘手账")
            page.wait_for_timeout(300)
            page.click("#batch-btn-plan")
            page.wait_for_timeout(1200)

            # Assert planning succeeded with default layout
            plan_text = page.locator("#batch-prompts-input").input_value()
            assert len(plan_text.strip()) > 0, "Fixed layout promptListText must be populated"
            notice_el = page.locator(".batch-plan-notice")
            assert notice_el.is_visible(), "Plan notice must be visible"
            notice_text = notice_el.inner_text()
            assert "未选图型，已使用默认图型" in notice_text, f"Notice must mention default layout: {notice_text}"
            assert page.locator(".batch-fixed-layout-card-wrap .make-image-slot-badge").is_visible(), "Layout card badge must be visible with default code"
            print(f"PASS Scenario 1: Plan notice verified: {notice_text}")

            shot1 = ARTIFACT_DIR / "batch_1440_fixed.png"
            page.screenshot(path=str(shot1), full_page=False)
            print(f"Captured screenshot: {shot1}")

            # Scenario 2: Tone and mood pickers open modal
            print("Verifying Scenario 2: Tone and Mood pickers open modal...")
            page.click("#batch-toggle-more-settings")
            page.wait_for_timeout(300)
            assert page.locator("#batch-body-more-settings").is_visible(), "More settings body must expand"

            page.click("#batch-btn-pick-tones")
            page.wait_for_timeout(400)
            assert page.locator("#hw-active-modal, .hw-modal-panel, [role='dialog']").count() > 0, "Tone picker modal must open"
            page.evaluate("() => window.HANDRAW_SHARED?.closeModal()")
            page.wait_for_timeout(300)

            page.click("#batch-btn-pick-moods")
            page.wait_for_timeout(400)
            assert page.locator("#hw-active-modal, .hw-modal-panel, [role='dialog']").count() > 0, "Mood picker modal must open"
            page.evaluate("() => window.HANDRAW_SHARED?.closeModal()")
            page.wait_for_timeout(300)
            print("PASS Scenario 2: Tone and Mood pickers open modal successfully.")

            # Switch to AI Recommended Layout mode
            page.click("#batch-strategy-ai")
            page.wait_for_timeout(500)

            assert page.locator("#batch-strategy-ai.is-active").is_visible(), "AI strategy should be active"
            assert page.locator("#batch-layout-req-input").is_visible(), "Layout requirement input must be visible in Row B"
            assert page.locator(".batch-edit-table").is_visible(), "Row table must be visible in AI mode"
            assert page.locator("#batch-btn-add-row").is_visible(), "Add row button must be visible"

            # Trigger AI Planning in AI mode
            print("Clicking AI 规划这套图 in AI mode...")
            page.click("#batch-btn-plan")
            page.wait_for_timeout(1200)

            # Check that table has planned rows and template notice is displayed
            row_count = page.locator(".batch-edit-row").count()
            print(f"Planned row count: {row_count}")
            assert row_count >= 1, "Planned rows must be populated into table"
            assert page.locator(".batch-plan-notice").is_visible(), "Template fallback notice must be visible"

            # Scenario 3: Row-by-row layout picker & preview lightbox actions
            print("Verifying Scenario 3: Row-by-row layout picker & preview lightbox actions...")
            layout_btn = page.locator(".batch-row-layout-btn[data-pick-layout-idx='0']")
            assert layout_btn.is_visible(), "Row 0 layout button must be visible"
            thumb_img = layout_btn.locator("img.batch-row-layout-thumb")
            assert thumb_img.is_visible(), "Row 0 layout button must contain thumbnail image"
            assert thumb_img.get_attribute("data-hw-src"), "Thumbnail image must have data-hw-src"

            # Click layout button -> shared picker modal opens
            print("Clicking row 0 layout button...")
            layout_btn.click()
            page.wait_for_timeout(600)

            modal_title = page.locator(".hw-modal-header h2, .hw-modal-header h3, #hw-modal-title, .hw-modal-title").first.inner_text()
            print(f"Opened layout picker modal with title: {modal_title}")
            assert "图型" in modal_title or "📐" in modal_title, f"Modal title should indicate layout picker: {modal_title}"
            assert page.locator("#sp-picker-search").is_visible(), "Search input must be visible in picker modal"
            assert page.locator("#sp-picker-rand").is_visible(), "Random pick button must be visible in picker modal"
            assert page.locator(".ic-picker-card").count() > 0, "Resource cards must be visible in picker modal"

            shot_picker = ARTIFACT_DIR / "batch_1440_layout_picker.png"
            page.screenshot(path=str(shot_picker), full_page=False)
            print(f"Captured screenshot: {shot_picker}")

            # Pick a layout card (e.g. SC-002 or first card with different ID)
            target_card = page.locator(".ic-picker-card[data-pick-id='SC-002']")
            if target_card.count() == 0:
                target_card = page.locator(".ic-picker-card").first
            picked_id = target_card.get_attribute("data-pick-id")
            print(f"Picking card {picked_id} in modal...")
            target_card.click()
            page.wait_for_timeout(600)

            # Modal must close and row 0 layout button must reflect picked layout
            assert page.locator("#hw-active-modal, .hw-modal-panel").count() == 0 or not page.locator(".hw-modal-panel").is_visible(), "Modal must close on card pick"
            updated_code = page.locator(".batch-row-layout-btn[data-pick-layout-idx='0'] .batch-row-layout-code").inner_text()
            assert updated_code == picked_id, f"Row 0 layout code must be updated to {picked_id}, got {updated_code}"
            print(f"PASS: Layout picker selected {picked_id} and updated row 0.")

            # Batch preview table thumbnail zoom (Lightbox)
            print("Verifying batch iteration thumbnail zoom button...")
            iter_thumb_btn = page.locator(".batch-iter-thumb-btn").first
            assert iter_thumb_btn.is_visible(), "Iteration thumbnail zoom button must be visible"
            zoom_src = iter_thumb_btn.get_attribute("data-zoom-src")
            zoom_title = iter_thumb_btn.get_attribute("data-zoom-title")
            assert zoom_src, "Zoom button must have data-zoom-src"
            print(f"Zoom button attributes: title='{zoom_title}', src='{zoom_src}'")

            # Check computed size of thumbnail on desktop: 56x42
            thumb_box = page.locator(".batch-iter-thumb").first.bounding_box()
            assert thumb_box and round(thumb_box["width"]) == 56 and round(thumb_box["height"]) == 42, f"Desktop thumb size should be 56x42, got {thumb_box}"
            print("PASS: Iteration thumbnail size is 56x42 on desktop.")

            # Click thumbnail zoom button to open lightbox
            iter_thumb_btn.click()
            page.wait_for_timeout(600)

            lightbox_modal = page.locator(".hw-modal-panel")
            assert lightbox_modal.is_visible(), "Lightbox modal must be visible on clicking thumb"
            lightbox_title = page.locator(".hw-modal-header h2, .hw-modal-header h3, #hw-modal-title, .hw-modal-title").first.inner_text()
            assert "🔍" in lightbox_title or zoom_title in lightbox_title, f"Lightbox title mismatch: {lightbox_title}"
            assert page.locator(".hw-modal-panel img").is_visible(), "Lightbox image must be visible"

            shot_lightbox = ARTIFACT_DIR / "batch_1440_lightbox.png"
            page.screenshot(path=str(shot_lightbox), full_page=False)
            print(f"Captured screenshot: {shot_lightbox}")

            # Close lightbox modal
            page.evaluate("() => window.HANDRAW_SHARED?.closeModal()")
            page.wait_for_timeout(300)
            print("PASS Scenario 3: Shared layout picker and lightbox zoom verified.")

            shot2 = ARTIFACT_DIR / "batch_1440_ai_recommended.png"
            page.screenshot(path=str(shot2), full_page=False)
            print(f"Captured screenshot: {shot2}")

            shot3 = ARTIFACT_DIR / "batch_1440_planned.png"
            page.screenshot(path=str(shot3), full_page=False)
            print(f"Captured screenshot: {shot3}")

            # Scenario 4: 21 images only pops confirm once
            print("Verifying Scenario 4: 21 images only pops confirm once...")
            page.click("#batch-strategy-fixed")
            page.wait_for_timeout(500)

            prompts_el = page.locator("#batch-prompts-input")
            assert prompts_el.is_visible(), "Prompts textarea must be visible in fixed mode"
            lines21 = "\n".join(f"手绘慢生活系列第 {i+1} 篇" for i in range(21))
            page.fill("#batch-prompts-input", lines21)
            page.wait_for_timeout(500)

            btn_start = page.locator("#batch-btn-start")
            assert btn_start.is_visible() and not btn_start.is_disabled(), "Start button must be visible and enabled"

            dialog_start_idx = len(all_dialogs)
            page.evaluate("() => document.querySelector('#batch-btn-start')?.click()")
            page.wait_for_timeout(1000)
            dialog_records = all_dialogs[dialog_start_idx:]

            assert len(dialog_records) == 1, f"Expected exactly 1 confirmation dialog, got {len(dialog_records)}: {dialog_records}"
            assert "21 张" in dialog_records[0] and "超过20张" in dialog_records[0], f"Confirmation dialog text missing required elements: {dialog_records[0]}"
            print(f"PASS Scenario 4: Exactly 1 confirmation dialog popped: {dialog_records[0]}")

            context.close()

            # -------------------------------------------------------------
            # Pass 2: Mobile 390x844
            # -------------------------------------------------------------
            context_mob = browser.new_context(viewport={"width": 390, "height": 844})
            page_mob = context_mob.new_page()

            console_errors_mob = []
            page_mob.on("console", lambda msg: console_errors_mob.append(msg.text) if msg.type == "error" else None)
            page_mob.on("pageerror", lambda err: console_errors_mob.append(f"PAGEERROR: {err}"))

            print("Navigating to Mobile 390 /studio/?entry=batch...")
            page_mob.goto(f"{BASE_URL}/studio/?entry=batch", wait_until="networkidle")
            page_mob.wait_for_timeout(1000)

            real_errors_mob = [e for e in console_errors_mob if not any(x in e.lower() for x in ignorable)]
            if real_errors_mob:
                print(f"FAILED: Mobile console errors encountered: {real_errors_mob}")
                return 1
            print("PASS: 0 console errors on mobile load.")

            has_h_scroll_mob = page_mob.evaluate("() => document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth")
            if has_h_scroll_mob:
                scroll_w = page_mob.evaluate("() => document.body.scrollWidth")
                inner_w = page_mob.evaluate("() => window.innerWidth")
                print(f"FAILED: Horizontal overflow detected on 390 mobile! scrollWidth={scroll_w}, innerWidth={inner_w}")
                return 1
            print("PASS: No horizontal overflow on 390 mobile.")

            shot4 = ARTIFACT_DIR / "batch_390_fixed.png"
            page_mob.screenshot(path=str(shot4), full_page=False)
            print(f"Captured screenshot: {shot4}")

            # Mobile switch to AI recommended mode
            page_mob.click("#batch-strategy-ai")
            page_mob.wait_for_timeout(500)

            has_h_scroll_mob_ai = page_mob.evaluate("() => document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth")
            if has_h_scroll_mob_ai:
                scroll_w = page_mob.evaluate("() => document.body.scrollWidth")
                inner_w = page_mob.evaluate("() => window.innerWidth")
                print(f"FAILED: Horizontal overflow detected on 390 mobile in AI mode! scrollWidth={scroll_w}, innerWidth={inner_w}")
                return 1

            if page_mob.locator(".batch-iter-thumb").count() > 0:
                thumb_box_mob = page_mob.locator(".batch-iter-thumb").first.bounding_box()
                if thumb_box_mob:
                    print(f"Mobile thumbnail size: {thumb_box_mob['width']}x{thumb_box_mob['height']}")
                    assert round(thumb_box_mob["width"]) == 48 and round(thumb_box_mob["height"]) == 36, f"Mobile thumb size should be 48x36, got {thumb_box_mob}"
                    print("PASS: Iteration thumbnail size is 48x36 on mobile.")

            shot5 = ARTIFACT_DIR / "batch_390_ai_recommended.png"
            page_mob.screenshot(path=str(shot5), full_page=False)
            print(f"Captured screenshot: {shot5}")

            context_mob.close()

            # -------------------------------------------------------------
            # Pass 3: Tab Refresh Defect 4 Verification
            # -------------------------------------------------------------
            print("Verifying Defect 4: Tab refresh does not create duplicate tabs...")
            context_refresh = browser.new_context(viewport={"width": 1440, "height": 900})
            page_ref = context_refresh.new_page()
            page_ref.goto(f"{BASE_URL}/studio/?entry=batch", wait_until="networkidle")
            page_ref.wait_for_timeout(800)

            initial_tab_count = page_ref.locator(".ic-doc-tab").count()
            assert initial_tab_count == 1, f"Expected 1 initial tab, got {initial_tab_count}"
            # Refresh 3 times
            for r in range(3):
                page_ref.reload(wait_until="networkidle")
                page_ref.wait_for_timeout(600)
                cur_tab_count = page_ref.locator(".ic-doc-tab").count()
                assert cur_tab_count == 1, f"Reload {r+1} created duplicate tab: {cur_tab_count} vs 1"

            print(f"PASS: Defect 4 verified. Tab count remained 1 after 3 consecutive reloads.")
            context_refresh.close()
            browser.close()

        print("\nAll browser verification checks passed successfully!")
        return 0

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except Exception:
            server_proc.kill()
            try:
                server_proc.wait(timeout=2)
            except Exception:
                pass
        time.sleep(0.5)
        try:
            temp_dir.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
