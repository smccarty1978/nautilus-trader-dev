# Bracket-Entry v3 — Full-Population PT-First Rescue

## Why this exists

The bracket_entry_v2 branch trained on resolved-only rows and
evaluated via schedule-driven NT, which inflated per-trade economics
2-3× by hiding the unresolved-population reality. See
`memory/schedule_driven_eval_survivor_bias.md`.

This v3 study tests whether the model can learn to discriminate
**true PT-first winners from everything else** (SL, regime-exit,
unresolved) when trained on the full live population — and whether
the resulting strategy survives live-style NT validation on TWO OOS
years.

## Population

- v2 corpus, RTH only, T ∈ {0, 30, ..., 600}
- `fillable_at_T == True`
- **NO** resolved-only filter — full live population

## Label

```
is_pt_first = 1  iff  pt100_before_sl100 == 1
            = 0  otherwise (SL first, regime-exit, unresolved, NaN)
```

No fast-window constraint. No clean-path constraint. Pure
PT-first-vs-everything binary on the full population.

## Splits

| OOS year | Train | Val | OOS |
|---|---|---|---|
| 2024 | 2020-2022 | 2023 | 2024 |
| 2026 | 2020-2024 | 2025 | 2026 |

Each year retrained independently — no future data leakage.

## Feature reduction sweep

For each OOS year, run iterations:
- full (177)
- top_50
- top_35
- top_25
- top_20
- top_15
- top_10

Feature ranking by gain importance from the full-feature model trained
on that year's split.

## Threshold

For each candidate model, threshold = score at val-set's 90th
percentile (top-10% of val scores). Same threshold used in live OOS
trading. Same recipe as prior studies.

## Evaluation — LIVE FULL-POPULATION ONLY

For each (candidate, OOS year), run `LiveBracketStrategy` (subclass
of CollectorV2):
- Subscribes to 1s + 1m bars
- Computes features live via the collector state machine
- Scores model at every fillable+feature-present checkpoint with T ≤ 600
- Submits market entry + 1 ATR PT/SL bracket if score >= threshold
- Single-position gate
- Cancels bracket + market-closes on regime flip

**Schedule-driven NT evaluation is FORBIDDEN by methodology.**

## Reporting

For each (candidate, OOS year):

### Classification
- AUC, PR-AUC, base rate
- Top-10% hit rate

### NT economics (cost-adjusted: $5 commission + 1-tick slippage)
- n trades, mean / median / trimmed-5% mean
- PF, win %, total $
- Long/short balance

### Outcome mix at top-decile vs population
- PT %, SL %, regime_exit %, unresolved %

This shows whether the model is reducing regime-exit contamination
in the selected trades — the core diagnostic.

## Selection criteria

Smallest viable feature set:
- Positive economics (PF > 1.10) on BOTH 2024 AND 2026 OOS
- Top-10% economics meaningfully above baseline (≥ 1.5× full-population mean)
- Direction balance (35-65% each side) in top-decile selections

If no candidate meets these on both years → **branch retired**.

## Files

- `collect.py` — add new label to existing cohort
- `train_sweep.py` — 7 iterations × 2 OOS years training
- `run_live_all.py` — orchestrate 14 live NT runs
- `analyze.py` — outcome classification + final report
