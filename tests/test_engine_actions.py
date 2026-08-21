"""Engine action surface: discovery, invocation, and the allowlist boundary."""

import unittest

from portfolio_suites.engine_actions import EngineActionError, list_actions, run_action
from portfolio_suites.engines import ENGINES


class TestEngineActionDiscovery(unittest.TestCase):
    def test_every_suite_exposes_at_least_one_action(self):
        catalog = list_actions()
        self.assertEqual(set(catalog), set(ENGINES))
        for suite_id, info in catalog.items():
            self.assertTrue(info["actions"], f"{suite_id} exposes no actions")
            self.assertTrue(info["emits"], f"{suite_id} declares no contract")

    def test_parameters_are_described_with_requiredness(self):
        actions = {a["name"]: a for a in list_actions("accessibility")["accessibility"]["actions"]}
        params = {p["name"]: p for p in actions["audit_html_snippet"]["parameters"]}
        self.assertTrue(params["html_content"]["required"])
        self.assertFalse(params["source_url"]["required"])
        self.assertEqual(params["source_url"]["default"], "snippet://local")

    def test_unknown_suite_rejected(self):
        with self.assertRaises(EngineActionError):
            list_actions("not-a-suite")


class TestEngineActionInvocation(unittest.TestCase):
    def test_runs_action_and_returns_typed_output(self):
        findings = run_action("accessibility", "audit_html_snippet", {"html_content": "<img src=x>"})
        self.assertTrue(findings)
        self.assertEqual(findings[0]["rule_id"], "wcag-1.1.1-non-text-content")

    def test_defaults_apply_when_argument_omitted(self):
        findings = run_action("accessibility", "audit_html_snippet", {"html_content": "<img src=x>"})
        self.assertEqual(findings[0]["evidence"][0]["source"], "snippet://local")

    def test_cross_suite_experiment_runs_compare(self):
        """Three suites emit ExperimentRun; compare_runs must accept them together."""
        game = run_action("game-design", "simulate_tucked_in_terrors", {"trials": 20})
        harness = run_action("agent-reliability", "run_adversarial_harness", {})
        matrix = run_action("model-behavior-lab", "compare_runs", {"runs": [game, harness]})
        self.assertEqual(len(matrix["comparisons"]), 2)


class TestEngineActionBoundary(unittest.TestCase):
    def test_private_and_dunder_names_are_not_invocable(self):
        for name in ("__init__", "__class__", "_is_square_attacked"):
            with self.assertRaises(EngineActionError):
                run_action("model-behavior-lab", name, {})

    def test_unknown_action_rejected(self):
        with self.assertRaises(EngineActionError):
            run_action("accessibility", "definitely_not_a_method", {})

    def test_unexpected_argument_rejected(self):
        with self.assertRaises(EngineActionError) as ctx:
            run_action("accessibility", "audit_html_snippet", {"html_content": "<p>x</p>", "evil": 1})
        self.assertIn("evil", str(ctx.exception))

    def test_missing_required_argument_rejected(self):
        with self.assertRaises(EngineActionError):
            run_action("accessibility", "audit_html_snippet", {})

    def test_non_string_keys_rejected(self):
        with self.assertRaises(EngineActionError):
            run_action("accessibility", "audit_html_snippet", {1: "x"})


if __name__ == "__main__":
    unittest.main()
