"""Idempotently route only the site root to the verified portal; preserve all other paths."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("input", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
text = args.input.read_text(encoding="utf-8")
marker = "# handraw-portal-home"
if marker not in text:
    original = "    location / {"
    if text.count(original) != 1:
        raise SystemExit("Expected exactly one existing root proxy; configuration unchanged")
    addition = """    # handraw-portal-home
    location = / {
        proxy_pass http://discourse_app/studio;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

"""
    text = text.replace(original, addition + original)
args.output.write_text(text, encoding="utf-8")
