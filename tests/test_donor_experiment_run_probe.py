"""Authentic producer -> separately executed consumer proof for ExperimentRun (contract freeze).

Producer: a donor-side probe subprocess using ai-ethics-comparator's own stats on a retained real run.
Consumer: the control plane's CLI in a second process. Skips when the donor checkout is absent.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.adapters.common import donor_env, get_repo_path
from portfolio_suites.adapters import donor_ethics_experiment_probe as probe_module
from portfolio_suites.paths import SUITES_ROOT

PROBE = Path(probe_module.__file__)


class EthicsExperimentRunProofTests(unittest.TestCase):
    def test_donor_producer_output_passes_independent_consumer(self):
        repo = get_repo_path("ai-ethics-comparator", "AI_ETHICS_COMPARATOR_PATH")
        results = sorted((repo / "results").glob("*.json")) if repo.is_dir() else []
        if not results:
            self.skipTest("ai-ethics-comparator checkout with retained results is not available")
        produced = subprocess.run(
            [sys.executable, str(PROBE), str(repo), str(results[0])],
            env=donor_env(), capture_output=True, text=True, timeout=60,
        )
        if produced.returncode == probe_module.EXIT_IMPORT_FAILED:
            self.skipTest("donor stats not loadable here (environment blocked)")
        self.assertEqual(produced.returncode, 0, produced.stderr)
        out = json.loads(produced.stdout.strip().splitlines()[-1])
        # Donor self-attestation is not accepted: the parent recomputes both digests.
        self.assertEqual(out["source_sha256"], hashlib.sha256(results[0].read_bytes()).hexdigest())
        self.assertEqual(out["stats_sha256"], hashlib.sha256((repo / "lib" / "stats.py").read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "run.json"
            artifact.write_text(json.dumps(out["experiment_run"]), encoding="utf-8")
            consumed = subprocess.run(
                [sys.executable, "-m", "portfolio_suites", "contract", "ExperimentRun", "validate", str(artifact)],
                env={"PYTHONPATH": str(SUITES_ROOT / "src"), "SUITES_ROOT": str(SUITES_ROOT), "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(consumed.returncode, 0, consumed.stdout + consumed.stderr)


if __name__ == "__main__":
    unittest.main()
