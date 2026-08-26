"""Validate and resolve the dependency-aware portfolio recovery program.

The suite manifests remain authoritative for wave objectives, acceptance text,
runtime follow-ups, evidence paths, and current recovery claims.  The recovery
program is deliberately an overlay: it adds execution order, target evidence,
runtime environment, and owner gates without copying those wave fields into a
second source of truth.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .paths import SUITES_ROOT
from .recovery_policy import (
    RECOVERY_CLAIM_KINDS,
    RECOVERY_PROMOTION_LEVELS,
    RECOVERY_RECEIPT_CONTRACTS,
    RECOVERY_RESOLUTION_OUTCOMES,
    RECOVERY_TIERS,
)


RECOVERY_PROGRAM_PATH = SUITES_ROOT / "portfolio" / "recovery-program.json"
RECOVERY_PROGRAM_ID = "portfolio-runtime-recovery-v2"
RECOVERY_PROGRAM_SCHEMA_VERSION = "1.0.0"
OBLIGATION_SOURCES = frozenset({"wave_runtime_followup", "lifecycle"})
EXPECTED_POLICY = {
    "runtime_followup_coverage": "exactly_once",
    "dependency_cycles_allowed": False,
    "owner_gates_are_machine_satisfiable": False,
    "environment_blocker_is_pass": False,
    "recording_changes_claim_level": False,
    "minimum_authentic_uses_for_adoption": 3,
}
EXPECTED_RECEIPT_BY_TARGET = {
    ("runtime", "source_executed"): "portfolio-runtime-source-v1",
    ("runtime", "parity_verified"): "portfolio-runtime-parity-v1",
    ("adoption", "adopted"): "portfolio-adoption-v1",
    ("convergence", "converged"): "portfolio-convergence-v1",
    ("resolution", None): "portfolio-resolution-v1",
}
EXPECTED_STORED_STATES = frozenset({
    "planned",
    "assessing",
    "blocked_environment",
    "blocked_owner",
    "in_progress",
    "evidence_candidate",
    "accepted",
    "discharged",
})
EXPECTED_DERIVED_STATES = frozenset({"ready", "blocked_dependency"})
TRACE_MAPPING_RELATIONSHIPS = frozenset({
    "representedBy",
    "authoritativeFor",
    "derivedFrom",
    "fallbackTo",
})
TRACE_POLICY_OUTCOMES = frozenset({"allowed", "denied"})


class RecoveryProgramError(ValueError):
    """Raised when the recovery program cannot be loaded as a JSON object."""


def load_recovery_program(path: Path | None = None) -> dict[str, Any]:
    """Load a detached recovery-program document without consulting donor runtimes."""
    program_path = path or RECOVERY_PROGRAM_PATH
    try:
        document = json.loads(program_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryProgramError(
            f"recovery program cannot be loaded from {program_path}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise RecoveryProgramError("recovery program must be a JSON object")
    return copy.deepcopy(document)


def _tier_target(suite_id: str) -> float | None:
    for tier in RECOVERY_TIERS.values():
        if suite_id in tier["suites"]:
            return float(tier["target_score"])
    return None


def _wave_followups(suites: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        f"{suite_id}/{wave.get('id')}": wave
        for suite_id, manifest in suites.items()
        for wave in manifest.get("waves", [])
        if isinstance(wave, dict) and str(wave.get("runtime_followup") or "").strip()
    }


def _dependency_cycle(nodes: dict[str, dict[str, Any]]) -> list[str] | None:
    """Return one dependency cycle, if present, without recursing into donor data."""
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id in visiting:
            start = stack.index(node_id)
            return stack[start:] + [node_id]
        if node_id in visited:
            return None
        visiting.add(node_id)
        stack.append(node_id)
        for dependency in nodes[node_id].get("dependencies", []):
            if dependency in nodes:
                cycle = visit(dependency)
                if cycle:
                    return cycle
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for obligation_id in nodes:
        cycle = visit(obligation_id)
        if cycle:
            return cycle
    return None


def validate_recovery_program(
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> list[str]:
    """Return fail-closed structural and semantic errors for the execution overlay."""
    errors: list[str] = []
    if program.get("schema_version") != RECOVERY_PROGRAM_SCHEMA_VERSION:
        errors.append(
            f"recovery program schema_version must be {RECOVERY_PROGRAM_SCHEMA_VERSION!r}"
        )
    if program.get("program_id") != RECOVERY_PROGRAM_ID:
        errors.append(f"recovery program id must be {RECOVERY_PROGRAM_ID!r}")

    allowed_states = program.get("allowed_states")
    derived_states = program.get("derived_states")
    allowed_dispositions = program.get("allowed_dispositions")
    acceptance_vocabulary = program.get("acceptance_vocabulary")
    priority_order = program.get("priority_order")
    for label, value in (
        ("allowed_states", allowed_states),
        ("derived_states", derived_states),
        ("allowed_dispositions", allowed_dispositions),
        ("acceptance_vocabulary", acceptance_vocabulary),
        ("priority_order", priority_order),
    ):
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
            errors.append(f"recovery program {label} must be a non-empty list of strings")
        elif len(value) != len(set(value)):
            errors.append(f"recovery program {label} must not contain duplicates")
    if isinstance(allowed_states, list) and all(
        isinstance(item, str) for item in allowed_states
    ) and set(allowed_states) != EXPECTED_STORED_STATES:
        errors.append("recovery program stored states do not match recovery policy")
    if isinstance(derived_states, list) and all(
        isinstance(item, str) for item in derived_states
    ) and set(derived_states) != EXPECTED_DERIVED_STATES:
        errors.append("recovery program derived states do not match recovery policy")
    if (
        isinstance(allowed_states, list)
        and isinstance(derived_states, list)
        and all(isinstance(item, str) for item in allowed_states + derived_states)
        and set(allowed_states).intersection(derived_states)
    ):
        errors.append("recovery program stored and derived states must be disjoint")
    if (
        isinstance(allowed_dispositions, list)
        and all(isinstance(item, str) for item in allowed_dispositions)
        and set(allowed_dispositions) != set(RECOVERY_RESOLUTION_OUTCOMES)
    ):
        errors.append("recovery program dispositions do not match recovery policy")
    if program.get("policy") != EXPECTED_POLICY:
        errors.append("recovery program policy does not match fail-closed execution policy")

    journeys = program.get("journeys")
    journey_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(journeys, list):
        errors.append("recovery program journeys must be a list")
        journeys = []
    for index, journey in enumerate(journeys):
        if not isinstance(journey, dict):
            errors.append(f"recovery journey {index} must be an object")
            continue
        journey_id = journey.get("id")
        suite_id = journey.get("suite_id")
        if not isinstance(journey_id, str) or not journey_id:
            errors.append(f"recovery journey {index} needs a non-empty id")
            continue
        if journey_id in journey_by_id:
            errors.append(f"duplicate recovery journey id: {journey_id}")
            continue
        journey_by_id[journey_id] = journey
        manifest = suites.get(suite_id) if isinstance(suite_id, str) else None
        if manifest is None:
            errors.append(f"{journey_id}: unknown suite_id {suite_id!r}")
            continue
        concepts = journey.get("business_concepts")
        authorities = journey.get("technical_authorities")
        contracts = journey.get("contracts")
        if not isinstance(concepts, list) or not concepts or any(not isinstance(item, str) or not item for item in concepts):
            errors.append(f"{journey_id}: business_concepts must be a non-empty string list")
        if not isinstance(authorities, list) or not authorities or any(not isinstance(item, str) or not item for item in authorities):
            errors.append(f"{journey_id}: technical_authorities must be a non-empty string list")
        if not isinstance(contracts, list) or any(not isinstance(item, str) or not item for item in contracts):
            errors.append(f"{journey_id}: contracts must be a string list")
        elif not set(contracts).issubset(set(manifest.get("contracts", []))):
            errors.append(f"{journey_id}: contracts must be declared by suite {suite_id}")
        expected_target = _tier_target(suite_id)
        if expected_target is None or journey.get("recovery_target") != expected_target:
            errors.append(f"{journey_id}: recovery_target must match suite tier target {expected_target}")
    journey_suite_counts = Counter(
        journey.get("suite_id")
        for journey in journeys
        if isinstance(journey, dict) and isinstance(journey.get("suite_id"), str)
    )
    if journey_suite_counts != Counter({suite_id: 1 for suite_id in suites}):
        errors.append("recovery journeys must cover every suite exactly once")

    obligations = program.get("obligations")
    obligation_by_id: dict[str, dict[str, Any]] = {}
    sequences: set[int] = set()
    trace_route_owners: dict[tuple[str, str], str] = {}
    if not isinstance(obligations, list):
        errors.append("recovery program obligations must be a list")
        obligations = []
    for index, obligation in enumerate(obligations):
        if not isinstance(obligation, dict):
            errors.append(f"recovery obligation {index} must be an object")
            continue
        obligation_id = obligation.get("id")
        if not isinstance(obligation_id, str) or not obligation_id:
            errors.append(f"recovery obligation {index} needs a non-empty id")
            continue
        if obligation_id in obligation_by_id:
            errors.append(f"duplicate recovery obligation id: {obligation_id}")
            continue
        obligation_by_id[obligation_id] = obligation
        source = obligation.get("source")
        if not isinstance(source, str) or source not in OBLIGATION_SOURCES:
            errors.append(f"{obligation_id}: unknown obligation source {source!r}")
        obligation_journey_id = obligation.get("journey_id")
        journey = (
            journey_by_id.get(obligation_journey_id)
            if isinstance(obligation_journey_id, str)
            else None
        )
        if journey is None:
            errors.append(f"{obligation_id}: unknown journey_id {obligation_journey_id!r}")
        elif not obligation_id.startswith(f"{journey['suite_id']}/"):
            errors.append(f"{obligation_id}: obligation suite does not match its journey")
        if obligation.get("state") not in (allowed_states if isinstance(allowed_states, list) else []):
            errors.append(f"{obligation_id}: invalid state {obligation.get('state')!r}")
        if obligation.get("priority") not in (priority_order if isinstance(priority_order, list) else []):
            errors.append(f"{obligation_id}: invalid priority {obligation.get('priority')!r}")
        sequence = obligation.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            errors.append(f"{obligation_id}: sequence must be a positive integer")
        elif sequence in sequences:
            errors.append(f"{obligation_id}: duplicate sequence {sequence}")
        else:
            sequences.add(sequence)
        claim_kind = obligation.get("target_claim_kind")
        target_level = obligation.get("target_level")
        valid_claim_kind = (
            isinstance(claim_kind, str) and claim_kind in RECOVERY_CLAIM_KINDS
        )
        valid_target_level = target_level is None or (
            isinstance(target_level, str)
            and target_level in RECOVERY_PROMOTION_LEVELS
        )
        if not valid_claim_kind:
            errors.append(f"{obligation_id}: invalid target_claim_kind {claim_kind!r}")
        if not valid_target_level:
            errors.append(f"{obligation_id}: invalid target_level {target_level!r}")
        expected_receipt = (
            EXPECTED_RECEIPT_BY_TARGET.get((claim_kind, target_level))
            if valid_claim_kind and valid_target_level
            else None
        )
        if expected_receipt is None:
            errors.append(
                f"{obligation_id}: unsupported target claim {claim_kind!r}/{target_level!r}"
            )
        elif obligation.get("receipt_contract") != expected_receipt:
            errors.append(f"{obligation_id}: receipt_contract must be {expected_receipt!r}")
        receipt_contract = obligation.get("receipt_contract")
        if (
            not isinstance(receipt_contract, str)
            or receipt_contract not in RECOVERY_RECEIPT_CONTRACTS
        ):
            errors.append(f"{obligation_id}: receipt_contract is not governed")
        dependencies = obligation.get("dependencies")
        if not isinstance(dependencies, list) or any(not isinstance(item, str) or not item for item in dependencies):
            errors.append(f"{obligation_id}: dependencies must be a string list")
        elif len(dependencies) != len(set(dependencies)):
            errors.append(f"{obligation_id}: dependencies must not contain duplicates")
        elif obligation_id in dependencies:
            errors.append(f"{obligation_id}: obligation cannot depend on itself")
        checks = obligation.get("acceptance_checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"{obligation_id}: acceptance_checks must be a non-empty list")
        elif any(check not in (acceptance_vocabulary if isinstance(acceptance_vocabulary, list) else []) for check in checks):
            errors.append(f"{obligation_id}: acceptance_checks contain unknown vocabulary")
        runtime_environment = obligation.get("runtime_environment")
        if not isinstance(runtime_environment, str) or not runtime_environment:
            errors.append(f"{obligation_id}: runtime_environment must be a non-empty string")
        owner_gate = obligation.get("owner_gate")
        if owner_gate is not None and (not isinstance(owner_gate, str) or not owner_gate):
            errors.append(f"{obligation_id}: owner_gate must be null or a non-empty string")

        trace_route = obligation.get("trace_route")
        if trace_route is not None:
            if not isinstance(trace_route, dict):
                errors.append(f"{obligation_id}: trace_route must be an object")
                continue
            adapter = trace_route.get("adapter")
            action = trace_route.get("action")
            for field, value in (
                ("adapter", adapter),
                ("action", action),
                ("ontology_version", trace_route.get("ontology_version")),
                ("mapping_version", trace_route.get("mapping_version")),
            ):
                if not isinstance(value, str) or not value:
                    errors.append(
                        f"{obligation_id}: trace_route {field} must be a non-empty string"
                    )
            if isinstance(adapter, str) and adapter and isinstance(action, str) and action:
                route_key = (adapter, action)
                if route_key in trace_route_owners:
                    errors.append(
                        f"{obligation_id}: trace_route duplicates {trace_route_owners[route_key]}"
                    )
                else:
                    trace_route_owners[route_key] = obligation_id

            journey_concepts = (
                set(journey.get("business_concepts", []))
                if journey is not None
                and isinstance(journey.get("business_concepts"), list)
                and all(isinstance(item, str) for item in journey["business_concepts"])
                else set()
            )
            journey_authorities = (
                set(journey.get("technical_authorities", []))
                if journey is not None
                and isinstance(journey.get("technical_authorities"), list)
                and all(isinstance(item, str) for item in journey["technical_authorities"])
                else set()
            )
            mappings = trace_route.get("resolved_mappings")
            if not isinstance(mappings, list) or not mappings:
                errors.append(
                    f"{obligation_id}: trace_route resolved_mappings must be a non-empty list"
                )
            else:
                for mapping_index, mapping in enumerate(mappings):
                    if not isinstance(mapping, dict):
                        errors.append(
                            f"{obligation_id}: trace_route mapping {mapping_index} must be an object"
                        )
                        continue
                    concept = mapping.get("concept")
                    relationship = mapping.get("relationship")
                    authority = mapping.get("authority")
                    if not isinstance(concept, str) or concept not in journey_concepts:
                        errors.append(
                            f"{obligation_id}: trace_route mapping {mapping_index} has unknown concept {concept!r}"
                        )
                    if (
                        not isinstance(relationship, str)
                        or relationship not in TRACE_MAPPING_RELATIONSHIPS
                    ):
                        errors.append(
                            f"{obligation_id}: trace_route mapping {mapping_index} has unknown relationship {relationship!r}"
                        )
                    if not isinstance(authority, str) or authority not in journey_authorities:
                        errors.append(
                            f"{obligation_id}: trace_route mapping {mapping_index} has unknown authority {authority!r}"
                        )

            candidate_authorities = trace_route.get("candidate_authorities")
            valid_candidates = (
                isinstance(candidate_authorities, list)
                and bool(candidate_authorities)
                and all(
                    isinstance(item, str) and bool(item)
                    for item in candidate_authorities
                )
            )
            if not valid_candidates:
                errors.append(
                    f"{obligation_id}: trace_route candidate_authorities must be a non-empty string list"
                )
                candidate_set: set[str] = set()
            else:
                candidate_set = set(candidate_authorities)
                if len(candidate_set) != len(candidate_authorities):
                    errors.append(
                        f"{obligation_id}: trace_route candidate_authorities must not contain duplicates"
                    )
                if not candidate_set.issubset(journey_authorities):
                    errors.append(
                        f"{obligation_id}: trace_route candidate_authorities must belong to its journey"
                    )
            selected_authority = trace_route.get("selected_authority")
            if (
                not isinstance(selected_authority, str)
                or selected_authority not in candidate_set
            ):
                errors.append(
                    f"{obligation_id}: trace_route selected_authority must be a candidate authority"
                )

            policy_decisions = trace_route.get("policy_decisions")
            if not isinstance(policy_decisions, list) or not policy_decisions:
                errors.append(
                    f"{obligation_id}: trace_route policy_decisions must be a non-empty list"
                )
            else:
                for decision_index, decision in enumerate(policy_decisions):
                    if not isinstance(decision, dict):
                        errors.append(
                            f"{obligation_id}: trace_route policy decision {decision_index} must be an object"
                        )
                        continue
                    for field in ("policy_id", "reason_code"):
                        value = decision.get(field)
                        if not isinstance(value, str) or not value:
                            errors.append(
                                f"{obligation_id}: trace_route policy decision {decision_index} {field} must be a non-empty string"
                            )
                    outcome = decision.get("outcome")
                    if not isinstance(outcome, str) or outcome not in TRACE_POLICY_OUTCOMES:
                        errors.append(
                            f"{obligation_id}: trace_route policy decision {decision_index} has unknown outcome {outcome!r}"
                        )

    for obligation_id, obligation in obligation_by_id.items():
        dependencies = obligation.get("dependencies")
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if not isinstance(dependency, str):
                continue
            if dependency not in obligation_by_id:
                errors.append(f"{obligation_id}: unknown dependency {dependency}")
    cycle_nodes = {
        obligation_id: {
            "dependencies": [
                dependency
                for dependency in obligation.get("dependencies", [])
                if isinstance(dependency, str)
            ]
            if isinstance(obligation.get("dependencies"), list)
            else []
        }
        for obligation_id, obligation in obligation_by_id.items()
    }
    cycle = _dependency_cycle(cycle_nodes)
    if cycle:
        errors.append(f"recovery obligation dependency cycle: {' -> '.join(cycle)}")

    # The resolver reports such an obligation as blocked_dependency, which reads exactly like
    # work that never started. The contradiction is in the program, so it is named here rather
    # than smoothed over in the derived state.
    for obligation_id, obligation in obligation_by_id.items():
        if obligation.get("state") != "discharged":
            continue
        undischarged = sorted(
            dependency
            for dependency in cycle_nodes[obligation_id]["dependencies"]
            if obligation_by_id.get(dependency, {}).get("state") != "discharged"
        )
        if undischarged:
            errors.append(
                f"{obligation_id}: discharged obligation depends on undischarged "
                f"{', '.join(undischarged)}"
            )

    wave_followups = _wave_followups(suites)
    covered_followups = {
        obligation_id
        for obligation_id, obligation in obligation_by_id.items()
        if obligation.get("source") == "wave_runtime_followup"
    }
    missing = sorted(set(wave_followups) - covered_followups)
    extra = sorted(covered_followups - set(wave_followups))
    if missing:
        errors.append(f"recovery program does not cover runtime follow-up(s): {', '.join(missing)}")
    if extra:
        errors.append(f"recovery program has non-follow-up wave obligation(s): {', '.join(extra)}")
    for obligation_id, obligation in obligation_by_id.items():
        if obligation.get("source") != "lifecycle":
            continue
        suite_id, _, lifecycle_id = obligation_id.partition("/")
        if suite_id not in suites or not lifecycle_id:
            errors.append(f"{obligation_id}: malformed lifecycle obligation id")
        if obligation.get("target_claim_kind") != "adoption":
            errors.append(f"{obligation_id}: only adoption lifecycle obligations are supported")

    return errors


def get_recovery_trace_context(
    program: dict[str, Any],
    *,
    adapter: str,
    action: str,
) -> dict[str, Any]:
    """Return the one governed obligation and route owned by an adapter action."""
    if not isinstance(program, dict):
        raise RecoveryProgramError("recovery program must be a JSON object")
    obligations = program.get("obligations")
    journeys = program.get("journeys")
    if not isinstance(obligations, list) or not isinstance(journeys, list):
        raise RecoveryProgramError(
            "recovery program journeys and obligations must be lists"
        )
    matches = [
        obligation
        for obligation in obligations
        if isinstance(obligation, dict)
        and isinstance(obligation.get("trace_route"), dict)
        and obligation["trace_route"].get("adapter") == adapter
        and obligation["trace_route"].get("action") == action
    ]
    if len(matches) != 1:
        raise RecoveryProgramError(
            f"expected exactly one recovery trace route for {adapter}.{action}; "
            f"found {len(matches)}"
        )
    obligation = matches[0]
    journey_id = obligation.get("journey_id")
    journey_matches = [
        journey
        for journey in journeys
        if isinstance(journey, dict) and journey.get("id") == journey_id
    ]
    if len(journey_matches) != 1:
        raise RecoveryProgramError(
            f"expected exactly one recovery journey for {journey_id!r}; "
            f"found {len(journey_matches)}"
        )
    return {
        "obligation_id": obligation.get("id"),
        "journey_id": journey_id,
        "owner_gate": obligation.get("owner_gate"),
        "receipt_contract": obligation.get("receipt_contract"),
        "trace_route": copy.deepcopy(obligation["trace_route"]),
    }


def resolve_recovery_obligations(
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join obligations to authoritative waves and derive dependency readiness."""
    errors = validate_recovery_program(program, suites)
    if errors:
        raise RecoveryProgramError("; ".join(errors))
    waves = {
        f"{suite_id}/{wave['id']}": wave
        for suite_id, manifest in suites.items()
        for wave in manifest.get("waves", [])
        if isinstance(wave, dict) and isinstance(wave.get("id"), str)
    }
    obligations = {
        obligation["id"]: copy.deepcopy(obligation)
        for obligation in program["obligations"]
    }
    priority_rank = {
        priority: index for index, priority in enumerate(program["priority_order"])
    }
    resolved: list[dict[str, Any]] = []
    for obligation_id, obligation in obligations.items():
        dependency_states = {
            dependency: obligations[dependency]["state"]
            for dependency in obligation["dependencies"]
        }
        dependencies_satisfied = all(
            state == "discharged" for state in dependency_states.values()
        )
        stored_state = obligation["state"]
        if not dependencies_satisfied:
            effective_state = "blocked_dependency"
        elif stored_state == "planned":
            effective_state = "ready"
        else:
            effective_state = stored_state
        wave = waves.get(obligation_id)
        joined = {
            **obligation,
            "effective_state": effective_state,
            "dependencies_satisfied": dependencies_satisfied,
            "dependency_states": dependency_states,
            "priority_rank": priority_rank[obligation["priority"]],
        }
        if wave is not None:
            joined.update({
                "suite_id": obligation_id.split("/", 1)[0],
                "wave_id": wave["id"],
                "objective": wave.get("objective"),
                "acceptance": wave.get("acceptance"),
                "runtime_followup": wave.get("runtime_followup"),
                "current_claim": copy.deepcopy(wave.get("recovery_claim")),
                "evidence": wave.get("evidence"),
            })
        else:
            joined.update({
                "suite_id": obligation_id.split("/", 1)[0],
                "wave_id": None,
                "objective": "Carry the existing parity-verified behavior through authentic adoption.",
                "acceptance": "At least three authentic accepted uses across distinct inputs or days, with recovery and privacy boundaries retained.",
                "runtime_followup": None,
                "current_claim": None,
                "evidence": None,
            })
        resolved.append(joined)
    return sorted(
        resolved,
        key=lambda item: (item["priority_rank"], item["sequence"], item["id"]),
    )


def recovery_program_summary(
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return exact program counts without inferring runtime or owner availability."""
    obligations = resolve_recovery_obligations(program, suites)
    states: dict[str, int] = {}
    for obligation in obligations:
        state = obligation["effective_state"]
        states[state] = states.get(state, 0) + 1
    return {
        "program_id": program["program_id"],
        "journeys": len(program["journeys"]),
        "obligations": len(obligations),
        "wave_runtime_followups": sum(
            obligation["source"] == "wave_runtime_followup"
            for obligation in obligations
        ),
        "lifecycle_obligations": sum(
            obligation["source"] == "lifecycle" for obligation in obligations
        ),
        "states": states,
        "ready": [
            obligation["id"]
            for obligation in obligations
            if obligation["effective_state"] == "ready"
        ],
    }
