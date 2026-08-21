import unittest

from portfolio_suites.engines.accessibility import AccessibilityEngine
from portfolio_suites.engines.operator_os import OperatorOSEngine
from portfolio_suites.engines.brand_publishing import BrandPublishingEngine
from portfolio_suites.engines.production_house import ProductionHouseEngine
from portfolio_suites.engines.model_behavior import ModelBehaviorEngine
from portfolio_suites.engines.discovery_decision import DiscoveryDecisionEngine
from portfolio_suites.engines.agent_reliability import AgentReliabilityEngine
from portfolio_suites.engines.game_design import GameDesignEngine
from portfolio_suites.adapters.operator_os import OperatorOSSourceAdapter
from portfolio_suites.contracts import generate_sample


class EngineTests(unittest.TestCase):
    def test_audit_identifiers_do_not_collide_within_one_second(self):
        package = generate_sample("BrandPackage")
        source = generate_sample("SourceRecord")
        publication_ids = {
            BrandPublishingEngine.dry_run_publish(package, source, "draft")["receipt_id"]
            for _ in range(3)
        }
        review_ids = {
            BrandPublishingEngine.simulate_vcc_human_approval(
                package,
                source,
                "draft",
                human_decision="rejected",
            )["review_id"]
            for _ in range(3)
        }
        action_ids = {
            OperatorOSEngine.preview_jarvis_action("backup_data", {})["action_id"]
            for _ in range(3)
        }
        harness_ids = {
            AgentReliabilityEngine.run_adversarial_harness()["run_id"]
            for _ in range(3)
        }
        for identifiers in (publication_ids, review_ids, action_ids, harness_ids):
            self.assertEqual(len(identifiers), 3)

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

        # Link with img alt text or text should NOT be flagged as empty link (Finding 6 fix)
        img_link = '<a href="/"><img src="home.png" alt="Home page"></a>'
        self.assertEqual(len(AccessibilityEngine.audit_html_snippet(img_link)), 0)

        # Table with <th> in first row should NOT be flagged as missing headers (Finding 6 fix)
        table_with_th = '<table><tr><th>Header</th></tr><tr><td>Data</td></tr></table>'
        table_findings = AccessibilityEngine.audit_rule_families(table_with_th)
        self.assertFalse(any(f["rule_id"] == "wcag-1.3.1-info-and-relationships-table-header" for f in table_findings))

        # Table with only <td> SHOULD be flagged as heuristic needs_review
        table_no_th = '<table><tr><td>Data 1</td><td>Data 2</td></tr></table>'
        table_no_th_findings = AccessibilityEngine.audit_rule_families(table_no_th)
        self.assertTrue(any(f["rule_id"] == "wcag-1.3.1-info-and-relationships-table-header" and f["needs_review"] is True for f in table_no_th_findings))

        ai_finding = AccessibilityEngine.create_ai_assisted_finding(
            "find-ai-1", "wcag-alt-quality", "Generic alt", "img.logo", "Hypothesis: Alt text too vague"
        )
        self.assertTrue(ai_finding["needs_review"])

        reconcile = AccessibilityEngine.reconcile_keyboard_overlays()
        self.assertEqual(reconcile["canonical_target"], "kb-overlay")

        kitchen = AccessibilityEngine.roundtrip_kitchen_learning_finding(findings[0])
        self.assertEqual(kitchen["roundtrip_status"], "verified")
        self.assertFalse(kitchen["evidence_loss"])

        final_overlay = AccessibilityEngine.finalize_overlay_reconciliation()
        self.assertEqual(final_overlay["artifact_kind"], "reference_prototype")
        self.assertEqual(len(final_overlay["proposed_frozen_donors"]), 2)

        # Test full candidate backlog evaluation
        backlog_res = AccessibilityEngine.evaluate_wcag_auditor_backlog_catalog([
            {"id": "inline-language-change", "kind": "single-page", "setup": "Spanish in English", "expected": "needs-review"},
            {"id": "input-assistance-error-msg", "kind": "single-page", "setup": "aria-invalid", "expected": "deterministic error"},
        ])
        self.assertEqual(backlog_res["total_candidates_evaluated"], 2)
        self.assertEqual(backlog_res["port_review_count"], 1)
        self.assertEqual(backlog_res["port_narrow_count"], 1)

    def test_operator_os_engine(self):
        src = OperatorOSEngine.capture_source("# Test Note", "note://test", "src-test-01")
        self.assertEqual(src["source_id"], "src-test-01")
        self.assertEqual(len(src["sha256"]), 64)

        proj = OperatorOSEngine.project_to_observer(src, "Test Title", "Test Summary", "Test Body")
        self.assertIn("fenced_from_reingestion: true", proj)
        self.assertIn("src-test-01", proj)

        preview = OperatorOSEngine.preview_jarvis_action("backup_data", {"vault": "ai-vault"})
        self.assertTrue(preview["requires_human_approval"])

        notes_batch = [{"source_id": "src-test-node-01", "origin": "note://s1", "content": "Note 1", "title": "T1"}]
        stream = OperatorOSEngine.capture_live_pkos_stream(notes_batch)
        self.assertEqual(len(stream), 1)

        ryos_disp = OperatorOSEngine.reconcile_ryos_disposition()
        self.assertEqual(ryos_disp["artifact_kind"], "reference_prototype")
        self.assertEqual(ryos_disp["duplicate_row_proposal"], "close_on_verification")

        # Test fail-closed without approval
        chk_blocked = OperatorOSEngine.execute_jarvis_action_checkpoint("audit_secrets", {"path": "/"}, operator_approved=False)
        self.assertEqual(chk_blocked["status"], "blocked_missing_approval")
        self.assertFalse(chk_blocked["operator_approval_verified"])
        self.assertIsNone(chk_blocked["execution_receipt"])

        # Test dry-run backup checkpoint generates content-addressed snapshot ID without disk mutation
        chk_dry_run = OperatorOSEngine.execute_jarvis_action_checkpoint(
            "backup_data", {"vault": "test-vault", "path": "contracts", "dry_run": True}, operator_approved=True
        )
        self.assertEqual(chk_dry_run["status"], "success")
        self.assertTrue(chk_dry_run["operator_approval_verified"])
        self.assertTrue(chk_dry_run["execution_result"]["dry_run"])
        self.assertEqual(chk_dry_run["execution_result"]["manifest_file"], "")
        self.assertTrue(chk_dry_run["execution_result"]["snapshot_id"].startswith("snap-"))

        # Test audit_secrets scans all eligible files without silent 50-file truncation
        chk_secrets_root = OperatorOSEngine.execute_jarvis_action_checkpoint(
            "audit_secrets", {"path": "."}, operator_approved=True
        )
        self.assertEqual(chk_secrets_root["status"], "success")
        self.assertGreater(chk_secrets_root["execution_result"]["scanned_files_count"], 50)
        # Root contains .env which has an API key, so findings must be detected
        self.assertGreaterEqual(chk_secrets_root["execution_result"]["findings_count"], 1)
        self.assertFalse(chk_secrets_root["execution_result"]["clean"])

        # Scanning clean subtree should report clean
        chk_secrets_clean = OperatorOSEngine.execute_jarvis_action_checkpoint(
            "audit_secrets", {"path": "src"}, operator_approved=True
        )
        self.assertEqual(chk_secrets_clean["status"], "success")
        self.assertTrue(chk_secrets_clean["execution_result"]["clean"])

    def test_operator_os_adapter(self):
        o1 = OperatorOSSourceAdapter.execute_o1_source_record_observer_gate()
        self.assertEqual(o1["status"], "verified")
        self.assertTrue(o1["mutation_protection_passed"])
        self.assertTrue(o1["mutation_cases"]["corrupt_sha_rejected"])
        self.assertTrue(o1["mutation_cases"]["no_fence_rejected"])
        self.assertTrue(o1["mutation_cases"]["no_citation_rejected"])
        self.assertTrue(o1["mutation_cases"]["anti_reingestion_fence_detected"])
        self.assertTrue(o1["mutation_cases"]["reingestion_intake_blocked"])

        o2 = OperatorOSSourceAdapter.execute_o2_ryos_inventory()
        self.assertEqual(o2["status"], "verified")
        self.assertGreaterEqual(o2["ryos_core_files_count"], 3)
        self.assertGreaterEqual(o2["inventory_catalog_count"], 5)

        o3 = OperatorOSSourceAdapter.execute_o3_jarvis_action_preview()
        self.assertEqual(o3["status"], "preview_verified")
        self.assertTrue(o3["requires_human_approval"])
        self.assertTrue(o3["dry_run_only"])

        o4 = OperatorOSSourceAdapter.execute_o4_pkos_stream_intake()
        self.assertEqual(o4["status"], "stream_intake_verified")
        self.assertEqual(o4["batch_size"], 3)
        self.assertTrue(o4["all_fenced_from_reingestion"])
        self.assertTrue(o4["all_sources_cited"])

        o5 = OperatorOSSourceAdapter.execute_o5_ryos_disposition_reconciliation()
        self.assertEqual(o5["status"], "disposition_reconciled")
        self.assertTrue(o5["duplicate_decisions_closed"])
        self.assertGreaterEqual(o5["port_candidates_count"], 2)

        o6 = OperatorOSSourceAdapter.execute_o6_jarvis_checkpoint_lifecycle()
        self.assertEqual(o6["status"], "checkpoint_lifecycle_verified")
        self.assertTrue(o6["multi_action_lifecycle_passed"])
        self.assertTrue(o6["fail_closed_test"]["verified"])
        self.assertTrue(o6["preview_test"]["verified"])
        self.assertFalse(o6["disk_mutations_performed"])

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

        v_cons = BrandPublishingEngine.verify_package_consumer(pkg, "site-fixture", "1.0.0")
        self.assertEqual(v_cons["status"], "verified")

        # Test empty intake: must NOT claim 9 phases or produce package (Finding 5 fix)
        bm_res_empty = BrandPublishingEngine.execute_brand_maker_intake("test-brand", {})
        self.assertEqual(bm_res_empty["phases_completed"], 0)
        self.assertIsNone(bm_res_empty["resulting_package"])

        # Test complete intake: must produce valid BrandPackage
        full_inputs = {
            1: {"one_liner": "A", "enemy": "B", "brand_name": "Test Brand"},
            2: {"primary_operator": "Ryan", "pain_points": ["drift"], "target_audience": "Devs"},
            3: {"tone_adjectives": ["crisp"], "taboo_words": ["bad"]},
            4: {"palette_hex": ["#000"], "typeface_pair": "Inter", "tagline": "Tag"},
            5: {"verifiable_claims": ["Fast"]},
            6: {"logo_paths": ["l.svg"], "icon_set": "lucide"},
            7: {"do_list": ["Pin"], "dont_list": ["Mutate"], "usage_rules": ["Rule 1"]},
            8: {"formats": ["json"], "cadence": "daily"},
            9: {"approver_signoff": "Ryan"},
        }
        bm_res_full = BrandPublishingEngine.execute_brand_maker_intake("test-brand", full_inputs)
        self.assertEqual(bm_res_full["phases_completed"], 9)
        self.assertIsNotNone(bm_res_full["resulting_package"])

        # Test human approval branching (Finding 3 fix)
        vcc_rev_app = BrandPublishingEngine.simulate_vcc_human_approval(pkg, src, "Zero-dependency local-first portfolio control plane", human_decision="approved")
        self.assertEqual(vcc_rev_app["status"], "ready_for_operator_release")

        vcc_rev_rej = BrandPublishingEngine.simulate_vcc_human_approval(pkg, src, "Zero-dependency draft", human_decision="rejected")
        self.assertEqual(vcc_rev_rej["status"], "blocked_rejected")

        vcc_rev_unmatched = BrandPublishingEngine.simulate_vcc_human_approval(pkg, src, "Unrelated text with no claims", human_decision="approved")
        self.assertEqual(vcc_rev_unmatched["status"], "blocked_unmatched_claims")

    def test_production_house_engine(self):
        job = ProductionHouseEngine.create_job("job-test-01", "groundwire-audio", "synthesis", [{"name": "script.fountain"}])
        self.assertEqual(job["status"], "queued")
        advanced = ProductionHouseEngine.advance_job_stage(job, "synthesis", [{"name": "stems.zip"}], status="completed")
        self.assertEqual(advanced["status"], "completed")
        self.assertEqual(len(advanced["outputs"]), 1)

        gw_job = ProductionHouseEngine.build_groundwire_pipeline_job("ep-01", "a" * 64)
        self.assertEqual(gw_job["status"], "completed")

        doc_job = ProductionHouseEngine.build_investigative_documentary_job("ep-14", "b" * 64)
        self.assertEqual(doc_job["status"], "completed")

        wr_map = ProductionHouseEngine.map_writers_room_events("story-1", [{"scene_number": 1, "revision_id": "v1"}])
        self.assertEqual(wr_map["mapped_job"]["status"], "completed")

    def test_model_behavior_engine(self):
        run = ModelBehaviorEngine.execute_ethics_scenario_run("run-test-01", "anthropic", "claude-3-5-sonnet", 5)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(run["iterations"]), 5)
        self.assertTrue(all(it["outcome_source"] == "deterministic_fixture" for it in run["iterations"]))
        self.assertTrue(all("simulated_latency_ms" in it for it in run["iterations"]))
        self.assertTrue(all("latency_ms" not in it and "tokens_in" not in it for it in run["iterations"]))

        comp = ModelBehaviorEngine.compare_runs([run])
        self.assertEqual(len(comp["comparisons"]), 1)
        self.assertEqual(comp["comparisons"][0]["simulated_average_latency_ms"], 495.0)
        self.assertNotIn("average_latency_ms", comp["comparisons"][0])

        # Test real deterministic chess evaluation (Finding 1 fix)
        chess = ModelBehaviorEngine.execute_chess_benchmark_run("run-chess-01", "deterministic-oracle", "chess-rules-evaluator-v1", 10)
        self.assertEqual(chess["status"], "completed")
        self.assertEqual(len(chess["iterations"]), 10)
        self.assertTrue(all("fen" in it and "candidate_move" in it for it in chess["iterations"]))
        self.assertTrue(all(it["passed"] for it in chess["iterations"]))
        self.assertEqual(chess["evidence"][0]["pass_rate"], 1.0)
        rejected = next(it for it in chess["iterations"] if it["scenario_id"] == "chess-puzzle-05")
        self.assertFalse(rejected["observed_legal"])
        self.assertTrue(rejected["passed"])

        illegal_moves = [
            ("4k3/8/8/r4pPK/8/8/8/8 w - f6 0 1", "g5f6"),
            ("4k3/8/8/8/8/8/8/4K3 w K - 0 1", "e1g1"),
            ("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a2q"),
        ]
        for fen, move in illegal_moves:
            legal, _, _ = ModelBehaviorEngine._evaluate_chess_move(fen, move, move)
            self.assertFalse(legal, f"Expected illegal move to be rejected: {move} in {fen}")

        corpus = ModelBehaviorEngine.build_versioned_corpus("corpus-01", [run, chess])
        self.assertEqual(len(corpus["benchmarks_included"]), 2)
        # Test valid re-run command (Finding 7 fix)
        self.assertEqual(corpus["reproducibility_contract"]["re_run_script"], "PYTHONPATH=src python3 -m portfolio_suites wave model-behavior-lab M4")

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

        sif_analogy = DiscoveryDecisionEngine.execute_sif_analogy_stage("inv-ana-1", "Test Analogy?")
        self.assertEqual(sif_analogy["status"], "completed")

        excav = DiscoveryDecisionEngine.ingest_insight_excavator_source(inv, src_a, "Insight")
        self.assertEqual(excav["insight_excavator_runtime"], "retired_into_forge_citations")

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

        audit = AgentReliabilityEngine.audit_promoted_components([
            {"component_id": "c1", "consumers": ["p1", "p2"]},
            {"component_id": "c2", "consumers": ["p1"]},
        ])
        self.assertEqual(audit["promoted_retained_count"], 1)
        self.assertEqual(audit["demoted_count"], 1)

        curr = AgentReliabilityEngine.build_curriculum_fixtures([{"id": "m1", "topic": "Gates"}])
        self.assertEqual(curr["fixtures_count"], 1)

    def test_game_design_engine(self):
        sim = GameDesignEngine.simulate_tucked_in_terrors(seed=42, trials=500)
        self.assertEqual(sim["status"], "completed")
        # Ensure all checkpoint win rates are valid probabilities (0 <= p <= 1.0)
        for it in sim["iterations"]:
            self.assertGreaterEqual(it["win_rate"], 0.0)
            self.assertLessEqual(it["win_rate"], 1.0)

        sheet = GameDesignEngine.generate_printable_balance_sheet(sim)
        self.assertIn("Statistical Balance Sheet", sheet)

        pack = GameDesignEngine.build_text_adventure_pack("pack-echo", rooms_count=4)
        self.assertEqual(pack["nodes_count"], 4)

        b_audit = GameDesignEngine.audit_authored_game_boundary("march-madness")
        self.assertEqual(b_audit["status"], "boundary_formalized")


if __name__ == "__main__":
    unittest.main()
