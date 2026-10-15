"""Explicitly add a self-declared ``.suites`` project to the local catalog."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat

from . import registry
from .catalog import CatalogError, catalog_rows, project_view, render_ledger, validate_catalog
from .paths import open_confined_directory
from .project_connection import CONNECTION_FILENAME, MAX_CONNECTION_BYTES, read_project_connection
from .txn import CommitUncertain, OccupantConflict, commit_replacement, write_temp_payload


class ProjectRegistrationUncertain(CatalogError):
    """The ledger swap may have landed; reload before trying the registration again."""


def _descriptor_fingerprint(location: Path) -> str:
    """Hash the declared descriptor through a pinned directory and non-following file open."""
    directory_fd = open_confined_directory(location, ".")
    file_fd = None
    try:
        file_fd = os.open(
            CONNECTION_FILENAME,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise CatalogError(".suites must be a regular file")
        if info.st_size > MAX_CONNECTION_BYTES:
            raise CatalogError(f".suites exceeds {MAX_CONNECTION_BYTES} bytes")
        chunks = []
        remaining = MAX_CONNECTION_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(remaining, 16_384))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_CONNECTION_BYTES:
            raise CatalogError(f".suites exceeds {MAX_CONNECTION_BYTES} bytes")
        return hashlib.sha256(raw).hexdigest()
    except OSError as error:
        raise CatalogError(".suites changed or became unavailable while connecting") from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def connect_project(location: str | Path) -> dict:
    """Register one valid ``.suites`` project without enrolling or editing that project.

    Registration is explicit, local, and idempotent. It appends only to the existing
    catalog-additions array, retains the descriptor's content hash as provenance, and
    leaves release-suite membership unset.
    """
    try:
        supplied = Path(location).expanduser()
        if not supplied.is_absolute():
            raise CatalogError("project location must be an absolute path")
        root = supplied.resolve(strict=True)
    except CatalogError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise CatalogError("project location cannot be resolved") from error
    if not root.is_dir():
        raise CatalogError("project location must be a directory")

    connection = read_project_connection(root)
    if connection.get("state") != "declared":
        details = "; ".join(connection.get("errors") or [])
        raise CatalogError("project does not have a valid .suites descriptor" + (f": {details}" if details else ""))
    project_id = connection["project_id"]
    descriptor_sha256 = _descriptor_fingerprint(root)
    confirmed = read_project_connection(root)
    if (
        confirmed.get("state") != "declared"
        or confirmed.get("project_id") != project_id
        or confirmed.get("declared_capabilities") != connection.get("declared_capabilities")
    ):
        raise CatalogError(".suites changed while connecting; reload it and retry")

    with registry._ledger_lock():
        directory_fd = open_confined_directory(registry.SUITES_ROOT, "portfolio")
        temp = None
        try:
            ledger_fd = os.open("project-ledger.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(ledger_fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise CatalogError("project ledger is not a regular file")
                mode = stat.S_IMODE(info.st_mode)
                before = stream.read()
            try:
                document = json.loads(before)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CatalogError("project ledger is unreadable JSON") from error
            errors = validate_catalog(document)
            if errors:
                raise CatalogError("project ledger is invalid: " + "; ".join(errors))

            rows = catalog_rows(document)
            same_id = next((row for row in rows if row.get("name") == project_id), None)
            same_location = next(
                (row for row in rows if row.get("operator", {}).get("location") == str(root)),
                None,
            )
            if same_id is not None:
                if same_id.get("operator", {}).get("location") != str(root):
                    raise CatalogError(f"project ID {project_id!r} is already connected at another location")
                if same_location is not same_id:
                    raise CatalogError("project location is already registered under a different identity")
                return project_view(same_id)
            if same_location is not None:
                raise CatalogError(
                    "project location is already registered as " + str(same_location.get("name"))
                )

            observed = dt.datetime.now().astimezone().date().isoformat()
            row = {
                "name": project_id,
                "primary_suite": None,
                "role": "catalog-only; runtime ownership retained",
                "disposition": "catalog-only",
                "migration": "not-enrolled",
                "operator": {
                    "schema_version": "1.0.0",
                    "id": project_id,
                    "location": str(root),
                    "inventory_kind": "project",
                    "parent": None,
                    "identity_status": "observed",
                    "primary_home": "independent",
                    "related_suites": [],
                    "owner": "Owner review pending; identity is self-declared in .suites",
                    "purpose": None,
                    "purpose_basis": ".suites declares project identity and capabilities only",
                    "resume": {
                        "kind": "directory",
                        "target": str(root),
                        "observed_at": observed,
                        "sha256": None,
                    },
                    "attention": None,
                    "now_order": None,
                    "next_action": None,
                    "waiting_trigger": None,
                    "done_for_now": None,
                    "restart_note": None,
                    "revision": 0,
                    "observed_at": observed,
                    "provenance": [
                        {
                            "source": f"{root}/{CONNECTION_FILENAME}",
                            "sha256": descriptor_sha256,
                            "observed_at": observed,
                            "observer": "local Suites connection command",
                        }
                    ],
                    "notes": [
                        "Connection records a self-declared identity and capabilities; it does not verify runtime behavior or enroll a suite."
                    ],
                },
            }
            document["catalog_additions"].append(row)
            errors = validate_catalog(document)
            if errors:
                raise CatalogError("project connection would invalidate the catalog: " + "; ".join(errors))

            temp = write_temp_payload(directory_fd, "project-ledger.json", render_ledger(document), mode=mode)
            try:
                commit_replacement(
                    directory_fd,
                    "project-ledger.json",
                    temp,
                    expected_digest=hashlib.sha256(before).hexdigest(),
                )
            except OccupantConflict as error:
                raise CatalogError("project ledger changed while connecting; reload and retry") from error
            except CommitUncertain as error:
                raise ProjectRegistrationUncertain(
                    "connection may have been saved; reload the project catalog before retrying"
                ) from error
        finally:
            if temp is not None:
                temp.close()
            os.close(directory_fd)

    return project_view(row)
