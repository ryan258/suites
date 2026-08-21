# Portfolio Migration Roadmap

## Current Program State

The `/Users/ryanjohnson/Projects/suites` control plane is established as the portfolio governance foundation:

```text
CONTROL PLANE FOUNDATION:
- 8/8 Suite boundaries defined with clear user promises and canonical anchors
- 6 Shared contracts implemented (A11yFinding, SourceRecord, BrandPackage, InvestigationRecord, ProductionJob, ExperimentRun)
- 70 Top-level projects dispositioned across suites and independent containers
- Control-plane tests cover contracts, registry, engines, OpenRouter isolation, CLI, and dashboard APIs
- Zero-dependency CLI and local web dashboard operational
- 43 Migration wave specifications defined; every wave runner reads donor content through one of
  8 source adapters, and every wave declares a recovery claim and a runtime follow-up
- Verified claims: four analysis milestones (A1, A3, O2, B2) and one runtime recovery (A2)
- Portfolio wave milestones: 5/43 complete; 38/43 source-backed prototype checks
- `validate` re-checks every declared claim and its retained receipt, not only completed waves
- Recovery target: 9/10 for valuable functionality; wave completion is not the recovery score
- Wave checks execute ephemerally by default; evidence is written only by explicit request
- Current monitored source baseline: 0/58 repositories drifted; `allys-tools` is clean at the recorded A2 commit
```

---

## Truth and Promotion Rules

The control plane uses the promotion model in the [9/10 recovery standard](RECOVERY-STANDARD.md):

1. A wave specification records intended work; it is not evidence that the migration exists.
2. A passing reference prototype proves only the suite-local contract or fixture behavior exercised by that runner.
3. Analysis milestones and runtime recoveries are reported separately.
4. Runtime promotion proceeds through `source_verified`, `parity_verified`, `adopted`, and `converged`.
5. Adoption requires at least three authentic accepted uses across distinct inputs or days.
6. Donor repositories are not frozen, retired, or redirected until verified parity exists and the owner explicitly authorizes that action.
7. Historical provider evidence remains attributed to the provider that actually produced it. Future hosted-AI execution routes through OpenRouter, while deterministic checks remain local.
8. Wave execution is ephemeral by default. Replacing evidence requires `--record` in the CLI or `record=true` through the dashboard API.
9. A receipt's status names what the gate performed, never the wave's objective. A gate that reads
   donor files says so; it does not report discovery, unification, parity, consolidation, or
   retirement it did not carry out.
10. Retained receipts are re-validated by `validate`, so a prototype receipt cannot drift out of
    agreement with its declared claim and still report green.

---

## Current Promotion Queue

| Suite | Verified | Next promotion target | Evidence required for promotion |
|---|---:|---|---|
| Accessibility | 3/6 | `A4` | Run candidate rules against real donor inputs, then retain per-rule donor/destination parity evidence |
| Operator OS | 1/6 | `O1` | Connect real dotfiles capture through PKos and retain an authentic Observer projection receipt |
| Brand + Publishing | 1/6 | `B1` | Compile a BrandPackage from real Brand Maker source and exercise the actual consumer boundary |
| Production House | 0/5 | `P1` | Read a real Groundwire workflow and retain authentic job and QC outputs |
| Model Behavior Lab | 0/5 | `M1` | Authentic normalized run records from OpenRouter or an identified local model; the current gate normalizes a *recorded* donor result |
| Discovery + Decision | 0/5 | `D1` | Executed SIF and Forge runs compared stage by stage; the current gate maps retained artifacts |
| Agent Reliability | 0/5 | `R1` | Real harness executions with retained inputs, outputs, failures, and environment metadata; the current gate reads harness source |
| Game Design | 0/5 | `G1` | A materialized pack executed in Storyweaver and compared to a fresh donor simulation; the current gate summarizes a recorded run |

---

## Migration Horizons

Migration proceeds suite by suite, requiring authentic source-backed execution, reproducible gates, and donor parity evidence before any runtime is retired.

### Horizon 1 — Ally Accessibility Suite (In Progress)
- **Target Anchor:** `allys-tools`
- **Current State:** `A1` and `A3` are verified analysis milestones; `A1` is a reviewed hand-authored document, not an executed gate. `A2` is a parity-verified runtime recovery at clean `allys-tools` commit `f2b4c6e`. `A4`, `A5`, and `A6` are prototype checks.
- **Next Wave (A4):** Read real WCAG Auditor rule inputs and retain per-rule donor/destination parity evidence. `A6` remains behind that migration and owner convergence approval.
- **Accessibility Wave Notes:**
  - `A3`: Feature, permission, and runtime reconciliation of three keyboard overlays (`kb-overlay`, `keyboard-nav-overlay`, `keyboard-nav-overlay-94bf7e`).
  - `A4`: Committed rule-candidate fixtures classified, with one suite-local compliant-markup smoke probe.
  - `A5`: Round-trip contract through `a11y kitchen`.
  - `A6`: Records `consolidation_proposed`. `kb-overlay` requests no broad API permission but
    injects on `<all_urls>`, exactly as both donors do, so `minimized_permissions_verified` is
    false. Narrowing that scope and freezing the donors are both outstanding, and the freeze
    remains an owner action.

### Horizon 2 — Operator OS Migration
- **Target Anchors:** `dotfiles` + `PKos`
- **Scope:**
  - `O1`: Connect real `dotfiles` capture into `PKos` content-addressed storage and verified `obsidian-observer` non-reingestion projections.
  - `O2`: Full feature inventory of `ryos` and `master-upgrade-plan` against `dotfiles`.
  - `O3`: Real JARVIS action preview/approval execution receipts against local system services.
  - `O4`–`O6`: Daily intake stream scaling and retirement of duplicate launcher code.

### Horizon 3 — Brand + Publishing Migration
- **Target Anchors:** `brand-maker-spec` + `cyborg`
- **Scope:**
  - `B1`: Real `BrandPackage` compilation from `brand-maker` into `cyborg` publishing pipeline.
  - `B2`–`B3`: VCC claim-verification and automated distribution gates.
  - `B4`–`B6`: Multi-consumer delivery verification and human gate release workflows.

### Horizon 4 — Production House & Model Behavior Lab
- **Production House (`production-house` anchor):** Real Groundwire audio fingerprinting, Writers Room event streaming, and documentary job pipelines.
- **Model Behavior Lab (`ai-strength-comparator` anchor):** Real benchmark executions against OpenRouter and identified local models with retained inputs, provider receipts, and versioned corpus manifests. The deterministic chess move validator remains a reference prototype until it is validated against canonical benchmark sources and promoted through the same evidence gate.
  - **Current prototype state:** `M1` normalizes one recorded `ai-ethics-comparator` result into
    `ExperimentRun` with field parity. `M2` is an extraction *matrix*, not an extraction: the four
    subsystems each comparator still duplicates are counted, with `canonical_slice_implemented`
    false. `M3`/`M4` verify recorded `ai-chess` openings at first ply only, because the engine
    judges legality but cannot yet apply a move. `M5` pins the donor corpora by content hash.

### Horizon 5 — Discovery, Agent Reliability & Game Design
- **Discovery + Decision (`breaking-chains` anchor):** SIF analogy forge records and Forge red-teaming.
  - **Current prototype state:** `D1` maps real SIF phase nodes to Forge stages using the donors'
    own call budgets; `D2`/`D4` carry recorded red-team and analogy artifacts into budgeted
    `InvestigationRecord`s. `D3` retains byte-anchored excerpts and a measured lexical overlap and
    makes no novelty, uncertainty, or semantic-discovery claim. `D5` is `retirement_proposed`: the
    Excavator runtime is untouched and owner approval is outstanding.
- **Agent Reliability (`looping-box` anchor):** Adversarial harness test runs across `SSSF` and curriculum fixtures.
  - **Current prototype state:** fixtures derive from the action policy declared in `looping-box`
    source, and gate coverage is measured per harness from source rather than execution (`budget`
    appears only in `agentic-harness`; `review_required` is absent from `sssf`).
    `components/executive_reporting` has two measured consumers, so the craft rule retains it.
- **Game Design (`storyweaver` anchor):** Rules simulation and playable adventure pack compilations.
  - **Current prototype state:** `G1` fingerprints 1000 recorded Tucked in Terrors runs into an
    outcome distribution and metric tolerances. `G2` is a shape projection into the Storyweaver
    pack vocabulary and reports no parity number at all, because nothing was generated
    independently to compare against. `G3`/`G5` measure zero engine coupling in the authored games.

---

## Verification Commands

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites wave --all
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --record --full
PYTHONPATH=src python3 -m portfolio_suites ai-config
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`wave --all` is a non-mutating portfolio check. Use the targeted `--record` form only after reviewing a successful source-backed result that is intended to replace retained evidence.
