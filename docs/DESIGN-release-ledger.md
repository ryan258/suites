# Design: Release / Completion Ledger (`0.2.0-alpha` increment)

Status: **implemented, partial release coverage through Phase 5** · Updated October 5, 2026
Goal: make "ready for v1" a machine-checkable claim that cannot be derived from wave counts.

## 1. Problem

Before this increment, the CLI's "next" answer and portfolio summary answered solely from
`resolve_recovery_obligations` + `recovery_program_summary`. That program covers
44 obligations but is not the full v1 blocker set: it has no release-lifecycle axis, no closure
dispositions on the roadmap's terms, and no per-suite release-score computation. The roadmap names a
release/completion ledger that maps every suite criterion, wave follow-up, unique capability, runtime,
owner, contract, evidence artifact, adoption record, recovery score, and final disposition
(ROADMAP.md:175-177), and requires "release status cannot be derived from milestone counts"
(ROADMAP.md:584-585 in the original design baseline). The implementation now lives in
`release_state.py`, `portfolio/release-ledger.json`, and focused release tests.

The existing `project-ledger.json` (`registry.load_ledger`, registry.py:181) is the **project**
portfolio ledger (which projects exist, their dispositions). It is not the release ledger.

## 2. Design principle

The release ledger **subsumes and references**, never forks nor duplicates, the recovery program.
`recovery-program.json` stays authoritative for execution order, target evidence, runtime
environment, owner gates, and receipt contracts. The release ledger adds what the recovery program
lacks and becomes the single source that CLI, Toolbench/API, export, and docs all derive from
(ROADMAP.md:182). This mirrors how AGENTS.md already treats the recovery program as an overlay over
suite manifests (recovery_program.py:1-8): one more overlay, broader scope, same rule.

Two axes stay separate forever (ROADMAP.md:178-179):

- **Release lifecycle** (`alpha`, `beta`, `release-candidate`, `supported`, `deprecated`, `retired`)
- **Recovery depth** (`specified` ... `converged`, from recovery_policy.py:16-25)

They must never be conflated: they are independent axes, but a support promise (`supported`/`beta`/
`release-candidate`) is never automatic -- it is an owner-backed declaration that additionally requires
at least `source_executed` recovery depth (a suite cannot move real support forward on no executed
evidence). "Supported" still never implies "recovered".

## 3. Module and file layout

New module `src/portfolio_suites/release_state.py` (parallel to `recovery_program.py`).

New data file `portfolio/release-ledger.json` (parallel to `portfolio/recovery-program.json`),
declared by the validator, not a runtime-writable store; mutation goes through authored edits plus
the existing txn/provenance machinery if ever written programmatically.

New CLI `suites release` (slots beside `next`, `status`, `wave` in cli.py:695-723): subcommands
`blockers` and `summary`. It becomes the phase-aware source that `next` and `status` read from (see
section 6).

Wired into: `cli._next` (phase-aware "next"), `registry.get_portfolio_summary`
(adds a release-ledger-derived block beside the existing `recovery_program_counts`; the summary
carries a `release_ledger` object consumed by `status` and the `/api/summary` surface).

`server.py /api/recovery` stays recovery-program-backed for now; exposing the release-ledger block
through it (as a superset of the current recovery response) is a deferred follow-up, not part of
this increment.

## 4. release-state schema (prototype)

```jsonc
{
  "ledger_id": "portfolio-release-completion-v1",
  "schema_version": "1.0.0",
  "policy": {
    "release_phases": ["alpha", "beta", "release-candidate", "supported", "deprecated", "retired"],
    "closure_outcomes": ["implemented", "already_covered", "independently_retained", "rejected", "deferred_with_trigger"],
    "score_targets": { "flagship": 9.0, "production": 8.0, "lab": 7.0 },
    "minimum_authentic_uses_for_adoption": 3,
    "silent_deletion": "forbidden",
    "blanket_deferral": "forbidden",
    "resolved_without_evidence_or_owner": "forbidden",
    "phases_covered": ["0", "1", "2", "3", "4", "5"]
  },
  "suites": {
    "brand-publishing": {
      "release_phase": "alpha",
      "release_phase_owner": "ryan",
      "score": null,
      "score_status": "insufficient_dimension_evidence",
      "criteria": [
        {
          "id": "brand-publishing.v1.criterion.1",
          "name": "authentic producer runtime",
          "dimension_weights": { "functional_parity": 35, "repeated_real_use": 20, "runtime_convergence": 15, "reproducibility": 10, "failure_and_recovery": 10, "provenance_and_owner_control": 5, "reporting_accuracy": 5 },
          "obligation_refs": [{ "id": "brand-publishing/B1" }, { "id": "brand-publishing/B4" }],
          "evidence_refs": [],
          "status": "open",
          "closure": null
        }
      ]
    }
  },
  "release_blockers": [
    {
      "id": "brand-publishing.v1.criterion.1",
      "phase": "0",
      "depends_on": ["phase-boundary.1-contract-freeze"],
      "obligation_refs": ["brand-publishing/B1"],
      "kind": "runtime",
      "receipt_contract": "portfolio-runtime-parity-v1",
      "owner": null,
      "scope": "phase1"
    }
  ],
  "global_blockers": [
    {
      "id": "phase1.contract-state-freeze",
      "phase": "1",
      "name": "six v1 contracts and persistent state formats are frozen before authentic runtime integration",
      "depends_on": [],
      "closure": null
    },
    {
      "id": "phase1.stable-surface",
      "phase": "1",
      "name": "stable CLI/API control-plane surface is frozen",
      "depends_on": [],
      "closure": {
        "outcome": "implemented",
        "owner": "ryan",
        "evidence_ref": "<suite>/evidence/<file>",
        "rationale": "boundary freeze recorded",
        "frozen_boundaries": {
          "contracts_schemas": [{ "path": "portfolio/contract-schemas-v1.json", "sha256": "<64-hex>" }],
          "persistent_state_formats": [{ "path": "src/portfolio_suites/state_formats_v1.py", "sha256": "<64-hex>" }]
        }
      }
    }
  ],
  "snapshot_at": "2026-08-28T00:00:00Z"
}
```

The schema shown is the **authored** ledger shape. `phases_covered` is the reviewed policy that
truthfully identifies this as a Phase 0–5 partial ledger; blocker `phase` values are restricted to it
and `phase_order` (next-queue ordering) is derived from it. Two blocker kinds, one openness rule:

The example is an abbreviated shape, not a loadable ledger or closure receipt. The
current exact frozen surface/path sets live in `GLOBAL_BLOCKER_SPECS`; the real ledger
contains all registered suites and obligations. Every governed recovery obligation
must appear in exactly one runtime queue entry, with its original predecessor
dependencies and the Phase 1 contract/state gate. Runtime phases follow the roadmap's
flagship/production/lab order; adoption is Phase 5. Recovery-program sequence breaks
ties within a phase. Requirements are projected from the owning program, not copied
into a second editable runtime specification.

`unmodeled_exit_phases` explicitly lists the later candidate, distribution, and
stabilization gates. An empty partial queue cannot assert release readiness. Dimension
scoring and those later executable closure gates are still pending implementation and
authentic evidence. `release blockers --json`, export, and the Toolbench use the same
resolver. `release candidate` and `doctor` provide the bounded preparatory checks
described in [platform operations](PLATFORM-OPERATIONS.md).

The format freeze binds validators and compatibility policy instead of live project
values, so saving an attention record does not invalidate a format boundary. The
stable-surface freeze includes the server and catalog interfaces, recovery commands,
candidate inspection, and diagnostics. No freeze closure was recorded in this increment.

- A **release blocker** owns `obligation_refs`; it is open while any referenced obligation is not
  `discharged` and closes automatically once all its obligations discharge.
- A **global blocker** (phase-boundary process gate, e.g. the contract freeze) owns no obligation. It
  closes **only** through an evidence- and owner-bound `closure` record — a bare boolean is rejected.
  The closure must carry a non-empty `owner`, an `evidence_ref` resolving to a real JSON receipt on
  disk, and a `frozen_boundaries` object mapping each frozen surface to `{path, sha256}` digest
  bindings. The validator recomputes each sha256 host-side and rejects stale or escaping bindings,
  so dependent work can never be authorized against a boundary that was not actually frozen. Until
  that record is authored the global blocker reports `open: true` (fail-closed).

A blocker is **actionable** only when every blocker in its `depends_on` is closed. Both blocker kinds
route through the same openness rule in `resolve_release_state`.

## 5. Resolution engine (`release_state.py`)

`resolve_release_state(ledger, program, suites)`:

1. **Validate the ledger** (fail closed, mirrors `validate_recovery_program`).
   Negative checks the roadmap demands (ROADMAP.md:183-184), plus exhaustive coverage:
   - the ledger's `suites` set must equal the registry exactly (a ledger that omits a
     registered suite, or lists an unknown one, could report release_ready by dropping the
     weakest members); every criterion must carry a non-empty `obligation_refs` list of objects,
     and the union of all criterion references must cover every governed recovery obligation
     (an obligation no criterion owns is invisible to the release gates);
   - impossible promotions (a `supported` suite with no supportable depth) and ownerless
     support promises (a `supported`/`beta`/`release-candidate` phase with no `release_phase_owner`);
   - self-comparison parity (parity evidence compared against itself where parity must be donor-vs-destination);
   - stale receipts (receipt content-address does not match the byte-addressed artifact);
   - missing provenance (an evidence ref that does not resolve inside its suite);
   - incomplete untracked fingerprints (the "complete candidate" fingerprint); and
   - status copied from the wave objective (opening/closing a release criterion with prose instead of evidence).

2. **Provenance-first closure.** Every `closure` must be closed as one of the policy outcomes
   (`implemented`, `already_covered`, `independently_retained`, `rejected`, `deferred_with_trigger`)
   carrying an owner and, for `implemented`, a retained evidence ref. The evidence ref is not proof
   by being a confined string: it must resolve through `resolve_declared_evidence_path` to the
   canonical `<suite>/evidence/<file>` shape (no traversal, no symlink escape), exist on disk, and
   parse as a JSON object receipt. Any other close is rejected.
   `rejected`/`deferred_with_trigger` require an owner and a dated rationale; `deferred_with_trigger`
   requires a structured `resume_trigger` (borrow the resolution-contract pattern,
   receipts.py `_resolution_receipt_errors`).

3. **Subsume the recovery program.** Call `resolve_recovery_obligations(program, suites)` and project
   each recovery obligation's `effective_state` onto `criteria[].obligation_refs`. A criterion is
   schedule-closed only when every referenced obligation is `discharged`. The recovery program stays
   the authority for obligation-level truth; the ledger only aggregates.

4. **Score computation.** Per suite, compute the dimension-weighted recovery score from closed
   criteria evidence exactly as the adopted 9/10 rubric describes. Because existing receipts do not
   yet carry per-dimension scores, `insufficient_dimension_evidence` is the only valid score_status
   today, and any authored numeric `score` is **rejected by validation** -- there is no trusted number
   in the system (matching registry.py:723-724 today). This preserves honesty: no numeric score is
   manufactured from milestone counts (registry.py:720-723 explains why), and an operator cannot type
   a compliant-looking number into the ledger. The resolver therefore counts a suite as under its
   tier target until `score_status` is `computed`, so `release_ready` stays withheld until
   dimension-bearing receipts exist and the computation lands.

5. **Phase-aware "next".** Produce an ordered release-blocker queue:
   - Phase 0 blockers first (ledger completeness, contract freeze, exact-candidate identity);
   - then dependency-ordained blockers (those whose `depends_on` are all closed);
   - then runtime recovery obligations in the recovery program's priority order.
   `cli._next` switches to this queue. B1 stays behind `phase1.contract-state-freeze` until the frozen
   boundary is recorded, so authentic runtime evidence is not collected against a moving contract
   (ROADMAP.md:203-205, 599).

## 6. CLI surface

Decision (Q1): **add a new `suites release` verb**, and make it the phase-aware source that
`next` and `status` read from. Rationale: the roadmap freezes the stable CLI surface at the end of
Phase 0 (item 4, ROADMAP.md:230-239), so introducing one narrow, well-scoped verb now and freezing
it later is the intended trajectory. A dedicated `release` surface also gives the "list every
remaining blocker / prove zero blockers" exit gate (ROADMAP.md:186-187) a first-class,
README-documented home instead of burying it inside `next` prose output.

`suites release blockers` — the complete remaining-work list: every open release blocker with
phase, id, actionable/held status, and the obligations it still owes (a held blocker names its
blocker; an actionable one names a path), **plus** the open-criteria and suites-under-score-target
counts printed unconditionally. An empty explicit queue does **not** claim completion: the command
reports the remaining criteria and score deficits and exits 0 only when `release_ready` is true,
mirroring `release summary` so an empty explicit queue can never read as a satisfied v1 claim. The
exit here is the `release_ready` conjunction — no open blocker **and** every criterion closed **and**
every suite at tier score target — so an open criterion whose obligations no explicit blocker
captures still withholds a clean exit.
`suites release summary` — counts by release phase and by closure outcome, plus the v1 exit gate.
The gate is not "zero blockers" alone: it exits 0 only when no release blocker is open **and** every
suite has reached its tier score target, so a portfolio with all gates closed but unscored suites
still reports `Release ready: no`.
`suites next` — re-uses the release-blocker queue, phase-aware. When the queue reports "superseded"
for an obligation whose boundary is frozen, it must still print the frozen-boundary gate and why it
is not yet dischargeable, rather than silently skipping to a later obligation.
`suites status` — the release summary is folded into the existing status output as the headline so
an operator reading `status` sees release truth, not milestone counts.

## 7. Test plan (Level 1/2 targeted, not full-suite discover)

New `tests/test_release_state.py` + `tests/test_release_cli.py`:
- `test_impossible_promotion` — `supported` at an unsupported depth is refused.
- `test_closure_requires_owner_and_evidence` — `implemented` without evidence ref fails closed.
- `test_banned_closures` — silent deletion/blanket deferral/resolved-without-owner all rejected.
- `test_score_stays_null_without_dimension_evidence` — no manufactured numeric score.
- `test_next_phase_aware` (fits `test_recovery_cli.py`) — the updated `_next` reports the
  release blocker queue, holds B1 behind the contract freeze, and still renders the
  dependency-ready queue when no blocker is open.
- Fix-gated regression tests: a release blocker with no `obligation_refs` is rejected
  (never silently closed), an authored numeric score is rejected until the dimension-derived
  computation exists, a blocker id shared across the release/global lists is refused, a
  criterion with empty/string-form obligation refs is refused, and a ledger whose suite set
  diverges from the registry or that fails to cover a governed obligation is refused.

Out of the original plan list, `test_parity_not_self_comparison`, `test_stale_receipt`, and
`test_status_not_from_objective_prose` were not implemented: the ledger schema neither defines
per-dimension parity criteria nor content-address/objective-prose fields for them to exercise, so
they would test fields the v1 ledger intentionally does not model. File them when those fields land
(per-dimension receipt scoring is explicitly §9 out-of-scope).

Run per AGENTS.md: targeted classes only (`python3 -m unittest tests.test_release_state...`),
never `discover` except at a genuine milestone.

## 8. Sequencing guard

This is a **precondition for B1**, not a blocker on all runtime work. Existing authentic execution
(O1, O4) and any Phase-0 runtime probes may proceed. The rule is narrow: B1-style parity evidence is
not release-usable until the `phase1.contract-state-freeze` global blocker carries a valid closure
record — owner, retained evidence receipt, and `frozen_boundaries` digest bindings that recompute
host-side to the current bytes (ROADMAP.md:205). Closing that gate is a real action, not a boolean
edit: the ledger rejects any bare flag, and B1's `depends_on` keeps it held (never "next") until the
frozen record lands. The validator enforces this, so the CLI stop handing out B1 as "the next thing"
before the boundary is genuinely frozen.

## Review repairs: evidence and interface boundaries

Runtime blocker dependencies must be explicit string lists, including when empty;
an absent or null list is invalid. Required freeze and predecessor edges remain
mandatory and cannot disappear through an omitted field.

Support-promise phases require validated retained execution evidence at the declared
recovery depth or above. Completed waves use the registry's receipt validation and
ownership checks; discharged lifecycle obligations use the recovery-program resolver.
An authored `recovery_depth` string cannot substitute for those receipts.

Retirement receipts require `supporting_evidence_sha256`, an exact mapping from every
`supporting_evidence_refs` path to its host-computed SHA-256. This mapping is part of
the canonical approval payload, alongside suite, donor, decision, disposition, and
sorted supporting references. Each supporting artifact must also pass its owning
wave or discharged lifecycle receipt validator and remain unchanged across validation.
Existing path-only approvals are insufficient under this boundary: preserve them as
history and obtain a new out-of-band approval for the content-bound payload. The
control plane never issues or silently upgrades an approval.

The overview next-step card reads `/api/catalog/release`, using the same ordered
actionable blockers as the CLI. A failed release read displays unavailable state;
it never falls back to a wave ranking or treats an empty partial queue as readiness.

Malformed closure and retirement fields return validation errors, including arrays
or objects where an outcome, operation, decision, or evidence-reference string belongs.
Focused regression coverage is in `tests/test_review_regressions.py` and its small
Node browser-logic companion. No browser, assistive-technology, or personal-use
acceptance is implied by those checks.

## 9. Out of scope (deliberately)

- The B1 authentic producer→external-consumer runtime path itself (its own follow-up increment).
- Per-dimension receipt scoring (requires new receipt contracts; only the `null`-until-then status here).
- Any withdrawal, freeze, or contract re-audit implementation (that is roadmap item 2, Phase 1).
