"""Authentic producer -> separately executed consumer proof for InvestigationRecord (contract freeze).

Producer: Forge (breaking-chains) loading a retained real, model-driven investigation through its own
persistence and domain validation, in a donor subprocess. Consumer: the control plane's CLI in a second
process. Skips when the donor checkout or its dependencies are absent.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.adapters import donor_forge_investigation_probe as probe_module
from portfolio_suites.adapters.common import donor_env, get_repo_path
from portfolio_suites.paths import SUITES_ROOT

PROBE = Path(probe_module.__file__)


class ForgeInvestigationRecordProofTests(unittest.TestCase):
    def test_forge_investigation_maps_to_a_record_an_independent_consumer_accepts(self):
        forge = get_repo_path("breaking-chains", "BREAKING_CHAINS_DIR")
        database = forge / "data" / "forge.sqlite3"
        if not database.is_file():
            self.skipTest("breaking-chains checkout with a retained Forge database is not available")
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        produced = subprocess.run(
            [sys.executable, str(PROBE), str(forge)],
            env=donor_env({"PYTHONDONTWRITEBYTECODE": "1"}), capture_output=True, text=True, timeout=90,
        )
        if produced.returncode == probe_module.EXIT_IMPORT_FAILED:
            self.skipTest("Forge dependencies not importable here (environment blocked)")
        self.assertEqual(produced.returncode, 0, produced.stderr)
        out = json.loads(produced.stdout.strip().splitlines()[-1])
        # Donor self-attestation is not accepted, and the donor database must be untouched.
        self.assertEqual(out["database_sha256"], before)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        forge_record = out["record"]
        receipts = forge_record["model_receipts"]
        workflow = forge_record["workflow"]
        record = {
            "schema_version": "1.0.0",
            "investigation_id": forge_record["id"],
            "question": forge_record["seed"],
            "mode": workflow["depth"],
            "status": "completed" if workflow["stage"] == "completed" else "running",
            "premises": [
                {"id": item["id"], "text": item["statement"]}
                for item in forge_record["epistemic_items"] if item["category"] == "premise"
            ],
            "evidence": [
                {"id": item["id"], "source": item.get("origin") or "forge", "finding": item["statement"]}
                for item in forge_record["epistemic_items"] if item["category"] == "evidence"
            ],
            "stages": [{"stage": event["to_stage"], "status": event["kind"]} for event in workflow["history"]],
            "decisions": [
                {"prompt_id": decision["prompt"]["id"], "kind": decision["prompt"]["kind"]}
                for decision in forge_record["decisions"]
            ],
            "budget": {
                "model_calls_used": len(receipts),
                "total_tokens": sum(r["usage"].get("total_tokens") or 0 for r in receipts),
                "used_time_sec": round(sum(r["duration_ms"] for r in receipts) / 1000.0, 3),
            },
            "created_at": workflow["created_at"],
            "updated_at": workflow["updated_at"],
        }
        self.assertTrue(record["premises"] and record["stages"] and record["decisions"])
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "investigation.json"
            artifact.write_text(json.dumps(record), encoding="utf-8")
            consumed = subprocess.run(
                [sys.executable, "-m", "portfolio_suites", "contract", "InvestigationRecord", "validate", str(artifact)],
                env={"PYTHONPATH": str(SUITES_ROOT / "src"), "SUITES_ROOT": str(SUITES_ROOT), "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(consumed.returncode, 0, consumed.stdout + consumed.stderr)


if __name__ == "__main__":
    unittest.main()
