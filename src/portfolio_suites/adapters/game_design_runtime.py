"""Out-of-process runtime evidence for the Tucked in Terrors simulator."""

from __future__ import annotations

import collections
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..contracts import compute_sha256
from ..paths import SUITES_ROOT
from .common import donor_env, get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

DONOR_ROOT = get_repo_path("TuckdInTerrors_MonteCarloSim", "TUCKED_IN_TERRORS_DIR")
PROBE = Path(__file__).with_name("donor_tucked_in_terrors_probe.py")
OBJECTIVE = "OBJ01"
POLICY = "scoring_ai"
SIMULATIONS = 1000
SEED = 0
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
REQUIRED_MODULES = {
    "tuck_in_terrors_sim.cli",
    "tuck_in_terrors_sim.catalog",
    "tuck_in_terrors_sim.experiments",
}


def _runtime_source_files(root: Path) -> list[str]:
    paths = ["main.py", "pyproject.toml", "data/cards.json", "data/objectives.json"]
    package = root / "src" / "tuck_in_terrors_sim"
    try:
        paths.extend(
            path.relative_to(root).as_posix()
            for path in package.rglob("*.py")
            if path.is_file() and not path.is_symlink()
        )
    except OSError:
        pass
    return sorted(set(paths))


def _dependency_files(root: Path) -> list[str]:
    candidates = (
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
    )
    return [name for name in candidates if (root / name).is_file() and not (root / name).is_symlink()]


def _same_fingerprint(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = (
        "branch",
        "head",
        "is_dirty",
        "dirty_files_count",
        "dirty_files",
        "patch_sha256",
        "lockfile_sha256",
        "tested_files_fingerprint",
        "target_state",
    )
    return all(left.get(field) == right.get(field) for field in fields)


def _host_module_fingerprints(
    root: Path, reported: Any
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(reported, dict) or not reported:
        return {}, ["probe returned no imported donor module fingerprints"]
    verified: dict[str, dict[str, Any]] = {}
    package_root = (root / "src" / "tuck_in_terrors_sim").resolve()
    for name, value in sorted(reported.items()):
        if not isinstance(name, str) or not isinstance(value, dict):
            errors.append("probe returned a malformed module fingerprint")
            continue
        rel = value.get("path")
        donor_digest = value.get("sha256")
        if not isinstance(rel, str) or not rel.startswith("src/tuck_in_terrors_sim/"):
            errors.append(f"module {name} has a path outside the donor package")
            continue
        path = root / rel
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(package_root)
            if path.is_symlink() or not resolved.is_file() or resolved.suffix != ".py":
                raise ValueError("module path is not a regular Python source file")
            host_digest = compute_sha256(resolved.read_bytes())
        except (OSError, ValueError):
            errors.append(f"module {name} could not be safely fingerprinted by the host")
            continue
        agrees = isinstance(donor_digest, str) and host_digest == donor_digest
        verified[name] = {
            "path": rel,
            "donor_attested_sha256": donor_digest,
            "host_recomputed_sha256": host_digest,
            "agrees": agrees,
        }
        if not agrees:
            errors.append(f"host module digest disagrees for {name}")
    missing = sorted(REQUIRED_MODULES - set(verified))
    if missing:
        errors.append(f"probe did not import required simulator modules: {', '.join(missing)}")
    return verified, errors


def _host_summary(results: list[Any]) -> dict[str, Any] | None:
    if not results or not all(isinstance(row, dict) for row in results):
        return None
    valid = [row for row in results if row.get("valid") is True]
    outcomes = dict(sorted(collections.Counter(str(row.get("win_status")) for row in results).items()))
    wins = sum(
        isinstance(row.get("win_status"), str)
        and row["win_status"] in {"PRIMARY_WIN", "ALTERNATIVE_WIN"}
        for row in valid
    )
    losses = sum(
        isinstance(row.get("win_status"), str)
        and row["win_status"] == "LOSS_NIGHTFALL"
        for row in valid
    )
    return {
        "games": len(results),
        "valid_games": len(valid),
        "invalid_games": len(results) - len(valid),
        "wins": wins,
        "losses": losses,
        "outcomes": outcomes,
    }


def _canonical_objective(root: Path) -> str | None:
    path = root / "data" / "objectives.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None
        objectives = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(objectives, list):
        return None
    matches = [
        row.get("objective_id")
        for row in objectives
        if isinstance(row, dict)
        and isinstance(row.get("objective_id"), str)
        and row["objective_id"].startswith(OBJECTIVE)
    ]
    return matches[0] if len(matches) == 1 else None


def _summary_agrees(donor: Any, host: dict[str, Any] | None) -> bool:
    if not isinstance(donor, dict) or host is None:
        return False
    for key, value in host.items():
        if donor.get(key) != value:
            return False
    total = host["valid_games"]
    expected_rate = host["wins"] / total if total else None
    observed_rate = donor.get("win_rate")
    if expected_rate is None:
        return observed_rate is None
    return (
        isinstance(observed_rate, (int, float))
        and not isinstance(observed_rate, bool)
        and math.isclose(float(observed_rate), expected_rate, rel_tol=0, abs_tol=1e-12)
    )


def _historical_reference() -> dict[str, Any] | None:
    path = SUITES_ROOT / "game-design" / "evidence" / "G1-TUCKED-IN-TERRORS-FINGERPRINT.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None
        raw = path.read_bytes()
        old = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    fields = (
        "game_version_fingerprint",
        "game_version_dirty",
        "cards_sha256",
        "cards_count",
        "objectives_sha256",
        "objectives_count",
        "results_sha256",
        "recorded_runs",
        "objectives_exercised",
        "outcome_distribution",
        "metric_tolerances",
        "configuration",
    )
    return {
        "basis": "retained source-inspection receipt; not compared to the current runtime sample",
        "receipt_sha256": compute_sha256(raw),
        **{field: old[field] for field in fields if field in old},
    }


def _error(stage: str, kind: str, message: str) -> dict[str, str]:
    return {"stage": stage, "error_kind": kind, "message": message}


class GameDesignRuntimeAdapter:
    """Executes the donor simulator in a stripped child process and checks its claims."""

    @classmethod
    def execute_g1_tucked_in_terrors_runtime(cls) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        errors: list[dict[str, str]] = []
        donor = DONOR_ROOT
        source_files = _runtime_source_files(donor)
        dependency_files = _dependency_files(donor)
        source_before = get_git_fingerprint(donor, source_files)
        dependencies_before = get_git_fingerprint(donor, dependency_files)
        source_invocation: dict[str, Any] | None = None
        modules: dict[str, dict[str, Any]] = {}
        module_errors: list[str] = []
        probe_payload: dict[str, Any] = {}
        host_summary: dict[str, Any] | None = None
        output_sha256 = ""
        output_bytes = 0
        temp_root: Path | None = None
        temp_removed = False
        child_status = "not_invoked"
        command_template = [
            sys.executable,
            "-I",
            str(PROBE),
            str(donor),
            "--objective", OBJECTIVE,
            "--policy", POLICY,
            "--simulations", str(SIMULATIONS),
            "--seed", str(SEED),
            "--output-file", "<TEMP_DIR>/g1-output.json",
            "--database", "<TEMP_DIR>/g1.sqlite3",
        ]

        if not donor.is_dir() or not (donor / ".git").exists():
            errors.append(_error("donor", "donor_repository_unavailable", "the configured donor checkout is unavailable"))
        elif not PROBE.is_file() or PROBE.is_symlink():
            errors.append(_error("probe", "probe_unavailable", "the isolated runtime probe is unavailable"))
        elif not is_meaningful_git_fingerprint(source_before):
            errors.append(_error("source_fingerprint", "source_fingerprint_unavailable", "donor source fingerprint is incomplete"))
        elif not is_meaningful_git_fingerprint(dependencies_before):
            errors.append(_error("dependency_fingerprint", "dependency_fingerprint_unavailable", "donor dependency fingerprint is incomplete"))
        else:
            temp_base = Path(os.environ.get("TMPDIR") or "/private/tmp")
            if not temp_base.is_dir():
                temp_base = Path(tempfile.gettempdir())
            try:
                with tempfile.TemporaryDirectory(prefix="suites-g1-", dir=temp_base) as temporary:
                    temp_root = Path(temporary)
                    output_path = temp_root / "g1-output.json"
                    database_path = temp_root / "g1.sqlite3"
                    command = [
                        sys.executable,
                        "-I",
                        str(PROBE),
                        str(donor),
                        "--objective", OBJECTIVE,
                        "--policy", POLICY,
                        "--simulations", str(SIMULATIONS),
                        "--seed", str(SEED),
                        "--output-file", str(output_path),
                        "--database", str(database_path),
                    ]
                    env = donor_env({
                        "TMPDIR": str(temp_root),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    })
                    if "HOME" in env or "PYTHONPATH" in env:
                        errors.append(_error("environment", "donor_environment_not_isolated", "HOME and PYTHONPATH must be absent"))
                    else:
                        invocation_started = time.monotonic()
                        try:
                            completed = subprocess.run(
                                command,
                                cwd=str(donor),
                                env=env,
                                capture_output=True,
                                text=True,
                                timeout=180,
                                check=False,
                            )
                            duration_ms = max(0.0, (time.monotonic() - invocation_started) * 1000)
                            source_invocation = {
                                "command": command,
                                "exit_code": completed.returncode,
                                "duration_ms": round(duration_ms, 2),
                                "working_directory": str(donor),
                                "environment_policy": "donor_env; HOME and PYTHONPATH withheld; temporary outputs outside donor",
                            }
                            lines = completed.stdout.splitlines()
                            if len(lines) != 1:
                                errors.append(_error("probe_output", "invalid_probe_output", "runtime probe must emit exactly one JSON line"))
                            else:
                                parsed = json.loads(lines[0])
                                if isinstance(parsed, dict):
                                    probe_payload = parsed
                                else:
                                    errors.append(_error("probe_output", "invalid_probe_output", "runtime probe JSON must be an object"))
                            child_status = str(probe_payload.get("status") or "invalid_probe_output")
                            if completed.returncode != 0:
                                kind = "donor_import_failed" if completed.returncode == 3 else "donor_runtime_failed"
                                errors.append(_error("source_invocation", kind, f"isolated donor invocation exited {completed.returncode}"))
                            elif child_status != "completed" or probe_payload.get("exit_code") != 0:
                                errors.append(_error("source_invocation", "donor_runtime_failed", "donor CLI did not report a successful run"))
                            modules, module_errors = _host_module_fingerprints(donor, probe_payload.get("module_fingerprints"))
                            errors.extend(_error("module_fingerprints", "module_digest_unverified", item) for item in module_errors)

                            if output_path.is_symlink() or not output_path.is_file():
                                errors.append(_error("output", "runtime_output_missing", "donor did not produce the requested JSON output"))
                            else:
                                output_bytes = output_path.stat().st_size
                                if output_bytes <= 0 or output_bytes > MAX_OUTPUT_BYTES:
                                    errors.append(_error("output", "runtime_output_size_invalid", "donor JSON output is empty or exceeds the configured size limit"))
                                else:
                                    raw_output = output_path.read_bytes()
                                    output_sha256 = compute_sha256(raw_output)
                                    try:
                                        output_document = json.loads(raw_output.decode("utf-8"))
                                    except (UnicodeDecodeError, json.JSONDecodeError):
                                        output_document = None
                                        errors.append(_error("output", "runtime_output_invalid", "donor JSON output is not valid UTF-8 JSON"))
                                    if not isinstance(output_document, dict):
                                        errors.append(_error("output", "runtime_output_invalid", "donor output must be a completed experiment object"))
                                    else:
                                        manifest = output_document.get("manifest")
                                        results = output_document.get("results")
                                        host_summary = _host_summary(results) if isinstance(results, list) else None
                                        donor_summary = output_document.get("summary")
                                        canonical_objective = _canonical_objective(donor)
                                        if output_document.get("status") != "completed":
                                            errors.append(_error("output", "experiment_incomplete", "donor experiment status is not completed"))
                                        if not isinstance(manifest, dict) or (
                                            canonical_objective is None
                                            or manifest.get("objective") != canonical_objective
                                            or manifest.get("policy") != POLICY
                                            or manifest.get("games") != SIMULATIONS
                                            or manifest.get("seed") != SEED
                                        ):
                                            errors.append(_error("output", "experiment_input_mismatch", "donor output manifest does not match the requested representative input"))
                                        if host_summary is None or not _summary_agrees(donor_summary, host_summary):
                                            errors.append(_error("host_recompute", "summary_mismatch", "host-recomputed results do not agree with the donor summary"))
                                        elif host_summary["games"] != SIMULATIONS or host_summary["invalid_games"] != 0:
                                            errors.append(_error("host_recompute", "invalid_simulation_results", "the complete sample must contain 1,000 valid games and no invalid games"))
                                        if output_document.get("finished_games") != SIMULATIONS:
                                            errors.append(_error("output", "experiment_incomplete", "donor output did not retain all requested games"))
                        except subprocess.TimeoutExpired:
                            duration_ms = max(0.0, (time.monotonic() - invocation_started) * 1000)
                            source_invocation = {
                                "command": command,
                                "exit_code": -1,
                                "duration_ms": round(duration_ms, 2),
                                "working_directory": str(donor),
                                "environment_policy": "donor_env; HOME and PYTHONPATH withheld; temporary outputs outside donor",
                            }
                            errors.append(_error("source_invocation", "donor_runtime_timeout", "isolated donor invocation exceeded 180 seconds"))
                        except (OSError, json.JSONDecodeError) as error:
                            errors.append(_error("source_invocation", type(error).__name__, "isolated donor invocation could not be verified"))
            except OSError as error:
                errors.append(_error("temporary_workspace", type(error).__name__, "temporary runtime workspace could not be created or removed"))
            temp_removed = temp_root is not None and not temp_root.exists()

        source_after = get_git_fingerprint(donor, source_files)
        dependencies_after = get_git_fingerprint(donor, dependency_files)
        source_unchanged = _same_fingerprint(source_before, source_after)
        dependencies_unchanged = _same_fingerprint(dependencies_before, dependencies_after)
        if not source_unchanged:
            errors.append(_error("recovery", "donor_source_changed", "donor working tree fingerprint changed during the runtime gate"))
        if not dependencies_unchanged:
            errors.append(_error("recovery", "donor_dependencies_changed", "donor dependency fingerprint changed during the runtime gate"))
        if not temp_removed:
            errors.append(_error("recovery", "temporary_outputs_not_removed", "temporary simulation outputs were not removed"))

        data_fingerprints = source_before.get("tested_files_fingerprint", {})
        historical = _historical_reference()
        all_stages_passed = not errors and bool(source_invocation) and bool(modules) and host_summary is not None
        environment_blocked = any(
            item.get("error_kind") in {"donor_import_failed", "FileNotFoundError", "PermissionError"}
            for item in errors
        )
        gate_summary = {
            "environment_blocked": environment_blocked,
            "donor_status": child_status,
            "requested_simulations": SIMULATIONS,
            "completed_games": host_summary.get("games", 0) if host_summary else 0,
            "invalid_games": host_summary.get("invalid_games", 0) if host_summary else 0,
            "output_sha256": output_sha256,
            "operational_error_count": len(errors),
        }
        finished_at = datetime.now(timezone.utc).isoformat()
        receipt = {
            "receipt_version": "portfolio-runtime-source-v1",
            "wave_id": "G1",
            "donor": "tucked-in-terrors",
            "status": "source_executed" if all_stages_passed else "source_unverified",
            "all_stages_passed": all_stages_passed,
            "environment_blocked": environment_blocked,
            "source_invocation_status": "invoked" if source_invocation is not None else "not_invoked",
            "source_invocation": source_invocation,
            "planned_source_invocation": {
                "command": command_template,
                "working_directory": str(donor),
                "environment_policy": "donor_env; HOME and PYTHONPATH withheld; temporary outputs outside donor",
            },
            "started_at": started_at,
            "finished_at": finished_at,
            "source_fingerprints": {"tucked_in_terrors": source_before},
            "dependency_fingerprints": {"tucked_in_terrors": dependencies_before},
            "module_fingerprints": modules,
            "tool_dependencies": {
                "host_python": platform.python_version(),
                "host_implementation": platform.python_implementation(),
                "donor_python": str(probe_payload.get("python_version") or "unreported"),
                "donor_implementation": str(probe_payload.get("python_implementation") or "unreported"),
                "donor_probe_sha256": compute_sha256(PROBE.read_bytes()) if PROBE.is_file() else "0" * 64,
                "donor_cli_sha256": str(data_fingerprints.get("src/tuck_in_terrors_sim/cli.py") or "0" * 64),
                "donor_manifest_sha256": str(data_fingerprints.get("pyproject.toml") or "0" * 64),
            },
            "representative_inputs": [
                {
                    "kind": "simulation_request",
                    "objective_alias": OBJECTIVE,
                    "objective_id": _canonical_objective(donor) or "unresolved",
                    "policy": POLICY,
                    "simulations": SIMULATIONS,
                    "seed": SEED,
                },
                {
                    "kind": "rules_catalog",
                    "cards_sha256": data_fingerprints.get("data/cards.json", ""),
                    "objectives_sha256": data_fingerprints.get("data/objectives.json", ""),
                },
                {
                    "kind": "simulation_runtime",
                    "donor_python": str(probe_payload.get("python_version") or "unreported"),
                    "donor_implementation": str(probe_payload.get("python_implementation") or "unreported"),
                },
            ],
            "host_recomputed_claims": {
                "requested_simulations": SIMULATIONS,
                "completed_games": host_summary.get("games", 0) if host_summary else 0,
                "valid_games": host_summary.get("valid_games", 0) if host_summary else 0,
                "invalid_games": host_summary.get("invalid_games", 0) if host_summary else 0,
                "outcome_counts": host_summary.get("outcomes", {}) if host_summary else {},
                "donor_summary_agrees": host_summary is not None and not any(
                    item["error_kind"] == "summary_mismatch" for item in errors
                ),
                "output_sha256": output_sha256 or "0" * 64,
                "output_bytes": output_bytes,
                "module_digest_agreement_count": sum(1 for item in modules.values() if item.get("agrees") is True),
                "module_count": len(modules),
                "source_fingerprint_unchanged": source_unchanged,
                "dependency_fingerprint_unchanged": dependencies_unchanged,
                "temporary_outputs_removed": temp_removed,
                "donor_status": child_status,
            },
            "run_summary": host_summary or {},
            "gate_summary": gate_summary,
            "historical_analysis_reference": historical,
            "reproducible_commands": [command_template],
            "recovery_behavior": {
                "runtime_mutation_mode": "temporary_workspace_only",
                "permanent_donor_write": False,
                "donor_working_tree_unchanged": source_unchanged,
                "temporary_outputs_removed": temp_removed,
                "rerun_safe": source_unchanged and dependencies_unchanged and temp_removed,
                "environment_failures_fail_closed": True,
                "evidence_write_requires_explicit_record": True,
            },
            "privacy_redaction": {
                "raw_game_results_retained": False,
                "credentials_retained": False,
                "command_arguments_reviewed": True,
            },
            "operational_errors": errors,
        }
        return receipt
