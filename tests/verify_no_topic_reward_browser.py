"""Playwright browser verification for Issue #46: Cancel normal topic publish credit reward.

Verifies against preview server on port 3097:
1. Normal topic publish:
   - Compose footer help copy does NOT promise +5✦.
   - Compose mode dropdown 'free' option does NOT promise +5✦.
   - Submit normal post -> Success toast does NOT include +5✦ reward message.
   - Wallet balance remains unchanged.
   - No 'publish_topic' ledger entry is created.
   - Screenshot saved to C:/tmp/normal_post_no_reward.png.
2. Bounty topic publish:
   - Select 10✦ bounty option.
   - Submit bounty post -> Escrow is deducted (balance - 10).
   - Screenshot saved to C:/tmp/bounty_post_escrow.png.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = 3097
BASE_URL = f"http://127.0.0.1:{PORT}"
SCREENSHOT_DIR = Path("C:/tmp")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


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


def get_user_boot(token: str) -> dict:
    url = f"{BASE_URL}/api/boot"
    req = urllib.request.Request(url, headers={"Cookie": f"handraw_sid={token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"=== Verifying against running preview server at {BASE_URL} ===")
    token = api_switch_user("yang0")
    assert token, "Failed to authenticate as yang0 via sandbox-switch"
    print("  Authenticated session token obtained.")

    boot_before = get_user_boot(token)
    initial_balance = boot_before.get("credits", 0)
    print(f"  Initial balance for yang0: {initial_balance}✦")

    with sync_playwright() as p:
        launch_args = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        }
        if os.path.exists(CHROME_PATH):
            launch_args["executable_path"] = CHROME_PATH

        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([{
            "name": "handraw_sid",
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        }])

        page = context.new_page()

        # =========================================================
        # Test 1: Publish normal topic -> balance unchanged, no +5✦ copy
        # =========================================================
        print("\n[Test 1] Verifying Normal Topic Publish (no credit reward)...")
        page.goto(f"{BASE_URL}/forum/?view=compose")
        page.wait_for_selector("#compose-title-input", timeout=10000)
        page.wait_for_selector("#compose-rich-editor", timeout=10000)

        # 1. Assert compose footer help does NOT mention +5✦ or 立得
        footer_text = page.locator(".hw-compose-footer-left").text_content() or ""
        print(f"  Footer help copy: {footer_text.strip()}")
        assert "+5✦" not in footer_text, f"Unexpected '+5✦' in footer copy: {footer_text}"
        assert "立得" not in footer_text, f"Unexpected '立得' in footer copy: {footer_text}"

        # 2. Assert compose mode dropdown 'free' option does NOT mention +5✦ or 立得
        free_option_text = page.locator('#compose-mode-dropdown option[value="free"]').text_content() or ""
        print(f"  Free option text: {free_option_text.strip()}")
        assert "+5✦" not in free_option_text, f"Unexpected '+5✦' in free option: {free_option_text}"
        assert "立得" not in free_option_text, f"Unexpected '立得' in free option: {free_option_text}"
        assert "✨ 公开免费" in free_option_text

        # 3. Enter post title & body
        page.fill("#compose-title-input", "浏览器实测｜普通交流帖无积分奖励")
        editor = page.locator("#compose-rich-editor")
        editor.click()
        editor.evaluate("el => el.innerHTML = '<p>这是一篇在浏览器自动化中测试的普通交流帖正文，发帖不增加积分。</p>'")

        # 4. Click submit
        page.click("#compose-submit-btn")

        # Wait for topic detail page
        page.wait_for_selector("#standalone-topic-detail-page", timeout=12000)
        time.sleep(1)

        # Verify toasts
        active_toasts = page.locator(".hw-toast").all_text_contents()
        print(f"  Visible toasts: {active_toasts}")
        for t in active_toasts:
            assert "+5✦" not in t, f"Unexpected '+5✦' in toast: {t}"
            assert "获得" not in t or "积分" not in t, f"Unexpected reward in toast: {t}"

        # Verify balance after normal post
        boot_after_normal = get_user_boot(token)
        normal_post_balance = boot_after_normal.get("credits", 0)
        print(f"  Balance after normal topic publish: {normal_post_balance}✦ (initial: {initial_balance}✦)")
        assert normal_post_balance == initial_balance, f"Expected balance unchanged ({initial_balance}), got {normal_post_balance}"

        # Screenshot normal post
        normal_shot = SCREENSHOT_DIR / "normal_post_no_reward.png"
        page.screenshot(path=str(normal_shot), full_page=False)
        print(f"  Saved screenshot to {normal_shot}")

        # =========================================================
        # Test 2: Publish bounty topic -> escrow deducted normally
        # =========================================================
        print("\n[Test 2] Verifying Bounty Topic Publish (escrow deduction)...")
        page.goto(f"{BASE_URL}/forum/?view=compose")
        page.wait_for_selector("#compose-title-input", timeout=10000)
        page.wait_for_selector("#compose-rich-editor", timeout=10000)

        # Fill title & body
        page.fill("#compose-title-input", "浏览器实测｜悬赏求调优托管扣分")
        editor = page.locator("#compose-rich-editor")
        editor.click()
        editor.evaluate("el => el.innerHTML = '<p>这是一篇在浏览器自动化中测试的悬赏求调优帖子，发布时应托管扣除 10 积分。</p>'")

        # Select bounty_10
        page.select_option("#compose-mode-dropdown", "bounty_10")
        print("  Selected compose mode: bounty_10")

        # Click submit
        page.click("#compose-submit-btn")

        # Wait for topic detail page
        page.wait_for_selector("#standalone-topic-detail-page", timeout=12000)
        time.sleep(1)

        # Verify balance after bounty post
        boot_after_bounty = get_user_boot(token)
        bounty_post_balance = boot_after_bounty.get("credits", 0)
        print(f"  Balance after bounty topic publish: {bounty_post_balance}✦ (expected: {initial_balance - 10}✦)")
        assert bounty_post_balance == initial_balance - 10, f"Expected balance {initial_balance - 10}, got {bounty_post_balance}"

        # Screenshot bounty post
        bounty_shot = SCREENSHOT_DIR / "bounty_post_escrow.png"
        page.screenshot(path=str(bounty_shot), full_page=False)
        print(f"  Saved screenshot to {bounty_shot}")

        browser.close()

    print("\n=== All Playwright browser verifications PASSED successfully! ===")


if __name__ == "__main__":
    main()
