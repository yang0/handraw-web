"""#106 real Chromium navigation / Project Center / deep-link smoke.
Runs an authenticated local HTTP server, inserts isolated SQLite fixtures, and
intercepts only the local same-origin remix recipe. No paid provider is invoked.
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
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.server import SESSION_COOKIE_NAME, create_channel_server, init_database
from backend.services import register_user


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "navigation106.sqlite"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "storage"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ENABLE_RECHARGE": "0",
            "HANDRAW_AI_CONFIG": str(root / "missing-ai.json"),
            "HANDRAW_IMAGE_CONFIG": str(root / "missing-image.json"),
        })
        env.start()
        db = server = thread = None
        try:
            db = init_database(root / "navigation106.sqlite")
            alice, token = register_user(db, "browser_nav_106", "Pass12345!")
            user_id = alice["id"]
            with db.transaction() as tx:
                for index in range(46):
                    # Seed only Project metadata. These are not generated
                    # images or paid model outputs.
                    stamp = f"2026-11-08T00:00:{index:02}Z"
                    title = "106 春日专项" if index == 3 else f"106 归档项目 {index:02}"
                    tx.execute(
                        """INSERT INTO studio_projects
                        (id,user_id,kind,title,authority,revision,draft_json,created_at,updated_at)
                        VALUES (?,?,?,?,?,1,'{}',?,?)""",
                        (f"nav106-{index:02}", user_id, "image", title,
                         "graph", stamp, stamp))
            server = create_channel_server(0, "main", db)
            server.allow_demo_routes = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            screens = ROOT / "artifacts" / "navigation-106-screen"
            screens.mkdir(parents=True, exist_ok=True)
            errors, paid, steps = [], [], []

            with sync_playwright() as pw:
                binary = next((b for cmd in ("chromium", "google-chrome-stable",
                    "google-chrome", "chrome") if (b := shutil.which(cmd))), None)
                launch = {"headless": True,
                          "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                if binary:
                    launch["executable_path"] = binary
                browser = pw.chromium.launch(**launch)
                context = browser.new_context(viewport={"width": 1366, "height": 900})
                context.add_cookies([{"name": SESSION_COOKIE_NAME,
                                     "value": token, "url": base}])
                page = context.new_page()
                page.add_init_script("window.__HANDRAW_TESTING__ = true")
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.on("request", lambda req: paid.append(req.url)
                    if req.method == "POST" and
                    ("/api/studio/generate" in req.url or
                     "/api/studio/run" in req.url) else None)

                def visit(query):
                    page.goto(base + "/studio/?" + query,
                              wait_until="networkidle", timeout=45000)
                    page.locator("#ic-entry-bar").wait_for(timeout=20000)

                def stage(expected):
                    page.wait_for_function("(v) => window.CS?.stageView === v",
                                           arg=expected, timeout=20000)

                # #136: Project Center is removed. Legacy URLs land on the
                # image form without erasing saved project data or deep links.
                visit("view=projects")
                stage("quick")
                assert "view=projects" not in page.url
                assert page.locator("#studio-mode-projects").count() == 0
                assert page.locator("[data-pc-open]").count() == 0
                assert page.locator("#studio-mode-view-toggle").count() == 1
                assert page.locator("#make-image-subject").is_visible()
                steps.append("retired project center redirects to image form")

                # One contextual switch, both directions, SAME graph.
                subject_box=page.locator("#make-image-subject")
                subject_box.fill("136 图像视图往返保真")
                page.wait_for_function("""() => window.CS.graph.nodes.some(n =>
                    n.type==='text_input' && n.data.text==='136 图像视图往返保真')""")
                before_graph=page.evaluate("""() => JSON.stringify(window.CS.graph.nodes
                    .map(n=>({id:n.id,type:n.type,data:n.data})))""")
                page.locator("#studio-mode-view-toggle").click()
                stage("canvas")
                assert page.locator("#studio-mode-view-toggle").inner_text().find("返回表单") >= 0
                assert page.locator("#studio-mode-simple").count() == 0
                assert page.locator("#studio-mode-canvas").count() == 0
                page.locator("#studio-mode-view-toggle").click()
                stage("quick")
                assert page.locator("#make-image-subject").input_value() == "136 图像视图往返保真"
                after_graph=page.evaluate("""() => JSON.stringify(window.CS.graph.nodes
                    .map(n=>({id:n.id,type:n.type,data:n.data})))""")
                assert before_graph == after_graph,"view switch must not rewrite graph nodes"
                steps.append("single contextual form/canvas round-trip preserves graph")

                page.locator("#studio-mode-batch").click()
                stage("batch")
                page.locator(".series108-board").wait_for(timeout=20000)
                page.locator("#studio-mode-view-toggle").click()
                stage("canvas")
                page.locator("#studio-mode-view-toggle").click()
                stage("batch")
                steps.append("series form/canvas two-way projection")

                page.locator("#studio-mode-article").click()
                stage("preview")
                page.locator("#ic-preview-stage").wait_for(timeout=20000,
                                                           state="visible")
                assert page.locator("#studio-mode-article").get_attribute("aria-pressed")=="true"
                steps.append("article entry without Project Center")

                page.locator("#studio-mode-from-workflow").click()
                stage("workflows")
                page.locator("#wf-search-inp").wait_for(timeout=20000)
                steps.append("workflow entry without Project Center")

                for url, expected, selector in [
                    ("entry=quick", "quick", "#make-image-subject"),
                    ("entry=batch", "batch", ".series108-board"),
                    ("entry=article", "preview", "#ic-preview-stage"),
                    ("entry=canvas", "canvas", "#ic-canvas-stage"),
                    ("view=projects", "quick", "#make-image-subject"),
                    ("view=history", "history", "#ic-history-stage"),
                    ("view=workflows", "workflows", "#wf-search-inp"),
                ]:
                    visit(url)
                    stage(expected)
                    page.locator(selector).wait_for(timeout=20000)
                steps.append("legacy routes redirect safely")

                # Known saved template must be routed into its Canvas graph.
                template_id = page.evaluate("""() => window.CS.savedWorkflows
                    ?.find(w => w?.graph?.nodes?.length)?.id || ''""")
                assert template_id, "Missing local workflow fixture"
                visit("workflow=" + quote(template_id, safe=""))
                stage("canvas")
                assert page.evaluate("""id => window.CS.tabs.some(t =>
                    t.id===window.CS.activeTabId && t.savedId===id)""", template_id)
                assert "workflow=" in page.url
                steps.append("workflow deep link retains identity")

                # ?project=id is a direct reopen contract, not just a library
                # link. Persist a valid graph without invoking generation.
                visit("entry=quick")
                page.locator("#make-image-subject").wait_for(timeout=20000)
                project = page.evaluate("""async () => {
                    const response = await fetch('/api/studio/projects', {
                        method: 'POST', credentials: 'include',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            projectId: 'nav106-direct', kind: 'image',
                            authority: 'graph', title: '106 云端直达项目',
                            idempotencyKey: 'nav106-create-direct-once',
                            draft: {graph: window.CS.graph, activeView: 'simple'}
                        })
                    });
                    return {status: response.status, payload: await response.json()};
                }""")
                assert project["status"] == 200, project
                visit("project=nav106-direct")
                try:
                    stage("quick")
                except Exception as exc:
                    detail = page.evaluate("""() => ({
                        stage: window.CS?.stageView, pending: window.CS?.pendingProjectDeepLink,
                        opening: window.CS?.projectOpeningId,
                        tabs: window.CS?.tabs?.map(t=>({
                            id:t.id,projectId:t.projectId,
                            saveState:t.projectSaveState,activeView:t.projectActiveView
                        })),
                        url:location.href,
                        pageText:document.body?.innerText?.slice(-600)
                    })""")
                    raise AssertionError({"directProject":project,"browserState":detail}) from exc
                page.wait_for_function("""() => window.CS?.tabs?.some(t =>
                    t.id===window.CS.activeTabId &&
                    t.projectId==='nav106-direct' &&
                    t.projectSaveState==='synced')""", timeout=20000)
                assert "project=nav106-direct" in page.url
                steps.append("direct cloud Project deep link and ID preservation")

                # Only this same-origin recipe is mocked: no third-party calls,
                # no live generation. The UI must show the selected work's spec.
                def remix_route(route):
                    route.fulfill(status=200, content_type="application/json",
                        body=json.dumps({"draft": {
                            "subjectHint": "106 复刻已预填主题",
                            "styleIds": ["FA-001"], "layoutId": "SC-021",
                            "ratio": "1:1", "mode": "graphic-text"
                        }}, ensure_ascii=False))
                page.route("**/api/studio/recipes/from-work/nav106-remix*", remix_route)
                visit("remix=nav106-remix")
                stage("quick")
                page.wait_for_function("""() => document.querySelector(
                    '#make-image-subject')?.value === '106 复刻已预填主题'""",
                    timeout=20000)
                assert page.locator("#make-image-ratio-input").input_value() == "1:1"
                assert "sourceRemix=nav106-remix" in page.url
                steps.append("remix prefill no generation")

                # 768px tablet and 360px narrow phone: navigation drawer
                # must actually expand, contract and accept touch-sized taps.
                for width in (768, 360):
                    page.set_viewport_size({"width": width, "height": 820})
                    page.locator("#studio-mobile-nav-toggle").wait_for(
                        timeout=10000, state="visible")
                    toggle = page.locator("#studio-mobile-nav-toggle")
                    toggle.click()
                    assert toggle.get_attribute("aria-expanded") == "true"
                    assert page.locator("#studio-mode-from-workflow").is_visible()
                    assert page.locator("#studio-mode-history").count() == 1
                    page.screenshot(path=str(screens / f"nav-{width}.png"),
                                    animations="disabled")
                    toggle.click()
                    assert toggle.get_attribute("aria-expanded") == "false"
                steps.append("tablet and 360px drawer")
                assert not paid, paid
                assert not errors, errors
                (screens / "results.json").write_text(json.dumps({
                    "result": "PASS", "scenarioCount": len(steps),
                    "steps": steps, "paidRequests": paid,
                    "pageErrors": errors, "viewports": [1366, 768, 360],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                print("STUDIO #136 REAL CHROMIUM FORM/CANVAS/REMIX PASS",
                      json.dumps(steps, ensure_ascii=False), flush=True)
                browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:
                thread.join(timeout=3)
            if db:
                db.close()
            env.stop()


if __name__ == "__main__":
    main()
