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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **suites** (2486 symbols, 5247 relationships, 212 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
