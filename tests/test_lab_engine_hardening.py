"""Bounded-input and malformed-artifact coverage for the four lab engines."""

from __future__ import annotations

import copy
import unittest

from portfolio_suites.contracts import generate_sample
from portfolio_suites.engines.agent_reliability import AgentReliabilityEngine
from portfolio_suites.engines.discovery_decision import DiscoveryDecisionEngine
from portfolio_suites.engines.game_design import GameDesignEngine
from portfolio_suites.engines.model_behavior import ModelBehaviorEngine


class GameDesignBounds(unittest.TestCase):
    def test_simulation_rejects_empty_huge_boolean_and_nonfinite_workloads(self):
        for kwargs in (
            {"trials": 0},
            {"trials": 1_000_001},
            {"trials": True},
            {"difficulty_modifier": float("nan")},
            {"difficulty_modifier": float("inf")},
            {"difficulty_modifier": 0},
            {"seed": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GameDesignEngine.simulate_tucked_in_terrors(**kwargs)

    def test_adventure_pack_requires_a_bounded_nonempty_graph(self):
        for pack_id, rooms in (("", 8), ("pack", 0), ("pack", -1), ("pack", 1_001), ("pack", True)):
            with self.subTest(pack_id=pack_id, rooms=rooms), self.assertRaises(ValueError):
                GameDesignEngine.build_text_adventure_pack(pack_id, rooms)
        pack = GameDesignEngine.build_text_adventure_pack("pack-ok", 2)
        self.assertEqual(pack["nodes_count"], 2)
        self.assertFalse(pack["storyweaver_runtime_invoked"])
        self.assertEqual(pack["verification_scope"], "suite_fixture_projection")

    def test_balance_sheet_requires_real_simulation_metrics(self):
        unrelated = generate_sample("ExperimentRun")
        with self.assertRaises(ValueError):
            GameDesignEngine.generate_printable_balance_sheet(unrelated)


class ModelBehaviorBounds(unittest.TestCase):
    def test_ethics_run_rejects_zero_scenarios(self):
        with self.assertRaises(ValueError):
            ModelBehaviorEngine.execute_ethics_scenario_run("run-test", "fixture", "fixture", 0)

    def test_comparator_rejects_nonfinite_iteration_values(self):
        run = ModelBehaviorEngine.execute_ethics_scenario_run("run-test", "fixture", "fixture", 1)
        broken = copy.deepcopy(run)
        broken["iterations"][0]["score"] = float("nan")
        with self.assertRaises(ValueError):
            ModelBehaviorEngine.compare_runs([broken])

    def test_corpus_requires_contract_valid_runs(self):
        with self.assertRaises(ValueError):
            ModelBehaviorEngine.build_versioned_corpus("corpus", [{"run_id": "incomplete"}])


class DiscoveryDecisionBounds(unittest.TestCase):
    def test_stage_cannot_overspend_either_budget(self):
        investigation = DiscoveryDecisionEngine.create_investigation(
            "inv-budget", "Can this stay bounded?", max_iterations=1, max_time_sec=1
        )
        with self.assertRaisesRegex(ValueError, "iteration budget"):
            DiscoveryDecisionEngine.advance_stage(investigation, "too-many", iteration_cost=2, time_cost_sec=0)
        with self.assertRaisesRegex(ValueError, "time budget"):
            DiscoveryDecisionEngine.advance_stage(investigation, "too-slow", iteration_cost=0, time_cost_sec=2)

    def test_discovery_requires_two_distinct_source_records(self):
        source = generate_sample("SourceRecord")
        with self.assertRaisesRegex(ValueError, "independently addressable"):
            DiscoveryDecisionEngine.discover_across_sources(source, source, "Compare")


class AgentReliabilityBounds(unittest.TestCase):
    def test_scalar_plan_is_refused_not_promoted(self):
        for raw in ("null", "[]", '"do the thing"', "42"):
            with self.subTest(raw=raw):
                receipt = AgentReliabilityEngine.recover_plan(raw)
                self.assertEqual(receipt["status"], "refused")
                self.assertFalse(receipt["recovered"])

    def test_budget_and_rollback_inputs_must_be_strict_json(self):
        with self.assertRaises(ValueError):
            AgentReliabilityEngine.partition_plan_by_budget([float("nan")], 1)
        with self.assertRaises(ValueError):
            AgentReliabilityEngine.apply_with_rollback({}, [{"key": "x", "value": float("inf")}])

    def test_consumer_deduplication_cannot_fake_shared_adoption(self):
        receipt = AgentReliabilityEngine.audit_promoted_components([
            {"component_id": "component-one", "consumers": ["same", "same"]}
        ])
        self.assertEqual(receipt["promoted_retained_count"], 0)
        self.assertEqual(receipt["demoted_count"], 1)


if __name__ == "__main__":
    unittest.main()
