"""Automated wave gate execution and evidence generation across all eight suites."""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.accessibility import AccessibilitySourceAdapter
from .adapters.agent_reliability import AgentReliabilitySourceAdapter
from .adapters.brand_publishing import BrandPublishingSourceAdapter
from .adapters.discovery_decision import DiscoveryDecisionSourceAdapter
from .adapters.game_design import GameDesignSourceAdapter
from .adapters.model_behavior import ModelBehaviorSourceAdapter
from .adapters.operator_os import OperatorOSSourceAdapter
from .adapters.production_house import ProductionHouseSourceAdapter
from .contracts import generate_sample
from .engines.agent_reliability import AgentReliabilityEngine
from .engines.brand_publishing import BrandPublishingEngine
from .engines.discovery_decision import DiscoveryDecisionEngine
from .engines.game_design import GameDesignEngine
from .engines.model_behavior import ModelBehaviorEngine
from .registry import (
    SUITES_ROOT,
    evidence_errors,
    evidence_ineligibility_reason,
    get_suite,
    load_suites,
)


@dataclass
class WaveRunResult:
    suite_id: str
    wave_id: str
    passed: bool  # True ONLY for authentic verified migration acceptance
    message: str
    evidence_path: str | None = None
    data: dict[str, Any] | None = None
    execution_kind: str = "unintegrated_specification"
    prototype_passed: bool = False
    # Why nothing was written when --record was asked for. None when not asked, or when the
    # write succeeded. "Not written" has several distinct causes and they must not be conflated.
    record_note: str | None = None



_RECORD_LOCKS: dict[Path, threading.Lock] = {}
_RECORD_LOCKS_GUARD = threading.Lock()


def _wave_for_evidence(rel_path: str) -> dict[str, Any] | None:
    """Return the one wave declaring an evidence path; fail closed on zero or duplicates."""
    matches: list[dict[str, Any]] = []
    for manifest in load_suites().values():
        for wave in manifest.get("waves", []):
            if wave.get("evidence") == rel_path:
                matches.append(wave)
    return matches[0] if len(matches) == 1 else None


def _record_lock(evidence_file: Path) -> threading.Lock:
    """Serialize writers for one retained receipt while allowing unrelated waves to record."""
    with _RECORD_LOCKS_GUARD:
        return _RECORD_LOCKS.setdefault(evidence_file, threading.Lock())


def _skipped_stages(data: Any) -> list[str]:
    """Names of receipt stages that were not executed on this run."""
    stages = data.get("stages", {}) if isinstance(data, dict) else {}
    return sorted(name for name, stage in stages.items() if isinstance(stage, dict) and stage.get("skipped"))


def _record_evidence(wave: dict[str, Any], data: Any, write_evidence: bool, passed: bool) -> str | None:
    """Record evidence ONLY when requested, the gate passed, AND the candidate validates.

    The receipt path comes from the wave manifest's own `evidence` field, so a runner cannot
    write to a path the registry does not already know about.

    Writes a temp sibling, runs `evidence_errors` against it, and only then atomically
    replaces the retained receipt. A rejected candidate leaves the prior receipt
    byte-for-byte unchanged and returns None.

    This is stricter than `suites validate`, which only inspects completed waves: a wave
    with no declared recovery claim is refused outright, because there would be no contract
    to check the bytes against. Callers wanting to report *why* nothing was written should
    consult `evidence_ineligibility_reason` rather than inferring it from the None.
    """
    if not (write_evidence and passed):
        return None

    rel_path = wave.get("evidence")
    if not rel_path or "/evidence/" not in rel_path:
        return None
    try:
        # Exactly one wave may own a receipt path, and it must be this one.
        owner = _wave_for_evidence(rel_path)
    except (OSError, ValueError, KeyError):
        return None
    if owner is None or owner.get("id") != wave.get("id"):
        return None

    suite_dir, _, filename = rel_path.partition("/evidence/")
    if "/" in filename or not filename:
        return None
    evidence_dir = SUITES_ROOT / suite_dir / "evidence"
    evidence_file = evidence_dir / filename
    try:
        payload = data if isinstance(data, str) else json.dumps(data, indent=2)
    except (TypeError, ValueError):
        return None

    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        with _record_lock(evidence_file):
            candidate: Path | None = None
            try:
                # A unique same-directory candidate prevents threaded writers from sharing bytes.
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=evidence_dir,
                    prefix=f".{evidence_file.stem}.",
                    suffix=evidence_file.suffix,
                    delete=False,
                ) as handle:
                    handle.write(payload)
                    candidate = Path(handle.name)
                if evidence_errors(wave, candidate):
                    return None
                os.replace(candidate, evidence_file)
                candidate = None
            finally:
                if candidate is not None:
                    candidate.unlink(missing_ok=True)
    except OSError:
        return None
    return str(evidence_file)


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
    ) -> WaveRunResult:
        """Record `receipt` against the wave's declared evidence path and build its result.

        Every runner ends this way: offer the receipt, keep whatever the recorder actually
        returned, and report `data` (often a narrower slice of the receipt) to the caller.
        """
        wave = next((w for w in suite.get("waves", []) if w.get("id") == wave_id), None) or {}
        return WaveRunResult(
            suite["id"],
            wave_id,
            passed,
            message,
            _record_evidence(wave, receipt, write_evidence, passed),
            data,
        )

    @classmethod
    def run_wave(cls, suite_id: str, wave_id: str, write_evidence: bool = False, full: bool = False) -> WaveRunResult:
        suite = get_suite(suite_id)
        if not suite:
            return WaveRunResult(suite_id, wave_id, False, f"Unknown suite: {suite_id}", execution_kind="error")
        return cls._run_loaded_wave(suite, wave_id, write_evidence=write_evidence, full=full)

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
            return cls._run_generic_wave(suite, wave_id, write_evidence)

        manifest_status = wave_spec.get("status", "specified")
        claim_kind = wave_spec.get("recovery_claim", {}).get("kind")
        if manifest_status == "complete" and claim_kind == "runtime":
            exec_kind = "verified_runtime_recovery"
        elif manifest_status == "complete":
            exec_kind = "verified_analysis"
        else:
            exec_kind = "prototype_check"

        # ponytail: only depth-aware runners declare `full`; the rest keep their 3-arg signature.
        depth_kwargs = {"full": full} if "full" in inspect.signature(runner_fn).parameters else {}
        raw_res = runner_fn(suite, wave_id, write_evidence, **depth_kwargs)

        if not raw_res.passed and raw_res.data and raw_res.data.get("environment_blocked"):
            exec_kind = "unverifiable_environment"

        # A probe that skipped required gates reports what it ran, not the manifest's historical
        # claim. The retained receipt still stands on its own; this run just cannot vouch for it.
        if exec_kind == "verified_runtime_recovery" and _skipped_stages(raw_res.data):
            exec_kind = "fast_probe"

        # A completed analysis and a recovered runtime are distinct verified claims.
        is_migration_verified = exec_kind in {"verified_analysis", "verified_runtime_recovery"} and raw_res.passed
        prototype_passed = exec_kind == "prototype_check" and raw_res.passed
        gate_passed = raw_res.passed or prototype_passed

        record_note: str | None = None
        if write_evidence and raw_res.evidence_path is None:
            record_note = (
                evidence_ineligibility_reason(wave_spec)
                or ("gate did not pass, so no receipt was offered" if not gate_passed
                    else "candidate receipt failed validation; prior receipt retained")
            )

        return WaveRunResult(
            suite_id=raw_res.suite_id,
            wave_id=raw_res.wave_id,
            passed=is_migration_verified or (exec_kind == "fast_probe" and raw_res.passed),
            message=raw_res.message,
            execution_kind=exec_kind,
            prototype_passed=prototype_passed,
            evidence_path=raw_res.evidence_path,
            data=raw_res.data,
            record_note=record_note,
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
                valid = len(content) > 100 and not evidence_errors(wave, evidence_file)
            except OSError:
                valid = False
        return WaveRunResult(
            suite["id"],
            wave_id,
            valid,
            "Parity matrix and fixture catalog verified." if valid else "Missing or invalid A1 parity evidence file.",
            str(evidence_file) if valid else None,
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
        if receipt.get("environment_blocked"):
            message = (
                "A2 donor/destination runtime gate is unverifiable in this environment; "
                "no product failure or recovery pass is claimed."
            )
        elif full_stage.get("skipped"):
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
            "Reconciled 3 keyboard overlay implementations into canonical kb-overlay anchor.",
            reconciliation,
        )

    @classmethod
    def _run_accessibility_a4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        receipt = AccessibilitySourceAdapter.execute_wcag_rule_candidates_gate()
        passed = receipt.get("all_stages_passed", False)
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            receipt,
            "Classified 20 committed backlog cases (18 port-review, 1 port-narrow, 1 port-options) and ran one suite-local compliant-markup smoke probe.",
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
            "Round-tripped A11yFinding contract through A11y Kitchen interactive teaching surface with zero evidence loss.",
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
            and result.get("status") == "verified"
            and result.get("source_record", {}).get("schema_version") == "1.0.0"
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result.get("observer_projection_preview", ""),
            "Captured content-addressed SourceRecord and projected fenced Observer note with mutation protection.",
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
            f"Widened PKOS intake stream across {result.get('batch_size', 0)} sources with verified Observer projection fences.",
            {"batch_size": result.get("batch_size")},
        )

    @classmethod
    def _run_operator_os_o5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        result = OperatorOSSourceAdapter.execute_o5_ryos_disposition_reconciliation()
        passed = (
            result.get("status") == "disposition_reconciled"
            and result.get("duplicate_decisions_closed") is True
            and result.get("port_candidates_count", 0) >= 2
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            result,
            "Reconciled Ryos and master-plan inventory: port targets assigned to dotfiles and PKos anchors confirmed.",
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
            "Exported and validated canonical BrandPackage with dry-run mutation protection and zero live publishing side-effects.",
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
            "Proved SourceRecord -> BrandPackage -> VCC review -> dry-run publishing receipt.",
            receipt,
        )

    @classmethod
    def _run_brand_publishing_b4(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        b1_result = BrandPublishingSourceAdapter.execute_b1_brand_package_export()
        pkg = b1_result["brand_package"]
        v1 = BrandPublishingEngine.verify_package_consumer(pkg, "site-fixture-consumer", "1.0.0")
        v2 = BrandPublishingEngine.verify_package_consumer(pkg, "portfolio-validator-consumer", "1.0.0")
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
            "Wired second BrandPackage consumer; verified version-pinning and mutation-protection boundary.",
            {"consumers_verified": 2},
        )

    @classmethod
    def _run_brand_publishing_b5(cls, suite: dict[str, Any], wave_id: str, write_evidence: bool) -> WaveRunResult:
        complete_phase_inputs = {
            1: {"one_liner": "Local-first portfolio suite", "enemy": "Fragile unversioned schemas", "brand_name": "Cyborg Suites"},
            2: {"primary_operator": "Ryan Johnson", "pain_points": ["drift", "cognitive load"], "target_audience": "Technical Operators"},
            3: {"tone_adjectives": ["clear", "grounded", "concise"], "taboo_words": ["vague", "magic", "untested"]},
            4: {"palette_hex": ["#111827", "#3b82f6"], "typeface_pair": "Inter / JetBrains Mono", "tagline": "Instituted Brand Package"},
            5: {"verifiable_claims": ["Zero-dependency local control", "Deterministic test gates"]},
            6: {"logo_paths": ["assets/logo.svg"], "icon_set": "lucide"},
            7: {"do_list": ["Pin versions"], "dont_list": ["Silent mutations"], "usage_rules": ["Never modify without explicit version bump"]},
            8: {"formats": ["markdown", "json"], "cadence": "on_demand"},
            9: {"approver_signoff": "Ryan Johnson"},
        }
        res_complete = BrandPublishingEngine.execute_brand_maker_intake("cyborg-brand", complete_phase_inputs)
        res_empty = BrandPublishingEngine.execute_brand_maker_intake("cyborg-brand", {})

        passed = (
            res_complete.get("phases_completed") == 9
            and res_complete.get("resulting_package", {}).get("schema_version") == "1.0.0"
            and res_empty.get("phases_completed") == 0
            and res_empty.get("resulting_package") is None
        )
        return cls._settle(
            suite,
            wave_id,
            write_evidence,
            passed,
            res_complete,
            "Implemented 9 Brand Workshop phases into Brand Maker intake state; validated input completeness.",
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

        passed = (
            b1_result.get("all_stages_passed") is True
            and approved_receipt.get("status") == "ready_for_operator_release"
            and rejected_receipt.get("status") == "blocked_rejected"
            and unmatched_receipt.get("status") == "blocked_unmatched_claims"
            and approved_receipt.get("human_gate", {}).get("boundary_check") == "stopped_before_live_publish"
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
            "Fingerprinted Groundwire episode workflow and QC outputs into ProductionJob.",
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
            "Executed episode slice via formatter adapter with resumable ProductionJob state.",
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
            "Proved Writers Room story-state handoff via validated ProductionJob lifecycle.",
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
            "Executed structural episode variant (investigative documentary) through unchanged ProductionJob engine.",
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
            "Mapped Writers Room story revisions into ProductionJob events; unified runtime state.",
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
            "Ported the recorded SIF red-team phase into a budgeted Forge InvestigationRecord.",
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
            "Ported the recorded SIF analogy phase through the same bounded Forge path.",
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
            res["document"],
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
