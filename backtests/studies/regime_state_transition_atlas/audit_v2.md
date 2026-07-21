# Look-Ahead & Timestamp Audit v2

**Date:** 2026-06-11
**Scope:** 
- `studies/regime_state_transition_atlas/build_state_rows.py`
- `studies/regime_state_transition_atlas/build_forward_labels.py`
- `studies/regime_state_transition_atlas/query_similar_states.py`
- `studies/regime_state_transition_atlas/analyze_state_memory.py`
- `studies/regime_state_transition_atlas/prototype_policy.py`
- `collectors/collector_v2/aggregator.py`
- `collectors/collector_v2/registry.py`

**Auditor:** lookahead-auditor v1

## Summary

- **Critical:** 7
- **Warning:** 3
- **Note:** 2

---

## Critical Findings

### 1. [E4] prototype_policy.py:85, 211 — 1-Second Entry/Exit Look-Ahead Fill

The policy simulator fills trades on `next_open = row["next_1s_open"]`. In `build_forward_labels.py`, `next_1s_open` is the open price of the first 1s bar after the 1m bar close. However, because `TimeframeAggregator` only closes a 1m bucket when the first 1s bar of the next bucket completes, the decision is made *after* this 1s bar has fully closed. 

For example, when the 1s bar covering `[10:01:00, 10:01:01)` arrives at receipt time `10:01:01`, it triggers the close of the `10:00` 1m bar. The simulator then places a trade and fills it at the open of the `10:01:00` 1s bar (which occurred at `10:01:00`, 1 second in the past). This is a look-ahead fill.

**Recommended fix (do not apply):** Shift the fill price to the open of the *following* 1s bar (i.e., the second 1s bar of the next period, at `10:01:01`).

### 2. [E4] prototype_policy.py:34-38, 81-88 — Look-Ahead Regime-Exit Back-Dating

When a regime change is detected, the position is closed at `active_trade["regime_exit_px"]`, which corresponds to the close price of the last bar of the old regime. However, this regime flip is only detected when the first bar of the *new* regime closes (which is 1 bar in the future). 

Exiting at the old regime's close price back-dates the exit by 1 bar (60 seconds) and uses future information, since at the moment of the old regime's close, the strategy could not have known the regime had ended.

**Recommended fix (do not apply):** Exit the position at the open price of the first bar of the new regime once the flip is detected at the bar close.

### 3. [E4] prototype_policy.py:133-134 — Massive 1-Minute Look-Ahead in `always_start` Benchmark

The `always_start` benchmark enters a regime at the open of bar 1:
```python
133:         bar_ret = row["bar_return_atr"]
134:         px_entry = px - direction * bar_ret * atr
```
This evaluates to the open price of bar 1. However, the first checkpoint is only evaluated at the *close* of bar 1. This fills the benchmark entry 1 minute before the decision could have been made.

**Recommended fix (do not apply):** Change the entry price of the benchmark to the close of bar 1 or the open of the next bar.

### 4. [B7] analyze_state_memory.py:79-90 — In-Sample Standardization Look-Ahead Leakage in 2021

During the walk-forward scoring loop for the year 2021, the database `db` is set to the entire 2021 year. The means and standard deviations used to standardize both the database and the queries are computed over the full year 2021:
```python
79:         means = db[NUMERIC_COLS].mean()
80:         stds = db[NUMERIC_COLS].std().replace(0.0, 1.0)
```
This leaks future distribution statistics (volatility, average spread, average PnL) into past query standardization for the year 2021.

**Recommended fix (do not apply):** Skip scoring 2021 queries (using it only as training data for subsequent years), or use expanding-window statistics for 2021 queries.

### 5. [C4] analyze_state_memory.py:67-68 — Future Neighbor Leakage in 2021 Scoring

For `year == 2021`, the KNN database `db` is the entire 2021 dataset. Since there is no chronological filter, queries in 2021 can select neighbors from the future of 2021 (e.g. a query in January 2021 finding similar states in December 2021).

**Recommended fix (do not apply):** Enforce a time constraint `cand_sub["bar_ts"] < query_row["bar_ts"]` when scoring same-year queries.

### 6. [C4] prototype_policy.py:314 — Tainted 2021 Threshold/Normalization Parameters

Because 2021 predictions are tainted with future leakage, including 2021 in `train_years` for calculating percentiles (`enter_thr`, etc.) and min/max PnL normalization parameters for years 2022-2026 leaks the 2021 look-ahead bias into the threshold selection for all subsequent years.

**Recommended fix (do not apply):** Exclude 2021 from the training years or fix the 2021 scoring leakage.

### 7. [D1] analyze_state_memory.py:300 — Out-of-Sample Selection Leakage in `top_state_cells`

The script compiles `top_state_cells.parquet` and sorts it by `oos_lift` (which is the actual lift in the 2025-2026 out-of-sample period):
```python
300:         df_top = df_top.sort_values("oos_lift", ascending=False)
```
If any downstream selector or strategy uses this file to select cells, features, or rules, it introduces OOS leakage because the selection was made based on future OOS performance.

**Recommended fix (do not apply):** Sort the cells strictly by `is_lift` (In-Sample lift) and use the OOS metrics only for reporting.

---

## Warnings

### 1. [A1] build_state_rows.py:298, 569, 577 & build_forward_labels.py:131, 479, 487 — Aggregation on Event Timestamp (`ts_event`)

`TimeframeAggregator` uses `ts_event` (open time) rather than `ts_init` (close time) to aggregate 1s bars:
```python
298:         self._agg.on_1s_bar(int(tse), o, h, l, c, v)
```
In NautilusTrader, this can cause misaligned bars if the catalog has `ts_init_delta = 0` or if event ordering is not strictly monotonic.

**Recommended fix (do not apply):** Aggregate using `ts_init` of the 1s bars to align with close-time semantics.

### 2. [D1] prototype_policy.py:311-312 — Frozen Walk-Forward Training Set for 2026

When evaluating `year == 2026`, the training database is frozen at `[2021, 2022, 2023, 2024]` and does not include `2025`:
```python
311:         else:
312:             train_years = [2021, 2022, 2023, 2024] # Strictly IS for OOS years
```
This is a train-serve inconsistency, as a true walk-forward pipeline in 2026 would include 2025 data in the training set.

**Recommended fix (do not apply):** Include `2025` in `train_years` when `year == 2026`.

### 3. [G2] collectors/collector_v2/aggregator.py:140-157 — Data Gaps Can Distort Bar Timestamps

The aggregator only closes a bucket when a bar from a new bucket arrives. If there are long overnight or weekend gaps in 1s data, the 1m bar's `completed.close_ts` is set to the logical end of the minute, but the actual decision is delayed until the next tick arrives (possibly hours later). This can cause issues in live strategy timing or create distorted bars.

**Recommended fix (do not apply):** Implement a timer-based close or check the actual tick timestamp to handle gaps.

---

## Notes

### 1. [E5] build_state_rows.py:53 — No Warmup Gate for Checkpoints

The strategy has no explicit indicator-warmup gate. Although `run_year` uses `lead_in_days=5` to preload data, if the parent regime is active right at the start of the year, checkpoints will be written even if the EMAs have not fully stabilized.

**Recommended fix (do not apply):** Only snapshot checkpoints when `_fm.emas` have been updated for at least `period * 3` bars.

### 2. [F2] build_state_rows.py:180-275 — Volume and Price Accumulators Cross RTH Boundaries

Regime-specific accumulators (e.g. `_aligned_volume_since_regime_start`, `_1m_regime_high`) do not reset when crossing Chicago RTH/ETH boundaries.

**Recommended fix (do not apply):** Consider resetting volume accumulators or adding boundary-aware features.

---

## Clean Checks

- **A2** (ts_init_delta verified in `build_catalog.py` script as +1s, +60s, +300s).
- **B1** (No `center=True` rolling computations found in feature path).
- **B4** (No `.shift(-N)` or negative-lag operations in the feature path).
- **B5** (No forward-fill operations leaking future values into past timestamps).
- **B6** (Joins/merges between states and labels align correctly on `regime_id` and `bar_ts`).
- **C3** (Train/test splits are strictly temporal: IS is `< 2025`, OOS is `>= 2025`).
- **F3** (Timezone handling is explicit using `pytz.timezone("America/Chicago")`).

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*

**Sign-off:** 2026-06-11T21:20:19-05:00 | Scope Hash: `d7ae19f0775a4099bcf099df32e4d075b22b10a26d7fdfcbdfcb86e8efc9820f`
