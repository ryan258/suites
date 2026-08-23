# Migration Program

Tranche 0's control-plane foundation is complete and all 43 migration wave milestones are verified:
one runtime recovery (`A2`) and 42 analysis milestones. Every wave gate reads donor content before
making a claim, and each analysis milestone carries an undischarged `runtime_followup` obligation in
its wave manifest. A verified milestone proves what its runner exercised, not a completed migration.
Real ports, adoption, retirement, and single-runtime convergence follow the
[9/10 recovery standard](RECOVERY-STANDARD.md) and the [roadmap](ROADMAP.md); the portfolio reads
0 adopted and 0 converged.

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

## Tranche 1 — Prove the three active bets (waves verified)

Accessibility, Operator OS, and Brand + Publishing are 6/6 verified each. `A2` is the portfolio's
only runtime recovery: the narrow WCAG 3.3.1 ARIA error-association port, verified against the real
`allys-tools` runtime. The other seventeen waves in this tranche are analysis milestones, and every
one still owes its `runtime_followup`.

- **Accessibility (6/6):** parity matrix, the A2 runtime port, overlay comparison, 20 candidate
  rules evaluated against live donor ASTs, a suite-local `A11yFinding` teaching projection shaped
  for (but not executed in) `a11y-kitchen`, and a
  measured overlay permission surface with a proposed consolidation. Outstanding: port the evaluated
  rules into the TypeScript runtime, verify the consolidated overlay in a real browser, and secure
  owner approval before any donor freeze.
- **Operator OS (6/6):** dotfiles capture into real PKos CAS with fenced Observer projection, the
  Ryos/master-plan inventory and its port assignments, and a JARVIS action lifecycle modeled through
  preview, approval, receipt, and a fail-closed unapproved-execution boundary. The suite-local
  launchpad now has real, bounded handlers for secret audit, content-addressed backup, additive note
  sync, and reversible cache rotation; active writes require exact, single-use approvals issued by
  an authority the suite cannot mint. Outstanding: execute the assigned donor ports in `dotfiles`
  backed by tests, scale live daily intake into the permanent vault, and accumulate authentic use
  receipts for these handlers before claiming adoption.
- **Brand + Publishing (6/6):** `BrandPackage` export from live `brand-maker-spec` sources, the
  nine-phase Brand Workshop mapping, the SourceRecord → draft → VCC review → publishing receipt
  path, two-consumer version-pinning and mutation-protection boundaries, the fixture intake state
  machine, and a simulated approval gate with verified rejection branching. Outstanding: run the
  export from the real Brand Maker runtime into a consumer outside this repository, implement the
  mapped gates, and replace the simulated gate with real human signoff.

## Tranche 2 — Prove the next systems (waves verified)

Production House (5/5), Model Behavior Lab (5/5), and Discovery + Decision (5/5) are verified as
analysis milestones. Each still describes donor structure rather than live execution:

- **Production House:** the pipeline is fingerprinted and expressed as `ProductionJob` receipts and
  event streams from fixtures. Outstanding: fingerprint real episode artifacts, invoke
  `elevenlabs-screenplay-formatter` on a real script slice, and carry live Writers Room story state
  through to a derived output.
- **Model Behavior Lab:** donor results are normalized into `ExperimentRun` with field parity, the
  duplication a shared comparator kernel would replace is measured, and the chess benchmark and
  corpus manifest are specified. Outstanding: re-run the donor runners live, implement the shared
  slice and delete the duplicated subsystems, and replay whole recorded matches.
- **Discovery + Decision:** SIF↔Forge stage mapping, red-team and analogy records, and Excavator
  discovery and citation paths are drawn from real phase nodes and budgets. Outstanding: execute
  both runtimes on one live question and diff their stages, run red-team and analogy live with
  budget accounting, and obtain owner approval before retiring any standalone runtime.

## Tranche 3 — Internal labs and real reference packs (waves verified)

Agent Reliability (5/5) and Game Design (5/5) are verified as analysis milestones:

- **Agent Reliability:** fixtures derive from the donors' declared action policy, gate coverage is
  read from harness source, promoted components are inventoried, and the curriculum fixtures are
  verified. Outstanding: execute the fixture battery inside each of the three harness runtimes
  against live agent loops, and confirm each counted consumer imports shared components at runtime.
- **Game Design:** the Tucked in Terrors run sample is fingerprinted and projected into the
  Storyweaver pack vocabulary, authored-game boundaries for Oregon D&D and March Madness are
  audited, and adventure-pack slot schemas are validated. Outstanding: re-run the donor simulator to
  regenerate distributions, materialize packs and run them in Storyweaver, and compare independently
  generated statistics against the donor sample.

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
