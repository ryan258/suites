"""Produce an ExperimentRun from one retained ai-ethics-comparator result, using the donor's own stats.

Runs as a standalone subprocess (never imported by the control plane). It loads the donor's
stdlib-only ``lib/stats.py`` by file path, computes Wilson intervals per option with it, and prints
one JSON line. The parent recomputes both digests itself; the probe's claims are not trusted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

EXIT_USAGE = 2
EXIT_IMPORT_FAILED = 3  # donor stats could not be loaded: environment_blocked, not an API break


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: donor_ethics_experiment_probe.py <donor-repo> <result.json>", file=sys.stderr)
        return EXIT_USAGE
    repo, result_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    stats_path = repo / "lib" / "stats.py"
    sys.dont_write_bytecode = True  # a probe must not write into the donor checkout
    if not result_path.is_file() or repo not in result_path.parents:
        print(f"result file not found inside the donor repository: {result_path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        spec = importlib.util.spec_from_file_location("donor_stats", stats_path)
        stats = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stats)
        stats.wilson_confidence_interval
    except Exception as exc:
        print(f"failed to load donor stats: {exc}", file=sys.stderr)
        return EXIT_IMPORT_FAILED

    result = json.loads(result_path.read_text(encoding="utf-8"))
    responses = result["responses"]
    total = len(responses)
    counts: dict[int, int] = {}
    for response in responses:
        if isinstance(response.get("optionId"), int):
            counts[response["optionId"]] = counts.get(response["optionId"], 0) + 1
    source_sha, stats_sha = _sha256(result_path), _sha256(stats_path)
    run = {
        "schema_version": "1.0.0",
        "run_id": "run-ethics-" + re.sub(r"[^A-Za-z0-9._:-]", "-", str(result["runId"])),
        "benchmark_id": "bench-ethics-" + re.sub(r"[^A-Za-z0-9._:-]", "-", str(result["paradoxId"])),
        "benchmark_version": "prompt@" + hashlib.sha256(result["prompt"].encode()).hexdigest()[:12],
        "provider": "ai-ethics-comparator",
        "model": result["modelName"],
        "parameters": result["params"],
        "scorer": "donor-lib-stats-wilson",
        "scorer_version": "stats.py@" + stats_sha[:12],
        "status": "completed",
        "iterations": [
            {"iteration": r["iteration"], "passed": isinstance(r.get("optionId"), int), "option_id": r.get("optionId")}
            for r in responses
        ],
        "evidence": [
            {"option_id": option_id, "count": count, "wilson": stats.wilson_confidence_interval(count, total)}
            for option_id, count in sorted(counts.items())
        ]
        or [{"note": "no decisive responses", "total": total}],
        "errors": [],
    }
    print(json.dumps({"experiment_run": run, "source_sha256": source_sha, "stats_sha256": stats_sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
