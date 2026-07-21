# Bracket-Aligned Entry Quality Model (v2 Corpus)

## Objective

Train a classifier on the v2 corpus to identify real-time-valid
entries that are specifically good for the intended bracket execution
(1 ATR PT / 1 ATR SL), with preference for **clean** and **fast** wins.

Replaces earlier framings (hold-to-flip, generic good_entry_300s)
with a target directly aligned to the live-trade mechanics.

## Population

- v2 corpus, HH/LL-confirmed events, checkpoint rows
- **RTH only** (ETH excluded — prior studies showed no signal there)
- Checkpoints `T ∈ {0, 30, 60, ..., 600}` (21 checkpoints)
- `fillable_at_T == True` only

## Target label

```
good_bracket_entry = 1  iff ALL of:
    pt100_before_sl100 == 1
    mfe_mae_ratio_300s > 1.25        # Note: spec called 360s; see SUBSTITUTION below
    bracket_resolution_time_s_pt100_before_sl100 <= 360
else 0
```

### SUBSTITUTION NOTE

Spec called for `mfe_mae_ratio_360s > 1.25` but v2 collector's
forward-window grid is `{30, 60, 120, 180, 300, 600}` — no 360s
window. Using 300s as the closest available. Since nearly all
positive-class trades resolve well before 300s (median PT hit ~115s),
the 300s window effectively captures the trade's full observable
life. Effect: slightly stricter clean-path requirement than the
spec, roughly equivalent signal.

If exact 360s is needed later, add it to `FWD_WINDOWS_S` in the
collector and re-run (~75 min for all 6 years).

## Unresolved bracket handling

For this target, **exclude unresolved rows from training**. Do not
fall back to regime-exit PnL. This keeps the target a clean PT-vs-SL
race label, matching the intended execution.

Report (do not filter on):
- Total unresolved count + rate overall
- Unresolved rate by stratum
- Unresolved rate by T bucket

## Features

All 177 `role == "model_feature"` columns from
`models/ml_5m_flip/feature_contract_v2.json`. No manual pruning on
first pass.

## Splits

- Train: years 2020-2023 (event-grouped)
- Val: year 2024 (early stopping on val AUC, event-grouped)
- OOS: year 2025 (never touched during training)
- Event-grouped chronological only. No row-level random.

## Model

LightGBM classifier baseline. No broad hyperparameter sweep on first
pass. Same defaults as prior studies (learning_rate=0.05, num_leaves=63,
min_data_in_leaf=200, feature_fraction=0.8, bagging_fraction=0.8).

## Required outputs

### Classification metrics (OOS)

- AUC, PR-AUC
- Base rate
- Top-decile hit rate (precision @ top-10%)
- Score-bucket calibration (10 deciles, predicted vs actual rate)

### Economic outputs (OOS, bracket PnL)

Bracket PnL formula:
  - PT hit: `+1.0 × atr_at_signal × 20 − 5` (NQ_MULT=20, commission=$5)
  - SL hit: `−1.0 × atr_at_signal × 20 − 5`
  - (Unresolved rows are excluded from economic tables per the target
     rule — they're not part of the "bracket race" population.)

For each score-bucket (ALL, top 30%, top 20%, top 10%, top 5%):
- n, mean $, median $, trimmed-5% mean, win rate, PF, total $

### Stratified reporting

Above metrics for:
- ALL RTH
- RTH-Long
- RTH-Short
- T buckets: 0-90s, 90-180s, 180-300s, 300-450s, 450-600s

### Feature importance

Top 25 gain. Report only — no pruning in first pass.

## Success criteria

Study worth continuing if AT LEAST ONE holds OOS:

1. Top-decile / top-quintile bracket economics improve materially
2. RTH-Short shows clear lift without collapsing median/trimmed
3. One or more T buckets show stable, non-tail-driven improvement
4. Usable ranking lift even if raw AUC is modest

Warning sign: mean-driven lift with weak median/trimmed support.

## Files

- `collect.py` — load RTH-only T=[0,600] cohort, attach target
- `train.py` — LightGBM classifier
- `report.py` — classification + economics + stratified tables
- `run_study.py` — orchestrator
