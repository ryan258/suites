"""Independent operator-approval authority.

Nothing in this repository can mint an operator approval. Approvals are issued
out of band into a JSON store named by ``PORTFOLIO_OPERATOR_APPROVAL_STORE``;
with no store configured every token fails closed.

An approval is bound to the exact artifact it approves via ``payload_sha256``
(see :func:`canonical_digest`), and is consumed exactly once under an exclusive
lock held across the whole read/validate/consume sequence.
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

from .paths import durable_write_text

STORE_ENV = "PORTFOLIO_OPERATOR_APPROVAL_STORE"
TOKEN_PREFIX = "opa1"
APPROVAL_SCHEMA = "operator-approval-v1"
REQUIRED_STRINGS = ("approval_id", "schema", "token_sha256", "operation", "decision", "reviewer", "payload_sha256")


class ApprovalError(Exception):
    """Raised whenever a token cannot be resolved to a verified approval."""


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


def _read_store(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ApprovalError(f"approval store unreadable: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("approvals"), list):
        raise ApprovalError("approval store must contain an 'approvals' list")
    return document


def _durably_replace_store(path: Path, document: dict[str, Any]) -> None:
    """Atomically replace ``path``, reporting a write failure as an approval failure."""
    try:
        durable_write_text(path, json.dumps(document, indent=2))
    except OSError as error:
        raise ApprovalError(f"approval store is not writable, cannot consume: {error}") from error


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
    lock_path = path.with_name(path.name + ".lock")
    try:
        lock = open(lock_path, "a+")
    except OSError as error:
        raise ApprovalError(f"approval lock unavailable: {error}") from error
    with lock:
        # The whole read/validate/consume sequence runs under one exclusive lock:
        # flock serializes both threads (distinct fds) and processes.
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = _read_store(path)
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
        _durably_replace_store(path, document)
    return dict(record)
