"""Authentic producer -> separately executed consumer proof for SourceRecord (contract freeze).

Producer: the existing PKos CAS probe subprocess acquires a real file into PKos's content-addressed store.
Consumer: the control plane's CLI in a second process. Skips when the PKos checkout is absent.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.adapters import donor_pkos_cas_probe as probe_module
from portfolio_suites.adapters.common import donor_env, get_repo_path
from portfolio_suites.paths import SUITES_ROOT

PROBE = Path(probe_module.__file__)


class PkosSourceRecordProofTests(unittest.TestCase):
    def test_pkos_acquisition_maps_to_a_source_record_an_independent_consumer_accepts(self):
        pkos = get_repo_path("PKos", "PKOS_DIR")
        if not (pkos / "pkos" / "storage.py").is_file():
            self.skipTest("PKos checkout is not available")
        source = SUITES_ROOT / "docs" / "GLOSSARY.md"
        produced = subprocess.run(
            [sys.executable, str(PROBE), str(source), "freeze/glossary"],
            cwd=pkos, env=donor_env({"PYTHONPATH": str(pkos), "PYTHONDONTWRITEBYTECODE": "1"}),
            capture_output=True, text=True, timeout=60,
        )
        if produced.returncode == probe_module.EXIT_IMPORT_FAILED:
            self.skipTest("PKos dependencies not importable here (environment blocked)")
        self.assertEqual(produced.returncode, 0, produced.stderr)
        payload = json.loads(produced.stdout.strip().splitlines()[-1])
        acquired = payload["acquired_record"]
        # Donor self-attestation is not accepted: the parent recomputes digest and size from the file.
        data = source.read_bytes()
        self.assertEqual(acquired["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(acquired["bytes"], len(data))
        self.assertTrue(payload["raw_bytes_match"])
        record = {
            "schema_version": "1.0.0",
            "source_id": "src-pkos-" + acquired["sha256"][:12],
            "acquired_at": acquired["acquired_at"],
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "media_type": acquired["media_type"],
            "origin": "pkos://" + acquired["label"],
            "provenance": {
                "collector": "pkos.storage.Workspace",
                "intake_method": "acquire_file",
                "donor_record_id": acquired["id"],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "source.json"
            artifact.write_text(json.dumps(record), encoding="utf-8")
            consumed = subprocess.run(
                [sys.executable, "-m", "portfolio_suites", "contract", "SourceRecord", "validate", str(artifact)],
                env={"PYTHONPATH": str(SUITES_ROOT / "src"), "SUITES_ROOT": str(SUITES_ROOT), "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(consumed.returncode, 0, consumed.stdout + consumed.stderr)


if __name__ == "__main__":
    unittest.main()
