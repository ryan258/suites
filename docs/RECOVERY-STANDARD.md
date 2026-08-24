# Portfolio Recovery Standard

## Adopted target

The portfolio targets **9/10 recovery of valuable functionality**, not 100% reproduction of every
historical repository. The governing principle is:

> Recover or explicitly resolve every valuable capability; do not reproduce every historical
> repository.

The machine-readable authority is
[`portfolio/recovery-standard.json`](../portfolio/recovery-standard.json). Registry validation fails
if its dimensions, weights, tiers, promotion levels, resolution outcomes, or enforcement rules drift.
For a runtime parity claim, validation also requires an explicitly versioned receipt contract and
inspects the retained receipt through that contract. The Accessibility A2 contract verifies
authentic donor and destination stages, representative inputs, full gates, source/dependency
fingerprints, and fail-closed rerun behavior without imposing accessibility-specific stages on
future suite receipt contracts.

## What counts

A wave milestone and a recovered runtime are different claims:

- `specified`: intended work with an acceptance boundary.
- `prototype`: suite-owned fixture or reference logic proves only the exercised concept.
- `reviewed_historical_analysis`: a hand-authored decision document about real donor behavior is
  retained and its required structure is checked. No donor code was read or run.
- `source_inspected`: authentic donor source, retained artifacts, or fingerprints were read and
  parsed. Nothing donor-side was executed.
- `source_executed`: authentic donor code was invoked and its behavior fingerprinted. This rung
  and every rung above it are `runtime` claims only. An analysis receipt is validated for what
  it *contains*, and no field in one can establish an argv, an exit code, or a source
  fingerprint proving the donor ran — so an analysis claim is refused here rather than allowed
  to buy the ladder's strongest statement with a `real_runtime: true` boolean. `source_inspected`
  is the highest analysis rung; an analysis wave whose runner really does execute the donor
  earns this one by re-declaring as `runtime` behind a `portfolio-runtime-source-v1` receipt.
- `parity_verified`: authentic source and canonical destination behavior match on accepted output
  and failure cases.
- `adopted`: the canonical path produced accepted work in at least three authentic uses across
  distinct inputs or days.
- `converged`: one canonical state owner and runtime remain; duplicate writers are frozen or
  retired with Ryan's approval.

An environment that cannot execute a gate is `unverifiable_environment`: it is neither a pass nor
evidence that the product failed. A retained successful receipt remains historical evidence, while
the current run remains unverified.

Every completed wave must carry a `recovery_claim` naming its claim kind, promotion level, whether
it exercised a real runtime, and the evidence basis. Analysis can be a completed milestone without
being counted as recovered functionality.

Milestone status and promotion level are two independent axes and must be reported as two. A wave
is `specified`, in progress, or analysis-complete on the first; it sits at one of the levels above
on the second. A completed analysis wave may hold `prototype` — finishing scheduled work is not a
claim about what that work demonstrated — but no report may present the first axis alone, because
"43/43 complete" and "4 of those exercised only a fixture" are both true and only one of them is
reassuring. Only `runtime` claims are barred from completing at `prototype`.

The three levels between `prototype` and `parity_verified` exist because one name for all of them
let a runner that reads a Markdown document, a runner that parses donor source, and a runner that
imports and executes donor modules all report the same word.

Validation is not reserved for completed waves. Registry validation checks every declared claim and
re-reads its retained receipt against the claim's declared evidence basis and, where one exists, its
receipt spec. Only the promotion rules — that a completed wave cannot claim a
planning level, that a completed *runtime* wave cannot claim a prototype level, and that completed
evidence must exist — are conditional on completion. A completed *analysis* wave may hold
`prototype`, as stated above; the rule is not "no completed wave may claim prototype". A prototype receipt
that later becomes malformed, hand-edited, or self-contradictory therefore fails the canonical gate
rather than coexisting with a green report.

A receipt's status names what its gate performed, not what its wave intends to achieve. Where a
gate stopped short of the wave's boundary, the receipt states the boundary as an explicit negative
field — `external_runtime_invoked`, `donor_read`, `duplicate_decisions_closed`,
`donor_legality_checker_invoked`, `whole_match_replayed` set to false — and the receipt validator
requires those fields rather than accepting a status word like "ported" or "closed" that the gate
never established. Silence about a boundary reads as having crossed it. A gate that
reads donor files reports reading them; it does not report discovery, unification, parity,
consolidation, or retirement it did not carry out. Where the performed work falls short of the
wave's acceptance boundary, the receipt says so in its own fields — for example
`independent_resimulation_verified`, `canonical_slice_implemented`, `minimized_permissions_verified`,
or `retirement_performed` set to false — and the wave's `runtime_followup` names the work that would
close the gap.

## The 9/10 rubric

| Dimension | Weight | Required evidence |
|---|---:|---|
| Functional parity | 35% | Authentic source and destination execution; accepted output and failure parity |
| Repeated real use | 20% | At least three accepted uses across distinct inputs or days |
| Runtime convergence | 15% | One canonical state owner/runtime; duplicate writers closed with approval |
| Reproducibility | 10% | Clean-environment command plus source, dependency, input, and output fingerprints |
| Failure and recovery | 10% | Interruption, retry, rollback, partial-state, and resume evidence |
| Provenance and owner control | 5% | Traceable source, authorship, approvals, side effects, and retirement decisions |
| Reporting accuracy | 5% | CLI, API, dashboard, manifests, evidence, and docs agree |

## Portfolio targets

- **9/10 flagships:** Accessibility, Operator OS, Brand + Publishing.
- **8/10 production systems:** Production House, Discovery + Decision.
- **7/10 labs until use earns more investment:** Model Behavior Lab, Agent Reliability, Game
  Design.

This tiering is intentional. Three deeply used systems and five constrained labs are healthier than
eight nominally complete suites that do not carry real work.

## Promotion gate

A runtime wave cannot become `parity_verified` unless its evidence shows:

1. authentic source invocation;
2. authentic canonical destination invocation;
3. representative inputs with sensitive state isolated;
4. output comparison;
5. failure comparison;
6. recovery or resumability behavior;
7. source and dependency fingerprints;
8. a reproducible command; and
9. human acceptance where judgment is involved.

It cannot become `adopted` until three authentic uses are accepted. It cannot become `converged`
until duplicate state writers are closed and Ryan explicitly approves any freeze, archival, or
deletion.

## Outside-World Sensitivity Standard (Content Asserted vs. Content Recorded)

A core invariant governs wave promotion: **What change in the outside world turns the receipt red?**

If modifying donor source files leaves a gate green, the gate is verifying only its own internal comparator rather than the donor. To enforce honest accounting, evidence receipts fall into three tiers:

1. **Tier 1: Content Asserted (Gold Standard)**
   - The gate parses or executes authentic donor/destination source and asserts against specific extracted values, finding distributions, or AST structures.
   - Modifying rule logic, export definitions, or schemas in the donor repository causes the receipt gate to fail immediately.
   - Exemplars: `A2` (executes donor rule via subprocess against live inputs), `A3` (parses real manifest scopes and permissions), and deepened `B1` (parses live `developer_exports.py` AST and `living-brand-system.md` specifications).
   - *Seam vs. Payload Precision (B1)*: Deepened `B1` is Tier 1 for the export seam and contract structure (verifying functions, artifact filenames, token types, and audience categories from donor source), while the specific `BrandPackage` payload values remain adapter-authored literals until real Brand Maker runtime compilation is executed in `runtime_followup`.
   - Machine enforcement: Enforced via `source_derived_assertions` in `_analysis_receipt_semantic_errors`.

2. **Tier 1b: Behavioral Assertion**
   - The gate executes authentic destination code against live donor content and asserts a *property of the pipeline* rather than a pinned value — so editing the donor's content correctly leaves the gate green, while breaking the destination turns it red.
   - Exemplar: `O1` (imports PKos's real `Workspace` and `normalize`, then asserts `checksum_file(cas_object) == checksum_file(donor) == record.sha256` byte for byte, and that normalization produced items and chunks with zero failures).
   - Do not "upgrade" a Tier 1b gate by pinning donor content: pinning `dotfiles/AGENTS.md` would break `O1` every time Ryan edits his own dotfiles, and would verify strictly less than the round-trip property already does.
   - Machine enforcement: `operational_errors` must be empty in the recorded receipt, so a swallowed exception cannot present as a clean pass.

3. **Tier 2: Content Recorded / Count-Gated**
   - The gate captures genuine git fingerprints and checks minimum item or byte counts, but does not assert on internal structure.
   - Examples: `O2` (records ryos/core bytes with count check), `B2` (extracts phase IDs with count check).

Every promoted wave must satisfy the Outside-World Sensitivity Test by asserting directly against donor-extracted structures.

## Deferred Runtime Work Must Be Named

A wave completed as an `analysis` claim has, by definition, left its runtime work undone. Unless
that work is written down, it is not deferred — it is lost: the wave reads as finished, and nothing
in the ledger remembers what it did not do.

Every wave with `status: complete` and `recovery_claim.kind: analysis` must therefore carry a
non-empty `runtime_followup` naming the runtime execution still owed. `A4` was originally promoted
without one; the rule below is what would have caught it, and every completed analysis wave now
carries a followup.

Machine enforcement: `validate_registry` refuses any completed analysis wave whose
`runtime_followup` is missing or blank, and `tests/test_registry.py` asserts the same invariant
across the whole registry.

## Resolution is success when it is explicit

Every material capability ultimately receives one outcome: `ported`, `already_covered`,
`retained_independent`, `rejected`, `historical_only`, or `deferred_with_trigger`. A deferred item
must name the observable trigger that would justify resuming work.

Wave counts remain useful scheduling metrics, but they are not the portfolio recovery score.
