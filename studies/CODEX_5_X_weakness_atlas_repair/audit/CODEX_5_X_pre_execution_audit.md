# CODEX 5.X — Batched Activity and Extended Comparator Pre-Execution Audit

**Scope:** `compute_activity_features_batched`, its integration into causal W4 construction, its scalar-equivalence test, and the extended 154-feature scalar/batch comparator. Prior sequence, ATR, parity, purge, freeze, and seal findings were checked for impact and remain valid.  
**Mode:** read-only source audit plus isolated test execution with bytecode generation and pytest cache disabled. Only this audit report was replaced. No atlas build, full-year comparator, model, result, or policy artifact was executed.  
**Status:** **PASS — PRE-EXECUTION AUDIT GATE SATISFIED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The vectorized activity implementation exactly preserves the inherited scalar formulas and their causal interval boundaries. It vectorizes only search bounds and caches medians by the complete state that determines them: `(left30, right)` for the sliding 30-minute median and `right` for fixed-count trailing medians. Counts, flip count, NaN behavior, ratios, and cross-family normalization match the scalar reference.

The extended full-year comparator now enforces and compares the complete ordered W4 matrix: 49 center/activity fields, 100 sequence fields, and 5 local fields, for 154 unique model inputs. Its strict row/key, NaN, tolerance, ATR, hashing, and fail-closed properties remain intact.

No label, future regime, checkpoint bar, or altered ATR definition enters the optimization.

## Activity interval semantics

For checkpoint `ts`, the implementation computes:

```text
right = searchsorted(end_times, ts, side="right")
left  = searchsorted(end_times, ts - window_minutes * 60 * NS, side="right")
count = right - left
```

This is identical to the inherited scalar formula and selects completed regimes whose end times lie in:

```text
(ts - window, ts]
```

The right bound admits a regime completed exactly at the checkpoint, which is causally available. The left bound excludes a regime ending exactly at the window's lower boundary, matching the prior implementation. Windows `(5, 15, 30, 60, 120)` are converted from minutes to nanoseconds with `window * 60 * NS`; checkpoint and regime end timestamps are both nanoseconds.

The implementation assumes the same sorted completed-regime history required by the scalar sequence/activity code. The local CODEX regime builder supplies that chronological history.

## Exact scalar formula correspondence

### Counts and flip count

- `activity_regime_count_{5,15,30,60,120}m` is exactly `right-left` for each window.
- `activity_flip_count_30m` is exactly the 30-minute regime count, as in the inherited scalar implementation.
- Counts are stored as floats to match the model frame's numeric feature representation; their values remain integral.

### Sliding 30-minute duration median

`activity_duration_median_30m` depends on both the moving lower bound and completed upper bound. The optimizer correctly caches by the full `(left30, right)` pair, not by `right` alone. Each unique non-empty pair computes:

```text
median(durations[left30:right])
```

An empty slice remains NaN. The inverse map restores each checkpoint's correct pair-specific result.

### Last 3/5/10 duration medians

`duration_median_last_{3,5,10}` depends only on the completed-regime count `right`, so caching by unique `right` is exact. For each N:

- `right >= N` uses `median(durations[right-N:right])`;
- insufficient history remains NaN.

No window lower bound is incorrectly applied to these fixed-count trailing features.

### Duration ratios

The two ratios retain the scalar equations and stabilizer:

```text
median_last_3 / (median_last_10 + 1e-8)
median_last_5 / (median_last_10 + 1e-8)
```

If required medians are unavailable, NumPy propagates NaN exactly as the scalar arithmetic does.

### Cross-family divisors

The shared divisor is exactly:

```text
max(activity_regime_count_30m, 1)
```

applied elementwise. The two cross-family fields divide the already-causal `center_spread_5m_30m` and `slope_30m_15m_aligned_atr` checkpoint-context values by that divisor. Zero activity therefore divides by one, matching the inherited scalar formula.

## Causality and integration

- Activity uses only completed regime `end_time <= checkpoint`.
- Rolling lower bounds refer only to past timestamps.
- Duration arrays contain completed regimes only.
- Cross-family inputs come from the last feature bar whose `ts_event < checkpoint`.
- The activity frame is index-aligned back to the checkpoint frame before sequence construction.
- No future label column is read.
- `BASE_FEATURES` and their order remain unchanged.

The optimization changes computation strategy only; it does not change feature availability or target chronology.

## Static test review

`test_batched_activity_features_equal_scalar_reference` independently reconstructs every optimized activity field with the inherited scalar loops and compares the full output matrix with `rtol=1e-12`, `atol=1e-12`, and paired NaNs.

The fixture uses regimes ending every 100 seconds and checkpoints at 550, 950, 1550, and 2050 seconds. Consequently:

- `right` advances across checkpoints;
- the 5-minute lower bound slides at every checkpoint;
- the 15-minute lower bound begins sliding;
- the 30-minute `(left,right)` cache state changes, including a nonzero lower bound at the final checkpoint;
- fixed-count medians transition from insufficient-history NaNs to available values;
- 30-minute divisors vary;
- cross-family numerators vary.

The test therefore exercises moving window bounds, both cache strategies, NaN propagation, ratios, and cross-family scaling rather than comparing only a constant completed-regime set.

The test-only NameError is closed: every nanosecond conversion in the activity fixture and independent scalar window formula now uses the imported repository constant `common.NS`. The fixture therefore reaches the batch computation and the independent scalar comparison rather than failing during setup.

The isolated suite was run with bytecode generation and pytest cache disabled:

```text
PYTHONDONTWRITEBYTECODE=1
python -m pytest -p no:cacheprovider studies/CODEX_5_X_weakness_atlas_repair/tests -q
25 passed in 1.38s
```

The passing activity test confirms the meaningful sliding-window comparison described above executes end to end.

## Extended comparator verification

The comparator imports the canonical ordered feature declarations and fails unless:

- `CENTER_FEATS`: exactly 49 unique fields;
- `SEQUENCE_FEATS`: exactly 100 unique fields;
- `LOCAL_FEATS`: exactly 5 unique fields;
- the concatenated list contains exactly 154 unique fields.

It compares all 154 fields for every paired row using the previously approved normalized table pairing, exact `(regime_start_ns, observation_time, direction)` keys, `RTOL=ATOL=1e-12`, and `equal_nan=True`. Per-column mismatch and maximum-difference maps now cover the full 154-field matrix.

The report persists ordered center, sequence, and local lists; all three counts; tolerances; scalar and batched artifact hashes; comparator source hash; and canonical feature-definition source hash. ATR validation remains independent and unchanged:

- `atr == atr_at_checkpoint` exactly;
- `atr_at_entry` and `atr_at_checkpoint` finite and positive.

PASS still requires zero key, feature-value, ATR-alias, and invalid-ATR mismatches, followed by an exception on any recorded FAIL.

## Prior-audit retention

- The 100 sequence fields and their seven dynamic formulas per K are unchanged.
- Activity concatenation preserves checkpoint index alignment before sequence batching.
- The explicit ATR fields and historical alias are unchanged.
- Local running features remain normalized by `atr_at_entry`.
- Sequence and center context continue to use the causal checkpoint ATR alias.
- The comparator's expanded field set strengthens coverage without weakening row pairing, tolerance, NaN, provenance, or fail-closed behavior.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The vectorized activity optimization and extended 154-feature comparator satisfy the mandatory pre-execution audit gate, and the corrected isolated suite passes. The full rebuild may now proceed subject to the existing causal, freeze, authorization, and 2026-seal chronology.
