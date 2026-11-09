"""Phase19 regression guard: no real changed status label may be suppressed."""
import unittest
from pathlib import Path
from ops.canvas_phase18_status_text_132 import HOOK_JS,validate
from ops.canvas_phase19_identical_status_132 import ORDER

ROOT=Path(__file__).resolve().parents[1]
ROLES=("bottom-save-button","entry-save-button")
WINDOWS=("pre-input-idle","synthetic-move-1","synthetic-move-2","synthetic-move-3")

def sample():
    z=lambda:{"writes":0,"suppressed":0,"identical":0}
    return {"mode":"skip_identical","targetPresence":2,"seenMoveCount":3,
            "restored":True,"noTextOrIdsPersisted":True,
            "visualLabelsPreserved":True,
            "writesByWindow":{k:{r:z() for r in ROLES} for k in WINDOWS}}

class Phase19Tests(unittest.TestCase):
    def test_only_identical_writes_can_be_skipped(self):
        a=sample()
        a["writesByWindow"]["synthetic-move-1"]["bottom-save-button"]={
            "writes":1,"suppressed":1,"identical":1}
        a["writesByWindow"]["synthetic-move-1"]["entry-save-button"]={
            "writes":1,"suppressed":0,"identical":0}
        self.assertEqual(len(validate("skip_identical",a)),4)
        self.assertIn('s.mode==="skip_identical"&&identical',HOOK_JS)

    def test_changed_text_must_be_applied_and_unchanged_semantics_verified(self):
        cases=[]
        altered=sample()
        altered["writesByWindow"]["synthetic-move-1"]["entry-save-button"]={
            "writes":1,"suppressed":1,"identical":0}
        cases.append(altered)
        altered=sample()
        altered["writesByWindow"]["synthetic-move-1"]["entry-save-button"]={
            "writes":1,"suppressed":0,"identical":1}
        cases.append(altered)
        altered=sample()
        altered["visualLabelsPreserved"]=False
        cases.append(altered)
        for i,c in enumerate(cases):
            with self.subTest(case=i),self.assertRaises(ValueError):
                validate("skip_identical",c)

    def test_physical_visual_release_never_claimed(self):
        src=(ROOT/"ops/canvas_phase19_identical_status_132.py").read_text()
        browser=(ROOT/"tests/benchmark_studio_phase12_111.py").read_text()
        ci=(ROOT/".github/workflows/checks.yml").read_text()
        self.assertEqual(ORDER,("observe","skip_identical","observe",
                                "skip_identical","observe"))
        self.assertIn('"productionOptimizationAuthorized":False',src)
        self.assertIn('"realLowEndHardwareMeasured":False',src)
        self.assertIn('phase19=collect_phase19(page,cdp)',browser)
        self.assertIn("artifacts/studio-111-phase19",browser)
        self.assertIn("artifacts/studio-111-phase19/**",ci)
        self.assertIn("Phase19 altered semantic save-status button labels",src)

if __name__=="__main__":
    unittest.main()
