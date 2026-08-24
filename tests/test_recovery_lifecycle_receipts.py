import json
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.registry import evidence_errors
from portfolio_suites.waves import classify_wave_spec


def fingerprint(seed: str):
    return {
        "branch": "main",
        "head": seed * 40,
        "tested_files_fingerprint": {"src/runtime.py": seed * 64},
    }


def write_receipt(root: str, payload: dict) -> Path:
    path = Path(root) / "receipt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RecoveryLifecycleReceiptTests(unittest.TestCase):
    def test_source_executed_runtime_has_a_real_receipt_contract(self):
        wave = {
            "id": "X1",
            "recovery_claim": {
                "kind": "runtime",
                "level": "source_executed",
                "receipt_contract": "portfolio-runtime-source-v1",
            },
        }
        payload = {
            "receipt_version": "portfolio-runtime-source-v1",
            "status": "source_executed",
            "all_stages_passed": True,
            "operational_errors": [],
            "source_invocation": {"command": ["tool", "verify"], "exit_code": 0},
            "source_fingerprints": {"donor": fingerprint("a")},
            "reproducible_commands": [["tool", "verify"]],
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(evidence_errors(wave, write_receipt(tmp, payload)), [])

    def test_adoption_requires_three_distinct_accepted_uses_bound_to_parity(self):
        wave = {
            "id": "X2",
            "recovery_claim": {
                "kind": "adoption",
                "level": "adopted",
                "receipt_contract": "portfolio-adoption-v1",
            },
        }
        payload = {
            "receipt_version": "portfolio-adoption-v1",
            "status": "adopted",
            "operational_errors": [],
            "parity_receipt_sha256": "f" * 64,
            "accepted_uses": [
                {
                    "use_id": f"use-{index}",
                    "input_sha256": str(index) * 64,
                    "accepted": True,
                    "evidence_ref": f"runs/use-{index}.json",
                    "occurred_at": f"2026-08-2{index}T12:00:00+00:00",
                }
                for index in range(1, 4)
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(evidence_errors(wave, write_receipt(tmp, payload)), [])
            payload["accepted_uses"][2]["input_sha256"] = payload["accepted_uses"][1]["input_sha256"]
            self.assertTrue(evidence_errors(wave, write_receipt(tmp, payload)))

    def test_convergence_requires_owner_authority_and_adoption_binding(self):
        wave = {
            "id": "X3",
            "recovery_claim": {
                "kind": "convergence",
                "level": "converged",
                "receipt_contract": "portfolio-convergence-v1",
            },
        }
        payload = {
            "receipt_version": "portfolio-convergence-v1",
            "status": "converged",
            "operational_errors": [],
            "canonical_runtime": "suite-runtime",
            "duplicate_writers": [{"runtime": "old-runtime", "disposition": "read_only"}],
            "owner_approval": {
                "approved": True,
                "approved_by": "Ryan",
                "authority_record_sha256": "a" * 64,
            },
            "adoption_receipt_sha256": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(evidence_errors(wave, write_receipt(tmp, payload)), [])

    def test_resolution_supports_explicit_deferred_trigger(self):
        wave = {
            "id": "X4",
            "recovery_claim": {
                "kind": "resolution",
                "level": "source_executed",
                "outcome": "deferred_with_trigger",
                "receipt_contract": "portfolio-resolution-v1",
            },
        }
        payload = {
            "receipt_version": "portfolio-resolution-v1",
            "status": "resolved",
            "outcome": "deferred_with_trigger",
            "operational_errors": [],
            "capability_id": "cap-authored-game",
            "rationale": "Keep independent until two consumers need the engine boundary.",
            "source_fingerprints": {"donor": fingerprint("c")},
            "resume_trigger": {"condition": "A second real consumer requests this capability."},
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(evidence_errors(wave, write_receipt(tmp, payload)), [])

    def test_classification_keeps_lifecycle_states_distinct(self):
        cases = {
            ("runtime", "source_executed"): "verified_source_execution",
            ("runtime", "parity_verified"): "verified_runtime_recovery",
            ("adoption", "adopted"): "verified_adoption",
            ("convergence", "converged"): "verified_convergence",
            ("resolution", "source_executed"): "verified_resolution",
        }
        for (kind, level), expected in cases.items():
            with self.subTest(kind=kind, level=level):
                self.assertEqual(
                    classify_wave_spec({
                        "status": "complete",
                        "recovery_claim": {"kind": kind, "level": level},
                    }),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
