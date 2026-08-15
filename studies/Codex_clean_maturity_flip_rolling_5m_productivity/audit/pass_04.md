# Look-Ahead & Timestamp Audit — Pass 04

**Date:** 2026-08-14T17:35:45-05:00  
**Scope:** Study SPEC/config/implementation/tests plus directly used feature-engine/tracker and collector-v2 state paths  
**Scope hash:** `68824bd1ce9d44db8c351549aba093a7e241c9cf26422782b899b9835b2e01f8`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 2
- Warning: 0
- Note: 2

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | G2/B9 missing 1s callback bypasses baseline-gap handling | NOT FIXED | `collector.py:154-157` now detects the timestamp gap and lines 191-193 suppress rows for 1800s, which fixes bounded count windows. However, regime/RTH cumulative baseline candidates are unbounded and remain incomplete after row emission resumes. |
| 2 | B2/B9 first regime receives pre-start buffered minute | FIXED | `features/engine.py:125-156` discards `buffered_minute` when no active regime existed; the first regime reset receives no pre-start bars. |
| 3 | F1/F2 flush precedes close-time RTH transition | FIXED | `features/engine.py:128-143` transitions `_rth_active` from `bar.ts_init` before attributing the completed minute. |

## Critical findings

### [G2, B9] Prior #1 NOT FIXED — missing-second corruption outlives the 1800s suppression window

**Failure path:** A missing callback sets `_last_rejected_feature_ns` and blocks rows for 1800 seconds, but feature state continues to advance without the missing observation. `OHLCVDeltaTracker.accumulate_regime_rth` maintains regime and RTH cumulative sums with no finite window (`features/trackers/ohlcv_delta.py:122-138`). If the regime or RTH session has not reset when suppression expires, emitted `regime_vol_sum`, `regime_volume_per_second`, `rth_vol_cum`, and related candidates omit the missing bar while elapsed time includes it. The baseline universe can therefore rank corrupted cumulative features after the nominal recovery period.

**Smallest fix:** Persist explicit regime/session gap-invalid flags and keep their cumulative features unavailable until the corresponding causal reset, while retaining the 1800-second suppression for bounded count windows.

### [F1, B9] `features/engine.py:125` — valid RTH minutes are discarded until the first regime initializes

**Failure path:** Before the first nonzero regime, `had_active_regime` is false. Although lines 128-135 correctly activate RTH from the parent-minute close, the completed `buffered_minute` is accumulated only when `had_active_regime` is true (lines 137-143). During ATR/regime warmup, every valid RTH minute is therefore discarded from RTH cumulative state as well as from regime state. Once the first regime appears, all later RTH features remain short the opening warmup volume/delta, changing baseline candidates for the rest of that session.

**Smallest fix:** Decouple RTH accumulation from regime accumulation: always attribute a valid completed minute to its close-time RTH state, while discarding it only from regime state until a causal regime start exists.

## Warnings

- None.

## Notes

- Exact rolling-window coverage, T-300 anchoring, and forming-5m exclusion remain clean.
- Observed incomplete 5m buckets reset registry, 5m recursive state, and structural geometry together.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1, A3-A5, B1, B3-B7, B10, C1, F2-F4, G4 verified clean on the implemented path.
- C2-C3 are not yet exercised; H1-H4 are not applicable.
