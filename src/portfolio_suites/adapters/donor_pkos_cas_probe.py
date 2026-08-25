"""Exercise PKos content-addressed storage acquisition and normalization in an isolated process.

This probe is invoked as a standalone subprocess by OperatorOSSourceAdapter to prove real PKos CAS
acquisition and SQLite normalization against dotfiles/AGENTS.md without polluting the control plane's
host Python process.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Read by the calling adapter to classify the failure; keep in sync with operator_os.py.
EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: donor_pkos_cas_probe.py <source-file-path>", file=sys.stderr)
        return EXIT_USAGE

    source_path = Path(sys.argv[1]).resolve()
    if not source_path.is_file():
        print(f"source file not found: {source_path}", file=sys.stderr)
        return EXIT_USAGE

    try:
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
            label="dotfiles/AGENTS.md",
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
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
