"""Phase14 #111 causal-trace contract: explicitly untrusted synthetic input."""
import unittest
from pathlib import Path

from ops.canvas_phase14_input_111 import (
    DRIVERS, POINTER_INPUT_HOOK, _reduce_trace,
)
from ops.canvas_phase13_pointer_111 import one_window

ROOT=Path(__file__).resolve().parents[1]


class Phase14PointerDriverContractTests(unittest.TestCase):
    def test_driver_is_strictly_scoped_to_real_drag_window(self):
        self.assertEqual(DRIVERS,(
            "native","synthetic","native-handler-blocked"))
        with self.assertRaises(ValueError):
            one_window(None,None,"drag-no-visual",driver="unreviewed")
        with self.assertRaises(ValueError):
            one_window(None,None,"idle-stationary",driver="synthetic")
        with self.assertRaises(ValueError):
            one_window(None,None,"pressed-stationary",
                       driver="native-handler-blocked")

    def test_untrusted_event_reuses_actual_pointer_id(self):
        self.assertIn('s.id=e.pointerId',POINTER_INPUT_HOOK)
        self.assertIn('pointerId:s.id',POINTER_INPUT_HOOK)
        self.assertIn('if(event.isTrusted)',POINTER_INPUT_HOOK)
        self.assertIn('syntheticTrusted:false',POINTER_INPUT_HOOK)
        self.assertIn('op==="dispatch"',POINTER_INPUT_HOOK)
        self.assertIn('s.synthetic++',POINTER_INPUT_HOOK)
        self.assertIn('s.blocked++',POINTER_INPUT_HOOK)
        self.assertIn('e.stopImmediatePropagation()',POINTER_INPUT_HOOK)
        self.assertIn('removeEventListener("pointermove"',POINTER_INPUT_HOOK)
        self.assertIn('removeEventListener("pointerdown"',POINTER_INPUT_HOOK)
        self.assertNotIn("textContent",POINTER_INPUT_HOOK)
        self.assertNotIn("innerHTML",POINTER_INPUT_HOOK)
        self.assertNotIn("outerHTML",POINTER_INPUT_HOOK)
        self.assertNotIn("localStorage",POINTER_INPUT_HOOK)

    def test_reducer_never_exports_raw_traces_or_dom_text(self):
        fixture={
            "eventDriver":"synthetic",
            "physicalMouseMoves":0,"syntheticEvents":3,
            "blockedNativeEvents":0,
            "domMutations":{"byType":{"node.style":0}},
            "structureChanges":{"childListRecords":0},
            "nativeGraphAndMediaStable":True,
            "chrome":{
                "updateLayoutTree":{
                    "largeEventsGE8000":1,"maxElementCount":9185},
                "invalidationEvents":4,
                "joinNearLargeUpdateByReason":{"SyntheticTest":1},
                "rawTrace":"MUST_NOT_LEAK",
            },
            "privateNodeText":"MUST_NOT_LEAK",
        }
        out=_reduce_trace(fixture)
        self.assertEqual(out["syntheticEvents"],3)
        self.assertEqual(out["largeUpdateEvents"],1)
        self.assertNotIn("MUST_NOT_LEAK",repr(out))
        self.assertNotIn("rawTrace",out)
        self.assertNotIn("privateNodeText",out)

    def test_phase14_is_wired_to_real_chromium_and_ci_artifact(self):
        run=(ROOT/"tests/benchmark_studio_phase12_111.py").read_text(
            encoding="utf-8")
        ci=(ROOT/".github/workflows/checks.yml").read_text(
            encoding="utf-8")
        self.assertIn(
            "from ops.canvas_phase14_input_111 import collect",run)
        self.assertIn("phase14=collect_phase14(page,cdp)",run)
        self.assertIn("artifacts/studio-111-phase14",run)
        self.assertIn("artifacts/studio-111-phase14/**",ci)
        self.assertIn(
            "python tests/benchmark_studio_phase12_111.py",ci)


if __name__=="__main__":
    unittest.main()
