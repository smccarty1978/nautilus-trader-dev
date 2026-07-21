# Look-Ahead & Timestamp Audit Report

## Audit Scope
- List of files audited:
  1. `features/collector.py`
  2. `features/engine.py`
  3. `features/trackers/velocity.py`
  4. `features/trackers/volume.py`
  5. `features/trackers/pullback.py`

## Findings Summary
- **CRITICAL**: 0
- **WARNING**: 0
- **NOTE**: 1

All audited files remain clean of look-ahead biases, future timestamp leaks, or indexing errors. The standalone smoke test suite validated 15/15 correctness invariants successfully.

---

## File-by-File Details

### 1. `features/collector.py`
- **Status**: Clean
- **Assessment**: Follows the composed `FeatureEngine` design. Decouples state tracking from decision-time snapshots. On 1s/1m bar updates, it updates the underlying `FeatureEngine` and retrieves canonical features on a trigger. There are no stateful computations within `FeatureCollector` itself, eliminating any risk of double-updating or sequence violation.

### 2. `features/engine.py`
- **Status**: Clean
- **Assessment**: Coordinates low-level trackers and manages timeframe-specific updates. Implements `update_1s`, `update_1m`, and `snapshot` with strict ordering.
  - Compliance with **A1** (Close-time semantics): Uses `touch_bar.ts_init` instead of `ts_event` for RTH/session calculations.
  - Compliance with **B2** (Lookback boundaries): Snapshots are calculated strictly using current/historical tracker states up to the decision time (`touch_bar.ts_init`).
  - Buffering & Replay: The `_minute_1s_buffer` retroactively attributes 1s bars to the correct 1m regime/RTH state upon 1m bar close. This resolves aggregation lag correctly without leaking future info.

### 3. `features/trackers/velocity.py`
- **Status**: Clean
- **Assessment**: Tracks velocity, acceleration, and jerk on 1s price streams. Calculations are strictly retrospective using historical slices from the prices deque (up to `p[-1]`), introducing no look-ahead bias.

### 4. `features/trackers/volume.py`
- **Status**: Clean
- **Assessment**: Tracks micro-volume dynamics, relative volume, trend, and price correlation on 1s bars.
  - Uses `v[-11:-1]` to calculate volume means/standard deviations, ensuring that the current volume `v[-1]` is normalized by strictly historical data.
  - Price-volume correlation over the last 10 seconds is properly aligned in time by reversing the `returns` list (`returns[::-1]`), matching the chronological order of `v_subset` (`v[-10:]`).

### 5. `features/trackers/pullback.py`
- **Status**: Clean
- **Assessment**: Calculates pullback features on 1s and 1m bar streams.
  - In 1s pullback calculations, all index slicing starts from `-1` or earlier and goes backward, preventing look-ahead.
  - In 1m pullback calculations, it receives the completed `bars_since_breach` list and calculates features on closed bars. No future-indexed attributes are accessed.

---

## Checklist Findings & Status

### A. NautilusTrader timestamp conventions
- **A1. Close-time indexing**: **Clean**. Uses `b.ts_init` for RTH and time features.
- **A2. BarType ts_init_delta**: **Clean**. Assumed at catalog building time.
- **A3. Current price lookup**: **Clean**. Uses `touch_bar` attributes inside `snapshot`.
- **A4. Timer/alert callbacks**: **N/A**. No timer or event callbacks used.
- **A5. Datetime conversion**: **Clean**. Correctly handles tz conversion to America/Chicago via `pytz.utc`.

### B. Feature engineering look-ahead
- **B1. Rolling computations**: **Clean**. Uses custom deques with strict backward lookups, no centered windows.
- **B2. Indicator look-ahead**: **Clean**. Indicators use only past and current data.
- **B3. Recursive indicators**: **Clean**. ATR and EMA are updated at 1m bar closes.
- **B4. Shift operations**: **Clean**. No `.shift(-N)` or negative lags.
- **B5. Forward-fill operations**: **Clean**. No `.ffill()` or `.bfill()` used.
- **B6. Joins/merges**: **Clean**. No joins or merges performed.
- **B7. Normalization window**: **Clean**. Uses `regime.atr.value` which is updated on the last closed 1m bar.
- **B8. Update/snapshot semantics**: **Clean**. Handled correctly in `FeatureEngine` and `FeatureCollector`.
- **B9. Timeframe Parameterization & Contract**: **Clean** (with 1 Note). Expectations regarding input cadence (1s/1m), window units, warmup requirements, and normalization are documented in class docstrings and implemented in code. Feature schema/metadata is registered in the central feature contract (`features/registry.py`).
  - > [!NOTE]
  > **Note (F-N1)**: Pullback 1m features in `features/registry.py` (e.g., `higher_lows_count_1m`) default to `source_timeframe='1s'` in their `FeatureDefinition` metadata, even though they evaluate macro pullback structure on 1m bars since breach. While this has no effect on calculation correctness (which is handled causally by `FeatureEngine` at touch-time), updating their metadata to `source_timeframe='1m'` would make the central feature contract more accurate.
- **B10. Multi-timeframe Reuse**: **Clean**. Timeframe wrappers (e.g., `MultiTimeframeFeatureLibrary`) reuse the exact same verified tracker logic without copy-pasted duplicates. Separate implementations inside `PullbackTracker` (1s vs 1m methods) are permitted and justified as their underlying mathematical and state-transition semantics genuinely differ.

### C. Label construction
- **C1-C4. Label construction**: **N/A**. No labels are constructed in these files.

### D. Train/serve skew
- **D1. Train/serve consistency**: **Clean**. Composed `FeatureEngine` is the single source of truth for both online execution and offline feature collection.
- **D2-D4. Inference & filters**: **Clean**. Feature ordering is canonical and deduplicated.

---

## Standalone Validation Summary
The RL feasibility study smoke test suite (`studies/rl_regime_feasibility/tests/test_smoke.py`) was run over a 5-day trading window with 335,030 1s bars and 67,952 observations. All 15 correctness invariants passed:
- **T01 episode_count**: PASSED (568 episodes detected)
- **T02 direction_valid**: PASSED (0 invalid direction values)
- **T03 obs_time_monotone**: PASSED (within each episode)
- **T04 step0_flip_zero**: PASSED (max|sec_since_flip|@step0=20.00s, tol=65s)
- **T05 sec_since_flip_nonneg**: PASSED (0 negative values)
- **T06 episode_max_30min**: PASSED (0 episodes exceed 30min)
- **T07 atr_positive**: PASSED (0 zero/neg ATR rows)
- **T08 progress_finite**: PASSED (0 inf values)
- **T09 max_progress_ge_current**: PASSED (0 max<current violations)
- **T10 max_adverse_nonneg**: PASSED (0 negative)
- **T11 range_nonneg**: PASSED (0 negative)
- **T12 regime_age_ge1**: PASSED (0 < 1)
- **T13 entry_after_obs**: PASSED (0/200 failures)
- **T14 stop_params_valid**: PASSED (0/200 invalid atr/flip_close)
- **T15 causal_no_violation**: PASSED (engine completed without CausalityViolation)
