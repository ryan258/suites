"""Shared utilities for source adapters across product suites."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ..contracts import compute_sha256
from ..paths import SUITES_ROOT
from ..provenance import is_meaningful_git_fingerprint


SENSITIVE_PATH_PATTERN = re.compile(
    r"(^|/)\.env($|\.)|(^|/)\.netrc$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$|\.(pem|p12|pfx|key)$|credential",
    re.IGNORECASE,
)
SENSITIVE_ENV_PATTERN = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)


def donor_env() -> dict[str, str]:
    """Environment for donor subprocesses, with this control plane's own secrets removed."""
    return {
        name: value
        for name, value in os.environ.items()
        if not SENSITIVE_ENV_PATTERN.search(name)
    }


def get_repo_path(repo_name: str, env_var: str | None = None) -> Path:
    """Resolve repository path dynamically from environment, workspace sibling, or standard directory."""
    if env_var and os.environ.get(env_var):
        # An explicit override is authoritative even when it is wrong. Returning the missing
        # path lets the caller fail closed instead of silently testing an unrelated fallback.
        return Path(os.environ[env_var]).resolve()
    sibling = (SUITES_ROOT.parent / repo_name).resolve()
    if sibling.exists():
        return sibling
    home_projects = (Path.home() / "Projects" / repo_name).resolve()
    if home_projects.exists():
        return home_projects
    return sibling


def get_git_fingerprint(repo_dir: Path, tracked_files: list[str] | None = None) -> dict[str, Any]:
    """Retrieve authentic git commit, branch, dirty status, and content-addressed hashes."""
    if not (repo_dir / ".git").exists():
        return {"branch": "unknown", "head": "unknown", "status": "no_git_dir"}
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, env=donor_env(), timeout=5).decode().strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, env=donor_env(), timeout=5).decode().strip()
        status_raw = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_dir, env=donor_env(), timeout=5).decode().strip()
        diff_raw = subprocess.check_output(["git", "diff", "HEAD"], cwd=repo_dir, env=donor_env(), timeout=5)

        dirty_lines = [line for line in status_raw.splitlines() if line.strip()]
        is_dirty = len(dirty_lines) > 0
        patch_sha256 = compute_sha256(diff_raw) if is_dirty else ""

        # Auto-discover relevant tracked files based on repository layout if not explicitly provided
        if tracked_files is None:
            if (repo_dir / "package.json").exists():
                tracked_files = [
                    "a11y-tools/aria-validator/index.ts",
                    "a11y-tools/tests/wcag-331-error-association.test.ts",
                    "a11y-tools/tests/full-audit.test.ts",
                    "a11y-tools/tests/contracts.test.ts",
                    "package.json",
                    "package-lock.json",
                    "tsconfig.json",
                ]
            elif (repo_dir / "wcag_auditor").exists():
                tracked_files = [
                    "wcag_auditor/rules/understandable_rules.py",
                    "wcag_auditor/rules/core_rules.py",
                    "pyproject.toml",
                    "requirements.txt",
                    "README.md",
                    "docs/coverage.md",
                ]
            elif (repo_dir / "pyproject.toml").exists() or (repo_dir / "src").exists() or (repo_dir / "brand_workshop").exists():
                tracked_files = [
                    "pyproject.toml",
                    "README.md",
                    "spec.md",
                    "brand_workshop/phases.py",
                    "src/brand_maker/publishing/developer_exports.py",
                ]
            else:
                tracked_files = ["README.md", "MANUAL.md"]

        file_hashes: dict[str, str] = {}
        for rel in tracked_files:
            fp = repo_dir / rel
            if fp.is_file():
                file_hashes[rel] = compute_sha256(fp.read_bytes())

        # Also fingerprint any modified/untracked files reported by git status. A donor's
        # secret files are neither read nor named in evidence; the dirty count stays honest.
        recorded_dirty_lines: list[str] = []
        for line in dirty_lines:
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                recorded_dirty_lines.append(line)
                continue
            status_code, dirty_rel = parts
            if SENSITIVE_PATH_PATTERN.search(dirty_rel):
                recorded_dirty_lines.append(f"{status_code} <redacted-sensitive-path>")
                continue
            recorded_dirty_lines.append(line)
            dirty_fp = repo_dir / dirty_rel
            if dirty_fp.is_file() and dirty_rel not in file_hashes:
                file_hashes[dirty_rel] = compute_sha256(dirty_fp.read_bytes())

        lockfile_path = repo_dir / "package-lock.json"
        if not lockfile_path.exists():
            lockfile_path = repo_dir / "uv.lock"
        lockfile_sha = compute_sha256(lockfile_path.read_bytes()) if lockfile_path.is_file() else ""

        return {
            "branch": branch,
            "head": head,
            "short": f"{branch}@{head[:7]}",
            "is_dirty": is_dirty,
            "dirty_files_count": len(dirty_lines),
            "dirty_files": recorded_dirty_lines,
            "patch_sha256": patch_sha256,
            "lockfile_sha256": lockfile_sha,
            "tested_files_fingerprint": file_hashes,
            "target_state": "local_working_tree_candidate" if is_dirty else "clean_commit",
        }
    except Exception as error:
        return {"branch": "unknown", "head": "unknown", "error": str(error)}
