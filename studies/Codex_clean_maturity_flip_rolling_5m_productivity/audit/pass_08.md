# Look-Ahead & Timestamp Audit — Pass 08

**Date:** 2026-08-14T19:40:01-05:00  
**Scope:** Pass-07 remediation in `implementation/collector.py`; unchanged runner; targeted delayed-label tests; frozen SPEC/config and directly used feature/regime state paths needed to resolve callback ordering  
**Scope hash:** `0ffda9626308bdc9de9d1c64f2368e0e6217abd11c57873b9f4fcd8fe27bae32`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 1
- Warning: 0
- Note: 1

Both Pass-07 endpoint defects are fixed. The changed parent-bar path still accepts low-quality 1m bars into the regime engine and target labels.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C-01 | Rejected 1s bar outside `(T,T+300s]` censored the row | FIXED | Rejected bars now invalidate by completed availability time (`collector.py:184-187`). Missing 1s availability ranges are exact (`collector.py:170-179`). A bar available at `T+301s` no longer intersects the target ending at `T+300s`. |
| C-02 | Missing final 1m close could be discovered after a negative was emitted | FIXED | Resolution was removed from 1s callbacks. `_on_1m` detects and invalidates a discontinuity first, updates/appends any current flip, then resolves (`collector.py:257-302`). The resolver requires a contiguous parent timestamp strictly later than the endpoint (`collector.py:342-357`). |

## Critical findings

### [G4/C2] `implementation/collector.py:257-279` — contiguous single-tick 1m bars remain valid target and indicator inputs

**Failure path:** A contiguous 1m parent bar with volume zero or one arrives inside `(T,T+300s]`. Because `_on_1m` checks only timestamp continuity, it feeds the bar's H/L/C into `RegimeEngine.update` and `FeatureEngine.update_1m`. A transition produced by that low-quality bar is appended as a real flip and later emits `flip_within_300s = 1`; even without a flip, subsequent ATR/EMA and regime-derived features retain the bad bar. The pending horizon is never marked unobservable.

**Smallest fix:** Apply the shared completed-bar quality gate to 1m before either engine update; treat a rejected parent as an unavailable interval, invalidate overlapping pending targets, and reset/suppress its dependent 1m state using the same fail-closed recovery as a missing parent.

## Warnings

- None.

## Notes

- Label computation remains wholly inside NT callbacks and mutates only the captured row's label. The established-regime gate and feature snapshot do not read pending or resolved target state.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1-A5, B1-B7, B9-B10, C1, C3, F1-F4, G1-G3 verified clean on the changed path.
- H1-H4 are not applicable: this study creates no orders or fills.
