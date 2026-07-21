# Good Entry v2 Study

## Hypothesis

Within the first 600s of an HH/LL-confirmed 1m regime flip, **certain
checkpoints are imminent, high-quality entries** — defined by the next
300s of price action being both substantial and clean. If such
checkpoints can be identified in real time from snap-time features,
they constitute an actionable entry signal.

This is a reframe of the (failed) delayed-entry framing: we are not
asking whether blind delay helps. We are asking whether *some
checkpoints* in the first 600s are systematically better than others
on a quality-of-forward-path basis, and whether that quality is
predictable from features available at decision time.

## Population

- v2 corpus, 2020-2025 (114K events, 1.69M fillable checkpoints total)
- HH/LL-confirmed events only (already enforced by collector)
- Checkpoints `T ∈ {0, 30, 60, ..., 600}` — the first 21 checkpoints
  (every 30s through the first 10 minutes of the event)

## Primary label

```
good_entry_300s = 1  iff
    mfe_300s_atr > 1.0  AND  mfe_mae_ratio_300s > 1.25
                       else 0
```

**Censoring policy**: applied directly to emitted label values. Censored
windows whose partial-window peak met both conditions count as 1
(observed condition was met during the trade's life). Censored
windows whose partial peak did NOT meet the conditions count as 0
(default per project policy — "did not achieve clean-path within
observable event life"). This matches the v2 collector's existing
`clean_path_300s` convention. The censoring fraction is reported as
audit context but is NEVER used as a row-exclusion filter — that's
the censored-label survivor bias trap from April 2026.

## Phase 1 — descriptive

For each checkpoint `T ∈ {0, 30, ..., 600}`:

1. Total fillable rows
2. `good_entry_300s == 1` count and base rate
3. RTH vs ETH breakdown (rates)
4. Long vs Short breakdown (rates)
5. Mean / median `regime_exit_pnl_dollars` for `good_entry_300s == 1`
   subset vs all rows
6. PT100 / SL100 win-rate for the subset vs all rows

The decision criterion: does any T have a **base rate elevated
meaningfully above the cross-T average AND with economic
discrimination** (subset PnL clearly positive while all-row PnL is near
zero)? If yes, Phase 2 ML modeling is warranted. If no, the label is
not learnable at this horizon and we stop.

## Phase 2 — ML feasibility (CONDITIONAL on Phase 1 signal)

If Phase 1 shows structure, train a classifier:

- **Target**: `good_entry_300s`
- **Features**: contract `role == "model_feature"` only (177 features)
  - When pooling across checkpoints, include `checkpoint_s` as a feature
- **Splits**: event-grouped chronological, NEVER row-level random
  - Train: 2020-2023 (4 years)
  - Validation: 2024 (1 year, held out for hyperparameters)
  - OOS test: 2025 (1 year, never touched until final eval)
- **Models**: LightGBM as baseline
- **Metrics**:
  - AUC on OOS test
  - Threshold sweep: precision, recall, fillable count at each
    threshold
  - Per-decile economic table on OOS: regime_exit $ and PT100 win-rate
    by predicted-probability decile
  - Top-decile vs bottom-decile spread (the actionable signal)
- **Per-strata reports**: RTH-Long, RTH-Short, ETH-Long, ETH-Short

Bar to claim Phase 2 success:
- AUC OOS > 0.60 AND
- Top-decile economic edge > $20/trade vs population baseline AND
- Edge present in at least 3 of 4 stratum × side cells AND
- No look-ahead audit issues (verify via parity harness on a sample)

## Out of scope

- Production strategy backtest in NT (separate work order if Phase 2
  succeeds)
- Bracket optimization beyond v2's existing 4 brackets
- Threshold-stacking with prior-checkpoint scores (later if needed)

## Output

```
results/
  cohort_long.parquet              # all (event_id, T) rows with label + features
  phase1_descriptive.parquet       # one row per (T, stratum) with rate + PnL
  PHASE1_REPORT.md                 # written summary + verdict
  # Phase 2 outputs (only if scaffolded):
  phase2_oos_predictions.parquet
  phase2_decile_table.parquet
  PHASE2_REPORT.md
```

## Files

- `collect.py` — assemble cohort from v2 parquets, compute label
- `analyze_phase1.py` — Phase 1 descriptive analysis
- `train_phase2.py` — Phase 2 LightGBM training (run only if Phase 1
  shows signal)
- `run_phase1.py` — Phase 1 CLI orchestrator
- `run_phase2.py` — Phase 2 CLI orchestrator (separate by design)
