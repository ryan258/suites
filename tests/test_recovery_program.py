import unittest
from copy import deepcopy

from portfolio_suites.recovery_program import (
    load_recovery_program,
    recovery_program_summary,
    resolve_recovery_obligations,
    validate_recovery_program,
)
from portfolio_suites.registry import load_suites


class RecoveryProgramTests(unittest.TestCase):
    def setUp(self):
        self.program = load_recovery_program()
        self.suites = load_suites()

    def test_current_program_is_valid_and_covers_every_runtime_followup_once(self):
        self.assertEqual(validate_recovery_program(self.program, self.suites), [])
        wave_followups = {
            f"{suite_id}/{wave['id']}"
            for suite_id, manifest in self.suites.items()
            for wave in manifest["waves"]
            if wave.get("runtime_followup")
        }
        covered = {
            obligation["id"]
            for obligation in self.program["obligations"]
            if obligation["source"] == "wave_runtime_followup"
        }
        self.assertEqual(covered, wave_followups)
        self.assertEqual(len(covered), 42)

    def test_program_has_one_journey_per_suite_and_explicit_lifecycle_obligations(self):
        self.assertEqual(
            {journey["suite_id"] for journey in self.program["journeys"]},
            set(self.suites),
        )
        lifecycle = [
            obligation
            for obligation in self.program["obligations"]
            if obligation["source"] == "lifecycle"
        ]
        self.assertEqual(
            [item["id"] for item in lifecycle],
            ["accessibility/A2-adoption", "operator-os/O1-adoption"],
        )
        for obligation in lifecycle:
            with self.subTest(obligation=obligation["id"]):
                self.assertEqual(obligation["receipt_contract"], "portfolio-adoption-v1")

    def test_adoption_obligation_carries_the_owner_gate_its_source_rung_does_not(self):
        by_id = {item["id"]: item for item in self.program["obligations"]}
        # source_executed is earned by invoking the donor; the permanent vault write is a
        # human decision that gates adoption, so it hangs off the adoption obligation.
        self.assertIsNone(by_id["operator-os/O1"]["owner_gate"])
        self.assertEqual(
            by_id["operator-os/O1-adoption"]["owner_gate"], "permanent_vault_write"
        )
        self.assertEqual(
            by_id["operator-os/O1-adoption"]["dependencies"], ["operator-os/O1"]
        )

    def test_duplicate_suite_journey_fails_exactly_once_coverage(self):
        program = deepcopy(self.program)
        duplicate = deepcopy(program["journeys"][0])
        duplicate["id"] = "accessibility-duplicate-journey"
        program["journeys"].append(duplicate)
        errors = validate_recovery_program(program, self.suites)
        self.assertIn("recovery journeys must cover every suite exactly once", errors)

    def test_stored_and_derived_state_vocabularies_are_explicit_and_disjoint(self):
        self.assertEqual(
            set(self.program["allowed_states"]),
            {
                "planned",
                "assessing",
                "blocked_environment",
                "blocked_owner",
                "in_progress",
                "evidence_candidate",
                "accepted",
                "discharged",
            },
        )
        self.assertEqual(
            set(self.program["derived_states"]), {"ready", "blocked_dependency"}
        )
        self.assertFalse(
            set(self.program["allowed_states"]).intersection(
                self.program["derived_states"]
            )
        )

    def test_malformed_program_values_return_errors_instead_of_raising(self):
        mutations = {
            "target_claim_kind": {"x": 1},
            "target_level": {"x": 1},
            "source": {"x": 1},
            "journey_id": {"x": 1},
            "receipt_contract": {"x": 1},
            "dependencies": [{"x": 1}],
        }
        for field, malformed in mutations.items():
            with self.subTest(field=field):
                program = deepcopy(self.program)
                obligation = next(
                    item
                    for item in program["obligations"]
                    if item["id"] == "operator-os/O1"
                )
                obligation[field] = malformed
                errors = validate_recovery_program(program, self.suites)
                self.assertTrue(errors)

    def test_malformed_journey_concepts_return_errors_instead_of_raising(self):
        program = deepcopy(self.program)
        journey = next(
            item for item in program["journeys"] if item["suite_id"] == "operator-os"
        )
        journey["business_concepts"] = [{"x": 1}]
        errors = validate_recovery_program(program, self.suites)
        self.assertTrue(errors)

    def test_o1_trace_route_is_governed_by_its_journey(self):
        obligation = next(
            item for item in self.program["obligations"] if item["id"] == "operator-os/O1"
        )
        route = obligation["trace_route"]
        self.assertEqual(route["selected_authority"], "PKos")
        self.assertEqual(
            {mapping["concept"] for mapping in route["resolved_mappings"]},
            {"CapturedSource", "KnowledgeProjection"},
        )

        invalid_cases = (
            ("concept", "NotAConcept", "unknown concept"),
            ("authority", "NotAnAuthority", "unknown authority"),
            ("relationship", "inventedRelationship", "unknown relationship"),
        )
        for field, malformed, expected in invalid_cases:
            with self.subTest(field=field):
                program = deepcopy(self.program)
                candidate = next(
                    item
                    for item in program["obligations"]
                    if item["id"] == "operator-os/O1"
                )
                candidate["trace_route"]["resolved_mappings"][0][field] = malformed
                errors = validate_recovery_program(program, self.suites)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_o1_trace_route_rejects_unrouted_selected_authority_and_policy(self):
        program = deepcopy(self.program)
        obligation = next(
            item for item in program["obligations"] if item["id"] == "operator-os/O1"
        )
        obligation["trace_route"]["selected_authority"] = "vaults"
        obligation["trace_route"]["policy_decisions"][0]["outcome"] = "maybe"
        errors = validate_recovery_program(program, self.suites)
        self.assertTrue(
            any("selected_authority must be a candidate authority" in error for error in errors),
            errors,
        )
        self.assertTrue(any("unknown outcome 'maybe'" in error for error in errors), errors)

    def test_missing_followup_obligation_fails_closed(self):
        program = deepcopy(self.program)
        program["obligations"] = [
            obligation
            for obligation in program["obligations"]
            if obligation["id"] != "operator-os/O1"
        ]
        errors = validate_recovery_program(program, self.suites)
        self.assertIn(
            "recovery program does not cover runtime follow-up(s): operator-os/O1",
            errors,
        )

    def test_non_followup_wave_cannot_enter_the_wave_obligation_set(self):
        program = deepcopy(self.program)
        lifecycle = next(
            obligation
            for obligation in program["obligations"]
            if obligation["id"] == "accessibility/A2-adoption"
        )
        lifecycle["id"] = "accessibility/A2"
        lifecycle["source"] = "wave_runtime_followup"
        errors = validate_recovery_program(program, self.suites)
        self.assertTrue(
            any("non-follow-up wave obligation(s): accessibility/A2" in error for error in errors),
            errors,
        )

    def test_dependency_cycle_is_rejected(self):
        program = deepcopy(self.program)
        by_id = {obligation["id"]: obligation for obligation in program["obligations"]}
        by_id["operator-os/O1"]["dependencies"] = ["operator-os/O4"]
        errors = validate_recovery_program(program, self.suites)
        self.assertTrue(
            any("recovery obligation dependency cycle" in error for error in errors),
            errors,
        )

    def test_runtime_target_requires_its_exact_receipt_contract(self):
        program = deepcopy(self.program)
        obligation = next(
            item for item in program["obligations"] if item["id"] == "operator-os/O1"
        )
        obligation["receipt_contract"] = "portfolio-runtime-parity-v1"
        errors = validate_recovery_program(program, self.suites)
        self.assertIn(
            "operator-os/O1: receipt_contract must be 'portfolio-runtime-source-v1'",
            errors,
        )

    def test_journey_contract_must_be_declared_by_its_suite(self):
        program = deepcopy(self.program)
        journey = next(
            item for item in program["journeys"] if item["suite_id"] == "operator-os"
        )
        journey["contracts"].append("BrandPackage")
        errors = validate_recovery_program(program, self.suites)
        self.assertIn(
            "operator-source-to-safe-action: contracts must be declared by suite operator-os",
            errors,
        )

    def test_resolver_joins_authoritative_wave_fields_without_copying_them_into_program(self):
        obligation = next(
            item
            for item in resolve_recovery_obligations(self.program, self.suites)
            if item["id"] == "operator-os/O1"
        )
        wave = next(
            item for item in self.suites["operator-os"]["waves"] if item["id"] == "O1"
        )
        raw = next(
            item for item in self.program["obligations"] if item["id"] == "operator-os/O1"
        )
        self.assertNotIn("runtime_followup", raw)
        self.assertEqual(obligation["runtime_followup"], wave["runtime_followup"])
        self.assertEqual(obligation["current_claim"], wave["recovery_claim"])

    def test_dependency_readiness_is_derived_without_claiming_environment_or_owner_availability(self):
        obligations = {
            item["id"]: item
            for item in resolve_recovery_obligations(self.program, self.suites)
        }
        self.assertEqual(obligations["operator-os/O1"]["effective_state"], "discharged")
        # O1 is discharged, so its adoption follow-on is dependency-satisfied and waits only
        # on its owner gate -- which readiness does not claim to know anything about.
        self.assertEqual(
            obligations["operator-os/O1-adoption"]["effective_state"], "ready"
        )
        self.assertEqual(
            obligations["brand-publishing/B3"]["effective_state"],
            "blocked_dependency",
        )
        self.assertEqual(
            obligations["brand-publishing/B3"]["dependency_states"],
            {
                "brand-publishing/B1": "planned",
                "brand-publishing/B5": "planned",
            },
        )
        self.assertIsNone(obligations["operator-os/O1"]["owner_gate"])

    def test_progress_states_cannot_bypass_unsatisfied_dependencies(self):
        for stored_state in (
            "assessing",
            "in_progress",
            "evidence_candidate",
            "accepted",
        ):
            with self.subTest(stored_state=stored_state):
                program = deepcopy(self.program)
                obligation = next(
                    item
                    for item in program["obligations"]
                    if item["id"] == "brand-publishing/B2"
                )
                obligation["state"] = stored_state
                resolved = {
                    item["id"]: item
                    for item in resolve_recovery_obligations(program, self.suites)
                }
                self.assertFalse(
                    resolved["brand-publishing/B2"]["dependencies_satisfied"]
                )
                self.assertEqual(
                    resolved["brand-publishing/B2"]["effective_state"],
                    "blocked_dependency",
                )

    def test_discharged_obligation_cannot_depend_on_undischarged_work(self):
        program = deepcopy(self.program)
        obligation = next(
            item
            for item in program["obligations"]
            if item["id"] == "brand-publishing/B2"
        )
        obligation["state"] = "discharged"
        errors = validate_recovery_program(program, self.suites)
        self.assertIn(
            "brand-publishing/B2: discharged obligation depends on undischarged "
            "brand-publishing/B1",
            errors,
        )

    def test_assessing_is_preserved_when_dependencies_are_satisfied(self):
        program = deepcopy(self.program)
        obligation = next(
            item
            for item in program["obligations"]
            if item["id"] == "operator-os/O1"
        )
        obligation["state"] = "assessing"
        resolved = {
            item["id"]: item
            for item in resolve_recovery_obligations(program, self.suites)
        }
        self.assertTrue(resolved["operator-os/O1"]["dependencies_satisfied"])
        self.assertEqual(resolved["operator-os/O1"]["effective_state"], "assessing")

    def test_summary_reports_program_state_without_changing_recovery_claims(self):
        before = deepcopy(self.suites)
        summary = recovery_program_summary(self.program, self.suites)
        self.assertEqual(summary["journeys"], 8)
        self.assertEqual(summary["obligations"], 44)
        self.assertEqual(summary["wave_runtime_followups"], 42)
        self.assertEqual(summary["lifecycle_obligations"], 2)
        self.assertGreater(len(summary["ready"]), 0)
        self.assertEqual(self.suites, before)


if __name__ == "__main__":
    unittest.main()
