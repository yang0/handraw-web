"""Extract image dimensions safely from local media storage."""
from __future__ import annotations

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
                with Image.open(target) as img:
                    return int(img.width), int(img.height)
            except Exception:
                return None
    return None
