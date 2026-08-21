"""Invocable engine action surface: introspect suite engines and call them by name.

The eight suite engines are the portfolio's consolidated capabilities. This module makes
them reachable from the CLI and the local dashboard without hand-maintaining a route per
method: public engine methods are discovered by introspection, and the discovered set is
the allowlist. A name that is not in that set is never passed to ``getattr``.
"""

from __future__ import annotations

import inspect
from typing import Any

from .engines import ENGINES

# Contract each engine's actions are expected to emit, for UI labelling only.
SUITE_CONTRACT = {
    "accessibility": "A11yFinding",
    "operator-os": "SourceRecord",
    "brand-publishing": "BrandPackage",
    "production-house": "ProductionJob",
    "model-behavior-lab": "ExperimentRun",
    "discovery-decision": "InvestigationRecord",
    "agent-reliability": "ExperimentRun",
    "game-design": "ExperimentRun",
}


class EngineActionError(ValueError):
    """Unknown suite/action, or arguments a discovered action will not accept."""


def _public_methods(engine: type) -> dict[str, Any]:
    """Public callables declared on the engine class itself."""
    found = {}
    for name, member in inspect.getmembers(engine):
        if name.startswith("_") or not callable(member):
            continue
        if name not in vars(engine) and not any(name in vars(base) for base in engine.__mro__[:-1]):
            continue
        found[name] = member
    return found


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


def list_actions(suite_id: str | None = None) -> dict[str, Any]:
    """Every invocable action, or just one suite's, with its parameter spec."""
    suites = ENGINES if suite_id is None else {suite_id: ENGINES[suite_id]} if suite_id in ENGINES else {}
    if suite_id is not None and not suites:
        raise EngineActionError(f"unknown suite '{suite_id}'")
    catalog = {}
    for sid, engine in suites.items():
        catalog[sid] = {
            "engine": engine.__name__,
            "emits": SUITE_CONTRACT.get(sid),
            "actions": [
                {
                    "name": name,
                    "summary": (inspect.getdoc(func) or "").split("\n")[0],
                    "parameters": _describe_parameters(func),
                }
                for name, func in sorted(_public_methods(engine).items())
            ],
        }
    return catalog


def run_action(suite_id: str, action: str, arguments: dict[str, Any] | None = None) -> Any:
    """Invoke one discovered engine action by name with keyword arguments."""
    engine = ENGINES.get(suite_id)
    if engine is None:
        raise EngineActionError(f"unknown suite '{suite_id}'")
    methods = _public_methods(engine)
    if action not in methods:
        raise EngineActionError(
            f"unknown action '{action}' for suite '{suite_id}'; available: {', '.join(sorted(methods))}"
        )
    func = methods[action]
    arguments = arguments or {}
    if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
        raise EngineActionError("arguments must be a JSON object with string keys")

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
    except TypeError as exc:
        raise EngineActionError(f"'{action}': {exc}") from exc
    return func(**arguments)
