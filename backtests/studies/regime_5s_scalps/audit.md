# Look-Ahead & Timestamp Audit

**Date:** 2026-06-11T19:30:32Z
**Scope:**
- `studies/regime_5s_scalps/run_5s_scalp_study.py`
- `studies/regime_5s_scalps/analyze_5s_scalps.py`
- `collectors/collector_v2/registry.py` (shared, read-only verification)
- `collectors/collector_v2/aggregator.py` (shared, read-only verification)
- `collectors/collector_v2/regime_engine.py` (shared, read-only verification)
- `studies/regime_5s_scalps/SPEC.md`

**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 6
- Note: 4

---

## Critical Findings

None. The core causal chain is intact. No look-ahead bias was found in the data path, feature snapshot, or path simulation.

---

## Warnings

### [W1 / A3] `run_5s_scalp_study.py:278` — `audit_provenance` hard-invariant guard never called before `_snapshot_features`

The `CompletedBarRegistry` exposes `audit_provenance(decision_ts)`, which raises `CausalityViolation` if any stored state has `close_ts > decision_ts`. This is the production hard gate used by collector_v2. In this study, `_snapshot_features` (called at line 278 inside `on_bucket_closed`) calls `self._reg.get("1m")` and `self._reg.get("5m")` without first calling `self._reg.audit_provenance(completed_5s.close_ts)`.

The ordering analysis (described in Clean Checks below) confirms the code is logically causal today, so this is not a current bug. However, the guard is the intended mechanical enforcement of that invariant. Without it, any future refactor to the aggregator TF iteration order or the callback dispatch sequence would silently remove the causality guarantee rather than loudly raising `CausalityViolation`.

**Recommended fix (do not apply):** At the top of `_snapshot_features`, before any `self._reg.get()` call, insert:
```python
self._reg.audit_provenance(completed_5s.close_ts)
```

---

### [W2 / F3] `run_5s_scalp_study.py:303,305,333` — Mixed `ts_event` / `ts_init` timestamp convention not documented; hold duration is in `ts_init`-space (+1s offset from wall-clock)

The aggregator receives `ts_event` (line 303: `self._agg.on_1s_bar(int(tse), ...)`), which is correct — the aggregator must use bar-open time to determine bucket membership. However, all entry timestamps (`entry_ts = ts` at line 333) and path timestamps use `ts = int(tsi)` (`ts_init` = `ts_event + 1_000_000_000 ns` for 1s bars from the NQ v.0 catalog).

Consequence: `dt = (ts - entry_ts) / NS_PER_S` in `_simulate_path` (line 434) measures hold duration in `ts_init`-space. Because both `entry_ts` and all path `ts` values are `ts_init`, the relative durations are correct and internally consistent. However, `entry_ts` stored in the parquet is `ts_init` of the fill bar, which is 1s after the bar's `ts_event` (the bar's open timestamp). A consumer reading `entry_ts` and comparing it to wall-clock times or to raw tick data needs to subtract 1 billion nanoseconds to obtain the actual market time of the entry. This is not documented in the output schema.

**Recommended fix (do not apply):** Add a comment on the `entry_ts` field in the entry record (lines 370-381) stating that the value is `ts_init` (bar close time) not `ts_event` (bar open time), and that the fill price is the open of the bar at `ts_event = entry_ts - 1_000_000_000`.

---

### [W3 / B2] `run_5s_scalp_study.py:268,519–520` — `flips_60s` and `flips_120s` count the triggering flip itself

At line 268, `self._5s_flips_timestamps.append(completed.close_ts / NS_PER_S)` runs before `_snapshot_features` is called at line 278. Inside `_snapshot_features`, lines 519–520 compute:

```python
flips_60  = sum(1 for t in self._5s_flips_timestamps if t >= now_s - 60.0)
flips_120 = sum(1 for t in self._5s_flips_timestamps if t >= now_s - 120.0)
```

Because the current flip's timestamp was just appended, these counts always include the triggering flip itself. A feature named "flips in the last 60 seconds" that self-includes the current flip inflates the count by 1 for every row. This is not look-ahead (the flip has happened), but it makes the feature label misleading: it actually means "flips including this one in the last 60s" rather than "prior flips in the last 60s." If a future model uses `flips_60s` as an input, the deployment-time computation must also self-include, or the train/serve convention will diverge.

**Recommended fix (do not apply):** Record the current flip timestamp after `_snapshot_features` returns (move line 268 to after line 278), so `flips_60s` / `flips_120s` count strictly prior flips. Alternatively, document the self-include convention explicitly in the feature dictionary.

---

### [W4 / C3] `analyze_5s_scalps.py:249–351` — Compounded in-sample selection: best bracket config chosen on full pooled data, then bucket rankings evaluated on the same data under that same config

Two nested selection steps both use the full 2021–2024 pooled dataset with no temporal holdout:

1. Line 249–250: `best_cfg` is selected as the single best bracket configuration ranked by primary net $/trade across all 160 configurations, all four years, all trades.
2. Lines 320–348: All bucket evaluations (approximately 90 bucket-cells across 30 features) are run on the same 2021–2024 data under `best_cfg`.

The "top 10 best buckets" table in the markdown report (`5s_scalp_results.md`) reflects the maximum of ~90 draws from the in-sample distribution of `best_cfg`. Even if `best_cfg` itself has zero true edge, the top-ranked bucket will appear to have a meaningful positive $/trade simply from noise across 90 cells evaluated on the same sample. No temporal holdout, no multiple-comparison correction, and no cross-year stability check are applied to the bucket rankings.

This does not corrupt the **global aggregate results** (which are straightforward in-sample descriptions of what happened). It **does** mean the "best bucket" claim requires out-of-sample or cross-year validation before any deployment claim. Per project MEMORY, this pattern has been fatal on prior studies (V_A pre-flip T-1 had +$11–22/tr IS that collapsed OOS; Level Momentum bucket-filter had +$10/tr IS and -$7.87/tr OOS).

**Recommended fix (do not apply):** Add a prominent disclaimer to the bucket table in the markdown report that these are in-sample tertile descriptions under the in-sample-best bracket config. Before claiming any bucket edge, re-evaluate on at least one held-out year (e.g., 2025 or 2020) using the same bracket config without re-selecting it.

---

### [W5 / F1 / F2] `run_5s_scalp_study.py:38–39` — RTH filter constants defined but never applied; all 24-hour data included

`RTH_START_MIN = 510` (08:30 CT) and `RTH_END_MIN = 900` (15:00 CT) are defined at lines 38–39 but not referenced anywhere else in the file. There is no session filter on entry triggers, path collection, or label simulation.

The study therefore includes overnight (ETH) entries with their structurally different characteristics: lower liquidity, wider effective spreads, different ATR regimes, and different 5s flip frequencies. If the intended use case is an RTH scalp strategy (which the SPEC implies by its benchmark against RTH AT-regime contexts), the presence of ETH data in the pooled results may mask or inflate edge that is RTH-specific, or credit edge from thin-market noise that would not survive a 0.5-tick slippage assumption in a real market.

**Recommended fix (do not apply):** Either apply an RTH filter to entry triggers using bar `ts_event` converted to Central Time (`CT = pytz.timezone("America/Chicago")`), comparing minutes-since-midnight against `RTH_START_MIN` and `RTH_END_MIN`, or explicitly document that the study is intentionally 24-hour and remove the unused constants to avoid misleading readers.

---

### [W6 / E4] `run_5s_scalp_study.py:444–460` — Regime-flip exits (`opposite_1m_regime`, `opposite_regime`) fill at bar CLOSE rather than next bar OPEN

In `_simulate_path`, when `reg_1m == -d or reg_1m == 0` (line 444) or `exit_flavor == "b5f" and reg_5s == -d` (line 453), the exit fills at `c` (close of the current 1s bar). However, the `reg_1m` and `reg_5s` values stored in the path tuple are sampled from `self._reg.get()` in `on_1s` at lines 340–343, which run AFTER `agg.on_1s_bar` at line 303. This means: when a 5s or 1m bucket closes on bar N (triggered by bar N's arrival), the registry is updated, and the path entry for bar N already reflects the new regime. The exit fills at `c` of bar N.

In a real-time system, a regime flip in a 5s or 1m bucket is detected only when the next bucket's first bar arrives — that bar is bar N+1. The earliest feasible exit is therefore bar N+1's open, not bar N's close. Exiting at `c` of bar N is approximately 0–1 seconds early and credits the fill at whatever price the bar closed at, rather than bar N+1's open price. The direction of the bias is ambiguous (bar N's close vs. bar N+1's open could go either way), but this is a systematic overprecision on roughly every regime-exit trade. The magnitude is at most one 1s bar's worth of price movement.

This is not a phantom fill (the exit price is within the bar's OHLC), and for a 1s-bar replay the error is small. For a study intended to describe what a live strategy would observe, the convention should be documented.

**Recommended fix (do not apply):** Record the path termination differently: when `reg_1m` or `reg_5s` indicates a flip on bar N, record the exit as occurring at bar N+1's open. In path-simulation, this would require looking ahead one bar — but since the path is replayed offline after collection, this can be done by examining `path[idx+1][1]` (the next bar's open) when the regime-exit condition fires.

---

## Notes

### [N1] `run_5s_scalp_study.py:169,306` — `_vol_1m_so_far` is accumulated but never read, never reset, never used

`self._vol_1m_so_far` is initialized at line 169 and incremented at line 306 but appears in no feature, no label, and no conditional logic. It is never reset on 1m regime change. If it were intended as a "volume so far in the current 1m bar" feature, it would be meaningless as written (monotonically increasing across the full replay). Dead code.

---

### [N2] `run_5s_scalp_study.py:251,264` — `prior_5s_duration` overestimates prior regime length by one 5s bucket

`self._5s_regime_start_ts` is set to `completed.open_ts` (the OPEN of the flip bar, line 264) rather than `completed.close_ts`. When the next flip fires, `prior_5s_duration` is computed as `(completed.close_ts - self._5s_regime_start_ts) / NS_PER_S` (line 251). This includes the flip bar's own 5-second window in the prior regime's duration. The true prior regime ended at the OPEN of the flip bar (`completed.open_ts`), so the start-of-new-regime tracking should anchor at `completed.close_ts`. The result is a systematic +5s inflation in the `prior_5s_duration` feature for every row. Not look-ahead, but a measurement inaccuracy.

---

### [N3] `run_5s_scalp_study.py:680–682` — Warmup comment is misleading; warmup is handled by post-processing year filter, not a special code path

The comment at line 681 states "Warmup registry with first 1000 bars (approx 16 mins) to avoid NaNs at start of the year." But the loop at lines 681–682 processes ALL bars identically, including the lead-in data before `year-01-01`. There is no warmup-gated code path. The actual mechanism is: `load_start = f"{year}-01-01" - 5 days` (line 655–656), so the first 5 days of data warm up ATR/EMA before any signal can trigger, and the year filter at line 695 (`df_ent.entry_ts >= yr0`) discards any entries that occurred during the lead-in period. This works correctly but the comment is misleading about the mechanism.

---

### [N4] `analyze_5s_scalps.py:106` — `entry_ts.argsort()` for drawdown assumes DataFrame index matches Series index after bucket-filtered `sub_df`

Inside `compute_metrics`, `sorted_idx = df["entry_ts"].argsort()` then `sorted_pnl = net_pnl.iloc[sorted_idx].values`. When `compute_metrics` is called on a subset `sub_df` (from `groupby` in the bucket analysis), `df["entry_ts"]` and `net_pnl` share the same index (the subsetted `sub_df`'s integer index). `argsort()` returns positional offsets within the series. `net_pnl.iloc[sorted_idx]` uses positional indexing into the series. This is correct if and only if `entry_ts` and `net_pnl` have identical index labels — which they do since both derive from the same `df` argument. However, if `df` is passed with a non-default index (e.g., after a `reset_index()` was not called), and the `entry_ts.argsort()` returns positional indices that do not correspond to `net_pnl`'s positional order, the drawdown will be computed in wrong chronological order. The current call sites pass merged DataFrames with `ignore_index=True` so this is safe today, but is fragile.

---

## Clean Checks

The following items were explicitly verified and found clean:

- **A (entry fill timing):** Confirmed. Scalp fills at bar N's open (`entry_px = o`, line 334). The pending→active handoff happens AFTER `agg.on_1s_bar` returns and accumulator updates run (steps 1→2→3 in `on_1s`). No same-bar decision/fill leakage.

- **B (feature snapshot causality — accumulator ordering):** Confirmed. `_snapshot_features` is called inside `on_bucket_closed`, which fires synchronously inside `agg.on_1s_bar` at line 303. The accumulators `_obv_signed_vol`, `_1m_mfe`, `_1m_mae`, `_1m_cum_abs_move`, `_aligned_5s_vol`, `_opposing_5s_vol` are updated at lines 306–317, which run AFTER `agg.on_1s_bar` returns. At snapshot time, all accumulators reflect state through bar N-1 (the previous 1s bar), not bar N. Strictly causal.

- **C (MTF read causality at 1m boundary):** Confirmed. The aggregator iterates timeframes in the order `("5s", "1m", "5m")` as specified at `ScalpReplay.__init__` line 147 (`TFS = ("5s", "1m", "5m")`, line 37). At a simultaneous 5s+1m boundary: the 5s close fires first; when `_snapshot_features` reads `self._reg.get("1m")` (line 509), the 1m bucket has not yet been processed. The registry returns the prior completed 1m bar — the previous minute's state. This is causal.

- **D (path simulation phantom fills):** No phantom fills found. PT exits at `pt_px` (checked only when `h >= pt_px` for longs, line 472), SL exits at `sl_px` (checked only when `l <= sl_px`, line 468). Max-hold exits at bar `o` (open). Regime exits at bar `c` (close, within OHLC). Conservative tie-break confirmed: when both SL and PT are hit in the same bar (line 464/480), SL takes priority — matches SPEC rule "stop-first if both hit in the same bar."

- **E (parent regime termination — no future info):** Confirmed. `reg1m` in the path tuple is read from `self._reg.get("1m")` inside `on_1s`, after `agg.on_1s_bar` returns. The registry updates the 1m state only when a 1m bucket closes. The state stored in each path entry is the regime as known at the moment that specific 1s bar's processing completes. This cannot leak future bar data.

- **F (catalog):** `CATALOG = "data/catalog/NQ_v0_2020_2026"` (line 28). This is the approved volume-continuous catalog per project MEMORY (`NQ.v.0` mandatory). Not a `c.0` source. Roll-day contract-mismatch risk does not apply here since this study uses 1s bars for both regime computation and path replay (same source), with no tick/bar source mixing.

- **G1 (no `closed='right'` resample bug):** The study does not perform any pandas resample. All aggregation is done by the `TimeframeAggregator`, which uses bucket_id = `ts_event // bucket_size_ns` (floor division). This is `closed='left'` semantics: each 1s bar belongs to the bucket whose start time is `<= ts_event < start + size`. No resample look-ahead.

- **G2 (no `shift(-N)` or `bfill` in features):** None found in either file.

- **G3 (no `center=True` rolling):** The `FeatureManager` uses custom incremental EMA and slope computation with deques. No pandas rolling or ewm calls anywhere in the study.

- **G4 (no train/test data contamination):** This is a research data collection + analysis pipeline, not an ML training pipeline. There is no sklearn `fit()`, `cross_val_score`, or similar call. The tertile bucketing uses `pd.qcut` on the full sample, which is correctly treated as in-sample description (WARNING W4 above).

- **G5 (RegimeStateEngine closed-bar semantics):** Verified. `RegimeStateEngine.on_bar_closed` only receives `_OpenBucket` from the aggregator's PREVIOUS bucket. All EMA, ATR, and regime state in the registry reflects closed bars only.

- **G6 (`5s_regime_start_px` anchoring):** Verified causal. The new 5s regime start price is set to `completed.close` (line 265) of the flip bar. For subsequent bars in the new regime, MFE/MAE are computed relative to this close price. No future bar data enters the start price.

---

*Audit complete. Findings reflect read-only static analysis of the files listed above. Dynamic bugs (race conditions, runtime memory aliasing, platform-specific float behavior) are out of scope.*

**Scope hash:** `b0a7dc198f81a88f`
