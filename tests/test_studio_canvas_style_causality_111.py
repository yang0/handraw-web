"""Stage 11 #111 safety and window-correlation unit regressions."""
import json
import unittest

from ops.canvas_style_causality_111 import (
    reduce_mutation_window, summarize_causality_window,
    validate_selector_census,
)


class Causality111Tests(unittest.TestCase):
    def test_real_trace_correlation_same_thread_only(self):
        private = "CANARY_PRIVATE_prompt_https://internal.example/abc"
        trace = {"traceEvents": [
            {"name": "StyleInvalidatorInvalidationTracking", "ts": 1000,
             "pid": 1, "tid": 2, "args": {"data": {
                 "nodeId": 999, "reason": "Ancestor tree invalidation",
                 "selector": private, "userText": private}}},
            {"name": "UpdateLayoutTree", "ph": "X", "ts": 2200,
             "pid": 1, "tid": 2, "args": {"data": {
                 "elementCount": 9200, "prompt": private}}},
            {"name": "StyleRecalcInvalidationTracking", "ts": 2500,
             "pid": 1, "tid": 3, "args": {"data": {
                 "reason": "PseudoClass", "nodeName": "DIV"}}},
            {"name": "UpdateLayoutTree", "ph": "X", "ts": 3000,
             "pid": 1, "tid": 2, "args": {"data": {"elementCount": 6}}},
            {"name": "StyleRecalcInvalidationTracking", "ts": 4000,
             "pid": 1, "tid": 2, "args": {"data": {"reason": "Class change"}}},
            {"name": "UpdateLayoutTree", "ph": "X", "ts": 110000,
             "pid": 1, "tid": 2, "args": {"data": {"elementCount": 10000}}},
        ]}
        mutation = {"records": [
            {"attribute": "style", "role": "node",
             "ancestors": ["studio-shell", "canvas-stage", "world", "nodes-layer", "node"],
             "sensitive": private},
            {"attribute": "class", "role": "edge-path",
             "ancestors": ["studio-shell", "canvas-stage", "world", "edge-svg", "edge-path"]},
        ]}
        got = summarize_causality_window(trace, mutation)
        self.assertEqual(got["joinedToNextSameThreadUpdateWithin50Ms"], 1)
        self.assertEqual(got["joinsNearLargeUpdate"], 1)
        self.assertEqual(got["joinNearLargeUpdateByReason"]["tree-dependency"], 1)
        self.assertEqual(got["updateLayoutTree"]["maxElementCount"], 10000)
        self.assertEqual(got["actualDomMutations"]["byTargetRole"]["node"], 1)
        self.assertEqual(got["unverifiedNodeIdFieldsObserved"]["opaque-nodeId"], 1)
        self.assertNotIn(private, json.dumps(got))
        self.assertFalse(got["rootCauseProven"])
        self.assertFalse(got["chromeTraceNodeIdentityVerified"])

    def test_unknown_trace_does_not_prove_zero_or_identity(self):
        a = summarize_causality_window({"traceEvents": []}, None)
        self.assertIsNone(a["updateLayoutTree"]["maxElementCount"])
        self.assertFalse(a["actualDomMutations"]["available"])
        self.assertEqual(a["joinedToNextSameThreadUpdateWithin50Ms"], 0)
        self.assertFalse(a["timingCorrelationProvesCausation"])
        with self.assertRaises(ValueError):
            summarize_causality_window({"traceEvents": [None] * 400001})

    def test_mutation_redaction_and_limits(self):
        secret = "CANARY_PASSWORD_BAD"
        observed = reduce_mutation_window({"records": [
            {"attribute": "style", "role": "studio-shell",
             "ancestors": ["studio-shell", secret], "value": secret},
            {"attribute": "onmousemove", "role": secret,
             "ancestors": [secret]},
            {"attribute": "class", "role": secret, "ancestors": [secret]},
        ], "overflow": 1})
        self.assertEqual(observed["observedAttributes"], 2)
        self.assertEqual(observed["byTargetRole"]["other"], 1)
        self.assertEqual(observed["eventsDroppedAtCap"], 1)
        self.assertNotIn(secret, json.dumps(observed))
        with self.assertRaises(ValueError):
            reduce_mutation_window({"records": [None] * 4001})

    def test_floating_toolbar_is_not_opaque_outside_canvas(self):
        observed = reduce_mutation_window({"records": [
            {"attribute": "style", "role": "node",
             "ancestors": ["studio-shell", "canvas-stage", "world", "nodes-layer", "node"]},
            {"attribute": "style", "role": "floating-toolbar",
             "ancestors": ["studio-shell", "canvas-stage", "canvas-overlay", "floating-toolbar"]},
        ]})
        self.assertEqual(observed["byTargetRole"]["floating-toolbar"], 1)
        self.assertEqual(observed["byTargetRole"]["node"], 1)
        self.assertEqual(len(observed["topActualDomAncestorRoleChains"]), 2)

    def test_fixed_cssom_whitelist(self):
        private = "CANARY_PRIVATE_SELECTOR"
        found = validate_selector_census([
            {"selector": ".ic-node:hover .ic-port-zone", "matches": 6},
            {"selector": private, "matches": 10000},
            {"selector": "img[src='" + private + "']", "matches": 7},
        ])
        self.assertEqual(len(found["candidates"]), 1)
        self.assertEqual(found["candidates"][0]["candidate"], "node-hover-port")
        self.assertNotIn(private, json.dumps(found))
        self.assertFalse(found["sameWindowCausationProven"])


if __name__ == "__main__":
    unittest.main()
