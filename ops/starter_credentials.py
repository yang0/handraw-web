"""Write generated starter credentials to the private storage directory."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from backend.config import get_storage_root


def write_credentials(records: list[dict]) -> Path:
    folder = get_storage_root()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"starter_credentials.{uuid.uuid4().hex}.json"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(records, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path
