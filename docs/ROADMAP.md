# Portfolio Migration Roadmap

## Program Objective & State

The `/Users/ryanjohnson/Projects/suites` control plane governs portfolio migration under the **9.0/10 Recovery Standard**.

- **Completed Foundation & Milestones**: 5/43 waves verified (1 runtime recovery `A2`, 4 analysis milestones `A1`, `A3`, `O2`, `B2`). Detailed logs and completed foundations are recorded in [CHANGELOG.md](CHANGELOG.md).
- **Remaining Work**: 38 migration waves across 8 suites requiring authentic donor-backed implementation, runtime execution, and parity verification.
- **Current Promotion Target**: 0/58 monitored source repositories drifted on branch, HEAD, and dirty
  count; `allys-tools` clean at `f2b4c6e`. All 58 baselines lack `status_sha256`, so working-tree
  *content* drift is unchecked for every one of them — the zero is a narrower claim than it reads.

### Machine-Checked State

These figures are restated from the registry and are verified against it by
`tests/test_docs.py`; they are scheduling and inventory metrics, not the recovery score.

- **70 Top-level projects** dispositioned across 8 suite boundaries and independent/archive containers.
- **43 Migration wave specifications** defined; wave milestone progress is 5/43.
- **38/43 source-backed prototype checks** passing. A prototype check proves only the concept its
  runner exercised; none of them counts as recovered functionality.
- **6 Shared contracts implemented**: `A11yFinding`, `BrandPackage`, `ExperimentRun`, `InvestigationRecord`, `ProductionJob`, `SourceRecord`.

---

## Immediate Promotion Queue

| Suite | Verified | Next Target | Evidence Required for Promotion |
|---|---:|---|---|
| Accessibility | 3/6 | `A4` | Run candidate rules against real donor inputs; retain per-rule donor/destination parity evidence |
| Operator OS | 1/6 | `O1` | Connect real dotfiles capture through PKos; retain an authentic Observer projection receipt |
| Brand + Publishing | 1/6 | `B1` | Compile a BrandPackage from real Brand Maker source; exercise the actual consumer boundary |
| Production House | 0/5 | `P1` | Read a real Groundwire workflow; retain authentic job and QC outputs |
| Model Behavior Lab | 0/5 | `M1` | Authentic normalized run records from OpenRouter or an identified local model vs recorded baseline |
| Discovery + Decision | 0/5 | `D1` | Executed SIF and Forge runs compared stage by stage with call-budget accounting |
| Agent Reliability | 0/5 | `R1` | Real harness executions with retained inputs, outputs, failures, and environment metadata |
| Game Design | 0/5 | `G1` | Materialized pack executed in Storyweaver and compared to fresh donor simulation |

---

## Remaining Work by Horizon

### Horizon 1 — Ally Accessibility Suite
- **Destination Anchor:** `allys-tools`
- **Completed:** `A1` (WCAG parity matrix), `A2` (WCAG 3.3.1 error association runtime recovery), `A3` (keyboard overlay reconciliation).
- **Remaining Waves:**
  - **`A4` — Rule Candidate Ports:** Port remaining heuristic and narrow rule candidates from `wcag-auditor` into `allys-tools` with regression evidence and live donor/destination parity verification.
  - **`A5` — Finding Ingestion Round-Trip:** Ingest `A11yFinding` contracts through the `a11y-kitchen` interactive teaching surface using authentic donor fixtures.
  - **`A6` — Keyboard Overlay Consolidation:** Narrow canonical content-script host permissions below `<all_urls>`, institute `kb-overlay`, and present donor freeze recommendations for owner approval.

### Horizon 2 — Operator OS Migration
- **Destination Anchors:** `dotfiles` + `PKos` + `obsidian-observer`
- **Completed:** `O2` (Ryos core file and master-plan inventory against dotfiles and Observer).
- **Remaining Waves:**
  - **`O1` — Dotfiles Capture to PKos CAS & Observer Projection:** Ingest real captured source through live `PKos` runtime and land projected note in actual `obsidian-observer` vault with fenced re-ingestion.
  - **`O3` — JARVIS System Action Lifecycle:** Drive real JARVIS actions through preview, approval, execution receipt, failure, and recovery over owned system APIs.
  - **`O4` — Daily Intake Stream Scaling:** Run real day-to-day daily-notes stream through live `PKos` capture path and scale multi-source batching.
  - **`O5` — Ryos Port Execution & Feature Disposition:** Execute assigned ports in `dotfiles` backed by tests, name superseded features, and retire duplicate launcher code.
  - **`O6` — Generalized JARVIS Lifecycle:** Generalize modeled action pattern to multiple commands with full approval and receipt lifecycle against live side effects.

### Horizon 3 — Brand + Publishing Migration
- **Destination Anchors:** `brand-maker-spec` + `cyborg`
- **Completed:** `B2` (Brand Workshop 9-phase mapping onto workspace state and gates).
- **Remaining Waves:**
  - **`B1` — BrandPackage Export & Downstream Consumption:** Export compiled `BrandPackage` from real Brand Maker runtime and consume it in downstream `cyborg` publishing pipeline.
  - **`B3` — Sourced Draft to VCC Review Pipeline:** Route real draft through actual VCC review path and produce authentic distribution receipts.
  - **`B4` — Cross-Consumer Boundary Verification:** Wire external consumer outside repository and verify version-pinning and mutation-protection across process boundaries.
  - **`B5` — Brand Maker Intake State Machine Migration:** Move 9-phase state machine into real Brand Maker application and reconcile duplicate intake UX.
  - **`B6` — Human Approval Gate Workflow:** Replace simulated approval gate with real human signoff in VCC distribution flow.

### Horizon 4 — Production House & Model Behavior Lab

#### Production House
- **Destination Anchors:** `groundwire` + `writers-room` + `elevenlabs-screenplay-formatter`
- **Completed:** None (0/5 complete).
- **Remaining Waves:**
  - **`P1` — Groundwire Audio Fingerprinting & Episode Pipeline:** Map real Groundwire episode workflow and QC/output stages into `ProductionJob` from real episode artifacts.
  - **`P2` — Screenplay Synthesis & Formatter Parity:** Invoke `elevenlabs-screenplay-formatter` on real script slice and verify parity/failure recovery.
  - **`P3` — Writers Room Story-State Handoff:** Take story state from real Writers Room runtime through to derived output with job receipt.
  - **`P4` — Investigative Documentary Episode Pipeline:** Drive multi-track and sound-design pipeline from real documentary episode fixtures.
  - **`P5` — Collaborative Story-State Event Stream:** Map real Writers Room revision history and final room signoff into canonical `ProductionJob` event stream.

#### Model Behavior Lab
- **Destination Anchors:** `ai-ethics-comparator` + `ai-chess`
- **Completed:** None (0/5 complete).
- **Remaining Waves:**
  - **`M1` — Live Scenario Benchmark Execution:** Re-run donor experiment runner live through OpenRouter/local models instead of normalizing stored result files.
  - **`M2` — Canonical Comparator Kernel Extraction:** Implement shared slice over comparator kernel and eliminate duplicated donor subsystems.
  - **`M3` — Full Multi-Ply Chess Game State Evaluation:** Replay whole recorded matches once engine can apply moves (beyond opening ply).
  - **`M4` — Tactical Puzzle & Match Scoring Benchmark:** Score full match transcripts and tactical puzzles across models.
  - **`M5` — Versioned Benchmark Corpus Verification:** Prove manifest re-runs historical evaluations end to end from pinned hashes.

### Horizon 5 — Discovery, Agent Reliability & Game Design

#### Discovery + Decision
- **Destination Anchors:** `sif` + `forge` + `insight-excavator`
- **Completed:** None (0/5 complete).
- **Remaining Waves:**
  - **`D1` — SIF to Forge Stage Parity Execution:** Execute both runtimes on live questions and diff stage outputs with call-budget accounting.
  - **`D2` — Live Red-Team Investigation Mode:** Run red-team stage live inside Forge with consent and resume gates.
  - **`D3` — Cited Discovery & Uncertainty Engine:** Run Excavator discovery path to produce real claims, novelty, and uncertainty measures.
  - **`D4` — Deep Analogy Synthesis:** Run analogy synthesis live in deep mode with real call-budget accounting.
  - **`D5` — Direct Forge Ingestion & Excavator Retirement:** Ingest Excavator sources directly into Forge; obtain owner approval before retiring standalone runtime.

#### Agent Reliability Lab
- **Destination Anchors:** `looping-box` + `sssf` + `agentic-harness`
- **Completed:** None (0/5 complete).
- **Remaining Waves:**
  - **`R1` — Live Agent Loop Adversarial Execution:** Execute adversarial fixtures against live agent loops instead of scoring declared policy.
  - **`R2` — Multi-Harness Runtime Execution:** Run fixture battery inside each harness runtime (`looping-box`, `sssf`, `agentic-harness`).
  - **`R3` — Shared Component Runtime Verification:** Confirm each counted consumer imports shared components at runtime.
  - **`R4` — 2-Consumer Craft Rule Enforcement:** Audit package consumers and demote single-consumer packages back to donor repositories.
  - **`R5` — Deterministic Agent Curriculum Scoring:** Execute mined AI Staff / prompt-chain test cases and score real agent behavior.

#### Game Design + Simulation
- **Destination Anchors:** `storyweaver` + `tucked-in-terrors`
- **Completed:** None (0/5 complete).
- **Remaining Waves:**
  - **`G1` — Live Simulation Parity Re-Run:** Re-run donor simulator to regenerate fresh distributions rather than fingerprinting retained runs.
  - **`G2` — Storyweaver Reference Pack Materialization:** Materialize pack on disk, run in Storyweaver, and compare generated statistics to donor sample.
  - **`G3` — Authored-Game Boundary Decoupling:** Formally decouple Oregon D&D and audit pack export boundaries.
  - **`G4` — Procedural Adventure Pack Generation:** Generate adventure packs through Storyweaver itself and validate game design slot schemas.
  - **`G5` — March Madness Sports Simulator Integration:** Formally audit authored-game boundary for March Madness simulation.

---

## Truth and Promotion Rules

The control plane uses the promotion model in the [9/10 recovery standard](RECOVERY-STANDARD.md):

1. **Intended Work vs Evidence:** A wave specification records intended work; it is not evidence that the migration exists.
2. **Prototype Boundary:** A passing reference prototype proves only the suite-local contract or fixture behavior exercised by that runner.
3. **Claim Separation:** Analysis milestones and runtime recoveries are reported separately.
4. **Promotion Sequence:** Runtime promotion proceeds through `prototype` → `source_verified` → `parity_verified` → `adopted` → `converged`.
5. **Adoption Standard:** Adoption requires at least three authentic accepted uses across distinct inputs or days.
6. **Donor Freezes & Retirement:** Donor repositories are not frozen, retired, or redirected until verified parity exists and the owner explicitly authorizes that action.
7. **Attribution & AI Routing:** Historical provider evidence remains attributed to the provider that actually produced it. Future hosted-AI execution routes through OpenRouter, while deterministic checks remain local.
8. **Ephemeral Execution:** Wave execution is ephemeral by default. Replacing evidence requires `--record` in the CLI or `record=true` through the dashboard API.
9. **Receipt Truthfulness:** A receipt's status names what the gate performed, never the wave's objective. A gate that reads donor files says so; it does not report discovery, unification, parity, consolidation, or retirement it did not carry out.
10. **Receipt Invariants:** Retained receipts are re-validated by `validate`, so a prototype receipt cannot drift out of agreement with its declared claim and still report green.

---

## Verification Commands

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites wave --all
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A4 --record --full
PYTHONPATH=src python3 -m portfolio_suites ai-config
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

> [!TIP]
> `wave --all` is a non-mutating portfolio check. Use the targeted `--record` form only after reviewing a successful source-backed result intended to replace retained evidence.

