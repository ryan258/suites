"""Run Production House's own Groundwire tasks against a private temp state and report what happened.

Runs as a standalone subprocess (never imported by the control plane). The donor engine executes
``groundwire.episode.create`` then ``groundwire.episode.advance-status`` twice on a state file inside a
temp directory, so no donor data changes. It prints one JSON line with the task results and the engine's
own audit log. If ``filelock`` is not installed the probe substitutes a no-op lock (safe: the state
is private to this process) and says so in ``filelock_stubbed``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3  # the donor engine could not be imported: environment_blocked


def _ensure_filelock() -> bool:
    try:
        import filelock  # noqa: F401
        return False
    except ImportError:
        class FileLock:
            def __init__(self, *args: object, **kwargs: object) -> None: ...
            def __enter__(self) -> "FileLock": return self
            def __exit__(self, *exc: object) -> None: ...
            def acquire(self, *args: object, **kwargs: object) -> "FileLock": return self
            def release(self, *args: object, **kwargs: object) -> None: ...
        module = types.ModuleType("filelock")
        module.FileLock = FileLock
        module.Timeout = type("Timeout", (Exception,), {})
        sys.modules["filelock"] = module
        return True


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: donor_production_job_probe.py <production-house-root> <episode-id>", file=sys.stderr)
        return EXIT_USAGE
    repo, episode_id = Path(sys.argv[1]).resolve(), sys.argv[2]
    sys.dont_write_bytecode = True  # a probe must not write into the donor checkout
    sys.path.insert(0, str(repo / "src"))
    stubbed = _ensure_filelock()
    try:
        from production_engine.domains.groundwire.tasks import register_tasks
        from production_engine.engine import ProductionEngine
    except Exception as exc:
        print(f"failed to import production_engine: {exc}", file=sys.stderr)
        return EXIT_IMPORT_FAILED

    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        engine = ProductionEngine.from_path(state, plugin_discovery="none")
        register_tasks(engine)
        payload = {"episode_id": episode_id, "title": "Freeze proof episode"}
        results = [
            engine.run_task("groundwire.episode.create", payload, _source="probe"),
            engine.run_task("groundwire.episode.advance-status", {"episode_id": episode_id}, _source="probe"),
            engine.run_task("groundwire.episode.advance-status", {"episode_id": episode_id}, _source="probe"),
        ]
        audit = [json.loads(line) for line in Path(str(state.with_suffix(".audit.jsonl"))).read_text().splitlines() if line.strip()]
    print(json.dumps({"payload": payload, "results": results, "audit": audit, "filelock_stubbed": stubbed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
