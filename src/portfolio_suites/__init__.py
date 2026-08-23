"""Shared contracts and portfolio registry for Ryan's project suites.

The checkout root is resolved only when a control-plane module is used. Keeping package import
lazy lets the installed console wrapper report a missing ``SUITES_ROOT`` cleanly instead of
raising an import-time traceback before the command has started.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ContractError", "validate_contract"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .contracts import ContractError, validate_contract

        return {"ContractError": ContractError, "validate_contract": validate_contract}[name]
    raise AttributeError(name)
