"""Reject runtime data and obvious credentials in the committed source set."""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.bootstrap_postgres_v3 import BASELINE_PATH, MIGRATIONS, ROOT


schema_sources = {path.relative_to(ROOT).as_posix() for path in (BASELINE_PATH, *MIGRATIONS)}
paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
issues = []
for name in filter(None, paths):
    path = Path(name)
    if name.startswith(("web/", "statics/", ".local/", "backups/")) or path.name in {
        "community_auth.json",
        ".env",
        "credentials.json",
        "image-service.json",
        "ai-service.json",
        "payment-service.json",
    }:
        issues.append(f"Private/runtime file tracked: {name}")
    suffix = path.suffix.lower()
    if suffix in {".pem", ".key", ".zip", ".gz", ".db", ".dump"} or (
        suffix.startswith(".sql") and (suffix != ".sql" or name not in schema_sources)
    ):
        issues.append(f"Sensitive/generated artifact tracked: {name}")
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if name in schema_sources and re.search(r"^-- PostgreSQL database dump|^COPY .+ FROM stdin;$", text, re.M):
        issues.append(f"Database dump tracked as schema source: {name}")
    if re.search(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}", text):
        issues.append(f"Credential-like content: {name}")
if issues:
    raise SystemExit("\n".join(issues))
print(f"Release boundary check passed for {len(paths) - 1} tracked files")
