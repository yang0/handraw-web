"""Extract image dimensions safely from local media storage."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from PIL import Image

from .config import DEFAULT_STYLE_IMAGES_DIR, get_generated_dir, get_uploads_dir
from .runtime_policy import include_private_benchmark_assets


def _path_is_within(path: Path, root: Path) -> bool:
    """Path containment check that does not mistake /root2 for /root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@lru_cache(maxsize=2048)
def _cached_image_size(path: str, mtime_ns: int, file_size: int) -> tuple[int, int] | None:
    """File-versioned Pillow header probe; bounded process-local cache.

    Only successful probes are cached long-term in practice; the caller avoids
    probing missing files, while corrupt files can be retried after replacement.
    """
    with Image.open(path) as img:
        return int(img.width), int(img.height)


def is_square(w: int, h: int) -> bool:
    """Determine whether (w, h) qualifies as a square within 1% tolerance."""
    if w <= 0 or h <= 0:
        return False
    return abs(w - h) <= max(2, round(0.01 * max(w, h)))


def image_size(url: str | None) -> tuple[int, int] | None:
    """Resolve the (w, h) pixel dimensions of an uploaded, generated, or style image.

    Only resolves local media under /uploads/, /generated/, and /images/ roots with strict path
    traversal containment checks matching server.py media routes. Returns None for
    external URLs, non-existent files, unreadable files, or path traversal attempts.
    """
    if not isinstance(url, str):
        return None
    s = url.strip()
    if not s:
        return None
    clean = s.split("?", 1)[0].split("#", 1)[0]
    for prefix, getter in (
        ("/uploads/", get_uploads_dir),
        ("/generated/", get_generated_dir),
        ("/images/", lambda: DEFAULT_STYLE_IMAGES_DIR),
    ):
        if clean.startswith(prefix):
            rel = clean.removeprefix(prefix).lstrip("/")
            if prefix == "/images/" and rel.lower().startswith("custom/") and not include_private_benchmark_assets():
                return None
            root_dir = getter()
            if not root_dir.exists():
                return None
            target = (root_dir / rel).resolve()
            if not _path_is_within(target, root_dir) or not target.is_file():
                return None
            try:
                stat = target.stat()
            except OSError:
                return None
            try:
                return _cached_image_size(str(target), stat.st_mtime_ns, stat.st_size)
            except Exception:
                return None
    return None
