import unittest

from portfolio_suites.waves import WaveRunner


class WaveTests(unittest.TestCase):
    def test_run_all_waves(self):
        results = WaveRunner.run_all(write_evidence=False)
        self.assertEqual(len(results), 43)

        verified = [r for r in results if r.passed]
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].suite_id, "accessibility")
        self.assertEqual(verified[0].wave_id, "A1")
        self.assertEqual(verified[0].execution_kind, "verified_migration")

        prototypes = [r for r in results if r.execution_kind == "prototype_check"]
        self.assertEqual(len(prototypes), 42)
        for r in prototypes:
            self.assertTrue(r.prototype_passed, f"Prototype check for {r.suite_id}/{r.wave_id} failed: {r.message}")

        self.assertFalse(verified[0].prototype_passed)
        self.assertFalse(any(r.execution_kind == "unintegrated_specification" for r in results))
        self.assertFalse(any(r.execution_kind == "error" for r in results))

        # The 42 prototypes must not be reported as passed migration gates.
        unverified = [r for r in results if not r.passed]
        self.assertEqual(len(unverified), 42)

    def test_run_individual_waves(self):
        # A1 is verified migration
        a1 = WaveRunner.run_wave("accessibility", "A1", write_evidence=False)
        self.assertTrue(a1.passed)
        self.assertEqual(a1.execution_kind, "verified_migration")
        self.assertFalse(a1.prototype_passed)
        self.assertIsNotNone(a1.evidence_path)

        # Prototypes pass prototype check but do not report passed migration acceptance
        a2 = WaveRunner.run_wave("accessibility", "A2", write_evidence=False)
        self.assertFalse(a2.passed)
        self.assertTrue(a2.prototype_passed)
        self.assertEqual(a2.execution_kind, "prototype_check")
        self.assertIsNotNone(a2.data)
        self.assertIsNone(a2.evidence_path)

        o1 = WaveRunner.run_wave("operator-os", "O1", write_evidence=False)
        self.assertFalse(o1.passed)
        self.assertTrue(o1.prototype_passed)

        b1 = WaveRunner.run_wave("brand-publishing", "B1", write_evidence=False)
        self.assertFalse(b1.passed)
        self.assertTrue(b1.prototype_passed)

        m4 = WaveRunner.run_wave("model-behavior-lab", "M4", write_evidence=False)
        self.assertFalse(m4.passed)
        self.assertTrue(m4.prototype_passed)

        d2 = WaveRunner.run_wave("discovery-decision", "D2", write_evidence=False)
        self.assertFalse(d2.passed)
        self.assertTrue(d2.prototype_passed)

        r1 = WaveRunner.run_wave("agent-reliability", "R1", write_evidence=False)
        self.assertFalse(r1.passed)
        self.assertTrue(r1.prototype_passed)

        g1 = WaveRunner.run_wave("game-design", "G1", write_evidence=False)
        self.assertFalse(g1.passed)
        self.assertTrue(g1.prototype_passed)

        missing = WaveRunner.run_wave("missing-suite", "X1", write_evidence=False)
        self.assertEqual(missing.execution_kind, "error")
        self.assertFalse(missing.passed)
        self.assertFalse(missing.prototype_passed)


if __name__ == "__main__":
    unittest.main()
