"""Trust-boundary tests for the independent operator-approval authority."""

import datetime
import json
import math
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from portfolio_suites import approvals
from portfolio_suites.approvals import (
    APPROVAL_SCHEMA,
    STORE_ENV,
    ApprovalCommitUnverified,
    ApprovalError,
    canonical_digest,
    token_sha256,
    verify_operator_approval,
)

BINDINGS = {"operation": "vcc_release", "decision": "approved", "payload_sha256": canonical_digest("draft")}


def issue(tmpdir, **overrides):
    """Write one authority record and point the environment at it."""
    record = {
        "approval_id": "apr-1",
        "schema": APPROVAL_SCHEMA,
        "reviewer": "Ryan Johnson",
        "issued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "expires_at": "2099-01-01T00:00:00+00:00",
        **BINDINGS,
    }
    record.update(overrides)
    for key, value in list(record.items()):
        if value is None:
            del record[key]
    token = f"opa1.{record['approval_id']}.s3cret"
    record.setdefault("token_sha256", token_sha256(token))
    store = os.path.join(tmpdir, "approvals.json")
    with open(store, "w", encoding="utf-8") as handle:
        json.dump({"approvals": [record]}, handle)
    os.environ[STORE_ENV] = store
    return store, token


def required_digest(engine, action_name, params):
    """Ask the engine which exact payload it will authorize.

    The v2 envelope binds detached content digests, so the value cannot be reconstructed
    from the command line alone. One unapproved run reports it, which is the same two-step
    an operator performs: run, read the digest, get that digest approved, run again.
    """
    os.environ.pop(STORE_ENV, None)
    refusal = engine.execute_jarvis_action_checkpoint(
        action_name, params, operator_approved=True
    )
    assert refusal["status"] == "error_unverified_approval", refusal["status"]
    return refusal["approval_payload_sha256"]


class ApprovalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_unconfigured_authority_fails_closed(self):
        os.environ.pop(STORE_ENV, None)
        with self.assertRaises(ApprovalError):
            verify_operator_approval("opa1.apr-1.s3cret", BINDINGS)

    def test_approval_digest_rejects_nonfinite_json(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_digest({"value": value})

    def test_concurrent_verification_consumes_the_approval_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            outcomes = []
            lock = threading.Lock()

            # Force both attempts to finish reading before either can write. Under a
            # correct exclusive lock the second reader cannot start until the first has
            # consumed, so this barrier times out instead of pairing up.
            both_read = threading.Barrier(2)
            original_read = approvals._read_store_fd

            def read_then_wait(filename, dir_fd):
                res = original_read(filename, dir_fd)
                try:
                    both_read.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
                return res

            approvals._read_store_fd = read_then_wait
            self.addCleanup(setattr, approvals, "_read_store_fd", original_read)

            def attempt():
                try:
                    verify_operator_approval(token, BINDINGS)
                    result = "verified"
                except ApprovalError:
                    result = "blocked"
                with lock:
                    outcomes.append(result)

            threads = [threading.Thread(target=attempt) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(outcomes.count("verified"), 1, outcomes)
            self.assertEqual(outcomes.count("blocked"), 1, outcomes)
            with open(store, encoding="utf-8") as handle:
                self.assertTrue(json.load(handle)["approvals"][0]["consumed"])

    def test_malformed_records_are_rejected_without_burning_the_approval(self):
        malformed = {
            "missing_reviewer": {"reviewer": None},
            "empty_reviewer": {"reviewer": "   "},
            "wrong_type_reviewer": {"reviewer": 42},
            "missing_schema": {"schema": None},
            "wrong_schema": {"schema": "operator-approval-v0"},
            "missing_payload_digest": {"payload_sha256": None},
            "naive_expiry": {"expires_at": "2099-01-01T00:00:00"},
            "issued_in_future": {"issued_at": "2099-06-01T00:00:00+00:00"},
            "expiry_before_issue": {"expires_at": "2020-01-01T00:00:00+00:00"},
        }
        for label, overrides in malformed.items():
            with tempfile.TemporaryDirectory() as tmpdir:
                store, token = issue(tmpdir, **overrides)
                with self.assertRaises(ApprovalError, msg=label):
                    verify_operator_approval(token, BINDINGS)
                with open(store, encoding="utf-8") as handle:
                    self.assertFalse(json.load(handle)["approvals"][0].get("consumed"), label)

    def test_verified_record_guarantees_the_fields_consumers_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            issue(tmpdir)
            record = verify_operator_approval("opa1.apr-1.s3cret", BINDINGS)
            for field in ("approval_id", "reviewer", "operation", "decision", "payload_sha256", "issued_at"):
                self.assertIsInstance(record[field], str)
            self.assertTrue(record["reviewer"].strip())

    def test_consumption_records_when_and_against_what_it_was_spent(self):
        """A spent approval must stay auditable: `consumed: true` alone loses the why."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            before = datetime.datetime.now(datetime.timezone.utc)
            record = verify_operator_approval(token, BINDINGS)

            with open(store, encoding="utf-8") as handle:
                stored = json.load(handle)["approvals"][0]
            self.assertTrue(stored["consumed"])
            consumed_at = datetime.datetime.fromisoformat(stored["consumed_at"])
            self.assertIsNotNone(consumed_at.tzinfo)
            self.assertGreaterEqual(consumed_at, before)
            self.assertEqual(
                stored["consumed_bindings"], {k: str(v) for k, v in sorted(BINDINGS.items())}
            )
            # The returned copy carries the same stamp the store kept.
            self.assertEqual(record["consumed_at"], stored["consumed_at"])
            self.assertEqual(record["consumed_bindings"], stored["consumed_bindings"])

    def test_unbound_or_mismatched_bindings_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, {**BINDINGS, "payload_sha256": canonical_digest("other draft")})
            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, {**BINDINGS, "source_id": "src-never-bound"})
            with open(store, encoding="utf-8") as handle:
                self.assertFalse(json.load(handle)["approvals"][0].get("consumed"))

    def test_consumption_is_synced_before_verification_returns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            issue(tmpdir)
            events = []
            original_fsync = approvals.os.fsync
            original_commit = approvals.commit_replacement

            def tracked_fsync(handle):
                events.append("fsync")
                return original_fsync(handle)

            def tracked_commit(*args, **kwargs):
                # The compare-and-swap is the commit point: the payload must already be
                # fsynced when it runs, and only the post-commit directory fsync may follow.
                events.append("cas_commit")
                return original_commit(*args, **kwargs)

            with (
                mock.patch.object(approvals.os, "fsync", side_effect=tracked_fsync),
                mock.patch.object(approvals, "commit_replacement", side_effect=tracked_commit),
            ):
                verify_operator_approval("opa1.apr-1.s3cret", BINDINGS)

            self.assertEqual(events, ["fsync", "cas_commit", "fsync"])

    def test_a_failed_cas_leaves_store_unconsumed_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            with mock.patch.object(
                approvals, "commit_replacement", side_effect=OSError("forced commit failure")
            ):
                with self.assertRaises(ApprovalError):
                    verify_operator_approval(token, BINDINGS)

            with open(store, encoding="utf-8") as handle:
                self.assertFalse(json.load(handle)["approvals"][0].get("consumed"))
            leftovers = [
                p.name for p in Path(tmpdir).iterdir()
                if p.name != Path(store).name and p.name != Path(store).name + ".lock"
            ]
            self.assertEqual(leftovers, [], leftovers)

    def test_a_store_replaced_by_the_issuer_during_consume_loses_no_approvals(self):
        """The check-then-replace hole: an out-of-band issuer replaces the store between
        the authority's read and its commit. The consumption must be refused and the
        issuer's newly issued approvals must survive untouched at the canonical name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            issuer_document = {
                "approvals": [
                    json.loads(Path(store).read_text(encoding="utf-8"))["approvals"][0],
                    {
                        "approval_id": "apr-issued-concurrently",
                        "schema": APPROVAL_SCHEMA,
                        "reviewer": "Out-of-band Issuer",
                        "issued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "expires_at": "2099-01-01T00:00:00+00:00",
                        **BINDINGS,
                        "token_sha256": token_sha256("opa1.apr-issued-concurrently.s3cret"),
                    },
                ]
            }
            original_read = approvals._read_store_fd

            def read_then_replace_store_as_issuer(filename, dir_fd):
                res = original_read(filename, dir_fd)
                # The issuer does not take our lock: it writes its own newer store and
                # swaps it into place while this consumer sits between read and commit.
                issued_name = f"{filename}.issuer-{os.getpid()}.tmp"
                payload = json.dumps(issuer_document, indent=2).encode("utf-8")
                issued_fd = os.open(
                    issued_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dir_fd
                )
                with os.fdopen(issued_fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(issued_name, filename, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                return res

            approvals._read_store_fd = read_then_replace_store_as_issuer
            self.addCleanup(setattr, approvals, "_read_store_fd", original_read)

            with self.assertRaises(ApprovalError) as caught:
                verify_operator_approval(token, BINDINGS)

            self.assertIn("changed after it was read", str(caught.exception))
            surviving = json.loads(Path(store).read_text(encoding="utf-8"))
            self.assertEqual(len(surviving["approvals"]), 2, "the issuer lost a concurrent approval")
            self.assertFalse(surviving["approvals"][0].get("consumed"), "nothing was consumed")
            self.assertFalse(surviving["approvals"][1].get("consumed"))
            leftovers = [p.name for p in Path(tmpdir).iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [], leftovers)

    def test_an_in_place_store_rewrite_as_issuer_preserves_new_approvals(self):
        """The in-place truncate-and-rewrite probe: an issuer adds an approval by truncating
        and rewriting the store in place without changing its inode. The digest-bound CAS
        must detect the change, reject the stale consumption, and preserve the new approval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            issuer_document = {
                "approvals": [
                    json.loads(Path(store).read_text(encoding="utf-8"))["approvals"][0],
                    {
                        "approval_id": "apr-issuer-concurrent-inplace",
                        "schema": APPROVAL_SCHEMA,
                        "reviewer": "Concurrent In-Place Issuer",
                        "issued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "expires_at": "2099-01-01T00:00:00+00:00",
                        **BINDINGS,
                        "token_sha256": token_sha256("opa1.apr-issuer-concurrent-inplace.s3cret"),
                    },
                ]
            }
            original_read = approvals._read_store_fd

            def read_then_rewrite_store_in_place(filename, dir_fd):
                res = original_read(filename, dir_fd)
                payload = json.dumps(issuer_document, indent=2).encode("utf-8")
                # Truncate and rewrite the existing file descriptor/name in place (retaining inode)
                store_fd = os.open(filename, os.O_WRONLY | os.O_TRUNC, dir_fd=dir_fd)
                try:
                    os.write(store_fd, payload)
                    os.fsync(store_fd)
                finally:
                    os.close(store_fd)
                return res

            approvals._read_store_fd = read_then_rewrite_store_in_place
            self.addCleanup(setattr, approvals, "_read_store_fd", original_read)

            with self.assertRaises(ApprovalError) as caught:
                verify_operator_approval(token, BINDINGS)

            self.assertIn("changed after it was read", str(caught.exception))
            surviving = json.loads(Path(store).read_text(encoding="utf-8"))
            self.assertEqual(len(surviving["approvals"]), 2, "the issuer lost a concurrent in-place approval")
            self.assertFalse(surviving["approvals"][0].get("consumed"), "nothing was consumed")
            self.assertFalse(surviving["approvals"][1].get("consumed"))

    def test_a_bystander_swapped_into_the_store_name_preserves_both_documents(self):
        """The displaced-original probe: the verified store is moved aside and replaced by
        a bystander before the commit. A replacing rename would destroy the bystander and
        still report a successful consumption; the compare-and-swap must refuse instead and
        leave every object alive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            bystander_bytes = json.dumps({
                "approvals": [{
                    "approval_id": "apr-bystander",
                    "schema": APPROVAL_SCHEMA,
                    "reviewer": "Bystander Authority",
                    "issued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    **BINDINGS,
                    "token_sha256": token_sha256("opa1.apr-bystander.s3cret"),
                }]
            }, indent=2).encode("utf-8")
            original_read = approvals._read_store_fd
            displaced_path = Path(tmpdir) / "displaced-original.json"

            def read_then_swap_in_bystander(filename, dir_fd):
                res = original_read(filename, dir_fd)
                os.rename(filename, displaced_path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                bystander_name = f"{filename}.bystander-{os.getpid()}.tmp"
                bystander_fd = os.open(
                    bystander_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dir_fd
                )
                with os.fdopen(bystander_fd, "wb") as stream:
                    stream.write(bystander_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(bystander_name, filename, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                return res

            approvals._read_store_fd = read_then_swap_in_bystander
            self.addCleanup(setattr, approvals, "_read_store_fd", original_read)

            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, BINDINGS)

            self.assertEqual(
                Path(store).read_bytes(), bystander_bytes, "the bystander authority was destroyed"
            )
            self.assertTrue(displaced_path.is_file(), "the displaced original was destroyed")
            self.assertNotIn('"consumed"', displaced_path.read_text(encoding="utf-8"))

    def test_symlink_store_is_refused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            symlink_store = os.path.join(tmpdir, "alias_store.json")
            os.symlink(store, symlink_store)
            os.environ[STORE_ENV] = symlink_store
            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, BINDINGS)
            with open(store, encoding="utf-8") as handle:
                self.assertFalse(json.load(handle)["approvals"][0].get("consumed"))

    def test_hardlink_store_is_refused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            hardlink_store = os.path.join(tmpdir, "hardlink_store.json")
            os.link(store, hardlink_store)
            os.environ[STORE_ENV] = hardlink_store
            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, BINDINGS)
            with open(store, encoding="utf-8") as handle:
                self.assertFalse(json.load(handle)["approvals"][0].get("consumed"))



class JarvisMutationBoundaryTests(unittest.TestCase):
    """The one JARVIS handler that writes to disk must need the authority, not a boolean."""

    ACTION = "backup_data"

    def setUp(self):
        self.addCleanup(os.environ.pop, STORE_ENV, None)
        from portfolio_suites.engines.operator_os import OperatorOSEngine
        from portfolio_suites.registry import SUITES_ROOT

        self.engine = OperatorOSEngine
        self.snapshots = Path(SUITES_ROOT) / "operator-os" / "state" / "backups"
        self.before = set(self.snapshots.glob("snap-*")) if self.snapshots.is_dir() else set()

    def _written(self):
        now = set(self.snapshots.glob("snap-*")) if self.snapshots.is_dir() else set()
        return now - self.before

    def _params(self):
        return {"vault": "boundary-test", "path": "contracts", "dry_run": False}

    def test_active_backup_without_a_token_writes_nothing(self):
        os.environ.pop(STORE_ENV, None)
        receipt = self.engine.execute_jarvis_action_checkpoint(
            self.ACTION, self._params(), operator_approved=True
        )
        self.assertEqual(receipt["status"], "error_unverified_approval")
        self.assertFalse(receipt["operator_approval_verified"])
        self.assertIsNone(receipt["execution_receipt"])
        self.assertEqual(self._written(), set(), "a refused backup must leave no manifest behind")

    def test_a_token_bound_to_other_parameters_is_refused(self):
        params = self._params()
        with tempfile.TemporaryDirectory() as tmp:
            _, token = issue(
                tmp,
                operation="jarvis_action_execution",
                action_name=self.ACTION,
                payload_sha256=canonical_digest(
                    {"action_name": self.ACTION, "parameters": {**params, "path": "docs"}}
                ),
            )
            receipt = self.engine.execute_jarvis_action_checkpoint(
                self.ACTION, params, operator_approved=True, operator_approval_token=token
            )
        self.assertEqual(receipt["status"], "error_unverified_approval")
        self.assertEqual(self._written(), set())

    def test_a_bound_token_permits_exactly_one_backup(self):
        params = self._params()
        with tempfile.TemporaryDirectory() as tmp:
            _, token = issue(
                tmp,
                operation="jarvis_action_execution",
                action_name=self.ACTION,
                payload_sha256=required_digest(self.engine, self.ACTION, params),
            )
            first = self.engine.execute_jarvis_action_checkpoint(
                self.ACTION, params, operator_approved=True, operator_approval_token=token
            )
            written = self._written()
            for path in written:
                self.addCleanup(path.unlink, True)
            # The authority consumes on use, so the same token cannot run a second backup.
            replay = self.engine.execute_jarvis_action_checkpoint(
                self.ACTION, params, operator_approved=True, operator_approval_token=token
            )

        self.assertEqual(first["status"], "success")
        self.assertTrue(first["execution_result"]["manifest_file"])
        self.assertTrue(first["execution_result"]["archive_file"])
        self.assertTrue(first["execution_result"]["backup_payload_created"])
        self.assertGreater(first["execution_result"]["files_backed_up"], 0)
        self.assertEqual(len(written), 2)
        self.assertEqual(replay["status"], "error_unverified_approval")

    def test_skipped_sensitive_count_participates_in_snapshot_identity(self):
        from portfolio_suites.registry import SUITES_ROOT

        with tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os") as source_dir:
            source = Path(source_dir)
            (source / "note.md").write_text("ordinary\n", encoding="utf-8")
            params = {
                "vault": f"sensitive-identity-{source.name}",
                "path": str(source),
                "dry_run": False,
            }

            with tempfile.TemporaryDirectory() as approval_dir:
                _, first_token = issue(
                    approval_dir,
                    operation="jarvis_action_execution",
                    action_name=self.ACTION,
                    payload_sha256=required_digest(self.engine, self.ACTION, params),
                )
                first = self.engine.execute_jarvis_action_checkpoint(
                    self.ACTION,
                    params,
                    operator_approved=True,
                    operator_approval_token=first_token,
                )
            for path in self._written():
                self.addCleanup(path.unlink, True)

            (source / ".env").write_text("OPENROUTER_API_KEY=never-read\n", encoding="utf-8")
            with tempfile.TemporaryDirectory() as approval_dir:
                _, second_token = issue(
                    approval_dir,
                    operation="jarvis_action_execution",
                    action_name=self.ACTION,
                    payload_sha256=required_digest(self.engine, self.ACTION, params),
                )
                second = self.engine.execute_jarvis_action_checkpoint(
                    self.ACTION,
                    params,
                    operator_approved=True,
                    operator_approval_token=second_token,
                )
            for path in self._written():
                self.addCleanup(path.unlink, True)

        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")
        self.assertNotEqual(
            first["execution_result"]["snapshot_id"],
            second["execution_result"]["snapshot_id"],
        )
        self.assertEqual(first["execution_result"]["skipped_sensitive_count"], 0)
        self.assertEqual(second["execution_result"]["skipped_sensitive_count"], 1)

    def test_dry_run_still_works_without_any_authority(self):
        os.environ.pop(STORE_ENV, None)
        receipt = self.engine.execute_jarvis_action_checkpoint(
            self.ACTION, {**self._params(), "dry_run": True}, operator_approved=True
        )
        self.assertEqual(receipt["status"], "success")
        self.assertEqual(receipt["execution_result"]["manifest_file"], "")
        self.assertEqual(self._written(), set())

    def test_bound_token_permits_reversible_cache_rotation(self):
        from portfolio_suites.registry import SUITES_ROOT

        with tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os") as workspace:
            cache = Path(workspace) / ".cache"
            cache.mkdir()
            (cache / "entry.bin").write_bytes(b"cache data")
            params = {"cache_dir": str(cache), "dry_run": False}
            with tempfile.TemporaryDirectory() as approval_dir:
                _, token = issue(
                    approval_dir,
                    operation="jarvis_action_execution",
                    action_name="rotate_local_cache",
                    payload_sha256=required_digest(self.engine, "rotate_local_cache", params),
                )
                receipt = self.engine.execute_jarvis_action_checkpoint(
                    "rotate_local_cache",
                    params,
                    operator_approved=True,
                    operator_approval_token=token,
                )

            rotated = Path(receipt["execution_result"]["rotated_path"])
            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["operator_approval_verified"])
            self.assertTrue(receipt["execution_result"]["rotated"])
            self.assertTrue(cache.is_dir())
            self.assertEqual(list(cache.iterdir()), [])
            self.assertEqual((rotated / "entry.bin").read_bytes(), b"cache data")
            self.assertIn("rename", receipt["execution_result"]["recovery"])

    def test_bound_token_permits_conflict_refusing_additive_note_sync(self):
        from portfolio_suites.registry import SUITES_ROOT

        with tempfile.TemporaryDirectory(dir=SUITES_ROOT / "operator-os") as workspace:
            source = Path(workspace) / "source-notes"
            destination = Path(workspace) / "destination-notes"
            source.mkdir()
            (source / "one.md").write_text("# One\n", encoding="utf-8")
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
                receipt = self.engine.execute_jarvis_action_checkpoint(
                    "sync_obsidian_notes",
                    params,
                    operator_approved=True,
                    operator_approval_token=token,
                )

            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["operator_approval_verified"])
            self.assertTrue(receipt["execution_result"]["sync_performed"])
            self.assertEqual(receipt["execution_result"]["files_synced"], ["one.md"])
            self.assertEqual((destination / "one.md").read_text(encoding="utf-8"), "# One\n")


class CommitUnverifiedTests(unittest.TestCase):
    """A failure after the commit point is a different fact from a failure before it.

    Reporting a post-replacement fsync failure as "cannot consume" tells an operator the
    token is still spendable when the durable store already says it is spent.
    """

    def setUp(self):
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_a_post_replacement_fsync_failure_says_the_token_may_be_spent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, token = issue(tmp)

            real_fsync = os.fsync
            replaced = []

            def fsync_after_replace(fd):
                # Directories only: the file fsync happens before the commit point.
                if os.fstat(fd).st_mode & 0o170000 == 0o040000 and not replaced:
                    replaced.append(True)
                    raise OSError("forced directory fsync failure")
                return real_fsync(fd)

            with mock.patch.object(os, "fsync", fsync_after_replace):
                with self.assertRaises(ApprovalCommitUnverified) as caught:
                    verify_operator_approval(token, BINDINGS)

            self.assertTrue(replaced, "the interleaving never ran")
            self.assertEqual(caught.exception.approval_id, "apr-1")
            self.assertIn("may already be spent", str(caught.exception))
            # And it is: the durable document already records the consumption.
            document = json.loads(Path(store).read_text(encoding="utf-8"))
            self.assertTrue(document["approvals"][0]["consumed"], "the store shows the token was spent")


if __name__ == "__main__":
    unittest.main()

