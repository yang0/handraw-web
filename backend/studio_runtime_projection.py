"""#119 read-only Studio Runtime projection; no new persisted status enum.

V3 Run/RunItem own completion and media; studio_generations is only the
gateway/billing attempt ledger. No projection mutates either. UI intents
(cancel_requested, checking_remote, connection_lost) remain client-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

PERSISTED_RUN = frozenset({"pending", "uploading", "running", "partial", "success", "failed", "cancelled"})
PERSISTED_ITEM = frozenset({"pending", "generating", "success", "failed", "cancelled"})
ACTIVE_GATEWAY = frozenset({"queued", "running"})
TERMINAL_GATEWAY = frozenset({"success", "refunded", "failed", "cancelled", "error"})


def _age_seconds(value: Any, now: datetime) -> float:
    try:
        timestamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return max(0.0, (now - timestamp).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 0.0


def project_studio_run(
    run: Mapping[str, Any],
    items: list[Mapping[str, Any]],
    gateway_rows: list[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    uncertain_after_seconds: int = 900,
) -> dict[str, Any]:
    """Project owner-scoped V3 items plus gateway attempts into ordered slots.

    An attempt is never an output. A successful output is accepted only when
    a V3 item has an owner-authorized media ID AND storage URL. Older success
    cannot be demoted by late refunds, callbacks or retries. Stale gateway
    submissions become *view-only* unknown; the database CHECK is untouched.
    """
    now = now or datetime.now(timezone.utc)
    source = str(run.get("source") or "")
    expected = int(run.get("expectedCount") or 0)
    if expected < 1 or expected > 1000:
        raise ValueError("Invalid persisted run expected_count")
    items_by_slot: dict[int, list[Mapping[str, Any]]] = {}
    for item in items:
        position = int(item.get("position") or 0)
        slot = int(item.get("slotIndex") if item.get("slotIndex") is not None
                   else position // 1000 if source == "web" else position)
        if 0 <= slot < expected:
            items_by_slot.setdefault(slot, []).append(item)

    attempts_by_slot: dict[int, list[dict[str, Any]]] = {}
    attempts: list[dict[str, Any]] = []
    for row in gateway_rows:
        index = int(row.get("batch_index") or 0)
        if source != "web" or index < 0 or index >= expected:
            continue
        try:
            stored = json.loads(row.get("system_append_json") or "{}")
            meta = stored.get("runtimeSnapshot") or {}
            if not isinstance(meta, dict):
                meta = {}
        except (ValueError, TypeError):
            meta = {}
        status = str(row.get("status") or "")
        if status not in ACTIVE_GATEWAY | TERMINAL_GATEWAY:
            status = "unknown"
        request_id = str(row.get("request_id") or "")
        task_id = str(row.get("task_id") or "")
        age = _age_seconds(row.get("created_at"), now)
        uncertain = status in ACTIVE_GATEWAY and age >= uncertain_after_seconds
        attempt = {
            "attemptId": str(row.get("id") or ""),
            "slotIndex": index, "position": index * 1000,
            "slotId": str(meta.get("slotId") or ""),
            "requestId": request_id,
            "idempotencyKey": request_id,
            "taskId": task_id,
            "persistedStatus": str(row.get("status") or ""),
            "viewStatus": "unknown" if uncertain else status,
            "needsRecheck": status in ACTIVE_GATEWAY,
            "chargedCredits": int(row.get("credits_spent") or 0),
            "costType": str(row.get("cost_type") or ""),
            "createdAt": str(row.get("created_at") or ""),
        }
        attempts_by_slot.setdefault(index, []).append(attempt)
        attempts.append(attempt)

    counts = {"success": 0, "failed": 0, "cancelled": 0,
              "running": 0, "queued": 0, "unknown": 0}
    slots = []
    for index in range(expected):
        candidates = items_by_slot.get(index, [])
        gateway = attempts_by_slot.get(index, [])
        # The canonical V3 media identity always wins, even after a new
        # attempt's status becomes queued, refunded or unknown.
        confirmed = next((
            i for i in candidates if str(i.get("status") or "") == "success"
            and i.get("mediaId") and i.get("imageUrl")
        ), None)
        last = gateway[-1] if gateway else None
        persisted_failure = next(
            (i for i in candidates if i.get("status") == "failed"), None)
        persisted_cancel = next(
            (i for i in candidates if i.get("status") == "cancelled"), None)
        actively_generating = next(
            (i for i in candidates if i.get("status") == "generating"), None)
        if confirmed:
            view = "success"
        elif last and last["viewStatus"] == "unknown":
            view = "unknown"
        elif last and last["viewStatus"] in ACTIVE_GATEWAY:
            view = "running" if last["taskId"] or last["viewStatus"] == "running" else "queued"
        elif actively_generating:
            view = "running"
        elif persisted_failure or last and last["persistedStatus"] in ("failed", "refunded", "error"):
            view = "failed"
        elif persisted_cancel or last and last["persistedStatus"] == "cancelled":
            view = "cancelled"
        elif last and last["persistedStatus"] == "success":
            # Gateway said success but an authorized durable media is missing.
            view = "unknown"
        else:
            view = "queued"
        counts[view] += 1
        item = confirmed or (candidates[-1] if candidates else {})
        slot_id = next((a["slotId"] for a in gateway if a["slotId"]), "")
        slots.append({
            "slotIndex": index, "position": index * 1000 if source == "web" else index,
            "slotId": slot_id, "viewStatus": view,
            "itemId": str(item.get("id") or ""),
            "persistedItemStatus": str(item.get("status") or ""),
            "mediaId": str(confirmed.get("mediaId") or "") if confirmed else "",
            "imageUrl": str(confirmed.get("imageUrl") or "") if confirmed else "",
            "errorCode": str(item.get("errorCode") or ""),
            "attemptCount": len(gateway),
            "latestAttemptId": last["attemptId"] if last else "",
            "requestId": last["requestId"] if last else "",
            "taskId": last["taskId"] if last else "",
            "retryAllowed": view in ("failed", "cancelled") and not any(
                a["persistedStatus"] in ACTIVE_GATEWAY for a in gateway),
            "needsRecheck": bool(last and last["needsRecheck"]),
        })

    terminal = counts["success"] + counts["failed"] + counts["cancelled"] == expected
    view_status = (
        "unknown" if counts["unknown"] else
        "running" if counts["running"] else
        "pending" if counts["queued"] else
        "success" if counts["success"] == expected else
        "partial" if counts["success"] else
        "failed" if counts["failed"] else "cancelled"
    )
    return {
        "slots": slots, "attempts": attempts,
        "projection": {
            "runId": str(run.get("id") or ""),
            "persistedStatus": str(run.get("status") or ""),
            "viewStatus": view_status, "total": expected,
            "succeeded": counts["success"], "failed": counts["failed"],
            "cancelled": counts["cancelled"], "generating": counts["running"],
            "queued": counts["queued"], "unknown": counts["unknown"],
            "processed": counts["success"] + counts["failed"] + counts["cancelled"],
            "isTerminal": terminal,
            "canRetry": any(slot["retryAllowed"] for slot in slots),
            "recoveryRequired": any(slot["needsRecheck"] for slot in slots),
        },
        "billing": {
            # Already-charged ledger rows include refunded attempts. These
            # numbers are NOT a promise that upstream cancellation refunded.
            "attemptCount": len(attempts),
            "creditsReservedOrCharged": sum(a["chargedCredits"] for a in attempts),
            "refundedAttemptCount": sum(a["persistedStatus"] == "refunded" for a in attempts),
            "note": "同一 requestId 重放不二次扣费；用户主动重试是新的请求，取消不保证退款。",
        },
    }
