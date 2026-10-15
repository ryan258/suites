"""Verification of retained wave evidence receipts against their declared recovery claims.

Dispatches by claim kind to versioned validators so a receipt that records successfully
cannot later fail registry validation, and a claim kind without an implemented contract
is refused rather than waved through.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
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
    "accessibility/A1": {
        "equals": {
            "wave_id": "A1",
            "review_kind": "source_only",
            "source_repository_modified": False,
            "donor_registered_rule_count": 34,
        },
        "objects": ["source_fingerprints", "rule_decision_counts", "retirement_gate"],
        "lists": [
            "rule_decisions",
            "crawl_and_sampling_decisions",
            "deliverable_and_workflow_decisions",
        ],
        "strings": ["projection_markdown"],
        "minimums": {"rule_decisions_count": 34},
    },
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
    # operator-os/O1 and O4 were here. They are runtime claims now, retaining a
    # portfolio-runtime-source-v1 receipt that proves the invocation, so they are validated by
    # _portfolio_runtime_receipt_errors and never reach an analysis spec.
    "brand-publishing/B1": {
        "equals": {"wave": "B1"},
        "strings": ["status"],
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
        "equals": {"wave": "B3"},
    },
    "brand-publishing/B4": {
        "equals": {"wave": "B4"},
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
        "equals": {"wave": "B6"},
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
    elif spec_key == "brand-publishing/B1":
        status = document.get("status")
        probe = document.get("probe")
        if status == "owner_approval_required":
            expected_blocker = {
                "blocker": "owner_approval_required",
                "all_stages_passed": False,
                "database_unchanged": True,
                "source_verification_passed": True,
                "probe.status": "no_published_version",
                "brand_package_emitted": False,
                "source_record_emitted": False,
                "publishing_receipt_emitted": False,
            }
            for dotted_path, expected in expected_blocker.items():
                actual = _receipt_value(document, dotted_path)
                if actual is _MISSING or actual != expected or type(actual) is not type(expected):
                    errors.append(f"{dotted_path} must equal {expected!r} for the B1 blocker receipt")
            if not isinstance(document.get("next_action"), str) or not document["next_action"].strip():
                errors.append("owner_approval_required B1 receipt must provide a next_action")
            if any(key in document for key in ("brand_package", "source_record", "publishing_receipt")):
                errors.append("B1 blocker receipt must not contain an emitted package, source, or publishing receipt")
        elif status == "verified_candidate":
            def require(condition: bool, message: str) -> None:
                if not condition:
                    errors.append(message)

            require(document.get("all_stages_passed") is True, "verified B1 export must retain all_stages_passed true")
            require(document.get("database_unchanged") is True, "verified B1 export must prove the donor database stayed unchanged")
            require(document.get("source_verification_passed") is True, "verified B1 export must retain source verification")
            require(isinstance(probe, dict) and probe.get("status") == "exported", "verified B1 export must retain an exported probe result")

            invocation = document.get("source_invocation")
            command = invocation.get("command") if isinstance(invocation, dict) else None
            require(
                isinstance(invocation, dict)
                and isinstance(command, list)
                and len(command) >= 2
                and all(isinstance(item, str) and item.strip() for item in command)
                and Path(command[1]).name == "donor_brand_package_probe.py"
                and invocation.get("exit_code") == 0
                and isinstance(invocation.get("duration_ms"), (int, float))
                and not isinstance(invocation.get("duration_ms"), bool)
                and invocation.get("duration_ms", -1) >= 0
                and invocation.get("environment_policy") == "donor_env_without_HOME_or_PYTHONPATH",
                "verified B1 export must retain a successful out-of-process Brand Maker probe invocation",
            )
            database_sha256 = document.get("database_sha256")
            require(
                isinstance(database_sha256, str) and SHA256_HEX.fullmatch(database_sha256) is not None,
                "verified B1 export must retain the unchanged database SHA-256",
            )
            target = document.get("target")
            consumer = document.get("consumer")
            require(
                isinstance(target, dict)
                and is_meaningful_git_fingerprint(target.get("fingerprint"))
                and target.get("has_developer_exports") is True
                and target.get("has_spec") is True
                and target.get("has_living_spec") is True,
                "verified B1 export must retain Brand Maker source fingerprints and inspected export/spec files",
            )
            require(
                isinstance(consumer, dict)
                and is_meaningful_git_fingerprint(consumer.get("fingerprint"))
                and consumer.get("has_manual") is True,
                "verified B1 export must retain the Cyborg consumer fingerprint and manual presence",
            )
            assertions = document.get("source_derived_assertions")
            asserted_functions = assertions.get("asserted_functions") if isinstance(assertions, dict) else None
            asserted_exports = assertions.get("asserted_exports") if isinstance(assertions, dict) else None
            require(
                isinstance(assertions, dict)
                and assertions.get("sensitivity_test_passed") is True
                and isinstance(asserted_functions, list)
                and "export_developer_package" in asserted_functions
                and isinstance(asserted_exports, list)
                and "change-manifest.json" in asserted_exports,
                "verified B1 export must retain the donor-derived export seam assertions",
            )

            brand_package = document.get("brand_package")
            source_record = document.get("source_record")
            package_valid = source_valid = False
            if not isinstance(brand_package, dict):
                errors.append("verified B1 export must retain a BrandPackage object")
            else:
                try:
                    validate_contract("BrandPackage", brand_package)
                    package_valid = True
                except (ContractError, TypeError, ValueError) as error:
                    errors.append(f"B1 brand_package violates BrandPackage: {error}")
            if not isinstance(source_record, dict):
                errors.append("verified B1 export must retain a SourceRecord object")
            else:
                try:
                    validate_contract("SourceRecord", source_record)
                    source_valid = True
                except (ContractError, TypeError, ValueError) as error:
                    errors.append(f"B1 source_record violates SourceRecord: {error}")

            published = probe.get("published_version") if isinstance(probe, dict) else None
            exports = probe.get("developer_export") if isinstance(probe, dict) else None
            module_fingerprints = probe.get("module_fingerprints") if isinstance(probe, dict) else None
            require(isinstance(published, dict), "verified B1 export must retain its published Brand Maker version")
            require(isinstance(exports, dict), "verified B1 export must retain the native developer exports")
            required_exports = {
                "tokens.css", "tokens.json", "rules.json", "patterns.json",
                "voice-context.json", "change-manifest.json",
            }
            if isinstance(exports, dict):
                require(
                    required_exports.issubset(exports)
                    and all(isinstance(exports.get(name), str) for name in required_exports),
                    "verified B1 export must retain every required native export as text",
                )
                export_sha256s = document.get("export_sha256s")
                require(
                    isinstance(export_sha256s, dict)
                    and set(export_sha256s) == set(exports)
                    and all(
                        isinstance(value, str)
                        and export_sha256s.get(name) == hashlib.sha256(value.encode("utf-8")).hexdigest()
                        for name, value in exports.items()
                    ),
                    "verified B1 export hashes must match every retained native export",
                )
            expected_modules = {
                "brand_maker.publishing.developer_exports": "src/brand_maker/publishing/developer_exports.py",
                "brand_maker.brand_system.models": "src/brand_maker/brand_system/models.py",
            }
            require(
                isinstance(module_fingerprints, dict)
                and set(module_fingerprints) == set(expected_modules)
                and all(
                    isinstance(module_fingerprints.get(name), dict)
                    and module_fingerprints[name].get("path") == path
                    and isinstance(module_fingerprints[name].get("sha256"), str)
                    and SHA256_HEX.fullmatch(module_fingerprints[name]["sha256"]) is not None
                    for name, path in expected_modules.items()
                ),
                "verified B1 export must retain the exact donor exporter/model module fingerprints",
            )

            if package_valid and source_valid and isinstance(published, dict):
                snapshot = published.get("snapshot")
                approvals = published.get("approvals")
                provenance = brand_package.get("provenance")
                source_content = document.get("source_content")
                published_hash = published.get("content_hash")
                require(isinstance(snapshot, dict), "published B1 version must retain its immutable snapshot")
                require(isinstance(approvals, list) and bool(approvals), "published B1 version must retain owner approvals")
                try:
                    snapshot_hash = hashlib.sha256(
                        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()
                    require(snapshot_hash == published_hash, "published B1 snapshot hash must reproduce the producer content hash")
                except (TypeError, ValueError):
                    errors.append("published B1 snapshot must be JSON-serializable for host-side hash verification")

                owner = snapshot.get("owner", {}) if isinstance(snapshot, dict) else {}
                owner = owner if isinstance(owner, dict) else {}
                revision = published.get("draft_revision")
                brand_id = published.get("brand_id")
                version = published.get("version")
                approval_ids: list[str] = []
                approval_times: list[datetime.datetime] = []
                if isinstance(approvals, list):
                    for index, approval in enumerate(approvals):
                        if not isinstance(approval, dict):
                            errors.append(f"published B1 approval {index} must be an object")
                            continue
                        approval_ids.append(str(approval.get("id", "")))
                        if not (
                            approval.get("brand_id") == brand_id
                            and approval.get("draft_revision") == revision
                            and approval.get("owner_id") == owner.get("id")
                            and approval.get("outcome") == "approved"
                            and isinstance(approval.get("id"), str)
                            and approval.get("id")
                        ):
                            errors.append(f"published B1 approval {index} must bind to the published owner and revision")
                        try:
                            approved_at = datetime.datetime.fromisoformat(
                                str(approval.get("approved_at", "")).replace("Z", "+00:00")
                            )
                            if approved_at.tzinfo is None or approved_at.utcoffset() is None:
                                raise ValueError("timezone required")
                            approval_times.append(approved_at)
                        except (TypeError, ValueError):
                            errors.append(f"published B1 approval {index} must retain a timezone-aware approved_at")

                require(
                    isinstance(snapshot, dict)
                    and snapshot.get("brand_id") == brand_id
                    and snapshot.get("revision") == revision
                    and snapshot.get("status") == "approved"
                    and snapshot.get("maturity") == "approved"
                    and isinstance(owner, dict)
                    and bool(owner.get("id"))
                    and bool(owner.get("display_name"))
                    and published.get("publisher_id") == owner.get("id"),
                    "published B1 version, snapshot, publisher, and owner must align",
                )
                section_ids = [
                    section.get("id") for section in snapshot.get("sections", [])
                    if isinstance(section, dict)
                ] if isinstance(snapshot, dict) and isinstance(snapshot.get("sections"), list) else []
                require(
                    isinstance(snapshot, dict) and isinstance(snapshot.get("sections"), list),
                    "published B1 snapshot must retain its section list",
                )
                published_manifest = published.get("manifest")
                require(
                    isinstance(published_manifest, dict)
                    and published_manifest.get("draft_revision") == revision
                    and published_manifest.get("section_ids") == section_ids,
                    "published B1 manifest must match the snapshot revision and section ids",
                )
                if (
                    isinstance(snapshot, dict)
                    and isinstance(exports, dict)
                    and required_exports.issubset(exports)
                    and all(isinstance(exports.get(name), str) for name in required_exports)
                ):
                    try:
                        token_export = json.loads(exports["tokens.json"])
                        rule_export = json.loads(exports["rules.json"])
                        pattern_export = json.loads(exports["patterns.json"])
                        voice_export = json.loads(exports["voice-context.json"])
                        change_manifest = json.loads(exports["change-manifest.json"])
                    except (TypeError, json.JSONDecodeError):
                        errors.append("B1 native JSON exports must remain parseable")
                    else:
                        if not all(
                            isinstance(artifact, dict)
                            for artifact in (token_export, rule_export, pattern_export, voice_export, change_manifest)
                        ):
                            errors.append("B1 native JSON exports must each contain an object")
                        token_export = token_export if isinstance(token_export, dict) else {}
                        rule_export = rule_export if isinstance(rule_export, dict) else {}
                        pattern_export = pattern_export if isinstance(pattern_export, dict) else {}
                        voice_export = voice_export if isinstance(voice_export, dict) else {}
                        change_manifest = change_manifest if isinstance(change_manifest, dict) else {}
                        sections = snapshot.get("sections", [])
                        sections = sections if isinstance(sections, list) else []
                        snapshot_assets = snapshot.get("assets", [])
                        if not isinstance(snapshot_assets, list):
                            errors.append("published B1 snapshot assets must be a list")
                            snapshot_assets = []
                        expected_section_values: dict[str, list[Any]] = {}
                        section_values_valid = True
                        for field in ("tokens", "rules", "patterns"):
                            values: list[Any] = []
                            for section in sections:
                                if not isinstance(section, dict):
                                    section_values_valid = False
                                    continue
                                items = section.get(field, [])
                                if not isinstance(items, list):
                                    section_values_valid = False
                                    continue
                                values.extend(items)
                            expected_section_values[field] = values
                        expected_tokens = [
                            *expected_section_values["tokens"]
                        ]
                        expected_rules = [
                            *expected_section_values["rules"]
                        ]
                        expected_patterns = [
                            *expected_section_values["patterns"]
                        ]
                        expected_voice_sections = [
                            section for section in sections
                            if isinstance(section, dict)
                            and section.get("id") in {"section.voice", "section.messaging", "section.strategy"}
                        ]
                        exported_rules = rule_export.get("rules", [])
                        if not isinstance(exported_rules, list):
                            errors.append("B1 native rules export must retain a rule list")
                            exported_rules = []
                        require(
                            section_values_valid
                            and token_export.get("tokens") == expected_tokens
                            and rule_export.get("rules") == expected_rules
                            and pattern_export.get("patterns") == expected_patterns
                            and voice_export.get("sections") == expected_voice_sections,
                            "B1 native token, rule, pattern, and voice exports must match the immutable snapshot",
                        )
                        for export_name, artifact in (
                            ("tokens.json", token_export),
                            ("rules.json", rule_export),
                            ("patterns.json", pattern_export),
                            ("voice-context.json", voice_export),
                            ("change-manifest.json", change_manifest),
                        ):
                            require(
                                artifact.get("version") == version
                                and artifact.get("content_hash") == published_hash,
                                f"B1 {export_name} must bind to the published version and content hash",
                            )
                        exported_approval_ids = change_manifest.get("approval_ids")
                        require(
                            published_hash in exports["tokens.css"]
                            and change_manifest.get("manifest") == published.get("manifest")
                            and isinstance(exported_approval_ids, list)
                            and all(isinstance(item, str) for item in exported_approval_ids)
                            and sorted(exported_approval_ids) == sorted(approval_ids),
                            "B1 CSS and change manifest must bind to the published hash, manifest, and approvals",
                        )
                        expected_usage_rules = [
                            rule["description"] for rule in exported_rules
                            if isinstance(rule, dict)
                            and isinstance(rule.get("description"), str)
                            and rule["description"].strip()
                        ]
                        expected_assets = [
                            {
                                "asset_id": asset["id"],
                                "name": asset["name"],
                                "kind": asset["media_type"],
                                "path": f"brand-maker://{brand_id}/assets/{asset['id']}",
                                "sha256": asset["content_hash"],
                                "storage": asset["storage"],
                            }
                            for asset in snapshot_assets
                            if isinstance(asset, dict)
                            and all(key in asset for key in ("id", "name", "media_type", "content_hash", "storage"))
                        ]
                        require(
                            brand_package.get("identity", {}).get("brand_name") == snapshot.get("brand_name")
                            and brand_package.get("identity", {}).get("brand_context") == snapshot.get("brand_context")
                            and brand_package.get("identity", {}).get("developer_tokens") == expected_tokens
                            and brand_package.get("voice", {}).get("sections") == expected_voice_sections
                            and brand_package.get("audience", {}).get("brief") == snapshot.get("brief", {})
                            and brand_package.get("assets") == expected_assets
                            and brand_package.get("usage_rules") == expected_usage_rules,
                            "B1 BrandPackage fields must be projected from the matching native exports and snapshot",
                        )
                require(
                    package_valid
                    and brand_package.get("brand_id") == brand_id
                    and brand_package.get("version") == version
                    and brand_package.get("package_id") == f"pkg-{str(brand_id).replace('-', '')}-{str(version).replace('.', '-')}"
                    and brand_package.get("approved_claims") == [],
                    "B1 BrandPackage must match the published identity and must not invent approved claims",
                )
                source_content_bytes = source_content.encode("utf-8") if isinstance(source_content, str) else b""
                require(
                    source_valid
                    and isinstance(source_content, str)
                    and source_record.get("sha256") == hashlib.sha256(source_content_bytes).hexdigest()
                    and source_record.get("size_bytes") == len(source_content_bytes)
                    and source_record.get("source_id") == f"src-brand-maker-{brand_id}-{version}"
                    and source_record.get("origin") == f"brand-maker-spec://{brand_id}/{version}/change-manifest.json"
                    and source_record.get("media_type") == "application/json"
                    and isinstance(source_record.get("provenance"), dict)
                    and source_record["provenance"].get("donor_repo") == "brand-maker-spec"
                    and source_record["provenance"].get("method") == "export_developer_package"
                    and source_record["provenance"].get("brand_version") == version
                    and source_record["provenance"].get("published_content_sha256") == published_hash,
                    "B1 SourceRecord must content-address the exact exported change manifest",
                )
                require(
                    isinstance(exports, dict)
                    and isinstance(source_content, str)
                    and exports.get("change-manifest.json") == source_content,
                    "B1 source content must be the exact native change-manifest export",
                )

                if (
                    isinstance(provenance, list)
                    and len(provenance) == 1
                    and isinstance(provenance[0], dict)
                    and isinstance(owner, dict)
                ):
                    origin = provenance[0]
                    origin_approval_ids = origin.get("approval_ids")
                    require(
                        origin.get("source") == "brand-maker-spec"
                        and origin.get("operator") == owner.get("display_name")
                        and origin.get("brand_version") == version
                        and origin.get("published_content_sha256") == published_hash
                        and isinstance(origin_approval_ids, list)
                        and all(isinstance(item, str) for item in origin_approval_ids)
                        and sorted(origin_approval_ids) == sorted(approval_ids)
                        and origin.get("derivation") == "native Brand Maker developer export from an immutable published version",
                        "B1 BrandPackage provenance must retain the real publisher, version, digest, and approval ids",
                    )
                    if approval_times:
                        approved_at = max(approval_times).astimezone(datetime.timezone.utc).isoformat()
                        require(
                            origin.get("timestamp") == approved_at
                            and brand_package.get("approved_at") == approved_at,
                            "B1 BrandPackage approval time must match the latest owner approval",
                        )
                else:
                    errors.append("B1 BrandPackage must retain one matching Brand Maker provenance record")

            receipt = document.get("publishing_receipt")
            require(isinstance(receipt, dict), "verified B1 export must retain a dry-run publishing receipt")
            if isinstance(receipt, dict) and package_valid and source_valid:
                try:
                    package_digest = hashlib.sha256(
                        json.dumps(
                            brand_package,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                            allow_nan=False,
                        ).encode("utf-8")
                    ).hexdigest()
                except (TypeError, ValueError):
                    errors.append("B1 BrandPackage must be JSON-serializable for publishing receipt verification")
                else:
                    require(
                        receipt.get("status") == "dry_run_verified"
                        and receipt.get("channel") == "brand-maker-developer-export"
                        and receipt.get("dry_run_only") is True
                        and receipt.get("live_published") is False
                        and receipt.get("human_review_required") is True
                        and receipt.get("brand_package_id") == brand_package.get("package_id")
                        and receipt.get("brand_version") == brand_package.get("version")
                        and receipt.get("brand_package_sha256") == package_digest
                        and receipt.get("source_id") == source_record.get("source_id")
                        and receipt.get("source_sha256") == source_record.get("sha256")
                        and receipt.get("matched_approved_claims_count") == 0
                        and receipt.get("matched_approved_claims") == []
                        and receipt.get("unmatched_approved_claims") == [],
                        "B1 publishing receipt must bind the validated package and source to a non-live dry run",
                    )

            mutation_tests = document.get("mutation_tests")
            expected_mutations = {
                "unmodified_identical": True,
                "mutated_identity_detected": False,
                "mutated_voice_detected": False,
                "mutated_provenance_detected": False,
            }
            observed_mutations = {
                item.get("case"): item
                for item in mutation_tests
                if isinstance(item, dict)
            } if isinstance(mutation_tests, list) else {}
            require(
                set(observed_mutations) == set(expected_mutations)
                and all(
                    observed_mutations[name].get("passed") is True
                    and bool(observed_mutations[name].get("violations")) is (not identical)
                    for name, identical in expected_mutations.items()
                )
                and document.get("mutation_protection_passed") is True,
                "verified B1 export must retain passing identical-package and three mutation-protection cases",
            )
        else:
            errors.append(f"B1 status {status!r} is not a supported retained receipt state")
    elif spec_key in {"brand-publishing/B3", "brand-publishing/B4", "brand-publishing/B6"}:
        def require(condition: bool, message: str) -> None:
            if not condition:
                errors.append(message)

        def require_text(value: Any, label: str) -> None:
            require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")

        def package_source_identity() -> tuple[Any, Any]:
            package_id = document.get("brand_package_id")
            source_id = document.get("source_id")
            require_text(package_id, "brand_package_id")
            require_text(source_id, "source_id")
            return package_id, source_id

        def validate_no_claims_blocker() -> None:
            package_id, source_id = package_source_identity()
            probe = document.get("upstream_probe")
            require(document.get("blocker") == "no_verified_approved_claims", "blocker must be no_verified_approved_claims")
            require(document.get("all_stages_passed") is False, "claims blocker must set all_stages_passed false")
            require(document.get("brand_package_approved_claims_count") == 0, "claims blocker must prove the exported package has zero approved claims")
            require_text(document.get("next_action"), "next_action")
            require(
                isinstance(probe, dict)
                and probe.get("status") == "verified_candidate"
                and probe.get("brand_package_id") == package_id
                and probe.get("source_id") == source_id
                and probe.get("brand_package_approved_claims_count") == 0,
                "claims blocker upstream_probe must bind the verified package, source, and empty claims list",
            )
            require(
                not any(key in document for key in ("publishing_receipt", "approved_review", "matched_approved_claims")),
                "claims blocker must not imply a publishing or review decision was attempted",
            )

        status = document.get("status")
        blocker = document.get("blocker")
        if status == "blocked":
            require(document.get("all_stages_passed") is False, "blocked brand publishing receipt must set all_stages_passed false")
            require_text(document.get("next_action"), "blocked brand publishing next_action")
            probe = document.get("upstream_probe")
            require(isinstance(probe, dict) and bool(probe), "blocked brand publishing receipt must retain an upstream_probe")
            if blocker == "brand_package_unavailable":
                require_text(probe.get("status"), "upstream_probe.status")
            elif blocker == "no_verified_approved_claims" and spec_key in {"brand-publishing/B3", "brand-publishing/B6"}:
                validate_no_claims_blocker()
            elif blocker == "no_approved_claim_match" and spec_key == "brand-publishing/B3":
                package_id, source_id = package_source_identity()
                receipt = document.get("publishing_receipt")
                require(isinstance(receipt, dict), "no-match B3 receipt must retain the dry-run publishing receipt")
                if isinstance(receipt, dict):
                    require(
                        receipt.get("brand_package_id") == package_id
                        and receipt.get("source_id") == source_id
                        and receipt.get("status") == "dry_run_verified"
                        and receipt.get("matched_approved_claims_count") == 0
                        and receipt.get("matched_approved_claims") == []
                        and receipt.get("dry_run_only") is True
                        and receipt.get("live_published") is False,
                        "no-match B3 receipt must bind a zero-match dry run that stopped before publication",
                    )
            else:
                errors.append(f"{spec_key} has an unsupported blocker {blocker!r}")
        elif spec_key == "brand-publishing/B3" and status == "dry_run_verified":
            package_id, source_id = package_source_identity()
            receipt = document.get("publishing_receipt")
            package_sha256 = document.get("brand_package_sha256")
            source_sha256 = document.get("source_sha256")
            require(isinstance(package_sha256, str) and SHA256_HEX.fullmatch(package_sha256) is not None, "B3 must retain the BrandPackage SHA-256")
            require(isinstance(source_sha256, str) and SHA256_HEX.fullmatch(source_sha256) is not None, "B3 must retain the SourceRecord SHA-256")
            require_text(document.get("brand_version"), "brand_version")
            require(document.get("all_stages_passed") is True, "verified B3 receipt must set all_stages_passed true")
            require(isinstance(receipt, dict), "B3 must retain its publishing receipt")
            if isinstance(receipt, dict):
                matched = receipt.get("matched_approved_claims")
                require(
                    receipt.get("status") == "dry_run_verified"
                    and receipt.get("channel") == "cyborg-vcc"
                    and receipt.get("brand_package_id") == package_id
                    and receipt.get("brand_version") == document.get("brand_version")
                    and receipt.get("brand_package_sha256") == package_sha256
                    and receipt.get("source_id") == source_id
                    and receipt.get("source_sha256") == source_sha256
                    and isinstance(matched, list)
                    and bool(matched)
                    and all(isinstance(item, str) and item.strip() for item in matched)
                    and receipt.get("matched_approved_claims_count") == len(matched)
                    and receipt.get("dry_run_only") is True
                    and receipt.get("live_published") is False
                    and receipt.get("human_review_required") is True,
                    "B3 dry-run receipt must bind a matched approved claim to the same package and source without live publication",
                )
        elif spec_key == "brand-publishing/B4" and status == "verified":
            package_id = document.get("brand_package_id")
            brand_version = document.get("brand_version")
            package_sha256 = document.get("brand_package_sha256")
            require_text(package_id, "brand_package_id")
            require_text(brand_version, "brand_version")
            require(isinstance(package_sha256, str) and SHA256_HEX.fullmatch(package_sha256) is not None, "B4 must retain the BrandPackage SHA-256")
            require(document.get("all_stages_passed") is True, "verified B4 receipt must set all_stages_passed true")
            consumers = [document.get("consumer_1"), document.get("consumer_2")]
            if not all(isinstance(consumer, dict) and bool(consumer) for consumer in consumers):
                errors.append("B4 must retain both consumer verification objects")
            else:
                for index, consumer in enumerate(consumers, start=1):
                    require(
                        consumer.get("status") == "verified"
                        and consumer.get("package_id") == package_id
                        and consumer.get("package_version") == brand_version
                        and consumer.get("pinned_version") == brand_version
                        and consumer.get("version_match") is True
                        and consumer.get("read_only_intent") is True
                        and consumer.get("digest_match") is True
                        and consumer.get("mutation_shield_active") is True
                        and consumer.get("package_sha256") == package_sha256
                        and consumer.get("expected_package_sha256") == package_sha256,
                        f"B4 consumer_{index} must verify the same pinned package digest read-only",
                    )
                require(
                    consumers[0].get("consumer_name") != consumers[1].get("consumer_name"),
                    "B4 must verify two independently named consumers",
                )
        elif spec_key == "brand-publishing/B6" and status == "simulated_gate_verified":
            package_id, source_id = package_source_identity()
            brand_version = document.get("brand_version")
            package_sha256 = document.get("brand_package_sha256")
            source_sha256 = document.get("source_sha256")
            require_text(brand_version, "brand_version")
            require(isinstance(package_sha256, str) and SHA256_HEX.fullmatch(package_sha256) is not None, "B6 must retain the BrandPackage SHA-256")
            require(isinstance(source_sha256, str) and SHA256_HEX.fullmatch(source_sha256) is not None, "B6 must retain the SourceRecord SHA-256")
            require(document.get("all_stages_passed") is True, "verified B6 receipt must set all_stages_passed true")
            approved = document.get("approved_review")
            require(isinstance(approved, dict) and bool(approved), "B6 must retain the simulated approved review branch")
            if isinstance(approved, dict):
                gate = approved.get("simulated_gate")
                dry_run = approved.get("dry_run_receipt")
                require(
                    approved.get("status") == "simulated_review_passed"
                    and approved.get("brand_package_id") == package_id
                    and approved.get("source_id") == source_id
                    and isinstance(gate, dict)
                    and gate.get("decision") == "approved"
                    and gate.get("decision_source") == "simulated_fixture"
                    and gate.get("human_confirmation_claimed") is False
                    and gate.get("boundary_check") == "stopped_before_live_publish",
                    "B6 approved branch must remain a fixture simulation and stop before live publication",
                )
                require(
                    isinstance(dry_run, dict)
                    and dry_run.get("status") == "dry_run_verified"
                    and dry_run.get("channel") == "vcc-focus-group"
                    and dry_run.get("brand_package_id") == package_id
                    and dry_run.get("brand_version") == brand_version
                    and dry_run.get("brand_package_sha256") == package_sha256
                    and dry_run.get("source_id") == source_id
                    and dry_run.get("source_sha256") == source_sha256
                    and dry_run.get("dry_run_only") is True
                    and dry_run.get("live_published") is False
                    and dry_run.get("human_review_required") is True
                    and isinstance(dry_run.get("matched_approved_claims"), list)
                    and bool(dry_run.get("matched_approved_claims")),
                    "B6 approved branch must bind a matched-claims dry run without publishing",
                )
            require(document.get("rejected_probe_status") == "simulated_blocked_rejected", "B6 must retain the rejected-decision branch")
            require(document.get("unmatched_probe_status") == "simulated_blocked_unmatched_claims", "B6 must retain the unmatched-claims branch")
        else:
            errors.append(f"{spec_key} has an unsupported status {status!r}")
    elif spec_key == "brand-publishing/B2":
        if len(document.get("phase_mappings", [])) != 9:
            errors.append("B2 must retain exactly nine phase mappings")
    elif spec_key == "brand-publishing/B5":
        if len(document.get("intake_log", [])) != 9:
            errors.append("B5 must retain exactly nine intake phases")
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


def _agreeing_module_fingerprints(value: Any) -> bool:
    """Whether every invoked module carries a host digest that reproduced the donor's.

    A digest the donor both computes and attests is self-attestation, so the receipt has to
    retain the host's own recomputation alongside it and the two have to agree. A receipt
    naming no module at all fails here: `source_executed` asserts specific code ran.
    """
    if not isinstance(value, dict) or not value:
        return False
    for module_name, record in value.items():
        if not isinstance(module_name, str) or not module_name.strip():
            return False
        if not isinstance(record, dict):
            return False
        raw_path = record.get("path")
        if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
            return False
        path_parts = raw_path.split("/")
        path = PurePosixPath(raw_path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path_parts):
            return False
        host = record.get("host_recomputed_sha256")
        if not isinstance(host, str) or not SHA256_HEX.fullmatch(host):
            return False
        if record.get("agrees") is not True or host != record.get("donor_attested_sha256"):
            return False
    return True


def _portfolio_runtime_receipt_errors(path: Path, contract_id: str, level: str) -> list[str]:
    document, errors = _receipt_document(path, contract_id)
    if document is None:
        return errors
    expected_status = "source_executed" if level == "source_executed" else "parity_verified"
    if document.get("status") != expected_status or document.get("all_stages_passed") is not True:
        errors.append(f"runtime receipt must retain status {expected_status!r} and all_stages_passed true")
    if document.get("source_invocation_status") != "invoked":
        errors.append("source_invocation_status must be 'invoked' for a promotional runtime receipt")
    source = document.get("source_invocation")
    if not (
        isinstance(source, dict)
        and isinstance(source.get("command"), list)
        and source.get("command")
        and all(isinstance(item, str) and item.strip() for item in source["command"])
        and source.get("exit_code") == 0
    ):
        errors.append("source_invocation must retain an argv command and zero exit code")
    duration = source.get("duration_ms") if isinstance(source, dict) else None
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
        errors.append("source_invocation must retain a non-negative duration_ms")
    if not _agreeing_module_fingerprints(document.get("module_fingerprints")):
        errors.append(
            "module_fingerprints must record a host-recomputed SHA-256 per invoked donor "
            "module that agrees with the donor's own digest"
        )
    tools = document.get("tool_dependencies")
    required_tool_roles = {"host_python", "donor_python"}
    if (
        not isinstance(tools, dict)
        or not required_tool_roles.issubset(tools)
        or any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(item, str)
            or not item.strip()
            for name, item in tools.items()
        )
        or any(
            name.endswith("_sha256") and not SHA256_HEX.fullmatch(item)
            for name, item in tools.items()
        )
    ):
        errors.append(
            "tool_dependencies must pin host_python, donor_python, and valid tool fingerprints"
        )
    if not _meaningful_fingerprint_collection(document.get("source_fingerprints")):
        errors.append("source_fingerprints must contain meaningful Git and content fingerprints")
    if not _meaningful_fingerprint_collection(document.get("dependency_fingerprints")):
        errors.append("dependency_fingerprints must contain meaningful Git and content fingerprints")
    commands = document.get("reproducible_commands")
    if (
        not isinstance(commands, list)
        or not commands
        or any(
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item.strip() for item in command)
            for command in commands
        )
    ):
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
    if not isinstance(kind, str) or not kind:
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
        if path.suffix != ".json":
            return [
                "analysis evidence must be a .json receipt; a prose receipt reaches no "
                "ANALYSIS_RECEIPT_SPECS entry, so its declared basis is checked as bare "
                "substrings and nothing verifies what those sections say"
            ]
        errors = _analysis_evidence_errors(path, basis)
        if errors:
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
