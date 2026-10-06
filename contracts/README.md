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

## Compatibility rules (v1 freeze)

- **Additive, compatible:** a new optional field, or a new enum value that existing consumers can
  ignore. Readers must tolerate unknown fields. `schema_version` stays `1.0.0` until a breaking change.
- **Breaking:** removing or renaming a field, making an optional field required, narrowing a type,
  enum, pattern, or range, or changing the meaning of an existing value. A breaking change needs a
  new `schema_version`, reopens the contract freeze, and invalidates the runtime and adoption
  evidence that used the old shape until it is repeated.
- **Security fixes:** tightening validation to reject unsafe input is allowed in a patch even if it
  rejects previously accepted payloads; record it in `docs/CHANGELOG.md`.
- **Invalid examples:** `tests/test_contracts.py::test_every_required_field_and_version_is_enforced`
  is the canonical negative set: for every contract, each required field removed, and a wrong
  `schema_version`, must be rejected.

