"""Collision-resistant identifiers for audit and prototype receipts."""

from __future__ import annotations

import uuid


def new_prefixed_id(prefix: str) -> str:
    """Return a process- and time-independent identifier under a stable prefix."""
    if not prefix or any(character.isspace() for character in prefix):
        raise ValueError("identifier prefix must be a non-empty token")
    return f"{prefix}-{uuid.uuid4().hex}"
