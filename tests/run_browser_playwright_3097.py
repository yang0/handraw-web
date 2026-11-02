from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:3097"
TMP_DIR = Path("C:/tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)

def api_switch_user(username: str) -> str:
    url = f"{BASE_URL}/api/auth/sandbox-switch"
    data = json.dumps({"username": username}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        cookie_header = resp.headers.get("Set-Cookie", "")
        for part in cookie_header.split(";"):
            if "handraw_sid=" in part:
                return part.strip().split("=")[1]
    return ""

def setup_context_routes(context):
    def route_config(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "configured": True,
                "liveImageEnabled": True,
                "realImageGeneration": True,
                "demoMode": True,
                "rechargeEnabled": False,
                "trustedOrigins": ["http://127.0.0.1:3097"],
                "model": "gpt-image-2",
                "dailyFreeQuota": 3,
                "creditPerImage": 2
            })
        )

    def route_generate(route, request):
        post_data = request.post_data_json or {}
        post_data["simulateGateway"] = "ok"
        post_data["confirmCost"] = True
        route.continue_(post_data=json.dumps(post_data))

    context.route("**/api/studio/config", route_config)
    context.route("**/api/studio/generate", route_generate)

def main():
    print("Starting Playwright verification on port 3097...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        setup_context_routes(context)
        page = context.new_page()

        # Step 1: Switch to Account A (cat_doctor)
        token_a = api_switch_user("cat_doctor")
        print(f"Logged in as cat_doctor (token: {token_a[:10]}...)")
        context.add_cookies([{
            "name": "handraw_sid",
            "value": token_a,
            "domain": "127.0.0.1",
            "path": "/"
        }])

        # Visit Studio with style FA-013 preselected
        print("Visiting Studio as cat_doctor with style FA-013...")
        page.goto(f"{BASE_URL}/studio/?style=FA-013&entry=quick", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Fill subject
        subject_input = page.locator("#make-image-subject")
        subject_input.wait_for(state="visible", timeout=10000)
        subject_input.fill("水墨山水云海与白鹤")

        # Click run button
        print("Triggering image generation for cat_doctor...")
        run_btn = page.locator("#make-image-btn-run")
        run_btn.wait_for(state="visible")
        run_btn.click()

        # Wait for generation to complete
        page.wait_for_timeout(4000)
        page.screenshot(path=str(TMP_DIR / "01_account_a_generated.png"))
        print(f"Screenshot saved: {TMP_DIR / '01_account_a_generated.png'}")

        # Check cat_doctor's generation ID from public API
        req = urllib.request.Request(f"{BASE_URL}/api/users/cat_doctor/generations")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            gens = data.get("generations", [])
            print(f"cat_doctor public generations count: {len(gens)}")
            assert len(gens) > 0, "No public generations found for cat_doctor"
            target_gen = gens[0]
            gen_id = target_gen["id"]
            print(f"Target generation ID: {gen_id}")

        # Step 2: Switch to Account B (cat_newbie)
        token_b = api_switch_user("cat_newbie")
        print(f"Switched to cat_newbie (token: {token_b[:10]}...)")
        context.clear_cookies()
        context.add_cookies([{
            "name": "handraw_sid",
            "value": token_b,
            "domain": "127.0.0.1",
            "path": "/"
        }])

        # Open Account A's profile generation history
        history_url = f"{BASE_URL}/?view=profile&user=cat_doctor&ptab=generations"
        print(f"Opening cat_doctor's profile generation history: {history_url}")
        page.goto(history_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # Locate the generation card
        gen_card = page.locator(f'[data-prof-gen="{gen_id}"]')
        gen_card.wait_for(state="visible", timeout=10000)
        print("Found target generation card on profile page")
        page.screenshot(path=str(TMP_DIR / "02_account_b_view_a_history.png"))
        print(f"Screenshot saved: {TMP_DIR / '02_account_b_view_a_history.png'}")

        # Click the generation card to open detail modal
        print("Clicking card to open detail modal...")
        gen_card.click()
        page.wait_for_timeout(1000)

        # Locate like, favorite, and fork buttons in the modal
        like_btn = page.locator("#gen-modal-like-btn")
        fav_btn = page.locator("#gen-modal-fav-btn")
        fork_btn = page.locator("#gen-modal-fork-btn")

        like_btn.wait_for(state="visible", timeout=5000)
        fav_btn.wait_for(state="visible", timeout=5000)
        fork_btn.wait_for(state="visible", timeout=5000)

        # Click like and favorite
        print("Clicking like...")
        like_btn.click()
        page.wait_for_timeout(1000)

        print("Clicking collect...")
        fav_btn.click()
        page.wait_for_timeout(1000)

        page.screenshot(path=str(TMP_DIR / "03_account_b_detail_modal_liked_collected.png"))
        print(f"Screenshot saved: {TMP_DIR / '03_account_b_detail_modal_liked_collected.png'}")

        # Click "用这个配方复刻 ↗"
        print("Clicking fork button...")
        fork_btn.click()

        # Wait for navigation to Studio
        page.wait_for_url("**/studio/**", timeout=15000)
        page.wait_for_timeout(3000)

        # Verify the fork banner is visible
        fork_banner = page.locator(".make-image-fork-banner")
        fork_banner.wait_for(state="visible", timeout=10000)
        banner_text = fork_banner.inner_text()
        print(f"Fork banner displayed: {repr(banner_text)}")
        assert "配方来自" in banner_text and ("cat_doctor" in banner_text or "兽医小许" in banner_text), f"Expected author in banner text, got: {repr(banner_text)}"

        page.screenshot(path=str(TMP_DIR / "04_account_b_studio_fork_banner.png"))
        print(f"Screenshot saved: {TMP_DIR / '04_account_b_studio_fork_banner.png'}")

        # Ensure subject is filled
        subj_loc = page.locator("#make-image-subject")
        subj_loc.wait_for(state="visible", timeout=10000)
        if not subj_loc.input_value():
            subj_loc.fill("水墨山水云海与白鹤")

        # Confirm generation: click run button
        print("Confirming generation as cat_newbie...")
        studio_run_btn = page.locator("#make-image-btn-run")
        studio_run_btn.wait_for(state="visible")
        studio_run_btn.click()

        page.wait_for_timeout(5000)
        page.screenshot(path=str(TMP_DIR / "05_account_b_generated_with_attribution.png"))
        print(f"Screenshot saved: {TMP_DIR / '05_account_b_generated_with_attribution.png'}")

        # Verify via API that cat_newbie's new generation has fork_generation_id == gen_id
        req_b = urllib.request.Request(f"{BASE_URL}/api/users/cat_newbie/generations")
        with urllib.request.urlopen(req_b) as resp:
            data_b = json.loads(resp.read().decode("utf-8"))
            gens_b = data_b.get("generations", [])
            print(f"cat_newbie public generations count: {len(gens_b)}")
            assert len(gens_b) > 0, "No generations found for cat_newbie"
            new_gen = gens_b[0]
            fork_info = new_gen.get("fork")
            print(f"New generation fork info: {fork_info}")
            assert fork_info is not None, "Expected fork attribution on new generation"
            assert fork_info.get("generationId") == gen_id, f"Expected generationId {gen_id}, got {fork_info.get('generationId')}"
            assert fork_info.get("author") == "cat_doctor", f"Expected author cat_doctor, got {fork_info.get('author')}"
            print("Attribution verification successful!")

        browser.close()
        print("ALL BROWSER VERIFICATION STEPS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
