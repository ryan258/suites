"""Operator OS reference prototype engine powering SourceRecord capture, PKOS indexing, Observer projections, and JARVIS actions.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. dotfiles, PKos).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import io
import os
import secrets
import stat
import zipfile
from pathlib import Path
import re
from typing import Any
from ..approvals import (
    ApprovalCommitUnverified,
    ApprovalError,
    canonical_digest,
    verify_operator_approval,
)
from ..contracts import SCHEMA_VERSION, validate_contract
from ..identifiers import new_prefixed_id
from ..paths import (
    SUITES_ROOT,
    ConfinementError,
    install_new_file,
    open_confined_directory,
    remove_fd_if_same,
    remove_installed_directory,
    remove_installed_file,
    rename_no_replace,
)
from ..provenance import is_sensitive_path


MAX_BACKUP_FILE_BYTES = 10 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 100 * 1024 * 1024
MAX_BACKUP_FILES = 10_000
MAX_NOTE_BYTES = 2 * 1024 * 1024
MAX_SYNC_NOTES = 1_000
MAX_AUDIT_FILES = 5_000


# Version is inside the digest so a v1 token cannot satisfy a v2 artifact binding.
APPROVAL_BINDING_VERSION = "operator-action-binding-v2"


def _action_approval_bindings(
    action_name: str,
    parameters: dict[str, Any],
    *,
    artifacts: Any = None,
) -> dict[str, str]:
    """Bind an approval to the exact artifacts an execution will write, not just its shape.

    ``artifacts`` is the inventory the caller detached *before* asking for authority: the
    content digest of every source byte it will install and the destination state it
    observed. Anything that changes between the inventory and the write therefore changes
    the digest the token has to match, and the execution fails closed instead of writing
    bytes nobody approved. Actions with no artifact inventory pass ``None`` and are bound to
    their parameters alone, which for them is the whole of what they do.
    """
    return {
        "operation": "jarvis_action_execution",
        "action_name": action_name,
        "decision": "approved",
        "payload_sha256": canonical_digest({
            "binding_version": APPROVAL_BINDING_VERSION,
            "action_name": action_name,
            "parameters": parameters,
            "artifacts": artifacts,
        }),
    }


def _action_error(
    preview: dict[str, Any],
    status: str,
    message: str,
    *,
    approval_verified: bool = False,
    approval_bindings: dict[str, str] | None = None,
    inspection_required: bool = False,
) -> dict[str, Any]:
    """Report a refusal, and where authority was the thing missing, say what to authorize.

    A caller told only "no verified approval" cannot act on that: the digest now covers
    detached content, so it is not something an operator can derive from the command they
    typed. Returning it turns the refusal into the first half of the real workflow -- run,
    read the digest, have it approved, run again -- without weakening anything, since the
    digest is a commitment to bytes the caller already holds.

    ``inspection_required`` marks post-commit uncertainty: the store replacement may have
    committed, so the authority must be inspected before any retry or reissue. That state
    must never be merged into an ordinary refusal whose safe answer is "get a new token".
    """
    detail = (
        {
            "approval_binding_version": APPROVAL_BINDING_VERSION,
            "approval_payload_sha256": approval_bindings["payload_sha256"],
        }
        if approval_bindings is not None
        else {}
    )
    if inspection_required:
        detail["approval_store_inspection_required"] = True
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
        **detail,
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


def _read_confined_bytes(
    directory_fd: int,
    name: str,
    *,
    max_bytes: int | None = MAX_BACKUP_TOTAL_BYTES,
) -> bytes | None:
    """Read ``name`` under ``directory_fd`` without following a link, or None if absent or unsupported."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        handle = os.open(name, flags, dir_fd=directory_fd)
    except (FileNotFoundError, OSError):
        return None
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode):
            return None
        if max_bytes is not None and info.st_size > max_bytes:
            return None
        with os.fdopen(os.dup(handle), "rb") as stream:
            payload = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        if max_bytes is not None and len(payload) > max_bytes:
            return None
        return payload
    except OSError:
        return None
    finally:
        os.close(handle)


def _install_confined_bytes(directory_fd: int, name: str, payload: bytes) -> tuple[int, int]:
    """Durably install ``payload`` as ``name`` under ``directory_fd``, never following a link.

    Durability expressed against an already-open directory rather than a pathname: the bytes land in a sibling temporary, get fsynced,
    and only then take the target's name. Anchoring it to the descriptor is what keeps an
    approved artifact inside the directory the approval was checked against, even if that
    directory's *pathname* is redirected while the write is running.

    The install is `linkat`, not `rename`: both callers are content-addressed and check the
    destination is absent first, but `os.rename` *replaces* whatever it finds, so a file
    created inside that window was silently destroyed by a helper whose whole claim is that
    it never overwrites. `os.link` makes the kernel decide existence and creation together
    and raises FileExistsError instead, which both callers already treat as a collision.

    Raising means nothing was installed. A failure *after* the name is taken -- a directory
    fsync that reports an error -- would otherwise leave the artifact on disk while the
    caller, which never received a return value, records nothing and reports only an error.

    Returns the (device, inode) of the object this call installed, so a caller unwinding a
    later failure can clean up through :func:`remove_fd_if_same` instead of an unlink by
    name -- which would delete whatever concurrent writer occupies the name by then.
    """
    temporary = f".{name}.{os.getpid()}-{secrets.token_hex(6)}.tmp"
    handle = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    installed = False
    installed_identity: tuple[int, int] | None = None
    try:
        info = os.fstat(handle)
        # linkat gives ``name`` this same inode, so the identity taken here is what the
        # undo below must match before it removes anything.
        installed_identity = (info.st_dev, info.st_ino)
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        installed = True
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        os.fsync(directory_fd)
    except BaseException as error:
        undo_failure = ""
        if installed:
            # The failing step is usually the directory fsync, which is precisely the window
            # in which another writer can take this name. Only our own inode may be removed.
            removal = remove_fd_if_same(directory_fd, name, installed_identity, directory=False)
            if not removal.removed:
                undo_failure = (
                    f"{name} was installed and could not be safely removed: "
                    f"{removal.conflict or 'the name no longer holds the installed object'}"
                )
                if removal.recovery_path:
                    undo_failure += f" (quarantined at {removal.recovery_path})"
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        if undo_failure:
            raise OSError(f"confined install failed and left an artifact behind -- {undo_failure}") from error
        raise
    assert installed_identity is not None
    return installed_identity


def _write_backup_archive(
    directory_fd: int,
    name: str,
    entries: list[tuple[str, bytes]],
    archive_manifest: dict[str, Any],
) -> tuple[str, bool, tuple[int, int] | None]:
    """Build a deterministic ZIP in memory and install it under ``directory_fd``.

    Returns its digest, whether this call installed it, and -- when it did -- the identity
    of the archive it installed. Every entry is already resident (the approval is bound to
    those exact bytes), so building the archive in memory costs nothing a temporary file
    would have saved and removes the last pathname from the write.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
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
    payload = buffer.getvalue()
    candidate_digest = hashlib.sha256(payload).hexdigest()
    existing = _read_confined_bytes(directory_fd, name, max_bytes=MAX_BACKUP_TOTAL_BYTES)
    if existing is not None:
        if hashlib.sha256(existing).hexdigest() != candidate_digest:
            raise OSError(f"content-addressed backup collision at {name}")
        return candidate_digest, False, None
    installed_identity = _install_confined_bytes(directory_fd, name, payload)
    return candidate_digest, True, installed_identity


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


def _write_anchor(target: Path) -> tuple[Path, Path]:
    """Split a confined destination into a trusted anchor and the path to walk from it.

    ``_confined_path`` has already established that the destination lies under the suites
    checkout or its sibling projects directory, but it established that about a *resolved
    string*. Handing the walk a trusted constant to start from is what lets every component
    below it be re-verified at open time instead of trusted from that earlier lookup.
    """
    suites_resolved = SUITES_ROOT.resolve()
    if target.is_relative_to(suites_resolved):
        return suites_resolved, target.relative_to(suites_resolved)
    projects_root = suites_resolved.parent
    return projects_root, target.relative_to(projects_root)


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

    O_NOFOLLOW on the final component is not sufficient on its own, because it says nothing
    about the *parents*. Exchanging an already-checked parent directory for a symlink
    between the confinement decision and the open redirects the read outside the workspace
    while every check still passes, and the backup path binds whatever it read into an
    approved archive. So the pathname is never reopened after being checked: the walk
    descends from the trusted anchor one component at a time under O_NOFOLLOW|O_DIRECTORY,
    and the file is opened relative to the parent descriptor that walk pinned.
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

    anchor = SUITES_ROOT.resolve().parent
    try:
        relative = confined.relative_to(anchor)
    except ValueError:
        return None
    *parents, name = relative.parts
    if not name:
        return None

    fd = None
    parent_fd = None
    try:
        parent_fd = open_confined_directory(anchor, Path(*parents) if parents else ".")
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
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
    except (OSError, ConfinementError):
        # ELOOP for a symlink at the file or any parent, ENXIO/EISDIR/ENOENT for anything
        # else the walk raced away.
        return None
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
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
            },
        }
        return validate_contract("SourceRecord", record)

    @staticmethod
    def project_to_observer(source_record: dict[str, Any], title: str, summary: str, body: str) -> str:
        """Create a derived Obsidian Observer note fenced against accidental re-ingestion."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        src_id = str(source_record.get("source_id", "unknown"))
        sha = str(source_record.get("sha256", "unknown"))

        # Serialize frontmatter fields safely with JSON string encoding to prevent frontmatter injection
        title_json = json.dumps(str(title), ensure_ascii=False)
        src_id_json = json.dumps(src_id, ensure_ascii=False)
        sha_json = json.dumps(sha, ensure_ascii=False)
        now_json = json.dumps(now_iso, ensure_ascii=False)
        clean_header_title = str(title).replace("\n", " ").strip()

        return f"""---
title: {title_json}
type: observer_projection
source_id: {src_id_json}
source_sha256: {sha_json}
projected_at: {now_json}
generator: "portfolio_suites.operator_os"
status: derived
fenced_from_reingestion: true
---

<!-- FENCE: DO NOT RE-INGEST INTO PKOS CANONICAL CORPUS -->

# {clean_header_title}

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
                            if len(candidate_files) >= MAX_AUDIT_FILES:
                                # Fail closed, same as backup_data. This action is HTTP-POST
                                # reachable, so an uncapped walk is a cheap denial of service
                                # even on loopback; a truncated report would also be a
                                # dishonest "no secrets found".
                                return _action_error(
                                    preview,
                                    "error_audit_limit",
                                    f"audit inventory exceeds the {MAX_AUDIT_FILES}-file safety limit",
                                )
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
                # Every byte that will enter the archive has already been read into
                # `archive_entries` and fingerprinted into `inventoried_files`; the approval
                # is bound to those fingerprints and to the content-addressed name they
                # produce, so the token authorizes this archive and no other.
                backup_bindings = _action_approval_bindings(
                    action_name,
                    parameters,
                    artifacts={
                        "kind": "backup_snapshot",
                        "snapshot_id": snap_id,
                        "vault": target_vault,
                        "source": str(vault_src),
                        "files": inventoried_files,
                        "total_bytes": total_bytes,
                        "skipped_sensitive_count": skipped_sensitive,
                        "skipped_unreadable_count": skipped_unreadable,
                    },
                )
                try:
                    verify_operator_approval(operator_approval_token, backup_bindings)
                except ApprovalCommitUnverified as error:
                    # The store replacement may already have spent this token. Retrying or
                    # reissuing before inspecting the authority is exactly the replay the
                    # uncertainty subclass exists to prevent.
                    return _action_error(
                        preview,
                        "error_approval_commit_unverified",
                        f"backup approval consumption is uncertain; inspect the approval "
                        f"store before retrying or reissuing: {error}",
                        inspection_required=True,
                    )
                except ApprovalError as error:
                    return _action_error(
                        preview,
                        "error_unverified_approval",
                        f"active backup requires a verified operator approval: {error}",
                        approval_bindings=backup_bindings,
                    )
                verified_mutation_authority = True
                # Backup payloads are runtime state, not evidence: they are dynamic,
                # regenerable outputs of an approved action, while a suite's `evidence/`
                # namespace is the canonical, ownership-checked record where every artifact
                # must be declared by exactly one wave or supporting entry. Writing
                # snapshots there made every backup invalidate the registry's own
                # ownership invariant, so they live in this suite's dedicated state
                # directory instead (ignored by Git; see .gitignore).
                #
                # The directory is a fixed location, but a fixed *pathname* is not a fixed
                # directory: a pre-existing or raced symlink at operator-os/state/backups
                # redirects every approved artifact written through it. The walk below
                # refuses a link at any component and pins the inode; nothing after it
                # resolves that pathname again.
                snapshot_relative = Path("operator-os") / "state" / "backups"
                snapshot_dir = SUITES_ROOT / snapshot_relative
                archive_name = f"{snap_id}.zip"
                archive_installed = False
                archive_identity: tuple[int, int] | None = None
                snapshot_fd: int | None = None
                try:
                    snapshot_fd = open_confined_directory(
                        SUITES_ROOT, snapshot_relative, create=True
                    )
                    archive_manifest = _archive_manifest(manifest_content)
                    (
                        archive_sha256,
                        archive_installed,
                        archive_identity,
                    ) = _write_backup_archive(
                        snapshot_fd,
                        archive_name,
                        archive_entries,
                        archive_manifest,
                    )
                    manifest_content["archive_file"] = archive_name
                    manifest_content["archive_sha256"] = archive_sha256
                    manifest_content["backup_payload_created"] = True
                    manifest_content["dry_run"] = False
                    manifest_name = f"{snap_id}.json"
                    manifest_file = snapshot_dir / manifest_name
                    existing_bytes = _read_confined_bytes(
                        snapshot_fd, manifest_name, max_bytes=MAX_BACKUP_FILE_BYTES
                    )
                    if existing_bytes is not None:
                        existing_manifest = json.loads(existing_bytes.decode("utf-8"))
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
                        _install_confined_bytes(
                            snapshot_fd,
                            manifest_name,
                            json.dumps(manifest_content, indent=2, allow_nan=False).encode("utf-8"),
                        )
                except (OSError, ValueError, ConfinementError, zipfile.BadZipFile) as error:
                    cleanup_note = ""
                    if archive_installed and snapshot_fd is not None and archive_identity is not None:
                        # Cleanup removes only the archive THIS run installed. An unlink by
                        # name would delete whatever concurrent writer claimed the name
                        # between the install and this failure.
                        removal = remove_fd_if_same(
                            snapshot_fd, archive_name, archive_identity, directory=False
                        )
                        if not removal.removed:
                            cleanup_note = (
                                f" The installed archive could not be safely removed"
                                f" ({removal.conflict or 'name no longer holds it'}); it"
                                f" remains for manual review."
                            )
                    return _action_error(
                        preview,
                        "error_backup_write_failed",
                        f"backup payload could not be written: {error}.{cleanup_note}",
                        approval_verified=True,
                    )
                finally:
                    if snapshot_fd is not None:
                        os.close(snapshot_fd)
                manifest_file_path = str(snapshot_dir / manifest_name)
                archive_file_path = str(snapshot_dir / archive_name)

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
            unchanged_entries: list[tuple[str, str]] = []
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
                pending: list[tuple[str, str, str]] = []
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
                        unchanged_entries.append((relative, digest))
                    else:
                        pending.append((relative, text, digest))
                if pending:
                    # The note bodies in `pending` were read and hashed before this point and
                    # are the bytes that will be installed. Binding those digests -- plus the
                    # destination and the files already observed there -- is what makes the
                    # token authorize this exact content: editing a source note after
                    # issuance changes the digest, and the token stops verifying.
                    sync_bindings = _action_approval_bindings(
                        action_name,
                        parameters,
                        artifacts={
                            "kind": "note_sync",
                            "source": str(vault_p),
                            "destination": str(destination),
                            "install": [
                                {"path": relative, "sha256": digest}
                                for relative, _, digest in pending
                            ],
                            "observed_unchanged": [
                                {"path": relative, "sha256": digest}
                                for relative, digest in sorted(unchanged_entries)
                            ],
                        },
                    )
                    try:
                        verify_operator_approval(operator_approval_token, sync_bindings)
                    except ApprovalCommitUnverified as error:
                        return _action_error(
                            preview,
                            "error_approval_commit_unverified",
                            f"note-sync approval consumption is uncertain; inspect the "
                            f"approval store before retrying or reissuing: {error}",
                            inspection_required=True,
                        )
                    except ApprovalError as error:
                        return _action_error(
                            preview,
                            "error_unverified_approval",
                            f"active note sync requires a verified operator approval: {error}",
                            approval_bindings=sync_bindings,
                        )
                    verified_mutation_authority = True
                # Every write is anchored back to a trusted constant and re-walked under
                # O_NOFOLLOW. The `exists()` conflict check above is a *report* of what the
                # operator was shown, not the guarantee: an approval verification takes real
                # time, and a checked destination directory can be exchanged for a symlink,
                # or a checked-absent file created, while it runs. The guarantee is here --
                # no component is followed, and the file itself is created O_EXCL, so an
                # existing file is a refusal rather than a silent overwrite.
                anchor, anchor_relative = _write_anchor(destination)
                # Names alone are not enough to undo a write: see `remove_installed_file`.
                # Each entry carries the identity the object had when this run created it.
                created_files: list[tuple[str, tuple[int, int]]] = []
                created_dirs: list[tuple[str, tuple[int, int]]] = []
                destination_fd: int | None = None

                def _roll_back_sync() -> tuple[list[str], list[str]]:
                    """Undo this run's installs and report any quarantine recovery conflicts."""
                    removed: list[str] = []
                    conflicts: list[str] = []
                    for created, identity in reversed(created_files):
                        try:
                            outcome = remove_installed_file(
                                anchor,
                                Path(anchor_relative) / created,
                                identity,
                            )
                            if outcome:
                                removed.append(created)
                            elif outcome.conflict:
                                recovery = (
                                    f"; recoverable object: {outcome.recovery_path}"
                                    if outcome.recovery_path
                                    else ""
                                )
                                conflicts.append(f"{created}: {outcome.conflict}{recovery}")
                        except (OSError, ConfinementError) as error:
                            conflicts.append(f"{created}: rollback path could not be inspected ({error})")
                    for created, identity in reversed(created_dirs):
                        try:
                            outcome = remove_installed_directory(
                                anchor,
                                Path(anchor_relative) / created,
                                identity,
                            )
                            if outcome.conflict:
                                recovery = (
                                    f"; recoverable object: {outcome.recovery_path}"
                                    if outcome.recovery_path
                                    else ""
                                )
                                conflicts.append(f"{created}: {outcome.conflict}{recovery}")
                        except (OSError, ConfinementError) as error:
                            conflicts.append(f"{created}: rollback path could not be inspected ({error})")
                    return removed, conflicts
                # Nothing to install is nothing to authorize, and nothing to authorize means
                # no token was verified above -- so this branch must not mutate either.
                # `create=True` would otherwise build the destination tree on an empty or
                # ineligible source without any approval ever being checked.
                try:
                    if pending:
                        destination_fd = open_confined_directory(
                            anchor, anchor_relative, create=True
                        )
                        for relative, text, _ in pending:
                            installed = install_new_file(destination_fd, relative, text)
                            created_dirs.extend(installed.directories)
                            created_files.append((relative, installed.identity))
                            synced_files.append(relative)
                except (OSError, ConfinementError) as error:
                    conflict = isinstance(error, FileExistsError)
                    # `dir_fd` anchors only the first lookup, so unlinking a slash-containing
                    # relative name here would still follow every intermediate component --
                    # including one exchanged for a symlink since it was created. Rollback
                    # re-walks from the trusted anchor under the same O_NOFOLLOW discipline
                    # installation used and touches only final basenames.
                    _, rollback_conflicts = _roll_back_sync()
                    synced_files.clear()
                    rollback_note = (
                        f"; rollback conflicts: {'; '.join(rollback_conflicts)}"
                        if rollback_conflicts
                        else ""
                    )
                    return _action_error(
                        preview,
                        "error_sync_conflict" if conflict else "error_sync_write_failed",
                        (
                            f"destination note appeared during execution and overwrite is refused: {error}"
                            if conflict
                            else f"note sync was rolled back after a write failure: {error}"
                        )
                        + rollback_note,
                        approval_verified=True,
                    )
                finally:
                    if destination_fd is not None:
                        os.close(destination_fd)

                # A file recorded as already identical was hashed before the approval was
                # verified, and verification takes real time. Reporting those pathnames
                # without rechecking them makes `files_unchanged` a description of the
                # destination as it was, not as it is -- so the receipt is re-earned here,
                # through the same no-follow discipline the writes used.
                for relative, digest in unchanged_entries:
                    observed = Path(anchor_relative) / relative
                    try:
                        parent_fd = open_confined_directory(anchor, observed.parent)
                        try:
                            current = _read_confined_bytes(
                                parent_fd, observed.name, max_bytes=MAX_NOTE_BYTES
                            )
                        finally:
                            os.close(parent_fd)
                    except (OSError, ConfinementError):
                        current = None
                    if current is None or hashlib.sha256(current).hexdigest() != digest:
                        # This check runs after the installs above, so failing it means the
                        # run is being abandoned with its own new files already on disk.
                        # Returning straight out left them installed under an error status
                        # and named none of them, so nothing downstream could clean up.
                        removed, rollback_conflicts = _roll_back_sync()
                        synced_files.clear()
                        rollback_note = (
                            f"; rollback conflicts: {'; '.join(rollback_conflicts)}"
                            if rollback_conflicts
                            else ""
                        )
                        return _action_error(
                            preview,
                            "error_sync_conflict",
                            (
                                f"destination note changed while the sync ran: {relative}; "
                                f"rolled back {len(removed)} newly installed note(s)"
                                + (f": {', '.join(removed)}" if removed else "")
                                + rollback_note
                            ),
                            approval_verified=verified_mutation_authority,
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
                "files_unchanged": [relative for relative, _ in unchanged_entries],
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
                # The rotation is decided here, on a descriptor, and carried out on that same
                # descriptor's parent. A path-based `stat` and `os.replace` after the approval
                # returns would re-resolve the name across the whole verification window, which
                # is long enough for the checked directory to be exchanged for another one --
                # or a symlink -- under the same pathname. O_NOFOLLOW is also what refuses a
                # symbolic-link target now, in the same lookup that pins the inode.
                anchor, anchor_relative = _write_anchor(cache_p)
                directory_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
                parent_fd: int | None = None
                cache_fd: int | None = None
                try:
                    parent_fd = open_confined_directory(anchor, anchor_relative.parent)
                    cache_fd = os.open(cache_p.name, directory_flags, dir_fd=parent_fd)
                    approved_identity = os.fstat(cache_fd)
                    original_mode = stat.S_IMODE(approved_identity.st_mode)

                    # Binding to `parameters` alone binds to a *pathname*. A token issued
                    # for the directory the operator inventoried stayed valid after that
                    # directory was replaced, and the replacement -- which no operator ever
                    # saw -- was what got rotated. The identity goes in the payload so a
                    # swap changes the digest and the token simply stops matching.
                    # Deliberately not the entry count: a cache is written to constantly,
                    # and binding to its contents would expire every token before use.
                    rotation_bindings = _action_approval_bindings(
                        action_name,
                        parameters,
                        artifacts={
                            "kind": "cache_rotation",
                            "cache": str(cache_p),
                            "device": approved_identity.st_dev,
                            "inode": approved_identity.st_ino,
                        },
                    )
                    try:
                        verify_operator_approval(operator_approval_token, rotation_bindings)
                    except ApprovalCommitUnverified as error:
                        return _action_error(
                            preview,
                            "error_approval_commit_unverified",
                            f"cache-rotation approval consumption is uncertain; inspect the "
                            f"approval store before retrying or reissuing: {error}",
                            inspection_required=True,
                        )
                    except ApprovalError as error:
                        return _action_error(
                            preview,
                            "error_unverified_approval",
                            f"active cache rotation requires a verified operator approval: {error}",
                            approval_bindings=rotation_bindings,
                        )
                    verified_mutation_authority = True

                    # `os.rename` acts on the name, so the approved inode still has to be the
                    # one that name reaches when the rename runs.
                    current_fd = os.open(cache_p.name, directory_flags, dir_fd=parent_fd)
                    try:
                        current_identity = os.fstat(current_fd)
                    finally:
                        os.close(current_fd)
                    if (current_identity.st_dev, current_identity.st_ino) != (
                        approved_identity.st_dev,
                        approved_identity.st_ino,
                    ):
                        return _action_error(
                            preview,
                            "error_invalid_cache_target",
                            "cache directory was replaced while the approval was being verified",
                            approval_verified=True,
                        )

                    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    suffix = canonical_digest({"cache": str(cache_p), "preview": preview["action_id"]})[:8]
                    rotated_name = f"{cache_p.name}.rotated-{timestamp}-{suffix}"
                    rotated_p = cache_p.with_name(rotated_name)
                    try:
                        # The rotation is a no-replace rename, not an absence check followed
                        # by a replacing one: POSIX rename replaces an empty destination
                        # directory, so a directory created in the gap between the check and
                        # the move used to be destroyed while the action reported success.
                        # renameat2(RENAME_NOREPLACE)/renameatx_np(RENAME_EXCL) make the
                        # kernel decide existence and movement in the same operation.
                        rename_no_replace(
                            cache_p.name,
                            rotated_name,
                            directory_fd=parent_fd,
                        )
                    except FileExistsError:
                        return _action_error(
                            preview,
                            "error_rotation_collision",
                            f"Rotation destination already exists: {rotated_p}",
                            approval_verified=True,
                        )
                    except OSError as error:
                        return _action_error(
                            preview,
                            "error_rotation_failed",
                            f"Cache rotation failed without moving anything: {error}",
                            approval_verified=True,
                        )
                    try:
                        # The no-replace move acts on the name, so the approved inode still
                        # has to be the one that name reached when it ran. There is no
                        # rename-by-inode, so the order is inverted: move first, then
                        # confirm through a descriptor that what moved is the approved
                        # object, and put it back -- never over anyone -- if it is not. The
                        # rotated name is unique to this run, so the object is pinned under
                        # a name no other writer is competing for.
                        moved_fd = os.open(rotated_name, directory_flags, dir_fd=parent_fd)
                        try:
                            moved_identity = os.fstat(moved_fd)
                        finally:
                            os.close(moved_fd)
                        if (moved_identity.st_dev, moved_identity.st_ino) != (
                            approved_identity.st_dev,
                            approved_identity.st_ino,
                        ):
                            # Rolling back with a replacing rename destroys whatever took the
                            # cache name in the meantime -- and something did, or the identity
                            # would have matched. Refuse replacement: if the name is occupied,
                            # both objects survive and the receipt says where the rotated one is.
                            try:
                                rename_no_replace(
                                    rotated_name,
                                    cache_p.name,
                                    directory_fd=parent_fd,
                                )
                            except OSError as restore_error:
                                return _action_error(
                                    preview,
                                    "error_invalid_cache_target",
                                    "cache directory was replaced before it could be rotated; the "
                                    f"unapproved object could not be restored to '{cache_p.name}' "
                                    f"without overwriting its current occupant ({restore_error}). "
                                    f"It remains preserved at '{rotated_p}'.",
                                    approval_verified=True,
                                )
                            return _action_error(
                                preview,
                                "error_invalid_cache_target",
                                "cache directory was replaced before it could be rotated",
                                approval_verified=True,
                            )
                        created_replacement = False
                        try:
                            os.mkdir(cache_p.name, original_mode, dir_fd=parent_fd)
                            created_replacement = True
                        except FileExistsError:
                            # A competing writer created a directory at cache_p.name; do not delete it!
                            # The rotated original remains safely preserved at rotated_name.
                            return _action_error(
                                preview,
                                "error_cache_collision",
                                f"A competing directory was created at '{cache_p.name}' after rotation; the rotated backup remains preserved at '{rotated_p}'.",
                                approval_verified=True,
                            )
                        except OSError:
                            if created_replacement:
                                try:
                                    os.rmdir(cache_p.name, dir_fd=parent_fd)
                                except OSError:
                                    pass
                            try:
                                # Restoration must not replace either: an uncooperative
                                # writer claiming the cache name during this window keeps
                                # it, and the rotated original stays preserved under its
                                # unique recovery name instead of being lost or copied
                                # over something else.
                                rename_no_replace(
                                    rotated_name,
                                    cache_p.name,
                                    directory_fd=parent_fd,
                                )
                            except OSError:
                                return _action_error(
                                    preview,
                                    "error_rotation_failed",
                                    "Cache rotation failed and the replacement directory "
                                    f"could not be restored; the rotated original is "
                                    f"preserved at '{rotated_p}' and must be renamed back to "
                                    f"'{cache_p.name}' manually once its current occupant "
                                    "is resolved.",
                                    approval_verified=True,
                                )
                            raise
                    except OSError as error:
                        return _action_error(
                            preview,
                            "error_rotation_failed",
                            f"Cache rotation failed and the original path was restored when possible: {error}",
                            approval_verified=True,
                        )
                except (OSError, ConfinementError) as error:
                    return _action_error(
                        preview,
                        "error_invalid_cache_target",
                        f"cache directory could not be opened without following a link: {error}",
                    )
                finally:
                    for open_fd in (cache_fd, parent_fd):
                        if open_fd is not None:
                            os.close(open_fd)
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
