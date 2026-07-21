# Look-Ahead & Timestamp Audit v4

**Date:** 2026-06-11
**Scope:**
- `studies/regime_state_transition_atlas/build_state_rows.py`
- `studies/regime_state_transition_atlas/build_forward_labels.py`
- `studies/regime_state_transition_atlas/query_similar_states.py`
- `studies/regime_state_transition_atlas/analyze_state_memory.py`
- `studies/regime_state_transition_atlas/prototype_policy.py`

**Auditor:** lookahead-auditor v1

## Summary

- **Critical:** 0
- **Warning:** 1
- **Note:** 1

---

## Critical Findings

*None. All critical findings identified in v3 have been successfully resolved.*

---

## Warnings

### 1. [E4] build_forward_labels.py:185 — 1-Second Look-Ahead Fill on Gapped Minutes

**Description:**
The executable fill price fallback:
```python
185:             next_1s_open = next_1m_ticks_all[1][1] if len(next_1m_ticks_all) > 1 else next_1m_ticks_all[0][1]
```
will fall back to the first tick's open price (`next_1m_ticks_all[0][1]`) if there is only one tick in the next minute (a data gap during illiquid overnight periods). Since the first tick's open price covers the interval `[checkpoint_ts, checkpoint_ts + 1s)` and is registered at receipt time, if there is a gap and the next tick occurs later in the minute, this fallback executes the fill using the open price of a bar that occurs later, introducing a minor look-ahead during illiquid overnight periods.

**Recommended fix (do not apply):**
Gate the entry such that we do not fill if `len(next_1m_ticks_all) <= 1`, or use a default fill price from the next available tick in the catalog.

---

## Notes

### 1. [B2] build_state_rows.py:355-357 — Unused `pullback_depth_current_bar` Calculation

**Description:**
The variable `pullback_depth_current_bar` is calculated at lines 355-357 but is never exported to the feature dictionary `f`.

**Recommended fix (do not apply):**
Either remove the dead calculation or export it as `bar_max_pullback_depth_atr` to capture intra-bar excursions.

---

## Clean Checks (Resolution Status of v3 Findings)

- **C1/C2 (Baseline Fix):** Clean. `build_forward_labels.py` correctly uses `checkpoint_high_actual` / `checkpoint_low_actual` instead of the stale prior variables.
- **C3/C4 (OOS Leakage):** Clean. `check_lift_stability` is strictly limited to IS years (`[2021, 2022, 2023, 2024]`), and cell selection inside `analyze_state_memory.py` is gated on `lift_is >= 0.05` and sorted by `is_lift`.
- **E4 (Back-Dating Exits):** Clean. Regime exits in `prototype_policy.py` execute causally at the `next_1s_open` of the first bar of the new regime, resolving back-dating.
- **E4 (Benchmark Entry):** Clean. The benchmark entry price now uses the causal entry mapping (`c_info["entry_px"]`), resolving the 1-minute entry look-ahead.
- **B7 (Standardization Leakage):** Clean. Skipping 2021 scoring in `analyze_state_memory.py` successfully prevents leaking 2021 stats.
- **D1 (2026 Walk-Forward Training Set):** Clean. Training years are dynamically built up to the query year, correctly incorporating 2025 into the 2026 backtest training set.
- **B3/D1 (Volume Percentiles):** Clean. Deque maxlen is set to 20, and the volume is appended after snapshot features are evaluated, preventing self-contamination.
- **[B2 / C1 / D1] First 1s Tick Triggering Bar Leakage (v3 Critical 1):** Resolved. `build_forward_labels.py` now defines a `trigger_cutoff = checkpoint_ts + 1 * NS_PER_S` and filters out all ticks <= `trigger_cutoff` from the path for all label, race, and excursion evaluations.
- **[D1] Train/Serve Skew (v3 Critical 2):** Resolved. All forward labels, races, returns, and excursions in `build_forward_labels.py` are now calculated relative to `base_px` (which is `next_1s_open`), matching the serve-time causal execution price.
- **[C4 / D1] Non-Causal Threshold Fallback (v3 Critical 3):** Resolved. `prototype_policy.py` now sweeps over backtest years `[2023, 2024, 2025, 2026]`. Since 2022 scoring is not skipped in `analyze_state_memory.py`, there is always a non-empty training set for the walk-forward threshold calculation, avoiding the fallback leak entirely.
- **[F1] RTH Session Classification Shift (v3 Warning 1):** Resolved. `build_state_rows.py` now uses the open timestamp of the bar (`completed_1m.open_ts`) to determine RTH session boundaries, aligning the minute binning logic exactly.
- **[A1] TimeframeAggregator Timestamp (v3 Warning 3):** Resolved. `build_state_rows.py` and `build_forward_labels.py` now pass `tsi` (the init close-labeled timestamp) instead of `tse` to `on_1s_bar`, ensuring correct close-time aggregation.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*

**Sign-off:** 2026-06-11T21:45:00-05:00 | Scope Hash: `c59d83dfa3e9c70b8f154ea2ff488e0b2401831826b15ef98fdf0b07b3debe9a`
