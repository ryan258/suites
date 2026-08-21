# Portfolio Suites — Changelog & Milestone History

This document records genuine, verified milestones for the `/Users/ryanjohnson/Projects/suites` portfolio control plane.

---

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
