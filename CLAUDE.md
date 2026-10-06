# CLAUDE.md

Project instructions live in AGENTS.md — read it in full, it is canonical for this repo.

@AGENTS.md

## Core Architecture & Evidence Invariants

- **Engine Action Chaining**: Compose multi-step wave logic and tool execution through `portfolio_suites.chains` (`{"$from": <step_index>}`) across CLI, server, and web UI.
- **Pure JSON Evidence Receipts**: All evidence artifacts must be structured `.json` with schema validation and content-addressed fingerprints (embed markdown/HTML in string fields).
- **2-Tier Adapter Pattern**: Decouple fast offline schema/mutation probes (<500ms) from deep authentic subprocess runtimes (`--full`).
- **Fail-Closed Operations**: Never manufacture synthetic human approval tokens or alter donor checkouts without explicit delegation.

## GitNexus token economy (canonical override)

- Ryan runs GitNexus locally. Do not invoke GitNexus CLI commands, MCP tools, resources, or broad GitNexus skill/reference lookups by default.
- This section and `AGENTS.md` override any generated instruction below that tells an agent to call GitNexus MCP tools directly.
- When graph evidence is materially required, give Ryan the smallest exact local command or read-only MCP invocation, say which compact output is needed, and ask him to paste it back.
- Use supplied GitNexus output as current evidence without repeating the query. Do not ask for a refresh if Ryan has already shown that the index matches the checked-out commit.
- For freshness, request `node .gitnexus/run.cjs status`; only after a stale result request `node .gitnexus/run.cjs analyze` followed by `node .gitnexus/run.cjs status`. Never run analysis yourself.
- When the generated block requires `impact` or `detect_changes`, request Ryan's local result. This changes who runs the query, not the safety gate.
- Invoke GitNexus directly only when Ryan explicitly delegates that operation in the current prompt.

> The generated GitNexus code-intelligence block lives once, in `AGENTS.md` (imported above). Refresh the index with `node .gitnexus/run.cjs analyze --index-only` so it does not re-add a second copy here.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **suites** (3118 symbols, 7021 relationships, 266 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/suites/context` | Codebase overview, check index freshness |
| `gitnexus://repo/suites/clusters` | All functional areas |
| `gitnexus://repo/suites/processes` | All execution flows |
| `gitnexus://repo/suites/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
