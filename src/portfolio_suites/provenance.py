"""Shared provenance predicates used by registry, engines, and source adapters."""

from __future__ import annotations

import re
import os
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

# One sensitivity policy for the whole control plane. Adapters use it to redact donor paths
# out of evidence; the Operator OS engine uses it to refuse reading those files at all.
# Keeping the two in agreement is the point: a second, weaker list guarding the read path is
# how a file that evidence declines to *name* becomes one the engine happily *opens*.
SENSITIVE_PATH_PATTERN = re.compile(
    r"(^|/)\.env($|\.)|(^|/)\.netrc$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$"
    r"|\.(pem|p12|pfx|key)$|credential|secret|token[_-]?store"
    r"|(^|/)\.(bash|zsh|sh)_history$|(^|/)\.git-credentials$"
    r"|(^|/)\.npmrc$|(^|/)\.pypirc$|(^|/)\.aws/credentials$"
    r"|(^|/)\.docker/config\.json$",
    re.IGNORECASE,
)

GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SHA256_DIGEST = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_VALUES = frozenset(
    {"", "unknown", "unavailable", "none", "null", "n/a", "na", "not available", "missing"}
)


def is_sensitive_path(path: Any) -> bool:
    """Whether a path names credential material that must not be read or recorded."""
    if not isinstance(path, (str, os.PathLike)):
        return True
    try:
        rendered = Path(path).as_posix()
    except (TypeError, ValueError, OSError):
        return True
    if not rendered or "\x00" in rendered:
        return True
    return bool(SENSITIVE_PATH_PATTERN.search(rendered))


def _safe_tested_path(path: Any) -> bool:
    if not isinstance(path, str) or not path or "\x00" in path:
        return False
    candidate = PurePosixPath(path.replace("\\", "/"))
    return (
        not candidate.is_absolute()
        and ".." not in candidate.parts
        and not is_sensitive_path(path)
    )


def is_meaningful_git_fingerprint(value: Any) -> bool:
    """Return whether a fingerprint identifies a real revision and inspected content."""
    if not isinstance(value, dict):
        return False
    branch = value.get("branch")
    head = value.get("head")
    tested = value.get("tested_files_fingerprint")
    if (
        not isinstance(branch, str)
        or branch.strip().lower() in PLACEHOLDER_VALUES
        or not isinstance(head, str)
        or not GIT_OBJECT_ID.fullmatch(head)
        or not isinstance(tested, dict)
        or not tested
    ):
        return False
    return all(
        _safe_tested_path(path)
        and isinstance(digest, str)
        and SHA256_DIGEST.fullmatch(digest) is not None
        for path, digest in tested.items()
    )
