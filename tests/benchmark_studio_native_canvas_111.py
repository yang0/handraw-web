"""#111: actual Studio HTTP Project/Chromium performance matrix.

Unlike the #127 synthetic DOM test this creates four real Projects with
10/50/100/300 native Studio nodes and locally served WebP assets. Run IDs,
media credentials and vendor requests are never created. Latency numbers
are observational and have no arbitrary pass/fail performance budget.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user
from smoke_studio_native_100_graph_112 import graph_fixture, http_json


def percentile(values, q):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * q))], 2)


JS_MEASURE = r"""() => {
  const graph=window.CS?.graph;
  const probe=window.HANDRAW_STUDIO_TESTING?.renderCanvasNodesForBenchmark;
  const root=document.getElementById('ic-nodes-layer');
  if(!graph||typeof probe!=='function'||!root)throw Error('native canvas test bridge unavailable');
  const beforeCards=new Map([...root.querySelectorAll('.ic-node[data-node-id]')]
    .map(el=>[el.dataset.nodeId,el]));
  const beforeImages=[...root.querySelectorAll('img')];
  const input=root.querySelector('[data-node-id="g00-3"] input[data-sp-aud]');
  if(!input)throw Error('first real native text_input editor not found');
  input.focus();
  input.value='光标仍保持在正在编辑的字段';
  if(typeof input.setSelectionRange==='function')input.setSelectionRange(2,5);
  const editNode=graph.nodes.find(n=>n.id==='g00-0');
  const resultNode=graph.nodes.find(n=>n.id==='g00-8');
  if(!editNode||!resultNode)throw Error('required text/result nodes are missing');
  const warm=probe();
  const updates=[];
  for(let i=0;i<7;i++){
    editNode.data.text='页面实际编辑-'+String(i);
    const measured=probe();
    updates.push({
      ms:+measured.durationMs.toFixed(2),
      dirty:(measured.patch?.changedIds||[]).filter(id=>id.startsWith('node:')),
      replaced:measured.patch?.replaced,
    });
  }
  // Reconcile may replace the owning card while explicitly restoring focus,
  // cursor and in-progress user value to the new real textarea node.
  const activeInput=root.querySelector('[data-node-id="g00-3"] input[data-sp-aud]');
  const focusHeld=document.activeElement===activeInput &&
    activeInput?.value==='光标仍保持在正在编辑的字段' &&
    activeInput.selectionStart===2 && activeInput.selectionEnd===5;
  const oldStatus=resultNode.data.status;
  resultNode.data.status=oldStatus==='generating'?'done':'generating';
  const status=probe();
  resultNode.data.status=oldStatus;
  const restored=probe();
  const stableNodes=[...beforeCards].filter(([id,el])=>
    id!=='g00-0'&&id!=='g00-8'&&el.isConnected &&
    root.querySelector('[data-node-id="'+id+'"]')===el).length;
  const afterImages=[...root.querySelectorAll('img')];
  const stableImages=beforeImages.filter(el=>el.isConnected&&afterImages.includes(el)).length;
  return {
    updates, focusHeld,
    statusMs:+status.durationMs.toFixed(2),
    statusDirty:(status.patch?.changedIds||[]).filter(id=>id.startsWith('node:')),
    restoredDirty:(restored.patch?.changedIds||[]).filter(id=>id.startsWith('node:')),
    stableUnrelatedNodes:stableNodes,
    totalUnrelatedNodes:beforeCards.size-2,
    stableImages,imagesBefore:beforeImages.length,
    totalCards:root.querySelectorAll('.ic-node[data-node-id]').length,
    edges:document.querySelectorAll('#ic-edges-svg [data-edge-id]').length,
    domElements:root.querySelectorAll('*').length,
    usedJSHeapBytes:performance.memory?.usedJSHeapSize??null
  };
}"""


def main() -> None:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)
        env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(path / "native-111.db"),
            "HANDRAW_PRIVATE_STORAGE": str(path / "private"),
            "HANDRAW_UPLOADS_DIR": str(path / "uploads"),
            "HANDRAW_GENERATED_DIR": str(path / "generated"),
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_AI_CONFIG": str(path / "missing-paid-ai.json"),
            "HANDRAW_IMAGE_CONFIG": str(path / "missing-paid-image.json"),
        })
        env.start()
        db = server = worker = None
        try:
            db = init_database(path / "native-111.db")
            _, token = register_user(db, "native111_benchmark", "Pass12345!")
            cookie = f"{SESSION_COOKIE_NAME}={token}"
            server = create_channel_server(0, "main", db)
            server.allow_demo_routes = True
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            cases = [10, 50, 100, 300]
            for size in cases:
                graph = graph_fixture(size // 10)
                assert len(graph["nodes"]) == size
                assert len(graph["edges"]) == size // 2
                status, created = http_json(base, "/api/studio/projects", cookie,
                    "POST", {"projectId": f"qa111-native-{size}",
                             "idempotencyKey": f"qa111-create-{size}",
                             "kind": "image", "authority": "graph",
                             "title": f"QA111 native {size} nodes",
                             "draft": {"graph": graph, "activeView": "canvas"}})
                assert status == 200 and created.get("ok") is not False, (
                    "Project API rejected safe fixture", size, status, created)

            measurements = []
            with sync_playwright() as pw:
                binary = next((x for cmd in ("chromium", "google-chrome-stable",
                    "google-chrome", "chrome") if (x := shutil.which(cmd))), None)
                launch = {"headless": True,
                          "args": ["--no-sandbox", "--disable-dev-shm-usage",
                                   "--enable-precise-memory-info"]}
                if binary:
                    launch["executable_path"] = binary
                browser = pw.chromium.launch(**launch)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 900},
                                                  device_scale_factor=1)
                    context.add_cookies([{"name": SESSION_COOKIE_NAME, "value": token,
                                         "url": base}])
                    for size in cases:
                        page = context.new_page()
                        page.add_init_script("window.__HANDRAW_TESTING__ = true")
                        errors, paid_posts = [], []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.on("request", lambda r: paid_posts.append(r.method)
                            if r.method == "POST" and (
                                "/api/studio/generate" in r.url or
                                "/api/studio/run" in r.url) else None)
                        begin = time.perf_counter()
                        try:
                            page.goto(base + f"/studio/?project=qa111-native-{size}",
                                      wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_function("""count => window.CS?.stageView==='canvas'
                              && window.CS?.graph?.nodes?.length===count
                              && document.querySelectorAll('#ic-nodes-layer .ic-node').length===count
                            """, arg=size, timeout=120000)
                            mount_ms = round((time.perf_counter() - begin) * 1000, 2)
                            native = page.evaluate(JS_MEASURE)
                            assert native["totalCards"] == size, native
                            assert native["edges"] == size // 2, native
                            assert native["focusHeld"], ("input focus lost on real canvas", size)
                            assert native["stableUnrelatedNodes"] == size - 2, (
                                "single node edit replaced unrelated cards", size, native)
                            assert native["stableImages"] == native["imagesBefore"], (
                                "local images reloaded during one-node update", size, native)
                            assert native["imagesBefore"] >= size * 4 // 10, native
                            assert all(x["dirty"] == ["node:g00-0"] for x in native["updates"]), (
                                "one text edit touched extra nodes", size, native["updates"])
                            assert len(native["statusDirty"]) <= 1, (
                                "one progress tick touched extra nodes", size, native["statusDirty"])
                            assert native["restoredDirty"] in ([], ["node:g00-8"])
                            # Actual UI zoom/camera path, measured separately from JS repaint.
                            zoom_ms = []
                            for _ in range(3):
                                tick = time.perf_counter()
                                page.locator("#bl-zoom-in").click(timeout=20000)
                                zoom_ms.append(round((time.perf_counter() - tick) * 1000, 2))
                            camera_stable = page.evaluate("""() => {
                              const root=document.querySelector('#ic-nodes-layer');
                              return root.querySelectorAll('.ic-node').length===window.CS.graph.nodes.length
                                && [...root.querySelectorAll('img')].every(img=>img.isConnected);
                            }""")
                            assert camera_stable, ("zoom removed graph cards", size)
                            assert not errors and not paid_posts, (size, errors, paid_posts)
                            native["nodePatchMs"] = [x["ms"] for x in native.pop("updates")]
                            native["nodePatchP95Ms"] = percentile(native["nodePatchMs"], .95)
                            native["zoomClickMs"] = zoom_ms
                            native["zoomClickP95Ms"] = percentile(zoom_ms, .95)
                            native["mountMs"] = mount_ms
                            native["nodes"] = size
                            native["expectedImageNodes"] = size * 4 // 10
                            native["paidGatewayPosts"] = 0
                            measurements.append(native)
                            print("CANVAS #111 REAL STUDIO " + json.dumps({
                                "nodes": size, "mountMs": mount_ms,
                                "nodePatchP95Ms": native["nodePatchP95Ms"],
                                "zoomClickP95Ms": native["zoomClickP95Ms"],
                                "domElements": native["domElements"],
                                "usedJSHeapBytes": native["usedJSHeapBytes"],
                                "stableImages": native["stableImages"],
                            }, ensure_ascii=False), flush=True)
                        finally:
                            page.close()
                    output = ROOT / "artifacts" / "studio-111-native"
                    output.mkdir(parents=True, exist_ok=True)
                    report = {"issue": 111,
                              "kind": "real-Studio-local-HTTP-Chromium",
                              "productionReleaseEvidence": False,
                              "paidGatewayCalls": 0,
                              "browser": browser.version,
                              "host": {"python": platform.python_version(),
                                       "system": platform.platform(),
                                       "machine": platform.machine()},
                              "measurements": measurements}
                    (output / "native-10-50-100-300.json").write_text(
                        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
                    assert [m["nodes"] for m in measurements] == cases
                    print("CANVAS #111 REAL STUDIO 10/50/100/300 PASS", flush=True)
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
