# Portfolio Migration Roadmap

## Current Program State

The `/Users/ryanjohnson/Projects/suites` control plane is established as the portfolio governance foundation:

```text
CONTROL PLANE FOUNDATION:
- 8/8 Suite boundaries defined with clear user promises and canonical anchors
- 6 Shared contracts implemented (A11yFinding, SourceRecord, BrandPackage, InvestigationRecord, ProductionJob, AgentRun)
- 70 Top-level projects dispositioned across suites and independent containers
- Control-plane tests cover contracts, registry, engines, OpenRouter isolation, CLI, and dashboard APIs
- Zero-dependency CLI and local web dashboard operational
- 43 Migration wave specifications defined with prototype reference runners
- Verified claims: ten analysis milestones (A1, A3-A5, O1-O6) and one runtime recovery (A2)
- Portfolio wave milestones: 11/43 complete; 32/43 reference prototype checks
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

---

## Current Promotion Queue

| Suite | Verified | Next promotion target | Evidence required for promotion |
|---|---:|---|---|
| Accessibility | 5/6 | `A6` | Owner-controlled consolidation review and 3 verified authentic uses for convergence |
| Operator OS | 6/6 | Complete | All 6 analysis waves verified across dotfiles, PKos, Observer, JARVIS, and Ryos |
| Brand + Publishing | 0/6 | `B1` | A real `BrandPackage` compiled from source intake and consumed by the publishing boundary |
| Production House | 0/5 | `P1` | Groundwire source fingerprints and reproducible audio-processing output |
| Model Behavior Lab | 0/5 | `M1` | Authentic normalized run records from OpenRouter or an identified local model |
| Discovery + Decision | 0/5 | `D1` | Source-backed SIF investigation records and Forge challenge results |
| Agent Reliability | 0/5 | `R1` | Real harness executions with retained inputs, outputs, failures, and environment metadata |
| Game Design | 0/5 | `G1` | Canonical source fingerprint plus reproducible rules-simulation output |

---

## Migration Horizons

Migration proceeds suite by suite, requiring authentic source-backed execution, reproducible gates, and donor parity evidence before any runtime is retired.

### Horizon 1 — Ally Accessibility Suite (In Progress)
- **Target Anchor:** `allys-tools`
- **Current State:** `A1` is a verified analysis milestone; `A2` is a parity-verified runtime recovery at clean `allys-tools` commit `f2b4c6e`.
- **Next Wave (A3):** Complete genuine browser-level reconciliation of the three keyboard overlays.
- **Subsequent Waves:**
  - `A3`: Genuine feature, permission, and runtime reconciliation of three keyboard overlays (`kb-overlay`, `keyboard-nav-overlay`, `keyboard-nav-overlay-94bf7e`).
  - `A4`: Port remaining rule candidates with regression fixtures.
  - `A5`: Round-trip contract through `a11y kitchen`.
  - `A6`: Freeze duplicate donor repositories upon verified parity.

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

### Horizon 5 — Discovery, Agent Reliability & Game Design
- **Discovery + Decision (`breaking-chains` anchor):** SIF analogy forge records and Forge red-teaming.
- **Agent Reliability (`looping-box` anchor):** Adversarial harness test runs across `SSSF` and curriculum fixtures.
- **Game Design (`storyweaver` anchor):** Rules simulation and playable adventure pack compilations.

---

## Verification Commands

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites wave --all
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --record
PYTHONPATH=src python3 -m portfolio_suites ai-config
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`wave --all` is a non-mutating portfolio check. Use the targeted `--record` form only after reviewing a successful source-backed result that is intended to replace retained evidence.
