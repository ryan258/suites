"""Chain suite engine actions: one action's output becomes a later action's argument.

A chain is the list the Toolbench result tray already keeps -- ``suite``, ``action``,
``arguments`` -- with references between steps. A reference is ``{"$from": <step index>}``,
optionally with ``"path"`` to select part of that step's output:

    [
      {"suite": "game-design", "action": "simulate_tucked_in_terrors", "arguments": {"trials": 100}},
      {"suite": "game-design", "action": "generate_printable_balance_sheet",
       "arguments": {"sim_result": {"$from": 0}}}
    ]

ponytail: compatibility is not declared anywhere. A reference either fits the receiving
action or that action rejects it, and the chain reports which step failed and why. A
hand-maintained compatibility table would be a second copy of every engine signature,
free to drift out of agreement with the code it describes.
"""

from __future__ import annotations

from typing import Any

from .engine_actions import EngineActionError, list_actions, run_action

REFERENCE_KEY = "$from"


class ChainError(ValueError):
    """A chain that cannot be resolved or run, tagged with the step that failed."""

    def __init__(self, message: str, step_index: int | None = None) -> None:
        super().__init__(message)
        self.step_index = step_index


def _walk_path(value: Any, path: str, step_index: int) -> Any:
    """Select part of a prior output: dotted keys, integer segments index into lists."""
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                raise ChainError(f"path '{path}' has no key '{part}' in step {step_index} output", step_index)
            value = value[part]
        elif isinstance(value, list):
            if not part.lstrip("-").isdigit():
                raise ChainError(f"path '{path}' needs an integer index for a list, got '{part}'", step_index)
            index = int(part)
            if not -len(value) <= index < len(value):
                raise ChainError(f"path '{path}' index {index} out of range in step {step_index} output", step_index)
            value = value[index]
        else:
            raise ChainError(f"path '{path}' cannot descend into a {type(value).__name__}", step_index)
    return value


def _is_reference(value: Any) -> bool:
    return isinstance(value, dict) and REFERENCE_KEY in value and set(value) <= {REFERENCE_KEY, "path"}


def resolve_references(value: Any, outputs: list[Any], step_index: int) -> Any:
    """Replace every ``{"$from": n}`` in an argument tree with step n's output."""
    if _is_reference(value):
        target = value[REFERENCE_KEY]
        if not isinstance(target, int) or isinstance(target, bool):
            raise ChainError(f"step {step_index}: '{REFERENCE_KEY}' must be a step index integer", step_index)
        if not 0 <= target < len(outputs):
            raise ChainError(
                f"step {step_index} references step {target}, which has not run "
                f"({len(outputs)} earlier step(s) available)",
                step_index,
            )
        resolved = outputs[target]
        path = value.get("path")
        if path is not None:
            if not isinstance(path, str) or not path:
                raise ChainError(f"step {step_index}: 'path' must be a non-empty string", step_index)
            resolved = _walk_path(resolved, path, target)
        return resolved
    if isinstance(value, dict):
        return {key: resolve_references(item, outputs, step_index) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_references(item, outputs, step_index) for item in value]
    return value


def run_chain(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Run steps in order, feeding referenced outputs forward.

    Stops at the first failing step and reports the completed prefix, so a long chain
    shows where it broke rather than only that it did.
    """
    if not isinstance(steps, list) or not steps:
        raise ChainError("a chain needs a non-empty list of steps")

    catalog = list_actions()
    outputs: list[Any] = []
    records: list[dict[str, Any]] = []

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ChainError(f"step {index} must be an object", index)
        suite = step.get("suite")
        action = step.get("action")
        if not isinstance(suite, str) or not isinstance(action, str):
            raise ChainError(f"step {index} needs string 'suite' and 'action'", index)
        arguments = step.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ChainError(f"step {index} 'arguments' must be an object", index)

        resolved = resolve_references(arguments, outputs, index)
        try:
            result = run_action(suite, action, resolved)
        except EngineActionError as exc:
            raise ChainError(f"step {index} ({suite}.{action}): {exc}", index) from exc
        except Exception as exc:
            raise ChainError(f"step {index} ({suite}.{action}) raised {type(exc).__name__}: {exc}", index) from exc

        outputs.append(result)
        records.append({
            "step": index,
            "suite": suite,
            "action": action,
            "emits": catalog.get(suite, {}).get("emits"),
            "references": sorted(_referenced_steps(arguments)),
            "result": result,
        })

    return {"steps_run": len(records), "steps": records, "final": outputs[-1]}


def _referenced_steps(value: Any) -> set[int]:
    """Which earlier steps an argument tree depends on, for display."""
    if _is_reference(value):
        target = value[REFERENCE_KEY]
        return {target} if isinstance(target, int) and not isinstance(target, bool) else set()
    if isinstance(value, dict):
        return set().union(*(_referenced_steps(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_referenced_steps(item) for item in value)) if value else set()
    return set()
