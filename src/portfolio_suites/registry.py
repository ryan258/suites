"""Load, inspect, and verify the suite registry, portfolio ledger, and live source tree."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import CONTRACTS, SCHEMA_VERSION

SUITES_ROOT = Path(os.environ["SUITES_ROOT"]).resolve() if "SUITES_ROOT" in os.environ else Path(__file__).resolve().parents[2]
PROJECTS_ROOT = SUITES_ROOT.parent
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


def get_project(name: str) -> dict[str, Any] | None:
    ledger = load_ledger()
    for row in ledger.get("projects", []):
        if row.get("name") == name:
            return row
    return None


def _git_value(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


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
    snap_head = snapshot.get("head")
    snap_branch = snapshot.get("branch")
    snap_lines = snapshot.get("status_lines", 0)

    head_or_branch_drift = (current_head != snap_head) or (current_branch != snap_branch)
    lines_drift = (current_lines != snap_lines)
    has_drift = head_or_branch_drift or lines_drift

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
        for wave in waves:
            if wave.get("status") != "complete":
                continue
            claim = wave.get("recovery_claim", {})
            kind = claim.get("kind")
            level = claim.get("level")
            if kind == "analysis":
                verified_analysis_milestones += 1
            if kind == "runtime" and level in {"parity_verified", "adopted", "converged"}:
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
            if wave.get("status") != "complete":
                continue
            claim = wave.get("recovery_claim")
            if not isinstance(claim, dict):
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed wave requires recovery_claim")
                continue
            if claim.get("kind") not in claim_kinds:
                report.errors.append(f"{suite_id}/{wave.get('id')}: unknown recovery claim kind")
            claim_kind = claim.get("kind")
            claim_level = claim.get("level")
            if claim_level not in RECOVERY_PROMOTION_LEVELS:
                report.errors.append(f"{suite_id}/{wave.get('id')}: unknown recovery promotion level")
            elif claim_level in {"specified", "prototype"}:
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed wave cannot claim a planning or prototype level")
            if not isinstance(claim.get("real_runtime"), bool):
                report.errors.append(f"{suite_id}/{wave.get('id')}: recovery claim must state real_runtime")
            if claim_kind == "runtime" and claim.get("real_runtime") is not True:
                report.errors.append(f"{suite_id}/{wave.get('id')}: runtime recovery must exercise a real runtime")
            if claim_kind == "analysis" and claim.get("real_runtime") is not False:
                report.errors.append(f"{suite_id}/{wave.get('id')}: analysis claim cannot manufacture runtime execution")

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
            if claim_kind == "runtime" and claim_level in {"parity_verified", "adopted", "converged"}:
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
                report.errors.append(f"{suite_id}/{wave.get('id')}: completed claim evidence is missing")
            elif claim_kind == "runtime" and claim_level in {"parity_verified", "adopted", "converged"}:
                for receipt_error in _runtime_parity_receipt_errors(
                    evidence_file,
                    claim.get("receipt_contract", ""),
                ):
                    report.errors.append(f"{suite_id}/{wave.get('id')}: {receipt_error}")

    if check_live:
        expected = set(projects)
        actual = {p.name for p in PROJECTS_ROOT.iterdir() if p.is_dir() and p.name != "suites"}
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
