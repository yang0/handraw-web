"""XorPay (and Creem) credit recharge checkout, webhook verification, and order sync."""
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

CREEM_LIVE_API_BASE = "https://api.creem.io"
CREEM_TEST_API_BASE = "https://test-api.creem.io"
CREEM_REDIRECT_SIGNED_KEYS = (
    "checkout_id",
    "order_id",
    "customer_id",
    "subscription_id",
    "product_id",
    "request_id",
)
MAX_WEBHOOK_BYTES = 512 * 1024


def get_billing_public_state() -> dict[str, Any]:
    return get_public_billing_summary()


def xorpay_sign(*args: str) -> str:
    """Compute XorPay MD5 signature (UTF-8 concatenated strings, 32-char lowercase hex)."""
    return hashlib.md5("".join(args).encode("utf-8")).hexdigest().lower()


def _serialize_order(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "provider": str(row["provider"] or "xorpay"),
        "packId": str(row["pack_id"]),
        "purpose": row.get("purpose","points"),
        "credits": int(row["credits"]),
        "amountCents": int(row["amount_cents"]),
        "currency": str(row["currency"] or "CNY"),
        "status": str(row["status"] or "pending"),
        "checkoutId": str(row["checkout_id"] or ""),
        "checkoutUrl": (f"/checkout/?orderId={urllib.parse.quote(str(row['id']))}" if row["provider"] == "xorpay" else str(row["checkout_url"] or "")) if row["status"] == "pending" else "",
        "providerOrderId": str(row["provider_order_id"] or ""),
        "providerOrderNumber": str(row["provider_order_number"] or ""),
        "testMode": bool(row["test_mode"]),
        "createdAt": str(row["created_at"] or ""),
        "updatedAt": str(row["updated_at"] or ""),
        "paidAt": str(row["paid_at"] or ""),
    }


def list_user_payment_orders(
    db: Database,
    user_id: int,
    limit: int = 20,
    *,
    page: int = 1,
    status_filter: str = "all",
    purpose_filter: str = "all",
) -> dict[str, Any]:
    if int(limit) < 1 or int(page) < 1:
        raise ServiceError("订单分页参数无效", status=400, code="invalid_pagination")
    safe_limit = min(50, int(limit))
    safe_page = int(page)
    clean_status = str(status_filter or "all").strip().lower()
    if clean_status not in ("all", "pending", "paid", "refund", "closed"):
        raise ServiceError("订单状态筛选无效", status=400, code="invalid_order_filter")
    clean_purpose = str(purpose_filter or "all").strip().lower()
    if clean_purpose not in ("all", "cash", "points"):
        raise ServiceError("订单用途筛选无效", status=400, code="invalid_order_filter")

    clauses = ["user_id = ?"]
    params: list[Any] = [int(user_id)]
    if clean_purpose in ("cash", "points"):
        clauses.append("purpose = ?")
        params.append(clean_purpose)
    if clean_status == "pending":
        clauses.append("status = 'pending'")
    elif clean_status == "paid":
        clauses.append("status IN ('paid', 'partially_refunded')")
    elif clean_status == "refund":
        clauses.append(
            "(status IN ('partially_refunded', 'refunded') OR EXISTS ("
            "SELECT 1 FROM billing_refund_requests r "
            "WHERE r.order_id = payment_orders.id AND r.user_id = payment_orders.user_id))"
        )
    elif clean_status == "closed":
        clauses.append("status IN ('failed', 'expired', 'cancelled')")

    where_sql = " AND ".join(clauses)
    offset = (safe_page - 1) * safe_limit
    conn = db.get_conn()
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM payment_orders WHERE {where_sql}",
            tuple(params),
        ).fetchone()[0]
    )
    total_pages = max(1, (total + safe_limit - 1) // safe_limit)
    rows = conn.execute(
        f"""
        SELECT * FROM payment_orders
        WHERE {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, safe_limit, offset),
    ).fetchall()

    orders: list[dict[str, Any]] = []
    if rows:
        order_ids = [str(r["id"]) for r in rows]
        ph = ",".join("?" for _ in order_ids)
        lot_params = (int(user_id), *order_ids)
        cash_map = {
            str(r["order_id"]): int(r["remaining_cents"] or 0)
            for r in conn.execute(
                f"SELECT order_id, remaining_cents FROM cash_lots WHERE user_id = ? AND order_id IN ({ph})",
                lot_params,
            ).fetchall()
        }
        point_map = {
            str(r["payment_order_id"]): int(r["units"] or 0)
            for r in conn.execute(
                f"SELECT payment_order_id, COALESCE(SUM(remaining_units), 0) AS units "
                f"FROM point_lots WHERE user_id = ? AND payment_order_id IN ({ph}) GROUP BY payment_order_id",
                lot_params,
            ).fetchall()
        }
        refund_map: dict[str, dict[str, Any]] = {}
        for r in conn.execute(
            f"SELECT id, order_id, status, amount_cents, units, reason, created_at "
            f"FROM billing_refund_requests WHERE user_id = ? AND order_id IN ({ph}) "
            f"ORDER BY created_at DESC, id DESC",
            lot_params,
        ).fetchall():
            oid = str(r["order_id"])
            if oid not in refund_map:
                created_raw = r["created_at"]
                refund_map[oid] = {
                    "id": str(r["id"]),
                    "status": str(r["status"] or "pending"),
                    "amountCents": int(r["amount_cents"] or 0),
                    "units": int(r["units"] or 0),
                    "reason": str(r["reason"] or ""),
                    "createdAt": created_raw.isoformat()
                    if hasattr(created_raw, "isoformat")
                    else str(created_raw or ""),
                }

        for r in rows:
            item = _serialize_order(r)
            if item["status"] in ("paid", "partially_refunded"):
                if item["purpose"] == "cash":
                    refundable_cents = int(cash_map.get(item["id"], 0))
                    refundable_units = 0
                else:
                    refundable_units = int(point_map.get(item["id"], 0))
                    refundable_cents = refundable_units * 10
            else:
                refundable_cents = 0
                refundable_units = 0
            item["refundableCents"] = refundable_cents
            item["refundableUnits"] = refundable_units
            item["refundRequest"] = refund_map.get(item["id"])
            orders.append(item)

    return {
        "ok": True,
        "orders": orders,
        "total": total,
        "page": safe_page,
        "pageSize": safe_limit,
        "totalPages": total_pages,
    }


def get_checkout_order(db: Database, user: dict[str, Any], order_id: str) -> dict[str, Any]:
    row = db.get_conn().execute('SELECT * FROM payment_orders WHERE id=? AND user_id=?', (order_id, user['id'])).fetchone()
    if not row:
        raise ServiceError('支付订单不存在', status=404, code='order_not_found')
    result = {'ok': True, 'order': _serialize_order(row)}
    meta = json.loads(row['meta_json'] or '{}')
    qr = str(meta.get('qr') or '') if row['status'] == 'pending' else ''
    if qr and len(qr) <= 4096 and qr.startswith(('https://', 'weixin://', 'alipays://')):
        cfg = load_payment_config()
        result['qr'] = qr
        result['qrImageUrl'] = str(cfg.get('api_base') or 'https://xorpay.com').rstrip('/') + '/qr?data=' + urllib.parse.quote(qr, safe='')
        result['paymentLink'] = qr if qr.startswith(('https://', 'alipays://')) else ''
    return result


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


def _xorpay_api_request(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    *,
    api_base: str = "https://xorpay.com",
    timeout: float = 20.0,
    retry: bool = True,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}{path}"
    data_bytes: bytes | None = None
    if method.upper() == "POST" and data is not None:
        data_bytes = urllib.parse.urlencode(data).encode("utf-8")
    elif method.upper() == "GET" and data:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(data)}"

    for attempt in range(2):
        req = urllib.request.Request(
            url,
            data=data_bytes,
            method=method.upper(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
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
                    raise RuntimeError("Invalid XorPay response payload")
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
                "XorPay API error: method=%s path=%s status=%s elapsed_ms=%.1f body_len=%d detail=%s",
                method.upper(),
                path,
                exc.code,
                elapsed_ms,
                len(err_bytes),
                sanitize_log_text(detail, 260) or "none",
            )
            if local_debug_stacks_enabled():
                trace_logger.warning(
                    "XorPay API error trace: method=%s path=%s status=%s\n%s",
                    method.upper(),
                    path,
                    exc.code,
                    "".join(traceback.format_stack(limit=12)),
                )
            raise ServiceError("支付网关请求失败，请稍后重试", status=502, code="payment_gateway_error") from exc
        except Exception as exc:
            elapsed_ms = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000
            if retry and attempt == 0 and isinstance(exc, (urllib.error.URLError, OSError, TimeoutError)):
                logger.warning(
                    "XorPay API transient transport error (retrying): method=%s path=%s elapsed_ms=%.1f err=%s",
                    method.upper(),
                    path,
                    elapsed_ms,
                    redact_sensitive_text(str(exc)),
                )
                continue
            logger.exception(
                "XorPay API transport failed: method=%s path=%s elapsed_ms=%.1f err=%s",
                method.upper(),
                path,
                elapsed_ms,
                redact_sensitive_text(str(exc)),
            )
            raise ServiceError("暂时无法连接支付网关，请稍后重试", status=502, code="payment_gateway_error") from exc
    raise ServiceError("暂时无法连接支付网关，请稍后重试", status=502, code="payment_gateway_error")


def _creem_api_base(api_key: str, test_mode: bool) -> str:
    if test_mode or str(api_key or "").startswith("creem_test_"):
        return CREEM_TEST_API_BASE
    return CREEM_LIVE_API_BASE


def _creem_api_request(
    method: str,
    path: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    *,
    test_mode: bool = True,
    timeout: float = 20.0,
) -> dict[str, Any]:
    url = f"{_creem_api_base(api_key, test_mode)}{path}"
    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    for attempt in range(2):
        req = urllib.request.Request(
            url,
            data=data_bytes,
            method=method.upper(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-api-key": api_key,
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
                    raise RuntimeError("Invalid Creem response payload")
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
                "Creem API error: method=%s path=%s status=%s elapsed_ms=%.1f body_len=%d detail=%s",
                method.upper(),
                path,
                exc.code,
                elapsed_ms,
                len(err_bytes),
                sanitize_log_text(detail, 260) or "none",
            )
            if local_debug_stacks_enabled():
                trace_logger.warning(
                    "Creem API error trace: method=%s path=%s status=%s\n%s",
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
                    "Creem API transient transport error (retrying): method=%s path=%s elapsed_ms=%.1f err=%s",
                    method.upper(),
                    path,
                    elapsed_ms,
                    redact_sensitive_text(str(exc)),
                )
                continue
            logger.exception(
                "Creem API transport failed: method=%s path=%s elapsed_ms=%.1f err=%s",
                method.upper(),
                path,
                elapsed_ms,
                redact_sensitive_text(str(exc)),
            )
            raise ServiceError("暂时无法连接支付网关，请稍后重试", status=502, code="payment_gateway_error") from exc
    raise ServiceError("暂时无法连接支付网关，请稍后重试", status=502, code="payment_gateway_error")


def _extract_entity_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or "").strip()
    return str(value or "").strip()


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    clean_sig = str(signature_header or "").strip().lower()
    if not clean_sig or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest().lower()
    return hmac.compare_digest(expected, clean_sig)


def verify_creem_redirect_signature(query_string: str, api_key: str) -> bool:
    """Verify Creem's redirect URL `signature` parameter."""
    clean_query = str(query_string or "").lstrip("?").strip()
    if not clean_query or not api_key:
        return False
    pairs = urllib.parse.parse_qsl(clean_query, keep_blank_values=False)
    signature = ""
    all_parts: list[str] = []
    creem_only_parts: list[str] = []
    for key, value in pairs:
        if key == "signature":
            signature = str(value or "").strip().lower()
            continue
        if value in (None, "", "null"):
            continue
        item = f"{key}={value}"
        all_parts.append(item)
        if key in CREEM_REDIRECT_SIGNED_KEYS:
            creem_only_parts.append(item)
    if not signature:
        return False

    candidates = []
    if all_parts:
        candidates.append("|".join([*all_parts, f"salt={api_key}"]))
    if creem_only_parts and creem_only_parts != all_parts:
        candidates.append("|".join([*creem_only_parts, f"salt={api_key}"]))
    for raw_data in candidates:
        expected = hashlib.sha256(raw_data.encode("utf-8")).hexdigest().lower()
        if hmac.compare_digest(signature, expected):
            return True
    return False


def _creem_compatible_origin(origin: str) -> str:
    parsed = urllib.parse.urlparse(origin)
    if (parsed.hostname or "").lower() in {"127.0.0.1", "::1"}:
        port_part = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://localhost{port_part}"
    return origin


def create_checkout_order(
    db: Database,
    user: dict[str, Any],
    pack_id: str,
    *,
    request_headers: Mapping[str, str],
    server_port: int | None = None,
    custom_amount_yuan: Any = None,
    custom_purpose: Any = None,
) -> dict[str, Any]:
    cfg = load_payment_config()
    if not cfg.get("enabled"):
        raise ServiceError("在线充值尚未配置完成", status=503, code="billing_not_configured")

    clean_pack_id = str(pack_id or "").strip()
    if custom_amount_yuan is not None or custom_purpose is not None:
        if clean_pack_id or custom_purpose not in ("cash", "points"):
            raise ServiceError("请选择一种充值用途", status=400, code="invalid_purchase_purpose")
        if type(custom_amount_yuan) is not int or not 1 <= custom_amount_yuan <= 10000:
            raise ServiceError("自定义金额须为 1–10000 元的整数", status=400, code="invalid_purchase_amount")
        if cfg.get("provider") != "xorpay" or cfg.get("currency") != "CNY":
            raise ServiceError("当前支付渠道暂不支持自定义金额", status=400, code="custom_purchase_unavailable")
        clean_pack_id = f"custom_{custom_purpose}_{custom_amount_yuan}"
        package = {
            "title": "生图余额充值" if custom_purpose == "cash" else "购买社区积分",
            "purpose": custom_purpose,
            "price_cents": custom_amount_yuan * 100,
            "credits": custom_amount_yuan * 10 if custom_purpose == "points" else 0,
        }
    else:
        package = next((p for p in cfg["active_packages"] if p["id"] == clean_pack_id), None)
    if not package:
        raise ServiceError("无效的购买档位", status=400, code="invalid_package")

    provider = str(cfg.get("provider") or "xorpay").strip().lower()
    uid = int(user["id"])
    order_id = f"ord_{uuid.uuid4().hex}"
    now = utc_now_iso()
    main_origin = resolve_main_portal_origin(request_headers, server_port=server_port)
    test_mode = bool(cfg.get("test_mode", False))

    if provider == "xorpay":
        price_cents = int(package["price_cents"])
        price_str = f"{price_cents / 100:.2f}"
        pay_type = str(cfg.get("pay_type") or "alipay").strip().lower()
        order_name = f"Handraw - {package['title']}"
        notify_url = str(cfg.get("notify_url") or f"{main_origin}/api/webhooks/xorpay").strip()
        aid = str(cfg["aid"]).strip()
        app_secret = str(cfg["app_secret"]).strip()
        api_base = str(cfg.get("api_base") or "https://xorpay.com").strip().rstrip("/")

        sign = xorpay_sign(order_name, pay_type, price_str, order_id, notify_url, app_secret)
        # The cashier endpoint is a separate WeChat JSAPI creation flow. Show
        # the QR returned by /pay, rather than submitting an order there again.
        cashier_url = f"{main_origin}/checkout/?orderId=" + urllib.parse.quote(order_id)

        with db.transaction() as tx:
            tx.execute('SELECT pg_advisory_xact_lock(254, ?)', (uid,))
            cutoff = (_dt.datetime.now(_dt.timezone.utc)-_dt.timedelta(minutes=15)).isoformat().replace('+00:00','Z')
            recent = tx.execute("SELECT * FROM payment_orders WHERE user_id=? AND provider='xorpay' AND pack_id=? AND amount_cents=? AND purpose=? AND currency=? AND test_mode=? AND status='pending' AND created_at>=? ORDER BY created_at DESC LIMIT 1", (uid, clean_pack_id, price_cents, str(package.get('purpose') or 'points'), str(cfg['currency']), int(test_mode), cutoff)).fetchone()
            if recent:
                serialized = _serialize_order(recent)
                return {'ok': True, 'order': serialized, 'checkoutUrl': serialized['checkoutUrl']}
            tx.execute(
                """
                INSERT INTO payment_orders (
                    id, user_id, provider, pack_id, variant_id, credits, amount_cents, currency, purpose,
                    status, checkout_id, checkout_url, provider_order_id, provider_order_number,
                    test_mode, meta_json, created_at, updated_at, paid_at
                ) VALUES (?, ?, 'xorpay', ?, ?, ?, ?, ?, ?, 'pending', '', ?, '', '', ?, ?, ?, ?, NULL)
                """,
                (
                    order_id,
                    uid,
                    clean_pack_id,
                    clean_pack_id,
                    int(package["credits"]),
                    price_cents,
                    str(cfg["currency"]),
                    str(package.get("purpose") or "points"),
                    cashier_url,
                    1 if test_mode else 0,
                    json.dumps(
                        {
                            "packTitle": package["title"],
                            "payType": pay_type,
                            "priceStr": price_str,
                            "cashierUrl": cashier_url,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    now,
                ),
            )

        pay_payload = {
            "name": order_name,
            "pay_type": pay_type,
            "price": price_str,
            "order_id": order_id,
            "notify_url": notify_url,
            "sign": sign,
        }

        try:
            res = _xorpay_api_request("POST", f"/api/pay/{aid}", pay_payload, api_base=api_base, retry=False)
        except Exception:
            with db.transaction() as tx:
                tx.execute(
                    "UPDATE payment_orders SET meta_json = (meta_json::jsonb || '{\"creationUnknown\":true}'::jsonb)::text, updated_at = ? WHERE id = ? AND status = 'pending'",
                    (utc_now_iso(), order_id),
                )
            raise

        res_status = str(res.get("status") or "").strip().lower()
        if res_status == "fee_error":
            with db.transaction() as tx:
                tx.execute(
                    "UPDATE payment_orders SET status = 'failed', updated_at = ? WHERE id = ? AND status = 'pending'",
                    (utc_now_iso(), order_id),
                )
            raise ServiceError("XorPay 平台手续费余额不足，请前往商户后台 xorpay.com 充值平台手续费", status=502, code="xorpay_fee_error")

        if res_status in ('order_exist', 'order_payed'):
            result = sync_payment_order_from_provider(db, user, order_id)
            result['checkoutUrl'] = cashier_url
            return result
        if res_status != "ok":
            with db.transaction() as tx:
                tx.execute(
                    "UPDATE payment_orders SET status = 'failed', updated_at = ? WHERE id = ? AND status = 'pending'",
                    (utc_now_iso(), order_id),
                )
            msg = str(res.get("msg") or res.get("status") or "未知网关错误")
            raise ServiceError(f"支付网关下单失败：{msg}", status=502, code="payment_gateway_error")

        info = res.get("info") if isinstance(res.get("info"), dict) else {}
        aoid = str(res.get("aoid") or info.get("aoid") or "").strip()
        qr = str(info.get("qr") or "").strip()

        updated_at = utc_now_iso()
        with db.transaction() as tx:
            tx.execute(
                """
                UPDATE payment_orders
                SET checkout_id = ?, checkout_url = ?, meta_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    aoid,
                    cashier_url,
                    json.dumps(
                        {
                            "packTitle": package["title"],
                            "payType": pay_type,
                            "priceStr": price_str,
                            "cashierUrl": cashier_url,
                            "aoid": aoid,
                            "qr": qr,
                        },
                        ensure_ascii=False,
                    ),
                    updated_at,
                    order_id,
                ),
            )
            row = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()

        return {
            "ok": True,
            "order": _serialize_order(row),
            "checkoutUrl": cashier_url,
            "qr": qr,
        }

    # Creem provider branch (backward compatibility)
    creem_origin = _creem_compatible_origin(main_origin)
    redirect_url = f"{creem_origin}/?view=wallet&order={urllib.parse.quote(order_id)}"
    product_id = str(package.get("product_id") or "")

    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO payment_orders (
                id, user_id, provider, pack_id, variant_id, credits, amount_cents, currency, purpose,
                status, checkout_id, checkout_url, provider_order_id, provider_order_number,
                test_mode, meta_json, created_at, updated_at, paid_at
            ) VALUES (?, ?, 'creem', ?, ?, ?, ?, ?, ?, 'pending', '', '', '', '', ?, ?, ?, ?, NULL)
            """,
            (
                order_id,
                uid,
                clean_pack_id,
                product_id,
                int(package["credits"]),
                int(package["price_cents"]),
                str(cfg["currency"]),
                    str(package.get("purpose") or "points"),
                1 if test_mode else 0,
                json.dumps({"packTitle": package["title"], "redirectBase": creem_origin}, ensure_ascii=False),
                now,
                now,
            ),
        )

    checkout_payload: dict[str, Any] = {
        "product_id": product_id,
        "request_id": order_id,
        "units": 1,
        "success_url": redirect_url,
        "metadata": {
            "order_id": order_id,
            "user_id": str(uid),
            "pack_id": clean_pack_id,
        },
    }
    user_email = str(user.get("email") or "").strip()
    if user_email and "@" in user_email and not user_email.endswith(".invalid"):
        checkout_payload["customer"] = {"email": user_email}

    try:
        res = _creem_api_request(
            "POST",
            "/v1/checkouts",
            cfg["api_key"],
            checkout_payload,
            test_mode=test_mode,
        )
    except Exception:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE payment_orders SET status = 'failed', updated_at = ? WHERE id = ? AND status = 'pending'",
                (utc_now_iso(), order_id),
            )
        raise

    checkout_id = str(res.get("id") or "").strip()
    checkout_url = str(res.get("checkout_url") or "").strip()
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


def _merge_meta_json(existing_raw: Any, patch: dict[str, Any]) -> str:
    try:
        base = json.loads(existing_raw) if isinstance(existing_raw, str) and existing_raw else {}
    except Exception:
        base = {}
    if not isinstance(base, dict):
        base = {}
    base.update(patch)
    return json.dumps(base, ensure_ascii=False)


def _assert_live_mode_allowed(cfg_test_mode: bool, payload_mode: str) -> None:
    clean_mode = str(payload_mode or "").strip().lower()
    if not cfg_test_mode and clean_mode in {"test", "sandbox", "local"}:
        raise ServiceError("正式环境不接受测试模式支付订单", status=400, code="test_mode_mismatch")


def _assert_creem_order_matches_local(
    local_order: Any,
    *,
    checkout_id: str,
    product_id: str,
    provider_order_obj: Mapping[str, Any],
) -> None:
    expected_checkout = str(local_order["checkout_id"] or "").strip()
    if expected_checkout and checkout_id and expected_checkout != checkout_id:
        raise ServiceError("收银台会话标识与订单不匹配", status=400, code="checkout_id_mismatch")

    expected_product = str(local_order["variant_id"] or "").strip()
    if product_id and expected_product and product_id != expected_product:
        raise ServiceError("支付商品规格与订单不匹配", status=400, code="product_mismatch")

    expected_currency = str(local_order["currency"] or "").strip().upper()
    got_currency = str(provider_order_obj.get("currency") or "").strip().upper()
    if expected_currency and got_currency and got_currency != expected_currency:
        raise ServiceError("支付币种与订单不匹配", status=400, code="currency_mismatch")

    expected_cents = int(local_order["amount_cents"] or 0)
    raw_paid = provider_order_obj.get("amount_paid")
    raw_amount = provider_order_obj.get("amount")
    paid_val = raw_paid if isinstance(raw_paid, (int, float)) else raw_amount
    if isinstance(paid_val, (int, float)) and expected_cents > 0 and int(round(paid_val)) < expected_cents:
        base_val = raw_amount if isinstance(raw_amount, (int, float)) else paid_val
        if int(round(base_val)) < expected_cents:
            raise ServiceError("支付金额低于订单应收金额", status=400, code="amount_mismatch")


def _settle_paid_order_tx(
    tx: Any,
    *,
    order_id: str,
    provider_order_id: str,
    provider_order_number: str = "",
    product_id: str = "",
    provider: str = "xorpay",
    meta_patch: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int, bool]:
    owner=tx.execute("SELECT user_id FROM payment_orders WHERE id=?",(order_id,)).fetchone()
    if owner:
        from .economy import lock_user
        lock_user(tx,owner[0])
    query = "SELECT * FROM payment_orders WHERE id = ?"
    query += " FOR UPDATE"
    order = tx.execute(query, (order_id,)).fetchone()
    if not order:
        raise ServiceError("充值订单不存在", status=404, code="order_not_found")

    clean_provider = str(order["provider"] or provider or "xorpay").strip().lower()
    clean_provider_order_id = str(provider_order_id or "").strip()
    if not clean_provider_order_id:
        raise ServiceError("缺少上游订单号", status=400, code="missing_provider_order_id")

    conflict = tx.execute(
        "SELECT id FROM payment_orders WHERE provider = ? AND provider_order_id = ? AND id <> ?",
        (clean_provider, clean_provider_order_id, order_id),
    ).fetchone()
    if conflict:
        raise ServiceError("该支付单号已绑定其他充值订单", status=409, code="provider_order_conflict")

    expected_product = str(order["variant_id"] or "").strip()
    if product_id and expected_product and str(product_id).strip() != expected_product:
        raise ServiceError("支付商品规格与订单不匹配", status=400, code="product_mismatch")

    uid = int(order["user_id"])
    cur_status = str(order["status"] or "")
    if cur_status == "refunded":
        raise ServiceError("该订单已退款，无法再次入账", status=409, code="order_already_refunded")

    if cur_status in ("paid","partially_refunded"):
        existing_poid = str(order["provider_order_id"] or "").strip()
        if existing_poid and existing_poid != clean_provider_order_id:
            raise ServiceError("该订单已由其他支付单完成入账", status=409, code="order_conflict")
        bal_row = tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        bal = int(bal_row["balance"]) if bal_row else 0
        if order.get("purpose")=="cash":
            from .economy import cash
            bal=cash(tx,uid)["balanceCents"]
        return _serialize_order(order), bal, False

    credits = int(order["credits"])
    now = utc_now_iso()
    event_prefix = clean_provider
    if order.get("purpose")=="cash":
        from .economy import cash_delta
        state,applied=cash_delta(tx,uid,int(order["amount_cents"]),0,"recharge",f"payment:{order_id}",ref=order_id)
        unspent=max(0,state["balanceCents"])-max(0,state["balanceCents"]-int(order["amount_cents"]))
        tx.execute("INSERT INTO cash_lots(order_id,user_id,remaining_cents) VALUES(?,?,?) ON CONFLICT DO NOTHING",(order_id,uid,unspent))
        new_bal=state["balanceCents"]
    else:
        new_bal, applied = apply_wallet_delta(
            tx,
            uid,
            credits,
            "recharge",
            f"在线充值积分到账 (+{credits} 积分)",
            event_key=f"{event_prefix}_order_{clean_provider_order_id}",
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
    provider: str = "xorpay",
    provider_order_id: str,
    order_id_hint: str = "",
    meta_patch: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, int | None, bool]:
    clean_poid = str(provider_order_id or "").strip()
    candidate=tx.execute("SELECT user_id FROM payment_orders WHERE (provider=? AND provider_order_id=? AND provider_order_id<>'') OR id=? LIMIT 1",(provider,clean_poid,order_id_hint)).fetchone()
    if candidate:
        from .economy import lock_user
        lock_user(tx,candidate[0])
    query = "SELECT * FROM payment_orders WHERE provider = ? AND provider_order_id = ?"
    params: tuple[Any, ...] = (provider, clean_poid)
    query += " FOR UPDATE"
    order = tx.execute(query, params).fetchone() if clean_poid else None
    if not order and order_id_hint:
        q2 = "SELECT * FROM payment_orders WHERE id = ?"
        q2 += " FOR UPDATE"
        order = tx.execute(q2, (order_id_hint,)).fetchone()
    if not order:
        return None, None, False

    oid = str(order["id"])
    effective_poid = clean_poid or str(order["provider_order_id"] or "").strip()
    was_paid = str(order["status"] or "") in ("paid","partially_refunded")
    now = utc_now_iso()
    new_meta = _merge_meta_json(order["meta_json"], meta_patch or {})

    tx.execute(
        "UPDATE payment_orders SET status = 'refunded', meta_json = ?, updated_at = ? WHERE id = ?",
        (new_meta, now, oid),
    )
    applied = False
    new_bal: int | None = None
    if was_paid and effective_poid:
        from .billing_refunds import apply_provider_refund
        new_bal,applied=apply_provider_refund(tx,order,effective_poid)
    refreshed = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (oid,)).fetchone()
    return _serialize_order(refreshed), new_bal, applied


def process_xorpay_webhook(
    db: Database,
    raw_body_or_form: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Process XorPay webhook callback (application/x-www-form-urlencoded)."""
    cfg = load_payment_config()
    secret = str(cfg.get("app_secret") or "").strip()
    if not secret:
        raise ServiceError("XorPay app_secret 尚未配置", status=503, code="webhook_not_configured")

    if isinstance(raw_body_or_form, (bytes, bytearray)):
        parsed = urllib.parse.parse_qs(raw_body_or_form.decode("utf-8", errors="replace"), keep_blank_values=True)
        form_dict: dict[str, str] = {k: v[0] if v else "" for k, v in parsed.items()}
    elif isinstance(raw_body_or_form, Mapping):
        form_dict = {str(k): str(v or "") for k, v in raw_body_or_form.items()}
    else:
        raise ServiceError("无效的 Webhook 载荷格式", status=400, code="invalid_webhook_payload")

    aoid = form_dict.get("aoid", "").strip()
    order_id = form_dict.get("order_id", "").strip()
    pay_price = form_dict.get("pay_price", "").strip()
    pay_time = form_dict.get("pay_time", "").strip()
    sign = form_dict.get("sign", "").strip().lower()
    more = form_dict.get("more", "").strip()
    detail_raw = form_dict.get("detail", "").strip()

    if not aoid or not order_id or not pay_price or not pay_time or not sign:
        raise ServiceError("缺少必要的支付回调字段", status=400, code="missing_webhook_fields")

    expected_sign = xorpay_sign(aoid, order_id, pay_price, pay_time, secret)
    if not hmac.compare_digest(expected_sign, sign):
        logger.warning(
            "XorPay webhook signature mismatch: aoid=%s order_id=%s got=%s expected=%s",
            aoid,
            order_id,
            sign,
            expected_sign,
        )
        raise ServiceError("Webhook 签名校验失败", status=401, code="invalid_webhook_signature")

    try:
        detail_obj = json.loads(detail_raw) if detail_raw else {}
    except Exception:
        detail_obj = {}

    event_key = f"xorpay:{order_id}:{aoid}"
    now = utc_now_iso()

    with db.transaction() as tx:
        dup = tx.execute(
            "SELECT id FROM payment_webhook_events WHERE provider = 'xorpay' AND event_key = ?",
            (event_key,),
        ).fetchone()
        if dup:
            return {"ok": True, "duplicate": True, "event": "pay", "response_body": "ok"}

        tx.execute(
            """
            INSERT INTO payment_webhook_events (
                provider, event_key, event_name, provider_order_id, signature_valid, payload_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "xorpay",
                event_key,
                "pay",
                aoid,
                1,
                json.dumps(
                    {
                        "aoid": aoid,
                        "order_id": order_id,
                        "pay_price": pay_price,
                        "pay_time": pay_time,
                        "more": more,
                        "detail": detail_obj,
                    },
                    ensure_ascii=False,
                ),
                "received",
                now,
            ),
        )

        target_row = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
        if not target_row:
            tx.execute(
                "UPDATE payment_webhook_events SET status = 'ignored_unknown_order' WHERE provider = 'xorpay' AND event_key = ?",
                (event_key,),
            )
            logger.warning("XorPay webhook unknown order: order_id=%s aoid=%s", order_id, aoid)
            return {"ok": True, "ignored": True, "reason": "unknown_order", "response_body": "ok"}

        try:
            paid_cents = int(round(float(pay_price) * 100))
        except (ValueError, TypeError):
            paid_cents = 0

        expected_cents = int(target_row["amount_cents"] or 0)
        if paid_cents < expected_cents:
            tx.execute(
                "UPDATE payment_webhook_events SET status = 'amount_mismatch' WHERE provider = 'xorpay' AND event_key = ?",
                (event_key,),
            )
            raise ServiceError("支付金额低于订单应收金额", status=400, code="amount_mismatch")

        provider_txn = str(detail_obj.get("transaction_id") or aoid).strip()
        settled_order, new_bal, applied = _settle_paid_order_tx(
            tx,
            order_id=order_id,
            provider_order_id=aoid,
            provider_order_number=provider_txn,
            product_id=str(target_row["variant_id"] or ""),
            provider="xorpay",
            meta_patch={
                "settledVia": "webhook",
                "aoid": aoid,
                "payPrice": pay_price,
                "payTime": pay_time,
                "more": more,
                "detail": detail_obj,
            },
        )
        tx.execute(
            "UPDATE payment_webhook_events SET status = 'processed' WHERE provider = 'xorpay' AND event_key = ?",
            (event_key,),
        )
        return {
            "ok": True,
            "event": "pay",
            "applied": applied,
            "order": settled_order,
            **({"balanceCents":new_bal} if settled_order and settled_order.get("purpose")=="cash" else {"credits":new_bal}),
            "response_body": "ok",
        }


def _extract_creem_order_id_hint(obj: Mapping[str, Any]) -> str:
    req_id = str(obj.get("request_id") or "").strip()
    if req_id:
        return req_id
    metadata = obj.get("metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("order_id") or "").strip()
    return ""


def process_creem_webhook(
    db: Database,
    raw_body: bytes,
    signature_header: str,
) -> dict[str, Any]:
    cfg = load_payment_config()
    secret = str(cfg.get("webhook_secret") or "").strip()
    if not secret:
        raise ServiceError("Webhook 密钥尚未配置", status=503, code="webhook_not_configured")

    if not verify_webhook_signature(raw_body, signature_header, secret):
        logger.warning("Creem webhook rejected: invalid creem-signature")
        raise ServiceError("Webhook 签名校验失败", status=401, code="invalid_webhook_signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise ServiceError(f"Webhook JSON 解析失败：{exc}", status=400, code="invalid_webhook_json") from exc

    if not isinstance(payload, dict):
        raise ServiceError("Webhook 载荷格式无效", status=400, code="invalid_webhook_payload")

    event_type = str(payload.get("eventType") or "").strip()
    webhook_event_id = str(payload.get("id") or "").strip()
    obj = payload.get("object") if isinstance(payload.get("object"), dict) else {}

    order_obj = obj.get("order") if isinstance(obj.get("order"), dict) else {}
    checkout_obj = obj.get("checkout") if isinstance(obj.get("checkout"), dict) else (obj if event_type == "checkout.completed" else {})
    txn_obj = obj.get("transaction") if isinstance(obj.get("transaction"), dict) else {}

    payload_mode = str(
        obj.get("mode") or order_obj.get("mode") or checkout_obj.get("mode") or ""
    ).strip()
    _assert_live_mode_allowed(bool(cfg.get("test_mode", True)), payload_mode)

    provider_order_id = (
        _extract_entity_id(order_obj)
        or _extract_entity_id(txn_obj.get("order") if txn_obj else "")
    )
    checkout_id = _extract_entity_id(checkout_obj) or _extract_entity_id(obj if obj.get("object") == "checkout" else "")
    body_digest = hashlib.sha256(raw_body).hexdigest()[:24]
    event_key = f"{event_type}:{provider_order_id or checkout_id or 'none'}:{webhook_event_id or body_digest}"

    now = utc_now_iso()
    with db.transaction() as tx:
        dup = tx.execute(
            "SELECT id FROM payment_webhook_events WHERE provider = 'creem' AND event_key = ?",
            (event_key,),
        ).fetchone()
        if dup:
            return {"ok": True, "duplicate": True, "event": event_type}

        tx.execute(
            """
            INSERT INTO payment_webhook_events (
                provider, event_key, event_name, provider_order_id, signature_valid, payload_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "creem",
                event_key,
                event_type or "unknown",
                provider_order_id,
                1,
                json.dumps(
                    {
                        "event_type": event_type,
                        "webhook_event_id": webhook_event_id,
                        "checkout_id": checkout_id,
                        "provider_order_id": provider_order_id,
                        "mode": payload_mode,
                    },
                    ensure_ascii=False,
                ),
                "received",
                now,
            ),
        )

        if event_type == "checkout.completed":
            checkout_status = str(obj.get("status") or "").strip().lower()
            order_status = str(order_obj.get("status") or "").strip().lower()
            if (checkout_status and checkout_status != "completed") or (order_status and order_status != "paid"):
                tx.execute(
                    "UPDATE payment_webhook_events SET status = 'ignored_unpaid' WHERE provider = 'creem' AND event_key = ?",
                    (event_key,),
                )
                return {"ok": True, "ignored": True, "reason": "not_paid", "event": event_type}

            local_order_id = _extract_creem_order_id_hint(obj)
            target_row = None
            if local_order_id:
                target_row = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (local_order_id,)).fetchone()
            elif checkout_id:
                target_row = tx.execute(
                    "SELECT * FROM payment_orders WHERE provider = 'creem' AND checkout_id = ?",
                    (checkout_id,),
                ).fetchone()
                if target_row:
                    local_order_id = str(target_row["id"])

            if not local_order_id or not target_row:
                tx.execute(
                    "UPDATE payment_webhook_events SET status = 'ignored_unknown_order' WHERE provider = 'creem' AND event_key = ?",
                    (event_key,),
                )
                logger.warning(
                    "Creem webhook missing or unknown order: req=%s chk=%s poid=%s",
                    local_order_id,
                    checkout_id,
                    provider_order_id,
                )
                return {"ok": True, "ignored": True, "reason": "unknown_order", "event": event_type}

            metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            custom_uid = str(metadata.get("user_id") or "").strip()
            if custom_uid and custom_uid != str(target_row["user_id"]):
                raise ServiceError("Webhook 用户标识不匹配", status=400, code="user_mismatch")

            product_id = _extract_entity_id(obj.get("product") or order_obj.get("product"))
            _assert_creem_order_matches_local(
                target_row,
                checkout_id=checkout_id,
                product_id=product_id,
                provider_order_obj=order_obj,
            )

            settled_order, new_bal, applied = _settle_paid_order_tx(
                tx,
                order_id=local_order_id,
                provider_order_id=provider_order_id or f"chk_{checkout_id}",
                provider_order_number=str(order_obj.get("transaction") or provider_order_id),
                product_id=product_id,
                provider="creem",
                meta_patch={
                    "settledVia": "webhook",
                    "creemEventId": webhook_event_id,
                    "providerCurrency": str(order_obj.get("currency") or ""),
                    "providerAmount": order_obj.get("amount"),
                    "providerAmountPaid": order_obj.get("amount_paid"),
                    "providerTransaction": str(order_obj.get("transaction") or ""),
                },
            )
            tx.execute(
                "UPDATE payment_webhook_events SET status = 'processed' WHERE provider = 'creem' AND event_key = ?",
                (event_key,),
            )
            return {
                "ok": True,
                "event": event_type,
                "applied": applied,
                "order": settled_order,
                **({"balanceCents":new_bal} if settled_order and settled_order.get("purpose")=="cash" else {"credits":new_bal}),
            }

        if event_type == "refund.created":
            refund_status = str(obj.get("status") or "").strip().lower()
            if refund_status and refund_status not in {"succeeded", "refunded", "completed"}:
                tx.execute(
                    "UPDATE payment_webhook_events SET status = 'ignored_refund_status' WHERE provider = 'creem' AND event_key = ?",
                    (event_key,),
                )
                return {"ok": True, "ignored": True, "reason": refund_status, "event": event_type}

            local_order_hint = _extract_creem_order_id_hint(checkout_obj) if isinstance(checkout_obj, dict) else ""
            if not local_order_hint and isinstance(obj.get("metadata"), dict):
                local_order_hint = str(obj["metadata"].get("order_id") or "").strip()

            refunded_order, new_bal, applied = _refund_order_tx(
                tx,
                provider="creem",
                provider_order_id=provider_order_id,
                order_id_hint=local_order_hint,
                meta_patch={
                    "refundedVia": "webhook",
                    "refundId": str(obj.get("id") or ""),
                    "refundReason": str(obj.get("reason") or ""),
                    "refundAmount": obj.get("refund_amount"),
                    "refundCurrency": str(obj.get("refund_currency") or ""),
                },
            )
            tx.execute(
                "UPDATE payment_webhook_events SET status = ? WHERE provider = 'creem' AND event_key = ?",
                ("processed" if refunded_order else "ignored_unknown_order", event_key),
            )
            return {
                "ok": True,
                "event": event_type,
                "applied": applied,
                "order": refunded_order,
                **({"balanceCents":new_bal} if refunded_order and refunded_order.get("purpose")=="cash" else {"credits":new_bal}),
            }

        tx.execute(
            "UPDATE payment_webhook_events SET status = 'ignored_event' WHERE provider = 'creem' AND event_key = ?",
            (event_key,),
        )
        return {"ok": True, "ignored": True, "event": event_type}


def sync_payment_order_from_provider(
    db: Database,
    user: dict[str, Any],
    order_id: str,
    *,
    checkout_id: str = "",
    provider_order_id: str = "",
    redirect_query: str = "",
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

    cur_status = str(order["status"] or "")
    if cur_status == "paid":
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
        }
    if cur_status == "refunded":
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
        }

    cfg = load_payment_config()
    if not cfg.get("enabled"):
        raise ServiceError("在线充值尚未配置完成", status=503, code="billing_not_configured")

    provider = str(order["provider"] or cfg.get("provider") or "xorpay").strip().lower()

    if provider == "xorpay":
        aid = str(cfg["aid"]).strip()
        app_secret = str(cfg["app_secret"]).strip()
        api_base = str(cfg.get("api_base") or "https://xorpay.com").strip().rstrip("/")
        query_sign = xorpay_sign(clean_order_id, app_secret)

        res = _xorpay_api_request(
            "GET",
            f"/api/query2/{aid}?order_id={urllib.parse.quote(clean_order_id)}&sign={query_sign}",
            api_base=api_base,
        )

        xorpay_status = str(res.get("status") or "").strip().lower()
        if xorpay_status in ("payed", "success"):
            aoid = str(res.get("aoid") or (res.get("info") or {}).get("aoid") or order["checkout_id"] or f"xor_{clean_order_id}").strip()
            raw_price = res.get("pay_price") or res.get("price") or (res.get("info") or {}).get("price")
            if raw_price is not None:
                try:
                    paid_cents = int(round(float(raw_price) * 100))
                    if paid_cents < int(order["amount_cents"] or 0):
                        raise ServiceError("支付金额低于订单应收金额", status=400, code="amount_mismatch")
                except (ValueError, TypeError):
                    pass

            detail = res.get("detail") if isinstance(res.get("detail"), dict) else {}
            provider_txn = str(detail.get("transaction_id") or res.get("transaction_id") or aoid).strip()

            with db.transaction() as tx:
                settled_order, new_bal, applied = _settle_paid_order_tx(
                    tx,
                    order_id=clean_order_id,
                    provider_order_id=aoid,
                    provider_order_number=provider_txn,
                    product_id=str(order["variant_id"] or ""),
                    provider="xorpay",
                    meta_patch={
                        "settledVia": "return_sync",
                        "xorpayStatus": xorpay_status,
                        "payPrice": raw_price,
                        "detail": detail,
                    },
                )
            return {
                "ok": True,
                "order": settled_order,
                **({"balanceCents":new_bal} if settled_order and settled_order.get("purpose")=="cash" else {"credits":new_bal}),
                "applied": applied,
            }

        if xorpay_status == "expire":
            now = utc_now_iso()
            with db.transaction() as tx:
                tx.execute(
                    "UPDATE payment_orders SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'pending'",
                    (now, clean_order_id),
                )
                refreshed = tx.execute("SELECT * FROM payment_orders WHERE id = ?", (clean_order_id,)).fetchone()
            return {
                "ok": True,
                "order": _serialize_order(refreshed),
                "credits": _wallet_balance(conn, uid),
                "applied": False,
                "providerStatus": "expire",
            }

        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
            "providerStatus": xorpay_status or "pending",
        }

    # Creem branch
    stored_checkout_id = str(order["checkout_id"] or "").strip()
    supplied_checkout_id = str(checkout_id or "").strip()
    if supplied_checkout_id and stored_checkout_id and supplied_checkout_id != stored_checkout_id:
        raise ServiceError("收银台会话标识校验失败", status=403, code="checkout_id_mismatch")

    clean_redirect_query = str(redirect_query or "").strip()
    if clean_redirect_query and "signature=" in clean_redirect_query:
        if not verify_creem_redirect_signature(clean_redirect_query, cfg["api_key"]):
            raise ServiceError("回跳签名校验失败", status=403, code="redirect_signature_mismatch")

    if not stored_checkout_id:
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
            "pendingProof": True,
        }

    test_mode = bool(cfg.get("test_mode", True))
    res = _creem_api_request(
        "GET",
        f"/v1/checkouts?checkout_id={urllib.parse.quote(stored_checkout_id)}",
        cfg["api_key"],
        test_mode=test_mode,
    )
    order_obj = res.get("order") if isinstance(res.get("order"), dict) else {}
    payload_mode = str(res.get("mode") or order_obj.get("mode") or "").strip()
    _assert_live_mode_allowed(test_mode, payload_mode)

    creem_status = str(res.get("status") or "").strip().lower()
    creem_order_status = str(order_obj.get("status") or "").strip().lower()
    if creem_status != "completed" or (creem_order_status and creem_order_status != "paid"):
        return {
            "ok": True,
            "order": _serialize_order(order),
            "credits": _wallet_balance(conn, uid),
            "applied": False,
            "providerStatus": creem_status or "pending",
        }

    hinted_order_id = _extract_creem_order_id_hint(res)
    if hinted_order_id and hinted_order_id != clean_order_id:
        raise ServiceError("上游收银台关联订单不匹配", status=403, code="order_reference_mismatch")

    remote_poid = _extract_entity_id(order_obj)
    supplied_poid = str(provider_order_id or "").strip()
    if supplied_poid and remote_poid and supplied_poid != remote_poid:
        raise ServiceError("订单回执校验失败", status=403, code="provider_order_mismatch")

    product_id = _extract_entity_id(res.get("product") or order_obj.get("product"))
    _assert_creem_order_matches_local(
        order,
        checkout_id=str(res.get("id") or stored_checkout_id).strip(),
        product_id=product_id,
        provider_order_obj=order_obj,
    )

    with db.transaction() as tx:
        settled_order, new_bal, applied = _settle_paid_order_tx(
            tx,
            order_id=clean_order_id,
            provider_order_id=remote_poid or f"chk_{stored_checkout_id}",
            provider_order_number=str(order_obj.get("transaction") or remote_poid),
            product_id=product_id,
            provider="creem",
            meta_patch={
                "settledVia": "return_sync",
                "providerCurrency": str(order_obj.get("currency") or ""),
                "providerAmount": order_obj.get("amount"),
                "providerAmountPaid": order_obj.get("amount_paid"),
                "providerTransaction": str(order_obj.get("transaction") or ""),
            },
        )
    return {
        "ok": True,
        "order": settled_order,
        **({"balanceCents":new_bal} if settled_order and settled_order.get("purpose")=="cash" else {"credits":new_bal}),
        "applied": applied,
    }
