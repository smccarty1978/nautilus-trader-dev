<!-- DOC-STATUS-BANNER -->
> **[HISTORICAL]**
>
> A point-in-time record of an individual historical audit. It is not a description of the current system
> and not a source of instructions.
>
> Current authority: **`docs/RESEARCH_WORKFLOW.md`**. Classification: `docs/DOCUMENT_MAP.md`.

# Look-Ahead & Timestamp Audit

**Date:** 2026-06-11T19:39:32Z
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

- Critical: 1
- Warning: 2
- Note: 0

---

## Critical Findings

### [D1 / B6] `run_5s_scalp_study.py:36,143` — Stale 1m/5m context at boundary bars due to TF aggregation order (`TFS` loop order)

The aggregation timeframes tuple `TFS` is defined as `("5s", "1m", "5m")` at line 36. This order is passed to the `TimeframeAggregator` (line 145), which iterates over timeframes in that exact sequence when processing a new 1s bar (line 99 of `aggregator.py`). 

On simultaneous boundaries (e.g., at minute/5-minute marks like `ts_event = 60s`), the 5s aggregation completed bucket is closed and processed first. During `on_bucket_closed("5s")`, the 5s regime flip is detected, a scalp trigger is checked, and `_snapshot_features` is called. However, because `"1m"` (and `"5m"`) have not yet been iterated in the aggregator loop, the registry has not yet processed the completed 1m/5m bars for that boundary. 

Consequences:
1. **Trigger Lag:** The alignment check (`now == self._active_1m_regime`) compares the new 5s regime against the 1m regime from 1 minute ago (stale). If both flipped at the boundary to match, the signal is missed.
2. **Feature Lag:** `_snapshot_features` queries `self._reg.get("1m")` and `self._reg.get("5m")`, obtaining states that are 1 minute and 5 minutes stale, respectively (e.g., `atr_1m` and EMA-based geometry are computed using the previous bar).

This creates a systematic train/serve skew because a live strategy running on NautilusTrader would typically receive the updated 1m regime state prior to evaluating a new 5s bar signal.

**Recommended fix (do not apply):**
Change line 36 in `run_5s_scalp_study.py` to:
```python
TFS = ("5m", "1m", "5s")
```
This ensures that at simultaneous boundaries, the macro-regimes (5m, then 1m) complete and update the registry before the 5s callback runs.

---

## Warnings

### [D4 / C3] `analyze_5s_scalps.py:249-351` — Compounded in-sample selection: best bracket config chosen on full pooled data, then bucket rankings evaluated on the same data

Two nested selection steps both use the full 2021–2024 pooled dataset with no temporal holdout:
1. Lines 244–246: `best_cfg` is selected as the single best bracket configuration ranked by primary net $/trade across all configurations.
2. Lines 320–348: All bucket evaluations are run on the exact same 2021–2024 data under `best_cfg`.

The "top 10 best buckets" table reflects the maximum of ~90 draws from the in-sample distribution under `best_cfg`. Even if the strategy has zero true edge, the top-ranked bucket will appear to have a meaningful positive expectency due to noise across the 90 cells. No out-of-sample or cross-year validation is performed for the bucket rankings, posing a high risk of selection bias.

**Recommended fix (do not apply):**
Add a prominent disclaimer to the bucket table in the markdown report indicating that these are in-sample tertile descriptions. Before choosing a bucket filter for live strategy use, perform walk-forward validation (e.g., fit bucket bounds on 2021–2023 data and evaluate on a held-out 2024 test set).

---

### [F4] `analyze_5s_scalps.py:106` — `entry_ts.argsort()` for drawdown is fragile

Inside `compute_metrics`, `sorted_idx = df["entry_ts"].argsort()` is used to obtain positional indices, which are then passed to `net_pnl.iloc[sorted_idx]`. When `compute_metrics` is called on grouped subsets of the dataframe (e.g. from `groupby` in the bucket analysis), `iloc` uses positional offsets within the series. While this is correct today because `df` and `net_pnl` share matching positional bounds, it is fragile. If the indices diverge or if the dataframe index is not 0-based sequential, `iloc` with positional argsort offsets will return misaligned rows and corrupt the drawdown calculation.

**Recommended fix (do not apply):**
Sort the dataframe chronologically using `df.sort_values("entry_ts")` before extracting `net_pnl` and calculating the cumulative drawdown, rather than relying on positional argsort with `iloc`.

---

## Clean Checks

The following checks were explicitly verified and found clean:

- **A1/A2 (NautilusTrader timestamp conventions & catalog build):** Verified clean. The catalog build wrangler correctly shifts bars to close-time labeling (`ts_init_delta` set to +1s for 1s bars, +60s for 1m bars, and +300s for 5m bars). Replay uses close-time `ts_init` for durations and entry records.
- **A3 (Causal pricing inside strategies):** Verified clean. Exits and entries use exact 1s bar OHLC values chronologically.
- **B1 (No center=True rolling):** Verified clean. The `FeatureManager` uses custom deques and incremental EMA update objects, avoiding any center-aligned pandas indicators.
- **B4/B5 (No negative lag or forward/backward fill leaks):** Verified clean. No `.shift(-N)` or `.ffill()` / `.bfill()` used in the feature paths.
- **C1/C2 (Label look-ahead separation):** Verified clean. Labels are calculated on future paths after entry and kept separate from features.
- **E4 (No same-bar fill leaks):** Verified clean. Signals are triggered on 5s close, and entries are filled at the open of the next 1s bar.
- **E5 (Indicator warmup):** Verified clean. The 5-day lead-in contains over 400,000 bars, which is way more than enough to stabilize the 14-period Wilder ATR and EMAs before year start.
- **F1/F2 (Session boundaries & time handling):** Verified clean. The RTH filter is correctly applied to triggers, and DST/timezone handling is explicit.
- **G1 (Continuous contract rolls):** Verified clean. Catalog `NQ_v0_2020_2026` is volume-continuous (`NQ.v.0`), eliminating quarterly contract-roll gaps.
- **G2 (No empty bar forward fills):** Verified clean. Custom `TimeframeAggregator` drops empty minutes and handles gaps causally.

---

*Audit complete. Findings reflect read-only static analysis of the files listed above. Dynamic bugs (race conditions, runtime memory aliasing, platform-specific float behavior) are out of scope.*

**Scope hash:** `b0a7dc198f81a88f`
