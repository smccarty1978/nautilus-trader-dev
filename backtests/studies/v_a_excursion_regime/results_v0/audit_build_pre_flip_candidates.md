# Look-Ahead & Timestamp Audit

**Date:** 2026-05-14T00:00:00Z
**Scope:** `studies/v_a_excursion_regime/build_pre_flip_candidates.py`
**Auditor:** lookahead-auditor v1
**Scope hash (git):** n/a (no git repo)

---

## Summary

- Critical: 0
- Warning: 1
- Note: 2

---

## Warnings

### [B7 / E5] `build_pre_flip_candidates.py:400-403` — EMA/ATR cold-start at year boundary; no warmup gate on output candidates

Each year's `tf_5s`, `tf_15s`, `tf_30s`, `tf_1m` series is computed independently from bar 0
of that year's raw 1s data. `compute_atr_wilder` produces `NaN` for the first `ATR_PERIOD - 1
= 13` bars at each timeframe, and the Wilder EMA has a cold start that requires ~3x the span
to settle (EMA_LONG=9 needs roughly 27 bars). Candidates generated from these early bars carry
either NaN ATR (making all ATR-normalized features NaN) or a poorly-calibrated EMA, which
means spurious EMA-distance and threshold-proximity values will enter the feature table for
the first several minutes of each year.

There is no guard that excludes candidates with `atr_1m == NaN` or `bars_in_regime_1m < N`.
NaN ATR causes `prox_ok` to be False (NaN comparisons are False), so those candidates can
still enter via `faster_aligned`. Their threshold-proximity and ATR-normalized features will
all be NaN, which ML frameworks handle differently (some impute, some drop, some pass through).
If the model imputes NaN features, cold-start candidates inject anomalous rows with no
structural information into the training set.

**Recommended fix (do not apply):** after building the feature DataFrame and before candidate
generation, filter to bars where `atr_1m` is finite and `bars_in_regime_1m >= 3` (or at
minimum `atr_1m > 0`). A tighter guard of `bars >= ATR_PERIOD * 3 = 42` at the 1m level
would ensure full ATR convergence at the cost of ~42 minutes of data per year.

---

## Notes

### [A5] `build_pre_flip_candidates.py:477-481` — RTH boundary uses 1m CLOSE time; first bar of session included or excluded correctly, but verify intent

The RTH filter converts `close_ts_ns` (= `ts_init_ns` = ts_event + 60s) to Central Time and
computes `hour * 60 + minute`. For the 8:30 CT session open, the first 1m bar has ts_event =
13:30:00 UTC and ts_init = 13:31:00 UTC. Converting ts_init to CT gives 8:31 CT, so that
bar's close-time minute = 511, which satisfies `>= 510 (8:30)`. The bar IS included. This is
correct behavior (the bar closes at 8:31, after the session opened at 8:30). No bug — this is
a documentation note to confirm intent: if the project convention is "first bar whose OPEN is
at 8:30 CT", the filter is effectively `minutes >= 511` at close time and the 8:30 bar is
included. Behavior matches the RTH definition used in the collector.

### [C3] `build_pre_flip_candidates.py:391,578` — no explicit train/val/test split; three years concatenated without temporal guard

The output `pre_flip_candidates.parquet` contains all three years concatenated. There is no
warning or column marking the temporal boundary for downstream training. If a consumer calls
`train_test_split` without a `TimeSeriesSplit` splitter or explicit year-based cut, random
splitting will produce cross-temporal contamination. This script is Phase 1 and may be
intentionally leaving splitting to Phase 2, but the absence of a `split` or `fold` column
creates a trap.

**Recommended fix (do not apply):** add a `fold` column (e.g., 2024=train, 2025=val,
2026=test) to the output parquet so downstream consumers cannot accidentally random-split.

---

## Clean checks

- **A1** — all query times use `ts_init_ns` (bar close time), never `ts_event_ns`, for feature
  snapshotting and RTH filtering.
- **A2** — `aggregate_to_tf` correctly sets `ts_init_ns = ts_event_ns + period_ns` for all
  TFs. At period=60s this matches the NT 1m `ts_init_delta` convention exactly.
- **A5** — `load_1s` normalizes timestamps to UTC-aware before stripping tz for int64
  conversion; no naive-timestamp ambiguity.
- **B1** — no `rolling(..., center=True)` or `ewm(..., center=True)` anywhere.
- **B2** — `compute_tf_state` uses forward-only `ewm(adjust=False)` and
  `compute_atr_wilder`; no index look-ahead.
- **B3** — sub-TF indicator values are looked up via `latest_state_at` which uses
  `searchsorted(ts_init, query, side='right') - 1`. A TF bar whose `ts_init == query_ts` IS
  included — correct, because both the 1m bar and any co-closing TF bar are simultaneously
  finished at that moment.
- **B4** — no `.shift(-N)` or negative-lag operations in the feature path. `.shift(-N)` is
  used nowhere in this file.
- **B5** — no `.ffill()` or `.bfill()` in the feature path.
- **B6** — multi-TF joins are performed via `searchsorted` on `ts_init_ns` arrays, not
  by index alignment or merge; direction is strictly backward (no future TF bar can satisfy
  `ts_init <= query_ts`).
- **C1/C2** — labels use `cand_close_ts + X * 60_000_000_000` (forward-looking). Timestamp
  arithmetic verified: for label_T1, `target_ts = candidate_ts_init + 60s = flip_bar_ts_init`
  of the bar exactly 1 bar after the candidate. Correct.
- **C1** — label construction uses `flip_set` lookup only in label columns; no label-derived
  value feeds back into feature columns.
- **D1** — `load_va_confirmed_flips` computes `flip_bar_close_ts = decision_ts -
  61_000_000_000`. Verified against collector `strategy.py`: `decision_ts` at `bar1_check`
  time is the 1s bar whose `ts_init = bar1_ts_event + 61s`, so subtracting 61s recovers
  `bar1_ts_event = flip_bar_ts_init`. Arithmetic is exact.
- **F1** — RTH classification uses bar CLOSE time (ts_init), consistent with A1.
- **F3** — all timestamps are explicitly UTC throughout; tz is verified on load and applied
  before any arithmetic.
- **micro_window_features (concern 4)** — `i_e = searchsorted(bars_ts, t_end, side='left')`
  where `t_end = close_ts_ns = 1m ts_init`. The 1s bar at `ts_event == t_end` (first bar of
  next minute) has `side='left'` placing the index AT that bar, so `bars[i_s:i_e]` excludes
  it. Strictly causal.
- **compute_current_regime_maturity (concern 3)** — pure forward scan with state reset at
  regime boundaries. No future bar data is accessed at row `i`; all accumulators
  (`run_max_h`, `run_min_l`, `cum_abs_range`) reflect `[regime_start, i]` inclusive.
- **Candidate filter (concern 7)** — `regime_ok = regime_1m != d` uses the 1m regime
  computed from the just-closed 1m bar's EMA state. Causal: the regime is derived from
  `close[i]` against `ema3_h[i]`/`ema9_h[i]` which are computed from data up to and
  including bar `i`. No future leakage.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race
conditions in live trading) are out of scope.*
