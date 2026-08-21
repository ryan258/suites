import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.registry import load_suites
from portfolio_suites.waves import WaveRunner

# Waves promoted from specification to source-backed prototype checks.
PROMOTED = {
    "model-behavior-lab": ["M1", "M2", "M3", "M4", "M5"],
    "discovery-decision": ["D1", "D2", "D3", "D4", "D5"],
    "agent-reliability": ["R1", "R2", "R3", "R4", "R5"],
    "game-design": ["G1", "G2", "G3", "G4", "G5"],
    "accessibility": ["A6"],
}

# One wave per new adapter, and the donor paths it must have to make any claim at all.
FAIL_CLOSED_CASES = [
    ("model-behavior-lab", "M1", "model_behavior", ["ETHICS_DIR"]),
    ("model-behavior-lab", "M4", "model_behavior", ["CHESS_DIR"]),
    ("discovery-decision", "D1", "discovery_decision", ["SIF_DIR", "FORGE_DIR"]),
    ("discovery-decision", "D3", "discovery_decision", ["INSIGHT_DIR"]),
    ("agent-reliability", "R1", "agent_reliability", ["LOOPING_BOX_DIR"]),
    ("agent-reliability", "R5", "agent_reliability", ["AI_STAFF_DIR", "AGENTIC_HARNESS_DIR"]),
    ("game-design", "G1", "game_design", ["TUCKED_IN_TERRORS_DIR"]),
    ("game-design", "G4", "game_design", ["STORYWEAVER_DIR"]),
]


class SourceBackedWaveTests(unittest.TestCase):
    def test_promoted_waves_declare_a_prototype_analysis_claim(self):
        suites = load_suites()
        for suite_id, wave_ids in PROMOTED.items():
            waves = {wave["id"]: wave for wave in suites[suite_id]["waves"]}
            for wave_id in wave_ids:
                with self.subTest(wave=f"{suite_id}/{wave_id}"):
                    claim = waves[wave_id].get("recovery_claim", {})
                    self.assertEqual(claim.get("kind"), "analysis")
                    self.assertEqual(claim.get("level"), "prototype")
                    self.assertIs(claim.get("real_runtime"), False)
                    self.assertTrue(claim.get("evidence_basis"))
                    self.assertTrue(waves[wave_id].get("runtime_followup"))

    def test_promoted_waves_pass_against_their_real_donors(self):
        for suite_id, wave_ids in PROMOTED.items():
            for wave_id in wave_ids:
                with self.subTest(wave=f"{suite_id}/{wave_id}"):
                    result = WaveRunner.run_wave(suite_id, wave_id, write_evidence=False)
                    self.assertEqual(result.execution_kind, "prototype_check")
                    self.assertTrue(result.prototype_passed, result.message)
                    self.assertFalse(result.passed)

    def test_source_backed_waves_fail_closed_without_donors(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            for suite_id, wave_id, module, constants in FAIL_CLOSED_CASES:
                with self.subTest(wave=f"{suite_id}/{wave_id}"):
                    patches = [
                        patch(f"portfolio_suites.adapters.{module}.{name}", missing / name.lower())
                        for name in constants
                    ]
                    for active in patches:
                        active.start()
                    try:
                        result = WaveRunner.run_wave(suite_id, wave_id, write_evidence=True)
                    finally:
                        for active in reversed(patches):
                            active.stop()
                    self.assertFalse(result.prototype_passed)
                    self.assertFalse(result.passed)
                    self.assertIsNone(result.evidence_path)

    def test_malformed_donor_json_fails_closed_instead_of_raising(self):
        from portfolio_suites.adapters.agent_reliability import _read_json_object

        with tempfile.TemporaryDirectory() as tmp:
            donor = Path(tmp) / "agentic-harness"
            (donor / "evals").mkdir(parents=True)
            for payload in ("{bad", "[]", '{"cases": "not-a-list"}'):
                with self.subTest(payload=payload):
                    (donor / "evals" / "smoke.json").write_text(payload, encoding="utf-8")
                    self.assertIsInstance(_read_json_object(donor / "evals" / "smoke.json"), dict)
                    with patch("portfolio_suites.adapters.agent_reliability.AGENTIC_HARNESS_DIR", donor):
                        result = WaveRunner.run_wave("agent-reliability", "R5", write_evidence=True)
                    self.assertFalse(result.prototype_passed)
                    self.assertIsNone(result.evidence_path)

    def test_run_all_survives_a_malformed_donor_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            donor = Path(tmp) / "agentic-harness"
            (donor / "evals").mkdir(parents=True)
            (donor / "evals" / "smoke.json").write_text("{bad", encoding="utf-8")
            with patch("portfolio_suites.adapters.agent_reliability.AGENTIC_HARNESS_DIR", donor):
                results = WaveRunner.run_all(write_evidence=False)
        self.assertEqual(len(results), 43)
        failed = {result.wave_id for result in results if not (result.passed or result.prototype_passed)}
        self.assertIn("R5", failed)


if __name__ == "__main__":
    unittest.main()
