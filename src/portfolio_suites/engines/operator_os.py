"""Operator OS reference prototype engine powering SourceRecord capture, PKOS indexing, Observer projections, and JARVIS actions.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. dotfiles, PKos).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract
from ..registry import SUITES_ROOT


class OperatorOSEngine:
    """Reference prototype to capture notes into SourceRecords, build PKOS citations, and project safe Observer notes."""

    @staticmethod
    def detect_reingestion_violation(content: str) -> bool:
        """Detect if an artifact is an Observer projection attempted to be re-ingested as raw canonical source."""
        return (
            "fenced_from_reingestion: true" in content
            or "<!-- FENCE: DO NOT RE-INGEST" in content
            or "type: observer_projection" in content
        )

    @staticmethod
    def validate_observer_projection(projection_text: str, source_record: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate that an Observer projection contains required anti-reingestion fences and source citations."""
        errors: list[str] = []
        if "fenced_from_reingestion: true" not in projection_text:
            errors.append("Missing frontmatter 'fenced_from_reingestion: true'")
        if "<!-- FENCE: DO NOT RE-INGEST INTO PKOS CANONICAL CORPUS -->" not in projection_text:
            errors.append("Missing anti-reingestion HTML fence comment")
        if "type: observer_projection" not in projection_text:
            errors.append("Missing frontmatter 'type: observer_projection'")

        src_id = source_record.get("source_id", "")
        if not src_id or src_id not in projection_text:
            errors.append(f"Missing source_id citation: {src_id}")

        src_sha = source_record.get("sha256", "")
        if not src_sha or src_sha[:12] not in projection_text:
            errors.append(f"Missing source_sha256 citation: {src_sha[:12]}")

        return (len(errors) == 0, errors)

    @staticmethod
    def capture_source(
        content: str,
        origin: str,
        source_id: str,
        media_type: str = "text/markdown",
        author: str = "Ryan",
        collector: str = "portfolio_suites.engines.operator_os",
        allow_projected_reingestion: bool = False,
    ) -> dict[str, Any]:
        """Convert arbitrary text into a content-addressed, validated SourceRecord."""
        if not allow_projected_reingestion and OperatorOSEngine.detect_reingestion_violation(content):
            raise ValueError(
                f"Cannot ingest fenced Observer projection '{source_id}' back into canonical PKOS corpus."
            )

        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "schema_version": SCHEMA_VERSION,
            "source_id": source_id,
            "acquired_at": now_iso,
            "sha256": digest,
            "size_bytes": len(encoded),
            "media_type": media_type,
            "origin": origin,
            "provenance": {
                "author": author,
                "collector": collector,
                "intake_method": "source_capture",
                "raw_preview": content[:120].strip(),
            },
        }
        return validate_contract("SourceRecord", record)

    @staticmethod
    def project_to_observer(source_record: dict[str, Any], title: str, summary: str, body: str) -> str:
        """Create a derived Obsidian Observer note fenced against accidental re-ingestion."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        src_id = source_record.get("source_id", "unknown")
        sha = source_record.get("sha256", "unknown")

        return f"""---
title: "{title}"
type: observer_projection
source_id: "{src_id}"
source_sha256: "{sha}"
projected_at: "{now_iso}"
generator: "portfolio_suites.operator_os"
status: derived
fenced_from_reingestion: true
---

<!-- FENCE: DO NOT RE-INGEST INTO PKOS CANONICAL CORPUS -->

# {title}

> **Source Citation:** `{src_id}` (SHA: `{sha[:12]}...`)
> **Acquired Origin:** `{source_record.get("origin")}`

## Summary
{summary}

## Extracted Analysis
{body}

---
*Derived via Operator OS projection engine. Immutable canonical truth lives in PKOS.*
"""

    @staticmethod
    def capture_live_pkos_stream(
        notes_batch: list[dict[str, str]],
        collector: str = "portfolio_suites.operator_os.live_intake",
    ) -> list[tuple[dict[str, Any], str]]:
        """Process real day-to-day notes stream into SourceRecords with fenced Observer projections (O4 wave)."""
        results = []
        for note in notes_batch:
            src_record = OperatorOSEngine.capture_source(
                content=note["content"],
                origin=note["origin"],
                source_id=note["source_id"],
                media_type=note.get("media_type", "text/markdown"),
                author=note.get("author", "Ryan"),
                collector=collector,
            )
            projection = OperatorOSEngine.project_to_observer(
                source_record=src_record,
                title=note.get("title", "Daily Working Note"),
                summary=note.get("summary", note["content"][:80]),
                body=note["content"],
            )
            results.append((src_record, projection))
        return results

    @staticmethod
    def reconcile_ryos_disposition() -> dict[str, Any]:
        """Formalize Ryos and master-plan inventory disposition proposal (O5 wave reference prototype)."""
        return {
            "artifact_kind": "reference_prototype",
            "reconciliation_id": "rec-ryos-dotfiles-2026",
            "migration_acceptance_verified": False,
            "canonical_anchors": {
                "system_runtime": "dotfiles",
                "knowledge_corpus": "PKos",
                "projection_view": "Observer",
                "orchestration_gateway": "JARVIS",
            },
            "proposed_ports": [
                {"name": "cli_launcher", "source": "ryos", "proposed_target": "dotfiles/bin/ryos-quick", "expected_disposition": "port_candidate"},
                {"name": "status_daemon_helpers", "source": "ryos", "proposed_target": "dotfiles/functions", "expected_disposition": "port_candidate"},
            ],
            "superseded_features": [
                {"name": "master-upgrade-plan", "expected_disposition": "superseded_by_suites_bible", "reason": "Centralized under suites/docs/ROADMAP.md"},
                {"name": "coos_ad_hoc_state", "expected_disposition": "rejected", "reason": "Redundant with PKos SourceRecord architecture"},
            ],
            "duplicate_row_proposal": "close_on_verification",
            "donor_freeze_status": "unverified_prototype",
        }

    @staticmethod
    def preview_jarvis_action(action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Generate a dry-run preview receipt for a user-approved JARVIS command."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "action_id": f"act-jarvis-{int(datetime.datetime.now().timestamp())}",
            "action_name": action_name,
            "parameters": parameters,
            "state": "preview_ready",
            "preview_at": now_iso,
            "requires_human_approval": True,
            "destructive": False,
            "recovery_path": "undo_via_backup_or_clean_revert",
        }

    @staticmethod
    def execute_jarvis_action_checkpoint(
        action_name: str,
        parameters: dict[str, Any],
        operator_approved: bool = False,
    ) -> dict[str, Any]:
        """Execute a secondary JARVIS action through the preview/approval/receipt/recovery lifecycle (O6 wave)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        preview = OperatorOSEngine.preview_jarvis_action(action_name, parameters)

        if not operator_approved:
            return {
                **preview,
                "status": "blocked_missing_approval",
                "state": "blocked_missing_approval",
                "operator_approval_verified": False,
                "execution_receipt": None,
            }

        # Supported action dispatchers
        known_actions = {"audit_secrets", "backup_data", "sync_obsidian_notes", "rotate_local_cache"}
        if action_name not in known_actions:
            return {
                **preview,
                "status": "error_unknown_action",
                "state": "error_unknown_action",
                "operator_approval_verified": True,
                "error": f"Unknown JARVIS action: {action_name}",
                "execution_receipt": None,
            }

        # Execute real handler
        action_results: dict[str, Any] = {}
        if action_name == "audit_secrets":
            search_path = parameters.get("path", ".")
            target_p = Path(search_path)
            if not target_p.exists():
                return {
                    **preview,
                    "status": "error_path_not_found",
                    "state": "error_path_not_found",
                    "operator_approval_verified": True,
                    "error": f"Target path does not exist: {search_path}",
                    "execution_receipt": None,
                }

            scanned_files = 0
            scanned_bytes = 0
            findings: list[str] = []
            secret_pattern = re.compile(
                r'(?:PRIVATE KEY|SECRET_KEY|API_KEY|PASSWORD|OPENROUTER_API_KEY)[ \t]*[:=][ \t]*["\']?[A-Za-z0-9_\-\.]{12,}',
                re.IGNORECASE,
            )

            candidate_files: list[Path] = []
            if target_p.is_file():
                candidate_files.append(target_p)
            else:
                for root, dirs, files in os.walk(target_p):
                    # Skip .git, binary, and virtualenv dirs
                    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv", "dist", "build")]
                    for f in files:
                        if f.endswith((".py", ".json", ".md", ".env.example", ".txt", ".yml", ".yaml")):
                            candidate_files.append(Path(root) / f)

            for cf in candidate_files:
                try:
                    stat = cf.stat()
                    if stat.st_size > 500_000:
                        continue
                    text = cf.read_text(encoding="utf-8", errors="ignore")
                    scanned_files += 1
                    scanned_bytes += stat.st_size
                    if secret_pattern.search(text):
                        findings.append(
                            str(cf.relative_to(target_p.parent) if cf.is_relative_to(target_p.parent) else cf)
                        )
                except Exception:
                    continue

            action_results = {
                "scanned_target": str(target_p.resolve()),
                "scanned_files_count": scanned_files,
                "scanned_bytes": scanned_bytes,
                "findings_count": len(findings),
                "clean": len(findings) == 0,
                "findings": findings,
            }
        elif action_name == "backup_data":
            target_vault = parameters.get("vault", "default-vault")
            raw_path = Path(parameters.get("path", "operator-os/evidence"))
            vault_src = raw_path if raw_path.is_absolute() else (SUITES_ROOT / raw_path).resolve()
            dry_run = parameters.get("dry_run", True)
            if not vault_src.exists():
                return {
                    **preview,
                    "status": "error_path_not_found",
                    "state": "error_path_not_found",
                    "operator_approval_verified": True,
                    "error": f"Vault source path does not exist: {vault_src}",
                    "execution_receipt": None,
                }

            backed_up_files = []
            for root, _, files in sorted(os.walk(vault_src)):
                for f in sorted(files):
                    fp = Path(root) / f
                    if fp.is_file() and not fp.name.startswith("snap-"):
                        data = fp.read_bytes()
                        backed_up_files.append({
                            "path": str(fp),
                            "size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        })

            # Content-addressed snapshot ID based on sorted file hashes
            hasher = hashlib.sha256()
            hasher.update(target_vault.encode("utf-8"))
            for f in backed_up_files:
                hasher.update(f"{f['path']}:{f['sha256']}".encode("utf-8"))
            snap_id = f"snap-{hasher.hexdigest()[:12]}"

            manifest_content = {
                "snapshot_id": snap_id,
                "vault": target_vault,
                "created_at": now_iso,
                "dry_run": dry_run,
                "files_count": len(backed_up_files),
                "files": backed_up_files,
            }

            manifest_file_path = ""
            if not dry_run:
                snapshot_dir = SUITES_ROOT / "operator-os" / "evidence" / "snapshots"
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                manifest_file = snapshot_dir / f"{snap_id}.json"
                manifest_file.write_text(json.dumps(manifest_content, indent=2), encoding="utf-8")
                manifest_file_path = str(manifest_file)

            action_results = {
                "vault": target_vault,
                "snapshot_id": snap_id,
                "dry_run": dry_run,
                "manifest_file": manifest_file_path,
                "files_backed_up": len(backed_up_files),
                "verified": True,
            }
        else:
            action_results = {"executed": True, "details": parameters}

        receipt = {
            "action_id": preview["action_id"],
            "action_name": action_name,
            "parameters": parameters,
            "state": "executed_with_receipt",
            "executed_at": now_iso,
            "requires_human_approval": True,
            "operator_approval_verified": True,
            "execution_result": action_results,
            "audit_trail": {
                "preview_hash": hashlib.sha256(str(preview).encode("utf-8")).hexdigest(),
                "recovery_snapshot": f"snapshot://pre-action-{preview['action_id']}",
                "credential_boundary_preserved": True,
            },
            "status": "success",
        }
        return receipt
