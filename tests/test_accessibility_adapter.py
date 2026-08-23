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

    def test_node_gates_never_install_packages_during_verification(self):
        receipt = self._run_with(
            {
                "invalid_input_missing_error_ref": True,
                "invalid_input_with_valid_errormessage": False,
                "invalid_input_with_valid_describedby": False,
            },
            _completed(0, _tap(127)),
        )
        self.assertTrue(
            receipt["stages"]["focused_parity_gate"]["command"].startswith(
                "npx --no-install tsx"
            )
        )
        self.assertTrue(
            receipt["stages"]["full_audit_integration_gate"]["command"].startswith(
                "npx --no-install tsx"
            )
        )

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

    def test_keyboard_overlay_inventory_ignores_hidden_ancestors_not_the_repo(self):
        fingerprint = {
            "branch": "main",
            "head": "a" * 40,
            "tested_files_fingerprint": {"manifest.json": "b" * 64},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".hidden-parent"
            repositories = {
                "KB_OVERLAY_DIR": root / "kb-overlay",
                "KEYBOARD_NAV_OVERLAY_DIR": root / "keyboard-nav-overlay",
                "KEYBOARD_NAV_OVERLAY_94BF7E_DIR": root / "keyboard-nav-overlay-94bf7e",
            }
            for repository in repositories.values():
                repository.mkdir(parents=True)
                (repository / "manifest.json").write_text(
                    json.dumps({"manifest_version": 3, "permissions": []}),
                    encoding="utf-8",
                )
                (repository / "content.js").write_text("export const ready = true;", encoding="utf-8")

            with (
                patch.object(accessibility_module, "KB_OVERLAY_DIR", repositories["KB_OVERLAY_DIR"]),
                patch.object(
                    accessibility_module,
                    "KEYBOARD_NAV_OVERLAY_DIR",
                    repositories["KEYBOARD_NAV_OVERLAY_DIR"],
                ),
                patch.object(
                    accessibility_module,
                    "KEYBOARD_NAV_OVERLAY_94BF7E_DIR",
                    repositories["KEYBOARD_NAV_OVERLAY_94BF7E_DIR"],
                ),
                patch.object(accessibility_module, "get_git_fingerprint", return_value=fingerprint),
            ):
                rec = AccessibilitySourceAdapter.execute_keyboard_overlay_reconciliation_gate()

        self.assertTrue(rec["all_stages_passed"])
        self.assertTrue(all(item["code_files_count"] == 2 for item in rec["matrix"].values()))

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
        # The canonical overlay injects on every page, exactly as its donors do: the gate may
        # call the consolidation justified, never minimized, and never owner-accepted.
        self.assertEqual(cons["canonical_permission_surface"]["host_scope"], ["<all_urls>"])
        self.assertFalse(cons["permission_analysis"]["minimized_permissions_verified"])
        self.assertTrue(cons["permission_analysis"]["canonical_no_broader_than_donors"])
        self.assertFalse(cons["migration_acceptance_verified"])
        self.assertTrue(all(not donor["retirement_performed"] for donor in cons["donor_retirement"].values()))

    def test_a_product_failure_is_reported_as_failed_not_unverifiable(self):
        receipt = self._run_with(
            {
                "invalid_input_missing_error_ref": True,
                "invalid_input_with_valid_errormessage": False,
                "invalid_input_with_valid_describedby": False,
            },
            _completed(
                1,
                stdout="TAP version 13\nok 1 - renders\nnot ok 2 - associates\n",
                stderr="AssertionError while checking the browser: permission denied on fixture",
            ),
        )
        self.assertFalse(receipt["all_stages_passed"])
        self.assertFalse(
            receipt["environment_blocked"],
            "a suite that produced verdicts was masked as an environment blocker",
        )
class EnvironmentBlockClassificationTests(unittest.TestCase):
    """An environment blocker is neither a pass nor a product failure, so misreading one costs a regression.

    The old rule fired on stderr prose alone: any output mentioning a denied permission and
    a browser became "unverifiable", exit 2, claiming nothing was wrong. The discriminator
    is now whether the runner reached any verdicts at all.
    """

    def test_a_suite_that_reached_verdicts_is_a_product_failure_not_a_blocker(self):
        from portfolio_suites.adapters.accessibility import _is_environment_blocked

        stdout = "TAP version 13\nok 1 - renders\nnot ok 2 - associates error message\n"
        stderr = "AssertionError: expected browser permission denied banner to be absent"
        self.assertFalse(_is_environment_blocked(stderr, stdout))

    def test_a_runner_that_reached_no_verdicts_is_still_a_blocker(self):
        from portfolio_suites.adapters.accessibility import _is_environment_blocked

        stderr = "Error: browser launch failed: listen EPERM operation not permitted"
        self.assertTrue(_is_environment_blocked(stderr, ""))

    def test_a_missing_runtime_is_unambiguous_at_any_output(self):
        from portfolio_suites.adapters.accessibility import _is_environment_blocked

        stdout = "TAP version 13\nnot ok 1 - anything\n"
        self.assertTrue(
            _is_environment_blocked("Please run the following command to download new browsers", stdout)
        )
        self.assertTrue(_is_environment_blocked("browserType.launch: Executable doesn't exist", stdout))

    def test_ordinary_assertion_failures_are_never_blockers(self):
        from portfolio_suites.adapters.accessibility import _is_environment_blocked

        self.assertFalse(_is_environment_blocked("AssertionError: expected 3 findings, got 2", ""))


if __name__ == "__main__":
    unittest.main()
