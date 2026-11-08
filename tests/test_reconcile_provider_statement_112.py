"""Issue #112 offline statement validator: real local records, NO paid provider access."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from ops.reconcile_provider_statement_112 import BadEvidence, main, reconcile

SHA = "a" * 40
WINDOW = {"start_utc": "2026-11-01T00:00:00Z", "end_utc": "2026-11-02T00:00:00Z"}
WHEN = "2026-11-01T12:00:00Z"


def clean_statements():
    provider = {
        "schema_version": 1, "source": "provider_export",
        "environment": "preproduction", "release_sha": SHA,
        "window": {**WINDOW, "exported_at_utc": "2026-11-04T00:00:00Z",
                   "settlement_grace_minutes": 1440, "invoice_final": True},
        "currency": "USD",
        "tasks": [{"owner_key": "owner-A", "request_id": "request-1", "attempt": 1,
                   "provider_task_id": "task-1", "state": "succeeded"}],
        "events": [{"event_id": "statement-event-1", "owner_key": "owner-A", "request_id": "request-1",
                    "attempt": 1, "provider_task_id": "task-1",
                    "kind": "charge", "currency": "USD",
                    "amount_minor": 125, "occurred_at_utc": WHEN}],
    }
    handraw = {
        "schema_version": 1, "source": "handraw_export",
        "environment": "preproduction", "release_sha": SHA,
        "window": dict(WINDOW),
        "attempts": [{"owner_key": "owner-A", "request_id": "request-1", "attempt": 1, "run_id": "run-1",
                      "item_id": "item-1", "slot_key": "slot-1",
                      "provider_task_id": "task-1", "submitted": True,
                      "status": "success", "cost_type": "credits"}],
        "ledger_events": [{"event_key": "charge-credit-1", "owner_key": "owner-A", "request_id": "request-1",
                           "attempt": 1, "kind": "studio_gen", "delta_credits": -3,
                           "occurred_at_utc": WHEN}],
        "callbacks": [{"callback_event_id": "callback-1",
                       "owner_key": "owner-A", "request_id": "request-1", "attempt": 1,
                       "provider_task_id": "task-1", "state": "succeeded",
                       "occurred_at_utc": WHEN}],
    }
    return provider, handraw


def anomaly_codes(p, h):
    return {row["code"] for row in reconcile(p, h)["anomalies"]}


class ProviderReconciliation112(unittest.TestCase):
    def test_paid_success_separates_usd_minor_units_from_wallet_credits(self):
        p, h = clean_statements()
        report = reconcile(p, h)
        self.assertEqual(report["result"], "NO_AUTOMATED_ANOMALIES")
        self.assertEqual(report["anomalies"], [])
        self.assertEqual(report["decision"], "NO-GO")
        self.assertFalse(report["externalStatementsAuthenticated"])
        self.assertFalse(report["productionVerified"])
        self.assertEqual(report["counts"]["attempts"], 1)
        self.assertEqual(report["counts"]["providerEvents"], 1)
        self.assertNotIn("request-1", json.dumps(report))
        self.assertNotIn("task-1", json.dumps(report))
        self.assertNotIn("callback-1", json.dumps(report))

    def test_confirmed_failure_refunds_wallet_once_and_provider_charge(self):
        p, h = clean_statements()
        p["tasks"][0]["state"] = "cancelled"
        p["events"].append({**p["events"][0], "event_id": "provider-refund-1",
                            "kind": "refund", "amount_minor": 125})
        h["attempts"][0]["status"] = "refunded"
        h["callbacks"][0]["state"] = "cancelled"
        h["ledger_events"].append({**h["ledger_events"][0], "event_key": "credit-refund-1",
                                    "kind": "studio_refund", "delta_credits": 3})
        self.assertEqual(anomaly_codes(p, h), set())

    def test_45_min_or_45_hour_unknown_still_needs_authoritative_resolution(self):
        p, h = clean_statements()
        p["tasks"][0]["state"] = "unknown"
        p["events"] = []
        h["attempts"][0]["status"] = "queued"
        h["callbacks"] = []
        self.assertIn("unconfirmed_remote_state", anomaly_codes(p, h))
        # A stale unknown cannot be laundered by adding a premature refund.
        h["attempts"][0]["status"] = "refunded"
        h["ledger_events"].append({**h["ledger_events"][0], "event_key": "bad-refund",
                                    "kind": "studio_refund", "delta_credits": 3})
        self.assertIn("unconfirmed_remote_state", anomaly_codes(p, h))

    def test_duplicate_charge_and_multiple_wallet_reservations_block(self):
        p, h = clean_statements()
        p["events"].append({**p["events"][0], "event_id": "second-charge"})
        h["ledger_events"].append({**h["ledger_events"][0], "event_key": "second-wallet-debit"})
        codes = anomaly_codes(p, h)
        self.assertIn("duplicate_provider_charge", codes)
        self.assertIn("missing_or_duplicate_wallet_reservation", codes)

    def test_conflicting_replayed_callback_and_late_success_after_refund(self):
        p, h = clean_statements()
        p["tasks"][0]["state"] = "cancelled"
        p["events"].append({**p["events"][0], "event_id": "provider-refund",
                            "kind": "refund"})
        h["attempts"][0]["status"] = "refunded"
        h["ledger_events"].append({**h["ledger_events"][0], "event_key": "wallet-refund",
                                    "kind": "studio_refund", "delta_credits": 3})
        # Identical callback replay is allowed, it does not itself charge twice.
        h["callbacks"][0]["state"] = "cancelled"
        h["callbacks"].append(deepcopy(h["callbacks"][0]))
        self.assertEqual(anomaly_codes(p, h), set())
        h["callbacks"].append({**h["callbacks"][0], "state": "succeeded"})
        codes = anomaly_codes(p, h)
        self.assertIn("conflicting_replayed_callback", codes)
        self.assertIn("late_success_after_refund_requires_investigation", codes)

    def test_orphan_provider_task_billing_and_unmatched_submitted_attempt(self):
        p, h = clean_statements()
        p["tasks"].append({**p["tasks"][0], "request_id": "ghost-request",
                           "provider_task_id": "ghost-task"})
        p["events"].append({**p["events"][0], "request_id": "ghost-request",
                            "provider_task_id": "ghost-task", "event_id": "ghost-charge"})
        h["attempts"][0]["provider_task_id"] = "wrong-task"
        codes = anomaly_codes(p, h)
        self.assertIn("orphan_provider_task", codes)
        self.assertIn("orphan_provider_billing_event", codes)
        self.assertIn("unmatched_submitted_attempt", codes)

    def test_wallet_refund_must_not_exceed_reservation_or_follow_success(self):
        p, h = clean_statements()
        h["ledger_events"].append({**h["ledger_events"][0], "event_key": "bad-refund",
                                    "kind": "studio_refund", "delta_credits": 5})
        codes = anomaly_codes(p, h)
        self.assertIn("wallet_refund_exceeds_reservation", codes)
        self.assertIn("success_has_unexpected_refund", codes)

    def test_pre_submit_failure_is_not_a_provider_charge(self):
        p, h = clean_statements()
        p["events"] = []
        p["tasks"] = []
        h["attempts"][0]["provider_task_id"] = None
        h["attempts"][0]["submitted"] = False
        h["attempts"][0]["status"] = "refunded"
        h["callbacks"] = []
        h["ledger_events"].append({**h["ledger_events"][0], "event_key": "wallet-refund",
                                    "kind": "studio_refund", "delta_credits": 3})
        self.assertEqual(anomaly_codes(p, h), set())

    def test_fail_closed_on_mismatch_incomplete_invoice_unsupported_quota_sensitive_rows(self):
        p, h = clean_statements()
        p["window"]["invoice_final"] = False
        with self.assertRaises(BadEvidence):
            reconcile(p, h)
        p["window"]["invoice_final"] = True
        p["window"]["exported_at_utc"] = "2026-11-02T00:00:00Z"
        with self.assertRaises(BadEvidence):
            reconcile(p, h)
        p["window"]["exported_at_utc"] = "2026-11-04T00:00:00Z"
        h["release_sha"] = "b" * 40
        with self.assertRaises(BadEvidence):
            reconcile(p, h)
        h["release_sha"] = SHA
        h["attempts"][0]["cost_type"] = "free"
        with self.assertRaisesRegex(BadEvidence, "free quota"):
            reconcile(p, h)
        h["attempts"][0]["cost_type"] = "credits"
        p["events"][0]["raw_prompt"] = "secret-victim-data"
        with self.assertRaises(BadEvidence):
            reconcile(p, h)

    def test_missing_invoice_record_even_if_wallet_paid_is_blocking(self):
        p, h = clean_statements()
        p["events"] = []
        self.assertIn("success_missing_provider_charge", anomaly_codes(p, h))
        p["events"] = [{**clean_statements()[0]["events"][0],
                        "occurred_at_utc": "2026-12-01T01:00:00Z"}]
        with self.assertRaises(BadEvidence):
            reconcile(p, h)

    def test_provider_terminal_conflicts_with_callback(self):
        p, h = clean_statements()
        h["callbacks"][0]["state"] = "failed"
        self.assertIn("callback_provider_terminal_conflict", anomaly_codes(p, h))

    def test_same_v3_slot_successful_twice_after_retry_blocks(self):
        p, h = clean_statements()
        p["tasks"].append({**p["tasks"][0], "request_id": "retry-request",
                           "provider_task_id": "retry-task"})
        p["events"].append({**p["events"][0], "request_id": "retry-request",
                            "provider_task_id": "retry-task", "event_id": "retry-charge"})
        h["attempts"].append({**h["attempts"][0], "request_id": "retry-request",
                              "provider_task_id": "retry-task"})
        h["ledger_events"].append({**h["ledger_events"][0],
                                   "request_id": "retry-request", "event_key": "retry-wallet"})
        h["callbacks"].append({**h["callbacks"][0], "request_id": "retry-request",
                               "provider_task_id": "retry-task",
                               "callback_event_id": "retry-callback"})
        self.assertIn("multiple_successful_paid_attempts_per_slot", anomaly_codes(p, h))

    def test_two_users_same_request_id_and_attempt_do_not_collide(self):
        p, h = clean_statements()
        # Backend uniqueness is scoped to user: request ID alone is unsafe.
        # Deliberately keep Run/Item/Slot identifiers equal to exercise scope.
        p["tasks"].append({**p["tasks"][0], "owner_key": "owner-B",
                           "provider_task_id": "task-B"})
        p["events"].append({**p["events"][0], "owner_key": "owner-B",
                            "provider_task_id": "task-B", "event_id": "invoice-B"})
        h["attempts"].append({**h["attempts"][0], "owner_key": "owner-B",
                              "provider_task_id": "task-B"})
        h["ledger_events"].append({**h["ledger_events"][0], "owner_key": "owner-B",
                                   "event_key": "wallet-B"})
        h["callbacks"].append({**h["callbacks"][0], "owner_key": "owner-B",
                               "provider_task_id": "task-B",
                               "callback_event_id": "callback-B"})
        report = reconcile(p, h)
        self.assertEqual(report["anomalies"], [])
        self.assertEqual(report["counts"]["attempts"], 2)
        self.assertNotIn("owner-B", json.dumps(report))

    def test_empty_statements_never_masquerade_as_reconciled(self):
        p, h = clean_statements()
        p["tasks"] = []
        p["events"] = []
        h["attempts"] = []
        h["ledger_events"] = []
        h["callbacks"] = []
        self.assertIn("empty_internal_statement", anomaly_codes(p, h))

    def test_malformed_status_containers_do_not_leak_traceback(self):
        p, h = clean_statements()
        p["tasks"][0]["state"] = ["succeeded"]
        with self.assertRaises(BadEvidence):
            reconcile(p, h)

    def test_cli_refuses_world_readable_evidence_and_does_not_replace_reports(self):
        p, h = clean_statements()
        with tempfile.TemporaryDirectory() as td:
            provider = Path(td) / "provider.json"
            handraw = Path(td) / "handraw.json"
            report = Path(td) / "report.json"
            provider.write_text(json.dumps(p), encoding="utf-8")
            handraw.write_text(json.dumps(h), encoding="utf-8")
            args = ["--provider", str(provider), "--handraw", str(handraw),
                    "--report", str(report)]
            if os.name == "posix":
                provider.chmod(0o644)
                handraw.chmod(0o600)
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args), 2)
            provider.chmod(0o600)
            with redirect_stdout(io.StringIO()) as capture:
                self.assertEqual(main(args), 0)
            self.assertNotIn("request-1", capture.getvalue())
            self.assertEqual(report.stat().st_mode & 0o077, 0)
            data = report.read_text(encoding="utf-8")
            self.assertEqual(json.loads(data)["decision"], "NO-GO")
            self.assertNotIn("request-1", data)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual(json.loads(report.read_text())["counts"]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
