# Causal & Look-Ahead Audit Report (Pass 07)

**Study:** `Gemini_clean_maturity_flip_rolling_5m_productivity`  
**Date:** `2026-08-15T02:37:30Z`  
**Verdict:** `CLEAR` (0 Critical, 0 Warning, 0 Note)  
**Audited Scope:**
- `strategies/flip_prediction_collector.py`: Exact 1s checkpoint timestamp equality (`triggering_1s_ts_init == observation_ts == T`), skipping gap seconds (`T < ts_avail`), `obs_ts = T`, and `FastOHLCVRingBuffer` backward causal slicing.
- `backtests/nt_runtime/run_plan.py`: `RunStage.FULL` bounded resolution strictly to `train_years` (`[2021, 2022, 2023]`).
- `backtests/nt_runtime/data_plan.py`: Chronology partition enforcement, explicit warmup window modeling, and fail-closed OOS lock (`OOS_LOCKED_UNTIL_FREEZE`).
- `backtests/nt_runtime/output_manager.py`: Strict 60-feature hash matching and SHA-256 artifact manifest generation.
- `utils/causal_registration.py`: Multi-timeframe causal bar ordering and coincident registration.

---

## 1. Prior Findings Adjudication Table

| Finding ID | Previous Status | Current Status | Adjudication / Evidence |
|---|---|---|---|
| **F3 / CAUSAL-01** | FIXED (Pass 02) | **FIXED** | Exact checkpoint timestamp equality invariant enforced: `triggering_1s_ts_init == observation_ts == T`. In `FlipPredictionCollector._handle_1s_bar`, missing 1s bars at grid seconds ($T < \text{ts\_avail}$) increment `next_checkpoint_index` and skip cleanly without back-stamping future bars. Evaluated checkpoints satisfy `ts_avail == T` exactly, verified by assertion in `_evaluate_checkpoint`. |
| **CAUSAL-02** | FIXED (Pass 02) | **FIXED** | Completed 5m bar dispatch occurs strictly on 1m boundary aligned at interval close (`minute_of_day % 5 == 0`) with `ts_avail = bar.ts_init`. Forming 5m bars are never exposed to feature snapshot logic. |
| **CAUSAL-03** | FIXED (Pass 02) | **FIXED** | Rolling 5m productivity anchors strictly at completed 1s bar $T - 300\text{s}$ via `Rolling5mProductivityTracker`. If any second in the 300s lookback is missing or unaligned, emits explicit unavailable reason without nearest-neighbor searching or forward interpolation. |
| **CAUSAL-04** | FIXED (Pass 04) | **FIXED** | `FastOHLCVRingBuffer` causal indexing: slices strictly on completed bars with $\text{ts} \le T$ (`ts_slice > obs_ts - window_ns`). Minimum buffer history guard (`ts_slice[0] <= c_window + NS`) prevents unwarmed calculations. Zero post-$T$ indexing. |
| **CAUSAL-05** | FIXED (Pass 05) | **FIXED** | `RunStage.FULL` in `run_plan.py` maps strictly to `train_years` (`[2021-01-01, 2023-12-31]`). DEV (`2024`) partition is not reached during FULL train replay and remains cryptographically locked until model freeze. |
| **F1 / F4** | FIXED (Pass 06) | **FIXED** | Full execution manifest coverage: `output_manager.py` enforces initial manifest creation, strict 60-feature hash matching, parquet serialization (`candidates.parquet`, `observations.parquet`), and complete runtime telemetry logging. |

---

## 2. Comprehensive Causal Checklist Verification (A, B, C1–C3, F, G, H)

### A. NautilusTrader Timestamp Conventions
- **A1–A2 (Timestamp Semantics):** Raw Databento data is `OPEN_STAMPED`. NautilusTrader runtime shifts `ts_init = ts_event + 1s` (1s bars) and `ts_init = ts_event + 60s` (1m bars) via `PRODUCT_CATALOGS` configuration in `data_plan.py`. All internal indicators, ring buffers, and trackers index strictly on `ts_init` (close time).
- **A3–A4 (Inside Strategy Price Lookup & Timers):** Pricing at checkpoint $T$ uses the direct bar argument `c = float(bar.close)` for the completing 1s bar where `ts_avail == T`. No timer callbacks or future-indexed lookups are used.
- **A5 (Datetime & Resampling):** Explicit timezones (`America/Chicago`) and close-time semantics are preserved across all aggregations. Multi-timeframe registration in `causal_registration.py` guarantees 1s sub-bars execute prior to coincident parent 1m bars.

### B. Feature Engineering Look-Ahead
- **B1–B4 (No Centering, Future Leakage, or Negative Shifts):** `FastOHLCVRingBuffer` slices backwards from `obs_ts = T` with `ts_slice > obs_ts - window_ns`. Window conditions enforce minimum buffer history (`ts_slice[0] <= c_window + NS`), ensuring no unwarmed lookbacks. Zero negative-lag operations (`shift(-k)`) or centering exist.
- **B5–B7 (No Look-Ahead Fills & Past-Window Normalization):** Missing anchor bars result in explicit `MISSING_EXACT_300S_BOUNDARY` / `None` returns without `bfill` or forward interpolation. Normalizing ATR is captured at regime start $T_0 \le T$ and held immutable across regime lifetime.
- **B9–B10 (Tracker Provenance & Explicit Cadences):** `Rolling5mProductivityTracker` and `StructuralRegimeGeometryTracker` enforce explicit window units and causal provenance timestamps (`five_provenance_close_ts <= checkpoint_ns`).

### C. Label Construction & Dataset Separation (C1–C3)
- **C1–C2 (Outcome Isolation & Label Alignment):** Target flip label `target_flip_within_horizon` is observed and resolved exclusively upon opposing regime flip events in `_on_regime_flip` at $T_{\text{flip}} > T$. Features logged at candidate declaration remain completely isolated from future outcome evaluation.
- **C3 (Temporal Chronology Enforcement):** `data_plan.py` and `run_plan.py` enforce strict partition boundaries: TRAIN `[2021, 2022, 2023]`, DEV `[2024]`, PROHIBITED `[2025, 2026]`. DEV partition access is hard-gated by `OOS_LOCKED_UNTIL_FREEZE` token verification.

### F. Session and Session Boundary Handling
- **F1–F4 (RTH Boundaries & Explicit Timezones):** RTH classification (08:30–15:00 CT) is evaluated on bar close times in the named timezone `America/Chicago`. RTH cumulative volume/delta trackers reset cleanly at RTH open and close.

### G. Data Integrity & Manifest Verification
- **G1–G4 (Catalog Integrity & Strict Feature Hash Matching):** Uses volume-continuous contract `NQ_v0_2020_2026`. `output_manager.py` verifies emitted candidate features match the frozen `StudySpec` 60-feature contract and feature list SHA-256 hash (`2a744cfa3acfa437ae0ff8219c56451e176a170ae83450c52b8ca42842b0cba5`). Warmup candidates prior to `start_dt` are filtered.

### H. Offline Bracket Simulation Price Resolution
- **H1–H4:** N/A (Feature collection and evaluation study without standalone offline bracket fill simulation).

---

## 3. Referred to Contract-Checker
- Checklist items **C4, D, E** and Deliverables Manifest tracking are verified by `contract-checker`.

---

## 4. Pass 07 Summary & Verdict

- **Critical Findings:** `0`
- **Warning Findings:** `0`
- **Note Findings:** `0`
- **Preflight Check:** `CLEAR`
- **Final Verdict:** **CLEAR**
