"""Shared utilities for source adapters across product suites."""

from __future__ import annotations

import functools
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ..contracts import compute_sha256
from ..paths import SUITES_ROOT
from ..provenance import SENSITIVE_PATH_PATTERN, is_meaningful_git_fingerprint


SENSITIVE_ENV_PATTERN = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)

# Only these names are inherited. A denylist over variable *names* cannot work here: the
# capability a donor subprocess inherits is rarely spelled out in its name. SSH_AUTH_SOCK is
# an open agent socket, DOCKER_CONFIG and KUBECONFIG are credential directories,
# PIP_INDEX_URL routinely carries embedded user:pass, and PORTFOLIO_OPERATOR_APPROVAL_STORE
# is this control plane's own authority -- none of which match KEY|TOKEN|SECRET.
DONOR_ENV_ALLOWLIST = frozenset({
    "PATH",     # without it the interpreter and git are unreachable
    "LANG",     # locale determinism: sorting and message text
    "LC_ALL",
    "LC_CTYPE",
    "TZ",       # timestamp determinism
    "TMPDIR",   # tools that must write scratch files
})

# Set rather than inherited: the neutral values. HOME is deliberately absent, so these close
# the credential surfaces the two invoked toolchains would otherwise reach through it
# (~/.ssh, ~/.npmrc, ~/.docker, ~/.aws, and git's global credential.helper).
DONOR_ENV_DEFAULTS = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",       # never block on a credential prompt
    "GIT_ASKPASS": "",
    "npm_config_userconfig": "/dev/null",
    "npm_config_update_notifier": "false",
}


@functools.lru_cache(maxsize=1)
def _global_excludes_file() -> str | None:
    """The user's global gitignore path, resolved once in *this* process.

    Withholding HOME also withholds git's global excludes, which would silently reclassify
    editor and tooling directories in all seventy donors as untracked content and flip every
    clean donor to dirty. That is a change to the migration record, not a security boundary,
    so the one setting is carried across explicitly -- as a value, never as a config file the
    subprocess could reach a credential helper through.
    """
    configured = subprocess.run(
        ["git", "config", "--get", "core.excludesFile"],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    if configured:
        return str(Path(configured).expanduser())
    xdg = os.environ.get("XDG_CONFIG_HOME")
    default = (Path(xdg) if xdg else Path.home() / ".config") / "git" / "ignore"
    return str(default) if default.is_file() else None


def donor_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment for donor subprocesses: allowlisted names plus explicit additions.

    A gate that genuinely needs another variable passes it in ``extra`` and says so at the
    call site, which is where that decision can be reviewed.
    """
    env = {
        name: os.environ[name]
        for name in DONOR_ENV_ALLOWLIST
        if name in os.environ
    }
    env.update(DONOR_ENV_DEFAULTS)
    excludes = _global_excludes_file()
    if excludes:
        # GIT_CONFIG_KEY/VALUE injects one setting without exposing a config file.
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "core.excludesFile"
        env["GIT_CONFIG_VALUE_0"] = excludes
    for name, value in (extra or {}).items():
        if SENSITIVE_ENV_PATTERN.search(name):
            raise ValueError(f"donor subprocesses are never given a credential-shaped variable: {name}")
        env[name] = value
    return env


# Repository-local configuration can execute code during read-only Git commands, and no
# environment can prevent it: `.git/config` is read from the donor checkout itself. The one
# status/drift actually exercises is `core.fsmonitor`, whose value is an executable Git
# launches to watch the worktree -- a drift scan across seventy donors would otherwise run
# seventy arbitrary programs *inside this process's authority*, handing whatever the
# control plane holds (approval-store path, API credentials, agent sockets) to code the
# review never saw. Command-line `-c` overrides win over repo config, so these close the
# known executable surfaces without touching the values the fingerprint depends on.
_DONOR_GIT_CONFIG_OVERRIDES = (
    "-c", "core.fsmonitor=",       # empty disables the fsmonitor hook/builtin
    "-c", "credential.helper=",    # never let a read command reach a credential helper
)


def run_donor_git(
    repo_dir: Path,
    *args: str,
    timeout: float = 5.0,
    check: bool = False,
    binary: bool = False,
) -> subprocess.CompletedProcess:
    """Run Git inside a donor checkout under the minimal, non-executing donor environment.

    This is the one runner for every donor Git invocation -- drift inspection, baseline
    fingerprints, untracked enumeration -- so there is exactly one place where the
    environment boundary and the local-config neutralization are reviewed.

    Beyond :func:`donor_env`'s stripped environment, the command runs with:

    - ``--no-pager``, so output plumbing never spawns a pager process;
    - ``core.fsMonitor`` emptied, refusing repository-local fsmonitor hooks/executables;
    - ``credential.helper`` emptied, so even an accidental network-touching subcommand
      cannot execute a helper carrying credentials;
    - ``GIT_OPTIONAL_LOCKS=0``, keeping status refreshes from writing to the donor's index.

    Callers doing content comparison must pass ``--no-ext-diff``/``--no-textconv``
    themselves (they are command-specific options), which the drift patch command does.
    ``binary=True`` returns undecoded bytes, for NUL-delimited machine output.
    """
    command = [
        "git",
        "--no-pager",
        *_DONOR_GIT_CONFIG_OVERRIDES,
        "-C",
        str(repo_dir),
        *args,
    ]
    return subprocess.run(
        command,
        env=donor_env({"GIT_OPTIONAL_LOCKS": "0"}),
        capture_output=True,
        text=not binary,
        check=check,
        timeout=timeout,
    )

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
        head = run_donor_git(repo_dir, "rev-parse", "HEAD", check=True).stdout.strip()
        branch = run_donor_git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD", check=True).stdout.strip()
        status_raw = run_donor_git(repo_dir, "status", "--porcelain", check=True).stdout.strip()
        diff_raw = run_donor_git(
            repo_dir, "diff", "--no-ext-diff", "--no-textconv", "HEAD", check=True, binary=True
        ).stdout

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
