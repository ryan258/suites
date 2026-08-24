"""Adversarial gates for the JARVIS active mutation path.

Each test here reproduces a defect that was confirmed by probe rather than inferred:
an approval that authorized a path instead of the bytes at it, a checked destination
directory exchanged for a symlink while the approval was being verified, and a checked
destination file created before the write landed. All three needed something to change
*between* a check and its use, so each one drives that change from inside the approval
verification itself -- the exact window the real races occupy.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites import paths as paths_module
from portfolio_suites.approvals import STORE_ENV, ApprovalError
from portfolio_suites.engines import operator_os as engine_module
from portfolio_suites.engines.operator_os import OperatorOSEngine
from portfolio_suites.paths import install_new_file, remove_installed_file
from portfolio_suites.registry import SUITES_ROOT

try:
    from tests.test_approvals import issue, required_digest
except ImportError:
    try:
        from .test_approvals import issue, required_digest
    except ImportError:
        from test_approvals import issue, required_digest


class _RaceDuringApproval:
    """Run ``mutate`` inside approval verification, then verify for real."""

    def __init__(self, mutate):
        self.mutate = mutate
        self.original = engine_module.verify_operator_approval

    def __enter__(self):
        def verifying(token, bindings):
            self.mutate()
            return self.original(token, bindings)

        engine_module.verify_operator_approval = verifying
        return self

    def __exit__(self, *exc):
        engine_module.verify_operator_approval = self.original
        return False


class NoteSyncMutationTests(unittest.TestCase):
    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def _workspace(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source-notes"
        source.mkdir()
        (source / "one.md").write_text("# Reviewed\n", encoding="utf-8")
        return root, source

    def _run(self, params, token):
        return self.engine.execute_jarvis_action_checkpoint(
            "sync_obsidian_notes",
            params,
            operator_approved=True,
            operator_approval_token=token,
        )

    def test_a_token_does_not_survive_an_edit_to_the_source_note(self):
        """The substitution defect: a token issued for reviewed bytes must not write other bytes."""
        root, source = self._workspace()
        destination = root / "destination-notes"
        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }
        with tempfile.TemporaryDirectory() as approval_dir:
            digest = required_digest(self.engine, "sync_obsidian_notes", params)
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=digest,
            )
            (source / "one.md").write_text("# Substituted after approval\n", encoding="utf-8")
            receipt = self._run(params, token)

        self.assertEqual(receipt["status"], "error_unverified_approval")
        self.assertFalse(
            (destination / "one.md").exists(),
            "changed bytes were written under a token issued for different content",
        )

    def test_unchanged_bytes_still_verify_under_the_same_token(self):
        """The binding has to refuse substitution without refusing the approved work."""
        root, source = self._workspace()
        destination = root / "destination-notes"
        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }
        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=required_digest(self.engine, "sync_obsidian_notes", params),
            )
            receipt = self._run(params, token)

        self.assertEqual(receipt["status"], "success", receipt.get("error"))
        self.assertEqual(receipt["execution_result"]["files_synced"], ["one.md"])
        self.assertEqual((destination / "one.md").read_text(encoding="utf-8"), "# Reviewed\n")

    def test_a_destination_swapped_for_a_symlink_mid_approval_cannot_escape(self):
        root, source = self._workspace()
        destination = root / "destination-notes"
        destination.mkdir()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        escape_target = Path(outside.name)
        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }

        def swap():
            destination.rmdir()
            destination.symlink_to(escape_target)

        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=required_digest(self.engine, "sync_obsidian_notes", params),
            )
            with _RaceDuringApproval(swap):
                receipt = self._run(params, token)

        self.assertNotEqual(receipt["status"], "success")
        self.assertFalse(
            (escape_target / "one.md").exists(),
            f"note escaped SUITES_ROOT through a swapped destination ({receipt['status']})",
        )

    def test_a_destination_file_created_mid_approval_is_never_overwritten(self):
        root, source = self._workspace()
        destination = root / "destination-notes"
        destination.mkdir()
        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }

        def create_concurrently():
            (destination / "one.md").write_text("# Concurrent writer\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=required_digest(self.engine, "sync_obsidian_notes", params),
            )
            with _RaceDuringApproval(create_concurrently):
                receipt = self._run(params, token)

        self.assertEqual(receipt["status"], "error_sync_conflict")
        self.assertEqual(
            (destination / "one.md").read_text(encoding="utf-8"),
            "# Concurrent writer\n",
            "a file created after the conflict check was silently overwritten",
        )


class BackupBindingTests(unittest.TestCase):
    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_a_backup_token_does_not_survive_an_edit_to_its_inventory(self):
        snapshots = SUITES_ROOT / "operator-os" / "state" / "backups"
        before = set(snapshots.glob("*")) if snapshots.is_dir() else set()
        with tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os") as workspace:
            source = Path(workspace)
            (source / "note.md").write_text("reviewed\n", encoding="utf-8")
            params = {"vault": f"bound-{source.name}", "path": str(source), "dry_run": False}
            with tempfile.TemporaryDirectory() as approval_dir:
                _, token = issue(
                    approval_dir,
                    operation="jarvis_action_execution",
                    action_name="backup_data",
                    payload_sha256=required_digest(self.engine, "backup_data", params),
                )
                (source / "note.md").write_text("substituted\n", encoding="utf-8")
                receipt = self.engine.execute_jarvis_action_checkpoint(
                    "backup_data",
                    params,
                    operator_approved=True,
                    operator_approval_token=token,
                )
        for path in (set(snapshots.glob("*")) if snapshots.is_dir() else set()) - before:
            self.addCleanup(path.unlink, True)

        self.assertEqual(receipt["status"], "error_unverified_approval")
        self.assertEqual(
            (set(snapshots.glob("*")) if snapshots.is_dir() else set()) - before,
            set(),
            "a backup was written under a token bound to a different inventory",
        )


class UnapprovedMutationTests(unittest.TestCase):
    """A mutation nobody approved must not happen, including the ones that write nothing.

    The approval check only ran when there was a file to install, but the active branch
    opened the destination with ``create=True`` either way -- so a source with no eligible
    notes created the destination tree, and its own receipt reported
    ``operator_approval_verified: false`` beside a filesystem change.
    """

    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_an_empty_active_sync_creates_no_destination(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source-notes"
        source.mkdir()
        (source / "ignored.txt").write_text("not a note\n", encoding="utf-8")
        destination = root / "nested" / "destination-notes"

        receipt = self.engine.execute_jarvis_action_checkpoint(
            "sync_obsidian_notes",
            {
                "vault_path": str(source),
                "destination_path": str(destination),
                "dry_run": False,
            },
            operator_approved=True,
            operator_approval_token=None,
        )

        self.assertFalse(receipt["operator_approval_verified"])
        self.assertFalse(
            destination.exists() or destination.parent.exists(),
            "an unapproved active sync created its destination tree",
        )


class UnchangedReportingTests(unittest.TestCase):
    """`files_unchanged` has to describe the destination the receipt is issued against."""

    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_an_identical_file_changed_mid_approval_is_not_reported_unchanged(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source-notes"
        source.mkdir()
        (source / "kept.md").write_text("identical\n", encoding="utf-8")
        (source / "new.md").write_text("added\n", encoding="utf-8")
        destination = root / "destination-notes"
        destination.mkdir()
        (destination / "kept.md").write_text("identical\n", encoding="utf-8")

        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }

        def rewrite():
            (destination / "kept.md").write_text("edited by someone else\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=required_digest(self.engine, "sync_obsidian_notes", params),
            )
            with _RaceDuringApproval(rewrite):
                receipt = self.engine.execute_jarvis_action_checkpoint(
                    "sync_obsidian_notes",
                    params,
                    operator_approved=True,
                    operator_approval_token=token,
                )

        self.assertEqual(receipt["status"], "error_sync_conflict")
        self.assertIn("kept.md", receipt["error"])


class RollbackConfinementTests(unittest.TestCase):
    """Rollback has to unwind through the same discipline the install used.

    ``dir_fd`` anchors only the first lookup, so unlinking a slash-containing relative name
    still follows every intermediate component -- including one renamed away and replaced
    with a symlink after the batch created it.
    """

    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_a_failed_write_leaves_no_file_and_no_directory_behind(self):
        """A write that fails after O_EXCL creation owns its own garbage.

        The caller only records a file *after* ``install_new_file`` returns, so anything
        left behind by a mid-write failure is invisible to its rollback while the receipt
        still claims the sync was rolled back.
        """
        with tempfile.TemporaryDirectory() as tmp:
            directory_fd = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaises(UnicodeEncodeError):
                    install_new_file(directory_fd, "nested/deeper/note.md", "\udcff")
            finally:
                os.close(directory_fd)
            self.assertEqual(
                sorted(path.name for path in Path(tmp).iterdir()),
                [],
                "a failed install left partial artifacts the caller cannot roll back",
            )

    def test_rollback_does_not_follow_a_substituted_intermediate_directory(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source-notes"
        (source / "nested").mkdir(parents=True)
        (source / "nested" / "first.md").write_text("first\n", encoding="utf-8")
        (source / "nested" / "second.md").write_text("second\n", encoding="utf-8")
        destination = root / "destination-notes"

        outside = root / "outside"
        outside.mkdir()
        # Named for the file rollback will try to remove: through the substituted link,
        # `nested/first.md` resolves here.
        bystander = outside / "first.md"
        bystander.write_text("someone else's file\n", encoding="utf-8")

        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }

        def substitute():
            """Swap the created nested directory for a link, then break the second write."""
            created = destination / "nested"
            if not created.is_dir() or created.is_symlink():
                return
            created.rename(root / "moved-nested")
            created.symlink_to(outside, target_is_directory=True)

        # The first item installs, the second one collides with the bystander now visible
        # through the substituted link, and rollback of the first must not reach outside.
        original_install = engine_module.install_new_file

        def failing_install(directory_fd, relative, text):
            result = original_install(directory_fd, relative, text)
            if relative.endswith("first.md"):
                substitute()
            else:
                raise OSError("write failed after the tree was substituted")
            return result

        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=required_digest(self.engine, "sync_obsidian_notes", params),
            )
            engine_module.install_new_file = failing_install
            try:
                receipt = self.engine.execute_jarvis_action_checkpoint(
                    "sync_obsidian_notes",
                    params,
                    operator_approved=True,
                    operator_approval_token=token,
                )
            finally:
                engine_module.install_new_file = original_install

        self.assertEqual(receipt["status"], "error_sync_write_failed")
        self.assertTrue(
            bystander.exists(),
            "rollback followed a substituted intermediate link and deleted an external file",
        )


class CacheRotationConfinementTests(unittest.TestCase):
    """The rename has to reach the directory the approval was checked against."""

    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def _rotate(self, params, token):
        return self.engine.execute_jarvis_action_checkpoint(
            "rotate_local_cache",
            params,
            operator_approved=True,
            operator_approval_token=token,
        )

    def test_a_cache_replaced_mid_approval_is_not_rotated(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        cache = root / ".cache"
        cache.mkdir()
        (cache / "entry").write_text("approved\n", encoding="utf-8")

        decoy = root / "decoy"
        decoy.mkdir()
        (decoy / "entry").write_text("never approved\n", encoding="utf-8")

        params = {"cache_dir": str(cache), "dry_run": False}

        def swap():
            cache.rename(root / "approved-cache")
            decoy.rename(cache)

        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="rotate_local_cache",
                payload_sha256=required_digest(self.engine, "rotate_local_cache", params),
            )
            with _RaceDuringApproval(swap):
                receipt = self._rotate(params, token)

        self.assertEqual(receipt["status"], "error_invalid_cache_target")
        self.assertEqual(
            (cache / "entry").read_text(encoding="utf-8"),
            "never approved\n",
            "the substituted directory was rotated under the original approval",
        )

    def test_an_untouched_cache_still_rotates(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        cache = Path(workspace.name) / ".cache"
        cache.mkdir()
        (cache / "entry").write_text("approved\n", encoding="utf-8")
        params = {"cache_dir": str(cache), "dry_run": False}

        with tempfile.TemporaryDirectory() as approval_dir:
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="rotate_local_cache",
                payload_sha256=required_digest(self.engine, "rotate_local_cache", params),
            )
            receipt = self._rotate(params, token)

        self.assertEqual(receipt["status"], "success", receipt.get("error"))
        self.assertTrue(cache.is_dir())
        self.assertEqual(list(cache.iterdir()), [])
        rotated = Path(receipt["execution_result"]["rotated_path"])
        self.assertEqual((rotated / "entry").read_text(encoding="utf-8"), "approved\n")

    def test_a_symlinked_cache_target_is_refused(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        real = root / "real"
        real.mkdir()
        (real / "entry").write_text("outside\n", encoding="utf-8")
        cache = root / ".cache"
        cache.symlink_to(real, target_is_directory=True)
        # Refused in the same lookup that would have pinned it, so this never reaches the
        # approval check and needs no token.
        receipt = self._rotate({"cache_dir": str(cache), "dry_run": False}, None)

        self.assertEqual(receipt["status"], "error_invalid_cache_target")
        self.assertTrue(cache.is_symlink())
        self.assertTrue((real / "entry").exists())


if __name__ == "__main__":
    unittest.main()


class RollbackIdentityTests(unittest.TestCase):
    """Undo paths must remove their own work and nothing else.

    A rollback that unlinks by name deletes whatever now holds the name, and a conflict
    check that runs after the writes leaves those writes installed under an error status.
    Both defects need another writer to act between two of this code's own steps, so each
    test drives that writer from inside `install_new_file`.
    """

    def setUp(self):
        self.engine = OperatorOSEngine()
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def _workspace(self, notes):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source-notes"
        source.mkdir()
        for name, text in notes.items():
            (source / name).write_text(text, encoding="utf-8")
        return root, source

    def _run_synced(self, params, during_install):
        """Run a sync with `during_install` invoked after each real install."""
        original = engine_module.install_new_file

        def wrapped(directory_fd, relative, text):
            installed = original(directory_fd, relative, text)
            during_install(relative)
            return installed

        with tempfile.TemporaryDirectory() as approval_dir:
            digest = required_digest(self.engine, "sync_obsidian_notes", params)
            _, token = issue(
                approval_dir,
                operation="jarvis_action_execution",
                action_name="sync_obsidian_notes",
                payload_sha256=digest,
            )
            engine_module.install_new_file = wrapped
            try:
                return self.engine.execute_jarvis_action_checkpoint(
                    "sync_obsidian_notes",
                    params,
                    operator_approved=True,
                    operator_approval_token=token,
                )
            finally:
                engine_module.install_new_file = original

    def test_a_late_conflict_rolls_back_the_notes_this_run_installed(self):
        """The unchanged-note recheck runs after the writes, so failing it must undo them."""
        root, source = self._workspace({"one.md": "# Reviewed\n", "two.md": "# Also\n"})
        destination = root / "destination-notes"
        destination.mkdir()
        # `one.md` is already identical, so it is inventoried as unchanged and only
        # revalidated at the very end -- after `two.md` has been installed.
        (destination / "one.md").write_text("# Reviewed\n", encoding="utf-8")
        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }

        def change_the_unchanged_note(_relative):
            (destination / "one.md").write_text("# Edited by someone else\n", encoding="utf-8")

        receipt = self._run_synced(params, change_the_unchanged_note)

        self.assertEqual(receipt["status"], "error_sync_conflict")
        self.assertFalse(
            (destination / "two.md").exists(),
            "a run that reported a conflict left its own note installed",
        )
        self.assertIn("rolled back", receipt.get("error", ""))

    def test_rollback_refuses_to_delete_another_writers_file(self):
        """Replacing an installed name before the undo must not turn the undo into a deletion."""
        root, source = self._workspace({"one.md": "# Reviewed\n", "two.md": "# Also\n"})
        destination = root / "destination-notes"
        params = {
            "vault_path": str(source),
            "destination_path": str(destination),
            "dry_run": False,
        }
        installed_first: list[str] = []

        def swap_then_fail(relative):
            installed_first.append(relative)
            if len(installed_first) == 1:
                return
            # A second writer replaced the first installed note with its own file, and
            # this batch then fails. Rollback must leave the bystander alone.
            bystander = destination / installed_first[0]
            bystander.unlink()
            bystander.write_text("# Owned by someone else\n", encoding="utf-8")
            raise OSError("write failed after the name was reused")

        receipt = self._run_synced(params, swap_then_fail)

        self.assertEqual(receipt["status"], "error_sync_write_failed")
        survivor = destination / installed_first[0]
        self.assertTrue(survivor.exists(), "rollback deleted a file it did not create")
        self.assertEqual(
            survivor.read_text(encoding="utf-8"),
            "# Owned by someone else\n",
            "rollback removed another writer's content",
        )


class QuarantineNoReplaceTests(unittest.TestCase):
    """Both rollback moves refuse collisions and preserve every writer's bytes."""

    @staticmethod
    def _identity(path: Path) -> tuple[int, int]:
        info = path.stat()
        return info.st_dev, info.st_ino

    def test_matching_install_is_removed_through_no_replace_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = Path(tmp)
            target = anchor / "note.md"
            target.write_text("installed", encoding="utf-8")

            outcome = remove_installed_file(anchor, "note.md", self._identity(target))

            self.assertTrue(outcome)
            self.assertFalse(target.exists())

    def test_existing_quarantine_name_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = Path(tmp)
            target = anchor / "note.md"
            target.write_text("installed", encoding="utf-8")
            quarantine = anchor / ".rollback-quarantine.fixed"
            quarantine.write_text("older recovery", encoding="utf-8")

            with patch.object(paths_module.secrets, "token_hex", return_value="fixed"):
                outcome = remove_installed_file(anchor, "note.md", self._identity(target))

            self.assertFalse(outcome)
            self.assertIn("already occupied", outcome.conflict or "")
            self.assertEqual(target.read_text(encoding="utf-8"), "installed")
            self.assertEqual(quarantine.read_text(encoding="utf-8"), "older recovery")

    def test_restore_never_overwrites_a_newer_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = Path(tmp)
            target = anchor / "note.md"
            target.write_text("writer B", encoding="utf-8")
            real_stat = paths_module.os.stat
            raced = False

            def recreate_after_quarantine(path, *args, **kwargs):
                nonlocal raced
                current = real_stat(path, *args, **kwargs)
                if path == ".rollback-quarantine.fixed" and not raced:
                    raced = True
                    target.write_text("writer C", encoding="utf-8")
                return current

            with (
                patch.object(paths_module.secrets, "token_hex", return_value="fixed"),
                patch.object(paths_module.os, "stat", side_effect=recreate_after_quarantine),
            ):
                outcome = remove_installed_file(anchor, "note.md", (0, 0))

            self.assertFalse(outcome)
            self.assertTrue(raced)
            self.assertEqual(target.read_text(encoding="utf-8"), "writer C")
            self.assertIsNotNone(outcome.recovery_path)
            recovery = anchor / str(outcome.recovery_path)
            self.assertEqual(recovery.read_text(encoding="utf-8"), "writer B")
            self.assertIn("without replacing", outcome.conflict or "")


class ConfinedInstallTests(unittest.TestCase):
    """`_install_confined_bytes` claims it never overwrites, and that a raise installs nothing."""

    def _directory(self):
        workspace = tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        self.addCleanup(os.close, fd)
        return root, fd

    def test_an_existing_destination_is_refused_not_replaced(self):
        root, fd = self._directory()
        (root / "snapshot.zip").write_text("owned by another writer", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            engine_module._install_confined_bytes(fd, "snapshot.zip", b"approved payload")

        self.assertEqual(
            (root / "snapshot.zip").read_text(encoding="utf-8"),
            "owned by another writer",
            "an atomic installer overwrote a destination it was told not to replace",
        )

    def test_a_failure_after_the_name_is_taken_installs_nothing(self):
        """A directory fsync that fails must not leave the artifact behind under an error."""
        root, fd = self._directory()
        real_fsync = os.fsync
        seen: list[int] = []

        def failing_fsync(target):
            seen.append(target)
            if len(seen) > 1:  # the file fsync succeeds; the directory fsync does not
                raise OSError("simulated directory fsync failure")
            return real_fsync(target)

        engine_module.os.fsync = failing_fsync
        try:
            with self.assertRaises(OSError):
                engine_module._install_confined_bytes(fd, "snapshot.zip", b"approved payload")
        finally:
            engine_module.os.fsync = real_fsync

        self.assertFalse(
            (root / "snapshot.zip").exists(),
            "an error was reported over an artifact that is still installed",
        )
        self.assertEqual(
            [entry for entry in os.listdir(root)], [], "the temporary was left behind"
        )


class RollbackBystanderTests(unittest.TestCase):
    """A rollback that unlinks by name deletes whatever answers to that name.

    Each case reproduces the same window: the operation creates its object, another writer
    takes the name, the operation then fails and rolls back. The bystander must survive.
    """

    def test_install_new_file_cleanup_never_deletes_a_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            anchor = Path(root)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)

            real_fsync = os.fsync
            swapped = []

            def fsync_after_swap(fd):
                # The directory fsync is the failure point, and the gap it opens is where a
                # concurrent writer replaces the name this call just created.
                if not swapped and os.fstat(fd).st_mode & 0o170000 == 0o040000:
                    swapped.append(True)
                    (anchor / "note.txt").unlink()
                    (anchor / "note.txt").write_text("bystander", encoding="utf-8")
                    raise OSError("forced directory fsync failure")
                return real_fsync(fd)

            with patch.object(os, "fsync", fsync_after_swap):
                with self.assertRaises(OSError):
                    install_new_file(directory_fd, "note.txt", "ours")

            self.assertTrue(swapped, "the interleaving never ran")
            self.assertTrue((anchor / "note.txt").is_file(), "cleanup deleted the other writer's file")
            self.assertEqual((anchor / "note.txt").read_text(encoding="utf-8"), "bystander")

    def test_confined_install_cleanup_never_deletes_a_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            anchor = Path(root)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)

            real_fsync = os.fsync
            swapped = []

            def fsync_after_swap(fd):
                if not swapped and os.fstat(fd).st_mode & 0o170000 == 0o040000:
                    swapped.append(True)
                    (anchor / "artifact.json").unlink()
                    (anchor / "artifact.json").write_text("bystander", encoding="utf-8")
                    raise OSError("forced directory fsync failure")
                return real_fsync(fd)

            with patch.object(os, "fsync", fsync_after_swap):
                with self.assertRaises(OSError):
                    engine_module._install_confined_bytes(directory_fd, "artifact.json", b"ours")

            self.assertTrue(swapped, "the interleaving never ran")
            self.assertEqual(
                (anchor / "artifact.json").read_text(encoding="utf-8"),
                "bystander",
                "cleanup deleted the other writer's file",
            )

    def test_rollback_rename_refuses_to_replace_a_reclaimed_name(self):
        """The primitive the cache rollback now uses must never overwrite an occupant."""
        with tempfile.TemporaryDirectory() as root:
            anchor = Path(root)
            (anchor / "rotated").write_text("unapproved", encoding="utf-8")
            (anchor / "cache").write_text("someone-elses", encoding="utf-8")
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)

            with self.assertRaises(OSError):
                paths_module.rename_no_replace("rotated", "cache", directory_fd=directory_fd)

            # Both objects survive; neither inode was destroyed.
            self.assertEqual((anchor / "cache").read_text(encoding="utf-8"), "someone-elses")
            self.assertEqual((anchor / "rotated").read_text(encoding="utf-8"), "unapproved")


class ConfinedReadParentRaceTests(unittest.TestCase):
    """A confinement decision on a pathname is void the moment the pathname is reopened.

    The final component being O_NOFOLLOW says nothing about its parents: exchanging an
    already-checked parent for a symlink redirects the read outside the workspace with
    every check still passing, and the backup path binds what it read into an archive.
    """

    def test_a_parent_swapped_after_the_check_cannot_redirect_the_read(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            anchor = Path(workspace)
            (anchor / "suites").mkdir()
            inside_dir = anchor / "donor"
            inside_dir.mkdir()
            (inside_dir / "note.txt").write_text("inside the workspace", encoding="utf-8")

            outside_dir = Path(outside)
            (outside_dir / "note.txt").write_text("OUTSIDE THE WORKSPACE", encoding="utf-8")

            target = inside_dir / "note.txt"
            real_confined_path = engine_module._confined_path
            swapped = []

            def confined_then_swap(raw_path, **kwargs):
                resolved = real_confined_path(raw_path, **kwargs)
                if resolved is not None and not swapped:
                    swapped.append(True)
                    # The window between the confinement decision and the open.
                    (inside_dir / "note.txt").unlink()
                    inside_dir.rmdir()
                    (anchor / "donor").symlink_to(outside_dir, target_is_directory=True)
                return resolved

            with patch.object(engine_module, "SUITES_ROOT", anchor / "suites"), \
                 patch.object(engine_module, "_confined_path", confined_then_swap):
                data = engine_module._read_confined_file(target)

            self.assertTrue(swapped, "the interleaving never ran")
            self.assertIsNone(data, "a swapped parent redirected the read outside the workspace")
