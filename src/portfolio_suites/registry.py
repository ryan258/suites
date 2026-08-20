"""Load, inspect, and verify the suite registry, portfolio ledger, and live source tree."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import CONTRACTS, SCHEMA_VERSION

SUITES_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = SUITES_ROOT.parent
SUITE_DIRS = (
    "accessibility", "operator-os", "brand-publishing", "production-house",
    "model-behavior-lab", "discovery-decision", "agent-reliability", "game-design",
)


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
    projects = ledger.get("projects", [])

    total_projects = len(projects)
    suite_summaries = []
    total_waves = 0
    completed_waves = 0

    for suite_id, manifest in suites.items():
        owned = [p for p in projects if p.get("primary_suite") == suite_id]
        waves = manifest.get("waves", [])
        total_waves += len(waves)
        completed_in_suite = sum(1 for w in waves if w.get("status") == "complete")
        completed_waves += completed_in_suite
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
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        report.errors.append(f"registry load failed: {error}")
        return report

    if len(suites) != len(SUITE_DIRS):
        report.errors.append("suite IDs are missing or duplicated")
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
                if ".git" not in dirnames and ".git" not in filenames:
                    continue
                # ponytail: don't descend into the .git dir we just found, it's the walk's dominant cost
                dirnames[:] = [d for d in dirnames if d != ".git"]
                marker_parent = Path(dirpath)
                if marker_parent == SUITES_ROOT:
                    continue
                parts = marker_parent.relative_to(PROJECTS_ROOT).parts
                if 1 < len(parts) <= 5:
                    actual_markers.add(str(marker_parent.relative_to(PROJECTS_ROOT)))
            for path in sorted(actual_markers - expected_markers):
                report.errors.append(f"unreviewed nested Git marker: {path}")
            for path in sorted(expected_markers - actual_markers):
                report.errors.append(f"nested Git marker no longer exists: {path}")

    return report
