# G1 — Tucked in Terrors parity fixture

- game_version_fingerprint: `main@21511ab` (dirty=False)
- cards_sha256: `43f0f300fa2e2b7d8dac418ec82506f1e55c7e68cf0d620824ec68b6e002fd0a` (31 cards)
- objectives_sha256: `059e14a20e41956618aa8d664964fefe1efced95c22d6edf5139f54fc25d04f9` (8 objectives)
- results_sha256: `b70aec649014a9b3ecbfcc24870d2dbfae875c54e803b4603f5366cc194d9e54` (1000 recorded runs)
- objectives_exercised: OBJ01_THE_FIRST_NIGHT

## outcome_distribution

| win_status | runs | share |
| --- | ---: | ---: |
| LOSS_NIGHTFALL | 926 | 0.926 |
| PRIMARY_WIN | 74 | 0.074 |

## metric_tolerances

| metric | min | mean | max |
| --- | ---: | ---: | ---: |
| distinct_toys_played | 0 | 3.739 | 7 |
| final_turn | 3 | 4.94 | 5 |
| mana_from_effects | 0 | 0.0 | 0 |
| memory_tokens | 0 | 0.0 | 0 |
| spirit_tokens | 0 | 2.432 | 55 |
| spirits_created | 0 | 2.432 | 55 |

## configuration

- seed_policy: donor run_01 corpus is the fixed reference sample; no reseeding is claimed.
- expected_tolerances: any replacement runtime must reproduce the distribution above per objective.
