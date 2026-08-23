"""Build a wheel, install it, and drive the console script it generates.

This is the gate that catches a packaging regression: a missing `package-data` entry, a
dropped entry point, or a root-resolution change that only bites once the code is outside
the checkout. `test_source_root.py` cannot catch any of those -- it imports from `src/`.

Opt-in, because building and installing a wheel is a Level 4 cost under the repo's test
economy and has no business running on every `unittest discover`:

    SUITES_WHEEL_SMOKE=1 python3 -m unittest tests.test_wheel_smoke

The interpreter must satisfy the `requires-python` floor in pyproject.toml -- the gate
builds and installs a real wheel, and pip refuses to install one below its own floor.

Asking for the gate and not getting an answer is a failure, not a skip. Once
SUITES_WHEEL_SMOKE is set, a build or install that does not complete raises rather than
skipping: a skipped class still exits 0, which is exactly the false milestone evidence
this file exists to prevent. `unittest` has no third status, so an environment genuinely
unable to build (no network for build deps) reports failure with the captured output --
"could not verify" rather than "verified", which is the honest direction to round.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PACKAGE_DATA = (
    "portfolio_suites/web/index.html",
    "portfolio_suites/web/app.js",
    "portfolio_suites/web/styles.css",
    "portfolio_suites/adapters/donor_wcag_331_browser_probe.mjs",
)


def _clean_env(**extra):
    """Environment with PYTHONPATH stripped.

    The repo is driven as `PYTHONPATH=src python3 ...`, and that inherits straight into
    pip -- which then finds `src/ryan_project_suites.egg-info`, decides the distribution is
    already installed, and skips creating the console script. The install "succeeds" and
    the gate reports a packaging break that is really just leakage from the harness. This
    whole gate is about behaviour *outside* the checkout, so the checkout stays off the path.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(extra)
    return env


@unittest.skipUnless(
    os.environ.get("SUITES_WHEEL_SMOKE"), "set SUITES_WHEEL_SMOKE=1 to run the packaging gate"
)
class WheelSmokeTests(unittest.TestCase):
    """One build and install shared by every assertion; the cost is the reason this is opt-in."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="suites-wheel-smoke-")
        tmp = Path(cls._tmp)

        # The venv comes first and does the building. pip is itself a PEP 517 build
        # frontend, so the gate needs no `build` distribution installed anywhere -- the
        # previous `python -m build` step made an uninstalled helper a hard prerequisite,
        # and the gate had never run on a machine that lacked it.
        venv = tmp / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)], check=True, timeout=300, env=_clean_env()
        )
        cls.bin = venv / ("Scripts" if os.name == "nt" else "bin")

        build = subprocess.run(
            [str(cls.bin / "pip"), "wheel", "--no-deps", "--wheel-dir", str(tmp / "dist"), str(ROOT)],
            capture_output=True, text=True, timeout=600, env=_clean_env(),
            # Never run from ROOT: a stale ROOT/build/ artifact directory on sys.path has
            # shadowed real distributions here before. ROOT is passed as an argument.
            cwd=str(tmp),
        )
        # Not SkipTest. Once the operator asks for this gate, "could not build" is the gate
        # failing, not the gate being inapplicable -- a skip exits 0 and would let an
        # unbuildable wheel pass for milestone evidence. The outer skipUnless is the only
        # place where not running is a legitimate outcome.
        if build.returncode != 0:
            hint = (
                f"\nhint: this gate ran on {sys.executable} ({sys.version_info.major}."
                f"{sys.version_info.minor}), which is below the requires-python floor in "
                "pyproject.toml. Re-run it with a conforming interpreter; the wheel cannot "
                "install on this one."
                if "requires a different Python" in build.stdout + build.stderr
                else ""
            )
            raise AssertionError(
                f"wheel build failed:\n{build.stdout[-800:]}\n{build.stderr[-800:]}{hint}"
            )
        cls.wheel = next((tmp / "dist").glob("*.whl"))

        install = subprocess.run(
            [str(cls.bin / "pip"), "install", "--no-input", str(cls.wheel)],
            capture_output=True, text=True, timeout=600, env=_clean_env(),
        )
        if install.returncode != 0:
            raise AssertionError(f"wheel install failed:\n{install.stdout[-800:]}\n{install.stderr[-800:]}")
        if "already installed" in install.stdout:
            raise AssertionError(f"pip skipped the install instead of performing it:\n{install.stdout}")
        cls.suites = cls.bin / ("suites.exe" if os.name == "nt" else "suites")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _run(self, *args, root=None):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home())}
        if root is not None:
            env["SUITES_ROOT"] = str(root)
        # Deliberately not _clean_env(): this is the minimal environment an installed
        # command actually gets, and PYTHONPATH must not be what makes it work.
        return subprocess.run(
            [str(self.suites), *args], cwd=tempfile.gettempdir(), env=env,
            capture_output=True, text=True, timeout=300,
        )

    def test_the_wheel_carries_its_non_python_assets(self):
        names = set(zipfile.ZipFile(self.wheel).namelist())
        for required in REQUIRED_PACKAGE_DATA:
            with self.subTest(asset=required):
                self.assertIn(required, names)

    def test_the_console_script_is_installed(self):
        self.assertTrue(self.suites.exists(), f"{self.suites} was not created by the install")

    def test_without_a_root_it_names_what_to_set(self):
        result = self._run("validate", "--fast")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("SUITES_ROOT", combined)
        self.assertIn("project-ledger.json", combined)

    def test_with_a_valid_root_it_validates_from_outside_the_checkout(self):
        result = self._run("validate", "--fast", root=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VALID", result.stdout)


if __name__ == "__main__":
    unittest.main()
