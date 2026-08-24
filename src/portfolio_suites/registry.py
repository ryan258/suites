"""Load, inspect, and verify the suite registry, portfolio ledger, and live source tree."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import datetime
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .contracts import CONTRACTS, SCHEMA_VERSION, ContractError, validate_contract
from .adapters.common import run_donor_git
from .paths import (
    PROJECTS_ROOT,
    SUITES_ROOT,
    CommitUnverified,
    open_confined_directory,
)
from .provenance import is_meaningful_git_fingerprint, is_sensitive_path
from .txn import CommitUncertain, OccupantConflict, commit_replacement, write_temp_payload

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
# Retired `source_verified`: one name covered historical review, source inspection, and execution.
RECOVERY_PROMOTION_LEVELS = [
    "specified",
    "prototype",
    "reviewed_historical_analysis",
    "source_inspected",
    "source_executed",
    "parity_verified",
    "adopted",
    "converged",
]
# Levels at which a claim asserts that donor code actually ran. `source_executed` invokes the
# donor; `parity_verified` and above additionally compare it against the destination.
EXECUTED_PROMOTION_LEVELS = frozenset({"source_executed", "parity_verified", "adopted", "converged"})
RECOVERY_RESOLUTION_OUTCOMES = [
    "ported", "already_covered", "retained_independent", "rejected",
    "historical_only", "deferred_with_trigger",
]
RECOVERY_CLAIM_KINDS = ["analysis", "runtime", "adoption", "convergence", "resolution"]
# Promotion levels whose names assert that a real runtime was executed and compared.
# Reaching one requires runtime evidence, so a claim that declares no runtime cannot hold it.
RUNTIME_PROMOTION_LEVELS = frozenset({"parity_verified", "adopted", "converged"})
# Which claim kinds may occupy an executed promotion level at all. `runtime` earns the whole
# ladder by retaining a receipt that proves the invocation; `adoption` and `convergence` are
# the terminal rungs their own contracts describe. Every other kind -- `analysis` and
# `resolution` -- is validated against a receipt specification that describes what a receipt
# *contains*, which can never establish an argv, an exit status, or a donor fingerprint.
EXECUTED_LEVELS_BY_KIND = {
    "runtime": EXECUTED_PROMOTION_LEVELS,
    "adoption": frozenset({"adopted"}),
    "convergence": frozenset({"converged"}),
}
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
RECOVERY_RECEIPT_CONTRACTS = {
    "accessibility-wcag-331-v1",
    "portfolio-runtime-source-v1",
    "portfolio-runtime-parity-v1",
    "portfolio-adoption-v1",
    "portfolio-convergence-v1",
    "portfolio-resolution-v1",
}
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_CONTRACT_FOR_KIND = {
    "adoption": "portfolio-adoption-v1",
    "convergence": "portfolio-convergence-v1",
    "resolution": "portfolio-resolution-v1",
}


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


def resolve_declared_evidence_path(rel_path: Any, suite_id: str | None = None) -> Path | None:
    """Resolve the canonical ``<suite>/evidence/<file>`` shape inside the suites tree.

    Manifest content is untrusted control data. This helper performs no filesystem writes and
    fails closed on absolute paths, traversal, backslash ambiguity, unexpected nesting, suite
    mismatch, or a symlink that resolves outside ``SUITES_ROOT``.
    """
    if not isinstance(rel_path, str) or not rel_path or "\\" in rel_path or "\x00" in rel_path:
        return None
    pure = PurePosixPath(rel_path)
    parts = pure.parts
    if (
        pure.is_absolute()
        or len(parts) != 3
        or parts[0] not in SUITE_DIRS
        or (suite_id is not None and parts[0] != suite_id)
        or parts[1] != "evidence"
        or parts[2] in {"", ".", ".."}
        or ".." in parts
    ):
        return None
    candidate = SUITES_ROOT.joinpath(*parts)
    try:
        resolved_root = SUITES_ROOT.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(resolved_root)
        expected_parent = (SUITES_ROOT / parts[0] / "evidence").resolve(strict=False)
        if resolved.parent != expected_parent:
            return None
    except (OSError, ValueError, RuntimeError):
        return None
    return candidate


def declared_evidence_owner(target: Path) -> tuple[str, dict[str, Any]] | None:
    """Return the unique manifest owner for an exact evidence file, if one exists."""
    try:
        resolved_target = target.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    matches: list[tuple[str, dict[str, Any]]] = []
    for suite_id, manifest in load_suites().items():
        for wave in manifest.get("waves", []):
            candidate = resolve_declared_evidence_path(wave.get("evidence"), suite_id)
            if candidate is not None and candidate.resolve(strict=False) == resolved_target:
                matches.append((suite_id, wave))
    return matches[0] if len(matches) == 1 else None


def build_evidence_ownership_index(
    suites: dict[str, dict[str, Any]],
) -> dict[Path, list[tuple[str, dict[str, Any]]]]:
    index: dict[Path, list[tuple[str, dict[str, Any]]]] = {}
    for owner_suite_id, manifest in suites.items():
        for owner_wave in manifest.get("waves", []):
            candidate = resolve_declared_evidence_path(owner_wave.get("evidence"), owner_suite_id)
            if candidate is not None:
                index.setdefault(candidate.resolve(strict=False), []).append((owner_suite_id, owner_wave))
    return index


def get_wave_evidence_status(
    suite_id: str,
    wave: dict[str, Any],
    ownership_index: dict[Path, list[tuple[str, dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    """Evidence-backed status for a manifest wave without executing its runtime."""
    candidate = resolve_declared_evidence_path(wave.get("evidence"), suite_id)
    if candidate is None:
        errors = ["declared evidence path is invalid or outside the canonical suite evidence directory"]
    elif not candidate.is_file():
        errors = ["declared evidence file is missing"]
    else:
        if ownership_index is None:
            owner = declared_evidence_owner(candidate)
        else:
            owners = ownership_index.get(candidate.resolve(strict=False), [])
            owner = owners[0] if len(owners) == 1 else None
        if owner is None or owner[0] != suite_id or owner[1].get("id") != wave.get("id"):
            errors = ["declared evidence path does not have one canonical suite/wave owner"]
        else:
            errors = evidence_errors(wave, candidate, suite_id)
    return {
        "evidence_path": str(candidate) if candidate is not None and candidate.is_file() else None,
        "evidence_valid": not errors,
        "evidence_errors": errors,
    }


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
        "minimums": {"batch_size": 3, "observer_projections_count": 1},
        "fingerprints": ["pkos_fingerprint", "observer_fingerprint"],
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
            "donor_read": False,
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
            "reconciliation_status": "suite_local_intake_phases_validated",
            "brand_workshop_read": False,
            "external_runtime_invoked": False,
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
        "equals": {
            "wave": "P1",
            "status": "source_fingerprints_with_fixture_projection_verified",
            "episode_artifacts_read": False,
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job"],
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
            "status": "fixture_output_projection_verified",
            "external_formatter_invoked": False,
            "fixture_output_only": True,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job"],
        "fingerprints": ["formatter_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P3": {
        "equals": {
            "wave": "P3",
            "status": "fixture_handoff_projection_verified",
            "writers_room_runtime_invoked": False,
            "signoff_observed": False,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job"],
        "fingerprints": ["writers_room_fingerprint"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P4": {
        "equals": {
            "wave": "P4",
            "status": "documentary_fixture_model_verified",
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "job.external_runtime_invoked": False,
            "all_stages_passed": True,
        },
        "objects": ["job"],
        "contracts": {"job": "ProductionJob"},
    },
    "production-house/P5": {
        "equals": {
            "wave": "P5",
            "status": "fixture_event_projection_verified",
            "writers_room_runtime_invoked": False,
            "runtime_consolidation_performed": False,
            "mapping.writers_room_runtime_invoked": False,
            "mapping.signoff_observed": False,
            "mapping.runtime_consolidation": "not_performed",
            "all_stages_passed": True,
        },
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


def get_project(name: str) -> dict[str, Any] | None:
    ledger = load_ledger()
    for row in ledger.get("projects", []):
        if row.get("name") == name:
            return row
    return None


def _git_value(path: Path, *args: str) -> str:
    """Read one value from a donor repository through the hardened donor Git runner.

    Every registry Git invocation goes through
    :func:`portfolio_suites.adapters.common.run_donor_git`; calling ``subprocess`` directly
    here would bypass both the minimal environment and the local-config neutralization, and
    a read-only drift command would execute repository-local code with this process's
    authority behind it.
    """
    try:
        result = run_donor_git(path, *args, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _git_untracked_paths(source: Path) -> tuple[list[str], bool]:
    """Return NUL-delimited untracked paths plus whether Git enumerated them successfully."""
    try:
        result = run_donor_git(
            source,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
            timeout=5,
            binary=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], False
    if result.returncode != 0:
        return [], False
    raw = result.stdout
    entries = raw.split(b"\x00")
    untracked = []
    for entry in entries:
        if entry.startswith(b"?? "):
            rel_name = entry[3:].decode("utf-8", errors="replace")
            if rel_name:
                untracked.append(rel_name)
    return untracked, True


def _untracked_content_digest(source: Path, untracked_paths: list[str]) -> tuple[str, bool]:
    """Stream-hash non-sensitive untracked entries without following symlinks.

    Returns (digest, is_incomplete).
    """
    if not untracked_paths:
        return "", False

    file_hashes: list[str] = []
    max_files = 1000
    max_stream_bytes = 100 * 1024 * 1024  # 100MB per file streaming budget
    total_bytes_streamed = 0
    max_total_bytes = 500 * 1024 * 1024  # 500MB total streaming budget
    is_incomplete = False

    processed_entries = 0
    truncated = False
    # Not reading a secret into evidence is correct. Reporting the result as a *complete*
    # fingerprint is not: the bytes of a sensitive untracked file can change with the
    # pathname and status shape held constant, and nothing here would notice. The count is
    # recorded so the digest still moves when the set changes; neither name nor content is.
    sensitive_skipped = 0

    def fingerprint_entry(file_path: Path, rel_file: str) -> bool:
        """Fingerprint one non-directory entry; false means the cap refused this entry."""
        nonlocal processed_entries, total_bytes_streamed, is_incomplete, truncated
        nonlocal sensitive_skipped

        if is_sensitive_path(rel_file):
            sensitive_skipped += 1
            is_incomplete = True
            return True
        if processed_entries >= max_files:
            if not truncated:
                file_hashes.append("::MAX_UNTRACKED_FILES_TRUNCATION::")
                truncated = True
            is_incomplete = True
            return False
        processed_entries += 1

        try:
            initial = file_path.lstat()
        except OSError:
            is_incomplete = True
            file_hashes.append(f"{rel_file}:UNREADABLE_ENTRY_INCOMPLETE")
            return True

        if stat.S_ISLNK(initial.st_mode):
            try:
                target = os.readlink(file_path)
                target_digest = hashlib.sha256(os.fsencode(target)).hexdigest()
                current = file_path.lstat()
                if (current.st_dev, current.st_ino, current.st_mtime_ns) != (
                    initial.st_dev,
                    initial.st_ino,
                    initial.st_mtime_ns,
                ):
                    raise OSError("symlink changed while it was fingerprinted")
                file_hashes.append(f"{rel_file}:SYMLINK:{target_digest}")
            except OSError:
                is_incomplete = True
                file_hashes.append(f"{rel_file}:UNREADABLE_SYMLINK_INCOMPLETE")
            return True

        if not stat.S_ISREG(initial.st_mode):
            is_incomplete = True
            file_hashes.append(
                f"{rel_file}:UNSUPPORTED_ENTRY_INCOMPLETE:mode={stat.S_IFMT(initial.st_mode):o}"
            )
            return True

        file_size = initial.st_size
        if file_size > max_stream_bytes or (total_bytes_streamed + file_size) > max_total_bytes:
            is_incomplete = True
            file_hashes.append(
                f"{rel_file}:LARGE_FILE_INCOMPLETE:size={file_size}:mtime={initial.st_mtime_ns}"
            )
            return True

        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
            file_fd = os.open(file_path, flags)
            try:
                opened = os.fstat(file_fd)
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                    initial.st_dev,
                    initial.st_ino,
                ):
                    raise OSError("entry changed before it was opened")
                hasher = hashlib.sha256()
                with os.fdopen(file_fd, "rb") as stream:
                    file_fd = -1
                    while chunk := stream.read(65536):
                        hasher.update(chunk)
                        total_bytes_streamed += len(chunk)
                current = file_path.lstat()
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                    initial.st_dev,
                    initial.st_ino,
                    initial.st_size,
                    initial.st_mtime_ns,
                ):
                    raise OSError("file changed while it was fingerprinted")
                file_hashes.append(f"{rel_file}:{hasher.hexdigest()}")
            finally:
                if file_fd >= 0:
                    os.close(file_fd)
        except OSError:
            is_incomplete = True
            file_hashes.append(f"{rel_file}:UNREADABLE_FILE_INCOMPLETE")
        return True

    for candidate in sorted(set(untracked_paths)):
        if is_sensitive_path(candidate):
            sensitive_skipped += 1
            is_incomplete = True
            continue
        candidate_path = source / candidate
        try:
            candidate_stat = candidate_path.lstat()
        except OSError:
            if not fingerprint_entry(candidate_path, candidate):
                break
            continue

        if not stat.S_ISDIR(candidate_stat.st_mode):
            if not fingerprint_entry(candidate_path, candidate):
                break
            continue

        walk_errors: list[OSError] = []
        for root, dirnames, filenames in os.walk(
            candidate_path,
            topdown=True,
            followlinks=False,
            onerror=walk_errors.append,
        ):
            dirnames.sort()
            filenames.sort()
            root_path = Path(root)
            symlink_dirs: list[str] = []
            real_dirs: list[str] = []
            for dirname in dirnames:
                try:
                    mode = (root_path / dirname).lstat().st_mode
                except OSError:
                    mode = 0
                if stat.S_ISLNK(mode) or mode == 0:
                    symlink_dirs.append(dirname)
                else:
                    real_dirs.append(dirname)
            dirnames[:] = real_dirs

            for entry_name in [*symlink_dirs, *filenames]:
                file_path = root_path / entry_name
                try:
                    rel_file = file_path.relative_to(source).as_posix()
                except ValueError:
                    is_incomplete = True
                    file_hashes.append("::UNTRACKED_PATH_ESCAPE_INCOMPLETE::")
                    continue
                if not fingerprint_entry(file_path, rel_file):
                    break
            if truncated:
                break
        if walk_errors:
            is_incomplete = True
            file_hashes.append(f"{candidate}:UNREADABLE_DIRECTORY_INCOMPLETE")
        if truncated:
            break

    if sensitive_skipped:
        file_hashes.append(f"::SENSITIVE_UNTRACKED_UNFINGERPRINTED:{sensitive_skipped}::")

    return "\n".join(sorted(set(file_hashes))), is_incomplete


def check_project_git_drift(name: str, row: dict[str, Any]) -> dict[str, Any] | None:
    """Inspect live git state for a project row and return drift metrics if git-enabled."""
    source = PROJECTS_ROOT / name
    snapshot = row.get("source_snapshot")
    if not source.exists() or not snapshot or not snapshot.get("git"):
        return None

    current_head = _git_value(source, "rev-parse", "--short", "HEAD")
    current_branch = _git_value(source, "branch", "--show-current") or "DETACHED"
    current_status = _git_value(source, "status", "--porcelain")
    current_lines = len(current_status.splitlines()) if current_status and current_status != "unavailable" else 0
    untracked_paths, untracked_enumeration_complete = _git_untracked_paths(source)
    untracked_digest, untracked_incomplete = _untracked_content_digest(source, untracked_paths)
    status_readable = current_status != "unavailable"
    untracked_incomplete_reasons: list[str] = []
    if not status_readable:
        untracked_incomplete_reasons.append("git_status_unreadable")
    if not untracked_enumeration_complete:
        untracked_incomplete_reasons.append("untracked_path_enumeration_failed")
    if untracked_incomplete:
        untracked_incomplete_reasons.append("untracked_content_fingerprint_incomplete")

    status_fragments = [current_status if current_status != "unavailable" else ""]
    if untracked_digest:
        status_fragments.append(untracked_digest)
    if not untracked_enumeration_complete:
        status_fragments.append("::UNTRACKED_PATH_ENUMERATION_INCOMPLETE::")
    status_payload = "\n---\n".join(status_fragments)
    # A dirty-item count is blind to two files changing identity while the count holds.
    # Streaming untracked files' SHA-256 prevents untracked content alterations from reporting clean.
    current_status_sha256 = hashlib.sha256(status_payload.encode("utf-8")).hexdigest()

    # Porcelain output is "XY path" -- it carries no file content, so editing an
    # already-modified tracked file leaves it byte-identical. The patch is what closes
    # that hole. The content options are refused here rather than in the shared runner:
    # they are diff-specific, and they are exactly the features a local config can aim at
    # external executables (diff.external, textconv filters).
    current_patch = _git_value(source, "diff", "--no-ext-diff", "--no-textconv", "HEAD")
    patch_readable = current_patch != "unavailable"
    if not patch_readable:
        untracked_incomplete_reasons.append("git_patch_unreadable")
    # One flag for "this fingerprint does not cover everything it claims to". Any component
    # the comparison needs and could not read leaves drift unresolved, not absent: an
    # unreadable patch is exactly how a byte change to an already-dirty tracked file reports
    # clean, because porcelain output carries no content.
    fingerprint_incomplete = bool(untracked_incomplete_reasons)
    untracked_incomplete = fingerprint_incomplete
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
    has_drift = (
        head_or_branch_drift or lines_drift or content_drift or patch_drift or fingerprint_incomplete
    )

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
        "status_readable": status_readable,
        "patch_readable": patch_readable,
        "fingerprint_complete": not fingerprint_incomplete,
        "fingerprint_incomplete_reasons": untracked_incomplete_reasons,
        "untracked_enumeration_complete": untracked_enumeration_complete,
        "untracked_fingerprint_complete": not untracked_incomplete,
        "untracked_incomplete": untracked_incomplete,
        "untracked_incomplete_reasons": untracked_incomplete_reasons,
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
    # Two axes, counted separately on purpose. `completed_analysis_milestones` is scheduling
    # progress; `promotion_counts` is how much each of those milestones actually demonstrated.
    # A single number that mixes them can only be wrong in one direction, and it was: every
    # completed analysis was reported as verified regardless of the level it claimed.
    completed_analysis_milestones = 0
    promotion_counts = {level: 0 for level in RECOVERY_PROMOTION_LEVELS}
    recovered_runtime_behaviors = 0
    adopted_runtime_behaviors = 0
    converged_runtime_behaviors = 0
    resolved_capabilities = 0
    validated_completed_claims = 0
    invalid_completed_claims: list[dict[str, Any]] = []
    ownership_index = build_evidence_ownership_index(suites)

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
        valid_in_suite = 0
        invalid_in_suite = 0
        prototype_in_suite = 0
        for wave in waves:
            if wave.get("status") != "complete":
                continue
            evidence_status = get_wave_evidence_status(suite_id, wave, ownership_index)
            if not evidence_status["evidence_valid"]:
                invalid_in_suite += 1
                invalid_completed_claims.append({
                    "suite_id": suite_id,
                    "wave_id": wave.get("id"),
                    "errors": evidence_status["evidence_errors"],
                })
                continue
            valid_in_suite += 1
            validated_completed_claims += 1
            claim = wave.get("recovery_claim", {})
            kind = claim.get("kind")
            level = claim.get("level")
            if level in promotion_counts:
                promotion_counts[level] += 1
            if kind == "analysis":
                completed_analysis_milestones += 1
                if level == "prototype":
                    prototype_in_suite += 1
            if kind == "runtime" and level in RUNTIME_PROMOTION_LEVELS:
                recovered_runtime_behaviors += 1
            if kind in {"runtime", "adoption"} and level in {"adopted", "converged"}:
                adopted_runtime_behaviors += 1
            if level == "converged":
                converged_runtime_behaviors += 1
            if kind == "resolution":
                resolved_capabilities += 1
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
            "validated_completed_claims": valid_in_suite,
            "invalid_completed_claims": invalid_in_suite,
            "waves_owing_runtime_followup": owing_in_suite,
            "prototype_level_claims": prototype_in_suite,
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
        "validated_completed_claims": validated_completed_claims,
        "invalid_completed_claims": invalid_completed_claims,
        "waves_owing_runtime_followup": waves_owing_runtime_followup,
        "portfolio_progress_pct": round((completed_waves / total_waves * 100) if total_waves else 0, 1),
        "recovery_standard_id": standard.get("standard_id"),
        "recovery_target_score": standard.get("target_score"),
        "completed_analysis_milestones": completed_analysis_milestones,
        "promotion_counts": promotion_counts,
        "prototype_level_claims": promotion_counts["prototype"],
        "recovered_runtime_behaviors": recovered_runtime_behaviors,
        "adopted_runtime_behaviors": adopted_runtime_behaviors,
        "converged_runtime_behaviors": converged_runtime_behaviors,
        "resolved_capabilities": resolved_capabilities,
        # The adopted 9/10 rubric is dimension-weighted. Existing receipts do not yet carry
        # per-dimension scores, so manufacturing a numeric recovery score from milestone count
        # would be false precision. The status is explicit until those receipts exist.
        "recovery_score": None,
        "recovery_score_status": "insufficient_dimension_evidence",
        "evidence_health_pct": round(
            (validated_completed_claims / completed_waves * 100) if completed_waves else 0,
            1,
        ),
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

    declared_evidence_paths: dict[Path, str] = {}
    # Every artifact under a suite's evidence/ directory must be owned by something. A wave
    # owns its canonical receipt; anything else is declared here with the role it actually
    # plays, so a stale narrative cannot sit beside a canonical receipt looking like one.
    allowed_evidence_roles = {"fixture", "ancillary", "historical"}
    allowed_suite_states = {"specified", "prototype", "migrating", "operational", "converged", "retired"}
    allowed_wave_statuses = {"specified", "prototype", "complete", "blocked", "deferred"}

    for suite_id, manifest in suites.items():
        if manifest.get("id") != suite_id:
            report.errors.append(f"{suite_id}: manifest id does not match its registry key")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            report.errors.append(f"{suite_id}: invalid schema version")
        if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
            report.errors.append(f"{suite_id}: suite name is required")
        if manifest.get("state") not in allowed_suite_states:
            report.errors.append(f"{suite_id}: suite state is invalid")
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
        wave_ids: set[str] = set()
        wave_orders: set[int] = set()
        for wave in manifest.get("waves", []):
            if not isinstance(wave, dict):
                report.errors.append(f"{suite_id}: every wave must be an object")
                continue
            wave_id = wave.get("id")
            if not isinstance(wave_id, str) or not wave_id or wave_id in wave_ids:
                report.errors.append(f"{suite_id}: wave ID is missing or duplicated: {wave_id!r}")
            else:
                wave_ids.add(wave_id)
            wave_order = wave.get("order")
            if not isinstance(wave_order, int) or isinstance(wave_order, bool) or wave_order in wave_orders:
                report.errors.append(f"{suite_id}/{wave_id}: wave order is missing, invalid, or duplicated")
            else:
                wave_orders.add(wave_order)
            if wave.get("status") not in allowed_wave_statuses:
                report.errors.append(f"{suite_id}/{wave_id}: wave status is invalid")
            for required_text in ("objective", "acceptance"):
                if not isinstance(wave.get(required_text), str) or not wave[required_text].strip():
                    report.errors.append(f"{suite_id}/{wave_id}: wave {required_text} is required")
            declared_path = resolve_declared_evidence_path(wave.get("evidence"), suite_id)
            if declared_path is None:
                report.errors.append(f"{suite_id}/{wave_id}: declared evidence path is invalid or escapes its suite")
            else:
                resolved_declared = declared_path.resolve(strict=False)
                prior_owner = declared_evidence_paths.get(resolved_declared)
                if prior_owner is not None:
                    report.errors.append(
                        f"{suite_id}/{wave_id}: evidence path is already owned by {prior_owner}"
                    )
                else:
                    declared_evidence_paths[resolved_declared] = f"{suite_id}/{wave_id}"
            # Every declared claim is checked, at whatever level it claims. Only the
            # promotion rules below are reserved for waves that claim completion: a
            # prototype receipt that later goes malformed must still fail this gate.
            is_complete = wave.get("status") == "complete"
            claim = wave.get("recovery_claim")
            if not isinstance(claim, dict):
                if is_complete:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: completed wave requires recovery_claim")
                continue
            claim_kind = claim.get("kind")
            claim_level = claim.get("level")
            if not isinstance(claim_kind, str) or claim_kind not in claim_kinds:
                report.errors.append(f"{suite_id}/{wave.get('id')}: unknown recovery claim kind")
                claim_kind = None
            if not isinstance(claim_level, str) or claim_level not in RECOVERY_PROMOTION_LEVELS:
                report.errors.append(f"{suite_id}/{wave.get('id')}: unknown recovery promotion level")
                claim_level = None
            elif is_complete and claim_level == "specified":
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed wave cannot claim a specified level")
            elif is_complete and claim_kind == "runtime" and claim_level == "prototype":
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed runtime wave cannot claim a prototype level")
            if not isinstance(claim.get("real_runtime"), bool):
                report.errors.append(f"{suite_id}/{wave.get('id')}: recovery claim must state real_runtime")
            if (
                claim_kind in {"runtime", "adoption", "convergence"}
                or claim_level in EXECUTED_PROMOTION_LEVELS
            ) and claim.get("real_runtime") is not True:
                report.errors.append(
                    f"{suite_id}/{wave.get('id')}: executed recovery claim ({claim_kind}/{claim_level}) must exercise a real runtime"
                )
            if claim_kind == "analysis" and claim.get("real_runtime") is not False:
                report.errors.append(f"{suite_id}/{wave.get('id')}: analysis claim cannot manufacture runtime execution")
            # `source_executed` and above are runtime rungs: their names assert that donor
            # code was actually invoked, and `parity_verified` and above additionally assert
            # it was compared against a destination. Analysis claims are validated against
            # the per-wave receipt specification, which describes what a receipt *contains* --
            # it has no way to establish an argv, an exit code, a source fingerprint, or any
            # other proof that the donor ran. Letting an analysis claim sit at
            # `source_executed` therefore made a manifest boolean the whole evidence for the
            # strongest thing the ladder can say, which is exactly the fail-open this refuses.
            # An analysis wave whose runner really does invoke the donor is not blocked from
            # the rung -- it earns it by declaring `kind: runtime` and retaining a
            # `portfolio-runtime-source-v1` receipt that proves the invocation.
            # Guarding on `analysis` alone left the gate open for every other non-runtime
            # kind. `resolution` routes to the generic resolution contract, and `adoption`
            # and `convergence` fall through to theirs, so all three could sit at
            # `source_executed` with no argv, exit status, or donor invocation anywhere in
            # the receipt -- the same fail-open this refuses for `analysis`. The rule is a
            # property of the kind, so it is stated as one.
            if claim_level is not None and claim_kind is not None:
                if claim_level in EXECUTED_PROMOTION_LEVELS and claim_level not in EXECUTED_LEVELS_BY_KIND.get(
                    claim_kind, frozenset()
                ):
                    permitted = EXECUTED_LEVELS_BY_KIND.get(claim_kind)
                    report.errors.append(
                        f"{suite_id}/{wave.get('id')}: {claim_kind} claim cannot occupy the runtime "
                        f"promotion level {claim_level!r}; "
                        + (
                            f"the only executed level it may hold is {sorted(permitted)[0]!r}"
                            if permitted
                            else "it may not hold an executed level at all"
                        )
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
            if claim_kind == "runtime" and claim_level == "parity_verified":
                missing_basis = sorted(RUNTIME_PARITY_EVIDENCE - evidence_basis_set)
                if missing_basis:
                    report.errors.append(
                        f"{suite_id}/{wave.get('id')}: runtime parity evidence is missing {', '.join(missing_basis)}"
                    )
                if claim.get("receipt_contract") not in {
                    "accessibility-wcag-331-v1", "portfolio-runtime-parity-v1"
                }:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: runtime parity receipt contract is missing or unsupported")
            if claim_kind == "runtime" and claim_level == "source_executed" and claim.get("receipt_contract") != "portfolio-runtime-source-v1":
                report.errors.append(
                    f"{suite_id}/{wave.get('id')}: source_executed runtime requires portfolio-runtime-source-v1"
                )
            if claim_kind == "runtime" and claim_level in {"adopted", "converged"}:
                expected_runtime_contract = (
                    "portfolio-adoption-v1" if claim_level == "adopted" else "portfolio-convergence-v1"
                )
                if claim.get("receipt_contract") != expected_runtime_contract:
                    report.errors.append(
                        f"{suite_id}/{wave.get('id')}: runtime at {claim_level} requires {expected_runtime_contract}"
                    )
            expected_lifecycle_contract = RECEIPT_CONTRACT_FOR_KIND.get(claim_kind)
            if expected_lifecycle_contract and claim.get("receipt_contract") != expected_lifecycle_contract:
                report.errors.append(
                    f"{suite_id}/{wave.get('id')}: {claim_kind} requires {expected_lifecycle_contract}"
                )
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
            evidence_file = declared_path
            if not evidence_file or not evidence_file.is_file():
                if is_complete:
                    report.errors.append(f"{suite_id}/{wave.get('id')}: completed claim evidence is missing")
                else:
                    report.warnings.append(
                        f"{suite_id}/{wave.get('id')}: declared claim has no retained receipt at {declared_path}"
                    )
            else:
                for evidence_error in evidence_errors(wave, evidence_file, suite_id):
                    report.errors.append(f"{suite_id}/{wave.get('id')}: {evidence_error}")

    for suite_id, manifest in suites.items():
        supporting = manifest.get("supporting_evidence", [])
        if not isinstance(supporting, list):
            report.errors.append(f"{suite_id}: supporting_evidence must be a list")
            supporting = []
        for entry in supporting:
            if not isinstance(entry, dict):
                report.errors.append(f"{suite_id}: every supporting evidence entry must be an object")
                continue
            entry_path = resolve_declared_evidence_path(entry.get("path"), suite_id)
            if entry_path is None:
                report.errors.append(
                    f"{suite_id}: supporting evidence path is invalid or escapes its suite: {entry.get('path')!r}"
                )
                continue
            if entry.get("role") not in allowed_evidence_roles:
                report.errors.append(f"{suite_id}: supporting evidence {entry['path']} has an invalid role")
            if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                report.errors.append(f"{suite_id}: supporting evidence {entry['path']} needs a reason")
            resolved_entry = entry_path.resolve(strict=False)
            prior_owner = declared_evidence_paths.get(resolved_entry)
            if prior_owner is not None:
                report.errors.append(
                    f"{suite_id}: supporting evidence {entry['path']} is already owned by {prior_owner}"
                )
            else:
                declared_evidence_paths[resolved_entry] = f"{suite_id}/supporting"
            if not entry_path.is_file():
                report.errors.append(f"{suite_id}: declared supporting evidence is missing at {entry['path']}")

        evidence_dir = SUITES_ROOT / suite_id / "evidence"
        if not evidence_dir.is_dir():
            continue
        for found in sorted(evidence_dir.rglob("*")):
            if not found.is_file():
                continue
            if found.resolve(strict=False) in declared_evidence_paths:
                continue
            report.errors.append(
                f"{suite_id}: undeclared artifact under active evidence: "
                f"{found.relative_to(SUITES_ROOT)}"
            )

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
            if drift.get("patch_drift"):
                report.warnings.append(
                    f"{name}: working-tree patch content drifted from recorded snapshot"
                )
            if drift.get("content_drift"):
                report.warnings.append(
                    f"{name}: working-tree untracked/status content drifted from recorded snapshot"
                )
            if drift.get("untracked_incomplete"):
                reasons = ", ".join(drift.get("untracked_incomplete_reasons") or ["unknown reason"])
                report.warnings.append(
                    f"{name}: untracked content fingerprint is incomplete ({reasons}); "
                    "drift is unresolved and baseline recording is refused"
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
    """Build a baseline snapshot from a project's live git state, or None if git is unreadable.

    A baseline is a claim that the recorded bytes were reviewed. Any component the
    fingerprint needs and could not read makes that claim unsupportable, so acceptance is
    refused rather than recorded with a hole in it.
    """
    if (
        "unavailable" in {drift["current_head"], drift["current_branch"]}
        or not drift.get("fingerprint_complete", False)
    ):
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


class LedgerConflict(RuntimeError):
    """The ledger changed under a transaction that had already read it."""


@contextlib.contextmanager
def _ledger_lock():
    """Serialize ledger transactions on a sidecar lock opened under an anchored directory.

    The lock is a sidecar rather than the ledger itself because the commit detaches the
    document's inode from its name, so locking the document would lock an inode no longer
    reachable by that name for the next writer. The lock covers cooperative writers only;
    uncooperative ones are handled by the compare-and-swap inside the commit itself.
    """
    directory_fd = open_confined_directory(SUITES_ROOT, "portfolio")
    try:
        handle = os.open(
            f"{_LEDGER_PATH.name}.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        os.close(handle)


def fingerprint_baselines(dry_run: bool = False, accept: bool = False) -> list[str]:
    """Record missing baseline fingerprints, and on `accept` re-capture drifted baselines.

    Read, live-state decision, transformation and commit all happen under one lock. Without
    it the new document is built from text read before an arbitrarily long git scan, and
    replacing the file discards every edit another writer committed in between -- silently,
    because the replace succeeds.

    The sidecar lock only covers cooperative writers, so the conflict check lives inside
    the commit primitive itself (:func:`portfolio_suites.txn.commit_replacement`): the
    replacement is conditional on the occupant still being byte-for-byte the document this
    transaction read, decided atomically at the swap rather than by a digest check that
    ends before the temporary is even flushed. An uncooperative writer that lands an edit
    during the write therefore blocks the commit instead of being overwritten.
    """
    with _ledger_lock():
        text = _LEDGER_PATH.read_text(encoding="utf-8")
        read_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        new_text, updated = apply_snapshot_updates(text, pending_snapshots(accept))
        if updated and not dry_run:
            try:
                ledger_mode = stat.S_IMODE(_LEDGER_PATH.stat().st_mode)
            except OSError:
                ledger_mode = 0o600
            # ``_LEDGER_PATH`` is trusted module state like SUITES_ROOT itself; opening its
            # parent O_NOFOLLOW pins the directory inode without re-resolving any string.
            directory_fd = os.open(
                _LEDGER_PATH.parent,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                temp = write_temp_payload(
                    directory_fd,
                    _LEDGER_PATH.name,
                    new_text.encode("utf-8"),
                    mode=ledger_mode,
                )
                try:
                    commit_replacement(
                        directory_fd,
                        _LEDGER_PATH.name,
                        temp,
                        expected_digest=read_digest,
                    )
                except OccupantConflict as error:
                    raise LedgerConflict(
                        "the project ledger changed while baselines were being computed; "
                        "no baseline was written and the concurrent edit was preserved. "
                        "Re-run to replay against the current document."
                    ) from error
                except CommitUncertain as error:
                    # The ledger is the single source of truth for all 70 dispositions and
                    # cannot be rebuilt from the suites, so "replaced but durability is
                    # unconfirmed" must never be reported as a clean refusal.
                    raise CommitUnverified(str(error)) from error
            finally:
                os.close(directory_fd)
    return updated
