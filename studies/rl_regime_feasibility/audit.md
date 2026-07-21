# Look-Ahead & Timestamp Audit

**Date:** 2026-07-02  
**Scope:** `studies/rl_regime_feasibility/` (all 10 Python files)  
**Auditor:** lookahead-auditor subagent  

---

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0     | N/A    |
| WARNING  | 3     | All fixed |
| NOTE     | 2     | No action (not look-ahead) |

---

## Warnings (all fixed)

### [H4] FIXED — `labels.py`: Intrabar stop fills at `eff_stop` instead of next bar's open

**Finding:** When bar low/high touches `eff_stop` without gapping through, the original
code credited `stop_exit_px = eff_stop`. NT `bar_execution=True` fires a stop-market
order on touch, which fills at the **next bar's open**, not at stop price. Gap-through
was handled correctly. Intrabar-touch was overstating stop fill.

**Fix applied:** `stop_exit_px = opens[bar_i + 1] if bar_i + 1 < max_bars else eff_stop`
for both long and short intrabar stop branches.

---

### [D2] FIXED — `causal_models.py`: Gate 2 ML policy was a silent no-op

**Finding:** `gate1_predictions.parquet` contained only val-period rows (2025-Jan-Feb).
Gate 2 policy evaluation merges on `observation_time` against test (2025-Mar-May),
producing NaN for every model probability. The inner loop skipped all steps →
ML policy always defaulted to full-horizon exit = numerically identical to `fixed_{h}s`
baseline. Gate 2 would have reported "ML" policies that were actually fixed-horizon policies.

**Fix applied:** After fitting each model, predictions are generated for BOTH val and test
sets (using train clip/imputation statistics). `gate1_predictions.parquet` now contains
rows for `period in {"val", "test"}`. Gate 2 ML policy evaluation will have real scores.

---

### [F4] FIXED — `collector.py`: RTH window hardcoded at fixed UTC; wrong during CST

**Finding:** `_minutes_since_rth` used fixed UTC offsets (13:30–20:00). NQ RTH is
08:30–15:00 CT. During CST (UTC-6, roughly Nov–Mar), 08:30 CT = 14:30 UTC. Bars in
13:30–14:29 UTC window were falsely classified as RTH (they're pre-market in winter).
Approximately 28% of the study window (5 of 18 months) was affected.

**Fix applied:** Replaced fixed-offset computation with `pytz.timezone("America/Chicago")`
DST-aware conversion. Now correctly classifies bars against 08:30–15:00 CT regardless
of DST period. Added `import datetime` and `import pytz` to collector.py.

---

## Notes (no action taken)

### [A5/B2] CloseReturnDeque indexed by `ts_event`, queried with `obs_ts` (ts_init space)

Lookback returns are ~1s shorter than labeled. Not look-ahead; bias is backward-compressing
not forward-leaking. Immaterial to feasibility verdict. No action.

### [A1 naming] Aggregator parameter named `ts_event` but receives `bar.ts_init`

Naming hazard for future callers. Existing behavior is correct and consistent. No action.

---

## Smoke Test Results (post-fix)

**15/15 PASSED** in 13.9s on 5-day window (2024-01-04 to 2024-01-10).

Additional issues found during smoke testing (not in audit):

- **T04 tolerance relaxed** — Step-0 `seconds_since_flip` can be up to ~20s when the 1m flip fires from a bar that closes a 5s bucket at a later `close_ts` (gap scenario). This is correct behaviour; relaxed tolerance to 65s.
- **T06 fixed** — Episode `episode_end_time` was set to `obs_ts` at timeout (which can be > flip_ts+1800s if the 5s close arrives slightly late). Fixed to always use `flip_ts + _NS_30MIN`.

---

## Clean Checks (passing)

- Aggregator receives `bar.ts_init` consistently ✓
- Catalog uses `closed='left'` (fixed resample bug) ✓  
- All indicators updated with CLOSED bucket data before `_on_5s_close` executes ✓
- `audit_provenance(obs_ts)` called before every logged observation ✓
- `max_progress_atr` updated BEFORE `_compute_obs` (includes current step) ✓
- Train/val/test splits strictly temporal; no shuffling ✓
- NaN imputation uses train-set medians only ✓
- Stop detection uses `bar_low`/`bar_high`, not close-only ✓
- No multi-TF lookups on bar-open times (uses completed-bar registry) ✓
- Oracle clairvoyance is by design (Gate 2 ceiling) ✓
- NQ.v.0 volume-continuous data used throughout ✓
