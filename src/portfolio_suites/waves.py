"""Automated wave gate execution and evidence generation across all eight suites."""

from __future__ import annotations

import fcntl
import hashlib
import inspect
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .approvals import canonical_digest
from .adapters.accessibility import AccessibilitySourceAdapter
from .adapters.agent_reliability import AgentReliabilitySourceAdapter
from .adapters.brand_publishing import BrandPublishingSourceAdapter
from .adapters.discovery_decision import DiscoveryDecisionSourceAdapter
from .adapters.game_design import GameDesignSourceAdapter
from .adapters.model_behavior import ModelBehaviorSourceAdapter
from .adapters.operator_os import OperatorOSSourceAdapter
from .adapters.production_house import ProductionHouseSourceAdapter
from .engines.brand_publishing import BrandPublishingEngine
from .paths import ConfinementError, open_confined_directory
from .registry import (
    SUITES_ROOT,
    evidence_errors,
    evidence_ineligibility_reason,
    get_suite,
    load_suites,
)
from .txn import (
    CommitUncertain,
    OccupantConflict,
    commit_replacement,
    discard_temp,
    verify_payload,
    write_temp_payload,
)


@dataclass
class WaveRunResult:
    suite_id: str
    wave_id: str
    passed: bool  # True when the gate executed and passed
    message: str
    evidence_path: str | None = None
    data: dict[str, Any] | None = None
    execution_kind: str = "unintegrated_specification"
    prototype_passed: bool = False
    # Work and promotion are separate axes. A completed analysis may be only a historical
    # review or may have inspected donor source; carrying the claim here prevents CLI/API
    # callers from flattening both into the same generic "analysis" outcome.
    claim_kind: str | None = None
    claim_level: str | None = None
    # Recording diagnostic when --record did not complete cleanly. A pre-commit refusal means
    # no write; a committed_unverified result means replacement occurred but could not be
    # verified. Those states must never share the same operator message.
    record_note: str | None = None
    # Machine-readable recording outcome. Gate success and evidence persistence are separate
    # operations: a passing gate must never make a rejected --record request look successful.
    record_status: str = "not_requested"


@dataclass(frozen=True)
class EvidenceCommitUnverified:
    """A replacement occurred, but its durability or canonical path could not be verified."""

    declared_path: str
    note: str


_RECORD_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_MUTEX = threading.Lock()


def _wave_for_evidence(rel_path: str) -> tuple[str, dict[str, Any]] | None:
    """Return the one suite/wave pair declaring an evidence path; fail closed on zero or duplicates.

    The suite ID comes back with the wave because the receipt spec is keyed by both, and
    deriving the suite from the evidence path instead would assume the directory name and
    the manifest ID never diverge.
    """
    matches: list[tuple[str, dict[str, Any]]] = []
    for suite_id, manifest in load_suites().items():
        for wave in manifest.get("waves", []):
            if wave.get("evidence") == rel_path:
                matches.append((suite_id, wave))
    return matches[0] if len(matches) == 1 else None


def _record_lock(evidence_file: Path) -> threading.Lock:
    with _LOCKS_MUTEX:
        return _RECORD_LOCKS.setdefault(evidence_file, threading.Lock())


def _skipped_stages(data: Any) -> list[str]:
    """Names of receipt stages that were not executed on this run."""
    stages = data.get("stages", {}) if isinstance(data, dict) else {}
    return sorted(name for name, stage in stages.items() if isinstance(stage, dict) and stage.get("skipped"))


def _record_evidence(
    wave: dict[str, Any],
    data: Any,
    write_evidence: bool,
    passed: bool,
) -> str | EvidenceCommitUnverified | None:
    """Record evidence ONLY when requested, the gate passed, AND the candidate validates.

    The receipt path comes from the wave manifest's own `evidence` field, so a runner cannot
    write to a path the registry does not already know about.

    Writes a temp sibling, runs `evidence_errors` against it, and only then atomically
    replaces the retained receipt. The commit is bound to the validated bytes twice over:
    the digest of the buffer that was validated is re-derived from the object the temp name
    reaches immediately before the swap (so bytes altered after validation are refused, not
    installed), and the replacement is a compare-and-swap against the retained receipt's
    identity at the start of this recording (so a receipt another process committed or
    edited meanwhile is preserved rather than replaced). A pre-commit rejection leaves the
    prior receipt byte-for-byte unchanged and returns None. Once replacement succeeds,
    later durability or canonical-path failures return :class:`EvidenceCommitUnverified`;
    they must never be reported as a rejection that retained the prior bytes.

    This is stricter than `suites validate`, which only inspects completed waves: a wave
    with no declared recovery claim is refused outright, because there would be no contract
    to check the bytes against. Callers wanting to report *why* nothing was written should
    consult `evidence_ineligibility_reason` rather than inferring it from the None.
    """
    if not (write_evidence and passed):
        return None

    rel_path = wave.get("evidence")
    if not isinstance(rel_path, str) or not rel_path:
        return None
    try:
        # Exactly one wave may own a receipt path, and it must be this one.
        owner = _wave_for_evidence(rel_path)
    except (OSError, ValueError, KeyError):
        return None
    if owner is None or owner[1].get("id") != wave.get("id"):
        return None
    owner_suite_id = owner[0]

    # A manifest is data, not authority to choose an arbitrary filesystem target. Require the
    # canonical <suite-id>/evidence/<filename> shape before creating any directories, and
    # enforce suite-ownership boundary confinement under O_NOFOLLOW.
    rel_parts = PurePosixPath(rel_path).parts
    if (
        len(rel_parts) != 3
        or rel_parts[0] != owner_suite_id
        or rel_parts[1] != "evidence"
        or rel_parts[2] in {"", ".", ".."}
        or PurePosixPath(rel_path).is_absolute()
    ):
        return None
    suite_dir, _, filename = rel_parts
    evidence_dir = SUITES_ROOT / suite_dir / "evidence"
    evidence_file = evidence_dir / filename

    try:
        evidence_dir_fd = open_confined_directory(SUITES_ROOT, f"{suite_dir}/evidence", create=True)
    except (OSError, ConfinementError):
        return None

    try:
        payload = (
            data.encode("utf-8") if isinstance(data, str) else json.dumps(data, indent=2).encode("utf-8")
        )
    except (TypeError, ValueError):
        os.close(evidence_dir_fd)
        return None
    payload_digest = hashlib.sha256(payload).hexdigest()

    # The compare-and-swap expectation is captured before any validation work: whatever
    # occupies the receipt name when this recording started is the only thing this
    # recording may displace. The expectation is the prior receipt's *content digest*, not
    # merely its identity -- an in-place truncate-and-rewrite by another writer keeps the
    # inode while changing every byte, and identity alone would bless that loss. A
    # concurrent recording that commits during our validation changes either the bytes or
    # the inode, and the commit refuses instead of clobbering their receipt.
    try:
        prior_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=evidence_dir_fd)
        try:
            prior_bytes = os.read(prior_fd, 64 * 1024 * 1024)
        finally:
            os.close(prior_fd)
        prior_digest: str | None = hashlib.sha256(prior_bytes).hexdigest()
    except OSError:
        prior_digest = None

    committed = False

    def committed_unverified(reason: str) -> EvidenceCommitUnverified:
        return EvidenceCommitUnverified(
            declared_path=rel_path,
            note=(
                f"receipt replacement committed for {rel_path}, but post-commit verification "
                f"failed ({reason}); current receipt state must be inspected"
            ),
        )

    temp = None
    try:
        with _record_lock(evidence_file):
            fcntl.flock(evidence_dir_fd, fcntl.LOCK_EX)
            try:
                temp = write_temp_payload(
                    evidence_dir_fd,
                    evidence_file.stem,
                    payload,
                    suffix=evidence_file.suffix,
                )
                if evidence_errors(wave, evidence_dir / temp.name, owner_suite_id):
                    return None

                # Bind the commit to the validated bytes. Validation ran against a
                # pathname; this re-derives the digest from the object that pathname
                # reaches right now, through an identity-checked descriptor, so bytes
                # substituted after validation are refused here rather than installed.
                try:
                    verify_payload(evidence_dir_fd, temp, payload_digest)
                except OccupantConflict:
                    return None

                kwargs = (
                    {"expected_absent": True}
                    if prior_digest is None
                    else {"expected_digest": prior_digest}
                )
                candidate = temp
                temp = None
                try:
                    commit_replacement(evidence_dir_fd, filename, candidate, **kwargs)
                except OccupantConflict:
                    # The retained receipt changed identity while we validated: it belongs
                    # to a newer recording now, and destroying it would lose their work.
                    return None
                except CommitUncertain as error:
                    committed = True
                    return committed_unverified(str(error))

                # Replacement is the commit point. Everything after it verifies durability and
                # canonical naming, and therefore has a distinct outcome when it fails.
                try:
                    os.fsync(evidence_dir_fd)
                    current_dir_stat = os.stat(evidence_dir)
                    pinned_dir_stat = os.fstat(evidence_dir_fd)
                    if (current_dir_stat.st_dev, current_dir_stat.st_ino) != (
                        pinned_dir_stat.st_dev,
                        pinned_dir_stat.st_ino,
                    ):
                        committed = True
                        return committed_unverified(
                            "canonical evidence directory no longer names the pinned directory"
                        )
                    installed_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=evidence_dir_fd)
                    try:
                        installed_stat = os.fstat(installed_fd)
                    finally:
                        os.close(installed_fd)
                    current_file_stat = os.stat(evidence_file)
                    if (current_file_stat.st_dev, current_file_stat.st_ino) != (
                        installed_stat.st_dev,
                        installed_stat.st_ino,
                    ):
                        committed = True
                        return committed_unverified(
                            "canonical evidence path no longer names the installed receipt"
                        )
                except OSError as error:
                    committed = True
                    return committed_unverified(str(error))
            finally:
                if temp is not None:
                    discard_temp(evidence_dir_fd, temp)
                fcntl.flock(evidence_dir_fd, fcntl.LOCK_UN)
    except OSError as error:
        return committed_unverified(str(error)) if committed else None
    finally:
        os.close(evidence_dir_fd)
    return str(evidence_file)


def classify_wave_spec(wave_spec: dict[str, Any], has_runner: bool = True) -> str:
    """Classify the intended execution kind of a wave specification.

    This reports the *work* axis only -- what the wave's gate does. How much the gate
    actually demonstrated is the separate promotion axis carried on `recovery_claim.level`,
    and callers that display one must display the other: an analysis milestone whose runner
    only exercised a suite-local fixture and one that parsed real donor source both classify
    here as completed analysis, and collapsing them is how 35 prototype-level claims came to
    be reported as verified.
    """
    manifest_status = wave_spec.get("status", "specified")
    claim = wave_spec.get("recovery_claim", {}) or {}
    claim_kind = claim.get("kind")
    claim_level = claim.get("level")
    if manifest_status == "complete":
        if claim_kind == "runtime" and claim_level == "source_executed":
            return "verified_source_execution"
        if claim_kind == "runtime" and claim_level == "parity_verified":
            return "verified_runtime_recovery"
        if claim_kind == "adoption" or claim_level == "adopted":
            return "verified_adoption"
        if claim_kind == "convergence" or claim_level == "converged":
            return "verified_convergence"
        if claim_kind == "resolution":
            return "verified_resolution"
        if claim_kind == "analysis":
            return "verified_analysis"
        return "unintegrated_specification"
    return "prototype_check" if has_runner else "unintegrated_specification"


def format_wave_tag(
    execution_kind: str,
    passed: bool,
    prototype_passed: bool = False,
    claim_level: str | None = None,
) -> str:
    """Return a display tag that preserves both execution and promotion depth."""
    if execution_kind == "error":
        return "[ERROR]"
    if prototype_passed:
        return "[PROTOTYPE]"
    if execution_kind == "verified_runtime_recovery" and passed:
        return "[RECOVERED]"
    if execution_kind == "verified_analysis" and passed:
        if claim_level == "reviewed_historical_analysis":
            return "[HISTORICAL]"
        if claim_level == "source_inspected":
            return "[INSPECTED]"
        return "[ANALYSIS]"
    if execution_kind == "verified_source_execution" and passed:
        return "[SOURCE-RUN]"
    if execution_kind == "verified_adoption" and passed:
        return "[ADOPTED]"
    if execution_kind == "verified_convergence" and passed:
        return "[CONVERGED]"
    if execution_kind == "verified_resolution" and passed:
        return "[RESOLVED]"
    if execution_kind == "fast_probe" and passed:
        return "[FAST-PROBE]"
    if execution_kind == "prototype_check" and (prototype_passed or passed):
        return "[PROTOTYPE]"
    if execution_kind == "unverifiable_environment":
        return "[UNVERIFIABLE]"
    if execution_kind == "unintegrated_specification":
        return "[SPECIFIED]"
    return "[FAIL]"


class WaveRunner:
    """Execute wave verification gates and generate structured evidence files."""

    @classmethod
    def _settle(
        cls,
        suite: dict[str, Any],
        wave_id: str,
        write_evidence: bool,
        passed: bool,
        receipt: Any,
        message: str,
        data: Any = None,
        failure_message: str | None = None,
    ) -> WaveRunResult:
        """Record `receipt` against the wave's declared evidence path and build its result.

        Every runner ends this way: offer the receipt, keep whatever the recorder actually
        returned, and report `data` (often a narrower slice of the receipt) to the caller.

        `message` is what the wave achieves *when its gate passes*, so a runner may state it
        in the past tense without checking. A failing gate never narrates that sentence as
        fact: the caller prints the message next to a `[FAIL]` tag, and "Proved the Writers
        Room handoff" on that line reads as a result no matter what the tag says. Demoting it
        to a stated intention happens here, once, instead of in each of the forty runners.

        A runner that can say something more precise about its own failure passes
        `failure_message` and is used verbatim -- A2 needs this to keep an unverifiable
        environment distinct from a product failure, which the generic demotion would flatten.
        """
        wave = next((w for w in suite.get("waves", []) if w.get("id") == wave_id), None) or {}
        if passed:
            settled_message = message
        elif failure_message is not None:
            settled_message = failure_message
        else:
            settled_message = f"gate did not pass; no claim is made (intended: {message})"
        recording = _record_evidence(wave, receipt, write_evidence, passed)
        if isinstance(recording, EvidenceCommitUnverified):
            evidence_path = None
            record_note = recording.note
            record_status = "committed_unverified"
        else:
            evidence_path = recording
            record_note = None
            record_status = "recorded" if recording is not None else "not_requested"

        return WaveRunResult(
            suite["id"],
            wave_id,
            passed,
            settled_message,
            evidence_path,
            data,
            record_note=record_note,
            record_status=record_status,
        )

    @classmethod
    def run_wave(cls, suite_id: str, wave_id: str, write_evidence: bool = False, full: bool = False) -> WaveRunResult:
        suite = get_suite(suite_id)
        if not suite:
            return WaveRunResult(suite_id, wave_id, False, f"Unknown suite: {suite_id}", execution_kind="error")
        return cls._run_loaded_wave(suite, wave_id, write_evidence=write_evidence, full=full)

    @classmethod
    def full_depth_command(cls, suite_id: str, wave_id: str) -> str | None:
        """The command that performs a deeper run of this wave, or None if none exists.

        `--full` is honoured only by runners that declare it; :meth:`_run_loaded_wave` drops
        the argument for every other runner. Printing the flag anyway turns the next-action
        surface into a dead end: the command runs, reproduces the same preview the retained
        receipt already holds, and discharges no part of the follow-up it was offered for.
        A follow-up with no executable runner is descriptive work, and the surfaces that
        present it have to say so rather than inventing a command.
        """
        runner_fn = getattr(cls, f"_run_{suite_id.replace('-', '_')}_{wave_id.lower()}", None)
        if runner_fn is None or "full" not in inspect.signature(runner_fn).parameters:
            return None
        return f"PYTHONPATH=src python3 -m portfolio_suites wave {suite_id} {wave_id} --full"

    @classmethod
    def _run_loaded_wave(
        cls,
        suite: dict[str, Any],
        wave_id: str,
        write_evidence: bool = False,
        full: bool = False,
    ) -> WaveRunResult:
        """Run one wave from an already-loaded suite manifest."""
        suite_id = suite.get("id", "unknown-suite")

        wave_spec = next((w for w in suite.get("waves", []) if w.get("id") == wave_id), None)
        if not wave_spec:
            return WaveRunResult(suite_id, wave_id, False, f"Wave {wave_id} not found in {suite_id}", execution_kind="error")

        method_name = f"_run_{suite_id.replace('-', '_')}_{wave_id.lower()}"
        runner_fn = getattr(cls, method_name, None)
        if not runner_fn:
            generic = cls._run_generic_wave(suite, wave_id, write_evidence)
            claim = wave_spec.get("recovery_claim", {}) or {}
            generic.claim_kind = claim.get("kind")
            generic.claim_level = claim.get("level")
            return generic

        exec_kind = classify_wave_spec(wave_spec, has_runner=True)

        # ponytail: only depth-aware runners declare `full`; the rest keep their 3-arg signature.
        depth_kwargs = {"full": full} if "full" in inspect.signature(runner_fn).parameters else {}
        raw_res = runner_fn(suite, wave_id, write_evidence, **depth_kwargs)

        if not raw_res.passed and raw_res.data and raw_res.data.get("environment_blocked"):
            exec_kind = "unverifiable_environment"

        # A probe that skipped required gates reports what it ran, not the manifest's historical
        # claim. The retained receipt still stands on its own; this run just cannot vouch for it.
        if exec_kind == "verified_runtime_recovery" and _skipped_stages(raw_res.data):
            exec_kind = "fast_probe"

        claim = wave_spec.get("recovery_claim", {}) or {}
        claim_level = claim.get("level")

        # Prototype-level analysis/checks pass prototype_passed
        is_prototype = claim_level in {"prototype", "specified"} or exec_kind == "prototype_check"
        prototype_passed = is_prototype and bool(raw_res.passed)
        gate_passed = bool(raw_res.passed)
        ineligibility_reason = evidence_ineligibility_reason(wave_spec)

        record_note: str | None = raw_res.record_note
        if record_note is None and write_evidence and raw_res.evidence_path is None:
            record_note = (
                "gate did not pass, so no receipt was offered"
                if not gate_passed
                else ineligibility_reason
                or "candidate receipt failed validation; prior receipt retained"
            )

        return WaveRunResult(
            suite_id=raw_res.suite_id,
            wave_id=raw_res.wave_id,
            passed=gate_passed,
            message=raw_res.message,
            execution_kind=exec_kind,
            prototype_passed=prototype_passed,
            claim_kind=claim.get("kind"),
            claim_level=claim_level,
            evidence_path=raw_res.evidence_path,
            data=raw_res.data,
            record_note=record_note,
            record_status=(
                "committed_unverified"
                if raw_res.record_status == "committed_unverified"
                else "not_requested"
                if not write_evidence
                else "read_only"
                if raw_res.record_note is not None and raw_res.evidence_path is not None
                else "recorded"
                if raw_res.evidence_path is not None and record_note is None
                else "gate_failed"
                if not gate_passed
                else "ineligible"
                if ineligibility_reason is not None
                else "candidate_rejected"
            ),
        )

    @classmethod
    def run_all(cls, write_evidence: bool = False, full: bool = False) -> list[WaveRunResult]:
        results = []
        suites = load_suites()
        for manifest in suites.values():
            for wave in manifest.get("waves", []):
                res = cls._run_loaded_wave(
                    manifest,
                    wave["id"],
                    write_evidence=write_evidence,
                    full=full,
                )
                results.append(res)
        return results

    # --- Specific Wave Implementations ---

    @classmethod
    def _run_accessibility_a1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        # A1 reads hand-authored prose rather than recording, but it still reads the path the
        # manifest declares, so the runner cannot drift from the registry.
        wave = next(w for w in suite.get("waves", []) if w.get("id") == wave_id)
        evidence_file = SUITES_ROOT / wave["evidence"]
        valid = False
        if evidence_file.is_file():
            try:
                content = evidence_file.read_text(encoding="utf-8")
                valid = len(content) > 100 and not evidence_errors(wave, evidence_file, suite["id"])
            except OSError:
                valid = False
        record_note = "A1 is a hand-authored analysis document and is read-only; recording is not supported" if write_evidence else None
        return WaveRunResult(
            suite["id"],
            wave_id,
            valid,
            "Parity matrix and fixture catalog verified." if valid else "Missing or invalid A1 parity evidence file.",
            evidence_path=str(evidence_file) if valid else None,
            record_note=record_note,
        )

    @classmethod
    def _run_accessibility_a2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool, full: bool = False) -> WaveRunResult:
        if write_evidence and not full:
            return WaveRunResult(
                suite["id"],
                wave_id,
                False,
                "A2 recording requires explicit full verification; re-run with --record --full.",
                data={"record_requires_full": True},
            )
        receipt = AccessibilitySourceAdapter.execute_wcag_331_migration_gate(full_suite=full)
        passed = receipt.get("all_stages_passed", False)
        findings = receipt.get("findings", [])
        full_stage = receipt.get("stages", {}).get("full_suite_and_typecheck_gate", {})
        focused_tests = receipt.get("stages", {}).get("focused_parity_gate", {}).get("passed_tests", 0)

        depth_note = (
            f"{focused_tests} focused tests (full suite skipped for fast check)"
            if full_stage.get("skipped")
            else f"{focused_tests} focused tests, {full_stage.get('total_tests_passed', 0)} full suite tests passed"
        )
        # A2 states its own failure text because only it can tell an unverifiable
        # environment apart from a product failure; `_settle` would flatten both.
        if receipt.get("environment_blocked"):
            failure_message = (
                "A2 donor/destination runtime gate is unverifiable in this environment; "
                "no product failure or recovery pass is claimed."
            )
        else:
            failure_message = (
                f"A2 gate did not pass ({depth_note}); generated {len(findings)} valid "
                "A11yFindings. No parity is claimed and the retained receipt is unchanged."
            )
        if full_stage.get("skipped"):
            message = (
                "FAST PROBE PASSED; HISTORICAL PARITY RECEIPT RETAINED. Executed WCAG Auditor donor "
                f"and Ally destination runtimes ({depth_note}); generated {len(findings)} valid "
                "A11yFindings. Re-run with --full for current runtime parity."
            )
        else:
            message = (
                "CURRENT RUNTIME PARITY VERIFIED. Executed authentic WCAG Auditor donor and Ally "
                f"destination runtimes ({depth_note}); generated {len(findings)} valid A11yFindings."
            )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            receipt,
            message,
            receipt,
            failure_message=failure_message,
        )

    @classmethod
    def _run_accessibility_a3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        reconciliation = AccessibilitySourceAdapter.execute_keyboard_overlay_reconciliation_gate()
        passed = reconciliation.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            reconciliation,
            "Compared 3 keyboard overlay implementations and retained the kb-overlay recommendation; "
            "no donor freeze or runtime consolidation was performed.",
            reconciliation,
        )

    @classmethod
    def _run_accessibility_a4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        receipt = AccessibilitySourceAdapter.execute_wcag_rule_candidates_gate()
        passed = receipt.get("all_stages_passed", False)
        # Counts come from the receipt this run produced, not from a literal. The old
        # message asserted "20 committed backlog cases (18 ...)" even on a run that
        # classified nothing.
        catalog = receipt.get("catalog_evaluation") or {}
        counts = (
            f"{catalog.get('total_candidates_evaluated', 0)} committed backlog cases "
            f"({catalog.get('port_review_count', 0)} port-review, "
            f"{catalog.get('port_narrow_count', 0)} port-narrow, "
            f"{catalog.get('port_options_count', 0)} port-options)"
        )
        message = f"Classified {counts} and ran one suite-local compliant-markup smoke probe."
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            receipt,
            message,
            receipt.get("catalog_evaluation"),
        )

    @classmethod
    def _run_accessibility_a5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        kitchen_view = AccessibilitySourceAdapter.execute_a11y_kitchen_roundtrip_gate()
        passed = kitchen_view.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            kitchen_view,
            "Projected A11yFinding through the suite-local teaching view with zero field loss; "
            "the A11y Kitchen runtime was not invoked.",
            kitchen_view,
        )

    @classmethod
    def _run_accessibility_a6(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        consolidation = AccessibilitySourceAdapter.execute_keyboard_overlay_consolidation_gate()
        passed = consolidation.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            consolidation,
            "Measured the full overlay permission surface; scope narrowing and donor freeze remain outstanding.",
            consolidation,
        )

    @classmethod
    def _run_operator_os_o1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = OperatorOSSourceAdapter.execute_o1_source_record_observer_gate()
        passed = (
            result.get("mutation_protection_passed") is True
            and result.get("cas_verified") is True
            and result.get("all_stages_passed") is True
            and result.get("status") == "cas_projection_verified"
            and result.get("source_record", {}).get("schema_version") == "1.0.0"
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            "Acquired live dotfiles into authentic PKos CAS, normalized into SQLite, and generated fenced Observer projection.",
            result.get("source_record"),
        )

    @classmethod
    def _run_operator_os_o2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = OperatorOSSourceAdapter.execute_o2_ryos_inventory()
        passed = (
            result.get("status") == "verified"
            and result.get("inventory_catalog_count", 0) >= 5
            and result.get("ryos_core_files_count", 0) >= 3
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            f"Inventoried {result.get('ryos_core_files_count', 0)} Ryos core files and {result.get('master_plan_files_count', 0)} master-plan specs against dotfiles/Observer.",
            {"inventory_catalog_count": result.get("inventory_catalog_count")},
        )

    @classmethod
    def _run_operator_os_o3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        receipt = OperatorOSSourceAdapter.execute_o3_jarvis_action_preview()
        passed = (
            receipt.get("status") == "preview_verified"
            and receipt.get("requires_human_approval") is True
            and receipt.get("dry_run_only") is True
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            receipt,
            "Verified JARVIS action preview receipt with human approval boundary and zero duplicate state.",
            receipt,
        )

    @classmethod
    def _run_operator_os_o4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = OperatorOSSourceAdapter.execute_o4_pkos_stream_intake()
        passed = (
            result.get("status") == "stream_intake_verified"
            and result.get("all_fenced_from_reingestion") is True
            and result.get("all_sources_cited") is True
            and result.get("batch_size", 0) >= 3
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            f"Widened PKOS intake stream across {result.get('batch_size', 0)} donor README sources with verified Observer projection fences.",
            {"batch_size": result.get("batch_size")},
        )

    @classmethod
    def _run_operator_os_o5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = OperatorOSSourceAdapter.execute_o5_ryos_disposition_reconciliation()
        passed = (
            result.get("status") == "disposition_proposal_recorded"
            and result.get("all_stages_passed") is True
            and result.get("duplicate_decisions_closed") is False
            and result.get("duplicate_decision_disposition") == "close_on_verification"
            and result.get("port_candidates_count", 0) >= 2
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            "Recorded a Ryos and master-plan disposition proposal from the live O2 inventory. "
            "No code was ported and no duplicate decision was closed -- closure remains "
            "proposed on verification.",
            {"port_candidates_count": result.get("port_candidates_count")},
        )

    @classmethod
    def _run_operator_os_o6(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = OperatorOSSourceAdapter.execute_o6_jarvis_checkpoint_lifecycle()
        passed = (
            result.get("status") == "checkpoint_lifecycle_verified"
            and result.get("multi_action_lifecycle_passed") is True
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            "Verified multi-action JARVIS checkpoint lifecycle with strict fail-closed boundary on unapproved execution.",
            {"lifecycle_passed": passed},
        )

    @classmethod
    def _run_brand_publishing_b1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = BrandPublishingSourceAdapter.execute_b1_brand_package_export()
        receipt = result.get("publishing_receipt", {})
        pkg = result.get("brand_package", {})
        passed = (
            result.get("all_stages_passed") is True
            and result.get("mutation_protection_passed") is True
            and receipt.get("dry_run_only") is True
            and receipt.get("matched_approved_claims_count", 0) >= 1
            and receipt.get("live_published") is False
            and pkg.get("schema_version") == "1.0.0"
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            "Built and validated a suite-local BrandPackage projection from inspected donor sources; "
            "the publishing boundary remained dry-run only.",
            result.get("publishing_receipt"),
        )

    @classmethod
    def _run_brand_publishing_b2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = BrandPublishingSourceAdapter.execute_b2_phase_mapping()
        passed = result.get("all_stages_passed") is True and result.get("total_phases_mapped") == 9
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            "Mapped all 9 Brand Workshop low-typing intake phases (00-spark to 08-living-brand) onto Brand Maker workspace gates.",
            {"phases_count": result.get("total_phases_mapped")},
        )

    @classmethod
    def _run_brand_publishing_b3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        b1_result = BrandPublishingSourceAdapter.execute_b1_brand_package_export()
        pkg = b1_result["brand_package"]
        src = b1_result["source_record"]
        receipt = BrandPublishingEngine.dry_run_publish(
            pkg, src, "Zero-dependency local-first portfolio control plane verified through Cyborg VCC review.", channel="cyborg-vcc"
        )
        passed = (
            b1_result.get("all_stages_passed") is True
            and receipt.get("status") == "dry_run_verified"
            and receipt.get("brand_package_id") == "pkg-cyborg-brand-v1"
            and receipt.get("source_id") == "src-manifesto-draft-001"
            and receipt.get("matched_approved_claims_count", 0) >= 1
            and receipt.get("dry_run_only") is True
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            receipt,
            "Exercised the suite-local SourceRecord -> BrandPackage -> VCC review projection and "
            "produced a dry-run publishing receipt.",
            receipt,
        )

    @classmethod
    def _run_brand_publishing_b4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        b1_result = BrandPublishingSourceAdapter.execute_b1_brand_package_export()
        pkg = b1_result["brand_package"]
        package_sha256 = canonical_digest(pkg)
        v1 = BrandPublishingEngine.verify_package_consumer(
            pkg, "site-fixture-consumer", "1.0.0", expected_package_sha256=package_sha256
        )
        v2 = BrandPublishingEngine.verify_package_consumer(
            pkg, "portfolio-validator-consumer", "1.0.0", expected_package_sha256=package_sha256
        )
        passed = (
            b1_result.get("all_stages_passed") is True
            and v1.get("status") == "verified"
            and v2.get("status") == "verified"
            and v1.get("package_id") == "pkg-cyborg-brand-v1"
            and v2.get("package_id") == "pkg-cyborg-brand-v1"
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            {"consumer_1": v1, "consumer_2": v2, "status": "verified"},
            "Exercised two suite-local BrandPackage consumer projections and verified version-pinning "
            "and mutation-protection boundaries.",
            {"consumers_verified": 2},
        )

    @classmethod
    def _run_brand_publishing_b5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res_complete = BrandPublishingSourceAdapter.execute_b5_brand_maker_intake()
        passed = (
            res_complete.get("all_stages_passed") is True
            and res_complete.get("brand_workshop_read") is True
            and res_complete.get("phases_completed") == 9
            and res_complete.get("resulting_package", {}).get("schema_version") == "1.0.0"
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res_complete,
            "Drove 9 intake phases aligned to live Brand Workshop phase ids through the "
            "suite-local Brand Maker state machine.",
            res_complete,
        )

    @classmethod
    def _run_brand_publishing_b6(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        b1_result = BrandPublishingSourceAdapter.execute_b1_brand_package_export()
        pkg = b1_result["brand_package"]
        src = b1_result["source_record"]

        approved_receipt = BrandPublishingEngine.simulate_vcc_human_approval(
            pkg, src, "Zero-dependency local-first portfolio control plane verified.", human_decision="approved"
        )
        rejected_receipt = BrandPublishingEngine.simulate_vcc_human_approval(
            pkg, src, "Zero-dependency draft.", human_decision="rejected"
        )
        unmatched_receipt = BrandPublishingEngine.simulate_vcc_human_approval(
            pkg, src, "Draft with zero matching approved claims.", human_decision="approved"
        )

        sim_gate = approved_receipt.get("simulated_gate", {})
        passed = (
            b1_result.get("all_stages_passed") is True
            and approved_receipt.get("status") == "simulated_review_passed"
            and rejected_receipt.get("status") == "simulated_blocked_rejected"
            and unmatched_receipt.get("status") == "simulated_blocked_unmatched_claims"
            and sim_gate.get("boundary_check") == "stopped_before_live_publish"
            and sim_gate.get("decision_source") == "simulated_fixture"
            and sim_gate.get("human_confirmation_claimed") is False
            and approved_receipt.get("brand_package_id") == "pkg-cyborg-brand-v1"
            and approved_receipt.get("source_id") == "src-manifesto-draft-001"
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            {
                "approved_review": approved_receipt,
                "rejected_probe_status": rejected_receipt.get("status"),
                "unmatched_probe_status": unmatched_receipt.get("status"),
            },
            "Simulated VCC editorial review with human approval gate; verified rejection and claim validation branching.",
            approved_receipt,
        )

    @classmethod
    def _run_production_house_p1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ProductionHouseSourceAdapter.execute_p1_groundwire_fingerprint()
        passed = res.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res,
            "Parsed a real Groundwire episode script into ProductionJob; outputs remain modeled and "
            "no audio runtime was invoked.",
            res.get("job"),
        )

    @classmethod
    def _run_production_house_p2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ProductionHouseSourceAdapter.execute_p2_formatter_job()
        passed = res.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res,
            "Hashed a real formatter play into ProductionJob; the formatter was not invoked.",
            res.get("job"),
        )

    @classmethod
    def _run_production_house_p3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ProductionHouseSourceAdapter.execute_p3_writers_room_handoff()
        passed = res.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res,
            "Hashed a real Writers Room final into ProductionJob; Writers Room and human "
            "signoff were not invoked.",
            res.get("job"),
        )

    @classmethod
    def _run_production_house_p4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ProductionHouseSourceAdapter.execute_p4_documentary_pipeline()
        passed = res.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res,
            "Projected a real Groundwire episode and production-house domain template through "
            "ProductionJob; no media runtime was invoked.",
            res.get("job"),
        )

    @classmethod
    def _run_production_house_p5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ProductionHouseSourceAdapter.execute_p5_writers_room_event_stream()
        passed = res.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res,
            "Mapped real Writers Room pipeline status files into ProductionJob events; signoff "
            "and runtime consolidation were not performed.",
            res.get("mapping"),
        )

    @classmethod
    def _run_model_behavior_lab_m1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ModelBehaviorSourceAdapter.execute_m1_ethics_experiment_run()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Normalized a recorded ai-ethics-comparator result into ExperimentRun with field parity.",
            res.get("field_parity"),
        )

    @classmethod
    def _run_model_behavior_lab_m2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ModelBehaviorSourceAdapter.execute_m2_comparator_kernel_matrix()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Measured the donor subsystem duplication a shared kernel would replace; extraction not performed.",
            res.get("extraction_matrix"),
        )

    @classmethod
    def _run_model_behavior_lab_m3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ModelBehaviorSourceAdapter.execute_m3_chess_adapter_fixture()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Built the legal-move chess adapter fixture from a recorded ai-chess match.",
            res.get("match_fixture"),
        )

    @classmethod
    def _run_model_behavior_lab_m4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ModelBehaviorSourceAdapter.execute_m4_chess_benchmark_run()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Scored recorded chess openings through the kernel that scores the ethics pack.",
            res.get("canonical_run"),
        )

    @classmethod
    def _run_model_behavior_lab_m5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = ModelBehaviorSourceAdapter.execute_m5_benchmark_corpus_manifest()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Pinned every donor benchmark corpus by content hash for reproducible re-runs.",
            res.get("corpus_manifest"),
        )

    @classmethod
    def _run_discovery_decision_d1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = DiscoveryDecisionSourceAdapter.execute_d1_sif_forge_stage_matrix()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Mapped real SIF phase nodes to Forge stages with the donors' own budgets and artifacts.",
            res.get("matrix"),
        )

    @classmethod
    def _run_discovery_decision_d2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = DiscoveryDecisionSourceAdapter.execute_d2_forge_redteam_record()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Projected the recorded SIF red-team phase into a suite-local, budgeted Forge "
            "InvestigationRecord; the donor runtimes were not invoked.",
            res.get("investigation"),
        )

    @classmethod
    def _run_discovery_decision_d3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = DiscoveryDecisionSourceAdapter.execute_d3_insight_excavator_discovery()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Cited two real Excavator documents by content with re-verifiable byte anchors.",
            res.get("discovery"),
        )

    @classmethod
    def _run_discovery_decision_d4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = DiscoveryDecisionSourceAdapter.execute_d4_sif_analogy_forge_record()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Projected the recorded SIF analogy phase through the same bounded suite-local Forge "
            "path; the donor runtimes were not invoked.",
            res.get("investigation"),
        )

    @classmethod
    def _run_discovery_decision_d5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = DiscoveryDecisionSourceAdapter.execute_d5_insight_excavator_citation()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Projected an Excavator citation into a recorded Forge investigation; retirement not performed.",
            res.get("retirement"),
        )

    @classmethod
    def _run_agent_reliability_r1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = AgentReliabilitySourceAdapter.execute_r1_adversarial_harness_scorecard()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Derived adversarial fixtures from the looping-box action policy and probed confinement.",
            res.get("canonical_run"),
        )

    @classmethod
    def _run_agent_reliability_r2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = AgentReliabilitySourceAdapter.execute_r2_cross_harness_eval()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Measured reliability-gate coverage across Looping Box, SSSF, and Agentic Harness sources.",
            res.get("gates_covered"),
        )

    @classmethod
    def _run_agent_reliability_r3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = AgentReliabilitySourceAdapter.execute_r3_promoted_components()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Counted the real sibling-repo consumers of every promoted shared component.",
            res.get("promoted_components"),
        )

    @classmethod
    def _run_agent_reliability_r4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = AgentReliabilitySourceAdapter.execute_r4_promoted_components_audit()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Applied the two-consumer craft rule to the measured component inventory.",
            res.get("audit"),
        )

    @classmethod
    def _run_agent_reliability_r5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = AgentReliabilitySourceAdapter.execute_r5_curriculum_fixtures()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Mined real AI Staff and harness eval cases into deterministic curriculum fixtures.",
            res.get("curriculum_fixtures"),
        )

    # --- Game Design & Simulation Suite Runners ---

    @classmethod
    def _run_game_design_g1(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = GameDesignSourceAdapter.execute_g1_tucked_in_terrors_fingerprint()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res.get("document", {}),
            "Fingerprinted the donor's real rules data and 1000 recorded runs into a parity fixture.",
            res.get("outcome_distribution"),
        )

    @classmethod
    def _run_game_design_g2(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = GameDesignSourceAdapter.execute_g2_storyweaver_pack_parity()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Projected the donor game into the Storyweaver pack vocabulary; no parity measured.",
            res.get("shape_projection"),
        )

    @classmethod
    def _run_game_design_g3(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = GameDesignSourceAdapter.execute_g3_authored_game_boundary()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Inventoried the authored Oregon D&D corpus and measured zero engine coupling.",
            res.get("engine_coupling"),
        )

    @classmethod
    def _run_game_design_g4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = GameDesignSourceAdapter.execute_g4_storyweaver_adventure_pack()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Checked a second game class against the pack vocabulary Storyweaver really writes.",
            res.get("schema_check"),
        )

    @classmethod
    def _run_game_design_g5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        res = GameDesignSourceAdapter.execute_g5_march_madness_boundary()
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            res.get("all_stages_passed", False),
            res,
            "Audited March Madness for mandatory engine coupling before any port is scheduled.",
            res.get("engine_coupling"),
        )

    @classmethod
    def _run_generic_wave(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        matching_wave = next((w for w in suite.get("waves", []) if w.get("id") == wave_id), None)
        if not matching_wave:
            return WaveRunResult(suite["id"], wave_id, False, f"Wave {wave_id} not found in {suite['id']}")

        return WaveRunResult(
            suite["id"],
            wave_id,
            False,
            f"Wave {wave_id} has no dedicated runner or source adapter implemented (fails closed). Objective: {matching_wave.get('objective')}",
            execution_kind="unintegrated_specification",
        )
