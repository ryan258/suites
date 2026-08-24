"""Verification of retained wave evidence receipts against their declared recovery claims.

Dispatches by claim kind to versioned validators so a receipt that records successfully
cannot later fail registry validation, and a claim kind without an implemented contract
is refused rather than waved through.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from .contracts import ContractError, validate_contract
from .provenance import is_meaningful_git_fingerprint
from .recovery_policy import (
    RECEIPT_CONTRACT_FOR_KIND,
    RECOVERY_ENFORCEMENT,
    RECOVERY_RECEIPT_CONTRACTS,
    RECOVERY_RESOLUTION_OUTCOMES,
)

import re

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _analysis_evidence_errors(path: Path, evidence_basis: set[str]) -> list[str]:
    """Check a retained analysis receipt actually contains the basis it claims.

    Runtime claims draw their basis from the closed RUNTIME_PARITY_EVIDENCE vocabulary.
    An analysis claim instead names fields of its own evidence: top-level keys for a JSON
    receipt, literal markers for a prose one. Either way the names must really be there.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"analysis evidence cannot be read: {error}"]

    if path.suffix == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            return [f"analysis evidence is not valid JSON: {error}"]
        if not isinstance(document, dict):
            return ["analysis evidence must be a JSON object"]
        present = set(document)
    else:
        present = {marker for marker in evidence_basis if marker in text}

    missing = sorted(evidence_basis - present)
    if missing:
        return [f"analysis evidence does not contain its declared basis: {', '.join(missing)}"]
    return []


_MISSING = object()

# Accepting a receipt no contract can check is indistinguishable from checking it and
# finding nothing wrong, and the recorder writes on that same empty list. A claim kind
# without a versioned receipt contract therefore refuses rather than passes; adding the
# contract is what lifts the refusal.
_UNSUPPORTED_EVIDENCE_CONTRACT = (
    "no versioned evidence receipt contract is implemented for {what}, "
    "so its receipt cannot be verified and is refused"
)


def _receipt_value(document: dict[str, Any], dotted_path: str) -> Any:
    value: Any = document
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


ANALYSIS_RECEIPT_SPECS: dict[str, dict[str, Any]] = {
    "accessibility/A3": {
        "equals": {"canonical_target": "kb-overlay"},
        "objects": ["matrix"],
        "strings": ["recommendation"],
    },
    "accessibility/A5": {
        "equals": {
            "all_stages_passed": True,
            "evidence_loss": False,
            "roundtrip_status": "suite_projection_verified",
            "a11y_kitchen_runtime_invoked": False,
            "external_roundtrip_verified": False,
        },
        "objects": ["canonical_finding"],
        "contracts": {"canonical_finding": "A11yFinding"},
    },
    "operator-os/O2": {
        "equals": {"wave_id": "O2", "status": "verified"},
        "objects": ["fingerprints", "canonical_anchors_confirmed"],
        "lists": ["ryos_core_files", "master_plan_files", "inventory_catalog"],
        "minimums": {
            "ryos_core_files_count": 3,
            "master_plan_files_count": 1,
            "inventory_catalog_count": 5,
        },
        "fingerprints": [
            "fingerprints.ryos",
            "fingerprints.master_upgrade_plan",
            "fingerprints.dotfiles",
            "fingerprints.obsidian_observer",
        ],
    },
    "operator-os/O3": {
        "equals": {
            "wave_id": "O3",
            "status": "preview_verified",
            "dry_run_only": True,
            "requires_human_approval": True,
        },
        "objects": ["jarvis_runtime", "action_preview"],
        "strings": ["recovery_path"],
        "fingerprints": ["jarvis_runtime"],
    },
    "operator-os/O4": {
        "equals": {
            "wave_id": "O4",
            "status": "stream_intake_verified",
            "all_fenced_from_reingestion": True,
            "all_sources_cited": True,
        },
        "lists": ["processed_records"],
        "fingerprints": ["pkos_fingerprint", "observer_fingerprint", "dotfiles_fingerprint"],
        "minimums": {"batch_size": 3, "observer_projections_count": 1, "donor_notes_read": 3},
    },
    "operator-os/O5": {
        "equals": {
            "wave_id": "O5",
            "status": "disposition_proposal_recorded",
            # The negative fields are required, not merely allowed. A receipt that simply
            # omitted them would read as silence about whether closure happened; asserting
            # them false is what makes the gate's boundary machine-checked.
            "duplicate_decisions_closed": False,
            "migration_acceptance_verified": False,
            "donor_read": True,
            "external_runtime_invoked": False,
            # The positive half of the same boundary. Without these the receipt could say
            # the run failed, or that closure was decided outright, and still validate --
            # the narrowed gate would have been asserted by the prose alone.
            "all_stages_passed": True,
            "duplicate_decision_disposition": "close_on_verification",
        },
        "objects": ["canonical_anchors"],
        "lists": ["proposed_ports", "source_inventory_catalog"],
        "minimums": {"port_candidates_count": 2},
    },
    "operator-os/O6": {
        "equals": {
            "wave_id": "O6",
            "status": "checkpoint_lifecycle_verified",
            "multi_action_lifecycle_passed": True,
            "disk_mutations_performed": False,
        },
        "objects": ["fail_closed_test", "preview_test"],
        "fingerprints": ["jarvis_fingerprint"],
    },
    "operator-os/O1": {
        "equals": {
            "wave_id": "O1",
            "status": "cas_projection_verified",
            "all_stages_passed": True,
            "cas_verified": True,
            "mutation_protection_passed": True,
            "operational_errors": [],
            "source_derived_assertions.sensitivity_test_passed": True,
        },
        "objects": ["source_record", "cas_acquisition", "source_derived_assertions", "target", "donor"],
        "strings": [
            "observer_projection_preview",
            "source_derived_assertions.donor_source_path",
            "source_derived_assertions.donor_sha256",
            "source_derived_assertions.cas_object_path",
        ],
        "minimums": {
            "source_derived_assertions.donor_bytes": 100,
            "source_derived_assertions.sqlite_normalized_items": 1,
            "source_derived_assertions.sqlite_normalized_chunks": 1,
        },
        "fingerprints": ["donor.fingerprint", "target.pkos_fingerprint", "target.observer_fingerprint"],
        "contracts": {"source_record": "SourceRecord"},
    },
    "brand-publishing/B1": {
        "equals": {
            "wave": "B1",
            "status": "verified_candidate",
            "mutation_protection_passed": True,
            "publishing_receipt.dry_run_only": True,
            "publishing_receipt.live_published": False,
            "source_derived_assertions.sensitivity_test_passed": True,
        },
        "objects": ["brand_package", "source_record", "publishing_receipt", "target", "consumer", "source_derived_assertions"],
        "lists": [
            "mutation_tests",
            "source_derived_assertions.asserted_exports",
            "source_derived_assertions.asserted_functions",
            "source_derived_assertions.asserted_token_categories",
            "source_derived_assertions.asserted_voice_sections",
            "source_derived_assertions.asserted_audiences",
        ],
        "strings": [
            "source_derived_assertions.donor_source_path",
            "source_derived_assertions.spec_source_path",
        ],
        "fingerprints": ["target.fingerprint", "consumer.fingerprint"],
        "contracts": {"brand_package": "BrandPackage", "source_record": "SourceRecord"},
    },
    "brand-publishing/B2": {
        "equals": {
            "wave": "B2",
            "status": "all_phases_mapped",
            "total_phases_mapped": 9,
        },
        "objects": ["donor", "target"],
        "lists": ["phase_mappings"],
        "fingerprints": ["donor.fingerprint", "target.fingerprint"],
    },
    "brand-publishing/B3": {
        "equals": {"status": "dry_run_verified", "dry_run_only": True, "live_published": False},
        "strings": ["brand_package_id", "source_id", "source_sha256"],
        "minimums": {"matched_approved_claims_count": 1},
    },
    "brand-publishing/B4": {
        "equals": {
            "status": "verified",
            "consumer_1.status": "verified",
            "consumer_1.version_match": True,
            "consumer_1.mutation_shield_active": True,
            "consumer_2.status": "verified",
            "consumer_2.version_match": True,
            "consumer_2.mutation_shield_active": True,
        },
        "objects": ["consumer_1", "consumer_2"],
    },
    "brand-publishing/B5": {
        "equals": {
            "phases_total": 9,
            "phases_completed": 9,
            "reconciliation_status": "workshop_aligned_intake_validated",
            "brand_workshop_read": True,
            "external_runtime_invoked": False,
        },
        "lists": ["intake_log", "workshop_phases"],
        "objects": ["resulting_package"],
        "contracts": {"resulting_package": "BrandPackage"},
    },
    "brand-publishing/B6": {
        "equals": {
            "approved_review.status": "simulated_review_passed",
            "approved_review.simulated_gate.boundary_check": "stopped_before_live_publish",
            "approved_review.simulated_gate.decision_source": "simulated_fixture",
            "approved_review.simulated_gate.human_confirmation_claimed": False,
            "approved_review.dry_run_receipt.dry_run_only": True,
            "approved_review.dry_run_receipt.live_published": False,
            "rejected_probe_status": "simulated_blocked_rejected",
            "unmatched_probe_status": "simulated_blocked_unmatched_claims",
        },
        "objects": ["approved_review"],
    },
    "production-house/P1": {
        "equals": {
            "wave": "P1",
            "status": "source_episode_script_projected",
            "episode_artifacts_read": True,
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job", "script"],
        "fingerprints": [
            "production_house_fingerprint",
            "groundwire_fingerprint",
            "formatter_fingerprint",
        ],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P2": {
        "equals": {
            "wave": "P2",
            "status": "source_play_projected",
            "external_formatter_invoked": False,
            "fixture_output_only": True,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job", "script"],
        "fingerprints": ["formatter_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P3": {
        "equals": {
            "wave": "P3",
            "status": "source_handoff_projected",
            "writers_room_runtime_invoked": False,
            "signoff_observed": False,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job", "script"],
        "fingerprints": ["writers_room_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P4": {
        "equals": {
            "wave": "P4",
            "status": "source_documentary_script_projected",
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job", "script"],
        "fingerprints": ["production_house_fingerprint", "groundwire_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P5": {
        "equals": {
            "wave": "P5",
            "status": "source_event_stream_projected",
            "writers_room_runtime_invoked": False,
            "runtime_consolidation_performed": False,
            "mapping.writers_room_runtime_invoked": False,
            "mapping.signoff_observed": False,
            "mapping.runtime_consolidation": "not_performed",
            "all_stages_passed": True,
        },
        "objects": ["mapping", "mapping.mapped_job"],
        "fingerprints": ["writers_room_fingerprint"],
        "contracts": {"mapping.mapped_job": "ProductionJob"},
    },
    "model-behavior-lab/M1": {
        "equals": {
            "wave": "M1",
            "status": "normalized",
            "all_stages_passed": True,
            "field_parity.all_fields_match": True,
        },
        "objects": ["canonical_run", "field_parity", "donor_result"],
        "lists": ["canonical_run.iterations"],
        "strings": ["donor_result.path", "donor_result.sha256"],
        "fingerprints": ["ethics_comparator_fingerprint"],
        "contracts": {"canonical_run": "ExperimentRun"},
    },
    "model-behavior-lab/M2": {
        "equals": {
            "wave": "M2",
            "status": "extraction_matrix_measured",
            "all_stages_passed": True,
            "extraction_matrix.canonical_slice_implemented": False,
            "extraction_matrix.duplicate_runtimes_eliminated": 0,
        },
        "objects": ["extraction_matrix", "extraction_matrix.donor_subsystem_copies"],
        "lists": ["packs", "extraction_matrix.subsystems_duplicated_across_donors"],
        "minimums": {
            "extraction_matrix.packs_normalized_through_kernel": 2,
            "extraction_matrix.duplicate_runtimes_remaining_in_donors": 1,
        },
        "fingerprints": ["ethics_comparator_fingerprint", "strength_comparator_fingerprint"],
    },
    "model-behavior-lab/M3": {
        "equals": {
            "wave": "M3",
            "status": "fixture_verified",
            "all_stages_passed": True,
            "legality_check.legal": True,
            "match_fixture.repeat_verdict_stable": True,
            "legality_evaluator": "suite_local",
            # M3 sits at `source_inspected`, and this is the field that earns it: the rung
            # means authentic donor artifacts were read and parsed. Leaving it unrequired let
            # the claim rest on the objective's prose rather than on the receipt.
            "donor_match_logs_read": True,
            "donor_legality_checker_invoked": False,
            "whole_match_replayed": False,
        },
        "objects": ["match_fixture", "legality_check"],
        "strings": ["match_fixture.source_sha256", "match_fixture.invalid_move_behavior"],
        "fingerprints": ["ai_chess_fingerprint"],
    },
    "model-behavior-lab/M4": {
        "equals": {"wave": "M4", "status": "benchmark_verified", "all_stages_passed": True},
        "objects": ["canonical_run", "kernel_generality"],
        "lists": ["canonical_run.iterations", "kernel_generality.domains_scored"],
        "fingerprints": ["ai_chess_fingerprint"],
        "contracts": {"canonical_run": "ExperimentRun"},
    },
    "accessibility/A4": {
        "equals": {
            "wave": "A4",
            "status": "catalog_analysis_verified",
            "all_stages_passed": True,
            "parity_verified": False,
            "donor_runtime_invoked": False,
            "target_runtime_invoked": False,
            "verification_scope": "source_catalog_and_suite_projection_only",
            "false_positive_probe_passed": True,
            "source_derived_assertions.sensitivity_test_passed": True,
        },
        "objects": ["catalog_evaluation", "source_derived_assertions", "target", "donor"],
        "lists": [
            "heuristic_findings_sample",
            "catalog_evaluation.evaluations",
            "source_derived_assertions.asserted_rules",
            "source_derived_assertions.asserted_criteria",
            "source_derived_assertions.asserted_modules",
        ],
        "strings": ["source_derived_assertions.donor_source_path"],
        "minimums": {
            "catalog_evaluation.total_candidates_evaluated": 20,
            "catalog_evaluation.port_review_count": 18,
        },
        "fingerprints": ["target.fingerprint", "donor.fingerprint"],
    },
    "accessibility/A6": {
        "equals": {
            "wave": "A6",
            "status": "consolidation_proposed",
            "all_stages_passed": True,
            "proposed_canonical_anchor": "kb-overlay",
            "migration_acceptance_verified": False,
            "permission_analysis.canonical_no_broader_than_donors": True,
            "permission_analysis.minimized_permissions_verified": False,
        },
        "objects": [
            "permission_analysis",
            "donor_retirement",
            "reconciliation_matrix",
            "canonical_permission_surface",
        ],
        "lists": [
            "proposed_frozen_donors",
            "canonical_permission_surface.host_scope",
            "permission_analysis.minimization_outstanding",
        ],
        "fingerprints": [
            "reconciliation_matrix.kb-overlay.git_fingerprint",
            "reconciliation_matrix.keyboard-nav-overlay.git_fingerprint",
            "reconciliation_matrix.keyboard-nav-overlay-94bf7e.git_fingerprint",
        ],
    },
    "discovery-decision/D1": {
        "equals": {"wave": "D1", "status": "stage_matrix_verified", "all_stages_passed": True},
        "objects": ["forge_budgets", "sif_run_sampled"],
        "lists": ["matrix", "sif_run_sampled.artifacts"],
        "fingerprints": ["sif_fingerprint", "forge_fingerprint"],
    },
    "discovery-decision/D2": {
        "equals": {
            "wave": "D2",
            "status": "artifact_projection_verified",
            "all_stages_passed": True,
            "execution_scope.suite_projection_invoked": True,
            "execution_scope.sif_runtime_invoked": False,
            "execution_scope.forge_runtime_invoked": False,
            "execution_scope.consent_gate_executed": False,
            "execution_scope.resume_gate_executed": False,
            "execution_scope.sqlite_rebuild_executed": False,
        },
        "objects": ["investigation", "donor_artifact", "budget_source", "execution_scope"],
        "strings": ["donor_artifact.origin", "donor_artifact.sha256"],
        "fingerprints": ["sif_fingerprint", "forge_fingerprint"],
        "contracts": {"investigation": "InvestigationRecord"},
    },
    "discovery-decision/D3": {
        "equals": {
            "wave": "D3",
            "status": "sources_cited_with_excerpts",
            "all_stages_passed": True,
            "lexical_overlap.semantic_relation_asserted": False,
            "discovery_limitations.semantic_discovery_performed": False,
            "discovery_limitations.novelty_score_measured": False,
        },
        "objects": ["lexical_overlap", "discovery_limitations", "primary_source"],
        "lists": ["cited_sources", "document_excerpts"],
        "fingerprints": ["insight_excavator_fingerprint"],
        "contracts": {"primary_source": "SourceRecord"},
    },
    "discovery-decision/D4": {
        "equals": {
            "wave": "D4",
            "status": "artifact_projection_verified",
            "all_stages_passed": True,
            "execution_scope.suite_projection_invoked": True,
            "execution_scope.sif_runtime_invoked": False,
            "execution_scope.forge_runtime_invoked": False,
            "execution_scope.consent_gate_executed": False,
            "execution_scope.resume_gate_executed": False,
            "execution_scope.sqlite_rebuild_executed": False,
        },
        "objects": ["investigation", "donor_artifact", "budget_source", "execution_scope"],
        "strings": ["donor_artifact.origin", "donor_artifact.sha256"],
        "fingerprints": ["sif_fingerprint", "forge_fingerprint"],
        "contracts": {"investigation": "InvestigationRecord"},
    },
    "discovery-decision/D5": {
        "equals": {
            "wave": "D5",
            "status": "retirement_proposed",
            "all_stages_passed": True,
            "retirement.retirement_performed": False,
            "retirement.standalone_excavator_runtime_removed": False,
            "retirement.owner_approval_required": True,
        },
        "objects": [
            "folded_investigation",
            "forge_investigation",
            "primary_source",
            "retirement",
            "citation_provenance",
        ],
        "lists": ["cited_sources"],
        "strings": ["forge_investigation.sha256", "forge_investigation.ID", "citation_provenance.sha256"],
        "fingerprints": ["insight_excavator_fingerprint", "forge_fingerprint"],
        "contracts": {"primary_source": "SourceRecord"},
    },
    "agent-reliability/R1": {
        "equals": {"wave": "R1", "status": "fixtures_defined", "all_stages_passed": True},
        "objects": ["canonical_run", "donor_policy", "engine_scorecard"],
        "lists": ["canonical_run.iterations"],
        "fingerprints": ["looping_box_fingerprint"],
        "contracts": {"canonical_run": "ExperimentRun"},
    },
    "agent-reliability/R2": {
        "equals": {"wave": "R2", "status": "coverage_measured", "all_stages_passed": True},
        "objects": ["harness_coverage", "gates_covered", "fingerprints"],
        "strings": ["execution_limitation"],
        "lists": ["gates_covered.confinement", "gates_covered.rollback"],
        "fingerprints": [
            "fingerprints.looping_box",
            "fingerprints.sssf",
            "fingerprints.agentic_harness",
        ],
    },
    "agent-reliability/R3": {
        "equals": {"wave": "R3", "status": "consumers_measured", "all_stages_passed": True},
        "objects": ["measurement"],
        "lists": ["promoted_components"],
        "fingerprints": ["components_fingerprint"],
    },
    "agent-reliability/R4": {
        "equals": {
            "wave": "R4",
            "status": "craft_rule_enforced",
            "all_stages_passed": True,
            "audit.craft_rule_enforced": True,
        },
        "objects": ["audit"],
        "lists": ["audited_components", "audit.retained"],
        "fingerprints": ["components_fingerprint"],
    },
    "agent-reliability/R5": {
        "equals": {"wave": "R5", "status": "curriculum_mined", "all_stages_passed": True},
        "objects": ["curriculum_fixtures"],
        "lists": ["mined_modules"],
        "fingerprints": ["ai_staff_fingerprint", "agentic_harness_fingerprint"],
    },
    "game-design/G2": {
        "equals": {
            "wave": "G2",
            "status": "pack_shape_projected",
            "all_stages_passed": True,
            "shape_projection.parallel_engine_written": False,
            "shape_projection.pack_materialized_on_disk": False,
            "shape_projection.statistical_parity_measured": False,
            "shape_projection.independent_resimulation_verified": False,
            "shape_projection.pack_slots_within_observed_vocabulary": True,
        },
        "objects": ["pack", "shape_projection", "shape_projection.donor_outcome_distribution"],
        "lists": ["pack.reference_slots_written", "shape_projection.pack_slots_filled"],
        "minimums": {"shape_projection.donor_rows_summarized": 1},
        "fingerprints": ["tucked_in_terrors_fingerprint", "storyweaver_fingerprint"],
    },
    "game-design/G3": {
        "equals": {
            "wave": "G3",
            "status": "boundary_documented",
            "all_stages_passed": True,
            "engine_coupling.coupled": False,
            "boundary.platform_invented": False,
        },
        "objects": ["boundary", "engine_coupling"],
        "lists": ["authored_inventory"],
        "fingerprints": ["oregon_dnd_fingerprint"],
    },
    "game-design/G4": {
        "equals": {
            "wave": "G4",
            "status": "second_class_verified",
            "all_stages_passed": True,
            "schema_check.pack_slots_within_vocabulary": True,
        },
        "objects": ["pack", "schema_check"],
        "lists": ["schema_check.observed_gds_vocabulary", "schema_check.reference_slots_written"],
        "fingerprints": ["storyweaver_fingerprint"],
    },
    "game-design/G5": {
        "equals": {
            "wave": "G5",
            "status": "boundary_formalized",
            "all_stages_passed": True,
            "engine_coupling.coupled": False,
            "boundary.suite_dependency_required": False,
        },
        "objects": ["boundary", "engine_coupling"],
        "lists": ["donor_modules"],
        "fingerprints": ["march_madness_fingerprint"],
    },
    "model-behavior-lab/M5": {
        "equals": {"wave": "M5", "status": "corpus_pinned", "all_stages_passed": True},
        "objects": ["corpus_manifest", "fingerprints"],
        "lists": ["corpus_sources", "corpus_manifest.benchmarks_included"],
        "fingerprints": [
            "fingerprints.ai_ethics_comparator",
            "fingerprints.ai_strength_comparator",
            "fingerprints.ai_chess",
        ],
    },
}


def _lookup_receipt_spec(
    suite_id: str | None, wave_id: str | None
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Resolve one receipt spec, or explain why no single spec applies.

    A known suite selects its own entry outright. Without one, a bare wave ID is accepted
    only while it identifies exactly one suite; once two suites declare the same wave
    letter the fallback refuses, because guessing between them would check a receipt
    against another suite's assertions and call that a pass.
    """
    if suite_id:
        key = f"{suite_id}/{wave_id}"
        spec = ANALYSIS_RECEIPT_SPECS.get(key)
        if spec is None:
            return None, (
                f"wave {key} has no ANALYSIS_RECEIPT_SPECS definition "
                "for JSON semantic validation"
            ), None
        return spec, None, key

    matches = [key for key in ANALYSIS_RECEIPT_SPECS if key.split("/", 1)[1] == wave_id]
    if not matches:
        return None, (
            f"wave {wave_id} has no ANALYSIS_RECEIPT_SPECS definition for JSON semantic validation"
        ), None
    if len(matches) > 1:
        return None, (
            f"wave {wave_id} matches several suites ({', '.join(sorted(matches))}); "
            "the caller must name its suite to select a receipt spec"
        ), None
    return ANALYSIS_RECEIPT_SPECS[matches[0]], None, matches[0]


def _analysis_receipt_semantic_errors(
    wave: dict[str, Any], document: dict[str, Any], suite_id: str | None = None
) -> list[str]:
    """Validate expected values and shapes for a completed analysis receipt.

    Specs are keyed `<suite id>/<wave id>` so two suites may use the same wave letter
    without silently sharing one another's assertions. A caller that does not know its
    suite falls back to a unique bare wave ID, and an ambiguous one is refused rather
    than resolved to whichever entry happens to match.
    """
    wave_id = wave.get("id")
    spec, lookup_error, spec_key = _lookup_receipt_spec(suite_id, wave_id)
    if lookup_error:
        return [lookup_error]

    errors: list[str] = []
    for dotted_path, expected in spec.get("equals", {}).items():
        actual = _receipt_value(document, dotted_path)
        if actual is _MISSING or actual != expected or type(actual) is not type(expected):
            errors.append(f"{dotted_path} must equal {expected!r}")
    for dotted_path in spec.get("objects", []):
        actual = _receipt_value(document, dotted_path)
        if not isinstance(actual, dict) or not actual:
            errors.append(f"{dotted_path} must be a non-empty object")
    for dotted_path in spec.get("lists", []):
        actual = _receipt_value(document, dotted_path)
        if not isinstance(actual, list) or not actual:
            errors.append(f"{dotted_path} must be a non-empty list")
    for dotted_path in spec.get("strings", []):
        actual = _receipt_value(document, dotted_path)
        if not isinstance(actual, str) or not actual.strip():
            errors.append(f"{dotted_path} must be a non-empty string")
    for dotted_path, minimum in spec.get("minimums", {}).items():
        actual = _receipt_value(document, dotted_path)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or actual < minimum:
            errors.append(f"{dotted_path} must be at least {minimum}")
    for dotted_path, contract_name in spec.get("contracts", {}).items():
        actual = _receipt_value(document, dotted_path)
        if not isinstance(actual, dict):
            errors.append(f"{dotted_path} must be a valid {contract_name} object")
            continue
        try:
            validate_contract(contract_name, actual)
        except ContractError as error:
            errors.append(f"{dotted_path} violates {contract_name}: {error}")
    for dotted_path in spec.get("fingerprints", []):
        if not is_meaningful_git_fingerprint(_receipt_value(document, dotted_path)):
            errors.append(f"{dotted_path} must be a meaningful source fingerprint")

    # Dispatch on the resolved spec key. These rules encode one suite's receipt shape --
    # accessibility's three keyboard overlays, brand-publishing's nine phases -- and a
    # different suite reusing the wave letter must not inherit them.
    if spec_key == "accessibility/A3":
        matrix = document.get("matrix", {})
        expected_overlays = {"kb-overlay", "keyboard-nav-overlay", "keyboard-nav-overlay-94bf7e"}
        if not isinstance(matrix, dict) or set(matrix) != expected_overlays:
            errors.append("matrix must contain exactly the three declared overlay sources")
        else:
            for name, overlay in matrix.items():
                if not (
                    isinstance(overlay, dict)
                    and isinstance(overlay.get("features"), list)
                    and bool(overlay.get("features"))
                    and isinstance(overlay.get("code_size_bytes"), int)
                    and overlay.get("code_size_bytes", 0) > 0
                ):
                    errors.append(f"matrix.{name} must retain non-empty inventory measurements")
        claim_level = (wave.get("recovery_claim") or {}).get("level")
        if claim_level == "parity_verified" and not (
            document.get("browser_evaluation_passed") is True
            and document.get("accessibility_parity_verified") is True
        ):
            errors.append("A3 receipt containing only source inventory cannot substantiate a parity_verified claim")
        if document.get("receipt_version") != "accessibility-a3-analysis-v2":
            errors.append("A3 receipt_version must be accessibility-a3-analysis-v2")
        elif isinstance(matrix, dict):
            verification = document.get("source_verification", {})
            if not (
                isinstance(verification, dict)
                and verification.get("passed") is True
                and verification.get("errors") == []
                and verification.get("donors_checked") == 3
            ):
                errors.append("A3 v2 source verification must retain a clean three-donor pass")
            for name, overlay in matrix.items():
                if not (
                    isinstance(overlay, dict)
                    and overlay.get("source_available") is True
                    and overlay.get("manifest_valid") is True
                    and overlay.get("fingerprint_verified") is True
                    and isinstance(overlay.get("code_size_bytes"), int)
                    and overlay.get("code_size_bytes", 0) > 0
                    and is_meaningful_git_fingerprint(overlay.get("git_fingerprint"))
                ):
                    errors.append(f"matrix.{name} must retain verified source measurements")
    elif spec_key == "accessibility/A4":
        catalog = document.get("catalog_evaluation", {})
        evaluations = catalog.get("evaluations", []) if isinstance(catalog, dict) else []
        if len(evaluations) != catalog.get("total_candidates_evaluated"):
            errors.append("catalog evaluation count must match the retained evaluations")
        for index, item in enumerate(evaluations):
            finding = item.get("finding") if isinstance(item, dict) else None
            try:
                validate_contract("A11yFinding", finding)
            except (ContractError, TypeError) as error:
                errors.append(f"catalog_evaluation.evaluations.{index}.finding violates A11yFinding: {error}")
    elif spec_key == "operator-os/O4":
        for index, record in enumerate(document.get("processed_records", [])):
            try:
                validate_contract("SourceRecord", record)
            except (ContractError, TypeError) as error:
                errors.append(f"processed_records.{index} violates SourceRecord: {error}")
    elif spec_key == "brand-publishing/B1":
        mutation_tests = document.get("mutation_tests", [])
        if any(not isinstance(test, dict) or test.get("passed") is not True for test in mutation_tests):
            errors.append("every B1 mutation test must retain an explicit pass")
    elif spec_key == "brand-publishing/B2":
        if len(document.get("phase_mappings", [])) != 9:
            errors.append("B2 must retain exactly nine phase mappings")
    elif spec_key == "brand-publishing/B5":
        if len(document.get("intake_log", [])) != 9:
            errors.append("B5 must retain exactly nine intake phases")
    elif spec_key == "brand-publishing/B6":
        app_rev = document.get("approved_review", {})
        sim_gate = app_rev.get("simulated_gate") or app_rev.get("human_gate", {})
        if isinstance(sim_gate, dict):
            if sim_gate.get("decision_source") == "simulated_fixture" and sim_gate.get("human_confirmation_claimed") is not False:
                errors.append("B6 simulated review gate must declare human_confirmation_claimed as false")
            if sim_gate.get("decision_source") == "simulated_fixture" and app_rev.get("status") == "ready_for_operator_release":
                errors.append("B6 simulated review cannot claim ready_for_operator_release without explicit operator approval")
    elif spec_key in {"production-house/P1", "production-house/P2", "production-house/P3", "production-house/P4"}:
        job = document.get("job", {})
        expected_collection = "inputs" if wave_id == "P3" else "outputs"
        expected_minimum = 1
        expected_exact = 3 if wave_id in {"P1", "P4"} else None
        collection = job.get(expected_collection, []) if isinstance(job, dict) else []
        if not isinstance(collection, list) or len(collection) < expected_minimum:
            errors.append(f"job.{expected_collection} must retain the declared job evidence")
        elif expected_exact is not None and len(collection) != expected_exact:
            errors.append(f"job.{expected_collection} must contain exactly {expected_exact} items")

    return errors


def _runtime_parity_receipt_errors(path: Path, contract_id: str) -> list[str]:
    """Validate a retained runtime receipt through an explicitly versioned contract."""
    if contract_id not in RECOVERY_RECEIPT_CONTRACTS:
        return [f"unsupported runtime parity receipt contract: {contract_id!r}"]
    if contract_id == "portfolio-runtime-parity-v1":
        return _portfolio_runtime_receipt_errors(path, contract_id, "parity_verified")
    if contract_id != "accessibility-wcag-331-v1":
        return [f"receipt contract {contract_id!r} is not a runtime parity contract"]
    try:
        receipt = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"runtime parity receipt cannot be loaded: {error}"]

    errors: list[str] = []
    donor = receipt.get("donor", {})
    target = receipt.get("target", {})
    stages = receipt.get("stages", {})
    recovery = receipt.get("recovery_behavior", {})
    required_passed_stages = {
        "donor_source_invocation",
        "donor_browser_evaluation",
        "focused_parity_gate",
        "full_suite_and_typecheck_gate",
        "full_audit_integration_gate",
    }

    if (
        receipt.get("status") != "parity_verified"
        or receipt.get("all_stages_passed") is not True
        or receipt.get("operational_errors") != []
    ):
        errors.append("runtime parity receipt must retain a clean all-stages pass")
    if not (
        donor.get("source_invoked") is True
        and donor.get("browser_runtime_invoked") is True
        and donor.get("donor_parity_verified") is True
    ):
        errors.append("runtime parity receipt must prove authentic donor execution and parity")
    if any(stages.get(stage, {}).get("passed") is not True for stage in required_passed_stages):
        errors.append("runtime parity receipt is missing a required passed execution stage")
    if stages.get("full_suite_and_typecheck_gate", {}).get("skipped") is not False:
        errors.append("runtime parity receipt cannot retain a skipped full-suite gate")
    if stages.get("full_audit_integration_gate", {}).get("skipped") is not False:
        errors.append("runtime parity receipt cannot retain a skipped full-audit gate")
    if len(receipt.get("representative_inputs", [])) < 3:
        errors.append("runtime parity receipt needs representative input evidence")
    if not (
        target.get("fingerprint", {}).get("head")
        and donor.get("fingerprint", {}).get("head")
        and target.get("fingerprint", {}).get("lockfile_sha256")
        and donor.get("fingerprint", {}).get("lockfile_sha256")
    ):
        errors.append("runtime parity receipt needs source and dependency fingerprints")
    if not (
        recovery.get("runtime_mutation_mode") == "read_only"
        and recovery.get("rerun_safe") is True
        and recovery.get("environment_failures_fail_closed") is True
    ):
        errors.append("runtime parity receipt needs fail-closed rerun and recovery evidence")
    return errors


def _receipt_document(path: Path, contract_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        document = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return None, [f"{contract_id} receipt cannot be loaded: {error}"]
    errors = []
    if document.get("receipt_version") != contract_id:
        errors.append(f"receipt_version must equal {contract_id!r}")
    if document.get("operational_errors") != []:
        errors.append("operational_errors must be an empty list")
    return document, errors


def _meaningful_fingerprint_collection(value: Any) -> bool:
    if isinstance(value, dict):
        values = list(value.values())
    elif isinstance(value, list):
        values = value
    else:
        return False
    return bool(values) and all(is_meaningful_git_fingerprint(item) for item in values)


def _portfolio_runtime_receipt_errors(path: Path, contract_id: str, level: str) -> list[str]:
    document, errors = _receipt_document(path, contract_id)
    if document is None:
        return errors
    expected_status = "source_executed" if level == "source_executed" else "parity_verified"
    if document.get("status") != expected_status or document.get("all_stages_passed") is not True:
        errors.append(f"runtime receipt must retain status {expected_status!r} and all_stages_passed true")
    source = document.get("source_invocation")
    if not (
        isinstance(source, dict)
        and isinstance(source.get("command"), list)
        and source.get("command")
        and source.get("exit_code") == 0
    ):
        errors.append("source_invocation must retain an argv command and zero exit code")
    if not _meaningful_fingerprint_collection(document.get("source_fingerprints")):
        errors.append("source_fingerprints must contain meaningful Git and content fingerprints")
    commands = document.get("reproducible_commands")
    if not isinstance(commands, list) or not commands or any(not isinstance(item, list) or not item for item in commands):
        errors.append("reproducible_commands must retain at least one argv command")
    if level != "source_executed":
        destination = document.get("destination_invocation")
        if not (
            isinstance(destination, dict)
            and isinstance(destination.get("command"), list)
            and destination.get("command")
            and destination.get("exit_code") == 0
        ):
            errors.append("destination_invocation must retain an argv command and zero exit code")
        if document.get("output_parity") is not True or document.get("failure_parity") is not True:
            errors.append("runtime parity requires explicit output_parity and failure_parity passes")
        if not isinstance(document.get("representative_inputs"), list) or not document["representative_inputs"]:
            errors.append("runtime parity requires representative_inputs")
        recovery = document.get("recovery_behavior")
        if not isinstance(recovery, dict) or recovery.get("rerun_safe") is not True:
            errors.append("runtime parity requires rerun-safe recovery behavior")
    return errors


def _adoption_receipt_errors(path: Path, contract_id: str) -> list[str]:
    document, errors = _receipt_document(path, contract_id)
    if document is None:
        return errors
    if document.get("status") != "adopted":
        errors.append("adoption receipt status must be 'adopted'")
    uses = document.get("accepted_uses")
    if not isinstance(uses, list) or len(uses) < RECOVERY_ENFORCEMENT["minimum_authentic_uses_for_adoption"]:
        return errors + ["adoption receipt requires at least three accepted authentic uses"]
    use_ids: set[str] = set()
    input_hashes: set[str] = set()
    for index, use in enumerate(uses):
        if not isinstance(use, dict):
            errors.append(f"accepted_uses.{index} must be an object")
            continue
        use_id = use.get("use_id")
        digest = use.get("input_sha256")
        if not isinstance(use_id, str) or not use_id.strip() or use_id in use_ids:
            errors.append(f"accepted_uses.{index}.use_id must be unique and non-empty")
        else:
            use_ids.add(use_id)
        if not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest) or digest in input_hashes:
            errors.append(f"accepted_uses.{index}.input_sha256 must be a unique SHA-256")
        else:
            input_hashes.add(digest)
        if use.get("accepted") is not True:
            errors.append(f"accepted_uses.{index}.accepted must be true")
        if not isinstance(use.get("evidence_ref"), str) or not use["evidence_ref"].strip():
            errors.append(f"accepted_uses.{index}.evidence_ref must be non-empty")
        try:
            occurred = str(use.get("occurred_at", ""))
            if "T" not in occurred or datetime.datetime.fromisoformat(occurred.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append(f"accepted_uses.{index}.occurred_at must be a timezone-aware date-time")
    parity_hash = document.get("parity_receipt_sha256")
    if not isinstance(parity_hash, str) or not SHA256_HEX.fullmatch(parity_hash):
        errors.append("parity_receipt_sha256 must bind adoption to validated parity evidence")
    return errors


def _convergence_receipt_errors(path: Path, contract_id: str) -> list[str]:
    document, errors = _receipt_document(path, contract_id)
    if document is None:
        return errors
    if document.get("status") != "converged":
        errors.append("convergence receipt status must be 'converged'")
    if not isinstance(document.get("canonical_runtime"), str) or not document["canonical_runtime"].strip():
        errors.append("canonical_runtime must name the surviving runtime")
    duplicate_writers = document.get("duplicate_writers")
    if not isinstance(duplicate_writers, list):
        errors.append("duplicate_writers must be a list, including an empty list when none exist")
    else:
        for index, writer in enumerate(duplicate_writers):
            if not (
                isinstance(writer, dict)
                and isinstance(writer.get("runtime"), str)
                and writer.get("runtime")
                and writer.get("disposition") in {"retired", "read_only", "adapter", "retained_independent"}
            ):
                errors.append(f"duplicate_writers.{index} needs a runtime and final non-writer disposition")
    approval = document.get("owner_approval")
    if not (
        isinstance(approval, dict)
        and approval.get("approved") is True
        and isinstance(approval.get("approved_by"), str)
        and approval.get("approved_by").strip()
        and isinstance(approval.get("authority_record_sha256"), str)
        and SHA256_HEX.fullmatch(approval.get("authority_record_sha256", ""))
    ):
        errors.append("owner_approval must bind explicit approval to an authority record SHA-256")
    adoption_hash = document.get("adoption_receipt_sha256")
    if not isinstance(adoption_hash, str) or not SHA256_HEX.fullmatch(adoption_hash):
        errors.append("adoption_receipt_sha256 must bind convergence to accepted use evidence")
    return errors


def _resolution_receipt_errors(path: Path, contract_id: str, claim: dict[str, Any]) -> list[str]:
    document, errors = _receipt_document(path, contract_id)
    if document is None:
        return errors
    outcome = document.get("outcome")
    if document.get("status") != "resolved" or outcome not in RECOVERY_RESOLUTION_OUTCOMES:
        errors.append("resolution receipt must have status 'resolved' and a supported outcome")
    if claim.get("outcome") and outcome != claim.get("outcome"):
        errors.append("resolution receipt outcome must match the manifest claim")
    for field in ("capability_id", "rationale"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            errors.append(f"resolution receipt {field} must be non-empty")
    if not _meaningful_fingerprint_collection(document.get("source_fingerprints")):
        errors.append("resolution receipt must retain meaningful source_fingerprints")
    if outcome in {"ported", "already_covered"}:
        digest = document.get("destination_evidence_sha256")
        if not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest):
            errors.append(f"{outcome} resolution requires destination_evidence_sha256")
    elif outcome == "retained_independent":
        if not isinstance(document.get("retained_owner"), str) or not document["retained_owner"].strip():
            errors.append("retained_independent resolution requires retained_owner")
    elif outcome == "deferred_with_trigger":
        trigger = document.get("resume_trigger")
        if not (
            isinstance(trigger, dict)
            and isinstance(trigger.get("condition"), str)
            and trigger.get("condition").strip()
        ):
            errors.append("deferred_with_trigger resolution requires a structured resume_trigger condition")
    return errors


def evidence_ineligibility_reason(wave: dict[str, Any]) -> str | None:
    """Why this wave may not write a receipt at all, or None when it may.

    A wave with no declared recovery claim has no contract to check a candidate against, so
    the recorder refuses rather than writing bytes nothing can later verify. That is a
    different outcome from "the gate failed" and from "the candidate was rejected", and
    callers must be able to tell the three apart.
    """
    claim = wave.get("recovery_claim") or {}
    kind = claim.get("kind")
    if not kind:
        return "wave declares no recovery evidence contract, so --record cannot write a verifiable receipt"
    if kind == "analysis":
        return None
    level = claim.get("level")
    contract = claim.get("receipt_contract")
    expected: set[str]
    if kind == "runtime" and level == "source_executed":
        expected = {"portfolio-runtime-source-v1"}
    elif kind == "runtime" and level == "parity_verified":
        expected = {"accessibility-wcag-331-v1", "portfolio-runtime-parity-v1"}
    elif kind in {"runtime", "adoption"} and level == "adopted":
        expected = {"portfolio-adoption-v1"}
    elif kind in {"runtime", "convergence"} and level == "converged":
        expected = {"portfolio-convergence-v1"}
    elif kind == "runtime":
        return _UNSUPPORTED_EVIDENCE_CONTRACT.format(what=f"runtime claim level {level!r}")
    elif kind in RECEIPT_CONTRACT_FOR_KIND:
        expected = {RECEIPT_CONTRACT_FOR_KIND[kind]}
    else:
        return _UNSUPPORTED_EVIDENCE_CONTRACT.format(what=f"{kind!r} claim at level {level!r}")
    if contract not in expected:
        return f"claim requires receipt_contract {', '.join(sorted(expected))}; got {contract!r}"
    return None


def evidence_errors(wave: dict[str, Any], path: Path, suite_id: str | None = None) -> list[str]:
    """Errors in a wave's evidence receipt, dispatched by claim kind.

    Shared by registry validation and the wave recorder, so a receipt that records
    successfully cannot then fail `suites validate`. The recorder is the stricter of the
    two: `validate` only inspects completed waves, while a wave with no declared claim
    can never record at all (see `evidence_ineligibility_reason`).

    Supported receipt contracts:
    - `analysis` is checked against its declared basis and `ANALYSIS_RECEIPT_SPECS`.
    - `runtime` supports `source_executed`, `parity_verified`, `adopted`, and `converged`
      through their corresponding versioned lifecycle validators. Those levels are runtime-
      only: an analysis receipt has no field that can prove a donor invocation, so an
      analysis claim is refused at them rather than validated leniently.
    - `adoption`, `convergence`, and `resolution` dispatch to their own receipt validators.
    Any other claim kind or runtime level is refused rather than waved through.
    """
    claim = wave.get("recovery_claim", {}) or {}
    kind = claim.get("kind")
    if not kind:
        return [evidence_ineligibility_reason(wave) or "wave has no declared recovery evidence contract"]
    ineligible = evidence_ineligibility_reason(wave)
    if ineligible:
        return [ineligible]
    if kind == "runtime":
        level = claim.get("level")
        contract_id = claim.get("receipt_contract", "")
        if level == "source_executed":
            return _portfolio_runtime_receipt_errors(path, contract_id, level)
        if level == "parity_verified":
            return _runtime_parity_receipt_errors(path, contract_id)
        if level == "adopted":
            return _adoption_receipt_errors(path, contract_id)
        if level == "converged":
            return _convergence_receipt_errors(path, contract_id)
        return [_UNSUPPORTED_EVIDENCE_CONTRACT.format(what=f"runtime claim level {level!r}")]
    if kind == "analysis":
        basis = {b for b in (claim.get("evidence_basis") or []) if isinstance(b, str) and b}
        if not basis:
            return ["analysis wave has empty or invalid evidence_basis"]
        errors = _analysis_evidence_errors(path, basis)
        if errors or path.suffix != ".json":
            return errors
        try:
            document = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return [f"analysis evidence cannot be loaded for semantic validation: {error}"]
        return _analysis_receipt_semantic_errors(wave, document, suite_id)
    contract_id = claim.get("receipt_contract", "")
    if kind == "adoption":
        return _adoption_receipt_errors(path, contract_id)
    if kind == "convergence":
        return _convergence_receipt_errors(path, contract_id)
    if kind == "resolution":
        return _resolution_receipt_errors(path, contract_id, claim)
    return [_UNSUPPORTED_EVIDENCE_CONTRACT.format(what=f"recovery claim kind {kind!r}")]
