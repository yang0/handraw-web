"""#103 real Chromium: private Project persistence and CAS recovery.
Uses the authenticated local HTTP server and real editor interactions.
No paid generation requests or external image provider credentials.
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


def main():
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        environment = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "project103.sqlite"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "storage"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ENABLE_RECHARGE": "0",
        })
        environment.start()
        db = server = thread = None
        try:
            db = init_database(root / "project103.sqlite")
            alice, token_a = register_user(db, "project103_alice", "Pass12345!")
            bob, token_b = register_user(db, "project103_bob", "Pass12345!")
            server = create_channel_server(0, "main", db)
            server.allow_demo_routes = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"

            with sync_playwright() as pw:
                binary = next((p for cmd in ("chromium", "google-chrome-stable",
                    "google-chrome", "chrome") if (p := shutil.which(cmd))), None)
                options = {"headless": True,
                    "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                if binary:
                    options["executable_path"] = binary
                browser = pw.chromium.launch(**options)
                paid, errors = [], []

                def make_page(token):
                    context = browser.new_context(viewport={"width": 1280, "height": 900})
                    context.add_cookies([{"name": SESSION_COOKIE_NAME,
                        "value": token, "url": base}])
                    page = context.new_page()
                    page.add_init_script("window.__HANDRAW_TESTING__ = true")
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on("request", lambda req: paid.append(req.url)
                        if req.method == "POST" and
                        "/api/studio/generate" in req.url else None)
                    return context, page

                def state(page):
                    return page.evaluate("""() => {
                      const tab=window.CS?.tabs?.find(t=>t.id===window.CS.activeTabId);
                      const text=window.CS?.graph?.nodes?.find(n=>n.type==='text_input');
                      return {scope:window.App?.state?.user?.id, tabId:tab?.id,
                        projectId:tab?.projectId,revision:tab?.projectRevision,
                        status:tab?.projectSaveState,error:tab?.projectError,
                        pending:!!tab?.projectPending,subject:text?.data?.text||'',
                        stage:window.CS?.stageView};
                    }""")

                def update_subject(page, value):
                    inp = page.locator("#make-image-subject")
                    inp.wait_for(timeout=15000)
                    inp.fill(value)
                    inp.evaluate("(element)=>element.blur()")

                def wait_synced(page, timeout=30000):
                    try:
                        page.wait_for_function("""() => {
                          const t=window.CS?.tabs?.find(x=>x.id===window.CS.activeTabId);
                          return t?.projectSaveState==='synced' &&
                            Number(t.projectRevision)>0 && !!t.projectId;
                        }""", timeout=timeout)
                    except BrowserTimeout:
                        raise AssertionError({"expected": "synced", "state": state(page),
                            "errors": errors})

                def get_project(page, id_):
                    return page.evaluate("""async id => {
                      const r=await fetch('/api/studio/projects/'+encodeURIComponent(id),{
                        credentials:'include'});
                      return {status:r.status, body:await r.json()};
                    }""", id_)

                ctx_a, page_a = make_page(token_a)
                page_a.goto(base + "/studio/?entry=quick", wait_until="networkidle",
                    timeout=45000)
                update_subject(page_a, "103 在线第一版")
                wait_synced(page_a)
                online = state(page_a)
                assert online["subject"] == "103 在线第一版", online
                project_id = online["projectId"]
                created = get_project(page_a, project_id)
                assert created["status"] == 200, created
                assert created["body"]["project"]["revision"] == online["revision"]
                print("103 online acknowledgement: PASS", flush=True)

                # Reload must recover the same project graph and revision.
                page_a.reload(wait_until="networkidle", timeout=45000)
                page_a.locator("#make-image-subject").wait_for(timeout=15000)
                after_reload = state(page_a)
                assert after_reload["projectId"] == project_id, after_reload
                assert after_reload["subject"] == "103 在线第一版", after_reload
                assert after_reload["revision"] == online["revision"], after_reload
                print("103 refresh and Graph identity: PASS", flush=True)

                # Disconnect the real browser network, edit the original graph,
                # verify the locally scoped outbox, then reconnect.
                ctx_a.set_offline(True)
                update_subject(page_a, "103 离线改稿")
                page_a.wait_for_function("""() => {
                  const t=window.CS.tabs.find(x=>x.id===window.CS.activeTabId);
                  return t?.projectSaveState==='error' && !!t.projectPending;
                }""", timeout=30000)
                offline = state(page_a)
                persisted = page_a.evaluate("""() => {
                  const key=Object.keys(localStorage).find(k=>
                    k.startsWith('handraw_open_tabs_v10::user_'));
                  const tabs=JSON.parse(localStorage.getItem(key)||'{}').tabs||[];
                  const tab=tabs.find(t=>t.projectId===window.CS.tabs.find(
                    x=>x.id===window.CS.activeTabId)?.projectId);
                  return {key,subject:tab?.graph?.nodes?.find(n=>n.type==='text_input')?.data?.text,
                    pending:tab?.projectPending,saveState:tab?.projectSaveState};
                }""")
                assert persisted["key"] and persisted["pending"], persisted
                assert persisted["subject"] == "103 离线改稿", persisted
                ctx_a.set_offline(False)
                # Refresh with the original outbox still on disk. The page
                # must restore and replay its frozen key without losing edits.
                page_a.reload(wait_until="networkidle", timeout=45000)
                wait_synced(page_a)
                restored = state(page_a)
                assert restored["projectId"] == project_id, restored
                assert restored["revision"] > online["revision"], (online, restored)
                fresh = get_project(page_a, project_id)["body"]["project"]
                assert any(n.get("data",{}).get("text") == "103 离线改稿"
                    for n in fresh["draft"]["graph"]["nodes"]), fresh
                assert not restored["pending"]
                print("103 offline outbox/reconnect: PASS", flush=True)

                # Same owner, independent browser context: both start at the
                # same CAS base; the second writer must not silently overwrite.
                ctx_two, page_two = make_page(token_a)
                page_two.goto(base + "/studio/?project=" + project_id,
                    wait_until="networkidle", timeout=45000)
                page_two.locator("#make-image-subject").wait_for(timeout=20000)
                initial_two = state(page_two)
                assert initial_two["projectId"] == project_id, initial_two
                assert initial_two["revision"] == restored["revision"], initial_two
                update_subject(page_two, "103 第二标签提交")
                wait_synced(page_two)
                committed_two = state(page_two)
                assert committed_two["revision"] > restored["revision"]
                update_subject(page_a, "103 第一标签冲突草稿")
                page_a.wait_for_function("""() => {
                  const t=window.CS.tabs.find(x=>x.id===window.CS.activeTabId);
                  return t?.projectSaveState==='conflict' && !!t.projectPending;
                }""", timeout=30000)
                assert "103 第二标签提交" in json.dumps(
                    get_project(page_a, project_id), ensure_ascii=False)
                assert state(page_a)["subject"] == "103 第一标签冲突草稿"
                # Conflict UI must offer all explicit choices, never auto-merge.
                conflict_button = page_a.locator("#studio-project-status")
                if conflict_button.count() == 0:
                    conflict_button = page_a.locator("#bl-save-project")
                conflict_button.first.click()
                page_a.locator("#studio103-conflict-copy").wait_for(timeout=15000)
                assert page_a.locator("#studio103-conflict-discard").count() == 1
                assert "103 第二标签提交" in page_a.locator(".studio103-diff").inner_text()
                page_a.locator("#studio103-conflict-copy").click()
                wait_synced(page_a)
                copied = state(page_a)
                assert copied["projectId"] != project_id, (copied, restored)
                assert copied["subject"] == "103 第一标签冲突草稿"
                assert "103 第二标签提交" in json.dumps(
                    get_project(page_a, project_id), ensure_ascii=False)
                print("103 two-tab CAS/copy and diff UI: PASS", flush=True)

                # A same-browser account switch must isolate persisted tabs and
                # cloud data (not merely hide A's private card).
                ctx_a.clear_cookies()
                ctx_a.add_cookies([{"name": SESSION_COOKIE_NAME,
                    "value": token_b, "url": base}])
                page_a.goto(base + "/studio/?entry=quick", wait_until="networkidle",
                    timeout=45000)
                page_a.locator("#make-image-subject").wait_for(timeout=15000)
                bob_ids = page_a.evaluate("""() => ({
                  scope:window.App?.state?.user?.id,
                  projectIds:window.CS.tabs.map(t=>t.projectId).filter(Boolean),
                  localIds:(window.CS.closedProjectDrafts||[]).map(t=>t.projectId)
                })""")
                # App is module-private; the authenticated owner-scoped HTTP response
                # is the authority for account identity, not a window.App guess.
                bob_projects = page_a.evaluate("""async () => {
                  const r=await fetch('/api/studio/projects',{credentials:'include'});
                  return {status:r.status,body:await r.json()};
                }""")
                assert bob_projects["status"] == 200, bob_projects
                assert bob_projects["body"]["projects"] == [], bob_projects
                assert project_id not in bob_ids["projectIds"], bob_ids
                assert copied["projectId"] not in bob_ids["projectIds"], bob_ids
                assert project_id not in bob_ids["localIds"], bob_ids
                assert get_project(page_a, project_id)["status"] == 404
                print("103 account switch / ACL: PASS", flush=True)

                out = ROOT / "artifacts" / "project-103-screen"
                out.mkdir(parents=True, exist_ok=True)
                page_two.screenshot(path=str(out / "cloud-restore.png"),
                    animations="disabled")
                (out / "results.json").write_text(json.dumps({
                    "result": "PASS", "onlineRevision": online["revision"],
                    "offlineRecoveredRevision": restored["revision"],
                    "secondTabRevision": committed_two["revision"],
                    "conflictCopy": copied["projectId"] != project_id,
                    "accountIsolated": True, "paidRequests": len(paid),
                    "scenarios": ["online", "offline/reconnect", "two-tab CAS",
                        "account switch", "reload/graph"]
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                assert not paid, paid
                assert not errors, errors
                browser.close()
                print("STUDIO #103 REAL CHROMIUM FIVE-SCENARIO RELIABILITY PASS", flush=True)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:
                thread.join(timeout=3)
            if db:
                db.close()
            environment.stop()


if __name__ == "__main__":
    main()
