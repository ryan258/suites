import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.registry import load_suites
from portfolio_suites.waves import WaveRunner

# Waves that parse authentic donor artifacts and must declare `source_inspected`.
SOURCE_INSPECTED = {
    "accessibility": ["A3", "A4", "A6"],
    "operator-os": ["O1", "O2", "O3", "O4", "O5", "O6"],
    "brand-publishing": ["B1", "B2", "B5"],
    "production-house": ["P1", "P2", "P3", "P4", "P5"],
    "model-behavior-lab": ["M1", "M2", "M3", "M4", "M5"],
    "discovery-decision": ["D1", "D2", "D3", "D4", "D5"],
    "agent-reliability": ["R1", "R2", "R3", "R4", "R5"],
    "game-design": ["G1", "G2", "G3", "G4", "G5"],
}

# Remaining suite-local engines that do not read donor artifacts.
PROTOTYPE_ONLY = {
    "accessibility": ["A5"],
    "brand-publishing": ["B3", "B4", "B6"],
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
    ("production-house", "P1", "production_house", ["GROUNDWIRE_DIR"]),
    ("production-house", "P4", "production_house", ["GROUNDWIRE_DIR", "PRODUCTION_HOUSE_DIR"]),
    ("brand-publishing", "B5", "brand_publishing", ["BRAND_WORKSHOP_DIR"]),
    ("operator-os", "O4", "operator_os", ["PKOS_DIR", "DOTFILES_DIR", "OBSERVER_DIR"]),
    ("operator-os", "O5", "operator_os", ["RYOS_DIR"]),
]


class SourceBackedWaveTests(unittest.TestCase):
    def test_source_inspected_waves_declare_the_rung_they_earned(self):
        suites = load_suites()
        for suite_id, wave_ids in SOURCE_INSPECTED.items():
            waves = {wave["id"]: wave for wave in suites[suite_id]["waves"]}
            for wave_id in wave_ids:
                with self.subTest(wave=f"{suite_id}/{wave_id}"):
                    claim = waves[wave_id].get("recovery_claim", {})
                    self.assertEqual(claim.get("kind"), "analysis")
                    self.assertEqual(claim.get("level"), "source_inspected")
                    self.assertIs(claim.get("real_runtime"), False)
                    self.assertTrue(claim.get("evidence_basis"))
                    self.assertTrue(waves[wave_id].get("runtime_followup"))

    def test_remaining_prototype_waves_stay_suite_local(self):
        suites = load_suites()
        for suite_id, wave_ids in PROTOTYPE_ONLY.items():
            waves = {wave["id"]: wave for wave in suites[suite_id]["waves"]}
            for wave_id in wave_ids:
                with self.subTest(wave=f"{suite_id}/{wave_id}"):
                    claim = waves[wave_id].get("recovery_claim", {})
                    self.assertEqual(claim.get("kind"), "analysis")
                    self.assertEqual(claim.get("level"), "prototype")
                    self.assertIs(claim.get("real_runtime"), False)

    def test_source_inspected_waves_pass_against_their_real_donors(self):
        for suite_id, wave_ids in SOURCE_INSPECTED.items():
            for wave_id in wave_ids:
                with self.subTest(wave=f"{suite_id}/{wave_id}"):
                    result = WaveRunner.run_wave(suite_id, wave_id, write_evidence=False)
                    self.assertEqual(result.execution_kind, "verified_analysis")
                    self.assertTrue(result.passed, result.message)
                    self.assertEqual(result.claim_level, "source_inspected")

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


# Every wave that still passes when all donor paths are blinded, i.e. every wave whose
# result comes only from suite-local fixtures. Each entry is deliberate and declared in
# its suite manifest's acceptance clause; the pin exists so a wave cannot join this set
# silently, and so a wave that is supposed to read a donor cannot quietly stop.
DONOR_INDEPENDENT = {
    ("accessibility", "A1"),      # hand-authored parity document, structure-checked only
}


class DonorBlindingCensusTests(unittest.TestCase):
    """Blind every donor path at once and pin exactly which gates still pass.

    The adapters resolve donor paths into module constants at import time, so the
    environment cannot be patched after the fact -- the constants are patched instead.
    """

    @staticmethod
    def _donor_constants():
        adapters = Path(__file__).resolve().parents[1] / "src" / "portfolio_suites" / "adapters"
        for module in sorted(adapters.glob("*.py")):
            for name in re.findall(
                r"^([A-Z][A-Z0-9_]*(?:_DIR|_ROOT))\s*=\s*get_repo_path", module.read_text(encoding="utf-8"), re.M
            ):
                yield f"portfolio_suites.adapters.{module.stem}.{name}"

    def test_only_declared_fixture_waves_survive_donor_blinding(self):
        targets = list(self._donor_constants())
        self.assertGreater(len(targets), 25, "donor constant discovery found suspiciously few paths")

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-such-donor"
            patches = [patch(target, missing) for target in targets]
            for active in patches:
                active.start()
            try:
                results = WaveRunner.run_all(write_evidence=False)
            finally:
                for active in reversed(patches):
                    active.stop()

        survived = {
            (r.suite_id, r.wave_id) for r in results if r.passed or r.prototype_passed
        }
        self.assertEqual(
            survived,
            DONOR_INDEPENDENT,
            "waves passing without any donor changed; update DONOR_INDEPENDENT only with "
            "a matching manifest acceptance clause",
        )


if __name__ == "__main__":
    unittest.main()
