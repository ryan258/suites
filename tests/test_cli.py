import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

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
        self.assertIn("1 runtime recovery, 10 analysis, 0 adopted, 0 converged", output)

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
        self.assertIn("[ANALYSIS]", output)

    def test_wave_run_no_record(self):
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "brand-publishing", "B1", "--no-record"])
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("[PROTOTYPE]", output)

    def test_wave_run_is_ephemeral_by_default(self):
        evidence = Path("accessibility/evidence/A2-WCAG-331-EVIDENCE.json")
        before = evidence.read_bytes()
        f = io.StringIO()
        with redirect_stdout(f):
            code = main(["wave", "accessibility", "A2"])
        self.assertIn(code, {0, 1})
        self.assertEqual(evidence.read_bytes(), before)
        self.assertNotIn("Evidence recorded at", f.getvalue())
        if code == 1:
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
        self.assertIn(code, {0, 1})
        self.assertIn("10 verified analyses", output)
        self.assertIn("32 prototype checks passed", output)
        if code == 0:
            self.assertIn("1 runtime recoveries", output)
        else:
            self.assertIn("1 environment-unverifiable", output)


if __name__ == "__main__":
    unittest.main()
