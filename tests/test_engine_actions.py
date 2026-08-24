"""Engine action surface: discovery, invocation, and the allowlist boundary."""

import unittest

from portfolio_suites.engine_actions import (
    EngineActionError,
    get_action_spec,
    list_actions,
    run_action,
)
from portfolio_suites.engines import ENGINES


class TestActionPolicyTruthfulness(unittest.TestCase):
    """Static defaults cannot masquerade as review, and token consumers cannot be replayable.

    `execute_brand_maker_intake` and `simulate_vcc_human_approval` both consume a one-time
    approval when their arguments supply a token; advertising them as read-only,
    approval-free, and replayable made the catalog a decoration instead of a boundary.
    """

    PARAMETER_DEPENDENT = (
        ("brand-publishing", "execute_brand_maker_intake"),
        ("brand-publishing", "simulate_vcc_human_approval"),
        ("operator-os", "execute_jarvis_action_checkpoint"),
    )

    def test_parameter_dependent_actions_advertise_the_conservative_bound(self):
        catalog = list_actions()
        for suite_id, name in self.PARAMETER_DEPENDENT:
            action = next(a for a in catalog[suite_id]["actions"] if a["name"] == name)
            with self.subTest(suite=suite_id, action=name):
                self.assertEqual(action["authority_use"], "parameter_dependent")
                self.assertTrue(action["approval_required"])
                self.assertFalse(action["replayable"])
                self.assertNotEqual(action["side_effect_class"], "read_only")

    def test_every_action_declares_an_explicit_authority_policy(self):
        for suite_id, info in list_actions().items():
            for action in info["actions"]:
                with self.subTest(suite=suite_id, action=action["name"]):
                    self.assertIn(
                        action["authority_use"],
                        {"none", "parameter_dependent"},
                    )

    def test_effective_policy_flags_a_token_consuming_invocation(self):
        static = get_action_spec("brand-publishing", "execute_brand_maker_intake")
        self.assertFalse(static["authority_consumed"])
        consuming = get_action_spec(
            "brand-publishing",
            "execute_brand_maker_intake",
            {"brand_id": "b", "phase_inputs": {}, "operator_approval_token": "opa1.a.b"},
        )
        self.assertTrue(consuming["authority_consumed"])
        self.assertFalse(consuming["replayable"], "a token-consuming step must never be replayable")
        self.assertEqual(consuming["side_effect_class"], "single_use_authority_consumed")
        # The static catalog entry stays the conservative bound and is not mutated.
        self.assertFalse(static["authority_consumed"])

        jarvis_static = get_action_spec("operator-os", "execute_jarvis_action_checkpoint")
        self.assertEqual(jarvis_static["authority_use"], "parameter_dependent")
        self.assertFalse(jarvis_static["authority_consumed"])
        jarvis_consuming = get_action_spec(
            "operator-os",
            "execute_jarvis_action_checkpoint",
            {
                "action_name": "backup_data",
                "parameters": {},
                "operator_approval_token": "opa1.a.b",
            },
        )
        self.assertTrue(jarvis_consuming["authority_consumed"])
        self.assertFalse(jarvis_consuming["replayable"])
        self.assertEqual(jarvis_consuming["side_effect_class"], "single_use_authority_consumed")

    def test_chain_records_carry_effective_authority_outcome(self):
        from portfolio_suites.chains import run_chain

        outcome = run_chain([
            {"suite": "game-design", "action": "simulate_tucked_in_terrors",
             "arguments": {"trials": 5}},
            {"suite": "accessibility", "action": "audit_html_snippet",
             "arguments": {"html_content": "<img src=x>"}},
        ])
        for record in outcome["steps"]:
            self.assertIn("authority_consumed", record)
            self.assertIn("authority_use", record)
            self.assertFalse(record["authority_consumed"])


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


class TestChains(unittest.TestCase):
    """Chained engine actions: one action's output as another's argument."""

    def test_output_feeds_next_step(self):
        from portfolio_suites.chains import run_chain
        outcome = run_chain([
            {"suite": "game-design", "action": "simulate_tucked_in_terrors", "arguments": {"trials": 20}},
            {"suite": "game-design", "action": "generate_printable_balance_sheet",
             "arguments": {"sim_result": {"$from": 0}}},
        ])
        self.assertEqual(outcome["steps_run"], 2)
        self.assertEqual(outcome["steps"][1]["references"], [0])
        self.assertIn("Balance Sheet", outcome["final"])

    def test_path_selects_from_a_list_output(self):
        from portfolio_suites.chains import run_chain
        outcome = run_chain([
            {"suite": "accessibility", "action": "audit_html_snippet",
             "arguments": {"html_content": "<img src=x>"}},
            {"suite": "accessibility", "action": "roundtrip_kitchen_learning_finding",
             "arguments": {"finding": {"$from": 0, "path": "0"}}},
        ])
        self.assertEqual(outcome["final"]["roundtrip_status"], "suite_projection_verified")
        self.assertFalse(outcome["final"]["external_consumer_invoked"])
        self.assertFalse(outcome["final"]["evidence_loss"])

    def test_provenance_survives_a_cross_suite_chain(self):
        from portfolio_suites.chains import run_chain
        outcome = run_chain([
            {"suite": "operator-os", "action": "capture_source",
             "arguments": {"content": "chained note", "origin": "test", "source_id": "src-test-chain"}},
            {"suite": "operator-os", "action": "project_to_observer",
             "arguments": {"source_record": {"$from": 0}, "title": "T", "summary": "S", "body": "B"}},
        ])
        captured_hash = outcome["steps"][0]["result"]["sha256"]
        self.assertIn(captured_hash, outcome["final"])

    def test_forward_reference_rejected(self):
        from portfolio_suites.chains import ChainError, run_chain
        with self.assertRaises(ChainError) as ctx:
            run_chain([{"suite": "game-design", "action": "generate_printable_balance_sheet",
                        "arguments": {"sim_result": {"$from": 0}}}])
        self.assertEqual(ctx.exception.step_index, 0)

    def test_bad_path_names_the_failure(self):
        from portfolio_suites.chains import ChainError, run_chain
        with self.assertRaises(ChainError):
            run_chain([
                {"suite": "accessibility", "action": "audit_html_snippet",
                 "arguments": {"html_content": "<img src=x>"}},
                {"suite": "accessibility", "action": "roundtrip_kitchen_learning_finding",
                 "arguments": {"finding": {"$from": 0, "path": "not_an_index"}}},
            ])

    def test_failing_step_is_identified(self):
        from portfolio_suites.chains import ChainError, run_chain
        with self.assertRaises(ChainError) as ctx:
            run_chain([
                {"suite": "accessibility", "action": "audit_html_snippet",
                 "arguments": {"html_content": "<img src=x>"}},
                {"suite": "accessibility", "action": "audit_html_snippet", "arguments": {}},
            ])
        self.assertEqual(ctx.exception.step_index, 1)

    def test_empty_chain_rejected(self):
        from portfolio_suites.chains import ChainError, run_chain
        with self.assertRaises(ChainError):
            run_chain([])
