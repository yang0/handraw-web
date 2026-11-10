"""#111: CDP frame diagnostics must never claim missing paints = 0."""
import base64
import json
import unittest

from ops.canvas_frame_trace_111 import (
    delta_performance_metrics, percentile, read_trace_from_stream,
    summarize_raf_intervals, summarize_trace_events,
)


class CanvasFrameDiagnostics111(unittest.TestCase):
    def test_raf_presentation_cadence_uses_sample_bounds(self):
        result = summarize_raf_intervals([16, 17, 32, 35, -5, None, float("nan")])
        self.assertEqual(result["samples"], 4)
        self.assertEqual(result["over16_7"], 3)
        self.assertEqual(result["over33_3"], 1)
        self.assertFalse(result["productionFrameSLA"])
        self.assertEqual(result["frameGapP95Ms"], 32)
        self.assertIsNone(percentile([], .95))

    def test_missing_metrics_are_unknown_not_zero(self):
        self.assertEqual(delta_performance_metrics({}, {})["LayoutDuration"], None)
        before = {"metrics": [{"name": "LayoutDuration", "value": 1.2},
                              {"name": "LayoutCount", "value": 4},
                              {"name": "ScriptDuration", "value": 2.0}]}
        after = {"metrics": [{"name": "LayoutDuration", "value": 1.2085},
                             {"name": "LayoutCount", "value": 7},
                             {"name": "ScriptDuration", "value": 2.028}]}
        result = delta_performance_metrics(before, after)
        self.assertAlmostEqual(result["LayoutDuration"], 8.5)
        self.assertEqual(result["LayoutCount"], 3)
        self.assertAlmostEqual(result["ScriptDuration"], 28)
        self.assertIsNone(result["RecalcStyleDuration"])
        self.assertIsNone(delta_performance_metrics(after, before)["LayoutDuration"])

    def test_trace_reports_only_aggregate_whitelist_and_never_private(self):
        secret = "https://private.example/?token=SECRET_ACCOUNT_123"
        trace = {"traceEvents": [
            {"name": "Layout", "ph": "X", "dur": 1350, "args": {"url": secret}},
            {"name": "Paint", "ph": "X", "dur": 270, "args": {"prompt": secret}},
            {"name": "Paint", "ph": "B", "args": {"requestId": secret}},
            {"name": "CompositeLayers", "ph": "X", "dur": 380},
            {"name": "metadata", "ph": "X", "dur": 99, "args": secret},
        ]}
        result = summarize_trace_events(trace)
        self.assertEqual(result["groups"]["layout"]["sumDurationMs"], 1.35)
        self.assertEqual(result["groups"]["paint"]["count"], 1)
        self.assertEqual(result["groups"]["composite"]["count"], 1)
        self.assertEqual(result["groups"]["raster"]["observed"], False)
        self.assertIsNone(result["groups"]["raster"]["sumDurationMs"])
        self.assertNotIn("SECRET_ACCOUNT", json.dumps(result))
        self.assertFalse(result["productionFrameSLA"])
        self.assertFalse(result["rawTracePersisted"])

    def test_trace_rejects_ambiguous_or_excessive_event_payloads(self):
        with self.assertRaises(ValueError):
            summarize_trace_events({"traceEvents": "unexpected-text"})
        with self.assertRaises(ValueError):
            summarize_trace_events({"traceEvents": [None]*400001})

    def test_stream_reader_bounded_and_always_closed(self):
        class FakeCDP:
            def __init__(self, pages):
                self.pages = list(pages)
                self.closed = []
            def send(self, name, payload):
                if name == "IO.read":
                    return self.pages.pop(0)
                if name == "IO.close":
                    self.closed.append(payload["handle"])
                    return {}
                raise AssertionError(name)
        encoded = base64.b64encode(b'{"traceEvents":').decode("ascii")
        cdp = FakeCDP([
            {"data": encoded, "base64Encoded": True, "eof": False},
            {"data": "[]}", "eof": True},
        ])
        self.assertEqual(read_trace_from_stream(cdp, "stream-a"), {"traceEvents": []})
        self.assertEqual(cdp.closed, ["stream-a"])
        cdp = FakeCDP([{"data": "x"*20, "eof": True}])
        with self.assertRaises(ValueError):
            read_trace_from_stream(cdp, "stream-b", max_bytes=10)
        self.assertEqual(cdp.closed, ["stream-b"])


if __name__ == "__main__":
    unittest.main()
