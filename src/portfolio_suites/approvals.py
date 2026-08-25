"""Independent operator-approval authority.

Nothing in this repository can mint an operator approval. Approvals are issued
out of band into a JSON store named by ``PORTFOLIO_OPERATOR_APPROVAL_STORE``;
with no store configured every token fails closed.

An approval is bound to the exact artifact it approves via ``payload_sha256``
(see :func:`canonical_digest`), and is consumed exactly once: the whole
read/validate/consume sequence runs under an exclusive sidecar lock, and the commit
itself is a compare-and-swap on the store's identity, so an issuer that does not take
this module's lock can still replace the store concurrently without losing its newly
issued approvals -- the consumption is refused instead (see
:mod:`portfolio_suites.txn`).
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import stat

from .txn import (
    CommitUncertain,
    OccupantConflict,
    commit_replacement,
    discard_temp,
    write_temp_payload,
)

STORE_ENV = "PORTFOLIO_OPERATOR_APPROVAL_STORE"
TOKEN_PREFIX = "opa1"
APPROVAL_SCHEMA = "operator-approval-v1"
REQUIRED_STRINGS = ("approval_id", "schema", "token_sha256", "operation", "decision", "reviewer", "payload_sha256")


class ApprovalError(Exception):
    """Raised whenever a token cannot be resolved to a verified approval."""


class ApprovalCommitUnverified(ApprovalError):
    """The store replacement committed; a durability or naming check after it did not.

    "Cannot consume" and "may already be spent" are different facts for an operator. The
    replacement is the commit point: once it succeeds the token is gone from the store even
    if the directory fsync or the canonical-path recheck then fails. Reporting that as a
    plain failure invites a retry against a token that is already consumed.

    Subclasses :class:`ApprovalError` so every existing caller still fails closed.
    """

    def __init__(self, message: str, approval_id: str | None = None) -> None:
        self.approval_id = approval_id
        named = f"approval '{approval_id}': " if approval_id else ""
        super().__init__(
            f"{named}{message}. The store replacement already committed, so this approval "
            "may already be spent -- verify the store before reissuing or retrying."
        )


def token_sha256(token: str) -> str:
    """Digest an issued token for storage. Issuers store this, never the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def canonical_digest(payload: Any) -> str:
    """SHA-256 over a canonical JSON encoding of the exact artifact being approved.

    Callers define the complete semantic payload before adding metadata created
    by the approval operation itself.
    """
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _store_path() -> Path:
    raw = os.environ.get(STORE_ENV)
    if not raw:
        raise ApprovalError(f"no approval authority configured ({STORE_ENV} unset)")
    return Path(raw)


def _open_authority_dir(path: Path) -> int:
    parent = path.parent
    if parent.is_symlink():
        raise ApprovalError(f"approval store directory '{parent}' cannot be a symlink")
    try:
        return os.open(parent, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0))
    except OSError as error:
        raise ApprovalError(f"approval store directory unreadable: {error}") from error


def _read_store_fd(filename: str, dir_fd: int) -> tuple[dict[str, Any], tuple[int, int], str, int]:
    try:
        store_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as error:
        raise ApprovalError(f"approval store unreadable: {error}") from error
    try:
        info = os.fstat(store_fd)
        if stat.S_ISLNK(info.st_mode):
            raise ApprovalError("approval store cannot be a symlink")
        if info.st_nlink > 1:
            raise ApprovalError(f"approval store has multiple hard links ({info.st_nlink})")
        with os.fdopen(os.dup(store_fd), "rb") as stream:
            content = stream.read()
            digest = hashlib.sha256(content).hexdigest()
            document = json.loads(content.decode("utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("approvals"), list):
            raise ApprovalError("approval store must contain an 'approvals' list")
        return document, (info.st_dev, info.st_ino), digest, info.st_mode
    except (OSError, ValueError) as error:
        raise ApprovalError(f"approval store unreadable: {error}") from error
    finally:
        os.close(store_fd)


def _durably_replace_store_confined(
    filename: str,
    dir_fd: int,
    document: dict[str, Any],
    expected_digest: str,
    mode: int,
    approval_id: str | None = None,
) -> None:
    """Commit the consumed-against document over the store this transaction read.

    The replacement is a compare-and-swap, not a replacing rename: it commits only if the
    object currently at the store name has the exact content digest ``_read_store_fd``
    validated. An out-of-band issuer that does not share this module's sidecar lock can
    therefore replace or edit the store with newly issued approvals between the read and
    the commit and lose nothing -- its document is preserved, the consumption is refused
    as a plain retryable failure, and no pre-commit ``stat`` is being asked to prove
    anything about a rename that happens later. See :mod:`portfolio_suites.txn` for the
    mechanism.
    """
    text = json.dumps(document, indent=2)
    try:
        temp = write_temp_payload(dir_fd, filename, text.encode("utf-8"), mode=stat.S_IMODE(mode))
    except OSError as error:
        raise ApprovalError(f"approval store is not writable, cannot consume: {error}") from error

    try:
        commit_replacement(dir_fd, filename, temp, expected_digest=expected_digest)
    except OccupantConflict as error:
        raise ApprovalError(
            "the approval store changed after it was read; nothing was consumed and every "
            f"concurrent document was preserved ({error})"
        ) from error
    except CommitUncertain as error:
        raise ApprovalCommitUnverified(str(error), approval_id) from error
    except BaseException as error:
        # The commit owns the candidate once invoked; any other failure path leaves the
        # scratch bytes behind unless this caller cleans them up itself.
        discard_temp(dir_fd, temp)
        if isinstance(error, OSError):
            raise ApprovalError(f"approval store is not writable, cannot consume: {error}") from error
        raise


def _aware(record: dict[str, Any], field: str) -> datetime.datetime:
    try:
        moment = datetime.datetime.fromisoformat(str(record.get(field)))
    except ValueError as error:
        raise ApprovalError(f"approval has no parseable {field}") from error
    if moment.tzinfo is None:
        raise ApprovalError(f"approval {field} must be timezone aware")
    return moment


def _validated(record: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    """Fully validate an authority record. Raises before any consumption."""
    for field in REQUIRED_STRINGS:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ApprovalError(f"approval field '{field}' must be a non-empty string")
    if record["schema"] != APPROVAL_SCHEMA:
        raise ApprovalError(f"approval schema must be {APPROVAL_SCHEMA}, not {record['schema']!r}")

    for key, expected in bindings.items():
        if key not in record:
            raise ApprovalError(f"approval '{record['approval_id']}' is not bound to {key}")
        if record[key] != expected:
            raise ApprovalError(f"approval '{record['approval_id']}' {key} is bound to {record[key]!r}, not {expected!r}")

    issued_at, expires_at = _aware(record, "issued_at"), _aware(record, "expires_at")
    now = datetime.datetime.now(datetime.timezone.utc)
    if issued_at > now:
        raise ApprovalError(f"approval '{record['approval_id']}' is issued in the future")
    if expires_at <= issued_at:
        raise ApprovalError(f"approval '{record['approval_id']}' expires at or before it was issued")
    if expires_at <= now:
        raise ApprovalError(f"approval '{record['approval_id']}' expired at {record['expires_at']}")
    if record.get("consumed"):
        raise ApprovalError(f"approval '{record['approval_id']}' was already consumed (replay)")
    return record


def verify_operator_approval(token: str | None, bindings: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``token`` against the configured authority, bound to ``bindings``.

    Every key in ``bindings`` must be present on the stored record and equal.
    Returns a copy of the verified record, including the ``consumed_at`` and
    ``consumed_bindings`` audit fields this consumption stamped onto the store.
    Raises ApprovalError on any failure.
    """
    if not isinstance(token, str) or token.count(".") != 2 or not token.startswith(f"{TOKEN_PREFIX}."):
        raise ApprovalError(f"token must look like {TOKEN_PREFIX}.<approval_id>.<secret>")
    _, approval_id, secret = token.split(".")
    if not approval_id or not secret:
        raise ApprovalError("token is missing an approval id or secret")

    path = _store_path()
    if path.is_symlink():
        raise ApprovalError(f"approval store '{path}' cannot be a symlink")

    dir_fd = _open_authority_dir(path)
    try:
        lock_name = path.name + ".lock"
        try:
            lock_fd = os.open(lock_name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
        except OSError as error:
            raise ApprovalError(f"approval lock unavailable: {error}") from error
        try:
            # The whole read/validate/consume sequence runs under one exclusive lock:
            # flock serializes both threads (distinct fds) and processes.
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                document, identity, digest, mode = _read_store_fd(path.name, dir_fd)
                matches = [r for r in document["approvals"] if isinstance(r, dict) and r.get("approval_id") == approval_id]
                if len(matches) != 1:
                    raise ApprovalError(f"approval '{approval_id}' is not issued by this authority")
                record = matches[0]
                if not hmac.compare_digest(str(record.get("token_sha256") or ""), token_sha256(token)):
                    raise ApprovalError(f"approval '{approval_id}' secret does not match the issued digest")

                _validated(record, bindings)  # raises before anything is consumed
                record["consumed"] = True
                # A consumed approval that does not say when, or against what, cannot be audited
                # after the fact -- the store would show only that the single use was spent.
                record["consumed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                record["consumed_bindings"] = {key: str(value) for key, value in sorted(bindings.items())}
                _durably_replace_store_confined(
                    path.name, dir_fd, document, digest, mode, approval_id
                )
                try:
                    current_parent_stat = os.stat(path.parent)
                    pinned_dir_stat = os.fstat(dir_fd)
                    if (current_parent_stat.st_dev, current_parent_stat.st_ino) != (
                        pinned_dir_stat.st_dev,
                        pinned_dir_stat.st_ino,
                    ):
                        raise ApprovalCommitUnverified(
                            "approval authority directory was rebound or detached during consumption",
                            approval_id,
                        )
                    installed_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
                    try:
                        installed_stat = os.fstat(installed_fd)
                    finally:
                        os.close(installed_fd)
                    current_file_stat = os.stat(path)
                    if (current_file_stat.st_dev, current_file_stat.st_ino) != (
                        installed_stat.st_dev,
                        installed_stat.st_ino,
                    ):
                        raise ApprovalCommitUnverified(
                            "approval authority store file was rebound or replaced during consumption",
                            approval_id,
                        )
                except OSError as error:
                    raise ApprovalCommitUnverified(
                        f"authority verification failed after store replacement: {error}",
                        approval_id,
                    ) from error
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    finally:
        os.close(dir_fd)
    return dict(record)
