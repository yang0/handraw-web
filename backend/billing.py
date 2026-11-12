"""Lemon Squeezy credit recharge checkout, webhook verification, and order sync."""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import logging
import os
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Mapping

from .config import get_public_billing_summary, load_payment_config, open_url
from .db import Database
from .observability import (
    extract_http_error_summary,
    local_debug_stacks_enabled,
    redact_sensitive_text,
    sanitize_log_text,
)
from .runtime_policy import normalize_origin, origin_allowed
from .services import ServiceError, apply_wallet_delta, utc_now_iso

logger = logging.getLogger("backend.billing")
trace_logger = logging.getLogger("handraw.trace")

LEMON_API_BASE = "https://api.lemonsqueezy.com"
MAX_WEBHOOK_BYTES = 512 * 1024


def get_billing_public_state() -> dict[str, Any]:
    return get_public_billing_summary()


def _serialize_order(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "packId": str(row["pack_id"]),
        "credits": int(row["credits"]),
        "amountCents": int(row["amount_cents"]),
        "currency": str(row["currency"] or "CNY"),
        "status": str(row["status"] or "pending"),
        "checkoutId": str(row["checkout_id"] or ""),
        "checkoutUrl": str(row["checkout_url"] or "") if row["status"] == "pending" else "",
        "providerOrderId": str(row["provider_order_id"] or ""),
        "providerOrderNumber": str(row["provider_order_number"] or ""),
        "testMode": bool(row["test_mode"]),
        "createdAt": str(row["created_at"] or ""),
        "updatedAt": str(row["updated_at"] or ""),
        "paidAt": str(row["paid_at"] or ""),
    }


def list_user_payment_orders(db: Database, user_id: int, limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(50, int(limit or 20)))
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT * FROM payment_orders
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (int(user_id), safe_limit),
    ).fetchall()
    return {
        "ok": True,
        "orders": [_serialize_order(r) for r in rows],
    }


def _strip_channel_subdomain(origin: str) -> str:
    clean = normalize_origin(origin)
    if not clean:
        return ""
    parsed = urllib.parse.urlparse(clean)
    hostname = (parsed.hostname or "").lower()
    for prefix in ("studio.", "forum.", "admin."):
        if hostname.startswith(prefix):
            root_host = hostname[len(prefix):]
            port_part = f":{parsed.port}" if parsed.port else ""
            candidate = f"{parsed.scheme}://{root_host}{port_part}"
            if origin_allowed(candidate):
                return candidate
    return clean


def resolve_main_portal_origin(headers: Mapping[str, str], *, server_port: int | None = None) -> str:
    """Resolve a trusted main-portal origin without trusting arbitrary redirect targets."""
    raw_origin = ""
    for k, v in headers.items():
        if k.lower() == "origin" and v:
            raw_origin = str(v).strip()
            break
    if raw_origin and origin_allowed(raw_origin):
        return _strip_channel_subdomain(raw_origin)

    raw_host = ""
    proto = "http"
    for k, v in headers.items():
        lk = k.lower()
        if lk == "host" and v:
            raw_host = str(v).split(",")[0].strip()
        elif lk == "x-forwarded-proto" and v:
            proto = str(v).split(",")[0].strip().lower() or "http"
    if raw_host:
        candidate = f"{proto}://{raw_host}"
        if origin_allowed(candidate):
            return _strip_channel_subdomain(candidate)

    env_base = normalize_origin(os.environ.get("HANDRAW_BASE_URL", ""))
    if env_base and origin_allowed(env_base):
        return _strip_channel_subdomain(env_base)
    return f"http://127.0.0.1:{int(server_port or 3080)}"


def _wallet_balance(conn: Any, user_id: int) -> int:
    row = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (int(user_id),)).fetchone()
    return int(row["balance"]) if row else 0


def _lemon_api_request(
    method: str,
    path: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    url = f"{LEMON_API_BASE}{path}"
    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    for attempt in range(2):
        req = urllib.request.Request(
            url,
            data=data_bytes,
            method=method.upper(),
            headers={
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "HandrawWeb/2.0",
                "Connection": "close",
            },
        )
        started = _dt.datetime.now(_dt.timezone.utc)
        try:
            with open_url(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                if not isinstance(parsed, dict):
                    raise RuntimeError("Invalid Lemon Squeezy response payload")
                return parsed
        except urllib.error.HTTPError as exc:
            elapsed_ms = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000
            err_bytes = b""
            try:
                err_bytes = exc.read(16384)
            except Exception:
                pass
            detail = extract_http_error_summary(err_bytes)
            logger.warning(
                "Lemon Squeezy API error: method=%s path=%s status=%s elapsed_ms=%.1f body_len=%d detail=%s",
                method.upper(),
                path,
                exc.code,
                elapsed_ms,
                len(err_bytes),
                sanitize_log_text(detail, 260) or "none",
            )
            if local_debug_stacks_enabled():
                trace_logger.warning(
                    "Lemon Squeezy API error trace: method=%s path=%s status=%s\n%s",
                    method.upper(),
                    path,
                    exc.code,
                    "".join(traceback.format_stack(limit=12)),
                )
            raise ServiceError("支付网关请求失败，请稍后重试", status=502, code="payment_gateway_error") from exc
        except Exception as exc:
            elapsed_ms = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000
            if attempt == 0 and isinstance(exc, (urllib.error.URLError, OSError, TimeoutError)):
                logger.warning(
                    "Lemon Squeezy API transient transport error (retrying): method=%s path=%s elapsed_ms=%.1f err=%s",
                    method.upper(),
                    path,
                    elapsed_ms,
                    redact_sensitive_text(str(exc)),
                )
                continue
            logger.exception(
                "Lemon Squeezy API transport failed: method=%s path=%s elapsed_ms=%.1f err=%s",
                method.upper(),
                path,
                elapsed_ms,
                redact_sensitive_text(str(exc)),
            )
            raise ServiceError("暂时无法连接支付网关，请稍后重试", status=502, code="payment_gateway_error") from exc
    raise ServiceError("暂时无法连接支付网关，请稍后重试", status=502, code="payment_gateway_error")


def create_checkout_order(
    db: Database,
    user: dict[str, Any],
    pack_id: str,
    *,
    request_headers: Mapping[str, str],
    server_port: int | None = None,
) -> dict[str, Any]:
    cfg = load_payment_config()
    if not cfg.get("enabled"):
        raise ServiceError("在线充值尚未配置完成", status=503, code="billing_not_configured")

    clean_pack_id = str(pack_id or "").strip()
    package = next((p for p in cfg["active_packages"] if p["id"] == clean_pack_id), None)
    if not package:
        raise ServiceError("无效的积分充值档位", status=400, code="invalid_package")

    uid = int(user["id"])
    order_id = f"ord_{uuid.uuid4().hex}"
    now = utc_now_iso()
    main_origin = resolve_main_portal_origin(request_headers, server_port=server_port)
    redirect_url = (
        f"{main_origin}/?view=wallet"
        f"&order={urllib.parse.quote(order_id)}"
        f"&ls_order=[order_id]"
        f"&ls_ident=[order_identifier]"
    )
    variant_id = str(package["variant_id"])
    store_id = str(cfg["store_id"])
    test_mode = bool(cfg.get("test_mode", True))

    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO payment_orders (
                id, user_id, provider, pack_id, variant_id, credits, amount_cents, currency,
                status, checkout_id, checkout_url, provider_order_id, provider_order_number,
                test_mode, meta_json, created_at, updated_at, paid_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                uid,
                "lemonsqueezy",
                clean_pack_id,
                variant_id,
                int(package["credits"]),
                int(package["price_cents"]),
                str(cfg["currency"]),
                "pending",
                "",
                "",
                "",
                "",
                1 if test_mode else 0,
                json.dumps({"packTitle": package["title"], "redirectBase": main_origin}, ensure_ascii=False),
                now,
                now,
                None,
            ),
        )

    checkout_data: dict[str, Any] = {
        "custom": {
            "order_id": order_id,
            "user_id": str(uid),
            "pack_id": clean_pack_id,
        }
    }
    user_email = str(user.get("email") or "").strip()
    if user_email and "@" in user_email and not user_email.endswith(".invalid"):
        checkout_data["email"] = user_email
    display_name = str(user.get("display_name") or user.get("username") or "").strip()
    if display_name:
        checkout_data["name"] = display_name[:120]

    checkout_payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "product_options": {
                    "enabled_variants": [int(variant_id)],
                    "redirect_url": redirect_url,
                    "receipt_button_text": "返回 Handraw 积分钱包",
                    "receipt_link_url": redirect_url,
                },
                "checkout_data": checkout_data,
                "test_mode": test_mode,
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": store_id}},
                "variant": {"data": {"type": "variants", "id": variant_id}},
            },
        }
    }

    try:
        res = _lemon_api_request("POST", "/v1/checkouts", cfg["api_key"], checkout_payload)
    except Exception:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE payment_orders SET status = 'failed', updated_at = ? WHERE id = ? AND status = 'pending'",
                (utc_now_iso(), order_id),
            )
        raise

    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    checkout_id = str(data.get("id") or "").strip()
    checkout_url = str(attrs.get("url") or "").strip()
    if not checkout_id or not checkout_url:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE payment_orders SET status = 'failed', updated_at = ? WHERE id = ? AND status = 'pending'",
                (utc_now_iso(), order_id),
            )
        raise ServiceError("支付网关未返回有效收银台地址", status=502, code="gateway_checkout_invalid")

    updated_at = utc_now_iso()
    with db.transaction() as tx:
        tx.execute(
            "UPDATE payment_orders SET checkout_id = ?, checkout_url = ?, updated_at = ? WHERE id = ?",
            (checkout_id, checkout_url, updated_at, order_id),
        )
        row = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()

    return {
        "ok": True,
        "order": _serialize_order(row),
        "checkoutUrl": checkout_url,
    }


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    clean_sig = str(signature_header or "").strip().lower()
    if not clean_sig or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest().lower()
    return hmac.compare_digest(expected, clean_sig)


def _merge_meta_json(existing_raw: Any, patch: dict[str, Any]) -> str:
    try:
        base = json.loads(existing_raw) if isinstance(existing_raw, str) and existing_raw else {}
    except Exception:
        base = {}
    if not isinstance(base, dict):
        base = {}
    base.update(patch)
    return json.dumps(base, ensure_ascii=False)


def _settle_paid_order_tx(
    tx: Any,
    *,
    order_id: str,
    provider_order_id: str,
    provider_order_number: str = "",
    variant_id: str = "",
    meta_patch: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int, bool]:
    query = "SELECT * FROM payment_orders WHERE id = ?"
    if getattr(tx, "dialect", "") == "postgresql":
        query += " FOR UPDATE"
    order = tx.execute(query, (order_id,)).fetchone()
    if not order:
        raise ServiceError("充值订单不存在", status=404, code="order_not_found")

    clean_provider_order_id = str(provider_order_id or "").strip()
    if not clean_provider_order_id:
        raise ServiceError("缺少上游订单号", status=400, code="missing_provider_order_id")

    conflict = tx.execute(
        "SELECT id FROM payment_orders WHERE provider = 'lemonsqueezy' AND provider_order_id = ? AND id <> ?",
        (clean_provider_order_id, order_id),
    ).fetchone()
    if conflict:
        raise ServiceError("该支付单号已绑定其他充值订单", status=409, code="provider_order_conflict")

    expected_variant = str(order["variant_id"] or "").strip()
    if variant_id and expected_variant and str(variant_id).strip() != expected_variant:
        raise ServiceError("支付商品规格与订单不匹配", status=400, code="variant_mismatch")

    uid = int(order["user_id"])
    cur_status = str(order["status"] or "")
    if cur_status == "refunded":
        raise ServiceError("该订单已退款，无法再次入账", status=409, code="order_already_refunded")

    if cur_status == "paid":
        existing_poid = str(order["provider_order_id"] or "").strip()
        if existing_poid and existing_poid != clean_provider_order_id:
            raise ServiceError("该订单已由其他支付单完成入账", status=409, code="order_conflict")
        bal_row = tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        bal = int(bal_row["balance"]) if bal_row else 0
        return _serialize_order(order), bal, False

    credits = int(order["credits"])
    now = utc_now_iso()
    new_bal, applied = apply_wallet_delta(
        tx,
        uid,
        credits,
        "recharge",
        f"在线充值积分到账 (+{credits} 积分)",
        event_key=f"ls_order_{clean_provider_order_id}",
        ref_type="payment_order",
        ref_id=order_id,
    )
    new_meta = _merge_meta_json(order["meta_json"], meta_patch or {})
    tx.execute(
        """
        UPDATE payment_orders
        SET status = 'paid',
            provider_order_id = ?,
            provider_order_number = COALESCE(NULLIF(?, ''), provider_order_number),
            meta_json = ?,
            paid_at = COALESCE(paid_at, ?),
            updated_at = ?
        WHERE id = ?
        """,
        (clean_provider_order_id, str(provider_order_number or ""), new_meta, now, now, order_id),
    )
    if applied:
        tx.execute(
            """
            INSERT INTO notifications(user_id, kind, title, target_type, target_id, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (uid, "wallet", f"在线充值到账 +{credits}✦ 积分", "wallet", order_id, now),
        )
    refreshed = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
    return _serialize_order(refreshed), new_bal, applied


def _refund_order_tx(
    tx: Any,
    *,
    provider_order_id: str,
    order_id_hint: str = "",
    meta_patch: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, int | None, bool]:
    clean_poid = str(provider_order_id or "").strip()
    query = "SELECT * FROM payment_orders WHERE provider = 'lemonsqueezy' AND provider_order_id = ?"
    params: tuple[Any, ...] = (clean_poid,)
    if getattr(tx, "dialect", "") == "postgresql":
        query += " FOR UPDATE"
    order = tx.execute(query, params).fetchone() if clean_poid else None
    if not order and order_id_hint:
        q2 = "SELECT * FROM payment_orders WHERE id = ?"
        if getattr(tx, "dialect", "") == "postgresql":
            q2 += " FOR UPDATE"
        order = tx.execute(q2, (order_id_hint,)).fetchone()
    if not order:
        return None, None, False

    uid = int(order["user_id"])
    oid = str(order["id"])
    was_paid = str(order["status"] or "") == "paid"
    now = utc_now_iso()
    new_meta = _merge_meta_json(order["meta_json"], meta_patch or {})

    tx.execute(
        "UPDATE payment_orders SET status = 'refunded', meta_json = ?, updated_at = ? WHERE id = ?",
        (new_meta, now, oid),
    )
    applied = False
    new_bal: int | None = None
    if was_paid and clean_poid:
        credits = int(order["credits"])
        new_bal, applied = apply_wallet_delta(
            tx,
            uid,
            -credits,
            "recharge_refund",
            f"充值订单退款扣回 (-{credits} 积分)",
            event_key=f"ls_refund_{clean_poid}",
            ref_type="payment_order",
            ref_id=oid,
            allow_negative=True,
        )
        if applied:
            tx.execute(
                """
                INSERT INTO notifications(user_id, kind, title, target_type, target_id, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (uid, "wallet", f"充值订单已退款，扣回 {credits}✦ 积分", "wallet", oid, now),
            )
    refreshed = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (oid,)).fetchone()
    return _serialize_order(refreshed), new_bal, applied


def process_lemonsqueezy_webhook(
    db: Database,
    raw_body: bytes,
    signature_header: str,
    event_name_header: str = "",
) -> dict[str, Any]:
    cfg = load_payment_config()
    secret = str(cfg.get("webhook_secret") or "").strip()
    if not secret:
        raise ServiceError("Webhook 密钥尚未配置", status=503, code="webhook_not_configured")

    if not verify_webhook_signature(raw_body, signature_header, secret):
        logger.warning("Lemon Squeezy webhook rejected: invalid X-Signature")
        raise ServiceError("Webhook 签名校验失败", status=401, code="invalid_webhook_signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise ServiceError(f"Webhook JSON 解析失败：{exc}", status=400, code="invalid_webhook_json") from exc

    if not isinstance(payload, dict):
        raise ServiceError("Webhook 载荷格式无效", status=400, code="invalid_webhook_payload")

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}

    event_name = str(meta.get("event_name") or event_name_header or "").strip()
    provider_order_id = str(data.get("id") or "").strip()
    cfg_store_id = str(cfg.get("store_id") or "").strip()
    payload_store_id = str(attrs.get("store_id") or "").strip()
    if cfg_store_id and payload_store_id and payload_store_id != cfg_store_id:
        logger.warning("Lemon Squeezy webhook store_id mismatch: expected=%s got=%s", cfg_store_id, payload_store_id)
        raise ServiceError("Webhook 商店编号不匹配", status=400, code="store_mismatch")

    payload_test_mode = bool(attrs.get("test_mode", False))
    if not bool(cfg.get("test_mode", True)) and payload_test_mode:
        logger.warning("Lemon Squeezy webhook rejected test_mode order in live mode: poid=%s", provider_order_id)
        raise ServiceError("正式环境拒绝处理测试模式订单", status=400, code="test_mode_mismatch")

    webhook_id = str(meta.get("webhook_id") or "").strip()
    body_digest = hashlib.sha256(raw_body).hexdigest()[:24]
    event_key = f"{event_name}:{provider_order_id or 'none'}:{webhook_id or body_digest}"

    custom_data = meta.get("custom_data") if isinstance(meta.get("custom_data"), dict) else {}
    order_id = str(custom_data.get("order_id") or "").strip()
    custom_uid = str(custom_data.get("user_id") or "").strip()
    first_item = attrs.get("first_order_item") if isinstance(attrs.get("first_order_item"), dict) else {}
    variant_id = str(first_item.get("variant_id") or "").strip()
    order_number = str(attrs.get("order_number") or "").strip()
    order_status = str(attrs.get("status") or "").strip().lower()
    is_refunded = bool(attrs.get("refunded", False))

    now = utc_now_iso()
    with db.transaction() as tx:
        dup = tx.execute(
            "SELECT id FROM payment_webhook_events WHERE provider = 'lemonsqueezy' AND event_key = ?",
            (event_key,),
        ).fetchone()
        if dup:
            return {"ok": True, "duplicate": True, "event": event_name}

        tx.execute(
            """
            INSERT INTO payment_webhook_events (
                provider, event_key, event_name, provider_order_id, signature_valid, payload_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "lemonsqueezy",
                event_key,
                event_name or "unknown",
                provider_order_id,
                1,
                json.dumps(
                    {
                        "event_name": event_name,
                        "order_id": order_id,
                        "provider_order_id": provider_order_id,
                        "status": order_status,
                        "refunded": is_refunded,
                    },
                    ensure_ascii=False,
                ),
                "received",
                now,
            ),
        )

        if event_name == "order_created":
            if order_status != "paid" or is_refunded:
                tx.execute(
                    "UPDATE payment_webhook_events SET status = 'ignored_unpaid' WHERE provider = 'lemonsqueezy' AND event_key = ?",
                    (event_key,),
                )
                return {"ok": True, "ignored": True, "reason": "not_paid", "event": event_name}
            if not order_id:
                tx.execute(
                    "UPDATE payment_webhook_events SET status = 'ignored_no_order_id' WHERE provider = 'lemonsqueezy' AND event_key = ?",
                    (event_key,),
                )
                logger.warning("Lemon Squeezy webhook missing custom_data.order_id for poid=%s", provider_order_id)
                return {"ok": True, "ignored": True, "reason": "missing_order_id", "event": event_name}

            target_row = tx.execute("SELECT user_id FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
            if not target_row:
                tx.execute(
                    "UPDATE payment_webhook_events SET status = 'ignored_unknown_order' WHERE provider = 'lemonsqueezy' AND event_key = ?",
                    (event_key,),
                )
                logger.warning("Lemon Squeezy webhook referenced unknown order_id=%s poid=%s", order_id, provider_order_id)
                return {"ok": True, "ignored": True, "reason": "unknown_order", "event": event_name}
            if custom_uid and custom_uid != str(target_row["user_id"]):
                raise ServiceError("Webhook 用户标识不匹配", status=400, code="user_mismatch")

            settled_order, new_bal, applied = _settle_paid_order_tx(
                tx,
                order_id=order_id,
                provider_order_id=provider_order_id,
                provider_order_number=order_number,
                variant_id=variant_id,
                meta_patch={
                    "settledVia": "webhook",
                    "providerCurrency": str(attrs.get("currency") or ""),
                    "providerTotal": attrs.get("total"),
                },
            )
            tx.execute(
                "UPDATE payment_webhook_events SET status = 'processed' WHERE provider = 'lemonsqueezy' AND event_key = ?",
                (event_key,),
            )
            return {
                "ok": True,
                "event": event_name,
                "applied": applied,
                "order": settled_order,
                "credits": new_bal,
            }

        if event_name == "order_refunded" or (event_name == "order_updated" and is_refunded):
            refunded_order, new_bal, applied = _refund_order_tx(
                tx,
                provider_order_id=provider_order_id,
                order_id_hint=order_id,
                meta_patch={"refundedVia": "webhook"},
            )
            tx.execute(
                "UPDATE payment_webhook_events SET status = ? WHERE provider = 'lemonsqueezy' AND event_key = ?",
                ("processed" if refunded_order else "ignored_unknown_order", event_key),
            )
            return {
                "ok": True,
                "event": event_name,
                "applied": applied,
                "order": refunded_order,
                "credits": new_bal,
            }

        tx.execute(
            "UPDATE payment_webhook_events SET status = 'ignored_event' WHERE provider = 'lemonsqueezy' AND event_key = ?",
            (event_key,),
        )
        return {"ok": True, "ignored": True, "event": event_name}


def _parse_iso_utc(raw: str) -> _dt.datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def sync_payment_order_from_provider(
    db: Database,
    user: dict[str, Any],
    order_id: str,
    *,
    provider_order_id: str = "",
    provider_order_identifier: str = "",
) -> dict[str, Any]:
    uid = int(user["id"])
    clean_order_id = str(order_id or "").strip()
    conn = db.get_conn()
    order = conn.execute(
        "SELECT * FROM payment_orders WHERE id = ? AND user_id = ?",
        (clean_order_id, uid),
    ).fetchone()
    if not order:
        raise ServiceError("充值订单不存在", status=404, code="order_not_found")

    if str(order["status"] or "") == "paid":
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
        }

    cfg = load_payment_config()
    if not cfg.get("enabled"):
        raise ServiceError("在线充值尚未配置完成", status=503, code="billing_not_configured")

    clean_poid = str(provider_order_id or order["provider_order_id"] or "").strip()
    clean_ident = str(provider_order_identifier or "").strip()
    if not clean_poid or not clean_poid.isdigit() or not clean_ident:
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
            "pendingProof": True,
        }

    res = _lemon_api_request("GET", f"/v1/orders/{clean_poid}", cfg["api_key"])
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}

    ls_ident = str(attrs.get("identifier") or "").strip()
    if not ls_ident or not hmac.compare_digest(ls_ident, clean_ident):
        raise ServiceError("订单回执校验失败", status=403, code="order_identifier_mismatch")

    cfg_store_id = str(cfg.get("store_id") or "").strip()
    if str(attrs.get("store_id") or "").strip() != cfg_store_id:
        raise ServiceError("支付订单所属商店不匹配", status=400, code="store_mismatch")

    if not bool(cfg.get("test_mode", True)) and bool(attrs.get("test_mode", False)):
        raise ServiceError("正式环境不接受测试模式支付订单", status=400, code="test_mode_mismatch")

    ls_status = str(attrs.get("status") or "").strip().lower()
    if ls_status != "paid" or bool(attrs.get("refunded", False)):
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
            "providerStatus": ls_status,
        }

    first_item = attrs.get("first_order_item") if isinstance(attrs.get("first_order_item"), dict) else {}
    variant_id = str(first_item.get("variant_id") or "").strip()
    if variant_id != str(order["variant_id"] or "").strip():
        raise ServiceError("支付商品与待支付订单不一致", status=400, code="variant_mismatch")

    ls_created = _parse_iso_utc(str(attrs.get("created_at") or ""))
    local_created = _parse_iso_utc(str(order["created_at"] or ""))
    if ls_created and local_created and (ls_created + _dt.timedelta(seconds=60)) < local_created:
        raise ServiceError("支付订单时间早于充值单创建时间", status=400, code="order_timestamp_mismatch")

    with db.transaction() as tx:
        settled_order, new_bal, applied = _settle_paid_order_tx(
            tx,
            order_id=clean_order_id,
            provider_order_id=clean_poid,
            provider_order_number=str(attrs.get("order_number") or ""),
            variant_id=variant_id,
            meta_patch={
                "settledVia": "return_sync",
                "providerCurrency": str(attrs.get("currency") or ""),
                "providerTotal": attrs.get("total"),
            },
        )
    return {
        "ok": True,
        "order": settled_order,
        "credits": new_bal,
        "applied": applied,
    }
