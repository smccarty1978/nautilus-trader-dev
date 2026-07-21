# Look-Ahead & Timestamp Audit

**Date:** 2026-05-13
**File:** `studies/v_a_excursion_regime/ml_va_walkforward_bar1plus30s.py`
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 1
- Warning: 1
- Note: 1

---

## Critical Findings

### [C1 / Label Censoring] `ml_va_walkforward_bar1plus30s.py:211` — censored trades receive label=0, creating survivor bias

`compute_label_unr_5m` skips the `continue` block on line 212 only when `cp_ts < exit_ts`. Trades that exit before `T_E + 300s` leave `label[k] = 0` (the initialized value) AND `unr_atr[k] = NaN`. The label 0 survives into the model because NaN rows are never dropped — `label[k]` defaults to `int(False)` = 0. These are the early-exiting trades that are most likely losers (SL hits). Labeling them as 0 (did not reach +0.75 ATR) is directionally correct, but the `unr_5m_atr` column is NaN for them while `target_unr075` is 0, creating an inconsistency. More critically, `pnl` (from `net_pnl`, a real-trade outcome) IS populated for these rows and is used in the evaluate() decile analysis, but the label was derived from a different measurement (unrealized at +5m, censored). This mismatch means the model is trained on a label that is always 0 for early-exit trades regardless of actual P&L, which is correct in spirit but could cause the label base-rate to be depressed relative to the true "good trade" rate, and the OOS PnL-vs-label correlation diagnostic may look better than it is.

**Recommended fix (do not apply):** Explicitly set `label[k] = 0` and document that censored trades are treated as non-passing; add an assertion that `unr_5m_atr.isna().sum()` equals the count of early exits, so the censoring is visible rather than silent.

---

## Warnings

### [B4 / Drop list] `ml_va_walkforward_bar1plus30s.py:315-342` — `atr_1m` survives the drop list and enters the feature matrix

The drop list (lines 315–342) removes `atr_at_signal` but does NOT remove `atr_1m`. The p30 features and bar-shape features are already ATR-normalized, so `atr_1m` in raw point terms encodes volatility level directly. This is causal (it is available at T_F), but if the model learns to use raw ATR magnitude as a feature it may be fitting volatility regime rather than trade quality. More importantly, the secondary forbidden-column assertion at line 450–455 also does not include `atr_1m`, so there is no runtime guard on this. This is a WARNING rather than CRITICAL because `atr_1m` is causally available — it is a feature, not a label — but its presence is likely unintentional given that every other raw price/ATR column is dropped.

**Recommended fix (do not apply):** Add `"atr_1m"` to the drop list on line 315 (or the forbidden set on line 450) if normalized features are the intent.

---

## Notes

### [Doc/Code Mismatch] `ml_va_walkforward_bar1plus30s.py:23` — `p30_close_vs_open_dir_atr` listed in module docstring but never computed

The module-level docstring (line 23) lists `p30_close_vs_open_dir_atr` as one of the new p30 features. It does not appear in the `cols` list (lines 107–116) or anywhere in `compute_p30_features`. `p30_body_dir_atr` (which computes `(c_last - o0) * d / a`) is the conceptually equivalent feature and IS produced. No bias impact — this is purely a documentation mismatch.

---

## Clean Checks

- **A1/A2** — 1s bars loaded by `ts_event`; bars used only for windowed lookups, not as an index. p30 window `[decision_ts, decision_ts + 30s)` correctly excludes `T_F` itself (side="left" on both bounds).
- **B1** — No `rolling`, `ewm`, or `center=True` in the feature path.
- **B4** — No `.shift(-N)` or negative-lag operations in features. `.shift` not present anywhere in file.
- **B5** — No `.ffill()` or `.bfill()` in feature path.
- **B6** — No cross-frequency join. All features from same-row snapshot + p30 window.
- **B7** — All normalizations use `atr_1m` (per-trade scalar), not dataset-wide statistics. No `StandardScaler` or global z-score.
- **C1** — Label look-ahead (`entry_ts + 300s`) is intentional and is in label columns only. Label columns confirmed absent from feature matrix via assertion at line 454–455.
- **C3** — Walk-forward splits are strictly temporal: train on earlier year(s), score on later year. No `cross_val_score` or random shuffle.
- **D1** — p30 features are computed from 1s `ts_event` timestamps using `searchsorted(side="left")` which finds first bar at-or-after `decision_ts`, matching how a live strategy would observe the window.
- **Concern 1 (causality of p30 window)** — CONFIRMED CLEAN. Window `[decision_ts, decision_ts + 30s)` uses `side="left"` for both bounds (lines 135–136). All bars have `ts_event < T_F`, so no look-ahead.
- **Concern 2 (bar1_check snapshot staleness)** — CONFIRMED CLEAN. Snapshot features are as-of `decision_ts` (bar1_close + 1s), 29s stale at T_F but causally valid. No future information.
- **Concern 3 (label causality)** — CONFIRMED CLEAN. Label observes 1s bar OPEN at `entry_ts + 300s` where `entry_ts ≈ T_F`. Forward-looking by design, in label column only.
- **Concern 4 (drop list completeness)** — MOSTLY CLEAN. All trade outcome columns (`net_pnl`, `gross_pnl`, `hold_s`, `exit_reason`, `running_mfe`, `running_mae`) dropped at line 335–339. Label columns (`target_unr075`, `unr_5m_atr`) dropped at line 336. `entry_ts`, `fill_price`, `exit_ts`, `exit_price` dropped. Secondary assertion at line 454–455 provides runtime guard. Exception: `atr_1m` survives (see Warning above).
- **Concern 5 (with-delay data source)** — CONFIRMED. Both `SNAP_PATHS` and `TRADE_PATHS` read from `v_a_v0_{year}/` (lines 51–57). The entry-decision diff print at lines 238–241 provides a runtime sanity check (~29s expected).
- **Concern 6 (entry-decision gap)** — CONFIRMED CONSISTENT. `entry_ts - decision_ts` printed at runtime. Code comment correctly states "expect ~29 for with-delay" (T_F = decision_ts + 30s, entry at bar1_close + 30s = decision_ts + 29s when decision_ts = bar1_close + 1s).

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*
