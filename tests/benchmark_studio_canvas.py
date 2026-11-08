"""Issue #127: reproducible Chromium Canvas DOM/selection/focus benchmark.

Run from repository root:
    python -m pip install playwright
    python tests/benchmark_studio_canvas.py --output artifacts/canvas-127.json

Uses installed Chromium/Chrome on the host or a Playwright browser binary.
All data is local; no paid image or AI gateway. Reports measured timings rather
than imposing an invented performance budget before the first baseline.
"""
from __future__ import annotations

import argparse
import functools
import json
import platform
import shutil
import sys
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/canvas-127.json")
    parser.add_argument("--require-browser", action="store_true")
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        if args.require_browser:
            raise RuntimeError("Missing playwright: pip install playwright") from exc
        print("SKIP: Playwright not installed", file=sys.stderr)
        return

    class SilentHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

    factory = functools.partial(SilentHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), factory)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as pw:
            executable = next((p for n in ("chromium", "google-chrome-stable",
                    "google-chrome", "chrome") if (p := shutil.which(n))), None)
            options = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage",
                         "--enable-precise-memory-info"],
            }
            if executable:
                options["executable_path"] = executable
            try:
                browser = pw.chromium.launch(**options)
            except Exception as exc:
                if args.require_browser:
                    raise RuntimeError("Chromium not available; install chromium or "
                                       "run playwright install chromium") from exc
                print("SKIP: Chromium not installed", file=sys.stderr)
                return
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900},
                                        device_scale_factor=1)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}"
                          "/tests/fixtures/studio_canvas_benchmark.html",
                          wait_until="load", timeout=30000)
                results = page.evaluate("async () => await window.runCanvasBenchmark()")
                if errors:
                    raise AssertionError("Browser JavaScript errors: " + repr(errors))
                assert [m["nodes"] for m in results["measurements"]] == [10, 50, 100, 300]
                for row in results["measurements"]:
                    assert row["imagesPreserved"] and row["focusAndCursorPreserved"]
                    assert row["otherNodesReused"], row
                    assert row["domElements"] >= row["nodes"]
                    assert row["singleStatusP95Ms"] >= 0
                    assert row["dragZoomFrameP95Ms"] > 0
                results.update({
                    "recordedAt": datetime.now(timezone.utc).isoformat(),
                    "chromeVersion": browser.version,
                    "host": {"python": platform.python_version(),
                             "system": platform.platform(),
                             "machine": platform.machine()},
                    "kind": "synthetic-real-Chromium",
                    "gate": "DOM/focus/image correctness; latency numbers are baseline",
                })
                location = ROOT / args.output
                location.parent.mkdir(parents=True, exist_ok=True)
                location.write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n")
                print(json.dumps(results, ensure_ascii=False, indent=2))
                print("CANVAS #127 browser benchmark PASS | " + str(location))
                page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()
