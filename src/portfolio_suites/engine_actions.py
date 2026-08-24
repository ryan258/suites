"""Reviewed, JSON-safe engine action surface for CLI, HTTP, and action chains.

Engine classes contain both public product capabilities and implementation helpers. Adding a
method to a class must not silently create a remotely invocable action, so this module keeps an
explicit action-level registry. Every result crosses one strict JSON boundary before a caller
sees it, and contract-labelled results are validated against their published contract.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ContractError, validate_contract
from .engines import ENGINES


class EngineActionError(ValueError):
    """Unknown/unregistered action or invalid public-boundary input/output."""


REDACTED_ARGUMENT = "[REDACTED: supply a new one-time secret]"
SENSITIVE_ARGUMENT_KEY_PATTERN = (
    r"(?:api[_-]?key|(?:access|approval|auth|bearer|refresh|id)[_-]?token|"
    r"authorization|bearer|credentials?|password|secrets?|^token$)"
)
_SENSITIVE_ARGUMENT_KEY = re.compile(SENSITIVE_ARGUMENT_KEY_PATTERN, re.IGNORECASE)


def argument_redaction_policy() -> dict[str, str]:
    """Return the credential-key policy consumed by the browser Toolbench."""
    return {
        "pattern": SENSITIVE_ARGUMENT_KEY_PATTERN,
        "flags": "i",
        "redacted_value": REDACTED_ARGUMENT,
    }


def redact_sensitive_arguments(value: Any) -> Any:
    """Return a detached copy with credential-shaped argument values replaced."""
    if isinstance(value, dict):
        return {
            key: REDACTED_ARGUMENT if _SENSITIVE_ARGUMENT_KEY.search(key) else redact_sensitive_arguments(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_arguments(child) for child in value]
    if isinstance(value, tuple):
        return [redact_sensitive_arguments(child) for child in value]
    return value


@dataclass(frozen=True)
class ActionSpec:
    """The reviewed policy for one exposed action.

    The four policy fields have no defaults on purpose. A defaulted ``read_only`` /
    ``approval_required=False`` / ``replayable=True`` bundle is how an action that can
    consume a one-time approval token ends up advertised as replayable: the default reads
    as a reviewed decision when it is only an absence of one. Every spec states its policy
    through one of the factories below (or passes all four fields itself), so what the
    catalog claims about authority is always something somebody wrote.

    ``authority_use`` says how the action relates to operator authority:
    - ``"none"`` -- the action never touches an approval token.
    - ``"parameter_dependent"`` -- the action consumes a single-use token when its
      arguments supply one, so static metadata carries the conservative bound while
      :func:`effective_policy` derives the truth from validated arguments at preflight.
    """

    output_kind: str
    side_effect_class: str
    approval_required: bool
    evidence_eligible: bool
    replayable: bool
    contract: str | None = None
    execution_tier: str = "reference_prototype"
    authority_use: str = "none"
    input_adapter: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    output_adapter: Callable[[Any], Any] | None = None


def read_only_action(output_kind: str, contract: str | None = None, **overrides: Any) -> ActionSpec:
    """A pure computation: no state change, no authority, deterministically replayable."""
    policy = {
        "side_effect_class": "read_only",
        "approval_required": False,
        "evidence_eligible": True,
        "replayable": True,
    }
    policy.update(overrides)
    return ActionSpec(output_kind=output_kind, contract=contract, **policy)


def simulated_action(output_kind: str, contract: str | None = None, **overrides: Any) -> ActionSpec:
    """Builds or advances suite-local in-memory artifacts; nothing external is touched."""
    policy = {
        "side_effect_class": "in_memory_mutation",
        "approval_required": False,
        "evidence_eligible": True,
        "replayable": True,
    }
    policy.update(overrides)
    return ActionSpec(output_kind=output_kind, contract=contract, **policy)


def authorized_action(output_kind: str, contract: str | None = None, **overrides: Any) -> ActionSpec:
    """Filesystem mutation gated by a one-time token in arguments; never safely replayable."""
    policy = {
        "side_effect_class": "filesystem_mutation",
        "approval_required": True,
        "evidence_eligible": True,
        "replayable": False,
        "authority_use": "parameter_dependent",
    }
    policy.update(overrides)
    return ActionSpec(output_kind=output_kind, contract=contract, **policy)


def parameter_dependent_action(output_kind: str, contract: str | None = None, **overrides: Any) -> ActionSpec:
    """Simulated without a token; consumes single-use authority when arguments supply one.

    The static metadata here is the conservative bound -- it advertises that the action
    *can* consume authority and therefore must not be replayed -- while
    :func:`effective_policy` derives the invocation-specific truth during preflight.
    """
    policy = {
        "side_effect_class": "in_memory_mutation",
        "approval_required": True,
        "evidence_eligible": True,
        "replayable": False,
        "authority_use": "parameter_dependent",
    }
    policy.update(overrides)
    return ActionSpec(output_kind=output_kind, contract=contract, **policy)


# Argument names that carry a one-time approval token. Presence of a non-empty value under
# any of these keys is what turns a parameter-dependent invocation into an authority-
# consuming one.
AUTHORITY_TOKEN_ARGUMENTS = frozenset({"operator_approval_token"})


def invocation_consumes_authority(arguments: dict[str, Any]) -> bool:
    """Whether validated arguments supply a live one-time approval token."""
    return any(
        isinstance(arguments.get(name), str) and arguments[name].strip()
        for name in AUTHORITY_TOKEN_ARGUMENTS
    )


def effective_policy(spec: ActionSpec, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """The policy that actually governs one invocation, derived from validated arguments.

    Static action-level metadata cannot represent parameter-dependent authority: the same
    brand-intake call is a simulated fixture without a token and a single-use authority
    consumption with one. Chains and any future replay surface must consult this, not the
    catalog, when deciding whether an invocation may be repeated.
    """
    policy = {
        "side_effect_class": spec.side_effect_class,
        "approval_required": spec.approval_required,
        "evidence_eligible": spec.evidence_eligible,
        "replayable": spec.replayable,
        "authority_use": spec.authority_use,
        "authority_consumed": False,
    }
    if spec.authority_use == "parameter_dependent" and invocation_consumes_authority(arguments or {}):
        policy["authority_consumed"] = True
        policy["side_effect_class"] = "single_use_authority_consumed"
        policy["replayable"] = False
    return policy


def _brand_phase_input(arguments: dict[str, Any]) -> dict[str, Any]:
    """Translate canonical JSON phase keys ("1".."9") to the engine's integer map."""
    if "phase_inputs" not in arguments:
        return arguments
    phases = arguments["phase_inputs"]
    if not isinstance(phases, dict):
        raise EngineActionError("phase_inputs must be an object keyed by decimal phases 1 through 9")
    normalized: dict[int, Any] = {}
    for key, value in phases.items():
        if not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key:
            raise EngineActionError("phase_inputs keys must be canonical decimal strings '1' through '9'")
        phase = int(key)
        if not 1 <= phase <= 9:
            raise EngineActionError("phase_inputs keys must be between '1' and '9'")
        if not isinstance(value, dict):
            raise EngineActionError(f"phase_inputs.{key} must be an object")
        normalized[phase] = value
    return {**arguments, "phase_inputs": normalized}


def _fen_output(value: Any) -> Any:
    """Project the internal tuple-keyed chess board into deterministic JSON coordinates."""
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("board"), dict):
        raise EngineActionError("parse_fen_board returned an invalid internal board representation")
    squares = []
    for coordinate, piece in value["board"].items():
        if (
            not isinstance(coordinate, tuple)
            or len(coordinate) != 2
            or any(not isinstance(part, int) for part in coordinate)
        ):
            raise EngineActionError("parse_fen_board returned an invalid board coordinate")
        file_index, rank_index = coordinate
        if not (0 <= file_index < 8 and 0 <= rank_index < 8):
            raise EngineActionError("parse_fen_board returned an out-of-range board coordinate")
        squares.append({
            "square": f"{chr(ord('a') + file_index)}{rank_index + 1}",
            "piece": piece,
        })
    return {
        **{key: item for key, item in value.items() if key != "board"},
        "board": sorted(squares, key=lambda item: item["square"]),
        "board_representation": "square_piece_list_v1",
    }


# The reviewed allowlist. Output metadata describes what each action actually returns; a suite-
# wide contract label is too coarse for summaries, Markdown renderers, boolean predicates, and
# receipt wrappers that are not contract artifacts. Policy comes from the named factories so
# every entry visibly declares its authority behavior.
ACTION_SPECS: dict[str, dict[str, ActionSpec]] = {
    "accessibility": {
        "audit_html_snippet": read_only_action("contract-list", "A11yFinding"),
        "audit_rule_families": read_only_action("contract-list", "A11yFinding"),
        "create_ai_assisted_finding": simulated_action("contract", "A11yFinding"),
        "evaluate_wcag_auditor_backlog_catalog": read_only_action("receipt"),
        "finalize_overlay_reconciliation": read_only_action("receipt"),
        "reconcile_keyboard_overlays": read_only_action("receipt"),
        "roundtrip_kitchen_learning_finding": read_only_action("receipt"),
    },
    "operator-os": {
        "capture_live_pkos_stream": simulated_action("data"),
        "capture_source": simulated_action("contract", "SourceRecord"),
        "detect_reingestion_violation": read_only_action("boolean"),
        "execute_jarvis_action_checkpoint": authorized_action("receipt"),
        "preview_jarvis_action": read_only_action("receipt"),
        "project_to_observer": read_only_action("markdown"),
        "reconcile_ryos_disposition": read_only_action("receipt"),
        "validate_observer_projection": read_only_action("data"),
    },
    "brand-publishing": {
        "compile_brand_package": simulated_action("contract", "BrandPackage"),
        "dry_run_publish": read_only_action("receipt"),
        # Both of these run as suite-local simulations until their arguments supply a
        # one-time approval token -- at which point the invocation consumes single-use
        # authority and must never be replayed. The conservative bound is advertised here;
        # effective_policy() derives the per-invocation truth during preflight.
        "execute_brand_maker_intake": parameter_dependent_action(
            "receipt", input_adapter=_brand_phase_input
        ),
        "simulate_vcc_human_approval": parameter_dependent_action("receipt"),
        "get_brand_workshop_phases": read_only_action("data"),
        "verify_immutability": read_only_action("data"),
        "verify_package_consumer": read_only_action("receipt"),
    },
    "production-house": {
        "advance_job_stage": simulated_action("contract", "ProductionJob"),
        "build_groundwire_pipeline_job": simulated_action("contract", "ProductionJob"),
        "build_investigative_documentary_job": simulated_action("contract", "ProductionJob"),
        "create_job": simulated_action("contract", "ProductionJob"),
        "map_writers_room_events": simulated_action("receipt"),
        "parse_episode_script": read_only_action("data"),
    },
    "model-behavior-lab": {
        "build_versioned_corpus": simulated_action("data"),
        "compare_runs": read_only_action("data"),
        "create_experiment_run": simulated_action("contract", "ExperimentRun"),
        "execute_chess_benchmark_run": simulated_action("contract", "ExperimentRun"),
        "execute_ethics_scenario_run": simulated_action("contract", "ExperimentRun"),
        "parse_fen_board": read_only_action("data", output_adapter=_fen_output),
    },
    "discovery-decision": {
        "advance_stage": simulated_action("contract", "InvestigationRecord"),
        "create_investigation": simulated_action("contract", "InvestigationRecord"),
        "discover_across_sources": simulated_action("receipt"),
        "execute_sif_analogy_stage": simulated_action("contract", "InvestigationRecord"),
        "ingest_insight_excavator_source": simulated_action("receipt"),
    },
    "agent-reliability": {
        "apply_with_rollback": simulated_action("receipt", replayable=True),
        "audit_promoted_components": read_only_action("receipt"),
        "build_curriculum_fixtures": simulated_action("data"),
        "partition_plan_by_budget": simulated_action("receipt"),
        "recover_plan": simulated_action("receipt"),
        "run_adversarial_harness": simulated_action("contract", "ExperimentRun"),
        "verify_path_confinement": read_only_action("data"),
    },
    "game-design": {
        "audit_authored_game_boundary": read_only_action("receipt"),
        "build_text_adventure_pack": simulated_action("data"),
        "generate_printable_balance_sheet": read_only_action("markdown"),
        "simulate_tucked_in_terrors": simulated_action("contract", "ExperimentRun"),
    },
}


def _describe_parameters(func: Any) -> list[dict[str, Any]]:
    params = []
    for name, param in inspect.signature(func).parameters.items():
        if name in {"self", "cls"} or param.kind in {param.VAR_POSITIONAL, param.VAR_KEYWORD}:
            continue
        annotation = param.annotation
        params.append({
            "name": name,
            "required": param.default is inspect.Parameter.empty,
            "default": None if param.default is inspect.Parameter.empty else param.default,
            "type": getattr(annotation, "__name__", str(annotation)) if annotation is not inspect.Parameter.empty else "any",
        })
    return params


def _registered_method(suite_id: str, action: str) -> tuple[Any, ActionSpec]:
    engine = ENGINES.get(suite_id)
    if engine is None:
        raise EngineActionError(f"unknown suite '{suite_id}'")
    specs = ACTION_SPECS.get(suite_id, {})
    spec = specs.get(action)
    if spec is None:
        raise EngineActionError(
            f"unknown or unregistered action '{action}' for suite '{suite_id}'; "
            f"available: {', '.join(sorted(specs))}"
        )
    func = getattr(engine, action, None)
    if action.startswith("_") or not callable(func):
        raise EngineActionError(f"registered action '{suite_id}.{action}' is unavailable")
    return func, spec


def unregistered_public_methods() -> dict[str, list[str]]:
    """Audit helper: public engine methods that require an explicit exposure decision."""
    gaps: dict[str, list[str]] = {}
    for suite_id, engine in ENGINES.items():
        public = {
            name
            for name, member in inspect.getmembers(engine)
            if not name.startswith("_") and callable(member) and name in vars(engine)
        }
        missing = sorted(public - set(ACTION_SPECS.get(suite_id, {})))
        if missing:
            gaps[suite_id] = missing
    return gaps


def list_actions(suite_id: str | None = None) -> dict[str, Any]:
    """Return reviewed actions with action-level output metadata."""
    suite_ids = [suite_id] if suite_id is not None else list(ENGINES)
    if suite_id is not None and suite_id not in ENGINES:
        raise EngineActionError(f"unknown suite '{suite_id}'")
    catalog: dict[str, Any] = {}
    for sid in suite_ids:
        actions = []
        for name, spec in sorted(ACTION_SPECS.get(sid, {}).items()):
            func, _ = _registered_method(sid, name)
            actions.append({
                "name": name,
                "summary": (inspect.getdoc(func) or "").split("\n")[0],
                "parameters": _describe_parameters(func),
                "output_kind": spec.output_kind,
                "emits": spec.contract,
                "execution_tier": spec.execution_tier,
                "side_effect_class": spec.side_effect_class,
                "approval_required": spec.approval_required,
                "evidence_eligible": spec.evidence_eligible,
                "replayable": spec.replayable,
                "authority_use": spec.authority_use,
            })
        catalog[sid] = {
            "engine": ENGINES[sid].__name__,
            "emits": "action-specific",
            "actions": actions,
        }
    return catalog


def get_action_spec(
    suite_id: str,
    action: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Policy metadata for one reviewed action, or for one concrete invocation.

    Without ``arguments`` this is the static catalog entry: for parameter-dependent
    actions it carries the conservative bound (they may consume single-use authority).
    With validated ``arguments`` the result is the effective per-invocation policy --
    including ``authority_consumed``, which any replay surface must treat as "never
    repeat this invocation".
    """
    _, spec = _registered_method(suite_id, action)
    policy = effective_policy(spec, arguments)
    return {
        "output_kind": spec.output_kind,
        "emits": spec.contract,
        "execution_tier": spec.execution_tier,
        **policy,
    }


def _check_json_value(value: Any, path: str = "value") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EngineActionError(f"{path} contains NaN or infinity")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise EngineActionError(f"{path} object keys must be strings")
            _check_json_value(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _check_json_value(child, f"{path}[{index}]")
        return
    raise EngineActionError(f"{path} contains non-JSON value {type(value).__name__}")


def _json_detach(value: Any, path: str) -> Any:
    _check_json_value(value, path)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise EngineActionError(f"{path} is not strict JSON: {error}") from error


def run_action(suite_id: str, action: str, arguments: dict[str, Any] | None = None) -> Any:
    """Invoke one reviewed action and return a detached, strict-JSON result."""
    func, spec = _registered_method(suite_id, action)
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
        raise EngineActionError("arguments must be a JSON object with string keys")
    arguments = _json_detach(arguments, "arguments")
    if spec.input_adapter is not None:
        arguments = spec.input_adapter(arguments)

    signature = inspect.signature(func)
    accepted = {
        name for name, param in signature.parameters.items()
        if name not in {"self", "cls"} and param.kind is not param.VAR_KEYWORD
    }
    unexpected = sorted(set(arguments) - accepted)
    if unexpected:
        raise EngineActionError(
            f"'{action}' does not accept: {', '.join(unexpected)}; accepted: {', '.join(sorted(accepted))}"
        )
    try:
        signature.bind(**arguments)
    except TypeError as error:
        raise EngineActionError(f"'{action}': {error}") from error

    result = func(**arguments)
    if spec.output_adapter is not None:
        result = spec.output_adapter(result)
    if spec.contract:
        try:
            if spec.output_kind == "contract-list":
                if not isinstance(result, list):
                    raise EngineActionError(f"'{action}' must return a list of {spec.contract}")
                result = [validate_contract(spec.contract, item) for item in result]
            else:
                result = validate_contract(spec.contract, result)
        except ContractError as error:
            raise EngineActionError(f"'{action}' returned invalid {spec.contract}: {error}") from error
    return _json_detach(result, f"result from {suite_id}.{action}")
