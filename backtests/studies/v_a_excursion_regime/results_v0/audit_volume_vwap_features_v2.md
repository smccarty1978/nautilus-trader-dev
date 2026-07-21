# Look-Ahead & Timestamp Audit — v2

**Date:** 2026-05-13
**File:** `studies/v_a_excursion_regime/compute_volume_vwap_features.py`
**Auditor:** lookahead-auditor v1
**Scope:** single file + live snapshot schema (`collectors/collector_v2/results/v_a_v0_2025/snapshots.parquet`)

## Summary

- Critical: 0
- Warning: 0
- Note: 1

## Critical findings

None.

## Warnings

None.

## Notes

### [A5] `compute_volume_vwap_features.py:329` — decision_ts semantics assertion covers only `path_checkpoint` kind

The assertion at lines 326–335 verifies `decision_ts - bar_ts_event == 1_000_000_000 ns` only for `path_checkpoint` rows (1s-bar events). For `regime_flip` and `bar1_check` rows the diff is ~61–65 s (1m bar ts_init - ts_event, including ts_init_delta). The assertion does not cover these kinds, leaving their decision_ts semantics unguarded by code. Data inspection confirms all three kinds have decision_ts = ts_init (close time) and the searchsorted cutoff is causal in all cases, so this is not a bug — it is a defensive-coding gap only.

**Recommended fix (do not apply):** Extend the assertion or add a separate block for regime_flip/bar1_check rows confirming `decision_ts - bar_ts_event` is in the range [60_000_000_000, 70_000_000_000] ns.

## Clean checks

- **Fix 1 (epoch assertion):** Implemented correctly. Lines 84–95 normalize to tz-aware UTC, strip tz via `tz_localize(None)` on a parallel column, cast to `datetime64[ns]` then `int64`, and assert `> 1_500_000_000_000_000_000`. Verified `tz_localize(None)` works on pandas 2.3.3 (the installed version).
- **Fix 2 (tz handling):** Lines 84–90 correctly branch on `dt.tz is None` to localize vs convert, then strip tz for int64 arithmetic. Works on both pandas <2.0 and >=2.0 (tested).
- **Fix 3 (decision_ts assertion):** Lines 326–335 assert `decision_ts - bar_ts_event == 1_000_000_000 ns` for all 91,646 path_checkpoint rows in 2025 data. Assertion is non-trivial and passes.
- **A-series (timestamp causality):** `searchsorted(ts_event_ns, T, side='left')` with `T = decision_ts = ts_init` correctly excludes the current 1s bar's open-time and all future bars. Causal for all three snapshot kinds.
- **B1 (no center=True):** No rolling/ewm calls anywhere in the file.
- **B4 (no negative shift):** No `.shift(-N)` in feature path.
- **B5 (no bfill):** No backward-fill operations.
- **B7 (normalization statistics):** VWAP/sigma computed from session-running cumulative sums up to T only. Rolling volume windows use strictly past bars.
- **F3 (timezone handling):** All session logic uses explicit `tz_convert("America/Chicago")`. No naive timestamps in session boundary computation.
- **G3 (resampler args):** No resampling in this file; reads raw 1s bars directly.
- **Internal audit function (lines 252–302):** Brute-force re-computation uses `bars_ts >= T_start` AND `bars_ts < T` — matching the cumsum window semantics exactly. VWAP audit also uses strict `< T`. Self-audit is causally consistent with the fast path.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*
