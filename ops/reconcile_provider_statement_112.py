#!/usr/bin/env python3
"""#112 offline paid-provider statement to Handraw paid-credit ledger reconciliation.

Two independently sourced, normalized PRIVATE JSON files. No network, no
credentials, no database writes, no paid API, no user-media access.
This tool cannot establish that an export is authentic and can NEVER grant GO.
Only paid-credit attempts are in scope; free-quota reconciliation is separate.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:@-]{0,127}$")
TERMINAL = {"succeeded", "failed", "cancelled"}
PENDING = {"unknown", "queued", "running"}
PROVIDER_STATES = TERMINAL | PENDING
INTERNAL_STATES = {"success", "refunded", "failed", "cancelled", "error", "queued", "running"}
KINDS = {"charge", "refund"}


class BadEvidence(ValueError):
    pass


def _object(value: object, allowed: set[str], required: set[str], where: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise BadEvidence("invalid evidence fields at " + where)
    return value


def _ident(value: object, where: str, *, optional: bool = False) -> str:
    if optional and value is None:
        return ""
    if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
        raise BadEvidence("invalid non-sensitive identifier at " + where)
    return value


def _stamp(value: object, where: str) -> datetime:
    if not isinstance(value, str) or len(value) > 35:
        raise BadEvidence("invalid UTC timestamp at " + where)
    try:
        item = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BadEvidence("invalid UTC timestamp at " + where) from None
    if item.tzinfo is None or item.utcoffset() != timedelta(0):
        raise BadEvidence("timestamp must be UTC at " + where)
    return item.astimezone(timezone.utc)


def _count(value: object, where: str, *, positive: bool = False) -> int:
    if type(value) is not int or not (-10**12 <= value <= 10**12):
        raise BadEvidence("invalid integer at " + where)
    if positive and value <= 0:
        raise BadEvidence("must be positive at " + where)
    return value


def _attempt_key(row: dict, where: str) -> tuple[str, str, int]:
    owner = _ident(row["owner_key"], where)
    rid = _ident(row["request_id"], where)
    number = _count(row["attempt"], where, positive=True)
    if number > 10000:
        raise BadEvidence("attempt outside supported bounds")
    return owner, rid, number


def _window(raw: object, provider: bool) -> dict:
    required = {"start_utc", "end_utc"}
    allowed = required | ({"exported_at_utc", "settlement_grace_minutes", "invoice_final"} if provider else set())
    w = _object(raw, allowed, allowed, "window")
    start, end = _stamp(w["start_utc"], "window.start"), _stamp(w["end_utc"], "window.end")
    if not start < end:
        raise BadEvidence("empty or reversed accounting period")
    if provider:
        if w["invoice_final"] is not True:
            raise BadEvidence("provider statement is not final")
        grace = _count(w["settlement_grace_minutes"], "settlement_grace_minutes")
        if not 60 <= grace <= 60 * 24 * 90:
            raise BadEvidence("provider settlement grace not configured safely")
        exported = _stamp(w["exported_at_utc"], "window.exported")
        if exported < end + timedelta(minutes=grace):
            raise BadEvidence("provider invoice export was not mature")
    return {"start": start, "end": end}


def _rows(value: object, where: str, *, maximum: int = 100000) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise BadEvidence("invalid evidence rows at " + where)
    return value


def _meta(raw: object, *, provider: bool) -> tuple[dict, dict]:
    source = "provider_export" if provider else "handraw_export"
    required = {"schema_version", "source", "environment", "release_sha", "window"}
    required |= {"currency", "tasks", "events"} if provider else {"attempts", "ledger_events", "callbacks"}
    root = _object(raw, required, required, "root")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise BadEvidence("unsupported schema")
    if root["source"] != source or root["environment"] not in ("preproduction", "production"):
        raise BadEvidence("untrusted evidence origin or environment")
    if type(root["environment"]) is not str:
        raise BadEvidence("invalid environment")
    if not isinstance(root["release_sha"], str) or not SHA_RE.fullmatch(root["release_sha"]):
        raise BadEvidence("release SHA must be a full git commit hash")
    return root, _window(root["window"], provider)


def _in_period(value: object, window: dict, where: str) -> None:
    when = _stamp(value, where)
    if not window["start"] <= when < window["end"]:
        raise BadEvidence("row outside accounting period at " + where)


def _issue(issues: list[dict], code: str, ref: int | None = None) -> None:
    # Only synthetic in-file row ordinal, NEVER a request/task/customer ID.
    row = {"code": code}
    if ref is not None:
        row["attemptOrdinal"] = ref
    issues.append(row)


def reconcile(provider: object, handraw: object) -> dict:
    p, pw = _meta(provider, provider=True)
    h, hw = _meta(handraw, provider=False)
    if (p["environment"] != h["environment"] or
            p["release_sha"].lower() != h["release_sha"].lower() or
            (pw["start"], pw["end"]) != (hw["start"], hw["end"])):
        raise BadEvidence("independent export period, environment or SHA mismatch")
    if not isinstance(p["currency"], str) or not re.fullmatch(r"[A-Z]{3}", p["currency"]):
        raise BadEvidence("invalid provider currency")
    issues: list[dict] = []
    attempts: dict[tuple[str, str, int], dict] = {}
    ordinal: dict[tuple[str, str, int], int] = {}
    task_ids: dict[str, tuple[str, str, int]] = {}
    for pos, row in enumerate(_rows(h["attempts"], "handraw.attempts"), 1):
        row = _object(row, {"owner_key", "request_id", "attempt", "run_id", "item_id", "slot_key",
                            "provider_task_id", "submitted", "status", "cost_type"},
                      {"owner_key", "request_id", "attempt", "run_id", "item_id", "slot_key",
                       "provider_task_id", "submitted", "status", "cost_type"}, "attempt")
        key = _attempt_key(row, "handraw attempt")
        for field in ("run_id", "item_id", "slot_key"):
            _ident(row[field], "handraw." + field)
        task = _ident(row["provider_task_id"], "handraw.provider_task_id", optional=True)
        if (type(row["submitted"]) is not bool or type(row["status"]) is not str
                or row["status"] not in INTERNAL_STATES):
            raise BadEvidence("invalid internal attempt status")
        if row["cost_type"] != "credits":
            raise BadEvidence("only actual paid-credit attempts are supported; free quota is a separate gate")
        if not row["submitted"] and task:
            raise BadEvidence("unsubmitted attempt must not have a provider task ID")
        if key in attempts:
            _issue(issues, "duplicate_internal_attempt", pos)
        else:
            attempts[key], ordinal[key] = row, pos

    tasks: dict[tuple[str, str, int], dict] = {}
    for row in _rows(p["tasks"], "provider.tasks"):
        row = _object(row, {"owner_key", "request_id", "attempt", "provider_task_id", "state"},
                      {"owner_key", "request_id", "attempt", "provider_task_id", "state"}, "provider task")
        key = _attempt_key(row, "provider task")
        tid = _ident(row["provider_task_id"], "provider task ID")
        if type(row["state"]) is not str or row["state"] not in PROVIDER_STATES:
            raise BadEvidence("invalid provider state")
        if key in tasks or (tid in task_ids and task_ids[tid] != key):
            _issue(issues, "duplicate_or_conflicting_provider_task", ordinal.get(key))
        else:
            tasks[key] = row
            task_ids[tid] = key

    event_groups: dict[tuple[str, str, int], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    event_ids: set[str] = set()
    for row in _rows(p["events"], "provider.events"):
        row = _object(row, {"event_id", "owner_key", "request_id", "attempt", "provider_task_id",
                            "kind", "currency", "amount_minor", "occurred_at_utc"},
                      {"event_id", "owner_key", "request_id", "attempt", "provider_task_id",
                       "kind", "currency", "amount_minor", "occurred_at_utc"}, "provider event")
        key = _attempt_key(row, "provider event")
        event_id = _ident(row["event_id"], "provider event ID")
        tid = _ident(row["provider_task_id"], "provider event task ID")
        _in_period(row["occurred_at_utc"], pw, "provider event")
        if type(row["kind"]) is not str or row["kind"] not in KINDS or row["currency"] != p["currency"]:
            raise BadEvidence("provider currency/kind mismatch")
        amount = _count(row["amount_minor"], "provider money minor units", positive=True)
        if event_id in event_ids:
            _issue(issues, "duplicate_provider_event", ordinal.get(key))
        event_ids.add(event_id)
        event_groups[key][row["kind"]].append(amount)
        if key not in tasks or tasks[key]["provider_task_id"] != tid:
            _issue(issues, "provider_event_without_matching_task", ordinal.get(key))

    ledger_groups: dict[tuple[str, str, int], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    ledger_ids: set[str] = set()
    for row in _rows(h["ledger_events"], "handraw.ledger_events"):
        row = _object(row, {"event_key", "owner_key", "request_id", "attempt", "kind",
                            "delta_credits", "occurred_at_utc"},
                      {"event_key", "owner_key", "request_id", "attempt", "kind",
                       "delta_credits", "occurred_at_utc"}, "handraw ledger event")
        key = _attempt_key(row, "handraw ledger event")
        event_id = _ident(row["event_key"], "handraw ledger ID")
        _in_period(row["occurred_at_utc"], hw, "handraw ledger event")
        if type(row["kind"]) is not str or row["kind"] not in ("studio_gen", "studio_refund"):
            raise BadEvidence("only dedicated studio ledger events allowed")
        delta = _count(row["delta_credits"], "handraw credit delta")
        if (row["kind"] == "studio_gen" and delta >= 0 or
                row["kind"] == "studio_refund" and delta <= 0):
            _issue(issues, "invalid_internal_ledger_direction", ordinal.get(key))
        if event_id in ledger_ids:
            _issue(issues, "duplicate_internal_ledger_event", ordinal.get(key))
        ledger_ids.add(event_id)
        ledger_groups[key][row["kind"]].append(delta)
        if key not in attempts:
            _issue(issues, "orphan_internal_ledger_event")

    callback_ids: dict[str, dict] = {}
    for row in _rows(h["callbacks"], "handraw.callbacks"):
        row = _object(row, {"callback_event_id", "owner_key", "request_id", "attempt",
                            "provider_task_id", "state", "occurred_at_utc"},
                      {"callback_event_id", "owner_key", "request_id", "attempt",
                       "provider_task_id", "state", "occurred_at_utc"}, "callback")
        key = _attempt_key(row, "callback")
        cbid = _ident(row["callback_event_id"], "callback event ID")
        _ident(row["provider_task_id"], "callback provider task ID")
        _in_period(row["occurred_at_utc"], hw, "callback")
        if type(row["state"]) is not str or row["state"] not in TERMINAL:
            raise BadEvidence("callback must have authoritative terminal status")
        if cbid in callback_ids and callback_ids[cbid] != row:
            _issue(issues, "conflicting_replayed_callback", ordinal.get(key))
        callback_ids[cbid] = row
        if key not in attempts:
            _issue(issues, "orphan_callback")
        elif (not attempts[key]["submitted"] or
              attempts[key]["provider_task_id"] != row["provider_task_id"]):
            _issue(issues, "callback_task_mismatch", ordinal.get(key))
        if key in tasks and tasks[key]["state"] in TERMINAL and row["state"] != tasks[key]["state"]:
            _issue(issues, "callback_provider_terminal_conflict", ordinal.get(key))
        if (row["state"] == "succeeded" and key in attempts
                and attempts[key]["status"] == "refunded"):
            _issue(issues, "late_success_after_refund_requires_investigation", ordinal.get(key))

    if not attempts:
        _issue(issues, "empty_internal_statement")

    # Multiple successful *paid* remote attempts for one canonical V3 output
    # slot can indicate double-billing even when requestId differs on retry.
    successes_by_slot: dict[tuple[str, str, str, str], list[tuple[str, str, int]]] = defaultdict(list)
    for key, row in attempts.items():
        if row["status"] == "success":
            successes_by_slot[(row["owner_key"], row["run_id"], row["item_id"], row["slot_key"])].append(key)
    for completed in successes_by_slot.values():
        if len(completed) > 1:
            for key in completed:
                _issue(issues, "multiple_successful_paid_attempts_per_slot", ordinal[key])

    for key, row in attempts.items():
        ref = ordinal[key]
        task, pg = tasks.get(key), event_groups.get(key, {})
        lg = ledger_groups.get(key, {})
        debits, refunds = lg.get("studio_gen", []), lg.get("studio_refund", [])
        charges, provider_refunds = pg.get("charge", []), pg.get("refund", [])
        if len(debits) != 1:
            _issue(issues, "missing_or_duplicate_wallet_reservation", ref)
        if len(refunds) > 1:
            _issue(issues, "duplicate_wallet_refund", ref)
        if refunds and (not debits or sum(refunds) > -sum(debits)):
            _issue(issues, "wallet_refund_exceeds_reservation", ref)
        if len(charges) > 1:
            _issue(issues, "duplicate_provider_charge", ref)
        if sum(provider_refunds) > sum(charges):
            _issue(issues, "provider_refund_exceeds_charge", ref)
        if len(provider_refunds) > 1:
            _issue(issues, "duplicate_provider_refund", ref)
        if not row["submitted"]:
            if task or charges or provider_refunds:
                _issue(issues, "unsubmitted_attempt_has_provider_activity", ref)
            if row["status"] != "refunded" or len(refunds) != 1:
                _issue(issues, "pre_submit_attempt_not_released", ref)
            continue
        if not task or not row["provider_task_id"] or (task and
                row["provider_task_id"] != task["provider_task_id"]):
            _issue(issues, "unmatched_submitted_attempt", ref)
            continue
        state, internal = task["state"], row["status"]
        if state in PENDING or internal in {"queued", "running"}:
            _issue(issues, "unconfirmed_remote_state", ref)
        if state == "succeeded":
            if internal != "success":
                _issue(issues, "provider_success_internal_mismatch", ref)
            if not charges:
                _issue(issues, "success_missing_provider_charge", ref)
            if refunds or provider_refunds:
                _issue(issues, "success_has_unexpected_refund", ref)
        if state in ("failed", "cancelled"):
            if internal != "refunded" or len(refunds) != 1:
                _issue(issues, "confirmed_failure_missing_wallet_refund", ref)
            if charges and sum(provider_refunds) != sum(charges):
                _issue(issues, "provider_failed_task_charge_unsettled", ref)

    for key, row in tasks.items():
        if key not in attempts:
            _issue(issues, "orphan_provider_task")
        elif not attempts[key]["submitted"]:
            _issue(issues, "provider_task_for_unsubmitted_attempt", ordinal[key])
    for key in event_groups:
        if key not in attempts:
            _issue(issues, "orphan_provider_billing_event")

    totals = Counter(x["code"] for x in issues)
    return {
        "schemaVersion": 1, "issue": 112, "environment": p["environment"],
        "releaseSha": p["release_sha"].lower(),
        "counts": {"attempts": len(attempts), "providerTasks": len(tasks),
                   "providerEvents": len(p["events"]), "walletEvents": len(h["ledger_events"]),
                   "callbackEvents": len(h["callbacks"])},
        "anomalies": sorted(issues, key=lambda v: (v["code"], v.get("attemptOrdinal", 0))),
        "anomalyCounts": dict(sorted(totals.items())),
        "currencyUnitsSeparated": True, "externalStatementsAuthenticated": False,
        "result": "ANOMALIES" if issues else "NO_AUTOMATED_ANOMALIES",
        "decision": "NO-GO", "productionVerified": False,
        "note": "Read-only normalized evidence; independent provider and finance sign-off required",
    }


def _private_read(path: Path) -> object:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise BadEvidence("missing, linked or oversized private evidence file")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise BadEvidence("private evidence file must be owner-accessible only (0600)")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BadEvidence("invalid private evidence JSON") from None


def _write_report(path: Path, result: dict) -> None:
    if not path.parent.is_dir() or path.is_symlink():
        raise BadEvidence("invalid report path")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
        out.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", type=Path, required=True)
    parser.add_argument("--handraw", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.provider.resolve() == args.handraw.resolve():
            raise BadEvidence("independent sources must be different files")
        report = reconcile(_private_read(args.provider), _private_read(args.handraw))
        _write_report(args.report, report)
        print(json.dumps({"result": report["result"], "decision": report["decision"],
                          "anomalyCount": len(report["anomalies"])}))
        return 0 if not report["anomalies"] else 1
    except (BadEvidence, OSError, OverflowError):
        print("reconciliation refused: invalid/private evidence or unsafe report target",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
