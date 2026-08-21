import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import portfolio_suites.adapters.accessibility as accessibility_module
from portfolio_suites.adapters.accessibility import AccessibilitySourceAdapter


def _tap(count: int) -> str:
    return "\n".join(f"ok {index} - pass" for index in range(1, count + 1))


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


DONOR_SOURCE = {
    "rule_id": "input-assistance-error-msg",
    "wcag_criterion": "3.3.1",
    "source_path": "/donor/understandable_rules.py",
    "evaluate_expression": "() => document.querySelectorAll('[aria-invalid=true]')",
}
TARGET_RESULT = {
    "findings": [
        {
            "wcagRule": "3.3.1",
            "selector": "#email",
            "severity": "serious",
            "description": "missing error",
            "status": "unverified",
            "tool": "aria-validator",
            "html": "<input id=\"email\">",
        }
    ]
}


class AccessibilityAdapterTests(unittest.TestCase):
    def _run_with(self, donor_outcomes: dict[str, bool], full_process: subprocess.CompletedProcess[str]):
        donor_runtime = {
            "rule_id": "input-assistance-error-msg",
            "wcag_criterion": "3.3.1",
            "outcomes": donor_outcomes,
            "violations": [],
        }
        processes = [
            _completed(0, json.dumps(DONOR_SOURCE)),
            _completed(0, json.dumps(donor_runtime)),
            _completed(0, _tap(6)),
            full_process,
            _completed(0, _tap(7)),
            _completed(0, json.dumps(TARGET_RESULT)),
        ]
        with patch(
            "portfolio_suites.adapters.accessibility.get_git_fingerprint",
            return_value={"is_dirty": False},
        ):
            with patch(
                "portfolio_suites.adapters.accessibility.subprocess.run",
                side_effect=processes,
            ):
                return AccessibilitySourceAdapter.execute_wcag_331_migration_gate(full_suite=True)

    def test_deep_gate_eperm_is_environment_blocked(self):
        stderr = "x" * 600 + " browser listen EPERM operation not permitted"
        receipt = self._run_with(
            {
                "invalid_input_missing_error_ref": True,
                "invalid_input_with_valid_errormessage": False,
                "invalid_input_with_valid_describedby": False,
            },
            _completed(1, stderr=stderr),
        )

        self.assertFalse(receipt["all_stages_passed"])
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(receipt["environment_blocked"])
        self.assertEqual(receipt["operational_errors"][0]["stage"], "full_suite_gate")
        self.assertTrue(receipt["operational_errors"][0]["environment_blocked"])

    def test_parity_uses_captured_donor_outcomes(self):
        receipt = self._run_with(
            {
                "invalid_input_missing_error_ref": False,
                "invalid_input_with_valid_errormessage": False,
                "invalid_input_with_valid_describedby": False,
            },
            _completed(0, _tap(127)),
        )

        self.assertFalse(receipt["all_stages_passed"])
        self.assertFalse(receipt["donor"]["donor_parity_verified"])
        mismatch = receipt["donor"]["parity_comparisons"][0]
        self.assertTrue(mismatch["target_flagged"])
        self.assertFalse(mismatch["donor_flagged"])
        self.assertFalse(mismatch["matches"])

    def test_keyboard_overlay_reconciliation_gate(self):
        rec = AccessibilitySourceAdapter.execute_keyboard_overlay_reconciliation_gate()
        self.assertTrue(rec["all_stages_passed"])
        self.assertEqual(rec["canonical_target"], "kb-overlay")
        self.assertIn("kb-overlay", rec["matrix"])
        self.assertIn("keyboard-nav-overlay", rec["matrix"])
        self.assertIn("keyboard-nav-overlay-94bf7e", rec["matrix"])
        self.assertEqual(rec["matrix"]["kb-overlay"]["active_status"], "retained_canonical")
        self.assertGreaterEqual(len(rec["matrix"]["kb-overlay"]["features"]), 8)

    def test_keyboard_overlay_reconciliation_fails_closed_without_donors(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with (
                patch.object(accessibility_module, "KB_OVERLAY_DIR", missing / "kb-overlay"),
                patch.object(
                    accessibility_module,
                    "KEYBOARD_NAV_OVERLAY_DIR",
                    missing / "keyboard-nav-overlay",
                ),
                patch.object(
                    accessibility_module,
                    "KEYBOARD_NAV_OVERLAY_94BF7E_DIR",
                    missing / "keyboard-nav-overlay-94bf7e",
                ),
            ):
                rec = AccessibilitySourceAdapter.execute_keyboard_overlay_reconciliation_gate()

        self.assertFalse(rec["all_stages_passed"])
        self.assertFalse(rec["source_verification"]["passed"])
        self.assertEqual(rec["source_verification"]["donors_checked"], 3)
        self.assertGreaterEqual(len(rec["source_verification"]["errors"]), 3)
        self.assertEqual(rec["matrix"]["kb-overlay"]["code_size_bytes"], 0)
        self.assertFalse(rec["matrix"]["kb-overlay"]["source_available"])
        self.assertFalse(rec["matrix"]["kb-overlay"]["fingerprint_verified"])

    def test_a11y_kitchen_roundtrip_fails_closed_without_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                accessibility_module,
                "A11Y_KITCHEN_DIR",
                Path(directory) / "missing-a11y-kitchen",
            ):
                rec = AccessibilitySourceAdapter.execute_a11y_kitchen_roundtrip_gate()

        self.assertFalse(rec["all_stages_passed"])
        self.assertFalse(rec["source_verification_passed"])

    def test_wcag_rule_candidates_gate(self):
        receipt = AccessibilitySourceAdapter.execute_wcag_rule_candidates_gate()
        self.assertTrue(receipt["all_stages_passed"])
        self.assertEqual(receipt["wave"], "A4")
        self.assertEqual(receipt["catalog_evaluation"]["total_candidates_evaluated"], 20)
        self.assertEqual(receipt["catalog_evaluation"]["status"], "all_backlog_candidates_evidenced")

    def test_a11y_kitchen_roundtrip_gate(self):
        kitchen = AccessibilitySourceAdapter.execute_a11y_kitchen_roundtrip_gate()
        self.assertTrue(kitchen["all_stages_passed"])
        self.assertEqual(kitchen["roundtrip_status"], "verified")
        self.assertFalse(kitchen["evidence_loss"])
        self.assertIn("advocate", kitchen["modes"])
        self.assertIn("builder", kitchen["modes"])
        self.assertIn("presenter", kitchen["modes"])

    def test_keyboard_overlay_consolidation_gate(self):
        cons = AccessibilitySourceAdapter.execute_keyboard_overlay_consolidation_gate()
        self.assertTrue(cons["all_stages_passed"])
        self.assertEqual(cons["proposed_canonical_anchor"], "kb-overlay")
        self.assertEqual(len(cons["proposed_frozen_donors"]), 2)
        self.assertTrue(cons["migration_acceptance_verified"])


if __name__ == "__main__":
    unittest.main()
