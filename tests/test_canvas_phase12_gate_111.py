"""#111 Phase12 unit gates: diagnostic wins are never deployable edits."""
import unittest

from ops.canvas_phase12_isolation_111 import gate, CASES, TRACE_MODES


def records(fast):
    rows=[]
    for cpu in (1,4):
        style=150 if cpu==1 else 600
        for i in range(5):
            is_candidate=i%2==1
            s=style*(.80 if is_candidate and fast else (1.10 if is_candidate else 1))
            rows.append({"cpu":cpu,"cdp":{"styleMs":s,"combinedMs":s+10*cpu,
                         "rafP95Ms":40*cpu}})
    return rows


class Phase12Gates111(unittest.TestCase):
    def test_all_branches_covered_without_changing_production(self):
        self.assertEqual(set(CASES),{
            "no-edges","no-card","global-state-selector-mask","no-overlay"})
        self.assertEqual(set(TRACE_MODES),{
            "normal","no-edges","no-card","global-state-selector-mask"})

    def test_diags_can_report_benefit_but_are_not_prod_candidates(self):
        for case in CASES:
            with self.subTest(case=case):
                result=gate(records(True),case)
                self.assertTrue(result["bothCpuBenefitObserved"])
                self.assertTrue(result["diagnosticOnly"])
                self.assertFalse(result["productionCandidate"])
                self.assertTrue(all(v["bothReplicatesPass"]
                                    for v in result["gate"].values()))

    def test_reject_noisy_candidate_and_cpu_mismatch(self):
        rows=records(True)
        # Candidate pass in 1x, but 4x first candidate loses.
        rows[6]["cdp"]["styleMs"]=900
        rows[6]["cdp"]["combinedMs"]=940
        got=gate(rows,"no-edges")
        self.assertTrue(got["gate"]["1x"]["bothReplicatesPass"])
        self.assertFalse(got["gate"]["4x"]["bothReplicatesPass"])
        self.assertFalse(got["bothCpuBenefitObserved"])

    def test_unequal_samples_fail_closed(self):
        with self.assertRaises(AssertionError):
            gate(records(False)[:-1],"no-card")


if __name__=="__main__":
    unittest.main()
