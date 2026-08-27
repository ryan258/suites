"""Exercise PKos content-addressed storage acquisition and normalization in an isolated process.

This probe is invoked as a standalone subprocess by OperatorOSSourceAdapter to prove real PKos CAS
acquisition and SQLite normalization against dotfiles/AGENTS.md without polluting the control plane's
host Python process.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

# Read by the calling adapter to classify the failure; keep in sync with operator_os.py.
EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3


def _module_records(modules: dict[str, object]) -> dict[str, dict[str, str]]:
    """Path and digest of each imported donor module, skipping any without a real file."""
    records: dict[str, dict[str, str]] = {}
    for name, module in modules.items():
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        path = Path(origin).resolve()
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        records[name] = {"path": str(path), "sha256": digest}
    return records


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("usage: donor_pkos_cas_probe.py <source-file-path> [<label>]", file=sys.stderr)
        return EXIT_USAGE

    source_path = Path(sys.argv[1]).resolve()
    if not source_path.is_file():
        print(f"source file not found: {source_path}", file=sys.stderr)
        return EXIT_USAGE
    # Optional donor-side label for the acquired record. O1 keeps the historical default;
    # a later wave can acquire a different donor file without mislabeling it as dotfiles.
    label = sys.argv[2] if len(sys.argv) == 3 else "dotfiles/AGENTS.md"

    try:
        from pkos import normalize as normalize_module
        from pkos import storage as storage_module
        from pkos.storage import Workspace, checksum_file
        from pkos.normalize import normalize
    except Exception as exc:
        # Exit 3, not 2: the caller records `environment_blocked` from this code alone, and
        # "PKos is on disk but its own dependencies are not importable here" is a different
        # claim from "the PKos API changed". Sharing an exit code collapses the two.
        print(f"failed to import pkos modules: {exc}", file=sys.stderr)
        return EXIT_IMPORT_FAILED

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(Path(tmpdir))
        acquired_record = ws.acquire_file(
            source_path,
            kind="operator_policy",
            label=label,
        )
        cas_object_path = ws.root / acquired_record["raw_object"]
        raw_bytes_match = (
            cas_object_path.is_file()
            and checksum_file(cas_object_path) == acquired_record["sha256"]
            and checksum_file(source_path) == acquired_record["sha256"]
        )
        counts = normalize(ws)
        print(
            json.dumps(
                {
                    "acquired_record": acquired_record,
                    "raw_bytes_match": raw_bytes_match,
                    "counts": counts,
                    # What this process actually imported, so the caller can recompute the
                    # digests itself. These are the donor's own claims about the donor --
                    # the adapter re-hashes the same paths host-side and requires agreement.
                    "modules": _module_records(
                        {"pkos.storage": storage_module, "pkos.normalize": normalize_module}
                    ),
                    "interpreter": {
                        "python": platform.python_version(),
                        "implementation": platform.python_implementation(),
                    },
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
