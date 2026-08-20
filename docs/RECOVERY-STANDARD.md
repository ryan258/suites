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
- `source_verified`: authentic source behavior has been executed and fingerprinted.
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

## Resolution is success when it is explicit

Every material capability ultimately receives one outcome: `ported`, `already_covered`,
`retained_independent`, `rejected`, `historical_only`, or `deferred_with_trigger`. A deferred item
must name the observable trigger that would justify resuming work.

Wave counts remain useful scheduling metrics, but they are not the portfolio recovery score.
