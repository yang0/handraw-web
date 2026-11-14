"""Bounded, stat-aware encoding cache for public frontend source files."""

import gzip
import hashlib
import html
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@lru_cache(maxsize=128)
def _content_digest(path: str, modified_ns: int, changed_ns: int, size: int):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:24]


def version_frontend_html(raw: bytes, root: Path) -> bytes:
    """Give local code its content identity, including matching preload URLs."""
    root = root.resolve()

    def replace(match):
        value = urlsplit(html.unescape(match.group(3)))
        if value.scheme or value.netloc or not value.path.startswith("/assets/"):
            return match.group(0)
        target = (root / value.path.lstrip("/")).resolve()
        if (
            not target.is_relative_to(root)
            or target.suffix not in (".js", ".css")
            or not target.is_file()
        ):
            return match.group(0)
        stat = target.stat()
        digest = _content_digest(
            str(target), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
        )
        query = [
            (key, val)
            for key, val in parse_qsl(value.query, keep_blank_values=True)
            if key != "v"
        ]
        query.append(("v", digest))
        url = urlunsplit(("", "", value.path, urlencode(query), value.fragment))
        return (
            match.group(1)
            + match.group(2)
            + html.escape(url, quote=True)
            + match.group(2)
        )

    # Match only actual script/link opening tags, never resource-like prose.
    def tag(match):
        return re.sub(
            r"(\b(?:src|href)\s*=\s*)([\"'])(.*?)\2",
            replace,
            match.group(0),
            flags=re.I,
        )

    return re.sub(
        r"<(?:script|link)\b[^>]*>", tag, raw.decode("utf-8"), flags=re.I
    ).encode("utf-8")


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
