"""Phase13 #111: no production tweak and 5 independent pointer conditions."""
import unittest
from ops.canvas_phase13_pointer_111 import (
    TRACE_WINDOWS, _plan, HOVER_MASK, STRUCTURE_OBSERVER,
)


class Phase13PointerTriageTests(unittest.TestCase):
    def test_no_visual_pointer_conditions_have_explicit_experimental_controls(self):
        self.assertEqual(len(TRACE_WINDOWS),5)
        self.assertEqual(_plan("idle-stationary"),
                         {"pressed":False,"moves":0,"hoverMask":False})
        self.assertEqual(_plan("hover-moving"),
                         {"pressed":False,"moves":3,"hoverMask":False})
        self.assertEqual(_plan("pressed-stationary"),
                         {"pressed":True,"moves":0,"hoverMask":False})
        self.assertEqual(_plan("drag-no-visual"),
                         {"pressed":True,"moves":3,"hoverMask":False})
        self.assertEqual(_plan("drag-no-visual-hover-mask"),
                         {"pressed":True,"moves":3,"hoverMask":True})
    def test_structure_observer_is_bounded_and_content_free(self):
        self.assertIn("childList:true,characterData:true", STRUCTURE_OBSERVER)
        self.assertIn("eventsDroppedAtCap", STRUCTURE_OBSERVER)
        self.assertIn("privateContentsPersisted:false", STRUCTURE_OBSERVER)
        self.assertIn("s.total++>=5000", STRUCTURE_OBSERVER)
        self.assertNotIn("textContent", STRUCTURE_OBSERVER)
        self.assertNotIn("outerHTML", STRUCTURE_OBSERVER)
        self.assertNotIn("innerHTML", STRUCTURE_OBSERVER)
        self.assertNotIn("getAttribute(", STRUCTURE_OBSERVER)

    def test_pointer_mode_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            _plan("pretend-passed-prod")
    def test_cssom_controls_restore_precise_original_rules(self):
        self.assertIn("rule.selectorText=original",HOVER_MASK)
        self.assertIn(".ic-node:hover .ic-port-zone",HOVER_MASK)
        self.assertIn(".ic-node:hover .ic-node-header-above",HOVER_MASK)
        self.assertIn('if(mode!=="mask")',HOVER_MASK)
        self.assertNotIn("CSSStyleSheet.prototype",HOVER_MASK)


if __name__=="__main__":
    unittest.main()
