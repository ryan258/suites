"""Shared provenance predicates used by registry, engines, and source adapters."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# One sensitivity policy for the whole control plane. Adapters use it to redact donor paths
# out of evidence; the Operator OS engine uses it to refuse reading those files at all.
# Keeping the two in agreement is the point: a second, weaker list guarding the read path is
# how a file that evidence declines to *name* becomes one the engine happily *opens*.
SENSITIVE_PATH_PATTERN = re.compile(
    r"(^|/)\.env($|\.)|(^|/)\.netrc$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$"
    r"|\.(pem|p12|pfx|key)$|credential|(^|/)\.(bash|zsh|sh)_history$",
    re.IGNORECASE,
)


def is_sensitive_path(path: Any) -> bool:
    """Whether a path names credential material that must not be read or recorded."""
    return bool(SENSITIVE_PATH_PATTERN.search(Path(path).as_posix()))


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
