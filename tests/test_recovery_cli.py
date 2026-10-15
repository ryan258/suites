import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from portfolio_suites.cli import main
from portfolio_suites.recovery_program import RecoveryProgramError


class RecoveryCLIIntegrationTests(unittest.TestCase):
    def test_next_is_phase_aware_and_gates_b1_behind_contract_freeze(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["next"])

        self.assertEqual(code, 2)
        rendered = output.getvalue()
        # The frozen contract-state gate is closed. The release ledger exposes B1 as the first
        # actionable runtime blocker, while blocked B3 remains a suite stopping point rather
        # than being presented as a runnable scheduled wave.
        self.assertIn(
            "NEXT RELEASE BLOCKER: brand-publishing.v1.b1-runtime",
            rendered,
        )
        self.assertIn("gate (phase1.contract-state-freeze): closed", rendered)
        self.assertNotIn("brand-publishing / B3:", rendered)
        # The phase-aware release blocker queue owns B1 while release blockers remain open.
        self.assertNotIn("NEXT RECOVERY OBLIGATION: brand-publishing/B1", rendered)

    def test_next_fails_closed_when_recovery_program_cannot_load(self):
        output = io.StringIO()
        with patch(
            "portfolio_suites.cli.load_recovery_program",
            side_effect=RecoveryProgramError("broken program"),
        ), redirect_stdout(output):
            code = main(["next"])

        self.assertEqual(code, 1)
        self.assertIn(
            "ERROR release or recovery program is invalid: broken program",
            output.getvalue(),
        )

    def test_next_renders_recovery_queue_when_no_blockers_open(self):
        """The dependency-ready queue branch must stay reachable and render even when the
        release ledger reports no open blockers -- the phase gate must not make it dead."""
        obligation = {
            "id": "brand-publishing/B1",
            "effective_state": "ready",
            "target_claim_kind": "runtime",
            "target_level": "source_executed",
            "runtime_environment": "node18",
            "owner_gate": "approvals.finance",
            "receipt_contract": "runtime-behavior",
            "acceptance_checks": ["probe", "snapshot"],
            "runtime_followup": "live run",
            "wave_id": None,
            "suite_id": "brand-publishing",
            "priority": "P1",
        }
        summary = {
            "obligations": 1,
            "wave_runtime_followups": 0,
            "lifecycle_obligations": 1,
            "states": {"blocked_dependency": 0},
        }
        benign = {
            "open_blockers": [],
            "open_blocker_count": 0,
            "actionable_blockers": [],
        }
        output = io.StringIO()
        with patch(
            "portfolio_suites.cli.resolve_release_state", return_value=benign
        ), patch(
            "portfolio_suites.cli.resolve_recovery_obligations",
            return_value=[obligation],
        ), patch(
            "portfolio_suites.cli.recovery_program_summary", return_value=summary
        ), redirect_stdout(output):
            code = main(["next"])

        self.assertEqual(code, 0)
        rendered = output.getvalue()
        self.assertIn("Recovery program: 1 obligations", rendered)
        self.assertIn("Dependency state: 1 ready, 0 blocked", rendered)
        self.assertIn("NEXT RECOVERY OBLIGATION: brand-publishing/B1", rendered)
        self.assertIn("owner gate: approvals.finance", rendered)
        self.assertIn("receipt: runtime-behavior", rendered)
        self.assertIn("acceptance: probe, snapshot", rendered)


if __name__ == "__main__":
    unittest.main()
