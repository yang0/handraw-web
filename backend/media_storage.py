"""The sole persistent writer for generated and user-uploaded media.

Never store a DB media reference before this function succeeds. The public
URL stays stable regardless of local development storage or private S3/R2.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from pathlib import Path

from .config import get_generated_dir, get_uploads_dir, get_storage_root
from .object_storage import put as put_private_object

_ROOTS = {"/generated/": get_generated_dir, "/uploads/": get_uploads_dir, "/avatars/": lambda: get_storage_root() / "avatars"}


def local_path_for_url(url: str) -> Path:
    url = str(url or "").split("?", 1)[0]
    for prefix, root_fn in _ROOTS.items():
        if not url.startswith(prefix):
            continue
        rel = url[len(prefix):]
        if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
            break
        if "\\" in rel or "\x00" in rel:
            break
        root = root_fn().resolve()
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            break
        return target
    raise ValueError("Unsafe generated/upload media URL")


def persist_media_bytes(
    url: str, payload: bytes, *, mime: str | None = None,
) -> Path:
    """Atomically persist bytes locally and to an optional private object bucket.

    Immutable URL identities may be retried only with identical bytes.
    If a remote PUT fails, no database write may follow. A remote object
    created just before a later local failure can be collected by the
    independent media GC; it must never be made public by an incomplete grant.
    """
    if not isinstance(payload, bytes) or not payload or len(payload) > 32 * 1024 * 1024:
        raise ValueError("Media data is empty or exceeds 32 MiB")
    target = local_path_for_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    if target.is_file():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Existing media URL contains different bytes")
        # Still ensure object-storage durability when the bucket is enabled
        # or when retrying after a previous remote upload interruption.
        put_private_object(url, payload, mime=mime)
        return target

    descriptor, tmp = tempfile.mkstemp(prefix=".media-write-", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        put_private_object(
            url, payload,
            mime=mime or mimetypes.guess_type(str(target))[0],
        )
        # Generated/uploaded names are random or content-addressed.
        # Atomic replace hides partially written files from HTTP readers.
        if target.is_file():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("Concurrent media writer used a conflicting URL")
        else:
            os.replace(tmp, target)
            tmp = ""
        return target
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)



def discard_uncommitted_media(db: object, url: str) -> None:
    """Reclaim a newly allocated, unique media URL after SQL write rollback.

    For unique upload IDs only. Never use on a content-addressed URL that may
    already be associated with a successful generation. Any object-store
    outage is recorded as a durable GC job rather than silently leaking data.
    """
    import logging

    log = logging.getLogger("handraw.media.storage")
    from .object_storage import delete_private_object

    try:
        delete_private_object(url)
        local_path_for_url(url).unlink(missing_ok=True)
    except Exception:
        log.warning("Could not discard uncommitted object %s; queuing cleanup", url, exc_info=True)
        try:
            with db.transaction() as tx:
                from .media_gc import queue_media_cleanup
                queue_media_cleanup(tx, url, delay_seconds=60)
        except Exception:
            log.exception("Failed to enqueue orphaned media for cleanup: %s", url)
