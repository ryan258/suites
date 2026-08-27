"""Preflight and execute JSON-safe chains of reviewed suite engine actions."""

from __future__ import annotations

import copy
import math
from typing import Any

from .engine_actions import (
    EngineActionError,
    action_cache_key,
    action_is_cacheable,
    get_action_spec,
    list_actions,
    registered_action_spec,
    run_action,
)

REFERENCE_KEY = "$from"
REFERENCE_FIELDS = frozenset({REFERENCE_KEY, "path"})
STEP_FIELDS = frozenset({"suite", "action", "arguments"})


class ChainError(ValueError):
    """A preflight or execution failure with its exact, detached completed prefix."""

    def __init__(
        self,
        message: str,
        step_index: int | None = None,
        *,
        completed_steps: list[dict[str, Any]] | None = None,
        suite: str | None = None,
        action: str | None = None,
        phase: str = "execution",
    ) -> None:
        super().__init__(message)
        self.step_index = step_index
        self.completed_steps = copy.deepcopy(completed_steps or [])
        self.suite = suite
        self.action = action
        self.phase = phase

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "phase": self.phase,
            "step_index": self.step_index,
            "suite": self.suite,
            "action": self.action,
            "completed_steps": copy.deepcopy(self.completed_steps),
        }


def _walk_path(value: Any, path: str, source_step: int, consumer_step: int) -> Any:
    """Select dotted keys or integer list indexes from an earlier output."""
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                raise ChainError(
                    f"path '{path}' has no key '{part}' in step {source_step} output",
                    consumer_step,
                )
            value = value[part]
        elif isinstance(value, list):
            # removeprefix, not lstrip: lstrip("-") also strips "--1" down to "1", which
            # passes isdigit() and then raises a bare ValueError out of int() below --
            # escaping this module's ChainError contract.
            if not part.removeprefix("-").isdigit():
                raise ChainError(
                    f"path '{path}' needs an integer index for a list, got '{part}'",
                    consumer_step,
                )
            index = int(part)
            if not -len(value) <= index < len(value):
                raise ChainError(
                    f"path '{path}' index {index} out of range in step {source_step} output",
                    consumer_step,
                )
            value = value[index]
        else:
            raise ChainError(
                f"path '{path}' cannot descend into a {type(value).__name__}",
                consumer_step,
            )
    return value


def _reference_shape(value: Any, step_index: int) -> bool:
    """Validate attempted reference dictionaries and return whether this is a reference."""
    if not isinstance(value, dict) or REFERENCE_KEY not in value:
        return False
    unknown = sorted(set(value) - REFERENCE_FIELDS)
    if unknown:
        raise ChainError(
            f"step {step_index} reference has unknown field(s): {', '.join(unknown)}",
            step_index,
            phase="preflight",
        )
    target = value[REFERENCE_KEY]
    if not isinstance(target, int) or isinstance(target, bool):
        raise ChainError(
            f"step {step_index}: '{REFERENCE_KEY}' must be a step index integer",
            step_index,
            phase="preflight",
        )
    if not 0 <= target < step_index:
        raise ChainError(
            f"step {step_index} references step {target}, which is not an earlier step",
            step_index,
            phase="preflight",
        )
    if "path" in value and (not isinstance(value["path"], str) or not value["path"]):
        raise ChainError(
            f"step {step_index}: 'path' must be a non-empty string",
            step_index,
            phase="preflight",
        )
    return True


def _validate_argument_tree(value: Any, step_index: int, path: str = "arguments") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ChainError(f"step {step_index} {path} contains NaN or infinity", step_index, phase="preflight")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_argument_tree(child, step_index, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        if _reference_shape(value, step_index):
            return
        for key, child in value.items():
            if not isinstance(key, str):
                raise ChainError(
                    f"step {step_index} {path} object keys must be strings",
                    step_index,
                    phase="preflight",
                )
            _validate_argument_tree(child, step_index, f"{path}.{key}")
        return
    raise ChainError(
        f"step {step_index} {path} contains non-JSON value {type(value).__name__}",
        step_index,
        phase="preflight",
    )


def preflight_chain(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the entire static chain before executing step zero."""
    if not isinstance(steps, list) or not steps:
        raise ChainError("a chain needs a non-empty list of steps", phase="preflight")

    catalog = list_actions()
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ChainError(f"step {index} must be an object", index, phase="preflight")
        unknown_step_fields = sorted(set(step) - STEP_FIELDS)
        if unknown_step_fields:
            raise ChainError(
                f"step {index} has unknown field(s): {', '.join(unknown_step_fields)}",
                index,
                phase="preflight",
            )
        suite = step.get("suite")
        action = step.get("action")
        if not isinstance(suite, str) or not isinstance(action, str):
            raise ChainError(f"step {index} needs string 'suite' and 'action'", index, phase="preflight")
        suite_catalog = catalog.get(suite)
        action_catalog = {
            item["name"]: item for item in suite_catalog.get("actions", [])
        } if suite_catalog else {}
        if action not in action_catalog:
            raise ChainError(
                f"step {index} ({suite}.{action}) is not a reviewed action",
                index,
                suite=suite,
                action=action,
                phase="preflight",
            )
        arguments = step.get("arguments", {})
        if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
            raise ChainError(f"step {index} 'arguments' must be an object", index, phase="preflight")
        _validate_argument_tree(arguments, index)

        parameters = {item["name"]: item for item in action_catalog[action]["parameters"]}
        unexpected = sorted(set(arguments) - set(parameters))
        if unexpected:
            raise ChainError(
                f"step {index} ({suite}.{action}) does not accept: {', '.join(unexpected)}",
                index,
                suite=suite,
                action=action,
                phase="preflight",
            )
        missing = sorted(
            name for name, metadata in parameters.items()
            if metadata["required"] and name not in arguments
        )
        if missing:
            raise ChainError(
                f"step {index} ({suite}.{action}) is missing: {', '.join(missing)}",
                index,
                suite=suite,
                action=action,
                phase="preflight",
            )
        normalized.append({"suite": suite, "action": action, "arguments": copy.deepcopy(arguments)})
    return normalized


def resolve_references(value: Any, outputs: list[Any], step_index: int) -> Any:
    """Replace every valid ``{"$from": n}`` in an argument tree with step n's output."""
    if isinstance(value, dict) and REFERENCE_KEY in value:
        # The shape and backward-only target were already checked by preflight. Recheck so this
        # helper remains safe when called directly.
        _reference_shape(value, step_index)
        target = value[REFERENCE_KEY]
        if target >= len(outputs):
            raise ChainError(
                f"step {step_index} references step {target}, but only {len(outputs)} output(s) exist",
                step_index,
            )
        resolved = outputs[target]
        if "path" in value:
            resolved = _walk_path(resolved, value["path"], target, step_index)
        return copy.deepcopy(resolved)
    if isinstance(value, dict):
        return {key: resolve_references(item, outputs, step_index) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_references(item, outputs, step_index) for item in value]
    return value


def run_chain(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Preflight all steps, then execute in order with structured partial-failure evidence."""
    prepared = preflight_chain(steps)
    outputs: list[Any] = []
    records: list[dict[str, Any]] = []
    # Scoped to this run on purpose. A read-only action is a pure function of its arguments
    # *and* whatever it read off disk, so two identical steps inside one chain are the same
    # question asked twice, while the same pair an hour apart is not.
    cache: dict[str, Any] = {}

    for index, step in enumerate(prepared):
        suite = step["suite"]
        action = step["action"]
        try:
            resolved = resolve_references(step["arguments"], outputs, index)
            cache_key = (
                action_cache_key(suite, action, resolved)
                if action_is_cacheable(registered_action_spec(suite, action), resolved)
                else None
            )
            served_from_cache = cache_key is not None and cache_key in cache
            result = run_action(suite, action, resolved, cache=cache)
        except (EngineActionError, ChainError) as error:
            raise ChainError(
                f"step {index} ({suite}.{action}): {error}",
                index,
                completed_steps=records,
                suite=suite,
                action=action,
                phase="execution",
            ) from error
        except Exception as error:
            raise ChainError(
                f"step {index} ({suite}.{action}) raised {type(error).__name__}: {error}",
                index,
                completed_steps=records,
                suite=suite,
                action=action,
                phase="execution",
            ) from error

        outputs.append(result)
        # The record carries the effective per-invocation policy, not the static catalog
        # entry: a parameter-dependent action that consumed its one-time token in this very
        # step must be visible as non-replayable here, or any replay surface built on these
        # traces would repeat an authority consumption the approval authority already spent.
        metadata = get_action_spec(suite, action, resolved, result=result)
        records.append({
            "step": index,
            "suite": suite,
            "action": action,
            "output_kind": metadata["output_kind"],
            "emits": metadata["emits"],
            "side_effect_class": metadata.get("side_effect_class"),
            "approval_required": metadata.get("approval_required"),
            "evidence_eligible": metadata.get("evidence_eligible"),
            "replayable": metadata.get("replayable"),
            "authority_use": metadata.get("authority_use"),
            "authority_consumed": bool(metadata.get("authority_consumed")),
            "served_from_cache": served_from_cache,
            "references": sorted(_referenced_steps(step["arguments"], index)),
            "result": result,
        })

    return {"steps_run": len(records), "steps": records, "final": outputs[-1]}


def _referenced_steps(value: Any, step_index: int) -> set[int]:
    if isinstance(value, dict) and REFERENCE_KEY in value:
        _reference_shape(value, step_index)
        return {value[REFERENCE_KEY]}
    if isinstance(value, dict):
        return set().union(*(_referenced_steps(item, step_index) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_referenced_steps(item, step_index) for item in value)) if value else set()
    return set()
