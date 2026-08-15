# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-14T06:48:43.2323507-05:00  
**Scope:** 13 files: the changed aggregator, registry, and structural tracker; study collection, fitting, and economic-evaluation paths; and the two targeted tracker/boundary tests.  
**Scope hash:** `c8a486002ee55918cfb99ae9af7b311f33c3aee35eee4accd1a4b4a6c4bfd422`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** BLOCKED

## Summary

- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omit the bucket that just completed | FIXED | `implementation/collector.py:62-70` absorbs the eligible final 1s bar, calls `finalize_through(ts_init)`, and only then snapshots; `collectors/collector_v2/aggregator.py:117-135` publishes only existing buckets with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema are stamped with bar-open time | FIXED | `implementation/collector.py:53-61` passes `bar.ts_init` to `StructuralRegimeGeometryTracker.on_1s`; `ts_event` remains confined to the aggregator's explicit bucket identifier. |
| 3 | [G4] Single-tick bars feed structural and 5m indicators | NOT FIXED | `implementation/collector.py:56-63` excludes volume-one bars from tracker/aggregator state, but `implementation/collector.py:70` still passes that excluded bar's `c` into `snapshot`, contradicting the stated policy and changing current-price-derived features. |
| 4 | [B9] Registry metadata omits the load-bearing 1m-flip update | FIXED | `features/registry.py:615-618` now declares the combined `1s+1m+5m` source and `completed_1s_completed_5m_then_1m_flip` update anchor. |

## Critical findings

### [G4] `implementation/collector.py:56-70` — an excluded volume-one bar still supplies the snapshot price

**Failure path:** At a 5-second checkpoint with `bar.volume == 1`, `eligible` is false, so the bar does not update structural extrema, the 5m aggregator, or `_last_close`; nevertheless, `snapshot(ti, c, ...)` consumes that bar's close. If the single print differs from the last eligible close, it changes `structural_current_expansion_atr`, giveback, retention, both completed-5m distances, and the outside-range flag. The pass-01 source evidence established that volume-one bars occur in the study input, so affected rows enter fitting and 2024 OOS evaluation.

**Smallest fix:** At snapshots, use the last eligible completed-1s close (already stored in `_last_close`) rather than `c`, then recollect and reevaluate dependent artifacts.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

None newly referred; pass-01 referrals are not re-raised.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1-G3; H1-H4 verified clean or unchanged-clean on the inspected paths.
- Equal-time 5m publication now preserves completed-bar exclusion: `finalize_through` cannot publish a bucket whose declared close is after the decision timestamp.
- Labels remain separated from features, and the train/OOS split remains temporal (2021-2023 / 2024).
