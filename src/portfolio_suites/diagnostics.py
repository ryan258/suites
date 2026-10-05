"""Offline prerequisite inventory; no provider, donor, browser, or mutation probes."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .paths import SUITES_ROOT

PACKAGE_ASSETS = (
    "web/index.html", "web/app.js", "web/catalog.js", "web/styles.css",
    "adapters/donor_wcag_331_browser_probe.mjs",
)


def inspect_environment(root: Path = SUITES_ROOT, package: Path | None = None) -> dict[str, Any]:
    """Report presence and capability only. Never expose config values or private paths."""
    package = package or Path(__file__).parent
    checks: list[dict[str, str]] = []

    def check(name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        checks.append({"name": name, "status": "available" if ok else ("blocked" if required else "optional_missing"),
                       "detail": detail})

    check("python", sys.version_info >= (3, 11), "Requires Python 3.11 or newer.")
    check("filesystem_primitives", os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
          "Control-plane confinement requires POSIX descriptor operations; Windows is not verified.")
    check("workspace_ledger", (root / "portfolio/project-ledger.json").is_file(),
          "Installed commands require SUITES_ROOT pointing to the owning source workspace.")
    check("workspace_owner", hasattr(os, "getuid") and root.stat().st_uid == os.getuid(),
          "Current user must own the workspace; no ownership changes are attempted.")
    check("ledger_directory_writable", os.access(root / "portfolio", os.W_OK | os.X_OK),
          "Permission inspection only; no file is created and durable writes are not proved.")
    for asset in PACKAGE_ASSETS:
        check(asset, (package / asset).is_file(), "Required packaged asset.")
    for command in ("git", "node"):
        check(command, shutil.which(command) is not None,
              "Executable found on PATH; version and donor behavior are not verified.", required=command == "git")
    for distribution in ("pip", "setuptools", "wheel"):
        try:
            version = importlib.metadata.version(distribution)
            present = distribution != "setuptools" or int(version.split(".")[0]) >= 68
        except (importlib.metadata.PackageNotFoundError, ValueError):
            present = False
        check("build_" + distribution, present,
              "Offline build prerequisite (setuptools >=68); never installed by diagnostics.", required=False)
    return {
        "schema_version": "portfolio-diagnostics-v1",
        "ok": not any(c["status"] == "blocked" for c in checks),
        "checks": checks,
        "configuration": {
            "workspace_override_present": bool(os.environ.get("SUITES_ROOT")),
            "approval_store_configured": bool(os.environ.get("PORTFOLIO_OPERATOR_APPROVAL_STORE")),
        },
        "not_probed": ["donor dependencies and runtime", "provider credentials or network",
                       "browser and assistive technology", "transaction recovery and durable writes"],
    }
