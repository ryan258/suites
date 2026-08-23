import unittest
from unittest.mock import patch

from portfolio_suites.chains import ChainError, preflight_chain, run_chain
from portfolio_suites.engine_actions import EngineActionError


class ChainPreflightTests(unittest.TestCase):
    def test_invalid_later_action_prevents_step_zero_execution(self):
        steps = [
            {"suite": "agent-reliability", "action": "run_adversarial_harness", "arguments": {}},
            {"suite": "agent-reliability", "action": "not_reviewed", "arguments": {}},
        ]
        with patch("portfolio_suites.chains.run_action") as invoke:
            with self.assertRaises(ChainError) as caught:
                run_chain(steps)
        invoke.assert_not_called()
        self.assertEqual(caught.exception.phase, "preflight")

    def test_attempted_reference_with_unknown_sibling_is_rejected(self):
        steps = [
            {"suite": "agent-reliability", "action": "run_adversarial_harness", "arguments": {}},
            {
                "suite": "model-behavior-lab",
                "action": "compare_runs",
                "arguments": {"runs": [{"$from": 0, "typo": "iterations"}]},
            },
        ]
        with self.assertRaisesRegex(ChainError, "unknown field"):
            preflight_chain(steps)

    def test_runtime_failure_reports_detached_completed_prefix(self):
        steps = [
            {"suite": "agent-reliability", "action": "recover_plan", "arguments": {"raw_plan": "{}"}},
            {"suite": "agent-reliability", "action": "recover_plan", "arguments": {"raw_plan": "{}"}},
        ]
        with patch(
            "portfolio_suites.chains.run_action",
            side_effect=[{"status": "valid"}, EngineActionError("boom")],
        ):
            with self.assertRaises(ChainError) as caught:
                run_chain(steps)
        error = caught.exception
        self.assertEqual(error.step_index, 1)
        self.assertEqual(len(error.completed_steps), 1)
        self.assertEqual(error.as_dict()["completed_steps"][0]["step"], 0)

    def test_missing_required_argument_is_a_preflight_failure(self):
        with self.assertRaises(ChainError) as caught:
            preflight_chain([
                {"suite": "model-behavior-lab", "action": "parse_fen_board", "arguments": {}}
            ])
        self.assertEqual(caught.exception.phase, "preflight")


if __name__ == "__main__":
    unittest.main()
