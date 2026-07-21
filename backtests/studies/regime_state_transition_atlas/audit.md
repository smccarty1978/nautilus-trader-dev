# Look-Ahead & Timestamp Audit

**Date:** 2026-06-11
**Scope:**
- `studies/regime_state_transition_atlas/build_state_rows.py`
- `studies/regime_state_transition_atlas/build_forward_labels.py`
- `studies/regime_state_transition_atlas/query_similar_states.py`
- `studies/regime_state_transition_atlas/analyze_state_memory.py`
- `studies/regime_state_transition_atlas/prototype_policy.py`
**Auditor:** lookahead-auditor v1

## Summary

- **Critical:** 2
- **Warning:** 3
- **Note:** 1

---

## Critical findings

### [C1/C2] build_forward_labels.py:185-193 & 212-222 — Stale Baseline for Future Continuation & Recovery Labels

The forward label evaluator uses the stale parameter `checkpoint_high_prior` (and `checkpoint_low_prior`) as the baseline to classify future continuation and recovery events:
```python
185:                 next_bar_makes_continuation = int(next_high > checkpoint_high_prior)
```
and:
```python
212:                     n_makes_c = int(max_h_N > checkpoint_high_prior)
213:                     n_recover = int(max_h_N >= checkpoint_high_prior)
```
`checkpoint_high_prior` holds the regime high *prior* to the current bar's close. If the current bar makes a new regime high, the true regime high at the checkpoint is the current bar's high (which is higher than the prior).
Using `checkpoint_high_prior` as the reference for the next bar(s) means a future bar that does not exceed the current bar's high but does exceed the prior bar's high will be incorrectly marked as a continuation/recovery. This introduces a severe look-ahead label corruption, making the model look like it has a high-probability continuation edge when it is actually just classification inside the current bar's range.

**Recommended fix (do not apply):** Update the baseline in `evaluate_checkpoint` to use the actual regime high at the checkpoint. This can be resolved by using the current bar's high/low directly or extracting `checkpoint_high_actual` (which would compare `completed.high` vs `checkpoint_high_prior`). For example, in `on_bucket_closed`, snap `"checkpoint_high_actual": max(self._1m_regime_high_prior, completed.high)` and use this as the baseline for all forward continuation/recovery comparisons.

### [C3/C4/D2] analyze_state_memory.py:280-281 & 45-50 — Out-of-Sample (OOS) Data Leakage in Model/Cell Selection

The script filters "top stable cells" based on their performance in the OOS (out-of-sample) validation period (2025–2026) using the `check_lift_stability` function:
```python
280:             stable = check_lift_stability(df_all, sub.index, label, base_rates_by_year, 1)
281:             if stable and lift_oos >= 0.05:
```
The `check_lift_stability` function explicitly peeks at the OOS years:
```python
45:     # Check OOS years
46:     for y in oos_years:
47:         val_y = sub[sub["year"] == y][label_col].mean()
48:         lift = val_y - base_rates_by_year[y][label_col]
49:         if np.sign(lift) != target_lift_dir:
50:             return False
```
This is a critical data-snooping violation. Model or category selection MUST be based strictly on in-sample (IS) data. Peeking at OOS years to filter and validate "stable" cells completely invalidates the OOS period as a true holdout set, resulting in severely inflated and non-replicable OOS lift metrics.

**Recommended fix (do not apply):** Restrict `check_lift_stability` and cell selection criteria strictly to the In-Sample dataset (years < 2025). The OOS dataset must only be used for final, un-gated performance evaluation of the cells selected in-sample.

---

## Warnings

### [E4] prototype_policy.py:80-87 & 55-73 — Optimistic Execution Fill Pricing

The prototype backtest simulates entering and exiting positions at the exact close price of the 1m bar that generated the signal:
```python
80:                 active_trade = {
81:                     "regime_id": r_id,
82:                     "entry_ts": ts,
83:                     "entry_px": px,  # Close price of bar i
```
and:
```python
55:                 if score <= exit_threshold:
56:                     pnl_usd = (px - active_trade["entry_px"]) * direction * 20.0  # Close price of bar i
```
Because the similarity score is calculated at the close of bar `i`, the trade cannot be filled at the close of bar `i`. It must be filled at the open (or first tick) of bar `i+1`. This introduces a train/serve consistency mismatch and optimistic fill pricing. Furthermore, the offline forward labels (races, excursions) are calculated starting from `checkpoint_px` (the close price), which creates a train/serve skew if a live strategy gets filled at the next bar's open.

**Recommended fix (do not apply):** Modify `run_policy_backtest` to enter at the next bar's open price. For a robust evaluation, offline label calculations in `build_forward_labels.py` should also use the open of the first 1s tick in the path as the trade entry price, rather than the 1m bar's close price.

### [C4/D1] prototype_policy.py:289-291 — Future Leakage in Static Walk-Forward Thresholds

The entry, hold, and exit thresholds are computed statically on the entire In-Sample (IS) dataset (2022–2024):
```python
289:     enter_threshold = np.percentile(scores_is, 80)
290:     hold_threshold = np.percentile(scores_is, 50)
291:     exit_threshold = np.percentile(scores_is, 30)
```
These static thresholds are then applied to backtest the early years of the IS period (e.g. 2022). This leaks future score distribution information to past trading decisions. If market regimes shift and the distribution of similarity scores changes over the three-year period, a historical trader would not have had access to the 2022–2024 aggregate percentile scores in 2022.

**Recommended fix (do not apply):** Compute thresholds dynamically on a rolling or expanding walk-forward basis, using only scores computed up to the year/month being traded.

### [B3/D1] build_state_rows.py:55, 74, & 439-445 — Volume Average & Percentile Calculation Mismatches

1. **Window Size Mismatch:** The features are named `bar_volume_vs_20avg` and `volume_percentile_20` (suggesting a 20-period rolling window), but they are computed using the full history in `self.vols_1m` (which has a max size of 512):
```python
55:         self.vols_1m = deque(maxlen=512)
```
This causes a train/serve feature skew if a live implementation uses a 20-bar window.
2. **Current Value Contamination:** In `on_bar_closed` (line 74), the current bar's volume is appended to `self.vols_1m` *before* the percentile calculation in `_snapshot_features` is run. This means the current bar is compared to itself in the ranking denominator and rank sum:
```python
443:             rank = sum(v < bar_vol for v in vols_list)
444:             eq = sum(v == bar_vol for v in vols_list)
```

**Recommended fix (do not apply):** Set the deque maxlen to 20 if a 20-period average/percentile is intended. Furthermore, calculate the volume average and percentile features *before* appending the current bar's volume to the historical deque, or exclude the current bar from the calculation.

---

## Notes

### [B2] build_state_rows.py:353-356 — Unused pullback_depth_current_bar Calculation

The local variable `pullback_depth_current_bar` is calculated at the end of the pullback state block:
```python
353:             pullback_depth_current_bar = max(0.0, self._1m_regime_high_prior - l) / atr_ref
354:         else:
355:             pullback_depth_current_bar = max(0.0, h - self._1m_regime_low_prior) / atr_ref
```
However, this variable is never used or exported in the feature map `f`. The feature map instead exports `current_pullback_depth_atr` using `pullback_val` (which is based on the bar close `c`, not the bar extreme `l`/`h`).

**Recommended fix (do not apply):** Either export `pullback_depth_current_bar` as an additional feature (representing the max intra-bar pullback depth) or remove the unused calculation.

---

## Clean checks

- **A1 (Timestamp Indexing):** Clean. The TimeframeAggregator closes and registers 1m buckets based on 1s event times, and the features snap `bar_ts` to the close timestamp (`completed_1m.close_ts`), preserving close-time semantics.
- **A2 (Catalog Deltas):** Clean. Verified in `archive/scripts/build_v0_multi_year_catalog.py` that `ts_init_delta` is correctly configured: 1s for 1s bars, 60s for 1m bars, and 300s for 5m bars.
- **A3 (Causal Current Price):** Clean. No future bar index lookups are performed for the current price in `build_state_rows.py` or the backtest.
- **A5 (Timezone Safety):** Clean. Conversions to Central Time are explicit and UTC-aware (`completed_1m.close_ts` converted from UTC to America/Chicago).
- **B1 (Causal Rolling):** Clean. No rolling or expanding windows use `center=True` or leak future price values.
- **B4 (Shift Lags):** Clean. No negative lags are used for feature construction; they are correctly isolated to label construction.
- **B5 (Forward Fill):** Clean. No `.ffill()` or `.bfill()` operations leak future values into past timestamps.
- **E5 (Warmup continuous updates):** Clean. The 5-day lead-in period provides sufficient warmup for 1m indicators (EMA and ATR) to stabilize before the recorded year starts.

---

*Sign-off: 2026-06-11T19:35:00-05:00 | Scope SHA-256 Hash: 9ca8df981db87e742cbbd4efd22a5789f64bf87b686d1b28d052a514d3c6cb19*
*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*
