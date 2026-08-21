"""Unified command-line interface for the Ryan Project Suites control plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .ai_config import AIConfigError, load_openrouter_config
from .engine_actions import EngineActionError, list_actions, run_action
from .contracts import CONTRACTS, ContractError, generate_sample, validate_json_str
from .registry import (
    get_live_drift_report,
    get_portfolio_summary,
    get_project,
    get_suite,
    load_ledger,
    load_nested_ledger,
    load_suites,
    validate_registry,
)
from .server import serve
from .waves import WaveRunner


def _list() -> int:
    suites = load_suites()
    for manifest in suites.values():
        print(f"{manifest['id']:<22} {manifest['state']:<10} {manifest['promise']}")
    return 0


def _status() -> int:
    summary = get_portfolio_summary()
    print(f"Portfolio snapshot: {summary['snapshot_at']}")
    print(f"Top-level directories reviewed: {summary['total_projects']}")
    print(f"Recovery standard: {summary['recovery_target_score']:.1f}/10 target ({summary['recovery_standard_id']})")
    print(f"Wave milestone progress: {summary['completed_waves']}/{summary['total_waves']} ({summary['portfolio_progress_pct']}%; not a recovery score)")
    print(
        "Verified claims: "
        f"{summary['recovered_runtime_behaviors']} runtime recovery, "
        f"{summary['verified_analysis_milestones']} analysis, "
        f"{summary['adopted_runtime_behaviors']} adopted, "
        f"{summary['converged_runtime_behaviors']} converged"
    )
    print("-" * 65)
    for s in summary["suites"]:
        print(f"{s['id']:<22} sources={s['project_count']:<2} next={s['current_wave']:<10} progress={s['waves_complete']}/{s['waves_total']}")
    print(f"independent/archive       sources={summary['independent_projects']}")
    return 0


def _next() -> int:
    candidates = []
    for manifest in load_suites().values():
        for wave in manifest["waves"]:
            if wave["status"] != "complete":
                candidates.append((wave["order"], manifest["id"], wave))
                break
    if not candidates:
        outstanding = [
            (manifest["id"], wave)
            for manifest in load_suites().values()
            for wave in manifest["waves"]
            if wave.get("runtime_followup")
        ]
        print("All migration waves across all 8 suites are scheduled complete.")
        if outstanding:
            print(f"{len(outstanding)} completed wave(s) still owe runtime follow-up:")
            for suite_id, wave in outstanding:
                print(f"  {suite_id} / {wave['id']}: {wave['runtime_followup']}")
        return 0
    for _, suite_id, wave in sorted(candidates):
        print(f"{suite_id} / {wave['id']}: {wave['objective']}")
        print(f"  acceptance: {wave['acceptance']}")
    return 0


def _validate(as_json: bool) -> int:
    report = validate_registry(check_live=True)
    if as_json:
        print(json.dumps({"ok": report.ok, "errors": report.errors, "warnings": report.warnings}, indent=2))
    else:
        for error in report.errors:
            print(f"ERROR {error}")
        for warning in report.warnings:
            print(f"WARN  {warning}")
        print(
            f"{'VALID' if report.ok else 'INVALID'}: "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
        )
    return 0 if report.ok else 1


def _ai_config(as_json: bool, require_key: bool) -> int:
    try:
        config = load_openrouter_config(require_api_key=require_key)
    except AIConfigError as error:
        if as_json:
            print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        else:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1

    summary = config.safe_summary()
    if as_json:
        print(json.dumps({"ok": True, **summary}, indent=2))
        return 0

    key_status = "configured" if config.api_key_configured else "missing"
    print(f"OpenRouter API key: {key_status}")
    print(f"Endpoint: {config.base_url}")
    print(f"App attribution: {config.app_title} ({config.app_url or 'disabled'})")
    print("Roles:")
    for role in config.roles.values():
        print(
            f"  {role.name:<14} model={role.model:<24} "
            f"temperature={role.temperature:<3} max_tokens={role.max_tokens}"
        )
    if not config.api_key_configured:
        print("Add OPENROUTER_API_KEY to the git-ignored .env before making network requests.")
    return 0


def _inspect(target: str) -> int:
    suite = get_suite(target)
    if suite:
        print(f"SUITE: {suite['name']} ({suite['id']})")
        print(f"State: {suite['state']}")
        print(f"Promise: {suite['promise']}")
        print(f"Anchors: {', '.join(suite.get('anchors', []))}")
        print(f"Contracts: {', '.join(suite.get('contracts', []))}")
        print("Members:")
        for m in suite.get("members", []):
            print(f"  - {m['project']:<30} [{m['relationship']}]")
        print("Waves:")
        for w in suite.get("waves", []):
            print(f"  - {w['id']:<4} ({w['status']:<11}) {w['objective']}")
            if w.get("runtime_followup"):
                print(f"         runtime follow-up outstanding: {w['runtime_followup']}")
        return 0

    project = get_project(target)
    if project:
        print(f"PROJECT: {project['name']}")
        print(f"Primary Suite: {project.get('primary_suite') or 'None (Independent)'}")
        print(f"Disposition: {project.get('disposition')}")
        print(f"Migration: {project.get('migration')}")
        snap = project.get("source_snapshot", {})
        if snap:
            print(f"Git Snapshot: {snap.get('branch')}@{snap.get('head')} ({snap.get('status_lines', 0)} dirty lines)")
        return 0

    print(f"Error: '{target}' is not a recognized suite or project in the registry.", file=sys.stderr)
    return 1


def _contract_cmd(name: str, action: str, file_path: str | None) -> int:
    if name not in CONTRACTS:
        print(f"Error: Unknown contract '{name}'. Available: {', '.join(CONTRACTS.keys())}", file=sys.stderr)
        return 1

    if action == "sample":
        sample = generate_sample(name)
        print(json.dumps(sample, indent=2))
        return 0

    if action == "spec":
        spec = CONTRACTS[name]
        print(f"Contract: {name}")
        print(f"Description: {spec.description}")
        print(f"Required Fields: {', '.join(sorted(spec.required))}")
        if spec.enums:
            print(f"Enum Fields: {dict(spec.enums)}")
        return 0

    if action == "validate":
        if not file_path:
            print("Error: Specify a JSON file path to validate with 'contract <name> validate <file>'", file=sys.stderr)
            return 1
        path = Path(file_path)
        if not path.exists():
            print(f"Error: File '{file_path}' not found.", file=sys.stderr)
            return 1
        try:
            validate_json_str(name, path.read_text(encoding="utf-8"))
            print(f"VALID: '{file_path}' conforms to contract '{name}'.")
            return 0
        except ContractError as exc:
            print(f"INVALID: '{file_path}' failed contract '{name}': {exc}", file=sys.stderr)
            return 1

    print(f"Error: Unknown action '{action}'", file=sys.stderr)
    return 1


def _wave_cmd(suite_id: str | None, wave_id: str | None, run_all: bool, write_evidence: bool, full: bool) -> int:
    if run_all or (not suite_id and not wave_id):
        results = WaveRunner.run_all(write_evidence=write_evidence, full=full)
        runtime_count = sum(1 for r in results if r.execution_kind == "verified_runtime_recovery" and r.passed)
        analysis_count = sum(1 for r in results if r.execution_kind == "verified_analysis" and r.passed)
        prototype_count = sum(1 for r in results if r.execution_kind == "prototype_check" and r.prototype_passed)
        failed_count = sum(
            1
            for r in results
            if r.execution_kind in {"verified_analysis", "verified_runtime_recovery", "prototype_check"}
            and not (r.passed or r.prototype_passed)
        )
        unintegrated_count = sum(1 for r in results if r.execution_kind == "unintegrated_specification")
        error_count = sum(1 for r in results if r.execution_kind == "error")
        unverifiable_count = sum(1 for r in results if r.execution_kind == "unverifiable_environment")
        fast_probe_count = sum(1 for r in results if r.execution_kind == "fast_probe" and r.passed)

        for r in results:
            if r.execution_kind == "error":
                tag = "[ERROR]"
            elif r.execution_kind == "verified_runtime_recovery" and r.passed:
                tag = "[RECOVERED]"
            elif r.execution_kind == "verified_analysis" and r.passed:
                tag = "[ANALYSIS]"
            elif r.execution_kind == "fast_probe" and r.passed:
                tag = "[FAST-PROBE]"
            elif r.execution_kind == "prototype_check" and r.prototype_passed:
                tag = "[PROTOTYPE]"
            elif r.execution_kind == "unverifiable_environment":
                tag = "[UNVERIFIABLE]"
            elif r.execution_kind == "unintegrated_specification":
                tag = "[SPECIFIED]"
            else:
                tag = "[FAIL]"
            print(f"{tag:<12} {r.suite_id:<20} {r.wave_id:<4} : {r.message}")
        print("-" * 65)
        print(
            f"Results: {runtime_count} runtime recoveries, {analysis_count} verified analyses, "
            f"{prototype_count} prototype checks passed, {fast_probe_count} fast probes, "
            f"{failed_count} checks failed, "
            f"{unverifiable_count} environment-unverifiable, {unintegrated_count} unintegrated, "
            f"{error_count} errors."
        )
        return 1 if failed_count or unverifiable_count or unintegrated_count or error_count else 0

    if not suite_id or not wave_id:
        print("Error: Specify suite and wave (e.g. 'suites wave accessibility A2') or '--all'", file=sys.stderr)
        return 1

    result = WaveRunner.run_wave(suite_id, wave_id, write_evidence=write_evidence, full=full)
    if result.execution_kind == "error":
        tag = "[ERROR]"
    elif result.execution_kind == "verified_runtime_recovery" and result.passed:
        tag = "[RECOVERED]"
    elif result.execution_kind == "verified_analysis" and result.passed:
        tag = "[ANALYSIS]"
    elif result.execution_kind == "fast_probe" and result.passed:
        tag = "[FAST-PROBE]"
    elif result.execution_kind == "prototype_check" and result.prototype_passed:
        tag = "[PROTOTYPE]"
    elif result.execution_kind == "unverifiable_environment":
        tag = "[UNVERIFIABLE]"
    elif result.execution_kind == "unintegrated_specification":
        tag = "[SPECIFIED]"
    else:
        tag = "[FAIL]"
    print(f"{tag} {result.suite_id} / {result.wave_id} ({result.execution_kind}): {result.message}")
    if result.evidence_path:
        print(f"Evidence recorded at: {result.evidence_path}")
    elif write_evidence:
        print(f"Evidence NOT written: {result.record_note}. Prior receipt retained.")
    return 0 if result.passed or result.prototype_passed else 1


def _drift() -> int:
    drift_items = get_live_drift_report()
    drifted = [d for d in drift_items if d["has_drift"]]
    print(f"Live Drift Report: {len(drifted)} drifted out of {len(drift_items)} monitored repos")
    print("-" * 75)
    for d in drift_items:
        if d["has_drift"]:
            print(f"DRIFT {d['name']:<30} snap={d['snapshot_branch']}@{d['snapshot_head']} live={d['current_branch']}@{d['current_head']} (dirty={d['current_lines']})")
    if not drifted:
        print("All monitored repositories match baseline snapshot.")
    unfingerprinted = [d["name"] for d in drift_items if d["status_unfingerprinted"]]
    if unfingerprinted:
        print(
            f"Note: {len(unfingerprinted)} baseline(s) carry no status_sha256; working-tree "
            "content drift is UNCHECKED for those repos (branch, HEAD and dirty count only)."
        )
    return 0


def _export() -> int:
    summary = get_portfolio_summary()
    suites = load_suites()
    ledger = load_ledger()
    nested = load_nested_ledger()
    export_payload = {
        "summary": summary,
        "suites": suites,
        "projects": ledger.get("projects", []),
        "nested_repositories": nested.get("repositories", []),
    }
    print(json.dumps(export_payload, indent=2))
    return 0


def _engine_cmd(suite: str | None, action: str | None, raw_args: str | None) -> int:
    """List invocable engine actions, or run one and print its typed output."""
    try:
        if action is None:
            catalog = list_actions(suite)
            for suite_id, info in catalog.items():
                print(f"{suite_id}  ({info['engine']} -> {info['emits']})")
                for entry in info["actions"]:
                    params = ", ".join(
                        param["name"] if param["required"] else f"{param['name']}={param['default']!r}"
                        for param in entry["parameters"]
                    )
                    print(f"    {entry['name']}({params})")
                    if entry["summary"]:
                        print(f"        {entry['summary']}")
            return 0

        try:
            arguments = json.loads(raw_args) if raw_args else {}
        except ValueError as exc:
            print(f"ERROR: --args is not valid JSON: {exc}")
            return 2
        result = run_action(suite, action, arguments)
    except EngineActionError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suites", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list suite promises and states")
    sub.add_parser("status", help="show portfolio coverage and next waves")
    sub.add_parser("next", help="show the next incomplete wave in every suite")
    sub.add_parser("drift", help="scan live git status and report drift against baseline snapshots")
    sub.add_parser("export", help="export consolidated portfolio data as JSON")

    ai_config = sub.add_parser("ai-config", help="inspect safe OpenRouter role configuration")
    ai_config.add_argument("--json", action="store_true", help="emit a machine-readable redacted summary")
    ai_config.add_argument(
        "--require-key",
        action="store_true",
        help="fail unless OPENROUTER_API_KEY is configured",
    )

    validate = sub.add_parser("validate", help="validate manifests, coverage, and live source drift")
    validate.add_argument("--json", action="store_true", help="emit a machine-readable report")

    inspect_p = sub.add_parser("inspect", help="inspect details of a specific suite or project")
    inspect_p.add_argument("target", help="suite id or project name to inspect")

    contract_p = sub.add_parser("contract", help="inspect, sample, or validate cross-suite contracts")
    contract_p.add_argument("name", help="contract name (e.g. A11yFinding, SourceRecord, BrandPackage, etc.)")
    contract_p.add_argument("action", choices=["sample", "spec", "validate"], help="action to perform")
    contract_p.add_argument("file", nargs="?", default=None, help="path to JSON file for validation")

    engine_p = sub.add_parser("engine", help="list or run the suite engines' invocable actions")
    engine_p.add_argument("suite", nargs="?", default=None, help="suite id (e.g. accessibility)")
    engine_p.add_argument("action", nargs="?", default=None, help="action name; omit to list actions")
    engine_p.add_argument("--args", default=None, help="JSON object of keyword arguments")

    wave_p = sub.add_parser("wave", help="run and verify migration wave gates and generate evidence")
    wave_p.add_argument("suite", nargs="?", default=None, help="suite ID (e.g. accessibility)")
    wave_p.add_argument("wave_id", nargs="?", default=None, help="wave ID (e.g. A2, O1, B1)")
    wave_p.add_argument("--all", action="store_true", help="run all 43 migration wave checks across all suites")
    wave_p.add_argument(
        "--record",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="write evidence files to suite directories (ephemeral by default)",
    )
    wave_p.add_argument(
        "--full",
        action="store_true",
        help="run every required verification gate instead of the fast probe",
    )

    serve_p = sub.add_parser("serve", help="launch local portfolio web dashboard server")
    serve_p.add_argument("--port", type=int, default=8383, help="port number (default: 8383)")

    args = parser.parse_args(argv)

    if args.command == "list":
        return _list()
    if args.command == "status":
        return _status()
    if args.command == "next":
        return _next()
    if args.command == "drift":
        return _drift()
    if args.command == "export":
        return _export()
    if args.command == "ai-config":
        return _ai_config(args.json, args.require_key)
    if args.command == "validate":
        return _validate(args.json)
    if args.command == "inspect":
        return _inspect(args.target)
    if args.command == "contract":
        return _contract_cmd(args.name, args.action, args.file)
    if args.command == "engine":
        return _engine_cmd(args.suite, args.action, args.args)
    if args.command == "wave":
        return _wave_cmd(args.suite, args.wave_id, args.all, args.record, args.full)
    if args.command == "serve":
        serve(args.port)
        return 0

    return 0
