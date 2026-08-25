"""Compare-and-swap file commits bound to an open descriptor.

:class:`TempPayload` pins a candidate inode. :func:`commit_replacement` installs it only
over the occupant the caller observed (identity, digest, or verified absence). Exchange is
preferred so the target is never vacant; filesystems without it fall back to no-replace
quarantine. :class:`OccupantConflict` means nothing was replaced. :class:`CommitUncertain`
means the target name holds the replacement but durability or cleanup could not be verified.
"""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass

from .paths import rename_exchange, rename_no_replace

# Guard against being tricked into slurping something enormous during verification.
_MAX_VERIFY_BYTES = 256 * 1024 * 1024

_EXCHANGE_UNSUPPORTED_ERRNOS = {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP}


class OccupantConflict(OSError):
    """The target name is held by an object this transaction did not read.

    Nothing was replaced and nothing was destroyed: the concurrent occupant survives under
    the target name, and any object this transaction displaced while verifying is named in
    ``recovery_paths`` for operator reconciliation. This is the "someone edited it while
    you were working" answer. A retry that does not reload first would lose their work
    again, which is precisely the behavior this layer exists to make impossible.
    """

    def __init__(self, message: str, recovery_paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.recovery_paths = recovery_paths


class CommitUncertain(OSError):
    """The replacement became observable under the target name; its outcome could not be verified.

    Distinct from :class:`OccupantConflict` on purpose: "nothing happened" and "something
    happened but I cannot prove what" demand opposite operator responses, so they must not
    share an exception. A failure after the atomic swap -- typically the directory fsync
    that makes the new name survive power loss, or an inability to unlink superseded bytes
    -- lands here even though the swap itself succeeded.
    """

    def __init__(self, message: str, recovery_paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.recovery_paths = recovery_paths


@dataclass
class TempPayload:
    """A fsynced candidate bound to an open descriptor on its own inode.

    ``fd`` stays open until the transaction ends: :func:`write_temp_payload` writes through
    it without closing it, every later question -- has this name been exchanged for another
    object? is the object still mine? -- is answered against the identity pinned at creation,
    and exactly one ``close()`` releases the descriptor. ``close()`` is idempotent on purpose:
    commit, discard, and caller cleanup can each run without coordinating, and a second call
    must never touch the *number* again -- in a multithreaded process a stale descriptor
    number may already name some other thread's object, and closing that is far worse than a
    leaked scratch fd.
    """

    name: str
    fd: int
    identity: tuple[int, int]
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.fd)


@dataclass(frozen=True)
class ReplacementResult:
    """Outcome of :func:`commit_replacement`.

    ``displaced`` names what the commit removed from the target: ``None`` when the name was
    vacant, otherwise the identity of the verified occupant whose bytes were superseded.
    """

    displaced: tuple[int, int] | None


def write_temp_payload(
    directory_fd: int,
    stem: str,
    payload: bytes,
    *,
    mode: int = 0o600,
    suffix: str = ".tmp",
) -> TempPayload:
    """Write ``payload`` once to an exclusive temporary sibling and pin its descriptor.

    The name is random per process, created O_EXCL|O_NOFOLLOW, so no other writer can
    pre-create or follow it. ``suffix`` exists because validators dispatch on file
    extension -- an evidence receipt must be validated under its real ``.json`` name shape,
    not a scratch one. The bytes are fsynced before this returns, which is what lets the
    commit step treat "the swap succeeded" as "the content is durable" once the directory
    entry is fsynced too. Callers close the returned descriptor (or pass it to
    :func:`commit_replacement`, which owns it from there).
    """
    name = f".{stem}.{os.getpid()}-{secrets.token_hex(8)}{suffix}"
    handle = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        stat.S_IMODE(mode),
        dir_fd=directory_fd,
    )
    try:
        info = os.fstat(handle)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            written += os.write(handle, view[written:])
        os.fsync(handle)
        return TempPayload(name=name, fd=handle, identity=(info.st_dev, info.st_ino))
    except BaseException:
        try:
            os.close(handle)
        except OSError:
            pass
        try:
            os.unlink(name, dir_fd=directory_fd)
        except OSError:
            pass
        raise


def _read_via_descriptor(directory_fd: int, temp: TempPayload) -> bytes:
    """Read the object the temp name currently reaches, refusing a swapped inode."""
    probe = os.open(temp.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        info = os.fstat(probe)
        if (info.st_dev, info.st_ino) != temp.identity:
            raise OccupantConflict(
                f"{temp.name}: the candidate was exchanged for a different object before commit"
            )
        if info.st_size > _MAX_VERIFY_BYTES:
            raise OSError(f"{temp.name}: candidate exceeds the verification size budget")
        chunks = []
        total_read = 0
        while True:
            chunk = os.read(probe, 1024 * 1024)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > _MAX_VERIFY_BYTES:
                raise OSError(f"{temp.name}: candidate exceeds the verification size budget")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(probe)


def verify_payload(directory_fd: int, temp: TempPayload, expected_digest: str) -> None:
    """Prove the candidate is still byte-for-byte ``expected_digest`` at commit time.

    This is the seam between "bytes that were validated" and "bytes that will be moved":
    validation necessarily ran against a pathname some other process can rewrite, so the
    recorder retains the digest of the buffer it validated and re-derives it from the object
    the name reaches immediately before installing it. A mismatch refuses the commit; the
    retained receipt is untouched.
    """
    actual = hashlib.sha256(_read_via_descriptor(directory_fd, temp)).hexdigest()
    if actual != expected_digest:
        raise OccupantConflict(
            f"{temp.name}: the candidate no longer holds the validated bytes "
            "(content changed after validation); commit refused"
        )


def _matches_expectation(
    dir_fd: int,
    name: str,
    expected_identity: tuple[int, int] | None,
    expected_digest: str | None,
) -> bool:
    """Check a displaced occupant against what the caller actually read."""
    if expected_identity is not None:
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            return False
        return (info.st_dev, info.st_ino) == expected_identity
    if expected_digest is not None:
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError:
            return False
        try:
            info = os.fstat(handle)
            if info.st_size > _MAX_VERIFY_BYTES:
                return False
            hasher = hashlib.sha256()
            total_read = 0
            while True:
                chunk = os.read(handle, 1024 * 1024)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > _MAX_VERIFY_BYTES:
                    return False
                hasher.update(chunk)
            return hasher.hexdigest() == expected_digest
        except OSError:
            return False
        finally:
            os.close(handle)
    raise ValueError("commit_replacement requires an expectation about the current occupant")


def _quarantine_name() -> str:
    return f".txn-quarantine.{os.getpid()}.{secrets.token_hex(12)}"


def _candidate_is_ours(directory_fd: int, temp: TempPayload) -> bool:
    """True only if ``temp.name`` still names the inode pinned at creation."""
    try:
        probe = os.open(temp.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError:
        return False
    try:
        info = os.fstat(probe)
    finally:
        os.close(probe)
    return (info.st_dev, info.st_ino) == temp.identity


def commit_replacement(
    directory_fd: int,
    target_name: str,
    temp: TempPayload,
    *,
    expected_identity: tuple[int, int] | None = None,
    expected_digest: str | None = None,
    expected_absent: bool = False,
) -> ReplacementResult:
    """Install ``temp``'s inode at ``target_name`` only over the object the caller read.

    The compare-and-swap contract: the replacement happens if and only if the current
    occupant matches ``expected_identity`` or ``expected_digest`` (exactly one of which the
    caller supplies), or is confirmed absent via ``expected_absent``. An occupant that does
    not match is never destroyed. On success the superseded bytes are unlinked and the
    directory entry is fsynced, so a returning call means the new document is durable.
    """
    expectations = [
        value is not None
        for value in (expected_identity, expected_digest)
    ] + [expected_absent]
    if sum(bool(flag) for flag in expectations) != 1:
        raise ValueError(
            "commit_replacement takes exactly one of expected_identity, "
            "expected_digest, or expected_absent"
        )

    def conflict(message: str, recovery: tuple[str, ...] = ()) -> OccupantConflict:
        return OccupantConflict(f"{target_name}: {message}", recovery_paths=recovery)

    def refuse_stolen_candidate() -> None:
        _discard_temp(directory_fd, temp)
        raise conflict("the candidate was exchanged for a different object before commit")

    if expected_absent:
        if not _candidate_is_ours(directory_fd, temp):
            refuse_stolen_candidate()
        try:
            rename_no_replace(temp.name, target_name, directory_fd=directory_fd)
        except FileExistsError:
            _discard_temp(directory_fd, temp)
            raise conflict("a concurrent writer created the target during the transaction")
        except OSError as error:
            _discard_temp(directory_fd, temp)
            raise conflict(f"no-replace install failed without replacing any occupant ({error})")
        return _finish_commit(directory_fd, temp, superseded=None)

    exchange_unsupported = False
    if not _candidate_is_ours(directory_fd, temp):
        refuse_stolen_candidate()
    try:
        rename_exchange(temp.name, target_name, directory_fd=directory_fd)
    except OSError as error:
        if error.errno not in _EXCHANGE_UNSUPPORTED_ERRNOS:
            _discard_temp(directory_fd, temp)
            if isinstance(error, FileNotFoundError) or error.errno == errno.ENOENT:
                raise conflict("the target does not exist; nothing was replaced")
            raise conflict(f"atomic exchange failed ({error})")
        exchange_unsupported = True

    if not exchange_unsupported:
        displaced_identity = _identity_or_none(directory_fd, temp.name)
        if _matches_expectation(directory_fd, temp.name, expected_identity, expected_digest):
            try:
                os.unlink(temp.name, dir_fd=directory_fd)
            except OSError as error:
                raise _uncertain_after_commit(
                    directory_fd, temp,
                    f"the superseded bytes remain at {temp.name} ({error})",
                    keep=(temp.name,),
                )
            return _finish_commit(directory_fd, temp, superseded=displaced_identity)

        try:
            rename_exchange(temp.name, target_name, directory_fd=directory_fd)
        except OSError as undo_error:
            recovery: list[str] = []
            ours_aside = _quarantine_name()
            try:
                rename_no_replace(target_name, ours_aside, directory_fd=directory_fd)
                recovery.append(ours_aside)
            except OSError:
                recovery.append(str(target_name))
            try:
                rename_no_replace(temp.name, target_name, directory_fd=directory_fd)
                recovery.append(str(temp.name))
            except OSError:
                recovery.append(str(temp.name))
            temp.close()
            raise CommitUncertain(
                f"{target_name}: an unexpected occupant was displaced and the automatic "
                f"restore failed; manual inspection is required ({undo_error})",
                recovery_paths=tuple(recovery),
            )
        _discard_temp(directory_fd, temp)
        raise conflict(
            "the occupant changed after it was read; nothing was replaced and the "
            "current occupant is preserved"
        )

    # Fallback for filesystems without exchange: no-replace quarantine.
    quarantine = _quarantine_name()
    try:
        rename_no_replace(target_name, quarantine, directory_fd=directory_fd)
    except FileExistsError:
        _discard_temp(directory_fd, temp)
        raise conflict("a quarantine-name collision blocked the transaction; retry")
    except (FileNotFoundError, OSError) as error:
        _discard_temp(directory_fd, temp)
        if isinstance(error, FileNotFoundError) or getattr(error, "errno", None) == errno.ENOENT:
            raise conflict("the target does not exist; nothing was replaced")
        raise conflict(f"occupant could not be moved aside without replacement ({error})")

    displaced_identity = _identity_or_none(directory_fd, quarantine)
    try:
        if not _matches_expectation(directory_fd, quarantine, expected_identity, expected_digest):
            try:
                rename_no_replace(quarantine, target_name, directory_fd=directory_fd)
            except FileExistsError:
                raise conflict(
                    "the occupant changed after it was read and its original could not be "
                    "restored to the contested name",
                    recovery_paths=(quarantine,),
                )
            raise conflict(
                "the occupant changed after it was read; the original is restored"
            )

        if not _candidate_is_ours(directory_fd, temp):
            try:
                rename_no_replace(quarantine, target_name, directory_fd=directory_fd)
            except FileExistsError:
                raise conflict(
                    "the candidate was exchanged for a different object before commit and "
                    "the original could not be restored to the contested name",
                    recovery_paths=(quarantine,),
                )
            refuse_stolen_candidate()

        try:
            rename_no_replace(temp.name, target_name, directory_fd=directory_fd)
        except FileExistsError:
            try:
                rename_no_replace(quarantine, target_name, directory_fd=directory_fd)
            except FileExistsError:
                raise conflict(
                    "a concurrent writer claimed the target during the transaction and the "
                    "original could not be restored to it",
                    recovery_paths=(quarantine,),
                )
            raise conflict(
                "a concurrent writer claimed the target during the transaction; "
                "the original is restored"
            )

        try:
            os.unlink(quarantine, dir_fd=directory_fd)
        except OSError as error:
            raise _uncertain_after_commit(
                directory_fd, temp,
                f"superseded bytes remain quarantined at {quarantine} ({error})",
                keep=(quarantine,),
            )
        return _finish_commit(
            directory_fd, temp, superseded=displaced_identity
        )
    except (OccupantConflict, CommitUncertain):
        _discard_temp(directory_fd, temp)
        raise


def _identity_or_none(dir_fd: int, name: str) -> tuple[int, int] | None:
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def _finish_commit(
    directory_fd: int,
    temp: TempPayload,
    *,
    superseded: tuple[int, int] | None,
) -> ReplacementResult:
    """Make the committed name durable and report what it superseded."""
    try:
        os.fsync(directory_fd)
    except OSError as error:
        raise CommitUncertain(
            f"{temp.name}: replacement committed, but directory durability could not be "
            f"confirmed ({error})"
        )
    finally:
        temp.close()
    return ReplacementResult(displaced=superseded)


def _uncertain_after_commit(
    directory_fd: int,
    temp: TempPayload,
    reason: str,
    *,
    keep: tuple[str, ...] = (),
) -> CommitUncertain:
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    temp.close()
    return CommitUncertain(
        f"{temp.name}: replacement committed, but durability/cleanup is incomplete -- {reason}",
        recovery_paths=keep,
    )


def discard_temp(directory_fd: int, temp: TempPayload) -> None:
    """Remove and close an uncommitted candidate; failures never mask the caller's error.

    Unlink only if the name still reaches this transaction's inode. A name-only unlink
    would destroy a concurrent writer's replacement of the same path.
    """
    if _candidate_is_ours(directory_fd, temp):
        try:
            os.unlink(temp.name, dir_fd=directory_fd)
        except OSError:
            pass
    temp.close()


# Internal call sites use the same primitive so there is exactly one cleanup behavior.
_discard_temp = discard_temp


__all__ = [
    "CommitUncertain",
    "OccupantConflict",
    "ReplacementResult",
    "TempPayload",
    "commit_replacement",
    "discard_temp",
    "verify_payload",
    "write_temp_payload",
]
