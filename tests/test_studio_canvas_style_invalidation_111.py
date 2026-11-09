"""#111 style invalidation and selector diagnostics must be bounded and safe."""
import json
import unittest
from ops.canvas_style_invalidation_111 import (
    summarize_selector_footprint, summarize_style_invalidation,
    summarize_selector_timings,
)

class StyleInvalidation111Tests(unittest.TestCase):
    def test_trace_reports_aggregates_not_private_args(self):
        secret="https://private.example/account?token=CANARY_TOPSECRET"
        obj={"traceEvents":[
            {"name":"StyleRecalcInvalidationTracking","args":{"data":{"reason":"PseudoClass","url":secret,"selector":secret}}},
            {"name":"ScheduleStyleRecalculation","args":{"data":{"reason":secret}}},
            {"name":"UpdateLayoutTree","ph":"X","args":{"data":{"elementCount":300,"text":secret}}},
            {"name":"UpdateLayoutTree","ph":"X","args":{"data":{"elementCount":42}}},
            {"name":"other","args":{"password":secret}},
        ]}
        result=summarize_style_invalidation(obj)
        self.assertEqual(result["invalidationsByType"]["StyleRecalcInvalidationTracking"],1)
        self.assertEqual(result["reasonCategories"]["pseudo-state"],1)
        self.assertEqual(result["reportedAffectedElements"]["max"],300)
        self.assertNotIn("CANARY_TOPSECRET",json.dumps(result))
        self.assertFalse(result["rootCauseProven"])
        self.assertFalse(result["rawTracePersisted"])

    def test_chrome_real_selector_stats_are_aggregated_and_redacted(self):
        secret="https://private.example?token=TOP_SECRET_DO_NOT_LOG"
        trace={"traceEvents":[
            {"name":"SelectorStats","ph":"X","args":{"selector_stats":{
                "selector_timings":[
                    {"selector":".ic-node:hover .ic-port-zone","elapsed (us)":1200,
                     "match_attempts":9000,"match_count":3,"fast_reject_count":8000,
                     "style_sheet_id":secret},
                    {"selector":".ic-node:hover .ic-port-zone","elapsed (us)":200,
                     "match_attempts":1000,"match_count":1,"fast_reject_count":950},
                    {"selector":"body [data-secret='"+secret+"']","elapsed (us)":9999,
                     "match_attempts":100,"match_count":2},
                ]}}},
        ]}
        result=summarize_selector_timings(trace)
        self.assertTrue(result["selectorStatsEventsObserved"])
        self.assertEqual(result["eligibleUniqueSelectors"],1)
        top=result["topByMeasuredMatchTime"][0]
        self.assertEqual(top["matchAttempts"],10000)
        self.assertEqual(top["matchCount"],4)
        self.assertEqual(top["elapsedMs"],1.4)
        self.assertNotIn("TOP_SECRET",json.dumps(result))
        self.assertTrue(result["addsInstrumentationOverhead"])

    def test_unknown_is_not_zero(self):
        result=summarize_style_invalidation({"traceEvents":[]})
        self.assertFalse(result["invalidationEventsObserved"])
        self.assertIsNone(result["reportedAffectedElements"]["max"])
        with self.assertRaises(ValueError):
            summarize_style_invalidation({"traceEvents":[None]*400001})

    def test_selector_report_only_safe_static_identifiers(self):
        obj={"skippedSheets":1,"rulesInspected":35,"selectors":[
            {"selector":".ic-node:hover .ic-badge","matches":300},
            {"selector":".ic-node:has(.ic-dirty)","matches":180},
            {"selector":".ic-node [data-private='SECRET']","matches":44},
            {"selector":".ic-other","matches":120},
            {"selector":"body #accountSECRET","matches":100},
        ]}
        report=summarize_selector_footprint(obj)
        self.assertEqual(report["eligibleSelectors"],3)
        self.assertTrue(report["matching300Cards"])
        self.assertTrue(report["highFanoutSelectors"][0]["dynamicPseudo"])
        self.assertNotIn("SECRET",json.dumps(report))
        self.assertEqual(report["stylesheetsSkipped"],1)

if __name__=="__main__":
    unittest.main()
