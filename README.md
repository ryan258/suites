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
STATUS: Portfolio control plane and suite prototypes established
RECOVERY STANDARD: 9.0/10 target for valuable functionality; raw wave completion is not the score
GATE CHECK: Registry valid | 8 Suite Boundaries | 6 Shared Contracts | 70 Projects Dispositioned
BIBLE: Done
CAST: Done as operator and system-role profiles
CRAFT RULES: Done
SKILL FILE: Staged locally; not installed outside this workspace
OUTPUTS: CLI, Zero-dependency Web Dashboard, 8 Prototype Engines, 8 Source Adapters, 6 Contracts, 43 Wave Specifications
VERIFIED CLAIMS: 1 Runtime Recovery (A2) | 4 Analysis Milestones (A1, A3, O2, B2) | 0 Adopted | 0 Converged
PROTOTYPES: 38 source-backed checks passing; every gate reads donor content, and none of them
           counts as recovered functionality
```

`A1` is a reviewed, hand-authored parity decision whose required document structure is checked by
the runner. It is an analysis milestone, not an executed donor or runtime gate.

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

The checkout-local control plane uses only the Python standard library and vanilla web
technologies. Source-runtime gates retain their donors' own prerequisites: Accessibility A2
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
PYTHONPATH=src python3 -m portfolio_suites ai-config

# Cross-suite contract inspection & testing
PYTHONPATH=src python3 -m portfolio_suites contract A11yFinding sample
PYTHONPATH=src python3 -m portfolio_suites contract BrandPackage spec
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate <file.json>

# Ephemeral wave checks (4 analysis milestones + 38 prototypes + 1 runtime wave)
# Without --full, A2 runs a fast probe and is reported as [FAST-PROBE], not a runtime recovery.
PYTHONPATH=src python3 -m portfolio_suites wave --all
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --full

# Explicitly replace a wave's evidence artifact after reviewing its runner
# Runtime evidence requires an explicit full-depth request; --record never selects depth.
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --record --full

# Run the suite engines directly (Toolbench surface)
PYTHONPATH=src python3 -m portfolio_suites engine                       # list all 46 actions
PYTHONPATH=src python3 -m portfolio_suites engine accessibility          # list one suite's actions
PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_html_snippet \
  --args '{"html_content": "<img src=hero.png>"}'

# Chain engine actions: one action's output becomes a later action's argument
# Steps reference earlier output as {"$from": <step>} with optional "path" to select part of it.
PYTHONPATH=src python3 -m portfolio_suites chain my-chain.json
PYTHONPATH=src python3 -m portfolio_suites chain my-chain.json --quiet

# Launch the zero-dependency local web dashboard (Toolbench tab runs and chains engine actions)
./start.sh                                              # default port 8383 (or ./start.sh <port>)
PYTHONPATH=src python3 -m portfolio_suites serve --port 8383

# Run complete test suite
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

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
the [recovery standard](docs/RECOVERY-STANDARD.md), and the
[OpenRouter configuration guide](docs/OPENROUTER.md).
