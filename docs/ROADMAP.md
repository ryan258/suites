# v1.0 Official Release Roadmap

## Mission

The first official release is the complete implementation of the eight suites already defined in
this repository. `v1.0.0` is not a control-plane-only release, a collection of prototypes, or three
finished flagships surrounded by five previews. All eight suite promises must work end to end
through authentic runtimes, owned contracts, recoverable state, and truthful evidence.

The release is evidence-gated, not date-gated. A calendar target may organize the work, but it
cannot waive runtime proof, repeated use, recovery, accessibility, security, provenance, or
owner-controlled approval. The [recovery standard](RECOVERY-STANDARD.md),
[migration program](MIGRATION-PROGRAM.md), and [project bible](PROJECT-BIBLE.md) govern promotion
and completion claims.

---

## What “Complete” Means for v1.0

All eight suites ship as supported product surfaces:

1. Accessibility
2. Operator OS
3. Brand + Publishing
4. Production House
5. Model Behavior Lab
6. Discovery + Decision
7. Agent Reliability Lab
8. Game Design + Simulation

A suite is release-complete only when:

1. its stated user promise runs end to end through one documented entry path;
2. every unique, valuable behavior represented by its current waves is ported, proven already
   covered, deliberately retained as an independently owned runtime, or explicitly rejected with
   evidence and owner acceptance;
3. its canonical state and cross-suite artifacts use owned, versioned contracts;
4. authentic producer and consumer runtimes replace suite-local fixtures wherever the supported
   promise depends on them;
5. source provenance, versions, approvals, failures, partial completion, and recovery stay visible;
6. automated, model-assisted, manual, and unknown evidence remain distinct;
7. at least three authentic accepted uses across distinct inputs or days prove adoption;
8. duplicate behavior has parity evidence and a single canonical owner, even when a separately
   versioned source repository remains the correct physical home;
9. appropriate deterministic, security, accessibility, failure, and recovery gates pass; and
10. publication, deployment, credentials, collaborator ownership, retirement, and destructive
    cleanup remain owner-controlled.

“Complete implementation” does not mean copying every repository into `/suites`, recreating
obsolete behavior, or deleting recoverable sources. It means every in-scope capability has an
evidenced final disposition and every one of the eight user promises is genuinely operable.

### Recovery targets

The purpose-fit targets already established by the project bible remain the minimum release bars.
They are recovery-quality scores, not percentages of files copied.

| Suite class | Suite IDs | Minimum v1 recovery target |
|---|---|---:|
| Flagships (`flagship`) | `accessibility`, `operator-os`, `brand-publishing` | 9.0/10 |
| Production systems (`production`) | `production-house`, `discovery-decision` | 8.0/10 |
| Constrained labs (`lab`) | `model-behavior-lab`, `agent-reliability`, `game-design` | 7.0/10 |

A lower lab target does not make a lab a preview. It reflects its narrower supported promise and
the decision not to reproduce low-value or obsolete donor behavior. Every lab still must meet its
completion criteria, run authentic workloads, and support documented recovery.

### What v1.0 does not claim

- All 70 source projects must live in one repository.
- Every donor must be deleted or archived.
- Optional model output can satisfy a deterministic, runtime, manual, or approval gate.
- A passing manifest, fixture, schema, test count, or analysis receipt proves runtime parity.
- A wave marked complete proves the migration objective named by that wave.
- The suite can mint human authority to publish, mutate external state, freeze donors, accept new
  baselines, or perform release actions.

---

## Current Baseline

The foundation and scheduled analysis program are complete. The eight-suite implementation and
adoption program is not.

- **Completed foundation and milestones:** 43/43 waves verified: 42 analysis milestones and one
  runtime recovery (`A2`). Completed work is recorded in [CHANGELOG.md](CHANGELOG.md).
- **70 Top-level projects** dispositioned across 8 suite boundaries and independent/archive
  containers.
- **43 Migration wave specifications** defined; wave milestone progress is 43/43.
- **6 Shared contracts implemented:** `A11yFinding`, `BrandPackage`, `ExperimentRun`, `InvestigationRecord`, `ProductionJob`, and `SourceRecord`.
- **Current promotion target:** `allys-tools`, clean at `f2b4c6e` in retained historical evidence.
  This is not a live cleanliness claim.
- **Baseline snapshot (2026-08-22):** 0/58 monitored source repositories drifted at snapshot time;
  all 58 baselines carried `status_sha256`. Current drift belongs in live CLI output, not static
  prose.

Milestone completion and evidence depth are separate axes:

- **4/43 prototype-level claims** — suite-owned fixtures or reference logic only (`A5`, `B3`,
  `B4`, `B6`).
- **1/43 reviewed historical analysis** — `A1`, a hand-authored decision whose structure is checked.
- **36/43 source-inspected claims** — donor source or retained artifacts parsed, not executed.
- **1/43 source-executed claims** — `O1`, whose receipt retains the argv, exit code, duration,
  and host-recomputed digests of the PKos modules that ran.
- **1/43 parity-verified runtime recoveries** — `A2`.
- **0 adopted, 0 converged, 0 resolved.**
- **42/43 completed waves still owe a live run** recorded in `runtime_followup`.

The release cannot be declared complete until all 42 current follow-ups are discharged and the one
existing runtime recovery is carried through authentic adoption. “Discharged” means verified
implementation or an evidence-backed final disposition allowed by the recovery standard—not a
documentation edit that removes the obligation.

### Current milestone register

This table is machine-checked against the manifests. “Complete” describes scheduled milestone
work, not suite or release completion.

| Suite | Verified | Next Target | Milestone meaning |
|---|---:|---|---|
| Accessibility | 6/6 | complete | All 6 scheduled milestones verified; 5 runtime follow-ups remain. |
| Operator OS | 6/6 | complete | All 6 scheduled milestones verified; 6 runtime follow-ups remain. |
| Brand + Publishing | 6/6 | complete | All 6 scheduled milestones verified; 6 runtime follow-ups remain. |
| Production House | 5/5 | complete | All 5 scheduled milestones verified; 5 runtime follow-ups remain. |
| Model Behavior Lab | 5/5 | complete | All 5 scheduled milestones verified; 5 runtime follow-ups remain. |
| Discovery + Decision | 5/5 | complete | All 5 scheduled milestones verified; 5 runtime follow-ups remain. |
| Agent Reliability | 5/5 | complete | All 5 scheduled milestones verified; 5 runtime follow-ups remain. |
| Game Design | 5/5 | complete | All 5 scheduled milestones verified; 5 runtime follow-ups remain. |

---

## Portfolio-Wide v1 Exit Criteria

Every required row must have retained, reviewable evidence on the exact release candidate.

| Area | Required outcome | Minimum release evidence |
|---|---|---|
| Eight suite promises | Every suite completes its documented end-to-end user journey. | Clean-room walkthrough, authentic inputs and runtimes, typed outputs, failure and recovery exercise. |
| Recovery program | Every current runtime follow-up has a verified implementation or approved final disposition; no unowned capability remains. | Updated runtime receipts, disposition decisions, provenance, and machine-checked zero outstanding release obligations. |
| Adoption | Every suite has at least three authentic accepted uses across distinct inputs or days. | Adoption receipts that identify distinct uses without exposing private content. |
| Convergence | Every duplicated capability has one canonical runtime/state owner or an approved independent-retention decision. | Parity evidence, owner decision, recovery plan, and retirement approval where retirement occurs. |
| Recovery score | Each suite meets or exceeds its class target without inflating unevidenced dimensions. | Machine-readable rubric assessment with linked evidence for every scored dimension. |
| Contracts | Six contracts are versioned, strict, documented, migration-safe, and proven across real boundaries. | Runtime/schema parity, canonical examples, invalid fixtures, and authentic producer/consumer tests. |
| Truth model | CLI, Toolbench, manifests, exports, docs, and receipts agree on evidence depth and support state. | Full validation and adversarial tests for over-promotion, stale evidence, and incomplete fingerprints. |
| Integrity | Approval, transaction, evidence, provenance, confinement, atomicity, and rollback boundaries fail closed. | Targeted race/interruption/adversarial tests and independent review of the exact candidate. |
| CLI/API | Supported commands/endpoints have stable inputs, JSON shapes, error taxonomy, exit behavior, and compatibility policy. | Contract tests and clean-install smoke workflows. |
| Toolbench | Browser surface is keyboard-usable, accessible, local-only, credential-safe, and behaviorally aligned with CLI/API. | Automated checks plus manual keyboard and assistive-technology-critical review. |
| Installation | Documented source, sdist, and wheel modes work on the supported environment matrix without hidden checkout assumptions. | Fresh isolated installs, packaged-asset checks, offline validation, and donor-prerequisite diagnostics. |
| Upgrade/recovery | Operator state can be backed up, upgraded from the last prerelease, rolled back, and recovered after interruption. | Versioned state fixtures, backup/restore drill, upgrade/rollback drill, and recovery receipts. |
| Security/privacy | No release-blocking issue; secrets/private content are not logged, archived, synchronized, replayed, exported, or transmitted unintentionally. | Threat-model review, secret probes, redaction tests, and release-workflow review. |
| Documentation | New operator can install, run every suite journey, understand evidence limits, diagnose failures, and recover. | Clean-room documentation walkthrough using only release artifacts. |
| Release artifacts | Version, source, changelog, wheel/sdist, schemas/assets, checksums, compatibility notes, and recovery bundle agree. | Reproducible build and owner-approved release checklist. |

Release-blocking severity policy:

- **P0/P1:** zero open findings.
- **P2:** fix before release unless Ryan explicitly accepts a narrowly documented risk with a
  containment and recovery plan.
- **P3:** may move to a patch/minor backlog only when it does not contradict a supported promise.
- An environment-blocked gate is neither a pass nor a product failure. Re-run it in an environment
  that permits the required socket, browser, filesystem, network, or donor runtime.

---

## Core Development Workstreams

### 1. Release truth and completion ledger

**Goal:** make “ready for v1” a machine-checkable claim that cannot be derived from wave counts.

- Add a release ledger that maps every suite criterion, wave follow-up, unique capability, runtime,
  canonical owner, contract, evidence artifact, adoption record, recovery score, and final
  disposition.
- Keep release lifecycle (`alpha`, `beta`, `release candidate`, `supported`, `deprecated`,
  `retired`) separate from recovery depth (`prototype` through `converged`).
- Require each obligation to close as implemented, already covered, independently retained, or
  rejected. Forbid silent deletion, blanket deferral, and “resolved” without evidence/owner.
- Derive CLI, Toolbench, export, and documentation summaries from the same ledger.
- Add negative tests for impossible promotions, self-comparison parity, stale receipts, missing
  provenance, incomplete untracked fingerprints, and status copied from the wave objective.

**Exit:** the control plane can list every remaining release blocker and can prove zero blockers
without converting plans or fixtures into implementation evidence.

### 2. Contract and state-format freeze

**Goal:** establish the v1 interoperability and upgrade boundary before broad runtime integration.

- Audit all six contracts for field semantics, identifiers, finite values, timestamps, hashes,
  provenance, approvals, partial completion, failures, and forward-compatibility behavior.
- Publish canonical valid/invalid examples and compatibility rules for additive, breaking, and
  security changes.
- Prove each stable contract across at least one authentic producer and one separately executed
  consumer; suite-local round trips are insufficient.
- Version approval stores, ledgers, evidence receipts, baselines, Toolbench state, and suite-owned
  persistent data.
- Create migration fixtures for every pre-v1 format that can appear in retained evidence or local
  operator state.
- Freeze v1 contracts and persistent state formats at the Phase 1 exit, before authentic runtime
  integration. Later additive compatible changes and security fixes remain possible; any breaking
  change reopens the freeze and invalidates the affected runtime/adoption evidence until repeated.

**Exit:** schemas, runtime validation, CLI inspection, examples, real producers/consumers, and
upgrade fixtures agree.

### 3. Trust core and transaction recovery

**Goal:** make evidence and mutation safe under concurrency, interruption, hostile paths, and
partial failure.

- Complete and independently review authority consumption, compare-and-swap, transaction commit,
  atomic replacement, no-clobber installation, quarantine, restoration, and rollback behavior.
- Bind approvals to canonical action, exact parameters, input bytes, destination state, expiry,
  and single-use consumption.
- Distinguish attempted, refused, committed, recovered, rolled back, and committed-but-unverified
  outcomes without collapsing them into success.
- Make evidence replacement confinement-safe, content-addressed, durable, and owner-aware.
- Fingerprint the complete candidate across tracked, staged, unstaged, and untracked content.
- Test symlinks, hard links, FIFOs/devices, path swaps, concurrent consumers, malformed JSON,
  non-finite values, Unicode, permission loss, crash points, partial writes, replay, and recovery.
- Document precise manual recovery wherever automatic rollback cannot be guaranteed.

**Exit:** exact-candidate review finds no open authority, data-loss, evidence-corruption,
confinement, race, or false-success defect at release-blocking severity.

### 4. Stable control-plane surface

**Goal:** make the portfolio operable without source-code archaeology.

- Freeze supported CLI command names, argument semantics, JSON shapes, exit codes, and error
  categories; document which human-readable output may evolve.
- Keep CLI, server, Toolbench, action registry, chain preflight, and redaction behavior aligned.
- Make source-workspace and installed-package root discovery explicit. An installed tool must find
  a valid workspace or fail with actionable setup/recovery instructions.
- Document configuration locations, environment variables, sensitive values, defaults,
  precedence, custom endpoints, provider-offline behavior, and donor prerequisites.
- Provide bounded diagnostics for configuration, workspace ownership, packaged assets, writable
  state, external runtimes, browser support, and incomplete recovery without exposing secrets.
- Preserve deterministic offline paths for every supported suite promise when optional hosted
  assistance is unavailable.

**Exit:** a new operator can install, inspect, validate, run deterministic work, diagnose a blocked
runtime, and recover without reading implementation code.

### 5. Toolbench accessibility and operator safety

**Goal:** make the browser a safe view of the same system rather than a second implementation.

- Provide complete keyboard operation, semantic structure, labeled controls, visible focus,
  accessible error/status announcements, large-text support, and reduced-motion behavior.
- Show evidence depth, execution depth, model assistance, mutation scope, required approval,
  partial failure, and recovery instructions before or alongside an action.
- Keep remote scripts/fonts disabled and prevent credentials, approvals, private content, and
  sensitive paths from entering URLs, logs, exports, replay trays, or browser state.
- Preserve chain preflight, dependency closure, `$from` rebasing, secret redaction, and fresh-token
  requirements consistently across UI/CLI/API.
- Test narrow/wide layouts, zoom, empty/partial state, corrupted evidence, provider outage, server
  restart, and interrupted mutation.

**Exit:** automated security/accessibility checks and manual keyboard/assistive-technology-critical
review pass; equivalent CLI and Toolbench actions return compatible typed results.

### 6. Distribution, compatibility, and upgrade

**Goal:** create verifiable artifacts that install, upgrade, and roll back cleanly.

- Declare and test supported Python, Node, browser, and operating-system versions; keep donor
  prerequisites separately documented.
- Build sdist/wheel from a clean candidate and verify entry points, schemas, manifests/workspace
  behavior, web assets, offline validation, and failure without prerequisites.
- Decide the canonical installation model before beta: source workspace, installed tool pointing
  to a workspace, or initialized self-contained workspace.
- Prohibit implicit dependency downloads during release verification.
- Generate artifact hashes and a machine-readable dependency/component inventory.
- Prove upgrade and rollback from preserved prerelease state, including incompatible and partially
  migrated data.

**Exit:** supported install modes behave consistently and a failed upgrade has a tested path back.

---

## Suite 1 — Accessibility

**Promise:** find, explain, repair, teach, and track accessibility without overstating evidence.

**Canonical destination:** `allys-tools`, with A11y Kitchen and the surviving keyboard overlay as
typed consumers rather than competing sources of truth.

### Implementation plan

1. **A1 — Execute the parity decisions.** Run each accepted WCAG Auditor port decision against the
   real destination runtime; retain donor/destination inputs, outputs, differences, and rejection
   reasons. Historical analysis remains attributed but stops being the only proof.
2. **A2 — Adopt the recovered WCAG 3.3.1 behavior.** Re-run full parity on the supported matrix,
   exercise failures and recovery, and record three accepted authentic uses across distinct pages
   or days.
3. **A4 — Port the selected rule set and crawl behavior.** Implement the evaluated candidates in
   the real TypeScript runtime, test representative/compliant/adversarial HTML in a real browser,
   and keep false-positive, false-negative, and manual-review boundaries explicit.
4. **A5 — Complete the teaching loop.** Feed findings produced by the real scanner into the
   running A11y Kitchen application and prove `A11yFinding` round-trips across audit, learning,
   ticket, and browser surfaces without evidence loss.
5. **A3/A6 — Converge the keyboard overlays.** Reconcile file, feature, permission, host scope,
   accessibility, and runtime parity in a real browser. Narrow permissions, choose one canonical
   overlay, preserve recovery, and obtain owner approval before freezing superseded donors.
6. **Evidence separation.** Ensure automated scan, deterministic comparison, model-assisted
   explanation, and manual assistive-technology findings remain separately labeled everywhere.

### Accessibility release gate

- All four suite completion criteria pass on authentic runtimes.
- One supported audit-to-learning/repair journey reaches adoption.
- Selected rules and crawl behavior have parity or explicit rejection evidence.
- Exactly one canonical keyboard overlay remains by owner-approved convergence decision.
- Manual keyboard and assistive-technology-critical review is retained alongside automated checks.
- Suite recovery score is at least 9.0/10.

---

## Suite 2 — Operator OS

**Promise:** preserve context and expose the next safe action when bandwidth is low.

**Canonical destinations:** `dotfiles` for operator commands and launchers, `PKos` for captured
knowledge/state, and the personal vault as a projection destination with loop prevention.

### Implementation plan

1. **O1/O4 — Complete the live intake path.** Run real daily inputs through live PKos capture and
   normalization into the permanent vault. Retain invocation, source fingerprint, exit result,
   host-verified output, checksum, provenance, citation, and projection ownership in a runtime
   receipt. Prove generated Observer notes cannot re-enter as canonical sources.
2. **O2/O5 — Finish Ryos/master-plan dispositions.** Port every accepted command/launcher behavior
   into `dotfiles` with tests and recovery; record evidence-backed rejections. Verify named
   duplicate decisions, then retire duplicate runtimes only with owner approval.
3. **O3/O6 — Run real JARVIS actions.** Drive preview, exact approval, real side effect, receipt,
   failure, rollback/recovery, and replay refusal through owned APIs or file contracts.
4. **Productionize bounded handlers.** Adopt secret audit, deterministic backup, additive note
   sync, and reversible cache rotation where they belong in the supported journey. Preserve
   dry-run/read-only paths and exact externally issued authority for writes.
5. **Low-bandwidth operation.** Make the next safe move, paused work, partial failure, recovery
   command, and offline/provider-free fallback obvious in CLI and Toolbench.
6. **Authentic adoption.** Complete three accepted daily-use cycles across distinct inputs/days,
   including at least one interruption/recovery case, without exposing private vault content in
   release evidence.

### Operator OS release gate

- All five completion criteria pass in the permanent operator environment.
- The supported capture-to-safe-action journey reaches adoption.
- Unique Ryos/master-plan behavior has a final implemented/rejected disposition.
- Approval and transaction boundaries survive stale input, concurrent consumption, path exchange,
  partial failure, and restart.
- Deterministic fallback remains useful with credentials and providers unavailable.
- Suite recovery score is at least 9.0/10.

---

## Suite 3 — Brand + Publishing

**Promise:** turn governed brand truth and sourced ideas into approved, traceable publications.

**Canonical destinations:** Brand System Maker for governed brand state and intake, with `cyborg`
or another explicitly chosen publishing consumer operating across a real process/repository seam.

### Implementation plan

1. **B1/B4 — Establish the real contract boundary.** Export a complete `BrandPackage` from the real
   Brand Maker runtime and consume it outside this repository. Prove version pinning, provenance,
   read-only canonical truth, incompatible-version refusal, and mutation protection.
2. **B2/B5 — Implement the governed intake.** Move all mapped Brand Workshop phases and low-typing
   gated state transitions into the real application; reconcile duplicate intake UX; verify resume,
   rejection, correction, and recovery per phase.
3. **B3 — Run the real editorial path.** Carry an authentic `SourceRecord` through draft and the
   actual VCC review system; preserve citations, transformations, version history, reviewer notes,
   rejection/return branches, and dry-run execution.
4. **B6 — Bind human signoff.** Replace simulated approval with retained human approval scoped to
   the exact artifact/package version. The suite may prepare a publication handoff but cannot mint
   signoff or publish without owner authority.
5. **Metrics and feedback.** Link approved output and later metrics to the same trace without
   treating engagement as factual or brand approval.
6. **Authentic adoption.** Complete three accepted brand-to-publication-handoff journeys across
   distinct inputs/days, including a rejected or revised path.

### Brand + Publishing release gate

- All five completion criteria pass across real producer, consumer, review, and approval systems.
- `BrandPackage` contains identity, voice, audience, claims, assets, rules, version, and provenance
  without consumer-side canonical mutation.
- Brand Workshop functionality is converged into the real Brand Maker application.
- Publication claims never exceed the actual owner-authorized action performed.
- The supported journey reaches adoption and the suite recovery score is at least 9.0/10.

---

## Suite 4 — Production House

**Promise:** move creative work through resumable jobs to verified deliverables.

**Canonical destination:** Production House owns `ProductionJob`; Groundwire, the formatter, and
Writers Room become bounded runtime stages or separately owned tools behind that job contract.

### Implementation plan

1. **P1 — Complete a real Groundwire episode.** Ingest a hashed authentic episode, render it, and
   compare stems, captions, manifests, QC, failures, retry behavior, and recovery against one
   `ProductionJob`.
2. **P2 — Integrate the real formatter.** Invoke `elevenlabs-screenplay-formatter` on the authentic
   script, bind source/output versions to the same job, and verify malformed input, partial output,
   retry, and recovery.
3. **P3/P5 — Complete Writers Room handoff.** Carry versioned real story state and revision history,
   including final room signoff, into a derived production output without creating a second
   production-state owner.
4. **P4 — Complete documentary production.** Drive multi-track and sound-design work from a real
   documentary episode render with resumable stages and independently verified deliverables.
5. **Shared-mechanic decisions.** Admit adjacent pipelines only after two real consumers prove a
   shared mechanic reduces complexity; otherwise retain the behavior locally.
6. **Authentic adoption.** Complete three accepted production jobs across distinct inputs/days,
   including a retry/recovery case and final deliverable verification.

### Production House release gate

- All four completion criteria pass on authentic creative artifacts.
- Formatter, render, caption, QC, retry, failure, and recovery events link to one job record.
- Writers Room remains the story-authoring source while Production House owns production state.
- At least one full Groundwire episode and one documentary/multi-track path complete.
- The supported production journey reaches adoption and the suite recovery score is at least 8.0/10.

---

## Suite 5 — Model Behavior Lab

**Promise:** produce reproducible, evidence-linked model capability profiles.

**Canonical destination:** one run/report kernel owned by the lab, with ethics and chess expressed
as packs/adapters and collaborator-owned sources remaining externally owned.

### Implementation plan

1. **M1 — Run live experiments.** Execute the donor experiment runner rather than normalizing only
   stored results. Pin benchmark, scorer, provider, resolved model, request parameters, seed or
   iteration policy, environment, cost, retry, errors, and partial completion.
2. **M2 — Implement the shared kernel.** Extract the proven shared slice, migrate at least two real
   consumers, verify parity, and remove duplicated donor subsystems only after recovery and owner
   approval.
3. **M3 — Replay whole chess matches.** Apply legal moves across complete recorded matches with
   invalid-move, provider-failure, retry, and resume behavior—not just opening plies.
4. **M4 — Score complete workloads.** Run full transcripts and tactical puzzles through the common
   scorer and preserve raw evidence plus structured results.
5. **M5 — Prove corpus reproducibility.** Re-run a historical evaluation end to end from pinned
   hashes and identify unavailable/non-reproducible provider behavior truthfully.
6. **Authentic adoption.** Produce and accept at least three reproducible capability profiles
   across distinct benchmark/model/input combinations or days.

### Model Behavior Lab release gate

- All four completion criteria pass on live runs.
- Every report traces to raw evidence, exact configuration, costs/errors/retries, and scorer.
- Ethics and chess use the shared kernel through at least two verified consumers.
- Collaborator ownership and provider attribution are preserved.
- The supported profiling journey reaches adoption and the suite recovery score is at least 7.0/10.

---

## Suite 6 — Discovery + Decision

**Promise:** turn a hard question and typed evidence into a resumable decision record.

**Canonical destination:** Forge-backed investigation modes writing `InvestigationRecord`, with
immutable `SourceRecord` citations and private Shadow Mirror constraints kept outside generalized
claims.

### Implementation plan

1. **D1 — Prove SIF/Forge parity.** Run both authentic runtimes on the same question and compare
   stage inputs, outputs, budgets, failures, and resume behavior.
2. **D2 — Run live red-team mode.** Execute the red-team stage inside Forge with consent, energy,
   budget, pause, resume, and refusal gates.
3. **D3 — Run authentic Excavator discovery.** Produce real claims, citations, novelty evaluation,
   uncertainty, and immutable source anchors rather than projecting retained documents.
4. **D4 — Run live analogy synthesis.** Execute deep-mode analogy work with real call-budget
   accounting, partial completion, and reproducible decision linkage.
5. **D5 — Converge source ingestion.** Make Forge ingest Excavator sources directly, verify
   behavior/recovery parity, and obtain owner approval before any standalone-runtime retirement.
6. **Protect Shadow Mirror.** Keep it private, non-clinical, consent/energy-gated, and excluded from
   generalized product efficacy claims.
7. **Authentic adoption.** Complete three accepted investigations across distinct hard questions
   or days, including a paused/resumed or budget-exhausted path.

### Discovery + Decision release gate

- All four completion criteria pass on live investigations.
- Question, premises, typed evidence, stages, budgets, decisions, and recovery survive round trip.
- Selected SIF stages run behind Forge modes with output/failure parity.
- Excavator citations and novelty/uncertainty measures are source-verifiable.
- The supported decision journey reaches adoption and the suite recovery score is at least 8.0/10.

---

## Suite 7 — Agent Reliability Lab

**Promise:** teach and test bounded agent behavior with deterministic gates.

**Canonical destination:** a shared evaluation contract and fixture curriculum, while production
harnesses remain separately owned runtimes unless two real consumers justify shared code.

### Implementation plan

1. **R1/R5 — Execute real agent behavior.** Run adversarial and mined curriculum fixtures against
   live bounded agent loops; retain plans, guards, actions, tool results, budgets, failures,
   reviewer artifacts, and rollback/recovery traces.
2. **R2 — Cross-harness verification.** Execute the fixture battery inside Looping Box, SSSF, and
   Agentic Harness; compare actual runtime enforcement rather than source markers.
3. **R3 — Prove shared consumers.** Confirm every promoted component is imported and exercised at
   runtime by at least two consumers.
4. **R4 — Demote false abstractions.** Move one-consumer or cosmetic “shared” code back to its
   owner, then re-audit actual consumers and dependency boundaries.
5. **Teaching boundary.** Keep examples readable, deterministic, intentionally smaller than
   production harnesses, and explicit about which safety properties they do not prove.
6. **Authentic adoption.** Complete three accepted evaluation cycles across distinct live agents,
   fixtures, or days, including malformed plan, exhausted budget, retry, and rollback cases.

### Agent Reliability release gate

- All four completion criteria pass against live harness runtimes.
- The shared evaluation covers confinement, malformed plans, retries, budgets, rollback, and
  reviewer artifacts.
- Promoted shared packages have two verified runtime consumers; all others are demoted.
- Teaching examples never read as production assurance.
- The supported evaluation journey reaches adoption and the suite recovery score is at least 7.0/10.

---

## Suite 8 — Game Design + Simulation

**Promise:** turn game rules into simulations, balance evidence, and playable artifacts.

**Canonical destination:** Storyweaver-compatible packs and simulation/report contracts, while
authored games remain independently owned unless a proven shared mechanic justifies integration.

### Implementation plan

1. **G1 — Re-run the donor simulator.** Regenerate the Tucked in Terrors sample from versioned
   rules, seed, code fingerprint, configuration, and run count rather than relying on the retained
   sample alone.
2. **G2 — Materialize and run the real pack.** Generate a complete Storyweaver pack, run it in the
   authentic engine, and compare independently produced distributions/statistics to donor results.
3. **G4 — Generate an adventure pack through Storyweaver.** Produce the pack from authored input
   and diff rules/slots/printable artifacts against the written design source.
4. **G3/G5 — Resolve authored-game boundaries.** Re-audit Oregon D&D and March Madness against real
   export/port intent. Retain them independently when no proven shared mechanic exists; if a port is
   chosen, execute it and prove parity rather than leaving a conditional roadmap note.
5. **Playable artifacts and recovery.** Link rules, seeds, simulations, metrics, reports, print
   outputs, failures, and regeneration instructions in one reproducible game-pack record.
6. **Authentic adoption.** Complete three accepted design/simulation cycles across distinct seeds,
   rules revisions, games, or days, including recovery from invalid/incomplete pack state.

### Game Design release gate

- All three completion criteria pass with a real playable pack and reproducible simulation.
- Tucked in Terrors statistics match or improve on the dedicated simulator with versioned evidence.
- Every authored game has a final integrated-or-independent ownership decision.
- Printable/playable artifacts can be regenerated from the retained rules and configuration.
- The supported game-design journey reaches adoption and the suite recovery score is at least 7.0/10.

---

## Release Sequence

Version numbers are internal promotion checkpoints. Publication of any checkpoint remains an
explicit owner decision.

### Phase 0 — Integrity baseline (`0.1.x`)

- Resolve or explicitly disposition current trust-core review findings.
- Establish exact candidate identity across tracked and untracked content.
- Implement the release/completion ledger and map all 42 follow-ups to concrete work/evidence.
- Reconfirm live drift, donor ownership, prerequisites, and recovery boundaries.

**Exit:** no known P0/P1 integrity defect; every suite has an approved implementation sequence;
release status cannot be derived from milestone counts.

### Phase 1 — Platform alpha (`0.2.0-alpha`)

- Complete contract/state-format policy, trust core, stable CLI/API boundary, root/workspace model,
  diagnostics, and upgrade fixtures.
- Add compatibility, migration, adversarial, transaction, and packaging tests before broad ports.
- Freeze the architecture for authentic suite integration; new frameworks require evidence that a
  contract, adapter, action, pack, or skill is insufficient.
- Freeze the six v1 contracts, receipt schemas, configuration boundary, and persistent state
  formats. Record the exact versions that all later runtime and adoption evidence must use.

**Exit:** clean install runs deterministic validation/read-only actions; mutations recover safely;
real suite ports can produce versioned receipts that v1 will continue to read; the v1
interoperability/state boundary is frozen before any authentic-use evidence is collected.

### Phase 2 — Flagship implementation (`0.4.0-alpha`)

- Complete Accessibility, Operator OS, and Brand + Publishing runtime follow-ups.
- Establish all flagship authentic producer/consumer seams and parity gates.
- Begin authentic use; do not claim adoption until repeated-use requirements are met.

**Exit:** all three flagship promises run end to end once with retained runtime/parity evidence and
no unresolved completion criterion.

### Phase 3 — Production systems (`0.6.0-alpha`)

- Complete Production House and Discovery + Decision runtime follow-ups.
- Verify real creative artifacts, budgeted investigations, resumability, failure, and recovery.
- Begin authentic use for both suites as soon as their end-to-end paths pass.
- Keep shared-contract changes additive and compatible. A necessary breaking change explicitly
  reopens the Phase 1 freeze and requires affected runtime evidence to be repeated.

**Exit:** both production-system promises run end to end once and meet their completion criteria
except repeated-use adoption.

### Phase 4 — Labs and games (`0.7.0-alpha`)

- Complete Model Behavior Lab, Agent Reliability Lab, and Game Design runtime follow-ups.
- Finish shared-kernel/two-consumer decisions, full live workloads, pack generation, and authored
  game dispositions.
- Begin authentic use for each suite as soon as its end-to-end path passes.

**Exit:** all eight suite promises run end to end; all 42 original runtime follow-ups have verified
resolutions; no suite remains fixture-only or source-inspection-only for its supported promise.

### Phase 5 — Adoption and convergence beta (`0.8.0-beta`)

- Complete the three-authentic-use threshold for every suite, carrying forward qualifying uses
  begun in Phases 2–4 and repeating any evidence invalidated by a reopened contract freeze.
- Correct operational friction, false success, recovery gaps, inaccessible workflows, and evidence
  ambiguity found in use.
- Score every suite against its target and close weak dimensions with real evidence.
- Finish canonical-owner, independent-retention, freeze, and retirement decisions; retirement
  requires current owner approval.
- Freeze v1 feature scope. New capabilities move after v1 unless they close an exit criterion.

**Exit:** all eight suites reach adoption, meet recovery targets, and have no unowned duplicate
behavior or unresolved release obligation.

### Phase 6 — Release candidate (`0.9.0-rc.1` and later)

- Confirm the Phase 1 contract/state freeze and freeze the supported CLI/API presentation surface;
  do not introduce a first or breaking data-contract freeze at release-candidate time.
- Build from the exact candidate and run deterministic, adversarial, full donor/runtime,
  packaging, browser, accessibility, clean-room docs, backup/restore, and upgrade/rollback gates.
- Independently review the exact candidate, not a neighboring worktree or manifest summary.
- Fix blockers, rebuild, and repeat affected gates; do not waive evidence by relabeling state.
- Prepare version, changelog, known limitations, hashes, compatibility notes, recovery bundle, and
  release runbook.

**Exit:** all portfolio-wide v1 criteria are evidenced; zero open P0/P1; accepted P2 risks have
explicit owner approval and containment; candidate remains unchanged after final verification.

### Phase 7 — Official release (`1.0.0`)

- Obtain Ryan’s explicit approval for the exact commit/tag and every external release action.
- Create the version/tag and artifacts from the approved source only after authorization.
- Verify installed artifacts against recorded hashes and run one smoke journey per suite.
- Publish or distribute only to explicitly named destinations.
- Preserve candidate fingerprint, evidence manifest, release notes, artifacts, hashes, and rollback
  bundle.

**Exit:** official artifacts are verifiably derived from the approved candidate, retrievable,
installable, and recoverable. A successful build without authorized distribution remains a release
candidate, not a published release.

### Phase 8 — Stabilization (`1.0.x`)

- Prioritize data loss, authority, evidence corruption, compatibility, accessibility, and recovery
  regressions found through real use.
- Keep patch releases backward-compatible; schedule breaking contract/API changes for a later
  major release.
- Continue measuring suite adoption without rewriting original release evidence.

---

## Critical Path

```text
release truth + exact candidate identity
        |
        +--> trust core + versioned state/upgrade policy
        |             |
        |             +--> stable CLI/API/Toolbench boundaries
        |                           |
        +--> contract freeze -------+--> authentic suite runtime ports
                                            |
                                            +--> all 8 end-to-end journeys
                                            |
                                            +--> repeated use + recovery scores
                                            |
distribution matrix + upgrade drills -------+--> exact release candidate
                                                     |
docs + accessibility + independent review ----------+--> owner-approved v1.0
```

The trust core and versioned state model precede broad authentic use so beta does not create
receipts or local state the official release cannot read safely. Within the suite work, the planned
order is flagship contracts first, then production systems, then constrained labs; independent
suite work may run in parallel only after its shared boundaries are stable.

### Cross-suite dependencies

| Producer | Contract/capability | Consumers | Sequencing consequence |
|---|---|---|---|
| Operator OS / knowledge intake | `SourceRecord` | Brand + Publishing, Discovery + Decision | Freeze provenance/citation semantics before authentic publishing and investigation adoption. |
| Accessibility | `A11yFinding` | A11y Kitchen, ticket/browser surfaces | Complete real scanner production before teaching/UI round-trip evidence. |
| Brand System Maker | `BrandPackage` | Cyborg/publishing consumers | Freeze version/mutation rules before repeated editorial use. |
| Production House | `ProductionJob` | Formatter, Groundwire, Writers Room handoff | Freeze resumable job/events before full episode and documentary evidence. |
| Model Behavior Lab | `ExperimentRun` | Ethics/chess adapters and reports | Shared kernel and pinned-run semantics precede full workload adoption. |
| Discovery + Decision | `InvestigationRecord` | Forge modes and decision records | Budget/resume/citation semantics precede SIF/Forge convergence. |
| Agent Reliability | shared eval/fixtures | Looping Box, SSSF, Agentic Harness | Two runtime consumers must exist before shared-package promotion. |
| Game Design | pack/simulation records | Storyweaver and printable outputs | Versioned rules/seeds precede parity comparison and pack adoption. |

---

## Verification Strategy

Use the cheapest relevant gate during development. Full matrices and donor runtimes run at phase
exits and on the exact release candidate, not reflexively after documentation-only edits. Retained
evidence changes only through an intentional reviewed record operation.

### Routine documentation and registry gates

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites validate --fast
PYTHONPATH=src python3 -m unittest tests.test_docs
```

### Phase-exit control-plane gates

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites wave --all --no-record
PYTHONPATH=src python3 -m portfolio_suites ai --status --json
PYTHONPATH=src python3 -m unittest discover -s tests -v
SUITES_WHEEL_SMOKE=1 PYTHONPATH=src python3 -m unittest tests.test_wheel_smoke -v
```

Each authentic runtime gate also requires its own recorded runbook because dependencies and manual
checks differ. A qualifying runtime receipt names the exact invocation/action, source fingerprint,
environment constraints, exit result, inputs, independently checked outputs, differences,
failures, recovery, and human decisions. `--record` never substitutes for selecting and reviewing
the correct full-depth runtime.

### Required negative-path families

- malformed contracts, unknown fields, non-finite values, incompatible versions, and stale data;
- source/destination drift, self-comparison parity, missing donor, partial output, and wrong runtime;
- symlink/hard-link/path-swap/FIFO/device attacks, untracked omissions, and incomplete fingerprints;
- expired/replayed/mismatched approvals, concurrent consumers, commit failure, rollback failure,
  and committed-but-unverified state;
- provider outage, missing credential, rate limit, model substitution, prompt secret, and unsafe
  custom endpoint;
- browser credential leakage, replay-tray leakage, local-origin violations, keyboard traps, zoom,
  reduced motion, and inaccessible status/error reporting;
- interrupted jobs, corrupted receipts, failed upgrade, failed restore, and recovery after restart.

---

## Official Release Checklist

### Eight-suite completion

- [ ] Accessibility passes all criteria, reaches adoption, and scores at least 9.0/10.
- [ ] Operator OS passes all criteria, reaches adoption, and scores at least 9.0/10.
- [ ] Brand + Publishing passes all criteria, reaches adoption, and scores at least 9.0/10.
- [ ] Production House passes all criteria, reaches adoption, and scores at least 8.0/10.
- [ ] Model Behavior Lab passes all criteria, reaches adoption, and scores at least 7.0/10.
- [ ] Discovery + Decision passes all criteria, reaches adoption, and scores at least 8.0/10.
- [ ] Agent Reliability Lab passes all criteria, reaches adoption, and scores at least 7.0/10.
- [ ] Game Design + Simulation passes all criteria, reaches adoption, and scores at least 7.0/10.
- [ ] All 42 original runtime follow-ups have verified final dispositions.
- [ ] Every duplicate capability has one canonical owner or approved independent-retention decision.

### Platform, integrity, and recovery

- [ ] Six contracts are frozen, versioned, documented, migration-tested, and proven across real
  producer/consumer boundaries.
- [ ] Exact candidate identity includes tracked, staged, unstaged, and untracked content.
- [ ] Approval, transaction, provenance, evidence, path, redaction, rollback, and recovery negative
  paths pass.
- [ ] CLI, API, Toolbench, exports, manifests, docs, and receipts agree on current truth.
- [ ] Backup/restore and upgrade/rollback drills succeed from preserved fixtures.
- [ ] No release-blocking secret, privacy, authority, data-loss, or evidence-integrity issue remains.
- [ ] Zero open P0/P1; any accepted P2 has explicit owner decision and containment.

### Distribution and owner control

- [ ] Supported environment matrix passes from clean installations.
- [ ] Source archive, sdist, wheel, entry point, assets, schemas, and workspace behavior are verified.
- [ ] Version, changelog, compatibility notes, known limitations, hashes, and rollback bundle agree.
- [ ] Clean-room install plus one end-to-end walkthrough per suite succeeds from shipped docs.
- [ ] Ryan explicitly authorizes the exact tag, publication destination, and every external action.

---

## After v1.0

Post-v1 work may expand capabilities, raise lab recovery targets, add consumers, or simplify
physical repository layout. It must not be used to hide incomplete v1 requirements. Appropriate
post-v1 candidates include:

- additional accessibility rules beyond the evidenced v1 set;
- more production formats, investigation modes, model benchmarks, harnesses, and game packs;
- promotion of independently proven shared components after two consumers emerge;
- later owner-approved physical rehoming of canonical anchors;
- hosted or multi-user operation if local-first ownership and privacy remain intact;
- new model providers or paid routing behind explicit cost/privacy policy;
- breaking contract/API changes scheduled through the next major-version process.

The official release succeeds when all eight existing suite promises are authentic, adopted,
recoverable, and honestly reported—not when the repository merely contains eight directories or a
green manifest.
