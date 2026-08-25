"""Canonical checkout paths and durable writes shared across the local control plane."""

from __future__ import annotations

import ctypes
import errno
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

# Root is this checkout, not site-packages. Set SUITES_ROOT if the derived path has no ledger.
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


class CommitUnverified(OSError):
    """The replacement committed; the durability check after it did not.

    The swap is the commit point: the new document is already reachable under the target
    name. A failure after it -- the directory fsync -- means the change may not survive a
    power loss, which is a different fact from "nothing was written", and a caller told
    only "OSError" reports the second when the first is true.

    Raised by :func:`portfolio_suites.registry.fingerprint_baselines` when the ledger
    commit lands but its durability cannot be confirmed; ``suites baseline`` catches it.
    """


class ConfinementError(OSError):
    """Raised when a path component is not a real directory inside the anchored root."""


def _relative_components(relative: str | Path) -> tuple[str, ...]:
    """Split a relative path into components, refusing anything that could leave the root."""
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ConfinementError(f"{relative!r} must be relative to its anchored root")
    parts = candidate.parts
    if not parts or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
        raise ConfinementError(f"{relative!r} contains a path component that is not a plain name")
    return parts


def open_confined_directory(anchor: Path, relative: str | Path, *, create: bool = False) -> int:
    """Return a descriptor for ``anchor/relative``, refusing a symlink at any component.

    Resolving a path and then opening it are two lookups over a tree another process can
    edit in between, so a check on the resolved string proves nothing about what the open
    will actually reach: an already-checked directory can be exchanged for a symlink while
    the caller is still verifying an approval. Walking component by component under
    O_NOFOLLOW moves the refusal inside each lookup, and every subsequent lookup is made
    relative to a descriptor that is already pinned to a specific inode. The anchor itself
    is a trusted constant (:data:`SUITES_ROOT` or :data:`PROJECTS_ROOT`), never caller input.

    ``create`` makes each missing component as the walk reaches it, still reopening it under
    O_NOFOLLOW, so a component another process wins the race to create as a symlink is
    refused rather than followed.

    The caller owns the returned descriptor and must close it.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    components = () if str(relative) in {"", "."} else _relative_components(relative)
    current = os.open(anchor, flags)
    try:
        for part in components:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
            nested = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = nested
    except OSError:
        os.close(current)
        raise
    return current


def _identity(fd: int) -> tuple[int, int]:
    """The (device, inode) pair naming the object ``fd`` is open on."""
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino)


class InstalledFile(NamedTuple):
    """What :func:`install_new_file` created, with the identities needed to undo it.

    A rollback that remembers only *names* can delete a bystander: between the failed batch
    and the undo, another writer can replace an installed name with its own file, and an
    unlink by name removes theirs. Carrying the (device, inode) each object had when this
    call created it makes the undo verify it is removing its own work.
    """

    directories: list[tuple[str, tuple[int, int]]]
    identity: tuple[int, int]


@dataclass(frozen=True)
class RollbackRemoval:
    """Result of a rollback removal, including any object left for manual recovery.

    ``bool(result)`` preserves the old caller contract: it is true only when the object
    installed by this run was removed. A false result may additionally name a quarantine
    object that could not be restored without replacing a newer writer's occupant.
    """

    removed: bool
    recovery_path: str | None = None
    conflict: str | None = None

    def __bool__(self) -> bool:
        return self.removed


def install_new_file(directory_fd: int, relative: str | Path, text: str) -> InstalledFile:
    """Create ``relative`` under ``directory_fd``, never following or replacing anything.

    O_CREAT|O_EXCL is what makes this safe rather than a check followed by a write: the
    kernel decides existence and creation in the same operation, so a file that appears
    between a caller's conflict check and this call is a refusal (FileExistsError), not a
    silent overwrite. Intermediate directories are created and reopened under the same
    O_NOFOLLOW discipline as :func:`open_confined_directory`.

    A failure after the name exists is this call's garbage, not the caller's: it raises
    without ever returning a directory list, so a caller unwinding a partial batch has no
    record of the file or directories to remove. So everything this call created is removed
    here, through the same descriptors it created them under, before the error propagates.
    A successful return means the file is durable.

    Returns the intermediate directories this call created, outermost first, each paired
    with the identity it had at creation, plus the identity of the file itself -- so a
    caller rolling back a partial batch knows which objects are its own to remove.
    """
    *directories, name = _relative_components(relative)
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    created: list[tuple[str, tuple[int, int]]] = []
    # Each walked descriptor stays open until the operation is durable, so the undo below
    # unlinks through inodes this call pinned rather than re-resolving a name.
    walked_fds = [os.dup(directory_fd)]
    made: list[tuple[int, str, tuple[int, int]]] = []
    try:
        walked: list[str] = []
        for part in directories:
            mine = False
            try:
                os.mkdir(part, 0o700, dir_fd=walked_fds[-1])
            except FileExistsError:
                pass
            else:
                mine = True
            relative_name = os.path.join(*walked, part) if walked else part
            parent_of_part = walked_fds[-1]
            walked.append(part)
            nested = os.open(part, flags, dir_fd=parent_of_part)
            walked_fds.append(nested)
            if mine:
                # Identity is taken from the descriptor the walk continues through, so the
                # rollback record names the directory this call actually descended into --
                # and so the undo below can refuse to remove someone else's replacement.
                directory_identity = _identity(nested)
                created.append((relative_name, directory_identity))
                made.append((parent_of_part, part, directory_identity))
        parent = walked_fds[-1]
        handle = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        file_identity = _identity(handle)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent)
        except BaseException:
            # Between the write and here the name may already belong to another writer --
            # the directory fsync that failed is exactly the window for it. Remove the
            # inode this call created, never whatever currently answers to the name.
            remove_fd_if_same(parent, name, file_identity, directory=False)
            raise
    except BaseException:
        for parent_fd, part, part_identity in reversed(made):
            remove_fd_if_same(parent_fd, part, part_identity, directory=True)
        raise
    finally:
        for fd in walked_fds:
            os.close(fd)
    return InstalledFile(created, file_identity)


def rename_no_replace(source: str, destination: str, *, directory_fd: int) -> None:
    """Atomically rename one name to another only when the destination is absent.

    Python's :func:`os.rename` has replacement semantics on POSIX, which is exactly the
    wrong primitive for rollback: both the quarantine slot and the original name may have
    been claimed by another writer. macOS and Linux expose collision-refusing rename
    operations through ``renameatx_np(RENAME_EXCL)`` and ``renameat2(RENAME_NOREPLACE)``.
    Unsupported platforms fail closed instead of falling back to a check-then-rename race.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)

    if sys.platform == "darwin":
        operation = getattr(libc, "renameatx_np", None)
        flags = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        operation = getattr(libc, "renameat2", None)
        flags = 0x00000001  # RENAME_NOREPLACE
    else:
        operation = None
        flags = 0

    if operation is None:
        raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")

    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = operation(
        directory_fd,
        source_bytes,
        directory_fd,
        destination_bytes,
        flags,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{source} -> {destination}",
        )


def rename_exchange(source: str, destination: str, *, directory_fd: int) -> None:
    """Atomically swap two existing names in one directory.

    An exchange is the closest thing POSIX offers to a compare-and-swap on a name: after it
    returns, ``source`` holds what ``destination`` held and vice versa, with no instant at
    which either name is vacant and no window in which another writer's object can be
    destroyed. It is what lets :mod:`portfolio_suites.txn` verify the occupant it displaced
    *after* the swap and put it back if the verification fails, instead of trusting a stat
    taken before an ordinary replacing rename.

    macOS and Linux expose the operation through ``renameatx_np(RENAME_SWAP)`` and
    ``renameat2(RENAME_EXCHANGE)``. Filesystems that do not implement it fail with ENOSYS
    or EINVAL rather than degrading to something lossy; callers fall back to the no-replace
    quarantine protocol, which preserves every object but briefly vacates the target name.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)

    if sys.platform == "darwin":
        operation = getattr(libc, "renameatx_np", None)
        flags = 0x00000002  # RENAME_SWAP
    elif sys.platform.startswith("linux"):
        operation = getattr(libc, "renameat2", None)
        flags = 0x00000002  # RENAME_EXCHANGE
    else:
        operation = None
        flags = 0

    if operation is None:
        raise OSError(errno.ENOTSUP, "atomic rename exchange is unavailable")

    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = operation(
        directory_fd,
        source_bytes,
        directory_fd,
        destination_bytes,
        flags,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{source} <-> {destination}",
        )


def _remove_if_same(
    anchor: Path,
    relative: str | Path,
    identity: tuple[int, int],
    *,
    directory: bool,
) -> RollbackRemoval:
    """Remove ``relative`` only if it is still the object ``identity`` names.

    Rollback runs after a failure, which means it runs after an arbitrary delay, and the
    names it is unwinding are ordinary names another writer may have claimed in between.
    To prevent deleting a bystander's replacement, the object is atomically moved to a
    random quarantine name first, inspected, and only deleted if its identity matches.
    Both moves refuse replacement atomically. If the original name is reclaimed before a
    mismatched object can be restored, both occupants survive and the quarantine path is
    returned for operator recovery.
    """
    *directories, name = _relative_components(relative)
    directory_fd = open_confined_directory(anchor, Path(*directories) if directories else ".")
    try:
        return remove_fd_if_same(
            directory_fd,
            name,
            identity,
            directory=directory,
            recovery_prefix=anchor / Path(*directories) if directories else anchor,
        )
    finally:
        os.close(directory_fd)


def remove_fd_if_same(
    directory_fd: int,
    name: str,
    identity: tuple[int, int],
    *,
    directory: bool,
    recovery_prefix: Path | None = None,
) -> RollbackRemoval:
    """Identity-checked removal of ``name`` under an already-pinned directory descriptor.

    This is the whole of the rollback rule, usable by callers that still hold the
    descriptor they created the object under. Removing by name alone deletes whatever
    currently answers to that name, which after a failure may be another writer's file.
    """
    quarantine_name = f".rollback-quarantine.{secrets.token_hex(16)}"
    try:
        rename_no_replace(name, quarantine_name, directory_fd=directory_fd)
    except FileExistsError:
        return RollbackRemoval(
            False,
            conflict="rollback quarantine name was already occupied; original name was left untouched",
        )
    except OSError as error:
        return RollbackRemoval(
            False,
            conflict=f"rollback quarantine move failed without replacing any occupant ({error})",
        )

    recovery_path = (
        str(recovery_prefix / quarantine_name) if recovery_prefix is not None else quarantine_name
    )

    def restore_or_preserve(reason: str) -> RollbackRemoval:
        try:
            rename_no_replace(quarantine_name, name, directory_fd=directory_fd)
        except OSError as error:
            return RollbackRemoval(
                False,
                recovery_path=recovery_path,
                conflict=(
                    f"{reason}; restoration refused or failed without replacing the current "
                    f"occupant ({error})"
                ),
            )
        return RollbackRemoval(False)

    try:
        current = os.stat(quarantine_name, dir_fd=directory_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != identity:
            return restore_or_preserve("quarantined object did not match the installed identity")

        if directory:
            os.rmdir(quarantine_name, dir_fd=directory_fd)
        else:
            os.unlink(quarantine_name, dir_fd=directory_fd)
        return RollbackRemoval(True)
    except OSError as error:
        return restore_or_preserve(f"quarantine inspection or removal failed ({error})")


def remove_installed_file(
    anchor: Path,
    relative: str | Path,
    identity: tuple[int, int],
) -> RollbackRemoval:
    """Remove a file installed by :func:`install_new_file`, anchored again, if it is still ours."""
    return _remove_if_same(anchor, relative, identity, directory=False)


def remove_installed_directory(
    anchor: Path,
    relative: str | Path,
    identity: tuple[int, int],
) -> RollbackRemoval:
    """Remove a directory created under ``anchor``, anchored again, if it is still ours.

    ``dir_fd`` anchors only the first lookup, so handing ``os.rmdir`` a slash-containing
    relative path still follows every intermediate component. Rollback re-walks from the
    trusted anchor under O_NOFOLLOW and operates on the final basename alone.
    """
    return _remove_if_same(anchor, relative, identity, directory=True)
