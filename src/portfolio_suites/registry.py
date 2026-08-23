"""Load, inspect, and verify the suite registry, portfolio ledger, and live source tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import CONTRACTS, SCHEMA_VERSION, ContractError, validate_contract
from .paths import PROJECTS_ROOT, SUITES_ROOT, durable_write_text
from .provenance import is_meaningful_git_fingerprint

RECOVERY_STANDARD_PATH = SUITES_ROOT / "portfolio" / "recovery-standard.json"
SUITE_DIRS = (
    "accessibility", "operator-os", "brand-publishing", "production-house",
    "model-behavior-lab", "discovery-decision", "agent-reliability", "game-design",
)
RECOVERY_DIMENSIONS = {
    "functional_parity": 35,
    "repeated_real_use": 20,
    "runtime_convergence": 15,
    "reproducibility": 10,
    "failure_and_recovery": 10,
    "provenance_and_owner_control": 5,
    "reporting_accuracy": 5,
}
RECOVERY_PROMOTION_LEVELS = [
    "specified", "prototype", "source_verified", "parity_verified", "adopted", "converged",
]
RECOVERY_RESOLUTION_OUTCOMES = [
    "ported", "already_covered", "retained_independent", "rejected",
    "historical_only", "deferred_with_trigger",
]
RECOVERY_CLAIM_KINDS = ["analysis", "runtime", "adoption", "convergence", "resolution"]
# Promotion levels whose names assert that a real runtime was executed and compared.
# Reaching one requires runtime evidence, so a claim that declares no runtime cannot hold it.
RUNTIME_PROMOTION_LEVELS = frozenset({"parity_verified", "adopted", "converged"})
RECOVERY_ENFORCEMENT = {
    "completed_wave_requires_recovery_claim": True,
    "prototype_never_counts_as_recovered": True,
    "environment_blocker_is_neither_pass_nor_product_failure": True,
    "minimum_authentic_uses_for_adoption": 3,
    "minimum_consumers_for_shared_component": 2,
    "retirement_requires_owner_approval": True,
}
RECOVERY_TIERS = {
    "flagship": {
        "target_score": 9.0,
        "suites": ["accessibility", "operator-os", "brand-publishing"],
    },
    "production": {
        "target_score": 8.0,
        "suites": ["production-house", "discovery-decision"],
    },
    "lab": {
        "target_score": 7.0,
        "suites": ["model-behavior-lab", "agent-reliability", "game-design"],
    },
}
RUNTIME_PARITY_EVIDENCE = {
    "source_invocation",
    "destination_invocation",
    "representative_inputs",
    "output_parity",
    "failure_parity",
    "recovery_behavior",
    "source_fingerprints",
    "dependency_fingerprints",
    "reproducible_commands",
}
RECOVERY_RECEIPT_CONTRACTS = {"accessibility-wcag-331-v1"}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_suites() -> dict[str, dict[str, Any]]:
    suites: dict[str, dict[str, Any]] = {}
    for directory in SUITE_DIRS:
        manifest = _load_json(SUITES_ROOT / directory / "suite.json")
        suites[manifest["id"]] = manifest
    return suites


def get_suite(suite_id: str) -> dict[str, Any] | None:
    suites = load_suites()
    return suites.get(suite_id)


def load_ledger() -> dict[str, Any]:
    return _load_json(SUITES_ROOT / "portfolio" / "project-ledger.json")


def load_nested_ledger() -> dict[str, Any]:
    return _load_json(SUITES_ROOT / "portfolio" / "nested-repositories.json")


def load_recovery_standard() -> dict[str, Any]:
    """Load the authoritative portfolio recovery rubric and promotion policy."""
    return _load_json(RECOVERY_STANDARD_PATH)


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
        "equals": {"evidence_loss": False, "roundtrip_status": "verified"},
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
        "minimums": {"batch_size": 3, "observer_projections_count": 1},
        "fingerprints": ["pkos_fingerprint", "observer_fingerprint"],
    },
    "operator-os/O5": {
        "equals": {
            "wave_id": "O5",
            "status": "disposition_reconciled",
            "duplicate_decisions_closed": True,
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
            "reconciliation_status": "brand_workshop_intake_ported_to_brand_maker",
        },
        "lists": ["intake_log"],
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
        "equals": {"wave": "P1", "status": "fingerprinted", "all_stages_passed": True},
        "objects": ["job"],
        "fingerprints": [
            "production_house_fingerprint",
            "groundwire_fingerprint",
            "formatter_fingerprint",
        ],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P2": {
        "equals": {"wave": "P2", "status": "formatter_executed", "all_stages_passed": True},
        "objects": ["job"],
        "fingerprints": ["formatter_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P3": {
        "equals": {"wave": "P3", "status": "handoff_verified", "all_stages_passed": True},
        "objects": ["job"],
        "fingerprints": ["writers_room_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P4": {
        "equals": {
            "wave": "P4",
            "status": "documentary_pipeline_verified",
            "all_stages_passed": True,
        },
        "objects": ["job"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P5": {
        "equals": {"wave": "P5", "status": "event_stream_unified", "all_stages_passed": True},
        "objects": ["mapping", "mapping.mapped_job"],
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
            "status": "parity_verified",
            "all_stages_passed": True,
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
        "equals": {"wave": "D1", "status": "parity_mapped", "all_stages_passed": True},
        "objects": ["forge_budgets", "sif_run_sampled"],
        "lists": ["matrix", "sif_run_sampled.artifacts"],
        "fingerprints": ["sif_fingerprint", "forge_fingerprint"],
    },
    "discovery-decision/D2": {
        "equals": {"wave": "D2", "status": "stage_ported", "all_stages_passed": True},
        "objects": ["investigation", "donor_artifact", "budget_source"],
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
        "equals": {"wave": "D4", "status": "stage_ported", "all_stages_passed": True},
        "objects": ["investigation", "donor_artifact", "budget_source"],
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
            errors.append(f"job.{expected_collection} must retain executed job evidence")
        elif expected_exact is not None and len(collection) != expected_exact:
            errors.append(f"job.{expected_collection} must contain exactly {expected_exact} items")

    return errors


def _runtime_parity_receipt_errors(path: Path, contract_id: str) -> list[str]:
    """Validate a retained runtime receipt through an explicitly versioned contract."""
    if contract_id not in RECOVERY_RECEIPT_CONTRACTS:
        return [f"unsupported runtime parity receipt contract: {contract_id!r}"]
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


def evidence_ineligibility_reason(wave: dict[str, Any]) -> str | None:
    """Why this wave may not write a receipt at all, or None when it may.

    A wave with no declared recovery claim has no contract to check a candidate against, so
    the recorder refuses rather than writing bytes nothing can later verify. That is a
    different outcome from "the gate failed" and from "the candidate was rejected", and
    callers must be able to tell the three apart.
    """
    if not (wave.get("recovery_claim") or {}).get("kind"):
        return "wave declares no recovery evidence contract, so --record cannot write a verifiable receipt"
    return None


def evidence_errors(wave: dict[str, Any], path: Path, suite_id: str | None = None) -> list[str]:
    """Errors in a wave's evidence receipt, dispatched by claim kind.

    Shared by registry validation and the wave recorder, so a receipt that records
    successfully cannot then fail `suites validate`. The recorder is the stricter of the
    two: `validate` only inspects completed waves, while a wave with no declared claim
    can never record at all (see `evidence_ineligibility_reason`).

    Which claims have a receipt contract:
    - `analysis` is checked against its declared basis and `ANALYSIS_RECEIPT_SPECS`.
    - `runtime` at `parity_verified`, `adopted`, or `converged` is checked against a
      versioned parity receipt contract from `RECOVERY_RECEIPT_CONTRACTS`.
    - `adoption`, `convergence`, `resolution`, and `runtime` below `parity_verified` have
      no contract yet and are *refused*, not waved through. `RECOVERY_CLAIM_KINDS` says
      those kinds are declarable; this says their receipts are not yet verifiable. Writing
      the contract is what makes them recordable.
    """
    claim = wave.get("recovery_claim", {}) or {}
    kind = claim.get("kind")
    if not kind:
        return [evidence_ineligibility_reason(wave) or "wave has no declared recovery evidence contract"]
    if kind == "runtime":
        if claim.get("level") in RUNTIME_PROMOTION_LEVELS:
            return _runtime_parity_receipt_errors(path, claim.get("receipt_contract", ""))
        return [_UNSUPPORTED_EVIDENCE_CONTRACT.format(what=f"runtime claim at level {claim.get('level')!r}")]
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
    return [_UNSUPPORTED_EVIDENCE_CONTRACT.format(what=f"recovery claim kind {kind!r}")]


def get_project(name: str) -> dict[str, Any] | None:
    ledger = load_ledger()
    for row in ledger.get("projects", []):
        if row.get("name") == name:
            return row
    return None


def _git_value(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def check_project_git_drift(name: str, row: dict[str, Any]) -> dict[str, Any] | None:
    """Inspect live git state for a project row and return drift metrics if git-enabled."""
    source = PROJECTS_ROOT / name
    snapshot = row.get("source_snapshot")
    if not source.exists() or not snapshot or not snapshot.get("git"):
        return None

    current_head = _git_value(source, "rev-parse", "--short", "HEAD")
    current_branch = _git_value(source, "branch", "--show-current") or "DETACHED"
    current_status = _git_value(source, "status", "--porcelain")
    current_lines = len(current_status.splitlines()) if current_status else 0
    # A dirty-item count is blind to two files changing identity while the count holds.
    current_status_sha256 = hashlib.sha256(current_status.encode("utf-8")).hexdigest()

    # Porcelain output is "XY path" -- it carries no file content, so editing an
    # already-modified tracked file leaves it byte-identical. The patch is what closes
    # that hole.
    # ponytail: `git diff HEAD` covers tracked modifications only. Untracked file
    # *contents* stay unfingerprinted; hash them here if a donor ever parks real work
    # in untracked files.
    current_patch = _git_value(source, "diff", "HEAD")
    patch_readable = current_patch != "unavailable"
    current_patch_sha256 = (
        hashlib.sha256(current_patch.encode("utf-8")).hexdigest() if patch_readable else ""
    )

    snap_head = snapshot.get("head")
    snap_branch = snapshot.get("branch")
    snap_lines = snapshot.get("status_lines", 0)
    snap_status_sha256 = snapshot.get("status_sha256")
    snap_patch_sha256 = snapshot.get("patch_sha256")

    head_or_branch_drift = (current_head != snap_head) or (current_branch != snap_branch)
    lines_drift = (current_lines != snap_lines)
    content_drift = bool(snap_status_sha256) and current_status_sha256 != snap_status_sha256
    patch_drift = (
        bool(snap_patch_sha256) and patch_readable and current_patch_sha256 != snap_patch_sha256
    )
    has_drift = head_or_branch_drift or lines_drift or content_drift or patch_drift

    return {
        "name": name,
        "primary_suite": row.get("primary_suite"),
        "snapshot_head": snap_head,
        "current_head": current_head,
        "snapshot_branch": snap_branch,
        "current_branch": current_branch,
        "snapshot_lines": snap_lines,
        "current_lines": current_lines,
        "head_or_branch_drift": head_or_branch_drift,
        "lines_drift": lines_drift,
        "snapshot_status_sha256": snap_status_sha256,
        "current_status_sha256": current_status_sha256,
        "content_drift": content_drift,
        "status_unfingerprinted": not snap_status_sha256,
        "snapshot_patch_sha256": snap_patch_sha256,
        "current_patch_sha256": current_patch_sha256,
        "patch_drift": patch_drift,
        "patch_unfingerprinted": patch_readable and not snap_patch_sha256,
        "has_drift": has_drift,
    }


def get_live_drift_report() -> list[dict[str, Any]]:
    """Scan all ledger projects and report live git branch, HEAD, dirty state and drift."""
    ledger = load_ledger()
    drift_items = []
    for row in ledger.get("projects", []):
        name = row.get("name")
        item = check_project_git_drift(name, row)
        if item:
            drift_items.append(item)
    return drift_items


def get_portfolio_summary() -> dict[str, Any]:
    """Return consolidated high-level portfolio metrics and status."""
    suites = load_suites()
    ledger = load_ledger()
    nested = load_nested_ledger()
    standard = load_recovery_standard()
    projects = ledger.get("projects", [])

    total_projects = len(projects)
    suite_summaries = []
    total_waves = 0
    completed_waves = 0
    # A completed analysis wave has left its runtime work undone and named it in
    # `runtime_followup`. Counting those here is what keeps the aggregate from reading
    # 100% while nearly every wave still owes a live run: `next` already listed the debt
    # per wave, and the headline was the one place it went missing.
    waves_owing_runtime_followup = 0
    verified_analysis_milestones = 0
    recovered_runtime_behaviors = 0
    adopted_runtime_behaviors = 0
    converged_runtime_behaviors = 0

    for suite_id, manifest in suites.items():
        owned = [p for p in projects if p.get("primary_suite") == suite_id]
        waves = manifest.get("waves", [])
        total_waves += len(waves)
        completed_in_suite = sum(1 for w in waves if w.get("status") == "complete")
        completed_waves += completed_in_suite
        owing_in_suite = sum(
            1 for w in waves
            if w.get("status") == "complete" and str(w.get("runtime_followup") or "").strip()
        )
        waves_owing_runtime_followup += owing_in_suite
        for wave in waves:
            if wave.get("status") != "complete":
                continue
            claim = wave.get("recovery_claim", {})
            kind = claim.get("kind")
            level = claim.get("level")
            if kind == "analysis":
                verified_analysis_milestones += 1
            if kind == "runtime" and level in RUNTIME_PROMOTION_LEVELS:
                recovered_runtime_behaviors += 1
            if kind in {"runtime", "adoption"} and level in {"adopted", "converged"}:
                adopted_runtime_behaviors += 1
            if level == "converged":
                converged_runtime_behaviors += 1
        current_wave = next((w for w in waves if w.get("status") != "complete"), None)

        suite_summaries.append({
            "id": suite_id,
            "name": manifest.get("name"),
            "state": manifest.get("state"),
            "promise": manifest.get("promise"),
            "anchors": manifest.get("anchors", []),
            "contracts": manifest.get("contracts", []),
            "member_count": len(manifest.get("members", [])),
            "project_count": len(owned),
            "waves_total": len(waves),
            "waves_complete": completed_in_suite,
            "waves_owing_runtime_followup": owing_in_suite,
            "current_wave": current_wave.get("id") if current_wave else "complete",
            "completion_percentage": round((completed_in_suite / len(waves) * 100) if waves else 100, 1),
        })

    independent_count = sum(1 for p in projects if p.get("primary_suite") is None)
    nested_count = len(nested.get("repositories", []))

    return {
        "snapshot_at": ledger.get("snapshot_at"),
        "total_projects": total_projects,
        "independent_projects": independent_count,
        "nested_repositories": nested_count,
        "total_waves": total_waves,
        "completed_waves": completed_waves,
        "waves_owing_runtime_followup": waves_owing_runtime_followup,
        "portfolio_progress_pct": round((completed_waves / total_waves * 100) if total_waves else 0, 1),
        "recovery_standard_id": standard.get("standard_id"),
        "recovery_target_score": standard.get("target_score"),
        "verified_analysis_milestones": verified_analysis_milestones,
        "recovered_runtime_behaviors": recovered_runtime_behaviors,
        "adopted_runtime_behaviors": adopted_runtime_behaviors,
        "converged_runtime_behaviors": converged_runtime_behaviors,
        "suites": suite_summaries,
    }


def get_dependency_graph() -> dict[str, Any]:
    """Construct a dependency and relationship graph between suites, projects, and contracts."""
    suites = load_suites()
    ledger = load_ledger()
    nodes = []
    links = []

    # Suite nodes
    for s_id, s in suites.items():
        nodes.append({"id": f"suite:{s_id}", "label": s["name"], "type": "suite", "state": s["state"]})

    # Contract nodes
    for c_id in CONTRACTS:
        nodes.append({"id": f"contract:{c_id}", "label": c_id, "type": "contract"})

    # Connect suites to contracts
    for s_id, s in suites.items():
        for c in s.get("contracts", []):
            links.append({"source": f"suite:{s_id}", "target": f"contract:{c}", "relationship": "uses_contract"})

    # Project nodes and suite memberships
    for p in ledger.get("projects", []):
        p_name = p["name"]
        nodes.append({
            "id": f"project:{p_name}",
            "label": p_name,
            "type": "project",
            "disposition": p.get("disposition"),
            "suite": p.get("primary_suite"),
        })
        if p.get("primary_suite"):
            links.append({
                "source": f"suite:{p['primary_suite']}",
                "target": f"project:{p_name}",
                "relationship": "owns_project",
            })

    return {"nodes": nodes, "links": links}


def validate_registry(check_live: bool = True) -> ValidationReport:
    report = ValidationReport()
    try:
        suites = load_suites()
        ledger = load_ledger()
        nested = load_nested_ledger()
        standard = load_recovery_standard()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        report.errors.append(f"registry load failed: {error}")
        return report

    if len(suites) != len(SUITE_DIRS):
        report.errors.append("suite IDs are missing or duplicated")

    if standard.get("schema_version") != SCHEMA_VERSION:
        report.errors.append("recovery standard schema version is invalid")
    if standard.get("standard_id") != "portfolio-recovery-9":
        report.errors.append("recovery standard ID is invalid")
    if standard.get("target_score") != 9.0:
        report.errors.append("recovery target must remain 9.0/10 unless Ryan explicitly changes it")

    dimensions = standard.get("dimensions")
    actual_dimensions: dict[str, Any] = {}
    if not isinstance(dimensions, list):
        report.errors.append("recovery standard dimensions must be a list")
    else:
        for dimension in dimensions:
            if not isinstance(dimension, dict):
                report.errors.append("recovery standard dimensions must be objects")
                continue
            dimension_id = dimension.get("id")
            if not isinstance(dimension_id, str) or dimension_id in actual_dimensions:
                report.errors.append(f"recovery dimension ID is missing or duplicated: {dimension_id!r}")
                continue
            if not dimension.get("requirement"):
                report.errors.append(f"recovery dimension {dimension_id} needs a requirement")
            actual_dimensions[dimension_id] = dimension.get("weight")
        if actual_dimensions != RECOVERY_DIMENSIONS:
            report.errors.append("recovery standard dimensions or weights do not match the adopted rubric")

    promotion_levels = standard.get("promotion_levels", [])
    if promotion_levels != RECOVERY_PROMOTION_LEVELS:
        report.errors.append("recovery promotion levels are missing or out of order")
    if standard.get("resolution_outcomes") != RECOVERY_RESOLUTION_OUTCOMES:
        report.errors.append("recovery resolution outcomes do not match the adopted policy")
    if standard.get("claim_kinds") != RECOVERY_CLAIM_KINDS:
        report.errors.append("recovery claim kinds do not match the adopted policy")
    if standard.get("enforcement") != RECOVERY_ENFORCEMENT:
        report.errors.append("recovery enforcement rules do not match the fail-closed policy")

    tiers = standard.get("portfolio_tiers")
    actual_tiers: dict[str, dict[str, Any]] = {}
    if not isinstance(tiers, list):
        report.errors.append("recovery portfolio tiers must be a list")
    else:
        for tier in tiers:
            if not isinstance(tier, dict):
                report.errors.append("recovery portfolio tiers must be objects")
                continue
            tier_id = tier.get("id")
            if not isinstance(tier_id, str) or tier_id in actual_tiers:
                report.errors.append(f"recovery tier ID is missing or duplicated: {tier_id!r}")
                continue
            actual_tiers[tier_id] = {
                "target_score": tier.get("target_score"),
                "suites": tier.get("suites"),
            }
        if actual_tiers != RECOVERY_TIERS:
            report.errors.append("recovery tiers, targets, or suite assignments do not match policy")

    claim_kinds = set(RECOVERY_CLAIM_KINDS)
    project_rows = ledger.get("projects", [])
    if ledger.get("schema_version") != SCHEMA_VERSION or not isinstance(project_rows, list):
        report.errors.append("project ledger schema is invalid")
        return report

    projects: dict[str, dict[str, Any]] = {}
    for row in project_rows:
        name = row.get("name")
        if not name or name in projects:
            report.errors.append(f"duplicate or missing project name: {name!r}")
            continue
        projects[name] = row
        suite_id = row.get("primary_suite")
        if suite_id is not None and suite_id not in suites:
            report.errors.append(f"{name}: unknown primary suite {suite_id}")
        if not row.get("disposition") or not row.get("migration"):
            report.errors.append(f"{name}: disposition and migration are required")

    for suite_id, manifest in suites.items():
        if manifest.get("schema_version") != SCHEMA_VERSION:
            report.errors.append(f"{suite_id}: invalid schema version")
        if not manifest.get("promise") or not manifest.get("anchors"):
            report.errors.append(f"{suite_id}: promise and anchors are required")
        for contract in manifest.get("contracts", []):
            if contract not in CONTRACTS:
                report.errors.append(f"{suite_id}: unknown contract {contract}")
        member_names: set[str] = set()
        for member in manifest.get("members", []):
            project = member.get("project")
            if project in member_names:
                report.errors.append(f"{suite_id}: duplicate member {project}")
            member_names.add(project)
            if project not in projects:
                report.errors.append(f"{suite_id}: member missing from ledger: {project}")
        for anchor in manifest.get("anchors", []):
            if anchor not in member_names:
                report.errors.append(f"{suite_id}: anchor is not a member: {anchor}")
        if not manifest.get("completion_criteria") or not manifest.get("waves"):
            report.errors.append(f"{suite_id}: completion criteria and waves are required")
        for wave in manifest.get("waves", []):
            # Every declared claim is checked, at whatever level it claims. Only the
            # promotion rules below are reserved for waves that claim completion: a
            # prototype receipt that later goes malformed must still fail this gate.
            is_complete = wave.get("status") == "complete"
            claim = wave.get("recovery_claim")
            if not isinstance(claim, dict):
                if is_complete:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: completed wave requires recovery_claim")
                continue
            if claim.get("kind") not in claim_kinds:
                report.errors.append(f"{suite_id}/{wave.get('id')}: unknown recovery claim kind")
            claim_kind = claim.get("kind")
            claim_level = claim.get("level")
            if claim_level not in RECOVERY_PROMOTION_LEVELS:
                report.errors.append(f"{suite_id}/{wave.get('id')}: unknown recovery promotion level")
            elif is_complete and claim_level == "specified":
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed wave cannot claim a specified level")
            elif is_complete and claim_kind == "runtime" and claim_level == "prototype":
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed runtime wave cannot claim a prototype level")
            if not isinstance(claim.get("real_runtime"), bool):
                report.errors.append(f"{suite_id}/{wave.get('id')}: recovery claim must state real_runtime")
            if claim_kind == "runtime" and claim.get("real_runtime") is not True:
                report.errors.append(f"{suite_id}/{wave.get('id')}: runtime recovery must exercise a real runtime")
            if claim_kind == "analysis" and claim.get("real_runtime") is not False:
                report.errors.append(f"{suite_id}/{wave.get('id')}: analysis claim cannot manufacture runtime execution")
            # `parity_verified` and above are runtime rungs: their names assert that a donor
            # and a destination were both executed and compared. An analysis claim states in
            # the same breath that no runtime ran, so it may climb no higher than
            # `source_verified`. Only the runtime branch below carries evidence that can
            # substantiate the upper rungs, and nothing was applying it to analysis claims.
            if claim_kind == "analysis" and claim_level in RUNTIME_PROMOTION_LEVELS:
                report.errors.append(
                    f"{suite_id}/{wave.get('id')}: analysis claim cannot occupy the runtime "
                    f"promotion level {claim_level!r}; the highest analysis level is 'source_verified'"
                )
            # A completed analysis wave has, by definition, left its runtime work undone.
            # Without a written followup that work is not deferred, it is lost: the wave
            # reads as finished and nothing in the ledger remembers what it did not do.
            if is_complete and claim_kind == "analysis" and not str(wave.get("runtime_followup") or "").strip():
                report.errors.append(
                    f"{suite_id}/{wave.get('id')}: completed analysis wave must record the runtime work it deferred in runtime_followup"
                )

            evidence_basis = claim.get("evidence_basis")
            if (
                not isinstance(evidence_basis, list)
                or not evidence_basis
                or any(not isinstance(item, str) or not item for item in evidence_basis)
                or len(evidence_basis) != len(set(evidence_basis))
            ):
                report.errors.append(f"{suite_id}/{wave.get('id')}: recovery claim needs a unique string evidence basis")
                evidence_basis_set: set[str] = set()
            else:
                evidence_basis_set = set(evidence_basis)
            if claim_kind == "runtime" and claim_level in RUNTIME_PROMOTION_LEVELS:
                missing_basis = sorted(RUNTIME_PARITY_EVIDENCE - evidence_basis_set)
                if missing_basis:
                    report.errors.append(
                        f"{suite_id}/{wave.get('id')}: runtime parity evidence is missing {', '.join(missing_basis)}"
                    )
                if claim.get("receipt_contract") not in RECOVERY_RECEIPT_CONTRACTS:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: runtime parity receipt contract is missing or unsupported")
            if claim_level in {"adopted", "converged"}:
                authentic_uses = claim.get("authentic_uses")
                if not isinstance(authentic_uses, int) or authentic_uses < RECOVERY_ENFORCEMENT["minimum_authentic_uses_for_adoption"]:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: adoption requires at least three authentic uses")
            if claim_level == "converged" and claim.get("owner_approval") is not True:
                report.errors.append(f"{suite_id}/{wave.get('id')}: convergence requires explicit owner approval")
            if claim_kind == "resolution":
                outcome = claim.get("outcome")
                if outcome not in RECOVERY_RESOLUTION_OUTCOMES:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: resolution outcome is invalid")
                if outcome == "deferred_with_trigger" and not claim.get("resume_trigger"):
                    report.errors.append(f"{suite_id}/{wave.get('id')}: deferred resolution needs a resume trigger")
            evidence_path = wave.get("evidence")
            evidence_file = SUITES_ROOT / evidence_path if evidence_path else None
            if not evidence_file or not evidence_file.is_file():
                if is_complete:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: completed claim evidence is missing")
                else:
                    report.warnings.append(
                        f"{suite_id}/{wave.get('id')}: declared claim has no retained receipt at {evidence_path}"
                    )
            else:
                for evidence_error in evidence_errors(wave, evidence_file, suite_id):
                    report.errors.append(f"{suite_id}/{wave.get('id')}: {evidence_error}")

    if check_live:
        expected = set(projects)
        actual = {
            p.name
            for p in PROJECTS_ROOT.iterdir()
            if p.is_dir()
            and p.name != "suites"
            # Tool config, not portfolio projects. A leading dot at this level is never a
            # tracked capability (.claude, .venv, .idea), and treating one as an unreviewed
            # source turns an editor writing a settings file into a registry error.
            and not p.name.startswith(".")
        }
        for name in sorted(actual - expected):
            report.errors.append(f"unreviewed top-level directory: {name}")
        for name in sorted(expected - actual):
            report.errors.append(f"ledger source no longer exists: {name}")

        for name, row in projects.items():
            drift = check_project_git_drift(name, row)
            if not drift:
                continue
            if drift["head_or_branch_drift"]:
                report.warnings.append(
                    f"{name}: source fingerprint drifted from {drift['snapshot_branch']}@{drift['snapshot_head']} "
                    f"to {drift['current_branch']}@{drift['current_head']}"
                )
            if drift["lines_drift"]:
                report.warnings.append(
                    f"{name}: working-tree item count changed from {drift['snapshot_lines']} "
                    f"to {drift['current_lines']}"
                )

        nested_rows = nested.get("repositories", [])
        if nested.get("schema_version") != SCHEMA_VERSION or not isinstance(nested_rows, list):
            report.errors.append("nested repository ledger schema is invalid")
        else:
            expected_markers = {row["path"] for row in nested_rows}
            actual_markers: set[str] = set()
            for dirpath, dirnames, filenames in os.walk(PROJECTS_ROOT):
                marker_parent = Path(dirpath)
                try:
                    rel_parts = marker_parent.relative_to(PROJECTS_ROOT).parts
                except ValueError:
                    rel_parts = ()

                has_git = (".git" in dirnames) or (".git" in filenames)

                # Prune descendant traversal: bounded depth and excluded folders
                if len(rel_parts) >= 5:
                    dirnames[:] = []
                else:
                    dirnames[:] = [
                        d for d in dirnames
                        if d not in (".git", "node_modules", ".venv", "__pycache__", ".next", "dist", "build")
                    ]

                if has_git and marker_parent != SUITES_ROOT:
                    if 1 < len(rel_parts) <= 5:
                        actual_markers.add(str(marker_parent.relative_to(PROJECTS_ROOT)))
            for path in sorted(actual_markers - expected_markers):
                report.errors.append(f"unreviewed nested Git marker: {path}")
            for path in sorted(expected_markers - actual_markers):
                report.errors.append(f"nested Git marker no longer exists: {path}")

    return report


_LEDGER_PATH = SUITES_ROOT / "portfolio" / "project-ledger.json"
_SNAPSHOT_RE = re.compile(r'"source_snapshot":\{[^}]*\}')
_NAME_RE = re.compile(r'"name":"([^"]+)"')


def apply_snapshot_updates(text: str, snapshots: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    """Rewrite named rows' `source_snapshot` in place, preserving the file's formatting.

    Only rows named in `snapshots` are touched, and only where the new snapshot actually
    differs from what is on disk.
    """
    # ponytail: line-oriented rewrite because the ledger keeps one project per line and
    # source_snapshot holds no nested objects; switch to a JSON round-trip if either changes.
    updated: list[str] = []
    out = []
    for line in text.splitlines(keepends=True):
        name_match = _NAME_RE.search(line)
        name = name_match.group(1) if name_match else None
        snapshot = snapshots.get(name) if name else None
        if snapshot is None or not _SNAPSHOT_RE.search(line):
            out.append(line)
            continue
        rendered = '"source_snapshot":' + json.dumps(snapshot, separators=(",", ":"))
        new_line = _SNAPSHOT_RE.sub(lambda _m: rendered, line, count=1)
        if new_line != line:
            updated.append(name)
        out.append(new_line)
    return "".join(out), updated


def _live_snapshot(name: str, drift: dict[str, Any]) -> dict[str, Any] | None:
    """Build a baseline snapshot from a project's live git state, or None if git is unreadable."""
    if "unavailable" in {drift["current_head"], drift["current_branch"]}:
        return None
    return {
        "git": True,
        "branch": drift["current_branch"],
        "head": drift["current_head"],
        "status_lines": drift["current_lines"],
        "status_sha256": drift["current_status_sha256"],
        "patch_sha256": drift["current_patch_sha256"],
    }


def pending_snapshots(accept: bool = False) -> dict[str, dict[str, Any]]:
    """Snapshots to write: missing fingerprints always, full live state for drifted rows on accept.

    Without `accept` this only fills in an absent `status_sha256`, leaving the owner's
    recorded branch, HEAD, and dirty count alone. With `accept` a drifted row's whole
    baseline is replaced by live state — that is the owner blessing the drift, so the
    caller is expected to have asked for it explicitly.
    """
    rows = {row.get("name"): row for row in load_ledger().get("projects", [])}
    pending: dict[str, dict[str, Any]] = {}
    for drift in get_live_drift_report():
        name = drift["name"]
        snapshot = _live_snapshot(name, drift)
        if snapshot is None:
            continue
        if accept and drift["has_drift"]:
            pending[name] = snapshot
        elif drift["status_unfingerprinted"] or drift["patch_unfingerprinted"]:
            existing = rows[name].get("source_snapshot") or {}
            pending[name] = {
                **existing,
                "status_sha256": existing.get("status_sha256") or snapshot["status_sha256"],
                "patch_sha256": existing.get("patch_sha256") or snapshot["patch_sha256"],
            }
    return pending


def fingerprint_baselines(dry_run: bool = False, accept: bool = False) -> list[str]:
    """Record missing baseline fingerprints, and on `accept` re-capture drifted baselines."""
    text = _LEDGER_PATH.read_text(encoding="utf-8")
    new_text, updated = apply_snapshot_updates(text, pending_snapshots(accept))
    if updated and not dry_run:
        # The ledger is the single source of truth for all 70 dispositions and cannot be
        # rebuilt from the suites; it gets the same durable replace as the approval store.
        durable_write_text(_LEDGER_PATH, new_text)
    return updated
