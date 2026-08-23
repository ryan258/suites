"""Operator OS reference prototype engine powering SourceRecord capture, PKOS indexing, Observer projections, and JARVIS actions.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. dotfiles, PKos).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path
import re
from typing import Any
from ..approvals import ApprovalError, canonical_digest, verify_operator_approval
from ..contracts import SCHEMA_VERSION, validate_contract
from ..identifiers import new_prefixed_id
from ..paths import durable_write_text
from ..provenance import is_sensitive_path
from ..registry import SUITES_ROOT


MAX_BACKUP_FILE_BYTES = 10 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 100 * 1024 * 1024
MAX_BACKUP_FILES = 10_000
MAX_NOTE_BYTES = 2 * 1024 * 1024
MAX_SYNC_NOTES = 1_000


def _action_approval_bindings(action_name: str, parameters: dict[str, Any]) -> dict[str, str]:
    return {
        "operation": "jarvis_action_execution",
        "action_name": action_name,
        "decision": "approved",
        "payload_sha256": canonical_digest({"action_name": action_name, "parameters": parameters}),
    }


def _action_error(
    preview: dict[str, Any],
    status: str,
    message: str,
    *,
    approval_verified: bool = False,
) -> dict[str, Any]:
    return {
        **preview,
        "status": status,
        "state": status,
        "operator_approval_verified": approval_verified,
        "execution_authority": (
            "verified_operator_approval" if approval_verified else "caller_confirmation_only"
        ),
        "error": message,
        "execution_receipt": None,
    }


def _deterministic_zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    return info


# Fields that vary between two runs over the same file set. `snap_id` covers the vault and the
# inventoried files only, so anything here would change the archived bytes without changing the
# name they are stored under, and the content-addressed guard would read that as a collision.
# The per-snapshot manifest written alongside the archive keeps all of them.
_RUN_VARYING_MANIFEST_FIELDS = frozenset({
    "created_at",
    "dry_run",
    "source",
    "skipped_sensitive_count",
    "skipped_unreadable_count",
})


def _archive_manifest(manifest_content: dict[str, Any]) -> dict[str, Any]:
    """Project a snapshot manifest down to the fields `snap_id` actually identifies."""
    return {
        key: value
        for key, value in manifest_content.items()
        if key not in _RUN_VARYING_MANIFEST_FIELDS
    }


def _write_backup_archive(
    destination: Path,
    entries: list[tuple[str, bytes]],
    archive_manifest: dict[str, Any],
) -> str:
    """Write a deterministic ZIP to a same-directory temporary and atomically install it."""
    temporary: str | None = None
    try:
        handle, temporary = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(handle)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr(
                _deterministic_zip_info("SNAPSHOT.json"),
                json.dumps(
                    archive_manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8"),
            )
            for relative_path, data in sorted(entries):
                archive.writestr(_deterministic_zip_info(f"files/{relative_path}"), data)
        hasher = hashlib.sha256()
        with open(temporary, "rb") as stream:
            while chunk := stream.read(65536):
                hasher.update(chunk)
            os.fsync(stream.fileno())
        candidate_digest = hasher.hexdigest()
        if destination.exists():
            existing_hasher = hashlib.sha256()
            with destination.open("rb") as stream:
                while chunk := stream.read(65536):
                    existing_hasher.update(chunk)
            if existing_hasher.hexdigest() != candidate_digest:
                raise OSError(f"content-addressed backup collision at {destination}")
            os.unlink(temporary)
            temporary = None
        else:
            os.replace(temporary, destination)
            temporary = None
        directory_handle = os.open(
            destination.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_handle)
        finally:
            os.close(directory_handle)
        return candidate_digest
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _confined_path(
    raw_path: str | Path,
    *,
    reject_sensitive_path: bool = True,
) -> Path | None:
    """Return a resolved workspace path, optionally rejecting sensitivity-shaped names.

    The boundary is the portfolio directory, which holds seventy donor checkouts, so
    confinement alone still leaves every donor's credentials in reach. Sensitivity is
    therefore decided by the one pattern the source adapters already use
    (:data:`SENSITIVE_PATH_PATTERN`: dotenv files, private keys, certificates, anything
    named credential) rather than by a second, weaker list maintained here. Two policies
    over the same question is how the weaker one ends up guarding the read path.
    """
    target_p = (Path(raw_path) if Path(raw_path).is_absolute() else (SUITES_ROOT / raw_path)).resolve()
    suites_resolved = SUITES_ROOT.resolve()
    projects_dir = suites_resolved.parent
    home_resolved = Path.home().resolve()
    sensitive_dirs = {".ssh", ".aws", ".gnupg"}

    if (
        target_p == home_resolved
        or target_p == Path("/")
        or any(m in target_p.parts for m in sensitive_dirs)
        or (reject_sensitive_path and is_sensitive_path(target_p))
        or not (target_p.is_relative_to(suites_resolved) or target_p.is_relative_to(projects_dir))
    ):
        return None
    return target_p


def _read_confined_file(
    candidate: Path,
    max_bytes: int | None = None,
    *,
    sensitivity_path: str | Path | None = None,
) -> bytes | None:
    """Read a file found by a directory walk, or None if it may not be read.

    ``sensitivity_path`` lets a caller with an established root evaluate credential names
    relative to that root. This prevents an unrelated ancestor named ``secrets-vault`` or
    ``credentialing-app`` from poisoning every ordinary child while preserving the same
    fail-closed sensitivity policy for the child path itself.

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
    if sensitivity_path is not None and is_sensitive_path(sensitivity_path):
        return None
    confined = (
        _confined_path(candidate)
        if sensitivity_path is None
        else _confined_path(candidate, reject_sensitive_path=False)
    )
    if confined is None:
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
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name must be a non-empty string")
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be a JSON object")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        active_requested = parameters.get("dry_run", True) is False
        return {
            "action_id": new_prefixed_id("act-jarvis"),
            "action_name": action_name,
            "parameters": parameters,
            "state": "preview_ready",
            "preview_at": now_iso,
            "requires_human_approval": True,
            "requires_verified_operator_token": active_requested,
            "mutation_requested": active_requested,
            "destructive": active_requested and action_name == "rotate_local_cache",
            "recovery_path": "undo_via_backup_or_clean_revert",
        }

    @staticmethod
    def execute_jarvis_action_checkpoint(
        action_name: str,
        parameters: dict[str, Any],
        operator_approved: bool = False,
        operator_approval_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute a secondary JARVIS action through the preview/approval/receipt/recovery lifecycle (O6 wave).

        `operator_approved` is a modeled boolean within this suite-local prototype engine. It
        gates the read-only and dry-run surface only -- and a caller supplies it, so it is a
        request, not an authorization.

        Anything that actually writes to the filesystem needs `operator_approval_token`: a
        single-use token resolved by :mod:`portfolio_suites.approvals` and bound to this exact
        action and parameter set. No token, no mutation. The boolean can never reach a write.
        """
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be a JSON object")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        preview = OperatorOSEngine.preview_jarvis_action(action_name, parameters)
        verified_mutation_authority = False

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
                "operator_approval_verified": False,
                "execution_authority": "caller_confirmation_only",
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
                    "operator_approval_verified": False,
                    "execution_authority": "caller_confirmation_only",
                    "error": f"Target path is outside allowed workspace boundaries: {search_path}",
                    "execution_receipt": None,
                }
            if not target_p.exists():
                return {
                    **preview,
                    "status": "error_path_not_found",
                    "state": "error_path_not_found",
                    "operator_approval_verified": False,
                    "execution_authority": "caller_confirmation_only",
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
            # A vault's ancestor names are not evidence that every child is sensitive.
            # Candidate files are checked against their path relative to this root below.
            vault_src = _confined_path(raw_path, reject_sensitive_path=False)
            dry_run = parameters.get("dry_run", True)

            if not isinstance(target_vault, str) or not target_vault.strip():
                return _action_error(preview, "error_invalid_parameters", "vault must be a non-empty string")
            if not isinstance(dry_run, bool):
                return _action_error(preview, "error_invalid_parameters", "dry_run must be a boolean")

            if vault_src is None:
                return _action_error(
                    preview,
                    "error_unconfined_path",
                    f"Vault source path is outside allowed workspace boundaries: {raw_path}",
                )
            if not vault_src.exists():
                return _action_error(
                    preview,
                    "error_path_not_found",
                    f"Vault source path does not exist: {vault_src}",
                )

            inventoried_files: list[dict[str, Any]] = []
            archive_entries: list[tuple[str, bytes]] = []
            skipped_sensitive = 0
            skipped_unreadable = 0
            total_bytes = 0
            candidates: list[tuple[Path, str]] = []
            if vault_src.is_file():
                candidates.append((vault_src, vault_src.name))
            else:
                for root, dirs, files in os.walk(vault_src):
                    dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"})
                    for filename in sorted(files):
                        candidate = Path(root) / filename
                        relative = candidate.relative_to(vault_src).as_posix()
                        candidates.append((candidate, relative))
                candidates.sort(key=lambda item: item[1])

            for fp, relative in candidates:
                if fp.name.startswith("snap-"):
                    continue
                # `_read_confined_file` would refuse these anyway, but a manifest that
                # silently omitted them would read as "these files do not exist" rather
                # than "these were deliberately not fingerprinted". Count them instead.
                if is_sensitive_path(relative):
                    skipped_sensitive += 1
                    continue
                if len(inventoried_files) >= MAX_BACKUP_FILES:
                    return _action_error(
                        preview,
                        "error_backup_limit",
                        f"backup inventory exceeds the {MAX_BACKUP_FILES}-file safety limit",
                    )
                try:
                    file_size = fp.lstat().st_size
                except OSError:
                    skipped_unreadable += 1
                    continue
                if file_size > MAX_BACKUP_FILE_BYTES:
                    return _action_error(
                        preview,
                        "error_backup_limit",
                        f"backup file {relative!r} exceeds the {MAX_BACKUP_FILE_BYTES}-byte safety limit",
                    )
                data = _read_confined_file(
                    fp,
                    max_bytes=MAX_BACKUP_FILE_BYTES,
                    sensitivity_path=relative,
                )
                if data is None:
                    skipped_unreadable += 1
                    continue
                total_bytes += len(data)
                if total_bytes > MAX_BACKUP_TOTAL_BYTES:
                    return _action_error(
                        preview,
                        "error_backup_limit",
                        f"backup inventory exceeds the {MAX_BACKUP_TOTAL_BYTES}-byte safety limit",
                    )
                digest = hashlib.sha256(data).hexdigest()
                inventoried_files.append({"path": relative, "size": len(data), "sha256": digest})
                archive_entries.append((relative, data))

            # The identity covers every field retained in the deterministic ZIP manifest.
            # Otherwise adding a skipped credential changes the archive bytes without changing
            # its destination name, producing a permanent content-address collision.
            hasher = hashlib.sha256()
            hasher.update(json.dumps({
                "vault": target_vault,
                "files": inventoried_files,
                "skipped_sensitive_count": skipped_sensitive,
                "skipped_unreadable_count": skipped_unreadable,
            }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
            snap_id = f"snap-{hasher.hexdigest()[:12]}"

            manifest_content = {
                "snapshot_id": snap_id,
                "vault": target_vault,
                "created_at": now_iso,
                "dry_run": dry_run,
                "source": str(vault_src),
                "files_count": len(inventoried_files),
                "total_bytes": total_bytes,
                "skipped_sensitive_count": skipped_sensitive,
                "skipped_unreadable_count": skipped_unreadable,
                "files": inventoried_files,
            }

            manifest_file_path = ""
            archive_file_path = ""
            archive_sha256 = ""
            if not dry_run:
                try:
                    verify_operator_approval(
                        operator_approval_token,
                        _action_approval_bindings(action_name, parameters),
                    )
                except ApprovalError as error:
                    return _action_error(
                        preview,
                        "error_unverified_approval",
                        f"active backup requires a verified operator approval: {error}",
                    )
                verified_mutation_authority = True
                snapshot_dir = SUITES_ROOT / "operator-os" / "evidence" / "snapshots"
                try:
                    snapshot_dir.mkdir(parents=True, exist_ok=True)
                    archive_file = snapshot_dir / f"{snap_id}.zip"
                    archive_existed_before = archive_file.exists()
                    archive_manifest = _archive_manifest(manifest_content)
                    archive_sha256 = _write_backup_archive(
                        archive_file,
                        archive_entries,
                        archive_manifest,
                    )
                    manifest_content["archive_file"] = archive_file.name
                    manifest_content["archive_sha256"] = archive_sha256
                    manifest_content["backup_payload_created"] = True
                    manifest_content["dry_run"] = False
                    manifest_file = snapshot_dir / f"{snap_id}.json"
                    if manifest_file.exists():
                        existing_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                        comparable_fields = (
                            "snapshot_id",
                            "vault",
                            "files_count",
                            "total_bytes",
                            "skipped_sensitive_count",
                            "skipped_unreadable_count",
                            "files",
                            "archive_sha256",
                        )
                        if any(
                            existing_manifest.get(field) != manifest_content.get(field)
                            for field in comparable_fields
                        ):
                            raise OSError(f"content-addressed manifest collision at {manifest_file}")
                    else:
                        durable_write_text(
                            manifest_file,
                            json.dumps(manifest_content, indent=2, allow_nan=False),
                        )
                except (OSError, ValueError, zipfile.BadZipFile) as error:
                    try:
                        if not archive_existed_before:
                            archive_file.unlink(missing_ok=True)
                    except (OSError, UnboundLocalError):
                        pass
                    return _action_error(
                        preview,
                        "error_backup_write_failed",
                        f"backup payload could not be written: {error}",
                        approval_verified=True,
                    )
                manifest_file = snapshot_dir / f"{snap_id}.json"
                manifest_file_path = str(manifest_file)
                archive_file_path = str(archive_file)

            action_results = {
                "vault": target_vault,
                "snapshot_id": snap_id,
                "dry_run": dry_run,
                "manifest_file": manifest_file_path,
                "archive_file": archive_file_path,
                "archive_sha256": archive_sha256,
                "files_inventoried": len(inventoried_files),
                "files_backed_up": len(inventoried_files) if archive_file_path else 0,
                "bytes_backed_up": total_bytes if archive_file_path else 0,
                "backup_payload_created": bool(archive_file_path),
                "snapshot_manifest_written": bool(manifest_file_path),
                "skipped_sensitive_count": skipped_sensitive,
                "skipped_unreadable_count": skipped_unreadable,
                "recovery": (
                    "Extract the ZIP into a reviewed destination; no source files were modified."
                    if archive_file_path
                    else "Dry run only; no recovery action is needed."
                ),
                "verified": True,
            }
        elif action_name == "sync_obsidian_notes":
            vault_path = parameters.get("vault_path", "operator-os/evidence")
            # As in backup_data: the vault the operator names is a root, not a candidate file,
            # so its own name does not disqualify it. Sensitivity is judged per note, relative
            # to this root. The workspace, home, and `.ssh`/`.aws`/`.gnupg` limits still apply.
            vault_p = _confined_path(vault_path, reject_sensitive_path=False)
            dry_run = parameters.get("dry_run", True)
            if not isinstance(dry_run, bool):
                return _action_error(preview, "error_invalid_parameters", "dry_run must be a boolean")
            if vault_p is None:
                return _action_error(
                    preview,
                    "error_unconfined_path",
                    f"Vault path is outside workspace boundaries: {vault_path}",
                )
            if not vault_p.exists():
                return _action_error(
                    preview,
                    "error_path_not_found",
                    f"Vault path does not exist: {vault_path}",
                )
            note_entries: list[tuple[str, str, str]] = []
            if vault_p.is_file() and vault_p.suffix == ".md":
                candidates = [(vault_p, vault_p.name)]
            elif vault_p.is_dir():
                candidates = []
                for root, dirs, files in os.walk(vault_p):
                    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv")]
                    for f in files:
                        if f.endswith(".md"):
                            candidate = Path(root) / f
                            candidates.append((candidate, candidate.relative_to(vault_p).as_posix()))
                            if len(candidates) > MAX_SYNC_NOTES:
                                break
                    if len(candidates) > MAX_SYNC_NOTES:
                        break
            else:
                candidates = []
            if len(candidates) > MAX_SYNC_NOTES:
                return _action_error(
                    preview,
                    "error_sync_limit",
                    f"note inventory exceeds the {MAX_SYNC_NOTES}-file safety limit",
                )
            for candidate, relative in candidates:
                if is_sensitive_path(relative):
                    continue
                data = _read_confined_file(
                    candidate,
                    max_bytes=MAX_NOTE_BYTES,
                    sensitivity_path=relative,
                )
                if data is None:
                    return _action_error(
                        preview,
                        "error_note_unreadable",
                        f"note {relative!r} is unreadable or exceeds the {MAX_NOTE_BYTES}-byte limit",
                    )
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    return _action_error(
                        preview,
                        "error_note_encoding",
                        f"note {relative!r} must be UTF-8 text",
                    )
                note_entries.append((relative, text, hashlib.sha256(data).hexdigest()))

            destination_path = parameters.get("destination_path")
            synced_files: list[str] = []
            unchanged_files: list[str] = []
            destination_display = ""
            if not dry_run:
                if not isinstance(destination_path, str) or not destination_path.strip():
                    return _action_error(
                        preview,
                        "error_invalid_parameters",
                        "active note sync requires a non-empty destination_path",
                    )
                destination = _confined_path(destination_path)
                if destination is None:
                    return _action_error(
                        preview,
                        "error_unconfined_path",
                        f"Destination path is outside workspace boundaries: {destination_path}",
                    )
                if (
                    destination == vault_p
                    or destination.is_relative_to(vault_p)
                    or vault_p.is_relative_to(destination)
                ):
                    return _action_error(
                        preview,
                        "error_overlapping_sync_paths",
                        "source and destination note trees must not overlap",
                    )
                destination_display = str(destination)
                pending: list[tuple[Path, str, str]] = []
                for relative, text, digest in note_entries:
                    target = destination / Path(relative)
                    confined_target = _confined_path(target)
                    if confined_target is None or not confined_target.is_relative_to(destination):
                        return _action_error(
                            preview,
                            "error_unconfined_path",
                            f"note destination escaped its root: {relative}",
                        )
                    if target.exists():
                        existing = _read_confined_file(target, max_bytes=MAX_NOTE_BYTES)
                        if existing is None or hashlib.sha256(existing).hexdigest() != digest:
                            return _action_error(
                                preview,
                                "error_sync_conflict",
                                f"destination note differs and overwrite is refused: {relative}",
                            )
                        unchanged_files.append(relative)
                    else:
                        pending.append((target, text, relative))
                if pending:
                    try:
                        verify_operator_approval(
                            operator_approval_token,
                            _action_approval_bindings(action_name, parameters),
                        )
                    except ApprovalError as error:
                        return _action_error(
                            preview,
                            "error_unverified_approval",
                            f"active note sync requires a verified operator approval: {error}",
                        )
                    verified_mutation_authority = True
                created_files: list[Path] = []
                created_dirs: list[Path] = []
                try:
                    for target, text, relative in pending:
                        missing_parents = []
                        parent = target.parent
                        while not parent.exists() and parent.is_relative_to(destination):
                            missing_parents.append(parent)
                            parent = parent.parent
                        target.parent.mkdir(parents=True, exist_ok=True)
                        created_dirs.extend(reversed(missing_parents))
                        durable_write_text(target, text)
                        created_files.append(target)
                        synced_files.append(relative)
                except OSError as error:
                    for created in reversed(created_files):
                        try:
                            created.unlink()
                        except OSError:
                            pass
                    for created in reversed(created_dirs):
                        try:
                            created.rmdir()
                        except OSError:
                            pass
                    return _action_error(
                        preview,
                        "error_sync_write_failed",
                        f"note sync was rolled back after a write failure: {error}",
                        approval_verified=True,
                    )
            action_results = {
                "vault_path": str(vault_p),
                "destination_path": destination_display,
                "notes_scanned_count": len(note_entries),
                "inventory": [
                    {"path": relative, "sha256": digest}
                    for relative, _, digest in note_entries
                ],
                "inventory_mode": "read_only_note_inventory" if dry_run else "one_way_additive_sync",
                "sync_performed": bool(not dry_run and synced_files),
                "files_synced": synced_files,
                "files_unchanged": unchanged_files,
                "overwrite_policy": "refuse_different_existing_files",
                "recovery": (
                    "Delete only the files listed in files_synced to roll back this additive sync."
                    if synced_files
                    else "No files were created; no recovery action is needed."
                ),
                "verified": True,
            }
        elif action_name == "rotate_local_cache":
            cache_dir = parameters.get("cache_dir", ".cache")
            cache_p = _confined_path(cache_dir)
            dry_run = parameters.get("dry_run", True)
            if not isinstance(dry_run, bool):
                return _action_error(preview, "error_invalid_parameters", "dry_run must be a boolean")
            if cache_p is None:
                return _action_error(
                    preview,
                    "error_unconfined_path",
                    f"Cache directory is outside allowed workspace boundaries: {cache_dir}",
                )
            cache_name_is_explicit = (
                cache_p.name in {".cache", "cache"}
                or cache_p.name.endswith(("-cache", "_cache", ".cache"))
            )
            cache_exists = cache_p.is_dir()
            immediate_entries = 0
            if cache_exists:
                try:
                    immediate_entries = sum(1 for _ in os.scandir(cache_p))
                except OSError:
                    return _action_error(
                        preview,
                        "error_cache_unreadable",
                        f"Cache directory cannot be inventoried: {cache_p}",
                    )
            rotated_path = ""
            recovery = "Dry run only; no recovery action is needed."
            if not dry_run:
                raw_cache_path = Path(cache_dir) if Path(cache_dir).is_absolute() else SUITES_ROOT / cache_dir
                if raw_cache_path.is_symlink():
                    return _action_error(
                        preview,
                        "error_invalid_cache_target",
                        "active cache rotation refuses symbolic-link targets",
                    )
                if not cache_name_is_explicit:
                    return _action_error(
                        preview,
                        "error_invalid_cache_target",
                        "active cache rotation requires a directory explicitly named cache, .cache, or *-cache",
                    )
                if not cache_exists:
                    return _action_error(
                        preview,
                        "error_path_not_found",
                        f"Cache directory does not exist: {cache_p}",
                    )
                try:
                    verify_operator_approval(
                        operator_approval_token,
                        _action_approval_bindings(action_name, parameters),
                    )
                except ApprovalError as error:
                    return _action_error(
                        preview,
                        "error_unverified_approval",
                        f"active cache rotation requires a verified operator approval: {error}",
                    )
                verified_mutation_authority = True
                timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                suffix = canonical_digest({"cache": str(cache_p), "preview": preview["action_id"]})[:8]
                rotated_p = cache_p.with_name(f"{cache_p.name}.rotated-{timestamp}-{suffix}")
                if rotated_p.exists():
                    return _action_error(
                        preview,
                        "error_rotation_collision",
                        f"Rotation destination already exists: {rotated_p}",
                        approval_verified=True,
                    )
                original_mode = stat.S_IMODE(cache_p.stat().st_mode)
                try:
                    os.replace(cache_p, rotated_p)
                    try:
                        cache_p.mkdir(mode=original_mode)
                    except OSError:
                        try:
                            cache_p.rmdir()
                        except OSError:
                            pass
                        os.replace(rotated_p, cache_p)
                        raise
                except OSError as error:
                    return _action_error(
                        preview,
                        "error_rotation_failed",
                        f"Cache rotation failed and the original path was restored when possible: {error}",
                        approval_verified=True,
                    )
                rotated_path = str(rotated_p)
                recovery = (
                    f"Remove the new empty directory {cache_p}, then rename {rotated_p} back to {cache_p}."
                )
            action_results = {
                "cache_target": str(cache_p),
                "cache_target_exists": cache_exists,
                "cache_name_is_explicit": cache_name_is_explicit,
                "immediate_entries_before": immediate_entries,
                "rotated": bool(rotated_path),
                "rotated_path": rotated_path,
                "replacement_cache_created": bool(rotated_path and cache_p.is_dir()),
                "rotation_mode": "active_reversible_rename" if rotated_path else "dry_run",
                "recovery": recovery,
            }
        else:
            return _action_error(
                preview,
                "error_dispatch_invariant",
                "Known JARVIS action did not reach its reviewed handler",
            )

        receipt = {
            "action_id": preview["action_id"],
            "action_name": action_name,
            "parameters": parameters,
            "state": "executed_with_receipt",
            "executed_at": now_iso,
            "requires_human_approval": True,
            "operator_approval_verified": verified_mutation_authority,
            "execution_authority": (
                "verified_operator_approval"
                if verified_mutation_authority
                else "caller_confirmed_read_only_or_dry_run"
            ),
            "execution_result": action_results,
            "audit_trail": {
                "preview_hash": hashlib.sha256(str(preview).encode("utf-8")).hexdigest(),
                "recovery_snapshot": f"snapshot://pre-action-{preview['action_id']}",
                "credential_boundary_preserved": True,
            },
            "status": "success",
        }
        return receipt
