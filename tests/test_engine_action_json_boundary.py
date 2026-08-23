import json
import math
import unittest
from unittest.mock import patch

from portfolio_suites.engine_actions import (
    EngineActionError,
    REDACTED_ARGUMENT,
    list_actions,
    redact_sensitive_arguments,
    run_action,
    unregistered_public_methods,
)
from portfolio_suites.engines.model_behavior import ModelBehaviorEngine


class EngineActionJSONBoundaryTests(unittest.TestCase):
    def test_sensitive_arguments_are_recursively_redacted_without_mutating_input(self):
        arguments = {
            "operator_approval_token": "opa1.single-use",
            "nested": {
                "api-key": "provider-secret",
                "credential": "credential-value",
                "bearer": "bearer-value",
                "token": "bare-token-value",
                "client_secret": "client-secret-value",
                "clientSecret": "camel-secret-value",
                "dbPassword": "db-password-value",
                "token_budget": 4096,
                "ordinary": "keep-me",
            },
            "items": [{"access_token": "token-value"}],
        }

        redacted = redact_sensitive_arguments(arguments)

        self.assertEqual(redacted["operator_approval_token"], REDACTED_ARGUMENT)
        self.assertEqual(redacted["nested"]["api-key"], REDACTED_ARGUMENT)
        for key in (
            "credential",
            "bearer",
            "token",
            "client_secret",
            "clientSecret",
            "dbPassword",
        ):
            self.assertEqual(redacted["nested"][key], REDACTED_ARGUMENT)
        self.assertEqual(redacted["nested"]["token_budget"], 4096)
        self.assertEqual(redacted["nested"]["ordinary"], "keep-me")
        self.assertEqual(redacted["items"][0]["access_token"], REDACTED_ARGUMENT)
        self.assertEqual(arguments["operator_approval_token"], "opa1.single-use")
        self.assertEqual(arguments["nested"]["api-key"], "provider-secret")

    def test_all_existing_public_methods_are_explicitly_reviewed(self):
        self.assertEqual(unregistered_public_methods(), {})

    def test_parse_fen_has_a_deterministic_json_projection(self):
        result = run_action(
            "model-behavior-lab",
            "parse_fen_board",
            {"fen": "4k3/8/8/8/8/8/8/4K3 w - - 0 1"},
        )
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["board_representation"], "square_piece_list_v1")
        self.assertEqual(
            result["board"],
            [{"square": "e1", "piece": "K"}, {"square": "e8", "piece": "k"}],
        )

    def test_brand_phase_keys_survive_the_json_boundary(self):
        phases = run_action("brand-publishing", "get_brand_workshop_phases", {})
        list_fields = {
            "pain_points", "tone_adjectives", "taboo_words", "palette_hex", "typeface_pair",
            "verifiable_claims", "logo_paths", "icon_set", "do_list", "dont_list", "formats",
        }
        phase_inputs = {}
        for phase in phases:
            values = {}
            for field in phase["required_inputs"]:
                values[field] = [f"{field}-value"] if field in list_fields else f"{field}-value"
            phase_inputs[str(phase["phase"])] = values
        result = run_action(
            "brand-publishing",
            "execute_brand_maker_intake",
            {"brand_id": "json-brand", "phase_inputs": phase_inputs},
        )
        self.assertEqual(result["phases_completed"], 9)
        self.assertIsNotNone(result["resulting_package"])

    def test_falsy_non_objects_are_not_silently_converted(self):
        for value in ([], "", False):
            with self.subTest(value=value), self.assertRaises(EngineActionError):
                run_action("agent-reliability", "run_adversarial_harness", value)

    def test_non_finite_input_is_refused(self):
        with self.assertRaisesRegex(EngineActionError, "NaN"):
            run_action(
                "discovery-decision",
                "create_investigation",
                {"investigation_id": "inv-json", "question": "Why?", "max_time_sec": math.nan},
            )

    def test_contract_labelled_output_is_validated(self):
        def invalid_result(run_id, provider, model, scenario_count=10):
            return {}

        with patch.object(
            ModelBehaviorEngine,
            "execute_ethics_scenario_run",
            new=staticmethod(invalid_result),
        ):
            with self.assertRaisesRegex(EngineActionError, "invalid ExperimentRun"):
                run_action(
                    "model-behavior-lab",
                    "execute_ethics_scenario_run",
                    {"run_id": "run-test", "provider": "test", "model": "test"},
                )

    def test_output_metadata_is_action_specific(self):
        actions = {
            item["name"]: item
            for item in list_actions("game-design")["game-design"]["actions"]
        }
        self.assertEqual(actions["simulate_tucked_in_terrors"]["emits"], "ExperimentRun")
        self.assertEqual(actions["generate_printable_balance_sheet"]["output_kind"], "markdown")
        self.assertIsNone(actions["generate_printable_balance_sheet"]["emits"])


if __name__ == "__main__":
    unittest.main()
