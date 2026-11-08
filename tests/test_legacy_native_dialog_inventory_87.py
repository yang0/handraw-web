"""#87 audit gate: inventory native browser dialogs without bypassing confirmations.

Legacy native calls are an OPEN debt, not an approved UX implementation.
The existing allowlist is a decreasing baseline: additions (or new files)
are blocked in CI, removal needs no allowlist update. This intentionally
DOES NOT claim Issue #87 is complete until zero native calls remain.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {
    "demo/assets/admin-app.js": 1,
    "demo/assets/cloud-center.js": 1,
    "demo/assets/curation-ui.js": 1,
    "demo/assets/device-auth.js": 1,
    "demo/assets/forum-app.js": 6,
    "demo/assets/main-app.js": 3,
    "demo/assets/messaging.js": 21,
    "demo/assets/shared.js": 3,
    "demo/assets/studio-app.js": 2,
    "demo/assets/studio-batch.js": 1,
    "demo/assets/studio-make-image.js": 1,
    "plugin/public/portal.js": 2,
}
CALL = re.compile(r"(?<![\w.])(?:window\.)?(alert|confirm|prompt)\s*\(")


def scan():
    findings = []
    for folder in ("demo", "plugin"):
        for file in sorted((ROOT / folder).rglob("*.js")):
            relative = file.relative_to(ROOT).as_posix()
            for line_no, line in enumerate(file.read_text(
                    encoding="utf-8").splitlines(), start=1):
                for match in CALL.finditer(line):
                    findings.append({
                        "file": relative,
                        "line": line_no,
                        "type": match.group(1),
                    })
    return findings


class NativeDialogInventory87(unittest.TestCase):
    def test_no_new_browser_native_dialogs_and_keep_debt_visible(self):
        findings = scan()
        counts = {name: 0 for name in BASELINE}
        for item in findings:
            self.assertIn(
                item["file"], BASELINE,
                "New native browser dialog outside #87 debt baseline: " +
                item["file"] + ":" + str(item["line"]))
            counts[item["file"]] += 1
        for filename, count in counts.items():
            self.assertLessEqual(
                count, BASELINE[filename],
                "Native dialogs increased; use a genuine async in-app "
                "modal/notice, never confirm() => true or prompt stubs: " +
                filename)
        report = {
            "issue": 87,
            "status": "OPEN_NATIVE_DIALOG_DEBT",
            "nativeCallsRemaining": len(findings),
            "notZero": bool(findings),
            "codeAndBrowserUXDone": False,
            "scope": "demo + plugin source JS, excludes tests/docs/vendor",
            "counts": counts,
            "findings": findings,
        }
        output = ROOT / "artifacts" / "native-dialog-audit-87.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        self.assertGreater(
            len(findings), 0,
            "This debt test is meant to be removed/replaced with strict "
            "zero-native-dialog enforcement when #87 reaches zero.")


if __name__ == "__main__":
    unittest.main()
