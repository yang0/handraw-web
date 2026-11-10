"""#132 Phase18: schema + test-only browser instrumentation guard."""
import unittest
from pathlib import Path

from ops.canvas_phase18_status_text_132 import (
    HOOK_JS, MOVE_WINDOWS, ORDER, ROLES, validate,
)

ROOT=Path(__file__).resolve().parents[1]


def sample(mode="observe"):
    zero=lambda:{"writes":0,"suppressed":0,"identical":0}
    return {
        "mode":mode,"targetPresence":2,"seenMoveCount":3,
        "restored":True,"noTextOrIdsPersisted":True,
        "writesByWindow":{
            name:{role:zero() for role in ROLES} for name in MOVE_WINDOWS
        },
    }


class Phase18SaveTextTests(unittest.TestCase):
    def test_valid_modes_and_full_capture(self):
        for mode in ORDER:
            report=sample(mode)
            for role in ROLES:
                report["writesByWindow"]["synthetic-move-1"][role]={
                    "writes":1,"suppressed":int(mode=="suppress"),"identical":0}
            out=validate(mode,report)
            self.assertEqual(set(out),set(MOVE_WINDOWS))
        self.assertEqual(ORDER,("observe","suppress","observe","suppress","observe"))

    def test_fail_closed_when_intervention_or_restore_is_not_proven(self):
        failed=[]
        bad=sample("suppress")
        bad["writesByWindow"]["synthetic-move-1"]["bottom-save-button"]["writes"]=1
        failed.append(("suppress",bad))
        bad=sample()
        bad["restored"]=False
        failed.append(("observe",bad))
        bad=sample()
        bad["seenMoveCount"]=2
        failed.append(("observe",bad))
        bad=sample()
        bad["writesByWindow"]["synthetic-move-1"]["unexpected-node"]={}
        failed.append(("observe",bad))
        bad=sample()
        bad["writesByWindow"]["synthetic-move-1"]["entry-save-button"]["writes"]=999999
        failed.append(("observe",bad))
        bad=sample()
        bad["noTextOrIdsPersisted"]=False
        failed.append(("observe",bad))
        for mode,fixture in failed:
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                validate(mode,fixture)

    def test_only_two_known_buttons_and_untrusted_pointer_events(self):
        self.assertIn('window.__HANDRAW_TESTING__!==true',HOOK_JS)
        self.assertIn('getElementById("bl-save-project")',HOOK_JS)
        self.assertIn('getElementById("studio-project-status")',HOOK_JS)
        self.assertIn('!ev.isTrusted',HOOK_JS)
        self.assertIn('Object.defineProperty(Node.prototype,"textContent",s.originalDescriptor)',HOOK_JS)
        self.assertIn('window.removeEventListener("pointermove",s.onPointerMove,true)',HOOK_JS)
        self.assertNotIn("innerHTML",HOOK_JS)
        self.assertNotIn("localStorage",HOOK_JS)

    def test_native_browser_and_redacted_artifact_wired(self):
        runner=(ROOT/"tests/benchmark_studio_phase12_111.py").read_text()
        workflow=(ROOT/".github/workflows/checks.yml").read_text()
        self.assertIn("from ops.canvas_phase18_status_text_132 import collect as collect_phase18",runner)
        self.assertIn("phase18=collect_phase18(page,cdp)",runner)
        self.assertIn("artifacts/studio-111-phase18",runner)
        self.assertIn("artifacts/studio-111-phase18/**",workflow)
        self.assertIn("python tests/benchmark_studio_phase12_111.py",workflow)


if __name__=="__main__":
    unittest.main()
