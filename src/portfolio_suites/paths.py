"""Canonical checkout paths shared across the local control plane."""

from __future__ import annotations

import os
from pathlib import Path


SUITES_ROOT = (
    Path(os.environ["SUITES_ROOT"]).resolve()
    if "SUITES_ROOT" in os.environ
    else Path(__file__).resolve().parents[2]
)
PROJECTS_ROOT = SUITES_ROOT.parent
