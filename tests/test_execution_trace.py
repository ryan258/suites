import unittest
from copy import deepcopy

from portfolio_suites.execution_trace import (
    load_execution_trace_contract,
    validate_execution_trace,
    validate_execution_trace_contract,
)
from portfolio_suites.recovery_program import load_recovery_program


class ExecutionTraceContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_execution_trace_contract()
        self.program = load_recovery_program()
        self.trace = {
            "trace_version": "portfolio-execution-trace-v1",
            "trace_id": "11111111-1111-4111-8111-111111111111",
            "request_id": "22222222-2222-4222-8222-222222222222",
            "obligation_id": "operator-os/O1",
            "journey_id": "operator-source-to-safe-action",
            "actor_class": "control_plane",
            "purpose": "runtime_recovery_verification",
            "ontology_version": "1.0.0",
            "mapping_version": "1.0.0",
            "resolved_mappings": [
                {
                    "concept": "CapturedSource",
                    "relationship": "authoritativeFor",
                    "authority": "dotfiles",
                },
                {
                    "concept": "KnowledgeProjection",
                    "relationship": "representedBy",
                    "authority": "PKos",
                },
            ],
            "candidate_authorities": ["dotfiles", "PKos"],
            "selected_authority": "PKos",
            "policy_decisions": [
                {
                    "policy_id": "local-read-only-runtime",
                    "outcome": "allowed",
                    "reason_code": "temporary_workspace_no_permanent_vault_write",
                }
            ],
            "adapter": "OperatorOSSourceAdapter",
            "plan_sha256": "a" * 64,
            "source_fingerprints": {
                "dotfiles": {
                    "branch": "main",
                    "head": "1" * 40,
                    "tested_files_fingerprint": {"AGENTS.md": "c" * 64},
                },
                "PKos": {
                    "branch": "main",
                    "head": "2" * 40,
                    "tested_files_fingerprint": {"pkos/storage.py": "e" * 64},
                },
            },
            "started_at": "2026-08-26T20:00:00+00:00",
            "finished_at": "2026-08-26T20:00:01+00:00",
            "outcome": "passed",
            "error_class": None,
            "fallback_used": False,
            "receipt_ref": None,
            "privacy": {
                "redacted": True,
                "raw_source_retained": False,
                "secrets_retained": False,
            },
        }

    def test_contract_and_representative_trace_are_valid(self):
        self.assertEqual(validate_execution_trace_contract(self.contract), [])
        self.assertEqual(
            validate_execution_trace(self.trace, self.program, self.contract),
            [],
        )

    def test_trace_rejects_authority_outside_the_journey(self):
        trace = deepcopy(self.trace)
        trace["candidate_authorities"] = ["cyborg"]
        trace["selected_authority"] = "cyborg"
        trace["resolved_mappings"][0]["authority"] = "cyborg"
        errors = validate_execution_trace(trace, self.program, self.contract)
        self.assertTrue(any("not governed for the journey" in error for error in errors))
        self.assertTrue(any("candidate_authorities" in error for error in errors))

    def test_trace_must_match_its_governed_route(self):
        drifts = (
            ("adapter", "SomeOtherAdapter", "adapter must match"),
            ("ontology_version", "9.9.9", "ontology_version must match"),
            ("mapping_version", "0.0.1", "mapping_version must match"),
            ("selected_authority", "dotfiles", "selected_authority must match"),
            (
                "candidate_authorities",
                ["PKos", "dotfiles"],
                "candidate_authorities must match",
            ),
            (
                "resolved_mappings",
                [
                    {
                        "concept": "CapturedSource",
                        "relationship": "authoritativeFor",
                        "authority": "dotfiles",
                    }
                ],
                "resolved_mappings must match",
            ),
        )
        for field, drifted, expected in drifts:
            with self.subTest(field=field):
                trace = deepcopy(self.trace)
                trace[field] = drifted
                errors = validate_execution_trace(trace, self.program, self.contract)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_trace_may_record_a_denied_decision_the_route_never_planned(self):
        trace = deepcopy(self.trace)
        trace["policy_decisions"] = [
            {
                "policy_id": "ephemeral-local-runtime",
                "outcome": "denied",
                "reason_code": "permanent_vault_write_not_authorized",
            }
        ]
        trace["outcome"] = "denied"
        trace["error_class"] = "policy_denied"
        trace["selected_authority"] = None
        self.assertEqual(
            validate_execution_trace(trace, self.program, self.contract), []
        )

    def test_environment_block_may_precede_authority_selection(self):
        trace = deepcopy(self.trace)
        trace["outcome"] = "blocked_environment"
        trace["error_class"] = "donor_import_failed"
        trace["selected_authority"] = None
        self.assertEqual(
            validate_execution_trace(trace, self.program, self.contract), []
        )

    def test_policy_decision_must_carry_a_reason_code(self):
        trace = deepcopy(self.trace)
        del trace["policy_decisions"][0]["reason_code"]
        errors = validate_execution_trace(trace, self.program, self.contract)
        self.assertIn("policy_decisions.0.reason_code must be non-empty", errors)

    def test_trace_rejects_silent_fallback(self):
        trace = deepcopy(self.trace)
        trace["fallback_used"] = True
        errors = validate_execution_trace(trace, self.program, self.contract)
        self.assertIn(
            "fallback_used requires an explicit fallbackTo mapping",
            errors,
        )

    def test_trace_rejects_denied_policy_disguised_as_success(self):
        trace = deepcopy(self.trace)
        trace["policy_decisions"][0]["outcome"] = "denied"
        errors = validate_execution_trace(trace, self.program, self.contract)
        self.assertIn(
            "a denied policy decision must produce a denied execution outcome",
            errors,
        )

    def test_trace_rejects_raw_payload_or_credentials(self):
        trace = deepcopy(self.trace)
        trace["raw_input"] = "private source text"
        trace["policy_decisions"][0]["token"] = "do-not-retain"
        errors = validate_execution_trace(trace, self.program, self.contract)
        self.assertTrue(
            any("$.raw_input" in error and ".token" in error for error in errors),
            errors,
        )

    def test_malformed_program_concepts_and_authorities_return_errors(self):
        for field in ("business_concepts", "technical_authorities"):
            with self.subTest(field=field):
                program = deepcopy(self.program)
                journey = next(
                    item
                    for item in program["journeys"]
                    if item["id"] == "operator-source-to-safe-action"
                )
                journey[field] = [{"x": 1}]
                errors = validate_execution_trace(self.trace, program, self.contract)
                self.assertTrue(any(field in error for error in errors), errors)

    def test_unhashable_trace_identifiers_return_errors(self):
        for field in ("obligation_id", "journey_id"):
            with self.subTest(field=field):
                trace = deepcopy(self.trace)
                trace[field] = {"x": 1}
                errors = validate_execution_trace(trace, self.program, self.contract)
                self.assertTrue(any(field in error for error in errors), errors)

    def test_unhashable_mapping_and_candidate_values_return_errors(self):
        trace = deepcopy(self.trace)
        trace["resolved_mappings"][0]["concept"] = {"x": 1}
        trace["resolved_mappings"][0]["authority"] = {"x": 1}
        trace["candidate_authorities"] = [{"x": 1}]
        errors = validate_execution_trace(trace, self.program, self.contract)
        self.assertTrue(any("concept" in error for error in errors), errors)
        self.assertTrue(any("authority" in error for error in errors), errors)
        self.assertTrue(any("candidate_authorities" in error for error in errors), errors)

    def test_unhashable_outcome_and_non_list_program_sections_return_errors(self):
        trace = deepcopy(self.trace)
        trace["outcome"] = {"x": 1}
        program = deepcopy(self.program)
        program["journeys"] = {"x": 1}
        program["obligations"] = {"x": 1}
        errors = validate_execution_trace(trace, program, self.contract)
        self.assertIn("outcome is not governed", errors)
        self.assertIn("recovery program journeys must be a list", errors)
        self.assertIn("recovery program obligations must be a list", errors)


if __name__ == "__main__":
    unittest.main()
