"""Negative-path guards for the suites most likely to overstate modeled work."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import portfolio_suites.adapters.accessibility as accessibility_module
from portfolio_suites.adapters.accessibility import AccessibilitySourceAdapter
from portfolio_suites.adapters.discovery_decision import DiscoveryDecisionSourceAdapter
from portfolio_suites.adapters.operator_os import OperatorOSSourceAdapter
from portfolio_suites.adapters.production_house import ProductionHouseSourceAdapter
from portfolio_suites.approvals import canonical_digest
from portfolio_suites.contracts import generate_sample
from portfolio_suites.engines.brand_publishing import BrandPublishingEngine
from portfolio_suites.engines.operator_os import OperatorOSEngine
from portfolio_suites.engines.production_house import ProductionHouseEngine


class ProductionLifecycleGuards(unittest.TestCase):
    def setUp(self):
        self.job = ProductionHouseEngine.create_job(
            "job-semantic-guard",
            "fixture-domain",
            "fixture-task",
            [{"name": "input.json", "sha256": "a" * 64}],
        )

    def test_queued_job_cannot_jump_to_completed(self):
        with self.assertRaisesRegex(ValueError, "illegal ProductionJob transition"):
            ProductionHouseEngine.advance_job_stage(
                self.job,
                "pretend-finished",
                [{"name": "output.json", "sha256": "b" * 64}],
                status="completed",
            )

    def test_terminal_job_cannot_be_reopened(self):
        running = ProductionHouseEngine.advance_job_stage(self.job, "start", status="running")
        completed = ProductionHouseEngine.advance_job_stage(
            running,
            "finish",
            [{"name": "output.json", "sha256": "b" * 64}],
            status="completed",
        )
        with self.assertRaisesRegex(ValueError, "terminal ProductionJob"):
            ProductionHouseEngine.advance_job_stage(completed, "reopen", status="running")

    def test_every_input_and_output_needs_a_real_digest(self):
        with self.assertRaisesRegex(ValueError, "sha256"):
            ProductionHouseEngine.create_job("job-bad-hash", "d", "t", [{"name": "input"}])
        with self.assertRaisesRegex(ValueError, "sha256"):
            ProductionHouseEngine.advance_job_stage(
                self.job,
                "start",
                [{"name": "output", "sha256": "not-a-digest"}],
                status="running",
            )

    def test_formatter_and_writers_room_receipts_name_fixture_boundaries(self):
        formatter = ProductionHouseSourceAdapter.execute_p2_formatter_job()
        handoff = ProductionHouseSourceAdapter.execute_p3_writers_room_handoff()
        documentary = ProductionHouseSourceAdapter.execute_p4_documentary_pipeline()
        revisions = ProductionHouseSourceAdapter.execute_p5_writers_room_event_stream()
        self.assertEqual(formatter["status"], "source_play_projected")
        self.assertFalse(formatter["external_formatter_invoked"])
        self.assertTrue(formatter["fixture_output_only"])
        self.assertFalse(formatter["job"]["external_runtime_invoked"])
        self.assertTrue(formatter["script"]["sha256"])
        self.assertEqual(handoff["status"], "source_handoff_projected")
        self.assertFalse(handoff["writers_room_runtime_invoked"])
        self.assertFalse(handoff["signoff_observed"])
        self.assertFalse(handoff["job"]["external_runtime_invoked"])
        self.assertEqual(documentary["status"], "source_documentary_script_projected")
        self.assertFalse(documentary["external_runtime_invoked"])
        self.assertTrue(documentary["script"]["sha256"])
        self.assertEqual(revisions["status"], "source_event_stream_projected")
        self.assertFalse(revisions["mapping"]["writers_room_runtime_invoked"])
        self.assertEqual(revisions["mapping"]["runtime_consolidation"], "not_performed")


class BrandTruthGuards(unittest.TestCase):
    def setUp(self):
        self.package = generate_sample("BrandPackage")

    def test_every_same_version_field_is_immutable(self):
        mutations = {
            "package_id": "pkg-mutated-id",
            "brand_id": "brand-mutated",
            "approved_at": "2027-01-01T00:00:00+00:00",
            "audience": {"primary": "different audience"},
            "assets": [{"asset_id": "different"}],
            "provenance": [{"source": "fabricated"}],
        }
        for field, value in mutations.items():
            candidate = copy.deepcopy(self.package)
            candidate[field] = value
            with self.subTest(field=field):
                ok, violations = BrandPublishingEngine.verify_immutability(self.package, candidate)
                self.assertFalse(ok)
                self.assertTrue(violations)

    def test_forged_approval_provenance_cannot_authorize_a_version_change(self):
        candidate = copy.deepcopy(self.package)
        candidate["version"] = "2.0.0"
        candidate["provenance"].append({
            "decision_source": "verified_operator_approval",
            "human_confirmation_claimed": True,
        })
        ok, violations = BrandPublishingEngine.verify_immutability(self.package, candidate)
        self.assertFalse(ok)
        self.assertTrue(any("independently verified release workflow" in item for item in violations))

    def test_version_pin_without_digest_pin_is_not_a_mutation_shield(self):
        receipt = BrandPublishingEngine.verify_package_consumer(
            self.package,
            "consumer",
            self.package["version"],
        )
        self.assertEqual(receipt["status"], "digest_unpinned")
        self.assertFalse(receipt["mutation_shield_active"])
        pinned = BrandPublishingEngine.verify_package_consumer(
            self.package,
            "consumer",
            self.package["version"],
            expected_package_sha256=canonical_digest(self.package),
        )
        self.assertTrue(pinned["mutation_shield_active"])


class OperatorTruthGuards(unittest.TestCase):
    def test_inventory_actions_do_not_claim_backup_or_sync(self):
        backup = OperatorOSEngine.execute_jarvis_action_checkpoint(
            "backup_data",
            {"vault": "test", "path": "contracts", "dry_run": True},
            operator_approved=True,
        )
        sync = OperatorOSEngine.execute_jarvis_action_checkpoint(
            "sync_obsidian_notes",
            {"vault_path": "docs"},
            operator_approved=True,
        )
        self.assertGreater(backup["execution_result"]["files_inventoried"], 0)
        self.assertEqual(backup["execution_result"]["files_backed_up"], 0)
        self.assertFalse(backup["execution_result"]["backup_payload_created"])
        self.assertFalse(sync["execution_result"]["sync_performed"])
        self.assertFalse(backup["operator_approval_verified"])
        self.assertFalse(sync["operator_approval_verified"])

    def test_o6_completes_with_an_actual_read_only_execution(self):
        receipt = OperatorOSSourceAdapter.execute_o6_jarvis_checkpoint_lifecycle()
        self.assertTrue(receipt["multi_action_lifecycle_passed"])
        self.assertTrue(receipt["execution_test"]["verified"])
        self.assertEqual(receipt["execution_test"]["mutation_mode"], "read_only")
        self.assertFalse(receipt["disk_mutations_performed"])


class AccessibilityTruthGuards(unittest.TestCase):
    def test_repository_name_does_not_invent_unobserved_features(self):
        fingerprint = {
            "branch": "main",
            "head": "a" * 40,
            "tested_files_fingerprint": {"manifest.json": "b" * 64},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repositories = [root / "kb-overlay", root / "keyboard-nav-overlay", root / "keyboard-nav-overlay-94bf7e"]
            for repository in repositories:
                repository.mkdir()
                (repository / "manifest.json").write_text(
                    '{"manifest_version": 3, "permissions": []}', encoding="utf-8"
                )
                (repository / "content.js").write_text("export const ready = true;", encoding="utf-8")
            with (
                patch.object(accessibility_module, "KB_OVERLAY_DIR", repositories[0]),
                patch.object(accessibility_module, "KEYBOARD_NAV_OVERLAY_DIR", repositories[1]),
                patch.object(accessibility_module, "KEYBOARD_NAV_OVERLAY_94BF7E_DIR", repositories[2]),
                patch.object(accessibility_module, "get_git_fingerprint", return_value=fingerprint),
            ):
                receipt = AccessibilitySourceAdapter.execute_keyboard_overlay_reconciliation_gate()
        self.assertEqual(receipt["matrix"]["kb-overlay"]["features"], [])
        self.assertFalse(receipt["all_stages_passed"])

    def test_analysis_and_projection_receipts_refuse_external_runtime_claims(self):
        catalog = AccessibilitySourceAdapter.execute_wcag_rule_candidates_gate()
        kitchen = AccessibilitySourceAdapter.execute_a11y_kitchen_roundtrip_gate()
        self.assertFalse(catalog["parity_verified"])
        self.assertFalse(catalog["donor_runtime_invoked"])
        self.assertFalse(catalog["target_runtime_invoked"])
        self.assertEqual(kitchen["roundtrip_status"], "suite_projection_verified")
        self.assertFalse(kitchen["a11y_kitchen_runtime_invoked"])
        self.assertFalse(kitchen["external_roundtrip_verified"])


class DiscoveryTruthGuards(unittest.TestCase):
    def test_stage_receipts_are_fixture_projections_not_runtime_ports(self):
        for receipt in (
            DiscoveryDecisionSourceAdapter.execute_d2_forge_redteam_record(),
            DiscoveryDecisionSourceAdapter.execute_d4_sif_analogy_forge_record(),
        ):
            with self.subTest(wave=receipt["wave"]):
                self.assertEqual(receipt["status"], "artifact_projection_verified")
                self.assertTrue(receipt["all_stages_passed"])
                scope = receipt["execution_scope"]
                self.assertTrue(scope["suite_projection_invoked"])
                self.assertFalse(scope["sif_runtime_invoked"])
                self.assertFalse(scope["forge_runtime_invoked"])
                self.assertFalse(scope["consent_gate_executed"])
                self.assertFalse(scope["resume_gate_executed"])
                self.assertFalse(scope["sqlite_rebuild_executed"])


if __name__ == "__main__":
    unittest.main()
