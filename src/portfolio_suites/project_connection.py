"""Read-only parser for a project's optional ``.suites`` connection descriptor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from .paths import open_confined_directory

CONNECTION_FILENAME = ".suites"
SCHEMA_VERSION = "1.0.0"
MAX_CONNECTION_BYTES = 64_000
MAX_CAPABILITIES = 32
PROJECT_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._:/-]{0,127}$")
CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class ProjectConnectionError(ValueError):
    """A project connection descriptor does not match the supported format."""


def _object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectConnectionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ProjectConnectionError(f"invalid JSON constant: {value}")


def validate_project_connection(payload: object) -> dict:
    """Validate and return the supported fields, ignoring future additive fields."""
    if not isinstance(payload, dict):
        raise ProjectConnectionError("top-level value must be an object")

    errors = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
        errors.append("project_id must be a stable identifier of 1–128 letters, digits, or . _ : / - characters")

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or len(capabilities) > MAX_CAPABILITIES:
        errors.append(f"capabilities must be an array of at most {MAX_CAPABILITIES} identifiers")
    elif any(
        not isinstance(value, str)
        or len(value) > 96
        or not CAPABILITY_ID.fullmatch(value)
        for value in capabilities
    ):
        errors.append("each capability must be a lowercase identifier of at most 96 characters")
    elif len(set(capabilities)) != len(capabilities):
        errors.append("capabilities must be distinct")

    if errors:
        raise ProjectConnectionError("; ".join(errors))
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "capabilities": list(capabilities),
    }


def _result(state: str, *, project_id=None, capabilities=None, schema_version=None, errors=None) -> dict:
    return {
        "state": state,
        "manifest": CONNECTION_FILENAME,
        "schema_version": schema_version,
        "project_id": project_id,
        "declared_capabilities": list(capabilities or []),
        "runtime_verified": False,
        "errors": list(errors or []),
    }


def read_project_connection(location: str | Path) -> dict:
    """Read a project's descriptor without following links or running project code.

    ``connected`` means only that the local descriptor is valid. Capability behavior is
    not invoked or independently verified here.
    """
    root = Path(location)
    if not root.is_absolute():
        return _result("unavailable", errors=["project location is not absolute"])

    try:
        directory_fd = open_confined_directory(root, ".")
    except OSError:
        return _result("unavailable", errors=["project directory cannot be opened safely"])

    file_fd = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        try:
            file_fd = os.open(CONNECTION_FILENAME, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return _result("not_connected")
        except OSError:
            return _result("invalid", errors=[".suites cannot be opened as a regular file"])

        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            return _result("invalid", errors=[".suites must be a regular file"])
        if info.st_size > MAX_CONNECTION_BYTES:
            return _result("invalid", errors=[f".suites exceeds {MAX_CONNECTION_BYTES} bytes"])

        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None  # fdopen owns the descriptor from here.
            raw = stream.read(MAX_CONNECTION_BYTES + 1)
        if len(raw) > MAX_CONNECTION_BYTES:
            return _result("invalid", errors=[f".suites exceeds {MAX_CONNECTION_BYTES} bytes"])
        try:
            text = raw.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ProjectConnectionError, RecursionError):
            return _result("invalid", errors=[".suites must contain one UTF-8 JSON object with unique keys"])

        try:
            descriptor = validate_project_connection(payload)
        except ProjectConnectionError as error:
            return _result("invalid", errors=[str(error)])
        return _result(
            "declared",
            schema_version=descriptor["schema_version"],
            project_id=descriptor["project_id"],
            capabilities=descriptor["capabilities"],
        )
    except OSError:
        return _result("unavailable", errors=[".suites could not be read safely"])
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
