"""Studio #126 actual Chromium: preview -> CAS apply -> durable undo.

The server uses temporary SQLite and local HTTP; no paid image or AI provider.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user
from backend.studio_projects import create_project, get_project

PROJECT = "graphpatch-browser-126"
SENTINEL = "GRAPH126_KEEP_PRIVATE_OLD_RUN"


def graph():
    return {
        "blueprint": "single", "revision": 7, "nodes": [
            {"id": "gpstyle", "type": "skill_params", "title": "风格参数",
             "x": 60, "y": 50, "data": {"style1": "", "layout": "",
                                        "colors": [], "tones": []}},
            {"id": "gptext", "type": "text_input", "title": "文本参数",
             "x": 65, "y": 460, "data": {"text": "春日窗台上的猫"}},
            {"id": "gpcontrol", "type": "output_control", "title": "生成设置",
             "x": 500, "y": 100, "data": {"mode": "graphic-text",
                                            "ratio": "3:4", "count": 1}},
            {"id": "gpdisplay", "type": "output_display", "title": "成图显示",
             "x": 920, "y": 100, "data": {"items": [{
                 "imageUrl": "/starter/bear-and-bird.webp",
                 "title": "原始成果，不得覆盖"}],
                 "runId": SENTINEL, "status": "success"}},
        ],
        "edges": [
            {"id": "edge1", "from": "gpstyle", "to": "gpcontrol"},
            {"id": "edge2", "from": "gptext", "to": "gpcontrol"},
            {"id": "edge3", "from": "gpcontrol", "to": "gpdisplay"},
        ], "selectedIds": [],
    }


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "browser-126.sqlite"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_AI_CONFIG": str(root / "no-ai-provider.json"),
            "HANDRAW_IMAGE_CONFIG": str(root / "no-image-provider.json"),
        })
        env.start()
        db = server = worker = None
        try:
            db = init_database(root / "browser-126.sqlite")
            user, token = register_user(db, "graphpatch_126_browser", "Pass12345!")
            created = create_project(db, user, {
                "projectId": PROJECT, "idempotencyKey": "graph-126-browser-create",
                "kind": "image", "authority": "graph", "title": "GraphPatch UI QA",
                "draft": {"graph": graph(), "activeView": "canvas"},
            })
            assert created["revision"] == 1, created
            server = create_channel_server(0, "main", db)
            server.allow_demo_routes = True
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as playwright:
                chrome = next((p for n in ("chromium", "google-chrome-stable",
                                          "google-chrome", "chrome")
                              if (p := shutil.which(n))), None)
                args = {"headless": True, "args": [
                    "--no-sandbox", "--disable-dev-shm-usage"]}
                if chrome:
                    args["executable_path"] = chrome
                browser = playwright.chromium.launch(**args)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 900})
                    context.add_cookies([{"name": SESSION_COOKIE_NAME,
                                         "value": token, "url": base}])
                    page = context.new_page()
                    page.add_init_script("window.__HANDRAW_TESTING__ = true")
                    page_errors = []
                    charge_calls = []
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.on("request", lambda req: charge_calls.append(req.url)
                            if req.method == "POST" and (
                                "/api/studio/generate" in req.url or
                                "/api/studio/batch" in req.url or
                                "/api/studio/run" in req.url) else None)
                    page.goto(base + "/studio/?entry=canvas&project=" + PROJECT,
                              wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_function("""() => window.CS?.graph?.nodes?.length===4
                      && window.CS?.tabs?.find(t=>t.id===window.CS.activeTabId)?.projectId
                        ==='graphpatch-browser-126'
                      && window.CS?.tabs?.find(t=>t.id===window.CS.activeTabId)
                        ?.projectSaveState==='synced'
                      && document.querySelectorAll('#ic-nodes-layer .ic-node').length===4
                    """, timeout=45000)
                    page.locator('#canvas-129-topbar [data-c129="graphpatch"]').click(
                        timeout=15000)
                    dialog = page.locator("#gp126-backdrop")
                    dialog.wait_for(timeout=15000)
                    assert dialog.locator('[data-gp126="apply"]').is_disabled()
                    assert dialog.locator('[data-gp126="undo"]').is_disabled()
                    assert dialog.locator('[data-gp126-mode="platforms"]').get_attribute(
                        "aria-pressed") == "true"

                    dialog.locator('[data-gp126="preview"]').click()
                    page.wait_for_function("""() => {
                      const d=document.querySelector('#gp126-backdrop');
                      return d && !d.querySelector('[data-gp126="apply"]').disabled &&
                        d.querySelectorAll('.gp126-details li').length>=6;
                    }""", timeout=45000)
                    assert "潜在生成费用" in dialog.inner_text()
                    assert "当前仅预览，不生成、不扣费" in dialog.inner_text()
                    baseline = get_project(db, user, PROJECT)["project"]
                    assert baseline["revision"] == 1, baseline
                    assert len(baseline["draft"]["graph"]["nodes"]) == 4
                    assert page.locator("#ic-nodes-layer .ic-node").count() == 4
                    assert not charge_calls, charge_calls
                    print("GRAPH #126 preview only, no persisted Graph mutation: PASS",
                          flush=True)

                    dialog.locator('[data-gp126="apply"]').click()
                    page.wait_for_function("""() => {
                      const t=window.CS?.tabs?.find(t=>t.id===window.CS.activeTabId);
                      return window.CS?.graph?.nodes?.length===7 &&
                        t?.projectRevision===2 && t.projectSaveState==='synced' &&
                        !document.querySelector('#gp126-backdrop [data-gp126="undo"]').disabled;
                    }""", timeout=45000)
                    committed = get_project(db, user, PROJECT)["project"]
                    assert committed["revision"] == 2
                    assert len(committed["draft"]["graph"]["nodes"]) == 7
                    assert committed["draft"]["graph"]["revision"] == 8
                    assert page.locator("#ic-nodes-layer .ic-node").count() == 7
                    assert any(n.get("data", {}).get("runId") == SENTINEL
                               for n in committed["draft"]["graph"]["nodes"])
                    assert not charge_calls
                    print("GRAPH #126 confirmed CAS apply, old Run preserved: PASS",
                          flush=True)

                    dialog.locator('[data-gp126="undo"]').click()
                    page.wait_for_function("""() => {
                      const t=window.CS?.tabs?.find(t=>t.id===window.CS.activeTabId);
                      return window.CS?.graph?.nodes?.length===4 &&
                        t?.projectRevision===3 && t.projectSaveState==='synced';
                    }""", timeout=45000)
                    reverted = get_project(db, user, PROJECT)["project"]
                    assert reverted["revision"] == 3
                    assert reverted["draft"]["graph"]["revision"] == 9
                    assert len(reverted["draft"]["graph"]["nodes"]) == 4
                    assert any(n.get("data", {}).get("runId") == SENTINEL
                               for n in reverted["draft"]["graph"]["nodes"])
                    assert page.locator('#gp126-backdrop [data-gp126="apply"]').is_disabled()
                    assert not charge_calls
                    print("GRAPH #126 durable CAS undo and immutable old results: PASS",
                          flush=True)

                    # UI supports the remaining presets and authorized style
                    # choices without requesting protected prompt definitions.
                    dialog.locator('[data-gp126="close"]').first.click()
                    page.locator('#canvas-129-topbar [data-c129="graphpatch"]').click()
                    dialog = page.locator("#gp126-backdrop")
                    dialog.locator('[data-gp126-mode="style_compare"]').click()
                    page.wait_for_function("""() => {
                      const a=document.querySelector('#gp126-style-a');
                      return a && a.options.length>=2;
                    }""", timeout=20000)
                    assert dialog.locator("#gp126-style-a").input_value() != \
                           dialog.locator("#gp126-style-b").input_value()
                    dialog.locator('[data-gp126="preview"]').click()
                    page.wait_for_function("""() => {
                      const d=document.querySelector('#gp126-backdrop');
                      return d && !d.querySelector('[data-gp126="apply"]').disabled &&
                        d.querySelectorAll('.gp126-details li').length>=8;
                    }""", timeout=45000)
                    dialog.locator('[data-gp126-mode="ai"]').click()
                    dialog.locator("#gp126-instruction").fill("新增一个文本节点")
                    assert dialog.locator('[data-gp126="apply"]').is_disabled()
                    assert not page_errors, page_errors
                    assert not charge_calls, charge_calls
                    output = ROOT / "artifacts" / "graphpatch-126"
                    output.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output / "graphpatch-review.png"),
                                    animations="disabled")
                    (output / "chromium-summary.json").write_text(json.dumps({
                        "issue": 126, "result": "PASS",
                        "browser": browser.version,
                        "previewWithoutWrite": True,
                        "applyRevision": 2, "undoRevision": 3,
                        "lastGraphRevision": 9,
                        "preservedRun": True, "generationCalls": len(charge_calls),
                        "styleCompareReview": True,
                        "scope": "temporary-HTTP-Chromium-no-paid-provider",
                    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print("STUDIO #126 GRAPHPATCH CHROMIUM PASS", flush=True)
                    page.close()
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if worker:
                worker.join(timeout=5)
            if db:
                db.close()
            env.stop()


if __name__ == "__main__":
    main()
