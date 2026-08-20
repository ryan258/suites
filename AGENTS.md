# AGENTS.md - Operational & Test Economy Guidelines for Suites Control Plane

> **For AI Assistants & Subagents:** This document defines the operating rules, test economy discipline, and execution boundaries for `/Users/ryanjohnson/Projects/suites`. Read and adhere to these guidelines on every task.

---

## 1. Core Principle: Test Economy & Cost Discipline

Running tests, subagents, and heavy external runtimes consumes time, tokens, and compute. **Tests are not free.** Do not reflexively run full test suites or multi-stage external test runners on minor incremental changes.

### Execution Hierarchy (From Cheapest to Most Expensive)

1. **Level 0: Schema & Registry Fast-Path (<100ms)**
   - Run `PYTHONPATH=src python3 -m portfolio_suites validate` to verify contracts, suite schemas, and file boundaries.
   - Use this for syntax, schema, or registry manifest verification.

2. **Level 1: Targeted Single-Test Execution (<500ms)**
   - When editing a specific engine, adapter, or contract, run **only** the relevant test class or method:
     ```bash
     PYTHONPATH=src python3 -m unittest tests.test_engines.EngineTests.test_operator_os_adapter
     ```
   - Do **NOT** invoke `unittest discover -s tests` for localized changes.

3. **Level 2: Focused Wave Gate Probes (<1s)**
   - Test a single wave in isolation without re-running other suites:
     ```bash
     PYTHONPATH=src python3 -m portfolio_suites wave <suite_id> <wave_id>
     ```
   - Only supply `--record` when generating intentional milestone evidence.

4. **Level 3: Full Test Suite (`discover`) — Milestone Only (~12s+)**
   - Reserve `PYTHONPATH=src python3 -m unittest discover -s tests` **strictly** for:
     - End-of-horizon completion.
     - Final validation before handing off or committing.
   - **Rule:** Never execute back-to-back full discover runs if no code has changed between turns.

5. **Level 4: External Project & Subprocess Gates (Heavy / Long-Running)**
   - Commands that shell out to Node/npm/Playwright in external repositories (e.g. `allys-tools`, `wcag-auditor`) or make network requests must use fast-path/dry-run options during development.
   - Only execute full multi-stage external suites when explicitly recording milestone migration receipts.

---

## 2. Operating Context & Architecture Invariants

- **Architecture:** Local-first, zero-dependency Python stdlib control plane governing 70 repositories across 8 suites.
- **Contract Enforcement:** All inter-suite data exchange uses versioned JSON contracts (`SourceRecord`, `BrandPackage`, etc.) validated by `portfolio_suites.contracts`.
- **Fail-Closed Boundaries:** Unapproved destructive or mutating actions must fail closed without manufacturing synthetic human approval tokens.
- **Immutable Provenance:** Retain content-addressed sha256 fingerprints, source origin paths, and author attribution on all extracted artifacts.

---

## 3. Reporting & Communication Rules

1. **Lead with Outcome / Next Action:** Maximize signal and recovery speed.
2. **Deterministic Gates Run Quietly:** Report failures, anomalies, or concise summary counts (e.g. `58/58 tests passed, 0 errors/warnings`), not raw passing-test transcripts.
3. **One Material Decision at a Time:** If human judgment is required, ask one focused question.
4. **Distinguish Evidence Types:** Clearly differentiate between deterministic facts, reference prototypes, live runtime checks, and unverified assumptions.

---

## 4. Working Tree & Commit Safety

- **Preserve Independent Repositories:** Never move, delete, or overwrite donor files or sibling repositories without explicit delegation.
- **Commit Delegation:** Do **NOT** stage, commit, push, publish, or deploy unless Ryan explicitly delegates that exact action in the prompt.
