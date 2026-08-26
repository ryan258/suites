"""Validate redacted semantic-routing traces for recovery executions."""

from __future__ import annotations

import copy
import datetime
import json
import re
import uuid
from pathlib import Path
from typing import Any

from .paths import SUITES_ROOT
from .provenance import is_meaningful_git_fingerprint


EXECUTION_TRACE_CONTRACT_PATH = (
    SUITES_ROOT / "portfolio" / "execution-trace-contract.json"
)
EXECUTION_TRACE_VERSION = "portfolio-execution-trace-v1"
EXECUTION_TRACE_SCHEMA_VERSION = "1.0.0"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ExecutionTraceError(ValueError):
    """Raised when the execution-trace contract cannot be loaded."""


def load_execution_trace_contract(path: Path | None = None) -> dict[str, Any]:
    """Load the trace contract without consulting a donor or adapter."""
    contract_path = path or EXECUTION_TRACE_CONTRACT_PATH
    try:
        document = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExecutionTraceError(
            f"execution trace contract cannot be loaded from {contract_path}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise ExecutionTraceError("execution trace contract must be a JSON object")
    return copy.deepcopy(document)


def validate_execution_trace_contract(contract: dict[str, Any]) -> list[str]:
    """Return errors in the static contract itself."""
    errors: list[str] = []
    if contract.get("schema_version") != EXECUTION_TRACE_SCHEMA_VERSION:
        errors.append(
            f"execution trace schema_version must be {EXECUTION_TRACE_SCHEMA_VERSION!r}"
        )
    if contract.get("contract_id") != EXECUTION_TRACE_VERSION:
        errors.append(f"execution trace contract_id must be {EXECUTION_TRACE_VERSION!r}")
    for field in (
        "required_fields",
        "mapping_relationships",
        "policy_outcomes",
        "execution_outcomes",
        "forbidden_payload_keys",
    ):
        value = contract.get(field)
        if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item for item in value
        ):
            errors.append(f"execution trace {field} must be a non-empty string list")
        elif len(value) != len(set(value)):
            errors.append(f"execution trace {field} must not contain duplicates")
    expected_policy = {
        "source_authority_is_hard_constraint": True,
        "fallback_requires_explicit_mapping": True,
        "unmapped_or_ambiguous_fails_closed": True,
        "credentials_belong_to_adapters": True,
        "raw_source_payloads_retained": False,
        "receipt_recording_requires_explicit_request": True,
    }
    if contract.get("policy") != expected_policy:
        errors.append("execution trace policy must preserve the fail-closed privacy boundary")
    return errors


def _timezone_aware(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _forbidden_key_paths(value: Any, forbidden: set[str], path: str = "$") -> list[str]:
    """Report every path whose *key* is a forbidden payload name.

    ponytail: key-name scan only, no value inspection. It holds because a trace is
    redacted by construction -- the control plane assembles it from governed route
    fields and fingerprints, never from donor payloads -- so a secret can only arrive
    under a name this catches. If a trace ever carries free text an adapter composed,
    that assumption dies and this needs a value-side scan to keep `privacy.redacted`
    honest.
    """
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in forbidden:
                found.append(child_path)
            found.extend(_forbidden_key_paths(child, forbidden, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_key_paths(child, forbidden, f"{path}[{index}]"))
    return found


def validate_execution_trace(
    trace: dict[str, Any],
    program: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> list[str]:
    """Validate one trace against the governed recovery program and authority map."""
    active_contract = contract or load_execution_trace_contract()
    errors = validate_execution_trace_contract(active_contract)
    if not isinstance(trace, dict):
        return errors + ["execution trace must be an object"]
    if not isinstance(program, dict):
        return errors + ["recovery program must be an object"]

    required_value = active_contract.get("required_fields", [])
    required = (
        required_value
        if isinstance(required_value, list)
        and all(isinstance(field, str) for field in required_value)
        else []
    )
    missing = [field for field in required if field not in trace]
    if missing:
        errors.append(f"execution trace missing required field(s): {', '.join(missing)}")
    if trace.get("trace_version") != EXECUTION_TRACE_VERSION:
        errors.append(f"trace_version must be {EXECUTION_TRACE_VERSION!r}")
    for field in ("trace_id", "request_id"):
        try:
            uuid.UUID(str(trace.get(field)))
        except (ValueError, AttributeError):
            errors.append(f"{field} must be a UUID")

    journey_values = program.get("journeys")
    if not isinstance(journey_values, list):
        errors.append("recovery program journeys must be a list")
        journey_values = []
    obligation_values = program.get("obligations")
    if not isinstance(obligation_values, list):
        errors.append("recovery program obligations must be a list")
        obligation_values = []
    journeys = {
        journey["id"]: journey
        for journey in journey_values
        if isinstance(journey, dict) and isinstance(journey.get("id"), str)
    }
    obligations = {
        obligation["id"]: obligation
        for obligation in obligation_values
        if isinstance(obligation, dict) and isinstance(obligation.get("id"), str)
    }
    obligation_id = trace.get("obligation_id")
    journey_id = trace.get("journey_id")
    obligation = (
        obligations.get(obligation_id) if isinstance(obligation_id, str) else None
    )
    journey = journeys.get(journey_id) if isinstance(journey_id, str) else None
    if obligation is None:
        errors.append("obligation_id must identify a governed recovery obligation")
    if journey is None:
        errors.append("journey_id must identify a governed recovery journey")
    if obligation is not None and trace.get("journey_id") != obligation.get("journey_id"):
        errors.append("trace journey_id must match the obligation journey")
    route = obligation.get("trace_route") if isinstance(obligation, dict) else None
    if not isinstance(route, dict):
        route = None

    journey_concepts = journey.get("business_concepts") if journey else None
    if journey is not None and (
        not isinstance(journey_concepts, list)
        or not journey_concepts
        or any(not isinstance(item, str) or not item for item in journey_concepts)
    ):
        errors.append("governed journey business_concepts must be a non-empty string list")
        concepts: set[str] = set()
    else:
        concepts = set(journey_concepts or [])
    journey_authorities = journey.get("technical_authorities") if journey else None
    if journey is not None and (
        not isinstance(journey_authorities, list)
        or not journey_authorities
        or any(not isinstance(item, str) or not item for item in journey_authorities)
    ):
        errors.append(
            "governed journey technical_authorities must be a non-empty string list"
        )
        authorities: set[str] = set()
    else:
        authorities = set(journey_authorities or [])
    mapping_relationships_value = active_contract.get("mapping_relationships", [])
    mapping_relationships = (
        set(mapping_relationships_value)
        if isinstance(mapping_relationships_value, list)
        and all(isinstance(item, str) for item in mapping_relationships_value)
        else set()
    )
    mappings = trace.get("resolved_mappings")
    mapped_concepts: set[str] = set()
    has_fallback_mapping = False
    if not isinstance(mappings, list) or not mappings:
        errors.append("resolved_mappings must be a non-empty list")
        mappings = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append(f"resolved_mappings.{index} must be an object")
            continue
        concept = mapping.get("concept")
        authority = mapping.get("authority")
        relationship = mapping.get("relationship")
        if not isinstance(concept, str) or concept not in concepts:
            errors.append(f"resolved_mappings.{index}.concept is not in the journey ontology")
        else:
            mapped_concepts.add(concept)
        if not isinstance(authority, str) or authority not in authorities:
            errors.append(f"resolved_mappings.{index}.authority is not governed for the journey")
        if not isinstance(relationship, str) or relationship not in mapping_relationships:
            errors.append(f"resolved_mappings.{index}.relationship is not governed")
        has_fallback_mapping = has_fallback_mapping or relationship == "fallbackTo"
    if concepts and not mapped_concepts:
        errors.append("trace must resolve at least one governed business concept")

    candidates_value = trace.get("candidate_authorities")
    valid_candidates = (
        isinstance(candidates_value, list)
        and bool(candidates_value)
        and all(
            isinstance(candidate, str) and candidate in authorities
            for candidate in candidates_value
        )
    )
    if not valid_candidates:
        errors.append("candidate_authorities must be a non-empty governed authority list")
    candidates = candidates_value if valid_candidates else []
    selected = trace.get("selected_authority")
    outcome = trace.get("outcome")
    unresolved_outcomes = {"denied", "unmapped", "ambiguous"}
    # A block that fires before routing has no authority to name. Requiring one here would
    # make the honest trace invalid and reward naming an authority that was never selected.
    preselection_block_outcomes = {"blocked_environment", "blocked_owner"}
    execution_outcomes_value = active_contract.get("execution_outcomes", [])
    execution_outcomes = (
        set(execution_outcomes_value)
        if isinstance(execution_outcomes_value, list)
        and all(isinstance(item, str) for item in execution_outcomes_value)
        else set()
    )
    if not isinstance(outcome, str) or outcome not in execution_outcomes:
        errors.append("outcome is not governed")
    if isinstance(outcome, str) and outcome in unresolved_outcomes:
        if selected is not None:
            errors.append("denied, unmapped, or ambiguous traces cannot select an authority")
    elif selected is None:
        if not (isinstance(outcome, str) and outcome in preselection_block_outcomes):
            errors.append(
                "selected_authority must be one of the eligible candidate authorities"
            )
    elif valid_candidates and selected not in candidates:
        errors.append("selected_authority must be one of the eligible candidate authorities")

    if route is not None:
        for field in ("adapter", "ontology_version", "mapping_version"):
            if trace.get(field) != route.get(field):
                errors.append(f"{field} must match the governed trace route")
        if trace.get("resolved_mappings") != route.get("resolved_mappings"):
            errors.append("resolved_mappings must match the governed trace route")
        if candidates_value != route.get("candidate_authorities"):
            errors.append("candidate_authorities must match the governed trace route")
        # Policy decisions are runtime outcomes, not a copy of the route: a denied decision
        # the static route never planned is exactly what a trace exists to record.
        if selected is not None and selected != route.get("selected_authority"):
            errors.append("selected_authority must match the governed trace route")

    decisions = trace.get("policy_decisions")
    denied = False
    policy_outcomes_value = active_contract.get("policy_outcomes", [])
    policy_outcomes = (
        set(policy_outcomes_value)
        if isinstance(policy_outcomes_value, list)
        and all(isinstance(item, str) for item in policy_outcomes_value)
        else set()
    )
    if not isinstance(decisions, list) or not decisions:
        errors.append("policy_decisions must be a non-empty list")
        decisions = []
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            errors.append(f"policy_decisions.{index} must be an object")
            continue
        for field in ("policy_id", "reason_code"):
            value = decision.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"policy_decisions.{index}.{field} must be non-empty")
        decision_outcome = decision.get("outcome")
        if (
            not isinstance(decision_outcome, str)
            or decision_outcome not in policy_outcomes
        ):
            errors.append(f"policy_decisions.{index}.outcome is not governed")
        denied = denied or decision_outcome == "denied"
    if denied and outcome != "denied":
        errors.append("a denied policy decision must produce a denied execution outcome")

    if not isinstance(trace.get("adapter"), str) or not trace.get("adapter"):
        errors.append("adapter must be non-empty")
    if not isinstance(trace.get("plan_sha256"), str) or not SHA256_HEX.fullmatch(
        trace.get("plan_sha256", "")
    ):
        errors.append("plan_sha256 must be a lowercase SHA-256")
    fingerprints = trace.get("source_fingerprints")
    if not isinstance(fingerprints, dict) or not fingerprints or any(
        not is_meaningful_git_fingerprint(value) for value in fingerprints.values()
    ):
        errors.append("source_fingerprints must contain meaningful Git fingerprints")

    started = _timezone_aware(trace.get("started_at"))
    finished = _timezone_aware(trace.get("finished_at"))
    if started is None:
        errors.append("started_at must be a timezone-aware date-time")
    if finished is None:
        errors.append("finished_at must be a timezone-aware date-time")
    if started is not None and finished is not None and finished < started:
        errors.append("finished_at cannot precede started_at")
    error_class = trace.get("error_class")
    if outcome == "passed" and error_class is not None:
        errors.append("a passed trace cannot retain an error_class")
    if outcome not in (None, "passed") and (
        not isinstance(error_class, str) or not error_class
    ):
        errors.append("a non-passing trace must retain an error_class")
    if not isinstance(trace.get("fallback_used"), bool):
        errors.append("fallback_used must be boolean")
    elif trace["fallback_used"] and not has_fallback_mapping:
        errors.append("fallback_used requires an explicit fallbackTo mapping")
    receipt_ref = trace.get("receipt_ref")
    if receipt_ref is not None and (
        not isinstance(receipt_ref, str) or not receipt_ref.strip()
    ):
        errors.append("receipt_ref must be null or a non-empty reference")
    privacy = trace.get("privacy")
    if privacy != {
        "redacted": True,
        "raw_source_retained": False,
        "secrets_retained": False,
    }:
        errors.append("privacy must prove redaction and absence of raw source and secrets")

    forbidden_keys_value = active_contract.get("forbidden_payload_keys", [])
    forbidden_keys = (
        {item.lower() for item in forbidden_keys_value}
        if isinstance(forbidden_keys_value, list)
        and all(isinstance(item, str) for item in forbidden_keys_value)
        else set()
    )
    forbidden_paths = _forbidden_key_paths(trace, forbidden_keys)
    if forbidden_paths:
        errors.append(
            "execution trace contains forbidden payload key(s): "
            + ", ".join(forbidden_paths)
        )
    return errors
