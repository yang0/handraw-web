import builtins
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.server import check_optional_dependencies, main


class StartupDependenciesSelfCheckTests(unittest.TestCase):
    def test_check_optional_dependencies_warns_on_missing_fitz(self) -> None:
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError("No module named 'fitz'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertLogs("backend.server", level="WARNING") as cm:
                check_optional_dependencies()
            self.assertTrue(
                any("PyMuPDF" in msg and "requirements.txt" in msg for msg in cm.output),
                f"Expected warning mentioning PyMuPDF and requirements.txt, got {cm.output}",
            )

    def test_check_optional_dependencies_warns_on_missing_docx(self) -> None:
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "docx":
                raise ImportError("No module named 'docx'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertLogs("backend.server", level="WARNING") as cm:
                check_optional_dependencies()
            self.assertTrue(
                any("python-docx" in msg and "requirements.txt" in msg for msg in cm.output),
                f"Expected warning mentioning python-docx and requirements.txt, got {cm.output}",
            )

    @patch.dict(os.environ, {"HANDRAW_DATABASE_URL": "postgresql://localhost/test", "HANDRAW_PG_RUNTIME_ACK": "V3_NATIVE", "HANDRAW_REDIS_REQUIRED": "1"})
    @patch("backend.server._load_env_file_if_present")
    @patch("backend.observability.configure_logging")
    def test_server_startup_continues_when_fitz_missing(self, _logging, _env_file) -> None:
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError("No module named 'fitz'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with patch("backend.server.Database") as mock_init:
                with patch("backend.server.create_channel_server") as mock_srv:
                    with patch("backend.server.GenerationReconciler"), patch("backend.server.ensure_seeded"), patch("backend.redis_rate_limit.ensure_ready"):
                        mock_srv.return_value.serve_forever.side_effect = KeyboardInterrupt
                        with self.assertLogs("backend.server", level="WARNING") as cm:
                            main(["--port", "3999"])
                        self.assertTrue(any("PyMuPDF" in msg for msg in cm.output))
                        mock_init.assert_called_once_with("postgresql://localhost/test")

    @patch.dict(os.environ, {"HANDRAW_DATABASE_URL": ""})
    @patch("backend.server._load_env_file_if_present")
    @patch("backend.observability.configure_logging")
    def test_server_requires_postgres_url(self, _logging, _env_file) -> None:
        with self.assertRaisesRegex(RuntimeError, "HANDRAW_DATABASE_URL"):
            main([])
