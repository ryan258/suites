# Ryan Project Suites

This is the clean portfolio control plane for the systems worth carrying forward from
`/Users/ryanjohnson/Projects`. It does not duplicate every historical checkout and it does not
pretend that a directory move is a product merge. It gives every durable capability one owner,
defines the contracts between owners, records where each source came from, and makes every
migration prove parity before an older runtime can be retired.

## Premise

- **What it is:** a local-first, evidence-bound portfolio of eight interoperable product suites.
- **Who it is for:** a high-cognitive, variable-bandwidth operator who needs work to survive
  interruptions and remain reviewable.
- **Why it exists:** the portfolio should compound through shared contracts and proven migrations
  instead of multiplying repos, prompts, dashboards, and unowned state.

## Kickstart status

```text
PROJECT: Ryan Project Suites
STATUS: Functional local launchpad, control plane, and truth-bounded suite engines established
RECOVERY STANDARD: 9.0/10 target for valuable functionality; raw wave completion is not the score
GATE CHECK: Registry valid | 8 Suite Boundaries | 6 Shared Contracts | 70 Projects Dispositioned
BIBLE: Done
CAST: Done as operator and system-role profiles
CRAFT RULES: Done
SKILL FILE: Staged locally; not installed outside this workspace
WORK STATE: 43/43 waves complete (42 analysis milestones + 1 runtime wave)
EVIDENCE PROMOTION: 4 prototype | 1 reviewed historical | 37 source inspected | 0 source executed
                    1 parity verified | 0 adopted | 0 converged | 0 resolved
OUTSTANDING: 42/43 completed waves still owe a live run
```

Those are two independent axes and both are load-bearing. The first says every scheduled analysis
milestone is finished. The second says what those milestones demonstrated: most waves now parse
authentic donor artifacts (`source_inspected`), four remain suite-local fixtures (`A5`, `B3`,
`B4`, `B6`), and one runtime recovery (`A2`) is at `parity_verified`. A completed wave at
`prototype` is a finished piece of work and is not a recovery; nothing here has reached adoption,
convergence, or retirement approval.

`A1` is a reviewed, hand-authored parity decision whose required document structure is checked by
the runner — `reviewed_historical_analysis`, not an executed donor or runtime gate. `A2` is the
single `parity_verified` runtime recovery.

`source_executed` and above are runtime-only rungs, and the count is `0` for a specific reason.
`O1`'s gate does import and run authentic donor PKos code, but its retained analysis receipt
records what that code produced, never the invocation itself — no argv, no exit code, no source
fingerprint of the module that ran. An analysis receipt has no field that can carry that proof, so
the claim is capped at `source_inspected` and the gap is written down in `O1`'s `runtime_followup`.
Reaching the rung means re-declaring `O1` as a runtime claim behind a `portfolio-runtime-source-v1`
receipt, not raising a boolean in its manifest.

## The eight suites

| Suite | User promise | Canonical anchor |
|---|---|---|
| [Accessibility](accessibility/README.md) | Find, explain, repair, teach, and track accessibility without overstating evidence. | `allys-tools` |
| [Operator OS](operator-os/README.md) | Preserve context and make the next safe move available at low bandwidth. | `dotfiles` + `PKos` |
| [Brand + Publishing](brand-publishing/README.md) | Turn governed brand truth and sourced ideas into approved, traceable publications. | `brand-maker-spec` + `cyborg` |
| [Production House](production-house/README.md) | Move creative work through resumable jobs to verified deliverables. | `production-house` |
| [Model Behavior Lab](model-behavior-lab/README.md) | Produce reproducible, evidence-linked model capability profiles. | `ai-strength-comparator` |
| [Discovery + Decision](discovery-decision/README.md) | Turn a hard question and typed evidence into a resumable decision record. | `breaking-chains` |
| [Agent Reliability Lab](agent-reliability/README.md) | Teach and test bounded agent behavior with deterministic gates. | `looping-box` |
| [Game Design + Simulation](game-design/README.md) | Turn game rules into simulations, balance evidence, and playable artifacts. | `storyweaver` |

The suites are product boundaries, not necessarily deployment or repository boundaries. A source
project may remain separately versioned when that preserves a clean runtime, independent release,
or collaborator ownership.

## Use it

New here, or want to kick the tyres? [**100 Demos**](docs/100-demos.md) is a hundred runnable
step-by-step exercises, from `list` and `status` through contract validation, action chains, wave
gates, the loopback dashboard, and a final act devoted entirely to trying to break it. Every
command in it is checked by `tests/test_docs.py`.

The checkout-local control plane uses only the Python standard library and vanilla web
technologies. The optional AI assistant makes HTTPS requests to OpenRouter but adds no Python
package dependency. Source-runtime gates retain their donors' own prerequisites: Accessibility A2
requires Node.js plus the already-installed, lockfile-pinned dependencies in `allys-tools` and
the Playwright runtime used by the WCAG Auditor browser probe. Verification commands use
`npx --no-install`, so a gate fails closed instead of downloading a missing package.
The repository root manifests, published contract schemas, evidence, and dashboard assets are
part of the runtime. When running from the checkout, the root is detected automatically; when
installed as a wheel/package, set `SUITES_ROOT=/path/to/suites` (e.g. `SUITES_ROOT=~/Projects/suites suites validate --fast`).

```bash
cd /Users/ryanjohnson/Projects/suites

# Portfolio status, inspection & validation
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites list
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate --fast
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites inspect accessibility
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites export                # consolidated portfolio data as JSON
PYTHONPATH=src python3 -m portfolio_suites baseline --dry-run    # report baselines lacking a status_sha256 or patch_sha256
PYTHONPATH=src python3 -m portfolio_suites baseline              # write those missing fingerprints
PYTHONPATH=src python3 -m portfolio_suites baseline --accept     # adopt live state for drifted repos (owner instruction only)

# Cross-suite contract inspection & testing
PYTHONPATH=src python3 -m portfolio_suites contract A11yFinding sample
PYTHONPATH=src python3 -m portfolio_suites contract BrandPackage spec
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate <file.json>

# Ephemeral wave checks (42 analysis milestones + 1 runtime wave; all 43 verified)
# Without --full, A2 runs a fast probe and is reported as [FAST-PROBE], not a runtime recovery.
PYTHONPATH=src python3 -m portfolio_suites wave --all --no-record
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --full

# Explicitly replace a wave's evidence artifact after reviewing its runner
# Runtime evidence requires an explicit full-depth request; --record never selects depth.
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --record --full

# Run the suite engines directly (Toolbench surface)
PYTHONPATH=src python3 -m portfolio_suites engine                       # list all 50 actions
PYTHONPATH=src python3 -m portfolio_suites engine accessibility          # list one suite's actions
PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_html_snippet \
  --args '{"html_content": "<img src=hero.png>"}'

# Chain engine actions: one action's output becomes a later action's argument.
# Steps reference earlier output as {"$from": <step>} with optional "path" to select part of it.
# The browser replays only the transitive dependency closure and redacts one-time secrets from its tray.
PYTHONPATH=src python3 -m portfolio_suites chain my-chain.json
PYTHONPATH=src python3 -m portfolio_suites chain my-chain.json --quiet

# Credential-free AI configuration check, then explicitly provider-assisted guidance
PYTHONPATH=src python3 -m portfolio_suites ai --status --json
PYTHONPATH=src python3 -m portfolio_suites ai --suite accessibility --role reviewer \
  "Review this proposed finding for evidence gaps"

# Launch the local web dashboard (Toolbench runs/chains actions; AI credentials stay server-side)
./start.sh                                              # default port 8383 (or ./start.sh <port>)
PYTHONPATH=src python3 -m portfolio_suites serve --port 8383

# Run complete test suite
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Optional always-on pre-commit gate (fast registry validation + checked docs commands)
git config core.hooksPath .githooks

# Opt-in packaging gate: builds a real wheel, installs it, drives the console script.
# Needs an interpreter satisfying the requires-python floor in pyproject.toml.
SUITES_WHEEL_SMOKE=1 python3 -m unittest tests.test_wheel_smoke
```

### Free OpenRouter assistant

The AI surface is deliberately optional and free-first. Copy [`.env.example`](.env.example) to the
gitignored `.env`, add your own `OPENROUTER_API_KEY`, and leave
`OPENROUTER_ALLOW_PAID_MODELS=false`. `OPENROUTER_API_KEY` is pinned to `openrouter.ai`. A local
proxy or other OpenAI-compatible host needs all three of `OPENROUTER_BASE_URL`,
`OPENROUTER_ALLOW_CUSTOM_ENDPOINT=true`, and a separately named `OPENROUTER_CUSTOM_ENDPOINT_API_KEY`;
if the custom key is exported in the process environment, export the destination and opt-in
alongside it. The official OpenRouter key is never sent to another origin. Every role then routes
through `openrouter/free`; a configured
paid slug is replaced with the free router unless the operator explicitly changes that policy.
OpenRouter chooses among the free models available for the request, so model identity, capacity,
and rate limits can vary. “Free” is a routing/cost policy, not an uptime guarantee. See the
[OpenRouter free-model router documentation](https://openrouter.ai/docs/guides/routing/routers/free-router)
and [rate-limit FAQ](https://openrouter.ai/docs/faq).

The browser receives configuration status and provider output, never the API key. Project material
is not collected automatically: only the prompt and context the operator explicitly supplies are
sent. Local secret-pattern checks reject obvious credentials and private keys before transport.
Every response is labeled `model_assisted`, names the resolved model, and requires human review;
it cannot satisfy deterministic gates, create retained evidence, approve a release, or authorize a
filesystem mutation.

### Operator actions

The Operator OS engine exposes four JARVIS handlers: bounded secret auditing, content-addressed ZIP
backup, conflict-refusing additive Markdown sync, and reversible cache rotation. Every handler has
a dry-run or read-only path. Active filesystem changes require an approval issued outside this
repository, bound to the exact action and canonical parameter digest through
`PORTFOLIO_OPERATOR_APPROVAL_STORE`, and consumed exactly once. The CLI, API, and dashboard cannot
mint that authority. Successful mutation receipts include concrete recovery instructions.

Toolbench exports and replays only the dependency steps required by the pending action. `$from`
references are rebased after pruning unrelated history, invalid or forward references fail during
preflight, and approval/API-token arguments are replaced with a redaction marker before a successful
result enters the browser tray. A redacted secret-bearing step cannot be replayed; the operator must
provide fresh one-time authority.

`validate` checks the entire current top-level directory inventory, nested Git-marker inventory,
suite membership, source paths, ownership, contracts, and migration waves. It re-reads the retained
receipt of every wave that declares a recovery claim — prototypes included — against that claim's
evidence basis and receipt spec, so a receipt cannot drift out of agreement with its claim and still
report green. Only the promotion rules are reserved for completed waves. Source-tree drift is
reported without modifying any source repository.

## Operating rules

1. One user promise and one canonical owner per capability.
2. Source repos remain untouched until a named migration wave begins.
3. Nothing is retired because it looks duplicate; parity, provenance, dirty state, and ownership
   are checked first.
4. Every cross-suite artifact uses a versioned contract in `contracts/`.
5. AI-generated judgments remain labeled. Deterministic, manual, and provider-backed evidence do
   not collapse into one confidence claim.
6. A receipt's status names what its gate performed, not what its wave intends to achieve. Reading a
   donor's files is reported as reading them, never as discovery, unification, parity,
   consolidation, or retirement.
7. Publication, deployment, staging, commits, destructive cleanup, and collaborator-owned changes
   remain owner-controlled.
8. “Complete” means the suite completion criteria are evidenced, not that a scaffold exists.
9. The [9/10 recovery standard](docs/RECOVERY-STANDARD.md) governs promotion, adoption, convergence,
   and intentional non-port outcomes; wave counts are scheduling metrics, not the recovery score.

See [the project bible](docs/PROJECT-BIBLE.md), [the review](docs/PORTFOLIO-REVIEW-2026-08-19.md),
[the migration program](docs/MIGRATION-PROGRAM.md), [the institution roadmap](docs/ROADMAP.md),
and the [recovery standard](docs/RECOVERY-STANDARD.md).
