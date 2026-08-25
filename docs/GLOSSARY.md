# Governance Glossary — Concept → Enforcing Function

One page mapping each governance concept to the code that actually enforces it. If a concept's
behavior seems wrong, fix it here; if the table and the code disagree, the code wins and this
table is stale.

| Concept | Meaning | Enforced by |
|---|---|---|
| Recovery claim (`kind`, `level`) | What a wave asserts it demonstrated. | `registry.validate_registry` (claim-shape rules); `receipts.evidence_errors` (dispatch to receipt validators) |
| Promotion ladder | 8 rungs from `specified` to `converged`. | `recovery_policy.RECOVERY_PROMOTION_LEVELS`; order checked against `portfolio/recovery-standard.json` in `validate_registry` |
| Executed rungs | Levels asserting donor code ran; restricted per claim kind. | `recovery_policy.EXECUTED_PROMOTION_LEVELS`, `EXECUTED_LEVELS_BY_KIND` (+ `validate_registry` kind guard) |
| Prototype ≠ recovered | A finished analysis milestone is not a recovery. | `recovery_policy.RECOVERY_ENFORCEMENT["prototype_never_counts_as_recovered"]` + `validate_registry` runtime/prototype checks |
| Evidence basis | Named fields/markers a receipt must really contain. | `receipts._analysis_evidence_errors` |
| Receipt spec | Per-wave assertions a JSON receipt must satisfy. | `receipts.ANALYSIS_RECEIPT_SPECS`, resolved by `receipts._lookup_receipt_spec`, applied by `receipts._analysis_receipt_semantic_errors` |
| Receipt contract (`*-v1`) | Versioned validator for runtime/adoption/convergence/resolution receipts. | `recovery_policy.RECEIPT_CONTRACT_FOR_KIND`, `RECOVERY_RECEIPT_CONTRACTS`; validators `receipts._runtime_parity_receipt_errors`, `_portfolio_runtime_receipt_errors`, `_adoption_receipt_errors`, `_convergence_receipt_errors`, `_resolution_receipt_errors` |
| Runtime parity evidence vocabulary | Closed set of proofs a `parity_verified` claim must declare. | `recovery_policy.RUNTIME_PARITY_EVIDENCE` (+ `validate_registry` basis check) |
| Evidence ineligibility | Why `--record` may not write a receipt at all (distinct from gate failure). | `receipts.evidence_ineligibility_reason` |
| Resolution outcomes | Typed endings for a capability (`ported`, `retained_independent`, …). | `recovery_policy.RECOVERY_RESOLUTION_OUTCOMES`; receipts checked by `_resolution_receipt_errors` |
| Recovery standard / 9.0 score | Weighted rubric; score stays `None` until per-dimension evidence exists. | `recovery_policy.RECOVERY_DIMENSIONS`, `RECOVERY_TIERS` vs `portfolio/recovery-standard.json` via `registry.load_recovery_standard` |
| Cross-suite contracts | 6 versioned artifact schemas. | `contracts.CONTRACTS`, `contracts.validate_contract`, published schemas in `contracts/*.schema.json` |
| Drift & baselines | Tamper-evident working-tree tracking of donor repos. | `registry.check_project_git_drift`, `pending_snapshots`, `fingerprint_baselines` |
| Wave recording | Writing evidence only when a claim can verify it. | `waves.WaveRunner`, `_record_evidence` (calls `receipts.evidence_errors`) |
| Owner approvals | Fail-closed authority for mutating operator actions. | `approvals.py` (store outside this repo, consumed once) |
| Donor isolation | Donor code executes in a subprocess that cannot reach the control plane's authority. | `adapters.common.donor_env` (env allowlist, credential-shaped names refused); `adapters/donor_*_probe.py` invoked via `subprocess.run` |

## Module map (post-split)

- `recovery_policy.py` — adopted policy data, no behavior.
- `receipts.py` — retained-receipt verification (the "did the receipt earn the claim" layer).
- `registry.py` — manifests/ledger loading, drift, orchestration of full validation.
