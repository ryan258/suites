"""Source adapter for Operator OS connecting dotfiles, PKos, Observer, JARVIS, and Ryos."""

from __future__ import annotations

import datetime
import json
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256, validate_contract
from ..engines.operator_os import OperatorOSEngine
from ..execution_trace import validate_execution_trace
from ..recovery_program import (
    RecoveryProgramError,
    get_recovery_trace_context,
    load_recovery_program,
)
from .common import (
    SUITES_ROOT,
    donor_env,
    donor_file_record,
    get_git_fingerprint,
    get_repo_path,
    is_meaningful_git_fingerprint,
    read_donor_text,
)

DONOR_PKOS_CAS_PROBE = Path(__file__).with_name("donor_pkos_cas_probe.py")
PROBE_EXIT_IMPORT_FAILED = 3  # keep in sync with donor_pkos_cas_probe.EXIT_IMPORT_FAILED

DOTFILES_DIR = get_repo_path("dotfiles", "DOTFILES_DIR")
PKOS_DIR = get_repo_path("PKos", "PKOS_DIR")
OBSERVER_DIR = get_repo_path("obsidian-observer", "OBSERVER_DIR")
JARVIS_DIR = get_repo_path("jarvis", "JARVIS_DIR")
RYOS_DIR = get_repo_path("ryos", "RYOS_DIR")
MASTER_UPGRADE_PLAN_DIR = get_repo_path("master-upgrade-plan", "MASTER_UPGRADE_PLAN_DIR")


def _verified_module_fingerprints(reported: Any) -> dict[str, dict[str, Any]]:
    """Re-hash each module the donor says it imported, host-side, and record whether it agrees.

    The donor computing and attesting its own digest proves nothing (AGENTS.md 3.7), so the
    digest that counts is the one this process computes. A path outside PKos is dropped
    rather than hashed: the donor names the file, it does not get to choose which file the
    host opens.
    """
    verified: dict[str, dict[str, Any]] = {}
    if not isinstance(reported, dict):
        return verified
    for name, record in reported.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            continue
        raw_path = record.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        path = Path(raw_path)
        try:
            relative = path.resolve().relative_to(PKOS_DIR.resolve())
        except (OSError, ValueError):
            continue
        host_record = donor_file_record(path, PKOS_DIR)
        attested = record.get("sha256")
        host_sha = host_record.get("sha256") if host_record else None
        verified[name] = {
            "path": str(relative).replace("\\", "/"),
            "donor_attested_sha256": attested if isinstance(attested, str) else None,
            "host_recomputed_sha256": host_sha,
            "agrees": bool(host_sha) and host_sha == attested,
        }
    return verified


def _o1_ungoverned_candidate(
    operational_errors: list[dict[str, Any]],
    error: RecoveryProgramError,
) -> dict[str, Any]:
    """Fail closed when the governed recovery route cannot be resolved at all."""
    candidate_errors = list(operational_errors) + [{
        "stage": "recovery_trace_context",
        "command": "get_recovery_trace_context",
        "error_kind": "recovery_program_unavailable",
        "message": str(error),
        "environment_blocked": True,
    }]
    return {
        "candidate_only": False,
        "promotion_eligible": False,
        "status": "source_unverified",
        "all_stages_passed": False,
        "blocked_owner_gate": None,
        "adoption_ceiling": ["governed_recovery_route_unavailable"],
        "receipt_contract": None,
        "receipt_contract_candidate": {
            "receipt_version": None,
            "status": "source_unverified",
            "all_stages_passed": False,
            "operational_errors": candidate_errors,
        },
        "execution_trace": None,
        "execution_trace_errors": [str(error)],
    }


def _o1_runtime_candidate(
    *,
    started_at: str,
    finished_at: str,
    command: list[str],
    invocation_attempted: bool,
    exit_code: int | None,
    duration_ms: float,
    module_fingerprints: dict[str, dict[str, Any]],
    donor_interpreter: dict[str, Any],
    all_stages_passed: bool,
    dotfiles_fingerprint: dict[str, Any],
    pkos_fingerprint: dict[str, Any],
    observer_fingerprint: dict[str, Any],
    source_record: dict[str, Any],
    cas_acquisition: dict[str, Any],
    normalize_counts: dict[str, int],
    operational_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an ephemeral runtime candidate without promoting or recording O1."""
    try:
        recovery_program = load_recovery_program()
        trace_context = get_recovery_trace_context(
            recovery_program,
            adapter="OperatorOSSourceAdapter",
            action="execute_o1_source_record_observer_gate",
        )
    except RecoveryProgramError as error:
        # An unreadable program or a route that stopped being unique is a governance
        # failure, not a gate crash. Every other failure in this adapter lands in
        # operational_errors, and a traceback here would report it as a broken runner.
        return _o1_ungoverned_candidate(operational_errors, error)
    trace_route = trace_context["trace_route"]
    plan_document = {
        "obligation_id": trace_context["obligation_id"],
        "planned_command": command,
        "adapter": trace_route["adapter"],
        "action": trace_route["action"],
        "mutation_mode": "temporary_workspace_only",
    }
    plan_sha256 = compute_sha256(
        json.dumps(plan_document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    source_invocation = (
        {
            "command": command,
            "exit_code": exit_code,
            "duration_ms": round(duration_ms, 2),
            "working_directory": str(PKOS_DIR),
            "environment_policy": "donor_env_with_explicit_pkos_pythonpath",
        }
        if invocation_attempted
        else None
    )
    candidate_errors = list(operational_errors)
    runtime_receipt = {
        "receipt_version": trace_context["receipt_contract"],
        "status": "source_executed" if all_stages_passed else "source_unverified",
        "all_stages_passed": all_stages_passed,
        "source_invocation_status": (
            "invoked" if invocation_attempted else "not_invoked"
        ),
        "source_invocation": source_invocation,
        "planned_source_invocation": {
            "command": command,
            "working_directory": str(PKOS_DIR),
            "environment_policy": "donor_env_with_explicit_pkos_pythonpath",
        },
        "source_fingerprints": {"dotfiles": dotfiles_fingerprint},
        "dependency_fingerprints": {
            "PKos": pkos_fingerprint,
            "obsidian-observer": observer_fingerprint,
        },
        "module_fingerprints": module_fingerprints,
        "tool_dependencies": {
            "host_python": platform.python_version(),
            "host_implementation": platform.python_implementation(),
            "donor_python": str(donor_interpreter.get("python") or "unreported"),
            "donor_implementation": str(
                donor_interpreter.get("implementation") or "unreported"
            ),
            "donor_probe_sha256": compute_sha256(
                DONOR_PKOS_CAS_PROBE.read_bytes()
            ),
        },
        "reproducible_commands": [command],
        "host_recomputed_claims": {
            "source_sha256": source_record.get("sha256"),
            "cas_sha256": cas_acquisition.get("sha256"),
            "cas_sha256_matches_source": bool(source_record.get("sha256"))
            and source_record.get("sha256") == cas_acquisition.get("sha256"),
            "normalized_items": normalize_counts.get("items", 0),
            "normalized_chunks": normalize_counts.get("chunks", 0),
        },
        "recovery_behavior": {
            "runtime_mutation_mode": "temporary_workspace_only",
            "permanent_vault_written": False,
            "partial_permanent_state_possible": False,
            "rerun_safe": True,
            "environment_failures_fail_closed": True,
            "evidence_write_requires_explicit_record": True,
        },
        "privacy_redaction": {
            "raw_source_content_retained": False,
            "credentials_retained": False,
            "command_arguments_reviewed": True,
        },
        "operational_errors": candidate_errors,
    }
    outcome = "passed" if all_stages_passed else "failed"
    error_class = None
    if not all_stages_passed:
        error_class = str(
            (operational_errors[0].get("error_kind") if operational_errors else None)
            or "source_verification_failed"
        )
    execution_trace = {
        "trace_version": "portfolio-execution-trace-v1",
        "trace_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "obligation_id": trace_context["obligation_id"],
        "journey_id": trace_context["journey_id"],
        "actor_class": "control_plane",
        "purpose": "runtime_recovery_verification",
        "ontology_version": trace_route["ontology_version"],
        "mapping_version": trace_route["mapping_version"],
        "resolved_mappings": trace_route["resolved_mappings"],
        "candidate_authorities": trace_route["candidate_authorities"],
        "selected_authority": trace_route["selected_authority"],
        "policy_decisions": trace_route["policy_decisions"],
        "adapter": trace_route["adapter"],
        "plan_sha256": plan_sha256,
        "source_fingerprints": {
            "dotfiles": dotfiles_fingerprint,
            "PKos": pkos_fingerprint,
            "obsidian-observer": observer_fingerprint,
        },
        "started_at": started_at,
        "finished_at": finished_at,
        "outcome": outcome,
        "error_class": error_class,
        "fallback_used": False,
        "receipt_ref": None,
        "privacy": {
            "redacted": True,
            "raw_source_retained": False,
            "secrets_retained": False,
        },
    }
    trace_errors = validate_execution_trace(
        execution_trace,
        recovery_program,
    )
    candidate_passed = all_stages_passed and not trace_errors
    if trace_errors:
        candidate_errors.append({
            "stage": "execution_trace_validation",
            "command": "validate_execution_trace",
            "error_kind": "invalid_execution_trace",
            "message": "; ".join(trace_errors),
            "environment_blocked": False,
        })
        execution_trace["outcome"] = "failed"
        execution_trace["error_class"] = "invalid_execution_trace"
        runtime_receipt["status"] = "source_unverified"
        runtime_receipt["all_stages_passed"] = False
    owner_gate = trace_context["owner_gate"]
    # These bound the *adoption* rung, not this one. The invocation is proven by the argv,
    # exit code, duration, and host-recomputed module digests the receipt retains; scaling
    # real intake into the permanent vault is what the next claim needs, and it has its own
    # owner-gated obligation now rather than living as a footnote on this receipt.
    adoption_ceiling = [
        "permanent_vault_write_not_authorized_or_attempted",
        "day_to_day_intake_adoption_not_accumulated",
    ]
    return {
        "candidate_only": False,
        "promotion_eligible": candidate_passed,
        "status": "source_executed" if candidate_passed else "source_unverified",
        "all_stages_passed": candidate_passed,
        "blocked_owner_gate": owner_gate,
        "adoption_ceiling": adoption_ceiling,
        "receipt_contract": trace_context["receipt_contract"],
        "receipt_contract_candidate": runtime_receipt,
        "execution_trace": execution_trace,
        "execution_trace_errors": trace_errors,
    }

RYOS_DISPOSITION_CATALOG: list[dict[str, str]] = [
    {
        "donor_project": "ryos",
        "source_file": "core/startday.sh",
        "feature": "Morning brief generator and environment check",
        "disposition": "port_to_dotfiles",
        "target": "dotfiles/bin/startday",
        "canonical_anchor": "dotfiles",
    },
    {
        "donor_project": "ryos",
        "source_file": "core/goodevening.sh",
        "feature": "Evening shutdown and session archiving",
        "disposition": "port_to_dotfiles",
        "target": "dotfiles/bin/goodevening",
        "canonical_anchor": "dotfiles",
    },
    {
        "donor_project": "ryos",
        "source_file": "core/status.sh",
        "feature": "System and daemon status check",
        "disposition": "port_to_dotfiles",
        "target": "dotfiles/scripts/status_daemon.sh",
        "canonical_anchor": "dotfiles",
    },
    {
        "donor_project": "ryos",
        "source_file": "core/modules.sh",
        "feature": "Dynamic bash module loader",
        "disposition": "port_to_dotfiles",
        "target": "dotfiles/functions/modules.zsh",
        "canonical_anchor": "dotfiles",
    },
    {
        "donor_project": "ryos",
        "source_file": "core/hook_weights.conf",
        "feature": "Priority weighting for operator hooks",
        "disposition": "port_to_dotfiles",
        "target": "dotfiles/config/hook_weights.conf",
        "canonical_anchor": "dotfiles",
    },
    {
        "donor_project": "master-upgrade-plan",
        "source_file": "v0.md - v3.md",
        "feature": "Cross-repo multi-horizon roadmap documentation",
        "disposition": "superseded_by_suites_bible",
        "target": "suites/docs/ROADMAP.md",
        "canonical_anchor": "suites",
    },
    {
        "donor_project": "CoOS",
        "source_file": "README.md",
        "feature": "Ad-hoc task tracking and unstructured states",
        "disposition": "rejected",
        "target": "N/A (Replaced by PKos SourceRecord architecture)",
        "canonical_anchor": "PKos",
    },
]


class OperatorOSSourceAdapter:
    """Invokes and inspects authentic dotfiles, PKos, Observer, JARVIS, and Ryos runtimes."""

    @classmethod
    def execute_o1_source_record_observer_gate(cls) -> dict[str, Any]:
        """Execute O1 wave gate: acquire live dotfiles into authentic PKos CAS, normalize into SQLite, and project to Observer."""
        dotfiles_fp = get_git_fingerprint(DOTFILES_DIR)
        pkos_fp = get_git_fingerprint(PKOS_DIR)
        observer_fp = get_git_fingerprint(OBSERVER_DIR)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        started_at = now_iso

        # Verify live files on disk in PKos and Observer
        has_pkos_normalize = (PKOS_DIR / "pkos" / "normalize.py").is_file()
        has_pkos_storage = (PKOS_DIR / "pkos" / "storage.py").is_file()
        has_observer_script = (OBSERVER_DIR / "scripts" / "observer.py").is_file()
        agents_path = DOTFILES_DIR / "AGENTS.md"
        has_agents = agents_path.is_file()

        cas_acquisition: dict[str, Any] = {}
        normalize_counts: dict[str, int] = {}
        operational_errors: list[dict[str, Any]] = []
        cas_verified = False
        donor_cas_cmd = [sys.executable, str(DONOR_PKOS_CAS_PROBE), str(agents_path)]
        donor_exit_code: int | None = None
        donor_duration_ms = 0.0
        donor_invocation_attempted = False
        module_fingerprints: dict[str, dict[str, Any]] = {}
        donor_interpreter: dict[str, Any] = {}

        if not has_agents:
            operational_errors.append({
                "stage": "donor_acquisition",
                "command": f"read {agents_path}",
                "error_kind": "missing_donor_file",
                "message": "dotfiles/AGENTS.md is not present; nothing to acquire into CAS.",
                "environment_blocked": False,
            })
        if not (has_pkos_storage and has_pkos_normalize):
            operational_errors.append({
                "stage": "cas_acquisition",
                "command": f"import pkos.storage, pkos.normalize from {PKOS_DIR}",
                "error_kind": "missing_destination_module",
                "message": "PKos storage or normalize module is not present on disk.",
                "environment_blocked": False,
            })

        if has_agents and has_pkos_storage and has_pkos_normalize:
            donor_started = time.perf_counter()
            donor_invocation_attempted = True
            try:
                proc = subprocess.run(
                    donor_cas_cmd,
                    cwd=PKOS_DIR,
                    env=donor_env({"PYTHONPATH": str(PKOS_DIR)}),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                donor_duration_ms = (time.perf_counter() - donor_started) * 1000.0
                donor_exit_code = proc.returncode
                if proc.returncode == 0 and proc.stdout.strip():
                    last_line = proc.stdout.strip().splitlines()[-1]
                    payload = json.loads(last_line)
                    cas_acquisition = payload.get("acquired_record") or {}
                    normalize_counts = payload.get("counts", {})
                    raw_bytes_match = payload.get("raw_bytes_match", False)
                    module_fingerprints = _verified_module_fingerprints(
                        payload.get("modules")
                    )
                    reported_interpreter = payload.get("interpreter")
                    donor_interpreter = (
                        reported_interpreter
                        if isinstance(reported_interpreter, dict)
                        else {}
                    )
                    modules_agree = bool(module_fingerprints) and all(
                        record["agrees"] for record in module_fingerprints.values()
                    )
                    if not modules_agree:
                        # The receipt's whole claim is "these modules ran". A digest the host
                        # cannot reproduce means the receipt would name a file that is not the
                        # one that executed, which is worse than recording no claim at all.
                        operational_errors.append({
                            "stage": "module_fingerprints",
                            "command": "host recompute of imported pkos modules",
                            "error_kind": "module_fingerprint_disagreement",
                            "message": (
                                "donor-attested module digests do not match the host "
                                "recomputation, or no imported module was reported."
                            ),
                            "environment_blocked": False,
                        })

                    # Independent parent-side cross-check: donor CAS sha256 matches actual file bytes
                    agents_bytes = agents_path.read_bytes() if has_agents else b""
                    parent_sha = compute_sha256(agents_bytes)
                    sha_cross_check = (
                        bool(cas_acquisition.get("sha256"))
                        and cas_acquisition.get("sha256") == parent_sha
                    )

                    cas_verified = (
                        raw_bytes_match
                        and sha_cross_check
                        and modules_agree
                        and normalize_counts.get("acquisitions", 0) >= 1
                        and normalize_counts.get("items", 0) >= 1
                        and normalize_counts.get("chunks", 0) >= 1
                        and normalize_counts.get("failures", 0) == 0
                    )
                else:
                    cas_verified = False
                    # The probe exits 3 only when PKos itself would not import. Reporting that
                    # as a plain non-zero exit would read as "the donor API changed" on a
                    # machine that simply cannot load the donor.
                    import_failed = proc.returncode == PROBE_EXIT_IMPORT_FAILED
                    operational_errors.append({
                        "stage": "cas_acquisition",
                        "command": f"{sys.executable} {DONOR_PKOS_CAS_PROBE.name} {agents_path}",
                        "error_kind": "donor_import_failed" if import_failed else "non_zero_exit",
                        "message": (proc.stderr or proc.stdout)[:500],
                        "environment_blocked": import_failed,
                    })
            except Exception as exc:
                donor_duration_ms = (time.perf_counter() - donor_started) * 1000.0
                # A silent False here would report a red wave with no way to tell a PKos API
                # change from a broken donor file. Record why, the way A2 does.
                cas_verified = False
                operational_errors.append({
                    "stage": "cas_acquisition",
                    "command": f"{sys.executable} {DONOR_PKOS_CAS_PROBE.name} {agents_path}",
                    "error_kind": type(exc).__name__,
                    "message": str(exc),
                    "environment_blocked": isinstance(exc, (ImportError, ModuleNotFoundError)),
                })

        donor_content = agents_path.read_text(encoding="utf-8") if has_agents else ""
        src_id = "src-dotfiles-agents-md"
        origin = "dotfiles://AGENTS.md"

        src_record = OperatorOSEngine.capture_source(
            content=donor_content,
            origin=origin,
            source_id=src_id,
            media_type="text/markdown",
            author="Ryan",
            collector="pkos.storage.Workspace",
        )

        projection = OperatorOSEngine.project_to_observer(
            source_record=src_record,
            title="Dotfiles Operator Policy Projection",
            summary="Canonical agent rules and operator boundaries captured from dotfiles/AGENTS.md into PKos CAS.",
            body=donor_content,
        )

        # Non-tautological mutation protection verification using genuine engine validators
        # 1. Corrupt sha256 fails contract validation
        corrupted_record = dict(src_record)
        corrupted_record["sha256"] = "bad" * 16
        try:
            validate_contract("SourceRecord", corrupted_record)
            corrupt_sha_rejected = False
        except Exception:
            corrupt_sha_rejected = True

        # 2. Mutated projection missing fence comment fails validate_observer_projection
        no_fence_proj = projection.replace("<!-- FENCE: DO NOT RE-INGEST INTO PKOS CANONICAL CORPUS -->", "")
        no_fence_valid, _ = OperatorOSEngine.validate_observer_projection(no_fence_proj, src_record)
        no_fence_rejected = (no_fence_valid is False)

        # 3. Mutated projection missing source citation fails validate_observer_projection
        no_cite_proj = projection.replace(src_id, "src-unknown-other")
        no_cite_valid, _ = OperatorOSEngine.validate_observer_projection(no_cite_proj, src_record)
        no_cite_rejected = (no_cite_valid is False)

        # 4. Anti-reingestion fence detector catches projected note and blocks raw ingestion
        fence_detected = OperatorOSEngine.detect_reingestion_violation(projection)
        try:
            OperatorOSEngine.capture_source(projection, origin, "src-reingest-attempt")
            reingest_blocked = False
        except ValueError:
            reingest_blocked = True

        mutation_checks_passed = (
            corrupt_sha_rejected
            and no_fence_rejected
            and no_cite_rejected
            and fence_detected
            and reingest_blocked
        )
        sources_verified = (
            is_meaningful_git_fingerprint(dotfiles_fp)
            and is_meaningful_git_fingerprint(pkos_fp)
            and is_meaningful_git_fingerprint(observer_fp)
            and has_pkos_normalize
            and has_pkos_storage
            and has_observer_script
            and has_agents
            and cas_verified
        )
        all_stages_passed = mutation_checks_passed and sources_verified and cas_verified

        sensitivity_passed = (
            cas_verified
            and is_meaningful_git_fingerprint(dotfiles_fp)
            and is_meaningful_git_fingerprint(pkos_fp)
            and is_meaningful_git_fingerprint(observer_fp)
            and bool(cas_acquisition.get("sha256"))
            and normalize_counts.get("items", 0) >= 1
        )

        source_derived_assertions = {
            "donor_source_path": "dotfiles/AGENTS.md",
            "donor_sha256": src_record["sha256"],
            "donor_bytes": src_record["size_bytes"],
            "cas_object_path": cas_acquisition.get("raw_object", ""),
            "sqlite_normalized_items": normalize_counts.get("items", 0),
            "sqlite_normalized_chunks": normalize_counts.get("chunks", 0),
            "sensitivity_test_passed": sensitivity_passed,
        }
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        runtime_candidate = _o1_runtime_candidate(
            started_at=started_at,
            finished_at=finished_at,
            command=donor_cas_cmd,
            invocation_attempted=donor_invocation_attempted,
            exit_code=donor_exit_code,
            duration_ms=donor_duration_ms,
            module_fingerprints=module_fingerprints,
            donor_interpreter=donor_interpreter,
            all_stages_passed=all_stages_passed,
            dotfiles_fingerprint=dotfiles_fp,
            pkos_fingerprint=pkos_fp,
            observer_fingerprint=observer_fp,
            source_record=src_record,
            cas_acquisition=cas_acquisition,
            normalize_counts=normalize_counts,
            operational_errors=operational_errors,
        )
        candidate_passed = runtime_candidate["all_stages_passed"]
        reported_operational_errors = runtime_candidate[
            "receipt_contract_candidate"
        ]["operational_errors"]

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O1",
            "executed_at": now_iso,
            "status": (
                "cas_projection_verified" if candidate_passed else "source_unverified"
            ),
            "source_record": src_record,
            "cas_acquisition": cas_acquisition,
            "observer_projection_preview": projection,
            "source_derived_assertions": source_derived_assertions,
            "runtime_candidate": runtime_candidate,
            "all_stages_passed": candidate_passed,
            "cas_verified": cas_verified,
            "operational_errors": reported_operational_errors,
            "source_verification_passed": sources_verified,
            "mutation_protection_passed": mutation_checks_passed,
            "mutation_cases": {
                "corrupt_sha_rejected": corrupt_sha_rejected,
                "no_fence_rejected": no_fence_rejected,
                "no_citation_rejected": no_cite_rejected,
                "anti_reingestion_fence_detected": fence_detected,
                "reingestion_intake_blocked": reingest_blocked,
            },
            "donor": {
                "name": "dotfiles",
                "path": str(DOTFILES_DIR),
                "fingerprint": dotfiles_fp,
                "source_file": "AGENTS.md",
            },
            "target": {
                "pkos_name": "PKos",
                "pkos_path": str(PKOS_DIR),
                "pkos_fingerprint": pkos_fp,
                "observer_name": "obsidian-observer",
                "observer_path": str(OBSERVER_DIR),
                "observer_fingerprint": observer_fp,
            },
        }

    @classmethod
    def execute_o2_ryos_inventory(cls) -> dict[str, Any]:
        """Execute O2 wave inventory: inspect live Ryos and master-upgrade-plan against dotfiles/Observer."""
        ryos_fp = get_git_fingerprint(RYOS_DIR)
        master_plan_fp = get_git_fingerprint(MASTER_UPGRADE_PLAN_DIR)
        dotfiles_fp = get_git_fingerprint(DOTFILES_DIR)
        observer_fp = get_git_fingerprint(OBSERVER_DIR)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Inspect real ryos core files
        ryos_items: list[dict[str, Any]] = []
        core_dir = RYOS_DIR / "core"
        if core_dir.exists():
            for item in sorted(core_dir.iterdir()):
                if item.is_file():
                    data = item.read_bytes()
                    ryos_items.append({
                        "filename": item.name,
                        "relative_path": f"core/{item.name}",
                        "sha256": compute_sha256(data),
                        "size_bytes": len(data),
                        "kind": "script" if item.name.endswith(".sh") else "config",
                    })

        # Inspect real master-upgrade-plan files
        master_plan_items: list[dict[str, Any]] = []
        if MASTER_UPGRADE_PLAN_DIR.exists():
            for item in sorted(MASTER_UPGRADE_PLAN_DIR.glob("*.md")):
                data = item.read_bytes()
                master_plan_items.append({
                    "filename": item.name,
                    "sha256": compute_sha256(data),
                    "size_bytes": len(data),
                })

        sources_verified = all(
            is_meaningful_git_fingerprint(fingerprint)
            for fingerprint in (ryos_fp, master_plan_fp, dotfiles_fp, observer_fp)
        )
        all_stages_passed = (
            sources_verified
            and len(ryos_items) >= 3
            and len(master_plan_items) >= 1
            and len(RYOS_DISPOSITION_CATALOG) >= 5
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O2",
            "executed_at": now_iso,
            "fingerprints": {
                "ryos": ryos_fp,
                "master_upgrade_plan": master_plan_fp,
                "dotfiles": dotfiles_fp,
                "obsidian_observer": observer_fp,
            },
            "ryos_core_files_count": len(ryos_items),
            "ryos_core_files": ryos_items,
            "master_plan_files_count": len(master_plan_items),
            "master_plan_files": master_plan_items,
            "inventory_catalog_count": len(RYOS_DISPOSITION_CATALOG),
            "inventory_catalog": RYOS_DISPOSITION_CATALOG,
            "canonical_anchors_confirmed": {
                "system_runtime": "dotfiles",
                "knowledge_corpus": "PKos",
                "projection_view": "Observer",
                "orchestration_gateway": "JARVIS",
            },
            "all_stages_passed": all_stages_passed,
            "source_verification_passed": sources_verified,
            "status": "verified" if all_stages_passed else "source_unverified",
        }

    @classmethod
    def execute_o3_jarvis_action_preview(cls) -> dict[str, Any]:
        """Execute O3 wave gate: connect JARVIS action preview to canonical services without state duplication."""
        jarvis_fp = get_git_fingerprint(JARVIS_DIR)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        schemas_path = JARVIS_DIR / "backend" / "app" / "schemas.py"
        main_path = JARVIS_DIR / "backend" / "app" / "main.py"
        schemas_record = donor_file_record(schemas_path, JARVIS_DIR)
        main_record = donor_file_record(main_path, JARVIS_DIR)
        has_backend_schemas = schemas_record is not None
        has_backend_main = main_record is not None

        action_name = "run_portfolio_backup"
        parameters = {
            "target_vault": "local_encrypted_vault",
            "source_paths": ["operator-os/evidence", "accessibility/evidence"],
            "compression": "none",
        }

        preview = OperatorOSEngine.preview_jarvis_action(action_name, parameters)

        source_verified = (
            is_meaningful_git_fingerprint(jarvis_fp)
            and has_backend_schemas
            and has_backend_main
        )
        all_stages_passed = (
            source_verified
            and preview.get("state") == "preview_ready"
            and preview.get("requires_human_approval") is True
        )

        receipt = {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O3",
            "executed_at": now_iso,
            "jarvis_runtime": {
                **jarvis_fp,
                "has_schemas": has_backend_schemas,
                "has_main": has_backend_main,
                "schemas": schemas_record,
                "main": main_record,
            },
            "jarvis_source_inspected": has_backend_schemas and has_backend_main,
            "action_preview": preview,
            "dry_run_only": True,
            "requires_human_approval": preview.get("requires_human_approval", False),
            "destructive": preview.get("destructive", True),
            "recovery_path": preview.get("recovery_path", ""),
            "all_stages_passed": all_stages_passed,
            "source_verification_passed": source_verified,
            "status": "preview_verified" if all_stages_passed else "source_unverified",
        }
        return receipt

    @classmethod
    def execute_o4_pkos_stream_intake(cls) -> dict[str, Any]:
        """Execute O4 wave gate: widen PKOS intake stream to multi-source stream with fenced Observer projections."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        pkos_fp = get_git_fingerprint(PKOS_DIR)
        observer_fp = get_git_fingerprint(OBSERVER_DIR)
        dotfiles_fp = get_git_fingerprint(DOTFILES_DIR)

        donor_notes = [
            (PKOS_DIR / "README.md", "src-pkos-readme", "pkos://README.md", "PKos README"),
            (DOTFILES_DIR / "README.md", "src-dotfiles-readme", "dotfiles://README.md", "dotfiles README"),
            (OBSERVER_DIR / "README.md", "src-observer-readme", "observer://README.md", "Observer README"),
        ]
        notes_stream = []
        for path, source_id, origin, title in donor_notes:
            content = read_donor_text(path)
            record = donor_file_record(path, path.parent)
            if not content or record is None:
                continue
            notes_stream.append({
                "source_id": source_id,
                "origin": origin,
                "content": content[:20_000],
                "title": title,
                "summary": f"Donor-backed intake from {record['path']} ({record['bytes']} bytes).",
                "sha256": record["sha256"],
            })

        stream_results = OperatorOSEngine.capture_live_pkos_stream(
            notes_stream, collector="portfolio_suites.adapters.operator_os.o4_stream"
        )

        all_fenced = all(
            "<!-- FENCE: DO NOT RE-INGEST INTO PKOS CANONICAL CORPUS -->" in proj
            and "fenced_from_reingestion: true" in proj
            for _, proj in stream_results
        )
        all_cited = all(
            rec["source_id"] in proj and rec["sha256"][:12] in proj
            for rec, proj in stream_results
        )
        sources_verified = (
            is_meaningful_git_fingerprint(pkos_fp)
            and is_meaningful_git_fingerprint(observer_fp)
            and is_meaningful_git_fingerprint(dotfiles_fp)
        )
        all_stages_passed = (
            len(notes_stream) >= 3
            and len(stream_results) >= 3
            and all_fenced
            and all_cited
            and sources_verified
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O4",
            "executed_at": now_iso,
            "pkos_fingerprint": pkos_fp,
            "observer_fingerprint": observer_fp,
            "dotfiles_fingerprint": dotfiles_fp,
            "donor_notes_read": len(notes_stream),
            "batch_size": len(stream_results),
            "all_fenced_from_reingestion": all_fenced,
            "all_sources_cited": all_cited,
            "processed_records": [rec for rec, _ in stream_results],
            "observer_projections_count": len(stream_results),
            "all_stages_passed": all_stages_passed,
            "source_verification_passed": sources_verified,
            "status": "stream_intake_verified" if all_stages_passed else "source_unverified",
        }

    @classmethod
    def execute_o5_ryos_disposition_reconciliation(cls) -> dict[str, Any]:
        """Execute O5 wave gate: formalize Ryos and master-plan inventory disposition and dotfiles porting."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        inventory = cls.execute_o2_ryos_inventory()
        disposition = OperatorOSEngine.reconcile_ryos_disposition()
        catalog = inventory.get("inventory_catalog") or RYOS_DISPOSITION_CATALOG
        donor_read = (
            inventory.get("status") == "verified"
            and inventory.get("ryos_core_files_count", 0) >= 3
            and bool(catalog)
        )
        all_stages_passed = (
            donor_read
            and len(disposition.get("proposed_ports", [])) >= 2
            and disposition.get("duplicate_row_proposal") == "close_on_verification"
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O5",
            "executed_at": now_iso,
            "disposition_id": "disp-ryos-masterplan-20260820",
            "canonical_anchors": disposition.get("canonical_anchors", {}),
            "port_candidates_count": len(disposition.get("proposed_ports", [])),
            "proposed_ports": disposition.get("proposed_ports", []),
            "superseded_features": disposition.get("superseded_features", []),
            "source_inventory_catalog": catalog,
            "ryos_core_files_count": inventory.get("ryos_core_files_count", 0),
            "duplicate_decisions_closed": False,
            "duplicate_decision_disposition": disposition.get("duplicate_row_proposal"),
            "migration_acceptance_verified": disposition.get("migration_acceptance_verified", False),
            "donor_read": donor_read,
            "external_runtime_invoked": False,
            "donor_freeze_status": disposition.get("donor_freeze_status"),
            "all_stages_passed": all_stages_passed,
            "status": "disposition_proposal_recorded" if all_stages_passed else "source_unverified",
        }

    @classmethod
    def execute_o6_jarvis_checkpoint_lifecycle(cls) -> dict[str, Any]:
        """Execute O6 wave gate: test multi-action checkpoint lifecycle with fail-closed security boundary (zero disk mutations)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        jarvis_fp = get_git_fingerprint(JARVIS_DIR)
        schemas_record = donor_file_record(JARVIS_DIR / "backend" / "app" / "schemas.py", JARVIS_DIR)
        main_record = donor_file_record(JARVIS_DIR / "backend" / "app" / "main.py", JARVIS_DIR)

        # 1. Test fail-closed behavior when approval is absent
        unapproved_res = OperatorOSEngine.execute_jarvis_action_checkpoint(
            action_name="audit_secrets",
            parameters={"path": str(SUITES_ROOT)},
            operator_approved=False,
        )

        fail_closed_ok = (
            unapproved_res.get("status") == "blocked_missing_approval"
            and unapproved_res.get("operator_approval_verified") is False
            and unapproved_res.get("execution_receipt") is None
        )

        # 2. Test dry-run preview generation with human approval boundary
        preview_res = OperatorOSEngine.preview_jarvis_action(
            action_name="backup_data",
            parameters={"vault": "operator-os-vault", "path": "operator-os/evidence", "dry_run": True},
        )
        preview_ok = (
            preview_res.get("state") == "preview_ready"
            and preview_res.get("requires_human_approval") is True
            and preview_res.get("destructive") is False
        )
        # 3. Complete the lifecycle with a real, approved-by-caller read-only execution. The
        # boolean is not represented as cryptographic operator authority; it only permits a
        # zero-mutation audit action.
        execution_res = OperatorOSEngine.execute_jarvis_action_checkpoint(
            action_name="audit_secrets",
            parameters={"path": str(SUITES_ROOT / "src")},
            operator_approved=True,
        )
        execution_ok = (
            execution_res.get("status") == "success"
            and execution_res.get("state") == "executed_with_receipt"
            and execution_res.get("operator_approval_verified") is False
            and execution_res.get("execution_authority") == "caller_confirmed_read_only_or_dry_run"
            and isinstance(execution_res.get("execution_result", {}).get("scanned_files_count"), int)
        )
        source_verified = (
            is_meaningful_git_fingerprint(jarvis_fp)
            and schemas_record is not None
            and main_record is not None
        )
        all_stages_passed = fail_closed_ok and preview_ok and execution_ok and source_verified

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O6",
            "executed_at": now_iso,
            "jarvis_fingerprint": jarvis_fp,
            "jarvis_source": {"schemas": schemas_record, "main": main_record},
            "fail_closed_test": {
                "action": "audit_secrets",
                "operator_approved": False,
                "result": unapproved_res,
                "verified": fail_closed_ok,
            },
            "preview_test": {
                "action": "backup_data",
                "preview": preview_res,
                "verified": preview_ok,
            },
            "execution_test": {
                "action": "audit_secrets",
                "mutation_mode": "read_only",
                "result": execution_res,
                "verified": execution_ok,
            },
            "multi_action_lifecycle_passed": all_stages_passed,
            "source_verification_passed": source_verified,
            "human_gate_boundary": "fail_closed_without_explicit_operator_token",
            "disk_mutations_performed": False,
            "all_stages_passed": all_stages_passed,
            "status": "checkpoint_lifecycle_verified" if all_stages_passed else "source_unverified",
        }
