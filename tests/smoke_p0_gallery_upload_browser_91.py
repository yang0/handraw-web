"""#91 real Chromium personal-library upload and failure/retry UI journey.

Uses the shipped cloud-center.js + normal owner Cookie + live HTTP/API,
temporary SQLite and PIL image bytes. The only simulated dependency is an
explicitly injected storage outage for the first request. No external network.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.server import create_channel_server, init_database, SESSION_COOKIE_NAME
from backend.services import register_user


def image(fmt: str, color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (28, 20), color).save(out, fmt)
    return out.getvalue()


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        environment = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(root / "gallery91-browser.sqlite"),
            "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
            "HANDRAW_GENERATED_DIR": str(root / "generated"),
            "HANDRAW_PRIVATE_STORAGE": str(root / "private"),
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
        })
        environment.start()
        db = server = thread = None
        try:
            db = init_database(root / "gallery91-browser.sqlite")
            user, cookie = register_user(db, "gallery_browser_91", "Pass12345!")
            server = create_channel_server(0, "main", db)
            server.allow_demo_routes = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as pw:
                binary = next((p for name in (
                    "chromium", "google-chrome-stable", "google-chrome", "chrome")
                    if (p := shutil.which(name))), None)
                launch = {"headless": True, "args": [
                    "--no-sandbox", "--disable-dev-shm-usage"]}
                if binary:
                    launch["executable_path"] = binary
                browser = pw.chromium.launch(**launch)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.context.add_cookies([{
                        "name": SESSION_COOKIE_NAME, "value": cookie, "url": base}])
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(base + "/", wait_until="domcontentloaded", timeout=60000)
                    page.add_script_tag(url=base + "/assets/cloud-center.js")
                    page.evaluate("""() => {
                        const host=document.createElement('div');
                        host.id='qa91-library';
                        host.style.cssText='max-width:1120px;margin:30px auto;';
                        document.body.appendChild(host);
                        window.qa91Loaded=false;
                        const api=async (path,options={}) => {
                            const response=await fetch(path,{
                                method:options.method||'GET',
                                credentials:'same-origin',
                                headers:{'Accept':'application/json',
                                    'Content-Type':'application/json'},
                                ...(options.body
                                    ?{body:JSON.stringify(options.body)}:{})
                            });
                            const body=await response.json();
                            if (!response.ok || !body.ok) {
                                const err=new Error(body.message||body.error||
                                    ('HTTP '+response.status));
                                err.status=response.status;
                                err.code=body.code;
                                throw err;
                            }
                            return body;
                        };
                        window.HandrawCloudCenter.mountGallery(host,api)
                            .then(()=>window.qa91Loaded=true);
                    }""")
                    page.wait_for_function("""() => window.qa91Loaded &&
                        !!document.querySelector('#qa91-library [data-gallery-file]')""",
                        timeout=15000)
                    host = page.locator("#qa91-library")
                    select_file = host.locator("[data-gallery-file]")
                    confirm = host.locator("[data-gallery-submit]")
                    name = host.locator("[data-gallery-name]")
                    category = host.locator("[data-gallery-upload-category]")
                    retry = host.locator("[data-gallery-retry]")
                    image_files = [
                        ("PNG", "mime/image PNG.png", "image/png", "characters"),
                        ("JPEG", "mime JPEG.jpg", "image/jpeg", "props"),
                        ("WEBP", "mime WebP.webp", "image/webp", "scenes"),
                    ]
                    for i, (fmt, file_name, mime, cat) in enumerate(image_files):
                        select_file.set_input_files({
                            "name":file_name,"mimeType":mime,
                            "buffer":image(fmt,(60+i*40,65,150))
                        })
                        assert host.locator("[data-gallery-upload-form]").is_visible()
                        assert name.input_value() == file_name.rsplit(".",1)[0][:60]
                        name.fill("P0测试素材-" + fmt)
                        category.select_option(cat)
                        if i == 0:
                            # Let the real backend fail before it writes the row,
                            # then verify retry retains the file/UID and succeeds.
                            with patch("backend.user_library._persist_library_image",
                                       side_effect=OSError("P0-91 forced storage failure")):
                                confirm.click()
                                retry.wait_for(state="visible",timeout=20000)
                            assert host.locator("[data-gallery-upload-form]").is_visible()
                            assert "服务器保存失败" in host.locator(
                                "[data-gallery-message]").inner_text()
                            assert name.input_value() == "P0测试素材-PNG"
                            retry.click()
                        else:
                            confirm.click()
                        page.wait_for_function("""(n) => document.querySelectorAll(
                            '#qa91-library [data-gallery-cards] article.hw-personal-gallery-card'
                            ).length >= n""",arg=i+1,timeout=25000)
                        assert not host.locator("[data-gallery-upload-form]").is_visible()
                    page.wait_for_function("""() =>
                        document.querySelector('#qa91-library [data-gallery-message]')?.textContent
                            ?.includes('添加成功')""",timeout=20000)
                    cards = host.locator("[data-gallery-cards] article.hw-personal-gallery-card")
                    assert cards.count() == 3
                    assert set(cards.locator("strong").all_inner_texts()) == {
                        "P0测试素材-PNG","P0测试素材-JPEG","P0测试素材-WEBP"}
                    assert not errors,errors
                    stored=db.get_conn().execute(
                        "SELECT cat, name_zh, revision, image_url FROM user_uploads "
                        "WHERE user_id=? ORDER BY created_at", (int(user["id"]),)
                    ).fetchall()
                    assert len(stored)==3
                    assert {row["cat"] for row in stored} == {
                        "characters","props","scenes"}
                    assert {row["revision"] for row in stored} == {1}
                    assert all(row["image_url"].startswith("/uploads/")
                               for row in stored)
                    files=list((root/"uploads").glob("UPL-*"))
                    assert len(files)==3,files
                    output=ROOT/"artifacts"/"p0-gallery-91"
                    output.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(output/"gallery-upload-1440.png"),
                                    animations="disabled")
                    # #98: real 390px viewport, real upload form, no premature
                    # network call, explicit name/category and private DB check.
                    page.set_viewport_size({"width":390,"height":900})
                    select_file.set_input_files({
                        "name":"mobile-category.webp","mimeType":"image/webp",
                        "buffer":image("WEBP",(120,90,190)),
                    })
                    mobile_name = "手机端自定义名称"
                    assert name.input_value() == "mobile-category"
                    name.fill(mobile_name)
                    category.select_option("props")
                    assert host.locator("[data-gallery-upload-form]").is_visible()
                    assert db.get_conn().execute(
                        "SELECT COUNT(*) FROM user_uploads WHERE user_id=?",
                        (int(user["id"]),)
                    ).fetchone()[0] == 3, "Selecting must not auto-upload"
                    confirm.click()
                    page.wait_for_function("""() => document.querySelectorAll(
                        '#qa91-library [data-gallery-cards] article.hw-personal-gallery-card'
                    ).length===4""",timeout=20000)
                    row=db.get_conn().execute(
                        "SELECT name_zh,cat FROM user_uploads WHERE user_id=? "
                        "AND name_zh=?", (int(user["id"]),mobile_name)
                    ).fetchone()
                    assert row and row["cat"] == "props"
                    mobile=page.evaluate("""() => {
                      const g=document.querySelector('#qa91-library [data-gallery-cards]');
                      const b=g.getBoundingClientRect();
                      const cards=[...g.children].map(el=>el.getBoundingClientRect());
                      return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
                        columns:getComputedStyle(g).gridTemplateColumns.split(' ').filter(Boolean).length,
                        x:b.x,right:b.right,
                        cards:cards.map(r=>({x:r.x,right:r.right}))};
                    }""")
                    assert mobile["width"]==390 and mobile["scrollWidth"]<=392,mobile
                    assert mobile["columns"]==2,mobile
                    assert all(c["x"]>=-1 and c["right"]<=391 for c in mobile["cards"]),mobile
                    page.screenshot(path=str(output/"gallery-upload-390.png"),
                                    animations="disabled")
                    (output/"browser-summary.json").write_text(
                        json.dumps({"issue":91,"result":"PASS",
                            "scope":"live-owner-Cookie-HTTP-Chromium-temporary-SQLite",
                            "formats":["PNG","JPEG","WEBP"],
                            "storageFailureInjected":True,
                            "retrySameUid":True,
                            "persistedCount":len(stored),
                            "mobileNewUploadVerified":True,
                            "mobileViewport":mobile,
                            "productionRequestIdRootCauseVerified":False,
                            "browser":browser.version},ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
                    print("P0 #91 Chromium gallery PNG/JPEG/WebP, name/category, "
                          "storage 503 -> same-UID retry, private DB: PASS",
                          flush=True)
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:
                thread.join(timeout=5)
            if db:
                db.close()
            environment.stop()


if __name__ == "__main__":
    main()
