#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"

if [ ! -d ".venv" ] || [ ! -x ".venv/bin/python" ]; then
  "$PYTHON" -m venv .venv
fi

.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import docx, fitz, PIL"
