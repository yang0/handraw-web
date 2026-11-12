"""Private durable import inputs and database claims; no in-memory task authority."""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid

from .config import get_storage_root
from .document_structure import DocumentImportError


def _input_path(key):
    if not re.fullmatch(r"imp_[a-f0-9]{32}\.input", str(key)):
        raise DocumentImportError("导入输入文件标识无效")
    return get_storage_root() / "import_inputs" / key


def persist_input(job_id, content):
    if not isinstance(content, bytes) or not content or len(content) > 10 * 1024 * 1024:
        raise DocumentImportError("导入文件为空或超过 10MB")
    key = job_id + ".input"
    destination = _input_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp_" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return key, hashlib.sha256(content).hexdigest()


def discard_input(key):
    if key:
        _input_path(key).unlink(missing_ok=True)


def read_input(job):
    try:
        content = _input_path(job["input_storage_key"]).read_bytes()
    except OSError as exc:
        raise DocumentImportError("导入原文件不可用，请重新导入") from exc
    if (
        len(content) > 10 * 1024 * 1024
        or hashlib.sha256(content).hexdigest() != job["input_sha256"]
    ):
        raise DocumentImportError("导入原文件校验失败，请重新导入")
    return content


def claim_input(db, duration):
    with db.transaction() as tx:
        row = tx.execute(
            """SELECT * FROM studio_import_jobs
               WHERE input_storage_key<>'' AND claim_count<3 AND
                 (status='queued' OR (status='running' AND lease_until<=now()))
               ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""",
        ).fetchone()
        if not row:
            return None
        token = uuid.uuid4().hex
        tx.execute(
            """UPDATE studio_import_jobs SET status='running',lease_token=?,
                      lease_until=now()+(? * interval '1 second'),claim_count=claim_count+1,
                      progress_done=0,error='',updated_at=to_char(now() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"')
               WHERE id=?""",
            (token, max(0.1, duration), row["id"]),
        )
        row["lease_token"] = token
        return row


def finish_input(db, job_id):
    """Detach only terminal inputs before unlinking; recovery keeps its file."""
    with db.transaction() as tx:
        row = tx.execute(
            "SELECT input_storage_key FROM studio_import_jobs WHERE id=? AND status IN ('done','failed') FOR UPDATE",
            (job_id,),
        ).fetchone()
        if not row or not row["input_storage_key"]:
            return
        tx.execute(
            "UPDATE studio_import_jobs SET input_storage_key='',input_sha256='',lease_token=NULL,lease_until=NULL WHERE id=?",
            (job_id,),
        )
        key = row["input_storage_key"]
    discard_input(key)


def cleanup_abandoned_inputs(db, *, age_seconds=86400, limit=200):
    """Reap files left before admission/after detach, preserving referenced input."""
    terminal = (
        db.get_conn()
        .execute(
            "SELECT id FROM studio_import_jobs WHERE status IN ('done','failed') AND input_storage_key<>'' LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    for job in terminal:
        finish_input(db, job["id"])
    root = get_storage_root() / "import_inputs"
    if not root.is_dir():
        return 0
    candidates = []
    for path in root.iterdir():
        if len(candidates) >= limit:
            break
        if not re.fullmatch(r"imp_[a-f0-9]{32}\.(?:input|tmp_[a-f0-9]{32})", path.name):
            continue
        try:
            if path.is_file() and path.stat().st_mtime < time.time() - age_seconds:
                candidates.append(path)
        except FileNotFoundError:
            pass
    referenced = (
        {
            r["input_storage_key"]
            for r in db.get_conn()
            .execute(
                "SELECT input_storage_key FROM studio_import_jobs WHERE input_storage_key=ANY(?)",
                ([p.name for p in candidates],),
            )
            .fetchall()
        }
        if candidates
        else set()
    )
    removed = 0
    db.release_request_connection()
    for path in candidates:
        if path.name not in referenced:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
