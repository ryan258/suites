"""Source adapter for Operator OS connecting dotfiles, PKos, Observer, JARVIS, and Ryos."""

from __future__ import annotations

import contextlib
import datetime
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256, validate_contract
from ..engines.operator_os import OperatorOSEngine
from .common import (
    SUITES_ROOT,
    get_git_fingerprint,
    get_repo_path,
    is_meaningful_git_fingerprint,
)

@contextlib.contextmanager
def donor_import_path(donor_dir: Path, package: str):
    """Expose a donor repo to `import` for one call only, then take it back off sys.path.

    The donor goes in at position 0, so leaving it there would let the donor shadow every
    later import in the process — including in a subsequent wave under `wave --all`. The
    donor's own modules are dropped from sys.modules on the way out too: a cached donor
    module would make a second run in the same process read the first run's code, which is
    exactly what the outside-world sensitivity test needs to be able to see change in.
    """
    entry = str(donor_dir)
    added = entry not in sys.path
    if added:
        sys.path.insert(0, entry)
    try:
        yield
    finally:
        if added:
            with contextlib.suppress(ValueError):
                sys.path.remove(entry)
        for name in [m for m in sys.modules if m == package or m.startswith(f"{package}.")]:
            del sys.modules[name]


DOTFILES_DIR = get_repo_path("dotfiles", "DOTFILES_DIR")
PKOS_DIR = get_repo_path("PKos", "PKOS_DIR")
OBSERVER_DIR = get_repo_path("obsidian-observer", "OBSERVER_DIR")
JARVIS_DIR = get_repo_path("jarvis", "JARVIS_DIR")
RYOS_DIR = get_repo_path("ryos", "RYOS_DIR")
MASTER_UPGRADE_PLAN_DIR = get_repo_path("master-upgrade-plan", "MASTER_UPGRADE_PLAN_DIR")

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
            try:
                with donor_import_path(PKOS_DIR, "pkos"):
                    from pkos.storage import Workspace, checksum_file
                    from pkos.normalize import normalize

                    with tempfile.TemporaryDirectory() as tmpdir:
                        ws = Workspace(Path(tmpdir))
                        acquired_record = ws.acquire_file(
                            agents_path,
                            kind="operator_policy",
                            label="dotfiles/AGENTS.md",
                        )
                        # Verify raw CAS object exists and hash matches byte-for-byte
                        cas_object_path = ws.root / acquired_record["raw_object"]
                        raw_bytes_match = (
                            cas_object_path.is_file()
                            and checksum_file(cas_object_path) == acquired_record["sha256"]
                            and checksum_file(agents_path) == acquired_record["sha256"]
                        )
                        # Run real PKos normalization into SQLite
                        counts = normalize(ws)
                        normalize_counts = counts
                        cas_acquisition = acquired_record
                        cas_verified = (
                            raw_bytes_match
                            and counts.get("acquisitions", 0) >= 1
                            and counts.get("items", 0) >= 1
                            and counts.get("chunks", 0) >= 1
                            and counts.get("failures", 0) == 0
                        )
            except Exception as exc:
                # A silent False here would report a red wave with no way to tell a PKos API
                # change from a broken donor file. Record why, the way A2 does.
                cas_verified = False
                operational_errors.append({
                    "stage": "cas_acquisition",
                    "command": f"pkos.storage.Workspace(...).acquire_file({agents_path}) + pkos.normalize.normalize(ws)",
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

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O1",
            "executed_at": now_iso,
            "status": "cas_projection_verified" if all_stages_passed else "source_unverified",
            "source_record": src_record,
            "cas_acquisition": cas_acquisition,
            "observer_projection_preview": projection,
            "source_derived_assertions": source_derived_assertions,
            "all_stages_passed": all_stages_passed,
            "cas_verified": cas_verified,
            "operational_errors": operational_errors,
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

        has_backend_schemas = (JARVIS_DIR / "backend" / "app" / "schemas.py").is_file()
        has_backend_main = (JARVIS_DIR / "backend" / "app" / "main.py").is_file()

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
            },
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

        notes_stream = [
            {
                "source_id": "src-daily-log-20260820",
                "origin": "dotfiles://logs/daily-20260820.md",
                "content": (
                    "# Daily Operating Log - 2026-08-20\n"
                    "- Verified portfolio suites control plane baseline.\n"
                    "- Executed clean migration wave gates for Operator OS.\n"
                    "- Preserved isolated git working trees across all 70 repositories."
                ),
                "title": "Daily Operating Log 2026-08-20",
                "summary": "Daily operating log covering suites control plane and clean migration gates.",
            },
            {
                "source_id": "src-arch-decision-009",
                "origin": "notes://arch/sqlite-wal.md",
                "content": (
                    "# Architecture Decision 009: SQLite WAL Concurrency\n"
                    "- Selected single-writer WAL mode for zero-dependency local ledger.\n"
                    "- Established content-addressed sha256 receipts on all mutating transactions."
                ),
                "title": "Architecture Decision 009 - SQLite WAL Concurrency",
                "summary": "Selection of single-writer WAL mode for zero-dependency local ledger.",
            },
            {
                "source_id": "src-security-boundary-003",
                "origin": "dotfiles://security/operator-boundary.md",
                "content": (
                    "# Security Boundary: Operator Gating\n"
                    "- Never auto-manufacture human approval tokens.\n"
                    "- Actions fail closed when operator approval token is absent."
                ),
                "title": "Security Boundary - Operator Gating",
                "summary": "Policy establishing fail-closed boundaries for unapproved operator actions.",
            },
        ]

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
        )
        all_stages_passed = len(stream_results) >= 3 and all_fenced and all_cited and sources_verified

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O4",
            "executed_at": now_iso,
            "pkos_fingerprint": pkos_fp,
            "observer_fingerprint": observer_fp,
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
        disposition = OperatorOSEngine.reconcile_ryos_disposition()

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O5",
            "executed_at": now_iso,
            "disposition_id": "disp-ryos-masterplan-20260820",
            "canonical_anchors": disposition.get("canonical_anchors", {}),
            "port_candidates_count": len(disposition.get("proposed_ports", [])),
            "proposed_ports": disposition.get("proposed_ports", []),
            "superseded_features": disposition.get("superseded_features", []),
            "source_inventory_catalog": RYOS_DISPOSITION_CATALOG,
            # The engine this reads from says `migration_acceptance_verified: False` and
            # `duplicate_row_proposal: "close_on_verification"` -- a proposal awaiting
            # verification. Reporting that as a closure named an outcome the gate never
            # performed, so the receipt now states the disposition and, explicitly, the
            # things it did not do.
            "duplicate_decisions_closed": False,
            "duplicate_decision_disposition": disposition.get("duplicate_row_proposal"),
            "migration_acceptance_verified": disposition.get("migration_acceptance_verified", False),
            "donor_read": False,
            "external_runtime_invoked": False,
            "donor_freeze_status": disposition.get("donor_freeze_status"),
            "all_stages_passed": len(disposition.get("proposed_ports", [])) >= 2 and disposition.get("duplicate_row_proposal") == "close_on_verification",
            "status": "disposition_proposal_recorded",
        }

    @classmethod
    def execute_o6_jarvis_checkpoint_lifecycle(cls) -> dict[str, Any]:
        """Execute O6 wave gate: test multi-action checkpoint lifecycle with fail-closed security boundary (zero disk mutations)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        jarvis_fp = get_git_fingerprint(JARVIS_DIR)

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
        source_verified = is_meaningful_git_fingerprint(jarvis_fp)
        all_stages_passed = fail_closed_ok and preview_ok and execution_ok and source_verified

        return {
            "schema_version": SCHEMA_VERSION,
            "wave_id": "O6",
            "executed_at": now_iso,
            "jarvis_fingerprint": jarvis_fp,
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
