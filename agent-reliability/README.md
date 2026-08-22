# Agent Reliability and Teaching Lab

Promise: teach and test bounded agent behavior with deterministic gates.

This is an internal lab and curriculum, not another general agent platform. Looping Box supplies
bounded workers and review records; SSSF supplies patterns only after confinement and rollback are
proven; Agentic Harness remains the readable teaching loop; prompt-chain and AI Staff material is
mined for curriculum/skills. `components` receives code only after two real consumers exist.

First move: define a shared `ExperimentRun` fixture that tests path confinement, malformed output,
budget exhaustion, rollback preservation, and reviewer evidence across the small harnesses.

Verified: none (0/5). All 5 waves carry source-backed prototype receipts; a prototype
proves only what its runner read, never recovered functionality.

Next wave: R1 — define the adversarial reliability fixtures — confinement, malformed output,
retry, budget, rollback, and reviewer cases — as `ExperimentRun`s with deterministic outcomes.
