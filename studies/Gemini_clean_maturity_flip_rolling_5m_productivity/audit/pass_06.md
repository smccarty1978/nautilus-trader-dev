# Causal & Look-Ahead Audit Report (Pass 06)

**Study:** `Gemini_clean_maturity_flip_rolling_5m_productivity`  
**Date:** `2026-08-15T01:45:00Z`  
**Verdict:** `CLEAR` (0 Critical, 0 Warning, 0 Note)  
**Audited Scope:** Optimized Targeted 60-Feature Collector (`FastOHLCVRingBuffer`, `FlipPredictionCollector`), Stage Resolution (`run_plan.py`), Data Plan and OOS Lock Enforcement (`data_plan.py`), and Output Manifest/Feature Hash Invariance (`output_manager.py`).

---

## 1. Prior Findings Adjudication

| Finding ID | Previous Status | Current Status | Adjudication / Evidence |
|---|---|---|---|
| **CAUSAL-01** | FIXED (Pass 02) | **FIXED** | Causal availability contract confirmed: $\text{latest\_source\_ts\_init} \le T$. Checkpoint evaluation loop strictly guards `if T > ts_avail: break`. |
| **CAUSAL-02** | FIXED (Pass 02) | **FIXED** | Completed 5m bar dispatch on 1m boundary aligned at interval close (`minute_of_day % 5 == 0`) with `ts_avail = bar.ts_init`. |
| **CAUSAL-03** | FIXED (Pass 02) | **FIXED** | Rolling 5m productivity anchors strictly at completed 1s bar $T - 300\text{s}$ without nearest-neighbor search or future interpolation. |
| **CAUSAL-04** | FIXED (Pass 04) | **FIXED** | `FastOHLCVRingBuffer` causal indexing: slices strictly on completed bars with $\text{ts} \le T$ (`ts_slice > obs_ts - window_ns`). Zero post-$T$ indexing. |
| **CAUSAL-05** | FIXED (Pass 05) | **FIXED** | `run_plan.py` bounded FULL stage: resolves strictly to `train_years` (`[2021-01-01, 2023-12-31]`) without leaking DEV (`2024`) partition. |

---

## 2. Comprehensive Causal Contract Verification (A, B, C1–C3, F, G, H)

### A. NautilusTrader Timestamp Conventions
- **A1–A2 (Timestamp Semantics):** Raw Databento data is `OPEN_STAMPED`. NautilusTrader runtime shifts `ts_init = ts_event + 1s` (1s bars) and `ts_init = ts_event + 60s` (1m bars) via `PRODUCT_CATALOGS` configuration. All internal indicators and trackers index strictly on `ts_init` (close time).
- **A3–A4 (Inside Strategy Price Lookup & Timers):** Pricing at checkpoint $T$ uses direct bar argument `c = float(bar.close)` for the completing bar where `ts_avail == T`. No timer-based future assumptions are made.
- **A5 (Datetime & Resampling):** Explicit timezones (`America/Chicago`) and close-time semantics preserved across all aggregations.

### B. Feature Engineering & Ring Buffer Causality
- **B1–B4 (No Centering, Future Leakage, or Negative Shifts):** `FastOHLCVRingBuffer` slices backwards from `obs_ts` with `ts_slice > obs_ts - window_ns`. Window conditions enforce minimum buffer history (`ts_slice[0] <= c_window + NS`), ensuring no unwarmed lookbacks. Zero negative-lag operations (`shift(-k)`) exist.
- **B5–B7 (No Look-Ahead Fills & Past-Window Normalization):** Missing anchor bars result in explicit `MISSING_EXACT_300S_BOUNDARY` / `None` returns without `bfill` or forward interpolation. Normalizing ATR is frozen at regime start $T_0 \le T$.
- **B9–B10 (Tracker Reuse & Frame Assumptions):** `Rolling5mProductivityTracker` and `StructuralRegimeGeometryTracker` enforce explicit window units and causal provenance timestamps (`five_provenance_close_ts <= checkpoint_ns`).

### C. Label Construction & Dataset Separation (C1–C3)
- **C1–C2 (Outcome Isolation & Label Alignment):** Target flip label `target_flip_within_horizon` is observed and resolved exclusively upon opposing regime flip events in `_on_regime_flip` at $T_{\text{flip}} > T$. Features logged at candidate declaration remain completely isolated from future outcome evaluation.
- **C3 (Temporal Chronology Enforcement):** `data_plan.py` and `run_plan.py` enforce strict partition boundaries: TRAIN `[2021, 2022, 2023]`, DEV `[2024]`, PROHIBITED `[2025, 2026]`. DEV partition access is hard-gated by `OOS_LOCKED_UNTIL_FREEZE` token verification.

### F. Session and Session Boundary Handling
- **F1–F4 (RTH Boundaries & Explicit Timezones):** RTH classification (08:30–15:00 CT) is evaluated on bar close times in `America/Chicago` named timezone. RTH cumulative volume/delta trackers reset cleanly at RTH open and close.

### G. Data Integrity & Manifest Verification
- **G1–G4 (Catalog Integrity & Strict Feature Hash Matching):** Uses volume-continuous contract `NQ_v0_2020_2026`. `output_manager.py` verifies emitted candidate features match the frozen `StudySpec` 60-feature contract and feature list SHA-256 hash. Warmup candidates prior to `start_dt` are filtered.

### H. Offline Simulation Price Resolution
- **H1–H4:** N/A (Feature collection and evaluation study without standalone offline fill simulation).

---

## 3. Scope Verification Summary

1. **`strategies/flip_prediction_collector.py`:** `FastOHLCVRingBuffer` and targeted 60-feature path operate strictly with $\text{ts\_avail} \le T$.
2. **`backtests/nt_runtime/run_plan.py`:** `RunStage.FULL` resolves strictly to `train_years` (`[2021-01-01, 2023-12-31]`).
3. **`backtests/nt_runtime/data_plan.py`:** Chronology guards prevent execution in prohibited years (`2025`, `2026`) and enforce `OOS_LOCKED_UNTIL_FREEZE` on DEV (`2024`).
4. **`backtests/nt_runtime/output_manager.py`:** Manifest generation enforces strict feature parity and SHA-256 integrity.

---

## 4. Pass 06 Summary & Verdict

- **Critical Findings:** `0`
- **Warning Findings:** `0`
- **Note Findings:** `0`
- **Preflight Check:** `CLEAR`
- **Final Verdict:** **CLEAR**
