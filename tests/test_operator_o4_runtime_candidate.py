import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.adapters.operator_os import (
    OperatorOSSourceAdapter,
    _runtime_source_candidate,
)
from portfolio_suites.execution_trace import validate_execution_trace
from portfolio_suites.receipts import evidence_errors
from portfolio_suites.recovery_program import (
    RecoveryProgramError,
    load_recovery_program,
)
from portfolio_suites.waves import WaveRunner


class OperatorO4RuntimeCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = OperatorOSSourceAdapter.execute_o4_pkos_stream_intake()

    def test_gate_proves_source_execution_and_names_the_owner_gate(self):
        self.assertEqual(self.result["status"], "stream_intake_verified")
        self.assertTrue(self.result["all_stages_passed"])
        candidate = self.result["runtime_candidate"]
        self.assertFalse(candidate["candidate_only"])
        self.assertTrue(candidate["promotion_eligible"])
        self.assertEqual(candidate["status"], "source_executed")
        # The vault write is O4's own owner gate; it bounds adoption, not the source rung.
        self.assertEqual(candidate["blocked_owner_gate"], "permanent_vault_write")
        self.assertIn(
            "permanent_vault_write_not_authorized_or_attempted",
            candidate["adoption_ceiling"],
        )

    def test_gate_verifies_donor_module_digests_host_side(self):
        receipt = self.result["runtime_candidate"]["receipt_contract_candidate"]
        modules = receipt["module_fingerprints"]
        self.assertEqual(
            set(modules), {"pkos.storage", "pkos.normalize"}
        )
        for name, record in modules.items():
            with self.subTest(module=name):
                self.assertTrue(record["agrees"])
                self.assertEqual(
                    record["host_recomputed_sha256"], record["donor_attested_sha256"]
                )
                self.assertFalse(record["path"].startswith("/"))
        tools = receipt["tool_dependencies"]
        self.assertTrue(tools["host_python"])
        self.assertTrue(tools["donor_python"])
        self.assertNotEqual(tools["donor_probe_sha256"], "")

    def test_candidate_retains_authentic_invocation_and_batch_metadata(self):
        receipt = self.result["runtime_candidate"]["receipt_contract_candidate"]
        invocation = receipt["source_invocation"]
        self.assertEqual(receipt["source_invocation_status"], "invoked")
        self.assertIsInstance(invocation["command"], list)
        self.assertGreaterEqual(len(invocation["command"]), 4)
        self.assertEqual(invocation["exit_code"], 0)
        self.assertGreaterEqual(invocation["duration_ms"], 0)
        self.assertTrue(receipt["all_stages_passed"])
        claims = receipt["host_recomputed_claims"]
        self.assertTrue(claims["cas_sha256_matches_source"])
        self.assertEqual(claims["batch_size"], 3)
        self.assertTrue(claims["all_fenced_from_reingestion"])
        self.assertTrue(claims["all_sources_cited"])
        self.assertFalse(receipt["recovery_behavior"]["permanent_vault_written"])
        self.assertTrue(receipt["recovery_behavior"]["rerun_safe"])
        self.assertEqual(receipt["operational_errors"], [])

    def test_candidate_receipt_satisfies_source_execution_contract(self):
        receipt = self.result["runtime_candidate"]["receipt_contract_candidate"]
        wave = {
            "status": "complete",
            "recovery_claim": {
                "kind": "runtime",
                "level": "source_executed",
                "receipt_contract": "portfolio-runtime-source-v1",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertEqual(evidence_errors(wave, path, "operator-os"), [])

    def test_execution_trace_is_redacted_and_governed(self):
        candidate = self.result["runtime_candidate"]
        trace = candidate["execution_trace"]
        self.assertEqual(candidate["execution_trace_errors"], [])
        self.assertEqual(
            validate_execution_trace(trace, load_recovery_program()),
            [],
        )
        self.assertEqual(trace["obligation_id"], "operator-os/O4")
        rendered = json.dumps(trace).lower()
        self.assertNotIn("raw_input", rendered)
        self.assertNotIn("source_content", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertIsNone(trace["receipt_ref"])

    def test_gate_propagates_trace_validation_failure(self):
        with patch(
            "portfolio_suites.adapters.operator_os.validate_execution_trace",
            return_value=["journey drift"],
        ):
            result = OperatorOSSourceAdapter.execute_o4_pkos_stream_intake()
        self.assertFalse(result["all_stages_passed"])
        self.assertEqual(result["status"], "source_unverified")
        self.assertEqual(
            result["operational_errors"][-1]["error_kind"],
            "invalid_execution_trace",
        )
        self.assertFalse(result["runtime_candidate"]["all_stages_passed"])


class OperatorO4RuntimeCandidateBoundaryTests(unittest.TestCase):
    def _candidate(self, **overrides):
        fingerprint = {
            "branch": "main",
            "head": "1" * 40,
            "tested_files_fingerprint": {"fixture.txt": "a" * 64},
        }
        arguments = {
            "started_at": "2026-08-26T20:00:00+00:00",
            "finished_at": "2026-08-26T20:00:01+00:00",
            "command": ["python", "donor_probe.py", "pkos/README.md"],
            "invocation_attempted": True,
            "exit_code": 0,
            "duration_ms": 1.0,
            "module_fingerprints": {
                "pkos.storage": {
                    "path": "pkos/storage.py",
                    "donor_attested_sha256": "d" * 64,
                    "host_recomputed_sha256": "d" * 64,
                    "agrees": True,
                }
            },
            "donor_interpreter": {"python": "3.13.1", "implementation": "CPython"},
            "all_stages_passed": True,
            "source_record": {"sha256": "b" * 64},
            "cas_acquisition": {"sha256": "b" * 64},
            "normalize_counts": {"items": 1, "chunks": 1},
            "operational_errors": [],
            "action": "execute_o4_pkos_stream_intake",
            "source_fingerprints": {"pkos": fingerprint},
            "dependency_fingerprints": {
                "dotfiles": fingerprint,
                "obsidian-observer": fingerprint,
            },
            "trace_fingerprints": {
                "dotfiles": fingerprint,
                "PKos": fingerprint,
                "obsidian-observer": fingerprint,
            },
            "extra_host_claims": {"batch_size": 3, "all_sources_cited": True},
        }
        arguments.update(overrides)
        return _runtime_source_candidate(**arguments)

    def test_trace_validation_error_invalidates_candidate_and_receipt(self):
        with patch(
            "portfolio_suites.adapters.operator_os.validate_execution_trace",
            return_value=["journey drift"],
        ):
            candidate = self._candidate()
        receipt = candidate["receipt_contract_candidate"]
        self.assertFalse(candidate["all_stages_passed"])
        self.assertEqual(candidate["status"], "source_unverified")
        self.assertFalse(receipt["all_stages_passed"])
        self.assertEqual(receipt["status"], "source_unverified")
        self.assertEqual(candidate["execution_trace"]["outcome"], "failed")
        self.assertEqual(
            candidate["execution_trace"]["error_class"],
            "invalid_execution_trace",
        )
        self.assertEqual(
            receipt["operational_errors"][-1]["error_kind"],
            "invalid_execution_trace",
        )

    def test_unattempted_command_is_not_reported_as_an_invocation(self):
        candidate = self._candidate(
            invocation_attempted=False,
            exit_code=None,
            duration_ms=0.0,
            all_stages_passed=False,
            operational_errors=[
                {
                    "stage": "cas_acquisition",
                    "command": "import PKos",
                    "error_kind": "missing_destination_module",
                    "message": "missing",
                    "environment_blocked": False,
                }
            ],
        )
        receipt = candidate["receipt_contract_candidate"]
        self.assertEqual(receipt["source_invocation_status"], "not_invoked")
        self.assertIsNone(receipt["source_invocation"])
        self.assertEqual(
            receipt["planned_source_invocation"]["command"],
            ["python", "donor_probe.py", "pkos/README.md"],
        )
        self.assertFalse(candidate["all_stages_passed"])

    def test_unresolvable_recovery_route_fails_closed_instead_of_raising(self):
        with patch(
            "portfolio_suites.adapters.operator_os.load_recovery_program",
            side_effect=RecoveryProgramError("recovery program cannot be loaded"),
        ):
            candidate = self._candidate()
        receipt = candidate["receipt_contract_candidate"]
        self.assertFalse(candidate["all_stages_passed"])
        self.assertEqual(candidate["status"], "source_unverified")
        self.assertIsNone(candidate["execution_trace"])
        self.assertEqual(
            receipt["operational_errors"][-1]["error_kind"],
            "recovery_program_unavailable",
        )
        self.assertTrue(receipt["operational_errors"][-1]["environment_blocked"])

    def test_wave_runner_reports_an_unresolvable_route_as_a_failed_gate(self):
        with patch(
            "portfolio_suites.adapters.operator_os.load_recovery_program",
            side_effect=RecoveryProgramError("recovery program cannot be loaded"),
        ):
            result = WaveRunner.run_wave("operator-os", "O4")
        self.assertFalse(result.passed)

    def test_trace_fields_come_from_the_governed_recovery_route(self):
        program = load_recovery_program()
        obligation = next(
            item for item in program["obligations"] if item["id"] == "operator-os/O4"
        )
        route = obligation["trace_route"]
        route["ontology_version"] = "9.9.9"
        route["mapping_version"] = "8.8.8"
        route["selected_authority"] = "dotfiles"
        with patch(
            "portfolio_suites.adapters.operator_os.load_recovery_program",
            return_value=program,
        ):
            candidate = self._candidate()
        trace = candidate["execution_trace"]
        self.assertEqual(trace["ontology_version"], "9.9.9")
        self.assertEqual(trace["mapping_version"], "8.8.8")
        self.assertEqual(trace["selected_authority"], "dotfiles")
        self.assertEqual(trace["resolved_mappings"], route["resolved_mappings"])
        self.assertEqual(trace["policy_decisions"], route["policy_decisions"])

    def test_extra_host_claims_merge_into_the_receipt(self):
        candidate = self._candidate()
        claims = candidate["receipt_contract_candidate"]["host_recomputed_claims"]
        self.assertEqual(claims["batch_size"], 3)
        self.assertTrue(claims["all_sources_cited"])


if __name__ == "__main__":
    unittest.main()