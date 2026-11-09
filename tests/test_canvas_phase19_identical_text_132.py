"""#132 Phase19 strict test-only identical-text setter and full drag trace."""
import unittest
from pathlib import Path

from ops.canvas_phase18_status_text_132 import HOOK_JS, validate
from ops.canvas_phase19_identical_text_132 import summarize

ROOT=Path(__file__).resolve().parents[1]
ROLES=("bottom-save-button","entry-save-button")

def sample(mode="skip-identical"):
    return {
        "mode":mode,"targetPresence":2,"seenMoveCount":3,
        "restored":True,"noTextOrIdsPersisted":True,
        "visualLabelsPreserved":True,
        "writesByWindow":{
            p:{role:{"writes":0,"suppressed":0,"identical":0}
               for role in ROLES}
            for p in ("pre-input-idle","synthetic-move-1",
                      "synthetic-move-2","synthetic-move-3")
        },
    }

def trial(mode,large):
    return {
        "mode":mode,"largeUpdateEvents":large,"maxElementCount":9185 if large else 2,
        "addedNodeCount":2 if mode=="observe" else 0,
        "nativeGraphUndoAndMediaStable":True,"originalSetterRestored":True,
        "traceWindow":"continuous-3-untrusted-moves",
        "targets":{role:{
            "firstMoveWrites":1,"firstMoveIdentical":1,
            "firstMoveSkipped":int(mode=="skip-identical"),
            "writes":1,"identical":1,"skipped":int(mode=="skip-identical"),
        } for role in ROLES},
    }

class Phase19VisualSafeTests(unittest.TestCase):
    def test_changed_visual_label_is_not_suppressed(self):
        payload=sample()
        payload["writesByWindow"]["synthetic-move-1"]["bottom-save-button"]={
            "writes":2,"suppressed":1,"identical":1}
        validate("skip-identical",payload)
        payload["writesByWindow"]["synthetic-move-1"]["bottom-save-button"]["suppressed"]=2
        with self.assertRaises(ValueError):
            validate("skip-identical",payload)

    def test_semantic_button_labels_remain_exactly_as_requested(self):
        payload=sample()
        payload["visualLabelsPreserved"]=False
        with self.assertRaisesRegex(ValueError,"semantics"):
            validate("skip-identical",payload)

    def test_preinput_never_suppresses_and_all_identical_moves_skip(self):
        payload=sample()
        payload["writesByWindow"]["pre-input-idle"]["bottom-save-button"]={
            "writes":1,"suppressed":1,"identical":1}
        with self.assertRaises(ValueError):
            validate("skip-identical",payload)
        payload=sample()
        payload["writesByWindow"]["synthetic-move-2"]["entry-save-button"]={
            "writes":1,"suppressed":0,"identical":1}
        with self.assertRaises(ValueError):
            validate("skip-identical",payload)

    def test_long_trace_analysis_requires_both_cpu_stable_controls(self):
        modes=["observe","skip-identical","observe","skip-identical","observe"]
        good=[trial(m,int(m=="observe")) for m in modes]
        stats=summarize({"1x":good,"4x":good})
        self.assertTrue(all(x["syntheticControlledSignal"] for x in stats.values()))
        unstable=[trial(m,0) for m in modes]
        stats=summarize({"1x":good,"4x":unstable})
        self.assertFalse(stats["4x"]["syntheticControlledSignal"])
        self.assertTrue(stats["1x"]["syntheticControlledSignal"])
        with self.assertRaises(ValueError):
            summarize({"1x":good})
        with self.assertRaises(ValueError):
            summarize({"1x":good[:-1],"4x":good})

    def test_test_browser_and_redacted_artifact_wiring(self):
        runner=(ROOT/"tests/benchmark_studio_phase12_111.py").read_text()
        ci=(ROOT/".github/workflows/checks.yml").read_text()
        self.assertIn('from ops.canvas_phase19_identical_text_132 import collect as collect_phase19',runner)
        self.assertIn("phase19=collect_phase19(page,cdp)",runner)
        self.assertIn("artifacts/studio-111-phase19/**",ci)
        self.assertIn('window.__HANDRAW_TESTING__!==true',HOOK_JS)
        self.assertIn('s.mode==="skip-identical"&&s.moveIndex>=1&&same',HOOK_JS)
        self.assertIn('Object.defineProperty(Node.prototype,"textContent",s.originalDescriptor)',HOOK_JS)
        self.assertNotIn("innerHTML",HOOK_JS)

if __name__=="__main__":
    unittest.main()
