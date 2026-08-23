"""Small installed-console boundary that can report checkout discovery failures cleanly."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Load the checkout-oriented CLI and turn root-discovery failures into user errors."""
    try:
        from .cli import main as cli_main
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return cli_main(argv)
