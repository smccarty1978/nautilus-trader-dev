# F1/F2 Population Reconciliation Report

## Exact per-period counts (explicit `population` field, F1 and F2 never combined)

population            F1     F2
period_role                    
dev_test            6650   3006
secondary_2025H2   16260   6905
secondary_2026      8934   3957
train             110503  47122
validation          4256   1779

## F2 canonical entry-rule reconciliation

**Canonical source:** `collectors/collector_v2/results/v_a_v0_nodelay_{2024,2025,2026}/trades.parquet` (current no-delay V_A confirmed-entry collector -- HH/LL vs. flip bar + directional close, decision_ts == entry_ts, same rule verified against `collectors/collector_v2/strategy.py` independently of this study's F2 construction in `build_flip_atlas.py`).

Coverage: validation + dev_test + secondary_2025H2 + secondary_2026 only (canonical V_A dataset starts late-2024; train period 2021-2023 has no canonical counterpart to reconcile against and is reported as `coverage_not_available`).

**Timing-convention finding:** V_A's `entry_ts` lands ~1-7 seconds after the 1m-bar-close minute boundary that F2's `observation_time` uses (V_A fills on the first 1s bar whose own processing follows the 1m-close event; F2 fills on the 1s bar that starts exactly at the minute boundary). This is a sub-bar execution-convention difference, not a population mismatch; matching uses a 5-second tolerance to bridge it.

- F2 study episodes in covered periods: 15608
- Matched (nearest entry_ts within 5s, same direction): 4400 (28.19% of study episodes)
- Only in study (F2 has no canonical V_A counterpart): 11208
- Only in canonical source (V_A trade with no F2 counterpart): 3394
- Entry-price match rate among matched pairs (tol 5.0 pts): 0.9686
- Terminal-ts (exit_ts) match rate among matched pairs: 0.8859

### Key finding: session-scope mismatch, not a rule mismatch

The canonical `v_a_v0_nodelay` collector's own `session` field shows it is ~99.3% RTH / ~0.7% ETH -- i.e. the canonical collector as currently deployed trades almost exclusively RTH. F2, by contrast, runs the same confirmation rule across the full ~23h session. When the reconciliation is restricted to F2's own RTH subset (the only subset where the canonical source has real coverage), match quality is:

- RTH-only F2 episodes: 4404
- RTH-only matched: 4368 (99.18%)
- RTH-only entry-price match rate (tol 5.0 pts): 0.9691
- RTH price-diff distribution (V_A fill - F2 fill, points): median=0.000, mean=0.029, std=2.114, |diff|<=5pt fraction=0.9691

The median diff is exactly 0.0 and the distribution is symmetric, consistent with ordinary NQ price movement over the 1-7s fill-timing gap between the two conventions -- not a systematic pricing bug.

This is reported as a **scope difference** (canonical collector not currently run over ETH), not a defect in F2's entry rule -- F2's rule was independently verified against `collectors/collector_v2/strategy.py` and matches. Primary economics in this study use the full F2 population (RTH+ETH), consistent with the frozen study's original scope; the RTH-restricted match rate is reported for interpretability.

**CANONICAL F2 ENTRY PARITY (RTH-comparable subset): PASS**
