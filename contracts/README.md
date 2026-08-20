# Shared Contracts

These are the only cross-suite data shapes in the foundation release. They are intentionally small
and versioned independently of any app's internal models.

| Contract | Canonical owner | Consumers |
|---|---|---|
| `A11yFinding` | Accessibility | audit, teaching, overlays, tickets, regression reports |
| `SourceRecord` | Operator OS / PKOS | every suite that must cite or preserve inputs |
| `BrandPackage` | Brand + Publishing | Cyborg, publishers, production jobs, site fixtures |
| `ProductionJob` | Production House | audio, video, story, game, and media adapters |
| `ExperimentRun` | Model Behavior Lab | benchmarks, reliability evals, simulations |
| `InvestigationRecord` | Discovery + Decision | Forge, SIF stages, cited discovery |

The JSON Schemas document interchange. `portfolio_suites.contracts` supplies the dependency-free
runtime invariants used by this control plane. Apps may use stricter internal schemas but cannot
silently weaken these boundary requirements.

