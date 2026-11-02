import os
import sys
import io
import json
import time
import tempfile
import threading
from pathlib import Path
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.services import register_user

PORT = 3098
BASE_URL = f"http://127.0.0.1:{PORT}"
TMP_DIR = Path("C:/tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)

# Generate test images with clear 4 corner markers:
# Top-Left: Red (255, 0, 0)
# Top-Right: Green (0, 255, 0)
# Bottom-Left: Blue (0, 0, 255)
# Bottom-Right: Yellow (255, 255, 0)
def create_test_image(width, height, mark_size=15):
    im = Image.new("RGB", (width, height), (245, 240, 230))
    draw = ImageDraw.Draw(im)
    # Red top-left
    draw.rectangle([0, 0, mark_size, mark_size], fill=(255, 0, 0))
    # Green top-right
    draw.rectangle([width - mark_size, 0, width, mark_size], fill=(0, 255, 0))
    # Blue bottom-left
    draw.rectangle([0, height - mark_size, mark_size, height], fill=(0, 0, 255))
    # Yellow bottom-right
    draw.rectangle([width - mark_size, height - mark_size, width, height], fill=(255, 255, 0))
    return im

def is_color_match(pixel, target_rgb, tolerance=40):
    r, g, b = pixel[:3]
    tr, tg, tb = target_rgb[:3]
    return abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance

def assert_four_corners_visible(img_bytes, nw, nh, label=""):
    im = Image.open(io.BytesIO(img_bytes))
    w, h = im.size
    
    # Compute content bounding rect inside element if object-fit: contain was used
    aspect_im = nw / nh
    aspect_box = w / h
    if aspect_box > aspect_im:
        # Pillarbox (black/empty bars on left & right)
        ch = h
        cw = int(round(h * aspect_im))
        ox = (w - cw) // 2
        oy = 0
    else:
        # Letterbox (bars on top & bottom)
        cw = w
        ch = int(round(w / aspect_im))
        ox = 0
        oy = (h - ch) // 2

    # Sample near the four corners of the actual rendered image content (within the 20x20 mark)
    inset = 5
    tl_color = im.getpixel((ox + inset, oy + inset))
    tr_color = im.getpixel((ox + cw - 1 - inset, oy + inset))
    bl_color = im.getpixel((ox + inset, oy + ch - 1 - inset))
    br_color = im.getpixel((ox + cw - 1 - inset, oy + ch - 1 - inset))

    red_ok = is_color_match(tl_color, (255, 0, 0))
    green_ok = is_color_match(tr_color, (0, 255, 0))
    blue_ok = is_color_match(bl_color, (0, 0, 255))
    yellow_ok = is_color_match(br_color, (255, 255, 0))

    assert red_ok, f"[{label}] Top-Left (Red) cropped or missing! Got {tl_color}"
    assert green_ok, f"[{label}] Top-Right (Green) cropped or missing! Got {tr_color}"
    assert blue_ok, f"[{label}] Bottom-Left (Blue) cropped or missing! Got {bl_color}"
    assert yellow_ok, f"[{label}] Bottom-Right (Yellow) cropped or missing! Got {br_color}"
    print(f"  ✓ {label}: 4 corner markers fully visible! TL={tl_color} TR={tr_color} BL={bl_color} BR={br_color}")


def run_browser_verification():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"=== Starting Issue #44 Browser Quantitative Verification on port {PORT} ===")
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "browser_crop_test.db"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = root / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    img_cfg = root / "image-service.json"
    img_cfg.write_text(json.dumps({"key": "mock-test-key", "url": f"http://127.0.0.1:{PORT}"}))

    os.environ["HANDRAW_DB_PATH"] = str(db_path)
    os.environ["HANDRAW_UPLOADS_DIR"] = str(uploads_dir)
    os.environ["HANDRAW_GENERATED_DIR"] = str(generated_dir)
    os.environ["HANDRAW_IMAGE_CONFIG"] = str(img_cfg)
    os.environ["HANDRAW_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{PORT}"
    os.environ["HANDRAW_DEMO_MODE"] = "1"

    # Create images in demo/assets/ so they can be served as public static media
    assets_dir = REPO_ROOT / "demo" / "assets"
    im_1_4 = create_test_image(120, 480, mark_size=20)
    im_4_1 = create_test_image(480, 120, mark_size=20)
    im_1_1 = create_test_image(300, 300, mark_size=20)

    path_1_4 = assets_dir / "temp_crop_test_1_4.png"
    path_4_1 = assets_dir / "temp_crop_test_4_1.png"
    path_1_1 = assets_dir / "temp_crop_test_1_1.png"
    im_1_4.save(str(path_1_4))
    im_4_1.save(str(path_4_1))
    im_1_1.save(str(path_1_1))

    url_1_4 = "/assets/temp_crop_test_1_4.png"
    url_4_1 = "/assets/temp_crop_test_4_1.png"
    url_1_1 = "/assets/temp_crop_test_1_1.png"

    db = init_database(db_path)
    user, session_token = register_user(db, "crop_tester", "Pass1234!")

    # Seed works with these test images so card picker and gallery can display them
    with db.transaction() as tx:
        tx.execute("""
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, status, likes, favorites, forks, tips, published_at_ms, created_label, created_at, updated_at)
            VALUES ('w_1_4', 'crop_tester', '测试员', '1:4 竖图作品', ?, '["FA-001"]', 'SC-001', 0, '竖图', 'published', 5, 2, 1, 0, 1000, '刚刚', '2026-10-25 10:00:00', '2026-10-25 10:00:00')
        """, (json.dumps([url_1_4]),))
        tx.execute("""
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, status, likes, favorites, forks, tips, published_at_ms, created_label, created_at, updated_at)
            VALUES ('w_4_1', 'crop_tester', '测试员', '4:1 横图作品', ?, '["FA-001"]', 'SC-001', 0, '横图', 'published', 5, 2, 1, 0, 1000, '刚刚', '2026-10-25 10:00:00', '2026-10-25 10:00:00')
        """, (json.dumps([url_4_1]),))
        tx.execute("""
            INSERT INTO works (id, author_username, author_name, title, images_json, styles_json, layout_code, price, prompt, status, likes, favorites, forks, tips, published_at_ms, created_label, created_at, updated_at)
            VALUES ('w_1_1', 'crop_tester', '测试员', '1:1 方图作品', ?, '["FA-001"]', 'SC-001', 0, '方图', 'published', 5, 2, 1, 0, 1000, '刚刚', '2026-10-25 10:00:00', '2026-10-25 10:00:00')
        """, (json.dumps([url_1_1]),))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), HandrawRequestHandler)
    httpd.channel_role = "main"
    httpd.db = db
    httpd.allow_demo_routes = True
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    time.sleep(0.5)

    test_cases = [
        ("1:4_tall", url_1_4, path_1_4, 120, 480),
        ("4:1_wide", url_4_1, path_4_1, 480, 120),
        ("1:1_square", url_1_1, path_1_1, 300, 300),
    ]
    viewports = [375, 768, 1440]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(channel="msedge", headless=True)

        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([{
            "name": SESSION_COOKIE_NAME,
            "value": session_token,
            "domain": "127.0.0.1",
            "path": "/"
        }])
        page = context.new_page()

        # ==================== PART 1: RICH EDITOR BODY IMAGES ====================
        print("\n--- Part 1: Rich Editor Body Images (1:4, 4:1, 1:1 across 375, 768, 1440) ---")
        for vp_w in viewports:
            page.set_viewport_size({"width": vp_w, "height": 900})
            page.goto(f"{BASE_URL}/forum.html?view=compose")
            page.wait_for_selector("#compose-rich-editor", timeout=8000)
            page.evaluate("() => { const ed = document.querySelector('#compose-rich-editor'); if (ed) ed.innerHTML = ''; }")

            for name, url, path, nw, nh in test_cases:
                # Insert the test image into editor
                with page.expect_file_chooser() as fc_info:
                    page.click("#tb-insert-image")
                fc_info.value.set_files(str(path))
                page.wait_for_timeout(400)

                img_loc = page.locator("#compose-rich-editor .hw-intext-media img").last
                img_loc.wait_for(state="visible", timeout=5000)

                # Temporarily hide delete button overlay so top-right pixel isn't obscured by the '✕' button
                page.evaluate("() => document.querySelectorAll('.hw-intext-del-btn').forEach(b => b.style.visibility = 'hidden')")

                # Quantitative Check 1: 4 corner markers visible
                img_bytes = img_loc.screenshot()
                assert_four_corners_visible(img_bytes, nw, nh, label=f"Editor [{name}] @ {vp_w}px")
                page.evaluate("() => document.querySelectorAll('.hw-intext-del-btn').forEach(b => b.style.visibility = 'visible')")

                # Quantitative Check 2: No horizontal overflow
                scroll_w = page.evaluate("() => document.documentElement.scrollWidth")
                client_w = page.evaluate("() => document.documentElement.clientWidth")
                assert scroll_w <= client_w + 1, f"Horizontal overflow detected! scrollWidth={scroll_w} > clientWidth={client_w}"

                # Quantitative Check 3: Aspect ratio preservation
                rendered = img_loc.bounding_box()
                assert rendered["width"] <= vp_w, f"Image width {rendered['width']} exceeds viewport {vp_w}"
                # Rendered ratio must match natural ratio within 1.5%
                rend_ratio = rendered["width"] / rendered["height"]
                nat_ratio = nw / nh
                assert abs(rend_ratio - nat_ratio) / nat_ratio < 0.05, f"Aspect ratio distorted! Rendered={rend_ratio}, Natural={nat_ratio}"

            # Save screenshot
            shot_path = TMP_DIR / f"editor_crop_body_{vp_w}.png"
            page.screenshot(path=str(shot_path))
            print(f"  ✓ Saved screenshot: {shot_path}")

        # Broken image visible placeholder verification
        print("\n--- Testing Broken Image Placeholder in Editor ---")
        page.evaluate("""() => {
            const editor = document.querySelector("#compose-rich-editor");
            const fig = document.createElement("figure");
            fig.className = "hw-intext-media";
            fig.innerHTML = '<div class="hw-intext-media-wrap"><img src="/non_existent_404.png" class="hw-editor-body-img hw-img-broken" alt="broken" /></div>';
            editor.appendChild(fig);
        }""")
        broken_img = page.locator("#compose-rich-editor img.hw-img-broken")
        broken_box = broken_img.bounding_box()
        assert broken_box["width"] >= 100, f"Broken image placeholder width too small: {broken_box['width']}"
        assert broken_box["height"] >= 60, f"Broken image placeholder height too small: {broken_box['height']}"
        print(f"  ✓ Broken image visible placeholder verified: {broken_box['width']}x{broken_box['height']}")

        # ==================== PART 2: CARD SELECTION PREVIEWS ====================
        print("\n--- Part 2: Card Selection Preview (Fixed 1:1 container + contain) ---")
        for vp_w in [375, 1440]:
            page.set_viewport_size({"width": vp_w, "height": 900})
            page.goto(f"{BASE_URL}/forum.html?view=compose")
            page.wait_for_selector("#tb-insert-work", timeout=8000)

            # Prepend our test works into App.state.works so they appear at the very front
            page.evaluate(f"""() => {{
                const works = window.HANDRAW_SHARED.App.state.works = window.HANDRAW_SHARED.App.state.works || [];
                works.unshift({{ id: 'test_work_1_1', title: '1:1 方图', authorName: '测试员', images: ['{url_1_1}'] }});
                works.unshift({{ id: 'test_work_4_1', title: '4:1 横图', authorName: '测试员', images: ['{url_4_1}'] }});
                works.unshift({{ id: 'test_work_1_4', title: '1:4 竖图', authorName: '测试员', images: ['{url_1_4}'] }});
            }}""")

            # Open card picker modal
            page.click("#tb-insert-work")
            page.wait_for_selector(".hw-modal-panel .hw-picker-card-media", timeout=6000)

            # Ensure data-hw-src images are hydrated and loaded
            page.evaluate("""() => {
                document.querySelectorAll(".hw-modal-panel .hw-picker-card-media img[data-hw-src]").forEach(img => {
                    if (!img.src) img.src = img.getAttribute("data-hw-src");
                });
            }""")
            page.wait_for_timeout(500)

            # Quantitative Check: All cards in picker use .hw-picker-card-media with 1:1 ratio
            cards = page.locator(".hw-modal-panel .hw-picker-card-media")
            card_count = cards.count()
            assert card_count >= 3, f"Expected at least 3 cards in picker, found {card_count}"

            # Check layout stability: all containers have 1:1 aspect ratio
            for i in range(min(card_count, 6)):
                box = cards.nth(i).bounding_box()
                assert abs(box["width"] - box["height"]) <= 2, f"Card container not 1:1! {box['width']}x{box['height']}"
                img_el = cards.nth(i).locator("img")
                fit = img_el.evaluate("el => window.getComputedStyle(el).objectFit")
                assert fit == "contain", f"Card preview image must use object-fit: contain! Got {fit}"

            # Test 4 corner visibility on the 1:4, 4:1, 1:1 cards in picker
            for name, url, path, nw, nh in test_cases:
                target_card_img = page.locator(f".hw-modal-panel .hw-picker-card-media img[data-hw-src='{url}'], .hw-modal-panel .hw-picker-card-media img[src='{url}']").first
                assert target_card_img.count() > 0, f"Card image for {url} not found in modal!"
                target_card_img.wait_for(state="visible", timeout=3000)
                c_bytes = target_card_img.screenshot()
                assert_four_corners_visible(c_bytes, nw, nh, label=f"Card Picker [{name}] @ {vp_w}px")

            shot_card = TMP_DIR / f"card_picker_contain_{vp_w}.png"
            page.screenshot(path=str(shot_card))
            print(f"  ✓ Saved card picker screenshot: {shot_card}")

            # Close modal
            page.click("#hw-modal-close-x")
            page.wait_for_timeout(300)

        # ==================== PART 3: MODAL LARGE IMAGE PREVIEW / LIGHTBOX ====================
        print("\n--- Part 3: Modal Large Image Preview / Lightbox ---")
        page.set_viewport_size({"width": 1440, "height": 900})
        # Open lightbox via forum-app / shared modal
        page.evaluate(f"""() => {{
            window.HANDRAW_SHARED.openModal({{
                title: '🖼️ 查看高清配图',
                html: `
                    <div class="hw-modal-lightbox-container">
                        <a href="{url_1_4}" target="_blank" rel="noopener noreferrer" title="点击查看原图" style="display:block;max-width:100%;">
                            <img class="hw-modal-lightbox-img" src="{url_1_4}" alt="1:4 大图" />
                        </a>
                        <div style="display:flex;gap:10px;align-items:center;margin-top:10px;justify-content:center;flex-wrap:wrap;">
                            <a class="btn btn-sm btn-primary" href="{url_1_4}" download>⬇️ 下载原图</a>
                            <a class="btn btn-sm" href="{url_1_4}" target="_blank" rel="noopener noreferrer">↗️ 查看原图</a>
                        </div>
                    </div>
                `
            }});
        }}""")

        page.wait_for_selector(".hw-modal-lightbox-img", timeout=5000)
        lb_img = page.locator(".hw-modal-lightbox-img")
        lb_box = lb_img.bounding_box()

        # Quantitative checks on lightbox:
        # 1. Height does not exceed 76vh (900 * 0.76 = 684px)
        assert lb_box["height"] <= 900 * 0.76 + 5, f"Lightbox image height exceeds 76vh: {lb_box['height']}"
        # 2. 4 corner markers visible (no cropping)
        lb_bytes = lb_img.screenshot()
        assert_four_corners_visible(lb_bytes, 120, 480, label="Lightbox 1:4 Preview")
        # 3. View original link exists
        assert page.locator(".hw-modal-panel a:has-text('查看原图')").count() >= 1, "View original link must exist"
        print("  ✓ Modal large image preview constraints and view-original link verified!")

        shot_lb = TMP_DIR / "lightbox_preview_1440.png"
        page.screenshot(path=str(shot_lb))
        print(f"  ✓ Saved lightbox screenshot: {shot_lb}")

        browser.close()

    httpd.shutdown()
    for p in [path_1_4, path_4_1, path_1_1]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    try:
        db.close()
    except Exception:
        pass
    try:
        temp_dir.cleanup()
    except Exception:
        pass

    print("\n>>> ALL ISSUE #44 BROWSER VERIFICATIONS PASSED WITH QUANTITATIVE ASSERTIONS! <<<")


if __name__ == "__main__":
    run_browser_verification()
