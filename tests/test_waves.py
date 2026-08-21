import unittest
from unittest.mock import patch

from portfolio_suites.waves import WaveRunner


class WaveTests(unittest.TestCase):
    def test_environment_blocker_is_neither_pass_nor_product_failure(self):
        receipt = {
            "all_stages_passed": False,
            "environment_blocked": True,
            "findings": [],
            "operational_errors": [{"environment_blocked": True}],
            "stages": {
                "focused_parity_gate": {"passed_tests": 0},
                "full_suite_and_typecheck_gate": {"skipped": True},
            },
        }
        with patch(
            "portfolio_suites.waves.AccessibilitySourceAdapter.execute_wcag_331_migration_gate",
            return_value=receipt,
        ):
            result = WaveRunner.run_wave("accessibility", "A2", write_evidence=False)
        self.assertFalse(result.passed)
        self.assertFalse(result.prototype_passed)
        self.assertEqual(result.execution_kind, "unverifiable_environment")

    def test_run_all_waves(self):
        results = WaveRunner.run_all(write_evidence=False)
        self.assertEqual(len(results), 43)

        verified = [r for r in results if r.passed]
        self.assertIn(len(verified), {1, 2})
        self.assertEqual(verified[0].suite_id, "accessibility")
        self.assertEqual(verified[0].wave_id, "A1")
        self.assertEqual(verified[0].execution_kind, "verified_analysis")
        a2 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A2")
        self.assertIn(a2.execution_kind, {"verified_runtime_recovery", "unverifiable_environment"})
        if a2.execution_kind == "verified_runtime_recovery":
            self.assertTrue(a2.passed)
        else:
            self.assertFalse(a2.passed)

        prototypes = [r for r in results if r.execution_kind == "prototype_check"]
        self.assertEqual(len(prototypes), 41)
        for r in prototypes:
            self.assertTrue(r.prototype_passed, f"Prototype check for {r.suite_id}/{r.wave_id} failed: {r.message}")

        self.assertFalse(any(r.execution_kind == "unintegrated_specification" for r in results))
        self.assertFalse(any(r.execution_kind == "error" for r in results))

        # The 41 prototypes must not be reported as passed migration gates.
        unverified = [r for r in results if not r.passed]
        self.assertIn(len(unverified), {41, 42})

    def test_run_individual_waves(self):
        # A1 is verified migration
        a1 = WaveRunner.run_wave("accessibility", "A1", write_evidence=False)
        self.assertTrue(a1.passed)
        self.assertEqual(a1.execution_kind, "verified_analysis")
        self.assertIsNotNone(a1.evidence_path)

        # A2 passes full multi-stage runtime gates with genuine donor parity evaluation
        a2 = WaveRunner.run_wave("accessibility", "A2", write_evidence=False)
        if a2.execution_kind == "verified_runtime_recovery":
            self.assertTrue(a2.passed)
            self.assertEqual(a2.data.get("receipt_kind"), "clean_commit_receipt")
            self.assertEqual(a2.data.get("status"), "parity_verified")
            self.assertTrue(a2.data.get("all_stages_passed"))
            self.assertTrue(a2.data.get("donor", {}).get("donor_parity_verified"))
            self.assertEqual(len(a2.data.get("operational_errors", [])), 0)
        else:
            self.assertEqual(a2.execution_kind, "unverifiable_environment")
            self.assertFalse(a2.passed)
            self.assertTrue(a2.data.get("environment_blocked"))

        # Prototypes pass prototype check but do not report passed migration acceptance
        a3 = WaveRunner.run_wave("accessibility", "A3", write_evidence=False)
        self.assertFalse(a3.passed)
        self.assertTrue(a3.prototype_passed)
        self.assertEqual(a3.execution_kind, "prototype_check")

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

    def test_failed_record_does_not_overwrite_evidence(self):
        failing_receipt = {
            "all_stages_passed": False,
            "environment_blocked": True,
            "findings": [],
            "operational_errors": [{"environment_blocked": True}],
        }
        with patch(
            "portfolio_suites.waves.AccessibilitySourceAdapter.execute_wcag_331_migration_gate",
            return_value=failing_receipt,
        ):
            with patch("portfolio_suites.waves._record_evidence") as mock_record:
                mock_record.return_value = None
                result = WaveRunner.run_wave("accessibility", "A2", write_evidence=True)
                self.assertFalse(result.passed)
                # When passed is False, _record_evidence is invoked with passed=False and writes nothing
                mock_record.assert_called_once_with(
                    "accessibility",
                    "A2-WCAG-331-EVIDENCE.json",
                    failing_receipt,
                    True,
                    False,
                )


if __name__ == "__main__":
    unittest.main()
