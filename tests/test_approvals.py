"""Trust-boundary tests for the independent operator-approval authority."""

import datetime
import json
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


class ApprovalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    def test_unconfigured_authority_fails_closed(self):
        os.environ.pop(STORE_ENV, None)
        with self.assertRaises(ApprovalError):
            verify_operator_approval("opa1.apr-1.s3cret", BINDINGS)

    def test_concurrent_verification_consumes_the_approval_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            outcomes = []
            lock = threading.Lock()

            # Force both attempts to finish reading before either can write. Under a
            # correct exclusive lock the second reader cannot start until the first has
            # consumed, so this barrier times out instead of pairing up.
            both_read = threading.Barrier(2)
            original_read = approvals._read_store

            def read_then_wait(path):
                document = original_read(path)
                try:
                    both_read.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
                return document

            approvals._read_store = read_then_wait
            self.addCleanup(setattr, approvals, "_read_store", original_read)

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
            original_replace = approvals.os.replace

            def tracked_fsync(handle):
                events.append("fsync")
                return original_fsync(handle)

            def tracked_replace(source, destination):
                events.append("replace")
                return original_replace(source, destination)

            with (
                mock.patch.object(approvals.os, "fsync", side_effect=tracked_fsync),
                mock.patch.object(approvals.os, "replace", side_effect=tracked_replace),
            ):
                verify_operator_approval("opa1.apr-1.s3cret", BINDINGS)

            self.assertEqual(events, ["fsync", "replace", "fsync"])

    def test_failed_replace_leaves_store_unconsumed_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store, token = issue(tmpdir)
            with mock.patch.object(approvals.os, "replace", side_effect=OSError("forced replace failure")):
                with self.assertRaises(ApprovalError):
                    verify_operator_approval(token, BINDINGS)

            with open(store, encoding="utf-8") as handle:
                self.assertFalse(json.load(handle)["approvals"][0].get("consumed"))
            self.assertEqual(list(Path(tmpdir).glob("approvals.json*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
