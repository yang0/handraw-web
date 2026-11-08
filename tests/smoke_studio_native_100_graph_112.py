"""#112 M3: real Studio HTTP Project -> native 100-node Canvas in Chromium.

This is a business-shaped Graph using actual editor node types, 40 real local
WebP previews and real Studio shell. It is not a paid gateway, customer-data
production benchmark, or an external object-storage/IDOR penetration test.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user


PRIVATE_TEXT = "QA112_PRIVATE_DRAFT_ONLY_NEVER_PUBLIC"
PROJECT_ID = "qa112-canvas-hundred"
PHOTO = "/starter/bear-and-bird.webp"
OTHER_PHOTO = "/starter/clay-commuter.webp"


def graph_fixture():
    nodes, edges = [], []
    types = ("text_input", "text_input", "text_input", "skill_params",
             "skill_params", "asset", "asset", "output_control",
             "output_display", "output_display")
    for group in range(10):
        prefix = f"g{group:02}"
        ids = []
        for offset, kind in enumerate(types):
            ident = f"{prefix}-{offset}"
            ids.append(ident)
            data = {}
            if kind == "text_input":
                data = {"text": (PRIVATE_TEXT if group == 0 and offset == 0
                                 else f"QA 场景 {group + 1} · 文本输入 {offset}")}
            elif kind == "skill_params":
                data = {"style1": "", "layout": "", "ratio": "3:4"}
            elif kind == "asset":
                data = {"items": [{
                    "id": f"local-fixture-{ident}",
                    "name": "仓库内测试样图（非生成媒体）",
                    "cat": "other",
                    "image": PHOTO if offset == 5 else OTHER_PHOTO,
                }]}
            elif kind == "output_control":
                data = {"mode": "graphic-text", "ratio": "3:4", "count": 1}
            elif kind == "output_display":
                data = {"status": "done", "items": [{
                    "title": "仓库测试图（不代表生成成功）",
                    "ratio": "3:4",
                    "imageUrl": PHOTO if offset == 8 else OTHER_PHOTO,
                    "demoMode": True,
                }]}
            nodes.append({
                "id": ident, "type": kind, "title": kind,
                "x": 30 + (group % 5) * 2400 + offset * 420,
                "y": 35 + (group // 5) * 1750 + (offset % 2) * 190,
                "w": 332, "data": data,
            })
        for src, dst in ((0, 7), (3, 7), (5, 7), (7, 8), (8, 9)):
            edges.append({
                "id": f"{prefix}-edge-{src}-{dst}",
                "from": ids[src], "to": ids[dst],
            })
    assert len(nodes) == 100 and len(edges) == 50
    return {"blueprint": "custom", "revision": 1, "nodes": nodes,
            "edges": edges, "selectedIds": []}


def http_json(base, path, cookie, method="GET", body=None):
    headers = {"Cookie": cookie, "Origin": "http://trusted.test"}
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=payload, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        environment = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "qa112-canvas.sqlite"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_AI_CONFIG": str(root / "no-provider-ai.json"),
            "HANDRAW_IMAGE_CONFIG": str(root / "no-provider-image.json"),
        })
        environment.start()
        database = server = worker = None
        try:
            database = init_database(root / "qa112-canvas.sqlite")
            _, alice_token = register_user(database, "qa112_canvas_alice", "Pass12345!")
            _, bob_token = register_user(database, "qa112_canvas_bob", "Pass12345!")
            alice = f"{SESSION_COOKIE_NAME}={alice_token}"
            bob = f"{SESSION_COOKIE_NAME}={bob_token}"
            server = create_channel_server(0, "main", database)
            server.allow_demo_routes = True
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"

            graph = graph_fixture()
            status, created = http_json(base, "/api/studio/projects", alice, "POST", {
                "projectId": PROJECT_ID, "idempotencyKey": "qa112-create-100",
                "kind": "image", "authority": "graph",
                "title": "QA112 100 节点复杂项目",
                "draft": {"graph": graph, "activeView": "canvas"},
            })
            assert status == 200, (status, created)
            status, owned = http_json(base, "/api/studio/projects/" + PROJECT_ID, alice)
            assert status == 200 and len(owned["project"]["draft"]["graph"]["nodes"]) == 100
            assert PRIVATE_TEXT in json.dumps(owned, ensure_ascii=False)
            status, denied = http_json(base, "/api/studio/projects/" + PROJECT_ID, bob)
            assert status == 404 and PRIVATE_TEXT not in json.dumps(denied), (status, denied)
            # A forged retry/copy by the non-owner must not reserialize any private Graph.
            status, copy_denied = http_json(
                base, "/api/studio/projects/" + PROJECT_ID + "/copy", bob, "POST",
                {"newProjectId": "qa112-forged-copy",
                 "idempotencyKey": "qa112-forged-idempotency"})
            assert status in (403, 404) and PRIVATE_TEXT not in json.dumps(copy_denied), (
                status, copy_denied)

            with sync_playwright() as pw:
                binary = next((b for cmd in ("chromium", "google-chrome-stable",
                    "google-chrome", "chrome") if (b := shutil.which(cmd))), None)
                launch = {"headless": True,
                          "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                if binary:
                    launch["executable_path"] = binary
                browser = pw.chromium.launch(**launch)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 900})
                    context.add_cookies([{
                        "name": SESSION_COOKIE_NAME, "value": alice_token,
                        "url": base,
                    }])
                    page = context.new_page()
                    page.add_init_script("window.__HANDRAW_TESTING__ = true")
                    errors, generation_posts = [], []
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    page.on("request", lambda req: generation_posts.append(req.url)
                            if req.method == "POST" and
                            ("/api/studio/generate" in req.url or
                             "/api/studio/run" in req.url) else None)

                    start = time.monotonic()
                    page.goto(base + "/studio/?project=" + PROJECT_ID,
                              wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_function("""() => window.CS?.stageView==='canvas'
                        && window.CS?.graph?.nodes?.length===100
                        && document.querySelectorAll('#ic-nodes-layer .ic-node').length===100
                    """, timeout=90000)
                    first_render_ms = round((time.monotonic() - start) * 1000, 1)
                    page.wait_for_function("""() => {
                      const images=[...document.querySelectorAll('#ic-nodes-layer img')];
                      return images.length>=40 && images.every(im=>im.complete && im.naturalWidth>0);
                    }""", timeout=30000)
                    initial = page.evaluate("""() => {
                      const root=document.querySelector('#ic-nodes-layer');
                      const cards=[...root.querySelectorAll('.ic-node')];
                      const imgs=[...root.querySelectorAll('img')];
                      window.__qa112Cards=new Map(cards.map(el=>[el.dataset.nodeId,el]));
                      window.__qa112Images=new Map(imgs.map((el,i)=>[i,el]));
                      return {count:cards.length, unique:new Set(cards.map(c=>c.dataset.nodeId)).size,
                        types:[...new Set(window.CS.graph.nodes.map(n=>n.type))],
                        links:window.CS.graph.edges.length, images:imgs.length,
                        decoded:imgs.filter(im=>im.complete && im.naturalWidth>0).length,
                        projectId:window.CS.tabs.find(t=>t.id===window.CS.activeTabId)?.projectId,
                        domElements:root.querySelectorAll('*').length};
                    }""")
                    assert initial["count"] == 100 and initial["unique"] == 100, initial
                    assert initial["links"] == 50 and initial["images"] >= 40, initial
                    assert initial["decoded"] == initial["images"], initial
                    assert initial["projectId"] == PROJECT_ID, initial
                    assert len(initial["types"]) == 5, initial

                    # Real Canvas click and zoom, rather than an isolated DOM benchmark.
                    # Fit-to-all for a 100-node graph places its first card
                    # under the dock/shelf. Pan to an operable viewport using
                    # the shipped 100% zoom button, then use a real pointer
                    # click (no DOM dispatch that bypasses hit testing).
                    page.evaluate("""() => {
                        window.CS.vx = 495;
                        window.CS.vy = 225;
                        document.querySelector('#bl-zoom-pct').click();
                    }""")
                    header = page.locator(
                        '#ic-nodes-layer [data-node-id="g00-0"] .ic-node-header-above')
                    header.click(position={"x": 42, "y": 12}, timeout=20000)
                    page.wait_for_function(
                        "() => window.CS?.graph?.selectedIds?.includes('g00-0')",
                        timeout=10000)
                    assert page.locator("#ic-nodes-layer .ic-node.is-selected").count() >= 1
                    measurements = []
                    for _ in range(5):
                        before = time.monotonic()
                        page.locator("#bl-zoom-in").click(timeout=15000)
                        measurements.append(round((time.monotonic()-before)*1000, 1))
                    selection = page.evaluate("""() => ({
                        nodes:[...window.__qa112Cards].every(([id,el]) =>
                            el.isConnected && document.querySelector(
                              '#ic-nodes-layer [data-node-id="'+id+'"]') === el),
                        images:[...window.__qa112Images.values()].every(
                            el=>el.isConnected && el.complete && el.naturalWidth>0),
                        count:document.querySelectorAll('#ic-nodes-layer .ic-node').length,
                    })""")
                    assert selection == {"nodes": True, "images": True, "count": 100}, selection
                    assert not errors and not generation_posts, (errors, generation_posts)
                    report = {
                        "issue": 112, "result": "PASS", "scope": "local-HTTP-native-Studio-Graph",
                        "production_release_approval": False,
                        "paid_gateway_calls": len(generation_posts),
                        "browser": browser.version, "viewport": [1440, 900],
                        "first_render_ms_observed": first_render_ms,
                        "zoom_click_ms_observed": measurements,
                        **initial, "stable_after_selection_zoom": selection,
                        "bob_project_read_http": 404,
                        "bob_project_copy_denied": status,
                    }
                    output = ROOT / "artifacts" / "studio-112-100-node"
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "actual-studio-graph-100.json").write_text(
                        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    page.screenshot(path=str(output / "actual-studio-graph-100.png"),
                                    animations="disabled")
                    print("STUDIO #112 NATIVE 100-NODE CHROMIUM PASS "
                          + json.dumps(report, ensure_ascii=False), flush=True)
                    page.close()
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if worker:
                worker.join(timeout=5)
            if database:
                database.close()
            environment.stop()


if __name__ == "__main__":
    main()
