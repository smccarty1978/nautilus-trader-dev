# Look-Ahead & Timestamp Audit (Keltner Fade Study)

**Date:** 2026-06-03T05:21:17Z
**Scope:**
- `studies/keltner_fade/collect.py`
- `studies/keltner_fade/keltner.py`
- `studies/keltner_fade/run_keltner_study.py`
- `collectors/collector_v2/registry.py`
- `collectors/collector_v2/aggregator.py`
- `collectors/collector_v2/regime_engine.py`
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 1
- Warning: 3
- Note: 2

---

## Critical findings

### [A1/State] collect.py:127-142 — Timeframe Aggregator Order & Lookback Inconsistency

In `TimeframeAggregator`, timeframes are processed in the loop order: `("30s", "3m")`. Therefore, `"30s"` completes first, calling `_on_bucket_closed("30s")` and appending the completed bar to `self._lookback_30s`. At this specific microsecond, the `"3m"` bucket for the same boundary has not yet closed, so the lookback buffer records the *old* (previous) Keltner band values.

However, in `on_1s_bar`, `_on_30s_bar_closed` is called *after* `self._aggregator.on_1s_bar(...)` has finished processing *both* timeframes. By this time, the `"3m"` bucket has finished closing and has updated `self._last_keltner_upper`.

Consequently, in `_check_entry_trigger`, the contemporaneous 30s bar is compared against the *new* Keltner band values, whereas if it is looked up in the lookback buffer via `_check_filter2`, it is compared against the *old* Keltner band values. This is a state alignment inconsistency at the 3-minute boundaries.

**Recommended fix (do not apply):**
Either process `"3m"` before `"30s"` in the aggregator, or defer the `_lookback_30s.append` call until after all timeframes in `on_1s_bar` have finished updating, ensuring the lookback buffer records consistent contemporaneous indicator values.

---

## Warnings

### [F3] collect.py:49 — Unimplemented `rth_only` Filter

The configuration parameter `rth_only` is defined in `KeltnerFadeConfig` but is never referenced or implemented in the strategy logic. The strategy will trade 24/7 (including ETH/overnight hours) even if `rth_only=True` is specified in the config.

**Recommended fix (do not apply):**
Check `self._cfg.rth_only` inside `_on_30s_bar_closed` or `_check_entry_trigger` and return early if it is set to `True` and the current time is outside RTH (using `self._is_rth_minute`).

### [E5] run_keltner_study.py:129-130 — No Lead-In/Warmup Period in Study Runner

The runner `run_keltner_study.py` loads NQ 1s bars starting exactly on `2025-01-01` without any lead-in period. The Keltner Channel requires 20 3-minute bars (1 hour) to start trading, but at only 20 bars of warmup, the span-20 EMA has not fully converged. The lack of historical lead-in data leads to un-converged indicators and distorted trading behavior in the first trading hours of the year.

**Recommended fix (do not apply):**
Modify `run_keltner_study.py` to load data starting 5 days prior to the backtest period (similar to the NQ runner's `--lead-in-days` parameter) to allow the EMA to fully stabilize.

### [A3] collect.py:143-152 — Registry Bypassed for 3m Timeframe

While `CompletedBarRegistry` is designed to act as a centralized, audited air-gap for MTF data (preventing look-ahead bias), the strategy bypasses it for the 3-minute Keltner channel features, writing and reading them directly from strategy fields (`self._last_keltner_basis`, etc.). This defeats the registry's provenance auditing.

**Recommended fix (do not apply):**
Instantiate a `RegimeStateEngine` for `"3m"`, register the completed 3m bars in the registry, and read the Keltner bands from the registry instead of local strategy fields.

---

## Notes

### [G2] collect.py:98-123 — Discontinuous Timeframe Aggregation on Gaps

In `TimeframeAggregator`, if there is a gap in 1s bars, the empty minutes are silently skipped. The indicators and rolling window will use the last 30 *active* bars rather than 30 *wall-clock* minutes. This can distort the temporal length of indicators during low-liquidity overnight sessions.

**Recommended fix (do not apply):**
If strict temporal alignment is desired, check for gaps between the current bin `b` and `self._bin` in `update`, and insert empty/flat bars to fill the gap.

### [A1] collect.py:117-121 — Safe One-Second Lag in Bar Closing

Buckets in `TimeframeAggregator` are only closed when the first bar of the *next* bucket arrives. This introduces a 1-second execution lag (e.g. evaluating 10:00:30 at 10:00:31). This is safe and causal but good to note.

**Recommended fix (do not apply):**
No action required as it is conservative, but be aware that the strategy trades 1 second late relative to a standard bar close.

---

## Clean checks

- **A1**: The strategy correctly uses `ts = bar.ts_init` (close time) instead of `ts_event` (open time).
- **A3**: No future lookups are used.
- **A4**: No timers or `TimeEvent` callbacks are used.
- **A5**: Timezone conversions (`_is_rth_minute`) are UTC-aware and converted properly using `astimezone`, ensuring safety against DST transitions.
- **B1**: No pandas rolling functions or `center=True` parameters are used.
- **B2**: Indicators are updated sequentially inside `_fold` using only completed bars.
- **B3**: Recursive indicators (ATR/EMAs) are sampled strictly at the end of the closed bar.
- **B4**: No shift operations or negative lags are present.
- **B5**: No forward-fill (`.ffill`) or backward-fill (`.bfill`) operations are used in the feature path.
- **B6**: No dataframe merges or joins across different frequencies are performed in the live path.
- **B7**: Indicators are calculated using strictly past data.
- **C1–C4**: No machine learning models, model inference, or cross-validation splits are used (rule-based strategy).
- **D1–D4**: Train/serve consistency is clean since features are computed live.
- **E1**: Bar subscription `NQ.XCME-1-SECOND-LAST-EXTERNAL` matches the loaded catalog data.
- **E2**: BarType properties match the loaded data.
- **E4**: Entry occurs at the next bar's open via market FOK orders, which is honest.
- **F1–F4**: RTH/ETH boundaries are correctly identified using Chicago Time and close-time timestamps.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*

**Scope Hash:** `86f12da30f7b0e271a39bfb1b79f64e1d1de78a05c742cf6302e1c3905c8b28f`
