# Migration Program

Tranche 0's control-plane foundation is complete, eight migration wave milestones are verified (one
runtime recovery, seven analysis milestones), and the remaining 35 waves carry source-backed
prototype receipts. Every wave gate reads donor content before making a claim. Prototype artifacts
prove only what their runner exercised, not completed migrations. Real ports, adoption, retirement,
and single-runtime convergence follow the [9/10 recovery standard](RECOVERY-STANDARD.md) and the
[roadmap](ROADMAP.md).

## Destination rule

`/Users/ryanjohnson/Projects/suites` is the new portfolio home for promises, contracts, migration
evidence, adapters, packs, and—after parity—recreated implementations. Original repositories remain
the recoverable source during migration. Working code is not bulk-copied simply to make the folder
look complete: that would duplicate bugs, local state, histories, credentials, caches, and unclear
ownership while providing no behavioral proof.

When an anchor is ready to be physically rehomed, its preserved Git history and clean source state
must be reconciled first. Until then, the suite manifest names the canonical external anchor and the
suite directory owns the target contract and evidence. This is a temporary migration topology, not
the final visual organization.

## Definition of done

A suite is complete when:

1. its user promise can be executed end to end through one documented entry path;
2. canonical state and every cross-suite artifact use owned, versioned contracts;
3. source provenance, versions, approvals, operational failures, and recovery remain visible;
4. duplicate behavior has parity evidence and only one canonical runtime remains;
5. automated, AI-assisted, manual, and unknown evidence are not conflated;
6. deterministic and accessibility gates appropriate to the product pass;
7. publication/deployment/credential and collaborator ownership boundaries are preserved; and
8. the original source can be recovered until Ryan explicitly approves archival or deletion.

A scaffold, README, build, or passing narrow unit test is not completion.

## Tranche 0 — Foundation (complete)

- Eight suite promises, anchors, member relationships, contracts, criteria, and waves.
- Seventy top-level dispositions and 35 nested Git-marker classifications.
- Six cross-suite JSON Schemas and dependency-free runtime validation.
- Live-tree and source-fingerprint verifier.
- Portfolio bible, local skill candidate, provenance boundary, and unit gates.
- Accessibility A1 parity decision and 20 future migration fixtures.

## Tranche 1 — Prove the three active bets

Seven waves in this tranche are verified (plus `A1` from Tranche 0, bringing the portfolio total to
eight): one runtime recovery (`A2`) and seven analysis milestones (`A1`, `A3`, `A4`, `O1`, `O2`,
`B1`, `B2`). Every verified analysis milestone still carries a `runtime_followup` obligation
recorded in its wave manifest; the milestone is not that obligation discharged.

### Accessibility (4/6 verified)

- **A1 — done in Tranche 0 (analysis):** WCAG Auditor to Ally rule, crawl, finding, and deliverable
  parity matrix.
- **A2 — done (runtime recovery):** the narrow WCAG 3.3.1 ARIA error-association port is verified
  against the real `allys-tools` runtime.
- **A3 — done (analysis):** the three keyboard overlays are reconciled; no archive action taken.
- **A4 — done (analysis):** 20 candidate WCAG Auditor rules evaluated against live donor rule ASTs,
  zero false positives on compliant markup. Porting them into the TypeScript runtime is the
  follow-up.
- **A5 / A6 remain:** finding round-trip through `a11y-kitchen`, then overlay consolidation and the
  host-permission narrowing that precedes any owner-approved donor freeze.

### Operator OS (2/6 verified)

- **O1 — done (analysis):** an authored source is captured into real PKos CAS, normalized into
  SQLite, and projected into a fenced Observer note that refuses re-ingestion.
- **O2 — done (analysis):** Ryos/master-plan inventory compared against current dotfiles/Observer
  state; the assigned ports are follow-up work.
- **O3 remains:** make one JARVIS action use a canonical service with preview, approval, receipt,
  and recovery against real side effects. `O4`–`O6` scale the intake stream, execute the Ryos ports,
  and generalize the JARVIS lifecycle.

### Brand + Publishing (2/6 verified)

- **B1 — done (analysis):** an approved `BrandPackage` is exported from live `brand-maker-spec`
  sources and consumed in a `cyborg` dry run with version pinning and mutation protection.
- **B2 — done (analysis):** Brand Workshop's nine low-typing phases are mapped onto Brand Maker
  workspace state and gates; implementing those gates is the follow-up.
- **B3 remains:** prove SourceRecord → governed draft → VCC review → publishing receipt through the
  real VCC path. `B4`–`B6` cross a repository seam, migrate the intake state machine, and replace
  the simulated approval gate with real human signoff.

## Tranche 2 — Prove the next systems

- **P1/P2:** fingerprint one Groundwire episode, then execute it as a ProductionJob through the
  formatter without parallel canonical state.
- **M1/M2:** normalize one ethics scenario into ExperimentRun, then extract the ethics app as a pack
  over the comparator kernel. *Current state:* `M1` normalizes a recorded donor result and proves
  field parity; `M2` measures the duplication a shared kernel would replace and states that no
  canonical slice exists yet.
- **D1/D2:** map SIF stages to Forge and port one bounded stage with consent, budget, failure, resume,
  canonical Markdown, and rebuild evidence. *Current state:* the mapping is drawn from real phase
  nodes and budgets, and the red-team stage is carried as a retained artifact, not a live run.

## Tranche 3 — Internal labs and real reference packs

- **R1/R2:** define and run adversarial harness fixtures for confinement, malformed output, retries,
  budgets, rollback, and reviewer evidence. *Current state:* fixtures derive from the donor's own
  declared action policy, and gate coverage is read from harness source; the fixtures have not been
  executed inside the three harness runtimes.
- **G1/G2:** fingerprint Tucked in Terrors and prove seeded statistical/artifact parity as a
  Storyweaver pack. *Current state:* `G1` fingerprints the recorded run sample; `G2` projects it
  into the pack vocabulary and deliberately reports no parity number, since nothing was generated
  independently to compare against.

## Retirement procedure

For every donor or duplicate:

1. record branch, HEAD, remote, working tree, nested checkouts, and data/secret boundaries;
2. identify unique behavior and its current tests/artifacts;
3. create target fixtures and an explicit port/reject decision;
4. implement the smallest end-to-end slice;
5. verify target behavior and compare source/target outputs;
6. document migration and recovery;
7. freeze the donor only after parity; and
8. archive/delete only with explicit current owner authorization.

No suite wave grants staging, commit, push, deployment, publication, credential, or destructive
cleanup authority. A gate may record that a retirement is *proposed* and what remains outstanding;
it may never record one as performed.

## Verification commands

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Source-specific commands belong in each wave's evidence record because dependencies, runtimes, and
manual gates differ.
