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
OUTPUTS: CLI, Zero-dependency Web Dashboard, 8 Prototype Engines, 6 Contracts, 43 Wave Specifications
VERIFIED CLAIMS: 1 Runtime Recovery (A2) | 1 Analysis Milestone (A1) | 0 Adopted | 0 Converged
PROTOTYPES: 41 checks passing; prototypes never count as recovered functionality
```

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

No third-party Python package or npm install is required (100% Python standard library + vanilla web technologies).

```bash
cd /Users/ryanjohnson/Projects/suites

# Portfolio status, inspection & validation
PYTHONPATH=src python3 -m portfolio_suites status
PYTHONPATH=src python3 -m portfolio_suites list
PYTHONPATH=src python3 -m portfolio_suites next
PYTHONPATH=src python3 -m portfolio_suites validate
PYTHONPATH=src python3 -m portfolio_suites inspect accessibility
PYTHONPATH=src python3 -m portfolio_suites drift
PYTHONPATH=src python3 -m portfolio_suites ai-config

# Cross-suite contract inspection & testing
PYTHONPATH=src python3 -m portfolio_suites contract A11yFinding sample
PYTHONPATH=src python3 -m portfolio_suites contract BrandPackage spec
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate <file.json>

# Ephemeral wave checks (1 runtime recovery + 1 analysis milestone + 41 prototypes)
PYTHONPATH=src python3 -m portfolio_suites wave --all
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2

# Explicitly replace a wave's evidence artifact after reviewing its runner
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --record

# Launch the zero-dependency local web dashboard
PYTHONPATH=src python3 -m portfolio_suites serve --port 8383

# Run complete test suite (57 tests)
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`validate` checks the entire current top-level directory inventory, nested Git-marker inventory,
suite membership, source paths, ownership, contracts, and migration waves. Source-tree drift is
reported without modifying any source repository.

## Operating rules

1. One user promise and one canonical owner per capability.
2. Source repos remain untouched until a named migration wave begins.
3. Nothing is retired because it looks duplicate; parity, provenance, dirty state, and ownership
   are checked first.
4. Every cross-suite artifact uses a versioned contract in `contracts/`.
5. AI-generated judgments remain labeled. Deterministic, manual, and provider-backed evidence do
   not collapse into one confidence claim.
6. Publication, deployment, staging, commits, destructive cleanup, and collaborator-owned changes
   remain owner-controlled.
7. “Complete” means the suite completion criteria are evidenced, not that a scaffold exists.
8. The [9/10 recovery standard](docs/RECOVERY-STANDARD.md) governs promotion, adoption, convergence,
   and intentional non-port outcomes; wave counts are scheduling metrics, not the recovery score.

See [the project bible](docs/PROJECT-BIBLE.md), [the review](docs/PORTFOLIO-REVIEW-2026-08-19.md),
[the migration program](docs/MIGRATION-PROGRAM.md), [the institution roadmap](docs/ROADMAP.md),
the [recovery standard](docs/RECOVERY-STANDARD.md), and the
[OpenRouter configuration guide](docs/OPENROUTER.md).
