---
name: ryan-project-suites
description: Govern and migrate Ryan's project portfolio into eight evidence-bound suites. Use for suite ownership, contract, provenance, parity, or migration work in /Users/ryanjohnson/Projects/suites.
---

# Ryan Project Suites

Use this local skill candidate to keep suite work inside the clean portfolio boundary. It is staged
here for review and is not installed into the canonical personal skill library.

## Rules

1. Preserve original repositories and working-tree state.
2. Require a source fingerprint and parity evidence before retirement.
3. Prefer an adapter or domain pack to a new generic runtime.
4. Use the versioned shared contracts for cross-suite artifacts.
5. Label deterministic, model-assisted, manual, stale, and unknown evidence separately.

## Workflow

1. Run `PYTHONPATH=src python3 -m portfolio_suites validate`.
2. Read the target suite's `suite.json` and README.
3. Select only the first incomplete migration wave.
4. Inspect source state and record any fingerprint drift.
5. Implement or port the smallest end-to-end slice.
6. Run source tests, suite tests, and parity checks appropriate to that slice.
7. Update evidence and status without deleting or retiring source work.

## Output Template

```text
SUITE:
WAVE:
SOURCE FINGERPRINT:
OUTCOME:
EVIDENCE:
LIMITATIONS:
RECOVERY PATH:
NEXT MOVE:
OWNER APPROVAL REQUIRED:
```

## Do Not

- Do not move or delete a source checkout because its name looks duplicated.
- Do not copy secrets, local databases, runtime logs, or generated caches.
- Do not claim deployment, conformance, publication, or market validation from local gates.
- Do not build shared abstractions before two real consumers exist.
- Do not stage, commit, push, deploy, or publish without current explicit delegation.
- Do not change collaborator-owned sources without agreement.

