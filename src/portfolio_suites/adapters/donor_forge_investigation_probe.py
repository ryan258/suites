"""Load one retained Forge investigation through Forge's own persistence and domain validation.

Runs as a standalone subprocess (never imported by the control plane). Forge's store constructor
creates and migrates its file, so the probe works on a copy and leaves the donor database untouched.
It selects the first completed investigation that retained model receipts (a smoke fixture has none)
and prints one JSON line; the parent recomputes the database digest itself.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3  # Forge or its dependencies could not be imported: environment_blocked


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: donor_forge_investigation_probe.py <breaking-chains-root>", file=sys.stderr)
        return EXIT_USAGE
    repo = Path(sys.argv[1]).resolve()
    database = repo / "data" / "forge.sqlite3"
    if not database.is_file():
        print(f"forge database not found: {database}", file=sys.stderr)
        return EXIT_USAGE
    sys.dont_write_bytecode = True  # a probe must not write into the donor checkout
    sys.path.insert(0, str(repo / "src"))
    try:
        from forge.persistence.sqlite import SQLiteProjection
    except Exception as exc:
        print(f"failed to import forge: {exc}", file=sys.stderr)
        return EXIT_IMPORT_FAILED

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "forge.sqlite3"
        shutil.copyfile(database, copy)
        projection = SQLiteProjection(copy)
        with sqlite3.connect(copy) as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM investigations ORDER BY created_at")]
        for investigation_id in ids:
            record = projection.load_record(investigation_id)
            if record.workflow.stage.value == "completed" and record.model_receipts:
                payload = record.model_dump(mode="json")
                break
        else:
            print("no completed investigation with model receipts is retained", file=sys.stderr)
            return EXIT_USAGE
    print(json.dumps({"record": payload, "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
