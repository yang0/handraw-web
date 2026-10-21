"""Reject runtime data and obvious credentials in the committed source set."""
import re
import subprocess
from pathlib import Path

paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
issues = []
for name in filter(None, paths):
    path = Path(name)
    if name.startswith(("web/", "statics/", ".local/", "backups/")) or path.name in {"community_auth.json", ".env", "credentials.json", "image-service.json"}:
        issues.append(f"Private/runtime file tracked: {name}")
    if path.suffix in {".pem", ".key", ".sql", ".zip", ".gz"}:
        issues.append(f"Sensitive/generated artifact tracked: {name}")
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}", text):
        issues.append(f"Credential-like content: {name}")
if issues:
    raise SystemExit("\n".join(issues))
print(f"Release boundary check passed for {len(paths) - 1} tracked files")
