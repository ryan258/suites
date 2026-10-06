"""Resolve the portfolio-wide release/completion ledger.

The roadmap (docs/ROADMAP.md: Item 1) requires a release ledger that maps every suite
criterion, wave follow-up, unique capability, runtime, owner, contract, evidence artifact,
adoption record, recovery score, and final disposition, so that "ready for v1" is a
machine-checkable claim that cannot be derived from wave counts.

This module deliberately *subsumes and references* the recovery program rather than
copying it. ``portfolio/recovery-program.json`` remains authoritative for obligation-level
truth (execution order, target evidence, runtime environment, owner gates, receipt
contracts). The release ledger is one more overlay on top of suite manifests -- same rule as
the recovery program (see recovery_program.py module docstring) -- but broader in scope and
purely aggregate.

Two axes are kept explicitly separate everywhere: the release **lifecycle** (alpha, beta,
release-candidate, supported, deprecated, retired) and the **recovery depth** (specified ...
converged). Support-promise phases (beta, release-candidate, supported) require an explicit
owner and at least ``source_executed`` recovery depth; "supported" never implies "recovered",
and no lifecycle phase may be manufactured from milestone counts.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import stat
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

from .approvals import (
    APPROVAL_SCHEMA,
    ApprovalError,
    canonical_digest,
    verify_consumed_operator_approval,
)
from .paths import ConfinementError, SUITES_ROOT, open_confined_directory
from .receipts import SHA256_HEX
from .recovery_policy import RECOVERY_PROMOTION_LEVELS, RECOVERY_TIERS
from .recovery_program import RecoveryProgramError, resolve_recovery_obligations


RELEASE_LEDGER_PATH = SUITES_ROOT / "portfolio" / "release-ledger.json"
RELEASE_LEDGER_ID = "portfolio-release-completion-v1"
RELEASE_LEDGER_SCHEMA_VERSION = "1.0.0"

EXPECTED_POLICY = {
    "release_phases": [
        "alpha",
        "beta",
        "release-candidate",
        "supported",
        "deprecated",
        "retired",
    ],
    "closure_outcomes": [
        "implemented",
        "already_covered",
        "independently_retained",
        "rejected",
        "deferred_with_trigger",
    ],
    "minimum_authentic_uses_for_adoption": 3,
    "silent_deletion": "forbidden",
    "blanket_deferral": "forbidden",
    "resolved_without_evidence_or_owner": "forbidden",
    # Runtime and adoption work through beta. Candidate verification, authorized
    # distribution, and stabilization remain separate roadmap exit gates.
    "phases_covered": ["0", "1", "2", "3", "4", "5"],
}

# Phases that assert a support promise and therefore require a defensible recovery depth.
# "supported" with no execution evidence is an impossible promotion and is refused.
SUPPORT_PROMISE_PHASES = frozenset({"supported", "beta", "release-candidate"})
# Lowest recovery depth a support-promise phase may honestly claim.
MIN_SUPPORT_PROMISE_LEVEL = "source_executed"
# Blocker phases this partial ledger truthfully covers (roadmap defines 0-8).
PHASES_COVERED = frozenset(EXPECTED_POLICY["phases_covered"])
UNMODELED_EXIT_PHASES = tuple(str(i) for i in range(9) if str(i) not in PHASES_COVERED)

# The score targets come from the adopted tier rubric, not authored freely in the ledger.
EXPECTED_SCORE_TARGETS = {tier: float(cfg["target_score"]) for tier, cfg in RECOVERY_TIERS.items()}

# Governed suite retirement receipt contract.
SUITE_RETIREMENT_RECEIPT_CONTRACT = "portfolio-suite-retirement-v1"

# Governed global-closure receipt contract for evidence artifacts closing global gates.
GLOBAL_CLOSURE_RECEIPT_CONTRACT = "portfolio-global-closure-v1"

# Governed roadmap phase expected for each mandatory global blocker gate.
GLOBAL_BLOCKER_EXPECTED_PHASES: dict[str, str] = {
    "phase0.release-ledger": "0",
    "phase1.contract-state-freeze": "1",
    "phase1.stable-surface": "1",
}

# Exact, exhaustive surfaces and paths required for each global blocker closure.
GLOBAL_BLOCKER_SPECS: dict[str, dict[str, frozenset[str]]] = {
    "phase0.release-ledger": {
        "release_ledger": frozenset({"portfolio/release-ledger.json"}),
        "recovery_program": frozenset({"portfolio/recovery-program.json"}),
        "recovery_standard": frozenset({"portfolio/recovery-standard.json"}),
        "enforcement": frozenset({"src/portfolio_suites/release_state.py", "src/portfolio_suites/registry.py"}),
    },
    "phase1.contract-state-freeze": {
        "contracts_schemas": frozenset({
            "contracts/a11y-finding.schema.json",
            "contracts/brand-package.schema.json",
            "contracts/experiment-run.schema.json",
            "contracts/investigation-record.schema.json",
            "contracts/production-job.schema.json",
            "contracts/source-record.schema.json",
        }),
        "persistent_state_formats": frozenset({
            "portfolio/execution-trace-contract.json",
            "src/portfolio_suites/approvals.py",
            "src/portfolio_suites/catalog.py",
            "src/portfolio_suites/operator_state.py",
            "src/portfolio_suites/recovery_program.py",
            "src/portfolio_suites/receipts.py",
            "src/portfolio_suites/contracts.py",
            "src/portfolio_suites/ai.py",
            "docs/PLATFORM-OPERATIONS.md",
        }),
    },
    "phase1.stable-surface": {
        "stable_cli_api_surfaces": frozenset({
            "src/portfolio_suites/cli.py",
            "src/portfolio_suites/registry.py",
            "src/portfolio_suites/server.py",
            "src/portfolio_suites/catalog.py",
            "src/portfolio_suites/operator_state.py",
            "src/portfolio_suites/candidate.py",
            "src/portfolio_suites/diagnostics.py",
            "src/portfolio_suites/web/catalog.js",
        }),
    },
}


def compute_canonical_ledger_bytes(content_bytes: bytes) -> bytes:
    """Compute non-self-referential canonical JSON bytes for portfolio/release-ledger.json.

    All blocker closure records are deeply cleared to None, allowing persisted ledger
    closures to be serialized and reloaded without invalidating the frozen baseline digest.
    Any alteration to policies, score targets, suites, criteria, obligations, or blocker
    definitions changes this canonical output and invalidates the Phase 0 freeze.
    """
    try:
        doc = json.loads(content_bytes.decode("utf-8"))
    except Exception:
        return content_bytes
    if isinstance(doc, dict):
        import copy
        doc = copy.deepcopy(doc)
        for b in doc.get("global_blockers", []):
            if isinstance(b, dict) and "closure" in b:
                b["closure"] = None
        for b in doc.get("release_blockers", []):
            if isinstance(b, dict) and "closure" in b:
                b["closure"] = None
        return json.dumps(doc, sort_keys=True, indent=2).encode("utf-8")
    return content_bytes


def canonical_suites_file_digest(path_text: str, content_bytes: bytes) -> str:
    """Compute content digest, applying canonicalization for self-referential ledger bytes."""
    if path_text == "portfolio/release-ledger.json":
        return hashlib.sha256(compute_canonical_ledger_bytes(content_bytes)).hexdigest()
    return hashlib.sha256(content_bytes).hexdigest()


class ReleaseLedgerError(ValueError):
    """Raised when the release ledger cannot be loaded or fails validation."""


def load_release_ledger(path: Path | None = None) -> dict[str, Any]:
    """Load a detached release-ledger document without consulting donor runtimes."""
    ledger_path = path or RELEASE_LEDGER_PATH
    try:
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseLedgerError(
            f"release ledger cannot be loaded from {ledger_path}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise ReleaseLedgerError("release ledger must be a JSON object")
    return document


def _dicts(entries: Any) -> list[dict[str, Any]]:
    return [entry for entry in entries if isinstance(entry, dict)]


def _fail_closed_blocker_entries(
    label: str,
    entries: Any,
    errors: list[str],
) -> list[dict[str, Any]]:
    """Return only object blocker entries, reporting every non-object entry so the
    validator stays total on malformed arrays instead of silently dropping them."""
    if not isinstance(entries, list):
        errors.append(f"{label} must be a list")
        return []
    invalid = [item for item in entries if not isinstance(item, dict)]
    if invalid:
        errors.append(
            f"{label} contains {len(invalid)} non-object entr"
            + ("y" if len(invalid) == 1 else "ies")
            + " that are rejected"
        )
    return [item for item in entries if isinstance(item, dict)]



def validate_release_ledger(
    ledger: dict[str, Any],
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> list[str]:
    """Return fail-closed structural and semantic errors for the release ledger."""
    errors: list[str] = []
    if not isinstance(ledger, dict):
        return ["release ledger must be an object"]
    if ledger.get("ledger_id") != RELEASE_LEDGER_ID:
        errors.append(f"release ledger id must be {RELEASE_LEDGER_ID!r}")
    if ledger.get("schema_version") != RELEASE_LEDGER_SCHEMA_VERSION:
        errors.append(
            f"release ledger schema_version must be {RELEASE_LEDGER_SCHEMA_VERSION!r}"
        )

    policy = ledger.get("policy")
    if policy != EXPECTED_POLICY:
        errors.append("release ledger policy does not match fail-closed release policy")
        # Fail closed: never trust an authored policy that differs from the expectation.
        # Use the expected vocabulary so downstream loops are safe, but the error above
        # already makes the ledger invalid.
        policy = EXPECTED_POLICY

    phases = policy["release_phases"]
    outcomes = policy["closure_outcomes"]
    phases_set = set(phases)
    outcomes_set = set(outcomes)

    actual_targets = ledger.get("score_targets")
    if isinstance(actual_targets, dict):
        for tier in RECOVERY_TIERS:
            if actual_targets.get(tier) != EXPECTED_SCORE_TARGETS[tier]:
                errors.append(f"score_targets.{tier} must be {EXPECTED_SCORE_TARGETS[tier]}")
    else:
        errors.append("score_targets must be an object")

    suites_block = ledger.get("suites")
    if not isinstance(suites_block, dict):
        return errors + ["release ledger suites must be an object"]

    # Exhaustive coverage: the ledger must name exactly the registered suites. A ledger
    # that omits a registered suite, or lists one the registry does not govern, could
    # report release_ready by dropping the weakest members -- fail closed on either.
    ledger_suite_ids = set(suites_block)
    registered_suite_ids = set(suites)
    if ledger_suite_ids != registered_suite_ids:
        missing = registered_suite_ids - ledger_suite_ids
        unknown = ledger_suite_ids - registered_suite_ids
        if missing:
            errors.append(
                "release ledger omits registered suites: "
                + ", ".join(sorted(missing))
            )
        if unknown:
            errors.append(
                "release ledger references unknown suites: "
                + ", ".join(sorted(unknown))
            )

    # Obligation ids the recovery program actually governs (for ref validation).
    program_obligations = program.get("obligations")
    if not isinstance(program_obligations, list):
        errors.append("recovery program obligations must be a list")
        program_obligations = []
    governed_obligation_ids = {
        obligation.get("id")
        for obligation in program_obligations
        if isinstance(obligation, dict) and isinstance(obligation.get("id"), str)
    }
    obligation_by_id = {
        obligation["id"]: obligation
        for obligation in program_obligations
        if isinstance(obligation, dict) and isinstance(obligation.get("id"), str)
    }
    # Every governed obligation must be covered by at least one criterion reference, or
    # the ledger could claim release_ready while an obligation is silently orphaned.
    covered_obligation_ids: set[str] = set()

    for suite_id, suite_block in suites_block.items():
        if suite_id not in suites:
            continue
        if not isinstance(suite_block, dict):
            errors.append(f"release ledger suite {suite_id} must be an object")
            continue

        phase = suite_block.get("release_phase")
        if not isinstance(phase, str) or phase not in phases_set:
            errors.append(f"{suite_id}: invalid release_phase {phase!r}")

        owner = suite_block.get("release_phase_owner")
        if owner is not None and (not isinstance(owner, str) or not owner.strip()):
            errors.append(f"{suite_id}: release_phase_owner must be null or a non-empty string")

        block_level = suite_block.get("recovery_depth")
        if not isinstance(block_level, str) or block_level not in RECOVERY_PROMOTION_LEVELS:
            errors.append(
                f"{suite_id}: invalid recovery_depth {block_level!r}; "
                f"must be one of {RECOVERY_PROMOTION_LEVELS}"
            )
        elif isinstance(phase, str) and phase in SUPPORT_PROMISE_PHASES:
            if RECOVERY_PROMOTION_LEVELS.index(block_level) < RECOVERY_PROMOTION_LEVELS.index(
                MIN_SUPPORT_PROMISE_LEVEL
            ):
                errors.append(
                    f"{suite_id}: {phase} phase cannot claim depth {block_level}; "
                    f"requires at least {MIN_SUPPORT_PROMISE_LEVEL}"
                )

        if (isinstance(phase, str) and phase in SUPPORT_PROMISE_PHASES
                and isinstance(block_level, str) and block_level in RECOVERY_PROMOTION_LEVELS
                and RECOVERY_PROMOTION_LEVELS.index(block_level)
                >= RECOVERY_PROMOTION_LEVELS.index(MIN_SUPPORT_PROMISE_LEVEL)):
            errors.extend(_support_promise_evidence_errors(suite_id, block_level, program, suites))

        # A support promise ("supported"/"beta"/"release-candidate") is never automatic:
        # it is an owner-backed declaration. Requiring an owner prevents an anonymous
        # suite from claiming a support promise, and mirrors the DESIGN §3 rule that any
        # such phase must carry explicit owner authority -- not just a recoverable depth.
        if isinstance(phase, str) and phase in SUPPORT_PROMISE_PHASES and (not isinstance(owner, str) or not owner.strip()):
            errors.append(
                f"{suite_id}: {phase} phase requires a release_phase_owner "
                "(a support promise is an owner-backed declaration, never automatic)"
            )

        if phase == "deprecated":
            if not isinstance(owner, str) or not owner.strip():
                errors.append(
                    f"{suite_id}: deprecated phase requires a release_phase_owner "
                    "(deprecation is an owner-backed lifecycle declaration)"
                )
        elif phase == "retired":
            if not isinstance(owner, str) or not owner.strip():
                errors.append(
                    f"{suite_id}: retired phase requires a release_phase_owner "
                    "(retirement requires explicit owner approval per recovery standard)"
                )
            errors.extend(_retired_suite_errors(suite_id, owner, suite_block, program, suites))

        score_status = suite_block.get("score_status")
        score = suite_block.get("score")
        if score_status != "insufficient_dimension_evidence":
            errors.append(
                f"{suite_id}: invalid score_status {score_status!r}; no numeric score is "
                "accepted until a dimension-derived recovery score computation exists "
                "in the control plane (authored numbers are false precision)"
            )
        if score is not None:
            errors.append(
                f"{suite_id}: authored score {score!r} is rejected; scores must be "
                "derived from validated dimension evidence once "
                "insufficient_dimension_evidence is lifted"
            )

        criteria = suite_block.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            errors.append(f"{suite_id}: criteria must be a non-empty list")
            continue
        if any(not isinstance(criterion, dict) for criterion in criteria):
            errors.append(f"{suite_id}: every criterion must be an object")
        seen: set[str] = set()
        for criterion in _dicts(criteria):
            criterion_id = criterion.get("id")
            if isinstance(criterion_id, str) and criterion_id:
                if criterion_id in seen:
                    errors.append(f"{suite_id}: duplicate criterion id {criterion_id!r}")
                seen.add(criterion_id)
        for index, criterion in enumerate(_dicts(criteria)):
            referenced: set[str] = set()
            criterion_id = criterion.get("id")
            if not isinstance(criterion_id, str) or not criterion_id:
                errors.append(f"{suite_id}: criterion {index} needs a non-empty id")
                continue
            status = criterion.get("status")
            if not isinstance(status, str) or status not in {"open", "closed"}:
                errors.append(f"{criterion_id}: invalid status {status!r}")
                continue
            refs = criterion.get("obligation_refs")
            if not isinstance(refs, list) or not refs:
                errors.append(
                    f"{criterion_id}: obligation_refs must be a non-empty list "
                    "(a criterion that owns no obligation could not move a release gate)"
                )
            else:
                for ref_index, ref in enumerate(refs):
                    if not isinstance(ref, dict):
                        errors.append(
                            f"{criterion_id}: obligation_ref {ref_index} must be an "
                            "object with an id; string refs are rejected to avoid a "
                            "criterion silently governing nothing"
                        )
                        continue
                    obligation_id = ref.get("id")
                    if not isinstance(obligation_id, str) or obligation_id not in governed_obligation_ids:
                        errors.append(
                            f"{criterion_id}: unknown obligation_ref {obligation_id!r}"
                        )
                    elif obligation_id.split("/", 1)[0] != suite_id:
                        errors.append(
                            f"{criterion_id}: obligation_ref {obligation_id} belongs to another suite"
                        )
                    else:
                        referenced.add(obligation_id)
                covered_obligation_ids.update(referenced)
            closure = criterion.get("closure")
            if status == "open" and closure is not None:
                errors.append(f"{criterion_id}: open criterion must not carry a closure")
            if status == "closed" and closure is None:
                errors.append(f"{criterion_id}: closed criterion requires a closure record")
                continue
            if closure is not None:
                governed_obligations = [
                    obligation_by_id[obligation_id]
                    for obligation_id in referenced
                    if obligation_id in obligation_by_id
                ]
                for c_error in _closure_errors(
                    criterion_id, closure, outcomes_set, suite_id, governed_obligations
                ):
                    errors.append(c_error)

    # Every governed obligation must be covered by at least one criterion reference.
    # An obligation no criterion owns is invisible to the release gates and could stay
    # unimplemented while the ledger claims completion -- fail closed on the gap.
    uncovered = governed_obligation_ids - covered_obligation_ids
    if uncovered:
        errors.append(
            "release ledger does not cover governed obligations: "
            + ", ".join(sorted(uncovered))
        )

    blocker_entries = _fail_closed_blocker_entries(
        "release_blockers", ledger.get("release_blockers"), errors
    )
    blocker_by_id: dict[str, dict[str, Any]] = {}
    runtime_owners: dict[str, list[str]] = {}
    for index, blocker in enumerate(blocker_entries):
        blocker_id = blocker.get("id")
        if not isinstance(blocker_id, str) or not blocker_id:
            errors.append(f"release blocker {index} needs a non-empty id")
            continue
        if blocker_id in blocker_by_id:
            errors.append(f"duplicate release blocker id: {blocker_id}")
            continue
        blocker_by_id[blocker_id] = blocker
        phase_val = blocker.get("phase")
        if not isinstance(phase_val, str) or phase_val not in PHASES_COVERED:
            errors.append(
                f"{blocker_id}: invalid phase {phase_val!r}; this partial "
                f"ledger covers roadmap phases {sorted(PHASES_COVERED)} only"
            )
        depends_on = blocker.get("depends_on")
        if (not isinstance(depends_on, list)
                or any(not isinstance(item, str) or not item for item in depends_on)):
            errors.append(f"{blocker_id}: depends_on must be an explicit string list")
        for field in ("name", "note"):
            value = blocker.get(field)
            if value is not None and not isinstance(value, str):
                errors.append(f"{blocker_id}: {field} must be a string")
        obligation_refs = blocker.get("obligation_refs")
        if not isinstance(obligation_refs, list) or not obligation_refs:
            errors.append(
                f"{blocker_id}: release blocker requires a non-empty obligation_refs "
                "(a blocker with no dischargeable obligation would vanish from the "
                "release gates without a closure record; fold process gates into "
                "global_blockers with an explicit closure)"
            )
        elif any(not isinstance(item, str) or not item for item in obligation_refs):
            errors.append(f"{blocker_id}: obligation_refs must be a string list")
        else:
            for obligation_id in obligation_refs:
                if obligation_id not in governed_obligation_ids:
                    errors.append(
                        f"{blocker_id}: unknown obligation_ref {obligation_id!r}"
                    )
                else:
                    runtime_owners.setdefault(obligation_id, []).append(blocker_id)

    # Every obligation gets one visible queue entry. Criterion coverage alone cannot
    # stop `next` from hiding most of the work behind a single exemplar blocker.
    for obligation_id in sorted(governed_obligation_ids):
        owners = runtime_owners.get(obligation_id, [])
        if len(owners) != 1:
            errors.append(f"{obligation_id}: requires exactly one release blocker; found {len(owners)}")
            continue
        blocker = blocker_by_id[owners[0]]
        obligation = obligation_by_id[obligation_id]
        suite_id = obligation_id.split('/', 1)[0]
        expected_phase = ('5' if obligation.get('target_claim_kind') == 'adoption' else
                          '2' if suite_id in {'accessibility', 'operator-os', 'brand-publishing'} else
                          '3' if suite_id in {'production-house', 'discovery-decision'} else '4')
        if blocker.get('phase') != expected_phase:
            errors.append(f"{blocker['id']}: governed obligation belongs to phase {expected_phase}")
        required_dependencies = {"phase1.contract-state-freeze"}
        for dependency in obligation.get("dependencies", []):
            required_dependencies.update(runtime_owners.get(dependency, []))
        actual_dependencies = blocker.get("depends_on")
        if isinstance(actual_dependencies, list) and all(isinstance(x, str) for x in actual_dependencies):
            missing = required_dependencies - set(actual_dependencies)
            if missing:
                errors.append(f"{blocker['id']}: missing governed dependencies: {sorted(missing)}")

    global_blocker_entries = _fail_closed_blocker_entries(
        "global_blockers", ledger.get("global_blockers"), errors
    )
    seen_global_ids: set[str] = set()
    for index, blocker in enumerate(global_blocker_entries):
        blocker_id = blocker.get("id")
        if not isinstance(blocker_id, str) or not blocker_id:
            errors.append(f"global blocker {index} needs a non-empty id")
            continue
        if blocker_id in blocker_by_id:
            errors.append(
                f"global blocker {blocker_id} collides with a release blocker id; "
                "blocker ids must be unique across both lists"
            )
        if blocker_id in seen_global_ids:
            errors.append(
                f"duplicate global blocker id: {blocker_id}; a duplicate closed entry "
                "could override an open gate in the dependency resolution"
            )
        seen_global_ids.add(blocker_id)
        phase_val = blocker.get("phase")
        if not isinstance(phase_val, str) or phase_val not in PHASES_COVERED:
            errors.append(
                f"global blocker {blocker_id}: invalid phase {phase_val!r}; "
                f"this partial ledger covers roadmap phases {sorted(PHASES_COVERED)} only"
            )
        elif blocker_id in GLOBAL_BLOCKER_EXPECTED_PHASES:
            expected_phase = GLOBAL_BLOCKER_EXPECTED_PHASES[blocker_id]
            if phase_val != expected_phase:
                errors.append(
                    f"global blocker {blocker_id}: phase {phase_val!r} does not match "
                    f"governed expected phase {expected_phase!r}"
                )
        depends_on = blocker.get("depends_on")
        if depends_on is not None and (
            not isinstance(depends_on, list)
            or any(not isinstance(item, str) or not item for item in depends_on)
        ):
            errors.append(f"global blocker {blocker_id}: depends_on must be a string list")
        name_value = blocker.get("name")
        if name_value is not None and not isinstance(name_value, str):
            errors.append(f"global blocker {blocker_id}: name must be a string")
        closure = blocker.get("closure")
        if "closed" in blocker:
            errors.append(
                f"global blocker {blocker_id}: a bare 'closed' flag is not valid; a "
                "phase-boundary gate closes only through an evidence- and owner-bound "
                "'closure' record, so flipping a boolean cannot authorize dependent work"
            )
        if closure is not None:
            for closure_error in _global_blocker_closure_errors(blocker_id, closure):
                errors.append(closure_error)

    # Require exact set equality for governed global gates
    required_global_ids = set(GLOBAL_BLOCKER_SPECS.keys())
    missing_global_ids = required_global_ids - seen_global_ids
    if missing_global_ids:
        errors.append(
            f"global_blockers missing mandatory gate(s): {sorted(missing_global_ids)}"
        )
    unrecognized_global_ids = seen_global_ids - required_global_ids
    if unrecognized_global_ids:
        errors.append(
            f"global_blockers contains unrecognized gate(s): {sorted(unrecognized_global_ids)}"
        )

    # Release and global blockers share one dependency namespace, so both lists are
    # checked together. A dependency on an unknown id, or a cycle (self-dependency
    # included), leaves a gate permanently non-actionable with no closure record --
    # the same silent-never-unblocks failure the obligation_refs rule forbids.
    depends_by_id: dict[str, set[str]] = {}
    for blocker in list(blocker_by_id.values()) + global_blocker_entries:
        blocker_id = blocker.get("id")
        if not isinstance(blocker_id, str) or not blocker_id:
            continue
        depends_on = blocker.get("depends_on")
        depends_by_id[blocker_id] = {
            item for item in (depends_on if isinstance(depends_on, list) else []) if isinstance(item, str) and item
        }
    for blocker_id, dependencies in depends_by_id.items():
        for dependency in sorted(dependencies):
            if dependency not in depends_by_id:
                errors.append(f"{blocker_id}: depends_on unknown blocker {dependency!r}")
    try:
        # Unknown edges are dropped so a cycle report names only real blockers.
        TopologicalSorter(
            {
                blocker_id: dependencies & depends_by_id.keys()
                for blocker_id, dependencies in depends_by_id.items()
            }
        ).prepare()
    except CycleError as error:
        errors.append(f"blocker depends_on cycle: {' -> '.join(error.args[1])}")

    return errors


def _retired_suite_errors(
    suite_id: str,
    owner: Any,
    suite_block: dict[str, Any],
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate a retired suite's retirement record, its receipt, and the consumed approval."""
    errors: list[str] = []
    retirement = suite_block.get("retirement")
    if not isinstance(retirement, dict):
        errors.append(
            f"{suite_id}: retired phase requires a governed retirement disposition "
            "record with owner approval and disposition evidence"
        )
    else:
        ret_owner = retirement.get("owner")
        if not isinstance(ret_owner, str) or not ret_owner.strip():
            errors.append(f"{suite_id}: retirement record requires an owner")
        elif isinstance(owner, str) and ret_owner != owner:
            errors.append(
                f"{suite_id}: retirement owner {ret_owner!r} does not match release_phase_owner {owner!r}"
            )
        disposition = retirement.get("disposition") or retirement.get("rationale")
        if not isinstance(disposition, str) or not disposition.strip():
            errors.append(f"{suite_id}: retirement record requires a disposition rationale")
        ret_evidence = retirement.get("evidence_ref")
        if not isinstance(ret_evidence, str) or not ret_evidence.strip():
            errors.append(f"{suite_id}: retirement record requires an evidence_ref")
        else:
            from .registry import resolve_declared_evidence_path

            ev_path = resolve_declared_evidence_path(ret_evidence, suite_id)
            if ev_path is None or not ev_path.is_file():
                errors.append(
                    f"{suite_id}: retirement evidence artifact is missing on disk: {ret_evidence!r}"
                )
            else:
                try:
                    doc = json.loads(ev_path.read_text(encoding="utf-8"))
                    if not isinstance(doc, dict):
                        errors.append(f"{suite_id}: retirement evidence must be a JSON object")
                    else:
                        version = doc.get("receipt_version")
                        if version != SUITE_RETIREMENT_RECEIPT_CONTRACT:
                            errors.append(
                                f"{suite_id}: retirement evidence receipt_version must equal "
                                f"{SUITE_RETIREMENT_RECEIPT_CONTRACT!r}; found {version!r}"
                            )
                        rec_suite = doc.get("suite_id")
                        if rec_suite != suite_id:
                            errors.append(
                                f"{suite_id}: retirement evidence suite_id {rec_suite!r} "
                                f"does not match retired suite {suite_id!r}"
                            )
                        rec_owner = doc.get("owner")
                        if isinstance(owner, str) and rec_owner != owner:
                            errors.append(
                                f"{suite_id}: retirement evidence owner {rec_owner!r} "
                                f"does not match release_phase_owner {owner!r}"
                            )
                        decision = doc.get("decision")
                        if not isinstance(decision, str) or decision not in {"retire", "retired"}:
                            errors.append(
                                f"{suite_id}: retirement evidence decision must be 'retire' or 'retired'; "
                                f"found {decision!r}"
                            )
                        rec_disposition = doc.get("disposition")
                        if not isinstance(rec_disposition, str) or not rec_disposition.strip():
                            errors.append(
                                f"{suite_id}: retirement evidence requires a non-empty 'disposition' statement"
                            )
                        elif isinstance(disposition, str) and disposition.strip() and rec_disposition.strip() != disposition.strip():
                            errors.append(
                                f"{suite_id}: retirement evidence disposition does not match ledger retirement disposition"
                            )
                        donor = doc.get("donor")
                        if not isinstance(donor, str) or not donor.strip():
                            errors.append(
                                f"{suite_id}: retirement evidence requires a non-empty 'donor' identifier"
                            )
                        supporting = doc.get("supporting_evidence_refs")
                        valid_supporting = (
                            isinstance(supporting, list) and bool(supporting)
                            and all(isinstance(ref, str) and ref.strip() for ref in supporting)
                            and len(set(supporting)) == len(supporting)
                        )
                        support_hashes = doc.get("supporting_evidence_sha256")
                        valid_hashes = (
                            valid_supporting and isinstance(support_hashes, dict)
                            and set(support_hashes) == set(supporting)
                            and all(isinstance(value, str) and SHA256_HEX.fullmatch(value)
                                    for value in support_hashes.values())
                        )
                        if not valid_supporting:
                            errors.append(
                                f"{suite_id}: retirement evidence requires a non-empty, distinct "
                                "'supporting_evidence_refs' string list of recovery/parity evidence"
                            )
                        if not valid_hashes:
                            errors.append(
                                f"{suite_id}: retirement supporting_evidence_sha256 must bind "
                                "exactly every supporting reference to a SHA-256 digest"
                            )
                        else:
                            errors.extend(_retirement_supporting_evidence_errors(
                                suite_id, support_hashes, program, suites
                            ))

                        # Operator approval authority verification
                        approval = doc.get("approval")
                        if not isinstance(approval, dict):
                            errors.append(
                                f"{suite_id}: retirement evidence requires a verified operator 'approval' record "
                                "from the independent approval authority"
                            )
                        else:
                            schema = approval.get("schema")
                            if schema != APPROVAL_SCHEMA:
                                errors.append(
                                    f"{suite_id}: retirement approval schema must be {APPROVAL_SCHEMA!r}; "
                                    f"found {schema!r}"
                                )
                            app_id = approval.get("approval_id")
                            if not isinstance(app_id, str) or not app_id.strip():
                                errors.append(
                                    f"{suite_id}: retirement approval requires an 'approval_id'"
                                )
                            token_hash = approval.get("token_sha256")
                            if not isinstance(token_hash, str) or not token_hash.strip():
                                errors.append(
                                    f"{suite_id}: retirement approval requires 'token_sha256'"
                                )
                            consumed_bindings = approval.get("consumed_bindings")
                            if not isinstance(consumed_bindings, dict):
                                errors.append(
                                    f"{suite_id}: retirement approval requires 'consumed_bindings'"
                                )
                            operation = approval.get("operation")
                            if not isinstance(operation, str) or operation not in {"suite-retirement", "retire"}:
                                errors.append(
                                    f"{suite_id}: retirement approval operation must be 'suite-retirement'; "
                                    f"found {operation!r}"
                                )
                            reviewer = approval.get("reviewer")
                            if isinstance(owner, str) and reviewer != owner:
                                errors.append(
                                    f"{suite_id}: retirement approval reviewer {reviewer!r} "
                                    f"does not match release_phase_owner {owner!r}"
                                )
                            app_decision = approval.get("decision")
                            if app_decision != decision:
                                errors.append(
                                    f"{suite_id}: retirement approval decision {app_decision!r} "
                                    f"does not match receipt decision {decision!r}"
                                )
                            consumed = approval.get("consumed")
                            if consumed is not True:
                                errors.append(
                                    f"{suite_id}: retirement approval must be consumed (consumed=True)"
                                )
                            # Validate timezone-aware ISO timestamps and chronology
                            parsed_times: dict[str, datetime.datetime] = {}
                            for time_field in ("issued_at", "expires_at", "consumed_at"):
                                val = approval.get(time_field)
                                try:
                                    parsed_t = datetime.datetime.fromisoformat(str(val))
                                    if parsed_t.tzinfo is None:
                                        errors.append(
                                            f"{suite_id}: retirement approval {time_field} must be timezone-aware"
                                        )
                                    else:
                                        parsed_times[time_field] = parsed_t
                                except (ValueError, TypeError):
                                    errors.append(
                                        f"{suite_id}: retirement approval {time_field} is not a valid ISO timestamp: {val!r}"
                                    )
                            if len(parsed_times) == 3:
                                if parsed_times["expires_at"] <= parsed_times["issued_at"]:
                                    errors.append(
                                        f"{suite_id}: retirement approval expires at or before it was issued"
                                    )
                                if parsed_times["consumed_at"] < parsed_times["issued_at"]:
                                    errors.append(
                                        f"{suite_id}: retirement approval was consumed before it was issued"
                                    )
                                if parsed_times["consumed_at"] > parsed_times["expires_at"]:
                                    errors.append(
                                        f"{suite_id}: retirement approval was consumed after it expired"
                                    )
                            # Validate bound payload canonical digest
                            expected_digest = None
                            if (isinstance(donor, str) and donor.strip() and isinstance(rec_disposition, str)
                                    and isinstance(decision, str) and valid_hashes):
                                expected_payload = {
                                    "suite_id": suite_id,
                                    "donor": donor,
                                    "decision": decision,
                                    "disposition": rec_disposition,
                                    "supporting_evidence_refs": sorted(supporting),
                                    "supporting_evidence_sha256": support_hashes,
                                }
                                expected_digest = canonical_digest(expected_payload)
                                payload_sha256 = approval.get("payload_sha256")
                                if payload_sha256 != expected_digest:
                                    errors.append(
                                        f"{suite_id}: retirement approval payload_sha256 does not bind "
                                        f"exact retirement payload: expected {expected_digest[:12]}… but got {payload_sha256!r}"
                                    )
                            # Verify against independent out-of-band authority store
                            if expected_digest is not None and isinstance(app_id, str) and app_id.strip():
                                expected_bindings = {
                                    "suite_id": suite_id,
                                    "donor": donor,
                                    "decision": decision,
                                    "operation": operation,
                                    "reviewer": owner,
                                    "payload_sha256": expected_digest,
                                }
                                try:
                                    verified_record = verify_consumed_operator_approval(
                                        app_id,
                                        bindings=expected_bindings,
                                    )
                                    for check_key in (
                                        "approval_id",
                                        "schema",
                                        "token_sha256",
                                        "operation",
                                        "decision",
                                        "reviewer",
                                        "payload_sha256",
                                        "consumed",
                                        "consumed_at",
                                    ):
                                        if approval.get(check_key) != verified_record.get(check_key):
                                            errors.append(
                                                f"{suite_id}: retirement approval field {check_key!r} "
                                                "differs from authority store record"
                                            )
                                except ApprovalError as err:
                                    errors.append(
                                        f"{suite_id}: retirement approval could not be verified against "
                                        f"independent authority: {err}"
                                    )
                except (OSError, ValueError) as err:
                    errors.append(f"{suite_id}: retirement evidence is not readable JSON: {err}")
    return errors


def _support_promise_evidence_errors(
    suite_id: str,
    declared_depth: str,
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> list[str]:
    """Require retained, governed execution evidence for the promised depth."""
    from .registry import build_evidence_ownership_index, get_wave_evidence_status

    required_rank = RECOVERY_PROMOTION_LEVELS.index(declared_depth)
    ownership = build_evidence_ownership_index(suites)
    for wave in suites[suite_id].get("waves", []):
        claim = wave.get("recovery_claim") or {}
        level = claim.get("level")
        if (wave.get("status") != "complete"
                or claim.get("kind") not in ("runtime", "adoption", "convergence")
                or not isinstance(level, str) or level not in RECOVERY_PROMOTION_LEVELS
                or RECOVERY_PROMOTION_LEVELS.index(level) < required_rank):
            continue
        if get_wave_evidence_status(suite_id, wave, ownership)["evidence_valid"]:
            return []

    # Lifecycle receipts may prove a higher rung than the original wave. The owning
    # program verifies their retained bindings and dependency state before use here.
    try:
        obligations = resolve_recovery_obligations(program, suites)
    except RecoveryProgramError as error:
        return [f"{suite_id}: support-promise evidence cannot be verified: {error}"]
    for obligation in obligations:
        level = obligation.get("target_level")
        if (obligation["suite_id"] == suite_id and obligation["effective_state"] == "discharged"
                and obligation.get("target_claim_kind") in ("runtime", "adoption", "convergence")
                and isinstance(level, str) and level in RECOVERY_PROMOTION_LEVELS
                and RECOVERY_PROMOTION_LEVELS.index(level) >= required_rank):
            return []
    return [f"{suite_id}: no validated retained execution evidence supports recovery_depth {declared_depth!r}"]


def _retirement_supporting_evidence_errors(
    suite_id: str,
    hashes: dict[str, str],
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> list[str]:
    """Bind retirement support to unchanged bytes and their owning receipt validators."""
    from .registry import build_evidence_ownership_index, get_wave_evidence_status, resolve_declared_evidence_path

    errors: list[str] = []
    ownership = build_evidence_ownership_index(suites)
    waves = suites[suite_id].get("waves", [])
    resolved: list[dict[str, Any]] | None = None  # resolved lazily, at most once
    for ref, expected in hashes.items():
        if resolve_declared_evidence_path(ref, suite_id) is None:
            errors.append(f"{suite_id}: retirement supporting evidence must stay in its canonical suite evidence directory: {ref}")
            continue
        before, read_error = _read_confined_suites_file(ref)
        if before is None:
            errors.append(f"{suite_id}: retirement supporting evidence cannot be read: {ref}: {read_error}")
            continue
        if hashlib.sha256(before).hexdigest() != expected:
            errors.append(f"{suite_id}: retirement supporting evidence digest mismatch: {ref}")
            continue
        owners = [wave for wave in waves if wave.get("status") == "complete" and wave.get("evidence") == ref]
        if len(owners) == 1:
            status = get_wave_evidence_status(suite_id, owners[0], ownership)
            errors.extend(f"{suite_id}: retirement supporting evidence {ref}: {error}"
                          for error in status["evidence_errors"])
        else:
            lifecycle = [o for o in program.get("obligations", [])
                         if isinstance(o, dict) and isinstance(o.get("id"), str)
                         and o["id"].startswith(suite_id + "/")
                         and o.get("source") == "lifecycle" and o.get("evidence") == ref]
            if len(lifecycle) != 1:
                errors.append(f"{suite_id}: retirement supporting evidence has no unique governed receipt owner: {ref}")
            else:
                try:
                    if resolved is None:
                        resolved = resolve_recovery_obligations(program, suites)
                    if not any(o["id"] == lifecycle[0]["id"] and o["effective_state"] == "discharged" for o in resolved):
                        errors.append(f"{suite_id}: retirement supporting lifecycle evidence is not discharged: {ref}")
                except RecoveryProgramError as error:
                    errors.append(f"{suite_id}: retirement supporting lifecycle evidence is invalid: {error}")
        after, read_error = _read_confined_suites_file(ref)
        if after != before or read_error:
            errors.append(f"{suite_id}: retirement supporting evidence changed during validation: {ref}")
    return errors


def _closure_errors(
    criterion_id: str,
    closure: dict[str, Any],
    outcomes: set[str],
    suite_id: str,
    governed_obligations: list[dict[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(closure, dict):
        return [f"{criterion_id}: closure must be an object"]
    outcome = closure.get("outcome")
    owner = closure.get("owner")
    if not isinstance(outcome, str) or outcome not in outcomes:
        errors.append(f"{criterion_id}: invalid closure outcome {outcome!r}")
    if isinstance(outcome, str) and outcome in {"implemented", "already_covered", "independently_retained"}:
        for evidence_error in _closure_evidence_errors(
            closure, suite_id, criterion_id, governed_obligations or []
        ):
            errors.append(evidence_error)
    if not isinstance(owner, str) or not owner.strip():
        errors.append(f"{criterion_id}: closure requires a non-empty owner")
    if outcome == "deferred_with_trigger":
        trigger = closure.get("resume_trigger")
        if not (
            isinstance(trigger, dict)
            and isinstance(trigger.get("condition"), str)
            and trigger["condition"].strip()
        ):
            errors.append(f"{criterion_id}: deferred_with_trigger requires a resume_trigger condition")
    # "resolved" with no evidence/owner is forbidden per policy; the owner check above
    # already enforces the owner half, and the evidence half only for implemented-style
    # outcomes. A rejected/deferred closure still needs the dated rationale.
    if isinstance(outcome, str) and outcome in {"rejected", "deferred_with_trigger"} and (
        not isinstance(closure.get("rationale"), str) or not closure["rationale"].strip()
    ):
        errors.append(f"{criterion_id}: {outcome} closure requires a rationale")
    return errors


def _closure_evidence_errors(
    closure: dict[str, Any],
    suite_id: str,
    criterion_id: str,
    governed_obligations: list[dict[str, Any]],
) -> list[str]:
    """Fail-closed integrity check on a closure's retained evidence artifact.

    An evidence ref is not proof by virtue of being a confined string. It must resolve
    to a real artifact of the canonical ``<suite>/evidence/<file>`` shape (no traversal,
    no symlink escape, right suite) that actually exists on disk, parse as a JSON object,
    and pass the governed receipt validator (:func:`receipts.evidence_errors`) for the
    criterion's obligations -- the same bridge the recovery program uses for a discharged
    obligation. ``evidence_errors`` enforces the receipt contract, a host-recomputed
    content digest, provenance/fingerprints, freshness, candidate identity, and parity
    semantics, so a bare object like ``{}`` can never pass as implementation evidence.
    """
    from .receipts import evidence_errors
    from .registry import resolve_declared_evidence_path

    errors: list[str] = []
    ref = closure.get("evidence_ref")
    path = resolve_declared_evidence_path(ref, suite_id)
    if path is None:
        errors.append(
            f"{criterion_id}: closure evidence_ref must resolve to the canonical "
            f"{suite_id}/evidence/<file> inside the suite; got {ref!r}"
        )
        return errors
    if not path.is_file():
        errors.append(
            f"{criterion_id}: closure evidence artifact is missing on disk: {ref}"
        )
        return errors
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(
            f"{criterion_id}: closure evidence artifact is not a readable JSON receipt: {error}"
        )
        return errors

    # Dispatch through each governed obligation's receipt contract. The closure evidence
    # must be a genuine governed receipt for at least one of the criterion's obligations;
    # if none of them validate it (or none carry a contract), the closure cannot be proven
    # and fails closed.
    claim_waves: list[tuple[str, dict[str, Any]]] = []
    for obligation in governed_obligations:
        kind = obligation.get("target_claim_kind")
        contract = obligation.get("receipt_contract")
        if not isinstance(kind, str) or not isinstance(contract, str):
            continue
        claim_waves.append(
            (
                obligation.get("id", "?"),
                {
                    "id": criterion_id,
                    "recovery_claim": {
                        "kind": kind,
                        "level": obligation.get("target_level"),
                        "receipt_contract": contract,
                    },
                },
            )
        )
    if not claim_waves:
        errors.append(
            f"{criterion_id}: closure evidence cannot be routed to any governed receipt "
            "validator; the criterion references no obligation with a receipt contract"
        )
        return errors

    failures: list[str] = []
    for obligation_id, wave in claim_waves:
        receipt_errors = evidence_errors(wave, path, suite_id)
        if not receipt_errors:
            return errors
        for receipt_error in receipt_errors:
            failures.append(f"{obligation_id}: {receipt_error}")
    errors.append(
        f"{criterion_id}: closure evidence fails every governed receipt validator: "
        + "; ".join(failures)
    )
    return errors


def _read_confined_suites_file(path_text: str) -> tuple[bytes | None, str | None]:
    """Read a path relative to SUITES_ROOT using descriptor-confined directory walk."""
    if not isinstance(path_text, str) or not path_text:
        return None, "empty or non-string path"
    candidate = Path(path_text)
    if candidate.is_absolute():
        return None, f"path {path_text!r} must be relative to suites root"
    parts = candidate.parts
    if not parts or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
        return None, f"path {path_text!r} contains invalid path components"
    *parents, name = parts
    if not name:
        return None, f"path {path_text!r} has no filename component"

    anchor = SUITES_ROOT.resolve(strict=False)
    parent_path = Path(*parents) if parents else Path(".")
    parent_fd = None
    fd = None
    try:
        parent_fd = open_confined_directory(anchor, parent_path)
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, f"path {path_text!r} is not a regular file"
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks), None
    except ConfinementError as error:
        return None, f"confinement violation for {path_text!r}: {error}"
    except FileNotFoundError:
        return None, f"file not found on disk: {path_text}"
    except OSError as error:
        return None, f"unreadable file at {path_text}: {error}"
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _global_closure_evidence_receipt(
    ref: Any, blocker_id: str, owner: Any
) -> tuple[Path | None, list[str], dict[str, Any] | None]:
    """Resolve, load, and validate a global blocker's governed closure receipt."""
    from .registry import resolve_declared_evidence_path

    path = resolve_declared_evidence_path(ref, None)
    if path is None:
        return None, [
            f"global blocker {blocker_id}: closure evidence_ref must resolve to the "
            f"canonical <suite>/evidence/<file> inside the suites tree; got {ref!r}"
        ], None
    if not path.is_file():
        return path, [
            f"global blocker {blocker_id}: closure evidence artifact is missing on disk: {ref}"
        ], None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return path, [
            f"global blocker {blocker_id}: closure evidence artifact is not a readable "
            f"JSON receipt: {error}"
        ], None
    if not isinstance(document, dict):
        return path, [
            f"global blocker {blocker_id}: closure evidence artifact must be a JSON "
            "object receipt"
        ], None

    receipt_errors: list[str] = []
    receipt_version = document.get("receipt_version")
    if receipt_version != GLOBAL_CLOSURE_RECEIPT_CONTRACT:
        receipt_errors.append(
            f"global blocker {blocker_id}: closure evidence receipt_version must equal "
            f"{GLOBAL_CLOSURE_RECEIPT_CONTRACT!r}; got {receipt_version!r}"
        )
    receipt_blocker = document.get("blocker_id")
    if receipt_blocker != blocker_id:
        receipt_errors.append(
            f"global blocker {blocker_id}: closure evidence blocker_id {receipt_blocker!r} "
            f"does not match blocker {blocker_id!r}"
        )
    receipt_owner = document.get("owner")
    if not isinstance(receipt_owner, str) or not receipt_owner.strip():
        receipt_errors.append(
            f"global blocker {blocker_id}: closure evidence requires an owner"
        )
    elif isinstance(owner, str) and receipt_owner != owner:
        receipt_errors.append(
            f"global blocker {blocker_id}: closure evidence owner {receipt_owner!r} "
            f"does not match closure owner {owner!r}"
        )

    return path, receipt_errors, (document if not receipt_errors else None)


def _global_blocker_closure_errors(
    blocker_id: str,
    closure: Any,
) -> list[str]:
    """Fail-closed check on a phase-boundary gate's owner/evidence-bound closure."""
    errors: list[str] = []
    if not isinstance(closure, dict):
        errors.append(f"global blocker {blocker_id}: closure must be an object")
        return errors

    owner = closure.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        errors.append(
            f"global blocker {blocker_id}: closure requires a non-empty owner"
        )

    outcome = closure.get("outcome")
    if outcome is not None and (not isinstance(outcome, str) or outcome not in {"implemented", "already_covered", "independently_retained"}):
        errors.append(
            f"global blocker {blocker_id}: closure outcome {outcome!r} is not valid"
        )

    ref = closure.get("evidence_ref")
    path, path_errors, receipt_doc = _global_closure_evidence_receipt(ref, blocker_id, owner)
    for path_error in path_errors:
        errors.append(path_error)

    if blocker_id not in GLOBAL_BLOCKER_SPECS:
        errors.append(
            f"global blocker {blocker_id}: has no governed closure contract; cannot be closed "
            "without a registered specification of required surfaces and paths"
        )
        return errors

    spec = GLOBAL_BLOCKER_SPECS[blocker_id]

    frozen = closure.get("frozen_boundaries")
    if frozen is None:
        errors.append(
            f"global blocker {blocker_id}: closure requires frozen_boundaries recording "
            "exact per-surface version or digest bindings for every frozen surface"
        )
        return errors
    if not isinstance(frozen, dict) or not frozen:
        errors.append(
            f"global blocker {blocker_id}: frozen_boundaries must be a non-empty object mapping "
            "each frozen surface to its binding list"
        )
        return errors

    actual_surfaces = set(frozen.keys())
    expected_surfaces = set(spec.keys())
    missing_surfaces = expected_surfaces - actual_surfaces
    extra_surfaces = actual_surfaces - expected_surfaces

    if missing_surfaces:
        errors.append(
            f"global blocker {blocker_id}: frozen_boundaries missing required surface(s): "
            + ", ".join(sorted(missing_surfaces))
        )
    if extra_surfaces:
        errors.append(
            f"global blocker {blocker_id}: frozen_boundaries contains unpermitted surface(s): "
            + ", ".join(sorted(extra_surfaces))
        )

    # Validate each surface's bindings
    for surface in sorted(expected_surfaces):
        if surface not in frozen:
            continue
        bindings = frozen[surface]
        if not isinstance(bindings, list) or not bindings:
            errors.append(
                f"global blocker {blocker_id}: frozen_boundaries.{surface} must be a "
                "non-empty list of {path, sha256} bindings"
            )
            continue
        seen_paths: set[str] = set()
        actual_paths: set[str] = set()
        for binding in bindings:
            if not isinstance(binding, dict):
                errors.append(
                    f"global blocker {blocker_id}: frozen_boundaries.{surface} entry "
                    "must be an object with path and sha256"
                )
                continue
            b_path = binding.get("path")
            if isinstance(b_path, str) and b_path:
                if b_path in seen_paths:
                    errors.append(
                        f"global blocker {blocker_id}: frozen_boundaries.{surface} contains "
                        f"duplicate path binding: {b_path!r}"
                    )
                seen_paths.add(b_path)
                actual_paths.add(b_path)
            for item in _frozen_binding_errors(blocker_id, surface, binding):
                errors.append(item)

        expected_paths = spec[surface]
        missing_paths = expected_paths - actual_paths
        extra_paths = actual_paths - expected_paths
        if missing_paths:
            errors.append(
                f"global blocker {blocker_id}: frozen_boundaries.{surface} missing required path(s): "
                + ", ".join(sorted(missing_paths))
            )
        if extra_paths:
            errors.append(
                f"global blocker {blocker_id}: frozen_boundaries.{surface} contains unpermitted path(s): "
                + ", ".join(sorted(extra_paths))
            )

    # Validate receipt bindings
    if receipt_doc is not None:
        receipt_frozen = receipt_doc.get("frozen_boundaries")
        if not isinstance(receipt_frozen, dict) or not receipt_frozen:
            errors.append(
                f"global blocker {blocker_id}: closure receipt must contain a non-empty "
                "'frozen_boundaries' object binding the exact digest set"
            )
        else:
            if receipt_frozen != frozen:
                errors.append(
                    f"global blocker {blocker_id}: closure receipt frozen_boundaries does "
                    "not bind the exact digest set declared in closure"
                )

    return errors


def _frozen_binding_errors(
    blocker_id: str,
    surface: str,
    binding: dict[str, Any],
) -> list[str]:
    """Recompute a bound surface's content digest and require it to match the record."""
    path_text = binding.get("path")
    stated = binding.get("sha256")
    if not isinstance(path_text, str) or not path_text:
        return [
            f"global blocker {blocker_id}: frozen_boundaries.{surface} binding needs a "
            "non-empty path"
        ]
    if not isinstance(stated, str) or not re.fullmatch(SHA256_HEX, stated):
        return [
            f"global blocker {blocker_id}: frozen_boundaries.{surface} binding for "
            f"{path_text!r} needs a 64-hex sha256"
        ]
    payload, read_error = _read_confined_suites_file(path_text)
    if payload is None:
        return [
            f"global blocker {blocker_id}: frozen_boundaries.{surface} binding {path_text!r} "
            f"cannot be read under descriptor confinement: {read_error}"
        ]
    actual = canonical_suites_file_digest(path_text, payload)
    if actual != stated:
        return [
            f"global blocker {blocker_id}: frozen boundary {surface} digest mismatch "
            f"for {path_text}: bound {stated[:12]}… but current content is {actual[:12]}…"
        ]
    return []



def _resolve_criterion_state(
    criterion: dict[str, Any],
    obligation_effective: dict[str, str],
) -> dict[str, Any]:
    """Combine authored closure with the referenced obligations' resolved states.

    A criterion is *schedule-closed* only when it is authored closed AND every referenced
    obligation is discharged. The recovery program stays the authority for obligation-level
    truth; the ledger only aggregates. An authored closure over an undischarged obligation
    is not silently accepted -- the caller reports the residual obligations.
    """
    refs = criterion.get("obligation_refs") or []
    residual = []
    obligation_states = []
    obligation_states_by_id = {}
    for ref in _dicts(refs):
        obligation_id = ref.get("id")
        if not isinstance(obligation_id, str):
            continue
        state = obligation_effective.get(obligation_id, "unknown")
        obligation_states.append(state)
        obligation_states_by_id[obligation_id] = state
        if state != "discharged":
            residual.append({"id": obligation_id, "state": state})
    residual.sort(key=lambda item: item["id"])
    auth_state = criterion.get("status")
    closed = auth_state == "closed" and not residual
    return {
        "id": criterion.get("id"),
        "status": "closed" if closed else "open",
        "authored_status": auth_state,
        "closure": criterion.get("closure") if auth_state == "closed" else None,
        "obligation_states": obligation_states,
        "obligation_states_by_id": obligation_states_by_id,
        "residual_obligations": residual,
        "residual_obligation_ids": [item["id"] for item in residual],
        "reason": (
            None
            if closed
            else _closure_reason(auth_state, residual)
        ),
    }


def _closure_reason(auth_state: str | None, residual: list[Any]) -> str:
    if auth_state == "closed" and residual:
        return "authored closed but referenced obligations not discharged"
    return "not closed"


def resolve_release_state(
    ledger: dict[str, Any],
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Join the ledger to resolved recovery obligations and produce the release truth."""
    errors = validate_release_ledger(ledger, program, suites)
    if errors:
        raise ReleaseLedgerError("; ".join(errors))

    obligations = resolve_recovery_obligations(program, suites)
    effective_by_id = {
        obligation["id"]: obligation["effective_state"] for obligation in obligations
    }

    suite_rows: dict[str, Any] = {}
    for suite_id, suite_block in ledger.get("suites").items():
        criteria = []
        open_count = 0
        for criterion in _dicts(suite_block.get("criteria", [])):
            resolved = _resolve_criterion_state(criterion, effective_by_id)
            criteria.append(resolved)
            if resolved["status"] != "closed":
                open_count += 1
        suite_rows[suite_id] = {
            "id": suite_id,
            "release_phase": suite_block.get("release_phase"),
            "release_phase_owner": suite_block.get("release_phase_owner"),
            "score": suite_block.get("score"),
            "score_status": suite_block.get("score_status"),
            "criteria_total": len(criteria),
            "criteria_closed": len(criteria) - open_count,
            "criteria_open": open_count,
            "criteria": criteria,
        }

    # Two blocker kinds, one openness rule.
    #   - A release blocker is OPEN while any referenced recovery obligation is not
    #     discharged. It closes automatically once its obligations all discharge.
    #   - A global blocker (phase-boundary gate, e.g. the contract freeze) is a process
    #     gate, not an obligation-bound one. It closes only through a valid, evidence-
    #     and owner-bound closure record (see validate_release_ledger), never a bare flag.
    # A blocker is ACTIONABLE only when every blocker it depends_on is itself closed.
    phase_order = {phase: index for index, phase in enumerate(sorted(PHASES_COVERED))}

    global_blockers = []
    for b in _dicts(ledger.get("global_blockers", [])):
        global_blockers.append({
            "id": b.get("id"),
            "phase": b.get("phase"),
            "name": b.get("name"),
            "depends_on": b.get("depends_on") or [],
            "closure": b.get("closure"),
            "open": b.get("closure") is None,
        })

    obligations_by_id = {o['id']: o for o in program['obligations']}
    blockers = []
    for b in _dicts(ledger.get("release_blockers", [])):
        obligation_refs = b.get("obligation_refs") or []
        residual = [
            ref for ref in obligation_refs if effective_by_id.get(ref) != "discharged"
        ]
        blockers.append({
            "id": b["id"],
            "phase": b.get("phase"),
            "name": b.get("name"),
            "note": b.get("note"),
            "depends_on": b.get("depends_on") or [],
            "obligation_refs": obligation_refs,
            "residual_obligations": residual,
            "open": bool(residual),
            "sequence": min(obligations_by_id[ref]['sequence'] for ref in obligation_refs),
            "requirements": [{key: obligations_by_id[ref].get(key) for key in (
                'id', 'runtime_environment', 'owner_gate', 'receipt_contract', 'acceptance_checks', 'target_level'
            )} for ref in obligation_refs],
        })

    all_blockers = blockers + global_blockers
    closed_by_id = {b["id"]: not b["open"] for b in all_blockers}

    def is_actionable(blocker: dict[str, Any]) -> bool:
        deps = blocker.get("depends_on") or []
        return all(closed_by_id.get(dep, False) for dep in deps)

    ordered_open = [b for b in all_blockers if b["open"]]
    ordered_open.sort(
        key=lambda b: (
            phase_order.get(b.get("phase"), 99),
            not is_actionable(b),
            b.get('sequence', 0),
            b.get("id"),
        )
    )
    actionable = [b for b in ordered_open if is_actionable(b)]

    return {
        "ledger_id": ledger.get("ledger_id"),
        "schema_version": ledger.get("schema_version"),
        "phases_covered": sorted(PHASES_COVERED),
        "unmodeled_exit_phases": list(UNMODELED_EXIT_PHASES),
        "suites": suite_rows,
        "open_blockers": ordered_open,
        "actionable_blockers": actionable,
        "open_blocker_count": len(ordered_open),
        "actionable_blocker_count": len(actionable),
        "closed_by_id": closed_by_id,
    }


def release_state_summary(
    ledger: dict[str, Any],
    program: dict[str, Any],
    suites: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return exact release counts without inferring runtime or owner availability."""
    state = resolve_release_state(ledger, program, suites)
    phase_counts: dict[str, int] = {}
    closure_counts: dict[str, int] = {}
    open_criteria = 0
    total_criteria = 0
    suites_under_score_target = 0
    for suite_id, suite_row in state["suites"].items():
        phase = suite_row["release_phase"]
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        total_criteria += suite_row["criteria_total"]
        open_criteria += suite_row["criteria_open"]
        # A suite is under its tier target until a score is actually derived from
        # dimension evidence. No derivation exists yet, so validate_release_ledger
        # accepts only "insufficient_dimension_evidence" and this count equals the
        # suite count -- release_ready stays withheld until the computation lands.
        if suite_row.get("score_status") != "computed":
            suites_under_score_target += 1
        for criterion in suite_row["criteria"]:
            closure = criterion.get("closure")
            if closure and isinstance(closure, dict):
                outcome = closure.get("outcome")
                if isinstance(outcome, str):
                    closure_counts[outcome] = closure_counts.get(outcome, 0) + 1
    return {
        "ledger_id": state["ledger_id"],
        "phases_covered": sorted(PHASES_COVERED),
        "unmodeled_exit_phases": list(UNMODELED_EXIT_PHASES),
        "suites": len(state["suites"]),
        "criteria_total": total_criteria,
        "criteria_open": open_criteria,
        "criteria_closed": total_criteria - open_criteria,
        "open_blockers": state["open_blocker_count"],
        "actionable_blockers": state["actionable_blocker_count"],
        "suites_under_score_target": suites_under_score_target,
        "release_phases": phase_counts,
        "closure_outcomes": closure_counts,
        "has_no_blockers": state["open_blocker_count"] == 0,
        # The v1 exit gate. Zero blockers alone is not the claim: every v1 criterion must
        # be closed and every suite must have reached (or exceeded) its tier score target.
        # Release blockers only cover the obligations they reference, so an open criterion
        # whose obligations no blocker captures must still withhold release_ready.
        "release_ready": (
            state["open_blocker_count"] == 0
            and suites_under_score_target == 0
            and open_criteria == 0
            and not UNMODELED_EXIT_PHASES
        ),
    }
