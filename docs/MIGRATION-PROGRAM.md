# Migration Program

All 24 Tranche 0–3 waves below are now complete (see each suite's `evidence/`). For what actually
instituting a suite requires next — real ports, real retirements, real single-runtime status — see
[the roadmap](ROADMAP.md).

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

### Accessibility

- **A2:** finish runtime verification of the narrow WCAG 3.3.1 ARIA error-association port.
- **A3:** reconcile the three keyboard overlays before any archive action.
- Then port crawl controls and one explicit review-candidate producer, not 17 pseudo-certification
  rules.

### Operator OS

- **O1:** capture one authored Markdown source into PKOS, retrieve it with citation, and project one
  stable Observer note that is fenced from re-ingestion.
- **O2:** compare Ryos/master-plan behavior against current dotfiles/Observer state.
- **O3:** make one JARVIS action use a canonical service with preview, approval, receipt, and recovery.

### Brand + Publishing

- **B1:** export one approved `BrandPackage` and consume it in a dry run with version pinning and
  mutation protection.
- **B2:** map and port Brand Workshop's nine low-typing phases into Brand Maker state.
- **B3:** prove SourceRecord → governed draft → VCC review → dry-run publishing receipt.

## Tranche 2 — Prove the next systems

- **P1/P2:** fingerprint one Groundwire episode, then execute it as a ProductionJob through the
  formatter without parallel canonical state.
- **M1/M2:** normalize one ethics scenario into ExperimentRun, then extract the ethics app as a pack
  over the comparator kernel.
- **D1/D2:** map SIF stages to Forge and port one bounded stage with consent, budget, failure, resume,
  canonical Markdown, and rebuild evidence.

## Tranche 3 — Internal labs and real reference packs

- **R1/R2:** define and run adversarial harness fixtures for confinement, malformed output, retries,
  budgets, rollback, and reviewer evidence.
- **G1/G2:** fingerprint Tucked in Terrors and prove seeded statistical/artifact parity as a
  Storyweaver pack.

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
cleanup authority.

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
