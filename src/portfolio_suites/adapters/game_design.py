"""Source adapter for Game Design + Simulation binding waves to real Storyweaver and game donors."""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256
from ..engines.game_design import GameDesignEngine
from .common import get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

STORYWEAVER_DIR = get_repo_path("storyweaver", "STORYWEAVER_DIR")
TUCKED_IN_TERRORS_DIR = get_repo_path("TuckdInTerrors_MonteCarloSim", "TUCKED_IN_TERRORS_DIR")
OREGON_DND_DIR = get_repo_path("oregon  dnd", "OREGON_DND_DIR")
MARCH_MADNESS_DIR = get_repo_path("march-madness", "MARCH_MADNESS_DIR")

STORYWEAVER_TRACKED = ["pyproject.toml", "README.md", "dev_spec.md"]
TUCKED_IN_TERRORS_TRACKED = ["data/cards.json", "data/objectives.json", "main.py", "README.md"]
OREGON_DND_TRACKED = ["01_events_and_hazards.md", "README.md"]
MARCH_MADNESS_TRACKED = ["config.yaml", "requirements.txt", "README.md"]



def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _tit_corpus() -> dict[str, Any] | None:
    """Real Tucked in Terrors rules data and recorded simulation rows."""
    cards_path = TUCKED_IN_TERRORS_DIR / "data" / "cards.json"
    objectives_path = TUCKED_IN_TERRORS_DIR / "data" / "objectives.json"
    results_path = TUCKED_IN_TERRORS_DIR / "results" / "run_01.json"
    cards, objectives, rows = _read_json(cards_path), _read_json(objectives_path), _read_json(results_path)
    if not (isinstance(cards, list) and isinstance(objectives, list) and isinstance(rows, list) and rows):
        return None
    return {
        "cards": cards,
        "objectives": objectives,
        "rows": rows,
        "cards_sha256": compute_sha256(cards_path.read_bytes()),
        "objectives_sha256": compute_sha256(objectives_path.read_bytes()),
        "results_sha256": compute_sha256(results_path.read_bytes()),
    }


def _outcome_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(collections.Counter(str(row.get("win_status")) for row in rows).items()))


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Min/mean/max for every numeric metric the donor recorded."""
    numeric_keys = sorted(
        key for key, value in rows[0].items() if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    summary = {}
    for key in numeric_keys:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        summary[key] = {
            "min": min(values),
            "max": max(values),
            "mean": round(sum(values) / len(values), 4),
            "samples": len(values),
        }
    return summary


def _gds_vocabulary() -> list[str]:
    """Pack slots Storyweaver actually writes, measured across its own real projects."""
    slots: set[str] = set()
    try:
        projects = sorted(path for path in (STORYWEAVER_DIR / "projects").iterdir() if path.is_dir())
    except OSError:
        return []
    for project in projects:
        slots.update(path.name for path in (project / "gds").glob("*.json"))
    return sorted(slots)


def _storyweaver_reference_pack() -> tuple[Path, list[str]] | None:
    """A real Storyweaver project and the gds slots it actually wrote."""
    try:
        projects = sorted(path for path in (STORYWEAVER_DIR / "projects").iterdir() if path.is_dir())
    except OSError:
        return None
    for project in projects:
        gds = project / "gds"
        if gds.is_dir():
            return project, sorted(path.name for path in gds.glob("*.json"))
    return None


def _markdown_inventory(repo: Path) -> list[dict[str, Any]]:
    try:
        paths = sorted(path for path in repo.glob("*.md") if path.is_file())
    except OSError:
        return []
    inventory = []
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-8", errors="replace")
        inventory.append({
            "file": path.name,
            "sha256": compute_sha256(raw),
            "bytes": len(raw),
            "title": next(
                (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
                path.stem,
            ),
        })
    return inventory


def _engine_coupling(repo: Path, engine_name: str) -> dict[str, Any]:
    """Whether an authored game imports or references the suite's engine donor at all."""
    referencing = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".toml", ".yaml", ".yml", ".txt"}:
            continue
        try:
            if path.stat().st_size > 262_144:
                continue
            if engine_name.lower() in path.read_text(encoding="utf-8", errors="replace").lower():
                referencing.append(str(path.relative_to(repo)))
        except OSError:
            continue
    return {"engine": engine_name, "referencing_files": referencing, "coupled": bool(referencing)}


class GameDesignSourceAdapter:
    """Reads authentic storyweaver, Tucked in Terrors, Oregon D&D, and March Madness sources."""

    @classmethod
    def execute_g1_tucked_in_terrors_fingerprint(cls) -> dict[str, Any]:
        """G1: Fingerprint the donor's real rules, recorded runs, metrics, and outcome tolerances."""
        fingerprint = get_git_fingerprint(TUCKED_IN_TERRORS_DIR, TUCKED_IN_TERRORS_TRACKED)
        corpus = _tit_corpus()
        source_verified = is_meaningful_git_fingerprint(fingerprint) and corpus is not None
        if not source_verified:
            return {
                "wave": "G1",
                "status": "source_unverified",
                "all_stages_passed": False,
                "document": "# G1 — Tucked in Terrors fingerprint\n\nSource unverified; no receipt written.\n",
            }

        rows = corpus["rows"]
        distribution = _outcome_distribution(rows)
        metrics = _metric_summary(rows)
        objectives = sorted({str(row.get("objective_id")) for row in rows})
        lines = [
            "# G1 — Tucked in Terrors parity fixture",
            "",
            f"- game_version_fingerprint: `{fingerprint['short']}` (dirty={fingerprint['is_dirty']})",
            f"- cards_sha256: `{corpus['cards_sha256']}` ({len(corpus['cards'])} cards)",
            f"- objectives_sha256: `{corpus['objectives_sha256']}` ({len(corpus['objectives'])} objectives)",
            f"- results_sha256: `{corpus['results_sha256']}` ({len(rows)} recorded runs)",
            f"- objectives_exercised: {', '.join(objectives)}",
            "",
            "## outcome_distribution",
            "",
            "| win_status | runs | share |",
            "| --- | ---: | ---: |",
        ]
        lines += [
            f"| {status} | {count} | {count / len(rows):.3f} |"
            for status, count in distribution.items()
        ]
        lines += ["", "## metric_tolerances", "", "| metric | min | mean | max |", "| --- | ---: | ---: | ---: |"]
        lines += [
            f"| {name} | {value['min']} | {value['mean']} | {value['max']} |"
            for name, value in metrics.items()
        ]
        lines += [
            "",
            "## configuration",
            "",
            "- seed_policy: donor run_01 corpus is the fixed reference sample; no reseeding is claimed.",
            "- expected_tolerances: any replacement runtime must reproduce the distribution above per objective.",
            "",
        ]

        return {
            "wave": "G1",
            "status": "fingerprinted",
            "all_stages_passed": True,
            "document": "\n".join(lines),
            "outcome_distribution": distribution,
            "metric_tolerances": metrics,
            "tucked_in_terrors_fingerprint": fingerprint,
            "source_verification_passed": True,
        }

    @classmethod
    def execute_g2_storyweaver_pack_parity(cls) -> dict[str, Any]:
        """G2: Express the donor game as a Storyweaver-shaped data pack over its own recorded runs."""
        tit_fp = get_git_fingerprint(TUCKED_IN_TERRORS_DIR, TUCKED_IN_TERRORS_TRACKED)
        sw_fp = get_git_fingerprint(STORYWEAVER_DIR, STORYWEAVER_TRACKED)
        corpus = _tit_corpus()
        reference = _storyweaver_reference_pack()
        source_verified = (
            all(is_meaningful_git_fingerprint(fp) for fp in (tit_fp, sw_fp))
            and corpus is not None
            and reference is not None
        )
        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "G2",
                "status": "source_unverified",
                "tucked_in_terrors_fingerprint": tit_fp,
                "storyweaver_fingerprint": sw_fp,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        project, slots_written = reference
        vocabulary = _gds_vocabulary()
        rows = corpus["rows"]
        donor_distribution = _outcome_distribution(rows)
        pack = {
            "pack_id": "pack-storyweaver-tucked-in-terrors",
            "game_name": "Tucked In Terrors",
            "gds_slots": {
                "cards.json": {"filled_from": "TuckdInTerrors_MonteCarloSim/data/cards.json", "items": len(corpus["cards"])},
                "objectives.json": {"filled_from": "TuckdInTerrors_MonteCarloSim/data/objectives.json", "items": len(corpus["objectives"])},
                "game.json": {"filled_from": "donor recorded run summary", "items": len(rows)},
            },
            "unfilled_gds_slots": [slot for slot in vocabulary if slot not in {"cards.json", "objectives.json", "game.json"}],
            "reference_project": f"storyweaver/projects/{project.name}",
            "reference_slots_written": slots_written,
        }
        # ponytail: shape projection only. Comparing a summary of the donor rows against those
        # same rows would be a tautology, so no parity number is produced at all: nothing was
        # generated independently to compare against.
        shape_projection = {
            "method": "donor rows and rules data projected into the Storyweaver pack vocabulary",
            "donor_outcome_distribution": donor_distribution,
            "donor_rows_summarized": len(rows),
            "pack_slots_filled": sorted(pack["gds_slots"]),
            "pack_slots_within_observed_vocabulary": set(pack["gds_slots"]) <= set(vocabulary),
            "parallel_engine_written": False,
            "pack_materialized_on_disk": False,
            "independent_resimulation_verified": False,
            "statistical_parity_measured": False,
        }
        all_stages_passed = (
            source_verified
            and shape_projection["pack_slots_within_observed_vocabulary"]
            and bool(rows)
            and bool(slots_written)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "G2",
            "status": "pack_shape_projected" if all_stages_passed else "pack_rejected",
            "pack": pack,
            "shape_projection": shape_projection,
            "tucked_in_terrors_fingerprint": tit_fp,
            "storyweaver_fingerprint": sw_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_g3_authored_game_boundary(cls) -> dict[str, Any]:
        """G3: Record the authored Oregon D&D corpus and prove no engine coupling was introduced."""
        fingerprint = get_git_fingerprint(OREGON_DND_DIR, OREGON_DND_TRACKED)
        inventory = _markdown_inventory(OREGON_DND_DIR)
        coupling = _engine_coupling(OREGON_DND_DIR, "storyweaver")
        source_verified = is_meaningful_git_fingerprint(fingerprint) and bool(inventory)
        all_stages_passed = source_verified and not coupling["coupled"]
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "G3",
            "status": "boundary_documented" if all_stages_passed else "boundary_unverified",
            "authored_inventory": inventory,
            "engine_coupling": coupling,
            "boundary": {
                "authored_game": "oregon  dnd",
                "ownership": "independent_creative_reference",
                "platform_invented": False,
                "pack_contract": "optional",
            },
            "oregon_dnd_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_g4_storyweaver_adventure_pack(cls) -> dict[str, Any]:
        """G4: Check a second game class fills the same slots Storyweaver writes for its own projects."""
        sw_fp = get_git_fingerprint(STORYWEAVER_DIR, STORYWEAVER_TRACKED)
        reference = _storyweaver_reference_pack()
        source_verified = is_meaningful_git_fingerprint(sw_fp) and reference is not None
        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "G4",
                "status": "source_unverified",
                "storyweaver_fingerprint": sw_fp,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        project, slots_written = reference
        vocabulary = _gds_vocabulary()
        pack = GameDesignEngine.build_text_adventure_pack("pack-storyweaver-echo-chambers", rooms_count=8)
        schema_check = {
            "reference_project": f"storyweaver/projects/{project.name}",
            "reference_slots_written": slots_written,
            "observed_gds_vocabulary": vocabulary,
            "pack_slots_within_vocabulary": True,
            "pack_declares_nodes": pack.get("nodes_count"),
            "pack_deterministic": pack.get("deterministic_graph"),
            "pack_slot_mapping": {"game.json": "graph metadata", "objectives.json": "win conditions"},
        }
        schema_check["pack_slots_within_vocabulary"] = set(schema_check["pack_slot_mapping"]) <= set(vocabulary)
        all_stages_passed = (
            source_verified
            and bool(vocabulary)
            and schema_check["pack_slots_within_vocabulary"]
            and pack.get("nodes_count") == 8
            and pack.get("deterministic_graph") is True
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "G4",
            "status": "second_class_verified" if all_stages_passed else "second_class_rejected",
            "pack": pack,
            "schema_check": schema_check,
            "storyweaver_fingerprint": sw_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_g5_march_madness_boundary(cls) -> dict[str, Any]:
        """G5: Audit the March Madness simulation for mandatory engine coupling before any port."""
        fingerprint = get_git_fingerprint(MARCH_MADNESS_DIR, MARCH_MADNESS_TRACKED)
        coupling = _engine_coupling(MARCH_MADNESS_DIR, "storyweaver")
        boundary = GameDesignEngine.audit_authored_game_boundary("march-madness")
        modules = sorted(
            str(path.relative_to(MARCH_MADNESS_DIR))
            for path in (MARCH_MADNESS_DIR / "src").rglob("*.py")
        ) if (MARCH_MADNESS_DIR / "src").is_dir() else []
        source_verified = is_meaningful_git_fingerprint(fingerprint) and bool(modules)
        all_stages_passed = (
            source_verified
            and not coupling["coupled"]
            and boundary.get("status") == "boundary_formalized"
            and boundary.get("suite_dependency_required") is False
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "G5",
            "status": "boundary_formalized" if all_stages_passed else "boundary_unverified",
            "boundary": boundary,
            "engine_coupling": coupling,
            "donor_modules": modules,
            "march_madness_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }
