"""Engine action surface: discovery, invocation, and the allowlist boundary."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from portfolio_suites.chains import run_chain
from portfolio_suites.engine_actions import (
    ActionSpec,
    EngineActionError,
    action_cache_key,
    action_is_cacheable,
    get_action_spec,
    list_actions,
    registered_action_spec,
    result_consumes_authority,
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

    def test_incomplete_intake_with_token_does_not_claim_authority_consumed(self):
        from portfolio_suites.chains import run_chain

        outcome = run_chain([
            {
                "suite": "brand-publishing",
                "action": "execute_brand_maker_intake",
                "arguments": {
                    "brand_id": "test-brand",
                    "phase_inputs": {},
                    "operator_approval_token": "opa1.fake.token",
                },
            }
        ])
        step0 = outcome["steps"][0]
        self.assertEqual(step0["result"]["reconciliation_status"], "intake_incomplete")
        self.assertFalse(step0["authority_consumed"], "incomplete intake must not claim authority was consumed")
        self.assertTrue(step0["replayable"])
        self.assertNotEqual(step0["side_effect_class"], "single_use_authority_consumed")

    def test_failed_approval_intake_does_not_claim_authority_consumed(self):
        from portfolio_suites.chains import run_chain
        from portfolio_suites.engines.brand_publishing import SIMULATED_PACKAGE_APPROVED_AT

        phase_inputs = {
            "1": {"one_liner": "A", "enemy": "B", "brand_name": "Test Brand"},
            "2": {"primary_operator": "Ryan", "pain_points": ["drift"], "target_audience": "Devs"},
            "3": {"tone_adjectives": ["crisp"], "taboo_words": ["bad"]},
            "4": {"palette_hex": ["#000"], "typeface_pair": "Inter", "tagline": "Tag"},
            "5": {"verifiable_claims": ["Fast"]},
            "6": {"logo_paths": ["l.svg"], "icon_set": "lucide"},
            "7": {"do_list": ["Pin"], "dont_list": ["Mutate"], "usage_rules": ["Rule 1"]},
            "8": {"formats": ["json"], "cadence": "daily"},
            "9": {"approver_signoff": "Ryan"},
        }
        outcome = run_chain([
            {
                "suite": "brand-publishing",
                "action": "execute_brand_maker_intake",
                "arguments": {
                    "brand_id": "test-brand",
                    "phase_inputs": phase_inputs,
                    "operator_approval_token": "opa1.invalid.token",
                },
            }
        ])
        step0 = outcome["steps"][0]
        pkg = step0["result"]["resulting_package"]
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg["approved_at"], SIMULATED_PACKAGE_APPROVED_AT)
        self.assertEqual(pkg["provenance"][0]["decision_source"], "simulated_fixture")
        self.assertFalse(step0["authority_consumed"], "failed approval intake must not burn authority")
        self.assertTrue(step0["replayable"])
        self.assertNotEqual(step0["side_effect_class"], "single_use_authority_consumed")

    def test_brand_intake_consumption_uses_explicit_outcome_not_timestamp(self):
        from portfolio_suites.engines.brand_publishing import SIMULATED_PACKAGE_APPROVED_AT

        arguments = {"operator_approval_token": "opa1.apr-1.secret"}
        package = {
            "approved_at": SIMULATED_PACKAGE_APPROVED_AT,
            "provenance": [{
                "decision_source": "verified_operator_approval",
                "human_confirmation_claimed": True,
            }],
        }
        self.assertTrue(result_consumes_authority(
            arguments,
            {"approval_verified": True, "resulting_package": package},
        ))

        # Timestamps are artifact metadata, not authority outcomes. A non-fixture
        # timestamp without the explicit verified result must not manufacture a
        # consumption claim.
        self.assertFalse(result_consumes_authority(
            arguments,
            {"resulting_package": {"approved_at": "2099-01-01T00:00:00+00:00"}},
        ))


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

    def test_invalid_list_index_like_double_hyphen_raises_chain_error(self):
        from portfolio_suites.chains import ChainError, _walk_path
        with self.assertRaises(ChainError):
            _walk_path(["first", "second"], "--1", source_step=0, consumer_step=1)


if __name__ == "__main__":
    unittest.main()


class ActionCacheTests(unittest.TestCase):
    """A cache that serves an action which spent authority reports a use that never happened."""

    def test_argument_pure_action_is_served_from_a_caller_owned_cache(self):
        cache: dict[str, object] = {}
        args = {"html_content": "<img src=hero.png>"}
        first = run_action("accessibility", "audit_html_snippet", args, cache=cache)
        self.assertEqual(len(cache), 1)
        second = run_action("accessibility", "audit_html_snippet", args, cache=cache)
        self.assertEqual(first, second)
        self.assertEqual(len(cache), 1)
        # Detached on the way out: a caller mutating its result cannot poison the cache.
        second.append("injected")
        third = run_action("accessibility", "audit_html_snippet", args, cache=cache)
        self.assertNotIn("injected", third)
        self.assertEqual(third, first)

    def test_first_uncached_result_does_not_alias_cache_storage(self):
        cache: dict[str, object] = {}
        args = {"html_content": "<img src=hero.png>"}
        first = run_action("accessibility", "audit_html_snippet", args, cache=cache)
        first.append("poisoned-by-first-caller")

        second = run_action("accessibility", "audit_html_snippet", args, cache=cache)

        self.assertNotIn("poisoned-by-first-caller", second)

    def test_filesystem_sensitive_read_is_not_cached_across_symlink_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = base / "workspace"
            inside = workspace / "inside"
            outside = base / "outside"
            inside.mkdir(parents=True)
            outside.mkdir()
            link = workspace / "target"
            link.symlink_to(inside, target_is_directory=True)
            args = {
                "workspace_root": str(workspace),
                "target_path": "target/note.md",
            }
            cache: dict[str, object] = {}

            first = run_action(
                "agent-reliability", "verify_path_confinement", args, cache=cache
            )
            link.unlink()
            link.symlink_to(outside, target_is_directory=True)
            second = run_action(
                "agent-reliability", "verify_path_confinement", args, cache=cache
            )

        self.assertTrue(first[0])
        self.assertFalse(second[0])
        self.assertIn("SECURITY VIOLATION", second[1])
        self.assertEqual(cache, {})

    def test_cache_key_separates_arguments_and_contract_version(self):
        base = action_cache_key("s", "a", {"x": 1})
        self.assertNotEqual(base, action_cache_key("s", "a", {"x": 2}))
        self.assertNotEqual(base, action_cache_key("s", "b", {"x": 1}))
        # Key order is not identity: the same arguments hash the same either way round.
        self.assertEqual(
            action_cache_key("s", "a", {"x": 1, "y": 2}),
            action_cache_key("s", "a", {"y": 2, "x": 1}),
        )

    def test_only_explicitly_argument_pure_read_only_actions_are_cacheable(self):
        for suite_id, action, expected in (
            ("accessibility", "audit_html_snippet", True),
            ("agent-reliability", "verify_path_confinement", False),
            ("brand-publishing", "execute_brand_maker_intake", False),
        ):
            with self.subTest(action=f"{suite_id}.{action}"):
                spec = registered_action_spec(suite_id, action)
                self.assertEqual(action_is_cacheable(spec, {}), expected)

    def test_an_authority_consuming_invocation_is_never_cacheable(self):
        spec = ActionSpec(
            output_kind="report",
            side_effect_class="read_only",
            approval_required=True,
            evidence_eligible=True,
            replayable=True,
            cacheable=True,
            authority_use="parameter_dependent",
        )
        self.assertTrue(action_is_cacheable(spec, {}))
        self.assertFalse(
            action_is_cacheable(spec, {"operator_approval_token": "one-time-token"})
        )

    def test_chain_marks_which_steps_were_served_from_cache(self):
        step = {
            "suite": "accessibility",
            "action": "audit_html_snippet",
            "arguments": {"html_content": "<img src=hero.png>"},
        }
        outcome = run_chain([step, deepcopy(step)])
        self.assertFalse(outcome["steps"][0]["served_from_cache"])
        self.assertTrue(outcome["steps"][1]["served_from_cache"])
        self.assertEqual(outcome["steps"][0]["result"], outcome["steps"][1]["result"])
