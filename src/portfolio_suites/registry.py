"""Load, inspect, and verify the suite registry, portfolio ledger, and live source tree."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .contracts import CONTRACTS, SCHEMA_VERSION
from .adapters.common import run_donor_git
from .execution_trace import (
    load_execution_trace_contract,
    validate_execution_trace_contract,
)
from .paths import (
    PROJECTS_ROOT,
    SUITES_ROOT,
    CommitUnverified,
    open_confined_directory,
)
from .provenance import is_meaningful_git_fingerprint, is_sensitive_path  # noqa: F401 -- predicate identity is asserted by tests
from .recovery_program import load_recovery_program, validate_recovery_program
from .recovery_policy import (
    EXECUTED_LEVELS_BY_KIND,
    EXECUTED_PROMOTION_LEVELS,
    RECEIPT_CONTRACT_FOR_KIND,
    RECOVERY_CLAIM_KINDS,
    RECOVERY_DIMENSIONS,
    RECOVERY_ENFORCEMENT,
    RECOVERY_PROMOTION_LEVELS,
    RECOVERY_RESOLUTION_OUTCOMES,
    RECOVERY_TIERS,
    RUNTIME_PARITY_EVIDENCE,
    RUNTIME_PROMOTION_LEVELS,
    RUNTIME_SOURCE_EVIDENCE,
)
from .receipts import (  # noqa: F401 -- compatibility surface for tests and callers
    ANALYSIS_RECEIPT_SPECS,
    _analysis_evidence_errors,
    _analysis_receipt_semantic_errors,
    _load_json,
    _lookup_receipt_spec,
    _runtime_parity_receipt_errors,
    evidence_errors,
    evidence_ineligibility_reason,
)
from .txn import CommitUncertain, OccupantConflict, commit_replacement, write_temp_payload

RECOVERY_STANDARD_PATH = SUITES_ROOT / "portfolio" / "recovery-standard.json"
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


def _is_finder_junk_path(path: str) -> bool:
    """True for a macOS Finder ``.DS_Store`` entry at any depth (segment-exact).

    A segment-exact match (``.DS_Store`` or ``dir/.DS_Store``) keeps look-alike names
    like ``backup.DS_Store`` visible, so only real Finder junk is excluded. Deliberately
    dropped entries remain fully covered by ``patch_sha256`` (``git diff HEAD``), which
    hashes tracked file content, staged adds, and deletions, so excluding these from the
    porcelain digest cannot hide a real change.
    """
    return path == ".DS_Store" or path.endswith("/.DS_Store")


def _is_ignored_junk_line(porcelain_line: str) -> bool:
    """True for a macOS Finder .DS_Store porcelain line so it cannot fake a dirty tree.

    Porcelain lines carry an ``XY path`` shape; the path portion is what matters.
    Finder recreates ``.DS_Store`` spuriously on folder touches, so entries that are
    Finder junk are excluded from both the dirty-line count and the status digest that
    baselines compare against. A repo that deliberately tracks ``.DS_Store`` should pin
    it via its own gitignore/disposition instead.
    """
    path = porcelain_line[3:].strip() if len(porcelain_line) >= 4 else porcelain_line
    return _is_finder_junk_path(path)


def _git_untracked_paths(source: Path) -> tuple[list[str], bool]:
    """Return NUL-delimited untracked paths plus whether Git enumerated them successfully.

    macOS Finder junk (``.DS_Store``) is excluded from the enumeration before any content
    digest is computed, so touching a folder in Finder cannot re-drift a clean baseline.
    """
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
            if rel_name and not _is_finder_junk_path(rel_name):
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
    porcelain_lines = (
        [line for line in current_status.splitlines() if not _is_ignored_junk_line(line)]
        if current_status and current_status != "unavailable"
        else []
    )
    current_lines = len(porcelain_lines)
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

    status_fragments = ["\n".join(porcelain_lines) if status_readable else ""]
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
        recovery_program = load_recovery_program()
        execution_trace_contract = load_execution_trace_contract()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        report.errors.append(f"registry load failed: {error}")
        return report

    if len(suites) != len(SUITE_DIRS):
        report.errors.append("suite IDs are missing or duplicated")
    for error in validate_recovery_program(recovery_program, suites):
        report.errors.append(f"recovery program: {error}")
    for error in validate_execution_trace_contract(execution_trace_contract):
        report.errors.append(f"execution trace contract: {error}")

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
            if claim_kind == "runtime" and claim_level == "source_executed":
                missing_basis = sorted(RUNTIME_SOURCE_EVIDENCE - evidence_basis_set)
                if missing_basis:
                    report.errors.append(
                        f"{suite_id}/{wave.get('id')}: source_executed runtime evidence is missing {', '.join(missing_basis)}"
                    )
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
