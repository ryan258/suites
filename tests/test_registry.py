import unittest
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from portfolio_suites.registry import (
    SUITES_ROOT,
    _analysis_evidence_errors,
    apply_snapshot_updates,
    _analysis_receipt_semantic_errors,
    _git_value,
    _runtime_parity_receipt_errors,
    get_portfolio_summary,
    load_ledger,
    load_recovery_standard,
    load_suites,
    validate_registry,
)
from portfolio_suites.registry import evidence_errors as registry_evidence_errors


class RegistryTests(unittest.TestCase):
    def test_git_probe_is_bounded_and_reports_timeout_as_unavailable(self):
        with patch(
            "portfolio_suites.registry.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["git", "status"], timeout=5),
        ) as run:
            value = _git_value(Path("/tmp/example"), "status", "--porcelain")
        self.assertEqual(value, "unavailable")
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_eight_suite_boundaries_exist(self):
        self.assertEqual(len(load_suites()), 8)

    def test_every_snapshot_directory_has_a_disposition(self):
        rows = load_ledger()["projects"]
        self.assertEqual(len(rows), 70)
        self.assertTrue(all(row["disposition"] and row["migration"] for row in rows))

    def test_registry_and_live_tree_are_consistent(self):
        report = validate_registry(check_live=True)
        self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_accessibility_parity_fixture_catalog_is_complete(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "accessibility/evidence/A1-parity-cases.json").read_text())
        ids = [case["id"] for case in data["cases"]]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(case["setup"] and case["expected"] for case in data["cases"]))

    def test_nine_out_of_ten_recovery_standard_is_enforced(self):
        standard = load_recovery_standard()
        self.assertEqual(standard["target_score"], 9.0)
        self.assertEqual(sum(row["weight"] for row in standard["dimensions"]), 100)
        self.assertEqual(standard["enforcement"]["minimum_authentic_uses_for_adoption"], 3)
        classified = [suite for tier in standard["portfolio_tiers"] for suite in tier["suites"]]
        self.assertEqual(sorted(classified), sorted(load_suites()))

    def test_recovery_enforcement_cannot_be_disabled(self):
        standard = deepcopy(load_recovery_standard())
        standard["enforcement"]["retirement_requires_owner_approval"] = False
        standard["enforcement"]["prototype_never_counts_as_recovered"] = False
        with patch("portfolio_suites.registry.load_recovery_standard", return_value=standard):
            report = validate_registry(check_live=False)
        self.assertIn(
            "recovery enforcement rules do not match the fail-closed policy",
            report.errors,
        )

    def test_recovery_tier_targets_are_enforced(self):
        standard = deepcopy(load_recovery_standard())
        standard["portfolio_tiers"][0]["target_score"] = 1.0
        with patch("portfolio_suites.registry.load_recovery_standard", return_value=standard):
            report = validate_registry(check_live=False)
        self.assertIn(
            "recovery tiers, targets, or suite assignments do not match policy",
            report.errors,
        )

    def test_recovery_dimensions_are_exact_and_well_formed(self):
        standard = deepcopy(load_recovery_standard())
        standard["dimensions"] = [{"id": "anything", "weight": 100, "requirement": "weak"}]
        with patch("portfolio_suites.registry.load_recovery_standard", return_value=standard):
            report = validate_registry(check_live=False)
        self.assertIn(
            "recovery standard dimensions or weights do not match the adopted rubric",
            report.errors,
        )

    def test_runtime_parity_receipt_requires_authentic_donor_evidence(self):
        with TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text(json.dumps({"all_stages_passed": True}), encoding="utf-8")
            errors = _runtime_parity_receipt_errors(receipt, "accessibility-wcag-331-v1")
        self.assertIn(
            "runtime parity receipt must prove authentic donor execution and parity",
            errors,
        )

    def test_analysis_evidence_must_contain_its_declared_basis(self):
        with TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text(json.dumps({"job": {}, "formatter_fingerprint": "abc"}), encoding="utf-8")
            self.assertEqual(_analysis_evidence_errors(receipt, {"job", "formatter_fingerprint"}), [])
            self.assertEqual(
                _analysis_evidence_errors(receipt, {"job", "output_parity"}),
                ["analysis evidence does not contain its declared basis: output_parity"],
            )

            prose = Path(directory) / "receipt.md"
            prose.write_text("# A1\n\n## Retirement gate\n", encoding="utf-8")
            self.assertEqual(_analysis_evidence_errors(prose, {"## Retirement gate"}), [])
            self.assertEqual(
                _analysis_evidence_errors(prose, {"## Missing section"}),
                ["analysis evidence does not contain its declared basis: ## Missing section"],
            )

    def test_analysis_receipt_rejects_null_and_empty_semantic_values(self):
        errors = _analysis_receipt_semantic_errors(
            {"id": "P2"},
            {
                "wave": "P2",
                "status": "formatter_executed",
                "all_stages_passed": True,
                "job": None,
                "formatter_fingerprint": "",
            },
        )
        self.assertTrue(any("job must be a non-empty object" in error for error in errors))
        self.assertTrue(any("meaningful source fingerprint" in error for error in errors))

    def test_analysis_receipt_accepts_expected_false_boundary_value(self):
        fingerprint = {
            "branch": "main",
            "head": "a" * 40,
            "tested_files_fingerprint": {"README.md": "b" * 64},
        }
        errors = _analysis_receipt_semantic_errors(
            {"id": "O6"},
            {
                "wave_id": "O6",
                "status": "checkpoint_lifecycle_verified",
                "multi_action_lifecycle_passed": True,
                "disk_mutations_performed": False,
                "fail_closed_test": {"verified": True},
                "preview_test": {"verified": True},
                "jarvis_fingerprint": fingerprint,
            },
        )
        self.assertEqual(errors, [])

    def test_a3_v2_receipt_requires_verified_donor_measurements(self):
        errors = _analysis_receipt_semantic_errors(
            {"id": "A3"},
            {
                "receipt_version": "accessibility-a3-analysis-v2",
                "canonical_target": "kb-overlay",
                "recommendation": "candidate only",
                "source_verification": {
                    "passed": False,
                    "errors": ["donor missing"],
                    "donors_checked": 3,
                },
                "matrix": {
                    name: {"features": ["spatial_nav"], "code_size_bytes": 1}
                    for name in (
                        "kb-overlay",
                        "keyboard-nav-overlay",
                        "keyboard-nav-overlay-94bf7e",
                    )
                },
            },
        )
        self.assertTrue(any("clean three-donor pass" in error for error in errors))
        self.assertTrue(any("verified source measurements" in error for error in errors))

    def test_a3_receipt_containing_only_source_inventory_cannot_claim_parity_verified(self):
        errors = _analysis_receipt_semantic_errors(
            {
                "id": "A3",
                "recovery_claim": {
                    "kind": "analysis",
                    "level": "parity_verified",
                    "real_runtime": False,
                },
            },
            {
                "receipt_version": "accessibility-a3-analysis-v2",
                "canonical_target": "kb-overlay",
                "recommendation": "candidate only",
                "source_verification": {
                    "passed": True,
                    "errors": [],
                    "donors_checked": 3,
                },
                "matrix": {
                    name: {
                        "source_available": True,
                        "manifest_valid": True,
                        "fingerprint_verified": True,
                        "features": ["spatial_nav"],
                        "code_size_bytes": 100,
                        "git_fingerprint": {"branch": "main", "head": "a" * 40},
                    }
                    for name in (
                        "kb-overlay",
                        "keyboard-nav-overlay",
                        "keyboard-nav-overlay-94bf7e",
                    )
                },
            },
        )
        self.assertTrue(any("cannot substantiate a parity_verified claim" in error for error in errors))

    def test_a3_parity_guard_survives_missing_or_unknown_receipt_version(self):
        def receipt(**overrides):
            document = {
                "receipt_version": "accessibility-a3-analysis-v2",
                "canonical_target": "kb-overlay",
                "recommendation": "candidate only",
                "matrix": {
                    name: {"features": ["spatial_nav"], "code_size_bytes": 100}
                    for name in ("kb-overlay", "keyboard-nav-overlay", "keyboard-nav-overlay-94bf7e")
                },
            }
            document.update(overrides)
            if overrides.get("receipt_version") is None and "receipt_version" in overrides:
                del document["receipt_version"]
            return document

        wave = {
            "id": "A3",
            "recovery_claim": {"kind": "analysis", "level": "parity_verified", "real_runtime": False},
        }
        for overrides in ({"receipt_version": None}, {"receipt_version": ""}, {"receipt_version": "accessibility-a3-analysis-v1"}):
            errors = _analysis_receipt_semantic_errors(wave, receipt(**overrides))
            self.assertTrue(any("cannot substantiate a parity_verified claim" in error for error in errors), overrides)
            self.assertTrue(any("receipt_version must be" in error for error in errors), overrides)

    def test_summary_separates_analysis_from_runtime_recovery(self):
        summary = get_portfolio_summary()
        self.assertEqual(summary["recovery_target_score"], 9.0)
        self.assertEqual(summary["verified_analysis_milestones"], 4)
        self.assertEqual(summary["recovered_runtime_behaviors"], 1)
        self.assertEqual(summary["adopted_runtime_behaviors"], 0)
        self.assertEqual(summary["converged_runtime_behaviors"], 0)

    def test_validate_rejects_a_corrupted_prototype_receipt(self):
        """A retained prototype receipt is re-checked by the canonical validator, not only at record time."""
        suites = deepcopy(load_suites())
        wave = next(w for w in suites["model-behavior-lab"]["waves"] if w["id"] == "M1")
        scratch = SUITES_ROOT / "model-behavior-lab" / "evidence" / ".validate-regression.json"
        retained = json.loads((SUITES_ROOT / wave["evidence"]).read_text(encoding="utf-8"))
        retained["field_parity"]["all_fields_match"] = False
        wave["evidence"] = "model-behavior-lab/evidence/.validate-regression.json"
        try:
            scratch.write_text(json.dumps(retained), encoding="utf-8")
            with patch("portfolio_suites.registry.load_suites", return_value=suites):
                report = validate_registry(check_live=False)
        finally:
            scratch.unlink(missing_ok=True)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("M1" in error and "field_parity.all_fields_match" in error for error in report.errors),
            report.errors,
        )

    def test_validate_checks_every_declared_claim_not_only_completed_waves(self):
        inspected: list[str] = []
        real_errors = registry_evidence_errors

        def spy(wave, path):
            inspected.append(str(wave.get("id")))
            return real_errors(wave, path)

        with patch("portfolio_suites.registry.evidence_errors", side_effect=spy):
            validate_registry(check_live=False)
        for wave_id in ("M1", "D3", "R5", "G2", "A6"):
            with self.subTest(wave=wave_id):
                self.assertIn(wave_id, inspected)


if __name__ == "__main__":
    unittest.main()


class UnsupportedEvidenceContractTests(unittest.TestCase):
    """A receipt no contract can check must be refused, not silently accepted."""

    def _wave(self, kind, level="adopted"):
        return {
            "id": "X1",
            "recovery_claim": {"kind": kind, "level": level, "evidence_basis": ["something"]},
        }

    def test_claim_kinds_without_a_receipt_contract_are_refused(self):
        from portfolio_suites.registry import evidence_errors

        missing = Path("/nonexistent/receipt.json")
        for kind in ("adoption", "convergence", "resolution"):
            with self.subTest(kind=kind):
                errors = evidence_errors(self._wave(kind), missing)
                self.assertTrue(errors)
                self.assertIn("no versioned evidence receipt contract", errors[0])

    def test_runtime_below_parity_is_refused(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(self._wave("runtime", "source_verified"), Path("/nonexistent/receipt.json"))
        self.assertTrue(errors)
        self.assertIn("no versioned evidence receipt contract", errors[0])

    def test_contracted_claim_kinds_are_still_evaluated(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(self._wave("runtime", "parity_verified"), Path("/nonexistent/receipt.json"))
        self.assertTrue(errors)
        self.assertNotIn("no versioned evidence receipt contract", errors[0])


class ApplySnapshotUpdatesTest(unittest.TestCase):
    LEDGER = (
        '{\n  "projects": [\n'
        '    {"name":"alpha","source_snapshot":{"git":true,"head":"aaa","status_lines":0}},\n'
        '    {"name":"beta","source_snapshot":{"git":true,"head":"bbb","status_lines":2,"status_sha256":"kept"}},\n'
        '    {"name":"gamma","source_snapshot":{"git":false}}\n'
        '  ]\n}\n'
    )

    def test_rewrites_only_named_rows_and_preserves_layout(self):
        text, updated = apply_snapshot_updates(
            self.LEDGER,
            {
                "alpha": {"git": True, "head": "aaa", "status_lines": 0, "status_sha256": "deadbeef"},
                "beta": {"git": True, "head": "bbb", "status_lines": 2, "status_sha256": "kept"},
            },
        )
        self.assertEqual(updated, ["alpha"])  # beta is unchanged, so it is not reported
        rows = json.loads(text)["projects"]
        self.assertEqual(rows[0]["source_snapshot"]["status_sha256"], "deadbeef")
        self.assertEqual(rows[1]["source_snapshot"]["status_sha256"], "kept")
        self.assertNotIn("status_sha256", rows[2]["source_snapshot"])
        self.assertEqual(text.count("\n"), self.LEDGER.count("\n"))

    def test_accepting_new_state_replaces_the_whole_snapshot(self):
        text, updated = apply_snapshot_updates(
            self.LEDGER,
            {"beta": {"git": True, "branch": "main", "head": "ccc", "status_lines": 0, "status_sha256": "fresh"}},
        )
        self.assertEqual(updated, ["beta"])
        snapshot = json.loads(text)["projects"][1]["source_snapshot"]
        self.assertEqual(snapshot, {"git": True, "branch": "main", "head": "ccc", "status_lines": 0, "status_sha256": "fresh"})
