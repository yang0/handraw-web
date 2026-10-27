"""Browser acceptance pass for the running local 2.0 site.

Loads every channel in a real Chromium, captures console errors, failed
requests and missing-element failures, then screenshots each view. Demo-mode
only; it logs in through the real UI form.

Usage:
    python tests/browser_acceptance.py [--base http://127.0.0.1] [--headed]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / ".local" / "browser-acceptance"

CHANNELS = {"main": 3080, "studio": 3081, "forum": 3082, "admin": 3083}
RESULTS: list[tuple[str, bool]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok)))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f" — {detail}" if detail else ""))
    return bool(ok)


class Recorder:
    def __init__(self, page) -> None:
        self.errors: list[str] = []
        self.failed: list[str] = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda exc: self.errors.append(f"pageerror: {exc}"))
        page.on("requestfailed", lambda req: self.failed.append(f"{req.method} {req.url} — {req.failure}"))

    def drain(self, label: str) -> bool:
        noisy = [e for e in self.errors if not _ignorable(e)]
        bad = [f for f in self.failed if not _ignorable(f)]
        ok = not noisy and not bad
        record(f"{label} 无控制台/请求错误", ok, f"{len(noisy)} 错误, {len(bad)} 失败请求" if not ok else "")
        for e in noisy[:6]:
            print(f"          console: {e[:220]}")
        for f in bad[:6]:
            print(f"          request: {f[:220]}")
        self.errors.clear()
        self.failed.clear()
        return ok


def _ignorable(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in ("favicon", "net::err_aborted", "err_blocked_by_client", "react devtools")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1")
    parser.add_argument("--user", default="yang0")
    parser.add_argument("--password", default="handraw123")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--channel", default="msedge")
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    main_url = f"{args.base}:{CHANNELS['main']}"
    studio_url = f"{args.base}:{CHANNELS['studio']}"
    forum_url = f"{args.base}:{CHANNELS['forum']}"
    admin_url = f"{args.base}:{CHANNELS['admin']}"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=args.channel, headless=not args.headed)
        except Exception as exc:
            print(f"无法启动 {args.channel}，改用默认 Chromium: {exc}")
            browser = p.chromium.launch(headless=not args.headed)

        ctx = browser.new_context(viewport={"width": 1440, "height": 960})
        page = ctx.new_page()
        rec = Recorder(page)

        print("\n== 1. 主站 ==")
        page.goto(f"{main_url}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        root = page.locator("#main-app-root")
        record("主站首屏渲染", root.count() > 0 and len(root.inner_text().strip()) > 40)
        rec.drain("主站首屏")
        page.screenshot(path=str(ARTIFACT_DIR / "01-main-home.png"))

        for view, label, marker in (
            ("styles", "画风库", "画风"),
            ("layouts", "图型库", "图型"),
            ("works", "作品广场", "作品"),
            ("rankings", "排行榜", "榜"),
            ("wallet", "钱包", "积分"),
        ):
            page.goto(f"{main_url}/?view={view}", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1000)
            text = page.locator("body").inner_text()
            record(f"主站 {label}", marker in text and len(text.strip()) > 80)
            rec.drain(f"主站 {label}")
            page.screenshot(path=str(ARTIFACT_DIR / f"02-main-{view}.png"))

        print("\n== 2. 界面登录 ==")
        page.goto(f"{main_url}/?view=auth", wait_until="networkidle", timeout=60000)
        logged = False
        try:
            page.wait_for_selector("#login-demo-account", timeout=20000)
            page.fill("#login-demo-account", args.user)
            page.fill("#login-demo-password", args.password)
            page.click("#login-confirm-btn")
            page.wait_for_timeout(3500)
            body_text = page.locator("body").inner_text()
            logged = "退出" in body_text or "Yang" in body_text or args.user in body_text
            record("界面登录", logged, "" if logged else body_text[:120])
        except Exception as exc:
            record("界面登录", False, str(exc)[:120])
        rec.drain("登录页")
        page.screenshot(path=str(ARTIFACT_DIR / "03-after-login.png"))

        print("\n== 3. 创作台 ==")
        page.goto(f"{studio_url}/", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)
        text = page.locator("body").inner_text()
        # The canvas is a DOM node graph, not a <canvas> element.
        nodes = page.locator(".canvas-node, .studio-node, [data-node-id]").count()
        has_palette = "节点工具箱" in text or "输入节点" in text
        record("创作台渲染", nodes > 0 and has_palette, f"节点 {nodes} 个, 工具箱={has_palette}")
        record("创作台画布操作", page.locator("text=运行").count() > 0, "运行按钮")
        rec.drain("创作台")
        page.screenshot(path=str(ARTIFACT_DIR / "04-studio.png"))

        print("\n== 4. 论坛 ==")
        page.goto(f"{forum_url}/", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2000)
        ftext = page.locator("body").inner_text()
        record("论坛列表", len(ftext.strip()) > 100, f"{len(ftext)} 字")
        rec.drain("论坛列表")
        page.screenshot(path=str(ARTIFACT_DIR / "05-forum.png"))

        page.goto(f"{forum_url}/?view=compose", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        compose = page.locator("#forum-compose-page").count() > 0
        record("论坛发帖页", compose, f"compose={compose}")
        rec.drain("论坛发帖页")
        page.screenshot(path=str(ARTIFACT_DIR / "06-forum-compose.png"))

        print("\n== 5. 管理后台 ==")
        page.goto(f"{admin_url}/", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2500)
        atext = page.locator("body").inner_text()
        gate = "分级权限管理中枢" in atext
        console_ready = any(m in atext for m in ("数据总览", "用户管理", "权限", "工作台", "审核"))
        # The session cookie is shared across channels, so either the gate or
        # the console is a valid landing depending on prior login state.
        record("后台进入", gate or console_ready, "登录门" if gate else ("已登录控制台" if console_ready else "空白"))
        if gate:
            try:
                page.fill("#adm-login-user", args.user)
                page.fill("#adm-login-pass", args.password)
                page.click("button:has-text('登录进入对应角色管理台')")
                page.wait_for_timeout(4000)
                after = page.locator("body").inner_text()
                console_ready = any(m in after for m in ("数据总览", "用户管理", "权限", "工作台", "审核"))
                record("后台控制台进入", console_ready, "" if console_ready else after[:140])
            except Exception as exc:
                record("后台控制台进入", False, str(exc)[:120])
        rec.drain("管理后台")
        page.screenshot(path=str(ARTIFACT_DIR / "07-admin.png"))

        print("\n== 6. 移动端 390px ==")
        mobile = ctx.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mrec = Recorder(mobile)
        mobile.goto(f"{main_url}/", wait_until="networkidle", timeout=60000)
        mobile.wait_for_timeout(1500)
        mtext = mobile.locator("body").inner_text()
        record("移动端首屏", len(mtext.strip()) > 80, f"{len(mtext)} 字")
        mrec.drain("移动端首屏")
        mobile.screenshot(path=str(ARTIFACT_DIR / "08-mobile-home.png"))
        mobile.close()

        ctx.close()
        browser.close()

    failed = [name for name, ok in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"浏览器验收 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}")
    for name in failed:
        print(f"  - {name}")
    print(f"截图目录: {ARTIFACT_DIR}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
