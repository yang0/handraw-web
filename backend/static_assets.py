"""Bounded, stat-aware encoding cache for public frontend source files."""

import gzip
import hashlib
from functools import lru_cache
from pathlib import Path


def accepts_gzip(value: str) -> bool:
    choices = {}
    for part in value.lower().split(","):
        coding, *parameters = part.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        choices[coding] = quality
    return choices.get("gzip", choices.get("*", 0)) > 0


@lru_cache(maxsize=64)
def _encoded_file(path: str, modified_ns: int, changed_ns: int, size: int):
    raw = Path(path).read_bytes()
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    return raw, compressed, hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=8)
def _encoded_data(raw: bytes):
    return (
        raw,
        gzip.compress(raw, compresslevel=6, mtime=0),
        hashlib.sha256(raw).hexdigest(),
    )


def _representation(parts, accept_encoding):
    raw, compressed, digest = parts
    encoded = accepts_gzip(accept_encoding) and len(compressed) < len(raw)
    return (
        (compressed if encoded else raw),
        ("gzip" if encoded else ""),
        f'"{digest}{"-gzip" if encoded else ""}"',
    )


def data_representation(raw: bytes, accept_encoding: str):
    return _representation(_encoded_data(raw), accept_encoding)


def file_representation(path: Path, accept_encoding: str):
    stat = path.stat()
    return _representation(
        _encoded_file(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size),
        accept_encoding,
    )
