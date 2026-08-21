import unittest
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from portfolio_suites.registry import (
    _analysis_evidence_errors,
    _runtime_parity_receipt_errors,
    get_portfolio_summary,
    load_ledger,
    load_recovery_standard,
    load_suites,
    validate_registry,
)


class RegistryTests(unittest.TestCase):
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

    def test_summary_separates_analysis_from_runtime_recovery(self):
        summary = get_portfolio_summary()
        self.assertEqual(summary["recovery_target_score"], 9.0)
        self.assertEqual(summary["verified_analysis_milestones"], 21)
        self.assertEqual(summary["recovered_runtime_behaviors"], 1)
        self.assertEqual(summary["adopted_runtime_behaviors"], 0)
        self.assertEqual(summary["converged_runtime_behaviors"], 0)


if __name__ == "__main__":
    unittest.main()
