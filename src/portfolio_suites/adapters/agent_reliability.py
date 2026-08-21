"""Source adapter for Agent Reliability Lab binding waves to real harness and component donors."""

from __future__ import annotations

import ast
import functools
import json
import os
import re
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256, validate_contract
from ..engines.agent_reliability import AgentReliabilityEngine
from ..paths import PROJECTS_ROOT
from .common import get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

LOOPING_BOX_DIR = get_repo_path("looping-box", "LOOPING_BOX_DIR")
SSSF_DIR = get_repo_path("sssf", "SSSF_DIR")
AGENTIC_HARNESS_DIR = get_repo_path("agentic-harness", "AGENTIC_HARNESS_DIR")
AI_STAFF_DIR = get_repo_path("AI-Staff-HQ", "AI_STAFF_HQ_DIR")
COMPONENTS_DIR = get_repo_path("components", "COMPONENTS_DIR")

LOOPING_BOX_TRACKED = [
    "src/looping_box/action_policy.py",
    "src/looping_box/supervisor.py",
    "src/looping_box/worker.py",
    "src/looping_box/schema.py",
    "README.md",
]
SSSF_TRACKED = ["aop.py", "spec.md", "README.md"]
AGENTIC_HARNESS_TRACKED = ["agent.py", "evals/smoke.json", "README.md"]
AI_STAFF_TRACKED = ["evals/planning_swarm_cases.yaml", "evals/planning_swarm_real_briefs.yaml", "README.md"]

# Reliability gates, and the source evidence that a harness actually implements each one.
GATE_MARKERS = {
    "confinement": r"resolve_under_root|is_relative_to|\.\./|traversal|confin",
    "review_required": r"review_required|approval|confirm",
    "budget": r"max_iterations|max_steps|budget|max_calls",
    "malformed_output": r"JSONDecodeError|json\.loads|validate|schema",
    "rollback": r"rollback|revert|restore|staging",
}
HARNESSES = {
    "looping-box": (LOOPING_BOX_DIR, ["src/looping_box"]),
    "sssf": (SSSF_DIR, ["aop.py"]),
    "agentic-harness": (AGENTIC_HARNESS_DIR, ["agent.py"]),
}

SCAN_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}
SCAN_SUFFIXES = {".py", ".toml", ".txt", ".cfg", ".md"}
MAX_SCANNED_BYTES = 262_144


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json_object(path: Path) -> dict[str, Any]:
    """Donor JSON as a mapping. A malformed or wrong-shaped artifact yields {}, never an exception."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _donor_action_classes() -> dict[str, Any]:
    """The real action policy vocabulary declared by looping-box, read from its source."""
    source = _read_text(LOOPING_BOX_DIR / "src" / "looping_box" / "action_policy.py")
    try:
        module = ast.parse(source)
    except SyntaxError:
        return {}
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_ACTION_CLASSES" for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return {}
    return {}


@functools.lru_cache(maxsize=4)
def _external_consumers(component: str) -> tuple[str, ...]:
    """Sibling repositories that reference `component`, excluding the component's own home."""
    consumers: set[str] = set()
    for repo in sorted(PROJECTS_ROOT.iterdir()):
        if not repo.is_dir() or repo.name in {COMPONENTS_DIR.name, "suites"}:
            continue
        for dirpath, dirnames, filenames in os.walk(repo):
            dirnames[:] = [name for name in dirnames if name not in SCAN_SKIP_DIRS]
            for filename in filenames:
                if Path(filename).suffix not in SCAN_SUFFIXES:
                    continue
                path = Path(dirpath) / filename
                try:
                    if path.stat().st_size > MAX_SCANNED_BYTES:
                        continue
                except OSError:
                    continue
                if component in _read_text(path):
                    consumers.add(repo.name)
                    break
            if repo.name in consumers:
                break
    return tuple(sorted(consumers))


class AgentReliabilitySourceAdapter:
    """Reads authentic looping-box, sssf, agentic-harness, AI-Staff-HQ, and components sources."""

    @classmethod
    def execute_r1_adversarial_harness_scorecard(cls) -> dict[str, Any]:
        """R1: Turn the donor's own action policy into adversarial fixtures with expected outcomes."""
        fingerprint = get_git_fingerprint(LOOPING_BOX_DIR, LOOPING_BOX_TRACKED)
        policy = _donor_action_classes()
        classes = policy.get("classes", {}) if isinstance(policy, dict) else {}
        source_verified = is_meaningful_git_fingerprint(fingerprint) and bool(classes)
        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "R1",
                "status": "source_unverified",
                "looping_box_fingerprint": fingerprint,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        iterations = []
        for index, (action_class, terms) in enumerate(sorted(classes.items()), start=1):
            for term in terms:
                must_be_gated = action_class in {"review_required", "blocked", "forbidden"}
                iterations.append({
                    "iteration": len(iterations) + 1,
                    "scenario_id": f"policy-{action_class}-{term.replace(' ', '_')}",
                    "action": term,
                    "donor_class": action_class,
                    "expected_gated": must_be_gated,
                    "passed": True,
                    "score": 1.0,
                    "outcome_source": "donor_declared_policy",
                })

        scorecard = AgentReliabilityEngine.run_adversarial_harness()
        confinement_holds, _ = AgentReliabilityEngine.verify_path_confinement("/workspace/sandbox", "safe/file.txt")
        escape_blocked, _ = AgentReliabilityEngine.verify_path_confinement("/workspace/sandbox", "../../etc/passwd")

        run = validate_contract("ExperimentRun", {
            "artifact_kind": "reference_prototype_run",
            "migration_acceptance_verified": False,
            "schema_version": SCHEMA_VERSION,
            "run_id": "run-r1-donor-policy-fixtures",
            "benchmark_id": "bench-agent-reliability-fixtures",
            "benchmark_version": f"action_policy@{compute_sha256(json.dumps(policy, sort_keys=True).encode('utf-8'))[:12]}",
            "provider": "deterministic-oracle",
            "model": "looping-box-action-policy",
            "parameters": {"donor": "looping-box", "policy_classes": sorted(classes)},
            "scorer": "donor_policy_expectation_matrix",
            "scorer_version": "1.0.0",
            "status": "completed",
            "iterations": iterations,
            "evidence": [{
                "evaluator": "donor_policy_reader",
                "summary": f"{len(iterations)} fixtures derived from {len(classes)} donor action classes.",
                "gated_fixture_count": sum(1 for it in iterations if it["expected_gated"]),
                "confinement_probe": {"safe_path_allowed": confinement_holds, "escape_blocked": not escape_blocked},
            }],
            "errors": [],
        })

        all_stages_passed = (
            source_verified
            and bool(iterations)
            and confinement_holds
            and not escape_blocked
            and scorecard.get("status") == "completed"
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "R1",
            "status": "fixtures_defined" if all_stages_passed else "fixtures_rejected",
            "canonical_run": run,
            "donor_policy": policy,
            "engine_scorecard": scorecard,
            "looping_box_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_r2_cross_harness_eval(cls) -> dict[str, Any]:
        """R2: Measure which reliability gates each harness actually implements in its own source.

        ponytail: source-evidence coverage, not execution. Running the fixtures inside three
        third-party runtimes is the runtime follow-up this wave names.
        """
        fingerprints = {
            name.replace("-", "_"): get_git_fingerprint(repo, tracked)
            for name, (repo, tracked) in {
                "looping-box": (LOOPING_BOX_DIR, LOOPING_BOX_TRACKED),
                "sssf": (SSSF_DIR, SSSF_TRACKED),
                "agentic-harness": (AGENTIC_HARNESS_DIR, AGENTIC_HARNESS_TRACKED),
            }.items()
        }

        coverage: dict[str, Any] = {}
        for harness, (repo, targets) in HARNESSES.items():
            blob = ""
            for target in targets:
                path = repo / target
                if path.is_dir():
                    blob += "".join(_read_text(child) for child in sorted(path.rglob("*.py")))
                else:
                    blob += _read_text(path)
            coverage[harness] = {
                gate: bool(re.search(pattern, blob, re.IGNORECASE))
                for gate, pattern in GATE_MARKERS.items()
            }
            coverage[harness]["source_bytes_scanned"] = len(blob)

        gates_covered = {
            gate: sorted(name for name, result in coverage.items() if result.get(gate))
            for gate in GATE_MARKERS
        }
        source_verified = all(is_meaningful_git_fingerprint(fp) for fp in fingerprints.values())
        all_stages_passed = (
            source_verified
            and all(result["source_bytes_scanned"] > 0 for result in coverage.values())
            and len(gates_covered["confinement"]) >= 2
            and all(gates_covered[gate] for gate in GATE_MARKERS)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "R2",
            "status": "coverage_measured" if all_stages_passed else "coverage_incomplete",
            "harness_coverage": coverage,
            "gates_covered": gates_covered,
            "fingerprints": fingerprints,
            "execution_limitation": "gate presence read from harness source; fixtures not executed inside the donor runtimes",
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_r3_promoted_components(cls) -> dict[str, Any]:
        """R3: Count the real consumers of the promoted shared component before keeping it shared."""
        fingerprint = get_git_fingerprint(COMPONENTS_DIR, ["README.md"])
        promoted = sorted(
            path.name for path in COMPONENTS_DIR.iterdir() if path.is_dir() and not path.name.startswith(".")
        ) if COMPONENTS_DIR.is_dir() else []

        components = [
            {
                "component_id": f"comp-{name}",
                "path": f"components/{name}",
                "consumers": list(_external_consumers(name)),
            }
            for name in promoted
        ]
        source_verified = is_meaningful_git_fingerprint(fingerprint) and bool(components)
        all_stages_passed = source_verified and any(len(c["consumers"]) >= 2 for c in components)
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "R3",
            "status": "consumers_measured" if all_stages_passed else "source_unverified",
            "promoted_components": components,
            "measurement": {
                "method": "content reference scan across sibling repositories",
                "scanned_root": str(PROJECTS_ROOT),
                "skipped_directories": sorted(SCAN_SKIP_DIRS),
            },
            "components_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_r4_promoted_components_audit(cls) -> dict[str, Any]:
        """R4: Apply the two-consumer craft rule to the measured component inventory."""
        measured = cls.execute_r3_promoted_components()
        components = measured.get("promoted_components", [])
        source_verified = measured.get("source_verification_passed", False)
        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "R4",
                "status": "source_unverified",
                "components_fingerprint": measured.get("components_fingerprint"),
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        audit = AgentReliabilityEngine.audit_promoted_components(components)
        all_stages_passed = (
            audit.get("promoted_retained_count", 0) + audit.get("demoted_count", 0) == len(components)
            and audit.get("promoted_retained_count", 0) >= 1
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "R4",
            "status": "craft_rule_enforced" if all_stages_passed else "audit_failed",
            "audit": audit,
            "audited_components": components,
            "components_fingerprint": measured.get("components_fingerprint"),
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_r5_curriculum_fixtures(cls) -> dict[str, Any]:
        """R5: Mine real AI Staff and harness eval cases into deterministic curriculum fixtures."""
        staff_fp = get_git_fingerprint(AI_STAFF_DIR, AI_STAFF_TRACKED)
        harness_fp = get_git_fingerprint(AGENTIC_HARNESS_DIR, AGENTIC_HARNESS_TRACKED)

        modules = []
        for rel in ("evals/planning_swarm_cases.yaml", "evals/planning_swarm_real_briefs.yaml"):
            path = AI_STAFF_DIR / rel
            text = _read_text(path)
            # ponytail: `- id:` scan, not a YAML parse — stdlib has no YAML and these files
            # only need their case identifiers. Add a parser when the values matter.
            case_ids = re.findall(r"^\s*-\s*id:\s*(\S+)", text, re.M)
            if case_ids:
                modules.append({
                    "id": f"mod-{path.stem}",
                    "topic": f"AI Staff planning cases from {rel}",
                    "gates": ["plan_validation", "capability_routing"],
                    "source": f"AI-Staff-HQ/{rel}",
                    "source_sha256": compute_sha256(path.read_bytes()),
                    "case_ids": case_ids,
                })

        smoke_path = AGENTIC_HARNESS_DIR / "evals" / "smoke.json"
        smoke = _read_json_object(smoke_path)
        cases = smoke.get("cases")
        smoke_cases = [
            case["name"]
            for case in (cases if isinstance(cases, list) else [])
            if isinstance(case, dict) and isinstance(case.get("name"), str) and case["name"]
        ]
        if smoke_cases:
            modules.append({
                "id": "mod-agentic-harness-smoke",
                "topic": "Agentic harness artifact and substring assertions",
                "gates": ["artifact_written", "content_match"],
                "source": "agentic-harness/evals/smoke.json",
                "source_sha256": compute_sha256(smoke_path.read_bytes()),
                "case_ids": smoke_cases,
            })

        fixtures = AgentReliabilityEngine.build_curriculum_fixtures(modules) if modules else {}
        source_verified = all(is_meaningful_git_fingerprint(fp) for fp in (staff_fp, harness_fp)) and bool(modules)
        all_stages_passed = (
            source_verified
            and fixtures.get("status") == "curriculum_fixtures_verified"
            and fixtures.get("fixtures_count") == len(modules)
            and sum(len(module["case_ids"]) for module in modules) >= 3
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "R5",
            "status": "curriculum_mined" if all_stages_passed else "curriculum_rejected",
            "curriculum_fixtures": fixtures,
            "mined_modules": modules,
            "ai_staff_fingerprint": staff_fp,
            "agentic_harness_fingerprint": harness_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }
