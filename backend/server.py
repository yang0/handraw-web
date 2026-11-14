"""Multi-subdomain HTTP application server for Handraw Web 2.0 (Main, Studio, Forum, Admin + Skill-Addon)."""
from __future__ import annotations

import argparse
import base64
import binascii
import errno
import hashlib
import html
import io
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import logging

logger = logging.getLogger("backend.server")
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .admin_services import (
    admin_adjust_user_credits,
    admin_assign_forum_moderator,
    admin_create_redeem_code,
    admin_create_user,
    admin_create_official_asset,
    admin_update_official_asset,
    admin_delete_official_asset,
    admin_delete_catalog_asset,
    admin_delete_user,
    admin_get_dashboard,
    admin_get_gateway_overview,
    admin_get_moderator_console,
    admin_get_permissions,
    admin_get_settings,
    admin_get_user_detail,
    admin_list_audit_logs,
    admin_list_catalog_assets,
    admin_list_comments,
    admin_list_forum_moderators,
    admin_list_generations,
    admin_list_presets,
    admin_list_redeem_codes,
    admin_list_reports,
    admin_list_topics,
    admin_list_unlocks,
    admin_list_users,
    admin_list_works,
    admin_moderate_comment,
    admin_moderate_topic,
    admin_moderate_work,
    admin_refund_unlock,
    admin_reset_user_free_quota,
    admin_resolve_report,
    admin_revoke_forum_moderator,
    admin_toggle_redeem_code,
    admin_update_gateway_config,
    admin_update_settings,
    admin_update_user,
    admin_upsert_catalog_asset,
    admin_upsert_preset,
    require_staff,
)
from .config import (
    CONTENT_DIR,
    DEFAULT_STYLE_IMAGES_DIR,
    DEFAULT_STYLE_REFS_DIR,
    DEMO_DIR,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    get_generated_dir,
    get_image_config_path,
    get_uploads_dir,
    load_image_config,
    open_url,
    resolve_gateway_model,
)
from .db import Database, utc_now_iso
from .observability import (
    extract_http_error_summary,
    local_debug_stacks_enabled,
    sanitize_log_text,
)
from .security import build_session_cookie
from .runtime_policy import (
    MAX_JSON_BODY_BYTES,
    MAX_IMAGE_BYTES,
    bind_host,
    check_auth_rate_limit,
    check_write_origin,
    decode_data_image_url,
    demo_mode_enabled,
    env_flag,
    include_private_benchmark_assets,
    origin_allowed,
    recharge_enabled,
    sanitize_media_url,
    sanitize_submission_body,
    trusted_origins,
    validate_image_bytes,
)
from .seed import ensure_seeded, is_seed_username, seed_ids
from .services import (
    ServiceError,
    accept_forum_bounty_reply,
    add_comment_to_asset,
    add_comment_to_work,
    authenticate_request,
    build_boot_payload,
    build_skill_asset_content,
    build_skill_library_payload,
    check_text_has_secret,
    complete_cloud_generation,
    claim_cloud_generation_submission,
    compute_public_asset_counts_and_creators,
    consume_daily_usage,
    delete_user_studio_workflow,
    forum_moderator_action,
    get_secrets_cache,
    get_site_settings,
    get_public_generation_history,
    get_user_public_generations,
    get_user_public_generation_by_id,
    get_user_collected_generations,
    fork_generation_recipe,
    get_studio_workspace,
    get_user_studio_task,
    get_wallet_quota_state,
    grant_studio_media_public,
    import_discourse_users_batch,
    login_user,
    logout_session,
    perform_daily_checkin,
    prepare_cloud_generation,
    publish_forum_reply_post,
    publish_forum_topic_post,
    publish_user_community_asset,
    publish_user_work,
    validate_topic_title,
    record_cloud_generation_task_id,
    record_user_studio_history,
    redeem_code_for_user,
    refund_failed_cloud_generation,
    register_user,
    sandbox_switch_account,
    save_user_studio_workflow,
    send_encourage_tip,
    submit_abuse_report,
    delete_user_studio_article,
    list_user_studio_articles,
    sync_user_studio_articles,
    toggle_user_cheer,
    toggle_user_collection,
    toggle_user_like,
    topup_credits_for_user,
    unlock_paid_item,
    update_my_profile,
)

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

_STATIC_JSON_CACHE: dict[str, bytes] = {}
_LEGACY_DEMO_STATE_LOCK = threading.Lock()
_LEGACY_DEMO_STATE: dict[str, Any] = {}

RATIOS_MAP = {
    "1:1": "1024x1024",
    "3:4": "1152x1536",
    "4:3": "1536x1152",
    "9:16": "864x1536",
    "16:9": "1536x864",
}


def size_for_ratio(ratio: str) -> str:
    if not ratio:
        return "1152x1536"
    if ratio in RATIOS_MAP:
        return RATIOS_MAP[ratio]
    try:
        w_s, h_s = ratio.split(":")
        val = float(w_s) / float(h_s)
        if 0.25 <= val <= 4.0:
            w, h = (1536.0, 1536.0 / val) if val >= 1.0 else (1536.0 * val, 1536.0)
            return f"{round(w / 16) * 16}x{round(h / 16) * 16}"
    except Exception:
        pass
    return "1152x1536"


def load_image_service_config() -> dict[str, Any]:
    return load_image_config()


class GatewayNotConfigured(RuntimeError):
    """Raised when the local image gateway configuration is missing."""


def gateway_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    cfg = load_image_service_config()
    if not cfg:
        raise GatewayNotConfigured("未检测到本地生图网关配置 image-service.json")
    url = f"{cfg['base_url']}{path}"
    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "User-Agent": "HandrawWeb2/2.0",
    }
    data_bytes = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST" if payload is not None else "GET")
    with open_url(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


_MIME_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _build_multipart_form_data(
    fields: list[tuple[str, str]],
    files: list[tuple[str, str, str, bytes]],
) -> tuple[str, bytes]:
    boundary = f"----HandrawFormBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, val in fields:
        safe_name = str(name).replace('"', "").replace("\r", "").replace("\n", "")
        chunks.append(
            (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{safe_name}"\r\n\r\n'
                f'{val}\r\n'
            ).encode("utf-8")
        )
    for field_name, filename, content_type, data in files:
        safe_field = str(field_name).replace('"', "").replace("\r", "").replace("\n", "")
        safe_file = str(filename).replace('"', "").replace("\r", "").replace("\n", "")
        chunks.append(
            (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{safe_field}"; filename="{safe_file}"\r\n'
                f'Content-Type: {content_type}\r\n\r\n'
            ).encode("utf-8")
            + data
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def openai_image_gateway_request(
    cfg: dict[str, Any],
    prompt: str,
    *,
    model: str,
    size: str,
    quality: str = "auto",
    refs: list[dict[str, str]] | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    """Call an OpenAI-compatible /v1/images/generations or /v1/images/edits endpoint."""
    if not cfg or not cfg.get("key"):
        raise GatewayNotConfigured("未检测到本地生图网关配置 image-service.json")
    raw_api_base = str(cfg.get("api_base_url") or "").strip().rstrip("/")
    if not raw_api_base:
        base = str(cfg.get("base_url") or "").strip().rstrip("/")
        raw_api_base = base if base.endswith("/v1") else f"{base}/v1"
    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "User-Agent": "HandrawWeb2/2.0",
    }
    files: list[tuple[str, str, str, bytes]] = []
    for idx, ref in enumerate(refs or []):
        if not isinstance(ref, dict) or not ref.get("b64_json"):
            continue
        raw_bytes = base64.b64decode(str(ref["b64_json"]))
        mime = str(ref.get("mime_type") or "image/png").split(";")[0].strip().lower()
        ext = _MIME_EXT_MAP.get(mime, ".png")
        files.append(("image", f"ref_{idx}{ext}", mime, raw_bytes))
    if files:
        url = f"{raw_api_base}/images/edits"
        ctype, data_bytes = _build_multipart_form_data(
            [
                ("model", model),
                ("prompt", prompt),
                ("n", "1"),
                ("size", size),
                ("quality", quality),
            ],
            files,
        )
        headers["Content-Type"] = ctype
    else:
        url = f"{raw_api_base}/images/generations"
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": quality,
            },
            ensure_ascii=False,
        ).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    with open_url(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe_generated_stem(filename_stem: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(filename_stem or "generated"))[:120] or "generated"


def cache_generated_image_bytes(raw_bytes: bytes, mime: str, filename_stem: str) -> str:
    """Validate and persist one gateway image under the private generated root."""
    payload, ext = validate_image_bytes(raw_bytes, mime)
    gen_dir = get_generated_dir()
    gen_dir.mkdir(parents=True, exist_ok=True)
    # Content-addressed names protect immutable media identities on retries.
    out_name = f"{_safe_generated_stem(filename_stem)}-{hashlib.sha256(payload).hexdigest()[:16]}{ext}"
    public_url = f"/generated/{out_name}"
    from .media_storage import persist_media_bytes
    persist_media_bytes(public_url, payload, mime=mime)
    return public_url


def _same_remote_origin(left: str, right: str) -> bool:
    a = urlparse(left)
    b = urlparse(right)
    a_port = a.port or (443 if a.scheme == "https" else 80)
    b_port = b.port or (443 if b.scheme == "https" else 80)
    return a.scheme.lower() == b.scheme.lower() and (a.hostname or "").lower() == (b.hostname or "").lower() and a_port == b_port


def _remote_image_url_allowed(remote_url: str, gateway_base: str) -> bool:
    parsed = urlparse(str(remote_url or ""))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    gateway_host = (urlparse(gateway_base).hostname or "").lower()
    allow_private_gateway = env_flag("HANDRAW_IMAGE_GATEWAY_ALLOW_PRIVATE", False) and parsed.hostname.lower() == gateway_host
    try:
        resolved = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {item[4][0] for item in resolved if item and item[4]}
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified) and not allow_private_gateway:
            return False
    return True


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str):  # type: ignore[override]
        return None


def download_and_cache_generated_image(remote_url: str, filename_stem: str) -> str:
    cfg = load_image_service_config()
    gateway_base = str(cfg.get("base_url") or "")
    current_url = str(remote_url or "")
    for _ in range(4):
        if not _remote_image_url_allowed(current_url, gateway_base):
            raise RuntimeError("网关返回了不安全的图片地址")
        headers = {"User-Agent": "HandrawWeb2/2.0"}
        # Bearer credentials stay on the configured gateway origin only. A
        # signed/public result host receives no Authorization header.
        if cfg.get("key") and _same_remote_origin(current_url, gateway_base):
            headers["Authorization"] = f"Bearer {cfg['key']}"
        req = urllib.request.Request(current_url, headers=headers)
        try:
            resp = open_url(req, timeout=45, extra_handlers=(_NoRedirectHandler(),))
        except urllib.error.HTTPError as he:
            if he.code in (301, 302, 303, 307, 308) and he.headers.get("Location"):
                current_url = urllib.parse.urljoin(current_url, he.headers["Location"])
                continue
            raise
        with resp:
            ctype = (resp.headers.get("Content-Type") or "image/png").split(";")[0].strip()
            raw_bytes = resp.read(MAX_IMAGE_BYTES + 1)
            try:
                return cache_generated_image_bytes(raw_bytes, ctype, filename_stem)
            except ValueError as exc:
                raise RuntimeError(f"网关返回了不受支持的图片：{exc}") from exc
    raise RuntimeError("网关图片重定向次数过多")


def _cache_gateway_item_image(item: Any, filename_stem: str) -> str | None:
    if not isinstance(item, dict):
        return None
    remote_url = str(item.get("url") or "").strip()
    if remote_url:
        return download_and_cache_generated_image(remote_url, filename_stem)
    b64_json = str(item.get("b64_json") or item.get("b64Json") or "").strip()
    if not b64_json:
        return None
    try:
        raw = base64.b64decode(b64_json, validate=True)
        mime = str(item.get("mime_type") or item.get("mimeType") or "image/png")
        return cache_generated_image_bytes(raw, mime, filename_stem)
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError(f"网关返回了不受支持的 Base64 图片：{exc}") from exc


def _row_gateway_protocol(raw_system_append: Any) -> str:
    if not raw_system_append:
        return "image-tasks"
    try:
        data = json.loads(raw_system_append) if isinstance(raw_system_append, str) else raw_system_append
        if isinstance(data, dict) and str(data.get("gatewayProtocol") or "").lower() == "openai":
            return "openai"
    except Exception:
        pass
    return "image-tasks"


def _get_generation_gateway_protocol(db: Database, gen_id: str) -> str:
    if not gen_id:
        return "image-tasks"
    row = db.get_conn().execute(
        "SELECT system_append_json FROM studio_generations WHERE id = ?",
        (gen_id,),
    ).fetchone()
    return _row_gateway_protocol(row["system_append_json"] if row else None)


def _mark_generation_gateway_protocol(db: Database, gen_id: str, protocol: str) -> None:
    """Persist non-sensitive protocol metadata so reconciler/tasks match the submitter."""
    if not gen_id or protocol != "openai":
        return
    with db.transaction() as tx:
        row = tx.execute(
            "SELECT system_append_json FROM studio_generations WHERE id = ?",
            (gen_id,),
        ).fetchone()
        data: dict[str, Any] = {}
        if row and row["system_append_json"]:
            try:
                parsed = json.loads(row["system_append_json"])
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                data = {}
        if data.get("gatewayProtocol") == protocol:
            return
        data["gatewayProtocol"] = protocol
        tx.execute(
            "UPDATE studio_generations SET system_append_json = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), gen_id),
        )


RECONCILE_UNRECEIVED_TASK_TIMEOUT_MINUTES = 30
RECONCILE_OPENAI_ORPHAN_TIMEOUT_MINUTES = 5


def _parse_created_at_dt(created_at_str: str | None) -> datetime | None:
    """Parse created_at timestamp string into a timezone-aware UTC datetime."""
    if not created_at_str:
        return None
    raw = str(created_at_str).strip()
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _sanitize_gateway_error_detail(
    raw_body: bytes | str | None,
    *,
    db: Database | None = None,
    prompt: str = "",
    api_key: str = "",
) -> tuple[str, bool]:
    """Return ``(safe_detail, secret_matched)`` safe for logs and bounded UI errors."""
    detail = extract_http_error_summary(raw_body, max_len=280)
    if not detail:
        return "", False

    secret_matched = False
    clean_key = str(api_key or "").strip()
    if len(clean_key) >= 4 and clean_key in detail:
        detail = detail.replace(clean_key, "[redacted]")

    clean_prompt = str(prompt or "").strip()
    if len(clean_prompt) >= 24:
        for idx in range(0, min(len(clean_prompt) - 23, 2000), 8):
            chunk = clean_prompt[idx : idx + 24]
            if chunk in detail:
                secret_matched = True
                return "[redacted prompt excerpt]", True

    if db is not None:
        try:
            conn = db.get_conn()
            _, secrets, _ = get_secrets_cache(conn)
            if check_text_has_secret(detail, conn):
                secret_matched = True
                masked = detail
                for sec in sorted(secrets, key=len, reverse=True):
                    if sec and sec in masked:
                        masked = masked.replace(sec, "[redacted]")
                if check_text_has_secret(masked, conn):
                    masked = "[redacted protected detail]"
                detail = masked
        except Exception:
            logger.warning("Failed to scan upstream error detail for protected secrets", exc_info=True)
            return "[redacted unverified upstream detail]", True

    return sanitize_log_text(detail, max_len=280), secret_matched


def _gateway_failure_is_definite(exc: BaseException) -> bool:
    """Return True if gateway definitely did not create the task or explicitly rejected it."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 408:
            return False
        return 400 <= exc.code < 500
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return False
        if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
            return True
        if isinstance(reason, OSError):
            if getattr(reason, "errno", None) in (errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", 10061)):
                return True
            if getattr(reason, "winerror", None) == 10061:
                return True
        return False
    if isinstance(exc, (ConnectionRefusedError, socket.gaierror)):
        return True
    if isinstance(exc, GatewayNotConfigured):
        return True
    return False


class GenerationReconciler:
    """Durably reconcile live jobs without depending on an open browser.

    A gateway timeout is deliberately left in ``queued``/``running``.  The
    worker never submits a second request and never refunds an unknown task;
    only an authoritative gateway failure/cancellation releases the original
    reservation.  This prevents a retry from becoming a free duplicate job.
    """

    def __init__(self, db: Database, interval_seconds: int | None = None) -> None:
        self.db = db
        try:
            configured = int(interval_seconds or os.environ.get("HANDRAW_RECONCILE_INTERVAL", "15"))
        except ValueError:
            configured = 15
        self.interval_seconds = max(5, min(120, configured))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def reconcile_once(self, lease=None) -> int:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE studio_generations SET prompt_ready = 1 WHERE prompt_ready = 0 AND created_at < ?",
                (cutoff_iso,),
            )
        try:
            from .services import run_blackbox_backfill
            run_blackbox_backfill(self.db)
        except Exception:
            logger.warning("worker=generation-reconciler phase=blackbox-backfill failed", exc_info=True)
        handled = 0
        from .generation_polling import polling_claims
        with polling_claims(self.db, interval_seconds=self.interval_seconds) as rows:
            for row in rows:
                if lease is not None and not lease.valid():
                    logger.warning("Reconciliation interrupted: Redis leadership lost")
                    break
                generation_id = str(row["id"])
                if _row_gateway_protocol(row["system_append_json"]) == "openai":
                    created_dt = _parse_created_at_dt(row["created_at"])
                    if created_dt and created_dt < (datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_OPENAI_ORPHAN_TIMEOUT_MINUTES)):
                        refund_failed_cloud_generation(
                            self.db,
                            generation_id,
                            "同步生图任务超时未完成，已退还",
                            poll_claim_token=row["poll_claim_token"],
                        )
                        handled += 1
                    continue
                task_id = str(row["task_id"] or "").strip()
                # If the submit process died before receiving an upstream id, use
                # the stable request id only to look for an already-created task.
                # Never submit a replacement request from this worker.
                lookup_id = task_id or str(row["request_id"] or "").strip()
                if not lookup_id:
                    continue
                cached_urls_for_task: list[str] = []
                try:
                    result = gateway_request(f"/api/image-tasks?ids={urllib.parse.quote(lookup_id)}", timeout=12)
                    items = result.get("items") or []
                    if not items:
                        created_dt = _parse_created_at_dt(row["created_at"])
                        if created_dt and created_dt < (datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_UNRECEIVED_TASK_TIMEOUT_MINUTES)):
                            refund_failed_cloud_generation(
                                self.db,
                                generation_id,
                                "网关未收到任务，已退还",
                                poll_claim_token=row["poll_claim_token"],
                            )
                            handled += 1
                        continue
                    item = items[0] if isinstance(items[0], dict) else {}
                    actual_id = str(item.get("id") or lookup_id)
                    if not task_id and actual_id:
                        complete_cloud_generation(self.db, generation_id, actual_id, poll_claim_token=row["poll_claim_token"])
                        task_id = actual_id
                    status = str(item.get("status") or "running").lower()
                    if status in ("success", "succeeded", "completed", "done"):
                        data = item.get("data") or []
                        local_urls: list[str] = []
                        for idx, image_item in enumerate(data):
                            local_url = _cache_gateway_item_image(image_item, f"{actual_id}_{idx}")
                            if local_url:
                                local_urls.append(local_url)
                                cached_urls_for_task.append(local_url)
                        # A download/validation exception keeps the row pending so
                        # the next pass can retry; do not mark success with a
                        # missing private artifact.
                        complete_cloud_generation(self.db, generation_id, actual_id, local_urls, poll_claim_token=row["poll_claim_token"])
                        handled += 1
                    elif status in ("failed", "error", "cancelled", "canceled"):
                        refund_failed_cloud_generation(
                            self.db,
                            generation_id,
                            f"云端任务失败 ({status})",
                            poll_claim_token=row["poll_claim_token"],
                        )
                        handled += 1
                except Exception:
                    # This attempt may already have downloaded private files even
                    # when its DB completion failed. Do not delete synchronously:
                    # an earlier callback may have referenced the same content.
                    if cached_urls_for_task:
                        try:
                            from .media_gc import queue_media_cleanup
                            with self.db.transaction() as tx:
                                for url in set(cached_urls_for_task):
                                    if url.startswith(("/generated/", "/uploads/")):
                                        queue_media_cleanup(tx, url, delay_seconds=86400)
                        except Exception:
                            logger.exception("worker=media-gc could not queue gateway orphan")
                    # Network errors, 404s and malformed gateway responses are
                    # unknown state. Keep the original charge and retry later.
                    row["_poll_failed"] = True
                    logger.warning("worker=generation-reconciler generation_id=%s polling failed; will retry", generation_id, exc_info=True)
                    continue
        return handled

    def reconcile_economy_once(self) -> None:
        from .points import settle_due
        from .economy import release_abandoned_quotes
        tx=self.db.get_conn()
        owners=tx.execute("SELECT author_id AS uid FROM creator_point_earnings WHERE status='pending' AND available_at<=now() UNION SELECT c.user_id AS uid FROM generation_charges c JOIN generation_quotes q ON q.id=c.quote_id WHERE c.status='reserved' AND c.item_id IS NULL AND c.generation_id IS NULL AND q.expires_at<now() LIMIT 100").fetchall()
        for owner in owners:
            settle_due(self.db,owner["uid"])
            release_abandoned_quotes(self.db,owner["uid"])

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.reconcile_economy_once()
            except Exception:
                logger.exception("worker=economy-maintenance iteration failed; will retry")
            try:
                from .redis_jobs import generation_reconcile_lease
                with generation_reconcile_lease() as lease:
                    if lease.valid():
                        self.reconcile_once(lease=lease)
                    if lease.valid():
                        # Media deletion uses the same cross-process lease and
                        # an independent durable claim; Redis holds no truth.
                        from .media_gc import drain_media_gc
                        drained = drain_media_gc(self.db, limit=5)
                        if drained["deleted"] or drained["failed"]:
                            logger.info("worker=media-gc result=%s", drained)
            except Exception:
                logger.exception("worker=generation-reconciler iteration failed; will retry")
            self._stop.wait(self.interval_seconds)

    def start(self) -> "GenerationReconciler":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="handraw-generation-reconciler", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.1, timeout))


def save_data_url_upload(
    db: Database,
    user: dict[str, Any] | None,
    data_url: str,
    name_zh: str = "上传图片",
    desc_zh: str = "",
    cat: str = "other",
) -> dict[str, Any]:
    try:
        raw_bytes, ext, _ = decode_data_image_url(data_url)
    except ValueError as exc:
        raise ServiceError(str(exc), status=400, code="invalid_image_upload") from exc

    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()

    raw_cat = str(cat or "other").strip().lower()
    PUBLIC_CATS = ("characters", "props", "scenes", "other")
    INTERNAL_CATS = ("forum", "share", "skill_history")          # 仅由论坛/投稿发布写入，原样保留
    if raw_cat in PUBLIC_CATS or raw_cat in INTERNAL_CATS:
        safe_cat = raw_cat
    else:
        safe_cat = "other"              # 未知值、以及 'import' 一律降级

    if user:
        user_id = int(user["id"])
        # Fresh V3 users have complete asset metadata on first write.
        from .user_library import check_user_upload_quota, next_change_seq

        new_file_path: Path | None = None
        new_media_url: str | None = None
        try:
            with db.transaction() as tx:
                # Check deduplication against existing active assets (library categories only)
                if safe_cat in PUBLIC_CATS:
                    existing_dup = tx.execute(
                        """
                        SELECT * FROM user_uploads
                        WHERE user_id = ? AND sha256 = ? AND deleted_at IS NULL AND (cat IS NULL OR cat IN ('characters', 'props', 'scenes', 'other'))
                        LIMIT 1
                        """,
                        (user_id, sha256_hex),
                    ).fetchone()
                    if existing_dup is not None:
                        return {
                            "id": existing_dup["id"],
                            "url": existing_dup["image_url"],
                            "cat": existing_dup["cat"],
                            "nameZh": existing_dup["name_zh"],
                            "descZh": existing_dup["desc_zh"],
                            "image": existing_dup["image_url"],
                            "isCustom": True,
                            "deduped": True,
                            "assetUid": existing_dup["asset_uid"],
                        }

                    # Enforce unified quota (500 assets, 1 GB storage) for library assets
                    check_user_upload_quota(tx, user_id, len(raw_bytes), is_new_item=True)

                uploads_dir = get_uploads_dir()
                uploads_dir.mkdir(parents=True, exist_ok=True)
                up_id = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
                fname = f"{up_id}{ext}"
                fpath = uploads_dir / fname
                public_url = f"/uploads/{fname}"
                new_media_url = public_url
                from .media_storage import persist_media_bytes
                persist_media_bytes(public_url, raw_bytes)
                new_file_path = fpath

                asset_uid = str(uuid.uuid4())
                now_iso = utc_now_iso()
                seq = next_change_seq(tx)
                tx.execute(
                    """
                    INSERT INTO user_uploads (
                        id, user_id, cat, name_zh, desc_zh, image_url, file_path, bytes, created_at,
                        asset_uid, local_id, name_en, tags_json, sha256, revision, change_seq, updated_at, origin
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        up_id,
                        user_id,
                        safe_cat,
                        (name_zh or "上传素材").strip()[:60],
                        (desc_zh or "").strip()[:200],
                        public_url,
                        str(fpath),
                        len(raw_bytes),
                        now_iso,
                        asset_uid,
                        None,
                        "",
                        "[]",
                        sha256_hex,
                        1,
                        seq,
                        now_iso,
                        "web",
                    ),
                )
                return {
                    "id": up_id,
                    "url": public_url,
                    "cat": safe_cat,
                    "nameZh": name_zh or "上传素材",
                    "descZh": desc_zh or "",
                    "image": public_url,
                    "isCustom": True,
                    "deduped": False,
                    "assetUid": asset_uid,
                }
        except Exception:
            if new_media_url:
                from .media_storage import discard_uncommitted_media
                discard_uncommitted_media(db, new_media_url)
            elif new_file_path is not None:
                new_file_path.unlink(missing_ok=True)
            raise

    uploads_dir = get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    up_id = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    fname = f"{up_id}{ext}"
    fpath = uploads_dir / fname
    public_url = f"/uploads/{fname}"
    from .media_storage import persist_media_bytes
    persist_media_bytes(public_url, raw_bytes)
    return {
        "id": up_id,
        "url": public_url,
        "cat": safe_cat,
        "nameZh": name_zh or "上传素材",
        "descZh": desc_zh or "",
        "image": public_url,
        "isCustom": True,
        "deduped": False,
    }


def _path_is_within(path: Path, root: Path) -> bool:
    """Path containment check that does not mistake /root2 for /root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ======================== RESPONSIVE IMAGE THUMBNAILS ========================
# Gallery pages request many images at once.  Serving the full-size original
# for every card wastes bandwidth on files that are displayed at a few hundred
# pixels, so each distinct width is rendered once into a private cache and
# reused.  Anything we cannot decode is served as the original bytes.

# Compatibility exports; the cache implementation is shared with all media routes.
from .image_variants import (
    THUMB_WIDTHS, build_thumbnail, get_thumb_cache_dir,
    normalize_thumb_width, read_with_thumbnail,
)


def _iter_media_values(value: Any):
    if isinstance(value, str):
        yield value.strip()
    elif isinstance(value, dict):
        for key in ("url", "src", "image", "imageUrl"):
            raw = value.get(key)
            if isinstance(raw, str):
                yield raw.strip()
    elif isinstance(value, list):
        for item in value:
            yield from _iter_media_values(item)


def _media_owner(db: Database, media_url: str) -> int | None:
    """Resolve the owner of a private upload/generated URL from DB records."""
    url = sanitize_media_url(media_url)
    if not url:
        return None
    conn = db.get_conn()
    if url.startswith("/uploads/"):
        rel = url.removeprefix("/uploads/").split("?", 1)[0]
        row = conn.execute(
            "SELECT user_id FROM user_uploads WHERE image_url = ? OR file_path = ? OR file_path LIKE ? LIMIT 1",
            (url, url, f"%\\{rel}"),
        ).fetchone()
        if not row:
            for candidate in conn.execute("SELECT user_id, file_path FROM user_uploads"):
                if Path(str(candidate["file_path"] or "")).name == Path(rel).name:
                    row = candidate
                    break
        return int(row["user_id"]) if row else None
    if url.startswith("/generated/"):
        target = url.split("?", 1)[0]
        try:
            media_row = conn.execute(
                "SELECT user_id FROM studio_generation_media WHERE media_url = ? ORDER BY created_at DESC LIMIT 1",
                (target,),
            ).fetchone()
        except Exception:
            media_row = None
        if media_row:
            return int(media_row["user_id"])
        for row in conn.execute("SELECT user_id, items_json FROM studio_generations WHERE user_id IS NOT NULL"):
            try:
                items = json.loads(row["items_json"] or "[]")
            except Exception:
                continue
            if any(item.split("?", 1)[0] == target for item in _iter_media_values(items)):
                return int(row["user_id"])
    return None


def _is_published_media(db: Database, media_url: str) -> bool:
    """A media URL becomes public only through an explicit grant."""
    target = sanitize_media_url(media_url).split("?", 1)[0]
    if not target.startswith(("/uploads/", "/generated/")):
        return False
    conn = db.get_conn()
    from .forum_boards import access_sql
    try:
        row = conn.execute(
            f"""
            SELECT 1 FROM media_public_grants g
            WHERE g.media_url=? AND g.revoked_at IS NULL
              AND (
                (g.target_type='work' AND EXISTS (
                    SELECT 1 FROM works w
                    WHERE w.id=g.target_id AND w.status='published'
                      AND (w.run_id IS NULL OR EXISTS (
                        SELECT 1 FROM work_media wm
                        JOIN media_assets m ON m.id=wm.media_id
                        WHERE wm.work_id=w.id AND m.storage_key=g.media_url
                      ))
                ))
                OR (g.target_type='topic' AND EXISTS (
                    SELECT 1 FROM forum_topics t
                    WHERE t.id=g.target_id AND t.status='published' AND {access_sql('t.category')}
                      AND (COALESCE(t.work_id,'')='' OR EXISTS (
                        SELECT 1 FROM works w
                        JOIN work_media wm ON wm.work_id=w.id
                        JOIN media_assets m ON m.id=wm.media_id
                        WHERE w.id=t.work_id AND w.status='published'
                          AND m.storage_key=g.media_url
                      ))
                ))
                OR (g.target_type='asset' AND EXISTS (
                    SELECT 1 FROM catalog_assets a
                    WHERE a.code=g.target_id AND a.status='published'
                ))
              )
            LIMIT 1
            """,
            (target,),
        ).fetchone()
    except Exception:
        row = None
    if row:
        return True
    # V3 has no legacy data. Never infer public access from JSON references.
    return False


def validate_publish_media(db: Database, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    """Validate media references before a user makes them public.

    Inline data URLs are persisted as owned uploads.  Existing private media
    may be published only by its owner; arbitrary file paths are dropped.
    This hook is intentionally reusable by feature handlers that edit works or
    forum posts.
    """
    out = dict(body)
    if not user:
        raise ServiceError("请先登录账号后再发布媒体", status=401, code="login_required")
    uid = int(user["id"])
    for key in ("image", "imageUrl", "cover"):
        raw = out.get(key)
        if isinstance(raw, str) and raw.startswith("data:image/"):
            saved = save_data_url_upload(db, user, raw, name_zh=str(out.get("title") or "作品配图"))
            out[key] = saved["url"]
        elif isinstance(raw, str) and raw.strip():
            safe = sanitize_media_url(raw)
            if not safe or (safe.startswith(("/uploads/", "/generated/")) and _media_owner(db, safe) != uid):
                out.pop(key, None)
            else:
                out[key] = safe
    images = out.get("images")
    if isinstance(images, list):
        clean: list[Any] = []
        for idx, item in enumerate(images[:12]):
            if isinstance(item, str):
                raw_url = item.strip()
                if raw_url.startswith("data:image/"):
                    saved = save_data_url_upload(db, user, raw_url, name_zh=f"配图-{idx + 1}")
                    clean.append(saved["url"])
                    continue
                safe = sanitize_media_url(raw_url)
                if not safe:
                    continue
                if safe.startswith(("/uploads/", "/generated/")) and _media_owner(db, safe) != uid:
                    # Never drop silently: the caller would believe an image was
                    # published when it was not (the Skill contract forbids this).
                    raise ServiceError("不能使用他人的图片作为作品配图", status=403, code="foreign_media")
                clean.append(safe)
            elif isinstance(item, dict):
                raw_url = str(item.get("url") or item.get("src") or item.get("image") or "").strip()
                tag = str(item.get("tag") or item.get("caption") or "").strip()[:60]
                if raw_url.startswith("data:image/"):
                    saved = save_data_url_upload(db, user, raw_url, name_zh=tag or f"帖内配图-{idx + 1}")
                    raw_url = saved["url"]
                safe = sanitize_media_url(raw_url)
                if not safe:
                    continue
                if safe.startswith(("/uploads/", "/generated/")) and _media_owner(db, safe) != uid:
                    raise ServiceError("不能使用他人的图片作为作品配图", status=403, code="foreign_media")
                clean.append({"url": safe, "tag": tag or f"配图 P{idx + 1}"})
        out["images"] = clean
    return out


def _persist_inline_images_in_body(db: Database, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    out = sanitize_submission_body(body)
    # Keep a single validation implementation for all existing publish routes.
    if user:
        return validate_publish_media(db, user, out)
    return out


def _entry_to_work_body(entry: dict[str, Any]) -> dict[str, Any]:
    """Translate a Skill work payload into the work publish body.

    Accepts the shape ``community_share.work_payload`` actually produces::

        {"kind": "work", "title": ..., "cover_url": ...,
         "content": {"prompt": ..., "parameters": {"style_ids": [...], "layout_ids": [...]},
                     "examples": [{"theme": ..., "image": ...}]},
         "assets": [{"ref": "official:FA-013", "role": "style"}, ...]}

    Flat fields (``prompt``, ``styleIds``, ``layoutId``) are also accepted so a
    direct ``/api/works`` call works without an adapter.
    """
    def _codes(value: Any) -> list[str]:
        items = value if isinstance(value, list) else [value]
        return [str(v).strip() for v in items if v is not None and str(v).strip()]

    content = entry.get("content") if isinstance(entry.get("content"), dict) else {}
    params = content.get("parameters") if isinstance(content.get("parameters"), dict) else {}

    # Images: cover first, then examples; fall back to flat image lists.
    image_urls: list[str] = []
    cover = entry.get("cover_url") or entry.get("image") or ""
    if cover:
        image_urls.append(str(cover))
    for example in content.get("examples") or []:
        if isinstance(example, dict):
            url = example.get("image") or example.get("url") or ""
            if url:
                image_urls.append(str(url))
        elif isinstance(example, str):
            image_urls.append(example)
    for item in entry.get("images") or entry.get("uploads") or []:
        if isinstance(item, str):
            image_urls.append(item)
        elif isinstance(item, dict):
            url = item.get("url") or item.get("short_url") or ""
            if url:
                image_urls.append(str(url))
    deduped: list[str] = []
    for url in image_urls:
        if url and url not in deduped:
            deduped.append(url)

    # A caller sending more than twelve images is rejected even when they collapse
    # to fewer unique URLs, so the "split the share" instruction still surfaces.
    if len(image_urls) > 12:
        raise ServiceError("一次最多 12 张图片，请分批发布", status=400, code="too_many_images")

    # Assets carry "official:<CODE>" refs; split them by role.
    styles = _codes(entry.get("styleIds") or entry.get("styles") or [])
    layouts = _codes(entry.get("layoutId") or entry.get("layout") or [])
    if not styles and not layouts:
        styles = _codes(params.get("style_ids") or [])
        layouts = _codes(params.get("layout_ids") or [])
    for asset in entry.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        ref = str(asset.get("ref") or "").strip()
        code = ref.split(":", 1)[1] if ref.startswith("official:") else ref
        if not code:
            continue
        role = str(asset.get("role") or "style")
        if role == "layout" and code not in layouts:
            layouts.append(code)
        elif role == "style" and code not in styles:
            styles.append(code)

    # Stored verbatim: the Skill preserves the user's original request byte for
    # byte, and trimming would silently change what they said.
    prompt = str(content.get("prompt") or entry.get("prompt") or "")

    return {
        "title": str(entry.get("title") or "").strip(),
        "prompt": prompt,
        "notes": str(entry.get("originalRequest") or entry.get("notes") or entry.get("summary") or "").strip(),
        "images": deduped,
        "styles": styles,
        "layout": layouts[0] if layouts else "",
        "ratio": str(entry.get("ratio") or "3:4"),
        "requestId": str(entry.get("requestId") or entry.get("clientRequestId") or "").strip(),
        # ``forkOf`` is accepted for lineage only; it never increments a counter
        # (forks are counted when a real generation succeeds).
        "forkOf": str(entry.get("forkOf") or "").strip(),
        "origin": "skill",
    }


def load_localized_json(filename: str) -> bytes:
    if filename in _STATIC_JSON_CACHE:
        return _STATIC_JSON_CACHE[filename]
    src = CONTENT_DIR / filename
    raw = src.read_text(encoding="utf-8")
    raw = raw.replace("https://img.handraw-style.com/images/", "/images/")
    raw = raw.replace("https://static.handraw-style.com/", "/")
    if filename == "catalog.json":
        data_obj = json.loads(raw)
        for r in data_obj.get("resources", []):
            r.pop("definition", None)
        data = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    else:
        data = raw.encode("utf-8")
    _STATIC_JSON_CACHE[filename] = data
    return data


def _normalize_asset_img(raw_img: str) -> str:
    s = str(raw_img or "").strip()
    if s.startswith("../../../images/"):
        return "/images/" + s.removeprefix("../../../images/")
    if s.startswith("https://img.handraw-style.com/images/"):
        return "/images/" + s.removeprefix("https://img.handraw-style.com/images/")
    return s


def load_benchmark_assets_json(db: Database, user: dict[str, Any] | None = None) -> bytes:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for cat, fname in (("characters", "characters.json"), ("props", "props.json"), ("scenes", "scenes.json")):
        fpath = DEFAULT_STYLE_REFS_DIR / fname
        if fpath.is_file():
            try:
                arr = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(arr, list):
                    for it in arr:
                        aid = str(it.get("id") or "").strip()
                        if not aid or aid in seen:
                            continue
                        seen.add(aid)
                        items.append(
                            {
                                "id": aid,
                                "cat": cat,
                                "name": it.get("name") or aid,
                                "name_en": it.get("name_en") or "",
                                "image": _normalize_asset_img(it.get("image") or ""),
                                "tags": it.get("tags") or [],
                                "is_custom": False,
                            }
                        )
            except Exception:
                pass

    # The legacy manifest points at a developer-local custom library.  It is
    # never part of the public benchmark catalogue unless an operator has
    # explicitly opted in via HANDRAW_INCLUDE_PRIVATE_CUSTOM_ASSETS=1.
    custom_js = DEFAULT_STYLE_IMAGES_DIR / "custom" / "custom_assets.js"
    if include_private_benchmark_assets() and user and custom_js.is_file():
        try:
            txt = custom_js.read_text(encoding="utf-8")
            brace_idx = txt.find("{")
            end_idx = txt.rfind("}")
            if 0 <= brace_idx < end_idx:
                obj = json.loads(txt[brace_idx : end_idx + 1])
                for cat in ("characters", "props", "scenes"):
                    for it in obj.get(cat) or []:
                        aid = str(it.get("id") or "").strip()
                        if not aid or aid in seen:
                            continue
                        seen.add(aid)
                        items.append(
                            {
                                "id": aid,
                                "cat": cat,
                                "name": it.get("name") or aid,
                                "name_en": it.get("name_en") or "",
                                "image": _normalize_asset_img(it.get("image") or ""),
                                "tags": it.get("tags") or [],
                                "is_custom": True,
                            }
                        )
        except Exception:
            pass

    fallback_samples = [
        {
            "id": "PR-D01",
            "cat": "props",
            "name": "白瓷青花盖碗茶具",
            "name_en": "Porcelain Gaiwan Tea Set",
            "image": "/images/poster-demo-autumn-equinox.webp",
            "tags": ["官方示例道具", "节气茶席", "器物锚点"],
            "is_custom": False,
        },
        {
            "id": "PR-D02",
            "cat": "props",
            "name": "手写吐槽咖啡杯套",
            "name_en": "Handwritten Coffee Cup Sleeve",
            "image": "/images/layouts/ecommerce/EC-002.webp",
            "tags": ["官方示例道具", "文创包装", "商业提案"],
            "is_custom": False,
        },
        {
            "id": "SCN-D01",
            "cat": "scenes",
            "name": "暖阳欧式生活画室",
            "name_en": "Sunlit Cozy Art Studio",
            "image": "/images/individual/FB/FB-028.webp",
            "tags": ["官方示例场景", "室内画室", "固定背景"],
            "is_custom": False,
        },
        {
            "id": "SCN-D02",
            "cat": "scenes",
            "name": "静谧绘本森林长椅",
            "name_en": "Quiet Forest Park Bench",
            "image": "/images/individual/FB/FB-031.webp",
            "tags": ["官方示例场景", "森系自然", "大留白背景"],
            "is_custom": False,
        },
    ]
    for fb in fallback_samples:
        if fb["id"] not in seen:
            seen.add(fb["id"])
            items.append(fb)

    if user:
        for r in db.get_conn().execute(
            "SELECT * FROM user_uploads WHERE user_id = ? AND cat IN ('characters', 'props', 'scenes', 'other') AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 60",
            (int(user["id"]),),
        ).fetchall():
            if r["id"] not in seen:
                seen.add(r["id"])
                items.insert(
                    0,
                    {
                        "id": r["id"],
                        "cat": r["cat"],
                        "name": r["name_zh"],
                        "name_en": "",
                        "image": r["image_url"],
                        "tags": ["云端个人上传", r["desc_zh"] or "参考锚点"],
                        "is_custom": True,
                    },
                )

    return json.dumps({"assets": items}, ensure_ascii=False).encode("utf-8")


def resolve_binary_image(
    img_str: str,
    db: Database | None = None,
    user: dict[str, Any] | None = None,
) -> tuple[bytes, str] | None:
    s = str(img_str or "").strip()
    if not s:
        return None
    if s.startswith("data:image/") and "," in s:
        try:
            raw, ext, _ = decode_data_image_url(s)
            return raw, ext
        except ValueError:
            return None
    for prefix, root in (
        ("/images/", DEFAULT_STYLE_IMAGES_DIR),
        ("/generated/", get_generated_dir()),
        ("/uploads/", get_uploads_dir()),
    ):
        if s.startswith(prefix):
            rel = s.removeprefix(prefix).lstrip("/")
            if prefix == "/images/" and rel.lower().startswith("custom/") and not include_private_benchmark_assets():
                return None
            safe_url = sanitize_media_url(s)
            if not safe_url:
                return None
            target = (root / rel).resolve()
            if not _path_is_within(target, root):
                return None
            if prefix in ("/generated/", "/uploads/") and db is not None:
                # An explicit grant makes the picture as public as the content it
                # belongs to; without one, only its owner may read it.
                if not _is_published_media(db, safe_url):
                    if not user or _media_owner(db, safe_url) != int(user["id"]):
                        return None
            if prefix in ("/generated/", "/uploads/") and not target.is_file():
                from .object_storage import ensure_local_copy
                if not ensure_local_copy(safe_url, target):
                    return None
            if target.is_file():
                return target.read_bytes(), (target.suffix.lower() or ".webp")
    return None


def resolve_local_ref_image(
    img_str: str,
    db: Database | None = None,
    user: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    res = resolve_binary_image(img_str, db=db, user=user)
    if not res:
        return None
    raw_bytes, ext = res
    mime = "image/gif" if ext == ".gif" else "image/webp" if ext == ".webp" else "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return {"b64_json": base64.b64encode(raw_bytes).decode("ascii"), "mime_type": mime}


def build_export_zip_package(
    body: dict[str, Any],
    db: Database | None = None,
    user: dict[str, Any] | None = None,
) -> tuple[bytes, str]:
    kind = str(body.get("kind") or "article").strip()
    pack_title = str(body.get("title") or ("Handraw文章配图包" if kind == "article" else "Handraw小红书组图包")).strip()
    raw_md = str(body.get("markdown") or "").strip()
    items = body.get("items") or []

    resolved_entries: list[dict[str, Any]] = []
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            img_url = str(it.get("imageUrl") or "").strip()
            res = resolve_binary_image(img_url, db=db, user=user)
            if not res:
                continue
            img_bytes, ext = res
            role = str(it.get("role") or ("cover" if idx == 0 and kind == "article" else "inline"))
            if kind == "article":
                stem = "00-cover" if role == "cover" else f"{idx:02d}-section-{idx:02d}"
            elif kind == "xhs":
                stem = f"P{idx + 1}-{'cover' if idx == 0 else 'slide'}"
            else:
                stem = f"image-{idx + 1:02d}"

            rel_img_path = f"images/{stem}{ext}"
            zf.writestr(rel_img_path, img_bytes)
            resolved_entries.append(
                {
                    "index": idx,
                    "role": role,
                    "title": str(it.get("title") or stem),
                    "anchorHeading": str(it.get("anchorHeading") or ""),
                    "prompt": str(it.get("prompt") or ""),
                    "theme": str(it.get("theme") or ""),
                    "afterLine": it.get("afterLine") if isinstance(it.get("afterLine"), int) else None,
                    "relPath": f"./{rel_img_path}",
                    "zipPath": rel_img_path,
                }
            )

        if kind == "article":
            cover_entry = next((e for e in resolved_entries if e["role"] == "cover"), None)
            inline_entries = [e for e in resolved_entries if e is not cover_entry]
            has_after_line = any(e.get("afterLine") is not None for e in resolved_entries)
            lines = raw_md.splitlines() if raw_md else [f"# {pack_title}", "", "## 一、核心章节", "正文内容……"]
            md_out: list[str] = []
            html_body: list[str] = []
            cover_inserted = False

            if has_after_line:
                inlines_by_line: dict[int, list[dict[str, Any]]] = {}
                overflow_inlines: list[dict[str, Any]] = []
                for ie in inline_entries:
                    al = ie.get("afterLine")
                    if isinstance(al, int) and 0 <= al < len(lines):
                        inlines_by_line.setdefault(al, []).append(ie)
                    else:
                        overflow_inlines.append(ie)

                has_h1 = any(re.match(r"^#\s+", ln.strip()) for ln in lines)
                if cover_entry and not has_h1:
                    md_out.extend([f"![{cover_entry['title']}]({cover_entry['relPath']})", ""])
                    html_body.append(f'<figure><img src="{html.escape(cover_entry["relPath"])}" alt="{html.escape(cover_entry["title"])}" /></figure>')
                    cover_inserted = True

                for line_idx, ln in enumerate(lines):
                    stripped = ln.strip()
                    if re.match(r"^#\s+", stripped):
                        h1_txt = re.sub(r"^#\s+", "", stripped)
                        md_out.append(ln)
                        html_body.append(f"<h1>{html.escape(h1_txt)}</h1>")
                        if cover_entry and not cover_inserted:
                            md_out.extend(["", f"![{cover_entry['title']}]({cover_entry['relPath']})", ""])
                            html_body.append(f'<figure><img src="{html.escape(cover_entry["relPath"])}" alt="{html.escape(cover_entry["title"])}" /></figure>')
                            cover_inserted = True
                    elif re.match(r"^#{2,3}\s+", stripped):
                        h2_txt = re.sub(r"^#{2,3}\s+", "", stripped)
                        md_out.append(ln)
                        html_body.append(f"<h2>{html.escape(h2_txt)}</h2>")
                    else:
                        md_out.append(ln)
                        if stripped:
                            html_body.append(f"<p>{html.escape(stripped)}</p>")

                    if line_idx in inlines_by_line:
                        for ie in inlines_by_line[line_idx]:
                            md_out.extend(["", f"![{ie['title']}]({ie['relPath']})", ""])
                            html_body.append(f'<figure><img src="{html.escape(ie["relPath"])}" alt="{html.escape(ie["title"])}" /></figure>')

                if cover_entry and not cover_inserted:
                    md_out.insert(0, f"![{cover_entry['title']}]({cover_entry['relPath']})\n")
                    html_body.insert(0, f'<figure><img src="{html.escape(cover_entry["relPath"])}" alt="{html.escape(cover_entry["title"])}" /></figure>')

                for ie in overflow_inlines:
                    md_out.extend(["", f"![{ie['title']}]({ie['relPath']})"])
                    html_body.append(f'<figure><img src="{html.escape(ie["relPath"])}" alt="{html.escape(ie["title"])}" /></figure>')
            else:
                inline_idx = 0
                for ln in lines:
                    stripped = ln.strip()
                    if re.match(r"^#\s+", stripped):
                        h1_txt = re.sub(r"^#\s+", "", stripped)
                        md_out.append(ln)
                        html_body.append(f"<h1>{html.escape(h1_txt)}</h1>")
                        if cover_entry and not cover_inserted:
                            md_out.extend(["", f"![{cover_entry['title']}]({cover_entry['relPath']})", ""])
                            html_body.append(f'<figure><img src="{html.escape(cover_entry["relPath"])}" alt="{html.escape(cover_entry["title"])}" /></figure>')
                            cover_inserted = True
                    elif re.match(r"^#{2,3}\s+", stripped):
                        h2_txt = re.sub(r"^#{2,3}\s+", "", stripped)
                        md_out.append(ln)
                        html_body.append(f"<h2>{html.escape(h2_txt)}</h2>")
                        if inline_idx < len(inline_entries):
                            ie = inline_entries[inline_idx]
                            inline_idx += 1
                            md_out.extend(["", f"![{ie['title']}]({ie['relPath']})", ""])
                            html_body.append(f'<figure><img src="{html.escape(ie["relPath"])}" alt="{html.escape(ie["title"])}" /></figure>')
                    else:
                        md_out.append(ln)
                        if stripped:
                            html_body.append(f"<p>{html.escape(stripped)}</p>")

                if cover_entry and not cover_inserted:
                    md_out.insert(0, f"![{cover_entry['title']}]({cover_entry['relPath']})\n")
                    html_body.insert(0, f'<figure><img src="{html.escape(cover_entry["relPath"])}" alt="{html.escape(cover_entry["title"])}" /></figure>')

                while inline_idx < len(inline_entries):
                    ie = inline_entries[inline_idx]
                    inline_idx += 1
                    md_out.extend(["", f"![{ie['title']}]({ie['relPath']})"])
                    html_body.append(f'<figure><img src="{html.escape(ie["relPath"])}" alt="{html.escape(ie["title"])}" /></figure>')

            zf.writestr("article.md", "\n".join(md_out).strip() + "\n")
            preview_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(pack_title)} — Handraw 图文排版预览</title>
  <style>
    body {{ max-width: 740px; margin: 40px auto; padding: 0 20px; background: #faf7f0; color: #1f1c18; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", serif; line-height: 1.82; }}
    h1 {{ font-size: 28px; line-height: 1.35; margin-bottom: 18px; color: #181512; }}
    h2 {{ font-size: 20px; margin-top: 32px; margin-bottom: 12px; color: #b74227; border-left: 4px solid #b74227; padding-left: 10px; }}
    p {{ font-size: 16px; margin: 12px 0; }}
    figure {{ margin: 18px 0 24px; }}
    img {{ width: 100%; border-radius: 12px; display: block; box-shadow: 0 8px 24px rgba(0,0,0,0.08); }}
  </style>
</head>
<body>
{chr(10).join(html_body)}
</body>
</html>
"""
            zf.writestr("preview.html", preview_doc)
            dl_name = "handraw-article-pack.zip"
        else:
            md_lines = [f"# {pack_title}", "", raw_md or "小红书成套视觉笔记文案与组图：", ""]
            cards_html: list[str] = []
            for e in resolved_entries:
                md_lines.extend([f"## {e['title']}", "", e["theme"] or "", "", f"![{e['title']}]({e['relPath']})", ""])
                cards_html.append(
                    f'<div class="card"><img src="{html.escape(e["relPath"])}" alt="{html.escape(e["title"])}"/><h3>{html.escape(e["title"])}</h3><p>{html.escape(e["theme"])}</p></div>'
                )
            zf.writestr("xiaohongshu-copy.md", "\n".join(md_lines).strip() + "\n")
            zf.writestr(
                "preview.html",
                f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/><title>{html.escape(pack_title)}</title>
<style>body{{background:#f6f2ea;font-family:sans-serif;padding:32px;}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px;max-width:1120px;margin:0 auto;}}.card{{background:#fff;border-radius:14px;padding:12px;box-shadow:0 6px 20px rgba(0,0,0,0.07);}}.card img{{width:100%;border-radius:10px;display:block;}}.card h3{{font-size:15px;margin:10px 0 4px;}}.card p{{font-size:12.5px;color:#665e54;margin:0;line-height:1.5;}}</style>
</head><body><h2 style="text-align:center;margin-bottom:24px;">{html.escape(pack_title)}</h2><div class="grid">{''.join(cards_html)}</div></body></html>""",
            )
            dl_name = "handraw-xhs-deck-pack.zip" if kind == "xhs" else "handraw-images-pack.zip"

        zf.writestr(
            "prompts-manifest.json",
            json.dumps(
                {"title": pack_title, "kind": kind, "imageCount": len(resolved_entries), "items": resolved_entries},
                ensure_ascii=False,
                indent=2,
            ),
        )

    return buf.getvalue(), dl_name


def _private_media_access(
    db: Database,
    media_url: str,
    user: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Return (allowed, cache-control) for generated/uploaded media."""
    safe = sanitize_media_url(media_url).split("?", 1)[0]
    owner = _media_owner(db, safe)
    if owner is not None and user and int(user.get("id") or 0) == owner:
        return True, "private, no-store"
    if _is_published_media(db, safe):
        # A work can be hidden by moderation later. Never emit long-lived
        # immutable/CDN cache headers for user-generated media access grants.
        return True, "public, max-age=60, must-revalidate"
    if user:
        from .forum_boards import access_sql
        allowed = db.get_conn().execute(f"""SELECT 1 FROM media_public_grants g
            JOIN forum_topics t ON g.target_type='topic' AND g.target_id=t.id
            WHERE g.media_url=? AND g.revoked_at IS NULL AND t.status='published'
              AND (COALESCE(t.work_id,'')='' OR EXISTS(
                SELECT 1 FROM works w JOIN work_media wm ON wm.work_id=w.id
                JOIN media_assets m ON m.id=wm.media_id
                WHERE w.id=t.work_id AND w.status='published' AND m.storage_key=g.media_url))
              AND {access_sql('t.category', user)} LIMIT 1""", (safe,)).fetchone()
        if allowed:
            return True, "private, no-store"
    return False, "private, no-store"


def _grant_published_media(
    db: Database,
    user: dict[str, Any],
    body: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
) -> None:
    """Create explicit public grants after a publish service commits."""
    table = {"work": "works", "topic": "forum_topics", "asset": "catalog_assets"}.get(target_type)
    if not table or not target_id:
        return
    key = "code" if target_type == "asset" else "id"
    row = db.get_conn().execute(f"SELECT status FROM {table} WHERE {key} = ? LIMIT 1", (target_id,)).fetchone()
    if not row or row["status"] != "published":
        return
    values: list[str] = []
    values.extend(str(v) for v in _iter_media_values(body.get("cover")))
    values.extend(str(v) for v in _iter_media_values(body.get("image")))
    values.extend(str(v) for v in _iter_media_values(body.get("images")))
    for media_url in values:
        safe = sanitize_media_url(media_url).split("?", 1)[0]
        if not safe.startswith(("/uploads/", "/generated/")):
            continue
        try:
            grant_studio_media_public(db, user, safe, target_type, target_id)
        except ServiceError:
            # A malformed/foreign media URL remains private; publishing the
            # text itself must not turn it into a public file by accident.
            continue
        except Exception:
            continue


def _revoke_media_grants(db: Database, target_type: str, target_id: str) -> None:
    if not target_type or not target_id:
        return
    try:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE media_public_grants SET revoked_at = ? WHERE target_type = ? AND target_id = ? AND revoked_at IS NULL",
                (utc_now_iso(), target_type, target_id),
            )
    except Exception:
        return


def build_robots_txt(origin: str, is_admin: bool = False) -> bytes:
    if is_admin:
        return b"User-agent: *\nDisallow: /\n"
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /api/admin/",
        "Disallow: /api/auth/",
        f"Sitemap: {origin.rstrip('/')}/sitemap.xml",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _is_demo_seed_record(record_id: str) -> bool:
    """Recognize fixture IDs from the live seed registry."""
    value = str(record_id or "")
    return value in seed_ids("works") or value in seed_ids("topics")


def build_sitemap_xml(db: Database, origin: str) -> bytes:
    base = origin.rstrip("/")
    conn = db.get_conn()
    urls: list[tuple[str, str]] = [
        (f"{base}/?view=styles", "0.9"),
        (f"{base}/?view=layouts", "0.9"),
        (f"{base}/?view=works", "1.0"),
        (f"{base}/?view=rankings", "0.8"),
    ]
    for w in conn.execute(
        "SELECT id FROM works WHERE status = 'published' ORDER BY featured DESC, published_at_ms DESC"
    ).fetchall():
        if not demo_mode_enabled() and _is_demo_seed_record(w["id"]):
            continue
        urls.append((f"{base}/?view=work&id={urllib.parse.quote(w['id'])}", "0.8"))
    for a in conn.execute(
        "SELECT code, kind FROM catalog_assets WHERE status = 'published' ORDER BY published_at_ms DESC"
    ).fetchall():
        urls.append((f"{base}/t/{urllib.parse.quote(a['code'])}", "0.7"))

    items_xml = "\n".join(
        f"  <url><loc>{html.escape(loc)}</loc><changefreq>daily</changefreq><priority>{prio}</priority></url>"
        for loc, prio in urls
    )
    xml_doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items_xml}\n"
        "</urlset>\n"
    )
    return xml_doc.encode("utf-8")


def render_seo_portal_html(db: Database, raw_html: str, origin: str, qs: dict[str, list[str]]) -> bytes:
    from .services import get_work_client_prompt, filter_display_prompt
    base = origin.rstrip("/")
    conn = db.get_conn()
    view = (qs.get("view", ["discover"])[0] or "discover").strip()
    work_id = (qs.get("work", [""])[0] or (qs.get("id", [""])[0] if view == "work" else "")).strip()
    asset_code = (qs.get("asset", [""])[0] or (qs.get("id", [""])[0] if view == "asset" else "")).strip().upper()
    profile_user = (qs.get("user", [""])[0] or "").strip()
    if not demo_mode_enabled() and is_seed_username(profile_user):
        profile_user = ""

    work_rows = conn.execute(
        "SELECT w.id, w.title, w.author_username, w.author_name, w.images_json, "
        "w.styles_json, w.layout_code, w.price, w.prompt, w.prompt_has_secret, "
        "w.notes, w.cheers, cover.storage_key AS selected_cover_url "
        "FROM works w LEFT JOIN media_assets cover ON cover.id=w.cover_media_id "
        "WHERE w.status='published' ORDER BY w.featured DESC, w.published_at_ms DESC"
    ).fetchall()
    if not demo_mode_enabled():
        work_rows = [w for w in work_rows if not _is_demo_seed_record(w["id"])]
    total_works = len(work_rows)

    page_title = f"Handraw 手绘风社区 2.0 — 375+ 画风库 · 174+ 图型库 · {total_works} 件晒作品广场"
    meta_desc = (
        f"Handraw 手绘风视觉创作社区，开放浏览 375+ 手绘画风、174+ 结构化版式图型与 {total_works} 件真实生图作品及提示词配方，"
        "支持在线无限画布一键复刻同款。"
    )
    canonical_url = f"{base}/?view={urllib.parse.quote(view)}"
    og_image = f"{base}/images/poster-demo-autumn-equinox.webp"
    json_ld: dict[str, Any]

    def _seo_cover_url(work: Any) -> str:
        """Use the author's linked cover, not the first output slot.

        Keep GIFs as still thumbnails in social previews and server-rendered
        discovery cards. Work details continue to use the animated original.
        """
        imgs = json.loads(work["images_json"] or "[]")
        preferred = str(work["selected_cover_url"] or "")
        selected = preferred if preferred and preferred in imgs else (
            imgs[0] if imgs else "/images/poster-demo-autumn-equinox.webp"
        )
        if selected.startswith("/") and selected.split("?", 1)[0].lower().endswith(".gif"):
            return selected + ("&" if "?" in selected else "?") + "w=480"
        return selected

    target_work = next((w for w in work_rows if w["id"] == work_id), None) if work_id else None
    if target_work:
        first_img = _seo_cover_url(target_work)
        og_image = first_img if first_img.startswith("http") else f"{base}{first_img}"
        styles_list = json.loads(target_work["styles_json"] or "[]")
        recipe_tags = " / ".join([*styles_list, *([target_work["layout_code"]] if target_work["layout_code"] else [])])
        from .services import get_work_client_prompt
        safe_p, _ = get_work_client_prompt(target_work, is_admin_route=False)
        snippet_src = target_work["notes"] or filter_display_prompt(safe_p)[:80]
        page_title = f"{target_work['title']} (@{target_work['author_name']}) 作品详情与评论 — Handraw 晒作品广场"
        meta_desc = f"由 @{target_work['author_name']} 分享的手绘晒作品《{target_work['title']}》" + (
            f"（配方：{recipe_tags}）" if recipe_tags else ""
        ) + f"：{snippet_src[:110]}"
        canonical_url = f"{base}/?view=work&id={urllib.parse.quote(target_work['id'])}"
        json_ld = {
            "@context": "https://schema.org",
            "@type": "VisualArtwork",
            "name": target_work["title"],
            "image": og_image,
            "creator": {"@type": "Person", "name": target_work["author_name"]},
            "description": meta_desc,
            "url": canonical_url,
        }
    elif view in ("profile", "account") and profile_user:
        u_row = conn.execute(
            "SELECT username, display_name, bio FROM users WHERE username = ?",
            (profile_user,),
        ).fetchone()
        disp_name = u_row["display_name"] if u_row else profile_user
        bio_txt = (u_row["bio"] if u_row and u_row["bio"] else "") or "Handraw 手绘风社区认证创作者独立个人主页"
        page_title = f"@{disp_name} 的个人主页 — Handraw 手绘风社区"
        meta_desc = f"访问 @{disp_name} ({profile_user}) 在 Handraw 手绘风社区的独立个人主页：{bio_txt[:120]}"
        canonical_url = f"{base}/?view=profile&user={urllib.parse.quote(profile_user)}"
        json_ld = {
            "@context": "https://schema.org",
            "@type": "ProfilePage",
            "name": page_title,
            "description": meta_desc,
            "url": canonical_url,
            "mainEntity": {"@type": "Person", "name": disp_name, "identifier": profile_user},
        }
    else:
        if view == "discover":
            page_title = "AI 视觉创作与实测分享 — 手绘风创作社区"
            meta_desc = "看看大家做出了什么，也把你的做法留下来。浏览画风、图型和公开作品，找到适合这次创作的方法。"
        elif view == "works":
            page_title = f"晒作品广场（{total_works} 件手绘生图作品与提示词配方）— Handraw 手绘风社区"
            meta_desc = f"匿名免登录公开浏览 {total_works} 件社区创作者真实手绘生图作品、画风图型搭配方案与实测提示词，支持一键带入无限画布复刻。"
        elif view == "layouts":
            page_title = "174+ 结构化版式与信息图图型库 — Handraw 手绘风社区"
        elif view == "rankings":
            page_title = "创作者荣誉殿堂与作品风云榜 — Handraw 手绘风社区"
        if asset_code:
            canonical_url = f"{base}/?view=asset&id={urllib.parse.quote(asset_code)}"
            a_row = conn.execute(
                "SELECT code, name, description FROM catalog_assets WHERE code = ?",
                (asset_code,),
            ).fetchone()
            a_name = f" {a_row['name']}" if a_row and a_row["name"] else ""
            page_title = f"{asset_code}{a_name} 详情与实测评论 — Handraw 手绘风社区"
            if a_row and a_row["description"]:
                meta_desc = f"{asset_code}{a_name}：{a_row['description'][:130]}"

        json_ld = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": page_title,
            "description": meta_desc,
            "url": canonical_url,
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": total_works,
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": idx + 1,
                        "url": f"{base}/?view=work&id={urllib.parse.quote(w['id'])}",
                        "name": w["title"],
                    }
                    for idx, w in enumerate(work_rows[:30])
                ],
            },
        }

    ld_str = json.dumps(json_ld, ensure_ascii=False).replace("</", "<\\/")
    head_seo = (
        f"  <title>{html.escape(page_title)}</title>\n"
        f'  <meta name="description" content="{html.escape(meta_desc)}" />\n'
        f'  <meta name="robots" content="index, follow, max-image-preview:large" />\n'
        f'  <link rel="canonical" href="{html.escape(canonical_url)}" />\n'
        f'  <meta property="og:site_name" content="Handraw 手绘风社区" />\n'
        f'  <meta property="og:type" content="website" />\n'
        f'  <meta property="og:title" content="{html.escape(page_title)}" />\n'
        f'  <meta property="og:description" content="{html.escape(meta_desc)}" />\n'
        f'  <meta property="og:url" content="{html.escape(canonical_url)}" />\n'
        f'  <meta property="og:image" content="{html.escape(og_image)}" />\n'
        f'  <script type="application/ld+json">{ld_str}</script>'
    )

    ssr_cards: list[str] = []
    for w in work_rows[:24]:
        img0 = _seo_cover_url(w)
        styles = json.loads(w["styles_json"] or "[]")
        tags = " · ".join([*styles, *([w["layout_code"]] if w["layout_code"] else [])]) or "自由手绘创作"
        safe_p, _ = get_work_client_prompt(w, is_admin_route=False)
        summary_txt = w["notes"] or filter_display_prompt(safe_p)[:80]
        w_href = f"/?view=work&id={urllib.parse.quote(w['id'])}"
        ssr_cards.append(
            f'<article class="hw-seo-work-item">'
            f'<a href="{html.escape(w_href)}"><h2>{html.escape(w["title"])}</h2></a>'
            f'<img data-hw-src="{html.escape(img0)}" alt="{html.escape(w["title"])}" loading="lazy" width="320" />'
            f"<p>作者：@{html.escape(w['author_name'])} ｜ 视觉配方：{html.escape(tags)} ｜ 鼓励：{int(w['cheers'])}</p>"
            f"<p>{html.escape(summary_txt)}</p>"
            f"</article>"
        )

    ssr_section = (
        '<div style="padding:36px 0 18px;text-align:center;color:var(--ink-muted);">'
        "正在加载 Handraw 画风库、图型库与公开晒作品广场…</div>\n"
        '<section class="hw-seo-ssr-directory" style="max-width:1100px;margin:0 auto;padding:12px 16px;" aria-label="公开晒作品索引">'
        f"<h1>{html.escape(page_title)}</h1>"
        f"<p>{html.escape(meta_desc)}</p>"
        '<nav aria-label="站点公开频道">'
        '<a href="/?view=discover">发现作品与做法</a> · '
        '<a href="/?view=styles">手绘画风库</a> · '
        '<a href="/?view=layouts">结构化图型库</a> · '
        '<a href="/?view=works">晒作品广场</a> · '
        '<a href="/?view=rankings">创作者与作品荣誉榜</a>'
        "</nav>"
        f'<div class="hw-seo-works-list">{"".join(ssr_cards)}</div>'
        "</section>"
    )

    enriched = re.sub(r"<title>.*?</title>", lambda _: head_seo, raw_html, count=1, flags=re.DOTALL)
    enriched = re.sub(
        r'(<main[^>]*id="main-app-root"[^>]*>).*?(</main>)',
        lambda m: f"{m.group(1)}\n{ssr_section}\n  {m.group(2)}",
        enriched,
        count=1,
        flags=re.DOTALL,
    )
    return enriched.encode("utf-8")


def execute_studio_generation(db, user, body, *, demo_mode=False, request_log_id=""):
    """Shared generation reservation, gateway dispatch and settlement for all entries."""
    cfg = load_image_service_config()
    simulation = str(body.get("simulateGateway") or "").strip().lower()
    if simulation and not demo_mode:
        raise ServiceError("演示/测试接口未启用", status=404, code="demo_disabled")
    if not cfg and not simulation:
        return ({"ok": False, "liveImageEnabled": False, "demoMode": demo_mode, "error": "本地未配置 image-service.json，无法进行真实生图"}, 503)
        return

    is_openai_gw = str(cfg.get("protocol") or "").strip().lower() == "openai"
    prep = prepare_cloud_generation(
        db,
        user,
        body,
        gateway_protocol="openai" if is_openai_gw else "",
    )
    gen_id = prep["genId"]
    submitted = False
    gw_started_at = 0.0
    endpoint = ""
    gw_model = ""
    gw_size = size_for_ratio(str(body.get("ratio") or "3:4"))
    full_prompt = ""
    refs: list[dict[str, str]] = []
    req_log_id = request_log_id or str(prep.get("requestId") or "")
    try:
        claim = claim_cloud_generation_submission(db, user, gen_id)
        if not claim.get("claimed"):
            existing = get_user_studio_task(
                db,
                user,
                task_id=str(claim.get("taskId") or ""),
                request_id=str(prep.get("requestId") or body.get("requestId") or body.get("clientRequestId") or ""),
            )
            existing = existing or {}
            response = {
                "ok": True,
                "genId": gen_id,
                "requestId": prep.get("requestId") or "",
                "clientRequestId": prep.get("clientRequestId") or prep.get("requestId") or "",
                "idempotent": True,
                "taskId": existing.get("taskId") or claim.get("taskId") or "",
                "status": existing.get("status") or claim.get("status") or "queued",
                "images": existing.get("images") or [],
                "error": existing.get("error") or "",
                "costType": prep.get("costType") or "",
                "creditsSpent": prep.get("creditsSpent") or 0,
                "amountCents": prep.get("amountCents",0),
                "billingSpec": prep.get("billingSpec"),
                "credits": prep.get("credits") or 0,
                "freeQuotaRemaining": prep.get("freeQuotaRemaining") or 0,
            }
            if "systemAppend" in prep:
                response["systemAppend"] = prep["systemAppend"]
            if prep.get("recipeId"):
                response["recipeId"] = prep["recipeId"]
            if prep.get("promptTrimmed"):
                response["promptTrimmed"] = True
            if prep.get("promptMasked"):
                response["promptMasked"] = True
            response["finalPrompt"] = prep.get("finalPrompt") or ""
            return (response, 202 if response["status"] in ("queued", "running") else 200)
            return
        if simulation == "fail":
            raise RuntimeError("模拟云端网关连接超时异常")
        if simulation == "ok":
            fake_tid = f"sim_{uuid.uuid4().hex[:10]}"
            complete_cloud_generation(db, gen_id, fake_tid, ["/images/poster-demo-autumn-equinox.webp"])
            sim_res = {
                "ok": True,
                "genId": gen_id,
                "requestId": prep.get("requestId") or "",
                "idempotent": bool(prep.get("idempotent")),
                "taskId": fake_tid,
                "status": "success",
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "finalPrompt": prep.get("finalPrompt") or "",
                "costType": prep["costType"],
                "creditsSpent": prep["creditsSpent"],
                "amountCents": prep.get("amountCents",0),
                "billingSpec": prep.get("billingSpec"),
                "credits": prep["credits"],
                "freeQuotaRemaining": prep["freeQuotaRemaining"],
            }
            if "systemAppend" in prep:
                sim_res["systemAppend"] = prep["systemAppend"]
            if prep.get("recipeId"):
                sim_res["recipeId"] = prep["recipeId"]
            if prep.get("promptTrimmed"):
                sim_res["promptTrimmed"] = True
            if prep.get("promptMasked"):
                sim_res["promptMasked"] = True
            return (sim_res, 200)
            return

        ratio = str(body.get("ratio") or "3:4")
        use_ch001 = bool(body.get("useCh001"))
        custom_ref = str(body.get("customRefImg") or "")
        ref_images = body.get("refImages") or []
        request_id = str(prep.get("requestId") or body.get("requestId") or body.get("clientRequestId") or "").strip()
        task_id = request_id if request_id else str(uuid.uuid4())
        refs: list[dict[str, str]] = []

        if use_ch001:
            resolved = resolve_local_ref_image("/images/characters/CH-001.webp", db=db, user=user)
            if resolved:
                refs.append(resolved)
        if custom_ref:
            resolved = resolve_local_ref_image(custom_ref, db=db, user=user)
            if resolved:
                refs.append(resolved)
        if isinstance(ref_images, list):
            for r_str in ref_images[:6]:
                resolved = resolve_local_ref_image(str(r_str), db=db, user=user)
                if resolved:
                    refs.append(resolved)

        grow = db.get_conn().execute(
            "SELECT prompt FROM studio_generations WHERE id = ?", (gen_id,)
        ).fetchone()
        full_prompt = (grow["prompt"] if grow else "") or prep["finalPrompt"]
        gw_model = str(cfg.get("model") or prep.get("model") or "gpt-image-2").strip()
        gw_quality = str(cfg.get("quality") or "auto").strip() or "auto"
        gw_timeout = int(cfg.get("timeout") or (180 if is_openai_gw else 28))
        spec=prep.get("billingSpec")
        if spec:
            gw_model=spec["model"]
            gw_quality=spec["quality"]
        gw_size = spec["size"] if spec else size_for_ratio(ratio)

        if is_openai_gw:
            endpoint = "/v1/images/edits" if refs else "/v1/images/generations"
            record_cloud_generation_task_id(db, gen_id, task_id)
            _mark_generation_gateway_protocol(db, gen_id, "openai")
            submitted = True
            gw_started_at = time.monotonic()
            logger.info(
                "Gateway submit start: request_id=%s gen_id=%s protocol=openai endpoint=%s model=%s size=%s quality=%s refs=%d",
                req_log_id, gen_id, endpoint, gw_model, gw_size, gw_quality, len(refs),
            )
            db.release_request_connection()
            gw_res = openai_image_gateway_request(
                cfg,
                full_prompt,
                model=gw_model,
                size=gw_size,
                quality=gw_quality,
                refs=refs or None,
                timeout=gw_timeout,
            )
            data_items = gw_res.get("data") or []
            local_urls: list[str] = []
            if isinstance(data_items, list):
                for idx, image_item in enumerate(data_items):
                    local_url = _cache_gateway_item_image(image_item, f"{task_id}_{idx}")
                    if local_url:
                        local_urls.append(local_url)
            complete_cloud_generation(db, gen_id, task_id, local_urls)
            if not local_urls:
                gw_elapsed_ms = (time.monotonic() - gw_started_at) * 1000.0 if gw_started_at else 0.0
                logger.error(
                    "Gateway empty response: request_id=%s gen_id=%s endpoint=%s model=%s size=%s refs=%d duration_ms=%.1f",
                    req_log_id, gen_id, endpoint, gw_model, gw_size, len(refs), gw_elapsed_ms,
                )
                return ({"ok": False, "refunded": True, "error": "生图网关未返回有效图片（已自动退还额度/积分）"}, 502)
                return
            gw_elapsed_ms = (time.monotonic() - gw_started_at) * 1000.0 if gw_started_at else 0.0
            logger.info(
                "Gateway submit ok: request_id=%s gen_id=%s endpoint=%s model=%s images=%d duration_ms=%.1f",
                req_log_id, gen_id, endpoint, gw_model, len(local_urls), gw_elapsed_ms,
            )
            actual_id = task_id
            gw_out: dict[str, Any] = {
                "ok": True,
                "genId": gen_id,
                "requestId": prep.get("requestId") or "",
                "idempotent": bool(prep.get("idempotent")),
                "taskId": actual_id,
                "status": "success",
                "images": local_urls,
                "finalPrompt": prep.get("finalPrompt") or "",
                "costType": prep["costType"],
                "creditsSpent": prep["creditsSpent"],
                "amountCents": prep.get("amountCents",0),
                "billingSpec": prep.get("billingSpec"),
                "credits": prep["credits"],
                "freeQuotaRemaining": prep["freeQuotaRemaining"],
            }
        else:
            gw_payload: dict[str, Any] = {
                "client_task_id": task_id,
                "prompt": full_prompt,
                "model": gw_model,
                "size": gw_size,
                "quality": gw_quality,
            }
            if refs:
                gw_payload["images"] = refs
                endpoint = "/api/image-tasks/edits"
            else:
                endpoint = "/api/image-tasks/generations"

            record_cloud_generation_task_id(db, gen_id, task_id)
            submitted = True
            gw_started_at = time.monotonic()
            logger.info(
                "Gateway submit start: request_id=%s gen_id=%s protocol=image-tasks endpoint=%s model=%s size=%s quality=%s refs=%d",
                req_log_id, gen_id, endpoint, gw_model, gw_size, gw_quality, len(refs),
            )
            db.release_request_connection()
            gw_res = gateway_request(endpoint, payload=gw_payload, timeout=gw_timeout)
            actual_id = str(gw_res.get("id") or task_id)
            complete_cloud_generation(db, gen_id, actual_id)
            gw_out = {
                "ok": True,
                "genId": gen_id,
                "requestId": prep.get("requestId") or "",
                "idempotent": bool(prep.get("idempotent")),
                "taskId": actual_id,
                "status": gw_res.get("status") or "queued",
                "costType": prep["costType"],
                "creditsSpent": prep["creditsSpent"],
                "amountCents": prep.get("amountCents",0),
                "billingSpec": prep.get("billingSpec"),
                "credits": prep["credits"],
                "freeQuotaRemaining": prep["freeQuotaRemaining"],
            }
        if "systemAppend" in prep:
            gw_out["systemAppend"] = prep["systemAppend"]
        if prep.get("recipeId"):
            gw_out["recipeId"] = prep["recipeId"]
        if prep.get("promptTrimmed"):
            gw_out["promptTrimmed"] = True
        if prep.get("promptMasked"):
            gw_out["promptMasked"] = True
        return (gw_out, 200)
    except Exception as exc:
        gw_elapsed_ms = (time.monotonic() - gw_started_at) * 1000.0 if gw_started_at else 0.0
        gw_proto = "openai" if is_openai_gw else "image-tasks"
        gw_api_key = str(cfg.get("key") or "") if isinstance(cfg, dict) else ""
        try:
            raw_exc_str = str(exc)
        except Exception:
            raw_exc_str = ""
        _, exc_str_secret = _sanitize_gateway_error_detail(
            raw_exc_str, db=db, prompt=full_prompt, api_key=gw_api_key,
        )
        gw_exc_info: Any = False if exc_str_secret else True
        tb_frames = (
            "\nTraceback (redacted exception message):\n" + "".join(traceback.format_tb(exc.__traceback__)).rstrip()
            if exc_str_secret and exc.__traceback__
            else ""
        )
        if not submitted:
            logger.error(
                "Gateway call not submitted: request_id=%s gen_id=%s protocol=%s error_type=%s err=%s%s",
                req_log_id,
                gen_id,
                gw_proto,
                type(exc).__name__,
                sanitize_log_text(raw_exc_str) if not exc_str_secret else "[redacted]",
                tb_frames,
                exc_info=gw_exc_info,
            )
            refund_failed_cloud_generation(db, gen_id, "生图网关连接失败")
            return ({"ok": False, "refunded": True, "error": "生图网关连接失败（已自动退还额度/积分）"}, 502)
        elif is_openai_gw or _gateway_failure_is_definite(exc):
            if isinstance(exc, urllib.error.HTTPError):
                err_body_bytes = b""
                try:
                    try:
                        raw_read = exc.read(16384)
                    except TypeError:
                        raw_read = exc.read()[:16384]
                    if isinstance(raw_read, bytes):
                        err_body_bytes = raw_read
                    elif isinstance(raw_read, str):
                        err_body_bytes = raw_read.encode("utf-8", errors="ignore")
                except Exception:
                    err_body_bytes = b""
                detail, secret_matched = _sanitize_gateway_error_detail(
                    err_body_bytes, db=db, prompt=full_prompt, api_key=gw_api_key,
                )
                logger.error(
                    "Gateway error: request_id=%s gen_id=%s protocol=%s endpoint=%s model=%s size=%s refs=%d status=%s duration_ms=%.1f body_len=%d detail=%s%s",
                    req_log_id, gen_id, gw_proto, endpoint or "-", gw_model or "-", gw_size, len(refs),
                    exc.code, gw_elapsed_ms, len(err_body_bytes), detail or "-", tb_frames,
                    exc_info=gw_exc_info,
                )
                err_msg = f"网关请求失败 (HTTP {exc.code}): {detail}" if (detail and not secret_matched) else f"网关请求失败 (HTTP {exc.code})"
            elif isinstance(exc, (socket.timeout, TimeoutError)) or (
                isinstance(exc, urllib.error.URLError)
                and isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError))
            ):
                logger.error(
                    "Gateway timeout: request_id=%s gen_id=%s protocol=%s endpoint=%s model=%s size=%s refs=%d duration_ms=%.1f error_type=%s%s",
                    req_log_id, gen_id, gw_proto, endpoint or "-", gw_model or "-", gw_size, len(refs),
                    gw_elapsed_ms, type(exc).__name__, tb_frames,
                    exc_info=gw_exc_info,
                )
                err_msg = "生图网关请求超时"
            else:
                detail, _secret_matched = _sanitize_gateway_error_detail(
                    getattr(exc, "reason", None) or raw_exc_str,
                    db=db,
                    prompt=full_prompt,
                    api_key=gw_api_key,
                )
                logger.error(
                    "Gateway exception: %s (request_id=%s gen_id=%s protocol=%s endpoint=%s model=%s size=%s refs=%d duration_ms=%.1f detail=%s)%s",
                    type(exc).__name__, req_log_id, gen_id, gw_proto, endpoint or "-", gw_model or "-", gw_size, len(refs),
                    gw_elapsed_ms, detail or "-", tb_frames,
                    exc_info=gw_exc_info,
                )
                err_msg = "生图网关连接失败"
            refund_failed_cloud_generation(db, gen_id, err_msg)
            return ({"ok": False, "refunded": True, "error": f"{err_msg}（已自动退还额度/积分）"}, 502)
        else:
            logger.warning(
                "Gateway exception: %s (status unknown, gen_id=%s request_id=%s protocol=%s endpoint=%s model=%s size=%s refs=%d duration_ms=%.1f)%s",
                type(exc).__name__, gen_id, req_log_id, gw_proto, endpoint or "-", gw_model or "-", gw_size, len(refs),
                gw_elapsed_ms, tb_frames,
                exc_info=gw_exc_info,
            )
            confirming_out = {
                "ok": True,
                "genId": gen_id,
                "requestId": prep.get("requestId") or "",
                "idempotent": bool(prep.get("idempotent")),
                "taskId": task_id,
                "status": "queued",
                "confirming": True,
                "costType": prep["costType"],
                "creditsSpent": prep["creditsSpent"],
                "amountCents": prep.get("amountCents",0),
                "billingSpec": prep.get("billingSpec"),
                "credits": prep["credits"],
                "freeQuotaRemaining": prep["freeQuotaRemaining"],
            }
            if "systemAppend" in prep:
                confirming_out["systemAppend"] = prep["systemAppend"]
            if prep.get("recipeId"):
                confirming_out["recipeId"] = prep["recipeId"]
            if prep.get("promptTrimmed"):
                confirming_out["promptTrimmed"] = True
            return (confirming_out, 200)
    return


class HandrawRequestHandler(BaseHTTPRequestHandler):
    server_version = "HandrawWeb/2.0"

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            db = getattr(self.server, "db", None)
            if db is not None and hasattr(db, "release_request_connection"):
                db.release_request_connection()

    def log_message(self, fmt: str, *args: Any) -> None:
        # BaseHTTPRequestHandler includes the raw request line (OAuth query
        # secrets). Safe request summaries are emitted by send_response below.
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        if not hasattr(self, "headers"):
            # Malformed HTTP before a request has even been parsed.
            super().send_error(code, message, explain)
            return
        public_message = "找不到请求的内容" if code == 404 else "这个操作暂时无法执行，请返回首页后重试。"
        self._send_json({"ok": False, "error": public_message, "code": "http_error"}, status=code)

    def send_response(self, code: int, message: str | None = None) -> None:
        if not hasattr(self, "_request_id"):
            self._request_id = uuid.uuid4().hex
        path = str(getattr(self, "path", "")).split("?", 1)[0].split("#", 1)[0]
        path = re.sub(r"[\x00-\x20\x7f]", "_", path)[:512]
        method = str(getattr(self, "command", "UNKNOWN"))
        elapsed_ms = (time.monotonic() - getattr(self, "_request_started", time.monotonic())) * 1000
        if code >= 400 or (path.startswith("/api/") and path != "/api/health"):
            level = logging.ERROR if code >= 500 else (logging.WARNING if code >= 400 else logging.INFO)
            logger.log(
                level, "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                self._request_id, method, path, code, max(0, elapsed_ms),
                exc_info=(sys.exc_info()[0] is not None) if code >= 500 else False,
            )
            if (
                code >= 400
                and sys.exc_info()[0] is None
                and local_debug_stacks_enabled()
                and (code >= 500 or path.startswith("/api/"))
            ):
                logging.getLogger("handraw.trace").info(
                    "request_id=%s method=%s path=%s status=%s call_stack\n%s",
                    self._request_id,
                    method,
                    path,
                    code,
                    "".join(traceback.format_stack(limit=16)).rstrip(),
                )
        super().send_response(code, message)
        self.send_header("X-Request-ID", self._request_id)

    def _dispatch_request(self, callback: Any, *, enforce_scope: bool = True) -> None:
        """Single boundary for authorization, business errors and unexpected failures."""
        self._request_id = uuid.uuid4().hex
        self._request_started = time.monotonic()
        try:
            if enforce_scope:
                self._enforce_token_scope()
            callback()
        except ServiceError as se:
            if 400 <= se.status < 500 and local_debug_stacks_enabled():
                path = str(getattr(self, "path", "")).split("?", 1)[0].split("#", 1)[0]
                path = re.sub(r"[\x00-\x20\x7f]", "_", path)[:512]
                logging.getLogger("handraw.trace").info(
                    "request_id=%s method=%s path=%s status=%s code=%s",
                    self._request_id,
                    getattr(self, "command", "UNKNOWN"),
                    path,
                    se.status,
                    se.code,
                    exc_info=True,
                )
            err_body = {"ok": False, "error": se.message, "code": se.code}
            if getattr(se, "extra", None):
                err_body.update(se.extra)
            self._send_json(err_body, status=se.status)
        except Exception:
            # send_response logs the active exception, including its traceback.
            # Internal SQL/paths/provider details belong in logs, not responses.
            self._send_json({"ok": False, "error": "服务暂时出错，请稍后重试", "code": "internal_error"}, status=500)

    @property
    def db(self) -> Database:
        return getattr(self.server, "db")

    def _demo_enabled(self) -> bool:
        return bool(getattr(self.server, "allow_demo_routes", False) or demo_mode_enabled())

    def _require_demo_mode(self) -> None:
        if not self._demo_enabled():
            raise ServiceError("演示/测试接口未启用", status=404, code="demo_disabled")

    def _enforce_write_origin(self) -> None:
        allowed, reason = check_write_origin({k: v for k, v in self.headers.items()})
        # The isolated demo fixture uses urllib clients without browser
        # provenance.  It is explicitly opted in and never weakens production
        # cookie writes.
        if not allowed and self._demo_enabled():
            if reason == "missing_origin":
                return
            srv_port = getattr(self.server, "server_port", None)
            origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
            if origin:
                parsed = urlparse(origin)
                if parsed.hostname in ("localhost", "127.0.0.1", "[::1]") and (srv_port is None or parsed.port == srv_port):
                    return
        if not allowed:
            raise ServiceError("写请求来源未通过校验", status=403, code=f"csrf_{reason}")

    def _client_ip(self) -> str:
        """The address a rate limit should key on.

        Behind the project's nginx deployment every request arrives from
        127.0.0.1, so keying on the socket address would put *all* visitors in
        one bucket — one person registering a few times would lock everyone out.
        The forwarded header is therefore honoured, but only when the connection
        itself comes from the local reverse proxy; a direct client cannot spoof
        its way into a fresh bucket.
        """
        peer = self.client_address[0] if self.client_address else "unknown"
        if peer not in ("127.0.0.1", "::1", "localhost"):
            return peer
        forwarded = (self.headers.get("X-Real-IP") or "").strip()
        if forwarded:
            return forwarded
        chain = (self.headers.get("X-Forwarded-For") or "").strip()
        if chain:
            # The left-most entry is the original client as recorded by the
            # outermost trusted proxy.
            first = chain.split(",")[0].strip()
            if first:
                return first
        return peer

    def _enforce_auth_rate_limit(self, scope: str, subject: str, *, per_ip_only: bool = False) -> None:
        if self._demo_enabled():
            return
        ip_addr = self._client_ip()
        if per_ip_only:
            # The caller controls the other half of the key, so it must not be
            # part of it.
            key = ip_addr
        else:
            key = f"{ip_addr}|{(subject or '').strip().lower()[:120]}"
        if not check_auth_rate_limit(scope, key):
            raise ServiceError("请求过于频繁，请稍后再试", status=429, code="rate_limited")

    def _feature_get(self, req_path: str, qs: dict[str, list[str]]) -> bool:
        from .economy_routes import handle_get
        if handle_get(self,req_path,qs):
            return True
        try:
            from .features import handle_feature_get
        except ImportError:
            return False
        return bool(handle_feature_get(self, req_path, qs))

    def _feature_post(self, req_path: str, body: dict[str, Any]) -> bool:
        from .economy_routes import handle_post
        if handle_post(self,req_path,body):
            return True
        try:
            from .features import handle_feature_post
        except ImportError:
            return False
        return bool(handle_feature_post(self, req_path, body))

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin") or ""
        self.send_header("Vary", "Origin")
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin.rstrip("/"))
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-Handraw-Token, Api-Key, User-Api-Key, Api-Username, X-CSRF-Token",
            )
            self.send_header("Access-Control-Allow-Credentials", "true")

    def _drain_request_body(self) -> None:
        """Consume an unread request body so the socket can close cleanly.

        Rejecting a write before its body is read leaves bytes in the receive
        buffer; closing the socket then sends RST and the client loses the
        error response it was owed.
        """
        if getattr(self, "_body_consumed", False):
            return
        self._body_consumed = True
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return
        if length <= 0:
            return
        if length > MAX_JSON_BODY_BYTES:
            self.close_connection = True
            return
        try:
            self.rfile.read(length)
        except Exception:
            self.close_connection = True

    def _send_json(
        self,
        obj: dict[str, Any],
        status: int = 200,
        set_cookie: str | None = None,
    ) -> None:
        if status >= 400:
            self._drain_request_body()
            obj = dict(obj, requestId=getattr(self, "_request_id", None) or uuid.uuid4().hex)
            self._request_id = obj["requestId"]
            from .application_errors import render_error_page, wants_error_page
            if wants_error_page(self.headers):
                body = render_error_page(status, obj.get("error") or "请返回首页后重试。", self._request_id)
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
                if set_cookie:
                    self.send_header("Set-Cookie", set_cookie)
                self.send_header("Content-Length", str(len(body)))
                try:
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(body)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    pass
                return
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def _send_bytes(self, data: bytes, content_type: str, cache: str = "no-cache") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache)
        self._cors_headers()
        self.send_header("Content-Length", str(len(data)))
        try:
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def _send_public_representation(self, representation, content_type, cache):
        body, encoding, etag = representation
        unchanged = etag in [tag.strip() for tag in self.headers.get("If-None-Match", "").split(",")]
        self.send_response(304 if unchanged else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache)
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("ETag", etag)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self._cors_headers()
        if not unchanged:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not unchanged and self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass

    def _send_media(self, path: Path, width: int, cache: str):
        payload, content_type, variant = read_with_thumbnail(path, width)
        if cache.startswith("public"):
            # Mutable paths must revalidate; unchanged derivatives return 304.
            # Private sources are authorized on every request, including hits.
            etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
            self._send_public_representation((payload, "", etag), content_type, "public, no-cache" if variant else cache)
        else:
            self._send_bytes(payload, content_type, cache="private, no-store")

    def _send_cached_json(
        self,
        obj: dict[str, Any],
        etag: str,
        cache_control: str = "public, max-age=300",
    ) -> None:
        clean_etag = etag.strip().strip('"').strip("'")
        inm = (self.headers.get("If-None-Match") or "").strip().strip('"').strip("'")
        if inm and clean_etag and inm == clean_etag:
            self.send_response(304)
            self.send_header("ETag", f'"{clean_etag}"')
            self.send_header("Cache-Control", cache_control)
            self._cors_headers()
            self.end_headers()
            return

        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache_control)
        self.send_header("ETag", f'"{clean_etag}"')
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        if getattr(self, "_body_consumed", False):
            return {}
        self._body_consumed = True
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ServiceError("Content-Length 无效", status=400, code="invalid_content_length") from exc
        # Skill embeds private images as Base64. Give only this authenticated
        # contract a bounded allowance for a few 15 MiB photos. The regular
        # website's 20 MiB JSON limit remains unchanged.
        target_path = unquote(urlparse(self.path).path)
        history_sync = self.command == "POST" and target_path == "/api/v1/me/generations"
        library_image_put = self.command == "PUT" and bool(
            re.fullmatch(r"/api/library/assets/[0-9a-fA-F-]{36}", target_path)
        )
        authenticated = self._current_user(required=False) if (history_sync or library_image_put) else None
        # 15 MiB binary becomes ~20 MiB as a Base64 data URL. Give only the
        # authenticated private library endpoint enough JSON headroom.
        body_limit = (
            64 * 1024 * 1024 if (history_sync and authenticated) else
            24 * 1024 * 1024 if (library_image_put and authenticated) else
            MAX_JSON_BODY_BYTES
        )
        if length > body_limit:
            raise ServiceError(
                "图片或请求数据过大；图库单图上限 15 MB" if library_image_put else
                "请求体过大；请缩小图片或分批上传",
                status=413, code="payload_too_large",
            )
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {"_list": parsed}
        except Exception as exc:
            raise ServiceError(f"JSON 请求体格式错误：{exc}", status=400) from exc

    def _current_user(self, required: bool = False) -> dict[str, Any] | None:
        if not hasattr(self, "_cached_auth_user"):
            hdr_dict = {k.lower(): v for k, v in self.headers.items()}
            self._cached_auth_user = authenticate_request(self.db, hdr_dict)
        user = self._cached_auth_user
        if required and not user:
            raise ServiceError("请先登录账号后再执行该操作", status=401, code="login_required")
        return user

    def _enforce_token_scope(self) -> None:
        user = self._current_user()
        if not user or user.get("_auth_kind") != "token":
            return

        parsed = urlparse(self.path)
        req_path = unquote(parsed.path)
        method = self.command.upper()
        scopes = set(user.get("_token_scopes") or [])

        # 1. Any valid token: GET /api/auth/me
        if method == "GET" and req_path == "/api/auth/me":
            return

        # 2. 'publish' scope: POST /api/uploads, POST /api/studio/uploads, POST /api/entries, POST /api/works
        if "publish" in scopes:
            if method == "POST" and req_path in (
                "/api/uploads",
                "/api/studio/uploads",
                "/api/entries",
                "/api/works",
            ):
                return

        # Skill v1 contract: only a library token can sync private data.
        if "library" in scopes:
            # Media access still checks ownership or an explicit public grant.
            if method == "GET" and req_path.startswith(("/uploads/", "/generated/")):
                return
            if method == "GET" and (
                req_path in (
                    "/api/v1/me/resources", "/api/v1/me/collection-items",
                    "/api/v1/me/generations", "/api/v1/me/notifications"
                )
                or re.fullmatch(r"^/api/v1/resources/[^/]+/download$", req_path)
                or re.fullmatch(r"^/api/v1/works/[^/]+/comments$", req_path)
            ):
                return
            if method == "PUT" and re.fullmatch(r"^/api/v1/me/resources/[^/]+$", req_path):
                return
            if method == "DELETE" and re.fullmatch(r"^/api/v1/me/resources/[^/]+$", req_path):
                return
        # Publishing scope covers the explicitly user-requested social writes.
        if "publish" in scopes and method == "POST" and (
            req_path == "/api/v1/me/generations"
            or re.fullmatch(r"^/api/v1/works/[^/]+/(likes|comments)$", req_path)
        ):
            return

        # 3. 'library' scope: personal library read endpoints and collection toggle
        if "library" in scopes:
            if method == "GET":
                if req_path.startswith("/api/resources/"):
                    return
                if req_path in ("/studio/api/library", "/api/skill/library", "/api/library/assets", "/api/collections/generations"):
                    return
                if re.fullmatch(r"^/(?:studio/api|api/skill)/assets/[^/]+/content$", req_path):
                    return
                if re.fullmatch(r"^/api/library/assets/[^/]+/image$", req_path):
                    return
            elif method == "POST":
                if req_path == "/api/collections/toggle":
                    return
                if re.fullmatch(r"^/api/library/assets/[^/]+/restore$", req_path):
                    return
            elif method == "PUT":
                if re.fullmatch(r"^/api/library/assets/[^/]+$", req_path):
                    return
            elif method == "DELETE":
                if re.fullmatch(r"^/api/library/assets/[^/]+$", req_path):
                    return

        raise ServiceError("token_scope_denied", status=403, code="token_scope_denied")

    def _cookie_for_token(self, token: str, clear: bool = False) -> str:
        host = self.headers.get("Host") or "localhost"
        is_https = (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        return build_session_cookie(
            SESSION_COOKIE_NAME,
            "" if clear else token,
            host=host,
            max_age=0 if clear else SESSION_TTL_SECONDS,
            secure=is_https,
        )

    def do_OPTIONS(self) -> None:
        self._dispatch_request(self._handle_options, enforce_scope=False)

    def _handle_options(self) -> None:
        origin = self.headers.get("Origin") or ""
        if origin and not origin_allowed(origin):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_DELETE(self) -> None:
        self._dispatch_request(self._handle_delete)

    def _handle_delete(self) -> None:
        self._enforce_write_origin()
        parsed = urlparse(self.path)
        req_path = unquote(parsed.path)
        from .skill_web_bridge import handle_delete as skill_web_delete
        if skill_web_delete(self, req_path, parse_qs(parsed.query, keep_blank_values=True)):
            return
        m_wf = re.match(r"^/api/studio/workflows/([^/]+)$", req_path)
        if m_wf:
            user = self._current_user(required=True)
            res = delete_user_studio_workflow(self.db, user, m_wf.group(1))  # type: ignore[arg-type]
            self._send_json(res)
            return
        m_art = re.match(r"^/api/studio/articles/([^/]+)$", req_path)
        if m_art:
            user = self._current_user(required=True)
            res = delete_user_studio_article(self.db, user, m_art.group(1))  # type: ignore[arg-type]
            self._send_json(res)
            return
        if req_path.startswith("/api/library/assets/"):
            from .user_library import handle_library_delete
            qs = parse_qs(parsed.query, keep_blank_values=True)
            if handle_library_delete(self, req_path, qs):
                return
        try:
            from .messaging import handle_dm_delete
        except ImportError:  # pragma: no cover
            handle_dm_delete = None
        if handle_dm_delete and handle_dm_delete(self, req_path, parse_qs(parsed.query, keep_blank_values=True)):
            return
        self._send_json({"ok": False, "error": "Not found"}, status=404)

    def do_GET(self) -> None:
        self._dispatch_request(self._handle_get)

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        from .application_errors import canonical_local_page
        if canonical_local_page(self, parsed):
            return
        req_path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        raw_host = self.headers.get("Host") or "localhost:3080"
        host = raw_host.split(":")[0].lower()
        proto = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip().lower()
        origin = f"{proto}://{raw_host}"
        srv_role = getattr(self.server, "channel_role", "main")
        is_admin_channel = host.startswith("admin.") or srv_role == "admin"

        def q1(key: str, default: str = "") -> str:
            vals = qs.get(key)
            return vals[0].strip() if vals and vals[0] else default

        # Legacy asset detail link 302 redirects to /t/<id>
        if req_path in ("/", "", "/main", "/main/", "/index.html", "/main/index.html"):
            is_legacy_asset = (q1("view") == "asset") or bool(q1("asset"))
            legacy_code = (q1("id") if q1("view") == "asset" else "") or q1("asset")
            if is_legacy_asset and legacy_code:
                clean_code = legacy_code.strip().upper().lstrip("#")
                extra_params = {}
                tab_val = q1("tab")
                focus_val = q1("focus")
                panel_val = q1("panel")
                if tab_val in ("topics", "works"):
                    conn = self.db.get_conn()
                    from .resource_discussions import resolve_resource
                    kind = "style" if resolve_resource(conn, "style", clean_code) else ("layout" if resolve_resource(conn, "layout", clean_code) else "asset")
                    dest = f"/forum/?view=related&kind={kind}&id={urllib.parse.quote(clean_code)}&tab={tab_val}"
                    if panel_val == "report":
                        dest += "&panel=report"
                else:
                    if focus_val == "comment" or tab_val == "comments":
                        extra_params["focus"] = "comment"
                    if panel_val == "report" or tab_val == "report":
                        extra_params["panel"] = "report"
                    qs_part = f"?{urllib.parse.urlencode(extra_params)}" if extra_params else ""
                    dest = f"/t/{urllib.parse.quote(clean_code)}{qs_part}"
                self.send_response(302)
                self.send_header("Location", dest)
                self._cors_headers()
                self.end_headers()
                return

        # Optional feature modules load lazily and degrade to "no route" when a
        # partial checkout omits them, so the rest of the server still boots.
        try:
            from .curation_routes import handle_get as curation_get
        except ImportError:  # pragma: no cover - partial checkout
            curation_get = None
        try:
            from .forum_resource_routes import handle_get as resource_get
        except ImportError:  # pragma: no cover - partial checkout
            resource_get = None
        try:
            from .post_routes import handle_get as post_get
        except ImportError:  # pragma: no cover - partial checkout
            post_get = None
        if post_get and post_get(self, req_path, qs):
            return
        if resource_get and resource_get(self, req_path, qs):
            return
        if curation_get and curation_get(self, req_path, qs):
            return
        if self._feature_get(req_path, qs):
            return

        try:
            from .messaging import handle_dm_get
        except ImportError:  # pragma: no cover
            handle_dm_get = None
        if handle_dm_get and handle_dm_get(self, req_path, qs):
            return

        try:
            from .device_auth_routes import handle_get as device_auth_get
        except ImportError:  # pragma: no cover
            device_auth_get = None
        if device_auth_get and device_auth_get(self, req_path, qs):
            return

        from .skill_web_bridge import handle_get as skill_web_get
        if skill_web_get(self, req_path, qs):
            return

        try:
            from .user_library import handle_library_get
        except ImportError:  # pragma: no cover
            handle_library_get = None
        if handle_library_get and handle_library_get(self, req_path, qs):
            return

        if req_path == "/robots.txt":
            self._send_bytes(build_robots_txt(origin, is_admin=is_admin_channel), "text/plain; charset=utf-8", cache="public, max-age=3600")
            return

        if req_path == "/sitemap.xml":
            self._send_bytes(build_sitemap_xml(self.db, origin), "application/xml; charset=utf-8", cache="public, max-age=600")
            return

        if req_path == "/favicon.ico":
            svg = (
                b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                b'<rect width="32" height="32" rx="7" fill="#b74227"/>'
                b'<text x="16" y="22" text-anchor="middle" font-size="18" font-weight="900" fill="#fffdf9">H</text>'
                b"</svg>"
            )
            self._send_bytes(svg, "image/svg+xml", cache="public, max-age=86400")
            return

        if req_path == "/api/health":
            self._send_json({"ok": True, "version": "2.0.0", "db": True})
            return

        # Single Resource Detail (/api/resources/<code>)
        if req_path.startswith("/api/resources/"):
            code = unquote(req_path[len("/api/resources/"):].strip())
            from . import resource_registry
            user = self._current_user(required=False)
            res = resource_registry.resolve(self.db.get_conn(), code, viewer=user, purpose="view")
            if not res:
                self._send_json({"ok": False, "error": f"资源不存在：{code}", "code": "resource_not_found"}, status=404)
                return
            client_dict = resource_registry.to_client_dict(res)
            resp = {"ok": True, "resource": client_dict, **client_dict}
            self._send_json(resp)
            return

        # Core Boot & Public Counts
        if req_path == "/api/boot":
            user = self._current_user(required=False)
            if user and user.get("status") == "active":
                from .p2_growth import record_visit
                record_visit(self.db, user)
            self._send_json(build_boot_payload(self.db, user, surface="studio" if q1("surface") == "studio" else "full"))
            return

        # Public Works Feed & Detail
        if req_path in ("/api/works/feed", "/api/works/feed/", "/api/works", "/api/works/"):
            from .works_feed import get_works_feed
            user = self._current_user(required=False)
            feed_params = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
            self._send_json(get_works_feed(self.db, feed_params, current_user=user))
            return

        m_work_detail = re.match(r"^/api/works/([^/]+)/?$", req_path)
        if m_work_detail:
            from .works_feed import get_work_by_id
            wid = m_work_detail.group(1)
            if wid not in ("feed",):
                user = self._current_user(required=False)
                work = get_work_by_id(self.db, wid, current_user=user)
                if not work:
                    raise ServiceError("作品不存在或未公开", status=404, code="work_not_found")
                self._send_json({"ok": True, "work": work})
                return

        if req_path == "/api/public/asset-counts":
            counts, total_works, total_cheers, creators = compute_public_asset_counts_and_creators(self.db.get_conn())
            self._send_json(
                {
                    "counts": counts,
                    "assetCounts": counts,
                    "totalWorksCount": total_works,
                    "totalCheersCount": total_cheers,
                    "publicCreators": creators,
                }
            )
            return

        if req_path == "/api/public/home-scenarios":
            from .home_scenarios import get_public_home_scenarios
            payload, etag = get_public_home_scenarios(self.db)
            self._send_cached_json(payload, etag=etag, cache_control="public, no-cache")
            return

        if req_path == "/__demo_state":
            self._require_demo_mode()
            with _LEGACY_DEMO_STATE_LOCK:
                snap = dict(_LEGACY_DEMO_STATE)
            if "assetCounts" not in snap:
                counts, _, _, _ = compute_public_asset_counts_and_creators(self.db.get_conn())
                snap["assetCounts"] = counts
            self._send_json(snap)
            return

        if req_path == "/api/billing/plans":
            from .billing import get_billing_public_state
            self._send_json({"ok": True, **get_billing_public_state()})
            return

        if req_path == "/api/billing/orders":
            user = self._current_user(required=True)
            from .billing import list_user_payment_orders
            self._send_json(list_user_payment_orders(self.db, int(user["id"]), limit=int(q1("limit") or 20)))  # type: ignore[index]
            return

        checkout_match = re.fullmatch(r"/api/billing/orders/([^/]+)", req_path)
        if checkout_match:
            from .billing import get_checkout_order
            self._send_json(get_checkout_order(self.db, self._current_user(required=True), checkout_match.group(1)))
            return

        # Studio Config, Workspace & Task Polling
        if req_path == "/api/studio/config":
            cfg = load_image_service_config()
            settings = get_site_settings(self.db.get_conn())
            econ = settings.get("economy", {})
            self._send_json(
                {
                    "liveImageEnabled": bool(cfg),
                    "realImageGeneration": bool(cfg),
                    "demoMode": self._demo_enabled(),
                    "rechargeEnabled": recharge_enabled(),
                    "trustedOrigins": sorted(trusted_origins()),
                    "model": resolve_gateway_model(settings, cfg),
                    "billingMode":"cash",
                    "specifications": __import__("backend.economy",fromlist=["specs"]).specs(self.db.get_conn()),
                }
            )
            return

        if req_path == "/api/studio/workspace":
            if q1("bootstrap")=="1":
                from .studio_workspace import bootstrap_workspace
                self._send_json(bootstrap_workspace(self.db,self._current_user(required=False)))
                return
            user = self._current_user(required=False)
            collection=q1("collection")
            if collection and collection not in ("history","workflows","uploads"):
                raise ServiceError("工作区集合无效",status=400,code="invalid_collection")
            self._send_json(get_studio_workspace(self.db, user,collection=collection or None,history_cursor=q1("cursor") or ""))
            return

        if req_path == "/api/studio/canvases":
            user = self._current_user(required=True)
            from .studio_paging import page_canvases
            self._send_json(page_canvases(self.db,user,cursor=q1("cursor") or ""))
            return

        canvas_runs = re.fullmatch(r"/api/studio/canvases/([^/]+)/runs",req_path)
        if canvas_runs:
            from .canvas_runs import list_canvas_runs
            self._send_json(list_canvas_runs(self.db,self._current_user(required=True),canvas_runs.group(1),cursor=q1("cursor") or ""))
            return
        canvas_run = re.fullmatch(r"/api/studio/canvas-runs/([^/]+)",req_path)
        if canvas_run:
            from .canvas_runs import get_canvas_run
            self._send_json(get_canvas_run(self.db,self._current_user(required=True),canvas_run.group(1)))
            return
        canvas_detail = re.fullmatch(r"/api/studio/canvases/([^/]+)", req_path)
        if canvas_detail:
            from .studio_canvases import get_canvas
            self._send_json(get_canvas(self.db,self._current_user(required=True),canvas_detail.group(1)))
            return

        if req_path == "/api/studio/articles":
            user = self._current_user(required=True)
            if q1("page")=="1":
                from .studio_workspace import page_articles
                self._send_json(page_articles(self.db,user,cursor=q1("cursor") or ""))
                return
            self._send_json(list_user_studio_articles(self.db, user))  # type: ignore[arg-type]
            return

        article_detail = re.fullmatch(r"/api/studio/articles/([^/]+)", req_path)
        if article_detail:
            from .studio_articles import get_article
            user = self._current_user(required=True)
            self._send_json(get_article(self.db, user, article_detail.group(1)))
            return

        if req_path == "/api/studio/history" or req_path.startswith("/api/studio/history/"):
            hid = ""
            if req_path.startswith("/api/studio/history/"):
                hid = req_path[len("/api/studio/history/"):].strip()
            if not hid:
                hid = q1("id") or ""
            if hid:
                entry = get_public_generation_history(self.db, history_id=hid)
                if not entry:
                    self._send_json({"ok": False, "error": "历史记录不存在"}, status=404)
                    return
                self._send_json({"ok": True, "history": entry})
                return
            lim = 40
            try:
                if q1("limit"):
                    lim = int(q1("limit"))
            except Exception:
                pass
            rows = get_public_generation_history(self.db, limit=lim)
            self._send_json({"ok": True, "history": rows})
            return

        if req_path.startswith("/api/users/"):
            parts = [p for p in req_path.split("/") if p]
            if len(parts) >= 4 and parts[0] == "api" and parts[1] == "users" and parts[3] == "generations":
                uname = unquote(parts[2]).strip()
                user = self._current_user(required=False)
                if len(parts) == 4:
                    cur = q1("cursor") or ""
                    lim = 24
                    try:
                        if q1("limit"):
                            lim = int(q1("limit"))
                    except (ValueError, TypeError):
                        lim = 24
                    data = get_user_public_generations(self.db, uname, cursor=cur, limit=lim, viewer=user)
                    self._send_json(data)
                    return
                elif len(parts) == 5:
                    gen_id = unquote(parts[4]).strip()
                    data = get_user_public_generation_by_id(self.db, uname, gen_id, viewer=user)
                    self._send_json(data)
                    return

        if req_path == "/api/collections/generations":
            user = self._current_user(required=True)
            lim = 60
            try:
                if q1("limit"):
                    lim = int(q1("limit"))
            except Exception:
                pass
            self._send_json(get_user_collected_generations(self.db, user, limit=lim))
            return

        if req_path.startswith("/api/studio/recipes"):
            from .recipe_routes import handle_recipe_get
            if handle_recipe_get(self, req_path, qs):
                return

        m_import = re.match(r"^/api/studio/imports/([^/]+)$", req_path)
        if m_import:
            user = self._current_user(required=True)
            import_id = m_import.group(1)
            with self.db.transaction() as tx:
                job = tx.execute(
                    "SELECT * FROM studio_import_jobs WHERE id = ?",
                    (import_id,),
                ).fetchone()
            if not job or int(job["user_id"]) != int(user["id"]):
                raise ServiceError("导入任务不存在", status=404, code="not_found")

            res_payload = json.loads(job["result_json"]) if job["result_json"] else None
            # Stage derives from persisted facts, never an invented timer percentage.
            job_status = str(job["status"])
            total = int(job["progress_total"] or 0)
            done = int(job["progress_done"] or 0)
            stage = (
                "queued" if job_status == "queued"
                else "completed" if job_status == "done"
                else "failed" if job_status == "failed"
                else "extracting" if total == 0
                else "validating" if done >= total
                else "structuring"
            )
            self._send_json({
                "ok": True,
                "status": job_status,
                "stage": stage,
                "progress": {"done": done, "total": total},
                "error": job["error"],
                "result": res_payload,
            })
            return

        if req_path == "/api/studio/tasks":
            user = self._current_user(required=True)
            task_id = q1("id") or q1("taskId")
            request_id = q1("requestId")
            if not task_id and not request_id:
                self._send_json({"error": "missing id or requestId"}, status=400)
                return
            task_ref = get_user_studio_task(self.db, user, task_id=task_id, request_id=request_id)
            if not task_ref:
                self._send_json({"error": "task not found"}, status=404)
                return
            rec_status = str(task_ref.get("status") or "").lower()
            if rec_status in ("refunded", "success", "failed", "error", "cancelled", "canceled"):
                self._send_json(task_ref)
                return
            # A request may be found by idempotency key before the upstream
            # task id exists.  Return the durable reservation state without
            # querying the gateway as another user or as an anonymous caller.
            if not task_id:
                self._send_json(task_ref)
                return
            gen_id = str(task_ref.get("genId") or "")
            if not gen_id:
                self._send_json({"error": "task not found"}, status=404)
                return
            if _get_generation_gateway_protocol(self.db, gen_id) == "openai":
                self._send_json({"status": rec_status or "running", "images": []})
                return
            try:
                self.db.release_request_connection()
                res = gateway_request(f"/api/image-tasks?ids={urllib.parse.quote(task_id)}")
                items = res.get("items") or []
                if not items:
                    self._send_json({"status": "queued", "images": []})
                    return
                item = items[0]
                status = item.get("status") or "running"
                local_urls: list[str] = []
                if status in ("success", "succeeded", "completed", "done"):
                    for idx, d in enumerate(item.get("data") or []):
                        r_url = d.get("url") if isinstance(d, dict) else None
                        if r_url:
                            try:
                                local_urls.append(download_and_cache_generated_image(r_url, f"{task_id}_{idx}"))
                            except Exception:
                                # Do not leak a gateway/signed URL when local
                                # private storage could not be populated.
                                continue
                    complete_cloud_generation(self.db, gen_id, task_id, local_urls)
                elif status in ("failed", "error", "cancelled", "canceled"):
                    refund_failed_cloud_generation(self.db, gen_id, f"云端任务失败 ({status})")
                self._send_json(
                    {
                        "status": status,
                        "images": local_urls,
                        "message": f"任务执行未成功 ({status})" if status in ("failed", "error", "cancelled", "canceled") else "",
                    }
                )
            except Exception as exc:
                logger.warning("Gateway task polling failed: %s", type(exc).__name__, exc_info=True)
                self._send_json({"status": "error", "message": "云端任务轮询异常"}, status=502)
            return

        # Skill-Addon Personal Library Compatibility
        if req_path in ("/studio/api/library", "/api/skill/library"):
            user = self._current_user(required=True)
            self._send_json(build_skill_library_payload(self.db, user))  # type: ignore[arg-type]
            return

        m_skill_asset = re.match(r"^/(?:studio/api|api/skill)/assets/([^/]+)/content$", req_path)
        if m_skill_asset:
            user = self._current_user(required=True)
            self._send_json(build_skill_asset_content(self.db, user, m_skill_asset.group(1)))  # type: ignore[arg-type]
            return

        # Admin Management GET Endpoints
        if req_path == "/api/admin/permissions":
            user = self._current_user(required=True)
            self._send_json(admin_get_permissions(self.db, user))
            return

        if req_path == "/api/admin/moderator-overview":
            user = self._current_user(required=True)
            self._send_json(admin_get_moderator_console(self.db, user, board_filter=q1("board"), query=q1("q")))
            return

        if req_path == "/api/admin/dashboard":
            user = self._current_user(required=True)
            self._send_json(admin_get_dashboard(self.db, user))
            return

        if req_path == "/api/admin/works":
            user = self._current_user(required=True)
            self._send_json(admin_list_works(self.db, user, status=q1("status"), query=q1("q")))
            return

        if req_path == "/api/admin/comments":
            user = self._current_user(required=True)
            self._send_json(admin_list_comments(self.db, user, status=q1("status"), query=q1("q")))
            return

        if req_path == "/api/admin/catalog":
            user = self._current_user(required=True)
            self._send_json(
                admin_list_catalog_assets(
                    self.db,
                    user,
                    kind=q1("kind"),
                    source_type=q1("sourceType"),
                    status=q1("status"),
                    query=q1("q"),
                )
            )
            return

        if req_path == "/api/admin/presets":
            user = self._current_user(required=True)
            self._send_json(admin_list_presets(self.db, user))
            return

        if req_path == "/api/forum/boards":
            from .forum_boards import list_boards
            self._send_json({"ok": True, "items": list_boards(self.db.get_conn(), self._current_user(required=False))})
            return

        if req_path == "/api/admin/forum-boards":
            from .forum_boards import admin_list
            self._send_json(admin_list(self.db, self._current_user(required=True)))
            return

        if req_path == "/api/admin/topics":
            user = self._current_user(required=True)
            self._send_json(
                admin_list_topics(
                    self.db,
                    user,
                    status=q1("status"),
                    bounty_only=(q1("bountyOnly") in ("1", "true")),
                    query=q1("q"),
                )
            )
            return

        if req_path == "/api/admin/reports":
            user = self._current_user(required=True)
            self._send_json(admin_list_reports(self.db, user, status=q1("status")))
            return

        if req_path == "/api/admin/forum-moderators":
            user = self._current_user(required=True)
            self._send_json(admin_list_forum_moderators(self.db, user))
            return

        if req_path == "/api/admin/users":
            user = self._current_user(required=True)
            self._send_json(admin_list_users(self.db, user, role=q1("role"), status=q1("status"), query=q1("q")))
            return

        m_admin_user = re.match(r"^/api/admin/users/(\d+)$", req_path)
        if m_admin_user:
            user = self._current_user(required=True)
            self._send_json(admin_get_user_detail(self.db, user, int(m_admin_user.group(1))))
            return

        if req_path == "/api/admin/unlocks":
            user = self._current_user(required=True)
            self._send_json(admin_list_unlocks(self.db, user, status=q1("status")))
            return

        if req_path == "/api/admin/redeem-codes":
            user = self._current_user(required=True)
            self._send_json(admin_list_redeem_codes(self.db, user))
            return

        if req_path == "/api/admin/gateway":
            user = self._current_user(required=True)
            self._send_json(
                admin_get_gateway_overview(
                    self.db,
                    user,
                    probe=(q1("probe") in ("1", "true")),
                    probe_ai=(q1("probeAi") in ("1", "true")),
                )
            )
            return

        if req_path == "/api/admin/generations":
            user = self._current_user(required=True)
            self._send_json(admin_list_generations(self.db, user, status=q1("status"), engine=q1("engine"), query=q1("q")))
            return

        if req_path == "/api/admin/settings":
            user = self._current_user(required=True)
            self._send_json(admin_get_settings(self.db, user))
            return

        if req_path == "/api/admin/home-scenarios":
            from .home_scenarios import admin_list_home_scenarios
            user = self._current_user(required=True)
            self._send_json(admin_list_home_scenarios(self.db, user))
            return

        if req_path == "/api/admin/audit-logs":
            user = self._current_user(required=True)
            self._send_json(
                admin_list_audit_logs(
                    self.db,
                    user,
                    action_filter=q1("action"),
                    actor_filter=q1("actor"),
                    target_type=q1("targetType"),
                )
            )
            return

        if req_path == "/api/front/user-manage":
            user = require_staff(self._current_user(required=True), allow_reviewer=True)
            target_uname = str(q1("username") or "").strip()
            if not target_uname:
                raise ServiceError("缺少目标用户名 username")
            conn = self.db.get_conn()
            row = conn.execute(
                "SELECT id, username, display_name, email, role, status, honor_override, bio, created_at, wallet_locked FROM users WHERE username = ?",
                (target_uname,),
            ).fetchone()
            if not row:
                raise ServiceError(f"未找到目标创作者：{target_uname}", status=404)
            tid = int(row["id"])
            w_row = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (tid,)).fetchone()
            q_state = get_wallet_quota_state(conn, tid)
            mods = [
                {"category": mr["category"], "title": mr["title"]}
                for mr in conn.execute("SELECT category, title FROM forum_moderators WHERE user_id = ?", (tid,)).fetchall()
            ]
            self._send_json(
                {
                    "ok": True,
                    "targetUser": {
                        "id": tid,
                        "username": row["username"],
                        "displayName": row["display_name"],
                        "email": row["email"] or "",
                        "role": row["role"],
                        "status": row["status"],
                        "honorOverride": row["honor_override"],
                        "bio": row["bio"] or "",
                        "walletLocked": bool(row["wallet_locked"]),
                        "balance": int(w_row["balance"] if w_row else 0),
                        "freeQuotaRemaining": q_state["freeQuotaRemaining"],
                        "freeQuotaMax": q_state["freeQuotaMax"],
                        "moderatedBoards": mods,
                    },
                }
            )
            return

        # Static Data JSON & Media Serving
        if req_path == "/data/catalog.json":
            from .static_assets import data_representation
            self._send_public_representation(data_representation(load_localized_json("catalog.json"), self.headers.get("Accept-Encoding", "")), "application/json; charset=utf-8", "public, max-age=300")
            return

        if req_path == "/data/options.json":
            from .static_assets import data_representation
            self._send_public_representation(data_representation(load_localized_json("studio-options.json"), self.headers.get("Accept-Encoding", "")), "application/json; charset=utf-8", "public, max-age=300")
            return

        if req_path == "/data/benchmark-assets.json":
            user = self._current_user(required=False)
            self._send_bytes(load_benchmark_assets_json(self.db, user), "application/json; charset=utf-8", cache="no-store")
            return

        if req_path.startswith("/avatars/"):
            from .avatar_identity import avatar_file_for_path
            path = avatar_file_for_path(req_path)
            if path is None:
                self.send_error(404, "Avatar not found")
                return
            if not path.is_file():
                try:
                    from .object_storage import ensure_local_copy
                    ensure_local_copy(req_path, path)
                except Exception:
                    logger.exception("Avatar object storage read failed")
                    self.send_error(503, "Avatar temporarily unavailable")
                    return
            if path.is_file():
                self._send_media(path, normalize_thumb_width(q1("w")), "public, max-age=31536000, immutable")
            else:
                self.send_error(404, "Avatar not found")
            return

        for prefix, root_dir in (
            ("/generated/", get_generated_dir()),
            ("/uploads/", get_uploads_dir()),
            ("/images/", DEFAULT_STYLE_IMAGES_DIR),
        ):
            if req_path.startswith(prefix):
                rel = req_path.removeprefix(prefix).lstrip("/")
                if prefix == "/images/" and rel.lower().startswith("custom/") and not include_private_benchmark_assets():
                    self.send_error(404, "Media not found")
                    return
                if root_dir.exists() or prefix in ("/generated/", "/uploads/"):
                    # Authorize before any object-storage read-through; S3 keys
                    # are never accessible merely because a URL was guessed.
                    target = (root_dir / rel).resolve()
                    if _path_is_within(target, root_dir):
                        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                        if prefix == "/images/":
                            cache_policy = "public, max-age=86400"
                        else:
                            media_user = self._current_user(required=False)
                            allowed, cache_policy = _private_media_access(self.db, f"{prefix}{rel}", media_user)
                            if not allowed:
                                self.send_error(404, "Media not found")
                                return
                            if not target.is_file():
                                from .object_storage import ensure_local_copy
                                try:
                                    if not ensure_local_copy(f"{prefix}{rel}", target):
                                        self.send_error(404, "Media not found")
                                        return
                                except Exception:
                                    logger.exception("object_storage read-through failed for authorized media")
                                    self.send_error(503, "Media temporarily unavailable")
                                    return
                        if not target.is_file():
                            self.send_error(404, "Media not found")
                            return
                        self._send_media(target, normalize_thumb_width(q1("w")), cache_policy)
                        return
                self.send_error(404, "Media not found")
                return

        # One listener serves all frontends. Production chooses by Host; local
        # development also has explicit paths on the same origin.
        is_studio_channel = host.startswith("studio.") or srv_role == "studio"
        is_forum_channel = host.startswith("forum.") or host.startswith("bbs.") or srv_role == "forum"

        # An unmatched API path must not fall through to the SPA shell: a client
        # would receive 200 + index.html and treat a missing endpoint as success.
        # "/api" itself and other casings are API paths too, not pages.
        api_path = req_path.lower()
        if api_path == "/api" or api_path.startswith("/api/"):
            self._send_json(
                {"ok": False, "error": "接口不存在", "code": "not_found"}, status=404
            )
            return

        if req_path in ("/", ""):
            if is_admin_channel:
                file_path = DEMO_DIR / "admin.html"
            elif is_studio_channel:
                file_path = DEMO_DIR / "studio.html"
            elif is_forum_channel:
                file_path = DEMO_DIR / "forum.html"
            else:
                file_path = DEMO_DIR / "index.html"
        elif req_path in ("/admin", "/admin/"):
            file_path = DEMO_DIR / "admin.html"
        elif req_path in ("/studio", "/studio/"):
            file_path = DEMO_DIR / "studio.html"
        elif req_path in ("/checkout", "/checkout/"):
            file_path = DEMO_DIR / "checkout.html"
        elif req_path in ("/forum", "/forum/"):
            file_path = DEMO_DIR / "forum.html"
        else:
            clean_rel = req_path.lstrip("/")
            file_path = (DEMO_DIR / clean_rel).resolve()
            if not _path_is_within(file_path, DEMO_DIR):
                self.send_error(403, "Forbidden")
                return
            if not file_path.is_file():
                if "." not in Path(clean_rel).name:
                    if is_admin_channel:
                        file_path = DEMO_DIR / "admin.html"
                    elif is_studio_channel:
                        file_path = DEMO_DIR / "studio.html"
                    elif is_forum_channel:
                        file_path = DEMO_DIR / "forum.html"
                    else:
                        file_path = DEMO_DIR / "index.html"
                else:
                    self.send_error(404, "Not found")
                    return

        if file_path == DEMO_DIR / "index.html":
            from .static_assets import version_frontend_html
            raw_tpl = file_path.read_text(encoding="utf-8")
            self._send_bytes(version_frontend_html(render_seo_portal_html(self.db, raw_tpl, origin, qs), DEMO_DIR), "text/html; charset=utf-8", cache="no-cache")
            return

        ctype = mimetypes.guess_type(str(file_path))[0] or "text/html"
        if ctype.startswith("text/") or ctype in ("application/javascript", "text/javascript"):
            ctype += "; charset=utf-8"
        if req_path.startswith("/assets/") and file_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            self._send_media(file_path, normalize_thumb_width(q1("w")), "public, max-age=3600")
            return
        # Only public frontend code uses this cache. Private media and API
        # responses keep their own authorization and no-store policies.
        if req_path.startswith("/assets/") and file_path.suffix in (".js", ".css", ".svg"):
            from .static_assets import file_representation
            self._send_public_representation(file_representation(file_path, self.headers.get("Accept-Encoding", "")), ctype, "public, max-age=3600" if q1("v") else "public, no-cache")
            return
        payload = file_path.read_bytes()
        if file_path.suffix.lower() == ".html":
            from .static_assets import version_frontend_html
            payload = version_frontend_html(payload, DEMO_DIR)
        self._send_bytes(payload, ctype, cache="no-cache")

    def do_POST(self) -> None:
        self._dispatch_request(self._handle_post)

    def do_PUT(self) -> None:
        self._dispatch_request(self._handle_put)

    def _handle_put(self) -> None:
        self._enforce_write_origin()
        parsed = urlparse(self.path)
        req_path = unquote(parsed.path)
        if req_path.startswith("/api/v1/me/resources/"):
            from .skill_web_bridge import handle_put as skill_web_put
            if skill_web_put(self, req_path, self._read_json_body()):
                return
        if req_path.startswith("/api/studio/recipes"):
            from .recipe_routes import handle_recipe_put
            body = self._read_json_body()
            if handle_recipe_put(self, req_path, body):
                return
        if req_path.startswith("/api/library/assets/"):
            from .user_library import handle_library_put
            body = self._read_json_body()
            if handle_library_put(self, req_path, body):
                return
        self._send_json({"ok": False, "error": "Not Found"}, status=404)

    def _handle_post(self) -> None:
        parsed = urlparse(self.path)
        req_path = unquote(parsed.path)
        if req_path == "/api/webhooks/xorpay":
            self._body_consumed = True
            from .billing import MAX_WEBHOOK_BYTES, process_xorpay_webhook
            try:
                hook_size = int(self.headers.get("Content-Length") or "0")
            except ValueError as exc:
                raise ServiceError("Content-Length 无效", status=400, code="invalid_content_length") from exc
            if hook_size <= 0:
                raise ServiceError("Webhook 请求体为空", status=400, code="empty_webhook_body")
            if hook_size > MAX_WEBHOOK_BYTES:
                raise ServiceError("Webhook 请求体过大", status=413, code="webhook_payload_too_large")
            raw_hook_body = self.rfile.read(hook_size)
            result = process_xorpay_webhook(self.db, raw_hook_body)
            resp_text = str(result.get("response_body") or "ok")
            self._send_bytes(resp_text.encode("utf-8"), "text/plain; charset=utf-8")
            return
        if req_path == "/api/webhooks/creem":
            self._body_consumed = True
            from .billing import MAX_WEBHOOK_BYTES, process_creem_webhook
            try:
                hook_size = int(self.headers.get("Content-Length") or "0")
            except ValueError as exc:
                raise ServiceError("Content-Length 无效", status=400, code="invalid_content_length") from exc
            if hook_size <= 0:
                raise ServiceError("Webhook 请求体为空", status=400, code="empty_webhook_body")
            if hook_size > MAX_WEBHOOK_BYTES:
                raise ServiceError("Webhook 请求体过大", status=413, code="webhook_payload_too_large")
            raw_hook_body = self.rfile.read(hook_size)
            self._send_json(
                process_creem_webhook(
                    self.db,
                    raw_hook_body,
                    self.headers.get("creem-signature") or self.headers.get("X-Creem-Signature") or "",
                )
            )
            return
        self._enforce_write_origin()
        if req_path == "/api/client-errors":
            self._enforce_auth_rate_limit("client_error", "", per_ip_only=True)
            try:
                report_size = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                raise ServiceError("Content-Length 无效", status=400, code="invalid_content_length")
            if report_size > 4096:
                raise ServiceError("错误报告过大", status=413, code="client_error_too_large")
            from .application_errors import record_client_error
            record_client_error(self, self._read_json_body())
            return
        body = self._read_json_body()
        if req_path.startswith("/api/v1/"):
            from .skill_web_bridge import handle_post as skill_web_post
            if skill_web_post(self, req_path, body):
                return
        ua = self.headers.get("User-Agent") or ""
        ip_addr = self.client_address[0] if self.client_address else ""

        if req_path == "/__demo_state":
            self._require_demo_mode()
            with _LEGACY_DEMO_STATE_LOCK:
                _LEGACY_DEMO_STATE.clear()
                _LEGACY_DEMO_STATE.update(body)
            self._send_json({"ok": True})
            return

        if req_path == "/api/auth/forgot-password":
            self._enforce_auth_rate_limit("reset", str(body.get("email") or ""))
        elif req_path == "/api/auth/reset-password":
            self._enforce_auth_rate_limit("reset", str(body.get("token") or "")[:80])
        elif req_path == "/api/auth/send-verification":
            self._enforce_auth_rate_limit("verification", str(self.headers.get("Cookie") or ""))
        elif req_path == "/api/auth/verify-email":
            self._enforce_auth_rate_limit("verification", str(body.get("token") or "")[:80])

        if re.fullmatch(r"/api/content/(works|topics)/[^/]+/edit", req_path):
            edit_user = self._current_user(required=True)
            body = validate_publish_media(self.db, edit_user, sanitize_submission_body(body))  # type: ignore[arg-type]

        try:
            from .curation_routes import handle_post as curation_post
        except ImportError:  # pragma: no cover - partial checkout
            curation_post = None
        try:
            from .forum_resource_routes import handle_post as resource_post
        except ImportError:  # pragma: no cover - partial checkout
            resource_post = None
        if resource_post and resource_post(self, req_path, body):
            return
        if curation_post and curation_post(self, req_path, body):
            return
        if self._feature_post(req_path, body):
            return

        try:
            from .messaging import handle_dm_post
        except ImportError:  # pragma: no cover
            handle_dm_post = None
        if handle_dm_post and handle_dm_post(self, req_path, body):
            return

        try:
            from .device_auth_routes import handle_post as device_auth_post
        except ImportError:  # pragma: no cover
            device_auth_post = None
        if device_auth_post and device_auth_post(self, req_path, body):
            return

        try:
            from .user_library import handle_library_post
        except ImportError:  # pragma: no cover
            handle_library_post = None
        if handle_library_post and handle_library_post(self, req_path, body):
            return

        # Auth & Session Endpoints
        if req_path == "/api/auth/register":
            # Registration is limited per IP only.  Keying by IP+username let a
            # caller pick a fresh username each time and bypass the limit, which
            # made invite farming unlimited.
            self._enforce_auth_rate_limit("register", "", per_ip_only=True)
            with self.db.transaction() as tx:
                tx.execute("INSERT INTO auth_funnel_events(event_name,created_at,source) VALUES(?,?,?)",
                           ("register_attempt", int(time.time()), "web"))
            user_row, token = register_user(
                self.db,
                username=str(body.get("username") or ""),
                password=str(body.get("password") or ""),
                email=str(body.get("email") or ""),
                display_name=str(body.get("displayName") or ""),
                invite_code=str(body.get("inviteCode") or ""),
                user_agent=ua,
                ip_addr=ip_addr,
            )
            from .p2_growth import record_login
            record_login(self.db, user_row, ua)
            boot = build_boot_payload(self.db, user_row)
            with self.db.transaction() as tx:
                tx.execute("INSERT INTO auth_funnel_events(event_name,created_at,user_id,source) VALUES(?,?,?,?)",
                           ("register_success", int(time.time()), user_row["id"], "web"))
            cookie_hdr = None if body.get("noSession") else self._cookie_for_token(token)
            self._send_json({"ok": True, "token": token, "boot": boot}, set_cookie=cookie_hdr)
            return

        if req_path == "/api/auth/login":
            self._enforce_auth_rate_limit(
                "login",
                str(body.get("identifier") or body.get("username") or body.get("account") or body.get("email") or ""),
            )
            with self.db.transaction() as tx:
                tx.execute("INSERT INTO auth_funnel_events(event_name,created_at,source) VALUES(?,?,?)",
                           ("login_attempt", int(time.time()), "web"))
            user_row, token = login_user(
                self.db,
                identifier=str(body.get("identifier") or body.get("username") or body.get("account") or body.get("email") or ""),
                password=str(body.get("password") or ""),
                user_agent=ua,
                ip_addr=ip_addr,
            )
            from .p2_growth import record_login
            unfamiliar_browser = record_login(self.db, user_row, ua)
            if unfamiliar_browser:
                from .features import try_send_security_alert
                try_send_security_alert(self.db, user_row, "新的浏览器登录",
                    "账号出现新的浏览器环境登录。如果不是你本人操作，请立即修改密码并退出其他设备。")
            boot = build_boot_payload(self.db, user_row)
            with self.db.transaction() as tx:
                tx.execute("INSERT INTO auth_funnel_events(event_name,created_at,user_id,source) VALUES(?,?,?,?)",
                           ("login_success", int(time.time()), user_row["id"], "web"))
            cookie_hdr = None if body.get("noSession") else self._cookie_for_token(token)
            self._send_json({"ok": True, "token": token, "boot": boot}, set_cookie=cookie_hdr)
            return

        if req_path == "/api/auth/logout":
            cur = self._current_user(required=False)
            if cur and cur.get("_session_token"):
                logout_session(self.db, str(cur["_session_token"]))
            boot = build_boot_payload(self.db, None)
            self._send_json({"ok": True, "boot": boot}, set_cookie=self._cookie_for_token("", clear=True))
            return

        if req_path == "/api/auth/profile":
            user = self._current_user(required=True)
            updated = update_my_profile(self.db, user, body)
            if body.get("newPassword"):
                from .features import try_send_security_alert
                try_send_security_alert(self.db, user, "密码已修改",
                    "你的 Handraw 账号密码刚刚发生变化。若非本人操作，请立即使用已验证邮箱找回密码。")
            self._send_json(updated)
            return

        if req_path == "/api/auth/sandbox-switch":
            self._require_demo_mode()
            target = str(body.get("username") or "").strip()
            if not target or target == "guest":
                cur = self._current_user(required=False)
                if cur and cur.get("_session_token"):
                    logout_session(self.db, str(cur["_session_token"]))
                boot = build_boot_payload(self.db, None)
                self._send_json({"ok": True, "boot": boot}, set_cookie=self._cookie_for_token("", clear=True))
                return
            user_row, token = sandbox_switch_account(self.db, target, user_agent=ua, ip_addr=ip_addr)
            boot = build_boot_payload(self.db, user_row)
            cookie_hdr = None if body.get("noSession") else self._cookie_for_token(token)
            self._send_json({"ok": True, "token": token, "boot": boot}, set_cookie=cookie_hdr)
            return

        if req_path == "/api/dev/reset":
            self._require_demo_mode()
            ensure_seeded(self.db, force_reset=True)
            user_row, token = sandbox_switch_account(self.db, "yang0", user_agent=ua, ip_addr=ip_addr)
            boot = build_boot_payload(self.db, user_row)
            cookie_hdr = None if body.get("noSession") else self._cookie_for_token(token)
            self._send_json({"ok": True, "token": token, "boot": boot}, set_cookie=cookie_hdr)
            return

        # Wallet & Economy Endpoints
        if req_path == "/api/wallet/checkin":
            user = self._current_user(required=True)
            self._send_json(perform_daily_checkin(self.db, user))  # type: ignore[arg-type]
            return

        if req_path == "/api/wallet/redeem":
            user = self._current_user(required=True)
            self._send_json(redeem_code_for_user(self.db, user, str(body.get("code") or "")))  # type: ignore[arg-type]
            return

        if req_path == "/api/wallet/recharge":
            if not recharge_enabled():
                raise ServiceError("现金充值尚未接入可信支付回调", status=503, code="payment_disabled")
            user = self._current_user(required=True)
            self._send_json(topup_credits_for_user(self.db, user, int(body.get("amount") or 50)))  # type: ignore[arg-type]
            return

        if req_path == "/api/billing/checkout":
            user = self._current_user(required=True)
            from .billing import create_checkout_order
            self._send_json(
                create_checkout_order(
                    self.db,
                    user,  # type: ignore[arg-type]
                    str(body.get("packId") or ""),
                    request_headers={k: v for k, v in self.headers.items()},
                    server_port=getattr(self.server, "server_port", None),
                )
            )
            return

        m_billing_sync = re.fullmatch(r"/api/billing/orders/([^/]+)/sync", req_path)
        if m_billing_sync:
            user = self._current_user(required=True)
            from .billing import sync_payment_order_from_provider
            self._send_json(
                sync_payment_order_from_provider(
                    self.db,
                    user,  # type: ignore[arg-type]
                    m_billing_sync.group(1),
                    checkout_id=str(body.get("checkoutId") or ""),
                    provider_order_id=str(body.get("providerOrderId") or ""),
                    redirect_query=str(body.get("redirectQuery") or ""),
                )
            )
            return

        # Collections, Cheers, Tips, Paid Unlocks & Reports
        if req_path == "/api/collections/toggle":
            user = self._current_user(required=True)
            self._send_json(
                toggle_user_collection(
                    self.db,
                    user,  # type: ignore[arg-type]
                    bucket=str(body.get("bucket") or ""),
                    target_id=str(body.get("id") or body.get("targetId") or ""),
                    title_label=str(body.get("title") or ""),
                    action=str(body.get("action") or "").strip().lower() or None,
                )
            )
            return

        if req_path == "/api/interactions/cheer":
            user = self._current_user(required=True)
            self._send_json(
                toggle_user_cheer(
                    self.db,
                    user,  # type: ignore[arg-type]
                    target_type=str(body.get("targetType") or "work"),
                    target_id=str(body.get("targetId") or body.get("id") or ""),
                    stamp_label=str(body.get("stampLabel") or body.get("stamp") or ""),
                )
            )
            return

        if req_path == "/api/interactions/like":
            user = self._current_user(required=True)
            self._send_json(
                toggle_user_like(
                    self.db,
                    user,  # type: ignore[arg-type]
                    target_type=str(body.get("targetType") or "work"),
                    target_id=str(body.get("targetId") or body.get("id") or ""),
                    action=str(body.get("action") or "").strip().lower() or None,
                )
            )
            return

        if req_path == "/api/interactions/tip":
            user = self._current_user(required=True)
            raw_amount = body.get("amount") if "amount" in body else None
            self._send_json(
                send_encourage_tip(
                    self.db,
                    user,  # type: ignore[arg-type]
                    target_type=str(body.get("targetType") or "work"),
                    target_id=str(body.get("targetId") or body.get("id") or ""),
                    amount=raw_amount,
                    request_id=str(body.get("requestId") or body.get("request_id") or "").strip() or None,
                )
            )
            return

        if req_path == "/api/unlocks":
            user = self._current_user(required=True)
            self._send_json(
                unlock_paid_item(
                    self.db,
                    user,  # type: ignore[arg-type]
                    target_type=str(body.get("targetType") or ""),
                    target_id=str(body.get("targetId") or body.get("id") or ""),
                )
            )
            return

        if req_path == "/api/reports":
            user = self._current_user(required=True)
            self._send_json(submit_abuse_report(self.db, user, body))  # type: ignore[arg-type]
            return

        # Uploads, Works, Community Assets & Forum
        if req_path in ("/api/uploads", "/api/studio/uploads"):
            user = self._current_user(required=True)
            raw_cat = str(body.get("cat") or "other").strip().lower()
            PUBLIC_CATS = ("characters", "props", "scenes", "other")
            INTERNAL_CATS = ("forum",)          # 仅由论坛/投稿发布写入，原样保留
            if raw_cat in PUBLIC_CATS or raw_cat in INTERNAL_CATS:
                safe_cat = raw_cat
            else:
                safe_cat = "other"              # 未知值、以及 'import' 一律降级
            saved = save_data_url_upload(
                self.db,
                user,
                data_url=str(body.get("dataUrl") or body.get("image") or ""),
                name_zh=str(body.get("nameZh") or body.get("name") or "上传素材"),
                desc_zh=str(body.get("descZh") or ""),
                cat=safe_cat,
            )
            self._send_json({"ok": True, **saved})
            return

        if req_path == "/api/works":
            user = self._current_user(required=True)
            clean_body = _persist_inline_images_in_body(self.db, user, body)
            validate_topic_title(clean_body.get("title"))
            raw_notes = str(clean_body.get("notes") or "").strip()
            notes_non_ws = re.sub(r"\s+", "", raw_notes)
            if not notes_non_ws:
                raise ServiceError("发布作品需要填写创作说明", status=400, code="notes_required")
            if len(notes_non_ws) < 8:
                raise ServiceError("作品创作说明至少需要 8 个字", status=400, code="notes_too_short")
            result = publish_user_work(self.db, user, clean_body)  # type: ignore[arg-type]
            _grant_published_media(self.db, user, clean_body, target_type="topic", target_id=str(result.get("topicId") or ""))
            self._send_json(result)
            return

        # Skill share contract.  ``community-share`` posts ``{"entry": {...}}``
        # and expects ``{"id", "kind": "work"}`` back so it can mint a durable
        # receipt.  This is the entry point the Skill targets; the shape is
        # translated here rather than making every Skill client speak the
        # browser payload.
        if req_path == "/api/entries":
            user = self._current_user(required=True)
            entry = body.get("entry") if isinstance(body, dict) else None
            if not isinstance(entry, dict):
                self._send_json({"ok": False, "error": "缺少 entry 对象", "code": "entry_required"}, status=400)
                return
            clean_body = _persist_inline_images_in_body(self.db, user, _entry_to_work_body(entry))
            result = publish_user_work(self.db, user, clean_body)  # type: ignore[arg-type]
            _grant_published_media(self.db, user, clean_body, target_type="topic", target_id=str(result.get("topicId") or ""))
            self._send_json(
                {
                    "ok": True,
                    "id": result.get("workId"),
                    "kind": "work",
                    "topicId": result.get("topicId"),
                    "url": result.get("url"),
                    "status": result.get("status"),
                }
            )
            return

        m_work_cover = re.match(r"^/api/works/([^/]+)/cover/?$", req_path)
        if m_work_cover:
            user = self._current_user(required=True)
            from .generation_v3 import set_work_cover
            self._send_json(set_work_cover(
                self.db, user, m_work_cover.group(1),
                str(body.get("imageUrl") or body.get("url") or ""),
            ))
            return

        m_work_comment = re.match(r"^/api/works/([^/]+)/comments$", req_path)
        if m_work_comment:
            user = self._current_user(required=True)
            self._send_json(add_comment_to_work(self.db, user, m_work_comment.group(1), str(body.get("text") or "")))  # type: ignore[arg-type]
            return

        m_asset_comment = re.match(r"^/api/assets/([^/]+)/comments$", req_path)
        if m_asset_comment:
            user = self._current_user(required=True)
            self._send_json(
                add_comment_to_asset(
                    self.db,
                    user,  # type: ignore[arg-type]
                    unquote(m_asset_comment.group(1)),
                    str(body.get("text") or ""),
                    str(body.get("kind") or ""),
                )
            )
            return

        if req_path == "/api/catalog/community":
            user = self._current_user(required=True)
            clean_body = _persist_inline_images_in_body(self.db, user, body)
            result = publish_user_community_asset(self.db, user, clean_body)  # type: ignore[arg-type]
            _grant_published_media(self.db, user, clean_body, target_type="topic", target_id=str(result.get("topicId") or ""))
            self._send_json(result)
            return

        if req_path in ("/api/forum/topics", "/api/topics"):
            user = self._current_user(required=True)
            clean_body = _persist_inline_images_in_body(self.db, user, body)
            result = publish_forum_topic_post(self.db, user, clean_body)  # type: ignore[arg-type]
            _grant_published_media(self.db, user, clean_body, target_type="topic", target_id=str(result.get("topicId") or ""))
            self._send_json(result)
            return

        m_topic_reply = re.match(r"^/api/(?:forum/topics|posts)/([^/]+)/replies$", req_path)
        if m_topic_reply:
            user = self._current_user(required=True)
            self._send_json(
                publish_forum_reply_post(
                    self.db,
                    user,  # type: ignore[arg-type]
                    topic_id=m_topic_reply.group(1),
                    text=str(body.get("text") or ""),
                    mounted_style=str(body.get("mountedStyle") or ""),
                    mounted_layout=str(body.get("mountedLayout") or ""),
                )
            )
            return

        m_topic_bounty = re.match(r"^/api/forum/topics/([^/]+)/accept-bounty$", req_path)
        if m_topic_bounty:
            user = self._current_user(required=True)
            self._send_json(accept_forum_bounty_reply(self.db, user, m_topic_bounty.group(1), str(body.get("replyId") or "")))  # type: ignore[arg-type]
            return

        if req_path == "/api/forum/moderate":
            user = self._current_user(required=True)
            self._send_json(forum_moderator_action(self.db, user, body))  # type: ignore[arg-type]
            return

        # Studio Cloud Persistence, Generation & ZIP Export
        if req_path == "/api/studio/canvases":
            from .studio_canvases import save_canvas
            self._send_json(save_canvas(self.db,self._current_user(required=True),body))
            return
        canvas_retry=re.fullmatch(r"/api/studio/canvas-runs/([^/]+)/retry",req_path)
        if canvas_retry:
            from .canvas_runs import retry_canvas_run
            self._send_json(retry_canvas_run(self.db,self._current_user(required=True),canvas_retry.group(1),body))
            return
        canvas_delete=re.fullmatch(r"/api/studio/canvases/([^/]+)/delete",req_path)
        if canvas_delete:
            user=self._current_user(required=True)
            self.db.get_conn().execute("UPDATE studio_canvases SET deleted_at=now() WHERE id=? AND user_id=?",(canvas_delete.group(1),user["id"]))
            self._send_json({"ok":True})
            return
        canvas_action = re.fullmatch(r"/api/studio/canvases/([^/]+)/(preview|runs)",req_path)
        if canvas_action:
            from .studio_canvases import preview_canvas,submit_canvas
            user = self._current_user(required=True)
            self._send_json(preview_canvas(self.db,user,canvas_action.group(1)) if canvas_action.group(2)=="preview"
                            else submit_canvas(self.db,user,canvas_action.group(1),body))
            return
        if req_path == "/api/studio/workflows":
            user = self._current_user(required=True)
            self._send_json(save_user_studio_workflow(self.db, user, body))  # type: ignore[arg-type]
            return

        if req_path == "/api/studio/workflows/delete":
            user = self._current_user(required=True)
            self._send_json(delete_user_studio_workflow(self.db, user, str(body.get("id") or "")))  # type: ignore[arg-type]
            return

        if req_path == "/api/studio/articles":
            user = self._current_user(required=True)
            articles = body.get("articles") if isinstance(body.get("articles"), list) else (body.get("_list") or [])
            self._send_json(sync_user_studio_articles(self.db, user, articles))  # type: ignore[arg-type]
            return

        article_selection = re.fullmatch(r"/api/studio/articles/([^/]+)/illustrations/([^/]+)/selection", req_path)
        if article_selection:
            from .studio_articles import select_illustration_media
            self._send_json(select_illustration_media(
                self.db, self._current_user(required=True), article_selection.group(1), article_selection.group(2), body,
            ))
            return

        if req_path == "/api/studio/articles/delete":
            user = self._current_user(required=True)
            aid = str(body.get("id") or body.get("articleId") or "").strip()
            self._send_json(delete_user_studio_article(self.db, user, aid))  # type: ignore[arg-type]
            return

        m_art_del = re.match(r"^/api/studio/articles/([^/]+)/delete$", req_path)
        if m_art_del:
            user = self._current_user(required=True)
            self._send_json(delete_user_studio_article(self.db, user, m_art_del.group(1)))  # type: ignore[arg-type]
            return

        if req_path == "/api/studio/parse-article":
            from backend.document_parser import parse_article_file

            user = self._current_user(required=True)
            if not consume_daily_usage(self.db, user["id"], "parse", 20):
                raise ServiceError("今日文档解析次数已达上限（20次/天），请明天再试", status=429, code="rate_limited")

            file_name = str(body.get("fileName") or body.get("name") or "")
            file_data = body.get("fileData") or body.get("data") or body.get("dataUrl") or ""
            raw_text = str(body.get("text") or "")

            if file_data and isinstance(file_data, str):
                if "," in file_data:
                    file_data = file_data.split(",", 1)[1]
                try:
                    file_bytes = base64.b64decode(file_data)
                except Exception as exc:
                    raise ServiceError(f"文件数据 Base64 解码失败：{exc}", status=400) from exc
            elif raw_text:
                file_bytes = raw_text.encode("utf-8")
            else:
                raise ServiceError("未提供有效的文件数据或文本正文", status=400)

            if len(file_bytes) > 10 * 1024 * 1024:
                raise ServiceError("解码后文件大小超过 10MB 限制", status=413, code="payload_too_large")

            logger.info("event=article_import user_id=%s bytes=%d", user["id"], len(file_bytes))
            parsed_res = parse_article_file(file_bytes, file_name)
            self._send_json({"ok": True, **parsed_res})
            return

        if req_path == "/api/studio/imports":
            from backend.db import local_today_str
            from backend.document_importer import get_import_manager, utc_now_iso

            user = self._current_user(required=True)
            user_id = int(user["id"])

            file_name = str(body.get("fileName") or body.get("name") or "")
            file_data = body.get("fileData") or body.get("data") or body.get("dataUrl") or ""
            raw_text = str(body.get("text") or "")

            if file_data and isinstance(file_data, str):
                if "," in file_data:
                    file_data = file_data.split(",", 1)[1]
                try:
                    file_bytes = base64.b64decode(file_data)
                except Exception as exc:
                    raise ServiceError(f"文件数据 Base64 解码失败：{exc}", status=400) from exc
            elif raw_text:
                file_bytes = raw_text.encode("utf-8")
            else:
                raise ServiceError("未提供有效的文件数据或文本正文", status=400)

            if len(file_bytes) > 10 * 1024 * 1024:
                raise ServiceError("解码后文件大小超过 10MB 限制", status=413, code="payload_too_large")

            mgr = getattr(self.server, "import_manager", None) or get_import_manager(self.db)
            if mgr.queue.full():
                raise ServiceError("导入队列已满，请稍后再试", status=429, code="import_queue_full")

            job_id = f"imp_{uuid.uuid4().hex}"
            now = utc_now_iso()
            today = local_today_str()

            from .import_jobs import persist_input,discard_input
            self.db.release_request_connection()
            input_key,input_digest=persist_input(job_id,file_bytes)
            try:
                with self.db.transaction() as tx:
                    # Admission spans all request workers and connection pools.
                    # Hold only while checking capacity and reserving the job.
                    tx.execute("SELECT pg_advisory_xact_lock(186, 206)")
                    active_job = tx.execute(
                        "SELECT 1 FROM studio_import_jobs WHERE user_id = ? AND status IN ('queued', 'running') LIMIT 1",
                        (user_id,),
                    ).fetchone()
                    if active_job:
                        raise ServiceError("已有导入任务正在进行中，请稍后再试", status=429, code="import_in_progress")

                    queued_count = tx.execute(
                        "SELECT COUNT(1) as cnt FROM studio_import_jobs WHERE status IN ('queued','running')",
                    ).fetchone()
                    if (queued_count and int(queued_count["cnt"]) >= 20) or mgr.queue.full():
                        raise ServiceError("导入队列已满，请稍后再试", status=429, code="import_queue_full")

                    usage_row = tx.execute(
                        "SELECT count FROM daily_usage WHERE user_id = ? AND scope = 'parse' AND usage_date = ?",
                        (user_id, today),
                    ).fetchone()
                    current_usage = int(usage_row["count"]) if usage_row else 0
                    if current_usage >= 20:
                        raise ServiceError("今日文档解析次数已达上限（20次/天），请明天再试", status=429, code="rate_limited")

                    tx.execute(
                        """
                        INSERT INTO daily_usage (user_id, scope, usage_date, count)
                        VALUES (?, 'parse', ?, 1)
                        ON CONFLICT (user_id, scope, usage_date)
                        DO UPDATE SET count = daily_usage.count + 1
                        """,
                        (user_id, today),
                    )

                    tx.execute(
                        """
                        INSERT INTO studio_import_jobs
                        (id, user_id, status, progress_done, progress_total, error, result_json, file_name, created_at, updated_at,input_storage_key,input_sha256)
                        VALUES (?, ?, 'queued', 0, 0, '', '', ?, ?, ?,?,?)
                        """,
                        (job_id, user_id, file_name, now, now,input_key,input_digest),
                    )

            except BaseException:
                discard_input(input_key)
                raise

            try:
                mgr.enqueue_job(job_id, user_id, file_name, file_bytes)
            except Exception:
                # The committed input is durable and discoverable without the
                # hint. Never remove a task another process may already own.
                logger.warning("Import wake-up hint failed for %s; database workers will recover it",job_id,exc_info=True)

            self._send_json({"ok": True, "importId": job_id})
            return

        if req_path.startswith("/api/studio/recipes"):
            from .recipe_routes import handle_recipe_post
            if handle_recipe_post(self, req_path, body):
                return

        if req_path == "/api/studio/fission":
            from .fission_routes import handle_fission_post
            if handle_fission_post(self, req_path, body):
                return

        if req_path == "/api/studio/batch-plan":
            from .batch_plan_routes import handle_batch_plan_post
            if handle_batch_plan_post(self, req_path, body):
                return

        if req_path == "/api/studio/article-plan":
            from .article_plan_routes import handle_article_plan_post
            if handle_article_plan_post(self, req_path, body):
                return

        if req_path == "/api/studio/history":
            user = self._current_user(required=True)
            self._send_json(record_user_studio_history(self.db, user, body))  # type: ignore[arg-type]
            return

        m_batch_cancel = re.match(r"^/api/studio/batches/([^/]+)/cancel-pending/?$", req_path)
        if m_batch_cancel:
            user = self._current_user(required=True)
            from .generation_v3 import cancel_unsubmitted_web_slots
            self._send_json(cancel_unsubmitted_web_slots(
                self.db, user, m_batch_cancel.group(1),
                body.get("positions") or [],
            ))
            return

        m_fork_gen = re.match(r"^/api/studio/generations/([^/]+)/fork$", req_path)
        if m_fork_gen:
            user = self._current_user(required=True)
            gen_id = m_fork_gen.group(1).strip()
            self._send_json(fork_generation_recipe(self.db, user, gen_id, body))
            return

        if req_path == "/api/studio/generate":
            for key in ("_canvasDispatchToken","_canvasResourceInputs","_canvasRunId","_canvasItemId"):
                body.pop(key,None)
            payload,status=execute_studio_generation(
                self.db,self._current_user(required=True),body,
                demo_mode=self._demo_enabled(),request_log_id=getattr(self,"_request_id",""),
            )
            self._send_json(payload,status=status)
            return

        if req_path == "/api/studio/export-zip":
            user = self._current_user(required=True)
            zip_bytes, filename = build_export_zip_package(body, db=self.db, user=user)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self._cors_headers()
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)
            return

        # Admin & Front-Stage Works Moderation & Deletion
        m_mod_work = re.match(r"^/api/(?:admin/)?works/([^/]+)/moderate$", req_path)
        if m_mod_work:
            user = self._current_user(required=True)
            action = str(body.get("action") or "").strip().lower()
            result = admin_moderate_work(self.db, user, m_mod_work.group(1), action, body)
            if action in {"delete", "pause", "hide"}:
                _revoke_media_grants(self.db, "work", m_mod_work.group(1))
            self._send_json(result)
            return

        m_del_work = re.match(r"^/api/(?:admin/)?works/([^/]+)/delete$", req_path)
        if m_del_work:
            user = self._current_user(required=True)
            result = admin_moderate_work(self.db, user, m_del_work.group(1), "delete", body)
            _revoke_media_grants(self.db, "work", m_del_work.group(1))
            self._send_json(result)
            return

        if req_path in ("/api/comments/moderate", "/api/admin/comments/moderate"):
            user = self._current_user(required=True)
            self._send_json(
                admin_moderate_comment(
                    self.db,
                    user,
                    comment_type=str(body.get("commentType") or ""),
                    comment_id=str(body.get("id") or ""),
                    action=str(body.get("action") or ""),
                    reason=str(body.get("reason") or ""),
                )
            )
            return

        if req_path == "/api/admin/catalog/official":
            user = self._current_user(required=True)
            self._send_json(admin_create_official_asset(self.db, user, body))
            return

        m_del_off = re.match(r"^/api/admin/catalog/official/([^/]+)/delete$", req_path)
        if m_del_off:
            user = self._current_user(required=True)
            self._send_json(admin_delete_official_asset(self.db, user, m_del_off.group(1), str(body.get("reason") or "")))
            return

        m_upd_off = re.match(r"^/api/admin/catalog/official/([^/]+)$", req_path)
        if m_upd_off:
            user = self._current_user(required=True)
            self._send_json(admin_update_official_asset(self.db, user, m_upd_off.group(1), body))
            return

        if req_path == "/api/admin/catalog":
            user = self._current_user(required=True)
            clean_body = _persist_inline_images_in_body(self.db, user, body)
            self._send_json(admin_upsert_catalog_asset(self.db, user, clean_body))
            return

        m_del_cat = re.match(r"^/api/admin/catalog/([^/]+)/delete$", req_path)
        if m_del_cat:
            user = self._current_user(required=True)
            result = admin_delete_catalog_asset(self.db, user, m_del_cat.group(1), str(body.get("reason") or ""))
            _revoke_media_grants(self.db, "asset", m_del_cat.group(1))
            self._send_json(result)
            return

        if req_path == "/api/admin/presets":
            user = self._current_user(required=True)
            self._send_json(admin_upsert_preset(self.db, user, body))
            return

        m_mod_topic = re.match(r"^/api/(?:admin/)?topics/([^/]+)/moderate$", req_path)
        if m_mod_topic:
            user = self._current_user(required=True)
            action = str(body.get("action") or "").strip().lower()
            result = admin_moderate_topic(self.db, user, m_mod_topic.group(1), action, body)
            if action in {"delete", "pause", "hide"}:
                _revoke_media_grants(self.db, "topic", m_mod_topic.group(1))
            self._send_json(result)
            return

        m_del_topic = re.match(r"^/api/(?:admin/)?topics/([^/]+)/delete$", req_path)
        if m_del_topic:
            user = self._current_user(required=True)
            result = admin_moderate_topic(self.db, user, m_del_topic.group(1), "delete", body)
            _revoke_media_grants(self.db, "topic", m_del_topic.group(1))
            self._send_json(result)
            return

        if req_path == "/api/admin/forum-moderators":
            user = self._current_user(required=True)
            self._send_json(admin_assign_forum_moderator(self.db, user, body))
            return

        if req_path == "/api/admin/forum-boards":
            from .forum_boards import save_board
            self._send_json(save_board(self.db, self._current_user(required=True), body))
            return

        board_route = re.fullmatch(r"/api/admin/forum-boards/([a-z0-9_-]+)(/members)?", req_path)
        if board_route:
            from .forum_boards import save_board, change_members
            actor = self._current_user(required=True)
            if board_route.group(2):
                self._send_json(change_members(self.db, actor, board_route.group(1), body))
            else:
                self._send_json(save_board(self.db, actor, body, board_route.group(1)))
            return

        if req_path == "/api/admin/forum-moderators/revoke":
            user = self._current_user(required=True)
            self._send_json(admin_revoke_forum_moderator(self.db, user, body))
            return

        m_res_report = re.match(r"^/api/admin/reports/(\d+)/resolve$", req_path)
        if m_res_report:
            user = self._current_user(required=True)
            self._send_json(
                admin_resolve_report(
                    self.db,
                    user,
                    report_id=int(m_res_report.group(1)),
                    resolution=str(body.get("resolution") or ""),
                    note=str(body.get("note") or ""),
                    auto_action=bool(body.get("autoAction", True)),
                )
            )
            return

        if req_path == "/api/admin/users/create":
            user = self._current_user(required=True)
            self._send_json(admin_create_user(self.db, user, body))
            return

        m_del_user = re.match(r"^/api/admin/users/(\d+)/delete$", req_path)
        if m_del_user:
            user = self._current_user(required=True)
            self._send_json(admin_delete_user(self.db, user, int(m_del_user.group(1)), str(body.get("reason") or "")))
            return

        m_upd_user = re.match(r"^/api/admin/users/(\d+)/update$", req_path)
        if m_upd_user:
            user = self._current_user(required=True)
            self._send_json(admin_update_user(self.db, user, int(m_upd_user.group(1)), body))
            return

        m_cred_user = re.match(r"^/api/admin/users/(\d+)/credits$", req_path)
        if m_cred_user:
            user = self._current_user(required=True)
            self._send_json(
                admin_adjust_user_credits(
                    self.db,
                    user,
                    int(m_cred_user.group(1)),
                    int(body.get("delta") or 0),
                    str(body.get("reason") or ""),
                )
            )
            return

        m_quota_user = re.match(r"^/api/admin/users/(\d+)/reset-quota$", req_path)
        if m_quota_user:
            user = self._current_user(required=True)
            self._send_json(admin_reset_user_free_quota(self.db, user, int(m_quota_user.group(1)), str(body.get("reason") or "")))
            return

        if req_path == "/api/admin/users/import-discourse":
            user = require_staff(self._current_user(required=True), allow_reviewer=False)
            raw_payload = body.get("payload") or body.get("users") or body.get("_list") or ""
            mig_credits = int(body["migrationCredits"]) if body.get("migrationCredits") is not None else None
            self._send_json(import_discourse_users_batch(self.db, user, raw_payload, migration_credits=mig_credits))
            return

        m_refund_ul = re.match(r"^/api/admin/unlocks/(\d+)/refund$", req_path)
        if m_refund_ul:
            user = self._current_user(required=True)
            self._send_json(admin_refund_unlock(self.db, user, int(m_refund_ul.group(1)), str(body.get("reason") or "")))
            return

        if req_path == "/api/admin/redeem-codes":
            user = self._current_user(required=True)
            self._send_json(admin_create_redeem_code(self.db, user, body))
            return

        m_toggle_redeem = re.match(r"^/api/admin/redeem-codes/([^/]+)/toggle$", req_path)
        if m_toggle_redeem:
            user = self._current_user(required=True)
            self._send_json(admin_toggle_redeem_code(self.db, user, m_toggle_redeem.group(1), bool(body.get("active"))))
            return

        if req_path == "/api/admin/gateway":
            user = self._current_user(required=True)
            self._send_json(admin_update_gateway_config(self.db, user, body))
            return

        if req_path == "/api/admin/settings":
            user = self._current_user(required=True)
            self._send_json(
                admin_update_settings(
                    self.db,
                    user,
                    section=str(body.get("section") or ""),
                    values=body.get("values") if isinstance(body.get("values"), dict) else {},
                    reason=str(body.get("reason") or ""),
                )
            )
            return

        if req_path == "/api/admin/home-scenarios":
            from .home_scenarios import (
                admin_save_home_scenario,
                admin_toggle_home_scenario,
                admin_reorder_home_scenarios,
                admin_pin_scenario_work,
                admin_unpin_scenario_work,
                admin_reorder_scenario_pins,
            )
            user = self._current_user(required=True)
            action = str(body.get("action") or "").strip().lower()
            if action == "toggle":
                is_enabled = bool(body.get("isEnabled") if body.get("isEnabled") is not None else body.get("is_enabled", True))
                res = admin_toggle_home_scenario(
                    self.db, user, key=str(body.get("key") or ""), is_enabled=is_enabled
                )
            elif action == "reorder":
                res = admin_reorder_home_scenarios(
                    self.db, user, orders=body.get("orders") or []
                )
            elif action == "pin":
                res = admin_pin_scenario_work(
                    self.db,
                    user,
                    scenario_key=str(body.get("scenarioKey") or body.get("scenario_key") or ""),
                    work_id=str(body.get("workId") or body.get("work_id") or ""),
                    sort_order=int(body.get("sortOrder") if body.get("sortOrder") is not None else body.get("sort_order", 0)),
                )
            elif action == "unpin":
                res = admin_unpin_scenario_work(
                    self.db,
                    user,
                    scenario_key=str(body.get("scenarioKey") or body.get("scenario_key") or ""),
                    work_id=str(body.get("workId") or body.get("work_id") or ""),
                )
            elif action == "reorder_pins":
                res = admin_reorder_scenario_pins(
                    self.db,
                    user,
                    scenario_key=str(body.get("scenarioKey") or body.get("scenario_key") or ""),
                    work_ids=body.get("workIds") or body.get("pins") or [],
                )
            else:
                res = admin_save_home_scenario(self.db, user, body)
            self._send_json(res)
            return

        self._send_json({"ok": False, "error": f"Unknown endpoint: {req_path}"}, status=404)


class HandrawHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        # Final fallback for failures outside route dispatch, e.g. setup or
        # connection cleanup. The stdlib default only prints to stderr.
        logger.exception("event=http_connection_failure")


class DualStackHTTPServer(HandrawHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except Exception:
            pass
        super().server_bind()


def create_channel_server(
    port: int,
    role: str,
    db: Database,
    host: str | None = None,
    demo_mode: bool | None = None,
) -> ThreadingHTTPServer:
    safe_host = bind_host(host)
    if ":" in safe_host:
        try:
            srv: ThreadingHTTPServer = DualStackHTTPServer((safe_host, port), HandrawRequestHandler)
        except Exception:
            srv = HandrawHTTPServer(("127.0.0.1", port), HandrawRequestHandler)
    else:
        srv = HandrawHTTPServer((safe_host, port), HandrawRequestHandler)
    srv.channel_role = role  # type: ignore[attr-defined]
    srv.db = db  # type: ignore[attr-defined]
    from .services import bind_runtime_database
    bind_runtime_database(db)  # Security/catalog reads use the same authoritative DB.
    srv.allow_demo_routes = demo_mode if demo_mode is not None else demo_mode_enabled()  # type: ignore[attr-defined]
    srv.bind_host = safe_host  # type: ignore[attr-defined]
    from backend.document_importer import get_import_manager
    srv.import_manager = get_import_manager(db)  # type: ignore[attr-defined]
    return srv


def init_database(dsn: str) -> Database:
    db = Database(dsn)
    try:
        ensure_seeded(db)
    except BaseException:
        db.close()
        raise
    return db


def check_optional_dependencies() -> None:
    try:
        import docx  # noqa: F401
    except Exception:
        logger.warning("缺少 python-docx，导入 .docx 会失败，请执行 pip install -r requirements.txt")
    try:
        import fitz  # noqa: F401
    except Exception:
        logger.warning("缺少 PyMuPDF，导入 .pdf 会失败，请执行 pip install -r requirements.txt")


def _load_env_file_if_present() -> None:
    for env_name in (".env.local", ".env"):
        env_file = Path(__file__).resolve().parent.parent / env_name
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _load_env_file_if_present()
    parser = argparse.ArgumentParser(description="Handraw Web single-backend server")
    parser.add_argument("--port", type=int, default=3080, help="Single HTTP port for all frontends (default: 3080)")
    parser.add_argument("--host", type=str, default="", help="Bind host; wildcard requires HANDRAW_ALLOW_PUBLIC_BIND=1")
    args = parser.parse_args(argv)
    from .observability import configure_logging
    configure_logging(port=args.port)
    check_optional_dependencies()

    from .redis_rate_limit import ensure_ready as ensure_redis_ready
    pg_url = os.environ.get("HANDRAW_DATABASE_URL", "").strip()
    if not pg_url:
        raise RuntimeError("请设置 HANDRAW_DATABASE_URL，指向 Handraw PostgreSQL 数据库")
    if os.environ.get("HANDRAW_REDIS_REQUIRED", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("PostgreSQL 服务要求 HANDRAW_REDIS_REQUIRED=1")
    if os.environ.get("HANDRAW_PG_RUNTIME_ACK", "") != "V3_NATIVE":
        raise RuntimeError(
            "请先为新建空库运行 python -m ops.bootstrap_postgres_v3 --apply，"
            "再设置 HANDRAW_PG_RUNTIME_ACK=V3_NATIVE"
        )
    ensure_redis_ready()

    db = init_database(pg_url)

    requested_host = args.host or None
    server = create_channel_server(args.port, "main", db, host=requested_host)
    reconciler = GenerationReconciler(db).start()
    from .canvas_dispatcher import get_canvas_dispatcher
    canvas_dispatcher=get_canvas_dispatcher(db).start()
    # Fresh V3 has no legacy data and therefore no background blackbox
    # backfill. Protected prompts are verified synchronously on publication.
    import_manager = getattr(server, "import_manager", None)

    print("Handraw Web single backend running (PostgreSQL V3 + Redis)")
    print(f"  [bind] {getattr(server, 'bind_host', '127.0.0.1')}")
    print(f"  [首页]   http://localhost:{args.port}/")
    print(f"  [创作台] http://localhost:{args.port}/studio/")
    print(f"  [社区]   http://localhost:{args.port}/forum/")
    print(f"  [后台]   http://localhost:{args.port}/admin/")
    print("  [部署] 按 Host 分发前端，所有二级域名共用本端口")
    print(f"  [DB] {db.db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        canvas_dispatcher.stop()
        reconciler.stop()
        if import_manager and hasattr(import_manager, "stop"):
            import_manager.stop()
        server.server_close()
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("event=startup_failed")
        raise SystemExit(1)
