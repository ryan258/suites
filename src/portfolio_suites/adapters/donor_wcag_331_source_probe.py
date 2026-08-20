"""Extract the executable WCAG 3.3.1 rule from the authentic donor source.

The donor annotates its rules with Playwright types, but the rule body itself only
needs a Page-compatible ``evaluate`` method.  This probe supplies import-only type
stubs, imports the donor class from the requested checkout, invokes the real rule,
and returns the exact JavaScript expression that the donor sends to Playwright.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path


def _install_playwright_type_stubs() -> None:
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.Page = type("Page", (), {})
    sync_api.Locator = type("Locator", (), {})
    playwright.sync_api = sync_api
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api


class _CapturePage:
    def evaluate(self, expression: str, *args: object) -> str:
        if args:
            raise ValueError("InputAssistanceRule unexpectedly supplied evaluate arguments")
        if not isinstance(expression, str) or "aria-invalid" not in expression:
            raise ValueError("InputAssistanceRule did not produce the expected JavaScript")
        return expression


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: donor_wcag_331_source_probe.py <wcag-auditor-root>", file=sys.stderr)
        return 2

    donor_root = Path(sys.argv[1]).resolve()
    rule_path = donor_root / "wcag_auditor" / "rules" / "understandable_rules.py"
    if not rule_path.is_file():
        print(f"donor rule source not found: {rule_path}", file=sys.stderr)
        return 2

    _install_playwright_type_stubs()
    sys.path.insert(0, str(donor_root))

    from wcag_auditor.rules.understandable_rules import InputAssistanceRule

    rule = InputAssistanceRule()
    expression = rule.evaluate(_CapturePage())
    print(
        json.dumps(
            {
                "rule_id": rule.metadata.id,
                "wcag_criterion": rule.metadata.wcag_criterion,
                "source_path": str(rule_path),
                "evaluate_expression": expression,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
