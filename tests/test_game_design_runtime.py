"""Fast, isolated contract checks for the G1 donor runtime adapter."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from portfolio_suites.adapters import game_design_runtime as runtime
from portfolio_suites.receipts import evidence_errors
from portfolio_suites.registry import load_suites
from portfolio_suites.waves import TABLE_RUNNERS, TableRunner, WaveRunner, classify_wave_spec


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GameDesignRuntimeProbeTests(unittest.TestCase):
    def _fake_donor(self, root: Path) -> None:
        (root / ".git").mkdir()
        package = root / "src" / "tuck_in_terrors_sim"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("\n", encoding="utf-8")
        (package / "catalog.py").write_text("CATALOG = True\n", encoding="utf-8")
        (package / "experiments.py").write_text("EXPERIMENTS = True\n", encoding="utf-8")
        (package / "cli.py").write_text(
            """import json
from pathlib import Path
from . import catalog, experiments

def main_cli(argv):
    def value(flag):
        return argv[argv.index(flag) + 1]
    count = int(value('--simulations'))
    output = Path(value('--output-file'))
    database = Path(value('--database'))
    rows = [{'valid': True, 'win_status': 'PRIMARY_WIN' if i % 2 else 'LOSS_NIGHTFALL'} for i in range(count)]
    summary = {
        'games': count, 'valid_games': count, 'invalid_games': 0,
        'wins': count // 2, 'losses': count - count // 2,
        'win_rate': (count // 2) / count,
        'outcomes': {'LOSS_NIGHTFALL': count - count // 2, 'PRIMARY_WIN': count // 2},
    }
    document = {
        'status': 'completed', 'finished_games': count,
        'manifest': {'objective': 'OBJ01_THE_FIRST_NIGHT', 'policy': value('--ai'), 'games': count, 'seed': int(value('--seed'))},
        'summary': summary, 'results': rows,
    }
    output.write_text(json.dumps(document), encoding='utf-8')
    database.write_bytes(b'temporary database')
    print('captured donor output')
    return 0
""",
            encoding="utf-8",
        )
        (root / "main.py").write_text("# fixture entrypoint\n", encoding="utf-8")
        (root / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "cards.json").write_text("[]", encoding="utf-8")
        (root / "data" / "objectives.json").write_text(
            json.dumps([{"objective_id": "OBJ01_THE_FIRST_NIGHT"}]), encoding="utf-8"
        )

    def test_probe_executes_donor_cli_and_emits_one_json_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "donor"
            root.mkdir()
            self._fake_donor(root)
            output = Path(temporary) / "result.json"
            database = Path(temporary) / "result.sqlite3"
            command = [
                sys.executable,
                "-I",
                str(runtime.PROBE),
                str(root),
                "--objective", "OBJ01",
                "--policy", "scoring_ai",
                "--simulations", "4",
                "--seed", "9",
                "--output-file", str(output),
                "--database", str(database),
            ]
            env = {"PATH": os.environ.get("PATH", ""), "TMPDIR": temporary}
            completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            lines = completed.stdout.splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["status"], "completed")
            self.assertGreaterEqual(len(payload["module_fingerprints"]), 4)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["finished_games"], 4)
            self.assertTrue(database.is_file())

    def test_adapter_recomputes_modules_summary_and_checks_receipt_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "donor"
            root.mkdir()
            self._fake_donor(root)
            package = root / "src" / "tuck_in_terrors_sim"
            module_names = ("cli", "catalog", "experiments")
            module_fingerprints = {
                f"tuck_in_terrors_sim.{name}": {
                    "path": f"src/tuck_in_terrors_sim/{name}.py",
                    "sha256": _sha((package / f"{name}.py").read_bytes()),
                }
                for name in module_names
            }
            module_fingerprints["tuck_in_terrors_sim.__init__"] = {
                "path": "src/tuck_in_terrors_sim/__init__.py",
                "sha256": _sha((package / "__init__.py").read_bytes()),
            }
            results = [
                {"valid": True, "win_status": "LOSS_NIGHTFALL"},
                {"valid": True, "win_status": "PRIMARY_WIN"},
                {"valid": True, "win_status": "LOSS_NIGHTFALL"},
            ]
            document = {
                "status": "completed",
                "finished_games": 3,
                "manifest": {"objective": "OBJ01_THE_FIRST_NIGHT", "policy": "scoring_ai", "games": 3, "seed": 0},
                "summary": {
                    "games": 3,
                    "valid_games": 3,
                    "invalid_games": 0,
                    "wins": 1,
                    "losses": 2,
                    "win_rate": 1 / 3,
                    "outcomes": {"LOSS_NIGHTFALL": 2, "PRIMARY_WIN": 1},
                },
                "results": results,
            }
            payload = {
                "status": "completed",
                "exit_code": 0,
                "duration_ms": 1.0,
                "python_version": "3.14.0",
                "python_implementation": "CPython",
                "module_fingerprints": module_fingerprints,
            }
            fingerprint = {
                "branch": "main",
                "head": "a" * 40,
                "short": "main@aaaaaaa",
                "is_dirty": True,
                "dirty_files_count": 1,
                "dirty_files": [" M main.py"],
                "patch_sha256": "b" * 64,
                "lockfile_sha256": "",
                "tested_files_fingerprint": {
                    "main.py": _sha((root / "main.py").read_bytes()),
                    "pyproject.toml": _sha((root / "pyproject.toml").read_bytes()),
                    "data/cards.json": _sha((root / "data" / "cards.json").read_bytes()),
                    "data/objectives.json": _sha((root / "data" / "objectives.json").read_bytes()),
                    "src/tuck_in_terrors_sim/cli.py": _sha((package / "cli.py").read_bytes()),
                },
                "target_state": "local_working_tree_candidate",
            }

            def fake_run(command, **kwargs):
                if command and command[0] == "git":
                    return SimpleNamespace(returncode=1, stdout="", stderr="")
                output_path = Path(command[command.index("--output-file") + 1])
                Path(command[command.index("--database") + 1]).write_bytes(b"db")
                output_path.write_text(json.dumps(document), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")

            with (
                patch.object(runtime, "DONOR_ROOT", root),
                patch.object(runtime, "SIMULATIONS", 3),
                patch.object(runtime, "get_git_fingerprint", return_value=fingerprint),
                patch.object(runtime, "is_meaningful_git_fingerprint", return_value=True),
                patch.object(runtime.subprocess, "run", side_effect=fake_run),
            ):
                candidate = runtime.GameDesignRuntimeAdapter.execute_g1_tucked_in_terrors_runtime()

            self.assertTrue(candidate["all_stages_passed"], candidate["operational_errors"])
            self.assertEqual(candidate["status"], "source_executed")
            self.assertEqual(candidate["host_recomputed_claims"]["invalid_games"], 0)
            self.assertEqual(candidate["host_recomputed_claims"]["module_count"], 4)
            self.assertTrue(candidate["recovery_behavior"]["rerun_safe"])
            self.assertTrue(candidate["historical_analysis_reference"]["receipt_sha256"])
            wave = {
                "status": "complete",
                "recovery_claim": {
                    "kind": "runtime",
                    "level": "source_executed",
                    "receipt_contract": "portfolio-runtime-source-v1",
                },
            }
            with tempfile.TemporaryDirectory() as evidence_dir:
                path = Path(evidence_dir) / "runtime.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                self.assertEqual(evidence_errors(wave, path, "game-design"), [])

    def test_host_rejects_a_donor_digest_that_disagrees_with_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "tuck_in_terrors_sim" / "cli.py"
            source.parent.mkdir(parents=True)
            source.write_text("# trusted host bytes\n", encoding="utf-8")
            verified, errors = runtime._host_module_fingerprints(
                root,
                {
                    "tuck_in_terrors_sim.cli": {
                        "path": "src/tuck_in_terrors_sim/cli.py",
                        "sha256": "0" * 64,
                    },
                    "tuck_in_terrors_sim.catalog": {
                        "path": "src/tuck_in_terrors_sim/cli.py",
                        "sha256": _sha(source.read_bytes()),
                    },
                    "tuck_in_terrors_sim.experiments": {
                        "path": "src/tuck_in_terrors_sim/cli.py",
                        "sha256": _sha(source.read_bytes()),
                    },
                },
            )
            self.assertEqual(len(verified), 3)
            self.assertTrue(any("disagrees" in error for error in errors))

    def test_g1_declares_and_routes_to_source_execution(self):
        wave = next(
            item for item in load_suites()["game-design"]["waves"] if item["id"] == "G1"
        )
        self.assertEqual(wave["recovery_claim"]["kind"], "runtime")
        self.assertEqual(wave["recovery_claim"]["level"], "source_executed")
        self.assertEqual(classify_wave_spec(wave), "verified_source_execution")
        runner, supports_full = WaveRunner._resolve_runner("game-design", "G1")
        self.assertIsNotNone(runner)
        self.assertFalse(supports_full)

    def test_wave_runner_classifies_donor_import_failure_as_environment_blocked(self):
        blocked = {
            "status": "source_unverified",
            "all_stages_passed": False,
            "gate_summary": {"environment_blocked": True, "donor_status": "import_failed"},
        }
        fake_entry = TableRunner(lambda: blocked, "mock G1 runtime", "gate_summary")
        with patch.dict(TABLE_RUNNERS, {("game-design", "G1"): fake_entry}):
            result = WaveRunner.run_wave("game-design", "G1", write_evidence=False)
        self.assertFalse(result.passed)
        self.assertEqual(result.execution_kind, "unverifiable_environment")
        self.assertTrue(result.data["environment_blocked"])


if __name__ == "__main__":
    unittest.main()
