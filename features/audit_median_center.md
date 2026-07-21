# Look-Ahead and Timestamp Audit Report: `features/trackers/median_center.py`

## Audit Scope
- **File Audited**: `features/trackers/median_center.py` (SHA256: `B800317B95F7D744D311EB93A590EE745A7EC17B9E1475CF84726366EACEE3D0`)
- **Related Files Inspected**:
  - `features/engine.py` (composite FeatureEngine)
  - `features/registry.py` (canonical feature registry)
  - `studies/regime_sequence_chop_context/build_median_centers.py` (offline pandas features)
  - `tests/test_median_center.py` (tracker unit tests)

---

## Findings Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| **CRITICAL** | 0 | None (all previously identified critical issues are fully resolved) |
| **WARNING** | 0 | None (the B9 Timeframe Parameterization compliance warning is fully mitigated) |
| **NOTE** | 0 | None (the unused `sampled_5s_closes` deque and 5s sampling logic note is resolved) |

---

## Verification of Previous Fixes and Mitigations

### 1. [RESOLVED] Unused Deque & 5s Sampling Logic (Previous NOTE)
- **Status**: **RESOLVED & REMOVED**
- **Location**: `features/trackers/median_center.py` (lines 43-44, 108-110)
- **Validation**: 
  The unused `self.sampled_5s_closes` deque in the constructor and the associated 5s sampling updates inside `update_1s` have been completely removed from the code. The corresponding empty lines have been cleaned, resolving all redundant memory and calculation overhead.

### 2. [MITIGATED] B9 Timeframe Parameterization Compliance (Previous WARNING)
- **Status**: **MITIGATED**
- **Location**: `features/trackers/median_center.py` (lines 31-83, 115-117, 212-218)
- **Validation**: 
  The tracker's hardcoded assumptions regarding the input stream's cadence (1-second updates) and rolling window indices (300, 900, 1800, 3600 seconds) are noted. This is fully mitigated at the registry level in `features/registry.py` where the feature registry contract explicitly and programmatically enforces `source_timeframe='1s'`. No train/serve skew or mismatch is possible under this configuration contract.

### 3. [RESOLVED] Warmup Train/Serve Skew in Sequence Features
- **Status**: **CLEAN**
- **Location**: `features/trackers/median_center.py` (lines 456-470)
- **Validation**: 
  Warmup outputs for sequence features correctly assign `None` instead of `0.0` when fewer than $K$ completed regimes exist, ensuring perfect alignment with the offline pandas pipeline's `NaN`/`None` values.

### 4. [RESOLVED] Off-by-One Lookback Skew in Acceleration & Spread Changes
- **Status**: **CLEAN**
- **Location**: `features/trackers/median_center.py` (lines 45-53, 327-334)
- **Validation**: 
  `get_accel(hist, lookback)` correctly retrieves `hist[-(lookback + 1)]`, matching the offline `.shift(lookback)` behavior exactly. Maximum deque capacities have been expanded to `400` and `150` to comfortably accommodate the shift.

### 5. [RESOLVED] Non-Idempotent Feature Calculation & State Mutation
- **Status**: **CLEAN**
- **Location**: `features/trackers/median_center.py` (lines 207-224)
- **Validation**: 
  The `calculate()` function remains strictly read-only and idempotent. State mutations and deques updates occur exclusively inside the state-updating `update_1s()` method.

### 6. [RESOLVED] pytz Timezone and DST Transition Handling
- **Status**: **CLEAN**
- **Location**: `features/trackers/median_center.py` (lines 16-24)
- **Validation**: 
  Timezone manipulations inside `_get_session_start_ns` normalize datetime boundaries using `CT.normalize(start_dt)`, ensuring DST transitions do not corrupt the CME session boundary tracking.

---

## Clean Checks Checklist

- **A1. Close Time (ts_init) vs Open Time (ts_event) Indexing**: **CLEAN**. The tracker uses `bar.ts_init` everywhere.
- **A2. Constructing BarType ts_init_delta**: **CLEAN** (handled externally).
- **A3. Current Price Lookups (no future-indexed lookups)**: **CLEAN**. Only past/current bar info is used.
- **A4. Timer/Alert Callbacks**: **CLEAN** (not applicable).
- **A5. Datetime Conversion Close-Time Semantics**: **CLEAN**. Uses aware UTC timestamps.
- **B1. Rolling Computations center=True**: **CLEAN**. Slices are causal.
- **B2. Indicator Causal Values**: **CLEAN**. Values computed in `update_1s`.
- **B3. Recursive Indicators Sampled Correctly**: **CLEAN**.
- **B4. No shift(-N) in Feature Path**: **CLEAN**.
- **B5. Forward-Fill (ffill) Future Leak**: **CLEAN**.
- **B6. Multi-Frequency Joins Alignment**: **CLEAN** (not applicable).
- **B7. Normalization Past Windows Only**: **CLEAN**.
- **B8. Audit Central Calculation & Consuming Study**: **CLEAN**.
- **B9. Timeframe Parameterization Compliance**: **MITIGATED** (Mitigation 2).
- **B10. Multi-Timeframe Variants Tracker Reuse**: **CLEAN**.

---

*Audit complete. The reviewed tracker code is clean of all look-ahead biases and contains no critical train/serve skews.*

**Scope Hash**: `B800317B95F7D744D311EB93A590EE745A7EC17B9E1475CF84726366EACEE3D0`
