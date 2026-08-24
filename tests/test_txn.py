"""The shared compare-and-swap transaction layer, exercised directly.

Every trust-critical commit in the control plane -- approval consumption, ledger
baselines, evidence recording -- goes through :mod:`portfolio_suites.txn`. These tests pin
its contract at the source: an occupant that does not match what the caller read is never
destroyed, a candidate that changed after validation is never committed, and every failure
path leaves the directory holding only objects someone can account for.
"""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from portfolio_suites.paths import open_confined_directory
from portfolio_suites import txn
from portfolio_suites.txn import (
    CommitUncertain,
    OccupantConflict,
    commit_replacement,
    discard_temp,
    verify_payload,
    write_temp_payload,
)


class TxnTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.dir_fd = open_confined_directory(self.root, ".")
        self.addCleanup(os.close, self.dir_fd)

    def identity(self, name):
        info = os.stat(self.root / name)
        return (info.st_dev, info.st_ino)

    def contents(self, name):
        return (self.root / name).read_bytes()

    def scratch_names(self):
        return sorted(p.name for p in self.root.iterdir() if p.name.startswith("."))

    def test_install_into_vacant_name(self):
        temp = write_temp_payload(self.dir_fd, "doc", b"v1")
        result = commit_replacement(self.dir_fd, "doc", temp, expected_absent=True)
        self.assertIsNone(result.displaced)
        self.assertEqual(self.contents("doc"), b"v1")
        self.assertEqual(self.scratch_names(), [])

    def test_cas_over_matching_identity_commits_and_reports_displacement(self):
        commit_replacement(
            self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
            expected_absent=True,
        )
        original = self.identity("doc")
        result = commit_replacement(
            self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v2"),
            expected_identity=original,
        )
        self.assertEqual(result.displaced, original)
        self.assertEqual(self.contents("doc"), b"v2")
        self.assertEqual(self.scratch_names(), [])

    def test_cas_over_stale_identity_refuses_and_preserves_occupant(self):
        commit_replacement(
            self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
            expected_absent=True,
        )
        stale = self.identity("doc")
        commit_replacement(
            self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v2"),
            expected_identity=stale,
        )
        with self.assertRaises(OccupantConflict):
            commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v3"),
                expected_identity=stale,
            )
        self.assertEqual(self.contents("doc"), b"v2", "the current occupant was harmed")
        self.assertEqual(self.scratch_names(), [], "the refused candidate was left behind")

    def test_digest_expectation_catches_an_in_place_edit(self):
        """An editor that truncates and rewrites keeps the inode; only content matches."""
        (self.root / "ledger").write_bytes(b"read-by-transaction")
        prior_digest = hashlib.sha256(b"read-by-transaction").hexdigest()

        # The concurrent edit lands after the transaction's read.
        (self.root / "ledger").write_bytes(b"concurrent-edit")

        with self.assertRaises(OccupantConflict):
            commit_replacement(
                self.dir_fd, "ledger",
                write_temp_payload(self.dir_fd, "ledger", b"stale-baseline"),
                expected_digest=prior_digest,
            )
        self.assertEqual(self.contents("ledger"), b"concurrent-edit")

    def test_matching_digest_commits_over_superseded_bytes(self):
        (self.root / "doc").write_bytes(b"observed")
        commit_replacement(
            self.dir_fd, "doc",
            write_temp_payload(self.dir_fd, "doc", b"next"),
            expected_digest=hashlib.sha256(b"observed").hexdigest(),
        )
        self.assertEqual(self.contents("doc"), b"next")

    def test_expected_absent_refuses_an_occupant(self):
        (self.root / "occupied").write_bytes(b"someone got here first")
        with self.assertRaises(OccupantConflict):
            commit_replacement(
                self.dir_fd, "occupied",
                write_temp_payload(self.dir_fd, "occupied", b"mine"),
                expected_absent=True,
            )
        self.assertEqual(self.contents("occupied"), b"someone got here first")

    def test_verify_payload_refuses_candidate_bytes_substituted_after_validation(self):
        temp = write_temp_payload(self.dir_fd, "receipt.json", b"honest", suffix=".json")
        verify_payload(self.dir_fd, temp, hashlib.sha256(b"honest").hexdigest())
        # Same inode, different bytes: exactly what a same-user tamper looks like.
        handle = os.open(temp.name, os.O_WRONLY, dir_fd=self.dir_fd)
        try:
            os.ftruncate(handle, 0)
            os.write(handle, b'tampered')
            os.fsync(handle)
        finally:
            os.close(handle)
        with self.assertRaises(OccupantConflict):
            verify_payload(self.dir_fd, temp, hashlib.sha256(b"honest").hexdigest())
        discard_temp(self.dir_fd, temp)

    def test_candidate_descriptor_stays_open_until_explicitly_closed(self):
        """The descriptor is the whole point of TempPayload: it must be live at return,
        answerable for identity checks, and released exactly once -- a stale descriptor
        *number* closed after recycling would hit some other thread's object."""
        temp = write_temp_payload(self.dir_fd, "doc", b"v1")
        # Live at return: fstat through the pinned fd must work and agree.
        info = os.fstat(temp.fd)
        self.assertEqual((info.st_dev, info.st_ino), temp.identity)
        temp.close()

        with mock.patch.object(txn.os, "close", side_effect=AssertionError("double close")):
            temp.close()  # idempotent: the second close never reaches the OS

    def test_write_error_closes_the_descriptor_and_removes_the_scratch_file(self):
        real_write = txn.os.write

        def failing_write(fd, data):
            raise OSError(5, "Input/output error")

        with mock.patch.object(txn.os, "write", side_effect=failing_write):
            with self.assertRaises(OSError):
                write_temp_payload(self.dir_fd, "doc", b"v1")
        self.assertEqual(self.scratch_names(), [])

    def test_quarantine_fallback_preserves_every_object_when_exchange_is_unsupported(self):
        with mock.patch.object(txn, "rename_exchange", side_effect=OSError(22, "EINVAL")):
            commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
                expected_absent=True,
            )
            ident = self.identity("doc")
            commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v2"),
                expected_identity=ident,
            )
            self.assertEqual(self.contents("doc"), b"v2")
            with self.assertRaises(OccupantConflict):
                commit_replacement(
                    self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v3"),
                    expected_identity=ident,
                )
            self.assertEqual(self.contents("doc"), b"v2", "fallback path harmed the occupant")
            self.assertEqual(self.scratch_names(), [])

    def test_post_commit_fsync_failure_is_uncertain_with_recovery_path(self):
        real_fsync = os.fsync

        def fail_once(fd):
            if os.fstat(fd).st_mode & 0o170000 == 0o040000:
                raise OSError("forced directory fsync failure")
            return real_fsync(fd)

        commit_replacement(
            self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
            expected_absent=True,
        )
        ident = self.identity("doc")
        with mock.patch.object(txn.os, "fsync", side_effect=fail_once):
            with self.assertRaises(CommitUncertain) as caught:
                commit_replacement(
                    self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v2"),
                    expected_identity=ident,
                )
        # The replacement did commit even though durability could not be confirmed.
        self.assertEqual(self.contents("doc"), b"v2")
        # The superseded bytes unlinked cleanly before the fsync failure, so there is
        # nothing left behind to recover -- the uncertainty names no leftovers.
        self.assertEqual(caught.exception.recovery_paths, ())

    def test_cas_over_vanished_occupant_refuses_under_exchange(self):
        with self.assertRaises(OccupantConflict):
            commit_replacement(
                self.dir_fd, "missing_doc", write_temp_payload(self.dir_fd, "missing_doc", b"v1"),
                expected_identity=(12345, 67890),
            )
        self.assertFalse((self.root / "missing_doc").exists())
        self.assertEqual(self.scratch_names(), [])

        with self.assertRaises(OccupantConflict):
            commit_replacement(
                self.dir_fd, "missing_doc2", write_temp_payload(self.dir_fd, "missing_doc2", b"v1"),
                expected_digest=hashlib.sha256(b"prior").hexdigest(),
            )
        self.assertFalse((self.root / "missing_doc2").exists())
        self.assertEqual(self.scratch_names(), [])

    def test_cas_over_vanished_occupant_refuses_under_fallback(self):
        with mock.patch.object(txn, "rename_exchange", side_effect=OSError(22, "EINVAL")):
            with self.assertRaises(OccupantConflict):
                commit_replacement(
                    self.dir_fd, "missing_doc", write_temp_payload(self.dir_fd, "missing_doc", b"v1"),
                    expected_identity=(12345, 67890),
                )
            self.assertFalse((self.root / "missing_doc").exists())
            self.assertEqual(self.scratch_names(), [])

            with self.assertRaises(OccupantConflict):
                commit_replacement(
                    self.dir_fd, "missing_doc2", write_temp_payload(self.dir_fd, "missing_doc2", b"v1"),
                    expected_digest=hashlib.sha256(b"prior").hexdigest(),
                )
            self.assertFalse((self.root / "missing_doc2").exists())
            self.assertEqual(self.scratch_names(), [])

    def test_quarantine_fallback_reports_displaced_identity_of_old_occupant(self):
        with mock.patch.object(txn, "rename_exchange", side_effect=OSError(22, "EINVAL")):
            commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
                expected_absent=True,
            )
            v1_ident = self.identity("doc")
            result = commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v2"),
                expected_identity=v1_ident,
            )
            self.assertEqual(result.displaced, v1_ident)
            v2_ident = self.identity("doc")
            self.assertNotEqual(result.displaced, v2_ident)

    def test_quarantine_fallback_unlink_failure_raises_commit_uncertain(self):
        with mock.patch.object(txn, "rename_exchange", side_effect=OSError(22, "EINVAL")):
            commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
                expected_absent=True,
            )
            v1_ident = self.identity("doc")
            real_unlink = os.unlink

            def fail_quarantine_unlink(path, *args, **kwargs):
                if ".txn-quarantine" in str(path):
                    raise OSError("cannot unlink quarantine")
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(txn.os, "unlink", side_effect=fail_quarantine_unlink):
                with self.assertRaises(CommitUncertain) as caught:
                    commit_replacement(
                        self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v2"),
                        expected_identity=v1_ident,
                    )
            self.assertEqual(self.contents("doc"), b"v2")
            self.assertEqual(len(caught.exception.recovery_paths), 1)
            self.assertTrue(caught.exception.recovery_paths[0].startswith(".txn-quarantine"))

    def _replace_candidate_name_with_impostor(self, temp, payload=b"impostor"):
        os.unlink(self.root / temp.name)
        (self.root / temp.name).write_bytes(payload)

    def test_commit_refuses_when_candidate_name_no_longer_names_our_inode(self):
        temp = write_temp_payload(self.dir_fd, "doc", b"v1")
        self._replace_candidate_name_with_impostor(temp)
        with self.assertRaises(OccupantConflict):
            commit_replacement(self.dir_fd, "doc", temp, expected_absent=True)
        self.assertEqual(self.contents(temp.name), b"impostor")
        self.assertFalse((self.root / "doc").exists())

    def test_cas_refuses_stolen_candidate_and_preserves_occupant(self):
        commit_replacement(
            self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
            expected_absent=True,
        )
        occupant = self.identity("doc")
        temp = write_temp_payload(self.dir_fd, "doc", b"v2")
        self._replace_candidate_name_with_impostor(temp)
        with self.assertRaises(OccupantConflict):
            commit_replacement(self.dir_fd, "doc", temp, expected_identity=occupant)
        self.assertEqual(self.contents("doc"), b"v1")
        self.assertEqual(self.identity("doc"), occupant)
        self.assertEqual(self.contents(temp.name), b"impostor")

    def test_quarantine_fallback_refuses_stolen_candidate_and_restores_occupant(self):
        real_is_ours = txn._candidate_is_ours

        def steal_after_first_check(dir_fd, temp):
            if steal_after_first_check.seen:
                if real_is_ours(dir_fd, temp):
                    os.unlink(self.root / temp.name)
                    (self.root / temp.name).write_bytes(b"impostor")
                return real_is_ours(dir_fd, temp)
            steal_after_first_check.seen = True
            return real_is_ours(dir_fd, temp)

        steal_after_first_check.seen = False
        with mock.patch.object(txn, "rename_exchange", side_effect=OSError(22, "EINVAL")):
            commit_replacement(
                self.dir_fd, "doc", write_temp_payload(self.dir_fd, "doc", b"v1"),
                expected_absent=True,
            )
            occupant = self.identity("doc")
            temp = write_temp_payload(self.dir_fd, "doc", b"v2")
            with mock.patch.object(txn, "_candidate_is_ours", side_effect=steal_after_first_check):
                with self.assertRaises(OccupantConflict):
                    commit_replacement(self.dir_fd, "doc", temp, expected_identity=occupant)
            self.assertEqual(self.contents("doc"), b"v1")
            self.assertEqual(self.identity("doc"), occupant)
            self.assertEqual(self.contents(temp.name), b"impostor")
            self.assertEqual(
                [name for name in self.scratch_names() if name.startswith(".txn-quarantine")],
                [],
            )

    def test_discard_temp_does_not_unlink_a_replaced_name(self):
        temp = write_temp_payload(self.dir_fd, "doc", b"ours")
        self._replace_candidate_name_with_impostor(temp)
        discard_temp(self.dir_fd, temp)
        self.assertEqual(self.contents(temp.name), b"impostor")

    def test_digest_expectation_caps_oversized_file(self):
        (self.root / "huge_doc").write_bytes(b"small_initial")
        real_fstat = os.fstat

        class FakeStat:
            def __init__(self, orig):
                self.st_size = 500 * 1024 * 1024
                self.st_dev = orig.st_dev
                self.st_ino = orig.st_ino
                self.st_mode = orig.st_mode

        def fake_fstat(fd):
            return FakeStat(real_fstat(fd))

        with mock.patch.object(txn.os, "fstat", side_effect=fake_fstat):
            with self.assertRaises(OccupantConflict):
                commit_replacement(
                    self.dir_fd, "huge_doc", write_temp_payload(self.dir_fd, "huge_doc", b"next"),
                    expected_digest=hashlib.sha256(b"small_initial").hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
