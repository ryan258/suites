"""Run one Tucked in Terrors experiment inside a credential-stripped child process.

This script intentionally has no dependency on ``portfolio_suites``. The control plane
passes the donor root and temporary output paths as argv, and the probe imports only the
donor package before running its CLI entry function.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3
EXIT_PROBE_FAILED = 4


def _emit(payload: dict[str, Any]) -> None:
    sys.__stdout__.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.__stdout__.flush()


def _imported_module_fingerprints(root: Path) -> dict[str, dict[str, str]]:
    package_root = (root / "src" / "tuck_in_terrors_sim").resolve()
    found: dict[str, dict[str, str]] = {}
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("tuck_in_terrors_sim"):
            continue
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path)
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(package_root).as_posix()
        except (OSError, ValueError):
            continue
        if path.suffix != ".py" or path.is_symlink() or not resolved.is_file():
            continue
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        found[name] = {
            "path": f"src/tuck_in_terrors_sim/{relative}",
            "sha256": digest,
        }
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("donor_root")
    parser.add_argument("--objective", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--simulations", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--database", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code or EXIT_USAGE)

    root = Path(args.donor_root).resolve()
    if args.simulations < 1 or args.seed < 0:
        _emit({"status": "invalid_request"})
        return EXIT_USAGE

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    try:
        from tuck_in_terrors_sim.cli import main_cli
    except Exception as error:
        _emit({
            "status": "import_failed",
            "import_error": type(error).__name__,
            "python_version": sys.version.split()[0],
            "python_implementation": getattr(sys, "implementation", None).name,
        })
        return EXIT_IMPORT_FAILED

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    command_args = [
        "run",
        "--objective", args.objective,
        "--ai", args.policy,
        "--simulations", str(args.simulations),
        "--seed", str(args.seed),
        "--output-file", args.output_file,
        "--database", args.database,
    ]
    started = time.monotonic()
    error_kind: str | None = None
    try:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            exit_code = main_cli(command_args)
        if type(exit_code) is not int:
            error_kind = "invalid_cli_exit_code"
            exit_code = EXIT_PROBE_FAILED
    except Exception as error:
        error_kind = type(error).__name__
        exit_code = EXIT_PROBE_FAILED
    duration_ms = max(0.0, (time.monotonic() - started) * 1000)

    modules = _imported_module_fingerprints(root)
    _emit({
        "status": "completed" if exit_code == 0 else "runtime_failed",
        "exit_code": exit_code,
        "duration_ms": round(duration_ms, 2),
        "python_version": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "module_fingerprints": modules,
        "error_kind": error_kind,
    })
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
