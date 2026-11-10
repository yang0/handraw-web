"""Phase15 #111: strict temporal labels, data minimization, test wiring."""
import unittest
from pathlib import Path

from ops.canvas_phase15_move_boundary_111 import (
    WINDOWS, PRE_TRACE_READ, _bounded_summary,
)

ROOT=Path(__file__).resolve().parents[1]


class Phase15PointerMoveWindowTests(unittest.TestCase):
    def test_exactly_one_idle_and_three_scripted_move_windows(self):
        self.assertEqual(WINDOWS,(
            "pre-input-idle","synthetic-move-1",
            "synthetic-move-2","synthetic-move-3"))
        self.assertIn("getBoundingClientRect()",PRE_TRACE_READ)
        self.assertIn("getComputedStyle(card)",PRE_TRACE_READ)
        self.assertNotIn("innerHTML",PRE_TRACE_READ)
        self.assertNotIn("textContent",PRE_TRACE_READ)

    def test_summary_is_bounded_and_does_not_leak_trace(self):
        raw={"traceEvents":[
            {"name":"UpdateLayoutTree","ph":"X","ts":120,"pid":2,
             "tid":4,"args":{"data":{"elementCount":9185,
                "dangerous":"PRIVATE_TEXT"}}},
        ]}
        attrs={
            "byType":{"node.style":1},"globalClassMutations":0,
            "privateText":"DO_NOT_EXPORT"}
        structure={"childListRecords":0,"privateContentsPersisted":False}
        r=_bounded_summary("synthetic-move-1",raw,attrs,structure)
        self.assertEqual(r["largeUpdateEvents"],1)
        self.assertEqual(r["maxElementCount"],9185)
        self.assertNotIn("PRIVATE_TEXT",repr(r))
        self.assertNotIn("DO_NOT_EXPORT",repr(r))
        self.assertFalse(r["causalAttributionConfirmed"])
        self.assertFalse(r["rawTracePersisted"])

    def test_unknown_window_and_empty_trace_fail_closed(self):
        with self.assertRaises(ValueError):
            _bounded_summary("imaginary",{"traceEvents":[]},
                             {"byType":{},"globalClassMutations":0},{})
        with self.assertRaises(RuntimeError):
            _bounded_summary("synthetic-move-1",{"traceEvents":[]},
                             {"byType":{},"globalClassMutations":0},{})

    def test_untrusted_events_and_native_undo_are_mandatory(self):
        code=(ROOT/"ops/canvas_phase15_move_boundary_111.py").read_text(
            encoding="utf-8")
        self.assertIn('page.mouse.down()',code)
        self.assertIn('page.mouse.up()',code)
        self.assertIn('POINTER_INPUT_HOOK,"stats"',code)
        self.assertIn('page.keyboard.press("Control+z")',code)
        self.assertIn('stats["seenDown"],stats["synthetic"],stats["blocked"]',code)
        self.assertIn('state["cards"],state["edges"],state["images"]',code)
        self.assertIn("rawTracePersisted",code)
        self.assertNotIn("outerHTML",code)

    def test_real_chromium_ci_runs_phase15_and_keeps_summary(self):
        run=(ROOT/"tests/benchmark_studio_phase12_111.py").read_text(
            encoding="utf-8")
        ci=(ROOT/".github/workflows/checks.yml").read_text(
            encoding="utf-8")
        self.assertIn(
            "from ops.canvas_phase15_move_boundary_111 import collect",run)
        self.assertIn("phase15=collect_phase15(page,cdp)",run)
        self.assertIn("artifacts/studio-111-phase15",run)
        self.assertIn("artifacts/studio-111-phase15/**",ci)
        self.assertIn(
            "python tests/benchmark_studio_phase12_111.py",ci)


if __name__=="__main__":
    unittest.main()
