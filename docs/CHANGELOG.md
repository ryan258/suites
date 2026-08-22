# Portfolio Suites — Changelog & Milestone History

This document records genuine, verified milestones for the `/Users/ryanjohnson/Projects/suites` portfolio control plane.

---

## Verified Completed Milestones & Control-Plane Foundations

The `/Users/ryanjohnson/Projects/suites` control plane foundation and verified milestones:

### Control Plane Foundation Established
- **8/8 Suite Boundaries**: Defined with explicit user promises and canonical anchors ([Accessibility](file:///Users/ryanjohnson/Projects/suites/accessibility), [Operator OS](file:///Users/ryanjohnson/Projects/suites/operator-os), [Brand + Publishing](file:///Users/ryanjohnson/Projects/suites/brand-publishing), [Production House](file:///Users/ryanjohnson/Projects/suites/production-house), [Model Behavior Lab](file:///Users/ryanjohnson/Projects/suites/model-behavior-lab), [Discovery + Decision](file:///Users/ryanjohnson/Projects/suites/discovery-decision), [Agent Reliability Lab](file:///Users/ryanjohnson/Projects/suites/agent-reliability), [Game Design](file:///Users/ryanjohnson/Projects/suites/game-design)).
- **6 Shared Contracts**: Implemented schemas with bidirectional validation (`A11yFinding`, `SourceRecord`, `BrandPackage`, `InvestigationRecord`, `ProductionJob`, `ExperimentRun`).
- **70 Top-Level Projects**: Dispositioned across suites and independent containers in [project-ledger.json](file:///Users/ryanjohnson/Projects/suites/portfolio/project-ledger.json).
- **Zero-Dependency CLI & Web Dashboard**: Operational CLI commands (`status`, `next`, `validate`, `drift`, `wave`, `ai-config`) and local web dashboard on port 8383.
- **43 Migration Wave Specifications**: Defined across 8 source adapters; every wave runner reads donor content, declares a recovery claim, and specifies runtime follow-up obligations.
- **9/10 Recovery Standard Adopted**: Weighted rubrics, strict promotion gates (`prototype` → `source_verified` → `parity_verified` → `adopted` → `converged`), and fail-closed validation.

### Verified Wave Milestones Completed (5/43)
1. **`A1` — Accessibility (Analysis Milestone)**: WCAG Auditor to Ally rule, crawl, finding, and deliverable parity matrix ([evidence](file:///Users/ryanjohnson/Projects/suites/accessibility/evidence/A1-WCAG-AUDITOR-PARITY.md)).
2. **`A2` — Accessibility (Runtime Recovery)**: WCAG 3.3.1 Error Association rule port into destination runtime [`allys-tools`](file:///Users/ryanjohnson/Projects/allys-tools) (`f2b4c6e`) with 127/127 tests passing and four-stage adapter verification ([evidence](file:///Users/ryanjohnson/Projects/suites/accessibility/evidence/A2-WCAG-331-EVIDENCE.json)).
3. **`A3` — Accessibility (Analysis Milestone)**: Keyboard overlay reconciliation across `kb-overlay`, `keyboard-nav-overlay`, and `keyboard-nav-overlay-94bf7e` ([evidence](file:///Users/ryanjohnson/Projects/suites/accessibility/evidence/A3-KEYBOARD-OVERLAYS.md)).
4. **`O2` — Operator OS (Analysis Milestone)**: Full feature inventory and spec mapping of `ryos` and `master-upgrade-plan` against `dotfiles` and `obsidian-observer` ([evidence](file:///Users/ryanjohnson/Projects/suites/operator-os/evidence/O2-RYOS-DISPOSITION.md)).
5. **`B2` — Brand + Publishing (Analysis Milestone)**: Live source mapping of Brand Workshop's nine phases onto `brand-maker-spec` workspace state and gates ([evidence](file:///Users/ryanjohnson/Projects/suites/brand-publishing/evidence/B2-WORKSHOP-MAPPING.json)).

---

## 2026-08-21 — Security Hardening, Descriptor Confinement & Packaging Gates

Implemented control-plane security hardening, file descriptor-anchored workspace confinement in Operator OS, deterministic CLI exits, environment-independent root resolution, and opt-in fail-closed distribution smoke tests:

- **Descriptor-Anchored Confinement (`_read_confined_file`)**: Hardened Operator OS file operations (`backup_file`, `audit_workspace_confinement`, `quarantine_file`, `diff_file_against_snapshot`) against path traversal, symlink escapes, and FIFO blocking. Enforces a strict 8-step read sequence:
  1. Recheck candidate confinement against workspace root.
  2. Open with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`.
  3. Inspect descriptor with `fstat`.
  4. Reject anything other than regular files (`S_ISREG`), blocking FIFOs, sockets, and character/block devices without stalling.
  5. Reject files exceeding initial maximum byte limits (`st_size > max_bytes`).
  6. Stream-read through the open descriptor, tracking cumulative bytes to reject files growing beyond the cap during concurrent writes.
  7. Read strictly through the anchored descriptor.
  8. Ensure descriptor closure across all normal and exception return paths.
- **Deterministic CLI Exit Codes & Fast Validation**: Standardized exit codes across all CLI commands (exit 0 on success/clean, exit 1 on errors/unresolved drift/failures, exit 2 on invalid argument flags). Added `--fast` flag to `validate` (`suites validate --fast`) for instant offline schema and contract verification without heavy external or runtime probes.
- **Environment & Out-of-Tree Resolution (`SUITES_ROOT`)**: Updated `portfolio_suites.paths` to support explicit `SUITES_ROOT` environment override when running from an installed wheel or out-of-tree working directory, emitting actionable diagnostic errors when root markers are absent.
- **Fail-Closed Installed Wheel Gate (`test_wheel_smoke.py`)**: Added an opt-in distribution verification gate triggered via `SUITES_WHEEL_SMOKE=1`. The gate builds the wheel, installs it into an isolated virtual environment with `PYTHONPATH` scrubbed, verifies non-Python package assets (`suite.json`, schemas, dashboard assets), exercises the installed console script outside the checkout, and proves fail-closed behavior when `SUITES_ROOT` is unset or invalid.
- **Test Suite Expansion**: Added 19 comprehensive unit tests across engine confinement, CLI status codes, server error handlers, out-of-tree root detection, and wheel installation, bringing full milestone test suite coverage to 163 passing tests (plus 4 opt-in distribution smoke tests).

---

## 2026-08-21 — Engine Action Chaining across CLI, Server, and Web Dashboard

Added the engine action chaining framework (`portfolio_suites.chains`), enabling sequential execution where earlier action outputs feed into subsequent action arguments via `{"$from": <step_index>}` references with optional dotted or indexed `path` resolution:

- **Chains Engine (`chains.py`)**: Resolves step references, handles topological validation, checks forward-reference bounds, and extracts nested path properties across heterogeneous engine outputs.
- **CLI Support**: Added `suites chain <chain.json>` (and `--quiet` mode) to load, validate, and execute chain workflows from file or stdin.
- **Server API**: Added `POST /api/chain` endpoint to execute multi-step chains and return step-by-step traces with latency and result payloads.
- **Toolbench UI Integration**: Added interactive chain construction to the web dashboard (`app.js`, `index.html`) — clicking **use** on any tray item injects a `$from` reference into pending tool arguments, replaying the complete reproducible chain server-side. Added **Copy Chain JSON** button for exporting tray workflows to standalone replayable files.
- **Test Coverage**: Added unit tests in `tests/test_engine_actions.py` covering multi-step data flow, list path extraction, cross-suite provenance survival, forward-reference rejection, and malformed path error handling.

---

## 2026-08-21 — Source Binding for the Twenty-One Unintegrated Waves

Every wave that was still `specified` — `M1`–`M5`, `D1`–`D5`, `R1`–`R5`, `G1`–`G5`, and `A6` — now
reads donor content before it makes any claim, and each declares a `recovery_claim` plus a
`runtime_followup`. Four source adapters were added (`model_behavior`, `discovery_decision`,
`agent_reliability`, `game_design`) and `A6` was rewritten to measure rather than assert. Each of
the twenty-one waves gained an `ANALYSIS_RECEIPT_SPECS` entry, and `validate_registry` now checks
every declared claim and its retained receipt instead of only completed waves — a prototype receipt
that later goes malformed or self-contradictory fails the canonical gate.

These gates read donor content; they do not execute donor runtimes. They are therefore `analysis`
claims at `prototype` level. Where a wave's objective describes an outcome the gate did not
produce, the receipt status names what was actually done:

- **Model Behavior Lab.** `M1` normalizes a real `ai-ethics-comparator` result (prompt, responses,
  params, tally, undecided count) into `ExperimentRun` and proves field parity. `M2` is an
  `extraction_matrix_measured` receipt, not a unification: both corpora are admitted by one
  contract kernel, and the four subsystems each donor still duplicates are counted, with
  `canonical_slice_implemented: false` and `duplicate_runtimes_eliminated: 0`. `M3`/`M4` score the
  recorded `ai-chess` openings — first ply only, because the engine judges legality but cannot
  apply a move.
- **Discovery + Decision.** `D1` maps real SIF phase nodes to Forge stages using the donors' own
  call budgets and retained artifacts; `D2`/`D4` carry the recorded red-team and analogy phases into
  budgeted `InvestigationRecord`s. `D3` retains byte-anchored excerpts from two real Excavator
  documents and a measured lexical overlap (one shared term between the two sampled documents); it
  makes no novelty, uncertainty, or semantic-discovery claim, and the prototype engine's fixed
  0.88 score and invented citation sections are deliberately unused. `D5` records
  `retirement_proposed`: the citation carries the source's own sha256 and origin into the
  investigation, while `retirement_performed`, `standalone_excavator_runtime_removed`, and
  `forge_ingests_source_directly` all remain false pending owner approval.
- **Agent Reliability Lab.** Fixtures derive from the action policy declared in `looping-box`
  source; gate coverage is measured per harness (`budget` appears only in `agentic-harness`;
  `review_required` is absent from `sssf`); `components/executive_reporting` is measured to have
  two real consumers — `ai-ethics-comparator` and `writers-room` — so the craft rule retains it and
  demotes nothing. Donor JSON is parsed through a guarded reader: a malformed `smoke.json` yields a
  failed prototype result rather than an exception escaping the wave boundary.
- **Game Design + Simulation.** `G1` fingerprints the 1000 recorded Tucked in Terrors runs into an
  outcome distribution (926 `LOSS_NIGHTFALL`, 74 `PRIMARY_WIN`) and metric tolerances. `G2` is
  `pack_shape_projected`: the donor rows are projected into the Storyweaver pack vocabulary, and no
  parity number is produced at all, because nothing was generated independently to compare against
  (`pack_materialized_on_disk`, `statistical_parity_measured`, and
  `independent_resimulation_verified` are all false). `G3`/`G5` confirm neither Oregon D&D nor
  March Madness references the engine.
- **Accessibility `A6`.** The gate now reads the whole effective extension surface —
  `permissions`, `host_permissions`, `optional_host_permissions`, and `content_scripts[*].matches`.
  `kb-overlay` requests no broad API permission, but it injects on `<all_urls>`, exactly as both
  donors do. The receipt therefore records `consolidation_proposed` with
  `minimized_permissions_verified: false`, `canonical_no_broader_than_donors: true`, and
  `migration_acceptance_verified: false`; narrowing that scope and freezing the donors are both
  outstanding, and the freeze remains an owner action.

Wave counts are unchanged: 43 waves, 5 complete (1 runtime recovery, 4 analysis milestones), 38
prototype checks. What changed is that no prototype check now passes without reading its donor,
and none of them names an outcome it did not produce.

## 2026-08-21 — Cosmetic-Fingerprint Reclassification

Extended the prototype reclassification to every wave whose gate does not read donor content.
An audit of all eighteen adapter gates found that only `A2`, `A3`, `O2`, and `B2` open, execute,
or parse a donor repository. A further nine gates called `get_git_fingerprint()` (or `.is_dir()` /
`.exists()`) on a donor and then evaluated suite-local engines exclusively: `A5`, `O1`, `O3`, `O4`,
`O6`, `B1`, `P1`, `P2`, `P3`, with `B3`, `B4`, and `B6` deriving from `B1`. A fingerprint over a
repository the gate never reads cannot fail when that repository's behavior changes, so it does not
support a parity claim.

`A5` is the illustrative case: its only contact with A11y Kitchen is a fingerprint and a directory
check, while the finding it round-trips is created and evaluated entirely by `AccessibilityEngine`.
It failed the missing-donor probe and therefore looked correctly guarded — failing closed on a
repository that is never read is indistinguishable, from outside, from failing closed on one that
is.

Reclassified to prototype: `A5`, `O1`, `O3`, `O4`, `O6`, `B1`, `B3`, `B4`, `B6`, `P1`, `P2`, `P3`.
Verified analysis milestones are now four (`A1`, `A3`, `O2`, `B2`), prototype checks are
thirty-eight, and complete wave milestones are 5/43. All reclassified waves also had their
`recovery_claim.level` corrected from `parity_verified` to `prototype`; the previous batch retained
a `parity_verified` claim that the raw manifests served over `/api/suites` while the status-derived
views reported a prototype.

The donor-backed migrations these waves describe remain future work. Nothing was retired, and no
source repository was modified.

---

## 2026-08-21 — Suite-Local Prototype Reclassification

Reclassified `A4`, `O5`, `B5`, `P4`, and `P5` from complete analysis milestones to prototype
checks. Their runners exercise suite-local engines, constants, or committed fixtures without
reading a donor repository, so donor fingerprint requirements would be cosmetic rather than
evidence of migration. The verified analysis count is now sixteen, the prototype count is
twenty-six, and complete wave milestones are 17/43. The corresponding donor-backed migrations
remain future work.

`A1` remains an analysis milestone because its intended artifact is a reviewed, hand-authored
parity decision. Its runner checks the document's required structure; it does not execute a donor
or runtime gate. `A4` output now describes the actual 20-case classification and single
suite-local compliant-markup smoke probe instead of claiming 17 candidates and broad false-positive
verification.

---

## 2026-08-20 — Control-Plane Integrity Repair

Fixed a defect that made the documented `wave ... --record` path raise `AttributeError` for all
seventeen Operator OS, Brand + Publishing, and Production House waves. Ephemeral runs were
unaffected, and the existing tests missed it because those waves were only exercised with
`write_evidence=False`. Record-mode coverage now runs every O/B/P wave against a redirected
evidence root.

Rewrote the seventeen O/B/P wave objectives and acceptance criteria to describe what their runners
actually do. Most fingerprint a source repository and then exercise suite-local fixtures; `O2` and
`B2` genuinely read live source; `O5`, `P4`, and `P5` touch no repository at all. Each wave now
carries a `runtime_followup` field recording the real runtime integration its former wording
implied, so narrowing the criteria does not discard the obligation. Wave count is unchanged at 43.

Analysis evidence is now validated for content rather than existence. An analysis claim's
`evidence_basis` names fields its own receipt must carry — top-level keys for a JSON receipt,
literal markers for a prose one — and registry validation fails closed when the receipt does not
contain them. The previous boilerplate basis of `source_inventory, parity_matrix, fixture_catalog`
was shared verbatim by twenty of twenty-one analysis waves and matched almost none of their
evidence. Production House runners now retain the source fingerprints their adapters compute
instead of writing the generated job alone, and `P1`-`P5` evidence was regenerated accordingly.

Verified claims are unchanged: one parity-verified runtime recovery, twenty-one analysis
milestones, zero adopted workflows, zero converged capabilities.

---

## 2026-08-20 — Analysis Milestones: Waves A3-A5, O1-O6, B1-B6, P1-P5

Promoted twenty analysis milestones across four suites, taking wave completion from 2/43 to 22/43.
Accessibility added `A3` keyboard-overlay reconciliation, `A4` rule-candidate evaluation, and `A5`
`a11y kitchen` round-trip. Operator OS added `O1`-`O6`, Brand + Publishing `B1`-`B6`, and
Production House `P1`-`P5`, each backed by a live source adapter and a retained receipt.

These are analysis claims, not runtime recoveries. Each fingerprints or reads its donor sources and
then exercises the suite-local engine; none invokes an external runtime. `A2` remains the sole
parity-verified runtime recovery. Adopted and converged counts remain zero, and 22/43 is a
planning milestone percentage rather than a functionality-recovery score.

Commits: `16da302`, `b87dfbb`, `b9e8ec5`, `ceb9b23`.

---

## 2026-08-20 — 9/10 Recovery Standard Adopted

Adopted a portfolio-wide standard that targets 9/10 recovery of valuable functionality rather than
complete reproduction of historical repositories. Added a machine-validated weighted rubric,
promotion levels from prototype through convergence, tiered suite targets, and explicit resolution
outcomes for intentionally unported behavior.

Reporting now separates the A1 analysis milestone from the A2 runtime recovery. Prototype checks do
not count as recovered functionality, and an environment-blocked gate is neither a pass nor a
product failure. Current claims are one parity-verified runtime recovery, one verified analysis
milestone, zero adopted workflows, and zero converged capabilities.

The A2 promotion now executes WCAG Auditor's authentic `InputAssistanceRule` in Playwright and
compares captured donor outcomes with Ally outcomes for the same representative cases. Registry
validation inspects the retained runtime receipt and fails closed on recovery-policy, tier, rubric,
owner-approval, evidence-basis, or receipt drift. Deep npm, tsx, and browser permission failures now
enter the operational-error channel and report `unverifiable_environment` rather than product
failure.

---

## 2026-08-20 — Horizon 1 Migration: Wave A2 (WCAG 3.3.1 Error Association into Ally) — Local Candidate Hardened

### Outcome

Successfully implemented and hardened the first source-backed migration candidate with four-stage verification, content-addressed dirty-tree provenance, operational error separation, and preserved epistemic source status. Ported the deterministic **WCAG 3.3.1 Error Association** rule from donor [`wcag-auditor`](file:///Users/ryanjohnson/Projects/wcag-auditor) into canonical destination runtime [`allys-tools`](file:///Users/ryanjohnson/Projects/allys-tools).

```text
MIGRATION PROGRESS: 1/43 waves verified (A1); Wave A2 verified as local working-tree candidate (42 prototype/candidate checks passing)
ACCESSIBILITY SUITE: 1/6 waves complete (A1); Wave A2 verified candidate; next: A2 commit / A3
RUNTIME GATES: 127/127 complete Ally tests passing (including 6/6 focused WCAG 3.3.1 tests and 7/7 full-audit tests); TypeScript check clean
CONTROL PLANE: 57/57 unit tests passing; 0 registry errors
EVIDENCE RECEIPT: accessibility/evidence/A2-WCAG-331-EVIDENCE.json (content-addressed candidate receipt with patch & file SHA-256 hashes)
```

### Deliverables & Verifications

1. **Target Runtime Parity Tests ([allys-tools](file:///Users/ryanjohnson/Projects/allys-tools))**:
   - Added [`a11y-tools/tests/wcag-331-error-association.test.ts`](file:///Users/ryanjohnson/Projects/allys-tools/a11y-tools/tests/wcag-331-error-association.test.ts) covering defective and compliant scenarios matching [`A1-parity-cases.json`](file:///Users/ryanjohnson/Projects/suites/accessibility/evidence/A1-parity-cases.json).
   - Added full-audit pipeline test to [`a11y-tools/tests/full-audit.test.ts`](file:///Users/ryanjohnson/Projects/allys-tools/a11y-tools/tests/full-audit.test.ts) verifying that `aria-validator` completes, covers the invalid page, emits the 3.3.1 finding into combined findings, and reports 0 operational errors.
   - Validated complete test suite: 127/127 tests pass and `npm run check` (typecheck + tests) passes cleanly.

2. **Hardened Source Adapter & Evidence Semantics ([suites](file:///Users/ryanjohnson/Projects/suites))**:
   - Implemented [`AccessibilitySourceAdapter`](file:///Users/ryanjohnson/Projects/suites/src/portfolio_suites/adapters/accessibility.py) with four distinct verification stages:
     1. Focused parity gate (6/6 tests).
     2. Full suite & typecheck gate (127/127 tests).
     3. Full-audit integration pipeline gate (7/7 tests, manifest coverage verified).
     4. Direct DOM snapshot evaluation & contract translation with preserved `source_status: "unverified"`, truthful `needs_review: true`, and donor parity comparison.
   - Captures comprehensive dirty-tree provenance: `HEAD`, branch, clean/dirty state, patch SHA-256, lockfile SHA-256, and SHA-256 hashes for all tested files.
   - Separates operational failures (`operational_errors: []`) from assertion outcomes.

3. **Truthful Control Plane State**:
   - Retained Wave `A2` as `"runner_prototyped"` / verified local candidate in [`accessibility/suite.json`](file:///Users/ryanjohnson/Projects/suites/accessibility/suite.json) until Ryan authorizes staging/committing.
   - `suites status` honestly reports `1/43 waves (2.3%)` while the candidate receipt [`A2-WCAG-331-EVIDENCE.json`](file:///Users/ryanjohnson/Projects/suites/accessibility/evidence/A2-WCAG-331-EVIDENCE.json) is fully reproducible and content-addressed.

---

## 2026-08-20 — Truth Model, Evidence Boundary, and Execution Semantics Hardened

### Outcome

Repaired the control plane so passing suite-local prototypes cannot present themselves as completed migrations. Wave execution, CLI exit behavior, API responses, dashboard labels, retained evidence, and AI configuration now use the same fail-closed truth model.

```text
MIGRATION PROGRESS: 1/43 verified (A1); 42/43 reference prototype checks passing
TESTS: 57/57 passing
REGISTRY: 0 errors; 1 expected allys-tools working-tree drift warning
EXECUTION DEFAULT: ephemeral; evidence recording requires explicit authorization
AI BOUNDARY: OpenRouter configured for future hosted-AI roles; no live provider call claimed
```

### Repairs and Alignment

1. **Consistent Wave Result Taxonomy**:
   - Dedicated incomplete runners report `execution_kind: "prototype_check"` and preserve their passing result as `prototype_passed` without increasing verified migration progress.
   - Completed source-backed waves report verified execution; waves without an adapter fail closed as unintegrated; runner exceptions remain execution errors.
   - Portfolio totals now distinguish verified migrations, passing prototypes, failed checks, unintegrated specifications, and execution errors.

2. **Fail-Closed CLI, API, and Dashboard Behavior**:
   - Unknown suites and waves return errors and non-zero CLI status instead of synthetic success.
   - Wave execution is ephemeral by default in both the CLI and dashboard API.
   - Evidence mutation requires `--record` or `record=true`, and the dashboard exposes the result classification instead of displaying every pass as migration completion.

3. **Deterministic Chess Prototype Correctness**:
   - Expanded move evaluation to account for attacked kings, check resolution, castling rook movement and path constraints, en passant state, promotion, and illegal king capture.
   - Added explicit expected-legality outcomes to the fixture corpus and made the M4 prototype gate depend on all cases matching those expectations.
   - Retained the chess evaluator's honest classification as a deterministic reference prototype rather than representing it as an external model or provider run.

4. **Evidence Corrections**:
   - Regenerated affected A6, O5, O6, M4, and M5 artifacts from the repaired runners.
   - Renamed the A6 artifact from an `INSTITUTED` claim to a `PROTOTYPE` artifact so its filename and contents agree with its evidence strength.
   - Preserved historical M1 provider provenance instead of rewriting earlier Anthropic-attributed evidence as OpenRouter execution.

5. **OpenRouter Role Boundary Alignment**:
   - Aligned committed role defaults to `openrouter/auto` while retaining `.env` process overrides for operator-selected models.
   - Kept credentials local, ignored, redacted from diagnostics, and outside retained wave evidence.
   - No live OpenRouter request was needed or claimed for deterministic reference checks.

6. **Verification Expansion**:
   - Increased coverage from 52 to 57 tests across contracts, registry behavior, wave classifications, chess rules, OpenRouter isolation, CLI exit semantics, and dashboard APIs.
   - Verified 57/57 unit tests, zero registry errors, clean Python and JavaScript syntax checks, and zero trailing-whitespace errors.

### Boundaries Preserved

- No canonical donor repository was modified, frozen, retired, or redirected.
- No wave beyond A1 was promoted to verified migration status.
- No credentials were committed or written into evidence.
- No staging, commit, push, deployment, or publication action is part of this milestone.

---

## 2026-08-20 — Portfolio Control Plane & Governance Foundation Established

### Summary
Established the eight-suite portfolio control plane, unified contracts, registry inspection tools, local-first zero-dependency dashboard, and OpenRouter configuration boundary.

```text
STATUS: Control Plane & Prototype Domain Kernels Operational
COVERAGE: 8 Suite Definitions | 6 Shared Contracts | 70 Projects Dispositioned
VERIFICATION: 57/57 Unit Tests PASS | 0 Registry Errors
WAVE VERIFICATION: 1/43 Waves Verified (A1 Parity Matrix); 42 Waves Specified with Prototype Runners
```

### Key Deliverables Established

1. **Portfolio Taxonomy & Structure**:
   - Defined 8 coherent suite boundaries: [Accessibility](file:///Users/ryanjohnson/Projects/suites/accessibility/README.md), [Operator OS](file:///Users/ryanjohnson/Projects/suites/operator-os/README.md), [Brand + Publishing](file:///Users/ryanjohnson/Projects/suites/brand-publishing/README.md), [Production House](file:///Users/ryanjohnson/Projects/suites/production-house/README.md), [Model Behavior Lab](file:///Users/ryanjohnson/Projects/suites/model-behavior-lab/README.md), [Discovery + Decision](file:///Users/ryanjohnson/Projects/suites/discovery-decision/README.md), [Agent Reliability Lab](file:///Users/ryanjohnson/Projects/suites/agent-reliability/README.md), and [Game Design](file:///Users/ryanjohnson/Projects/suites/game-design/README.md).
   - Mapped 70 top-level projects and 35 nested git repositories in [project-ledger.json](file:///Users/ryanjohnson/Projects/suites/portfolio/project-ledger.json) and [nested-repositories.json](file:///Users/ryanjohnson/Projects/suites/portfolio/nested-repositories.json).

2. **Unified Contract System**:
   - Implemented 6 core schemas: `A11yFinding`, `SourceRecord`, `BrandPackage`, `InvestigationRecord`, `ProductionJob`, and `ExperimentRun`.
   - Added automated JSON schema generator and bidirectional schema/contract validation tests.

3. **Control Plane CLI & Dashboard**:
   - Zero-dependency Python standard library CLI: `status`, `list`, `next`, `validate`, `drift`, `inspect`, `contract`, `wave`, `ai-config`, `serve`.
   - Zero-dependency local web dashboard on port 8383 with live SVG dependency graph and ephemeral wave runner triggers.

4. **OpenRouter Configuration Boundary**:
   - Standard-library `.env` parser with process-level overrides and strict fail-closed key validation.
   - Redacted diagnostics and dataclass representations to prevent key leakage.
   - Pinned role routing budgets for orchestrator, analyst, reviewer, creative, and accessibility roles.

5. **Wave Specification & Parity Artifacts**:
   - **A1 Parity Matrix**: Verified rule, crawl, and deliverable parity matrix between `wcag-auditor` and `allys-tools` ([evidence](file:///Users/ryanjohnson/Projects/suites/accessibility/evidence/A1-WCAG-AUDITOR-PARITY.md)).
   - **42 Wave Specifications**: Detailed acceptance criteria and reference prototype runners for incremental source migrations.

6. **Truth-Bound Execution Model**:
   - Separates verified migrations, passing prototype checks, unintegrated specifications, and execution errors across the CLI and dashboard API.
   - Runs wave checks ephemerally by default; evidence replacement requires an explicit `--record` or `record=true` request.
   - Fails closed on unknown waves and failed checks while preserving the verified progress count at 1/43.
