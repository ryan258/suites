"""Bounded, read-only source candidate identity. Never stage or refresh the index.

The scope is Git's tracked files and non-ignored untracked files. Ignored runtime
state/build products are explicitly outside this source identity. Two observations
must agree; this is a drift detector, not a filesystem snapshot or an approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from .adapters.common import run_donor_git
from .paths import SUITES_ROOT, open_confined_directory
from .provenance import is_sensitive_path

VERSION = "portfolio-source-candidate-v1"
MAX_FILES = 20000
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class CandidateError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _git(root: Path, *args: str) -> bytes:
    try:
        result = run_donor_git(root, *args, binary=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise CandidateError("git_unavailable") from error
    if result.returncode:
        raise CandidateError("git_observation_failed")
    if len(result.stdout) > 16 * 1024 * 1024:
        raise CandidateError("git_inventory_too_large")
    return result.stdout


def _metadata(root: Path) -> tuple[str, list[dict[str, str]], list[str]]:
    top = os.fsdecode(_git(root, "rev-parse", "--show-toplevel").rstrip(b"\n"))
    if Path(top).resolve() != root.resolve():
        raise CandidateError("workspace_is_not_repository_root")
    head = _git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    index = []
    for raw in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not raw:
            continue
        header, name = raw.split(b"\t", 1)
        mode, oid, stage = header.decode("ascii").split()
        if stage != "0":
            raise CandidateError("unmerged_index")
        if mode not in {"100644", "100755"}:
            raise CandidateError("unsupported_index_entry")
        index.append({"path": os.fsdecode(name), "mode": mode, "object_id": oid})
    untracked = [os.fsdecode(p) for p in _git(
        root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p]
    if len(index) + len(untracked) > MAX_FILES:
        raise CandidateError("file_limit_exceeded")
    return head, sorted(index, key=lambda r: r["path"]), sorted(untracked)


def _file(root: Path, name: str, tracked: bool) -> dict[str, Any]:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise CandidateError("unsafe_path")
    # This reviewed, tracked template contains empty credentials and is source input.
    # The exception is exact; nested/untracked templates and actual .env remain refused.
    if is_sensitive_path(path) and not (tracked and name == ".env.example"):
        # Neither the path nor file bytes escape into the report.
        raise CandidateError("sensitive_path_excluded")
    parent_fd = fd = None
    try:
        parent_fd = open_confined_directory(root, path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        except FileNotFoundError:
            if tracked:
                return {"path": name, "state": "deleted"}
            raise CandidateError("untracked_file_disappeared")
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CandidateError("unsupported_file_type_or_hardlink")
        if before.st_size > MAX_FILE_BYTES:
            raise CandidateError("file_size_limit_exceeded")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(fd, 65536):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise CandidateError("file_size_limit_exceeded")
            digest.update(chunk)
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink,
                              s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(named) or size != after.st_size:
            raise CandidateError("file_changed_during_observation")
        return {"path": name, "state": "present", "size": size,
                "mode": "100755" if after.st_mode & 0o111 else "100644", "sha256": digest.hexdigest()}
    except FileNotFoundError:
        # A removed parent is a valid tracked deletion. A linked parent is refused.
        if tracked:
            return {"path": name, "state": "deleted"}
        raise CandidateError("untracked_file_disappeared") from None
    except OSError as error:
        raise CandidateError("file_unreadable_or_unsafe") from error
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _observe(root: Path) -> dict[str, Any]:
    head, index, untracked = _metadata(root)
    _check_special_files(root)
    tracked = {r["path"] for r in index}
    files = []
    total = 0
    for name in sorted(tracked | set(untracked)):
        row = _file(root, name, name in tracked)
        total += row.get("size", 0)
        if total > MAX_TOTAL_BYTES:
            raise CandidateError("total_size_limit_exceeded")
        files.append(row)
    if (head, index, untracked) != _metadata(root):
        raise CandidateError("git_changed_during_observation")
    return {"head": head, "index": index, "untracked": untracked, "files": files}


def _check_special_files(root: Path) -> None:
    """Git omits FIFOs/devices from `ls-files --others`; inspect directory entries too.

    Skip explicitly ignored paths and Git metadata. Walk pinned directories without
    following links, applying the same inventory bound as the content scan.
    """
    ignored = {os.fsdecode(p).rstrip("/") for p in _git(
        root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"
    ).split(b"\0") if p}
    pending = [Path(".")]
    count = 0
    while pending:
        parent = pending.pop()
        fd = None
        try:
            fd = open_confined_directory(root, parent)
            with os.scandir(fd) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_FILES:
                        raise CandidateError("directory_inventory_limit_exceeded")
                    relative = parent / entry.name
                    if relative.as_posix() in ignored or relative.as_posix() == ".git":
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(relative)
                    elif not entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                        raise CandidateError("unsupported_untracked_file_type")
        except OSError as error:
            raise CandidateError("directory_unreadable_or_unsafe") from error
        finally:
            if fd is not None:
                os.close(fd)


def inspect_candidate(root: Path = SUITES_ROOT) -> dict[str, Any]:
    """Return a digest only for two complete, identical observations of the source."""
    result: dict[str, Any] = {"schema_version": VERSION, "complete": False, "sha256": None,
                             "scope": "tracked-and-nonignored-untracked", "ignored_files_included": False}
    try:
        first = _observe(root)
        if first != _observe(root):
            raise CandidateError("candidate_changed_during_observation")
        result.update(complete=True, sha256=_digest({"schema_version": VERSION, **first}),
                      head=first["head"], index_sha256=_digest(first["index"]),
                      working_tree_sha256=_digest(first["files"]),
                      tracked_files=len(first["index"]), untracked_files=len(first["untracked"]),
                      files=first["files"], errors=[])
    except (CandidateError, UnicodeError, ValueError) as error:
        result["errors"] = [str(error) if isinstance(error, CandidateError) else "invalid_git_inventory"]
    return result
