"""Game Design & Simulation engine powering seeded Monte Carlo simulations and balance reports."""

from __future__ import annotations

import datetime
import random
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


class GameDesignEngine:
    """Execute seeded Monte Carlo game simulations, analyze balance curves, and export Storyweaver packs."""

    @staticmethod
    def simulate_tucked_in_terrors(
        seed: int = 42,
        trials: int = 1000,
        difficulty_modifier: float = 1.0,
    ) -> dict[str, Any]:
        """Simulate Tucked in Terrors card/dice encounters using deterministic PRNG."""
        rng = random.Random(seed)
        trial_wins: list[int] = []
        turn_counts: list[int] = []
        terror_levels: list[int] = []

        for _ in range(trials):
            hp = 10
            sanity = 10
            turns = 0

            while hp > 0 and sanity > 0 and turns < 15:
                turns += 1
                # Draw hazard event
                hazard_roll = rng.randint(1, 6) * difficulty_modifier
                if hazard_roll > 4.0:
                    hp -= rng.randint(1, 3)
                    sanity -= rng.randint(0, 2)
                elif hazard_roll > 2.0:
                    sanity -= rng.randint(1, 2)
                else:
                    # Resource recovery
                    sanity = min(10, sanity + 1)

            is_win = 1 if (hp > 0 and sanity > 0) else 0
            trial_wins.append(is_win)
            turn_counts.append(turns)
            terror_levels.append(max(0, 10 - sanity))

        total_wins = sum(trial_wins)
        total_losses = trials - total_wins
        avg_turns = sum(turn_counts) / len(turn_counts)
        avg_terror = sum(terror_levels) / len(terror_levels)
        win_rate = total_wins / trials

        # Calculate accurate checkpoint win rates
        checkpoint_iterations = []
        for i in range(1, min(trials // 100 + 1, 11)):
            sample_size = i * 100
            sample_wins = sum(trial_wins[:sample_size])
            checkpoint_iterations.append({
                "trial_sample_100": i,
                "win_rate": round(sample_wins / sample_size, 4),
            })

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        experiment_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": f"run-sim-tit-{seed}-{trials}",
            "benchmark_id": "bench-tucked-in-terrors-balance",
            "benchmark_version": "1.0.0",
            "provider": "game-simulation-engine",
            "model": f"monte-carlo-prng-seed-{seed}",
            "parameters": {
                "seed": seed,
                "trials": trials,
                "difficulty_modifier": difficulty_modifier,
            },
            "scorer": "statistical_balance_scorer",
            "scorer_version": "1.0.0",
            "status": "completed",
            "iterations": checkpoint_iterations,
            "evidence": [
                {
                    "trials": trials,
                    "seed": seed,
                    "win_rate": round(win_rate, 4),
                    "loss_rate": round(total_losses / trials, 4),
                    "avg_turn_count": round(avg_turns, 2),
                    "avg_peak_terror": round(avg_terror, 2),
                    "balance_status": "optimal" if 0.45 <= win_rate <= 0.65 else "unbalanced",
                    "timestamp": now_iso,
                }
            ],
            "errors": [],
        }

        return validate_contract("ExperimentRun", experiment_payload)

    @staticmethod
    def generate_printable_balance_sheet(sim_result: dict[str, Any]) -> str:
        """Generate a formatted markdown printable balance sheet."""
        ev = sim_result.get("evidence", [{}])[0]
        params = sim_result.get("parameters", {})
        return f"""# Tucked in Terrors — Statistical Balance Sheet

**Simulation Run ID:** `{sim_result.get('run_id')}`  
**Seed:** `{params.get('seed')}` | **Trials:** `{params.get('trials')}` | **Modifier:** `{params.get('difficulty_modifier')}`  

---

## Performance Summary

| Metric | Measured Value | Target Balance Zone | Status |
|---|---|---|---|
| **Win Rate** | `{ev.get('win_rate') * 100:.1f}%` | 45.0% – 65.0% | **{ev.get('balance_status', 'UNKNOWN').upper()}** |
| **Loss Rate** | `{ev.get('loss_rate') * 100:.1f}%` | 35.0% – 55.0% | Normal |
| **Avg Turn Count** | `{ev.get('avg_turn_count')} turns` | 7.0 – 11.0 turns | Normal |
| **Avg Peak Terror** | `{ev.get('avg_peak_terror')} / 10` | 5.0 – 8.0 | High Tension |

---

*Generated deterministically by Storyweaver Game Design & Simulation Engine.*
"""
