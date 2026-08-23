"""How the control plane finds its checkout, and what it says when it cannot.

`suites` is checkout-oriented: suite manifests, contract schemas, the portfolio ledger and
retained evidence are working state, not packaged data. An installed run therefore needs
SUITES_ROOT, and the failure when it is absent has to name that rather than surface as a
confusing ENOENT under site-packages.

Scope: these run against the source tree. They prove root *resolution*, not packaging --
a wheel that shipped no web assets would leave them green. The build-and-install gate is
`test_wheel_smoke.py`, which is opt-in because building a wheel is a Level 4 cost that
does not belong in every `unittest discover` run.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(code, cwd, env_root=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    if env_root is not None:
        env["SUITES_ROOT"] = str(env_root)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd, env={**env, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=60,
    )


class InstalledRootTests(unittest.TestCase):
    def test_a_root_without_the_ledger_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as empty:
            result = _run("import portfolio_suites.paths", cwd=empty, env_root=empty)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SUITES_ROOT", result.stderr)
        self.assertIn("project-ledger.json", result.stderr)

    def test_an_explicit_valid_root_resolves(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            result = _run(
                "from portfolio_suites.paths import SUITES_ROOT; print(SUITES_ROOT)",
                cwd=elsewhere, env_root=ROOT,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(ROOT.resolve()))

    def test_the_console_entry_point_is_declared(self):
        """Declaration only -- that it *works* installed is test_wheel_smoke.py's job."""
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('suites = "portfolio_suites.entrypoint:main"', pyproject)

    def test_console_boundary_names_a_missing_root_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as empty:
            result = _run(
                "from portfolio_suites.entrypoint import main; raise SystemExit(main(['validate', '--fast']))",
                cwd=empty,
                env_root=empty,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("SUITES_ROOT", result.stderr)
        self.assertIn("project-ledger.json", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
