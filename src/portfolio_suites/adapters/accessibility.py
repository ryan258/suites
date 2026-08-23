"""Source adapter invoking real canonical allys-tools runtime and capturing authentic evidence."""

from __future__ import annotations

import ast
import datetime
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, validate_contract
from ..engines.accessibility import AccessibilityEngine
from .common import donor_env, get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

ALLYS_TOOLS_DIR = get_repo_path("allys-tools", "ALLYS_TOOLS_DIR")
WCAG_AUDITOR_DIR = get_repo_path("wcag-auditor", "WCAG_AUDITOR_DIR")
# Permissions that let an extension reach beyond the tab the user invoked it on.
BROAD_EXTENSION_PERMISSIONS = frozenset({
    "scripting", "tabs", "webNavigation", "debugger", "management",
})
# Host match patterns that reach every page the user visits.
BROAD_HOST_PATTERNS = frozenset({"<all_urls>", "*://*/*", "http://*/*", "https://*/*"})

KB_OVERLAY_DIR = get_repo_path("kb-overlay", "KB_OVERLAY_DIR")
KEYBOARD_NAV_OVERLAY_DIR = get_repo_path("keyboard-nav-overlay", "KEYBOARD_NAV_OVERLAY_DIR")
KEYBOARD_NAV_OVERLAY_94BF7E_DIR = get_repo_path("keyboard-nav-overlay-94bf7e", "KEYBOARD_NAV_OVERLAY_94BF7E_DIR")
A11Y_KITCHEN_DIR = get_repo_path("a11y kitchen", "A11Y_KITCHEN_DIR")
DONOR_SOURCE_PROBE = Path(__file__).with_name("donor_wcag_331_source_probe.py")
DONOR_BROWSER_PROBE = Path(__file__).with_name("donor_wcag_331_browser_probe.mjs")


def parse_tap_output(stdout: str) -> tuple[int, int]:
    """Parse TAP output counting passed and failed tests accurately without 'not ok' / 'ok' collisions."""
    passed = 0
    failed = 0
    for line in stdout.splitlines():
        stripped = line.strip()
        if re.match(r"^ok\s+\d+", stripped):
            passed += 1
        elif re.match(r"^not\s+ok\s+\d+", stripped):
            failed += 1
    return passed, failed


def _is_environment_blocked(output: str, stdout: str = "") -> bool:
    """Recognize execution-environment failures without converting product failures to blockers.

    An environment blocker is neither a pass nor a product failure, so misreading one costs
    a real regression: a failing gate reported as "unverifiable" exits 2 and claims nothing
    is wrong. The permission markers alone cannot carry that decision -- a suite whose own
    assertion output happens to mention a browser and a denied permission would relabel its
    own failures.

    So the discriminator is whether the runner produced test results at all. TAP lines mean
    the gate ran and reached verdicts; whatever failed then is a product failure, however
    the stderr reads. No verdicts plus a permission signal means the runner never got far
    enough to judge anything, which is the actual blocker. A missing runtime is unambiguous
    on its own -- there is no interpretation of "playwright install" that is a product bug.
    """
    normalized = output.casefold()
    missing_runtime = any(
        marker in normalized
        for marker in (
            "executable doesn't exist",
            "playwright install",
            "please run the following command to download new browsers",
        )
    )
    if missing_runtime:
        return True

    permission_signal = any(
        marker in normalized
        for marker in ("eperm", "operation not permitted", "permission denied")
    )
    execution_context = any(
        marker in normalized
        for marker in ("listen", "socket", ".pipe", "playwright", "browser", "chromium")
    )
    if not (permission_signal and execution_context):
        return False

    passed_tests, failed_tests = parse_tap_output(stdout)
    return (passed_tests + failed_tests) == 0


def _process_error(stage: str, command: list[str], process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    full_stderr = process.stderr or ""
    return {
        "stage": stage,
        "command": shlex.join(command),
        "error_kind": "non_zero_exit",
        "exit_code": process.returncode,
        "stderr": full_stderr[:500],
        # stdout carries the TAP verdicts that decide whether this run judged anything.
        "environment_blocked": _is_environment_blocked(full_stderr, process.stdout or ""),
    }


def _exception_error(stage: str, command: list[str], error: Exception) -> dict[str, Any]:
    message = str(error)
    return {
        "stage": stage,
        "command": shlex.join(command),
        "error_kind": type(error).__name__,
        "message": message,
        "environment_blocked": _is_environment_blocked(message),
    }


class AccessibilitySourceAdapter:
    """Invokes authentic allys-tools runtime to evaluate WCAG rules and capture contract-compliant receipts."""

    @classmethod
    def execute_wcag_331_migration_gate(cls, full_suite: bool = False) -> dict[str, Any]:
        """Execute WCAG 3.3.1 migration gate with operational error separation.

        Args:
            full_suite: When True (formal evidence recording), runs complete 127-test suite
                        and full-audit pipeline. When False (ephemeral wave probes and unit tests),
                        runs focused parity gate and DOM snapshot evaluator in sub-second time.
        """
        target_fp = get_git_fingerprint(ALLYS_TOOLS_DIR)
        donor_fp = get_git_fingerprint(WCAG_AUDITOR_DIR)
        operational_errors: list[dict[str, Any]] = []

        # --- Stage 0: Authentic Donor Source and Browser Runtime ---
        donor_source_cmd = [sys.executable, str(DONOR_SOURCE_PROBE), str(WCAG_AUDITOR_DIR)]
        donor_runtime_cmd = ["node", str(DONOR_BROWSER_PROBE)]
        donor_source: dict[str, Any] = {}
        donor_result: dict[str, Any] = {}
        donor_source_duration_ms = 0.0
        donor_runtime_duration_ms = 0.0
        donor_source_ok = False
        donor_runtime_ok = False

        t0_donor_source = time.perf_counter()
        try:
            donor_source_proc = subprocess.run(
                donor_source_cmd,
                cwd=WCAG_AUDITOR_DIR,
                capture_output=True,
                text=True,
                env=donor_env(),
                timeout=15,
            )
            donor_source_duration_ms = (time.perf_counter() - t0_donor_source) * 1000.0
            if donor_source_proc.returncode == 0 and donor_source_proc.stdout.strip():
                donor_source = json.loads(donor_source_proc.stdout)
                donor_source_ok = (
                    donor_source.get("rule_id") == "input-assistance-error-msg"
                    and donor_source.get("wcag_criterion") == "3.3.1"
                    and bool(donor_source.get("evaluate_expression"))
                )
                if not donor_source_ok:
                    operational_errors.append({
                        "stage": "donor_source_invocation",
                        "command": shlex.join(donor_source_cmd),
                        "error_kind": "invalid_output",
                        "message": "Donor rule metadata or evaluate expression was invalid.",
                        "environment_blocked": False,
                    })
            else:
                operational_errors.append(
                    _process_error("donor_source_invocation", donor_source_cmd, donor_source_proc)
                )
        except Exception as exc:
            donor_source_duration_ms = (time.perf_counter() - t0_donor_source) * 1000.0
            operational_errors.append(
                _exception_error("donor_source_invocation", donor_source_cmd, exc)
            )

        if donor_source_ok:
            t0_donor_runtime = time.perf_counter()
            try:
                donor_runtime_proc = subprocess.run(
                    donor_runtime_cmd,
                    cwd=ALLYS_TOOLS_DIR,
                    input=json.dumps(donor_source),
                    capture_output=True,
                    text=True,
                    env=donor_env(),
                    timeout=30,
                )
                donor_runtime_duration_ms = (time.perf_counter() - t0_donor_runtime) * 1000.0
                if donor_runtime_proc.returncode == 0 and donor_runtime_proc.stdout.strip():
                    donor_result = json.loads(donor_runtime_proc.stdout)
                    outcomes = donor_result.get("outcomes")
                    donor_runtime_ok = (
                        donor_result.get("rule_id") == "input-assistance-error-msg"
                        and donor_result.get("wcag_criterion") == "3.3.1"
                        and isinstance(outcomes, dict)
                        and set(outcomes) == {
                            "invalid_input_missing_error_ref",
                            "invalid_input_with_valid_errormessage",
                            "invalid_input_with_valid_describedby",
                        }
                        and all(isinstance(value, bool) for value in outcomes.values())
                    )
                    if not donor_runtime_ok:
                        operational_errors.append({
                            "stage": "donor_browser_evaluation",
                            "command": shlex.join(donor_runtime_cmd),
                            "error_kind": "invalid_output",
                            "message": "Donor browser result did not contain the required case outcomes.",
                            "environment_blocked": False,
                        })
                else:
                    operational_errors.append(
                        _process_error("donor_browser_evaluation", donor_runtime_cmd, donor_runtime_proc)
                    )
            except Exception as exc:
                donor_runtime_duration_ms = (time.perf_counter() - t0_donor_runtime) * 1000.0
                operational_errors.append(
                    _exception_error("donor_browser_evaluation", donor_runtime_cmd, exc)
                )

        # --- Stage 1: Focused Test Gate ---
        t0_foc = time.perf_counter()
        foc_cmd = [
            "npx",
            "--no-install",
            "tsx",
            "--test",
            "a11y-tools/tests/wcag-331-error-association.test.ts",
        ]
        try:
            foc_proc = subprocess.run(
                foc_cmd,
                cwd=ALLYS_TOOLS_DIR,
                capture_output=True,
                text=True,
                env=donor_env(),
                timeout=30,
            )
            foc_duration_ms = (time.perf_counter() - t0_foc) * 1000.0
            foc_passed, foc_failed = parse_tap_output(foc_proc.stdout)
            foc_ok = (foc_proc.returncode == 0 and foc_passed >= 6 and foc_failed == 0)
            if not foc_ok and foc_proc.returncode != 0:
                operational_errors.append(_process_error("focused_gate", foc_cmd, foc_proc))
        except Exception as exc:
            foc_duration_ms = (time.perf_counter() - t0_foc) * 1000.0
            foc_ok = False
            foc_passed = 0
            foc_failed = 1
            operational_errors.append(_exception_error("focused_gate", foc_cmd, exc))

        # --- Stage 2: Complete Ally Test Suite & Typecheck Gate (Optional / Deep) ---
        full_cmd = ["npm", "run", "check"]
        full_duration_ms = 0.0
        full_total = 0
        full_failed = 0
        full_ok = None  # None = not executed this run (ephemeral/fast path); not a fabricated pass
        if full_suite:
            t0_full = time.perf_counter()
            try:
                full_proc = subprocess.run(
                    full_cmd,
                    cwd=ALLYS_TOOLS_DIR,
                    capture_output=True,
                    text=True,
                    env=donor_env(),
                    timeout=120,
                )
                full_duration_ms = (time.perf_counter() - t0_full) * 1000.0
                full_total, full_failed = parse_tap_output(full_proc.stdout)
                full_ok = (full_proc.returncode == 0 and full_total >= 126 and full_failed == 0)
                if not full_ok and full_proc.returncode != 0:
                    operational_errors.append(
                        _process_error("full_suite_gate", full_cmd, full_proc)
                    )
            except Exception as exc:
                full_duration_ms = (time.perf_counter() - t0_full) * 1000.0
                full_ok = False
                full_total = 0
                full_failed = 1
                operational_errors.append(_exception_error("full_suite_gate", full_cmd, exc))

        # --- Stage 3: Full-Audit Integration Pipeline Gate (Optional / Deep) ---
        audit_cmd = [
            "npx",
            "--no-install",
            "tsx",
            "--test",
            "a11y-tools/tests/full-audit.test.ts",
        ]
        audit_duration_ms = 0.0
        audit_passed = 0
        audit_failed = 0
        audit_ok = None  # None = not executed this run (ephemeral/fast path); not a fabricated pass
        if full_suite:
            t0_audit = time.perf_counter()
            try:
                audit_proc = subprocess.run(
                    audit_cmd,
                    cwd=ALLYS_TOOLS_DIR,
                    capture_output=True,
                    text=True,
                    env=donor_env(),
                    timeout=120,
                )
                audit_duration_ms = (time.perf_counter() - t0_audit) * 1000.0
                audit_passed, audit_failed = parse_tap_output(audit_proc.stdout)
                audit_ok = (audit_proc.returncode == 0 and audit_passed >= 7 and audit_failed == 0)
                if not audit_ok and audit_proc.returncode != 0:
                    operational_errors.append(
                        _process_error("full_audit_integration_gate", audit_cmd, audit_proc)
                    )
            except Exception as exc:
                audit_duration_ms = (time.perf_counter() - t0_audit) * 1000.0
                audit_ok = False
                audit_passed = 0
                audit_failed = 1
                operational_errors.append(
                    _exception_error("full_audit_integration_gate", audit_cmd, exc)
                )

        # --- Stage 4: Direct DOM Snapshot & Contract Translation ---
        node_script = """
import { validateAriaSnapshot } from './a11y-tools/aria-validator/index.ts';

const url = 'https://example.test/checkout';
const nodes = [
  {
    selector: '#email',
    tagName: 'input',
    role: null,
    implicitRole: null,
    accessibleName: 'Email Address',
    focusable: true,
    interactive: true,
    text: '',
    html: '<input id="email" type="email" class="is-invalid" aria-invalid="true">',
    attributes: { id: 'email', type: 'email', class: 'is-invalid', 'aria-invalid': 'true' },
  },
  {
    selector: '#pwd',
    tagName: 'input',
    role: null,
    implicitRole: null,
    accessibleName: 'Password',
    focusable: true,
    interactive: true,
    text: '',
    html: '<input id="pwd" type="password" aria-invalid="true" aria-errormessage="pwd-err">',
    attributes: { id: 'pwd', type: 'password', 'aria-invalid': 'true', 'aria-errormessage': 'pwd-err' },
  },
  {
    selector: '#pwd-err',
    tagName: 'span',
    role: null,
    implicitRole: null,
    accessibleName: '',
    focusable: false,
    interactive: false,
    text: 'Password must be at least 12 characters.',
    html: '<span id="pwd-err">Password must be at least 12 characters.</span>',
    attributes: { id: 'pwd-err' },
  },
  {
    selector: '#name',
    tagName: 'input',
    role: null,
    implicitRole: null,
    accessibleName: 'Full Name',
    focusable: true,
    interactive: true,
    text: '',
    html: '<input id="name" type="text" aria-invalid="true" aria-describedby="name-desc">',
    attributes: { id: 'name', type: 'text', 'aria-invalid': 'true', 'aria-describedby': 'name-desc' },
  },
  {
    selector: '#name-desc',
    tagName: 'span',
    role: null,
    implicitRole: null,
    accessibleName: '',
    focusable: false,
    interactive: false,
    text: 'Name is required.',
    html: '<span id="name-desc">Name is required.</span>',
    attributes: { id: 'name-desc' },
  }
];

const result = validateAriaSnapshot(url, nodes);
console.log(JSON.stringify(result));
"""
        findings: list[dict[str, Any]] = []
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            eval_proc = subprocess.run(
                ["npx", "--no-install", "tsx", "-e", node_script],
                cwd=ALLYS_TOOLS_DIR,
                capture_output=True,
                text=True,
                env=donor_env(),
                timeout=30,
            )
            if eval_proc.returncode == 0 and eval_proc.stdout.strip():
                raw_result = json.loads(eval_proc.stdout.strip())
                for idx, raw_f in enumerate(raw_result.get("findings", []), start=1):
                    # Preserve unverified source status and set needs_review: true (human confirmation boundary)
                    contract_finding = {
                        "schema_version": SCHEMA_VERSION,
                        "finding_id": f"find-ally-331-{idx:03d}",
                        "rule_id": f"wcag-{raw_f.get('wcagRule', '3.3.1').replace('.', '')}",
                        "severity": raw_f.get("severity", "serious"),
                        "summary": raw_f.get("description", "Input marked invalid lacks error message"),
                        "target": raw_f.get("selector", "#target"),
                        "evidence": [
                            {
                                "tool": raw_f.get("tool", "aria-validator"),
                                "html": raw_f.get("html", ""),
                                "source_status": raw_f.get("status", "unverified"),
                                "verification_state": "unverified_deterministic_finding",
                                "timestamp": now_iso,
                            }
                        ],
                        "evidence_kind": "deterministic",
                        "needs_review": True,  # Truthful: automated finding is unverified by human
                        "status": "open",
                    }
                    validated = validate_contract("A11yFinding", contract_finding)
                    findings.append(validated)
            elif eval_proc.returncode != 0:
                operational_errors.append(
                    _process_error(
                        "dom_snapshot_evaluation",
                        ["npx", "--no-install", "tsx", "-e", "<snapshot-probe>"],
                        eval_proc,
                    )
                )
            else:
                operational_errors.append({
                    "stage": "dom_snapshot_evaluation",
                    "command": "npx --no-install tsx -e <snapshot-probe>",
                    "error_kind": "empty_output",
                    "exit_code": eval_proc.returncode,
                    "stderr": eval_proc.stderr[:500],
                    "environment_blocked": _is_environment_blocked(eval_proc.stderr, eval_proc.stdout or ""),
                })
        except Exception as exc:
            operational_errors.append(
                _exception_error(
                    "dom_snapshot_evaluation",
                    ["npx", "--no-install", "tsx", "-e", "<snapshot-probe>"],
                    exc,
                )
            )

        # --- Authentic Donor/Destination Parity Evaluation ---
        target_outcomes = {
            "invalid_input_missing_error_ref": any(f.get("target") == "#email" for f in findings),
            "invalid_input_with_valid_errormessage": any(f.get("target") == "#pwd" for f in findings),
            "invalid_input_with_valid_describedby": any(f.get("target") == "#name" for f in findings),
        }
        donor_outcomes = donor_result.get("outcomes", {}) if donor_runtime_ok else {}
        parity_comparisons = [
            {
                "case_id": case_id,
                "target_flagged": target_flagged,
                "donor_flagged": donor_outcomes.get(case_id),
                "matches": (
                    case_id in donor_outcomes
                    and target_flagged == donor_outcomes.get(case_id)
                ),
            }
            for case_id, target_flagged in target_outcomes.items()
        ]
        donor_parity_verified = (
            donor_source_ok
            and donor_runtime_ok
            and len(parity_comparisons) == 3
            and all(c["matches"] for c in parity_comparisons)
        )

        # full_ok/audit_ok are None when full_suite=False (stage not executed, not a fabricated pass);
        # `is not False` lets the ephemeral fast path gate on what it actually ran without claiming
        # the skipped deep stages passed.
        all_stages_passed = (
            foc_ok
            and donor_source_ok
            and donor_runtime_ok
            and full_ok is not False
            and audit_ok is not False
            and len(findings) >= 1
            and donor_parity_verified
            and len(operational_errors) == 0
        )

        return {
            "wave": "A2",
            "migration_kind": "source_backed_runtime_integration",
            "receipt_kind": "local_working_tree_candidate_receipt" if target_fp.get("is_dirty") else "clean_commit_receipt",
            "status": "parity_verified" if all_stages_passed else "failed",
            "all_stages_passed": all_stages_passed,
            "representative_inputs": [
                {
                    "case_id": "invalid_input_missing_error_ref",
                    "purpose": "defective invalid control with no error association",
                },
                {
                    "case_id": "invalid_input_with_valid_errormessage",
                    "purpose": "valid aria-errormessage association",
                },
                {
                    "case_id": "invalid_input_with_valid_describedby",
                    "purpose": "valid aria-describedby association",
                },
            ],
            "target": {
                "name": "allys-tools",
                "path": str(ALLYS_TOOLS_DIR),
                "fingerprint": target_fp,
                "role": "canonical_runtime_destination",
            },
            "donor": {
                "name": "wcag-auditor",
                "path": str(WCAG_AUDITOR_DIR),
                "fingerprint": donor_fp,
                "rule_ported": "input-assistance-error-msg (WCAG 3.3.1)",
                "role": "donor_parity_source",
                "source_invoked": donor_source_ok,
                "browser_runtime_invoked": donor_runtime_ok,
                "runtime_outcomes": donor_outcomes,
                "runtime_violations": donor_result.get("violations", []),
                "donor_parity_verified": donor_parity_verified,
                "parity_comparisons": parity_comparisons,
            },
            "stages": {
                "donor_source_invocation": {
                    "command": shlex.join(donor_source_cmd),
                    "duration_ms": round(donor_source_duration_ms, 2),
                    "rule_id": donor_source.get("rule_id"),
                    "wcag_criterion": donor_source.get("wcag_criterion"),
                    "source_path": donor_source.get("source_path"),
                    "passed": donor_source_ok,
                },
                "donor_browser_evaluation": {
                    "command": shlex.join(donor_runtime_cmd),
                    "duration_ms": round(donor_runtime_duration_ms, 2),
                    "case_count": len(donor_result.get("outcomes", {})),
                    "passed": donor_runtime_ok,
                },
                "focused_parity_gate": {
                    "command": shlex.join(foc_cmd),
                    "duration_ms": round(foc_duration_ms, 2),
                    "passed_tests": foc_passed,
                    "failed_tests": foc_failed,
                    "passed": foc_ok,
                },
                "full_suite_and_typecheck_gate": {
                    "command": shlex.join(full_cmd),
                    "skipped": not full_suite,
                    "duration_ms": round(full_duration_ms, 2),
                    "total_tests_passed": full_total,
                    "failed_tests": full_failed,
                    "passed": full_ok,
                },
                "full_audit_integration_gate": {
                    "command": shlex.join(audit_cmd),
                    "skipped": not full_suite,
                    "duration_ms": round(audit_duration_ms, 2),
                    "passed_tests": audit_passed,
                    "failed_tests": audit_failed,
                    "manifest_coverage_verified": audit_ok,
                    "passed": audit_ok,
                },
            },
            "findings": findings,
            "operational_errors": operational_errors,
            "environment_blocked": bool(operational_errors) and all(
                error.get("environment_blocked", False) for error in operational_errors
            ),
            "recovery_behavior": {
                "runtime_mutation_mode": "read_only",
                "partial_state_possible": False,
                "rerun_safe": True,
                "environment_failures_fail_closed": True,
                "evidence_write_requires_explicit_record": True,
            },
            "epistemic_boundary": {
                "source_status": "unverified",
                "needs_review_preserved": True,
                "human_confirmation_claimed": False,
            },
            "generated_at": now_iso,
        }

    @classmethod
    def execute_keyboard_overlay_reconciliation_gate(cls) -> dict[str, Any]:
        """A3: Source-backed inventory of the three keyboard navigation overlays.

        Declared feature/disposition analysis is retained as analysis, but it cannot pass unless
        every configured donor exists, has a readable manifest and source files, and yields a
        meaningful Git fingerprint. Missing source state is never replaced with historical values.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        overlays_info: dict[str, Any] = {}
        source_errors: list[str] = []
        dirs = [
            ("kb-overlay", KB_OVERLAY_DIR, "canonical_anchor"),
            ("keyboard-nav-overlay", KEYBOARD_NAV_OVERLAY_DIR, "duplicate_donor"),
            ("keyboard-nav-overlay-94bf7e", KEYBOARD_NAV_OVERLAY_94BF7E_DIR, "duplicate_donor"),
        ]

        for name, repo_path, default_role in dirs:
            source_available = repo_path.is_dir()
            manifest_file = repo_path / "manifest.json"
            manifest_valid = False
            manifest_error: str | None = None
            permissions: list[str] = []
            host_scope: list[str] = []
            manifest_v: int | None = None
            if not source_available:
                manifest_error = "configured donor directory does not exist"
            elif not manifest_file.is_file():
                manifest_error = "manifest.json is missing"
            else:
                try:
                    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    permissions_value = manifest_data.get("permissions")
                    manifest_version_value = manifest_data.get("manifest_version")
                    if not isinstance(permissions_value, list) or any(
                        not isinstance(permission, str) or not permission
                        for permission in permissions_value
                    ):
                        raise ValueError("permissions must be a list of non-empty strings")
                    if not isinstance(manifest_version_value, int):
                        raise ValueError("manifest_version must be an integer")
                    permissions = permissions_value
                    # Host reach is not confined to `permissions`: an extension also reaches
                    # every page it injects a content script into, and optional host grants count.
                    scope: list[str] = []
                    for key in ("host_permissions", "optional_host_permissions"):
                        declared = manifest_data.get(key)
                        if isinstance(declared, list):
                            scope.extend(str(entry) for entry in declared)
                    for content_script in manifest_data.get("content_scripts", []) or []:
                        matches = content_script.get("matches") if isinstance(content_script, dict) else None
                        if isinstance(matches, list):
                            scope.extend(str(entry) for entry in matches)
                    host_scope = sorted(set(scope))
                    manifest_v = manifest_version_value
                    manifest_valid = True
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    manifest_error = f"manifest.json is invalid: {error}"

            code_size = 0
            code_files_count = 0
            if source_available:
                try:
                    for f in repo_path.glob("**/*"):
                        relative_parts = f.relative_to(repo_path).parts
                        if f.is_file() and not any(part.startswith(".") for part in relative_parts):
                            if f.suffix in {".js", ".ts", ".html", ".css", ".json"}:
                                code_size += f.stat().st_size
                                code_files_count += 1
                except OSError as error:
                    source_errors.append(f"{name}: source inventory could not be read: {error}")

            fingerprint = get_git_fingerprint(repo_path)
            fingerprint_verified = is_meaningful_git_fingerprint(fingerprint)

            if manifest_error:
                source_errors.append(f"{name}: {manifest_error}")
            if code_files_count == 0:
                source_errors.append(f"{name}: no inspectable extension source files found")
            if not fingerprint_verified:
                source_errors.append(f"{name}: meaningful Git/source fingerprint unavailable")

            if name == "kb-overlay":
                features = [
                    "spatial_nav",
                    "visual_focus_ring",
                    "keyboard_shortcuts",
                    "settings_storage",
                    "aria_tree_scan",
                    "shadow_dom_encapsulation",
                    "mutation_observer_updates",
                    "global_chrome_command",
                ]
                flaws: list[str] = []
                active_status = "retained_canonical"
            elif name == "keyboard-nav-overlay":
                features = ["spatial_nav", "visual_focus_ring"]
                flaws = ["syntax_typos_in_content_js", "global_css_leakage_no_shadow_dom"]
                active_status = "superseded_by_kb-overlay"
            else:
                features = ["spatial_nav"]
                flaws = ["unencapsulated_dom", "incomplete_event_handling"]
                active_status = "superseded_by_kb-overlay"

            overlays_info[name] = {
                "role": default_role,
                "manifest_version": manifest_v,
                "features": features,
                "feature_inventory_kind": "declared_analysis",
                "permissions": permissions,
                "host_scope": host_scope,
                "code_size_bytes": code_size,
                "code_files_count": code_files_count,
                "active_status": active_status,
                "git_fingerprint": fingerprint,
                "source_available": source_available,
                "manifest_valid": manifest_valid,
                "fingerprint_verified": fingerprint_verified,
            }
            if manifest_error:
                overlays_info[name]["source_error"] = manifest_error
            if flaws:
                overlays_info[name]["flaws_identified"] = flaws

        passed = (
            not source_errors
            and overlays_info["kb-overlay"]["active_status"] == "retained_canonical"
            and len(overlays_info["kb-overlay"]["features"]) >= 8
            and "flaws_identified" not in overlays_info["kb-overlay"]
            and all(
                overlay.get("source_available") is True
                and overlay.get("manifest_valid") is True
                and overlay.get("fingerprint_verified") is True
                and overlay.get("code_size_bytes", 0) > 0
                for overlay in overlays_info.values()
            )
        )

        return {
            "receipt_version": "accessibility-a3-analysis-v2",
            "all_stages_passed": passed,
            "canonical_target": "kb-overlay",
            "matrix": overlays_info,
            "source_verification": {
                "passed": not source_errors,
                "errors": source_errors,
                "donors_checked": len(dirs),
            },
            "recommendation": (
                "Source inventory supports kb-overlay as the canonical candidate; behavioral and "
                "owner-controlled convergence gates remain outstanding."
                if passed
                else "Canonical selection is not established because one or more donor sources could not be verified."
            ),
            "generated_at": now_iso,
        }

    @classmethod
    def execute_wcag_rule_candidates_gate(cls) -> dict[str, Any]:
        """A4: Batch evaluation of 20 backlog candidate WCAG Auditor rules with regression evidence."""
        target_fp = get_git_fingerprint(ALLYS_TOOLS_DIR)
        donor_fp = get_git_fingerprint(WCAG_AUDITOR_DIR)

        # Parse live wcag-auditor rules via AST
        rules_dir = WCAG_AUDITOR_DIR / "wcag_auditor" / "rules"
        rule_to_criterion: dict[str, str] = {}
        asserted_rules: set[str] = set()
        asserted_criteria: set[str] = set()
        asserted_modules: list[str] = []

        if rules_dir.is_dir():
            for rule_file in sorted(rules_dir.glob("*.py")):
                if rule_file.name == "__init__.py":
                    continue
                asserted_modules.append(rule_file.name)
                try:
                    tree = ast.parse(rule_file.read_text(encoding="utf-8"))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "RuleMetadata":
                            rid = None
                            sc = None
                            for kw in node.keywords:
                                if kw.arg == "id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                    rid = kw.value.value
                                    asserted_rules.add(rid)
                                elif kw.arg == "wcag_criterion" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                    sc = kw.value.value
                                    asserted_criteria.add(sc)
                            if rid and sc:
                                rule_to_criterion[rid] = sc
                except Exception:
                    pass

        expected_rule_criteria = {
            "inline-language-change": "3.1.2",
            "audio-description-track": "1.2.5",
            "adaptable-landmarks": "1.3.1",
            "enough-time-controls": "2.2.2",
            "link-purpose": "2.4.4",
            "focus-not-obscured": "2.4.11",
            "pointer-gestures": "2.5.1",
            "pointer-cancellation": "2.5.2",
            "dragging-movements": "2.5.7",
            "predictable-navigation": "3.2.2",
            "input-assistance-error-msg": "3.3.1",
            "labels-or-instructions": "3.3.2",
            "error-suggestion": "3.3.3",
            "required-field-indicators": "3.3.2",
            "redundant-entry": "3.3.7",
            "accessible-authentication": "3.3.8",
            "identify-input-purpose": "1.3.5",
            "status-messages": "4.1.3",
        }

        exact_criteria_matched = all(
            rule_to_criterion.get(r) == expected_sc
            for r, expected_sc in expected_rule_criteria.items()
        )

        sensitivity_passed = (
            exact_criteria_matched
            and set(expected_rule_criteria.keys()).issubset(asserted_rules)
            and len(asserted_modules) >= 5
            and is_meaningful_git_fingerprint(donor_fp)
            and is_meaningful_git_fingerprint(target_fp)
        )

        source_derived_assertions = {
            "donor_source_path": "wcag_auditor/rules",
            "asserted_rules": sorted(asserted_rules),
            "asserted_criteria": sorted(asserted_criteria),
            "asserted_modules": sorted(asserted_modules),
            "rule_criterion_mappings": {r: rule_to_criterion[r] for r in sorted(expected_rule_criteria.keys()) if r in rule_to_criterion},
            "sensitivity_test_passed": sensitivity_passed,
        }

        cases_file = Path(__file__).resolve().parent.parent.parent.parent / "accessibility" / "evidence" / "A1-parity-cases.json"
        if cases_file.exists():
            try:
                cases_data = json.loads(cases_file.read_text(encoding="utf-8"))
                cases = cases_data.get("cases", [])
            except Exception:
                cases = []
        else:
            cases = []

        catalog = AccessibilityEngine.evaluate_wcag_auditor_backlog_catalog(cases)
        all_passed = (
            catalog.get("total_candidates_evaluated") == 20
            and catalog.get("status") == "all_backlog_candidates_evidenced"
            and all(isinstance(e.get("finding"), dict) for e in catalog.get("evaluations", []))
            and sensitivity_passed
        )
        # The "zero false positives on compliant markup" claim is executed, not asserted.
        compliant_markup = (
            '<label for="email">Email</label>'
            '<input id="email" type="email" aria-describedby="email-help">'
            '<p id="email-help">We never share it.</p>'
            '<table><tr><th scope="col">Name</th></tr><tr><td>Ada</td></tr></table>'
            '<img src="logo.png" alt="Company logo">'
        )
        false_positives = AccessibilityEngine.audit_html_snippet(
            compliant_markup, source_url="snippet://a4-false-positive-probe"
        )
        sample = [e["finding"] for e in catalog.get("evaluations", []) if isinstance(e.get("finding"), dict)][:3]

        return {
            "all_stages_passed": all_passed and not false_positives,
            "wave": "A4",
            "status": "parity_verified" if (all_passed and not false_positives) else "unverified",
            "catalog_evaluation": catalog,
            "heuristic_findings_sample": sample,
            "false_positive_probe_passed": not false_positives,
            "source_derived_assertions": source_derived_assertions,
            "target": {
                "name": "allys-tools",
                "path": str(ALLYS_TOOLS_DIR),
                "fingerprint": target_fp,
                "role": "canonical_runtime_destination",
            },
            "donor": {
                "name": "wcag-auditor",
                "path": str(WCAG_AUDITOR_DIR),
                "fingerprint": donor_fp,
                "role": "heuristic_rule_donor",
            },
        }

    @classmethod
    def execute_a11y_kitchen_roundtrip_gate(cls) -> dict[str, Any]:
        """A5: Round-trip A11yFinding contract through A11y Kitchen interactive teaching surface."""
        html_sample = '<input id="email" class="is-invalid">'
        findings = AccessibilityEngine.audit_html_snippet(html_sample, source_url="kitchen://module-01")
        if not findings:
            finding = AccessibilityEngine.create_ai_assisted_finding(
                "find-wcag-331-kitchen-001",
                "wcag-3.3.1-error-identification",
                "Form control #email lacks aria-describedby linkage.",
                "input#email",
                "Form control missing error description",
                severity="critical",
            )
        else:
            finding = findings[0]
            finding["finding_id"] = "find-wcag-331-kitchen-001"
            finding["target"] = "input#email"

        kitchen_receipt = AccessibilityEngine.roundtrip_kitchen_learning_finding(finding)
        kitchen_fp = get_git_fingerprint(A11Y_KITCHEN_DIR)

        canonical = kitchen_receipt.get("canonical_finding")
        has_required_fields = isinstance(canonical, dict) and all(k in canonical for k in ("schema_version", "finding_id", "rule_id", "severity", "target", "evidence", "evidence_kind"))
        modes = kitchen_receipt.get("modes", {})
        has_all_modes = all(m in modes and len(modes[m]) > 20 for m in ("advocate", "builder", "presenter"))
        target_retained = kitchen_receipt.get("target_element") == finding.get("target")
        finding_equal = (canonical == finding)

        source_verified = A11Y_KITCHEN_DIR.is_dir() and is_meaningful_git_fingerprint(kitchen_fp)
        all_passed = (
            source_verified
            and has_required_fields
            and has_all_modes
            and target_retained
            and finding_equal
            and kitchen_receipt.get("roundtrip_status") == "verified"
            and kitchen_receipt.get("evidence_loss") is False
        )
        kitchen_receipt["all_stages_passed"] = all_passed
        kitchen_receipt["source_verification_passed"] = source_verified
        kitchen_receipt["kitchen_fingerprint"] = kitchen_fp
        return kitchen_receipt

    @classmethod
    def execute_keyboard_overlay_consolidation_gate(cls) -> dict[str, Any]:
        """A6: Verify kb-overlay as the single canonical overlay and report donor retirement status.

        Freezing a donor repository is an owner action. This gate measures whether the
        consolidation is justified and what remains outstanding; it never performs it.
        """
        reconciliation = cls.execute_keyboard_overlay_reconciliation_gate()
        reconciliation_passed = reconciliation.get("all_stages_passed", False)
        matrix = reconciliation.get("matrix", {})

        canonical = matrix.get("kb-overlay", {})
        canonical_permissions = sorted(canonical.get("permissions", []))
        canonical_scope = sorted(canonical.get("host_scope", []))
        duplicates = {name: entry for name, entry in matrix.items() if name != "kb-overlay"}

        def scope_is_broad(scope: list[str]) -> bool:
            return any(entry in BROAD_HOST_PATTERNS for entry in scope)

        permission_analysis = {
            "canonical_api_permissions": canonical_permissions,
            "canonical_host_scope": canonical_scope,
            "broad_api_permission_vocabulary": sorted(BROAD_EXTENSION_PERMISSIONS),
            "broad_host_patterns": sorted(BROAD_HOST_PATTERNS),
            "canonical_broad_api_permissions": sorted(set(canonical_permissions) & BROAD_EXTENSION_PERMISSIONS),
            "canonical_host_scope_is_broad": scope_is_broad(canonical_scope),
            "donor_api_permissions": {
                name: sorted(entry.get("permissions", [])) for name, entry in sorted(duplicates.items())
            },
            "donor_host_scope": {
                name: sorted(entry.get("host_scope", [])) for name, entry in sorted(duplicates.items())
            },
        }
        permission_analysis["donor_broad_api_permissions"] = {
            name: sorted(set(perms) & BROAD_EXTENSION_PERMISSIONS)
            for name, perms in permission_analysis["donor_api_permissions"].items()
        }
        permission_analysis["donor_only_api_permissions"] = {
            name: sorted(set(perms) - set(canonical_permissions))
            for name, perms in permission_analysis["donor_api_permissions"].items()
        }
        # The canonical overlay is compared against what it would replace. It is not called
        # minimized: it injects on every page, exactly as its donors do.
        permission_analysis["canonical_no_broader_than_donors"] = all(
            (set(canonical_permissions) & BROAD_EXTENSION_PERMISSIONS) <= set(perms)
            and set(canonical_scope) <= set(permission_analysis["donor_host_scope"][name])
            for name, perms in permission_analysis["donor_api_permissions"].items()
        )
        permission_analysis["minimized_permissions_verified"] = (
            not permission_analysis["canonical_broad_api_permissions"]
            and not permission_analysis["canonical_host_scope_is_broad"]
        )
        permission_analysis["minimization_outstanding"] = sorted(
            {
                f"content script host scope {entry!r} is not narrowed"
                for entry in canonical_scope
                if entry in BROAD_HOST_PATTERNS
            }
        )

        donor_retirement = {
            name: {
                "active_status": entry.get("active_status"),
                "source_present": entry.get("source_available"),
                "working_tree_dirty": entry.get("git_fingerprint", {}).get("is_dirty"),
                "head": entry.get("git_fingerprint", {}).get("short"),
                "retirement_performed": False,
                "owner_action_required": True,
            }
            for name, entry in sorted(duplicates.items())
        }

        all_stages_passed = (
            reconciliation_passed
            and not permission_analysis["canonical_broad_api_permissions"]
            and permission_analysis["canonical_no_broader_than_donors"]
            and len(donor_retirement) == 2
            and all(entry["source_present"] for entry in donor_retirement.values())
            and all(str(entry["active_status"]).startswith("superseded_by") for entry in donor_retirement.values())
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "A6",
            "status": "consolidation_proposed" if all_stages_passed else "consolidation_unverified",
            "all_stages_passed": all_stages_passed,
            "artifact_kind": "reference_prototype",
            "proposed_canonical_anchor": "kb-overlay",
            "manifest_version": canonical.get("manifest_version"),
            "proposed_frozen_donors": sorted(duplicates),
            "features_targeted": sorted(canonical.get("features", [])),
            "canonical_permission_surface": {
                "api_permissions": canonical_permissions,
                "host_scope": canonical_scope,
            },
            "permission_analysis": permission_analysis,
            "donor_retirement": donor_retirement,
            "proposed_disposition": "proposed_anchor",
            # Acceptance stays false while the owner freeze and the scope narrowing are outstanding.
            "migration_acceptance_verified": False,
            "reconciliation_matrix": matrix,
        }
