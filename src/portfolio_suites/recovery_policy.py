"""Adopted recovery-policy vocabulary shared by receipt verification and registry validation."""

from __future__ import annotations


RECOVERY_DIMENSIONS = {
    "functional_parity": 35,
    "repeated_real_use": 20,
    "runtime_convergence": 15,
    "reproducibility": 10,
    "failure_and_recovery": 10,
    "provenance_and_owner_control": 5,
    "reporting_accuracy": 5,
}
# Retired `source_verified`: one name covered historical review, source inspection, and execution.
RECOVERY_PROMOTION_LEVELS = [
    "specified",
    "prototype",
    "reviewed_historical_analysis",
    "source_inspected",
    "source_executed",
    "parity_verified",
    "adopted",
    "converged",
]
# Levels at which a claim asserts that donor code actually ran. `source_executed` invokes the
# donor; `parity_verified` and above additionally compare it against the destination.
EXECUTED_PROMOTION_LEVELS = frozenset({"source_executed", "parity_verified", "adopted", "converged"})
RECOVERY_RESOLUTION_OUTCOMES = [
    "ported", "already_covered", "retained_independent", "rejected",
    "historical_only", "deferred_with_trigger",
]
RECOVERY_CLAIM_KINDS = ["analysis", "runtime", "adoption", "convergence", "resolution"]
# Promotion levels whose names assert that a real runtime was executed and compared.
# Reaching one requires runtime evidence, so a claim that declares no runtime cannot hold it.
RUNTIME_PROMOTION_LEVELS = frozenset({"parity_verified", "adopted", "converged"})
# Which claim kinds may occupy an executed promotion level at all. `runtime` earns the whole
# ladder by retaining a receipt that proves the invocation; `adoption` and `convergence` are
# the terminal rungs their own contracts describe. Every other kind -- `analysis` and
# `resolution` -- is validated against a receipt specification that describes what a receipt
# *contains*, which can never establish an argv, an exit status, or a donor fingerprint.
EXECUTED_LEVELS_BY_KIND = {
    "runtime": EXECUTED_PROMOTION_LEVELS,
    "adoption": frozenset({"adopted"}),
    "convergence": frozenset({"converged"}),
}
RECOVERY_ENFORCEMENT = {
    "completed_wave_requires_recovery_claim": True,
    "prototype_never_counts_as_recovered": True,
    "environment_blocker_is_neither_pass_nor_product_failure": True,
    "minimum_authentic_uses_for_adoption": 3,
    "minimum_consumers_for_shared_component": 2,
    "retirement_requires_owner_approval": True,
}
RECOVERY_TIERS = {
    "flagship": {
        "target_score": 9.0,
        "suites": ["accessibility", "operator-os", "brand-publishing"],
    },
    "production": {
        "target_score": 8.0,
        "suites": ["production-house", "discovery-decision"],
    },
    "lab": {
        "target_score": 7.0,
        "suites": ["model-behavior-lab", "agent-reliability", "game-design"],
    },
}
RUNTIME_PARITY_EVIDENCE = {
    "source_invocation",
    "destination_invocation",
    "representative_inputs",
    "output_parity",
    "failure_parity",
    "recovery_behavior",
    "source_fingerprints",
    "dependency_fingerprints",
    "reproducible_commands",
}
RECOVERY_RECEIPT_CONTRACTS = {
    "accessibility-wcag-331-v1",
    "portfolio-runtime-source-v1",
    "portfolio-runtime-parity-v1",
    "portfolio-adoption-v1",
    "portfolio-convergence-v1",
    "portfolio-resolution-v1",
}
RECEIPT_CONTRACT_FOR_KIND = {
    "adoption": "portfolio-adoption-v1",
    "convergence": "portfolio-convergence-v1",
    "resolution": "portfolio-resolution-v1",
}
