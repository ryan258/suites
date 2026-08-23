"""Canonical checkout paths and durable writes shared across the local control plane."""

from __future__ import annotations

import os
import stat
import tempfile
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


def durable_write_text(path: Path, text: str) -> None:
    """Replace ``path`` atomically, persisting both its contents and its directory entry.

    A truncate-and-write leaves a window where the file on disk is neither the old content
    nor the new one, and the files this control plane rewrites -- the project ledger, the
    approval store -- are exactly the ones that cannot be reconstructed from anything else.
    So the bytes land in a same-directory temporary file, get fsynced, and only then take
    the target's name; the directory fsync is what makes that rename survive a power loss
    rather than merely a crash.

    The replacement inherits the target's permissions. `mkstemp` creates its file 0600, and
    replacing a 0644 file with it would quietly strip group and other read access from the
    ledger -- a change Git cannot report, because it tracks only the executable bit. A file
    that does not exist yet keeps the private 0600 default rather than inventing one.

    Raises OSError on any failure, with the temporary file cleaned up. Callers that need a
    domain-specific failure wrap it.
    """
    try:
        existing_mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        existing_mode = None

    temporary: str | None = None
    try:
        handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            if existing_mode is not None:
                os.fchmod(stream.fileno(), existing_mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None

        directory_handle = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_handle)
        finally:
            os.close(directory_handle)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                # The write has already failed. Cleanup failure must not replace the
                # original error or imply the replacement succeeded.
                pass
