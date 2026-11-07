"""Public creator avatar upload; image bytes stay in private storage.

Only the generated square WebP is publicly served at /avatars/<filename>.
Uploaded payloads are decoded and re-encoded, never served directly.
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import secrets
from pathlib import Path
from typing import Any

from .config import get_storage_root
from .services import ServiceError

AVATAR_DEFAULT_URL = "/assets/avatar-default.svg"
MAX_AVATAR_BYTES = 3 * 1024 * 1024
AVATAR_EDGE = 320
AVATAR_PATTERN = re.compile(r"^u[1-9][0-9]*-[a-f0-9]{20}\.webp$")
_AVATAR_DATA = re.compile(r"^data:image/(?:jpeg|png|webp);base64,([a-zA-Z0-9+/=\s]+)$", re.IGNORECASE)


def avatar_dir() -> Path:
    return get_storage_root() / "avatars"


def avatar_file_for_path(url_path: str) -> Path | None:
    name = str(url_path or "").removeprefix("/avatars/")
    if not AVATAR_PATTERN.fullmatch(name):
        return None
    target = (avatar_dir() / name).resolve()
    if not target.is_relative_to(avatar_dir().resolve()):
        return None
    return target


def save_avatar(db: Any, user: dict[str, Any], data_url: str) -> dict[str, Any]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    raw = str(data_url or "")
    if len(raw) > MAX_AVATAR_BYTES * 2:
        raise ServiceError("头像文件不能超过 3 MB", status=413, code="avatar_too_large")
    match = _AVATAR_DATA.fullmatch(raw)
    if not match:
        raise ServiceError("请上传 JPG、PNG 或 WebP 图片", code="avatar_type")
    try:
        image_bytes = base64.b64decode(match.group(1), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ServiceError("头像图片无效", code="avatar_invalid") from exc
    if not image_bytes or len(image_bytes) > MAX_AVATAR_BYTES:
        raise ServiceError("头像文件不能超过 3 MB", status=413, code="avatar_too_large")
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.width < 32 or source.height < 32 or source.width * source.height > 16_000_000:
                raise ServiceError("头像尺寸需至少 32×32，且不得超过 1600 万像素", code="avatar_dimensions")
            source = ImageOps.exif_transpose(source)
            # Crop centrally, not distort, then re-encode to remove metadata/scripts.
            square = ImageOps.fit(source.convert("RGB"), (AVATAR_EDGE, AVATAR_EDGE), method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            square.save(output, "WEBP", quality=85, method=4)
            encoded = output.getvalue()
    except ServiceError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ServiceError("无法读取这张图片，请更换 JPG、PNG 或 WebP 头像", code="avatar_invalid") from exc

    uid = int(user["id"])
    filename = f"u{uid}-{secrets.token_hex(10)}.webp"
    folder = avatar_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    url = f"/avatars/{filename}"
    from .media_storage import persist_media_bytes
    persist_media_bytes(url, encoded, mime="image/webp")
    try:
        with db.transaction() as tx:
            existing = tx.execute("SELECT avatar_url FROM users WHERE id=?", (uid,)).fetchone()
            updated = tx.execute("UPDATE users SET avatar_url=? WHERE id=? AND status='active'", (url, uid))
            if updated.rowcount != 1:
                raise ServiceError("登录账号无效", status=403)
            previous = str(existing["avatar_url"] or "") if existing else ""
            if previous.startswith("/avatars/") and previous != url:
                from .media_gc import queue_media_cleanup
                queue_media_cleanup(tx, previous)
    except Exception:
        target.unlink(missing_ok=True)
        try:
            from .object_storage import delete_private_object
            delete_private_object(url)
        except Exception:
            # Preserve a retryable cleanup intent if the remote delete fails.
            try:
                with db.transaction() as tx:
                    from .media_gc import queue_media_cleanup
                    queue_media_cleanup(tx, url, delay_seconds=60)
            except Exception:
                pass
        raise
    return {"ok": True, "avatarUrl": url}


def reset_avatar(db: Any, user: dict[str, Any]) -> dict[str, Any]:
    with db.transaction() as tx:
        uid = int(user["id"])
        previous_row = tx.execute("SELECT avatar_url FROM users WHERE id=?", (uid,)).fetchone()
        updated = tx.execute("UPDATE users SET avatar_url='' WHERE id=? AND status='active'", (uid,))
        if updated.rowcount != 1:
            raise ServiceError("登录账号无效", status=403)
        previous = str(previous_row["avatar_url"] or "") if previous_row else ""
        if previous.startswith("/avatars/"):
            from .media_gc import queue_media_cleanup
            queue_media_cleanup(tx, previous)
    return {"ok": True, "avatarUrl": AVATAR_DEFAULT_URL}
