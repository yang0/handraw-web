"""#132 Phase16 probe is diagnostic only; no production script modifications."""
import unittest
from pathlib import Path

from ops.canvas_phase16_drag_init_132 import PROBE_JS, _validate_sample

ROOT=Path(__file__).resolve().parents[1]
ROLES=("global-root","canvas-shell","viewport","node-layer",
       "floating-toolbar","overlay","other")


def sample(name="synthetic-move-1"):
    counts={r:0 for r in ROLES}
    reads={q:dict(counts) for q in (
        "rect","computed","offsetWidth","offsetHeight","offsetTop","offsetLeft")}
    return {"phase":name,"reads":reads,
            "rootAttributes":{"class":dict(counts),"style":dict(counts)},
            "mountCounts":{"added":dict(counts),"removed":dict(counts)},
            "childRecords":2,
            "offsetGettersTracked":4,"restored":True,
            "privateDomValuesPersisted":False}


class CanvasPhase16Tests(unittest.TestCase):
    def test_exactly_six_geometry_methods_and_finite_dom_roles(self):
        s=_validate_sample("synthetic-move-1",sample())
        self.assertFalse(s["forcedSynchronousLayoutProven"])
        self.assertFalse(s["privateDomValuesPersisted"])
        self.assertEqual(len(s["reads"]),6)
        self.assertEqual(len(s["rootAttributes"]),2)
        self.assertEqual(len(s["mountCounts"]),2)

    def test_reject_incomplete_or_privacy_broken_data(self):
        tests=[
            ("synthetic-move-1",dict(sample(),offsetGettersTracked=2)),
            ("synthetic-move-1",dict(sample(),restored=False)),
            ("synthetic-move-1",dict(sample(),privateDomValuesPersisted=True)),
            ("unknown-window",sample()),
            ("synthetic-move-1",dict(sample(),reads={"rawNodeId":"leak"})),
        ]
        for window,payload in tests:
            with self.subTest(window=window),self.assertRaises(ValueError):
                _validate_sample(window,payload)

    def test_real_dom_measurements_are_wrapped_only_in_testing(self):
        self.assertIn('window.__HANDRAW_TESTING__!==true',PROBE_JS)
        self.assertIn('window.getComputedStyle=function',PROBE_JS)
        self.assertIn('Element.prototype.getBoundingClientRect=function',PROBE_JS)
        self.assertIn('Object.defineProperty(HTMLElement.prototype',PROBE_JS)
        self.assertIn('s.attr.observe(el,{attributes:true',PROBE_JS)
        self.assertIn('s.child.observe(document.body,{childList:true,subtree:true})',PROBE_JS)
        self.assertIn('s.origOffsets',PROBE_JS)
        self.assertIn('delete window.__qa132draginit',PROBE_JS)
        for prohibited in ("innerHTML","outerHTML","textContent","localStorage"):
            self.assertNotIn(prohibited,PROBE_JS)

    def test_native_chromium_integration_and_artifact_required(self):
        runner=(ROOT/"tests/benchmark_studio_phase12_111.py").read_text()
        phase15=(ROOT/"ops/canvas_phase15_move_boundary_111.py").read_text()
        ci=(ROOT/".github/workflows/checks.yml").read_text()
        self.assertIn('from ops.canvas_phase16_drag_init_132 import collect',runner)
        self.assertIn('phase16=collect_phase16(page,cdp)',runner)
        self.assertIn('artifacts/studio-111-phase16',runner)
        self.assertIn('artifacts/studio-111-phase16/**',ci)
        self.assertIn('one_trial(page, cdp, *, probe=False)',phase15)
        self.assertIn('summary["phase16"]=probe_data',phase15)
        self.assertIn('python tests/benchmark_studio_phase12_111.py',ci)


if __name__=="__main__":
    unittest.main()
