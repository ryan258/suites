import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.cli import main


class CLITests(unittest.TestCase):
    def test_list_command(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["list"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("accessibility", output)
        self.assertIn("operator-os", output)

    def test_status_command(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["status"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("Portfolio snapshot", output)
        self.assertIn("Top-level directories reviewed: 70", output)
        self.assertIn("Recovery standard: 9.0/10 target", output)
        # Both axes, and specifically the prototype count: the milestone line alone reads
        # as a recovered portfolio, which is the reporting defect this asserts against.
        self.assertIn("Wave milestone progress: 43/43", output)
        self.assertIn("Completed analysis milestones: 42", output)
        self.assertIn(
            "Evidence promotion: 4 prototype, 1 reviewed historical, 37 source inspected, "
            "0 source executed, 1 parity verified, 0 adopted, 0 converged, 0 resolved",
            output,
        )

    def test_next_command(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["next"])
        self.assertEqual(code, 0)

    def test_drift_command(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["drift"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("Live Drift Report", output)

    def test_export_command(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["export"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("summary", output)
        self.assertIn("suites", output)

    def test_inspect_suite(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["inspect", "accessibility"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("SUITE: Ally Accessibility Suite", output)

    def test_inspect_project(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["inspect", "dotfiles"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("PROJECT: dotfiles", output)

    def test_contract_sample(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["contract", "A11yFinding", "sample"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("wcag-3.3.1-error-identification", output)

    def test_contract_spec(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["contract", "BrandPackage", "spec"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("Contract: BrandPackage", output)

    def test_wave_run(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "accessibility", "A1", "--no-record"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("[HISTORICAL]", output)
        self.assertIn("claim=reviewed_historical_analysis", output)

    def test_wave_run_no_record(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "accessibility", "A5", "--no-record"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("[PROTOTYPE]", output)
        self.assertIn("claim=prototype", output)

    def test_wave_run_is_ephemeral_by_default(self):
        evidence = Path("accessibility/evidence/A2-WCAG-331-EVIDENCE.json")
        before = evidence.read_bytes()
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "accessibility", "A2"])
        # A2 drives a donor runtime, so a machine without it is incomplete (2), not failed (1).
        self.assertIn(code, {0, 2})
        self.assertEqual(evidence.read_bytes(), before)
        self.assertNotIn("Evidence recorded at", f.getvalue())
        if code == 2:
            self.assertIn("[UNVERIFIABLE]", f.getvalue())

    def test_wave_unknown_fails_closed(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "missing-suite", "X1", "--no-record"])
        self.assertEqual(code, 1)
        self.assertIn("[ERROR]", f.getvalue())

    def test_wave_all_reports_consistent_classifications(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "--all", "--no-record"])
        output = f.getvalue()
        self.assertIn(code, {0, 2})
        self.assertIn("38 verified analyses", output)
        self.assertIn("4 prototype checks passed", output)
        self.assertIn("0 runtime recoveries", output)
        if code == 0:
            self.assertIn("1 fast probes", output)
        else:
            self.assertIn("[UNVERIFIABLE]", output)
            self.assertIn("1 environment-unverifiable", output)

    def test_drift_command_surfaces_incomplete_untracked_fingerprint(self):
        incomplete = {
            "name": "donor",
            "has_drift": True,
            "snapshot_branch": "main",
            "snapshot_head": "abc123",
            "current_branch": "main",
            "current_head": "abc123",
            "current_lines": 0,
            "untracked_incomplete": True,
            "untracked_incomplete_reasons": ["untracked_path_enumeration_failed"],
            "status_unfingerprinted": False,
            "patch_unfingerprinted": False,
        }
        output = io.StringIO()
        with patch("portfolio_suites.cli.get_live_drift_report", return_value=[incomplete]):
            with redirect_stdout(output):
                code = main(["drift"])
        self.assertEqual(code, 0)
        self.assertIn("UNRESOLVED", output.getvalue())
        self.assertIn("untracked_path_enumeration_failed", output.getvalue())


class WaveExitStatusTests(unittest.TestCase):
    """An unrun gate must not report the same shell status as a verified one."""

    @staticmethod
    def _failed_probe():
        from portfolio_suites.waves import WaveRunResult

        return WaveRunResult(
            "accessibility", "A2", False, "probe failed", execution_kind="fast_probe",
        )

    @staticmethod
    def _blocked():
        from portfolio_suites.waves import WaveRunResult

        return WaveRunResult(
            "accessibility", "A2", False, "donor runtime unavailable",
            execution_kind="unverifiable_environment", data={"environment_blocked": True},
        )

    def test_single_environment_blocked_wave_is_incomplete_not_success(self):
        from unittest.mock import patch

        from portfolio_suites.cli import EXIT_INCOMPLETE

        with patch("portfolio_suites.waves.WaveRunner.run_wave", return_value=self._blocked()):
            with redirect_stdout(io.StringIO()):
                code = main(["wave", "accessibility", "A2"])
        self.assertEqual(code, EXIT_INCOMPLETE)

    def test_all_waves_with_only_a_blocked_gate_is_incomplete_not_success(self):
        from unittest.mock import patch

        from portfolio_suites.cli import EXIT_INCOMPLETE

        with patch("portfolio_suites.waves.WaveRunner.run_all", return_value=[self._blocked()]):
            with redirect_stdout(io.StringIO()):
                code = main(["wave", "--all"])
        self.assertEqual(code, EXIT_INCOMPLETE)

    def test_a_failed_fast_probe_is_a_product_failure(self):
        """A fast probe that ran and came back failing prints [FAIL]; the exit code must agree."""
        from unittest.mock import patch

        from portfolio_suites.cli import EXIT_FAILED

        with patch("portfolio_suites.waves.WaveRunner.run_all", return_value=[self._failed_probe()]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["wave", "--all"])
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("[FAIL]", buf.getvalue())
        self.assertIn("1 checks failed", buf.getvalue())

    def test_a_failed_fast_probe_outranks_an_environment_blocker(self):
        from unittest.mock import patch

        from portfolio_suites.cli import EXIT_FAILED

        with patch(
            "portfolio_suites.waves.WaveRunner.run_all",
            return_value=[self._failed_probe(), self._blocked()],
        ):
            with redirect_stdout(io.StringIO()):
                code = main(["wave", "--all"])
        self.assertEqual(code, EXIT_FAILED)

    def test_a_product_failure_still_outranks_an_environment_blocker(self):
        from unittest.mock import patch

        from portfolio_suites.cli import EXIT_FAILED
        from portfolio_suites.waves import WaveRunResult

        failed = WaveRunResult(
            "accessibility", "A3", False, "gate failed", execution_kind="verified_analysis",
        )
        with patch("portfolio_suites.waves.WaveRunner.run_all", return_value=[self._blocked(), failed]):
            with redirect_stdout(io.StringIO()):
                code = main(["wave", "--all"])
        self.assertEqual(code, EXIT_FAILED)
