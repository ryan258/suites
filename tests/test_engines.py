import unittest

from portfolio_suites.engines.accessibility import AccessibilityEngine
from portfolio_suites.engines.operator_os import OperatorOSEngine
from portfolio_suites.engines.brand_publishing import BrandPublishingEngine
from portfolio_suites.engines.production_house import ProductionHouseEngine
from portfolio_suites.engines.model_behavior import ModelBehaviorEngine
from portfolio_suites.engines.discovery_decision import DiscoveryDecisionEngine
from portfolio_suites.engines.agent_reliability import AgentReliabilityEngine
from portfolio_suites.engines.game_design import GameDesignEngine
from portfolio_suites.contracts import generate_sample


class EngineTests(unittest.TestCase):
    def test_accessibility_engine_audit(self):
        html = '<input id="test-zip" class="is-invalid"><img src="pic.jpg"><button></button>'
        findings = AccessibilityEngine.audit_html_snippet(html)
        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0]["rule_id"], "wcag-3.3.1-error-identification")
        self.assertEqual(findings[1]["rule_id"], "wcag-1.1.1-non-text-content")
        self.assertEqual(findings[2]["rule_id"], "wcag-4.1.2-name-role-value")

        # Test false-positive prevention:
        # Bare 'error' in attribute name or value other than class should not trigger WCAG 3.3.1
        clean_html = '<input id="code" name="error_code" data-error-msg="none">'
        self.assertEqual(len(AccessibilityEngine.audit_html_snippet(clean_html)), 0)

        # Buttons with aria-labelledby or title should not trigger WCAG 4.1.2 empty button finding
        labeled_btn_1 = '<button aria-labelledby="submit-label"></button>'
        labeled_btn_2 = '<button title="Search"></button>'
        self.assertEqual(len(AccessibilityEngine.audit_html_snippet(labeled_btn_1)), 0)
        self.assertEqual(len(AccessibilityEngine.audit_html_snippet(labeled_btn_2)), 0)

        ai_finding = AccessibilityEngine.create_ai_assisted_finding(
            "find-ai-1", "wcag-alt-quality", "Generic alt", "img.logo", "Hypothesis: Alt text too vague"
        )
        self.assertTrue(ai_finding["needs_review"])

        reconcile = AccessibilityEngine.reconcile_keyboard_overlays()
        self.assertEqual(reconcile["canonical_target"], "kb-overlay")

    def test_operator_os_engine(self):
        src = OperatorOSEngine.capture_source("# Test Note", "note://test", "src-test-01")
        self.assertEqual(src["source_id"], "src-test-01")
        self.assertEqual(len(src["sha256"]), 64)

        proj = OperatorOSEngine.project_to_observer(src, "Test Title", "Test Summary", "Test Body")
        self.assertIn("fenced_from_reingestion: true", proj)
        self.assertIn("src-test-01", proj)

        preview = OperatorOSEngine.preview_jarvis_action("backup_data", {"vault": "ai-vault"})
        self.assertTrue(preview["requires_human_approval"])

    def test_brand_publishing_engine(self):
        pkg = generate_sample("BrandPackage")
        src = generate_sample("SourceRecord")
        receipt = BrandPublishingEngine.dry_run_publish(pkg, src, "Zero-dependency local-first portfolio control plane")
        self.assertTrue(receipt["dry_run_only"])
        self.assertGreaterEqual(receipt["matched_approved_claims_count"], 1)

        ok, violations = BrandPublishingEngine.verify_immutability(pkg, pkg)
        self.assertTrue(ok)
        self.assertEqual(len(violations), 0)

        mutated = dict(pkg)
        mutated["identity"] = {"name": "Mutated Name"}
        ok, violations = BrandPublishingEngine.verify_immutability(pkg, mutated)
        self.assertFalse(ok)
        self.assertGreater(len(violations), 0)

        phases = BrandPublishingEngine.get_brand_workshop_phases()
        self.assertEqual(len(phases), 9)

    def test_production_house_engine(self):
        job = ProductionHouseEngine.create_job("job-test-01", "groundwire-audio", "synthesis", [{"name": "script.fountain"}])
        self.assertEqual(job["status"], "queued")
        advanced = ProductionHouseEngine.advance_job_stage(job, "synthesis", [{"name": "stems.zip"}], status="completed")
        self.assertEqual(advanced["status"], "completed")
        self.assertEqual(len(advanced["outputs"]), 1)

        gw_job = ProductionHouseEngine.build_groundwire_pipeline_job("ep-01", "a" * 64)
        self.assertEqual(gw_job["status"], "completed")

    def test_model_behavior_engine(self):
        run = ModelBehaviorEngine.execute_ethics_scenario_run("run-test-01", "anthropic", "claude-3-5-sonnet", 5)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(run["iterations"]), 5)

        comp = ModelBehaviorEngine.compare_runs([run])
        self.assertEqual(len(comp["comparisons"]), 1)

    def test_discovery_decision_engine(self):
        inv = DiscoveryDecisionEngine.create_investigation("inv-test-01", "Test Question?")
        self.assertEqual(inv["status"], "draft")
        advanced = DiscoveryDecisionEngine.advance_stage(inv, "red_team", [{"evidence": "ok"}], status="completed")
        self.assertEqual(advanced["status"], "completed")
        self.assertEqual(advanced["budget"]["used_iterations"], 1)

        src_a = generate_sample("SourceRecord")
        src_b = generate_sample("SourceRecord")
        src_b["source_id"] = "src-other"
        disc = DiscoveryDecisionEngine.discover_across_sources(src_a, src_b, "test query")
        self.assertGreater(disc["novelty_score"], 0.5)

    def test_agent_reliability_engine(self):
        confined, _ = AgentReliabilityEngine.verify_path_confinement("/Users/ryan/Projects", "suites/README.md")
        self.assertTrue(confined)

        escaped, _ = AgentReliabilityEngine.verify_path_confinement("/Users/ryan/Projects", "../../../etc/passwd")
        self.assertFalse(escaped)

        scorecard = AgentReliabilityEngine.run_adversarial_harness()
        self.assertEqual(scorecard["status"], "completed")
        self.assertEqual(len(scorecard["iterations"]), 4)
        for it in scorecard["iterations"]:
            self.assertTrue(it["passed"])

    def test_game_design_engine(self):
        sim = GameDesignEngine.simulate_tucked_in_terrors(seed=42, trials=500)
        self.assertEqual(sim["status"], "completed")
        # Ensure all checkpoint win rates are valid probabilities (0 <= p <= 1.0)
        for it in sim["iterations"]:
            self.assertGreaterEqual(it["win_rate"], 0.0)
            self.assertLessEqual(it["win_rate"], 1.0)

        sheet = GameDesignEngine.generate_printable_balance_sheet(sim)
        self.assertIn("Statistical Balance Sheet", sheet)


if __name__ == "__main__":
    unittest.main()
