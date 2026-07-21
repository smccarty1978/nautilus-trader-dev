# Look-Ahead & Timestamp Audit v3

**Date:** 2026-06-11
**Scope:**
- `studies/regime_state_transition_atlas/build_state_rows.py`
- `studies/regime_state_transition_atlas/build_forward_labels.py`
- `studies/regime_state_transition_atlas/query_similar_states.py`
- `studies/regime_state_transition_atlas/analyze_state_memory.py`
- `studies/regime_state_transition_atlas/prototype_policy.py`

**Auditor:** lookahead-auditor v1

## Summary

- **Critical:** 3
- **Warning:** 3
- **Note:** 1

---

## Critical Findings

### 1. [B2 / C1 / D1] build_forward_labels.py:178, 209, 274 — First 1s Tick (Triggering Bar) Leakage in Forward Labels & Races

**Description:**
The forward label evaluator logs the 1s ticks starting from the one that triggered the 1m bar close at receipt time. In `on_1s`, the triggering tick is appended to all active checkpoints:
```python
154:         for cp in self._active_checkpoints:
155:             cp["path"].append((ts, o, h, l, c, reg_1m))
```
Because the decision to trade is made *after* this 1s bar has fully closed (receipt time e.g., `10:01:01` for the bar covering `[10:01:00, 10:01:01)`), the strategy cannot execute until the open of the *second* 1s bar of the new period (`10:01:01`). 

However, by including the first 1s bar `[10:01:00, 10:01:01)` in `path` and `next_1m_ticks` for forward label calculations:
- If a profit target or stop loss is hit during that first 1s bar, the race is marked resolved inside the triggering bar (which occurred *before* the trade started).
- If a new regime high/low is made during that first 1s bar, `next_bar_makes_continuation` will be marked as `1`, even though the strategy was not yet in the market.

This is a critical look-ahead leakage. The training labels assume the trade is active during the first 1s bar, which is physically impossible under causal execution.

**Recommended fix (do not apply):**
Filter out the first tick of the path for all label and race evaluations. Specifically, only evaluate ticks where `b[0] > checkpoint_ts + 1 * NS_PER_S` (assuming a +1s delta) or drop the first item in the path if it belongs to the triggering bar.

---

### 2. [D1] build_forward_labels.py:267, 338, 404, 410 — Train/Serve Skew due to `checkpoint_px` Baseline in Labels

**Description:**
In `prototype_policy.py`, the strategy has been updated to execute causally using `next_1s_open` (the open price of the second 1s bar of the next period) as the entry price. 

However, in `build_forward_labels.py`, the target labels (e.g. forward PnL, MFE/MAE excursions, and target/stop races) are still calculated using `checkpoint_px` (the 1m bar close price) as the baseline:
```python
404:         forward_pnl_atr = (regime_exit_px - checkpoint_px) * d / atr
```
This introduces a severe train/serve skew. The similarity scores and predicted probabilities output by the KNN model are trained to predict outcomes relative to `checkpoint_px`, but the strategy executes and realizes PnL relative to `next_1s_open`. 

**Recommended fix (do not apply):**
Change the baseline price for all forward labels, races, and excursions in `build_forward_labels.py` from `checkpoint_px` to `next_1s_open`.

---

### 3. [C4 / D1] prototype_policy.py:348-349 — Non-Causal Threshold Fallback for Year 2022

**Description:**
For `year == 2022`, the training years are set to `[2021]`. However, since 2021 scoring was skipped in `analyze_state_memory.py` to resolve 2021 look-ahead leaks, `df_scored` contains zero records for the year 2021. 

Consequently, `df_train` is empty, triggering the fallback branch:
```python
348:                 if len(df_train) == 0:
349:                     df_train = df_scored[df_scored["year"] == year].copy()
```
This causes the 2022 backtest to compute the entry/exit percentile thresholds (`enter_thr` and `exit_thr`) on the 2022 score distribution itself. This leaks future score distribution information to past trading decisions during the 2022 backtest.

**Recommended fix (do not apply):**
Use a static historical threshold calibrated on a separate pilot set for the first trading year, or use expanding-window statistics starting from a minimum sample size rather than falling back to the query year's own scores.

---

## Warnings

### 1. [F1] build_state_rows.py:319 — RTH Session Classification Shifted by 1 Minute due to Close-Time Binning

**Description:**
The Chicago RTH/ETH session classification uses the 1m bar's close timestamp:
```python
316:         ct_dt = pd.Timestamp(int(completed_1m.close_ts), tz="UTC").tz_convert(CT)
317:         date_str = ct_dt.strftime("%Y-%m-%d")
318:         min_ct = ct_dt.hour * 60 + ct_dt.minute
319:         is_rth = int(RTH_START_MIN <= min_ct < RTH_END_MIN)
```
Because it uses close timestamps, the boundary checks lead to a 1-minute shift:
- The `08:29` bar (which covers `08:29` to `08:30` and is entirely ETH) has a close timestamp of `08:30:00` (`min_ct = 510`). It is incorrectly marked as `is_rth = 1`.
- The `14:59` bar (which covers `14:59` to `15:00` and is the final minute of RTH) has a close timestamp of `15:00:00` (`min_ct = 900`). It is incorrectly marked as `is_rth = 0` (ETH).

**Recommended fix (do not apply):**
Adjust the boundary check to reflect close-time semantics: `RTH_START_MIN < min_ct <= RTH_END_MIN` (so `510 < min_ct <= 900`).

---

### 2. [E4] build_forward_labels.py:182 — 1-Second Look-Ahead Fill on Gapped Minutes

**Description:**
The executable fill price fallback:
```python
182:             next_1s_open = next_1m_ticks[1][1] if len(next_1m_ticks) > 1 else next_1m_ticks[0][1]
```
will fall back to the first tick's open price (`next_1m_ticks[0][1]`) if there is only one tick in the next minute (a data gap during illiquid overnight periods). This executes the fill 1 second before the 1m bar close was actually registered at receipt time.

**Recommended fix (do not apply):**
Gate the entry such that we do not fill if `len(next_1m_ticks) <= 1`, or use a default fill price from the next available tick in the catalog.

---

### 3. [A1] build_state_rows.py:298 & build_forward_labels.py:131 — TimeframeAggregator Aggregates on `ts_event` instead of `ts_init`

**Description:**
Both scripts pass `tse` (event timestamp, i.e., open time) to the aggregator:
```python
298:         self._agg.on_1s_bar(int(tse), o, h, l, c, v)
```
In NautilusTrader, this can cause alignment issues if `ts_init_delta = 0` or if event ordering is not strictly monotonic. Additionally, since the path logs use `tsi` (`ts_init`) for filtering, any mismatch in catalog deltas will result in off-by-one errors during label evaluations.

**Recommended fix (do not apply):**
Aggregate using the init timestamp (`tsi`) to remain consistent with close-time aggregation.

---

## Notes

### 1. [B2] build_state_rows.py:355-357 — Unused `pullback_depth_current_bar` Calculation

**Description:**
The variable `pullback_depth_current_bar` is calculated at lines 355-357 but is never exported to the feature dictionary `f`.

**Recommended fix (do not apply):**
Either remove the dead calculation or export it as `bar_max_pullback_depth_atr` to capture intra-bar excursions.

---

## Clean Checks (Verified Prior Fixes)

- **C1/C2 (Baseline Fix):** Clean. `build_forward_labels.py` correctly uses `checkpoint_high_actual` / `checkpoint_low_actual` instead of the stale prior variables.
- **C3/C4 (OOS Leakage):** Clean. `check_lift_stability` is strictly limited to IS years (`[2021, 2022, 2023, 2024]`), and cell selection inside `analyze_state_memory.py` is gated on `lift_is >= 0.05` and sorted by `is_lift`.
- **E4 (Back-Dating Exits):** Clean. Regime exits in `prototype_policy.py` execute causally at the `next_1s_open` of the first bar of the new regime, resolving back-dating.
- **E4 (Benchmark Entry):** Clean. The benchmark entry price now uses the causal entry mapping (`c_info["entry_px"]`), resolving the 1-minute entry look-ahead.
- **B7 (Standardization Leakage):** Clean. skipping 2021 scoring in `analyze_state_memory.py` successfully prevents leaking 2021 stats.
- **D1 (2026 Walk-Forward Training Set):** Clean. Training years are dynamically built up to the query year, correctly incorporating 2025 into the 2026 backtest training set.
- **B3/D1 (Volume Percentiles):** Clean. Deque maxlen is set to 20, and the volume is appended after snapshot features are evaluated, preventing self-contamination.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*

**Sign-off:** 2026-06-11T21:40:00-05:00 | Scope Hash: `c59d83dfa3e9c70b8f154ea2ff488e0b2401831826b15ef98fdf0b07b3debe9a`
