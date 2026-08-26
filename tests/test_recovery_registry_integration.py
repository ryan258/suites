import unittest
from copy import deepcopy
from unittest.mock import patch

from portfolio_suites.execution_trace import load_execution_trace_contract
from portfolio_suites.recovery_program import (
    RecoveryProgramError,
    load_recovery_program,
)
from portfolio_suites.registry import validate_registry


class RecoveryRegistryIntegrationTests(unittest.TestCase):
    def test_fast_registry_validation_includes_both_governance_artifacts(self):
        report = validate_registry(check_live=False)
        self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_fast_registry_validation_rejects_incomplete_followup_coverage(self):
        program = deepcopy(load_recovery_program())
        program["obligations"] = [
            obligation
            for obligation in program["obligations"]
            if obligation["id"] != "operator-os/O1"
        ]
        with patch(
            "portfolio_suites.registry.load_recovery_program",
            return_value=program,
        ):
            report = validate_registry(check_live=False)

        self.assertIn(
            "recovery program: recovery program does not cover runtime follow-up(s): operator-os/O1",
            report.errors,
        )

    def test_fast_registry_validation_rejects_weakened_trace_policy(self):
        contract = deepcopy(load_execution_trace_contract())
        contract["policy"]["raw_source_payloads_retained"] = True
        with patch(
            "portfolio_suites.registry.load_execution_trace_contract",
            return_value=contract,
        ):
            report = validate_registry(check_live=False)

        self.assertIn(
            "execution trace contract: execution trace policy must preserve the fail-closed privacy boundary",
            report.errors,
        )

    def test_fast_registry_validation_fails_closed_when_program_cannot_load(self):
        with patch(
            "portfolio_suites.registry.load_recovery_program",
            side_effect=RecoveryProgramError("unreadable program"),
        ):
            report = validate_registry(check_live=False)

        self.assertEqual(
            report.errors,
            ["registry load failed: unreadable program"],
        )

    def test_fast_registry_validation_reports_malformed_program_values(self):
        program = deepcopy(load_recovery_program())
        program["allowed_dispositions"] = [{"x": 1}]
        obligation = next(
            item for item in program["obligations"] if item["id"] == "operator-os/O1"
        )
        obligation["target_claim_kind"] = {"x": 1}
        with patch(
            "portfolio_suites.registry.load_recovery_program",
            return_value=program,
        ):
            report = validate_registry(check_live=False)

        self.assertFalse(report.ok)
        self.assertTrue(
            any("allowed_dispositions" in error for error in report.errors),
            report.errors,
        )
        self.assertTrue(
            any("invalid target_claim_kind" in error for error in report.errors),
            report.errors,
        )


if __name__ == "__main__":
    unittest.main()
