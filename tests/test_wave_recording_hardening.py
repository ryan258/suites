import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.cli import EXIT_FAILED, EXIT_INCOMPLETE, main
from portfolio_suites.waves import (
    EvidenceCommitUnverified,
    WaveRunResult,
    WaveRunner,
    _record_evidence,
    format_wave_tag,
)


class EvidenceRecordingHardeningTests(unittest.TestCase):
    def test_manifest_evidence_path_cannot_escape_suite_root(self):
        malicious = {
            "id": "X1",
            "evidence": "../escaped/evidence/owned.json",
            "recovery_claim": {
                "kind": "analysis",
                "promotion_level": "specified",
                "evidence_basis": ["wave"],
            },
        }
        manifests = {"evil": {"id": "evil", "waves": [malicious]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suites"
            with (
                patch("portfolio_suites.waves.SUITES_ROOT", root),
                patch("portfolio_suites.waves.load_suites", return_value=manifests),
            ):
                result = _record_evidence(
                    malicious,
                    {"wave": "X1"},
                    write_evidence=True,
                    passed=True,
                )
            self.assertIsNone(result)
            self.assertFalse((Path(tmp) / "escaped" / "evidence" / "owned.json").exists())
            self.assertFalse(root.exists(), "a rejected path must not create directories")

    def test_rejected_candidate_has_machine_readable_status(self):
        with patch("portfolio_suites.waves._record_evidence", return_value=None):
            result = WaveRunner.run_wave(
                "model-behavior-lab",
                "M1",
                write_evidence=True,
            )
        self.assertTrue(result.passed)
        self.assertEqual(result.record_status, "candidate_rejected")
        self.assertIn("failed validation", result.record_note)

    def test_cli_record_rejection_is_not_a_success_exit(self):
        rejected = WaveRunResult(
            "model-behavior-lab",
            "M1",
            True,
            "gate passed",
            execution_kind="verified_analysis",
            record_note="candidate receipt failed validation; prior receipt retained",
            record_status="candidate_rejected",
        )
        with patch("portfolio_suites.waves.WaveRunner.run_wave", return_value=rejected):
            with redirect_stdout(io.StringIO()):
                code = main(["wave", "model-behavior-lab", "M1", "--record"])
        self.assertEqual(code, EXIT_FAILED)

    def test_post_commit_failure_is_not_reported_as_candidate_rejection(self):
        wave = {
            "id": "X1",
            "evidence": "example/evidence/X1.json",
            "recovery_claim": {
                "kind": "analysis",
                "level": "prototype",
                "evidence_basis": ["wave"],
            },
        }
        manifests = {"example": {"id": "example", "waves": [wave]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suites"
            evidence_dir = root / "example" / "evidence"
            evidence_dir.mkdir(parents=True)
            retained = evidence_dir / "X1.json"
            retained.write_text("old", encoding="utf-8")
            real_fsync = __import__("os").fsync

            def fail_directory_fsync(fd):
                # Directories only: payload fsyncs happen before the commit point.
                if os.fstat(fd).st_mode & 0o170000 == 0o040000:
                    raise OSError("forced post-commit fsync failure")
                return real_fsync(fd)

            with (
                patch("portfolio_suites.waves.SUITES_ROOT", root),
                patch("portfolio_suites.waves.load_suites", return_value=manifests),
                patch("portfolio_suites.waves.evidence_errors", return_value=[]),
                patch("os.fsync", side_effect=fail_directory_fsync),
            ):
                outcome = _record_evidence(wave, "new", write_evidence=True, passed=True)

            self.assertIsInstance(outcome, EvidenceCommitUnverified)
            self.assertIn("replacement committed", outcome.note)
            self.assertEqual(retained.read_text(encoding="utf-8"), "new")

    def test_bytes_substituted_after_validation_are_never_committed(self):
        """The validate-by-pathname hole: a candidate altered between `evidence_errors` and
        the replacement used to be installed verbatim while the recorder reported success.
        The commit now re-derives the validated digest from the descriptor-pinned object
        and refuses on any mismatch."""
        wave = {
            "id": "X1",
            "evidence": "example/evidence/X1.json",
            "recovery_claim": {
                "kind": "analysis",
                "level": "prototype",
                "evidence_basis": ["wave"],
            },
        }
        manifests = {"example": {"id": "example", "waves": [wave]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suites"
            evidence_dir = root / "example" / "evidence"
            evidence_dir.mkdir(parents=True)
            retained = evidence_dir / "X1.json"
            retained.write_text("old", encoding="utf-8")

            def validate_then_tamper(wave_arg, candidate, suite_id=None):
                # Simulates a concurrent same-user process swapping the candidate's bytes
                # after (or while) validation ran, before the commit happened.
                parent_fd = os.open(evidence_dir, os.O_RDONLY)
                try:
                    handle = os.open(candidate.name, os.O_WRONLY, dir_fd=parent_fd)
                    try:
                        os.ftruncate(handle, 0)
                        os.write(handle, b'{"tampered_after_validation": true}')
                        os.fsync(handle)
                    finally:
                        os.close(handle)
                finally:
                    os.close(parent_fd)
                return []

            with (
                patch("portfolio_suites.waves.SUITES_ROOT", root),
                patch("portfolio_suites.waves.load_suites", return_value=manifests),
                patch("portfolio_suites.waves.evidence_errors", side_effect=validate_then_tamper),
            ):
                outcome = _record_evidence(wave, "honest", write_evidence=True, passed=True)

            self.assertIsNone(
                outcome, "a candidate whose bytes changed after validation was committed"
            )
            self.assertEqual(retained.read_text(encoding="utf-8"), "old")
            leftovers = [
                p.name for p in evidence_dir.iterdir()
                if p.name != "X1.json" and not p.name.startswith(".")
            ]
            self.assertEqual(leftovers, [], leftovers)

    def test_a_retained_receipt_edited_during_recording_is_preserved(self):
        """A concurrent writer touching the retained receipt while ours validates must win:
        the compare-and-swap expectation is the prior bytes' digest, so even an in-place
        truncate-and-rewrite (which keeps the inode) refuses the commit instead of being
        silently replaced."""
        wave = {
            "id": "X1",
            "evidence": "example/evidence/X1.json",
            "recovery_claim": {
                "kind": "analysis",
                "level": "prototype",
                "evidence_basis": ["wave"],
            },
        }
        manifests = {"example": {"id": "example", "waves": [wave]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suites"
            evidence_dir = root / "example" / "evidence"
            evidence_dir.mkdir(parents=True)
            retained = evidence_dir / "X1.json"
            retained.write_text("old", encoding="utf-8")

            def validate_then_concurrent_edit(wave_arg, candidate, suite_id=None):
                parent_fd = os.open(evidence_dir, os.O_RDONLY)
                try:
                    handle = os.open(
                        "X1.json", os.O_WRONLY | os.O_TRUNC, dir_fd=parent_fd
                    )
                    try:
                        os.write(handle, b"theirs")
                        os.fsync(handle)
                    finally:
                        os.close(handle)
                finally:
                    os.close(parent_fd)
                return []

            with (
                patch("portfolio_suites.waves.SUITES_ROOT", root),
                patch("portfolio_suites.waves.load_suites", return_value=manifests),
                patch(
                    "portfolio_suites.waves.evidence_errors",
                    side_effect=validate_then_concurrent_edit,
                ),
            ):
                outcome = _record_evidence(wave, "mine", write_evidence=True, passed=True)

            self.assertIsNone(outcome, "our recording replaced a concurrently edited receipt")
            self.assertEqual(
                retained.read_text(encoding="utf-8"),
                "theirs",
                "the concurrent edit was lost",
            )

    def test_committed_unverified_status_reaches_wave_result(self):
        uncertain = EvidenceCommitUnverified(
            "model-behavior-lab/evidence/M1.json",
            "receipt replacement committed; current receipt state must be inspected",
        )
        with patch("portfolio_suites.waves._record_evidence", return_value=uncertain):
            result = WaveRunner.run_wave(
                "model-behavior-lab",
                "M1",
                write_evidence=True,
            )
        self.assertTrue(result.passed)
        self.assertEqual(result.record_status, "committed_unverified")
        self.assertIsNone(result.evidence_path)
        self.assertIn("must be inspected", result.record_note)

    def test_cli_never_claims_prior_receipt_survived_an_unverified_commit(self):
        uncertain = WaveRunResult(
            "model-behavior-lab",
            "M1",
            True,
            "gate passed",
            execution_kind="verified_analysis",
            claim_kind="analysis",
            claim_level="prototype",
            record_note="receipt replacement committed; current receipt state must be inspected",
            record_status="committed_unverified",
        )
        output = io.StringIO()
        with patch("portfolio_suites.waves.WaveRunner.run_wave", return_value=uncertain):
            with redirect_stdout(output):
                code = main(["wave", "model-behavior-lab", "M1", "--record"])
        self.assertEqual(code, EXIT_INCOMPLETE)
        self.assertIn("Evidence commit UNVERIFIED", output.getvalue())
        self.assertIn("Do not assume the prior receipt was retained", output.getvalue())
        self.assertNotIn("Prior receipt retained.", output.getvalue())

    def test_read_only_record_request_is_explicitly_incomplete(self):
        with redirect_stdout(io.StringIO()):
            code = main(["wave", "accessibility", "A1", "--record"])
        self.assertEqual(code, EXIT_INCOMPLETE)

    def test_gate_failure_note_and_status_use_the_same_precedence(self):
        manifest = {
            "id": "fake-suite",
            "waves": [{"id": "X1", "status": "specified"}],
        }
        failed = WaveRunResult("fake-suite", "X1", False, "gate failed")
        runner = staticmethod(lambda suite, wave_id, write_evidence: failed)

        with patch.object(WaveRunner, "_run_fake_suite_x1", runner, create=True):
            result = WaveRunner._run_loaded_wave(
                manifest,
                "X1",
                write_evidence=True,
                full=False,
            )

        self.assertEqual(result.record_status, "gate_failed")
        self.assertEqual(result.record_note, "gate did not pass, so no receipt was offered")

    def test_analysis_tags_preserve_promotion_depth(self):
        self.assertEqual(
            format_wave_tag(
                "verified_analysis",
                True,
                claim_level="reviewed_historical_analysis",
            ),
            "[HISTORICAL]",
        )
        self.assertEqual(
            format_wave_tag("verified_analysis", True, claim_level="source_inspected"),
            "[INSPECTED]",
        )

    def test_symlinked_evidence_directory_is_refused(self):
        wave = {
            "id": "P1",
            "evidence": "production-house/evidence/P1-RECEIPT.json",
            "recovery_claim": {
                "kind": "analysis",
                "promotion_level": "specified",
                "evidence_basis": ["wave"],
            },
        }
        manifests = {"production-house": {"id": "production-house", "waves": [wave]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suites"
            root.mkdir()
            target_evidence = root / "operator-os" / "evidence"
            target_evidence.mkdir(parents=True)
            prod_dir = root / "production-house"
            prod_dir.mkdir()
            (prod_dir / "evidence").symlink_to(target_evidence)

            with (
                patch("portfolio_suites.waves.SUITES_ROOT", root),
                patch("portfolio_suites.waves.load_suites", return_value=manifests),
            ):
                result = _record_evidence(
                    wave,
                    {"wave": "P1"},
                    write_evidence=True,
                    passed=True,
                )
            self.assertIsNone(result)
            self.assertEqual(list(target_evidence.iterdir()), [], "symlink target must not receive evidence")


if __name__ == "__main__":
    unittest.main()
