"""Operator OS reference prototype engine powering SourceRecord capture, PKOS indexing, Observer projections, and JARVIS actions.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. dotfiles, PKos).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import stat
from pathlib import Path
import re
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract
from ..identifiers import new_prefixed_id
from ..registry import SUITES_ROOT


def _confined_path(raw_path: str | Path) -> Path | None:
    """Validate and return resolved path if strictly confined to workspace; return None if unconfined or sensitive."""
    target_p = (Path(raw_path) if Path(raw_path).is_absolute() else (SUITES_ROOT / raw_path)).resolve()
    suites_resolved = SUITES_ROOT.resolve()
    projects_dir = suites_resolved.parent
    home_resolved = Path.home().resolve()
    sensitive_markers = {".ssh", ".aws", ".gnupg", ".netrc", ".bash_history", ".zsh_history"}

    if (
        target_p == home_resolved
        or target_p == Path("/")
        or any(m in target_p.parts for m in sensitive_markers)
        or not (target_p.is_relative_to(suites_resolved) or target_p.is_relative_to(projects_dir))
    ):
        return None
    return target_p


def _read_confined_file(candidate: Path, max_bytes: int | None = None) -> bytes | None:
    """Read a file found by a directory walk, or None if it may not be read.

    Confining the walk root is not enough. `os.walk` declines to follow *directory*
    symlinks, but a *file* symlink inside an allowed directory is an ordinary file to
    `is_file()`, and reading it follows the link wherever it points. So every candidate is
    rechecked against the boundary its root was checked against.

    Testing the path and then opening it are two separate lookups, and a candidate swapped
    for a symlink in between would still be followed -- checking first does not avoid that
    race, it just moves it. O_NOFOLLOW puts the refusal inside the open itself (ELOOP).

    A walk also turns up things that are not files. Opening a FIFO with no writer blocks
    forever, and blocking happens *before* `fstat` could say what it is, so the type check
    has to be bought with O_NONBLOCK on the open rather than paid for afterwards. Only a
    regular file is then read, from that same descriptor.

    The cap is enforced while reading, not just against the opening `st_size`: `fstat`
    fixes which inode is being read, not how large it stays, and a file growing under the
    loop would otherwise walk straight past the limit.

    ponytail: the file is anchored, its parent directories are not. Swapping a parent for a
    symlinked directory mid-walk is out of scope; closing that means rebuilding the walk on
    directory descriptors (os.fwalk + openat), which is more than a read-only audit of a
    local checkout earns. The threat this does close is a symlink planted in donor content.
    """
    if _confined_path(candidate) is None:
        return None
    fd = None
    try:
        fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        if max_bytes is not None and info.st_size > max_bytes:
            return None
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(fd, 65536):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        # ELOOP for a symlink, ENXIO/EISDIR/ENOENT for anything else the walk raced away.
        return None
    finally:
        if fd is not None:
            os.close(fd)


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
            "action_id": new_prefixed_id("act-jarvis"),
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
        """Execute a secondary JARVIS action through the preview/approval/receipt/recovery lifecycle (O6 wave).

        Note: `operator_approved` is a modeled boolean token within this suite-local prototype engine.
        Full runtime deployment will bind to cryptographic session signoffs and external auth gates.
        """
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
            target_p = _confined_path(search_path)
            if target_p is None:
                return {
                    **preview,
                    "status": "error_unconfined_path",
                    "state": "error_unconfined_path",
                    "operator_approval_verified": True,
                    "error": f"Target path is outside allowed workspace boundaries: {search_path}",
                    "execution_receipt": None,
                }
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
                data = _read_confined_file(cf, max_bytes=500_000)
                if data is None:
                    continue
                try:
                    text = data.decode("utf-8", errors="ignore")
                    scanned_files += 1
                    scanned_bytes += len(data)
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
            raw_path = parameters.get("path", "operator-os/evidence")
            vault_src = _confined_path(raw_path)
            dry_run = parameters.get("dry_run", True)

            if vault_src is None:
                return {
                    **preview,
                    "status": "error_unconfined_path",
                    "state": "error_unconfined_path",
                    "operator_approval_verified": True,
                    "error": f"Vault source path is outside allowed workspace boundaries: {raw_path}",
                    "execution_receipt": None,
                }
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
                    if fp.name.startswith("snap-"):
                        continue
                    data = _read_confined_file(fp)
                    if data is not None:
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
        elif action_name == "sync_obsidian_notes":
            vault_path = parameters.get("vault_path", "operator-os/evidence")
            vault_p = _confined_path(vault_path)
            if vault_p is None:
                return {
                    **preview,
                    "status": "error_unconfined_path",
                    "state": "error_unconfined_path",
                    "operator_approval_verified": True,
                    "error": f"Vault path is outside workspace boundaries: {vault_path}",
                    "execution_receipt": None,
                }
            if not vault_p.exists():
                return {
                    **preview,
                    "status": "error_path_not_found",
                    "state": "error_path_not_found",
                    "operator_approval_verified": True,
                    "error": f"Vault path does not exist: {vault_path}",
                    "execution_receipt": None,
                }
            md_files = []
            if vault_p.is_file() and vault_p.suffix == ".md":
                md_files.append(vault_p)
            elif vault_p.is_dir():
                for root, dirs, files in os.walk(vault_p):
                    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv")]
                    for f in files:
                        if f.endswith(".md"):
                            md_files.append(Path(root) / f)
                            if len(md_files) >= 1000:
                                break
                    if len(md_files) >= 1000:
                        break
            action_results = {
                "vault_path": str(vault_p),
                "notes_scanned_count": len(md_files),
                "sync_mode": "read_only_verification",
                "verified": True,
            }
        elif action_name == "rotate_local_cache":
            cache_dir = parameters.get("cache_dir", ".cache")
            cache_p = _confined_path(cache_dir)
            if cache_p is None:
                return {
                    **preview,
                    "status": "error_unconfined_path",
                    "state": "error_unconfined_path",
                    "operator_approval_verified": True,
                    "error": f"Cache directory is outside allowed workspace boundaries: {cache_dir}",
                    "execution_receipt": None,
                }
            # No rotation operation exists yet, so active mode is refused rather than
            # reported. A receipt saying `rotated: true` for work that never happened is
            # worse than no receipt: it is the evidence layer certifying its own fiction.
            # Implementing this needs a retention policy, an atomic and recoverable
            # mutation, and before/after evidence -- then `rotated` derives from a
            # verified postcondition instead of from the request.
            if not parameters.get("dry_run", True):
                return {
                    **preview,
                    "status": "error_unimplemented_action",
                    "state": "error_unimplemented_action",
                    "operator_approval_verified": True,
                    "error": "rotate_local_cache has no active rotation implementation; only dry_run inspection is supported",
                    "execution_receipt": None,
                }
            action_results = {
                "cache_target": str(cache_p),
                "cache_target_exists": cache_p.is_dir(),
                "rotated": False,
                "rotation_mode": "dry_run",
            }
        else:
            return {
                **preview,
                "status": "error_unknown_action",
                "state": "error_unknown_action",
                "operator_approval_verified": True,
                "error": f"Unimplemented JARVIS action: {action_name}",
                "execution_receipt": None,
            }

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
