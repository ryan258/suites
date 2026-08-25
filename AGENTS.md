# AGENTS.md - Operational & Test Economy Guidelines for Suites Control Plane

> **For AI Assistants & Subagents:** This document defines the operating rules, test economy discipline, and execution boundaries for `/Users/ryanjohnson/Projects/suites`. Read and adhere to these guidelines on every task.

---

## 1. Core Principle: Test Economy & Cost Discipline

Running tests, subagents, and heavy external runtimes consumes time, tokens, and compute. **Tests are not free.** Do not reflexively run full test suites or multi-stage external test runners on minor incremental changes.

### Execution Hierarchy (From Cheapest to Most Expensive)

1. **Level 0: Schema & Registry Fast-Path (<100ms)**
   - Run `PYTHONPATH=src python3 -m portfolio_suites validate --fast` to verify contracts, suite schemas, and file boundaries offline.
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

4. **Level 3: Full Test Suite (`discover`) — Milestone Only**
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
- **Contract Enforcement:** All inter-suite data exchange uses versioned JSON contracts (`SourceRecord`, `BrandPackage`, `ProductionJob`, `ExperimentRun`, `InvestigationRecord`, `A11yFinding`) validated by `portfolio_suites.contracts`.
- **Fail-Closed Boundaries:** Unapproved destructive or mutating actions must fail closed without manufacturing synthetic human approval tokens.
- **Immutable Provenance:** Retain content-addressed sha256 fingerprints, source origin paths, and author attribution on all extracted artifacts.

---

## 3. Architecture Principles & Evidence Standards (Hard-Won Lessons)

1. **Engine Action Chaining as Universal Control Primitive**:
   - Prefer composing multi-step wave logic and tool pipelines through `portfolio_suites.chains` using `{"$from": <step_index>}` parameter references instead of writing custom ad-hoc Python glue.
   - The CLI (`suites chain`), Web Toolbench (`POST /api/chain`), and wave runners must use the exact same declarative action engine.

2. **Pure JSON Structured Evidence Receipts**:
   - All evidence receipts must be structured `.json` documents validated by `ANALYSIS_RECEIPT_SPECS` and `validate_contract`.
   - Markdown projections, HTML samples, or diffs must be embedded within structured string fields (e.g., `"projection_markdown"`), ensuring typed invariants, minimums, and git fingerprints are always machine-checked.

3. **2-Tier Adapter Pattern (`probe` vs `execute_runtime`)**:
   - Every source adapter must cleanly decouple:
     - **Fast Probe (Level 1/2)**: Validates schemas, mutation protection, content hashes, and donor file presence offline in milliseconds.
     - **Live Runtime (Level 4)**: Spins up external subprocesses (Node/Playwright/Python) to prove real behavioral parity with `--full` depth.

4. **Single Source of Truth for Wave Specifications**:
   - Avoid creating disjoint validation logic across separate files. Keep wave metadata, `recovery_claim`, `evidence_basis`, and contract validators strictly aligned with manifest schemas in `suite.json`.

5. **Tamper-Evident Working Tree Tracking**:
   - Preserve dirty state patches and check drift non-destructively; never modify donor repositories or commit changes without explicit delegation.

6. **Live State Figures vs. Static Markdown**:
   - Live filesystem figures (such as active donor repository drift or dirty working tree counts) must be queried dynamically via CLI tools (`suites drift`, `suites validate`) and never asserted as live claims in static Markdown documentation. Markdown docs may only record dated snapshot baselines; live numbers in static files cannot be enforced by registry-driven doc gates and will rot silently.

7. **Donor Code Runs Out-of-Process**:
   - Never import a donor repository into the control-plane process. This process holds the approval store, credential-bearing configuration, and the ledger; an in-process donor import hands all of it to code this repository does not own.
   - A gate that must execute donor code adds a `donor_*_probe.py` module beside the adapters, runs it with `subprocess.run([sys.executable, str(PROBE), ...], env=donor_env({...}))`, passes inputs as argv, and reads one JSON line from stdout. `donor_env` withholds `PYTHONPATH` and `HOME`, so the probe cannot reach back into `portfolio_suites` or the user's credential surfaces.
   - The probe must return a dedicated exit code for "the donor could not be imported" so the adapter can still record `environment_blocked` truthfully. A single non-zero exit reports a missing dependency as an API break.
   - Verify donor claims the parent can check itself. A digest the donor both computes and attests is donor self-attestation; recompute it host-side and require agreement.

---

## 4. Reporting & Communication Rules

1. **Lead with Outcome / Next Action:** Maximize signal and recovery speed.
2. **Deterministic Gates Run Quietly:** Report failures, anomalies, or concise summary counts (e.g. `all tests passed, 0 errors/warnings`), not raw passing-test transcripts.
3. **One Material Decision at a Time:** If human judgment is required, ask one focused question.
4. **Distinguish Evidence Types:** Clearly differentiate between deterministic facts, reference prototypes, live runtime checks, and unverified assumptions.

---

## 5. Working Tree & Commit Safety

- **Preserve Independent Repositories:** Never move, delete, or overwrite donor files or sibling repositories without explicit delegation.
- **Commit Delegation:** Do **NOT** stage, commit, push, publish, or deploy unless Ryan explicitly delegates that exact action in the prompt.

---

## 6. GitNexus Code Graph (Ryan runs GitNexus locally)

The repo is indexed by [GitNexus](https://github.com/abhigyanpatwari/GitNexus) (`gitnexus` CLI, installed globally; MCP + skills registered for Claude Code / Codex / Antigravity / OpenCode).

- **Canonical token-economy rule:** Agents do **not** run GitNexus CLI commands, MCP tools, resources, or broad GitNexus skill/reference lookups by default. This rule overrides the generated GitNexus block below wherever that block tells an agent to invoke MCP tools directly.
- When graph evidence is materially needed, give Ryan the **smallest exact local command or tool invocation** required, state what output is needed, and ask him to paste the compact result back. Prefer one focused request at a time over broad graph dumps.
- Do not duplicate a GitNexus query after Ryan supplies current output. Treat the pasted result as task evidence, summarize only the relevant facts, and continue with ordinary source inspection or tests.
- Never run `gitnexus analyze`. Indexing is a Level 4 heavy gate. If freshness is unknown, ask Ryan to run `node .gitnexus/run.cjs status`. If it reports stale, ask him to run `node .gitnexus/run.cjs analyze` and then `node .gitnexus/run.cjs status`.
- Do not request a refresh when current task output already proves the index is up to date at the checked-out commit.
- If a required query is available only through a GitNexus MCP client rather than the CLI, provide the exact read-only MCP invocation for Ryan to run locally; do not invoke it yourself unless Ryan explicitly delegates GitNexus operation in the current prompt.
- Where the generated block requires `impact` or `detect_changes`, satisfy that requirement by requesting Ryan's local result; the token-economy rule changes who runs the query, not whether required safety evidence is collected.
- Continue any safe, useful non-GitNexus work while waiting when the query result is not a hard blocker.

### Prompt for Ryan to run locally (check and refresh only if stale)

```bash
cd /Users/ryanjohnson/Projects/suites
node .gitnexus/run.cjs status

# Only when status reports stale:
node .gitnexus/run.cjs analyze
node .gitnexus/run.cjs status
```

- Incremental by default — re-run after a batch of edits or a branch switch.
- `gitnexus analyze -f` — force a full re-index (after big refactors or a bad index).
- `gitnexus analyze --index-only` — refresh the graph without touching `AGENTS.md` / `CLAUDE.md` / skills.
- `gitnexus analyze --pdg` — adds data/control-flow substrate, needed for `explain` / `pdg_query`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **suites** (2362 symbols, 5085 relationships, 201 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/suites/context` | Codebase overview, check index freshness |
| `gitnexus://repo/suites/clusters` | All functional areas |
| `gitnexus://repo/suites/processes` | All execution flows |
| `gitnexus://repo/suites/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
