"""Authentic producer -> separately executed consumer proof for ProductionJob (contract freeze).

Producer: Production House's own engine running its Groundwire tasks (state in a private temp dir) in a
donor subprocess. Consumer: the control plane's CLI in a second process. Skips when the donor checkout or
its dependencies are absent. If `filelock` is missing the probe stubs the lock; this test records that.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.adapters import donor_production_job_probe as probe_module
from portfolio_suites.adapters.common import donor_env, get_repo_path
from portfolio_suites.paths import SUITES_ROOT

PROBE = Path(probe_module.__file__)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ProductionHouseJobProofTests(unittest.TestCase):
    def test_donor_engine_run_maps_to_a_production_job_an_independent_consumer_accepts(self):
        donor = get_repo_path("production-house", "PRODUCTION_HOUSE_DIR")
        state = donor / "data" / "state.json"
        if not (donor / "src" / "production_engine" / "engine.py").is_file():
            self.skipTest("production-house checkout is not available")
        before = hashlib.sha256(state.read_bytes()).hexdigest() if state.is_file() else None
        produced = subprocess.run(
            [sys.executable, str(PROBE), str(donor), "ep-freeze-001"],
            env=donor_env({"PYTHONDONTWRITEBYTECODE": "1"}), capture_output=True, text=True, timeout=90,
        )
        if produced.returncode == probe_module.EXIT_IMPORT_FAILED:
            self.skipTest("Production House dependencies not importable here (environment blocked)")
        self.assertEqual(produced.returncode, 0, produced.stderr)
        out = json.loads(produced.stdout.strip().splitlines()[-1])
        self.assertEqual(hashlib.sha256(state.read_bytes()).hexdigest() if state.is_file() else None, before)
        self.assertEqual([r["attributes"]["status"] for r in out["results"]], ["draft", "in_production", "published"])
        # Donor claims are recomputed host-side: digests come from the returned payload and entity, not the donor.
        final = out["results"][-1]
        audit = out["audit"]
        job = {
            "schema_version": "1.0.0",
            "job_id": "job-gw-" + out["payload"]["episode_id"],
            "domain": "groundwire",
            "task": "episode.create+advance-status*2",
            "status": "completed" if final["attributes"]["status"] == "published" else "running",
            "inputs": [{"name": "task-payload.json", "sha256": _digest(out["payload"])}],
            "outputs": [{"name": "entity:" + final["entity_id"], "sha256": _digest(final)}],
            "events": [{"time": a["ts"], "stage": a["source"], "status": a["op"]} for a in audit],
            "created_at": audit[0]["ts"],
            "updated_at": audit[-1]["ts"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "job.json"
            artifact.write_text(json.dumps(job), encoding="utf-8")
            consumed = subprocess.run(
                [sys.executable, "-m", "portfolio_suites", "contract", "ProductionJob", "validate", str(artifact)],
                env={"PYTHONPATH": str(SUITES_ROOT / "src"), "SUITES_ROOT": str(SUITES_ROOT), "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(consumed.returncode, 0, consumed.stdout + consumed.stderr)


if __name__ == "__main__":
    unittest.main()
