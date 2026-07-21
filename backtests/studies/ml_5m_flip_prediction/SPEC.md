# ML 5m Flip Prediction — SPEC (v1)

> Phase 1 — dataset construction + no-model baseline scan. Derived from
> `ml_5m_flip_prediction_study_kickoff.md` plus decisions from the
> April 2026 review.

---

## Research question

> Given information known at a 1m signal or minute-boundary checkpoint,
> can we predict whether the 5m regime will flip into alignment with the
> signal direction within the next X seconds?

Primary horizon: **X = 300s**. Secondary horizons: 120, 180, 600.

---

## Locked-in design decisions

1. **Labels from 30s snapshot fields only** (`regime_5m_aligned_T_{T:03d}`).
   No reconstructed 5m-boundary labels. The ~30s visibility lag in the
   snapshots is treated as a real deployment constraint, not contamination.
2. **Minute-boundary candidate decision rows only** — T ∈
   {0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600}.
3. **Existing fields only** — use columns already present in
   `trades_all.parquet`. Collector is not re-run for v1.
4. **Strict per-row exclusion** — drop rows where
   `regime_5m_aligned_T_{T_d:03d} == 1` (already aligned at decision).
5. **Group-by-trade chronological split** — all rows of one trade stay in
   one fold. Year assigned from signal time: 2020–2023 train, 2024 val,
   2025 test.
6. **Pooled baseline model**, one LightGBM with `decision_checkpoint_s`
   as a feature. Per-checkpoint models only if baseline shows signal.
7. **Forbidden features** — no `forward_*`, no `regime_5m_flip_checkpoint`,
   no `t0_*` (forward from T0 fill), no `mae/mfe/pnl_from_t0_to_T_*`
   (forward from T0 fill), no `regime_exit_*`, no checkpoint fields at
   T > T_d.

---

## Candidate row generation

For each trade in `trades_all.parquet`, emit one row per decision
checkpoint T_d in {0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600}
if and only if:

- `alive_at_T_{T_d:03d} == 1`
- `fillable_at_T_{T_d:03d} == 1`
- `regime_5m_aligned_T_{T_d:03d} == 0`

Max rows: 11 × 113,970 = 1,253,670 candidates before exclusions.

---

## Label construction

For each decision row at T_d and horizon X ∈ {120, 180, 300, 600}:

```
target_5m_flip_within_X =
    1   if ANY T_f in (T_d, T_d+X], step 30s, has regime_5m_aligned_T_{T_f} == 1
    0   if ALL T_f in (T_d, T_d+X] have observable data AND none show aligned=1
    NaN if the trade dies (dead_before_T_{T_f}==1) for any T_f in the window
          before alignment was observed, OR T_d + X > 600 (out of collector range)
```

The "NaN if dies before observing alignment" rule handles censoring: we
did not observe what would have happened, so the label is missing.

### Horizon × decision-T availability

| Horizon | Usable T_d | Max rows/trade |
|---|---|---|
| 120s | 0..480 | 9 |
| 180s | 0..420 | 8 |
| 300s (**primary**) | 0..300 | 6 |
| 600s | 0 only | 1 |

Different horizons will have different usable subsets.

---

## Feature selection rules

### Root-level (per trade, same value across all decision rows)

Included:

- `atr_14`, `atr_at_signal`
- Flip bar anatomy: `flip_range_atr, flip_body_atr, flip_body_pct,
  flip_close_location, flip_upper_wick_pct, flip_lower_wick_pct,
  flip_volume, flip_vol_vs_20avg, flip_close_vs_prior_close_atr,
  flip_high_vs_prior_high_atr, flip_low_vs_prior_low_atr,
  flip_bar_bullish_volume_pct, flip_bar_vol_rank_20`
- Bar+1 anatomy: `bar1_range_atr, bar1_body_atr, bar1_body_pct,
  bar1_close_location, bar1_upper_wick_pct, bar1_lower_wick_pct,
  bar1_volume, bar1_vol_vs_flip_vol, bar1_vol_rank_20, bar1_hh_amount_atr,
  bar1_close_vs_flip_close_atr, bar1_close_above_flip_close,
  bar1_close_above_50pct_range, bar1_bullish_volume_pct`
- Two-bar sequence: `two_bar_range_atr, two_bar_body_atr,
  two_bar_close_vs_open_pct, two_bar_volume_total, two_bar_vol_vs_40avg,
  flip_low_to_bar1_high_atr`
- Pre-flip / 1m regime context: `prior_regime_duration_bars,
  consecutive_trend_bars_pre_flip, pre_flip_3bar_body_direction,
  pre_flip_3bar_range_atr, pre_flip_5bar_range_atr, pre_flip_volume_trend,
  regime_flips_last_30min, regime_flips_last_60min`
- 1m MA context: `price_vs_sma20_atr, price_vs_sma50_atr, sma20_slope_atr,
  sma20_vs_sma50_atr, sma50_slope_atr, ema3_slope_atr, ema_spread_atr,
  ema3_ema9_spread_atr`
- 1m volume: `vol_1m_20avg, vol_ratio_up_down_10bar,
  vol_ratio_up_down_20bar, vol_acceleration_5bar, high_vol_bar_count_10,
  cumulative_volume_bias_10`
- Session at signal: `is_rth, hour_of_day, minute_of_hour,
  minutes_since_rth_open, distance_from_session_high_atr,
  distance_from_session_low_atr`
- State at signal: `regime_30s_aligned_t0, regime_5m_aligned_t0`
- Direction: `signal_direction`

### Checkpoint-level at T_d (renamed to drop `_T_{T_d:03d}` suffix)

Included:

- ATR: `atr_14_at_T`
- 30s context: `regime_30s_T, regime_30s_aligned_T,
  regime_30s_duration_bars_T, ema3_slope_30s_atr_T, ema_spread_30s_atr_T,
  price_vs_sma20_30s_atr_T, bar_range_30s_current_atr_T`
- 5m context: `regime_5m_T, regime_5m_duration_bars_T,
  ema3_slope_5m_atr_T, ema_spread_5m_atr_T, price_vs_sma20_5m_atr_T,
  regime_5m_changed_during_delay_by_T`
- 1m context: `regime_1m_T`
- Micro: `micro_same_dir_count_12s_T, micro_opp_dir_count_12s_T,
  micro_aligned_T, micro_opposing_T, micro_net_return_atr_T,
  micro_range_compression_T, micro_body_pct_avg_T`
- Continuation: `continuation_count_since_signal_T,
  consecutive_continuation_bars_T, bars_since_last_continuation_T,
  checkpoint_bars_since_signal_1m_T`
- Session at decision: `is_rth_T, hour_of_day_T, minute_of_hour_T,
  minutes_since_rth_open_T, distance_from_session_high_atr_T,
  distance_from_session_low_atr_T`
- Volume: `vol_total_30s_recent_T, vol_vs_20avg_30s_T`

### Decision-derived

- `decision_checkpoint_s` (= T_d in seconds; used as a feature)

### Dropped (zero-variance or eligibility-redundant)

- `alive_at_T, fillable_at_T` — always 1 by eligibility
- `regime_5m_aligned_T` — always 0 by eligibility
- `regime_5m_flipped_to_align_by_T` — always 0 by eligibility (signal
  aligned_t0=0 AND T aligned=0 → flipped_to_align_by_T=0)
- `dead_before_T` — always 0 by eligibility
- `checkpoint_elapsed_s_T` — redundant with `decision_checkpoint_s`

### Dropped (forbidden by no-lookahead rule)

- All `forward_*` columns
- All `t0_*` columns (forward from T0 fill)
- All `mfe_from_t0_to_T_*`, `mae_from_t0_to_T_*`, `pnl_from_t0_to_T_*`
  columns (hypothetical T0-entry forward path)
- `regime_5m_flip_checkpoint` (post-hoc clipped, demonstrably lookahead)
- `regime_exit_price, regime_exit_time`
- All `_T_{T:03d}` checkpoint fields where T > T_d
- `checkpoint_entry_fill_price_T, checkpoint_entry_fill_time_T,
  checkpoint_time_T` — trade-state metadata not useful as features

### Dropped (spec-listed but absent from collector output)

These are in `ml_5m_flip_prediction_study_kickoff.md` but not in
`trades_all.parquet`. Documented here as v1 gaps; candidates for a
collector extension if v1 baseline justifies it:

- `prior_regime_mfe_atr` (spec A — pre-flip regime context)
- `bars_since_last_flip` (spec A — pre-flip)
- `avg_regime_duration_last_5` (spec A — pre-flip)
- `bar1_confirmed_hh_ll` (spec A — bar+1; confirmation is implicit,
  all rows in v3 collector are confirmed by construction)

Final feature counts will be logged in the QA output.

---

## Metadata columns (kept but not used as features)

- `event_id` (= `signal_ts`, globally-unique key — use for grouping/splits)
- `trade_id, signal_time, signal_ts`  — `trade_id` is a per-year counter
  and collides across year boundaries; use `event_id` for group-by-trade
  integrity
- `year, date, session`
- `decision_ts` (= signal_ts + T_d × 1e9 ns, int64 nanoseconds UTC)
- `decision_fill_ts` (= decision_ts + 30e9 ns)

---

## Train/val/test split

- **Train**: trades where signal year ∈ {2020, 2021, 2022, 2023}
- **Val**: trades where signal year == 2024
- **Test**: trades where signal year == 2025

Group-by-event enforced: all rows sharing the same `event_id`
(= `signal_ts`) stay in the same fold. Multiple decision-T rows per
event are valid; contamination is prevented by assigning fold at event
level, not row. Do **not** group by `trade_id` — it is a per-year
counter that collides across year boundaries.

---

## Deliverables (v1)

Files:

```
studies/ml_5m_flip_prediction/
├── SPEC.md                                      (this file)
├── build_dataset.py
├── label_base_rates.py                          (phase 2)
├── feature_scan.py                              (phase 2)
├── baseline_model.py                            (phase 3)
├── tradeability_sanity.py                       (phase 3)
└── results/
    ├── ml_5m_flip_prediction_dataset.parquet
    ├── ml_5m_flip_dataset_qa.log                (phase 1 output)
    ├── ml_5m_flip_label_base_rates.log          (phase 2)
    ├── ml_5m_flip_feature_scan.log              (phase 2)
    ├── ml_5m_flip_baseline_models.log           (phase 3)
    └── ml_5m_flip_tradeability_sanity.log       (phase 3)
```

## Decision gate

Before any modeling (phase 3), review the QA log from phase 1 (dataset
build) and the label base rates + feature scan from phase 2.

If label base rates or feature scan show no separation worth learning,
**stop** at phase 2. Don't force a model on a signal that isn't there.
