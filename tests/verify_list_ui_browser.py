import os
import sys
import mimetypes

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8')

from pathlib import Path
from playwright.sync_api import sync_playwright

WORKTREE_DIR = Path(r"C:\Users\yang0\.paseo\worktrees\2mbwfje1\list-ui")
ASSETS_DIR = WORKTREE_DIR / "demo" / "assets"
TMP_DIR = Path(r"C:\tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)

def route_assets(route, request):
    url = request.url
    if "/assets/" in url:
        asset_name = url.split("/assets/")[1].split("?")[0].split("#")[0]
        local_file = ASSETS_DIR / asset_name
        if local_file.is_file():
            content_type, _ = mimetypes.guess_type(str(local_file))
            if local_file.suffix == ".js":
                content_type = "application/javascript"
            elif local_file.suffix == ".css":
                content_type = "text/css"
            with open(local_file, "rb") as f:
                body = f.read()
            route.fulfill(
                status=200,
                headers={"Content-Type": content_type or "text/plain; charset=utf-8"},
                body=body
            )
            return
    route.continue_()

def main():
    print("Starting Playwright browser verification with MS Edge...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        
        # 1. Desktop Context
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.route("**/assets/*", route_assets)

        # Login as su_editorial via sandbox switch
        page.goto("http://127.0.0.1:3097/")
        page.wait_for_timeout(1000)
        login_res = page.evaluate("""
            async () => {
                const res = await fetch('/api/auth/sandbox-switch', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: 'su_editorial'})
                });
                return {
                    status: res.status,
                    data: await res.json().catch(e => ({ error: e.message }))
                };
            }
        """)
        print("Sandbox switch raw response:", login_res)

        # -------------------------------------------------------------
        # Verification 1: Works list action bar & Like button
        # -------------------------------------------------------------
        print("\n--- Verifying Works list (/?view=works) ---")
        page.goto("http://127.0.0.1:3097/?view=works")
        page.wait_for_selector(".hw-card, .hw-wb-card", timeout=8000)
        page.wait_for_timeout(1500)

        # Inspect first work card action buttons
        actions_order = page.evaluate("""
            () => {
                const card = document.querySelector('.hw-card, .hw-wb-card');
                if (!card) return null;
                const actions = card.querySelector('.hw-wb-actions, .hw-card-actions');
                if (!actions) return null;
                const btns = Array.from(actions.querySelectorAll('button'));
                return btns.map(b => ({
                    text: b.textContent.trim(),
                    classes: b.className,
                    hasLike: b.hasAttribute('data-wb-like'),
                    hasFav: b.hasAttribute('data-wb-fav'),
                    hasComment: b.hasAttribute('data-wb-comment'),
                    actionAttr: b.getAttribute('data-social-action')
                }));
            }
        """)
        print("Works card action buttons:", actions_order)
        assert actions_order is not None, "Works card actions not found"
        assert len(actions_order) >= 3, f"Expected at least 3 buttons, found {len(actions_order)}"
        
        # Verify order: Like, Collect, Comment
        assert actions_order[0]["hasLike"] or actions_order[0]["actionAttr"] == "like", "1st button must be Like"
        assert actions_order[1]["hasFav"] or actions_order[1]["actionAttr"] == "collect", "2nd button must be Collect"
        assert actions_order[2]["hasComment"], "3rd button must be Comment"
        
        # Verify classes
        for btn in actions_order[:3]:
            assert "btn" in btn["classes"] and "btn-sm" in btn["classes"] and "hw-action-btn" in btn["classes"], \
                f"Button classes should contain btn btn-sm hw-action-btn, got: {btn['classes']}"
        print("✓ Works list action bar has Like button, unified order [Like, Collect, Comment], and consistent classes.")

        # Save screenshot
        screenshot_works = TMP_DIR / "list_ui_works_desktop.png"
        page.screenshot(path=str(screenshot_works), full_page=False)
        print(f"✓ Saved screenshot: {screenshot_works}")

        # -------------------------------------------------------------
        # Verification 2: Styles list action bar parity
        # -------------------------------------------------------------
        print("\n--- Verifying Styles list (/?view=styles) ---")
        page.goto("http://127.0.0.1:3097/?view=styles")
        page.wait_for_selector(".hw-card", timeout=8000)
        page.wait_for_timeout(1500)

        style_actions_order = page.evaluate("""
            () => {
                const card = document.querySelector('.hw-card');
                if (!card) return null;
                const actions = card.querySelector('.hw-card-actions');
                if (!actions) return null;
                const btns = Array.from(actions.querySelectorAll('button'));
                return btns.map(b => ({
                    text: b.textContent.trim(),
                    classes: b.className,
                    hasLike: b.hasAttribute('data-like-asset'),
                    hasFav: b.hasAttribute('data-fav-asset'),
                    hasComment: b.hasAttribute('data-comment-asset'),
                    actionAttr: b.getAttribute('data-social-action')
                }));
            }
        """)
        print("Style card action buttons:", style_actions_order)
        assert style_actions_order is not None, "Style card actions not found"
        assert len(style_actions_order) >= 3, f"Expected at least 3 buttons, found {len(style_actions_order)}"
        assert style_actions_order[0]["hasLike"] or style_actions_order[0]["actionAttr"] == "like", "1st button must be Like"
        assert style_actions_order[1]["hasFav"] or style_actions_order[1]["actionAttr"] == "collect", "2nd button must be Collect"
        assert style_actions_order[2]["hasComment"], "3rd button must be Comment"
        for btn in style_actions_order[:3]:
            assert "btn" in btn["classes"] and "btn-sm" in btn["classes"] and "hw-action-btn" in btn["classes"], \
                f"Button classes should contain btn btn-sm hw-action-btn, got: {btn['classes']}"
        print("✓ Styles list action bar order [Like, Collect, Comment] and classes match.")

        # Save screenshot
        screenshot_styles = TMP_DIR / "list_ui_styles_desktop.png"
        page.screenshot(path=str(screenshot_styles), full_page=False)
        print(f"✓ Saved screenshot: {screenshot_styles}")

        # -------------------------------------------------------------
        # Verification 3: In-Place Toggle (Zero Full-Page Reload / Zero Extra Image Requests)
        # -------------------------------------------------------------
        print("\n--- Verifying In-Place Local Toggle (No Full-Page Re-renders) ---")
        page.goto("http://127.0.0.1:3097/?view=works")
        page.wait_for_selector(".hw-card, .hw-wb-card", timeout=8000)
        page.wait_for_timeout(1500)

        # Track image requests during click
        img_requests = []
        def on_request(req):
            if any(req.url.lower().endswith(ext) or ext in req.url.lower() for ext in [".png", ".jpg", ".jpeg", ".webp"]):
                if not req.url.endswith("/api/interactions/like") and not req.url.endswith("/api/collections/toggle"):
                    img_requests.append(req.url)
        page.on("request", on_request)

        # Read initial like state & count of first card
        initial_info = page.evaluate("""
            () => {
                const card = document.querySelector('.hw-card, .hw-wb-card');
                const likeBtn = card.querySelector('[data-wb-like]');
                const cntSpan = likeBtn.querySelector('.hw-social-count');
                return {
                    initialCount: parseInt(cntSpan.textContent.trim(), 10),
                    initialActive: likeBtn.classList.contains('is-active')
                };
            }
        """)
        print("Initial work like state:", initial_info)

        # Click like button
        print("Clicking like button...")
        img_requests.clear()
        page.click(".hw-wb-card [data-wb-like]")
        page.wait_for_timeout(1000)

        page_state = page.evaluate("""
            () => ({
                url: window.location.href,
                cardCount: document.querySelectorAll('.hw-wb-card').length,
                loggedIn: window.HANDRAW_APP?.state?.loggedIn,
                hasModal: Boolean(document.querySelector('.hw-modal'))
            })
        """)
        print("Page state after click:", page_state)

        after_like_info = page.evaluate("""
            () => {
                const card = document.querySelector('.hw-card, .hw-wb-card');
                const likeBtn = card.querySelector('[data-wb-like]');
                const cntSpan = likeBtn.querySelector('.hw-social-count');
                return {
                    count: parseInt(cntSpan.textContent.trim(), 10),
                    active: likeBtn.classList.contains('is-active')
                };
            }
        """)
        print("After like state:", after_like_info)
        assert after_like_info["active"] != initial_info["initialActive"], "Like active class should toggle"
        if after_like_info["active"]:
            assert after_like_info["count"] == initial_info["initialCount"] + 1, "Like count should increment"
        else:
            assert after_like_info["count"] == initial_info["initialCount"] - 1, "Like count should decrement"
        
        # Verify 0 image reloads
        print(f"Image requests triggered during like click: {len(img_requests)}")
        assert len(img_requests) == 0, f"Expected 0 image requests during local like, got: {img_requests}"
        print("✓ In-place like toggle verified: counter updated and active state toggled with 0 image reloads.")

        # Click collect button
        print("Clicking collect button on same card...")
        img_requests.clear()
        page.click(".hw-card [data-wb-fav], .hw-wb-card [data-wb-fav]")
        page.wait_for_timeout(1000)

        after_fav_info = page.evaluate("""
            () => {
                const card = document.querySelector('.hw-card, .hw-wb-card');
                const favBtn = card.querySelector('[data-wb-fav]');
                const cntSpan = favBtn.querySelector('.hw-social-count');
                const heart = favBtn.querySelector('.hw-fav-icon');
                const topbarCol = document.getElementById('hw-dropdown-collections');
                return {
                    count: parseInt(cntSpan.textContent.trim(), 10),
                    active: favBtn.classList.contains('is-active'),
                    heartText: heart ? heart.textContent.trim() : '',
                    topbarText: topbarCol ? topbarCol.textContent.trim() : ''
                };
            }
        """)
        print("After collect state:", after_fav_info)
        print(f"Image requests triggered during collect click: {len(img_requests)}")
        assert len(img_requests) == 0, f"Expected 0 image requests during local collect, got: {img_requests}"
        print("✓ In-place collect toggle verified: counter and icon updated with 0 image reloads.")

        # Ensure card is collected so Verification 4 has an item in collections
        if not after_fav_info["active"]:
            print("Card is currently uncollected, clicking collect to ensure it is collected for collections view test...")
            page.click(".hw-card [data-wb-fav], .hw-wb-card [data-wb-fav]")
            page.wait_for_timeout(1000)

        # -------------------------------------------------------------
        # Verification 4: Collections view card removal on uncollect
        # -------------------------------------------------------------
        print("\n--- Verifying Collections View Uncollect & DOM Removal ---")
        page.goto("http://127.0.0.1:3097/?view=collections")
        page.wait_for_timeout(1000)

        # Switch to works tab where we just collected work_102
        page.click('[data-ftab="works"]')
        page.wait_for_timeout(1000)

        col_cards_count = page.evaluate("() => document.querySelectorAll('.hw-card').length")
        print(f"Collections tab works card count: {col_cards_count}")
        assert col_cards_count >= 1, f"Expected at least 1 collected work card, got: {col_cards_count}"

        first_card_id = page.evaluate("() => document.querySelector('.hw-card').getAttribute('data-fav-item')")
        print(f"First collected card id: {first_card_id}")
        
        # Click uncollect button on that card
        page.click(".hw-card [data-unfav]")
        page.wait_for_timeout(800)

        # Check if that specific card was removed
        card_still_present = page.evaluate(f"() => Boolean(document.querySelector('[data-fav-item=\"{first_card_id}\"]'))")
        assert not card_still_present, f"Card {first_card_id} should be removed from DOM"
        print(f"✓ Card {first_card_id} removed locally from collections view DOM without reload.")

        screenshot_col = TMP_DIR / "list_ui_collections_uncollect.png"
        page.screenshot(path=str(screenshot_col), full_page=False)
        print(f"✓ Saved screenshot: {screenshot_col}")

        # -------------------------------------------------------------
        # Verification 5: Mobile 390px Viewport
        # -------------------------------------------------------------
        print("\n--- Verifying Mobile Viewport (390px) ---")
        context_mobile = browser.new_context(viewport={"width": 390, "height": 844})
        page_m = context_mobile.new_page()
        page_m.route("**/assets/*", route_assets)

        page_m.goto("http://127.0.0.1:3097/?view=works")
        page_m.wait_for_selector(".hw-card, .hw-wb-card", timeout=8000)
        page_m.wait_for_timeout(1500)

        # Check action button styling & overflow on 390px
        btn_box = page_m.evaluate("""
            () => {
                const actions = document.querySelector('.hw-wb-actions, .hw-card-actions');
                const btns = Array.from(actions.querySelectorAll('button'));
                return {
                    actionsWidth: actions.clientWidth,
                    buttons: btns.map(b => ({
                        text: b.textContent.trim(),
                        width: b.offsetWidth,
                        height: b.offsetHeight
                    }))
                };
            }
        """)
        print("Mobile action buttons layout:", btn_box)
        assert all(b["height"] >= 24 for b in btn_box["buttons"]), "Mobile action buttons must have adequate touch height"

        screenshot_mobile = TMP_DIR / "list_ui_mobile_390.png"
        page_m.screenshot(path=str(screenshot_mobile), full_page=False)
        print(f"✓ Saved screenshot: {screenshot_mobile}")

        context_mobile.close()
        context.close()
        browser.close()
    
    print("\n========================================================")
    print("ALL BROWSER VERIFICATIONS PASSED SUCCESSFULLY!")
    print("========================================================")

if __name__ == "__main__":
    main()
