"""Issue #87: zero-tolerance native dialog gate for shipped JavaScript.

Every browser-native alert/confirm/prompt blocks interaction, breaks async
cancellation semantics and is forbidden in application JS (demo + plugin).
Test fixtures, documentation and third-party dependencies are not app source.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("demo/assets", "plugin/public")
# Covers the three native functions in both direct and window/globalThis/self form.
CALL = re.compile(
    r"(?<![\w.])(?:(?:window|globalThis|self)\s*\.\s*)?"
    r"(alert|confirm|prompt)\s*\("
)


def scan():
    findings = []
    for folder in SOURCE_ROOTS:
        for file in sorted((ROOT / folder).rglob("*.js")):
            relative = file.relative_to(ROOT).as_posix()
            for line_no, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                for match in CALL.finditer(line):
                    findings.append({
                        "file": relative,
                        "line": line_no,
                        "type": match.group(1),
                    })
    return findings


class NativeDialogInventory87(unittest.TestCase):
    def test_no_native_browser_dialogs_in_application_code(self):
        findings = scan()
        report = {
            "issue": 87,
            "status": "NO_NATIVE_DIALOGS" if not findings else "FAIL_NATIVE_DIALOGS",
            "nativeCallsRemaining": len(findings),
            "codeAndBrowserUXDone": not findings,
            "scope": "shipped JS under demo/assets and plugin/public; excludes tests/docs/vendor",
            "findings": findings,
        }
        output = ROOT / "artifacts" / "native-dialog-audit-87.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual([], findings, "Use genuine async in-app dialog/notice with cancel, "
                         "Escape and explicit approval; no confirm()=>true stubs.")

    def test_no_confirmation_bypass_stubs(self):
        # Do not replace destructive confirms with always-true shims.
        bypass = re.compile(
            r"(?:window\.)?confirm\s*=\s*(?:\(\s*\)\s*=>\s*true|function\s*\(\s*\)\s*\{\s*return\s+true)",
            re.I,
        )
        for folder in SOURCE_ROOTS:
            for file in sorted((ROOT / folder).rglob("*.js")):
                self.assertNotRegex(file.read_text(encoding="utf-8"), bypass,
                                    "Do not bypass user confirmation: " + file.as_posix())


if __name__ == "__main__":
    unittest.main()
