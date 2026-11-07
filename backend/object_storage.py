"""Private S3/R2/MinIO-backed media with a safe local read-through cache.

Existing /generated/ and /uploads/ links are retained: the backend continues
to authorize EACH request before it reads this object's private binary data.
No public ACLs or presigned links are created here.

Environment:
  HANDRAW_OBJECT_BUCKET       -- enables object storage when nonempty
  HANDRAW_OBJECT_ENDPOINT     -- optional S3-compatible endpoint (R2/MinIO)
  HANDRAW_OBJECT_REGION       -- default: auto
  HANDRAW_OBJECT_PREFIX       -- optional path prefix, default handraw/v3
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY -- boto3 standard env chain
"""
from __future__ import annotations

import mimetypes
import os
import tempfile
from functools import lru_cache
from pathlib import Path

MAX_OBJECT_BYTES = 32 * 1024 * 1024


def enabled() -> bool:
    return bool(os.environ.get("HANDRAW_OBJECT_BUCKET", "").strip())


def _key(url: str) -> str:
    clean = str(url or "").split("?", 1)[0].strip()
    if not clean.startswith(("/generated/", "/uploads/")):
        raise ValueError("Unsupported private media namespace")
    pieces = clean.lstrip("/").split("/")
    if (len(pieces) < 2 or any(p in ("", ".", "..") for p in pieces)
            or "\x00" in clean or "\\" in clean):
        raise ValueError("Unsafe private media key")
    prefix = os.environ.get("HANDRAW_OBJECT_PREFIX", "handraw/v3").strip("/")
    if prefix and any(seg in ("", ".", "..") for seg in prefix.split("/")):
        raise ValueError("Unsafe object storage prefix")
    return "/".join([*([prefix] if prefix else []), *pieces])


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config
    endpoint = os.environ.get("HANDRAW_OBJECT_ENDPOINT", "").strip() or None
    region = os.environ.get("HANDRAW_OBJECT_REGION", "").strip() or ("auto" if endpoint else "us-east-1")
    return boto3.client(
        "s3", endpoint_url=endpoint, region_name=region,
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=8,
            read_timeout=20,
        ),
    )


def put(url: str, payload: bytes, *, mime: str | None = None) -> None:
    """Save durably before a DB row may refer to this media."""
    if not enabled():
        return
    if not payload or len(payload) > MAX_OBJECT_BYTES:
        raise ValueError("Invalid object payload size")
    key = _key(url)
    options = {
        "Bucket": os.environ["HANDRAW_OBJECT_BUCKET"].strip(),
        "Key": key,
        "Body": payload,
        "ContentType": mime or mimetypes.guess_type(url)[0] or "application/octet-stream",
        "CacheControl": "private, no-store",
    }
    sse = os.environ.get("HANDRAW_OBJECT_SSE", "").strip()
    if sse:
        options["ServerSideEncryption"] = sse
    _client().put_object(**options)


def ensure_local_copy(url: str, target: Path) -> bool:
    """Restore a missing local file from the authoritative private bucket.

    Call ONLY AFTER the HTTP caller has passed _private_media_access (or
    another equivalent owner/authorized-grant check). Do not allow this
    function to become a public image endpoint itself.
    """
    if target.is_file():
        return True
    if not enabled():
        return False
    key = _key(url)
    try:
        obj = _client().get_object(
            Bucket=os.environ["HANDRAW_OBJECT_BUCKET"].strip(), Key=key,
        )
        payload = obj["Body"].read(MAX_OBJECT_BYTES + 1)
        if not payload or len(payload) > MAX_OBJECT_BYTES:
            raise ValueError("Object is empty or exceeds size limit")
    except Exception as error:
        # A missing object should return 404 from the caller; other failures
        # must not silently manufacture a successful, empty media response.
        error_code = str(
            (getattr(error, "response", {}) or {}).get("Error", {}).get("Code", "")
        )
        if error_code in ("NoSuchKey", "404", "NotFound"):
            return False
        raise
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".handraw-object-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, target)
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return True
