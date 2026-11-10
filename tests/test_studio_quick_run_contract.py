"""Issue #122: V3 authoritative runId in cloud reserve responses.

The gateway attempt's genId must not be mistaken for the logical Run. The
result uses owner scoped DB lookup by the immutable batch/gateway key.
"""
import unittest
from backend.services import _cloud_generation_result


class _Cursor:
    def __init__(self, row):
        self.row = row
    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, owner=23, key="batch-122", run_id="run-owner-122"):
        self.owner = owner
        self.key = key
        self.run_id = run_id
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        if "FROM wallets" in sql:
            self.owner_requested = params[0]
            return _Cursor({"balance": 15, "free_quota_used": 0,
                            "free_quota_date": "outdated"})
        if "FROM generation_runs" in sql:
            assert "user_id=?" in sql and "external_run_id=?" in sql
            assert params == (self.owner, self.key)
            return _Cursor({"id": self.run_id})
        raise AssertionError("Unexpected SQL " + sql)


def sample_row(batch="batch-122"):
    return {
        "id": "gen-122-a", "user_id": 23, "batch_id": batch,
        "request_id": "req-122-a", "status": "running",
        "task_id": "task-122-a", "visible_prompt": "",
        "prompt_masked": 1, "cost_type": "credits",
        "credits_spent": 2, "reservation_date": "2026-11-08",
        "fork_generation_id": "", "fork_item_id": ""
    }


class QuickRunContractTests(unittest.TestCase):
    def test_batch_reservation_returns_owner_scoped_v3_identity(self):
        conn = _Conn()
        result = _cloud_generation_result(conn, sample_row(), {
            "economy": {"daily_free_quota": 3},
            "gateway": {"model": "gpt-image-2"},
        })
        self.assertEqual(result["runId"], "run-owner-122")
        self.assertEqual(result["genId"], "gen-122-a")
        self.assertNotEqual(result["runId"], result["genId"])
        self.assertEqual(result["requestId"], "req-122-a")
        self.assertTrue(result["promptMasked"])
        self.assertEqual(result["finalPrompt"], "")
        self.assertEqual(conn.owner_requested, 23)

    def test_single_reservation_uses_generation_as_external_key(self):
        conn = _Conn(key="gen-122-a", run_id="run-single-122")
        result = _cloud_generation_result(conn, sample_row(batch=""), {
            "economy": {}, "gateway": {}
        })
        self.assertEqual(result["runId"], "run-single-122")
        self.assertEqual(conn.queries[-1][1], (23, "gen-122-a"))

    def test_missing_run_is_not_conjured_from_gateway_id(self):
        conn = _Conn(key="batch-122", run_id="")
        def fetch(sql, params):
            if "FROM generation_runs" in sql:
                self.assertEqual(params, (23, "batch-122"))
                return _Cursor(None)
            return _Cursor({"balance": 3, "free_quota_used": 0,
                            "free_quota_date": "outdated"})
        conn.execute = fetch
        result = _cloud_generation_result(conn, sample_row(), {
            "economy": {}, "gateway": {}
        })
        self.assertNotIn("runId", result)


if __name__=="__main__":
    unittest.main()
