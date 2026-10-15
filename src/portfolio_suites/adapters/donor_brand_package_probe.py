"""Read one real Brand Maker publication and run its developer exporter in isolation.

The probe never initializes or writes the donor database. With no published version it
returns that fact before importing Brand Maker. When a publication exists, its validated
immutable snapshot is passed to Brand Maker's own ``export_developer_package`` function.
Only JSON is written to stdout; import failures have a dedicated exit code.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import sys
from pathlib import Path

EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3  # Brand Maker or its dependencies could not be imported.
EXIT_PROBE_FAILED = 4


def _emit(status: str, **fields: object) -> None:
    print(json.dumps({"status": status, **fields}, sort_keys=True, separators=(",", ":")))


def _published_rows(database: Path) -> list[tuple[object, ...]]:
    uri = database.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "published_brand_versions" not in tables:
            raise LookupError("published_brand_versions table is unavailable")
        return connection.execute(
            """SELECT brand_id, version, published_at, publisher_id, draft_revision,
                      change_summary, content_hash, manifest_json, approvals_json, snapshot_json
               FROM published_brand_versions"""
        ).fetchall()
    finally:
        connection.close()


def main() -> int:
    if len(sys.argv) not in {3, 4}:
        print(
            "usage: donor_brand_package_probe.py <brand-maker-root> <database> [brand-id]",
            file=sys.stderr,
        )
        return EXIT_USAGE

    root = Path(sys.argv[1]).resolve()
    database = Path(sys.argv[2]).resolve()
    selected_brand_id = sys.argv[3] if len(sys.argv) == 4 and sys.argv[3] else None
    sys.dont_write_bytecode = True

    if not database.is_file():
        _emit("database_missing")
        return 0

    try:
        rows = _published_rows(database)
    except LookupError:
        _emit("publication_schema_unavailable")
        return 0
    except (OSError, sqlite3.Error) as error:
        _emit("database_unavailable", error_kind=type(error).__name__)
        return 0

    if not rows:
        _emit("no_published_version", published_version_count=0)
        return 0

    if selected_brand_id is not None:
        rows = [row for row in rows if str(row[0]) == selected_brand_id]
        if not rows:
            _emit("selected_brand_not_published", selected_brand_id=selected_brand_id)
            return 0
    else:
        brand_ids = sorted({str(row[0]) for row in rows})
        if len(brand_ids) != 1:
            _emit(
                "brand_selection_required",
                published_brand_ids=brand_ids,
                published_version_count=len(rows),
            )
            return 0

    # Brand Maker versions are immutable. Select the most recently published version for
    # the explicitly selected (or sole) brand; never choose between different brands.
    try:
        rows.sort(key=lambda row: str(row[2]))
        row = rows[-1]
    except (IndexError, TypeError):
        _emit("published_version_invalid")
        return 0

    sys.path.insert(0, str(root / "src"))
    try:
        from brand_maker.brand_system.models import PublishedVersion
        from brand_maker.publishing.developer_exports import export_developer_package
    except Exception as error:
        print(f"failed to import Brand Maker exporter: {type(error).__name__}", file=sys.stderr)
        return EXIT_IMPORT_FAILED

    try:
        published = PublishedVersion.model_validate(
            {
                "brand_id": row[0],
                "version": row[1],
                "published_at": row[2],
                "publisher_id": row[3],
                "draft_revision": row[4],
                "change_summary": row[5],
                "content_hash": row[6],
                "manifest": json.loads(str(row[7])),
                "approvals": json.loads(str(row[8])),
                "snapshot": json.loads(str(row[9])),
            }
        )
        exports = export_developer_package(published)
        module_paths = {
            "brand_maker.publishing.developer_exports": root
            / "src/brand_maker/publishing/developer_exports.py",
            "brand_maker.brand_system.models": root
            / "src/brand_maker/brand_system/models.py",
        }
        module_fingerprints = {
            name: {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, path in module_paths.items()
        }
        version_data = published.model_dump(mode="json")
        version_data["approvals"] = [
            {
                "id": str(item.id),
                "brand_id": str(item.brand_id),
                "draft_revision": item.draft_revision,
                "owner_id": item.owner_id,
                "approved_at": item.approved_at.isoformat(),
                "outcome": item.outcome,
            }
            for item in published.approvals
        ]
        _emit(
            "exported",
            published_version=version_data,
            developer_export=exports,
            module_fingerprints=module_fingerprints,
        )
        return 0
    except Exception as error:
        print(f"Brand Maker publication export failed: {type(error).__name__}", file=sys.stderr)
        return EXIT_PROBE_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
