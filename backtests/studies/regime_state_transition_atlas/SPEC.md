# NQ Regime State Transition Atlas Specification

This specification documents the causal state features, forward labels, neighbor similarity metric, scoring policy, and backtest rules for the NQ 1m Regime State Transition Atlas.

## 1. Directory Structure

```text
studies/regime_state_transition_atlas/
  SPEC.md
  build_state_rows.py
  build_forward_labels.py
  analyze_state_memory.py
  query_similar_states.py
  prototype_policy.py
  results/
    state_rows.parquet
    forward_labels.parquet
    state_memory_summary.md
    similar_state_examples.md
    top_state_cells.parquet
    policy_backtest_results.md
```

## 2. Causal State Features (state_rows.parquet)

Snapped at the close of each 1m bar ($t \in [1, 30]$) inside active 1m regimes:

1. **Identity:**
   - `regime_id`: unique integer id of the parent 1m regime.
   - `year`: integer year of the bar.
   - `date`: string date format `YYYY-MM-DD`.
   - `session`: string `"RTH"` or `"ETH"`.
   - `is_rth`: integer boolean (1 if 08:30–15:00 Chicago Central Time, else 0).
   - `direction`: integer regime direction (+1 for long, -1 for short).
   - `regime_start_ts`: nanoseconds timestamp of regime start.
   - `bar_ts`: nanoseconds timestamp of current bar close.
   - `bar_index_in_regime`: integer index from 1 to 30.
   - `bar1_confirmed_flag`: 1 if `made_continuation` was 1 on bar 1, else 0.

2. **Current Regime Progress (direction-normalized, ATR-normalized):**
   - `current_pnl_atr`: `(close - entry_px) * direction / entry_atr`
   - `mfe_so_far_atr`: `(regime_high - entry_px) * direction / entry_atr` (for long)
   - `mae_so_far_atr`: `(entry_px - regime_low) * direction / entry_atr` (for long)
   - `pullback_from_peak_atr`: `max(0, mfe_so_far_atr - current_pnl_atr)`
   - `max_pullback_depth_so_far_atr`: max pullback recorded so far.
   - `progress_efficiency_so_far`: `mfe_so_far_atr / (mfe_so_far_atr + mae_so_far_atr)` (0.0 if denom <= 0)
   - `mfe_mae_ratio_so_far`: `mfe_so_far_atr / mae_so_far_atr` (0.0 if mae <= 0)
   - `regime_age_bars`: same as `bar_index_in_regime`.

3. **Current Bar Anatomy (direction-normalized):**
   - `bar_return_atr`: `(close - open) * direction / entry_atr`
   - `bar_range_atr`: `(high - low) / entry_atr`
   - `bar_body_atr`: `abs(close - open) / entry_atr`
   - `bar_body_pct`: `abs(close - open) / (high - low)` (0.0 if range <= 0)
   - `bar_close_location`: `(close - low) / (high - low)` if direction=1 else `(high - close) / (high - low)`
   - `bar_direction_aligned`: `sign(close - open) * direction`
   - `upper_wick_pct`: `(high - max(open, close)) / range` for long, `(min(open, close) - low) / range` for short.
   - `lower_wick_pct`: `(min(open, close) - low) / range` for long, `(high - max(open, close)) / range` for short.

4. **Continuation State:**
   - `made_continuation_this_bar`: 1 if current bar made a new high (long) or low (short) relative to regime history prior to current bar.
   - `bars_since_last_continuation`: count of bars since last continuation.
   - `consecutive_no_continuation_bars`: count of consecutive failed continuation bars.
   - `continuation_count_so_far`: number of continuations in this regime through current bar close.
   - `prior_bar_made_continuation`: `made_continuation` of the prior bar in the regime.
   - `first_bar_made_continuation`: `made_continuation` on bar 1 (constant for regime).
   - `first_two_bars_made_continuation`: 1 if both bar 1 and bar 2 made continuation, else 0 (constant for regime for bar >= 2).

5. **Pullback / Recovery State:**
   - `bar1_pullback_depth_atr`: pullback depth at the close of bar 1 (constant for regime).
   - `current_pullback_depth_atr`: same as `pullback_from_peak_atr`.
   - `deep_pullback_gt_0p25`: 1 if pullback > 0.25 ATR, else 0.
   - `deep_pullback_gt_0p50`: 1 if pullback > 0.50 ATR, else 0.
   - `deep_pullback_gt_0p75`: 1 if pullback > 0.75 ATR, else 0.
   - `recovered_prior_peak_this_bar`: 1 if prior pullback > 0 and current high/low retouched or exceeded the prior MFE peak.
   - `recovered_above_prior_bar_midpoint`: 1 if current close is above prior bar midpoint (direction-normalized).
   - `recovered_above_prior_bar_close`: 1 if current close is above prior bar close (direction-normalized).

6. **Recent Sequence Encoding:**
   - Letters: `C` (continuation), `P` (pullback/no continuation but close positive vs entry), `F` (failure/close negative vs entry), `R` (recovery close positive vs prior close and prior pullback > 0).
   - `last_1_bar_pattern`
   - `last_2_bar_pattern`
   - `last_3_bar_pattern`
   - `last_4_bar_pattern`

7. **5s Context:**
   - `regime_5s_aligned`: 1 if 5s regime matches 1m direction, else 0.
   - `regime_5s_direction`: 5s regime direction (+1, -1, or 0).
   - `5s_flip_count_since_1m_start`: flip count of 5s regime.
   - `5s_opposed_flip_count_since_1m_start`: flip count of 5s regime opposed to 1m direction.
   - `5s_current_aligned_duration_s`: seconds aligned with 1m direction.
   - `5s_flips_last_60s`: flips in the last 60 seconds.
   - `5s_flips_last_120s`: flips in the last 120 seconds.

8. **EMA / Slope Context (direction-normalized, entry-ATR normalized):**
   - `distance_to_ema{p}_atr` (for p in 3, 9, 13, 21)
   - `ema{p}_slope_atr`
   - `ema{p}_slope_change` (slope current - slope prior)
   - `ema3_ema9_spread_atr`, `ema9_ema21_spread_atr`

9. **Volume / Participation:**
   - `bar_volume`
   - `bar_volume_vs_20avg`
   - `volume_percentile_20`
   - `signed_volume_proxy`: `volume * sign(close - open) * direction`
   - `cum_signed_volume_since_regime_start`
   - `aligned_volume_since_regime_start`
   - `opposed_volume_since_regime_start`
   - `aligned_opposed_volume_ratio`

---

## 3. Forward Labels (forward_labels.parquet)

Computed starting from the open of the first 1s bar AFTER the 1m bar close:

1. **Next-Bar Transition Labels:**
   - `next_bar_makes_continuation`: 1 if next bar makes a new high/low beyond the MFE peak of checkpoint.
   - `next_bar_close_positive`: 1 if next bar close is positive relative to checkpoint close.
   - `next_bar_return_atr`: return of next bar relative to checkpoint close.
   - `next_bar_recovers_prior_peak`: 1 if next bar high/low retouches checkpoint peak MFE.

2. **Next-N-Bar Labels (for N in 2, 3, 5):**
   - `next_N_bars_make_continuation`
   - `next_N_bars_recover_prior_peak`
   - `next_N_bars_net_positive`
   - `next_N_bars_max_favorable_atr`
   - `next_N_bars_max_adverse_atr`

3. **First-Passage Races (using 1s path):**
   - `pt025_before_sl025`
   - `pt050_before_sl050`
   - `pt100_before_sl100`
   - `pt200_before_sl100`
   - `race_resolution_time_s`
   - `race_resolution_reason`

4. **Regime-End Labels:**
   - `forward_pnl_to_regime_exit_atr`
   - `forward_pnl_to_regime_exit_dollars`
   - `future_mfe_from_here_atr`
   - `future_mae_from_here_atr`
   - `regime_exit_in_next_1_bar`, `regime_exit_in_next_2_bars`, `regime_exit_in_next_3_bars`
   - `remaining_regime_bars`

---

## 4. State Memory Query Engine (query_similar_states.py)

### Similarity Features

Continuous Features (Numeric):
- `current_pnl_atr`
- `mfe_so_far_atr`
- `mae_so_far_atr`
- `pullback_from_peak_atr`
- `consecutive_no_continuation_bars`
- `continuation_count_so_far`
- `5s_flip_count_since_1m_start`
- `ema9_slope_atr`
- `ema9_slope_change`
- `distance_to_ema9_atr`
- `volume_percentile_20`

Categorical/Exact Match Features:
- `bar_index_in_regime`
- `last_3_bar_pattern`
- `regime_5s_aligned`

### Distance Metric
For KNN, the numeric features are z-score normalized using the mean and standard deviation of the **In-Sample** (2021–2024) training dataset.
Euclidean distance is computed on the scaled numeric features.

---

## 5. Prototype Policy (prototype_policy.py)

### Scoring Formula
`score = 0.35 * P(pt050_before_sl050) + 0.25 * P(next_bar_makes_continuation) + 0.25 * P(recover_peak_next_3) + 0.15 * normalized_forward_pnl`

where:
- `normalized_forward_pnl` is scaled robustly on the IS dataset to range `[0, 1]` using min-max scaling of the neighbor outcomes: `(mean_fwd_pnl - min_is_pnl) / (max_is_pnl - min_is_pnl)`.

### Policy Thresholds
- `enter_threshold`: top 20% of IS scores.
- `hold_threshold`: median IS score.
- `exit_threshold`: bottom 30% of IS scores.

### Execution Rules
- Position size: 1 contract.
- Direction: matching parent 1m regime direction.
- Entries filled on the open of the first 1s bar after the 1m bar close if `flat` and `score >= enter_threshold`.
- Exits filled on the open of the first 1s bar after `score <= exit_threshold` or opposing 1m regime flip.
