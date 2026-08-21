"""Shared provenance predicates used by registry and source adapters."""

from __future__ import annotations

from typing import Any


def is_meaningful_git_fingerprint(value: Any) -> bool:
    """Return whether a fingerprint identifies a real revision and inspected content."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("branch"), str)
        and value.get("branch") not in {"", "unknown"}
        and isinstance(value.get("head"), str)
        and value.get("head") not in {"", "unknown"}
        and isinstance(value.get("tested_files_fingerprint"), dict)
        and bool(value.get("tested_files_fingerprint"))
    )
