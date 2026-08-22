"""Canonical checkout paths shared across the local control plane."""

from __future__ import annotations

import os
from pathlib import Path

# The control plane operates on a suites *checkout*: suite manifests, contract schemas,
# the portfolio ledger, and retained evidence are working state, not distributable data.
# So the root is derived from this file's location, which is right for an editable
# checkout and meaningless once the package is installed into site-packages. Rather than
# hand callers a plausible-looking path that resolves nothing, an installed run is told
# exactly what to set.
_LEDGER_MARKER = Path("portfolio") / "project-ledger.json"


def _resolve_suites_root() -> Path:
    override = os.environ.get("SUITES_ROOT")
    if override:
        root = Path(override).resolve()
        if not (root / _LEDGER_MARKER).is_file():
            raise RuntimeError(
                f"SUITES_ROOT={override} is not a suites checkout: {_LEDGER_MARKER} is missing."
            )
        return root

    derived = Path(__file__).resolve().parents[2]
    if not (derived / _LEDGER_MARKER).is_file():
        raise RuntimeError(
            "portfolio_suites operates on a suites checkout, and this installation is not "
            f"inside one ({derived} has no {_LEDGER_MARKER}). Set SUITES_ROOT to your "
            "suites checkout, e.g. SUITES_ROOT=~/Projects/suites suites validate --fast"
        )
    return derived


SUITES_ROOT = _resolve_suites_root()
PROJECTS_ROOT = SUITES_ROOT.parent
