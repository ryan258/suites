import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.cli import EXIT_FAILED, EXIT_INCOMPLETE, main
from portfolio_suites.waves import WaveRunResult, WaveRunner, _record_evidence


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


if __name__ == "__main__":
    unittest.main()
