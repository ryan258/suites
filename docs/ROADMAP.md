# Portfolio Migration Roadmap

## Program Objective & State

The `/Users/ryanjohnson/Projects/suites` control plane governs portfolio migration under the **9.0/10 Recovery Standard**.

- **Completed Foundation & Milestones**: 43/43 waves verified (1 runtime recovery `A2`, 42 analysis milestones). Detailed logs and completed foundations are recorded in [CHANGELOG.md](CHANGELOG.md).
- **Remaining Work**: 0 remaining migration wave specifications; all 43 milestone wave specifications verified.
- **Current Promotion Target**: `allys-tools`, clean at `f2b4c6e` as of the snapshot below.
  Live drift is deliberately not restated in this file. Every other figure here is registry-derived
  and pinned by `tests/test_docs.py`; drift is filesystem state, so a count written here is the one
  number no gate can hold honest and it rots silently between edits. The CLI is the only current
  source: `PYTHONPATH=src python3 -m portfolio_suites drift`.
- **Baseline snapshot (2026-08-22)**: 0/58 monitored source repositories drifted *at snapshot time*.
  All 58 baselines carry `status_sha256` as of that date, so working-tree *content* drift is checked
  alongside branch, HEAD, and dirty count — the zero was the full claim it reads as, on that date.
  Five repos (`alias-scanner`, `code-tutorial-builder`, `cyborg-agent`, `obsidian-observer`, `sif`)
  had gone from 1 dirty item to 0 since the 2026-08-19 snapshot and were re-baselined by owner
  instruction via `suites baseline --accept`.

### Machine-Checked State

These figures are restated from the registry and are verified against it by
`tests/test_docs.py`; they are scheduling and inventory metrics, not the recovery score.

- **70 Top-level projects** dispositioned across 8 suite boundaries and independent/archive containers.
- **43 Migration wave specifications** defined; wave milestone progress is 43/43.
- **6 Shared contracts implemented**: `A11yFinding`, `BrandPackage`, `ExperimentRun`, `InvestigationRecord`, `ProductionJob`, `SourceRecord`.

Milestone progress above is the scheduling axis. What those milestones demonstrated is the
promotion axis, and it is reported separately because the two move independently — 43/43 complete
coexists with 4 claims that have only exercised a suite-owned fixture:

- **4/43 prototype-level claims** — suite-owned fixture or reference logic only (`A5`, `B3`, `B4`, `B6`).
- **1/43 reviewed historical analysis** — `A1`, a hand-authored decision whose structure is checked.
- **37/43 source-inspected claims** — donor source or retained artifacts parsed, not executed.
- **0/43 source-executed claims** — `source_executed` and above are runtime-only rungs. `O1`'s
  gate does import and run authentic donor PKos code, but its retained analysis receipt records
  what that code produced rather than the invocation itself, so the claim is capped at
  `source_inspected` until `O1` is re-declared as a runtime claim carrying a
  `portfolio-runtime-source-v1` receipt.
- **1/43 parity-verified runtime recoveries** — `A2`.
- **0 adopted, 0 converged, 0 resolved.**
- **42/43 completed waves still owe a live run** recorded in `runtime_followup`.

---

## Functional Launchpad Surface

The local CLI and browser launchpad now expose all 50 reviewed engine actions, strict preflighted
action chains, the contract workbench, manifest and evidence views, project inventory, drift and
validation reports, ephemeral wave execution, and the optional free-first OpenRouter assistant.
The browser never receives the provider credential, uses no remote font or script dependency, and
labels provider output as model-assisted and human-review-required.

Operator OS also has concrete local handlers for bounded secret audit, deterministic backup,
additive note sync, and reversible cache rotation. Write paths stay locked behind independently
issued, exact-payload, single-use approvals; the launchpad cannot mint its own authority.

This completes the launchpad implementation surface. It does not change the recovery ledger below:
provider guidance is not evidence, fixture execution is not donor-runtime recovery, and a safe
handler existing is not adoption.

---

## Immediate Promotion Queue

| Suite | Verified | Next Target | Evidence Required for Promotion |
|---|---:|---|---|
| Accessibility | 6/6 | complete | All 6 wave milestones verified |
| Operator OS | 6/6 | complete | All 6 wave milestones verified |
| Brand + Publishing | 6/6 | complete | All 6 wave milestones verified |
| Production House | 5/5 | complete | All 5 wave milestones verified |
| Model Behavior Lab | 5/5 | complete | All 5 wave milestones verified |
| Discovery + Decision | 5/5 | complete | All 5 wave milestones verified |
| Agent Reliability | 5/5 | complete | All 5 wave milestones verified |
| Game Design | 5/5 | complete | All 5 wave milestones verified |

---

## Remaining Work — Runtime Follow-Up

All 43 migration wave specifications are verified, so no wave remains scheduled. That is a
scheduling metric, not the recovery score. The portfolio still reads **0 adopted, 0 converged**:
42 of the 43 verified waves are analysis milestones, and each carries a `runtime_followup`
obligation recorded in its wave manifest. Only `A2` (WCAG 3.3.1 error association into
`allys-tools`) is a verified runtime recovery.

The remaining work is discharging those obligations, per suite:

| Suite | Waves | Follow-ups outstanding | Nature of the outstanding work |
|---|---|---|---|
| Accessibility | 6/6 waves | 5 outstanding | Port evaluated rules into the TypeScript runtime; verify overlay consolidation in a real browser; obtain owner approval before any donor freeze. |
| Operator OS | 6/6 waves | 6 outstanding | Execute the assigned Ryos ports in `dotfiles` with tests; scale live PKos intake into the permanent vault; drive JARVIS actions against real side effects. |
| Brand + Publishing | 6/6 waves | 6 outstanding | Export from the real Brand Maker runtime into a consumer outside this repo; implement the mapped phase gates; replace the simulated approval gate with human signoff. |
| Production House | 5/5 waves | 5 outstanding | Invoke the formatter and Groundwire render on the hashed episode scripts; take Writers Room story state through the live runtime including signoff. |
| Model Behavior Lab | 5/5 waves | 5 outstanding | Re-run donor experiment runners live; implement the shared comparator slice and delete the duplicated subsystems; replay whole matches. |
| Discovery + Decision | 5/5 waves | 5 outstanding | Execute SIF and Forge on the same question and diff stages; run red-team and analogy stages live with budget accounting. |
| Agent Reliability | 5/5 waves | 5 outstanding | Execute fixtures against live agent loops inside each harness runtime; confirm runtime imports of shared components. |
| Game Design | 5/5 waves | 5 outstanding | Re-run the donor simulator; materialize and run packs in Storyweaver; compare independently generated statistics. |

Each obligation's exact text is the `runtime_followup` field of its wave in that suite's
`suite.json`, and is read back by `validate`. Promotion past `source_inspected` requires the
obligation discharged, not the wave marked complete.

---

## Truth and Promotion Rules

The control plane uses the promotion model in the [9/10 recovery standard](RECOVERY-STANDARD.md):

1. **Intended Work vs Evidence:** A wave specification records intended work; it is not evidence that the migration exists.
2. **Prototype Boundary:** A passing reference prototype proves only the suite-local contract or fixture behavior exercised by that runner.
3. **Claim Separation:** Analysis milestones and runtime recoveries are reported separately.
4. **Promotion Sequence:** Runtime promotion proceeds through `prototype` → `source_inspected` → `source_executed` → `parity_verified` → `adopted` → `converged`. `source_verified` is retired: one name for three depths of evidence is how a report stays internally consistent while overstating what was demonstrated, and the staged registry rejects it.
5. **Adoption Standard:** Adoption requires at least three authentic accepted uses across distinct inputs or days.
6. **Donor Freezes & Retirement:** Donor repositories are not frozen, retired, or redirected until verified parity exists and the owner explicitly authorizes that action.
7. **Attribution & AI Routing:** Historical provider evidence remains attributed to the provider that actually produced it. Optional hosted-AI assistance routes through the free-only OpenRouter policy by default, stays labeled `model_assisted`, and never substitutes for deterministic or runtime evidence.
8. **Ephemeral Execution:** Wave execution is ephemeral by default. Replacing evidence requires `--record` in the CLI or `record=true` through the dashboard API.
9. **Receipt Truthfulness:** A receipt's status names what the gate performed, never the wave's objective. A gate that reads donor files says so; it does not report discovery, unification, parity, consolidation, or retirement it did not carry out.
10. **Receipt Invariants:** Retained receipts are re-validated by `validate`, so a prototype receipt cannot drift out of agreement with its declared claim and still report green.

---

## Verification Commands

```bash
cd /Users/ryanjohnson/Projects/suites
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate --fast
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites wave --all --no-record
PYTHONPATH=src python3 -m portfolio_suites ai --status --json
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --record --full
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Opt-in fail-closed distribution packaging gate
SUITES_WHEEL_SMOKE=1 PYTHONPATH=src python3 -m unittest tests/test_wheel_smoke.py -v
```

> [!TIP]
> `wave --all` is a non-mutating portfolio check. Use the targeted `--record` form only after reviewing a successful source-backed result intended to replace retained evidence.
