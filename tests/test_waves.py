import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import portfolio_suites.registry as registry_module
from portfolio_suites.registry import (
    SUITES_ROOT,
    evidence_errors,
    evidence_ineligibility_reason,
    get_suite,
)
from portfolio_suites.waves import WaveRunner, _record_evidence


def _wave(suite_id: str, wave_id: str) -> dict:
    """The manifest wave a recorder call is addressed to."""
    return next(w for w in get_suite(suite_id)["waves"] if w["id"] == wave_id)


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
        with patch(
            "portfolio_suites.registry._load_json",
            wraps=registry_module._load_json,
        ) as load_json:
            results = WaveRunner.run_all(write_evidence=False)
        manifest_reads = [
            call
            for call in load_json.call_args_list
            if call.args and call.args[0].name == "suite.json"
        ]
        self.assertEqual(len(manifest_reads), 8)
        self.assertEqual(len(results), 43)

        verified = [r for r in results if r.passed]
        # Only A1/A3/O2/B2 read donor source; A2 adds the runtime probe when it is available.
        self.assertIn(len(verified), {4, 5})
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
        self.assertEqual(a4.execution_kind, "prototype_check")
        self.assertFalse(a4.passed)
        self.assertTrue(a4.prototype_passed)

        # A5 only fingerprints A11y Kitchen; it never reads it, so it is a prototype.
        a5 = next(r for r in results if r.suite_id == "accessibility" and r.wave_id == "A5")
        self.assertEqual(a5.execution_kind, "prototype_check")
        self.assertFalse(a5.passed)
        self.assertTrue(a5.prototype_passed)

        # O2 and B2 read donor content; the rest only fingerprint or stat it.
        for suite_id, wave_id in (("operator-os", "O2"), ("brand-publishing", "B2")):
            res = next(r for r in results if r.suite_id == suite_id and r.wave_id == wave_id)
            self.assertEqual(res.execution_kind, "verified_analysis")
            self.assertTrue(res.passed)

        for suite_id, wave_ids in (
            ("operator-os", ("O1", "O3", "O4", "O6")),
            ("brand-publishing", ("B1", "B3", "B4", "B6")),
            ("production-house", ("P1", "P2", "P3")),
        ):
            for wave_id in wave_ids:
                res = next(r for r in results if r.suite_id == suite_id and r.wave_id == wave_id)
                self.assertEqual(res.execution_kind, "prototype_check")
                self.assertFalse(res.passed)
                self.assertTrue(res.prototype_passed)

        prototypes = [r for r in results if r.execution_kind == "prototype_check"]
        self.assertEqual(len(prototypes), 38)
        for r in prototypes:
            self.assertTrue(r.prototype_passed, f"Prototype check for {r.suite_id}/{r.wave_id} failed: {r.message}")

        self.assertFalse(any(r.execution_kind == "unintegrated_specification" for r in results))
        self.assertFalse(any(r.execution_kind == "error" for r in results))

        unverified = [r for r in results if not r.passed]
        self.assertIn(len(unverified), {38, 39})

    def test_run_individual_waves(self):
        # A1 and A3 are verified analysis milestones; A2 is runtime recovery.
        a1 = WaveRunner.run_wave("accessibility", "A1", write_evidence=False)
        self.assertTrue(a1.passed)
        self.assertEqual(a1.execution_kind, "verified_analysis")
        self.assertIsNotNone(a1.evidence_path)

        a1_rec = WaveRunner.run_wave("accessibility", "A1", write_evidence=True)
        self.assertTrue(a1_rec.passed)
        self.assertIsNotNone(a1_rec.record_note)
        self.assertIn("read-only", a1_rec.record_note)

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
        self.assertFalse(a4.passed)
        self.assertTrue(a4.prototype_passed)
        self.assertEqual(a4.execution_kind, "prototype_check")

        a5 = WaveRunner.run_wave("accessibility", "A5", write_evidence=False)
        self.assertFalse(a5.passed)
        self.assertTrue(a5.prototype_passed)
        self.assertEqual(a5.execution_kind, "prototype_check")

        # A6 remains a prototype until owner convergence approval is granted
        a6 = WaveRunner.run_wave("accessibility", "A6", write_evidence=False)
        self.assertFalse(a6.passed)
        self.assertTrue(a6.prototype_passed)
        self.assertEqual(a6.execution_kind, "prototype_check")

        # O2 and B2 are the only donor-reading analysis milestones outside accessibility.
        for suite_id, wave_id in (("operator-os", "O2"), ("brand-publishing", "B2")):
            res = WaveRunner.run_wave(suite_id, wave_id, write_evidence=False)
            self.assertTrue(res.passed, f"{suite_id} wave {wave_id} failed: {res.message}")
            self.assertEqual(res.execution_kind, "verified_analysis")
            self.assertIsNone(res.evidence_path)

        # These gates only fingerprint or stat their donor, so they cannot claim an analysis.
        for suite_id, wave_ids in (
            ("operator-os", ("O1", "O3", "O4", "O6")),
            ("brand-publishing", ("B1", "B3", "B4", "B6")),
            ("production-house", ("P1", "P2", "P3")),
        ):
            for wave_id in wave_ids:
                res = WaveRunner.run_wave(suite_id, wave_id, write_evidence=False)
                self.assertFalse(res.passed)
                self.assertTrue(res.prototype_passed, f"{suite_id}/{wave_id}: {res.message}")
                self.assertEqual(res.execution_kind, "prototype_check")

        # Reclassified local-only checks pass as prototypes but not migration acceptance.
        for suite_id, wave_id in (
            ("operator-os", "O5"),
            ("brand-publishing", "B5"),
            ("production-house", "P4"),
            ("production-house", "P5"),
        ):
            result = WaveRunner.run_wave(suite_id, wave_id, write_evidence=False)
            self.assertFalse(result.passed)
            self.assertTrue(result.prototype_passed)
            self.assertEqual(result.execution_kind, "prototype_check")

        # Remaining suite prototypes pass prototype check but do not report passed migration acceptance.
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
        """Recordable analysis waves must write receipts satisfying their evidence basis.

        A1 is reviewed prose and A2 requires its explicit full runtime gate. Redirects SUITES_ROOT
        so retained evidence is untouched. A candidate that would fail `suites validate` is refused.
        """
        cases = (("accessibility", "A3"), ("operator-os", "O2"), ("brand-publishing", "B2"))
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
                result = WaveRunner.run_wave("accessibility", "A2", write_evidence=True, full=True)
                self.assertFalse(result.passed)
                # When passed is False, _record_evidence is invoked with passed=False and writes nothing
                mock_record.assert_called_once()
                recorded_wave, recorded_receipt, requested, gate_passed = mock_record.call_args.args
                # The recorder is addressed by the wave itself; the path is the manifest's.
                self.assertEqual(recorded_wave["id"], "A2")
                self.assertEqual(
                    recorded_wave["evidence"], "accessibility/evidence/A2-WCAG-331-EVIDENCE.json"
                )
                self.assertEqual(recorded_receipt, failing_receipt)
                self.assertTrue(requested)
                self.assertFalse(gate_passed)

    def test_a2_record_requires_explicit_full_depth(self):
        with patch(
            "portfolio_suites.waves.AccessibilitySourceAdapter.execute_wcag_331_migration_gate"
        ) as gate:
            result = WaveRunner.run_wave(
                "accessibility",
                "A2",
                write_evidence=True,
                full=False,
            )
        gate.assert_not_called()
        self.assertFalse(result.passed)
        self.assertIsNone(result.evidence_path)
        self.assertEqual(result.data, {"record_requires_full": True})

    def test_unserializable_candidate_is_rejected_without_raising(self):
        result = _record_evidence(
            _wave("production-house", "P2"),
            {"job": object()},
            write_evidence=True,
            passed=True,
        )
        self.assertIsNone(result)

    def test_failed_operator_record_returns_no_evidence_path(self):
        failed_o1 = {
            "mutation_protection_passed": False,
            "all_stages_passed": False,
            "status": "source_unverified",
            "source_record": {},
            "observer_projection_preview": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch("portfolio_suites.waves.SUITES_ROOT", Path(tmp)):
                with patch(
                    "portfolio_suites.waves.OperatorOSSourceAdapter.execute_o1_source_record_observer_gate",
                    return_value=failed_o1,
                ):
                    result = WaveRunner.run_wave("operator-os", "O1", write_evidence=True)
            self.assertFalse(result.passed)
            self.assertIsNone(result.evidence_path)
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def test_semantically_invalid_candidate_is_not_recorded(self):
        invalid_p2 = {
            "job": None,
            "formatter_fingerprint": "",
            "wave": "P2",
            "status": "formatter_executed",
            "all_stages_passed": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch("portfolio_suites.waves.SUITES_ROOT", Path(tmp)):
                result = _record_evidence(
                    _wave("production-house", "P2"),
                    invalid_p2,
                    write_evidence=True,
                    passed=True,
                )
            self.assertIsNone(result)
            self.assertFalse(
                (Path(tmp) / "production-house/evidence/P2-FORMATTER-JOB-RECEIPT.json").exists()
            )
            evidence_dir = Path(tmp) / "production-house/evidence"
            self.assertEqual(list(evidence_dir.glob(".*")) if evidence_dir.exists() else [], [])

    def test_prototype_writer_uses_authoritative_recorder_return(self):
        with patch("portfolio_suites.waves._record_evidence", return_value=None) as recorder:
            result = WaveRunner.run_wave("model-behavior-lab", "M1", write_evidence=True)
        recorder.assert_called_once()
        self.assertIsNone(result.evidence_path)

    def test_wave_without_recovery_contract_cannot_record_evidence(self):
        # Every shipped wave now declares a claim, so the refusal is exercised against a
        # manifest entry stripped of one: bytes nothing can verify are never written.
        claimless = {key: value for key, value in _wave("model-behavior-lab", "M1").items() if key != "recovery_claim"}
        self.assertIsNotNone(evidence_ineligibility_reason(claimless))
        with tempfile.TemporaryDirectory() as tmp:
            with patch("portfolio_suites.waves.SUITES_ROOT", Path(tmp)):
                written = _record_evidence(claimless, {"wave": "M1"}, write_evidence=True, passed=True)
        self.assertIsNone(written)
        self.assertEqual(list(Path(tmp).rglob("*")), [])

    def test_source_backed_analysis_waves_fail_closed_without_donors(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with (
                patch("portfolio_suites.adapters.operator_os.RYOS_DIR", missing / "ryos"),
                patch(
                    "portfolio_suites.adapters.operator_os.MASTER_UPGRADE_PLAN_DIR",
                    missing / "master-upgrade-plan",
                ),
                patch("portfolio_suites.adapters.operator_os.DOTFILES_DIR", missing / "dotfiles"),
                patch("portfolio_suites.adapters.operator_os.OBSERVER_DIR", missing / "observer"),
            ):
                operator = WaveRunner.run_wave("operator-os", "O2", write_evidence=False)
            with patch(
                "portfolio_suites.adapters.brand_publishing.BRAND_MAKER_DIR",
                missing / "brand-maker-spec",
            ):
                brand = WaveRunner.run_wave("brand-publishing", "B1", write_evidence=False)
            with (
                patch(
                    "portfolio_suites.adapters.production_house.PRODUCTION_HOUSE_DIR",
                    missing / "production-house",
                ),
                patch(
                    "portfolio_suites.adapters.production_house.GROUNDWIRE_DIR",
                    missing / "groundwire",
                ),
                patch(
                    "portfolio_suites.adapters.production_house.FORMATTER_DIR",
                    missing / "formatter",
                ),
            ):
                production = WaveRunner.run_wave("production-house", "P1", write_evidence=False)

        self.assertFalse(operator.passed)
        self.assertFalse(brand.passed)
        self.assertFalse(production.passed)

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
