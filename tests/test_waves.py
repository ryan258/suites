import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.registry import SUITES_ROOT, evidence_errors, get_suite
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
        self.assertIn(len(verified), {21, 22})
        a1 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A1")
        self.assertEqual(a1.execution_kind, "verified_analysis")
        self.assertTrue(a1.passed)

        a2 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A2")
        # A fast probe cannot claim the manifest's runtime recovery; only a --full run can.
        self.assertIn(a2.execution_kind, {"fast_probe", "unverifiable_environment"})
        if a2.execution_kind == "fast_probe":
            self.assertTrue(a2.passed)
        else:
            self.assertFalse(a2.passed)

        a3 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A3")
        self.assertEqual(a3.execution_kind, "verified_analysis")
        self.assertTrue(a3.passed)

        a4 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A4")
        self.assertEqual(a4.execution_kind, "verified_analysis")
        self.assertTrue(a4.passed)

        a5 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A5")
        self.assertEqual(a5.execution_kind, "verified_analysis")
        self.assertTrue(a5.passed)

        for wave_id in ("O1", "O2", "O3", "O4", "O5", "O6"):
            o_res = next(r for r in results if r.suite_id == "operator-os" and r.wave_id == wave_id)
            self.assertEqual(o_res.execution_kind, "verified_analysis")
            self.assertTrue(o_res.passed)

        for wave_id in ("B1", "B2", "B3", "B4", "B5", "B6"):
            b_res = next(r for r in results if r.suite_id == "brand-publishing" and r.wave_id == wave_id)
            self.assertEqual(b_res.execution_kind, "verified_analysis")
            self.assertTrue(b_res.passed)

        for wave_id in ("P1", "P2", "P3", "P4", "P5"):
            p_res = next(r for r in results if r.suite_id == "production-house" and r.wave_id == wave_id)
            self.assertEqual(p_res.execution_kind, "verified_analysis")
            self.assertTrue(p_res.passed)

        prototypes = [r for r in results if r.execution_kind == "prototype_check"]
        self.assertEqual(len(prototypes), 21)
        for r in prototypes:
            self.assertTrue(r.prototype_passed, f"Prototype check for {r.suite_id}/{r.wave_id} failed: {r.message}")

        self.assertFalse(any(r.execution_kind == "unintegrated_specification" for r in results))
        self.assertFalse(any(r.execution_kind == "error" for r in results))

        unverified = [r for r in results if not r.passed]
        self.assertIn(len(unverified), {21, 22})

    def test_run_individual_waves(self):
        # A1, A3, A4, A5 are verified analysis milestones; A2 is runtime recovery
        a1 = WaveRunner.run_wave("accessibility", "A1", write_evidence=False)
        self.assertTrue(a1.passed)
        self.assertEqual(a1.execution_kind, "verified_analysis")
        self.assertIsNotNone(a1.evidence_path)

        a2 = WaveRunner.run_wave("accessibility", "A2", write_evidence=False)
        if a2.execution_kind == "fast_probe":
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

        a3 = WaveRunner.run_wave("accessibility", "A3", write_evidence=False)
        self.assertTrue(a3.passed)
        self.assertEqual(a3.execution_kind, "verified_analysis")

        a4 = WaveRunner.run_wave("accessibility", "A4", write_evidence=False)
        self.assertTrue(a4.passed)
        self.assertEqual(a4.execution_kind, "verified_analysis")

        a5 = WaveRunner.run_wave("accessibility", "A5", write_evidence=False)
        self.assertTrue(a5.passed)
        self.assertEqual(a5.execution_kind, "verified_analysis")

        # A6 remains a prototype until owner convergence approval is granted
        a6 = WaveRunner.run_wave("accessibility", "A6", write_evidence=False)
        self.assertFalse(a6.passed)
        self.assertTrue(a6.prototype_passed)
        self.assertEqual(a6.execution_kind, "prototype_check")

        # O1-O6 in operator-os are verified analysis milestones
        for wave_id in ("O1", "O2", "O3", "O4", "O5", "O6"):
            o_res = WaveRunner.run_wave("operator-os", wave_id, write_evidence=False)
            self.assertTrue(o_res.passed, f"Operator OS wave {wave_id} failed: {o_res.message}")
            self.assertEqual(o_res.execution_kind, "verified_analysis")
            self.assertIsNone(o_res.evidence_path)

        # B1-B6 in brand-publishing are verified analysis milestones
        for wave_id in ("B1", "B2", "B3", "B4", "B5", "B6"):
            b_res = WaveRunner.run_wave("brand-publishing", wave_id, write_evidence=False)
            self.assertTrue(b_res.passed, f"Brand Publishing wave {wave_id} failed: {b_res.message}")
            self.assertEqual(b_res.execution_kind, "verified_analysis")
            self.assertIsNone(b_res.evidence_path)

        # P1-P5 in production-house are verified analysis milestones
        for wave_id in ("P1", "P2", "P3", "P4", "P5"):
            p_res = WaveRunner.run_wave("production-house", wave_id, write_evidence=False)
            self.assertTrue(p_res.passed, f"Production House wave {wave_id} failed: {p_res.message}")
            self.assertEqual(p_res.execution_kind, "verified_analysis")
            self.assertIsNone(p_res.evidence_path)

        # Remaining suite prototypes pass prototype check but do not report passed migration acceptance
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

    def test_completed_waves_record_valid_evidence(self):
        """Record mode must write a receipt that satisfies the wave's own declared evidence basis.

        Redirects SUITES_ROOT so retained evidence is untouched. A recorded artifact that would
        fail `suites validate` is refused by the recorder, so evidence_path comes back None.
        """
        cases = (
            [("accessibility", f"A{i}") for i in range(3, 6)]
            + [("operator-os", f"O{i}") for i in range(1, 7)]
            + [("brand-publishing", f"B{i}") for i in range(1, 7)]
            + [("production-house", f"P{i}") for i in range(1, 6)]
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("portfolio_suites.waves.SUITES_ROOT", Path(tmp)):
                for suite_id, wave_id in cases:
                    res = WaveRunner.run_wave(suite_id, wave_id, write_evidence=True)
                    self.assertTrue(res.passed, f"{suite_id} {wave_id}: {res.message}")
                    self.assertIsNotNone(
                        res.evidence_path,
                        f"{suite_id} {wave_id}: recorded receipt was rejected by its evidence contract",
                    )
                    self.assertTrue(
                        Path(res.evidence_path).is_file(),
                        f"{suite_id} {wave_id} recorded no evidence file",
                    )
                    errors = evidence_errors(
                        next(w for w in get_suite(suite_id)["waves"] if w["id"] == wave_id),
                        Path(res.evidence_path),
                    )
                    self.assertEqual(errors, [], f"{suite_id} {wave_id} recorded invalid evidence")

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

    def test_invalid_candidate_leaves_retained_receipt_byte_identical(self):
        """A record attempt that violates the evidence contract must not touch the prior receipt."""
        retained = SUITES_ROOT / "accessibility" / "evidence" / "A4-WCAG-RULE-CANDIDATES-EVIDENCE.json"
        before = retained.read_bytes()
        short_receipt = {"all_stages_passed": True, "wave": "A4", "catalog_evaluation": {}}
        with patch(
            "portfolio_suites.waves.AccessibilitySourceAdapter.execute_wcag_rule_candidates_gate",
            return_value=short_receipt,
        ):
            res = WaveRunner.run_wave("accessibility", "A4", write_evidence=True)
        self.assertIsNone(res.evidence_path)
        self.assertEqual(retained.read_bytes(), before)
        self.assertEqual(list(retained.parent.glob(".*tmp*")), [])

    def test_fast_probe_cannot_claim_runtime_recovery(self):
        """Skipped deep gates downgrade the manifest's runtime claim to a fast probe."""
        skipped_receipt = {
            "all_stages_passed": True,
            "stages": {
                "focused_parity_gate": {"passed": True, "passed_tests": 6},
                "full_suite_and_typecheck_gate": {"skipped": True, "passed": None},
                "full_audit_integration_gate": {"skipped": True, "passed": None},
            },
            "findings": [{"finding_id": "f1"}],
        }
        with patch(
            "portfolio_suites.waves.AccessibilitySourceAdapter.execute_wcag_331_migration_gate",
            return_value=skipped_receipt,
        ):
            res = WaveRunner.run_wave("accessibility", "A2", write_evidence=False)
        self.assertEqual(res.execution_kind, "fast_probe")
        self.assertIn("HISTORICAL PARITY RECEIPT RETAINED", res.message)


if __name__ == "__main__":
    unittest.main()
