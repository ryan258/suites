import json
import subprocess
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
