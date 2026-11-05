"""Regression checks for the Windows local server startup preflight.

The PowerShell wrapper must not import deprecated fitz at startup, and an
optional package probe should never fail due to a FutureWarning.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class WindowsLocalServiceScriptTests(unittest.TestCase):
    def test_preflight_is_warning_free_and_syntax_valid(self):
        source = (REPO / "ops" / "local-service.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$localPython = Join-Path $projectRoot '.venv\\Scripts\\python.exe'", source)
        marker = "$checkScript = @'\n"
        self.assertIn(marker, source)
        script = source.split(marker, 1)[1].split("\n'@", 1)[0]
        compile(script, "<local-service-dependency-probe>", "exec")
        self.assertIn("importlib.util.find_spec", script)
        self.assertNotIn("__import__", script)
        result = subprocess.run(
            [sys.executable, "-W", "error::FutureWarning", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stderr, "Dependency probe should not write to stderr")

    def test_document_parser_prefers_modern_pymupdf_name(self):
        source = (REPO / "backend" / "document_parser.py").read_text(encoding="utf-8")
        self.assertIn("import pymupdf as fitz", source)
        self.assertIn("except ImportError:\n                import fitz", source)


if __name__ == "__main__":
    unittest.main()
