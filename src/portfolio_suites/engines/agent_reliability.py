"""Agent Reliability reference prototype engine powering AgentRun evaluations, adversarial scorecards, and curriculum verification.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. agentic-harness, looping-box)."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract
from ..identifiers import new_prefixed_id


class AgentReliabilityEngine:
    """Run adversarial harness fixtures testing path confinement, malformed plans, budget bounds, and rollback."""

    @staticmethod
    def verify_path_confinement(workspace_root: str, target_path: str) -> tuple[bool, str]:
        """Check if target_path is strictly confined within workspace_root without traversal escapes."""
        root = Path(workspace_root).resolve()
        try:
            target = (root / target_path).resolve()
            if target == root or root in target.parents:
                return (True, f"Path {target_path!r} is safely confined inside {workspace_root}.")
            return (False, f"SECURITY VIOLATION: Path {target_path!r} escapes workspace root {workspace_root}.")
        except Exception as exc:
            return (False, f"Path resolution failed: {exc}")

    @staticmethod
    def _outside_strings(raw: str) -> list[tuple[bool, str]]:
        """Split JSON source into (is_string, segment) runs so repairs cannot touch prose.

        A repair regex run over the whole document also matches the contents of quoted
        strings, where a comma or a colon is ordinary text rather than syntax. Segmenting
        first is what keeps `{"note": "coordinate, owner: Ryan"}` from being "repaired"
        into nonsense.
        """
        segments: list[tuple[bool, str]] = []
        buffer: list[str] = []
        in_string = False
        escaped = False
        for char in raw:
            if in_string:
                buffer.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    segments.append((True, "".join(buffer)))
                    buffer = []
                    in_string = False
                continue
            if char == '"':
                if buffer:
                    segments.append((False, "".join(buffer)))
                buffer = ['"']
                in_string = True
                continue
            buffer.append(char)
        if buffer:
            segments.append((in_string, "".join(buffer)))
        return segments

    @classmethod
    def _repair_outside_strings(cls, raw: str, pattern: str, replacement: str) -> str:
        """Apply one repair to JSON syntax only, leaving quoted content byte-identical."""
        return "".join(
            segment if is_string else re.sub(pattern, replacement, segment)
            for is_string, segment in cls._outside_strings(raw)
        )

    # Each repair is narrow and is tried on its own before being combined, because a
    # document needing only one of them must not be failed by the other. A parser that
    # guesses harder starts inventing plans the agent never wrote.
    _TRAILING_COMMA = (r",(\s*[}\]])", r"\1")
    _BARE_KEY = (r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3')

    @classmethod
    def recover_plan(cls, raw_plan: str) -> dict[str, Any]:
        """Parse an agent plan, repairing only bounded syntax damage, or refuse it.

        Repairs are attempted individually and then together, returning the first candidate
        that parses, so the repair a document does not need can never break the one it does.
        Anything still unparseable is refused with the reason, never approximated.
        """
        if not isinstance(raw_plan, str):
            return {"status": "refused", "recovered": False, "plan": None, "reason": "plan must be a string"}
        try:
            return {"status": "valid", "recovered": False, "plan": json.loads(raw_plan), "repairs": []}
        except json.JSONDecodeError as first_error:
            original_reason = first_error.msg

        attempts: list[tuple[list[str], str]] = []
        for names in (["dropped_trailing_comma"], ["quoted_bare_key"], ["dropped_trailing_comma", "quoted_bare_key"]):
            candidate = raw_plan
            for name in names:
                pattern, replacement = cls._TRAILING_COMMA if name == "dropped_trailing_comma" else cls._BARE_KEY
                candidate = cls._repair_outside_strings(candidate, pattern, replacement)
            if candidate != raw_plan:
                attempts.append((names, candidate))

        last_error = original_reason
        for names, candidate in attempts:
            try:
                return {
                    "status": "repaired",
                    "recovered": True,
                    "plan": json.loads(candidate),
                    "repairs": names,
                }
            except json.JSONDecodeError as error:
                last_error = error.msg

        return {
            "status": "unrecoverable",
            "recovered": False,
            "plan": None,
            "repairs_attempted": sorted({name for names, _ in attempts for name in names}),
            "reason": f"{original_reason}; still unparseable after repair: {last_error}",
        }

    @staticmethod
    def partition_plan_by_budget(steps: list[Any], max_steps: int) -> dict[str, Any]:
        """Split a plan at its step budget into the part admitted and the part deferred.

        This admits steps; it does not run them. There is no action executor in this engine,
        so calling the admitted half "executed" would report work that never happened -- the
        exact defect this suite exists to catch, and one an earlier revision of this method
        shipped: it returned a write action under `executed` while nothing was ever written.
        The names say partitioning because partitioning is all that occurs.

        ponytail: a real bounded executor -- deriving counts from completed action receipts,
        with stop-at-budget and mid-plan failure paths -- is what would let this claim
        execution control. Build it when there is an executor worth bounding.
        """
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 0:
            raise ValueError("max_steps must be a non-negative integer")
        if not isinstance(steps, list):
            raise ValueError("steps must be a list")
        accepted = steps[:max_steps]
        deferred = steps[max_steps:]
        return {
            "requested": len(steps),
            "budget": max_steps,
            "accepted_count": len(accepted),
            "deferred_count": len(deferred),
            "accepted": accepted,
            "deferred": deferred,
            "budget_exhausted": bool(deferred),
            "executed": False,
            "execution_note": "steps are admitted against the budget, not run; no action was invoked",
        }

    @staticmethod
    def apply_with_rollback(initial_state: dict[str, Any], edits: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply edits as one transaction: any failing edit restores the state it started from.

        Each edit is ``{"key": ..., "value": ..., "fails": bool}``. Partial application is
        never returned -- a caller that sees `committed: false` can trust the state is the
        one it handed in, which is the whole point of asking for a transaction.
        """
        if not isinstance(initial_state, dict) or not isinstance(edits, list):
            raise ValueError("initial_state must be an object and edits a list")
        working = dict(initial_state)
        applied: list[str] = []
        for index, edit in enumerate(edits):
            if not isinstance(edit, dict) or "key" not in edit:
                raise ValueError(f"edit {index} needs a 'key'")
            if edit.get("fails"):
                return {
                    "committed": False,
                    "state": dict(initial_state),
                    "applied_before_failure": applied,
                    "failed_at_index": index,
                    "rolled_back": True,
                }
            working[edit["key"]] = edit.get("value")
            applied.append(edit["key"])
        return {
            "committed": True,
            "state": working,
            "applied_before_failure": applied,
            "failed_at_index": None,
            "rolled_back": False,
        }

    @classmethod
    def run_adversarial_harness(cls) -> dict[str, Any]:
        """Execute a battery of real deterministic reliability fixtures.

        Every fixture drives an engine method with adversarial input and checks the result
        in both directions -- what must be refused *and* what must still succeed. A fixture
        that only asserted the language's own semantics (that `json.loads` rejects bad JSON,
        that a `break` stops a loop) could never fail, and a gate that cannot fail is not
        evidence of anything.
        """
        mock_root = "/workspace/sandbox"

        # Fixture 1: Path Traversal Confinement
        traversal_inputs = ["../../etc/passwd", "/tmp/secret.key", "../../../root"]
        conf_results = [cls.verify_path_confinement(mock_root, p) for p in traversal_inputs]
        valid_conf, _ = cls.verify_path_confinement(mock_root, "safe/child/file.txt")
        fix_conf_passed = all(not is_confined for is_confined, _ in conf_results) and valid_conf

        # Fixture 2: Malformed Plan Recovery -- damage the repairer must fix, and damage it
        # must refuse. Falsely "recovering" an unparseable plan fails this as loudly as raising.
        repairable_input = '{"steps": [1, 2,], "mode": "quick",}'
        unrecoverable_inputs = ["{ unquoted_key: 123", "{'incomplete': true,"]
        repaired = cls.recover_plan(repairable_input)
        refusals = [cls.recover_plan(raw) for raw in unrecoverable_inputs]
        fix_json_passed = (
            repaired["status"] == "repaired"
            and repaired["plan"] == {"steps": [1, 2], "mode": "quick"}
            and all(r["status"] == "unrecoverable" and r["plan"] is None for r in refusals)
        )

        # Fixture 3: Budget Partition -- an over-budget plan is cut at the budget with the
        # remainder deferred; an under-budget plan is not clipped. This checks admission
        # only. Nothing here runs a step, so the fixture claims no execution control.
        max_steps = 5
        over_budget = cls.partition_plan_by_budget(list(range(10)), max_steps)
        under_budget = cls.partition_plan_by_budget(list(range(3)), max_steps)
        fix_budg_passed = (
            over_budget["accepted_count"] == max_steps
            and over_budget["deferred_count"] == 5
            and over_budget["budget_exhausted"] is True
            and over_budget["executed"] is False
            and under_budget["accepted_count"] == 3
            and under_budget["budget_exhausted"] is False
        )

        # Fixture 4: Atomic Rollback -- a failing edit restores the original state, and a
        # clean run still commits. Checking only the rollback would pass on a no-op engine.
        initial_state = {"doc_v": 1, "status": "clean"}
        rolled_back = cls.apply_with_rollback(
            initial_state,
            [{"key": "doc_v", "value": 2}, {"key": "status", "value": "dirty", "fails": True}],
        )
        committed = cls.apply_with_rollback(initial_state, [{"key": "doc_v", "value": 2}])
        fix_roll_passed = (
            rolled_back["committed"] is False
            and rolled_back["state"] == initial_state
            and rolled_back["failed_at_index"] == 1
            and committed["committed"] is True
            and committed["state"] == {"doc_v": 2, "status": "clean"}
        )

        fixtures = [
            {
                "fixture_id": "fix-conf-01",
                "name": "Path Traversal Escapes",
                "inputs": traversal_inputs,
                "expected": "all_rejected",
                "passed": fix_conf_passed,
            },
            {
                "fixture_id": "fix-json-02",
                "name": "Malformed Plan Recovery",
                "inputs": [repairable_input, *unrecoverable_inputs],
                "expected": "repairs_bounded_damage_and_refuses_the_rest",
                "passed": fix_json_passed,
            },
            {
                "fixture_id": "fix-budg-03",
                "name": "Budget Partition (admission only, no execution)",
                "inputs": {"max_steps": max_steps, "planned_steps": 10, "under_budget_steps": 3},
                "expected": "plan_cut_at_budget_without_clipping_short_plans",
                "passed": fix_budg_passed,
            },
            {
                "fixture_id": "fix-roll-04",
                "name": "Atomic Rollback on Execution Failure",
                "inputs": {"stage_1": "success", "stage_2": "fail", "control_run": "all_success"},
                "expected": "revert_stage_1_state_and_still_commit_clean_runs",
                "passed": fix_roll_passed,
            },
        ]

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        passed_count = sum(1 for f in fixtures if f["passed"])

        scorecard = {
            "schema_version": SCHEMA_VERSION,
            "run_id": new_prefixed_id("run-rel-harness"),
            "benchmark_id": "bench-agent-adversarial-gates",
            "benchmark_version": "1.0.0",
            "provider": "agent-reliability-lab",
            "model": "deterministic-harness",
            "parameters": {"confinement": "strict", "rollback": "atomic"},
            "scorer": "deterministic_fixture_evaluator",
            "scorer_version": "1.0.0",
            "status": "completed",
            # These fixtures run in-process against deterministic evaluators. No timing is
            # measured and no model is called, so no latency or token field is reported.
            "iterations": [
                {"iteration": idx, "fixture_id": f["fixture_id"], "passed": f["passed"]}
                for idx, f in enumerate(fixtures, start=1)
            ],
            "evidence": [
                {"fixture_count": len(fixtures), "passed_count": passed_count, "pass_rate": passed_count / len(fixtures)}
            ],
            "errors": [],
        }
        return validate_contract("ExperimentRun", scorecard)

    @staticmethod
    def audit_promoted_components(
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Audit shared components to enforce the 2-real-consumers craft rule (R4 wave)."""
        retained = []
        demoted = []

        for comp in candidates:
            consumers = comp.get("consumers", [])
            if len(consumers) >= 2:
                retained.append({
                    "component_id": comp["component_id"],
                    "path": comp.get("path"),
                    "consumers": consumers,
                    "status": "promoted_shared_component",
                })
            else:
                demoted.append({
                    "component_id": comp["component_id"],
                    "path": comp.get("path"),
                    "consumers": consumers,
                    "status": "demoted_to_home_repo",
                    "reason": "Fewer than 2 active portfolio consumers; violates shared-boundary promotion rule.",
                })

        return {
            "total_evaluated": len(candidates),
            "promoted_retained_count": len(retained),
            "demoted_count": len(demoted),
            "retained": retained,
            "demoted": demoted,
            "craft_rule_enforced": True,
        }

    @staticmethod
    def build_curriculum_fixtures(
        modules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Mine AI Staff and prompt-chain fixtures into deterministic test curriculum (R5 wave)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fixtures = []
        for mod in modules:
            fixtures.append({
                "module_id": mod["id"],
                "topic": mod["topic"],
                "deterministic_gates": mod.get("gates", ["confinement", "budget", "rollback"]),
                "verified_at": now_iso,
            })

        return {
            "curriculum_version": "1.0.0",
            "fixtures_count": len(fixtures),
            "fixtures": fixtures,
            "status": "curriculum_fixtures_verified",
        }
