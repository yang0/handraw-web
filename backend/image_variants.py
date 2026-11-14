"""Size-specific WebP derivatives; callers must authorize the original first."""

import hashlib
import io
import mimetypes
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import get_storage_root

THUMB_WIDTHS = (48, 96, 160, 240, 320, 480, 640, 960, 1280, 1600, 1920, 2560)
ENCODER_VERSION = "webp-v2-orientation"
_locks = [threading.Lock() for _ in range(64)]
_prune_lock = threading.Lock()
_encode_slots = threading.BoundedSemaphore(2)
_last_prune = {}


def get_thumb_cache_dir() -> Path:
    explicit = os.environ.get("HANDRAW_THUMB_CACHE_DIR")
    return Path(explicit).resolve() if explicit else get_storage_root() / "thumbs"


def normalize_thumb_width(raw) -> int:
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError):
        return 0
    return (
        next((width for width in THUMB_WIDTHS if value <= width), THUMB_WIDTHS[-1])
        if value > 0
        else 0
    )


def build_thumbnail(source: Path, width: int) -> bytes | None:
    try:
        from PIL import Image, ImageOps

        with _encode_slots, Image.open(source) as image:
            if getattr(image, "is_animated", False):
                return None  # Keep animation, rather than silently showing its first frame.
            image = ImageOps.exif_transpose(image)
            target_width = min(width, image.width)
            height = max(1, round(image.height * target_width / image.width))
            if image.size != (target_width, height):
                image = image.resize(
                    (target_width, height), Image.Resampling.LANCZOS, reducing_gap=3.0
                )
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert(
                    "RGBA" if image.mode == "P" or "A" in image.getbands() else "RGB"
                )
            buffer = io.BytesIO()
            image.save(
                buffer,
                format="WEBP",
                quality=55 if width <= 48 else 82,
                method=2 if width <= 48 else 4,
                icc_profile=image.info.get('icc_profile', b''),
            )
            return buffer.getvalue()
    except Exception:
        return None


def cache_key(source: Path, width: int) -> str:
    stat = source.stat()
    identity = f"{ENCODER_VERSION}\0{source.resolve()}\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}\0{stat.st_size}\0{width}"
    return hashlib.sha256(identity.encode()).hexdigest()


@contextmanager
def _process_lock(directory, stripe):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f".variant-{stripe}.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if lock.seek(0, 2) == 0:
                lock.write(b"0")
                lock.flush()
            deadline = time.monotonic() + 30
            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Image variant cache lock timed out")
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def prune_cache(directory: Path):
    """Best-effort bounded disk cache. Original files are never under this directory."""
    now = time.time()
    if now - _last_prune.get(str(directory), 0) < 60 or not _prune_lock.acquire(False):
        return
    try:
        _last_prune[str(directory)] = now
        try:
            limit = max(
                1024 * 1024,
                int(os.environ.get("HANDRAW_IMAGE_CACHE_MAX_BYTES", 512 * 1024 * 1024)),
            )
        except ValueError:
            limit = 512 * 1024 * 1024
        entries = []
        for path in directory.glob("*.webp"):
            # Even a misconfigured cache directory must never prune originals.
            if not re.fullmatch(r"[0-9a-f]{64}\.webp", path.name):
                continue
            try:
                stat = path.stat()
                entries.append((stat.st_mtime, stat.st_size, path))
            except OSError:
                pass
        total = sum(size for _, size, _ in entries)
        for modified, size, path in sorted(entries):
            if total <= limit and modified > now - 30 * 86400:
                break
            try:
                path.unlink()
                total -= size
            except OSError:
                pass
    finally:
        _prune_lock.release()


def read_with_thumbnail(source: Path, width: int) -> tuple[bytes, str, bool]:
    original_type = mimetypes.guess_type(str(source))[0] or "application/octet-stream"
    width = normalize_thumb_width(width)
    if not width or source.suffix.lower() in (".svg", ".gif"):
        return source.read_bytes(), original_type, False
    key = cache_key(source, width)
    directory = get_thumb_cache_dir()
    cached = directory / f"{key}.webp"
    try:
        if cached.is_file():
            data = cached.read_bytes()
            os.utime(cached, None)
            return data, "image/webp", True
        stripe = int(key[:8], 16) % len(_locks)
        with _locks[stripe], _process_lock(directory, stripe):
            if cached.is_file():
                return cached.read_bytes(), "image/webp", True
            payload = build_thumbnail(source, width)
            if payload is None:
                return source.read_bytes(), original_type, False
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=directory, suffix=".tmp", delete=False
                ) as output:
                    temporary = Path(output.name)
                    output.write(payload)
                temporary.replace(cached)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        prune_cache(directory)
        return payload, "image/webp", True
    except OSError:
        # A read-only/full cache must not make the original image disappear.
        payload = build_thumbnail(source, width)
        return (
            (payload, "image/webp", True)
            if payload
            else (source.read_bytes(), original_type, False)
        )
